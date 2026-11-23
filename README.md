# household-finance-kit

Last verified: 2026-11-22

## What Is This

`household-finance-kit` (`hfk`) is a public, open-source toolkit for households that use a Tiller spreadsheet (it's a requirement) as their financial ledger and want local budgeting analysis and planning from it. 

**Not affiliated with Tiller:** this project is unofficial. It is not affiliated with, endorsed by, or sponsored by Tiller, and "Tiller" is a trademark of its owner [Tiller](https://tiller.com/). 

Background: I've used Tiller (in Excel and now transitioned to using Google Sheets), and it has been fantastic about showing me how I spend my money.  However, it never really answered the question of am I under- or over-spending.  It has tools to help with budgeting but I didn't know how to leverage it (they have resources that I didn't use). So I started building this project for me and it has been immensely useful at getting me more involved in my finances.  This in turn has helped me curb some spending, know when I can spend more, and how much I can save away for trips and gifts etc. Therefore, I have redesigned it for public use. I've been a computer programmer my whole life, and while I'm comfortable using coding tools and AI, my goal is to make it usable by anyone familiar with just spreadsheets.  Right now it needs a few terminal commands.  You can use this project as is, but understand that it does require use of Tiller which has an annual subscription cost that I find completely reasonable for the value I receive from it. 

## Current Status

Every milestone except M0 and M5 is done, and what is left in those two waits on the maintainer. M0 lacks only publishing the package to PyPI (`M0-08`). M5 lacks the usability session (`M5-14`) and the README rewrite that follows it (`M5-15`). The [Milestones](#milestones) table below is the single status record for the project. Other documents link to it rather than restating it, and [ROADMAP](docs/ROADMAP.md) holds item-level status.

Working today:

- `hfk setup [DIR]` makes your hfk folder, `HFK` in your home folder by default, with an empty `data` folder for your workbook and the double-click launchers, but no settings yet; running it again changes nothing. On Windows it adds Open HFK to the Start menu; on a Mac it opens the folder in Finder. Then it opens the setup page in your browser (ADR-0022): choose your workbook download, answer the questions, and it saves the settings and shows whether the reports are ready.
- `hfk init <dir>` interviews you from the newest workbook in `data/` and writes a private instance with `household.yaml` and `declarations.yaml`, plus the Tiller read-only hook (`--git` also sets up git and the privacy hook). If the workbook already has an `HFK Plan` sheet, the interview reads it and asks about each category the sheet puts outside its group's bucket ([ADR-0021](docs/DECISIONS.md#adr-0021-hfk-init-reads-an-existing-hfk-plan-sheet)).
- `hfk doctor` checks config and data quality and fails loudly on stale data, unmapped categories, conflicts and undeclared closed accounts. It ends with a readiness section that says, in plain words, whether the workbook, history, category mapping and plan are ready and what to fix.
- `hfk scorecard`, `hfk categories`, `hfk balances`, `hfk networth`, `hfk renewals` and `hfk rebaseline` report from closed months, each with `--format text|csv|html`.
- `hfk plan check` validates the budget plan.
- `hfk serve` shows the reports as a local read-only web page on `127.0.0.1`, with a month picker, a Regenerate button, and a Choose file button that copies a new workbook download into `data`. On a folder with no settings yet it shows the setup page instead. Each run's address starts with a random token, so an old address stops working when hfk stops ([PRIVACY](docs/PRIVACY.md#the-browser-pages-and-a-shared-computer)). `hfk open` starts it on a free port and opens your browser, and `hfk init` writes double-click launchers (`Open HFK.command`, `Open HFK.bat`) that run `hfk open` for you.
- `hfk dev fixture --out PATH [--no-plan-tab]` writes a synthetic workbook, with the example `HFK Plan` sheet, for tests and demos.
- `hfk plan to-sheet` converts a `plan.yaml` from before ADR-0015 to CSV rows for the `HFK Plan` sheet.
- `hfk settle YYYY-MM` prints the two-person settle-up statement for a finished month: what each person paid and owes, and the one transfer that settles it. Turn it on with `extensions: [settle_up]` in `household.yaml` and declare who pays each shared account in `settle_up.yaml`. It also takes `--format text|csv|html|paste` and `--compare` against a hand-built statement.
- `hfk retirement --claim-age alex=67 --claim-age sam=67` prints a calendar-year income-vs-need track in today's dollars from `retirement.yaml`, per person and for the household. Turn it on with `extensions: [retirement]`. It shows arithmetic, not advice. It uses the 2026 federal tax table that ships with hfk, cited to IRS publications, or one you name with `--tax-table PATH`. Federal tax leaves out the deductions for people 65 and older, so it is overstated for them (proposed ADR-0020).

The budget plan lives only in an `HFK Plan` sheet that you add to your own workbook ([ADR-0015](docs/DECISIONS.md#adr-0015-the-plan-lives-only-in-the-hfk-plan-sheet-planyaml-is-removed)). hfk never writes the workbook. If your workbook has no `HFK Plan` sheet yet, `hfk init` writes starter rows to `out/hfk-plan-starter.csv` for you to paste in; if it has one, hfk uses it. A leftover `plan.yaml` is an error whose fix is `hfk plan to-sheet`.

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
- A budget plan: an `HFK Plan` sheet that you add to the workbook.

`hfk` **never writes to the Tiller workbook**. The source adapter must open workbooks read-only, and the guard hook at `hooks/tiller_guard.py` exists to block agent edits that would call `save` on a workbook.

## Two-Repo Model
There are two separate places:

- **Public toolkit repo:** this repository. It contains code, docs, tests, examples, synthetic fixtures, presets, hooks, and no real household data.
- **Private instance repo or directory:** one per person or household. This is where real workbooks, generated reports, and private decisions live.

Instance layout (the plan lives in the workbook's `HFK Plan` sheet, not in a file):

```text
my-finances/
  household.yaml
  declarations.yaml
  settle_up.yaml
  shared-items/
  retirement.yaml
  data/
  out/
  .claude/settings.json
  .gitignore
```

The toolkit never reads its own directory for user data. A private instance is located by `--home <dir>` or `HFK_HOME`, with the current directory as the default.

## Install

Install [uv](https://docs.astral.sh/uv/) first. Once the package is on PyPI, installing hfk is one line in a terminal:

```bash
uv tool install household-finance-kit
```

If you use pipx instead of uv, `pipx install household-finance-kit` does the same. Either command puts `hfk` on your `PATH` and keeps it apart from other Python programs.

The package is not on PyPI yet: publication waits on `M0-08`. Until then, install it straight from this repository. You do not need git or Python; uv downloads Python if it needs to:

```bash
uv tool install https://github.com/parkercombes/household-finance-kit/archive/refs/heads/master.zip
```

Check the install with `hfk --version`. If the terminal says `hfk` is not found, run `uv tool update-shell`, then open a new terminal window.

## Getting Started

This is the draft path for a household that does not program; the usability session (`M5-14`) tests it. Each step is one command typed in a terminal (Terminal on a Mac, PowerShell on Windows). A double-click installer is planned (`M5-22`, `M5-23`) so that no terminal is needed. Steps 3 and 4 can already be done in the browser instead: double-click `Open HFK.command` (Mac) or `Open HFK.bat` (Windows) in the `HFK` folder, choose the workbook download, and answer the same questions there.

1. Install hfk as shown in [Install](#install).
2. Make your hfk folder:

   ```bash
   hfk setup
   ```

   This makes a folder named `HFK` in your home folder, with an empty `data` folder inside it, and prints where the folder is. On a Mac it also opens the `data` folder in Finder. The commands below write the folder as `~/HFK`. On Windows, type the path `hfk setup` printed instead, such as `C:\Users\<you>\HFK`.
3. Put a workbook in `data`. To try hfk first with a sample workbook of made-up data:

   ```bash
   hfk dev fixture --out ~/HFK/data/Tiller-Example.xlsx
   ```

   To use your own data, download your Tiller workbook into `~/HFK/data`. In Google Sheets, use File > Download > Microsoft Excel (.xlsx). In Excel, copy the workbook file. hfk looks for a file whose name starts with `Tiller` or contains `Tiller Spreadsheet`, which Tiller's downloads do. If you rename the file, keep `Tiller` at the start of its name.
4. Answer the setup questions about the people, accounts and categories in the workbook:

   ```bash
   hfk init ~/HFK
   ```

   Type the people's first names separated by commas, like `Alex, Sam`. For a question with numbered choices, type the number. For an account two people share unevenly, type each person's share in percent, like `Alex 60, Sam 40`. Pressing Enter takes the answer shown after "Press Enter for:" ([ADR-0023](docs/DECISIONS.md#adr-0023-plain-word-answers-in-the-hfk-init-interview)). If an answer does not work, or a question with no Enter answer gets an empty answer, the interview says what was wrong and asks that question again; your earlier answers are kept. The sample's `HFK Plan` sheet puts two categories, Utilities and Dining, in a different bucket from the rest of their group; the interview asks whether to keep each one there.
5. Check that everything is ready:

   ```bash
   hfk doctor --home ~/HFK
   ```

   It prints a readiness section and ends with a count of errors and warnings. With the sample workbook, the last line is `doctor: 0 errors, 1 warning`: the warning says the latest transaction is old, because the sample's made-up transactions stop in September 2026. Each problem it finds names the file or sheet row to fix.
6. Open your reports: double-click `Open HFK.command` (Mac) or `Open HFK.bat` (Windows) in the `HFK` folder. Your browser opens the scorecard. Keep the window that opens with it while you read; close it to stop. To see them again later, double-click the same file; on Windows, `Open HFK` is also in the Start menu.

Each month, download the workbook into `data` again the same way. hfk reads the newest one.

## Quickstart

These commands set up a development checkout and run the checks. They are for contributors; to use hfk, see [Getting Started](#getting-started).

```bash
git clone https://github.com/parkercombes/household-finance-kit
cd household-finance-kit
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
hfk --version
python -m pytest -q
python scripts/privacy_scan.py --root .
```

## Still To Come

These wait on the maintainer; see [ROADMAP](docs/ROADMAP.md):

- A usability session with a non-programmer on a clean machine (`M5-14`), then a non-programmer README rewrite (`M5-15`).
- Publishing the package to PyPI, so `uv tool install household-finance-kit` works (`M0-08`).
- A decision on modelling the deductions for people 65 and older in `hfk retirement` (proposed ADR-0020).
- Planned (`M5-22`, `M5-23`, ADR-0022): a double-click installer and a quickstart built on it, so a household never needs the terminal; the default `HFK` folder (`M5-20`) and the setup page (`M5-21`) are done. Code-signing the installers is `M5-24`, which waits on the maintainer.

## Milestones

See [ROADMAP](docs/ROADMAP.md) for item-level status and executable acceptance criteria.

| Milestone | Status | Summary |
|---|---:|---|
| M0 | In progress | Foundations: design brief, docs, skeleton, CI, privacy scan, Tiller guard hook, public repository; PyPI publication (`M0-08`) waits on the maintainer |
| M1 | Done | Reader, Ledger types, synthetic workbook fixture |
| M2 | Done | Config loading, validation, and `hfk doctor` with orphan, stale-data, and closed-account checks |
| M3 | Done | Ownership shares, bucket mapping, monthly scorecard, doctor conflict checks, and the `M3-07` parity check against a private instance |
| M4 | Done | Category targets, balances, net worth, renewals, rebaseline, plan check |
| M5 | In progress | Instance interview, plan-in-workbook tab, renderers, local front door and launcher, one-line install, non-programmer docs; `M5-14` and `M5-15` wait on the maintainer |
| M6 | Done | Extension API: entry-point discovery, contract, config files, doctor hooks |
| M7 | Done | `settle_up` extension for exactly two people |
| M8 | Done | `retirement` extension, R1 through R6, with the 2026 federal tax table |
| M9 | Done | Google Sheets: households download the workbook; no adapter or Google sign-in (ADR-0019) |
| M10 | Done | Community extensions: FSA tracking, pension add-ons, home purchase modelling |

## What It Does

Core `hfk` analysis reads the Tiller `Transactions`, `Categories`, and `Balance History` sheets by header name, normalizes them into a Ledger, validates household configuration, and produces budgeting views: monthly scorecards, category targets, balances and net worth, renewals with sinking-fund adequacy, rebaseline proposals, and doctor checks for stale or unmapped data.

Two extensions are built in, and a household turns each on in `household.yaml`. The first is `settle_up`. It is limited to exactly two people and computes monthly paid-vs-owed totals, shared on-ledger transactions, off-ledger shared items, and a net transfer. It never settles an unfinished month and never writes back to Tiller.

The second is `retirement`. It models income-vs-need mechanics from declared people, income streams, expenses, inflation assumptions, and versioned tax data. It is arithmetic, not advice: no product recommendations, no optimization strategy, and no claim that a scenario is the right financial decision.

## Documentation Map

- [README](README.md): overview, status, quickstart, and safety summary.
- [AGENTS](AGENTS.md): LLM entry point and development rules.
- [CLAUDE](CLAUDE.md): Claude Code pointer.
- [CONTRIBUTING](CONTRIBUTING.md): development and PR process.
- [CHANGELOG](CHANGELOG.md): release history.
- [LICENSE](LICENSE): MIT license.
- [DESIGN-BRIEF](docs/DESIGN-BRIEF.md): approved source of truth.
- [ARCHITECTURE](docs/ARCHITECTURE.md): system layers and boundaries.
- [ROADMAP](docs/ROADMAP.md): milestones and acceptance criteria.
- [DECISIONS](docs/DECISIONS.md): architecture decision records.
- [EXTENSIONS](docs/EXTENSIONS.md): extension API and the built-in `settle_up` and `retirement` extensions.
- [TILLER-SCHEMA](docs/TILLER-SCHEMA.md): Tiller sheets and headers.
- [PRIVACY](docs/PRIVACY.md): public-repo privacy model.
- [WORKING-WITH-AI](docs/WORKING-WITH-AI.md): using `hfk` with or without an AI assistant, and keeping your data private.

## Safety And Privacy
This is a public repo, so it must contain no real financial data, no personal names, no account numbers, no addresses, no emails, no employer names, and no private balances. Examples use fictional names Alex and Sam, `Example Bank`, and round numbers. The privacy scan is part of the M0 safety system and should be run before sharing changes:

```bash
python scripts/privacy_scan.py --root .
```

See [PRIVACY](docs/PRIVACY.md) for the full privacy model.

## License

MIT. See [LICENSE](LICENSE).
