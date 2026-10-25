"""Pure HTML presentation for hfk report objects.

Renderers turn engine report dataclasses into static, self-contained HTML
pages: one inline stylesheet, no scripts, no external assets, and no URLs, so
the same report renders to the same bytes forever and a browser opens the
page from disk with no network. Row cells reuse the CSV boundary formatter
:func:`hfk.render.csv._cell` so the two formats always agree, totals mirror
the text renderer's summary lines, and ``Decimal`` values are formatted only
at this output boundary through ``money``. Renderers never open workbooks,
print, or touch standard streams; every function returns a ``str`` ending in
exactly one newline.
"""

from __future__ import annotations

import dataclasses
import html
import typing
from collections.abc import Callable, Iterable
from datetime import date
from decimal import Decimal

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
from hfk.render.csv import _cell
from hfk.render.text import money

_STYLESHEET = """\
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  margin: 2rem;
  color: #222;
  line-height: 1.4;
}
h1 {
  font-size: 1.25rem;
  margin: 0 0 1rem;
}
h2 {
  font-size: 1.05rem;
  margin: 1.5rem 0 0.5rem;
}
table {
  border-collapse: collapse;
  margin-bottom: 1.5rem;
}
th, td {
  border: 1px solid #bbb;
  padding: 0.25rem 0.5rem;
  text-align: left;
}
th {
  background: #f0f0f0;
}
th.num, td.num {
  text-align: right;
}
dl.totals {
  display: grid;
  grid-template-columns: max-content max-content;
  gap: 0.25rem 1rem;
  margin: 0 0 1rem;
}
dl.totals dt {
  font-weight: bold;
}
dl.totals dd {
  margin: 0;
}
p.note {
  color: #666;
  margin: 0.25rem 0;
}
"""


def _escape(value: str) -> str:
    """Escape one piece of report-derived text for HTML and XML output."""
    return html.escape(value, quote=True)


def _resolve_decimal_fields(row_type: type) -> frozenset[str]:
    """Resolve the field names whose annotation is ``Decimal`` or ``Decimal | None``."""
    return frozenset(
        name
        for name, hint in typing.get_type_hints(row_type).items()
        if hint is Decimal or Decimal in typing.get_args(hint)
    )


_DECIMAL_FIELD_CACHE: dict[type, frozenset[str]] = {
    row_type: _resolve_decimal_fields(row_type)
    for row_type in (BucketScore, CategoryLine, AccountBalance, NetWorthLine, Renewal)
}


def _decimal_fields(row_type: type) -> frozenset[str]:
    """Return cached Decimal field names, resolving unknown row types on first use.

    ``typing.get_type_hints`` resolves a dataclass's string annotations through
    ``sys.modules``, so the five known row types are resolved eagerly at import
    time rather than at render time.
    """
    names = _DECIMAL_FIELD_CACHE.get(row_type)
    if names is None:
        names = _resolve_decimal_fields(row_type)
        _DECIMAL_FIELD_CACHE[row_type] = names
    return names


def _tag(kind: str, text: str, *, num: bool = False) -> str:
    """Render one escaped cell; numeric cells carry ``class="num"``."""
    cls = ' class="num"' if num else ""
    return f"<{kind}{cls}>{_escape(text)}</{kind}>"


def _table(rows: Iterable[object], row_type: type) -> str:
    """Render one header row plus one row per dataclass instance as an HTML table."""
    fields = dataclasses.fields(row_type)
    numeric = _decimal_fields(row_type)
    header = "".join(
        _tag("th", field.name.replace("_", " "), num=field.name in numeric)
        for field in fields
    )
    lines = [f"<table>\n<thead><tr>{header}</tr></thead>\n<tbody>"]
    for item in rows:
        cells = "".join(
            _tag("td", _cell(getattr(item, field.name)), num=field.name in numeric)
            for field in fields
        )
        lines.append(f"<tr>{cells}</tr>")
    lines.append("</tbody>\n</table>")
    return "\n".join(lines) + "\n"


def _totals(pairs: Iterable[tuple[str, str]]) -> str:
    """Render the totals list mirroring the text report's summary lines."""
    entries = "".join(f"{_tag('dt', label)}{_tag('dd', value)}" for label, value in pairs)
    return f'<dl class="totals">\n{entries}\n</dl>\n'


def _note(text: str) -> str:
    """Render one muted note paragraph with the text renderer's wording."""
    return f'<p class="note">{_escape(text)}</p>\n'


def _document(header: str, body: str) -> str:
    """Wrap a rendered body in the fixed static HTML5 skeleton."""
    title = _escape(header)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8" />\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        f"<title>{title}</title>\n"
        "<style>\n"
        f"{_STYLESHEET}"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        f"<h1>{title}</h1>\n"
        f"{body}"
        "</body>\n"
        "</html>\n"
    )


def render_scorecard_html(scorecard: Scorecard) -> str:
    """Render a closed-month scorecard as a static HTML page."""
    header = (
        f"scorecard {scorecard.month} for {scorecard.who} "
        "(closed month, shares per declarations)"
    )
    body = _table(scorecard.buckets, BucketScore)
    body += _totals(
        (
            ("total plan", money(scorecard.planned_total)),
            ("total actual", money(scorecard.actual_total)),
            ("total left", money(scorecard.planned_total - scorecard.actual_total)),
        )
    )
    if scorecard.clamped:
        body += _note(
            f"note: window clamped to history_start {scorecard.window_start.isoformat()}"
        )
    return _document(header, body)


def render_categories_html(report: CategoriesReport) -> str:
    """Render per-category plan versus actual as a static HTML page."""
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
    body = _table(report.lines, CategoryLine)
    if not report.lines:
        body += _note(f"no plan lines with categories for {report.who} in {report.month}")
    body += _totals(
        (
            ("total target", money(report.target_total)),
            ("total actual", money(report.actual_total)),
            ("total left", money(report.target_total - report.actual_total)),
        )
    )
    if report.clamped:
        body += _note(
            f"note: window clamped to history_start {report.window_start.isoformat()}"
        )
    return _document(header, body)


def render_balances_html(report: BalancesReport, *, history_start: date | None) -> str:
    """Render per-account balances as a static HTML page."""
    body = _table(report.accounts, AccountBalance)
    body += _totals(
        (
            ("accounts", str(len(report.accounts))),
            ("gaps", str(report.gap_count)),
        )
    )
    if report.ignored_before_history_start:
        body += _note(
            f"note: ignored {report.ignored_before_history_start} observations "
            f"before history_start {history_start.isoformat()}"
        )
    return _document(f"balances as of {report.as_of.isoformat()}", body)


def render_networth_html(report: NetWorthReport, *, history_start: date | None) -> str:
    """Render assets, liabilities, and net worth as a static HTML page."""
    body = _table(report.lines, NetWorthLine)
    body += _totals(
        (
            ("assets", money(report.assets)),
            ("liabilities", money(report.liabilities)),
            ("net worth", money(report.net_worth)),
            ("counted", f"{report.counted} of {len(report.lines)}"),
            ("excluded", str(len(report.excluded))),
        )
    )
    if report.incomplete:
        body += _note(
            f"warning: incomplete net worth; excluded: {', '.join(report.incomplete)}"
        )
    if report.ignored_before_history_start:
        body += _note(
            f"note: ignored {report.ignored_before_history_start} observations "
            f"before history_start {history_start.isoformat()}"
        )
    return _document(f"net worth as of {report.as_of.isoformat()}", body)


def render_renewals_html(report: RenewalsReport) -> str:
    """Render annual renewals, their schedule, and adequacy as a static HTML page."""
    header = f"renewals for {report.month}"
    if report.who is not None:
        header += f"  who {report.who}"
    body = _table(report.renewals, Renewal)
    if report.schedule:
        rows = "".join(
            "<tr>"
            f"{_tag('td', str(entry.month))}"
            f"{_tag('td', money(entry.total), num=True)}"
            f"{_tag('td', ', '.join(entry.items))}"
            "</tr>\n"
            for entry in report.schedule
        )
        body += (
            "<h2>schedule</h2>\n"
            "<table>\n"
            '<thead><tr><th>month</th><th class="num">total</th><th>items</th></tr></thead>\n'
            f"<tbody>\n{rows}</tbody>\n"
            "</table>\n"
        )
    else:
        body += _note("schedule: nothing due in the next 12 months")
    if report.shortfall_total == 0:
        adequacy = "ok"
    else:
        plural = "renewal" if report.short_count == 1 else "renewals"
        adequacy = f"short {money(report.shortfall_total)} across {report.short_count} {plural}"
    body += _totals(
        (
            ("set-aside monthly", money(report.set_aside_monthly)),
            ("accrued", money(report.accrued_total)),
            ("shortfall", money(report.shortfall_total)),
            ("adequacy", adequacy),
        )
    )
    return _document(header, body)


HTML_RENDERERS: dict[type, Callable[..., str]] = {
    Scorecard: render_scorecard_html,
    CategoriesReport: render_categories_html,
    BalancesReport: render_balances_html,
    NetWorthReport: render_networth_html,
    RenewalsReport: render_renewals_html,
}


def register_html_renderer(report_type: type, renderer: Callable[..., str]) -> None:
    """Register or replace the HTML renderer for a report type."""
    HTML_RENDERERS[report_type] = renderer


def render_html(report: object, **options: object) -> str:
    """Render a report through its registered HTML renderer.

    Raises ``TypeError`` for report types without a registered renderer.
    """
    renderer = HTML_RENDERERS.get(type(report))
    if renderer is None:
        for registered_type, candidate in HTML_RENDERERS.items():
            if isinstance(report, registered_type):
                renderer = candidate
                break
    if renderer is None:
        registered = ", ".join(
            sorted(registered_type.__name__ for registered_type in HTML_RENDERERS)
        )
        raise TypeError(f"no html renderer for {type(report).__name__}; registered: {registered}")
    return renderer(report, **options)


__all__ = [
    "HTML_RENDERERS",
    "register_html_renderer",
    "render_balances_html",
    "render_categories_html",
    "render_html",
    "render_networth_html",
    "render_renewals_html",
    "render_scorecard_html",
]
