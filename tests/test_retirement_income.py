"""Typed retirement income streams and claim-age scenarios (M8-02, R2; ADR-0008).

Expected values are worked by hand with inflation 0.025:
a fixed-dollar (cola: none) 1500.00 a month pension is 18000.00 in its first
year, 18000 / 1.025 = 17560.98 the next, and 18000 / 1.025**2 = 17132.66 the
year after; a 300.00 a month stream growing 2 percent nominal is 3600.00, then
3600 * 1.02 / 1.025 = 3582.44, and 3530.27 in its fifth year.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from hfk.config import ConfigError

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "retirement.example.yaml"


def example() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")))


def load(tmp_path: Path, data: dict[str, Any] | None = None):
    from hfk.ext.retirement.schema import load_retirement

    data = example() if data is None else data
    path = tmp_path / "retirement.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return load_retirement(data, path)


def amounts(config, label: str, years, scenario=None) -> list[str]:
    from hfk.ext.retirement.income import stream_amount

    stream = next(s for s in config.income if s.label == label)
    person = config.person(stream.who)
    return [
        str(
            stream_amount(
                stream,
                year,
                birth_year=person.birth_year,
                birth_month=person.birth_month,
                claim_age=(scenario or {}).get(stream.who),
                inflation=config.assumptions.inflation,
            )
        )
        for year in years
    ]


def test_example_streams_load(tmp_path):
    config = load(tmp_path)
    assert [(s.type, s.who) for s in config.income] == [
        ("social_security", "alex"),
        ("social_security", "sam"),
        ("pension", "sam"),
        ("account_drawdown", "alex"),
        ("other", "sam"),
    ]
    alex_ss = config.income[0]
    assert alex_ss.label == "social security (alex)"
    assert alex_ss.claim_ages == (
        (62, Decimal("1400.00")),
        (67, Decimal("2000.00")),
        (70, Decimal("2480.00")),
    )
    assert config.income[2].cola == "none"
    assert config.income[4].cola == Decimal("0.02")


def test_cola_streams_calculate_as_documented(tmp_path):
    config = load(tmp_path)

    # cola: none erodes by inflation from its first year.
    assert amounts(config, "pension (sam)", [2036, 2037, 2038, 2039]) == [
        "0.00", "18000.00", "17560.98", "17132.66",
    ]
    # cola: full stays flat in today's dollars, inside start_year..end_year only.
    assert amounts(config, "account drawdown (alex)", [2034, 2035, 2060, 2061]) == [
        "0.00", "12000.00", "12000.00", "0.00",
    ]
    # A numeric cola is a nominal growth rate, converted to real with inflation.
    assert amounts(config, "Example rent", range(2037, 2043)) == [
        "3600.00", "3582.44", "3564.96", "3547.57", "3530.27", "0.00",
    ]


def test_social_security_claim_age_scenarios_are_alternatives(tmp_path):
    config = load(tmp_path)
    label = "social security (alex)"  # born 1970-06, so 7 months in the first year

    at_62 = amounts(config, label, [2031, 2032, 2033, 2040], {"alex": 62})
    at_67 = amounts(config, label, [2036, 2037, 2038, 2040], {"alex": 67})
    at_70 = amounts(config, label, [2037, 2039, 2040, 2041], {"alex": 70})

    assert at_62 == ["0.00", "9800.00", "16800.00", "16800.00"]
    assert at_67 == ["0.00", "14000.00", "24000.00", "24000.00"]
    assert at_70 == ["0.00", "0.00", "17360.00", "29760.00"]
    # One scenario, one claim age: the 67 scenario never pays the 62 or 70 amounts.
    assert "16800.00" not in at_67 and "29760.00" not in at_67


def test_a_scenario_must_pick_a_listed_claim_age_for_everyone(tmp_path):
    from hfk.ext.retirement.income import check_scenario, social_security_people

    config = load(tmp_path)
    assert social_security_people(config.income) == ("alex", "sam")
    check_scenario(config.income, {"alex": 67, "sam": 70}, config.path)

    with pytest.raises(ConfigError) as caught:
        check_scenario(config.income, {"alex": 67}, config.path)
    assert caught.value.key == "income[1].claim_ages"
    assert "no claim age chosen for sam" in caught.value.problem
    assert "hfk never picks one for you" in caught.value.fix

    with pytest.raises(ConfigError) as caught:
        check_scenario(config.income, {"alex": 65, "sam": 67}, config.path)
    assert caught.value.key == "income[0].claim_ages"
    assert "claim age 65 is not listed for alex" in caught.value.problem


@pytest.mark.parametrize(
    ("mutate", "key", "problem"),
    [
        (lambda d: d["income"][2].pop("cola"), "income[2].cola", "Missing required key"),
        (lambda d: d["income"][2].update(cola="partial"), "income[2].cola", "Invalid cola"),
        (lambda d: d["income"][2].update(cola=2.0), "income[2].cola", "Invalid cola"),
        (lambda d: d["assumptions"].pop("inflation"), "income[2].cola",
         "assumptions.inflation is required"),
        (lambda d: d["income"][0]["claim_ages"].update({61: 1000}),
         'income[0].claim_ages."61"', "Invalid claim age"),
        (lambda d: d["income"][0].update(claim_ages={}), "income[0].claim_ages",
         "claim_ages is empty"),
        (lambda d: d["income"][0].update(monthly=100), "income[0].monthly", "Unknown key"),
        (lambda d: d["income"][2].update(type="annuity"), "income[2].type",
         "Unknown income type"),
        (lambda d: d["income"][2].update(who="pat"), "income[2].who", "Unknown person slug"),
        (lambda d: d["income"][3].update(end_year=2030), "income[3].end_year",
         "end_year 2030 is before start_year 2035"),
        (lambda d: d["income"][3].update(monthly=-5), "income[3].monthly", "Invalid amount"),
        (lambda d: d["income"][3].pop("start_year"), "income[3].start_year",
         "Missing required key"),
        (lambda d: d["income"][4].update(label="pension (sam)"), "income[4].label",
         "both called"),
    ],
)
def test_invalid_streams_fail_clearly(tmp_path, mutate, key, problem):
    data = example()
    mutate(data)
    with pytest.raises(ConfigError) as caught:
        load(tmp_path, data)
    assert caught.value.key == key
    assert problem in caught.value.problem
    assert caught.value.fix


def test_all_full_streams_need_no_inflation(tmp_path):
    data = example()
    del data["assumptions"]["inflation"]
    data["income"] = [s for s in data["income"] if s["cola"] == "full"]
    config = load(tmp_path, data)
    assert config.assumptions.inflation is None
    assert amounts(config, "account drawdown (alex)", [2035]) == ["12000.00"]
