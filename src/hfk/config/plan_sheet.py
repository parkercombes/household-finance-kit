"""Load the plan from the ``HFK Plan`` workbook sheet (TILLER-SCHEMA; ADR-0013).

The sheet is an optional, user-added tab in the household's own Tiller
workbook. It is read through the source adapter's read-only loader, by header
name and never by column position, and nothing here ever writes a workbook.
Each row becomes the same ``PlanLine`` a ``plan.yaml`` line would: every row is
converted to the mapping a YAML line would hold and validated by the very same
``plan.py`` helper, so the two sources cannot disagree about what is valid.
Problems name the sheet, row, column, and fix.

``load_instance_plan`` is the one entry point commands use: it reads
``plan.yaml`` or the sheet according to ``household.yaml``'s
``plan: {source: file | workbook}``.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from hfk.config.declarations import Declarations
from hfk.config.errors import ConfigError, PlanSheetError
from hfk.config.household import Household
from hfk.config.plan import Month, Plan, PlanLine, _line, load_plan, plan_path
from hfk.source import SheetRows, TillerFormatError, find_workbook, read_optional_sheet

PLAN_SHEET = "HFK Plan"
PLAN_SHEET_SCHEMA_VERSION = 1

# plan.yaml line key -> HFK Plan header, in the documented column order.
COLUMNS = (
    ("desc", "Description"),
    ("who", "Who"),
    ("bucket", "Bucket"),
    ("monthly", "Monthly"),
    ("categories", "Categories"),
    ("paced", "Paced"),
    ("effective_from", "Effective From"),
    ("effective_until", "Effective Until"),
    ("annual_bill", "Annual Bill"),
    ("annual_full", "Annual Full"),
    ("account", "Account"),
    ("due.month", "Due Month"),
    ("due.day", "Due Day"),
)
HEADERS = tuple(header for _key, header in COLUMNS)
REQUIRED_HEADERS = ("Description", "Who", "Bucket", "Monthly", "Effective From")
_COLUMN_FOR_KEY = dict(COLUMNS)
# Key names that plan.py messages mention and that read as keys, not English words;
# replaced as whole words only, so "bucket" or "who" in prose is left alone.
_TERMS = tuple(
    (re.compile(rf"\b{key}\b"), header)
    for key, header in COLUMNS
    if "_" in key or key == "monthly"
)
_ROW_PARENT = "row"


@dataclass(frozen=True)
class SheetLine:
    """One validated sheet row, or the first problem found in it."""

    index: int
    row: int
    line: PlanLine | None
    error: PlanSheetError | None


def load_instance_plan(
    home: Path, *, household: Household, declarations: Declarations
) -> Plan:
    """Load the plan from the source ``household.yaml`` selects."""

    if household.plan_source == "workbook":
        return load_plan_sheet(
            plan_workbook(home, household), declarations=declarations, people=household.slugs
        )
    return load_plan(home, declarations=declarations, people=household.slugs)


def plan_workbook(home: Path, household: Household) -> Path:
    """The workbook whose ``HFK Plan`` sheet holds the plan under ``source: workbook``."""

    try:
        return find_workbook(Path(home) / "data", household.tiller_glob)
    except TillerFormatError as error:
        raise ConfigError(
            f"plan.source is workbook but no workbook was found ({error})",
            file=household.path,
            key="plan.source",
            fix="put the Tiller workbook export in data/, or set plan: {source: file}",
        ) from error


def unused_plan_file(home: Path, household: Household) -> Path | None:
    """``plan.yaml`` when it exists but is ignored because the plan comes from the workbook."""

    path = plan_path(Path(home))
    if household.plan_source == "workbook" and path.exists():
        return path
    return None


def load_plan_sheet(
    workbook: Path, *, declarations: Declarations, people: Iterable[str] | None = None
) -> Plan:
    """Read the ``HFK Plan`` sheet of ``workbook`` into a ``Plan``; the first problem raises."""

    sheet = read_plan_sheet(workbook)
    lines: list[PlanLine] = []
    rows: list[int] = []
    for result in sheet_lines(sheet, declarations=declarations, people=people):
        if result.error is not None:
            raise result.error
        assert result.line is not None
        lines.append(result.line)
        rows.append(result.row)
    return Plan(
        path=sheet.path,
        schema_version=PLAN_SHEET_SCHEMA_VERSION,
        effective_from=min(line.effective_from for line in lines),
        lines=tuple(lines),
        source="workbook",
        line_rows=tuple(rows),
    )


def read_plan_sheet(workbook: Path) -> SheetRows:
    """The raw ``HFK Plan`` sheet, after the sheet-level checks every caller needs."""

    workbook = Path(workbook)
    sheet = read_optional_sheet(workbook, PLAN_SHEET)
    if sheet is None:
        raise PlanSheetError(
            "Missing plan sheet",
            file=workbook,
            sheet=PLAN_SHEET,
            row=0,
            column="",
            fix=(
                f"add a sheet named {PLAN_SHEET} with headers {', '.join(HEADERS)} "
                "in row 1, or set plan: {source: file} in household.yaml"
            ),
        )
    for header in REQUIRED_HEADERS:
        if header not in sheet.headers:
            raise PlanSheetError(
                "Missing required column",
                file=workbook,
                sheet=PLAN_SHEET,
                row=1,
                column=header,
                fix=f"add a {header} header in row 1 of the {PLAN_SHEET} sheet",
            )
    if not sheet.rows:
        raise PlanSheetError(
            "The plan sheet has no plan lines",
            file=workbook,
            sheet=PLAN_SHEET,
            row=2,
            column="",
            fix="add at least one budget line below the header row",
        )
    return sheet


def sheet_lines(
    sheet: SheetRows, *, declarations: Declarations, people: Iterable[str] | None = None
) -> Iterator[SheetLine]:
    """Validate every row independently, yielding a line or the row's first problem."""

    bucket_names = declarations.bucket_names()
    declared_buckets = set(bucket_names)
    people = None if people is None else tuple(people)
    known_people = None if people is None else set(people)
    for index, (row, cells) in enumerate(sheet.rows):
        try:
            entry = _entry(cells, row=row, path=sheet.path)
            try:
                line = _line(
                    entry,
                    plan_effective_from=Month.parse(entry["effective_from"]),
                    bucket_names=bucket_names,
                    declared_buckets=declared_buckets,
                    people=people,
                    known_people=known_people,
                    path=sheet.path,
                    parents=(_ROW_PARENT,),
                )
            except PlanSheetError:
                raise
            except ConfigError as error:
                raise _sheet_error(error, row=row, path=sheet.path) from error
        except PlanSheetError as error:
            yield SheetLine(index=index, row=row, line=None, error=error)
        else:
            yield SheetLine(index=index, row=row, line=line, error=None)


def sheet_terms(text: str) -> str:
    """Rewrite ``plan.yaml`` key names in a message as ``HFK Plan`` column names."""

    for pattern, header in _TERMS:
        text = pattern.sub(header, text)
    return text.replace("remove this key", "clear this cell")


def _sheet_error(error: ConfigError, *, row: int, path: Path) -> PlanSheetError:
    key = error.key
    prefix = _ROW_PARENT + "."
    field = key[len(prefix) :] if key.startswith(prefix) else ""
    field = field.split("[", 1)[0]
    if field == "due":
        field = "due.month"
    return PlanSheetError(
        sheet_terms(error.problem),
        file=path,
        sheet=PLAN_SHEET,
        row=row,
        column=_COLUMN_FOR_KEY.get(field, ""),
        fix=sheet_terms(error.fix),
    )


def _entry(cells: dict[str, Any], *, row: int, path: Path) -> dict[str, Any]:
    """The ``plan.yaml``-shaped mapping for one row; blank optional cells are left out."""

    def fail(column: str, problem: str, fix: str) -> PlanSheetError:
        return PlanSheetError(
            problem, file=path, sheet=PLAN_SHEET, row=row, column=column, fix=fix
        )

    entry: dict[str, Any] = {}
    for key, column in (("desc", "Description"), ("who", "Who"), ("bucket", "Bucket")):
        text = _text(cells.get(column), column, fail)
        if text is None:
            raise fail(column, "Missing value", f"fill in the {column} cell")
        entry[key] = text

    monthly = _money(cells.get("Monthly"), "Monthly", fail)
    if monthly is None:
        raise fail("Monthly", "Missing value", "fill in the Monthly cell with a dollar amount")
    entry["monthly"] = monthly

    categories = _text(cells.get("Categories"), "Categories", fail)
    if categories is not None:
        names = [name.strip() for name in categories.split(";")]
        if any(not name for name in names):
            raise fail(
                "Categories",
                f"Empty category name in {categories!r}",
                "separate Tiller category names with a single ; and no empty entries",
            )
        entry["categories"] = names

    paced = cells.get("Paced")
    paced_text = paced.strip().lower() if isinstance(paced, str) else paced
    if paced_text in (None, ""):
        pass
    elif paced_text in ("yes", "no"):
        entry["paced"] = paced_text == "yes"
    else:
        raise fail("Paced", f"Invalid Paced value {paced!r}", "write yes, no, or leave it blank")

    effective_from = _month(cells.get("Effective From"), "Effective From", fail)
    if effective_from is None:
        raise fail(
            "Effective From",
            "Missing value",
            "fill in the Effective From cell as YYYY-MM; every row needs its own month",
        )
    entry["effective_from"] = effective_from
    effective_until = _month(cells.get("Effective Until"), "Effective Until", fail)
    if effective_until is not None:
        entry["effective_until"] = effective_until

    for key, column in (("annual_bill", "Annual Bill"), ("annual_full", "Annual Full")):
        amount = _money(cells.get(column), column, fail)
        if amount is not None:
            entry[key] = amount

    account = _text(cells.get("Account"), "Account", fail)
    if account is not None:
        entry["account"] = account

    due_month = _integer(cells.get("Due Month"), "Due Month", fail)
    due_day = _integer(cells.get("Due Day"), "Due Day", fail)
    if (due_month is None) != (due_day is None):
        blank = "Due Day" if due_day is None else "Due Month"
        raise fail(blank, "Due Month and Due Day must both be filled or both be blank",
                   f"fill in {blank} or clear the other due cell")
    if due_month is not None:
        entry["due"] = {"month": due_month, "day": due_day}
    return entry


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _text(value: Any, column: str, fail: Any) -> str | None:
    if _blank(value):
        return None
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    raise fail(column, f"Expected text, got {value!r}", f"write {column} as plain text")


def _money(value: Any, column: str, fail: Any) -> Decimal | None:
    if _blank(value):
        return None
    if isinstance(value, bool):
        amount = None
    elif isinstance(value, (int, Decimal)):
        amount = Decimal(value)
    elif isinstance(value, float):
        # str() of a float is its shortest round-trip text, so 33.33 stays 33.33.
        amount = Decimal(str(value))
    elif isinstance(value, str):
        try:
            amount = Decimal(value.strip().replace("$", "").replace(",", ""))
        except InvalidOperation:
            amount = None
    else:
        amount = None
    if amount is None or not amount.is_finite():
        raise fail(
            column,
            f"Expected a dollar amount, got {value!r}",
            f"write {column} as a number with at most two decimal places",
        )
    return amount


def _month(value: Any, column: str, fail: Any) -> str | None:
    """A ``YYYY-MM`` string for ``plan.py``; a date cell contributes its month."""

    if _blank(value):
        return None
    if isinstance(value, (dt.date, dt.datetime)):
        return str(Month(value.year, value.month))
    if isinstance(value, str):
        try:
            return str(Month.parse(value))
        except ValueError:
            pass
    raise fail(column, f"Invalid month {value!r}", f"write {column} as YYYY-MM text or a date")


def _integer(value: Any, column: str, fail: Any) -> int | None:
    if _blank(value):
        return None
    if isinstance(value, bool):
        number = None
    elif isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        number = None
    if number is None:
        raise fail(column, f"Expected a whole number, got {value!r}", f"write {column} as a whole number")
    return number
