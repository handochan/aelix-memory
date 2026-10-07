# ADR-0001: Opt-in, scoped, evidence-preserving memory

Status: Accepted (alpha implementation)
Date: 2026-10-08

## Decision

Ship a separate Apache-2.0 Aelix extension, plus a model-free SDK and CLI.
No core dependency on memory. Install/load/default OFF performs no file creation,
capture, embedding, retrieval or memory injection. Consent lives in user-owned
storage, never in project-controlled files. Canonical project root is the nearest
`.git` directory/file, otherwise the supplied cwd; symlink aliases resolve to the
same scope. Distinct worktree roots are distinct scopes in this alpha. No implicit
cross-project/global sharing.

Modes: OFF blocks agent reads/writes/injection; READ allows recall only; ON allows
recall and proposals. Only user management commands change mode or approve,
update, export and forget. The SDK is a trusted management interface, not a
sandbox against arbitrary Python code or the host's general file/shell tools.
Every agent proposal transaction rechecks ON under the same SQLite writer lock.
Each context hook rechecks consent. Already sent requests, assistant text, explicit
tool results, exported files and session backups cannot be revoked by toggling OFF.

Keep fact/preference/procedure/episode records with origin, declared source,
session/tool receipts when available, creation/validity/expiry timestamps, tags,
related IDs and stable citation IDs. Approval of an agent proposal records consent;
it does not verify its source or convert inferred content into observed fact.
No raw transcript or tool-output harvesting. A best-effort secret detector rejects
common credentials; it does not guarantee detection of every sensitive value.

Use SQLite transactions, schema version checks, restricted file permissions and
per-operation connections. No persistent worker, no automatic network access.
READ is actually read-only at the SQLite layer; search never records touches.
Keyed replacements require the exact previous revision. Check that revision again
at approval to prevent lost updates. Superseded content is available only in user
history or explicit as-of searches. Expired records never appear in current recall.
Deletion removes the entire revision family, pending updates, indices and vectors;
content-free audit receipts do not retain plaintext. Rebuild FTS indices and compact
the file after deletion. Logical erasure is tested; SSD/backups/exports/session
history are outside the erasure guarantee.

Fuse ranked lexical, CJK n-gram and optional local vector candidates with RRF.
Scope/time/status filters apply before candidate limits in every channel. Limit
query/candidate/result/context size. Ranking scores are not factual confidence.
Return no evidence when there is no match. Optional embeddings are validated for
dimension/finite values and isolated by model fingerprint. Embedding failure falls
back visibly to lexical retrieval. Do not silently download models. Explicit
reindex is required to embed existing records. The optional embedding scan is
bounded at 5000 active records per project and reports when the cap is exceeded.

Use the host `context` hook to insert bounded, escaped historical evidence into
the next model request. It never appends that recall to the durable session.
Prompt fencing prevents structural boundary spoofing, not all prompt injection.
Memory cannot override current user instructions or host tool permissions.

## Alternatives and consequences

Plain Markdown is easy to edit but complicates atomic consent, concurrent updates,
temporal revisions and exact deletion. Provide JSON export rather than a second
mutable source of truth. A worker/vector database adds deployment and privacy
complexity before it demonstrates benefit. Optional local embeddings and typed
links allow measured improvements without making them mandatory.

An automatic writer is convenient but can persist secret tool output, mistakes,
or instructions injected by a repository. Use reviewable proposals in alpha.
Automatic extraction/consolidation will be separate opt-in policies after an
evaluation proves quality and failure behavior.

## Acceptance gates

1. OFF/no-store and READ produce no writes; agent tools cannot enable memory.
2. Persistence/restart, concurrent proposals, revision CAS, scope isolation,
   expiry/as-of, pending isolation and complete family deletion use real SQLite.
3. Korean/CJK, identifiers, adversarial FTS input, source citations and bounded
   escaped context have deterministic regression coverage.
4. Build/install a wheel, validate the actual host manifest resolver and run the
   real host lifecycle/permission/session pipeline, including a live model run.
5. Run a labelled retrieval smoke corpus and report its size and limits. Full
   LongMemEval/LoCoMo and real semantic-model comparison are separate release gates.
