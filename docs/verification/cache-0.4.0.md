# Cache-stable recall verification (0.4.0)

Date: 2026-10-11. Local platform: macOS arm64, CPython 3.12.13.
Only the extension was changed. No host source, release or provider cache policy
was modified. Storage and consent contracts remain unchanged.

## Source and installed artifact

- `uv run pytest`: **123 passed, 1 skipped** (optional provisioned semantic model).
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`: pass.
- `uv build`: sdist and `aelix_memory-0.4.0-py3-none-any.whl`.
  Local wheel SHA256: `5560991522c7af66d6fb656912b1e302a6042a09c13f9e783102cda9a1ab051b`.
- Existing real host wheels, installed memory wheel (imports resolve to
  site-packages), already provisioned multilingual MiniLM with
  `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`: **124 passed in 5.16s**.
  `aelix extension verify aelix-memory`: all one endpoint **BOUND**, exit 0.
- Unchanged published PyPI `aelix[tui]==0.1.0b2`, installed memory wheel:
  **15 cache/host regressions + 4 panel regressions pass**; manifest is **BOUND**.
  The host does not expose `register_setting`; no new host API is required.
- Both manifest checks use temporary agent/settings/memory locations. Loading an
  OFF extension creates no memory directory. No user auth file is touched.

Actual converter tests cover Codex `build_request_body`, OpenAI Responses
`build_params`, and Claude `transform_messages`. They assert identical earlier
input items across turns. Other regressions cover tool iterations (one search),
duplicate user messages, deletion, correction, expiry, compaction, lifecycle reset,
bounded eviction, non-persistent recall, and concurrent OFF/ON or forget/revision
while retrieval is suspended. Cache correctness is not inferred from a stable key.

## Structural comparison

`tools/evaluate_prompt_cache.py` compares the old latest-only placement against
the new implementation through the real Codex request converter. Four synthetic
user turns alternate pytest/uv records. Fixed reference material supplies a long
fixture prefix; production prompts are never padded. Synthetic assistant history
keeps both variants' non-memory input identical. The metric serializes visible
instructions/tools and individual input items; it is **bytes, not cache tokens**.

| Prior request | 0.3.0 shared / prior bytes | 0.4.0 shared / prior bytes |
| --- | --- | --- |
| First → second | 12,490 / 13,395 | 13,395 / 13,395 |
| Second → third | 18,427 / 19,333 | 20,176 / 20,176 |
| Third → fourth | 24,363 / 25,272 | 26,117 / 26,117 |

All three improved requests preserve the complete previous visible input prefix;
none of the baseline pairs do. Retained snippets increase total input size; this
measurement alone does not establish savings.

## Live cache usage

[cache-live.json](cache-live.json) records eight actual OpenRouter
`openai/gpt-5.4-mini` requests with a 32-token output cap, four per variant.
Each variant has a different nonce at the beginning of its system prefix and a
separate stable request key, preventing the baseline from warming the improved
fixture. Both first requests reported zero cache reads. No retention policy or
provider breakpoint was added. Missing cache-write metrics are recorded as null.

| Follow-up request | Baseline input / cache read | Improved input / cache read |
| --- | --- | --- |
| Second | 3,448 / 1,792 | 3,655 / 2,304 |
| Third | 4,363 / 2,816 | 4,570 / 3,328 |
| Fourth | 5,278 / 3,840 | 5,485 / 4,352 |
| Sum, excluding cold first request | 13,089 / 8,448 | 13,710 / 9,984 |

The three follow-ups reported 18.2% more cache-read tokens and 19.7% fewer uncached
input tokens (4,641 → 3,726), with 4.7% more total input. These are this fixture's
observed usage, not a guaranteed cost/latency improvement, randomized benchmark,
or measurement of Codex/Claude cache hits. Routing, model and retention affect
results. Generated answers are not used as a quality benchmark here.

## Same-session live behavior

[cache-session-live.json](cache-session-live.json) uses the installed final wheel
with the real host harness and provider, tools disabled, one global opt-in, zero
manual memory writes and zero approvals. The four replies are ACK / pnpm / ACK /
npm. Automatic source-quote extraction, stable earlier context before correction,
removal of the superseded ID, injection of a current ID, retained revision history
and absence of overlays from host state/storage all pass. This is a small synthetic
flow, separate from the provisioned semantic and cache-token measurements.

An intermediate repeat returned the same four correct replies but failed the
probe's combined overlay condition; [the nonpassing result](cache-session-intermediate.json)
is retained. That probe compared provider evidence with storage after the final
reply had already been learned. The revised probe snapshots current records before
the exchange and reports old-ID removal, current-ID presence and lexical hit count
separately. The subsequent instrumented run passes all three. The old result cannot
identify which condition failed and its cause is not conclusively attributed to
the probe or retrieval. Deterministic privacy/revision regressions pass; broader
repeated real-model extraction/retrieval evaluation remains tracked in
[Issue #2](https://github.com/handochan/aelix-memory/issues/2).

Reproduce from an environment with the extension and host installed, using existing
provider environment credentials:

```bash
python tools/evaluate_prompt_cache.py --output /tmp/cache-structure.json
python tools/evaluate_prompt_cache.py --provider openrouter --model openai/gpt-5.4-mini \
  --output /tmp/cache-live.json
python tools/live_session_memory.py --provider openrouter --model openai/gpt-5.4-mini \
  --output /tmp/session-memory.json
```

## Remaining scope

CI contains core, installed-host and published beta.2 gates on Python
3.11/3.12/3.13 × Linux/macOS/Windows, nine combinations each. Published-host CI
now runs all 15 cache regressions as well as the panel tests. Actual remote
conclusions are tracked on the PR and are separate from local macOS results.
The optional semantic model is exercised locally, not downloaded in these jobs.
Public memory benchmarks, every provider/model, persistent cross-process prompt
snapshots, exact billing/latency comparisons and Claude cache-write usage remain
outside this verification. The catalog continues to list merged 0.3.0 until this
candidate is merged and the catalog source pin is updated.
