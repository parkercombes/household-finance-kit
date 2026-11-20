"""Itemized retirement expenses in today's dollars (M8-03, R3; ADR-0008).

``retirement.yaml`` lists the household's need under ``expenses``::

    expenses:
      seed_from_plan: {month: 2026-08}
      items:
        - {label: "Housing", monthly: 1500}
        - {label: "Healthcare", who: alex, monthly: 400, real_growth: 0.02,
           reason: "medical costs have outpaced inflation"}
        - {label: "Car", monthly: 250, start_year: 2035, end_year: 2044}

Every amount is a monthly figure in today's dollars, and by ADR-0008 it stays
flat in today's dollars: the household ``inflation`` assumption never touches
expenses. One expense may declare its own ``real_growth``, a rate above (or
below) inflation, and must then say why in ``reason``. Its real amount in year
``Y`` is ``monthly * 12 * (1 + real_growth) ** (Y - base_year)``, where
``base_year`` is the year the amounts are priced in: the current year.

``who`` is optional; an expense without one belongs to the household as a
whole. ``start_year`` and an inclusive ``end_year`` limit an expense to some
years.

``seed_from_plan`` is optional. With it, every line of the household's own
plan (the workbook's ``HFK Plan`` sheet) effective in ``month`` becomes one
expense, with the line's description, person and monthly amount, and no
growth. Seeding is explicit: the month is the household's choice, and nothing
is summed, guessed, or dropped. The ``items`` add to the seeded lines.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from hfk.config import ConfigError, Month, Plan
from hfk.config._yaml import (
    reject_unknown_keys,
    require,
    require_list,
    require_mapping,
    require_text,
)
from hfk.config.errors import key_path
from hfk.ledger import money

EXPENSES_KEYS = ("seed_from_plan", "items")
SEED_KEYS = ("month",)
ITEM_KEYS = ("label", "who", "monthly", "real_growth", "reason", "start_year", "end_year")
MAX_REAL_GROWTH = Decimal("0.10")
MIN_REAL_GROWTH = Decimal("-0.10")
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Expense:
    label: str
    who: str | None
    monthly: Decimal
    real_growth: Decimal = Decimal(0)
    reason: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    source: str = "retirement.yaml"

    def amount_in(self, year: int, *, base_year: int) -> Decimal:
        """The expense's real (today's dollars) amount in calendar ``year``."""

        if self.start_year is not None and year < self.start_year:
            return ZERO
        if self.end_year is not None and year > self.end_year:
            return ZERO
        growth = (1 + self.real_growth) ** (year - base_year)
        return money(self.monthly * 12 * growth)


@dataclass(frozen=True)
class ExpensesConfig:
    seed_month: Month | None
    items: tuple[Expense, ...]


def load_expenses(value: Any, path: Path, *, people: tuple[str, ...]) -> ExpensesConfig:
    """Validate the ``expenses`` section of ``retirement.yaml``."""

    section = require_mapping(value, path, "expenses")
    reject_unknown_keys(section, EXPENSES_KEYS, path, "expenses")
    seed_month = None
    if "seed_from_plan" in section:
        seed = require_mapping(section["seed_from_plan"], path, "expenses", "seed_from_plan")
        reject_unknown_keys(seed, SEED_KEYS, path, "expenses", "seed_from_plan")
        raw = require(seed, "month", path, "expenses", "seed_from_plan")
        try:
            seed_month = Month.parse(str(raw))
        except ValueError:
            raise ConfigError(
                f"Invalid month {raw!r}",
                file=path,
                key="expenses.seed_from_plan.month",
                fix="write the plan month to copy as YYYY-MM",
            ) from None
    rows = require_list(section.get("items", []), path, "expenses", "items")
    if seed_month is None and not rows:
        raise ConfigError(
            "expenses lists no items and no seed_from_plan",
            file=path,
            key="expenses",
            fix="add items, or seed_from_plan: {month: YYYY-MM} to start from your plan",
        )
    items: list[Expense] = []
    labels: set[tuple[str, str | None]] = set()
    for index, row in enumerate(rows):
        parents = ("expenses", "items", f"[{index}]")
        entry = require_mapping(row, path, *parents)
        reject_unknown_keys(entry, ITEM_KEYS, path, *parents)
        label = require_text(require(entry, "label", path, *parents), path, *parents, "label")
        who = None
        if entry.get("who") is not None:
            who = require_text(entry["who"], path, *parents, "who")
            if who not in people:
                raise ConfigError(
                    f"Unknown person slug {who!r}",
                    file=path,
                    key=key_path(*parents, "who"),
                    fix=f"use one of {list(people)}, or leave who out for the household",
                )
        if (label, who) in labels:
            raise ConfigError(
                f"Expense {label!r} is listed twice",
                file=path,
                key=key_path(*parents, "label"),
                fix="give each expense its own label",
            )
        labels.add((label, who))
        monthly = _money(require(entry, "monthly", path, *parents), path, *parents, "monthly")
        real_growth = Decimal(0)
        reason = None
        if "real_growth" in entry:
            real_growth = _growth(entry["real_growth"], path, *parents, "real_growth")
            if "reason" not in entry:
                raise ConfigError(
                    "real_growth needs a reason",
                    file=path,
                    key=key_path(*parents, "reason"),
                    fix="say in one sentence why this cost grows faster or slower than prices",
                )
        if "reason" in entry:
            reason = require_text(entry["reason"], path, *parents, "reason")
        start_year = _year(entry, "start_year", path, *parents)
        end_year = _year(entry, "end_year", path, *parents)
        if start_year is not None and end_year is not None and end_year < start_year:
            raise ConfigError(
                f"end_year {end_year} is before start_year {start_year}",
                file=path,
                key=key_path(*parents, "end_year"),
                fix="use the same year as start_year or a later one",
            )
        items.append(
            Expense(label, who, monthly, real_growth, reason, start_year, end_year)
        )
    return ExpensesConfig(seed_month=seed_month, items=tuple(items))


def plan_expenses(plan: Plan, month: Month) -> tuple[Expense, ...]:
    """One expense per plan line effective in ``month``, with no growth."""

    lines = plan.lines_for(month)
    if not lines:
        raise ConfigError(
            f"the plan has no lines effective in {month}",
            file=plan.path,
            key="expenses.seed_from_plan.month",
            fix="choose a month your HFK Plan sheet covers in retirement.yaml",
        )
    expenses: list[Expense] = []
    for index, line in enumerate(plan.lines):
        if not line.is_effective(month):
            continue
        expenses.append(
            Expense(
                label=line.desc,
                who=line.who,
                monthly=line.monthly,
                source=plan.describe_line(index),
            )
        )
    return tuple(expenses)


def all_expenses(config: ExpensesConfig, plan: Plan | None, *, path: Path) -> tuple[Expense, ...]:
    """The seeded plan lines (when asked for) followed by the listed items."""

    if config.seed_month is None:
        return config.items
    if plan is None:
        raise ConfigError(
            "expenses.seed_from_plan needs the household's plan, which did not load",
            file=path,
            key="expenses.seed_from_plan",
            fix="fix the HFK Plan sheet (run hfk plan check), or remove seed_from_plan",
        )
    return plan_expenses(plan, config.seed_month) + config.items


def _money(value: Any, path: Path, *parents: str) -> Decimal:
    try:
        amount = (
            Decimal(str(value))
            if isinstance(value, (int, float, str)) and not isinstance(value, bool)
            else None
        )
    except InvalidOperation:
        amount = None
    if amount is None or not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise ConfigError(
            f"Invalid amount {value!r}",
            file=path,
            key=key_path(*parents),
            fix="write a monthly amount in today's dollars, at most two decimal places",
        )
    return money(amount)


def _growth(value: Any, path: Path, *parents: str) -> Decimal:
    try:
        rate = (
            Decimal(str(value))
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else None
        )
    except InvalidOperation:
        rate = None
    if rate is None or not rate.is_finite() or not MIN_REAL_GROWTH <= rate <= MAX_REAL_GROWTH:
        raise ConfigError(
            f"Invalid real_growth {value!r}",
            file=path,
            key=key_path(*parents),
            fix=f"write the yearly growth above inflation as a fraction from {MIN_REAL_GROWTH} "
            f"to {MAX_REAL_GROWTH}, such as 0.02",
        )
    return rate


def _year(entry: dict[str, Any], key: str, path: Path, *parents: str) -> int | None:
    if entry.get(key) is None:
        return None
    value = entry[key]
    if isinstance(value, int) and not isinstance(value, bool) and 1900 <= value <= 2200:
        return value
    raise ConfigError(
        f"Invalid {key} {value!r}",
        file=path,
        key=key_path(*parents, key),
        fix="write a four-digit calendar year, such as 2035",
    )


__all__ = ["Expense", "ExpensesConfig", "all_expenses", "load_expenses", "plan_expenses"]
