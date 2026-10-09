"""Engine layer: pure calculations and diagnostics."""

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
from hfk.engine.doctor import Diagnostic, DoctorReport, run_doctor
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
    "BucketAmount",
    "BucketConflictError",
    "BucketError",
    "BucketPortion",
    "CategoryResolution",
    "Diagnostic",
    "DoctorReport",
    "Share",
    "ShareConflictError",
    "ShareError",
    "TransactionShares",
    "allocate",
    "bucket_attributes",
    "person_total",
    "resolve_category",
    "resolve_ledger",
    "run_doctor",
    "share_ledger",
    "share_transaction",
    "share_weights",
]
