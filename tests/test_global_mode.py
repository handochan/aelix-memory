import json
import os
import sqlite3
import subprocess
import sys

import pytest

from aelix_memory.models import ConsentError, Draft, MemoryError
from aelix_memory.scope import Scope
from aelix_memory.store import Store


def other_scope(tmp_path):
    project = tmp_path / "another-project"
    project.mkdir()
    return Scope.for_project(project)


def test_one_mode_choice_applies_to_every_project_and_fresh_process(store, scope, tmp_path):
    other = other_scope(tmp_path)
    assert store.mode(scope) == store.mode(other) == "off"
    store.set_mode(scope, "on")
    assert Store(store.home).mode(other) == "on"
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,sys; from pathlib import Path; from aelix_memory.store import Store; print(json.dumps(Store(Path(sys.argv[1])).global_mode()))",
            str(store.home),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    assert json.loads(completed.stdout) == "on"
    store.set_mode(other, "off")
    assert Store(store.home).mode(scope) == "off"


def test_global_enablement_does_not_share_project_knowledge(store, scope, tmp_path):
    other = other_scope(tmp_path)
    store.set_global_mode("on")
    first = store.add(
        scope, Draft("First project", "Use pnpm here.", "user-command", key="package-manager")
    )
    second = store.add(
        other, Draft("Second project", "Use npm here.", "user-command", key="package-manager")
    )
    assert store.search(scope, "pnpm").hits[0].memory.id == first.id
    assert store.search(other, "npm").hits[0].memory.id == second.id
    assert not store.search(other, "pnpm").hits
    with pytest.raises(MemoryError):
        store.get(other, first.id)


def test_off_on_in_other_project_process_revokes_jobs_everywhere(enabled, scope, tmp_path):
    other = other_scope(tmp_path)
    token = enabled.consent_token(scope)
    assert enabled.consent_token(other) == token
    for mode in ("off", "on"):
        completed = subprocess.run(
            [sys.executable, "-m", "aelix_memory", "--project", str(other.root), mode],
            env={**os.environ, "AELIX_MEMORY_HOME": str(enabled.home)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        assert completed.stdout.strip() == f"Memory {mode.upper()} globally."
    with pytest.raises(ConsentError):
        enabled.add(
            scope,
            Draft("Stale", "Old background result.", "user-source"),
            origin="agent",
            consent_token=token,
        )
    assert enabled.list(scope) == []


@pytest.mark.parametrize("mode", ["on", "read", "off"])
def test_legacy_latest_explicit_mode_becomes_global_without_read_writes(
    enabled, scope, tmp_path, mode
):
    other = other_scope(tmp_path)
    existing = enabled.add(scope, Draft("Existing", "Keep existing memory.", "user-source"))
    with sqlite3.connect(enabled.path) as conn:
        conn.execute("DROP TABLE configuration")
        conn.execute("PRAGMA user_version=2")
        conn.execute("INSERT OR IGNORE INTO scopes VALUES(?,?,'off')", (other.id, str(other.root)))
        conn.execute(
            "INSERT INTO audit(scope,action,memory_id,at) VALUES(?,?,NULL,'2026-10-08T00:00:00Z')",
            (other.id, f"mode:{mode}"),
        )
    before = enabled.path.read_bytes()
    assert enabled.mode(scope) == enabled.mode(other) == mode
    assert enabled.get(scope, existing.id).content == "Keep existing memory."
    assert enabled.path.read_bytes() == before
    enabled.set_mode(scope, "on")
    assert enabled.mode(other) == "on"
    with sqlite3.connect(enabled.path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert conn.execute("SELECT mode FROM configuration").fetchone()[0] == "on"


def test_default_global_off_status_creates_no_files(store, scope):
    assert store.global_mode() == "off"
    store.set_global_mode("off")
    assert not store.home.exists()
