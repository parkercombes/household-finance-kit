# installers

Build-time templates for the double-click installers shipped in each GitHub
release (roadmap item M5-22, ADR-0022). `scripts/build_installers.py` fills the
`@NAME@` placeholders in these two `.in` files and writes `Install HFK.command`,
`Install HFK.sh` and `Install HFK.bat` into `HFK-Installer-<version>.zip`. Do not
edit the rendered files; edit the templates here and rebuild.

To update the pinned uv version or its installer digests, download
`uv-installer.sh` and `uv-installer.ps1` from
`https://github.com/astral-sh/uv/releases/download/<version>/` and run
`sha256sum` on each, then update the constants in `scripts/build_installers.py`.
