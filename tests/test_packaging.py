"""One-line install (M5-12).

Build the wheel, install it into a fresh virtual environment outside the
checkout, and run the commands a new user runs, with no source tree on the
path. The examples are copied into a scratch folder first, so nothing reads
from the checkout once the wheel is built.

These tests need network access to download `openpyxl` and `PyYAML` into the
fresh environment.
"""

from __future__ import annotations

import http.client
import os
import re
import shutil
import signal
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
BIN = "Scripts" if os.name == "nt" else "bin"


def clean_env(**extra: str) -> dict[str, str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in {"PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME", "HFK_HOME"}
    }
    env.update(extra)
    return env


def run(args: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 600):
    return subprocess.run(
        args,
        cwd=cwd,
        env=env or clean_env(),
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> Path:
    dist = tmp_path_factory.mktemp("dist")
    result = run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist), str(ROOT)],
        cwd=dist,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = sorted(dist.glob("household_finance_kit-*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


@pytest.fixture(scope="module")
def installed(tmp_path_factory, wheel) -> Path:
    work = tmp_path_factory.mktemp("fresh")
    venv = work / "venv"
    result = run([sys.executable, "-m", "venv", str(venv)], cwd=work)
    assert result.returncode == 0, result.stderr
    pip = venv / BIN / "python"
    result = run([str(pip), "-m", "pip", "install", "-q", str(wheel)], cwd=work)
    assert result.returncode == 0, result.stdout + result.stderr
    return venv / BIN / "hfk"


@pytest.fixture()
def instance(tmp_path, installed) -> Path:
    home = tmp_path / "instance"
    shutil.copytree(INSTANCE_EXAMPLE, home)
    result = run(
        [str(installed), "dev", "fixture", "--out", str(home / "data" / "Tiller-Example.xlsx")],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    return home


def test_wheel_carries_console_script_and_package_data(wheel):
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        entry_points = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        text = archive.read(entry_points).decode("utf-8")
    assert "[console_scripts]" in text
    assert "hfk = hfk.cli:main" in text
    for name in ("simple.yaml", "four-bucket.yaml", "fifty-thirty-twenty.yaml"):
        assert f"hfk/profiles/{name}" in names
    for name in ("household.yaml", "declarations.yaml", "README.md", "gitignore", "tiller_guard"):
        assert f"hfk/templates/{name}" in names
    assert not any(name.startswith(("tests/", "examples/", "docs/")) for name in names)


def test_installed_version_runs_outside_checkout(installed, tmp_path):
    result = run([str(installed), "--version"], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert re.fullmatch(r"hfk \S+\n", result.stdout)

    where = run(
        [str(installed.parent / "python"), "-c", "import hfk; print(hfk.__file__)"], cwd=tmp_path
    )
    assert where.returncode == 0, where.stderr
    assert not Path(where.stdout.strip()).is_relative_to(ROOT)


def test_installed_doctor_on_example_instance(installed, instance):
    result = run(
        [str(installed), "doctor", "--home", str(instance), "--today", "2026-10-01"],
        cwd=instance.parent,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "doctor: 0 errors" in result.stdout


def test_installed_open_no_browser(installed, instance):
    process = subprocess.Popen(
        [str(installed), "open", "--no-browser", "--home", str(instance), "--today", "2026-09-15"],
        cwd=instance.parent,
        env=clean_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        line = process.stdout.readline()
        match = re.search(r"http://127\.0\.0\.1:(\d+)/", line)
        assert match, line
        connection = http.client.HTTPConnection("127.0.0.1", int(match.group(1)), timeout=30)
        connection.request("GET", "/")
        response = connection.getresponse()
        page = response.read().decode("utf-8")
        connection.close()
        assert response.status == 200
        assert "scorecard 2026-08" in page
        process.send_signal(signal.SIGINT)
        _stdout, stderr = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
    assert process.returncode == 0, stderr


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_uv_tool_install_of_the_wheel(wheel, tmp_path):
    env = clean_env(
        UV_TOOL_DIR=str(tmp_path / "tools"),
        UV_TOOL_BIN_DIR=str(tmp_path / "bin"),
    )
    result = run(["uv", "tool", "install", str(wheel)], cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    version = run([str(tmp_path / "bin" / "hfk"), "--version"], cwd=tmp_path, env=env)
    assert version.returncode == 0, version.stderr
    assert version.stdout.startswith("hfk ")
