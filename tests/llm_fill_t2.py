"""Shared builders for the T2 oracles (test_llm_fill_{facts,locks,guards,model}.py; not a test file).

`rctx()` = the synthetic sample profile in a ResolveContext with the sample resume and JD;
`pf()` builds a PageField without a browser; `secrets()` = the sample S values (AD §5.3).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from apply_flow_support import EMAIL, sample_profile  # noqa: E402
from llm_fill_support import FIX, sample_secrets  # noqa: E402

from jobscraper.apply.contracts import (  # noqa: E402
    FieldType, FormField, Option, PageField, ResolveContext, ValueOrigin,
)

TODAY = "2026-11-03"
NOW = datetime(2026, 11, 2, 16, 30, tzinfo=timezone.utc).timestamp()     # TR-5: SG date is the 3rd


def rctx(profile=None, **kw) -> ResolveContext:
    p = profile if profile is not None else sample_profile()
    base = dict(profile=p, employer_name="Example Employer", ats="workday", account_email=EMAIL,
                resume_text=(FIX / "resume_sample.txt").read_text(encoding="utf-8"),
                jd_text=(FIX / "jd_sample.txt").read_text(encoding="utf-8"))
    base.update(kw)
    return ResolveContext(**base)


def pf(key: str, label: str, type: FieldType = FieldType.TEXT, *, required: bool = False,
       options=(), shown="", origin: ValueOrigin = ValueOrigin.EMPTY, widget: str = "text",
       group: str = "", group_title: str = "") -> PageField:
    opts = tuple(Option(label=o, value=o) for o in options)
    return PageField(field=FormField(key=key, label=label, type=type, required=required, options=opts),
                     widget=widget, shown=shown, origin=origin, group=group, group_title=group_title)


def secrets() -> list[str]:
    return sample_secrets(sample_profile(), EMAIL)


def rules():
    from jobscraper.apply import resolve
    return resolve.load_rules(ROOT / "config" / "questions.yaml")
