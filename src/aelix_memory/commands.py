"""Trusted user management shared by slash commands and the standalone CLI."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import cast

from .models import Draft, Kind, MemoryError, Mode
from .scope import Scope
from .store import Store


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise MemoryError(message)


def parser() -> Parser:
    command = Parser(
        prog="aelix-memory",
        description="Turn memory on/off globally; project inspection and export are optional.",
    )
    command.add_argument("--project", default=os.getcwd(), help="Project directory (default: cwd)")
    operations = command.add_subparsers(dest="command")
    for name in ("status", "on", "read", "off", "pending", "reindex", "help"):
        operations.add_parser(name)
    listing = operations.add_parser("list")
    listing.add_argument("--all", action="store_true")
    for name in ("show", "history", "approve", "discard", "forget"):
        operation = operations.add_parser(name)
        operation.add_argument("id")
    for name in ("remember", "update"):
        operation = operations.add_parser(name)
        if name == "update":
            operation.add_argument("id")
        operation.add_argument("text", nargs="+")
        operation.add_argument("--title")
        operation.add_argument("--kind", choices=("fact", "preference", "procedure", "episode"))
        operation.add_argument("--key")
        operation.add_argument("--tag", action="append", default=[])
        operation.add_argument("--source", default="user-command")
        operation.add_argument("--expires")
    search = operations.add_parser("search")
    search.add_argument("query", nargs="+")
    search.add_argument("--as-of")
    search.add_argument("--limit", type=int, default=5)
    export = operations.add_parser("export")
    export.add_argument("--output", type=Path)
    return command


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def run(store: Store, scope: Scope, args: argparse.Namespace) -> str:
    name = args.command or "status"
    if name == "help":
        return parser().format_help()
    if name in {"on", "read", "off"}:
        store.set_mode(scope, cast(Mode, name))
        return f"Memory {name.upper()} globally."
    if name == "status":
        mode = store.mode(scope)
        return _json(
            {
                "mode": mode,
                "setting_scope": "global",
                "knowledge_scope": "project",
                "project": str(scope.root),
                "scope": scope.id,
                "store_exists": store.path.exists(),
                "semantic": store.embedder is not None,
                "automatic_learning": mode == "on",
                "write_policy": "Automatic extraction after completed conversations; no per-memory approval.",
            }
        )
    if name in {"remember", "update"}:
        previous = store.get(scope, args.id) if name == "update" else None
        text = " ".join(args.text)
        draft = Draft(
            title=args.title or (previous.title if previous else text[:60]),
            content=text,
            source_ref=args.source,
            kind=cast(Kind, args.kind or (previous.kind if previous else "fact")),
            key=args.key if args.key is not None else previous.key if previous else None,
            tags=tuple(args.tag) if args.tag else previous.tags if previous else (),
            related_ids=previous.related_ids if previous else (),
            expires_at=args.expires,
        )
        return _json(
            store.add(scope, draft, supersedes=previous.id if previous else None).to_dict()
        )
    if name in {"list", "pending"}:
        status = "pending" if name == "pending" else "all" if args.all else "active"
        return _json([m.to_dict() for m in store.list(scope, status=status)])
    if name == "show":
        return _json(store.get(scope, args.id).to_dict())
    if name == "history":
        return _json([m.to_dict() for m in store.history(scope, args.id)])
    if name == "approve":
        return _json(store.approve(scope, args.id).to_dict())
    if name == "discard":
        store.discard(scope, args.id)
        return "Pending proposal discarded."
    if name == "forget":
        return f"Forgot {store.forget(scope, args.id)} record(s) in this revision family."
    if name == "search":
        result = store.search(
            scope, " ".join(args.query), limit=args.limit, as_of=args.as_of, agent=False
        )
        return _json({"hits": [h.to_dict() for h in result.hits], "warnings": result.warnings})
    if name == "reindex":
        return f"Indexed {store.reindex(scope)} current memories with the local embedding model."
    if name == "export":
        data = _json(store.export(scope)) + "\n"
        if args.output is None:
            return data
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(args.output, flags, 0o600)
        except FileExistsError as exc:
            raise MemoryError("Export destination already exists; choose a new file.") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
        return f"Exported to {args.output}."
    raise MemoryError("Unknown memory command. Use /memory help.")
