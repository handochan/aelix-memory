"""Live startup summary, on-demand tools and automatic updates; synthetic data only."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path


async def verify(provider: str, model_id: str) -> dict:
    from dataclasses import replace

    from aelix_agent_core.harness.core import AgentHarness, AgentHarnessOptions
    from aelix_agent_core.session.memory_storage import MemorySessionStorage
    from aelix_agent_core.session.session import Session
    from aelix_ai.messages import AssistantMessage, TextContent, ToolCallContent
    from aelix_ai.oauth import AuthStorage
    from aelix_ai.streaming import stream_simple
    from aelix_coding_agent.builtin.permission import PermissionExtension
    from aelix_coding_agent.builtin.permission_mode import PermissionMode, PermissionPosture
    from aelix_coding_agent.cli.runtime_bootstrap import register_providers
    from aelix_coding_agent.extensions.api import Extension, ExtensionAPI, _ExtensionRuntime
    from aelix_coding_agent.model_registry import ModelRegistry

    from aelix_memory.extension import _RecallMessage, register
    from aelix_memory.models import Draft, now_iso
    from aelix_memory.scope import Scope
    from aelix_memory.store import Store

    def contents(messages):
        return "\n".join(c.text for m in messages for c in m.content if isinstance(c, TextContent))

    def calls(harness):
        return [
            c.tool_name
            for m in harness.state.messages
            if isinstance(m, AssistantMessage)
            for c in m.content
            if isinstance(c, ToolCallContent)
        ]

    register_providers()
    with tempfile.TemporaryDirectory(prefix="aelix-memory-session-live-") as directory:
        root = Path(directory)
        project = root / "project"
        project.mkdir()
        prior_home = os.environ.get("AELIX_MEMORY_HOME")
        prior_model = os.environ.pop("AELIX_MEMORY_EMBEDDING_MODEL", None)
        os.environ["AELIX_MEMORY_HOME"] = str(root / "memory")
        try:
            auth_storage = AuthStorage(root / "auth.json")
            await auth_storage.load()
            registry = ModelRegistry.in_memory(auth_storage)
            model = registry.find(provider, model_id)
            if model is None:
                raise ValueError("Model unavailable in existing registry.")
            auth = await registry.get_api_key_and_headers(model)
            if not auth.ok:
                raise ValueError("Existing provider authentication unavailable.")
            scope = Scope.for_project(project)
            store = Store(root / "memory")
            store.set_mode(scope, "on")
            # Four unrelated core facts ensure the learned procedure requires a detail lookup.
            for key, content in (
                ("package-manager", "Always use pnpm as the package manager in this project."),
                ("test-runner", "Always use pytest for this project's tests."),
                ("installer", "Always use uv for Python dependency installation."),
                ("commit-style", "Always use conventional commits in this project."),
            ):
                store.add(scope, Draft(key, content, "fixture://core", kind="preference", key=key))
            original = store.current_keys(scope)["package-manager"]
            cases = []

            def build():
                runtime = _ExtensionRuntime()
                runtime.bind_model_registry(registry)
                pack = Extension(name="aelix-memory")
                extension = register(ExtensionAPI(pack, runtime))
                permission = Extension(name="permission")
                PermissionExtension(posture=PermissionPosture(mode=PermissionMode.DEFAULT))(
                    ExtensionAPI(permission, runtime)
                )
                contexts = []

                async def stream(selected_model, context, options):
                    contexts.append(context)
                    options = replace(
                        options,
                        api_key=auth.api_key,
                        headers=dict(auth.headers),
                        max_tokens=256,
                        max_retries=0,
                    )
                    events = await stream_simple(selected_model, context, options)
                    try:
                        async for event in events:
                            yield event
                    finally:
                        close = getattr(events, "aclose", None)
                        if close:
                            await close()

                storage = MemorySessionStorage()
                harness = AgentHarness(
                    AgentHarnessOptions(
                        model=model,
                        extensions=[pack, permission],
                        runtime=runtime,
                        session=Session(storage),
                        cwd=str(project),
                        stream_fn=stream,
                        active_tool_names=["memory_recall", "memory_get"],
                        system_prompt="Answer concisely. Current user instructions override historical quoted memory.",
                    )
                )
                return harness, extension, contexts, storage

            async def turn(harness, extension, label, prompt, expected):
                await harness.prompt(prompt)
                await extension.learner.drain()
                reply = next(
                    m for m in reversed(harness.state.messages) if isinstance(m, AssistantMessage)
                )
                answer = contents([reply]).strip()
                cases.append(
                    {
                        "case": label,
                        "expected": expected,
                        "answer": answer,
                        "passed": answer == expected and not reply.error_message,
                    }
                )

            first, learner, _, first_storage = build()
            await first._emit_session_start("startup")
            await turn(
                first,
                learner,
                "automatic_procedure_learning",
                "The archive-recovery procedure for this project is: verify the manifest, "
                "restore the latest snapshot, run the ARCHIVE-731 checksum, and compare "
                "the recovered record count before resuming service. Respond only ACK.",
                "ACK",
            )
            await first._emit_session_shutdown("quit")
            target_hits = store.search(scope, "archive recovery ARCHIVE-731").hits
            if not target_hits:
                raise ValueError("Live automatic extraction produced no procedure.")
            target = target_hits[0].memory

            second, extension, contexts, second_storage = build()
            await second._emit_session_start("startup")
            await turn(second, extension, "unrelated_turn", "Reply only HELLO.", "HELLO")
            greeting_calls = calls(second)
            initial = next(m for m in contexts[0].messages if isinstance(m, _RecallMessage))
            detail_hidden = target.content not in contents([initial])
            await turn(
                second,
                extension,
                "on_demand_procedure_recall",
                "What exact quote was saved for the archive-recovery procedure? "
                "Return only the stored quote, verbatim, without quotation marks.",
                target.content,
            )
            lookup_calls = calls(second)
            lookup_tools = [tool.name for tool in contexts[1].tools]
            lookup_policy = "<aelix_memory_usage_policy>" in contexts[1].system_prompt
            prefix_preserved = (
                contexts[1].messages[: len(contexts[0].messages)] == contexts[0].messages
            )
            await turn(
                second,
                extension,
                "automatic_correction",
                "The package manager preference changed: use npm in this project instead of pnpm. Reply only ACK.",
                "ACK",
            )
            corrected = store.current_keys(scope).get("package-manager")
            await turn(
                second,
                extension,
                "same_session_corrected_answer",
                "Which package manager do I use now? Reply only with its name.",
                "npm",
            )
            after_read = store.current_keys(scope).get("package-manager")
            read_kept_revision = (
                corrected is not None and after_read is not None and corrected.id == after_read.id
            )
            current_summary = contents(
                [m for m in contexts[-1].messages if isinstance(m, _RecallMessage)]
            )
            old_removed = original.id not in current_summary
            update_not_injected = corrected is not None and corrected.id not in current_summary
            await second._emit_session_shutdown("quit")

            third, extension, latest, third_storage = build()
            await third._emit_session_start("startup")
            await turn(
                third,
                extension,
                "next_session_uses_updated_summary",
                "Which package manager do I use in this project? Reply only with its name.",
                "npm",
            )
            updated_summary = contents(
                [m for m in latest[0].messages if isinstance(m, _RecallMessage)]
            )
            next_session_updated = corrected is not None and corrected.id in updated_summary
            await third._emit_session_shutdown("quit")
            entries = await asyncio.gather(
                *(s.get_entries() for s in (first_storage, second_storage, third_storage))
            )
            ephemeral = all("<aelix_memory" not in str(value) for value in entries)
            updated = corrected is not None and corrected.id != original.id
            return {
                "at": now_iso(),
                "provider": provider,
                "model": model_id,
                "synthetic_data_only": True,
                "manual_fixture_core_records": 4,
                "manual_target_writes": 0,
                "per_memory_approvals": 0,
                "automatic_target_has_matched_quote": target.source_verification == "matched_quote",
                "unrelated_turn_tool_calls": greeting_calls,
                "on_demand_tool_calls": lookup_calls,
                "available_lookup_tools": lookup_tools,
                "trusted_lookup_policy_present": lookup_policy,
                "target_detail_absent_from_startup": detail_hidden,
                "stable_prefix_during_lookup": prefix_preserved,
                "superseded_summary_entry_removed": old_removed,
                "same_session_read_kept_preference_revision": read_kept_revision,
                "package_preference_after_read": {
                    "kind": after_read.kind if after_read else None,
                    "source_role": after_read.source_role if after_read else None,
                    "starts_with_question": after_read.content.lower().startswith("which ")
                    if after_read
                    else None,
                    "contains_npm": "npm" in after_read.content if after_read else False,
                },
                "updated_record_not_automatically_injected": update_not_injected,
                "next_session_uses_updated_summary": next_session_updated,
                "recall_not_persisted": ephemeral,
                "cases": cases,
                "passed": all(c["passed"] for c in cases)
                and not greeting_calls
                and bool(lookup_calls)
                and detail_hidden
                and prefix_preserved
                and updated
                and read_kept_revision
                and old_removed
                and update_not_injected
                and next_session_updated
                and ephemeral,
            }
        finally:
            for name, previous in (
                ("AELIX_MEMORY_HOME", prior_home),
                ("AELIX_MEMORY_EMBEDDING_MODEL", prior_model),
            ):
                if previous is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = previous


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(verify(args.provider, args.model))
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
