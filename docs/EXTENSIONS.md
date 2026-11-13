# Extensions

Last verified: 2026-11-13

This document describes the extension API for `hfk`. Each section says whether it is implemented, with its roadmap item, or planned. See the [README milestone table](../README.md#milestones) for milestone status. The design baseline is [DESIGN-BRIEF](DESIGN-BRIEF.md).

## What an extension is

An extension is a Python package that adds a bounded feature on top of the core household-finance-kit engine. It may add CLI commands, report sections, validation rules, and doctor checks, but it must not change the meaning of the core ledger or write to the user's Tiller workbook.

The planned API treats extensions as clients of the lower layers:

- Source adapter reads Tiller into a normalized ledger.
- Ledger exposes frozen transaction, category, account, balance, and ledger objects.
- Config loads and validates `household.yaml`, `declarations.yaml`, and the `HFK Plan` sheet.
- Engine provides pure finance calculations over ledger plus config.
- Extensions import engine, ledger, and config APIs to add optional behavior.
- Presentation exposes CLI and renderers.

That boundary matters because `hfk` is public software used with private household data. Extensions must be testable using synthetic fixtures, must fail loudly when required configuration is missing, and must keep private instance facts outside this repository.

## Discovery

Implemented (M6-01): `hfk.ext.discover_extensions()` finds extensions through the Python entry-point group `hfk.extensions`. An installed package registers one target under that group: the extension object, its class, or a function that returns it. Discovery loads every entry point in name order. A package that fails to import is reported as a problem naming the entry point; it never stops other extensions or core. Planned for later M6 items: core loads only extensions enabled by the private instance config, validates their declared config sections, and wires their CLI and report hooks.

Illustrative `pyproject.toml` snippet:

```toml
[project]
name = "hfk-example-extension"
version = "0.1.0"
dependencies = ["household-finance-kit"]

[project.entry-points."hfk.extensions"]
example = "hfk_example_extension:extension"
```

The name on the left is the entry-point name, which must equal the extension's `name`. The target on the right is the extension object described below, its class, or a function that returns it.

## The contract

Implemented (M6-02): `hfk.ext.validate_extension` checks every member below and reports every problem at once in one `ContractError`. `hfk.ext.load_extensions()` discovers and validates; an extension that breaks the contract is refused and reported, never half-used.

| Member | Required | Rule |
|---|---:|---|
| `name` | Yes | A lowercase identifier, such as `settle_up`, equal to the entry-point name. Households enable it by listing it under `extensions` in `household.yaml`. |
| `version` | Yes | The extension package's own version, as a non-empty string. |
| `contract_version` | Yes | `MAJOR.MINOR.PATCH`. This hfk supports contract major version 1; any other major version is refused loudly. |
| `config_section` | Yes | `None` when the extension needs no config, or the file name of its own input file in the instance, such as `retirement.yaml`. Core file names are refused. Sections inside `household.yaml` or `declarations.yaml` are not supported; see proposed [ADR-0016](DECISIONS.md#adr-0016-an-extensions-config-is-a-file-of-its-own-in-the-instance). |
| `schema` | When `config_section` is set | A callable `schema(data, path)` that validates the loaded mapping and returns the extension's config object, raising `hfk.config.ConfigError` naming the file, key path, and fix. `None` when `config_section` is `None`. |
| `requires` | Yes | A mapping with optional `ledger_fields` (names of `Ledger` fields: `transactions`, `categories`, `balances`, `accounts`) and `extensions` (other extension names). |
| `commands()` | Yes | Returns `hfk.ext.ExtensionCommand` objects: `name`, `help`, `configure(parser)`, and `run(args, context)` returning an exit code. |
| `report_sections()` | Optional | Returns `hfk.ext.ReportSection` objects: `name`, `title`, and `build(context)` returning a report object. |
| `doctor` | Yes | A callable `doctor(context, config)` that returns `hfk.engine.Diagnostic` objects. |

The contract is intentionally small. Extensions should use the core engine for shared calculations instead of each inventing its own ledger parser, date rules, money handling, or config semantics.

## A minimal extension

```python
"""A minimal hfk extension."""

from hfk.config import ConfigError
from hfk.ext import ExtensionCommand


def _schema(data, path):
    reason = data.get("enabled_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ConfigError(
            "enabled_reason is required",
            file=path,
            key="enabled_reason",
            fix="write one sentence saying why the household uses this extension",
        )
    return {"enabled_reason": reason}


def _run(args, context):
    print("example report")
    return 0


class ExampleExtension:
    name = "example"
    version = "0.1.0"
    contract_version = "1.0.0"
    config_section = "example.yaml"
    schema = staticmethod(_schema)
    requires = {"ledger_fields": ["transactions", "categories"], "extensions": []}

    def commands(self):
        return [ExtensionCommand("example", "Print the example report.", lambda parser: None, _run)]

    def report_sections(self):
        return []

    def doctor(self, context, config):
        return []


def extension():
    return ExampleExtension()
```

The imports show the rule: extensions may import the engine, ledger, and config layers. The core package never imports this extension directly; discovery happens through entry points.

## Config sections and validation

Each extension owns its configuration. Implemented (M6-03): an extension's config is a separate YAML file in the private instance directory, named by its `config_section`, such as `retirement.yaml`. Whether a small extension may instead own a section inside `household.yaml` or `declarations.yaml` is open: see proposed [ADR-0016](DECISIONS.md#adr-0016-an-extensions-config-is-a-file-of-its-own-in-the-instance).

`hfk.ext.load_enabled_extensions(home, household=..., installed=...)` reads config only for the extensions listed under `extensions` in `household.yaml`. The file of an extension that is not enabled is never opened, so a stale or half-written file cannot break anything. For an enabled extension, every problem is a `ConfigError` naming the file, key path, and fix:

- An enabled extension that is not installed names its `extensions[N]` entry in `household.yaml`.
- An enabled extension whose required extensions (`requires.extensions`) are not enabled names the missing one.
- A missing config file, unparseable YAML, or a value the extension's `schema` rejects names the extension's file.

Implemented (M6-04): `hfk doctor` reports these problems and runs each enabled extension's own `doctor(context, config)` after the core checks. The context is an `hfk.engine.DoctorContext` with `home`, `household`, `declarations`, `ledger` (each `None` when it failed to load) and `today`.

- An entry point that failed to load or broke the contract is `extension-unavailable`: an error when the household enabled it, a warning otherwise.
- A config problem is `extension-config`, naming the file and key; the extension's own doctor is then skipped.
- A doctor hook that raises, or returns something other than `Diagnostic` objects, is `extension-hook-failed` naming the extension. The core checks, the readiness section, and the other extensions still report.
- A disabled extension's hook never runs.
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

On-ledger shares come from the core share function: account ownership weights from `household.yaml`, overridden per transaction by the `sharing` rules in `declarations.yaml`. The extension declares no sharing rules of its own, so a joint bill paid from one person's account is split the same way in settle-up and in the scorecard. The result is a shared expense allocation, not a mutation of the ledger.

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

A private extension can be kept in a private Git repository and installed into the same Python environment as `hfk`. The private instance enables it by name in config. There is no instance-local `extensions/` directory: discovery is entry points only (ADR-0006), so a private extension is installed, not dropped into the instance. The public toolkit should never import that private package directly and should never include its data in tests, examples, or docs.

## Testing extensions

Extensions should test against the synthetic fixture planned for M1 and avoid real workbooks. A good extension test suite should cover:

- Config validation success and failure.
- `doctor()` errors with exact file, key path, and fix guidance.
- Ledger edge cases such as transfers, hidden categories, null balances, and history start clamps when relevant.
- Finished versus unfinished period behavior.
- Renderer output using fictional data only.
- Privacy scan before publishing.

Extension-specific command tests are planned for M6 and later; see the [README milestone table](../README.md#milestones) for current status.

## Stability and versioning

The extension contract will use semver. The extension object declares `contract_version`; core compares it with the supported API range and rejects incompatible extensions loudly. Extension packages also have their own package `version`, which may change for bug fixes or feature additions.

Contract stability goal:

- Patch changes clarify docs or fix behavior without changing the interface.
- Minor changes add optional members or optional fields.
- Major changes may require extension authors to update code.

Until M6 lands, this document is a planned API reference, not a promise that current code can load extensions.
