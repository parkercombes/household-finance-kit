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

from hfk.config import load_declarations, load_household
from hfk.engine import BalancesError, build_balances
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


def append_balance(
    home: Path,
    *,
    observed: date,
    account: str,
    balance: Decimal | None,
    account_class: str = "Asset",
    account_type: str = "Checking",
) -> None:
    path = fixture_workbook(home)
    workbook = load_workbook(path)
    try:
        sheet = workbook["Balance History"]
        headers = [cell.value for cell in sheet[1]]
        account_id = account.lower().replace(" ", "-")
        values = {
            "Date": observed,
            "Time": None,
            "Account": account,
            "Account #": None,
            "Account ID": f"acct-{account_id}",
            "Balance ID": f"test-{observed.isoformat()}-{account_id}",
            "Institution": "Example Bank",
            "Balance": balance,
            "Month": observed.replace(day=1),
            "Week": observed,
            "Type": account_type,
            "Class": account_class,
            "Account Status": "Open",
            "Date Added": observed,
        }
        sheet.append([values.get(header) for header in headers])
        workbook.save(path)
    finally:
        workbook.close()


def load_balances(home: Path, as_of: date):
    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    ledger = read_tiller(find_workbook(home / "data", household.tiller_glob))
    return build_balances(
        ledger=ledger,
        household=household,
        declarations=declarations,
        as_of=as_of,
    )


def by_account(report) -> dict[str, Any]:
    return {row.account: row for row in report.accounts}


def test_balances_cli_runs_on_example_instance(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    result = run_hfk("balances", "--home", str(home), "--as-of", "2026-09-30")

    assert result.returncode == 0
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert lines[0] == "balances as of 2026-09-30"
    assert f"{'Alex Checking':<13}  {'Asset':<9}  3025.00  observed 2026-09-28" in lines
    assert f"{'Sam Checking':<13}  {'Asset':<9}  2725.00  observed 2026-09-28" in lines
    assert f"{'Joint Card':<13}  {'Liability':<9}  25.00  observed 2026-09-28" in lines
    assert f"{'Savings':<13}  {'Asset':<9}  5625.00  observed 2026-09-28" in lines
    assert "accounts 4  gaps 0" in lines


def test_latest_observation_on_or_before_as_of_is_selected(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    report = load_balances(home, date(2026, 9, 30))
    by = by_account(report)

    assert report.as_of == date(2026, 9, 30)
    assert [row.account for row in report.accounts] == [
        "Alex Checking",
        "Sam Checking",
        "Joint Card",
        "Savings",
    ]
    assert by["Alex Checking"].balance == Decimal("3025.00")
    assert by["Alex Checking"].observed == date(2026, 9, 28)
    assert by["Alex Checking"].gap is False
    assert by["Alex Checking"].account_class == "Asset"
    assert by["Alex Checking"].account_type == "Checking"
    assert by["Sam Checking"].balance == Decimal("2725.00")
    assert by["Joint Card"].balance == Decimal("25.00")
    assert by["Joint Card"].account_class == "Liability"
    assert by["Joint Card"].account_type == "Credit"
    assert by["Savings"].balance == Decimal("5625.00")
    assert report.gap_count == 0

    june = by_account(load_balances(home, date(2026, 6, 15)))
    assert june["Alex Checking"].balance == Decimal("2525.00")
    assert june["Alex Checking"].observed == date(2026, 5, 28)

    exact = by_account(load_balances(home, date(2026, 9, 28)))
    assert exact["Alex Checking"].balance == Decimal("3025.00")
    assert exact["Alex Checking"].observed == date(2026, 9, 28)

    append_balance(
        home,
        observed=date(2026, 9, 28),
        account="Alex Checking",
        balance=Decimal("3100.00"),
    )
    same_day = by_account(load_balances(home, date(2026, 9, 30)))
    assert same_day["Alex Checking"].balance == Decimal("3100.00")
    assert same_day["Alex Checking"].observed == date(2026, 9, 28)


def test_blank_latest_observation_is_a_gap_not_zero(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    report = load_balances(home, date(2026, 6, 15))
    joint = by_account(report)["Joint Card"]

    assert joint.gap is True
    assert joint.balance is None
    assert joint.observed == date(2026, 5, 28)
    assert joint.gap_reason == "latest observation 2026-05-28 is blank"
    assert joint.last_known == Decimal("-600.00")
    assert joint.last_known_date == date(2026, 4, 28)
    assert by_account(report)["Alex Checking"].balance == Decimal("2525.00")
    assert by_account(report)["Sam Checking"].balance == Decimal("2225.00")
    assert by_account(report)["Savings"].balance == Decimal("5125.00")
    assert report.gap_count == 1

    result = run_hfk("balances", "--home", str(home), "--as-of", "2026-06-15")
    assert result.returncode == 0
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert lines[0] == "balances as of 2026-06-15"
    assert f"{'Alex Checking':<13}  {'Asset':<9}  2525.00  observed 2026-05-28" in lines
    assert f"{'Sam Checking':<13}  {'Asset':<9}  2225.00  observed 2026-05-28" in lines
    assert (
        f"{'Joint Card':<13}  {'Liability':<9}  gap  "
        "latest observation 2026-05-28 is blank; last known -600.00 on 2026-04-28"
    ) in lines
    assert f"{'Savings':<13}  {'Asset':<9}  5125.00  observed 2026-05-28" in lines
    assert "accounts 4  gaps 1" in lines

    append_balance(
        home,
        observed=date(2026, 9, 5),
        account="Trip Fund",
        balance=None,
        account_type="Savings",
    )
    blank_only = by_account(load_balances(home, date(2026, 9, 30)))["Trip Fund"]
    assert blank_only.gap is True
    assert blank_only.balance is None
    assert blank_only.gap_reason == "latest observation 2026-09-05 is blank"
    assert blank_only.last_known is None
    assert blank_only.last_known_date is None

    blank_result = run_hfk("balances", "--home", str(home), "--as-of", "2026-09-30")
    assert blank_result.returncode == 0
    assert (
        f"{'Trip Fund':<13}  {'Asset':<9}  gap  "
        "latest observation 2026-09-05 is blank; no earlier value; undeclared"
    ) in blank_result.stdout.splitlines()
    assert "accounts 5  gaps 1" in blank_result.stdout.splitlines()


def test_account_without_history_is_a_gap(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    household_path = home / "household.yaml"
    household = load_yaml(household_path)
    household["accounts"]["Backup Account"] = {"owner": "alex"}
    dump_yaml(household_path, household)

    report = load_balances(home, date(2026, 9, 30))
    backup = by_account(report)["Backup Account"]

    assert [row.account for row in report.accounts] == [
        "Alex Checking",
        "Sam Checking",
        "Joint Card",
        "Savings",
        "Backup Account",
    ]
    assert backup.gap is True
    assert backup.balance is None
    assert backup.observed is None
    assert backup.account_class is None
    assert backup.account_type is None
    assert backup.gap_reason == "no balance history on or before 2026-09-30"
    assert backup.last_known is None
    assert backup.last_known_date is None
    assert backup.declared is True
    assert report.gap_count == 1

    result = run_hfk("balances", "--home", str(home), "--as-of", "2026-09-30")
    assert result.returncode == 0
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert (
        f"{'Backup Account':<14}  {'-':<9}  gap  no balance history on or before 2026-09-30"
    ) in lines
    assert "accounts 5  gaps 1" in lines


def test_observations_before_history_start_are_ignored(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    household_path = home / "household.yaml"
    household = load_yaml(household_path)
    household["history_start"] = "2026-06-01"
    dump_yaml(household_path, household)

    report = load_balances(home, date(2026, 9, 30))
    assert report.ignored_before_history_start == 8
    assert report.gap_count == 0
    assert by_account(report)["Alex Checking"].balance == Decimal("3025.00")

    result = run_hfk("balances", "--home", str(home), "--as-of", "2026-09-30")
    assert result.returncode == 0
    assert result.stderr == ""
    assert (
        "note: ignored 8 observations before history_start 2026-06-01"
        in result.stdout.splitlines()
    )

    june = load_balances(home, date(2026, 6, 15))
    assert june.gap_count == 4
    assert june.ignored_before_history_start == 8
    assert (
        by_account(june)["Alex Checking"].gap_reason
        == "no balance history on or before 2026-06-15"
    )


def test_closed_account_stops_at_its_closed_date(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    household_path = home / "household.yaml"
    household = load_yaml(household_path)
    del household["accounts"]["Savings"]
    dump_yaml(household_path, household)
    declarations_path = home / "declarations.yaml"
    declarations = load_yaml(declarations_path)
    declarations["closed_accounts"] = {"Savings": {"closed": "2026-07-01"}}
    dump_yaml(declarations_path, declarations)

    report = load_balances(home, date(2026, 9, 30))
    assert [row.account for row in report.accounts] == [
        "Alex Checking",
        "Sam Checking",
        "Joint Card",
        "Savings",
    ]
    savings = by_account(report)["Savings"]
    assert savings.balance == Decimal("5250.00")
    assert savings.observed == date(2026, 6, 28)
    assert savings.closed == date(2026, 7, 1)
    assert savings.declared is True
    assert savings.gap is False
    assert report.gap_count == 0

    result = run_hfk("balances", "--home", str(home), "--as-of", "2026-09-30")
    assert result.returncode == 0
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert (
        f"{'Savings':<13}  {'Asset':<9}  5250.00  observed 2026-06-28; closed 2026-07-01"
    ) in lines
    assert "accounts 4  gaps 0" in lines

    declarations["closed_accounts"] = {"Savings": {"closed": "2026-10-15"}}
    dump_yaml(declarations_path, declarations)
    after = by_account(load_balances(home, date(2026, 9, 30)))["Savings"]
    assert after.balance == Decimal("5625.00")
    assert after.observed == date(2026, 9, 28)
    assert after.closed == date(2026, 10, 15)


def test_undeclared_account_is_flagged(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    append_balance(
        home,
        observed=date(2026, 9, 20),
        account="Vacation Fund",
        balance=Decimal("4100.00"),
        account_type="Savings",
    )
    append_balance(
        home,
        observed=date(2026, 9, 18),
        account="Auto Loan",
        balance=Decimal("-1500.00"),
        account_class="Liability",
        account_type="Loan",
    )

    report = load_balances(home, date(2026, 9, 30))
    assert [row.account for row in report.accounts] == [
        "Alex Checking",
        "Sam Checking",
        "Joint Card",
        "Savings",
        "Auto Loan",
        "Vacation Fund",
    ]
    vacation = by_account(report)["Vacation Fund"]
    auto = by_account(report)["Auto Loan"]
    assert vacation.declared is False
    assert vacation.closed is None
    assert vacation.balance == Decimal("4100.00")
    assert vacation.observed == date(2026, 9, 20)
    assert auto.declared is False
    assert auto.balance == Decimal("-1500.00")
    assert auto.observed == date(2026, 9, 18)
    assert report.gap_count == 0

    result = run_hfk("balances", "--home", str(home), "--as-of", "2026-09-30")
    assert result.returncode == 0
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert (
        f"{'Auto Loan':<13}  {'Liability':<9}  -1500.00  "
        "observed 2026-09-18; undeclared"
    ) in lines
    assert (
        f"{'Vacation Fund':<13}  {'Asset':<9}  4100.00  observed 2026-09-20; undeclared"
    ) in lines
    assert "accounts 6  gaps 0" in lines


def test_as_of_before_history_start_is_refused(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    with pytest.raises(BalancesError) as error:
        load_balances(home, date(2024, 12, 31))
    message = str(error.value)
    assert "as_of 2024-12-31 is before history_start 2025-01-01" in message
    assert "choose a date on or after history_start" in message

    result = run_hfk("balances", "--home", str(home), "--as-of", "2024-12-31")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("balances: ")
    assert "before history_start 2025-01-01" in result.stderr

    boundary = load_balances(home, date(2025, 1, 1))
    assert boundary.gap_count == 4
    assert (
        by_account(boundary)["Alex Checking"].gap_reason
        == "no balance history on or before 2025-01-01"
    )
