"""The one-time ``hfk plan to-sheet`` converter (ADR-0015).

Before ADR-0015 a household's plan could live in ``plan.yaml``. hfk no longer
scores from that file: a ``plan.yaml`` in an instance is an error. This module
is the only code that still reads one. It validates the file with the same
line rules the ``HFK Plan`` sheet uses and turns its lines into sheet rows, so
the household can paste them into the sheet and then delete the file. Every
plan-level default (``plan.effective_from``) is written onto each row, because
a sheet row carries its own ``Effective From``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from hfk.config._yaml import (
    load_mapping,
    reject_unknown_keys,
    require,
    require_list,
    require_mapping,
    require_schema_version,
)
from hfk.config.declarations import Declarations
from hfk.config.errors import ConfigError, key_path
from hfk.config.plan import (
    LINE_KEYS,
    PLAN_FILE,
    Month,
    Plan,
    PlanLine,
    _line,
    _require_month,
)

TOP_LEVEL_KEYS = ("schema_version", "plan")
PLAN_KEYS = ("effective_from", "lines")


def plan_path(home: Path) -> Path:
    return Path(home) / PLAN_FILE


def load_plan_file(
    home_or_file: Path, *, declarations: Declarations, people: Iterable[str] | None = None
) -> Plan:
    """Read a retired ``plan.yaml`` into ``Plan`` lines, for conversion only; never for scoring."""

    path = Path(home_or_file)
    if path.is_dir():
        path = plan_path(path)
    data = load_mapping(path)
    reject_unknown_keys(data, TOP_LEVEL_KEYS, path)

    schema_version = require_schema_version(data, path)
    plan = require_mapping(require(data, "plan", path), path, "plan")
    reject_unknown_keys(plan, PLAN_KEYS, path, "plan")
    effective_from = _require_month(require(plan, "effective_from", path, "plan"), path, "plan", "effective_from")
    bucket_names = declarations.bucket_names()
    lines = _lines(
        require(plan, "lines", path, "plan"),
        plan_effective_from=effective_from,
        bucket_names=bucket_names,
        people=None if people is None else tuple(people),
        path=path,
    )
    return Plan(
        path=path,
        schema_version=schema_version,
        effective_from=effective_from,
        lines=lines,
        source="file",
    )


def _lines(
    value: Any,
    *,
    plan_effective_from: Month,
    bucket_names: tuple[str, ...],
    people: tuple[str, ...] | None,
    path: Path,
) -> tuple[PlanLine, ...]:
    rows = _plan_rows(value, path)
    declared_buckets = set(bucket_names)
    known_people = None if people is None else set(people)
    lines: list[PlanLine] = []
    for index, row in enumerate(rows):
        parents = ("plan", "lines", f"[{index}]")
        lines.append(
            _line_entry(
                row,
                parents=parents,
                plan_effective_from=plan_effective_from,
                bucket_names=bucket_names,
                declared_buckets=declared_buckets,
                people=people,
                known_people=known_people,
                path=path,
            )
        )
    return tuple(lines)


def _plan_rows(value: Any, path: Path) -> list[Any]:
    rows = require_list(value, path, "plan", "lines")
    if not rows:
        raise ConfigError(
            "plan.lines must list at least one line",
            file=path,
            key="plan.lines",
            fix="add at least one budget line",
        )
    return rows


def _line_entry(
    row: Any,
    *,
    parents: tuple[str, ...],
    plan_effective_from: Month,
    bucket_names: tuple[str, ...],
    declared_buckets: set[str],
    people: tuple[str, ...] | None,
    known_people: set[str] | None,
    path: Path,
) -> PlanLine:
    entry = require_mapping(row, path, *parents)
    if "type" in entry:
        raise ConfigError(
            "Plan lines use bucket, not type",
            file=path,
            key=key_path(*parents, "type"),
            fix="rename type to bucket; Type already means Expense/Income/Transfer in Tiller",
        )
    reject_unknown_keys(entry, LINE_KEYS, path, *parents)
    return _line(
        entry,
        plan_effective_from=plan_effective_from,
        bucket_names=bucket_names,
        declared_buckets=declared_buckets,
        people=people,
        known_people=known_people,
        path=path,
        parents=parents,
    )
