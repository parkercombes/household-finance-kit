"""Versioned tax data, a staleness gate, and pluggable state tax (M8-04, R4; ADR-0005).

Federal figures are data, not code. Each federal table is a YAML file tagged
with its tax year and the official publication every figure comes from::

    schema_version: 1
    jurisdiction: us-federal
    tax_year: 2026
    source: "IRS Rev. Proc. ..., section ..."
    filing_status:
      married_joint:
        standard_deduction: 1000.00
        brackets: [{over: 0, rate: 0.10}, {over: 2000, rate: 0.20}]
      single: {...}
    social_security:
      source: "IRS Publication 915 ..."
      first_fraction: 0.50
      second_fraction: 0.85
      married_joint: {base: 100.00, adjusted_base: 200.00}
      single: {...}

Tables ship as package data in ``hfk/ext/retirement/tax_data/``. A figure that
cannot be cited to an official IRS or SSA publication is left out, never
guessed: with no table for the needed year, the extension fails loudly.

``retirement.yaml`` chooses the household's side in its ``tax`` section::

    tax:
      filing_status: married_joint     # married_joint or single; no default
      max_data_age_years: 1            # the staleness limit; no default
      state: {module: flat, rate: 0.04}

The staleness gate (ADR-0005): the newest federal table is refused when the
current year is more than ``max_data_age_years`` after its ``tax_year``.

State tax is a separate small module chosen by ``state.module``, with figures
the household supplies for its own state:

- ``none``: no state tax.
- ``flat``: ``rate`` times taxable income, after an optional ``deduction``.
- ``bracket``: ``brackets`` (``over`` and ``rate``) after an optional
  ``deduction``.

Every function here is plain arithmetic on exact decimals. It recommends no
filing status, tax strategy, or anything else.
"""

from __future__ import annotations

import importlib.resources
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from hfk.config import ConfigError
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

FILING_STATUSES = ("married_joint", "single")
JURISDICTION = "us-federal"
TAX_KEYS = ("filing_status", "max_data_age_years", "state")
TABLE_KEYS = ("schema_version", "jurisdiction", "tax_year", "source", "filing_status",
              "social_security")
STATUS_KEYS = ("standard_deduction", "brackets")
SOCIAL_SECURITY_KEYS = ("source", "first_fraction", "second_fraction", *FILING_STATUSES)
THRESHOLD_KEYS = ("base", "adjusted_base")
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Bracket:
    over: Decimal
    rate: Decimal


@dataclass(frozen=True)
class StatusTable:
    standard_deduction: Decimal
    brackets: tuple[Bracket, ...]


@dataclass(frozen=True)
class SocialSecurityRule:
    source: str
    first_fraction: Decimal
    second_fraction: Decimal
    thresholds: tuple[tuple[str, Decimal, Decimal], ...]

    def for_status(self, status: str) -> tuple[Decimal, Decimal]:
        for name, base, adjusted in self.thresholds:
            if name == status:
                return base, adjusted
        raise KeyError(status)


@dataclass(frozen=True)
class FederalTable:
    path: Path
    tax_year: int
    source: str
    statuses: tuple[tuple[str, StatusTable], ...]
    social_security: SocialSecurityRule

    def status(self, name: str) -> StatusTable:
        for status, table in self.statuses:
            if status == name:
                return table
        raise ConfigError(
            f"the {self.tax_year} federal table has no {name} figures",
            file=self.path,
            key=f"filing_status.{name}",
            fix="add that filing status, cited to its IRS publication, or choose another",
        )


@dataclass(frozen=True)
class StateTax:
    module: str
    compute: Callable[[Decimal], Decimal]


@dataclass(frozen=True)
class TaxConfig:
    filing_status: str
    max_data_age_years: int
    state: StateTax


def tax_data_dir() -> Path:
    # hfk ships as a wheel, never zipped, so this Traversable is a plain Path.
    return Path(str(importlib.resources.files("hfk.ext.retirement") / "tax_data"))


def load_federal_table(path: Path) -> FederalTable:
    """Validate one federal tax table file."""

    data = load_mapping(path)
    reject_unknown_keys(data, TABLE_KEYS, path)
    require_schema_version(data, path)
    jurisdiction = require_text(require(data, "jurisdiction", path), path, "jurisdiction")
    if jurisdiction != JURISDICTION:
        raise ConfigError(
            f"jurisdiction {jurisdiction!r} is not {JURISDICTION}",
            file=path,
            key="jurisdiction",
            fix=f"set jurisdiction: {JURISDICTION}",
        )
    tax_year = require(data, "tax_year", path)
    if not isinstance(tax_year, int) or isinstance(tax_year, bool) or not 1900 <= tax_year <= 2200:
        raise ConfigError(
            f"Invalid tax_year {tax_year!r}", file=path, key="tax_year",
            fix="write the four-digit tax year the figures apply to",
        )
    source = require_text(require(data, "source", path), path, "source")
    rows = require_mapping(require(data, "filing_status", path), path, "filing_status")
    statuses: list[tuple[str, StatusTable]] = []
    for name, entry in rows.items():
        name = str(name)
        if name not in FILING_STATUSES:
            raise ConfigError(
                f"Unknown filing status {name!r}", file=path, key=key_path("filing_status", name),
                fix=f"use {list(FILING_STATUSES)}",
            )
        statuses.append((name, _status_table(entry, path, "filing_status", name)))
    social = _social_security(require(data, "social_security", path), path)
    return FederalTable(path, tax_year, source, tuple(statuses), social)


def newest_federal_table(directory: Path | None = None) -> FederalTable:
    """The federal table with the latest tax year; none at all is a loud error."""

    directory = tax_data_dir() if directory is None else Path(directory)
    files = sorted(directory.glob("us-federal-*.yaml")) if directory.is_dir() else []
    if not files:
        raise ConfigError(
            "no federal tax table is installed",
            file=directory,
            key="(file)",
            fix="the toolkit maintainer must add us-federal-<tax year>.yaml with every figure "
            "cited to its IRS or SSA publication; hfk never guesses tax figures",
        )
    tables = [load_federal_table(path) for path in files]
    return max(tables, key=lambda table: table.tax_year)


def check_staleness(table: FederalTable, *, current_year: int, max_age_years: int,
                    config_path: Path) -> None:
    """ADR-0005: refuse a table older than the household's staleness limit."""

    age = current_year - table.tax_year
    if age > max_age_years:
        raise ConfigError(
            f"the newest federal tax table is for {table.tax_year}, {age} years before "
            f"{current_year}, beyond max_data_age_years {max_age_years}",
            file=config_path,
            key="tax.max_data_age_years",
            fix="update hfk to a release with newer tax data; raising the limit accepts "
            "out-of-date tax figures knowingly",
        )


def load_tax_config(value: Any, path: Path) -> TaxConfig:
    """Validate the ``tax`` section of ``retirement.yaml``."""

    entry = require_mapping(value, path, "tax")
    reject_unknown_keys(entry, TAX_KEYS, path, "tax")
    status = require_text(require(entry, "filing_status", path, "tax"), path, "tax",
                          "filing_status")
    if status not in FILING_STATUSES:
        raise ConfigError(
            f"Unknown filing status {status!r}", file=path, key="tax.filing_status",
            fix=f"write one of {list(FILING_STATUSES)}",
        )
    age = require(entry, "max_data_age_years", path, "tax")
    if not isinstance(age, int) or isinstance(age, bool) or not 0 <= age <= 10:
        raise ConfigError(
            f"Invalid max_data_age_years {age!r}", file=path, key="tax.max_data_age_years",
            fix="write how many years old the federal tax data may be, a whole number from "
            "0 to 10, such as 1",
        )
    state = load_state_tax(require(entry, "state", path, "tax"), path)
    return TaxConfig(filing_status=status, max_data_age_years=age, state=state)


def _flat(entry: dict[str, Any], path: Path) -> Callable[[Decimal], Decimal]:
    reject_unknown_keys(entry, ("module", "rate", "deduction"), path, "tax", "state")
    rate = _rate(require(entry, "rate", path, "tax", "state"), path, "tax", "state", "rate")
    deduction = _amount(entry.get("deduction", 0), path, "tax", "state", "deduction")
    return lambda income: money(max(income - deduction, ZERO) * rate)


def _bracket(entry: dict[str, Any], path: Path) -> Callable[[Decimal], Decimal]:
    reject_unknown_keys(entry, ("module", "brackets", "deduction"), path, "tax", "state")
    brackets = _brackets(require(entry, "brackets", path, "tax", "state"), path, "tax", "state")
    deduction = _amount(entry.get("deduction", 0), path, "tax", "state", "deduction")
    return lambda income: bracket_tax(max(income - deduction, ZERO), brackets)


def _none(entry: dict[str, Any], path: Path) -> Callable[[Decimal], Decimal]:
    reject_unknown_keys(entry, ("module",), path, "tax", "state")
    return lambda income: ZERO


STATE_MODULES: dict[str, Callable[[dict[str, Any], Path], Callable[[Decimal], Decimal]]] = {
    "none": _none,
    "flat": _flat,
    "bracket": _bracket,
}


def load_state_tax(value: Any, path: Path) -> StateTax:
    """Choose and configure the state-tax module named by ``module``."""

    entry = require_mapping(value, path, "tax", "state")
    module = require_text(require(entry, "module", path, "tax", "state"), path, "tax", "state",
                          "module")
    factory = STATE_MODULES.get(module)
    if factory is None:
        raise ConfigError(
            f"Unknown state tax module {module!r}", file=path, key="tax.state.module",
            fix=f"use one of {sorted(STATE_MODULES)}",
        )
    return StateTax(module=module, compute=factory(entry, path))


def bracket_tax(taxable: Decimal, brackets: tuple[Bracket, ...]) -> Decimal:
    """Progressive tax: each slice of income above a bracket's ``over`` at its rate."""

    tax = Decimal(0)
    for index, bracket in enumerate(brackets):
        top = brackets[index + 1].over if index + 1 < len(brackets) else None
        if taxable <= bracket.over:
            break
        slice_top = taxable if top is None else min(taxable, top)
        tax += (slice_top - bracket.over) * bracket.rate
    return money(tax)


def federal_income_tax(income: Decimal, table: FederalTable, status: str) -> Decimal:
    """Federal tax on ordinary ``income`` after the standard deduction."""

    figures = table.status(status)
    taxable = max(income - figures.standard_deduction, ZERO)
    return bracket_tax(taxable, figures.brackets)


def taxable_social_security(
    benefits: Decimal, other_income: Decimal, rule: SocialSecurityRule, status: str
) -> Decimal:
    """The taxable part of Social Security benefits, by the base-amount worksheet.

    Provisional income is ``other_income`` plus ``first_fraction`` of the
    benefits. Above the base amount, ``first_fraction`` of the excess is taxable,
    up to ``first_fraction`` of the benefits; above the adjusted base amount,
    ``second_fraction`` of that excess is added, and the total never exceeds
    ``second_fraction`` of the benefits.
    """

    base, adjusted = rule.for_status(status)
    first, second = rule.first_fraction, rule.second_fraction
    provisional = other_income + first * benefits
    if provisional <= base:
        return ZERO
    if provisional <= adjusted:
        return money(min(first * benefits, first * (provisional - base)))
    lower = min(first * benefits, first * (adjusted - base))
    return money(min(second * benefits, second * (provisional - adjusted) + lower))


def _status_table(value: Any, path: Path, *parents: str) -> StatusTable:
    entry = require_mapping(value, path, *parents)
    reject_unknown_keys(entry, STATUS_KEYS, path, *parents)
    deduction = _amount(require(entry, "standard_deduction", path, *parents), path, *parents,
                        "standard_deduction")
    brackets = _brackets(require(entry, "brackets", path, *parents), path, *parents)
    return StatusTable(deduction, brackets)


def _brackets(value: Any, path: Path, *parents: str) -> tuple[Bracket, ...]:
    rows = require_list(value, path, *parents, "brackets")
    brackets: list[Bracket] = []
    for index, row in enumerate(rows):
        where = (*parents, "brackets", f"[{index}]")
        entry = require_mapping(row, path, *where)
        reject_unknown_keys(entry, ("over", "rate"), path, *where)
        over = _amount(require(entry, "over", path, *where), path, *where, "over")
        rate = _rate(require(entry, "rate", path, *where), path, *where, "rate")
        if brackets and over <= brackets[-1].over:
            raise ConfigError(
                "brackets must rise", file=path, key=key_path(*where, "over"),
                fix="list brackets from the lowest threshold up",
            )
        brackets.append(Bracket(over, rate))
    if not brackets or brackets[0].over != 0:
        raise ConfigError(
            "the first bracket must start at 0", file=path, key=key_path(*parents, "brackets"),
            fix="begin the list with {over: 0, rate: ...}",
        )
    return tuple(brackets)


def _social_security(value: Any, path: Path) -> SocialSecurityRule:
    entry = require_mapping(value, path, "social_security")
    reject_unknown_keys(entry, SOCIAL_SECURITY_KEYS, path, "social_security")
    source = require_text(require(entry, "source", path, "social_security"), path,
                          "social_security", "source")
    first = _rate(require(entry, "first_fraction", path, "social_security"), path,
                  "social_security", "first_fraction")
    second = _rate(require(entry, "second_fraction", path, "social_security"), path,
                   "social_security", "second_fraction")
    thresholds = []
    for status in FILING_STATUSES:
        if status not in entry:
            continue
        row = require_mapping(entry[status], path, "social_security", status)
        reject_unknown_keys(row, THRESHOLD_KEYS, path, "social_security", status)
        base = _amount(require(row, "base", path, "social_security", status), path,
                       "social_security", status, "base")
        adjusted = _amount(require(row, "adjusted_base", path, "social_security", status), path,
                           "social_security", status, "adjusted_base")
        thresholds.append((status, base, adjusted))
    return SocialSecurityRule(source, first, second, tuple(thresholds))


def _amount(value: Any, path: Path, *parents: str) -> Decimal:
    try:
        amount = (Decimal(str(value)) if isinstance(value, (int, float, str))
                  and not isinstance(value, bool) else None)
    except InvalidOperation:
        amount = None
    if amount is None or not amount.is_finite() or amount < 0:
        raise ConfigError(
            f"Invalid amount {value!r}", file=path, key=key_path(*parents),
            fix="write a dollar amount of zero or more",
        )
    return amount


def _rate(value: Any, path: Path, *parents: str) -> Decimal:
    try:
        rate = (Decimal(str(value)) if isinstance(value, (int, float))
                and not isinstance(value, bool) else None)
    except InvalidOperation:
        rate = None
    if rate is None or not rate.is_finite() or not 0 <= rate <= 1:
        raise ConfigError(
            f"Invalid rate {value!r}", file=path, key=key_path(*parents),
            fix="write the rate as a fraction from 0 to 1, such as 0.04 for 4 percent",
        )
    return rate


__all__ = [
    "FILING_STATUSES",
    "STATE_MODULES",
    "Bracket",
    "FederalTable",
    "SocialSecurityRule",
    "StateTax",
    "TaxConfig",
    "bracket_tax",
    "check_staleness",
    "federal_income_tax",
    "load_federal_table",
    "load_state_tax",
    "load_tax_config",
    "newest_federal_table",
    "tax_data_dir",
    "taxable_social_security",
]
