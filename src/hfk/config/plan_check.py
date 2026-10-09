"""Validate ``plan.yaml`` for ``hfk plan check`` without stopping at the first problem.

Three rule groups, all checked from ``plan.yaml``, ``household.yaml``, and
``declarations.yaml`` alone — the workbook is never opened and the check
writes nothing, ever:

1. File-level problems stop the check with exactly one problem: a missing or
   unparseable file, a top level that is not a mapping, a bad
   ``schema_version``, an unknown top-level or ``plan`` key, a missing or
   empty ``plan.lines``, or a bad ``plan.effective_from``. Each is the same
   ``ConfigError`` ``load_plan`` raises, so ``plan check`` and ``load_plan``
   never disagree about what is valid.
2. Per-line problems: every ``plan.lines`` entry is validated independently
   with ``load_plan``'s own helpers, reporting the first problem of each bad
   line and continuing, so one run names every bad line at once.
3. Cross-line problems over the lines that passed: one person's category on
   two lines effective in the same month, and a category whose bucket
   ``declarations.yaml`` alone determines (an override, a split, or a
   ``categories`` entry under ``mapping_source: explicit``) sitting on a line
   in a different bucket. Group-mapped categories need the ledger and stay
   with ``hfk doctor``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

from hfk.config._yaml import (
    load_mapping,
    reject_unknown_keys,
    require,
    require_mapping,
    require_schema_version,
)
from hfk.config.declarations import Declarations
from hfk.config.errors import ConfigError, key_path
from hfk.config.plan import (
    PLAN_KEYS,
    TOP_LEVEL_KEYS,
    Month,
    PlanLine,
    _line_entry,
    _plan_rows,
    _require_month,
    plan_path,
)


@dataclass(frozen=True)
class PlanProblem:
    """One ``plan.yaml`` problem: 1-based physical line (0 when unknown), key, fix."""

    line: int
    key: str
    problem: str
    fix: str


@dataclass(frozen=True)
class PlanCheckReport:
    """Every problem found in one ``plan.yaml``; the check itself wrote nothing."""

    path: Path
    problems: tuple[PlanProblem, ...]
    line_count: int

    @property
    def ok(self) -> bool:
        return not self.problems


def check_plan(
    home_or_file: Path,
    *,
    declarations: Declarations,
    people: Iterable[str] | None = None,
) -> PlanCheckReport:
    """Collect every problem in ``plan.yaml`` instead of stopping at the first one."""

    path = Path(home_or_file)
    if path.is_dir():
        path = plan_path(path)
    people = None if people is None else tuple(people)
    bucket_names = declarations.bucket_names()
    text = _read_text(path)

    try:
        data = load_mapping(path)
        reject_unknown_keys(data, TOP_LEVEL_KEYS, path)
        require_schema_version(data, path)
        plan = require_mapping(require(data, "plan", path), path, "plan")
        reject_unknown_keys(plan, PLAN_KEYS, path, "plan")
        effective_from = _require_month(
            require(plan, "effective_from", path, "plan"), path, "plan", "effective_from"
        )
        rows = _plan_rows(require(plan, "lines", path, "plan"), path)
    except ConfigError as error:
        return PlanCheckReport(path=path, problems=(_problem(error, text),), line_count=0)

    problems: list[PlanProblem] = []
    good: list[tuple[int, PlanLine]] = []
    declared_buckets = set(bucket_names)
    known_people = None if people is None else set(people)
    for index, row in enumerate(rows):
        try:
            good.append(
                (
                    index,
                    _line_entry(
                        row,
                        parents=("plan", "lines", f"[{index}]"),
                        plan_effective_from=effective_from,
                        bucket_names=bucket_names,
                        declared_buckets=declared_buckets,
                        people=people,
                        known_people=known_people,
                        path=path,
                    ),
                )
            )
        except ConfigError as error:
            problems.append(_problem(error, text))

    problems.extend(_duplicate_category_problems(good, text))
    problems.extend(_bucket_mapping_problems(good, declarations, text))
    problems.sort(key=lambda problem: problem.line)
    return PlanCheckReport(path=path, problems=tuple(problems), line_count=len(rows))


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _problem(error: ConfigError, text: str | None) -> PlanProblem:
    return PlanProblem(
        line=_key_line(error.key, text),
        key=error.key,
        problem=error.problem,
        fix=error.fix,
    )


def _category_key(index: int, position: int) -> str:
    return key_path("plan", "lines", f"[{index}]", "categories", f"[{position}]")


def _key_line(key: str, text: str | None) -> int:
    """The 1-based physical line of the deepest key in ``key`` that exists in the file."""

    if text is None or key in ("", "(file)"):
        return 0
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return 0
    if not isinstance(root, yaml.MappingNode):
        return 0
    line = 0
    node: yaml.Node = root
    for segment in _key_segments(key):
        if segment.startswith("[") and segment.endswith("]"):
            if not isinstance(node, yaml.SequenceNode):
                break
            try:
                position = int(segment[1:-1])
            except ValueError:
                break
            if not 0 <= position < len(node.value):
                break
            node = node.value[position]
            line = node.start_mark.line + 1
        else:
            if not isinstance(node, yaml.MappingNode):
                break
            child = None
            for key_node, value_node in node.value:
                if isinstance(key_node, yaml.ScalarNode) and key_node.value == _segment_name(
                    segment
                ):
                    child = value_node
                    line = key_node.start_mark.line + 1
                    break
            if child is None:
                break
            node = child
    return line


def _key_segments(key: str) -> list[str]:
    segments: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(key):
        char = key[index]
        if char == ".":
            if current:
                segments.append("".join(current))
                current = []
        elif char == "[":
            if current:
                segments.append("".join(current))
                current = []
            end = key.find("]", index)
            if end < 0:
                break
            segments.append(key[index : end + 1])
            index = end
        else:
            current.append(char)
        index += 1
    if current:
        segments.append("".join(current))
    return segments


def _segment_name(segment: str) -> str:
    if len(segment) >= 2 and segment.startswith('"') and segment.endswith('"'):
        return segment[1:-1]
    return segment


def _duplicate_category_problems(
    good: list[tuple[int, PlanLine]], text: str | None
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
                key = _category_key(right_index, right.categories.index(category))
                problems.append(
                    PlanProblem(
                        line=_key_line(key, text),
                        key=key,
                        problem=(
                            f'category "{category}" for "{who}" is also on '
                            f'plan.lines[{left_index}] ("{left.desc}") '
                            f"with first overlapping month {overlap}"
                        ),
                        fix=(
                            "end one line with effective_until before the other starts, "
                            "or remove the category from one of them"
                        ),
                    )
                )
    return problems


def _bucket_mapping_problems(
    good: list[tuple[int, PlanLine]], declarations: Declarations, text: str | None
) -> list[PlanProblem]:
    explicit = dict(declarations.categories)
    problems: list[PlanProblem] = []
    for index, line in good:
        for position, category in enumerate(line.categories):
            expected = _declared_buckets(category, declarations, explicit)
            if expected is None or line.bucket in expected:
                continue
            key = _category_key(index, position)
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
                PlanProblem(
                    line=_key_line(key, text),
                    key=key,
                    problem=problem,
                    fix=(
                        f"move the line to {', '.join(expected)}, or change the "
                        "declarations.yaml override, split, or categories entry"
                    ),
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
