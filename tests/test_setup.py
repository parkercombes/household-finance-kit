"""`hfk setup`: the household's folder, ready for the setup page (M5-20, ADR-0022)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from hfk.instance import (
    InstanceError,
    default_setup_folder,
    start_menu_command,
    write_setup_folder,
)
from hfk.source.fixture import build_fixture

ROOT = Path(__file__).resolve().parents[1]
PYTHONPATH = str(ROOT / "src")
SETUP_FILES = {
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".gitignore",
    "shared-items/README.md",
    ".claude/settings.json",
    ".claude/hooks/tiller_guard.py",
    "Open HFK.command",
    "Open HFK.bat",
}
SETTINGS_FILES = ("household.yaml", "declarations.yaml", "settle_up.yaml")


def run_hfk(
    *args: str, home: Path, cwd: Path = ROOT
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH
    env["HOME"] = str(home)
    env.pop("APPDATA", None)
    return subprocess.run(
        [sys.executable, "-m", "hfk", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


def snapshot(folder: Path) -> dict[str, tuple[str, int]]:
    """Every file under ``folder`` with its content hash and modification time."""

    return {
        str(path.relative_to(folder)): (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
        )
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def files(folder: Path) -> set[str]:
    return {str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file()}


def test_setup_makes_hfk_in_the_home_folder_without_settings(tmp_path: Path) -> None:
    result = run_hfk("setup", "--no-open", home=tmp_path)

    assert result.returncode == 0, result.stderr
    folder = tmp_path / "HFK"
    assert files(folder) == SETUP_FILES
    assert (folder / "data").is_dir() and not any((folder / "data").iterdir())
    assert (folder / "out").is_dir()
    for name in SETTINGS_FILES:
        assert not (folder / name).exists()
    assert f"your hfk folder is {folder}" in result.stdout
    assert f"next: download your Tiller workbook into {folder / 'data'}" in result.stdout
    assert "Google Sheets: File > Download > Microsoft Excel (.xlsx)" in result.stdout
    assert os.access(folder / "Open HFK.command", os.X_OK)


def test_the_default_folder_is_not_documents_or_desktop(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_setup_folder() == tmp_path / "HFK"


def test_running_setup_again_changes_nothing(tmp_path: Path) -> None:
    assert run_hfk("setup", "--no-open", home=tmp_path).returncode == 0
    before = snapshot(tmp_path / "HFK")

    again = run_hfk("setup", "--no-open", home=tmp_path)

    assert again.returncode == 0, again.stderr
    assert "nothing was changed" in again.stdout
    assert snapshot(tmp_path / "HFK") == before


def test_setup_fills_in_only_what_is_missing(tmp_path: Path) -> None:
    folder = tmp_path / "HFK"
    write_setup_folder(folder)
    (folder / "AGENTS.md").write_text("the household's own notes\n", encoding="utf-8")
    (folder / "CLAUDE.md").unlink()

    report = write_setup_folder(folder)

    assert [path.name for path in report.created] == ["CLAUDE.md"]
    assert (folder / "AGENTS.md").read_text(encoding="utf-8") == "the household's own notes\n"


def test_a_folder_already_set_up_is_left_alone(tmp_path: Path) -> None:
    folder = tmp_path / "HFK"
    folder.mkdir()
    (folder / "household.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    (folder / "declarations.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    before = snapshot(folder)

    result = run_hfk("setup", "--no-open", home=tmp_path)

    assert result.returncode == 0, result.stderr
    assert f"{folder} is already set up; nothing was changed" in result.stdout
    assert snapshot(folder) == before


def test_a_partly_set_up_folder_is_a_plain_language_error(tmp_path: Path) -> None:
    folder = tmp_path / "HFK"
    folder.mkdir()
    (folder / "household.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    before = snapshot(folder)

    result = run_hfk("setup", "--no-open", home=tmp_path)

    assert result.returncode == 1
    assert (
        "setup: this folder is only partly set up: it has household.yaml but no "
        "declarations.yaml"
    ) in result.stderr
    assert "fix: put back declarations.yaml from a backup" in result.stderr
    assert "Traceback" not in result.stderr
    assert snapshot(folder) == before


@pytest.mark.parametrize("blocker", ["HFK", "HFK/data"])
def test_a_file_where_a_folder_belongs_is_an_error(tmp_path: Path, blocker: str) -> None:
    (tmp_path / "HFK").mkdir(exist_ok=blocker != "HFK")
    if blocker == "HFK":
        (tmp_path / "HFK").rmdir()
    (tmp_path / blocker).write_text("not a folder\n", encoding="utf-8")

    with pytest.raises(InstanceError, match="is a file"):
        write_setup_folder(tmp_path / "HFK")


def test_init_completes_a_folder_from_setup(tmp_path: Path) -> None:
    folder = tmp_path / "HFK"
    assert run_hfk("setup", "--no-open", home=tmp_path).returncode == 0
    launchers = {name: (folder / name).read_bytes() for name in ("Open HFK.command", "Open HFK.bat")}
    build_fixture(folder / "data" / "Tiller-Example.xlsx")
    answers = tmp_path / "answers.yaml"
    answers.write_text(
        yaml.safe_dump(
            {
                "people": [{"slug": "alex", "name": "Alex"}, {"slug": "sam", "name": "Sam"}],
                "accounts": {
                    "Alex Checking": {"owner": "alex"},
                    "Sam Checking": {"owner": "sam"},
                    "Joint Card": {"shared": {"alex": 0.5, "sam": 0.5}},
                    "Savings": {"owner": "alex"},
                },
                "profile": "four-bucket",
                "groups": {
                    "Housing": "Fixed Essential",
                    "Food": "Variable Essential",
                    "Transportation": "Variable Essential",
                    "Subscriptions": "Fixed Discretionary",
                },
            }
        ),
        encoding="utf-8",
    )

    init = run_hfk("init", str(folder), "--answers", str(answers), home=tmp_path)

    assert init.returncode == 0, init.stderr
    for name in SETTINGS_FILES:
        assert (folder / name).is_file()
    # hfk init never overwrites what hfk setup made.
    assert {name: (folder / name).read_bytes() for name in launchers} == launchers
    doctor = run_hfk("doctor", "--home", str(folder), "--today", "2026-10-01", home=tmp_path)
    assert doctor.returncode == 0, doctor.stdout
    again = run_hfk("setup", "--no-open", home=tmp_path)
    assert f"{folder} is already set up; nothing was changed" in again.stdout


def test_init_still_refuses_a_folder_that_has_settings(tmp_path: Path) -> None:
    folder = tmp_path / "HFK"
    write_setup_folder(folder)
    (folder / "household.yaml").write_text("schema_version: 1\n", encoding="utf-8")

    result = run_hfk("init", str(folder), home=tmp_path)

    assert result.returncode == 1
    assert "already contains household.yaml" in result.stderr


def test_init_before_the_workbook_is_downloaded_writes_no_settings(tmp_path: Path) -> None:
    # Run too early, init used to fill the folder with the example household, and
    # then setup called it set up and init refused it.
    folder = tmp_path / "HFK"
    write_setup_folder(folder)

    result = run_hfk("init", str(folder), home=tmp_path)

    assert result.returncode == 1
    assert "no Tiller workbook" in result.stderr
    assert "File > Download" in result.stderr
    for name in SETTINGS_FILES:
        assert not (folder / name).exists(), name
    again = run_hfk("setup", "--no-open", str(folder), home=tmp_path)
    assert "already set up" not in again.stdout


@pytest.mark.parametrize("from_setup", [True, False])
def test_init_names_a_workbook_it_does_not_recognise(tmp_path: Path, from_setup: bool) -> None:
    folder = tmp_path / "HFK"
    if from_setup:
        write_setup_folder(folder)
    else:
        (folder / "data").mkdir(parents=True)
    build_fixture(folder / "data" / "Budget.xlsx")

    result = run_hfk("init", str(folder), home=tmp_path)

    assert result.returncode == 1
    assert "Budget.xlsx" in result.stderr
    assert "--workbook Budget.xlsx" in result.stderr
    for name in SETTINGS_FILES:
        assert not (folder / name).exists(), name


def test_setup_takes_a_folder_name_relative_to_the_current_folder(tmp_path: Path) -> None:
    result = run_hfk("setup", "--no-open", "My HFK", home=tmp_path, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    folder = tmp_path / "My HFK"
    assert f"your hfk folder is {folder}" in result.stdout
    assert (folder / "Open HFK.command").is_file()


def test_launcher_opens_a_folder_with_spaces_and_accents(tmp_path: Path) -> None:
    record = tmp_path / "argv.txt"
    python = tmp_path / "tools dir" / "python"
    python.parent.mkdir()
    python.write_text(
        f"#!{sys.executable}\nimport sys\n"
        f"open({str(record)!r}, 'w', encoding='utf-8').write('\\n'.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    folder = tmp_path / "Jos\u00e9's Finances (2026)"
    write_setup_folder(folder, python=python)

    env = {**os.environ, "PATH": "/usr/bin:/bin"}
    result = subprocess.run(
        [str(folder / "Open HFK.command")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert record.read_text(encoding="utf-8").split("\n") == [
        "-m",
        "hfk",
        "open",
        "--home",
        str(folder.resolve()),
    ]


def test_start_menu_entry_command_quotes_every_path() -> None:
    home = Path("C:/Users/Jos\u00e9 O'Neil/HFK")
    command = start_menu_command(home, "C:/Users/Jos\u00e9 O'Neil/AppData/Roaming")

    assert command[:4] == ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
    script = command[4]
    # In PowerShell single quotes, a quote is written twice.
    assert "Jos\u00e9 O''Neil" in script
    assert "Open HFK.lnk" in script
    assert f"$s.TargetPath = '{str(home / 'Open HFK.bat').replace(chr(39), chr(39) * 2)}'" in script


def test_setup_is_a_core_command_name() -> None:
    from hfk.ext.contract import CORE_COMMANDS

    assert "setup" in CORE_COMMANDS


def test_a_lone_settle_up_file_is_a_partly_set_up_folder(tmp_path: Path) -> None:
    folder = tmp_path / "HFK"
    folder.mkdir()
    (folder / "settle_up.yaml").write_text("schema_version: 1\n", encoding="utf-8")

    result = run_hfk("setup", "--no-open", home=tmp_path)

    # hfk init would refuse this folder, so hfk setup must not call it ready for init.
    assert result.returncode == 1
    assert (
        "setup: this folder is only partly set up: it has settle_up.yaml but no "
        "household.yaml or declarations.yaml"
    ) in result.stderr
    assert "move settle_up.yaml out of the folder" in result.stderr
    assert files(folder) == {"settle_up.yaml"}
