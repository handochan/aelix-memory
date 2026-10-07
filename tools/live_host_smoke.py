"""Explicit live-provider smoke test with synthetic memory and capped output.

Uses the caller's normal host credentials, but stores only synthetic memory and
sessions in a disposable directory. It never changes the caller's memory mode.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

from aelix_memory.models import Draft, now_iso
from aelix_memory.scope import Scope
from aelix_memory.store import Store

CAP_EXTENSION = """from aelix_agent_core.harness.hooks import BeforeProviderPayloadResult
def setup(api):
    def cap(event, ctx):
        payload = dict(event.payload)
        payload.pop("max_completion_tokens", None)
        payload["max_tokens"] = 256
        return BeforeProviderPayloadResult(payload=payload)
    api.on("before_provider_payload", cap)
"""


def verify(provider: str, model: str) -> dict:
    results = []
    with tempfile.TemporaryDirectory(prefix="aelix-memory-live-") as directory:
        root = Path(directory)
        project = root / "project"
        project.mkdir()
        scope = Scope.for_project(project)
        store = Store(root / "memory")
        helper = root / "cap_output.py"
        helper.write_text(CAP_EXTENSION, encoding="utf-8")
        cli = Path(sys.executable).with_name("aelix.exe" if os.name == "nt" else "aelix")
        session_dir = root / "sessions"
        env = {**os.environ, "AELIX_MEMORY_HOME": str(store.home)}
        env.pop("AELIX_MEMORY_EMBEDDING_MODEL", None)
        prompt = "What is this project's release codename? Answer with only the codename from memory; if memory provides no evidence, answer UNKNOWN."
        for mode, expected in (("off", "UNKNOWN"), ("on", "LANTERN-7392"), ("off", "UNKNOWN")):
            store.set_mode(scope, mode)
            if mode == "on":
                store.add(
                    scope,
                    Draft(
                        "Release codename",
                        "The project release codename is LANTERN-7392.",
                        "user-command",
                        key="release-codename",
                    ),
                )
            completed = subprocess.run(
                [
                    str(cli),
                    "--provider",
                    provider,
                    "--model",
                    model,
                    "--thinking",
                    "low",
                    "--no-agents",
                    "--no-tools",
                    "--no-skills",
                    "--no-context-files",
                    "--no-approve",
                    "--extension",
                    str(helper),
                    "--session-dir",
                    str(session_dir),
                    "-p",
                    prompt,
                ],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=180,
            )
            answer = completed.stdout.strip()
            results.append(
                {
                    "mode": mode,
                    "expected": expected,
                    "answer": answer,
                    "exit_code": completed.returncode,
                    "passed": completed.returncode == 0 and answer == expected,
                }
            )
        contents = [p.read_text(encoding="utf-8") for p in session_dir.rglob("*.jsonl")]
        ephemeral = all(
            "<aelix_memory" not in text and "memory://" not in text for text in contents
        )
        return {
            "at": now_iso(),
            "provider": provider,
            "model": model,
            "python": platform.python_version(),
            "max_output_tokens": 256,
            "synthetic_fixture_only": True,
            "new_session_each_turn": True,
            "session_files": len(contents),
            "recall_not_persisted": ephemeral,
            "cases": results,
            "passed": all(r["passed"] for r in results) and ephemeral,
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
