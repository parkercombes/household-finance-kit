"""`hfk init` interview (M5-06): instance YAML proposed from a Tiller workbook.

The interview opens the newest workbook in `data/` read-only, proposes
accounts from `Balance History` and group-to-bucket mappings from the
`Categories` sheet, and writes `household.yaml`, `declarations.yaml`, and a
starter `plan.yaml` with a comment per judgement call. Answers here come from
`--answers <file>`; the prompt path is exercised in-process through a
scripted `ask` callback. Plain `hfk init` without a workbook in `data/` must
stay byte-identical to the M5-01 behaviour.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from hfk.config import Month, load_declarations, load_household, load_plan
from hfk.instance import write_instance
from hfk.interview import Question, propose_from_ledger, run_interview
from hfk.ledger import BalanceRow, Category, Ledger, Transaction
from hfk.source.fixture import build_fixture

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
PYTHONPATH = str(ROOT / "src")

FIXTURE_ACCOUNTS = ("Alex Checking", "Sam Checking", "Joint Card", "Savings")
FIXTURE_EXPENSE_CATEGORIES = (
    "Rent",
    "Utilities",
    "Groceries",
    "Dining",
    "Fuel",
    "Transit",
    "Annual Membership",
)


def run_hfk(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = PYTHONPATH
    if env is not None:
        environment.update(env)
    return subprocess.run(
        [sys.executable, "-m", "hfk", *args],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def make_home(tmp_path: Path, name: str = "finances") -> Path:
    home = tmp_path / name
    (home / "data").mkdir(parents=True)
    build_fixture(home / "data" / "Tiller-Example.xlsx")
    return home


def four_bucket_answers() -> dict[str, Any]:
    return {
        "people": [
            {"slug": "alex", "name": "Alex"},
            {"slug": "sam", "name": "Sam"},
        ],
        "accounts": {
            "Alex Checking": {"owner": "alex"},
            "Sam Checking": {"owner": "sam"},
            "Joint Card": {"shared": {"alex": 0.5, "sam": 0.5}},
            "Savings": {"owner": "alex"},
        },
        "profile": "four-bucket",
        "groups": {
            "Housing": "Fixed Essential",
            "Food": "Variable Essential",
            "Transportation": "Variable Essential",
            "Subscriptions": "Fixed Discretionary",
        },
        "history_start": date(2026, 4, 1),
    }


def write_answers(tmp_path: Path, answers: dict[str, Any]) -> Path:
    path = tmp_path / "answers.yaml"
    path.write_text(yaml.safe_dump(answers, sort_keys=False), encoding="utf-8")
    return path


def init_with_answers(
    tmp_path: Path, answers: dict[str, Any], name: str = "finances"
) -> subprocess.CompletedProcess[str]:
    home = make_home(tmp_path, name)
    answers_path = write_answers(tmp_path, answers)
    return run_hfk("init", str(home), "--answers", str(answers_path))


def prompt_replies() -> dict[str, str]:
    return {
        "people": "alex=Alex, sam=Sam",
        "account:Alex Checking": "",
        "account:Joint Card": "alex=0.5, sam=0.5",
        "account:Sam Checking": "",
        "account:Savings": "alex",
        "profile": "four-bucket",
        "group:Housing": "Fixed Essential",
        "group:Food": "Variable Essential",
        "group:Transportation": "Variable Essential",
        "group:Subscriptions": "Fixed Discretionary",
        "history_start": "",
    }


class ScriptedAsk:
    """Records every question in order and plays back scripted answers."""

    def __init__(self, replies: dict[str, str]) -> None:
        self.replies = replies
        self.asked: list[Question] = []

    def __call__(self, question: Question) -> str:
        self.asked.append(question)
        return self.replies[question.key]


def test_interview_writes_household_naming_every_fixture_account(tmp_path: Path) -> None:
    result = init_with_answers(tmp_path, four_bucket_answers())

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    household = load_household(tmp_path / "finances")
    assert [person.slug for person in household.people] == ["alex", "sam"]
    assert [person.name for person in household.people] == ["Alex", "Sam"]
    assert household.history_start == date(2026, 4, 1)
    assert household.tiller_glob == "Tiller*.xls*"
    assert household.extensions == ()

    accounts = {account.name: account for account in household.accounts}
    assert set(accounts) == set(FIXTURE_ACCOUNTS)
    assert accounts["Alex Checking"].owner == "alex"
    assert accounts["Sam Checking"].owner == "sam"
    assert accounts["Savings"].owner == "alex"
    assert accounts["Joint Card"].weights == (("alex", Decimal("0.5")), ("sam", Decimal("0.5")))
    assert accounts["Alex Checking"].kind == "checking"
    assert accounts["Sam Checking"].kind == "checking"
    assert accounts["Joint Card"].kind == "credit"
    assert accounts["Savings"].kind == "savings"


def test_interview_maps_every_fixture_expense_group(tmp_path: Path) -> None:
    result = init_with_answers(tmp_path, four_bucket_answers())

    assert result.returncode == 0, result.stderr
    declarations = load_declarations(tmp_path / "finances", people=("alex", "sam"))
    assert declarations.profile == "four-bucket"
    assert declarations.mapping_source == "tiller_group"
    assert declarations.bucket_names() == (
        "Fixed Essential",
        "Variable Essential",
        "Fixed Discretionary",
        "Variable Discretionary",
    )
    assert dict(declarations.groups) == {
        "Housing": "Fixed Essential",
        "Food": "Variable Essential",
        "Transportation": "Variable Essential",
        "Subscriptions": "Fixed Discretionary",
    }
    assert declarations.non_spend_groups == ("Income", "Transfers")
    assert declarations.closed_accounts == ()


def test_interview_instance_passes_doctor_and_plan_check(tmp_path: Path) -> None:
    result = init_with_answers(tmp_path, four_bucket_answers())
    home = tmp_path / "finances"

    assert result.returncode == 0, result.stderr

    doctor = run_hfk("doctor", "--home", str(home), "--today", "2026-10-01")
    assert doctor.returncode == 0, doctor.stdout
    assert "doctor: 0 errors" in doctor.stdout

    check = run_hfk("plan", "check", "--home", str(home))
    assert check.returncode == 0, check.stdout

    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    plan = load_plan(home, declarations=declarations, people=household.slugs)
    assert plan.effective_from == Month(2026, 4)
    assert len(plan.lines) == 4
    categories = [name for line in plan.lines for name in line.categories]
    assert categories == list(FIXTURE_EXPENSE_CATEGORIES)


def test_missing_required_answer_fails_naming_the_question(tmp_path: Path) -> None:
    without_food = four_bucket_answers()
    del without_food["groups"]["Food"]
    without_profile = four_bucket_answers()
    del without_profile["profile"]
    without_joint_card = four_bucket_answers()
    del without_joint_card["accounts"]["Joint Card"]
    cases = (
        ("Food", without_food, "missing-food"),
        ("profile", without_profile, "missing-profile"),
        ("Joint Card", without_joint_card, "missing-joint-card"),
    )

    for expected, answers, name in cases:
        result = init_with_answers(tmp_path, answers, name=name)
        home = tmp_path / name

        assert result.returncode == 1, result.stderr
        assert expected in result.stderr
        for filename in ("household.yaml", "declarations.yaml", "plan.yaml"):
            assert not (home / filename).exists(), filename


def test_unknown_answer_key_and_unknown_account_fail_loudly(tmp_path: Path) -> None:
    with_colour = four_bucket_answers()
    with_colour["colour"] = "blue"
    result = init_with_answers(tmp_path, with_colour, name="colour-home")

    assert result.returncode == 1
    assert "colour" in result.stderr

    with_ghost = four_bucket_answers()
    with_ghost["accounts"]["Ghost Card"] = {"owner": "alex"}
    result = init_with_answers(tmp_path, with_ghost, name="ghost-home")

    assert result.returncode == 1
    assert "Ghost Card" in result.stderr
    assert not (tmp_path / "ghost-home" / "household.yaml").exists()


def test_bucket_outside_profile_fails_naming_the_profile_buckets(tmp_path: Path) -> None:
    needs = four_bucket_answers()
    needs["groups"]["Housing"] = "Needs"
    result = init_with_answers(tmp_path, needs, name="needs-home")

    assert result.returncode == 1
    assert "Needs" in result.stderr
    assert "Fixed Essential" in result.stderr

    fancy = four_bucket_answers()
    fancy["profile"] = "fancy"
    result = init_with_answers(tmp_path, fancy, name="fancy-home")

    assert result.returncode == 1
    assert "fancy" in result.stderr
    assert "four-bucket" in result.stderr


def test_plain_init_without_workbook_is_unchanged(tmp_path: Path) -> None:
    home = tmp_path / "finances"

    result = run_hfk("init", str(home))

    assert result.returncode == 0, result.stderr
    for name in ("household.yaml", "declarations.yaml", "plan.yaml"):
        assert load_yaml(home / name) == load_yaml(INSTANCE_EXAMPLE / name), name
    lines = result.stdout.splitlines()
    assert lines[-2] == "next: put the Tiller workbook export in data/"
    assert lines[-1] == f"then run: hfk plan check --home {home} and hfk doctor --home {home}"


def test_answers_without_workbook_fails(tmp_path: Path) -> None:
    home = tmp_path / "finances"
    answers = write_answers(tmp_path, four_bucket_answers())

    result = run_hfk("init", str(home), "--answers", str(answers))

    assert result.returncode == 1
    assert "workbook" in result.stderr
    assert not home.exists() or not any(home.iterdir())


def test_no_terminal_and_no_answers_fails_pointing_at_answers(tmp_path: Path) -> None:
    home = make_home(tmp_path)

    result = run_hfk("init", str(home))

    assert result.returncode == 1
    assert "--answers" in result.stderr
    for filename in ("household.yaml", "declarations.yaml", "plan.yaml"):
        assert not (home / filename).exists(), filename


def test_prompt_mode_accepts_scripted_answers_and_defaults(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    workbook = home / "data" / "Tiller-Example.xlsx"
    scripted = ScriptedAsk(prompt_replies())

    result = run_interview(workbook, answers=None, ask=scripted)

    assert [question.key for question in scripted.asked] == [
        "people",
        "account:Alex Checking",
        "account:Joint Card",
        "account:Sam Checking",
        "account:Savings",
        "profile",
        "group:Housing",
        "group:Food",
        "group:Transportation",
        "group:Subscriptions",
        "history_start",
    ]
    by_key = {question.key: question for question in scripted.asked}
    assert by_key["account:Alex Checking"].default == "alex"
    assert by_key["account:Savings"].default is None

    instance = tmp_path / "interviewed"
    write_instance(instance, documents=result.documents)
    household = load_household(instance)
    declarations = load_declarations(instance, people=household.slugs)
    load_plan(instance, declarations=declarations, people=household.slugs)
    assert household.history_start == date(2026, 4, 2)


def test_single_person_household_asks_no_account_questions(tmp_path: Path) -> None:
    answers: dict[str, Any] = {
        "people": [{"slug": "pat", "name": "Pat"}],
        "profile": "simple",
        "groups": {
            "Housing": "Essential",
            "Food": "Essential",
            "Transportation": "Essential",
            "Subscriptions": "Discretionary",
        },
        "history_start": date(2026, 4, 1),
    }
    result = init_with_answers(tmp_path, answers, name="pat-home")

    assert result.returncode == 0, result.stderr
    household = load_household(tmp_path / "pat-home")
    accounts = {account.name: account for account in household.accounts}
    assert set(accounts) == set(FIXTURE_ACCOUNTS)
    assert all(account.owner == "pat" for account in accounts.values())

    scripted = ScriptedAsk(
        {
            "people": "pat=Pat",
            "profile": "simple",
            "group:Housing": "Essential",
            "group:Food": "Essential",
            "group:Transportation": "Essential",
            "group:Subscriptions": "Discretionary",
            "history_start": "",
        }
    )
    run_interview(
        tmp_path / "pat-home" / "data" / "Tiller-Example.xlsx", answers=None, ask=scripted
    )
    assert not any(question.key.startswith("account:") for question in scripted.asked)


def closed_ledger() -> Ledger:
    categories = (
        Category("Rent", "Housing", "Expense"),
        Category("Utilities", "Housing", "Expense"),
        Category("Groceries", "Food", "Expense"),
        Category("Dining", "Food", "Expense"),
        Category("Fuel", "Transportation", "Expense"),
        Category("Transit", "Transportation", "Expense"),
        Category("Annual Membership", "Subscriptions", "Expense"),
        Category("Alex Paycheck", "Income", "Income"),
        Category("Sam Paycheck", "Income", "Income"),
        Category("Savings Transfer", "Transfers", "Transfer"),
    )
    transactions = (
        Transaction(
            date=date(2026, 4, 2),
            description="Alex Paycheck",
            category="Alex Paycheck",
            amount=Decimal("3200.00"),
            account="Alex Checking",
        ),
    )
    balances = []
    open_rows = (
        ("Alex Checking", "Checking", "Asset"),
        ("Sam Checking", "Checking", "Asset"),
        ("Joint Card", "Credit", "Liability"),
        ("Savings", "Savings", "Asset"),
    )
    for month in (4, 5):
        for name, account_type, account_class in open_rows:
            balances.append(
                BalanceRow(
                    date=date(2026, month, 28),
                    account=name,
                    balance=Decimal("100.00"),
                    account_type=account_type,
                    account_class=account_class,
                    account_status="Open",
                )
            )
    balances.append(
        BalanceRow(
            date=date(2026, 2, 28),
            account="Old Card",
            balance=Decimal("-40.00"),
            account_type="Credit",
            account_class="Liability",
            account_status="Closed",
        )
    )
    balances.append(
        BalanceRow(
            date=date(2026, 3, 28),
            account="Old Card",
            balance=Decimal("-20.00"),
            account_type="Credit",
            account_class="Liability",
            account_status="Closed",
        )
    )
    return Ledger(
        transactions=transactions,
        categories=categories,
        balances=tuple(balances),
    )


def test_closed_accounts_are_declared_closed_not_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = closed_ledger()
    proposal = propose_from_ledger(ledger, tmp_path / "Tiller-Example.xlsx")

    assert [facts.name for facts in proposal.accounts] == [
        "Alex Checking",
        "Joint Card",
        "Sam Checking",
        "Savings",
    ]
    assert [facts.name for facts in proposal.closed_accounts] == ["Old Card"]
    assert proposal.closed_accounts[0].last_balance == date(2026, 3, 28)

    monkeypatch.setattr("hfk.interview.read_tiller", lambda _path: ledger)
    scripted = ScriptedAsk(prompt_replies())
    result = run_interview(
        tmp_path / "Tiller-Example.xlsx", answers=None, ask=scripted
    )

    assert all(question.key != "account:Old Card" for question in scripted.asked)
    text = result.documents["declarations.yaml"]
    assert "closed_accounts:" in text
    assert "Old Card" in text
    assert "2026-03-28" in text


def test_workbook_is_never_modified(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    workbook = home / "data" / "Tiller-Example.xlsx"
    before_hash = hashlib.sha256(workbook.read_bytes()).hexdigest()
    before_mtime = workbook.stat().st_mtime_ns
    answers = write_answers(tmp_path, four_bucket_answers())

    result = run_hfk("init", str(home), "--answers", str(answers))

    assert result.returncode == 0, result.stderr
    assert hashlib.sha256(workbook.read_bytes()).hexdigest() == before_hash
    assert workbook.stat().st_mtime_ns == before_mtime


def test_simple_profile_writes_a_plan_that_loads(tmp_path: Path) -> None:
    answers = four_bucket_answers()
    answers["profile"] = "simple"
    answers["groups"] = {
        "Housing": "Essential",
        "Food": "Essential",
        "Transportation": "Essential",
        "Subscriptions": "Discretionary",
    }
    result = init_with_answers(tmp_path, answers, name="simple-home")
    home = tmp_path / "simple-home"

    assert result.returncode == 0, result.stderr

    doctor = run_hfk("doctor", "--home", str(home), "--today", "2026-10-01")
    assert doctor.returncode == 0, doctor.stdout
    assert "doctor: 0 errors" in doctor.stdout

    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    plan = load_plan(home, declarations=declarations, people=household.slugs)
    assert plan.lines
    assert all(line.bucket in {"Essential", "Discretionary"} for line in plan.lines)


def test_yaml_carries_a_comment_per_judgement_call(tmp_path: Path) -> None:
    result = init_with_answers(tmp_path, four_bucket_answers(), name="commented-home")
    home = tmp_path / "commented-home"

    assert result.returncode == 0, result.stderr

    def comments(text: str) -> list[str]:
        return [line for line in text.splitlines() if line.lstrip().startswith("#")]

    household_text = (home / "household.yaml").read_text(encoding="utf-8")
    declarations_text = (home / "declarations.yaml").read_text(encoding="utf-8")
    plan_text = (home / "plan.yaml").read_text(encoding="utf-8")

    for text in (household_text, declarations_text, plan_text):
        assert len(comments(text)) >= 3
        assert "hfk init" in text
    assert any("Balance History" in line for line in comments(household_text))
    assert any("Categories" in line for line in comments(declarations_text))
    assert any("plan check" in line for line in comments(plan_text))
