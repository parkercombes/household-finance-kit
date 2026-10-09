"""Config layer: load and validate private instance YAML files.

Errors are ``ConfigError`` and always name the file, key path, and fix.
M2-01 implements ``household.yaml``; ``declarations.yaml`` (M2-02) and
``plan.yaml`` (M2-03) follow.
"""

from .errors import ConfigError
from .household import (
    HOUSEHOLD_FILE,
    AccountOwnership,
    Household,
    Person,
    household_path,
    load_household,
)

__all__ = [
    "HOUSEHOLD_FILE",
    "AccountOwnership",
    "ConfigError",
    "Household",
    "Person",
    "household_path",
    "load_household",
]
