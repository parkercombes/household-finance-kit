"""Config layer: load and validate private instance YAML files.

Errors are ``ConfigError`` and always name the file, key path, and fix.
M2-01 implements ``household.yaml``; M2-02 implements ``declarations.yaml``;
``plan.yaml`` (M2-03) follows.
"""

from .declarations import (
    DECLARATIONS_FILE,
    Bucket,
    ClosedAccount,
    Declarations,
    Override,
    SharingRule,
    Split,
    declarations_path,
    load_declarations,
)
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
    "DECLARATIONS_FILE",
    "HOUSEHOLD_FILE",
    "AccountOwnership",
    "Bucket",
    "ClosedAccount",
    "ConfigError",
    "Declarations",
    "Household",
    "Override",
    "Person",
    "SharingRule",
    "Split",
    "declarations_path",
    "household_path",
    "load_declarations",
    "load_household",
]
