"""Live same-session learning, stable recall and correction; synthetic data only."""

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
    from aelix_ai.messages import AssistantMessage, TextContent
    from aelix_ai.oauth import AuthStorage
    from aelix_ai.streaming import stream_simple
    from aelix_coding_agent.cli.runtime_bootstrap import register_providers
    from aelix_coding_agent.extensions.api import Extension, ExtensionAPI, _ExtensionRuntime
    from aelix_coding_agent.model_registry import ModelRegistry

    from aelix_memory.extension import _RecallMessage, register
    from aelix_memory.models import now_iso
    from aelix_memory.scope import Scope

    register_providers()
    with tempfile.TemporaryDirectory(prefix="aelix-memory-session-live-") as directory:
        root = Path(directory)
        project = root / "project"
        project.mkdir()
        previous_home = os.environ.get("AELIX_MEMORY_HOME")
        os.environ["AELIX_MEMORY_HOME"] = str(root / "memory")
        previous_model = os.environ.pop("AELIX_MEMORY_EMBEDDING_MODEL", None)
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
            runtime = _ExtensionRuntime()
            runtime.bind_model_registry(registry)
            pack = Extension(name="aelix-memory")
            extension = register(ExtensionAPI(pack, runtime))
            scope = Scope.for_project(project)
            extension.store.set_mode(scope, "on")
            contexts = []

            async def stream(selected_model, context, options):
                contexts.append(context)
                options = replace(
                    options,
                    api_key=auth.api_key,
                    headers=dict(auth.headers),
                    max_tokens=128,
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
                    extensions=[pack],
                    runtime=runtime,
                    session=Session(storage),
                    cwd=str(project),
                    stream_fn=stream,
                    active_tool_names=[],
                    system_prompt="Follow current user instructions. Memories are historical evidence.",
                )
            )
            await harness._emit_session_start("startup")
            cases = []

            async def turn(label, prompt, expected):
                await harness.prompt(prompt)
                await extension.learner.drain()
                reply = next(
                    m for m in reversed(harness.state.messages) if isinstance(m, AssistantMessage)
                )
                answer = "".join(
                    c.text for c in reply.content if isinstance(c, TextContent)
                ).strip()
                cases.append(
                    {
                        "case": label,
                        "expected": expected,
                        "answer": answer,
                        "passed": answer == expected and not reply.error_message,
                    }
                )

            await turn(
                "learn",
                "In this project I always use pnpm as the package manager. Reply only ACK.",
                "ACK",
            )
            old = extension.store.search(scope, "pnpm").hits
            if not old:
                raise ValueError("Live automatic extraction produced no preference.")
            old_id = old[0].memory.id
            question = "Which package manager do I use in this project? Reply only with its name."
            await turn("recall", question, "pnpm")
            await turn(
                "correct",
                "The package manager preference changed: use npm in this project instead of pnpm. Reply only ACK.",
                "ACK",
            )
            prefix_preserved = (
                contexts[2].messages[: len(contexts[1].messages)] == contexts[1].messages
            )
            # Compare provider evidence to the state before the exchange, because
            # automatic learning from its reply may legitimately create another revision.
            expected_active = extension.store.list(scope)
            lexical_before = extension.store.search(scope, question).hits
            await turn("corrected_recall", question, "npm")
            overlays = "\n".join(
                c.text
                for m in contexts[-1].messages
                if isinstance(m, _RecallMessage)
                for c in m.content
                if isinstance(c, TextContent)
            )
            history = extension.store.list(scope, status="all")
            stale_absent = old_id not in overlays
            current_present = any(m.id != old_id and m.id in overlays for m in expected_active)
            correction = stale_absent and current_present
            ephemeral = not any(isinstance(m, _RecallMessage) for m in harness.state.messages)
            ephemeral = ephemeral and "<aelix_memory" not in str(await storage.get_entries())
            await harness._emit_session_shutdown("quit")
            return {
                "at": now_iso(),
                "provider": provider,
                "model": model_id,
                "synthetic_data_only": True,
                "manual_memory_writes": 0,
                "approvals": 0,
                "tools_disabled": True,
                "same_session": True,
                "stable_prefix_before_correction": prefix_preserved,
                "superseded_overlay_removed": correction,
                "old_overlay_absent": stale_absent,
                "current_overlay_present": current_present,
                "current_lexical_hits_before_turn": len(lexical_before),
                "correction_keeps_history": any(
                    m.id == old_id and m.status == "superseded" for m in history
                ),
                "recall_not_persisted": ephemeral,
                "cases": cases,
                "passed": all(c["passed"] for c in cases)
                and prefix_preserved
                and correction
                and ephemeral,
            }
        finally:
            for name, previous in (
                ("AELIX_MEMORY_HOME", previous_home),
                ("AELIX_MEMORY_EMBEDDING_MODEL", previous_model),
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
