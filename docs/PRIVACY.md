# Privacy

Last verified: 2026-10-08

household-finance-kit ("hfk") is a public toolkit for building and checking household finance workflows without exposing any real household data. This document describes the privacy rules for the toolkit repository, private instance repositories, contributors, and LLM agents that help with the project.

## Principles

The public toolkit contains zero real data. It may contain source code, documentation, schema examples, synthetic fixtures, and fictional examples, but it must not contain any real transaction, account, statement, workbook, household member, employer, institution, balance, or plan data.

Every user's data lives in a private instance. A private instance is the place for a user's local configuration, exports, generated outputs, and working files. The public hfk repository should be safe to publish, clone, fork, index, and discuss without revealing anything about Alex, Sam, or any real household.

Examples in public documentation must be fictional and deliberately generic. Use names such as Alex and Sam, institutions such as Example Bank, and round-number values that cannot be mistaken for real records. When a realistic workflow needs sample data, use the synthetic fixture rather than copying from a private workbook or statement.

Privacy is not a single control. hfk relies on simple repo rules, automated scanning, local denylist terms, optional hooks, and careful contributor behavior. These controls are meant to catch mistakes early, before data reaches a public commit or a shared prompt.

## What must never be committed

- Tiller workbooks: `.xlsx`, `.xlsm`, and `.xls` files.
- CSV or TSV exports.
- PDFs and statements.
- Account numbers.
- Real names, employers, or balances.
- API keys and tokens.
- The user's `household.yaml`, `declarations.yaml`, or `plan.yaml` in the toolkit repo.

## Layers of defence

| Layer | Purpose |
| --- | --- |
| `.gitignore` patterns | Blocks common private artifacts such as workbooks, CSV/TSV files, PDFs, generated data directories, output directories, and local household configuration files from being added casually. |
| `scripts/privacy_scan.py` | Performs an automated content and filename scan so forbidden file types and sensitive-looking text are caught before review or release. |
| Local gitignored `.privacy-denylist` file | Lets each user list private names, employers, account tails, and other household-specific terms without putting those terms in the public repository. |
| Optional pre-commit hook | Runs privacy checks before a commit is created, giving contributors a fast local guardrail. |
| CI workflow | Runs the privacy scan for shared changes so pull requests get a second check outside one developer's machine. |
| Tiller read-only hook `hooks/tiller_guard.py` | Helps keep Tiller workbook access read-only and reduces the chance that tooling accidentally mutates source financial files. |

## The privacy scan

The privacy scan is implemented by `scripts/privacy_scan.py`. Run it from the repository root before publishing changes:

```sh
python scripts/privacy_scan.py --root .
```

To scan only staged changes before committing, run:

```sh
python scripts/privacy_scan.py --staged
```

The scan checks for forbidden file types, including workbook, CSV, TSV, and PDF-style artifacts that do not belong in the public toolkit. It also checks for account-number patterns such as `xxxx` followed by four digits, long digit runs that look like account identifiers, and email addresses other than approved fictional or service-style addresses such as `example.com`, `example.org`, or `noreply` addresses.

The scan also reads every term listed one-per-line in `.privacy-denylist`. If any listed term appears in scanned content, the scan should fail. This allows Alex to block a private employer name, Sam to block an account tail, or a household to block a nickname without ever publishing those private terms.

The scanner is a defence layer, not permission to include risky material. Passing the scan does not make real data acceptable in the toolkit repository. If something came from a real household, statement, workbook, account, employer, or transaction history, keep it out of the public repo.

## Using the denylist

Put real names, employers, account tails, and other identifying household terms in `.privacy-denylist`, one term per line. Example entries might represent Alex's employer, Sam's account tail, or a private nickname used in exports. Use fictional examples in documentation, such as `Example Bank`, and keep real entries only in the local file.

The `.privacy-denylist` file itself is gitignored. Do not commit it, paste it into issues, or share it with support channels unless every term has been replaced with fictional values. Treat the denylist as sensitive because it may describe exactly what the project is trying to protect.

## Instance repos

Instance repositories should be private. They may contain a household's real configuration, local declarations, generated plan files, exports, or outputs, so they should not be public templates or public forks.

An instance repo should gitignore Tiller workbooks, spreadsheet exports, statements, generated output folders, temporary analysis files, local caches, secrets files, and any other artifact copied from a financial institution. Keep `household.yaml`, `declarations.yaml`, and `plan.yaml` private when they describe a real household.

Backups for instance repositories should follow the same privacy expectations. Use encrypted storage where practical, restrict access to the household or trusted operators, and avoid backup systems that make public links easy to create accidentally. If Example Bank statements are downloaded for local use, they should stay in private storage and outside the toolkit repository.

## If a leak is committed

Stop immediately. Do not just delete the file in a new commit. A later deletion does not remove the leaked content from repository history, forks, caches, pull request views, or local clones.

Rewrite history to remove the leaked data, then force-push the corrected history if the repository owner decides that is appropriate. Rotate any exposed secrets, API keys, tokens, or credentials. If statements, account numbers, real balances, real employer names, or household identities were pushed, treat that data as public.

Contact the hosting provider's support team and ask them to purge caches and remove any retained views of the sensitive content. Also check releases, artifacts, CI logs, issue comments, pull request comments, and any shared prompts or transcripts where the content may have been copied.

After the immediate cleanup, add any missed names, account tails, employers, or identifiers to `.privacy-denylist`, run the privacy scan again, and review why the existing controls did not catch the leak before it was committed.

## Guidance for LLM agents

LLM agents working on hfk must never paste real transactions into issues, pull requests, code review comments, prompts, logs, shared tools, or generated examples. Use the synthetic fixture when testing import, categorization, declaration, or planning behavior.

Use only fictional names Alex and Sam for people. Use fictional institutions such as Example Bank. Do not invent realistic account numbers, employer names, addresses, phone numbers, or transaction histories. If a workflow needs an account tail, use an obviously fake value already present in synthetic examples or a placeholder that the privacy scan allows.

Agents should keep the public toolkit and private instances mentally separate. The public toolkit can receive code, schemas, docs, tests, and synthetic fixtures. A private instance can contain household-specific configuration and financial artifacts. When in doubt, leave the real data out and describe the shape of the data with fictional values.

## Reporting a problem

Report privacy problems through the project's normal issue or security reporting channel, but do not include real financial data in the report. Describe the affected file path, command, or workflow using fictional values such as Alex, Sam, and Example Bank.

If the problem involves a possible leak, say that clearly and share the minimum safe reproduction steps. For example, report that a scanner missed a masked account-tail pattern in a synthetic fixture rather than pasting a real account tail. Maintainers should treat privacy reports as high priority because the project is intended to be safe for public use.
