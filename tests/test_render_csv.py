"""CSV renderer tests (M5-04)."""

from __future__ import annotations

import csv
import dataclasses
import io
import os
import shutil
import subprocess
import sys
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
from hfk.engine.balances import AccountBalance
from hfk.engine.categories import CategoryLine
from hfk.engine.networth import NetWorthLine
from hfk.engine.renewals import Renewal
from hfk.engine.scorecard import BucketScore
from hfk.render import (
    CSV_RENDERERS,
    money,
    register_csv_renderer,
    render_balances_csv,
    render_categories_csv,
    render_csv,
    render_networth_csv,
    render_renewals_csv,
    render_scorecard_csv,
)
from hfk.source import find_workbook, read_tiller
from hfk.source.fixture import build_fixture

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
PYTHONPATH = str(ROOT / "src")
SNAPSHOTS = ROOT / "tests" / "snapshots" / "csv"
TEXT_SNAPSHOTS = ROOT / "tests" / "snapshots" / "text"

SNAPSHOT_COMMANDS = (
    (
        "scorecard-2026-08-alex.csv.txt",
        "scorecard-2026-08-alex.txt",
        ("scorecard", "--month", "2026-08", "--who", "alex", "--today", "2026-09-15"),
    ),
    (
        "categories-2026-08-alex.csv.txt",
        "categories-2026-08-alex.txt",
        ("categories", "--month", "2026-08", "--who", "alex", "--today", "2026-09-15"),
    ),
    (
        "categories-2026-09-alex-paced.csv.txt",
        "categories-2026-09-alex-paced.txt",
        ("categories", "--month", "2026-09", "--who", "alex", "--today", "2026-09-15"),
    ),
    (
        "balances-2026-09-30.csv.txt",
        "balances-2026-09-30.txt",
        ("balances", "--as-of", "2026-09-30"),
    ),
    (
        "networth-2026-09-30.csv.txt",
        "networth-2026-09-30.txt",
        ("networth", "--as-of", "2026-09-30"),
    ),
    (
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


def parse_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def _cell_rules(value: object) -> str:
    """Reimplementation of the renderer's boundary formatting rules."""
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


def test_scorecard_csv_matches_snapshot(tmp_path):
    home = make_instance(tmp_path)
    _household, scorecard, *_ = build_all_reports(home)
    assert render_scorecard_csv(scorecard) == snapshot("scorecard-2026-08-alex.csv.txt")


def test_categories_csv_matches_snapshots(tmp_path):
    home = make_instance(tmp_path)
    household, declarations, plan, ledger = load_loaded_instance(home)
    for month, name in (
        (Month(2026, 8), "categories-2026-08-alex.csv.txt"),
        (Month(2026, 9), "categories-2026-09-alex-paced.csv.txt"),
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
        assert render_categories_csv(report) == snapshot(name)


def test_balances_csv_matches_snapshot(tmp_path):
    home = make_instance(tmp_path)
    _household, _scorecard, _categories, balances, _networth, _renewals = build_all_reports(home)
    assert render_balances_csv(balances) == snapshot("balances-2026-09-30.csv.txt")


def test_networth_csv_matches_snapshot(tmp_path):
    home = make_instance(tmp_path)
    _household, _scorecard, _categories, _balances, networth, _renewals = build_all_reports(home)
    assert render_networth_csv(networth) == snapshot("networth-2026-09-30.csv.txt")


def test_renewals_csv_matches_snapshot(tmp_path):
    home = make_instance(tmp_path)
    _household, _scorecard, _categories, _balances, _networth, renewals = build_all_reports(home)
    assert render_renewals_csv(renewals) == snapshot("renewals-2026-09.csv.txt")


def test_cli_format_csv_prints_exactly_the_csv_render(tmp_path):
    home = make_instance(tmp_path)
    for csv_name, _text_name, args in SNAPSHOT_COMMANDS:
        result = run_hfk(*args, "--home", str(home), "--format", "csv")
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        assert result.stdout == snapshot(csv_name)


def test_cli_default_format_is_unchanged_text(tmp_path):
    home = make_instance(tmp_path)
    for _csv_name, text_name, args in SNAPSHOT_COMMANDS:
        default_result = run_hfk(*args, "--home", str(home))
        assert default_result.returncode == 0, default_result.stderr
        assert default_result.stdout == text_snapshot(text_name)
        text_result = run_hfk(*args, "--home", str(home), "--format", "text")
        assert text_result.returncode == 0, text_result.stderr
        assert text_result.stdout == text_snapshot(text_name)
    rejected = run_hfk(
        "scorecard", "--month", "2026-08", "--who", "alex",
        "--home", str(home), "--format", "xml",
    )
    assert rejected.returncode == 2
    assert "csv" in rejected.stderr


def test_csv_rows_mirror_engine_objects(tmp_path):
    home = make_instance(tmp_path)
    _household, scorecard, categories, balances, networth, renewals = build_all_reports(home)
    cases = (
        (scorecard, render_scorecard_csv(scorecard), scorecard.buckets, BucketScore),
        (categories, render_categories_csv(categories), categories.lines, CategoryLine),
        (balances, render_balances_csv(balances), balances.accounts, AccountBalance),
        (networth, render_networth_csv(networth), networth.lines, NetWorthLine),
        (renewals, render_renewals_csv(renewals), renewals.renewals, Renewal),
    )
    for _report, text, rows, row_type in cases:
        parsed = parse_csv(text)
        names = [field.name for field in dataclasses.fields(row_type)]
        assert parsed[0] == names
        assert len(parsed) - 1 == len(rows)
        for item, data_row in zip(rows, parsed[1:], strict=True):
            assert data_row == [_cell_rules(getattr(item, name)) for name in names]


def test_csv_has_no_totals_rows(tmp_path):
    home = make_instance(tmp_path)
    reports = build_all_reports(home)
    renderers = (
        render_scorecard_csv,
        render_categories_csv,
        render_balances_csv,
        render_networth_csv,
        render_renewals_csv,
    )
    forbidden_first_cells = {"total", "totals", "assets", "liabilities", "net worth"}
    forbidden_strings = ("planned_total", "actual_total", "target_total", "set_aside_monthly")
    for report, renderer in zip(reports[1:], renderers, strict=True):
        text = renderer(report)
        for forbidden in forbidden_strings:
            assert forbidden not in text
        for data_row in parse_csv(text)[1:]:
            assert data_row[0].lower() not in forbidden_first_cells


def test_csv_cells_format_at_the_boundary(tmp_path):
    home = make_instance(tmp_path)
    _household, scorecard, _categories, balances, _networth, renewals = build_all_reports(home)

    balances_rows = parse_csv(render_balances_csv(balances))[1:]
    fields = [field.name for field in dataclasses.fields(AccountBalance)]
    observed_index = fields.index("observed")
    balance_index = fields.index("balance")
    gap_index = fields.index("gap")
    closed_index = fields.index("closed")
    for row, item in zip(balances_rows, balances.accounts, strict=True):
        if item.balance is not None:
            assert row[balance_index] == money(item.balance)
        else:
            assert row[balance_index] == ""
        if item.observed is not None:
            assert row[observed_index] == item.observed.isoformat()
        assert row[gap_index] in ("true", "false")
        if item.closed is None:
            assert row[closed_index] == ""
        else:
            assert row[closed_index] == item.closed.isoformat()

    renewed = dataclasses.replace(renewals.renewals[0], due=(3, 15))
    renewed_report = dataclasses.replace(renewals, renewals=(renewed,))
    renewed_rows = parse_csv(render_renewals_csv(renewed_report))[1:]
    renewed_fields = [field.name for field in dataclasses.fields(Renewal)]
    assert renewed_rows[0][renewed_fields.index("due")] == "03-15"

    quoted_scorecard = dataclasses.replace(
        scorecard,
        buckets=(
            dataclasses.replace(
                scorecard.buckets[0], bucket='odd, "bucket"'
            ),
        ),
    )
    quoted_rows = parse_csv(render_scorecard_csv(quoted_scorecard))
    assert quoted_rows[1][0] == 'odd, "bucket"'


def test_empty_reports_render_header_only(tmp_path):
    home = make_instance(tmp_path)
    _household, scorecard, categories, _balances, _networth, renewals = build_all_reports(home)

    empty_scorecard = dataclasses.replace(
        scorecard,
        buckets=(),
        planned_total=Decimal(0),
        actual_total=Decimal(0),
    )
    assert render_scorecard_csv(empty_scorecard) == (
        "bucket,essential,fixed,planned,actual,variance\n"
    )

    empty_categories = dataclasses.replace(categories, lines=())
    assert render_categories_csv(empty_categories) == (
        "desc,bucket,categories,paced,monthly,target,actual,variance\n"
    )

    empty_renewals = dataclasses.replace(renewals, renewals=(), schedule=())
    assert render_renewals_csv(empty_renewals) == (
        "desc,who,bucket,account,annual_bill,annual_full,monthly,due,"
        "next_due,accrued_months,accrued,months_to_due,projected,shortfall,flags\n"
    )


def test_render_csv_dispatches_and_refuses_unknown(tmp_path):
    home = make_instance(tmp_path)
    household, scorecard, _categories, balances, _networth, _renewals = build_all_reports(home)
    assert render_csv(scorecard) == render_scorecard_csv(scorecard)
    assert (
        render_csv(balances, history_start=household.history_start)
        == render_balances_csv(balances)
    )
    with pytest.raises(TypeError, match="object"):
        render_csv(object())

    @dataclasses.dataclass(frozen=True)
    class Custom:
        pass

    try:
        register_csv_renderer(Custom, lambda report, **options: "a,b\n1,2\n")
        assert render_csv(Custom()) == "a,b\n1,2\n"
    finally:
        CSV_RENDERERS.pop(Custom)


def test_csv_renderers_never_print(tmp_path, capsys):
    home = make_instance(tmp_path)
    _household, scorecard, categories, balances, networth, renewals = build_all_reports(home)
    render_scorecard_csv(scorecard)
    render_categories_csv(categories)
    render_balances_csv(balances)
    render_networth_csv(networth)
    render_renewals_csv(renewals)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
