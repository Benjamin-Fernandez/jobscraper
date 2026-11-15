"""Helpers shared by the Q-121 Amendment A1 oracles (tests/test_always_a1*.py; not a test file).

Everything here drives the PUBLIC entry points of the always-answer filler through the scripted
fake `ask` of tests/test_always_fill.py (which fills a missing `class` from the code key, see
`FakeAsk`). A field's outcome is either an `Answer` or the `AlwaysStop` the page raised;
`attempt()` returns whichever happened so a pin can say which. No model, no network, no browser,
dummy sample profile only (employer "Example Employer"). Expected values come from the DESIGN
(llm_first_fill_design §17), never from the code under test.
"""
from __future__ import annotations

import copy
import dataclasses
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_always_fill import (  # noqa: E402,F401
    NO_CLASS, TODAY, YN, FakeAsk, _lr, _one, _pf, _profile, _run, _shown, pick_by, say)

_MEANING_VALUE = re.compile(r"answers «(.*?)» to the question")


def pick_faithful(confirm: str, right: str):
    """A scripted `pick` for a wording the reader cannot read (U9 / U6 / U8 / U8b): the confirmation call gets
    `confirm`; the MEANING call about a value V answers what a faithful reader would: "no" when V is the RIGHT
    value (it does not state the contradiction), "yes" for any other value. Compare `pick_by(confirm, meaning)`,
    which gives every meaning call the same reply."""
    def pick(q, w, o):
        w = str(w)
        if w.startswith("If the applicant answers"):
            m = _MEANING_VALUE.search(w)
            return "no" if m and m.group(1).strip().lower() == right.strip().lower() else "yes"
        return confirm
    return pick


def outcome(field, ask=None, profile=None, **kw):
    """The whole PageOutcome of a one-field page (`transport_failed`, `answers`, `model_calls`), for the pins
    where the page itself must end (F5) rather than the field."""
    return _run([field], ask if ask is not None else FakeAsk(), profile, **kw)


DOB = "2002-03-14"                       # the sample profile's date of birth
INVENTED_DOB = "1999-05-17"
SAMPLE_AGE = "24"                        # 2002-03-14 on TODAY = 2026-11-12


def attempt(field, ask=None, profile=None, **kw):
    """The Answer for one field, or the AlwaysStop the page raised."""
    from jobscraper.apply import always as AL
    try:
        return _one(field, ask if ask is not None else FakeAsk(), profile, **kw)[0]
    except AL.AlwaysStop as exc:
        return exc


def page(fields, ask=None, profile=None, **kw):
    """{key: Answer} for a page, or the AlwaysStop it raised."""
    from jobscraper.apply import always as AL
    try:
        return _run(list(fields), ask if ask is not None else FakeAsk(), profile, **kw).answers
    except AL.AlwaysStop as exc:
        return exc


def is_stop(res) -> bool:
    from jobscraper.apply import always as AL
    return isinstance(res, AL.AlwaysStop)


def stop_is(res, reason: str, target: str | None = None) -> bool:
    from jobscraper.apply.contracts import ReasonCode
    return is_stop(res) and res.reason is ReasonCode(reason) \
        and (target is None or res.target_path == target)


def shown(res) -> str:
    """What the answer writes: the option label(s), the text, "" for nothing; "<STOP ...>" for a stop."""
    if is_stop(res):
        return f"<STOP {res.reason.value}>"
    return _shown(res)


def what(res) -> str:
    if is_stop(res):
        return f"STOP {res.reason.value} {res.detail!r} {res.target_path!r}"
    return (f"{shown(res)!r} source={res.source} assumed={res.assumed} "
            f"evidence={str(res.evidence)[:70]!r} note={str(res.note)[:70]!r}")


def is_ticked(res) -> bool:
    return (not is_stop(res)) and res.value == "true"


def is_unticked(res) -> bool:
    """A checkbox that is not ticked (empty counts: the site's validation decides, §4.7)."""
    return (not is_stop(res)) and res.value in (None, "", "false", False) and not res.option_labels


def is_empty(res) -> bool:
    return (not is_stop(res)) and res.value in (None, "", [], "false") and not list(res.option_labels or ())


def labels(res) -> list[str]:
    return [] if is_stop(res) else list(res.option_labels or ())


def digits(text) -> str:
    return re.sub(r"\D+", "", str(text or ""))


def with_text(pf, *, context: str = "", description: str = ""):
    """A PageField with the preceding-field `context` and/or the site's help text set."""
    f = pf.field
    if description:
        f = dataclasses.replace(f, description=description)
    return dataclasses.replace(pf, field=f, context=context or pf.context)


def profile_with(**edits):
    """The sample profile with `section__key=value` edits (value `DELETE` removes the key)."""
    p = _profile()
    for path, value in edits.items():
        cur = p
        keys = path.split("__")
        for k in keys[:-1]:
            cur = cur[k]
        if value is DELETE:
            cur.pop(keys[-1], None)
        else:
            cur[keys[-1]] = value
    return p


class _Delete:
    def __repr__(self):
        return "DELETE"


DELETE = _Delete()

NO_DOB = {"identity__date_of_birth": None}
ALL_CONSENTS_FALSE = {"consents__privacy_consent": False, "consents__data_retention_consent": False,
                      "consents__talent_pool_opt_in": False, "consents__certify_true": False}
ALL_CONSENTS_TRUE = {"consents__privacy_consent": True, "consents__data_retention_consent": True,
                     "consents__talent_pool_opt_in": True, "consents__certify_true": True}


def consent_profile(kind: str) -> dict:
    """sample | false (all four consents false) | true (all true, opt-in too) | unset (the opt-in key absent)."""
    if kind == "sample":
        return _profile()
    if kind == "false":
        return profile_with(**ALL_CONSENTS_FALSE)
    if kind == "true":
        return profile_with(**ALL_CONSENTS_TRUE)
    if kind == "unset":
        return profile_with(consents__talent_pool_opt_in=DELETE)
    raise ValueError(kind)


def lie(value, klass=None, basis="assumption", ref="", assumed=True):
    """A model answer with no ground under it: basis `assumption`, optionally a chosen class."""
    return say(value, basis, ref, assumed, "guess", klass=klass)


def report(bad, limit: int = 8) -> str:
    """The first `limit` failing inputs of a table-driven pin, plus the total (full output stays readable)."""
    lines = [str(b) for b in bad[:limit]]
    if len(bad) > limit:
        lines.append(f"... and {len(bad) - limit} more ({len(bad)} failing inputs in all)")
    else:
        lines.append(f"({len(bad)} failing inputs)")
    return "\n".join(lines).encode("ascii", "backslashreplace").decode("ascii")   # a Windows console cannot print curly quotes


def code_key_of(pf, profile=None, **rctx_kw):
    """`always.code_key(pf, ctx)` -> (class value or "ordinary", which). A None result and
    (ORDINARY, "") both read "ordinary": the code finds no protected class."""
    import llm_fill_t2 as T
    from jobscraper import applicant
    from jobscraper.apply import always as AL, briefing as BR
    p = profile if profile is not None else _profile()
    r = T.rctx(p, **rctx_kw)
    ctx = AL.PageCtx(brief=BR.build(p, r, today=TODAY), rctx=r, profile=applicant.normalise(dict(p)),
                     ask=FakeAsk(), rules=T.rules(), today=TODAY, step_title="Application")
    klass, which = AL.code_key(pf, ctx)
    return ("ordinary" if klass is None else getattr(klass, "value", str(klass))), which or ""
