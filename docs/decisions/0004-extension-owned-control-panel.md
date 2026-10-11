# ADR-0004: Extension-owned memory control panel

Status: Accepted
Date: 2026-10-11
Extends: ADR-0003 management surface; consent and knowledge scopes remain unchanged

Bare `/memory` opens the extension's control panel when a public interactive UI
is bound. It uses only `select`, `input`, `editor` and `confirm`; no host source,
private menu mutation, monkeypatch, or host release is involved. The optional
`register_setting` integration remains additive. `/memory panel` is an alias.
Noninteractive invocation returns the existing status result. Explicit slash
and model-free CLI subcommands retain their behavior.

The panel exposes global usage and learning/recall-only modes, project-scoped
browse/search/content/provenance/history, optional manual edits/deletion/export,
and legacy pending/local reindex controls. No automatic record needs approval.
Forgetting a family has an explicit destructive-action confirmation; ordinary
learning and mode changes have no per-record approval.

Opening, inspecting and cancelling never creates storage, migrates it, starts
indexing or enables usage. Action callbacks delegate to the existing trusted
management operations with a captured canonical project and full IDs. Mode
selection writes the intended value from the displayed row, rather than toggling
a freshly read value after another process changed it. Stale host contexts cannot
enter a panel write. Manual changes cancel earlier local learning and clear the
captured exchange, so an earlier reply cannot recreate or reverse that action.

Editing also supports existing unkeyed notes. A replacement requires its exact
active revision ID and unchanged key (including None), uses the same family and
SQLite writer transaction, and rejects a second concurrent replacement. Keyed
uniqueness and all scope filters remain intact; no schema migration is needed.
Editors preserve existing expiry unless changed through the explicit CLI.

Details are paginated with short titles and bounded text rows for the older
public dialog implementation. Exports resolve relative paths within the panel's
project and retain the existing exclusive-create/no-overwrite policy.

Acceptance includes read-only byte identity, external mode races, scope isolation,
revision conflicts, cancelled/destructive actions, headless fallback, actual
installed-wheel/manifest/host tests, and actual PTY interaction on an unchanged
released host. Live-provider and optional semantic runs are separate evidence.
