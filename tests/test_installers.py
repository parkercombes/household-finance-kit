"""Double-click installers for hfk (M5-22, ADR-0022).

The ZIP is built from a stand-in wheel and checked structurally. ``Install HFK.sh``
is then run on this machine against a fake ``curl``, a fake ``uv`` and a fake
``hfk`` that record what was called, so the download/verify/install flow is
exercised without the network. The ``.bat`` is checked statically: this sandbox
is not Windows.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_installers.py"

_spec = importlib.util.spec_from_file_location("build_installers", SCRIPT)
assert _spec is not None and _spec.loader is not None
build_installers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_installers)

WHEEL_NAME = "hfk-0.1.0.dev0-py3-none-any.whl"
VERSION = "0.1.0.dev0"
SH_HAS_RUN = Path("/bin/sh").exists()


def _mktemp_works() -> bool:
    try:
        result = subprocess.run(
            ["mktemp", "-d"], capture_output=True, text=True, timeout=10, check=False
        )
    except OSError:
        return False
    if result.returncode != 0:
        return False
    p = Path(result.stdout.strip())
    try:
        p.rmdir()
    except OSError:
        pass
    return True


MKTEMP_WORKS = _mktemp_works()
RUN_SH = SH_HAS_RUN and MKTEMP_WORKS


def _q(value: str) -> str:
    """Single-quote a string for POSIX sh."""

    return "'" + value.replace("'", "'\\''") + "'"


def make_wheel(path: Path, content: bytes = b"hfk stand-in wheel\n") -> Path:
    """A minimal zip named like an hfk wheel."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("hfk/METADATA", content)
    return path


def build_zip(
    tmp_path: Path,
    *,
    wheel: Path | None = None,
    uv_sh_sha256: str | None = None,
) -> tuple[Path, Path, dict[str, bytes]]:
    """Build the installer ZIP and return (zip_path, wheel, entries)."""

    if wheel is None:
        wheel = make_wheel(tmp_path / WHEEL_NAME)
    out = tmp_path / "out"
    kwargs: dict[str, object] = {}
    if uv_sh_sha256 is not None:
        kwargs["uv_sh_sha256"] = uv_sh_sha256
    zip_path = build_installers.build_installers(wheel, out, **kwargs)  # type: ignore[arg-type]
    with zipfile.ZipFile(zip_path) as zf:
        entries = {info.filename: zf.read(info.filename) for info in zf.infolist()}
    return zip_path, wheel, entries


def make_fakes(tmp_path: Path) -> dict[str, Path]:
    """A fake ``curl``, a fake ``uv-installer.sh``, and a fake ``uv``/``hfk`` pair."""

    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    uv_log = tmp_path / "uv.log"
    hfk_log = tmp_path / "hfk.log"
    bindir = tmp_path / "uvbin"

    curl = fakebin / "curl"
    curl.write_text(
        f"#!{sys.executable}\n"
        "import sys, shutil, os\n"
        "args = sys.argv[1:]\n"
        "dest = None\n"
        "i = 0\n"
        "while i < len(args):\n"
        "    if args[i] == '-o':\n"
        "        dest = args[i + 1]\n"
        "        i += 2\n"
        "        continue\n"
        "    i += 1\n"
        f"src = os.path.join({str(fixtures)!r}, args[-1].rsplit('/', 1)[-1])\n"
        "shutil.copyfile(src, dest)\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)

    fake_uv = (
        "#!/bin/sh\n"
        f"echo \"$*\" >> {_q(str(uv_log))}\n"
        'if [ "$1" = "tool" ] && [ "$2" = "dir" ] && [ "$3" = "--bin" ]; then\n'
        f"    echo {_q(str(bindir))}\n"
        'elif [ "$1" = "tool" ] && [ "$2" = "install" ]; then\n'
        f"    mkdir -p {_q(str(bindir))}\n"
        f"    cat > {_q(str(bindir) + '/hfk')} <<'HFKEOF'\n"
        "#!/bin/sh\n"
        f"printf '%s %s\\n' \"$0\" \"$*\" >> {_q(str(hfk_log))}\n"
        "HFKEOF\n"
        f"    chmod +x {_q(str(bindir) + '/hfk')}\n"
        "fi\n"
    )
    installer = fixtures / "uv-installer.sh"
    installer.write_text(
        "#!/bin/sh\n"
        "mkdir -p \"$UV_INSTALL_DIR\"\n"
        "cat > \"$UV_INSTALL_DIR/uv\" <<'UVEOF'\n"
        + fake_uv
        + "UVEOF\n"
        "chmod +x \"$UV_INSTALL_DIR/uv\"\n",
        encoding="utf-8",
    )
    installer.chmod(0o755)

    return {
        "fakebin": fakebin,
        "fixtures": fixtures,
        "uv_log": uv_log,
        "hfk_log": hfk_log,
        "bindir": bindir,
        "fake_uv": fake_uv,
    }


def run_install_sh(
    sh_path: Path,
    *,
    tmp_path: Path,
    home: Path,
    fakebin: Path,
    fixtures: Path,
    wheel: Path,
) -> subprocess.CompletedProcess[str]:
    """Run an extracted ``Install HFK.sh`` with the fake curl and fixtures wired in."""

    shutil.copyfile(wheel, fixtures / wheel.name)
    home.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": f"{fakebin}{os.pathsep}/usr/bin{os.pathsep}/bin",
        "HOME": str(home),
        "TMPDIR": str(tmp_path),
    }
    return subprocess.run(
        [str(sh_path)],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


# --------------------------------------------------------------------------- #
# Structural tests on the built ZIP.
# --------------------------------------------------------------------------- #


def test_zip_has_exactly_three_root_entries(tmp_path: Path) -> None:
    _zip, _wheel, entries = build_zip(tmp_path)
    assert set(entries) == {"Install HFK.command", "Install HFK.sh", "Install HFK.bat"}


def test_all_entries_are_executable_with_unix_system_and_lf(tmp_path: Path) -> None:
    zip_path, _wheel, _entries = build_zip(tmp_path)
    with zipfile.ZipFile(zip_path) as zf:
        infos = {info.filename: info for info in zf.infolist()}
        unix_bytes = {name: zf.read(name) for name in ("Install HFK.command", "Install HFK.sh")}
        bat_info = infos["Install HFK.bat"]
        bat_bytes = zf.read("Install HFK.bat")
    for name in ("Install HFK.command", "Install HFK.sh"):
        info = infos[name]
        assert info.create_system == 3, name
        assert (info.external_attr >> 16) & 0o777 == 0o755, name
        assert b"\r" not in unix_bytes[name]
    # The .bat carries the same Unix execute mode as the other two (M5-22).
    assert bat_info.create_system == 3
    assert ((bat_info.external_attr >> 16) & 0o777) == 0o755
    # The .bat body still uses CRLF.
    assert b"\r" in bat_bytes


def test_bat_uses_crlf_on_every_line(tmp_path: Path) -> None:
    _zip, _wheel, entries = build_zip(tmp_path)
    bat = entries["Install HFK.bat"]
    assert bat.count(b"\r\n") == bat.count(b"\n")
    assert bat.endswith(b"\r\n")


def test_each_file_names_versions_wheel_url_and_digest(tmp_path: Path) -> None:
    wheel = make_wheel(tmp_path / WHEEL_NAME)
    _zip, _wheel, entries = build_zip(tmp_path, wheel=wheel)
    wheel_sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    wheel_url = (
        f"{build_installers.REPO_URL}/releases/download/v{VERSION}/{WHEEL_NAME}"
    )
    for name, data in entries.items():
        text = data.decode("utf-8")
        assert build_installers.UV_VERSION in text, name
        assert VERSION in text, name
        assert wheel_url in text, name
        assert wheel_sha in text, name


def test_sh_and_command_hold_sh_digest_bat_holds_ps1_digest(tmp_path: Path) -> None:
    _zip, _wheel, entries = build_zip(tmp_path)
    sh_digest = build_installers.UV_INSTALLER_SH_SHA256
    ps1_digest = build_installers.UV_INSTALLER_PS1_SHA256
    for name in ("Install HFK.command", "Install HFK.sh"):
        text = entries[name].decode("utf-8")
        assert sh_digest in text, name
        assert ps1_digest not in text, name
    bat_text = entries["Install HFK.bat"].decode("utf-8")
    assert ps1_digest in bat_text
    assert sh_digest not in bat_text


def test_pinned_constants_are_64_lowercase_hex() -> None:
    hex_re = re.compile(r"^[0-9a-f]{64}$")
    assert hex_re.match(build_installers.UV_INSTALLER_SH_SHA256)
    assert hex_re.match(build_installers.UV_INSTALLER_PS1_SHA256)


def test_missing_wheel_exits_nonzero_without_traceback(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--wheel", tmp_path / "nope.whl", "--out", tmp_path / "out"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert result.stderr.strip().count("\n") == 0
    assert "not an hfk wheel" in result.stderr or "not found" in result.stderr


def test_non_hfk_wheel_name_exits_nonzero_without_traceback(tmp_path: Path) -> None:
    bad = tmp_path / "foo-1.0-py3-none-any.whl"
    make_wheel(bad)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--wheel", bad, "--out", tmp_path / "out"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "not an hfk wheel" in result.stderr


# --------------------------------------------------------------------------- #
# Run tests against the extracted Install HFK.sh.
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not RUN_SH, reason="/bin/sh and mktemp are required")
def test_run_uv_missing_downloads_and_runs_uv_installer(tmp_path: Path) -> None:
    fakes = make_fakes(tmp_path)
    wheel = make_wheel(tmp_path / WHEEL_NAME)
    zip_path, _wheel, _entries = build_zip(
        tmp_path, wheel=wheel, uv_sh_sha256=hashlib.sha256(
            (fakes["fixtures"] / "uv-installer.sh").read_bytes()
        ).hexdigest()
    )
    with zipfile.ZipFile(zip_path) as zf:
        sh_path = tmp_path / "Install HFK.sh"
        sh_path.write_bytes(zf.read("Install HFK.sh"))
        sh_path.chmod(0o755)

    result = run_install_sh(
        sh_path, tmp_path=tmp_path, home=tmp_path / "home", fakebin=fakes["fakebin"],
        fixtures=fakes["fixtures"], wheel=wheel,
    )

    assert result.returncode == 0, result.stderr
    assert "Installing uv" in result.stdout
    # The uv installer was run: it created the fake uv in HOME/.local/bin.
    assert (tmp_path / "home" / ".local" / "bin" / "uv").exists()
    uv_lines = fakes["uv_log"].read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("tool install --force ") for line in uv_lines)
    assert "tool dir --bin" in uv_lines


@pytest.mark.skipif(not RUN_SH, reason="/bin/sh and mktemp are required")
def test_run_uv_present_does_not_download_uv(tmp_path: Path) -> None:
    fakes = make_fakes(tmp_path)
    wheel = make_wheel(tmp_path / WHEEL_NAME)
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "uv").write_text(fakes["fake_uv"], encoding="utf-8")
    (home / ".local" / "bin" / "uv").chmod(0o755)

    zip_path, _wheel, _entries = build_zip(tmp_path, wheel=wheel)
    with zipfile.ZipFile(zip_path) as zf:
        sh_path = tmp_path / "Install HFK.sh"
        sh_path.write_bytes(zf.read("Install HFK.sh"))
        sh_path.chmod(0o755)

    result = run_install_sh(
        sh_path, tmp_path=tmp_path, home=home, fakebin=fakes["fakebin"],
        fixtures=fakes["fixtures"], wheel=wheel,
    )

    assert result.returncode == 0, result.stderr
    assert "Installing uv" not in result.stdout
    assert "Installing hfk" in result.stdout
    lines = fakes["hfk_log"].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert lines[0].endswith(" setup")


@pytest.mark.skipif(not RUN_SH, reason="/bin/sh and mktemp are required")
def test_run_wheel_digest_mismatch_stops_before_install(tmp_path: Path) -> None:
    fakes = make_fakes(tmp_path)
    # The ZIP is built from wheel A; a different wheel B is served by fake curl.
    wheel_a = make_wheel(tmp_path / WHEEL_NAME, b"wheel A\n")
    wheel_b = make_wheel(tmp_path / "other" / WHEEL_NAME, b"wheel B\n")
    (fakes["fixtures"]).mkdir(exist_ok=True)
    shutil.copyfile(wheel_b, fakes["fixtures"] / WHEEL_NAME)

    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "uv").write_text(fakes["fake_uv"], encoding="utf-8")
    (home / ".local" / "bin" / "uv").chmod(0o755)

    zip_path, _wheel, _entries = build_zip(tmp_path, wheel=wheel_a)
    with zipfile.ZipFile(zip_path) as zf:
        sh_path = tmp_path / "Install HFK.sh"
        sh_path.write_bytes(zf.read("Install HFK.sh"))
        sh_path.chmod(0o755)

    env = {
        "PATH": f"{fakes['fakebin']}{os.pathsep}/usr/bin{os.pathsep}/bin",
        "HOME": str(home),
        "TMPDIR": str(tmp_path),
    }
    result = subprocess.run(
        [str(sh_path)], env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, check=False, timeout=60,
    )

    assert result.returncode != 0
    assert "checksum did not match" in result.stderr
    # uv tool install was never called and hfk was never run.
    assert not fakes["uv_log"].exists()
    assert not fakes["hfk_log"].exists()


@pytest.mark.skipif(not RUN_SH, reason="/bin/sh and mktemp are required")
def test_run_uv_installer_digest_mismatch_never_runs_installer(tmp_path: Path) -> None:
    fakes = make_fakes(tmp_path)
    wheel = make_wheel(tmp_path / WHEEL_NAME)
    wrong_digest = "deadbeef" * 8  # 64 hex chars, all letters
    zip_path, _wheel, _entries = build_zip(
        tmp_path, wheel=wheel, uv_sh_sha256=wrong_digest
    )
    with zipfile.ZipFile(zip_path) as zf:
        sh_path = tmp_path / "Install HFK.sh"
        sh_path.write_bytes(zf.read("Install HFK.sh"))
        sh_path.chmod(0o755)

    home = tmp_path / "home"
    result = run_install_sh(
        sh_path, tmp_path=tmp_path, home=home, fakebin=fakes["fakebin"],
        fixtures=fakes["fixtures"], wheel=wheel,
    )

    assert result.returncode != 0
    assert "checksum did not match" in result.stderr
    # The uv installer was never run, so no uv and no hfk.
    assert not (home / ".local" / "bin" / "uv").exists()
    assert not fakes["uv_log"].exists()
    assert not fakes["hfk_log"].exists()


@pytest.mark.skipif(not RUN_SH, reason="/bin/sh and mktemp are required")
def test_run_runs_hfk_setup_once_by_absolute_path(tmp_path: Path) -> None:
    fakes = make_fakes(tmp_path)
    wheel = make_wheel(tmp_path / WHEEL_NAME)
    zip_path, _wheel, _entries = build_zip(
        tmp_path, wheel=wheel, uv_sh_sha256=hashlib.sha256(
            (fakes["fixtures"] / "uv-installer.sh").read_bytes()
        ).hexdigest()
    )
    with zipfile.ZipFile(zip_path) as zf:
        sh_path = tmp_path / "Install HFK.sh"
        sh_path.write_bytes(zf.read("Install HFK.sh"))
        sh_path.chmod(0o755)
    # The installer script itself must invoke hfk by absolute path, not bare name.
    script = sh_path.read_text(encoding="utf-8")
    assert "tool dir --bin)/hfk" in script
    assert re.search(r'"\$hfk" setup', script)

    result = run_install_sh(
        sh_path, tmp_path=tmp_path, home=tmp_path / "home", fakebin=fakes["fakebin"],
        fixtures=fakes["fixtures"], wheel=wheel,
    )

    assert result.returncode == 0, result.stderr
    lines = fakes["hfk_log"].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    invoked, args = lines[0].rsplit(" ", 1)
    assert args == "setup"
    assert invoked.startswith("/")  # absolute path
    assert invoked.endswith("/hfk")


@pytest.mark.skipif(not RUN_SH, reason="/bin/sh and mktemp are required")
def test_run_with_a_home_path_that_has_spaces_apostrophe_and_an_accent(tmp_path: Path) -> None:
    fakes = make_fakes(tmp_path)
    wheel = make_wheel(tmp_path / WHEEL_NAME)
    zip_path, _wheel, _entries = build_zip(
        tmp_path, wheel=wheel, uv_sh_sha256=hashlib.sha256(
            (fakes["fixtures"] / "uv-installer.sh").read_bytes()
        ).hexdigest()
    )
    with zipfile.ZipFile(zip_path) as zf:
        sh_path = tmp_path / "Install HFK.sh"
        sh_path.write_bytes(zf.read("Install HFK.sh"))
        sh_path.chmod(0o755)

    home = tmp_path / "Jos\u00e9's HFK (café)"
    result = run_install_sh(
        sh_path, tmp_path=tmp_path, home=home, fakebin=fakes["fakebin"],
        fixtures=fakes["fixtures"], wheel=wheel,
    )

    assert result.returncode == 0, result.stderr
    lines = fakes["hfk_log"].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert lines[0].endswith(" setup")


# --------------------------------------------------------------------------- #
# Static checks on the rendered .bat (not run: this sandbox is not Windows).
# --------------------------------------------------------------------------- #


def test_bat_has_chcp_getfilehash_tool_dir_and_no_bare_hfk(tmp_path: Path) -> None:
    _zip, _wheel, entries = build_zip(tmp_path)
    bat = entries["Install HFK.bat"].decode("utf-8")
    assert "chcp 65001" in bat
    assert "Get-FileHash" in bat
    assert "tool dir --bin" in bat
    # hfk must be invoked through a variable, not by bare name. Comment lines
    # (`rem ...`) may mention hfk in prose.
    for line in bat.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("rem "):
            continue
        assert not re.search(r"(^|[^$])hfk(\.exe)?\s+setup", line), line
    # No %~dp0 or %~f0 inside a PowerShell -Command string.
    command_match = re.search(r'-Command\s+"(.*)"', bat, re.DOTALL)
    assert command_match is not None
    command = command_match.group(1)
    assert "%~dp0" not in command
    assert "%~f0" not in command


def test_bat_checks_exit_codes_tls_and_progress_and_unix_setup_fails_loudly(
    tmp_path: Path,
) -> None:
    _zip, _wheel, entries = build_zip(tmp_path)
    bat = entries["Install HFK.bat"].decode("utf-8")
    sh = entries["Install HFK.sh"].decode("utf-8")
    # Native programs (uv tool install, hfk setup) do not throw on failure, so
    # the .bat must check $LASTEXITCODE after each of them (at least twice).
    assert bat.count("$LASTEXITCODE") >= 2
    # TLS 1.2 and a silenced progress bar are set before any web request.
    assert "[Net.ServicePointManager]::SecurityProtocol" in bat
    assert "3072" in bat
    assert "$ProgressPreference='SilentlyContinue'" in bat
    # A failed hfk setup must print a message instead of closing silently. The
    # `|| fail` must sit on the same line as `"$hfk" setup` so the line ends in
    # `|| fail "..."` (a backslash continuation would make the line end in `\`).
    assert re.search(r'"\$hfk" setup\s*\|\|\s*fail', sh), sh
    assert "setup did not start" in sh
