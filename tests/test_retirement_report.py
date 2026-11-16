"""The calendar-year income-vs-need track (M8-05, R5; ADR-0008, ADR-0018).

The federal table here is SYNTHETIC test data with made-up round figures, never real
tax figures: standard deduction 1000; 10% from 0, 20% from 2000, 30% from 5000; Social
Security base 100, adjusted base 200, fractions 0.5 and 0.85; tax year 2025.

Worked by hand for the small household below (inflation 0.025, priced in 2026):

2035: income 12000.00 (Alex's taxable pension). Federal tax on 12000 - 1000 = 11000 is
200 + 600 + 1800 = 2600.00. State tax 10% of 12000 = 1200.00. Need 12000 (housing)
+ 2400 (Alex's healthcare) = 14400.00. Gap 12000 - 2600 - 1200 - 14400 = -6200.00.

2037: Alex's Social Security starts at 67 (born June: 7 months, 14000.00), plus the
pension 12000.00 and Sam's untaxed 6000.00: income 32000.00. The thresholds shrink to
100 / 1.025**12 = 74.36 and 148.71; provisional income 12000 + 7000 = 19000 is above
both, so 85% of the benefits, 11900.00, is taxable (the cap). Federal tax on
12000 + 11900 - 1000 = 22900 is 200 + 600 + 5370 = 6170.00; state tax stays 1200.00
because the state exempts Social Security. Gap 32000 - 6170 - 1200 - 14400 = 10230.00.
"""

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

from hfk.config import ConfigError

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
TODAY = date(2026, 11, 16)
ADVICE_WORDS = ("should", "recommend", "best", "optimal", "consider", "advise")

TABLE = {
    "schema_version": 1,
    "jurisdiction": "us-federal",
    "tax_year": 2025,
    "source": "SYNTHETIC TEST TABLE - not real figures",
    "filing_status": {
        "married_joint": {
            "standard_deduction": 1000,
            "brackets": [
                {"over": 0, "rate": 0.10},
                {"over": 2000, "rate": 0.20},
                {"over": 5000, "rate": 0.30},
            ],
        }
    },
    "social_security": {
        "source": "SYNTHETIC TEST RULE - not real figures",
        "first_fraction": 0.5,
        "second_fraction": 0.85,
        "married_joint": {"base": 100, "adjusted_base": 200},
    },
}

RETIREMENT = {
    "schema_version": 1,
    "people": {
        "alex": {"birth": "1970-06", "retire_year": 2035},
        "sam": {"birth": "1972-09", "retire_year": 2037},
    },
    "assumptions": {"until_age": 66, "inflation": 0.025},
    "income": [
        {"type": "social_security", "who": "alex", "cola": "full",
         "claim_ages": {62: 1400, 67: 2000}},
        {"type": "pension", "who": "alex", "monthly": 1000, "start_year": 2035,
         "cola": "full", "taxable": "full"},
        {"type": "other", "who": "sam", "monthly": 500, "start_year": 2037,
         "cola": "full", "taxable": "none"},
    ],
    "expenses": {"items": [
        {"label": "Housing", "monthly": 1000},
        {"label": "Healthcare", "who": "alex", "monthly": 200},
    ]},
    "tax": {"filing_status": "married_joint", "max_data_age_years": 1,
            "state": {"module": "flat", "rate": 0.10, "social_security": "exempt"}},
}


def write(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def build(tmp_path: Path, data: dict[str, Any] = RETIREMENT, table: dict = TABLE,
          scenario: dict[str, int] | None = None):
    from hfk.config import load_household
    from hfk.ext.retirement.report import build_retirement_report
    from hfk.ext.retirement.schema import load_retirement
    from hfk.ext.retirement.tax import load_federal_table

    path = write(tmp_path / "retirement.yaml", data)
    config = load_retirement(yaml.safe_load(path.read_text(encoding="utf-8")), path)
    return build_retirement_report(
        config,
        household=load_household(INSTANCE_EXAMPLE),
        plan=None,
        table=load_federal_table(write(tmp_path / "tax" / "us-federal-2025.yaml", table)),
        scenario={"alex": 67} if scenario is None else scenario,
        today=TODAY,
    )


def test_report_rows_cover_calendar_years_with_income_need_and_gap(tmp_path):
    report = build(tmp_path)

    assert [row.year for row in report.household] == [2035, 2036, 2037, 2038]
    y2035, y2036, y2037, y2038 = report.household
    assert (y2035.income, y2035.federal_tax, y2035.state_tax, y2035.need, y2035.gap) == (
        Decimal("12000.00"), Decimal("2600.00"), Decimal("1200.00"), Decimal("14400.00"),
        Decimal("-6200.00"),
    )
    assert y2036.gap == Decimal("-6200.00")
    assert y2037.income == Decimal("32000.00")
    assert y2037.social_security == Decimal("14000.00")
    assert y2037.taxable_social_security == Decimal("11900.00")
    assert y2037.federal_tax == Decimal("6170.00")
    assert y2037.state_tax == Decimal("1200.00")
    assert y2037.gap == Decimal("10230.00")
    assert y2038.social_security == Decimal("24000.00")

    people = {(row.year, row.who): row for row in report.people}
    assert len(report.people) == 8
    alex, sam = people[(2037, "alex")], people[(2037, "sam")]
    assert (alex.age, alex.income, alex.need, alex.before_tax) == (
        67, Decimal("26000.00"), Decimal("2400.00"), Decimal("23600.00"))
    assert (sam.age, sam.income, sam.need, sam.before_tax) == (
        65, Decimal("6000.00"), Decimal("0.00"), Decimal("6000.00"))


def test_social_security_thresholds_shrink_in_todays_dollars(tmp_path):
    # One year after the table's tax year, a base of 20500 is 20000 in today's dollars
    # and an adjusted base of 30750 is 30000. Provisional income 12000 + 12000 = 24000
    # sits between them: taxable = min(12000, 0.5 * (24000 - 20000)) = 2000.00.
    # Without the shrink it would be 0.5 * (24000 - 20500) = 1750.00.
    table = yaml.safe_load(yaml.safe_dump(TABLE))
    table["social_security"]["married_joint"] = {"base": 20500, "adjusted_base": 30750}
    data = yaml.safe_load(yaml.safe_dump(RETIREMENT))
    data["people"] = {"alex": {"birth": "1960-01", "retire_year": 2026},
                      "sam": {"birth": "1960-01", "retire_year": 2026}}
    data["income"] = [
        {"type": "social_security", "who": "alex", "cola": "full", "claim_ages": {66: 2000}},
        {"type": "pension", "who": "sam", "monthly": 1000, "start_year": 2026, "cola": "full",
         "taxable": "full"},
    ]
    report = build(tmp_path, data, table, scenario={"alex": 66})
    assert [row.year for row in report.household] == [2026]
    assert report.household[0].taxable_social_security == Decimal("2000.00")


def test_report_text_has_no_advice_language(tmp_path):
    from hfk.ext.retirement.render import render_csv, render_html, render_text

    report = build(tmp_path)
    text = render_text(report)
    assert "in today's dollars (priced in 2026; inflation assumption 0.025)" in text
    assert "claim ages: alex 67" in text
    assert "gap = income - federal tax - state tax - need" in text
    assert "\n2037  32000.00          12000.00" in text
    for output in (text, render_csv(report), render_html(report)):
        lowered = output.lower()
        for word in ADVICE_WORDS:
            assert f" {word}" not in lowered, word
    assert render_csv(report).splitlines()[0].startswith("view,year,who,age,income")
    assert "<td class=\"num\">10230.00</td>" in render_html(report)


@pytest.mark.parametrize(
    ("change", "scenario", "problem"),
    [
        (lambda d: d.pop("expenses"), {"alex": 67}, "has no expenses"),
        (lambda d: d.pop("tax"), {"alex": 67}, "has no tax section"),
        (lambda d: d["assumptions"].pop("inflation"), {"alex": 67},
         "inflation is required to keep the Social Security tax thresholds"),
        (lambda d: None, {}, "no claim age chosen for alex"),
        (lambda d: d["tax"].update(max_data_age_years=0), {"alex": 67},
         "is for 2025, 1 years before 2026"),
    ],
)
def test_missing_inputs_fail_loudly(tmp_path, change, scenario, problem):
    data = yaml.safe_load(yaml.safe_dump(RETIREMENT))
    change(data)
    with pytest.raises(ConfigError) as caught:
        build(tmp_path, data, scenario=scenario)
    assert problem in caught.value.problem


def test_retirement_command(tmp_path):
    from hfk.source.fixture import build_fixture

    home = tmp_path / "instance"
    home.mkdir()
    for filename in ("household.yaml", "declarations.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, home / filename)
    household = yaml.safe_load((home / "household.yaml").read_text(encoding="utf-8"))
    household["extensions"] = ["settle_up", "retirement"]
    write(home / "household.yaml", household)
    write(home / "retirement.yaml", RETIREMENT)
    build_fixture(home / "data" / "Tiller-Example.xlsx")
    table = write(tmp_path / "us-federal-2025.yaml", TABLE)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")

    def hfk(*args: str):
        return subprocess.run(
            [sys.executable, "-m", "hfk", "retirement", "--home", str(home),
             "--today", "2026-11-16", *args],
            env=env, text=True, capture_output=True, check=False,
        )

    shown = hfk("--claim-age", "alex=67", "--tax-table", str(table))
    assert shown.returncode == 0, shown.stderr
    assert shown.stdout.startswith("retirement track 2035-2038, in today's dollars")
    assert hfk("--claim-age", "alex=67", "--tax-table", str(table), "--format", "csv").stdout

    no_table = hfk("--claim-age", "alex=67")
    assert no_table.returncode == 1
    assert "no federal tax table is installed" in no_table.stderr

    bad = hfk("--claim-age", "alex", "--tax-table", str(table))
    assert bad.returncode == 1
    assert "is not slug=age" in bad.stderr
