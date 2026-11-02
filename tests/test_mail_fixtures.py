"""WP-T1: the F-50 synthetic mail fixtures and the fake IMAP server (mail_status_design.md 5, 6,
13, 16; build plan WP-T1). Verify: `python tests/run_tests.py -k mail_fixtures`.

Runs now (no src module needed):
  - every golden .eml parses and golden.yaml lists each file once, with expectations drawn from
    the MS 3 contract values; at least 3 cases per category and every tricky case of the build
    plan (tags);
  - the fixtures are synthetic: addresses only on reserved domains or public platform domains,
    test-net IPs, synthetic Message-IDs; plus the owner deny-list scan when
    JOBSCRAPER_FIXTURE_DENYLIST names a file outside the repo (values are never printed);
  - the reference parsers in mail_support agree with the golden `auth` values (the transport's
    Authentication-Results reading must give the same), and `[link]` replaces every URL;
  - rules_min.yaml satisfies the MS 6.1 schema (E1 platform keys included);
  - the fake server behaves like Gmail IMAP where the oracles rely on it.
"""
from __future__ import annotations

import imaplib
import ipaddress
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_support import (  # noqa: E402
    GMAIL_HOST, GMAIL_LOGIN_ERRORS, GOLDEN_DIR, GOLDEN_YAML, LAYOUTS, LOGIN_ERROR_ECHOING_USER,
    MAIL, PLAIN_CAPABILITIES, RULES_MIN, FakeMailServer, auth_result, body_text,
    design_contracts, eml, golden, golden_cases, message, mutf7, parse_fetch, reg_domain,
    schema_errors,
)

CATEGORIES = ("acknowledged", "assessment", "interview", "offer", "rejected", "withdrawn",
              "posting_closed", "kept_on_file", "portal_update", "unknown")
HEADER_SKIPS = {"too_old", "own_mail", "auto_reply", "job_board", "not_job_mail", "bulk"}
CONTENT_SKIPS = {"auto_reply", "account_mail", "job_alert", "outreach"}
# Build plan WP-T1's tricky cases (MB 4), plus the Oleeo tal.net acknowledgement.
TRICKY = {"neutral_subject_log_in_to_view", "volume_disclaimer", "talent_community_newsletter",
          "talent_community_welcome", "job_alert", "job_board", "verification_with_confirm",
          "security_code", "reminder", "reschedule", "recruiter_outreach", "auto_replied",
          "auto_generated", "own_sent_mail", "chinese_rejection", "offer_you_an_interview",
          "hirevue_on_demand", "hirevue_live", "kept_on_file_alone", "kept_on_file_with_rejection",
          "offer_from_spam", "offer_dmarc_fail", "oleeo_talnet", "confirm_in_acknowledgement",
          "ambiguous_no_role", "thread_first", "saved_role", "calendar_request"}
PLATFORM_DOMAINS = ("greenhouse-mail.io", "greenhouse.io", "myworkday.com", "myworkdayjobs.com",
                    "tal.net", "successfactors.eu", "successfactors.com", "hirevue.com",
                    "hackerrankforwork.com", "hackerrank.com", "codility.com", "linkedin.com")
SYNTHETIC_DOMAINS = ("example.com", "example.org", "example.net", "example", "test")


def _files() -> list[Path]:
    return sorted(GOLDEN_DIR.glob("*.eml"))


# ------------------------------------------------------------------ the golden set

def test_mail_fixtures_every_golden_eml_parses_and_is_listed_once():
    listed = [c["file"] for c in golden_cases()]
    on_disk = [p.name for p in _files()]
    assert len(listed) == len(set(listed)), "golden.yaml lists a file twice"
    assert set(listed) == set(on_disk), (
        f"unlisted: {sorted(set(on_disk) - set(listed))}, missing: {sorted(set(listed) - set(on_disk))}")
    for p in _files():
        msg = message(p.read_bytes())
        for h in ("From", "To", "Subject", "Date", "Message-ID"):
            assert msg.get(h), f"{p.name}: no {h}"
        assert msg["From"].addresses, f"{p.name}: From has no address"
        assert datetime.strptime(str(msg["Date"])[5:25], "%d %b %Y %H:%M:%S")
    ids = [c["gm_msgid"] for c in golden_cases()]
    assert len(ids) == len(set(ids)) and all(re.fullmatch(r"\d{19}", i) for i in ids)
    assert golden()["version"] == 1


def test_mail_fixtures_cover_every_category_gate_and_tricky_case():
    cases = golden_cases()
    per = {k: 0 for k in CATEGORIES}
    for c in cases:
        if not c["expect"]["skip"]:
            per[c["expect"]["category"]] += 1
    thin = {k: n for k, n in per.items() if n < 3}
    assert not thin, f"fewer than 3 golden cases for {thin}"
    skips = {c["expect"]["skip"]["reason"] for c in cases if c["expect"]["skip"]}
    assert (HEADER_SKIPS | CONTENT_SKIPS) <= skips, f"no case for {(HEADER_SKIPS | CONTENT_SKIPS) - skips}"
    tags = {t for c in cases for t in c.get("tags") or []}
    assert TRICKY <= tags, f"tricky cases without a golden case: {sorted(TRICKY - tags)}"
    kinds = {c["expect"]["change"]["kind"] for c in cases if not c["expect"]["skip"]}
    assert kinds == {"auto", "suggest", "none"}
    assert {c["folder"] for c in cases} == {"all", "junk"}


def test_mail_fixtures_expectations_use_the_contract_values():
    """Every value in golden.yaml is a value of the MS 3 contracts (read from the design
    listing, so this runs before contracts.py exists)."""
    c = design_contracts()
    cats = {m.value for m in c.Category}
    reasons = {m.value for m in c.Reason}
    skip_reasons = {m.value for m in c.SKIP_REASONS}
    suggest = {m.value for m in c.SUGGEST_REASONS}
    g = golden()
    apps = {a["job_id"] for a in g["apps"]}
    statuses = set(g["context"]["statuses"])
    assert set(g["context"]["mail_status"]["category_status"]) <= cats
    assert set(g["context"]["mail_status"]["category_status"].values()) <= statuses
    for a in g["apps"]:
        assert a["status"] in statuses, a
        assert set(a) >= {"job_id", "status", "company_names", "role", "employer_domains",
                          "tenant_hosts", "board_slugs", "req_ids", "threads",
                          "owner_changed_at", "last_event_at"}, a["job_id"]
    for case in g["cases"]:
        e, f = case["expect"], case["file"]
        assert case["folder"] in {m.value for m in c.MailboxRole}, f
        assert case["auth"] in {m.value for m in c.AuthResult}, f
        if e["skip"]:
            gate, reason = e["skip"]["gate"], e["skip"]["reason"]
            assert reason in skip_reasons, f
            assert reason in (HEADER_SKIPS if gate == "header" else CONTENT_SKIPS), f
            assert set(e) == {"skip"}, f"{f}: a skipped case has no category/match/change"
            continue
        assert e["category"] in cats - {"no_change"}, f"{f}: rules never give no_change"
        assert isinstance(e["status_words"], bool), f
        m = e["match"]
        assert m["kind"] in {k.value for k in c.MatchKind}, f
        if m["kind"] == "ambiguous":
            assert len(m["candidates"]) >= 2 and set(m["candidates"]) <= apps, f
        elif m["kind"] != "none":
            assert m["job_id"] in apps, f
        ch = e["change"]
        reasons_here = ch["reason"] if isinstance(ch["reason"], list) else [ch["reason"]]
        assert set(reasons_here) <= reasons, f
        assert ch["kind"] in {k.value for k in c.ChangeKind}, f
        if ch["kind"] == "auto":
            assert reasons_here == ["forward"] and ch["to"] in statuses, f
        elif ch["kind"] == "suggest":
            assert set(reasons_here) <= suggest, f
            assert ch["to"] is None or ch["to"] in statuses, f
        else:
            assert ch["to"] is None and not set(reasons_here) & (suggest | {"forward"}), f
        if e.get("conflict"):
            assert e["category"] == "unknown" and set(e["conflict"]) <= cats, f
        if e.get("needs_model"):
            assert e["category"] == "unknown" and e["status_words"], f


# ------------------------------------------------------------------ privacy

_ADDR = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_HOST = re.compile(r"(?i)https?://([\w.-]+)")


def _allowed(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in SYNTHETIC_DOMAINS + PLATFORM_DOMAINS)


def test_mail_fixtures_are_synthetic():
    bad = []
    scanned = _files() + [GOLDEN_YAML, RULES_MIN]
    for p in scanned:
        text = p.read_text(encoding="utf-8")
        for dom in _ADDR.findall(text):
            if not _allowed(dom):
                bad.append(f"{p.name}: address on {dom}")
        for host in _HOST.findall(text):
            if not _allowed(host):
                bad.append(f"{p.name}: URL host {host}")
        for ip in _IP.findall(text):
            if ipaddress.ip_address(ip) not in ipaddress.ip_network("192.0.2.0/24"):
                bad.append(f"{p.name}: IP {ip} outside TEST-NET-1")
        if p.suffix == ".eml":
            mid = str(message(p.read_bytes())["Message-ID"])
            if not mid.endswith("@synthetic.test>"):
                bad.append(f"{p.name}: Message-ID")
    assert not bad, bad


def _denylist() -> list[str] | None:
    path = os.environ.get("JOBSCRAPER_FIXTURE_DENYLIST", "")
    if not path:
        return None
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def test_mail_fixtures_hold_none_of_the_owners_denylisted_values():
    deny = _denylist()
    if deny is None:
        print("  note: JOBSCRAPER_FIXTURE_DENYLIST not set; owner deny-list scan not run")
        return
    assert deny, "the deny-list file is empty"
    here = Path(__file__).resolve().parent
    scanned = [p for p in MAIL.rglob("*") if p.is_file()] + [here / "mail_support.py", Path(__file__)]
    scanned += sorted(here.glob("test_mail_*.py"))
    hits = set()
    for p in scanned:
        low = p.read_bytes().decode("utf-8", "replace").lower()
        if any(v.lower() in low for v in deny):
            hits.add(p.name)
    assert not hits, f"deny-listed values found in {sorted(hits)}"      # never print the values


# ------------------------------------------------------------------ reference parsers

def test_mail_fixtures_reference_auth_matches_every_golden_case():
    """The transport's Authentication-Results reading (MS 3 AuthResult) must give these too."""
    wrong = {c["file"]: (auth_result(message(eml(c["file"]))), c["auth"]) for c in golden_cases()
             if auth_result(message(eml(c["file"]))) != c["auth"]}
    assert not wrong, wrong
    assert {c["auth"] for c in golden_cases()} == {"pass", "fail", "none"}


def test_mail_fixtures_body_text_replaces_urls_and_reads_html_and_calendars():
    text, cal = body_text(message(eml("int_offer_you_an_interview")))
    assert "[link]" in text and "http" not in text and not cal
    text, cal = body_text(message(eml("portal_neutral_subject")))
    assert "log in to view" in text and "<" not in text and "http" not in text
    text, cal = body_text(message(eml("int_calendar_invite")))
    assert cal and "invited you to a meeting" in text and "BEGIN:VCALENDAR" not in text
    text, _ = body_text(message(eml("rej_chinese")))
    assert "很遗憾" in text
    assert str(message(eml("rej_chinese"))["Subject"]).startswith("关于您的申请")
    assert message(eml("int_reschedule"))["From"].addresses[0].display_name == "Northwind Traders Hiring"
    assert reg_domain("us.greenhouse-mail.io") == "greenhouse-mail.io"
    assert reg_domain("contosobank.tal.net") == "tal.net"
    assert reg_domain("jobs.mycareersfuture.gov.sg") == "mycareersfuture.gov.sg"
    assert mutf7("Messages envoyés") == "Messages envoy&AOk-s" and mutf7("A&B") == "A&-B"


# ------------------------------------------------------------------ rules_min.yaml (MS 6.1)

def test_mail_fixtures_rules_min_is_valid_and_has_the_e1_platforms():
    doc = yaml.safe_load(RULES_MIN.read_text(encoding="utf-8"))
    cats = {m.value for m in design_contracts().Category}
    assert schema_errors(doc, cats) == []
    plats = {p["id"]: p for p in doc["platforms"]}
    assert plats["workday"]["tenant_from_local_part"] and plats["workday"]["tenant_sites"] == ["myworkdayjobs.com"]
    assert plats["oleeo"]["tenant_from_subdomain"] and plats["oleeo"]["tenant_sites"] == ["tal.net"]
    assert set(doc["categories"]) == cats - {"no_change", "unknown"}
    # The bare word "confirm" is no account phrase (MB 4): only longer phrases contain it.
    for e in doc["gates"]["account"]:
        assert not re.fullmatch(r"\(?confirm\)?", e["re"]), e
    # The schema check bites.
    broken = yaml.safe_load(RULES_MIN.read_text(encoding="utf-8"))
    broken["platforms"][1]["tenant_from_subdomain"] = True
    broken["categories"]["acknowledged"]["phrases"][0]["re"] = "thank (you"
    broken["dominates"]["offer"].append("nonsense")
    errs = schema_errors(broken, cats)
    assert any("both tenant flags" in x for x in errs) and any("regex" in x for x in errs)
    assert any(x.startswith("dominates offer") for x in errs)


# ------------------------------------------------------------------ the fake IMAP server

def _server(layout="gmail", **kw) -> FakeMailServer:
    s = FakeMailServer(layout, **kw)
    for c in golden_cases()[:6]:
        s.deliver(eml(c["file"]), gm_msgid=c["gm_msgid"], gm_thrid=c["gm_thrid"])
    return s


def test_mail_fixtures_fake_imap_lists_special_use_layouts():
    seen = {}
    for layout in LAYOUTS:
        s = FakeMailServer(layout)
        with s.patched():
            conn = imaplib.IMAP4_SSL(GMAIL_HOST, 993)
            conn.login("someone@example.com", "app-password-unused")
            typ, lines = conn.list()
        assert typ == "OK" and all(isinstance(x, bytes) for x in lines)
        flags = {f for x in lines for f in re.findall(rb"\\(\w+)", x.split(b")")[0])}
        seen[layout] = (flags, lines)
        for x in lines:
            x.decode("ascii")                                    # mUTF-7 is plain ASCII
    assert b"All" in seen["gmail"][0] and b"Junk" in seen["gmail"][0]
    assert b"All" not in seen["all_hidden"][0] and b"Junk" in seen["all_hidden"][0]
    assert b"Junk" not in seen["junk_hidden"][0] and b"All" in seen["junk_hidden"][0]
    assert any(b'"[Google Mail]/Alle Nachrichten"' in x for x in seen["googlemail_de"][1])
    assert any(b"&" in x and b"\\All" in x for x in seen["zh"][1])
    assert b"All" not in seen["plain"][0]


def test_mail_fixtures_fake_imap_examines_and_follows_the_uid_rules():
    s = _server()
    with s.patched():
        conn = imaplib.IMAP4_SSL(GMAIL_HOST, 993)
        conn.login("someone@example.com", "x")
        typ, data = conn.select('"[Gmail]/All Mail"', readonly=True)
        assert typ == "OK" and data == [b"6"]
        assert conn.response("UIDVALIDITY")[1] == [str(s.box("all").validity).encode()]
        assert conn.untagged_responses["UIDNEXT"] == [b"7"] and "READ-ONLY" in conn.untagged_responses
        # The `n:*` gotcha: `*` is the highest UID, so 50:* still returns 6.
        assert conn.uid("SEARCH", None, "UID", "50:*") == ("OK", [b"6"])
        assert conn.uid("SEARCH", "UID 4:*") == ("OK", [b"4 5 6"])
        assert conn.uid("SEARCH", None, "SINCE", "24-Oct-2026") == ("OK", [b"5 6"])
        assert conn.uid("SEARCH", None, "SINCE", "01-Jan-2030") == ("OK", [b""])
        msgid = golden_cases()[2]["gm_msgid"]
        assert conn.uid("SEARCH", None, "X-GM-MSGID", msgid) == ("OK", [b"3"])
        st = conn.status('"[Gmail]/All Mail"', "(UIDNEXT UIDVALIDITY)")
        assert b"UIDNEXT 7" in st[1][0]
        assert conn.select('"[Gmail]/Nope"', readonly=True)[0] == "NO"
        try:
            conn.select("[Gmail]/All Mail", readonly=True)           # unquoted: BAD, as Gmail
        except imaplib.IMAP4.error:
            pass
        else:
            raise AssertionError("an unquoted name with a space must fail")
        try:
            conn.select('"[Gmail]/所有邮件"', readonly=True)         # decoded, not mUTF-7
        except UnicodeEncodeError:
            pass
        else:
            raise AssertionError("a decoded localised name must fail as in imaplib")
        conn.logout()
    assert ("EXAMINE", '"[Gmail]/All Mail"', True) in s.log
    assert s.violations == []


def test_mail_fixtures_fake_imap_fetches_gmail_items_and_peek_keeps_mail_unread():
    s = _server()
    items = ("(UID INTERNALDATE RFC822.SIZE X-GM-MSGID X-GM-THRID X-GM-LABELS "
             "BODY.PEEK[HEADER.FIELDS (FROM REPLY-TO SUBJECT DATE LIST-ID PRECEDENCE AUTO-SUBMITTED "
             "X-AUTOREPLY X-AUTORESPOND AUTHENTICATION-RESULTS)])")
    with s.patched():
        conn = imaplib.IMAP4_SSL(GMAIL_HOST, 993)
        conn.login("someone@example.com", "x")
        conn.select('"[Gmail]/All Mail"', readonly=True)
        typ, data = conn.uid("FETCH", "2:3", items)
        rows = parse_fetch(data)
        assert typ == "OK" and [r["UID"] for r in rows] == [2, 3]
        head = rows[0]["BODY[HEADER.FIELDS (FROM REPLY-TO SUBJECT DATE LIST-ID PRECEDENCE AUTO-SUBMITTED X-AUTOREPLY X-AUTORESPOND AUTHENTICATION-RESULTS)]"]
        assert head.startswith(b"Authentication-Results") or b"\r\nFrom:" in head
        assert b"Message-ID" not in head and head.endswith(b"\r\n\r\n")
        assert rows[0]["X-GM-MSGID"] == int(golden_cases()[1]["gm_msgid"])
        assert rows[0]["RFC822.SIZE"] == len(eml(golden_cases()[1]["file"]))
        assert re.fullmatch(r"\d\d-\w{3}-2026 \d\d:\d\d:\d\d \+0000", rows[0]["INTERNALDATE"])
        body = parse_fetch(conn.uid("FETCH", "3", "(BODY.PEEK[])")[1])[0]["BODY[]"]
        assert message(body)["Subject"] == message(eml(golden_cases()[2]["file"]))["Subject"]
        assert s.seen("all") == set() and s.violations == []
        assert conn.uid("FETCH", "99", "(UID)") == ("OK", [None])
        conn.uid("FETCH", "4", "(BODY[])")                          # no PEEK: marks it read
        assert s.seen("all") == {4} and s.violations
        conn.uid("FETCH", "5", "(RFC822)")
        assert 5 in s.seen("all")


def test_mail_fixtures_fake_imap_refuses_writes_and_never_logs_the_password():
    s = _server()
    with s.patched():
        conn = imaplib.IMAP4_SSL(GMAIL_HOST, 993)
        conn.login("someone@example.com", "s3cret-app-pw")
        conn.select('"INBOX"', readonly=True)
        for call in (lambda: conn.store("1", "+FLAGS", "\\Seen"), lambda: conn.expunge(),
                     lambda: conn.copy("1", "Trash"), lambda: conn.append("INBOX", None, None, b"x"),
                     lambda: conn.uid("STORE", "1", "+FLAGS", "(\\Seen)"),
                     lambda: conn.uid("MOVE", "1", "Trash"), lambda: conn.create("New"),
                     lambda: conn.delete("INBOX")):
            try:
                call()
            except AssertionError:
                pass
            else:
                raise AssertionError("a write command went through")
        conn.select('"INBOX"')                                     # read-write SELECT: logged
    verbs = s.verbs()
    for v in ("STORE", "EXPUNGE", "COPY", "APPEND", "UID STORE", "UID MOVE", "CREATE", "DELETE", "SELECT"):
        assert v in verbs, v
    assert len(s.violations) == 9
    assert "s3cret-app-pw" not in repr(s.log) and ("LOGIN", "someone@example.com") in s.log


def test_mail_fixtures_fake_imap_login_errors_capabilities_and_connect_errors():
    for text, code in GMAIL_LOGIN_ERRORS.items():
        s = FakeMailServer()
        s.login_error = text
        with s.patched():
            conn = imaplib.IMAP4_SSL(GMAIL_HOST, 993)
            try:
                conn.login("someone@example.com", "x")
            except imaplib.IMAP4.error as e:
                assert text in str(e), (text, str(e))
            else:
                raise AssertionError(f"login should fail: {code}")
    assert set(GMAIL_LOGIN_ERRORS.values()) == {"login_refused", "app_password_required",
                                                "web_login_required", "rate_limited"}
    assert "canary.user@example.com" in LOGIN_ERROR_ECHOING_USER
    s = FakeMailServer(password="right")
    with s.patched():
        try:
            imaplib.IMAP4_SSL(GMAIL_HOST, 993).login("someone@example.com", "wrong")
        except imaplib.IMAP4.error:
            pass
        else:
            raise AssertionError("a wrong password must fail")
        assert imaplib.IMAP4_SSL(GMAIL_HOST, 993).login("someone@example.com", "right")[0] == "OK"
    s = FakeMailServer("plain", capabilities=PLAIN_CAPABILITIES)
    with s.patched():
        conn = imaplib.IMAP4_SSL("imap.example.com", 993)
        assert "X-GM-EXT-1" not in conn.capabilities
        conn.login("someone@example.com", "x")
        conn.select('"INBOX"', readonly=True)
        try:
            conn.uid("SEARCH", None, "X-GM-MSGID", "1")
        except imaplib.IMAP4.error:
            pass
        else:
            raise AssertionError("X-GM items need X-GM-EXT-1")
    s = FakeMailServer()
    s.connect_error = OSError("getaddrinfo failed")
    with s.patched():
        try:
            imaplib.IMAP4_SSL(GMAIL_HOST, 993)
        except OSError:
            pass
        else:
            raise AssertionError("connect_error must raise")


def test_mail_fixtures_fake_imap_drops_moves_deletes_and_changes_uidvalidity():
    s = _server()
    s.drop_after = 3
    with s.patched():
        conn = imaplib.IMAP4_SSL(GMAIL_HOST, 993)
        conn.login("someone@example.com", "x")
        conn.select('"[Gmail]/All Mail"', readonly=True)
        conn.uid("SEARCH", None, "UID", "1:*")
        try:
            conn.uid("FETCH", "1", "(UID)")
        except imaplib.IMAP4.abort:
            pass
        else:
            raise AssertionError("the 4th command must drop the connection")
        assert s.log[-1] == ("DROPPED", "UID FETCH")
    s.drop_after = None
    old = s.box("all").validity
    assert s.change_validity("all") == old + 1
    jid = s.deliver(eml("ack_spam_gh"), to=("junk",))
    new_uid = s.move(jid, "junk", "all")
    assert s.find("all", jid) == new_uid == 7 and s.find("junk", jid) is None
    s.delete(golden_cases()[0]["gm_msgid"])
    with s.patched():
        conn = imaplib.IMAP4_SSL(GMAIL_HOST, 993)
        conn.login("someone@example.com", "x")
        conn.select('"[Gmail]/All Mail"', readonly=True)
        assert conn.response("UIDVALIDITY")[1] == [str(old + 1).encode()]
        assert conn.uid("SEARCH", None, "X-GM-MSGID", str(jid)) == ("OK", [b"7"])
        assert conn.uid("SEARCH", None, "ALL") == ("OK", [b"2 3 4 5 6 7"])
    assert len(s.session_logs) == 2 and s.session_logs[1][0][0] == "CONNECT"


def test_mail_fixtures_fake_imap_hidden_all_mail_is_not_selectable():
    s = FakeMailServer("all_hidden")
    s.deliver(eml("ack_gh_saved_role"), when=datetime(2026, 10, 20, tzinfo=timezone.utc))
    with s.patched():
        conn = imaplib.IMAP4_SSL(GMAIL_HOST, 993)
        conn.login("someone@example.com", "x")
        assert conn.select('"[Gmail]/All Mail"', readonly=True)[0] == "NO"
        assert conn.select('"INBOX"', readonly=True) == ("OK", [b"1"])
        assert conn.search(None, "ALL") == ("OK", [b"1"])           # apply/mail.py's plain SEARCH
        assert parse_fetch(conn.fetch("1", "(INTERNALDATE BODY.PEEK[])")[1])[0]["BODY[]"]
