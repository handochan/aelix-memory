# Implementation and evaluation

Aelix Memory now implements natural automatic extraction, persistence, updates and
recall after one project opt-in. Automatic learning is core functionality, not a
feature held behind public benchmark evaluation or per-memory review.

| Work | Acceptance criteria | State |
| --- | --- | --- |
| Reliable store and host integration | Atomic persistence/restart, scope isolation, consent, temporal revisions, erasure, read-only paths, bound wheel and real host pipeline | Implemented |
| Natural automatic memory | ON learns after completed exchanges, no memory write tool/approval, bounded background jobs, next-turn/shutdown drain, matched quotes and receipts, corrections/deduplication, cancellation/consent generations, automatic local indexing | Implemented; live fresh-session learning/correction verified |
| Controlled public evaluation | LongMemEval-S/LoCoMo; fixed model/embedding/corpus/budgets; no-memory, full-context and plain RAG controls; temporal/multi-hop/abstention breakdown; read/write latency, tokens, cost and uncertainty | [Issue #2](https://github.com/handochan/aelix-memory/issues/2) |
| Evaluated consolidation | Entity links and documentary summaries; preserve source chains and negation; measure utility at matched cost; never revive superseded/expired claims | [Issue #3](https://github.com/handochan/aelix-memory/issues/3) |
| Further hardening | Large-store/retention policy, crash recovery of unfinished jobs, Windows ACL verification, provider compatibility, auxiliary usage integration in the host cost ledger, reproducible signed artifacts | Remaining release work |

The repository and distribution are `aelix-memory`; the product is Aelix Memory.
The prior alpha label described an implementation stage. It is removed from the
current product header, distribution version, repository description and catalog
submission. Source and Marketplace changes retain explicit review records.

The small labelled retrieval fixture is regression evidence, not statistical proof
of superior answer accuracy. The real multilingual local-model test checks offline
adapter behavior. The live automatic fixture verifies normal dialogue learning,
fresh-session recall, preference correction, OFF behavior and ephemeral injection;
it does not replace public benchmark or adversarial memory-quality evaluation.
Use held-out results to set thresholds and choose embedding models. Report source,
model, budget, failure cases and cost separately when comparing architectures.
