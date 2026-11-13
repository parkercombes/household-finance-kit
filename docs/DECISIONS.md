# Architecture Decision Records

Last verified: 2026-11-13

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

See also [ADR-0015](#adr-0015-the-plan-lives-only-in-the-hfk-plan-sheet-planyaml-is-removed):
the line rules below stand, but the plan now lives in the `HFK Plan` sheet, not `plan.yaml`.

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

Setup needs one more short section, which `hfk doctor` can list group by group when
it is missing. The example declarations now carry a `groups` map that covers the synthetic
fixture, with overrides for `Utilities` and `Dining` as real exceptions to their groups.
M2-02 loads the map, M2-05 reports unmapped groups, and M3-02 and M3-03 implement the
resolution order.

## ADR-0012: Net Worth Sums Observed Balances by Tiller Class; Unsynced Accounts Are Declared in household.yaml

Status: accepted
Date: 2026-10-09

### Context

Tiller's own net worth is a plain sum of balances in which liabilities are
recorded as negative numbers. The design brief (section 7) forbids counting
null balances as zero and says declared unsynced accounts carry their own
dates. `hfk networth` (M4-03) needed those rules pinned before any arithmetic
was written, because each open question is a place where a believable wrong
total could appear.

### Decision

`build_networth` starts from the per-account balances `build_balances` already
selects (same selection rule, same closed-account cutoff, same `history_start`
clamping) and splits them by Tiller's `Class` metadata:

- Gap and unclassified accounts are excluded from the totals and reported by
  name (`incomplete`, plus a warning), never counted as zero and never
  silently assigned a side; the fix belongs in the workbook.
- Closed accounts stop counting at their declared closure date; on or after
  that date the line is excluded with the flag `closed <ISO>` and shows the
  last observation on or before the closure date.
- Liabilities are summed exactly as recorded (negative), and a positive
  liability is flagged rather than sign-flipped.
- Synced accounts are flagged `stale (<days> days)` when their observation is
  more than `stale_after_days` (default 14) before `--as-of`; the observation
  itself is still counted because it is the truth the workbook holds.
- An account whose Balance History is hand-typed rather than synced (a house
  value, a pension statement) is declared per account in `household.yaml`
  with `unsynced: true` and is never flagged stale, because its dates carry
  their own cadence.
- Undeclared accounts are still counted but flagged `undeclared`.

### Consequences

Net worth totals can be labelled incomplete, which is the honest statement
that an unknown value was excluded rather than zeroed. The user's fixes are
to set `Class` in Tiller, declare closed accounts in `declarations.yaml`, or
declare unsynced accounts in `household.yaml` — never to edit arithmetic.

---

## ADR-0013: The Plan Can Live in a `HFK Plan` Workbook Tab; `hfk plan edit` Is Superseded

Status: superseded by [ADR-0015](#adr-0015-the-plan-lives-only-in-the-hfk-plan-sheet-planyaml-is-removed) for source selection; the sheet contract and the `hfk plan edit` supersession stand
Date: 2026-10-28

### Context

Since ADR-0010 the budget plan lives only in `plan.yaml`, a hand-edited file in the
private instance. A non-programmer household therefore faces one of two bad paths: edit
YAML by hand, where indentation and quoting mistakes surface as validation errors, or
wait for the M10 `hfk plan edit` local web editor, which was planned precisely to make
the plan editable without touching YAML. Both keep the plan in a second place the
household must learn, while the household already edits its Tiller workbook every
week: the plan can live beside the data people already open.

Three alternatives were weighed. Build the M10 `hfk plan edit` editor as planned:
rejected, because a second editor beside the spreadsheet duplicates what the workbook
already does well and adds a local web app to maintain for one screen of data. Make
the tab the only plan source and drop `plan.yaml`: rejected, because a versioned,
diffable text file is exactly what a household that runs `hfk init --git` wants, and
removing it would break those instances. Read the tab by column position: rejected,
because positional reads break when columns are inserted, and reading by header name
is already the project rule.

### Decision

The plan can live in an optional `HFK Plan` sheet that the user adds to their own
workbook; Tiller does not create it. `hfk` reads it through the same read-only loader
as every other sheet (`openpyxl.load_workbook(path, read_only=True, data_only=True)`),
by header name and never by column position, and `hfk` never writes it; the only
writer of such a tab is the planned `hfk dev fixture --plan-tab` (M5-08), which writes
the synthetic fixture workbook, never a user's workbook. Row 1 holds the headers and
each later row is one plan line with exactly the meaning a `plan.yaml` line has today
(ADR-0010). The thirteen columns are `Description` (`desc`), `Who` (`who`), `Bucket`
(`bucket`), `Monthly` (`monthly`), `Categories` (`categories`, Tiller category names
separated by `;` with surrounding spaces trimmed), `Paced` (`paced`), `Effective From`
(`effective_from`, required on every row because a tab has no plan-level default
month), `Effective Until` (`effective_until`), `Annual Bill` (`annual_bill`),
`Annual Full` (`annual_full`), `Account` (`account`), `Due Month` and `Due Day`
(`due: {month, day}`). Source selection is declared in `household.yaml`:
`plan: {source: file}` (the default) reads `plan.yaml` exactly as today;
`plan: {source: workbook}` reads the tab, and `plan.yaml` remains the alternative for
households that want the plan under version control. To change an amount, end the old
row with `Effective Until` and add a new row — the same append-and-end rule ADR-0010
set for `plan.yaml`.

### Consequences

M5-08 implements the tab loader, extends `hfk plan check` to validate either source,
and adds `hfk dev fixture --plan-tab`. The M10 `hfk plan edit` editor is superseded by
the tab and will not be built; ADR-0010's sentence about it stays as written and is
read as historical. Once M5-08 lands, the `hfk init` interview defaults new instances
to the tab and offers `plan.yaml` only when `--git` is chosen, as the M5-08 roadmap
row records. Reports never depend on which source was used: the same lines give the
same cents.

---

## ADR-0014: A Closed Account Keeps Its Ownership; Closure Is a Date on the household.yaml Account Entry

Status: accepted
Date: 2026-10-17

### Context

ADR-0003 puts every account's ownership under `accounts` in `household.yaml`.
Closure lives somewhere else: `declarations.yaml` has `closed_accounts`, a map
of name to `{closed, note}` with no ownership, and `hfk doctor`
(`_check_closed_accounts`) reports `account-closed-and-open` when a name
appears in both places. That split was designed for accounts that closed before
`history_start`, where no transaction ever needs a share.

A real-data smoke of the scorecard on 2026-10-17 showed the case the split
cannot express: a card closed at the end of August still had June transactions
inside the reporting window. `share_weights` in `hfk.engine.shares` raises
`ShareError` for any transaction whose account is not under `accounts`, so the
only way to score that month was to leave the card under `accounts`, and then
doctor reported it as declared twice. The two declarations are not redundant
either: `build_balances` already looks up a closed date for every household
account, so the code half-expects both at once while doctor forbids it.

Three options were weighed:

1. Add `owner` or `shared` to `closed_accounts` entries. Rejected: ownership
   would then be declared in two files with two parsers, and the doctor
   duplicate check becomes a reconciliation problem instead of a simple rule.
2. Keep both places and let doctor accept an account declared in both when the
   closure date is after `history_start`. Rejected: "declare it in exactly one
   place" stops being true, and a user has to learn when the second place is
   required.
3. Make closure an attribute of the account entry in `household.yaml`.
   Accepted.

### Decision

- An entry under `accounts` in `household.yaml` may carry `closed: YYYY-MM-DD`
  and an optional `note`, next to its `owner` or `shared` weights. Ownership
  does not change at closure: `share_weights` uses the account's weights for
  every transaction on that account, exactly as for an open account.
- Balances and net worth keep the existing cutoff rule, now read from the
  account entry: an account with `closed` is observed through
  `min(as_of, closed)`; on or after the closure date net worth excludes the line
  with the `closed <ISO>` flag.
- Doctor's liveness check moves with the data: a transaction dated after
  `closed` is still the `closed-account-active` error, with the fix naming
  `household.yaml`. The `account-closed-and-open` diagnostic is removed because
  the condition can no longer be written.
- `declarations.yaml` loses `closed_accounts`. The loader rejects the key with
  a `ConfigError` whose fix says to move each entry under `accounts` in
  `household.yaml` and add its ownership. There is no silent alias: the
  loaders reject unknown keys everywhere else (ADR-0002), and a tolerated
  alias would recreate the two-places problem this record removes.
- An account that closed before `history_start` is declared the same way; its
  ownership is simply never consulted, because every report clamps to
  `history_start`.

### Consequences

One declaration per account answers both "whose is it" and "until when". A
closed account with in-window transactions scores without `ShareError`, doctor
is clean when the account is declared once, and balances still stop at the
closure date. The design brief's `declarations.yaml` sketch (section 6) and
[docs/TILLER-SCHEMA.md](TILLER-SCHEMA.md) must be amended to show `closed` on
the account entry, the example instance and tests move their closed accounts,
and ADR-0012's fix wording ("declare closed accounts in `declarations.yaml`")
is read as `household.yaml` from this record on; its Decision section is left
as written. Private instances that still carry `closed_accounts` fail loudly on
load with the move named as the fix, which matches the fail-loudly rule. The
change ships as roadmap item `M5-16`.

---

## ADR-0015: The Plan Lives Only in the `HFK Plan` Sheet; `plan.yaml` Is Removed

Status: accepted
Date: 2026-11-12

### Context

ADR-0013 let the plan live in either of two places: `plan.yaml` (the default) or an
`HFK Plan` sheet in the household's own workbook, chosen by `plan: {source: file |
workbook}` in `household.yaml`. M5-08 built both. Two sources turned out to cost more
than they give:

- People are confused about where the plan lives. Two sources need a switch, a warning
  when a leftover `plan.yaml` is ignored, and docs that explain both. The maintainer
  found this confusing, and the toolkit is aimed at households that do not program.
- The `hfk init` interview cannot default to the sheet. It writes starter plan lines,
  and hfk never writes the workbook (ADR-0001), so under `source: workbook` those lines
  have nowhere to go. The roadmap's "default to the sheet once M5-08 lands" plan stalled
  on this.
- Every command, test, and doc has to cover both sources, and `hfk plan check` keeps two
  location models: YAML line numbers and sheet rows.
- The household already edits the workbook every week. The plan sits next to the data
  it is scored against, and both Excel and Google Sheets keep version history.

Three alternatives were considered:

- Keep both sources (ADR-0013 as it stands). Rejected for the reasons above.
- Move the plan into `household.yaml` so there is one settings file. Rejected: it keeps
  hand-edited YAML as the way to change a budget, which is exactly what ADR-0013 set out
  to remove for non-programmers. It also mixes what changes monthly (targets) with what
  rarely changes (people, accounts).
- Keep `plan.yaml` only for `hfk init --git` instances. Rejected: it is still two sources,
  only harder to find.

### Decision

The `HFK Plan` sheet in the household's own workbook is the only plan source. The
following changes apply:

- `plan.yaml` is no longer read. A `plan.yaml` in an instance is a loud error, not a
  warning, because a file that used to change numbers must not be silently ignored. The
  error names the file and the fix: move its lines into the sheet, then delete the file.
- The `plan:` key in `household.yaml` is removed. With one source there is nothing to
  select, so the key becomes an unknown-key error whose fix says to delete it.
- The column contract, the read-only loader, the validation, and the append-and-end rule
  from ADR-0013 and ADR-0010 are unchanged. Every row carries its own `Effective From`,
  so a plan-level default start month no longer exists.
- hfk still never writes the workbook. To get lines into the sheet:
  - The `hfk init` interview writes its starter lines to `out/hfk-plan-starter.csv`
    (gitignored, private to the instance), with the thirteen headers in contract order.
    It then tells the user to add an `HFK Plan` sheet and paste or import the file.
  - A one-time `hfk plan to-sheet` writes an existing `plan.yaml` to the same CSV shape,
    for instances created before this decision. It reads `plan.yaml` only to convert it
    and never scores from it.
- `hfk init --git` keeps its meaning: git and the privacy pre-commit hook for the
  instance's YAML files. It no longer has anything to do with where the plan lives.

### Consequences

- This supersedes the source-selection part of ADR-0013. ADR-0013's sheet contract and
  its supersession of `hfk plan edit` still stand.
- ADR-0010's rules for plan lines (bucket-keyed, dated, carry their own categories)
  still stand. Its file location (`plan.yaml`) and `plan.effective_from` do not.
- Commands that need the plan now need the workbook too. This changes `hfk renewals` and
  `hfk plan check`, which today run from YAML alone.
- The plan is no longer diffable in a git-tracked instance. Plan history is kept by the
  dated rows themselves (end a row, add a row) and by the spreadsheet's own version
  history.
- The public example plan can no longer be a YAML file. The privacy scan blocks CSV-like
  data, so the example is shown as a Markdown table in `examples/instance/README.md`, and
  the machine-readable copy is the synthetic fixture's tab (`hfk dev fixture --plan-tab`).
- Code removed: the `plan.yaml` loader and its YAML line-number lookup in `plan check`,
  the `plan_source` field, the unused-file warning, and the `plan.yaml` instance
  template.
- Roadmap row `M5-18` implements this ADR, together with the matching updates to the
  brief, the schema doc, the README, the instance templates, and the tests. Until it
  lands, M5-08's two-source behaviour is what the code does.

---

## ADR-0016: An Extension's Config Is a File of Its Own in the Instance

Status: proposed
Date: 2026-11-13

### Context

The brief (section 8) says each extension "declares a config section + schema".
[EXTENSIONS](EXTENSIONS.md) allows two shapes: "Small extensions may own a section in
`household.yaml` or `declarations.yaml`. Larger features may own a separate file in the
private instance directory, such as `retirement.yaml`." Neither document says how the
first shape works. `household.yaml` and `declarations.yaml` reject unknown top-level keys
(ADR-0002), and core may not know which extensions exist (ADR-0006), so a section named
after an extension would be an unknown-key error today.

The M6 implementation needed a rule. It was found during unattended roadmap work, so it
is recorded here as proposed for the maintainer to decide, not as a decision.

Options:

1. **A separate file only.** `config_section` names a YAML file in the instance, such as
   `retirement.yaml`, or is `None` when the extension needs no config. Core loads and
   validates the file only when the extension is enabled; a file for a disabled extension
   is ignored. Core loaders keep rejecting every unknown key.
2. **Also a top-level key in `household.yaml` or `declarations.yaml`.** The core loaders
   would accept a top-level key only when an installed extension claims it. A loader's
   result would then depend on which packages are installed, and a typo in a section name
   would pass silently whenever an extension with that name happens to be installed.
3. **A reserved `extensions_config:` mapping in `household.yaml`.** One known key holds
   every extension's section, keyed by extension name. Core rejects names that no
   enabled extension owns. Small sections stay in one file, at the cost of one more level
   of nesting and a new key for every household to learn.

### Decision

Proposed: option 1. Both planned extensions already use their own inputs
(`retirement.yaml`, `shared-items/`), a separate file keeps the core loaders strict and
independent of installed packages, and option 3 can be added later without breaking
option 1.

The M6-02 contract and the M6-03 loader implement option 1 as the narrowest safe
behaviour: a `config_section` that is not a plain `.yaml` file name is a contract error.
If the maintainer chooses option 2 or 3, the contract check widens and
[EXTENSIONS](EXTENSIONS.md) keeps its in-file wording; if option 1 is accepted, that
wording is removed.

### Consequences

- Until this ADR is decided, an extension cannot keep its settings inside
  `household.yaml` or `declarations.yaml`.
- [EXTENSIONS](EXTENSIONS.md) describes the implemented file form and points here for
  the in-file form.

---

## ADR-0017: Who Paid a Shared Account's Charges in a Settle-Up Statement

Status: proposed
Date: 2026-11-13

### Context

`hfk settle YYYY-MM` (M7-04) must show "per-person paid vs owed, and the net transfer"
(design brief section 8a). The owed side is settled: ADR-0009 says every extension reads
shares from the core share function, and M7-02 does. The paid side is not defined
anywhere for workbook transactions. Off-ledger shared items carry an explicit `paid_by`
(M7-03), but a charge on a shared account such as the `Joint Card` has no payer in the
workbook or in config.

The choice changes the net transfer, so it cannot be guessed (ADR-0002). Two examples
with a 50/50 `Joint Card` and a 100.00 charge:

- If the card is funded half each, Alex paid 50.00 and owes 50.00: no transfer.
- If Alex alone pays the card bill each month, Alex paid 100.00 and owes 50.00: Sam owes
  Alex 50.00.

A household that builds a settle-up tab by hand is usually in the second case, which is
why it needs a statement at all. The gap was found during unattended roadmap work, so it
is recorded as proposed for the maintainer to decide.

Options:

1. **The account's ownership weights are also who paid.** No new config. The net comes
   only from `sharing` rules (a joint bill paid from Alex's own account) and from shared
   items. A jointly owned card always nets to zero, so this cannot express "Alex pays
   the joint card".
2. **Declare who pays each shared account, in the extension's own config file.**
   `settle_up.yaml` (per proposed ADR-0016's option 1) maps each account that carries
   shared charges to payer weights, for example
   `payers: {"Joint Card": {alex: 1.0}}` or `{alex: 0.5, sam: 0.5}`. A shared charge on an
   account without an entry is a loud error naming the account. Paying from a person's
   own account (`owner: alex`) needs no entry: the owner paid.
3. **Infer the payer from card-payment transfers in `Transactions`.** Match each payment
   into the card from a person's checking account. This is inference (ADR-0011 rejects
   inferring household facts), it breaks when a payment lands in a different month from
   the charges, and it needs payments to be in the workbook at all.

### Decision

Proposed: option 2. It covers both examples above (option 1 is option 2 with the
account's own weights written out), keeps every number traceable to a declared line, and
fails loudly when a payer is missing.

### Consequences

- Roadmap items `M7-04` (statement output) and `M7-05` to `M7-07`, which depend on it,
  are blocked until this ADR and proposed ADR-0016 are decided.
- If option 2 is accepted, `settle_up` gains `config_section = "settle_up.yaml"` with a
  schema for `payers`, the example instance gains a `settle_up.yaml`, and the statement's
  paid column is: on-ledger shared charges by payer weights, plus shared items by
  `paid_by`.

---

## ADR-0018: How Tax Enters the Retirement Income-vs-Need Gap

Status: proposed
Date: 2026-11-13

### Context

The retirement report (M8-05, brief section 8b) shows a calendar-year track of income,
need, and the gap, per person and for the household, and the brief gives the extension
pluggable tax (M8-04). Three things that change the gap are not decided anywhere:

1. **Which income is taxable.** A pension is usually taxable and Social Security is partly
   taxable by the base-amount rule. An `account_drawdown` may come from a pre-tax account
   (fully taxable), an after-tax account (not taxable), or a taxable brokerage account
   (only gains are taxable). `retirement.yaml` cannot tell these apart today, and
   guessing would change the gap.
2. **Thresholds in today's dollars.** ADR-0008 puts every figure in real dollars. Federal
   brackets and the standard deduction are indexed to inflation by law each year, so
   holding them flat in real terms is a reasonable model. The Social Security base
   amounts are fixed in nominal dollars, so in real terms they shrink every year, and
   holding them flat would understate tax decades out.
3. **Per-person tax.** A married couple files one joint return, so tax is a household
   figure. The per-person view needs either no tax or a declared way to split it.

This was found during unattended roadmap work and is recorded as proposed for the
maintainer to decide.

Options:

1. **Report before tax.** Show income, need, and gap with no tax, labelled "before
   income tax" on every page and row. This is simple and needs no new input, but every
   gap overstates what the household can spend: the plausible-but-wrong number this
   project exists to prevent, softened only by a label.
2. **Declared taxability, statute-aware thresholds.** Every income stream gains a required
   `taxable: full | none` (Social Security always uses the base-amount rule). Federal
   brackets and the standard deduction stay flat in today's dollars. The Social Security
   base amounts shrink by `inflation` each year after the table's tax year, and the
   report says so. The household view's gap is income minus federal tax, state tax, and
   need. The per-person view shows income and need with no tax, and says that tax is
   counted only in the household view.
3. **Option 2, but every threshold flat in today's dollars.** This is simpler, but it
   understates tax on Social Security more each year.

### Decision

Proposed: option 2. It keeps every number traceable to a declared input, follows how
each threshold is actually indexed, and avoids splitting a joint tax bill by a rule
nobody declared.

### Consequences

- Roadmap item `M8-05` (the report) is blocked until this ADR is decided, and so are
  `M8-06` (which depends on it) and `M10-02` (which depends on `M8-06`).
- Under option 2, the income schema (M8-02) gains `taxable` on every stream except
  `social_security`, and the report needs a federal tax table (M8-04). No table ships
  until its figures are cited to IRS publications, so the report fails loudly until the
  maintainer adds one.
