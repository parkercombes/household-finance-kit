"""Scan the public toolkit repo for files or text that should stay private."""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
from pathlib import Path

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
}

SENSITIVE_SUFFIXES = tuple("." + part for part in ("xl" + "sx", "xl" + "sm", "xl" + "s"))
SENSITIVE_SUFFIXES += tuple("." + part for part in ("cs" + "v", "ts" + "v", "pd" + "f"))
SENSITIVE_SUFFIXES += ("." + "numbers",)


def _patterns() -> tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str]]:
    account_tail = re.compile("x" + "{3,4}" + r"\d{4}", re.IGNORECASE)
    long_digits = re.compile(r"\b\d" + "{9,}" + r"\b")
    email = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
    return account_tail, long_digits, email


def _is_skipped(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(part in SKIP_DIRS or fnmatch.fnmatch(part, "*.egg-info") for part in parts)


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"\0" in handle.read(4096)
    except OSError:
        return True


def _denylist_terms(root: Path) -> list[str]:
    denylist = root / ".privacy-denylist"
    if not denylist.exists():
        return []
    terms: list[str] = []
    for line in denylist.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            terms.append(stripped)
    return terms


def _iter_all_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for current_root, dirnames, filenames in os.walk(root):
        current = Path(current_root)
        dirnames[:] = [
            name
            for name in dirnames
            if not _is_skipped(current / name, root)
            and not fnmatch.fnmatch(name, "*.egg-info")
        ]
        for filename in filenames:
            path = current / filename
            if not _is_skipped(path, root):
                files.append(path)
    return files


def _iter_staged_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        return []
    files = []
    for line in result.stdout.splitlines():
        path = (root / line).resolve()
        if path.exists() and path.is_file() and not _is_skipped(path, root):
            files.append(path)
    return files


def _allowed_email(address: str) -> bool:
    local, _, domain = address.partition("@")
    return local.lower() == "noreply" or domain.lower() in {"example.com", "example.org"}


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def scan(root: Path, staged: bool = False) -> list[str]:
    root = root.resolve()
    account_tail, long_digits, email = _patterns()
    deny_terms = _denylist_terms(root)
    deny_terms_lower = [(term, term.lower()) for term in deny_terms]
    files = _iter_staged_files(root) if staged else _iter_all_files(root)
    findings: list[str] = []

    for path in files:
        label = _display_path(path, root)
        if path.suffix.lower() in SENSITIVE_SUFFIXES:
            findings.append(f"{label}:1: blocked private file type {path.suffix.lower()}")

        if path.name == ".privacy-denylist" or _is_binary(path):
            continue

        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if account_tail.search(line):
                findings.append(f"{label}:{line_number}: account tail pattern")
            if long_digits.search(line):
                findings.append(f"{label}:{line_number}: long digit run")
            for match in email.finditer(line):
                if not _allowed_email(match.group(0)):
                    findings.append(f"{label}:{line_number}: disallowed email address")
            lowered = line.lower()
            for _term, lowered_term in deny_terms_lower:
                if lowered_term in lowered:
                    findings.append(f"{label}:{line_number}: <denylist term>")

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args(argv)

    findings = scan(args.root, args.staged)
    if findings:
        for finding in findings:
            print(finding)
        return 1
    print("privacy scan clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
