"""Annual renewal schedule and sinking-fund adequacy, design brief section 7.

`hfk renewals --month YYYY-MM` reports the plan's annual obligations, the
month each is due next, and whether the monthly set-aside (the sinking fund)
will have accumulated each bill by the time it comes due. The report is
plan-only: it reads `plan.yaml` and `household.yaml` and never opens the
Tiller workbook.

Cycle rule: a line's fund cycles yearly at its due month. A contribution of
`monthly` is set aside every month including the due month, the bill is paid
in the due month from the full fund, and the cycle restarts the month after
the due month.

Adequacy:

- `elapsed` is how many months of the current cycle have passed at the report
  month `M` for due month `D`: `((M.month - D) mod 12)`, and 12 when `M` is
  the due month itself, so the due month shows the full fund.
- Contributions only exist for months the line was effective and that are on
  or after `history_start`, so `accrued_months` is the smaller of `elapsed`
  and the inclusive month count from the line's start to `M`.
- `projected` is what the fund holds when the bill comes due: `annual_bill`
  exactly when a full cycle of contributions remains (`accrued_months +
  months_to_due == 12`, which avoids a spurious cents gap from monthly
  rounding), else `money(monthly * (accrued_months + months_to_due))`.

Problems are flagged, never fixed: a missing due date, an undeclared account,
an owner share that disagrees with the account's ownership weights
(ADR-0003: weights are the default share), and a line that ends before its
next due month are reported as flags on the line itself. All money is
`Decimal` cents through `hfk.ledger.money`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from hfk.config import Household, Month, Plan, PlanLine
from hfk.ledger import money


@dataclass(frozen=True)
class RenewalsError(ValueError):
    """Raised when a renewals report cannot be built."""

    problem: str
    fix: str

    def __post_init__(self) -> None:
        ValueError.__init__(self, str(self))

    def __str__(self) -> str:
        return f"{self.problem}. Fix: {self.fix}"


@dataclass(frozen=True)
class Renewal:
    desc: str
    who: str
    bucket: str
    account: str | None
    annual_bill: Decimal
    annual_full: Decimal | None
    monthly: Decimal
    due: tuple[int, int] | None
    next_due: Month | None
    accrued_months: int | None
    accrued: Decimal | None
    months_to_due: int | None
    projected: Decimal | None
    shortfall: Decimal | None
    flags: tuple[str, ...]


@dataclass(frozen=True)
class ScheduleMonth:
    month: Month
    total: Decimal
    items: tuple[str, ...]


@dataclass(frozen=True)
class RenewalsReport:
    month: Month
    who: str | None
    renewals: tuple[Renewal, ...]
    schedule: tuple[ScheduleMonth, ...]
    set_aside_monthly: Decimal
    accrued_total: Decimal
    shortfall_total: Decimal
    short_count: int


def build_renewals(
    *, plan: Plan, household: Household, month: Month, who: str | None = None
) -> RenewalsReport:
    """Build the renewal schedule and sinking-fund adequacy for ``month``."""

    if month < plan.effective_from:
        raise RenewalsError(
            f"month {month} is before the plan effective_from {plan.effective_from}",
            "choose a month on or after plan.effective_from",
        )
    history_month = None
    if household.history_start is not None:
        history_month = Month(household.history_start.year, household.history_start.month)
        if month < history_month:
            raise RenewalsError(
                f"month {month} is before history_start {household.history_start.isoformat()}",
                "choose a month on or after history_start",
            )
    if who is not None and who not in household.slugs:
        raise RenewalsError(
            f"unknown person {who}",
            f"use one of {', '.join(household.slugs)}",
        )

    lines = tuple(line for line in plan.lines_for(month, who) if line.annual_bill is not None)
    renewals = tuple(_renewal(line, household, month, history_month) for line in lines)
    schedule = _schedule(renewals, month)

    set_aside_monthly = money(sum((line.monthly for line in lines), Decimal("0.00")))
    accrued_total = money(
        sum((renewal.accrued for renewal in renewals if renewal.accrued is not None), Decimal("0.00"))
    )
    shortfall_total = money(
        sum(
            (renewal.shortfall for renewal in renewals if renewal.shortfall is not None),
            Decimal("0.00"),
        )
    )
    short_count = sum(1 for renewal in renewals if renewal.shortfall is not None and renewal.shortfall > 0)
    return RenewalsReport(
        month=month,
        who=who,
        renewals=renewals,
        schedule=schedule,
        set_aside_monthly=set_aside_monthly,
        accrued_total=accrued_total,
        shortfall_total=shortfall_total,
        short_count=short_count,
    )


def _renewal(
    line: PlanLine, household: Household, month: Month, history_month: Month | None
) -> Renewal:
    flags: list[str] = []
    if line.due is None:
        flags.append("no due date")
    ownership = None if line.account is None else household.account(line.account)
    if line.account is not None and ownership is None:
        flags.append("account undeclared")
    if ownership is not None and line.annual_full is not None:
        expected = money(line.annual_full * ownership.weight(line.who))
        if expected != line.annual_bill:
            flags.append(f"share mismatch: expected {expected} from {line.account} weights")

    if line.due is None:
        return Renewal(
            desc=line.desc,
            who=line.who,
            bucket=line.bucket,
            account=line.account,
            annual_bill=line.annual_bill,
            annual_full=line.annual_full,
            monthly=line.monthly,
            due=None,
            next_due=None,
            accrued_months=None,
            accrued=None,
            months_to_due=None,
            projected=None,
            shortfall=None,
            flags=tuple(flags),
        )

    elapsed = (month.month - line.due[0]) % 12
    if elapsed == 0:
        elapsed = 12
    start = line.effective_from
    if history_month is not None and history_month > start:
        start = history_month
    months_effective = (month.year - start.year) * 12 + (month.month - start.month) + 1
    accrued_months = min(elapsed, months_effective)
    accrued = money(line.monthly * accrued_months)
    months_to_due = 12 - elapsed
    next_due = _add_months(month, months_to_due)
    if accrued_months + months_to_due == 12:
        projected = line.annual_bill
    else:
        projected = money(line.monthly * (accrued_months + months_to_due))
    shortfall = money(max(Decimal("0.00"), line.annual_bill - projected))
    if line.effective_until is not None and line.effective_until < next_due:
        flags.append("ends before next due")
    return Renewal(
        desc=line.desc,
        who=line.who,
        bucket=line.bucket,
        account=line.account,
        annual_bill=line.annual_bill,
        annual_full=line.annual_full,
        monthly=line.monthly,
        due=line.due,
        next_due=next_due,
        accrued_months=accrued_months,
        accrued=accrued,
        months_to_due=months_to_due,
        projected=projected,
        shortfall=shortfall,
        flags=tuple(flags),
    )


def _schedule(renewals: tuple[Renewal, ...], month: Month) -> tuple[ScheduleMonth, ...]:
    horizon = _add_months(month, 11)
    items: dict[Month, list[str]] = {}
    totals: dict[Month, Decimal] = {}
    for renewal in renewals:
        if renewal.next_due is None or not month <= renewal.next_due <= horizon:
            continue
        items.setdefault(renewal.next_due, []).append(f"{renewal.desc} ({renewal.who})")
        totals[renewal.next_due] = money(
            totals.get(renewal.next_due, Decimal("0.00")) + renewal.annual_bill
        )
    return tuple(
        ScheduleMonth(month=due_month, total=totals[due_month], items=tuple(items[due_month]))
        for due_month in sorted(items)
    )


def _add_months(month: Month, count: int) -> Month:
    index = month.year * 12 + month.month - 1 + count
    return Month(index // 12, index % 12 + 1)
