from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHONPATH = str(ROOT / "src")
# `settle` (M7-04) and `retirement` (M8-05) are real commands from their extensions.
STUBS: dict[str, str] = {
}


def run_hfk(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH
    return subprocess.run(
        [sys.executable, "-m", "hfk", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_version_output() -> None:
    result = run_hfk("--version")

    assert result.returncode == 0
    assert result.stdout.strip() == "hfk 0.1.0.dev0"
    assert result.stderr == ""


def test_no_arg_prints_help() -> None:
    result = run_hfk()

    assert result.returncode == 0
    assert "usage: hfk" in result.stdout


def test_every_stub_returns_two_and_mentions_milestone() -> None:
    for name, milestone in STUBS.items():
        result = run_hfk("--home", ".", name)

        assert result.returncode == 2
        assert result.stdout == ""
        assert f"hfk {name}: not implemented yet" in result.stderr
        assert f"milestone {milestone}" in result.stderr


def test_dev_without_subcommand_prints_help_to_stderr() -> None:
    result = run_hfk("dev")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "usage: hfk dev" in result.stderr


def test_plan_without_subcommand_prints_help_to_stderr() -> None:
    result = run_hfk("plan")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "usage: hfk plan" in result.stderr


def _subcommand_help(parser):
    """Each subcommand name mapped to its help line, for every subparser group."""

    import argparse

    found = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            listed = {choice.dest: choice.help for choice in action._choices_actions}
            for name, subparser in action.choices.items():
                found[name] = listed.get(name)
                for child, text in _subcommand_help(subparser).items():
                    found[f"{name} {child}"] = text
    return found


def test_every_command_is_listed_in_help() -> None:
    from hfk.cli import _build_parser

    commands = _subcommand_help(_build_parser())
    assert {"doctor", "scorecard", "plan check", "dev fixture", "settle"} <= set(commands)
    missing = sorted(name for name, text in commands.items() if not text)
    assert missing == [], f"commands without help text: {missing}"

    listing = run_hfk("--help").stdout
    for name in commands:
        if " " not in name:
            assert f"    {name} " in listing, name
