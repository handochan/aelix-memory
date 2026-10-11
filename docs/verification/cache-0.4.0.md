# Fixed startup memory verification (0.4.0)

Date: 2026-10-12 (Asia/Seoul). Local platform: macOS arm64, CPython 3.12.13.
Only the extension changed. No host code, release, auth file or provider cache
policy was modified. Consent, canonical project isolation and source-quote writes
remain unchanged. [ADR-0005](../decisions/0005-cache-stable-recall.md) defines the
fixed 4 KiB initial summary/topic index and on-demand detail tools.

## Deterministic and installed gates

- Source suite: 143 passed, 1 skipped (the optional provisioned semantic model).
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`: pass.
- sdist/wheel build; installed-wheel imports resolve to site-packages.
- Existing real host with the installed wheel and already provisioned offline
  multilingual MiniLM: 144 tests pass. No model is downloaded at runtime.
- Installed wheel on unchanged published `aelix[tui]==0.1.0b2`: 21 startup/cache
  regressions plus 4 panel regressions pass; no `register_setting` API is required.
- Real `aelix extension verify aelix-memory` reports all one endpoint BOUND on
  both hosts, using temporary agent/settings/memory paths. OFF creates no memory home.

Actual converter tests cover Codex, Responses, Chat Completions and Claude input.
Other regressions cover zero searches across user turns/tool iterations, one initial
candidate read, model-requested detail tools, fixed empty snapshots, new-session
updates, source/time/scope filters before candidate limits, priority of core rules
over recent episodes, UTF-8 budgets and escaping, host state non-persistence,
storage failure, expiry, compaction, session reset and concurrent OFF/ON or
forget/revision during asynchronous reads. Final mode-check cycling is also revoked.

## Structural comparison and observed live cache usage

[cache-live.json](cache-live.json) compares the 0.3.0 latest-only placement with the
fixed startup snapshot. Four synthetic turns alternate pytest/uv questions. The
Codex converter measures preserved visible input bytes; the separate eight live
calls use OpenRouter `openai/gpt-5.4-mini`. Fixed reference text supplies a long
fixture prefix; production is never padded. Synthetic assistant history keeps
both variants' non-memory input identical. The new constant memory usage policy
is part of the improved variant's system prefix, never derived from stored text. Generated replies are not an answer
quality comparison and their output lengths may differ.

| Prior request | 0.3.0 shared / prior bytes | Fixed startup shared / prior bytes |
| --- | --- | --- |
| First → second | 12,490 / 13,395 | 14,788 / 14,788 |
| Second → third | 18,427 / 19,333 | 20,724 / 20,724 |
| Third → fourth | 24,363 / 25,272 | 26,665 / 26,665 |

All three new requests preserve the entire previous visible prefix; no baseline
pair does. These are serialized visible input bytes, not provider cache tokens.

Each live variant has a distinct nonce at the beginning of its system prefix and
a separate stable request key to avoid cross-warming. Both first cache reads are
zero. No retention or breakpoint policy is added. Missing cache-write metrics are
null. Output is capped at 32 tokens per request.

| Follow-up request | Baseline input / cache read | Startup input / cache read |
| --- | --- | --- |
| Second | 3,449 / 1,792 | 3,733 / 2,304 |
| Third | 4,358 / 2,816 | 4,648 / 3,328 |
| Fourth | 5,279 / 3,840 | 5,563 / 4,352 |
| Sum, excluding cold first request | 13,086 / 8,448 | 13,944 / 9,984 |

Observed follow-ups have 18.2% more cache-read tokens and 14.6% fewer uncached
input tokens (4,638 → 3,960), with 6.6% more total input. Including the first
request, uncached input is 7,166 → 6,778 (5.4% less); initial startup input is
2,818 versus 2,528. This fixture does not prove lower total task cost, latency,
randomized benchmark performance, or actual Codex/Claude cache hits. Routing,
retention, model and provider policy affect cache reuse.

## Actual model-directed tools and automatic learning

[cache-session-live.json](cache-session-live.json) runs the real host harness,
default headless permission extension and provider across three sessions under a
single global opt-in. Four unrelated synthetic core preferences are seeded to
make the target procedure an indexed topic rather than a full startup quote.
The target procedure is learned through a real completed conversation; there are
zero manual writes of that target and zero per-memory approvals.

- The unrelated HELLO turn makes zero memory tool calls.
- A task requiring the exact stored procedure quote causes the model to call
  `memory_get`. The quote is absent from the startup summary and the final
  answer matches the automatically stored source quote exactly.
- Prior input remains a prefix during the lookup. Tool results are ordinary host
  history; startup overlays are absent from persisted host state/storage.
- A real pnpm → npm correction is automatically stored. The old startup ID is
  removed; its replacement is not automatically added to that session's snapshot.
- The same session answers npm from current evidence. The next session includes
  the updated record in its initial summary and also answers npm.

Both independent final runs pass all six answer cases and the state/tool assertions.
The repeat is recorded in [cache-session-live-repeat.json](cache-session-live-repeat.json). This is bounded synthetic
evidence, separate from the offline semantic test and cache-token measurement.
Interactive tool approval follows host policy; this headless test does not claim
that every interactive permission mode will silently allow extension tools.

## Reproduction and scope

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
python tools/evaluate_prompt_cache.py --output /tmp/cache-structure.json
python tools/evaluate_prompt_cache.py --provider openrouter --model openai/gpt-5.4-mini \
  --output /tmp/cache-live.json
python tools/live_session_memory.py --provider openrouter --model openai/gpt-5.4-mini \
  --output /tmp/session-memory.json
```

Provider tools use existing environment credentials and disposable synthetic
stores/sessions; no user memory, raw transcripts, credentials or weights are
committed. GitHub CI runs core, installed-host and published-host gates on Python
3.11/3.12/3.13 × Linux/macOS/Windows, nine combinations each. Actual remote
conclusions are recorded on the PR separately from these local runs.
Public benchmark accuracy, repeated cross-model recall decisions, full task-cost
and latency evaluation remain in [Issue #2](https://github.com/handochan/aelix-memory/issues/2).
Persistent cross-process prompt snapshots and citation-locked answers are not
implemented. The catalog remains at merged 0.3.0 until final source publication.

Earlier measurements, including a nonpassing combined-condition probe from a
different recall policy, are preserved in
[historical candidate evidence](history/append-candidate-2026-10-11.json).
Those results do not validate this implementation.

[Startup hardening evidence](history/startup-hardening-2026-10-12.json) retains
intermediate failed runs. Instrumentation confirmed that a lookup question was
incorrectly extracted as a user preference and overwrote npm, causing a later uv
answer. The parser now rejects known queries/response-format requests and fragments
of query-only sources, and preserves an existing property kind. Regression tests
first reproduced the overwrite and pass after repair. A separate run missed the
detail lookup; trusted fixed usage instructions and explicit unloaded topic labels
now distinguish index metadata from stored quotes. The two final runs make the
required lookup and preserve the preference revision across subsequent reads.
These bounded checks do not guarantee every model will choose every needed tool.
