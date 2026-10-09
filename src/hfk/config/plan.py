"""Load and validate ``plan.yaml`` (design brief section 6; ADR-0010)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from hfk.config._yaml import (
    load_mapping,
    reject_unknown_keys,
    require,
    require_bool,
    require_list,
    require_mapping,
    require_schema_version,
    require_text,
)
from hfk.config.declarations import Declarations
from hfk.config.errors import ConfigError, key_path
from hfk.ledger import money

PLAN_FILE = "plan.yaml"
CENT = Decimal("0.01")
MONTH_TEXT = re.compile(r"^(\d{4})-(\d{2})$")
TOP_LEVEL_KEYS = ("schema_version", "plan")
PLAN_KEYS = ("effective_from", "lines")
LINE_KEYS = (
    "desc",
    "who",
    "bucket",
    "monthly",
    "categories",
    "paced",
    "effective_from",
    "effective_until",
    "annual_bill",
    "annual_full",
    "account",
    "due",
)
DUE_KEYS = ("month", "day")
ANNUAL_DEPENDENT_KEYS = ("annual_full", "account", "due")


@dataclass(frozen=True, order=True)
class Month:
    year: int
    month: int

    @classmethod
    def parse(cls, text: str) -> Month:
        match = MONTH_TEXT.fullmatch(text.strip())
        if match is None:
            raise ValueError(f"Invalid month {text!r}")
        year = int(match.group(1))
        month = int(match.group(2))
        if not 1 <= month <= 12:
            raise ValueError(f"Invalid month {text!r}")
        return cls(year, month)

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


@dataclass(frozen=True)
class PlanLine:
    desc: str
    who: str
    bucket: str
    monthly: Decimal
    categories: tuple[str, ...]
    paced: bool
    effective_from: Month
    effective_until: Month | None
    annual_bill: Decimal | None
    annual_full: Decimal | None
    account: str | None
    due: tuple[int, int] | None

    def is_effective(self, month: Month) -> bool:
        if month < self.effective_from:
            return False
        return self.effective_until is None or month <= self.effective_until


@dataclass(frozen=True)
class Plan:
    path: Path
    schema_version: int
    effective_from: Month
    lines: tuple[PlanLine, ...]

    def lines_for(self, month: Month, who: str | None = None) -> tuple[PlanLine, ...]:
        return tuple(
            line
            for line in self.lines
            if line.is_effective(month) and (who is None or line.who == who)
        )


def plan_path(home: Path) -> Path:
    return Path(home) / PLAN_FILE


def load_plan(
    home_or_file: Path, *, declarations: Declarations, people: Iterable[str] | None = None
) -> Plan:
    """Load ``plan.yaml`` from an instance home directory or explicit file path."""

    path = Path(home_or_file)
    if path.is_dir():
        path = plan_path(path)
    data = load_mapping(path)
    reject_unknown_keys(data, TOP_LEVEL_KEYS, path)

    schema_version = require_schema_version(data, path)
    plan = require_mapping(require(data, "plan", path), path, "plan")
    reject_unknown_keys(plan, PLAN_KEYS, path, "plan")
    effective_from = _require_month(require(plan, "effective_from", path, "plan"), path, "plan", "effective_from")
    bucket_names = declarations.bucket_names()
    lines = _lines(
        require(plan, "lines", path, "plan"),
        plan_effective_from=effective_from,
        bucket_names=bucket_names,
        people=None if people is None else tuple(people),
        path=path,
    )
    return Plan(
        path=path,
        schema_version=schema_version,
        effective_from=effective_from,
        lines=lines,
    )


def _lines(
    value: Any,
    *,
    plan_effective_from: Month,
    bucket_names: tuple[str, ...],
    people: tuple[str, ...] | None,
    path: Path,
) -> tuple[PlanLine, ...]:
    rows = require_list(value, path, "plan", "lines")
    if not rows:
        raise ConfigError(
            "plan.lines must list at least one line",
            file=path,
            key="plan.lines",
            fix="add at least one budget line",
        )
    declared_buckets = set(bucket_names)
    known_people = None if people is None else set(people)
    lines: list[PlanLine] = []
    for index, row in enumerate(rows):
        parents = ("plan", "lines", f"[{index}]")
        entry = require_mapping(row, path, *parents)
        if "type" in entry:
            raise ConfigError(
                "Plan lines use bucket, not type",
                file=path,
                key=key_path(*parents, "type"),
                fix="rename type to bucket; Type already means Expense/Income/Transfer in Tiller",
            )
        reject_unknown_keys(entry, LINE_KEYS, path, *parents)
        lines.append(
            _line(
                entry,
                plan_effective_from=plan_effective_from,
                bucket_names=bucket_names,
                declared_buckets=declared_buckets,
                people=people,
                known_people=known_people,
                path=path,
                parents=parents,
            )
        )
    return tuple(lines)


def _line(
    entry: dict[str, Any],
    *,
    plan_effective_from: Month,
    bucket_names: tuple[str, ...],
    declared_buckets: set[str],
    people: tuple[str, ...] | None,
    known_people: set[str] | None,
    path: Path,
    parents: tuple[str, ...],
) -> PlanLine:
    for key in ANNUAL_DEPENDENT_KEYS:
        if key in entry and "annual_bill" not in entry:
            raise ConfigError(
                f"{key} requires annual_bill",
                file=path,
                key=key_path(*parents, key),
                fix="add annual_bill or remove this key",
            )

    desc = require_text(require(entry, "desc", path, *parents), path, *parents, "desc")
    who = require_text(require(entry, "who", path, *parents), path, *parents, "who")
    if known_people is not None and who not in known_people:
        raise ConfigError(
            f"Unknown person slug {who!r}",
            file=path,
            key=key_path(*parents, "who"),
            fix=f"use one of {list(people or ())} or add the person to household.yaml",
        )
    bucket = require_text(require(entry, "bucket", path, *parents), path, *parents, "bucket")
    if bucket not in declared_buckets:
        raise ConfigError(
            f"Unknown bucket {bucket!r}",
            file=path,
            key=key_path(*parents, "bucket"),
            fix=f"use one of {list(bucket_names)}",
        )

    monthly = _require_money(
        require(entry, "monthly", path, *parents),
        path,
        *parents,
        "monthly",
        minimum=Decimal("0.00"),
    )
    categories = _categories(entry.get("categories", []), path, *parents, "categories")
    paced = False
    if "paced" in entry:
        paced = require_bool(entry["paced"], path, *parents, "paced")
    effective_from = plan_effective_from
    if "effective_from" in entry:
        effective_from = _require_month(entry["effective_from"], path, *parents, "effective_from")
    if effective_from < plan_effective_from:
        raise ConfigError(
            "Line effective_from is before plan.effective_from",
            file=path,
            key=key_path(*parents, "effective_from"),
            fix=f"use {plan_effective_from} or a later month",
        )
    effective_until = None
    if "effective_until" in entry:
        effective_until = _require_month(entry["effective_until"], path, *parents, "effective_until")
        if effective_until < effective_from:
            raise ConfigError(
                "Line effective_until is before effective_from",
                file=path,
                key=key_path(*parents, "effective_until"),
                fix="use the same month as effective_from, a later month, or remove effective_until",
            )

    annual_bill = None
    if "annual_bill" in entry:
        annual_bill = _require_money(
            entry["annual_bill"],
            path,
            *parents,
            "annual_bill",
            minimum=Decimal("0.00"),
            minimum_exclusive=True,
        )
    annual_full = None
    if "annual_full" in entry:
        annual_full = _require_money(entry["annual_full"], path, *parents, "annual_full")
        if annual_bill is not None and annual_full < annual_bill:
            raise ConfigError(
                "annual_full is less than annual_bill",
                file=path,
                key=key_path(*parents, "annual_full"),
                fix="make annual_full at least annual_bill",
            )
    account = None
    if "account" in entry:
        account = require_text(entry["account"], path, *parents, "account")
    due = None
    if "due" in entry:
        due = _due(entry["due"], path, *parents, "due")
    if annual_bill is not None:
        _require_annual_monthly(monthly, annual_bill, path, *parents, "monthly")

    return PlanLine(
        desc=desc,
        who=who,
        bucket=bucket,
        monthly=monthly,
        categories=categories,
        paced=paced,
        effective_from=effective_from,
        effective_until=effective_until,
        annual_bill=annual_bill,
        annual_full=annual_full,
        account=account,
        due=due,
    )


def _require_month(value: Any, path: Path, *parents: str) -> Month:
    if isinstance(value, str):
        try:
            return Month.parse(value)
        except ValueError:
            pass
    raise ConfigError(
        f"Invalid month {value!r}",
        file=path,
        key=key_path(*parents),
        fix="write the month as YYYY-MM",
    )


def _require_money(
    value: Any,
    path: Path,
    *parents: str,
    minimum: Decimal | None = None,
    minimum_exclusive: bool = False,
) -> Decimal:
    raw = _decimal_number(value, path, *parents)
    if raw.as_tuple().exponent < -2:
        raise ConfigError(
            f"Too many decimal places: {value!r}",
            file=path,
            key=key_path(*parents),
            fix="use a number with at most two decimal places",
        )
    if minimum is not None and (raw < minimum or (minimum_exclusive and raw == minimum)):
        comparison = "greater than" if minimum_exclusive else "at least"
        raise ConfigError(
            f"Amount must be {comparison} {minimum}",
            file=path,
            key=key_path(*parents),
            fix=f"use a number {comparison} {minimum} with at most two decimal places",
        )
    try:
        return money(raw)
    except ValueError as exc:
        raise ConfigError(
            f"Invalid money amount {value!r}",
            file=path,
            key=key_path(*parents),
            fix="use a finite number with at most two decimal places",
        ) from exc


def _decimal_number(value: Any, path: Path, *parents: str) -> Decimal:
    if isinstance(value, bool) or value is None or not isinstance(value, (int, float, Decimal)):
        amount = Decimal("NaN")
    else:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            amount = Decimal("NaN")
    if not amount.is_finite():
        raise ConfigError(
            f"Expected a number, got {value!r}",
            file=path,
            key=key_path(*parents),
            fix="use a finite number with at most two decimal places",
        )
    return amount


def _categories(value: Any, path: Path, *parents: str) -> tuple[str, ...]:
    rows = require_list(value, path, *parents)
    result: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        category = require_text(row, path, *parents, f"[{index}]")
        if category in seen:
            raise ConfigError(
                f"Duplicate category {category!r}",
                file=path,
                key=key_path(*parents, f"[{index}]"),
                fix="list each category once",
            )
        seen.add(category)
        result.append(category)
    return tuple(result)


def _due(value: Any, path: Path, *parents: str) -> tuple[int, int]:
    due = require_mapping(value, path, *parents)
    reject_unknown_keys(due, DUE_KEYS, path, *parents)
    month = _int_in_range(require(due, "month", path, *parents), 1, 12, path, *parents, "month")
    day = _int_in_range(require(due, "day", path, *parents), 1, 31, path, *parents, "day")
    return month, day


def _int_in_range(value: Any, minimum: int, maximum: int, path: Path, *parents: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ConfigError(
            f"Expected an integer from {minimum} to {maximum}",
            file=path,
            key=key_path(*parents),
            fix=f"use an integer from {minimum} to {maximum}",
        )
    return value


def _require_annual_monthly(
    monthly: Decimal, annual_bill: Decimal, path: Path, *parents: str
) -> None:
    expected = (annual_bill / Decimal(12)).quantize(CENT, rounding=ROUND_HALF_UP)
    if abs(monthly - expected) > CENT:
        raise ConfigError(
            f"monthly should be {expected} for annual_bill {annual_bill}",
            file=path,
            key=key_path(*parents),
            fix=f"set monthly to {expected} or adjust annual_bill",
        )
