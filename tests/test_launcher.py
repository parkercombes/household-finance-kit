"""`hfk open` and the double-click launchers (M5-11).

The launchers are exercised on Linux only: the `.command` file is run with
`/bin/sh` against a stand-in `hfk` that records its arguments, and the `.bat`
file is checked line by line. Neither has been double-clicked on a real macOS
or Windows desktop by this suite.
"""

from __future__ import annotations

import http.client
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hfk.source.fixture import build_fixture

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"
PYTHONPATH = str(ROOT / "src")
URL = re.compile(r"http://127\.0\.0\.1:(\d+)/")


def environment(**extra: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH
    env.update(extra)
    return env


def make_instance(tmp_path: Path) -> Path:
    home = tmp_path / "instance"
    home.mkdir()
    for filename in ("household.yaml", "declarations.yaml", "plan.yaml"):
        shutil.copyfile(INSTANCE_EXAMPLE / filename, home / filename)
    build_fixture(home / "data" / "Tiller-Example.xlsx")
    return home


def start_open(home: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "hfk", "open", "--home", str(home), "--today", "2026-09-15", *args],
        env=env or environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def read_url(process: subprocess.Popen[str]) -> tuple[str, int]:
    assert process.stdout is not None
    line = process.stdout.readline()
    match = URL.search(line)
    assert match, line
    return match.group(0), int(match.group(1))


def get(port: int, path: str = "/") -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


@pytest.mark.parametrize("stop", [signal.SIGINT, signal.SIGTERM])
def test_open_no_browser_prints_url_and_exits_zero_when_stopped(tmp_path, stop):
    home = make_instance(tmp_path)
    process = start_open(home, "--no-browser")
    try:
        url, port = read_url(process)
        assert url == f"http://127.0.0.1:{port}/"
        assert port != 0
        assert get(port) == 200
        process.send_signal(stop)
        stdout, stderr = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
    assert process.returncode == 0, stderr
    assert "hfk stopped" in stdout


def test_open_launches_the_browser_on_the_url(tmp_path):
    home = make_instance(tmp_path)
    record = tmp_path / "browser.txt"
    browser = tmp_path / "fake-browser"
    browser.write_text(
        f"#!{sys.executable}\nimport sys\nopen({str(record)!r}, 'w').write(sys.argv[1])\n",
        encoding="utf-8",
    )
    browser.chmod(0o755)
    process = start_open(home, env=environment(BROWSER=f"{browser} %s"))
    try:
        url, _port = read_url(process)
        deadline = time.monotonic() + 30
        while not record.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        process.send_signal(signal.SIGINT)
        process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
    assert record.read_text(encoding="utf-8") == url
    assert process.returncode == 0


def test_open_refuses_missing_instance(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "hfk", "open", "--no-browser", "--home", str(tmp_path / "nope")],
        env=environment(),
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 1
    assert "does not exist" in result.stderr


def init_instance(tmp_path: Path) -> Path:
    home = tmp_path / "My Finances"
    result = subprocess.run(
        [sys.executable, "-m", "hfk", "init", str(home)],
        env=environment(),
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "Open HFK.command" in result.stdout
    return home


def test_init_writes_both_launchers(tmp_path):
    home = init_instance(tmp_path)
    command = home / "Open HFK.command"
    bat = home / "Open HFK.bat"
    assert command.is_file()
    assert bat.is_file()
    assert command.stat().st_mode & stat.S_IXUSR
    assert command.read_bytes().startswith(b"#!/bin/sh\n")
    assert b"\r" not in command.read_bytes()
    raw = bat.read_bytes()
    assert raw.count(b"\r\n") == raw.count(b"\n")


def fake_hfk(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "argv.txt"
    script = bin_dir / "hfk"
    script.write_text(
        f"#!{sys.executable}\nimport sys\n"
        f"open({str(record)!r}, 'w').write('\\n'.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return bin_dir, record


def test_command_launcher_runs_hfk_open_on_its_own_folder(tmp_path):
    home = init_instance(tmp_path)
    bin_dir, record = fake_hfk(tmp_path)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    # Run from somewhere else, then again after moving the folder: the launcher
    # always opens the folder it sits in.
    for move_to in (None, tmp_path / "Moved Finances"):
        folder = home if move_to is None else home.rename(move_to)
        record.unlink(missing_ok=True)
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
            "open",
            "--home",
            str(folder.resolve()),
        ]


def test_bat_launcher_runs_only_hfk_open_on_its_own_folder(tmp_path):
    home = init_instance(tmp_path)
    lines = (home / "Open HFK.bat").read_bytes().decode("utf-8").split("\r\n")
    commands = [
        line
        for line in lines
        if line and not line.lower().startswith("rem ") and line.lower() != "@echo off"
    ]
    # %~dp0 is the folder holding the .bat file; the trailing "." stops its
    # trailing backslash from escaping the closing quote.
    assert commands == ['hfk open --home "%~dp0."', "if errorlevel 1 pause"]
