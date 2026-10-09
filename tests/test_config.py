"""Config loaders: household.yaml (M2-01)."""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from hfk.config import (
    ConfigError,
    Declarations,
    Household,
    Month,
    Plan,
    load_declarations,
    load_household,
    load_plan,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "household.example.yaml"
DECLARATIONS_EXAMPLE = ROOT / "examples" / "declarations.example.yaml"
PLAN_EXAMPLE = ROOT / "examples" / "plan.example.yaml"
PROFILES = ROOT / "profiles"


def example_data() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")))


def write_household(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "household.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def declarations_data() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(DECLARATIONS_EXAMPLE.read_text(encoding="utf-8")))


def write_declarations(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "declarations.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def plan_data() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(PLAN_EXAMPLE.read_text(encoding="utf-8")))


def write_plan(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "plan.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def example_declarations() -> Declarations:
    return load_declarations(DECLARATIONS_EXAMPLE, people=("alex", "sam"))


def test_example_household_loads() -> None:
    household = load_household(EXAMPLE)

    assert isinstance(household, Household)
    assert household.path == EXAMPLE
    assert household.schema_version == 1
    assert household.slugs == ("alex", "sam")
    assert household.person("sam").name == "Sam"
    assert household.tiller_glob == "Tiller*.xls*"
    assert household.history_start == date(2025, 1, 1)
    assert household.extensions == ("settle_up", "retirement")

    joint = household.account("Joint Card")
    assert joint.owner is None
    assert joint.weights == (("alex", Decimal("0.5")), ("sam", Decimal("0.5")))
    assert joint.weight("sam") == Decimal("0.5")

    savings = household.account("Savings")
    assert savings.owner == "alex"
    assert savings.kind == "savings"
    assert savings.weight("sam") == Decimal(0)
    assert household.account("Nope") is None


def test_household_loader_accepts_home_directory(tmp_path: Path) -> None:
    write_household(tmp_path, example_data())

    assert load_household(tmp_path).path == tmp_path / "household.yaml"


@pytest.mark.parametrize(
    "missing",
    ["schema_version", "people", "files", "files.tiller_glob", "accounts", "people[0].slug"],
)
def test_household_loader_validates_required_fields(tmp_path: Path, missing: str) -> None:
    data = example_data()
    parts = missing.replace("[", ".[").split(".")
    target: Any = data
    for part in parts[:-1]:
        target = target[int(part[1:-1])] if part.startswith("[") else target[part]
    last = parts[-1]
    if last.startswith("["):
        del target[int(last[1:-1])]
    else:
        del target[last]
    path = write_household(tmp_path, data)

    with pytest.raises(ConfigError) as error:
        load_household(path)

    message = str(error.value)
    assert f"file={path}" in message
    assert f"key={missing}" in message
    assert "fix=" in message


def test_missing_file_names_the_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as error:
        load_household(tmp_path)

    assert "Missing config file" in str(error.value)
    assert str(tmp_path / "household.yaml") in str(error.value)


def test_history_start_is_optional_and_must_be_a_date(tmp_path: Path) -> None:
    data = example_data()
    del data["history_start"]
    assert load_household(write_household(tmp_path, data)).history_start is None

    data["history_start"] = "2025-01-01"
    assert load_household(write_household(tmp_path, data)).history_start == date(2025, 1, 1)

    data["history_start"] = "January 2025"
    with pytest.raises(ConfigError, match="key=history_start"):
        load_household(write_household(tmp_path, data))


def test_extensions_default_to_none_enabled(tmp_path: Path) -> None:
    data = example_data()
    del data["extensions"]

    assert load_household(write_household(tmp_path, data)).extensions == ()


@pytest.mark.parametrize(
    ("mutate", "expected_key"),
    [
        (lambda d: d.__setitem__("schema_version", 2), "schema_version"),
        (lambda d: d.__setitem__("budget", {}), "budget"),
        (lambda d: d["people"].append({"slug": "alex", "name": "Again"}), "people[2].slug"),
        (lambda d: d["people"].append({"slug": "Al Ex", "name": "Al"}), "people[2].slug"),
        (lambda d: d["people"].clear(), "people"),
        (lambda d: d["accounts"].__setitem__("Nope", {"owner": "pat"}), 'accounts.Nope.owner'),
        (lambda d: d["accounts"].__setitem__("Both", {"owner": "alex", "shared": {"alex": 1}}), "accounts.Both"),
        (lambda d: d["accounts"].__setitem__("Neither", {"kind": "savings"}), "accounts.Neither"),
        (lambda d: d["accounts"].__setitem__("Typo", {"onwer": "alex"}), "accounts.Typo.onwer"),
        (lambda d: d["accounts"].__setitem__("Joint Card", {"shared": {"alex": 0.6, "sam": 0.5}}), 'accounts."Joint Card".shared'),
        (lambda d: d["accounts"].__setitem__("Joint Card", {"shared": {"alex": 0, "sam": 1}}), 'accounts."Joint Card".shared.alex'),
        (lambda d: d["accounts"].__setitem__("Joint Card", {"shared": {"alex": "half", "sam": 0.5}}), 'accounts."Joint Card".shared.alex'),
        (lambda d: d["accounts"].__setitem__("Joint Card", {"shared": {}}), 'accounts."Joint Card".shared'),
        (lambda d: d["accounts"].clear(), "accounts"),
        (lambda d: d["files"].__setitem__("tiller_glob", "data/Tiller*.xlsx"), "files.tiller_glob"),
        (lambda d: d.__setitem__("extensions", "settle_up"), "extensions"),
        (lambda d: d["extensions"].append("settle_up"), "extensions[2]"),
        (lambda d: d["extensions"].append("Settle Up"), "extensions[2]"),
    ],
)
def test_household_loader_rejects_invalid_values(tmp_path: Path, mutate: Any, expected_key: str) -> None:
    data = example_data()
    mutate(data)
    path = write_household(tmp_path, data)

    with pytest.raises(ConfigError) as error:
        load_household(path)

    assert error.value.key == expected_key
    assert error.value.file == path
    assert error.value.fix


def test_shared_weights_are_exact_decimals(tmp_path: Path) -> None:
    data = example_data()
    data["accounts"]["Joint Card"] = {"shared": {"alex": 0.7, "sam": 0.3}}

    joint = load_household(write_household(tmp_path, data)).account("Joint Card")

    assert joint.weights == (("alex", Decimal("0.7")), ("sam", Decimal("0.3")))
    assert sum(weight for _slug, weight in joint.weights) == Decimal(1)


def test_household_unsynced_flag_loads_and_rejects_non_bool(tmp_path: Path) -> None:
    data = example_data()
    data["accounts"]["Savings"]["unsynced"] = True

    household = load_household(write_household(tmp_path, data))

    assert household.account("Savings").unsynced is True
    assert household.account("Alex Checking").unsynced is False

    data = example_data()
    household = load_household(write_household(tmp_path, data))
    assert household.account("Savings").unsynced is False

    data = example_data()
    data["accounts"]["Savings"]["unsynced"] = "yes"
    path = write_household(tmp_path, data)

    with pytest.raises(ConfigError) as error:
        load_household(path)

    assert error.value.key == "accounts.Savings.unsynced"
    assert error.value.file == path
    assert error.value.fix == "write unsynced as true or false"
    assert "unsynced" in str(error.value)


def test_household_objects_are_frozen() -> None:
    household = load_household(EXAMPLE)

    with pytest.raises(AttributeError):
        household.people = ()  # type: ignore[misc]
    with pytest.raises(AttributeError):
        household.accounts[0].name = "x"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("mutate", "expected_key"),
    [
        (lambda d: d["overrides"]["Utilities"].pop("reason"), "overrides.Utilities.reason"),
        (lambda d: d["splits"]["Fuel"].pop("reason"), "splits.Fuel.reason"),
        (lambda d: d["sharing"][0].pop("reason"), "sharing[0].reason"),
        (
            lambda d: d["sharing"][0].__setitem__("weights", {"alex": 0.4, "sam": 0.5}),
            "sharing[0].weights",
        ),
    ],
)
def test_declarations_loader_requires_reasons(
    tmp_path: Path, mutate: Any, expected_key: str
) -> None:
    data = declarations_data()
    mutate(data)
    path = write_declarations(tmp_path, data)

    with pytest.raises(ConfigError) as error:
        load_declarations(path, people=("alex", "sam"))

    assert error.value.key == expected_key
    assert error.value.file == path
    assert error.value.fix


def test_example_declarations_load() -> None:
    declarations = load_declarations(DECLARATIONS_EXAMPLE, people=("alex", "sam"))

    assert isinstance(declarations, Declarations)
    assert declarations.path == DECLARATIONS_EXAMPLE
    assert declarations.bucket_names() == (
        "Fixed Essential",
        "Variable Essential",
        "Fixed Discretionary",
        "Variable Discretionary",
    )
    assert declarations.groups == (
        ("Housing", "Fixed Essential"),
        ("Food", "Variable Essential"),
        ("Transportation", "Variable Essential"),
        ("Subscriptions", "Fixed Discretionary"),
    )

    utilities = declarations.override("Utilities")
    assert utilities.bucket == "Variable Essential"
    assert utilities.reason == "Utilities vary by season; the rest of Housing is fixed."

    fuel = declarations.split("Fuel")
    assert fuel.weights == (
        ("Variable Essential", Decimal("0.5")),
        ("Variable Discretionary", Decimal("0.5")),
    )

    rule = declarations.sharing[0]
    assert rule.account == "Alex Checking"
    assert rule.description == "City Utilities*"
    assert rule.weights == (("alex", Decimal("0.5")), ("sam", Decimal("0.5")))
    assert declarations.closed_accounts == ()


def test_declarations_profile_import(tmp_path: Path) -> None:
    data = declarations_data()
    expected_buckets = tuple(bucket["name"] for bucket in data.pop("buckets"))
    data["profile"] = "four-bucket"
    declarations = load_declarations(write_declarations(tmp_path, data), profiles_dir=PROFILES)

    assert declarations.profile == "four-bucket"
    assert declarations.bucket_names() == expected_buckets

    data["profile"] = "unknown-profile"
    path = write_declarations(tmp_path, data)
    with pytest.raises(ConfigError) as error:
        load_declarations(path, profiles_dir=PROFILES)

    assert error.value.file == PROFILES / "unknown-profile.yaml"


def test_declarations_mapping_source_rules(tmp_path: Path) -> None:
    data = declarations_data()
    data["mapping_source"] = "explicit"
    del data["groups"]
    data["categories"] = {"Rent": "Fixed Essential"}
    declarations = load_declarations(write_declarations(tmp_path, data))
    assert declarations.categories == (("Rent", "Fixed Essential"),)
    assert declarations.groups == ()

    data = declarations_data()
    data["categories"] = {"Rent": "Fixed Essential"}
    with pytest.raises(ConfigError) as error:
        load_declarations(write_declarations(tmp_path, data))
    assert error.value.key == "categories"

    data = declarations_data()
    data["mapping_source"] = "explicit"
    data["categories"] = {"Rent": "Fixed Essential"}
    with pytest.raises(ConfigError) as error:
        load_declarations(write_declarations(tmp_path, data))
    assert error.value.key == "groups"

    data = declarations_data()
    del data["mapping_source"]
    declarations = load_declarations(write_declarations(tmp_path, data))
    assert declarations.mapping_source == "tiller_group"
    assert declarations.groups

    data = declarations_data()
    data["mapping_source"] = "spreadsheet"
    with pytest.raises(ConfigError) as error:
        load_declarations(write_declarations(tmp_path, data))
    assert error.value.key == "mapping_source"


@pytest.mark.parametrize(
    ("mutate", "expected_key"),
    [
        (lambda d: d["groups"].__setitem__("Housing", "Unknown"), "groups.Housing"),
        (
            lambda d: d["overrides"]["Utilities"].__setitem__("bucket", "Unknown"),
            "overrides.Utilities.bucket",
        ),
        (
            lambda d: d["splits"]["Fuel"].__setitem__(
                "weights", {"Unknown": 0.5, "Variable Essential": 0.5}
            ),
            "splits.Fuel.weights.Unknown",
        ),
        (
            lambda d: d["overrides"].__setitem__(
                "Fuel", {"bucket": "Variable Essential", "reason": "Round example reason."}
            ),
            "splits.Fuel",
        ),
    ],
)
def test_declarations_reject_unknown_buckets_and_conflicts(
    tmp_path: Path, mutate: Any, expected_key: str
) -> None:
    data = declarations_data()
    mutate(data)
    path = write_declarations(tmp_path, data)

    with pytest.raises(ConfigError) as error:
        load_declarations(path)

    assert error.value.key == expected_key
    assert error.value.file == path


def test_declarations_people_check(tmp_path: Path) -> None:
    data = declarations_data()
    data["sharing"][0]["weights"] = {"alex": 0.5, "unknown": 0.5}
    path = write_declarations(tmp_path, data)

    with pytest.raises(ConfigError) as error:
        load_declarations(path, people=("alex", "sam"))

    assert error.value.key == "sharing[0].weights.unknown"
    assert load_declarations(path, people=None).sharing[0].weights == (
        ("alex", Decimal("0.5")),
        ("unknown", Decimal("0.5")),
    )


def test_declarations_closed_accounts(tmp_path: Path) -> None:
    data = declarations_data()
    data["closed_accounts"] = {
        "Example Bank Card": {"closed": date(2025, 5, 1), "note": "Closed after payoff."}
    }
    declarations = load_declarations(write_declarations(tmp_path, data))

    closed = declarations.closed_account("Example Bank Card")
    assert closed.closed == date(2025, 5, 1)
    assert closed.note == "Closed after payoff."

    data["closed_accounts"]["Example Bank Card"]["closed"] = "05/01/2025"
    with pytest.raises(ConfigError) as error:
        load_declarations(write_declarations(tmp_path, data))

    assert error.value.key == 'closed_accounts."Example Bank Card".closed'


def test_plan_loader_validates_annual_bill_math(tmp_path: Path) -> None:
    declarations = example_declarations()
    plan = load_plan(PLAN_EXAMPLE, declarations=declarations, people=("alex", "sam"))
    assert plan.lines[7].monthly == Decimal("10.00")

    data = plan_data()
    data["plan"]["lines"][7]["monthly"] = 11.00
    path = write_plan(tmp_path, data)
    with pytest.raises(ConfigError) as error:
        load_plan(path, declarations=declarations, people=("alex", "sam"))
    assert error.value.key == "plan.lines[7].monthly"
    assert error.value.file == path

    data = plan_data()
    data["plan"]["lines"][7]["annual_full"] = 119.00
    path = write_plan(tmp_path, data)
    with pytest.raises(ConfigError) as error:
        load_plan(path, declarations=declarations, people=("alex", "sam"))
    assert error.value.key == "plan.lines[7].annual_full"
    assert error.value.file == path


def test_plan_loader_rejects_unknown_bucket(tmp_path: Path) -> None:
    declarations = example_declarations()
    data = plan_data()
    data["plan"]["lines"][0]["bucket"] = "Savings Goal"
    path = write_plan(tmp_path, data)

    with pytest.raises(ConfigError) as error:
        load_plan(path, declarations=declarations, people=("alex", "sam"))

    assert error.value.key == "plan.lines[0].bucket"
    assert error.value.file == path
    message = str(error.value)
    for bucket in declarations.bucket_names():
        assert bucket in message


def test_example_plan_loads() -> None:
    plan = load_plan(PLAN_EXAMPLE, declarations=example_declarations(), people=("alex", "sam"))

    assert isinstance(plan, Plan)
    assert len(plan.lines) == 9
    assert plan.effective_from == Month(2025, 1)
    assert plan.lines[3].effective_until == Month(2025, 6)

    alex_march = plan.lines_for(Month(2025, 3), "alex")
    assert any(line.desc == "Example Grocer" and line.monthly == Decimal("500.00") for line in alex_march)
    assert not any(
        line.desc == "Example Grocer" and line.monthly == Decimal("550.00") for line in alex_march
    )

    alex_august = plan.lines_for(Month(2025, 8), "alex")
    assert any(
        line.desc == "Example Grocer" and line.monthly == Decimal("550.00") for line in alex_august
    )
    assert not any(
        line.desc == "Example Grocer" and line.monthly == Decimal("500.00") for line in alex_august
    )

    streaming = plan.lines[6]
    assert streaming.categories == ()
    assert streaming.paced is False
    assert plan.lines[7].due == (7, 1)


@pytest.mark.parametrize("value", ["2025-13", "2025-1", date(2025, 1, 1), 202501])
def test_plan_month_parsing(tmp_path: Path, value: Any) -> None:
    assert Month.parse("2025-01") == Month(2025, 1)
    assert str(Month(2025, 1)) == "2025-01"

    data = plan_data()
    data["plan"]["effective_from"] = value
    path = write_plan(tmp_path, data)

    with pytest.raises(ConfigError) as error:
        load_plan(path, declarations=example_declarations(), people=("alex", "sam"))

    assert error.value.key == "plan.effective_from"
    assert error.value.file == path
    assert error.value.fix == "write the month as YYYY-MM"


def test_plan_line_date_rules(tmp_path: Path) -> None:
    declarations = example_declarations()
    data = plan_data()
    data["plan"]["lines"][0]["effective_from"] = "2024-12"
    path = write_plan(tmp_path, data)
    with pytest.raises(ConfigError) as error:
        load_plan(path, declarations=declarations, people=("alex", "sam"))
    assert error.value.key == "plan.lines[0].effective_from"
    assert error.value.file == path

    data = plan_data()
    data["plan"]["lines"][0]["effective_from"] = "2025-05"
    data["plan"]["lines"][0]["effective_until"] = "2025-04"
    path = write_plan(tmp_path, data)
    with pytest.raises(ConfigError) as error:
        load_plan(path, declarations=declarations, people=("alex", "sam"))
    assert error.value.key == "plan.lines[0].effective_until"
    assert error.value.file == path


def test_plan_rejects_type_key(tmp_path: Path) -> None:
    data = plan_data()
    data["plan"]["lines"][0]["type"] = "Fixed Essential"
    path = write_plan(tmp_path, data)

    with pytest.raises(ConfigError) as error:
        load_plan(path, declarations=example_declarations(), people=("alex", "sam"))

    assert error.value.key == "plan.lines[0].type"
    assert error.value.file == path
    assert "bucket" in error.value.fix


def test_plan_people_check(tmp_path: Path) -> None:
    declarations = example_declarations()
    data = plan_data()
    data["plan"]["lines"][0]["who"] = "pat"
    path = write_plan(tmp_path, data)

    with pytest.raises(ConfigError) as error:
        load_plan(path, declarations=declarations, people=("alex", "sam"))
    assert error.value.key == "plan.lines[0].who"
    assert error.value.file == path

    plan = load_plan(path, declarations=declarations, people=None)
    assert plan.lines[0].who == "pat"


def test_plan_rejects_unknown_line_keys(tmp_path: Path) -> None:
    data = plan_data()
    data["plan"]["lines"][0]["extra"] = "remove me"
    path = write_plan(tmp_path, data)

    with pytest.raises(ConfigError) as error:
        load_plan(path, declarations=example_declarations(), people=("alex", "sam"))

    assert error.value.key == "plan.lines[0].extra"
    assert error.value.file == path
    assert "extra" in str(error.value)
