"""Extensions layer: entry-point discovery (M6-01; ADR-0006).

Extensions are installed Python packages that register an object, or a
factory returning one, under the entry-point group ``hfk.extensions``. Core
never imports an extension by name: this module finds them through
``importlib.metadata`` and nothing else. A package that fails to load is
reported as a ``DiscoveryProblem`` naming the entry point; it never stops the
other extensions, or core, from working.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

ENTRY_POINT_GROUP = "hfk.extensions"


@dataclass(frozen=True)
class DiscoveredExtension:
    """One extension object found through an entry point."""

    entry_point: str
    value: str
    extension: Any


@dataclass(frozen=True)
class DiscoveryProblem:
    """An entry point that could not be loaded, and the fix."""

    entry_point: str
    value: str
    problem: str
    fix: str

    def __str__(self) -> str:
        return f"extension entry point {self.entry_point} ({self.value}): {self.problem}; fix={self.fix}"


@dataclass(frozen=True)
class Discovery:
    """Every extension found in the ``hfk.extensions`` group, and every load problem."""

    extensions: tuple[DiscoveredExtension, ...]
    problems: tuple[DiscoveryProblem, ...]


def discover_extensions(
    entry_points: Iterable[importlib.metadata.EntryPoint] | None = None,
) -> Discovery:
    """Load every ``hfk.extensions`` entry point, sorted by entry-point name.

    The entry point's target is the extension object itself, or a callable
    that takes no arguments and returns it. ``entry_points`` replaces the
    installed set, for tests.
    """

    points = (
        importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
        if entry_points is None
        else entry_points
    )
    found: list[DiscoveredExtension] = []
    problems: list[DiscoveryProblem] = []
    for point in sorted(points, key=lambda item: item.name):
        try:
            target = point.load()
            extension = _instantiate(target)
        except Exception as error:  # noqa: BLE001 - one broken package must not stop the rest
            problems.append(
                DiscoveryProblem(
                    entry_point=point.name,
                    value=point.value,
                    problem=f"failed to load: {type(error).__name__}: {error}",
                    fix="reinstall or remove the package that registers this entry point",
                )
            )
            continue
        found.append(DiscoveredExtension(point.name, point.value, extension))
    return Discovery(tuple(found), tuple(problems))


def _instantiate(target: Any) -> Any:
    """A class is instantiated, a factory function is called, an object is used as is."""

    if isinstance(target, type) or (callable(target) and not hasattr(target, "name")):
        return target()
    return target


__all__ = [
    "ENTRY_POINT_GROUP",
    "DiscoveredExtension",
    "Discovery",
    "DiscoveryProblem",
    "discover_extensions",
]
