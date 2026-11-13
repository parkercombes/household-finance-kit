# AGENTS.md

This folder is a private `hfk` instance: one household's budgeting setup. It
holds personal information. Read this file before you read or change
anything here.

## Never read the workbook

You may read the configuration files and the `hfk` code. You must never read
the Tiller workbook or any statement.

- Do not open, list the contents of, print, summarise, or copy any file in
  `data/`. That includes every `.xlsx`, `.xlsm`, `.csv`, `.tsv`, `.pdf`, and
  `.numbers` file, wherever it is.
- Do not read the reports in `out/`. They contain the household's amounts.
- Never write to, move, or delete the workbook. The guard in
  `.claude/hooks/tiller_guard.py` blocks writes, but it does not block
  reads: not reading the workbook is your job.
- If a task seems to need workbook data, stop and ask the person to run an
  `hfk` command and share only the lines you need.

## What you may change

- `household.yaml`: people, workbook file pattern, and account ownership.
- `declarations.yaml`: buckets, the group or category map, overrides,
  splits, and sharing rules. Every override, split, and sharing rule needs a
  `reason` written in the person's words.
- `plan.yaml`, while this instance still has one.

Do not change `.claude/`, `.gitignore`, or the launcher files
`Open HFK.command` and `Open HFK.bat`.

Make one change at a time, and never guess a value that changes a number.
If you do not know a bucket, a weight, or a date, ask.

## Check your work

After every change, run these and show the person the result:

    hfk plan check --home .
    hfk doctor --home .

Both must report no errors. Then list each file you changed and show each
change, so the person can review it before keeping it.

## What hfk does not do

`hfk` shows arithmetic about the household's own data. It does not give
financial advice. Do not recommend financial products, tax strategy, or
investments.

The person's guide to working with an AI assistant is
`docs/WORKING-WITH-AI.md` in the `hfk` repository.
