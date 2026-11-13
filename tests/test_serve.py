"""Local read-only web front door tests (M5-10)."""

from __future__ import annotations

import hashlib
import http.client
import os
import re
import shutil
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

from hfk.config import Month, load_declarations, load_household, load_instance_plan
from hfk.engine import build_scorecard
from hfk.render import render_text
from hfk.serve import ServeError, check_loopback_host, last_finished_month, make_server
from hfk.source import find_workbook, read_tiller
from hfk.source.fixture import build_fixture

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
PYTHONPATH = str(ROOT / "src")
TODAY = date(2026, 9, 15)


def make_instance(tmp_path: Path) -> Path:
    home = tmp_path / "instance"
    home.mkdir()
    for filename in ("household.yaml", "declarations.yaml", "plan.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, home / filename)
    build_fixture(home / "data" / "Tiller-Example.xlsx")
    return home


@contextmanager
def running(home: Path) -> Iterator[int]:
    server = make_server(home, port=0, today=lambda: TODAY)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request(
    port: int, method: str, path: str, *, host: str | None = None
) -> tuple[int, dict[str, str], str]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        headers = {"Host": host} if host is not None else {}
        connection.request(method, path, body=b"x" if method in {"POST", "PUT"} else None,
                           headers=headers)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        return response.status, dict(response.getheaders()), body
    finally:
        connection.close()


def snapshot_tree(home: Path) -> dict[str, str]:
    return {
        str(path.relative_to(home)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(home.rglob("*"))
        if path.is_file()
    }


def totals(page: str) -> dict[str, str]:
    root = ET.fromstring(page.split("\n", 1)[1])
    dl = root.find("body/dl")
    labels = [dt.text for dt in dl.findall("dt")]
    values = [dd.text for dd in dl.findall("dd")]
    return dict(zip(labels, values, strict=True))


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::1", "::", "example.com", ""])
def test_server_refuses_non_loopback_host(tmp_path, host):
    home = make_instance(tmp_path)
    with pytest.raises(ServeError, match="loopback only"):
        make_server(home, host=host, port=0)


def test_loopback_hosts_are_accepted():
    assert check_loopback_host("127.0.0.1") == "127.0.0.1"
    assert check_loopback_host("localhost") == "127.0.0.1"
    assert check_loopback_host("127.0.0.2") == "127.0.0.2"


def test_cli_serve_refuses_non_loopback_host(tmp_path):
    home = make_instance(tmp_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH
    result = subprocess.run(
        [sys.executable, "-m", "hfk", "serve", "--home", str(home), "--host", "0.0.0.0"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 1
    assert "loopback only" in result.stderr
    assert result.stdout == ""


def test_root_is_scorecard_with_text_render_totals(tmp_path):
    home = make_instance(tmp_path)
    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    plan = load_instance_plan(home, household=household, declarations=declarations)
    ledger = read_tiller(find_workbook(home / "data", household.tiller_glob))
    month = last_finished_month(TODAY)
    assert month == Month(2026, 8)
    scorecard = build_scorecard(
        ledger=ledger,
        household=household,
        declarations=declarations,
        plan=plan,
        month=month,
        who=household.slugs[0],
        today=TODAY,
    )
    text = render_text(scorecard)
    total_line = text.splitlines()[-1]
    match = re.fullmatch(r"total  plan (\S+)  actual (\S+)  left (\S+)", total_line)
    assert match, total_line

    with running(home) as port:
        status, headers, page = request(port, "GET", "/")

    assert status == 200
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert "scorecard 2026-08 for alex" in page
    assert totals(page) == {
        "total plan": match.group(1),
        "total actual": match.group(2),
        "total left": match.group(3),
    }
    assert '<input type="month" name="month" value="2026-08" />' in page
    assert 'action="/regenerate"' in page
    assert "<script" not in page
    assert "http://" not in page and "https://" not in page


@pytest.mark.parametrize(
    "method", ["POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "CONNECT", "BREW"]
)
def test_every_non_get_request_is_405(tmp_path, method):
    home = make_instance(tmp_path)
    with running(home) as port:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        try:
            connection.putrequest(method, "/", skip_accept_encoding=True)
            connection.putheader("Content-Length", "0")
            connection.endheaders()
            response = connection.getresponse()
            response.read()
            status = response.status
            allow = response.getheader("Allow")
        finally:
            connection.close()
    assert status == 405
    assert allow == "GET"


def test_foreign_host_header_is_refused(tmp_path):
    home = make_instance(tmp_path)
    with running(home) as port:
        status, _headers, _body = request(port, "GET", "/", host=f"attacker.example:{port}")
        ok, _headers, _body = request(port, "GET", "/", host=f"localhost:{port}")
    assert status == 400
    assert ok == 200


def test_unfinished_month_scorecard_is_an_error_page(tmp_path):
    home = make_instance(tmp_path)
    with running(home) as port:
        status, _headers, page = request(port, "GET", "/scorecard?month=2026-09&who=alex")
    assert status == 200
    assert "not available" in page
    assert '<p class="error">' in page
    assert "<dl" not in page


def test_doctor_page_shows_readiness(tmp_path):
    home = make_instance(tmp_path)
    with running(home) as port:
        status, _headers, page = request(port, "GET", "/doctor")
    assert status == 200
    assert "doctor: 0 errors" in page
    assert "readiness: ready" in page


def test_full_crawl_writes_only_out(tmp_path):
    home = make_instance(tmp_path)
    before = snapshot_tree(home)
    paths = ["/", "/missing", "/scorecard?month=bad"]
    for report in ("scorecard", "categories", "balances", "networth", "renewals", "doctor"):
        for month in ("2026-07", "2026-08", "2026-09"):
            for who in ("", "alex", "sam"):
                suffix = f"&who={who}" if who else ""
                paths.append(f"/{report}?month={month}{suffix}")
    paths.append("/regenerate?month=2026-08&who=alex&report=categories")

    with running(home) as port:
        statuses = {path: request(port, "GET", path)[0] for path in paths}
        for method in ("POST", "PUT", "DELETE"):
            request(port, method, "/regenerate?month=2026-08")

    assert statuses["/"] == 200
    assert statuses["/missing"] == 404
    assert statuses["/scorecard?month=bad"] == 400
    assert statuses["/regenerate?month=2026-08&who=alex&report=categories"] == 303
    after = snapshot_tree(home)
    changed = {
        name
        for name in set(before) | set(after)
        if before.get(name) != after.get(name)
    }
    assert changed, "Regenerate should save pages under out/"
    assert all(name.startswith("out" + os.sep) for name in changed), changed
    assert {name for name in before if name in after} == set(before)
    assert (home / "out" / "scorecard-2026-08-alex.html").exists()
    assert (home / "out" / "doctor.html").exists()


def test_regenerate_rereads_the_workbook(tmp_path):
    home = make_instance(tmp_path)
    workbook = home / "data" / "Tiller-Example.xlsx"
    with running(home) as port:
        _status, _headers, first = request(port, "GET", "/scorecard?month=2026-08&who=alex")
        workbook.unlink()
        _status, _headers, cached = request(port, "GET", "/scorecard?month=2026-08&who=alex")
        status, headers, _body = request(port, "GET", "/regenerate?month=2026-08&who=alex")
        _status, _headers, after = request(port, "GET", "/scorecard?month=2026-08&who=alex")
    assert first == cached
    assert status == 303
    assert headers["Location"] == "/scorecard?month=2026-08&who=alex"
    assert "not available" in after
    assert "workbook" in after.lower()
