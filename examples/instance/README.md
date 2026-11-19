# Example Instance

This directory is a complete private-instance shape using only the example files.
The `data/` directory is gitignored and absent.

## The example plan

The budget plan lives only in the workbook's `HFK Plan` sheet (ADR-0015), so this
directory holds no plan file. The synthetic fixture workbook carries the example plan
in its `HFK Plan` sheet; `hfk dev fixture` writes it by default. The same rows, as
they appear in the sheet:

| Description | Who | Bucket | Monthly | Categories | Paced | Effective From | Effective Until | Annual Bill | Annual Full | Account | Due Month | Due Day |
|---|---|---|---:|---|---|---|---|---:|---:|---|---:|---:|
| Example Rent | alex | Fixed Essential | 1200.00 | Rent | | 2025-01 | | | | | | |
| Example Utilities | alex | Variable Essential | 90.00 | Utilities | yes | 2025-01 | | | | | | |
| Example Utilities | sam | Variable Essential | 90.00 | Utilities | yes | 2025-01 | | | | | | |
| Example Grocer | alex | Variable Essential | 500.00 | Groceries | yes | 2025-01 | 2025-06 | | | | | |
| Example Grocer | alex | Variable Essential | 550.00 | Groceries | yes | 2025-07 | | | | | | |
| Example Transit | sam | Variable Essential | 80.00 | Transit | yes | 2025-01 | | | | | | |
| Example Streaming | alex | Fixed Discretionary | 20.00 | | | 2025-01 | | | | | | |
| Example Cloud Renewal | alex | Fixed Discretionary | 10.00 | Annual Membership | | 2025-01 | | 120.00 | 120.00 | Alex Checking | 7 | 1 |
| Example Cafe | sam | Variable Discretionary | 60.00 | Dining | yes | 2025-01 | | | | | | |

The Grocer rows show a dated amount change: end the old row with `Effective Until`
and add a new row, rather than editing the amount in place.

## Running doctor by hand

```bash
hfk dev fixture --out examples/instance/data/Tiller-Example.xlsx
hfk doctor --home examples/instance --today 2026-10-01
```

Delete `examples/instance/data/` afterwards. `scripts/privacy_scan.py` blocks workbook
files anywhere in the tree.

Automated acceptance is
`tests/test_doctor.py::test_example_instance_passes_doctor`, which does the same work in
a temporary directory, and `tests/test_plan_sheet.py` checks that this table matches the
fixture's `HFK Plan` sheet.
