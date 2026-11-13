# My Household Finances

This folder is your private hfk instance. hfk reads your Tiller workbook and
the three YAML files here, and writes reports to `out/`. It never changes your
workbook.

## What each file and folder is

- `household.yaml` — who is in the household, and which accounts belong to
  whom.
- `declarations.yaml` — your judgement calls: which Tiller groups go into
  which buckets, and any exceptions you decide.
- `README.md` — this note.
- `Open HFK.command` (Mac, Linux) and `Open HFK.bat` (Windows) — double-click
  one to see your reports in your web browser. Close the window it opens to
  stop.
- `shared-items/` — for shared costs that are not in the workbook. Leave it
  empty until the settle-up report is released.
- `data/` — where your Tiller workbook export goes. hfk only reads it.
- `out/` — where generated reports land. After the `hfk init` interview it
  also holds `hfk-plan-starter.csv`, starter rows for your budget plan.
- `.gitignore` — keeps workbooks and reports out of git.
- `AGENTS.md` and `CLAUDE.md` — instructions for an AI assistant you open in
  this folder. The main rule: it may read your settings, but never your
  workbook or statements.
- `.claude/` — holds a small safety rule for AI coding assistants (Claude
  Code reads it) that stops them from changing the Tiller workbook. It does
  nothing if you never use an AI assistant, and it is safe to leave in place.

`data/` and `out/` are never committed: `.gitignore` blocks them along with
workbook, CSV, TSV, PDF, and Numbers files anywhere in this folder, and keeps
`.claude/settings.local.json` (Claude Code's per-machine settings) local.

## Your budget plan lives in the workbook

hfk reads your budget plan from a sheet named `HFK Plan` that you add to your
own Tiller workbook. Row 1 holds these headers: Description, Who, Bucket,
Monthly, Categories, Paced, Effective From, Effective Until, Annual Bill,
Annual Full, Account, Due Month, Due Day. Each later row is one person's
share of one budget item. hfk never writes the workbook, so after the
interview, paste or import `out/hfk-plan-starter.csv` into that sheet and
set your targets there.

## The YAML files may start as example data

If `hfk init` did not interview you from a workbook, the two YAML files
describe two fictional people, Alex and Sam. Replace their people, accounts,
and buckets with your own before trusting any report.

Then check your setup from a terminal:

    hfk plan check --home <this folder>
    hfk doctor --home <this folder>

`hfk plan check` prints `ok` and `hfk doctor` reports `0 errors` when your files are ready.

## Git is optional

This folder works without git. If you do keep it in git, the `.gitignore`
here keeps workbooks and reports out of every commit.
