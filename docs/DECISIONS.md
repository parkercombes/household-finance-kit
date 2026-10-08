# Architecture Decision Records

Last verified: 2026-10-08

This file is the Architecture Decision Record (ADR) log for `hfk`, the public
`household-finance-kit` Python toolkit. It records durable choices from the approved
design baseline in [docs/DESIGN-BRIEF.md](DESIGN-BRIEF.md), with cross-reference to
the system shape in [docs/ARCHITECTURE.md](ARCHITECTURE.md) and the delivery sequence in
[docs/ROADMAP.md](ROADMAP.md).

As of 2026-10-08, only milestone M0 exists: the design brief, documentation, repository
skeleton, stub CLI, privacy scan, Tiller read-only hook, CI workflow, examples, profiles,
and a small pytest suite. The reader, ledger, config validation, scorecard, balances,
settle-up, retirement, Google Sheets adapter, and other described capabilities are
planned work in later milestones unless this log says otherwise.

## How to Add an ADR

Add a new ADR when a decision changes project shape, data boundaries, privacy posture,
extension behavior, or user-facing semantics. Use the next number in sequence and this
heading form:

```md
## ADR-0000: Short title

Status: proposed
Date: 2026-10-08

### Context
...

### Decision
...

### Consequences
...
```

Status vocabulary is intentionally small:

| Status | Meaning |
| --- | --- |
| proposed | Under discussion; not yet binding. |
| accepted | Binding for implementation and docs. |
| superseded | Replaced by a later ADR. Link to the replacing ADR. |

Never edit the Decision section of an accepted ADR to change what was decided. If the
project learns something new, create a new ADR that supersedes the old one, then mark the
old ADR as superseded and link both records. Corrections that do not change the decision,
such as spelling fixes or links, are acceptable.

## ADR-0001: Tiller Is the Only Data Source

Status: accepted
Date: 2026-10-08

### Context

`hfk` is designed for households that already use a Tiller spreadsheet. The approved
input sheets are `Transactions`, `Categories`, and `Balance History`, with `Accounts`
optional. The design brief deliberately avoids adding parallel importers, bank feeds,
manual ledgers, or a second budgeting database. The only other user-owned inputs are
small YAML files: `household.yaml`, `declarations.yaml`, and `plan.yaml`.

### Decision

Tiller is the only financial data source for core `hfk`. The Source adapter layer reads
the user's Tiller workbook and normalizes it into a `Ledger`. Core features operate on
that normalized ledger plus the private YAML files owned by the user's instance.

### Consequences

The project can keep a narrow trust boundary and a simpler explanation for non-programmer
users: Tiller remains where transaction, category, account, and balance data come from.
This limits scope and prevents the toolkit from becoming a general personal-finance
aggregator. Users without Tiller are outside v1 scope. Synthetic fixtures remain important
so tests and examples do not require real workbooks.

## ADR-0002: Tiller Workbook Is Read-Only

Status: accepted
Date: 2026-10-08

### Context

Tiller workbooks may include formulas, formatting, charts, and VBA. The design brief
states that saving a workbook through `openpyxl` can strip charts and VBA. The public
toolkit also needs to be safe for LLM agents and scripts that might otherwise modify a
private workbook by accident.

### Decision

`hfk` will open Tiller workbooks with `openpyxl.load_workbook(path, read_only=True,
data_only=True)` and will never call `save` on the workbook. The toolkit ships a Claude
Code PreToolUse hook, `hooks/tiller_guard.py`, to enforce read-only behavior for agents.

### Consequences

Users can run analysis without risking damage to the original workbook. Features that
need output must write separate report files or private instance files, never the Tiller
workbook. Planned commands such as scorecards, balances, and settle-up reports must be
designed around read-only input and generated output.

## ADR-0003: Public Toolkit, Private Instances

Status: accepted
Date: 2026-10-08

### Context

The project is intended to be published as a public open-source repository. Household
financial data, account details, category judgements, and generated reports are private.
The design brief separates a public toolkit repository from a private instance directory
or repository.

### Decision

The toolkit repository contains code, docs, example configs, presets, test fixtures, CI,
and privacy tooling only. User data lives in a separate private instance with
`household.yaml`, `declarations.yaml`, `plan.yaml`, optional extension inputs,
gitignored `data/`, and gitignored `out/`.

### Consequences

The public repository must never contain real personal facts, real balances, account
numbers, emails, employer names, or private product details. Examples use only Alex, Sam,
Example Bank, and round example numbers. Implementation must never assume the toolkit
directory is a user's finance home; the instance is located by `--home`, `HFK_HOME`, or
the current directory as defined by the design.

## ADR-0004: Read Tiller Columns by Header Name

Status: accepted
Date: 2026-10-08

### Context

Tiller can add columns over time, and users may have workbooks with optional columns.
Column order is a brittle integration point. The design brief identifies required and
optional headers for `Transactions`, `Categories`, and `Balance History`.

### Decision

The Source adapter reads columns by header name, never by column position. Extra columns
are tolerated. Missing required columns are loud errors that name the sheet and missing
column.

### Consequences

The reader can survive harmless workbook evolution while still protecting users from
plausible but wrong analysis when required data is absent. Tests for the planned M1 reader
should include reordered columns, tolerated extra columns, and explicit failures for
missing required headers.

## ADR-0005: Fail Loudly, Feature-Owned Optional Config

Status: accepted
Date: 2026-10-08

### Context

The project's most dangerous failure mode is producing believable but incorrect numbers.
The design brief says missing required configuration is an error, conflicting constraints
stop analysis, and feature-specific sections are optional unless the feature is loaded.

### Decision

`hfk` will fail loudly rather than silently defaulting important financial decisions.
Config sections are owned by the feature that needs them. A section may be absent when
its feature is not active, but loaded features must validate their required keys and
report errors with file names, key paths, and fixes.

### Consequences

Users may see more validation errors during setup, but those errors are preferable to
quietly wrong budget numbers. M2 config validation and `hfk doctor` must treat missing
required keys, unmapped categories, stale data, and undeclared closed accounts as user
action items rather than guesses.

## ADR-0006: Attribute-Based Buckets

Status: accepted
Date: 2026-10-08

### Context

The design supports several adoption levels: simple Tiller group analysis, two buckets,
four buckets, and presets such as `simple`, `four-bucket`, and `fifty-thirty-twenty`.
Users may rename buckets or use different naming schemes.

### Decision

Bucket behavior is based on attributes such as `essential` and `fixed`, not hard-coded
bucket names. Fixed buckets are checked against the plan with tight tolerance. Variable
buckets can be paced mid-month. Essential and discretionary attributes support views that
separate necessary from optional spending.

### Consequences

Users can use names that make sense to them without changing engine behavior. The engine
must read bucket attributes from declarations or presets and must not rely on strings
such as "Fixed Essential" except as examples. Orphan categories and invalid mappings are
errors for `hfk doctor`.

## ADR-0007: Account Ownership Uses Owner or Shared Weights

Status: accepted
Date: 2026-10-08

### Context

The design must support a single person, a two-person household, and more general
N-person sharing. The example `household.yaml` shows accounts owned by Alex or Sam and
accounts shared with weights that sum to 1.0.

### Decision

Every account is declared as either `owner: <slug>` or `shared: {slug: weight}`.
A person's share of a transaction is the transaction amount multiplied by that person's
ownership weight for the account.

### Consequences

One ownership rule covers solo users, equal splits, weighted splits, and households with
more than two people. Engine code in planned M3 must validate that weights are present,
valid, and sum to 1.0 where sharing is declared. This model is broader than the settle-up
extension, which remains limited to exactly two people.

## ADR-0008: Settle-Up Is Limited to Exactly Two People

Status: accepted
Date: 2026-10-08

### Context

The ownership model is N-person, but the first settle-up use case is a two-person
household replacing a hand-built spreadsheet tab. Larger groups introduce ambiguity in
how reimbursements should be optimized, displayed, and explained.

### Decision

The `settle_up` extension is limited to exactly two people. It computes a monthly
statement with category totals, paid-versus-owed amounts, and a net transfer for a
finished month only.

### Consequences

The extension remains explainable and testable for the initial household use case. It
does not attempt to solve housemate, group-trip, or multi-party reimbursement flows.
The broader account ownership model still supports N-person budgeting outside settle-up.

## ADR-0009: Shared Costs Use Versioned YAML and On-Ledger Rules

Status: accepted
Date: 2026-10-08

### Context

Some shared costs appear in Tiller, while others may be paid outside the tracked
workbook. The design replaces macro-built spreadsheet tabs with a reproducible private
instance format that can be validated and tested.

### Decision

On-ledger sharing is represented by settle-up sharing rules. Off-ledger shared costs
live in versioned `shared-items/YYYY-MM.yaml` files with label, amount, paid_by, weights,
and bucket. Macro-built spreadsheet tabs are not a system of record for `hfk`.

### Consequences

Shared-cost inputs are reviewable, versioned, and private. The same model works for
future Google Sheets users because it does not depend on workbook macros. Users may
still emit a paste-ready block for a personal spreadsheet, but `hfk` does not maintain
that tab or write to Tiller.

## ADR-0010: Retirement Is an Extension

Status: accepted
Date: 2026-10-08

### Context

Retirement income-vs-need modelling has different inputs, disclaimers, tax data, and
scope boundaries from core budgeting. The design says retirement uses `retirement.yaml`
and has no Excel dependency.

### Decision

Retirement modelling is a separate `retirement` extension with its own input file. It is
not part of core budgeting, ledger reading, or plan-vs-actual analysis.

### Consequences

Core `hfk` stays focused on budget mechanics from Tiller plus household YAML files.
The retirement extension can evolve its own schema, fixtures, report, disclaimers, and
tax-data checks in M8. Documentation and output must be clear that retirement projection
is arithmetic, not financial advice.

## ADR-0011: Tax Tables Are Versioned Data with a Staleness Gate

Status: accepted
Date: 2026-10-08

### Context

The retirement design includes pluggable tax handling for federal brackets, standard
deduction, Social Security taxability, and optional state modules. Tax data changes over
time, and stale tables could create plausible but wrong projections.

### Decision

Tax tables are versioned data files tagged with a tax year. The retirement extension
fails loudly when the data's tax year is older than a configurable staleness limit.

### Consequences

Projection output cannot silently rely on outdated tax assumptions. The extension must
surface the tax year used and must stop when the configured freshness rule is violated.
Updating data files becomes a normal maintenance task rather than an implicit code
change.

## ADR-0012: Money Is Decimal and Cents Are Canonical

Status: accepted
Date: 2026-10-08

### Context

Budgeting and settle-up calculations need exact cents. Floating-point arithmetic can
produce small representation errors that are unacceptable when reports must reconcile to
the cent.

### Decision

Money values in the Ledger and engine are represented as `Decimal`. Cents are canonical,
with at most one cent tolerance where the design allows comparison tolerance.

### Consequences

Parsing must convert workbook and YAML money values into `Decimal` before calculation.
Reports should round or format only at presentation boundaries. Tests should assert
cent-level behavior, especially for ownership weights, annual renewals, and settle-up
net transfers.

## ADR-0013: Extensions Use Python Entry Points

Status: accepted
Date: 2026-10-08

### Context

The design has a layered architecture where core never imports extensions. Extensions
must be able to declare config, schema, required ledger fields, CLI subcommands, report
sections, and `doctor` checks.

### Decision

Extensions are discovered through Python entry points in the group `hfk.extensions`.
An extension object provides its name, version, config section and schema, requirements,
commands, optional report sections, and doctor hook.

### Consequences

Core remains stable while public, private, and community extensions can be installed
separately. The first planned extensions are `settle_up` and `retirement`. The Extension
API in M6 must keep imports one-way: extensions may import engine, ledger, and config;
core must not import extension packages directly.

## ADR-0014: V1 Source Is Exported Excel, Google Sheets Later

Status: accepted
Date: 2026-10-08

### Context

Tiller data may be available from an exported Excel workbook or from Google Sheets.
The design chooses an incremental path: implement a file-based reader first, then add a
Google Sheets adapter later with the same normalized output.

### Decision

The v1 Source adapter reads an exported or downloaded `.xlsx` or `.xlsm` Tiller file in
read-only mode. A Google Sheets adapter is deferred to a later milestone.

### Consequences

M1 can focus on deterministic local file parsing and synthetic workbook tests. The Source
adapter boundary must still be shaped so M9 can add Google Sheets without changing the
Ledger, Config, Engine, Extensions, or Presentation layers.

## ADR-0015: Privacy Scan Uses a Local Gitignored Denylist

Status: accepted
Date: 2026-10-08

### Context

The public repository must contain no real personal names, employers, balances, account
numbers, email addresses, private finance brands, or files such as workbooks and PDFs.
Some sensitive terms are personal to the maintainer and should never be committed even
inside a public denylist.

### Decision

The toolkit includes `scripts/privacy_scan.py` and supports a local gitignored denylist
file, `.privacy-denylist`. The scan blocks risky file types, account-number-like
patterns, email addresses except allowed examples, and every term in the local denylist.

### Consequences

Personal names and private terms can be protected without appearing in the public repo.
CI and optional pre-commit usage can run the same scan. Public examples must remain
fictional and generic, using Alex, Sam, Example Bank, and round numbers.

## ADR-0016: Project Is Unofficial and MIT Licensed

Status: accepted
Date: 2026-10-08

### Context

`hfk` reads Tiller spreadsheets but is not made by Tiller. The project is intended to be
public, reusable, and open source.

### Decision

`household-finance-kit` is an unofficial project that is not affiliated with, endorsed
by, or sponsored by Tiller. The toolkit is MIT licensed.

### Consequences

Documentation and presentation must avoid implying official status. The project can be
published and reused under the MIT license while preserving the private-instance boundary
for user data. References to Tiller identify the workbook format the user already owns,
not a partnership or endorsement.
