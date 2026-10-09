from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from hfk.config import Declarations, Household, load_declarations, load_household
from hfk.engine import (
    Share,
    ShareConflictError,
    ShareError,
    person_total,
    share_ledger,
    share_transaction,
    share_weights,
)
from hfk.ledger import Ledger, Transaction
from hfk.source.fixture import build_fixture
from hfk.source.tiller import read_tiller

ROOT = Path(__file__).resolve().parents[1]
HOUSEHOLD_EXAMPLE = ROOT / "examples" / "household.example.yaml"
DECLARATIONS_EXAMPLE = ROOT / "examples" / "declarations.example.yaml"
CENT = Decimal("0.01")


def household_data() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(HOUSEHOLD_EXAMPLE.read_text(encoding="utf-8")))


def declarations_data() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(DECLARATIONS_EXAMPLE.read_text(encoding="utf-8")))


def write_household(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "household.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def write_declarations(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "declarations.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def example_household() -> Household:
    return load_household(HOUSEHOLD_EXAMPLE)


def example_declarations(household: Household | None = None) -> Declarations:
    if household is None:
        household = example_household()
    return load_declarations(DECLARATIONS_EXAMPLE, people=household.slugs)


def tx(
    description: str = "Rent Payment",
    category: str = "Rent",
    amount: Decimal = Decimal("-1500.00"),
    account: str = "Alex Checking",
) -> Transaction:
    return Transaction(
        date=date(2026, 9, 14),
        description=description,
        category=category,
        amount=amount,
        account=account,
    )


def fixture_ledger(tmp_path: Path) -> Ledger:
    return read_tiller(build_fixture(tmp_path / "Tiller-Example.xlsx"))


def test_owner_account_is_one_hundred_percent() -> None:
    household = example_household()
    declarations = example_declarations(household)

    result = share_transaction(tx(), household, declarations)

    assert result.rule is None
    assert result.amount_for("alex") == Decimal("-1500.00")
    assert result.amount_for("sam") == Decimal("0.00")
    assert result.shares == (Share("alex", Decimal("-1500.00")),)


def test_shared_account_weights_reconcile(tmp_path: Path) -> None:
    household = example_household()
    declarations = example_declarations(household)
    ledger = fixture_ledger(tmp_path)

    results = share_ledger(ledger, household, declarations)

    for result in results:
        assert sum((share.amount for share in result.shares), Decimal("0.00")) == (
            result.transaction.amount
        )
        for person, weight in result.weights:
            expected = result.transaction.amount * weight
            assert abs(result.amount_for(person) - expected) <= CENT

    joint = next(
        result
        for result in results
        if result.transaction.account == "Joint Card"
        and result.transaction.description == "Neighborhood Grocer"
    )
    assert joint.rule is None
    assert joint.weights == (("alex", Decimal("0.5")), ("sam", Decimal("0.5")))
    assert joint.amount_for("alex") == Decimal("-60.00")
    assert joint.amount_for("sam") == Decimal("-60.00")


def test_sharing_rule_moves_joint_bill(tmp_path: Path) -> None:
    household = example_household()
    declarations = example_declarations(household)
    ledger = fixture_ledger(tmp_path)
    utility = next(row for row in ledger.transactions if row.description == "City Utilities")
    rent = next(row for row in ledger.transactions if row.description == "Rent Payment")

    utility_result = share_transaction(utility, household, declarations)
    rent_result = share_transaction(rent, household, declarations)

    assert utility.account == "Alex Checking"
    assert utility.amount == Decimal("-210.00")
    assert utility_result.amount_for("alex") == Decimal("-105.00")
    assert utility_result.amount_for("sam") == Decimal("-105.00")
    assert utility_result.rule is not None
    assert utility_result.rule.reason == "Utilities are a joint bill paid from Alex's account."
    assert rent_result.rule is None
    assert rent_result.amount_for("alex") == Decimal("-1500.00")
    assert rent_result.amount_for("sam") == Decimal("0.00")


def test_description_glob_is_case_insensitive() -> None:
    household = example_household()
    declarations = example_declarations(household)

    match_result = share_transaction(
        tx(description="CITY UTILITIES autopay", category="Utilities", amount=Decimal("-210.00")),
        household,
        declarations,
    )
    miss_result = share_transaction(
        tx(description="Utilities City", category="Utilities", amount=Decimal("-210.00")),
        household,
        declarations,
    )

    assert match_result.rule is not None
    assert match_result.amount_for("alex") == Decimal("-105.00")
    assert match_result.amount_for("sam") == Decimal("-105.00")
    assert miss_result.rule is None
    assert miss_result.amount_for("alex") == Decimal("-210.00")
    assert miss_result.amount_for("sam") == Decimal("0.00")


def test_rule_requires_every_set_key(tmp_path: Path) -> None:
    household = example_household()
    data = declarations_data()
    data["sharing"] = [
        {
            "match": {"account": "Alex Checking", "category": "Dining"},
            "weights": {"sam": 1},
            "reason": "Example dining charge belongs to Sam.",
        }
    ]
    declarations = load_declarations(write_declarations(tmp_path, data), people=household.slugs)

    result = share_transaction(tx(), household, declarations)

    assert result.rule is None
    assert result.amount_for("alex") == Decimal("-1500.00")
    assert result.amount_for("sam") == Decimal("0.00")


def test_conflicting_rules_raise(tmp_path: Path) -> None:
    household = example_household()
    data = declarations_data()
    data["sharing"] = [
        {
            "match": {"account": "Alex Checking", "description": "City*"},
            "weights": {"alex": 0.5, "sam": 0.5},
            "reason": "First example reason.",
        },
        {
            "match": {"category": "Utilities"},
            "weights": {"alex": 1},
            "reason": "Second example reason.",
        },
    ]
    declarations = load_declarations(write_declarations(tmp_path, data), people=household.slugs)
    transaction = tx(description="City Utilities", category="Utilities", amount=Decimal("-210.00"))

    with pytest.raises(ShareConflictError) as error:
        share_transaction(transaction, household, declarations)

    message = str(error.value)
    assert "2026-09-14" in message
    assert "City Utilities" in message
    assert "Alex Checking" in message
    assert "-210.00" in message
    assert "First example reason." in message
    assert "Second example reason." in message


def test_identical_rules_do_not_conflict(tmp_path: Path) -> None:
    household = example_household()
    data = declarations_data()
    data["sharing"] = [
        {
            "match": {"account": "Alex Checking", "description": "City*"},
            "weights": {"alex": 0.5, "sam": 0.5},
            "reason": "First example reason.",
        },
        {
            "match": {"category": "Utilities"},
            "weights": {"sam": 0.5, "alex": 0.5},
            "reason": "Second example reason.",
        },
    ]
    declarations = load_declarations(write_declarations(tmp_path, data), people=household.slugs)

    result = share_transaction(
        tx(description="City Utilities", category="Utilities", amount=Decimal("-210.00")),
        household,
        declarations,
    )

    assert result.rule is declarations.sharing[0]
    assert result.weights == (("alex", Decimal("0.5")), ("sam", Decimal("0.5")))
    assert result.amount_for("alex") == Decimal("-105.00")
    assert result.amount_for("sam") == Decimal("-105.00")


def test_undeclared_account_raises() -> None:
    household = example_household()
    declarations = example_declarations(household)

    with pytest.raises(ShareError) as error:
        share_weights(tx(account="Mystery Bank"), household, declarations)

    assert "Mystery Bank" in str(error.value)
    assert 'declare "Mystery Bank" under accounts in household.yaml with owner or shared' in str(
        error.value
    )


def test_residual_cent_goes_to_largest_weight(tmp_path: Path) -> None:
    household = example_household()
    declarations = example_declarations(household)

    penny = share_transaction(
        tx(description="Tiny charge", amount=Decimal("-0.01"), account="Joint Card"),
        household,
        declarations,
    )
    assert penny.amount_for("alex") == Decimal("-0.01")
    assert penny.amount_for("sam") == Decimal("0.00")
    assert sum((share.amount for share in penny.shares), Decimal("0.00")) == Decimal("-0.01")

    data = declarations_data()
    data["sharing"] = [
        {
            "match": {"account": "Alex Checking", "description": "Split*"},
            "weights": {"alex": 0.7, "sam": 0.3},
            "reason": "Example weighted split.",
        }
    ]
    weighted = load_declarations(write_declarations(tmp_path, data), people=household.slugs)
    ten_dollars = share_transaction(
        tx(description="Split charge", amount=Decimal("-10.00")),
        household,
        weighted,
    )
    assert ten_dollars.amount_for("alex") == Decimal("-7.00")
    assert ten_dollars.amount_for("sam") == Decimal("-3.00")

    people_data = household_data()
    people_data["people"].append({"slug": "alex_alt", "name": "Alex"})
    three_person_household = load_household(write_household(tmp_path, people_data))
    data["sharing"] = [
        {
            "match": {"account": "Alex Checking", "description": "Three*"},
            "weights": {"alex": 0.3333, "sam": 0.3333, "alex_alt": 0.3334},
            "reason": "Example three-person split.",
        }
    ]
    three_person_declarations = load_declarations(
        write_declarations(tmp_path, data),
        people=three_person_household.slugs,
    )
    nickels = share_transaction(
        tx(description="Three-way charge", amount=Decimal("-0.05")),
        three_person_household,
        three_person_declarations,
    )

    assert nickels.amount_for("alex") == Decimal("-0.02")
    assert nickels.amount_for("sam") == Decimal("-0.02")
    assert nickels.amount_for("alex_alt") == Decimal("-0.01")
    assert sum((share.amount for share in nickels.shares), Decimal("0.00")) == Decimal("-0.05")


def test_person_total_sums_shares(tmp_path: Path) -> None:
    household = example_household()
    declarations = example_declarations(household)
    ledger = fixture_ledger(tmp_path)

    shares = share_ledger(ledger, household, declarations)

    assert person_total(shares, "alex") + person_total(shares, "sam") == Ledger.total(
        ledger.transactions
    )
