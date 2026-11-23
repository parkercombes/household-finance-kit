"""Build the double-click installer ZIP for one hfk release (M5-22, ADR-0022).

The ZIP holds ``Install HFK.command`` (macOS), ``Install HFK.bat`` (Windows) and
``Install HFK.sh`` (Linux), made from the templates in ``installers/``. Each names
one uv version and one hfk version, with a SHA-256 digest for each download, so a
release's installers cannot install anything else.

Usage, after building the wheel that the release will attach::

    python scripts/build_installers.py --wheel dist/<wheel> \\
        --base-url https://github.com/<owner>/<repo> --out dist

The wheel's URL is ``<base-url>/releases/download/v<version>/<wheel name>``, so
the release must be tagged ``v<version>`` and carry that exact wheel file.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "installers"

# The uv release the installers install when uv is missing, and the SHA-256
# digests of that release's installer scripts, from
# https://github.com/astral-sh/uv/releases/download/<UV_VERSION>/uv-installer.sh
# and .../uv-installer.ps1. Change all three together, after downloading both
# files and checking their digests; each uv installer then checks the digest of
# the uv binary it downloads.
UV_VERSION = "0.11.32"
UV_INSTALLER_SH_SHA256 = "43aff33a967fe40e8c17949d8c85c65bc43f3b5c94742393c957f56ab5ba80f4"
UV_INSTALLER_PS1_SHA256 = "d84b0d973693497f8c1c1d82b2d2f52e32e50c7c24efa3d925341bd6fc5238b2"

# Published name -> (template, line ending).
INSTALLERS = {
    "Install HFK.command": ("install.sh.in", "\n"),
    "Install HFK.sh": ("install.sh.in", "\n"),
    "Install HFK.bat": ("install.bat.in", "\r\n"),
}

WHEEL_NAME = re.compile(r"^household_finance_kit-(?P<version>[^-]+)-py3-none-any\.whl$")
PLACEHOLDER = re.compile(r"@[A-Z0-9_]+@")
SAFE_VALUE = re.compile(r"^[A-Za-z0-9._:/+-]+$")
# rw-r--r-- plus execute for everyone, as a regular file, in the ZIP's Unix field.
EXECUTABLE = (0o100755 << 16)


class BuildError(Exception):
    """A loud, specific reason the installers were not built."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def wheel_version(wheel: Path) -> str:
    match = WHEEL_NAME.match(wheel.name)
    if match is None:
        raise BuildError(
            f"{wheel.name} is not a household_finance_kit pure-Python wheel; "
            "build it with `python -m build --wheel`"
        )
    return match["version"]


def installer_values(wheel: Path, base_url: str) -> dict[str, str]:
    """Every value the templates name, checked so none can break a script's quoting."""
    base_url = base_url.rstrip("/")
    if not base_url.startswith("https://"):
        raise BuildError(f"--base-url must start with https://, got {base_url!r}")
    version = wheel_version(wheel)
    values = {
        "HFK_VERSION": version,
        "HFK_WHEEL_NAME": wheel.name,
        "HFK_WHEEL_URL": f"{base_url}/releases/download/v{version}/{wheel.name}",
        "HFK_WHEEL_SHA256": sha256_file(wheel),
        "HFK_PROJECT_URL": base_url,
        "UV_VERSION": UV_VERSION,
    }
    for key, value in values.items():
        if not SAFE_VALUE.match(value):
            raise BuildError(f"{key} has a character the installers cannot quote: {value!r}")
    return values


def render(template: str, values: dict[str, str], line_ending: str) -> bytes:
    text = (TEMPLATES / template).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace(f"@{key}@", value)
    left = sorted(set(PLACEHOLDER.findall(text)))
    if left:
        raise BuildError(f"installers/{template} has unfilled placeholders: {', '.join(left)}")
    if not text.isascii():
        raise BuildError(f"installers/{template} must be ASCII so every shell reads it the same")
    return text.replace("\r\n", "\n").replace("\n", line_ending).encode("ascii")


def render_all(wheel: Path, base_url: str) -> dict[str, bytes]:
    """The three installers, keyed by their published file names."""
    values = installer_values(wheel, base_url)
    rendered = {}
    for name, (template, line_ending) in INSTALLERS.items():
        uv_digest = UV_INSTALLER_PS1_SHA256 if template.endswith(".bat.in") else (
            UV_INSTALLER_SH_SHA256
        )
        rendered[name] = render(
            template, {**values, "UV_INSTALLER_SHA256": uv_digest}, line_ending
        )
    return rendered


def build_zip(wheel: Path, base_url: str, out_dir: Path) -> Path:
    """Write ``Install-HFK-<version>.zip`` into ``out_dir`` and return its path."""
    rendered = render_all(wheel, base_url)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"Install-HFK-{wheel_version(wheel)}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in rendered.items():
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.create_system = 3  # Unix, so unzip tools honour the mode bits.
            info.external_attr = EXECUTABLE
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wheel", required=True, type=Path, help="The release's hfk wheel.")
    parser.add_argument(
        "--base-url",
        required=True,
        help="The project's GitHub address, such as https://github.com/<owner>/<repo>.",
    )
    parser.add_argument("--out", required=True, type=Path, help="Folder for the ZIP.")
    args = parser.parse_args(argv)
    if not args.wheel.is_file():
        print(f"build_installers: no wheel at {args.wheel}", file=sys.stderr)
        return 1
    try:
        target = build_zip(args.wheel, args.base_url, args.out)
    except BuildError as error:
        print(f"build_installers: {error}", file=sys.stderr)
        return 1
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
