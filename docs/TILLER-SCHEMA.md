# Tiller Schema

Last verified: 2026-10-08

This document describes the workbook contract for `hfk`. It is derived from [DESIGN-BRIEF](DESIGN-BRIEF.md), especially section 5. The M1 source adapter reads a local `.xlsx` or `.xlsm` workbook into the normalized ledger model. Current CLI analysis commands remain planned until later milestones.

`hfk` is unofficial and not affiliated with Tiller. It reads a user's own workbook read-only and produces reports outside the workbook.

Header names were verified against a real Tiller workbook in October 2026. Tiller can change its template. If that happens, update this document by checking a current workbook, changing the header tables below, updating the synthetic fixture and reader tests, and recording the behavior change in the project docs.

## Workbook selection

The file reader can look in the private instance `data/` directory for a Tiller workbook. Workbooks may be named like `Tiller Finance v5.xlsm`, where the version number changes over time. Matching is case-insensitive. When more than one matching workbook exists, the highest numeric `vN` wins (`v10` is newer than `v2`). If candidates have the same version number, or no version number, the newest modified file wins. The workbook glob is configurable through `household.yaml` as `files.tiller_glob`, with the design example:

```yaml
files:
  tiller_glob: "Tiller*.xls*"
```

Temporary lock files beginning with `~$` are ignored. The reader accepts `.xlsx` and `.xlsm` files through `openpyxl` in read-only mode with `data_only=True`. It never saves the workbook.

## Sheets

`hfk` expects these sheets from a Tiller workbook:

| Sheet | Required by hfk | Purpose |
|---|---:|---|
| `Transactions` | Yes | Source rows for spending, income, transfers, categories, dates, and accounts. |
| `Categories` | Yes | Category names, groups, and Tiller category type. |
| `Balance History` | Yes | Account balance observations for balances and net worth. |
| `Accounts` | No | Optional Tiller sheet. Section 5 of the design brief does not define required `hfk` columns for this sheet. |

Extra sheets are tolerated. Extra columns are tolerated because Tiller may add columns over time. Missing required sheets and columns are loud errors.

The missing-column error shape is:

```text
Missing required Tiller column: sheet=<sheet>, column=<column>, fix=<how to add or restore the column>
```

The missing-sheet error shape is:

```text
Missing required Tiller sheet: sheet=<sheet>, fix=<how to restore the sheet>
```

Invalid category type, date, and amount errors name the sheet, row number, column, and bad value. The reader must stop rather than guessing from column position.

## `Transactions`

The source adapter reads by header name, never by column position.

| Header | Required by hfk | Notes |
|---|---:|---|
| `Date` | Yes | Transaction date. |
| `Description` | Yes | User-facing description used for reports and planned matching rules. |
| `Category` | Yes | Tiller category name. |
| `Amount` | Yes | Signed amount. Expenses are negative; income is positive. |
| `Account` | Yes | Account name as shown in Tiller. |
| `Account #` | No | Tiller workbook field. Not required by the approved M1 reader contract. |
| `Institution` | No | Optional metadata. |
| `Month` | No | Tiller workbook field; `hfk` should derive periods from dates when needed. |
| `Week` | No | Tiller workbook field. |
| `Transaction ID` | No | Optional stable source identifier when present. |
| `Account ID` | No | Optional stable account identifier when present. |
| `Check Number` | No | Tiller workbook field. |
| `Full Description` | No | Optional fuller source description. |
| `Date Added` | No | Tiller workbook field. |
| `Category Hint` | No | Tiller workbook field. |
| `Categorized Date` | No | Tiller workbook field. |

The reader maps optional `Transaction ID`, `Account ID`, `Institution`, and `Full Description` values to the ledger transaction when present. Amount sign follows Tiller convention: expenses are negative and income is positive. Transfers may appear in the workbook as signed rows, but their category type is handled through `Categories.Type`.

## `Categories`

| Header | Required by hfk | Notes |
|---|---:|---|
| `Category` | Yes | Category name used by transaction rows. |
| `Group` | Yes | Category group. Planned config can map buckets from Tiller group by default. |
| `Type` | Yes | Must be one of `Expense`, `Income`, or `Transfer`. |
| `Hide From Reports` | No | Truthy values map to `Category.hidden=True`. |
| Monthly columns | No | Tiller includes month columns after the core fields. They are tolerated but not part of the required `hfk` contract in the design brief. |

`Category Type` values are `Expense`, `Income`, and `Transfer`; in the workbook header this field is named `Type`. The reader treats other values as a validation error because bucket mapping and non-spend filtering depend on this distinction.

## `Balance History`

| Header | Required by hfk | Notes |
|---|---:|---|
| `Date` | Yes | Balance observation date. |
| `Time` | No | Tiller workbook field. |
| `Account` | Yes | Account name for the balance row. |
| `Account #` | No | Tiller workbook field. |
| `Account ID` | No | Optional stable account identifier when present. |
| `Balance ID` | No | Tiller workbook field. |
| `Institution` | No | Optional metadata. |
| `Balance` | Yes | Balance amount. Null amounts are reported as gaps, never treated as zero. |
| `Month` | No | Tiller workbook field. |
| `Week` | No | Tiller workbook field. |
| `Type` | No | Tiller account type metadata. |
| `Class` | No | Tiller account class metadata. |
| `Account Status` | No | Tiller account status metadata. |
| `Date Added` | No | Tiller workbook field. |

Balances support planned `hfk balances` and `hfk networth` reports in M4. Closed accounts are declared in private config; stale or undeclared account issues are planned `hfk doctor` errors.

The reader maps optional `Account ID`, `Institution`, `Type`, `Class`, and `Account Status` values to the ledger balance row when present. Empty `Balance` cells are represented as balance gaps (`None`), never as zero.

## `Accounts` optional sheet

Section 5 names `Accounts` as optional but does not define exact column headers for `hfk`. Therefore no `Accounts` columns are required by the approved M0 design. A future reader may use this sheet only after the design brief and this document are updated together.

| Header | Required by hfk | Notes |
|---|---:|---|
| Not specified in section 5 | No | Optional sheet; no approved column contract yet. |

## Dates and time zones

Dates are interpreted as workbook dates from the user's exported Tiller file. The reader accepts date and datetime cells and stores only the calendar date. Analysis windows use calendar months such as `YYYY-MM` and are clamped to `history_start` from `household.yaml` when that value is present. An unfinished month must not be settled and should be treated carefully by reports that could produce plausible but misleading partial results.

The private instance is the user's local context. `hfk` should not reinterpret workbook dates through an external service or remote timezone. If date cells contain both date and time data, the reader keeps the calendar date needed for month grouping.

## Exporting a workbook for `hfk`

Use a private instance directory. In general terms:

1. In Tiller, download or save a copy of the workbook as `.xlsx` or `.xlsm`.
2. Put the copy in the private instance `data/` directory.
3. Keep `data/` gitignored.
4. If multiple versions exist, keep the versioned filenames clear so the newest `vN` rule selects the intended file.
5. Use the reader through `hfk.source.load_ledger()` or later CLI commands as they land.

Do not place real workbooks in the public toolkit repo. Do not paste real account numbers, balances, addresses, employers, or personal names into examples or tests.

## Read-only behavior

The source adapter opens workbooks read-only with `openpyxl.load_workbook(path, read_only=True, data_only=True)`. It never calls `save`. Macros, charts, formatting, and workbook formulas are never touched because `hfk` reads data and writes reports outside the workbook.

This matters for `.xlsm` files: saving with a library can damage workbook features. `hfk` avoids that entire class of problems by treating Tiller as an input source only.

## Updating this document

When Tiller changes its template or a real workbook shows different headers:

1. Verify the current workbook headers from a private copy without committing that workbook.
2. Update the tables in this document.
3. Update the synthetic fixture.
4. Update reader validation tests so missing required columns fail with the documented error shape.
5. Keep backward-compatible optional columns optional when possible.
6. Record any intentional contract change in the project docs.

The rule is simple: tolerate new extra columns, fail loudly on missing required columns, and never infer meaning from spreadsheet column position.
