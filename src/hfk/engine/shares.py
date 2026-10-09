"""Ownership share calculations for ledger transactions."""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from hfk.config import Declarations, Household, SharingRule
from hfk.ledger import Ledger, Transaction, money

CONFLICT_FIX = (
    "narrow the match of one rule or give both the same weights; "
    "rules are never ordered or merged"
)


@dataclass(frozen=True)
class ShareError(ValueError):
    """Raised when a transaction cannot be assigned to household members."""

    problem: str
    fix: str
    transaction: Transaction | None = None

    def __post_init__(self) -> None:
        ValueError.__init__(self, str(self))

    def __str__(self) -> str:
        return f"{self.problem}. Fix: {self.fix}"


@dataclass(frozen=True, init=False)
class ShareConflictError(ShareError):
    """Raised when unordered sharing rules disagree for one transaction."""

    def __init__(self, transaction: Transaction, rules: tuple[SharingRule, ...]) -> None:
        reasons = "; ".join(rule.reason for rule in rules)
        problem = (
            "Conflicting sharing rules match transaction "
            f'{transaction.date} "{transaction.description}" on "{transaction.account}" '
            f"amount {transaction.amount}: {reasons}"
        )
        super().__init__(problem, CONFLICT_FIX, transaction)


@dataclass(frozen=True)
class Share:
    person: str
    amount: Decimal


@dataclass(frozen=True)
class TransactionShares:
    transaction: Transaction
    weights: tuple[tuple[str, Decimal], ...]
    shares: tuple[Share, ...]
    rule: SharingRule | None

    def amount_for(self, slug: str) -> Decimal:
        for share in self.shares:
            if share.person == slug:
                return share.amount
        return Decimal("0.00")


def share_weights(
    transaction: Transaction, household: Household, declarations: Declarations
) -> tuple[tuple[tuple[str, Decimal], ...], SharingRule | None]:
    """Return the weights for ``transaction`` and the matching override rule, if any."""

    matches = tuple(
        rule for rule in declarations.sharing if _rule_matches_transaction(rule, transaction)
    )
    if matches:
        first = matches[0]
        first_weights = _weights_key(first.weights)
        conflicts = tuple(rule for rule in matches if _weights_key(rule.weights) != first_weights)
        if conflicts:
            raise ShareConflictError(transaction, matches)
        return first.weights, first

    account = household.account(transaction.account)
    if account is None:
        raise ShareError(
            f'Account "{transaction.account}" has no ownership declaration',
            f'declare "{transaction.account}" under accounts in household.yaml with owner or shared',
            transaction,
        )
    return account.weights, None


def share_transaction(
    transaction: Transaction, household: Household, declarations: Declarations
) -> TransactionShares:
    """Compute per-person shares for one transaction, reconciling rounded cents."""

    weights, rule = share_weights(transaction, household, declarations)
    share_rows = [
        Share(person=person, amount=money(transaction.amount * weight))
        for person, weight in weights
    ]
    total = sum((share.amount for share in share_rows), Decimal("0.00"))
    residual = transaction.amount - total
    if residual:
        residual_index = _largest_weight_index(weights)
        current = share_rows[residual_index]
        share_rows[residual_index] = Share(
            person=current.person,
            amount=current.amount + residual,
        )

    return TransactionShares(
        transaction=transaction,
        weights=weights,
        shares=tuple(share_rows),
        rule=rule,
    )


def share_ledger(
    ledger: Ledger, household: Household, declarations: Declarations
) -> tuple[TransactionShares, ...]:
    """Compute shares for every ledger transaction in ledger order."""

    return tuple(
        share_transaction(transaction, household, declarations)
        for transaction in ledger.transactions
    )


def person_total(shares: Iterable[TransactionShares], slug: str) -> Decimal:
    """Sum one person's share across already-computed transaction shares."""

    return sum(
        (transaction_shares.amount_for(slug) for transaction_shares in shares),
        Decimal("0.00"),
    )


def _rule_matches_transaction(rule: SharingRule, transaction: Transaction) -> bool:
    if rule.account is not None and rule.account != transaction.account:
        return False
    if rule.category is not None and rule.category != transaction.category:
        return False
    if rule.description is not None:
        description = transaction.description.lower()
        pattern = rule.description.lower()
        if not fnmatch.fnmatchcase(description, pattern):
            return False
    return True


def _weights_key(weights: tuple[tuple[str, Decimal], ...]) -> frozenset[tuple[str, Decimal]]:
    return frozenset(weights)


def _largest_weight_index(weights: tuple[tuple[str, Decimal], ...]) -> int:
    return max(range(len(weights)), key=lambda index: weights[index][1])
