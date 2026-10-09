"""Bucket mapping and allocation calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from hfk.config import Bucket, Declarations
from hfk.ledger import Ledger, money


@dataclass(frozen=True)
class BucketError(ValueError):
    """Raised when a category cannot be assigned to declared buckets."""

    problem: str
    fix: str
    category: str | None = None

    def __post_init__(self) -> None:
        ValueError.__init__(self, str(self))

    def __str__(self) -> str:
        return f"{self.problem}. Fix: {self.fix}"


@dataclass(frozen=True, init=False)
class BucketConflictError(BucketError):
    """Raised when a category has conflicting bucket judgments."""

    def __init__(self, category: str) -> None:
        super().__init__(
            f'category "{category}" is declared in both splits and overrides',
            "keep the category in splits or overrides, not both",
            category,
        )


@dataclass(frozen=True)
class BucketPortion:
    bucket: str
    weight: Decimal
    source: str
    reason: str | None


@dataclass(frozen=True)
class CategoryResolution:
    category: str
    group: str | None
    excluded: bool
    portions: tuple[BucketPortion, ...]


@dataclass(frozen=True)
class BucketAmount:
    bucket: str
    amount: Decimal


def resolve_category(name: str, ledger: Ledger, declarations: Declarations) -> CategoryResolution:
    """Resolve one category name to bucket portions."""

    split = declarations.split(name)
    override = declarations.override(name)
    category = ledger.category(name)
    group = None if category is None else category.group

    if split is not None and override is not None:
        raise BucketConflictError(name)
    if split is not None:
        return CategoryResolution(
            category=name,
            group=group,
            excluded=False,
            portions=tuple(
                BucketPortion(bucket=bucket, weight=weight, source="split", reason=split.reason)
                for bucket, weight in split.weights
            ),
        )
    if override is not None:
        return CategoryResolution(
            category=name,
            group=group,
            excluded=False,
            portions=(
                BucketPortion(
                    bucket=override.bucket,
                    weight=Decimal(1),
                    source="override",
                    reason=override.reason,
                ),
            ),
        )

    if category is None:
        raise BucketError(
            f'category "{name}" appears in transactions but not in the Categories sheet',
            f'add "{name}" back to the Categories sheet in Tiller, or add '
            f'overrides."{name}" with a bucket and reason in declarations.yaml; '
            "history is never remapped silently",
            name,
        )

    if _category_excluded(category.type, category.group, declarations):
        return CategoryResolution(category=name, group=category.group, excluded=True, portions=())

    if declarations.mapping_source == "tiller_group":
        bucket = dict(declarations.groups).get(category.group)
        if bucket is None:
            raise BucketError(
                f'group "{category.group}" (category "{name}") has no bucket',
                f'add groups."{category.group}": <bucket> in declarations.yaml, '
                "or list it under non_spend_groups",
                name,
            )
        source = "group"
    elif declarations.mapping_source == "explicit":
        bucket = dict(declarations.categories).get(name)
        if bucket is None:
            raise BucketError(
                f'category "{name}" has no bucket',
                f'add categories."{name}": <bucket> in declarations.yaml',
                name,
            )
        source = "category"
    else:
        raise BucketError(
            f'Unknown mapping_source "{declarations.mapping_source}"',
            "use mapping_source tiller_group or explicit",
            name,
        )

    return CategoryResolution(
        category=name,
        group=category.group,
        excluded=False,
        portions=(BucketPortion(bucket=bucket, weight=Decimal(1), source=source, reason=None),),
    )


def resolve_ledger(ledger: Ledger, declarations: Declarations) -> dict[str, CategoryResolution]:
    """Resolve every Categories-sheet category and every transaction category."""

    resolutions: dict[str, CategoryResolution] = {}
    for name in _category_names_in_ledger_order(ledger):
        resolutions[name] = resolve_category(name, ledger, declarations)
    return resolutions


def allocate(amount: Decimal, resolution: CategoryResolution) -> tuple[BucketAmount, ...]:
    """Allocate ``amount`` across a resolved category with exact-cent reconciliation."""

    if resolution.excluded:
        return ()

    allocations = [
        BucketAmount(bucket=portion.bucket, amount=money(amount * portion.weight))
        for portion in resolution.portions
    ]
    total = sum((allocation.amount for allocation in allocations), Decimal("0.00"))
    residual = amount - total
    if residual and allocations:
        residual_index = _largest_weight_index(resolution.portions)
        current = allocations[residual_index]
        allocations[residual_index] = BucketAmount(
            bucket=current.bucket,
            amount=current.amount + residual,
        )
    return tuple(allocations)


def bucket_attributes(declarations: Declarations, name: str) -> Bucket:
    """Return the declared bucket attributes for ``name``."""

    bucket = declarations.bucket(name)
    if bucket is None:
        raise BucketError(
            f'bucket "{name}" is not declared',
            f'add "{name}" under buckets with essential and fixed attributes',
        )
    return bucket


def _category_names_in_ledger_order(ledger: Ledger) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for category in ledger.categories:
        if category.name not in seen:
            seen.add(category.name)
            names.append(category.name)
    for transaction in ledger.transactions:
        if transaction.category not in seen:
            seen.add(transaction.category)
            names.append(transaction.category)
    return tuple(names)


def _category_excluded(category_type: str, group: str, declarations: Declarations) -> bool:
    return category_type in {"Income", "Transfer"} or group in declarations.non_spend_groups


def _largest_weight_index(portions: tuple[BucketPortion, ...]) -> int:
    return max(range(len(portions)), key=lambda index: portions[index].weight)
