from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from openpyxl import load_workbook

from hfk.config import Month, load_declarations, load_household, load_plan
from hfk.engine import CategoriesError, build_categories
from hfk.source import find_workbook, read_tiller
from hfk.source.fixture import build_fixture

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
INSTANCE_EXAMPLE = EXAMPLES / "instance"
PYTHONPATH = str(ROOT / "src")


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


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def fixture_workbook(home: Path) -> Path:
    return next((home / "data").glob("Tiller*.xlsx"))


def append_transaction(
    home: Path,
    *,
    day: int,
    description: str,
    category: str,
    amount: Decimal,
    account: str,
) -> None:
    transaction_date = date(2026, 9, day)
    path = fixture_workbook(home)
    workbook = load_workbook(path)
    try:
        sheet = workbook["Transactions"]
        headers = [cell.value for cell in sheet[1]]
        account_id = account.lower().replace(" ", "-")
        values = {
            "Date": transaction_date,
            "Description": description,
            "Category": category,
            "Amount": amount,
            "Account": account,
            "Account #": None,
            "Institution": "Example Bank",
            "Month": date(2026, 9, 1),
            "Week": transaction_date,
            "Transaction ID": f"test-{day}-{description.lower().replace(' ', '-')}",
            "Account ID": f"acct-{account_id}",
            "Check Number": None,
            "Full Description": f"{description} example transaction",
            "Date Added": transaction_date,
            "Category Hint": category,
            "Categorized Date": transaction_date,
        }
        sheet.append([values.get(header) for header in headers])
        workbook.save(path)
    finally:
        workbook.close()


def load_categories(
    home: Path,
    who: str,
    month: str = "2026-09",
    today: date = date(2026, 10, 1),
):
    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    plan = load_plan(home, declarations=declarations, people=household.slugs)
    ledger = read_tiller(find_workbook(home / "data", household.tiller_glob))
    return build_categories(
        ledger=ledger,
        household=household,
        declarations=declarations,
        plan=plan,
        month=Month.parse(month),
        who=who,
        today=today,
    )


def by_desc(report) -> dict[str, Any]:
    return {line.desc: line for line in report.lines}


def test_categories_cli_runs_on_example_instance(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    alex = run_hfk(
        "categories",
        "--home",
        str(home),
        "--month",
        "2026-09",
        "--who",
        "alex",
        "--today",
        "2026-10-01",
    )
    sam = run_hfk(
        "categories",
        "--home",
        str(home),
        "--month",
        "2026-09",
        "--who",
        "sam",
        "--today",
        "2026-10-01",
    )

    assert alex.returncode == 0
    assert alex.stderr == ""
    assert "categories 2026-09 for alex (closed month, 30 of 30 days)" in alex.stdout
    assert (
        "Example Rent" + " " * 11 + "fixed  target 1200.00  actual 1500.00  left -300.00"
        in alex.stdout
    )
    assert "total  target 1850.00  actual 1787.50  left 62.50" in alex.stdout
    assert sam.returncode == 0
    assert sam.stderr == ""
    assert "categories 2026-09 for sam (closed month, 30 of 30 days)" in sam.stdout
    assert "total  target 230.00  actual 157.50  left 72.50" in sam.stdout


def test_paced_and_unpaced_targets_differ_mid_month(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    mid_month = date(2026, 9, 15)

    alex = load_categories(home, "alex", today=mid_month)
    sam = load_categories(home, "sam", today=mid_month)

    assert alex.closed is False
    assert alex.window_end == date(2026, 9, 15)
    assert alex.window_days == 15
    assert alex.days_in_month == 30
    alex_lines = by_desc(alex)
    assert alex_lines["Example Rent"].paced is False
    assert alex_lines["Example Rent"].monthly == Decimal("1200.00")
    assert alex_lines["Example Rent"].target == Decimal("1200.00")
    assert alex_lines["Example Rent"].actual == Decimal("1500.00")
    assert alex_lines["Example Rent"].variance == Decimal("-300.00")
    assert alex_lines["Example Utilities"].paced is True
    assert alex_lines["Example Utilities"].monthly == Decimal("90.00")
    assert alex_lines["Example Utilities"].target == Decimal("45.00")
    assert alex_lines["Example Utilities"].actual == Decimal("105.00")
    assert alex_lines["Example Utilities"].variance == Decimal("-60.00")
    assert alex_lines["Example Grocer"].target == Decimal("275.00")
    assert alex_lines["Example Grocer"].actual == Decimal("127.50")
    assert alex_lines["Example Grocer"].variance == Decimal("147.50")
    assert alex_lines["Example Cloud Renewal"].paced is False
    assert alex_lines["Example Cloud Renewal"].target == Decimal("10.00")
    assert alex_lines["Example Cloud Renewal"].actual == Decimal("0.00")

    sam_lines = by_desc(sam)
    assert sam_lines["Example Transit"].target == Decimal("40.00")
    assert sam_lines["Example Transit"].actual == Decimal("0.00")
    assert sam_lines["Example Cafe"].target == Decimal("30.00")
    assert sam_lines["Example Cafe"].actual == Decimal("22.50")
    assert sam_lines["Example Cafe"].variance == Decimal("7.50")

    result = run_hfk(
        "categories",
        "--home",
        str(home),
        "--month",
        "2026-09",
        "--who",
        "alex",
        "--today",
        "2026-09-15",
    )
    assert result.returncode == 0
    assert result.stderr == ""
    assert "categories 2026-09 for alex (through 2026-09-15, 15 of 30 days)" in result.stdout
    assert "target 45.00  actual 105.00  left -60.00" in result.stdout
    assert "total  target 1530.00  actual 1732.50  left -202.50" in result.stdout


def test_closed_month_targets_are_full(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    alex = load_categories(home, "alex")
    sam = load_categories(home, "sam")

    assert alex.closed is True
    assert alex.window_start == date(2026, 9, 1)
    assert alex.window_end == date(2026, 9, 30)
    assert alex.window_days == 30
    alex_lines = by_desc(alex)
    assert alex_lines["Example Utilities"].target == Decimal("90.00")
    assert alex_lines["Example Utilities"].actual == Decimal("105.00")
    assert alex_lines["Example Grocer"].target == Decimal("550.00")
    assert alex_lines["Example Grocer"].actual == Decimal("182.50")
    assert alex_lines["Example Rent"].target == Decimal("1200.00")
    assert alex_lines["Example Rent"].actual == Decimal("1500.00")
    assert alex_lines["Example Cloud Renewal"].target == Decimal("10.00")
    assert alex.target_total == Decimal("1850.00")
    assert alex.actual_total == Decimal("1787.50")

    sam_lines = by_desc(sam)
    assert sam_lines["Example Utilities"].target == Decimal("90.00")
    assert sam_lines["Example Cafe"].target == Decimal("60.00")
    assert sam_lines["Example Cafe"].actual == Decimal("52.50")
    assert sam_lines["Example Transit"].target == Decimal("80.00")
    assert sam_lines["Example Transit"].actual == Decimal("0.00")


def test_history_start_prorates_paced_lines(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    household_path = home / "household.yaml"
    household = load_yaml(household_path)
    household["history_start"] = "2026-09-10"
    dump_yaml(household_path, household)

    alex = load_categories(home, "alex")
    alex_lines = by_desc(alex)

    assert alex.clamped is True
    assert alex.window_start == date(2026, 9, 10)
    assert alex.window_end == date(2026, 9, 30)
    assert alex.window_days == 21
    assert alex.days_in_month == 30
    assert alex_lines["Example Utilities"].target == Decimal("63.00")
    assert alex_lines["Example Grocer"].target == Decimal("385.00")
    assert alex_lines["Example Rent"].paced is False
    assert alex_lines["Example Rent"].target == Decimal("1200.00")
    assert alex_lines["Example Cloud Renewal"].target == Decimal("10.00")
    assert alex_lines["Example Rent"].actual == Decimal("0.00")
    assert alex_lines["Example Utilities"].actual == Decimal("105.00")
    assert alex_lines["Example Grocer"].actual == Decimal("122.50")

    result = run_hfk(
        "categories",
        "--home",
        str(home),
        "--month",
        "2026-09",
        "--who",
        "alex",
        "--today",
        "2026-10-01",
    )
    assert result.returncode == 0
    assert "note: window clamped to history_start 2026-09-10" in result.stdout

    household["history_start"] = "2026-10-01"
    dump_yaml(household_path, household)
    with pytest.raises(CategoriesError, match="before history_start"):
        load_categories(home, "alex")


def test_duplicate_category_lines_stop(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    plan_path = home / "plan.yaml"
    plan = load_yaml(plan_path)
    plan["plan"]["lines"].append(
        {
            "desc": "Example Grocer Extra",
            "who": "alex",
            "bucket": "Variable Essential",
            "monthly": 50.00,
            "categories": ["Groceries"],
            "effective_from": "2025-01",
        }
    )
    dump_yaml(plan_path, plan)

    with pytest.raises(CategoriesError) as error:
        load_categories(home, "alex")
    message = str(error.value)
    assert '"Groceries"' in message
    assert '"Example Grocer"' in message
    assert '"Example Grocer Extra"' in message
    assert (
        "end one line with effective_until or remove the category from one of them"
        in message
    )

    result = run_hfk(
        "categories",
        "--home",
        str(home),
        "--month",
        "2026-09",
        "--who",
        "alex",
        "--today",
        "2026-10-01",
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("categories: ")
    assert '"Example Grocer Extra"' in result.stderr


def test_future_month_is_refused(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    with pytest.raises(CategoriesError) as error:
        load_categories(home, "alex", month="2026-10", today=date(2026, 9, 15))
    message = str(error.value)
    assert "month 2026-10 has not started (today is 2026-09-15)" in message
    assert "choose the current month or a past month" in message

    result = run_hfk(
        "categories",
        "--home",
        str(home),
        "--month",
        "2026-10",
        "--who",
        "alex",
        "--today",
        "2026-09-15",
    )
    assert result.returncode == 1
    assert "has not started" in result.stderr

    first_day = load_categories(home, "alex", month="2026-10", today=date(2026, 10, 1))
    assert first_day.closed is False
    assert first_day.window_days == 1
    assert first_day.days_in_month == 31
    assert by_desc(first_day)["Example Utilities"].target == Decimal("2.90")


def test_who_is_required_with_several_people(tmp_path: Path) -> None:
    home = make_instance(tmp_path / "two")

    result = run_hfk(
        "categories",
        "--home",
        str(home),
        "--month",
        "2026-09",
        "--today",
        "2026-10-01",
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "categories: choose --who from: alex, sam" in result.stderr

    with pytest.raises(CategoriesError) as error:
        load_categories(home, "pat")
    assert "choose one of: alex, sam" in str(error.value)

    solo = make_instance(tmp_path / "solo")
    household_path = solo / "household.yaml"
    household = load_yaml(household_path)
    household["people"] = [{"slug": "alex", "name": "Alex"}]
    household["accounts"] = {
        "Alex Checking": {"owner": "alex"},
        "Sam Checking": {"owner": "alex"},
        "Joint Card": {"owner": "alex"},
        "Savings": {"owner": "alex", "kind": "savings"},
    }
    dump_yaml(household_path, household)

    declarations_path = solo / "declarations.yaml"
    declarations = load_yaml(declarations_path)
    declarations["sharing"] = []
    dump_yaml(declarations_path, declarations)

    plan_path = solo / "plan.yaml"
    plan = load_yaml(plan_path)
    plan["plan"]["lines"] = [
        line for line in plan["plan"]["lines"] if line.get("who") == "alex"
    ]
    dump_yaml(plan_path, plan)

    solo_result = run_hfk(
        "categories",
        "--home",
        str(solo),
        "--month",
        "2026-09",
        "--today",
        "2026-10-01",
    )
    assert solo_result.returncode == 0
    assert solo_result.stderr == ""
    assert "categories 2026-09 for alex" in solo_result.stdout
    assert "total  target 1850.00  actual 2075.00  left -225.00" in solo_result.stdout


def test_refund_reduces_actual(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    append_transaction(
        home,
        day=28,
        description="Grocer Refund",
        category="Groceries",
        amount=Decimal("30.00"),
        account="Joint Card",
    )

    grocer = by_desc(load_categories(home, "alex"))["Example Grocer"]

    assert grocer.actual == Decimal("167.50")
    assert grocer.variance == Decimal("382.50")

    result = run_hfk(
        "categories",
        "--home",
        str(home),
        "--month",
        "2026-09",
        "--who",
        "alex",
        "--today",
        "2026-10-01",
    )
    assert result.returncode == 0
    assert "target 550.00  actual 167.50  left 382.50" in result.stdout


def test_no_kept_lines_reports_and_exits_zero(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    plan_path = home / "plan.yaml"
    plan = load_yaml(plan_path)
    for line in plan["plan"]["lines"]:
        if line.get("who") == "alex":
            line.pop("categories", None)
    dump_yaml(plan_path, plan)

    result = run_hfk(
        "categories",
        "--home",
        str(home),
        "--month",
        "2026-09",
        "--who",
        "alex",
        "--today",
        "2026-10-01",
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "categories 2026-09 for alex (closed month, 30 of 30 days)" in result.stdout
    assert "no plan lines with categories for alex in 2026-09" in result.stdout
    assert "total" not in result.stdout
