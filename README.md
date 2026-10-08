# household-finance-kit

Last verified: 2026-10-08

`household-finance-kit` (`hfk`) is a public, open-source Python toolkit for households that use a Tiller spreadsheet as their financial ledger and want local budgeting analysis from it. It reads the workbook read-only, combines it with small YAML files owned by the household, and produces reports without becoming the place where private financial data lives.

**Not affiliated with Tiller:** this project is unofficial. It is not affiliated with, endorsed by, or sponsored by Tiller, and "Tiller" is a trademark of its owner.

## Current Status

`hfk` is at **M0 Foundations**. The repository currently contains the approved design brief, documentation, package skeleton, CLI stubs, privacy scan, Tiller read-only guard hook, CI workflow, example configs, bucket presets, and a small pytest suite. The CLI subcommands for analysis are not implemented yet; planned commands intentionally print `not implemented yet` and exit with code 2 until their milestones land.

## Who It Is For

`hfk` is for:

- A single person on their first budget who wants clear plan-vs-actual numbers without sending data to another service.
- A couple who share some accounts or expenses but still need ownership shares to be explicit.
- A family where each person or household keeps a private `hfk` instance with their own workbook, config, generated reports, and local judgement calls.

The public toolkit is designed to be understandable by a non-programmer household member and by an LLM agent resuming development cold.

## Requirements

- A Tiller spreadsheet exported as `.xlsx` or `.xlsm`.
- Python >= 3.10.
- Local YAML instance files: `household.yaml`, `declarations.yaml`, and `plan.yaml`.

`hfk` **never writes to the Tiller workbook**. The source adapter must open workbooks read-only, and the guard hook at `hooks/tiller_guard.py` exists to block agent edits that would call `save` on a workbook.

## Two-Repo Model

There are two separate places:

- **Public toolkit repo:** this repository. It contains code, docs, tests, examples, synthetic fixtures, presets, hooks, and no real household data.
- **Private instance repo or directory:** one per person or household. This is where real workbooks, generated reports, and private decisions live.

Planned instance layout:

```text
my-finances/
  household.yaml
  declarations.yaml
  plan.yaml
  shared-items/
  retirement.yaml
  extensions/
  data/
  out/
  .claude/settings.json
  .gitignore
```

The toolkit never reads its own directory for user data. A private instance is located by `--home <dir>` or `HFK_HOME`, with the current directory as the default.

## Quickstart

These are the commands intended to work for the M0 repository state. The clone command shown is for making a disposable local copy from an existing checkout before the public URL is assigned.

```bash
git clone . household-finance-kit
cd household-finance-kit
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
hfk --version
python -m pytest -q
python scripts/privacy_scan.py --root .
```

## Coming Soon

The design includes these planned commands. They are listed here to show direction, not current functionality.

- Available now (M1): `hfk dev fixture --out PATH` generates a synthetic Tiller workbook for tests and demos.
- Planned (M2): `hfk doctor` for config validation and loud data-quality checks.
- Planned (M3): `hfk scorecard --month YYYY-MM` for monthly plan-vs-actual by bucket.
- Planned (M4): `hfk categories --month YYYY-MM`, `hfk balances`, `hfk networth`, `hfk renewals`, `hfk rebaseline`, and `hfk plan edit`.
- Planned (M5): `hfk init <dir>` for creating a private instance skeleton.
- Planned (M7): `hfk settle YYYY-MM` from the `settle_up` extension.

## Milestones

See [ROADMAP](docs/ROADMAP.md) for item-level status and executable acceptance criteria.

| Milestone | Status | Summary |
|---|---:|---|
| M0 | Done | Foundations: design brief, docs, skeleton, CI, privacy scan, Tiller guard hook |
| M1 | Done | Reader, Ledger types, synthetic workbook fixture |
| M2 | Planned | Config loading, validation, and `hfk doctor` |
| M3 | Planned | Ownership, bucket mapping, monthly scorecard |
| M4 | Planned | Category targets, balances, net worth, renewals, rebaseline, plan editor |
| M5 | Planned | Instance creation, hook wiring, renderers, CLI polish |
| M6 | Planned | Extension API and discovery |
| M7 | Planned | `settle_up` extension for exactly two people |
| M8 | Planned | `retirement` extension, R1 through R6 |
| M9 | Planned | Google Sheets source adapter |
| M10 | Planned | Community extensions and local web front door |

## What It Will Do

Core `hfk` analysis is planned to read Tiller `Transactions`, `Categories`, and `Balance History` sheets by header name, normalize them into a Ledger, validate household configuration, and produce budgeting views. Planned core reports include monthly scorecards, category targets, balances and net worth, renewals, sinking-fund checks, rebaseline proposals, and doctor checks for stale or unmapped data.

The first planned extension is `settle_up` (M7). It is limited to exactly two people and computes monthly paid-vs-owed totals, shared on-ledger transactions, off-ledger shared items, and a net transfer. It never settles an unfinished month and never writes back to Tiller.

The second planned extension is `retirement` (M8). It models income-vs-need mechanics from declared people, income streams, expenses, inflation assumptions, and versioned tax data. It is arithmetic, not advice: no product recommendations, no optimization strategy, and no claim that a scenario is the right financial decision.

## Documentation Map

- [README](README.md): overview, status, quickstart, and safety summary.
- [AGENTS](AGENTS.md): LLM entry point and development rules.
- [CLAUDE](CLAUDE.md): Claude Code pointer.
- [CONTRIBUTING](CONTRIBUTING.md): development and PR process.
- [CHANGELOG](CHANGELOG.md): release history.
- [LICENSE](LICENSE): MIT license.
- [DESIGN-BRIEF](docs/DESIGN-BRIEF.md): approved source of truth.
- [ARCHITECTURE](docs/ARCHITECTURE.md): planned system layers and boundaries.
- [ROADMAP](docs/ROADMAP.md): milestones and acceptance criteria.
- [DECISIONS](docs/DECISIONS.md): architecture decision records.
- [EXTENSIONS](docs/EXTENSIONS.md): extension API and planned first extensions.
- [TILLER-SCHEMA](docs/TILLER-SCHEMA.md): Tiller sheets and headers.
- [PRIVACY](docs/PRIVACY.md): public-repo privacy model.

## Safety And Privacy

This is a public repo, so it must contain no real financial data, no personal names, no account numbers, no addresses, no emails, no employer names, and no private balances. Examples use fictional names Alex and Sam, `Example Bank`, and round numbers. The privacy scan is part of the M0 safety system and should be run before sharing changes:

```bash
python scripts/privacy_scan.py --root .
```

See [PRIVACY](docs/PRIVACY.md) for the full privacy model.

## License

MIT. See [LICENSE](LICENSE).
