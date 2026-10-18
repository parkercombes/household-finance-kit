# Architecture

Last verified: 2026-10-17

This document explains the architecture of `hfk`, the household-finance-kit toolkit, for both human maintainers and LLM agents resuming the project cold. The source of truth for product scope is [DESIGN-BRIEF.md](DESIGN-BRIEF.md). Planned work is tracked in [ROADMAP.md](ROADMAP.md), and architectural decisions are recorded in [DECISIONS.md](DECISIONS.md).

## Overview

`hfk` is a public, MIT-licensed Python toolkit for budgeting analysis. It reads a user's Tiller workbook read-only, combines that ledger data with small private YAML files, and produces reports such as monthly scorecards, category target views, balances, renewals, and extension reports.

The project is deliberately conservative. A wrong finance report can look plausible, so the architecture favors explicit configuration, loud validation, frozen normalized data, and deterministic calculations over convenience guesses. The core rule is: read source data, normalize it, validate the user's declared intent, calculate from those inputs, and render output without changing the source workbook.

Implementation status is recorded once, in the milestone table in [README](../README.md#milestones), with item-level detail in [ROADMAP](ROADMAP.md). Other documents link there instead of restating it. The layer descriptions below cover both implemented and planned layers; the package map marks which is which.

## Two-repo model

`hfk` separates the public toolkit from each user's private instance.

| Repo | Visibility | Contents | Must never contain |
|---|---:|---|---|
| Toolkit | Public | Code, docs, examples, profiles, tests, privacy scan, read-only hook | Real financial data, real personal facts, workbooks, statements |
| Instance | Private | `household.yaml`, `declarations.yaml`, `plan.yaml`, optional extension inputs, local data and generated output | Public toolkit source changes unless intentionally vendored |

The toolkit repo is the package developers publish and improve. It contains example configs only, using Alex, Sam, Example Bank, and round numbers. It does not contain a household's real workbook, statements, balances, account numbers, employer names, or private notes.

An instance is a private directory or private repo for one person or household. Its intended shape is defined in the design brief: `household.yaml` for people, files, and account ownership; `declarations.yaml` for judgment calls such as bucket mappings, overrides, and splits; `plan.yaml` for the budget plan; `data/` for local workbooks; and `out/` for generated reports. `data/` and `out/` are gitignored in the instance.

The toolkit locates the instance by an explicit `--home <dir>` flag or by the `HFK_HOME` environment variable. If neither is provided, the current directory is the instance home. The toolkit must not search its own repo for user data.

## Layers

Import rule: a layer imports only from layers below it. Higher layers may depend on lower layers, never the reverse. Extensions may import `engine`, `ledger`, and `config`; core code must not import extensions.

| Layer | Package | Responsibility | Inputs | Outputs | Must never do |
|---|---|---|---|---|---|
| Source adapter | `hfk.source` | Read source systems and normalize them. M1 starts with Tiller `.xlsx`/`.xlsm`; M9 adds Google Sheets. Tiller columns are resolved by header name, never by column position. | Tiller workbook path and source options from config | A normalized `Ledger` | Write to Tiller, rely on column position, perform budgeting policy, hide missing required columns |
| Ledger | `hfk.ledger` | Hold frozen domain records: transactions, categories, accounts, balance rows, and ledger helpers. | Normalized rows from source adapters | Immutable ledger collections using `Decimal` money | Know Tiller sheet names, read files, validate household intent, render reports |
| Config | `hfk.config` | Load and validate private YAML files. Errors name file, key path, and fix. | `household.yaml`, `declarations.yaml`, `plan.yaml`, extension config sections | Typed config objects | Read workbook data, infer missing required decisions, calculate reports |
| Engine | `hfk.engine` | Calculate ownership shares, bucket mappings, scorecards, targets, balances, renewals, rebaseline proposals, and doctor diagnostics. | `Ledger` plus validated config | Pure result objects and diagnostics | Mutate source data, write YAML without an explicit command, call renderers, import extensions |
| Extensions | `hfk.ext` | Discover optional plugins through `hfk.extensions` entry points. | Extension config section, ledger fields, engine outputs as needed | Extra commands, report sections, and doctor checks | Become required for core use, bypass validation, write to Tiller, import presentation internals |
| Presentation | `hfk.cli`, `hfk.render` | Provide CLI commands and render text, CSV, and HTML. `hfk serve` (M5) is the local read-only web front door, bound to `127.0.0.1` only. | Result objects and diagnostics | Terminal output and files under the instance output directory | Recalculate business logic, silently patch data, reach around lower-layer APIs |

This layering is for maintainability and for agent safety. A worker changing renderers should not need to understand Tiller column headers. A worker changing the source adapter should not be able to modify budgeting policy by accident, but must preserve header name lookup so Tiller column reordering does not change behavior. When in doubt, keep data conversion low, decisions in config, calculations in engine, and formatting in presentation.

## Data flow

```text
Private instance home (--home or HFK_HOME)

  data/Tiller*.xls*                household.yaml
       |                           declarations.yaml
       |                           plan.yaml
       v                                |
  +----------------+                    |
  | Source adapter |  read-only          |
  | hfk.source     |<-------------------+
  +----------------+
           |
           v
  +----------------+
  | Ledger         |  frozen records, Decimal amounts
  | hfk.ledger     |
  +----------------+
           |
           v
  +----------------+       +----------------+
  | Config         |------>| Engine         |
  | hfk.config     |       | hfk.engine     |
  +----------------+       +----------------+
                                    |
                                    v
                            +----------------+
                            | Extensions     |
                            | hfk.ext        |
                            +----------------+
                                    |
                                    v
                            +----------------+
                            | Presentation   |
                            | hfk.cli/render |
                            +----------------+
                                    |
                                    v
                         out/report.txt, .csv, .html
```

The workbook is an input only. Reports are generated outputs. Configuration files are user-owned inputs except for explicit commands that are designed to write a specific config file, such as `hfk init` writing a new instance's config files. The plan may also be read from an `HFK Plan` tab in the workbook (M5), through the same read-only loader. The toolkit contains no save path for workbooks; `tests/test_read_only_invariant.py` checks that statically.

## Ownership and shares

Every account in `household.yaml` is either owned by one person or shared with weights:

- `owner: alex`
- `shared: {alex: 0.5, sam: 0.5}`

The model is N-person even though the first settle-up extension is limited to exactly two people. The same rule covers a solo household, equal sharing, income-proportional sharing, and housemates.

A transaction share is computed from the transaction amount and the account's ownership weights using `Decimal` money. If an account is owned by Alex, Alex's weight is `Decimal("1")` and everyone else has `Decimal("0")`. If an account is shared 50/50, each weight is `Decimal("0.5")`. A transaction amount of `Decimal("-100.00")` on that shared account gives Alex `Decimal("-50.00")` and Sam `Decimal("-50.00")`.

Account weights are only the default. `sharing` rules in `declarations.yaml` match a transaction by account, description glob, or category and replace its weights, each with a written reason. The engine exposes one share function that applies both, and every core report and every extension reads shares from it. That is what keeps settle-up and the scorecard from disagreeing about a joint bill paid from one person's account. Two rules with different weights matching the same transaction is a conflict that stops analysis; rules are never ordered or merged.

Shares are arithmetic, not advice. The engine does not decide whether a person should pay more or less. It applies the declared account model, validates that weights sum to one, and reports conflicts loudly.

## Buckets

Buckets are attribute-based. The engine keys behavior off `essential` and `fixed`, not hard-coded bucket names. A household may use four buckets, two buckets, or a custom scheme as long as the declared buckets provide the attributes the requested report needs.

The common four-bucket profile is:

| Bucket example | `essential` | `fixed` | Engine behavior |
|---|---:|---:|---|
| Fixed Essential | true | true | Compare tightly to plan because timing and amount should be predictable |
| Variable Essential | true | false | Pace mid-month so normal timing does not look like overspending too early |
| Fixed Discretionary | false | true | Compare to plan; useful for subscriptions and recurring choices |
| Variable Discretionary | false | false | Pace and summarize as flexible spending |

Fixed buckets are checked against the plan with tight tolerance. Variable buckets can be paced, especially in mid-month views, because a full-month target should not be treated as equally spendable on day 1 and day 30. Essential and discretionary attributes support views about what is committed versus flexible without embedding any recommendation about what a household should cut.

Adoption levels:

| Level | Meaning | Typical use |
|---:|---|---|
| 0 | Use Tiller `Type` and `Group` only | Basic spend by category or group |
| 1 | Two buckets | Essential versus discretionary |
| 2 | Four buckets | Essential/discretionary crossed with fixed/variable |

The three presets — simple, four-bucket, and fifty-thirty-twenty — ship inside the package as `hfk/profiles/` package data, resolved with `importlib.resources`, and are mirrored at the top-level `profiles/` for reading the repository on GitHub, with a test keeping the two copies identical. A profile is a starting point, not hidden policy.

`mapping_source` controls how categories map into buckets. The default is `tiller_group`, so Tiller remains the place users edit their taxonomy. An `explicit` mapping source is allowed when a household wants all mappings declared outside Tiller.

Bucket names and Tiller group names are different vocabularies, so the map between them is always declared. Under `tiller_group`, a `groups` section maps every expense group in the ledger to a bucket, and a category inherits its group's bucket. Under `explicit`, a `categories` section maps every expense category directly. A category resolves through `splits`, then `overrides`, then the map; a category in both `splits` and `overrides` is a conflict. The engine never guesses a bucket from a group name that happens to resemble one.

Overrides and splits are first-class judgment calls and each must include a reason. An override maps one category to a bucket when the plan and source taxonomy disagree. A split allocates one category across multiple buckets using weights. The reason is not decoration; it prevents future maintainers and LLM agents from "cleaning up" intentional decisions.

Orphan categories are categories with no bucket mapping, often caused by renaming a category in Tiller and leaving history under the old name. `hfk doctor` must fail on orphans, name each category, and print the fix. It must not silently remap old history.

## Invariants

| Invariant | Rule | Why |
|---|---|---|
| Read-only Tiller | Open workbooks read-only and never save them. | Saving with spreadsheet libraries can strip workbook features; users own the source. |
| Fail loudly | Missing required keys, columns, stale data, and conflicting constraints are errors. | Quiet guesses produce believable but wrong reports. |
| Flag, don't fix | Diagnostics report problems and proposed fixes; they do not rewrite source data automatically. | Financial judgment belongs to the user. |
| Cents canonical | Money is represented in cents with `Decimal`; comparisons allow no more than one cent tolerance for rounding boundaries. | Float drift must not create fake variances or hide real ones. |
| Never project unfinished months | Settle-up and projection-style reports do not finalize a month until it has ended. | Partial months distort both spending pace and obligations. |
| `history_start` clamp | Analysis windows are clamped to the configured start date. | Old setup noise or pre-budget history should not leak into reports. |
| No silent defaults | Required choices must be present when a feature needs them. | Defaults are policy, and policy must be visible in instance data. |

These invariants apply to code, docs, examples, tests, and agent-generated changes.

## Error handling and diagnostics

A good error message names three things:

| Required part | Example shape |
|---|---|
| File | `declarations.yaml` |
| Key path | `buckets[2].fixed` |
| Fix | `Add fixed: true or fixed: false to this bucket.` |

For workbook errors, the message should name the workbook, sheet, and header or row condition. For config errors, it should name the YAML file and key path. For `doctor` diagnostics, it should explain whether the problem blocks analysis or is a warning, and it should give the smallest safe user action.

Bad: `invalid config`

Good: `declarations.yaml: splits.Fuel.reason is required. Add a short reason explaining why this category is split across buckets.`

Diagnostics should be deterministic and suitable for tests. Do not rely on traceback text as the user-facing explanation.

## Extensions

Extensions are optional plugins discovered through the `hfk.extensions` Python entry-point group. An extension declares its name, version, config section and schema, required ledger fields, CLI commands, optional report sections, and a `doctor()` hook.

The first planned extensions are `settle_up` and `retirement`. `settle_up` produces a two-person monthly sharing statement from declared account ownership, on-ledger sharing rules, and off-ledger shared items. `retirement` models income versus need using `retirement.yaml`; it is arithmetic and reporting, not financial advice.

See [EXTENSIONS.md](EXTENSIONS.md) for the extension API contract and extension-specific rules.

## Package map

The package names below are the approved architecture from the design brief. Status here mirrors the README milestone table; update both in the same change.

| Path | Layer | Implementation status |
|---|---|---|
| `src/hfk/source` | Source adapter | Done (M1): Tiller workbook reader and synthetic fixture generator; planned M9 for Google Sheets adapter |
| `src/hfk/ledger` | Ledger | Done (M1): frozen dataclasses and helpers |
| `src/hfk/config` | Config | Planned M2 YAML loading and validation |
| `src/hfk/engine` | Engine | Planned M2 doctor basics; M3 ownership, buckets, scorecard; M4 targets, balances, renewals |
| `src/hfk/ext` | Extensions | Planned M6 extension discovery and API support |
| `src/hfk/render` | Presentation | Planned M5 text, CSV, and HTML renderers |
| `src/hfk/cli.py` | Presentation | `--version` and `dev fixture` work; analysis subcommands are stubs that become functional across M2-M8 |

## Implemented vs planned

See the [README milestone table](../README.md#milestones). It is the only place milestone status is recorded.

## Testing strategy

Tests must use synthetic data only. No real workbook, real account, real institution, real employer, real address, or real private category set belongs in the public repository.

The synthetic Tiller workbook fixture planned for M1 is the base for source, ledger, engine, and presentation tests. It should contain fictional rows with Alex, Sam, Example Bank, round amounts, and edge cases that matter: missing optional columns, extra unknown columns, hidden categories, transfers, income, expenses, null balances, renamed categories, and lumpy annual bills.

Layer test expectations:

| Layer | Tests assert |
|---|---|
| Source adapter | Header-name lookup, required-column failures, read-only workbook handling, lock-file ignore behavior, amount sign preservation |
| Ledger | Frozen records, `Decimal` amounts, helper behavior, no Tiller-specific leakage above source parsing |
| Config | Required keys, optional feature sections, account ownership validation, bucket schemas, reasons for overrides and splits |
| Engine | Share allocation, bucket mapping, pacing, scorecard math, history clamps, orphan diagnostics, one-cent tolerance boundaries |
| Extensions | Entry-point contract, config-section validation, required ledger fields, extension doctor output |
| Presentation | Formatting only; no business logic or recalculation |

CI must include the privacy scan. The real command today is `python scripts/privacy_scan.py --root .`. The scan blocks workbook-like files, account-number patterns, email addresses outside the allowlist, and locally configured denylist terms.

## Security and privacy model

The security model is simple: the public toolkit contains code and examples; private instances contain personal data. The toolkit must not ship private finance facts, and generated reports should stay under the instance output directory. Examples use only Alex, Sam, Example Bank, and round numbers.

The project also ships guardrails for agents and contributors: gitignore patterns for financial files, a privacy scan for CI and local use, and a Tiller read-only hook for agent workflows. These guardrails reduce accidents, but they do not replace review. Before publishing, run the privacy scan and review changed docs for private names, brands, numbers, and facts.

See [PRIVACY.md](PRIVACY.md) for the full privacy policy and contributor checklist.
