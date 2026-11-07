"""Defect pins for the KA-3 review of Q-60 (docs/reviews/Q-60-stage-imap-ui.md) and its fix
decisions D-154 (instructions/02_status.md). Verify: `python tests/run_tests.py -k mail_review_pins`.

These fail until lanes S and I land the fixes; each test names its finding. The stage pins run on
tests/fixtures/mail/rules_min.yaml and, when present, config/mail_rules.yaml. Headers are built with
the reference parser in tests/mail_support.py (unit_header); transport pins use imapread itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_support import (  # noqa: E402
    MATCH, MODEL, REAL_RULES, RULES, RULES_MIN, TRANSITION, WAITING, app_candidate, assert_live,
    build_policy, decide, golden_own, load, make_eml, needs, note_waiting, unit_header,
)

_W0 = len(WAITING)
IMAPREAD = "jobscraper.imapread"
REJ = "Thank you for your interest. Unfortunately, we will not be moving forward with your application."
WINDOW = "2026-08-01T00:00:00"


def _c():
    from jobscraper.mailstatus import contracts
    return contracts


def _paths():
    return [RULES_MIN] + ([REAL_RULES] if REAL_RULES.exists() else [])


def _app(company, *, job_id="j1", status="applied", domains=(), tenants=(), role="Graduate Analyst"):
    return app_candidate(dict(job_id=job_id, status=status, company_names=(company,), role=role,
                              employer_domains=tuple(domains), tenants=tuple(tenants),
                              owner_changed_at=None, last_event_at=None))


def _run(rules_obj, frm, subject, body, apps, **kw):
    """(gate, match, verdict, change) through the stage as the flow runs it (MS 5.4)."""
    from jobscraper.mailstatus import match as M, rules as R
    h, b = unit_header(frm, subject, body, **kw)
    regs = frozenset(r for a in apps for r in a.employer_domains)
    g = R.header_gate(h, rules_obj, own=golden_own(), window_start=WINDOW, threads=frozenset(),
                      employer_regs=regs) or R.content_gate(h, b, rules_obj, in_matched_thread=False)
    if g is not None:
        return g, None, None, None
    m = M.match(h, b, tuple(apps), rules_obj)
    v = R.classify(h, b, rules_obj)
    c = _c()
    if m.kind == c.MatchKind.NONE:
        return None, m, v, None
    by = {a.job_id: a for a in apps}
    if m.kind == c.MatchKind.AMBIGUOUS:
        cands = [by[j] for j in m.candidates]
        return None, m, v, decide(cands[0], v, m, h, build_policy(), candidates=cands)
    return None, m, v, decide(by[m.job_id], v, m, h, build_policy())


def _rules(path):
    """The rules file, with the neutral common-word names of these pins (Claim, Ocean) added
    to its `common_word_names` (rules_min lists them; the shipped file lists real ones)."""
    import dataclasses
    r = load(path)
    return dataclasses.replace(r, common_word_names=r.common_word_names | {"claim", "ocean"})


def _not_auto(res, why):
    c = _c()
    _g, m, _v, ch = res
    assert ch is None or ch.kind != c.ChangeKind.AUTO, (why, m, ch)


# ------------------------------------------------------------------ F1 (BLOCKER), D-154 a

@needs(RULES, MATCH, TRANSITION)
def test_review_f1_another_tenant_on_the_same_platform_never_auto_moves():
    """F1 repro D: careers URL acmebank.tal.net; employer_domain() gives 'tal.net'. A
    rejection from otherbank.tal.net (Gmail-authenticated for tal.net) must not reach the
    application; the stage fails closed whatever employer_domains the store sends."""
    from jobscraper.mailstatus import match as M
    c = _c()
    for path in _paths():
        rules_obj = load(path)
        tenants = M.tenants_from_hosts(("acmebank.tal.net",), rules_obj)
        bank = _app("Acme Bank", domains=("tal.net",), tenants=tenants)
        res = _run(rules_obj, "Graduate Recruitment <noreply@otherbank.tal.net>", "Your application",
                   REJ, [bank])
        _not_auto(res, f"{path.name}: other tenant")
        m = res[1]
        assert m is None or c.Signal.EMPLOYER_DOMAIN not in m.signals, (path.name, m)
        own = _run(rules_obj, "Graduate Recruitment <noreply@acmebank.tal.net>", "Your application",
                   REJ, [bank])
        assert own[1].kind == c.MatchKind.STRONG and own[1].signals == (c.Signal.TENANT,), \
            (path.name, "the tenant signal still carries the bank's own mail", own[1])


@needs(RULES, MATCH)
def test_review_f1_a_platform_domain_is_never_an_employer_signal():
    c = _c()
    for path in _paths():
        rules_obj = load(path)
        for dom, frm in (("greenhouse.io", "Other Co <no-reply@greenhouse.io>"),
                         ("greenhouse-mail.io", "Other Co <no-reply@us.greenhouse-mail.io>"),
                         ("myworkday.com", "Careers <otherco@myworkday.com>"),
                         ("myworkdayjobs.com", "Careers <jobs@otherco.wd3.myworkdayjobs.com>"),
                         ("tal.net", "Recruitment <noreply@otherbank.tal.net>")):
            app = _app("Acme Bank", domains=(dom,))
            res = _run(rules_obj, frm, "Your application", REJ, [app])
            m = res[1]
            assert m is None or c.Signal.EMPLOYER_DOMAIN not in m.signals, (path.name, dom, m)
            assert m is None or m.kind == c.MatchKind.NONE, (path.name, dom, m)


# ------------------------------------------------------------------ F2 (MAJOR), D-154 b

@needs(RULES, MATCH, TRANSITION)
def test_review_f2_a_reply_to_from_a_free_mail_sender_gives_no_strong_match():
    """F2 repro A: From random.person@gmail.com (dmarc=pass for gmail.com), Reply-To
    hr@acme.example, a rejection. Reply-To counts only when From is a platform domain and
    Gmail authentication passed (D-154 b)."""
    c = _c()
    acme = _app("Acme Example", domains=("acme.example",))
    for path in _paths():
        rules_obj = _rules(path)
        res = _run(rules_obj, "Recruiter <random.person@gmail.com>", "Your application", REJ, [acme],
                   headers={"Reply-To": "hr@acme.example"})
        _not_auto(res, f"{path.name}: free-mail From with an employer Reply-To")
        m = res[1]
        assert m is None or m.kind != c.MatchKind.STRONG, (path.name, m)
        assert m is None or c.Signal.EMPLOYER_DOMAIN not in m.signals, (path.name, m)
        # A platform From without Gmail's pass: Reply-To is ignored as well.
        res = _run(rules_obj, "Hiring <no-reply@us.greenhouse-mail.io>", "Your application", REJ, [acme],
                   headers={"Reply-To": "hr@acme.example"}, auth="none")
        m = res[1]
        assert m is None or c.Signal.EMPLOYER_DOMAIN not in m.signals, (path.name, "unauthenticated", m)
        # The case D-154 b keeps: an authenticated platform From replying to the employer.
        res = _run(rules_obj, "Hiring <no-reply@us.greenhouse-mail.io>", "Your application", REJ, [acme],
                   headers={"Reply-To": "hr@acme.example"})
        assert c.Signal.EMPLOYER_DOMAIN in res[1].signals, (path.name, "platform + pass keeps it", res[1])


# ------------------------------------------------------------------ F3 (MAJOR), D-154 c

@needs(RULES, MATCH, TRANSITION)
def test_review_f3_common_word_names_on_shared_platforms_never_auto_move():
    c = _c()
    claim = _app("Claim", domains=("claim.example",), role="Software Engineer")
    ocean = _app("Ocean", domains=("ocean.example",))
    acme = _app("Acme", domains=("acme.example",))
    for path in _paths():
        rules_obj = _rules(path)
        res = _run(rules_obj, "HackerRank <support@hackerrankforwork.com>",
                   "Claim your spot: complete your coding assessment",
                   "You have been invited to complete an online assessment for Other Co.", [claim])
        _not_auto(res, f"{path.name}: Claim subject")
        res = _run(rules_obj, "Other Co <no-reply@us.greenhouse-mail.io>",
                   "Interview for the Ocean of opportunities programme",
                   "We would like to invite you to an interview for the role.", [ocean])
        _not_auto(res, f"{path.name}: Ocean subject")
        res = _run(rules_obj, "Other Co <no-reply@us.greenhouse-mail.io>",
                   "Re: Your application - Acme Analytics partner role", REJ, [acme])
        _not_auto(res, f"{path.name}: Acme prefix of Acme Analytics")


@needs(RULES, MATCH)
def test_review_f3_a_common_word_or_short_name_alone_is_at_most_weak():
    c = _c()
    claim = _app("Claim", domains=("claim.example",))
    zeta = _app("Zeta Pte Ltd", domains=("zeta.example",))
    for path in _paths():
        rules_obj = _rules(path)
        for app, frm, subject in ((claim, "Claim Careers <no-reply@us.greenhouse-mail.io>", "Your application"),
                                  (claim, "Hiring <no-reply@us.greenhouse-mail.io>", "Your Claim application"),
                                  (zeta, "Zeta Careers <no-reply@us.greenhouse-mail.io>", "Your application"),
                                  (zeta, "Hiring <no-reply@us.greenhouse-mail.io>", "Your Zeta application")):
            m = _run(rules_obj, frm, subject, "Thank you for applying.", [app])[1]
            assert m is not None and m.kind in (c.MatchKind.WEAK, c.MatchKind.NONE), \
                (path.name, frm, subject, m)
        # It still confirms a strong signal from the employer's own domain.
        m = _run(rules_obj, "Claim Careers <careers@claim.example>", "Your Claim application",
                 "Thank you for applying.", [claim])[1]
        assert m.kind == c.MatchKind.STRONG and c.Signal.EMPLOYER_DOMAIN in m.signals, (path.name, m)


# ------------------------------------------------------------------ F5 (MINOR), D-154 f

@needs(IMAPREAD)
def test_review_f5_every_url_form_becomes_link():
    from jobscraper import imapread as I
    frm = "Northwind <talent@northwind.example>"
    cases = [
        # (body, words that must be gone, text that must survive)
        ("Reset at careers.example.com/reset?token=abc and example.org/x today.",
         ("careers.example.com", "token=abc", "example.org/x"), ("Reset at", "today")),
        ("Get it from ftp://f.example/a now.", ("ftp:", "f.example"), ("Get it from", "now")),
        ("Assets at //cdn.example.com/a here.", ("cdn.example.com",), ("Assets at", "here")),
        ("Open https://exa\nmple.com/path/secret please.", ("mple.com", "secret"), ("Open", "please")),
        ("link https://ex.example/a(b)token123 end", ("token123", "ex.example"), ("link", "end")),
        ("(see https://ex.example/a) and the rest.", ("ex.example",), ("(see", ") and the rest.")),
        ("Portal (https://portal.example/x?id=1) closes Friday.", ("portal.example", "id=1"),
         ("Portal (", ") closes Friday.")),
    ]
    for body, gone, kept in cases:
        text = I.parse_body(make_eml(frm, "s", body)).text
        flat = " ".join(text.split())
        for g in gone:
            assert g not in flat, (body, g, flat)
        for k in kept:
            assert k in flat, (body, k, flat)
        assert "[link]" in flat, (body, flat)
    # Ordinary prose with a dot is not a link.
    for prose in ("We met on 3.11 and spoke about the role.", "The salary is S$5.5k per month."):
        flat = " ".join(I.parse_body(make_eml(frm, "s", prose)).text.split())
        assert flat == prose, (prose, flat)


# ------------------------------------------------------------------ F6 (MINOR), D-154 d

@needs(MODEL)
def test_review_f6_a_model_quote_needs_15_characters_and_3_words():
    from jobscraper.mailstatus import model as MO
    c = _c()
    h, body = unit_header("Northwind <talent@northwind.example>", "Update",
                          "Please see next steps. Please review attached documents. "
                          "Unfortunately unsuccessful applicants hear later.")
    for quote, ok in (("s", False), ("next steps", False), ("see next steps", False),
                      ("Unfortunately unsuccessful", False), ("Please review attached", True),
                      ("Please see next steps.", True)):
        v = MO.parse('{"category": "offer", "quote": "%s"}' % quote, h, body, "local-model")
        if ok:
            assert v.category == c.Category.OFFER, (quote, v)
        else:
            assert v.category == c.Category.UNKNOWN and v.rule_id.startswith("model:"), (quote, v)
            assert v.quote == "" and v.status_words, (quote, v)


# ------------------------------------------------------------------ D-154 g

@needs(TRANSITION)
def test_review_d154g_require_auth_false_as_text_is_false():
    from mail_support import golden_policy_raw
    for raw, want in (("false", False), ("False", False), ("no", False), ("0", False), (False, False),
                      ("true", True), ("yes", True), (True, True)):
        got = build_policy(raw=dict(golden_policy_raw(), require_auth=raw)).require_auth
        assert got is want, (raw, got)


@needs("jobscraper.config:MailStatusConfig")
def test_review_d154g_mail_status_config_booleans_read_text_false():
    from jobscraper.config import MailStatusConfig
    cfg = MailStatusConfig.from_raw({"enabled": "false", "model": "false", "require_auth": "false"})
    assert (cfg.enabled, cfg.model, cfg.require_auth) == (False, False, False), cfg
    cfg = MailStatusConfig.from_raw({"enabled": "true", "model": "yes", "require_auth": True})
    assert (cfg.enabled, cfg.model, cfg.require_auth) == (True, True, True), cfg


def test_review_pins_are_live():
    assert_live(RULES, _W0, "test_mail_review_pins")


note_waiting("test_mail_review_pins", _W0)
