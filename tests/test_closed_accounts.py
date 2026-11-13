"""A closed account keeps its ownership (ADR-0014, roadmap M5-16).

Closure is ``closed: YYYY-MM-DD`` on the account's ``household.yaml`` entry.
The account still scores with its own weights, balances and net worth stop at
the closure date, doctor flags activity after it, and ``declarations.yaml``
no longer accepts ``closed_accounts``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from hfk.config import (
    ConfigError,
    Month,
    load_declarations,
    load_household,
    load_instance_plan,
)
from hfk.engine import build_balances, build_networth, build_scorecard, run_doctor
from hfk.source import find_workbook, read_tiller
from hfk.source.fixture import build_fixture

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
TEXT_SNAPSHOTS = ROOT / "tests" / "snapshots" / "text"
PYTHONPATH = str(ROOT / "src")
CLOSED = "2026-09-22"  # the Joint Card's last fixture transaction


def make_instance(tmp_path: Path, closed: str = CLOSED) -> Path:
    home = tmp_path / "instance"
    home.mkdir()
    for filename in ("household.yaml", "declarations.yaml", "plan.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, home / filename)
    build_fixture(home / "data" / "Tiller-Example.xlsx")
    path = home / "household.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["accounts"]["Joint Card"]["closed"] = closed
    data["accounts"]["Joint Card"]["note"] = "Replaced by a new card."
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return home


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


def load(home: Path):
    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    ledger = read_tiller(find_workbook(home / "data", household.tiller_glob))
    return household, declarations, ledger


def test_household_loads_closed_and_note(tmp_path):
    household = load_household(make_instance(tmp_path))
    account = household.account("Joint Card")
    assert account.closed == date(2026, 9, 22)
    assert account.note == "Replaced by a new card."
    assert account.weights == (("alex", Decimal("0.5")), ("sam", Decimal("0.5")))
    assert household.account("Alex Checking").closed is None


def test_bad_closed_date_names_the_account_key(tmp_path):
    home = make_instance(tmp_path, closed="22/09/2026")
    with pytest.raises(ConfigError) as error:
        load_household(home)
    assert error.value.key == 'accounts."Joint Card".closed'
    assert "YYYY-MM-DD" in error.value.fix


def test_closed_account_scores_with_its_weights(tmp_path):
    home = make_instance(tmp_path)
    household, declarations, ledger = load(home)
    plan = load_instance_plan(home, household=household, declarations=declarations)
    assert any(t.account == "Joint Card" and t.date.month == 8 for t in ledger.transactions)

    scorecard = build_scorecard(
        ledger=ledger,
        household=household,
        declarations=declarations,
        plan=plan,
        month=Month(2026, 8),
        who="alex",
        today=date(2026, 9, 15),
    )
    assert scorecard.actual_total == Decimal("1840.00")

    result = run_hfk(
        "scorecard", "--home", str(home), "--month", "2026-08", "--who", "alex",
        "--today", "2026-09-15",
    )
    assert result.returncode == 0, result.stderr
    snapshot = (TEXT_SNAPSHOTS / "scorecard-2026-08-alex.txt").read_text(encoding="utf-8")
    assert result.stdout == snapshot


def test_doctor_is_clean_with_the_account_declared_once(tmp_path):
    home = make_instance(tmp_path)
    report = run_doctor(home, today=date(2026, 10, 1))
    assert report.ok, [d.render() for d in report.errors()]
    result = run_hfk("doctor", "--home", str(home), "--today", "2026-10-01")
    assert result.returncode == 0, result.stdout


def test_balances_and_networth_stop_at_the_closure_date(tmp_path):
    home = make_instance(tmp_path)
    household, declarations, ledger = load(home)
    balances = build_balances(
        ledger=ledger, household=household, declarations=declarations, as_of=date(2026, 9, 30)
    )
    joint = next(row for row in balances.accounts if row.account == "Joint Card")
    assert joint.closed == date(2026, 9, 22)
    assert joint.observed == date(2026, 8, 28)

    networth = build_networth(
        ledger=ledger,
        household=household,
        declarations=declarations,
        as_of=date(2026, 9, 30),
        stale_after_days=14,
    )
    line = next(line for line in networth.lines if line.account == "Joint Card")
    assert line.counted is False
    assert line.flags == ("closed 2026-09-22",)

    result = run_hfk("balances", "--home", str(home), "--as-of", "2026-09-30")
    assert result.returncode == 0, result.stderr
    assert "observed 2026-08-28; closed 2026-09-22" in result.stdout
    result = run_hfk("networth", "--home", str(home), "--as-of", "2026-09-30")
    assert result.returncode == 0, result.stderr
    assert "closed 2026-09-22" in result.stdout


def test_transaction_after_closed_is_an_error_naming_household_yaml(tmp_path):
    home = make_instance(tmp_path, closed="2026-09-10")
    report = run_doctor(home, today=date(2026, 10, 1))
    active = [d for d in report.errors() if d.code == "closed-account-active"]
    assert len(active) == 1
    assert active[0].where == "household.yaml"
    assert "Joint Card" in active[0].message
    assert "2026-09-22" in active[0].message
    assert 'accounts."Joint Card".closed' in active[0].fix
    result = run_hfk("doctor", "--home", str(home), "--today", "2026-10-01")
    assert result.returncode == 1


def test_declarations_closed_accounts_fails_naming_the_move(tmp_path):
    home = make_instance(tmp_path)
    path = home / "declarations.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["closed_accounts"] = {"Joint Card": {"closed": "2026-09-22"}}
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ConfigError) as error:
        load_declarations(home)
    assert error.value.key == "closed_accounts"
    assert "under accounts in household.yaml" in error.value.fix
    assert "Joint Card" in error.value.fix

    result = run_hfk("doctor", "--home", str(home), "--today", "2026-10-01")
    assert result.returncode == 1
    assert "closed_accounts moved to household.yaml" in result.stdout
