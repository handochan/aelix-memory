from concurrent.futures import ThreadPoolExecutor

import pytest

from aelix_memory.models import ConflictError, ConsentError, Draft, MemoryError
from aelix_memory.scope import Scope
from aelix_memory.store import Store


def draft(content="Use uv run pytest.", **kwargs):
    return Draft(
        title=kwargs.pop("title", "Test runner"),
        content=content,
        source_ref=kwargs.pop("source_ref", "docs/testing.md:12"),
        **kwargs,
    )


def test_off_never_creates_store_and_agent_cannot_enable(store, scope):
    assert store.mode(scope) == "off"
    assert store.list(scope) == []
    store.set_mode(scope, "off")
    with pytest.raises(ConsentError):
        store.add(scope, draft(), origin="agent")
    with pytest.raises(ConsentError):
        store.search(scope, "pytest")
    assert not store.home.exists()


def test_restart_read_mode_and_no_write_hash(enabled, scope):
    memory = enabled.add(scope, draft())
    enabled.set_mode(scope, "read")
    restarted = Store(enabled.home)
    before = enabled.path.read_bytes()
    assert restarted.mode(scope) == "read"
    assert restarted.search(scope, "pytest").hits[0].memory.id == memory.id
    assert restarted.get(scope, memory.id, agent=True) == memory
    with pytest.raises(ConsentError):
        restarted.add(scope, draft("new"), origin="agent")
    assert enabled.path.read_bytes() == before


def test_pending_is_not_evidence_and_approval_does_not_relabel(enabled, scope):
    proposal = enabled.add(
        scope, draft(), origin="agent", source_session="session-1", source_call="call-1"
    )
    assert not enabled.search(scope, "pytest").hits
    with pytest.raises(MemoryError):
        enabled.get(scope, proposal.id, agent=True)
    approved = enabled.approve(scope, proposal.id)
    assert approved.origin == "agent" and approved.source_session == "session-1"
    assert approved.source_call == "call-1"
    assert approved.to_dict()["source_verification"] == "declared"
    assert enabled.search(scope, "pytest").hits[0].memory == approved


def test_disable_blocks_all_agent_paths_but_keeps_user_management(enabled, scope):
    active = enabled.add(scope, draft())
    pending = enabled.add(scope, draft("proposal"), origin="agent")
    enabled.set_mode(scope, "off")
    for operation in (
        lambda: enabled.search(scope, "pytest"),
        lambda: enabled.get(scope, active.id, agent=True),
        lambda: enabled.add(scope, draft(), origin="agent"),
        lambda: enabled.approve(scope, pending.id),
    ):
        with pytest.raises(ConsentError):
            operation()
    assert enabled.get(scope, active.id) == active
    assert enabled.forget(scope, active.id) == 1


def test_scope_isolation_applies_to_every_lookup(enabled, scope, tmp_path):
    another = tmp_path / "other"
    another.mkdir()
    other = Scope.for_project(another)
    enabled.set_mode(other, "on")
    memory = enabled.add(scope, draft())
    assert not enabled.search(other, "pytest").hits
    assert enabled.list(other) == []
    for operation in (
        lambda: enabled.get(other, memory.id),
        lambda: enabled.history(other, memory.id),
        lambda: enabled.forget(other, memory.id),
        lambda: enabled.approve(other, memory.id),
    ):
        with pytest.raises(MemoryError):
            operation()
    with pytest.raises(MemoryError):
        enabled.add(other, draft(related_ids=(memory.id,)))
    assert enabled.get(scope, memory.id).id == memory.id


def test_subdirectories_and_symlink_alias_have_same_scope(scope, tmp_path):
    subdir = scope.root / "src"
    subdir.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(subdir, target_is_directory=True)
    assert Scope.for_project(subdir) == scope
    assert Scope.for_project(alias) == scope


def test_compare_and_swap_preserves_old_revision_and_rejects_stale_approval(enabled, scope):
    old = enabled.add(scope, draft("Use poetry.", key="test-runner"))
    pending = enabled.add(scope, draft(key="test-runner"), origin="agent", supersedes=old.id)
    current = enabled.add(scope, draft("Use hatch.", key="test-runner"), supersedes=old.id)
    with pytest.raises(ConflictError):
        enabled.approve(scope, pending.id)
    with pytest.raises(ConflictError):
        enabled.add(scope, draft(key="test-runner"), supersedes=old.id)
    assert enabled.search(scope, "hatch").hits[0].memory.id == current.id
    assert not enabled.search(scope, "poetry").hits
    assert enabled.get(scope, old.id).status == "superseded"
    assert len(enabled.history(scope, current.id)) == 3


def test_as_of_and_expiry_use_utc_instants(enabled, scope, monkeypatch):
    monkeypatch.setattr("aelix_memory.store.now_iso", lambda: "2026-10-08T00:00:00.000000+00:00")
    old = enabled.add(
        scope, draft("Use poetry.", key="runner", expires_at="2026-10-09T09:00:00+09:00")
    )
    monkeypatch.setattr("aelix_memory.store.now_iso", lambda: "2026-10-08T01:00:00.000000+00:00")
    new = enabled.add(
        scope, draft(key="runner", expires_at="2026-10-09T00:00:00Z"), supersedes=old.id
    )
    assert (
        enabled.search(scope, "poetry", as_of="2026-10-08T09:30:00+09:00").hits[0].memory.id
        == old.id
    )
    assert enabled.search(scope, "pytest", as_of="2026-10-08T01:00:00Z").hits[0].memory.id == new.id
    assert not enabled.search(scope, "pytest", as_of="2026-10-09T00:00:00Z").hits
    with pytest.raises(MemoryError):
        enabled.search(scope, "pytest", as_of="2026-10-08")


def test_forget_removes_whole_family_pending_and_search_plaintext(enabled, scope):
    marker = "UNIQUE_ERASURE_MARKER_928761"
    old = enabled.add(scope, draft(marker, key="secret-free-note"))
    current = enabled.add(
        scope, draft(marker + " updated", key="secret-free-note"), supersedes=old.id
    )
    enabled.add(
        scope,
        draft(marker + " proposal", key="secret-free-note"),
        origin="agent",
        supersedes=current.id,
    )
    assert enabled.forget(scope, current.id) == 3
    restarted = Store(enabled.home)
    assert restarted.list(scope, status="all") == []
    assert not restarted.search(scope, marker).hits
    assert marker.encode() not in enabled.path.read_bytes()


def test_parallel_proposals_persist_and_same_key_approval_has_one_winner(enabled, scope):
    def add(index):
        return Store(enabled.home).add(
            scope, draft(f"Lesson {index}", key="same-key"), origin="agent"
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        proposals = list(pool.map(add, range(20)))
    assert len(Store(enabled.home).list(scope, status="pending")) == 20

    def approve(proposal):
        try:
            return Store(enabled.home).approve(scope, proposal.id).id
        except ConflictError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        winners = list(pool.map(approve, proposals))
    assert sum(w is not None for w in winners) == 1
    assert len(Store(enabled.home).list(scope)) == 1


def test_deduplicate_retry_and_unicode_normalization(enabled, scope):
    first = enabled.add(scope, draft("메모리 사용", title="기억"), origin="agent")
    duplicate = enabled.add(scope, draft("메모리 사용", title="기억"), origin="agent")
    assert first.id == duplicate.id
    assert len(enabled.list(scope, status="pending")) == 1


@pytest.mark.parametrize(
    "value",
    ["sk-" + "a" * 30, "ghp_" + "a" * 30, "password=very-secret-value", "\x1b[2J", "a\u202eb"],
)
def test_credential_and_control_detection_leaves_no_memory(enabled, scope, value):
    with pytest.raises(MemoryError):
        enabled.add(scope, draft(value))
    assert enabled.list(scope, status="all") == []


def test_future_schema_is_not_modified(enabled, scope):
    import sqlite3

    with sqlite3.connect(enabled.path) as connection:
        connection.execute("PRAGMA user_version=999")
    before = enabled.path.read_bytes()
    with pytest.raises(MemoryError, match="Unsupported"):
        enabled.set_mode(scope, "on")
    assert enabled.path.read_bytes() == before


def test_storage_symlink_and_insecure_permissions_are_refused(store, scope, tmp_path):
    destination = tmp_path / "destination"
    destination.mkdir(mode=0o700)
    store.home.symlink_to(destination)
    with pytest.raises(MemoryError, match="symlink"):
        store.set_mode(scope, "on")
    assert not (destination / "memory.sqlite3").exists()


def test_approve_and_discard_are_explicit(enabled, scope):
    pending = enabled.add(scope, draft("proposal"), origin="agent")
    enabled.discard(scope, pending.id)
    with pytest.raises(MemoryError):
        enabled.approve(scope, pending.id)
    active = enabled.add(scope, draft())
    with pytest.raises(MemoryError):
        enabled.discard(scope, active.id)


def test_consent_revoked_between_proposal_attempts(enabled, scope):
    another = Store(enabled.home)
    another.set_mode(scope, "read")
    with pytest.raises(ConsentError):
        enabled.add(scope, draft("should not persist"), origin="agent")
    assert another.list(scope, status="pending") == []


def test_forget_key_deletes_unapproved_initial_proposals_too(enabled, scope):
    first = enabled.add(scope, draft("First value", key="runner"), origin="agent")
    second = enabled.add(scope, draft("Second value", key="runner"), origin="agent")
    enabled.approve(scope, first.id)
    enabled.forget(scope, first.id)
    with pytest.raises(MemoryError):
        enabled.approve(scope, second.id)
    assert enabled.list(scope, status="all") == []


def test_different_declared_sources_and_links_are_not_lost_as_duplicates(enabled, scope):
    first = enabled.add(scope, draft(source_ref="docs/testing.md:12"))
    second = enabled.add(scope, draft(source_ref="docs/testing.md:20"))
    assert first.id != second.id
    assert {m.source_ref for m in enabled.list(scope)} == {
        "docs/testing.md:12",
        "docs/testing.md:20",
    }
