"""`hfk plan check` (M4-06): every plan.yaml problem, with line, key, and fix."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hfk.config import (
    ConfigError,
    PlanCheckReport,
    check_plan,
    load_declarations,
    load_plan,
)

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
PYTHONPATH = str(ROOT / "src")
EXAMPLE_PLAN = (INSTANCE_EXAMPLE / "plan.yaml").read_text(encoding="utf-8")
PEOPLE = ("alex", "sam")

LINE_UTILITIES_NOPE = (
    '    - {desc: "Example Utilities", who: alex, bucket: Nope, monthly: 90.00, '
    "categories: [Utilities], paced: true}"
)
LINE_TRANSIT_PAT = (
    '    - {desc: "Example Transit", who: pat, bucket: Variable Essential, '
    "monthly: 80.00, categories: [Transit], paced: true}"
)
LINE_CLOUD_MONTHLY_11 = (
    '    - {desc: "Example Cloud Renewal", who: alex, bucket: Fixed Discretionary, '
    "monthly: 11.00, annual_bill: 120.00, annual_full: 120.00, "
    'account: "Alex Checking", due: {month: 7, day: 1}, categories: [Annual Membership]}'
)
LINE_CLOUD_ANNUAL_FULL_119 = (
    '    - {desc: "Example Cloud Renewal", who: alex, bucket: Fixed Discretionary, '
    "monthly: 10.00, annual_bill: 120.00, annual_full: 119.00, "
    'account: "Alex Checking", due: {month: 7, day: 1}, categories: [Annual Membership]}'
)
LINE_GROCER_UNTIL_MARCH = (
    '    - {desc: "Example Grocer", who: alex, bucket: Variable Essential, '
    "monthly: 550.00, categories: [Groceries], paced: true, "
    "effective_from: 2025-07, effective_until: 2025-03}"
)
LINE_GROCER_UNTIL_AUGUST = (
    '    - {desc: "Example Grocer", who: alex, bucket: Variable Essential, '
    "monthly: 500.00, categories: [Groceries], paced: true, effective_until: 2025-08}"
)
LINE_STREAMING_TYPE = (
    '    - {desc: "Example Streaming", who: alex, type: Fixed Essential, monthly: 20.00}'
)
LINE_STREAMING_NO_MONTHLY = '    - {desc: "Example Streaming", who: alex, bucket: Fixed Discretionary}'
LINE_STREAMING_DUE = (
    '    - {desc: "Example Streaming", who: alex, bucket: Fixed Discretionary, '
    "monthly: 20.00, due: {month: 1, day: 1}}"
)
LINE_STREAMING_WRAPPED = (
    '    - {desc: "Example Streaming", who: alex, bucket: Fixed Discretionary, '
    "monthly: 20.00,\n       effective_from: 2024-12}"
)
LINE_CAFE_ESSENTIAL = (
    '    - {desc: "Example Cafe", who: sam, bucket: Variable Essential, '
    "monthly: 60.00, categories: [Dining], paced: true}"
)
LINE_FUEL_VARIABLE = (
    '    - {desc: "Example Fuel", who: sam, bucket: Variable Essential, '
    "monthly: 40.00, categories: [Fuel], paced: true}"
)
LINE_FUEL_FIXED = (
    '    - {desc: "Example Fuel", who: sam, bucket: Fixed Essential, '
    "monthly: 40.00, categories: [Fuel], paced: true}"
)

ROW_UNKNOWN_BUCKET = (
    "  line 7  plan.lines[1].bucket  Unknown bucket 'Nope'; fix: use one of "
    "['Fixed Essential', 'Variable Essential', 'Fixed Discretionary', "
    "'Variable Discretionary']"
)
ROW_MISSING_FILE = (
    "  line -  (file)  Missing config file; fix: create plan.yaml in the instance home "
    "(see examples/plan.example.yaml)"
)


def make_instance(home: Path, plan_text: str = EXAMPLE_PLAN) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    for filename in ("household.yaml", "declarations.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, home / filename)
    (home / "plan.yaml").write_text(plan_text, encoding="utf-8")
    return home


def edit_plan(*edits: tuple[int, str]) -> str:
    """Replace physical lines (1-based) of the example plan; a replacement may span lines."""

    lines = EXAMPLE_PLAN.splitlines()
    for line_number, replacement in edits:
        lines[line_number - 1 : line_number] = replacement.split("\n")
    return "\n".join(lines) + "\n"


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
    declarations = load_declarations(home, people=PEOPLE)
    return check_plan(home, declarations=declarations, people=PEOPLE)


def problem_rows(stdout: str) -> list[list[str]]:
    return [
        line[2:].split("  ", 2) for line in stdout.splitlines() if line.startswith("  line ")
    ]


def test_plan_check_cli_passes_on_example_instance(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    result = run_hfk("plan", "check", "--home", str(home))

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        f"plan check {home / 'plan.yaml'}",
        "ok: 9 lines",
    ]


def test_unknown_bucket_names_line_and_fix(tmp_path: Path) -> None:
    home = make_instance(tmp_path, edit_plan((7, LINE_UTILITIES_NOPE)))

    result = run_hfk("plan", "check", "--home", str(home))

    assert result.returncode == 1
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        f"plan check {home / 'plan.yaml'}",
        ROW_UNKNOWN_BUCKET,
        "1 problem",
    ]


def test_every_problem_is_reported_at_once(tmp_path: Path) -> None:
    home = make_instance(
        tmp_path,
        edit_plan(
            (7, LINE_UTILITIES_NOPE),
            (11, LINE_TRANSIT_PAT),
            (13, LINE_CLOUD_MONTHLY_11),
        ),
    )

    result = run_hfk("plan", "check", "--home", str(home))

    assert result.returncode == 1
    assert result.stderr == ""
    rows = problem_rows(result.stdout)
    assert [(row[0], row[1]) for row in rows] == [
        ("line 7", "plan.lines[1].bucket"),
        ("line 11", "plan.lines[5].who"),
        ("line 13", "plan.lines[7].monthly"),
    ]
    assert rows[2][2] == (
        "monthly should be 10.00 for annual_bill 120.00; "
        "fix: set monthly to 10.00 or adjust annual_bill"
    )
    assert result.stdout.splitlines()[-1] == "3 problems"


def test_line_number_points_at_the_offending_key(tmp_path: Path) -> None:
    home = make_instance(tmp_path, edit_plan((12, LINE_STREAMING_WRAPPED)))

    report = check(home)

    assert len(report.problems) == 1
    problem = report.problems[0]
    assert problem.line == 13
    assert problem.key == "plan.lines[6].effective_from"
    assert problem.problem == "Line effective_from is before plan.effective_from"
    assert problem.fix == "use 2025-01 or a later month"


def test_missing_key_points_at_the_entry_line(tmp_path: Path) -> None:
    home = make_instance(tmp_path, edit_plan((12, LINE_STREAMING_NO_MONTHLY)))

    result = run_hfk("plan", "check", "--home", str(home))

    assert result.returncode == 1
    assert problem_rows(result.stdout) == [
        [
            "line 12",
            "plan.lines[6].monthly",
            "Missing required key; fix: add monthly (see examples/plan.example.yaml)",
        ]
    ]
    assert result.stdout.splitlines()[-1] == "1 problem"


def test_per_line_problems_report_their_physical_lines(tmp_path: Path) -> None:
    home = make_instance(
        tmp_path,
        edit_plan(
            (10, LINE_GROCER_UNTIL_MARCH),
            (12, LINE_STREAMING_TYPE),
        ),
    )

    result = run_hfk("plan", "check", "--home", str(home))

    assert result.returncode == 1
    rows = problem_rows(result.stdout)
    assert [(row[0], row[1]) for row in rows] == [
        ("line 10", "plan.lines[4].effective_until"),
        ("line 12", "plan.lines[6].type"),
    ]
    assert rows[0][2] == (
        "Line effective_until is before effective_from; fix: use the same month as "
        "effective_from, a later month, or remove effective_until"
    )
    assert rows[1][2] == (
        "Plan lines use bucket, not type; fix: rename type to bucket; "
        "Type already means Expense/Income/Transfer in Tiller"
    )
    assert result.stdout.splitlines()[-1] == "2 problems"


def test_duplicate_category_overlap_is_reported_on_the_later_line(tmp_path: Path) -> None:
    home = make_instance(tmp_path, edit_plan((9, LINE_GROCER_UNTIL_AUGUST)))

    report = check(home)
    declarations = load_declarations(home, people=PEOPLE)
    loaded = load_plan(home, declarations=declarations, people=PEOPLE)

    assert len(loaded.lines) == 9
    assert len(report.problems) == 1
    problem = report.problems[0]
    assert problem.line == 10
    assert problem.key == "plan.lines[4].categories[0]"
    assert problem.problem == (
        'category "Groceries" for "alex" is also on plan.lines[3] ("Example Grocer") '
        "with first overlapping month 2025-07"
    )
    assert problem.fix == (
        "end one line with effective_until before the other starts, "
        "or remove the category from one of them"
    )


def test_non_overlapping_lines_are_fine(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    report = check(home)

    assert report.ok
    assert report.problems == ()
    assert report.line_count == 9
    assert not any("Groceries" in problem.problem for problem in report.problems)


def test_override_bucket_mismatch_is_reported(tmp_path: Path) -> None:
    home = make_instance(tmp_path, edit_plan((14, LINE_CAFE_ESSENTIAL)))

    report = check(home)

    assert len(report.problems) == 1
    problem = report.problems[0]
    assert problem.line == 14
    assert problem.key == "plan.lines[8].categories[0]"
    assert problem.problem == (
        'category "Dining" maps to bucket "Variable Discretionary" in declarations.yaml '
        'but this line is bucket "Variable Essential"'
    )
    assert problem.fix == (
        "move the line to Variable Discretionary, or change the declarations.yaml "
        "override, split, or categories entry"
    )


def test_split_bucket_membership_is_accepted(tmp_path: Path) -> None:
    ok_home = make_instance(tmp_path / "member", edit_plan((15, LINE_FUEL_VARIABLE)))

    ok_result = run_hfk("plan", "check", "--home", str(ok_home))
    ok_report = check(ok_home)

    assert ok_result.returncode == 0
    assert ok_result.stdout.splitlines()[-1] == "ok: 10 lines"
    assert ok_report.ok
    assert ok_report.line_count == 10

    bad_home = make_instance(tmp_path / "outsider", edit_plan((15, LINE_FUEL_FIXED)))

    bad_result = run_hfk("plan", "check", "--home", str(bad_home))
    bad_report = check(bad_home)

    assert bad_result.returncode == 1
    assert len(bad_report.problems) == 1
    problem = bad_report.problems[0]
    assert problem.line == 15
    assert problem.key == "plan.lines[9].categories[0]"
    assert problem.problem == (
        'category "Fuel" splits across Variable Essential, Variable Discretionary in '
        'declarations.yaml but this line is bucket "Fixed Essential"'
    )
    assert problem.fix == (
        "move the line to Variable Essential, Variable Discretionary, or change the "
        "declarations.yaml override, split, or categories entry"
    )


def test_problems_match_load_plan_errors(tmp_path: Path) -> None:
    plans = [
        edit_plan((7, LINE_UTILITIES_NOPE)),
        edit_plan((11, LINE_TRANSIT_PAT)),
        edit_plan((13, LINE_CLOUD_MONTHLY_11)),
        edit_plan((12, LINE_STREAMING_TYPE)),
        edit_plan((12, LINE_STREAMING_NO_MONTHLY)),
        edit_plan((10, LINE_GROCER_UNTIL_MARCH)),
        edit_plan((12, LINE_STREAMING_DUE)),
        edit_plan((13, LINE_CLOUD_ANNUAL_FULL_119)),
        edit_plan((12, LINE_STREAMING_WRAPPED)),
    ]

    for number, plan_text in enumerate(plans):
        home = make_instance(tmp_path / f"case-{number}", plan_text)
        declarations = load_declarations(home, people=PEOPLE)

        report = check_plan(home, declarations=declarations, people=PEOPLE)

        assert len(report.problems) == 1, (number, report.problems)
        row = report.problems[0]

        with pytest.raises(ConfigError) as error_info:
            load_plan(home, declarations=declarations, people=PEOPLE)

        assert error_info.value.problem == row.problem, number
        assert error_info.value.key == row.key, number
        assert error_info.value.fix == row.fix, number


def test_missing_plan_file_is_one_problem(tmp_path: Path) -> None:
    home = tmp_path
    home.mkdir(parents=True, exist_ok=True)
    for filename in ("household.yaml", "declarations.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, home / filename)

    result = run_hfk("plan", "check", "--home", str(home))

    assert result.returncode == 1
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        f"plan check {home / 'plan.yaml'}",
        ROW_MISSING_FILE,
        "1 problem",
    ]

    report = check(home)
    assert report.line_count == 0
    assert len(report.problems) == 1
    assert report.problems[0].line == 0
    assert report.problems[0].key == "(file)"
    assert report.problems[0].problem == "Missing config file"


def test_unparseable_plan_is_one_problem(tmp_path: Path) -> None:
    home = make_instance(tmp_path, "plan: [unclosed")

    result = run_hfk("plan", "check", "--home", str(home))

    assert result.returncode == 1
    assert result.stderr == ""
    lines = result.stdout.splitlines()
    assert lines[1].startswith("  line -  (file)  Unparseable YAML (")
    assert lines[-1] == "1 problem"

    report = check(home)
    assert report.line_count == 0
    assert report.problems[0].key == "(file)"
    assert report.problems[0].problem.startswith("Unparseable YAML (")


def test_missing_declarations_prints_plan_check_error(tmp_path: Path) -> None:
    shutil.copyfile(INSTANCE_EXAMPLE / "household.yaml", tmp_path / "household.yaml")
    (tmp_path / "plan.yaml").write_text(EXAMPLE_PLAN, encoding="utf-8")

    result = run_hfk("plan", "check", "--home", str(tmp_path))

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("plan check: ")
    assert "declarations.yaml" in result.stderr


def test_check_writes_nothing(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    def digests() -> dict[str, str]:
        return {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(home.iterdir())
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
