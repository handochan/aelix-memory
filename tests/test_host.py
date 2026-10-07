"""Real host hooks, loop, permissions and session persistence, with a deterministic extractor."""

import json

import pytest

pytest.importorskip("aelix_coding_agent", reason="Host packages required")

from aelix_agent_core.harness.core import AgentHarness, AgentHarnessOptions
from aelix_agent_core.session.memory_storage import MemorySessionStorage
from aelix_agent_core.session.session import Session
from aelix_ai.messages import AssistantMessage, TextContent, ToolCallContent
from aelix_ai.streaming import AssistantEndEvent, AssistantStartEvent, Model
from aelix_coding_agent.builtin.permission import PermissionExtension
from aelix_coding_agent.builtin.permission_mode import PermissionMode, PermissionPosture
from aelix_coding_agent.extensions.api import Extension, ExtensionAPI, _ExtensionRuntime

from aelix_memory.extension import register
from aelix_memory.learning import parse_extraction
from aelix_memory.models import Draft

pytestmark = pytest.mark.host


async def test_extraction_accepts_real_canonical_provider_done_event(enabled, scope, monkeypatch):
    from types import SimpleNamespace

    from aelix_ai.streaming import AssistantDoneEvent
    from test_learning import exchange, payload

    from aelix_memory.learning import HostExtractor

    class Registry:
        async def get_api_key_and_headers(self, model):
            return SimpleNamespace(ok=True, api_key=None, headers={})

    async def stream(model, context, options):
        assert context.tools == [] and options.max_tokens == 1024

        async def events():
            yield AssistantDoneEvent(
                message=AssistantMessage(
                    content=[TextContent(text=payload())], stop_reason="end_turn"
                )
            )

        return events()

    monkeypatch.setattr("aelix_ai.streaming.stream_simple", stream)
    notes = await HostExtractor().extract(exchange(enabled, scope), Model(id="mock"), Registry())
    assert len(notes) == 1 and notes[0].source_role == "user"


class FakeExtractor:
    def __init__(self):
        self.calls = 0

    async def extract(self, exchange, model, registry):
        self.calls += 1
        text = exchange.sources[0].text
        if not text.startswith(("I always", "Actually", "저는")):
            return ()
        return parse_extraction(
            json.dumps(
                {
                    "memories": [
                        {
                            "title": "Package manager",
                            "key": "package-manager",
                            "kind": "preference",
                            "quote": text,
                            "source_index": 0,
                        }
                    ]
                }
            ),
            exchange,
        )


def build(
    scope,
    home,
    monkeypatch,
    *,
    tool_call=None,
    permission_mode=PermissionMode.DEFAULT,
    active_tool_names=None,
    extractor=None,
    reply_reason="end_turn",
):
    monkeypatch.setenv("AELIX_MEMORY_HOME", str(home))
    runtime = _ExtensionRuntime()
    pack = Extension(name="aelix-memory")
    extension = register(ExtensionAPI(pack, runtime), extractor=extractor or FakeExtractor())
    permission = Extension(name="permission")
    PermissionExtension(posture=PermissionPosture(mode=permission_mode))(
        ExtensionAPI(permission, runtime)
    )
    captured = []
    storage = MemorySessionStorage()

    async def stream(_model, context, _options):
        captured.append(context)
        if tool_call and len(captured) == 1:
            message = AssistantMessage(content=[tool_call], stop_reason="toolUse")
        else:
            message = AssistantMessage(content=[TextContent(text="done")], stop_reason=reply_reason)
        yield AssistantStartEvent(partial=AssistantMessage())
        yield AssistantEndEvent(message=message)

    harness = AgentHarness(
        AgentHarnessOptions(
            model=Model(id="deterministic", provider="mock"),
            extensions=[pack, permission],
            runtime=runtime,
            stream_fn=stream,
            session=Session(storage),
            cwd=str(scope.root),
            active_tool_names=active_tool_names,
        )
    )
    return harness, captured, storage, pack, extension


async def test_off_host_load_and_prompt_do_not_create_files(scope, tmp_path, monkeypatch):
    home = tmp_path / "absent"
    extractor = FakeExtractor()
    harness, captured, storage, _, extension = build(scope, home, monkeypatch, extractor=extractor)
    await harness._emit_session_start("startup")
    await harness.prompt("I always use pnpm in this project.")
    await harness._emit_session_shutdown("quit")
    assert not home.exists() and extractor.calls == 0
    assert extension._prompt == "" and extension._turn_id is None
    assert not any(t.name.startswith("memory_") for t in captured[0].tools)
    assert len(await storage.find_entries("message")) == 2


async def test_normal_host_conversation_learns_without_tools_or_approval_and_survives_shutdown(
    enabled, scope, monkeypatch
):
    harness, captured, storage, pack, _ = build(
        scope, enabled.home, monkeypatch, active_tool_names=[]
    )
    await harness._emit_session_start("startup")
    await harness.prompt("I always use pnpm in this project.")
    await harness._emit_session_shutdown("quit")
    memory = enabled.search(scope, "pnpm").hits[0].memory
    assert memory.status == "active" and memory.source_role == "user"
    assert memory.source_session == (await storage.get_metadata()).id
    assert memory.evidence_quote == "I always use pnpm in this project."
    assert captured[0].tools == []
    assert not any(
        name in pack.tools for name in ("memory_propose", "memory_approve", "memory_remember")
    )
    assert enabled.list(scope, status="pending") == []


async def test_next_turn_drains_learning_and_recall_is_ephemeral(enabled, scope, monkeypatch):
    harness, captured, storage, _, _ = build(scope, enabled.home, monkeypatch)
    await harness._emit_session_start("startup")
    await harness.prompt("I always use pnpm in this project.")
    await harness.prompt("Which package manager uses pnpm?")
    memory = enabled.search(scope, "pnpm").hits[0].memory
    assert any(memory.citation in str(m.content) for m in captured[-1].messages)
    assert not any(memory.citation in str(m.content) for m in harness.state.messages)
    assert not any("<aelix_memory" in str(e) for e in await storage.get_entries())
    await harness._emit_session_shutdown("quit")


async def test_new_host_session_recalls_automatically_learned_fact(enabled, scope, monkeypatch):
    first, _, _, _, _ = build(scope, enabled.home, monkeypatch)
    await first._emit_session_start("startup")
    await first.prompt("I always use pnpm in this project.")
    await first._emit_session_shutdown("new")
    memory = enabled.search(scope, "pnpm").hits[0].memory
    other, captured, _, _, _ = build(scope, enabled.home, monkeypatch)
    await other._emit_session_start("startup")
    await other.prompt("Which package manager uses pnpm?")
    assert any(memory.citation in str(m.content) for m in captured[0].messages)
    await other._emit_session_shutdown("quit")


async def test_read_host_recalls_but_does_not_extract_or_write(enabled, scope, monkeypatch):
    memory = enabled.add(scope, Draft("Package manager", "Use pnpm.", "user-command"))
    enabled.set_mode(scope, "read")
    before = enabled.path.read_bytes()
    extractor = FakeExtractor()
    harness, captured, _, pack, _ = build(scope, enabled.home, monkeypatch, extractor=extractor)
    await harness._emit_session_start("startup")
    await harness.prompt("I always use pnpm in this project.")
    await harness._emit_session_shutdown("quit")
    assert any(memory.citation in str(m.content) for m in captured[0].messages)
    assert extractor.calls == 0 and enabled.path.read_bytes() == before
    assert set(pack.tools) == {"memory_recall", "memory_get"}


async def test_off_next_turn_removes_recall_and_learning(enabled, scope, monkeypatch):
    harness, captured, _, _, _ = build(scope, enabled.home, monkeypatch)
    await harness._emit_session_start("startup")
    await harness.prompt("I always use pnpm in this project.")
    await harness._emit_session_shutdown("quit")
    memory = enabled.search(scope, "pnpm").hits[0].memory
    enabled.set_mode(scope, "off")
    await harness.prompt("Which pnpm package manager?")
    assert not any(memory.citation in str(m.content) for m in captured[-1].messages)
    assert captured[-1].tools == []


async def test_real_plan_gate_still_blocks_optional_memory_tool(enabled, scope, monkeypatch):
    enabled.add(scope, Draft("Package manager", "Use pnpm.", "user-command"))
    call = ToolCallContent(
        tool_call_id="plan-call", tool_name="memory_recall", input={"query": "pnpm"}
    )
    harness, _, _, _, _ = build(
        scope, enabled.home, monkeypatch, tool_call=call, permission_mode=PermissionMode.PLAN
    )
    await harness._emit_session_start("startup")
    await harness.prompt("What package manager?")
    await harness._emit_session_shutdown("quit")
    results = [m for m in harness.state.messages if getattr(m, "tool_call_id", None) == "plan-call"]
    assert results and results[0].is_error and "plan" in str(results[0].content).lower()


@pytest.mark.parametrize("reason", ["error", "aborted", "max_tokens"])
async def test_failed_host_response_does_not_learn(enabled, scope, monkeypatch, reason):
    extractor = FakeExtractor()
    harness, _, _, _, _ = build(
        scope, enabled.home, monkeypatch, extractor=extractor, reply_reason=reason
    )
    await harness._emit_session_start("startup")
    await harness.prompt("I always use pnpm in this project.")
    await harness._emit_session_shutdown("quit")
    assert extractor.calls == 0 and enabled.list(scope) == []


async def test_private_request_and_secret_response_are_not_extracted(enabled, scope, monkeypatch):
    extractor = FakeExtractor()
    harness, _, _, _, _ = build(scope, enabled.home, monkeypatch, extractor=extractor)
    await harness._emit_session_start("startup")
    await harness.prompt("Do not remember this conversation.")
    await harness._emit_session_shutdown("quit")
    assert extractor.calls == 0 and enabled.list(scope) == []


async def test_invalid_embedding_configuration_is_inert_while_off(scope, tmp_path, monkeypatch):
    monkeypatch.setenv("AELIX_MEMORY_EMBEDDING_MODEL", str(tmp_path / "missing-model"))
    home = tmp_path / "absent"
    harness, _, _, _, _ = build(scope, home, monkeypatch)
    await harness._emit_session_start("startup")
    await harness.prompt("hello")
    await harness._emit_session_shutdown("quit")
    assert not home.exists()
