"""Validate the ``HFK Plan`` sheet for ``hfk plan check`` without stopping at the first problem.

The check reads the workbook read-only and writes nothing, ever. Three rule
groups (ADR-0015 made the sheet the only plan source):

1. Sheet-level problems stop the check with exactly one problem: a
   ``plan.yaml`` still in the instance, no workbook, no ``HFK Plan`` sheet, a
   missing required column, or a sheet with no plan rows.
2. Per-row problems: every row is validated independently with the loader's
   own rules, reporting the first problem of each bad row and continuing, so
   one run names every bad row at once.
3. Cross-row problems over the rows that passed: one person's category on two
   rows effective in the same month, and a category whose bucket
   ``declarations.yaml`` alone determines (an override, a split, or a
   ``categories`` entry under ``mapping_source: explicit``) sitting on a row
   in a different bucket. Group-mapped categories need the ledger and stay
   with ``hfk doctor``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from hfk.config.declarations import Declarations
from hfk.config.errors import ConfigError, PlanSheetError
from hfk.config.household import Household
from hfk.config.plan import Month, PlanLine
from hfk.config.plan_sheet import (
    PLAN_SHEET,
    plan_workbook,
    read_plan_sheet,
    reject_plan_file,
    sheet_lines,
    sheet_terms,
)


@dataclass(frozen=True)
class PlanProblem:
    """One plan problem and its fix.

    For the ``HFK Plan`` sheet, ``sheet`` is set, ``line`` is the sheet row (0
    when the problem is the whole sheet), and ``column`` names the header. A
    problem outside the sheet (a leftover ``plan.yaml``, no workbook) has no
    ``sheet``, ``line`` 0, and ``key`` naming the file's key.
    """

    line: int
    key: str
    problem: str
    fix: str
    sheet: str | None = None
    column: str | None = None


@dataclass(frozen=True)
class PlanCheckReport:
    """Every problem found in the plan; the check itself wrote nothing."""

    path: Path
    problems: tuple[PlanProblem, ...]
    line_count: int
    source: str = "workbook"

    @property
    def ok(self) -> bool:
        return not self.problems


def check_plan_sheet(
    workbook: Path,
    *,
    declarations: Declarations,
    people: Iterable[str] | None = None,
) -> PlanCheckReport:
    """Collect every problem in the ``HFK Plan`` sheet of ``workbook``; nothing is written."""

    workbook = Path(workbook)
    try:
        sheet = read_plan_sheet(workbook)
    except PlanSheetError as error:
        return PlanCheckReport(
            path=workbook, problems=(_sheet_problem(error),), line_count=0
        )

    problems: list[PlanProblem] = []
    good: list[tuple[int, PlanLine]] = []
    rows: dict[int, int] = {}
    for result in sheet_lines(sheet, declarations=declarations, people=people):
        rows[result.index] = result.row
        if result.error is not None:
            problems.append(_sheet_problem(result.error))
        else:
            assert result.line is not None
            good.append((result.index, result.line))

    where = _SheetLocator(rows)
    problems.extend(_duplicate_category_problems(good, where))
    problems.extend(_bucket_mapping_problems(good, declarations, where))
    problems.sort(key=lambda problem: problem.line)
    return PlanCheckReport(path=workbook, problems=tuple(problems), line_count=len(sheet.rows))


def check_instance_plan(
    home: Path, *, household: Household, declarations: Declarations
) -> PlanCheckReport:
    """``hfk plan check``: validate the ``HFK Plan`` sheet of the instance's workbook."""

    try:
        reject_plan_file(home)
        workbook = plan_workbook(home, household)
    except ConfigError as error:
        return PlanCheckReport(
            path=error.file,
            problems=(PlanProblem(line=0, key=error.key, problem=error.problem, fix=error.fix),),
            line_count=0,
        )
    return check_plan_sheet(workbook, declarations=declarations, people=household.slugs)


def _sheet_problem(error: PlanSheetError) -> PlanProblem:
    return PlanProblem(
        line=error.row,
        key=error.key,
        problem=error.problem,
        fix=error.fix,
        sheet=error.sheet,
        column=error.column or None,
    )


class _SheetLocator:
    """Locates plan lines in the ``HFK Plan`` sheet by row and the Categories column."""

    def __init__(self, rows: dict[int, int]) -> None:
        self.rows = rows

    def name(self, index: int) -> str:
        return f"{PLAN_SHEET} row {self.rows[index]}"

    def terms(self, text: str) -> str:
        return sheet_terms(text)

    def problem(self, index: int, position: int, problem: str, fix: str) -> PlanProblem:
        row = self.rows[index]
        return PlanProblem(
            line=row,
            key=f"sheet={PLAN_SHEET}, row={row}, column=Categories",
            problem=problem,
            fix=fix,
            sheet=PLAN_SHEET,
            column="Categories",
        )


def _duplicate_category_problems(
    good: list[tuple[int, PlanLine]], where: _SheetLocator
) -> list[PlanProblem]:
    rows: dict[tuple[str, str], list[tuple[int, PlanLine]]] = {}
    for index, line in good:
        for category in line.categories:
            rows.setdefault((line.who, category), []).append((index, line))

    problems: list[PlanProblem] = []
    for (who, category), entries in rows.items():
        for left_position, (left_index, left) in enumerate(entries):
            for right_index, right in entries[left_position + 1 :]:
                overlap = _first_overlapping_month(
                    left.effective_from,
                    left.effective_until,
                    right.effective_from,
                    right.effective_until,
                )
                if overlap is None:
                    continue
                problems.append(
                    where.problem(
                        right_index,
                        right.categories.index(category),
                        (
                            f'category "{category}" for "{who}" is also on '
                            f'{where.name(left_index)} ("{left.desc}") '
                            f"with first overlapping month {overlap}"
                        ),
                        where.terms(
                            "end one line with effective_until before the other starts, "
                            "or remove the category from one of them"
                        ),
                    )
                )
    return problems


def _bucket_mapping_problems(
    good: list[tuple[int, PlanLine]],
    declarations: Declarations,
    where: _SheetLocator,
) -> list[PlanProblem]:
    explicit = dict(declarations.categories)
    problems: list[PlanProblem] = []
    for index, line in good:
        for position, category in enumerate(line.categories):
            expected = _declared_buckets(category, declarations, explicit)
            if expected is None or line.bucket in expected:
                continue
            if len(expected) == 1:
                problem = (
                    f'category "{category}" maps to bucket "{expected[0]}" in '
                    f'declarations.yaml but this line is bucket "{line.bucket}"'
                )
            else:
                problem = (
                    f'category "{category}" splits across {", ".join(expected)} in '
                    f'declarations.yaml but this line is bucket "{line.bucket}"'
                )
            problems.append(
                where.problem(
                    index,
                    position,
                    problem,
                    f"move the line to {', '.join(expected)}, or change the "
                    "declarations.yaml override, split, or categories entry",
                )
            )
    return problems


def _declared_buckets(
    category: str, declarations: Declarations, explicit: dict[str, str]
) -> tuple[str, ...] | None:
    """The buckets ``declarations.yaml`` alone assigns, or ``None`` when the ledger is needed."""

    split = declarations.split(category)
    if split is not None:
        return tuple(bucket for bucket, _weight in split.weights)
    override = declarations.override(category)
    if override is not None:
        return (override.bucket,)
    if declarations.mapping_source == "explicit" and category in explicit:
        return (explicit[category],)
    return None


def _first_overlapping_month(
    left_from: Month,
    left_until: Month | None,
    right_from: Month,
    right_until: Month | None,
) -> Month | None:
    start = max(left_from, right_from)
    if left_until is None:
        end = right_until
    elif right_until is None:
        end = left_until
    else:
        end = min(left_until, right_until)
    if end is not None and end < start:
        return None
    return start
