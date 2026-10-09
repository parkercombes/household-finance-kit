"""Command line interface for hfk.

Only M0 foundation commands are implemented today. Analysis commands are stubs
until their roadmap milestones are built.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from hfk import __version__
from hfk.config import ConfigError, Month, load_declarations, load_household, load_plan
from hfk.engine import (
    BucketError,
    CategoriesError,
    ScorecardError,
    ShareError,
    build_categories,
    build_scorecard,
    run_doctor,
)
from hfk.source import TillerFormatError, find_workbook, read_tiller
from hfk.source.fixture import build_fixture

_STUB_MILESTONES = {
    "balances": "M4",
    "networth": "M4",
    "renewals": "M4",
    "rebaseline": "M4",
    "init": "M5",
    "plan": "M4",
    "settle": "M7",
    "retirement": "M8",
}


def _stub(name: str) -> int:
    milestone = _STUB_MILESTONES[name]
    print(
        f"hfk {name}: not implemented yet (see docs/ROADMAP.md, milestone {milestone})",
        file=sys.stderr,
    )
    return 2


def _dev_help(parser: argparse.ArgumentParser) -> int:
    parser.print_help(sys.stderr)
    return 2


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("write dates as YYYY-MM-DD") from exc


def _parse_month(value: str) -> Month:
    try:
        return Month.parse(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("write months as YYYY-MM") from exc


def _doctor(args: argparse.Namespace) -> int:
    report = run_doctor(
        Path(args.home),
        today=args.today,
        stale_after_days=args.stale_days,
    )
    for diagnostic in report.diagnostics:
        print(diagnostic.render())
    print(f"doctor: {len(report.errors())} errors, {len(report.warnings())} warnings")
    return 0 if report.ok else 1


def _scorecard(args: argparse.Namespace) -> int:
    home = Path(args.home)
    try:
        household = load_household(home)
        declarations = load_declarations(home, people=household.slugs)
        plan = load_plan(home, declarations=declarations, people=household.slugs)
        who = args.who
        if who is None:
            if len(household.slugs) != 1:
                print(
                    f"scorecard: choose --who from: {', '.join(household.slugs)}",
                    file=sys.stderr,
                )
                return 1
            who = household.slugs[0]

        workbook = find_workbook(home / "data", household.tiller_glob)
        ledger = read_tiller(workbook)
        scorecard = build_scorecard(
            ledger=ledger,
            household=household,
            declarations=declarations,
            plan=plan,
            month=args.month,
            who=who,
            today=args.today if args.today is not None else date.today(),  # noqa: DTZ011
        )
    except (ConfigError, TillerFormatError, ShareError, BucketError, ScorecardError) as error:
        print(f"scorecard: {error}", file=sys.stderr)
        return 1

    print(f"scorecard {scorecard.month} for {scorecard.who} (closed month, shares per declarations)")
    width = max((len(bucket.bucket) for bucket in scorecard.buckets), default=len("total"))
    for bucket in scorecard.buckets:
        print(
            f"{bucket.bucket:<{width}}  plan {_money(bucket.planned)}  "
            f"actual {_money(bucket.actual)}  left {_money(bucket.variance)}"
        )
    print(
        f"total  plan {_money(scorecard.planned_total)}  actual {_money(scorecard.actual_total)}  "
        f"left {_money(scorecard.planned_total - scorecard.actual_total)}"
    )
    if scorecard.clamped:
        print(f"note: window clamped to history_start {scorecard.window_start.isoformat()}")
    return 0


def _categories(args: argparse.Namespace) -> int:
    home = Path(args.home)
    try:
        household = load_household(home)
        declarations = load_declarations(home, people=household.slugs)
        plan = load_plan(home, declarations=declarations, people=household.slugs)
        who = args.who
        if who is None:
            if len(household.slugs) != 1:
                print(
                    f"categories: choose --who from: {', '.join(household.slugs)}",
                    file=sys.stderr,
                )
                return 1
            who = household.slugs[0]

        workbook = find_workbook(home / "data", household.tiller_glob)
        ledger = read_tiller(workbook)
        report = build_categories(
            ledger=ledger,
            household=household,
            declarations=declarations,
            plan=plan,
            month=args.month,
            who=who,
            today=args.today if args.today is not None else date.today(),  # noqa: DTZ011
        )
    except (ConfigError, TillerFormatError, ShareError, BucketError, CategoriesError) as error:
        print(f"categories: {error}", file=sys.stderr)
        return 1

    if report.closed:
        print(
            f"categories {report.month} for {report.who} "
            f"(closed month, {report.window_days} of {report.days_in_month} days)"
        )
    else:
        print(
            f"categories {report.month} for {report.who} "
            f"(through {report.window_end.isoformat()}, "
            f"{report.window_days} of {report.days_in_month} days)"
        )
    if not report.lines:
        print(f"no plan lines with categories for {report.who} in {report.month}")
        return 0
    width = max(len(line.desc) for line in report.lines)
    for line in report.lines:
        paced = "paced" if line.paced else "fixed"
        print(
            f"{line.desc:<{width}}  {paced}  "
            f"target {_money(line.target)}  actual {_money(line.actual)}  "
            f"left {_money(line.variance)}"
        )
    print(
        f"total  target {_money(report.target_total)}  actual {_money(report.actual_total)}  "
        f"left {_money(report.target_total - report.actual_total)}"
    )
    if report.clamped:
        print(f"note: window clamped to history_start {report.window_start.isoformat()}")
    return 0


def _dev_fixture(args: argparse.Namespace) -> int:
    output = build_fixture(args.out, months=args.months)
    print(output)
    return 0


def _money(amount: object) -> str:
    return f"{amount:.2f}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hfk")
    parser.add_argument(
        "--home",
        default=os.environ.get("HFK_HOME", "."),
        help="Instance directory (default: HFK_HOME or current directory).",
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit.")

    subparsers = parser.add_subparsers(dest="command", metavar="command")
    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument(
        "--home",
        default=argparse.SUPPRESS,
        help="Instance directory (default: HFK_HOME or current directory).",
    )
    doctor_parser.add_argument("--today", type=_parse_date, help="Date for reproducible checks.")
    doctor_parser.add_argument("--stale-days", type=int, default=14, help="Stale data threshold.")
    doctor_parser.set_defaults(func=_doctor)

    scorecard_parser = subparsers.add_parser("scorecard")
    scorecard_parser.add_argument("--month", required=True, type=_parse_month, help="Closed month.")
    scorecard_parser.add_argument("--who", help="Household person slug.")
    scorecard_parser.add_argument("--today", type=_parse_date, help="Date for reproducible checks.")
    scorecard_parser.add_argument(
        "--home",
        default=argparse.SUPPRESS,
        help="Instance directory (default: HFK_HOME or current directory).",
    )
    scorecard_parser.set_defaults(func=_scorecard)

    categories_parser = subparsers.add_parser("categories")
    categories_parser.add_argument("--month", required=True, type=_parse_month, help="Month to report.")
    categories_parser.add_argument("--who", help="Household person slug.")
    categories_parser.add_argument("--today", type=_parse_date, help="Date for reproducible pacing.")
    categories_parser.add_argument(
        "--home",
        default=argparse.SUPPRESS,
        help="Instance directory (default: HFK_HOME or current directory).",
    )
    categories_parser.set_defaults(func=_categories)

    for name in _STUB_MILESTONES:
        subparser = subparsers.add_parser(name)
        subparser.set_defaults(func=lambda _args, command=name: _stub(command))

    dev_parser = subparsers.add_parser("dev")
    dev_subparsers = dev_parser.add_subparsers(dest="dev_command", metavar="command")
    fixture_parser = dev_subparsers.add_parser("fixture")
    fixture_parser.add_argument("--out", required=True, help="Output workbook path.")
    fixture_parser.add_argument("--months", type=int, default=6, help="Number of months.")
    fixture_parser.set_defaults(func=_dev_fixture)
    dev_parser.set_defaults(func=lambda _args, dev_parser=dev_parser: _dev_help(dev_parser))

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(f"hfk {__version__}")
        return 0
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
