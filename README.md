# Aelix Memory (alpha)

Opt-in persistent memory for Aelix. Memories stay on your machine, separate from
session history. Every project starts **OFF**. Installing or loading the extension
creates no memory files. No API key, database service or background worker is needed.

```bash
uv pip install .                 # into the same environment as Aelix
aelix extension verify aelix-memory
aelix
```

Inside Aelix:

```text
/memory status
/memory on
/memory remember --kind preference --key answer-language "Prefer Korean explanations."
/memory search "answer language"
/memory pending
/memory approve <id>
/memory read
/memory off
```

`on` enables recall and agent proposals. `read` enables recall without proposals.
`off` blocks agent memory access and further recall injection. Only you can change
these modes or approve a proposal. Saving a proposal does not make it searchable.
User management (`list`, `show`, `history`, `export`, `forget`) works even while
memory is off, so you can inspect and delete retained records.

The standalone CLI has the same commands, for example:

```bash
aelix-memory --project /path/to/repo on
aelix-memory --project /path/to/repo remember --title "Test runner" --key test-runner "Use uv run pytest."
aelix-memory --project /path/to/repo search "test runner"
aelix-memory --project /path/to/repo export --output memories.json
aelix-memory --project /path/to/repo forget <id>
```

Use `aelix-memory --help` or `/memory help` for the full command list. Keyed
changes use `update <id> <text>`; a stale revision is rejected. `history <id>`
shows the retained versions, and `search --as-of <ISO timestamp> <query>` answers
historical queries. `forget <id>` deletes the whole revision family, including
pending replacements, so an older value cannot reappear. Export files are created
exclusively with private permissions; existing files are not overwritten.

Storage defaults to `~/.aelix/memory/memory.sqlite3`. `AELIX_MEMORY_HOME` selects a
different user-owned directory. Project identity uses the resolved nearest Git
root (otherwise cwd), and different worktree roots stay separate. Consent is not
read from repository files. There is no global sharing in this version.

Search combines SQLite FTS5 lexical ranking and CJK character n-grams. Optional
offline semantic search uses a model directory you have already provisioned:

```bash
uv pip install '.[semantic]'
export AELIX_MEMORY_EMBEDDING_MODEL=/absolute/path/to/local/sentence-transformer
aelix-memory reindex
```

The extension never downloads models. Model-directory fingerprints keep different
embedding spaces separate. Keep the supplied model directory immutable for a session.
Without a model, lexical/CJK search works on its own.
Run `reindex` after saving or approving memories to include them in semantic search.
Semantic failures produce a warning and fall back to lexical recall. We have not
established benchmark superiority; see [research](docs/research.md),
[contract](docs/decisions/0001-memory-contract.md) and
[verification](docs/verification/README.md) for the measured scope and release gates.

The alpha does not harvest transcripts or tool output. Agent proposals retain
their inferred origin after approval; source pointers are declared, not verified.
Memory tools retain the host's permission prompts and plan-mode restrictions,
and the extension respects `--no-tools` and explicit tool selection.
Retrieved memory is escaped historical evidence, and current instructions and
tool permissions still govern the agent. Secret detection is best effort.
Stored memory is plaintext protected by local file permissions, not encryption.
OFF cannot erase a request already sent or remembered text in an existing session;
use a new session when you need a clean conversation. Deletion covers this store
and its search indices, not backups, exports, host transcripts or SSD remnants.

Develop with `uv sync --python 3.12`, `uv run pytest`, `uv run ruff check .`,
`uv run ruff format --check .`, `uv run pyright` and `uv build`. Host integration
and type checking require host packages; install them with `uv sync --extra host`.
Release CI checks integration against a pinned Aelix checkout.
