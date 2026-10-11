"""Optional management through public host dialogs; no host imports or patches."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import unicodedata
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol

from .cli import terminal_text
from .models import Memory, MemoryError
from .scope import Scope
from .store import Store


class PanelUI(Protocol):
    async def select(self, title: str, options: list[str]) -> str | None: ...
    async def input(self, title: str, placeholder: str | None = None) -> str | None: ...
    async def editor(self, title: str, prefill: str | None = None) -> str | None: ...
    async def confirm(self, title: str, message: str) -> bool: ...


def one_line(value: str, width: int = 44) -> str:
    value = " ".join(terminal_text(value).split())
    out, cells = "", 0
    for char in value:
        size = 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        if cells + size > width:
            return out + "…"
        out += char
        cells += size
    return out


def page_lines(value: str, width: int = 48) -> list[str]:
    lines: list[str] = []
    for line in terminal_text(value).expandtabs(4).splitlines():
        current, cells = "", 0
        for char in line:
            size = 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
            if cells + size > width:
                lines.append(current)
                current, cells = "", 0
            current += char
            cells += size
        lines.append(current)
    return lines or ["No data."]


class MemoryPanel:
    def __init__(
        self,
        store: Store,
        scope: Scope,
        ui: PanelUI,
        execute: Callable[[list[str]], Awaitable[str]],
    ) -> None:
        self.store, self.scope, self.ui, self.execute = store, scope, ui, execute

    async def message(self, title: str, content: str) -> None:
        lines = page_lines(content)
        pages = [lines[i : i + 4] for i in range(0, len(lines), 4)]
        index = 0
        while True:
            options = ["Back"]
            if index + 1 < len(pages):
                options.insert(0, "Next page")
            if index:
                options.insert(0, "Previous page")
            heading = f"{one_line(title)} ({index + 1}/{len(pages)})"
            choice = await self.ui.select(heading + "\n" + "\n".join(pages[index]), options)
            if choice == "Next page":
                index += 1
            elif choice == "Previous page":
                index -= 1
            else:
                return

    async def open(self) -> str:
        while True:
            mode = await asyncio.to_thread(self.store.global_mode)
            usage = "OFF" if mode == "off" else "ON"
            learning = {"on": "automatic", "read": "recall only", "off": "disabled"}[mode]
            toggle = f"Memory: {usage} (global)"
            modes = f"Learning mode: {learning}"
            options = [
                toggle,
                modes,
                "Browse memories",
                "Search memories",
                "Remember something",
                "Export project memories",
                "Details and advanced options",
                "Close",
            ]
            choice = await self.ui.select(
                f"Memory — {one_line(self.scope.root.name, 24)}\nKnowledge stays in this project.",
                options,
            )
            if choice is None or choice == "Close":
                return "Memory panel closed."
            try:
                if choice == toggle:
                    # The displayed ON row means OFF even if another process changed it.
                    await self.execute(["on" if mode == "off" else "off"])
                elif choice == modes:
                    await self.modes()
                elif choice == "Browse memories":
                    await self.browse()
                elif choice == "Search memories":
                    query = await self.ui.input("Search this project's memories")
                    if query and query.strip():
                        result = await asyncio.to_thread(
                            self.store.search, self.scope, query, limit=20, agent=False
                        )
                        if result.warnings:
                            await self.message("Search information", "\n".join(result.warnings))
                        await self.choose_memory([hit.memory for hit in result.hits])
                elif choice == "Remember something":
                    await self.edit()
                elif choice == "Export project memories":
                    destination = await self.ui.input("Export JSON path (existing files are kept)")
                    if destination and destination.strip():
                        path = Path(destination.strip()).expanduser()
                        if not path.is_absolute():
                            path = self.scope.root / path
                        await self.message(
                            "Export", await self.execute(["export", f"--output={path}"])
                        )
                elif choice == "Details and advanced options":
                    await self.advanced()
            except MemoryError as exc:
                await self.message("Memory", str(exc))
            except (sqlite3.Error, OSError, ValueError):
                await self.message(
                    "Memory unavailable", "Check the project path and user-owned storage."
                )

    async def modes(self) -> None:
        modes = {
            "ON — automatically learn and recall": "on",
            "READ — recall without automatic learning": "read",
            "OFF — stop all memory usage": "off",
        }
        choice = await self.ui.select("Memory usage applies globally", [*modes, "Back"])
        if choice in modes:
            await self.execute([modes[choice]])

    async def browse(self, *, status: str = "active") -> None:
        limit = 50
        while True:
            memories = await asyncio.to_thread(
                self.store.list, self.scope, status=status, limit=limit
            )
            more = len(memories) == limit and limit < 10000
            if await self.choose_memory(memories, more=more) != "more":
                return
            limit = min(limit * 2, 10000)

    async def choose_memory(self, memories: list[Memory], *, more: bool = False) -> str | None:
        if not memories:
            await self.message("Project memories", "No matching memories in this project.")
            return None
        choices = {
            f"{i + 1}. {one_line(memory.title, 32)} [{memory.status}]": memory.id
            for i, memory in enumerate(memories)
        }
        while True:
            options = [*choices, *(["Load more"] if more else []), "Back"]
            choice = await self.ui.select("Project memories — select to inspect", options)
            if choice == "Load more":
                return "more"
            if choice not in choices:
                return None
            if await self.memory(choices[choice]):
                return None

    async def memory(self, mid: str) -> bool:
        while True:
            memory = await asyncio.to_thread(self.store.get, self.scope, mid)
            options = ["View content and source", "Revision history"]
            if memory.status == "pending":
                options.extend(["Approve legacy proposal", "Discard legacy proposal"])
            elif memory.status == "active":
                options.append("Edit memory")
            options.extend(["Forget entire memory history", "Back"])
            choice = await self.ui.select(one_line(memory.title), options)
            if choice == "View content and source":
                await self.message(
                    "Memory details", json.dumps(memory.to_dict(), ensure_ascii=False, indent=2)
                )
            elif choice == "Revision history":
                history = await asyncio.to_thread(self.store.history, self.scope, mid)
                await self.message(
                    "Revision history",
                    json.dumps([m.to_dict() for m in history], ensure_ascii=False, indent=2),
                )
            elif choice == "Edit memory":
                if await self.edit(memory):
                    return True
            elif choice == "Forget entire memory history":
                if await self.ui.confirm(
                    "Forget this memory?",
                    "Deletes this project's record and all revisions. Exports and backups remain.",
                ):
                    await self.message("Memory forgotten", await self.execute(["forget", mid]))
                    return True
            elif choice == "Approve legacy proposal":
                await self.execute(["approve", mid])
                return True
            elif choice == "Discard legacy proposal":
                await self.execute(["discard", mid])
                return True
            else:
                return False

    async def edit(self, memory: Memory | None = None) -> bool:
        title = await self.ui.input("Memory title", memory.title if memory else None)
        if title is None:
            return False
        content = await self.ui.editor(
            "Memory content — submit to save, Esc to cancel", memory.content if memory else None
        )
        if content is None:
            return False
        if (
            memory
            and content == memory.content
            and (not title.strip() or title.strip() == memory.title)
        ):
            return False
        tokens = ["update", memory.id] if memory else ["remember"]
        if title.strip():
            tokens.append(f"--title={title.strip()}")
        if memory and memory.expires_at:
            tokens.append(f"--expires={memory.expires_at}")
        tokens.extend(["--", content])
        await self.execute(tokens)
        await self.message("Memory saved", "Saved in this project. Global usage mode is unchanged.")
        return True

    async def advanced(self) -> None:
        options = [
            "Status and storage",
            "All records and history",
            "Legacy pending proposals",
            "Rebuild local semantic index",
            "Command help",
            "Back",
        ]
        while True:
            choice = await self.ui.select("Memory details and advanced options", options)
            if choice == "Status and storage":
                status = await self.execute(["status"])
                await self.message("Memory status", status)
            elif choice == "All records and history":
                await self.browse(status="all")
            elif choice == "Legacy pending proposals":
                await self.browse(status="pending")
            elif choice == "Rebuild local semantic index":
                await self.message("Semantic index", await self.execute(["reindex"]))
            elif choice == "Command help":
                await self.message("Memory commands", await self.execute(["help"]))
            else:
                return
