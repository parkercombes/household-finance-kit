"""The double-click installers and their ZIP (M5-22, ADR-0022).

``Install HFK.sh`` runs here on Linux against stand-ins: a ``curl`` that serves
files from a folder, a uv installer that writes a stand-in ``uv``, and a ``uv``
that writes a stand-in ``hfk``. ``Install HFK.command`` is the same bytes. The
``.bat`` file is checked line by line; no test here runs it on Windows or
double-clicks anything on macOS.
"""

from __future__ import annotations

import importlib.util
import os
import re
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WHEEL = "household_finance_kit-1.2.3-py3-none-any.whl"
BASE_URL = "https://github.com/example/household-finance-kit"


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_installers", ROOT / "scripts" / "build_installers.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_builder()

FAKE_CURL = r"""#!/bin/sh
out=''
url=''
while [ $# -gt 0 ]; do
    case "$1" in
        --output) out="$2"; shift 2 ;;
        -*) shift ;;
        *) url="$1"; shift ;;
    esac
done
printf 'download %s\n' "$url" >> "$FAKE_LOG"
cp "$FAKE_DOWNLOADS/$(basename "$url")" "$out"
"""

FAKE_UV_INSTALLER = r"""#!/bin/sh
printf 'uv-installer dir=%s no-modify-path=%s\n' "$UV_INSTALL_DIR" "$UV_NO_MODIFY_PATH" \
    >> "$FAKE_LOG"
mkdir -p "$UV_INSTALL_DIR"
cp "$FAKE_UV" "$UV_INSTALL_DIR/uv"
chmod 755 "$UV_INSTALL_DIR/uv"
"""

FAKE_UV = r"""#!/bin/sh
printf 'uv %s\n' "$*" >> "$FAKE_LOG"
if [ "$1 $2 $3" = "tool dir --bin" ]; then
    printf '%s\n' "$FAKE_TOOL_BIN"
elif [ "$1 $2" = "tool install" ]; then
    mkdir -p "$FAKE_TOOL_BIN"
    cp "$FAKE_HFK" "$FAKE_TOOL_BIN/hfk"
    chmod 755 "$FAKE_TOOL_BIN/hfk"
fi
"""

FAKE_HFK = r"""#!/bin/sh
printf 'hfk %s %s\n' "$0" "$*" >> "$FAKE_LOG"
"""

WHEEL_BYTES = b"stand-in wheel for the installer tests\n"


def write_script(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A built ZIP whose digests match the stand-in downloads."""
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / WHEEL).write_bytes(WHEEL_BYTES)
    uv_installer = write_script(downloads / "uv-installer.sh", FAKE_UV_INSTALLER)
    monkeypatch.setattr(
        builder, "UV_INSTALLER_SH_SHA256", builder.sha256_file(uv_installer)
    )
    archive = builder.build_zip(downloads / WHEEL, BASE_URL, tmp_path / "dist")
    return {"zip": archive, "downloads": downloads}


def installer_from(archive: Path, name: str, folder: Path) -> Path:
    with zipfile.ZipFile(archive) as opened:
        info = opened.getinfo(name)
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(opened.read(info))
        target.chmod((info.external_attr >> 16) & 0o777)
    return target


def run_installer(tmp_path: Path, release: dict[str, Path], **extra: str):
    """Run ``Install HFK.sh`` with stand-ins; return (result, log lines, home)."""
    home = tmp_path / "Home Folder é"
    home.mkdir(exist_ok=True)
    stubs = tmp_path / "stubs"
    write_script(stubs / "curl", FAKE_CURL)
    log = tmp_path / "log.txt"
    log.touch()
    installer = installer_from(release["zip"], "Install HFK.sh", tmp_path / "unzipped")
    env = {
        "HOME": str(home),
        "PATH": os.pathsep.join([str(stubs), "/usr/bin", "/bin"]),
        "LANG": "C.UTF-8",
        "FAKE_LOG": str(log),
        "FAKE_DOWNLOADS": str(release["downloads"]),
        "FAKE_UV": str(write_script(tmp_path / "fakes" / "uv", FAKE_UV)),
        "FAKE_HFK": str(write_script(tmp_path / "fakes" / "hfk", FAKE_HFK)),
        "FAKE_TOOL_BIN": str(home / ".local" / "share" / "uv tools bin"),
        **extra,
    }
    result = subprocess.run(
        [str(installer)],
        env=env,
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result, log.read_text(encoding="utf-8").splitlines(), home


# --- The ZIP ---------------------------------------------------------------


def test_zip_holds_three_executable_installers(release):
    with zipfile.ZipFile(release["zip"]) as opened:
        infos = {info.filename: info for info in opened.infolist()}
        assert set(infos) == {"Install HFK.command", "Install HFK.bat", "Install HFK.sh"}
        for info in infos.values():
            mode = info.external_attr >> 16
            assert stat.S_ISREG(mode), info.filename
            assert mode & 0o111 == 0o111, f"{info.filename} is not executable"
        sh = opened.read("Install HFK.sh")
        command = opened.read("Install HFK.command")
        bat = opened.read("Install HFK.bat")
    assert release["zip"].name == "Install-HFK-1.2.3.zip"
    assert command == sh
    assert b"\r" not in sh, "the shell installers must have Unix line endings"
    assert sh.startswith(b"#!/bin/sh\n")
    assert bat.count(b"\n") == bat.count(b"\r\n"), "the .bat must have Windows line endings"
    assert bat.endswith(b"\r\n")


def assignments(text: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    pattern = re.compile(r"^(?:set \")?([A-Z_0-9]+)='?([^'\"\r\n]*)'?\"?\r?$", re.MULTILINE)
    for key, value in pattern.findall(text):
        found.setdefault(key, []).append(value)
    return found


@pytest.mark.parametrize("name", ["Install HFK.sh", "Install HFK.command", "Install HFK.bat"])
def test_each_installer_names_one_version_and_digest_of_each(release, name):
    with zipfile.ZipFile(release["zip"]) as opened:
        text = opened.read(name).decode("ascii")
    values = assignments(text)
    for key in (
        "HFK_VERSION",
        "HFK_WHEEL_URL",
        "HFK_WHEEL_SHA256",
        "UV_VERSION",
        "UV_INSTALLER_URL",
        "UV_INSTALLER_SHA256",
    ):
        assert len(values.get(key, [])) == 1, f"{name} sets {key} {len(values.get(key, []))} times"
    assert values["HFK_VERSION"] == ["1.2.3"]
    assert values["HFK_WHEEL_URL"] == [f"{BASE_URL}/releases/download/v1.2.3/{WHEEL}"]
    assert values["HFK_WHEEL_SHA256"] == [builder.hashlib.sha256(WHEEL_BYTES).hexdigest()]
    assert values["UV_VERSION"] == [builder.UV_VERSION]
    script = "uv-installer.ps1" if name.endswith(".bat") else "uv-installer.sh"
    assert values["UV_INSTALLER_URL"] == [
        f"https://github.com/astral-sh/uv/releases/download/{builder.UV_VERSION}/{script}"
    ]
    expected_uv = (
        builder.UV_INSTALLER_PS1_SHA256 if name.endswith(".bat") else builder.UV_INSTALLER_SH_SHA256
    )
    assert values["UV_INSTALLER_SHA256"] == [expected_uv]
    for digest in (values["HFK_WHEEL_SHA256"][0], values["UV_INSTALLER_SHA256"][0]):
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
    versions = set(re.findall(r"\b\d+\.\d+\.\d+(?:\.dev\d+)?\b", text))
    assert versions == {"1.2.3", builder.UV_VERSION}, f"{name} names other versions: {versions}"


def test_pinned_uv_digests_look_like_sha256():
    assert re.fullmatch(r"\d+\.\d+\.\d+", builder.UV_VERSION)
    for digest in (builder.UV_INSTALLER_SH_SHA256, builder.UV_INSTALLER_PS1_SHA256):
        assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_bat_checks_digests_and_runs_hfk_setup_by_absolute_path(release):
    with zipfile.ZipFile(release["zip"]) as opened:
        lines = opened.read("Install HFK.bat").decode("ascii").split("\r\n")
    joined = "\n".join(lines)
    assert lines[0] == "@echo off"
    assert 'call :check "%WORK%\\uv-installer.ps1" "%UV_INSTALLER_SHA256%"' in lines
    assert 'call :check "%WORK%\\%HFK_WHEEL_NAME%" "%HFK_WHEEL_SHA256%"' in lines
    assert "Get-FileHash -Algorithm SHA256" in joined
    # uv is installed only when neither the usual place nor PATH has it.
    assert lines.index('if exist "%UV%" goto :have_uv') < lines.index(
        'call :download "%UV_INSTALLER_URL%" "%WORK%\\uv-installer.ps1"'
    )
    # The digest check comes before the uv installer or uv tool install runs.
    assert joined.index('"%UV_INSTALLER_SHA256%"') < joined.index("-File \"%WORK%\\uv-installer.ps1\"")
    assert joined.index('"%HFK_WHEEL_SHA256%"') < joined.index('"%UV%" tool install')
    # hfk is run by the folder uv reports, never by name.
    assert "for /f \"delims=\" %%B in ('call \"%UV%\" tool dir --bin') do set \"HFK_BIN=%%B\"" in lines
    assert 'set "HFK=%HFK_BIN%\\hfk.exe"' in lines
    assert '"%HFK%" setup' in lines
    assert not any(re.match(r"\s*hfk(\.exe)?\s", line) for line in lines)
    assert "pause" in lines


def test_build_refuses_a_wheel_it_cannot_name(tmp_path):
    wheel = tmp_path / "something-else-1.0-py3-none-any.whl"
    wheel.write_bytes(b"x")
    with pytest.raises(builder.BuildError, match="not a household_finance_kit"):
        builder.build_zip(wheel, BASE_URL, tmp_path)


def test_build_refuses_a_plain_http_base_url(tmp_path):
    wheel = tmp_path / WHEEL
    wheel.write_bytes(b"x")
    with pytest.raises(builder.BuildError, match="https://"):
        builder.build_zip(wheel, "http://github.com/example/hfk", tmp_path)


# --- Install HFK.sh on Linux -------------------------------------------------


def test_installs_uv_when_missing_then_hfk_then_runs_setup_by_absolute_path(tmp_path, release):
    result, log, home = run_installer(tmp_path, release)
    assert result.returncode == 0, result.stderr
    uv_dir = home / ".local" / "bin"
    tool_bin = home / ".local" / "share" / "uv tools bin"
    assert log[0] == (
        "download https://github.com/astral-sh/uv/releases/download/"
        f"{builder.UV_VERSION}/uv-installer.sh"
    )
    assert log[1] == f"uv-installer dir={uv_dir} no-modify-path=1"
    assert log[2] == f"download {BASE_URL}/releases/download/v1.2.3/{WHEEL}"
    assert log[3] == "uv tool dir --bin"
    assert re.fullmatch(r"uv tool install --force /.+/" + re.escape(WHEEL), log[4])
    assert log[5] == f"hfk {tool_bin}/hfk setup"
    assert len(log) == 6
    assert (uv_dir / "uv").is_file()


def test_uses_uv_already_in_the_usual_place(tmp_path, release):
    home = tmp_path / "Home Folder é"
    write_script(home / ".local" / "bin" / "uv", FAKE_UV)
    result, log, _ = run_installer(tmp_path, release)
    assert result.returncode == 0, result.stderr
    assert not any("uv-installer" in line for line in log)
    assert log[0].endswith(f"/{WHEEL}")
    assert log[-1].endswith("/hfk setup")


def test_uses_uv_already_on_path(tmp_path, release):
    write_script(tmp_path / "stubs" / "uv", FAKE_UV)
    result, log, home = run_installer(tmp_path, release)
    assert result.returncode == 0, result.stderr
    assert not any("uv-installer" in line for line in log)
    assert not (home / ".local" / "bin" / "uv").exists()
    assert log[-1].endswith("/hfk setup")


def test_uv_installer_digest_mismatch_stops_before_installing(tmp_path, release):
    with (release["downloads"] / "uv-installer.sh").open("a", encoding="utf-8") as handle:
        handle.write("echo tampered\n")
    result, log, home = run_installer(tmp_path, release)
    assert result.returncode == 1
    assert "HFK was not installed." in result.stderr
    assert "The downloaded uv installer is not the expected file" in result.stderr
    assert "Traceback" not in result.stderr
    assert len(log) == 1 and log[0].endswith("/uv-installer.sh")
    assert not (home / ".local" / "bin").exists()


def test_hfk_digest_mismatch_stops_before_installing(tmp_path, release):
    (release["downloads"] / WHEEL).write_bytes(WHEEL_BYTES + b"tampered")
    result, log, home = run_installer(tmp_path, release)
    assert result.returncode == 1
    assert "The downloaded HFK is not the expected file, so nothing was installed." in (
        result.stderr
    )
    assert not any(line.startswith("uv tool install") for line in log)
    assert not any(line.startswith("hfk ") for line in log)
    assert not (home / ".local" / "share" / "uv tools bin" / "hfk").exists()


def test_failed_download_stops_with_a_plain_message(tmp_path, release):
    (release["downloads"] / WHEEL).unlink()
    result, log, _ = run_installer(tmp_path, release)
    assert result.returncode == 1
    assert "The download of HFK did not finish." in result.stderr
    assert not any(line.startswith("uv tool install") for line in log)


def test_leaves_no_temporary_files(tmp_path, release):
    temp = tmp_path / "temp"
    temp.mkdir()
    result, _, _ = run_installer(tmp_path, release, TMPDIR=str(temp))
    assert result.returncode == 0, result.stderr
    assert list(temp.iterdir()) == []


def test_hfk_setup_exit_status_is_the_installers(tmp_path, release):
    failing_hfk = FAKE_HFK + "exit 3\n"
    result, _, _ = run_installer(
        tmp_path,
        release,
        FAKE_HFK=str(write_script(tmp_path / "fakes" / "hfk-failing", failing_hfk)),
    )
    assert result.returncode == 3
