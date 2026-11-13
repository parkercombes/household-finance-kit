"""On-ledger shares for settle-up (M7-02; ADR-0009).

Settle-up declares no sharing rules of its own. Every amount a person owes for
a workbook transaction comes from the core share function,
``hfk.engine.share_transaction``: the account's weights from ``household.yaml``,
replaced by a matching ``sharing`` rule from ``declarations.yaml``. Spend is
the same spend the scorecard counts: categories that resolve to a bucket, with
Income, Transfer and ``non_spend_groups`` categories left out, inside the
month and on or after ``history_start``. So for any month, each person's total
here equals that person's scorecard total, to the cent.

Amounts are spend-positive: a ``-100.00`` purchase is ``100.00`` owed, and a
refund is negative.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from hfk.config import Declarations, Household, Month
from hfk.engine import resolve_ledger, share_transaction
from hfk.ledger import Ledger, money

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class OnLedgerLine:
    """One spend transaction and what each person owes for it."""

    date: date
    description: str
    account: str
    category: str
    amount: Decimal
    owed: tuple[tuple[str, Decimal], ...]

    def owed_by(self, slug: str) -> Decimal:
        for person, amount in self.owed:
            if person == slug:
                return amount
        return ZERO

    @property
    def shared(self) -> bool:
        """True when more than one person owes part of it."""

        return sum(1 for _person, amount in self.owed if amount != ZERO) > 1


def month_window(month: Month, history_start: date | None) -> tuple[date, date]:
    """The first and last day of ``month``, the first clamped to ``history_start``."""

    first = date(month.year, month.month, 1)
    last = first.replace(day=calendar.monthrange(month.year, month.month)[1])
    if history_start is not None and first < history_start <= last:
        first = history_start
    return first, last


def on_ledger_lines(
    *,
    ledger: Ledger,
    household: Household,
    declarations: Declarations,
    month: Month,
    people: tuple[str, ...],
) -> tuple[OnLedgerLine, ...]:
    """Every spend transaction in ``month`` with each person's owed share, in ledger order."""

    start, end = month_window(month, household.history_start)
    if household.history_start is not None and household.history_start > end:
        return ()
    resolutions = resolve_ledger(ledger, declarations)
    lines: list[OnLedgerLine] = []
    for transaction in ledger.transactions:
        if not start <= transaction.date <= end:
            continue
        if resolutions[transaction.category].excluded:
            continue
        shares = share_transaction(transaction, household, declarations)
        lines.append(
            OnLedgerLine(
                date=transaction.date,
                description=transaction.description,
                account=transaction.account,
                category=transaction.category,
                amount=money(-transaction.amount),
                owed=tuple((slug, money(-shares.amount_for(slug))) for slug in people),
            )
        )
    return tuple(lines)


def owed_totals(lines: tuple[OnLedgerLine, ...], people: tuple[str, ...]) -> dict[str, Decimal]:
    """Each person's total owed over ``lines``."""

    return {slug: money(sum((line.owed_by(slug) for line in lines), ZERO)) for slug in people}


__all__ = ["OnLedgerLine", "month_window", "on_ledger_lines", "owed_totals"]
