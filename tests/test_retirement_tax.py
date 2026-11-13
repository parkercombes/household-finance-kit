"""Versioned tax data, the staleness gate, and state-tax modules (M8-04, R4; ADR-0005).

The tables here are SYNTHETIC test data with round, made-up figures. They are
not real tax figures and must never be copied into a shipped table: shipped
tables cite an official IRS or SSA publication for every figure.

Hand-worked with the synthetic table (deduction 1000; 10% from 0, 20% from
2000, 30% from 5000): income 4000 is taxable 3000, so 2000 * 0.10 + 1000 * 0.20 =
400.00; income 9000 is taxable 8000, so 200 + 600 + 900 = 1700.00.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from hfk.config import ConfigError

SYNTHETIC = {
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


def write_table(directory: Path, data: dict[str, Any], year: int | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    data = copy.deepcopy(data)
    if year is not None:
        data["tax_year"] = year
    path = directory / f"us-federal-{data['tax_year']}.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_federal_bracket_arithmetic(tmp_path):
    from hfk.ext.retirement.tax import federal_income_tax, load_federal_table

    table = load_federal_table(write_table(tmp_path, SYNTHETIC))
    assert table.tax_year == 2025
    assert table.source.startswith("SYNTHETIC")
    tax = [str(federal_income_tax(Decimal(i), table, "married_joint")) for i in (500, 4000, 9000)]
    assert tax == ["0.00", "400.00", "1700.00"]


def test_social_security_taxability_worksheet(tmp_path):
    from hfk.ext.retirement.tax import load_federal_table, taxable_social_security

    rule = load_federal_table(write_table(tmp_path, SYNTHETIC)).social_security

    def taxable(benefits, other):
        return str(taxable_social_security(Decimal(benefits), Decimal(other), rule,
                                           "married_joint"))

    assert taxable(100, 40) == "0.00"     # provisional 90 is under the base 100
    assert taxable(200, 50) == "25.00"    # provisional 150: half of the 50 over the base
    assert taxable(1000, 0) == "305.00"   # 0.85 * (500 - 200) + min(500, 50)
    assert taxable(100, 10_000) == "85.00"  # never more than 85% of the benefits


def test_stale_tax_data_fails_loudly(tmp_path):
    from hfk.ext.retirement.tax import check_staleness, load_federal_table, newest_federal_table

    write_table(tmp_path / "data", SYNTHETIC, year=2023)
    write_table(tmp_path / "data", SYNTHETIC, year=2024)
    table = newest_federal_table(tmp_path / "data")
    assert table.tax_year == 2024

    config_path = tmp_path / "retirement.yaml"
    check_staleness(table, current_year=2026, max_age_years=2, config_path=config_path)
    with pytest.raises(ConfigError) as caught:
        check_staleness(table, current_year=2026, max_age_years=1, config_path=config_path)
    assert caught.value.key == "tax.max_data_age_years"
    assert "is for 2024, 2 years before 2026" in caught.value.problem

    fresh = load_federal_table(write_table(tmp_path / "fresh", SYNTHETIC, year=2026))
    check_staleness(fresh, current_year=2026, max_age_years=0, config_path=config_path)


def test_missing_tax_data_fails_loudly_and_none_ships_unverified(tmp_path):
    from hfk.ext.retirement.tax import newest_federal_table, tax_data_dir

    with pytest.raises(ConfigError, match="no federal tax table is installed") as caught:
        newest_federal_table(tmp_path / "empty")
    assert "hfk never guesses tax figures" in caught.value.fix

    # No federal table ships until its figures are verified against IRS publications.
    assert (tax_data_dir() / "README.md").exists()
    assert list(tax_data_dir().glob("us-federal-*.yaml")) == []
    with pytest.raises(ConfigError, match="no federal tax table is installed"):
        newest_federal_table()


@pytest.mark.parametrize(
    ("state", "income", "expected"),
    [
        ({"module": "none"}, 50_000, "0.00"),
        ({"module": "flat", "rate": 0.04}, 5000, "200.00"),
        ({"module": "flat", "rate": 0.04, "deduction": 1000}, 5000, "160.00"),
        ({"module": "bracket", "brackets": [{"over": 0, "rate": 0.02},
                                            {"over": 1000, "rate": 0.05}]}, 3000, "120.00"),
        ({"module": "bracket", "deduction": 500,
          "brackets": [{"over": 0, "rate": 0.02}, {"over": 1000, "rate": 0.05}]}, 3000, "95.00"),
    ],
)
def test_state_tax_modules_plug_in_cleanly(tmp_path, state, income, expected):
    from hfk.ext.retirement.tax import STATE_MODULES, load_tax_config

    assert sorted(STATE_MODULES) == ["bracket", "flat", "none"]
    config = load_tax_config(
        {"filing_status": "married_joint", "max_data_age_years": 1, "state": state},
        tmp_path / "retirement.yaml",
    )
    assert config.state.module == state["module"]
    assert str(config.state.compute(Decimal(income))) == expected


@pytest.mark.parametrize(
    ("tax", "key", "problem"),
    [
        ({"filing_status": "joint", "max_data_age_years": 1, "state": {"module": "none"}},
         "tax.filing_status", "Unknown filing status"),
        ({"filing_status": "single", "state": {"module": "none"}},
         "tax.max_data_age_years", "Missing required key"),
        ({"filing_status": "single", "max_data_age_years": 1, "state": {"module": "progressive"}},
         "tax.state.module", "Unknown state tax module"),
        ({"filing_status": "single", "max_data_age_years": 1, "state": {"module": "flat"}},
         "tax.state.rate", "Missing required key"),
        ({"filing_status": "single", "max_data_age_years": 1,
          "state": {"module": "flat", "rate": 4}}, "tax.state.rate", "Invalid rate"),
        ({"filing_status": "single", "max_data_age_years": 1,
          "state": {"module": "none", "rate": 0.04}}, "tax.state.rate", "Unknown key"),
        ({"filing_status": "single", "max_data_age_years": 1,
          "state": {"module": "bracket", "brackets": [{"over": 100, "rate": 0.02}]}},
         "tax.state.brackets", "must start at 0"),
    ],
)
def test_invalid_tax_config_fails_clearly(tmp_path, tax, key, problem):
    from hfk.ext.retirement.tax import load_tax_config

    with pytest.raises(ConfigError) as caught:
        load_tax_config(tax, tmp_path / "retirement.yaml")
    assert caught.value.key == key
    assert problem in caught.value.problem


@pytest.mark.parametrize(
    ("mutate", "key"),
    [
        (lambda d: d.pop("source"), "source"),
        (lambda d: d["social_security"].pop("source"), "social_security.source"),
        (lambda d: d.update(jurisdiction="us-ca"), "jurisdiction"),
        (lambda d: d["filing_status"]["married_joint"]["brackets"][2].update(over=1000),
         "filing_status.married_joint.brackets[2].over"),
    ],
)
def test_tables_must_name_their_source_and_rise(tmp_path, mutate, key):
    from hfk.ext.retirement.tax import load_federal_table

    data = copy.deepcopy(SYNTHETIC)
    mutate(data)
    with pytest.raises(ConfigError) as caught:
        load_federal_table(write_table(tmp_path, data))
    assert caught.value.key == key


def test_example_retirement_yaml_carries_tax_choices(tmp_path):
    from hfk.ext.retirement.schema import load_retirement

    path = Path(__file__).resolve().parents[1] / "examples" / "retirement.example.yaml"
    config = load_retirement(yaml.safe_load(path.read_text(encoding="utf-8")), path)
    assert config.tax.filing_status == "married_joint"
    assert config.tax.state.module == "flat"
