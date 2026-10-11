# Extension-owned panel verification (0.3.0)

The `/memory` panel uses public extension select/input/editor/confirm dialogs.
No Aelix host source was changed and no host release was prepared or published.
The wheel is `aelix_memory-0.3.0-py3-none-any.whl`, local SHA256
`3306c9f3a06fa6435bc3413805431d41c3ac26c4eae3c1a4fee855e4a76432a4`.

- Source `uv run pytest`: 100 passed, 1 optional semantic-model test skipped.
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`: pass.
- Installed actual wheel with the existing host: 100 passed, 1 skipped;
  `aelix extension verify aelix-memory`: all one endpoint BOUND, exit 0.
- Actual PyPI Aelix 0.1.0b2 plus the installed wheel: `register_setting` is absent,
  four panel-specific host regression tests pass and manifest verification is BOUND.
- [panel-tui-beta2.json](panel-tui-beta2.json): real PTY, 80x24 and 120x42,
  native panel/key/editor dialogs, initially no store and cancelled panel creates
  no store, ON persists into a second project/process, project memory isolation,
  unkeyed manual edit preserves history, external OFF while ON is shown remains
  OFF when selected, and both processes quit with exit 0. Zero model turns are
  checked against synthetic session entry types; no transcripts are committed.
- [panel-tui-existing-host.json](panel-tui-existing-host.json): same actual PTY
  probe on the existing previously built settings-capable host wheels also passes.
- Provisioned local multilingual MiniLM semantic run: 101 passed in 5.98s,
  HF_HUB_OFFLINE=1 / TRANSFORMERS_OFFLINE=1, using the already provisioned pinned
  model from the existing verification record. No models are included or downloaded.
- [panel-live.json](panel-live.json): OpenRouter openai/gpt-5.4-mini, nine fresh
  processes, synthetic conversations only, zero manual memory writes or approvals.
  Automatic extraction, recall, correction/history, global usage with project
  isolation and OFF suppression pass. This provider probe enables via the SDK;
  the separate actual PTY probe verifies the panel's opt-in write path.

The initial PTY verifier incorrectly treated process completion as failure while
waiting for clean quit. Correcting the verifier condition resolved it without any
host or product code repair; actual exit is 0. Deterministic tests remain separate
from live-provider and real-semantic quality evidence.

CI config includes core, existing installed-host and released-beta.2 panel gates
on Linux/macOS/Windows x Python 3.11/3.12/3.13 (nine combinations each).
Remote execution results are recorded on the PR; these local results do not claim
an interactive Windows desktop run. The published catalog remains 0.2.0 until
this feature is reviewed and merged.
