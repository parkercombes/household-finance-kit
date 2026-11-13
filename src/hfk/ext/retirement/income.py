"""Typed income streams (M8-02, R2; ADR-0008).

``retirement.yaml`` lists income streams under ``income``. Every amount is a
monthly figure in today's dollars, and every stream must say how it tracks
inflation through ``cola``; there is no default::

    income:
      - {type: social_security, who: alex, cola: full,
         claim_ages: {62: 1400, 67: 2000, 70: 2480}}
      - {type: pension, who: sam, monthly: 1500, start_year: 2037, cola: none}
      - {type: account_drawdown, who: alex, monthly: 1000, start_year: 2035,
         end_year: 2060, cola: full}
      - {type: other, label: "Example rent", who: sam, monthly: 300,
         start_year: 2037, end_year: 2041, cola: 0.02}

Stream types:

- ``social_security`` lists the monthly benefit for each claim age the
  household wants to compare (``claim_ages``). The ages are mutually exclusive
  alternatives, not a timeline: a scenario picks one claim age per person, and
  the stream starts in the calendar year the person reaches that age. In that
  first year it pays for the months from the birth month on (``13 - birth
  month`` months); after that, twelve months a year, to the end of the track.
- ``pension``, ``account_drawdown`` and ``other`` take ``monthly``, a
  ``start_year`` and an optional inclusive ``end_year``; they pay twelve months
  of every year in that range. An ``account_drawdown`` is the withdrawal the
  household declares; the extension does not model an account balance.

``cola`` (ADR-0008), with ``n`` the number of years since the stream started:

- ``full``: flat in today's dollars; the amount every year.
- ``none``: flat in nominal dollars, so its real value is
  ``amount / (1 + inflation) ** n``.
- a number ``r``: grows by ``r`` a year in nominal dollars, so its real value is
  ``amount * ((1 + r) / (1 + inflation)) ** n``.

``assumptions.inflation`` is required as soon as any stream's ``cola`` is not
``full``. Annual amounts are rounded to the cent once, at the end.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from hfk.config import ConfigError
from hfk.config._yaml import (
    reject_unknown_keys,
    require,
    require_list,
    require_mapping,
    require_text,
)
from hfk.config.errors import key_path
from hfk.ledger import money

STREAM_TYPES = ("social_security", "pension", "account_drawdown", "other")
SOCIAL_SECURITY_KEYS = ("type", "who", "label", "claim_ages", "cola")
DATED_KEYS = ("type", "who", "label", "monthly", "start_year", "end_year", "cola")
MAX_COLA = Decimal("0.20")
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class IncomeStream:
    type: str
    who: str
    label: str
    cola: str | Decimal
    monthly: Decimal | None = None
    start_year: int | None = None
    end_year: int | None = None
    claim_ages: tuple[tuple[int, Decimal], ...] = ()

    @property
    def tracks_inflation(self) -> bool:
        return self.cola == "full"

    def claim_amount(self, age: int) -> Decimal | None:
        for claim_age, monthly in self.claim_ages:
            if claim_age == age:
                return monthly
        return None


@dataclass(frozen=True)
class StreamAmount:
    """One stream's amount for one calendar year, in today's dollars."""

    label: str
    type: str
    who: str
    amount: Decimal


def load_income(
    value: Any, path: Path, *, people: tuple[str, ...], inflation: Decimal | None
) -> tuple[IncomeStream, ...]:
    """Validate the ``income`` list of ``retirement.yaml``."""

    rows = require_list(value, path, "income")
    streams: list[IncomeStream] = []
    labels: set[str] = set()
    for index, row in enumerate(rows):
        parents = ("income", f"[{index}]")
        entry = require_mapping(row, path, *parents)
        kind = require_text(require(entry, "type", path, *parents), path, *parents, "type")
        if kind not in STREAM_TYPES:
            raise ConfigError(
                f"Unknown income type {kind!r}",
                file=path,
                key=key_path(*parents, "type"),
                fix=f"use one of {list(STREAM_TYPES)}",
            )
        allowed = SOCIAL_SECURITY_KEYS if kind == "social_security" else DATED_KEYS
        reject_unknown_keys(entry, allowed, path, *parents)
        who = require_text(require(entry, "who", path, *parents), path, *parents, "who")
        if who not in people:
            raise ConfigError(
                f"Unknown person slug {who!r}",
                file=path,
                key=key_path(*parents, "who"),
                fix=f"use one of {list(people)} from people",
            )
        cola = _cola(require(entry, "cola", path, *parents), path, *parents, "cola")
        if cola != "full" and inflation is None:
            raise ConfigError(
                "assumptions.inflation is required when a stream does not track inflation fully",
                file=path,
                key=key_path(*parents, "cola"),
                fix="add inflation under assumptions (such as 0.025), or set cola: full",
            )
        default_label = f"{kind.replace('_', ' ')} ({who})"
        label = default_label
        if "label" in entry:
            label = require_text(entry["label"], path, *parents, "label")
        if label in labels:
            raise ConfigError(
                f"Two income streams are both called {label!r}",
                file=path,
                key=key_path(*parents, "label"),
                fix="give each stream its own label",
            )
        labels.add(label)
        if kind == "social_security":
            claim_ages = _claim_ages(require(entry, "claim_ages", path, *parents), path, *parents)
            streams.append(IncomeStream(kind, who, label, cola, claim_ages=claim_ages))
            continue
        monthly = _money(require(entry, "monthly", path, *parents), path, *parents, "monthly")
        start_year = _year(require(entry, "start_year", path, *parents), path, *parents, "start_year")
        end_year = None
        if entry.get("end_year") is not None:
            end_year = _year(entry["end_year"], path, *parents, "end_year")
            if end_year < start_year:
                raise ConfigError(
                    f"end_year {end_year} is before start_year {start_year}",
                    file=path,
                    key=key_path(*parents, "end_year"),
                    fix="use the same year as start_year or a later one, or remove end_year",
                )
        streams.append(
            IncomeStream(kind, who, label, cola, monthly=monthly, start_year=start_year,
                         end_year=end_year)
        )
    return tuple(streams)


def social_security_people(streams: tuple[IncomeStream, ...]) -> tuple[str, ...]:
    """People with a Social Security stream, who each need a claim age in a scenario."""

    return tuple(dict.fromkeys(s.who for s in streams if s.type == "social_security"))


def check_scenario(
    streams: tuple[IncomeStream, ...], scenario: Mapping[str, int], path: Path
) -> None:
    """A scenario names one listed claim age for every person with Social Security."""

    for index, stream in enumerate(streams):
        if stream.type != "social_security":
            continue
        listed = [age for age, _monthly in stream.claim_ages]
        age = scenario.get(stream.who)
        if age is None:
            raise ConfigError(
                f"no claim age chosen for {stream.who}'s Social Security",
                file=path,
                key=key_path("income", f"[{index}]", "claim_ages"),
                fix=f"choose one of {listed} for {stream.who}; claim ages are alternatives, "
                "and hfk never picks one for you",
            )
        if age not in listed:
            raise ConfigError(
                f"claim age {age} is not listed for {stream.who}",
                file=path,
                key=key_path("income", f"[{index}]", "claim_ages"),
                fix=f"choose one of {listed}, or add {age} with its benefit to claim_ages",
            )


def stream_amount(
    stream: IncomeStream,
    year: int,
    *,
    birth_year: int,
    birth_month: int,
    claim_age: int | None,
    inflation: Decimal | None,
) -> Decimal:
    """The stream's real (today's dollars) amount in calendar ``year``; zero outside it."""

    if stream.type == "social_security":
        assert claim_age is not None
        monthly = stream.claim_amount(claim_age)
        assert monthly is not None
        start = birth_year + claim_age
        if year < start:
            return ZERO
        months = 13 - birth_month if year == start else 12
    else:
        assert stream.monthly is not None and stream.start_year is not None
        start = stream.start_year
        if year < start or (stream.end_year is not None and year > stream.end_year):
            return ZERO
        monthly = stream.monthly
        months = 12
    return money(monthly * months * real_factor(stream.cola, year - start, inflation))


def real_factor(cola: str | Decimal, years: int, inflation: Decimal | None) -> Decimal:
    """How much of a stream's starting real value is left after ``years`` (ADR-0008)."""

    if cola == "full":
        return Decimal(1)
    assert inflation is not None
    growth = Decimal(0) if cola == "none" else Decimal(cola)
    return ((1 + growth) / (1 + inflation)) ** years


def _cola(value: Any, path: Path, *parents: str) -> str | Decimal:
    if value in ("full", "none"):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            rate = Decimal(str(value))
        except InvalidOperation:
            rate = None
        if rate is not None and rate.is_finite() and Decimal("-0.10") <= rate <= MAX_COLA:
            return rate
    raise ConfigError(
        f"Invalid cola {value!r}",
        file=path,
        key=key_path(*parents),
        fix="write full (keeps pace with inflation), none (fixed in dollars), or an annual "
        "nominal rate from -0.10 to 0.20 such as 0.02",
    )


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


def _year(value: Any, path: Path, *parents: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and 1900 <= value <= 2200:
        return value
    raise ConfigError(
        f"Invalid year {value!r}",
        file=path,
        key=key_path(*parents),
        fix="write a four-digit calendar year, such as 2035",
    )


def _claim_ages(value: Any, path: Path, *parents: str) -> tuple[tuple[int, Decimal], ...]:
    rows = require_mapping(value, path, *parents, "claim_ages")
    if not rows:
        raise ConfigError(
            "claim_ages is empty",
            file=path,
            key=key_path(*parents, "claim_ages"),
            fix="list the monthly benefit for each claim age, such as {62: 1400, 67: 2000}",
        )
    ages: list[tuple[int, Decimal]] = []
    for raw_age, raw_monthly in rows.items():
        if not isinstance(raw_age, int) or isinstance(raw_age, bool) or not 62 <= raw_age <= 70:
            raise ConfigError(
                f"Invalid claim age {raw_age!r}",
                file=path,
                key=key_path(*parents, "claim_ages", str(raw_age)),
                fix="use whole ages from 62 to 70, the range in which a benefit can be claimed",
            )
        ages.append((raw_age, _money(raw_monthly, path, *parents, "claim_ages", str(raw_age))))
    return tuple(sorted(ages))


__all__ = [
    "STREAM_TYPES",
    "IncomeStream",
    "StreamAmount",
    "check_scenario",
    "load_income",
    "real_factor",
    "social_security_people",
    "stream_amount",
]
