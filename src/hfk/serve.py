"""Local read-only web front door: ``hfk serve`` (M5-10).

The server binds to a loopback address only and answers ``GET`` alone. Every
page is the static HTML render of one report (the same renderers ``--format
html`` uses) with a small navigation bar and a month picker added above it.
Pages carry no script and load nothing from the network.

The server never writes the workbook or the instance's config files. Its only
write path is ``out/``: the Regenerate action re-reads the workbook and the
config, then saves the month's pages there as static files.

Inputs are loaded once and cached; Regenerate drops the cache. A load or
report error is shown as an error page with the message the CLI would print,
never as a guessed number.
"""

from __future__ import annotations

import html
import ipaddress
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from hfk.config import (
    ConfigError,
    Declarations,
    Household,
    Month,
    Plan,
    load_declarations,
    load_household,
    load_instance_plan,
)
from hfk.engine import (
    BalancesError,
    BucketError,
    CategoriesError,
    NetWorthError,
    RenewalsError,
    ScorecardError,
    ShareError,
    build_balances,
    build_categories,
    build_networth,
    build_renewals,
    build_scorecard,
    run_doctor,
)
from hfk.ledger import Ledger
from hfk.render import render_doctor_html, render_html
from hfk.source import TillerFormatError, find_workbook, read_tiller

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
REPORTS = ("scorecard", "categories", "balances", "networth", "renewals", "doctor")
REPORT_TITLES = {
    "scorecard": "Scorecard",
    "categories": "Categories",
    "balances": "Balances",
    "networth": "Net worth",
    "renewals": "Renewals",
    "doctor": "Doctor",
}
_REPORT_ERRORS = (
    ConfigError,
    TillerFormatError,
    ShareError,
    BucketError,
    ScorecardError,
    CategoriesError,
    BalancesError,
    NetWorthError,
    RenewalsError,
)
_SECURITY_HEADERS = (
    ("Cache-Control", "no-store"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    (
        "Content-Security-Policy",
        (
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
            "frame-ancestors 'none'"
        ),
    ),
)
_NAV_STYLE = """\
<style>
nav.hfk { display: flex; flex-wrap: wrap; gap: 0.5rem 1rem; align-items: center;
  border-bottom: 1px solid #bbb; padding-bottom: 0.75rem; margin-bottom: 1rem; }
nav.hfk a.current { font-weight: bold; text-decoration: none; color: #222; }
nav.hfk form { display: flex; gap: 0.5rem; align-items: center; margin: 0; }
p.error { color: #a00; }
</style>
"""


class ServeError(ValueError):
    """A ``hfk serve`` setup problem, such as a non-loopback host."""


def check_loopback_host(host: str) -> str:
    """Return the IPv4 loopback address to bind for ``host``, or raise ``ServeError``.

    ``localhost`` means ``127.0.0.1``. Any other name, and any address that is
    not IPv4 loopback (``127.0.0.0/8``), is refused: reports hold private
    financial data and must never be reachable from another machine.
    """

    text = host.strip()
    if text.lower() == "localhost":
        return DEFAULT_HOST
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        address = None
    if address is None or address.version != 4 or not address.is_loopback:
        raise ServeError(
            f"refusing to serve on {host!r}: hfk serve binds to loopback only; "
            f"fix=omit --host or use --host {DEFAULT_HOST}"
        )
    return str(address)


def last_finished_month(today: date) -> Month:
    """The latest calendar month that has fully ended on ``today``."""

    first = today.replace(day=1)
    previous = first - timedelta(days=1)
    return Month(previous.year, previous.month)


def month_end(month: Month) -> date:
    """The last day of ``month``."""

    if month.month == 12:
        return date(month.year, 12, 31)
    return date(month.year, month.month + 1, 1) - timedelta(days=1)


@dataclass(frozen=True)
class _Inputs:
    household: Household
    declarations: Declarations
    plan: Plan | None
    plan_error: str | None
    ledger: Ledger


@dataclass(frozen=True)
class Page:
    status: int
    body: str


class FrontDoor:
    """Builds report pages for one instance; thread-safe and read-only."""

    def __init__(self, home: Path, *, today: Callable[[], date] | None = None) -> None:
        self.home = Path(home)
        self._today = today or date.today
        self._lock = threading.Lock()
        self._inputs: _Inputs | None = None

    def today(self) -> date:
        return self._today()

    def reset(self) -> None:
        """Drop cached inputs so the next page re-reads the workbook and config."""

        with self._lock:
            self._inputs = None

    def _load(self) -> _Inputs:
        with self._lock:
            if self._inputs is None:
                household = load_household(self.home)
                declarations = load_declarations(self.home, people=household.slugs)
                plan: Plan | None
                plan_error: str | None
                try:
                    plan = load_instance_plan(
                        self.home, household=household, declarations=declarations
                    )
                    plan_error = None
                except ConfigError as error:
                    plan, plan_error = None, str(error)
                workbook = find_workbook(self.home / "data", household.tiller_glob)
                ledger = read_tiller(workbook)
                self._inputs = _Inputs(household, declarations, plan, plan_error, ledger)
            return self._inputs

    def people(self) -> tuple[str, ...]:
        try:
            return self._load().household.slugs
        except _REPORT_ERRORS:
            return ()

    def page(self, report: str, *, month: Month, who: str | None) -> Page:
        """Render one report page, or an error page naming the problem."""

        if report == "doctor":
            doctor = run_doctor(self.home, today=self.today())
            return Page(HTTPStatus.OK, render_doctor_html(doctor))
        try:
            body = self._render(report, month=month, who=who)
        except (*_REPORT_ERRORS, ServeError) as error:
            return Page(HTTPStatus.OK, _error_page(report, month, str(error)))
        return Page(HTTPStatus.OK, body)

    def _render(self, report: str, *, month: Month, who: str | None) -> str:
        inputs = self._load()
        today = self.today()
        as_of = min(today, month_end(month))
        if report == "balances":
            result = build_balances(
                ledger=inputs.ledger,
                household=inputs.household,
                declarations=inputs.declarations,
                as_of=as_of,
            )
            return render_html(result, history_start=inputs.household.history_start)
        if report == "networth":
            result = build_networth(
                ledger=inputs.ledger,
                household=inputs.household,
                declarations=inputs.declarations,
                as_of=as_of,
                stale_after_days=14,
            )
            return render_html(result, history_start=inputs.household.history_start)
        if inputs.plan is None:
            raise ServeError(inputs.plan_error or "the plan did not load")
        if report == "renewals":
            result = build_renewals(
                plan=inputs.plan, household=inputs.household, month=month, who=who
            )
            return render_html(result)
        person = who if who is not None else inputs.household.slugs[0]
        builder = build_scorecard if report == "scorecard" else build_categories
        result = builder(
            ledger=inputs.ledger,
            household=inputs.household,
            declarations=inputs.declarations,
            plan=inputs.plan,
            month=month,
            who=person,
            today=today,
        )
        return render_html(result)

    def regenerate(self, *, month: Month, who: str | None) -> list[Path]:
        """Re-read every input, then save the month's pages under ``out/``."""

        self.reset()
        out = self.home / "out"
        out.mkdir(exist_ok=True)
        written: list[Path] = []
        suffix = f"-{who}" if who else ""
        for report in REPORTS:
            page = self.page(report, month=month, who=who)
            name = "doctor.html" if report == "doctor" else f"{report}-{month}{suffix}.html"
            path = out / name
            path.write_text(page.body, encoding="utf-8")
            written.append(path)
        return written


def _error_page(report: str, month: Month, message: str) -> str:
    title = html.escape(f"{report} {month}: not available")
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8" />\n'
        f"<title>{title}</title>\n"
        "</head>\n"
        "<body>\n"
        f"<h1>{title}</h1>\n"
        f'<p class="error">{html.escape(message)}</p>\n'
        "</body>\n"
        "</html>\n"
    )


def _nav(report: str, month: Month, who: str | None, people: tuple[str, ...]) -> str:
    links = []
    for name in REPORTS:
        query = {"month": str(month)}
        if who:
            query["who"] = who
        css = ' class="current"' if name == report else ""
        href = html.escape(f"/{name}?{urlencode(query)}")
        links.append(f'<a{css} href="{href}">{REPORT_TITLES[name]}</a>')
    options = ['<option value="">household</option>'] if report == "renewals" else []
    for slug in people:
        selected = ' selected="selected"' if slug == who else ""
        options.append(f'<option value="{html.escape(slug)}"{selected}>{html.escape(slug)}</option>')
    who_select = f'<select name="who">{"".join(options)}</select>' if options else ""
    picker = (
        f'<form method="get" action="/{report}">'
        f'<label>Month <input type="month" name="month" value="{month}" /></label>'
        f"{who_select}"
        '<button type="submit">Show</button>'
        "</form>"
    )
    regen_query = {"month": str(month), "report": report}
    if who:
        regen_query["who"] = who
    regenerate = (
        '<form method="get" action="/regenerate">'
        + "".join(
            f'<input type="hidden" name="{key}" value="{html.escape(value)}" />'
            for key, value in regen_query.items()
        )
        + '<button type="submit">Regenerate</button></form>'
    )
    return f'<nav class="hfk">{"".join(links)}{picker}{regenerate}</nav>\n'


def decorate(page: str, nav: str) -> str:
    """Insert the navigation bar and its style into a rendered report page."""

    page = page.replace("</head>\n", f"{_NAV_STYLE}</head>\n", 1)
    return page.replace("<body>\n", f"<body>\n{nav}", 1)


def make_handler(front: FrontDoor, *, port_ref: list[int]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "hfk"
        sys_version = ""

        def log_message(self, format: str, *args: object) -> None:
            return

        def __getattr__(self, name: str) -> Callable[[], None]:
            # BaseHTTPRequestHandler dispatches on do_<METHOD>; every method but
            # GET is refused with 405 rather than 501 so no write verb exists.
            if name.startswith("do_"):
                return self._method_not_allowed
            raise AttributeError(name)

        def _method_not_allowed(self) -> None:
            self.close_connection = True
            self._send(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed: hfk serve is read-only\n",
                       content_type="text/plain; charset=utf-8", extra=(("Allow", "GET"),))

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").strip().lower()
            port = port_ref[0]
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            return host in allowed

        def _send(
            self,
            status: int,
            body: str,
            *,
            content_type: str = "text/html; charset=utf-8",
            extra: tuple[tuple[str, str], ...] = (),
        ) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            for key, value in _SECURITY_HEADERS + extra:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if not self._host_ok():
                self._send(HTTPStatus.BAD_REQUEST, "bad Host header\n",
                           content_type="text/plain; charset=utf-8")
                return
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            path = parts.path.rstrip("/") or "/"
            report = "scorecard" if path == "/" else path.lstrip("/")
            month_text = (query.get("month") or [""])[0]
            who = (query.get("who") or [""])[0] or None
            try:
                month = (
                    Month.parse(month_text) if month_text else last_finished_month(front.today())
                )
            except ValueError:
                self._send(HTTPStatus.BAD_REQUEST, "write months as YYYY-MM\n",
                           content_type="text/plain; charset=utf-8")
                return
            if report == "regenerate":
                target = (query.get("report") or ["scorecard"])[0]
                if target not in REPORTS:
                    target = "scorecard"
                front.regenerate(month=month, who=who)
                location = {"month": str(month)}
                if who:
                    location["who"] = who
                self._send(HTTPStatus.SEE_OTHER, "", extra=(
                    ("Location", f"/{target}?{urlencode(location)}"),
                ))
                return
            if report not in REPORTS:
                self._send(HTTPStatus.NOT_FOUND, "not found\n",
                           content_type="text/plain; charset=utf-8")
                return
            people = front.people()
            if who is None and report in ("scorecard", "categories") and people:
                who = people[0]
            page = front.page(report, month=month, who=who)
            self._send(page.status, decorate(page.body, _nav(report, month, who, people)))

    return Handler


def make_server(
    home: Path,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    today: Callable[[], date] | None = None,
) -> ThreadingHTTPServer:
    """Create (but do not start) the front-door server; port 0 picks a free port."""

    address = check_loopback_host(host)
    home = Path(home)
    if not home.is_dir():
        raise ServeError(f"instance directory {home} does not exist; fix=pass --home <dir>")
    front = FrontDoor(home, today=today)
    port_ref = [port]
    server = ThreadingHTTPServer((address, port), make_handler(front, port_ref=port_ref))
    server.daemon_threads = True
    port_ref[0] = server.server_address[1]
    return server


def server_url(server: ThreadingHTTPServer) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}/"


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "REPORTS",
    "FrontDoor",
    "ServeError",
    "check_loopback_host",
    "decorate",
    "last_finished_month",
    "make_server",
    "month_end",
    "server_url",
]
