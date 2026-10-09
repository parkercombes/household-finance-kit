"""Load and validate ``declarations.yaml`` (design brief section 6; ADR-0011).

The file declares bucket definitions, group/category bucket maps, judgment-call
overrides and splits, transaction sharing rules, and closed accounts. Nothing is
inferred: every error names the file, key path, and fix.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from hfk.config._yaml import (
    load_mapping,
    reject_unknown_keys,
    require,
    require_list,
    require_mapping,
    require_schema_version,
    require_text,
)
from hfk.config.errors import ConfigError, key_path

DECLARATIONS_FILE = "declarations.yaml"
TOP_LEVEL_KEYS = (
    "schema_version",
    "buckets",
    "profile",
    "mapping_source",
    "groups",
    "categories",
    "non_spend_groups",
    "overrides",
    "splits",
    "sharing",
    "closed_accounts",
)
BUCKET_KEYS = ("name", "essential", "fixed")
OVERRIDE_KEYS = ("bucket", "reason")
SPLIT_KEYS = ("weights", "reason")
SHARING_KEYS = ("match", "weights", "reason")
MATCH_KEYS = ("account", "description", "category")
CLOSED_ACCOUNT_KEYS = ("closed", "note")
MAPPING_SOURCES = ("tiller_group", "explicit")


@dataclass(frozen=True)
class Bucket:
    name: str
    essential: bool
    fixed: bool


@dataclass(frozen=True)
class Override:
    category: str
    bucket: str
    reason: str


@dataclass(frozen=True)
class Split:
    category: str
    weights: tuple[tuple[str, Decimal], ...]
    reason: str


@dataclass(frozen=True)
class SharingRule:
    account: str | None
    description: str | None
    category: str | None
    weights: tuple[tuple[str, Decimal], ...]
    reason: str


@dataclass(frozen=True)
class ClosedAccount:
    name: str
    closed: date
    note: str | None


@dataclass(frozen=True)
class Declarations:
    path: Path
    schema_version: int
    buckets: tuple[Bucket, ...]
    profile: str | None
    mapping_source: str
    groups: tuple[tuple[str, str], ...]
    categories: tuple[tuple[str, str], ...]
    non_spend_groups: tuple[str, ...]
    overrides: tuple[Override, ...]
    splits: tuple[Split, ...]
    sharing: tuple[SharingRule, ...]
    closed_accounts: tuple[ClosedAccount, ...]

    def bucket(self, name: str) -> Bucket | None:
        for bucket in self.buckets:
            if bucket.name == name:
                return bucket
        return None

    def bucket_names(self) -> tuple[str, ...]:
        return tuple(bucket.name for bucket in self.buckets)

    def override(self, category: str) -> Override | None:
        for override in self.overrides:
            if override.category == category:
                return override
        return None

    def split(self, category: str) -> Split | None:
        for split in self.splits:
            if split.category == category:
                return split
        return None

    def closed_account(self, name: str) -> ClosedAccount | None:
        for account in self.closed_accounts:
            if account.name == name:
                return account
        return None


def declarations_path(home: Path) -> Path:
    return Path(home) / DECLARATIONS_FILE


def load_declarations(
    home_or_file: Path,
    *,
    people: Iterable[str] | None = None,
    profiles_dir: Path | None = None,
) -> Declarations:
    """Load ``declarations.yaml`` from an instance home directory or explicit file path."""

    path = Path(home_or_file)
    if path.is_dir():
        path = declarations_path(path)
    data = load_mapping(path)
    reject_unknown_keys(data, TOP_LEVEL_KEYS, path)

    schema_version = require_schema_version(data, path)
    buckets, profile = _bucket_definitions(data, path, profiles_dir)
    bucket_names = tuple(bucket.name for bucket in buckets)
    declared_buckets = set(bucket_names)
    mapping_source = _mapping_source(data, path)
    groups: tuple[tuple[str, str], ...] = ()
    categories: tuple[tuple[str, str], ...] = ()
    if mapping_source == "tiller_group":
        if "categories" in data:
            raise ConfigError(
                "categories is only used with mapping_source explicit",
                file=path,
                key="categories",
                fix="remove categories or set mapping_source: explicit",
            )
        groups = _bucket_map(
            require(data, "groups", path),
            declared_buckets,
            bucket_names,
            path,
            "groups",
        )
    else:
        if "groups" in data:
            raise ConfigError(
                "groups is only used with mapping_source tiller_group",
                file=path,
                key="groups",
                fix="remove groups or set mapping_source: tiller_group",
            )
        categories = _bucket_map(
            require(data, "categories", path),
            declared_buckets,
            bucket_names,
            path,
            "categories",
        )
    non_spend_groups = _unique_text_list(data.get("non_spend_groups", []), path, "non_spend_groups")
    overrides = _overrides(data.get("overrides", {}), declared_buckets, bucket_names, path)
    split_conflicts = {override.category for override in overrides}
    splits = _splits(data.get("splits", {}), declared_buckets, bucket_names, split_conflicts, path)
    known_people = None if people is None else set(people)
    sharing = _sharing(data.get("sharing", []), known_people, path)
    closed_accounts = _closed_accounts(data.get("closed_accounts", {}), path)
    return Declarations(
        path=path,
        schema_version=schema_version,
        buckets=buckets,
        profile=profile,
        mapping_source=mapping_source,
        groups=groups,
        categories=categories,
        non_spend_groups=non_spend_groups,
        overrides=overrides,
        splits=splits,
        sharing=sharing,
        closed_accounts=closed_accounts,
    )


def _bucket_definitions(
    data: dict[str, Any], path: Path, profiles_dir: Path | None
) -> tuple[tuple[Bucket, ...], str | None]:
    has_buckets = "buckets" in data
    has_profile = "profile" in data
    if has_buckets == has_profile:
        if has_buckets:
            raise ConfigError(
                "declarations.yaml must have exactly one of buckets or profile",
                file=path,
                key="profile",
                fix="remove either buckets or profile",
            )
        raise ConfigError(
            "declarations.yaml must have exactly one of buckets or profile",
            file=path,
            key="buckets",
            fix="add buckets or import a profile such as profile: four-bucket",
        )
    if has_buckets:
        return _buckets(require(data, "buckets", path), path, "buckets"), None

    profile = require_text(require(data, "profile", path), path, "profile")
    profile_root = Path(__file__).resolve().parents[3] / "profiles"
    if profiles_dir is not None:
        profile_root = Path(profiles_dir)
    if not profile_root.is_dir():
        raise ConfigError(
            "Missing profiles directory",
            file=profile_root,
            key="profile",
            fix="create the profiles directory or pass profiles_dir to load_declarations",
        )
    profile_path = profile_root / f"{profile}.yaml"
    if not profile_path.is_file():
        raise ConfigError(
            f"Missing profile {profile!r}",
            file=profile_path,
            key="profile",
            fix=f"create {profile_path.name} under {profile_root} or choose an existing profile",
        )
    profile_data = load_mapping(profile_path)
    reject_unknown_keys(profile_data, ("name", "description", "buckets"), profile_path)
    buckets = _buckets(require(profile_data, "buckets", profile_path), profile_path, "buckets")
    return buckets, profile


def _buckets(value: Any, path: Path, *parents: str) -> tuple[Bucket, ...]:
    rows = require_list(value, path, *parents)
    if not rows:
        raise ConfigError(
            "buckets must list at least one bucket",
            file=path,
            key=key_path(*parents),
            fix="add at least one bucket with name, essential, and fixed",
        )
    buckets: list[Bucket] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        row_path = (*parents, f"[{index}]")
        entry = require_mapping(row, path, *row_path)
        reject_unknown_keys(entry, BUCKET_KEYS, path, *row_path)
        name = require_text(require(entry, "name", path, *row_path), path, *row_path, "name")
        if name in seen:
            raise ConfigError(
                f"Duplicate bucket {name!r}",
                file=path,
                key=key_path(*row_path, "name"),
                fix="give each bucket a distinct name",
            )
        seen.add(name)
        essential = _require_bool(
            require(entry, "essential", path, *row_path),
            path,
            *row_path,
            "essential",
        )
        fixed = _require_bool(require(entry, "fixed", path, *row_path), path, *row_path, "fixed")
        buckets.append(Bucket(name=name, essential=essential, fixed=fixed))
    return tuple(buckets)


def _mapping_source(data: dict[str, Any], path: Path) -> str:
    if "mapping_source" not in data:
        return "tiller_group"
    source = require_text(data["mapping_source"], path, "mapping_source")
    if source not in MAPPING_SOURCES:
        raise ConfigError(
            f"Unknown mapping_source {source!r}",
            file=path,
            key="mapping_source",
            fix="use one of ['tiller_group', 'explicit']",
        )
    return source


def _bucket_map(
    value: Any,
    declared_buckets: set[str],
    bucket_names: tuple[str, ...],
    path: Path,
    *parents: str,
) -> tuple[tuple[str, str], ...]:
    rows = require_mapping(value, path, *parents)
    if not rows:
        raise ConfigError(
            f"{parents[-1]} must map at least one name to a bucket",
            file=path,
            key=key_path(*parents),
            fix="map each Tiller group or category to one declared bucket",
        )
    result: list[tuple[str, str]] = []
    for raw_name, raw_bucket in rows.items():
        name = require_text(raw_name, path, *parents, str(raw_name))
        bucket = require_text(raw_bucket, path, *parents, name)
        _require_bucket(bucket, declared_buckets, bucket_names, path, *parents, name)
        result.append((name, bucket))
    return tuple(result)


def _unique_text_list(value: Any, path: Path, *parents: str) -> tuple[str, ...]:
    rows = require_list(value, path, *parents)
    result: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        item = require_text(raw, path, *parents, f"[{index}]")
        if item in seen:
            raise ConfigError(
                f"Duplicate value {item!r}",
                file=path,
                key=key_path(*parents, f"[{index}]"),
                fix="list each value once",
            )
        seen.add(item)
        result.append(item)
    return tuple(result)


def _overrides(
    value: Any, declared_buckets: set[str], bucket_names: tuple[str, ...], path: Path
) -> tuple[Override, ...]:
    rows = require_mapping(value, path, "overrides")
    result: list[Override] = []
    for raw_category, raw_entry in rows.items():
        category = require_text(raw_category, path, "overrides", str(raw_category))
        parents = ("overrides", category)
        entry = require_mapping(raw_entry, path, *parents)
        reject_unknown_keys(entry, OVERRIDE_KEYS, path, *parents)
        bucket = require_text(require(entry, "bucket", path, *parents), path, *parents, "bucket")
        _require_bucket(bucket, declared_buckets, bucket_names, path, *parents, "bucket")
        reason = require_text(require(entry, "reason", path, *parents), path, *parents, "reason")
        result.append(Override(category=category, bucket=bucket, reason=reason))
    return tuple(result)


def _splits(
    value: Any,
    declared_buckets: set[str],
    bucket_names: tuple[str, ...],
    conflict_categories: set[str],
    path: Path,
) -> tuple[Split, ...]:
    rows = require_mapping(value, path, "splits")
    result: list[Split] = []
    for raw_category, raw_entry in rows.items():
        category = require_text(raw_category, path, "splits", str(raw_category))
        parents = ("splits", category)
        if category in conflict_categories:
            raise ConfigError(
                f"Category {category!r} is also in overrides",
                file=path,
                key=key_path(*parents),
                fix="keep the category in splits or overrides, not both",
            )
        entry = require_mapping(raw_entry, path, *parents)
        reject_unknown_keys(entry, SPLIT_KEYS, path, *parents)
        weights = _bucket_weights(
            require(entry, "weights", path, *parents),
            declared_buckets,
            bucket_names,
            path,
            *parents,
            "weights",
        )
        reason = require_text(require(entry, "reason", path, *parents), path, *parents, "reason")
        result.append(Split(category=category, weights=weights, reason=reason))
    return tuple(result)


def _bucket_weights(
    value: Any,
    declared_buckets: set[str],
    bucket_names: tuple[str, ...],
    path: Path,
    *parents: str,
) -> tuple[tuple[str, Decimal], ...]:
    rows = require_mapping(value, path, *parents)
    if not rows:
        raise ConfigError(
            "weights must list at least two buckets",
            file=path,
            key=key_path(*parents),
            fix="write weights as {Bucket One: 0.5, Bucket Two: 0.5}",
        )
    weights: list[tuple[str, Decimal]] = []
    for raw_bucket, raw_weight in rows.items():
        bucket = require_text(raw_bucket, path, *parents, str(raw_bucket))
        _require_bucket(bucket, declared_buckets, bucket_names, path, *parents, bucket)
        weights.append((bucket, _decimal_weight(raw_weight, path, *parents, bucket)))
    if len(weights) < 2:
        raise ConfigError(
            "split weights must list at least two buckets",
            file=path,
            key=key_path(*parents),
            fix="split the category across two or more declared buckets",
        )
    _require_sum_one(weights, path, *parents)
    return tuple(weights)


def _sharing(
    value: Any, known_people: set[str] | None, path: Path
) -> tuple[SharingRule, ...]:
    rows = require_list(value, path, "sharing")
    result: list[SharingRule] = []
    for index, row in enumerate(rows):
        parents = ("sharing", f"[{index}]")
        entry = require_mapping(row, path, *parents)
        reject_unknown_keys(entry, SHARING_KEYS, path, *parents)
        account, description, category = _match(
            require(entry, "match", path, *parents),
            path,
            *parents,
            "match",
        )
        weights = _person_weights(
            require(entry, "weights", path, *parents),
            known_people,
            path,
            *parents,
            "weights",
        )
        reason = require_text(require(entry, "reason", path, *parents), path, *parents, "reason")
        result.append(
            SharingRule(
                account=account,
                description=description,
                category=category,
                weights=weights,
                reason=reason,
            )
        )
    return tuple(result)


def _match(value: Any, path: Path, *parents: str) -> tuple[str | None, str | None, str | None]:
    match = require_mapping(value, path, *parents)
    reject_unknown_keys(match, MATCH_KEYS, path, *parents)
    if not any(key in match for key in MATCH_KEYS):
        raise ConfigError(
            "match must include at least one key",
            file=path,
            key=key_path(*parents),
            fix="add account, description, category, or a combination of them",
        )
    account = None
    description = None
    category = None
    if "account" in match:
        account = require_text(match["account"], path, *parents, "account")
    if "description" in match:
        description = require_text(match["description"], path, *parents, "description")
    if "category" in match:
        category = require_text(match["category"], path, *parents, "category")
    return account, description, category


def _person_weights(
    value: Any, known_people: set[str] | None, path: Path, *parents: str
) -> tuple[tuple[str, Decimal], ...]:
    rows = require_mapping(value, path, *parents)
    if not rows:
        raise ConfigError(
            "weights must list at least one person",
            file=path,
            key=key_path(*parents),
            fix="write weights such as {alex: 0.5, sam: 0.5}",
        )
    weights: list[tuple[str, Decimal]] = []
    for raw_slug, raw_weight in rows.items():
        slug = require_text(raw_slug, path, *parents, str(raw_slug))
        if known_people is not None and slug not in known_people:
            raise ConfigError(
                f"Unknown person slug {slug!r}",
                file=path,
                key=key_path(*parents, slug),
                fix=f"use one of {sorted(known_people)} or add the person to household.yaml",
            )
        weights.append((slug, _decimal_weight(raw_weight, path, *parents, slug)))
    _require_sum_one(weights, path, *parents)
    return tuple(weights)


def _closed_accounts(value: Any, path: Path) -> tuple[ClosedAccount, ...]:
    rows = require_mapping(value, path, "closed_accounts")
    result: list[ClosedAccount] = []
    for raw_name, raw_entry in rows.items():
        name = require_text(raw_name, path, "closed_accounts", str(raw_name))
        parents = ("closed_accounts", name)
        entry = require_mapping(raw_entry, path, *parents)
        reject_unknown_keys(entry, CLOSED_ACCOUNT_KEYS, path, *parents)
        closed = _closed_date(require(entry, "closed", path, *parents), path, *parents, "closed")
        note = None
        if "note" in entry:
            note = require_text(entry["note"], path, *parents, "note")
        result.append(ClosedAccount(name=name, closed=closed, note=note))
    return tuple(result)


def _closed_date(value: Any, path: Path, *parents: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            parsed = date.fromisoformat(text)
        except ValueError:
            parsed = None
        if parsed is not None and text == parsed.isoformat():
            return parsed
    raise ConfigError(
        f"closed is not an ISO date: {value!r}",
        file=path,
        key=key_path(*parents),
        fix="write closed as YYYY-MM-DD",
    )


def _require_bool(value: Any, path: Path, *parents: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(
            "Expected true or false",
            file=path,
            key=key_path(*parents),
            fix="use YAML true or false",
        )
    return value


def _decimal_weight(value: Any, path: Path, *parents: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        weight = Decimal("NaN")
    else:
        try:
            weight = Decimal(str(value))
        except (InvalidOperation, ValueError):
            weight = Decimal("NaN")
    if not weight.is_finite() or weight <= 0 or weight > 1:
        raise ConfigError(
            f"Invalid weight {value!r}",
            file=path,
            key=key_path(*parents),
            fix="use a number greater than 0 and at most 1",
        )
    return weight


def _require_sum_one(
    weights: tuple[tuple[str, Decimal], ...] | list[tuple[str, Decimal]],
    path: Path,
    *parents: str,
) -> None:
    total = sum(weight for _name, weight in weights)
    if total != 1:
        raise ConfigError(
            f"Weights sum to {total}, not 1",
            file=path,
            key=key_path(*parents),
            fix="make the weights sum to exactly 1",
        )


def _require_bucket(
    bucket: str,
    declared_buckets: set[str],
    bucket_names: tuple[str, ...],
    path: Path,
    *parents: str,
) -> None:
    if bucket not in declared_buckets:
        raise ConfigError(
            f"Unknown bucket {bucket!r}",
            file=path,
            key=key_path(*parents),
            fix=f"use one of {list(bucket_names)}",
        )
