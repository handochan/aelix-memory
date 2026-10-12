"""A small fixed summary and topic index with correctness-first invalidation."""

import pytest

from aelix_memory.models import Draft
from aelix_memory.startup import StartupMemory


def test_capture_is_fixed_and_new_records_require_a_new_session(enabled, scope):
    first = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    summary = StartupMemory()
    summary.prepare((scope.id, "session", 1))
    summary.capture((first,))
    before = summary.render()
    later = enabled.add(scope, Draft("Installer", "Use uv.", "user-command"))
    summary.capture((first, later))
    assert summary.render() == before and later.id not in before
    summary.prepare((scope.id, "other-session", 1))
    summary.capture((first, later))
    assert later.id in summary.render()


def test_empty_snapshot_stays_empty_after_automatic_learning(enabled, scope):
    summary = StartupMemory()
    summary.prepare((scope.id, "session", 1))
    summary.capture(())
    before = summary.render()
    memory = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    summary.capture((memory,))
    assert summary.render() == before and "Initial project memory" in before


def test_pruning_does_not_silently_import_replacements(enabled, scope):
    old = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command", key="runner"))
    stable = enabled.add(scope, Draft("Installer", "Use uv.", "user-command"))
    summary = StartupMemory()
    summary.prepare((scope.id, "session", 1))
    summary.capture((old, stable))
    new = enabled.add(
        scope, Draft("Runner", "Use unittest.", "user-command", key="runner"), supersedes=old.id
    )
    summary.prune({new.id: new, stable.id: stable})
    assert old.id not in summary.render() and new.id not in summary.render()
    assert stable.id in summary.render()


@pytest.mark.parametrize("budget", [1024, 4096, 8192])
def test_utf8_bounds_escaping_and_topic_only_episode_details(budget, enabled, scope):
    memories = tuple(
        enabled.add(
            scope,
            Draft(f"<Episode {i}>", "SECRET DETAIL " * 400, "user-command", kind="episode"),
        )
        for i in range(18)
    )
    core = enabled.add(
        scope,
        Draft("<Runner>", "pytest & 테스트 " * 300, "user-command", kind="preference"),
    )
    summary = StartupMemory(budget=budget)
    summary.capture((*memories, core))
    rendered = summary.render()
    assert len(rendered.encode()) <= budget
    assert rendered.endswith("</aelix_memory>") and "SECRET DETAIL" not in rendered
    assert "<Runner>" not in rendered and len(summary.entries) <= 16
    if budget >= 4096:
        assert "&lt;Runner&gt;" in rendered and 'preview="true"' in rendered
        assert "<topic " in rendered


def test_revision_receipt_is_read_only_and_project_scoped(store, scope, tmp_path):
    from aelix_memory.scope import Scope

    assert store.revision_token(scope) == 0 and not store.home.exists()
    store.set_mode(scope, "on")
    store.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    revision = store.revision_token(scope)
    before = store.path.read_bytes()
    assert store.revision_token(scope) == revision and store.path.read_bytes() == before
    other = tmp_path / "other"
    other.mkdir()
    store.add(Scope.for_project(other), Draft("Installer", "Use uv.", "user-command"))
    assert store.revision_token(scope) == revision


def test_startup_candidates_filter_scope_status_time_and_priority_before_limit(
    enabled, scope, tmp_path, monkeypatch
):
    from aelix_memory.scope import Scope

    monkeypatch.setattr("aelix_memory.store.now_iso", lambda: "2026-10-12T00:00:00.000000+00:00")
    core = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command", kind="preference"))
    expired = enabled.add(
        scope,
        Draft(
            "Expired",
            "Old setting.",
            "user-command",
            kind="preference",
            expires_at="2026-10-12T00:01:00Z",
        ),
    )
    pending = enabled.add(
        scope,
        Draft("Pending", "Unapproved legacy.", "user-command", kind="preference"),
        review=True,
    )
    for index in range(70):
        enabled.add(scope, Draft(f"Episode {index}", "History.", "user-command", kind="episode"))
    other = tmp_path / "other"
    other.mkdir()
    outside = enabled.add(
        Scope.for_project(other), Draft("Other core", "Use uv.", "user-command", kind="preference")
    )
    monkeypatch.setattr("aelix_memory.store.now_iso", lambda: "2026-10-12T00:02:00.000000+00:00")
    before = enabled.path.read_bytes()
    selected = enabled.startup_memories(scope)
    assert len(selected) == 64 and selected[0].id == core.id
    assert not {expired.id, pending.id, outside.id}.intersection(m.id for m in selected)
    assert enabled.path.read_bytes() == before


@pytest.mark.parametrize("budget", [100, 8193])
def test_invalid_context_bounds_rejected(budget):
    with pytest.raises(ValueError):
        StartupMemory(budget=budget)


def test_usage_policy_is_fixed_idempotent_and_removable():
    from aelix_memory.startup import USAGE_POLICY, usage_prompt

    prompt = usage_prompt("Base instructions", enabled=True)
    assert usage_prompt(prompt, enabled=True) == prompt
    assert prompt.count(USAGE_POLICY) == 1
    assert usage_prompt(prompt, enabled=False) == "Base instructions"


def test_schema_one_startup_read_does_not_migrate(enabled, scope):
    import sqlite3

    memory = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    with sqlite3.connect(enabled.path) as connection:
        for column in ("evidence_quote", "source_role", "source_verification"):
            connection.execute(f"ALTER TABLE memories DROP COLUMN {column}")
        connection.execute("DROP TABLE configuration")
        connection.execute("PRAGMA user_version=1")
    before = enabled.path.read_bytes()
    assert enabled.startup_memories(scope)[0].id == memory.id
    assert enabled.path.read_bytes() == before
