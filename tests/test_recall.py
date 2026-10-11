"""Recall keeps emitted bytes stable until correctness or bounds require removal."""

import pytest

from aelix_memory.models import Draft, Hit
from aelix_memory.recall import RecallLedger


def hit(memory):
    return Hit(memory, 1.0, ("lexical",))


def test_previous_blocks_are_stable_and_duplicate_records_are_not_repeated(enabled, scope):
    first = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    second = enabled.add(scope, Draft("Installer", "Use uv.", "user-command"))
    a, b = ("first", 0), ("second", 0)
    ledger = RecallLedger()
    ledger.prepare((scope.id, "session", 1), {a, b})
    ledger.append(a, (hit(first),))
    original = ledger.get(a)
    ledger.append(b, (hit(second), hit(first)))
    assert ledger.get(a) == original and first.id not in ledger.get(b)
    assert second.id in ledger.get(b)
    ledger.append(a, (hit(second),))
    assert ledger.get(a) == original


def test_epoch_changes_clear_all_snippets_and_missing_anchors_are_pruned(enabled, scope):
    memory = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    ledger = RecallLedger()
    a = ("first", 0)
    ledger.prepare((scope.id, "session", 1), {a})
    ledger.append(a, (hit(memory),))
    ledger.prepare((scope.id, "session", 1), set())
    assert ledger.size == 0 and not ledger.seen
    ledger.append(a, (hit(memory),))
    ledger.prepare((scope.id, "other-session", 1), {a})
    assert not ledger.blocks and not ledger.seen


def test_changed_or_deleted_record_invalidates_whole_block(enabled, scope):
    memory = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command", key="runner"))
    ledger = RecallLedger()
    a = ("first", 0)
    ledger.prepare((scope.id, "session", 1), {a})
    ledger.append(a, (hit(memory),))
    newer = enabled.add(
        scope, Draft("Runner", "Use unittest.", "user-command", key="runner"), supersedes=memory.id
    )
    ledger.prune({newer.id: newer})
    assert ledger.get(a) == "" and a not in ledger.seen


def test_aggregate_budget_and_anchor_count_are_bounded(enabled, scope):
    ledger = RecallLedger(budget=4096, block_budget=2048, anchors=3)
    anchors = set()
    for index in range(12):
        anchor = (str(index), 0)
        anchors.add(anchor)
        ledger.prepare((scope.id, "session", 1), anchors)
        memory = enabled.add(scope, Draft(f"Runner {index}", "pytest " * 500, "user-command"))
        ledger.append(anchor, (hit(memory),))
        assert ledger.size <= 4096 and len(ledger.seen) <= 3
    assert ledger.get(("0", 0)) == ""
    assert ledger.get(("11", 0))


def test_anchor_eviction_can_reemit_a_relevant_record_at_the_latest_turn(enabled, scope):
    memory = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    ledger = RecallLedger(anchors=2)
    a, b, c = ("a", 0), ("b", 0), ("c", 0)
    ledger.prepare((scope.id, "session", 1), {a, b, c})
    ledger.append(a, (hit(memory),))
    ledger.append(b, ())
    ledger.append(c, (hit(memory),))
    assert ledger.get(a) == "" and memory.id in ledger.get(c)
    assert len(ledger.seen) == 2


@pytest.mark.parametrize("args", [{"budget": 10}, {"anchors": 0}, {"block_budget": 50000}])
def test_invalid_context_bounds_rejected(args):
    with pytest.raises(ValueError):
        RecallLedger(**args)
