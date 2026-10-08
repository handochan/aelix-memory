import asyncio
import json
import threading

import pytest

from aelix_memory.learning import Exchange, Learner, Source, parse_extraction, sources_for
from aelix_memory.models import ConsentError, Draft, MemoryError


def exchange(enabled, scope, text="I always use pnpm in this project.", turn="turn-1"):
    return Exchange(
        scope,
        "session-1",
        turn,
        enabled.consent_token(scope),
        (Source("user", text), Source("assistant", "Understood.")),
        enabled.current_keys(scope),
    )


def payload(quote="I always use pnpm in this project.", **overrides):
    return json.dumps(
        {
            "memories": [
                {
                    "title": "Package manager",
                    "key": "package-manager",
                    "kind": "preference",
                    "quote": quote,
                    "source_index": 0,
                    **overrides,
                }
            ]
        }
    )


class Extractor:
    def __init__(self):
        self.calls = 0

    async def extract(self, event, model, registry):
        self.calls += 1
        return parse_extraction(payload(event.sources[0].text), event)


async def test_automatic_learning_creates_active_grounded_memory_without_approval(enabled, scope):
    extractor = Extractor()
    learner = Learner(enabled, extractor=extractor)
    event = exchange(enabled, scope)
    learner.start(event, None, None)
    await learner.drain()
    memory = enabled.search(scope, "pnpm").hits[0].memory
    assert memory.status == "active" and memory.origin == "agent"
    assert memory.source_role == "user" and memory.evidence_quote == event.sources[0].text
    assert memory.source_verification == "matched_quote"
    assert memory.source_session == "session-1" and memory.source_call == "turn-1"
    assert enabled.list(scope, status="pending") == []
    learner.start(event, None, None)
    await learner.drain()
    assert extractor.calls == 1


async def test_corrections_and_identical_repeated_facts_are_automatic(enabled, scope):
    learner = Learner(enabled, extractor=Extractor())
    for turn in ("first", "repeated"):
        learner.start(exchange(enabled, scope, turn=turn), None, None)
        await learner.drain()
    assert len(enabled.list(scope, status="all")) == 1
    learner.start(
        exchange(enabled, scope, "Actually use npm in this project.", "correction"), None, None
    )
    await learner.drain()
    assert not enabled.search(scope, "pnpm").hits
    assert (
        enabled.search(scope, "npm").hits[0].memory.content == "Actually use npm in this project."
    )
    assert len(enabled.list(scope, status="all")) == 2


@pytest.mark.parametrize(
    "text",
    [
        "Do not remember this conversation.",
        "이 내용은 저장하지 마세요.",
        "hello",
        "password=super-secret-value",
        "sk-" + "a" * 24,
    ],
)
def test_private_and_trivial_exchanges_never_reach_extractor(text):
    assert sources_for(text, "Understood.") == ()


@pytest.mark.parametrize(
    "data", ["invalid", '{"memories":{},"other":1}', '{"memories":[{"quote":"invented"}]}']
)
def test_malformed_or_ungrounded_output_never_creates_a_note(enabled, scope, data):
    try:
        notes = parse_extraction(data, exchange(enabled, scope))
    except MemoryError:
        notes = ()
    assert notes == ()
    assert enabled.list(scope) == []


def test_invented_quotes_and_external_source_ids_are_rejected(enabled, scope):
    event = exchange(enabled, scope)
    assert parse_extraction(payload("I always use npm."), event) == ()
    assert parse_extraction(payload(source_index=99), event) == ()
    assert parse_extraction(payload(source_index=True), event) == ()
    assert parse_extraction(payload(source_ref="invented-file"), event) == ()
    assert parse_extraction(payload(kind="unknown"), event) == ()


async def test_off_read_and_off_on_cycle_revoke_existing_job_without_writes(enabled, scope):
    started, finish = asyncio.Event(), asyncio.Event()

    class Waiting(Extractor):
        async def extract(self, event, model, registry):
            started.set()
            await finish.wait()
            return await super().extract(event, model, registry)

    learner = Learner(enabled, extractor=Waiting())
    learner.start(exchange(enabled, scope), None, None)
    await started.wait()
    enabled.set_mode(scope, "off")
    enabled.set_mode(scope, "on")
    finish.set()
    await learner.drain()
    assert enabled.list(scope) == []
    for mode in ("read", "off"):
        enabled.set_mode(scope, mode)
        e = exchange(enabled, scope, turn=mode)
        extractor = Extractor()
        other = Learner(enabled, extractor=extractor)
        other.start(e, None, None)
        await other.drain()
        assert extractor.calls == 0 and enabled.list(scope) == []


async def test_cancelled_or_timed_out_extraction_never_persists(enabled, scope):
    class Slow(Extractor):
        async def extract(self, event, model, registry):
            await asyncio.sleep(1)
            return await super().extract(event, model, registry)

    learner = Learner(enabled, extractor=Slow(), timeout=0.02)
    learner.start(exchange(enabled, scope), None, None)
    await learner.drain()
    assert learner.state == "unavailable" and enabled.list(scope) == []
    learner = Learner(enabled, extractor=Slow())
    learner.start(exchange(enabled, scope, turn="cancel"), None, None)
    await asyncio.sleep(0.01)
    learner.cancel()
    await learner.drain()
    assert enabled.list(scope) == []


def test_direct_agent_write_is_active_and_generation_checked_inside_transaction(enabled, scope):
    draft = Draft("Package manager", "Use pnpm.", "user-source", key="package-manager")
    memory = enabled.add(scope, draft, origin="agent", consent_token=enabled.consent_token(scope))
    assert memory.status == "active"
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(ConsentError):
        enabled.add(
            scope, Draft("No", "discard this", "user-source"), origin="agent", cancelled=cancelled
        )


def test_v1_read_paths_preserve_bytes_and_first_write_migrates(enabled, scope):
    import sqlite3

    old = enabled.add(scope, Draft("Prior memory", "Retain old facts.", "old-source"))
    with sqlite3.connect(enabled.path) as conn:
        for column in ("evidence_quote", "source_role", "source_verification"):
            conn.execute("ALTER TABLE memories DROP COLUMN " + column)
        conn.execute("PRAGMA user_version=1")
    before = enabled.path.read_bytes()
    assert enabled.get(scope, old.id).source_verification == "declared"
    assert enabled.path.read_bytes() == before
    enabled.add(scope, Draft("New", "New facts.", "new-source"), origin="agent")
    with sqlite3.connect(enabled.path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert enabled.get(scope, old.id).content == "Retain old facts."


async def test_automatic_indexing_requires_no_manual_reindex(enabled, scope):
    class Local:
        fingerprint = "local-test:1"

        def encode(self, texts):
            return [[1.0, 0.0] for text in texts]

    enabled.embedder = Local()
    learner = Learner(enabled, extractor=Extractor())
    learner.start(exchange(enabled, scope), None, None)
    await learner.drain()
    result = enabled.search(scope, "dependency installation")
    assert result.hits and result.hits[0].channels == ("semantic",)
    assert result.warnings == ()


async def test_stale_correction_cannot_replace_a_newer_revision_or_revive_forgotten_memory(
    enabled, scope
):
    learner = Learner(enabled, extractor=Extractor())
    learner.start(exchange(enabled, scope), None, None)
    await learner.drain()
    old = enabled.list(scope)[0]
    stale = exchange(enabled, scope, "Actually use npm in this project.", "stale")
    current = enabled.add(
        scope,
        Draft("Package manager", "Use yarn now.", "user-source", key="package-manager"),
        supersedes=old.id,
    )
    learner.start(stale, None, None)
    await learner.drain()
    assert enabled.list(scope)[0].id == current.id
    late = exchange(enabled, scope, "Actually use npm in this project.", "late")
    enabled.forget(scope, current.id)
    learner.start(late, None, None)
    await learner.drain()
    assert enabled.list(scope) == []


def test_assistant_inference_does_not_override_an_explicit_user_preference(enabled, scope):
    old = enabled.add(
        scope, Draft("Package manager", "Use pnpm.", "user-command", key="package-manager")
    )
    inferred = enabled.add(
        scope,
        Draft("Package manager", "Use npm.", "assistant-source", key="package-manager"),
        origin="agent",
        supersedes=old.id,
        source_role="assistant",
        evidence_quote="Use npm.",
    )
    assert inferred.id == old.id
