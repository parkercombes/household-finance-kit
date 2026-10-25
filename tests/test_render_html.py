"""HTML renderer tests (M5-05)."""

from __future__ import annotations

import csv
import dataclasses
import io
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from hfk.config import Month, load_declarations, load_household, load_plan
from hfk.engine import (
    build_balances,
    build_categories,
    build_networth,
    build_renewals,
    build_scorecard,
)
from hfk.engine.balances import BalancesReport
from hfk.engine.categories import CategoriesReport
from hfk.engine.networth import NetWorthReport
from hfk.engine.renewals import RenewalsReport
from hfk.engine.scorecard import Scorecard
from hfk.render import (
    HTML_RENDERERS,
    money,
    register_html_renderer,
    render_balances_html,
    render_categories_html,
    render_csv,
    render_html,
    render_networth_html,
    render_renewals_html,
    render_scorecard_html,
    render_text,
)
from hfk.source import find_workbook, read_tiller
from hfk.source.fixture import build_fixture

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
PYTHONPATH = str(ROOT / "src")
SNAPSHOTS = ROOT / "tests" / "snapshots" / "html"
CSV_SNAPSHOTS = ROOT / "tests" / "snapshots" / "csv"
TEXT_SNAPSHOTS = ROOT / "tests" / "snapshots" / "text"

SNAPSHOT_COMMANDS = (
    (
        "scorecard-2026-08-alex.html",
        "scorecard-2026-08-alex.csv.txt",
        "scorecard-2026-08-alex.txt",
        ("scorecard", "--month", "2026-08", "--who", "alex", "--today", "2026-09-15"),
    ),
    (
        "categories-2026-08-alex.html",
        "categories-2026-08-alex.csv.txt",
        "categories-2026-08-alex.txt",
        ("categories", "--month", "2026-08", "--who", "alex", "--today", "2026-09-15"),
    ),
    (
        "categories-2026-09-alex-paced.html",
        "categories-2026-09-alex-paced.csv.txt",
        "categories-2026-09-alex-paced.txt",
        ("categories", "--month", "2026-09", "--who", "alex", "--today", "2026-09-15"),
    ),
    (
        "balances-2026-09-30.html",
        "balances-2026-09-30.csv.txt",
        "balances-2026-09-30.txt",
        ("balances", "--as-of", "2026-09-30"),
    ),
    (
        "networth-2026-09-30.html",
        "networth-2026-09-30.csv.txt",
        "networth-2026-09-30.txt",
        ("networth", "--as-of", "2026-09-30"),
    ),
    (
        "renewals-2026-09.html",
        "renewals-2026-09.csv.txt",
        "renewals-2026-09.txt",
        ("renewals", "--month", "2026-09"),
    ),
)


def make_instance(tmp_path: Path, **fixture_kwargs: Any) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    for filename in ("household.yaml", "declarations.yaml", "plan.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, tmp_path / filename)
    build_fixture(tmp_path / "data" / "Tiller-Example.xlsx", **fixture_kwargs)
    return tmp_path


def run_hfk(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH
    return subprocess.run(
        [sys.executable, "-m", "hfk", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def snapshot(name: str) -> str:
    return (SNAPSHOTS / name).read_text(encoding="utf-8")


def csv_snapshot(name: str) -> str:
    return (CSV_SNAPSHOTS / name).read_text(encoding="utf-8")


def text_snapshot(name: str) -> str:
    return (TEXT_SNAPSHOTS / name).read_text(encoding="utf-8")


def load_loaded_instance(home: Path):
    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    plan = load_plan(home, declarations=declarations, people=household.slugs)
    ledger = read_tiller(find_workbook(home / "data", household.tiller_glob))
    return household, declarations, plan, ledger


def build_all_reports(home: Path):
    household, declarations, plan, ledger = load_loaded_instance(home)
    scorecard = build_scorecard(
        ledger=ledger,
        household=household,
        declarations=declarations,
        plan=plan,
        month=Month(2026, 8),
        who="alex",
        today=date(2026, 9, 15),
    )
    categories = build_categories(
        ledger=ledger,
        household=household,
        declarations=declarations,
        plan=plan,
        month=Month(2026, 8),
        who="alex",
        today=date(2026, 9, 15),
    )
    balances = build_balances(
        ledger=ledger,
        household=household,
        declarations=declarations,
        as_of=date(2026, 9, 30),
    )
    networth = build_networth(
        ledger=ledger,
        household=household,
        declarations=declarations,
        as_of=date(2026, 9, 30),
        stale_after_days=14,
    )
    renewals = build_renewals(
        plan=plan,
        household=household,
        month=Month(2026, 9),
        who=None,
    )
    return household, scorecard, categories, balances, networth, renewals


def parse_page(page: str) -> ET.Element:
    return ET.fromstring(page.split("\n", 1)[1])


def totals_dict(page_root: ET.Element) -> dict[str, str]:
    dl = page_root.find("body/dl")
    labels = [dt.text for dt in dl.findall("dt")]
    values = [dd.text for dd in dl.findall("dd")]
    return dict(zip(labels, values, strict=True))


def test_scorecard_html_matches_snapshot(tmp_path):
    home = make_instance(tmp_path)
    _household, scorecard, *_ = build_all_reports(home)
    assert render_scorecard_html(scorecard) == snapshot("scorecard-2026-08-alex.html")


def test_categories_html_matches_snapshots(tmp_path):
    home = make_instance(tmp_path)
    household, declarations, plan, ledger = load_loaded_instance(home)
    for month, name in (
        (Month(2026, 8), "categories-2026-08-alex.html"),
        (Month(2026, 9), "categories-2026-09-alex-paced.html"),
    ):
        report = build_categories(
            ledger=ledger,
            household=household,
            declarations=declarations,
            plan=plan,
            month=month,
            who="alex",
            today=date(2026, 9, 15),
        )
        assert render_categories_html(report) == snapshot(name)


def test_balances_html_matches_snapshot(tmp_path):
    home = make_instance(tmp_path)
    household, _scorecard, _categories, balances, _networth, _renewals = build_all_reports(home)
    assert (
        render_balances_html(balances, history_start=household.history_start)
        == snapshot("balances-2026-09-30.html")
    )


def test_networth_html_matches_snapshot(tmp_path):
    home = make_instance(tmp_path)
    household, _scorecard, _categories, _balances, networth, _renewals = build_all_reports(home)
    assert (
        render_networth_html(networth, history_start=household.history_start)
        == snapshot("networth-2026-09-30.html")
    )


def test_renewals_html_matches_snapshot(tmp_path):
    home = make_instance(tmp_path)
    _household, _scorecard, _categories, _balances, _networth, renewals = build_all_reports(home)
    assert render_renewals_html(renewals) == snapshot("renewals-2026-09.html")


def test_cli_format_html_prints_exactly_the_html_render(tmp_path):
    home = make_instance(tmp_path)
    for html_name, _csv_name, _text_name, args in SNAPSHOT_COMMANDS:
        result = run_hfk(*args, "--home", str(home), "--format", "html")
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        assert result.stdout == snapshot(html_name)


def test_cli_text_and_csv_formats_are_unchanged(tmp_path):
    home = make_instance(tmp_path)
    for _html_name, csv_name, text_name, args in SNAPSHOT_COMMANDS:
        default_result = run_hfk(*args, "--home", str(home))
        assert default_result.returncode == 0, default_result.stderr
        assert default_result.stderr == ""
        assert default_result.stdout == text_snapshot(text_name)
        text_result = run_hfk(*args, "--home", str(home), "--format", "text")
        assert text_result.returncode == 0, text_result.stderr
        assert text_result.stdout == text_snapshot(text_name)
        csv_result = run_hfk(*args, "--home", str(home), "--format", "csv")
        assert csv_result.returncode == 0, csv_result.stderr
        assert csv_result.stdout == csv_snapshot(csv_name)
    rejected = run_hfk(
        "scorecard", "--month", "2026-08", "--who", "alex",
        "--home", str(home), "--format", "xml",
    )
    assert rejected.returncode == 2
    assert "html" in rejected.stderr


def test_html_contains_the_same_totals_as_text_and_csv(tmp_path):
    home = make_instance(tmp_path)
    household, scorecard, categories, balances, networth, renewals = build_all_reports(home)
    history = household.history_start
    cases = (
        (scorecard, render_scorecard_html(scorecard), render_text(scorecard), render_csv(scorecard)),
        (
            categories,
            render_categories_html(categories),
            render_text(categories),
            render_csv(categories),
        ),
        (
            balances,
            render_balances_html(balances, history_start=history),
            render_text(balances, history_start=history),
            render_csv(balances),
        ),
        (
            networth,
            render_networth_html(networth, history_start=history),
            render_text(networth, history_start=history),
            render_csv(networth),
        ),
        (renewals, render_renewals_html(renewals), render_text(renewals), render_csv(renewals)),
    )
    for report, page, text, csv_text in cases:
        root = parse_page(page)

        # (a) the h1 carries the text report's first line.
        assert root.find("body/h1").text == text.split("\n", 1)[0]

        # (b) every money value in the text render appears in the page.
        for value in re.findall(r"-?\d+\.\d\d", text):
            assert value in page

        # (c) the main table mirrors the CSV table cell for cell.
        csv_rows = list(csv.reader(io.StringIO(csv_text)))
        names = csv_rows[0]
        table = root.find("body/table")
        header_cells = [th.text for th in table.findall("thead/tr/th")]
        assert header_cells == [name.replace("_", " ") for name in names]
        body_rows = table.findall("tbody/tr")
        assert len(body_rows) == len(csv_rows) - 1
        for row, data_row in zip(body_rows, csv_rows[1:], strict=True):
            assert [td.text or "" for td in row.findall("td")] == data_row

        # (d) the totals dl mirrors the text report's summary lines.
        totals = totals_dict(root)
        if isinstance(report, Scorecard):
            assert totals["total plan"] == money(report.planned_total)
            assert totals["total actual"] == money(report.actual_total)
            assert totals["total left"] == money(report.planned_total - report.actual_total)
        elif isinstance(report, CategoriesReport):
            assert totals["total target"] == money(report.target_total)
            assert totals["total actual"] == money(report.actual_total)
            assert totals["total left"] == money(report.target_total - report.actual_total)
        elif isinstance(report, BalancesReport):
            assert totals["accounts"] == str(len(report.accounts))
            assert totals["gaps"] == str(report.gap_count)
        elif isinstance(report, NetWorthReport):
            assert totals["assets"] == money(report.assets)
            assert totals["liabilities"] == money(report.liabilities)
            assert totals["net worth"] == money(report.net_worth)
            assert totals["counted"] == f"{report.counted} of {len(report.lines)}"
            assert totals["excluded"] == str(len(report.excluded))
        elif isinstance(report, RenewalsReport):
            assert totals["set-aside monthly"] == money(report.set_aside_monthly)
            assert totals["accrued"] == money(report.accrued_total)
            assert totals["shortfall"] == money(report.shortfall_total)
            assert totals["adequacy"] == "ok"


def test_html_is_static_and_self_contained(tmp_path):
    home = make_instance(tmp_path)
    household, scorecard, categories, balances, networth, renewals = build_all_reports(home)
    pages = (
        render_scorecard_html(scorecard),
        render_categories_html(categories),
        render_balances_html(balances, history_start=household.history_start),
        render_networth_html(networth, history_start=household.history_start),
        render_renewals_html(renewals),
    )
    forbidden = (
        "<script",
        "<link",
        "<iframe",
        "http://",
        "https://",
        "url(",
        "@import",
        "src=",
        "onclick",
        "javascript:",
    )
    for page in pages:
        assert page.startswith("<!DOCTYPE html>\n")
        assert page.endswith("</html>\n")
        ET.fromstring(page.split("\n", 1)[1])
        assert page.count("<style") == 1
        assert '<meta charset="utf-8"' in page
        lower = page.lower()
        for marker in forbidden:
            assert marker not in lower


def test_html_escapes_cell_text(tmp_path):
    home = make_instance(tmp_path)
    _household, scorecard, *_ = build_all_reports(home)
    renamed = dataclasses.replace(
        scorecard,
        buckets=(
            dataclasses.replace(scorecard.buckets[0], bucket='<b>&"odd"</b>'),
            *scorecard.buckets[1:],
        ),
    )
    page = render_scorecard_html(renamed)
    assert "&lt;b&gt;&amp;&quot;odd&quot;&lt;/b&gt;" in page
    assert "<b>" not in page.split("<body>", 1)[1]
    ET.fromstring(page.split("\n", 1)[1])


def test_empty_reports_render_headers_and_totals(tmp_path):
    home = make_instance(tmp_path)
    _household, scorecard, categories, _balances, _networth, renewals = build_all_reports(home)

    empty_scorecard = dataclasses.replace(
        scorecard,
        buckets=(),
        planned_total=Decimal("0.00"),
        actual_total=Decimal("0.00"),
    )
    page = render_scorecard_html(empty_scorecard)
    root = parse_page(page)
    assert root.find("body/table/tbody").findall("tr") == []
    assert totals_dict(root)["total plan"] == "0.00"

    empty_categories = dataclasses.replace(
        categories,
        lines=(),
        target_total=Decimal("0.00"),
        actual_total=Decimal("0.00"),
    )
    page = render_categories_html(empty_categories)
    root = parse_page(page)
    assert root.find("body/table/tbody").findall("tr") == []
    assert (
        f"no plan lines with categories for {categories.who} in {categories.month}" in page
    )
    assert totals_dict(root)["total target"] == "0.00"

    empty_renewals = dataclasses.replace(
        renewals,
        renewals=(),
        schedule=(),
        set_aside_monthly=Decimal("0.00"),
        accrued_total=Decimal("0.00"),
        shortfall_total=Decimal("0.00"),
    )
    page = render_renewals_html(empty_renewals)
    root = parse_page(page)
    assert len(root.findall("body/table")) == 1
    assert root.find("body/table/tbody").findall("tr") == []
    assert "schedule: nothing due in the next 12 months" in page
    assert totals_dict(root)["adequacy"] == "ok"


def test_render_html_dispatches_and_refuses_unknown(tmp_path):
    home = make_instance(tmp_path)
    household, scorecard, _categories, balances, _networth, _renewals = build_all_reports(home)
    assert render_html(scorecard) == render_scorecard_html(scorecard)
    assert (
        render_html(balances, history_start=household.history_start)
        == render_balances_html(balances, history_start=household.history_start)
    )
    with pytest.raises(TypeError, match="object"):
        render_html(object())

    @dataclasses.dataclass(frozen=True)
    class Custom:
        pass

    try:
        register_html_renderer(Custom, lambda report, **options: "<p>custom</p>\n")
        assert render_html(Custom()) == "<p>custom</p>\n"
    finally:
        HTML_RENDERERS.pop(Custom)


def test_html_renderers_never_print(tmp_path, capsys):
    home = make_instance(tmp_path)
    household, scorecard, categories, balances, networth, renewals = build_all_reports(home)
    render_scorecard_html(scorecard)
    render_categories_html(categories)
    render_balances_html(balances, history_start=household.history_start)
    render_networth_html(networth, history_start=household.history_start)
    render_renewals_html(renewals)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
