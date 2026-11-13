"""The extension object contract (M6-02; ADR-0006; docs/EXTENSIONS.md).

``validate_extension`` checks a discovered object member by member and returns
a frozen ``Extension`` that core uses from then on. Every problem found is
collected, so one ``ContractError`` names everything an extension author must
fix. Core never calls a member it has not validated.

Members:

- ``name``: lowercase identifier, equal to the entry-point name; the value a
  household lists under ``extensions`` in ``household.yaml``.
- ``version``: the package's own version text.
- ``contract_version``: ``MAJOR.MINOR.PATCH``; hfk supports major version 1.
- ``config_section``: ``None``, or the file name of the extension's own input
  file in the instance, such as ``retirement.yaml`` (M6-03).
- ``schema``: a callable ``schema(data, path)`` that validates the loaded
  mapping and returns the extension's config object, raising ``ConfigError``;
  required exactly when ``config_section`` is set.
- ``requires``: a mapping with optional ``ledger_fields`` (``Ledger`` field
  names) and ``extensions`` (other extension names).
- ``commands()``: returns ``ExtensionCommand`` objects.
- ``report_sections()``: optional; returns ``ReportSection`` objects.
- ``doctor``: a callable ``doctor(context, config)`` returning ``Diagnostic``
  objects (M6-04).
"""

from __future__ import annotations

import argparse
import dataclasses
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from hfk.config import Declarations, Household
from hfk.config.household import SLUG
from hfk.ledger import Ledger

CONTRACT_MAJOR = 1
SUPPORTED_CONTRACT = f"{CONTRACT_MAJOR}.x"
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
COMMAND_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
CORE_FILES = frozenset({"household.yaml", "declarations.yaml", "plan.yaml"})
# Core subcommands an extension may not replace. ``settle`` and ``retirement``
# are not listed: they are stubs reserved for the settle_up and retirement extensions.
CORE_COMMANDS = frozenset(
    {
        "balances",
        "categories",
        "dev",
        "doctor",
        "init",
        "networth",
        "open",
        "plan",
        "rebaseline",
        "renewals",
        "scorecard",
        "serve",
    }
)
REQUIRES_KEYS = ("ledger_fields", "extensions")
LEDGER_FIELDS = tuple(field.name for field in dataclasses.fields(Ledger))


@dataclass(frozen=True)
class ExtensionCommand:
    """One CLI subcommand an extension contributes.

    ``configure(parser)`` adds the command's own arguments; ``run(args,
    context)`` does the work and returns the exit code.
    """

    name: str
    help: str
    configure: Callable[[argparse.ArgumentParser], None]
    run: Callable[[argparse.Namespace, Any], int]


@dataclass(frozen=True)
class CommandContext:
    """What an extension command's ``run(args, context)`` receives from core.

    ``config`` is the extension's validated config (``None`` when it has none).
    ``load_ledger()`` reads the instance's workbook read-only on first call.
    """

    home: Path
    household: Household
    declarations: Declarations
    config: object
    today: date
    load_ledger: Callable[[], Ledger]


@dataclass(frozen=True)
class ReportSection:
    """One report an extension can add to a page; ``build(context)`` returns a report object."""

    name: str
    title: str
    build: Callable[[Any], object]


@dataclass(frozen=True)
class Requirements:
    ledger_fields: tuple[str, ...]
    extensions: tuple[str, ...]


@dataclass(frozen=True)
class Extension:
    """A discovered extension object that passed every contract check."""

    name: str
    version: str
    contract_version: str
    config_section: str | None
    schema: Callable[[Any, Any], object] | None
    requires: Requirements
    commands: tuple[ExtensionCommand, ...]
    report_sections: tuple[ReportSection, ...]
    doctor: Callable[[Any, object], object]
    entry_point: str
    obj: Any = dataclasses.field(compare=False, repr=False)


class ContractError(ValueError):
    """An extension object that breaks the contract; ``problems`` lists every break."""

    def __init__(self, entry_point: str, problems: tuple[tuple[str, str, str], ...]) -> None:
        self.entry_point = entry_point
        self.problems = problems
        text = "; ".join(f"{member}: {problem} (fix: {fix})" for member, problem, fix in problems)
        super().__init__(f"extension {entry_point} breaks the hfk extension contract: {text}")


def validate_extension(obj: Any, *, entry_point: str) -> Extension:
    """Check ``obj`` against the contract; raise one ``ContractError`` naming every problem."""

    problems: list[tuple[str, str, str]] = []

    def fail(member: str, problem: str, fix: str) -> None:
        problems.append((member, problem, fix))

    name = _text(obj, "name", fail)
    if name is not None:
        if not SLUG.match(name):
            fail("name", f"{name!r} is not a lowercase identifier", "use a name such as settle_up")
        elif name != entry_point:
            fail(
                "name",
                f"{name!r} differs from the entry-point name {entry_point!r}",
                "register the entry point under the extension's name",
            )
    version = _text(obj, "version", fail)
    contract_version = _contract_version(obj, fail)
    config_section, schema = _config_section(obj, fail)
    requires = _requires(obj, fail)
    commands = _commands(obj, fail)
    report_sections = _report_sections(obj, fail)
    doctor = getattr(obj, "doctor", None)
    if not callable(doctor):
        fail("doctor", "missing or not callable", "define doctor(context, config) returning diagnostics")

    if problems:
        raise ContractError(entry_point, tuple(problems))
    assert name is not None and version is not None and contract_version is not None
    assert requires is not None and commands is not None and report_sections is not None
    return Extension(
        name=name,
        version=version,
        contract_version=contract_version,
        config_section=config_section,
        schema=schema,
        requires=requires,
        commands=commands,
        report_sections=report_sections,
        doctor=doctor,
        entry_point=entry_point,
        obj=obj,
    )


def _text(obj: Any, member: str, fail: Callable[[str, str, str], None]) -> str | None:
    if not hasattr(obj, member):
        fail(member, "missing", f"set {member} to a non-empty string")
        return None
    value = getattr(obj, member)
    if not isinstance(value, str) or not value.strip():
        fail(member, f"{value!r} is not a non-empty string", f"set {member} to a non-empty string")
        return None
    return value


def _contract_version(obj: Any, fail: Callable[[str, str, str], None]) -> str | None:
    value = _text(obj, "contract_version", fail)
    if value is None:
        return None
    match = SEMVER.fullmatch(value)
    if match is None:
        fail("contract_version", f"{value!r} is not MAJOR.MINOR.PATCH", 'write it as "1.0.0"')
        return None
    if int(match.group(1)) != CONTRACT_MAJOR:
        fail(
            "contract_version",
            f"{value} is not supported; this hfk supports contract {SUPPORTED_CONTRACT}",
            "install an extension release built for this hfk, or a matching hfk",
        )
        return None
    return value


def _config_section(
    obj: Any, fail: Callable[[str, str, str], None]
) -> tuple[str | None, Callable[[Any, Any], object] | None]:
    for member in ("config_section", "schema"):
        if not hasattr(obj, member):
            fail(member, "missing", f"set {member}, or set it to None when there is no config")
    section = getattr(obj, "config_section", None)
    schema = getattr(obj, "schema", None)
    if section is None:
        if schema is not None:
            fail("schema", "set while config_section is None", "set schema to None, or add config_section")
        return None, None
    if not isinstance(section, str) or not section.endswith(".yaml") or "/" in section or "\\" in section:
        fail(
            "config_section",
            f"{section!r} is not a YAML file name in the instance",
            "name the extension's own file, such as retirement.yaml",
        )
        return None, None
    if section in CORE_FILES:
        fail(
            "config_section",
            f"{section} belongs to core",
            "give the extension its own file, such as <name>.yaml",
        )
    if not callable(schema):
        fail("schema", "missing or not callable", "define schema(data, path) returning the config")
        return section, None
    return section, schema


def _requires(obj: Any, fail: Callable[[str, str, str], None]) -> Requirements | None:
    if not hasattr(obj, "requires"):
        fail("requires", "missing", 'set requires = {"ledger_fields": [...], "extensions": [...]}')
        return None
    value = obj.requires
    if not isinstance(value, Mapping):
        fail("requires", f"{value!r} is not a mapping", "use a dict with ledger_fields and extensions")
        return None
    unknown = sorted(str(key) for key in value if key not in REQUIRES_KEYS)
    if unknown:
        fail("requires", f"unknown keys {unknown}", f"use only {list(REQUIRES_KEYS)}")
    lists: dict[str, tuple[str, ...]] = {}
    for key in REQUIRES_KEYS:
        items = value.get(key, ())
        if isinstance(items, str) or not isinstance(items, (list, tuple)) or not all(
            isinstance(item, str) for item in items
        ):
            fail(f"requires.{key}", f"{items!r} is not a list of names", "list names as strings")
            lists[key] = ()
            continue
        lists[key] = tuple(items)
    for field in lists["ledger_fields"]:
        if field not in LEDGER_FIELDS:
            fail(
                "requires.ledger_fields",
                f"{field!r} is not a Ledger field",
                f"use some of {list(LEDGER_FIELDS)}",
            )
    return Requirements(ledger_fields=lists["ledger_fields"], extensions=lists["extensions"])


def _commands(obj: Any, fail: Callable[[str, str, str], None]) -> tuple[ExtensionCommand, ...] | None:
    method = getattr(obj, "commands", None)
    if not callable(method):
        fail("commands", "missing or not callable", "define commands() returning ExtensionCommand objects")
        return None
    try:
        items = tuple(method())
    except Exception as error:  # noqa: BLE001 - reported as a contract break
        fail("commands", f"commands() raised {type(error).__name__}: {error}", "make commands() return a list")
        return None
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, ExtensionCommand):
            fail("commands", f"{item!r} is not an ExtensionCommand", "build commands with hfk.ext.ExtensionCommand")
            continue
        if not COMMAND_NAME.match(item.name):
            fail("commands", f"command name {item.name!r} is not a lowercase word", "use a name such as settle")
        if item.name in CORE_COMMANDS:
            fail("commands", f"command {item.name!r} is a core command", "choose another name")
        if item.name in seen:
            fail("commands", f"command {item.name!r} is listed twice", "list each command once")
        if not callable(item.configure) or not callable(item.run):
            fail("commands", f"command {item.name!r} has a non-callable configure or run", "pass functions")
        seen.add(item.name)
    return items


def _report_sections(
    obj: Any, fail: Callable[[str, str, str], None]
) -> tuple[ReportSection, ...] | None:
    method = getattr(obj, "report_sections", None)
    if method is None:
        return ()
    if not callable(method):
        fail("report_sections", "not callable", "define report_sections() or leave it out")
        return None
    try:
        items = tuple(method())
    except Exception as error:  # noqa: BLE001 - reported as a contract break
        fail("report_sections", f"raised {type(error).__name__}: {error}", "make it return a list")
        return None
    for item in items:
        if not isinstance(item, ReportSection) or not callable(item.build):
            fail("report_sections", f"{item!r} is not a ReportSection", "build them with hfk.ext.ReportSection")
    return items


__all__ = [
    "CONTRACT_MAJOR",
    "CORE_COMMANDS",
    "CommandContext",
    "ContractError",
    "Extension",
    "ExtensionCommand",
    "ReportSection",
    "Requirements",
    "validate_extension",
]
