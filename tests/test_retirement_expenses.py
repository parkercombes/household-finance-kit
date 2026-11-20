"""Itemized retirement expenses and plan-seeded baselines (M8-03, R3; ADR-0008).

Hand-worked values, priced in 2026: a 400.00 a month expense growing 2 percent a
year faster than prices is 4800.00 in 2026, 4800 * 1.02 = 4896.00 in 2027, and
4800 * 1.02**9 = 5736.44 in 2035. A flat expense is the same every year, whatever
the household inflation assumption is.
"""

from __future__ import annotations

import copy
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from hfk.config import ConfigError, Month

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "retirement.example.yaml"
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
BASE_YEAR = 2026


def example() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")))


def load(tmp_path: Path, data: dict[str, Any] | None = None):
    from hfk.ext.retirement.schema import load_retirement

    data = example() if data is None else data
    path = tmp_path / "retirement.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return load_retirement(data, path)


def by_label(expenses, label: str, who: str | None = None):
    return next(e for e in expenses if e.label == label and e.who == who)


def yearly(expense, years) -> list[str]:
    return [str(expense.amount_in(year, base_year=BASE_YEAR)) for year in years]


def fixture_plan(tmp_path: Path):
    from hfk.config import load_declarations, load_household, load_instance_plan
    from hfk.source.fixture import build_fixture

    home = tmp_path / "instance"
    home.mkdir()
    for filename in ("household.yaml", "declarations.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, home / filename)
    build_fixture(home / "data" / "Tiller-Example.xlsx")
    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    return load_instance_plan(home, household=household, declarations=declarations)


def test_expense_inflation_follows_adr_0008(tmp_path):
    config = load(tmp_path)
    items = config.expenses.items

    assert yearly(by_label(items, "Housing"), [2026, 2040, 2067]) == ["18000.00"] * 3
    assert yearly(by_label(items, "Healthcare", "alex"), [2026, 2027, 2035]) == [
        "4800.00", "4896.00", "5736.44",
    ]
    assert yearly(by_label(items, "Car"), [2034, 2035, 2044, 2045]) == [
        "0.00", "3000.00", "3000.00", "0.00",
    ]

    # The household inflation assumption never touches expenses.
    changed = example()
    changed["assumptions"]["inflation"] = 0.05
    other = load(tmp_path, changed)
    for expense, same in zip(items, other.expenses.items, strict=True):
        assert yearly(expense, [2030, 2050]) == yearly(same, [2030, 2050])


def test_plan_seeded_baselines_match_the_fixture_plan(tmp_path):
    from hfk.ext.retirement.expenses import all_expenses

    plan = fixture_plan(tmp_path)
    data = example()
    data["expenses"] = {"seed_from_plan": {"month": "2026-08"}, "items": [
        {"label": "Travel", "monthly": 200},
    ]}
    config = load(tmp_path, data)
    assert config.expenses.seed_month == Month(2026, 8)

    expenses = all_expenses(config.expenses, plan, path=config.path)

    assert [(e.label, e.who, str(e.monthly), e.source) for e in expenses] == [
        ("Example Rent", "alex", "1200.00", "HFK Plan row 2"),
        ("Example Utilities", "alex", "90.00", "HFK Plan row 3"),
        ("Example Utilities", "sam", "90.00", "HFK Plan row 4"),
        ("Example Grocer", "alex", "550.00", "HFK Plan row 6"),
        ("Example Transit", "sam", "80.00", "HFK Plan row 7"),
        ("Example Streaming", "alex", "20.00", "HFK Plan row 8"),
        ("Example Cloud Renewal", "alex", "10.00", "HFK Plan row 9"),
        ("Example Cafe", "sam", "60.00", "HFK Plan row 10"),
        ("Travel", None, "200.00", "retirement.yaml"),
    ]
    assert all(e.real_growth == 0 for e in expenses)
    seeded_total = sum(e.amount_in(2040, base_year=BASE_YEAR) for e in expenses[:-1])
    assert seeded_total == Decimal("25200.00")  # 2100.00 a month, flat

    # A month before the grocer line changed seeds the earlier amount.
    data["expenses"]["seed_from_plan"]["month"] = "2025-03"
    earlier = all_expenses(load(tmp_path, data).expenses, plan, path=config.path)
    assert by_label(earlier, "Example Grocer", "alex").monthly == Decimal("500.00")


def test_seeding_fails_loudly_without_plan_lines(tmp_path):
    from hfk.ext.retirement.expenses import all_expenses

    plan = fixture_plan(tmp_path)
    data = example()
    data["expenses"]["seed_from_plan"] = {"month": "2024-12"}
    config = load(tmp_path, data)

    with pytest.raises(ConfigError, match="no lines effective in 2024-12"):
        all_expenses(config.expenses, plan, path=config.path)
    with pytest.raises(ConfigError) as caught:
        all_expenses(config.expenses, None, path=config.path)
    assert caught.value.file == config.path
    assert "hfk plan check" in caught.value.fix


@pytest.mark.parametrize(
    ("mutate", "key", "problem"),
    [
        (lambda d: d["expenses"]["items"][2].pop("reason"), "expenses.items[2].reason",
         "real_growth needs a reason"),
        (lambda d: d["expenses"]["items"][2].update(real_growth=0.5),
         "expenses.items[2].real_growth", "Invalid real_growth"),
        (lambda d: d["expenses"]["items"][0].update(who="pat"), "expenses.items[0].who",
         "Unknown person slug"),
        (lambda d: d["expenses"]["items"][1].update(label="Housing"), "expenses.items[1].label",
         "listed twice"),
        (lambda d: d["expenses"]["items"][0].update(monthly="lots"), "expenses.items[0].monthly",
         "Invalid amount"),
        (lambda d: d["expenses"]["items"][4].update(end_year=2030), "expenses.items[4].end_year",
         "before start_year"),
        (lambda d: d["expenses"].update(seed_from_plan={"month": "August"}),
         "expenses.seed_from_plan.month", "Invalid month"),
        (lambda d: d.__setitem__("expenses", {}), "expenses", "no items and no seed_from_plan"),
        (lambda d: d["expenses"]["items"][0].update(inflation=0.03), "expenses.items[0].inflation",
         "Unknown key"),
    ],
)
def test_invalid_expenses_fail_clearly(tmp_path, mutate, key, problem):
    data = example()
    mutate(data)
    with pytest.raises(ConfigError) as caught:
        load(tmp_path, data)
    assert caught.value.key == key
    assert problem in caught.value.problem
