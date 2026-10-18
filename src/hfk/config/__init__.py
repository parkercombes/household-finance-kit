"""Config layer: load and validate private instance YAML files.

Errors are ``ConfigError`` and always name the file, key path, and fix.
M2-01 implements ``household.yaml``; M2-02 implements ``declarations.yaml``;
M2-03 implements ``plan.yaml``.
"""

from .declarations import (
    DECLARATIONS_FILE,
    Bucket,
    ClosedAccount,
    Declarations,
    Override,
    SharingRule,
    Split,
    available_profiles,
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
from .plan import PLAN_FILE, Month, Plan, PlanLine, load_plan, plan_path
from .plan_check import PlanCheckReport, PlanProblem, check_plan

__all__ = [
    "DECLARATIONS_FILE",
    "HOUSEHOLD_FILE",
    "PLAN_FILE",
    "AccountOwnership",
    "Bucket",
    "ClosedAccount",
    "ConfigError",
    "Declarations",
    "Household",
    "Month",
    "Override",
    "Person",
    "Plan",
    "PlanCheckReport",
    "PlanLine",
    "PlanProblem",
    "SharingRule",
    "Split",
    "available_profiles",
    "check_plan",
    "declarations_path",
    "household_path",
    "load_declarations",
    "load_household",
    "load_plan",
    "plan_path",
]
