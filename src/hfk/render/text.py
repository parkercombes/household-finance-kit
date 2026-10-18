"""Pure text presentation for hfk report objects.

Renderers turn engine report dataclasses into terminal text and never open
workbooks, print, or touch standard streams; every function returns a ``str``
ending in exactly one newline.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from hfk.engine import (
    AccountBalance,
    BalancesReport,
    CategoriesReport,
    NetWorthLine,
    NetWorthReport,
    RenewalsReport,
    Scorecard,
)


def money(amount: object) -> str:
    """Format an amount with exactly two decimal places."""
    return f"{amount:.2f}"


def render_scorecard(scorecard: Scorecard) -> str:
    """Render a closed-month scorecard with per-bucket and total lines."""
    lines = [
        (
            f"scorecard {scorecard.month} for {scorecard.who} "
            "(closed month, shares per declarations)"
        )
    ]
    width = max((len(bucket.bucket) for bucket in scorecard.buckets), default=len("total"))
    for bucket in scorecard.buckets:
        lines.append(
            f"{bucket.bucket:<{width}}  plan {money(bucket.planned)}  "
            f"actual {money(bucket.actual)}  left {money(bucket.variance)}"
        )
    lines.append(
        f"total  plan {money(scorecard.planned_total)}  "
        f"actual {money(scorecard.actual_total)}  "
        f"left {money(scorecard.planned_total - scorecard.actual_total)}"
    )
    if scorecard.clamped:
        lines.append(f"note: window clamped to history_start {scorecard.window_start.isoformat()}")
    return "\n".join(lines) + "\n"


def render_categories(report: CategoriesReport) -> str:
    """Render per-category plan versus actual for one person and month."""
    if report.closed:
        header = (
            f"categories {report.month} for {report.who} "
            f"(closed month, {report.window_days} of {report.days_in_month} days)"
        )
    else:
        header = (
            f"categories {report.month} for {report.who} "
            f"(through {report.window_end.isoformat()}, "
            f"{report.window_days} of {report.days_in_month} days)"
        )
    lines = [header]
    if not report.lines:
        lines.append(f"no plan lines with categories for {report.who} in {report.month}")
        return "\n".join(lines) + "\n"
    width = max(len(line.desc) for line in report.lines)
    for line in report.lines:
        paced = "paced" if line.paced else "fixed"
        lines.append(
            f"{line.desc:<{width}}  {paced}  "
            f"target {money(line.target)}  actual {money(line.actual)}  "
            f"left {money(line.variance)}"
        )
    lines.append(
        f"total  target {money(report.target_total)}  actual {money(report.actual_total)}  "
        f"left {money(report.target_total - report.actual_total)}"
    )
    if report.clamped:
        lines.append(f"note: window clamped to history_start {report.window_start.isoformat()}")
    return "\n".join(lines) + "\n"


def _balance_class(row: AccountBalance) -> str:
    return "-" if row.account_class is None else row.account_class


def _balance_detail(row: AccountBalance) -> str:
    if not row.gap:
        detail = f"observed {row.observed.isoformat()}"
    else:
        detail = row.gap_reason or ""
        if row.observed is not None:
            if row.last_known is not None:
                detail += (
                    f"; last known {money(row.last_known)} on "
                    f"{row.last_known_date.isoformat()}"
                )
            else:
                detail += "; no earlier value"
    if row.closed is not None:
        detail += f"; closed {row.closed.isoformat()}"
    if not row.declared:
        detail += "; undeclared"
    return detail


def render_balances(report: BalancesReport, *, history_start: date | None) -> str:
    """Render per-account balances as of the report date."""
    lines = [f"balances as of {report.as_of.isoformat()}"]
    account_width = max((len(row.account) for row in report.accounts), default=0)
    class_width = max((len(_balance_class(row)) for row in report.accounts), default=1)
    for row in report.accounts:
        amount = "gap" if row.gap else money(row.balance)
        lines.append(
            f"{row.account:<{account_width}}  {_balance_class(row):<{class_width}}  "
            f"{amount}  {_balance_detail(row)}"
        )
    lines.append(f"accounts {len(report.accounts)}  gaps {report.gap_count}")
    if report.ignored_before_history_start:
        lines.append(
            f"note: ignored {report.ignored_before_history_start} observations "
            f"before history_start {history_start.isoformat()}"
        )
    return "\n".join(lines) + "\n"


def _networth_class(line: NetWorthLine) -> str:
    return "-" if line.account_class is None else line.account_class


def _networth_detail(line: NetWorthLine) -> str:
    if not line.gap:
        detail = f"observed {line.observed.isoformat()}"
    else:
        detail = line.gap_reason or ""
    for flag in line.flags:
        detail += f"; {flag}"
    if not line.counted:
        detail += "; excluded"
    return detail


def render_networth(report: NetWorthReport, *, history_start: date | None) -> str:
    """Render assets, liabilities, and net worth as of the report date."""
    lines = [f"net worth as of {report.as_of.isoformat()}"]
    account_width = max((len(line.account) for line in report.lines), default=0)
    class_width = max((len(_networth_class(line)) for line in report.lines), default=1)
    for line in report.lines:
        amount = "gap" if line.gap else money(line.balance)
        lines.append(
            f"{line.account:<{account_width}}  {_networth_class(line):<{class_width}}  "
            f"{amount}  {_networth_detail(line)}"
        )
    lines.append(f"assets {money(report.assets)}")
    lines.append(f"liabilities {money(report.liabilities)}")
    lines.append(f"net worth {money(report.net_worth)}")
    lines.append(f"counted {report.counted} of {len(report.lines)}  excluded {len(report.excluded)}")
    if report.incomplete:
        lines.append(f"warning: incomplete net worth; excluded: {', '.join(report.incomplete)}")
    if report.ignored_before_history_start:
        lines.append(
            f"note: ignored {report.ignored_before_history_start} observations "
            f"before history_start {history_start.isoformat()}"
        )
    return "\n".join(lines) + "\n"


def render_renewals(report: RenewalsReport) -> str:
    """Render annual renewals, their schedule, and sinking-fund adequacy."""
    header = f"renewals for {report.month}"
    if report.who is not None:
        header += f"  who {report.who}"
    lines = [header]
    desc_width = max((len(row.desc) for row in report.renewals), default=0)
    who_width = max((len(row.who) for row in report.renewals), default=0)
    for row in report.renewals:
        due_text = "-" if row.next_due is None else str(row.next_due)
        accrued_text = "-" if row.accrued is None else money(row.accrued)
        projected_text = "-" if row.projected is None else money(row.projected)
        if row.shortfall is None:
            status = "-"
        elif row.shortfall == 0:
            status = "ok"
        else:
            status = f"short {money(row.shortfall)}"
        line = (
            f"{row.desc:<{desc_width}}  {row.who:<{who_width}}  due {due_text}  "
            f"bill {money(row.annual_bill)}  monthly {money(row.monthly)}  "
            f"accrued {accrued_text}  projected {projected_text}  {status}"
        )
        for flag in row.flags:
            line += f"; {flag}"
        lines.append(line)
    if report.schedule:
        lines.append("schedule:")
        for entry in report.schedule:
            lines.append(f"  {entry.month}  {money(entry.total)}  {', '.join(entry.items)}")
    else:
        lines.append("schedule: nothing due in the next 12 months")
    lines.append(
        f"set-aside monthly {money(report.set_aside_monthly)}  "
        f"accrued {money(report.accrued_total)}  shortfall {money(report.shortfall_total)}"
    )
    if report.shortfall_total == 0:
        lines.append("adequacy ok")
    else:
        plural = "renewal" if report.short_count == 1 else "renewals"
        lines.append(
            f"adequacy short {money(report.shortfall_total)} across {report.short_count} {plural}"
        )
    return "\n".join(lines) + "\n"


TEXT_RENDERERS: dict[type, Callable[..., str]] = {
    Scorecard: render_scorecard,
    CategoriesReport: render_categories,
    BalancesReport: render_balances,
    NetWorthReport: render_networth,
    RenewalsReport: render_renewals,
}


def register_text_renderer(report_type: type, renderer: Callable[..., str]) -> None:
    """Register or replace the text renderer for a report type."""
    TEXT_RENDERERS[report_type] = renderer


def render_text(report: object, **options: object) -> str:
    """Render a report through its registered text renderer.

    Raises ``TypeError`` for report types without a registered renderer.
    """
    renderer = TEXT_RENDERERS.get(type(report))
    if renderer is None:
        for registered_type, candidate in TEXT_RENDERERS.items():
            if isinstance(report, registered_type):
                renderer = candidate
                break
    if renderer is None:
        registered = ", ".join(
            sorted(registered_type.__name__ for registered_type in TEXT_RENDERERS)
        )
        raise TypeError(f"no text renderer for {type(report).__name__}; registered: {registered}")
    return renderer(report, **options)


__all__ = [
    "TEXT_RENDERERS",
    "money",
    "register_text_renderer",
    "render_balances",
    "render_categories",
    "render_networth",
    "render_renewals",
    "render_scorecard",
    "render_text",
]
