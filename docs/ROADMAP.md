# household-finance-kit Roadmap

Last verified: 2026-10-08

## Start here when resuming

Read this file from the top once, then work the milestone tables in ID order.
The next item is `M1-01`; M0 is complete enough for development, but repository publication is blocked on the maintainer's decision.
Take the first `todo` item whose dependencies are all `done`; do not skip ahead because a later item looks easier.
After finishing an item, update its status and acceptance result in this file before starting another item.
Use [DESIGN-BRIEF](docs/DESIGN-BRIEF.md) as the source of truth when a roadmap line is unclear.

## Status legend

- `todo`: not started; no implementation should be assumed to exist.
- `doing`: actively in progress by one worker; avoid parallel edits to the same files or behavior.
- `done`: implemented, documented where needed, and the acceptance command has passed.
- `blocked`: cannot proceed until a named external decision or dependency changes.

## Current state

Only M0 exists today. The repository has the approved design brief, public skeleton, `pyproject.toml`, `src/hfk/` package, stub CLI subcommands that print `not implemented yet` and exit with code 2, `scripts/privacy_scan.py`, `hooks/tiller_guard.py`, CI, examples, profiles, and a small pytest suite. Every feature in M1 and later is planned work, not working behavior. Do not describe the Tiller reader, ledger, config validation, scorecard, balances, settle-up, retirement extension, or Google Sheets adapter as available until the relevant roadmap item is `done`.

## M0 Foundations

Goal: establish the public, private-data-safe project baseline that later workers can build on.

| ID | Item | Status | Dependencies | Acceptance |
|---|---|---:|---|---|
| `M0-01` | Approve the complete design baseline in [DESIGN-BRIEF](docs/DESIGN-BRIEF.md). | `done` | none | Run `python scripts/privacy_scan.py --root .`; expected: exit 0 with no private-data findings. |
| `M0-02` | Create the public repository skeleton, package layout, examples, profiles, docs directory, hooks directory, tests directory, and scripts directory. | `done` | `M0-01` | Run `python -m pytest -q`; expected: exit 0 for the skeleton test suite. |
| `M0-03` | Provide the initial `hfk` CLI with version support and stub subcommands that clearly report unimplemented work. | `done` | `M0-02` | Run `hfk --version`; expected: prints the installed `hfk` version and exits 0. |
| `M0-04` | Add the privacy scanner that blocks workbooks, CSV-like data, account-number patterns, email addresses outside the allowlist, and local denylist terms. | `done` | `M0-02` | Run `python scripts/privacy_scan.py --root .`; expected: exit 0 on the public repo. |
| `M0-05` | Add the Tiller read-only guard hook so agents are warned before code writes workbook files. | `done` | `M0-02` | Run `python -m pytest -q`; expected: hook-related tests pass with the rest of the suite. |
| `M0-06` | Add CI that runs tests and privacy checks for the public toolkit. | `done` | `M0-02`, `M0-04` | Run `python -m pytest -q && python scripts/privacy_scan.py --root .`; expected: both commands exit 0 locally before CI publication. |
| `M0-07` | Publish the repository to GitHub. | `blocked` | `M0-01`, `M0-04`, `M0-06` | Waiting on the maintainer's destination decision. Once unblocked, run `git ls-remote --exit-code origin HEAD`; expected: exit 0 against the chosen public GitHub remote after publication. |

## M1 Reader + Fixture

Goal: read a Tiller workbook by header name into a normalized Decimal-based ledger and generate synthetic workbooks for tests and demos.

| ID | Item | Status | Dependencies | Acceptance |
|---|---|---:|---|---|
| `M1-01` | Implement frozen `Ledger`, `Transaction`, `Category`, `Account`, and `BalanceRow` dataclasses with `Decimal` amounts and no Tiller-specific fields above the source layer. | `todo` | `M0-02`, `M0-03` | Run `python -m pytest -q tests/test_ledger.py`; expected: all ledger immutability, helper, and Decimal precision tests pass. |
| `M1-02` | Implement the workbook source adapter that locates the newest non-lock `Tiller*.xls*` workbook and opens it read-only with `openpyxl.load_workbook(..., read_only=True, data_only=True)`. | `todo` | `M1-01` | Run `python -m pytest -q tests/test_reader.py::test_reader_opens_workbook_read_only`; expected: the test proves no save path is used. |
| `M1-03` | Parse `Transactions`, `Categories`, and `Balance History` by header name, tolerate extra columns, and fail loudly on missing required headers. | `todo` | `M1-01`, `M1-02` | Run `python -m pytest -q tests/test_reader.py`; expected: reordered-header and missing-header cases pass with clear error messages. |
| `M1-04` | Add `hfk dev fixture` to generate a synthetic Tiller-like workbook using only Alex, Sam, Example Bank, and round example numbers. | `todo` | `M1-01` | Run `hfk dev fixture --out /tmp/hfk-fixture.xlsx && python -m pytest -q tests/test_fixture.py`; expected: fixture is created and readable by the source adapter. |
| `M1-05` | Cover amount signs, optional Tiller columns, null balance gaps, lock-file ignoring, and newest-version workbook selection. | `todo` | `M1-03`, `M1-04` | Run `python -m pytest -q tests/test_reader.py tests/test_fixture.py`; expected: tests pass without real workbook data. |
| `M1-06` | Update schema-facing docs if reader behavior clarifies required or optional Tiller fields. | `todo` | `M1-03` | Run `python scripts/privacy_scan.py --root .`; expected: exit 0, and the doc review check confirms [TILLER-SCHEMA](docs/TILLER-SCHEMA.md) matches the implemented headers. |

## M2 Config + Doctor

Goal: load and validate instance YAML files, then give users an actionable `hfk doctor` before any analysis runs.

| ID | Item | Status | Dependencies | Acceptance |
|---|---|---:|---|---|
| `M2-01` | Implement `household.yaml` loading with schema version, people, files, account ownership, `history_start`, and opt-in extension names. | `todo` | `M1-01` | Run `python -m pytest -q tests/test_config.py::test_household_loader_validates_required_fields`; expected: valid examples load and missing keys name the file and key path. |
| `M2-02` | Implement `declarations.yaml` loading for bucket definitions, profile imports, mapping source, non-spend groups, overrides, splits, category targets, and closed accounts. | `todo` | `M2-01` | Run `python -m pytest -q tests/test_config.py::test_declarations_loader_requires_reasons`; expected: judgement calls without `reason` fail clearly. |
| `M2-03` | Implement `plan.yaml` loading, including annual renewal validation that `monthly` equals `annual_bill / 12` within cents tolerance. | `todo` | `M2-01` | Run `python -m pytest -q tests/test_config.py::test_plan_loader_validates_annual_bill_math`; expected: valid plans pass and incorrect monthly math fails. |
| `M2-04` | Implement `hfk doctor --home <dir>` for config validation, stale data checks, and `history_start` clamping checks. | `todo` | `M2-01`, `M2-02`, `M2-03`, `M1-03` | Run `hfk doctor --home examples/instance`; expected: exit 0 for the example instance once examples are wired to synthetic data. |
| `M2-05` | Add orphan-category detection so any ledger category without a bucket mapping fails doctor with the category name and suggested config location. | `todo` | `M2-02`, `M2-04` | Run `python -m pytest -q tests/test_doctor.py::test_orphan_category_fails_doctor`; expected: failure output names the unmapped category. |
| `M2-06` | Add closed-account liveness checks so activity after a declared closure date is an error, while declared closed accounts remain documented. | `todo` | `M2-02`, `M2-04` | Run `python -m pytest -q tests/test_doctor.py::test_closed_account_liveness`; expected: post-closure activity fails and inactive closed accounts pass. |

## M3 Ownership + Buckets + Scorecard

Goal: allocate ledger amounts to people, map categories into user-defined buckets, and produce the first monthly budget scorecard.

| ID | Item | Status | Dependencies | Acceptance |
|---|---|---:|---|---|
| `M3-01` | Implement the ownership/share engine for owned and weighted shared accounts, supporting one or more people in core accounting. | `todo` | `M1-01`, `M2-01` | Run `python -m pytest -q tests/test_ownership.py`; expected: owner and weighted shared amounts reconcile to the original ledger amount within one cent. |
| `M3-02` | Implement bucket mapping from Tiller group or explicit config, including shipped presets in `profiles/`. | `todo` | `M2-02`, `M3-01` | Run `python -m pytest -q tests/test_buckets.py`; expected: simple, four-bucket, and fifty-thirty-twenty presets map synthetic categories. |
| `M3-03` | Implement overrides and splits, detect conflicting constraints, and keep every judgement call traceable to declarations data. | `todo` | `M3-02` | Run `python -m pytest -q tests/test_buckets.py::test_overrides_splits_and_conflicts`; expected: valid splits sum correctly and conflicts stop with a clear error. |
| `M3-04` | Implement `hfk scorecard --month YYYY-MM` for actual-vs-plan per bucket using the selected owner's share and the closed month requested. | `todo` | `M2-03`, `M3-01`, `M3-03` | Run `hfk scorecard --home examples/instance --month 2025-03`; expected: exits 0 and prints bucket actuals and plan totals from the synthetic fixture. |
| `M3-05` | Add scorecard regression tests for cents tolerance, non-spend exclusion, `history_start`, and no silent remapping of renamed categories. | `todo` | `M3-04` | Run `python -m pytest -q tests/test_scorecard.py`; expected: all scorecard edge cases pass on synthetic data. |

## M4 Targets, Balances, Renewals

Goal: expand core analysis beyond the scorecard to targets, positions, annual obligations, rebaselining, and plan editing.

| ID | Item | Status | Dependencies | Acceptance |
|---|---|---:|---|---|
| `M4-01` | Implement `hfk categories --month YYYY-MM` for category targets versus actuals, including paced mid-month treatment where declared. | `todo` | `M3-04`, `M2-02` | Run `python -m pytest -q tests/test_categories.py`; expected: paced and unpaced targets produce distinct, documented results. |
| `M4-02` | Implement `hfk balances` from `Balance History`, reporting null or missing balance amounts as gaps rather than zero. | `todo` | `M1-03`, `M2-04` | Run `python -m pytest -q tests/test_balances.py`; expected: latest balance rows are selected and gaps are reported. |
| `M4-03` | Implement `hfk networth` using balance history, account classes, declared unsynced account dates, and `history_start`. | `todo` | `M4-02`, `M2-01` | Run `python -m pytest -q tests/test_networth.py`; expected: net worth totals match fixture expectations and never count null balances as zero. |
| `M4-04` | Implement `hfk renewals` for annual obligations by month and sinking-fund adequacy. | `todo` | `M2-03`, `M3-01` | Run `python -m pytest -q tests/test_renewals.py`; expected: annual bills are scheduled by due month and monthly sinking-fund amounts reconcile to plan lines. |
| `M4-05` | Implement `hfk rebaseline` to propose targets from history while flagging lumpy or spiky categories instead of silently smoothing them. | `todo` | `M3-04`, `M4-01` | Run `python -m pytest -q tests/test_rebaseline.py`; expected: stable categories get proposed targets and spiky categories are flagged. |
| `M4-06` | Implement `hfk plan edit` as a local `127.0.0.1` editor that validates and writes only `plan.yaml`. | `todo` | `M2-03`, `M4-04` | Run `python -m pytest -q tests/test_plan_editor.py`; expected: editor writes only the plan file and rejects invalid annual math. |

## M5 Instance + CLI Polish

Goal: make the toolkit usable as a private instance workflow with initialization, hook wiring, and renderers.

| ID | Item | Status | Dependencies | Acceptance |
|---|---|---:|---|---|
| `M5-01` | Implement `hfk init <dir>` to create a private instance skeleton with config files, `shared-items/`, `extensions/`, gitignored `data/` and `out/`, and safe examples. | `todo` | `M2-03`, `M4-06` | Run `python -m pytest -q tests/test_init.py`; expected: generated instance tree matches the design brief and contains no real data. |
| `M5-02` | Wire the Tiller read-only hook into initialized instances without writing into the public toolkit's own data paths. | `todo` | `M5-01`, `M0-05` | Run `python -m pytest -q tests/test_init.py::test_init_wires_tiller_guard`; expected: `.claude/settings.json` points to the guard and workbook patterns remain gitignored. |
| `M5-03` | Implement text rendering for scorecard, categories, balances, net worth, renewals, and later extension reports. | `todo` | `M3-04`, `M4-04` | Run `python -m pytest -q tests/test_render_text.py`; expected: text snapshots are stable and readable in a terminal. |
| `M5-04` | Implement CSV rendering for tabular reports without changing arithmetic or adding presentation-only totals. | `todo` | `M5-03` | Run `python -m pytest -q tests/test_render_csv.py`; expected: CSV rows match engine objects and round only at presentation boundaries. |
| `M5-05` | Implement HTML rendering for generated reports using static output files and no external service dependency. | `todo` | `M5-03` | Run `python -m pytest -q tests/test_render_html.py`; expected: HTML contains the same totals as text and CSV reports. |

## M6 Extension API

Goal: let optional packages add config, commands, report sections, and doctor checks through entry points without core importing extensions.

| ID | Item | Status | Dependencies | Acceptance |
|---|---|---:|---|---|
| `M6-01` | Implement extension discovery through Python entry points in the `hfk.extensions` group. | `todo` | `M5-01` | Run `python -m pytest -q tests/test_extensions.py::test_entry_point_discovery`; expected: a test extension is discovered without a direct core import. |
| `M6-02` | Define the extension object contract: `name`, `version`, config section and schema, `requires`, `commands()`, optional `report_sections()`, and `doctor()`. | `todo` | `M6-01` | Run `python -m pytest -q tests/test_extensions.py::test_extension_contract_validation`; expected: incomplete extension objects fail with clear contract errors. |
| `M6-03` | Integrate extension config-section loading while keeping sections optional unless the feature is enabled. | `todo` | `M2-02`, `M6-02` | Run `python -m pytest -q tests/test_extensions.py::test_extension_config_sections`; expected: disabled extension config is ignored and enabled malformed config fails. |
| `M6-04` | Run extension doctor hooks as part of `hfk doctor` and report hook failures with extension names. | `todo` | `M2-04`, `M6-02` | Run `python -m pytest -q tests/test_extensions.py::test_extension_doctor_hooks`; expected: hook errors are surfaced without stopping unrelated core checks from reporting. |
| `M6-05` | Document the extension API and boundaries for public and private extension packages. | `todo` | `M6-02`, `M6-04` | Run `python scripts/privacy_scan.py --root .`; expected: exit 0, and the doc review check confirms [EXTENSIONS](docs/EXTENSIONS.md) names the `hfk.extensions` entry point. |

## M7 settle_up Extension

Goal: provide a two-person monthly settle-up report for shared household costs while never settling an unfinished month.

| ID | Item | Status | Dependencies | Acceptance |
|---|---|---:|---|---|
| `M7-01` | Implement the `settle_up` extension registration and enforce exactly two people for settle-up, even though core ownership can support more. | `todo` | `M6-04`, `M3-01` | Run `python -m pytest -q tests/test_settle_up.py::test_exactly_two_people_required`; expected: one-person and three-person settle-up configs fail clearly. |
| `M7-02` | Implement on-ledger sharing rules that match description patterns on named accounts and apply weighted splits. | `todo` | `M7-01` | Run `python -m pytest -q tests/test_settle_up.py::test_on_ledger_sharing_rules`; expected: matched synthetic transactions are included and unmatched transactions are excluded. |
| `M7-03` | Implement `shared-items/YYYY-MM.yaml` for off-ledger shared costs with label, amount, paid_by, weights, and bucket validation. | `todo` | `M7-01` | Run `python -m pytest -q tests/test_settle_shared_items.py`; expected: valid shared items load and invalid weights, people, or months fail. |
| `M7-04` | Implement `hfk settle YYYY-MM` statement output with category totals, paid-vs-owed per person, and net transfer in text, CSV, and HTML renderers. | `todo` | `M7-02`, `M7-03`, `M5-05` | Run `hfk settle --home examples/instance 2025-03`; expected: exits 0 and prints a statement using only Alex, Sam, and synthetic numbers. |
| `M7-05` | Prevent settlement of an unfinished month based on the current date and the requested `YYYY-MM`. | `todo` | `M7-04` | Run `python -m pytest -q tests/test_settle_up.py::test_unfinished_month_never_settles`; expected: current or future months fail before producing a transfer. |
| `M7-06` | Add a regression method for comparing the extension against a hand-built historical statement to the cent. | `todo` | `M7-04` | Run `python -m pytest -q tests/test_settle_regression.py`; expected: fixture statement totals match the hand-built expected statement within one cent. |
| `M7-07` | Ensure settle-up never writes to Tiller and can emit a paste-ready statement block for users who keep their own tab. | `todo` | `M7-04`, `M7-05` | Run `python -m pytest -q tests/test_settle_up.py::test_settle_outputs_without_tiller_writes`; expected: no workbook save calls occur and the paste-ready block is generated from report data. |

## M8 retirement Extension

Goal: add a mechanics-only retirement income-vs-need model, with explicit disclaimers and no advice, optimisation, Monte Carlo, or product recommendations.

| ID | Item | Status | Dependencies | Acceptance |
|---|---|---:|---|---|
| `M8-01` | R1: implement the `retirement.yaml` schema for people, birth year-month, retire year, household assumptions, and schema version. | `todo` | `M6-04` | Run `python -m pytest -q tests/test_retirement_schema.py`; expected: valid fixture config loads and invalid dates or missing people fail clearly. |
| `M8-02` | R2: implement typed income streams: `social_security` by claim age, `pension`, `account_drawdown`, and `other`, each with start, end, amount, and COLA handling. | `todo` | `M8-01` | Run `python -m pytest -q tests/test_retirement_income.py`; expected: mutually exclusive Social Security claim-age scenarios and COLA streams calculate as documented. |
| `M8-03` | R3: implement itemized expenses in today's dollars with inflation and optional seeding from the user's own `plan.yaml` spend. | `todo` | `M8-01`, `M2-03` | Run `python -m pytest -q tests/test_retirement_expenses.py`; expected: expense inflation and plan-seeded baselines match synthetic fixture expectations. |
| `M8-04` | R4: ship versioned federal tax data files tagged with tax year, add a configurable staleness gate, and support a pluggable state-tax module. | `todo` | `M8-02` | Run `python -m pytest -q tests/test_retirement_tax.py`; expected: stale tax data fails loudly and none, flat, and bracket state-tax modules plug in cleanly. |
| `M8-05` | R5: implement the calendar-year track and income-vs-need report, with per-person and household views. | `todo` | `M8-02`, `M8-03`, `M8-04`, `M5-05` | Run `python -m pytest -q tests/test_retirement_report.py`; expected: report rows cover calendar years and show income, need, and gap without advice language. |
| `M8-06` | R6: add mechanics-not-advice disclaimers, synthetic fixtures, and explicit out-of-scope notes for Monte Carlo, optimisation, Roth conversion strategy, product recommendations, and advice. | `todo` | `M8-05` | Run `python -m pytest -q tests/test_retirement_fixtures.py && python scripts/privacy_scan.py --root .`; expected: fixtures use only fictional data and report text includes the mechanics-not-advice disclaimer. |

## M9 Google Sheets Adapter

Goal: add a Google Sheets source adapter that produces the same `Ledger` as the workbook adapter.

| ID | Item | Status | Dependencies | Acceptance |
|---|---|---:|---|---|
| `M9-01` | Record the chosen Google Sheets authentication approach after the maintainer decides it, without storing secrets in the public toolkit. | `todo` | `M6-05` | Run `python scripts/privacy_scan.py --root .`; expected: exit 0, and the doc review check confirms the auth approach is documented without credentials. |
| `M9-02` | Implement the Sheets source adapter behind the same source-layer boundary as the workbook reader. | `todo` | `M1-03`, `M9-01` | Run `python -m pytest -q tests/test_sheets_source.py::test_sheets_adapter_returns_ledger`; expected: mocked Sheets rows produce a `Ledger` with no Tiller details above `hfk.source`. |
| `M9-03` | Add parity tests proving workbook and Sheets adapters produce equivalent ledgers from the same synthetic dataset. | `todo` | `M9-02`, `M1-04` | Run `python -m pytest -q tests/test_source_parity.py`; expected: transactions, categories, accounts, and balance rows match except for source metadata that stays below the ledger. |
| `M9-04` | Add doctor coverage for Sheets-source configuration and stale or missing Sheets data. | `todo` | `M9-02`, `M2-04` | Run `python -m pytest -q tests/test_doctor_sheets.py`; expected: missing access, stale data, and malformed rows fail with actionable messages. |

## M10+ Community Candidates

Goal: document and preserve clean boundaries for useful extensions that are outside the core roadmap.

| ID | Item | Status | Dependencies | Acceptance |
|---|---|---:|---|---|
| `M10-01` | Document FSA and reimbursement tracking as a community extension candidate rather than core behavior. | `todo` | `M6-05` | Run `python scripts/privacy_scan.py --root .`; expected: exit 0, and the doc review check confirms [EXTENSIONS](docs/EXTENSIONS.md) lists FSA or reimbursement tracking as out-of-core. |
| `M10-02` | Document employer pension add-ons as separate public, private, or community packages, not built into the generic retirement extension. | `todo` | `M8-06` | Run `python scripts/privacy_scan.py --root .`; expected: exit 0, and the doc review check confirms employer-specific pension schedules are extension candidates only. |
| `M10-03` | Document home purchase modelling as a separate extension candidate, not part of core budgeting or retirement mechanics. | `todo` | `M6-05` | Run `python scripts/privacy_scan.py --root .`; expected: exit 0, and the doc review check confirms home purchase modelling is named as out-of-core. |
| `M10-04` | Document the local read-only web front door as a later candidate bound to `127.0.0.1`, not a hosted service. | `todo` | `M5-05` | Run `python scripts/privacy_scan.py --root .`; expected: exit 0, and the doc review check confirms any web front door is local and read-only. |
| `M10-05` | Leave settle-up for more than two people to other implementers and document the boundary clearly. | `todo` | `M7-01` | Run `python scripts/privacy_scan.py --root .`; expected: exit 0, and the doc review check confirms core `settle_up` remains exactly two people while N-person ownership stays in the core engine. |

## Open questions

- What Google Sheets authentication approach should M9 use for a public toolkit while keeping credentials entirely out of the repository?
- What package name should be used on PyPI if `hfk` is unavailable or too ambiguous?
- Should `hfk dev fixture` support multiple named synthetic scenarios at launch, or begin with one canonical scenario and add more only when tests need them?
- Which report formats should be the default for CLI commands once text, CSV, and HTML renderers all exist?
- How should extension packages publish compatibility with `hfk` versions: package metadata only, runtime contract checks, or both?

## How to add a roadmap item

Add the new line under the milestone where a future worker would naturally look for it. Give it the next stable ID in the form `Mn-NN`; for retirement work keep the R1-R6 mapping already defined by `M8-01` through `M8-06`. Use status `todo` unless work has already started or an external decision blocks it. List dependencies by ID, not by prose, so the resume rule stays mechanical.

Every item must include an executable acceptance criterion: a command to run and the result that proves the work is complete. Prefer a focused pytest command for code, `hfk doctor --home examples/instance` or another designed CLI command for user workflows, and `python scripts/privacy_scan.py --root .` plus a named doc review check for documentation-only work. Do not add roadmap text that names real people, real accounts, real employers, private balances, private addresses, or private financial products.
