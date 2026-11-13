"""Config layer: load and validate private instance YAML files.

Errors are ``ConfigError`` and always name the file, key path, and fix.
M2-01 implements ``household.yaml``; M2-02 implements ``declarations.yaml``;
M2-03 implemented ``plan.yaml``; M5-08 added the ``HFK Plan`` workbook sheet,
which M5-18 made the only plan source (ADR-0015). ``plan.yaml`` is read only by
the ``hfk plan to-sheet`` converter in ``plan_convert``.
"""

from .declarations import (
    DECLARATIONS_FILE,
    Bucket,
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
from .plan import PLAN_FILE, Month, Plan, PlanLine
from .plan_check import (
    PlanCheckReport,
    PlanProblem,
    check_instance_plan,
    check_plan_sheet,
)
from .plan_sheet import (
    HEADERS as PLAN_SHEET_HEADERS,
)
from .plan_sheet import (
    PLAN_SHEET,
    STARTER_CSV,
    load_instance_plan,
    load_plan_sheet,
    plan_csv,
    plan_workbook,
    reject_plan_file,
)

__all__ = [
    "DECLARATIONS_FILE",
    "HOUSEHOLD_FILE",
    "PLAN_FILE",
    "PLAN_SHEET",
    "PLAN_SHEET_HEADERS",
    "STARTER_CSV",
    "AccountOwnership",
    "Bucket",
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
    "check_plan_sheet",
    "declarations_path",
    "household_path",
    "load_declarations",
    "load_household",
    "load_instance_plan",
    "load_plan_sheet",
    "plan_csv",
    "plan_workbook",
    "reject_plan_file",
]
