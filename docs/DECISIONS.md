# Architecture Decision Records

Last verified: 2026-10-08

This file is the Architecture Decision Record (ADR) log for `hfk`, the public
`household-finance-kit` Python toolkit. An ADR records a choice where a real alternative
was rejected, so that a later maintainer or LLM agent does not "fix" it back. The product
baseline is [docs/DESIGN-BRIEF.md](DESIGN-BRIEF.md); the system shape is in
[docs/ARCHITECTURE.md](ARCHITECTURE.md); the delivery sequence is in
[docs/ROADMAP.md](ROADMAP.md). Implementation status lives in the README milestone table,
not here.

## Principles Carried From the Design Brief

These are binding, but they are restatements of the design brief rather than decisions
between alternatives, so they do not get their own ADR. Each one is covered by a hard rule
in [AGENTS.md](../AGENTS.md) and by tests where code exists.

| Principle | Where it is stated | Why it is not an ADR |
| --- | --- | --- |
| Tiller is the only data source for core | Brief section 1 | Scope definition, not a choice among importers |
| Public toolkit, private instances | Brief sections 2 and 3 | Scope and privacy posture of the whole project |
| Read Tiller columns by header name, never position | Brief section 5 | Correctness requirement; tested in `tests/test_reader.py` |
| Buckets are attribute-based (`essential`, `fixed`), not named | Brief section 6 | Schema definition of `declarations.yaml` |
| Off-ledger shared costs are versioned YAML, not macro tabs | Brief section 8a | Follows from "never writes to Tiller" |
| Retirement is an extension, not core | Brief sections 4 and 8b | Follows from the extension layer existing |
| Money is `Decimal`; cents are canonical, one cent tolerance | Brief section 2 principle 4 | Correctness requirement; tested in `tests/test_ledger.py` |
| Privacy scan uses a local, gitignored denylist | Brief section 9 | Privacy mechanism, not a design fork |
| Unofficial, not affiliated with Tiller, MIT licensed | Brief section 1 | Licensing and trademark statement |

## Consolidation Note

On 2026-10-08 this log was consolidated from seventeen entries to eight. The nine entries
above were folded into the principles table; the eight below were kept verbatim and
renumbered in their original order. Old numbers, for anyone reading the M0 commit:
0002 became 0001, 0005 became 0002, 0007 became 0003, 0008 became 0004, 0011 became
0005, 0013 became 0006, 0014 became 0007, 0017 became 0008.

## How to Add an ADR

Add a new ADR when a decision changes project shape, data boundaries, privacy posture,
extension behavior, or user-facing semantics, and when a real alternative was rejected.
If the entry would only restate the design brief, add a row to the principles table
instead. Use the next number in sequence and this heading form:

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

## ADR-0001: Tiller Workbook Is Read-Only

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

## ADR-0002: Fail Loudly, Feature-Owned Optional Config

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

## ADR-0003: Account Ownership Uses Owner or Shared Weights

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

## ADR-0004: Settle-Up Is Limited to Exactly Two People

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

## ADR-0005: Tax Tables Are Versioned Data with a Staleness Gate

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

## ADR-0006: Extensions Use Python Entry Points

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

## ADR-0007: V1 Source Is Exported Excel, Google Sheets Later

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

## ADR-0008: Retirement Projections Use One Money Frame, Real Dollars

Status: accepted
Date: 2026-10-08

### Context

The retirement design in [DESIGN-BRIEF](DESIGN-BRIEF.md) section 8b describes three
things at once: income streams are "flat for life unless a stream declares COLA", expenses
are "in today's dollars with inflation", and planning is "in today's dollars". Read
literally, that mixes two frames. Flat nominal income and inflated nominal expenses live
in a nominal frame; today's-dollar planning lives in a real frame. Mixing them produces a
believable income-vs-need gap that is wrong by the cumulative inflation between now and
the year shown. That is exactly the plausible-but-wrong failure this project exists to
prevent, and it must be settled before M8 writes any arithmetic.

### Decision

Every retirement figure, input and output, is in real dollars, meaning today's purchasing
power. There is no nominal frame in the extension.

- Expenses are declared in today's dollars and stay flat in real terms. A single expense
  may declare its own real growth rate above inflation, such as healthcare, with a
  `reason`. The household `inflation` assumption is never applied to expenses as a whole.
- Each income stream declares how it tracks inflation through `cola`:
  `full` keeps the stream flat in real terms; `none` keeps it flat in nominal terms, so
  its real value erodes by the household `inflation` assumption each year; a numeric
  rate is a nominal annual growth rate and is converted to real using the same
  assumption. `cola` is required on every stream, with no default.
- The household `inflation` assumption is required whenever any stream is not `full`,
  and it exists only to convert nominal-tracking streams into real dollars.
- Reports label every money column as "today's dollars" and state the inflation
  assumption used. A nominal column is not produced.

This clarifies section 8b rather than reversing it: "flat for life" still means a stream
does not step up with age or with claim-age scenarios, and "today's dollars" is now the
only frame.

### Consequences

A stream with `cola: none` loses purchasing power on the report, which is the correct
real-dollar picture of a fixed pension. Users cannot compare the output directly to a
nominal bank statement in a future year, and the report must say so. M8 fixtures need at
least one `full`, one `none`, and one numeric `cola` stream, plus one expense with its
own real growth rate, with hand-checked expected values. Section 8b of the design brief
gains a pointer to this record so the two cannot drift.

## ADR-0009: Sharing Rules Live in Core Declarations

Status: accepted
Date: 2026-10-08

### Context

The original design put per-transaction sharing rules ("a bill paid from Alex's account
that is really joint") inside the `settle_up` extension, while core reports used account
ownership weights alone. Under that split the M3 scorecard would charge Alex 100% of a
joint utility bill and the M7 settle-up would charge 50%, for the same month, from the
same workbook. Two believable numbers that disagree is the failure this project is built
to prevent, and it would have been baked in before either feature existed.

### Decision

Sharing rules are a core `declarations.yaml` section, `sharing`. A rule matches on any
combination of exact `account`, case-insensitive `description` glob, and exact `category`,
carries `weights` that sum to 1.0, and requires a `reason`. The engine exposes one share
function: account ownership weights by default, replaced by the matching rule's weights.
Every core report and every extension reads shares from that function. Rules are not
ordered and never merged; two rules with different weights matching one transaction is a
`doctor` conflict that stops analysis. Off-ledger shared items remain in `settle_up`
because they are not in the workbook.

### Consequences

The scorecard, the categories view, and settle-up agree by construction. M3-01 grows to
include rule matching, M7-02 shrinks to consuming the core function, and M3-06 adds the
conflict check. A household that previously expressed "shared" through a Tiller category
can declare that with a `category` match rather than code.

## ADR-0010: Plan Lines Are Bucket-Keyed, Dated, and Carry Their Own Categories

Status: accepted
Date: 2026-10-08

### Context

The original `plan.yaml` line used `type: Fixed Discretionary`, where `Type` already
means Expense, Income, or Transfer in the Tiller workbook. Lines had no dates, so a report
for a past month would be scored against today's plan, and rebaseline, history views, and
the to-the-cent regression against a hand-built statement would drift as soon as a line
changed. Plan-to-category linkage was split between `plan.yaml` and a
`category_targets` section in `declarations.yaml`, two files describing one thing.

### Decision

Each plan line is one person's share of one budget item. The bucket key is `bucket` and
must name a declared bucket. Lines are dated with `effective_from` and optional
`effective_until` as inclusive `YYYY-MM` months, with `plan.effective_from` as the default
start; a report for month M uses only the lines effective in M. To change an amount, end
the old line and add a new one. A line may list `categories`, which ties it to Tiller
categories for `hfk categories`; for one person a category may appear on at most one line
effective in a month, and every listed category must map to the line's bucket. The
`category_targets` section is removed from `declarations.yaml`.

### Consequences

Plan history is preserved in the file itself, so past months stay reproducible and
`hfk plan edit` must append-and-end rather than edit in place. M2-03 validates `bucket`,
dates, and categories; M3-06 reports the conflicts. The example plan shows a dated amount
change. Existing private plans that use `type` need a one-word rename, which `doctor`
should name explicitly.

## ADR-0011: The Group-to-Bucket Map Is Declared, Never Inferred

Status: accepted
Date: 2026-10-08

### Context

`mapping_source: tiller_group` says a category takes its bucket from its Tiller `Group`,
but the design never said how a group name such as `Housing` reaches a bucket such as
`Fixed Essential` when the names differ, which they always do. The example override even
mapped `Housing`, a group, as if it were a category. Left open, an implementer would
either match strings when they happen to agree, which is a silent default, or hard-code
a household's group names into the engine, which breaks attribute-based buckets.

### Decision

The map is always declared in `declarations.yaml`. Under `tiller_group`, a `groups`
section maps every expense group present in the ledger to a declared bucket and a category
inherits its group's bucket. Under `explicit`, a `categories` section maps every expense
category directly and `groups` is ignored. Resolution order for a category is `splits`,
then `overrides`, then the map; a category in both `splits` and `overrides` is a conflict.
Groups in `non_spend_groups` and categories whose Tiller `Type` is Income or Transfer
are excluded from spend and need no entry. A missing entry for a group or category that
appears in the ledger is a `doctor` orphan error naming it. Profiles supply bucket
definitions only, since group names are household-specific. The engine never maps by
name similarity, even when a group and a bucket share a name.

### Consequences

Setup needs one more short section, which `hfk doctor` can list group by group when it
is missing. The example declarations now carry a `groups` map that covers the synthetic
fixture, with overrides for `Utilities` and `Dining` as real exceptions to their groups.
M2-02 loads the map, M2-05 reports unmapped groups, and M3-02 and M3-03 implement the
resolution order.
