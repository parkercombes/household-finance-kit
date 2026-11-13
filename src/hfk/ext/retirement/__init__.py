"""The ``retirement`` extension (M8; design brief section 8b; ADR-0005, ADR-0008).

A built-in-first extension: an income-vs-need model in today's dollars. It
shows arithmetic and scenarios, never advice: it does not recommend
products, tax strategy, claiming strategy, or investment decisions. Its input
is the instance's own ``retirement.yaml``; a household turns it on with
``extensions: [retirement]`` in ``household.yaml``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import ClassVar

from hfk import __version__
from hfk.config import ConfigError
from hfk.engine import Diagnostic, DoctorContext
from hfk.ext.retirement.schema import CONFIG_FILE, RetirementConfig, check_people, load_retirement

NAME = "retirement"


class Retirement:
    """The ``retirement`` extension object (the M6 contract)."""

    name = NAME
    version = __version__
    contract_version = "1.0.0"
    config_section = CONFIG_FILE
    schema = staticmethod(load_retirement)
    requires: ClassVar[dict[str, list[str]]] = {"ledger_fields": [], "extensions": []}

    def commands(self) -> list:
        return []

    def doctor(self, context: DoctorContext, config: RetirementConfig) -> Iterator[Diagnostic]:
        if context.household is None:
            return
        try:
            check_people(config, context.household)
        except ConfigError as error:
            yield Diagnostic(
                "error",
                "retirement-config",
                f"{error.file.name} key={error.key}",
                error.problem,
                error.fix,
            )


__all__ = ["NAME", "Retirement"]
