from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "tiller_guard.py"
WORKBOOK = "Tiller Finance." + ("xls" + "m")


def run_hook(tool_name: str, tool_input: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_name": tool_name, "tool_input": tool_input}),
        text=True,
        capture_output=True,
        check=False,
    )


def test_save_on_tiller_workbook_blocks() -> None:
    command = f"python -c \"wb = load_workbook('{WORKBOOK}'); wb.save('{WORKBOOK}')\""

    result = run_hook("Bash", {"command": command})

    assert result.returncode == 2
    assert "blocked" in result.stderr


def test_load_workbook_read_only_allowed() -> None:
    command = f"python -c \"load_workbook('{WORKBOOK}', read_only=True)\""

    result = run_hook("Bash", {"command": command})

    assert result.returncode == 0


def test_ls_allowed() -> None:
    result = run_hook("Bash", {"command": "ls"})

    assert result.returncode == 0


def test_write_to_tiller_path_blocks() -> None:
    result = run_hook("Write", {"file_path": "/tmp/" + WORKBOOK})

    assert result.returncode == 2
    assert "blocked" in result.stderr


def test_guardrail_override_allows_bash_command() -> None:
    command = f"python -c \"wb.save('{WORKBOOK}')\" # guardrail-ok"

    result = run_hook("Bash", {"command": command})

    assert result.returncode == 0
