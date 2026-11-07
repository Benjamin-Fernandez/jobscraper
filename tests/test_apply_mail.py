"""WP-V3 oracles: the IMAP watcher (apply_design §11.1, §11.3, §11.5; F-36, NF-02).

No network. A fake `imaplib.IMAP4_SSL` serves the synthetic messages in tests/fixtures/mail/ and
records every command, so the tests can prove the watcher only EXAMINEs (select readonly) and
FETCHes with BODY.PEEK, never STORE/COPY/EXPUNGE/APPEND.

ASSUMED API (one place to change: the helpers in the "assumptions" block):
  apply/mail.py:  MailWatcher(host, port, username, password: Secret, timeout_s=20)
                  .wait_for(*, since_utc, sender_domains, link_domains, otp_pattern, want,
                            wait_s, poll_s, to_addr=None) -> contracts.Verification (kind, value, ...)
                  test_connection(host, port, username, password) -> "ok: N messages in INBOX"
                  employer_domain(careers_url) -> str ('' or None for an ATS host)
                  mailbox_for(address, profile, settings) -> (host, port, username) | None
  The module reaches IMAP through `imaplib.IMAP4_SSL` (we patch the attribute on `imaplib`, and on
  the mail module's own `imaplib` / `IMAP4_SSL` name when it has one).
  `settings` is ASSUMED to be a nested mapping {"apply": {"mail": {host, port, username},
  "mail_backup": {host, port, username}}} (design §11.5 keys `apply.mail.*`).
  `since_utc` is a timezone-aware UTC datetime.
"""
from __future__ import annotations

import email
import imaplib
import re
import sys
from datetime import datetime, timezone
from email import policy
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import ROOT, WAITING, needs, profile  # noqa: E402

from jobscraper.apply.contracts import ApplyFailure, ReasonCode, Secret  # noqa: E402

MAIL = ROOT / "tests" / "fixtures" / "mail"
SINCE = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)      # the attempt's started_at
PRIMARY, BACKUP = "alex.testcase@example.com", "alex.backup@example.net"
WD_SENDERS = ("myworkday.com", "workday.com")
WD_LINKS = ("acme.wd3.myworkdayjobs.com", "myworkdayjobs.com", "myworkday.com")
GH_OTP = r"\b([A-Z0-9]{8})\b"


def _raw(name: str) -> bytes:
    return (MAIL / f"{name}.eml").read_bytes()


# ------------------------------------------------------------------ the fake server

class FakeServer:
    """Class-level state so a test can read what any connection did."""

    def __init__(self, mailboxes: dict[str, list[bytes]]):
        self.mailboxes = mailboxes
        self.commands: list[tuple] = []
        server = self

        class IMAP4_SSL:                                    # noqa: N801 (mirrors imaplib)
            def __init__(self, host="", port=993, *a, **kw):
                server.commands.append(("connect", host, port))
                self._box: list[bytes] = []

            def login(self, user, password):
                server.commands.append(("login", user))     # never the password
                return "OK", [b"logged in"]

            def select(self, mailbox="INBOX", readonly=False):
                server.commands.append(("select", mailbox, bool(readonly)))
                if mailbox not in server.mailboxes:
                    return "NO", [b"[NONEXISTENT] Unknown Mailbox"]
                self._box = server.mailboxes[mailbox]
                return "OK", [str(len(self._box)).encode()]

            def search(self, charset, *criteria):
                server.commands.append(("search", *criteria))
                return "OK", [b" ".join(str(i + 1).encode() for i in range(len(self._box)))]

            def fetch(self, num, spec):
                spec = spec if isinstance(spec, str) else spec.decode()
                server.commands.append(("fetch", spec))
                raw = self._box[int(num) - 1]
                when = parsedate_to_datetime(email.message_from_bytes(raw)["Date"])
                internal = when.astimezone(timezone.utc).strftime("%d-%b-%Y %H:%M:%S +0000")
                head = f'{int(num)} (INTERNALDATE "{internal}" BODY[] {{{len(raw)}}}'.encode()
                return "OK", [(head, raw), b")"]

            def uid(self, command, *args):                  # tolerated: same data, recorded as uid
                server.commands.append(("uid", command, *args))
                if command.upper() == "SEARCH":
                    return self.search(None, *args)
                return self.fetch(args[0], args[1])

            def noop(self):
                return "OK", [b""]

            def close(self):
                return "OK", [b""]

            def logout(self):
                server.commands.append(("logout",))
                return "BYE", [b""]

            def shutdown(self):
                pass

            def __getattr__(self, name):                    # store/copy/move/expunge/append/...
                def forbidden(*a, **kw):
                    server.commands.append(("FORBIDDEN", name))
                    raise AssertionError(f"mail must be read-only: IMAP {name} called")
                return forbidden

        self.cls = IMAP4_SSL

    def verbs(self) -> set[str]:
        return {c[0] for c in self.commands}


class _Patched:
    def __init__(self, server: FakeServer):
        self.server = server

    def __enter__(self):
        from jobscraper.apply import mail
        self.mail, self.saved = mail, []
        for holder, name in ((imaplib, "IMAP4_SSL"), (getattr(mail, "imaplib", None), "IMAP4_SSL"),
                             (mail, "IMAP4_SSL")):
            if holder is not None and hasattr(holder, name):
                self.saved.append((holder, name, getattr(holder, name)))
                setattr(holder, name, self.server.cls)
        self.sleep = getattr(getattr(mail, "time", None), "sleep", None)
        if self.sleep:
            mail.time.sleep = lambda *_a, **_k: None        # never really wait between polls
        return self.server

    def __exit__(self, *exc):
        for holder, name, old in self.saved:
            setattr(holder, name, old)
        if self.sleep:
            self.mail.time.sleep = self.sleep


# ------------------------------------------------------------------ assumptions block

def _watcher():
    from jobscraper.apply.mail import MailWatcher
    return MailWatcher("imap.example.test", 993, PRIMARY, Secret("synthetic-app-password"))


def _wait(w, *, to_addr=None, want="link", otp=None, senders=WD_SENDERS, links=WD_LINKS, wait_s=2):
    return w.wait_for(since_utc=SINCE, sender_domains=senders, link_domains=links, otp_pattern=otp,
                      want=want, wait_s=wait_s, poll_s=0, to_addr=to_addr)


def _settings(main=True, backup=True) -> dict:
    s: dict = {"apply": {}}
    if main:
        s["apply"]["mail"] = {"host": "imap.gmail.com", "port": 993, "username": PRIMARY}
    if backup:
        s["apply"]["mail_backup"] = {"host": "imap.example.net", "port": 993, "username": BACKUP}
    return s


def _inbox(*names, spam=()):
    boxes = {"INBOX": [_raw(n) for n in names]}
    if spam:
        boxes["[Gmail]/Spam"] = [_raw(n) for n in spam]
    return FakeServer(boxes)


# ================================================================== fixtures (run now)

def test_mail_fixtures_are_synthetic_and_parse():
    files = sorted(MAIL.glob("*.eml"))
    assert len(files) >= 4, "WP-F4 asks for at least four messages"
    names = {f.stem for f in files}
    assert {"workday_verify_primary", "workday_verify_backup", "greenhouse_code",
            "phishing_foreign_link"} <= names
    for f in files:
        raw = f.read_bytes().decode("utf-8")
        msg = email.message_from_string(raw, policy=policy.default)
        assert msg["From"] and msg["To"] and msg["Date"], f.name
        addrs = set(re.findall(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)+", raw))
        for a in addrs:
            dom = a.split("@")[1]
            assert dom.endswith(("example.com", "example.net", "synthetic.test", "myworkday.com",
                                 "greenhouse-mail.io", "phish.example")), (f.name, a)
        assert "benjamin" not in raw.lower() and "fernandez" not in raw.lower(), f.name


def test_mail_fixtures_cover_both_addresses_and_the_traps():
    p, b = _raw("workday_verify_primary").decode(), _raw("workday_verify_backup").decode()
    assert PRIMARY in p and BACKUP not in p
    assert BACKUP in b and PRIMARY not in b
    assert "evil.example" in _raw("phishing_foreign_link").decode()
    assert "myworkday.com.phish.example" in _raw("phishing_lookalike_sender").decode()


def test_the_fake_server_refuses_writes():
    srv = _inbox("workday_verify_primary")
    c = srv.cls("h", 993)
    try:
        c.store("1", "+FLAGS", "\\Seen")
    except AssertionError:
        pass
    else:
        raise AssertionError("the fake must refuse STORE")
    assert ("FORBIDDEN", "store") in srv.commands


# ================================================================== WP-V3 oracles (skip until mail.py)

@needs("jobscraper.apply.mail")
def test_mail_reads_only_with_examine_and_body_peek():
    with _Patched(_inbox("workday_verify_primary", spam=("greenhouse_code",))) as srv:
        _wait(_watcher())
    assert "FORBIDDEN" not in srv.verbs(), srv.commands
    selects = [c for c in srv.commands if c[0] == "select"]
    assert selects and all(c[2] is True for c in selects), "every select is readonly (EXAMINE)"
    fetches = [c[1] for c in srv.commands if c[0] == "fetch"]
    assert fetches and all("BODY.PEEK[" in f and "BODY[]" not in f.replace("BODY.PEEK[]", "")
                           for f in fetches), fetches
    assert ("logout",) in srv.commands, "the connection is closed"
    assert any(c[0] == "search" and "SINCE" in c for c in srv.commands)


@needs("jobscraper.apply.mail")
def test_mail_finds_the_workday_link_for_the_tenant():
    with _Patched(_inbox("workday_verify_primary")):
        v = _wait(_watcher(), to_addr=PRIMARY)
    assert v.kind == "link" and v.value.endswith("/activate/abc123primary")
    assert v.sender_domain == "myworkday.com"


@needs("jobscraper.apply.mail")
def test_to_addr_keeps_only_the_message_for_that_address():
    both = ("workday_verify_primary", "workday_verify_backup")      # one inbox receives both
    with _Patched(_inbox(*both)):
        assert _wait(_watcher(), to_addr=BACKUP).value.endswith("/activate/def456backup")
    with _Patched(_inbox(*both)):
        assert _wait(_watcher(), to_addr=PRIMARY).value.endswith("/activate/abc123primary")
    with _Patched(_inbox(*both)):                                   # the newer one wins without to_addr
        assert _wait(_watcher()).value.endswith("/activate/def456backup")
    with _Patched(_inbox("workday_verify_primary")):                # nothing for the backup: timeout
        try:
            _wait(_watcher(), to_addr=BACKUP, wait_s=0)
        except ApplyFailure as e:
            assert e.reason is ReasonCode.EMAIL_VERIFICATION_TIMEOUT
        else:
            raise AssertionError("the primary's message must not satisfy a wait for the backup")


@needs("jobscraper.apply.mail")
def test_to_addr_matches_case_insensitively_and_on_forwarding_headers():
    raw = _raw("workday_verify_primary").replace(b"To: Alex Testcase <alex.testcase@example.com>",
                                                 b"To: undisclosed-recipients:;\r\n"
                                                 b"X-Original-To: ALEX.Backup@Example.NET")
    with _Patched(FakeServer({"INBOX": [raw]})):
        assert _wait(_watcher(), to_addr=BACKUP).kind == "link"


@needs("jobscraper.apply.mail")
def test_a_foreign_domain_link_is_never_returned():
    for name in ("phishing_foreign_link", "phishing_lookalike_sender"):
        with _Patched(_inbox(name)):
            try:
                v = _wait(_watcher(), wait_s=0)
            except ApplyFailure as e:
                assert e.reason is ReasonCode.EMAIL_VERIFICATION_TIMEOUT, name
            else:
                raise AssertionError(f"{name} must not yield a verification, got {v.kind}")


@needs("jobscraper.apply.mail")
def test_the_genuine_message_wins_over_traps_in_the_same_inbox():
    with _Patched(_inbox("workday_verify_primary", "phishing_foreign_link", "phishing_lookalike_sender")):
        v = _wait(_watcher())                    # the traps are newer, still never chosen
    assert v.value.endswith("/activate/abc123primary")


@needs("jobscraper.apply.mail")
def test_a_message_older_than_the_attempt_is_ignored():
    with _Patched(_inbox("workday_verify_stale")):
        try:
            _wait(_watcher(), wait_s=0)
        except ApplyFailure as e:
            assert e.reason is ReasonCode.EMAIL_VERIFICATION_TIMEOUT
        else:
            raise AssertionError("a message from before the attempt began must be ignored")


@needs("jobscraper.apply.mail")
def test_a_code_is_extracted_with_the_adapter_pattern_and_never_a_link():
    with _Patched(_inbox("greenhouse_code")):
        v = _wait(_watcher(), want="code", otp=GH_OTP, senders=("greenhouse-mail.io", "greenhouse.io"),
                  links=("greenhouse.io",))
    assert v.kind == "code" and v.value == "K7P2M9QX"
    assert v.sender_domain == "us.greenhouse-mail.io"


@needs("jobscraper.apply.mail")
def test_a_spam_folder_message_is_found_and_a_missing_folder_is_skipped():
    with _Patched(_inbox(spam=("workday_verify_primary",))) as srv:
        assert _wait(_watcher()).kind == "link"
    assert ("select", "[Gmail]/Spam", True) in srv.commands
    with _Patched(_inbox("workday_verify_primary")) as srv:         # no Spam folder on this server
        assert _wait(_watcher()).kind == "link"


@needs("jobscraper.apply.mail")
def test_an_empty_mailbox_times_out_with_the_reason_code():
    with _Patched(FakeServer({"INBOX": []})):
        try:
            _wait(_watcher(), wait_s=0)
        except ApplyFailure as e:
            assert e.reason is ReasonCode.EMAIL_VERIFICATION_TIMEOUT
        else:
            raise AssertionError("no message must raise email_verification_timeout")


@needs("jobscraper.apply.mail")
def test_the_password_and_the_link_never_reach_the_log():
    import io
    import logging
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    root = logging.getLogger()
    root.addHandler(h)
    old = root.level
    root.setLevel(logging.DEBUG)
    try:
        with _Patched(_inbox("workday_verify_primary")):
            _wait(_watcher())
    finally:
        root.removeHandler(h)
        root.setLevel(old)
    text = buf.getvalue()
    for secret in ("synthetic-app-password", "abc123primary", "Verify your email address"):
        assert secret not in text, secret


@needs("jobscraper.apply.mail:test_connection")
def test_connection_reports_the_message_count_read_only():
    from jobscraper.apply.mail import test_connection as probe
    with _Patched(_inbox("workday_verify_primary", "greenhouse_code")) as srv:
        out = probe("imap.example.test", 993, PRIMARY, Secret("synthetic-app-password"))
    assert out.startswith("ok:") and "2" in out
    assert not (srv.verbs() & {"FORBIDDEN"})
    assert all(c[2] is True for c in srv.commands if c[0] == "select")


@needs("jobscraper.apply.mail:employer_domain")
def test_employer_domain_is_the_registrable_domain_and_never_an_ats_host():
    from jobscraper.apply.mail import employer_domain as ed
    assert ed("https://www.dbs.com.sg/careers") == "dbs.com.sg"
    assert ed("https://careers.dbs.com/jobs/1") == "dbs.com"
    assert ed("https://jobs.example.co.uk/x") == "example.co.uk"
    for ats in ("https://acme.wd3.myworkdayjobs.com/External", "https://job-boards.greenhouse.io/x",
                "https://jobs.lever.co/x", "https://jobs.ashbyhq.com/x"):
        assert not ed(ats), ats


@needs("jobscraper.apply.mail:mailbox_for")
def test_mailbox_for_maps_each_address_to_its_mailbox():
    from jobscraper.apply.mail import mailbox_for
    prof = profile(email=PRIMARY, backup_email=BACKUP)
    assert mailbox_for(PRIMARY, prof, _settings()) == ("imap.gmail.com", 993, PRIMARY)
    assert mailbox_for(BACKUP, prof, _settings()) == ("imap.example.net", 993, BACKUP)
    # a backup address with no apply.mail_backup maps to the main mailbox (forwarding / alias)
    assert mailbox_for(BACKUP, prof, _settings(backup=False)) == ("imap.gmail.com", 993, PRIMARY)
    assert mailbox_for(PRIMARY, prof, _settings(main=False)) is None
    assert mailbox_for("someone.else@example.org", prof, _settings()) is None


# ================================================================== WP-T4 (Q-60): apply/mail on imapread
# MS 5.7: the watcher reads the special-use Spam name, falls back to [Gmail]/Spam, and its
# moved helpers are the imapread functions. These run on tests/mail_support.FakeMailServer
# (special-use LIST, per-session command log, write refusal, \Seen tracking).

def _gmail(layout="gmail", inbox=(), spam=()):
    from mail_support import FakeMailServer
    srv = FakeMailServer(layout)
    for n in inbox:
        srv.deliver(_raw(n), to=("inbox", "all") if layout != "all_hidden" else ("inbox",))
    for n in spam:
        srv.deliver(_raw(n), to=("junk",))
    return srv


def _gmail_watcher(srv):
    from jobscraper.apply.mail import MailWatcher
    return MailWatcher("imap.example.test", 993, PRIMARY, Secret("synthetic-app-password"),
                       connect=srv.factory, sleep=lambda _s: None)


def _watcher_read_only(srv):
    assert set(srv.verbs()) <= {"CONNECT", "LOGIN", "CAPABILITY", "LIST", "EXAMINE", "SEARCH", "FETCH",
                                "UID SEARCH", "UID FETCH", "NOOP", "LOGOUT"}, srv.verbs()
    assert srv.violations == [], srv.violations
    assert all(not srv.seen(b.role) for b in srv.boxes if b.role), "nothing marked read"


@needs("jobscraper.imapread", "jobscraper.apply.mail")
def test_apply_mail_helpers_are_the_imapread_functions():
    from jobscraper import imapread
    from jobscraper.apply import mail
    pairs = {"_host": "host_of", "domain_matches": "domain_matches", "employer_domain": "employer_domain",
             "_HtmlText": "_HtmlText", "_body": "body_text", "_sender_domain": "sender_domain",
             "_quote_folder": "quote_folder", "_internaldate": "internaldate", "_imap_date": "imap_date",
             "URL_RE": "URL_RE", "ATS_DOMAINS": "ATS_DOMAINS"}
    for alias, name in pairs.items():
        assert getattr(mail, alias) is getattr(imapread, name), alias
    # F-36 keeps its links (the verification-link search); F-50 hides them.
    msg = email.message_from_bytes(_raw("workday_verify_primary"), policy=policy.default)
    text, links = mail._body(msg)
    assert links and any("/activate/abc123primary" in u for u, _a in links)
    hidden, none = imapread.body_text(msg, links=False)
    assert none == [] and "abc123primary" not in hidden


@needs("jobscraper.imapread", "jobscraper.apply.mail")
def test_apply_mail_reads_the_special_use_spam_name():
    from jobscraper import imapread
    from jobscraper.apply import mail
    from mail_support import mutf7
    for layout, spam in (("googlemail_de", "[Google Mail]/Spam"), ("zh", "[Gmail]/" + mutf7("垃圾邮件")),
                         ("gmail", "[Gmail]/Spam"), ("plain", "Junk")):
        srv = _gmail(layout, spam=("workday_verify_primary",))
        with srv.patched(mail, imapread):
            v = _wait(_gmail_watcher(srv), to_addr=PRIMARY)
        assert v.kind == "link" and v.value.endswith("/activate/abc123primary"), layout
        examined = [c[1] for c in srv.commands("EXAMINE")]
        assert imapread.quote_folder(spam) in examined, (layout, examined)
        if spam != "[Gmail]/Spam":
            assert "[Gmail]/Spam" not in examined, (layout, examined)
        _watcher_read_only(srv)


@needs("jobscraper.imapread", "jobscraper.apply.mail")
def test_apply_mail_falls_back_to_gmail_spam_when_no_junk_is_flagged():
    from jobscraper import imapread
    from jobscraper.apply import mail
    srv = _gmail("junk_hidden", inbox=("workday_verify_primary",))
    with srv.patched(mail, imapread):
        v = _wait(_gmail_watcher(srv), to_addr=PRIMARY)
    assert v.kind == "link"
    assert "[Gmail]/Spam" in [c[1] for c in srv.commands("EXAMINE")], "the fixed fallback is tried"
    _watcher_read_only(srv)

    class Conn:                                       # LIST refused, then a dropped connection
        def __init__(self, exc):
            self.exc = exc

        def list(self, *_a):
            raise self.exc
    assert mail._folders(Conn(imaplib.IMAP4.error("LIST refused"))) == ("INBOX", "[Gmail]/Spam")
    try:
        mail._folders(Conn(imaplib.IMAP4.abort("socket error: EOF")))
    except imaplib.IMAP4.abort:
        pass
    else:
        raise AssertionError("a dropped connection must propagate, not fall back")


if WAITING:
    print(f"test_apply_mail: waiting on {sorted({m for _n, m in WAITING})} "
          f"({len(WAITING)} oracles not yet defined)", file=sys.stderr)
