"""The setup page that ``hfk open`` shows for a folder with no settings yet (M5-21).

ADR-0022: a household that does not program sets hfk up in the browser. The
page has two steps: copy the Tiller workbook download into ``data/``, then
answer the ``hfk init`` questions as a form. The form is not a second
interview: every answer goes through ``run_interview`` as if it had been typed
at the terminal, so the checks and the settings files are the same.

The questions depend on earlier answers (the accounts on the people, the
group buckets on the profile, the plan-sheet exceptions on the groups), so the
page is filled in rounds and works with scripts turned off. Each round shows
every question whose earlier answers are known; a question the household has
not seen yet is never answered for them. Only hfk's existing defaults are
filled in, and group buckets start empty (ADR-0011, ADR-0021).
"""

from __future__ import annotations

import html
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from hfk.config import ConfigError
from hfk.interview import (
    FOLLOW_GROUP,
    KEEP_PLAN,
    WORKBOOK_GLOBS,
    InterviewError,
    InterviewResult,
    Question,
    find_interview_workbooks,
    parse_people,
    people_question,
    run_interview,
)
from hfk.source import TillerFormatError

OTHER = "__other__"  # the account choice that reads the typed shares instead
_STAND_IN_DATE = "2000-01-01"


class _Stop(Exception):
    """The interview cannot go on until the household answers a question."""


@dataclass
class Asked:
    """One question as the page shows it: the field's value and any problem."""

    question: Question
    value: str
    answered: bool
    problem: str | None = None


@dataclass
class Collected:
    """One round: the questions so far, and the result once every answer works."""

    asked: list[Asked] = field(default_factory=list)
    result: InterviewResult | None = None
    error: str | None = None  # a problem no single question can fix

    def visible(self) -> list[Asked]:
        """The questions whose earlier answers are all known and working."""

        blocked = {entry.question.key for entry in self.asked if _open(entry)}
        groups = {entry.question.key for entry in self.asked if entry.question.key.startswith("group:")}
        shown = []
        for entry in self.asked:
            if not _depends_on(entry.question.key, groups) & blocked:
                shown.append(entry)
        return shown

    @property
    def complete(self) -> bool:
        return self.result is not None


def _open(entry: Asked) -> bool:
    return not entry.answered or entry.problem is not None


def _depends_on(key: str, groups: set[str]) -> set[str]:
    if key == "people":
        return set()
    if key.startswith("group:"):
        return {"people", "profile"}
    if key.startswith("override:"):
        return {"people", "profile", *groups}
    return {"people"}


def answers_from_form(form: Mapping[str, list[str]]) -> dict[str, str]:
    """The typed answer for each question the page showed, from the posted form.

    ``asked`` names each question on the page, so an empty or unticked field still
    counts as the household's answer rather than as a question not yet shown.
    """

    answers: dict[str, str] = {}
    for key in form.get("asked", []):
        value = (form.get(f"q:{key}") or [""])[0]
        if key.startswith("override:"):
            value = KEEP_PLAN if value == KEEP_PLAN else FOLLOW_GROUP
        elif key.startswith("account:"):
            # Typed shares count when that choice is picked, or when no choice is.
            other = (form.get(f"q:{key}:other") or [""])[0]
            if value == OTHER or (not value and other.strip()):
                value = other
        answers[key] = value
    return answers


def collect(workbook: Path, answers: Mapping[str, str]) -> Collected:
    """Run the ``hfk init`` interview on the form's answers, one round at a time.

    A question the form does not answer yet gets a stand-in answer only so the
    interview can reach the questions after it; a round with any stand-in, or any
    answer that did not work, has no result, so nothing is written from it.
    """

    collected = Collected()
    by_key: dict[str, Asked] = {}

    def ask(question: Question) -> str:
        entry = by_key.get(question.key)
        if entry is None:
            original = replace(question, problem=None)
            if question.key in answers:
                entry = Asked(original, answers[question.key], answered=True)
            else:
                entry = Asked(original, question.default or "", answered=False)
            by_key[question.key] = entry
            collected.asked.append(entry)
            return answers[question.key] if entry.answered else _stand_in(question)
        if entry.answered and entry.problem is None:
            entry.problem = question.problem
            return _stand_in(question)
        raise _Stop

    try:
        result = run_interview(workbook, answers=None, ask=ask)
    except _Stop:
        return collected
    except (InterviewError, ConfigError, TillerFormatError) as error:
        collected.error = str(error)
        return collected
    if all(not _open(entry) for entry in collected.asked):
        collected.result = result
    return collected


def _stand_in(question: Question) -> str:
    if question.key == "people":
        raise _Stop  # every other question depends on the people
    if question.default is not None:
        return question.default
    if question.choices:
        return question.choices[0].value
    if question.key == "history_start":
        return _STAND_IN_DATE
    raise _Stop


@dataclass(frozen=True)
class WorkbookState:
    """What ``data/`` holds: the workbook hfk reads, and files it cannot use."""

    chosen: Path | None
    others: tuple[str, ...]  # other Tiller workbooks, not read
    unrecognised: tuple[str, ...]  # spreadsheets whose names hfk does not find


def workbook_state(home: Path) -> WorkbookState:
    data = Path(home) / "data"
    if not data.is_dir():
        return WorkbookState(None, (), ())
    found = find_interview_workbooks(data)
    names = {path.name for path in found}
    unrecognised = tuple(
        sorted(
            path.name
            for path in data.iterdir()
            if path.is_file()
            and not path.name.startswith(("~$", "."))
            and path.suffix.lower() in (".xlsx", ".xlsm")
            and path.name not in names
        )
    )
    chosen = found[0] if found else None
    return WorkbookState(chosen, tuple(path.name for path in found[1:]), unrecognised)


_STYLE = """\
<style>
body { font-family: system-ui, sans-serif; max-width: 46rem; margin: 2rem auto; padding: 0 1rem;
  line-height: 1.45; }
section { border-top: 1px solid #bbb; margin-top: 1.5rem; padding-top: 0.5rem; }
fieldset { border: 1px solid #ccc; margin: 1rem 0; padding: 0.5rem 1rem 0.75rem; }
legend { font-weight: bold; padding: 0 0.25rem; }
fieldset label { display: block; margin: 0.25rem 0; }
p.problem, p.error { color: #a00; }
p.hint, p.note { color: #444; font-size: 0.95em; }
input[type=text] { width: 100%; max-width: 30rem; }
button { font-size: 1em; padding: 0.3rem 0.9rem; margin-top: 0.5rem; }
</style>
"""

# Pages work without scripts; this one only warns before a tab with unsent
# answers closes and sends a chosen workbook without a second click (ADR-0022).
_SCRIPT = """\
(function () {
  var dirty = false;
  var answers = document.getElementById("answers");
  if (answers) {
    answers.addEventListener("input", function () { dirty = true; });
    answers.addEventListener("change", function () { dirty = true; });
    answers.addEventListener("submit", function () { dirty = false; });
  }
  window.addEventListener("beforeunload", function (event) {
    if (dirty) { event.preventDefault(); event.returnValue = ""; }
  });
  var file = document.getElementById("workbook-file");
  if (file) {
    file.addEventListener("change", function () {
      if (file.files.length && !dirty) { file.form.submit(); }
    });
  }
})();
"""


def workbook_form(token: str, back: str, *, label: str) -> str:
    """The Choose file form that copies a workbook download into ``data/``."""

    return (
        f'<form method="post" action="/{html.escape(token)}/workbook" '
        'enctype="multipart/form-data" class="workbook">'
        f'<input type="hidden" name="back" value="{html.escape(back)}" />'
        '<label>Workbook download (.xlsx) '
        '<input type="file" id="workbook-file" name="workbook" '
        'accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" />'
        "</label> "
        f'<button type="submit">{html.escape(label)}</button>'
        "</form>"
    )


def render_setup_page(
    home: Path,
    *,
    token: str,
    nonce: str,
    collected: Collected | None,
    message: str | None = None,
) -> str:
    """The whole setup page: the workbook step, then the questions."""

    state = workbook_state(home)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8" />',
        '<meta name="viewport" content="width=device-width, initial-scale=1" />',
        "<title>Set up hfk</title>",
        _STYLE.rstrip("\n"),
        "</head>",
        "<body>",
        "<h1>Set up hfk</h1>",
        (
            "<p>Two steps: give hfk a copy of your Tiller workbook, then answer a few "
            "questions about it. hfk never changes your workbook; it reads the copy in your "
            "hfk folder.</p>"
        ),
    ]
    if message:
        parts.append(f'<p class="error">{html.escape(message)}</p>')
    parts.extend(_workbook_section(state, token))
    if state.chosen is not None:
        parts.extend(_questions_section(token, collected))
    parts.append(f'<script nonce="{html.escape(nonce)}">\n{_SCRIPT}</script>')
    parts.extend(["</body>", "</html>", ""])
    return "\n".join(parts)


def _workbook_section(state: WorkbookState, token: str) -> list[str]:
    parts = ["<section>", "<h2>1. Your Tiller workbook</h2>"]
    if state.chosen is None:
        parts.extend(
            [
                "<p>Download your workbook, then choose the downloaded file here.</p>",
                "<ul>",
                (
                    "<li>Google Sheets: open the workbook, then File &gt; Download &gt; "
                    "Microsoft Excel (.xlsx).</li>"
                ),
                "<li>Excel: use the workbook file as it is.</li>",
                "</ul>",
            ]
        )
        if state.unrecognised:
            patterns = " or ".join(WORKBOOK_GLOBS)
            parts.append(
                f'<p class="problem">The data folder has {html.escape(", ".join(state.unrecognised))}, '
                f"but hfk only reads a workbook whose name matches {html.escape(patterns)}. "
                "Rename the file so its name starts with Tiller, or choose it here under a "
                "name that does.</p>"
            )
        parts.append(workbook_form(token, "/setup", label="Copy the workbook"))
    else:
        parts.append(f"<p>hfk will read <strong>{html.escape(state.chosen.name)}</strong>.</p>")
        if state.others:
            parts.append(
                f'<p class="note">The data folder also has {html.escape(", ".join(state.others))}; '
                "hfk reads the newest workbook.</p>"
            )
        parts.append('<p class="hint">Chose the wrong file? Choose another download:</p>')
        parts.append(workbook_form(token, "/setup", label="Copy the workbook"))
    parts.append("</section>")
    return parts


def _questions_section(token: str, collected: Collected | None) -> list[str]:
    parts = ["<section>", "<h2>2. A few questions</h2>"]
    if collected is not None and collected.error:
        parts.append(f'<p class="error">{html.escape(collected.error)}</p>')
        parts.append(
            "<p>Fix this in the workbook, download it again, and choose the new download "
            "above.</p>"
        )
        parts.append("</section>")
        return parts
    entries = collected.visible() if collected is not None else []
    if not entries:
        entries = [Asked(people_question(), "", answered=False)]
    parts.append(
        f'<form method="post" action="/{html.escape(token)}/setup" id="answers">'
    )
    for entry in entries:
        parts.append(_field(entry, collected))
    parts.append('<button type="submit">Continue</button>')
    parts.append("</form>")
    parts.append(
        '<p class="hint">After each Continue, hfk checks the answers and shows the next '
        "questions. Nothing is saved until every question has a working answer; then hfk "
        "saves the settings and shows whether the reports are ready.</p>"
    )
    parts.append("</section>")
    return parts


def _field(entry: Asked, collected: Collected | None) -> str:
    question = entry.question
    key = question.key
    name = f"q:{key}"
    lines = [f'<fieldset><input type="hidden" name="asked" value="{html.escape(key)}" />']
    if key == "people":
        lines.append("<legend>Who is in the household?</legend>")
        lines.append(
            f'<label>First names, separated by commas <input type="text" name="{html.escape(name)}" '
            f'value="{html.escape(entry.value)}" placeholder="Alex, Sam" /></label>'
        )
        short = _short_names(entry)
        if short:
            lines.append(
                f'<p class="hint">Short names hfk uses in its files and in the HFK Plan sheet\'s '
                f"Who column: {html.escape(short)}.</p>"
            )
    elif key.startswith("account:"):
        lines.append(f"<legend>{html.escape(question.text)}</legend>")
        values = {choice.value for choice in question.choices}
        other = entry.value not in values and entry.value != ""
        for choice in question.choices:
            checked = ' checked="checked"' if choice.value == entry.value else ""
            lines.append(
                f'<label><input type="radio" name="{html.escape(name)}" '
                f'value="{html.escape(choice.value)}"{checked} /> {html.escape(choice.label)}</label>'
            )
        checked = ' checked="checked"' if other else ""
        lines.append(
            f'<label><input type="radio" name="{html.escape(name)}" value="{OTHER}"{checked} /> '
            "Shared another way, in percent: "
            f'<input type="text" name="{html.escape(name)}:other" '
            f'value="{html.escape(entry.value if other else "")}" '
            f'placeholder="{html.escape(_hint_example(question))}" /></label>'
        )
        if entry.question.default is not None and not entry.answered:
            lines.append('<p class="hint">Filled in because the account name has that '
                         "person's name in it.</p>")
    elif key.startswith("override:"):
        lines.append(f"<legend>{html.escape(question.text.rsplit(' Which ', 1)[0])}</legend>")
        keep = question.choices[0].label
        checked = ' checked="checked"' if entry.value in ("", KEEP_PLAN) else ""
        lines.append(
            f'<label><input type="checkbox" name="{html.escape(name)}" value="{KEEP_PLAN}"'
            f"{checked} /> {html.escape(keep)}</label>"
        )
        lines.append(
            f'<p class="hint">Untick to {html.escape(question.choices[1].label[0].lower() + question.choices[1].label[1:])}.</p>'
        )
    elif key == "history_start":
        lines.append("<legend>From which date should reports start?</legend>")
        lines.append(
            f'<label>Start date <input type="date" name="{html.escape(name)}" '
            f'value="{html.escape(entry.value)}" /></label>'
        )
        if question.default is not None:
            lines.append(
                f'<p class="hint">Filled in with the earliest transaction in the workbook, '
                f"{html.escape(question.default)}.</p>"
            )
    elif key.startswith("group:"):
        lines.append(f"<legend>{html.escape(question.text)}</legend>")
        lines.append(f'<select name="{html.escape(name)}">')
        lines.append('<option value="">Choose a bucket</option>')
        for choice in question.choices:
            selected = ' selected="selected"' if choice.value == entry.value else ""
            lines.append(
                f'<option value="{html.escape(choice.value)}"{selected}>'
                f"{html.escape(choice.label)}</option>"
            )
        lines.append("</select>")
    else:  # profile, and any future question with choices
        lines.append(f"<legend>{html.escape(question.text)}</legend>")
        for choice in question.choices:
            checked = ' checked="checked"' if choice.value == entry.value else ""
            lines.append(
                f'<label><input type="radio" name="{html.escape(name)}" '
                f'value="{html.escape(choice.value)}"{checked} /> {html.escape(choice.label)}</label>'
            )
        if key == "profile" and question.default is not None and not entry.answered:
            lines.append('<p class="hint">Filled in because its buckets match the HFK Plan '
                         "sheet's.</p>")
    if entry.problem:
        lines.append(f'<p class="problem">That answer did not work: {html.escape(entry.problem)}</p>')
    lines.append("</fieldset>")
    return "\n".join(lines)


def _short_names(entry: Asked) -> str | None:
    if not entry.answered or entry.problem:
        return None
    try:
        people = parse_people(entry.value)
    except InterviewError:
        return None
    return ", ".join(f"{name} ({slug})" for slug, name in people)


def _hint_example(question: Question) -> str:
    hint = question.hint or ""
    return hint.rsplit("like ", 1)[-1] if "like " in hint else ""


__all__ = [
    "OTHER",
    "Asked",
    "Collected",
    "WorkbookState",
    "answers_from_form",
    "collect",
    "render_setup_page",
    "workbook_form",
    "workbook_state",
]
