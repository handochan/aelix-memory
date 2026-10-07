# Memory references and adopted decisions

Reviewed 2026-10-08. These are primary sources and author-owned implementations.
Reported benchmark results belong to the cited systems; they are not Aelix results.

| Reference | Useful lesson | Aelix decision |
| --- | --- | --- |
| [Pi package catalog](https://pi.dev/packages), [`jayzeng/pi-memory`](https://github.com/jayzeng/pi-memory/tree/1e276a762a666a7031459fdf7af018cc7966663e) | Durable notes, daily logs, scratchpad; optional qmd keyword/semantic/hybrid retrieval; bounded startup context | Separate durable memory from sessions; provide inspection/export; retrieve relevant records under a strict budget. Do not inject daily logs indiscriminately or start a daemon. |
| [`netguy204/pi-mem`](https://github.com/netguy204/pi-mem) | Journal/consolidated/core tiers and explicit wiki tools | Keep typed notes, explicit links and revisions. Consolidation must preserve evidence and pass evaluation before automatic deployment. |
| [`HaqimIskandar/pi-agent-memory`](https://github.com/HaqimIskandar/pi-agent-memory) | Worker-backed hybrid recall and cross-engine observations | Avoid mandatory workers and transcript capture. This is an independent adapter with AGPL-3.0 licensing, not Pi first-party memory. No code copied. |
| [Mem0 (2025)](https://arxiv.org/abs/2504.19413) | Extraction, consolidation and targeted recall are distinct operations | Agent writes are proposals; approval is a separate commit; keyed updates preserve previous versions. |
| [A-MEM (NeurIPS 2025)](https://arxiv.org/abs/2502.12110) | Structured notes, keywords, links and evolving memory | Typed notes, tags, explicit related IDs. Agent-inferred links or summaries may not silently replace evidence. |
| [LongMemEval (ICLR 2025)](https://arxiv.org/abs/2410.10813) | Evaluate extraction, multi-session reasoning, time, changed knowledge and abstention separately | Include current/as-of retrieval, expiry, updates, distractors and no-answer fixtures. Plan an actual dataset evaluation separately. |
| [Hindsight (2025)](https://arxiv.org/abs/2512.12818) | Distinguish evidence, experiences and beliefs; temporal/entity-aware retain/recall/reflect | Preserve origin and source pointers; user approval never relabels an agent inference as an observation. Reflection is a later evaluated layer. |
| [MemDelta (June 2026)](https://arxiv.org/abs/2606.29914) | Architecture rankings depend on models, embeddings and baseline controls | Fix backbone, embeddings, corpus and context budget in comparisons; measure writing cost, latency, recall and answer quality independently. No "best" claim from local tests. |
| [Agent Zero Memory (August 2026)](https://arxiv.org/abs/2608.29606) | Parallel representations, intent gating and citation-backed reading | Adopt citations and declared provenance now. Citation-locked answers require host enforcement and are not claimed by this adapter. Full graph/documentary layers remain research candidates. |
| [Letta memory blocks](https://docs.letta.com/v1-sdk/memory/memory-blocks), [attach/detach](https://docs.letta.com/tutorials/attaching-detaching-blocks/) | Explicit access control and read-only memory | Persist per-project OFF / READ / ON modes; opt-in and proposed-write review are separate user decisions. |

## Current host evidence

Inspected Aelix `402a801325dcc335e2b7e1a7e829e9b5ebed93ca` (2026-10-07).
`ExtensionAPI.on("context")` alters the next provider request without appending
to the durable session; `before_agent_start.messages` are persisted. Therefore
retrieved memory uses `context`, not stored prompt injection or transcript edits.
The public tools still pass through the host permission gate (ADR-0253).

[Issue #17](https://github.com/handochan/aelix-ai/issues/17) remains open and its
June decision described a built-in extension. This repository follows the user's
October request for a separately installable official extension. It does not
silently edit or complete that older host issue. Packaging keeps core independent.

[Marketplace CONTRIBUTING](https://github.com/handochan/aelix-marketplace/blob/main/CONTRIBUTING.md)
requires a publicly installable source, `aelix.extensions` entry point and a bound
manifest. Catalog listing is advisory and requires owner review; it is not a safety
endorsement. Submission uses a commit-pinned git spec until a PyPI release exists.

## Research to implementation boundary

Alpha implements a reliable store and host integration, not every cited algorithm.
Default retrieval is offline FTS5 lexical + CJK character n-gram rank fusion.
Optional local embedding retrieval uses a supplied, fingerprinted model directory;
no automatic model download or hosted embeddings. Compare it with lexical-only
retrieval before selecting a shipped default. Full graph inference, autonomous
consolidation, automatic transcript extraction and cloud synchronization need
their own acceptance criteria and are not enabled in this alpha.
