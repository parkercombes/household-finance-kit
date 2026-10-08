# Design brief — household-finance-kit (hfk)

Status: **v0.1, approved design baseline.** This is the source of truth the other
docs (README, ARCHITECTURE, ROADMAP, DECISIONS, EXTENSIONS, TILLER-SCHEMA, PRIVACY)
are derived from. If a doc and this brief disagree, fix the doc, or change this brief
deliberately and record why in `DECISIONS.md`.

Unofficial: this project is **not affiliated with, endorsed by, or sponsored by Tiller**.
"Tiller" is a trademark of its owner; we only read the spreadsheet a user already owns.

## 1. What it is

An open-source (MIT) Python toolkit that reads a user's **Tiller** spreadsheet
(`Transactions`, `Categories`, `Balance History`) **read-only** and produces budgeting
analysis: monthly scorecard (plan vs actual), category targets, balances and net worth,
annual renewals / sinking fund, and (as extensions) two-person settle-up and retirement
income-vs-need modelling.

- **Requires Tiller** as its only data source. It stands on its own otherwise: no other
  spreadsheet, macro, or service is needed. Its only other inputs are small YAML files the
  user owns (`household.yaml`, `declarations.yaml`, `plan.yaml`).
- **Never writes to the Tiller workbook.** It produces output files and reports.
- Package name `hfk`, CLI `hfk`, Python >= 3.10, dependencies: `openpyxl`, `PyYAML`;
  dev: `pytest`, `ruff`.
- Audience: a single person (e.g. someone on their first budget), a couple, or a
  family sharing the tool, each with their own private data. Documentation must be
  readable by a non-programmer and by an LLM agent resuming the work cold.

## 2. Principles

1. **Public toolkit, private instances.** The toolkit repo contains zero real financial
   data and zero personal facts. Every user's data and judgement calls live in their own
   private "instance" repo/directory.
2. **Tiller is read-only.** Open workbooks with `openpyxl.load_workbook(path,
   read_only=True, data_only=True)`. Never call `save`. (openpyxl strips Tiller's charts
   and VBA on save.) A Claude Code PreToolUse hook ships to enforce this for agents.
3. **Fail loudly, never default silently.** Configuration is schema-validated; a missing
   required key is an error. Sections belong to the feature that needs them and are
   optional otherwise. Judgement calls are recorded as data with a written reason.
4. **Plausible-but-wrong is the enemy.** Failures here look like believable numbers, not
   errors. So: flag, don't auto-fix; on conflicting constraints stop and report; cents are
   canonical (<= 1 cent tolerance); never settle up or project a month that has not
   ended; never delete a plan line because its category looks empty; a stale tax table or
   undeclared closed account is an error, not a guess.
5. **Mechanics, not advice.** The tool models arithmetic. It never recommends financial
   products or strategies. Docs and output say so wherever projections appear.
6. **Layers only know the layer below.** See section 4.
7. **Everything is testable without real data.** A synthetic-Tiller-workbook generator
   ships in the toolkit; tests, demos and onboarding use it.

## 3. Repos and layout

Two kinds of repo, strictly separated:

- **Toolkit (this repo, public).** Code, docs, example configs, synthetic data generator.
- **Instance (one per person/household, private).** Created by `hfk init <dir>`:

```
my-finances/               # private git repo
  household.yaml           # people, files, account ownership (tracked in git; contains no balances)
  declarations.yaml        # judgement calls: buckets, overrides, splits, targets
  plan.yaml                # the budget plan (lines the user edits with `hfk plan edit`)
  shared-items/            # settle-up extension: YYYY-MM.yaml off-ledger shared items
  retirement.yaml          # retirement extension input
  extensions/              # optional local extension code
  data/                    # GITIGNORED: Tiller workbook(s), statements, snapshots
  out/                     # GITIGNORED: generated reports
  .claude/settings.json    # tiller read-only hook wiring
  .gitignore               # blocks *.xlsx *.xlsm *.csv *.pdf *.tsv data/ out/
```

The toolkit never reads its own directory for user data. The instance is located by
`--home <dir>` or the `HFK_HOME` environment variable (default: current directory).

Toolkit repo layout:

```
household-finance-kit/
  README.md  AGENTS.md  CLAUDE.md  CONTRIBUTING.md  LICENSE  CHANGELOG.md
  pyproject.toml  .gitignore
  docs/            ARCHITECTURE ROADMAP DECISIONS EXTENSIONS TILLER-SCHEMA PRIVACY DESIGN-BRIEF
  src/hfk/         package (reader, ledger, config, engine, ext, cli, render)
  examples/        household.example.yaml declarations.example.yaml plan.example.yaml ...
  profiles/        presets: simple.yaml  four-bucket.yaml  fifty-thirty-twenty.yaml
  tests/           pytest suite using the synthetic fixture only
  scripts/         privacy_scan.py  (CI + pre-commit)
  hooks/           tiller_guard.py  (Claude Code PreToolUse hook)
  .github/workflows/ci.yml
```

## 4. Layers

1. **Source adapter** (`hfk.source`). The only code that knows Tiller. Reads by **header
   name, never column position**. v1: an exported/downloaded `.xlsx`/`.xlsm` file, always
   read-only. Later: Google Sheets adapter (same output). Output is a normalized `Ledger`.
2. **Ledger** (`hfk.ledger`). Frozen dataclasses: `Transaction`, `Category`, `Account`,
   `BalanceRow`, and `Ledger` (collections + helpers). Amounts are `Decimal`. No Tiller
   specifics leak above this layer.
3. **Config** (`hfk.config`). Loads and validates `household.yaml`, `declarations.yaml`,
   `plan.yaml` (JSON-Schema or hand-written validators; errors name the file, key path and
   fix). Sections are optional unless a loaded feature requires them.
4. **Engine** (`hfk.engine`). Pure functions over `Ledger` + config: ownership/share
   allocation, bucket mapping, monthly scorecard, plan-vs-actual, category targets,
   balances/net worth, renewals and sinking fund, `doctor` checks.
5. **Extensions** (`hfk.ext`). Plugins discovered by Python entry points
   (`hfk.extensions`). Each declares a config section + schema, required ledger fields,
   CLI subcommands, and optional report sections. Settle-up and retirement are the first.
6. **Presentation** (`hfk.cli`, `hfk.render`). CLI first; renderers: text, CSV, HTML.
   A local read-only web front door (127.0.0.1 only) comes later.

Rule: a layer imports only from layers below it. Extensions may import engine, ledger,
config; never the reverse.

## 5. Tiller input (see docs/TILLER-SCHEMA.md)

Sheets used (header names verified against a real Tiller workbook):

- `Transactions`: `Date, Description, Category, Amount, Account, Account #, Institution,
  Month, Week, Transaction ID, Account ID, Check Number, Full Description, Date Added,
  Category Hint, Categorized Date`. Required by hfk: `Date, Description, Category, Amount,
  Account`. Optional: `Transaction ID, Account ID, Institution, Full Description`.
- `Categories`: `Category, Group, Type, Hide From Reports`, then monthly columns. `Type`
  is one of `Expense | Income | Transfer`.
- `Balance History`: `Date, Time, Account, Account #, Account ID, Balance ID, Institution,
  Balance, Month, Week, Type, Class, Account Status, Date Added`.
- `Accounts` (optional).

Amount sign: expenses negative, income positive (Tiller convention). Workbooks may be
named `Tiller Finance v5.xlsm` (version bumps; newest `vN` in `data/` wins; glob
configurable). Lock files `~$*` are ignored. Extra columns are tolerated (Tiller adds
them over time); missing required columns are a loud error naming the sheet and column.

## 6. Configuration

### household.yaml
```yaml
schema_version: 1
people:
  - {slug: alex, name: Alex}
  - {slug: sam, name: Sam}          # omit for a single-person household
files:
  tiller_glob: "Tiller*.xls*"
history_start: 2025-01-01           # nothing earlier is ever analysed (optional but encouraged)
accounts:
  "Alex Checking": {owner: alex}
  "Joint Card":    {shared: {alex: 0.5, sam: 0.5}}   # weights sum to 1.0
  "Sam Checking":  {owner: sam}
  "Savings":       {owner: alex, kind: savings}
extensions: [settle_up, retirement]  # opt-in
```
**Ownership model.** Every account is either `owner: <slug>` or `shared: {slug: weight}`.
An owner's *share* of a transaction is `amount * weight`. This one rule covers a solo
user, a 50/50 couple, an income-proportional 60/40 split, and housemates. (Settle-up is
limited to exactly two people; the ownership model itself is N-person.)

### declarations.yaml (every judgement call, each with a `reason`)
```yaml
schema_version: 1
buckets:                       # or `profile: four-bucket` to import a preset
  - {name: Fixed Essential,        essential: true,  fixed: true}
  - {name: Variable Essential,     essential: true,  fixed: false}
  - {name: Fixed Discretionary,    essential: false, fixed: true}
  - {name: Variable Discretionary, essential: false, fixed: false}
mapping_source: tiller_group   # tiller_group (default) | explicit
non_spend_groups: [Income, Transfers]      # extra to Tiller Type Income/Transfer
overrides:                     # category -> bucket where plan and Tiller disagree
  "Housing": {bucket: Variable Essential, reason: "plan lumps rent+utilities"}
splits:                        # categories straddling two buckets
  "Home Goods": {weights: {Variable Essential: 0.5, Variable Discretionary: 0.5}, reason: "..."}
category_targets: {}           # plan lines mapped to categories, with `paced` flag
closed_accounts: {}            # name -> {closed: date, note}
```
**Bucket model.** Buckets are defined by attributes (`essential`, `fixed`), not hard-coded
names. Engine behaviour keys off attributes: fixed buckets are checked against the plan
with tight tolerance; variable buckets are *paced* mid-month (rent landing on day 2 must
not read 100% spent); essential/discretionary drives "what could be cut" views. Users may
rename buckets or use a different scheme (e.g. Needs/Wants/Savings).

**Adoption levels.** Level 0: only Tiller `Type` and `Group` (spend by category/group).
Level 1: two buckets (essential/discretionary). Level 2: four buckets. Presets live in
`profiles/`. Mapping source defaults to Tiller's `Group` column so Tiller remains the
place users edit their taxonomy; `overrides`/`splits` layer on top.

**Orphans.** Renaming a Tiller category leaves history under the old name. `hfk doctor`
fails on any category with no bucket mapping, names it, and prints the fix. Never silently
remapped.

### plan.yaml
```yaml
schema_version: 1
plan:
  lines:
    - {desc: "Streaming", who: alex, type: Fixed Discretionary, monthly: 15.99}
    - {desc: "Domain renewal", who: alex, type: Fixed Discretionary, monthly: 1.67,
       annual_bill: 20.00, annual_full: 20.00, account: "Alex Card", due: {month: 7, day: 6}}
```
`annual_bill` is the owner's share of an annual renewal; `monthly` must equal
`annual_bill / 12` (validated). `hfk plan edit` is a local 127.0.0.1-bound editor that
validates and writes only `plan.yaml`.

## 7. Engine capabilities (core)

- `hfk scorecard --month YYYY-MM` — actual vs plan per bucket, owner's share only.
- `hfk categories --month YYYY-MM` — targets vs actual per category, paced where declared.
- `hfk balances`, `hfk networth` — position from `Balance History`; null amounts allowed
  and reported as gaps, never as zero; declared unsynced accounts carry their own dates.
- `hfk renewals` — annual obligations by month, sinking-fund adequacy.
- `hfk rebaseline` — proposes new targets from history, flags lumpy/spiky categories.
- `hfk doctor` — config validation, unmapped categories, closed-account liveness, stale
  data, history_start clamps.
- `hfk init`, `hfk plan edit`, `hfk dev fixture` (generate synthetic Tiller workbook).
- Hard invariant: any analysis window is clamped to `history_start`.

## 8. Extensions (see docs/EXTENSIONS.md)

Entry-point group `hfk.extensions`. An extension object provides: `name`, `version`,
`config_section` + `schema`, `requires` (ledger fields / other extensions), `commands()`
returning CLI subcommands, `report_sections()` optional, and a `doctor()` hook. Extensions
live in separate packages (public or private). Core never imports an extension.

### 8a. settle_up (two people maximum)
Computes the monthly settle-up statement that a household would otherwise build by hand
in a spreadsheet tab with macros. `hfk settle YYYY-MM` outputs category totals of the
shared account(s), per-person paid vs owed, and the net transfer, as text/CSV/HTML.
- Exactly two people. Weighted split (default 50/50). Anything larger is out of scope and
  documented as open for others.
- **Sharing rules** (on-ledger): a rule can declare that transactions matching a
  description pattern on a given account are shared for settle-up (e.g. a bill paid from
  one person's account that is really joint).
- **Shared items** (off-ledger): costs not in Tiller (a partner's untracked card, a
  utility paid elsewhere) go in `shared-items/YYYY-MM.yaml` with label, amount, paid_by,
  weights, bucket. Validated, tracked in the private instance, works for Sheets users.
- Never settles an unfinished month. Never writes to Tiller; a paste-ready block can be
  emitted for users who keep a settle-up tab.
- A migration note: users with a hand-built tab can regression-test the new computation
  against their historical tabs to the cent.

### 8b. retirement (income vs need; NOT advice)
A generic income-vs-need model, input `retirement.yaml` (no Excel dependency):
- **People**: birth year-month, retire year.
- **Income streams** (typed list): `social_security` (amount per claim age), `pension`,
  `account_drawdown`, `other`; each with start, end, amount, COLA.
- **Expenses**: itemized monthly budget in today's dollars with inflation; baseline may
  be seeded from the user's own `plan.yaml` spend.
- **Rules carried over**: the claim-age scenarios are mutually exclusive "retire at that
  age" alternatives, not a timeline; income is flat for life after retirement unless a
  stream declares COLA; planning in today's dollars.
- **Output**: calendar-year track and income-vs-need gap; per-person and household.
- **Pluggable tax**: federal brackets, standard deduction, and Social Security
  taxability rule shipped as **versioned data files tagged with a tax year**. The tool
  fails loudly when the data's tax year is older than a configurable staleness limit.
  State tax is a separate small module (e.g. none / flat / bracket).
- **Not in scope**: Monte Carlo, optimisation, Roth conversion strategy, advice.
- Employer-specific add-ons (e.g. a national civil-service pension schedule) and
  home-purchase modelling are separate extensions, expected to live in private repos or
  community packages.

## 9. Public safety

- Fresh git history; no commit ever contains real data. The toolkit's own `.gitignore`
  blocks `*.xlsx *.xlsm *.xls *.csv *.tsv *.pdf *.numbers`, `data/`, `out/`, and any
  `household.yaml`, `declarations.yaml`, `plan.yaml` outside `examples/`.
- `scripts/privacy_scan.py` (CI + optional pre-commit): fails on staged workbook/CSV/PDF
  files; account-number patterns (`xxxx\d{4}`, `\b\d{9,}\b`); email addresses (except an
  allowlist like `noreply@`); and every term in a **local, gitignored denylist file**
  (`.privacy-denylist`) so personal names never need to appear in the public repo.
- Examples use obviously fictional names (Alex, Sam, "Example Bank") and round numbers.
- Instances get a pre-commit hook blocking workbooks/CSVs.

## 10. Documentation conventions (for humans and LLMs)

- `README.md`: what it is, who it's for, quickstart using the synthetic fixture, links.
- `AGENTS.md`: the LLM entry point: start-here reading order, hard rules (the principles
  above), how to run tests/lint/privacy scan, how to pick up the next roadmap item, how
  to update docs. `CLAUDE.md` is a one-line pointer to `AGENTS.md`.
- `ROADMAP.md`: every item has an ID (`M3-02`), status (`todo|doing|done|blocked`),
  dependencies, and **acceptance criteria that are executable** (a command and expected
  result). A "Start here when resuming" block lists the next item.
- `DECISIONS.md`: numbered ADRs (context, decision, consequences, date, status).
- Each doc carries `Last verified: YYYY-MM-DD` and the commands it describes must work.
- Never put a real person's name, balance, account number or employer in any doc.

## 11. Milestones (summary; ROADMAP.md holds the detail)

- **M0 Foundations** — design brief, docs, repo skeleton, CI + privacy scan, hook.
- **M1 Reader + fixture** — Tiller source adapter, Ledger types, synthetic workbook generator.
- **M2 Config + doctor** — household/declarations/plan loading, validation, `hfk doctor`.
- **M3 Ownership + buckets + scorecard** — shares, bucket mapping, monthly scorecard.
- **M4 Targets, balances, renewals** — category targets (paced), balances/net worth,
  renewals/sinking fund, rebaseline, plan editor.
- **M5 Instance + CLI polish** — `hfk init`, hook wiring, text/CSV/HTML renderers.
- **M6 Extension API** — entry-point discovery, config-section hooks, doctor hooks.
- **M7 settle_up extension** (two people).
- **M8 retirement extension** — R1 schema; R2 income streams; R3 expenses; R4 tax data +
  staleness gate; R5 report; R6 disclaimers and fixtures.
- **M9 Google Sheets adapter.**
- **M10+ Community**: FSA/reimbursements, employer pension add-ons, home purchase,
  local web front door.
