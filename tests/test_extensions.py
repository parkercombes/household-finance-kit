"""Extension API (M6): discovery, contract, config sections, and doctor hooks."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from ext_fixture import forget, install_extension

from hfk.ext import ENTRY_POINT_GROUP, discover_extensions

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "hfk"

EXAMPLE_SOURCE = '''
class ExampleExtension:
    name = "example"
    version = "0.1.0"
    contract_version = "1.0.0"
    config_section = None
    schema = None
    requires = {"ledger_fields": ["transactions"], "extensions": []}

    def commands(self):
        return []

    def doctor(self, context, config):
        return []


def extension():
    return ExampleExtension()
'''


@pytest.fixture()
def example_installed(tmp_path, monkeypatch):
    root = install_extension(
        tmp_path / "site",
        module="hfk_example_ext",
        source=EXAMPLE_SOURCE,
        entry_points={"example": "hfk_example_ext:extension"},
    )
    monkeypatch.syspath_prepend(str(root))
    forget("hfk_example_ext")
    yield root
    forget("hfk_example_ext")


def test_entry_point_discovery(example_installed):
    assert "hfk_example_ext" not in sys.modules

    discovery = discover_extensions()

    names = [found.entry_point for found in discovery.extensions]
    assert "example" in names
    found = next(item for item in discovery.extensions if item.entry_point == "example")
    assert found.value == "hfk_example_ext:extension"
    assert type(found.extension).__name__ == "ExampleExtension"
    assert found.extension.name == "example"
    assert discovery.problems == ()
    # The module was imported by entry-point loading, never by a core import.
    assert "hfk_example_ext" in sys.modules


def test_discovery_accepts_a_class_or_an_object(tmp_path, monkeypatch):
    root = install_extension(
        tmp_path / "site",
        module="hfk_shapes_ext",
        source=EXAMPLE_SOURCE + "\nINSTANCE = ExampleExtension()\n",
        entry_points={
            "as-class": "hfk_shapes_ext:ExampleExtension",
            "as-object": "hfk_shapes_ext:INSTANCE",
        },
    )
    monkeypatch.syspath_prepend(str(root))
    forget("hfk_shapes_ext")

    discovery = discover_extensions()

    found = {item.entry_point: item.extension for item in discovery.extensions}
    assert found["as-class"].name == "example"
    assert found["as-object"].name == "example"
    forget("hfk_shapes_ext")


def test_a_broken_entry_point_is_a_problem_not_a_crash(tmp_path, monkeypatch):
    root = install_extension(
        tmp_path / "site",
        module="hfk_broken_ext",
        source="raise RuntimeError('cannot import')\n",
        entry_points={"broken": "hfk_broken_ext:extension"},
    )
    install_extension(
        root,
        module="hfk_example_ext",
        source=EXAMPLE_SOURCE,
        entry_points={"example": "hfk_example_ext:extension"},
    )
    monkeypatch.syspath_prepend(str(root))
    forget("hfk_broken_ext")
    forget("hfk_example_ext")

    discovery = discover_extensions()

    assert [problem.entry_point for problem in discovery.problems] == ["broken"]
    assert "RuntimeError: cannot import" in discovery.problems[0].problem
    assert "example" in [item.entry_point for item in discovery.extensions]
    forget("hfk_broken_ext")
    forget("hfk_example_ext")


def test_entry_point_group_name():
    assert ENTRY_POINT_GROUP == "hfk.extensions"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_core_layers_never_import_the_extension_layer():
    """Source, ledger, config, engine and render sit below hfk.ext and never import it."""

    for layer in ("source", "ledger", "config", "engine", "render"):
        for path in (SRC / layer).rglob("*.py"):
            imported = _imports(path)
            assert not any(name == "hfk.ext" or name.startswith("hfk.ext.") for name in imported), (
                f"{path.relative_to(SRC)} imports the extension layer"
            )
