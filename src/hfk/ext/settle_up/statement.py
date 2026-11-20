"""The monthly settle-up statement (M7-04, M7-05; design brief 8a; ADR-0017).

For one finished month and exactly two people:

- **Shared charges** are the month's spend transactions (``on_ledger_lines``,
  M7-02) that both people owe part of, or that one person owes and the other
  paid part of, such as a ``{sam: 1.0}`` sharing rule on a card Alex pays. Who
  *owes* comes from the core share function. Who *paid* is the account's single
  owner, or the payer weights that ``settle_up.yaml`` declares for a shared
  account (ADR-0017). A charge the same one person paid and owes is left out.
- **Shared items** from ``shared-items/YYYY-MM.yaml`` (M7-03) were paid by
  ``paid_by`` and are owed by their ``weights``.
- Each person's **net** is what they paid minus what they owe. The two nets are
  equal and opposite, and the **transfer** is the one payment that settles them.

A split between two people gives the first person the rounded cents and the
second the remainder, so every amount splits exactly. A month that has not
ended is refused before any number is worked out (M7-05).
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from hfk.config import Declarations, Household, Month
from hfk.ext.settle_up import SettleUpError, two_people
from hfk.ext.settle_up.config import CONFIG_FILE, SettleUpConfig
from hfk.ext.settle_up.items import SharedItems
from hfk.ext.settle_up.shares import month_window, on_ledger_lines
from hfk.ledger import Ledger, money

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class StatementLine:
    """One shared charge or shared item with what each person paid and owes."""

    source: str  # "workbook" or "shared item"
    date: date | None
    description: str
    account: str
    category: str
    amount: Decimal
    paid: tuple[Decimal, Decimal]
    owed: tuple[Decimal, Decimal]


@dataclass(frozen=True)
class Transfer:
    payer: str
    payee: str
    amount: Decimal


@dataclass(frozen=True)
class Statement:
    month: Month
    people: tuple[str, str]
    lines: tuple[StatementLine, ...]
    categories: tuple[tuple[str, Decimal], ...]
    total: Decimal
    paid: tuple[Decimal, Decimal]
    owed: tuple[Decimal, Decimal]
    net: tuple[Decimal, Decimal]
    transfer: Transfer | None
    items_file: str
    items_found: bool


def split(amount: Decimal, weights: tuple[tuple[str, Decimal], ...],
          people: tuple[str, str]) -> tuple[Decimal, Decimal]:
    """``amount`` split by ``weights``; the second person takes the rounding remainder."""

    weight = dict(weights)
    first = money(amount * weight.get(people[0], Decimal(0)))
    return first, money(amount - first)


def check_month_finished(month: Month, today: date) -> None:
    """M7-05: never settle a month that has not ended."""

    _start, end = month_window(month, None)
    if end >= today:
        raise SettleUpError(
            f"month {month} has not ended (today is {today.isoformat()})",
            "settle a month after it ends; hfk never settles an unfinished month",
        )


def build_statement(
    *,
    ledger: Ledger,
    household: Household,
    declarations: Declarations,
    config: SettleUpConfig,
    items: SharedItems,
    month: Month,
    today: date,
) -> Statement:
    people = two_people(household)
    check_month_finished(month, today)
    if household.history_start is not None and household.history_start > month_window(month, None)[1]:
        raise SettleUpError(
            f"month {month} is before history_start {household.history_start.isoformat()}",
            "choose a month on or after history_start",
        )

    lines: list[StatementLine] = []
    for line in on_ledger_lines(
        ledger=ledger, household=household, declarations=declarations, month=month,
        people=people,
    ):
        owed = (line.owed_by(people[0]), line.owed_by(people[1]))
        if not line.shared and owed == (ZERO, ZERO):
            continue
        account = household.account(line.account)
        if account is None:
            raise SettleUpError(
                f"account {line.account!r} is not declared in household.yaml",
                "declare it under accounts in household.yaml",
            )
        if account.owner is not None:
            payer = ((account.owner, Decimal(1)),)
        else:
            payer = config.payer_weights(line.account)
            if payer is None:
                raise SettleUpError(
                    f"no payer is declared for the shared account {line.account!r}, which has "
                    f"shared charges in {month}",
                    f'add "{line.account}": {{<slug>: <weight>, ...}} under payers in '
                    f"{CONFIG_FILE} (ADR-0017)",
                )
        paid = split(line.amount, payer, people)
        if not line.shared and paid == owed:
            continue  # one person paid it and owes all of it: nothing crosses
        lines.append(
            StatementLine(
                source="workbook",
                date=line.date,
                description=line.description,
                account=line.account,
                category=line.category,
                amount=line.amount,
                paid=paid,
                owed=owed,
            )
        )
    for item in items.items:
        lines.append(
            StatementLine(
                source="shared item",
                date=None,
                description=item.label,
                account="(not in the workbook)",
                category=f"{item.label} (shared item)",
                amount=item.amount,
                paid=split(item.amount, ((item.paid_by, Decimal(1)),), people),
                owed=split(item.amount, item.weights, people),
            )
        )

    categories: OrderedDict[str, Decimal] = OrderedDict()
    for line in lines:
        categories[line.category] = money(categories.get(line.category, ZERO) + line.amount)
    paid = tuple(money(sum((line.paid[i] for line in lines), ZERO)) for i in (0, 1))
    owed = tuple(money(sum((line.owed[i] for line in lines), ZERO)) for i in (0, 1))
    net = (money(paid[0] - owed[0]), money(paid[1] - owed[1]))
    if net[0] != -net[1]:  # pragma: no cover - every split is exact
        raise AssertionError(f"settle-up nets do not balance: {net}")
    transfer = None
    if net[0] > 0:
        transfer = Transfer(payer=people[1], payee=people[0], amount=net[0])
    elif net[0] < 0:
        transfer = Transfer(payer=people[0], payee=people[1], amount=-net[0])
    return Statement(
        month=month,
        people=people,
        lines=tuple(lines),
        categories=tuple(categories.items()),
        total=money(sum((line.amount for line in lines), ZERO)),
        paid=paid,  # type: ignore[arg-type]
        owed=owed,  # type: ignore[arg-type]
        net=net,
        transfer=transfer,
        items_file=f"shared-items/{month}.yaml",
        items_found=items.exists,
    )


__all__ = [
    "Statement",
    "StatementLine",
    "Transfer",
    "build_statement",
    "check_month_finished",
    "split",
]
