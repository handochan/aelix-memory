# ADR-0003: Global memory usage with project-isolated knowledge

Status: Accepted
Date: 2026-10-08
Supersedes: ADR-0001/0002 per-project enablement; extraction and provenance remain unchanged

## Decision

The user's first ON choice MUST enable memory globally in the selected user-owned
memory home. It MUST persist across projects, sessions and fresh host processes.
OFF remains the initial default. Installing/loading, reading status or opening
`/settings` MUST NOT create files or migrate a database. Project files cannot opt in.

The extension contributes a live boolean `Memory` row via the host's generic
`ExtensionAPI.register_setting`. The extension getter reads its real SQLite mode;
the async setter persists it before returning and updates active tools/background
work. `/memory on`, `/memory off` and the model-free CLI/SDK use that same value.
The host owns only the menu, not memory persistence. Older hosts without this
optional API retain the global slash/CLI controls without a settings row.

READ remains an optional recall-only mode. Because it uses memory, the boolean row
shows ON for READ; switching it OFF disables all usage and switching it ON enables
normal automatic learning. `/memory status` reports the exact three-state mode.
No individual note needs approval. Inspection/deletion/export remain optional.

Global usage consent MUST NOT broaden knowledge scope. All record lookup, search,
revision, export, vector and deletion filters continue to use the canonical project.
One project's facts and record IDs MUST NOT be returned to another project.

Schema v3 stores one `configuration` value. Consent generations derive from the
latest mode audit receipt across all scopes. Every automatic write transaction
rechecks the global mode and generation under its SQLite writer lock. An OFF/ON
cycle in any project/process revokes jobs started under the earlier generation.
Already sent requests and session text cannot be retracted by OFF.

For legacy v1/v2 stores, the most recent explicit `mode:*` audit decision becomes
the global mode. No decision means OFF; an earlier ON cannot override a later OFF
or READ. Read-only paths compute this value without changing bytes. The next
authorized write migrates transactionally, preserving records, scopes and receipts.
This migration interprets the user's latest mode choice with the requested new
global meaning; it does not merge knowledge across projects.

## Acceptance

- A single ON is visible to another project and a fresh process; default OFF creates nothing.
- Project search and ID resolution remain isolated after global ON.
- Cross-project OFF/ON rejects stale automatic writes, including across processes.
- Legacy latest-choice migration preserves data and read-only byte identity.
- A real contributed `/settings` toggle and slash controls share persistent state.
- Installed-wheel host verification, actual TUI and live-model runs are recorded
  separately from deterministic storage/host tests and the optional real semantic test.
