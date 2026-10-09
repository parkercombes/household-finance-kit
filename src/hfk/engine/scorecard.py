"""Monthly scorecard calculations."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from hfk.config import Declarations, Household, Month, Plan
from hfk.engine.buckets import allocate, resolve_ledger
from hfk.engine.shares import share_transaction
from hfk.ledger import Ledger, money


@dataclass(frozen=True)
class ScorecardError(ValueError):
    """Raised when a scorecard cannot be built."""

    problem: str
    fix: str

    def __post_init__(self) -> None:
        ValueError.__init__(self, str(self))

    def __str__(self) -> str:
        return f"{self.problem}. Fix: {self.fix}"


@dataclass(frozen=True)
class BucketScore:
    bucket: str
    essential: bool
    fixed: bool
    planned: Decimal
    actual: Decimal
    variance: Decimal


@dataclass(frozen=True)
class Scorecard:
    month: Month
    who: str
    window_start: date
    window_end: date
    clamped: bool
    buckets: tuple[BucketScore, ...]
    planned_total: Decimal
    actual_total: Decimal
    plan_lines: int
    transactions: int


def build_scorecard(
    *,
    ledger: Ledger,
    household: Household,
    declarations: Declarations,
    plan: Plan,
    month: Month,
    who: str,
    today: date,
) -> Scorecard:
    """Build a closed-month actual-vs-plan scorecard for one household member."""

    slugs = household.slugs
    if who not in slugs:
        raise ScorecardError(
            f'unknown person slug "{who}"',
            f"choose one of: {', '.join(slugs)}",
        )

    month_start, month_end, next_month_start = _month_window(month)
    if next_month_start > today:
        raise ScorecardError(
            f"month {month} has not ended (today is {today.isoformat()})",
            "wait for the month to end; hfk never projects an unfinished month",
        )

    window_start = month_start
    clamped = False
    if household.history_start is not None:
        if household.history_start > month_end:
            raise ScorecardError(
                f"month {month} is before history_start {household.history_start.isoformat()}",
                "choose a month on or after history_start",
            )
        if month_start <= household.history_start <= month_end:
            window_start = household.history_start
            clamped = True

    resolutions = resolve_ledger(ledger, declarations)
    planned_by_bucket = {bucket.name: Decimal("0.00") for bucket in declarations.buckets}
    actual_by_bucket = {bucket.name: Decimal("0.00") for bucket in declarations.buckets}

    plan_lines = plan.lines_for(month, who)
    for line in plan_lines:
        planned_by_bucket[line.bucket] = money(planned_by_bucket[line.bucket] + line.monthly)

    transaction_count = 0
    for transaction in ledger.transactions:
        if not window_start <= transaction.date <= month_end:
            continue

        share = share_transaction(transaction, household, declarations).amount_for(who)
        resolution = resolutions[transaction.category]
        allocations = allocate(share, resolution)
        if not allocations:
            continue

        if share != Decimal("0.00"):
            transaction_count += 1
        for allocation in allocations:
            actual_by_bucket[allocation.bucket] = money(
                actual_by_bucket[allocation.bucket] + allocation.amount
            )

    bucket_scores: list[BucketScore] = []
    for bucket in declarations.buckets:
        planned = planned_by_bucket[bucket.name]
        actual = money(-actual_by_bucket[bucket.name])
        bucket_scores.append(
            BucketScore(
                bucket=bucket.name,
                essential=bucket.essential,
                fixed=bucket.fixed,
                planned=planned,
                actual=actual,
                variance=money(planned - actual),
            )
        )

    planned_total = money(sum((score.planned for score in bucket_scores), Decimal("0.00")))
    actual_total = money(sum((score.actual for score in bucket_scores), Decimal("0.00")))
    return Scorecard(
        month=month,
        who=who,
        window_start=window_start,
        window_end=month_end,
        clamped=clamped,
        buckets=tuple(bucket_scores),
        planned_total=planned_total,
        actual_total=actual_total,
        plan_lines=len(plan_lines),
        transactions=transaction_count,
    )


def _month_window(month: Month) -> tuple[date, date, date]:
    month_start = date(month.year, month.month, 1)
    if month.month == 12:
        next_month_start = date(month.year + 1, 1, 1)
    else:
        next_month_start = date(month.year, month.month + 1, 1)
    last_day = calendar.monthrange(month.year, month.month)[1]
    return month_start, month_start.replace(day=last_day), next_month_start
