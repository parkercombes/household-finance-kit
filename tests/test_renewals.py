from __future__ import annotations

import os
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from hfk.config import Month, load_declarations, load_household, load_plan
from hfk.engine import Renewal, RenewalsError, RenewalsReport, build_renewals

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
PYTHONPATH = str(ROOT / "src")


def make_instance(tmp_path: Path) -> Path:
    """Copy the example YAML files; the renewals report never opens a workbook."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    for filename in ("household.yaml", "declarations.yaml", "plan.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, tmp_path / filename)
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


def append_plan_lines(home: Path, lines: list[dict[str, Any]]) -> None:
    plan = load_yaml(home / "plan.yaml")
    plan["plan"]["lines"].extend(lines)
    dump_yaml(home / "plan.yaml", plan)


def set_history_start(home: Path, iso_date: str) -> None:
    household_path = home / "household.yaml"
    household = load_yaml(household_path)
    household["history_start"] = iso_date
    dump_yaml(household_path, household)


def build_report(home: Path, month: str, who: str | None = None) -> RenewalsReport:
    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    plan = load_plan(home, declarations=declarations, people=household.slugs)
    return build_renewals(plan=plan, household=household, month=Month.parse(month), who=who)


def by_desc(report: RenewalsReport) -> dict[str, Renewal]:
    return {renewal.desc: renewal for renewal in report.renewals}


EXTRA_LINES: list[dict[str, Any]] = [
    {
        "desc": "Example Insurance",
        "who": "sam",
        "bucket": "Fixed Essential",
        "monthly": 50.00,
        "annual_bill": 600.00,
        "annual_full": 1200.00,
        "account": "Joint Card",
        "due": {"month": 1, "day": 15},
        "effective_from": "2026-08",
    },
    {
        "desc": "Example Mismatch",
        "who": "alex",
        "bucket": "Fixed Discretionary",
        "monthly": 10.00,
        "annual_bill": 120.00,
        "annual_full": 120.00,
        "account": "Joint Card",
        "due": {"month": 3, "day": 1},
    },
    {
        "desc": "Example Undated",
        "who": "alex",
        "bucket": "Fixed Discretionary",
        "monthly": 5.00,
        "annual_bill": 60.00,
    },
    {
        "desc": "Example Orphan Account",
        "who": "sam",
        "bucket": "Fixed Discretionary",
        "monthly": 2.00,
        "annual_bill": 24.00,
        "annual_full": 24.00,
        "account": "Old Card",
        "due": {"month": 12, "day": 31},
    },
    {
        "desc": "Example Ending",
        "who": "alex",
        "bucket": "Fixed Discretionary",
        "monthly": 1.00,
        "annual_bill": 12.00,
        "annual_full": 12.00,
        "account": "Alex Checking",
        "due": {"month": 6, "day": 1},
        "effective_until": "2026-12",
    },
]


def test_renewals_cli_runs_on_example_instance(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    result = run_hfk("renewals", "--home", str(home), "--month", "2026-10")

    assert result.returncode == 0
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert lines[0] == "renewals for 2026-10"
    assert (
        "Example Cloud Renewal  alex  due 2027-07  bill 120.00  monthly 10.00  "
        "accrued 30.00  projected 120.00  ok" in lines
    )
    assert "schedule:" in lines
    assert "  2027-07  120.00  Example Cloud Renewal (alex)" in lines
    assert "set-aside monthly 10.00  accrued 30.00  shortfall 0.00" in lines
    assert "adequacy ok" in lines


def test_due_month_is_the_full_fund(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    renewal = by_desc(build_report(home, "2026-07"))["Example Cloud Renewal"]

    assert renewal.next_due == Month(2026, 7)
    assert renewal.accrued_months == 12
    assert renewal.accrued == Decimal("120.00")
    assert renewal.projected == Decimal("120.00")
    assert renewal.shortfall == Decimal("0.00")
    assert renewal.flags == ()

    result = run_hfk("renewals", "--home", str(home), "--month", "2026-07")
    assert result.returncode == 0
    assert "due 2026-07" in result.stdout
    assert "  2026-07  120.00  Example Cloud Renewal (alex)" in result.stdout.splitlines()

    restarted = by_desc(build_report(home, "2026-08"))["Example Cloud Renewal"]
    assert restarted.next_due == Month(2027, 7)
    assert restarted.accrued_months == 1
    assert restarted.accrued == Decimal("10.00")
    assert restarted.projected == Decimal("120.00")


def test_recently_started_line_shows_shortfall(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    append_plan_lines(home, EXTRA_LINES)

    insurance = by_desc(build_report(home, "2026-10"))["Example Insurance"]

    assert insurance.accrued_months == 3
    assert insurance.accrued == Decimal("150.00")
    assert insurance.next_due == Month(2027, 1)
    assert insurance.projected == Decimal("300.00")
    assert insurance.shortfall == Decimal("300.00")
    assert insurance.flags == ()

    report = build_report(home, "2026-10")
    assert report.shortfall_total == Decimal("300.00")
    assert report.short_count == 1

    result = run_hfk("renewals", "--home", str(home), "--month", "2026-10")
    assert result.returncode == 0
    assert "adequacy short 300.00 across 1 renewal" in result.stdout.splitlines()

    due_month = by_desc(build_report(home, "2027-01"))["Example Insurance"]
    assert due_month.accrued == Decimal("300.00")
    assert due_month.projected == Decimal("300.00")
    assert due_month.shortfall == Decimal("300.00")


def test_history_start_limits_accrual(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    set_history_start(home, "2026-09-01")

    cloud = by_desc(build_report(home, "2026-10"))["Example Cloud Renewal"]

    assert cloud.accrued_months == 2
    assert cloud.accrued == Decimal("20.00")
    assert cloud.projected == Decimal("110.00")
    assert cloud.shortfall == Decimal("10.00")

    report = build_report(home, "2026-10")
    assert report.shortfall_total == Decimal("10.00")
    assert report.short_count == 1

    result = run_hfk("renewals", "--home", str(home), "--month", "2026-10")
    assert result.returncode == 0
    assert "adequacy short 10.00 across 1 renewal" in result.stdout.splitlines()


def test_schedule_lists_the_next_twelve_months_by_due_month(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    append_plan_lines(home, EXTRA_LINES)

    report = build_report(home, "2026-10")

    assert [(entry.month, entry.total) for entry in report.schedule] == [
        (Month(2026, 12), Decimal("24.00")),
        (Month(2027, 1), Decimal("600.00")),
        (Month(2027, 3), Decimal("120.00")),
        (Month(2027, 6), Decimal("12.00")),
        (Month(2027, 7), Decimal("120.00")),
    ]
    assert report.schedule[0].items == ("Example Orphan Account (sam)",)
    assert report.schedule[1].items == ("Example Insurance (sam)",)
    assert report.schedule[4].items == ("Example Cloud Renewal (alex)",)

    ending = by_desc(report)["Example Ending"]
    assert ending.next_due == Month(2027, 6)
    assert ending.flags == ("ends before next due",)

    january = build_report(home, "2027-01")
    assert "Example Ending" not in by_desc(january)
    orphan = by_desc(january)["Example Orphan Account"]
    assert orphan.next_due == Month(2027, 12)
    assert orphan.accrued == Decimal("2.00")

    result = run_hfk("renewals", "--home", str(home), "--month", "2026-10")
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    schedule_start = lines.index("schedule:")
    assert lines[schedule_start + 1 : schedule_start + 6] == [
        "  2026-12  24.00  Example Orphan Account (sam)",
        "  2027-01  600.00  Example Insurance (sam)",
        "  2027-03  120.00  Example Mismatch (alex)",
        "  2027-06  12.00  Example Ending (alex)",
        "  2027-07  120.00  Example Cloud Renewal (alex)",
    ]
    assert "set-aside monthly 78.00  accrued 274.00  shortfall 300.00" in lines


def test_line_without_due_is_flagged_and_unscheduled(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    append_plan_lines(home, EXTRA_LINES)

    report = build_report(home, "2026-10")

    undated = by_desc(report)["Example Undated"]
    assert undated.due is None
    assert undated.next_due is None
    assert undated.accrued_months is None
    assert undated.accrued is None
    assert undated.months_to_due is None
    assert undated.projected is None
    assert undated.shortfall is None
    assert undated.flags == ("no due date",)
    assert undated.monthly == Decimal("5.00")
    assert all(
        "Example Undated" not in item for entry in report.schedule for item in entry.items
    )
    assert report.set_aside_monthly == Decimal("78.00")
    assert report.accrued_total == Decimal("274.00")

    result = run_hfk("renewals", "--home", str(home), "--month", "2026-10")
    assert result.returncode == 0
    assert (
        "Example Undated" + " " * 9 + "alex  due -  bill 60.00  monthly 5.00  "
        "accrued -  projected -  -; no due date" in result.stdout.splitlines()
    )


def test_share_mismatch_is_flagged(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    append_plan_lines(home, EXTRA_LINES)

    report = build_report(home, "2026-10")

    mismatch = by_desc(report)["Example Mismatch"]
    assert mismatch.flags == ("share mismatch: expected 60.00 from Joint Card weights",)
    assert mismatch.accrued == Decimal("70.00")
    assert mismatch.projected == Decimal("120.00")
    assert mismatch.shortfall == Decimal("0.00")

    insurance = by_desc(report)["Example Insurance"]
    assert insurance.flags == ()

    result = run_hfk("renewals", "--home", str(home), "--month", "2026-10")
    assert result.returncode == 0
    assert (
        "Example Mismatch" + " " * 8 + "alex  due 2027-03  bill 120.00  monthly 10.00  "
        "accrued 70.00  projected 120.00  ok; "
        "share mismatch: expected 60.00 from Joint Card weights"
        in result.stdout.splitlines()
    )


def test_undeclared_account_is_flagged(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    append_plan_lines(home, EXTRA_LINES)

    orphan = by_desc(build_report(home, "2026-10"))["Example Orphan Account"]

    assert orphan.account == "Old Card"
    assert orphan.flags == ("account undeclared",)
    assert orphan.next_due == Month(2026, 12)
    assert orphan.accrued == Decimal("20.00")
    assert orphan.projected == Decimal("24.00")
    assert orphan.shortfall == Decimal("0.00")

    result = run_hfk("renewals", "--home", str(home), "--month", "2026-10")
    assert result.returncode == 0
    assert (
        "Example Orphan Account  sam" + " " * 3 + "due 2026-12  bill 24.00  monthly 2.00  "
        "accrued 20.00  projected 24.00  ok; account undeclared"
        in result.stdout.splitlines()
    )


def test_who_filters_lines(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    append_plan_lines(home, EXTRA_LINES)

    report = build_report(home, "2026-10", who="sam")

    assert [renewal.desc for renewal in report.renewals] == [
        "Example Insurance",
        "Example Orphan Account",
    ]
    assert report.set_aside_monthly == Decimal("52.00")
    assert report.accrued_total == Decimal("170.00")
    assert report.shortfall_total == Decimal("300.00")

    result = run_hfk("renewals", "--home", str(home), "--month", "2026-10", "--who", "sam")
    assert result.returncode == 0
    assert result.stdout.splitlines()[0] == "renewals for 2026-10  who sam"

    empty = make_instance(tmp_path / "no-annual-lines")
    nobody = run_hfk("renewals", "--home", str(empty), "--month", "2026-10", "--who", "sam")
    assert nobody.returncode == 0
    assert nobody.stderr == ""
    assert nobody.stdout.splitlines() == [
        "renewals for 2026-10  who sam",
        "schedule: nothing due in the next 12 months",
        "set-aside monthly 0.00  accrued 0.00  shortfall 0.00",
        "adequacy ok",
    ]

    with pytest.raises(RenewalsError) as error:
        build_report(home, "2026-10", who="pat")
    message = str(error.value)
    assert "unknown person pat" in message
    assert "use one of alex, sam" in message

    refused = run_hfk("renewals", "--home", str(home), "--month", "2026-10", "--who", "pat")
    assert refused.returncode == 1
    assert refused.stdout == ""
    assert refused.stderr == "renewals: unknown person pat. Fix: use one of alex, sam\n"


def test_month_before_history_start_is_refused(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    set_history_start(home, "2026-09-01")

    with pytest.raises(RenewalsError) as error:
        build_report(home, "2026-08")
    message = str(error.value)
    assert "month 2026-08 is before history_start 2026-09-01" in message
    assert "choose a month on or after history_start" in message

    result = run_hfk("renewals", "--home", str(home), "--month", "2026-08")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "renewals: month 2026-08 is before history_start 2026-09-01. "
        "Fix: choose a month on or after history_start\n"
    )


def test_month_before_plan_start_is_refused(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    with pytest.raises(RenewalsError) as error:
        build_report(home, "2024-12")
    message = str(error.value)
    assert "month 2024-12 is before the plan effective_from 2025-01" in message
    assert "choose a month on or after plan.effective_from" in message

    result = run_hfk("renewals", "--home", str(home), "--month", "2024-12")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "renewals: month 2024-12 is before the plan effective_from 2025-01. "
        "Fix: choose a month on or after plan.effective_from\n"
    )
