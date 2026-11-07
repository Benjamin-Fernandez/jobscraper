"""WP-T4 oracles: the read-only Gmail transport (mail_status_design.md 5.2-5.7, 12, 13; build
plan WP-T4, WP-I1). Verify: `python tests/run_tests.py -k imapread`.

No network: tests/mail_support.FakeMailServer stands in for Gmail (special-use LIST, EXAMINE
with UIDVALIDITY/UIDNEXT, UID SEARCH with the `n:*` rule, X-GM-*, BODY.PEEK) and records
every command; `patched` also makes any real socket a test failure.

Skip-clean until `jobscraper.imapread` exists; after that `test_imapread_oracles_are_live`
fails if any oracle here still waits.

ASSUMED call shapes (build plan WP-I1, MS 3):
  imapread.ImapTransport(host, port, username, Secret, *, timeout_s=20, connect=None)
    .open() -> TransportInfo   .scan(role, cursor, *, account_id, window_start, limit, now)
    .fetch_body(ref, max_bytes) -> MailBody | None   .refind(gm_msgid) -> MailHeader | None
    .close(); failures raise contracts.MailFailure(code, detail)
  imapread.plan_scan(cursor, uidvalidity, uidnext, window_start, now) -> ScanPlan
  imapread.special_use_folders(conn), login_code(exc), auth_result(headers, from_reg),
  parse_header(meta, raw, ref, cursor_before), parse_body(raw), body_text(msg, links),
  quote_folder(name), and the guard class _ReadOnly.
"""
from __future__ import annotations

import base64
import email
import email.policy
import imaplib
import re
import socket
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_support import (  # noqa: E402
    GMAIL_LOGIN_ERRORS, LOGIN_ERROR_ECHOING_USER, LAYOUTS, PLAIN_CAPABILITIES, RULES_MIN, WAITING,
    FakeMailServer, assert_live, eml, golden, golden_cases, golden_employer_regs, golden_own,
    golden_threads, header_from_eml, make_eml, mutf7, needs, note_waiting,
)

_W0 = len(WAITING)
IMAPREAD = "jobscraper.imapread"
USER = "alex.applicant@inbox.example"
NOW = "2026-11-02T12:00:00"
EARLY = "2020-01-01T00:00:00"
READ_VERBS = {"CONNECT", "LOGIN", "CAPABILITY", "LIST", "EXAMINE", "UID SEARCH", "UID FETCH",
              "NOOP", "LOGOUT"}


def _i():
    from jobscraper import imapread
    return imapread


def _c():
    from jobscraper.mailstatus import contracts
    return contracts


def _transport(**kw):
    from jobscraper.apply.contracts import Secret
    return _i().ImapTransport("imap.gmail.com", 993, USER, Secret("synthetic-app-password"), **kw)


def _scan(t, role="all", cursor=None, *, limit=2000, window=EARLY, now=NOW):
    c = _c()
    return t.scan(c.MailboxRole(role), cursor, account_id=1, window_start=window, limit=limit, now=now)


def _msg(n, date="Mon, 26 Oct 2026 09:00:00 +0000", frm="Northwind Talent <talent@northwind.example>"):
    return make_eml(frm, f"Message {n}", f"Body {n}. Thank you for applying.", date=date)


def _when(y, m, d):
    return datetime(y, m, d, 9, 0, tzinfo=timezone.utc)


def _uids(res):
    return [h.ref.uid for h in res.headers]


def _fetch_items(srv):
    return [str(c[2]) for c in srv.commands("UID FETCH")]


def _assert_read_only(srv):
    assert set(srv.verbs()) <= READ_VERBS, set(srv.verbs()) - READ_VERBS
    assert srv.violations == [], srv.violations
    for items in _fetch_items(srv):
        up = items.upper()
        assert "BODY[" not in up.replace("BODY.PEEK[", ""), items
        assert not re.search(r"RFC822(?!\.SIZE)", up), items
    for b in srv.boxes:
        assert not any("\\Seen" in m.flags for m in b.messages.values()), b.name


# ------------------------------------------------------------------ the command guard (MS 5.6)

@needs(IMAPREAD)
def test_imapread_readonly_surface_is_the_allow_list():
    ro_cls = _i()._ReadOnly
    public = {n for n in dir(ro_cls) if not n.startswith("_")}
    assert public == {"login", "capability", "list", "examine", "uid_search", "uid_fetch", "noop",
                      "logout"}, public
    assert "__getattr__" not in vars(ro_cls), "nothing may be forwarded by name"

    class Conn:
        def __getattr__(self, name):
            raise AssertionError(f"forwarded {name}")
    ro = ro_cls(Conn())
    for name in ("store", "copy", "move", "expunge", "append", "select", "uid", "xatom",
                 "_simple_command", "create", "delete"):
        try:
            getattr(ro, name)
        except AttributeError:
            continue
        raise AssertionError(f"_ReadOnly offers {name}")


@needs(IMAPREAD)
def test_imapread_uid_fetch_refuses_every_item_that_marks_mail_read():
    I = _i()

    class Stub:
        def __init__(self):
            self.calls = []

        def uid(self, *a):
            self.calls.append(a)
            return "OK", [None]
    refused = ["BODY[]", "(UID BODY[])", "(UID BODY[TEXT])", "BODY[HEADER.FIELDS (FROM)]",
               "body[]", "(UID BODY[]<0.100>)", "RFC822", "(UID RFC822.TEXT)", "(UID RFC822.HEADER)",
               "(UID RFC822.SIZE RFC822)", "BINARY[1]", b"(UID BODY[])",
               "(UID BODY.PEEK[HEADER] BODY[TEXT])"]
    for items in refused:
        stub = Stub()
        try:
            I._ReadOnly(stub).uid_fetch("1", items)
        except ValueError:
            assert stub.calls == [], (items, "refused items never reach the server")
            continue
        raise AssertionError(f"uid_fetch sent {items!r}")
    for items in (I.HEADER_ITEMS, I.SIZE_ITEMS, I.BODY_ITEMS, "(UID BODY.PEEK[TEXT]<0.2048>)",
                  "(UID BODYSTRUCTURE)", "(UID FLAGS)", "(UID rfc822.size)"):
        stub = Stub()
        I._ReadOnly(stub).uid_fetch("1:3", items)
        assert stub.calls == [("FETCH", "1:3", items)], (items, stub.calls)
    assert "BODY.PEEK[" in I.HEADER_ITEMS and I.BODY_ITEMS == "(UID BODY.PEEK[])"


def _golden_server(layout="gmail"):
    srv = FakeMailServer(layout)
    for case in golden_cases():
        srv.deliver(eml(case["file"]), to=(case.get("folder", "all"),), gm_msgid=case["gm_msgid"],
                    gm_thrid=case["gm_thrid"], labels=case.get("labels") or ())
    return srv


@needs(IMAPREAD)
def test_imapread_a_whole_session_sends_read_commands_only():
    """Open, scan All Mail and Spam, fetch every body, refind, close: the log holds no
    write, no read-write SELECT and no fetch that sets \\Seen (F-50g, MS 5.6)."""
    srv = _golden_server()
    with srv.patched(_i()):
        t = _transport()
        t.open()
        heads = list(_scan(t, "all").headers) + list(_scan(t, "junk").headers)
        assert len(heads) == len(golden_cases())
        for h in heads:
            assert t.fetch_body(h.ref, 5_000_000) is not None, h.ref
        assert t.refind(heads[0].gm_msgid) is not None
        t.close()
    _assert_read_only(srv)
    assert srv.verbs()[-1] == "LOGOUT"
    assert all(c[2] is True for c in srv.commands("EXAMINE"))
    assert srv.verbs().count("LOGIN") == 1, "one connection per sync"


# ------------------------------------------------------------------ special-use folders (MS 5.2)

_FOLDERS = {
    "gmail": ({"all": "[Gmail]/All Mail", "junk": "[Gmail]/Spam"}, ()),
    "googlemail_de": ({"all": "[Google Mail]/Alle Nachrichten", "junk": "[Google Mail]/Spam"}, ()),
    "fr": ({"all": "[Gmail]/Tous les messages", "junk": "[Gmail]/Spam"}, ()),
    "zh": ({"all": "[Gmail]/" + mutf7("所有邮件"), "junk": "[Gmail]/" + mutf7("垃圾邮件")}, ()),
    "all_hidden": ({"inbox": "INBOX", "junk": "[Gmail]/Spam"}, ("all_mail_hidden",)),
    "junk_hidden": ({"all": "[Gmail]/All Mail"}, ("junk_hidden",)),
    "plain": ({"inbox": "INBOX", "junk": "Junk"}, ("all_mail_hidden",)),
}


@needs(IMAPREAD)
def test_imapread_folders_come_from_special_use_flags_in_every_layout():
    c = _c()
    assert set(_FOLDERS) == set(LAYOUTS)
    for layout, (want, notes) in _FOLDERS.items():
        srv = FakeMailServer(layout)
        for role in want:
            srv.deliver(_msg(1), to=(role,))
        with srv.patched(_i()):
            t = _transport()
            info = t.open()
            got = {r.value: n for r, n in info.folders.items()}
            assert got == want, (layout, got)
            assert tuple(n.value for n in info.notes) == notes, (layout, info.notes)
            assert "X-GM-EXT-1" in {x.upper() for x in info.capabilities}
            for role in want:                    # the raw name EXAMINEs (quoting, mUTF-7)
                res = _scan(t, role)
                assert _uids(res) == [1] and res.complete, (layout, role)
                assert res.headers[0].ref.role == c.MailboxRole(role)
                assert res.headers[0].ref.mailbox == want[role]
            t.close()
        _assert_read_only(srv)


@needs(IMAPREAD)
def test_imapread_list_lines_quoted_atom_literal_and_escaped():
    I, c = _i(), _c()

    class Lister:
        def __init__(self, data, typ="OK"):
            self.data, self.typ = data, typ

        def list(self, directory='""', pattern="*"):
            return self.typ, self.data
    data = [b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
            (b'(\\HasNoChildren \\All) "/" {16}', b'Alle "Nachricht"'),
            b"",
            b'(\\junk \\HasNoChildren) NIL Junk',
            None,
            b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Bin"']
    got = I.special_use_folders(Lister(data))
    assert got == {c.MailboxRole.ALL: 'Alle "Nachricht"', c.MailboxRole.JUNK: "Junk"}, got
    esc = [b'(\\All \\HasNoChildren) "/" "[Gmail]/All \\"Mail\\""']
    assert I.special_use_folders(Lister(esc)) == {c.MailboxRole.ALL: '[Gmail]/All "Mail"'}
    first = [b'(\\All) "/" "[Gmail]/All Mail"', b'(\\All) "/" "Archive"']
    assert I.special_use_folders(Lister(first))[c.MailboxRole.ALL] == "[Gmail]/All Mail"
    assert I.special_use_folders(Lister([], "NO")) == {}
    assert I.special_use_folders(Lister([b'(\\HasNoChildren) "/" "INBOX"'])) == {}


@needs(IMAPREAD)
def test_imapread_quote_folder_keeps_the_raw_name():
    q = _i().quote_folder
    assert q("INBOX") == "INBOX" and q("[Gmail]/Spam") == "[Gmail]/Spam"
    assert q("[Gmail]/All Mail") == '"[Gmail]/All Mail"'
    z = "[Gmail]/" + mutf7("所有邮件")
    assert q(z) == z, "mUTF-7 goes as LIST gave it"
    assert q('Alle "Nachricht"') == '"Alle \\"Nachricht\\""'
    assert q("a\\b") == '"a\\\\b"'


# ------------------------------------------------------------------ plan_scan (MS 5.3, pure)

def _cursor(validity=600, last=10, last_scan_at="2026-10-30T08:00:00", role="all"):
    c = _c()
    return c.Cursor(1, c.MailboxRole(role), "[Gmail]/All Mail", validity, last, last_scan_at)


@needs(IMAPREAD)
def test_imapread_plan_scan_cases():
    I = _i()
    p = I.plan_scan(None, 600, 1, "2026-08-01T00:00:00", NOW)
    assert (p.kind, p.search, p.after_uid, p.validity, p.from_smallest) == \
        (I.PLAN_FIRST, ("SINCE", "31-Jul-2026"), 0, 600, True), p
    p = I.plan_scan(None, 600, 57, "2026-08-01T09:30:00", NOW)
    assert p.kind == I.PLAN_FIRST and p.search == ("SINCE", "31-Jul-2026")
    p = I.plan_scan(_cursor(last=10), 600, 15, EARLY, NOW)
    assert (p.kind, p.search, p.after_uid, p.last_uid) == (I.PLAN_RANGE, ("UID", "11:*"), 10, 10), p
    p = I.plan_scan(_cursor(last=10), 600, 11, EARLY, NOW)
    assert (p.kind, p.search) == (I.PLAN_NOTHING, ()), p
    p = I.plan_scan(_cursor(last=10), 600, 0, EARLY, NOW)             # UIDNEXT not reported
    assert p.kind == I.PLAN_RANGE and p.after_uid == 10
    p = I.plan_scan(_cursor(validity=600, last=10), 777, 3, EARLY, NOW)
    assert (p.kind, p.search, p.after_uid, p.validity, p.from_smallest) == \
        (I.PLAN_RESCAN, ("SINCE", "29-Oct-2026"), 0, 777, True), p
    p = I.plan_scan(_cursor(validity=600, last_scan_at=""), 777, 3, "2026-08-01T00:00:00", NOW)
    assert p.search == ("SINCE", "31-Jul-2026"), "no last scan: from the window"


@needs(IMAPREAD)
def test_imapread_first_sync_empty_and_non_empty():
    srv = FakeMailServer()
    with srv.patched(_i()):
        t = _transport()
        t.open()
        res = _scan(t, window="2026-08-01T00:00:00")
        assert res.headers == () and res.complete
        assert res.end_cursor.last_uid == 0 and res.end_cursor.validity == srv.box("all").validity
        assert res.end_cursor.last_scan_at == NOW
        t.close()
    srv = FakeMailServer()
    srv.deliver(_msg(1), to=("all",), when=_when(2026, 7, 1))             # before the window
    srv.deliver(_msg(2), to=("all",), when=_when(2026, 9, 1))
    srv.deliver(_msg(3), to=("all",), when=_when(2026, 6, 1))             # moved in later, old date
    srv.deliver(_msg(4), to=("all",), when=_when(2026, 10, 1))
    with srv.patched(_i()):
        t = _transport()
        t.open()
        res = _scan(t, window="2026-08-01T00:00:00")
        t.close()
    assert _uids(res) == [2, 3, 4], "from the smallest SINCE hit, every UID; the gate drops old ones"
    assert res.complete and res.end_cursor.last_uid == 4
    assert [h.cursor_after.last_uid for h in res.headers] == [2, 3, 4]
    assert ("UID SEARCH", "SINCE", "31-Jul-2026") in srv.log
    assert ("UID SEARCH", "UID", "2:*") in srv.log


@needs(IMAPREAD)
def test_imapread_resume_and_the_star_gotcha():
    srv = FakeMailServer()
    for n in range(3):
        srv.deliver(_msg(n), to=("all",))
    with srv.patched(_i()):
        t = _transport()
        t.open()
        first = _scan(t)
        assert _uids(first) == [1, 2, 3] and first.end_cursor.last_uid == 3
        assert _uids(_scan(t, cursor=first.end_cursor)) == [], "nothing new"
        n_before = len(srv.commands("UID SEARCH"))
        _scan(t, cursor=first.end_cursor)
        assert len(srv.commands("UID SEARCH")) == n_before, "UIDNEXT says nothing new: no SEARCH"
        gone = srv.deliver(_msg(9), to=("all",))
        srv.delete(gone)                                  # UIDNEXT 5, highest UID 3
        res = _scan(t, cursor=first.end_cursor)
        assert ("UID SEARCH", "UID", "4:*") in srv.log
        assert res.headers == (), "`4:*` matches UID 3; it must be dropped"
        assert res.complete and res.end_cursor.last_uid == 4, "end = max(last, UIDNEXT - 1)"
        srv.deliver(_msg(10), to=("all",))
        srv.deliver(_msg(11), to=("all",))
        res2 = _scan(t, cursor=res.end_cursor)
        assert _uids(res2) == [5, 6] and res2.end_cursor.last_uid == 6
        t.close()
    _assert_read_only(srv)


@needs(IMAPREAD)
def test_imapread_the_cap_leaves_no_end_cursor_and_resumes_from_the_last_header():
    srv = FakeMailServer()
    for n in range(5):
        srv.deliver(_msg(n), to=("all",))
    with srv.patched(_i()):
        t = _transport()
        t.open()
        r1 = _scan(t, limit=2)
        assert _uids(r1) == [1, 2] and r1.complete is False and r1.end_cursor is None
        r2 = _scan(t, cursor=r1.headers[-1].cursor_after, limit=2)
        assert _uids(r2) == [3, 4] and r2.end_cursor is None
        r3 = _scan(t, cursor=r2.headers[-1].cursor_after, limit=2)
        assert _uids(r3) == [5] and r3.complete and r3.end_cursor.last_uid == 5
        t.close()


@needs(IMAPREAD)
def test_imapread_fetches_headers_in_chunks():
    I = _i()
    srv = FakeMailServer()
    for n in range(I.FETCH_CHUNK + 20):
        srv.deliver(_msg(n), to=("all",))
    with srv.patched(I):
        t = _transport()
        t.open()
        res = _scan(t)
        t.close()
    assert _uids(res) == list(range(1, I.FETCH_CHUNK + 21))
    sets = [str(c[1]) for c in srv.commands("UID FETCH")]
    assert len(sets) == 2 and all(len(s.split(",")) <= I.FETCH_CHUNK for s in sets), sets


@needs(IMAPREAD)
def test_imapread_uidvalidity_change_between_sessions_rescans():
    srv = FakeMailServer()
    old = [srv.deliver(_msg(n), to=("all",), when=_when(2026, 10, 1 + n)) for n in range(3)]
    with srv.patched(_i()):
        t = _transport()
        t.open()
        first = _scan(t, now="2026-10-02T12:00:00")
        t.close()
        new_validity = srv.change_validity("all")
        fresh = srv.deliver(_msg(7), to=("all",), when=_when(2026, 10, 20))
        t = _transport()
        t.open()
        res = _scan(t, cursor=first.end_cursor)
        assert ("UID SEARCH", "SINCE", "01-Oct-2026") in srv.log
        got = {h.gm_msgid: h.ref.uid for h in res.headers}
        assert str(fresh) in got and set(map(str, old[1:])) <= set(got), got
        assert all(h.ref.validity == new_validity for h in res.headers)
        assert res.end_cursor.validity == new_validity and res.end_cursor.last_uid == 4
        assert t.fetch_body(first.headers[0].ref, 5_000_000) is None, "an old-validity UID names nothing"
        t.close()


# ------------------------------------------------------------------ headers and auth (MS 3, 5.3)

@needs(IMAPREAD)
def test_imapread_parse_header_decodes_names_subject_labels_and_dates():
    I, c = _i(), _c()
    subj = base64.b64encode("Your application – Graduate Analyst".encode()).decode()
    raw = ("From: =?UTF-8?Q?Jos=C3=A9_at_Northwind?= <Talent@Mail.Northwind.Example>\r\n"
           "Reply-To: a@northwind.example, b@hr.northwind.example, c@contoso.example\r\n"
           f"Subject: =?UTF-8?B?{subj}?=\r\n  (R0012345)\r\n"
           "Date: Mon, 26 Oct 2026 09:00:00 +0000\r\n"
           "List-ID: <updates.northwind.example>\r\nPrecedence: Bulk\r\n"
           "Auto-Submitted: Auto-Generated\r\nX-Autoreply: yes\r\n\r\n").encode()
    meta = (b'7 (X-GM-THRID 1800000000000000777 X-GM-MSGID 1800000000000000778 '
            b'X-GM-LABELS (\\Inbox "Job search" "\\\\Important") UID 42 '
            b'INTERNALDATE "26-Oct-2026 17:30:05 +0800" RFC822.SIZE 4321 '
            b'BODY[HEADER.FIELDS (FROM)] {10}')
    ref = c.MessageRef(c.MailboxRole.ALL, "[Gmail]/All Mail", 600, 42)
    base = c.Cursor(3, c.MailboxRole.ALL, "[Gmail]/All Mail", 600, 41, "2026-10-30T08:00:00")
    h = I.parse_header(meta, raw, ref, base)
    assert (h.gm_msgid, h.gm_thrid) == ("1800000000000000778", "1800000000000000777")
    assert h.labels == ("\\Inbox", "Job search", "\\Important"), h.labels
    assert h.received_at == "2026-10-26T09:30:05" and h.size == 4321
    assert (h.from_addr, h.from_domain, h.from_reg, h.from_local) == \
        ("talent@mail.northwind.example", "mail.northwind.example", "northwind.example", "talent")
    assert h.from_name == "José at Northwind", h.from_name
    assert h.reply_to_regs == ("northwind.example", "contoso.example"), h.reply_to_regs
    assert h.subject == "Your application – Graduate Analyst (R0012345)", h.subject
    assert h.list_id and h.precedence == "bulk" and h.auto_submitted == "auto-generated"
    assert h.autoreply_header and h.auth == c.AuthResult.NONE
    assert h.ref == ref and h.cursor_after == c.Cursor(3, c.MailboxRole.ALL, "[Gmail]/All Mail",
                                                       600, 42, "2026-10-30T08:00:00")
    bare = I.parse_header(b'1 (UID 5 BODY[HEADER] {3}', b"From: x@example.org\r\n\r\n", ref, base)
    assert bare.subject == "" and not bare.list_id and bare.precedence == "" and bare.labels == ()
    assert not bare.autoreply_header and bare.reply_to_regs == ()


_G = "mx.google.com; "
_AUTH = [
    # (headers top to bottom, from_reg, expected)
    ([_G + "dkim=pass header.i=@example.com; spf=pass smtp.mailfrom=example.com; "
      "dmarc=pass (p=REJECT sp=REJECT dis=NONE) header.from=example.com"], "example.com", "pass"),
    ([_G + "dkim=pass header.i=@example.com; dmarc=fail (p=QUARANTINE dis=QUARANTINE) "
      "header.from=example.com"], "example.com", "fail"),
    ([_G + "dkim=pass header.d=mail.example.com header.s=s1; spf=neutral"], "example.com", "pass"),
    ([_G + "dkim=pass header.i=@hr.example.com; dmarc=none"], "example.com", "pass"),
    ([_G + "dkim=pass header.i=@sendgrid.example.net; spf=pass smtp.mailfrom=bounce.example.net"],
     "example.com", "none"),
    ([_G + "spf=pass smtp.mailfrom=example.com"], "example.com", "none"),
    ([_G + "dmarc=temperror header.from=example.com"], "example.com", "none"),
    ([], "example.com", "none"),
    (["mail.example.com; dmarc=pass header.from=example.com"], "example.com", "none"),
    ([_G + "dkim=fail header.i=@example.com; dmarc=fail header.from=example.com",
      _G + "dmarc=pass header.from=example.com"], "example.com", "fail"),       # forged, below Gmail's
    ([_G + "arc=pass (i=1 spf=pass spfdomain=example.com dkim=pass dkdomain=example.com "
      "dmarc=pass fromdomain=example.com); spf=softfail smtp.mailfrom=lists.example.org"],
     "example.com", "none"),                                                   # dmarc only in a comment
    (["MX.GOOGLE.COM;\r\n       DKIM=PASS header.i=@example.com;\r\n       DMARC=PASS"],
     "example.com", "pass"),
]


@needs(IMAPREAD)
def test_imapread_auth_result_reads_only_gmails_own_verdict():
    I, c = _i(), _c()
    for values, reg, want in _AUTH:
        assert I.auth_result(values, reg) == c.AuthResult(want), (values, want)


# ------------------------------------------------------------------ bodies (MS 3, 5.4, 5.6)

def _qp(text_qp: str, ctype="text/plain") -> bytes:
    return ("From: Northwind <talent@northwind.example>\r\nSubject: s\r\n"
            "Date: Mon, 26 Oct 2026 09:00:00 +0000\r\nMIME-Version: 1.0\r\n"
            f'Content-Type: {ctype}; charset="utf-8"\r\nContent-Transfer-Encoding: quoted-printable\r\n\r\n'
            + text_qp).encode()


@needs(IMAPREAD)
def test_imapread_body_text_hides_every_url():
    I = _i()
    frm = "Northwind <talent@northwind.example>"
    cases = [
        (make_eml(frm, "s", "Start: https://assess.example.net/t/abc?u=1&v=2 now"), "Start: [link] now"),
        (make_eml(frm, "s", "HTTPS://Assess.Example.Net/T and http://example.org/x"), "[link] and [link]"),
        (make_eml(frm, "s", "Visit www.example.net/careers today."), "Visit [link] today."),
        (make_eml(frm, "s", "See <https://example.net/a> now"), "See <[link]> now"),
        (make_eml(frm, "s", '<p>Go: <a href="https://assess.example.net/t/abc">'
                             'https://assess.example.net/t/abc</a></p>', html=True), "Go: [link]"),
        (make_eml(frm, "s", '<p><a href="https://assess.example.net/secret-token">Start the test</a></p>',
                  html=True), "Start the test"),
        (make_eml(frm, "s", "<p>https://example.net/very<wbr>long/path ok</p>", html=True), "[link] ok"),
        (make_eml(frm, "s", "<p>&#104;ttps://example.net/x?t=1 ok</p>", html=True), "[link] ok"),
        (_qp("Open https://assess.example.net/invite/abcdefghij=\r\nklmnop?x=3D1 to begin."),
         "Open [link] to begin."),
        (_qp('<p>Open <a href=3D"https://example.net/a">https://example.net/a=\r\nbcdef</a> now</p>',
             "text/html"), "Open [link] now"),
    ]
    for raw, want in cases:
        body = I.parse_body(raw)
        assert " ".join(body.text.split()) == want, (want, body.text)
        assert not re.search(r"(?i)https?:|www\.|secret-token|klmnop|bcdef", body.text), body.text
        text, links = I.body_text(email.message_from_bytes(raw, policy=email.policy.default),
                                  links=False)
        assert links == [] and text == body.text, (links, text)


@needs(IMAPREAD)
def test_imapread_a_url_keeps_the_sentence_punctuation_after_it():
    """DEFECT pin (LOW, lane I): URL_RE takes a sentence's closing ".", "," or "!" into the
    URL, so "[link]" eats it and two sentences run together. The classifier's quote is then
    the sentence around the hit plus the next one (MS 6.3 quote <= one sentence). apply/mail
    already strips that punctuation from the links it lists (rstrip(".,;:!?"))."""
    I = _i()
    frm = "Northwind <talent@northwind.example>"
    for text, want in (("Start here: https://assess.example.net/t/abc. We regret nothing.",
                        "Start here: [link]. We regret nothing."),
                       ("Open https://example.net/a, then sign in.", "Open [link], then sign in."),
                       ("See www.example.net/careers! Thanks.", "See [link]! Thanks.")):
        got = " ".join(I.parse_body(make_eml(frm, "s", text)).text.split())
        assert got == want, (want, got)


@needs(IMAPREAD)
def test_imapread_calendar_flag_needs_a_request():
    I = _i()
    frm = "Northwind <talent@northwind.example>"
    assert I.parse_body(make_eml(frm, "Interview", "Join us.", calendar=True)).calendar_request
    assert not I.parse_body(make_eml(frm, "Interview", "Join us.")).calendar_request
    cancel = make_eml(frm, "Interview", "Join us.", calendar=True).replace(
        b"method=REQUEST", b"method=CANCEL").replace(b"METHOD:REQUEST", b"METHOD:CANCEL")
    assert not I.parse_body(cancel).calendar_request
    noparam = make_eml(frm, "Interview", "Join us.", calendar=True).replace(b"; method=REQUEST", b"")
    assert I.parse_body(noparam).calendar_request, "METHOD:REQUEST in the part counts too"


# ------------------------------------------------------------------ the golden set end to end

@needs(IMAPREAD, "jobscraper.mailstatus.rules")
def test_imapread_golden_set_through_the_transport_classifies_as_expected():
    """Each golden .eml delivered to the fake Gmail, read by ImapTransport, gives the reference
    MailHeader fields, Gmail's auth verdict, a URL-free body and the golden gate/category."""
    from jobscraper.mailstatus import rules as R
    c = _c()
    rules_obj = R.load_rules(RULES_MIN)
    srv = _golden_server()
    by_id = {str(case["gm_msgid"]): case for case in golden_cases()}
    wrong = []
    with srv.patched(_i()):
        t = _transport()
        t.open()
        heads = list(_scan(t, "all").headers) + list(_scan(t, "junk").headers)
        bodies = {h.gm_msgid: t.fetch_body(h.ref, 5_000_000) for h in heads}
        t.close()
    assert sorted(by_id) == sorted(h.gm_msgid for h in heads)
    window = golden()["context"]["window_start"]
    for h in heads:
        case = by_id[h.gm_msgid]
        ref = header_from_eml(eml(case["file"]), gm_msgid=case["gm_msgid"], gm_thrid=case["gm_thrid"],
                              labels=case.get("labels") or (), auth=case["auth"])
        for f in ("gm_thrid", "labels", "received_at", "size", "from_addr", "from_name", "from_domain",
                  "from_reg", "from_local", "reply_to_regs", "list_id", "precedence", "auto_submitted",
                  "autoreply_header", "auth"):
            if getattr(h, f) != getattr(ref, f):
                wrong.append(f"{case['file']}: {f} {getattr(h, f)!r} != {getattr(ref, f)!r}")
        if " ".join(h.subject.split()) != " ".join(ref.subject.split()):
            wrong.append(f"{case['file']}: subject {h.subject!r}")
        body = bodies[h.gm_msgid]
        if re.search(r"(?i)https?://|www\.", body.text):
            wrong.append(f"{case['file']}: a URL left in the body")
        exp = case["expect"]
        got = R.header_gate(h, rules_obj, own=golden_own(), window_start=window,
                            threads=golden_threads(), employer_regs=golden_employer_regs())
        gate = ("header", got) if got else None
        if gate is None:
            got = R.content_gate(h, body, rules_obj, in_matched_thread=h.gm_thrid in golden_threads())
            gate = ("content", got) if got else None
        want = (exp["skip"]["gate"], c.Reason(exp["skip"]["reason"])) if exp["skip"] else None
        if gate != want:
            wrong.append(f"{case['file']}: gate {gate} != {want}")
            continue
        if not want:
            v = R.classify(h, body, rules_obj)
            if (v.category.value, v.status_words) != (exp["category"], exp["status_words"]):
                wrong.append(f"{case['file']}: {v.category.value}/{v.status_words} != "
                             f"{exp['category']}/{exp['status_words']}")
    assert not wrong, f"{len(wrong)} differences:\n  " + "\n  ".join(wrong)


# ------------------------------------------------------------------ failures (MS 12, 13)

@needs(IMAPREAD)
def test_imapread_login_code_maps_gmail_texts():
    I, c = _i(), _c()
    for text, want in GMAIL_LOGIN_ERRORS.items():
        for exc in (imaplib.IMAP4.error(text), imaplib.IMAP4.error(text.encode())):
            assert I.login_code(exc) == c.SyncCode(want), (text, I.login_code(exc))
    assert I.login_code(imaplib.IMAP4.error(LOGIN_ERROR_ECHOING_USER)) == c.SyncCode.LOGIN_REFUSED
    for exc in (imaplib.IMAP4.abort("socket error: EOF"), ConnectionResetError("reset"),
                socket.timeout("timed out"), ssl.SSLError("bad record mac"), EOFError()):
        assert I.login_code(exc) == c.SyncCode.NETWORK, exc
    assert I.login_code(imaplib.IMAP4.error("[CLIENTBUG] Something new")) == c.SyncCode.LOGIN_REFUSED
    assert I.login_code(c.MailFailure(c.SyncCode.VAULT_ERROR)) == c.SyncCode.VAULT_ERROR
    assert I.login_code(ValueError("x")) == c.SyncCode.INTERNAL
    assert all(isinstance(I.login_code(imaplib.IMAP4.error(t)), c.SyncCode) for t in GMAIL_LOGIN_ERRORS)


def _open_fails(srv):
    c = _c()
    with srv.patched(_i()):
        try:
            _transport().open()
        except c.MailFailure as e:
            return e
    raise AssertionError("open() should have failed")


@needs(IMAPREAD)
def test_imapread_open_failures_carry_a_code_and_never_server_text():
    c = _c()
    for text, want in list(GMAIL_LOGIN_ERRORS.items()) + [(LOGIN_ERROR_ECHOING_USER, "login_refused")]:
        srv = FakeMailServer()
        srv.login_error = text
        e = _open_fails(srv)
        assert e.code == c.SyncCode(want), (text, e.code)
        said = f"{e} {e.detail} {e.args}"
        for leak in ("canary", "Invalid", "ALERT", "support.google", "Too many", USER):
            assert leak not in said, (leak, said)
        assert re.fullmatch(r"\w*", e.detail), e.detail
        assert srv.verbs()[-1] == "LOGOUT", "the refused connection is closed"
    for err in (ConnectionRefusedError("refused"), socket.timeout("timed out"),
                ssl.SSLError("handshake"), imaplib.IMAP4.error("greeting refused")):
        srv = FakeMailServer()
        srv.connect_error = err
        assert _open_fails(srv).code == c.SyncCode.NETWORK, err
    srv = FakeMailServer(capabilities=PLAIN_CAPABILITIES)
    assert _open_fails(srv).code == c.SyncCode.NOT_GMAIL
    assert srv.verbs()[-1] == "LOGOUT"
    t = _transport()
    assert USER not in repr(t) and "synthetic-app-password" not in repr(vars(t))
    try:
        _i().ImapTransport("imap.gmail.com", 993, USER, "plain-text")
    except TypeError:
        pass
    else:
        raise AssertionError("a plain-str password must be refused")


@needs(IMAPREAD)
def test_imapread_a_dropped_or_throttled_connection_mid_scan():
    c = _c()
    for drop, want in ((lambda: imaplib.IMAP4.abort("socket error: EOF"), c.SyncCode.NETWORK),
                       (lambda: imaplib.IMAP4.abort("[THROTTLED] Account exceeded command or "
                                                    "bandwidth limits. (Failure)"), c.SyncCode.RATE_LIMITED)):
        srv = FakeMailServer()
        for n in range(3):
            srv.deliver(_msg(n), to=("all",))
        srv.drop_error = drop
        with srv.patched(_i()):
            t = _transport()
            t.open()
            srv.drop_after = 5                            # LOGIN, CAPABILITY, LIST, EXAMINE, SEARCH
            try:
                _scan(t)
            except c.MailFailure as e:
                assert e.code == want and re.fullmatch(r"\w*", e.detail), (e.code, e.detail)
            else:
                raise AssertionError("the drop must surface as a MailFailure")
            t.close()


# ------------------------------------------------------------------ fetch_body and refind (MS 5.4, 5.5)

@needs(IMAPREAD)
def test_imapread_fetch_body_sizes_first_and_handles_gone_mail():
    I = _i()
    srv = FakeMailServer()
    big = make_eml("Northwind <talent@northwind.example>", "Big", "x" * 5000)
    srv.deliver(_msg(1), to=("all",))
    srv.deliver(big, to=("all",))
    gone = srv.deliver(_msg(3), to=("all",))
    srv.deliver(_msg(4), to=("junk",))
    with srv.patched(I):
        t = _transport()
        t.open()
        heads = _scan(t).headers
        junk = _scan(t, "junk").headers
        n_peek = sum("BODY.PEEK[]" in x for x in _fetch_items(srv))
        b = t.fetch_body(heads[1].ref, 1000)
        assert (b.text, b.truncated) == ("", True)
        assert sum("BODY.PEEK[]" in x for x in _fetch_items(srv)) == n_peek, "too big: no body fetch"
        srv.delete(gone)
        assert t.fetch_body(heads[2].ref, 5_000_000) is None
        ok = t.fetch_body(heads[0].ref, 5_000_000)        # All Mail again, after Spam was open
        assert "Body 1." in ok.text and not ok.truncated
        assert srv.commands("EXAMINE")[-1][1] == '"[Gmail]/All Mail"'
        assert "Body 4." in t.fetch_body(junk[0].ref, 5_000_000).text
        t.close()
    _assert_read_only(srv)


@needs(IMAPREAD)
def test_imapread_refind_searches_all_mail_then_spam():
    c = _c()
    srv = FakeMailServer()
    in_all = srv.deliver(_msg(1), to=("all",))
    spam = srv.deliver(_msg(2), to=("junk",))
    rescued = srv.deliver(_msg(3), to=("junk",))
    with srv.patched(_i()):
        t = _transport()
        t.open()
        h = t.refind(str(in_all))
        assert h.ref.role == c.MailboxRole.ALL and h.gm_msgid == str(in_all)
        h = t.refind(str(spam))
        assert h.ref.role == c.MailboxRole.JUNK and h.ref.mailbox == "[Gmail]/Spam"
        searched = [x[1:] for x in srv.commands("UID SEARCH")]
        assert searched[-2:] == [("X-GM-MSGID", str(spam))] * 2, searched
        new_uid = srv.move(rescued, "junk", "all")        # "Not spam": a new UID in All Mail
        h = t.refind(str(rescued))
        assert (h.ref.role, h.ref.uid) == (c.MailboxRole.ALL, new_uid)
        srv.delete(in_all)
        assert t.refind(str(in_all)) is None
        n = len(srv.log)
        assert t.refind("not-a-number") is None and t.refind("") is None
        assert len(srv.log) == n, "a bad id sends nothing"
        t.close()
    srv = FakeMailServer("all_hidden")
    mid = srv.deliver(_msg(5), to=("inbox",))
    with srv.patched(_i()):
        t = _transport()
        t.open()
        assert t.refind(str(mid)).ref.role == c.MailboxRole.INBOX
        t.close()
    _assert_read_only(srv)


def test_imapread_oracles_are_live():
    assert_live(IMAPREAD, _W0, "test_imapread")


note_waiting("test_imapread", _W0)
