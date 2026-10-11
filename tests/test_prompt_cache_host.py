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
    policy = captures[-1].system_prompt
    await harness.prompt("Which uv installer?")
    current = captures[-1].messages
    assert current[: len(previous)] == previous
    assert captures[-1].system_prompt == policy
    assert policy.count("<aelix_memory_usage_policy>") == 1
    assert first.id in text(current) and second.id in text(current)
    assert not any(isinstance(m, _RecallMessage) for m in harness.state.messages)
    assert "<aelix_memory" not in str(await storage.get_entries())
    await harness._emit_session_shutdown("quit")


@pytest.mark.parametrize("provider", ["codex", "responses", "completions", "anthropic"])
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
    elif provider == "completions":
        from aelix_ai.providers._openai_compat import get_compat
        from aelix_ai.providers.openai_completions import build_params

        compat = get_compat(model)
        first, second = (
            build_params(model, a, opts, compat, "short"),
            build_params(model, b, opts, compat, "short"),
        )
        key = "messages"
    else:
        from aelix_ai.providers._anthropic_transforms import transform_messages

        first, second = (
            {"messages": transform_messages(prior, model)},
            {"messages": transform_messages(later, model)},
        )
        key = "messages"
    assert second[key][: len(first[key])] == first[key]


async def test_turns_and_tool_iterations_never_search_or_expand_startup(
    enabled, scope, monkeypatch
):
    old = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    _, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    queries, listings = [], []
    search, listing = extension.store.search, extension.store.startup_memories
    monkeypatch.setattr(
        extension.store, "search", lambda *a, **k: queries.append(True) or search(*a, **k)
    )
    monkeypatch.setattr(
        extension.store,
        "startup_memories",
        lambda *a, **k: listings.append(True) or listing(*a, **k),
    )
    user = UserMessage(content=[TextContent(text="pytest runner?")])
    first = await compose(extension, ctx, [user])
    assert await compose(extension, ctx, first) == first
    later = enabled.add(scope, Draft("Later note", "pytest uses fixtures.", "user-command"))
    current = await compose(extension, ctx, [user, AssistantMessage(), user])
    assert current[: len(first)] == first and text(current).count(old.citation) == 1
    assert later.id not in text(current) and not queries and len(listings) == 1
    extension.session_id = "new-session"
    assert later.id in text(await compose(extension, ctx, [user]))


async def test_topics_are_read_on_demand_through_real_model_tool_calls(enabled, scope, monkeypatch):
    from aelix_ai.messages import ToolCallContent

    detail = enabled.add(
        scope,
        Draft(
            "Archive protocol",
            "Use ARCHIVE-731 for export recovery.",
            "user-command",
            kind="episode",
        ),
    )
    for index in range(20):
        enabled.add(
            scope, Draft(f"Other topic {index}", "Other history.", "user-command", kind="episode")
        )
    call = ToolCallContent(
        tool_call_id="detail-call", tool_name="memory_get", input={"id": detail.id}
    )
    harness, captures, storage, _, _ = build(scope, enabled.home, monkeypatch, tool_call=call)
    await harness._emit_session_start("startup")
    await harness.prompt("Look up the requested archive record.")
    snapshot = next(m for m in captures[0].messages if isinstance(m, _RecallMessage))
    assert detail.id not in text([snapshot]) and "ARCHIVE-731" not in text([snapshot])
    results = [
        m for m in harness.state.messages if getattr(m, "tool_call_id", None) == "detail-call"
    ]
    assert results and not results[0].is_error and "ARCHIVE-731" in text(results)
    assert captures[-1].messages[: len(captures[0].messages)] == captures[0].messages
    assert "<aelix_memory" not in str(await storage.get_entries())
    await harness._emit_session_shutdown("quit")


async def test_forget_and_correction_remove_old_summary_without_auto_refresh(
    enabled, scope, monkeypatch
):
    from types import SimpleNamespace

    old = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command", key="runner"))
    harness, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    await harness._emit_session_start("startup")
    user = UserMessage(content=[TextContent(text="pytest runner?")])
    assert old.id in text(await compose(extension, ctx, [user]))
    enabled.forget(scope, old.id)
    assert old.id not in text(await compose(extension, ctx, [user]))
    later = enabled.add(scope, Draft("Installer", "Use uv.", "user-command", key="installer"))
    assert later.id not in text(await compose(extension, ctx, [user]))
    await harness._emit_session_start("resume")
    assert later.id in text(await compose(extension, ctx, [user]))
    replacement = enabled.add(
        scope, Draft("Installer", "Use pip.", "user-command", key="installer"), supersedes=later.id
    )
    updated = await compose(
        extension, ctx, [user, AssistantMessage(), UserMessage(content=[TextContent(text="pip?")])]
    )
    assert later.id not in text(updated) and replacement.id not in text(updated)
    recalled = await extension.tool("memory_recall", {"query": "pip"}, SimpleNamespace(signal=None))
    assert replacement.id in text([recalled]) and not recalled.is_error


async def test_compaction_keeps_the_same_valid_startup_snapshot(enabled, scope, monkeypatch):
    memory = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    _, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    previous = await compose(extension, ctx, [UserMessage(content=[TextContent(text="pytest?")])])
    compacted = await compose(
        extension, ctx, [UserMessage(content=[TextContent(text="Compacted task context")])]
    )
    assert compacted[0] == previous[0] and memory.id in text([compacted[0]])


async def test_cached_evidence_expires_without_writes(enabled, scope, monkeypatch):
    for module in ("store", "extension"):
        monkeypatch.setattr(
            f"aelix_memory.{module}.now_iso", lambda: "2026-10-12T00:00:00.000000+00:00"
        )
    memory = enabled.add(
        scope, Draft("Runner", "Use pytest.", "user-command", expires_at="2026-10-12T00:01:00Z")
    )
    _, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    user = UserMessage(content=[TextContent(text="pytest?")])
    assert memory.id in text(await compose(extension, ctx, [user]))
    before = enabled.path.read_bytes()
    for module in ("store", "extension"):
        monkeypatch.setattr(
            f"aelix_memory.{module}.now_iso", lambda: "2026-10-12T00:02:00.000000+00:00"
        )
    assert memory.id not in text(await compose(extension, ctx, [user]))
    assert enabled.path.read_bytes() == before


@pytest.mark.parametrize("cycle", [False, True])
async def test_consent_change_during_startup_read_suppresses_old_context(
    enabled, scope, monkeypatch, cycle
):
    import asyncio
    import threading

    enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    _, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    user = UserMessage(content=[TextContent(text="pytest?")])
    started, release = threading.Event(), threading.Event()
    listing = extension.store.startup_memories

    def delayed(*args, **kwargs):
        result = listing(*args, **kwargs)
        started.set()
        assert release.wait(3)
        return result

    monkeypatch.setattr(extension.store, "startup_memories", delayed)
    task = asyncio.create_task(compose(extension, ctx, [user]))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        enabled.set_global_mode("off")
        if cycle:
            enabled.set_global_mode("on")
    finally:
        release.set()
    assert await task == [user] and not extension._startup.loaded


async def test_external_off_on_cycle_and_project_change_do_not_replay_evidence(
    enabled, scope, tmp_path, monkeypatch
):
    memory = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    _, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    user = UserMessage(content=[TextContent(text="pytest?")])
    first = await compose(extension, ctx, [user])
    enabled.set_global_mode("off")
    assert await compose(extension, ctx, first) == [user]
    enabled.set_global_mode("on")
    other = tmp_path / "other"
    other.mkdir()
    assert memory.id not in text(
        await compose(extension, command_context(extension, Scope.for_project(other)), first)
    )


async def test_off_on_cycle_at_final_mode_check_revokes_snapshot(enabled, scope, monkeypatch):
    enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    _, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    mode = extension.store.mode
    checks = []

    def cycle_at_last_check(scope):
        value = mode(scope)
        checks.append(True)
        if len(checks) == 2:
            enabled.set_global_mode("off")
            enabled.set_global_mode("on")
        return value

    monkeypatch.setattr(extension.store, "mode", cycle_at_last_check)
    user = UserMessage(content=[TextContent(text="pytest?")])
    assert await compose(extension, ctx, [user]) == [user]
    assert not extension._startup.loaded


@pytest.mark.parametrize("operation", ["forget", "revise"])
@pytest.mark.parametrize("loaded", [False, True])
async def test_source_change_during_async_read_is_revalidated(
    operation, loaded, enabled, scope, monkeypatch
):
    import asyncio
    import threading

    old = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command", key="runner"))
    _, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    user = UserMessage(content=[TextContent(text="pytest?")])
    if loaded:
        await compose(extension, ctx, [user])
    started, release = threading.Event(), threading.Event()
    get = extension.store.get

    def delayed(*args, **kwargs):
        result = get(*args, **kwargs)
        if not started.is_set():
            started.set()
            assert release.wait(3)
        return result

    monkeypatch.setattr(extension.store, "get", delayed)
    task = asyncio.create_task(compose(extension, ctx, [user]))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        if operation == "forget":
            enabled.forget(scope, old.id)
        else:
            enabled.add(
                scope,
                Draft("Runner", "Use unittest.", "user-command", key="runner"),
                supersedes=old.id,
            )
    finally:
        release.set()
    assert old.id not in text(await task)


async def test_storage_failure_does_not_refresh_snapshot_with_new_records(
    enabled, scope, monkeypatch
):
    old = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    _, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    user = UserMessage(content=[TextContent(text="pytest?")])
    await compose(extension, ctx, [user])

    def fail(*_args, **_kwargs):
        raise OSError("Unavailable store")

    with monkeypatch.context() as patch:
        patch.setattr(extension.store, "get", fail)
        assert await compose(extension, ctx, [user]) == [user]
    later = enabled.add(scope, Draft("Installer", "Use uv.", "user-command"))
    rendered = text(await compose(extension, ctx, [user]))
    assert old.id not in rendered and later.id not in rendered


async def test_session_start_and_shutdown_discard_snapshot(enabled, scope, monkeypatch):
    enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    harness, _, _, _, extension = build(scope, enabled.home, monkeypatch)
    ctx = command_context(extension, scope)
    await compose(extension, ctx, [UserMessage(content=[TextContent(text="pytest?")])])
    assert extension._startup.loaded
    await harness._emit_session_start("resume")
    assert not extension._startup.loaded
    await compose(extension, ctx, [UserMessage(content=[TextContent(text="pytest?")])])
    assert extension._startup.loaded
    await harness._emit_session_shutdown("quit")
    assert not extension._startup.loaded


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
