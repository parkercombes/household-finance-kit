# Changelog

All notable changes to `household-finance-kit` will be documented in this file.

The format is based on Keep a Changelog, and this project is expected to use semantic versioning once releases begin.

## [Unreleased]

### Added

- Established M0 Foundations for the public toolkit: approved design brief, top-level documentation, repository skeleton, package layout, CLI stubs, example configuration files, bucket presets, and a small pytest suite.
- Added public-repo safety infrastructure: `scripts/privacy_scan.py`, the Tiller read-only guard hook at `hooks/tiller_guard.py`, and CI coverage for tests and privacy checks.
- Recorded the two-repo model that keeps this public toolkit separate from private household instances containing workbooks, generated reports, and local financial decisions.
- M1 Reader + Fixture: frozen `Decimal`-based ledger dataclasses (`hfk.ledger`), a read-only Tiller workbook reader that matches columns by header name and fails loudly on missing ones (`hfk.source`), and `hfk dev fixture` for synthetic workbooks.
- ADR-0008: retirement projections use a single real-dollar money frame, with `cola` required on every income stream.
- Consolidated `docs/DECISIONS.md` from seventeen ADRs to eight; principle restatements moved to a table at the top of the file.
- ADR-0009: sharing rules move from the `settle_up` extension into core `declarations.yaml` so the scorecard and settle-up compute shares from one function.
- ADR-0010: plan lines use `bucket` (not `type`), carry `effective_from`/`effective_until` months, and list their own `categories`; `category_targets` is removed from `declarations.yaml`. Examples and roadmap items M2-02, M2-03, M3-01, M3-04, M4-01, M7-02 updated; M3-06 added.
- ADR-0011: the group-to-bucket map is declared in `declarations.yaml` (`groups` under `tiller_group`, `categories` under `explicit`), never inferred from names; resolution order is splits, overrides, map. Example declarations now map the synthetic fixture's groups; roadmap items M2-02, M2-05, M3-02, M3-03 updated.
- `hfk plan edit` moves from M4 to M10 (`M10-06`); M4-06 is now `hfk plan check`, a validator that writes nothing. The instance-local `extensions/` directory is dropped from the design because discovery is entry points only.
- `M3-07` adds a local-only parity check of the scorecard against a household's existing statement.
- Reader: `Ledger.accounts` is derived from transaction and balance rows; `Hide From Reports` accepts only Tiller's `Hide`/`Show` and boolean spellings and errors on anything else; category lookup is indexed.
- `tests/test_read_only_invariant.py` statically checks that no toolkit module except the fixture generator can save a workbook. PRIVACY.md documents the guard hook's limits.
- M3-01: `hfk.engine.shares` computes per-transaction person shares from account ownership defaults and matching sharing rules, with cent reconciliation and conflict errors.
- Marked M2 done in the README milestone table and added roadmap item `M5-00` to package the bucket profiles as package data before `hfk init` ships.
- M2-06: `hfk doctor` reports closed accounts that still have later ledger activity and accounts declared as both open and closed.
- M2-05: `hfk doctor` reports orphan transaction categories and unmapped expense groups or categories without inferring buckets.
- M2-04: `hfk doctor` validates instance config, workbook availability, declared accounts, stale data, and `history_start` clamps with actionable diagnostics.
- M2-03: `hfk.config` loads and validates `plan.yaml` schema, declared buckets, people, month ranges, categories, pacing flags, and annual renewal math.
- M2-02: `hfk.config` loads and validates `declarations.yaml` bucket definitions, profile imports, mapping source maps, non-spend groups, overrides, splits, sharing rules, and closed accounts.
- M2-01: `hfk.config` loads and validates `household.yaml` (schema version, people, `files.tiller_glob`, `history_start`, account ownership as exact `Decimal` weights that must sum to 1, opt-in `extensions`). `ConfigError` names the file, key path, and fix; unknown keys are rejected.
- Made the README milestone table the single status record; removed stale "M0 only" statements from AGENTS, CONTRIBUTING, ARCHITECTURE, EXTENSIONS, and ROADMAP. Added `tests/test_roadmap.py` to check the roadmap's "next item" line against item statuses.
