from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = ROOT / "scripts" / "privacy_scan.py"


def run_scan(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCAN), "--root", str(root)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_clean_tmp_dir_passes(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("noreply@example.com\n", encoding="utf-8")

    result = run_scan(tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() == "privacy scan clean"


def test_findings_include_sensitive_patterns_without_echoing_denylist(tmp_path: Path) -> None:
    account_tail = ("x" * 4) + "1234"
    local = "alex"
    domain = "mail" + "." + "invalid"
    private_term = "private" + "phrase"
    workbook_suffix = "." + ("xl" + "sx")

    (tmp_path / ".privacy-denylist").write_text(private_term + "\n", encoding="utf-8")
    (tmp_path / ("budget" + workbook_suffix)).write_bytes(b"")
    (tmp_path / "leaks.txt").write_text(
        "\n".join([account_tail, local + "@" + domain, "mentions " + private_term]),
        encoding="utf-8",
    )

    result = run_scan(tmp_path)

    assert result.returncode == 1
    assert "account tail pattern" in result.stdout
    assert "disallowed email address" in result.stdout
    assert "blocked private file type" in result.stdout
    assert "<denylist term>" in result.stdout
    assert private_term not in result.stdout
