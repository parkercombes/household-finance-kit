from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = [
    ROOT / "examples" / "household.example.yaml",
    ROOT / "examples" / "declarations.example.yaml",
    ROOT / "examples" / "plan.example.yaml",
]
PROFILES = [
    ROOT / "profiles" / "simple.yaml",
    ROOT / "profiles" / "four-bucket.yaml",
    ROOT / "profiles" / "fifty-thirty-twenty.yaml",
]


def load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def cents(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def test_examples_parse() -> None:
    for path in EXAMPLES:
        data = load_yaml(path)

        assert isinstance(data, dict)
        assert data["schema_version"] == 1


def test_profiles_parse_and_bucket_attributes_are_present() -> None:
    for path in PROFILES:
        data = load_yaml(path)

        assert isinstance(data, dict)
        assert data["name"]
        assert data["description"]
        for bucket in data["buckets"]:
            assert isinstance(bucket["essential"], bool)
            assert isinstance(bucket["fixed"], bool)


def test_plan_annual_bill_matches_monthly_to_cent() -> None:
    data = load_yaml(ROOT / "examples" / "plan.example.yaml")
    assert isinstance(data, dict)

    annual_lines = [line for line in data["plan"]["lines"] if "annual_bill" in line]
    assert annual_lines
    for line in annual_lines:
        assert cents(line["monthly"]) == cents(Decimal(str(line["annual_bill"])) / Decimal(12))
