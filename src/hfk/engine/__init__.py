"""Engine layer: pure calculations and diagnostics."""

from hfk.engine.balances import (
    AccountBalance,
    BalancesError,
    BalancesReport,
    build_balances,
)
from hfk.engine.buckets import (
    BucketAmount,
    BucketConflictError,
    BucketError,
    BucketPortion,
    CategoryResolution,
    allocate,
    bucket_attributes,
    resolve_category,
    resolve_ledger,
)
from hfk.engine.categories import (
    CategoriesError,
    CategoriesReport,
    CategoryLine,
    build_categories,
)
from hfk.engine.doctor import Diagnostic, DoctorReport, run_doctor
from hfk.engine.networth import (
    NetWorthError,
    NetWorthLine,
    NetWorthReport,
    build_networth,
)
from hfk.engine.renewals import (
    Renewal,
    RenewalsError,
    RenewalsReport,
    ScheduleMonth,
    build_renewals,
)
from hfk.engine.scorecard import BucketScore, Scorecard, ScorecardError, build_scorecard
from hfk.engine.shares import (
    Share,
    ShareConflictError,
    ShareError,
    TransactionShares,
    person_total,
    share_ledger,
    share_transaction,
    share_weights,
)

__all__ = [
    "AccountBalance",
    "BalancesError",
    "BalancesReport",
    "BucketAmount",
    "BucketConflictError",
    "BucketError",
    "BucketPortion",
    "BucketScore",
    "CategoriesError",
    "CategoriesReport",
    "CategoryLine",
    "CategoryResolution",
    "Diagnostic",
    "DoctorReport",
    "NetWorthError",
    "NetWorthLine",
    "NetWorthReport",
    "Renewal",
    "RenewalsError",
    "RenewalsReport",
    "ScheduleMonth",
    "Scorecard",
    "ScorecardError",
    "Share",
    "ShareConflictError",
    "ShareError",
    "TransactionShares",
    "allocate",
    "bucket_attributes",
    "build_balances",
    "build_categories",
    "build_networth",
    "build_renewals",
    "build_scorecard",
    "person_total",
    "resolve_category",
    "resolve_ledger",
    "run_doctor",
    "share_ledger",
    "share_transaction",
    "share_weights",
]
