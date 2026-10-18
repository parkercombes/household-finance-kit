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
from hfk.config import (
    ConfigError,
    Month,
    check_plan,
    load_declarations,
    load_household,
    load_plan,
)
from hfk.engine import (
    BalancesError,
    BucketError,
    CategoriesError,
    NetWorthError,
    RebaselineError,
    RenewalsError,
    ScorecardError,
    ShareError,
    build_balances,
    build_categories,
    build_networth,
    build_rebaseline,
    build_renewals,
    build_scorecard,
    run_doctor,
)
from hfk.instance import InstanceError, write_instance
from hfk.render import (
    money,
    render_balances,
    render_categories,
    render_networth,
    render_renewals,
    render_scorecard,
)
from hfk.source import TillerFormatError, find_workbook, read_tiller
from hfk.source.fixture import build_fixture

_STUB_MILESTONES = {
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


def _subcommand_help(parser: argparse.ArgumentParser) -> int:
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

    sys.stdout.write(render_scorecard(scorecard))
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

    sys.stdout.write(render_categories(report))
    return 0


def _balances(args: argparse.Namespace) -> int:
    home = Path(args.home)
    try:
        household = load_household(home)
        declarations = load_declarations(home, people=household.slugs)
        workbook = find_workbook(home / "data", household.tiller_glob)
        ledger = read_tiller(workbook)
        report = build_balances(
            ledger=ledger,
            household=household,
            declarations=declarations,
            as_of=args.as_of,
        )
    except (ConfigError, TillerFormatError, BalancesError) as error:
        print(f"balances: {error}", file=sys.stderr)
        return 1

    sys.stdout.write(render_balances(report, history_start=household.history_start))
    return 0


def _networth(args: argparse.Namespace) -> int:
    home = Path(args.home)
    try:
        household = load_household(home)
        declarations = load_declarations(home, people=household.slugs)
        workbook = find_workbook(home / "data", household.tiller_glob)
        ledger = read_tiller(workbook)
        report = build_networth(
            ledger=ledger,
            household=household,
            declarations=declarations,
            as_of=args.as_of,
            stale_after_days=args.stale_after_days,
        )
    except (ConfigError, TillerFormatError, NetWorthError) as error:
        print(f"networth: {error}", file=sys.stderr)
        return 1

    sys.stdout.write(render_networth(report, history_start=household.history_start))
    return 0


def _renewals(args: argparse.Namespace) -> int:
    home = Path(args.home)
    try:
        household = load_household(home)
        declarations = load_declarations(home, people=household.slugs)
        plan = load_plan(home, declarations=declarations, people=household.slugs)
        report = build_renewals(
            plan=plan,
            household=household,
            month=args.month,
            who=args.who,
        )
    except (ConfigError, RenewalsError) as error:
        print(f"renewals: {error}", file=sys.stderr)
        return 1

    sys.stdout.write(render_renewals(report))
    return 0


def _rebaseline(args: argparse.Namespace) -> int:
    home = Path(args.home)
    try:
        household = load_household(home)
        declarations = load_declarations(home, people=household.slugs)
        plan = load_plan(home, declarations=declarations, people=household.slugs)
        who = args.who
        if who is None:
            if len(household.slugs) != 1:
                print(
                    f"rebaseline: choose --who from: {', '.join(household.slugs)}",
                    file=sys.stderr,
                )
                return 1
            who = household.slugs[0]

        workbook = find_workbook(home / "data", household.tiller_glob)
        ledger = read_tiller(workbook)
        today = args.today if args.today is not None else date.today()  # noqa: DTZ011
        through = args.through if args.through is not None else _month_before(today)
        report = build_rebaseline(
            ledger=ledger,
            household=household,
            declarations=declarations,
            plan=plan,
            who=who,
            through=through,
            months=args.months,
            today=today,
        )
    except (ConfigError, TillerFormatError, ShareError, BucketError, RebaselineError) as error:
        print(f"rebaseline: {error}", file=sys.stderr)
        return 1

    print(
        f"rebaseline for {report.who}  "
        f"window {report.window_start}..{report.window_end}  months {report.months}"
    )
    if not report.lines:
        print(f"no spend for {report.who} in the window")
    else:
        width = max(len(line.category) for line in report.lines)
        for line in report.lines:
            row = "  ".join(
                (
                    f"{line.category:<{width}}",
                    f"months {line.nonzero_months}/{report.months}",
                    f"mean {money(line.mean)}",
                    f"median {money(line.median)}",
                    f"max {money(line.max)}",
                    f"current {_amount_or_dash(line.current)}",
                    f"proposed {_amount_or_dash(line.proposed)}",
                    line.classification,
                )
            )
            for flag in line.flags:
                row += f"; {flag}"
            print(row)
    print(f"stable {report.stable}  lumpy {report.lumpy}  spiky {report.spiky}")
    if report.clamped:
        print(f"note: window clamped to history_start {report.history_start.isoformat()}")
    return 0


def _plan_check(args: argparse.Namespace) -> int:
    home = Path(args.home)
    try:
        household = load_household(home)
        declarations = load_declarations(home, people=household.slugs)
    except ConfigError as error:
        print(f"plan check: {error}", file=sys.stderr)
        return 1

    report = check_plan(home, declarations=declarations, people=household.slugs)
    print(f"plan check {report.path}")
    for problem in report.problems:
        line = "-" if problem.line == 0 else str(problem.line)
        print(f"  line {line}  {problem.key}  {problem.problem}; fix: {problem.fix}")
    if report.ok:
        print(f"ok: {report.line_count} lines")
        return 0
    count = len(report.problems)
    plural = "problem" if count == 1 else "problems"
    print(f"{count} {plural}")
    return 1


def _month_before(value: date) -> Month:
    year, month = value.year, value.month - 1
    if month == 0:
        year, month = year - 1, 12
    return Month(year, month)


def _amount_or_dash(amount: object) -> str:
    return "-" if amount is None else money(amount)


def _dev_fixture(args: argparse.Namespace) -> int:
    output = build_fixture(args.out, months=args.months)
    print(output)
    return 0


def _init(args: argparse.Namespace) -> int:
    try:
        report = write_instance(Path(args.dir), git=args.git)
    except InstanceError as error:
        print(f"init: {error}", file=sys.stderr)
        return 1

    print(f"created {args.dir}")
    for path in report.created:
        relative = path.relative_to(report.home)
        suffix = "/" if path.is_dir() else ""
        print(f"  {relative}{suffix}")
    if report.git_initialised:
        print("git: initialised with pre-commit hook")
    print("next: put the Tiller workbook export in data/")
    print(f"then run: hfk plan check --home {args.dir} and hfk doctor --home {args.dir}")
    return 0


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

    balances_parser = subparsers.add_parser("balances")
    balances_parser.add_argument(
        "--as-of",
        type=_parse_date,
        default=date.today(),  # noqa: DTZ011
        dest="as_of",
        help="Report date; each account shows its latest observation on or before it.",
    )
    balances_parser.add_argument(
        "--home",
        default=argparse.SUPPRESS,
        help="Instance directory (default: HFK_HOME or current directory).",
    )
    balances_parser.set_defaults(func=_balances)

    networth_parser = subparsers.add_parser("networth")
    networth_parser.add_argument(
        "--as-of",
        type=_parse_date,
        default=date.today(),  # noqa: DTZ011
        dest="as_of",
        help="Report date; each account shows its latest observation on or before it.",
    )
    networth_parser.add_argument(
        "--stale-after-days",
        type=int,
        default=14,
        dest="stale_after_days",
        help="Flag synced accounts whose latest observation is older than this many days.",
    )
    networth_parser.add_argument(
        "--home",
        default=argparse.SUPPRESS,
        help="Instance directory (default: HFK_HOME or current directory).",
    )
    networth_parser.set_defaults(func=_networth)

    renewals_parser = subparsers.add_parser("renewals")
    renewals_parser.add_argument(
        "--month",
        type=_parse_month,
        default=Month(date.today().year, date.today().month),  # noqa: DTZ011
        help="Report month; the schedule and fund are shown as of that month.",
    )
    renewals_parser.add_argument("--who", help="Household person slug.")
    renewals_parser.add_argument(
        "--home",
        default=argparse.SUPPRESS,
        help="Instance directory (default: HFK_HOME or current directory).",
    )
    renewals_parser.set_defaults(func=_renewals)

    rebaseline_parser = subparsers.add_parser("rebaseline")
    rebaseline_parser.add_argument("--who", help="Household person slug.")
    rebaseline_parser.add_argument(
        "--months",
        type=int,
        default=6,
        help="Number of closed months to analyze (at least 2).",
    )
    rebaseline_parser.add_argument(
        "--through",
        type=_parse_month,
        help="Last month of the window (default: the month before today).",
    )
    rebaseline_parser.add_argument("--today", type=_parse_date, help="Date for reproducible checks.")
    rebaseline_parser.add_argument(
        "--home",
        default=argparse.SUPPRESS,
        help="Instance directory (default: HFK_HOME or current directory).",
    )
    rebaseline_parser.set_defaults(func=_rebaseline)

    plan_parser = subparsers.add_parser("plan")
    plan_subparsers = plan_parser.add_subparsers(dest="plan_command", metavar="command")
    plan_check_parser = plan_subparsers.add_parser("check")
    plan_check_parser.add_argument(
        "--home",
        default=argparse.SUPPRESS,
        help="Instance directory (default: HFK_HOME or current directory).",
    )
    plan_check_parser.set_defaults(func=_plan_check)
    plan_parser.set_defaults(
        func=lambda _args, plan_parser=plan_parser: _subcommand_help(plan_parser)
    )

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("dir", help="New instance directory.")
    init_parser.add_argument(
        "--git",
        action="store_true",
        help="Also run git init and install the privacy pre-commit hook.",
    )
    init_parser.set_defaults(func=_init)

    for name in _STUB_MILESTONES:
        subparser = subparsers.add_parser(name)
        subparser.set_defaults(func=lambda _args, command=name: _stub(command))

    dev_parser = subparsers.add_parser("dev")
    dev_subparsers = dev_parser.add_subparsers(dest="dev_command", metavar="command")
    fixture_parser = dev_subparsers.add_parser("fixture")
    fixture_parser.add_argument("--out", required=True, help="Output workbook path.")
    fixture_parser.add_argument("--months", type=int, default=6, help="Number of months.")
    fixture_parser.set_defaults(func=_dev_fixture)
    dev_parser.set_defaults(func=lambda _args, dev_parser=dev_parser: _subcommand_help(dev_parser))

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
