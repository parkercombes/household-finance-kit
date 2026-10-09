"""Net worth from Balance History, design brief section 7.

``hfk networth --as-of YYYY-MM-DD`` computes the household's position on a
date: the per-account balances that :func:`hfk.engine.balances.build_balances`
already selects are split into assets and liabilities by Tiller's ``Class``
metadata and summed.

Why gaps and unclassified accounts are excluded instead of counted as zero
(design brief: null amounts are gaps, never zero; flag, do not auto-fix):

- A gap means the account's value is unknown on the report date. Counting it
  as zero would invent a believable wrong total, and promoting an older
  number over a blank would lie about when it was last true. The account is
  therefore excluded from the totals, named in ``incomplete``, and warned
  about; the fix belongs in the Balance History sheet, not in arithmetic.
- An account whose ``Class`` is blank, or is neither Asset nor Liability
  once stripped and lowercased, cannot be placed on either side of the sum.
  Assigning it a side, or zeroing it, would be a silent default. It is
  excluded, flagged ``unclassified``, and named in ``incomplete``; the fix
  is to set ``Class`` in Tiller.

Closed accounts stop counting at their declared closure date: on or after
that date the line is excluded with the flag ``closed <ISO>`` and shows the
last observation on or before the closure date. Liabilities are summed
exactly as recorded (Tiller records them negative) and flagged
``liability positive`` when positive. Synced accounts are flagged
``stale (<days> days)`` when their observation is more than
``stale_after_days`` before ``as_of``; an account declared
``unsynced: true`` in ``household.yaml`` is never stale because its
hand-typed Balance History dates carry their own cadence. Undeclared
accounts are flagged ``undeclared``. Money is ``Decimal`` cents throughout,
and ``history_start`` clamping is inherited from ``build_balances``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from hfk.config import Declarations, Household
from hfk.engine.balances import BalancesError, build_balances
from hfk.ledger import Ledger

_ASSET = "asset"
_LIABILITY = "liability"


@dataclass(frozen=True)
class NetWorthError(ValueError):
    """Raised when a net worth report cannot be built."""

    problem: str
    fix: str

    def __post_init__(self) -> None:
        ValueError.__init__(self, str(self))

    def __str__(self) -> str:
        return f"{self.problem}. Fix: {self.fix}"


@dataclass(frozen=True)
class NetWorthLine:
    """One account's contribution to the net worth report."""

    account: str
    account_class: str | None
    balance: Decimal | None
    observed: date | None
    gap: bool
    gap_reason: str | None
    counted: bool
    flags: tuple[str, ...]
    closed: date | None
    declared: bool
    unsynced: bool


@dataclass(frozen=True)
class NetWorthReport:
    """The household's net worth position on ``as_of``."""

    as_of: date
    lines: tuple[NetWorthLine, ...]
    assets: Decimal
    liabilities: Decimal
    net_worth: Decimal
    counted: int
    excluded: tuple[str, ...]
    incomplete: tuple[str, ...]
    stale_after_days: int
    ignored_before_history_start: int


def build_networth(
    *,
    ledger: Ledger,
    household: Household,
    declarations: Declarations,
    as_of: date,
    stale_after_days: int = 14,
) -> NetWorthReport:
    """Build the net worth report for ``as_of``."""

    if not _valid_stale_after_days(stale_after_days):
        raise NetWorthError(
            f"stale_after_days must be a non-negative integer, not {stale_after_days!r}",
            "pass a whole number of days such as 14",
        )

    try:
        report = build_balances(
            ledger=ledger,
            household=household,
            declarations=declarations,
            as_of=as_of,
        )
    except BalancesError as error:
        raise NetWorthError(error.problem, error.fix) from error

    lines: list[NetWorthLine] = []
    assets = Decimal("0.00")
    liabilities = Decimal("0.00")
    excluded: list[str] = []
    incomplete: list[str] = []
    counted = 0
    for row in report.accounts:
        ownership = household.account(row.account)
        unsynced = ownership is not None and ownership.unsynced
        flags: list[str] = []
        line_counted = False
        if row.closed is not None and as_of >= row.closed:
            flags.append(f"closed {row.closed.isoformat()}")
        elif row.gap:
            incomplete.append(row.account)
        elif _classified(row.account_class):
            line_counted = True
            counted += 1
            if _is_asset(row.account_class):
                assets += row.balance
            else:
                liabilities += row.balance
                if row.balance > 0:
                    flags.append("liability positive")
            if unsynced:
                flags.append("unsynced")
            elif (as_of - row.observed).days > stale_after_days:
                flags.append(f"stale ({(as_of - row.observed).days} days)")
        else:
            flags.append("unclassified")
            incomplete.append(row.account)
        if not line_counted:
            excluded.append(row.account)
        if not row.declared:
            flags.append("undeclared")
        lines.append(
            NetWorthLine(
                account=row.account,
                account_class=row.account_class,
                balance=row.balance,
                observed=row.observed,
                gap=row.gap,
                gap_reason=row.gap_reason,
                counted=line_counted,
                flags=tuple(flags),
                closed=row.closed,
                declared=row.declared,
                unsynced=unsynced,
            )
        )

    if counted == 0:
        raise NetWorthError(
            f"no account has a balance observation on or before {as_of.isoformat()}",
            "choose a later date or check the Balance History sheet",
        )

    return NetWorthReport(
        as_of=as_of,
        lines=tuple(lines),
        assets=assets,
        liabilities=liabilities,
        net_worth=assets + liabilities,
        counted=counted,
        excluded=tuple(excluded),
        incomplete=tuple(incomplete),
        stale_after_days=stale_after_days,
        ignored_before_history_start=report.ignored_before_history_start,
    )


def _classified(account_class: str | None) -> bool:
    normalized = _normalized(account_class)
    return normalized == _ASSET or normalized == _LIABILITY


def _is_asset(account_class: str | None) -> bool:
    return _normalized(account_class) == _ASSET


def _normalized(account_class: str | None) -> str | None:
    if account_class is None:
        return None
    return account_class.strip().lower()


def _valid_stale_after_days(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
