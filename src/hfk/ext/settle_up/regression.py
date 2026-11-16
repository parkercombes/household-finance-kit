"""Compare a settle-up statement with a hand-built one (M7-06; design brief 8a).

A household moving from a hand-built settle-up tab writes what that tab said for
a finished month, then runs ``hfk settle YYYY-MM --compare FILE``::

    schema_version: 1
    month: 2026-08
    categories: {Groceries: 365.00, Dining: 105.00, Utilities: 210.00}
    paid: {alex: 680.00, sam: 0.00}
    owes: {alex: 340.00, sam: 340.00}
    transfer: {from: sam, to: alex, amount: 340.00}

``categories`` is optional; the rest is required. Every figure must match to
within one cent (the project's only allowed tolerance); each larger difference
is reported by key, with both values. Nothing is adjusted to make them agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from hfk.config import ConfigError, Month
from hfk.config._yaml import (
    load_mapping,
    reject_unknown_keys,
    require,
    require_mapping,
    require_schema_version,
)
from hfk.config.errors import key_path
from hfk.ext.settle_up.statement import Statement

TOLERANCE = Decimal("0.01")
TOP_LEVEL_KEYS = ("schema_version", "month", "categories", "paid", "owes", "transfer")


@dataclass(frozen=True)
class Difference:
    key: str
    expected: str
    actual: str

    def render(self) -> str:
        return f"{self.key}: expected {self.expected}, statement has {self.actual}"


def load_expected(path: Path) -> dict[str, Any]:
    data = load_mapping(path)
    reject_unknown_keys(data, TOP_LEVEL_KEYS, path)
    require_schema_version(data, path)
    month_text = str(require(data, "month", path))
    try:
        month = Month.parse(month_text)
    except ValueError:
        raise ConfigError(f"Invalid month {month_text!r}", file=path, key="month",
                          fix="write the month as YYYY-MM") from None
    expected: dict[str, Any] = {"month": month, "categories": None}
    if "categories" in data:
        expected["categories"] = _amounts(data["categories"], path, "categories")
    expected["paid"] = _amounts(require(data, "paid", path), path, "paid")
    expected["owes"] = _amounts(require(data, "owes", path), path, "owes")
    transfer = require_mapping(require(data, "transfer", path), path, "transfer")
    reject_unknown_keys(transfer, ("from", "to", "amount"), path, "transfer")
    amount = _amount(require(transfer, "amount", path, "transfer"), path, "transfer", "amount")
    expected["transfer"] = (
        None if amount == 0 else str(require(transfer, "from", path, "transfer")),
        None if amount == 0 else str(require(transfer, "to", path, "transfer")),
        amount,
    )
    return expected


def compare(statement: Statement, expected: dict[str, Any]) -> list[Difference]:
    """Every figure that differs from the hand-built statement by more than one cent."""

    differences: list[Difference] = []
    if expected["month"] != statement.month:
        differences.append(Difference("month", str(expected["month"]), str(statement.month)))

    def check(key: str, want: Decimal, have: Decimal) -> None:
        if abs(want - have) > TOLERANCE:
            differences.append(Difference(key, f"{want:.2f}", f"{have:.2f}"))

    if expected["categories"] is not None:
        actual = dict(statement.categories)
        for name in sorted(set(expected["categories"]) | set(actual)):
            check(key_path("categories", name), expected["categories"].get(name, Decimal(0)),
                  actual.get(name, Decimal(0)))
    for section, values in (("paid", statement.paid), ("owes", statement.owed)):
        for index, person in enumerate(statement.people):
            check(key_path(section, person), expected[section].get(person, Decimal(0)),
                  values[index])
    want_from, want_to, want_amount = expected["transfer"]
    have = statement.transfer
    have_amount = Decimal(0) if have is None else have.amount
    check("transfer.amount", want_amount, have_amount)
    if want_amount and have is not None and (want_from, want_to) != (have.payer, have.payee):
        differences.append(Difference("transfer.direction", f"{want_from} pays {want_to}",
                                      f"{have.payer} pays {have.payee}"))
    return differences


def _amounts(value: Any, path: Path, key: str) -> dict[str, Decimal]:
    rows = require_mapping(value, path, key)
    return {str(name): _amount(raw, path, key, str(name)) for name, raw in rows.items()}


def _amount(value: Any, path: Path, *parents: str) -> Decimal:
    try:
        amount = (Decimal(str(value)) if isinstance(value, (int, float, str))
                  and not isinstance(value, bool) else None)
    except InvalidOperation:
        amount = None
    if amount is None or not amount.is_finite():
        raise ConfigError(f"Invalid amount {value!r}", file=path, key=key_path(*parents),
                          fix="write the amount from your hand-built statement, such as 340.00")
    return amount


__all__ = ["TOLERANCE", "Difference", "compare", "load_expected"]
