"""Block agent writes to Tiller workbooks.

Tiller workbooks belong to a paid live service, and saving one with openpyxl can
strip Tiller's charts and VBA. This Claude Code PreToolUse hook permits read-only
inspection while blocking likely writes.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from typing import Any

TILLER_WORKBOOK = re.compile(r"tiller[^/]*\.xls[xm]", re.IGNORECASE)
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def _mentions_tiller_workbook(text: str) -> bool:
    return bool(TILLER_WORKBOOK.search(text))


def _has_write_verb(command: str) -> bool:
    word_patterns = [
        r"\brm\b",
        r"\bunlink\b",
        r"\btruncate\b",
        r"\bshred\b",
    ]
    return (
        ".save(" in command
        or "to_excel" in command
        or "ExcelWriter" in command
        or any(re.search(pattern, command) for pattern in word_patterns)
        or re.search(r"\bsed\s+-i\b", command) is not None
        or re.search(r"\bperl\s+-i\b", command) is not None
    )


def _has_redirect_toward_workbook(command: str) -> bool:
    return re.search(r">>?\s*\S*tiller[^/]*\.xls[xm]", command, re.IGNORECASE) is not None


def _has_destination_write(command: str) -> bool:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    for index, token in enumerate(tokens):
        command_name = token.rsplit("/", 1)[-1]
        if command_name == "mv" and any(_mentions_tiller_workbook(item) for item in tokens[index + 1 :]):
            return True
        if command_name in {"cp", "rsync", "ditto"}:
            operands = [item for item in tokens[index + 1 :] if not item.startswith("-")]
            if operands and _mentions_tiller_workbook(operands[-1]):
                return True
    return False


def _unsafe_load_workbook(command: str) -> bool:
    return (
        "load_workbook(" in command
        and _mentions_tiller_workbook(command)
        and "read_only=True" not in command
    )


def _blocked_reason(tool_name: str, tool_input: dict[str, Any]) -> str | None:
    if tool_name in EDIT_TOOLS:
        file_path = str(tool_input.get("file_path", ""))
        if _mentions_tiller_workbook(file_path):
            return "blocked: Tiller workbooks must not be edited by agents"
        return None

    if tool_name != "Bash":
        return None

    command = str(tool_input.get("command", ""))
    if "# guardrail-ok" in command or not _mentions_tiller_workbook(command):
        return None
    if _unsafe_load_workbook(command):
        return "blocked: use openpyxl.load_workbook(..., read_only=True) for Tiller files"
    if _has_write_verb(command) or _has_redirect_toward_workbook(command) or _has_destination_write(command):
        return "blocked: command appears to write to a Tiller workbook"
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, TypeError, ValueError):
        return 0

    if not isinstance(payload, dict):
        return 0
    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return 0

    reason = _blocked_reason(tool_name, tool_input)
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
