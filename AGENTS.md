# Aelix Memory

Python 3.11+, Apache-2.0, hatchling. The SDK and CLI use the standard library;
host imports live only in the extension adapter. Read `docs/decisions/0001-memory-contract.md`
before changing consent, persistence, provenance, retrieval, or deletion.

Memory is OFF until the user enables it globally in user-owned storage. Usage consent
is shared across projects and sessions; knowledge stays isolated by canonical project.
ON authorizes automatic extraction and storage without per-memory approval. Read paths
may not create files or change storage. Recheck the consent generation and cancellation
inside every automatic write transaction; an OFF/ON cycle revokes earlier jobs.
Keep scope filters on every query, including retrieval and ID resolution. Read
`docs/decisions/0002-natural-automatic-memory.md`, which supersedes the approval policy.
Read `docs/decisions/0003-global-usage-settings.md` for global consent, legacy migration
and the host `/settings` toggle, which supersede the per-project enablement policy.

Run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and
`uv run pyright`. Host integration is a separate gate: build and install a real
wheel with the host, then run `aelix extension verify aelix-memory` and host tests.
Document actual live-model and semantic-model runs separately from deterministic tests.
Track remaining release work in GitHub Issues and committed verification records.
Never commit user memory, credentials, model weights, or session transcripts.
