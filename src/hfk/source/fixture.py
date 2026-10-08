"""Synthetic workbook fixture generation for tests and demos."""

from __future__ import annotations

import datetime as dt
import random
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

TRANSACTION_HEADERS = [
    "Date",
    "Description",
    "Category",
    "Amount",
    "Account",
    "Account #",
    "Institution",
    "Month",
    "Week",
    "Transaction ID",
    "Account ID",
    "Check Number",
    "Full Description",
    "Date Added",
    "Category Hint",
    "Categorized Date",
]

CATEGORY_HEADERS = [
    "Category",
    "Group",
    "Type",
    "Hide From Reports",
]

BALANCE_HISTORY_HEADERS = [
    "Date",
    "Time",
    "Account",
    "Account #",
    "Account ID",
    "Balance ID",
    "Institution",
    "Balance",
    "Month",
    "Week",
    "Type",
    "Class",
    "Account Status",
    "Date Added",
]

ACCOUNTS_HEADERS = ["Account", "Institution", "Type", "Class", "Account Status"]

SHEET_HEADERS = {
    "Transactions": TRANSACTION_HEADERS,
    "Categories": CATEGORY_HEADERS,
    "Balance History": BALANCE_HISTORY_HEADERS,
    "Accounts": ACCOUNTS_HEADERS,
}

_CENTS = Decimal("0.01")
_INSTITUTION = "Example Bank"


def build_fixture(
    path: str | Path,
    *,
    months: int = 6,
    end_month: tuple[int, int] = (2026, 9),
    shuffle_headers: bool = False,
    drop_columns: Iterable[tuple[str, str]] = (),
    extra_columns: Iterable[tuple[str, str]] = (),
    balance_gap: bool = True,
) -> Path:
    """Create a deterministic synthetic Tiller-like workbook and return its path."""

    if months < 1:
        raise ValueError("months must be at least 1")

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)

    drop = set(drop_columns)
    extras_by_sheet = _extras_by_sheet(extra_columns)
    month_starts = _month_starts(months, end_month)

    workbook = Workbook()
    default_sheet = workbook.active
    workbook.remove(default_sheet)

    _write_sheet(
        workbook,
        "Transactions",
        _transaction_rows(month_starts),
        drop=drop,
        extras=extras_by_sheet.get("Transactions", ()),
        shuffle_headers=shuffle_headers,
    )
    _write_sheet(
        workbook,
        "Categories",
        _category_rows(),
        drop=drop,
        extras=extras_by_sheet.get("Categories", ()),
        shuffle_headers=shuffle_headers,
    )
    _write_sheet(
        workbook,
        "Balance History",
        _balance_rows(month_starts, balance_gap=balance_gap),
        drop=drop,
        extras=extras_by_sheet.get("Balance History", ()),
        shuffle_headers=shuffle_headers,
    )
    _write_sheet(
        workbook,
        "Accounts",
        _account_rows(),
        drop=drop,
        extras=extras_by_sheet.get("Accounts", ()),
        shuffle_headers=shuffle_headers,
    )

    workbook.save(output)
    return output


def _write_sheet(
    workbook: Workbook,
    sheet_name: str,
    rows: list[dict[str, object]],
    *,
    drop: set[tuple[str, str]],
    extras: tuple[str, ...],
    shuffle_headers: bool,
) -> None:
    headers = [
        header
        for header in [*SHEET_HEADERS[sheet_name], *extras]
        if (sheet_name, header) not in drop
    ]
    if shuffle_headers:
        seed = 20261008 + sum(ord(char) for char in sheet_name)
        random.Random(seed).shuffle(headers)

    sheet = workbook.create_sheet(sheet_name)
    sheet.append(headers)
    for row in rows:
        sheet.append([row.get(header, _extra_value(sheet_name, header)) for header in headers])

    if sheet_name == "Transactions":
        sheet.append([None for _header in headers])
        sheet.append([None for _header in headers])


def _transaction_rows(month_starts: list[dt.date]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    sequence = 1
    annual_month = month_starts[len(month_starts) // 2]

    for month_start in month_starts:
        transactions = [
            (2, "Alex Paycheck", "Alex Paycheck", Decimal("3200.00"), "Alex Checking"),
            (3, "Sam Paycheck", "Sam Paycheck", Decimal("2800.00"), "Sam Checking"),
            (4, "Rent Payment", "Rent", Decimal("-1500.00"), "Alex Checking"),
            (5, "Neighborhood Grocer", "Groceries", Decimal("-120.00"), "Joint Card"),
            (12, "Neighborhood Grocer", "Groceries", Decimal("-135.00"), "Joint Card"),
            (19, "Neighborhood Grocer", "Groceries", Decimal("-110.00"), "Joint Card"),
            (8, "Corner Cafe", "Dining", Decimal("-45.00"), "Joint Card"),
            (22, "Corner Cafe", "Dining", Decimal("-60.00"), "Joint Card"),
            (14, "City Utilities", "Utilities", Decimal("-210.00"), "Alex Checking"),
            (15, "Transfer to Savings", "Savings Transfer", Decimal("-400.00"), "Alex Checking"),
            (15, "Transfer from Checking", "Savings Transfer", Decimal("400.00"), "Savings"),
        ]
        if month_start == annual_month:
            transactions.append(
                (10, "Annual Membership", "Annual Membership", Decimal("-120.00"), "Joint Card")
            )

        for day, description, category, amount, account in transactions:
            tx_date = month_start.replace(day=day)
            account_id = _account_id(account)
            rows.append(
                {
                    "Date": tx_date,
                    "Description": description,
                    "Category": category,
                    "Amount": amount.quantize(_CENTS),
                    "Account": account,
                    "Account #": None,
                    "Institution": _INSTITUTION,
                    "Month": dt.date(tx_date.year, tx_date.month, 1),
                    "Week": _week_start(tx_date),
                    "Transaction ID": f"fx-{sequence:04d}",
                    "Account ID": account_id,
                    "Check Number": None,
                    "Full Description": f"{description} example transaction",
                    "Date Added": tx_date,
                    "Category Hint": category,
                    "Categorized Date": tx_date,
                }
            )
            sequence += 1

    return rows


def _category_rows() -> list[dict[str, object]]:
    categories = [
        ("Rent", "Housing", "Expense"),
        ("Utilities", "Housing", "Expense"),
        ("Groceries", "Food", "Expense"),
        ("Dining", "Food", "Expense"),
        ("Fuel", "Transportation", "Expense"),
        ("Transit", "Transportation", "Expense"),
        ("Alex Paycheck", "Income", "Income"),
        ("Sam Paycheck", "Income", "Income"),
        ("Savings Transfer", "Transfers", "Transfer"),
        ("Annual Membership", "Subscriptions", "Expense"),
    ]
    return [
        {
            "Category": category,
            "Group": group,
            "Type": category_type,
            "Hide From Reports": False,
        }
        for category, group, category_type in categories
    ]


def _balance_rows(month_starts: list[dt.date], *, balance_gap: bool) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    accounts = [
        ("Alex Checking", Decimal("2400.00"), "Checking", "Asset"),
        ("Sam Checking", Decimal("2100.00"), "Checking", "Asset"),
        ("Joint Card", Decimal("-600.00"), "Credit", "Liability"),
        ("Savings", Decimal("5000.00"), "Savings", "Asset"),
    ]
    gap_written = False
    sequence = 1

    for month_index, month_start in enumerate(month_starts):
        for account, base_balance, account_type, account_class in accounts:
            balance = base_balance + (Decimal(month_index) * Decimal("125.00"))
            if balance_gap and not gap_written and account == "Joint Card" and month_index == 1:
                balance_cell: Decimal | None = None
                gap_written = True
            else:
                balance_cell = balance.quantize(_CENTS)
            rows.append(
                {
                    "Date": month_start.replace(day=28),
                    "Time": dt.time(8, 0),
                    "Account": account,
                    "Account #": None,
                    "Account ID": _account_id(account),
                    "Balance ID": f"bal-{sequence:04d}",
                    "Institution": _INSTITUTION,
                    "Balance": balance_cell,
                    "Month": month_start,
                    "Week": _week_start(month_start.replace(day=28)),
                    "Type": account_type,
                    "Class": account_class,
                    "Account Status": "Open",
                    "Date Added": month_start.replace(day=28),
                }
            )
            sequence += 1

    return rows


def _account_rows() -> list[dict[str, object]]:
    return [
        {
            "Account": "Alex Checking",
            "Institution": _INSTITUTION,
            "Type": "Checking",
            "Class": "Asset",
            "Account Status": "Open",
        },
        {
            "Account": "Sam Checking",
            "Institution": _INSTITUTION,
            "Type": "Checking",
            "Class": "Asset",
            "Account Status": "Open",
        },
        {
            "Account": "Joint Card",
            "Institution": _INSTITUTION,
            "Type": "Credit",
            "Class": "Liability",
            "Account Status": "Open",
        },
        {
            "Account": "Savings",
            "Institution": _INSTITUTION,
            "Type": "Savings",
            "Class": "Asset",
            "Account Status": "Open",
        },
    ]


def _month_starts(months: int, end_month: tuple[int, int]) -> list[dt.date]:
    year, month = end_month
    if not 1 <= month <= 12:
        raise ValueError("end_month month must be between 1 and 12")
    starts = []
    cursor_year, cursor_month = year, month
    for _index in range(months):
        starts.append(dt.date(cursor_year, cursor_month, 1))
        cursor_month -= 1
        if cursor_month == 0:
            cursor_month = 12
            cursor_year -= 1
    return list(reversed(starts))


def _week_start(value: dt.date) -> dt.date:
    return value - dt.timedelta(days=value.weekday())


def _account_id(account: str) -> str:
    account_ids = {
        "Alex Checking": "acct-alex-checking",
        "Sam Checking": "acct-sam-checking",
        "Joint Card": "acct-joint-card",
        "Savings": "acct-savings",
    }
    return account_ids[account]


def _extras_by_sheet(extra_columns: Iterable[tuple[str, str]]) -> dict[str, tuple[str, ...]]:
    extras: dict[str, list[str]] = {}
    for sheet, header in extra_columns:
        extras.setdefault(sheet, []).append(header)
    return {sheet: tuple(headers) for sheet, headers in extras.items()}


def _extra_value(sheet_name: str, header: str) -> str:
    slug = sheet_name.lower().replace(" ", "-")
    return f"fixture-{slug}-{header.lower().replace(' ', '-')}"
