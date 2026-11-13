"""Off-ledger shared items for settle-up (M7-03)."""

from __future__ import annotations

import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from hfk.config import ConfigError, Month, load_declarations, load_household
from hfk.ext.settle_up.items import (
    check_shared_items_dir,
    load_shared_items,
    shared_items_path,
)

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
MONTH = Month(2026, 8)

VALID = {
    "schema_version": 1,
    "items": [
        {
            "label": "Example utility bill",
            "amount": 120.00,
            "paid_by": "alex",
            "weights": {"alex": 0.5, "sam": 0.5},
            "bucket": "Fixed Essential",
        },
        {
            "label": "Example shared supplies",
            "amount": "40.10",
            "paid_by": "sam",
            "weights": {"alex": 0.6, "sam": 0.4},
            "bucket": "Variable Essential",
        },
    ],
}


def make_home(tmp_path: Path) -> Path:
    for filename in ("household.yaml", "declarations.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, tmp_path / filename)
    (tmp_path / "shared-items").mkdir()
    return tmp_path


def write(home: Path, data: object, name: str = "2026-08.yaml") -> Path:
    path = home / "shared-items" / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def load(home: Path, month: Month = MONTH):
    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    return load_shared_items(home, month, household=household, declarations=declarations)


def edited(**changes: object) -> dict:
    data = yaml.safe_load(yaml.safe_dump(VALID))
    data["items"][0].update(changes)
    return data


def test_valid_shared_items_load(tmp_path):
    home = make_home(tmp_path)
    write(home, VALID)

    loaded = load(home)

    assert loaded.exists
    assert loaded.path == shared_items_path(home, MONTH)
    first, second = loaded.items
    assert first.amount == Decimal("120.00")
    assert first.paid_by == "alex"
    assert first.weights == (("alex", Decimal("0.5")), ("sam", Decimal("0.5")))
    assert second.amount == Decimal("40.10")
    assert second.weight("alex") == Decimal("0.6")
    assert second.bucket == "Variable Essential"


def test_absent_month_has_no_items(tmp_path):
    home = make_home(tmp_path)
    loaded = load(home, Month(2026, 7))
    assert not loaded.exists
    assert loaded.items == ()


@pytest.mark.parametrize(
    ("changes", "key", "problem"),
    [
        ({"weights": {"alex": 0.6, "sam": 0.6}}, "items[0].weights", "Weights sum to 1.2, not 1"),
        ({"weights": {"alex": 1.5}}, "items[0].weights.alex", "Invalid weight"),
        ({"weights": {}}, "items[0].weights", "weights is empty"),
        ({"weights": {"alex": 0.5, "pat": 0.5}}, "items[0].weights.pat", "Unknown person slug"),
        ({"paid_by": "pat"}, "items[0].paid_by", "Unknown person slug 'pat'"),
        ({"amount": -5}, "items[0].amount", "Invalid amount"),
        ({"amount": 10.005}, "items[0].amount", "Invalid amount"),
        ({"amount": "lots"}, "items[0].amount", "Invalid amount"),
        ({"bucket": "Treats"}, "items[0].bucket", "Unknown bucket 'Treats'"),
        ({"colour": "blue"}, "items[0].colour", "Unknown key 'colour'"),
    ],
)
def test_invalid_weights_people_and_fields_fail(tmp_path, changes, key, problem):
    home = make_home(tmp_path)
    path = write(home, edited(**changes))

    with pytest.raises(ConfigError) as caught:
        load(home)

    assert caught.value.file == path
    assert caught.value.key == key
    assert problem in caught.value.problem
    assert caught.value.fix


def test_missing_item_key_fails(tmp_path):
    home = make_home(tmp_path)
    data = yaml.safe_load(yaml.safe_dump(VALID))
    del data["items"][1]["paid_by"]
    write(home, data)
    with pytest.raises(ConfigError) as caught:
        load(home)
    assert caught.value.key == "items[1].paid_by"


@pytest.mark.parametrize("name", ["2026-13.yaml", "August.yaml", "2026-8.yaml", "2026-08.yml"])
def test_badly_named_month_files_fail(tmp_path, name):
    home = make_home(tmp_path)
    write(home, VALID, name=name)
    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)

    problems = check_shared_items_dir(home, household=household, declarations=declarations)

    assert len(problems) == 1
    assert problems[0].file.name == name
    assert "is not named after a month" in problems[0].problem


def test_doctor_reports_shared_item_problems(tmp_path):
    from hfk.engine import run_doctor
    from hfk.ext import load_extensions
    from hfk.ext.doctor import extension_doctor_hooks
    from hfk.source.fixture import build_fixture

    home = make_home(tmp_path)
    build_fixture(home / "data" / "Tiller-Example.xlsx")
    shutil.copyfile(ROOT / "src" / "hfk" / "templates" / "shared-items-README.md",
                    home / "shared-items" / "README.md")
    write(home, VALID)
    write(home, edited(paid_by="pat"), name="2026-07.yaml")
    write(home, VALID, name="Sept.yaml")

    report = run_doctor(
        home, today=date(2026, 10, 1), hooks=extension_doctor_hooks(load_extensions())
    )

    found = sorted(d.where for d in report.errors() if d.code == "settle-up-shared-items")
    assert found == [
        "shared-items/2026-07.yaml key=items[0].paid_by",
        "shared-items/Sept.yaml key=(file)",
    ]
