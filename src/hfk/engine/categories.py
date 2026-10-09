"""Per-person category target report for plan lines that list categories.

Design brief section 7, `hfk categories --month YYYY-MM`. For one person, each
plan line effective in the month that lists `categories` is reported with its
target, actual spend, and what is left.

Target rule (paced vs fixed):

- A `paced` line's target is prorated to the analysis window:
  ``money(monthly * window_days / days_in_month)``. Mid-month, only paced
  targets shrink; a mid-month view is an explicitly paced view, never a
  projection of the finished month.
- A fixed (unpaced) line always gets the full ``monthly``, because a fixed
  obligation is due in whole regardless of how much of the month has elapsed.
- In a closed, unclamped month the window is the whole month, so paced and
  fixed targets both equal ``monthly``. In a closed month clamped by
  ``history_start``, paced targets are prorated to the window while fixed
  targets stay whole.

Actuals are the person's share of ledger transactions whose category matches a
kept line exactly (no bucket resolution is needed here because `hfk doctor`
already enforces bucket agreement), negated so expenses read positive and
refunds reduce actual. All money is `Decimal` cents through `hfk.ledger.money`.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from hfk.config import Declarations, Household, Month, Plan, PlanLine
from hfk.engine.shares import share_transaction
from hfk.ledger import Ledger, money


@dataclass(frozen=True)
class CategoriesError(ValueError):
    """Raised when a categories report cannot be built."""

    problem: str
    fix: str

    def __post_init__(self) -> None:
        ValueError.__init__(self, str(self))

    def __str__(self) -> str:
        return f"{self.problem}. Fix: {self.fix}"


@dataclass(frozen=True)
class CategoryLine:
    desc: str
    bucket: str
    categories: tuple[str, ...]
    paced: bool
    monthly: Decimal
    target: Decimal
    actual: Decimal
    variance: Decimal


@dataclass(frozen=True)
class CategoriesReport:
    month: Month
    who: str
    window_start: date
    window_end: date
    closed: bool
    window_days: int
    days_in_month: int
    clamped: bool
    lines: tuple[CategoryLine, ...]
    target_total: Decimal
    actual_total: Decimal


def build_categories(
    *,
    ledger: Ledger,
    household: Household,
    declarations: Declarations,
    plan: Plan,
    month: Month,
    who: str,
    today: date,
) -> CategoriesReport:
    """Build one person's category target report for ``month`` as of ``today``."""

    slugs = household.slugs
    if who not in slugs:
        raise CategoriesError(
            f'unknown person slug "{who}"',
            f"choose one of: {', '.join(slugs)}",
        )

    month_start, month_end = _month_window(month)
    if month_start > today:
        raise CategoriesError(
            f"month {month} has not started (today is {today.isoformat()})",
            "choose the current month or a past month",
        )

    closed = month_end < today
    window_end = month_end if closed else today

    window_start = month_start
    clamped = False
    if household.history_start is not None:
        if household.history_start > month_end:
            raise CategoriesError(
                f"month {month} is before history_start {household.history_start.isoformat()}",
                "choose a month on or after history_start",
            )
        if month_start <= household.history_start <= month_end:
            window_start = household.history_start
            clamped = True

    window_days = (window_end - window_start).days + 1
    days_in_month = calendar.monthrange(month.year, month.month)[1]

    kept = tuple(line for line in plan.lines_for(month, who) if line.categories)
    category_line = _reject_duplicate_categories(kept, who, month)

    spent_by_category: dict[str, Decimal] = {}
    for transaction in ledger.transactions:
        if not window_start <= transaction.date <= window_end:
            continue
        if transaction.category not in category_line:
            continue
        share = share_transaction(transaction, household, declarations).amount_for(who)
        spent_by_category[transaction.category] = money(
            spent_by_category.get(transaction.category, Decimal("0.00")) + share
        )

    lines: list[CategoryLine] = []
    for line in kept:
        if line.paced:
            target = money(line.monthly * window_days / days_in_month)
        else:
            target = line.monthly
        actual = money(
            -sum(
                (spent_by_category.get(category, Decimal("0.00")) for category in line.categories),
                Decimal("0.00"),
            )
        )
        lines.append(
            CategoryLine(
                desc=line.desc,
                bucket=line.bucket,
                categories=line.categories,
                paced=line.paced,
                monthly=line.monthly,
                target=target,
                actual=actual,
                variance=money(target - actual),
            )
        )

    target_total = money(sum((line.target for line in lines), Decimal("0.00")))
    actual_total = money(sum((line.actual for line in lines), Decimal("0.00")))
    return CategoriesReport(
        month=month,
        who=who,
        window_start=window_start,
        window_end=window_end,
        closed=closed,
        window_days=window_days,
        days_in_month=days_in_month,
        clamped=clamped,
        lines=tuple(lines),
        target_total=target_total,
        actual_total=actual_total,
    )


def _reject_duplicate_categories(
    kept: tuple[PlanLine, ...], who: str, month: Month
) -> dict[str, str]:
    seen: dict[str, str] = {}
    for line in kept:
        for category in line.categories:
            if category in seen:
                raise CategoriesError(
                    f'category "{category}" appears on plan lines '
                    f'"{seen[category]}" and "{line.desc}" for "{who}" in month {month}',
                    "end one line with effective_until or remove the category from one of them",
                )
            seen[category] = line.desc
    return seen


def _month_window(month: Month) -> tuple[date, date]:
    month_start = date(month.year, month.month, 1)
    last_day = calendar.monthrange(month.year, month.month)[1]
    return month_start, month_start.replace(day=last_day)
