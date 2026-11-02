"""Shared helpers for the F-50 mail-status oracles (not a test file: the runner ignores it).

mail_status_design.md (MS) sections 5, 6, 13 and 16; build plan WP-T1. Test files do
`sys.path.insert(0, str(Path(__file__).parent))` then `from mail_support import ...`.

What is here:
  - `needs` / `WAITING` / `missing` (re-exported from apply_support): skip-clean gating.
  - The golden set: `golden()`, `eml()`, `golden_header()`, `golden_body()`, `golden_apps()`,
    `golden_policy_raw()`; the files are tests/fixtures/mail/golden/*.eml + golden.yaml.
  - Reference parsers that need no src code: `reg_domain`, `auth_result`, `body_text`,
    `URL_RE`, `mutf7`. The transport (imapread) must agree with them on the golden set.
  - `FakeMailServer`: a Gmail-shaped IMAP server patchable as the `imaplib.IMAP4_SSL` factory.
    It speaks LOGIN, CAPABILITY, LIST (special-use flags; localised, mUTF-7 and hidden-\\All
    layouts), SELECT/EXAMINE (UIDVALIDITY, UIDNEXT), STATUS, UID SEARCH (UID n:* with the RFC
    "* is the highest" rule, SINCE, BEFORE, X-GM-MSGID, ALL), UID FETCH (UID, FLAGS,
    INTERNALDATE, RFC822.SIZE, X-GM-MSGID, X-GM-THRID, X-GM-LABELS, BODY.PEEK[...] incl.
    HEADER.FIELDS and partials), plain SEARCH/FETCH (apply/mail.py), NOOP, CLOSE and LOGOUT.
    It records every command (never a password), refuses every mailbox write (STORE, COPY,
    MOVE, EXPUNGE, APPEND, CREATE/DELETE/RENAME, UID STORE ...) with an AssertionError after
    logging it, marks a message \\Seen when fetched without PEEK (and logs a violation), fails
    a login with each Gmail error text, drops the connection after N commands, changes
    UIDVALIDITY between sessions, moves a message Spam -> All Mail keeping X-GM-MSGID, deletes
    one (vanished), and blocks real sockets while patched.

ASSUMED (MS leaves these to the transport): imapread reaches IMAP through
`imaplib.IMAP4_SSL(host, port, ...)` looked up per call (or a module-level `IMAP4_SSL`
name, which `patched` also replaces), reads UIDVALIDITY/UIDNEXT from `untagged_responses` /
`response()` after `select(name, readonly=True)` or from STATUS, and sends UID commands with
`conn.uid("SEARCH"|"FETCH", ...)`.
"""
from __future__ import annotations

import base64
import contextlib
import email
import imaplib
import re
import socket
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from email import policy
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable, Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import ROOT, WAITING, missing, needs  # noqa: E402,F401

MAIL = ROOT / "tests" / "fixtures" / "mail"
GOLDEN_DIR = MAIL / "golden"
GOLDEN_YAML = MAIL / "golden.yaml"
RULES_MIN = MAIL / "rules_min.yaml"
REAL_RULES = ROOT / "config" / "mail_rules.yaml"
DESIGN = ROOT / "docs" / "architecture" / "mail_status_design.md"
TIME_FMT = "%Y-%m-%dT%H:%M:%S"
GMAIL_HOST, GMAIL_PORT = "imap.gmail.com", 993

CONTRACTS = "jobscraper.mailstatus.contracts"
RULES = "jobscraper.mailstatus.rules"
MATCH = "jobscraper.mailstatus.match"
TRANSITION = "jobscraper.mailstatus.transition"
MODEL = "jobscraper.mailstatus.model"


# ------------------------------------------------------------------ the golden set

_GOLDEN: Optional[dict] = None


def golden() -> dict:
    global _GOLDEN
    if _GOLDEN is None:
        _GOLDEN = yaml.safe_load(GOLDEN_YAML.read_text(encoding="utf-8"))
    return _GOLDEN


def golden_cases() -> list[dict]:
    return list(golden()["cases"])


def golden_case(file: str) -> dict:
    for c in golden_cases():
        if c["file"] == file:
            return c
    raise KeyError(file)


def eml(name: str) -> bytes:
    """The raw bytes of a golden message (`name` with or without `.eml`)."""
    return (GOLDEN_DIR / (name if name.endswith(".eml") else name + ".eml")).read_bytes()


def message(raw: bytes) -> email.message.EmailMessage:
    return email.message_from_bytes(raw, policy=policy.default)


def golden_policy_raw() -> dict:
    """The `mail_status` block for `transition.build_policy(statuses, raw)`."""
    return dict(golden()["context"]["mail_status"])


def golden_statuses() -> tuple[str, ...]:
    return tuple(golden()["context"]["statuses"])


def golden_own() -> frozenset[str]:
    return frozenset(a.lower() for a in golden()["context"]["own"])


def golden_threads() -> frozenset[str]:
    """Every gm_thrid already matched to an application (the header gate's `threads`)."""
    return frozenset(t for a in golden()["apps"] for t in a.get("threads", []))


def golden_employer_regs() -> frozenset[str]:
    return frozenset(d for a in golden()["apps"] for d in a.get("employer_domains", []))


def design_contracts():
    """MS section 3's python listing executed as a module: the contract values (enums, reason
    sets) for checks that must run before src/jobscraper/mailstatus/contracts.py exists."""
    import types
    name = "_ms3_contracts_listing"
    if name not in sys.modules:
        text = DESIGN.read_text(encoding="utf-8")
        block = re.search(r"```python\n(.*?)\n```", text[text.index("## 3. Contracts"):], re.S)
        mod = types.ModuleType(name)
        sys.modules[name] = mod
        exec(compile(block.group(1) + "\n", "mail_status_design.md#3", "exec"), mod.__dict__)
    return sys.modules[name]


# ------------------------------------------------------------------ reference parsers

URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"')\]]+")
_SLD = {"com", "co", "gov", "edu", "org", "net", "ac", "mil"}


def reg_domain(host: str) -> str:
    """Registrable domain, the same rule as apply/mail.employer_domain: the last two labels,
    or three under a two-letter ccTLD with a generic second level (`x.gov.sg`)."""
    labels = (host or "").strip().lower().rstrip(".").split(".")
    if len(labels) >= 3 and labels[-2] in _SLD and len(labels[-1]) == 2 and labels[-1].isalpha():
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def auth_result(msg: email.message.Message) -> str:
    """MS 3 AuthResult from Gmail's own Authentication-Results (mx.google.com) header:
    'pass' for dmarc=pass, or dkim=pass with d= aligned (same registrable domain) to the From
    domain; 'fail' for dmarc=fail; 'none' otherwise."""
    frm = msg.get("From")
    addrs = getattr(frm, "addresses", ()) if frm is not None else ()
    from_dom = addrs[0].domain.lower() if addrs else ""
    verdict = "none"
    for value in msg.get_all("Authentication-Results", []) or []:
        v = " ".join(str(value).split())
        if not v.lower().startswith("mx.google.com"):
            continue
        dmarc = re.search(r"\bdmarc=(\w+)", v, re.I)
        if dmarc and dmarc.group(1).lower() == "pass":
            return "pass"
        if dmarc and dmarc.group(1).lower() == "fail":
            return "fail"
        for m in re.finditer(r"\bdkim=pass\b[^;]*?\bheader\.(?:i=@?|d=)([\w.-]+)", v, re.I):
            if from_dom and reg_domain(m.group(1)) == reg_domain(from_dom):
                verdict = "pass"
    return verdict


class _Text(HTMLParser):
    BLOCK = {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def body_text(msg: email.message.EmailMessage) -> tuple[str, bool]:
    """(text, calendar_request): text/plain if present, else HTML as text; every URL is
    replaced by "[link]" (MS 3 MailBody, 5.6). A text/calendar part with METHOD:REQUEST
    sets the flag."""
    plain = html = None
    calendar = False
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        if ctype == "text/calendar":
            content = part.get_content()
            if re.search(r"(?im)^METHOD:REQUEST\s*$", content) or \
                    (part.get_param("method") or "").upper() == "REQUEST":
                calendar = True
        elif ctype == "text/plain" and plain is None:
            plain = part.get_content()
        elif ctype == "text/html" and html is None:
            html = part.get_content()
    if plain is None and html is not None:
        p = _Text()
        p.feed(html)
        plain = re.sub(r"\n\s*\n+", "\n\n", "".join(p.parts)).strip() + "\n"
    return URL_RE.sub("[link]", plain or ""), calendar


def mutf7(s: str) -> str:
    """RFC 3501 modified UTF-7, as Gmail lists localised folder names."""
    out: list[str] = []
    buf: list[str] = []

    def flush():
        if buf:
            b = "".join(buf).encode("utf-16-be")
            out.append("&" + base64.b64encode(b).decode().rstrip("=").replace("/", ",") + "-")
            buf.clear()
    for ch in s:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def to_utc_text(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(TIME_FMT)


# ------------------------------------------------------------------ contract builders

def _contracts():
    import importlib
    return importlib.import_module(CONTRACTS)


def header_from_eml(raw: bytes, *, role: str = "all", mailbox: Optional[str] = None,
                    validity: int = 1, uid: int = 1, gm_msgid: str = "1", gm_thrid: str = "1",
                    labels: Iterable[str] = (), account_id: int = 1, last_scan_at: str = "",
                    auth: Optional[str] = None, received_at: Optional[str] = None):
    """A contracts.MailHeader built from a raw message the way MS 3 describes the fields.
    `auth` defaults to the reference parser; `received_at` to the Date header (UTC)."""
    c = _contracts()
    msg = message(raw)
    frm = msg["From"]
    a = frm.addresses[0]
    from_addr = f"{a.username}@{a.domain}".lower()
    reply = msg.get("Reply-To")
    reply_regs = tuple(reg_domain(x.domain) for x in (reply.addresses if reply is not None else ()))
    role_e = c.MailboxRole(role)
    name = mailbox or {"all": "[Gmail]/All Mail", "junk": "[Gmail]/Spam", "inbox": "INBOX"}[role]
    when = received_at or to_utc_text(parsedate_to_datetime(str(msg["Date"])))
    ref = c.MessageRef(role_e, name, validity, uid)
    return c.MailHeader(
        ref=ref, gm_msgid=str(gm_msgid), gm_thrid=str(gm_thrid), labels=tuple(labels),
        received_at=when, size=len(raw), from_addr=from_addr, from_name=a.display_name or "",
        from_domain=a.domain.lower(), from_reg=reg_domain(a.domain), from_local=a.username.lower(),
        reply_to_regs=reply_regs, subject=str(msg.get("Subject", "")),
        list_id="List-ID" in msg, precedence=str(msg.get("Precedence", "")).strip().lower(),
        auto_submitted=str(msg.get("Auto-Submitted", "")).strip().lower(),
        autoreply_header=("X-Autoreply" in msg or "X-Autorespond" in msg),
        auth=c.AuthResult(auth or auth_result(msg)),
        cursor_after=c.Cursor(account_id, role_e, name, validity, uid, last_scan_at))


def body_from_eml(raw: bytes, max_bytes: Optional[int] = None):
    """A contracts.MailBody: "" and truncated=True when the message is over `max_bytes`."""
    c = _contracts()
    if max_bytes is not None and len(raw) > max_bytes:
        return c.MailBody("", False, truncated=True)
    text, cal = body_text(message(raw))
    return c.MailBody(text, cal)


def golden_header(case: dict, uid: Optional[int] = None):
    """The MailHeader of a golden case, as the transport would give it."""
    n = golden_cases().index(case) + 1 if uid is None else uid
    return header_from_eml(eml(case["file"]), role=case.get("folder", "all"), uid=n,
                           gm_msgid=case["gm_msgid"], gm_thrid=case["gm_thrid"],
                           labels=case.get("labels") or (), auth=case["auth"])


def golden_body(case: dict):
    return body_from_eml(eml(case["file"]))


def app_candidate(d: dict, tenants_fn: Optional[Callable[[Iterable[str]], tuple]] = None):
    """A contracts.AppCandidate from a golden/test dict. `tenant_hosts` become `tenants`
    through `tenants_fn` (match.tenants_from_hosts bound to the rules, E1); a dict may give
    `tenants` directly instead."""
    c = _contracts()
    if "tenants" in d:
        tenants = tuple(d["tenants"])
    else:
        tenants = tuple(tenants_fn(d.get("tenant_hosts", ()))) if tenants_fn else ()
    return c.AppCandidate(
        job_id=d["job_id"], status=d["status"], company_names=tuple(d.get("company_names", ())),
        role=d.get("role", ""), employer_domains=tuple(d.get("employer_domains", ())),
        tenants=tenants, board_slugs=tuple(d.get("board_slugs", ())),
        req_ids=tuple(d.get("req_ids", ())), threads=tuple(d.get("threads", ())),
        owner_changed_at=d.get("owner_changed_at"), last_event_at=d.get("last_event_at"))


def golden_apps(tenants_fn=None) -> tuple:
    return tuple(app_candidate(a, tenants_fn) for a in golden()["apps"])


# ------------------------------------------------------------------ the fake IMAP server

GMAIL_CAPABILITIES = ("IMAP4REV1", "UNSELECT", "IDLE", "NAMESPACE", "QUOTA", "ID", "XLIST",
                      "CHILDREN", "X-GM-EXT-1", "UIDPLUS", "COMPRESS=DEFLATE", "ENABLE", "MOVE",
                      "CONDSTORE", "ESEARCH", "UTF8=ACCEPT", "LIST-EXTENDED", "LIST-STATUS",
                      "LITERAL-", "SPECIAL-USE", "APPENDLIMIT=35651584")
PLAIN_CAPABILITIES = ("IMAP4REV1", "IDLE", "NAMESPACE", "UIDPLUS", "SPECIAL-USE", "MOVE")

# Gmail's LOGIN failure texts -> the SyncCode value imapread.login_code must give (MS 12).
GMAIL_LOGIN_ERRORS = {
    "[AUTHENTICATIONFAILED] Invalid credentials (Failure)": "login_refused",
    "[ALERT] Application-specific password required: "
    "https://support.google.com/accounts/answer/185833 (Failure)": "app_password_required",
    "[ALERT] Please log in via your web browser: "
    "https://support.google.com/mail/accounts/answer/78754 (Failure)": "web_login_required",
    "[WEBALERT https://accounts.google.com/signin/continue?sarp=1&scc=1&plt=AKgnsbsSynthetic] "
    "Web login required.": "web_login_required",
    "[ALERT] Too many simultaneous connections. (Failure)": "rate_limited",
    "[THROTTLED] Account exceeded command or bandwidth limits. (Failure)": "rate_limited",
    "[OVERQUOTA] Account exceeded command or bandwidth limits. (Failure)": "rate_limited",
    "[UNAVAILABLE] Temporary System Error": "rate_limited",
}
# A server text that echoes the username: login_code must still return only the code.
LOGIN_ERROR_ECHOING_USER = ("[AUTHENTICATIONFAILED] Invalid credentials for "
                            "canary.user@example.com (Failure)")

_G = "[Gmail]/"
_LAYOUT_GMAIL = [
    (("\\HasNoChildren",), "INBOX", "inbox"),
    (("\\HasChildren", "\\Noselect"), "[Gmail]", None),
    (("\\All", "\\HasNoChildren"), _G + "All Mail", "all"),
    (("\\Drafts", "\\HasNoChildren"), _G + "Drafts", None),
    (("\\HasNoChildren", "\\Important"), _G + "Important", None),
    (("\\HasNoChildren", "\\Sent"), _G + "Sent Mail", None),
    (("\\HasNoChildren", "\\Junk"), _G + "Spam", "junk"),
    (("\\Flagged", "\\HasNoChildren"), _G + "Starred", None),
    (("\\HasNoChildren", "\\Trash"), _G + "Trash", None),
    (("\\HasNoChildren",), "Job search", None),
]


def _layout(kind: str) -> list[tuple[tuple[str, ...], str, Optional[str]]]:
    """LIST layouts: (flags, raw mailbox name as LIST gives it, role or None)."""
    if kind == "gmail":
        return list(_LAYOUT_GMAIL)
    if kind == "googlemail_de":                 # "[Google Mail]" prefix, German names
        g = "[Google Mail]/"
        return [(("\\HasNoChildren",), "INBOX", "inbox"),
                (("\\HasChildren", "\\Noselect"), "[Google Mail]", None),
                (("\\All", "\\HasNoChildren"), g + "Alle Nachrichten", "all"),
                (("\\HasNoChildren", "\\Sent"), g + "Gesendet", None),
                (("\\HasNoChildren", "\\Junk"), g + "Spam", "junk"),
                (("\\HasNoChildren", "\\Trash"), g + "Papierkorb", None)]
    if kind == "fr":                            # mUTF-7 in a Latin name
        return [(("\\HasNoChildren",), "INBOX", "inbox"),
                (("\\All", "\\HasNoChildren"), _G + "Tous les messages", "all"),
                (("\\HasNoChildren", "\\Sent"), _G + mutf7("Messages envoyés"), None),
                (("\\HasNoChildren", "\\Junk"), _G + "Spam", "junk")]
    if kind == "zh":                            # every system name in mUTF-7
        return [(("\\HasNoChildren",), "INBOX", "inbox"),
                (("\\All", "\\HasNoChildren"), _G + mutf7("所有邮件"), "all"),
                (("\\HasNoChildren", "\\Sent"), _G + mutf7("已发邮件"), None),
                (("\\HasNoChildren", "\\Junk"), _G + mutf7("垃圾邮件"), "junk"),
                (("\\HasNoChildren", "\\Trash"), _G + mutf7("已删除邮件"), None)]
    if kind == "all_hidden":                    # "Show in IMAP" off for All Mail
        return [e for e in _LAYOUT_GMAIL if e[2] != "all"]
    if kind == "junk_hidden":
        return [e for e in _LAYOUT_GMAIL if e[2] != "junk"]
    if kind == "plain":                         # a non-Gmail server (with \Junk, no \All)
        return [(("\\HasNoChildren",), "INBOX", "inbox"),
                (("\\HasNoChildren", "\\Junk"), "Junk", "junk"),
                (("\\HasNoChildren", "\\Sent"), "Sent", None)]
    raise ValueError(kind)


LAYOUTS = ("gmail", "googlemail_de", "fr", "zh", "all_hidden", "junk_hidden", "plain")


@dataclass
class FakeMessage:
    raw: bytes
    gm_msgid: int
    gm_thrid: int
    labels: tuple[str, ...]
    internaldate: datetime                      # aware, UTC
    flags: set = field(default_factory=set)


@dataclass
class FakeMailbox:
    name: str                                   # the raw (mUTF-7) name LIST gives
    flags: tuple[str, ...]
    role: Optional[str]
    listed: bool = True
    validity: int = 1
    next_uid: int = 1
    messages: dict = field(default_factory=dict)  # uid -> FakeMessage, ascending

    def max_uid(self) -> int:
        return max(self.messages, default=0)


_WRITE_METHODS = frozenset({"store", "copy", "move", "expunge", "append", "create", "delete",
                            "rename", "subscribe", "unsubscribe", "setacl", "deleteacl",
                            "setquota", "setannotation", "xatom", "_simple_command"})
_WRITE_UID = frozenset({"STORE", "COPY", "MOVE", "EXPUNGE"})
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _imap_date(s: str) -> date:
    s = s.strip('"')
    d, m, y = s.split("-")
    return date(int(y), _MONTHS.index(m.title()) + 1, int(d))


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()]+', text) if t not in "()"]


class FakeMailServer:
    """One Gmail account. Construct, `deliver` messages, then `with server.patched(mod):`."""

    def __init__(self, layout: str = "gmail", *, capabilities: Iterable[str] = GMAIL_CAPABILITIES,
                 validity: int = 600, password: Optional[str] = None):
        self.layout = layout
        self.capabilities = tuple(capabilities)
        self.password = password                 # None: any password is accepted
        self.login_error: Optional[str] = None   # a GMAIL_LOGIN_ERRORS key -> LOGIN fails
        self.connect_error: Optional[BaseException] = None
        self.drop_after: Optional[int] = None    # commands per connection, then abort
        self.drop_error: Callable[[], BaseException] = (
            lambda: imaplib.IMAP4.abort("socket error: EOF occurred in violation of protocol"))
        self.log: list[tuple] = []               # every command, every session: (VERB, *args)
        self.session_logs: list[list[tuple]] = []
        self.violations: list[str] = []
        self.boxes: list[FakeMailbox] = []
        all_names = {r for _f, _n, r in _layout("gmail")}
        listed_roles = {r for _f, _n, r in _layout(layout)}
        for i, (flags, name, role) in enumerate(_layout(layout)):
            self.boxes.append(FakeMailbox(name, flags, role, True, validity + i))
        for role in ("all", "junk"):             # hidden from LIST, so not selectable either
            if role in all_names and role not in listed_roles:
                self.boxes.append(FakeMailbox(f"<hidden {role}>", (), role, False, validity + 50))
        self._next_msgid = 1800000000000100001

    # ---------------------------------------------------------------- mailbox content
    def box(self, role: str) -> FakeMailbox:
        for b in self.boxes:
            if b.role == role:
                return b
        raise KeyError(role)

    def name_of(self, role: str) -> str:
        return self.box(role).name

    def deliver(self, raw: bytes, *, to: Iterable[str] = ("inbox", "all"), gm_msgid=None,
                gm_thrid=None, labels: Iterable[str] = (), when: Optional[datetime] = None) -> int:
        """Add a message to the boxes of the given roles (Gmail: an inbox message is also in
        All Mail, with its own UID there). `when` defaults to the Date header. Returns X-GM-MSGID."""
        msgid = int(gm_msgid) if gm_msgid is not None else self._next_msgid
        self._next_msgid = max(self._next_msgid, msgid) + 1
        if when is None:
            when = parsedate_to_datetime(str(message(raw)["Date"]))
        when = when.astimezone(timezone.utc)
        for role in to:
            b = self.box(role)
            b.messages[b.next_uid] = FakeMessage(raw, msgid, int(gm_thrid or msgid), tuple(labels), when)
            b.next_uid += 1
        return msgid

    def find(self, role: str, gm_msgid) -> Optional[int]:
        for uid, m in self.box(role).messages.items():
            if m.gm_msgid == int(gm_msgid):
                return uid
        return None

    def move(self, gm_msgid, src: str = "junk", dst: str = "all") -> int:
        """'Not spam': the message leaves `src` and gets a new UID in `dst`, same X-GM-MSGID."""
        s, d = self.box(src), self.box(dst)
        uid = self.find(src, gm_msgid)
        m = s.messages.pop(uid)
        d.messages[d.next_uid] = m
        d.next_uid += 1
        return d.next_uid - 1

    def delete(self, gm_msgid) -> None:
        """The owner deleted it (between header and body fetch, say): gone everywhere."""
        for b in self.boxes:
            for uid in [u for u, m in b.messages.items() if m.gm_msgid == int(gm_msgid)]:
                del b.messages[uid]

    def change_validity(self, role: str, new: Optional[int] = None) -> int:
        """A label rebuilt: new UIDVALIDITY, every message renumbered from 1 (same X-GM-MSGID)."""
        b = self.box(role)
        b.validity = new if new is not None else b.validity + 1
        msgs = [b.messages[u] for u in sorted(b.messages)]
        b.messages = {i + 1: m for i, m in enumerate(msgs)}
        b.next_uid = len(msgs) + 1
        return b.validity

    def seen(self, role: str) -> set[int]:
        return {u for u, m in self.box(role).messages.items() if "\\Seen" in m.flags}

    # ---------------------------------------------------------------- the log
    def verbs(self) -> list[str]:
        return [c[0] for c in self.log]

    def commands(self, verb: str) -> list[tuple]:
        return [c for c in self.log if c[0] == verb]

    # ---------------------------------------------------------------- the factory
    @property
    def factory(self):
        server = self

        class IMAP4_SSL(_FakeConnection):        # noqa: N801 (mirrors imaplib)
            _server = server
        return IMAP4_SSL

    @contextlib.contextmanager
    def patched(self, *modules):
        """`imaplib.IMAP4_SSL` (and any module's own `IMAP4_SSL` name) -> this server, and
        `socket.create_connection` -> an error, for the duration."""
        fake = self.factory
        saved = [(imaplib, "IMAP4_SSL", imaplib.IMAP4_SSL)]
        for m in modules:
            if m is not None and hasattr(m, "IMAP4_SSL"):
                saved.append((m, "IMAP4_SSL", getattr(m, "IMAP4_SSL")))

        def no_network(*_a, **_k):
            raise AssertionError("a test opened a real socket")
        saved.append((socket, "create_connection", socket.create_connection))
        try:
            for holder, name, _old in saved:
                setattr(holder, name, no_network if name == "create_connection" else fake)
            yield self
        finally:
            for holder, name, old in saved:
                setattr(holder, name, old)


class _FakeConnection:
    """What `imaplib.IMAP4_SSL(host, port)` returns while patched. The imaplib surface a
    read-only client uses; everything else is refused or missing."""
    _server: FakeMailServer
    error = imaplib.IMAP4.error
    abort = imaplib.IMAP4.abort
    readonly = imaplib.IMAP4.readonly

    def __init__(self, host: str = "", port: int = 993, *args, **kwargs):
        s = self._server
        s.session_logs.append([])
        self._log = s.session_logs[-1]
        self._count = 0
        self._dead = False
        self._box: Optional[FakeMailbox] = None
        self._readonly = True
        self.state = "NONAUTH"
        self.host, self.port = host, port
        self.untagged_responses: dict[str, list] = {}
        self._rec("CONNECT", host, port, kwargs.get("timeout"))
        if s.connect_error is not None:
            raise s.connect_error
        self.capabilities = tuple(c.upper() for c in s.capabilities)

    # ---------------------------------------------------------------- plumbing
    def _rec(self, verb: str, *args) -> None:
        entry = (verb, *args)
        self._server.log.append(entry)
        self._log.append(entry)

    def _cmd(self, verb: str, *args) -> None:
        """Record a command; drop the connection when the budget is spent."""
        if self._dead:
            raise imaplib.IMAP4.abort("command on a closed connection")
        lim = self._server.drop_after
        if lim is not None and self._count >= lim:
            self._dead = True
            self._rec("DROPPED", verb)
            raise self._server.drop_error()
        self._count += 1
        self._rec(verb, *args)

    def _need_selected(self, verb):
        if self._box is None:
            raise imaplib.IMAP4.error(f"command {verb} illegal in state {self.state}, "
                                      "only allowed in states SELECTED")

    def __getattr__(self, name):
        if name in _WRITE_METHODS:
            def refused(*a, **k):
                self._rec(name.upper().lstrip("_"), *a)
                self._server.violations.append(f"write command {name}")
                raise AssertionError(f"mail must be read-only: IMAP {name} called")
            return refused
        raise AttributeError(name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self.state != "LOGOUT" and not self._dead:
            self.logout()

    # ---------------------------------------------------------------- session
    def login(self, user, password):
        self._cmd("LOGIN", user)                 # the password is never recorded
        s = self._server
        if s.login_error is not None:
            raise imaplib.IMAP4.error(s.login_error.encode())
        if s.password is not None and str(password) != s.password:
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)")
        self.state = "AUTH"
        return "OK", [b"user authenticated (Success)"]

    def capability(self):
        self._cmd("CAPABILITY")
        return "OK", [" ".join(self._server.capabilities).encode()]

    def noop(self):
        self._cmd("NOOP")
        return "OK", [b"Success"]

    def logout(self):
        self._cmd("LOGOUT")
        self.state = "LOGOUT"
        self._dead = True
        return "BYE", [b"LOGOUT Requested"]

    def close(self):
        self._cmd("CLOSE")
        self._box = None
        self.state = "AUTH"
        return "OK", [b"Returned to authenticated state. (Success)"]

    def shutdown(self):
        self._dead = True

    def response(self, code):
        return code, self.untagged_responses.pop(code.upper(), [None])

    # ---------------------------------------------------------------- folders
    def list(self, directory='""', pattern="*"):
        self._cmd("LIST", directory, pattern)
        lines = []
        for b in self._server.boxes:
            if b.listed:
                lines.append(f'({" ".join(b.flags)}) "/" "{b.name}"'.encode("ascii"))
        return "OK", lines

    @staticmethod
    def _ascii(mailbox) -> str:
        raw = mailbox.decode("ascii") if isinstance(mailbox, bytes) else str(mailbox)
        raw.encode("ascii")      # imaplib encodes arguments as ASCII: a decoded name fails unsent
        return raw

    def _resolve(self, raw: str, verb) -> Optional[FakeMailbox]:
        """The box a mailbox argument names. Gmail quotes names; an unquoted name with a space
        or a special character is a BAD command, as on the real server."""
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            name = re.sub(r'\\(["\\])', r"\1", raw[1:-1])
        else:
            if re.search(r'[\s"(){%*\\]', raw):
                raise imaplib.IMAP4.error(f"{verb} command error: BAD [b'Could not parse command']")
            name = raw
        for b in self._server.boxes:
            if b.listed and b.name == name:
                return b
        return None

    def select(self, mailbox="INBOX", readonly=False):
        verb = "EXAMINE" if readonly else "SELECT"
        raw = self._ascii(mailbox)
        self._cmd(verb, raw, bool(readonly))
        b = self._resolve(raw, verb)
        if not readonly:
            self._server.violations.append(f"SELECT {mailbox} read-write")
        self.untagged_responses = {}
        if b is None:
            self._box = None
            return "NO", [b"[NONEXISTENT] Unknown Mailbox: " + str(mailbox).encode("ascii")
                          + b" (Failure)"]
        self._box, self._readonly, self.state = b, bool(readonly), "SELECTED"
        self.untagged_responses = {
            "FLAGS": [b"(\\Answered \\Flagged \\Draft \\Deleted \\Seen $Phishing $NotPhishing)"],
            "UIDVALIDITY": [str(b.validity).encode()],
            "UIDNEXT": [str(b.next_uid).encode()],
            "HIGHESTMODSEQ": [b"4242"],
            "RECENT": [b"0"],
        }
        if readonly:
            self.untagged_responses["READ-ONLY"] = [b""]
        return "OK", [str(len(b.messages)).encode()]

    def status(self, mailbox, names):
        raw = self._ascii(mailbox)
        self._cmd("STATUS", raw, names)
        b = self._resolve(raw, "STATUS")
        if b is None:
            return "NO", [b"[NONEXISTENT] Unknown Mailbox (Failure)"]
        return "OK", [f'"{b.name}" (MESSAGES {len(b.messages)} UIDNEXT {b.next_uid} '
                      f'UIDVALIDITY {b.validity})'.encode("ascii")]

    # ---------------------------------------------------------------- search and fetch
    def uid(self, command, *args):
        cmd = str(command).upper()
        if cmd in _WRITE_UID:
            self._rec("UID " + cmd, *args)
            self._server.violations.append(f"UID {cmd}")
            raise AssertionError(f"mail must be read-only: UID {cmd} called")
        self._cmd("UID " + cmd, *args)
        self._need_selected("UID " + cmd)
        if cmd == "SEARCH":
            uids = self._search(args)
            return "OK", [" ".join(str(u) for u in uids).encode()]
        if cmd == "FETCH":
            return self._fetch(args[0], args[1], by_uid=True)
        raise imaplib.IMAP4.error(f"UID command error: BAD [b'Unknown UID command {cmd}']")

    def search(self, charset, *criteria):
        self._cmd("SEARCH", *criteria)
        self._need_selected("SEARCH")
        uids = self._search(criteria)
        seqs = {u: i + 1 for i, u in enumerate(sorted(self._box.messages))}
        return "OK", [" ".join(str(seqs[u]) for u in uids).encode()]

    def fetch(self, message_set, message_parts):
        self._cmd("FETCH", message_set, message_parts)
        self._need_selected("FETCH")
        return self._fetch(message_set, message_parts, by_uid=False)

    def _set(self, spec: str, ordered: list[int]) -> list[int]:
        """An IMAP sequence set over `ordered` positions (UIDs or 1..n). `*` is the highest
        value in use, so `n:*` always includes it, even when n is above it (RFC 3501 6.4.8)."""
        if not ordered:
            return []
        top = ordered[-1]
        out: set[int] = set()
        for part in str(spec).split(","):
            a, _, b = part.partition(":")
            lo = top if a == "*" else int(a)
            hi = lo if not b else (top if b == "*" else int(b))
            lo, hi = min(lo, hi), max(lo, hi)
            out |= {u for u in ordered if lo <= u <= hi}
        return sorted(out)

    def _search(self, criteria) -> list[int]:
        text = " ".join(c.decode() if isinstance(c, bytes) else str(c)
                        for c in criteria if c is not None)
        toks = _tokens(text)
        msgs = self._box.messages
        hits = set(msgs)
        i = 0
        while i < len(toks):
            t = toks[i].upper()
            if t == "ALL":
                i += 1
            elif t == "CHARSET":
                i += 2
            elif t == "UID":
                hits &= set(self._set(toks[i + 1], sorted(msgs)))
                i += 2
            elif t in ("SINCE", "BEFORE"):
                d = _imap_date(toks[i + 1])
                hits &= {u for u in hits if (msgs[u].internaldate.date() >= d if t == "SINCE"
                                             else msgs[u].internaldate.date() < d)}
                i += 2
            elif t == "X-GM-MSGID":
                if "X-GM-EXT-1" not in self.capabilities:
                    raise imaplib.IMAP4.error("SEARCH command error: BAD [b'Could not parse command']")
                want = int(toks[i + 1].strip('"'))
                hits &= {u for u in hits if msgs[u].gm_msgid == want}
                i += 2
            else:                                # X-GM-RAW, TEXT, FROM ...: not used by F-50
                raise imaplib.IMAP4.error(f"SEARCH command error: BAD [b'fake: unsupported {t}']")
        return sorted(hits)

    _ITEM = re.compile(r"BODY(\.PEEK)?\[([^\]]*)\](?:<(\d+)\.(\d+)>)?|RFC822\.SIZE|RFC822\.HEADER|"
                       r"RFC822\.TEXT|RFC822|X-GM-MSGID|X-GM-THRID|X-GM-LABELS|INTERNALDATE|UID|"
                       r"FLAGS|ENVELOPE", re.I)

    def _fetch(self, message_set, parts, *, by_uid: bool):
        b = self._box
        ordered = sorted(b.messages)
        spec = message_set.decode() if isinstance(message_set, bytes) else str(message_set)
        parts = parts.decode() if isinstance(parts, bytes) else str(parts)
        items = [m for m in self._ITEM.finditer(parts.upper())]
        if any(m.group(0).startswith("X-GM") for m in items) and "X-GM-EXT-1" not in self.capabilities:
            raise imaplib.IMAP4.error("FETCH command error: BAD [b'Could not parse command']")
        if by_uid:
            chosen = self._set(spec, ordered)
        else:
            seqs = self._set(spec, list(range(1, len(ordered) + 1)))
            chosen = [ordered[s - 1] for s in seqs]
        out: list = []
        for uid in chosen:
            msg = b.messages[uid]
            seq = ordered.index(uid) + 1
            attrs: list[str] = []
            lits: list[tuple[str, bytes]] = []
            names = {m.group(0).split("[")[0].split("<")[0] for m in items}
            if "X-GM-THRID" in names:
                attrs.append(f"X-GM-THRID {msg.gm_thrid}")
            if "X-GM-MSGID" in names:
                attrs.append(f"X-GM-MSGID {msg.gm_msgid}")
            if "X-GM-LABELS" in names:
                labs = " ".join(x if x.startswith("\\") else '"' + x + '"' for x in msg.labels)
                attrs.append(f"X-GM-LABELS ({labs})")
            if by_uid or "UID" in names:
                attrs.append(f"UID {uid}")
            if "INTERNALDATE" in names:
                attrs.append('INTERNALDATE "' + msg.internaldate.strftime("%d-%b-%Y %H:%M:%S +0000") + '"')
            if "RFC822.SIZE" in names:
                attrs.append(f"RFC822.SIZE {len(msg.raw)}")
            for m in items:
                tok = m.group(0)
                if tok.startswith("BODY"):
                    peek, section, start, length = m.group(1), m.group(2), m.group(3), m.group(4)
                    data = self._section(msg.raw, section)
                    if start is not None:
                        data = data[int(start):int(start) + int(length)]
                    label = f"BODY[{section}]" + (f"<{start}>" if start is not None else "")
                    lits.append((label, data))
                    if not peek:
                        self._mark_seen(msg, uid, f"BODY[{section}] without .PEEK")
                elif tok in ("RFC822", "RFC822.TEXT", "RFC822.HEADER"):
                    data = msg.raw if tok == "RFC822" else self._section(
                        msg.raw, "HEADER" if tok == "RFC822.HEADER" else "TEXT")
                    lits.append((tok, data))
                    if tok != "RFC822.HEADER":
                        self._mark_seen(msg, uid, tok)
            if "FLAGS" in names:
                attrs.append(f"FLAGS ({' '.join(sorted(msg.flags))})")
            head = f"{seq} (" + " ".join(attrs)
            if not lits:
                out.append((head + ")").encode())
                continue
            for k, (label, data) in enumerate(lits):
                prefix = (head + (" " if attrs else "") if k == 0 else " ") + f"{label} {{{len(data)}}}"
                out.append((prefix.encode(), data))
            out.append(b")")
        return "OK", out or [None]

    def _mark_seen(self, msg: FakeMessage, uid: int, why: str) -> None:
        msg.flags.add("\\Seen")
        self._server.violations.append(f"{why} (uid {uid})")

    @staticmethod
    def _section(raw: bytes, section: str) -> bytes:
        norm = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        head, _, body = norm.partition(b"\r\n\r\n")
        sec = section.upper().strip()
        if sec == "":
            return norm
        if sec == "TEXT":
            return body
        if sec == "HEADER":
            return head + b"\r\n\r\n"
        m = re.fullmatch(r"HEADER\.FIELDS(\.NOT)?\s*\(([^)]*)\)", sec)
        if m:
            want = {f.upper() for f in m.group(2).split()}
            keep, cur = [], None
            for line in head.split(b"\r\n"):
                if line[:1] in (b" ", b"\t") and cur is not None:
                    if cur:
                        keep.append(line)
                    continue
                name = line.split(b":", 1)[0].decode("ascii", "replace").upper()
                cur = (name in want) != bool(m.group(1))
                if cur:
                    keep.append(line)
            return b"\r\n".join(keep) + b"\r\n\r\n"
        raise imaplib.IMAP4.error(f"FETCH command error: BAD [b'fake: unsupported section {section}']")


def gmail_server(layout: str = "gmail", **kw) -> FakeMailServer:
    """A FakeMailServer holding nothing yet (`deliver` the messages a test needs)."""
    return FakeMailServer(layout, **kw)


def parse_fetch(data) -> list[dict]:
    """imaplib FETCH data -> [{attr: value, 'BODY[...]': bytes}] (a reader for the fake's own
    tests; imapread has its own)."""
    out = []
    cur: Optional[dict] = None
    for item in data or []:
        if item is None:
            continue
        if isinstance(item, tuple):
            head = item[0].decode()
            if cur is None or re.match(r"^\d+ \(", head):
                cur = {}
                out.append(cur)
            _attrs(head, cur)
            label = re.search(r"(BODY\[[^\]]*\](?:<\d+>)?|RFC822(?:\.\w+)?) \{\d+\}$", head)
            if label:
                cur[label.group(1)] = item[1]
        elif item == b")":
            cur = None
        else:
            cur = {}
            out.append(cur)
            _attrs(item.decode(), cur)
            cur = None
    return out


def _attrs(text: str, into: dict) -> None:
    for k, v in re.findall(r'(UID|RFC822\.SIZE|X-GM-MSGID|X-GM-THRID) (\d+)', text):
        into[k] = int(v)
    m = re.search(r'INTERNALDATE "([^"]+)"', text)
    if m:
        into["INTERNALDATE"] = m.group(1)
    m = re.search(r"X-GM-LABELS \(([^)]*)\)", text)
    if m:
        into["X-GM-LABELS"] = m.group(1)
    m = re.search(r"(?<![\w-])FLAGS \(([^)]*)\)", text)
    if m:
        into["FLAGS"] = m.group(1)


def note_waiting(module_name: str, start: int) -> None:
    """The one import-time line every gated mail test file prints."""
    mine = WAITING[start:]
    if mine:
        print(f"[{module_name}] {len(mine)} oracle tests wait for modules not built yet: "
              + ", ".join(sorted({m for _n, m in mine})))


def assert_live(primary: str, start: int, module_name: str) -> None:
    """Skip-clean only while `primary` is absent: once it exists, no oracle in the file may
    still wait (a missing name is then a failure, not a quiet skip)."""
    if missing(primary):
        print(f"[{module_name}] waiting for {primary}")
        return
    mine = WAITING[start:]
    assert not mine, f"{primary} exists but these oracles still wait: {mine}"
