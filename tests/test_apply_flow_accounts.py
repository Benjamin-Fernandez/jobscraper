"""The flow's account and mail paths (Q-35 WP-T4 flow half, lane N WP-N4; apply_design §4.2,
§10.2, §10.5, §11; NF-02, NF-06, NF-07; review Q-35-lanes-NR F3, F4, F7).

  - F3: a `provider: workday` job stops `unsupported_ats` in planning, before Edge starts and
    before any vault or account call (the interim gate until WP-N6a; this pin flips then);
  - identity (§10.5): lower-case compare, the details name no address;
  - sign-up (§10.2): no `consents.privacy_consent` -> unanswerable_required "account terms"
    before any vault write; with it, the password is in the vault and the row `creating`
    BEFORE the sign-up click; a field error rolls both back; any other error keeps both
    (`unknown`); no password in the log;
  - F4 (Greenhouse emailed security code, auto mode): the code from the fake IMAP mailbox is
    entered once and Submit pressed once more -> submitted, `code_resubmits` 1; a second code
    request -> submitted_unconfirmed; the IMAP wait is added back to the deadline; the code
    is never logged; D-85 (failing pins until lane N applies it): the code is the only line of
    6-12 letters/digits after the sentence, "security" is never the code, a letters-only code
    is valid, zero or two candidates -> no code;
  - F7 (skip-clean until N6a): on Workday `choose_entry` runs before the account wall.
Fakes: tests/apply_flow_support.py (adapter, browser), tests/vault_support.py (keyring), a fake
`imaplib.IMAP4_SSL` serving tests/fixtures/mail/greenhouse_code.eml re-dated to now.
Verify: python tests/run_tests.py -k apply_flow_accounts
"""
from __future__ import annotations

import contextlib
import dataclasses
import email
import imaplib
import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import ROOT, WAITING, needs  # noqa: E402
from apply_flow_support import (  # noqa: E402
    EMAIL, FakeAdapter, FakeBrowserFactory, NoModel, Say, add_job, fake_world, make_world,
    page_signals, registered, sample_profile,
)
from vault_support import memory_keyring  # noqa: E402

from jobscraper import apply_flow  # noqa: E402
from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R  # noqa: E402

_W0 = len(WAITING)
A_URL = "https://exampleco.wd3.myworkdayjobs.com/en-US/External/job/Singapore/Graduate-Engineer_REQ-0001"
CODE = "K7P2M9QX"
GH_OTP = r"\b([A-Z0-9]{8})\b"
IMAP_HOST = "imap.example.test"
_REAL_SLEEP = time.sleep


def test_the_flow_module_imports():
    assert hasattr(apply_flow, "run")


def _run(w, job_ids, adapter=None, *, dry_run=True, apply_over=None, profile_file=True):
    factory, say = FakeBrowserFactory(), Say()
    over = {"dry_run_hold_s": 0, "confirm_timeout_s": 0, **(apply_over or {})}
    acfg = dataclasses.replace(w.cfg.apply, **over)
    reg = registered(adapter) if adapter is not None else contextlib.nullcontext()
    with reg, page_signals():
        res = apply_flow.run(w.cfg, w.store, list(job_ids), dry_run=dry_run, backend=NoModel(),
                             http=object(), browser_factory=factory, apply_cfg=acfg, say=say,
                             evidence_dir=w.tmp / "evidence")
    return res, factory, say


# ------------------------------------------------------------------ F3: the Workday gate

@needs("jobscraper.apply.ats.workday:NAVIGATOR")
def test_a_workday_job_stops_unsupported_before_edge_and_before_any_account_call():
    """Review F3: the only thing stopping live Workday runs before WP-N6a. Real REGISTRY."""
    from jobscraper.apply.ats import REGISTRY
    assert "workday" in REGISTRY and not hasattr(REGISTRY["workday"], "read_step"), \
        "N6a landed: replace this pin with the Workday flow oracles (T4 flow part)"
    w = make_world()
    try:
        _cid, jid = add_job(w.store, key="exampleco", name="Example Employer", provider="workday",
                            slug="exampleco", external_id="REQ-0001", url=A_URL)
        with memory_keyring() as mem:
            for dry in (True, False):
                res, factory, say = _run(w, [jid], dry_run=dry)
                r = res[0]
                assert r.state is S.FAILED and r.reason is R.UNSUPPORTED_ATS, (dry, r.state, r.reason)
                assert "form filling arrives" in r.reason_detail
                assert factory.started == 0, "Edge never starts"
                row = w.store.attempt(r.attempt_id)
                assert row["step"] == "planning" and row["submit_clicked_at"] is None
                assert row["ats"] == "workday"
                assert w.store.answers(r.attempt_id) == []
            assert mem.calls == [], "no vault read or write"
            assert w.store.accounts() == [], "no account row"
    finally:
        w.close()


# ------------------------------------------------------------------ identity (§10.5)

@needs("jobscraper.apply.accounts:choose_identity")
def test_identity_compares_addresses_in_lower_case_and_details_name_no_address():
    from jobscraper.apply import accounts as A
    from jobscraper.apply.contracts import ApplyFailure
    P, B = "Alex.Testcase@Example.com", "alex.backup@example.net"
    i = A.choose_identity(P, B, {"alex.testcase@example.com": "verified"}, lambda e: e == P)
    assert (i.email, i.action) == (P, A.SIGN_IN)
    i = A.choose_identity(P, B, {"ALEX.TESTCASE@EXAMPLE.COM": "exists_no_password"}, lambda e: False)
    assert (i.email, i.action) == (B, A.SIGN_UP)
    i = A.choose_identity(P, P.lower(), {}, lambda e: False)
    assert (i.email, i.action) == (P, A.SIGN_UP), "a backup equal to the main email is no backup"
    for detail in (A.NO_PASSWORD_DETAIL, A.BOTH_NO_PASSWORD_DETAIL, A.SIGNIN_FAILED_DETAIL):
        assert "@" not in detail
    try:
        A.choose_identity(P, B, {P.upper(): "exists_no_password", B.upper(): "exists_no_password"},
                          lambda e: False)
    except ApplyFailure as e:
        assert e.reason is R.LOGIN_FAILED and e.detail == A.BOTH_NO_PASSWORD_DETAIL
    else:
        raise AssertionError("both emails blocked must fail login_failed")


# ------------------------------------------------------------------ sign-up (§10.2)

class _AccountAdapter(FakeAdapter):
    """A fakeats adapter behind an account wall: sign-up first, then the form."""
    needs_account = True

    def __init__(self, store, *, sign_up=None):
        super().__init__()
        self.store = store
        self.walls = ["sign_up"]
        self.sign_up_fn = sign_up or (lambda: "signed_in")
        self.seen: list[dict] = []

    def account_wall(self, page):
        return self.walls.pop(0) if self.walls else None

    def sign_up(self, page, ctx, password):
        from jobscraper import vault
        self.calls.append("sign_up")
        service = vault.service_for(self.name, ctx.tenant.host)
        got = vault.get(service, ctx.email)
        row = self.store.account(self.name, ctx.tenant.host, ctx.email)
        self.seen.append({"vault_has_it": got is not None and got.reveal() == password.reveal(),
                          "row": row and row["status"], "pw": password.reveal()})
        return self.sign_up_fn()

    def sign_in(self, page, ctx, password):
        self.calls.append("sign_in")


SERVICE = "jobscraper:fakeats:fake.example.com"


def _account_world(consent=True):
    p = sample_profile()
    p["consents"]["privacy_consent"] = consent
    w = make_world(profile=p)
    cid, jid = add_job(w.store, key="fakeco", name="Fake Co", provider="fakeats", slug="fakeco",
                       external_id="1", url="https://fake.example.com/jobs/1")
    return w, jid


@needs("jobscraper.apply.accounts:choose_identity")
def test_sign_up_needs_the_privacy_consent_before_any_vault_write():
    w, jid = _account_world(consent=False)
    try:
        with memory_keyring() as mem:
            ad = _AccountAdapter(w.store)
            r = _run(w, [jid], ad)[0][0]
            # Q-71 G3: a consent that is not True is refused up front (the profile guard), before any
            # browser or vault work; the sign-up-time "account terms" check is the second line.
            assert r.state is S.FAILED and r.reason is R.PROFILE_INCOMPLETE, (r.state, r.reason)
            assert "consents.privacy_consent" in r.reason_detail
            assert "sign_up" not in ad.calls
            assert not [c for c in mem.calls if c[0] == "set"] and w.store.accounts() == []
    finally:
        w.close()


@needs("jobscraper.apply.accounts:choose_identity")
def test_the_password_is_stored_and_the_row_creating_before_the_sign_up_click():
    w, jid = _account_world()
    try:
        with memory_keyring() as mem:
            ad = _AccountAdapter(w.store)
            res, factory, say = _run(w, [jid], ad)
            r = res[0]
            assert r.state is S.READY_TO_SUBMIT, (r.state, r.reason, r.reason_detail)
            assert ad.calls.count("sign_up") == 1
            assert ad.seen[0]["vault_has_it"] and ad.seen[0]["row"] == "creating"
            assert w.store.account("fakeats", "fake.example.com", EMAIL)["status"] == "created"
            assert (SERVICE, EMAIL) in mem.d
            assert ad.seen[0]["pw"] not in say.text, "never a password in the log"
    finally:
        w.close()


@needs("jobscraper.apply.accounts:choose_identity")
def test_a_sign_up_field_error_rolls_back_and_any_other_error_keeps_both_as_unknown():
    from jobscraper.apply.contracts import ApplyFailure

    def field_error():
        raise ApplyFailure(R.VALIDATION_ERROR, "account form: Password")

    def crash():
        raise RuntimeError("the page went away")
    for fn, keep in ((field_error, False), (crash, True)):
        w, jid = _account_world()
        try:
            with memory_keyring() as mem:
                ad = _AccountAdapter(w.store, sign_up=fn)
                r = _run(w, [jid], ad)[0][0]
                assert r.state is S.FAILED, (fn.__name__, r.state)
                row = w.store.account("fakeats", "fake.example.com", EMAIL)
                if keep:
                    assert row is not None and row["status"] == "unknown", row
                    assert (SERVICE, EMAIL) in mem.d, "the next attempt signs in with it"
                else:
                    assert row is None and (SERVICE, EMAIL) not in mem.d, "refused: nothing kept"
        finally:
            w.close()


# ------------------------------------------------------------------ F4: Greenhouse security code

def _code_mail(when: datetime) -> bytes:
    raw = (ROOT / "tests" / "fixtures" / "mail" / "greenhouse_code.eml").read_bytes()
    msg = email.message_from_bytes(raw)
    del msg["Date"]
    msg["Date"] = format_datetime(when)
    return msg.as_bytes()


@contextlib.contextmanager
def _fake_imap(messages: list[bytes], *, login_delay_s: float = 0.0):
    """imaplib.IMAP4_SSL -> a read-only fake serving `messages` in INBOX."""
    from jobscraper.apply import mail
    log: list[tuple] = []

    class IMAP4_SSL:                                         # noqa: N801
        def __init__(self, host="", port=993, *a, **kw):
            log.append(("connect", host))

        def login(self, user, password):
            log.append(("login", user))
            if login_delay_s:
                _REAL_SLEEP(login_delay_s)
            return "OK", [b"ok"]

        def select(self, mailbox="INBOX", readonly=False):
            box = messages if mailbox == "INBOX" else []
            return ("OK", [str(len(box)).encode()]) if mailbox == "INBOX" else ("NO", [b"none"])

        def search(self, charset, *criteria):
            return "OK", [b" ".join(str(i + 1).encode() for i in range(len(messages)))]

        def fetch(self, num, spec):
            raw = messages[int(num) - 1]
            when = parsedate_to_datetime(email.message_from_bytes(raw)["Date"])
            internal = when.astimezone(timezone.utc).strftime("%d-%b-%Y %H:%M:%S +0000")
            return "OK", [(f'{int(num)} (INTERNALDATE "{internal}" BODY[] {{{len(raw)}}}'.encode(), raw), b")"]

        def uid(self, command, *args):
            return self.search(None, *args) if command.upper() == "SEARCH" else self.fetch(args[0], args[1])

        def noop(self):
            return "OK", [b""]

        def close(self):
            return "OK", [b""]

        def logout(self):
            return "BYE", [b""]

        def shutdown(self):
            pass

    saved = [(h, getattr(h, "IMAP4_SSL")) for h in {imaplib, getattr(mail, "imaplib", imaplib)}]
    for h, _ in saved:
        h.IMAP4_SSL = IMAP4_SSL
    try:
        yield log
    finally:
        for h, old in saved:
            h.IMAP4_SSL = old


class _CodeAdapter(FakeAdapter):
    """A schema adapter whose site asks for an emailed code after Submit (AD §4.2)."""
    mail_domains = ("greenhouse.io", "greenhouse-mail.io")
    otp_pattern = GH_OTP

    def __init__(self, afters):
        super().__init__()
        self.afters = list(afters)
        self.codes: list[str] = []
        self.deadlines: list[float] = []
        self.after = lambda page, ctx: self.afters.pop(0) if self.afters else None
        self.on_submit = lambda ctx: self.deadlines.append(ctx.deadline)

    def enter_code(self, page, ctx, code):
        self.calls.append("enter_code")
        self.codes.append(code)
        self.deadlines.append(ctx.deadline)


@contextlib.contextmanager
def _code_world(afters, *, login_delay_s=0.0):
    from jobscraper import vault
    from jobscraper.apply.contracts import Secret
    w, ad, cid, jid = fake_world()
    with memory_keyring() as mem:
        vault.put(vault.imap_service(IMAP_HOST), EMAIL, Secret("synthetic-app-password"))
        w.store.set_setting("apply.mail.host", IMAP_HOST)
        w.store.set_setting("apply.mail.username", EMAIL)
        w.store.set_setting("apply.mail.poll_s", "1")
        w.store.set_setting("apply.mail.wait_s", "5")
        w.store.commit()
        msg = _code_mail(datetime.now(timezone.utc) + timedelta(minutes=1))
        with _fake_imap([msg], login_delay_s=login_delay_s) as log:
            try:
                yield w, _CodeAdapter(afters), jid, log
            finally:
                w.close()


@needs("jobscraper.apply_flow:_Run.code_after_submit")
def test_an_emailed_code_is_entered_once_and_the_application_resubmitted_once():
    with _code_world(["code_required", "confirmed:url"], login_delay_s=0.6) as (w, ad, jid, log):
        res, factory, say = _run(w, [jid], ad, dry_run=False)
        r = res[0]
        assert r.state is S.SUBMITTED, (r.state, r.reason_detail)
        assert ad.codes == [CODE] and ad.calls.count("submit") == 2
        row = w.store.attempt(r.attempt_id)
        assert row["code_resubmits"] == 1 and row["submit_clicked_at"]
        assert ("login", EMAIL) in log
        assert ad.deadlines[1] - ad.deadlines[0] >= 0.5, "the IMAP wait is added back to the deadline"
        assert CODE not in say.text, "the code is never logged"


@needs("jobscraper.apply_flow:_Run.code_after_submit")
def test_a_second_code_request_ends_unconfirmed_after_one_resubmit():
    with _code_world(["code_required", "code_required"]) as (w, ad, jid, log):
        r = _run(w, [jid], ad, dry_run=False)[0][0]
        assert r.state is S.SUBMITTED_UNCONFIRMED, (r.state, r.reason_detail)
        assert "a second security code was asked for" in r.reason_detail
        assert ad.codes == [CODE] and ad.calls.count("submit") == 2
        row = w.store.attempt(r.attempt_id)
        assert row["code_resubmits"] == 1 and row["reason_code"] is None


@needs("jobscraper.apply_flow:_Run.code_after_submit")
def test_a_dry_run_never_reaches_the_code_path():
    with _code_world(["code_required"]) as (w, ad, jid, log):
        r = _run(w, [jid], ad, dry_run=True)[0][0]
        assert r.state is S.READY_TO_SUBMIT and "submit" not in ad.calls and ad.codes == []
        assert log == [], "no mailbox opened in a dry run"


def _gh_code(body: str):
    """How the flow reads a Greenhouse code: `mail.find_code(text, GreenhouseAdapter.otp_pattern)`
    (the watcher's call). If lane N moves D-85 into its own function, change only this helper."""
    from jobscraper.apply.ats.greenhouse import GreenhouseAdapter
    from jobscraper.apply.mail import find_code
    return find_code(body, GreenhouseAdapter.otp_pattern)


def _gh_body(*code_lines: str) -> str:
    msg = email.message_from_bytes((ROOT / "tests" / "fixtures" / "mail" / "greenhouse_code.eml").read_bytes())
    body = msg.get_payload()
    return body.replace(CODE, "\n\n".join(code_lines)) if code_lines else body.replace(CODE, "")


@needs("jobscraper.apply.mail:find_code")
def test_the_greenhouse_code_pattern_reads_the_code_not_a_word():
    """Failing pin until D-85 lands (MEDIUM, live with the int/Q-35-NR merge): the Greenhouse
    `otp_pattern` `\\b([A-Za-z0-9]{8})\\b` returns the word "security" from the line "...into the
    security code field..."; the flow would type that and resubmit."""
    assert _gh_code(_gh_body()) != "security"
    assert _gh_code(_gh_body(CODE)) == CODE


@needs("jobscraper.apply.mail:find_code")
def test_d85_the_code_is_the_only_short_alphanumeric_line_after_the_sentence():
    """D-85: the code is the only line (trimmed) of 6-12 letters/digits after the "security
    code" sentence; a code without a digit is valid (~24% of 8-character codes have none);
    zero or several candidate lines -> no code (fail closed). Failing pin until lane N's D-85."""
    assert _gh_code(_gh_body("KPQMXRTZ")) == "KPQMXRTZ", "letters only is a valid code"
    assert _gh_code(_gh_body("  A1B2C3  ")) == "A1B2C3", "6 characters, trimmed"
    assert _gh_code(_gh_body("A1B2C3D4E5F6")) == "A1B2C3D4E5F6", "12 characters"
    assert _gh_code(_gh_body(CODE, "Q2W3E4R5")) is None, "two candidates: fail closed"
    assert _gh_code(_gh_body()) is None, "no candidate: fail closed"


# ------------------------------------------------------------------ F7 (N6a)

@needs("jobscraper.apply.pagefill:fill_page", "jobscraper.apply.ats.workday:NAVIGATOR.read_step")
def test_on_workday_choose_entry_runs_before_the_account_wall():
    """Review F7 (N6a "Done when"): open -> choose_entry -> account wall; after an email-check
    reopen, choose_entry again. Waits for WP-N6a; the flow oracle is written against it then."""
    raise AssertionError("N6a landed: write the F7 flow oracle (choose_entry before account())")


if WAITING[_W0:]:
    print(f"[test_apply_flow_accounts] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))

def test_the_sign_up_step_itself_refuses_without_the_privacy_consent():
    """Q-71 G3 refuses such a profile earlier (PROFILE_INCOMPLETE), so the flow never reaches this check;
    it stays as the second line of defence, and this calls it directly: no vault, no account row, no click."""
    import types
    from jobscraper.apply.contracts import ApplyFailure
    for consent in (False, None):
        p = sample_profile()
        p["consents"]["privacy_consent"] = consent
        stub = types.SimpleNamespace(profile=p)           # sign_up reads nothing else before the guard
        try:
            apply_flow._Run.sign_up(stub, None, None, None, None, None, "", "", "")
        except ApplyFailure as e:
            assert e.reason is R.UNANSWERABLE_REQUIRED and "account terms" in str(e.detail if hasattr(e, "detail") else e)
        else:
            raise AssertionError("sign_up went ahead without the privacy consent")
