"""Live automatic extraction and fresh-session recall using synthetic data only."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

from aelix_memory.models import now_iso
from aelix_memory.scope import Scope
from aelix_memory.store import Store

CAP = """from aelix_agent_core.harness.hooks import BeforeProviderPayloadResult
def setup(api):
    def cap(event, ctx):
        payload = dict(event.payload)
        payload.pop("max_completion_tokens", None)
        payload["max_tokens"] = 256
        return BeforeProviderPayloadResult(payload=payload)
    api.on("before_provider_payload", cap)
"""


def verify(provider: str, model: str) -> dict:
    cases = []
    with tempfile.TemporaryDirectory(prefix="aelix-memory-automatic-") as directory:
        root = Path(directory)
        project = root / "project"
        project.mkdir()
        scope = Scope.for_project(project)
        store = Store(root / "memory")
        helper = root / "cap.py"
        helper.write_text(CAP, encoding="utf-8")
        cli = Path(sys.executable).with_name("aelix.exe" if os.name == "nt" else "aelix")
        env = {**os.environ, "AELIX_MEMORY_HOME": str(store.home)}
        env.pop("AELIX_MEMORY_EMBEDDING_MODEL", None)

        def turn(label: str, prompt: str, expected: str) -> None:
            completed = subprocess.run(
                [
                    str(cli),
                    "--provider",
                    provider,
                    "--model",
                    model,
                    "--thinking",
                    "low",
                    "--no-tools",
                    "--no-agents",
                    "--no-skills",
                    "--no-context-files",
                    "--no-approve",
                    "--extension",
                    str(helper),
                    "--session-dir",
                    str(root / "sessions"),
                    "-p",
                    prompt,
                ],
                cwd=project,
                env=env,
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=180,
            )
            answer = completed.stdout.strip()
            cases.append(
                {
                    "case": label,
                    "answer": answer,
                    "expected": expected,
                    "exit_code": completed.returncode,
                    "passed": completed.returncode == 0 and answer == expected,
                }
            )

        turn(
            "off_does_not_learn",
            "In this project I always use pnpm as the package manager. Respond only ACK.",
            "ACK",
        )
        off_created_store = store.path.exists()
        store.set_mode(scope, "on")
        turn(
            "automatic_learning",
            "In this project I always use pnpm as the package manager. Respond only ACK.",
            "ACK",
        )
        learned = store.search(scope, "pnpm").hits
        captured = bool(learned and learned[0].memory.source_verification == "matched_quote")
        question = "Which package manager do I use in this project? Reply only with its name from memory, or UNKNOWN if no memory evidence is provided."
        turn("fresh_session_recall", question, "pnpm")
        turn(
            "automatic_correction",
            "The package manager preference changed: use npm in this project instead of pnpm. Respond only ACK.",
            "ACK",
        )
        turn("fresh_session_corrected_recall", question, "npm")
        history = store.list(scope, status="all")
        updated = bool(any(m.status == "superseded" for m in history))
        store.set_mode(scope, "off")
        turn("off_suppresses_recall", question, "UNKNOWN")
        sessions = [p.read_text(encoding="utf-8") for p in (root / "sessions").rglob("*.jsonl")]
        ephemeral = all("<aelix_memory" not in text for text in sessions)
        return {
            "at": now_iso(),
            "provider": provider,
            "model": model,
            "python": platform.python_version(),
            "synthetic_data_only": True,
            "manual_memory_writes": 0,
            "approvals": 0,
            "tools_disabled": True,
            "new_session_each_turn": True,
            "off_created_store": off_created_store,
            "automatically_extracted": captured,
            "correction_keeps_history": updated,
            "pending_records": len(store.list(scope, status="pending")),
            "recall_not_persisted": ephemeral,
            "cases": cases,
            "passed": all(c["passed"] for c in cases)
            and captured
            and updated
            and ephemeral
            and not off_created_store,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.provider, args.model)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
