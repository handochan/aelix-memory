# Aelix Memory verification

## Current automatic memory (0.1.0)

The current contract is [ADR-0002](../decisions/0002-natural-automatic-memory.md).
ON enables automatic extraction/storage after completed exchanges with no record
approval or memory write tool. OFF/READ remain separate, persistent choices.

- Source checks: 75 passed with the optional real semantic test skipped;
  ruff lint/format and pyright pass with the pinned host installed.
- Built 0.1.0 wheel installed in the isolated environment with the pinned host
  and provisioned local multilingual model: 76 passed in 7.08s. Host manifest
  verification reports all one endpoint BOUND, exit 0.
- [live-automatic-memory.json](live-automatic-memory.json): OpenRouter
  `openai/gpt-5.4-mini`, six fresh host processes, tools disabled, zero manual memory
  writes and zero approvals. Normal pnpm preference was automatically extracted,
  recalled in a fresh session, corrected to npm and recalled again. OFF returned
  UNKNOWN and created no store; injected memory remained absent from session files.
- Provider integration handles the actual canonical `AssistantDoneEvent`. A regression
  first reproduced failure with the deprecated event subclass check, then passed
  with the native event class. Deterministic extractor tests alone had not verified it.
- Legacy schema v1 is read without mutation and upgraded transactionally on first
  write. Legacy pending notes stay pending. New automatic notes carry matched source
  quotes/roles and session/turn receipts. OFF-to-ON cycles revoke old job generations.
- Automatic vectors update without manual reindex, and stale inference cannot overwrite
  a stronger user preference, newer revision or a forgotten family.

Reproduce with a host-installed current wheel and normal host credentials:

```bash
python tools/live_automatic_memory.py --provider openrouter --model openai/gpt-5.4-mini
```

The fixture uses only synthetic preferences and temporary stores/sessions. Auxiliary
extraction uses the current model route with a 1024-token output cap and a 15-second
job deadline. Auxiliary usage is separate from the host main-turn cost ledger today;
the full cost integration is tracked as further hardening. Complete public benchmark
accuracy, automatic consolidation, crash recovery of unfinished jobs and adversarial
LLM instruction following remain unmeasured/unimplemented scope.

## Historical 0.1.0a1 baseline

The following records describe the prior implementation at source
`9559fb1e6121586a1d88bf9b1057fc128b6a3197`; its per-record approval design is superseded.

Date: 2026-10-08 (Asia/Seoul). Local platform: macOS arm64, CPython 3.12.13,
SQLite 3.53.1. No user memory or real project transcript is included in these artifacts.

## Implemented and measured

| Gate | Evidence |
| --- | --- |
| Core + deterministic real host tests | `uv run pytest -q`: 51 passed; real semantic test requires a provisioned model and skips by default |
| Complete installed-wheel suite | Fresh environment, latest pinned host, local semantic model, network blocked for semantic test: 52 passed |
| Lint, formatting, types | `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`: pass; pyright runs with the host installed |
| Built artifact | `uv build`: sdist and wheel; opened wheel has the manifest and the `aelix.extensions` entry point, no private state/transcripts/bytecode |
| Installed artifact | Fresh venv + actual wheel + host: `aelix extension verify aelix-memory` reports `BOUND`, exit 0; host tests pass from the installed artifact |
| Host compatibility | Initially Aelix `402a801325dcc335e2b7e1a7e829e9b5ebed93ca`; repeated host tests on remote main `61f03b6718211c5e3ec81617374ff736881dd999` (one CI/docs-only change ahead). CI pins the latter. Host package version is 0.1.0b2. |
| Retrieval smoke | [retrieval-smoke.json](retrieval-smoke.json): 11 records, 26 queries (23 positive, 3 negative); top1/recall5/negative abstention all 1.0 on this fixture only |
| Local semantic model | `tests/test_semantic_live.py`: English evidence recalled by Korean question, lexical control has no hit; socket connections blocked; READ leaves DB bytes unchanged; forgotten record disappears from vector recall |
| Live host | [live-host-smoke.json](live-host-smoke.json): OpenRouter `openai/gpt-5.4-mini`, capped at 256 output tokens, fresh session for each OFF/ON/OFF turn; `UNKNOWN / LANTERN-7392 / UNKNOWN`, exit 0; three session files contain no injected memory fence/citation |
| Actual TUI | Installed wheel in a PTY: startup shows `aelix-memory`, `/memory status` reports ON for the synthetic project; `/memory read` and `/memory off` display changed modes; process quits successfully. `--no-tools` remains honoured. |

Deterministic regressions include real concurrent SQLite commits, approval CAS,
pending isolation, source-aware deduplication, UTC validity/expiry/as-of, scope/ID
isolation, family erasure (including unapproved initial proposals), credential/control
rejection, literal FTS handling, escaped byte-budgeted context, host plan permissions,
non-persistent recall, explicit tool selection, and OFF during slow embedding.
Windows CI initially caught a test helper reading a UTF-8 export with its legacy
default encoding. The helper now uses UTF-8 explicitly, and an additional regression
verifies real CLI pipe output preserves Korean paths even under CP1252.

## Real semantic test reproduction

We explicitly provisioned the author-owned Apache-2.0
[paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)
at revision `e8f8c211226b894fcb81acc59f3b34ba3efd5f42` in a disposable development
directory. Runtime retrieval does not provision or download the model.
Test environment: sentence-transformers 5.7.0, transformers 5.19.0, torch 2.14.1,
CPU, 384-dimensional output. Model fingerprints include model file contents and
sentence-transformers/transformers/torch versions. Use a provisioned local model:

```bash
uv pip install '.[semantic]'
AELIX_MEMORY_TEST_MODEL_LOCAL=/path/to/local/model HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  uv run pytest tests/test_semantic_live.py -q
```

## Live test reproduction

Use an environment with Aelix and this wheel installed plus normal host credentials:

```bash
python tools/live_host_smoke.py --provider openrouter --model openai/gpt-5.4-mini
```

The script creates synthetic memory and sessions in a temporary directory and
changes only that temporary project's memory mode. An auxiliary, temporary
`before_provider_payload` hook caps output. The current host ignores `max_tokens`
patches on `before_provider_request`, so that hook was unsuitable for the cap.
Uncapped OpenRouter requests initially failed with an output-budget error; the
capped requests passed. The Codex account rejected the attempted gpt-5.4-mini,
gpt-5.4 and gpt-5.3-codex models with HTTP 400; those providers/models are unvalidated.
No credential/credit settings were changed and no credential is recorded here.

## Limits and pending gates

These tests do not measure full LongMemEval/LoCoMo accuracy, superiority over other
systems, automatic extraction, consolidation quality, or LLM resistance to prompt
injection. No hosted embedding calls, shared/global memory, autonomous writer,
sync, encryption, or citation-locked answer enforcement is implemented.
Local filesystem permissions are POSIX mode bits; Windows ACL behavior requires
its own release verification. Physical SSD/backups/exports/host histories are
outside the deletion guarantee. CI and Marketplace submission results are tracked
separately from local checks in GitHub.
