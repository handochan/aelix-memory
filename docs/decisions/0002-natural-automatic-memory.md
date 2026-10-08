# ADR-0002: Natural automatic memory after a single user opt-in

Status: Accepted
Date: 2026-10-08
Supersedes: ADR-0001 approval/extraction policy
Superseded by: [ADR-0003](0003-global-usage-settings.md) for consent scope and settings;
automatic extraction and provenance decisions remain accepted.

## Decision

The user enables memory once with `/memory on`; the extension automatically learns,
stores, updates, indexes and recalls durable information from completed exchanges.
No per-memory proposal, approval or management action is required. `/memory off`
stops reading/injection/learning; optional READ enables recall without learning.
Inspection, deletion and export remain optional controls. Existing legacy pending
records stay pending; they are not silently imported as current evidence.

Extraction runs in a bounded background task using the host's selected model and
its existing authentication/endpoint. It starts only after a successful response,
never while OFF or READ. It reads the visible user turn and final assistant text,
not thinking or raw tool outputs. The main reply is not held for extraction;
before the next turn and during session shutdown the extension drains outstanding
work with a deadline so fresh sessions retain the learned facts. Shutdown/reload
cleanup cancels remaining work. No separate API key, service or automatic model
download is required.

An extraction request asks for up to four durable, source-grounded notes. The parser
requires every saved evidence quote to be an exact substring of a supplied source;
the stored content is the quote, not an unconstrained model paraphrase. Origin stays
agent-derived and source role/quote/receipt remain visible. A matched quote verifies
the passage, not the truth of its claim. Trivial, transient, hypothetical or sensitive
information is excluded. Explicit requests not to remember an exchange suppress
learning. Detected credentials suppress the exchange before any extra model call.

ON permits automatic active writes. The write transaction checks scope, current
consent generation, cancellation and the expected previous revision. OFF, READ,
OFF-to-ON cycling, forgotten/changed records and cancelled jobs cannot admit stale
results. Repeated identical facts do not create additional revisions. Conflicting
updates use compare-and-swap; failures never silently replace newer evidence.
Local vector indices update automatically when a model is configured, without
requiring routine reindex commands. Schema upgrades preserve records and keep OFF
and READ paths read-only.

Product identity is `aelix-memory` / `Aelix Memory`. Alpha was a delivery label and
branch suffix, not another repository or extension. User-facing names/descriptions
and the Marketplace entry use the product identity without that suffix.

## Acceptance

- A normal enabled conversation learns without a memory tool call or approval.
- The next turn and a fresh host process recall automatically extracted evidence.
- OFF/READ, private exchanges, failed responses, malformed or invented quotes,
  unavailable models and extraction timeouts do not create active records.
- Corrections update current facts without resurrecting stale values; repeated
  evidence is idempotent; cancellation and consent revocation work across processes.
- Optional local vector indexing updates without user maintenance.
- Real host tests, installed-wheel tests, live model extraction/recall, migration,
  packaging and Marketplace submission verify the final behavior.
- Benchmarks remain a separate measurement task; implementing automatic extraction
  is not delayed behind a claim of benchmark superiority.
