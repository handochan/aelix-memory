# ADR-0005: Preserve prompt prefixes for session recall

Status: Accepted
Date: 2026-10-11
Extends: ADR-0001 retrieval and ADR-0002 automatic extraction; global consent and
the extension-owned panel remain governed by ADR-0003 and ADR-0004.

## Problem and references

Version 0.3.0 regenerated recall before the latest user message on every provider
request and removed the previous block. On the next turn this changed historical
provider input before the previous user message. System instructions and tool
definitions already remained stable, but the conversation prefix did not.

[OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
and [Claude prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
depend on matching rendered prefixes. Preserve earlier messages and append new
context after them. API cache controls, thresholds and retention differ by model;
a stable session identifier alone does not establish a hit.

The [OpenAI Codex example](https://developers.openai.com/cookbook/examples/prompt_caching_201)
describes stable instructions/tools and append-only runtime updates; its older
model-specific caching behavior is not a universal current threshold.
[Claude Code memory](https://code.claude.com/docs/en/memory) uses a bounded startup
memory index with detailed topic files. [Letta memory blocks](https://docs.letta.com/v1-sdk/memory/memory-blocks)
provide bounded, named, optionally read-only context. We adopt bounded context and
stable placement while keeping project-scoped retrieval and verified source quotes.
These references do not demonstrate Aelix memory quality or cost superiority.

## Decision

The public `context` hook maintains a bounded ledger in session RAM. A recalled
block is anchored immediately before the user turn that first selected it. On
later calls the hook reconstructs the same blocks at their original positions,
then adds previously unseen relevant records before the new user turn. Repeated
tool iterations do not repeat retrieval. Existing records are not duplicated in
later blocks. No host source, transcript, system prompt, provider payload policy
or tool definition is rewritten by this policy.

Anchors contain a digest of user text and timestamp plus a duplicate occurrence
ordinal; the ledger stores neither raw user text nor whole exchanges. It holds
rendered snippets and source record snapshots for validation. Defaults are 12 KiB
of rendered UTF-8 memory context in aggregate, 4 KiB per block, and 64 anchors.
The oldest blocks are evicted when needed. Evicted or compacted history is not
silently regenerated throughout the conversation. Only the latest unprocessed
user turn may trigger a new bounded search, using the existing 2,000-byte query limit.

The ledger is scoped by canonical project, host session identity and consent
generation. Session start/shutdown, identity changes and OFF clear it. An OFF/ON
cycle revokes earlier context work even if the final mode is ON. Management
mutations clear local context. Read paths remain read-only and create no files.

Every reuse revalidates source IDs through the scoped, active agent read path.
Deleted, superseded, changed, expired or unavailable evidence removes its whole
block. After asynchronous retrieval, old and newly selected evidence is validated
again; a result forgotten or revised while search was running cannot be replayed.
Generation and cancellation-by-ledger-reset checks follow asynchronous reads.
Storage errors fail closed for memory injection. These invalidations can change
the prefix intentionally: privacy and current evidence take priority over caching.
An already sent request and facts present in the host's own history remain outside
the extension's retraction guarantee.

Automatic extraction keeps the existing fixed instructions. Its JSON lists known
keys in deterministic order before volatile exchange sources. The auxiliary
request identifier is stable within the canonical project/session and distinct
from the main conversation; turn IDs still identify provenance, not cache routing.
No minimum-length padding, cache-retention override or provider breakpoint is added.
Short extraction requests may not meet the provider's caching requirements.

## Verification and tradeoffs

Tests inspect actual Codex, OpenAI Responses and Claude message transformations,
not only the ledger. They verify exact preservation of earlier visible input,
single retrieval per turn, non-persistent overlays, consent races, concurrent
forget/revision, expiry, compaction, lifecycle changes and context bounds.
Installed-wheel tests run separately against existing and published beta.2 hosts.
Synthetic live usage is separate from byte-prefix measurements and semantic tests.

Retaining relevant historical snippets can increase total input tokens compared
with latest-only recall; the strict bound limits that overhead. Prefix preservation
enables caching but cannot guarantee lower total cost or latency. Provider cache
metrics, useful answers, correctness and writing cost must be measured separately.
Cross-process or restarted sessions do not reuse this RAM ledger. This decision
does not add persistent prompt snapshots or change the storage schema.
