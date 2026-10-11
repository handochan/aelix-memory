# ADR-0005: Fixed startup summary and on-demand memory tools

Status: Accepted
Date: 2026-10-12
Supersedes: ADR-0001/0002 recall cadence and placement. Extraction, provenance,
global consent and the extension-owned panel remain governed by ADR-0002/0003/0004.

## Problem and references

Version 0.3.0 regenerated recall before the latest user message and removed the
previous block. This changed historical provider input before the previous user
message. A fixed startup summary and selective detail lookup preserve a stable
prefix while avoiding automatic searches and growing injected context every turn.

[OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
recommends stable early context, preserved history and appended new messages.
The [Codex example](https://developers.openai.com/cookbook/examples/prompt_caching_201)
describes fixed instructions/tools and appended runtime changes; older API/model
thresholds are not treated as current universal rules.
[OpenAI Sandbox Agents memory](https://developers.openai.com/api/docs/guides/agents/sandboxes)
documents startup summary injection, relevant index searches and selective detail
reads. This SDK documentation is not evidence of every Codex client implementation.
[Claude Code memory](https://code.claude.com/docs/en/memory) also uses a bounded
startup index with detail files. [Claude caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
matches rendered prefixes. [Letta blocks](https://docs.letta.com/v1-sdk/memory/memory-blocks)
provide bounded named context. These references guide the architecture; they do
not establish Aelix quality or cost superiority.

## Decision

The extension captures one startup snapshot on the first provider request in an
enabled project/session/consent generation. It inserts that snapshot at the start
of provider conversation input through the public `context` hook and keeps it
identical in subsequent requests. Initial injection means stable inclusion in
later requests, not removing the snapshot after the first request. A fixed usage
policy is appended through the existing public `before_agent_start` system-prompt
result while memory is enabled. It is idempotent, contains no stored/user memory,
and stays identical across turns. Stored text remains untrusted provider context.
Tool definitions stay fixed and no host source is changed.

The default rendered UTF-8 budget is 4 KiB. Up to 64 current project candidates
are selected with consent, scope, status and time filters before the limit. Core
preferences, procedures and facts precede episodes, and explicit user evidence
precedes assistant-derived evidence within a kind. The snapshot includes at most
four core quotes (each at most 512 escaped bytes) and twelve title/key/tag/ID topic
entries within the aggregate budget. Quotes and source references have explicit
preview/truncation markers and stable citations. It is a compact extractive summary
and index, not an unconstrained LLM paraphrase or an exhaustive memory inventory.
The constant system usage policy is separate from the 4 KiB data budget. Topic
labels explicitly mark their contents as unloaded and cannot serve as quotes.
When a relevant indexed record's requested details are absent, the policy requires
a tool read before answering, subject to existing tool availability/permissions.

There is no per-turn query generation, lexical/vector search, model retrieval gate,
or automatic addition of newly learned records to provider context. The agent calls
`memory_recall` when prior preferences, decisions, procedures or work matter and
the snapshot is insufficient or potentially outdated; `memory_get` opens a full
current record. Unrelated tasks need no lookup. Query/tool descriptions and the
fixed snapshot explain this policy. Existing host permissions, Plan mode and
explicit tool selection are honoured. The extension never bypasses a host gate.

Automatic extraction/storage continues quietly after successful completed exchanges
under one global opt-in. New records are immediately queryable through tools and
enter the next session's startup summary. The current snapshot is not refreshed
by automatic writes, manual save/edit/forget, or tool reads. An empty startup
snapshot also stays empty. Live updates are obtained through ordinary appended
tool results or current conversation evidence, preserving earlier request prefixes.

## Correctness and lifecycle

Before reuse, captured IDs are revalidated through scoped active agent reads.
Deleted, changed, superseded and expired entries are removed permanently from that
snapshot; replacements are not injected automatically. A read-only project audit
receipt detects writes during asynchronous validation and allows one bounded
retry. Consent generation/reset and current validity are rechecked afterward.
Repeated concurrent writes or storage errors fail closed for memory evidence;
they do not refresh an already initialized snapshot with new records.

OFF clears the snapshot. OFF/ON cycling revokes earlier in-flight reads, even if
the final mode is ON. A new canonical project, host session, session start/reload
or consent generation permits a fresh snapshot. Compaction within the same epoch
retains the same valid startup snapshot before the newly compacted history. Reads
create no memory files, modify no store and perform no migration. The snapshot is
session RAM only; no prompt snapshot, transcript or summary sidecar is persisted.

Invalidation can change the prefix intentionally. Correctness and user consent
take priority over a cache hit. Already sent requests and ordinary host history,
including memory tool results, cannot be retracted by the extension. Snapshot
overlays are never appended to durable host state; tool results follow the host's
normal persistence and permission rules.

Automatic extraction keeps fixed instructions, deterministic known-key ordering
before volatile sources, and a project/session-scoped auxiliary request key.
Turn IDs still identify provenance. No padding, provider cache-retention override,
or model-specific breakpoint is added. A stable key or summary alone does not
guarantee provider cache hits; short extraction requests may not be cacheable.
The parser rejects known English/Korean lookup questions and response-format
requests as durable quotes, including fragments of query-only user sources. An
automatic correction reuses the existing property's kind. These deterministic
checks supplement model extraction; they are not complete semantic understanding
of every language or statement. Manual management can still change record kinds.

## Verification and tradeoffs

Tests verify actual Codex, Responses and Claude input conversions, zero automatic
searches over user turns/tool iterations, model-requested detail retrieval, empty
snapshot stability, new-session updates, priority/filtering before limits, bounded
escaping, non-persistent overlays, expiry, storage failures and concurrent consent,
forget/revision during reads. Real installed-wheel and released beta.2 gates are
separate from semantic-model and live provider usage/answer checks.

A startup snapshot has a small initial token cost and can include unused core
facts; detail lookup may add a model/tool round trip. Model discretion can miss a
needed lookup. Measure answer quality, total input, cached input, output, latency
and task cost together. This policy enables caching but does not guarantee savings
or benchmark superiority, and does not add persistent cross-process prompt state.
