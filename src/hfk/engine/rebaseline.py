"""Rebaseline: propose per-category monthly targets from recent actual spend.

Design brief section 7, ``hfk rebaseline --who SLUG``. For one person, the
report looks at the person's share of actual spend in each spend category
over a window of closed months and proposes a monthly target per category
next to the current plan target, with a classification that says whether the
history is steady enough to trust. The command proposes only: it never edits
``plan.yaml``; changing the plan stays a human decision.

Classification rules, applied in this order:

- ``spiky`` when the category is nonzero in fewer than ``ceil(n / 2)`` of the
  ``n`` window months (absent more months than it is present): no target is
  proposed and the line is flagged ``spiky (<k> of <n> months)``.
- ``lumpy`` when the median is positive and the largest month is more than
  twice the median: the mean is proposed and the line is flagged
  ``lumpy (max <max> vs median <median>)``.
- ``stable`` otherwise: the mean is proposed with no classification flag.

Hard invariants: any analysis window is clamped to ``history_start`` (window
months earlier than the ``history_start`` month are dropped, transactions
dated before ``history_start`` are ignored, and a window left with fewer than
two months is a loud error, never a silently widened one); the window ends at
a closed month; all money is ``Decimal`` cents through ``hfk.ledger.money``,
exact decimal arithmetic end to end.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from hfk.config import Declarations, Household, Month, Plan, PlanLine
from hfk.engine.buckets import resolve_ledger
from hfk.engine.shares import share_transaction
from hfk.ledger import Ledger, money

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class RebaselineError(ValueError):
    """Raised when a rebaseline report cannot be built."""

    problem: str
    fix: str

    def __post_init__(self) -> None:
        ValueError.__init__(self, str(self))

    def __str__(self) -> str:
        return f"{self.problem}. Fix: {self.fix}"


@dataclass(frozen=True)
class CategoryBaseline:
    """One spend category's history series, summary values, and proposal."""

    category: str
    months: tuple[Decimal, ...]
    nonzero_months: int
    mean: Decimal
    median: Decimal
    max: Decimal
    current: Decimal | None
    proposed: Decimal | None
    classification: str
    flags: tuple[str, ...]


@dataclass(frozen=True)
class RebaselineReport:
    """One person's rebaseline proposal over a clamped window of closed months."""

    who: str
    window_start: Month
    window_end: Month
    months: int
    clamped: bool
    history_start: date | None
    lines: tuple[CategoryBaseline, ...]
    stable: int
    lumpy: int
    spiky: int


def build_rebaseline(
    *,
    ledger: Ledger,
    household: Household,
    declarations: Declarations,
    plan: Plan,
    who: str,
    through: Month,
    months: int = 6,
    today: date,
) -> RebaselineReport:
    """Build one person's rebaseline proposal for the window ending at ``through``."""

    slugs = household.slugs
    if who not in slugs:
        raise RebaselineError(
            f"unknown person {who}",
            f"use one of {', '.join(slugs)}",
        )

    if months < 2:
        raise RebaselineError(
            f"months must be at least 2, got {months}",
            "choose a window of 2 or more closed months",
        )

    last_day = calendar.monthrange(through.year, through.month)[1]
    if date(through.year, through.month, last_day) >= today:
        raise RebaselineError(
            f"month {through} is not closed yet",
            f"choose a month that ended before {today.isoformat()}",
        )

    window = tuple(_shift_month(through, -offset) for offset in range(months - 1, -1, -1))
    history_start = household.history_start
    kept = window
    clamped = False
    if history_start is not None:
        history_month = Month(history_start.year, history_start.month)
        kept = tuple(month for month in window if month >= history_month)
        clamped = len(kept) < len(window)
        if len(kept) < 2:
            raise RebaselineError(
                f"window {window[0]}..{window[-1]} has only {len(kept)} month(s) "
                f"on or after history_start {history_start.isoformat()}",
                "choose a later --through or move history_start",
            )

    n = len(kept)
    resolutions = resolve_ledger(ledger, declarations)
    spend = tuple(name for name, resolution in resolutions.items() if not resolution.excluded)
    spend_names = frozenset(spend)

    spend_by_month: dict[tuple[str, int], Decimal] = {}
    for month_index, window_month in enumerate(kept):
        for transaction in ledger.transactions_in_month(window_month.year, window_month.month):
            if history_start is not None and transaction.date < history_start:
                continue
            if transaction.category not in spend_names:
                continue
            share = share_transaction(transaction, household, declarations).amount_for(who)
            key = (transaction.category, month_index)
            spend_by_month[key] = spend_by_month.get(key, ZERO) - share

    plan_lines = plan.lines_for(through, who)

    lines: list[CategoryBaseline] = []
    counts = {"stable": 0, "lumpy": 0, "spiky": 0}
    for category in spend:
        series = tuple(
            money(spend_by_month.get((category, month_index), ZERO)) for month_index in range(n)
        )
        if all(value == ZERO for value in series):
            continue
        baseline = _category_baseline(category=category, series=series, plan_lines=plan_lines)
        lines.append(baseline)
        counts[baseline.classification] += 1

    return RebaselineReport(
        who=who,
        window_start=kept[0],
        window_end=through,
        months=n,
        clamped=clamped,
        history_start=history_start,
        lines=tuple(lines),
        stable=counts["stable"],
        lumpy=counts["lumpy"],
        spiky=counts["spiky"],
    )


def _category_baseline(
    *,
    category: str,
    series: tuple[Decimal, ...],
    plan_lines: tuple[PlanLine, ...],
) -> CategoryBaseline:
    n = len(series)
    nonzero = sum(1 for value in series if value != ZERO)
    mean = money(sum(series, ZERO) / n)
    ordered = sorted(series)
    if n % 2 == 1:
        median = ordered[n // 2]
    else:
        median = money((ordered[n // 2 - 1] + ordered[n // 2]) / 2)
    peak = max(series)

    flags: list[str] = []
    if nonzero < _ceil_half(n):
        classification = "spiky"
        proposed = None
        flags.append(f"spiky ({nonzero} of {n} months)")
    elif median > ZERO and peak > 2 * median:
        classification = "lumpy"
        proposed = mean
        flags.append(f"lumpy (max {peak:.2f} vs median {median:.2f})")
    else:
        classification = "stable"
        proposed = mean

    current = None
    line = next((candidate for candidate in plan_lines if category in candidate.categories), None)
    if line is None:
        flags.append("no plan line")
    else:
        if len(line.categories) == 1:
            current = line.monthly
        else:
            flags.append(f"shared line: {line.desc}")
        if line.annual_bill is not None:
            flags.append(f"annual line: {line.desc}")

    return CategoryBaseline(
        category=category,
        months=series,
        nonzero_months=nonzero,
        mean=mean,
        median=median,
        max=peak,
        current=current,
        proposed=proposed,
        classification=classification,
        flags=tuple(flags),
    )


def _shift_month(month: Month, offset: int) -> Month:
    total = month.year * 12 + (month.month - 1) + offset
    return Month(total // 12, total % 12 + 1)


def _ceil_half(n: int) -> int:
    return (n + 1) // 2
