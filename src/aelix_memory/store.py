"""Transactional scoped memory. Agent paths never initialize a missing store."""

from __future__ import annotations

import contextlib
import json
import math
import os
import sqlite3
import stat
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Literal, cast

from .embeddings import Embedder, normalized
from .models import (
    MODES,
    ConflictError,
    ConsentError,
    Draft,
    Hit,
    Memory,
    MemoryError,
    Mode,
    SearchResult,
    clean_text,
    now_iso,
    timestamp,
)
from .retrieval import fuse, grams, match_query, words
from .scope import Scope

_SCHEMA = (
    "CREATE TABLE scopes (id TEXT PRIMARY KEY, root TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('off','read','on')))",
    """CREATE TABLE memories (
        id TEXT PRIMARY KEY, scope TEXT NOT NULL REFERENCES scopes(id), family_id TEXT NOT NULL,
        title TEXT NOT NULL, content TEXT NOT NULL, kind TEXT NOT NULL, key TEXT,
        tags TEXT NOT NULL, related_ids TEXT NOT NULL, source_ref TEXT NOT NULL,
        origin TEXT NOT NULL, source_session TEXT, source_call TEXT,
        status TEXT NOT NULL CHECK(status IN ('pending','active','superseded')),
        created_at TEXT NOT NULL, valid_from TEXT, valid_until TEXT, expires_at TEXT,
        supersedes TEXT, fingerprint TEXT NOT NULL)""",
    "CREATE UNIQUE INDEX active_keys ON memories(scope,key) WHERE status='active' AND key IS NOT NULL",
    "CREATE INDEX scope_status ON memories(scope,status)",
    "CREATE INDEX families ON memories(scope,family_id)",
    """CREATE VIRTUAL TABLE memory_lex USING fts5(
        title,content,tags,memory_id UNINDEXED,scope UNINDEXED, tokenize='unicode61')""",
    "CREATE VIRTUAL TABLE memory_cjk USING fts5(terms,memory_id UNINDEXED,scope UNINDEXED)",
    """CREATE TABLE vectors (
        memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
        model TEXT NOT NULL, dimension INTEGER NOT NULL, vector TEXT NOT NULL,
        PRIMARY KEY(memory_id,model))""",
    "CREATE TABLE audit (id INTEGER PRIMARY KEY, scope TEXT NOT NULL, action TEXT NOT NULL, memory_id TEXT, at TEXT NOT NULL)",
    """CREATE TRIGGER delete_search AFTER DELETE ON memories BEGIN
        DELETE FROM memory_lex WHERE memory_id=old.id;
        DELETE FROM memory_cjk WHERE memory_id=old.id;
        END""",
)
_FIELDS = tuple(Memory.__dataclass_fields__)


def _memory(row: sqlite3.Row) -> Memory:
    data = {name: row[name] for name in _FIELDS}
    data["tags"] = tuple(json.loads(data["tags"]))
    data["related_ids"] = tuple(json.loads(data["related_ids"]))
    return Memory(**data)


class Store:
    def __init__(self, home: Path, *, embedder: Embedder | None = None) -> None:
        self.home = home.absolute()
        self.path = self.home / "memory.sqlite3"
        self.embedder = embedder

    def _check_path(self) -> None:
        for path in (self.home, self.path):
            if path.is_symlink():
                raise MemoryError("Memory storage paths may not be symlinks.")
            if path.exists():
                info = path.stat()
                if hasattr(os, "getuid") and info.st_uid != os.getuid():
                    raise MemoryError("Memory storage must belong to the current user.")
                if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
                    raise MemoryError(
                        "Memory storage needs private permissions (directory 700, file 600)."
                    )
        if self.path.exists() and not self.path.is_file():
            raise MemoryError("Memory database path must be a regular file.")

    @contextlib.contextmanager
    def _connect(
        self, *, write: bool = False, create: bool = False
    ) -> Iterator[sqlite3.Connection | None]:
        if create:
            self.home.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._check_path()
        if not self.path.exists():
            if not create:
                yield None
                return
            flags = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(self.path, flags, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(fd)
        self._check_path()
        uri = self.path.as_uri() + ("?mode=rw" if write else "?mode=ro")
        connection = sqlite3.connect(uri, uri=True, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            if write:
                connection.execute("PRAGMA secure_delete=ON")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0 and create:
                if connection.execute("SELECT name FROM sqlite_master").fetchone():
                    raise MemoryError("Refusing an unversioned, non-empty memory database.")
                for statement in _SCHEMA:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version=1")
            elif version != 1:
                raise MemoryError("Unsupported memory schema; no data was changed.")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _mode(connection: sqlite3.Connection, scope: Scope) -> Mode:
        row = connection.execute("SELECT mode FROM scopes WHERE id=?", (scope.id,)).fetchone()
        return cast(Mode, row[0]) if row else "off"

    def mode(self, scope: Scope) -> Mode:
        with self._connect() as connection:
            return self._mode(connection, scope) if connection else "off"

    @staticmethod
    def _require(connection: sqlite3.Connection, scope: Scope, *, write: bool = False) -> None:
        mode = Store._mode(connection, scope)
        if mode == "off" or (write and mode != "on"):
            raise ConsentError("Memory access is disabled. Only the user can change /memory mode.")

    @staticmethod
    def _audit(
        connection: sqlite3.Connection, scope: Scope, action: str, mid: str | None = None
    ) -> None:
        connection.execute(
            "INSERT INTO audit(scope,action,memory_id,at) VALUES(?,?,?,?)",
            (scope.id, action, mid, now_iso()),
        )

    def set_mode(self, scope: Scope, mode: Mode) -> None:
        if mode not in MODES:
            raise MemoryError("Mode must be off, read or on.")
        # OFF on a missing store is a true no-op; the default already applies.
        with self._connect(write=True, create=mode != "off") as connection:
            if connection is None:
                return
            connection.execute(
                "INSERT INTO scopes(id,root,mode) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET mode=excluded.mode",
                (scope.id, str(scope.root), mode),
            )
            self._audit(connection, scope, "mode:" + mode)

    @staticmethod
    def _resolve(connection: sqlite3.Connection, scope: Scope, mid: str) -> Memory:
        if (
            not isinstance(mid, str)
            or not 8 <= len(mid) <= 32
            or any(c not in "0123456789abcdef" for c in mid)
        ):
            raise MemoryError(
                "Use a memory ID or an unambiguous prefix of at least 8 hex characters."
            )
        rows = connection.execute(
            "SELECT * FROM memories WHERE scope=? AND id LIKE ? LIMIT 2", (scope.id, mid + "%")
        ).fetchall()
        if len(rows) != 1:
            raise MemoryError("Memory ID is missing or ambiguous in this project.")
        return _memory(rows[0])

    def get(self, scope: Scope, mid: str, *, agent: bool = False) -> Memory:
        with self._connect() as connection:
            if connection is None:
                raise MemoryError("No memories saved in this project.")
            if agent:
                self._require(connection, scope)
            memory = self._resolve(connection, scope, mid)
            if agent and not self._visible(memory, now_iso()):
                raise MemoryError(
                    "Memory is pending, expired or superseded; it is not current evidence."
                )
            return memory

    @staticmethod
    def _visible(memory: Memory, at: str) -> bool:
        return (
            memory.status != "pending"
            and memory.valid_from is not None
            and memory.valid_from <= at
            and (memory.valid_until is None or memory.valid_until > at)
            and (memory.expires_at is None or memory.expires_at > at)
        )

    @staticmethod
    def _index(connection: sqlite3.Connection, memory: Memory) -> None:
        connection.execute(
            "INSERT INTO memory_lex(title,content,tags,memory_id,scope) VALUES(?,?,?,?,?)",
            (memory.title, memory.content, " ".join(memory.tags), memory.id, memory.scope),
        )
        connection.execute(
            "INSERT INTO memory_cjk(terms,memory_id,scope) VALUES(?,?,?)",
            (
                " ".join(grams(memory.title + " " + memory.content + " " + " ".join(memory.tags))),
                memory.id,
                memory.scope,
            ),
        )

    def add(
        self,
        scope: Scope,
        draft: Draft,
        *,
        origin: Literal["user", "agent"] = "user",
        supersedes: str | None = None,
        source_session: str | None = None,
        source_call: str | None = None,
    ) -> Memory:
        draft = draft.validated()
        if origin not in ("user", "agent"):
            raise MemoryError("origin must be user or agent.")
        source_session = (
            clean_text(source_session, "source_session", 200) if source_session else None
        )
        source_call = clean_text(source_call, "source_call", 200) if source_call else None
        with self._connect(write=True) as connection:
            if connection is None:
                raise ConsentError("Memory is OFF. Enable it explicitly first.")
            self._require(connection, scope, write=True)
            at = now_iso()
            if draft.expires_at and draft.expires_at <= at:
                raise MemoryError("expires_at must be in the future.")
            for related in draft.related_ids:
                if not self._visible(self._resolve(connection, scope, related), at):
                    raise MemoryError("Related IDs must refer to current memories in this project.")
            previous = self._resolve(connection, scope, supersedes) if supersedes else None
            if previous and (
                previous.status != "active" or previous.key is None or previous.key != draft.key
            ):
                raise ConflictError("Replacement requires the current revision and its exact key.")
            current = (
                connection.execute(
                    "SELECT * FROM memories WHERE scope=? AND key=? AND status='active'",
                    (scope.id, draft.key),
                ).fetchone()
                if draft.key
                else None
            )
            if current and (previous is None or current["id"] != previous.id):
                raise ConflictError("This key already exists; update using its current memory ID.")
            status = "pending" if origin == "agent" else "active"
            duplicate = connection.execute(
                "SELECT * FROM memories WHERE scope=? AND fingerprint=? AND status=? AND origin=? AND supersedes IS ?",
                (scope.id, draft.fingerprint, status, origin, previous.id if previous else None),
            ).fetchone()
            if duplicate:
                return _memory(duplicate)
            count = connection.execute(
                "SELECT count(*) FROM memories WHERE scope=?", (scope.id,)
            ).fetchone()[0]
            pending = connection.execute(
                "SELECT count(*) FROM memories WHERE scope=? AND status='pending'", (scope.id,)
            ).fetchone()[0]
            if count >= 10000 or (origin == "agent" and pending >= 100):
                raise MemoryError(
                    "Memory capacity reached; review or forget records before adding more."
                )
            mid = uuid.uuid4().hex
            pending_family = (
                connection.execute(
                    "SELECT family_id FROM memories WHERE scope=? AND key=? AND status='pending' ORDER BY created_at LIMIT 1",
                    (scope.id, draft.key),
                ).fetchone()
                if draft.key
                else None
            )
            memory = Memory(
                id=mid,
                scope=scope.id,
                family_id=previous.family_id
                if previous
                else pending_family[0]
                if pending_family
                else mid,
                title=draft.title,
                content=draft.content,
                kind=draft.kind,
                key=draft.key,
                tags=draft.tags,
                related_ids=draft.related_ids,
                source_ref=draft.source_ref,
                origin=origin,
                source_session=source_session,
                source_call=source_call,
                status=cast(Literal["pending", "active"], status),
                created_at=at,
                valid_from=at if status == "active" else None,
                valid_until=None,
                expires_at=draft.expires_at,
                supersedes=previous.id if previous else None,
            )
            if previous and status == "active":
                connection.execute(
                    "UPDATE memories SET status='superseded',valid_until=? WHERE id=? AND scope=?",
                    (at, previous.id, scope.id),
                )
            values = [
                json.dumps(getattr(memory, f), ensure_ascii=False)
                if f in {"tags", "related_ids"}
                else getattr(memory, f)
                for f in _FIELDS
            ]
            connection.execute(
                "INSERT INTO memories("
                + ",".join(_FIELDS)
                + ",fingerprint) VALUES("
                + ",".join("?" for _ in range(len(_FIELDS) + 1))
                + ")",
                (*values, draft.fingerprint),
            )
            if status == "active":
                self._index(connection, memory)
            self._audit(connection, scope, status, mid)
            return memory

    def approve(self, scope: Scope, mid: str) -> Memory:
        with self._connect(write=True) as connection:
            if connection is None:
                raise MemoryError("No pending memories.")
            self._require(connection, scope, write=True)
            memory = self._resolve(connection, scope, mid)
            if memory.status != "pending":
                raise MemoryError("Only a pending proposal can be approved.")
            at = now_iso()
            if memory.expires_at and memory.expires_at <= at:
                raise MemoryError("Proposal expired; discard it or propose a new memory.")
            for related in memory.related_ids:
                if not self._visible(self._resolve(connection, scope, related), at):
                    raise ConflictError("Related memory changed or expired; review a new proposal.")
            current = (
                connection.execute(
                    "SELECT id FROM memories WHERE scope=? AND key=? AND status='active'",
                    (scope.id, memory.key),
                ).fetchone()
                if memory.key
                else None
            )
            if memory.supersedes:
                if current is None or current[0] != memory.supersedes:
                    raise ConflictError(
                        "The previous revision changed; review a new proposal instead."
                    )
                connection.execute(
                    "UPDATE memories SET status='superseded',valid_until=? WHERE id=? AND scope=?",
                    (at, memory.supersedes, scope.id),
                )
            elif current:
                raise ConflictError(
                    "A memory with this key was added since the proposal; review an update."
                )
            connection.execute(
                "UPDATE memories SET status='active',valid_from=? WHERE id=? AND scope=?",
                (at, memory.id, scope.id),
            )
            approved = self._resolve(connection, scope, memory.id)
            self._index(connection, approved)
            self._audit(connection, scope, "approve", memory.id)
            return approved

    def list(self, scope: Scope, *, status: str = "active", limit: int = 50) -> list[Memory]:
        if status not in {"active", "pending", "all"} or not 1 <= limit <= 10000:
            raise MemoryError("Invalid list status or limit.")
        with self._connect() as connection:
            if connection is None:
                return []
            clause = "" if status == "all" else " AND status=?"
            params = (scope.id, limit) if status == "all" else (scope.id, status, limit)
            return [
                _memory(row)
                for row in connection.execute(
                    "SELECT * FROM memories WHERE scope=?"
                    + clause
                    + " ORDER BY created_at DESC,id LIMIT ?",
                    params,
                )
            ]

    def history(self, scope: Scope, mid: str) -> list[Memory]:
        with self._connect() as connection:
            if connection is None:
                raise MemoryError("No memories saved.")
            memory = self._resolve(connection, scope, mid)
            return [
                _memory(row)
                for row in connection.execute(
                    "SELECT * FROM memories WHERE scope=? AND family_id=? ORDER BY created_at,id",
                    (scope.id, memory.family_id),
                )
            ]

    def discard(self, scope: Scope, mid: str) -> None:
        with self._connect(write=True) as connection:
            if connection is None:
                raise MemoryError("No pending memories.")
            memory = self._resolve(connection, scope, mid)
            if memory.status != "pending":
                raise MemoryError(
                    "Only pending proposals can be discarded; use forget for saved memory."
                )
            connection.execute("DELETE FROM memories WHERE scope=? AND id=?", (scope.id, memory.id))
            self._audit(connection, scope, "discard", memory.id)
        self._compact()

    def forget(self, scope: Scope, mid: str) -> int:
        with self._connect(write=True) as connection:
            if connection is None:
                raise MemoryError("No memories saved.")
            memory = self._resolve(connection, scope, mid)
            count = connection.execute(
                "DELETE FROM memories WHERE scope=? AND (family_id=? OR (key IS NOT NULL AND key=?))",
                (scope.id, memory.family_id, memory.key),
            ).rowcount
            self._audit(connection, scope, "forget-family", memory.id)
            # Remove obsolete terms from FTS segment history, not just query visibility.
            connection.execute("INSERT INTO memory_lex(memory_lex) VALUES('rebuild')")
            connection.execute("INSERT INTO memory_cjk(memory_cjk) VALUES('rebuild')")
        self._compact()
        return count

    def _compact(self) -> None:
        self._check_path()
        with contextlib.closing(
            sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=10)
        ) as connection:
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("VACUUM")

    def export(self, scope: Scope) -> dict:
        return {
            "schema_version": 1,
            "project": str(scope.root),
            "scope": scope.id,
            "exported_at": now_iso(),
            "memories": [m.to_dict() for m in self.list(scope, status="all", limit=10000)],
        }

    def search(
        self,
        scope: Scope,
        query: str,
        *,
        limit: int = 5,
        as_of: str | None = None,
        agent: bool = True,
    ) -> SearchResult:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise MemoryError("Search limit must be between 1 and 20.")
        query = clean_text(query, "query", 2000)
        at = timestamp(as_of) if as_of else now_iso()
        warnings: list[str] = []
        channels: dict[str, list[str]] = {}
        semantic_query = None
        if self.embedder:
            if agent and self.mode(scope) == "off":
                raise ConsentError("Memory is OFF.")
            # Hash/load/encode outside a read transaction so OFF and deletion stay responsive.
            try:
                model = clean_text(self.embedder.fingerprint, "model fingerprint", 200)
                with self._connect() as probe:
                    has_vectors = (
                        probe is not None
                        and probe.execute(
                            "SELECT 1 FROM vectors v JOIN memories m ON m.id=v.memory_id WHERE m.scope=? AND v.model=? AND m.status!='pending' AND m.valid_from<=? AND (m.valid_until IS NULL OR m.valid_until>?) AND (m.expires_at IS NULL OR m.expires_at>?) LIMIT 1",
                            (scope.id, model, at, at, at),
                        ).fetchone()
                        is not None
                    )
                if has_vectors:
                    encoded = self.embedder.encode([query])
                    if len(encoded) != 1:
                        raise MemoryError(
                            "Embedding provider returned the wrong number of vectors."
                        )
                    semantic_query = (model, normalized(encoded[0]))
                elif self.list(scope):
                    warnings.append(
                        "Semantic index is unavailable for this model; run /memory reindex."
                    )
            except Exception:
                warnings.append("Semantic retrieval unavailable; lexical/CJK retrieval was used.")
        with self._connect() as connection:
            if connection is None:
                if agent:
                    raise ConsentError("Memory is OFF.")
                return SearchResult()
            if agent:
                self._require(connection, scope)
            visibility = "m.scope=? AND m.status!='pending' AND m.valid_from<=? AND (m.valid_until IS NULL OR m.valid_until>?) AND (m.expires_at IS NULL OR m.expires_at>?)"
            args = (scope.id, at, at, at)
            for name, table, tokens in (
                ("lexical", "memory_lex", words(query)),
                ("cjk", "memory_cjk", grams(query)),
            ):
                match = match_query(tokens)
                if match:
                    # Table names are fixed code constants, never user values.
                    rows = connection.execute(
                        f"SELECT m.id FROM {table} JOIN memories m ON m.id={table}.memory_id WHERE {table} MATCH ? AND {visibility} ORDER BY bm25({table}),m.created_at DESC,m.id LIMIT 80",
                        (match, *args),
                    ).fetchall()
                    channels[name] = [row[0] for row in rows]
            if semantic_query:
                try:
                    model, vector = semantic_query
                    channels["semantic"] = self._semantic(
                        connection, model, vector, visibility, args
                    )
                except Exception:
                    # Do not expose model/file exceptions, which may include private paths/text.
                    warnings.append(
                        "Semantic retrieval unavailable; lexical/CJK retrieval was used."
                    )
            hits = tuple(
                Hit(self._resolve(connection, scope, mid), score, matched)
                for mid, score, matched in fuse(channels)[:limit]
            )
            return SearchResult(hits, tuple(warnings))

    def _semantic(
        self,
        connection: sqlite3.Connection,
        model: str,
        vector: list[float],
        visibility: str,
        args: tuple[str, ...],
    ) -> list[str]:
        assert self.embedder is not None
        if (
            connection.execute(
                "SELECT count(*) FROM memories m WHERE " + visibility, args
            ).fetchone()[0]
            > 5000
        ):
            raise MemoryError("Semantic scan capacity exceeded.")
        rows = connection.execute(
            "SELECT v.memory_id,v.dimension,v.vector FROM vectors v JOIN memories m ON m.id=v.memory_id WHERE v.model=? AND "
            + visibility,
            (model, *args),
        ).fetchall()
        if not rows:
            return []
        scored = []
        for row in rows:
            stored = normalized(json.loads(row["vector"]))
            if row["dimension"] != len(vector) or len(stored) != len(vector):
                raise MemoryError("Embedding dimension mismatch; reindex with the current model.")
            similarity = math.fsum(a * b for a, b in zip(stored, vector, strict=True))
            if similarity >= 0.45:
                scored.append((similarity, row["memory_id"]))
        return [mid for _, mid in sorted(scored, key=lambda pair: (-pair[0], pair[1]))[:80]]

    def reindex(self, scope: Scope) -> int:
        if self.embedder is None:
            raise MemoryError(
                "Set AELIX_MEMORY_EMBEDDING_MODEL to a provisioned local model first."
            )
        if self.mode(scope) != "on":
            raise ConsentError("Enable ON before indexing memory.")
        records = [m for m in self.list(scope, limit=10000) if self._visible(m, now_iso())]
        if len(records) > 5000:
            raise MemoryError(
                "Semantic indexing supports at most 5000 active memories per project."
            )
        model = clean_text(self.embedder.fingerprint, "model fingerprint", 200)
        raw = self.embedder.encode([m.title + "\n" + m.content for m in records]) if records else []
        if len(raw) != len(records):
            raise MemoryError("Embedding provider returned the wrong number of vectors.")
        vectors = [normalized(v) for v in raw]
        if len({len(v) for v in vectors}) > 1:
            raise MemoryError("Embedding dimensions must be consistent.")
        with self._connect(write=True) as connection:
            assert connection is not None
            self._require(connection, scope, write=True)
            # Recheck that every record is still current after the slow embedding step.
            for memory in records:
                if not self._visible(self._resolve(connection, scope, memory.id), now_iso()):
                    raise ConflictError("Memory changed while embedding; retry reindex.")
            for memory, vector in zip(records, vectors, strict=True):
                connection.execute(
                    "INSERT OR REPLACE INTO vectors(memory_id,model,dimension,vector) VALUES(?,?,?,?)",
                    (memory.id, model, len(vector), json.dumps(vector)),
                )
            self._audit(connection, scope, "reindex")
        return len(records)
