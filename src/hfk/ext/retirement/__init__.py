"""The ``retirement`` extension (M8; design brief section 8b; ADR-0005, ADR-0008).

A built-in-first extension: an income-vs-need model in today's dollars. It
shows arithmetic and scenarios, never advice: it does not recommend
products, tax strategy, claiming strategy, or investment decisions. Its input
is the instance's own ``retirement.yaml``; a household turns it on with
``extensions: [retirement]`` in ``household.yaml``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

from hfk import __version__
from hfk.config import ConfigError
from hfk.engine import Diagnostic, DoctorContext
from hfk.ext import CommandContext, ExtensionCommand
from hfk.ext.retirement.schema import CONFIG_FILE, RetirementConfig, check_people, load_retirement

NAME = "retirement"


def _configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--claim-age",
        action="append",
        dest="claim_age",
        metavar="SLUG=AGE",
        help="The Social Security claim age for one person, such as alex=67; repeat per person.",
    )
    parser.add_argument(
        "--format", choices=("text", "csv", "html"), default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--tax-table",
        dest="tax_table",
        help="A federal tax table file to use instead of the newest packaged one.",
    )


def _run(args: argparse.Namespace, context: CommandContext) -> int:
    from hfk.config import load_instance_plan
    from hfk.ext.retirement.render import render_csv, render_html, render_text
    from hfk.ext.retirement.report import build_retirement_report, parse_claim_ages
    from hfk.ext.retirement.tax import load_federal_table, newest_federal_table

    config = context.config
    try:
        scenario = parse_claim_ages(args.claim_age, config.path)
        plan = None
        if config.expenses is not None and config.expenses.seed_month is not None:
            plan = load_instance_plan(
                context.home, household=context.household, declarations=context.declarations
            )
        table = (
            load_federal_table(Path(args.tax_table))
            if args.tax_table is not None
            else newest_federal_table()
        )
        report = build_retirement_report(
            config,
            household=context.household,
            plan=plan,
            table=table,
            scenario=scenario,
            today=context.today,
        )
    except ConfigError as error:
        print(f"retirement: {error}", file=sys.stderr)
        return 1
    renderer = {"text": render_text, "csv": render_csv, "html": render_html}[args.format]
    sys.stdout.write(renderer(report))
    return 0


class Retirement:
    """The ``retirement`` extension object (the M6 contract)."""

    name = NAME
    version = __version__
    contract_version = "1.0.0"
    config_section = CONFIG_FILE
    schema = staticmethod(load_retirement)
    requires: ClassVar[dict[str, list[str]]] = {"ledger_fields": [], "extensions": []}

    def commands(self) -> list:
        return [
            ExtensionCommand(
                name="retirement",
                help="Show the calendar-year retirement income-vs-need track.",
                configure=_configure,
                run=_run,
            )
        ]

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
