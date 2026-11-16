"""Retirement fixtures, disclaimers, and out-of-scope notes (M8-06, R6).

The fixtures are the example `retirement.yaml` and a SYNTHETIC federal tax table.
Both use only the fictional people Alex and Sam and round, made-up numbers.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "retirement.example.yaml"
SYNTHETIC_TABLE = ROOT / "tests" / "fixtures" / "us-federal-synthetic.yaml"
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"


def example_report(scenario: dict[str, int]):
    from hfk.config import load_household
    from hfk.ext.retirement.report import build_retirement_report
    from hfk.ext.retirement.schema import load_retirement
    from hfk.ext.retirement.tax import load_federal_table

    config = load_retirement(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")), EXAMPLE)
    return build_retirement_report(
        config,
        household=load_household(INSTANCE_EXAMPLE),
        plan=None,
        table=load_federal_table(SYNTHETIC_TABLE),
        scenario=scenario,
        today=date(2026, 11, 16),
    )


def test_fixtures_use_only_fictional_people_and_round_numbers():
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    assert set(data["people"]) == {"alex", "sam"}
    for stream in data["income"]:
        assert stream["who"] in {"alex", "sam"}
        amounts = list(stream.get("claim_ages", {}).values()) or [stream["monthly"]]
        for amount in amounts:
            assert Decimal(str(amount)) % 10 == 0, stream
    for item in data["expenses"]["items"]:
        assert Decimal(str(item["monthly"])) % 10 == 0, item
        assert item.get("who") in {None, "alex", "sam"}

    table = yaml.safe_load(SYNTHETIC_TABLE.read_text(encoding="utf-8"))
    assert table["source"].startswith("SYNTHETIC")
    assert table["social_security"]["source"].startswith("SYNTHETIC")
    for text in (EXAMPLE.read_text(encoding="utf-8"), SYNTHETIC_TABLE.read_text("utf-8")):
        assert not re.search(r"\b\d{9,}\b", text)
        assert "@" not in text


def test_report_text_includes_the_mechanics_not_advice_disclaimer():
    from hfk.ext.retirement.render import (
        DISCLAIMER,
        OUT_OF_SCOPE,
        render_csv,
        render_html,
        render_text,
    )

    report = example_report({"alex": 67, "sam": 67})
    text = render_text(report)
    html = render_html(report)

    assert text.startswith(DISCLAIMER + "\n")
    assert text.rstrip().endswith(OUT_OF_SCOPE)
    assert DISCLAIMER in html and OUT_OF_SCOPE in html
    assert "Mechanics, not advice" in DISCLAIMER
    for topic in ("Monte Carlo", "optimisation", "Roth conversion strategy",
                  "product recommendations", "personal advice"):
        assert topic in OUT_OF_SCOPE
    assert render_csv(report).startswith("view,year,")
    assert report.household[0].year == 2035
    assert report.household[-1].year == 1972 + 95


def test_the_same_fixture_gives_each_claim_age_scenario_separately():
    early = example_report({"alex": 62, "sam": 62})
    late = example_report({"alex": 70, "sam": 70})
    assert early.scenario == (("alex", 62), ("sam", 62))
    assert late.scenario == (("alex", 70), ("sam", 70))
    year = {row.year: row for row in early.household}[2040]
    assert year.social_security != {row.year: row for row in late.household}[2040].social_security
