"""Text, CSV and HTML output for the settle-up statement (M7-04).

Formatting only: every number comes from ``Statement`` and prints with two
decimal places.
"""

from __future__ import annotations

import csv
import html
import io
from decimal import Decimal

from hfk.ext.settle_up.statement import Statement


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def header(statement: Statement) -> str:
    a, b = statement.people
    return (
        f"settle-up {statement.month} for {a} and {b} "
        "(finished month; owed shares per declarations, payers per settle_up.yaml)"
    )


def transfer_line(statement: Statement) -> str:
    if statement.transfer is None:
        return "transfer: none, already even"
    t = statement.transfer
    return f"transfer: {t.payer} pays {t.payee} {_money(t.amount)}"


def items_line(statement: Statement) -> str:
    if not statement.items_found:
        return f"shared items: none ({statement.items_file} does not exist)"
    count = sum(1 for line in statement.lines if line.source == "shared item")
    return f"shared items: {count} from {statement.items_file}"


def render_text(statement: Statement) -> str:
    a, b = statement.people
    lines = [header(statement), items_line(statement), ""]
    width = max([len("category"), *(len(name) for name, _ in statement.categories)])
    lines.append(f"{'category':<{width}}  {'total':>10}")
    for name, total in statement.categories:
        lines.append(f"{name:<{width}}  {_money(total):>10}")
    lines.append(f"{'total':<{width}}  {_money(statement.total):>10}")
    lines.append("")
    who = max(len(a), len(b), len("person"))
    lines.append(f"{'person':<{who}}  {'paid':>10}  {'owes':>10}  {'net':>10}")
    for index, person in enumerate(statement.people):
        lines.append(
            f"{person:<{who}}  {_money(statement.paid[index]):>10}  "
            f"{_money(statement.owed[index]):>10}  {_money(statement.net[index]):>10}"
        )
    lines.append("")
    lines.append(transfer_line(statement))
    return "\n".join(lines) + "\n"


def render_csv(statement: Statement) -> str:
    """One row per shared charge or item, with what each person paid and owes."""

    a, b = statement.people
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["source", "date", "description", "account", "category", "amount",
                     f"{a} paid", f"{b} paid", f"{a} owes", f"{b} owes"])
    for line in statement.lines:
        writer.writerow([
            line.source,
            "" if line.date is None else line.date.isoformat(),
            line.description,
            line.account,
            line.category,
            _money(line.amount),
            _money(line.paid[0]),
            _money(line.paid[1]),
            _money(line.owed[0]),
            _money(line.owed[1]),
        ])
    return buffer.getvalue()


def render_html(statement: Statement) -> str:
    def esc(text: str) -> str:
        return html.escape(text, quote=True)

    title = esc(header(statement))
    rows = "".join(
        f"<tr><td>{esc(name)}</td><td class=\"num\">{_money(total)}</td></tr>"
        for name, total in statement.categories
    )
    people = "".join(
        f"<tr><td>{esc(person)}</td><td class=\"num\">{_money(statement.paid[i])}</td>"
        f"<td class=\"num\">{_money(statement.owed[i])}</td>"
        f"<td class=\"num\">{_money(statement.net[i])}</td></tr>"
        for i, person in enumerate(statement.people)
    )
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\" />\n"
        f"<title>{title}</title>\n"
        "<style>body{font-family:sans-serif;margin:2rem}table{border-collapse:collapse;"
        "margin-bottom:1.5rem}th,td{border:1px solid #bbb;padding:.25rem .5rem}"
        "td.num{text-align:right}</style>\n</head>\n<body>\n"
        f"<h1>{title}</h1>\n<p>{esc(items_line(statement))}</p>\n"
        f"<table>\n<tr><th>category</th><th>total</th></tr>\n{rows}\n"
        f"<tr><th>total</th><td class=\"num\">{_money(statement.total)}</td></tr>\n</table>\n"
        f"<table>\n<tr><th>person</th><th>paid</th><th>owes</th><th>net</th></tr>\n{people}\n"
        f"</table>\n<p><strong>{esc(transfer_line(statement))}</strong></p>\n</body>\n</html>\n"
    )


def render_paste(statement: Statement) -> str:
    """A tab-separated block to paste into a household's own settle-up tab (M7-07).

    hfk never writes the workbook; the household pastes this block where it
    wants it. Every value comes from the statement.
    """

    rows = [["settle-up", str(statement.month)], ["category", "total"]]
    rows += [[name, _money(total)] for name, total in statement.categories]
    rows.append(["total", _money(statement.total)])
    rows.append([])
    rows.append(["person", "paid", "owes", "net"])
    for index, person in enumerate(statement.people):
        rows.append([person, _money(statement.paid[index]), _money(statement.owed[index]),
                     _money(statement.net[index])])
    rows.append([])
    if statement.transfer is None:
        rows.append(["transfer", "none"])
    else:
        t = statement.transfer
        rows.append(["transfer", t.payer, t.payee, _money(t.amount)])
    return "\n".join("\t".join(row) for row in rows) + "\n"


__all__ = ["header", "render_csv", "render_html", "render_paste", "render_text", "transfer_line"]
