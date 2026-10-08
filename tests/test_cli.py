from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHONPATH = str(ROOT / "src")
STUBS = {
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
