"""Instance diagnostics for ``hfk doctor``."""

from __future__ import annotations

import fnmatch
from collections.abc import Callable, Iterable, Sequence
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
    load_instance_plan,
)
from hfk.engine.buckets import BucketError, resolve_category
from hfk.engine.shares import ShareConflictError, ShareError, share_weights
from hfk.ledger import Category, Ledger, Transaction
from hfk.source import (
    REQUIRED_SHEETS,
    TillerFormatError,
    find_workbook,
    read_tiller,
    workbook_sheet_names,
)

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
class ReadinessCheck:
    """One plain-language answer to "can I start using hfk?" for a new user."""

    name: str
    ready: bool
    detail: str
    fix: str = ""

    def render(self) -> str:
        status = "ready" if self.ready else "not ready"
        text = f"  {status}: {self.name}: {self.detail}"
        return text if self.ready else f"{text}. Fix: {self.fix}"


@dataclass(frozen=True)
class DoctorReport:
    diagnostics: tuple[Diagnostic, ...]
    readiness: tuple[ReadinessCheck, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors()

    @property
    def ready(self) -> bool:
        """True when every readiness check passes; it never changes the exit code."""

        return bool(self.readiness) and all(check.ready for check in self.readiness)

    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(diagnostic for diagnostic in self.diagnostics if diagnostic.level == "error")

    def warnings(self) -> tuple[Diagnostic, ...]:
        return tuple(diagnostic for diagnostic in self.diagnostics if diagnostic.level == "warning")


@dataclass(frozen=True)
class DoctorContext:
    """What an extension's doctor hook may inspect; every field is read-only input."""

    home: Path
    household: Household | None
    declarations: Declarations | None
    ledger: Ledger | None
    today: date


@dataclass(frozen=True)
class DoctorHook:
    """A named extra check that ``run_doctor`` runs after the core checks.

    Core defines the hook shape and never imports an extension (ADR-0006): the
    presentation layer builds hooks from installed extensions and passes them in.
    """

    name: str
    check: Callable[[DoctorContext], Iterable[Diagnostic]]


def run_doctor(
    home: Path,
    *,
    today: date | None = None,
    stale_after_days: int = 14,
    hooks: Sequence[DoctorHook] = (),
) -> DoctorReport:
    """Run read-only diagnostics for an hfk private instance.

    ``hooks`` run after every core check. A hook that raises, or returns
    something other than ``Diagnostic`` objects, becomes an
    ``extension-hook-failed`` error naming the hook; it never stops the core
    checks or the other hooks from reporting.
    """

    home = Path(home)
    today = date.today() if today is None else today  # noqa: DTZ011
    diagnostics: list[Diagnostic] = []

    household = _load_household(home, diagnostics)
    people = household.slugs if household is not None else None
    declarations = _load_declarations(home, people=people, diagnostics=diagnostics)
    plan: Plan | None = None
    plan_duplicates_checked = False
    if declarations is None or household is None:
        failed = "household.yaml" if household is None else "declarations.yaml"
        diagnostics.append(
            Diagnostic(
                "error",
                "config-error",
                "HFK Plan",
                f"the HFK Plan sheet was not checked because {failed} failed",
                f"fix {failed} first, then rerun doctor",
            )
        )
    else:
        plan = _load_plan(
            home, household=household, declarations=declarations, diagnostics=diagnostics
        )

    workbook_path: Path | None = None
    ledger: Ledger | None = None
    if household is not None:
        workbook_path, ledger = _read_source(home, household, diagnostics)

    if household is not None and ledger is not None:
        _check_accounts(household, declarations, ledger, diagnostics)
        _check_closed_accounts(household, ledger, diagnostics)
        if declarations is not None:
            _check_category_orphans(declarations, ledger, diagnostics)
            if plan is not None:
                _check_plan_category_buckets(plan, declarations, ledger, diagnostics)
                _check_plan_category_duplicates(plan, diagnostics)
                plan_duplicates_checked = True
            _check_sharing_rule_conflicts(household, declarations, ledger, diagnostics)
        _check_stale_data(ledger, workbook_path, today, stale_after_days, diagnostics)
        _check_history_start(household, ledger, diagnostics)

    if plan is not None and not plan_duplicates_checked:
        _check_plan_category_duplicates(plan, diagnostics)

    context = DoctorContext(home, household, declarations, ledger, today)
    for hook in hooks:
        diagnostics.extend(_run_hook(hook, context))

    readiness = (
        _sheets_readiness(workbook_path),
        _history_readiness(household, ledger, today),
        _mapping_readiness(declarations, ledger),
        _plan_readiness(plan),
    )
    return DoctorReport(tuple(diagnostics), readiness)


def _run_hook(hook: DoctorHook, context: DoctorContext) -> list[Diagnostic]:
    def failed(problem: str) -> Diagnostic:
        return Diagnostic(
            "error",
            "extension-hook-failed",
            f"extension {hook.name}",
            f"the {hook.name} doctor hook {problem}",
            f"report this to the {hook.name} extension's maintainer, or remove {hook.name} "
            "from extensions in household.yaml",
        )

    try:
        results = list(hook.check(context))
    except Exception as error:  # noqa: BLE001 - one bad hook must not hide the rest
        return [failed(f"raised {type(error).__name__}: {error}")]
    bad = [item for item in results if not isinstance(item, Diagnostic)]
    if bad:
        return [failed(f"returned {bad[0]!r}, not a Diagnostic")]
    return results


def _count(number: int, noun: str, plural: str | None = None) -> str:
    return f"{number} {noun if number == 1 else (plural or noun + 's')}"


def _sheets_readiness(workbook_path: Path | None) -> ReadinessCheck:
    name = "workbook sheets"
    if workbook_path is None:
        return ReadinessCheck(name, False, "no Tiller workbook was found in data/", WORKBOOK_FIX)
    sheet_names = set(workbook_sheet_names(workbook_path))
    missing = [sheet for sheet in REQUIRED_SHEETS if sheet not in sheet_names]
    required = ", ".join(REQUIRED_SHEETS)
    if missing:
        return ReadinessCheck(
            name,
            False,
            f"{workbook_path.name} is missing {', '.join(missing)}",
            f"download a fresh copy of your Tiller workbook into data/; hfk needs the "
            f"{required} sheets",
        )
    return ReadinessCheck(name, True, f"{workbook_path.name} has {required}")


def _history_readiness(
    household: Household | None, ledger: Ledger | None, today: date
) -> ReadinessCheck:
    name = "transaction history"
    if household is None or ledger is None:
        return ReadinessCheck(
            name,
            False,
            "transactions could not be read",
            "fix the household.yaml or workbook error above, then rerun doctor",
        )
    start = household.history_start
    months = {
        Month(transaction.date.year, transaction.date.month)
        for transaction in ledger.transactions
        if start is None or transaction.date >= start
    }
    current = Month(today.year, today.month)
    finished = sum(1 for month in months if month < current)
    since = "in the workbook" if start is None else f"on or after {start.isoformat()}"
    detail = (
        f"{_count(len(months), 'month')} of Transactions {since}, "
        f"{finished} of them finished"
    )
    if finished:
        return ReadinessCheck(name, True, detail)
    if not months:
        fix = (
            "download a workbook with transactions on or after history_start, "
            "or move history_start earlier in household.yaml"
        )
    else:
        fix = (
            f"reports cover finished months only; wait for {current} to end, "
            "or move history_start earlier in household.yaml"
        )
    return ReadinessCheck(name, False, detail, fix)


def _mapping_readiness(declarations: Declarations | None, ledger: Ledger | None) -> ReadinessCheck:
    name = "category mapping"
    if declarations is None:
        return ReadinessCheck(
            name,
            False,
            "declarations.yaml did not load",
            "fix the declarations.yaml error above, then rerun doctor",
        )
    if ledger is None:
        return ReadinessCheck(
            name,
            False,
            "categories could not be read from the workbook",
            "fix the workbook error above, then rerun doctor",
        )
    unmapped = len(_unmapped_spend_categories(declarations, ledger))
    if not unmapped:
        return ReadinessCheck(name, True, "every expense category has a bucket")
    return ReadinessCheck(
        name,
        False,
        f"{_count(unmapped, 'expense category', 'expense categories')} still "
        f"{'has' if unmapped == 1 else 'have'} no bucket",
        "give each one a bucket in declarations.yaml; the errors above name them",
    )


def _plan_readiness(plan: Plan | None) -> ReadinessCheck:
    name = "budget plan"
    if plan is None:
        return ReadinessCheck(
            name,
            False,
            "the plan did not load",
            "fix the plan error above, then run hfk plan check",
        )
    return ReadinessCheck(
        name, True, f"{_count(len(plan.lines), 'line')} load from the HFK Plan sheet"
    )


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
    household: Household,
    declarations: Declarations,
    diagnostics: list[Diagnostic],
) -> Plan | None:
    try:
        return load_instance_plan(home, household=household, declarations=declarations)
    except ConfigError as error:
        diagnostics.append(_config_diagnostic(error))
        return None


def _plan_where(_plan: Plan) -> str:
    return "HFK Plan"


def _plan_categories_ref(plan: Plan, index: int) -> str:
    return f"{plan.describe_line(index)} Categories"


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
    ledger_accounts = set(ledger.account_names())

    for name in sorted(ledger_accounts - declared_accounts):
        diagnostics.append(
            Diagnostic(
                "error",
                "account-undeclared",
                "household.yaml",
                f'ledger account "{name}" is not declared',
                f'add "{name}" under accounts with owner or shared, '
                "plus closed: YYYY-MM-DD if the account is closed",
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


@dataclass(frozen=True)
class _UnmappedCategory:
    name: str
    category: Category | None  # None: in Transactions but not in the Categories sheet


def _unmapped_spend_categories(
    declarations: Declarations, ledger: Ledger
) -> tuple[_UnmappedCategory, ...]:
    """Spend categories with no bucket and no override or split, in ledger order."""

    visible_categories = [category for category in ledger.categories if not category.hidden]
    groups = dict(declarations.groups)
    categories = dict(declarations.categories)
    non_spend_groups = set(declarations.non_spend_groups)
    unmapped: list[_UnmappedCategory] = []
    for name in _category_names_in_ledger_order(visible_categories, ledger):
        category = ledger.category(name)
        if _has_category_judgment(declarations, name):
            continue
        if category is None:
            unmapped.append(_UnmappedCategory(name, None))
            continue
        if _category_excluded_from_spend(category, non_spend_groups):
            continue
        if declarations.mapping_source == "tiller_group":
            if category.group not in groups:
                unmapped.append(_UnmappedCategory(name, category))
        elif name not in categories:
            unmapped.append(_UnmappedCategory(name, category))
    return tuple(unmapped)


def _check_category_orphans(
    declarations: Declarations, ledger: Ledger, diagnostics: list[Diagnostic]
) -> None:
    reported_groups: set[str] = set()
    for unmapped in _unmapped_spend_categories(declarations, ledger):
        name, category = unmapped.name, unmapped.category
        if category is None:
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
        elif declarations.mapping_source == "tiller_group":
            if category.group in reported_groups:
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
        else:
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
    ledger: Ledger,
    diagnostics: list[Diagnostic],
) -> None:
    """A transaction dated after an account's ``closed`` date is an error (ADR-0014)."""

    transactions_by_account: dict[str, list[date]] = {}
    for transaction in ledger.transactions:
        transactions_by_account.setdefault(transaction.account, []).append(transaction.date)

    for account in household.accounts:
        if account.closed is None:
            continue
        latest = max(transactions_by_account.get(account.name, ()), default=None)
        if latest is None or latest <= account.closed:
            continue
        diagnostics.append(
            Diagnostic(
                "error",
                "closed-account-active",
                "household.yaml",
                f'account "{account.name}" closed {account.closed.isoformat()} but has '
                f"activity through {latest.isoformat()}",
                f'in household.yaml set accounts."{account.name}".closed to '
                f"{latest.isoformat()} or later, or remove closed if the account is still open",
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
                    _plan_where(plan),
                    f'{_plan_categories_ref(plan, index)} desc "{line.desc}" who "{line.who}" '
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
                        _plan_where(plan),
                        f"{_plan_categories_ref(plan, left[0])} and "
                        f"{_plan_categories_ref(plan, right[0])} "
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
