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


def _month(value: object) -> tuple[int, int]:
    year, month = str(value).split("-")
    return int(year), int(month)


def test_plan_lines_use_declared_buckets_and_not_type() -> None:
    declarations = load_yaml(ROOT / "examples" / "declarations.example.yaml")
    plan = load_yaml(ROOT / "examples" / "plan.example.yaml")
    assert isinstance(declarations, dict) and isinstance(plan, dict)

    declared = {bucket["name"] for bucket in declarations["buckets"]}
    for line in plan["plan"]["lines"]:
        assert "type" not in line, f"plan line {line['desc']!r} uses `type`; the key is `bucket`"
        assert line["bucket"] in declared, f"plan line {line['desc']!r} names undeclared bucket"


def test_plan_lines_are_dated_and_one_category_per_person_per_month() -> None:
    plan = load_yaml(ROOT / "examples" / "plan.example.yaml")
    assert isinstance(plan, dict)
    default_start = _month(plan["plan"]["effective_from"])

    ranges = []
    for line in plan["plan"]["lines"]:
        start = _month(line.get("effective_from", plan["plan"]["effective_from"]))
        end = _month(line["effective_until"]) if "effective_until" in line else (9999, 12)
        assert default_start <= start <= end
        for category in line.get("categories", []):
            ranges.append((line["who"], category, start, end))

    for i, (who, category, start, end) in enumerate(ranges):
        for other_who, other_category, other_start, other_end in ranges[i + 1 :]:
            if (who, category) != (other_who, other_category):
                continue
            overlap = max(start, other_start) <= min(end, other_end)
            assert not overlap, f"{who}/{category} appears on two lines effective in the same month"


def test_sharing_rules_have_reasons_and_weights_sum_to_one() -> None:
    declarations = load_yaml(ROOT / "examples" / "declarations.example.yaml")
    assert isinstance(declarations, dict)
    assert "category_targets" not in declarations

    rules = declarations["sharing"]
    assert rules
    for rule in rules:
        assert rule["reason"]
        assert rule["match"]
        assert set(rule["match"]) <= {"account", "description", "category"}
        assert cents(sum(Decimal(str(w)) for w in rule["weights"].values())) == cents(1)


def test_example_declarations_map_every_fixture_expense_group(tmp_path: Path) -> None:
    from hfk.source.fixture import build_fixture
    from hfk.source.tiller import read_tiller

    declarations = load_yaml(ROOT / "examples" / "declarations.example.yaml")
    assert isinstance(declarations, dict)
    assert declarations["mapping_source"] == "tiller_group"

    declared = {bucket["name"] for bucket in declarations["buckets"]}
    groups = declarations["groups"]
    assert set(groups.values()) <= declared

    ledger = read_tiller(build_fixture(tmp_path / "fixture.xlsx"))
    categories = {c.name: c for c in ledger.categories}
    expense_groups = {c.group for c in ledger.categories if c.type == "Expense"}
    expense_groups -= set(declarations["non_spend_groups"])
    assert expense_groups <= set(groups), f"unmapped groups: {expense_groups - set(groups)}"

    overrides = declarations["overrides"]
    splits = declarations["splits"]
    assert not set(overrides) & set(splits), "a category is in both overrides and splits"
    for name, override in overrides.items():
        assert name in categories, f"override {name!r} is not a fixture category"
        assert override["bucket"] in declared
        assert override["reason"]
    for name, split in splits.items():
        assert name in categories, f"split {name!r} is not a fixture category"
        assert set(split["weights"]) <= declared
        assert cents(sum(Decimal(str(w)) for w in split["weights"].values())) == cents(1)
        assert split["reason"]


def test_example_plan_categories_resolve_to_their_line_bucket() -> None:
    declarations = load_yaml(ROOT / "examples" / "declarations.example.yaml")
    plan = load_yaml(ROOT / "examples" / "plan.example.yaml")
    assert isinstance(declarations, dict) and isinstance(plan, dict)

    from hfk.source.fixture import _category_rows

    group_of = {row["Category"]: row["Group"] for row in _category_rows()}
    for line in plan["plan"]["lines"]:
        for category in line.get("categories", []):
            if category in declarations["splits"]:
                buckets = set(declarations["splits"][category]["weights"])
            elif category in declarations["overrides"]:
                buckets = {declarations["overrides"][category]["bucket"]}
            else:
                buckets = {declarations["groups"][group_of[category]]}
            assert line["bucket"] in buckets, (
                f"plan line {line['desc']!r} ({line['who']}) is {line['bucket']} but "
                f"{category} resolves to {sorted(buckets)}"
            )
