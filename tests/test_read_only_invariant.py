"""Static check that the toolkit cannot write a workbook.

The Tiller workbook is an input only (ADR-0001). The agent guard hook in
``hooks/tiller_guard.py`` is a tripwire for sessions; this test is the boundary
for the code itself. Only the synthetic fixture generator may save a workbook.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "hfk"
ALLOWED_WRITERS = {SRC / "source" / "fixture.py"}
WRITE_PATTERNS = (
    re.compile(r"\.save\("),
    re.compile(r"ExcelWriter"),
    re.compile(r"to_excel"),
    re.compile(r"load_workbook\((?![^)]*read_only=True)"),
)


def test_no_module_outside_fixture_can_write_a_workbook() -> None:
    offenders: list[str] = []
    for module in sorted(SRC.rglob("*.py")):
        if module in ALLOWED_WRITERS:
            continue
        for number, line in enumerate(module.read_text().splitlines(), start=1):
            for pattern in WRITE_PATTERNS:
                if pattern.search(line):
                    offenders.append(f"{module.relative_to(SRC.parent)}:{number}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)


def test_fixture_generator_is_the_only_allowed_writer() -> None:
    assert all(path.exists() for path in ALLOWED_WRITERS)
