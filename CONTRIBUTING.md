# Contributing

Last verified: 2026-10-08

Thanks for contributing to `household-finance-kit` (`hfk`). This repository is intended to become a public MIT-licensed toolkit, so the main contribution rule is simple: useful work is welcome, but private financial data is never welcome here.

## Development Setup

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
hfk --version
python -m pytest -q
python -m ruff check .
python scripts/privacy_scan.py --root .
```

M0 contains the foundation only: docs, skeleton package, CLI stubs, privacy scan, Tiller guard hook, CI, examples, presets, and tests. Analysis commands such as scorecard, balances, settle-up, and retirement are planned by milestone and should not be represented as working until their roadmap acceptance commands pass.

## Branch And PR Flow

Create a focused branch for one roadmap item or one small documentation correction. Keep the diff narrow. A good PR explains:

- The roadmap item or design issue it addresses.
- The commands run locally.
- Any docs updated because behavior changed.
- Any privacy-sensitive areas reviewed.

Do not commit generated private reports, Tiller workbooks, exported CSV files, PDFs, statements, local instance directories, or scratch files.

## Tests And Privacy Scan

Every PR should run:

```bash
python -m pytest -q
python -m ruff check .
python scripts/privacy_scan.py --root .
```

Tests must use synthetic fixtures only. No PR may contain real financial data, real personal names, account numbers, addresses, emails, employer names, insurance or financial product brands, or private balances. Documentation and examples should use only Alex, Sam, `Example Bank`, and round example numbers.

## Documentation Requirements

Update docs in the same PR when behavior, commands, file formats, or milestones change. Maintained docs should include a `Last verified: YYYY-MM-DD` line near the top, except [CLAUDE](CLAUDE.md) and [CHANGELOG](CHANGELOG.md). Add a [CHANGELOG](CHANGELOG.md) entry under `[Unreleased]` for user-visible changes.

Design changes need an ADR in [DECISIONS](docs/DECISIONS.md). If a change contradicts [DESIGN-BRIEF](docs/DESIGN-BRIEF.md), update the brief deliberately and record why.

## Proposing An Extension

Extensions should follow [EXTENSIONS](docs/EXTENSIONS.md). Start by describing the household problem, required config section, ledger fields needed, CLI command shape, doctor checks, and privacy risks. Core should define extension hooks, but it must not import extension implementation details.

The first planned extensions are `settle_up` for exactly two people and `retirement` for income-vs-need mechanics. New extensions should preserve the same boundary: mechanics are allowed, financial advice is not.

## Code Style

Use `ruff` for linting and formatting checks. Keep code layered according to [ARCHITECTURE](docs/ARCHITECTURE.md): source adapter, Ledger, Config, Engine, Extensions, Presentation. Read Tiller sheets by header name, store money with exact decimal handling, and fail loudly on ambiguous input.
