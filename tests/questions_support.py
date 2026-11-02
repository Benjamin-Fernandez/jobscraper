"""Shared helpers for the Q-30 oracles (WP-Q0): questions from applications and the work-rights
defaults (docs/architecture/questions_design.md, "QD"). Not a test file: the runner globs only
`test_*.py`. Test files do `sys.path.insert(0, str(Path(__file__).parent))` and then
`from questions_support import ...`.

`needs(...)` is tests/apply_support.needs: the decorated test is not defined (the runner never
sees it) until the named module / attribute exists, and one line at import says what waits.

Every call into a module that does not exist yet goes through ONE helper here or at the top of
the test file, marked ASSUMED, so an engineer who names something differently changes one line.
No network, no src changes, synthetic data only (the sample profile is an invented person).
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import FIX, ROOT, SAMPLE, missing, profile  # noqa: E402,F401

from jobscraper.apply.contracts import (  # noqa: E402
    Answer, AnswerStatus, AnswerTier, FieldType, FormField, Option, ResolveContext,
)
from jobscraper.backends import Backend, BackendError, Completion  # noqa: E402

D75_RULES = FIX / "questions_d75.yaml"
EXTRA_SAMPLE = FIX / "applicant_extra.sample.yaml"
REAL_RULES = ROOT / "config" / "questions.yaml"
NOW = "2026-11-02T10:00:00"          # store.TIME_FMT, UTC
LATER = "2026-11-02T11:00:00"

RESUME_TEXT = ("Alex Testcase\nExperience\nSoftware Engineering Intern, Example Logistics Pte Ltd\n"
               "Built REST APIs in Python and Postgres for shipment tracking.\n")


WAITING: list[tuple[str, str]] = []     # (test name, what is missing) for the Q-30 files only


def needs(*specs: str):
    """apply_support.needs, but recorded in this module's own list (so the other apply test files'
    "waiting" lines stay about their own oracles). The decorated test is not defined until every
    spec (`module` or `module:Attr.attr`) is importable."""
    gone = [m for m in (missing(s) for s in specs) if m]
    if os.environ.get("Q30_FORCE"):       # tester's smoke switch: define every oracle, see how it fails
        gone = []

    def deco(fn):
        if gone:
            WAITING.append((fn.__name__, gone[0]))
            return None
        return fn
    return deco


def waiting_mark() -> int:
    """Call at the top of a test file; pass the result to `report_waiting` at the bottom."""
    return len(WAITING)


def report_waiting(module: str, start: int) -> None:
    """One line at import: what this file's skipped tests wait for."""
    mine = WAITING[start:]
    if mine:
        what = sorted({w for _n, w in mine})
        print(f"[{module}] {len(mine)} oracle tests wait for modules not built yet: {', '.join(what)}")


# ------------------------------------------------------------------ profiles

def extra_block() -> dict:
    return copy.deepcopy(yaml.safe_load(EXTRA_SAMPLE.read_text(encoding="utf-8"))["extra"])


def profile_with_extra(only: Optional[Iterable[str]] = None, **overrides) -> dict:
    """The sample profile plus the sample `extra:` entries (all, or only the named keys).
    `overrides` replace whole `extra` entries (a dict) or delete them (None)."""
    p = profile()
    ex = extra_block()
    if only is not None:
        ex = {k: v for k, v in ex.items() if k in set(only)}
    for k, v in overrides.items():
        if v is None:
            ex.pop(k, None)
        else:
            ex[k] = v
    p["extra"] = ex
    return p


def with_work_rights(authorised: Any, sponsorship: Any, base: Optional[dict] = None) -> dict:
    """The sample profile with the two work-rights maps replaced (D-75). A map is a dict or None
    (None removes the key: 'absent map')."""
    p = base if base is not None else profile()
    for key, val in (("authorised_to_work", authorised), ("requires_sponsorship", sponsorship)):
        if val is None:
            p["singapore_status"].pop(key, None)
        else:
            p["singapore_status"][key] = val
    return p


# ------------------------------------------------------------------ fields and a scripted model

def field(key, label, type=FieldType.TEXT, options=(), required=True, canonical=None,
          description="", step="", section="", max_length=None) -> FormField:
    return FormField(key=key, label=label, type=type, required=required,
                     options=tuple(Option(o) for o in options), canonical=canonical,
                     description=description, step=step, section=section, max_length=max_length)


def yes_no(key, label, required=True) -> FormField:
    return field(key, label, FieldType.DROPDOWN, ("Yes", "No"), required)


def chosen(a: Answer) -> tuple:
    if a.option_labels:
        return tuple(a.option_labels)
    return tuple(a.value) if isinstance(a.value, list) else (a.value,)


def unknown(f: FormField, *, rule_id: str = "", note: str = "", sensitive: bool = False,
            status: AnswerStatus = AnswerStatus.UNKNOWN) -> Answer:
    """The Answer the resolver returns when no tier answers (`resolve._final`), hand-built so a
    capture oracle does not depend on how the resolver reached it."""
    return Answer(field_key=f.key, value=None, tier=AnswerTier.NONE, source="", confidence=0.0,
                  status=status, rule_id=rule_id, sensitive=sensitive, note=note)


class StubBackend(Backend):
    """Scripted model (same shape as tests/test_apply_contracts.StubBackend). Each reply is a
    dict (sent as JSON), a raw string, or an exception; `calls` records every request."""
    name = "stub"
    model_id = "stub-model"

    def __init__(self, replies: Sequence[Any] = ()):
        self.replies = list(replies)
        self.calls: list[dict] = []

    @property
    def available(self) -> bool:
        return True

    def complete(self, system, user, max_tokens=4096, *, format=None, temperature=None,
                 seed=None, top_k=None):
        self.calls.append({"system": system, "user": user, "format": format,
                           "temperature": temperature, "seed": seed, "max_tokens": max_tokens})
        if not self.replies:
            raise BackendError("stub: no reply scripted")
        r = self.replies.pop(0)
        if isinstance(r, BaseException):
            raise r
        return Completion(text=r if isinstance(r, str) else json.dumps(r))


def ctx_for(profile_: dict, *, employer: str = "Example Employer", aliases=(), ats: str = "greenhouse",
            job_country: Optional[str] = None, resume: str = RESUME_TEXT) -> ResolveContext:
    kw: dict[str, Any] = {}
    if job_country is not None:
        kw["job_country"] = job_country
    return ResolveContext(profile=profile_, employer_name=employer, employer_aliases=tuple(aliases),
                          resume_text=resume, resume_path="C:/fixture/Alex_Testcase_Resume.pdf",
                          ats=ats, **kw)


def resolve_all(fields: Sequence[FormField], profile_: dict, rules_path: Path, *, backend=None,
                memory=None, **ctx_kw) -> dict[str, Answer]:
    """Every field through the real resolver, over `rules_path`. Returns {field key: Answer}."""
    import importlib
    R = importlib.import_module("jobscraper.apply.resolve")
    ctx = ctx_for(profile_, **ctx_kw)
    out = R.resolve_all(list(fields), ctx, backend=backend or StubBackend(),
                        rules=R.load_rules(rules_path), memory=memory or (lambda *_a: None))
    assert set(out) == {f.key for f in fields}, "every field gets exactly one Answer"
    return out


def resolve_one(f: FormField, profile_: dict, rules_path: Path, **kw) -> Answer:
    return resolve_all([f], profile_, rules_path, **kw)[f.key]


# ------------------------------------------------------------------ a temp store and web app

def temp_dir() -> Path:
    return Path(tempfile.mkdtemp())


def make_store(tmp: Optional[Path] = None):
    from jobscraper.store import Store
    return Store((tmp or temp_dir()) / "t.db")


def make_job(st, cid: int, n: int, url: Optional[str] = None) -> str:
    from jobscraper.models import RawJob
    raw = RawJob(f"x{n}", f"Engineer {n}", url or f"https://x.example/jobs/{n}", "Singapore")
    jid = raw.job_id(cid, "greenhouse")
    st.upsert_job(jid, cid, raw, 1, True)
    st.commit()
    return jid


def question_row(*, key: str, label: str, kind: str, label_norm: Optional[str] = None,
                 options: Sequence[str] = (), sensitive: bool = False, reason: str = "no_rule",
                 target_path: str = "", title: str = "", named_by: str = "rule",
                 description: str = "") -> dict:
    """The dict `Store.upsert_question` takes. ASSUMED shape (QD 7.1 names the method, not the
    dict): the DDL columns of `questions` minus the id and the timestamps, with `options` as
    [{"label": verbatim, "norm": normalised}] and `sig` per QD 5.1. `options_json` is passed too
    (the same list, JSON text) so either reading works. ONE place to change."""
    import hashlib
    from jobscraper.apply.plan import norm_label
    ln = label_norm if label_norm is not None else norm_label(label)
    opts = [{"label": o, "norm": norm_label(o)} for o in options]
    sig = hashlib.sha256((kind + "\n" + ln + "\n"
                          + "\n".join(sorted(o["norm"] for o in opts))).encode("utf-8")).hexdigest()[:16]
    return {"sig": sig, "key": key, "target_path": target_path, "title": title or label[:60],
            "description": description, "kind": kind, "label": label, "label_norm": ln,
            "options": opts, "options_json": json.dumps(opts), "sensitive": bool(sensitive),
            "reason": reason, "named_by": named_by}


def seed_question(st, *, attempt_id: int, job_id: str, company_id: Optional[int] = None,
                  employer_norm: str = "", ats: str = "greenhouse", field_key: str = "q1",
                  required: bool = True, now: str = NOW, **row_kw) -> int:
    """upsert_question + add_sighting. Returns the question id. ASSUMED call shapes (QD 7.1):
    upsert_question(q: dict, now) -> int; add_sighting(question_id, attempt_id, job_id,
    company_id, employer_norm, ats, step, field_key, label, required, now)."""
    row = question_row(**row_kw)
    qid = st.upsert_question(row, now)
    st.add_sighting(qid, attempt_id, job_id, company_id, employer_norm, ats, "", field_key,
                    row["label"], required, now)
    st.commit()
    return qid


def failed_attempt(st, job_id: str, cid: int, *, reason: str = "unanswerable_required",
                   now: str = NOW) -> int:
    """A queued -> planning -> failed(reason) attempt (lane B's Store.create_attempt /
    set_attempt_state, apply_design 4). Does not exist until lane B merges."""
    from jobscraper.apply.contracts import AttemptState as S, ReasonCode
    aid = st.create_attempt(job_id, cid, "dry_run", now)
    st.set_attempt_state(aid, S.PLANNING)
    st.set_attempt_state(aid, S.FAILED, reason=ReasonCode(reason), detail="x")
    st.commit()
    return aid
