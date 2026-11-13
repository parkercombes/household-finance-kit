"""retirement.yaml people and household assumptions (M8-01, R1)."""

from __future__ import annotations

import copy
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from hfk.config import ConfigError, load_household

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "retirement.example.yaml"
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"


def example() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")))


def without_sam() -> dict[str, Any]:
    """The example with Sam, and Sam's income streams, removed."""

    data = example()
    del data["people"]["sam"]
    data["income"] = [stream for stream in data["income"] if stream["who"] != "sam"]
    return data


def load(tmp_path: Path, data: dict[str, Any]):
    from hfk.ext.retirement.schema import load_retirement

    path = tmp_path / "retirement.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return load_retirement(data, path)


def test_valid_fixture_config_loads(tmp_path):
    config = load(tmp_path, example())

    alex = config.person("alex")
    sam = config.person("sam")
    assert (alex.birth_year, alex.birth_month, alex.retire_year) == (1970, 6, 2035)
    assert alex.retire_age == 65
    assert sam.age_in(2040) == 68
    assert config.assumptions.until_age == 95
    assert config.assumptions.inflation == Decimal("0.025")
    assert config.first_year == 2035
    assert config.last_year == 1972 + 95
    assert config.schema_version == 1


@pytest.mark.parametrize(
    ("mutate", "key", "problem"),
    [
        (lambda d: d["people"]["alex"].update(birth="1970-13"), "people.alex.birth", "Invalid birth"),
        (lambda d: d["people"]["alex"].update(birth="June 1970"), "people.alex.birth", "Invalid birth"),
        (lambda d: d["people"]["alex"].update(birth=1970), "people.alex.birth", "Invalid birth"),
        (lambda d: d["people"]["alex"].update(retire_year="2035"), "people.alex.retire_year",
         "Invalid retire_year"),
        (lambda d: d["people"]["alex"].update(retire_year=1980), "people.alex.retire_year",
         "makes alex 10 at retirement"),
        (lambda d: d["people"]["alex"].update(retire_year=2075), "people.alex.retire_year",
         "makes alex 105 at retirement"),
        (lambda d: d["people"]["alex"].pop("retire_year"), "people.alex.retire_year",
         "Missing required key"),
        (lambda d: d.pop("people"), "people", "Missing required key"),
        (lambda d: d.__setitem__("people", {}), "people", "at least one person"),
        (lambda d: d["people"].__setitem__("Al Ex", {"birth": "1970-06", "retire_year": 2035}),
         'people."Al Ex"', "Invalid person slug"),
        (lambda d: d["assumptions"].pop("until_age"), "assumptions.until_age", "Missing required key"),
        (lambda d: d["assumptions"].update(until_age=200), "assumptions.until_age",
         "Invalid until_age"),
        (lambda d: d["assumptions"].update(inflation=2.5), "assumptions.inflation", "Invalid rate"),
        (lambda d: d["assumptions"].update(inflation="lots"), "assumptions.inflation",
         "Invalid rate"),
        (lambda d: d.__setitem__("colour", "blue"), "colour", "Unknown key"),
    ],
)
def test_invalid_dates_or_missing_people_fail_clearly(tmp_path, mutate, key, problem):
    data = example()
    mutate(data)
    with pytest.raises(ConfigError) as caught:
        load(tmp_path, data)
    assert caught.value.key == key
    assert problem in caught.value.problem
    assert caught.value.fix


def test_people_must_match_household(tmp_path):
    from hfk.ext.retirement.schema import check_people

    household = load_household(INSTANCE_EXAMPLE)
    check_people(load(tmp_path, example()), household)

    missing = without_sam()
    with pytest.raises(ConfigError) as caught:
        check_people(load(tmp_path, missing), household)
    assert caught.value.key == "people"
    assert "Person 'sam' from household.yaml is missing" in caught.value.problem

    extra = example()
    extra["people"]["pat"] = {"birth": "1980-01", "retire_year": 2045}
    with pytest.raises(ConfigError) as caught:
        check_people(load(tmp_path, extra), household)
    assert caught.value.key == "people.pat"


def test_doctor_checks_retirement_when_enabled(tmp_path):
    from hfk.engine import run_doctor
    from hfk.ext import load_extensions
    from hfk.ext.doctor import extension_doctor_hooks
    from hfk.source.fixture import build_fixture

    home = tmp_path / "instance"
    home.mkdir()
    for filename in ("household.yaml", "declarations.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, home / filename)
    data = yaml.safe_load((home / "household.yaml").read_text(encoding="utf-8"))
    data["extensions"] = ["settle_up", "retirement"]
    (home / "household.yaml").write_text(yaml.safe_dump(data, sort_keys=False), "utf-8")
    build_fixture(home / "data" / "Tiller-Example.xlsx")

    def doctor():
        return run_doctor(home, today=date(2026, 10, 1),
                          hooks=extension_doctor_hooks(load_extensions()))

    missing = doctor()
    assert [d.code for d in missing.errors()] == ["extension-config"]
    assert "retirement is enabled but its config file is missing" in missing.errors()[0].message

    shutil.copyfile(EXAMPLE, home / "retirement.yaml")
    assert doctor().ok

    broken = without_sam()
    (home / "retirement.yaml").write_text(yaml.safe_dump(broken), encoding="utf-8")
    errors = doctor().errors()
    assert [(d.code, d.where) for d in errors] == [("retirement-config", "retirement.yaml key=people")]
