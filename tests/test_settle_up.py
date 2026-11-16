"""The settle_up extension (M7; ADR-0004, ADR-0009)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from hfk.config import load_household
from hfk.ext import load_extensions
from hfk.source.fixture import build_fixture

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
PYTHONPATH = str(ROOT / "src")
TODAY = date(2026, 10, 1)


def make_instance(tmp_path: Path, *, people: list[dict] | None = None) -> Path:
    home = tmp_path / "instance"
    home.mkdir(parents=True)
    for filename in ("household.yaml", "declarations.yaml", "settle_up.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, home / filename)
    if people is not None:
        data = yaml.safe_load((home / "household.yaml").read_text(encoding="utf-8"))
        data["people"] = people
        slugs = [person["slug"] for person in people]
        weights = {1: [1], 2: [0.5, 0.5], 3: [0.5, 0.25, 0.25]}[len(slugs)]
        for account in data["accounts"].values():
            if "owner" in account and account["owner"] not in slugs:
                account["owner"] = slugs[0]
            if "shared" in account:
                account["shared"] = dict(zip(slugs, weights, strict=True))
        (home / "household.yaml").write_text(yaml.safe_dump(data, sort_keys=False), "utf-8")
        declarations = yaml.safe_load((home / "declarations.yaml").read_text(encoding="utf-8"))
        declarations["sharing"] = []
        (home / "declarations.yaml").write_text(
            yaml.safe_dump(declarations, sort_keys=False), "utf-8"
        )
    build_fixture(home / "data" / "Tiller-Example.xlsx")
    return home


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


def doctor(home: Path):
    # Imported here, not at module top: tests/test_ledger.py re-imports every hfk
    # module, and the entry point always loads the current one.
    from hfk.engine import run_doctor
    from hfk.ext import load_extensions
    from hfk.ext.doctor import extension_doctor_hooks

    return run_doctor(home, today=TODAY, hooks=extension_doctor_hooks(load_extensions()))


def test_settle_up_is_registered_through_its_entry_point():
    loaded = load_extensions()
    extension = loaded.get("settle_up")
    assert extension is not None, loaded.problems
    assert extension.entry_point == "settle_up"
    assert extension.config_section == "settle_up.yaml"
    assert [command.name for command in extension.commands] == ["settle"]
    assert "hfk.ext.settle_up" not in {
        name for name in sys.modules if name.startswith("hfk.cli")
    }


def test_example_instance_enables_settle_up_and_passes_doctor(tmp_path):
    home = make_instance(tmp_path)
    assert load_household(home).extensions == ("settle_up",)
    report = doctor(home)
    assert report.ok, [d.render() for d in report.errors()]


@pytest.mark.parametrize(
    ("people", "count"),
    [
        ([{"slug": "alex", "name": "Alex"}], 1),
        (
            [
                {"slug": "alex", "name": "Alex"},
                {"slug": "sam", "name": "Sam"},
                {"slug": "pat", "name": "Pat"},
            ],
            3,
        ),
    ],
)
def test_exactly_two_people_required(tmp_path, people, count):
    from hfk.ext.settle_up import SettleUpError, two_people

    home = make_instance(tmp_path, people=people)
    household = load_household(home)

    with pytest.raises(SettleUpError) as caught:
        two_people(household)
    assert f"exactly two people, but household.yaml lists {count}" in str(caught.value)
    assert "remove settle_up from extensions" in caught.value.fix

    report = doctor(home)
    errors = [d for d in report.errors() if d.code == "settle-up-people"]
    assert len(errors) == 1
    assert errors[0].where == "household.yaml key=people"

    result = run_hfk("doctor", "--home", str(home), "--today", "2026-10-01")
    assert result.returncode == 1
    assert "settle-up works between exactly two people" in result.stdout


def test_two_people_pass(tmp_path):
    from hfk.ext.settle_up import two_people

    household = load_household(make_instance(tmp_path))
    assert two_people(household) == ("alex", "sam")


def load(home: Path):
    from hfk.config import load_declarations, load_instance_plan
    from hfk.source import find_workbook, read_tiller

    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    plan = load_instance_plan(home, household=household, declarations=declarations)
    ledger = read_tiller(find_workbook(home / "data", household.tiller_glob))
    return household, declarations, plan, ledger


@pytest.mark.parametrize("month", ["2026-04", "2026-07", "2026-08", "2026-09"])
def test_on_ledger_shares_match_scorecard(tmp_path, month):
    from hfk.config import Month
    from hfk.engine import build_scorecard
    from hfk.ext.settle_up.shares import on_ledger_lines, owed_totals

    home = make_instance(tmp_path)
    household, declarations, plan, ledger = load(home)
    people = ("alex", "sam")

    lines = on_ledger_lines(
        ledger=ledger,
        household=household,
        declarations=declarations,
        month=Month.parse(month),
        people=people,
    )
    totals = owed_totals(lines, people)

    for who in people:
        scorecard = build_scorecard(
            ledger=ledger,
            household=household,
            declarations=declarations,
            plan=plan,
            month=Month.parse(month),
            who=who,
            today=TODAY,
        )
        assert totals[who] == scorecard.actual_total, (month, who)

    # The core sharing rule makes the utility bill paid from Alex's own account a
    # shared line in settle-up too: half each, exactly as the scorecard counts it.
    utilities = [line for line in lines if line.account == "Alex Checking"
                 and line.category == "Utilities"]
    assert utilities
    for line in utilities:
        assert line.shared
        assert line.owed_by("alex") + line.owed_by("sam") == line.amount
        assert abs(line.owed_by("alex") - line.owed_by("sam")) <= Decimal("0.01")


def test_settle_up_declares_no_sharing_rules_of_its_own():
    import ast

    source = (ROOT / "src" / "hfk" / "ext" / "settle_up").rglob("*.py")
    for path in source:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", None)
            for node in ast.walk(tree)
        }
        assert "share_weights" not in names, path
        assert "SharingRule" not in names, path
        assert "sharing" not in names, path


# M7-04: the statement. Hand-worked for 2026-08 with Alex paying the Joint Card:
# shared charges are Groceries 120 + 135 + 110 = 365.00 and Dining 45 + 60 = 105.00 on
# the Joint Card (Alex pays), plus Utilities 210.00 from Alex's own account, which a
# sharing rule splits half each. Alex paid 680.00; each owes 340.00; Sam pays Alex 340.00.


def statement_for(home: Path, month: str = "2026-08", today: date = TODAY):
    from hfk.config import Month, load_declarations
    from hfk.ext.settle_up.config import load_settle_up
    from hfk.ext.settle_up.items import load_shared_items
    from hfk.ext.settle_up.statement import build_statement
    from hfk.source import find_workbook, read_tiller

    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    path = home / "settle_up.yaml"
    config = load_settle_up(yaml.safe_load(path.read_text(encoding="utf-8")), path)
    items = load_shared_items(home, Month.parse(month), household=household,
                              declarations=declarations)
    return build_statement(
        ledger=read_tiller(find_workbook(home / "data", household.tiller_glob)),
        household=household,
        declarations=declarations,
        config=config,
        items=items,
        month=Month.parse(month),
        today=today,
    )


def test_statement_paid_owed_and_transfer(tmp_path):
    statement = statement_for(make_instance(tmp_path))

    assert statement.people == ("alex", "sam")
    assert statement.categories == (
        ("Groceries", Decimal("365.00")),
        ("Dining", Decimal("105.00")),
        ("Utilities", Decimal("210.00")),
    )
    assert statement.total == Decimal("680.00")
    assert statement.paid == (Decimal("680.00"), Decimal("0.00"))
    assert statement.owed == (Decimal("340.00"), Decimal("340.00"))
    assert statement.net == (Decimal("340.00"), Decimal("-340.00"))
    assert (statement.transfer.payer, statement.transfer.payee, statement.transfer.amount) == (
        "sam", "alex", Decimal("340.00"))
    assert all(line.paid[0] + line.paid[1] == line.amount for line in statement.lines)


def test_statement_includes_shared_items_and_payer_weights(tmp_path):
    home = make_instance(tmp_path)
    (home / "shared-items").mkdir()
    (home / "shared-items" / "2026-08.yaml").write_text(yaml.safe_dump({
        "schema_version": 1,
        "items": [{"label": "Example utility bill", "amount": 120, "paid_by": "sam",
                   "weights": {"alex": 0.5, "sam": 0.5}, "bucket": "Fixed Essential"}],
    }), encoding="utf-8")
    # Sam pays 120 and owes 60 of it; Alex owes 60 more: Sam now pays Alex 280.00.
    statement = statement_for(home)
    assert statement.paid == (Decimal("680.00"), Decimal("120.00"))
    assert statement.owed == (Decimal("400.00"), Decimal("400.00"))
    assert statement.transfer.amount == Decimal("280.00")
    assert statement.items_found

    # The card funded half each: only the sharing rule and the item move money.
    (home / "settle_up.yaml").write_text(
        "schema_version: 1\npayers:\n  Joint Card: {alex: 0.5, sam: 0.5}\n", encoding="utf-8")
    even = statement_for(home)
    # Alex paid 235 + 210 = 445 and owes 400; Sam paid 235 + 120 = 355 and owes 400.
    assert even.paid == (Decimal("445.00"), Decimal("355.00"))
    assert (even.transfer.payer, even.transfer.amount) == ("sam", Decimal("45.00"))


def test_missing_payer_fails_loudly_naming_the_account(tmp_path):
    from hfk.ext.settle_up import SettleUpError

    home = make_instance(tmp_path)
    (home / "settle_up.yaml").write_text("schema_version: 1\npayers: {}\n", encoding="utf-8")
    with pytest.raises(SettleUpError) as caught:
        statement_for(home)
    assert "no payer is declared for the shared account 'Joint Card'" in caught.value.problem
    assert "settle_up.yaml" in caught.value.fix


@pytest.mark.parametrize(
    ("payers", "key", "problem"),
    [
        ({"Joint Card": {"alex": 0.6, "sam": 0.6}}, 'payers."Joint Card"', "sum to 1.2"),
        ({"Joint Card": {"alex": "all"}}, 'payers."Joint Card".alex', "Invalid weight"),
        ({"Joint Card": {}}, 'payers."Joint Card"', "payer weights are empty"),
        ({"Old Card": {"alex": 1.0}}, 'payers."Old Card"', "Unknown account"),
        ({"Alex Checking": {"alex": 1.0}}, 'payers."Alex Checking"', "has a single owner"),
        ({"Joint Card": {"pat": 1.0}}, 'payers."Joint Card".pat', "Unknown person slug"),
    ],
)
def test_payer_config_is_validated(tmp_path, payers, key, problem):
    from hfk.config import ConfigError
    from hfk.ext.settle_up.config import check_payers, load_settle_up

    path = tmp_path / "settle_up.yaml"
    with pytest.raises(ConfigError) as caught:
        config = load_settle_up({"schema_version": 1, "payers": payers}, path)
        check_payers(config, load_household(INSTANCE_EXAMPLE))
    assert caught.value.key == key
    assert problem in caught.value.problem


def test_settle_command_prints_the_statement(tmp_path):
    home = make_instance(tmp_path)
    args = ("settle", "--home", str(home), "--today", "2026-10-01", "2026-08")

    text = run_hfk(*args)
    assert text.returncode == 0, text.stderr
    assert text.stdout.splitlines()[0].startswith("settle-up 2026-08 for alex and sam")
    assert text.stdout.rstrip().endswith("transfer: sam pays alex 340.00")
    csv_out = run_hfk(*args, "--format", "csv")
    assert csv_out.stdout.splitlines()[0] == (
        "source,date,description,account,category,amount,alex paid,sam paid,alex owes,sam owes")
    assert len(csv_out.stdout.splitlines()) == 1 + 6
    html_out = run_hfk(*args, "--format", "html")
    assert "<strong>transfer: sam pays alex 340.00</strong>" in html_out.stdout


@pytest.mark.parametrize(
    ("month", "today"),
    [
        ("2026-09", date(2026, 9, 15)),   # the current month
        ("2026-09", date(2026, 9, 30)),   # its last day has not ended yet
        ("2026-12", date(2026, 9, 15)),   # a future month
    ],
)
def test_unfinished_month_never_settles(tmp_path, monkeypatch, month, today):
    from hfk.ext.settle_up import SettleUpError

    home = make_instance(tmp_path)
    with pytest.raises(SettleUpError) as caught:
        statement_for(home, month, today)
    assert f"month {month} has not ended (today is {today.isoformat()})" in caught.value.problem
    assert "never settles an unfinished month" in caught.value.fix

    result = run_hfk("settle", "--home", str(home), "--today", today.isoformat(), month)
    assert result.returncode == 1
    assert result.stdout == ""  # no statement and no transfer is printed
    assert "has not ended" in result.stderr

    # The refusal comes before the workbook is read: no ledger is ever loaded.
    from hfk.ext.settle_up import statement as module

    def no_lines(**_kwargs):
        raise AssertionError("an unfinished month reached the ledger")

    monkeypatch.setattr(module, "on_ledger_lines", no_lines)
    with pytest.raises(SettleUpError):
        statement_for(home, month, today)


def test_a_month_settles_the_day_after_it_ends(tmp_path):
    statement = statement_for(make_instance(tmp_path), "2026-09", date(2026, 10, 1))
    assert statement.month.month == 9


def test_settle_outputs_without_tiller_writes(tmp_path, monkeypatch):
    import hashlib

    import openpyxl

    from hfk.ext.settle_up.render import render_csv, render_html, render_paste, render_text

    home = make_instance(tmp_path)
    workbook = home / "data" / "Tiller-Example.xlsx"
    before = hashlib.sha256(workbook.read_bytes()).hexdigest()

    def refuse(*_args, **_kwargs):
        raise AssertionError("settle-up saved a workbook")

    opened: list[dict] = []
    real_load = openpyxl.load_workbook

    def spy(*args, **kwargs):
        opened.append(kwargs)
        return real_load(*args, **kwargs)

    monkeypatch.setattr(openpyxl.Workbook, "save", refuse)
    monkeypatch.setattr(openpyxl, "load_workbook", spy)

    statement = statement_for(home)
    for render in (render_text, render_csv, render_html, render_paste):
        render(statement)
    assert opened and all(k.get("read_only") is True and k.get("data_only") is True
                          for k in opened)

    paste = render_paste(statement)
    rows = [line.split("\t") for line in paste.splitlines()]
    assert rows[0] == ["settle-up", "2026-08"]
    assert rows[1] == ["category", "total"]
    assert rows[2:5] == [[name, f"{total:.2f}"] for name, total in statement.categories]
    assert ["total", f"{statement.total:.2f}"] in rows
    assert ["alex", "680.00", "340.00", "340.00"] in rows
    assert ["sam", "0.00", "340.00", "-340.00"] in rows
    assert rows[-1] == ["transfer", "sam", "alex", "340.00"]

    for fmt in ("text", "csv", "html", "paste"):
        result = run_hfk("settle", "--home", str(home), "--today", "2026-10-01", "2026-08",
                         "--format", fmt)
        assert result.returncode == 0, result.stderr
    assert run_hfk("settle", "--home", str(home), "--today", "2026-10-01", "2026-08",
                   "--format", "paste").stdout == paste
    assert hashlib.sha256(workbook.read_bytes()).hexdigest() == before
    assert sorted(path.name for path in (home / "data").iterdir()) == ["Tiller-Example.xlsx"]
