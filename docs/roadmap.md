# Release work

The alpha establishes the store/consent/provenance contract. It does not close
Aelix host issue #17's earlier built-in scope or claim benchmark leadership.
Implementation and Marketplace registration are separate review steps.
Tracking: [alpha and registration #1](https://github.com/handochan/aelix-memory/issues/1),
[public evaluation #2](https://github.com/handochan/aelix-memory/issues/2),
[automatic learning #3](https://github.com/handochan/aelix-memory/issues/3).

| Work | Acceptance criteria | State |
| --- | --- | --- |
| R01 opt-in alpha | Real SQLite persistence/restart/concurrency/consent/erasure; OFF/READ/ON; declared provenance and temporal revisions; CJK and optional local embeddings; actual wheel binding; real host loop and live model checks | Implemented with bounded evidence in `verification/` |
| R02 controlled public evaluation | LongMemEval-S and LoCoMo adapters; fixed backbone, corpus, embedding and context budget; full-context, plain RAG and memory comparisons; extraction/updates/temporal/multi-hop/abstention breakdown; latency, write/read tokens, cost and uncertainty | Required before a quality leadership claim |
| R03 automatic learning | Separate explicit opt-in; source-grounded candidate extraction; provenance receipts and conflict handling; bounded jobs/cancellation; redaction and review/undo; no raw tool transcript retention; measurable gain over curated R01 | Planned after R02 |
| R04 richer organization | Evaluate entity links, graph traversal and documentary summaries against R01 on matched cost; source chains survive consolidation; superseded/expired claims cannot silently become current again | Research candidate |
| R05 release hardening | Upgrade/migration/backup recovery, large-store performance, actual Windows filesystem/ACL behavior, optional model failure/compatibility matrix, cancellation and threat review, reproducible signed artifacts; Marketplace owner review | Required before stable 1.0 |

## Evaluation discipline

The 26-query fixture is a smoke test on 11 deliberately labelled records. It is
useful for regressions, not statistical evidence of superior answer accuracy.
The real multilingual embedding smoke verifies the adapter with a provisioned
model and network connections blocked; it does not select the best embedding model.
The live host fixture measures OFF/ON/OFF recall and session non-persistence on one
model with synthetic facts; it does not measure extraction quality or adversarial
LLM instruction following. Expand each dimension and publish the results before
changing default retrieval, automatic writes or consolidation.

Do not pool model/embedding changes with memory method changes. Report confidence
intervals, failure cases and cost per correct answer. Measure false recalls and
changed-knowledge failures as well as successful recall. Keep a no-memory control
and matched-budget baselines. Define operating thresholds using held-out data.
