# Aelix Memory verification

## Current global usage and settings (0.2.0)

The current consent/settings contract is
[ADR-0003](../decisions/0003-global-usage-settings.md); automatic extraction remains
specified by [ADR-0002](../decisions/0002-natural-automatic-memory.md).
Usage is global; knowledge, search, record IDs and exports stay project-isolated.

- Source suite: **83 passed, 1 skipped** (the optional provisioned semantic model).
  Lint, formatting, pyright, retrieval smoke and sdist/wheel build pass.
- Installed 0.2.0 wheel with real host wheels and the provisioned multilingual local
  model: **84 passed in 6.05 seconds**. Imports resolve to site-packages. Real
  `aelix extension verify aelix-memory` reports all one endpoint BOUND, exit 0.
- [settings-tui.json](settings-tui.json): actual `uv run aelix` in a 120×42 PTY,
  installed memory wheel, temporary agent/memory/session directories. Startup and
  opening settings create no memory home. `Memory off` → `Memory on` persists; a
  fresh process in a second project shows ON, then toggles global OFF. Both quit
  with exit 0. This UI run makes zero model requests.
- [live-global-memory.json](live-global-memory.json): OpenRouter
  `openai/gpt-5.4-mini`, nine fresh processes, two synthetic projects, tools disabled,
  zero manual memory writes and zero approvals. One global opt-in enables learning
  in both projects. The second project cannot recall the first's facts and recalls
  its own yarn preference; the first recalls pnpm, then its corrected npm value.
  OFF from the second project suppresses recall in the first. Recall injection
  stays absent from durable host session files.
- Deterministic regressions cover global persistence, actual fresh CLI process
  OFF/ON revocation of earlier jobs in another project, scope/ID isolation and
  legacy v2 latest explicit ON/READ/OFF choices. Legacy reads preserve database
  bytes; the next authorized write upgrades transactionally to schema v3.
- Host contribution implementation has a separate actual TUI and host regression
  gate in Aelix `docs/verification/extension-settings-2026-10-08.md`; its first
  implementation-base run passed 2589 tests, and the run integrated with host main
  `28dbcaf4a1a9a97e46d88cec4b90c1ddeb486321` passed 2710 tests. Separate review found and verified
  repairs for async callback invalidation and adversarial final-label collisions.

Core and installed-host jobs are configured for the full Python 3.11/3.12/3.13 ×
Linux/macOS/Windows matrix, nine combinations each. Host jobs install the TUI extra
and a pinned checkout exposing the new settings API, so the settings integration
test runs against the installed memory wheel there. Wheel installation uses explicit
paths from Python so shell wildcard behavior cannot affect the Windows gate.
GitHub CI executions are separate from these local macOS results.
The final host API/UI pin is `b5f9e89af47f56e6e144a6759db68042d7c71bc0`.
Its actual menu preserves displayed intent if another process changes the global
value while settings are open; selecting an ON row for OFF cannot turn memory back
ON because the other process already switched OFF. Real-modal regressions failed
in both directions before repair and pass afterward. A final installed-wheel PTY
run, including external CLI OFF while the ON row stayed visible, also passes.
The first expanded run exposed an `os.getuid` attribute error in Windows pyright
stubs; the existing runtime `hasattr` guard did not narrow those stubs. A POSIX
platform guard now expresses the same supported-platform ownership policy. Local
pyright runs for Windows, Linux and Darwin all pass; remote checks rerun on the
final commit. This does not extend the existing POSIX mode-bit checks to Windows ACLs.
The optional real semantic and live provider runs are local gates, not claims that
every provider/model was exercised on every OS/Python combination.

Reproduce model checks using an environment with the built wheels installed and
normal host credentials:

```bash
python tools/live_automatic_memory.py --provider openrouter --model openai/gpt-5.4-mini
AELIX_MEMORY_TEST_MODEL_LOCAL=/path/to/local/model HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python -m pytest -q
```

The original 0.1.0 verification below describes its earlier project opt-in policy.
The local model remains the explicitly provisioned pinned multilingual MiniLM
documented below; runtime never downloads it. Public memory-quality benchmarks,
advanced consolidation and the remaining release tasks remain tracked in Issues.

## Previous automatic memory (0.1.0)

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
