"""Command line interface for hfk.

Only M0 foundation commands are implemented today. Analysis commands are stubs
until their roadmap milestones are built.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from hfk import __version__
from hfk.source.fixture import build_fixture

_STUB_MILESTONES = {
    "doctor": "M2",
    "scorecard": "M3",
    "categories": "M4",
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


def _dev_fixture(args: argparse.Namespace) -> int:
    output = build_fixture(args.out, months=args.months)
    print(output)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hfk")
    parser.add_argument(
        "--home",
        default=os.environ.get("HFK_HOME", "."),
        help="Instance directory; accepted by M0 stubs but not read yet.",
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit.")

    subparsers = parser.add_subparsers(dest="command", metavar="command")
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
