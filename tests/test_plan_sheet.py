"""The ``HFK Plan`` workbook sheet as a plan source (roadmap M5-08; ADR-0013)."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import openpyxl
import pytest
import yaml

from hfk.cli import main
from hfk.config import (
    PLAN_SHEET,
    ConfigError,
    PlanSheetError,
    check_instance_plan,
    load_declarations,
    load_household,
    load_instance_plan,
    load_plan,
    load_plan_sheet,
)
from hfk.engine import run_doctor
from hfk.source.fixture import build_fixture

ROOT = Path(__file__).resolve().parent.parent
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
PYTHONPATH = str(ROOT / "src")


def make_instance(home: Path, *, source: str | None, plan_file: bool) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    for filename in ("household.yaml", "declarations.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, home / filename)
    if plan_file:
        shutil.copyfile(INSTANCE_EXAMPLE / "plan.yaml", home / "plan.yaml")
    if source is not None:
        household = yaml.safe_load((home / "household.yaml").read_text(encoding="utf-8"))
        household["plan"] = {"source": source}
        (home / "household.yaml").write_text(
            yaml.safe_dump(household, sort_keys=False), encoding="utf-8"
        )
    build_fixture(home / "data" / "Tiller-Example.xlsx", plan_tab=True)
    return home


def workbook(home: Path) -> Path:
    return home / "data" / "Tiller-Example.xlsx"


def edit_plan_sheet(home: Path, row: int, column: str, value: Any) -> None:
    """Change one cell of the synthetic fixture (tests may write the fixture, never src)."""

    path = workbook(home)
    book = openpyxl.load_workbook(path)
    sheet = book[PLAN_SHEET]
    headers = [cell.value for cell in sheet[1]]
    if column not in headers:
        sheet.cell(row=1, column=len(headers) + 1, value=column)
        headers.append(column)
    # cell(value=None) leaves the old value in place, so assign explicitly.
    sheet.cell(row=row, column=headers.index(column) + 1).value = value
    book.save(path)


def loaded(home: Path):
    household = load_household(home)
    declarations = load_declarations(home, people=household.slugs)
    return household, declarations


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


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fixture_tab_loads_equal_to_example_plan_yaml(tmp_path: Path) -> None:
    home = make_instance(tmp_path, source="workbook", plan_file=False)
    household, declarations = loaded(home)

    from_sheet = load_instance_plan(home, household=household, declarations=declarations)
    from_file = load_plan(INSTANCE_EXAMPLE, declarations=declarations, people=household.slugs)

    assert from_sheet.source == "workbook"
    assert from_sheet.path == workbook(home)
    assert from_sheet.effective_from == from_file.effective_from
    assert len(from_sheet.lines) == len(from_file.lines)
    for sheet_line, file_line in zip(from_sheet.lines, from_file.lines, strict=True):
        assert sheet_line == file_line
    assert from_sheet.line_rows == tuple(range(2, 2 + len(from_file.lines)))
    assert from_sheet.describe_line(0) == "HFK Plan row 2"


def test_source_defaults_to_file(tmp_path: Path) -> None:
    home = make_instance(tmp_path, source=None, plan_file=True)
    household, declarations = loaded(home)

    plan = load_instance_plan(home, household=household, declarations=declarations)

    assert household.plan_source == "file"
    assert plan.source == "file"
    assert plan.path == home / "plan.yaml"


@pytest.mark.parametrize("who", ["alex", "sam"])
def test_scorecard_matches_to_the_cent_between_sources(tmp_path: Path, who: str) -> None:
    file_home = make_instance(tmp_path / "file", source="file", plan_file=True)
    sheet_home = make_instance(tmp_path / "sheet", source="workbook", plan_file=False)
    args = ("--month", "2026-09", "--who", who, "--today", "2026-10-01")

    for fmt in ("text", "csv"):
        from_file = run_hfk("scorecard", "--home", str(file_home), *args, "--format", fmt)
        from_sheet = run_hfk("scorecard", "--home", str(sheet_home), *args, "--format", fmt)
        assert from_file.returncode == 0, from_file.stderr
        assert from_sheet.returncode == 0, from_sheet.stderr
        assert from_sheet.stderr == ""
        assert from_sheet.stdout == from_file.stdout


def test_other_plan_commands_match_between_sources(tmp_path: Path) -> None:
    file_home = make_instance(tmp_path / "file", source="file", plan_file=True)
    sheet_home = make_instance(tmp_path / "sheet", source="workbook", plan_file=False)

    for args in (
        ("renewals", "--month", "2026-09"),
        ("categories", "--month", "2026-09", "--who", "alex", "--today", "2026-10-01"),
    ):
        from_file = run_hfk(args[0], "--home", str(file_home), *args[1:])
        from_sheet = run_hfk(args[0], "--home", str(sheet_home), *args[1:])
        assert from_file.returncode == 0, from_file.stderr
        assert from_sheet.returncode == 0, from_sheet.stderr
        assert from_sheet.stdout == from_file.stdout


@pytest.mark.parametrize(
    ("row", "column", "value", "problem", "fix"),
    [
        (3, "Monthly", "ninety", "Expected a dollar amount", "two decimal places"),
        (3, "Monthly", -5, "Amount must be at least 0.00", "two decimal places"),
        (2, "Bucket", "Nope", "Unknown bucket 'Nope'", "use one of"),
        (4, "Who", "pat", "Unknown person slug 'pat'", "household.yaml"),
        (5, "Paced", "maybe", "Invalid Paced value 'maybe'", "write yes, no"),
        (6, "Effective From", None, "Missing value", "Effective From"),
        (6, "Effective From", "July", "Invalid month 'July'", "YYYY-MM"),
        (5, "Effective Until", "2024-12", "Effective Until is before Effective From", "Effective Until"),
        (9, "Due Day", None, "Due Month and Due Day must both be filled", "Due Day"),
        (9, "Monthly", 11, "Monthly should be 10.00 for Annual Bill 120.00", "set Monthly"),
        (8, "Annual Full", 50, "Annual Full requires Annual Bill", "clear this cell"),
        (2, "Categories", "Rent;;Utilities", "Empty category name", "single ;"),
        (2, "Categories", "Rent; Rent", "Duplicate category 'Rent'", "list each category once"),
    ],
)
def test_malformed_row_names_sheet_row_column_and_fix(
    tmp_path: Path, row: int, column: str, value: Any, problem: str, fix: str
) -> None:
    home = make_instance(tmp_path, source="workbook", plan_file=False)
    edit_plan_sheet(home, row, column, value)
    household, declarations = loaded(home)

    with pytest.raises(PlanSheetError) as caught:
        load_instance_plan(home, household=household, declarations=declarations)

    error = caught.value
    assert error.sheet == PLAN_SHEET
    assert error.row == row
    assert error.column == column
    assert problem in error.problem
    assert fix in error.fix
    assert f"sheet=HFK Plan, row={row}, column={column}" in str(error)
    assert "fix=" in str(error)

    result = run_hfk("plan", "check", "--home", str(home))
    assert result.returncode == 1
    assert f"sheet HFK Plan  row {row}  column {column}  " in result.stdout
    assert problem in result.stdout
    assert "fix: " in result.stdout


def test_plan_check_reports_every_bad_row_at_once(tmp_path: Path) -> None:
    home = make_instance(tmp_path, source="workbook", plan_file=False)
    edit_plan_sheet(home, 3, "Monthly", "ninety")
    edit_plan_sheet(home, 7, "Bucket", "Nope")
    household, declarations = loaded(home)

    report = check_instance_plan(home, household=household, declarations=declarations)

    assert report.source == "workbook"
    assert [(p.line, p.column) for p in report.problems] == [(3, "Monthly"), (7, "Bucket")]
    assert report.line_count == 9


def test_plan_check_passes_on_the_fixture_tab(tmp_path: Path) -> None:
    home = make_instance(tmp_path, source="workbook", plan_file=False)

    result = run_hfk("plan", "check", "--home", str(home))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "(sheet HFK Plan)" in result.stdout
    assert "ok: 9 lines" in result.stdout


def test_duplicate_category_across_rows_names_the_later_row(tmp_path: Path) -> None:
    home = make_instance(tmp_path, source="workbook", plan_file=False)
    edit_plan_sheet(home, 5, "Effective Until", None)
    household, declarations = loaded(home)

    report = check_instance_plan(home, household=household, declarations=declarations)

    assert len(report.problems) == 1
    problem = report.problems[0]
    assert (problem.sheet, problem.line, problem.column) == (PLAN_SHEET, 6, "Categories")
    assert 'is also on HFK Plan row 5 ("Example Grocer")' in problem.problem
    assert "Effective Until" in problem.fix


def test_missing_required_column_names_sheet_and_column(tmp_path: Path) -> None:
    home = make_instance(tmp_path, source="workbook", plan_file=False)
    path = workbook(home)
    book = openpyxl.load_workbook(path)
    sheet = book[PLAN_SHEET]
    headers = [cell.value for cell in sheet[1]]
    sheet.cell(row=1, column=headers.index("Who") + 1, value="Person")
    book.save(path)
    household, declarations = loaded(home)

    with pytest.raises(PlanSheetError) as caught:
        load_instance_plan(home, household=household, declarations=declarations)

    assert (caught.value.row, caught.value.column) == (1, "Who")
    assert "add a Who header in row 1" in caught.value.fix


def test_missing_sheet_is_a_loud_error(tmp_path: Path) -> None:
    home = make_instance(tmp_path, source="workbook", plan_file=False)
    build_fixture(workbook(home), plan_tab=False)
    household, declarations = loaded(home)

    with pytest.raises(PlanSheetError, match="Missing plan sheet") as caught:
        load_instance_plan(home, household=household, declarations=declarations)

    assert "plan: {source: file}" in caught.value.fix


def test_columns_are_read_by_header_not_position(tmp_path: Path) -> None:
    home = tmp_path
    for filename in ("household.yaml", "declarations.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, home / filename)
    path = build_fixture(
        home / "data" / "Tiller-Example.xlsx",
        plan_tab=True,
        shuffle_headers=True,
        extra_columns=[("HFK Plan", "Notes")],
    )
    household, declarations = loaded(home)

    plan = load_plan_sheet(path, declarations=declarations, people=household.slugs)
    expected = load_plan(INSTANCE_EXAMPLE, declarations=declarations, people=household.slugs)

    assert plan.lines == expected.lines


def test_tab_plus_plan_yaml_warns_that_the_file_is_ignored(tmp_path: Path) -> None:
    home = make_instance(tmp_path, source="workbook", plan_file=True)
    (home / "plan.yaml").write_text("not: [valid yaml for a plan\n", encoding="utf-8")

    scorecard = run_hfk(
        "scorecard", "--home", str(home), "--month", "2026-09", "--who", "alex",
        "--today", "2026-10-01",
    )
    check = run_hfk("plan", "check", "--home", str(home))
    report = run_doctor(home, today=__import__("datetime").date(2026, 10, 1))

    for result in (scorecard, check):
        assert result.returncode == 0, result.stdout + result.stderr
        assert "plan.yaml is ignored because household.yaml sets plan: {source: workbook}" in (
            result.stderr
        )
    unused = [d for d in report.diagnostics if d.code == "plan-file-unused"]
    assert len(unused) == 1
    assert unused[0].level == "warning"
    assert unused[0].where == "plan.yaml"


def test_unknown_plan_source_is_an_error(tmp_path: Path) -> None:
    home = make_instance(tmp_path, source="sheet", plan_file=True)

    with pytest.raises(ConfigError) as caught:
        load_household(home)

    assert caught.value.key == "plan.source"


def test_workbook_is_never_saved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = make_instance(tmp_path, source="workbook", plan_file=False)
    edit_plan_sheet(home, 3, "Monthly", "ninety")
    before = digest(workbook(home))

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("a workbook was saved")

    opened: list[dict[str, Any]] = []
    real_load = openpyxl.load_workbook

    def spy(*args: Any, **kwargs: Any):
        opened.append(kwargs)
        return real_load(*args, **kwargs)

    monkeypatch.setattr(openpyxl.Workbook, "save", refuse)
    monkeypatch.setattr(openpyxl, "load_workbook", spy)
    household, declarations = loaded(home)
    with pytest.raises(PlanSheetError):
        load_instance_plan(home, household=household, declarations=declarations)
    check_instance_plan(home, household=household, declarations=declarations)
    assert main(["plan", "check", "--home", str(home)]) == 1
    run_doctor(home, today=__import__("datetime").date(2026, 10, 1))

    assert opened
    assert all(kwargs.get("read_only") is True and kwargs.get("data_only") is True for kwargs in opened)
    assert digest(workbook(home)) == before
