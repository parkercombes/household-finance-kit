"""The setup page that ``hfk open`` serves for a folder with no settings (M5-21, ADR-0022).

The tests drive the pages the way a browser with scripts turned off would: they
read each form from the page's HTML, change only the fields a person would
change, and send it back.
"""

from __future__ import annotations

import hashlib
import http.client
import os
import re
import shutil
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode

import pytest
import yaml

from hfk.instance import write_instance, write_setup_folder
from hfk.interview import load_answers, run_interview
from hfk.serve import FORM_LIMIT, make_server
from hfk.source.fixture import build_fixture

TOKEN = "setup-token"
PREFIX = f"/{TOKEN}"
TODAY = date(2026, 9, 15)
WORKBOOK = "Tiller-Example.xlsx"
SETTINGS = ("household.yaml", "declarations.yaml", "settle_up.yaml")

# What a person picks on the page, by field name; everything else keeps the page's value.
PICKS = {
    "q:people": "Alex, Sam",
    "q:account:Alex Checking": "alex",
    "q:account:Sam Checking": "sam",
    "q:account:Joint Card": "alex=0.5, sam=0.5",
    "q:account:Savings": "alex",
    "q:profile": "four-bucket",
    "q:group:Housing": "Fixed Essential",
    "q:group:Food": "Variable Essential",
    "q:group:Transportation": "Variable Essential",
    "q:group:Subscriptions": "Fixed Discretionary",
    "q:history_start": "2026-04-01",
}
# The same household as an hfk init --answers file.
ANSWERS = {
    "people": [{"slug": "alex", "name": "Alex"}, {"slug": "sam", "name": "Sam"}],
    "accounts": {
        "Alex Checking": {"owner": "alex"},
        "Sam Checking": {"owner": "sam"},
        "Joint Card": {"shared": {"alex": 0.5, "sam": 0.5}},
        "Savings": {"owner": "alex"},
    },
    "profile": "four-bucket",
    "groups": {
        "Housing": "Fixed Essential",
        "Food": "Variable Essential",
        "Transportation": "Variable Essential",
        "Subscriptions": "Fixed Discretionary",
    },
    "history_start": date(2026, 4, 1),
}


def setup_folder(tmp_path: Path, *, workbook: bool = True) -> Path:
    home = tmp_path / "HFK"
    write_setup_folder(home)
    if workbook:
        build_fixture(home / "data" / WORKBOOK)
    return home


def tree(home: Path) -> dict[str, str]:
    return {
        str(path.relative_to(home)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(home.rglob("*"))
        if path.is_file()
    }


@contextmanager
def running(home: Path) -> Iterator[int]:
    server = make_server(home, port=0, today=lambda: TODAY, token=TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def send(
    port: int,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    origin: str | None = "same",
) -> tuple[int, dict[str, str], str]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    all_headers = dict(headers or {})
    if origin == "same":
        all_headers["Origin"] = f"http://127.0.0.1:{port}"
    elif origin is not None:
        all_headers["Origin"] = origin
    try:
        connection.request(method, path, body=body, headers=all_headers)
        response = connection.getresponse()
        text = response.read().decode("utf-8")
        return response.status, dict(response.getheaders()), text
    finally:
        connection.close()


def get(port: int, path: str) -> tuple[int, dict[str, str], str]:
    return send(port, "GET", PREFIX + path, origin=None)


def post_form(
    port: int, fields: list[tuple[str, str]], *, origin: str | None = "same"
) -> tuple[int, dict[str, str], str]:
    body = urlencode(fields).encode()
    return send(
        port,
        "POST",
        f"{PREFIX}/setup",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        origin=origin,
    )


def post_workbook(
    port: int, filename: str, data: bytes, *, back: str = "/setup", origin: str | None = "same"
) -> tuple[int, dict[str, str], str]:
    boundary = "hfk-test-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="back"\r\n\r\n'
        f"{back}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="workbook"; filename="{filename}"\r\n'
        "Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return send(
        port,
        "POST",
        f"{PREFIX}/workbook",
        body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        origin=origin,
    )


class _Form(HTMLParser):
    """The answers form's fields as a browser without scripts would send them."""

    def __init__(self) -> None:
        super().__init__()
        self.inside = False
        self.fields: list[tuple[str, str]] = []
        self.radios: dict[str, list[tuple[str, bool]]] = {}
        self.checkboxes: dict[str, tuple[str, bool]] = {}
        self.selects: dict[str, list[tuple[str, bool]]] = {}
        self.select: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "form" and values.get("id") == "answers":
            self.inside = True
        if not self.inside:
            return
        if tag == "input":
            kind, name = values.get("type", "text"), values.get("name", "")
            if kind == "radio":
                self.radios.setdefault(name, []).append((values["value"], "checked" in values))
            elif kind == "checkbox":
                self.checkboxes[name] = (values["value"], "checked" in values)
            else:
                self.fields.append((name, values.get("value", "")))
        elif tag == "select":
            self.select = values["name"]
            self.selects[self.select] = []
        elif tag == "option" and self.select is not None:
            self.selects[self.select].append((values["value"], "selected" in values))

    def handle_endtag(self, tag: str) -> None:
        if tag == "select":
            self.select = None
        if tag == "form":
            self.inside = False


def fill(page: str, picks: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """Fill the page's form: ``picks`` by field name, every other field as shown."""

    picks = PICKS if picks is None else picks
    form = _Form()
    form.feed(page)
    sent: list[tuple[str, str]] = []
    for name, value in form.fields:
        if name.endswith(":other"):
            continue
        sent.append((name, picks.get(name, value) if name != "asked" else value))
    for name, options in form.radios.items():
        values = [value for value, _checked in options]
        wanted = picks.get(name)
        if wanted is not None and wanted not in values:
            sent += [(name, "__other__"), (f"{name}:other", wanted)]
            continue
        chosen = wanted or next((value for value, checked in options if checked), None)
        if chosen is not None:
            sent.append((name, chosen))
    for name, (value, checked) in form.checkboxes.items():
        if picks.get(name, "plan" if checked else "") == "plan":
            sent.append((name, value))
    for name, options in form.selects.items():
        chosen = picks.get(name) or next((value for value, selected in options if selected), "")
        sent.append((name, chosen))
    return sent


def answer_everything(port: int, picks: dict[str, str] | None = None) -> tuple[int, dict, str]:
    """Press Continue until the page stops asking: at most one round per question kind."""

    _status, _headers, page = get(port, "/")
    for _round in range(6):
        status, headers, page = post_form(port, fill(page, picks))
        if status != 200:
            return status, headers, page
    return status, headers, page


def test_a_folder_from_hfk_setup_opens_on_the_setup_page(tmp_path: Path) -> None:
    home = setup_folder(tmp_path, workbook=False)
    with running(home) as port:
        pages = {path: get(port, path) for path in ("/", "/scorecard", "/doctor", "/setup")}
    for path, (status, headers, page) in pages.items():
        assert status == 200, path
        assert "<title>Set up hfk</title>" in page
        assert "File &gt; Download &gt; Microsoft Excel (.xlsx)" in page
        assert f'action="{PREFIX}/workbook"' in page
        assert 'id="answers"' not in page  # no questions before there is a workbook
        nonce = re.search(r'<script nonce="([^"]+)">', page).group(1)
        assert f"script-src 'nonce-{nonce}'" in headers["Content-Security-Policy"]
        assert "http://" not in page and "https://" not in page


def test_the_first_round_asks_only_for_the_people(tmp_path: Path) -> None:
    home = setup_folder(tmp_path)
    with running(home) as port:
        _status, _headers, page = get(port, "/")
        status, _headers, second = post_form(port, fill(page))
    assert f"hfk will read <strong>{WORKBOOK}</strong>" in page
    assert re.findall(r'name="asked" value="([^"]+)"', page) == ["people"]
    assert status == 200
    asked = re.findall(r'name="asked" value="([^"]+)"', second)
    assert asked[0] == "people"
    assert "account:Joint Card" in asked and "profile" in asked and "history_start" in asked
    assert not any(key.startswith(("group:", "override:")) for key in asked)
    assert "Alex (alex), Sam (sam)" in second
    # Only hfk's own defaults are filled in: an owner named in the account, the history start.
    assert 'value="alex" checked="checked"' in second
    assert 'value="2026-04-02"' in second


def test_group_buckets_start_empty_and_an_unanswered_group_is_refused(tmp_path: Path) -> None:
    home = setup_folder(tmp_path)
    before = tree(home)
    picks = {key: value for key, value in PICKS.items() if key != "q:group:Food"}
    with running(home) as port:
        _status, _headers, page = get(port, "/")
        page = post_form(port, fill(page, picks))[2]
        groups_page = post_form(port, fill(page, picks))[2]
        status, _headers, refused = post_form(port, fill(groups_page, picks))
    assert '<option value="">Choose a bucket</option>' in groups_page
    assert "selected" not in groups_page.split('name="q:group:Housing"')[1].split("</select>")[0]
    assert status == 200
    food = refused.split('value="group:Food"')[1].split("</fieldset>")[0]
    assert "That answer did not work: this question needs an answer" in food
    assert tree(home) == before


def test_a_valid_submission_writes_what_hfk_init_answers_writes(tmp_path: Path) -> None:
    home = setup_folder(tmp_path)
    before = tree(home)
    workbook = home / "data" / WORKBOOK
    workbook_bytes = workbook.read_bytes()
    with running(home) as port:
        status, headers, _page = answer_everything(port)
        doctor = get(port, headers.get("Location", "/doctor")[len(PREFIX):])[2]
    assert status == 303
    assert headers["Location"] == f"{PREFIX}/doctor"
    assert "doctor:" in doctor and "Set up hfk" not in doctor

    answers_path = tmp_path / "answers.yaml"
    answers_path.write_text(yaml.safe_dump(ANSWERS, sort_keys=False), encoding="utf-8")
    expected = run_interview(workbook, answers=load_answers(answers_path), ask=None)
    for name in ("household.yaml", "declarations.yaml"):
        assert (home / name).read_text(encoding="utf-8") == expected.documents[name], name

    after = tree(home)
    added = set(after) - set(before)
    assert added == set(SETTINGS) | ({"out/hfk-plan-starter.csv"} if expected.starter_plan else set())
    assert {name: after[name] for name in before} == before  # no launcher, hook or file changed
    assert not (home / ".git").exists()
    assert workbook.read_bytes() == workbook_bytes


def test_the_same_answers_as_hfk_init_answers_in_a_terminal_folder(tmp_path: Path) -> None:
    """The settings match a whole hfk init --answers run, not only run_interview."""

    home = setup_folder(tmp_path)
    with running(home) as port:
        assert answer_everything(port)[0] == 303
    other = tmp_path / "other"
    result = run_interview(home / "data" / WORKBOOK, answers=ANSWERS, ask=None)
    write_instance(other, documents=result.documents, starter_plan=result.starter_plan)
    for name in SETTINGS:
        assert (home / name).read_bytes() == (other / name).read_bytes(), name


def test_two_concurrent_submissions_leave_one_complete_set_of_settings(tmp_path: Path) -> None:
    home = setup_folder(tmp_path)
    with running(home) as port:
        _status, _headers, page = get(port, "/")
        for _round in range(6):
            fields = fill(page)
            asked = [value for name, value in fields if name == "asked"]
            if any(key.startswith("group:") for key in asked) and "history_start" in asked:
                break
            page = post_form(port, fields)[2]
        # Answer the overrides round too, so the next submission is the last.
        status, _headers, last = post_form(port, fields)
        final = fill(last) if status == 200 else fields
        results: list[int] = []
        barrier = threading.Barrier(4)

        def submit() -> None:
            barrier.wait()
            results.append(post_form(port, final)[0])

        threads = [threading.Thread(target=submit) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
    assert sorted(results).count(303) == 1, results
    assert all(code in (303, 409) for code in results), results
    for name in SETTINGS:
        assert (home / name).is_file() and (home / name).stat().st_size > 0
    assert not list(home.rglob("*.hfk-tmp"))
    assert yaml.safe_load((home / "household.yaml").read_text(encoding="utf-8"))["people"]


def test_every_settings_write_is_refused_once_household_yaml_exists(tmp_path: Path) -> None:
    home = setup_folder(tmp_path)
    with running(home) as port:
        assert answer_everything(port)[0] == 303
        before = tree(home)
        fields = [("asked", "people"), ("q:people", "Pat")]
        status, _headers, page = post_form(port, fields)
        redirect = get(port, "/setup")
    assert status == 409
    assert "already set up" in page
    assert redirect[0] == 303
    assert tree(home) == before


def test_requests_without_the_token_are_refused(tmp_path: Path) -> None:
    home = setup_folder(tmp_path)
    before = tree(home)
    with running(home) as port:
        results = [
            send(port, "GET", "/", origin=None)[0],
            send(port, "GET", "/setup", origin=None)[0],
            send(port, "GET", "/other-token/", origin=None)[0],
            send(port, "GET", f"{PREFIX}x/", origin=None)[0],
            send(port, "POST", "/setup", body=b"asked=people&q%3Apeople=Pat",
                 headers={"Content-Type": "application/x-www-form-urlencoded"})[0],
            send(port, "POST", "/other-token/workbook", body=b"x")[0],
        ]
    assert results == [404] * len(results)
    assert tree(home) == before


@pytest.mark.parametrize(
    "origin", [None, "null", "http://attacker.example", "http://localhost:1", "https://127.0.0.1"]
)
def test_writes_without_this_servers_origin_are_refused(tmp_path: Path, origin: str | None) -> None:
    home = setup_folder(tmp_path, workbook=False)
    before = tree(home)
    source = tmp_path / WORKBOOK
    build_fixture(source)
    with running(home) as port:
        form = post_form(port, [("asked", "people"), ("q:people", "Pat")], origin=origin)
        copy = post_workbook(port, WORKBOOK, source.read_bytes(), origin=origin)
    assert form[0] == 403 and copy[0] == 403
    assert tree(home) == before


def test_a_request_over_the_size_limit_is_refused(tmp_path: Path) -> None:
    home = setup_folder(tmp_path)
    before = tree(home)
    with running(home) as port:
        status = post_form(port, [("asked", "people"), ("q:people", "A" * FORM_LIMIT)])[0]
        missing = send(port, "POST", f"{PREFIX}/setup", headers={"Content-Length": "x"})[0]
    assert status == 413
    assert missing == 411
    assert tree(home) == before


def test_get_cannot_write_and_other_paths_cannot_be_posted(tmp_path: Path) -> None:
    home = setup_folder(tmp_path)
    before = tree(home)
    with running(home) as port:
        query = urlencode({"asked": "people", "q:people": "Pat"})
        got = get(port, f"/setup?{query}")[0]
        posted = send(port, "POST", f"{PREFIX}/scorecard", body=b"")[0]
    assert got == 200 and posted == 405
    assert tree(home) == before


def test_the_workbook_copy_writes_one_xlsx_into_data_and_nothing_else(tmp_path: Path) -> None:
    home = setup_folder(tmp_path, workbook=False)
    source = tmp_path / "download" / "Alex Tiller Spreadsheet - 2026-09-01.xlsx"
    build_fixture(source)
    source_bytes = source.read_bytes()
    before = tree(home)
    with running(home) as port:
        status, headers, _body = post_workbook(port, source.name, source_bytes)
        _status, _headers, page = get(port, "/")
    after = tree(home)
    assert status == 303 and headers["Location"] == f"{PREFIX}/setup"
    assert set(after) - set(before) == {f"data{os.sep}{source.name}"}
    assert {name: after[name] for name in before} == before
    assert (home / "data" / source.name).read_bytes() == source_bytes
    assert source.read_bytes() == source_bytes
    assert f"hfk will read <strong>{source.name}</strong>" in page


def test_a_new_download_replaces_only_the_file_of_the_same_name(tmp_path: Path) -> None:
    home = setup_folder(tmp_path)
    keep = home / "data" / "Tiller-Older.xlsx"
    shutil.copyfile(home / "data" / WORKBOOK, keep)
    keep_bytes = keep.read_bytes()
    replacement = tmp_path / WORKBOOK
    build_fixture(replacement, months=3)
    assert replacement.read_bytes() != (home / "data" / WORKBOOK).read_bytes()
    with running(home) as port:
        status = post_workbook(port, WORKBOOK, replacement.read_bytes())[0]
    assert status == 303
    assert (home / "data" / WORKBOOK).read_bytes() == replacement.read_bytes()
    assert keep.read_bytes() == keep_bytes
    assert sorted(path.name for path in (home / "data").iterdir()) == sorted(["Tiller-Older.xlsx", WORKBOOK])


@pytest.mark.parametrize(
    ("filename", "data", "words"),
    [
        ("Budget.xlsx", None, "starts with Tiller"),
        ("Tiller-Example.csv", None, "not an Excel workbook"),
        ("../Tiller-Escape.xlsx", None, None),
        ("Tiller-Fake.xlsx", b"not a zip file", "not an Excel workbook"),
        ("", None, "no file was chosen"),
    ],
)
def test_a_copy_that_is_not_a_tiller_workbook_is_refused(
    tmp_path: Path, filename: str, data: bytes | None, words: str | None
) -> None:
    home = setup_folder(tmp_path, workbook=False)
    source = tmp_path / "download.xlsx"
    build_fixture(source)
    before = tree(home)
    with running(home) as port:
        status, _headers, page = post_workbook(port, filename, source.read_bytes() if data is None else data)
    if words is None:  # a path is cut to its file name, which stays inside data/
        assert status == 303
        assert set(tree(home)) - set(before) == {f"data{os.sep}Tiller-Escape.xlsx"}
        assert not (tmp_path / "Tiller-Escape.xlsx").exists()
        return
    assert status == 400
    assert words in page
    assert tree(home) == before


def test_report_pages_offer_the_workbook_copy_and_name_the_workbook_read(tmp_path: Path) -> None:
    home = setup_folder(tmp_path)
    with running(home) as port:
        assert answer_everything(port)[0] == 303
        shutil.copyfile(home / "data" / WORKBOOK, home / "data" / "Tiller-Older.xlsx")
        os.utime(home / "data" / "Tiller-Older.xlsx", (0, 0))
        pages = {name: get(port, f"/{name}?month=2026-08")[2] for name in ("scorecard", "doctor")}
        status, headers, _body = post_workbook(
            port, WORKBOOK, (home / "data" / WORKBOOK).read_bytes(), back="/doctor?month=2026-08"
        )
    for name, page in pages.items():
        assert f'action="{PREFIX}/workbook"' in page, name
        assert f"Read {WORKBOOK}, the newest workbook in data; also there: Tiller-Older.xlsx" in page
        assert "<script" not in page
    assert status == 303 and headers["Location"] == f"{PREFIX}/doctor?month=2026-08"


def test_a_copy_cannot_redirect_off_this_server(tmp_path: Path) -> None:
    home = setup_folder(tmp_path)
    with running(home) as port:
        status, headers, _body = post_workbook(
            port, WORKBOOK, (home / "data" / WORKBOOK).read_bytes(), back="//attacker.example/"
        )
    assert status == 303
    assert headers["Location"] == f"{PREFIX}/"


def test_every_page_works_with_scripts_turned_off(tmp_path: Path) -> None:
    """Each form posts with a plain submit button; the script only adds conveniences."""

    home = setup_folder(tmp_path)
    with running(home) as port:
        _status, _headers, page = get(port, "/")
    assert page.count("<script") == 1
    for form in re.findall(r"<form .*?</form>", page, flags=re.DOTALL):
        assert '<button type="submit">' in form
        assert 'method="post"' in form
    assert "<noscript" not in page


def test_pages_let_the_browser_send_its_origin_on_the_pages_own_forms(tmp_path: Path) -> None:
    """With Referrer-Policy no-referrer, browsers send "Origin: null" and every form fails."""

    home = setup_folder(tmp_path)
    with running(home) as port:
        _status, headers, _page = get(port, "/")
    assert headers["Referrer-Policy"] == "same-origin"


def test_typed_shares_count_when_no_owner_choice_is_picked(tmp_path: Path) -> None:
    home = setup_folder(tmp_path)
    with running(home) as port:
        _status, _headers, page = get(port, "/")
        page = post_form(port, fill(page))[2]
        fields = [
            (name, value)
            for name, value in fill(page)
            if name not in ("q:account:Savings", "q:account:Savings:other")
        ]
        fields.append(("q:account:Savings:other", "Alex 60, Sam 40"))
        page = post_form(port, fields)[2]
    savings = page.split('value="account:Savings"')[1].split("</fieldset>")[0]
    assert "did not work" not in savings
    assert 'value="Alex 60, Sam 40"' in savings
