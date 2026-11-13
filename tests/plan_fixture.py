"""Test helpers for the `HFK Plan` sheet, the only plan source (ADR-0015).

Many tests used to edit `plan.yaml`. They now edit the same plan as a Python
mapping in the old `plan.yaml` shape and write it into the synthetic fixture
workbook's `HFK Plan` sheet through `build_fixture(plan_rows=...)`, which is
the only code allowed to write a workbook.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from hfk.source.fixture import build_fixture

# The former examples/instance/plan.yaml, the same lines as the fixture's
# default HFK Plan sheet and the table in examples/instance/README.md.
EXAMPLE_PLAN: dict[str, Any] = {
    "schema_version": 1,
    "plan": {
        "effective_from": "2025-01",
        "lines": [
            {"desc": "Example Rent", "who": "alex", "bucket": "Fixed Essential",
             "monthly": 1200.00, "categories": ["Rent"]},
            {"desc": "Example Utilities", "who": "alex", "bucket": "Variable Essential",
             "monthly": 90.00, "categories": ["Utilities"], "paced": True},
            {"desc": "Example Utilities", "who": "sam", "bucket": "Variable Essential",
             "monthly": 90.00, "categories": ["Utilities"], "paced": True},
            {"desc": "Example Grocer", "who": "alex", "bucket": "Variable Essential",
             "monthly": 500.00, "categories": ["Groceries"], "paced": True,
             "effective_until": "2025-06"},
            {"desc": "Example Grocer", "who": "alex", "bucket": "Variable Essential",
             "monthly": 550.00, "categories": ["Groceries"], "paced": True,
             "effective_from": "2025-07"},
            {"desc": "Example Transit", "who": "sam", "bucket": "Variable Essential",
             "monthly": 80.00, "categories": ["Transit"], "paced": True},
            {"desc": "Example Streaming", "who": "alex", "bucket": "Fixed Discretionary",
             "monthly": 20.00},
            {"desc": "Example Cloud Renewal", "who": "alex", "bucket": "Fixed Discretionary",
             "monthly": 10.00, "annual_bill": 120.00, "annual_full": 120.00,
             "account": "Alex Checking", "due": {"month": 7, "day": 1},
             "categories": ["Annual Membership"]},
            {"desc": "Example Cafe", "who": "sam", "bucket": "Variable Discretionary",
             "monthly": 60.00, "categories": ["Dining"], "paced": True},
        ],
    },
}

EXAMPLE_PLAN_YAML = """\
schema_version: 1
plan:
  effective_from: 2025-01
  lines:
    - {desc: "Example Rent", who: alex, bucket: Fixed Essential, monthly: 1200.00, categories: [Rent]}
    - {desc: "Example Utilities", who: alex, bucket: Variable Essential, monthly: 90.00, categories: [Utilities], paced: true}
    - {desc: "Example Utilities", who: sam, bucket: Variable Essential, monthly: 90.00, categories: [Utilities], paced: true}
    - {desc: "Example Grocer", who: alex, bucket: Variable Essential, monthly: 500.00, categories: [Groceries], paced: true, effective_until: 2025-06}
    - {desc: "Example Grocer", who: alex, bucket: Variable Essential, monthly: 550.00, categories: [Groceries], paced: true, effective_from: 2025-07}
    - {desc: "Example Transit", who: sam, bucket: Variable Essential, monthly: 80.00, categories: [Transit], paced: true}
    - {desc: "Example Streaming", who: alex, bucket: Fixed Discretionary, monthly: 20.00}
    - {desc: "Example Cloud Renewal", who: alex, bucket: Fixed Discretionary, monthly: 10.00, annual_bill: 120.00, annual_full: 120.00, account: "Alex Checking", due: {month: 7, day: 1}, categories: [Annual Membership]}
    - {desc: "Example Cafe", who: sam, bucket: Variable Discretionary, monthly: 60.00, categories: [Dining], paced: true}
"""


def example_plan() -> dict[str, Any]:
    """A fresh, editable copy of the example plan in the old `plan.yaml` shape."""

    return copy.deepcopy(EXAMPLE_PLAN)


def sheet_rows(plan: dict[str, Any]) -> list[dict[str, object]]:
    """Convert a `plan.yaml`-shaped mapping into `HFK Plan` rows keyed by header."""

    default_from = plan["plan"].get("effective_from")
    rows: list[dict[str, object]] = []
    for line in plan["plan"]["lines"]:
        due = line.get("due") or {}
        rows.append(
            {
                "Description": line.get("desc"),
                "Who": line.get("who"),
                "Bucket": line.get("bucket"),
                "Monthly": line.get("monthly"),
                "Categories": "; ".join(line.get("categories", [])) or None,
                "Paced": "yes" if line.get("paced") else None,
                "Effective From": line.get("effective_from", default_from),
                "Effective Until": line.get("effective_until"),
                "Annual Bill": line.get("annual_bill"),
                "Annual Full": line.get("annual_full"),
                "Account": line.get("account"),
                "Due Month": due.get("month"),
                "Due Day": due.get("day"),
            }
        )
    return rows


def write_plan(home: Path, plan: dict[str, Any], **fixture_kwargs: Any) -> Path:
    """Rebuild the instance's fixture workbook with `plan` in its `HFK Plan` sheet."""

    return build_fixture(
        Path(home) / "data" / "Tiller-Example.xlsx", plan_rows=sheet_rows(plan), **fixture_kwargs
    )
