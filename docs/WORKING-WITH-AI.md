# Working With AI

Last verified: 2026-11-13

This guide explains how to use `hfk` with or without an AI assistant, and how to keep your financial data private when you do use one. It is written for the household that uses `hfk`, not for toolkit developers. Developers should read [AGENTS.md](../AGENTS.md) instead.

`hfk` never needs an AI assistant. Everything it does works without one.

## Choose how you work

There are three ways to work with `hfk`. Pick the one that fits you. You can change at any time.

| Tier | Who it is for | What you do |
|---|---|---|
| 1. Use it as-is | Anyone who uses a spreadsheet | Install `hfk`, run `hfk init`, then double-click the launcher in your folder. No AI is involved. |
| 2. Ask an AI for tweaks | Anyone who wants help changing their setup | Open your instance folder in an AI assistant and ask for a change with one of the prompts in [Prompts you can copy](#prompts-you-can-copy). You review every change before you keep it. |
| 3. Develop the toolkit | Programmers | Clone this repository and follow [AGENTS.md](../AGENTS.md) and [CONTRIBUTING.md](../CONTRIBUTING.md). |

### Tier 1: use it as-is

1. Install `hfk` with the one line in the [README](../README.md#install).
2. Put your Tiller workbook download in a new folder's `data/` folder.
3. Run `hfk init <folder>` and answer its questions.
4. Double-click `Open HFK.command` (Mac, Linux) or `Open HFK.bat` (Windows) in that folder to read your reports.

### Tier 2: ask an AI for tweaks

Your instance folder holds an `AGENTS.md` file, written by `hfk init`. An AI assistant that you open in that folder reads it first. It tells the assistant the privacy rule below, which files it may change, and how to check its work. Claude Code also reads the folder's `CLAUDE.md`, which points to `AGENTS.md`.

Ask for one change at a time. Then follow [Review every AI-made change](#review-every-ai-made-change).

### Tier 3: develop the toolkit

Toolkit work happens in the public repository, which holds no real data. Never open a private instance and the toolkit in the same AI session: the assistant could copy your data into a public file.

## The privacy rule

An AI assistant may read your configuration and the `hfk` code. It must never read your workbook or your statements.

| The assistant may read | The assistant must never read |
|---|---|
| `household.yaml`, `declarations.yaml`, and `plan.yaml` until it is removed | Anything in `data/`: your Tiller workbook and any downloads |
| `README.md`, `AGENTS.md`, and the `shared-items/README.md` note | Bank, card, pay, or tax statements, in any folder |
| Output of `hfk doctor` and `hfk plan check` that you choose to share | Reports in `out/`, which contain your amounts |
| The `hfk` source code | Any file that holds account numbers, balances, or transactions |

Your configuration files hold names, account names, and judgement calls, but no balances or transactions. Your workbook and reports hold every transaction you have. That is why the line is drawn here.

The `.claude/` folder in your instance holds a guard that stops Claude Code from saving, moving, or deleting your Tiller workbook. The guard blocks writes only. It does not stop an assistant from reading the workbook. The read rule depends on the assistant following `AGENTS.md`, and on you not asking it to break the rule.

## What to paste into a chat

When you ask an AI for help in a chat window, paste only what the question needs.

You may paste:

- An error line from `hfk doctor` or `hfk plan check`, after you replace any account name or amount you would not share.
- The part of `declarations.yaml` that the question is about.
- A made-up example, using names such as Alex and Sam and round numbers.

Never paste:

- Rows from your workbook, or a screenshot of it.
- Any report from `out/`, or a screenshot of the `hfk open` page.
- Account numbers, balances, statements, or tax documents.
- Your employer, address, or any detail that identifies a real person.

If you are not sure, leave it out. The assistant can ask for more.

## Prompts you can copy

Use these prompts in an AI assistant opened in your instance folder. Each one asks for a small change and for the check to run afterwards.

- "Read `AGENTS.md`. `hfk doctor` reports that the Tiller group `<group>` has no bucket. Add it to `groups` in `declarations.yaml` under the bucket `<bucket>`, then tell me what to run to check it."
- "Read `AGENTS.md`. Add a sharing rule to `declarations.yaml` so that `<description>` charges on `<account>` are split 50/50 between Alex and Sam, with the reason `<reason>`. Then tell me what to run to check it."
- "Read `AGENTS.md`. Explain in plain words what this `hfk doctor` error means and which file and key I need to change: `<error line>`."
- "Read `AGENTS.md`. Explain what the `fixed` and `essential` settings on my buckets change in the reports. Do not change any file."

Replace each `<...>` with your own words. Do not paste amounts or account numbers into a prompt.

## Review every AI-made change

Treat an AI-made change like a change from a helpful stranger: probably right, always checked.

1. Ask the assistant to list every file it changed and to show each change.
2. Read each change. If you do not understand one, ask it to explain, or undo it.
3. Run `hfk plan check --home <folder>` and `hfk doctor --home <folder>`. Both must finish with no errors.
4. Open the reports with the launcher and compare one month you know well with what you expect.
5. If you keep the folder in git, commit the change with a message that says what changed and why.

A report number that looks believable is not proof that the change is right. When a number moves after an AI-made change, find out why before you trust it.
