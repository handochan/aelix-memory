# Aelix Memory

Python 3.11+, Apache-2.0, hatchling. The SDK and CLI use the standard library;
host imports live only in the extension adapter. Read `docs/decisions/0001-memory-contract.md`
before changing consent, persistence, provenance, retrieval, or deletion.

Memory is OFF until the user enables the canonical project in user-owned storage.
Agent proposals never become recallable without a user approval. Read paths may not
create files or change storage. Check consent again inside every agent write transaction.
Keep scope filters on every query, including retrieval and ID resolution.

Run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and
`uv run pyright`. Host integration is a separate gate: build and install a real
wheel with the host, then run `aelix extension verify aelix-memory` and host tests.
Document actual live-model and semantic-model runs separately from deterministic tests.
Track remaining release work in GitHub Issues and committed verification records.
Never commit user memory, credentials, model weights, or session transcripts.
