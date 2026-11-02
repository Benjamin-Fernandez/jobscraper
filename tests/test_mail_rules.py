"""WP-T2 oracles: the rules file, the gates and the phrase classifier (mail_status_design.md
6.1-6.4, E1; build plan WP-T2, WP-S1). Verify: `python tests/run_tests.py -k mail_rules`.

Skip-clean: every oracle needs `jobscraper.mailstatus.rules` (S1); the golden match and change
rows also need `match` (S2) and `transition` (S3). The real-file half needs
config/mail_rules.yaml (R1) and says so while it is absent. Once rules.py exists,
`test_mail_rules_oracles_are_live` fails if any oracle here still waits (a misspelt name is
a failure, not a skip).

ASSUMED call shapes (build plan WP-S1; the helpers in tests/mail_support.py):
  rules.load_rules(path) -> Rules              raises rules.RulesError(entry_id, message)
  rules.platform_of(h, rules) -> str           "" when the sender is no platform
  rules.header_gate(h, rules, *, own, window_start, threads, employer_regs) -> Reason | None
  rules.content_gate(h, body, rules, *, in_matched_thread) -> Reason | None
  rules.classify(h, body, rules) -> Verdict    rules.quote_around(text, start, end) -> str
  rules.needs_model(verdict) -> bool
"""
from __future__ import annotations

import copy
import re
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_support import (  # noqa: E402
    MATCH, REAL_RULES, RULES, RULES_MIN, TRANSITION, WAITING, assert_live, build_policy, decide,
    design_contracts, golden, golden_apps, golden_body, golden_cases, golden_employer_regs,
    golden_header, golden_own, golden_threads, load, needs, norm_quote, note_waiting,
    schema_errors, tenants_fn, unit_header,
)

_W0 = len(WAITING)
WD = "Example Corp <examplecorp@myworkday.com>"
GH = "Northwind Traders Hiring <no-reply@us.greenhouse-mail.io>"
WINDOW = "2026-08-01T00:00:00"


def _c():
    from jobscraper.mailstatus import contracts
    return contracts


def _r():
    from jobscraper.mailstatus import rules
    return rules


def _phrase_categories(path: Path) -> dict[str, str]:
    """phrase id -> category, read from the YAML itself (to check rule ids)."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {p["id"]: cat for cat, spec in doc["categories"].items() for p in spec.get("phrases", [])}


def _gates(h, body, rules_obj, *, own=None, threads=None):
    """(gate, Reason) of the first gate that skips, or None (MS 6.2 order)."""
    R = _r()
    threads = golden_threads() if threads is None else threads
    hr = R.header_gate(h, rules_obj, own=golden_own() if own is None else own,
                       window_start=golden()["context"]["window_start"], threads=threads,
                       employer_regs=golden_employer_regs())
    if hr is not None:
        return "header", hr
    cr = R.content_gate(h, body, rules_obj, in_matched_thread=h.gm_thrid in threads)
    return ("content", cr) if cr is not None else None


# ------------------------------------------------------------------ the golden set

def _check_golden_gates_and_classifier(path: Path) -> None:
    R, c = _r(), _c()
    rules_obj = load(path)
    ids = _phrase_categories(path)
    wrong = []
    for case in golden_cases():
        h, body, exp = golden_header(case), golden_body(case), case["expect"]
        got = _gates(h, body, rules_obj)
        want = (exp["skip"]["gate"], c.Reason(exp["skip"]["reason"])) if exp["skip"] else None
        if got != want:
            wrong.append(f"{case['file']}: gate {got} != {want}")
            continue
        if want:
            continue
        v = R.classify(h, body, rules_obj)
        if v.category != c.Category(exp["category"]) or v.status_words != exp["status_words"]:
            wrong.append(f"{case['file']}: {v.category.value}/{v.status_words} != "
                         f"{exp['category']}/{exp['status_words']} ({v.rule_id})")
            continue
        if v.tier != c.Tier.RULE:
            wrong.append(f"{case['file']}: tier {v.tier}")
        if R.needs_model(v) != bool(exp.get("needs_model")):
            wrong.append(f"{case['file']}: needs_model {R.needs_model(v)}")
        if exp.get("conflict"):
            parts = v.rule_id.removeprefix("conflict:").split("+")
            cats = {ids.get(p, p) for p in parts}
            if not v.rule_id.startswith("conflict:") or cats != set(exp["conflict"]):
                wrong.append(f"{case['file']}: conflict rule id {v.rule_id!r}")
        elif v.category != c.Category.UNKNOWN:
            want_cat = exp.get("rule_category", exp["category"])
            if ids.get(v.rule_id) != want_cat:
                wrong.append(f"{case['file']}: rule id {v.rule_id!r} is not a {want_cat} phrase")
            if not v.quote or len(v.quote) > c.QUOTE_MAX:
                wrong.append(f"{case['file']}: quote length {len(v.quote)}")
            elif norm_quote(v.quote) not in norm_quote(h.subject + "\n" + body.text):
                wrong.append(f"{case['file']}: quote not in the message")
    assert not wrong, f"{len(wrong)} golden cases wrong against {path.name}:\n  " + "\n  ".join(wrong)


@needs(RULES)
def test_mail_rules_golden_gates_and_categories_on_rules_min():
    _check_golden_gates_and_classifier(RULES_MIN)


@needs(RULES)
def test_mail_rules_golden_gates_and_categories_on_the_real_file():
    if not REAL_RULES.exists():
        print("  note: config/mail_rules.yaml not there yet (WP-R1); real-file half not run")
        return
    _check_golden_gates_and_classifier(REAL_RULES)


def _match_and_change(path: Path, *, check_change: bool) -> None:
    R, c = _r(), _c()
    from jobscraper.mailstatus import match as M
    rules_obj = load(path)
    apps = golden_apps(tenants_fn(rules_obj))
    by_id = {a.job_id: a for a in apps}
    pol = build_policy() if check_change else None
    wrong = []
    for case in golden_cases():
        exp = case["expect"]
        if exp["skip"]:
            continue
        h, body = golden_header(case), golden_body(case)
        m = M.match(h, body, apps, rules_obj)
        want = exp["match"]
        ok = m.kind == c.MatchKind(want["kind"]) and (
            set(m.candidates) == set(want["candidates"]) if want["kind"] == "ambiguous"
            else want["kind"] == "none" or m.job_id == want["job_id"])
        if not ok:
            wrong.append(f"{case['file']}: match {m.kind.value} {m.job_id} {m.candidates} "
                         f"signals={[s.value for s in m.signals]} != {want}")
            continue
        if not check_change:
            continue
        v = R.classify(h, body, rules_obj)
        if m.kind == c.MatchKind.AMBIGUOUS:
            cands = [by_id[j] for j in m.candidates]
            ch = decide(cands[0], v, m, h, pol, candidates=cands)
        else:
            ch = decide(by_id[m.job_id], v, m, h, pol)
        w = exp["change"]
        reasons = w["reason"] if isinstance(w["reason"], list) else [w["reason"]]
        if ch.kind.value != w["kind"] or ch.reason.value not in reasons or ch.to_status != w["to"]:
            wrong.append(f"{case['file']}: change {ch.kind.value}/{ch.reason.value}/{ch.to_status} != "
                         f"{w['kind']}/{reasons}/{w['to']}")
    assert not wrong, f"{len(wrong)} golden rows wrong against {path.name}:\n  " + "\n  ".join(wrong)


@needs(RULES, MATCH)
def test_mail_rules_golden_matches_on_rules_min():
    _match_and_change(RULES_MIN, check_change=False)


@needs(RULES, MATCH, TRANSITION)
def test_mail_rules_golden_changes_on_rules_min():
    _match_and_change(RULES_MIN, check_change=True)


@needs(RULES, MATCH, TRANSITION)
def test_mail_rules_golden_matches_and_changes_on_the_real_file():
    if not REAL_RULES.exists():
        print("  note: config/mail_rules.yaml not there yet (WP-R1); real-file half not run")
        return
    _match_and_change(REAL_RULES, check_change=True)


def test_mail_rules_real_file_meets_the_schema_when_present():
    """Runs now: a reference reading of MS 6.1 on config/mail_rules.yaml (R1), and the E1
    platform entries R1 must carry."""
    if not REAL_RULES.exists():
        print("  note: config/mail_rules.yaml not there yet (WP-R1)")
        return
    doc = yaml.safe_load(REAL_RULES.read_text(encoding="utf-8"))
    assert schema_errors(doc, {m.value for m in design_contracts().Category}) == []
    plats = {p["id"]: p for p in doc["platforms"]}
    assert plats["workday"].get("tenant_from_local_part") and \
        "myworkdayjobs.com" in plats["workday"].get("tenant_sites", [])
    assert plats["oleeo"].get("tenant_from_subdomain") and "tal.net" in plats["oleeo"]["domains"]


# ------------------------------------------------------------------ validation

def _write(doc: dict) -> Path:
    p = Path(tempfile.mkdtemp()) / "mail_rules.yaml"
    p.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return p


def _base() -> dict:
    return yaml.safe_load(RULES_MIN.read_text(encoding="utf-8"))


def _break(fn) -> dict:
    d = copy.deepcopy(_base())
    fn(d)
    return d


_BROKEN = [  # (what, mutation, the entry the error must name: any of)
    ("bad regex", lambda d: d["categories"]["acknowledged"]["phrases"][0].update(re="thank (you"),
     ("ack.thank_applying",)),
    ("duplicate id", lambda d: d["gates"]["outreach"].append({"id": "ack.received", "re": "x"}),
     ("ack.received",)),
    ("unknown top-level key", lambda d: d.update(extra_key=1), ("extra_key",)),
    ("unknown category", lambda d: d["categories"].update(hired={"phrases": [{"id": "h.x", "re": "x"}]}),
     ("hired",)),
    ("dominates an unknown category", lambda d: d["dominates"]["offer"].append("hired"),
     ("offer", "hired")),
    ("version", lambda d: d.update(version=2), ("version",)),
    ("upper-case domain", lambda d: d["platforms"][0]["domains"].append("Greenhouse.IO"),
     ("greenhouse", "Greenhouse.IO")),
    ("domain with @", lambda d: d["job_boards"].append("jobs@linkedin.com"), ("jobs@linkedin.com",)),
    ("both tenant flags (E1)", lambda d: d["platforms"][1].update(tenant_from_subdomain=True),
     ("workday",)),
    ("bad id characters", lambda d: d["gates"]["account"][0].update(id="Acc-Verify"), ("Acc-Verify",)),
    ("unknown phrase key", lambda d: d["gates"]["account"][0].update(where="subject"),
     ("acc.verify_email", "where")),
]


@needs(RULES)
def test_mail_rules_every_validation_error_names_its_entry():
    R = _r()
    load(RULES_MIN)                                        # the base file is valid
    missed = []
    for what, mutate, names in _BROKEN:
        try:
            load(_write(_break(mutate)))
        except R.RulesError as e:
            said = f"{getattr(e, 'entry_id', '')} {e}"
            if not any(n in said for n in names):
                missed.append(f"{what}: error {said!r} names none of {names}")
        else:
            missed.append(f"{what}: loaded without a RulesError")
    assert not missed, missed


@needs(RULES)
def test_mail_rules_keeps_the_e1_platform_keys():
    """E1: tenant_sites and the tenant flags load (they feed match.tenants_from_hosts); a
    platform with neither flag is fine."""
    R = _r()
    doc = _base()
    doc["platforms"].append({"id": "newats", "kind": "ats", "domains": ["newats.example"]})
    rules_obj = load(_write(doc))
    h, _b = unit_header("New ATS <noreply@mail.newats.example>", "Thank you for applying")
    assert R.platform_of(h, rules_obj) == "newats"


# ------------------------------------------------------------------ gates (MS 6.2)

@needs(RULES)
def test_mail_rules_platform_of_reads_sender_domains():
    R = _r()
    rules_obj = load()
    for frm, want in ((GH, "greenhouse"), (WD, "workday"),
                      ("Contoso <noreply@contosobank.tal.net>", "oleeo"),
                      ("HireVue <noreply@hirevue.com>", "hirevue"),
                      ("Jordan <jordan.lee@example.com>", ""), ("LinkedIn <jobs@linkedin.com>", "")):
        h, _b = unit_header(frm, "Hello")
        assert R.platform_of(h, rules_obj) == want, frm


@needs(RULES)
def test_mail_rules_header_gate_order_first_hit_decides():
    c = _c()
    rules_obj = load()
    old = "Wed, 15 Jul 2026 09:00:00 +0000"
    me = "Alex Applicant <alex.applicant@inbox.example>"
    cases = [
        # (from, subject, kwargs, expected)                      the gates that also hold
        (me, "Re: hi", dict(date=old, labels=("\\Sent",)), c.Reason.TOO_OLD),       # own
        (me, "Re: hi", dict(headers={"Auto-Submitted": "auto-replied"}), c.Reason.OWN_MAIL),
        ("Jordan <jordan.lee@example.com>", "Re: hi", dict(labels=("\\Draft",)), c.Reason.OWN_MAIL),
        ("LinkedIn <jobs-noreply@linkedin.com>", "Your application was sent",
         dict(headers={"Auto-Submitted": "auto-replied"}), c.Reason.AUTO_REPLY),    # job board
        ("LinkedIn <jobs-noreply@linkedin.com>", "Your application was sent",
         dict(headers={"List-ID": "<jobs.linkedin.com>"}), c.Reason.JOB_BOARD),     # bulk
        ("Indeed relay <reply@example.com>", "Re: your application",
         dict(headers={"Reply-To": "relay <r123@indeedemail.com>"}), c.Reason.JOB_BOARD),
        ("Deals <deals@shop.example>", "Weekly", dict(headers={"List-ID": "<deals.shop.example>"}),
         c.Reason.NOT_JOB_MAIL),                                                    # bulk
        (GH, "Newsletter", dict(headers={"Precedence": "bulk"}), c.Reason.BULK),
        (GH, "Newsletter", dict(headers={"Precedence": "list"}), c.Reason.BULK),
        (GH, "Out of office: back Monday", {}, c.Reason.AUTO_REPLY),               # subject phrase
        ("Jordan <jordan.lee@example.com>", "Hi", dict(headers={"X-Autoreply": "yes"}), c.Reason.AUTO_REPLY),
        # Not skipped: auto-generated ATS mail; a Reply-To platform; a matched thread; bulk in a
        # matched thread; an employer domain.
        (WD, "Thank you for applying", dict(headers={"Auto-Submitted": "auto-generated"}), None),
        ("Careers <careers@shop.example>", "Re: your application",
         dict(headers={"Reply-To": "no-reply@greenhouse.io"}), None),
        ("Jordan <jordan@mail.example>", "Re: interview", dict(gm_thrid="1800000000000000901"), None),
        (GH, "Re: interview", dict(gm_thrid="1800000000000000901", headers={"List-ID": "<x.example>"}), None),
        ("Jordan <jordan.lee@example.com>", "Hi", {}, None),
    ]
    wrong = []
    for frm, subject, kw, want in cases:
        h, body = unit_header(frm, subject, "Hello.", **kw)
        got = _r().header_gate(h, rules_obj, own=golden_own(), window_start=WINDOW,
                               threads=golden_threads(), employer_regs=golden_employer_regs())
        if got != want:
            wrong.append(f"{frm} / {subject} / {kw}: {got} != {want}")
    assert not wrong, wrong


@needs(RULES)
def test_mail_rules_content_gate_order_and_thread_exemption():
    c, R = _c(), _r()
    doc = _base()
    doc["gates"]["auto_reply"].append({"id": "ar.away_body", "re": "i am away until", "in": "body"})
    rules_obj = load(_write(doc))
    cases = [
        ("I am away until Monday. Your security code is 1234.", "9", c.Reason.AUTO_REPLY),
        ("Your security code is 1234. More jobs you may like below.", "9", c.Reason.ACCOUNT_MAIL),
        ("Jobs you may like. I came across your profile.", "9", c.Reason.JOB_ALERT),
        ("I came across your profile and would like to talk.", "9", c.Reason.OUTREACH),
        ("I came across your profile again while reviewing.", "1800000000000000901", None),
        ("Please reset your password using the link.", "9", c.Reason.ACCOUNT_MAIL),
        ("Your account has been created.", "9", c.Reason.ACCOUNT_MAIL),
        ("Out of office is in the body only. Thank you for applying.", "9", None),   # in: subject
    ]
    wrong = []
    for text, thrid, want in cases:
        h, body = unit_header(GH, "About your application", text, gm_thrid=thrid)
        got = R.content_gate(h, body, rules_obj, in_matched_thread=thrid in golden_threads())
        if got != want:
            wrong.append(f"{text!r}: {got} != {want}")
    assert not wrong, wrong


@needs(RULES)
def test_mail_rules_the_bare_word_confirm_never_trips_the_account_gate():
    """MB 4 / D-85: "confirm" alone is in acknowledgements and interview mail too."""
    R = _r()
    paths = [RULES_MIN] + ([REAL_RULES] if REAL_RULES.exists() else [])
    texts = ["This email confirms that we have received your application.",
             "Please confirm your attendance at the interview on Tuesday.",
             "We confirm receipt of your application for the Graduate Analyst role.",
             "Kindly confirm the time slot that suits you.",
             "Confirmed: your interview is booked."]
    for path in paths:
        rules_obj = load(path)
        for t in texts:
            h, body = unit_header(GH, "Confirmation", t)
            assert R.content_gate(h, body, rules_obj, in_matched_thread=False) is None, (path.name, t)


# ------------------------------------------------------------------ classifier (MS 6.3)

def _classify(text, subject="About your application", **kw):
    h, body = unit_header(GH, subject, text, **kw)
    return _r().classify(h, body, load())


@needs(RULES)
def test_mail_rules_dominates_picks_a_winner():
    c = _c()
    cases = [
        ("We regret to inform you that we will keep your resume on file.", c.Category.REJECTED),
        ("We are pleased to offer you the role. Please complete the assessment by Friday.", c.Category.OFFER),
        ("Thank you for applying. Please select a time for your interview.", c.Category.INTERVIEW),
        ("Thank you for applying. Complete the assessment by Friday.", c.Category.ASSESSMENT),
        ("Thank you for applying. Your application has been withdrawn.", c.Category.WITHDRAWN),
        ("The position has been put on hold. We will keep your details on file.", c.Category.POSTING_CLOSED),
        ("The position has been filled. The position has been closed.", c.Category.REJECTED),
    ]
    for text, want in cases:
        v = _classify(text)
        assert v.category == want and v.tier == c.Tier.RULE and v.status_words, (text, v)


@needs(RULES)
def test_mail_rules_conflict_gives_unknown_with_status_words():
    c = _c()
    ids = _phrase_categories(RULES_MIN)
    for text, cats in (("The position has been closed. Your application has been withdrawn.",
                        {"posting_closed", "withdrawn"}),
                       ("We are delighted to offer you a place. Your application has been withdrawn.",
                        {"offer", "withdrawn"})):
        v = _classify(text)
        assert v.category == c.Category.UNKNOWN and v.status_words, v
        assert v.rule_id.startswith("conflict:"), v.rule_id
        assert {ids.get(p, p) for p in v.rule_id.removeprefix("conflict:").split("+")} == cats, v.rule_id
        assert _r().needs_model(v)


@needs(RULES)
def test_mail_rules_portal_update_drops_out_when_anything_else_hits():
    c = _c()
    assert _classify("Please log in to view the update.").category == c.Category.PORTAL_UPDATE
    assert _classify("We regret to inform you of our decision. Log in to view details."
                     ).category == c.Category.REJECTED
    assert _classify("Thank you for applying. Log in to view your application."
                     ).category == c.Category.ACKNOWLEDGED


@needs(RULES)
def test_mail_rules_no_hit_status_words_from_weak_words_calendar_or_script():
    c, R = _c(), _r()
    v = _classify("We will share the next steps soon.")
    assert v.category == c.Category.UNKNOWN and v.status_words and R.needs_model(v)
    v = _classify("Your candidate profile has been saved.")
    assert v.category == c.Category.UNKNOWN and not v.status_words and not R.needs_model(v)
    v = _classify("Meeting details are attached.", calendar=True)
    assert v.category == c.Category.UNKNOWN and v.status_words                # calendar, no "interview"
    v = _classify("Join us for the interview.", calendar=True)
    assert v.category == c.Category.INTERVIEW                                 # calendar phrase
    assert _classify("Ten interview tips for graduates.").category == c.Category.UNKNOWN
    # >= 20% of the letters non-Latin -> status_words (MS 6.3, MB 4)
    v = _classify("感谢您申请我们公司的职位。经过慎重考虑，我们很遗憾地通知您。", subject="Graduate Analyst")
    assert v.category == c.Category.UNKNOWN and v.status_words
    few = "Your candidate profile has been saved for the Graduate Analyst role in our system. 谢谢"
    letters = [ch for ch in few + "About your application" if ch.isalpha()]
    assert sum(ord(ch) > 0x24F for ch in letters) / len(letters) < 0.2
    assert not _classify(few).status_words


@needs(RULES)
def test_mail_rules_phrases_are_whole_words_case_insensitive_and_respect_in():
    c = _c()
    assert _classify("THANK YOU FOR APPLYING to Northwind.").category == c.Category.ACKNOWLEDGED
    assert _classify("Prethank you for applyingly.").category == c.Category.UNKNOWN    # not whole words
    assert _classify("", subject="Application received").category == c.Category.ACKNOWLEDGED
    assert _classify("We are pleased to offer you an interview next week.").category != c.Category.OFFER


@needs(RULES)
def test_mail_rules_quote_is_the_hit_sentence_at_most_200_characters():
    c, R = _c(), _r()
    v = _classify("Hello Alex.\n\nWe regret to inform you that the   role went to\tsomeone else. Best wishes!")
    assert v.quote == "We regret to inform you that the role went to someone else.", v.quote
    filler = " ".join(["the committee reviewed many strong profiles across several rounds"] * 6)
    long = f"After {filler} we regret to inform you that we chose another candidate {filler}."
    v = _classify(long)
    assert v.category == c.Category.REJECTED and 0 < len(v.quote) <= c.QUOTE_MAX, len(v.quote)
    assert "…" in v.quote and "regret to inform you" in v.quote
    inner = v.quote.strip("…").strip()
    assert norm_quote(inner) in norm_quote(long)
    words = set(re.findall(r"\w+", long))
    assert inner.split()[0].strip(".,") in words and inner.split()[-1].strip(".,") in words
    # quote_around directly: the sentence around a span.
    text = "First line here. Second sentence holds the offer letter details! Third."
    s = text.index("offer letter")
    assert R.quote_around(text, s, s + len("offer letter")) == "Second sentence holds the offer letter details!"
    v = _classify("", subject="Offer of employment - Graduate Analyst")
    assert v.category == c.Category.OFFER and v.quote == "Offer of employment - Graduate Analyst"


@needs(RULES)
def test_mail_rules_d92_assessment_vendors_never_decide_interview():
    """D-92 (1): a rule-tier `interview` verdict from a `kind: assessment` platform is read
    as `assessment`; the same words from the employer stay `interview`. (2) An assessment
    centre or superday is `interview`. (3) "confirm your email" may be an account phrase."""
    c, R = _c(), _r()
    paths = [RULES_MIN] + ([REAL_RULES] if REAL_RULES.exists() else [])
    for path in paths:
        rules_obj = load(path)
        for frm in ("HireVue <noreply@hirevue.com>", "Codility <no-reply@codility.com>",
                    "Example Corp via HackerRank <support@hackerrankforwork.com>"):
            for text in ("We would like to invite you to an interview for the Graduate Analyst role.",
                         "Your live video interview has been scheduled. Interview confirmation below."):
                h, body = unit_header(frm, "Your next step", text)
                v = R.classify(h, body, rules_obj)
                assert v.category == c.Category.ASSESSMENT, (path.name, frm, text, v)
        h, body = unit_header("Jordan Lee <jordan.lee@example.com>", "Your next step",
                              "We would like to invite you to an interview for the Graduate Analyst role.")
        assert R.classify(h, body, rules_obj).category == c.Category.INTERVIEW, path.name
        h, body = unit_header("Jordan Lee <jordan.lee@example.com>", "Assessment centre",
                              "We are pleased to invite you to our assessment centre on 12 November.")
        assert R.classify(h, body, rules_obj).category == c.Category.INTERVIEW, path.name
        h, body = unit_header(WD, "Action needed", "Please confirm your email address to continue.")
        assert R.content_gate(h, body, rules_obj, in_matched_thread=False) == c.Reason.ACCOUNT_MAIL, path.name
        h, body = unit_header("HireVue <noreply@hirevue.com>", "Offer",
                              "We are delighted to offer you the position.")
        assert R.classify(h, body, rules_obj).category == c.Category.OFFER, path.name   # only interview turns


def test_mail_rules_oracles_are_live():
    assert_live(RULES, _W0, "test_mail_rules")


note_waiting("test_mail_rules", _W0)
