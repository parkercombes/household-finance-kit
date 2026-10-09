"""Config loaders: household.yaml (M2-01)."""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from hfk.config import ConfigError, Household, load_household

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "household.example.yaml"


def example_data() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")))


def write_household(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "household.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


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


def test_household_objects_are_frozen() -> None:
    household = load_household(EXAMPLE)

    with pytest.raises(AttributeError):
        household.people = ()  # type: ignore[misc]
    with pytest.raises(AttributeError):
        household.accounts[0].name = "x"  # type: ignore[misc]
