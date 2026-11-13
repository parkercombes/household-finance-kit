"""Config layer: load and validate private instance YAML files.

Errors are ``ConfigError`` and always name the file, key path, and fix.
M2-01 implements ``household.yaml``; M2-02 implements ``declarations.yaml``;
M2-03 implements ``plan.yaml``; M5-08 adds the ``HFK Plan`` workbook sheet.
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
from .errors import ConfigError, PlanSheetError
from .household import (
    HOUSEHOLD_FILE,
    AccountOwnership,
    Household,
    Person,
    household_path,
    load_household,
)
from .plan import PLAN_FILE, Month, Plan, PlanLine, load_plan, plan_path
from .plan_check import (
    PlanCheckReport,
    PlanProblem,
    check_instance_plan,
    check_plan,
    check_plan_sheet,
)
from .plan_sheet import (
    PLAN_SHEET,
    load_instance_plan,
    load_plan_sheet,
    plan_workbook,
    unused_plan_file,
)

__all__ = [
    "DECLARATIONS_FILE",
    "HOUSEHOLD_FILE",
    "PLAN_FILE",
    "PLAN_SHEET",
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
    "PlanSheetError",
    "SharingRule",
    "Split",
    "available_profiles",
    "check_instance_plan",
    "check_plan",
    "check_plan_sheet",
    "declarations_path",
    "household_path",
    "load_declarations",
    "load_household",
    "load_instance_plan",
    "load_plan",
    "load_plan_sheet",
    "plan_path",
    "plan_workbook",
    "unused_plan_file",
]
