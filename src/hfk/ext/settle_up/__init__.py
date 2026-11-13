"""The ``settle_up`` extension (M7; design brief section 8a; ADR-0004, ADR-0009).

A built-in-first extension: it ships inside the ``household-finance-kit``
distribution and registers through its ``hfk.extensions`` entry point, so core
discovers it like any other extension and never imports it. A household turns
it on with ``extensions: [settle_up]`` in ``household.yaml``.

Settle-up is for exactly two people (ADR-0004), even though the core
ownership model is N-person: one or three people is a loud error, from
``hfk doctor`` and from every settle-up command.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import ClassVar

from hfk import __version__
from hfk.config import Household
from hfk.engine import Diagnostic, DoctorContext

NAME = "settle_up"
SHARED_ITEMS_DIR = "shared-items"
PEOPLE_FIX = (
    "settle-up needs exactly two people under people in household.yaml; "
    f"remove {NAME} from extensions for any other household"
)


@dataclass(frozen=True)
class SettleUpError(ValueError):
    """A settle-up problem and its fix."""

    problem: str
    fix: str

    def __post_init__(self) -> None:
        ValueError.__init__(self, str(self))

    def __str__(self) -> str:
        return f"{self.problem}. Fix: {self.fix}"


def two_people(household: Household) -> tuple[str, str]:
    """The two person slugs settle-up works between, or ``SettleUpError``."""

    slugs = household.slugs
    if len(slugs) != 2:
        listed = ", ".join(slugs)
        raise SettleUpError(
            f"settle-up works between exactly two people, but household.yaml lists "
            f"{len(slugs)} ({listed})",
            PEOPLE_FIX,
        )
    return slugs[0], slugs[1]


class SettleUp:
    """The ``settle_up`` extension object (the M6 contract)."""

    name = NAME
    version = __version__
    contract_version = "1.0.0"
    config_section = None
    schema = None
    requires: ClassVar[dict[str, list[str]]] = {
        "ledger_fields": ["transactions", "categories"],
        "extensions": [],
    }

    def commands(self) -> list:
        return []

    def doctor(self, context: DoctorContext, config: object) -> Iterator[Diagnostic]:
        if context.household is None:
            return
        try:
            two_people(context.household)
        except SettleUpError as error:
            yield Diagnostic(
                "error", "settle-up-people", "household.yaml key=people", error.problem, error.fix
            )
        if context.declarations is None:
            return
        from hfk.ext.settle_up.items import check_shared_items_dir

        for problem in check_shared_items_dir(
            context.home, household=context.household, declarations=context.declarations
        ):
            yield Diagnostic(
                "error",
                "settle-up-shared-items",
                f"{SHARED_ITEMS_DIR}/{problem.file.name} key={problem.key}",
                problem.problem,
                problem.fix,
            )


__all__ = ["NAME", "SettleUp", "SettleUpError", "two_people"]
