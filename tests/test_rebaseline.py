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
from hfk.engine import RebaselineError, build_rebaseline
from hfk.source import find_workbook, read_tiller
from hfk.source.fixture import build_fixture

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
PYTHONPATH = str(ROOT / "src")
TODAY = date(2026, 10, 5)
WIDTH = len("Annual Membership")


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
    year: int = 2026,
    month: int = 9,
) -> None:
    transaction_date = date(year, month, day)
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
            "Month": date(year, month, 1),
            "Week": transaction_date,
            "Transaction ID": f"test-{year}{month:02d}{day:02d}-{description.lower().replace(' ', '-')}",
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


def load_rebaseline(
    home: Path,
    who: str,
    *,
    through: str = "2026-09",
    months: int = 6,
    today: date = TODAY,
):
    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    plan = load_plan(home, declarations=declarations, people=household.slugs)
    ledger = read_tiller(find_workbook(home / "data", household.tiller_glob))
    return build_rebaseline(
        ledger=ledger,
        household=household,
        declarations=declarations,
        plan=plan,
        who=who,
        through=Month.parse(through),
        months=months,
        today=today,
    )


def by_category(report) -> dict[str, Any]:
    return {line.category: line for line in report.lines}


def row(category: str, rest: str) -> str:
    return f"{category:<{WIDTH}}  {rest}"


def test_rebaseline_cli_runs_on_example_instance(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    plan_before = (home / "plan.yaml").read_bytes()

    result = run_hfk(
        "rebaseline",
        "--home",
        str(home),
        "--who",
        "alex",
        "--through",
        "2026-09",
        "--today",
        "2026-10-05",
    )

    assert result.returncode == 0
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert lines[0] == "rebaseline for alex  window 2026-04..2026-09  months 6"
    assert lines[1] == row(
        "Rent",
        "months 6/6  mean 1500.00  median 1500.00  max 1500.00  "
        "current 1200.00  proposed 1500.00  stable",
    )
    assert lines[2] == row(
        "Utilities",
        "months 6/6  mean 105.00  median 105.00  max 105.00  "
        "current 90.00  proposed 105.00  stable",
    )
    assert lines[3] == row(
        "Groceries",
        "months 6/6  mean 182.50  median 182.50  max 182.50  "
        "current 550.00  proposed 182.50  stable",
    )
    assert lines[4] == row(
        "Dining",
        "months 6/6  mean 52.50  median 52.50  max 52.50  "
        "current -  proposed 52.50  stable; no plan line",
    )
    assert lines[5] == row(
        "Annual Membership",
        "months 1/6  mean 10.00  median 0.00  max 60.00  "
        "current 10.00  proposed -  spiky; "
        "spiky (1 of 6 months); annual line: Example Cloud Renewal",
    )
    assert lines[6] == "stable 4  lumpy 0  spiky 1"
    assert len(lines) == 7
    assert (home / "plan.yaml").read_bytes() == plan_before

    default_through = run_hfk(
        "rebaseline",
        "--home",
        str(home),
        "--who",
        "alex",
        "--today",
        "2026-10-05",
    )
    assert default_through.returncode == 0
    assert default_through.stdout.splitlines()[0] == lines[0]

    sam = run_hfk(
        "rebaseline",
        "--home",
        str(home),
        "--who",
        "sam",
        "--through",
        "2026-09",
        "--today",
        "2026-10-05",
    )
    assert sam.returncode == 0
    assert sam.stderr == ""
    sam_lines = sam.stdout.splitlines()
    assert sam_lines[0] == "rebaseline for sam  window 2026-04..2026-09  months 6"
    assert not any(line.lstrip().startswith("Rent") for line in sam_lines)
    assert row(
        "Utilities",
        "months 6/6  mean 105.00  median 105.00  max 105.00  "
        "current 90.00  proposed 105.00  stable",
    ) in sam_lines
    assert row(
        "Groceries",
        "months 6/6  mean 182.50  median 182.50  max 182.50  "
        "current -  proposed 182.50  stable; no plan line",
    ) in sam_lines
    assert row(
        "Dining",
        "months 6/6  mean 52.50  median 52.50  max 52.50  "
        "current 60.00  proposed 52.50  stable",
    ) in sam_lines
    assert row(
        "Annual Membership",
        "months 1/6  mean 10.00  median 0.00  max 60.00  "
        "current -  proposed -  spiky; spiky (1 of 6 months); no plan line",
    ) in sam_lines
    assert sam_lines[-1] == "stable 3  lumpy 0  spiky 1"


def test_stable_category_proposes_its_mean(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    report = load_rebaseline(home, "alex")
    lines = by_category(report)

    rent = lines["Rent"]
    assert rent.months == (Decimal("1500.00"),) * 6
    assert rent.nonzero_months == 6
    assert rent.mean == Decimal("1500.00")
    assert rent.median == Decimal("1500.00")
    assert rent.max == Decimal("1500.00")
    assert rent.classification == "stable"
    assert rent.proposed == Decimal("1500.00")
    assert rent.current == Decimal("1200.00")
    assert rent.flags == ()

    utilities = lines["Utilities"]
    assert utilities.mean == Decimal("105.00")
    assert utilities.proposed == Decimal("105.00")
    assert utilities.current == Decimal("90.00")
    assert utilities.classification == "stable"
    assert utilities.flags == ()

    assert report.stable == 4
    assert report.lumpy == 0
    assert report.spiky == 1


def test_spiky_category_is_flagged_not_smoothed(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    report = load_rebaseline(home, "alex")
    membership = by_category(report)["Annual Membership"]

    assert membership.months == (
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("60.00"),
        Decimal("0.00"),
        Decimal("0.00"),
    )
    assert membership.nonzero_months == 1
    assert membership.mean == Decimal("10.00")
    assert membership.median == Decimal("0.00")
    assert membership.max == Decimal("60.00")
    assert membership.classification == "spiky"
    assert membership.proposed is None
    assert membership.flags == ("spiky (1 of 6 months)", "annual line: Example Cloud Renewal")
    assert report.spiky == 1

    short = load_rebaseline(home, "alex", through="2026-07", months=2)
    short_membership = by_category(short)["Annual Membership"]
    assert short.window_start == Month(2026, 6)
    assert short.window_end == Month(2026, 7)
    assert short.months == 2
    assert short_membership.months == (Decimal("0.00"), Decimal("60.00"))
    assert short_membership.nonzero_months == 1
    assert short_membership.classification == "stable"
    assert short_membership.mean == Decimal("30.00")
    assert short_membership.median == Decimal("30.00")
    assert short_membership.proposed == Decimal("30.00")
    assert short_membership.flags == ("annual line: Example Cloud Renewal",)


def test_lumpy_category_is_flagged_with_median_and_max(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    append_transaction(
        home,
        year=2026,
        month=6,
        day=20,
        description="Big Dinner",
        category="Dining",
        amount=Decimal("-400.00"),
        account="Joint Card",
    )

    report = load_rebaseline(home, "alex")
    dining = by_category(report)["Dining"]

    assert dining.months == (
        Decimal("52.50"),
        Decimal("52.50"),
        Decimal("252.50"),
        Decimal("52.50"),
        Decimal("52.50"),
        Decimal("52.50"),
    )
    assert dining.nonzero_months == 6
    assert dining.mean == Decimal("85.83")
    assert dining.median == Decimal("52.50")
    assert dining.max == Decimal("252.50")
    assert dining.classification == "lumpy"
    assert dining.proposed == Decimal("85.83")
    assert dining.flags == ("lumpy (max 252.50 vs median 52.50)", "no plan line")
    assert report.lumpy == 1

    result = run_hfk(
        "rebaseline",
        "--home",
        str(home),
        "--who",
        "alex",
        "--through",
        "2026-09",
        "--today",
        "2026-10-05",
    )
    assert result.returncode == 0
    assert (
        "months 6/6  mean 85.83  median 52.50  max 252.50  "
        "current -  proposed 85.83  lumpy; lumpy (max 252.50 vs median 52.50); no plan line"
    ) in result.stdout
    assert "stable 3  lumpy 1  spiky 1" in result.stdout
    assert report.stable == 3
    assert report.lumpy == 1
    assert report.spiky == 1


def test_current_target_comes_from_the_single_category_line(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    report = load_rebaseline(home, "alex")
    lines = by_category(report)

    assert lines["Rent"].current == Decimal("1200.00")
    assert lines["Utilities"].current == Decimal("90.00")
    assert lines["Groceries"].current == Decimal("550.00")
    assert lines["Groceries"].flags == ()


def test_multi_category_line_gives_no_current(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    plan_path = home / "plan.yaml"
    plan = load_yaml(plan_path)
    for line in plan["plan"]["lines"]:
        if line.get("desc") == "Example Rent" and line.get("who") == "alex":
            line["desc"] = "Example Housing"
            line["categories"] = ["Rent", "Utilities"]
    plan["plan"]["lines"] = [
        line
        for line in plan["plan"]["lines"]
        if not (line.get("desc") == "Example Utilities" and line.get("who") == "alex")
    ]
    dump_yaml(plan_path, plan)

    report = load_rebaseline(home, "alex")
    lines = by_category(report)

    assert lines["Rent"].current is None
    assert "shared line: Example Housing" in lines["Rent"].flags
    assert lines["Rent"].classification == "stable"
    assert lines["Rent"].proposed == Decimal("1500.00")
    assert lines["Utilities"].current is None
    assert "shared line: Example Housing" in lines["Utilities"].flags

    result = run_hfk(
        "rebaseline",
        "--home",
        str(home),
        "--who",
        "alex",
        "--through",
        "2026-09",
        "--today",
        "2026-10-05",
    )
    assert result.returncode == 0
    assert "current -  proposed 1500.00  stable; shared line: Example Housing" in result.stdout


def test_annual_line_is_flagged(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    report = load_rebaseline(home, "alex", through="2026-07", months=2)
    membership = by_category(report)["Annual Membership"]

    assert membership.current == Decimal("10.00")
    assert membership.classification == "stable"
    assert membership.flags == ("annual line: Example Cloud Renewal",)

    full = load_rebaseline(home, "alex")
    full_flags = by_category(full)["Annual Membership"].flags
    assert full_flags == ("spiky (1 of 6 months)", "annual line: Example Cloud Renewal")


def test_history_start_clamps_the_window(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    household_path = home / "household.yaml"
    household = load_yaml(household_path)
    household["history_start"] = "2026-07-01"
    dump_yaml(household_path, household)

    report = load_rebaseline(home, "alex", through="2026-09", months=6)
    assert report.window_start == Month(2026, 7)
    assert report.window_end == Month(2026, 9)
    assert report.months == 3
    assert report.clamped is True
    assert report.history_start == date(2026, 7, 1)
    rent = by_category(report)["Rent"]
    assert rent.months == (Decimal("1500.00"),) * 3
    assert rent.nonzero_months == 3
    assert rent.mean == Decimal("1500.00")

    result = run_hfk(
        "rebaseline",
        "--home",
        str(home),
        "--who",
        "alex",
        "--through",
        "2026-09",
        "--today",
        "2026-10-05",
    )
    assert result.returncode == 0
    assert (
        result.stdout.splitlines()[0]
        == "rebaseline for alex  window 2026-07..2026-09  months 3"
    )
    assert "note: window clamped to history_start 2026-07-01" in result.stdout


def test_too_short_window_is_refused(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    household_path = home / "household.yaml"
    household = load_yaml(household_path)
    household["history_start"] = "2026-07-01"
    dump_yaml(household_path, household)

    with pytest.raises(RebaselineError) as error:
        load_rebaseline(home, "alex", through="2026-07", months=6)
    message = str(error.value)
    assert (
        "window 2026-02..2026-07 has only 1 month(s) on or after history_start 2026-07-01"
        in message
    )
    assert "choose a later --through or move history_start" in message

    result = run_hfk(
        "rebaseline",
        "--home",
        str(home),
        "--who",
        "alex",
        "--through",
        "2026-07",
        "--today",
        "2026-10-05",
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("rebaseline: ")
    assert "history_start" in result.stderr

    with pytest.raises(RebaselineError, match="months must be at least 2"):
        load_rebaseline(home, "alex", months=1)
    short = run_hfk(
        "rebaseline",
        "--home",
        str(home),
        "--who",
        "alex",
        "--through",
        "2026-09",
        "--months",
        "1",
        "--today",
        "2026-10-05",
    )
    assert short.returncode == 1
    assert "months must be at least 2" in short.stderr


def test_unclosed_through_month_is_refused(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    with pytest.raises(RebaselineError) as error:
        load_rebaseline(home, "alex", through="2026-10")
    message = str(error.value)
    assert "month 2026-10 is not closed yet" in message
    assert "choose a month that ended before 2026-10-05" in message

    result = run_hfk(
        "rebaseline",
        "--home",
        str(home),
        "--who",
        "alex",
        "--through",
        "2026-10",
        "--today",
        "2026-10-05",
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("rebaseline: ")
    assert "is not closed yet" in result.stderr


def test_shares_follow_sharing_rules(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    alex = load_rebaseline(home, "alex")
    sam = load_rebaseline(home, "sam")

    # City Utilities is a -210.00 transaction on Alex Checking, split 50/50 by
    # the sharing rule, so each person sees 105.00 of spend per month.
    alex_utilities = by_category(alex)["Utilities"]
    sam_utilities = by_category(sam)["Utilities"]
    assert alex_utilities.months == (Decimal("105.00"),) * 6
    assert sam_utilities.months == (Decimal("105.00"),) * 6
    assert alex_utilities.mean == Decimal("105.00")
    assert sam_utilities.mean == Decimal("105.00")
    assert sam_utilities.current == Decimal("90.00")


def test_unknown_who_is_refused(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    with pytest.raises(RebaselineError) as error:
        load_rebaseline(home, "pat")
    message = str(error.value)
    assert "unknown person pat" in message
    assert "use one of alex, sam" in message

    result = run_hfk(
        "rebaseline",
        "--home",
        str(home),
        "--who",
        "pat",
        "--through",
        "2026-09",
        "--today",
        "2026-10-05",
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("rebaseline: ")
    assert "unknown person pat" in result.stderr

    missing = run_hfk(
        "rebaseline",
        "--home",
        str(home),
        "--through",
        "2026-09",
        "--today",
        "2026-10-05",
    )
    assert missing.returncode == 1
    assert "rebaseline: choose --who from: alex, sam" in missing.stderr


def test_no_spend_in_window_prints_placeholder(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    household_path = home / "household.yaml"
    household = load_yaml(household_path)
    household["accounts"] = {
        "Alex Checking": {"owner": "alex"},
        "Sam Checking": {"owner": "alex"},
        "Joint Card": {"owner": "alex"},
        "Savings": {"owner": "alex", "kind": "savings"},
    }
    dump_yaml(household_path, household)
    declarations_path = home / "declarations.yaml"
    declarations = load_yaml(declarations_path)
    declarations["sharing"] = []
    dump_yaml(declarations_path, declarations)

    result = run_hfk(
        "rebaseline",
        "--home",
        str(home),
        "--who",
        "sam",
        "--through",
        "2026-09",
        "--today",
        "2026-10-05",
    )
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "rebaseline for sam  window 2026-04..2026-09  months 6",
        "no spend for sam in the window",
        "stable 0  lumpy 0  spiky 0",
    ]
