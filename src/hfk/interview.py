"""The ``hfk init`` interview: instance YAML proposed from a Tiller workbook (M5-06).

``run_interview`` reads the newest workbook in ``data/`` through the read-only
source adapter, proposes ``household.yaml`` accounts from the ``Balance
History`` sheet and ``declarations.yaml`` group-to-bucket mappings from the
``Categories`` sheet, asks only what the workbook cannot answer, and renders
``household.yaml``, ``declarations.yaml``, and a starter ``plan.yaml`` with a
comment per judgement call. The module never prompts and never touches a
terminal: the CLI passes an ``ask`` callback, tests pass an answers mapping,
and both share one validation code path. The workbook is only ever opened
through ``hfk.source.read_tiller``.
"""

from __future__ import annotations

import fnmatch
import importlib.resources
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from hfk.config._yaml import load_mapping
from hfk.config.declarations import available_profiles
from hfk.config.household import SLUG
from hfk.ledger import BalanceRow, Category, Ledger
from hfk.source import read_tiller

ANSWER_KEYS = ("people", "accounts", "profile", "groups", "history_start")
WORKBOOK_GLOB = "Tiller*.xls*"


class InterviewError(Exception):
    """Raised when the interview cannot produce a valid instance."""

    def __init__(self, problem: str, *, question: str | None = None, fix: str) -> None:
        self.problem = problem
        self.question = question
        self.fix = fix
        if question is None:
            super().__init__(f"{problem}: fix={fix}")
        else:
            super().__init__(f"{problem}: question={question}, fix={fix}")


@dataclass(frozen=True)
class Question:
    """One interview question: its answers key, plain text, and default."""

    key: str
    text: str
    default: str | None = None


@dataclass(frozen=True)
class AccountFacts:
    """What the Balance History sheet says about one account."""

    name: str
    account_type: str | None
    account_class: str | None
    status: str | None
    last_balance: date | None


@dataclass(frozen=True)
class GroupFacts:
    """One expense group and its Expense-typed categories in sheet order."""

    name: str
    categories: tuple[str, ...]


@dataclass(frozen=True)
class Proposal:
    """What the workbook proposes before any question is answered."""

    workbook: Path
    accounts: tuple[AccountFacts, ...]
    closed_accounts: tuple[AccountFacts, ...]
    expense_groups: tuple[GroupFacts, ...]
    non_spend_groups: tuple[str, ...]
    earliest_transaction: date | None


@dataclass(frozen=True)
class InterviewResult:
    """The resolved interview: proposal, rendered documents, and summary lines."""

    proposal: Proposal
    documents: dict[str, str]
    summary: tuple[str, ...]


# Tiller's Sheets feed writes "ACTIVE" in Balance History's Account Status column; the
# Excel template wrote "Open". Closure is declared, never inferred (ADR-0014), so only
# an explicit closed-style status files an account under closed_accounts; anything else,
# including a missing column, counts as open.
CLOSED_STATUSES = frozenset({"closed", "inactive"})


def _is_closed_status(status: str | None) -> bool:
    return status is not None and status.strip().lower() in CLOSED_STATUSES


def propose_from_ledger(ledger: Ledger, workbook: Path) -> Proposal:
    """Derive the interview proposal from a ledger, without reading any file."""

    facts = _account_facts(ledger)
    open_accounts: list[AccountFacts] = []
    closed_accounts: list[AccountFacts] = []
    for name in ledger.account_names():
        entry = facts[name]
        if _is_closed_status(entry.status):
            closed_accounts.append(entry)
        else:
            open_accounts.append(entry)
    expense_groups, non_spend_groups = _group_facts(ledger.categories)
    earliest = min((row.date for row in ledger.transactions), default=None)
    return Proposal(
        workbook=Path(workbook),
        accounts=tuple(open_accounts),
        closed_accounts=tuple(closed_accounts),
        expense_groups=expense_groups,
        non_spend_groups=non_spend_groups,
        earliest_transaction=earliest,
    )


def propose(workbook: Path) -> Proposal:
    """Read the workbook read-only and derive the interview proposal."""

    return propose_from_ledger(read_tiller(workbook), Path(workbook))


def load_answers(path: Path) -> dict[str, object]:
    """Load a YAML answers file, rejecting top-level keys the interview never asks."""

    data = load_mapping(Path(path))
    for key in data:
        if key not in ANSWER_KEYS:
            raise InterviewError(
                f"unknown answers key {key!r}",
                question=str(key),
                fix=f"answers files may only use: {', '.join(ANSWER_KEYS)}",
            )
    return data


def run_interview(
    workbook: Path, *, answers: Mapping[str, object] | None, ask: Callable[[Question], str] | None
) -> InterviewResult:
    """Resolve every interview question and render the three instance files."""

    if answers is None and ask is None:
        raise InterviewError(
            "the interview needs an answers mapping or an ask callback",
            fix="pass answers for non-interactive runs, or ask for the terminal prompt",
        )
    proposal = propose(workbook)
    if not proposal.accounts:
        raise InterviewError(
            "the workbook has no open accounts in Balance History",
            fix="restore the Balance History sheet or reopen the accounts in Tiller, then rerun",
        )
    people = _resolve_people(answers, ask)
    ownership = _resolve_accounts(proposal, people, answers, ask)
    profile = _resolve_profile(answers, ask)
    buckets = _profile_bucket_names(profile)
    groups = _resolve_groups(proposal, profile, buckets, answers, ask)
    history_start, answered = _resolve_history_start(proposal, answers, ask)
    documents = {
        "household.yaml": _render_household(proposal, people, ownership, history_start, answered),
        "declarations.yaml": _render_declarations(proposal, profile, buckets, groups),
        "plan.yaml": _render_plan(proposal, people, groups, history_start),
    }
    accounts_line = (
        f"accounts: {len(proposal.accounts)} open from Balance History, "
        f"{len(proposal.closed_accounts)} closed"
    )
    groups_line = (
        f"groups: {len(proposal.expense_groups)} expense groups mapped, "
        f"{len(proposal.non_spend_groups)} non-spend"
    )
    history_line = (
        f"history_start: {history_start.isoformat()} "
        f"({'answered' if answered else 'earliest transaction'})"
    )
    summary = (
        f"workbook: {proposal.workbook.name}",
        accounts_line,
        groups_line,
        history_line,
    )
    return InterviewResult(proposal=proposal, documents=documents, summary=summary)


def _account_facts(ledger: Ledger) -> dict[str, AccountFacts]:
    rows: dict[str, list[tuple[int, BalanceRow]]] = {}
    for index, row in enumerate(ledger.balances):
        rows.setdefault(row.account, []).append((index, row))
    facts: dict[str, AccountFacts] = {}
    for name in ledger.account_names():
        ordered = sorted(rows.get(name, ()), key=lambda item: (item[1].date, item[0]))
        account_type: str | None = None
        account_class: str | None = None
        status: str | None = None
        for _index, row in ordered:
            if row.account_type is not None:
                account_type = row.account_type
            if row.account_class is not None:
                account_class = row.account_class
            if row.account_status is not None:
                status = row.account_status
        facts[name] = AccountFacts(
            name=name,
            account_type=account_type,
            account_class=account_class,
            status=status,
            last_balance=ordered[-1][1].date if ordered else None,
        )
    return facts


def _group_facts(
    categories: tuple[Category, ...],
) -> tuple[tuple[GroupFacts, ...], tuple[str, ...]]:
    order: list[str] = []
    seen: set[str] = set()
    expense: dict[str, list[str]] = {}
    for category in categories:
        if category.group not in seen:
            seen.add(category.group)
            order.append(category.group)
        if category.type == "Expense":
            expense.setdefault(category.group, []).append(category.name)
    expense_groups = tuple(
        GroupFacts(name=group, categories=tuple(expense[group]))
        for group in order
        if group in expense
    )
    non_spend_groups = tuple(group for group in order if group not in expense)
    return expense_groups, non_spend_groups


def _people_question() -> Question:
    return Question(
        key="people",
        text="Who is in the household, as slug=Name pairs separated by commas "
        "(like alex=Alex, sam=Sam)?",
    )


def _account_question(facts: AccountFacts, people: tuple[tuple[str, str], ...]) -> Question:
    account_type = facts.account_type if facts.account_type is not None else "unknown"
    account_class = facts.account_class if facts.account_class is not None else "unknown"
    return Question(
        key=f"account:{facts.name}",
        text=f'Who owns "{facts.name}" (Type {account_type}, Class {account_class} in '
        "Balance History): one person's slug, or slug=weight pairs separated by commas "
        "(like alex=0.5, sam=0.5) for a shared account?",
        default=_account_default(facts.name, people),
    )


def _account_default(name: str, people: tuple[tuple[str, str], ...]) -> str | None:
    lowered = name.lower()
    matches = [slug for slug, person_name in people if person_name.lower() in lowered]
    if len(matches) == 1:
        return matches[0]
    return None


def _profile_question() -> Question:
    names = ", ".join(available_profiles())
    return Question(key="profile", text=f"Which bucket profile should the budget use: {names}?")


def _group_question(facts: GroupFacts, buckets: tuple[str, ...]) -> Question:
    categories = ", ".join(facts.categories)
    names = ", ".join(buckets)
    return Question(
        key=f"group:{facts.name}",
        text=f'Which bucket covers the "{facts.name}" group (categories {categories}): {names}?',
    )


def _history_start_question(earliest: date | None) -> Question:
    if earliest is None:
        return Question(key="history_start", text="From which date should reports start (YYYY-MM-DD)?")
    return Question(
        key="history_start",
        text="From which date should reports start (YYYY-MM-DD), leaving it empty to use "
        f"the earliest transaction in the workbook ({earliest.isoformat()})?",
        default=earliest.isoformat(),
    )


def _file_answer(question: Question, answers: Mapping[str, object], *, fix: str) -> object:
    if question.key not in answers:
        raise InterviewError(f"missing answer for {question.text}", question=question.key, fix=fix)
    return answers[question.key]


def _prompt_answer(question: Question, ask: Callable[[Question], str]) -> str:
    text = ask(question)
    value = "" if text is None else str(text).strip()
    if value:
        return value
    if question.default is not None:
        return question.default
    raise InterviewError(
        "missing answer",
        question=question.key,
        fix="type an answer; an empty answer only takes the shown default",
    )


def _resolve_people(
    answers: Mapping[str, object] | None, ask: Callable[[Question], str] | None
) -> tuple[tuple[str, str], ...]:
    question = _people_question()
    if answers is not None:
        raw = _file_answer(question, answers, fix="add people to the answers file")
    else:
        raw = _prompt_answer(question, ask)
    return _parse_people(raw)


def _parse_people(raw: object) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[object, object]] = []
    if isinstance(raw, str):
        for part in raw.split(","):
            slug, separator, name = part.partition("=")
            if not separator or not slug.strip() or not name.strip():
                raise InterviewError(
                    f"invalid people answer {raw!r}",
                    question="people",
                    fix="write slug=Name pairs separated by commas, like alex=Alex, sam=Sam",
                )
            pairs.append((slug.strip(), name.strip()))
    elif isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict) or set(entry) != {"slug", "name"}:
                raise InterviewError(
                    f"invalid person entry {entry!r}",
                    question="people",
                    fix="write each person as {slug: alex, name: Alex}",
                )
            pairs.append((entry["slug"], entry["name"]))
    else:
        raise InterviewError(
            f"invalid people answer {raw!r}",
            question="people",
            fix="write people as a list of {slug, name} entries or as slug=Name pairs",
        )
    if not pairs:
        raise InterviewError(
            "people must list at least one person",
            question="people",
            fix="add at least one person",
        )
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for slug, name in pairs:
        _validate_slug(slug, question="people")
        if not isinstance(name, str) or not name.strip():
            raise InterviewError(
                f"person {slug!r} needs a non-empty name",
                question="people",
                fix="write the person's name, like Alex",
            )
        if slug in seen:
            raise InterviewError(
                f"duplicate person slug {slug!r}",
                question="people",
                fix="give each person a distinct slug",
            )
        seen.add(slug)
        result.append((slug, name.strip()))
    return tuple(result)


def _validate_slug(value: object, *, question: str) -> str:
    if not isinstance(value, str) or not SLUG.match(value):
        raise InterviewError(
            f"invalid person slug {value!r}",
            question=question,
            fix="use lowercase letters, digits, and underscores, starting with a letter",
        )
    return value


def _resolve_accounts(
    proposal: Proposal,
    people: tuple[tuple[str, str], ...],
    answers: Mapping[str, object] | None,
    ask: Callable[[Question], str] | None,
) -> dict[str, tuple[str, object]]:
    single = len(people) == 1
    open_names = [facts.name for facts in proposal.accounts]
    open_set = set(open_names)
    known = {slug for slug, _name in people}
    entries: dict[str, object] = {}
    if answers is not None:
        raw = answers.get("accounts")
        if raw is None:
            if single:
                entries = {name: {"owner": people[0][0]} for name in open_names}
        elif not isinstance(raw, dict):
            raise InterviewError(
                f"invalid accounts answer {raw!r}",
                question="accounts",
                fix="write accounts as a mapping of account name to "
                "{owner: <slug>} or {shared: {<slug>: <weight>, ...}}",
            )
        else:
            entries = dict(raw)
    elif single:
        entries = {name: {"owner": people[0][0]} for name in open_names}
    else:
        for facts in proposal.accounts:
            entries[facts.name] = _prompt_answer(_account_question(facts, people), ask)

    for name in entries:
        if name not in open_set:
            raise InterviewError(
                f"unknown account {name!r}",
                question=f"account:{name}",
                fix=f"choose one of: {', '.join(open_names)}",
            )
    ownership: dict[str, tuple[str, object]] = {}
    for facts in proposal.accounts:
        name = facts.name
        if name not in entries:
            raise InterviewError(
                f"missing answer for {_account_question(facts, people).text}",
                question=f"account:{name}",
                fix=f"add {name} under accounts in the answers file",
            )
        raw = entries[name]
        if isinstance(raw, str) and answers is None:
            raw = _parse_account_text(raw, name)
        ownership[name] = _validate_account_entry(name, raw, known)
    return ownership


def _parse_account_text(text: str, name: str) -> dict[str, object]:
    if "=" not in text:
        return {"owner": text}
    shares: dict[str, str] = {}
    for part in text.split(","):
        slug, separator, weight = part.partition("=")
        if not separator or not slug.strip() or not weight.strip():
            raise InterviewError(
                f"invalid answer {text!r} for account {name!r}",
                question=f"account:{name}",
                fix="write one slug, or slug=weight pairs separated by commas",
            )
        shares[slug.strip()] = weight.strip()
    return {"shared": shares}


def _validate_account_entry(
    name: str, entry: object, known: set[str]
) -> tuple[str, object]:
    if not isinstance(entry, dict):
        raise InterviewError(
            f"account {name!r} must be a mapping",
            question=f"account:{name}",
            fix="write {owner: <slug>} or {shared: {<slug>: <weight>, ...}}",
        )
    has_owner = "owner" in entry
    has_shared = "shared" in entry
    if has_owner == has_shared or not set(entry) <= {"owner", "shared"}:
        raise InterviewError(
            f"account {name!r} must have exactly one of owner or shared",
            question=f"account:{name}",
            fix="write {owner: <slug>} for one person or {shared: {<slug>: <weight>, ...}}",
        )
    if has_owner:
        owner = entry["owner"]
        if not isinstance(owner, str) or owner not in known:
            raise InterviewError(
                f"unknown person slug {owner!r}",
                question=f"account:{name}",
                fix=f"use one of: {', '.join(sorted(known))}",
            )
        return ("owner", owner)
    shares = entry["shared"]
    if not isinstance(shares, dict) or not shares:
        raise InterviewError(
            f"shared weights for {name!r} must list at least one person",
            question=f"account:{name}",
            fix="write shared: {alex: 0.5, sam: 0.5} with weights that sum to 1",
        )
    weights: list[tuple[str, Decimal]] = []
    for slug, value in shares.items():
        if not isinstance(slug, str) or slug not in known:
            raise InterviewError(
                f"unknown person slug {slug!r}",
                question=f"account:{name}",
                fix=f"use one of: {', '.join(sorted(known))}",
            )
        try:
            weight = Decimal(str(value))
        except (InvalidOperation, ValueError):
            weight = Decimal("NaN")
        if not weight.is_finite() or weight <= 0 or weight > 1:
            raise InterviewError(
                f"invalid share weight {value!r} for account {name!r}",
                question=f"account:{name}",
                fix="use a number greater than 0 and at most 1",
            )
        weights.append((slug, weight))
    total = sum((weight for _slug, weight in weights), Decimal(0))
    if total != 1:
        raise InterviewError(
            f"share weights for account {name!r} sum to {total}, not 1",
            question=f"account:{name}",
            fix="make the weights sum to exactly 1",
        )
    return ("shared", tuple(weights))


def _resolve_profile(
    answers: Mapping[str, object] | None, ask: Callable[[Question], str] | None
) -> str:
    question = _profile_question()
    if answers is not None:
        raw = _file_answer(question, answers, fix="add profile to the answers file")
    else:
        raw = _prompt_answer(question, ask)
    if not isinstance(raw, str) or not raw.strip():
        raise InterviewError(
            f"invalid profile answer {raw!r}",
            question="profile",
            fix="write the profile name, like four-bucket",
        )
    name = raw.strip()
    available = available_profiles()
    if name not in available:
        raise InterviewError(
            f"unknown profile {name!r}",
            question="profile",
            fix=f"choose one of: {', '.join(available)}",
        )
    return name


def _profile_bucket_names(profile: str) -> tuple[str, ...]:
    """Return the packaged profile's bucket names, read from the profile file."""

    root = Path(str(importlib.resources.files("hfk.profiles")))
    data = load_mapping(root / f"{profile}.yaml")
    buckets = data.get("buckets")
    if not isinstance(buckets, list) or not buckets:
        raise InterviewError(
            f"profile {profile!r} declares no buckets",
            question="profile",
            fix=f"fix the packaged profile file, or choose one of: {', '.join(available_profiles())}",
        )
    names: list[str] = []
    for entry in buckets:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise InterviewError(
                f"profile {profile!r} has an invalid bucket entry {entry!r}",
                question="profile",
                fix="fix the packaged profile file",
            )
        names.append(entry["name"])
    return tuple(names)


def _resolve_groups(
    proposal: Proposal,
    profile: str,
    buckets: tuple[str, ...],
    answers: Mapping[str, object] | None,
    ask: Callable[[Question], str] | None,
) -> dict[str, str]:
    if not proposal.expense_groups:
        raise InterviewError(
            "the Categories sheet has no expense categories",
            question="groups",
            fix="add expense categories in Tiller, then rerun hfk init",
        )
    expense_names = {facts.name for facts in proposal.expense_groups}
    raw_groups: dict[str, object] = {}
    if answers is not None:
        raw = answers.get("groups")
        if raw is None:
            first = proposal.expense_groups[0]
            raise InterviewError(
                f"missing answer for {_group_question(first, buckets).text}",
                question=f"group:{first.name}",
                fix=f"add {first.name} under groups in the answers file",
            )
        if not isinstance(raw, dict):
            raise InterviewError(
                f"invalid groups answer {raw!r}",
                question="groups",
                fix="write groups as a mapping of group name to bucket",
            )
        for name in raw:
            if name not in expense_names:
                raise InterviewError(
                    f"unknown group {name!r}",
                    question=f"group:{name}",
                    fix=f"choose one of: {', '.join(facts.name for facts in proposal.expense_groups)}",
                )
        raw_groups = dict(raw)
    else:
        for facts in proposal.expense_groups:
            raw_groups[facts.name] = _prompt_answer(_group_question(facts, buckets), ask)

    result: dict[str, str] = {}
    for facts in proposal.expense_groups:
        if facts.name not in raw_groups:
            raise InterviewError(
                f"missing answer for {_group_question(facts, buckets).text}",
                question=f"group:{facts.name}",
                fix=f"add {facts.name} under groups in the answers file",
            )
        bucket = raw_groups[facts.name]
        if not isinstance(bucket, str) or not bucket.strip():
            raise InterviewError(
                f"the bucket for {facts.name!r} must be a bucket name",
                question=f"group:{facts.name}",
                fix=f"use one of the {profile} buckets: {', '.join(buckets)}",
            )
        bucket = bucket.strip()
        if bucket not in buckets:
            raise InterviewError(
                f"bucket {bucket!r} is not one of the {profile} buckets",
                question=f"group:{facts.name}",
                fix=f"use one of: {', '.join(buckets)}",
            )
        result[facts.name] = bucket
    return result


def _resolve_history_start(
    proposal: Proposal,
    answers: Mapping[str, object] | None,
    ask: Callable[[Question], str] | None,
) -> tuple[date, bool]:
    question = _history_start_question(proposal.earliest_transaction)
    raw: object = None
    if answers is not None:
        raw = answers.get("history_start")
    else:
        raw = _prompt_answer(question, ask)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if question.default is None:
            raise InterviewError(
                f"missing answer for {question.text}",
                question="history_start",
                fix="add history_start to the answers file",
            )
        return (date.fromisoformat(question.default), False)
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return (raw, True)
    if isinstance(raw, str):
        try:
            return (date.fromisoformat(raw.strip()), True)
        except ValueError:
            pass
    raise InterviewError(
        f"history_start is not an ISO date: {raw!r}",
        question="history_start",
        fix="write it as YYYY-MM-DD",
    )


def _quote(value: str) -> str:
    return json.dumps(value)


def _fact(value: str | None) -> str:
    return value if value is not None else "unknown"


def _tiller_glob(workbook: Path) -> str:
    if fnmatch.fnmatchcase(workbook.name.lower(), WORKBOOK_GLOB.lower()):
        return WORKBOOK_GLOB
    return workbook.name


def _header(workbook: Path) -> list[str]:
    return [
        f"# This file was written by `hfk init` from the Tiller workbook {workbook.name}.",
        "# Edit it by hand; comments explain each judgement call.",
    ]


def _account_entry(facts: AccountFacts, ownership: tuple[str, object]) -> str:
    parts: list[str] = []
    if ownership[0] == "owner":
        parts.append(f"owner: {_quote(ownership[1])}")
    else:
        weights = ", ".join(f"{_quote(slug)}: {weight}" for slug, weight in ownership[1])
        parts.append(f"shared: {{{weights}}}")
    if facts.account_type is not None:
        parts.append(f"kind: {_quote(facts.account_type.lower())}")
    joined = ", ".join(parts)
    return f'  {_quote(facts.name)}: {{{joined}}}'


def _render_household(
    proposal: Proposal,
    people: tuple[tuple[str, str], ...],
    ownership: dict[str, tuple[str, object]],
    history_start: date,
    history_answered: bool,
) -> str:
    lines = _header(proposal.workbook)
    lines.append("schema_version: 1")
    lines.append("# people: who is in the household, answered in the interview.")
    lines.append("people:")
    for slug, name in people:
        lines.append(f"  - {{slug: {_quote(slug)}, name: {_quote(name)}}}")
    lines.append("# files.tiller_glob: the pattern that finds the workbook in data/.")
    lines.append("files:")
    lines.append(f"  tiller_glob: {_quote(_tiller_glob(proposal.workbook))}")
    if history_answered:
        lines.append("# history_start: answered in the interview.")
    else:
        lines.append(
            "# history_start: defaulted to the earliest transaction in the workbook "
            f"({proposal.earliest_transaction.isoformat()})."
        )
    lines.append(f"history_start: {history_start.isoformat()}")
    lines.append("# accounts: one entry per account that is Open in Balance History.")
    lines.append("accounts:")
    for facts in proposal.accounts:
        lines.append(
            f"  # {facts.name}: Type {_fact(facts.account_type)}, "
            f"Class {_fact(facts.account_class)}, status {_fact(facts.status)} "
            "in Balance History."
        )
        lines.append(_account_entry(facts, ownership[facts.name]))
    lines.append("# extensions: settle_up and retirement can be listed here later.")
    lines.append("extensions: []")
    return "\n".join(lines) + "\n"


def _render_declarations(
    proposal: Proposal,
    profile: str,
    buckets: tuple[str, ...],
    groups: dict[str, str],
) -> str:
    lines = _header(proposal.workbook)
    lines.append("schema_version: 1")
    lines.append(f"# profile: {profile} (buckets: {', '.join(buckets)}).")
    lines.append(f"profile: {_quote(profile)}")
    lines.append("# mapping_source: mappings follow the Group column of the Categories sheet.")
    lines.append(f"mapping_source: {_quote('tiller_group')}")
    lines.append("# groups: one bucket per expense group from the Categories sheet, "
                 "answered in the interview.")
    lines.append("groups:")
    for facts in proposal.expense_groups:
        categories = ", ".join(facts.categories)
        lines.append(f"  # {facts.name}: categories {categories} in the Categories sheet.")
        lines.append(f"  {_quote(facts.name)}: {_quote(groups[facts.name])}")
    lines.append(
        "# non_spend_groups: these groups hold only Income or Transfer categories "
        "in the Categories sheet."
    )
    non_spend = ", ".join(_quote(name) for name in proposal.non_spend_groups)
    lines.append(f"non_spend_groups: [{non_spend}]")
    lines.append("# overrides: per-category bucket changes, each with a reason.")
    lines.append("overrides: {}")
    lines.append("# splits: categories split across buckets by weights, each with a reason.")
    lines.append("splits: {}")
    lines.append("# sharing: per-transaction ownership overrides, each with a reason.")
    lines.append("sharing: []")
    lines.append(
        "# closed_accounts: accounts that are not Open in Balance History; ADR-0014 (M5-16) "
        "will move closure onto the household.yaml account entry."
    )
    if proposal.closed_accounts:
        lines.append("closed_accounts:")
        for facts in proposal.closed_accounts:
            closed = facts.last_balance
            note = f"{facts.status} in Balance History"
            lines.append(
                f"  # {facts.name}: last Balance History observation {closed.isoformat()}."
            )
            entry = f"closed: {closed.isoformat()}, note: {_quote(note)}"
            lines.append(f'  {_quote(facts.name)}: {{{entry}}}')
    else:
        lines.append("closed_accounts: {}")
    return "\n".join(lines) + "\n"


def _render_plan(
    proposal: Proposal,
    people: tuple[tuple[str, str], ...],
    groups: dict[str, str],
    history_start: date,
) -> str:
    who = people[0][0]
    effective = f"{history_start.year:04d}-{history_start.month:02d}"
    lines = _header(proposal.workbook)
    lines.append("schema_version: 1")
    lines.append("plan:")
    lines.append(
        f"  # effective_from: the month the plan starts, from history_start "
        f"{history_start.isoformat()}."
    )
    lines.append(f"  effective_from: {effective}")
    lines.append(
        "  # lines: one starter line per expense group from the Categories sheet, "
        "placeholders with monthly: 0.00 targets."
    )
    lines.append(
        "  # Set each target yourself; you may split lines per person, add paced: true, "
        "and model annual renewals with annual_bill."
    )
    lines.append("  # hfk plan check validates this file.")
    lines.append("  lines:")
    for facts in proposal.expense_groups:
        categories = ", ".join(facts.categories)
        quoted = ", ".join(_quote(name) for name in facts.categories)
        lines.append(f"    # {facts.name} starter: placeholder target for {categories}.")
        rendered = (
            f"desc: {_quote(f'{facts.name} starter')}, who: {_quote(who)}, "
            f"bucket: {_quote(groups[facts.name])}, monthly: 0.00, "
            f"categories: [{quoted}]"
        )
        lines.append(f"    - {{{rendered}}}")
    return "\n".join(lines) + "\n"
