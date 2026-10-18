# My Household Finances

This folder is your private hfk instance. hfk reads your Tiller workbook and
the three YAML files here, and writes reports to `out/`. It never changes your
workbook.

## What each file and folder is

- `household.yaml` — who is in the household, and which accounts belong to
  whom.
- `declarations.yaml` — your judgement calls: which Tiller groups go into
  which buckets, and any exceptions you decide.
- `plan.yaml` — your monthly budget plan.
- `README.md` — this note.
- `shared-items/` — for shared costs that are not in the workbook. Leave it
  empty until the settle-up report is released.
- `data/` — where your Tiller workbook export goes. hfk only reads it.
- `out/` — where generated reports land.
- `.gitignore` — keeps workbooks and reports out of git.
- `.claude/` — holds a small safety rule for AI coding assistants (Claude
  Code reads it) that stops them from changing the Tiller workbook. It does
  nothing if you never use an AI assistant, and it is safe to leave in place.

`data/` and `out/` are never committed: `.gitignore` blocks them along with
workbook, CSV, TSV, PDF, and Numbers files anywhere in this folder, and keeps
`.claude/settings.local.json` (Claude Code's per-machine settings) local.

## The YAML files start as example data

The three YAML files describe two fictional people, Alex and Sam. Replace
their people, accounts, buckets, and amounts with your own before trusting
any report.

Then check your setup from a terminal:

    hfk plan check --home <this folder>
    hfk doctor --home <this folder>

`hfk plan check` prints `ok` and `hfk doctor` reports `0 errors` when your files are ready.

## Git is optional

This folder works without git. If you do keep it in git, the `.gitignore`
here keeps workbooks and reports out of every commit.
