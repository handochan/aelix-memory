"""A small labelled offline retrieval smoke evaluation, not LongMemEval or QA accuracy."""

from __future__ import annotations

import argparse
import json
import platform
import sqlite3
import tempfile
import time
from pathlib import Path

from aelix_memory.models import Draft
from aelix_memory.scope import Scope
from aelix_memory.store import Store

RECORDS = {
    "runner": ("Test runner", "Run the regression suite with uv run pytest.", ("testing",)),
    "language": (
        "Answer language",
        "Prefer Korean explanations; identifiers stay English.",
        ("language",),
    ),
    "database": (
        "Memory database",
        "Persist project memory in SQLite with transactional writes.",
        ("storage",),
    ),
    "queue": (
        "Pending session queue",
        "pending_session_writes preserves FIFO older then newer after dispatcher failure.",
        ("queue",),
    ),
    "korean": (
        "메모리 사용자 선택",
        "메모리는 사용자 승인 후 저장하며 프로젝트별로 격리합니다.",
        ("메모리",),
    ),
    "window": (
        "Window contract",
        "WindowDefinition resolves to zero or more actual window instances per wafer run.",
        ("analysis",),
    ),
    "unicode": (
        "Unicode paths",
        "Keep Unicode 파일 경로 and user-authored Korean content intact.",
        ("paths",),
    ),
    "permissions": (
        "Extension permissions",
        "The host permission gate blocks extension tools in plan mode.",
        ("permissions",),
    ),
    "privacy": (
        "Memory privacy",
        "Memory starts OFF; no raw transcript or tool output harvesting.",
        ("privacy",),
    ),
    "export": (
        "Memory export",
        "Export a portable JSON document; never overwrite an existing export file.",
        ("portability",),
    ),
    "distractor": (
        "Database migration",
        "The old experiment used PostgreSQL for a separate execution ledger.",
        ("ledger",),
    ),
}
CASES = [
    ("pytest regression suite", "runner"),
    ("uv runner", "runner"),
    ("testing", "runner"),
    ("Korean explanations", "language"),
    ("answer language", "language"),
    ("SQLite transactional", "database"),
    ("project storage SQLite", "database"),
    ("pending_session_writes", "queue"),
    ("FIFO dispatcher failure", "queue"),
    ("older newer queue", "queue"),
    ("메모리 승인", "korean"),
    ("사용자승인", "korean"),
    ("프로젝트별격리", "korean"),
    ("WindowDefinition", "window"),
    ("wafer window instances", "window"),
    ("Unicode paths", "unicode"),
    ("파일경로", "unicode"),
    ("plan permission gate", "permissions"),
    ("raw transcript harvesting", "privacy"),
    ("memory privacy OFF", "privacy"),
    ("portable JSON export", "export"),
    ("existing export file", "export"),
    ("PostgreSQL execution ledger", "distractor"),
    ("quantum volcanoes", None),
    ("mars crocodiles", None),
    ("neutrino spectroscopy", None),
]


def evaluate() -> dict:
    with tempfile.TemporaryDirectory(prefix="aelix-memory-eval-") as directory:
        root = Path(directory)
        project = root / "project"
        project.mkdir()
        scope = Scope.for_project(project)
        store = Store(root / "memory")
        store.set_mode(scope, "on")
        records = {
            key: store.add(scope, Draft(title, content, f"fixture:{key}", tags=tags)).id
            for key, (title, content, tags) in RECORDS.items()
        }
        durations = []
        results = []
        for query, expected in CASES:
            start = time.perf_counter()
            hits = store.search(scope, query).hits
            durations.append((time.perf_counter() - start) * 1000)
            ids = [hit.memory.id for hit in hits]
            results.append(
                {
                    "query": query,
                    "expected": expected,
                    "top1": bool(ids and ids[0] == records.get(expected)) if expected else not ids,
                    "recall5": records.get(expected) in ids if expected else not ids,
                }
            )
        positives = [r for r in results if r["expected"] is not None]
        negatives = [r for r in results if r["expected"] is None]
        return {
            "kind": "hand-labelled retrieval smoke; not answer quality or public benchmark",
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "channels": ["lexical", "cjk"],
            "records": len(records),
            "queries": len(results),
            "positive_top1": sum(r["top1"] for r in positives) / len(positives),
            "positive_recall5": sum(r["recall5"] for r in positives) / len(positives),
            "negative_abstention": sum(r["top1"] for r in negatives) / len(negatives),
            "p50_ms": sorted(durations)[len(durations) // 2],
            "p95_ms": sorted(durations)[int(len(durations) * 0.95)],
            "cases": results,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate()
    if args.output:
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps({k: v for k, v in result.items() if k != "cases"}, ensure_ascii=False, indent=2)
    )
    raise SystemExit(
        0 if result["positive_recall5"] == 1 and result["negative_abstention"] == 1 else 1
    )
