# Extensions

Last verified: 2026-10-08

This document describes the planned extension API for `hfk`. It is a contract proposal for milestone M6 and later. Nothing in this file works today in M0: the current CLI subcommands are stubs, and the source adapter, ledger, config loader, engine, and extension system are not implemented yet. The design baseline is [DESIGN-BRIEF](DESIGN-BRIEF.md).

## What an extension is

An extension is a Python package that adds a bounded feature on top of the core household-finance-kit engine. It may add CLI commands, report sections, validation rules, and doctor checks, but it must not change the meaning of the core ledger or write to the user's Tiller workbook.

The planned API treats extensions as clients of the lower layers:

- Source adapter reads Tiller into a normalized ledger.
- Ledger exposes frozen transaction, category, account, balance, and ledger objects.
- Config loads and validates `household.yaml`, `declarations.yaml`, and `plan.yaml`.
- Engine provides pure finance calculations over ledger plus config.
- Extensions import engine, ledger, and config APIs to add optional behavior.
- Presentation exposes CLI and renderers.

That boundary matters because `hfk` is public software used with private household data. Extensions must be testable using synthetic fixtures, must fail loudly when required configuration is missing, and must keep private instance facts outside this repository.

## Discovery

Planned for M6: `hfk` discovers extensions through the Python entry-point group `hfk.extensions`. An installed package registers one object factory under that group. Core discovers installed entry points, loads only extensions enabled by the private instance config, validates their declared config sections, and wires their CLI/report hooks.

Illustrative `pyproject.toml` snippet:

```toml
[project]
name = "hfk-example-extension"
version = "0.1.0"
dependencies = ["household-finance-kit"]

[project.entry-points."hfk.extensions"]
example = "hfk_example_extension:extension"
```

The name on the left is the entry-point name. The callable on the right returns or exposes the extension object described below. This is planned API text, not a working interface in M0.

## The contract

Planned for M6, an extension object provides these members:

| Member | Required | Purpose |
|---|---:|---|
| `name` | Yes | Stable machine name, such as `settle_up` or `retirement`. This is the value enabled from private instance config. |
| `version` | Yes | Extension package version. This follows the package's own release version. |
| `contract_version` | Yes | Extension API contract version the extension expects, using semver. Core rejects incompatible versions loudly. |
| `config_section` | Yes | Name of the config section owned by the extension, or a pointer to the extension's own input file when the feature uses one. |
| `schema` | Yes | Validation schema or validator for that config section. Missing or invalid required keys are errors. |
| `requires` | Yes | Required ledger fields, config capabilities, or other extensions. Core checks these before running commands. |
| `commands()` | Yes | Returns planned CLI subcommands contributed by the extension. Commands run through normal `hfk` presentation wiring. |
| `report_sections()` | Optional | Returns report section builders for text, CSV, or HTML output. |
| `doctor()` | Yes | Hook for extension-specific diagnostics, stale data checks, and configuration errors. |

The contract is intentionally small. Extensions should use the core engine for shared calculations instead of each inventing its own ledger parser, date rules, money handling, or config semantics.

## A minimal extension

Illustrative skeleton only. This is not executable against M0.

```python
"""Example planned hfk extension skeleton."""

from hfk import config, engine, ledger


class ExampleExtension:
    name = "example"
    version = "0.1.0"
    contract_version = "1.0.0"
    config_section = "example"
    schema = {
        "type": "object",
        "required": ["enabled_reason"],
        "properties": {
            "enabled_reason": {"type": "string"},
        },
    }
    requires = {
        "ledger_fields": ["transactions", "categories"],
        "extensions": [],
    }

    def commands(self):
        return []

    def report_sections(self):
        return []

    def doctor(self, loaded_config: config.LoadedConfig, book: ledger.Ledger):
        return []


def extension():
    return ExampleExtension()
```

The imports show the rule: extensions may import the engine, ledger, and config layers. The core package never imports this extension directly; discovery happens through entry points.

## Config sections and validation

Each extension owns its configuration. Small extensions may own a section in `household.yaml` or `declarations.yaml`. Larger features may own a separate file in the private instance directory, such as `retirement.yaml`. Either way, validation is part of the extension contract.

The planned behavior is fail-loud:

- If an enabled extension's section is missing, `hfk doctor` reports the file, key path, and fix.
- If a key has the wrong type, validation reports the exact key path and expected shape.
- If an extension requires a ledger field that the selected source adapter cannot provide, the command stops before producing numbers.
- If config conflicts, the extension reports the conflict instead of guessing.

The public toolkit repo may include example config using Alex and Sam only. Real household data, employer details, balances, account numbers, addresses, emails, and product brands belong only in private instance repos.

## Rules

The extension boundary is part of the privacy and correctness model.

- Core never imports an extension by package name. It only discovers entry points.
- Extensions import only `hfk.engine`, `hfk.ledger`, and `hfk.config` APIs, plus their own package code.
- Extensions never write to Tiller. They may read the normalized ledger produced by the source adapter and may write generated reports under the user's private output directory.
- Public extensions must not include real data. Tests and docs use the synthetic fixture, Alex, Sam, Example Bank, and round example numbers.
- Extensions must be deterministic for the same input files.
- Extensions must make unfinished-period rules explicit. A feature that could produce misleading in-progress numbers must stop or clearly label them.
- Extensions must include `doctor()` checks for stale external data, missing private inputs, and unsupported configurations.

## Built-in-first extensions

`settle_up` and `retirement` are planned as built-in-first extensions: they exercise the M6 contract while remaining optional features. Their names and high-level behavior are part of the approved design, but the code does not exist in M0.

### `settle_up`

Planned for M7, `settle_up` computes a monthly statement for exactly two people. It is intended for a household that would otherwise maintain a manual settle-up spreadsheet, but wants the calculation to come from the read-only Tiller ledger plus a small private YAML file for off-ledger items.

Scope and limits:

- Exactly two people are supported.
- The default split is weighted 50/50.
- Other two-person weights are allowed when declared, such as 60/40.
- Larger groups are explicitly out of scope for the built-in extension and open to the community.
- The extension never settles an unfinished month.
- The extension never writes to Tiller.

On-ledger sharing rules cover transactions that are already in Tiller but paid from an account that needs settle-up treatment. A rule can declare that matching transactions on a given account are shared. Matching is planned to use declared account and description-pattern rules from the private instance config. The result is a shared expense allocation, not a mutation of the ledger.

Off-ledger shared items live in `shared-items/YYYY-MM.yaml` in the private instance. These are costs not present in the user's Tiller workbook, such as a bill paid from another person's untracked account. Example using only fictional data:

```yaml
schema_version: 1
items:
  - label: "Example utility bill"
    amount: 120.00
    paid_by: alex
    weights: {alex: 0.5, sam: 0.5}
    bucket: "Fixed Essential"
  - label: "Example shared supplies"
    amount: 40.00
    paid_by: sam
    weights: {alex: 0.5, sam: 0.5}
    bucket: "Variable Essential"
```

Planned command behavior: `hfk settle YYYY-MM` outputs category totals for shared accounts and shared items, per-person paid versus owed, and the net transfer. Renderers are planned to support text, CSV, and HTML. A paste-ready block may be emitted for users who keep their own manual tab, but the workbook remains read-only.

Regression testing should compare the planned computation against a hand-built historical statement to the cent. The private instance owner can create a small expected statement from a finished month, run the synthetic or private fixture locally, and confirm that category totals, paid amounts, owed amounts, and net transfer match. Public tests must use synthetic data only.

### `retirement`

Planned for M8, `retirement` is an income-vs-need model. It models mechanics, not advice. It must not recommend financial products, claiming strategies, Roth conversion plans, or optimized behavior.

Input lives in `retirement.yaml` in the private instance. The planned schema includes:

- People, with birth year-month and retirement year.
- Income streams with type `social_security`, `pension`, `account_drawdown`, or `other`.
- Optional COLA per income stream. Income is flat after retirement unless COLA is declared.
- Itemized expenses in today's dollars, with inflation assumptions.
- Versioned tax data tagged with tax year.
- State-tax module selection, such as none, flat, or bracket.

Claim-age scenarios are mutually exclusive alternatives, not a timeline. For example, a Social Security claim-age scenario compares separate possible starts; it does not imply that a person claims at several ages over time.

Planned outputs include a calendar-year track and an income-vs-need gap, shown per person and for the household. Tax data must have a staleness gate: if the versioned tax data is older than the configured allowed tax-year age, the extension fails loudly before producing a projection.

Out of scope for the built-in extension:

- Monte Carlo simulations.
- Optimisation.
- Roth conversion strategy.
- Product selection.
- Personalized financial advice.

## Private and community extensions

Some models belong outside the public toolkit. Employer-specific pension schedules, home-purchase modeling, reimbursement workflows, and local household conventions can live in separate packages. They may be public community packages when they contain no private data, or private repos when they encode employer rules or household-specific assumptions.

A private extension can be kept in a private Git repository and installed into the same Python environment as `hfk`. The private instance enables it by name in config. The public toolkit should never import that private package directly and should never include its data in tests, examples, or docs.

## Testing extensions

Extensions should test against the synthetic fixture planned for M1 and avoid real workbooks. A good extension test suite should cover:

- Config validation success and failure.
- `doctor()` errors with exact file, key path, and fix guidance.
- Ledger edge cases such as transfers, hidden categories, null balances, and history start clamps when relevant.
- Finished versus unfinished period behavior.
- Renderer output using fictional data only.
- Privacy scan before publishing.

The public repo's real commands today are limited to `pip install -e .`, `hfk --version`, `python -m pytest -q`, and `python scripts/privacy_scan.py --root .`. Extension-specific command tests are planned for M6 and later.

## Stability and versioning

The extension contract will use semver. The extension object declares `contract_version`; core compares it with the supported API range and rejects incompatible extensions loudly. Extension packages also have their own package `version`, which may change for bug fixes or feature additions.

Contract stability goal:

- Patch changes clarify docs or fix behavior without changing the interface.
- Minor changes add optional members or optional fields.
- Major changes may require extension authors to update code.

Until M6 lands, this document is a planned API reference, not a promise that current code can load extensions.
