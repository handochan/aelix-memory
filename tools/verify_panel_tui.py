"""Actual POSIX PTY interaction with installed wheels; synthetic data, no model calls."""

from __future__ import annotations

import argparse
import errno
import json
import os
import select
import signal
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path


def verify(cli: Path, output: Path) -> None:
    import fcntl
    import pty
    import struct
    import termios

    import pyte

    root = Path(tempfile.mkdtemp(prefix="aelix-memory-panel-pty-"))
    home = root / "memory"
    env = {
        **os.environ,
        "TERM": "xterm-256color",
        "PI_OFFLINE": "1",
        "AELIX_CODING_AGENT_DIR": str(root / "agent"),
        "AELIX_MEMORY_HOME": str(home),
    }
    env.pop("AELIX_MEMORY_EMBEDDING_MODEL", None)
    env.pop("NO_COLOR", None)
    screens = []

    def mode():
        if not (home / "memory.sqlite3").exists():
            return "off"
        with sqlite3.connect((home / "memory.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
            return db.execute("SELECT mode FROM configuration").fetchone()[0]

    for index, (cols, rows) in enumerate(((80, 24), (120, 42))):
        project = root / f"project-{index}"
        project.mkdir()
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        process = subprocess.Popen(
            [
                str(cli),
                "--provider",
                "openrouter",
                "--model",
                "openai/gpt-5.4-mini",
                "--no-tools",
                "--no-agents",
                "--no-skills",
                "--no-context-files",
                "--no-approve",
                "--session-dir",
                str(root / "sessions"),
            ],
            cwd=project,
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
        )
        os.close(slave)
        screen = pyte.Screen(cols, rows)
        stream = pyte.Stream(screen)
        raw = bytearray()

        def pump(wait=0.05, master=master, raw=raw, stream=stream):
            if select.select([master], [], [], wait)[0]:
                try:
                    data = os.read(master, 65536)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        return
                    raise
                raw.extend(data)
                if b"\x1b[6n" in data:
                    os.write(master, b"\x1b[1;1R")
                stream.feed(data.decode("utf-8", errors="replace"))

        def until(predicate, label, pump=pump, process=process, screen=screen):
            deadline = time.monotonic() + 20
            while not predicate():
                pump()
                if not predicate() and (process.poll() is not None or time.monotonic() > deadline):
                    raise AssertionError(f"{label}\n" + "\n".join(screen.display))
            for _ in range(4):
                pump()

        def visible(text, screen=screen):
            return text in "\n".join(screen.display)

        def send(text, master=master):
            os.write(master, text.encode())

        def snapshot(label, screen=screen, cols=cols, rows=rows):
            lines = [line.rstrip() for line in screen.display if line.strip()]
            screens.append({"size": [cols, rows], "screen": label, "lines": lines})

        try:
            until(lambda: visible("aelix-memory"), "startup")
            if index == 0:
                assert not home.exists()
            send("/memory\r")
            until(lambda: visible("Learning mode:") and visible("Knowledge stays"), "panel")
            snapshot("opened")
            if index == 0:
                assert not home.exists(), "opening panel created storage"
                send("\x1b")
                until(lambda: visible("Memory panel closed."), "cancel")
                assert not home.exists()
                send("/memory\r")
                until(lambda: visible("Learning mode:"), "reopen")
                send("Memory:\r")
                until(lambda: mode() == "on" and visible("Memory: ON"), "global ON")
                send("Remember\r")
                until(lambda: visible("Memory title"), "title dialog")
                send("Panel runner\r")
                until(lambda: visible("Memory content"), "editor")
                send("Use uv run pytest.\x13")
                until(lambda: visible("Memory saved"), "manual save")
                send("\r")
                until(lambda: visible("Learning mode:"), "return to panel")
                send("Browse\r")
                until(lambda: visible("Panel runner"), "browse current project")
                send("\r")
                until(lambda: visible("View content and source"), "memory actions")
                snapshot("memory-actions")
                send("Edit\r")
                until(lambda: visible("Memory title"), "edit title")
                send("\r")
                until(lambda: visible("Memory content"), "edit content")
                send("\x01\x0bUse pytest.\x13")
                until(lambda: visible("Memory saved"), "unkeyed edit saved")
                send("\r")
                until(lambda: visible("Learning mode:"), "panel after edit")
                snapshot("enabled")
            else:
                assert visible("Memory: ON"), "global opt-in missing in another project"
                send("Browse\r")
                until(lambda: visible("No matching memories"), "project isolation")
                snapshot("isolated")
                send("\r")
                until(lambda: visible("Learning mode:"), "back to panel")
                other = root / "external-project"
                other.mkdir()
                python = cli.with_name("python.exe" if os.name == "nt" else "python")
                subprocess.run(
                    [str(python), "-m", "aelix_memory", "--project", str(other), "off"],
                    env=env,
                    capture_output=True,
                    check=True,
                )
                assert mode() == "off" and visible("Memory: ON")
                send("Memory:\r")
                until(lambda: visible("Memory: OFF"), "displayed intent")
                assert mode() == "off"
                snapshot("disabled")
            marker = len(raw)
            send("Close\r")
            until(
                lambda raw=raw, marker=marker, visible=visible: (
                    b"Memory panel closed." in bytes(raw[marker:])
                    and not visible("Knowledge stays")
                ),
                "close",
            )
            send("/quit\r")
            until(lambda process=process: process.poll() is not None, "clean quit")
            assert process.returncode == 0
        finally:
            (root / f"{index}-terminal.ansi").write_bytes(raw)
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            os.close(master)

    for session in (root / "sessions").rglob("*.jsonl"):
        entries = [json.loads(line) for line in session.read_text().splitlines() if line.strip()]
        assert not any(entry.get("type") == "message" for entry in entries), (
            "UI probe reached a model turn"
        )
    with sqlite3.connect((home / "memory.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        records = db.execute(
            "SELECT content,status,key FROM memories ORDER BY created_at"
        ).fetchall()
    assert records == [("Use uv run pytest.", "superseded", None), ("Use pytest.", "active", None)]
    result = {
        "passed": True,
        "synthetic_data_only": True,
        "model_requests": 0,
        "default_and_cancel_created_no_store": True,
        "global_across_projects": True,
        "project_isolation": True,
        "external_off_preserves_intent": True,
        "unkeyed_edit_and_history": True,
        "final_mode": mode(),
        "screens": screens,
    }
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "screens"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aelix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.aelix.resolve(), args.output)
