"""Pure CSV presentation for hfk report objects.

Renderers turn engine report dataclasses into CSV tables and never open
workbooks, print, or touch standard streams; every function returns a ``str``
ending in exactly one newline. Rows mirror the engine's frozen row dataclasses
field for field: there are no presentation-only totals rows and no arithmetic
here, and ``Decimal`` values are formatted only at this output boundary
through ``money`` from :mod:`hfk.render.text`.
"""

from __future__ import annotations

import csv
import dataclasses
import io
from collections.abc import Callable, Iterable
from datetime import date
from decimal import Decimal

from hfk.config import Month
from hfk.engine import (
    BalancesReport,
    CategoriesReport,
    NetWorthReport,
    RenewalsReport,
    Scorecard,
)
from hfk.engine.balances import AccountBalance
from hfk.engine.categories import CategoryLine
from hfk.engine.networth import NetWorthLine
from hfk.engine.renewals import Renewal
from hfk.engine.scorecard import BucketScore
from hfk.render.text import money


def _cell(value: object) -> str:
    """Format one cell value at the output boundary."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return money(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Month):
        return str(value)
    if isinstance(value, tuple):
        if value and all(isinstance(part, int) for part in value):
            return "-".join(f"{part:02d}" for part in value)
        return "; ".join(str(part) for part in value)
    return str(value)


def _table(rows: Iterable[object], row_type: type) -> str:
    """Write one header row plus one row per dataclass instance as CSV."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    names = [field.name for field in dataclasses.fields(row_type)]
    writer.writerow(names)
    for item in rows:
        writer.writerow([_cell(getattr(item, name)) for name in names])
    return buffer.getvalue()


def render_scorecard_csv(scorecard: Scorecard) -> str:
    """Render the scorecard's per-bucket rows as one CSV table."""
    return _table(scorecard.buckets, BucketScore)


def render_categories_csv(report: CategoriesReport) -> str:
    """Render the categories report's plan lines as one CSV table."""
    return _table(report.lines, CategoryLine)


def render_balances_csv(report: BalancesReport) -> str:
    """Render the balances report's account rows as one CSV table."""
    return _table(report.accounts, AccountBalance)


def render_networth_csv(report: NetWorthReport) -> str:
    """Render the net worth report's account lines as one CSV table."""
    return _table(report.lines, NetWorthLine)


def render_renewals_csv(report: RenewalsReport) -> str:
    """Render the renewals report's renewal rows as one CSV table."""
    return _table(report.renewals, Renewal)


CSV_RENDERERS: dict[type, Callable[..., str]] = {
    Scorecard: render_scorecard_csv,
    CategoriesReport: render_categories_csv,
    BalancesReport: render_balances_csv,
    NetWorthReport: render_networth_csv,
    RenewalsReport: render_renewals_csv,
}


def register_csv_renderer(report_type: type, renderer: Callable[..., str]) -> None:
    """Register or replace the CSV renderer for a report type."""
    CSV_RENDERERS[report_type] = renderer


def render_csv(report: object, **options: object) -> str:
    """Render a report through its registered CSV renderer.

    Keyword ``options`` are accepted for call-shape parity with ``render_text``
    and are ignored: the renderer is called with the report alone, so
    ``render_csv(balances_report, history_start=...)`` works too.

    Raises ``TypeError`` for report types without a registered renderer.
    """
    renderer = CSV_RENDERERS.get(type(report))
    if renderer is None:
        for registered_type, candidate in CSV_RENDERERS.items():
            if isinstance(report, registered_type):
                renderer = candidate
                break
    if renderer is None:
        registered = ", ".join(
            sorted(registered_type.__name__ for registered_type in CSV_RENDERERS)
        )
        raise TypeError(f"no csv renderer for {type(report).__name__}; registered: {registered}")
    return renderer(report)


__all__ = [
    "CSV_RENDERERS",
    "register_csv_renderer",
    "render_balances_csv",
    "render_categories_csv",
    "render_csv",
    "render_networth_csv",
    "render_renewals_csv",
    "render_scorecard_csv",
]
