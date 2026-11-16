"""The ``settle_up`` extension (M7; design brief section 8a; ADR-0004, ADR-0009).

A built-in-first extension: it ships inside the ``household-finance-kit``
distribution and registers through its ``hfk.extensions`` entry point, so core
discovers it like any other extension and never imports it. A household turns
it on with ``extensions: [settle_up]`` in ``household.yaml``.

Who paid a shared account's charges is declared in the extension's own
``settle_up.yaml`` (ADR-0016, ADR-0017); ``hfk settle YYYY-MM`` prints the
statement for a finished month.

Settle-up is for exactly two people (ADR-0004), even though the core
ownership model is N-person: one or three people is a loud error, from
``hfk doctor`` and from every settle-up command.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from hfk import __version__
from hfk.config import ConfigError, Household, Month
from hfk.engine import Diagnostic, DoctorContext
from hfk.ext import CommandContext, ExtensionCommand

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


def _load_settle_up(data: dict, path: Path) -> object:
    from hfk.ext.settle_up.config import load_settle_up

    return load_settle_up(data, path)


def _configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("month", type=_month, help="The finished month to settle, YYYY-MM.")
    parser.add_argument(
        "--format", choices=("text", "csv", "html", "paste"), default="text",
        help="Output format (default: text); paste is a tab-separated block to paste into "
        "your own spreadsheet tab. hfk never writes the workbook.",
    )
    parser.add_argument(
        "--compare",
        metavar="FILE",
        help="A hand-built statement (YAML) to check this one against, to the cent.",
    )


def _month(value: str) -> Month:
    try:
        return Month.parse(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("write the month as YYYY-MM") from error


def _run(args: argparse.Namespace, context: CommandContext) -> int:
    from hfk.ext.settle_up import render
    from hfk.ext.settle_up.config import check_payers
    from hfk.ext.settle_up.items import load_shared_items
    from hfk.ext.settle_up.statement import build_statement, check_month_finished
    from hfk.source import TillerFormatError

    try:
        check_month_finished(args.month, context.today)
        check_payers(context.config, context.household)
        items = load_shared_items(
            context.home, args.month, household=context.household,
            declarations=context.declarations,
        )
        statement = build_statement(
            ledger=context.load_ledger(),
            household=context.household,
            declarations=context.declarations,
            config=context.config,
            items=items,
            month=args.month,
            today=context.today,
        )
    except (ConfigError, SettleUpError, TillerFormatError, ValueError) as error:
        print(f"settle: {error}", file=sys.stderr)
        return 1
    renderers = {
        "text": render.render_text,
        "csv": render.render_csv,
        "html": render.render_html,
        "paste": render.render_paste,
    }
    sys.stdout.write(renderers[args.format](statement))
    if args.compare is not None:
        from hfk.ext.settle_up.regression import compare, load_expected

        try:
            differences = compare(statement, load_expected(Path(args.compare)))
        except ConfigError as error:
            print(f"settle: {error}", file=sys.stderr)
            return 1
        for difference in differences:
            print(f"compare: {difference.render()}", file=sys.stderr)
        if differences:
            print(f"compare: {len(differences)} differences from {args.compare}", file=sys.stderr)
            return 1
        print(f"compare: matches {args.compare} to the cent", file=sys.stderr)
    return 0


class SettleUp:
    """The ``settle_up`` extension object (the M6 contract)."""

    name = NAME
    version = __version__
    contract_version = "1.0.0"
    config_section = "settle_up.yaml"
    schema = staticmethod(_load_settle_up)
    requires: ClassVar[dict[str, list[str]]] = {
        "ledger_fields": ["transactions", "categories"],
        "extensions": [],
    }

    def commands(self) -> list:
        return [
            ExtensionCommand(
                name="settle",
                help="Print the settle-up statement for a finished month.",
                configure=_configure,
                run=_run,
            )
        ]

    def doctor(self, context: DoctorContext, config: object) -> Iterator[Diagnostic]:
        if context.household is None:
            return
        from hfk.ext.settle_up.config import check_payers

        try:
            check_payers(config, context.household)
        except ConfigError as error:
            yield Diagnostic(
                "error", "settle-up-config", f"{error.file.name} key={error.key}",
                error.problem, error.fix,
            )
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
