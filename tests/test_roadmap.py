"""Keep docs/ROADMAP.md internally consistent.

The "Start here when resuming" block names the next item. That line goes
stale the moment a status flips, so this test derives the next item from
the milestone tables and checks the two agree.
"""

from __future__ import annotations

import re
from pathlib import Path

ROADMAP = Path(__file__).resolve().parents[1] / "docs" / "ROADMAP.md"
ROW = re.compile(r"^\| `(M\d+-\d+)` \| .* \| `(todo|doing|done|blocked)` \| (.*?) \| ", re.MULTILINE)
NEXT = re.compile(r"The next item is `(M\d+-\d+)`")


def _items() -> dict[str, tuple[str, tuple[str, ...]]]:
    text = ROADMAP.read_text(encoding="utf-8")
    items: dict[str, tuple[str, tuple[str, ...]]] = {}
    for item_id, status, deps_cell in ROW.findall(text):
        deps = tuple(re.findall(r"`(M\d+-\d+)`", deps_cell))
        items[item_id] = (status, deps)
    return items


def test_roadmap_items_parse_and_dependencies_exist() -> None:
    items = _items()
    assert len(items) > 10
    for item_id, (_status, deps) in items.items():
        for dep in deps:
            assert dep in items, f"{item_id} depends on unknown item {dep}"


def test_start_here_names_first_ready_todo_item() -> None:
    items = _items()
    ready = [
        item_id
        for item_id, (status, deps) in items.items()
        if status == "todo" and all(items[dep][0] == "done" for dep in deps)
    ]
    assert ready, "no todo item has all dependencies done"
    expected = ready[0]

    match = NEXT.search(ROADMAP.read_text(encoding="utf-8"))
    assert match, "ROADMAP.md must say 'The next item is `Mn-NN`'"
    assert match.group(1) == expected, (
        f"ROADMAP.md says next item is {match.group(1)} but the first ready todo item is {expected}"
    )
