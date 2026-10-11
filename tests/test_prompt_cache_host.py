"""Actual host contexts and provider converters preserve historical prompt prefixes."""

import json

import pytest

pytest.importorskip("aelix_coding_agent")

from aelix_agent_core.harness.hooks import ContextHookEvent
from aelix_ai.messages import AssistantMessage, TextContent, UserMessage
from aelix_ai.streaming import Context, Model, SimpleStreamOptions
from test_host import build, command_context

from aelix_memory.extension import _RecallMessage
from aelix_memory.models import Draft
from aelix_memory.scope import Scope

pytestmark = pytest.mark.host


def text(messages):
    return "\n".join(c.text for m in messages for c in m.content if isinstance(c, TextContent))


async def compose(extension, ctx, messages):
    result = await extension.context(ContextHookEvent(messages=messages), ctx)
    return result.messages if result is not None else messages


async def test_multi_turn_context_keeps_earlier_memory_and_reads_remain_ephemeral(
    enabled, scope, monkeypatch
):
    first = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    second = enabled.add(scope, Draft("Installer", "Use uv.", "user-command"))
    harness, captures, storage, _, extension = build(scope, enabled.home, monkeypatch)
    await harness._emit_session_start("startup")
    await harness.prompt("Which pytest runner?")
    previous = captures[-1].messages
    await harness.prompt("Which uv installer?")
    current = captures[-1].messages
    assert current[: len(previous)] == previous
    assert first.id in text(current) and second.id in text(current)
    assert not any(isinstance(m, _RecallMessage) for m in harness.state.messages)
    assert "<aelix_memory" not in str(await storage.get_entries())
    await harness._emit_session_shutdown("quit")


@pytest.mark.parametrize("provider", ["codex", "responses", "anthropic"])
async def test_actual_provider_input_preserves_previous_prefix(
    provider, enabled, scope, monkeypatch
):
    enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    enabled.add(scope, Draft("Installer", "Use uv.", "user-command"))
    _, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    original = [UserMessage(content=[TextContent(text="pytest runner?")])]
    prior = await compose(extension, ctx, original)
    later = await compose(
        extension,
        ctx,
        original
        + [
            AssistantMessage(content=[TextContent(text="pytest")]),
            UserMessage(content=[TextContent(text="uv installer?")]),
        ],
    )
    model = Model(id="model", provider="openai" if provider != "anthropic" else "anthropic")
    a, b = (
        Context(system_prompt="Stable instructions", messages=prior),
        Context(system_prompt="Stable instructions", messages=later),
    )
    opts = SimpleStreamOptions(session_id="stable-host-session")
    if provider == "codex":
        from aelix_ai.providers.openai_codex_responses import build_request_body

        first, second = build_request_body(model, a, opts), build_request_body(model, b, opts)
        assert (
            first["instructions"] == second["instructions"]
            and first["prompt_cache_key"] == second["prompt_cache_key"]
        )
        key = "input"
    elif provider == "responses":
        from aelix_ai.providers.openai_responses import build_params

        first, second = build_params(model, a, opts), build_params(model, b, opts)
        key = "input"
    else:
        from aelix_ai.providers._anthropic_transforms import transform_messages

        first, second = (
            {"messages": transform_messages(prior, model)},
            {"messages": transform_messages(later, model)},
        )
        key = "messages"
    assert second[key][: len(first[key])] == first[key]


async def test_tool_iterations_do_not_repeat_search_or_rewrite_existing_block(
    enabled, scope, monkeypatch
):
    enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    _, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    original = [UserMessage(content=[TextContent(text="pytest runner?")])]
    searches = []
    search = extension.store.search
    monkeypatch.setattr(
        extension.store, "search", lambda *a, **k: searches.append(True) or search(*a, **k)
    )
    first = await compose(extension, ctx, original)
    assert await compose(extension, ctx, first) == first
    again = await compose(
        extension, ctx, original + [AssistantMessage(content=[TextContent(text="Still working")])]
    )
    assert again[: len(first)] == first and len(searches) == 1


async def test_duplicate_user_text_has_distinct_anchors_and_new_records_append(
    enabled, scope, monkeypatch
):
    old = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    _, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    user = UserMessage(content=[TextContent(text="pytest?")])
    first = await compose(extension, ctx, [user])
    new = enabled.add(scope, Draft("Later note", "pytest uses fixtures.", "user-command"))
    second = await compose(extension, ctx, [user, AssistantMessage(), user])
    assert second[: len(first)] == first and text(second).count(old.citation) == 1
    assert new.citation in text(second)


async def test_forget_correction_and_compaction_remove_stale_overlays(enabled, scope, monkeypatch):
    old = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command", key="runner"))
    _, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    user = UserMessage(content=[TextContent(text="pytest runner?")])
    assert old.id in text(await compose(extension, ctx, [user]))
    enabled.forget(scope, old.id)
    assert old.id not in text(await compose(extension, ctx, [user]))
    assert extension._recall.size == 0

    later = enabled.add(scope, Draft("Installer", "Use uv.", "user-command", key="installer"))
    newer_user = UserMessage(content=[TextContent(text="uv installer?")])
    assert later.id in text(await compose(extension, ctx, [newer_user]))
    replacement = enabled.add(
        scope, Draft("Installer", "Use pip.", "user-command", key="installer"), supersedes=later.id
    )
    rewritten = await compose(
        extension,
        ctx,
        [newer_user, AssistantMessage(), UserMessage(content=[TextContent(text="pip installer?")])],
    )
    assert later.id not in text(rewritten) and replacement.id in text(rewritten)
    await compose(
        extension, ctx, [UserMessage(content=[TextContent(text="Unrelated compacted context")])]
    )
    assert extension._recall.size == 0


async def test_cached_evidence_expires_without_writes(enabled, scope, monkeypatch):
    monkeypatch.setattr("aelix_memory.store.now_iso", lambda: "2026-10-11T00:00:00.000000+00:00")
    memory = enabled.add(
        scope, Draft("Runner", "Use pytest.", "user-command", expires_at="2026-10-11T00:01:00Z")
    )
    _, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    user = UserMessage(content=[TextContent(text="pytest runner?")])
    assert memory.id in text(await compose(extension, ctx, [user]))
    before = enabled.path.read_bytes()
    monkeypatch.setattr("aelix_memory.store.now_iso", lambda: "2026-10-11T00:02:00.000000+00:00")
    assert memory.id not in text(await compose(extension, ctx, [user]))
    assert enabled.path.read_bytes() == before


@pytest.mark.parametrize("cycle", [False, True])
async def test_consent_change_during_async_retrieval_suppresses_old_context(
    enabled, scope, monkeypatch, cycle
):
    import asyncio
    import threading

    enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    _, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    user = UserMessage(content=[TextContent(text="pytest runner?")])
    started, release = threading.Event(), threading.Event()
    search = extension.store.search

    def delayed(*args, **kwargs):
        result = search(*args, **kwargs)
        started.set()
        assert release.wait(3)
        return result

    monkeypatch.setattr(extension.store, "search", delayed)
    task = asyncio.create_task(compose(extension, ctx, [user]))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        enabled.set_global_mode("off")
        if cycle:
            enabled.set_global_mode("on")
    finally:
        release.set()
    assert await task == [user] and extension._recall.size == 0


async def test_external_off_on_cycle_and_project_change_do_not_replay_cached_evidence(
    enabled, scope, tmp_path, monkeypatch
):
    memory = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    _, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    user = UserMessage(content=[TextContent(text="pytest runner?")])
    first = await compose(extension, ctx, [user])
    enabled.set_global_mode("off")
    assert await compose(extension, ctx, first) == [user]
    enabled.set_global_mode("on")
    other = tmp_path / "other"
    other.mkdir()
    other_ctx = command_context(extension, Scope.for_project(other))
    assert memory.id not in text(await compose(extension, other_ctx, first))


@pytest.mark.parametrize("operation", ["forget", "revise"])
async def test_evidence_changed_during_search_is_not_replayed(
    operation, enabled, scope, monkeypatch
):
    import asyncio
    import threading

    old = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command", key="runner"))
    installer = enabled.add(scope, Draft("Installer", "Use uv.", "user-command"))
    _, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    user = UserMessage(content=[TextContent(text="pytest runner?")])
    await compose(extension, ctx, [user])
    started, release = threading.Event(), threading.Event()
    search = extension.store.search

    def delayed(*args, **kwargs):
        result = search(*args, **kwargs)
        started.set()
        assert release.wait(3)
        return result

    monkeypatch.setattr(extension.store, "search", delayed)
    task = asyncio.create_task(
        compose(
            extension,
            ctx,
            [user, AssistantMessage(), UserMessage(content=[TextContent(text="uv installer?")])],
        )
    )
    try:
        assert await asyncio.to_thread(started.wait, 3)
        if operation == "forget":
            enabled.forget(scope, old.id)
            enabled.forget(scope, installer.id)
        else:
            enabled.add(
                scope,
                Draft("Runner", "Use unittest.", "user-command", key="runner"),
                supersedes=old.id,
            )
            enabled.add(
                scope, Draft("Installer", "Use pip.", "user-command"), supersedes=installer.id
            )
    finally:
        release.set()
    rendered = text(await task)
    assert old.id not in rendered and installer.id not in rendered
    assert extension._recall.size == 0


async def test_session_start_and_shutdown_discard_transient_blocks(enabled, scope, monkeypatch):
    enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    harness, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    await compose(extension, ctx, [UserMessage(content=[TextContent(text="pytest runner?")])])
    assert extension._recall.size > 0
    await harness._emit_session_start("resume")
    assert extension._recall.size == 0
    await compose(extension, ctx, [UserMessage(content=[TextContent(text="pytest runner?")])])
    assert extension._recall.size > 0
    await harness._emit_session_shutdown("quit")
    assert extension._recall.size == 0


async def test_extractor_key_is_stable_per_session_and_payload_order_is_deterministic(
    enabled, scope, monkeypatch
):
    from dataclasses import replace
    from types import SimpleNamespace

    from aelix_ai.streaming import AssistantDoneEvent
    from test_learning import exchange

    from aelix_memory.learning import HostExtractor

    seen = []

    async def stream(model, context, options):
        seen.append((context, options))

        async def events():
            yield AssistantDoneEvent(
                message=AssistantMessage(
                    content=[TextContent(text='{"memories":[]}')], stop_reason="end_turn"
                )
            )

        return events()

    class Registry:
        async def get_api_key_and_headers(self, model):
            return SimpleNamespace(ok=True, api_key=None, headers={})

    monkeypatch.setattr("aelix_ai.streaming.stream_simple", stream)
    first = exchange(enabled, scope)
    await HostExtractor().extract(first, Model(id="mock"), Registry())
    await HostExtractor().extract(
        replace(first, turn_id="another-turn"), Model(id="mock"), Registry()
    )
    await HostExtractor().extract(
        replace(first, session_id="another-session"), Model(id="mock"), Registry()
    )
    assert seen[0][1].session_id == seen[1][1].session_id != seen[2][1].session_id
    assert len(seen[0][1].session_id) <= 64
    payload = json.loads(seen[0][0].messages[0].content[0].text)
    assert list(payload) == ["existing", "sources"]
