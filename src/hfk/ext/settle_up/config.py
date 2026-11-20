"""``settle_up.yaml``: who pays each shared account (M7-04; ADR-0016, ADR-0017).

::

    schema_version: 1
    payers:
      "Joint Card": {alex: 1.0}     # Alex pays the whole card bill
      "Joint Checking": {alex: 0.5, sam: 0.5}

A charge on an account with a single ``owner`` in ``household.yaml`` was paid
by that owner and needs no entry. Every shared account that carries a shared
charge in the month being settled needs one; a missing entry is a loud error
naming the account, never a guess. Weights sum to exactly one.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from hfk.config import ConfigError, Household
from hfk.config._yaml import reject_unknown_keys, require, require_mapping, require_schema_version
from hfk.config.errors import key_path

CONFIG_FILE = "settle_up.yaml"
TOP_LEVEL_KEYS = ("schema_version", "payers")


@dataclass(frozen=True)
class SettleUpConfig:
    path: Path
    payers: tuple[tuple[str, tuple[tuple[str, Decimal], ...]], ...]

    def payer_weights(self, account: str) -> tuple[tuple[str, Decimal], ...] | None:
        for name, weights in self.payers:
            if name == account:
                return weights
        return None


def load_settle_up(data: dict[str, Any], path: Path) -> SettleUpConfig:
    """Validate a loaded ``settle_up.yaml`` mapping (the extension's ``schema``)."""

    reject_unknown_keys(data, TOP_LEVEL_KEYS, path)
    require_schema_version(data, path)
    rows = require_mapping(require(data, "payers", path), path, "payers")
    payers: list[tuple[str, tuple[tuple[str, Decimal], ...]]] = []
    for raw_account, raw_weights in rows.items():
        account = str(raw_account)
        parents = ("payers", account)
        entry = require_mapping(raw_weights, path, *parents)
        if not entry:
            raise ConfigError(
                "payer weights are empty",
                file=path,
                key=key_path(*parents),
                fix="write who pays the account's bill, such as {alex: 1.0}",
            )
        weights: list[tuple[str, Decimal]] = []
        for raw_slug, raw_weight in entry.items():
            slug = str(raw_slug)
            try:
                weight = (
                    Decimal(str(raw_weight))
                    if isinstance(raw_weight, (int, float)) and not isinstance(raw_weight, bool)
                    else None
                )
            except InvalidOperation:
                weight = None
            if weight is None or not weight.is_finite() or not 0 <= weight <= 1:
                raise ConfigError(
                    f"Invalid weight {raw_weight!r}",
                    file=path,
                    key=key_path(*parents, slug),
                    fix="use a number from 0 to 1",
                )
            weights.append((slug, weight))
        total = sum(weight for _slug, weight in weights)
        if total != 1:
            raise ConfigError(
                f"Payer weights sum to {total}, not 1",
                file=path,
                key=key_path(*parents),
                fix="make the weights sum to exactly 1, such as {alex: 1.0} or "
                "{alex: 0.5, sam: 0.5}",
            )
        payers.append((account, tuple(weights)))
    return SettleUpConfig(path=path, payers=tuple(payers))


def check_payers(config: SettleUpConfig, household: Household) -> None:
    """Every payer entry names a shared account and household people."""

    for account, weights in config.payers:
        declared = household.account(account)
        if declared is None:
            raise ConfigError(
                f"Unknown account {account!r}",
                file=config.path,
                key=key_path("payers", account),
                fix="use an account name from household.yaml",
            )
        if declared.owner is not None:
            raise ConfigError(
                f"{account!r} has a single owner, {declared.owner}, who pays its charges",
                file=config.path,
                key=key_path("payers", account),
                fix="remove this entry; only shared accounts need payers",
            )
        for slug, _weight in weights:
            if slug not in household.slugs:
                raise ConfigError(
                    f"Unknown person slug {slug!r}",
                    file=config.path,
                    key=key_path("payers", account, slug),
                    fix=f"use one of {list(household.slugs)} from household.yaml",
                )


__all__ = ["CONFIG_FILE", "SettleUpConfig", "check_payers", "load_settle_up"]
