"""Tailor golden cases A-C (tailor_design.md §15): terms, coverage, deterministic rewrite,
validator rejections and resume-wide invariants. Plan: tests/plans/tailor_test_plan.md.

Fixtures: tests/fixtures/tailor/aliases_golden.yaml and case_{a,b,c}/{master.json, resume.txt,
jd.txt, expected.json}. Synthetic people only; no model call (deterministic mode, M20).

Two kinds of test:
  1. Fixture integrity (run now): the fixtures agree with the design's own arithmetic.
  2. Oracles for lane T's modules, decorated `@needs(...)`: not defined until the module
     exists (one line at import says what is waiting). Verify: `python tests/run_tests.py -k tailor_golden`.

The design fixes `terms.find`, `mapping.coverage` and `validate.bullet`'s name; it leaves the
other stage call shapes open. Those are ASSUMED in the `_api` block below and nowhere else:
if lane T picks other names, change that block (and tell the tester), not the oracles.
"""
from __future__ import annotations

import importlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobscraper.tailor.contracts import (  # noqa: E402
    WEIGHT_PREFERRED, WEIGHT_REQUIRED, Bullet, Contact, Entry, IssueCode, JdTerm, MasterResume,
    Section, SectionKind, TermStatus,
)

FIX = ROOT / "tests" / "fixtures" / "tailor"
ALIASES = FIX / "aliases_golden.yaml"
CASES = ("case_a", "case_b", "case_c")

# Number tokens exactly as validator §8.1 defines them (commas inside digit groups removed).
NUM = re.compile(r"\d+(?:[.,]\d+)*(?:%|[kKmMbB]\b|x\b)?")

_WAITING: list[tuple[str, str]] = []


def _missing(spec: str) -> str:
    mod, _, attr = spec.partition(":")
    try:
        obj = importlib.import_module(mod)
    except ModuleNotFoundError as e:
        if e.name and (mod == e.name or mod.startswith(e.name + ".")):
            return mod
        raise
    for part in filter(None, attr.split(".")):
        if not hasattr(obj, part):
            return spec
        obj = getattr(obj, part)
    return ""


def needs(*specs: str):
    gone = [m for m in (_missing(s) for s in specs) if m]

    def deco(fn):
        if gone:
            _WAITING.append((fn.__name__, gone[0]))
            return None
        return fn
    return deco


# ------------------------------------------------------------------ fixtures

def _load(case: str):
    d = FIX / case
    return (json.loads((d / "master.json").read_text(encoding="utf-8")),
            (d / "jd.txt").read_text(encoding="utf-8"),
            (d / "resume.txt").read_text(encoding="utf-8"),
            json.loads((d / "expected.json").read_text(encoding="utf-8")))


def master_from_json(m: dict) -> MasterResume:
    """Build the contract dataclasses from the cache JSON shape (§3.1 `master`)."""
    return MasterResume(
        resume_hash=m["resume_hash"], source_name=m["source_name"], contact=Contact(**m["contact"]),
        summary=m["summary"], page_count=m["page_count"], parsed_by=m["parsed_by"], parsed_at=m["parsed_at"],
        sections=[Section(heading=s["heading"], kind=SectionKind(s["kind"]), items=list(s["items"]),
                          entries=[Entry(**{**e, "bullets": [Bullet(**b) for b in e["bullets"]]})
                                   for e in s["entries"]])
                  for s in m["sections"]])


def _dictionary_strings() -> list[str]:
    import yaml
    data = yaml.safe_load(ALIASES.read_text(encoding="utf-8"))
    out = []
    for t in data["terms"]:
        out += [t["canonical"], *t.get("variants", []), *t.get("instances", [])]
    return sorted(out, key=len, reverse=True)


def _nums(text: str) -> Counter:
    """§8.1 number multiset. Digits inside a dictionary term ("k8s") are not numbers: the design
    expects k8s -> Kubernetes to keep bullet 2's numbers {95, 35%} (raised to the architect: the
    literal "no left boundary" rule would report NUMBER_DROPPED "8")."""
    for s in _dictionary_strings():
        if any(c.isdigit() for c in s):
            text = re.sub(rf"(?<![\w]){re.escape(s)}(?![\w])", " ", text)
    return Counter(t.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", t.rstrip("%kKmMbBx")) else t
                   for t in NUM.findall(text))


# ------------------------------------------------------------------ _api: ASSUMED call shapes

def _api():
    T = importlib.import_module("jobscraper.tailor.terms")
    M = importlib.import_module("jobscraper.tailor.mapping")
    R = importlib.import_module("jobscraper.tailor.rewrite")
    V = importlib.import_module("jobscraper.tailor.validate")
    return T, M, R, V


def _dictionary(T):
    return T.load_dictionary(ALIASES)                         # ASSUMED (§4.2 Dictionary from aliases.yaml)


def _terms(case: str):
    """JD terms classified against the master, as lane T's pipeline would produce them."""
    T, M, R, V = _api()
    m, jd, _txt, exp = _load(case)
    master = master_from_json(m)
    d = _dictionary(T)
    terms = T.extract(jd, d)                                  # ASSUMED: §4.3 -> list[JdTerm], JD order
    terms = M.classify(terms, master, d, attested=())         # ASSUMED: §5.1 -> list[JdTerm]
    return master, d, terms, jd, exp


def _tailored(case: str):
    T, M, R, V = _api()
    master, d, terms, _jd, exp = _terms(case)
    swapped, changes = R.swap(master, terms, d)               # ASSUMED: §6.2 -> (MasterResume, [BulletChange])
    ordered = R.reorder(swapped, terms, attested=())          # ASSUMED: §6.3 bullets + skills order
    return master, ordered, terms, changes, exp


def _text(T_or_M, master: MasterResume) -> str:
    return T_or_M.resume_text(master)                         # ASSUMED: §5.1 leaves joined, contact excluded


# ================================================================== 1. fixture integrity (run now)

def test_golden_masters_load_into_the_contracts_with_ids_in_reading_order():
    for case in CASES:
        m, _jd, _txt, _exp = _load(case)
        master = master_from_json(m)
        ids = [b.id for _e, b in master.bullets()]
        assert ids == list(range(1, len(ids) + 1)), case
        assert [e.id for _s, e in master.entries()] == [f"e{i}" for i in range(1, len(list(master.entries())) + 1)]


def test_golden_leaves_occur_in_the_resume_text():
    """§3.3 leaf check, simplified: the fixture master is a faithful parse of resume.txt."""
    for case in CASES:
        m, _jd, txt, _exp = _load(case)
        master = master_from_json(m)
        leaves = [master.contact.name, *[s.heading for s in master.sections], *master.skills()]
        for _s, e in master.entries():
            leaves += [e.title, e.organisation, e.dates, *[b.text for b in e.bullets]]
        for leaf in filter(None, leaves):
            assert leaf in txt, (case, leaf)


def test_golden_terms_occur_in_the_jd_with_their_spelling():
    for case in CASES:
        _m, jd, _txt, exp = _load(case)
        positions = [jd.find(t["term"]) for t in exp["terms"]]
        assert all(p >= 0 for p in positions), (case, exp["terms"])
        assert positions == sorted(positions), f"{case}: terms are listed in JD order"


def test_golden_coverage_follows_the_f21_weights():
    for case in CASES:
        _m, _jd, _txt, exp = _load(case)
        w = {t["term"]: WEIGHT_REQUIRED if t["required"] else WEIGHT_PREFERRED for t in exp["terms"]}
        total = sum(w.values())
        before = sum(w[t["term"]] for t in exp["terms"] if t["status"] == "present_exact")
        after = before + sum(w[t["term"]] for t in exp["terms"]
                             if t["status"] == "present_variant" and t["via"] in ("alias", "acronym"))
        assert [before, total] == exp["coverage_before"], case
        assert [after, total] == exp["coverage_after"], case
        assert after >= before


def test_golden_rewrites_keep_every_number_and_every_protected_field():
    for case in CASES:
        m, _jd, _txt, exp = _load(case)
        master = master_from_json(m)
        for _e, b in master.bullets():
            after = exp["bullets_after"][str(b.id)]
            assert _nums(after) == _nums(b.text), (case, b.id)
            assert sorted(_nums(after).elements()) == sorted(exp["numbers_per_bullet"][str(b.id)]), (case, b.id)
        for word in exp["absent"]:
            assert not re.search(rf"(?<![\w/]){re.escape(word)}(?![\w/])", " ".join(exp["bullets_after"].values())
                                 + " " + " ".join(exp["skills_after"])), (case, word)


def test_golden_number_rejections_really_change_the_numbers():
    """The validator rows that expect a number issue differ from the post-swap bullet in exactly that number."""
    for case in CASES:
        _m, _jd, _txt, exp = _load(case)
        for row in exp["rejections"]:
            src, out = exp["bullets_after"][str(row["bullet"])], row["out"]
            added, dropped = _nums(out) - _nums(src), _nums(src) - _nums(out)
            want_added = sorted(d for c, d in row["issues"] if c == "number_added")
            want_dropped = sorted(d for c, d in row["issues"] if c == "number_dropped")
            assert sorted(added.elements()) == want_added, (case, row)
            assert sorted(dropped.elements()) == want_dropped, (case, row)
            assert {c for c, _d in row["issues"]} <= {i.value for i in IssueCode}


# ================================================================== 2. design-fixed signatures (lane T)

@needs("jobscraper.tailor.terms")
def test_find_matches_tokens_and_ambiguous_terms_only_when_capitalised():
    T = importlib.import_module("jobscraper.tailor.terms")
    text = "We go-live with Go and Node.js APIs; CI/CD on GitHub."
    assert [text[s:e] for s, e in T.find(text, "Go")] == ["Go"], "lowercase 'go' never counts"
    assert [text[s:e] for s, e in T.find(text, "node.js")] == ["Node.js"]
    assert [text[s:e] for s, e in T.find(text, "API")] == ["APIs"], "a trailing s folds"
    assert T.find(text, "Git") == [], "Git is not inside GitHub"
    assert [text[s:e] for s, e in T.find(text, "CI/CD")] == ["CI/CD"]


@needs("jobscraper.tailor.mapping")
def test_coverage_counts_only_the_jd_spelling():
    M = importlib.import_module("jobscraper.tailor.mapping")
    terms = [JdTerm("PostgreSQL", "postgresql", True), JdTerm("Kafka", "kafka", False)]
    assert M.coverage(terms, "Built APIs with Postgres.") == 0.0, "a variant does not count"
    assert abs(M.coverage(terms, "Built APIs with PostgreSQL.") - 2 / 3) < 1e-9
    assert M.coverage([], "anything") == 0.0


# ================================================================== 3. golden cases (lane T; _api ASSUMED)

def _check_terms(case):
    _master, _d, terms, jd, exp = _terms(case)
    got = [(t.term, t.required, t.status.value, t.variant, t.via, t.related) for t in terms]
    want = [(t["term"], t["required"], t["status"], t["variant"], t["via"], t["related"]) for t in exp["terms"]]
    assert got == want, f"{case}\n got  {got}\n want {want}"
    T = importlib.import_module("jobscraper.tailor.terms")
    assert T.knockouts(jd) == exp["knockouts"]               # ASSUMED name (§4.3 step 5)


def _check_coverage(case):
    T, M, R, V = _api()
    master, tailored, terms, _changes, exp = _tailored(case)
    b, n = exp["coverage_before"]
    a, _n = exp["coverage_after"]
    assert abs(M.coverage(terms, _text(M, master)) - b / n) < 1e-4, case
    assert abs(M.coverage(terms, _text(M, tailored)) - a / n) < 1e-4, case


def _check_rewrite(case):
    T, M, R, V = _api()
    master, tailored, _terms_, changes, exp = _tailored(case)
    got = {str(b.id): b.text for _e, b in tailored.bullets()}
    assert got == exp["bullets_after"], case
    order = {e.id: [b.id for b in e.bullets] for _s, e in tailored.entries()}
    for eid, ids in exp["bullet_order"].items():
        assert order[eid] == ids, (case, eid, order[eid])
    assert tailored.skills() == exp["skills_after"], case
    text = _text(M, tailored)
    for word in exp["absent"]:
        assert not T.find(text, word), (case, word)
    # invariants §8.3: protected fields, headings, contact byte-equal
    for (s0, e0), (s1, e1) in zip(master.entries(), tailored.entries()):
        assert (s0.heading, e0.id, e0.title, e0.organisation, e0.location, e0.dates, e0.subtitle) == \
               (s1.heading, e1.id, e1.title, e1.organisation, e1.location, e1.dates, e1.subtitle), case
    assert tailored.contact == master.contact
    assert V.invariants(master, tailored) == [], case        # ASSUMED name (§8.3) -> list of violations
    assert all(not c.issues for c in changes if c.source == "swap"), "swaps pass §8.1 by construction"


def _check_rejections(case):
    T, M, R, V = _api()
    _master, d, _terms_, _jd, exp = _terms(case)
    for row in exp["rejections"]:
        src = exp["bullets_after"][str(row["bullet"])]
        issues = V.bullet(src, row["out"], V.BulletContext(dictionary=d))   # ctx ASSUMED (§8.1)
        got = sorted((i.code.value, i.detail) for i in issues)
        assert got == sorted(map(tuple, row["issues"])), f"{case} bullet {row['bullet']}: {got}"
    # alias-equal and unchanged rewrites raise nothing
    for src in exp["bullets_after"].values():
        assert V.bullet(src, src, V.BulletContext(dictionary=d)) == []


_LANE_T = ("jobscraper.tailor.terms", "jobscraper.tailor.mapping",
           "jobscraper.tailor.rewrite", "jobscraper.tailor.validate")


@needs(*_LANE_T)
def test_case_a_terms_and_status():
    _check_terms("case_a")


@needs(*_LANE_T)
def test_case_b_terms_and_status():
    _check_terms("case_b")


@needs(*_LANE_T)
def test_case_c_terms_status_and_knockouts():
    _check_terms("case_c")


@needs(*_LANE_T)
def test_case_a_coverage_29_to_64():
    _check_coverage("case_a")


@needs(*_LANE_T)
def test_case_b_coverage_50_unchanged():
    _check_coverage("case_b")


@needs(*_LANE_T)
def test_case_c_coverage_38_to_54():
    _check_coverage("case_c")


@needs(*_LANE_T)
def test_case_a_variant_swaps_and_article_fix():
    _check_rewrite("case_a")


@needs(*_LANE_T)
def test_case_b_no_tool_swapping_and_reorder():
    _check_rewrite("case_b")


@needs(*_LANE_T)
def test_case_c_no_claim_upgrade():
    _check_rewrite("case_c")


@needs(*_LANE_T)
def test_case_a_validator_rejections():
    _check_rejections("case_a")


@needs(*_LANE_T)
def test_case_b_validator_rejections():
    _check_rejections("case_b")


@needs(*_LANE_T)
def test_case_c_validator_rejections():
    _check_rejections("case_c")


@needs(*_LANE_T)
def test_invariants_reject_a_changed_employer_or_date():
    T, M, R, V = _api()
    master, tailored, *_rest = _tailored("case_a")
    tailored.sections[1].entries[0].organisation = "Acme Logistics"          # "Pte Ltd" dropped
    assert V.invariants(master, tailored), "a changed employer must fail tailoring"
    master, tailored, *_rest = _tailored("case_c")
    tailored.sections[0].entries[0].dates = "Jul 2023 – Dec 2025"
    assert V.invariants(master, tailored), "a changed date must fail tailoring"


if _WAITING:
    print(f"[test_tailor_golden] {len(_WAITING)} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in _WAITING})))
