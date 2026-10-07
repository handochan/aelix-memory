"""The model-free memory CLI. It never imports Aelix."""

from __future__ import annotations

import os
import sqlite3
import sys
import unicodedata

from .commands import parser, run
from .embeddings import LocalSentenceEmbedder
from .models import MemoryError
from .scope import Scope, memory_home
from .store import Store


def configured_store() -> Store:
    model = os.environ.get("AELIX_MEMORY_EMBEDDING_MODEL")
    return Store(memory_home(), embedder=LocalSentenceEmbedder(model) if model else None)


def terminal_text(value: str) -> str:
    return "".join(
        c for c in value if c in "\n\t" or unicodedata.category(c) not in {"Cc", "Cf", "Cs"}
    )


def main(argv: list[str] | None = None) -> int:
    # Pipes/files must carry portable UTF-8, including Windows legacy code pages.
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty() and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        args = parser().parse_args(argv)
        scope = Scope.for_project(args.project)
        output = run(configured_store(), scope, args)
    except MemoryError as exc:
        print("Memory: " + terminal_text(str(exc)), file=sys.stderr)
        return 2
    except (sqlite3.Error, OSError, ValueError):
        print("Memory unavailable: check the project path and user-owned storage.", file=sys.stderr)
        return 2
    print(terminal_text(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
