"""WP-T3 oracles: the matcher (mail_status_design.md 7 with amendment E1; build plan WP-T3,
WP-S2). Verify: `python tests/run_tests.py -k mail_match`. The golden match rows run in
test_mail_rules (`-k mail_rules`, MS 14).

Skip-clean until `jobscraper.mailstatus.match` exists (it needs `rules` too); after that,
`test_mail_match_oracles_are_live` fails if any oracle here still waits.

ASSUMED call shapes (build plan WP-S2):
  match.norm_company(name, suffixes) -> str     match.norm_role(title) -> str
  match.compact(s) -> str                       match.variants(app, rules) -> iterable of str
  match.tenants_from_hosts(hosts, rules) -> tuple[str, ...]
  match.match(h, body, apps, rules) -> MatchResult   (signals in Signal order)
"""
from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_support import (  # noqa: E402
    MATCH, RULES, RULES_MIN, WAITING, app_candidate, assert_live, load, needs, note_waiting,
    unit_header,
)

_W0 = len(WAITING)
SUFFIXES = yaml.safe_load(RULES_MIN.read_text(encoding="utf-8"))["company_suffixes"]
GH = "no-reply@greenhouse.io"


def _c():
    from jobscraper.mailstatus import contracts
    return contracts


def _m():
    from jobscraper.mailstatus import match
    return match


def _app(job_id, company, role="", **kw):
    d = dict(job_id=job_id, status=kw.pop("status", "applied"),
             company_names=(company,) if isinstance(company, str) else tuple(company), role=role,
             employer_domains=(), tenants=(), board_slugs=(), req_ids=(), threads=(),
             owner_changed_at=None, last_event_at=None)
    d.update(kw)
    return app_candidate(d)


EX_SWE = dict(job_id="ex-swe", company="Example Corp", role="Graduate Software Engineer",
              employer_domains=("example.com",), req_ids=("R0012345",))
EX_DATA = dict(job_id="ex-data", company="Example Corp", role="Data Analyst Graduate",
               employer_domains=("example.com",), req_ids=("R0067890",))
NW = dict(job_id="nw", company="Northwind Traders Pte Ltd", role="Graduate Analyst",
          employer_domains=("northwind.example",), board_slugs=("northwind",))
CT = dict(job_id="ct", company="Contoso Bank", role="Technology Graduate Programme",
          employer_domains=("contoso.example",))


def _a(spec, **over):
    s = dict(spec)
    s.update(over)
    return _app(s.pop("job_id"), s.pop("company"), s.pop("role", ""), **s)


def _match(apps, frm, subject, body="Hello.", **kw):
    h, b = unit_header(frm, subject, body, **kw)
    return _m().match(h, b, tuple(apps), load())


def _sig(*names):
    S = _c().Signal
    return {S(n) for n in names}


# ------------------------------------------------------------------ normalisation

@needs(RULES, MATCH)
def test_mail_match_norm_company_role_and_compact():
    M = _m()
    assert M.norm_company("Example Holdings Pte Ltd", SUFFIXES) == "example"
    assert M.norm_company("Northwind Traders Pte. Ltd.", SUFFIXES) == "northwind traders"
    assert M.norm_company("Contoso & Partners Pte Ltd", SUFFIXES) == "contoso and partners"
    assert M.norm_company("Contoso Café Singapore", SUFFIXES) == "contoso cafe"
    assert M.norm_company("EXAMPLE CORP", SUFFIXES) == "example"
    assert M.norm_role("Graduate Software Engineer (m/f/d)") == "graduate software engineer"
    assert M.norm_role("Data Analyst - Graduate,  2027") == "data analyst graduate 2027"
    assert M.compact("Contoso Bank") == "contosobank"
    assert M.compact("contoso-bank") == "contosobank"
    assert M.compact("Example Bank") == "examplebank"


@needs(RULES, MATCH)
def test_mail_match_variants_cover_names_slugs_tenants_and_domain_labels():
    """MS 7: company_names, board_slugs (hyphens -> spaces), tenants and the first label of
    each employer domain, all normalised."""
    app = _a(NW, board_slugs=("northwind-traders",), tenants=("nwtraders",),
             company=("Northwind Traders Pte Ltd", "Northwind Holdings"))
    got = set(_m().variants(app, load()))
    assert {"northwind traders", "northwind", "nwtraders"} <= got, got


@needs(RULES, MATCH)
def test_mail_match_tenants_from_hosts_strict_subdomains_of_tenant_sites():
    """E1: the first label of a posting or careers host under a rules `tenant_sites` suffix."""
    got = _m().tenants_from_hosts(("examplecorp.wd3.myworkdayjobs.com", "contosobank.tal.net",
                                   "myworkdayjobs.com", "tal.net", "careers.example.com",
                                   "evil-myworkdayjobs.com", "ExampleCorp.WD3.MyWorkdayJobs.com"),
                                  load())
    assert isinstance(got, tuple)
    assert set(got) == {"examplecorp", "contosobank"}, got


# ------------------------------------------------------------------ each signal alone

@needs(RULES, MATCH)
def test_mail_match_each_employer_signal_alone():
    c = _c()
    nw = _a(NW)
    cases = [
        # (from, subject, body, kw, kind, signals)
        ("HR <hr@northwind.example>", "Hello", "Hi.", {}, "strong", {"employer_domain"}),
        ("Hiring <%s>" % GH, "Hello", "Hi.", {"headers": {"Reply-To": "talent@northwind.example"}},
         "strong", {"employer_domain"}),
        ("Northwind Traders <%s>" % GH, "Hello", "Hi.", {}, "strong", {"name_in_sender"}),
        ("Hiring <%s>" % GH, "Your Northwind application", "Hi.", {}, "strong", {"name_in_subject"}),
        ("Hiring <%s>" % GH, "Update", "Thanks for your interest in Northwind.", {}, "weak",
         {"name_in_body"}),
        ("Jordan <jordan@mail.example>", "Re: chat", "See you then.", {"gm_thrid": "t-nw"},
         "strong", {"thread"}),
    ]
    for frm, subject, body, kw, kind, sigs in cases:
        app = _a(NW, threads=("t-nw",)) if kw.get("gm_thrid") else nw
        m = _match([app], frm, subject, body, **kw)
        assert m.kind == c.MatchKind(kind) and m.job_id == "nw", (frm, subject, m)
        assert set(m.signals) == _sig(*sigs), (frm, subject, m.signals)


@needs(RULES, MATCH)
def test_mail_match_role_or_req_id_alone_is_no_match():
    c = _c()
    for subject in ("Graduate Analyst opening", "Reference R0012345"):
        m = _match([_a(NW), _a(EX_SWE)], "Hiring <%s>" % GH, subject, "Hi.")
        assert m.kind == c.MatchKind.NONE and m.job_id is None, (subject, m)
    m = _match([_a(NW)], "Hiring <%s>" % GH, "Hello", "Hi.")
    assert m.kind == c.MatchKind.NONE and m.platform == "greenhouse"


@needs(RULES, MATCH)
def test_mail_match_signals_combine_in_signal_order():
    c = _c()
    m = _match([_a(EX_SWE)], "Example Corp Careers <careers@example.com>",
               "Example Corp: Graduate Software Engineer (R0012345)",
               "Thank you for applying to Example Corp.")
    assert m.kind == c.MatchKind.STRONG and m.job_id == "ex-swe"
    want = _sig("employer_domain", "name_in_sender", "name_in_subject", "name_in_body", "role", "req_id")
    assert set(m.signals) == want, m.signals
    order = list(c.Signal)
    assert list(m.signals) == sorted(m.signals, key=order.index), m.signals
    assert m.platform == ""


# ------------------------------------------------------------------ E1 tenants

@needs(RULES, MATCH)
def test_mail_match_e1_oleeo_subdomain_matches_by_compact_name_without_an_attempt_row():
    c = _c()
    bank = _app("eb", "Example Bank", "Technology Graduate Programme")   # tenants () : made by hand
    m = _match([bank], "Graduate Recruitment <noreply@examplebank.tal.net>", "Your application",
               "Thank you.")
    assert m.kind == c.MatchKind.STRONG and m.job_id == "eb" and set(m.signals) == _sig("tenant"), m
    assert m.platform == "oleeo"


@needs(RULES, MATCH)
def test_mail_match_e1_tal_net_itself_gives_no_tenant():
    c = _c()
    bank = _app("eb", "Example Bank")
    m = _match([bank], "Recruitment <noreply@tal.net>", "Your application", "Thank you.")
    assert m.kind == c.MatchKind.NONE, m
    other = _app("eb", "Tal Pte Ltd")               # "tal" must not come from tal.net itself
    assert _match([other], "Recruitment <noreply@tal.net>", "Hello", "Hi.").kind == c.MatchKind.NONE


@needs(RULES, MATCH)
def test_mail_match_e1_workday_local_part_equal_to_the_compact_company_name():
    c = _c()
    nw = _a(NW)                                     # no tenants recorded
    m = _match([nw], "Careers <northwindtraders@myworkday.com>", "Your application", "Thank you.")
    assert m.kind == c.MatchKind.STRONG and m.job_id == "nw" and set(m.signals) == _sig("tenant"), m


@needs(RULES, MATCH)
def test_mail_match_workday_tenant_from_the_local_part_and_app_tenants():
    c = _c()
    ex = _a(EX_SWE, tenants=("examplecorp",))
    m = _match([ex], "Careers <examplecorp@myworkday.com>", "Your application", "Thank you.")
    assert m.kind == c.MatchKind.STRONG and set(m.signals) == _sig("tenant") and m.platform == "workday"
    other = _a(EX_SWE, tenants=("othertenant",), employer_domains=())
    m = _match([other], "Careers <examplecorp@myworkday.com>", "Your application", "Thank you.")
    assert c.Signal.TENANT not in m.signals, m
    # A local part only names the tenant for a platform with tenant_from_local_part.
    m = _match([_a(EX_SWE, tenants=("examplecorp",), employer_domains=())],
               "Careers <examplecorp@greenhouse.io>", "Your application", "Thank you.")
    assert c.Signal.TENANT not in m.signals, m


@needs(RULES)
def test_mail_match_e1_loader_refuses_both_tenant_flags():
    from jobscraper.mailstatus import rules as R
    doc = yaml.safe_load(RULES_MIN.read_text(encoding="utf-8"))
    bad = copy.deepcopy(doc)
    for p in bad["platforms"]:
        if p["id"] == "oleeo":
            p["tenant_from_local_part"] = True
    path = Path(tempfile.mkdtemp()) / "rules.yaml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    try:
        R.load_rules(path)
    except R.RulesError as e:
        assert "oleeo" in f"{getattr(e, 'entry_id', '')} {e}"
    else:
        raise AssertionError("both tenant flags on one platform must not load")


# ------------------------------------------------------------------ decisions (MS 7 steps 1-6)

@needs(RULES, MATCH)
def test_mail_match_one_employer_two_applications_by_role_by_req_id_or_ambiguous():
    c = _c()
    apps = [_a(EX_SWE), _a(EX_DATA)]
    frm = "Example Corp <careers@example.com>"
    m = _match(apps, frm, "Your Graduate Software Engineer application", "Thank you.")
    assert (m.kind, m.job_id) == (c.MatchKind.STRONG, "ex-swe") and c.Signal.ROLE in m.signals
    m = _match(apps, frm, "Application R0067890", "Thank you.")
    assert (m.kind, m.job_id) == (c.MatchKind.STRONG, "ex-data") and c.Signal.REQ_ID in m.signals
    m = _match(apps, frm, "Thank you for applying", "We will be in touch.")
    assert m.kind == c.MatchKind.AMBIGUOUS and set(m.candidates) == {"ex-swe", "ex-data"}
    assert m.job_id is None
    m = _match(apps, frm, "Graduate Software Engineer and Data Analyst Graduate", "Both roles.")
    assert m.kind == c.MatchKind.AMBIGUOUS and set(m.candidates) == {"ex-swe", "ex-data"}
    # >= 80% of the role's tokens (at least 2) on one line count as the role.
    m = _match(apps, frm, "Update", "Software Engineer, Graduate intake\nThanks.")
    assert (m.kind, m.job_id) == (c.MatchKind.STRONG, "ex-swe"), m


@needs(RULES, MATCH)
def test_mail_match_two_companies_tie_is_ambiguous_and_the_stronger_tier_wins():
    c = _c()
    apps = [_a(NW), _a(CT)]
    m = _match(apps, "Events <%s>" % GH, "Northwind and Contoso Bank graduate fair", "Hello.")
    assert m.kind == c.MatchKind.AMBIGUOUS and set(m.candidates) == {"nw", "ct"}, m
    m = _match(apps, "Northwind Traders <%s>" % GH, "Your application",
               "We also partner with Contoso Bank on events.")
    assert (m.kind, m.job_id) == (c.MatchKind.STRONG, "nw"), m


@needs(RULES, MATCH)
def test_mail_match_common_word_and_short_names_count_in_the_body_only_capitalised():
    c = _c()
    sea = _app("sea", "Sea Limited", "Graduate Analyst")
    zeta = _app("zeta", "Zeta Pte Ltd", "Graduate Analyst")
    for app, lower, upper in ((sea, "We met by the sea last week.", "Thank you for applying to Sea."),
                              (zeta, "We studied the zeta function.", "Thank you for applying to Zeta.")):
        m = _match([app], "Hiring <%s>" % GH, "Update", lower)
        assert m.kind == c.MatchKind.NONE, (app.job_id, m)
        m = _match([app], "Hiring <%s>" % GH, "Update", upper)
        assert (m.kind, m.job_id) == (c.MatchKind.WEAK, app.job_id), (app.job_id, m)
        assert set(m.signals) == _sig("name_in_body")


@needs(RULES, MATCH)
def test_mail_match_thread_comes_first():
    c = _c()
    apps = [_a(EX_SWE, threads=("t1",)), _a(EX_DATA)]
    m = _match(apps, "Jordan <jordan.lee@example.com>", "Re: Data Analyst Graduate", "Hi.",
               gm_thrid="t1")
    assert (m.kind, m.job_id) == (c.MatchKind.STRONG, "ex-swe") and c.Signal.THREAD in m.signals, m
    shared = [_a(EX_SWE, threads=("t2",)), _a(EX_DATA, threads=("t2",))]
    m = _match(shared, "Jordan <jordan.lee@example.com>", "Re: Data Analyst Graduate", "Hi.",
               gm_thrid="t2")
    assert (m.kind, m.job_id) == (c.MatchKind.STRONG, "ex-data"), m       # role decides inside


@needs(RULES, MATCH)
def test_mail_match_saved_and_terminal_applications_are_candidates():
    c = _c()
    saved = _a(NW, status="to_apply")
    m = _match([saved], "Northwind Traders <%s>" % GH, "Thank you for applying", "Graduate Analyst.")
    assert (m.kind, m.job_id) == (c.MatchKind.STRONG, "nw"), m
    closed = _a(CT, job_id="ct-ops", role="Operations Graduate Associate", status="rejected")
    open_ = _a(CT)
    m = _match([closed, open_], "Contoso Bank <noreply@contosobank.tal.net>",
               "Operations Graduate Associate", "An update.")
    assert (m.kind, m.job_id) == (c.MatchKind.STRONG, "ct-ops"), m       # not the open sibling


def test_mail_match_oracles_are_live():
    assert_live(MATCH, _W0, "test_mail_match")


note_waiting("test_mail_match", _W0)
