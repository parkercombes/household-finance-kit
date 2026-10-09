"""Config validation errors.

Every error names the file, the key path, and the fix so the user can act on
it without reading code (design brief section 6; ADR-0002).
"""

from __future__ import annotations

from pathlib import Path


class ConfigError(ValueError):
    """Raised when a private instance YAML file is missing, malformed, or invalid."""

    def __init__(self, problem: str, *, file: Path, key: str, fix: str) -> None:
        self.problem = problem
        self.file = file
        self.key = key
        self.fix = fix
        super().__init__(f"{problem}: file={file}, key={key}, fix={fix}")


def key_path(*parts: str) -> str:
    """Join key path parts: ``people[0].slug``; keys that are not identifiers are quoted."""

    rendered = ""
    for part in parts:
        if part.startswith("[") and part.endswith("]"):
            rendered += part
            continue
        if rendered:
            rendered += "."
        if part.replace("_", "").isalnum() and not part[:1].isdigit():
            rendered += part
        else:
            rendered += f'"{part}"'
    return rendered
