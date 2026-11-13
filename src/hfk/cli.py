"""Command line interface for hfk.

Only M0 foundation commands are implemented today. Analysis commands are stubs
until their roadmap milestones are built.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import webbrowser
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from hfk import __version__
from hfk.config import (
    PLAN_FILE,
    PLAN_SHEET,
    STARTER_CSV,
    ConfigError,
    Declarations,
    Household,
    Month,
    Plan,
    check_instance_plan,
    load_declarations,
    load_household,
    load_instance_plan,
    plan_csv,
)
from hfk.config.plan_convert import load_plan_file
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
from hfk.ext import (
    CommandContext,
    Extension,
    ExtensionCommand,
    LoadedExtensions,
    enabled_extension,
    load_extension_config,
    load_extensions,
)
from hfk.ext.doctor import extension_doctor_hooks
from hfk.instance import InstanceError, InstanceReport, write_instance
from hfk.interview import (
    InterviewError,
    Question,
    find_interview_workbooks,
    load_answers,
    run_interview,
)
from hfk.render import money, render_csv, render_html, render_text
from hfk.serve import DEFAULT_HOST, DEFAULT_PORT, ServeError, make_server, server_url
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


def _load_plan(home: Path, household: Household, declarations: Declarations) -> Plan:
    return load_instance_plan(home, household=household, declarations=declarations)


def _doctor(args: argparse.Namespace) -> int:
    report = run_doctor(
        Path(args.home),
        today=args.today,
        stale_after_days=args.stale_days,
        hooks=extension_doctor_hooks(load_extensions()),
    )
    for diagnostic in report.diagnostics:
        print(diagnostic.render())
    print(f"readiness: {'ready' if report.ready else 'not ready'}")
    for check in report.readiness:
        print(check.render())
    print(f"doctor: {len(report.errors())} errors, {len(report.warnings())} warnings")
    return 0 if report.ok else 1


def _scorecard(args: argparse.Namespace) -> int:
    home = Path(args.home)
    try:
        household = load_household(home)
        declarations = load_declarations(home, people=household.slugs)
        plan = _load_plan(home, household, declarations)
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

    if args.format == "csv":
        sys.stdout.write(render_csv(scorecard))
    elif args.format == "html":
        sys.stdout.write(render_html(scorecard))
    else:
        sys.stdout.write(render_text(scorecard))
    return 0


def _categories(args: argparse.Namespace) -> int:
    home = Path(args.home)
    try:
        household = load_household(home)
        declarations = load_declarations(home, people=household.slugs)
        plan = _load_plan(home, household, declarations)
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

    if args.format == "csv":
        sys.stdout.write(render_csv(report))
    elif args.format == "html":
        sys.stdout.write(render_html(report))
    else:
        sys.stdout.write(render_text(report))
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

    if args.format == "csv":
        sys.stdout.write(render_csv(report))
    elif args.format == "html":
        sys.stdout.write(render_html(report, history_start=household.history_start))
    else:
        sys.stdout.write(render_text(report, history_start=household.history_start))
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

    if args.format == "csv":
        sys.stdout.write(render_csv(report))
    elif args.format == "html":
        sys.stdout.write(render_html(report, history_start=household.history_start))
    else:
        sys.stdout.write(render_text(report, history_start=household.history_start))
    return 0


def _renewals(args: argparse.Namespace) -> int:
    home = Path(args.home)
    try:
        household = load_household(home)
        declarations = load_declarations(home, people=household.slugs)
        plan = _load_plan(home, household, declarations)
        report = build_renewals(
            plan=plan,
            household=household,
            month=args.month,
            who=args.who,
        )
    except (ConfigError, TillerFormatError, RenewalsError) as error:
        print(f"renewals: {error}", file=sys.stderr)
        return 1

    if args.format == "csv":
        sys.stdout.write(render_csv(report))
    elif args.format == "html":
        sys.stdout.write(render_html(report))
    else:
        sys.stdout.write(render_text(report))
    return 0


def _rebaseline(args: argparse.Namespace) -> int:
    home = Path(args.home)
    try:
        household = load_household(home)
        declarations = load_declarations(home, people=household.slugs)
        plan = _load_plan(home, household, declarations)
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

    report = check_instance_plan(home, household=household, declarations=declarations)
    if report.path.suffix.lower().startswith(".xls"):
        print(f"plan check {report.path} (sheet {PLAN_SHEET})")
    else:
        print(f"plan check {report.path}")
    for problem in report.problems:
        if problem.sheet is not None:
            row = "-" if problem.line == 0 else str(problem.line)
            column = problem.column or "-"
            print(
                f"  sheet {problem.sheet}  row {row}  column {column}  "
                f"{problem.problem}; fix: {problem.fix}"
            )
            continue
        line = "-" if problem.line == 0 else str(problem.line)
        print(f"  line {line}  {problem.key}  {problem.problem}; fix: {problem.fix}")
    if report.ok:
        print(f"ok: {report.line_count} lines")
        return 0
    count = len(report.problems)
    plural = "problem" if count == 1 else "problems"
    print(f"{count} {plural}")
    return 1


def _serve(args: argparse.Namespace) -> int:
    today = args.today
    try:
        server = make_server(
            Path(args.home),
            host=args.host,
            port=args.port,
            today=(lambda: today) if today is not None else None,
        )
    except (ServeError, OSError) as error:
        print(f"serve: {error}", file=sys.stderr)
        return 1
    print(f"serving {server_url(server)} (read-only; press Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _open(args: argparse.Namespace) -> int:
    """``hfk open``: serve on a free loopback port and open the browser on it."""

    today = args.today
    try:
        server = make_server(
            Path(args.home),
            port=0,
            today=(lambda: today) if today is not None else None,
        )
    except (ServeError, OSError) as error:
        print(f"open: {error}", file=sys.stderr)
        return 1
    url = server_url(server)
    print(f"hfk is open at {url}", flush=True)
    print("leave this window open while you read; close it or press Ctrl+C to stop", flush=True)
    previous = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _stop_on_signal)
    try:
        if not args.no_browser:
            webbrowser.open(url)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous)
        server.server_close()
    print("hfk stopped", flush=True)
    return 0


def _stop_on_signal(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def _plan_to_sheet(args: argparse.Namespace) -> int:
    """``hfk plan to-sheet``: convert a retired ``plan.yaml`` to the sheet's CSV shape."""

    home = Path(args.home)
    source = home / PLAN_FILE
    output = Path(args.out) if args.out is not None else home / STARTER_CSV
    try:
        household = load_household(home)
        declarations = load_declarations(home, people=household.slugs)
        if not source.exists():
            print(
                f"plan to-sheet: {source} does not exist: fix=nothing to convert; "
                f"the plan already lives in the {PLAN_SHEET} sheet",
                file=sys.stderr,
            )
            return 1
        plan = load_plan_file(source, declarations=declarations, people=household.slugs)
    except ConfigError as error:
        print(f"plan to-sheet: {error}", file=sys.stderr)
        return 1
    if output.exists():
        print(
            f"plan to-sheet: {output} already exists: fix=move or delete it, or pass --out",
            file=sys.stderr,
        )
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(plan_csv(plan.lines), encoding="utf-8")
    print(f"wrote {len(plan.lines)} plan lines to {output}")
    print(
        f"next: add a sheet named {PLAN_SHEET} to your workbook, paste or import {output.name} "
        "into it starting at cell A1, download the workbook into data/, run "
        f"hfk plan check --home {home}, then delete {source.name}"
    )
    return 0


def _run_extension_command(
    args: argparse.Namespace,
    *,
    extension: Extension,
    command: ExtensionCommand,
    loaded: LoadedExtensions,
) -> int:
    """Load the instance and the extension's config, then hand over to the extension."""

    home = Path(args.home)
    try:
        household = load_household(home)
        enabled_extension(extension.name, household=household, installed=loaded.extensions)
        declarations = load_declarations(home, people=household.slugs)
        config = load_extension_config(home, extension)
    except ConfigError as error:
        print(f"{command.name}: {error}", file=sys.stderr)
        return 1

    def load_ledger():
        return read_tiller(find_workbook(home / "data", household.tiller_glob))

    context = CommandContext(
        home=home,
        household=household,
        declarations=declarations,
        config=config,
        today=args.today if args.today is not None else date.today(),  # noqa: DTZ011
        load_ledger=load_ledger,
    )
    return int(command.run(args, context))


def _add_extension_commands(
    subparsers: argparse._SubParsersAction, loaded: LoadedExtensions
) -> set[str]:
    """Add every installed extension's commands; returns the names added."""

    added: set[str] = set()
    for extension in loaded.extensions:
        for command in extension.commands:
            if command.name in added:
                continue
            parser = subparsers.add_parser(
                command.name, help=f"{command.help} (extension {extension.name})"
            )
            parser.add_argument(
                "--home",
                default=argparse.SUPPRESS,
                help="Instance directory (default: HFK_HOME or current directory).",
            )
            parser.add_argument("--today", type=_parse_date, help="Date for reproducible checks.")
            command.configure(parser)
            parser.set_defaults(
                func=lambda args, extension=extension, command=command: _run_extension_command(
                    args, extension=extension, command=command, loaded=loaded
                )
            )
            added.add(command.name)
    return added


def _month_before(value: date) -> Month:
    year, month = value.year, value.month - 1
    if month == 0:
        year, month = year - 1, 12
    return Month(year, month)


def _amount_or_dash(amount: object) -> str:
    return "-" if amount is None else money(amount)


def _dev_fixture(args: argparse.Namespace) -> int:
    output = build_fixture(args.out, months=args.months, plan_tab=args.plan_tab)
    print(output)
    return 0


def _prompt(question: Question) -> str:
    default = f" [{question.default}]" if question.default is not None else ""
    print(f"{question.text}{default}")
    return input("> ")


def _init_workbooks(home: Path) -> tuple[Path, ...]:
    data_dir = home / "data"
    if not data_dir.is_dir():
        return ()
    return find_interview_workbooks(data_dir)


def _chosen_workbook(home: Path, option: str) -> Path:
    """The ``--workbook`` path, which must be a file inside the instance's ``data/``."""

    path = Path(option)
    if not path.is_absolute() and not path.exists():
        path = home / "data" / option
    if not path.is_file():
        raise InterviewError(
            f"--workbook {option} is not a file",
            question="workbook",
            fix="pass the path of a workbook in data/",
        )
    if path.resolve().parent != (home / "data").resolve():
        raise InterviewError(
            f"--workbook {option} is not in {home / 'data'}",
            question="workbook",
            fix="copy the workbook into data/ first; every hfk report reads it from there",
        )
    return path


def _print_instance(report: InstanceReport, args: argparse.Namespace) -> None:
    print(f"created {args.dir}")
    for path in report.created:
        relative = path.relative_to(report.home)
        suffix = "/" if path.is_dir() else ""
        print(f"  {relative}{suffix}")
    if report.git_initialised:
        print("git: initialised with pre-commit hook")


def _init_plain(args: argparse.Namespace) -> int:
    try:
        report = write_instance(Path(args.dir), git=args.git)
    except InstanceError as error:
        print(f"init: {error}", file=sys.stderr)
        return 1

    _print_instance(report, args)
    print("to read reports: double-click Open HFK.command (Mac, Linux) or Open HFK.bat (Windows)")
    print(
        f"next: put the Tiller workbook download in data/; it needs an {PLAN_SHEET} sheet "
        "for your budget plan (see the README in the new folder)"
    )
    print(f"then run: hfk plan check --home {args.dir} and hfk doctor --home {args.dir}")
    return 0


def _init_interview(
    args: argparse.Namespace, home: Path, workbook: Path, candidates: tuple[Path, ...]
) -> int:
    if args.answers is None and not sys.stdin.isatty():
        print(
            "init: no terminal attached for the interview: fix=pass --answers <file>",
            file=sys.stderr,
        )
        return 1
    try:
        if args.answers is not None:
            answers = load_answers(Path(args.answers))
            result = run_interview(workbook, answers=answers, ask=None)
        else:
            result = run_interview(workbook, answers=None, ask=_prompt)
    except (InterviewError, ConfigError, TillerFormatError) as error:
        print(f"init: {error}", file=sys.stderr)
        return 1

    try:
        report = write_instance(
            home, git=args.git, documents=result.documents, starter_plan=result.starter_plan
        )
    except InstanceError as error:
        print(f"init: {error}", file=sys.stderr)
        return 1

    _print_instance(report, args)
    for line in result.summary:
        print(line)
    others = [path.name for path in candidates if path.resolve() != workbook.resolve()]
    if others:
        reason = "chosen with --workbook" if args.workbook is not None else "the newest"
        print(
            f"note: data/ holds {len(candidates)} Tiller workbooks; read {workbook.name} "
            f"({reason}); not read: {', '.join(others)}; "
            "pass --workbook <path> to read another"
        )
    print(f"next: run hfk doctor --home {args.dir}")
    print("to read reports: double-click Open HFK.command (Mac, Linux) or Open HFK.bat (Windows)")
    print(
        f"then: add a sheet named {PLAN_SHEET} to your workbook, paste or import "
        f"{STARTER_CSV} into it starting at cell A1, set your targets, download the "
        f"workbook into data/ again, and run hfk plan check --home {args.dir}"
    )
    return 0


def _init(args: argparse.Namespace) -> int:
    home = Path(args.dir)
    candidates = _init_workbooks(home)
    workbook = candidates[0] if candidates else None
    if args.workbook is not None:
        try:
            workbook = _chosen_workbook(home, args.workbook)
        except InterviewError as error:
            print(f"init: {error}", file=sys.stderr)
            return 1
        if workbook.resolve() not in {path.resolve() for path in candidates}:
            candidates = (*candidates, workbook)
    if workbook is None and args.answers is not None:
        print(
            f"init: --answers given but no Tiller workbook found in {home / 'data'}: "
            "fix=put the workbook export in data/ first",
            file=sys.stderr,
        )
        return 1
    if workbook is None:
        return _init_plain(args)
    return _init_interview(args, home, workbook, candidates)


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
        "--format",
        choices=("text", "csv", "html"),
        default="text",
        help="Output format (default: text).",
    )
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
        "--format",
        choices=("text", "csv", "html"),
        default="text",
        help="Output format (default: text).",
    )
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
        "--format",
        choices=("text", "csv", "html"),
        default="text",
        help="Output format (default: text).",
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
        "--format",
        choices=("text", "csv", "html"),
        default="text",
        help="Output format (default: text).",
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
        "--format",
        choices=("text", "csv", "html"),
        default="text",
        help="Output format (default: text).",
    )
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

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Loopback address to bind (default: {DEFAULT_HOST}); anything else is refused.",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT}; 0 picks a free port).",
    )
    serve_parser.add_argument("--today", type=_parse_date, help="Date for reproducible pages.")
    serve_parser.add_argument(
        "--home",
        default=argparse.SUPPRESS,
        help="Instance directory (default: HFK_HOME or current directory).",
    )
    serve_parser.set_defaults(func=_serve)

    open_parser = subparsers.add_parser("open")
    open_parser.add_argument(
        "--no-browser",
        action="store_true",
        dest="no_browser",
        help="Print the address but do not open a browser.",
    )
    open_parser.add_argument("--today", type=_parse_date, help="Date for reproducible pages.")
    open_parser.add_argument(
        "--home",
        default=argparse.SUPPRESS,
        help="Instance directory (default: HFK_HOME or current directory).",
    )
    open_parser.set_defaults(func=_open)

    plan_parser = subparsers.add_parser("plan")
    plan_subparsers = plan_parser.add_subparsers(dest="plan_command", metavar="command")
    plan_check_parser = plan_subparsers.add_parser("check")
    plan_check_parser.add_argument(
        "--home",
        default=argparse.SUPPRESS,
        help="Instance directory (default: HFK_HOME or current directory).",
    )
    plan_check_parser.set_defaults(func=_plan_check)
    to_sheet_parser = plan_subparsers.add_parser("to-sheet")
    to_sheet_parser.add_argument(
        "--out",
        help=f"CSV file to write (default: {STARTER_CSV} in the instance).",
    )
    to_sheet_parser.add_argument(
        "--home",
        default=argparse.SUPPRESS,
        help="Instance directory (default: HFK_HOME or current directory).",
    )
    to_sheet_parser.set_defaults(func=_plan_to_sheet)
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
    init_parser.add_argument(
        "--answers",
        help="YAML file of interview answers; required when no terminal is attached.",
    )
    init_parser.add_argument(
        "--workbook",
        help="Workbook in data/ to interview from (default: the newest Tiller workbook there).",
    )
    init_parser.set_defaults(func=_init)

    extension_commands = _add_extension_commands(subparsers, load_extensions())
    for name in _STUB_MILESTONES:
        if name in extension_commands:
            continue
        subparser = subparsers.add_parser(name)
        subparser.set_defaults(func=lambda _args, command=name: _stub(command))

    dev_parser = subparsers.add_parser("dev")
    dev_subparsers = dev_parser.add_subparsers(dest="dev_command", metavar="command")
    fixture_parser = dev_subparsers.add_parser("fixture")
    fixture_parser.add_argument("--out", required=True, help="Output workbook path.")
    fixture_parser.add_argument("--months", type=int, default=6, help="Number of months.")
    fixture_parser.add_argument(
        "--plan-tab",
        action="store_true",
        dest="plan_tab",
        default=True,
        help="Write the example HFK Plan sheet (the default).",
    )
    fixture_parser.add_argument(
        "--no-plan-tab",
        action="store_false",
        dest="plan_tab",
        help="Leave out the HFK Plan sheet.",
    )
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
