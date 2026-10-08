from __future__ import annotations

import datetime as dt
import importlib
import re
import sys
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from hfk.ledger import Account, BalanceRow, Category, Ledger, Transaction, money


def tx(day: int, amount: Decimal = Decimal("1.00"), category: str = "Groceries") -> Transaction:
    return Transaction(
        date=dt.date(2025, 1, day),
        description="Example purchase",
        category=category,
        amount=amount,
        account="Checking",
        institution="Example Bank",
    )


def test_money_quantizes_to_cents() -> None:
    assert money("12.345") == Decimal("12.34")
    assert money("12.355") == Decimal("12.36")


def test_money_uses_half_even_rounding() -> None:
    assert money("2.225") == Decimal("2.22")
    assert money("2.235") == Decimal("2.24")


def test_money_accepts_float_via_str() -> None:
    assert money(0.1) == Decimal("0.10")


@pytest.mark.parametrize("value", [None, "not numeric", "NaN", Decimal("NaN")])
def test_money_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValueError, match=re.escape(repr(value))):
        money(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "instance, field, value",
    [
        (Account(name="Checking"), "name", "Savings"),
        (Category(name="Groceries", group="Food", type="Expense"), "type", "Income"),
        (tx(1), "amount", Decimal("2.00")),
        (
            BalanceRow(date=dt.date(2025, 1, 1), account="Checking", balance=Decimal("10.00")),
            "balance",
            Decimal("11.00"),
        ),
        (Ledger(transactions=(), categories=(), balances=()), "transactions", (tx(1),)),
    ],
)
def test_dataclasses_are_frozen(instance: object, field: str, value: object) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(instance, field, value)


@pytest.mark.parametrize("amount", [1.0, 1, "1.00"])
def test_transaction_amount_must_already_be_decimal(amount: object) -> None:
    with pytest.raises(TypeError, match="Transaction.amount"):
        Transaction(
            date=dt.date(2025, 1, 1),
            description="Example purchase",
            category="Groceries",
            amount=amount,  # type: ignore[arg-type]
            account="Checking",
        )


@pytest.mark.parametrize("balance", [1.0, 1, "1.00"])
def test_balance_row_balance_must_be_decimal_or_none(balance: object) -> None:
    with pytest.raises(TypeError, match="BalanceRow.balance"):
        BalanceRow(date=dt.date(2025, 1, 1), account="Checking", balance=balance)  # type: ignore[arg-type]


def test_balance_row_allows_none_balance() -> None:
    row = BalanceRow(date=dt.date(2025, 1, 1), account="Checking", balance=None)

    assert row.balance is None


def test_category_rejects_unknown_type_and_names_allowed_values() -> None:
    with pytest.raises(ValueError) as error:
        Category(name="Groceries", group="Food", type="Spending")

    message = str(error.value)
    assert "Expense" in message
    assert "Income" in message
    assert "Transfer" in message


def test_ledger_months_are_sorted_unique_transaction_months() -> None:
    ledger = Ledger(
        transactions=(
            Transaction(dt.date(2025, 3, 1), "Example", "Groceries", Decimal("1.00"), "Checking"),
            Transaction(dt.date(2025, 1, 1), "Example", "Groceries", Decimal("1.00"), "Checking"),
            Transaction(dt.date(2025, 3, 2), "Example", "Groceries", Decimal("1.00"), "Checking"),
        ),
        categories=(),
        balances=(BalanceRow(dt.date(2024, 12, 31), "Checking", Decimal("10.00")),),
    )

    assert ledger.months() == [(2025, 1), (2025, 3)]


def test_transactions_in_month_returns_matching_tuple() -> None:
    january = tx(1)
    february = Transaction(dt.date(2025, 2, 1), "Example", "Groceries", Decimal("2.00"), "Checking")
    ledger = Ledger(transactions=(february, january), categories=(), balances=())

    assert ledger.transactions_in_month(2025, 1) == (january,)


def test_category_and_category_type_lookup() -> None:
    groceries = Category(name="Groceries", group="Food", type="Expense")
    ledger = Ledger(transactions=(), categories=(groceries,), balances=())

    assert ledger.category("Groceries") == groceries
    assert ledger.category_type("Groceries") == "Expense"
    assert ledger.category("Missing") is None
    assert ledger.category_type("Missing") is None


def test_account_names_include_transactions_and_balances_sorted_unique() -> None:
    ledger = Ledger(
        transactions=(tx(1), Transaction(dt.date(2025, 1, 2), "Example", "Income", Decimal("3.00"), "Savings")),
        categories=(),
        balances=(
            BalanceRow(dt.date(2025, 1, 1), "Checking", Decimal("10.00")),
            BalanceRow(dt.date(2025, 1, 1), "Credit Card", Decimal("-5.00")),
        ),
    )

    assert ledger.account_names() == ["Checking", "Credit Card", "Savings"]


def test_latest_balances_ignores_none_balances() -> None:
    old_checking = BalanceRow(dt.date(2025, 1, 1), "Checking", Decimal("10.00"))
    new_checking_gap = BalanceRow(dt.date(2025, 1, 2), "Checking", None)
    savings = BalanceRow(dt.date(2025, 1, 2), "Savings", Decimal("20.00"))
    ledger = Ledger(transactions=(), categories=(), balances=(old_checking, new_checking_gap, savings))

    assert ledger.latest_balances() == {"Checking": old_checking, "Savings": savings}


def test_balance_gaps_returns_rows_with_none_balance() -> None:
    gap = BalanceRow(dt.date(2025, 1, 2), "Checking", None)
    ledger = Ledger(
        transactions=(),
        categories=(),
        balances=(BalanceRow(dt.date(2025, 1, 1), "Checking", Decimal("10.00")), gap),
    )

    assert ledger.balance_gaps() == (gap,)


def test_total_sums_decimal_amounts_exactly() -> None:
    transactions = tuple(tx(day, Decimal("0.10")) for day in (1, 2, 3))

    assert Ledger.total(transactions) == Decimal("0.30")


def test_importing_ledger_imports_no_sibling_hfk_packages() -> None:
    for name in list(sys.modules):
        if name.startswith("hfk."):
            del sys.modules[name]

    importlib.import_module("hfk.ledger")

    loaded_siblings = {
        name
        for name in sys.modules
        if name.startswith("hfk.") and name.split(".")[1] not in {"ledger"}
    }
    assert loaded_siblings == set()
