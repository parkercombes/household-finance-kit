"""Settle-up against a hand-built statement, to the cent (M7-06)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
EXPECTED = ROOT / "tests" / "fixtures" / "settle-2026-08-expected.yaml"


def make_instance(tmp_path: Path) -> Path:
    from hfk.source.fixture import build_fixture

    home = tmp_path / "instance"
    home.mkdir()
    for filename in ("household.yaml", "declarations.yaml", "settle_up.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, home / filename)
    build_fixture(home / "data" / "Tiller-Example.xlsx")
    return home


def statement(home: Path):
    from hfk.config import Month, load_declarations, load_household
    from hfk.ext.settle_up.config import load_settle_up
    from hfk.ext.settle_up.items import load_shared_items
    from hfk.ext.settle_up.statement import build_statement
    from hfk.source import find_workbook, read_tiller

    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    path = home / "settle_up.yaml"
    month = Month(2026, 8)
    return build_statement(
        ledger=read_tiller(find_workbook(home / "data", household.tiller_glob)),
        household=household,
        declarations=declarations,
        config=load_settle_up(yaml.safe_load(path.read_text(encoding="utf-8")), path),
        items=load_shared_items(home, month, household=household, declarations=declarations),
        month=month,
        today=date(2026, 10, 1),
    )


def write_expected(tmp_path: Path, change) -> Path:
    data = yaml.safe_load(EXPECTED.read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / "expected.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_fixture_statement_matches_the_hand_built_statement(tmp_path):
    from hfk.ext.settle_up.regression import compare, load_expected

    assert compare(statement(make_instance(tmp_path)), load_expected(EXPECTED)) == []


@pytest.mark.parametrize(
    ("change", "differences"),
    [
        (lambda d: d["paid"].update(alex=680.01), []),  # one cent is within tolerance
        (lambda d: d["paid"].update(alex=680.02),
         ["paid.alex: expected 680.02, statement has 680.00"]),
        (lambda d: d["categories"].update(Dining=100.00),
         ["categories.Dining: expected 100.00, statement has 105.00"]),
        (lambda d: d["categories"].pop("Utilities"),
         ["categories.Utilities: expected 0.00, statement has 210.00"]),
        (lambda d: d["transfer"].update({"from": "alex", "to": "sam"}),
         ["transfer.direction: expected alex pays sam, statement has sam pays alex"]),
        (lambda d: d["transfer"].update(amount=300),
         ["transfer.amount: expected 300.00, statement has 340.00"]),
    ],
)
def test_differences_are_named_to_the_cent(tmp_path, change, differences):
    from hfk.ext.settle_up.regression import compare, load_expected

    found = compare(statement(make_instance(tmp_path)), load_expected(write_expected(tmp_path, change)))
    assert [difference.render() for difference in found] == differences


def test_settle_compare_on_the_command_line(tmp_path):
    home = make_instance(tmp_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")

    def settle(expected: Path):
        return subprocess.run(
            [sys.executable, "-m", "hfk", "settle", "--home", str(home), "--today", "2026-10-01",
             "2026-08", "--compare", str(expected)],
            env=env, text=True, capture_output=True, check=False,
        )

    good = settle(EXPECTED)
    assert good.returncode == 0, good.stderr
    assert f"compare: matches {EXPECTED} to the cent" in good.stderr

    bad = settle(write_expected(tmp_path, lambda d: d["owes"].update(sam=300)))
    assert bad.returncode == 1
    assert "compare: owes.sam: expected 300.00, statement has 340.00" in bad.stderr
    assert "compare: 1 differences from" in bad.stderr
