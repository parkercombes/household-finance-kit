"""Text, CSV and HTML output for the retirement track (M8-05, M8-06).

Text and HTML open with the mechanics-not-advice disclaimer and end with the
out-of-scope note (M8-06). CSV is a plain table for spreadsheets and carries
neither; the disclaimer is on every page a person reads.

Formatting only: every number comes from ``RetirementReport`` and is printed
with two decimal places. Every page labels its money as today's dollars and
states the inflation assumption (ADR-0008).
"""

from __future__ import annotations

import csv
import html
import io
from decimal import Decimal

from hfk.ext.retirement.report import RetirementReport

DISCLAIMER = (
    "Mechanics, not advice: this report is arithmetic on the figures in retirement.yaml. "
    "It does not recommend financial products, tax strategy, when to claim Social Security, "
    "or investment decisions."
)
OUT_OF_SCOPE = (
    "Not modelled: Monte Carlo simulation, optimisation, Roth conversion strategy, product "
    "recommendations, account balances or investment returns, and personal advice."
)
HOUSEHOLD_COLUMNS = (
    ("year", "year"),
    ("income", "income"),
    ("ordinary_taxable", "ordinary taxable"),
    ("social_security", "social security"),
    ("taxable_social_security", "taxable social security"),
    ("federal_tax", "federal tax"),
    ("state_tax", "state tax"),
    ("need", "need"),
    ("gap", "gap"),
)
PERSON_COLUMNS = (
    ("year", "year"),
    ("who", "who"),
    ("age", "age"),
    ("income", "income"),
    ("need", "own need"),
    ("before_tax", "income minus need, before tax"),
)


def _cell(value: object) -> str:
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    return str(value)


def header_lines(report: RetirementReport) -> list[str]:
    inflation = "not set" if report.inflation is None else str(report.inflation)
    scenario = ", ".join(f"{who} {age}" for who, age in report.scenario) or "none"
    social = "taxed" if report.state_taxes_social_security else "exempt"
    state = report.state_module if report.state_module == "none" else (
        f"{report.state_module}, Social Security {social}"
    )
    return [
        (f"retirement track {report.first_year}-{report.last_year}, in today's dollars "
        f"(priced in {report.base_year}; inflation assumption {inflation})"),
        f"claim ages: {scenario}",
        (f"federal tax: {report.tax_year} table ({report.tax_source}), {report.filing_status}; "
        f"state tax: {state}"),
    ]


def notes(report: RetirementReport) -> list[str]:
    return [
        "gap = income - federal tax - state tax - need; a negative gap is a shortfall.",
        ("per person: own income and own expenses only, before tax; tax and expenses with no "
        "person are counted only in the household view."),
    ]


def _rows(report: RetirementReport, which: str) -> tuple[tuple[tuple[str, str], ...], list]:
    if which == "household":
        return HOUSEHOLD_COLUMNS, list(report.household)
    return PERSON_COLUMNS, list(report.people)


def render_text(report: RetirementReport) -> str:
    lines = [DISCLAIMER, *header_lines(report)]
    for which, title in (("household", "household"), ("people", "per person, before tax")):
        columns, rows = _rows(report, which)
        table = [[label for _key, label in columns]] + [
            [_cell(getattr(row, key)) for key, _label in columns] for row in rows
        ]
        widths = [max(len(row[i]) for row in table) for i in range(len(columns))]
        lines.append("")
        lines.append(title)
        for row in table:
            lines.append(
                "  ".join(
                    cell.ljust(width) if index == 1 and which == "people" else cell.rjust(width)
                    for index, (cell, width) in enumerate(zip(row, widths, strict=True))
                ).rstrip()
            )
    lines.append("")
    lines.extend(notes(report))
    lines.append(OUT_OF_SCOPE)
    return "\n".join(lines) + "\n"


def render_csv(report: RetirementReport) -> str:
    """One CSV table: household rows, then per-person rows, told apart by ``view``."""

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    keys = ["view", "year", "who", "age", "income", "ordinary_taxable", "social_security",
            "taxable_social_security", "federal_tax", "state_tax", "need", "gap", "before_tax"]
    writer.writerow(keys)
    for row in report.household:
        values = {"view": "household", "who": "", "age": "", "before_tax": ""}
        values.update({key: _cell(getattr(row, key)) for key, _label in HOUSEHOLD_COLUMNS})
        writer.writerow([values.get(key, "") for key in keys])
    for row in report.people:
        values = {"view": "person"}
        values.update({key: _cell(getattr(row, key)) for key, _label in PERSON_COLUMNS})
        writer.writerow([values.get(key, "") for key in keys])
    return buffer.getvalue()


def render_html(report: RetirementReport) -> str:
    def esc(text: str) -> str:
        return html.escape(text, quote=True)

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8" />',
        f"<title>{esc(header_lines(report)[0])}</title>",
        ("<style>body{font-family:sans-serif;margin:2rem}table{border-collapse:collapse;"
        "margin-bottom:1.5rem}th,td{border:1px solid #bbb;padding:.25rem .5rem}"
        "td.num{text-align:right}</style>"),
        "</head>",
        "<body>",
        f"<h1>{esc(header_lines(report)[0])}</h1>",
        f'<p class="disclaimer"><strong>{esc(DISCLAIMER)}</strong></p>',
    ]
    parts.extend(f"<p>{esc(line)}</p>" for line in header_lines(report)[1:])
    for which, title in (("household", "Household"), ("people", "Per person, before tax")):
        columns, rows = _rows(report, which)
        parts.append(f"<h2>{esc(title)}</h2>")
        parts.append("<table>")
        parts.append("<tr>" + "".join(f"<th>{esc(label)}</th>" for _k, label in columns) + "</tr>")
        for row in rows:
            cells = []
            for key, _label in columns:
                value = getattr(row, key)
                css = ' class="num"' if isinstance(value, Decimal) else ""
                cells.append(f"<td{css}>{esc(_cell(value))}</td>")
            parts.append("<tr>" + "".join(cells) + "</tr>")
        parts.append("</table>")
    parts.extend(f"<p>{esc(line)}</p>" for line in notes(report))
    parts.append(f"<p>{esc(OUT_OF_SCOPE)}</p>")
    parts.extend(["</body>", "</html>"])
    return "\n".join(parts) + "\n"


__all__ = ["DISCLAIMER", "OUT_OF_SCOPE", "header_lines", "notes", "render_csv", "render_html", "render_text"]
