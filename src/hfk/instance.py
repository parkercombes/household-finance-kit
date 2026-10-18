"""Create a private instance skeleton (design brief section 3; roadmap M5-01).

``write_instance`` copies the packaged ``hfk.templates`` files into a new
instance directory: the three example YAML files, a README, a ``.gitignore``,
``shared-items/``, the empty ``data/`` and ``out/`` directories, and the
``.claude/`` wiring (``settings.json`` plus the ``tiller_guard`` hook) that
blocks AI assistants from writing the workbook. With ``git=True`` it also
runs ``git init`` and installs the privacy pre-commit hook. The module never
reads or writes a workbook.
"""

from __future__ import annotations

import importlib.resources
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_INSTANCE_FILES = (
    ("household.yaml", "household.yaml"),
    ("declarations.yaml", "declarations.yaml"),
    ("plan.yaml", "plan.yaml"),
    ("README.md", "README.md"),
    (".gitignore", "gitignore"),
    ("shared-items/README.md", "shared-items-README.md"),
    (".claude/settings.json", "claude-settings.json"),
    (".claude/hooks/tiller_guard.py", "tiller_guard"),
)
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


def write_instance(target: Path, *, git: bool = False) -> InstanceReport:
    """Create a private instance skeleton in ``target`` and report what was written."""

    home = Path(target)
    root = _templates_root()
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
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / template, destination)
        if relative == _GUARD_NAME:
            destination.chmod(0o755)
        created.append(destination)
    for name in _EMPTY_DIRECTORIES:
        directory = home / name
        directory.mkdir(exist_ok=True)
        created.append(directory)

    if git:
        _install_hook(home, root)
    return InstanceReport(home=home, created=tuple(created), git_initialised=git)


def _templates_root() -> Path:
    # hfk ships as a wheel, never zipped, so this Traversable is a plain Path.
    return Path(str(importlib.resources.files("hfk.templates")))


def _require_free_target(home: Path) -> None:
    existing = [
        relative for relative, _template in _INSTANCE_FILES if (home / relative).exists()
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
