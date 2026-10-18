"""`hfk init <dir>` (M5-01): a private instance skeleton with safe examples.

The generated instance must match the design brief's instance layout, parse
identically to the example instance, contain no real data, and work without
`git` on `PATH`. `--git` opts into a fresh repo with the privacy pre-commit
hook installed.
"""

from __future__ import annotations

import importlib.resources
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from hfk.source.fixture import build_fixture

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "tiller_guard.py"
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
PRIVACY_SCAN = ROOT / "scripts" / "privacy_scan.py"
PYTHONPATH = str(ROOT / "src")
GITIGNORE_PATTERNS = (
    "*.xlsx",
    "*.xlsm",
    "*.xls",
    "*.csv",
    "*.tsv",
    "*.pdf",
    "*.numbers",
    "data/",
    "out/",
)
COMMIT_IDENTITY = (
    "-c",
    "user.name=Alex",
    "-c",
    "user.email=alex@example.com",
    "-c",
    "commit.gpgsign=false",
)


def run_hfk(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = PYTHONPATH
    if env is not None:
        environment.update(env)
    return subprocess.run(
        [sys.executable, "-m", "hfk", *args],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def run_git(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("GIT_")
    }
    return subprocess.run(
        ["git", *args],
        cwd=home,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def init_home(tmp_path: Path, name: str = "finances") -> Path:
    home = tmp_path / name
    result = run_hfk("init", str(home))
    assert result.returncode == 0, result.stderr
    return home


def test_init_creates_skeleton(tmp_path: Path) -> None:
    home = tmp_path / "finances"

    result = run_hfk("init", str(home))

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines()[0] == f"created {home}"
    for name in ("household.yaml", "declarations.yaml", "plan.yaml", "README.md", ".gitignore"):
        assert (home / name).is_file(), name
    assert (home / "shared-items" / "README.md").is_file()
    assert (home / "data").is_dir()
    assert (home / "out").is_dir()
    assert list((home / "data").iterdir()) == []
    assert list((home / "out").iterdir()) == []
    assert not (home / ".git").exists()
    assert (home / ".claude" / "settings.json").is_file()
    assert (home / ".claude" / "hooks" / "tiller_guard.py").is_file()

    for name in ("household.yaml", "declarations.yaml", "plan.yaml"):
        assert load_yaml(home / name) == load_yaml(INSTANCE_EXAMPLE / name), name

    assert "plan" not in load_yaml(home / "household.yaml")

    gitignore = (home / ".gitignore").read_text(encoding="utf-8")
    for pattern in GITIGNORE_PATTERNS:
        assert pattern in gitignore, pattern


def test_init_wires_tiller_guard(tmp_path: Path) -> None:
    home = init_home(tmp_path)
    workbook = "Tiller Finance." + ("xls" + "m")

    settings = json.loads(
        (home / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    entry = settings["hooks"]["PreToolUse"][0]
    command = entry["hooks"][0]["command"]
    assert ".claude/hooks/tiller_guard.py" in command
    assert "$CLAUDE_PROJECT_DIR" in command
    assert "Bash" in entry["matcher"]
    assert "Edit" in entry["matcher"]
    assert "Write" in entry["matcher"]

    guard = home / ".claude" / "hooks" / "tiller_guard.py"
    assert guard.read_bytes() == (ROOT / "hooks" / "tiller_guard.py").read_bytes()
    assert os.access(guard, os.X_OK)

    def run_guard(tool_name: str, tool_input: dict[str, Any]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(guard)],
            input=json.dumps({"tool_name": tool_name, "tool_input": tool_input}),
            text=True,
            capture_output=True,
            check=False,
        )

    save = f"python -c \"wb = load_workbook('{workbook}'); wb.save('{workbook}')\""
    blocked_save = run_guard("Bash", {"command": save})
    assert blocked_save.returncode == 2
    assert "blocked" in blocked_save.stderr

    read_only = f"python -c \"load_workbook('{workbook}', read_only=True)\""
    assert run_guard("Bash", {"command": read_only}).returncode == 0

    write = run_guard("Write", {"file_path": "/somewhere/" + workbook})
    assert write.returncode == 2
    assert "blocked" in write.stderr

    assert run_guard("Bash", {"command": "ls -la"}).returncode == 0

    gitignore = (home / ".gitignore").read_text(encoding="utf-8")
    for pattern in GITIGNORE_PATTERNS:
        assert pattern in gitignore, pattern
    assert ".claude/settings.local.json" in gitignore
    lines = {line.strip() for line in gitignore.splitlines()}
    assert ".claude/" not in lines
    assert ".claude" not in lines


def test_packaged_guard_matches_hooks_copy() -> None:
    packaged = importlib.resources.files("hfk.templates") / "tiller_guard"

    assert packaged.read_bytes() == (ROOT / "hooks" / "tiller_guard.py").read_bytes()


def test_init_does_not_write_into_toolkit(tmp_path: Path) -> None:
    home = tmp_path / "finances"

    result = run_hfk("init", str(home))

    assert result.returncode == 0, result.stderr
    assert not (ROOT / ".claude").exists()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        env={
            name: value
            for name, value in os.environ.items()
            if not name.startswith("GIT_")
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert status.returncode == 0
    assert not any(".claude" in line.split()[1:] for line in status.stdout.splitlines())


def test_init_instance_passes_plan_check_and_doctor(tmp_path: Path) -> None:
    home = init_home(tmp_path)

    check = run_hfk("plan", "check", "--home", str(home))

    assert check.returncode == 0
    assert "ok: 9 lines" in check.stdout

    build_fixture(home / "data" / "Tiller-Example.xlsx")

    doctor = run_hfk("doctor", "--home", str(home), "--today", "2026-10-01")

    assert doctor.returncode == 0
    assert "doctor: 0 errors" in doctor.stdout


def test_init_contains_no_real_data(tmp_path: Path) -> None:
    home = init_home(tmp_path)

    scan = subprocess.run(
        [sys.executable, str(PRIVACY_SCAN), "--root", str(home)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert scan.returncode == 0, scan.stdout
    assert "privacy scan clean" in scan.stdout


def test_init_without_git(tmp_path: Path) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    env = {"PATH": str(empty_bin)}
    assert shutil.which("git", path=env["PATH"]) is None

    home = tmp_path / "finances"
    result = run_hfk("init", str(home), env=env)

    assert result.returncode == 0
    assert (home / "household.yaml").is_file()
    assert not (home / ".git").exists()


def test_init_git_flag_without_git_fails_loudly(tmp_path: Path) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    env = {"PATH": str(empty_bin)}
    assert shutil.which("git", path=env["PATH"]) is None

    home = tmp_path / "finances"
    result = run_hfk("init", str(home), "--git", env=env)

    assert result.returncode == 1
    assert "git" in result.stderr
    assert not home.exists() or not any(home.iterdir())


def test_init_refuses_existing_files(tmp_path: Path) -> None:
    home = init_home(tmp_path)

    def snapshot() -> dict[str, bytes]:
        return {
            str(path.relative_to(home)): path.read_bytes()
            for path in sorted(home.rglob("*"))
            if path.is_file()
        }

    before = snapshot()

    result = run_hfk("init", str(home))

    assert result.returncode == 1
    assert "household.yaml" in result.stderr
    assert "choose an empty or new directory" in result.stderr
    assert snapshot() == before


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_init_git_installs_pre_commit_hook(tmp_path: Path) -> None:
    home = tmp_path / "finances"

    result = run_hfk("init", "--git", str(home))

    assert result.returncode == 0
    assert "git: initialised with pre-commit hook" in result.stdout
    assert (home / ".git").is_dir()

    hooks = run_git(home, "rev-parse", "--git-path", "hooks")
    assert hooks.returncode == 0
    hook = home / hooks.stdout.strip()
    assert hook.is_dir()
    pre_commit = hook / "pre-commit"
    assert pre_commit.is_file()
    assert os.access(pre_commit, os.X_OK)

    (home / "statement.csv").write_text("example,statement\n", encoding="utf-8")
    assert run_git(home, "add", "-f", "statement.csv").returncode == 0

    blocked = run_git(home, *COMMIT_IDENTITY, "commit", "-m", "try")

    assert blocked.returncode != 0
    assert "statement.csv" in blocked.stderr

    assert run_git(home, "reset").returncode == 0
    assert (
        run_git(
            home,
            "add",
            "household.yaml",
            "declarations.yaml",
            "plan.yaml",
            "README.md",
            ".gitignore",
        ).returncode
        == 0
    )

    committed = run_git(home, *COMMIT_IDENTITY, "commit", "-m", "instance config")

    assert committed.returncode == 0

    assert run_git(home, "check-ignore", "-q", ".claude/settings.json").returncode != 0
    assert run_git(home, "check-ignore", "-q", ".claude/settings.local.json").returncode == 0

    (home / "data" / "notes.txt").write_text("example\n", encoding="utf-8")
    status = run_git(home, "status", "--porcelain", "--ignored")

    assert status.returncode == 0
    assert any(
        line.startswith("!!") and line.endswith("data/")
        for line in status.stdout.splitlines()
    )
