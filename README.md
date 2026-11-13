# household-finance-kit

Last verified: 2026-11-13

## What Is This

`household-finance-kit` (`hfk`) is a public, open-source toolkit for households that use a Tiller spreadsheet (it's a requirement) as their financial ledger and want local budgeting analysis and planning from it. 

**Not affiliated with Tiller:** this project is unofficial. It is not affiliated with, endorsed by, or sponsored by Tiller, and "Tiller" is a trademark of its owner [Tiller](https://tiller.com/). 

Background: I've used Tiller (in Excel and now transitioned to using Google Sheets), and it has been fantastic about showing me how I spend my money.  However, it never really answered the question of am I under- or over-spending.  It has tools to help with budgeting but I didn't know how to leverage it (they have resources that I didn't use). So I started building this project for me and it has been immensely useful at getting me more involved in my finances.  This in turn has helped me curb some spending, know when I can spend more, and how much I can save away for trips and gifts etc. Therefore, I have redesigned it for public use. I've been a computer programmer my whole life, and while I'm comfortable using coding tools and AI, my goal is to make it usable by anyone familiar with just spreadsheets.  Right now it needs a few terminal commands.  You can use this project as is, but understand that it does require use of Tiller which has an annual subscription cost that I find completely reasonable for the value I receive from it. 

## Current Status

M0 Foundations through M4 Analyses are done, including the `M3-07` parity check against a private instance. M5 Usability is in progress: `M5-00` through `M5-10` are done and `M5-11` (`hfk open` and a double-click launcher) is next. The [Milestones](#milestones) table below is the single status record for the project. Other documents link to it rather than restating it, and [ROADMAP](docs/ROADMAP.md) holds item-level status.

Working today:

- `hfk init <dir>` interviews you from the newest workbook in `data/` and writes a private instance with `household.yaml` and `declarations.yaml`, plus the Tiller read-only hook (`--git` also sets up git and the privacy hook).
- `hfk doctor` checks config and data quality and fails loudly on stale data, unmapped categories, conflicts and undeclared closed accounts. It ends with a readiness section that says, in plain words, whether the workbook, history, category mapping and plan are ready and what to fix.
- `hfk scorecard`, `hfk categories`, `hfk balances`, `hfk networth`, `hfk renewals` and `hfk rebaseline` report from closed months, each with `--format text|csv|html`.
- `hfk plan check` validates the budget plan.
- `hfk serve` shows the reports as a local read-only web page on `127.0.0.1`, with a month picker and a Regenerate button.
- `hfk dev fixture --out PATH [--plan-tab]` writes a synthetic workbook for tests and demos.

The budget plan can be read from an `HFK Plan` sheet in your workbook (`plan: {source: workbook}` in `household.yaml`) or from `plan.yaml`. Per [ADR-0015](docs/DECISIONS.md#adr-0015-the-plan-lives-only-in-the-hfk-plan-sheet-planyaml-is-removed), the sheet becomes the only source and `plan.yaml` is removed: planned (M5-18).

## Who It Is For

`hfk` is for:

- A single person on their first budget who wants clear plan-vs-actual numbers without sending data to another service.
- A couple who share some accounts or expenses but still need ownership shares to be explicit.
- A family where each person or household keeps a private `hfk` instance with their own workbook, config, generated reports, and local judgement calls.

The public toolkit is designed to be understandable by a non-programmer household member and by an LLM agent resuming development cold.

## Requirements

- A Tiller spreadsheet exported as `.xlsx` or `.xlsm`.
- Python >= 3.10.
- Local YAML instance files: `household.yaml` and `declarations.yaml`.
- A budget plan: an `HFK Plan` sheet in the workbook, or `plan.yaml` until M5-18 removes it.

`hfk` **never writes to the Tiller workbook**. The source adapter must open workbooks read-only, and the guard hook at `hooks/tiller_guard.py` exists to block agent edits that would call `save` on a workbook.

## Two-Repo Model
There are two separate places:

- **Public toolkit repo:** this repository. It contains code, docs, tests, examples, synthetic fixtures, presets, hooks, and no real household data.
- **Private instance repo or directory:** one per person or household. This is where real workbooks, generated reports, and private decisions live.

Instance layout (the plan lives in the workbook's `HFK Plan` sheet; `plan.yaml` is accepted until M5-18):

```text
my-finances/
  household.yaml
  declarations.yaml
  shared-items/
  retirement.yaml
  data/
  out/
  .claude/settings.json
  .gitignore
```

The toolkit never reads its own directory for user data. A private instance is located by `--home <dir>` or `HFK_HOME`, with the current directory as the default.

## Quickstart
These commands set up a development checkout and run the checks. The clone command shown is for making a disposable local copy from an existing checkout before the public URL is assigned.

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

What has landed by milestone, and what is still planned:

- Available now (M1): `hfk dev fixture --out PATH` generates a synthetic Tiller workbook for tests and demos.
- Available now (M2): `hfk doctor` for config validation and loud data-quality checks, including plan-line and sharing-rule conflicts.
- Available now (M3): `hfk scorecard --month YYYY-MM [--who SLUG]` for closed-month plan-vs-actual by bucket, using the selected person's share.
- Available now (M4): `hfk categories --month YYYY-MM`, `hfk balances`, `hfk networth`, `hfk renewals`, `hfk rebaseline`, and `hfk plan check`.
- Available now (M5): `hfk init <dir>` as an interview that writes the config from your workbook, the `HFK Plan` sheet as a plan source, `--format text|csv|html` on the reports, and a readiness section in `hfk doctor`, and `hfk serve` for a local read-only page.
- Planned (M5): `hfk open`, a double-click launcher, one-line install, non-programmer docs, and the sheet as the only plan source (M5-18).
- Planned (M7): `hfk settle YYYY-MM` from the `settle_up` extension.

## Milestones

See [ROADMAP](docs/ROADMAP.md) for item-level status and executable acceptance criteria.

| Milestone | Status | Summary |
|---|---:|---|
| M0 | Done | Foundations: design brief, docs, skeleton, CI, privacy scan, Tiller guard hook |
| M1 | Done | Reader, Ledger types, synthetic workbook fixture |
| M2 | Done | Config loading, validation, and `hfk doctor` with orphan, stale-data, and closed-account checks |
| M3 | Done | Ownership shares, bucket mapping, monthly scorecard, doctor conflict checks, and the `M3-07` parity check against a private instance |
| M4 | Done | Category targets, balances, net worth, renewals, rebaseline, plan check |
| M5 | In progress | Instance interview, plan-in-workbook tab, renderers, local front door and launcher, one-line install, non-programmer docs |
| M6 | Planned | Extension API and discovery |
| M7 | Planned | `settle_up` extension for exactly two people |
| M8 | Planned | `retirement` extension, R1 through R6 |
| M9 | Planned | Google Sheets source adapter |
| M10 | Planned | Community extensions: FSA tracking, pension add-ons, home purchase modelling |

## What It Will Do

Core `hfk` analysis reads the Tiller `Transactions`, `Categories`, and `Balance History` sheets by header name, normalizes them into a Ledger, validates household configuration, and produces budgeting views: monthly scorecards, category targets, balances and net worth, renewals with sinking-fund adequacy, rebaseline proposals, and doctor checks for stale or unmapped data.

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
