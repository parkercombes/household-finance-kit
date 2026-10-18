"""Text renderer tests (M5-03)."""

from __future__ import annotations

import dataclasses
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
from hfk.render import (
    TEXT_RENDERERS,
    money,
    register_text_renderer,
    render_balances,
    render_categories,
    render_networth,
    render_renewals,
    render_scorecard,
    render_text,
)
from hfk.source import find_workbook, read_tiller
from hfk.source.fixture import build_fixture

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
PYTHONPATH = str(ROOT / "src")
SNAPSHOTS = ROOT / "tests" / "snapshots" / "text"

SNAPSHOT_COMMANDS = (
    ("scorecard-2026-08-alex.txt", ("scorecard", "--month", "2026-08", "--who", "alex", "--today", "2026-09-15")),
    ("categories-2026-08-alex.txt", ("categories", "--month", "2026-08", "--who", "alex", "--today", "2026-09-15")),
    (
        "categories-2026-09-alex-paced.txt",
        ("categories", "--month", "2026-09", "--who", "alex", "--today", "2026-09-15"),
    ),
    ("balances-2026-09-30.txt", ("balances", "--as-of", "2026-09-30")),
    ("networth-2026-09-30.txt", ("networth", "--as-of", "2026-09-30")),
    ("renewals-2026-09.txt", ("renewals", "--month", "2026-09")),
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


def load_loaded_instance(home: Path):
    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    plan = load_plan(home, declarations=declarations, people=household.slugs)
    ledger = read_tiller(find_workbook(home / "data", household.tiller_glob))
    return household, declarations, plan, ledger


def test_scorecard_text_matches_snapshot(tmp_path):
    home = make_instance(tmp_path)
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
    assert render_scorecard(scorecard) == snapshot("scorecard-2026-08-alex.txt")


def test_categories_text_matches_snapshots(tmp_path):
    home = make_instance(tmp_path)
    household, declarations, plan, ledger = load_loaded_instance(home)
    for month, name in ((Month(2026, 8), "categories-2026-08-alex.txt"), (Month(2026, 9), "categories-2026-09-alex-paced.txt")):
        report = build_categories(
            ledger=ledger,
            household=household,
            declarations=declarations,
            plan=plan,
            month=month,
            who="alex",
            today=date(2026, 9, 15),
        )
        assert render_categories(report) == snapshot(name)


def test_balances_text_matches_snapshot(tmp_path):
    home = make_instance(tmp_path)
    household, declarations, _plan, ledger = load_loaded_instance(home)
    report = build_balances(
        ledger=ledger,
        household=household,
        declarations=declarations,
        as_of=date(2026, 9, 30),
    )
    assert (
        render_balances(report, history_start=household.history_start)
        == snapshot("balances-2026-09-30.txt")
    )


def test_networth_text_matches_snapshot(tmp_path):
    home = make_instance(tmp_path)
    household, declarations, _plan, ledger = load_loaded_instance(home)
    report = build_networth(
        ledger=ledger,
        household=household,
        declarations=declarations,
        as_of=date(2026, 9, 30),
        stale_after_days=14,
    )
    assert (
        render_networth(report, history_start=household.history_start)
        == snapshot("networth-2026-09-30.txt")
    )


def test_renewals_text_matches_snapshot(tmp_path):
    home = make_instance(tmp_path)
    household, _declarations, plan, _ledger = load_loaded_instance(home)
    report = build_renewals(
        plan=plan,
        household=household,
        month=Month(2026, 9),
        who=None,
    )
    assert render_renewals(report) == snapshot("renewals-2026-09.txt")


def test_cli_prints_exactly_the_text_render(tmp_path):
    home = make_instance(tmp_path)
    for name, args in SNAPSHOT_COMMANDS:
        result = run_hfk(*args, "--home", str(home))
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        assert result.stdout == snapshot(name)


def test_snapshots_are_terminal_friendly():
    for path in sorted(SNAPSHOTS.iterdir()):
        text = path.read_text(encoding="utf-8")
        assert text
        assert text.endswith("\n")
        assert not text.endswith("\n\n")
        for line in text.splitlines():
            assert "\t" not in line
            assert line == line.rstrip()
            assert len(line) <= 120


def test_categories_without_lines_says_so(tmp_path):
    home = make_instance(tmp_path)
    household, declarations, plan, ledger = load_loaded_instance(home)
    report = build_categories(
        ledger=ledger,
        household=household,
        declarations=declarations,
        plan=plan,
        month=Month(2026, 8),
        who="alex",
        today=date(2026, 9, 15),
    )
    report = dataclasses.replace(
        report,
        lines=(),
        target_total=Decimal(0),
        actual_total=Decimal(0),
    )
    assert render_categories(report) == (
        "categories 2026-08 for alex (closed month, 31 of 31 days)\n"
        "no plan lines with categories for alex in 2026-08\n"
    )


def test_renewals_without_schedule_says_so(tmp_path):
    home = make_instance(tmp_path)
    household, _declarations, plan, _ledger = load_loaded_instance(home)
    report = build_renewals(
        plan=plan,
        household=household,
        month=Month(2026, 9),
        who=None,
    )
    report = dataclasses.replace(
        report,
        renewals=(),
        schedule=(),
        set_aside_monthly=Decimal(0),
        accrued_total=Decimal(0),
        shortfall_total=Decimal(0),
        short_count=0,
    )
    text = render_renewals(report)
    assert "schedule: nothing due in the next 12 months" in text
    assert "adequacy ok" in text


def test_render_text_dispatches_and_refuses_unknown(tmp_path):
    home = make_instance(tmp_path)
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
    balances = build_balances(
        ledger=ledger,
        household=household,
        declarations=declarations,
        as_of=date(2026, 9, 30),
    )
    assert render_text(scorecard) == render_scorecard(scorecard)
    assert (
        render_text(balances, history_start=household.history_start)
        == render_balances(balances, history_start=household.history_start)
    )
    with pytest.raises(TypeError, match="object"):
        render_text(object())

    @dataclasses.dataclass(frozen=True)
    class Custom:
        pass

    try:
        register_text_renderer(Custom, lambda report, **options: "custom report\n")
        assert render_text(Custom()) == "custom report\n"
    finally:
        TEXT_RENDERERS.pop(Custom)


def test_renderers_never_print(tmp_path, capsys):
    home = make_instance(tmp_path)
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
    render_scorecard(scorecard)
    render_categories(categories)
    render_balances(balances, history_start=household.history_start)
    render_networth(networth, history_start=household.history_start)
    render_renewals(renewals)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_money_formats_cents():
    assert money(Decimal("1.5")) == "1.50"
    assert money(Decimal(-300)) == "-300.00"
    assert money(Decimal(0)) == "0.00"
