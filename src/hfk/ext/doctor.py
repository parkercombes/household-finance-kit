"""Extension doctor hooks for ``hfk doctor`` (M6-04).

``extension_doctor_hooks`` turns the installed extensions into
``hfk.engine.DoctorHook`` objects that ``run_doctor`` runs after its core
checks. The first hook, ``extensions``, reports the extension setup itself:
an entry point that failed to load or broke the contract (an error when the
household enabled it, a warning otherwise) and an enabled extension that is
not installed. Then each installed extension gets a hook named after it,
which does nothing unless the household enabled it; when enabled it checks
the required extensions, loads the config file, and calls the extension's
own ``doctor(context, config)``. A config problem is reported with the file,
key path, and fix, and the extension's own doctor is skipped.
"""

from __future__ import annotations

from collections.abc import Iterator

from hfk.config import ConfigError
from hfk.engine import Diagnostic, DoctorContext, DoctorHook
from hfk.ext import LoadedExtensions, enabled_extension, load_extension_config
from hfk.ext.contract import Extension


def extension_doctor_hooks(loaded: LoadedExtensions) -> tuple[DoctorHook, ...]:
    """One setup hook, then one hook per installed extension, in name order."""

    hooks = [DoctorHook("extensions", lambda context: _setup(context, loaded))]
    for extension in loaded.extensions:
        hooks.append(DoctorHook(extension.name, _extension_check(extension, loaded)))
    return tuple(hooks)


def _enabled(context: DoctorContext) -> tuple[str, ...]:
    return () if context.household is None else context.household.extensions


def _setup(context: DoctorContext, loaded: LoadedExtensions) -> Iterator[Diagnostic]:
    enabled = _enabled(context)
    broken = {problem.entry_point for problem in loaded.problems}
    for problem in loaded.problems:
        level = "error" if problem.entry_point in enabled else "warning"
        yield Diagnostic(
            level,
            "extension-unavailable",
            f"extension {problem.entry_point}",
            problem.problem,
            problem.fix,
        )
    if context.household is None:
        return
    for name in enabled:
        if loaded.get(name) is not None or name in broken:
            continue
        try:
            enabled_extension(name, household=context.household, installed=loaded.extensions)
        except ConfigError as error:
            yield _config_diagnostic(error)


def _extension_check(extension: Extension, loaded: LoadedExtensions):
    def check(context: DoctorContext) -> Iterator[Diagnostic]:
        if context.household is None or extension.name not in _enabled(context):
            return
        try:
            enabled_extension(
                extension.name, household=context.household, installed=loaded.extensions
            )
            config = load_extension_config(context.home, extension)
        except ConfigError as error:
            yield _config_diagnostic(error)
            return
        yield from extension.doctor(context, config)

    return check


def _config_diagnostic(error: ConfigError) -> Diagnostic:
    return Diagnostic(
        "error",
        "extension-config",
        f"{error.file.name} key={error.key}",
        error.problem,
        error.fix,
    )


__all__ = ["extension_doctor_hooks"]
