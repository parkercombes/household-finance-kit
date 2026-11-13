"""Extension config sections (M6-03; ADR-0002, proposed ADR-0016).

A household enables an extension by listing its name under ``extensions`` in
``household.yaml``. Only then is its config section read: the extension's own
YAML file in the instance, validated by the extension's ``schema``. A file for
an extension that is not enabled is never opened, so a stale or half-written
one cannot break core. An enabled extension that is not installed, whose
required extensions are not enabled, or whose file is missing or invalid is a
``ConfigError`` naming the file, key path, and fix.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hfk.config import ConfigError, Household
from hfk.config._yaml import load_mapping
from hfk.config.errors import key_path
from hfk.ext.contract import Extension


@dataclass(frozen=True)
class EnabledExtension:
    """An enabled, installed extension and its validated config (``None`` when it has none)."""

    extension: Extension
    config: object


def enabled_extension(
    name: str, *, household: Household, installed: tuple[Extension, ...]
) -> Extension:
    """The installed extension enabled as ``name``, after checking its required extensions."""

    by_name = {extension.name: extension for extension in installed}
    index = household.extensions.index(name) if name in household.extensions else None
    if index is None:
        raise ConfigError(
            f"extension {name!r} is not enabled",
            file=household.path,
            key="extensions",
            fix=f"add {name} to extensions in household.yaml",
        )
    extension = by_name.get(name)
    if extension is None:
        available = ", ".join(sorted(by_name)) or "none"
        raise ConfigError(
            f"extension {name!r} is enabled but not installed (installed: {available})",
            file=household.path,
            key=key_path("extensions", f"[{index}]"),
            fix=f"install the package that provides {name}, or remove it from extensions",
        )
    for required in extension.requires.extensions:
        if required not in household.extensions:
            raise ConfigError(
                f"extension {name!r} requires extension {required!r}, which is not enabled",
                file=household.path,
                key="extensions",
                fix=f"add {required} to extensions in household.yaml, or remove {name}",
            )
    return extension


def load_extension_config(home: Path, extension: Extension) -> object:
    """Read and validate an enabled extension's own config file; ``None`` when it has none."""

    if extension.config_section is None:
        return None
    assert extension.schema is not None
    path = Path(home) / extension.config_section
    if not path.exists():
        raise ConfigError(
            f"{extension.name} is enabled but its config file is missing",
            file=path,
            key="(file)",
            fix=(
                f"create {extension.config_section} in the instance (see the {extension.name} "
                "extension's documentation), or remove it from extensions in household.yaml"
            ),
        )
    data = load_mapping(path)
    try:
        return extension.schema(data, path)
    except ConfigError:
        raise
    except Exception as error:
        raise ConfigError(
            f"the {extension.name} schema failed: {type(error).__name__}: {error}",
            file=path,
            key="(file)",
            fix=f"report this to the {extension.name} extension's maintainer",
        ) from error


def load_enabled_extensions(
    home: Path, *, household: Household, installed: tuple[Extension, ...]
) -> tuple[EnabledExtension, ...]:
    """Every enabled extension with its config, in ``household.yaml`` order; the first problem raises."""

    return tuple(
        EnabledExtension(
            extension=(extension := enabled_extension(name, household=household, installed=installed)),
            config=load_extension_config(home, extension),
        )
        for name in household.extensions
    )


__all__ = [
    "EnabledExtension",
    "enabled_extension",
    "load_enabled_extensions",
    "load_extension_config",
]
