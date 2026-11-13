"""``retirement.yaml``: people and household assumptions (M8-01, R1; ADR-0008).

Income streams (``income``, R2) are validated by ``hfk.ext.retirement.income``.

The retirement extension models arithmetic, not advice. Its input is the
instance's own ``retirement.yaml`` (proposed ADR-0016, option 1)::

    schema_version: 1
    people:
      alex: {birth: 1970-06, retire_year: 2035}
      sam: {birth: 1972-09, retire_year: 2037}
    assumptions:
      until_age: 95
      inflation: 0.025

- ``people`` maps each person's slug from ``household.yaml`` to a birth
  ``YYYY-MM`` and the calendar year they retire. Every person in the household
  must be listed; ``check_people`` compares the two files.
- ``assumptions.until_age`` is required: the calendar-year track runs through
  the year the youngest person reaches that age. There is no default horizon.
- ``assumptions.inflation`` is an annual rate such as ``0.025``. It is optional
  here; ADR-0008 makes it required as soon as any income stream does not track
  inflation fully (R2). A value above ``0.20`` is refused, because ``2.5``
  written for 2.5 percent would otherwise be read as 250 percent.

Every figure the extension takes or prints is in today's dollars (ADR-0008).
Problems are ``ConfigError`` naming the file, key path, and fix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from hfk.config import ConfigError, Household
from hfk.config._yaml import (
    reject_unknown_keys,
    require,
    require_mapping,
    require_schema_version,
)
from hfk.config.errors import key_path
from hfk.config.household import SLUG
from hfk.ext.retirement.income import IncomeStream, load_income

CONFIG_FILE = "retirement.yaml"
TOP_LEVEL_KEYS = ("schema_version", "people", "assumptions", "income")
PERSON_KEYS = ("birth", "retire_year")
ASSUMPTION_KEYS = ("until_age", "inflation")
BIRTH = re.compile(r"^(\d{4})-(\d{2})$")
MAX_INFLATION = Decimal("0.20")
MIN_RETIRE_AGE = 18


@dataclass(frozen=True)
class RetirementPerson:
    slug: str
    birth_year: int
    birth_month: int
    retire_year: int

    def age_in(self, year: int) -> int:
        """The age the person reaches during calendar ``year``."""

        return year - self.birth_year

    @property
    def retire_age(self) -> int:
        return self.age_in(self.retire_year)


@dataclass(frozen=True)
class Assumptions:
    until_age: int
    inflation: Decimal | None


@dataclass(frozen=True)
class RetirementConfig:
    path: Path
    schema_version: int
    people: tuple[RetirementPerson, ...]
    assumptions: Assumptions
    income: tuple[IncomeStream, ...] = ()

    def person(self, slug: str) -> RetirementPerson | None:
        for person in self.people:
            if person.slug == slug:
                return person
        return None

    @property
    def first_year(self) -> int:
        """The first year of the track: the earliest retirement year."""

        return min(person.retire_year for person in self.people)

    @property
    def last_year(self) -> int:
        """The last year of the track: the youngest person reaches ``until_age``."""

        youngest = max(self.people, key=lambda person: (person.birth_year, person.birth_month))
        return youngest.birth_year + self.assumptions.until_age


def load_retirement(data: dict[str, Any], path: Path) -> RetirementConfig:
    """Validate a loaded ``retirement.yaml`` mapping (the extension's ``schema``)."""

    reject_unknown_keys(data, TOP_LEVEL_KEYS, path)
    schema_version = require_schema_version(data, path)
    assumptions = _assumptions(require(data, "assumptions", path), path)
    people = _people(require(data, "people", path), path, assumptions)
    income = load_income(
        data.get("income", []),
        path,
        people=tuple(person.slug for person in people),
        inflation=assumptions.inflation,
    )
    return RetirementConfig(
        path=path,
        schema_version=schema_version,
        people=people,
        assumptions=assumptions,
        income=income,
    )


def check_people(config: RetirementConfig, household: Household) -> None:
    """Every household person is in ``retirement.yaml``, and nobody else."""

    listed = [person.slug for person in config.people]
    for slug in listed:
        if slug not in household.slugs:
            raise ConfigError(
                f"Unknown person slug {slug!r}",
                file=config.path,
                key=key_path("people", slug),
                fix=f"use the slugs from household.yaml: {', '.join(household.slugs)}",
            )
    for slug in household.slugs:
        if slug not in listed:
            raise ConfigError(
                f"Person {slug!r} from household.yaml is missing",
                file=config.path,
                key="people",
                fix=f"add {slug}: {{birth: YYYY-MM, retire_year: YYYY}} under people",
            )


def _people(value: Any, path: Path, assumptions: Assumptions) -> tuple[RetirementPerson, ...]:
    rows = require_mapping(value, path, "people")
    if not rows:
        raise ConfigError(
            "people must list at least one person",
            file=path,
            key="people",
            fix="add each person, such as alex: {birth: 1970-06, retire_year: 2035}",
        )
    people: list[RetirementPerson] = []
    for raw_slug, raw_entry in rows.items():
        slug = str(raw_slug)
        parents = ("people", slug)
        if not SLUG.match(slug):
            raise ConfigError(
                f"Invalid person slug {slug!r}",
                file=path,
                key=key_path(*parents),
                fix="use the person's slug from household.yaml",
            )
        entry = require_mapping(raw_entry, path, *parents)
        reject_unknown_keys(entry, PERSON_KEYS, path, *parents)
        birth_year, birth_month = _birth(require(entry, "birth", path, *parents), path, *parents)
        retire_year = _year(require(entry, "retire_year", path, *parents), path, *parents)
        retire_age = retire_year - birth_year
        if not MIN_RETIRE_AGE <= retire_age <= assumptions.until_age:
            raise ConfigError(
                f"retire_year {retire_year} makes {slug} {retire_age} at retirement",
                file=path,
                key=key_path(*parents, "retire_year"),
                fix=f"use a year when {slug} is between {MIN_RETIRE_AGE} and "
                f"until_age ({assumptions.until_age})",
            )
        people.append(RetirementPerson(slug, birth_year, birth_month, retire_year))
    return tuple(people)


def _birth(value: Any, path: Path, *parents: str) -> tuple[int, int]:
    match = BIRTH.fullmatch(value.strip()) if isinstance(value, str) else None
    if match is not None:
        year, month = int(match.group(1)), int(match.group(2))
        if 1900 <= year <= 2100 and 1 <= month <= 12:
            return year, month
    raise ConfigError(
        f"Invalid birth {value!r}",
        file=path,
        key=key_path(*parents, "birth"),
        fix='write the birth year and month as "YYYY-MM", such as "1970-06"',
    )


def _year(value: Any, path: Path, *parents: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and 1900 <= value <= 2200:
        return value
    raise ConfigError(
        f"Invalid retire_year {value!r}",
        file=path,
        key=key_path(*parents, "retire_year"),
        fix="write a four-digit calendar year, such as 2035",
    )


def _assumptions(value: Any, path: Path) -> Assumptions:
    entry = require_mapping(value, path, "assumptions")
    reject_unknown_keys(entry, ASSUMPTION_KEYS, path, "assumptions")
    until_age = require(entry, "until_age", path, "assumptions")
    if not isinstance(until_age, int) or isinstance(until_age, bool) or not 60 <= until_age <= 120:
        raise ConfigError(
            f"Invalid until_age {until_age!r}",
            file=path,
            key="assumptions.until_age",
            fix="write a whole age from 60 to 120: the track ends the year the youngest "
            "person reaches it",
        )
    inflation = None
    if "inflation" in entry:
        inflation = rate(entry["inflation"], path, "assumptions", "inflation", maximum=MAX_INFLATION)
    return Assumptions(until_age=until_age, inflation=inflation)


def rate(
    value: Any, path: Path, *parents: str, maximum: Decimal, minimum: Decimal = Decimal("-0.10")
) -> Decimal:
    """An annual rate as an exact decimal fraction, such as ``0.025``."""

    try:
        number = (
            Decimal(str(value))
            if isinstance(value, (int, float, str)) and not isinstance(value, bool)
            else None
        )
    except InvalidOperation:
        number = None
    if number is None or not number.is_finite() or not minimum <= number <= maximum:
        raise ConfigError(
            f"Invalid rate {value!r}",
            file=path,
            key=key_path(*parents),
            fix=f"write the annual rate as a fraction from {minimum} to {maximum}, "
            "such as 0.025 for 2.5 percent",
        )
    return number


__all__ = [
    "CONFIG_FILE",
    "Assumptions",
    "RetirementConfig",
    "RetirementPerson",
    "check_people",
    "load_retirement",
    "rate",
]
