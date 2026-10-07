"""Aelix adapter. All memory access uses the public extension lifecycle and tool gate."""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import sqlite3
from typing import Any, cast

from aelix_agent_core.harness.hooks import (
    BeforeAgentStartHookEvent,
    ContextHookEvent,
    ContextResult,
    SessionStartHookEvent,
)
from aelix_agent_core.types import AgentTool
from aelix_ai.messages import TextContent, UserMessage
from aelix_ai.tools import ToolExecutionContext, ToolResult
from aelix_coding_agent.extensions.api import ExtensionAPI, ExtensionContext

from .cli import configured_store, terminal_text
from .commands import parser, run
from .context import render_context
from .models import Draft, Kind, MemoryError
from .scope import Scope

_TOOL_NAMES = ("memory_recall", "memory_get", "memory_propose")
_LOG = logging.getLogger(__name__)


class _RecallMessage(UserMessage):
    """A transient marker; never appended to the durable session by this extension."""


def _result(data: Any, *, error: bool = False) -> ToolResult:
    text = json.dumps(data, ensure_ascii=False)
    return ToolResult(content=[TextContent(text=text)], details=data, is_error=error)


class MemoryExtension:
    def __init__(self, api: ExtensionAPI) -> None:
        self.api = api
        self.store = configured_store()
        self.scope: Scope | None = None
        self.session_id: str | None = None
        self._permitted_tools: set[str] | None = None
        self._last_tools: set[str] = set()

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
            # Preserve explicit host --tools/--no-tools and later user tool choices.
            self._permitted_tools.difference_update(self._last_tools - current)
            self._permitted_tools.update(current - self._last_tools)
        desired = [name for name in active if name not in _TOOL_NAMES]
        if mode != "off":
            desired.extend(name for name in _TOOL_NAMES[:2] if name in self._permitted_tools)
        if mode == "on" and "memory_propose" in self._permitted_tools:
            desired.append("memory_propose")
        self._last_tools = set(desired).intersection(_TOOL_NAMES)
        if desired != active:
            self.api.set_active_tools(desired)

    async def session_start(self, _event: SessionStartHookEvent, ctx: ExtensionContext) -> None:
        await self.bind(ctx)

    async def before_start(self, _event: BeforeAgentStartHookEvent, ctx: ExtensionContext) -> None:
        await self.bind(ctx)

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
        query = " ".join(
            block.text for block in messages[user_index].content if isinstance(block, TextContent)
        )
        if not query.strip() or len(query.encode()) > 2000:
            return None
        try:
            result = await asyncio.to_thread(self.store.search, scope, query)
            for warning in result.warnings:
                _LOG.warning(warning)
                if ctx.has_ui:
                    ctx.ui.notify(warning, "warning")
            rendered = render_context(result.hits)
            # Recheck after retrieval before adding evidence to a provider request.
            if not rendered or self.store.mode(scope) == "off":
                return None
        except (MemoryError, sqlite3.Error, OSError):
            if ctx.has_ui:
                ctx.ui.notify(
                    "Memory recall unavailable; this turn continues without it.", "warning"
                )
            return None
        messages.insert(user_index, _RecallMessage(content=[TextContent(text=rendered)]))
        return ContextResult(messages=messages)

    async def command(self, args: str, ctx: ExtensionContext) -> str:
        try:
            # Slash commands cannot choose another project's path via --project.
            tokens = shlex.split(args)
            if any(t == "--project" or t.startswith("--project=") for t in tokens):
                raise MemoryError("Slash commands use the current host project.")
            if not tokens or tokens[0] == "help":
                if tokens:
                    return parser().format_help()
                tokens = ["status"]
            if "--help" in tokens or "-h" in tokens:
                return parser().format_help()
            parsed = parser().parse_args(tokens)
            await self.bind(ctx)
            assert self.scope is not None
            output = await asyncio.to_thread(run, self.store, self.scope, parsed)
            self.sync_tools()
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
            if name == "memory_recall":
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
                data = {
                    "hits": hits,
                    "warnings": result.warnings,
                    "scores_are": "rank fusion relevance, not confidence",
                }
                while len(json.dumps(data, ensure_ascii=False).encode()) > 32768 and hits:
                    hits.pop()
                    data["truncated"] = True
                return _result(data)
            if name == "memory_get":
                memory = await asyncio.to_thread(self.store.get, self.scope, args["id"], agent=True)
                return _result(memory.to_dict())
            draft = Draft(
                title=args["title"],
                content=args["content"],
                source_ref=args["source_ref"],
                kind=cast(Kind, args.get("kind", "fact")),
                key=args.get("key"),
                tags=tuple(args.get("tags", ())),
                related_ids=tuple(args.get("related_ids", ())),
                expires_at=args.get("expires_at"),
            )
            memory = await asyncio.to_thread(
                self.store.add,
                self.scope,
                draft,
                origin="agent",
                supersedes=args.get("supersedes"),
                source_session=self.session_id,
                source_call=ctx.tool_call_id or None,
            )
            return _result(
                {
                    "id": memory.id,
                    "status": "pending",
                    "instruction": f"Not saved as active memory. The user may inspect /memory show {memory.id} and approve /memory approve {memory.id}.",
                }
            )
        except MemoryError as exc:
            return _result({"error": str(exc)}, error=True)
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
            return _result(
                {"error": "Memory unavailable or invalid arguments; no active memory was added."},
                error=True,
            )


def register(api: ExtensionAPI) -> None:
    extension = MemoryExtension(api)
    api.register_command(
        "memory",
        handler=extension.command,
        description="Choose mode, inspect, approve, update, export and forget project memory.",
    )
    api.on("session_start", extension.session_start, error_mode="continue")
    api.on("before_agent_start", extension.before_start, error_mode="continue")
    api.on("context", extension.context, error_mode="continue")
    definitions = {
        "memory_recall": (
            "Retrieve user-approved project evidence. Returns citations; missing results mean no evidence. Current user instructions take precedence. Optional as_of requests historical evidence.",
            {
                "query": {"type": "string", "maxLength": 2000},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                "as_of": {"type": "string"},
            },
            ["query"],
        ),
        "memory_get": (
            "Open a full current, approved memory by its ID. Source pointers are declared, not verified; inspect the source before relying on it.",
            {"id": {"type": "string", "minLength": 8, "maxLength": 32}},
            ["id"],
        ),
        "memory_propose": (
            "Propose one durable lesson or preference for user review. Requires memory ON. Never capture secrets or raw transcripts. This does not save active memory; only the user can approve. A keyed replacement requires the previous ID in supersedes.",
            {
                "title": {"type": "string", "maxLength": 240},
                "content": {"type": "string", "maxLength": 8000},
                "source_ref": {"type": "string", "maxLength": 1000},
                "kind": {"type": "string", "enum": ["fact", "preference", "procedure", "episode"]},
                "key": {"type": "string", "maxLength": 200},
                "tags": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 80},
                    "maxItems": 16,
                },
                "related_ids": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 32},
                    "maxItems": 10,
                },
                "expires_at": {"type": "string"},
                "supersedes": {"type": "string", "minLength": 8, "maxLength": 32},
            },
            ["title", "content", "source_ref"],
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
