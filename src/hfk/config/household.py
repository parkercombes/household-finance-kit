"""Load and validate ``household.yaml`` (design brief section 6; ADR-0003).

The file declares who is in the household, where the Tiller workbook lives,
how far back analysis may look, how each account is owned, and which optional
extensions are enabled. Nothing is inferred: a missing required key, an
unknown key, an undeclared person slug, or shared weights that do not sum to
exactly one is an error that names the file, key path, and fix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from hfk.config._yaml import (
    load_mapping,
    reject_unknown_keys,
    require,
    require_list,
    require_mapping,
    require_schema_version,
    require_text,
)
from hfk.config.errors import ConfigError, key_path

HOUSEHOLD_FILE = "household.yaml"
SLUG = re.compile(r"^[a-z][a-z0-9_]*$")
TOP_LEVEL_KEYS = ("schema_version", "people", "files", "history_start", "accounts", "extensions")
ACCOUNT_KEYS = ("owner", "shared", "kind", "unsynced")


@dataclass(frozen=True)
class Person:
    slug: str
    name: str


@dataclass(frozen=True)
class AccountOwnership:
    """One account's default ownership weights, keyed by person slug.

    Weights are exact ``Decimal`` values that sum to one. An owned account is
    represented as a single weight of one so the engine has one code path.
    """

    name: str
    weights: tuple[tuple[str, Decimal], ...]
    kind: str | None = None
    unsynced: bool = False

    @property
    def owner(self) -> str | None:
        """The sole owner's slug when one person holds the whole account."""

        if len(self.weights) == 1 and self.weights[0][1] == 1:
            return self.weights[0][0]
        return None

    def weight(self, slug: str) -> Decimal:
        for person, weight in self.weights:
            if person == slug:
                return weight
        return Decimal(0)


@dataclass(frozen=True)
class Household:
    path: Path
    schema_version: int
    people: tuple[Person, ...]
    tiller_glob: str
    history_start: date | None
    accounts: tuple[AccountOwnership, ...]
    extensions: tuple[str, ...]

    def person(self, slug: str) -> Person | None:
        for person in self.people:
            if person.slug == slug:
                return person
        return None

    def account(self, name: str) -> AccountOwnership | None:
        for account in self.accounts:
            if account.name == name:
                return account
        return None

    @property
    def slugs(self) -> tuple[str, ...]:
        return tuple(person.slug for person in self.people)


def household_path(home: Path) -> Path:
    return Path(home) / HOUSEHOLD_FILE


def load_household(home_or_file: Path) -> Household:
    """Load ``household.yaml`` from an instance home directory or an explicit file path."""

    path = Path(home_or_file)
    if path.is_dir():
        path = household_path(path)
    data = load_mapping(path)
    reject_unknown_keys(data, TOP_LEVEL_KEYS, path)

    schema_version = require_schema_version(data, path)
    people = _people(require(data, "people", path), path)
    slugs = {person.slug for person in people}
    tiller_glob = _files(require(data, "files", path), path)
    history_start = _history_start(data.get("history_start"), path)
    accounts = _accounts(require(data, "accounts", path), slugs, path)
    extensions = _extensions(data.get("extensions", []), path)
    return Household(
        path=path,
        schema_version=schema_version,
        people=people,
        tiller_glob=tiller_glob,
        history_start=history_start,
        accounts=accounts,
        extensions=extensions,
    )


def _people(value: Any, path: Path) -> tuple[Person, ...]:
    rows = require_list(value, path, "people")
    if not rows:
        raise ConfigError(
            "people must list at least one person",
            file=path,
            key="people",
            fix="add a person such as {slug: alex, name: Alex}",
        )
    people: list[Person] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        parents = ("people", f"[{index}]")
        entry = require_mapping(row, path, *parents)
        reject_unknown_keys(entry, ("slug", "name"), path, *parents)
        slug = require_text(require(entry, "slug", path, *parents), path, *parents, "slug")
        if not SLUG.match(slug):
            raise ConfigError(
                f"Invalid person slug {slug!r}",
                file=path,
                key=key_path(*parents, "slug"),
                fix="use lowercase letters, digits, and underscores, starting with a letter",
            )
        if slug in seen:
            raise ConfigError(
                f"Duplicate person slug {slug!r}",
                file=path,
                key=key_path(*parents, "slug"),
                fix="give each person a distinct slug",
            )
        seen.add(slug)
        name = require_text(require(entry, "name", path, *parents), path, *parents, "name")
        people.append(Person(slug=slug, name=name))
    return tuple(people)


def _files(value: Any, path: Path) -> str:
    files = require_mapping(value, path, "files")
    reject_unknown_keys(files, ("tiller_glob",), path, "files")
    pattern = require_text(require(files, "tiller_glob", path, "files"), path, "files", "tiller_glob")
    if "/" in pattern or "\\" in pattern:
        raise ConfigError(
            "tiller_glob must be a file name pattern, not a path",
            file=path,
            key="files.tiller_glob",
            fix='use a pattern such as "Tiller*.xls*"; workbooks are looked up under data/',
        )
    return pattern


def _history_start(value: Any, path: Path) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise ConfigError(
        f"history_start is not a date: {value!r}",
        file=path,
        key="history_start",
        fix="write it as YYYY-MM-DD, or remove it to analyse all history",
    )


def _accounts(value: Any, slugs: set[str], path: Path) -> tuple[AccountOwnership, ...]:
    rows = require_mapping(value, path, "accounts")
    if not rows:
        raise ConfigError(
            "accounts must declare at least one account",
            file=path,
            key="accounts",
            fix='add each Tiller account, such as "Alex Checking": {owner: alex}',
        )
    accounts: list[AccountOwnership] = []
    for raw_name, raw_entry in rows.items():
        name = require_text(raw_name, path, "accounts", str(raw_name))
        parents = ("accounts", name)
        entry = require_mapping(raw_entry, path, *parents)
        reject_unknown_keys(entry, ACCOUNT_KEYS, path, *parents)
        kind = None
        if "kind" in entry:
            kind = require_text(entry["kind"], path, *parents, "kind")
        unsynced = False
        if "unsynced" in entry:
            raw_unsynced = entry["unsynced"]
            if not isinstance(raw_unsynced, bool):
                raise ConfigError(
                    f"Invalid unsynced flag {raw_unsynced!r}",
                    file=path,
                    key=key_path(*parents, "unsynced"),
                    fix="write unsynced as true or false",
                )
            unsynced = raw_unsynced
        has_owner = "owner" in entry
        has_shared = "shared" in entry
        if has_owner == has_shared:
            raise ConfigError(
                "Account must have exactly one of owner or shared",
                file=path,
                key=key_path(*parents),
                fix="write {owner: <slug>} for one person or {shared: {<slug>: <weight>, ...}}",
            )
        if has_owner:
            owner = require_text(entry["owner"], path, *parents, "owner")
            _require_known_slug(owner, slugs, path, *parents, "owner")
            weights: tuple[tuple[str, Decimal], ...] = ((owner, Decimal(1)),)
        else:
            weights = _shared_weights(entry["shared"], slugs, path, *parents, "shared")
        accounts.append(AccountOwnership(name=name, weights=weights, kind=kind, unsynced=unsynced))
    return tuple(accounts)


def _shared_weights(
    value: Any, slugs: set[str], path: Path, *parents: str
) -> tuple[tuple[str, Decimal], ...]:
    shares = require_mapping(value, path, *parents)
    if not shares:
        raise ConfigError(
            "shared must list at least one person",
            file=path,
            key=key_path(*parents),
            fix="write shared: {alex: 0.5, sam: 0.5} with weights that sum to 1",
        )
    weights: list[tuple[str, Decimal]] = []
    for raw_slug, raw_weight in shares.items():
        slug = str(raw_slug)
        _require_known_slug(slug, slugs, path, *parents, slug)
        if isinstance(raw_weight, bool):
            raw_weight = None
        try:
            weight = Decimal(str(raw_weight))
        except InvalidOperation:
            weight = Decimal("NaN")
        if raw_weight is None or weight.is_nan() or weight <= 0 or weight > 1:
            raise ConfigError(
                f"Invalid share weight {raw_weight!r}",
                file=path,
                key=key_path(*parents, slug),
                fix="use a number greater than 0 and at most 1",
            )
        weights.append((slug, weight))
    total = sum(weight for _slug, weight in weights)
    if total != 1:
        raise ConfigError(
            f"Share weights sum to {total}, not 1",
            file=path,
            key=key_path(*parents),
            fix="make the weights sum to exactly 1 (for example 0.5 and 0.5, or 0.6 and 0.4)",
        )
    return tuple(weights)


def _require_known_slug(slug: str, slugs: set[str], path: Path, *parents: str) -> None:
    if slug not in slugs:
        raise ConfigError(
            f"Unknown person slug {slug!r}",
            file=path,
            key=key_path(*parents),
            fix=f"use one of {sorted(slugs)} or add the person under people",
        )


def _extensions(value: Any, path: Path) -> tuple[str, ...]:
    names = require_list(value, path, "extensions")
    result: list[str] = []
    for index, raw in enumerate(names):
        name = require_text(raw, path, "extensions", f"[{index}]")
        if not SLUG.match(name):
            raise ConfigError(
                f"Invalid extension name {name!r}",
                file=path,
                key=key_path("extensions", f"[{index}]"),
                fix="extension names are lowercase identifiers such as settle_up",
            )
        if name in result:
            raise ConfigError(
                f"Duplicate extension {name!r}",
                file=path,
                key=key_path("extensions", f"[{index}]"),
                fix="list each extension once",
            )
        result.append(name)
    return tuple(result)
