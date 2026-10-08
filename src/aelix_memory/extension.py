"""Natural memory through public host hooks; enabling once authorizes automatic learning."""

from __future__ import annotations

import asyncio
import contextlib
import json
import shlex
import sqlite3
import uuid
from typing import Any

from aelix_agent_core.harness.hooks import (
    AgentEndHookEvent,
    BeforeAgentStartHookEvent,
    ContextHookEvent,
    ContextResult,
    SessionShutdownHookEvent,
    SessionStartHookEvent,
)
from aelix_agent_core.types import AgentTool
from aelix_ai.messages import AssistantMessage, TextContent, UserMessage
from aelix_ai.tools import ToolExecutionContext, ToolResult
from aelix_coding_agent.extensions.api import ExtensionAPI, ExtensionContext

from .cli import configured_store, terminal_text
from .commands import parser, run
from .context import render_context
from .learning import Exchange, Extractor, Learner, sources_for
from .models import MemoryError
from .scope import Scope

_TOOL_NAMES = ("memory_recall", "memory_get")


class _RecallMessage(UserMessage):
    """Transient provider context, never appended to the durable session."""


def _result(data: Any, *, error: bool = False) -> ToolResult:
    return ToolResult(
        content=[TextContent(text=json.dumps(data, ensure_ascii=False))],
        details=data,
        is_error=error,
    )


class MemoryExtension:
    def __init__(self, api: ExtensionAPI, *, extractor: Extractor | None = None) -> None:
        self.api = api
        self.store = configured_store()
        self.learner = Learner(self.store, extractor=extractor)
        self.scope: Scope | None = None
        self.session_id: str | None = None
        self._permitted_tools: set[str] | None = None
        self._last_tools: set[str] = set()
        self._turn_id: str | None = None
        self._prompt = ""
        self._consent = 0
        self._index_task: asyncio.Task | None = None

    async def bind(self, ctx: ExtensionContext) -> None:
        self.scope = Scope.for_project(ctx.cwd)
        session = ctx.session_manager.get_session()
        self.session_id = str((await session.get_metadata()).id) if session is not None else None
        self.sync_tools()

    def sync_tools(self) -> None:
        mode = self.store.mode(self.scope) if self.scope else "off"
        active = self.api.get_active_tools()
        current = set(active).intersection(_TOOL_NAMES)
        if self._permitted_tools is None:
            self._permitted_tools = current
        elif current != self._last_tools:
            self._permitted_tools.difference_update(self._last_tools - current)
            self._permitted_tools.update(current - self._last_tools)
        desired = [name for name in active if name not in _TOOL_NAMES]
        if mode != "off":
            desired.extend(name for name in _TOOL_NAMES if name in self._permitted_tools)
        self._last_tools = set(desired).intersection(_TOOL_NAMES)
        if desired != active:
            self.api.set_active_tools(desired)

    def memory_enabled(self) -> bool:
        """Global usage checkbox; READ is also enabled memory, with learning paused."""
        return self.store.global_mode() != "off"

    async def set_memory_enabled(self, enabled: bool) -> None:
        if not enabled:
            self.cancel()
            self._prompt = ""
            self._turn_id = None
        await asyncio.to_thread(self.store.set_global_mode, "on" if enabled else "off")
        self.sync_tools()
        self.index_in_background()

    def cancel(self) -> None:
        self.learner.cancel()
        if self._index_task and not self._index_task.done():
            self._index_task.cancel()

    def index_in_background(self) -> None:
        if self.scope is None or self.store.embedder is None or self.store.mode(self.scope) != "on":
            return
        if self._index_task is not None and not self._index_task.done():
            return
        scope, token = self.scope, self.store.consent_token(self.scope)

        async def index() -> None:
            with contextlib.suppress(MemoryError, sqlite3.Error, OSError):
                await asyncio.to_thread(self.store.index_missing, scope, consent_token=token)

        self._index_task = asyncio.create_task(index())

    async def session_start(self, _event: SessionStartHookEvent, ctx: ExtensionContext) -> None:
        await self.bind(ctx)
        self.index_in_background()

    async def before_start(self, event: BeforeAgentStartHookEvent, ctx: ExtensionContext) -> None:
        incoming = Scope.for_project(ctx.cwd)
        if (
            self.scope != incoming
            or self.store.mode(incoming) != "on"
            or self.store.consent_token(incoming) != self._consent
        ):
            self.learner.cancel()
        await self.learner.drain()
        await self.bind(ctx)
        assert self.scope is not None
        enabled = self.store.mode(self.scope) == "on"
        self._turn_id = uuid.uuid4().hex if enabled else None
        self._prompt = event.prompt if enabled else ""
        self._consent = self.store.consent_token(self.scope)
        self.index_in_background()

    async def agent_end(self, event: AgentEndHookEvent, ctx: ExtensionContext) -> None:
        if self.scope is None or self._turn_id is None or self.store.mode(self.scope) != "on":
            return
        if self.store.consent_token(self.scope) != self._consent:
            return
        assistant = next(
            (m for m in reversed(event.messages) if isinstance(m, AssistantMessage)), None
        )
        if (
            assistant is None
            or assistant.error_message
            or assistant.stop_reason in {"error", "aborted", "max_tokens"}
        ):
            return
        text = "\n".join(c.text for c in assistant.content if isinstance(c, TextContent))
        sources = sources_for(self._prompt, text)
        if not sources:
            return
        exchange = Exchange(
            self.scope,
            self.session_id,
            self._turn_id,
            self._consent,
            sources,
            self.store.current_keys(self.scope),
        )
        self.learner.start(exchange, ctx.model, ctx.model_registry)

    async def session_shutdown(
        self, _event: SessionShutdownHookEvent, _ctx: ExtensionContext
    ) -> None:
        await self.learner.drain()
        if self._index_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._index_task), timeout=3)
            except (TimeoutError, asyncio.CancelledError):
                self._index_task.cancel()

    async def context(self, event: ContextHookEvent, ctx: ExtensionContext) -> ContextResult | None:
        messages = [m for m in event.messages if not isinstance(m, _RecallMessage)]
        scope = Scope.for_project(ctx.cwd)
        if self.store.mode(scope) == "off":
            return (
                ContextResult(messages=messages) if len(messages) != len(event.messages) else None
            )
        user_index = next(
            (i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], UserMessage)),
            None,
        )
        if user_index is None:
            return None
        query = " ".join(c.text for c in messages[user_index].content if isinstance(c, TextContent))
        if not query.strip() or len(query.encode()) > 2000:
            return None
        try:
            result = await asyncio.to_thread(self.store.search, scope, query)
            rendered = render_context(result.hits)
            if not rendered or self.store.mode(scope) == "off":
                return None
        except (MemoryError, sqlite3.Error, OSError):
            return None
        messages.insert(user_index, _RecallMessage(content=[TextContent(text=rendered)]))
        return ContextResult(messages=messages)

    async def command(self, args: str, ctx: ExtensionContext) -> str:
        try:
            tokens = shlex.split(args)
            if any(t == "--project" or t.startswith("--project=") for t in tokens):
                raise MemoryError("Slash commands use the current host project.")
            if tokens and (tokens[0] == "help" or "--help" in tokens or "-h" in tokens):
                return parser().format_help()
            parsed = parser().parse_args(tokens or ["status"])
            await self.bind(ctx)
            assert self.scope is not None
            if parsed.command in {"off", "read", "forget"}:
                self.cancel()
            output = await asyncio.to_thread(run, self.store, self.scope, parsed)
            self.sync_tools()
            self.index_in_background()
            return terminal_text(output)
        except MemoryError as exc:
            return "Memory: " + terminal_text(str(exc))
        except (sqlite3.Error, OSError, ValueError):
            return "Memory unavailable: check the project path and user-owned storage."
        except SystemExit:
            return parser().format_help()

    async def tool(self, name: str, args: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        try:
            if self.scope is None:
                raise MemoryError("Memory is not bound to a host session.")
            if getattr(ctx.signal, "aborted", False):
                raise MemoryError("Memory operation cancelled.")
            if name == "memory_get":
                memory = await asyncio.to_thread(self.store.get, self.scope, args["id"], agent=True)
                return _result(memory.to_dict())
            if name != "memory_recall":
                raise MemoryError("Unknown memory tool.")
            result = await asyncio.to_thread(
                self.store.search,
                self.scope,
                args["query"],
                limit=args.get("limit", 5),
                as_of=args.get("as_of"),
            )
            hits = []
            for hit in result.hits:
                value = hit.to_dict()
                original = value["memory"]["content"]
                value["memory"]["content"] = original.encode()[:2000].decode(
                    "utf-8", errors="ignore"
                )
                value["preview"] = value["memory"]["content"] != original
                hits.append(value)
            data: dict[str, Any] = {
                "hits": hits,
                "warnings": result.warnings,
                "scores_are": "rank fusion relevance, not confidence",
            }
            while len(json.dumps(data, ensure_ascii=False).encode()) > 32768 and hits:
                hits.pop()
                data["truncated"] = True
            return _result(data)
        except MemoryError as exc:
            return _result({"error": str(exc)}, error=True)
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
            return _result({"error": "Memory unavailable or invalid arguments."}, error=True)


def register(api: ExtensionAPI, *, extractor: Extractor | None = None) -> MemoryExtension:
    extension = MemoryExtension(api, extractor=extractor)
    register_setting = getattr(api, "register_setting", None)
    if callable(register_setting):
        register_setting(
            "enabled",
            label="Memory",
            get_value=extension.memory_enabled,
            set_value=extension.set_memory_enabled,
            description="Use memory globally across projects and sessions. On learns and recalls automatically; off stops both.",
        )
    api.register_command(
        "memory",
        handler=extension.command,
        description="Turn natural memory on/off and optionally inspect, export or forget records.",
    )
    api.on("session_start", extension.session_start, error_mode="continue")
    api.on("before_agent_start", extension.before_start, error_mode="continue")
    api.on("context", extension.context, error_mode="continue")
    api.on("agent_end", extension.agent_end, error_mode="continue")
    api.on("session_shutdown", extension.session_shutdown, error_mode="continue")
    api.add_cleanup(extension.cancel)
    definitions = {
        "memory_recall": (
            "Retrieve current project memories and citations. Learning happens automatically; no memory write or approval tool is needed.",
            {
                "query": {"type": "string", "maxLength": 2000},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                "as_of": {"type": "string"},
            },
            ["query"],
        ),
        "memory_get": (
            "Open a full current project memory. Quoted evidence identifies its source passage; verify the claim against current evidence.",
            {"id": {"type": "string", "minLength": 8, "maxLength": 32}},
            ["id"],
        ),
    }
    for name, (description, properties, required) in definitions.items():

        async def execute(
            args: dict[str, Any], ctx: ToolExecutionContext, tool_name: str = name
        ) -> ToolResult:
            return await extension.tool(tool_name, args, ctx)

        api.register_tool(
            AgentTool(
                name=name,
                description=description,
                parameters={
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
                execute=execute,
            )
        )
    return extension
