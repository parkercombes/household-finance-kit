"""Build the double-click installer ZIP for a GitHub release (M5-22, ADR-0022).

Reads the hfk version from a wheel's file name, computes the wheel's SHA-256,
fills the two installer templates, and writes ``HFK-Installer-<version>.zip``
into ``--out``. The installer holds no logic beyond: get uv, get this release's
hfk, run ``hfk setup``.

Usage::

    python scripts/build_installers.py --wheel PATH --out DIR \
        [--uv-sh-sha256 HEX] [--uv-ps1-sha256 HEX] [--repo-url URL]
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

# Pinned uv version and the SHA-256 digests of its official installers, shipped
# in the ZIP so the installer can detect a tampered or truncated download. To
# update: download uv-installer.sh and uv-installer.ps1 from
# https://github.com/astral-sh/uv/releases/download/<version>/ and run sha256.
UV_VERSION = "0.13.9"
UV_INSTALLER_SH_SHA256 = "ccc888115ac831bd9c30855c1d4abeae32fce679701d2aac8e72eb0beffb41c2"
UV_INSTALLER_PS1_SHA256 = "43b64ed13b8abfcdb3bcfc6ad6a1600dec0849d9e656c18f8ad81305b5d6d4a2"
REPO_URL = "https://github.com/parkercombes/household-finance-kit"

_UNIX_TEMPLATE = "install-unix.sh.in"
_WINDOWS_TEMPLATE = "install-windows.bat.in"
_WHEEL_RE = re.compile(r"^hfk-(?P<version>.+)-py3-none-any\.whl$")
_PLACEHOLDER_RE = re.compile(r"@[A-Z][A-Z0-9_]*@")

# ZIP entry names.
COMMAND_NAME = "Install HFK.command"
SH_NAME = "Install HFK.sh"
BAT_NAME = "Install HFK.bat"


class BuildInstallerError(Exception):
    """A loud, one-line failure with no traceback."""


def _wheel_version(wheel: Path) -> str:
    match = _WHEEL_RE.match(wheel.name)
    if match is None:
        raise BuildInstallerError(f"{wheel.name} is not an hfk wheel (expected hfk-<version>-py3-none-any.whl)")
    return match.group("version")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fill(template: str, mapping: dict[str, str]) -> str:
    text = template
    for placeholder, value in mapping.items():
        text = text.replace(placeholder, value)
    leftover = _PLACEHOLDER_RE.search(text)
    if leftover is not None:
        raise BuildInstallerError(f"unfilled placeholder {leftover.group(0)!r} in rendered installer")
    return text


def _normalize_lf(text: str) -> bytes:
    # Whatever line endings the template holds, the rendered unix files use LF.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")


def _normalize_crlf(text: str) -> bytes:
    # The rendered .bat uses CRLF on every line, including the last.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    text = text.replace("\n", "\r\n")
    return text.encode("utf-8")


def build_installers(
    wheel: Path,
    out: Path,
    *,
    uv_sh_sha256: str = UV_INSTALLER_SH_SHA256,
    uv_ps1_sha256: str = UV_INSTALLER_PS1_SHA256,
    repo_url: str = REPO_URL,
    templates_dir: Path | None = None,
) -> Path:
    """Fill the templates and write ``HFK-Installer-<version>.zip`` into ``out``.

    Returns the path of the ZIP that was written.
    """

    if not wheel.is_file():
        raise BuildInstallerError(f"wheel not found: {wheel}")
    version = _wheel_version(wheel)
    wheel_name = wheel.name
    wheel_sha256 = _sha256(wheel)
    wheel_url = f"{repo_url}/releases/download/v{version}/{wheel_name}"
    uv_sh_url = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-installer.sh"
    uv_ps1_url = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-installer.ps1"

    here = Path(__file__).resolve().parent.parent if templates_dir is None else templates_dir
    unix_template = (here / "installers" / _UNIX_TEMPLATE).read_text(encoding="utf-8")
    windows_template = (here / "installers" / _WINDOWS_TEMPLATE).read_text(encoding="utf-8")

    common = {
        "@HFK_VERSION@": version,
        "@HFK_WHEEL@": wheel_name,
        "@HFK_WHEEL_SHA256@": wheel_sha256,
        "@HFK_WHEEL_URL@": wheel_url,
        "@UV_VERSION@": UV_VERSION,
        "@REPO_URL@": repo_url,
    }
    unix_mapping = {
        **common,
        "@UV_INSTALLER_URL@": uv_sh_url,
        "@UV_INSTALLER_SHA256@": uv_sh_sha256,
    }
    windows_mapping = {
        **common,
        "@UV_INSTALLER_URL@": uv_ps1_url,
        "@UV_INSTALLER_SHA256@": uv_ps1_sha256,
    }

    unix_bytes = _normalize_lf(_fill(unix_template, unix_mapping))
    windows_bytes = _normalize_crlf(_fill(windows_template, windows_mapping))

    out.mkdir(parents=True, exist_ok=True)
    zip_path = out / f"HFK-Installer-{version}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in (
            (COMMAND_NAME, unix_bytes),
            (SH_NAME, unix_bytes),
            (BAT_NAME, windows_bytes),
        ):
            info = zipfile.ZipInfo(name)
            info.create_system = 3  # Unix
            info.external_attr = (0o100755 << 16)
            zf.writestr(info, data)
    return zip_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the hfk installer ZIP for a release.")
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--uv-sh-sha256", default=UV_INSTALLER_SH_SHA256)
    parser.add_argument("--uv-ps1-sha256", default=UV_INSTALLER_PS1_SHA256)
    parser.add_argument("--repo-url", default=REPO_URL)
    args = parser.parse_args(argv)

    try:
        zip_path = build_installers(
            args.wheel,
            args.out,
            uv_sh_sha256=args.uv_sh_sha256,
            uv_ps1_sha256=args.uv_ps1_sha256,
            repo_url=args.repo_url,
        )
    except BuildInstallerError as error:
        print(f"build_installers: {error}", file=sys.stderr)
        return 1
    print(zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
