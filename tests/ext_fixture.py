"""Install throwaway extension packages for tests, without pip.

Each package is a module plus a ``*.dist-info`` directory with an
``entry_points.txt`` registering it in the ``hfk.extensions`` group, written to
a temporary directory that the test puts on ``sys.path``. That is all
``importlib.metadata`` needs to find an installed distribution.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path


def install_extension(
    root: Path,
    *,
    module: str,
    source: str,
    entry_points: dict[str, str],
    distribution: str | None = None,
) -> Path:
    """Write ``module.py`` and a dist-info that registers ``entry_points`` under hfk.extensions."""

    root.mkdir(parents=True, exist_ok=True)
    (root / f"{module}.py").write_text(textwrap.dedent(source), encoding="utf-8")
    dist = distribution or module.replace("_", "-")
    info = root / f"{dist.replace('-', '_')}-0.1.0.dist-info"
    info.mkdir(exist_ok=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {dist}\nVersion: 0.1.0\n", encoding="utf-8"
    )
    lines = ["[hfk.extensions]"] + [f"{name} = {target}" for name, target in entry_points.items()]
    (info / "entry_points.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def forget(module: str) -> None:
    sys.modules.pop(module, None)
