"""Pure ledger data objects and Decimal money helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

CENT = Decimal("0.01")
CATEGORY_TYPES = frozenset({"Expense", "Income", "Transfer"})


def money(value: str | float | Decimal) -> Decimal:
    """Return ``value`` as cents using banker rounding."""
    try:
        if value is None:
            raise ValueError
        raw = value if isinstance(value, Decimal) else Decimal(str(value))
        if not raw.is_finite():
            raise ValueError
        return raw.quantize(CENT, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid money value {value!r}") from exc


@dataclass(frozen=True)
class Account:
    name: str
    account_id: str | None = None
    institution: str | None = None


@dataclass(frozen=True)
class Category:
    name: str
    group: str
    type: str
    hidden: bool = False

    def __post_init__(self) -> None:
        if self.type not in CATEGORY_TYPES:
            allowed = ", ".join(sorted(CATEGORY_TYPES))
            raise ValueError(f"Invalid category type {self.type!r}; allowed values: {allowed}")


@dataclass(frozen=True)
class Transaction:
    date: date
    description: str
    category: str
    amount: Decimal
    account: str
    transaction_id: str | None = None
    account_id: str | None = None
    institution: str | None = None
    full_description: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError("Transaction.amount must be Decimal")


@dataclass(frozen=True)
class BalanceRow:
    date: date
    account: str
    balance: Decimal | None
    account_id: str | None = None
    institution: str | None = None
    account_type: str | None = None
    account_class: str | None = None
    account_status: str | None = None

    def __post_init__(self) -> None:
        if self.balance is not None and not isinstance(self.balance, Decimal):
            raise TypeError("BalanceRow.balance must be Decimal or None")


@dataclass(frozen=True)
class Ledger:
    transactions: tuple[Transaction, ...]
    categories: tuple[Category, ...]
    balances: tuple[BalanceRow, ...]

    def months(self) -> list[tuple[int, int]]:
        return sorted({(transaction.date.year, transaction.date.month) for transaction in self.transactions})

    def transactions_in_month(self, year: int, month: int) -> tuple[Transaction, ...]:
        return tuple(
            transaction
            for transaction in self.transactions
            if transaction.date.year == year and transaction.date.month == month
        )

    def category(self, name: str) -> Category | None:
        for category in self.categories:
            if category.name == name:
                return category
        return None

    def category_type(self, name: str) -> str | None:
        category = self.category(name)
        if category is None:
            return None
        return category.type

    def account_names(self) -> list[str]:
        names = {transaction.account for transaction in self.transactions}
        names.update(balance.account for balance in self.balances)
        return sorted(names)

    def latest_balances(self) -> dict[str, BalanceRow]:
        latest: dict[str, BalanceRow] = {}
        for balance in self.balances:
            if balance.balance is None:
                continue
            existing = latest.get(balance.account)
            if existing is None or balance.date > existing.date:
                latest[balance.account] = balance
        return latest

    def balance_gaps(self) -> tuple[BalanceRow, ...]:
        return tuple(balance for balance in self.balances if balance.balance is None)

    @staticmethod
    def total(transactions: Iterable[Transaction]) -> Decimal:
        return sum((transaction.amount for transaction in transactions), Decimal("0.00"))
