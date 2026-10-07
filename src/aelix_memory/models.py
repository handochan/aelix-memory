"""Bounded memory records and explicit provenance. No inferred fact is labelled observed."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

Mode = Literal["off", "read", "on"]
Kind = Literal["fact", "preference", "procedure", "episode"]
MODES = ("off", "read", "on")
KINDS = ("fact", "preference", "procedure", "episode")


class MemoryError(ValueError):
    """An actionable memory contract error (never a raw storage exception)."""


class ConsentError(MemoryError):
    pass


class ConflictError(MemoryError):
    pass


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise MemoryError("Use an ISO 8601 timestamp with an explicit timezone.") from exc
    if parsed.tzinfo is None:
        raise MemoryError("A timestamp must include a timezone.")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


# Defence in depth, not a comprehensive secret detector. Never interpolate a match in an error.
_SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    r"|\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"
    r"|\bAKIA[A-Z0-9]{16}\b"
    r"|\b(?:api[_-]?key|password|passwd|secret|access[_-]?token|authorization)\s*[:=]\s*[\"']?\S{8,}",
    re.IGNORECASE,
)


def clean_text(value: str, name: str, max_bytes: int) -> str:
    if not isinstance(value, str):
        raise MemoryError(f"{name} must be text.")
    value = unicodedata.normalize("NFC", value).strip()
    if not value or len(value.encode("utf-8")) > max_bytes:
        raise MemoryError(f"{name} must be non-empty and at most {max_bytes} UTF-8 bytes.")
    if any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} and c not in "\n\t" for c in value):
        raise MemoryError(f"{name} contains unsupported control characters.")
    if _SECRET.search(value):
        raise MemoryError("Possible credential detected; remove it before saving memory.")
    return value


def contains_secret(value: str) -> bool:
    """A conservative signal for excluding an exchange before automatic extraction."""
    return bool(_SECRET.search(value))


@dataclass(frozen=True)
class Draft:
    title: str
    content: str
    source_ref: str
    kind: Kind = "fact"
    key: str | None = None
    tags: tuple[str, ...] = ()
    related_ids: tuple[str, ...] = ()
    expires_at: str | None = None

    def validated(self) -> Draft:
        if self.kind not in KINDS:
            raise MemoryError(f"kind must be one of {', '.join(KINDS)}.")
        if len(self.tags) > 16 or len(self.related_ids) > 10:
            raise MemoryError("Use at most 16 tags and 10 related memory IDs.")
        return Draft(
            title=clean_text(self.title, "title", 240),
            content=clean_text(self.content, "content", 8000),
            source_ref=clean_text(self.source_ref, "source_ref", 1000),
            kind=self.kind,
            key=clean_text(self.key, "key", 200) if self.key is not None else None,
            tags=tuple(dict.fromkeys(clean_text(t, "tag", 80) for t in self.tags)),
            related_ids=tuple(
                dict.fromkeys(clean_text(t, "related ID", 32) for t in self.related_ids)
            ),
            expires_at=timestamp(self.expires_at) if self.expires_at else None,
        )

    @property
    def fingerprint(self) -> str:
        data = [
            self.title,
            self.content,
            self.kind,
            self.key,
            sorted(self.tags),
            self.source_ref,
            sorted(self.related_ids),
            self.expires_at,
        ]
        return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class Memory:
    id: str
    scope: str
    family_id: str
    title: str
    content: str
    kind: Kind
    key: str | None
    tags: tuple[str, ...]
    related_ids: tuple[str, ...]
    source_ref: str
    origin: Literal["user", "agent"]
    source_session: str | None
    source_call: str | None
    status: Literal["pending", "active", "superseded"]
    created_at: str
    valid_from: str | None
    valid_until: str | None
    expires_at: str | None
    supersedes: str | None
    evidence_quote: str | None = None
    source_role: Literal["user", "assistant"] | None = None
    source_verification: Literal["declared", "matched_quote"] = "declared"

    @property
    def citation(self) -> str:
        return f"memory://{self.scope}/{self.id}"

    def to_dict(self) -> dict:
        return {**asdict(self), "citation": self.citation}


@dataclass(frozen=True)
class Hit:
    memory: Memory
    score: float
    channels: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"memory": self.memory.to_dict(), "score": self.score, "channels": self.channels}


@dataclass(frozen=True)
class SearchResult:
    hits: tuple[Hit, ...] = ()
    warnings: tuple[str, ...] = ()
