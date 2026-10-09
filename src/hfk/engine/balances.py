"""Per-account balance report from Balance History, design brief section 7.

`hfk balances --as-of YYYY-MM-DD` reports every account's latest balance
observation on or before the requested date.

Gap rule (design brief: null amounts are gaps, never zero):

- The selected observation for an account is the considered observation with
  the greatest date; when two observations share that date, the later row in
  sheet order wins.
- If no observation is considered, the account is a gap with the reason
  ``no balance history on or before <cutoff ISO>``. An account with no
  Balance History rows at all is still reported as such a gap.
- If the selected observation's balance is blank (``None``), the account is a
  gap with the reason ``latest observation <ISO> is blank`` plus the most
  recent known non-blank value. A blank observation is never read as zero,
  and an older number is never silently promoted over it.

Closed-account cutoff:

- An account declared under ``declarations.yaml``'s ``closed_accounts`` is
  only considered up to its declared closure date: its cutoff is
  ``min(as_of, closed date)``. Open accounts use ``as_of`` itself.

Analysis window:

- When ``household.yaml`` sets ``history_start``, observations before it are
  ignored (and counted in ``ignored_before_history_start``), and an ``as_of``
  before ``history_start`` is refused.

Account order: ``household.accounts`` in file order, then declared closed
accounts in file order, then remaining Balance History account names sorted
by name. All money is `Decimal` cents from the reader; no totals are computed
here (net worth is M4-03).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from hfk.config import Declarations, Household
from hfk.ledger import BalanceRow, Ledger


@dataclass(frozen=True)
class BalancesError(ValueError):
    """Raised when a balances report cannot be built."""

    problem: str
    fix: str

    def __post_init__(self) -> None:
        ValueError.__init__(self, str(self))

    def __str__(self) -> str:
        return f"{self.problem}. Fix: {self.fix}"


@dataclass(frozen=True)
class AccountBalance:
    account: str
    account_class: str | None
    account_type: str | None
    balance: Decimal | None
    observed: date | None
    gap: bool
    gap_reason: str | None
    last_known: Decimal | None
    last_known_date: date | None
    closed: date | None
    declared: bool


@dataclass(frozen=True)
class BalancesReport:
    as_of: date
    accounts: tuple[AccountBalance, ...]
    gap_count: int
    ignored_before_history_start: int


def build_balances(
    *,
    ledger: Ledger,
    household: Household,
    declarations: Declarations,
    as_of: date,
) -> BalancesReport:
    """Build the per-account balances report for ``as_of``."""

    history_start = household.history_start
    if history_start is not None and as_of < history_start:
        raise BalancesError(
            f"as_of {as_of.isoformat()} is before history_start {history_start.isoformat()}",
            "choose a date on or after history_start",
        )

    ignored_before_history_start = 0
    if history_start is not None:
        ignored_before_history_start = sum(
            1 for balance in ledger.balances if balance.date < history_start
        )

    rows: list[AccountBalance] = []
    for name, declared, closed in _account_order(household, declarations, ledger):
        cutoff = as_of if closed is None else min(as_of, closed)
        considered = tuple(
            balance
            for balance in ledger.balances
            if balance.account == name
            and balance.date <= cutoff
            and (history_start is None or balance.date >= history_start)
        )
        rows.append(_account_balance(name, declared, closed, cutoff, considered))

    gap_count = sum(1 for row in rows if row.gap)
    return BalancesReport(
        as_of=as_of,
        accounts=tuple(rows),
        gap_count=gap_count,
        ignored_before_history_start=ignored_before_history_start,
    )


def _account_order(
    household: Household, declarations: Declarations, ledger: Ledger
) -> list[tuple[str, bool, date | None]]:
    """Yield ``(name, declared, closed)`` in report order for every account."""

    ordered: list[tuple[str, bool, date | None]] = []
    listed: set[str] = set()
    for account in household.accounts:
        closed = _closed_date(declarations, account.name)
        ordered.append((account.name, True, closed))
        listed.add(account.name)
    for account in declarations.closed_accounts:
        if account.name in listed:
            continue
        ordered.append((account.name, True, account.closed))
        listed.add(account.name)
    history_accounts = {balance.account for balance in ledger.balances}
    for name in sorted(history_accounts - listed):
        ordered.append((name, False, None))
    return ordered


def _closed_date(declarations: Declarations, name: str) -> date | None:
    account = declarations.closed_account(name)
    return None if account is None else account.closed


def _account_balance(
    name: str,
    declared: bool,
    closed: date | None,
    cutoff: date,
    considered: tuple[BalanceRow, ...],
) -> AccountBalance:
    selected = _latest(considered)
    if selected is None:
        return AccountBalance(
            account=name,
            account_class=None,
            account_type=None,
            balance=None,
            observed=None,
            gap=True,
            gap_reason=f"no balance history on or before {cutoff.isoformat()}",
            last_known=None,
            last_known_date=None,
            closed=closed,
            declared=declared,
        )

    if selected.balance is None:
        last_known_row = _latest(
            tuple(balance for balance in considered if balance.balance is not None)
        )
        return AccountBalance(
            account=name,
            account_class=selected.account_class,
            account_type=selected.account_type,
            balance=None,
            observed=selected.date,
            gap=True,
            gap_reason=f"latest observation {selected.date.isoformat()} is blank",
            last_known=None if last_known_row is None else last_known_row.balance,
            last_known_date=None if last_known_row is None else last_known_row.date,
            closed=closed,
            declared=declared,
        )

    return AccountBalance(
        account=name,
        account_class=selected.account_class,
        account_type=selected.account_type,
        balance=selected.balance,
        observed=selected.date,
        gap=False,
        gap_reason=None,
        last_known=None,
        last_known_date=None,
        closed=closed,
        declared=declared,
    )


def _latest(considered: tuple[BalanceRow, ...]) -> BalanceRow | None:
    """Return the greatest-date observation; later sheet rows win date ties."""

    latest: BalanceRow | None = None
    for balance in considered:
        if latest is None or balance.date >= latest.date:
            latest = balance
    return latest
