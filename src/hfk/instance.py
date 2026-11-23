"""Create a private instance skeleton (design brief section 3; roadmap M5-01).

``write_instance`` copies the packaged ``hfk.templates`` files into a new
instance directory: the two example YAML files, a README, a ``.gitignore``,
``shared-items/``, the empty ``data/`` and ``out/`` directories, and the
``.claude/`` wiring (``settings.json`` plus the ``tiller_guard`` hook) that
blocks AI assistants from writing the workbook, an ``AGENTS.md`` (with a
``CLAUDE.md`` pointer) that tells assistants never to read it (M5-13), and the two double-click
launchers ``Open HFK.command`` and ``Open HFK.bat`` (M5-11). With ``git=True`` it also
runs ``git init`` and installs the privacy pre-commit hook. The M5-06
interview passes ``documents`` to replace the two YAML files with
interview-rendered text; everything else is copied as before. The module
never reads or writes a workbook.
"""

from __future__ import annotations

import importlib.resources
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_INSTANCE_FILES = (
    ("household.yaml", "household.yaml"),
    ("declarations.yaml", "declarations.yaml"),
    ("README.md", "README.md"),
    ("AGENTS.md", "AGENTS.md"),
    ("CLAUDE.md", "CLAUDE.md"),
    (".gitignore", "gitignore"),
    ("shared-items/README.md", "shared-items-README.md"),
    ("settle_up.yaml", "settle_up.yaml"),
    (".claude/settings.json", "claude-settings.json"),
    (".claude/hooks/tiller_guard.py", "tiller_guard"),
)
# Double-click launchers (M5-11). Each runs ``hfk open`` on the folder it sits
# in, found at run time, so the instance can be moved or renamed. They call hfk
# through the absolute path of the Python that wrote them (ADR-0022): a window
# opened by double-clicking may not have hfk on its PATH yet. If that Python is
# gone, they fall back to ``hfk`` on the PATH. They are written from code, not
# package data, so the Windows file keeps its CRLF line endings whatever git or
# an editor does to the toolkit checkout.
LAUNCHER_COMMAND = "Open HFK.command"
LAUNCHER_BAT = "Open HFK.bat"
_LAUNCHER_NAMES = (LAUNCHER_COMMAND, LAUNCHER_BAT)


def launcher_python() -> Path:
    """The Python running hfk now, which the launchers call by absolute path.

    It is not resolved through symlinks: a tool environment's ``python`` link is
    what puts hfk's packages on the path.
    """

    return Path(sys.executable).absolute()


def _sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _launchers(python: Path) -> tuple[tuple[str, str, str], ...]:
    # In a .bat file, % starts a variable even inside quotes; %% is a literal %.
    bat_python = str(python).replace("%", "%%")
    return (
        (
            LAUNCHER_COMMAND,
            (
                "#!/bin/sh\n"
                "# Double-click to open this folder's hfk reports in your browser.\n"
                "# Close this window, or press Ctrl+C in it, to stop.\n"
                'cd "$(dirname "$0")" || exit 1\n'
                f"HFK_PYTHON={_sh_quote(str(python))}\n"
                'if [ -x "$HFK_PYTHON" ]; then\n'
                '  exec "$HFK_PYTHON" -m hfk open --home "$(pwd)"\n'
                "fi\n"
                'exec hfk open --home "$(pwd)"\n'
            ),
            "\n",
        ),
        (
            LAUNCHER_BAT,
            (
                "@echo off\n"
                "rem Double-click to open this folder's hfk reports in your browser.\n"
                "rem Close this window to stop.\n"
                "rem UTF-8, so folder names with accents work.\n"
                "chcp 65001 >nul\n"
                f'set "HFK_PYTHON={bat_python}"\n'
                'if exist "%HFK_PYTHON%" (\n'
                '  "%HFK_PYTHON%" -m hfk open --home "%~dp0."\n'
                ") else (\n"
                '  hfk open --home "%~dp0."\n'
                ")\n"
                "if errorlevel 1 pause\n"
            ),
            "\r\n",
        ),
    )


_INSTANCE_DOCUMENTS = ("household.yaml", "declarations.yaml")
_STARTER_PLAN = "out/hfk-plan-starter.csv"
_EMPTY_DIRECTORIES = ("data", "out")
_HOOK_NAME = "pre-commit"
_GUARD_NAME = ".claude/hooks/tiller_guard.py"


class InstanceError(Exception):
    """Raised when a private instance cannot be created safely."""

    def __init__(self, problem: str, *, file: Path, fix: str) -> None:
        self.problem = problem
        self.file = file
        self.fix = fix
        super().__init__(f"{problem}: file={file}, fix={fix}")


@dataclass(frozen=True)
class InstanceReport:
    home: Path
    created: tuple[Path, ...]
    git_initialised: bool


def write_instance(
    target: Path,
    *,
    git: bool = False,
    documents: Mapping[str, str] | None = None,
    starter_plan: str | None = None,
    python: Path | None = None,
) -> InstanceReport:
    """Create a private instance skeleton in ``target`` and report what was written.

    ``documents`` replaces the text of the named YAML files (household.yaml,
    declarations.yaml); every other instance file comes from the packaged
    templates as usual. ``starter_plan`` is CSV text for the ``HFK Plan`` sheet,
    written to ``out/hfk-plan-starter.csv`` (gitignored) for the household to
    paste into the workbook; hfk never writes the workbook (ADR-0015).
    """

    home = Path(target)
    root = _templates_root()
    if documents is not None and not set(documents) <= set(_INSTANCE_DOCUMENTS):
        unknown = ", ".join(sorted(set(documents) - set(_INSTANCE_DOCUMENTS)))
        raise InstanceError(
            f"unknown instance documents {unknown}",
            file=home,
            fix="documents keys must be household.yaml or declarations.yaml",
        )
    _require_free_target(home)
    if git and shutil.which("git") is None:
        raise InstanceError(
            "git was not found on PATH",
            file=home,
            fix="install git or run without --git",
        )

    home.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for relative, template in _INSTANCE_FILES:
        destination = home / relative
        if destination.exists():
            continue  # a folder from hfk setup: keep what is there (ADR-0022)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if documents is not None and relative in documents:
            destination.write_text(documents[relative], encoding="utf-8")
        else:
            shutil.copyfile(root / template, destination)
        if relative == _GUARD_NAME:
            destination.chmod(0o755)
        created.append(destination)
    created.extend(_write_launchers(home, python or launcher_python(), keep=True))
    for name in _EMPTY_DIRECTORIES:
        directory = home / name
        directory.mkdir(exist_ok=True)
        created.append(directory)
    if starter_plan is not None:
        destination = home / _STARTER_PLAN
        destination.write_text(starter_plan, encoding="utf-8")
        created.append(destination)

    if git:
        _install_hook(home, root)
    return InstanceReport(home=home, created=tuple(created), git_initialised=git)


def _write_launchers(home: Path, python: Path, *, keep: bool = False) -> list[Path]:
    """Write both launchers; with ``keep``, leave an existing launcher untouched."""

    written: list[Path] = []
    for name, text, newline in _launchers(python):
        destination = home / name
        if keep and destination.exists():
            continue
        with destination.open("w", encoding="utf-8", newline=newline) as handle:
            handle.write(text)
        destination.chmod(0o755)
        written.append(destination)
    return written


# hfk setup (M5-20, ADR-0022): the household's folder, ready for the setup page.
SETUP_FOLDER_NAME = "HFK"
_SETTINGS_FILES = ("household.yaml", "declarations.yaml")
# The settings files come later, from the setup page or hfk init; settle_up.yaml
# belongs with them.
_SETUP_FILES = tuple(
    (relative, template)
    for relative, template in _INSTANCE_FILES
    if relative not in (*_SETTINGS_FILES, "settle_up.yaml")
)


@dataclass(frozen=True)
class SetupReport:
    home: Path
    created: tuple[Path, ...]
    configured: bool  # household.yaml and declarations.yaml were already there


def is_setup_folder(home: Path) -> bool:
    """True when ``home`` holds anything ``hfk setup`` writes besides the empty folders."""

    names = (*(relative for relative, _template in _SETUP_FILES), *_LAUNCHER_NAMES)
    return any((Path(home) / name).exists() for name in names)


def default_setup_folder() -> Path:
    """``HFK`` in the home folder: not Documents or Desktop, which are often synced."""

    return Path.home() / SETUP_FOLDER_NAME


def write_setup_folder(target: Path, *, python: Path | None = None) -> SetupReport:
    """Make the household's folder without its settings files, never overwriting a file.

    A folder that already has both settings files is set up: nothing is written. A
    folder with only one of them is partly set up, which is an error, because
    guessing the other would change numbers. Otherwise every missing piece is
    added, so running this again changes nothing.
    """

    home = Path(target).expanduser()
    if home.exists() and not home.is_dir():
        raise InstanceError(
            f"{home.name} is a file, not a folder",
            file=home,
            fix="choose another folder, or rename that file and run hfk setup again",
        )
    present = [name for name in _SETTINGS_FILES if (home / name).exists()]
    if len(present) == 2:
        return SetupReport(home=home, created=(), configured=True)
    # settle_up.yaml is written with the settings, so alone it is a partial folder too.
    present += ["settle_up.yaml"] if (home / "settle_up.yaml").exists() else []
    if present:
        missing = [name for name in _SETTINGS_FILES if name not in present]
        have = " and ".join(present)
        raise InstanceError(
            f"this folder is only partly set up: it has {have} but no {' or '.join(missing)}",
            file=home,
            fix=(
                f"put back {' and '.join(missing)} from a backup, or move {have} out of "
                "the folder and run hfk setup again to start over"
            ),
        )
    for name in _EMPTY_DIRECTORIES:
        if (home / name).exists() and not (home / name).is_dir():
            raise InstanceError(
                f"{name} in this folder is a file, but hfk needs a folder there",
                file=home / name,
                fix=f"rename the file {name}, then run hfk setup again",
            )

    root = _templates_root()
    home.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for relative, template in _SETUP_FILES:
        destination = home / relative
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / template, destination)
        if relative == _GUARD_NAME:
            destination.chmod(0o755)
        created.append(destination)
    created.extend(_write_launchers(home, python or launcher_python(), keep=True))
    for name in _EMPTY_DIRECTORIES:
        directory = home / name
        if not directory.exists():
            directory.mkdir()
            created.append(directory)
    return SetupReport(home=home, created=tuple(created), configured=False)


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def start_menu_command(home: Path, appdata: str) -> list[str]:
    """The PowerShell command that adds an ``Open HFK`` entry to the Windows Start menu."""

    programs = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    shortcut = programs / "Open HFK.lnk"
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut("
        f"{_ps_quote(str(shortcut))}); "
        f"$s.TargetPath = {_ps_quote(str(home / LAUNCHER_BAT))}; "
        f"$s.WorkingDirectory = {_ps_quote(str(home))}; "
        "$s.Save()"
    )
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]


def _templates_root() -> Path:
    # hfk ships as a wheel, never zipped, so this Traversable is a plain Path.
    return Path(str(importlib.resources.files("hfk.templates")))


def _require_free_target(home: Path) -> None:
    """Refuse a folder that already has settings; any other instance file is kept.

    A folder made by ``hfk setup`` has the launchers and assistant files but no
    settings, and ``hfk init`` completes it (ADR-0022) without overwriting a file.
    """

    existing = [
        name for name in (*_SETTINGS_FILES, "settle_up.yaml") if (home / name).exists()
    ]
    existing += [
        name
        for name in _EMPTY_DIRECTORIES
        if (home / name).exists() and not (home / name).is_dir()
    ]
    if existing:
        raise InstanceError(
            f"instance directory already contains {', '.join(existing)}",
            file=home,
            fix="choose an empty or new directory",
        )


def _install_hook(home: Path, root: Path) -> None:
    init = _git(home, "init", "-q")
    if init.returncode != 0:
        raise InstanceError(
            f"git init failed: {_detail(init)}",
            file=home,
            fix="resolve the git error, or run hfk init without --git",
        )
    hooks = _git(home, "rev-parse", "--git-path", "hooks")
    if hooks.returncode != 0:
        raise InstanceError(
            f"could not locate the git hooks directory: {_detail(hooks)}",
            file=home,
            fix="run git rev-parse --git-path hooks in the instance to see the error",
        )
    hooks_dir = home / hooks.stdout.strip()
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook = hooks_dir / _HOOK_NAME
    if hook.exists():
        raise InstanceError(
            "a pre-commit hook already exists",
            file=hook,
            fix="remove it or point core.hooksPath elsewhere, then rerun hfk init --git",
        )
    shutil.copyfile(root / _HOOK_NAME, hook)
    hook.chmod(0o755)


def _git(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # GIT_* variables from an outer repository would redirect git away from
    # the new instance, so they are dropped for these commands only.
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("GIT_")
    }
    return subprocess.run(
        ["git", *args],
        cwd=home,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _detail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr.strip() or result.stdout.strip() or "no message").splitlines()[0]
