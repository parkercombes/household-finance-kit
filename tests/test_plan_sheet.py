"""The ``HFK Plan`` workbook sheet, the only plan source (M5-08, M5-18; ADR-0013, ADR-0015)."""

from __future__ import annotations

import ast
import csv
import hashlib
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import openpyxl
import pytest
import yaml
from plan_fixture import EXAMPLE_PLAN_YAML

from hfk.cli import main
from hfk.config import (
    PLAN_SHEET,
    ConfigError,
    PlanSheetError,
    check_instance_plan,
    load_declarations,
    load_household,
    load_instance_plan,
    load_plan_sheet,
    plan_csv,
)
from hfk.config.plan_convert import load_plan_file
from hfk.engine import run_doctor
from hfk.source.fixture import build_fixture

ROOT = Path(__file__).resolve().parent.parent
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
PYTHONPATH = str(ROOT / "src")
SRC = ROOT / "src" / "hfk"


def make_instance(home: Path, *, plan_yaml: bool = False) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    for filename in ("household.yaml", "declarations.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, home / filename)
    if plan_yaml:
        (home / "plan.yaml").write_text(EXAMPLE_PLAN_YAML, encoding="utf-8")
    build_fixture(home / "data" / "Tiller-Example.xlsx", plan_tab=True)
    return home


def former_plan(tmp_path: Path, declarations, people):
    """The example plan as it used to be written in examples/instance/plan.yaml."""

    path = tmp_path / "former-plan.yaml"
    path.write_text(EXAMPLE_PLAN_YAML, encoding="utf-8")
    return load_plan_file(path, declarations=declarations, people=people)


def csv_rows(text: str) -> list[dict[str, object]]:
    """CSV text as sheet rows, each cell the plain text a paste would put there."""

    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


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


def test_fixture_tab_loads_equal_to_the_former_plan_yaml(tmp_path: Path) -> None:
    home = make_instance(tmp_path / "home")
    household, declarations = loaded(home)

    from_sheet = load_instance_plan(home, household=household, declarations=declarations)
    from_file = former_plan(tmp_path, declarations, household.slugs)

    assert from_sheet.source == "workbook"
    assert from_sheet.path == workbook(home)
    assert from_sheet.effective_from == from_file.effective_from
    assert len(from_sheet.lines) == len(from_file.lines)
    for sheet_line, file_line in zip(from_sheet.lines, from_file.lines, strict=True):
        assert sheet_line == file_line
    assert from_sheet.line_rows == tuple(range(2, 2 + len(from_file.lines)))
    assert from_sheet.describe_line(0) == "HFK Plan row 2"


def test_example_readme_table_matches_the_fixture_tab(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    household, declarations = loaded(home)
    plan = load_instance_plan(home, household=household, declarations=declarations)
    readme = (INSTANCE_EXAMPLE / "README.md").read_text(encoding="utf-8")
    table = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in readme.splitlines()
        if line.startswith("| Example ")
    ]
    expected = list(csv.reader(io.StringIO(plan_csv(plan.lines))))[1:]

    assert table == expected


def test_plan_yaml_is_an_error_for_every_plan_command(tmp_path: Path) -> None:
    home = make_instance(tmp_path, plan_yaml=True)
    household, declarations = loaded(home)

    with pytest.raises(ConfigError) as caught:
        load_instance_plan(home, household=household, declarations=declarations)
    assert caught.value.file == home / "plan.yaml"
    assert "hfk plan to-sheet" in caught.value.fix
    assert "then delete plan.yaml" in caught.value.fix

    month = ("--month", "2026-09")
    for args in (
        ("scorecard", *month, "--who", "alex", "--today", "2026-10-01"),
        ("categories", *month, "--who", "alex", "--today", "2026-10-01"),
        ("renewals", *month),
        ("rebaseline", "--who", "alex", "--today", "2026-10-01"),
    ):
        result = run_hfk(args[0], "--home", str(home), *args[1:])
        assert result.returncode == 1, args
        assert "plan.yaml is no longer read" in result.stderr, args
    check = run_hfk("plan", "check", "--home", str(home))
    assert check.returncode == 1
    assert "plan.yaml is no longer read" in check.stdout
    report = run_doctor(home, today=__import__("datetime").date(2026, 10, 1))
    assert not report.ok
    assert any("plan.yaml is no longer read" in d.message for d in report.errors())


def test_household_plan_key_is_a_loud_error(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    data = yaml.safe_load((home / "household.yaml").read_text(encoding="utf-8"))
    data["plan"] = {"source": "workbook"}
    (home / "household.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ConfigError) as caught:
        load_household(home)
    assert caught.value.key == "plan"
    assert caught.value.fix == "delete the plan key from household.yaml"


def test_to_sheet_converts_the_former_plan_yaml_line_for_line(tmp_path: Path) -> None:
    home = make_instance(tmp_path / "home", plan_yaml=True)
    household, declarations = loaded(home)

    result = run_hfk("plan", "to-sheet", "--home", str(home))

    assert result.returncode == 0, result.stderr
    output = home / "out" / "hfk-plan-starter.csv"
    assert f"wrote 9 plan lines to {output}" in result.stdout
    text = output.read_text(encoding="utf-8")
    assert text.splitlines()[0] == (
        "Description,Who,Bucket,Monthly,Categories,Paced,Effective From,Effective Until,"
        "Annual Bill,Annual Full,Account,Due Month,Due Day"
    )
    pasted = build_fixture(tmp_path / "pasted.xlsx", plan_rows=csv_rows(text))
    from_csv = load_plan_sheet(pasted, declarations=declarations, people=household.slugs)
    fixture_tab = load_plan_sheet(workbook(home), declarations=declarations, people=household.slugs)
    assert from_csv.lines == fixture_tab.lines
    assert (home / "plan.yaml").exists(), "to-sheet never deletes plan.yaml"

    again = run_hfk("plan", "to-sheet", "--home", str(home))
    assert again.returncode == 1
    assert "already exists" in again.stderr


def test_to_sheet_without_plan_yaml_fails_loudly(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    result = run_hfk("plan", "to-sheet", "--home", str(home))
    assert result.returncode == 1
    assert "nothing to convert" in result.stderr
    assert not (home / "out").exists()


def test_converted_plan_gives_the_same_reports(tmp_path: Path) -> None:
    home = make_instance(tmp_path / "home", plan_yaml=True)
    assert run_hfk("plan", "to-sheet", "--home", str(home)).returncode == 0
    text = (home / "out" / "hfk-plan-starter.csv").read_text(encoding="utf-8")
    converted = make_instance(tmp_path / "converted")
    build_fixture(workbook(converted), plan_rows=csv_rows(text))
    original = make_instance(tmp_path / "original")

    for args in (
        ("scorecard", "--month", "2026-09", "--who", "alex", "--today", "2026-10-01"),
        ("scorecard", "--month", "2026-09", "--who", "sam", "--today", "2026-10-01"),
        ("renewals", "--month", "2026-09"),
        ("categories", "--month", "2026-09", "--who", "alex", "--today", "2026-10-01"),
    ):
        expected = run_hfk(args[0], "--home", str(original), *args[1:])
        actual = run_hfk(args[0], "--home", str(converted), *args[1:])
        assert expected.returncode == 0, expected.stderr
        assert actual.stdout == expected.stdout, args


def test_only_the_converter_reads_plan_yaml() -> None:
    """No module under src/hfk but the to-sheet converter loads a plan.yaml."""

    readers = set()
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name in {"load_plan_file", "load_mapping"}:
                    readers.add((path.relative_to(SRC).as_posix(), name))
    plan_yaml_readers = {
        module for module, name in readers if name == "load_mapping"
        and "PLAN_FILE" in (SRC / module).read_text(encoding="utf-8")
    }
    assert plan_yaml_readers <= {"config/plan_convert.py"}
    assert {module for module, name in readers if name == "load_plan_file"} == {"cli.py"}
    cli = (SRC / "cli.py").read_text(encoding="utf-8")
    assert cli.count("load_plan_file(") == 1
    assert "def _plan_to_sheet(" in cli


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
    home = make_instance(tmp_path)
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
    home = make_instance(tmp_path)
    edit_plan_sheet(home, 3, "Monthly", "ninety")
    edit_plan_sheet(home, 7, "Bucket", "Nope")
    household, declarations = loaded(home)

    report = check_instance_plan(home, household=household, declarations=declarations)

    assert [(p.line, p.column) for p in report.problems] == [(3, "Monthly"), (7, "Bucket")]
    assert report.line_count == 9


def test_plan_check_passes_on_the_fixture_tab(tmp_path: Path) -> None:
    home = make_instance(tmp_path)

    result = run_hfk("plan", "check", "--home", str(home))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "(sheet HFK Plan)" in result.stdout
    assert "ok: 9 lines" in result.stdout


def test_duplicate_category_across_rows_names_the_later_row(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
    edit_plan_sheet(home, 5, "Effective Until", None)
    household, declarations = loaded(home)

    report = check_instance_plan(home, household=household, declarations=declarations)

    assert len(report.problems) == 1
    problem = report.problems[0]
    assert (problem.sheet, problem.line, problem.column) == (PLAN_SHEET, 6, "Categories")
    assert 'is also on HFK Plan row 5 ("Example Grocer")' in problem.problem
    assert "Effective Until" in problem.fix


def test_missing_required_column_names_sheet_and_column(tmp_path: Path) -> None:
    home = make_instance(tmp_path)
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
    home = make_instance(tmp_path)
    build_fixture(workbook(home), plan_tab=False)
    household, declarations = loaded(home)

    with pytest.raises(PlanSheetError, match="Missing plan sheet") as caught:
        load_instance_plan(home, household=household, declarations=declarations)

    assert "add a sheet named HFK Plan" in caught.value.fix


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
    expected = former_plan(tmp_path, declarations, household.slugs)

    assert plan.lines == expected.lines


def test_workbook_is_never_saved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = make_instance(tmp_path)
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
