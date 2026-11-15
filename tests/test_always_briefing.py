"""Q-121 briefing oracles (D-208; llm_first_fill_design §3, §13 oracles 5, 12, 17; review M2, M7).

The candidate briefing is the model's whole view of the applicant under fill policy `always`.
These pins fail when a profile fact goes missing, when something K1/§3.1 excludes leaks in,
when the bytes stop being deterministic, when `refs` drifts from what is printed, when a
computed fact is wrong, when a standing rule says the opposite of the profile, when a secret
key gets through, or when an earlier owner answer is dropped (no count cap, M2).
Dummy data only: tests/fixtures/apply/applicant.sample.yaml + the T2 dummy resume and JD.
Verify: python tests/run_tests.py -k always_briefing
"""
from __future__ import annotations

import copy
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import needs  # noqa: E402

NEEDS = ("jobscraper.apply.briefing:build", "jobscraper.apply.briefing:build_with_report")
TODAY = "2026-11-12"
REF_LINE = re.compile(r"^((?:profile|extra|standing|default):\S+) \| ")


def _ctx(profile=None, **kw):
    import llm_fill_t2 as T
    return T.rctx(profile if profile is not None else _profile(), **kw)


def _profile() -> dict:
    from apply_flow_support import sample_profile
    p = sample_profile()
    p["contact"]["backup_email"] = "backup.marker.zz@example.com"
    p["documents"] = {"resume": "C:/dummy/MARKERDOC_resume.pdf", "transcript": "C:/dummy/MARKERDOC_t.pdf"}
    return p


def _build(profile=None, *, today=TODAY, **kw):
    from jobscraper.apply import briefing as BR
    p = profile if profile is not None else _profile()
    r = _ctx(p, **kw)
    return BR.build(p, r, today=today), r


def _lines(text: str) -> dict[str, str]:
    out = {}
    for ln in text.splitlines():
        m = REF_LINE.match(ln)
        if m:
            out[m.group(1)] = ln
    return out


def _extra(n: int, *, sensitive_marker: str = "") -> dict:
    ex = {}
    for i in range(n):
        ex[f"q_{i:03d}"] = {"title": f"Dummy question {i}", "kind": "text",
                            "description": "A dummy owner answer saved from the Questions page. " * 4,
                            "sensitive": False, "labels": [f"dummy label number {i} widget"],
                            "value": f"dummy answer {i}"}
    if sensitive_marker:
        ex["secretless_sensitive"] = {"title": "Sensitive dummy", "description": "", "kind": "text",
                                      "sensitive": True, "labels": ["what is your dummy sensitive fact"],
                                      "value": sensitive_marker}
    return ex


@needs(*NEEDS)
def test_every_profile_leaf_outside_the_exclusions_is_printed_on_its_ref_line():
    from jobscraper import applicant
    from jobscraper.apply import briefing as BR
    p = _profile()
    b, _ = _build(p)
    lines = _lines(b.text)
    norm = applicant.normalise(copy.deepcopy(p))
    missing = []
    checked = 0
    for path, value in applicant.walk_leaves(norm):
        bare = re.sub(r"\[\d+\]", "", path)
        if bare.split(".")[0] in ("documents", "version", "extra") or bare == "contact.backup_email":
            continue
        cands = [path]
        cur = path
        while re.search(r"(\.[^.\[]+|\[\d+\])$", cur):            # the ref may be an ancestor
            cur = re.sub(r"(\.[^.\[]+|\[\d+\])$", "", cur)
            cands.append(cur)
        line = next((lines["profile:" + c] for c in cands if "profile:" + c in lines), None)
        shown = BR.render_value(path, value)
        if line is None or shown not in line:
            missing.append((path, shown))
        checked += 1
    assert checked >= 60, checked
    assert not missing, missing[:10]


@needs(*NEEDS)
def test_the_exclusions_are_exactly_documents_version_and_the_backup_email():
    from jobscraper.apply import briefing as BR
    b, _ = _build()
    assert "MARKERDOC" not in b.text and "backup.marker.zz" not in b.text
    bad = [r for r in b.refs if r.startswith(("profile:documents", "profile:version",
                                              "profile:contact.backup_email"))]
    assert not bad, bad
    assert set(BR.EXCLUDED_TOP) == {"documents", "version", "extra"}     # extra = its own section
    assert set(BR.EXCLUDED_PATHS) == {"contact.backup_email"}
    # every other contact leaf IS there (the exclusion is one path, not the group)
    for ref in ("profile:contact.email", "profile:contact.phone_number", "profile:contact.postal_code",
                "profile:identity.date_of_birth", "profile:contact.address_line1"):
        assert ref in b.refs, ref


@needs(*NEEDS)
def test_a_sensitive_extra_answer_is_shown_with_its_value():
    p = _profile()
    p["extra"] = _extra(2, sensitive_marker="SENSITIVE-DUMMY-ANSWER-77")
    b, _ = _build(p)
    assert "SENSITIVE-DUMMY-ANSWER-77" in b.text
    assert "extra:secretless_sensitive" in b.refs


@needs(*NEEDS)
def test_deterministic_bytes_and_hash_and_one_changed_value_changes_the_hash():
    b1, _ = _build()
    b2, _ = _build()
    assert b1.text == b2.text and b1.hash == b2.hash and b1.refs == b2.refs
    assert b1.hash == hashlib.sha256(b1.text.encode("utf-8")).hexdigest()[:16]
    p = _profile()
    p["contact"]["city"] = "Jurong Dummytown"
    b3, _ = _build(p)
    assert b3.hash != b1.hash and "Jurong Dummytown" in b3.text


@needs(*NEEDS)
def test_today_moves_only_the_computed_facts_lines_the_design_names():
    # §3.3: today, experience (an open end runs to today), notice / earliest start, age,
    # graduation expected/completed, student and employment status. Nothing else.
    allowed = re.compile(r"^standing:(today|earliest_start|notice_period|experience(_years|_months)?|"
                         r"age_\d+_plus|graduation_(date|year)|current_student|current_employer|"
                         r"current_title|currently_employed) \| ")
    p = _profile()
    p["experience"].insert(0, {"employer": "Open Dummy Co", "title": "Engineer", "start": "2025-09",
                               "end": None, "location": "Singapore", "description": "Dummy work.",
                               "from_resume": False})
    a, _ = _build(p, today="2026-11-12")
    b, _ = _build(p, today="2027-03-01")
    la, lb = a.text.splitlines(), b.text.splitlines()
    assert len(la) == len(lb)
    diff = [(x, y) for x, y in zip(la, lb) if x != y]
    assert diff, "today changed nothing"
    assert all(allowed.match(x) and allowed.match(y) for x, y in diff), diff
    assert any(x.startswith("standing:today | ") for x, _ in diff)
    assert any(x.startswith("standing:experience_months | ") for x, _ in diff)  # open end runs to today


@needs(*NEEDS)
def test_refs_equal_the_refs_printed_in_the_text_plus_the_job_refs():
    from jobscraper.apply import briefing as BR
    p = _profile()
    p["extra"] = _extra(3)
    b, r = _build(p)
    printed = set(_lines(b.text))
    assert set(b.refs) == printed | set(BR.JOB_REFS)
    assert len(b.refs) == len(set(b.refs))
    job = BR.job_block(r, today=TODAY)
    assert set(BR.JOB_REFS) <= set(_lines(job))


@needs(*NEEDS)
def test_computed_facts_match_a_hand_checked_sample():
    b, _ = _build()
    L = _lines(b.text)
    # experience 2024-05..2024-08 (4 months) + 2025-01..2025-06 (6 months) = 10 months
    assert L["standing:experience_months"].endswith("| 10"), L["standing:experience_months"]
    assert L["standing:experience_years"].endswith("| 0")
    assert "0 years 10 months" in L["standing:experience"]
    assert L["standing:graduation_year"].endswith("| 2025") and "completed" in L["standing:graduation_year"]
    assert "| Sample Analytics (ended 2025-06" in L["standing:current_employer"]
    assert "| Data Intern" in L["standing:current_title"]
    assert L["standing:currently_employed"].endswith("| no")
    assert "| 2026-11-12" in L["standing:earliest_start"]          # 0 days' notice, 2026-01-05 passed
    assert L["standing:age_18_plus"].endswith("| yes")
    # an open-ended job from 2023-11 makes 36 months, current, by 2026-11-12
    p = _profile()
    p["experience"].insert(0, {"employer": "Current Dummy Pte Ltd", "title": "Engineer",
                               "start": "2023-11", "end": None, "location": "Singapore",
                               "description": "Dummy.", "from_resume": False})
    b2, _ = _build(p)
    L2 = _lines(b2.text)
    assert L2["standing:experience_years"].endswith("| 3"), L2["standing:experience_years"]
    assert "Current Dummy Pte Ltd (current" in L2["standing:current_employer"]
    assert L2["standing:currently_employed"].endswith("| yes")
    # no date of birth: no age line at all (never computed from nothing)
    p3 = _profile()
    p3["identity"]["date_of_birth"] = None
    b3, _ = _build(p3)
    assert "standing:age_18_plus" not in b3.refs


@needs(*NEEDS)
def test_standing_rules_follow_the_profile_in_both_polarities_and_list_each_work_rights_row():
    b, _ = _build()
    d1 = _lines(b.text)["default:no_declaration"]
    assert "is not a politically exposed person" in d1
    assert "has no criminal record" in d1 and "has never been bankrupt" in d1
    assert "HAS a criminal record" not in d1
    p = _profile()
    p["declarations"]["criminal_record"] = True
    p["declarations"]["pep"] = True
    b2, _ = _build(p)
    d1t = _lines(b2.text)["default:no_declaration"]
    assert "HAS a criminal record" in d1t and "has no criminal record" not in d1t
    assert "IS a politically exposed person" in d1t and "is not a politically exposed" not in d1t
    # D3 / §3.3 (rev M7): each country of the profile's maps, the default row, citizenship
    p4 = _profile()
    p4["singapore_status"]["authorised_to_work"] = {"SG": True, "US": False, "GB": True, "default": False}
    p4["singapore_status"]["requires_sponsorship"] = {"SG": False, "US": True}
    b4, _ = _build(p4)
    L4 = _lines(b4.text)
    for cc in ("SG", "US", "GB"):
        assert f"standing:work_rights.{cc}" in L4, cc
    assert "does not have the right to work (own row); needs visa sponsorship (own row)" in \
        L4["standing:work_rights.US"]
    assert "does not have the right to work" in L4["standing:work_rights.other"]   # the default row
    assert "every-other-country row" not in L4["standing:work_rights.SG"]
    assert "the profile lists no other citizenship or residence" in L4["standing:citizenship"]
    d3 = L4["default:work_rights"]
    assert all(name in d3 for name in ("Singapore", "United States", "United Kingdom"))
    assert "any other country" in d3


@needs(*NEEDS)
def test_a_key_named_like_a_secret_is_refused_without_its_value():
    from jobscraper.apply import briefing as BR
    for where in ("contact", "extra"):
        p = _profile()
        if where == "contact":
            p["contact"]["app_password"] = "hunter2-DUMMY-SECRET"
        else:
            p["extra"] = {"portal_password": {"title": "x", "kind": "text", "labels": ["x"],
                                              "value": "hunter2-DUMMY-SECRET"}}
        try:
            BR.build(p, _ctx(p), today=TODAY)
        except BR.BriefingRefused as exc:
            assert "hunter2" not in str(exc)
        else:
            raise AssertionError(f"a secret-named key in {where} was not refused")


@needs(*NEEDS)
def test_300_earlier_answers_none_dropped_and_the_report_says_what_moved():
    from jobscraper.apply import briefing as BR
    p = _profile()
    p["extra"] = _extra(300)
    r = _ctx(p)
    b, rep = BR.build_with_report(p, r, today=TODAY)
    assert rep.answers_listed == 300 and rep.answers_left_out == 0
    assert rep.full_tokens > rep.max_tokens and not rep.answers_in_prefix
    assert rep.reduced and "300 kept, 0 dropped" in rep.reduced[0]
    assert all(f"extra:q_{i:03d}" in b.refs for i in range(300))
    per_call = BR.answers_block(p, r, ["dummy label number 299 widget"])
    got = set(re.findall(r"extra:q_\d{3}", per_call))
    assert len(got) == 300                                      # every answer, per call
    assert per_call.index("extra:q_299") < per_call.index("extra:q_000")   # most relevant first
    for sec in ("== PROFILE ==", "== COMPUTED FACTS ==", "== STANDING RULES ==", "== RESUME =="):
        assert sec in b.text                                  # the rest stays whole
    assert "Nanyang Example University" in b.text and "Campus Robot League" in b.text
