# Aelix Memory

Natural persistent memory for Aelix. Enable it once; important preferences,
project decisions and useful lessons are extracted, stored and recalled automatically.

Memory starts OFF globally. Installing/loading the extension or opening settings creates
no memory files. Enable **Memory** in Aelix `/settings` once; that choice persists across
projects, sessions and process restarts. You can also use the same global setting:

```text
/memory on
/memory off
```

The settings row requires a host with `ExtensionAPI.register_setting` (Aelix host
[Issue #403](https://github.com/handochan/aelix-ai/issues/403)). On older hosts,
`/memory on` and `/memory off` provide the same global choice.

After enabling, just talk normally:

```text
You:   In this project I always use pnpm, never npm.
Aelix: Understood.

...a new session later...

You:   Which package manager should we use?
Aelix: pnpm.
```

You do not have to call a memory tool, approve individual records, inspect a queue,
or maintain an index. Corrections update the current property automatically;
previous versions remain available as history. A configured local embedding model
is indexed automatically.

Install into the same Python environment as Aelix:

```bash
uv pip install .
aelix extension verify aelix-memory
aelix
```

Automatic extraction runs quietly after a completed exchange, using the same
model, endpoint and credentials as your current Aelix session. It makes a bounded
auxiliary model request; it needs no separate API key, worker or service. The main
reply is not held for learning. Pending work is finished before the next turn and
at session shutdown so a fresh session can recall what was learned.

Only durable information is selected. Stored content is an exact source quote with
its source role and session/turn receipt, not an unconstrained generated summary.
Thinking and raw tool output are excluded. Explicit requests not to remember an
exchange and detected credentials suppress extraction. Source matching verifies a
passage, not the truth of its claim. Current instructions and fresh evidence take
precedence over memory.

Inspection and management are optional:

```text
/memory status
/memory list
/memory show <id>
/memory history <id>
/memory forget <id>
/memory export --output memories.json
/memory read
```

READ recalls without learning; OFF stops learning, recall and further injection.
OFF also revokes pending jobs, including when you later turn memory on again.
A change in any project applies everywhere and revokes older jobs in other processes.
A forgotten record or newer revision cannot be overwritten by an old learning job.
Existing pending records from the previous implementation remain pending and may
be approved/discarded with the legacy management commands; they are not part of
the normal automatic workflow.

The model-free SDK and CLI support the same optional management, for example:

```bash
aelix-memory on
aelix-memory --project /path/to/repo list
aelix-memory --project /path/to/repo export --output memories.json
```

CLI pipe output and exports use UTF-8. Export does not overwrite an existing file.
Storage defaults to `~/.aelix/memory/memory.sqlite3`; `AELIX_MEMORY_HOME` selects
another user-owned directory. Each resolved nearest Git root (otherwise cwd) is
isolated; worktrees stay separate. Repository files cannot enable memory.
Global ON/OFF controls usage, while facts, searches, exports and IDs remain project
scoped. Existing schema v1/v2 stores inherit the most recent explicit user mode choice
as the global mode. Read access never migrates or mutates the database; the next
authorized write upgrades it transactionally and preserves existing records.

Default retrieval is offline SQLite lexical/CJK search. Optional local semantic
retrieval uses an already provisioned model:

```bash
uv pip install '.[semantic]'
export AELIX_MEMORY_EMBEDDING_MODEL=/absolute/path/to/local/model
```

The extension automatically indexes new records and fills missing vectors in bounded
batches. No model is downloaded at runtime. Keep model files immutable for a session.
Manual `reindex` remains an optional repair command, not routine maintenance.

Memory uses plaintext local storage with POSIX file permissions. OFF cannot retract
requests already sent or facts already present in a host conversation. Deletion
covers this memory store and indices, not exports, backups, host transcripts or SSD
remnants. The host still governs optional memory tool calls through its permission
gate; no tool approval is involved in automatic learning.

[Research](docs/research.md), [current contract](docs/decisions/0003-global-usage-settings.md),
[verification](docs/verification/README.md), and [remaining evaluation work](docs/roadmap.md)
record the tested scope. A public benchmark comparison remains necessary for a
claim of superior memory quality.

Develop with `uv sync --python 3.12`, `uv run pytest`, `uv run ruff check .`,
`uv run ruff format --check .`, `uv run pyright` and `uv build`. Type/host checks
require host packages; release CI installs a pinned Aelix checkout. Core storage and
CLI remain standard-library-only. The repository/package identity is `aelix-memory`,
and the product name is Aelix Memory.
