"""The calendar-year income-vs-need track (M8-05, R5; ADR-0008, ADR-0018).

Every figure is in today's dollars, priced in the current year. For each
calendar year from the first retirement year until the youngest person reaches
``until_age``:

- **Household view**: income from every stream; federal tax on the ordinary
  taxable income (streams with ``taxable: full``) plus the taxable part of Social
  Security; state tax from the household's state module; need (every expense);
  and the gap, income minus federal tax, state tax and need. A negative gap is a
  shortfall.
- **Per-person view**: each person's own income streams and own expenses (those
  with ``who``), and their difference *before tax*. Tax is a joint figure, so it
  is counted only in the household view, and so are expenses with no ``who``.

Tax rules (ADR-0018): federal brackets and the standard deduction stay flat in
today's dollars; the Social Security base amounts are fixed in nominal dollars,
so in today's dollars they shrink by ``inflation`` each year after the federal
table's tax year.

The report shows arithmetic for the scenario the household chose. It never
picks a claim age, compares scenarios, or recommends anything.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from hfk.config import ConfigError, Household, Plan
from hfk.ext.retirement.expenses import all_expenses
from hfk.ext.retirement.income import check_scenario, stream_amount
from hfk.ext.retirement.schema import RetirementConfig, check_people
from hfk.ext.retirement.tax import (
    FederalTable,
    check_staleness,
    federal_income_tax,
    taxable_social_security,
)
from hfk.ledger import money

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class HouseholdYear:
    year: int
    income: Decimal
    ordinary_taxable: Decimal
    social_security: Decimal
    taxable_social_security: Decimal
    federal_tax: Decimal
    state_tax: Decimal
    need: Decimal
    gap: Decimal


@dataclass(frozen=True)
class PersonYear:
    year: int
    who: str
    age: int
    income: Decimal
    need: Decimal
    before_tax: Decimal


@dataclass(frozen=True)
class RetirementReport:
    first_year: int
    last_year: int
    base_year: int
    inflation: Decimal | None
    scenario: tuple[tuple[str, int], ...]
    tax_year: int
    tax_source: str
    filing_status: str
    state_module: str
    state_taxes_social_security: bool
    household: tuple[HouseholdYear, ...]
    people: tuple[PersonYear, ...]


def build_retirement_report(
    config: RetirementConfig,
    *,
    household: Household,
    plan: Plan | None,
    table: FederalTable,
    scenario: dict[str, int],
    today: date,
) -> RetirementReport:
    """Build the track; every missing input is a ``ConfigError``, never a default."""

    check_people(config, household)
    path = config.path
    if config.expenses is None:
        raise ConfigError(
            "retirement.yaml has no expenses, so there is no need to compare income with",
            file=path,
            key="expenses",
            fix="add expenses: {items: [...]} or expenses: {seed_from_plan: {month: YYYY-MM}}",
        )
    if config.tax is None:
        raise ConfigError(
            "retirement.yaml has no tax section",
            file=path,
            key="tax",
            fix="add tax: {filing_status: ..., max_data_age_years: ..., state: {module: ...}}",
        )
    check_scenario(config.income, scenario, path)
    check_staleness(
        table,
        current_year=today.year,
        max_age_years=config.tax.max_data_age_years,
        config_path=path,
    )
    inflation = config.assumptions.inflation
    has_social_security = any(stream.type == "social_security" for stream in config.income)
    if has_social_security and inflation is None:
        raise ConfigError(
            "assumptions.inflation is required to keep the Social Security tax thresholds in "
            "today's dollars",
            file=path,
            key="assumptions.inflation",
            fix="add inflation under assumptions, such as 0.025 (ADR-0018)",
        )
    expenses = all_expenses(config.expenses, plan, path=path)
    status = config.tax.filing_status
    state = config.tax.state
    base_year = today.year

    household_rows: list[HouseholdYear] = []
    person_rows: list[PersonYear] = []
    for year in range(config.first_year, config.last_year + 1):
        income_by_person = {person.slug: ZERO for person in config.people}
        ordinary = ZERO
        benefits = ZERO
        for stream in config.income:
            person = config.person(stream.who)
            assert person is not None
            amount = stream_amount(
                stream,
                year,
                birth_year=person.birth_year,
                birth_month=person.birth_month,
                claim_age=scenario.get(stream.who),
                inflation=inflation,
            )
            income_by_person[stream.who] += amount
            if stream.type == "social_security":
                benefits += amount
            elif stream.taxable == "full":
                ordinary += amount
        rule = table.social_security
        if has_social_security:
            shrink = (1 + inflation) ** (year - table.tax_year)
            rule = replace(
                rule,
                thresholds=tuple(
                    (name, base / shrink, adjusted / shrink)
                    for name, base, adjusted in rule.thresholds
                ),
            )
        taxable_benefits = (
            taxable_social_security(benefits, ordinary, rule, status) if benefits else ZERO
        )
        federal = federal_income_tax(ordinary + taxable_benefits, table, status)
        state_base = ordinary + (taxable_benefits if state.taxes_social_security else ZERO)
        state_tax = state.compute(state_base)
        need = money(sum((e.amount_in(year, base_year=base_year) for e in expenses), ZERO))
        income = money(sum(income_by_person.values(), ZERO))
        household_rows.append(
            HouseholdYear(
                year=year,
                income=income,
                ordinary_taxable=money(ordinary),
                social_security=money(benefits),
                taxable_social_security=taxable_benefits,
                federal_tax=federal,
                state_tax=state_tax,
                need=need,
                gap=money(income - federal - state_tax - need),
            )
        )
        for person in config.people:
            own_need = money(
                sum(
                    (e.amount_in(year, base_year=base_year) for e in expenses
                     if e.who == person.slug),
                    ZERO,
                )
            )
            own_income = money(income_by_person[person.slug])
            person_rows.append(
                PersonYear(
                    year=year,
                    who=person.slug,
                    age=person.age_in(year),
                    income=own_income,
                    need=own_need,
                    before_tax=money(own_income - own_need),
                )
            )

    return RetirementReport(
        first_year=config.first_year,
        last_year=config.last_year,
        base_year=base_year,
        inflation=inflation,
        scenario=tuple(sorted(scenario.items())),
        tax_year=table.tax_year,
        tax_source=table.source,
        filing_status=status,
        state_module=state.module,
        state_taxes_social_security=state.taxes_social_security,
        household=tuple(household_rows),
        people=tuple(person_rows),
    )


def parse_claim_ages(values: list[str] | None, path: Path) -> dict[str, int]:
    """``alex=67`` pairs from the command line."""

    scenario: dict[str, int] = {}
    for value in values or ():
        slug, separator, age = value.partition("=")
        if not separator or not slug.strip() or not age.strip().isdigit():
            raise ConfigError(
                f"--claim-age {value!r} is not slug=age",
                file=path,
                key="--claim-age",
                fix="write --claim-age alex=67, once per person with Social Security",
            )
        scenario[slug.strip()] = int(age)
    return scenario


__all__ = [
    "HouseholdYear",
    "PersonYear",
    "RetirementReport",
    "build_retirement_report",
    "parse_claim_ages",
]
