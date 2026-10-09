"""Shared helpers for loading and shape-checking instance YAML files."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from hfk.config.errors import ConfigError, key_path

SUPPORTED_SCHEMA_VERSION = 1


def load_mapping(path: Path) -> dict[str, Any]:
    """Read a YAML file that must be a mapping; name the file on every failure."""

    if not path.is_file():
        raise ConfigError(
            "Missing config file",
            file=path,
            key="(file)",
            fix=f"create {path.name} in the instance home (see examples/{path.stem}.example.yaml)",
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"Unparseable YAML ({exc.__class__.__name__})",
            file=path,
            key="(file)",
            fix="fix the YAML syntax at the position the parser reports",
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError(
            "Config file is not a mapping",
            file=path,
            key="(file)",
            fix="make the top level of the file a mapping of keys to values",
        )
    return data


def require_schema_version(data: dict[str, Any], path: Path) -> int:
    version = require(data, "schema_version", path)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ConfigError(
            "schema_version must be an integer",
            file=path,
            key="schema_version",
            fix=f"set schema_version: {SUPPORTED_SCHEMA_VERSION}",
        )
    if version != SUPPORTED_SCHEMA_VERSION:
        raise ConfigError(
            f"Unsupported schema_version {version}",
            file=path,
            key="schema_version",
            fix=f"this toolkit reads schema_version {SUPPORTED_SCHEMA_VERSION}; "
            "upgrade the toolkit or rewrite the file",
        )
    return version


def require(data: dict[str, Any], key: str, path: Path, *parents: str) -> Any:
    if key not in data:
        raise ConfigError(
            "Missing required key",
            file=path,
            key=key_path(*parents, key),
            fix=f"add {key} (see examples/{path.stem}.example.yaml)",
        )
    return data[key]


def reject_unknown_keys(data: dict[str, Any], allowed: Iterable[str], path: Path, *parents: str) -> None:
    allowed_set = set(allowed)
    for key in data:
        if key not in allowed_set:
            raise ConfigError(
                f"Unknown key {key!r}",
                file=path,
                key=key_path(*parents, str(key)),
                fix=f"remove it or fix the spelling; allowed keys are {sorted(allowed_set)}",
            )


def require_mapping(value: Any, path: Path, *parents: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(
            "Expected a mapping",
            file=path,
            key=key_path(*parents),
            fix="write this key as a mapping of keys to values",
        )
    return value


def require_list(value: Any, path: Path, *parents: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigError(
            "Expected a list",
            file=path,
            key=key_path(*parents),
            fix="write this key as a YAML list",
        )
    return value


def require_bool(value: Any, path: Path, *parents: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(
            "Expected true or false",
            file=path,
            key=key_path(*parents),
            fix="use YAML true or false",
        )
    return value


def require_text(value: Any, path: Path, *parents: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            "Expected non-empty text",
            file=path,
            key=key_path(*parents),
            fix="give this key a non-empty string value",
        )
    return value.strip()
