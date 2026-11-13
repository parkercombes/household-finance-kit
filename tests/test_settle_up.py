"""The settle_up extension (M7; ADR-0004, ADR-0009)."""

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

from hfk.config import load_household
from hfk.ext import load_extensions
from hfk.source.fixture import build_fixture

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
PYTHONPATH = str(ROOT / "src")
TODAY = date(2026, 10, 1)


def make_instance(tmp_path: Path, *, people: list[dict] | None = None) -> Path:
    home = tmp_path / "instance"
    home.mkdir(parents=True)
    for filename in ("household.yaml", "declarations.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, home / filename)
    if people is not None:
        data = yaml.safe_load((home / "household.yaml").read_text(encoding="utf-8"))
        data["people"] = people
        slugs = [person["slug"] for person in people]
        weights = {1: [1], 2: [0.5, 0.5], 3: [0.5, 0.25, 0.25]}[len(slugs)]
        for account in data["accounts"].values():
            if "owner" in account and account["owner"] not in slugs:
                account["owner"] = slugs[0]
            if "shared" in account:
                account["shared"] = dict(zip(slugs, weights, strict=True))
        (home / "household.yaml").write_text(yaml.safe_dump(data, sort_keys=False), "utf-8")
        declarations = yaml.safe_load((home / "declarations.yaml").read_text(encoding="utf-8"))
        declarations["sharing"] = []
        (home / "declarations.yaml").write_text(
            yaml.safe_dump(declarations, sort_keys=False), "utf-8"
        )
    build_fixture(home / "data" / "Tiller-Example.xlsx")
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


def doctor(home: Path):
    # Imported here, not at module top: tests/test_ledger.py re-imports every hfk
    # module, and the entry point always loads the current one.
    from hfk.engine import run_doctor
    from hfk.ext import load_extensions
    from hfk.ext.doctor import extension_doctor_hooks

    return run_doctor(home, today=TODAY, hooks=extension_doctor_hooks(load_extensions()))


def test_settle_up_is_registered_through_its_entry_point():
    loaded = load_extensions()
    extension = loaded.get("settle_up")
    assert extension is not None, loaded.problems
    assert extension.entry_point == "settle_up"
    assert extension.config_section is None
    assert "hfk.ext.settle_up" not in {
        name for name in sys.modules if name.startswith("hfk.cli")
    }


def test_example_instance_enables_settle_up_and_passes_doctor(tmp_path):
    home = make_instance(tmp_path)
    assert load_household(home).extensions == ("settle_up",)
    report = doctor(home)
    assert report.ok, [d.render() for d in report.errors()]


@pytest.mark.parametrize(
    ("people", "count"),
    [
        ([{"slug": "alex", "name": "Alex"}], 1),
        (
            [
                {"slug": "alex", "name": "Alex"},
                {"slug": "sam", "name": "Sam"},
                {"slug": "pat", "name": "Pat"},
            ],
            3,
        ),
    ],
)
def test_exactly_two_people_required(tmp_path, people, count):
    from hfk.ext.settle_up import SettleUpError, two_people

    home = make_instance(tmp_path, people=people)
    household = load_household(home)

    with pytest.raises(SettleUpError) as caught:
        two_people(household)
    assert f"exactly two people, but household.yaml lists {count}" in str(caught.value)
    assert "remove settle_up from extensions" in caught.value.fix

    report = doctor(home)
    errors = [d for d in report.errors() if d.code == "settle-up-people"]
    assert len(errors) == 1
    assert errors[0].where == "household.yaml key=people"

    result = run_hfk("doctor", "--home", str(home), "--today", "2026-10-01")
    assert result.returncode == 1
    assert "settle-up works between exactly two people" in result.stdout


def test_two_people_pass(tmp_path):
    from hfk.ext.settle_up import two_people

    household = load_household(make_instance(tmp_path))
    assert two_people(household) == ("alex", "sam")


def load(home: Path):
    from hfk.config import load_declarations, load_instance_plan
    from hfk.source import find_workbook, read_tiller

    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    plan = load_instance_plan(home, household=household, declarations=declarations)
    ledger = read_tiller(find_workbook(home / "data", household.tiller_glob))
    return household, declarations, plan, ledger


@pytest.mark.parametrize("month", ["2026-04", "2026-07", "2026-08", "2026-09"])
def test_on_ledger_shares_match_scorecard(tmp_path, month):
    from hfk.config import Month
    from hfk.engine import build_scorecard
    from hfk.ext.settle_up.shares import on_ledger_lines, owed_totals

    home = make_instance(tmp_path)
    household, declarations, plan, ledger = load(home)
    people = ("alex", "sam")

    lines = on_ledger_lines(
        ledger=ledger,
        household=household,
        declarations=declarations,
        month=Month.parse(month),
        people=people,
    )
    totals = owed_totals(lines, people)

    for who in people:
        scorecard = build_scorecard(
            ledger=ledger,
            household=household,
            declarations=declarations,
            plan=plan,
            month=Month.parse(month),
            who=who,
            today=TODAY,
        )
        assert totals[who] == scorecard.actual_total, (month, who)

    # The core sharing rule makes the utility bill paid from Alex's own account a
    # shared line in settle-up too: half each, exactly as the scorecard counts it.
    utilities = [line for line in lines if line.account == "Alex Checking"
                 and line.category == "Utilities"]
    assert utilities
    for line in utilities:
        assert line.shared
        assert line.owed_by("alex") + line.owed_by("sam") == line.amount
        assert abs(line.owed_by("alex") - line.owed_by("sam")) <= Decimal("0.01")


def test_settle_up_declares_no_sharing_rules_of_its_own():
    import ast

    source = (ROOT / "src" / "hfk" / "ext" / "settle_up").rglob("*.py")
    for path in source:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", None)
            for node in ast.walk(tree)
        }
        assert "share_weights" not in names, path
        assert "SharingRule" not in names, path
        assert "sharing" not in names, path
