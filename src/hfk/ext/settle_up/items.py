"""Off-ledger shared items: ``shared-items/YYYY-MM.yaml`` (M7-03; design brief 8a).

Some shared costs never reach the Tiller workbook: a bill paid from an
account Tiller does not sync, or cash. The household records them for a
month in ``shared-items/YYYY-MM.yaml`` in its private instance::

    schema_version: 1
    items:
      - label: "Example utility bill"
        amount: 120.00
        paid_by: alex
        weights: {alex: 0.5, sam: 0.5}
        bucket: "Fixed Essential"

Every item needs all five keys. ``amount`` is a positive amount of dollars
and cents, read as an exact decimal; ``paid_by`` and every ``weights`` key are
person slugs from ``household.yaml``; the weights sum to exactly one; and
``bucket`` is a declared bucket. A month with no file has no shared items. A
file whose name is not a valid ``YYYY-MM`` is an error, never skipped.
Problems are ``ConfigError`` naming the file, key path, and fix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from hfk.config import ConfigError, Declarations, Household, Month
from hfk.config._yaml import (
    load_mapping,
    reject_unknown_keys,
    require,
    require_list,
    require_mapping,
    require_schema_version,
    require_text,
)
from hfk.config.errors import key_path
from hfk.ledger import money

SHARED_ITEMS_DIR = "shared-items"
FILE_NAME = re.compile(r"^(\d{4})-(\d{2})\.yaml$")
TOP_LEVEL_KEYS = ("schema_version", "items")
ITEM_KEYS = ("label", "amount", "paid_by", "weights", "bucket")


@dataclass(frozen=True)
class SharedItem:
    label: str
    amount: Decimal
    paid_by: str
    weights: tuple[tuple[str, Decimal], ...]
    bucket: str

    def weight(self, slug: str) -> Decimal:
        for person, weight in self.weights:
            if person == slug:
                return weight
        return Decimal(0)


@dataclass(frozen=True)
class SharedItems:
    month: Month
    path: Path
    exists: bool
    items: tuple[SharedItem, ...]


def shared_items_path(home: Path, month: Month) -> Path:
    return Path(home) / SHARED_ITEMS_DIR / f"{month}.yaml"


def load_shared_items(
    home: Path, month: Month, *, household: Household, declarations: Declarations
) -> SharedItems:
    """The validated shared items for ``month``; an absent file means none."""

    path = shared_items_path(home, month)
    if not path.exists():
        return SharedItems(month=month, path=path, exists=False, items=())
    return SharedItems(
        month=month,
        path=path,
        exists=True,
        items=_items(path, household=household, declarations=declarations),
    )


def check_shared_items_dir(
    home: Path, *, household: Household, declarations: Declarations
) -> list[ConfigError]:
    """Every problem in every file under ``shared-items/``, one per file."""

    directory = Path(home) / SHARED_ITEMS_DIR
    if not directory.is_dir():
        return []
    problems: list[ConfigError] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.name.lower() == "readme.md" or path.name.startswith("."):
            continue
        try:
            month_from_name(path)
            _items(path, household=household, declarations=declarations)
        except ConfigError as error:
            problems.append(error)
    return problems


def month_from_name(path: Path) -> Month:
    match = FILE_NAME.fullmatch(path.name)
    month = None
    if match is not None:
        try:
            month = Month.parse(f"{match.group(1)}-{match.group(2)}")
        except ValueError:
            month = None
    if month is None:
        raise ConfigError(
            f"{path.name} is not named after a month",
            file=path,
            key="(file)",
            fix="name each shared-items file YYYY-MM.yaml, such as 2026-08.yaml, "
            "or move it out of shared-items/",
        )
    return month


def _items(
    path: Path, *, household: Household, declarations: Declarations
) -> tuple[SharedItem, ...]:
    data = load_mapping(path)
    reject_unknown_keys(data, TOP_LEVEL_KEYS, path)
    require_schema_version(data, path)
    rows = require_list(require(data, "items", path), path, "items")
    people = set(household.slugs)
    buckets = declarations.bucket_names()
    items: list[SharedItem] = []
    for index, row in enumerate(rows):
        parents = ("items", f"[{index}]")
        entry = require_mapping(row, path, *parents)
        reject_unknown_keys(entry, ITEM_KEYS, path, *parents)
        label = require_text(require(entry, "label", path, *parents), path, *parents, "label")
        amount = _amount(require(entry, "amount", path, *parents), path, *parents, "amount")
        paid_by = require_text(require(entry, "paid_by", path, *parents), path, *parents, "paid_by")
        _known_person(paid_by, people, path, *parents, "paid_by")
        weights = _weights(require(entry, "weights", path, *parents), people, path, *parents)
        bucket = require_text(require(entry, "bucket", path, *parents), path, *parents, "bucket")
        if bucket not in buckets:
            raise ConfigError(
                f"Unknown bucket {bucket!r}",
                file=path,
                key=key_path(*parents, "bucket"),
                fix=f"use one of {list(buckets)}",
            )
        items.append(SharedItem(label, amount, paid_by, weights, bucket))
    return tuple(items)


def _amount(value: Any, path: Path, *parents: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        amount = None
    else:
        try:
            amount = Decimal(str(value).strip())
        except InvalidOperation:
            amount = None
    if amount is None or not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise ConfigError(
            f"Invalid amount {value!r}",
            file=path,
            key=key_path(*parents),
            fix="write a positive amount with at most two decimal places, such as 120.00",
        )
    return money(amount)


def _known_person(slug: str, people: set[str], path: Path, *parents: str) -> None:
    if slug not in people:
        raise ConfigError(
            f"Unknown person slug {slug!r}",
            file=path,
            key=key_path(*parents),
            fix=f"use one of {sorted(people)} from household.yaml",
        )


def _weights(
    value: Any, people: set[str], path: Path, *parents: str
) -> tuple[tuple[str, Decimal], ...]:
    raw = require_mapping(value, path, *parents, "weights")
    if not raw:
        raise ConfigError(
            "weights is empty",
            file=path,
            key=key_path(*parents, "weights"),
            fix="write weights such as {alex: 0.5, sam: 0.5}",
        )
    weights: list[tuple[str, Decimal]] = []
    for raw_slug, raw_weight in raw.items():
        slug = str(raw_slug)
        _known_person(slug, people, path, *parents, "weights", slug)
        try:
            weight = Decimal(str(raw_weight)) if not isinstance(raw_weight, bool) else None
        except InvalidOperation:
            weight = None
        if weight is None or not weight.is_finite() or weight < 0 or weight > 1:
            raise ConfigError(
                f"Invalid weight {raw_weight!r}",
                file=path,
                key=key_path(*parents, "weights", slug),
                fix="use a number from 0 to 1",
            )
        weights.append((slug, weight))
    total = sum(weight for _slug, weight in weights)
    if total != 1:
        raise ConfigError(
            f"Weights sum to {total}, not 1",
            file=path,
            key=key_path(*parents, "weights"),
            fix="make the weights sum to exactly 1, such as 0.5 and 0.5",
        )
    return tuple(weights)


__all__ = [
    "SHARED_ITEMS_DIR",
    "SharedItem",
    "SharedItems",
    "check_shared_items_dir",
    "load_shared_items",
    "month_from_name",
    "shared_items_path",
]
