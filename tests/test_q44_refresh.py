"""Q-44 / Q-73 / D-106: refresh the application details from the resume.

Design: docs/architecture/q44_refresh_from_resume.md (section 6, R1-R9). The
vitest side (R10) is web/tests/q44-refresh.test.js.

R1 dates   R2 owner entries are kept   R3 placeholders and from_resume entries
R4 never contact.location / languages / links / attested_skills
R5 skills (add-only, implied skills not added, template list replaced)
R6 stable ids, only accepted ids applied   R7 order, from_resume, no plan-only keys
R8 web GET/POST states   R9 cli (skip line, relative paths, refresh-resume)
D-106 "Expected"/"Anticipated" prefixes and "Present"/"To date" open ends.

No network, no model: pure dicts, a temp config, a monkeypatched master.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import yaml  # noqa: E402

from jobscraper import applicant  # noqa: E402
from test_web_applicant import _world  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
TEMPLATE = applicant.load_template()


# ---------------------------------------------------------------- helpers

def _profile(**over) -> dict:
    """A valid profile: the template, with the example entries replaced as asked."""
    p = copy.deepcopy(TEMPLATE)
    p.update(over)
    return p


def _exp(employer="Acme Logistics", title="Software Engineering Intern", start="2024-05", end="2024-08",
         location="", description="", **extra) -> dict:
    return {"employer": employer, "title": title, "start": start, "end": end,
            "location": location, "description": description, **extra}


def _edu(institution="Nanyang Example University", degree="B.Eng.", start="2021-08", end="2025-05",
         **extra) -> dict:
    return {"institution": institution, "degree": degree, "major": "", "minor": "", "start": start,
            "end": end, "grade_type": "", "grade": "", "grade_scale": "", **extra}


def _props(experience=(), education=(), skills=(), not_on_resume=()) -> dict:
    return {"resume_hash": "sha256:r1", "source_name": "resume.pdf", "created_at": "2026-11-07T00:00:00",
            "experience": list(experience), "education": list(education),
            "skills": list(skills), "not_on_resume": list(not_on_resume)}


def _prop_exp(employer="Acme Logistics", title="Software Engineering Intern", dates="May 2024 – Aug 2024",
              **kw) -> dict:
    s, e, _ok = applicant.parse_resume_dates(dates)
    return {"employer": employer, "title": title, "start": s, "end": e, "location": kw.pop("location", ""),
            "description": kw.pop("description", ""), "from_resume": True, "dates_text": dates, **kw}


def _prop_edu(institution="Nanyang Example University", degree="B.Eng.", dates="Aug 2021 – May 2025",
              **kw) -> dict:
    s, e, _ok = applicant.parse_resume_dates(dates)
    return {"institution": institution, "degree": degree, "major": "", "minor": "", "start": s, "end": e,
            "grade_type": "", "grade": "", "grade_scale": "", "from_resume": True, "dates_text": dates,
            "subtitle": kw.pop("subtitle", ""), **kw}


def _plan(profile, props):
    return applicant.refresh_plan(profile, props, TEMPLATE)


def _ops(plan, lst=None):
    return [(c["list"], c["op"]) for c in plan["changes"] if lst is None or c["list"] == lst]


def _by_op(plan, lst, op):
    return [c for c in plan["changes"] if c["list"] == lst and c["op"] == op]


# ---------------------------------------------------------------- R1 + D-106: dates

def test_r1_each_accepted_form():
    p = applicant.parse_resume_dates
    for text in ("May 2024 – Aug 2024", "May 2024 - Aug 2024", "May 2024 — Aug 2024", "May 2024 to Aug 2024",
                 "may 2024 – AUG 2024", "May 2024–Aug 2024", "May 2024  –  Aug 2024",
                 "05/2024 – 08/2024", "5/2024 – 8/2024", "2024-05 – 2024-08", "May. 2024 – Aug. 2024",
                 "May 2024 – August 2024", "  May 2024 – Aug 2024  "):
        assert p(text) == ("2024-05", "2024-08", True), text
    assert p("Sept 2024 – Dec 2024")[:2] == ("2024-09", "2024-12")
    assert p("September 2024") == ("2024-09", "2024-09", True), "one token is both start and end"
    assert p("2024-09") == ("2024-09", "2024-09", True)


def test_d106_present_and_its_synonyms_are_an_open_end():
    for word in ("Present", "present", "PRESENT", "Current", "Now", "To date", "to date", "Ongoing"):
        assert applicant.parse_resume_dates(f"May 2024 – {word}") == ("2024-05", None, True), word
    assert applicant.parse_resume_dates("May 2024 to date") == ("2024-05", None, True)
    assert applicant.parse_resume_dates("May 2024 - present") == ("2024-05", None, True)


def test_d106_expected_prefix_before_the_end_date():
    p = applicant.parse_resume_dates
    for prefix in ("Expected", "Expected:", "Exp.", "Anticipated", "expected", "EXPECTED", "exp"):
        assert p(f"Aug 2021 – {prefix} May 2025") == ("2021-08", "2025-05", True), prefix
    assert p("Aug 2021 to Expected May 2025") == ("2021-08", "2025-05", True)
    assert p("Aug 2021 – Expected: 05/2025") == ("2021-08", "2025-05", True)


def test_d106_a_single_expected_date_is_the_end_only():
    p = applicant.parse_resume_dates
    for text in ("Expected May 2025", "Expected: May 2025", "Exp. May 2025", "Anticipated May 2025"):
        assert p(text) == (None, "2025-05", True), text
    assert p("May 2025") == ("2025-05", "2025-05", True), "without the prefix it is both"


def test_r1_what_is_not_understood_gives_none_none_false():
    p = applicant.parse_resume_dates
    bad = ("2021 – 2025", "Aug 2021 – Expected 2025", "Aug 2021 – 2025", "2021", "Expected 2025",
           "Foo 2021 – Bar 2022", "13/2024 – 14/2024", "Aug 2025 – May 2021", "", "   ", None, "present",
           "Present – May 2024", "May 2024 – Soon", "Aug 2021 – Expected", "Expected")
    for text in bad:
        assert p(text) == (None, None, False), repr(text)


# ---------------------------------------------------------------- R5: skill labels (shared fixture)

def test_r5_skill_label_cases_shared_with_the_form():
    cases = json.loads((FIX / "skill_labels.json").read_text(encoding="utf-8"))["cases"]
    assert len(cases) >= 8
    for raw, want in cases:
        assert applicant.skill_label(raw) == want, raw
    assert applicant.skill_label(None) == ""


# ---------------------------------------------------------------- R2 / R3: who may change

def test_r2_an_owner_entry_is_never_changed_even_when_the_resume_matches_it():
    mine = _exp(description="my own words")                       # no from_resume key: the form's
    mine2 = _exp(employer="Beta Corp", title="Analyst", from_resume=False)
    profile = _profile(experience=[mine, mine2])
    props = _props(experience=[_prop_exp(description="from the resume"),
                               _prop_exp(employer="Beta Corp", title="Analyst", dates="Jan 2023 – Jun 2023")])
    plan = _plan(profile, props)
    assert [c["op"] for c in _by_op(plan, "experience", "kept")] == ["kept", "kept"]
    assert not _by_op(plan, "experience", "update") and not _by_op(plan, "experience", "add")
    assert not _by_op(plan, "experience", "remove")
    new, ignored = applicant.apply_refresh(profile, props, [c["id"] for c in plan["changes"]], TEMPLATE)
    assert new["experience"] == [mine, mine2]
    assert sorted(ignored) == sorted(c["id"] for c in plan["changes"]), "a kept row is info only"


def test_r2_an_owner_entry_that_the_resume_lacks_is_not_removed():
    mine = _exp(employer="Side Gig", title="Tutor")
    plan = _plan(_profile(experience=[mine]), _props(experience=[_prop_exp()]))
    assert not _by_op(plan, "experience", "remove")
    assert len(_by_op(plan, "experience", "add")) == 1


def test_r3_template_placeholders_are_removed_or_replaced():
    example_exp = copy.deepcopy(TEMPLATE["experience"][0])
    example_edu = copy.deepcopy(TEMPLATE["education"][0])
    profile = _profile(experience=[example_exp], education=[example_edu])
    plan = _plan(profile, _props(experience=[_prop_exp()], education=[_prop_edu()]))
    removes = [c for c in plan["changes"] if c["op"] == "remove"]
    assert {c["reason"] for c in removes} == {"template"}
    assert all(c["default"] for c in removes)
    new, ignored = applicant.apply_refresh(profile, _props(experience=[_prop_exp()], education=[_prop_edu()]),
                                           [c["id"] for c in plan["changes"] if c["default"]], TEMPLATE)
    assert ignored == []
    assert [e["employer"] for e in new["experience"]] == ["Acme Logistics"]
    assert [e["institution"] for e in new["education"]] == ["Nanyang Example University"]


def test_r3_a_placeholder_matched_by_the_resume_is_updated_in_place():
    example = copy.deepcopy(TEMPLATE["experience"][0])           # "Example Pte Ltd" / intern
    props = _props(experience=[_prop_exp(employer=example["employer"], title=example["title"],
                                         dates="Jun 2025 – Aug 2025", location="Singapore")])
    plan = _plan(_profile(experience=[example]), props)
    assert _ops(plan, "experience") == [("experience", "update")]
    after = plan["changes"][0]["after"]
    assert (after["start"], after["end"], after["from_resume"]) == ("2025-06", "2025-08", True)


def test_r3_a_from_resume_entry_is_updated_and_a_removed_one_is_offered_for_removal():
    old = _exp(description="old text", from_resume=True)
    gone = _exp(employer="Closed Co", title="Temp", from_resume=True)
    profile = _profile(experience=[old, gone])
    props = _props(experience=[_prop_exp(description="new text")])
    plan = _plan(profile, props)
    assert _ops(plan, "experience") == [("experience", "update"), ("experience", "remove")]
    assert _by_op(plan, "experience", "remove")[0]["reason"] == "not_on_resume"
    new, _ = applicant.apply_refresh(profile, props, [c["id"] for c in plan["changes"]], TEMPLATE)
    assert [(e["employer"], e["description"]) for e in new["experience"]] == [("Acme Logistics", "new text")]


def test_r3_unread_dates_keep_the_old_value_only_for_a_from_resume_entry():
    unread = _prop_exp(dates="2024 – 2025")                       # year only: not understood
    assert (unread["start"], unread["end"]) == (None, None)
    kept_old = _exp(start="2024-05", end="2024-08", from_resume=True)
    plan = _plan(_profile(experience=[kept_old]), _props(experience=[dict(unread, description="x")]))
    after = _by_op(plan, "experience", "update")[0]["after"]
    assert (after["start"], after["end"]) == ("2024-05", "2024-08")
    assert 'Dates not understood ("2024 – 2025")' in _by_op(plan, "experience", "update")[0]["note"]

    example = copy.deepcopy(TEMPLATE["experience"][0])           # a placeholder never lends its dates
    unread2 = _prop_exp(employer=example["employer"], title=example["title"], dates="2024 – 2025")
    plan2 = _plan(_profile(experience=[example]), _props(experience=[unread2]))
    after2 = _by_op(plan2, "experience", "update")[0]["after"]
    assert (after2["start"], after2["end"]) == (None, None)


def test_r3_an_open_end_stays_open_on_update():
    old = _exp(start="2024-05", end="2024-08", from_resume=True)
    plan = _plan(_profile(experience=[old]), _props(experience=[_prop_exp(dates="May 2024 – Present")]))
    assert _by_op(plan, "experience", "update")[0]["after"]["end"] is None


def test_r3_a_promotion_matches_on_the_employer_alone_when_unique():
    old = _exp(title="Intern", from_resume=True)
    plan = _plan(_profile(experience=[old]), _props(experience=[_prop_exp(title="Software Engineer")]))
    assert _ops(plan, "experience") == [("experience", "update")]


def test_r3_no_change_gives_no_row():
    e = _exp(from_resume=True, description="d")
    plan = _plan(_profile(experience=[e]), _props(experience=[_prop_exp(description="d")]))
    assert _by_op(plan, "experience", "update") == []


def test_r3_an_unreadable_education_add_is_not_ticked_and_says_why():
    plan = _plan(_profile(education=[]), _props(education=[_prop_edu(dates="2021 – 2025", subtitle="Honours, CAP 4.5")]))
    add = _by_op(plan, "education", "add")[0]
    assert add["default"] is False
    assert 'Dates not understood ("2021 – 2025")' in add["note"]
    assert "Resume says: Honours, CAP 4.5" in add["note"]
    assert add["after"]["major"] == "" and add["after"]["grade"] == ""


# ---------------------------------------------------------------- R4: what is never touched

def test_r4_languages_links_attested_skills_and_the_rest_are_byte_identical_after_apply():
    profile = _profile(experience=[copy.deepcopy(TEMPLATE["experience"][0])],
                       attested_skills=["Rust"], links={"linkedin": "x", "github": "", "portfolio": "", "other": []})
    before = copy.deepcopy(profile)
    props = _props(experience=[_prop_exp()], education=[_prop_edu()], skills=["Go"])
    plan = _plan(profile, props)
    new, _ = applicant.apply_refresh(profile, props, [c["id"] for c in plan["changes"]], TEMPLATE)
    for key in set(before) - {"experience", "education", "skills"}:
        assert new[key] == before[key], key
    assert profile == before, "apply_refresh works on a copy"


def test_r4_the_plan_never_mentions_languages_links_or_attested_skills():
    plan = _plan(_profile(), _props(experience=[_prop_exp()], skills=["Go"]))
    assert {c["list"] for c in plan["changes"]} <= {"experience", "education", "skills"}


# ---------------------------------------------------------------- R5: skills

def test_r5_skills_are_added_never_removed_and_case_insensitively():
    profile = _profile(skills=["Python", "Rust"])
    props = _props(skills=["python", "kubernetes", "machine learning", "RUST"])
    plan = _plan(profile, props)
    assert plan["skills"]["add"] == ["Kubernetes", "Machine Learning"]
    change = next(c for c in plan["changes"] if c["id"] == "skills:add")
    assert change["after"] == ["Python", "Rust", "Kubernetes", "Machine Learning"]
    new, _ = applicant.apply_refresh(profile, props, ["skills:add"], TEMPLATE)
    assert new["skills"] == ["Python", "Rust", "Kubernetes", "Machine Learning"]


def test_r5_nothing_to_add_means_no_skills_row():
    plan = _plan(_profile(skills=["Python", "Rust"]), _props(skills=["python"]))
    assert not [c for c in plan["changes"] if c["list"] == "skills"]
    assert plan["skills"]["add"] == []


def test_r5_the_template_skill_list_is_offered_for_replacing_not_adding_to():
    plan = _plan(_profile(skills=list(TEMPLATE["skills"])), _props(skills=["go", "kubernetes"]))
    ids = [c["id"] for c in plan["changes"] if c["list"] == "skills"]
    assert ids == ["skills:replace"]
    new, _ = applicant.apply_refresh(_profile(skills=list(TEMPLATE["skills"])), _props(skills=["go", "kubernetes"]),
                                     ["skills:replace"], TEMPLATE)
    assert new["skills"] == ["Go", "Kubernetes"]


def test_r5_implied_skills_are_listed_but_never_added():
    plan = _plan(_profile(skills=["Python"]), _props(skills=["go"], not_on_resume=["Docker"]))
    assert plan["skills"]["not_on_resume"] == ["Docker"]
    assert "Docker" not in plan["skills"]["add"]


# ---------------------------------------------------------------- R6 / R7: ids, apply, order

def test_r6_change_ids_are_stable_and_named_by_list_op_and_key():
    profile = _profile(experience=[_exp(employer="Gone Co", title="Temp", from_resume=True)])
    props = _props(experience=[_prop_exp()], skills=["go"])
    a, b = _plan(profile, props), _plan(copy.deepcopy(profile), copy.deepcopy(props))
    assert [c["id"] for c in a["changes"]] == [c["id"] for c in b["changes"]]
    ids = {c["id"] for c in a["changes"]}
    assert "experience:remove:gone co|temp" in ids
    assert "experience:add:acme logistics|software engineering intern" in ids
    assert "skills:add" in ids or "skills:replace" in ids


def test_r6_the_same_pair_twice_gets_a_hash_suffix():
    props = _props(experience=[_prop_exp(), _prop_exp(dates="Jan 2023 – Feb 2023")])
    ids = [c["id"] for c in _by_op(_plan(_profile(experience=[]), props), "experience", "add")]
    assert ids == ["experience:add:acme logistics|software engineering intern",
                   "experience:add:acme logistics|software engineering intern#2"]


def test_r6_only_accepted_ids_are_applied_and_unknown_ones_reported():
    profile = _profile(experience=[_exp(employer="Gone Co", title="Temp", from_resume=True)], skills=["Python"])
    props = _props(experience=[_prop_exp()], skills=["go"])
    plan = _plan(profile, props)
    remove_id = _by_op(plan, "experience", "remove")[0]["id"]
    new, ignored = applicant.apply_refresh(profile, props, [remove_id, "experience:add:nobody|nothing", "bogus"], TEMPLATE)
    assert [e["employer"] for e in new["experience"]] == []            # removed; the add was not accepted
    assert new["skills"] == ["Python"]                                  # not accepted: untouched
    assert ignored == ["experience:add:nobody|nothing", "bogus"]
    same, ignored2 = applicant.apply_refresh(profile, props, [], TEMPLATE)
    assert same == profile and ignored2 == []


def test_r7_an_added_entry_goes_before_the_first_following_entry_it_matches_in_resume_order():
    kept_a = _exp(employer="Aaa", title="One", from_resume=True)
    kept_c = _exp(employer="Ccc", title="Three", from_resume=True)
    profile = _profile(experience=[kept_a, kept_c])
    props = _props(experience=[_prop_exp(employer="Aaa", title="One"), _prop_exp(employer="Bbb", title="Two"),
                               _prop_exp(employer="Ccc", title="Three"), _prop_exp(employer="Ddd", title="Four")])
    plan = _plan(profile, props)
    new, _ = applicant.apply_refresh(profile, props, [c["id"] for c in plan["changes"]], TEMPLATE)
    assert [e["employer"] for e in new["experience"]] == ["Aaa", "Bbb", "Ccc", "Ddd"]


def test_r7_an_added_entry_is_from_resume_and_carries_no_plan_only_keys():
    profile = _profile(education=[])
    props = _props(education=[_prop_edu(subtitle="Honours")])
    plan = _plan(profile, props)
    new, _ = applicant.apply_refresh(profile, props, [c["id"] for c in plan["changes"]], TEMPLATE)
    entry = new["education"][0]
    assert entry["from_resume"] is True
    assert "dates_text" not in entry and "subtitle" not in entry
    for c in plan["changes"]:
        assert "dates_text" not in (c["after"] or {}) and "subtitle" not in (c["after"] or {})
        assert not [k for k in c if k.startswith("_")], "private apply data stays private"


# ---------------------------------------------------------------- proposals file + template

def test_proposals_file_round_trips_atomically_and_missing_is_none():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = applicant.proposals_path(Path(tmp) / "applicant.yaml")
        assert path.name == "applicant.refresh.json" and path.parent == Path(tmp)
        assert applicant.load_proposals(path) is None
        props = _props(skills=["Zürich"])
        applicant.save_proposals(path, props)
        assert applicant.load_proposals(path) == props
        assert not list(Path(tmp).glob("*.tmp"))
        path.write_text("{not json", encoding="utf-8")
        assert applicant.load_proposals(path) is None
        path.write_text("[1]", encoding="utf-8")
        assert applicant.load_proposals(path) is None


# ---------------------------------------------------------------- tailor_flow.profile_proposals

def _master_dict() -> dict:
    return json.loads((FIX / "tailor" / "case_a" / "master.json").read_text(encoding="utf-8"))


def _proposals_for(master: dict, derived_skills: list[str], *, text: str | None = None) -> dict:
    from jobscraper import tailor_flow
    from jobscraper.config import Config
    from jobscraper.tailor import master as master_mod
    m = master_mod.from_dict(master)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        prof = Path(tmp) / "profile.derived.yaml"
        prof.write_text(yaml.safe_dump({"skills": derived_skills}), encoding="utf-8")
        cfg = Config({"paths": {"profile": str(prof), "resume_dir": tmp}})
        real = tailor_flow.ensure_master
        tailor_flow.ensure_master = lambda c, b: (m, "sha256:abc", text or "")
        try:
            return tailor_flow.profile_proposals(cfg, backend=None)
        finally:
            tailor_flow.ensure_master = real


def test_r4_profile_proposals_copy_the_resume_and_invent_nothing():
    master = _master_dict()
    master["contact"]["location"] = "Contact City"            # must never become a job location
    exp = next(s for s in master["sections"] if s["kind"] == "experience")["entries"][0]
    exp["location"] = ""
    exp["bullets"][0]["text"] = "word " * 200                  # 1000 chars: cut at a space before 500
    out = _proposals_for(master, ["python"])
    assert out["resume_hash"] == "sha256:abc" and out["source_name"] == master["source_name"]
    job = out["experience"][0]
    assert job["employer"] == exp["organisation"] and job["title"] == exp["title"]
    assert job["location"] == "", "never the contact line"
    assert "Contact City" not in json.dumps(out)
    assert 400 < len(job["description"]) <= 500 and not job["description"].endswith(" ")
    assert job["description"].startswith("word word")
    assert job["from_resume"] is True and job["dates_text"] == exp["dates"]
    edu = out["education"][0]
    assert edu["institution"] == "Nanyang Example University"
    assert (edu["major"], edu["minor"], edu["grade"], edu["grade_type"], edu["grade_scale"]) == ("",) * 5


def test_r4_profile_proposals_use_an_entrys_own_location_and_dates():
    master = _master_dict()
    exp = next(s for s in master["sections"] if s["kind"] == "experience")["entries"][0]
    exp["location"] = "Singapore"
    exp["dates"] = "May 2024 – Present"
    job = _proposals_for(master, [])["experience"][0]
    assert job["location"] == "Singapore"
    assert (job["start"], job["end"]) == ("2024-05", None)


def test_r4_profile_proposals_leave_out_projects_and_incomplete_entries():
    master = _master_dict()
    master["sections"].append({"heading": "Projects", "kind": "projects", "items": [], "entries": [
        {"id": "p1", "title": "Side project", "organisation": "Hobby Org", "location": "", "dates": "2024",
         "subtitle": "", "bullets": [{"id": 1, "text": "Built a thing."}]}]})
    exp_section = next(s for s in master["sections"] if s["kind"] == "experience")
    exp_section["entries"].append({"id": "x9", "title": "No org here", "organisation": "", "location": "",
                                   "dates": "2020", "subtitle": "", "bullets": []})
    out = _proposals_for(master, [])
    blob = json.dumps(out)
    assert "Hobby Org" not in blob and "No org here" not in blob
    assert len(out["experience"]) == 1


def test_r5_profile_proposals_split_derived_skills_by_whether_the_resume_has_them():
    master = _master_dict()
    out = _proposals_for(master, ["python", "Docker", "machine learning", "python"])
    assert "Python" in out["skills"]
    assert "Docker" in out["not_on_resume"], "implied by the derive step, not written on the resume"
    assert out["skills"].count("Python") == 1, "deduplicated"
    assert not set(out["skills"]) & set(out["not_on_resume"])


# ---------------------------------------------------------------- R8: web

def _write_resume(cfg) -> str:
    Path(cfg.resume_dir, "resume.pdf").write_bytes(b"%PDF-1.4 fake resume for the hash")
    return applicant.original_resume_hash(cfg.resume_dir)


def _ready_world_profile() -> dict:
    return _profile(experience=[copy.deepcopy(TEMPLATE["experience"][0])],
                    education=[copy.deepcopy(TEMPLATE["education"][0])])


def _ready_props(rhash: str) -> dict:
    props = _props(experience=[_prop_exp()], education=[_prop_edu()], skills=["go", "kubernetes"],
                   not_on_resume=["Docker"])
    props["resume_hash"] = rhash
    return props


def test_r8_get_states_no_profile_none_stale_ready_unreadable():
    with _world() as (c, path, cfg):
        assert c.get("/api/applicant/refresh").json() == {"state": "no_profile"}
    with _world(prof=_ready_world_profile()) as (c, path, cfg):
        rhash = _write_resume(cfg)
        assert c.get("/api/applicant/refresh").json() == {"state": "none"}
        props = _ready_props("sha256:of-an-older-resume")
        applicant.save_proposals(applicant.proposals_path(path), props)
        assert c.get("/api/applicant/refresh").json() == {"state": "stale"}
        applicant.save_proposals(applicant.proposals_path(path), _ready_props(rhash))
        body = c.get("/api/applicant/refresh").json()
        assert body["state"] == "ready"
        assert body["source_name"] == "resume.pdf" and body["resume_hash"] == rhash and body["etag"]
        assert body["skills"] == {"add": ["Go", "Kubernetes"], "not_on_resume": ["Docker"]}
        ops = {(ch["list"], ch["op"]) for ch in body["changes"]}
        assert {("experience", "remove"), ("experience", "add"), ("education", "add"), ("skills", "replace")} <= ops
        assert all(set(ch) >= {"id", "list", "op", "index", "before", "after", "note", "default"} for ch in body["changes"])
        assert all("dates_text" not in (ch["after"] or {}) for ch in body["changes"])
        path.write_text("identity: [unclosed\n", encoding="utf-8")
        assert c.get("/api/applicant/refresh").json() == {"state": "unreadable"}


def test_r8_post_saves_the_ticked_changes_and_the_file_validates():
    with _world(prof=_ready_world_profile()) as (c, path, cfg):
        rhash = _write_resume(cfg)
        applicant.save_proposals(applicant.proposals_path(path), _ready_props(rhash))
        plan = c.get("/api/applicant/refresh").json()
        accept = [ch["id"] for ch in plan["changes"] if ch["default"]]
        assert accept
        r = c.post("/api/applicant/refresh", json={"etag": plan["etag"], "accept": accept})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["saved"] == len(accept) and body["ignored"] == []
        assert body["profile"]["skills"] == ["Go", "Kubernetes"]
        saved = applicant.load(path)
        assert applicant.validate(saved) == []
        assert [e["employer"] for e in saved["experience"]] == ["Acme Logistics"]
        assert all(e["from_resume"] is True for e in saved["experience"])
        assert "dates_text" not in path.read_text(encoding="utf-8")
        # The plan is computed fresh: what was saved is no longer offered.
        after = c.get("/api/applicant/refresh").json()
        assert not [ch for ch in after["changes"] if ch["op"] in ("remove", "update")]


def test_r8_post_with_a_stale_etag_is_409_changed_and_writes_nothing():
    with _world(prof=_ready_world_profile()) as (c, path, cfg):
        rhash = _write_resume(cfg)
        applicant.save_proposals(applicant.proposals_path(path), _ready_props(rhash))
        plan = c.get("/api/applicant/refresh").json()
        before = path.read_bytes()
        r = c.post("/api/applicant/refresh", json={"etag": "not-the-etag", "accept": [plan["changes"][0]["id"]]})
        assert r.status_code == 409 and r.json()["detail"] == "changed"
        assert path.read_bytes() == before


def test_r8_post_409_when_the_proposals_are_unusable():
    with _world(prof=_ready_world_profile()) as (c, path, cfg):
        rhash = _write_resume(cfg)
        etag = c.get("/api/applicant").json()["etag"]
        r = c.post("/api/applicant/refresh", json={"etag": etag, "accept": ["skills:add"]})
        assert (r.status_code, r.json()["detail"]) == (409, "none")
        applicant.save_proposals(applicant.proposals_path(path), _ready_props("sha256:older"))
        r = c.post("/api/applicant/refresh", json={"etag": etag, "accept": ["skills:add"]})
        assert (r.status_code, r.json()["detail"]) == (409, "stale")
        applicant.save_proposals(applicant.proposals_path(path), _ready_props(rhash))
        path.write_text("identity: [unclosed\n", encoding="utf-8")
        r = c.post("/api/applicant/refresh", json={"etag": etag, "accept": ["skills:add"]})
        assert (r.status_code, r.json()["detail"]) == (409, "unreadable")
    with _world() as (c, path, cfg):
        r = c.post("/api/applicant/refresh", json={"etag": "", "accept": []})
        assert (r.status_code, r.json()["detail"]) == (409, "no_profile")


def test_r8_unknown_ids_are_ignored_and_a_post_of_only_those_writes_nothing():
    with _world(prof=_ready_world_profile()) as (c, path, cfg):
        rhash = _write_resume(cfg)
        applicant.save_proposals(applicant.proposals_path(path), _ready_props(rhash))
        plan = c.get("/api/applicant/refresh").json()
        before = path.read_bytes()
        r = c.post("/api/applicant/refresh", json={"etag": plan["etag"], "accept": ["bogus", "experience:add:no|one"]})
        assert r.status_code == 200
        assert r.json()["saved"] == 0 and r.json()["ignored"] == ["bogus", "experience:add:no|one"]
        assert path.read_bytes() == before
        good = plan["changes"][0]["id"]
        r = c.post("/api/applicant/refresh", json={"etag": plan["etag"], "accept": [good, "bogus"]})
        assert r.json()["saved"] == 1 and r.json()["ignored"] == ["bogus"]


# ---------------------------------------------------------------- Q-73 / web: /api/profile fields

def test_q73_profile_view_reports_years_and_graduation_or_null():
    from jobscraper.config import Config
    from jobscraper.web.control import profile_view
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        prof = Path(tmp) / "profile.derived.yaml"
        cfg = Config({"paths": {"profile": str(prof), "db": str(Path(tmp) / "x.db")}})
        base = {"source_file": "resume.pdf", "profile_version": 1, "skills": [], "target_titles": []}
        cases = [({"years_experience": 3, "graduation": "2025-06"}, (3, "2025-06")),
                 ({"years_experience": 0, "graduation": 2025}, (0, "2025")),
                 ({"years_experience": True, "graduation": "  "}, (None, None)),
                 ({"years_experience": -1, "graduation": None}, (None, None)),
                 ({"years_experience": "3"}, (None, None)),
                 ({}, (None, None))]
        for extra, (years, grad) in cases:
            prof.write_text(yaml.safe_dump({**base, **extra}), encoding="utf-8")
            out = profile_view(cfg)
            assert (out["years_experience"], out["graduation"]) == (years, grad), extra
        prof.unlink()
        out = profile_view(cfg)
        assert out["present"] is False and out["years_experience"] is None and out["graduation"] is None


# ---------------------------------------------------------------- R9: cli

def _cfg_with_applicant(tmp: str, prof: dict | None):
    from jobscraper.config import Config
    data = Path(tmp) / "data"
    data.mkdir()
    path = data / "applicant.yaml"
    if prof is not None:
        path.write_text(yaml.safe_dump(prof, sort_keys=False), encoding="utf-8", newline="\n")
    return Config({"paths": {"applicant": str(path), "profile": str(data / "profile.derived.yaml"),
                             "resume_dir": str(data), "db": str(data / "x.db")}}), path


@contextlib.contextmanager
def _patched(cli, **attrs):
    from jobscraper import tailor_flow
    saved = {}
    targets = {"profile_proposals": tailor_flow, "build": cli.backends}
    try:
        for name, value in attrs.items():
            saved[name] = getattr(targets[name], name)
            setattr(targets[name], name, value)
        yield
    finally:
        for name, value in saved.items():
            setattr(targets[name], name, value)


def _run(fn, *a):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(*a)
    return rc, out.getvalue(), err.getvalue()


def test_r9_plan_applicant_with_the_model_down_prints_the_skip_line_and_writes_nothing():
    from jobscraper import backends, cli

    def down(cfg, backend):
        raise backends.BackendError("ollama is not running")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        cfg, path = _cfg_with_applicant(tmp, _ready_world_profile())
        with _patched(cli, profile_proposals=down, build=lambda budget: object()):
            _rc, out, _err = _run(cli._plan_applicant, cfg)
        assert out.strip() == "application details check skipped: the AI model isn't running"
        assert out.strip() == cli.SKIP_MODEL_DOWN
        assert not applicant.proposals_path(path).exists()


def test_r9_plan_applicant_never_raises_whatever_goes_wrong_and_names_only_the_error_type():
    from jobscraper import cli

    def broken(cfg, backend):
        raise RuntimeError("C:/Users/me/secret/resume.pdf could not be read")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        cfg, path = _cfg_with_applicant(tmp, _ready_world_profile())
        with _patched(cli, profile_proposals=broken, build=lambda budget: object()):
            _rc, out, _err = _run(cli._plan_applicant, cfg)
        assert out.strip() == "application details check skipped: RuntimeError"
        assert "secret" not in out and "Users" not in out


def test_r9_plan_applicant_writes_the_proposals_and_counts_the_changes():
    from jobscraper import cli
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        cfg, path = _cfg_with_applicant(tmp, _ready_world_profile())
        props = _ready_props("sha256:r1")
        with _patched(cli, profile_proposals=lambda c, b: props, build=lambda budget: object()):
            _rc, out, _err = _run(cli._plan_applicant, cfg)
        assert applicant.load_proposals(applicant.proposals_path(path)) == props
        n = sum(1 for c in _plan(_ready_world_profile(), props)["changes"] if c["op"] != "kept")
        assert out.strip() == f"application details check: {n} changes to review"


def test_r9_plan_applicant_without_a_profile_file_still_writes_the_proposals():
    from jobscraper import cli
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        cfg, path = _cfg_with_applicant(tmp, None)
        with _patched(cli, profile_proposals=lambda c, b: _ready_props("sha256:r1"), build=lambda budget: object()):
            _rc, out, _err = _run(cli._plan_applicant, cfg)
        assert out.strip() == "application details check: no application details yet"
        assert applicant.proposals_path(path).is_file()


def test_r9_rel_paths_are_project_relative_or_just_the_name():
    from jobscraper import cli
    from jobscraper.config import ROOT as PROJECT
    assert cli._rel(PROJECT / "data" / "profile.derived.yaml") == "data/profile.derived.yaml"
    outside = Path(tempfile.gettempdir()) / "somewhere" / "profile.derived.yaml"
    assert cli._rel(outside) == "profile.derived.yaml"
    for p in (PROJECT / "data" / "x.yaml", outside):
        assert ":" not in cli._rel(p) and "\\" not in cli._rel(p)


def test_r9_refresh_resume_prints_the_plan_and_saves_only_with_yes():
    from jobscraper import cli
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        cfg, path = _cfg_with_applicant(tmp, _ready_world_profile())
        props = _ready_props("sha256:r1")
        before = path.read_bytes()
        with _patched(cli, profile_proposals=lambda c, b: props, build=lambda budget: object()):
            rc, out, err = _run(cli._applicant_refresh, cfg, False)
            assert rc == 0 and err == ""
            assert "Remove: example from the template (experience)" in out
            assert "Add (experience): Acme Logistics · Software Engineering Intern · May 2024 – Aug 2024" in out or \
                "Add (experience): Acme Logistics · Software Engineering Intern · 2024-05 – 2024-08" in out
            assert "Replace the example skills with 2 skills from your resume: Go, Kubernetes" in out
            assert "Not on your resume, so not added: Docker" in out
            assert "Run again with --yes to save" in out
            assert path.read_bytes() == before, "the plan alone writes nothing"
            rc, out, err = _run(cli._applicant_refresh, cfg, True)
            assert rc == 0 and out.count("Saved") == 1
        saved = applicant.load(path)
        assert [e["employer"] for e in saved["experience"]] == ["Acme Logistics"]
        assert saved["skills"] == ["Go", "Kubernetes"]
        assert applicant.validate(saved) == []
        # Run again: the ticked changes are done, so nothing is left to save.
        with _patched(cli, profile_proposals=lambda c, b: props, build=lambda budget: object()):
            rc, out, _ = _run(cli._applicant_refresh, cfg, True)
        assert rc == 0 and "Saved" not in out


def test_r9_refresh_resume_fails_clearly_without_a_profile_or_a_model():
    from jobscraper import backends, cli

    def down(cfg, backend):
        raise backends.BackendError("down")

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        cfg, path = _cfg_with_applicant(tmp, None)
        rc, _out, err = _run(cli._applicant_refresh, cfg, False)
        assert rc == 1 and "no profile at applicant.yaml" in err
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        cfg, path = _cfg_with_applicant(tmp, _ready_world_profile())
        with _patched(cli, profile_proposals=down, build=lambda budget: object()):
            rc, _out, err = _run(cli._applicant_refresh, cfg, False)
        assert rc == 1 and cli.SKIP_MODEL_DOWN in err


def test_r9_the_profile_job_asks_for_the_applicant_check():
    from jobscraper.web.jobs import cli_command
    argv = cli_command(None)("profile", {})
    assert argv[-3:] == ["profile", "--refresh", "--plan-applicant"]
    from jobscraper.cli import build_parser
    ns = build_parser().parse_args(["profile", "--refresh", "--plan-applicant"])
    assert ns.plan_applicant is True
    ns = build_parser().parse_args(["applicant", "refresh-resume", "--yes"])
    assert ns.applicant_cmd == "refresh-resume" and ns.yes is True
