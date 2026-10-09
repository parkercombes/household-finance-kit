"""Instance diagnostics for ``hfk doctor``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from hfk.config import (
    ConfigError,
    Declarations,
    Household,
    load_declarations,
    load_household,
    load_plan,
)
from hfk.ledger import Ledger
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
        _load_plan(home, declarations=declarations, people=people, diagnostics=diagnostics)

    workbook_path: Path | None = None
    ledger: Ledger | None = None
    if household is not None:
        workbook_path, ledger = _read_source(home, household, diagnostics)

    if household is not None and ledger is not None:
        _check_accounts(household, declarations, ledger, diagnostics)
        _check_stale_data(ledger, workbook_path, today, stale_after_days, diagnostics)
        _check_history_start(household, ledger, diagnostics)

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
) -> None:
    try:
        load_plan(home, declarations=declarations, people=people)
    except ConfigError as error:
        diagnostics.append(_config_diagnostic(error))


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
