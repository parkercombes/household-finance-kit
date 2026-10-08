# AGENTS.md

Last verified: 2026-10-08

This is the LLM entry point for `household-finance-kit` (`hfk`). Read it before changing code, docs, tests, examples, hooks, or workflows. The repository is public, the real user data belongs only in private instances, and the current implementation state is **M0 Foundations only**.

## Start Here

Read in this order when resuming cold:

1. [AGENTS.md](AGENTS.md) for rules, commands, and task flow.
2. [DESIGN-BRIEF](docs/DESIGN-BRIEF.md) for the approved source of truth.
3. [ARCHITECTURE](docs/ARCHITECTURE.md) for layer boundaries.
4. [ROADMAP](docs/ROADMAP.md), especially its "Start here when resuming" block.
5. [DECISIONS](docs/DECISIONS.md) for accepted design decisions and their consequences.

If any doc disagrees with [DESIGN-BRIEF](docs/DESIGN-BRIEF.md), fix the derived doc or deliberately update the brief and record the design change in [DECISIONS](docs/DECISIONS.md).

## Hard Rules

- Treat Tiller as read-only. Open workbooks with `read_only=True` and `data_only=True`; never call `save` on a Tiller workbook.
- Fail loudly. Missing required config, stale tax data, unmapped categories, conflicting constraints, and undeclared closed accounts are errors.
- Flag, do not auto-fix. Report the problem and the exact file, key path, or source row that needs attention.
- Use cents as canonical. Money uses exact decimal arithmetic with no float drift, and comparisons tolerate at most one cent where explicitly allowed.
- Never project unfinished months. Do not score, settle, or forecast a month that has not ended unless the design explicitly says the view is mid-month paced.
- No real data ever. Do not write real names, employers, balances, account numbers, emails, addresses, financial product brands, or private financial facts. Use only Alex, Sam, `Example Bank`, and round example numbers.
- Model mechanics, not advice. Retirement and planning output may show arithmetic and scenarios; it must not recommend products, tax strategy, claiming strategy, or investment decisions.
- Keep layers one-way. Source adapter feeds Ledger; Ledger feeds Config and Engine; Engine feeds Extensions and Presentation. Layers only import downward, and core never imports an extension.

## How To Run

Use real commands only. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python -m pytest -q
python -m ruff check .
python scripts/privacy_scan.py --root .
```

The CLI version command is also expected to work:

```bash
hfk --version
```

Current planned analysis subcommands are stubs until their milestone lands. Do not document a command as working unless it is implemented and covered by the roadmap acceptance command.

## How To Pick Up The Next Task

1. Open [ROADMAP](docs/ROADMAP.md).
2. Read the "Start here when resuming" block.
3. Take the first todo item whose dependencies are done.
4. Implement only the files needed for that item and respect repository privacy rules.
5. Run that item's acceptance command exactly as written.
6. Run `python -m pytest -q` and `python scripts/privacy_scan.py --root .`.
7. Flip the roadmap status only when the acceptance command passes.
8. Add a line to [CHANGELOG](CHANGELOG.md) under `[Unreleased]`.
9. Update any docs whose described behavior changed.

If a task reveals a design gap, stop and record the decision path in [DECISIONS](docs/DECISIONS.md) before coding around it.

## How To Update Docs

Every maintained doc except [CLAUDE](CLAUDE.md) and [CHANGELOG](CHANGELOG.md) carries a `Last verified: YYYY-MM-DD` line near the top. Update that line when you verify or materially change the document.

Use [DECISIONS](docs/DECISIONS.md) for any architecture or design change. An ADR should include context, decision, consequences, date, and status. Do not hide design changes only in prose or code comments.

Documentation must distinguish implemented behavior from planned behavior. If something belongs to a future milestone, label it as planned with the milestone, such as `planned (M3)`.

## Repository Map

Planned public toolkit layout:

```text
household-finance-kit/
  README.md
  AGENTS.md
  CLAUDE.md
  CONTRIBUTING.md
  LICENSE
  CHANGELOG.md
  pyproject.toml
  docs/
  src/hfk/
  examples/
  profiles/
  tests/
  scripts/
  hooks/
  .github/workflows/
```

The six design layers are:

| Layer | Package Area | Responsibility |
|---|---|---|
| Source adapter | `hfk.source` | Read Tiller by header name and produce a normalized Ledger |
| Ledger | `hfk.ledger` | Frozen dataclasses and helpers using `Decimal` amounts |
| Config | `hfk.config` | Load and validate `household.yaml`, `declarations.yaml`, and `plan.yaml` |
| Engine | `hfk.engine` | Pure budgeting, ownership, scorecard, balances, renewals, and doctor logic |
| Extensions | `hfk.ext` | Entry-point plugins such as `settle_up` and `retirement` |
| Presentation | `hfk.cli`, `hfk.render` | CLI and text, CSV, HTML output |

Private instances are separate from this repo and may contain `household.yaml`, `declarations.yaml`, `plan.yaml`, `shared-items/`, `retirement.yaml`, `extensions/`, `data/`, `out/`, `.claude/settings.json`, and a `.gitignore`. Never copy private instance data into the public toolkit.

## Things That Look Right But Are Wrong

- Silent defaults. A missing config value that changes a number must be a loud error, not a guessed default.
- Positional column reads. Tiller columns are read by header name, never by spreadsheet column position.
- Float money. Use exact decimal money handling; floats create plausible but wrong cents.
- Saving the Tiller workbook. `openpyxl` can strip charts and VBA on save, and this project is read-only by design.
- Copying private data into examples. Examples must use Alex, Sam, `Example Bank`, and round numbers only.
- Treating current-month results as final. Unfinished months can be paced where designed, but must not be settled or projected as complete.
- Letting extension assumptions leak into core. Core defines extension hooks; it must not import `settle_up`, `retirement`, or private add-ons.
