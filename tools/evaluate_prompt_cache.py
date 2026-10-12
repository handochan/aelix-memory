"""Compare 0.3.0 recall with a fixed startup summary; optional live cache usage."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path


async def compare(provider: str | None, model_id: str | None) -> dict:
    from types import SimpleNamespace

    from aelix_agent_core.harness.hooks import ContextHookEvent
    from aelix_ai.messages import AssistantMessage, TextContent, UserMessage
    from aelix_ai.providers.openai_codex_responses import build_request_body
    from aelix_ai.streaming import (
        AssistantDoneEvent,
        Context,
        Model,
        SimpleStreamOptions,
        stream_simple,
    )
    from aelix_coding_agent.extensions.api import (
        Extension,
        ExtensionAPI,
        ExtensionContext,
        _ExtensionRuntime,
    )

    from aelix_memory.context import render_context
    from aelix_memory.extension import MemoryExtension, _RecallMessage
    from aelix_memory.models import Draft
    from aelix_memory.scope import Scope
    from aelix_memory.startup import usage_prompt
    from aelix_memory.store import Store

    def wire(context):
        body = build_request_body(
            Model(id="test", provider="openai-codex"),
            context,
            SimpleStreamOptions(session_id="stable"),
        )
        header = json.dumps(
            {"instructions": body["instructions"], "tools": body.get("tools", [])}, sort_keys=True
        )
        return (
            header
            + "\n"
            + "\n".join(
                json.dumps(item, sort_keys=True, ensure_ascii=False) for item in body["input"]
            )
        ).encode()

    def prefix(left, right):
        for index, (a, b) in enumerate(zip(left, right, strict=False)):
            if a != b:
                return index
        return min(len(left), len(right))

    with tempfile.TemporaryDirectory(prefix="aelix-memory-cache-eval-") as directory:
        root = Path(directory)
        project = root / "project"
        project.mkdir()
        scope = Scope.for_project(project)
        store = Store(root / "memory")
        store.set_mode(scope, "on")
        store.add(scope, Draft("Runner", "Use pytest for tests.", "user-command"))
        store.add(scope, Draft("Installer", "Use uv for packages.", "user-command"))
        runtime = _ExtensionRuntime()
        api = ExtensionAPI(Extension(name="cache-eval"), runtime)
        extension = MemoryExtension(api)
        extension.store = store
        extension.session_id = "evaluation"
        ctx = ExtensionContext(
            runtime,
            cwd=str(project),
            model=None,
            is_idle=lambda: True,
            abort=lambda: None,
            get_active_tools=lambda: [],
            get_system_prompt=lambda: "",
            session_manager=SimpleNamespace(get_session=lambda: None),
        )
        history = []
        # Useful fixture reference text supplies a long shared prefix; production is never padded.
        static = "Answer concisely; project memory is quoted historical evidence.\n" + "\n".join(
            f"Reference section {i}: preserve scoped records, validate exact revisions, and use explicit data types."
            for i in range(120)
        )
        contexts = {"baseline": [], "improved": []}
        prompts = [
            "Which pytest runner?",
            "Which uv installer?",
            "Explain pytest fixtures.",
            "Explain uv packages.",
        ]
        for index, prompt in enumerate(prompts):
            history.append(UserMessage(content=[TextContent(text=prompt)], timestamp=index + 1))
            old = list(history)
            rendered = render_context(store.search(scope, prompt).hits)
            if rendered:
                old.insert(len(old) - 1, _RecallMessage(content=[TextContent(text=rendered)]))
            result = await extension.context(ContextHookEvent(messages=list(history)), ctx)
            new = result.messages if result else list(history)
            contexts["baseline"].append(Context(system_prompt=static, messages=old, tools=[]))
            contexts["improved"].append(
                Context(system_prompt=usage_prompt(static, enabled=True), messages=new, tools=[])
            )
            history.append(
                AssistantMessage(
                    content=[TextContent(text=("Synthetic response about the project. " * 150))]
                )
            )
        structural = {}
        for variant, series in contexts.items():
            pairs = []
            for earlier, later in zip(series, series[1:], strict=False):
                a, b = wire(earlier), wire(later)
                count = prefix(a, b)
                pairs.append(
                    {
                        "previous_bytes": len(a),
                        "shared_prefix_bytes": count,
                        "previous_prefix_preserved": count == len(a),
                    }
                )
            structural[variant] = pairs
        assert all(p["previous_prefix_preserved"] for p in structural["improved"])
        assert not any(p["previous_prefix_preserved"] for p in structural["baseline"])
        report = {
            "synthetic_data_only": True,
            "implementation": "fixed startup summary; no per-turn automatic retrieval",
            "metric": "serialized visible input bytes, not cache tokens",
            "structural": structural,
            "live": None,
        }
        if provider:
            from aelix_ai.oauth import AuthStorage
            from aelix_coding_agent.cli.runtime_bootstrap import register_providers
            from aelix_coding_agent.model_registry import ModelRegistry

            register_providers()
            auth_storage = AuthStorage(root / "auth.json")
            await auth_storage.load()
            registry = ModelRegistry.in_memory(auth_storage)
            model = registry.find(provider, model_id)
            if model is None:
                raise ValueError(
                    "Model unavailable in existing registry; specify an available provider/model."
                )
            auth = await registry.get_api_key_and_headers(model)
            if not auth.ok:
                raise ValueError("Existing provider authentication unavailable.")
            live = {}
            for variant, series in contexts.items():
                usages = []
                for context in series:
                    # Distinct prefixes prevent the baseline from warming the improved fixture.
                    live_context = Context(
                        system_prompt=f"Evaluation fixture {root.name}/{variant}.\n"
                        + context.system_prompt,
                        messages=context.messages,
                        tools=context.tools,
                    )
                    options = SimpleStreamOptions(
                        api_key=auth.api_key,
                        headers=dict(auth.headers),
                        max_tokens=32,
                        max_retries=0,
                        session_id=f"memory-cache-eval:{root.name}:{variant}",
                    )
                    stream = await stream_simple(model, live_context, options)
                    final = None
                    try:
                        async for event in stream:
                            if isinstance(event, AssistantDoneEvent):
                                final = event.message
                    finally:
                        close = getattr(stream, "aclose", None)
                        if close:
                            await close()
                    if final is None or final.error_message:
                        raise ValueError("Live provider did not return a successful response.")
                    usage = final.usage or {}
                    details = (
                        usage.get("prompt_tokens_details")
                        or usage.get("input_tokens_details")
                        or {}
                    )
                    usages.append(
                        {
                            "input": usage.get(
                                "input", usage.get("prompt_tokens", usage.get("input_tokens"))
                            ),
                            "output": usage.get(
                                "output", usage.get("completion_tokens", usage.get("output_tokens"))
                            ),
                            "cache_read": usage.get(
                                "cache_read",
                                details.get("cached_tokens", usage.get("cache_read_input_tokens")),
                            ),
                            "cache_write": usage.get(
                                "cache_write", usage.get("cache_creation_input_tokens")
                            ),
                        }
                    )
                live[variant] = usages
            report["live"] = {
                "provider": provider,
                "model": model_id,
                "usage": live,
                "note": "Observed fixture usage; retention, routing and backend policy affect hits.",
            }
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(compare(args.provider, args.model))
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
