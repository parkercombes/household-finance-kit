"""Instance diagnostics for ``hfk doctor``."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from hfk.config import (
    ConfigError,
    Declarations,
    Household,
    Month,
    Plan,
    SharingRule,
    load_declarations,
    load_household,
    load_plan,
)
from hfk.engine.buckets import BucketError, resolve_category
from hfk.engine.shares import ShareConflictError, ShareError, share_weights
from hfk.ledger import Category, Ledger, Transaction
from hfk.source import TillerFormatError, find_workbook, read_tiller

DIAGNOSTIC_LEVELS = frozenset({"error", "warning"})
WORKBOOK_FIX = "download the Tiller workbook into data/ (or fix files.tiller_glob)"


@dataclass(frozen=True)
class Diagnostic:
    level: str
    code: str
    where: str
    message: str
    fix: str

    def __post_init__(self) -> None:
        if self.level not in DIAGNOSTIC_LEVELS:
            allowed = ", ".join(sorted(DIAGNOSTIC_LEVELS))
            raise ValueError(f"Invalid diagnostic level {self.level!r}; allowed values: {allowed}")

    def render(self) -> str:
        return f"{self.level}: {self.where}: {self.message}. Fix: {self.fix}"


@dataclass(frozen=True)
class DoctorReport:
    diagnostics: tuple[Diagnostic, ...]

    @property
    def ok(self) -> bool:
        return not self.errors()

    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(diagnostic for diagnostic in self.diagnostics if diagnostic.level == "error")

    def warnings(self) -> tuple[Diagnostic, ...]:
        return tuple(diagnostic for diagnostic in self.diagnostics if diagnostic.level == "warning")


def run_doctor(
    home: Path, *, today: date | None = None, stale_after_days: int = 14
) -> DoctorReport:
    """Run read-only diagnostics for an hfk private instance."""

    home = Path(home)
    today = date.today() if today is None else today  # noqa: DTZ011
    diagnostics: list[Diagnostic] = []

    household = _load_household(home, diagnostics)
    people = household.slugs if household is not None else None
    declarations = _load_declarations(home, people=people, diagnostics=diagnostics)
    plan: Plan | None = None
    plan_duplicates_checked = False
    if declarations is None:
        diagnostics.append(
            Diagnostic(
                "error",
                "config-error",
                "plan.yaml",
                "plan.yaml was not checked because declarations.yaml failed key=plan",
                "fix declarations.yaml first, then rerun doctor",
            )
        )
    else:
        plan = _load_plan(home, declarations=declarations, people=people, diagnostics=diagnostics)

    workbook_path: Path | None = None
    ledger: Ledger | None = None
    if household is not None:
        workbook_path, ledger = _read_source(home, household, diagnostics)

    if household is not None and ledger is not None:
        _check_accounts(household, declarations, ledger, diagnostics)
        if declarations is not None:
            _check_category_orphans(declarations, ledger, diagnostics)
            _check_closed_accounts(household, declarations, ledger, diagnostics)
            if plan is not None:
                _check_plan_category_buckets(plan, declarations, ledger, diagnostics)
                _check_plan_category_duplicates(plan, diagnostics)
                plan_duplicates_checked = True
            _check_sharing_rule_conflicts(household, declarations, ledger, diagnostics)
        _check_stale_data(ledger, workbook_path, today, stale_after_days, diagnostics)
        _check_history_start(household, ledger, diagnostics)

    if plan is not None and not plan_duplicates_checked:
        _check_plan_category_duplicates(plan, diagnostics)

    return DoctorReport(tuple(diagnostics))


def _load_household(home: Path, diagnostics: list[Diagnostic]) -> Household | None:
    try:
        return load_household(home)
    except ConfigError as error:
        diagnostics.append(_config_diagnostic(error))
        return None


def _load_declarations(
    home: Path, *, people: tuple[str, ...] | None, diagnostics: list[Diagnostic]
) -> Declarations | None:
    try:
        return load_declarations(home, people=people)
    except ConfigError as error:
        diagnostics.append(_config_diagnostic(error))
        return None


def _load_plan(
    home: Path,
    *,
    declarations: Declarations,
    people: tuple[str, ...] | None,
    diagnostics: list[Diagnostic],
) -> Plan | None:
    try:
        return load_plan(home, declarations=declarations, people=people)
    except ConfigError as error:
        diagnostics.append(_config_diagnostic(error))
        return None


def _config_diagnostic(error: ConfigError) -> Diagnostic:
    return Diagnostic(
        "error",
        "config-error",
        error.file.name,
        f"{error.problem} key={error.key}",
        error.fix,
    )


def _read_source(
    home: Path, household: Household, diagnostics: list[Diagnostic]
) -> tuple[Path | None, Ledger | None]:
    try:
        workbook_path = find_workbook(home / "data", household.tiller_glob)
    except TillerFormatError as error:
        diagnostics.append(
            Diagnostic(
                "error",
                "workbook-missing",
                f"data/{household.tiller_glob}",
                str(error),
                WORKBOOK_FIX,
            )
        )
        return None, None

    try:
        ledger = read_tiller(workbook_path)
    except TillerFormatError as error:
        diagnostics.append(
            Diagnostic(
                "error",
                "workbook-unreadable",
                workbook_path.name,
                str(error),
                WORKBOOK_FIX,
            )
        )
        return workbook_path, None

    if not ledger.transactions:
        diagnostics.append(
            Diagnostic(
                "error",
                "workbook-empty",
                workbook_path.name,
                "workbook has zero transactions",
                WORKBOOK_FIX,
            )
        )
    return workbook_path, ledger


def _check_accounts(
    household: Household,
    declarations: Declarations | None,
    ledger: Ledger,
    diagnostics: list[Diagnostic],
) -> None:
    declared_accounts = {account.name for account in household.accounts}
    closed_accounts = (
        set() if declarations is None else {account.name for account in declarations.closed_accounts}
    )
    ledger_accounts = set(ledger.account_names())

    for name in sorted(ledger_accounts - declared_accounts - closed_accounts):
        diagnostics.append(
            Diagnostic(
                "error",
                "account-undeclared",
                "household.yaml",
                f'ledger account "{name}" is not declared',
                f'add "{name}" under accounts with owner or shared, '
                "or under closed_accounts in declarations.yaml if it is closed",
            )
        )

    for name in sorted(declared_accounts - ledger_accounts):
        diagnostics.append(
            Diagnostic(
                "warning",
                "account-unused",
                "household.yaml",
                f'declared account "{name}" does not appear in the workbook',
                "remove it or check the workbook",
            )
        )


def _check_category_orphans(
    declarations: Declarations, ledger: Ledger, diagnostics: list[Diagnostic]
) -> None:
    visible_categories = [category for category in ledger.categories if not category.hidden]
    ordered_names = _category_names_in_ledger_order(visible_categories, ledger)
    groups = dict(declarations.groups)
    categories = dict(declarations.categories)
    non_spend_groups = set(declarations.non_spend_groups)
    reported_groups: set[str] = set()

    for name in ordered_names:
        category = ledger.category(name)
        if category is None:
            if not _has_category_judgment(declarations, name):
                diagnostics.append(
                    Diagnostic(
                        "error",
                        "category-orphan",
                        "declarations.yaml",
                        f'category "{name}" appears in transactions but not in the '
                        "Categories sheet",
                        f'add "{name}" back to the Categories sheet in Tiller, or add '
                        f'overrides."{name}" with a bucket and reason in declarations.yaml; '
                        "history is never remapped silently",
                    )
                )
            continue

        if _category_excluded_from_spend(category, non_spend_groups):
            continue
        if _has_category_judgment(declarations, name):
            continue
        if declarations.mapping_source == "tiller_group":
            if category.group in groups or category.group in reported_groups:
                continue
            reported_groups.add(category.group)
            diagnostics.append(
                Diagnostic(
                    "error",
                    "group-unmapped",
                    "declarations.yaml",
                    f'group "{category.group}" (category "{name}") has no bucket',
                    f'add groups."{category.group}": <bucket> in declarations.yaml, '
                    "or list it under non_spend_groups",
                )
            )
            continue

        if name not in categories:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "category-unmapped",
                    "declarations.yaml",
                    f'category "{name}" has no bucket',
                    f'add categories."{name}": <bucket> in declarations.yaml',
                )
            )


def _category_names_in_ledger_order(categories: list[Category], ledger: Ledger) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for category in categories:
        name = category.name
        if name not in seen:
            seen.add(name)
            names.append(name)
    for transaction in ledger.transactions:
        if transaction.category not in seen:
            seen.add(transaction.category)
            names.append(transaction.category)
    return tuple(names)


def _has_category_judgment(declarations: Declarations, name: str) -> bool:
    return declarations.split(name) is not None or declarations.override(name) is not None


def _category_excluded_from_spend(category: Category, non_spend_groups: set[str]) -> bool:
    return category.type in {"Income", "Transfer"} or category.group in non_spend_groups


def _check_closed_accounts(
    household: Household,
    declarations: Declarations,
    ledger: Ledger,
    diagnostics: list[Diagnostic],
) -> None:
    open_accounts = {account.name for account in household.accounts}
    transactions_by_account: dict[str, list[date]] = {}
    for transaction in ledger.transactions:
        transactions_by_account.setdefault(transaction.account, []).append(transaction.date)

    for account in declarations.closed_accounts:
        if account.name in open_accounts:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "account-closed-and-open",
                    "declarations.yaml",
                    f'account "{account.name}" is declared as open and closed',
                    "declare the account in exactly one place",
                )
            )

        latest = max(transactions_by_account.get(account.name, ()), default=None)
        if latest is None or latest <= account.closed:
            continue
        diagnostics.append(
            Diagnostic(
                "error",
                "closed-account-active",
                "declarations.yaml",
                f'account "{account.name}" closed {account.closed.isoformat()} but has '
                f"activity through {latest.isoformat()}",
                f"move it back under accounts in household.yaml, or set closed to "
                f"{latest.isoformat()} or later",
            )
        )


def _check_plan_category_buckets(
    plan: Plan,
    declarations: Declarations,
    ledger: Ledger,
    diagnostics: list[Diagnostic],
) -> None:
    for index, line in enumerate(plan.lines):
        for category in line.categories:
            try:
                resolution = resolve_category(category, ledger, declarations)
            except BucketError:
                continue

            mapped_buckets = tuple(portion.bucket for portion in resolution.portions)
            if not resolution.excluded and line.bucket in mapped_buckets:
                continue

            mapped_text = "excluded from spend" if resolution.excluded else ", ".join(mapped_buckets)
            fix_bucket = "a mapped spend bucket" if resolution.excluded else mapped_text
            diagnostics.append(
                Diagnostic(
                    "error",
                    "plan-category-bucket-mismatch",
                    "plan.yaml",
                    f'plan.lines[{index}].categories desc "{line.desc}" who "{line.who}" '
                    f'lists category "{category}" on bucket "{line.bucket}", but it maps to '
                    f"{mapped_text}",
                    f"move the category to a line in {fix_bucket}, or change the declarations "
                    "mapping, override, or split for it",
                )
            )


def _check_plan_category_duplicates(plan: Plan, diagnostics: list[Diagnostic]) -> None:
    rows: dict[tuple[str, str], list[tuple[int, Month, Month | None]]] = {}
    for index, line in enumerate(plan.lines):
        for category in line.categories:
            rows.setdefault((line.who, category), []).append(
                (index, line.effective_from, line.effective_until)
            )

    for (who, category), entries in rows.items():
        for left_pos, left in enumerate(entries):
            for right in entries[left_pos + 1 :]:
                overlap = _first_overlapping_month(left[1], left[2], right[1], right[2])
                if overlap is None:
                    continue
                diagnostics.append(
                    Diagnostic(
                        "error",
                        "plan-category-duplicate",
                        "plan.yaml",
                        f'plan.lines[{left[0]}].categories and plan.lines[{right[0]}].categories '
                        f'list category "{category}" for "{who}" with first overlapping month '
                        f"{overlap}",
                        "end one line with effective_until before the other starts, or remove "
                        "the category from one of them",
                    )
                )


def _first_overlapping_month(
    left_from: Month,
    left_until: Month | None,
    right_from: Month,
    right_until: Month | None,
) -> Month | None:
    start = max(left_from, right_from)
    if left_until is None:
        end = right_until
    elif right_until is None:
        end = left_until
    else:
        end = min(left_until, right_until)
    if end is not None and end < start:
        return None
    return start


def _check_sharing_rule_conflicts(
    household: Household,
    declarations: Declarations,
    ledger: Ledger,
    diagnostics: list[Diagnostic],
) -> None:
    reported: set[frozenset[str]] = set()
    for transaction in ledger.transactions:
        try:
            share_weights(transaction, household, declarations)
        except ShareConflictError:
            reasons = frozenset(
                rule.reason
                for rule in declarations.sharing
                if _sharing_rule_matches_transaction(rule, transaction)
            )
            if reasons in reported:
                continue
            reported.add(reasons)
            diagnostics.append(
                Diagnostic(
                    "error",
                    "sharing-rule-conflict",
                    "declarations.yaml",
                    "conflicting sharing rules match first transaction "
                    f'{transaction.date.isoformat()} "{transaction.description}" on '
                    f'"{transaction.account}": {", ".join(sorted(reasons))}',
                    "narrow the match of one rule or give both the same weights; rules are never "
                    "ordered or merged",
                )
            )
        except ShareError:
            continue


def _sharing_rule_matches_transaction(rule: SharingRule, transaction: Transaction) -> bool:
    if rule.account is not None and rule.account != transaction.account:
        return False
    if rule.category is not None and rule.category != transaction.category:
        return False
    return rule.description is None or fnmatch.fnmatchcase(
        transaction.description.lower(), rule.description.lower()
    )


def _check_stale_data(
    ledger: Ledger,
    workbook_path: Path | None,
    today: date,
    stale_after_days: int,
    diagnostics: list[Diagnostic],
) -> None:
    if not ledger.transactions:
        return
    latest = max(transaction.date for transaction in ledger.transactions)
    days_old = (today - latest).days
    if days_old > stale_after_days:
        diagnostics.append(
            Diagnostic(
                "warning",
                "data-stale",
                _workbook_where(workbook_path),
                f"latest transaction is {latest.isoformat()} ({days_old} days old)",
                "download a fresh workbook into data/",
            )
        )


def _check_history_start(
    household: Household, ledger: Ledger, diagnostics: list[Diagnostic]
) -> None:
    if not ledger.transactions:
        return
    latest = max(transaction.date for transaction in ledger.transactions)
    if household.history_start is None:
        diagnostics.append(
            Diagnostic(
                "warning",
                "history-start-missing",
                "household.yaml",
                "history_start is not set",
                "add history_start: YYYY-MM-DD so setup noise stays out of reports",
            )
        )
        return

    if household.history_start > latest:
        diagnostics.append(
            Diagnostic(
                "error",
                "history-start-after-data",
                "household.yaml",
                "history_start "
                f"{household.history_start.isoformat()} is after latest transaction "
                f"{latest.isoformat()}",
                "move history_start earlier",
            )
        )
        return

    before_count = sum(
        1 for transaction in ledger.transactions if transaction.date < household.history_start
    )
    if before_count:
        diagnostics.append(
            Diagnostic(
                "warning",
                "history-start-clamps",
                "household.yaml",
                f"{before_count} transactions before {household.history_start.isoformat()} "
                "are excluded from every report",
                "none needed; this is a reminder",
            )
        )


def _workbook_where(workbook_path: Path | None) -> str:
    if workbook_path is None:
        return "workbook"
    return workbook_path.name
