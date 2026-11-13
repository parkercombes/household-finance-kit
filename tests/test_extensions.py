"""Extension API (M6): discovery, contract, config sections, and doctor hooks."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import ClassVar

import pytest
import yaml
from ext_fixture import forget, install_extension

from hfk.config import ConfigError, Household, load_household
from hfk.ext import (
    ENTRY_POINT_GROUP,
    ContractError,
    ExtensionCommand,
    ReportSection,
    discover_extensions,
    load_enabled_extensions,
    load_extensions,
    validate_extension,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "hfk"
INSTANCE_EXAMPLE = ROOT / "examples" / "instance"

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


class Complete:
    name = "example"
    version = "0.1.0"
    contract_version = "1.2.0"
    config_section = None
    schema = None
    requires: ClassVar[dict] = {"ledger_fields": ["transactions", "balances"], "extensions": []}

    def commands(self):
        return [
            ExtensionCommand(
                name="example-report",
                help="Print the example report.",
                configure=lambda parser: None,
                run=lambda args, context: 0,
            )
        ]

    def report_sections(self):
        return [ReportSection(name="example", title="Example", build=lambda context: None)]

    def doctor(self, context, config):
        return []


def test_extension_contract_validation():
    extension = validate_extension(Complete(), entry_point="example")
    assert extension.name == "example"
    assert extension.contract_version == "1.2.0"
    assert extension.requires.ledger_fields == ("transactions", "balances")
    assert [command.name for command in extension.commands] == ["example-report"]
    assert [section.name for section in extension.report_sections] == ["example"]

    class Incomplete:
        name = "Example Ext"
        contract_version = "2.0.0"
        requires: ClassVar[dict] = {"ledger_fields": ["receipts"], "colour": []}

    with pytest.raises(ContractError) as caught:
        validate_extension(Incomplete(), entry_point="example")
    members = [member for member, _problem, _fix in caught.value.problems]
    assert members == [
        "name",
        "version",
        "contract_version",
        "config_section",
        "schema",
        "requires",
        "requires.ledger_fields",
        "commands",
        "doctor",
    ]
    text = str(caught.value)
    assert text.startswith("extension example breaks the hfk extension contract: ")
    assert "'Example Ext' is not a lowercase identifier" in text
    assert "2.0.0 is not supported; this hfk supports contract 1.x" in text
    assert "'receipts' is not a Ledger field" in text
    assert "unknown keys ['colour']" in text


@pytest.mark.parametrize(
    ("change", "member", "problem"),
    [
        ({"name": "other"}, "name", "differs from the entry-point name"),
        ({"contract_version": "1.0"}, "contract_version", "is not MAJOR.MINOR.PATCH"),
        ({"config_section": "household.yaml", "schema": staticmethod(lambda d, p: d)},
         "config_section", "belongs to core"),
        ({"config_section": "settings"}, "config_section", "is not a YAML file name"),
        ({"config_section": "example.yaml"}, "schema", "missing or not callable"),
        ({"schema": staticmethod(lambda d, p: d)}, "schema", "set while config_section is None"),
        ({"requires": {"ledger_fields": "transactions"}}, "requires.ledger_fields", "not a list"),
        ({"commands": lambda self: [object()]}, "commands", "is not an ExtensionCommand"),
        ({"commands": lambda self: 1 / 0}, "commands", "raised ZeroDivisionError"),
        ({"doctor": None}, "doctor", "missing or not callable"),
        ({"report_sections": lambda self: ["page"]}, "report_sections", "is not a ReportSection"),
    ],
)
def test_each_contract_rule_is_enforced(change, member, problem):
    broken = type("Broken", (Complete,), change)
    with pytest.raises(ContractError) as caught:
        validate_extension(broken(), entry_point="example")
    assert [(m, p) for m, p, _fix in caught.value.problems if m == member and problem in p]


def test_load_extensions_refuses_contract_breaks(tmp_path, monkeypatch):
    root = install_extension(
        tmp_path / "site",
        module="hfk_partial_ext",
        source="class Partial:\n    name = 'partial'\n\nextension = Partial()\n",
        entry_points={"partial": "hfk_partial_ext:extension"},
    )
    install_extension(
        root,
        module="hfk_example_ext",
        source=EXAMPLE_SOURCE,
        entry_points={"example": "hfk_example_ext:extension"},
    )
    monkeypatch.syspath_prepend(str(root))
    forget("hfk_partial_ext")
    forget("hfk_example_ext")

    loaded = load_extensions()

    assert loaded.get("example") is not None
    assert loaded.get("partial") is None
    problem = next(p for p in loaded.problems if p.entry_point == "partial")
    assert "version: missing" in problem.problem
    forget("hfk_partial_ext")
    forget("hfk_example_ext")


def test_the_documented_minimal_extension_passes_the_contract():
    text = (ROOT / "docs" / "EXTENSIONS.md").read_text(encoding="utf-8")
    section = text.split("## A minimal extension", 1)[1]
    code = section.split("```python\n", 1)[1].split("```", 1)[0]
    namespace: dict[str, object] = {}
    exec(compile(code, "EXTENSIONS.md", "exec"), namespace)  # noqa: S102 - the doc's own example

    extension = validate_extension(namespace["extension"](), entry_point="example")

    assert extension.config_section == "example.yaml"
    assert [command.name for command in extension.commands] == ["example"]


def _schema(data, path):
    if not isinstance(data.get("enabled_reason"), str):
        raise ConfigError(
            "enabled_reason must be text",
            file=path,
            key="enabled_reason",
            fix="write one sentence",
        )
    return {"enabled_reason": data["enabled_reason"]}


class Configured(Complete):
    config_section = "example.yaml"
    schema = staticmethod(_schema)


def household_with(tmp_path: Path, extensions: list[str]) -> Household:
    data = yaml.safe_load((INSTANCE_EXAMPLE / "household.yaml").read_text(encoding="utf-8"))
    data["extensions"] = extensions
    path = tmp_path / "household.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return load_household(path)


def test_extension_config_sections(tmp_path):
    installed = (validate_extension(Configured(), entry_point="example"),)
    (tmp_path / "example.yaml").write_text("enabled_reason: [not, text\n", encoding="utf-8")

    # Disabled: the malformed file is never read.
    disabled = household_with(tmp_path, [])
    assert load_enabled_extensions(tmp_path, household=disabled, installed=installed) == ()

    # Enabled and malformed: a loud error naming the file.
    enabled = household_with(tmp_path, ["example"])
    with pytest.raises(ConfigError) as caught:
        load_enabled_extensions(tmp_path, household=enabled, installed=installed)
    assert caught.value.file == tmp_path / "example.yaml"

    (tmp_path / "example.yaml").write_text("enabled_reason: 7\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_enabled_extensions(tmp_path, household=enabled, installed=installed)
    assert (caught.value.key, caught.value.fix) == ("enabled_reason", "write one sentence")

    (tmp_path / "example.yaml").write_text("enabled_reason: we share a card\n", encoding="utf-8")
    loaded = load_enabled_extensions(tmp_path, household=enabled, installed=installed)
    assert [item.extension.name for item in loaded] == ["example"]
    assert loaded[0].config == {"enabled_reason": "we share a card"}

    (tmp_path / "example.yaml").unlink()
    with pytest.raises(ConfigError) as caught:
        load_enabled_extensions(tmp_path, household=enabled, installed=installed)
    assert "config file is missing" in caught.value.problem


def test_enabled_extension_must_be_installed_and_have_its_requirements(tmp_path):
    installed = (validate_extension(Complete(), entry_point="example"),)

    missing = household_with(tmp_path, ["example", "settle_up"])
    with pytest.raises(ConfigError) as caught:
        load_enabled_extensions(tmp_path, household=missing, installed=installed)
    assert caught.value.key == "extensions[1]"
    assert "'settle_up' is enabled but not installed (installed: example)" in caught.value.problem

    needy = type("Needy", (Complete,), {"requires": {"extensions": ["settle_up"]}})
    installed = (validate_extension(needy(), entry_point="example"),)
    alone = household_with(tmp_path, ["example"])
    with pytest.raises(ConfigError, match="requires extension 'settle_up'"):
        load_enabled_extensions(tmp_path, household=alone, installed=installed)


def test_extension_without_config_loads_none(tmp_path):
    installed = (validate_extension(Complete(), entry_point="example"),)
    enabled = household_with(tmp_path, ["example"])
    loaded = load_enabled_extensions(tmp_path, household=enabled, installed=installed)
    assert loaded[0].config is None
