from __future__ import annotations

import copy
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from hfk.config import Declarations, Override, load_declarations
from hfk.engine import (
    BucketConflictError,
    BucketError,
    BucketPortion,
    CategoryResolution,
    allocate,
    bucket_attributes,
    resolve_category,
    resolve_ledger,
    run_doctor,
)
from hfk.ledger import Ledger, Transaction
from hfk.source.fixture import build_fixture
from hfk.source.tiller import read_tiller

ROOT = Path(__file__).resolve().parents[1]
HOUSEHOLD_EXAMPLE = ROOT / "examples" / "household.example.yaml"
DECLARATIONS_EXAMPLE = ROOT / "examples" / "declarations.example.yaml"
PLAN_EXAMPLE = ROOT / "examples" / "plan.example.yaml"
PROFILES = ROOT / "profiles"


def declarations_data() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(DECLARATIONS_EXAMPLE.read_text(encoding="utf-8")))


def household_data() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(HOUSEHOLD_EXAMPLE.read_text(encoding="utf-8")))


def plan_data() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(PLAN_EXAMPLE.read_text(encoding="utf-8")))


def write_yaml(tmp_path: Path, name: str, data: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def write_declarations(tmp_path: Path, data: dict[str, Any]) -> Path:
    return write_yaml(tmp_path, "declarations.yaml", data)


def example_declarations() -> Declarations:
    return load_declarations(DECLARATIONS_EXAMPLE, people=("alex", "sam"))


def fixture_ledger(tmp_path: Path) -> Ledger:
    return read_tiller(build_fixture(tmp_path / "Tiller-Example.xlsx"))


def instance_home(tmp_path: Path, declarations: dict[str, Any]) -> Path:
    write_yaml(tmp_path, "household.yaml", household_data())
    write_yaml(tmp_path, "declarations.yaml", declarations)
    write_yaml(tmp_path, "plan.yaml", plan_data())
    build_fixture(tmp_path / "data" / "Tiller-Example.xlsx")
    return tmp_path


@pytest.mark.parametrize(
    ("profile", "groups", "overrides", "split_weights"),
    [
        (
            "simple",
            {
                "Housing": "Essential",
                "Food": "Essential",
                "Transportation": "Essential",
                "Subscriptions": "Discretionary",
            },
            {"Utilities": "Essential", "Dining": "Discretionary"},
            {"Essential": "0.5", "Discretionary": "0.5"},
        ),
        (
            "four-bucket",
            {
                "Housing": "Fixed Essential",
                "Food": "Variable Essential",
                "Transportation": "Variable Essential",
                "Subscriptions": "Fixed Discretionary",
            },
            {"Utilities": "Variable Essential", "Dining": "Variable Discretionary"},
            {
                "Variable Essential": "0.5",
                "Variable Discretionary": "0.5",
            },
        ),
        (
            "fifty-thirty-twenty",
            {
                "Housing": "Needs",
                "Food": "Needs",
                "Transportation": "Needs",
                "Subscriptions": "Wants",
            },
            {"Utilities": "Needs", "Dining": "Wants"},
            {"Needs": "0.5", "Wants": "0.5"},
        ),
    ],
)
def test_presets_map_the_fixture_through_a_declared_groups_map(
    tmp_path: Path,
    profile: str,
    groups: dict[str, str],
    overrides: dict[str, str],
    split_weights: dict[str, str],
) -> None:
    data = declarations_data()
    del data["buckets"]
    data["profile"] = profile
    data["groups"] = groups
    for category, bucket in overrides.items():
        data["overrides"][category]["bucket"] = bucket
    data["splits"]["Fuel"]["weights"] = split_weights
    declarations = load_declarations(
        write_declarations(tmp_path, data),
        people=("alex", "sam"),
        profiles_dir=PROFILES,
    )
    ledger = fixture_ledger(tmp_path)

    resolutions = resolve_ledger(ledger, declarations)

    expense_categories = {category.name for category in ledger.categories if category.type == "Expense"}
    assert expense_categories <= set(resolutions)
    assert resolutions["Alex Paycheck"].excluded is True
    assert resolutions["Savings Transfer"].excluded is True
    for resolution in resolutions.values():
        if not resolution.excluded:
            assert sum((portion.weight for portion in resolution.portions), Decimal(0)) == 1


def test_group_name_matching_a_bucket_name_is_not_inferred(tmp_path: Path) -> None:
    data = declarations_data()
    data["buckets"].append({"name": "Subscriptions", "essential": False, "fixed": True})
    del data["groups"]["Subscriptions"]
    declarations = load_declarations(write_declarations(tmp_path, data), people=("alex", "sam"))
    ledger = fixture_ledger(tmp_path)

    with pytest.raises(BucketError) as error:
        resolve_category("Annual Membership", ledger, declarations)

    assert 'group "Subscriptions" (category "Annual Membership") has no bucket' in str(
        error.value
    )


def test_explicit_mapping_source_uses_categories_map(tmp_path: Path) -> None:
    data = declarations_data()
    data["mapping_source"] = "explicit"
    del data["groups"]
    data["categories"] = {"Rent": "Variable Essential"}
    declarations = load_declarations(write_declarations(tmp_path, data), people=("alex", "sam"))
    ledger = fixture_ledger(tmp_path)

    rent = resolve_category("Rent", ledger, declarations)

    assert rent.portions[0].bucket == "Variable Essential"
    assert rent.portions[0].source == "category"
    with pytest.raises(BucketError) as error:
        resolve_category("Groceries", ledger, declarations)
    assert 'category "Groceries" has no bucket' in str(error.value)


def test_overrides_splits_and_conflicts(tmp_path: Path) -> None:
    declarations = example_declarations()
    ledger = fixture_ledger(tmp_path)

    utilities = resolve_category("Utilities", ledger, declarations)
    assert utilities.portions[0].bucket == "Variable Essential"
    assert utilities.portions[0].source == "override"
    assert utilities.portions[0].reason == (
        "Utilities vary by season; the rest of Housing is fixed."
    )

    fuel = resolve_category("Fuel", ledger, declarations)
    assert tuple(portion.weight for portion in fuel.portions) == (Decimal("0.5"), Decimal("0.5"))
    assert {portion.source for portion in fuel.portions} == {"split"}

    amounts = allocate(Decimal("-45.01"), fuel)
    assert tuple(amount.amount for amount in amounts) == (Decimal("-22.51"), Decimal("-22.50"))
    assert sum((amount.amount for amount in amounts), Decimal("0.00")) == Decimal("-45.01")

    conflict = replace(
        declarations,
        overrides=(
            *declarations.overrides,
            Override("Fuel", "Variable Essential", "Example conflict."),
        ),
    )
    with pytest.raises(BucketConflictError):
        resolve_category("Fuel", ledger, conflict)


def test_resolution_order_is_splits_then_overrides_then_map(tmp_path: Path) -> None:
    data = declarations_data()
    data["splits"]["Rent"] = {
        "weights": {"Fixed Essential": "0.5", "Variable Discretionary": "0.5"},
        "reason": "Example rent split.",
    }
    data["overrides"]["Groceries"] = {
        "bucket": "Variable Discretionary",
        "reason": "Example grocery override.",
    }
    declarations = load_declarations(write_declarations(tmp_path, data), people=("alex", "sam"))
    ledger = fixture_ledger(tmp_path)

    rent = resolve_category("Rent", ledger, declarations)
    groceries = resolve_category("Groceries", ledger, declarations)

    assert tuple(portion.source for portion in rent.portions) == ("split", "split")
    assert tuple(portion.bucket for portion in rent.portions) == (
        "Fixed Essential",
        "Variable Discretionary",
    )
    assert groceries.portions[0].source == "override"
    assert groceries.portions[0].bucket == "Variable Discretionary"


def test_orphan_category_raises(tmp_path: Path) -> None:
    declarations = example_declarations()
    ledger = fixture_ledger(tmp_path)
    orphan_transaction = Transaction(
        date=date(2026, 9, 24),
        description="Old category example",
        category="Old Category",
        amount=Decimal("-10.00"),
        account="Joint Card",
    )
    orphan_ledger = replace(ledger, transactions=(*ledger.transactions, orphan_transaction))

    with pytest.raises(BucketError) as error:
        resolve_ledger(orphan_ledger, declarations)

    assert 'category "Old Category" appears in transactions but not in the Categories sheet' in str(
        error.value
    )

    declared_orphan = replace(
        declarations,
        overrides=(
            *declarations.overrides,
            Override("Old Category", "Variable Essential", "Old category example."),
        ),
    )
    resolved = resolve_category("Old Category", orphan_ledger, declared_orphan)
    assert resolved.group is None
    assert resolved.portions[0].source == "override"


def test_allocate_excluded_returns_nothing_and_exact_cents(tmp_path: Path) -> None:
    declarations = example_declarations()
    ledger = fixture_ledger(tmp_path)
    excluded = resolve_category("Alex Paycheck", ledger, declarations)

    assert allocate(Decimal("100.00"), excluded) == ()

    resolution = CategoryResolution(
        category="Three Way",
        group="Example",
        excluded=False,
        portions=(
            BucketPortion("Needs", Decimal("0.5"), "split", "Example split."),
            BucketPortion("Wants", Decimal("0.25"), "split", "Example split."),
            BucketPortion("Savings", Decimal("0.25"), "split", "Example split."),
        ),
    )
    amounts = allocate(Decimal("-0.10"), resolution)

    assert tuple(amount.amount for amount in amounts) == (
        Decimal("-0.06"),
        Decimal("-0.02"),
        Decimal("-0.02"),
    )
    assert sum((amount.amount for amount in amounts), Decimal("0.00")) == Decimal("-0.10")


def test_bucket_attributes_follow_declarations() -> None:
    declarations = example_declarations()

    bucket = bucket_attributes(declarations, "Fixed Essential")

    assert bucket.essential is True
    assert bucket.fixed is True
    with pytest.raises(BucketError):
        bucket_attributes(declarations, "Unknown")


def test_engine_agrees_with_doctor(tmp_path: Path) -> None:
    data = declarations_data()
    home = instance_home(tmp_path, data)
    declarations = load_declarations(home, people=("alex", "sam"))
    ledger = read_tiller(home / "data" / "Tiller-Example.xlsx")

    resolve_ledger(ledger, declarations)
    report = run_doctor(home, today=date(2026, 10, 1))
    assert not [
        diagnostic
        for diagnostic in report.diagnostics
        if diagnostic.code in {"category-orphan", "group-unmapped", "category-unmapped"}
    ]

    del data["groups"]["Subscriptions"]
    home = instance_home(tmp_path, data)
    declarations = load_declarations(home, people=("alex", "sam"))

    with pytest.raises(BucketError) as error:
        resolve_ledger(ledger, declarations)

    report = run_doctor(home, today=date(2026, 10, 1))
    group_unmapped = [diagnostic for diagnostic in report.diagnostics if diagnostic.code == "group-unmapped"]
    assert group_unmapped
    assert 'group "Subscriptions" (category "Annual Membership") has no bucket' in str(
        error.value
    )
    assert 'group "Subscriptions" (category "Annual Membership") has no bucket' in (
        group_unmapped[0].message
    )
