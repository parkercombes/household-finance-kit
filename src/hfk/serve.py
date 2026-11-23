"""Local web front door: ``hfk serve`` and ``hfk open`` (M5-10, M5-21).

The server binds to a loopback address only. Every report page is the static
HTML render of one report (the same renderers ``--format html`` uses) with a
small navigation bar, a month picker, and the Choose file form for a new
workbook download added above it.

A folder with no ``household.yaml`` gets the setup page instead (ADR-0022): a
copy of the workbook download into ``data/``, then the ``hfk init`` questions
as a form. Exactly two things may be written from a request: the settings, once
(``write_settings``), and a workbook copy into ``data/``. Regenerate also saves
the month's pages under ``out/``. The Tiller workbook itself is never written.

Each run makes a random token; every address starts with it, so an address
from another run, or from another web page, finds nothing. Writes are POSTs
with the token, an ``Origin`` exactly matching this server, and a size limit.

Inputs are loaded once and cached; Regenerate and a workbook copy drop the
cache. A load or report error is shown as an error page with the message the
CLI would print, never as a guessed number.
"""

from __future__ import annotations

import email.parser
import email.policy
import fnmatch
import hmac
import html
import ipaddress
import os
import secrets
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
from hfk.config.household import SLUG
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
from hfk.ext import load_extensions
from hfk.ext.doctor import extension_doctor_hooks
from hfk.instance import InstanceError, write_settings
from hfk.interview import WORKBOOK_GLOBS
from hfk.ledger import Ledger
from hfk.render import render_doctor_html, render_html
from hfk.setup_page import (
    answers_from_form,
    collect,
    render_setup_page,
    workbook_form,
    workbook_state,
)
from hfk.source import TillerFormatError, find_workbook, find_workbooks, read_tiller

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
    # same-origin, not no-referrer: with no-referrer, browsers send "Origin: null" on
    # the page's own form posts, which the exact Origin check must refuse. Other sites
    # still get no referrer.
    ("Referrer-Policy", "same-origin"),
)
# The answers form is small; a workbook download is a few megabytes at most.
FORM_LIMIT = 64 * 1024
WORKBOOK_LIMIT = 50 * 1024 * 1024
_ZIP_MAGIC = b"PK\x03\x04"  # an .xlsx file is a zip archive


def content_security_policy(nonce: str) -> str:
    """Scripts only from the page itself, with this response's nonce; nothing remote."""

    return (
        f"default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    )
_NAV_STYLE = """\
<style>
nav.hfk { display: flex; flex-wrap: wrap; gap: 0.5rem 1rem; align-items: center;
  border-bottom: 1px solid #bbb; padding-bottom: 0.75rem; margin-bottom: 1rem; }
nav.hfk a.current { font-weight: bold; text-decoration: none; color: #222; }
nav.hfk form { display: flex; gap: 0.5rem; align-items: center; margin: 0; }
nav.hfk p { margin: 0; flex-basis: 100%; }
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

    def configured(self) -> bool:
        """True once ``household.yaml`` exists; until then every page is the setup page."""

        return (self.home / "household.yaml").exists()

    def workbook_names(self) -> tuple[str, ...]:
        """Every workbook hfk could read in ``data/``, newest (the one read) first."""

        try:
            pattern = self._load().household.tiller_glob
        except _REPORT_ERRORS:
            return ()
        return tuple(path.name for path in find_workbooks(self.home / "data", pattern))

    def workbook_patterns(self) -> tuple[str, ...]:
        if self.configured():
            try:
                return (load_household(self.home).tiller_glob,)
            except ConfigError:
                pass
        return WORKBOOK_GLOBS

    def copy_workbook(self, filename: str, data: bytes) -> Path:
        """Copy a workbook download into ``data/``, replacing only a file of that name."""

        name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not name:
            raise ServeError("no file was chosen; choose the workbook download, then send it")
        if not name.lower().endswith(".xlsx") or name.startswith((".", "~$")):
            raise ServeError(
                f"{name} is not an Excel workbook (.xlsx); in Google Sheets use File > Download "
                "> Microsoft Excel (.xlsx), then choose that file"
            )
        patterns = self.workbook_patterns()
        if not any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns):
            raise ServeError(
                f"hfk only reads a workbook whose name matches {' or '.join(patterns)}, and "
                f"{name} does not; rename the download so its name starts with Tiller, like "
                f"Tiller-{name}, then choose it again"
            )
        if not data.startswith(_ZIP_MAGIC):
            raise ServeError(f"{name} is not an Excel workbook; download it again as .xlsx")
        data_dir = self.home / "data"
        data_dir.mkdir(exist_ok=True)
        destination = data_dir / name
        temporary = data_dir / f".{name}.hfk-tmp"
        temporary.write_bytes(data)
        os.replace(temporary, destination)
        self.reset()
        return destination

    def save_settings(self, documents: dict[str, str], starter_plan: str | None) -> None:
        write_settings(self.home, documents=documents, starter_plan=starter_plan)
        self.reset()

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
            doctor = run_doctor(
                self.home,
                today=self.today(),
                hooks=extension_doctor_hooks(load_extensions()),
            )
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
        if who is not None and not SLUG.match(who):
            raise ServeError(f"who {who!r} is not a person's slug")
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


def _nav(
    report: str,
    month: Month,
    who: str | None,
    people: tuple[str, ...],
    *,
    token: str,
    workbooks: tuple[str, ...] = (),
) -> str:
    prefix = f"/{token}"
    links = []
    for name in REPORTS:
        query = {"month": str(month)}
        if who:
            query["who"] = who
        css = ' class="current"' if name == report else ""
        href = html.escape(f"{prefix}/{name}?{urlencode(query)}")
        links.append(f'<a{css} href="{href}">{REPORT_TITLES[name]}</a>')
    options = ['<option value="">household</option>'] if report == "renewals" else []
    for slug in people:
        selected = ' selected="selected"' if slug == who else ""
        options.append(f'<option value="{html.escape(slug)}"{selected}>{html.escape(slug)}</option>')
    who_select = f'<select name="who">{"".join(options)}</select>' if options else ""
    picker = (
        f'<form method="get" action="{prefix}/{report}">'
        f'<label>Month <input type="month" name="month" value="{month}" /></label>'
        f"{who_select}"
        '<button type="submit">Show</button>'
        "</form>"
    )
    regen_query = {"month": str(month), "report": report}
    if who:
        regen_query["who"] = who
    regenerate = (
        f'<form method="get" action="{prefix}/regenerate">'
        + "".join(
            f'<input type="hidden" name="{key}" value="{html.escape(value)}" />'
            for key, value in regen_query.items()
        )
        + '<button type="submit">Regenerate</button></form>'
    )
    back = f"/{report}?{urlencode({k: v for k, v in regen_query.items() if k != 'report'})}"
    refresh = workbook_form(token, back, label="Copy a new download")
    read = ""
    if len(workbooks) > 1:
        read = (
            f"<p>Read {html.escape(workbooks[0])}, the newest workbook in data; also there: "
            f"{html.escape(', '.join(workbooks[1:]))}.</p>"
        )
    return f'<nav class="hfk">{"".join(links)}{picker}{regenerate}{refresh}{read}</nav>\n'


def decorate(page: str, nav: str) -> str:
    """Insert the navigation bar and its style into a rendered report page."""

    page = page.replace("</head>\n", f"{_NAV_STYLE}</head>\n", 1)
    return page.replace("<body>\n", f"<body>\n{nav}", 1)


def _message_page(title: str, message: str, *, back: str | None = None) -> str:
    link = f'<p><a href="{html.escape(back)}">Go back</a></p>\n' if back else ""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8" />\n'
        f"<title>{html.escape(title)}</title>\n"
        "</head>\n"
        "<body>\n"
        f"<h1>{html.escape(title)}</h1>\n"
        f'<p class="error">{html.escape(message)}</p>\n'
        f"{link}"
        "</body>\n"
        "</html>\n"
    )


def _safe_back(back: str) -> str:
    """A path on this server to return to after a copy; anything else is the first page."""

    if not back.startswith("/") or back.startswith("//") or "\\" in back:
        return "/"
    return back


def make_handler(
    front: FrontDoor, *, port_ref: list[int], token: str
) -> type[BaseHTTPRequestHandler]:
    prefix = f"/{token}"

    class Handler(BaseHTTPRequestHandler):
        server_version = "hfk"
        sys_version = ""

        def log_message(self, format: str, *args: object) -> None:
            return

        def __getattr__(self, name: str) -> Callable[[], None]:
            # BaseHTTPRequestHandler dispatches on do_<METHOD>; every method but GET
            # and POST is refused with 405 rather than 501.
            if name.startswith("do_"):
                return self._method_not_allowed
            raise AttributeError(name)

        def _method_not_allowed(self) -> None:
            self.close_connection = True
            self._send(HTTPStatus.METHOD_NOT_ALLOWED,
                       "method not allowed: hfk answers GET, and POST only for its two forms\n",
                       content_type="text/plain; charset=utf-8", extra=(("Allow", "GET, POST"),))

        def _host(self) -> str | None:
            host = (self.headers.get("Host") or "").strip().lower()
            port = port_ref[0]
            return host if host in {f"127.0.0.1:{port}", f"localhost:{port}"} else None

        def _send(
            self,
            status: int,
            body: str,
            *,
            content_type: str = "text/html; charset=utf-8",
            extra: tuple[tuple[str, str], ...] = (),
            nonce: str | None = None,
        ) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            for key, value in _SECURITY_HEADERS + extra:
                self.send_header(key, value)
            self.send_header(
                "Content-Security-Policy", content_security_policy(nonce or secrets.token_urlsafe(16))
            )
            self.end_headers()
            self.wfile.write(data)

        def _text(self, status: int, text: str) -> None:
            self._send(status, text, content_type="text/plain; charset=utf-8")

        def _redirect(self, path: str) -> None:
            self._send(HTTPStatus.SEE_OTHER, "", extra=(("Location", prefix + path),))

        def _route(self) -> tuple[str, dict[str, list[str]]] | None:
            """The path after the token and the query, or ``None`` once refused."""

            if self._host() is None:
                self._text(HTTPStatus.BAD_REQUEST, "bad Host header\n")
                return None
            parts = urlsplit(self.path)
            path = parts.path
            if path != prefix and not path.startswith(prefix + "/"):
                # Compare the token in constant time, then refuse every other address.
                hmac.compare_digest(path[1 : len(prefix)].encode(), token.encode())
                self._text(
                    HTTPStatus.NOT_FOUND,
                    "not found: this address is from an earlier run of hfk, or is not hfk's; "
                    "double-click Open HFK to open it again\n",
                )
                return None
            rest = path[len(prefix):].rstrip("/") or "/"
            return rest, parse_qs(parts.query)

        def _setup_page(self, *, collected=None, message=None, status=HTTPStatus.OK) -> None:
            nonce = secrets.token_urlsafe(16)
            body = render_setup_page(
                front.home, token=token, nonce=nonce, collected=collected, message=message
            )
            self._send(status, body, nonce=nonce)

        def do_GET(self) -> None:
            route = self._route()
            if route is None:
                return
            path, query = route
            if not front.configured():
                if path in ("/", "/setup", "/regenerate", *(f"/{name}" for name in REPORTS)):
                    self._setup_page()
                else:
                    self._text(HTTPStatus.NOT_FOUND, "not found\n")
                return
            if path == "/setup":
                self._redirect("/doctor")
                return
            report = "scorecard" if path == "/" else path.lstrip("/")
            month_text = (query.get("month") or [""])[0]
            who = (query.get("who") or [""])[0] or None
            if who is not None and not SLUG.match(who):
                # who names a file under out/ on Regenerate, so only a slug is accepted.
                self._text(HTTPStatus.BAD_REQUEST, "who must be a person's slug from household.yaml\n")
                return
            try:
                month = (
                    Month.parse(month_text) if month_text else last_finished_month(front.today())
                )
            except ValueError:
                self._text(HTTPStatus.BAD_REQUEST, "write months as YYYY-MM\n")
                return
            if report == "regenerate":
                target = (query.get("report") or ["scorecard"])[0]
                if target not in REPORTS:
                    target = "scorecard"
                front.regenerate(month=month, who=who)
                location = {"month": str(month)}
                if who:
                    location["who"] = who
                self._redirect(f"/{target}?{urlencode(location)}")
                return
            if report not in REPORTS:
                self._text(HTTPStatus.NOT_FOUND, "not found\n")
                return
            people = front.people()
            if who is None and report in ("scorecard", "categories") and people:
                who = people[0]
            page = front.page(report, month=month, who=who)
            nav = _nav(report, month, who, people, token=token, workbooks=front.workbook_names())
            self._send(page.status, decorate(page.body, nav))

        def do_POST(self) -> None:
            self.close_connection = True
            route = self._route()
            if route is None:
                return
            path, _query = route
            if path not in ("/setup", "/workbook"):
                self._method_not_allowed()
                return
            origin = self.headers.get("Origin")
            if origin is None or origin.strip().lower() != f"http://{self._host()}":
                self._text(HTTPStatus.FORBIDDEN,
                           "refused: this form must be sent from hfk's own page\n")
                return
            limit = FORM_LIMIT if path == "/setup" else WORKBOOK_LIMIT
            try:
                length = int(self.headers.get("Content-Length") or "")
            except ValueError:
                self._text(HTTPStatus.LENGTH_REQUIRED, "refused: the request has no length\n")
                return
            if length < 0 or length > limit:
                self._text(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                           f"refused: the request is larger than {limit} bytes\n")
                return
            body = self.rfile.read(length)
            if path == "/setup":
                self._post_setup(body)
            else:
                self._post_workbook(body)

        def _post_setup(self, body: bytes) -> None:
            if front.configured():
                self._send(HTTPStatus.CONFLICT, _message_page(
                    "hfk is already set up",
                    "The settings were already saved, so they were not changed. To change "
                    "them, edit household.yaml or declarations.yaml in the hfk folder.",
                    back=f"{prefix}/doctor",
                ))
                return
            form = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
            workbook = workbook_state(front.home).chosen
            if workbook is None:
                self._setup_page(message="Choose your workbook download first.",
                                 status=HTTPStatus.BAD_REQUEST)
                return
            collected = collect(workbook, answers_from_form(form))
            if collected.result is None:
                self._setup_page(collected=collected)
                return
            try:
                front.save_settings(collected.result.documents, collected.result.starter_plan)
            except InstanceError as error:
                self._send(HTTPStatus.CONFLICT, _message_page(
                    "The settings were not saved", f"{error.problem}; {error.fix}",
                    back=f"{prefix}/doctor",
                ))
                return
            self._redirect("/doctor")

        def _post_workbook(self, body: bytes) -> None:
            fields = _multipart(self.headers.get("Content-Type") or "", body)
            back = _safe_back((fields.get("back") or ("", b""))[1].decode("utf-8", "replace"))
            filename, data = fields.get("workbook") or ("", b"")
            try:
                front.copy_workbook(filename, data)
            except ServeError as error:
                if not front.configured():
                    self._setup_page(message=str(error), status=HTTPStatus.BAD_REQUEST)
                else:
                    self._send(HTTPStatus.BAD_REQUEST, _message_page(
                        "The workbook was not copied", str(error), back=prefix + back
                    ))
                return
            self._redirect(back)

    return Handler


def _multipart(content_type: str, body: bytes) -> dict[str, tuple[str, bytes]]:
    """Each form field's file name and bytes from a ``multipart/form-data`` body."""

    if not content_type.lower().startswith("multipart/form-data"):
        return {}
    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1", "replace") + b"\r\n\r\n" + body
    )
    if not message.is_multipart():
        return {}
    fields: dict[str, tuple[str, bytes]] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str) or name in fields:
            continue
        payload = part.get_payload(decode=True)
        fields[name] = (part.get_filename() or "", payload if isinstance(payload, bytes) else b"")
    return fields


def make_server(
    home: Path,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    today: Callable[[], date] | None = None,
    token: str | None = None,
) -> ThreadingHTTPServer:
    """Create (but do not start) the front-door server; port 0 picks a free port.

    ``token`` starts every address; by default each server makes a new random one.
    """

    address = check_loopback_host(host)
    home = Path(home)
    if not home.is_dir():
        raise ServeError(f"instance directory {home} does not exist; fix=pass --home <dir>")
    if token is None:
        token = secrets.token_urlsafe(24)
    if not token or not all(ch.isalnum() or ch in "-_" for ch in token):
        raise ServeError("the token must be letters, digits, - or _")
    front = FrontDoor(home, today=today)
    port_ref = [port]
    server = ThreadingHTTPServer(
        (address, port), make_handler(front, port_ref=port_ref, token=token)
    )
    server.daemon_threads = True
    server.hfk_token = token  # type: ignore[attr-defined]
    port_ref[0] = server.server_address[1]
    return server


def server_url(server: ThreadingHTTPServer) -> str:
    """The address to open: this server, then its token."""

    host, port = server.server_address[:2]
    return f"http://{host}:{port}/{server.hfk_token}/"  # type: ignore[attr-defined]


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "REPORTS",
    "FrontDoor",
    "ServeError",
    "check_loopback_host",
    "content_security_policy",
    "decorate",
    "last_finished_month",
    "make_server",
    "month_end",
    "server_url",
]
