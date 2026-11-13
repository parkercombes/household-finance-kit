"""`hfk plan check` (M4-06, M5-18): every HFK Plan sheet problem, with row, column, and fix.

Since ADR-0015 the plan lives only in the workbook's `HFK Plan` sheet, so these
tests edit the plan as a `plan.yaml`-shaped mapping and write it into the
fixture workbook's sheet (`plan_fixture.write_plan`). Sheet row N holds plan
line N - 2.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from plan_fixture import example_plan, write_plan

from hfk.config import (
    ConfigError,
    PlanCheckReport,
    check_instance_plan,
    load_declarations,
    load_household,
    load_instance_plan,
)

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
PYTHONPATH = str(ROOT / "src")
FIX_UNKNOWN_BUCKET = (
    "use one of ['Fixed Essential', 'Variable Essential', 'Fixed Discretionary', "
    "'Variable Discretionary']"
)


def make_instance(home: Path, plan: dict[str, Any] | None = None) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    for filename in ("household.yaml", "declarations.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, home / filename)
    write_plan(home, example_plan() if plan is None else plan)
    return home


def edited(*changes: tuple[int, dict[str, Any] | None]) -> dict[str, Any]:
    """The example plan with line ``index`` updated by ``fields`` (or appended when new)."""

    plan = example_plan()
    lines = plan["plan"]["lines"]
    for index, fields in changes:
        if index == len(lines):
            lines.append(dict(fields or {}))
            continue
        for key, value in (fields or {}).items():
            if value is None:
                lines[index].pop(key, None)
            else:
                lines[index][key] = value
    return plan


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


def check(home: Path) -> PlanCheckReport:
    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    return check_instance_plan(home, household=household, declarations=declarations)


def test_plan_check_cli_passes_on_example_instance(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    result = run_hfk("plan", "check", "--home", str(home))

    assert result.returncode == 0, result.stdout
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        f"plan check {home / 'data' / 'Tiller-Example.xlsx'} (sheet HFK Plan)",
        "ok: 9 lines",
    ]


def test_unknown_bucket_names_row_column_and_fix(tmp_path: Path) -> None:
    home = make_instance(tmp_path, edited((1, {"bucket": "Nope"})))

    result = run_hfk("plan", "check", "--home", str(home))

    assert result.returncode == 1
    assert result.stdout.splitlines()[1:] == [
        f"  sheet HFK Plan  row 3  column Bucket  Unknown bucket 'Nope'; fix: {FIX_UNKNOWN_BUCKET}",
        "1 problem",
    ]


def test_every_problem_is_reported_at_once(tmp_path: Path) -> None:
    home = make_instance(
        tmp_path,
        edited(
            (1, {"bucket": "Nope"}),
            (5, {"who": "pat"}),
            (7, {"monthly": 11.00}),
        ),
    )

    report = check(home)

    assert [(problem.line, problem.column) for problem in report.problems] == [
        (3, "Bucket"),
        (7, "Who"),
        (9, "Monthly"),
    ]
    assert report.line_count == 9
    result = run_hfk("plan", "check", "--home", str(home))
    assert result.returncode == 1
    assert result.stdout.splitlines()[-1] == "3 problems"


def test_duplicate_category_overlap_is_reported_on_the_later_row(tmp_path: Path) -> None:
    home = make_instance(tmp_path, edited((3, {"effective_until": "2025-08"})))

    report = check(home)

    assert len(report.problems) == 1
    problem = report.problems[0]
    assert (problem.line, problem.column) == (6, "Categories")
    assert problem.problem == (
        'category "Groceries" for "alex" is also on HFK Plan row 5 ("Example Grocer") '
        "with first overlapping month 2025-07"
    )
    assert problem.fix == (
        "end one line with Effective Until before the other starts, "
        "or remove the category from one of them"
    )


def test_non_overlapping_rows_are_fine(tmp_path: Path) -> None:
    report = check(make_instance(tmp_path))

    assert report.ok
    assert report.line_count == 9


def test_override_bucket_mismatch_is_reported(tmp_path: Path) -> None:
    home = make_instance(tmp_path, edited((8, {"bucket": "Variable Essential"})))

    report = check(home)

    assert len(report.problems) == 1
    problem = report.problems[0]
    assert (problem.line, problem.column) == (10, "Categories")
    assert problem.problem == (
        'category "Dining" maps to bucket "Variable Discretionary" in declarations.yaml '
        'but this line is bucket "Variable Essential"'
    )


def test_split_bucket_membership_is_accepted(tmp_path: Path) -> None:
    fuel = {"desc": "Example Fuel", "who": "sam", "monthly": 40.00, "categories": ["Fuel"],
            "paced": True}
    ok_home = make_instance(
        tmp_path / "member", edited((9, fuel | {"bucket": "Variable Essential"}))
    )
    ok_report = check(ok_home)
    assert ok_report.ok
    assert ok_report.line_count == 10

    bad_home = make_instance(
        tmp_path / "outsider", edited((9, fuel | {"bucket": "Fixed Essential"}))
    )
    bad_report = check(bad_home)
    assert len(bad_report.problems) == 1
    problem = bad_report.problems[0]
    assert (problem.line, problem.column) == (11, "Categories")
    assert problem.problem == (
        'category "Fuel" splits across Variable Essential, Variable Discretionary in '
        'declarations.yaml but this line is bucket "Fixed Essential"'
    )


@pytest.mark.parametrize(
    ("index", "fields", "column"),
    [
        (1, {"bucket": "Nope"}, "Bucket"),
        (5, {"who": "pat"}, "Who"),
        (7, {"monthly": 11.00}, "Monthly"),
        (7, {"annual_full": 119.00}, "Annual Full"),
        (4, {"effective_until": "2025-03"}, "Effective Until"),
        (6, {"due": {"month": 1, "day": 1}}, "Due Month"),
    ],
)
def test_problems_match_loader_errors(
    tmp_path: Path, index: int, fields: dict[str, Any], column: str
) -> None:
    home = make_instance(tmp_path, edited((index, fields)))
    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)

    report = check(home)

    assert len(report.problems) == 1, report.problems
    row = report.problems[0]
    assert row.column == column
    with pytest.raises(ConfigError) as error_info:
        load_instance_plan(home, household=household, declarations=declarations)
    assert error_info.value.problem == row.problem
    assert error_info.value.key == row.key
    assert error_info.value.fix == row.fix


def test_missing_workbook_is_one_problem(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    shutil.rmtree(home / "data")

    result = run_hfk("plan", "check", "--home", str(home))

    assert result.returncode == 1
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert lines[0] == f"plan check {home / 'household.yaml'}"
    assert lines[1].startswith("  line -  files.tiller_glob  the plan is read from the HFK Plan")
    assert lines[-1] == "1 problem"


def test_leftover_plan_yaml_is_one_problem(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    (home / "plan.yaml").write_text("schema_version: 1\n", encoding="utf-8")

    report = check(home)

    assert report.line_count == 0
    assert len(report.problems) == 1
    problem = report.problems[0]
    assert problem.key == "(file)"
    assert "plan.yaml is no longer read" in problem.problem
    assert "hfk plan to-sheet" in problem.fix
    assert "then delete plan.yaml" in problem.fix
    result = run_hfk("plan", "check", "--home", str(home))
    assert result.returncode == 1
    assert result.stdout.splitlines()[0] == f"plan check {home / 'plan.yaml'}"


def test_missing_declarations_prints_plan_check_error(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    (home / "declarations.yaml").unlink()

    result = run_hfk("plan", "check", "--home", str(home))

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("plan check: ")
    assert "declarations.yaml" in result.stderr


def test_check_writes_nothing(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    def digests() -> dict[str, str]:
        return {
            str(path.relative_to(home)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(home.rglob("*"))
            if path.is_file()
        }

    before = digests()
    result = run_hfk("plan", "check", "--home", str(home))
    after = digests()

    assert result.returncode == 0
    assert before == after


def test_plan_without_subcommand_prints_help() -> None:
    result = run_hfk("plan")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "usage: hfk plan" in result.stderr
