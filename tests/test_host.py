"""Real host hooks, loop, permission gate and session storage; no provider network calls."""

import pytest

pytest.importorskip(
    "aelix_coding_agent", reason="Run host integration in a host-equipped environment"
)

from aelix_agent_core.harness.core import AgentHarness, AgentHarnessOptions
from aelix_agent_core.session.memory_storage import MemorySessionStorage
from aelix_agent_core.session.session import Session
from aelix_ai.messages import AssistantMessage, TextContent, ToolCallContent
from aelix_ai.streaming import AssistantEndEvent, AssistantStartEvent, Model
from aelix_coding_agent.builtin.permission import PermissionExtension
from aelix_coding_agent.builtin.permission_mode import PermissionMode, PermissionPosture
from aelix_coding_agent.extensions.api import Extension, ExtensionAPI, _ExtensionRuntime

from aelix_memory import setup
from aelix_memory.models import Draft

pytestmark = pytest.mark.host


def build(
    scope,
    home,
    monkeypatch,
    *,
    tool_call=None,
    permission_mode=PermissionMode.DEFAULT,
    active_tool_names=None,
):
    monkeypatch.setenv("AELIX_MEMORY_HOME", str(home))
    runtime = _ExtensionRuntime()
    pack = Extension(name="aelix-memory")
    api = ExtensionAPI(pack, runtime)
    setup(api)
    permission = Extension(name="permission")
    PermissionExtension(posture=PermissionPosture(mode=permission_mode))(
        ExtensionAPI(permission, runtime)
    )
    captured = []
    replies = []
    storage = MemorySessionStorage()
    session = Session(storage)

    async def stream(_model, context, _options):
        captured.append(context)
        if tool_call and len(captured) == 1:
            message = AssistantMessage(content=[tool_call], stop_reason="toolUse")
        else:
            message = AssistantMessage(content=[TextContent(text="done")], stop_reason="end_turn")
        replies.append(message)
        yield AssistantStartEvent(partial=AssistantMessage())
        yield AssistantEndEvent(message=message)

    harness = AgentHarness(
        AgentHarnessOptions(
            model=Model(id="deterministic", provider="mock"),
            extensions=[pack, permission],
            runtime=runtime,
            stream_fn=stream,
            session=session,
            cwd=str(scope.root),
            active_tool_names=active_tool_names,
        )
    )
    handler = pack.commands["memory"].handler
    return harness, captured, storage, pack, handler


async def test_off_host_load_and_prompt_do_not_create_files(scope, tmp_path, monkeypatch):
    home = tmp_path / "absent"
    harness, captured, storage, pack, _ = build(scope, home, monkeypatch)
    await harness._emit_session_start("startup")
    await harness.prompt("pytest")
    assert not home.exists()
    assert not any(t.name.startswith("memory_") for t in captured[0].tools)
    assert len(await storage.find_entries("message")) == 2


async def test_memory_respects_host_explicit_no_tools(enabled, scope, monkeypatch):
    harness, captured, _, _, _ = build(scope, enabled.home, monkeypatch, active_tool_names=[])
    await harness._emit_session_start("startup")
    await harness.prompt("pytest")
    assert captured[0].tools == []


async def test_real_context_is_ephemeral_and_off_next_turn_removes_recall(
    enabled, scope, monkeypatch
):
    memory = enabled.add(scope, Draft("Test runner", "Use uv run pytest.", "docs/testing.md:12"))
    harness, captured, storage, pack, _ = build(scope, enabled.home, monkeypatch)
    await harness._emit_session_start("startup")
    await harness.prompt("What test runner uses pytest?")
    assert any(memory.citation in str(m.content) for m in captured[0].messages)
    assert not any(memory.citation in str(m.content) for m in harness.state.messages)
    assert not any(memory.citation in str(e) for e in await storage.get_entries())
    enabled.set_mode(scope, "off")
    await harness.prompt("Which pytest runner?")
    assert not any(memory.citation in str(m.content) for m in captured[-1].messages)
    assert not any(t.name.startswith("memory_") for t in captured[-1].tools)


async def test_host_tool_execution_creates_only_pending_proposal_with_receipts(
    enabled, scope, monkeypatch
):
    call = ToolCallContent(
        tool_call_id="host-call-123",
        tool_name="memory_propose",
        input={
            "title": "Test runner",
            "content": "Use uv run pytest.",
            "source_ref": "user said this turn",
        },
    )
    harness, captured, storage, pack, _ = build(scope, enabled.home, monkeypatch, tool_call=call)
    await harness._emit_session_start("startup")
    await harness.prompt("Remember the test runner.")
    proposals = enabled.list(scope, status="pending")
    assert len(proposals) == 1
    assert proposals[0].source_call == "host-call-123"
    assert proposals[0].source_session == (await storage.get_metadata()).id
    assert not enabled.search(scope, "pytest").hits
    assert any(getattr(m, "tool_call_id", None) == "host-call-123" for m in harness.state.messages)
    enabled.approve(scope, proposals[0].id)
    assert enabled.search(scope, "pytest").hits


async def test_real_plan_gate_blocks_proposals(enabled, scope, monkeypatch):
    call = ToolCallContent(
        tool_call_id="plan-call",
        tool_name="memory_propose",
        input={
            "title": "Test runner",
            "content": "Use pytest.",
            "source_ref": "user-command",
        },
    )
    harness, captured, storage, pack, _ = build(
        scope, enabled.home, monkeypatch, tool_call=call, permission_mode=PermissionMode.PLAN
    )
    await harness._emit_session_start("startup")
    await harness.prompt("Propose a test runner memory.")
    assert enabled.list(scope, status="pending") == []
    results = [m for m in harness.state.messages if getattr(m, "tool_call_id", None) == "plan-call"]
    assert results and results[0].is_error
    assert "plan" in str(results[0].content).lower()


async def test_read_host_has_no_propose_tool(enabled, scope, monkeypatch):
    enabled.set_mode(scope, "read")
    harness, captured, _, _, _ = build(scope, enabled.home, monkeypatch)
    await harness._emit_session_start("startup")
    await harness.prompt("pytest")
    names = {t.name for t in captured[0].tools}
    assert {"memory_recall", "memory_get"} <= names
    assert "memory_propose" not in names


async def test_invalid_model_configuration_is_inert_while_off(scope, tmp_path, monkeypatch):
    monkeypatch.setenv("AELIX_MEMORY_EMBEDDING_MODEL", str(tmp_path / "missing-model"))
    home = tmp_path / "never-created"
    harness, _, _, _, _ = build(scope, home, monkeypatch)
    await harness._emit_session_start("startup")
    await harness.prompt("hello")
    assert not home.exists()
