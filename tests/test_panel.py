"""User actions through the panel preserve the real SQLite contracts."""

import asyncio
import json

import pytest

from aelix_memory.commands import parser, run
from aelix_memory.models import ConflictError, Draft
from aelix_memory.panel import MemoryPanel, page_lines
from aelix_memory.scope import Scope


class UI:
    def __init__(self, selections=(), inputs=(), edits=(), confirms=()):
        self.selections = iter(selections)
        self.inputs = iter(inputs)
        self.edits = iter(edits)
        self.confirms = iter(confirms)
        self.dialogs = []

    async def select(self, title, options):
        self.dialogs.append((title, options))
        choice = next(self.selections)
        if callable(choice):
            choice = choice(title, options)
        assert choice is None or choice in options, (choice, options)
        return choice

    async def input(self, title, placeholder=None):
        return next(self.inputs)

    async def editor(self, title, prefill=None):
        choice = next(self.edits)
        return choice() if callable(choice) else choice

    async def confirm(self, title, message):
        return next(self.confirms)


def panel(store, scope, ui):
    async def execute(tokens):
        return await asyncio.to_thread(run, store, scope, parser().parse_args(tokens))

    return MemoryPanel(store, scope, ui, execute)


async def test_open_status_browse_search_and_cancel_leave_no_store(store, scope):
    ui = UI(
        [
            "Browse memories",
            "Back",
            "Search memories",
            "Back",
            "Details and advanced options",
            "Status and storage",
            "Back",
            "Back",
            None,
        ],
        inputs=["missing"],
    )
    assert await panel(store, scope, ui).open() == "Memory panel closed."
    assert not store.home.exists()
    assert not any("Approve" in option for _, options in ui.dialogs for option in options)


@pytest.mark.parametrize("initial,target", [("on", "off"), ("off", "on"), ("read", "off")])
async def test_displayed_toggle_intent_survives_an_external_change(
    store, scope, tmp_path, initial, target
):
    other = tmp_path / "other-project"
    other.mkdir()
    other_scope = Scope.for_project(other)
    store.set_mode(scope, initial)

    def external_change(title, options):
        store.set_mode(other_scope, target)
        return options[0]

    ui = UI([external_change, "Close"])
    await panel(store, scope, ui).open()
    assert store.mode(scope) == store.mode(other_scope) == target


async def test_recall_only_and_back_are_persistent_and_explicit(store, scope):
    ui = UI(["Learning mode: disabled", "READ — recall without automatic learning", "Close"])
    await panel(store, scope, ui).open()
    assert store.global_mode() == "read"
    before = store.path.read_bytes()
    await panel(store, scope, UI(["Learning mode: recall only", "Back", "Close"])).open()
    assert store.path.read_bytes() == before


async def test_browse_and_search_never_expose_other_projects_and_reads_keep_bytes(
    enabled, scope, tmp_path
):
    saved = enabled.add(scope, Draft("Package manager", "Use pnpm.", "user-command"))
    other = tmp_path / "other"
    other.mkdir()
    enabled.add(Scope.for_project(other), Draft("Other secret", "Use yarn.", "user-command"))
    before = enabled.path.read_bytes()
    ui = UI(
        [
            "Browse memories",
            lambda _, opts: opts[0],
            "View content and source",
            "Back",
            "Back",
            "Back",
            "Search memories",
            "Back",
            "Close",
        ],
        inputs=["pnpm"],
    )
    await panel(enabled, scope, ui).open()
    rendered = "\n".join(title + "\n" + "\n".join(options) for title, options in ui.dialogs)
    assert saved.title in rendered and "Other secret" not in rendered and "yarn" not in rendered
    assert enabled.path.read_bytes() == before


async def test_manual_create_edit_history_forget_and_export_use_same_project(enabled, scope):
    created = panel(
        enabled,
        scope,
        UI(["Remember something", "Back", "Close"], inputs=["Runner"], edits=["Use pytest."]),
    )
    await created.open()
    memory = enabled.list(scope)[0]
    assert memory.title == "Runner" and memory.origin == "user"
    edited = panel(enabled, scope, UI(["Back"], inputs=[""], edits=["Use uv run pytest."]))
    assert await edited.edit(memory)
    current = enabled.list(scope)[0]
    assert current.title == memory.title and len(enabled.history(scope, current.id)) == 2
    destination = scope.root / "saved.json"
    await panel(
        enabled, scope, UI(["Export project memories", "Back", "Close"], inputs=["saved.json"])
    ).open()
    assert len(json.loads(destination.read_text())["memories"]) == 2
    original = destination.read_bytes()
    await panel(
        enabled, scope, UI(["Export project memories", "Back", "Close"], inputs=["saved.json"])
    ).open()
    assert destination.read_bytes() == original
    await panel(
        enabled,
        scope,
        UI(
            [
                "Browse memories",
                lambda _, opts: opts[0],
                "Forget entire memory history",
                "Back",
                "Close",
            ],
            confirms=[True],
        ),
    ).open()
    assert enabled.list(scope, status="all") == []


async def test_cancelled_edit_and_declined_forget_do_not_modify_records(enabled, scope):
    memory = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command"))
    before = enabled.path.read_bytes()
    assert not await panel(enabled, scope, UI(inputs=["New title"], edits=[None])).edit(memory)
    await panel(
        enabled,
        scope,
        UI(
            [
                "Browse memories",
                lambda _, opts: opts[0],
                "Forget entire memory history",
                "Back",
                "Back",
                "Close",
            ],
            confirms=[False],
        ),
    ).open()
    assert enabled.path.read_bytes() == before


async def test_delayed_edit_cannot_replace_a_newer_revision(enabled, scope):
    memory = enabled.add(scope, Draft("Runner", "Use pytest.", "user-command", key="runner"))

    def concurrent_edit():
        enabled.add(
            scope,
            Draft("Runner", "Use unittest.", "user-command", key="runner"),
            supersedes=memory.id,
        )
        return "Use nose."

    with pytest.raises(ConflictError):
        await panel(enabled, scope, UI(inputs=[""], edits=[concurrent_edit])).edit(memory)
    assert enabled.list(scope)[0].content == "Use unittest."


async def test_user_text_cannot_inject_project_or_command_options(enabled, scope):
    ui = UI(["Back"], inputs=["--project=/tmp/foreign"], edits=["--project /tmp/foreign"])
    assert await panel(enabled, scope, ui).edit()
    memory = enabled.list(scope)[0]
    assert memory.title == "--project=/tmp/foreign" and memory.scope == scope.id


async def test_details_are_bounded_paginated_and_strip_terminal_controls(store, scope):
    ui = UI(["Next page", "Previous page", "Back"])
    await panel(store, scope, ui).message("Info", "\x1b[31m" + "한글" * 120)
    assert len(ui.dialogs) == 3
    assert all(len(title.splitlines()) <= 5 for title, _ in ui.dialogs)
    assert all("\x1b" not in title for title, _ in ui.dialogs)
    assert len(page_lines("a" * 150)) == 4


async def test_reindex_failure_is_visible_without_creating_files(store, scope):
    ui = UI(["Details and advanced options", "Rebuild local semantic index", "Back", "Close"])
    await panel(store, scope, ui).open()
    assert any("AELIX_MEMORY_EMBEDDING_MODEL" in title for title, _ in ui.dialogs)
    assert not store.home.exists()
