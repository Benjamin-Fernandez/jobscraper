"""Read-only Gmail over IMAP: the one module that speaks IMAP for F-50
(mail_status_design.md §5; ADR-0007).

Foundation module (MS §2.1). It imports the standard library, `apply.contracts`
(for `Secret`) and `mailstatus.contracts` only: both are stdlib-only data shapes
a foundation module may use (D-73). The mailstatus stage never touches IMAP; the
flow hands it the `MailHeader`s and `MailBody`s made here. `apply/mail.py` (F-36)
uses the helpers below too, so there is one copy of each.

Read-only by construction (F-50g, D-91 d, MS §5.6). Every command goes through
`_ReadOnly`, which offers only LOGIN, CAPABILITY, LIST, EXAMINE (a read-only
open), UID SEARCH, UID FETCH, NOOP and LOGOUT. There is no way through it to
store flags, copy, move, expunge or append, or to open a mailbox for writing,
and `uid_fetch` refuses any fetch item that would mark a message read: a body
section without `.PEEK`, or any RFC822 item but RFC822.SIZE.

What leaves this module: parsed headers, and body text in which every URL is
already `[link]` (no link list, nothing rendered, nothing remote). What never
does: server text. Login and command failures become a `SyncCode` through
`login_code` / `_op_code`; `MailFailure.detail` holds an exception class name
only, because Gmail's error text can echo the username (MS §13).

Gmail facts this relies on (MB §2): `\\All` and `\\Junk` special-use flags on
LIST; X-GM-MSGID / X-GM-THRID / X-GM-LABELS behind the `X-GM-EXT-1`
capability; `UID SEARCH UID n:*` always returns the highest UID even when it
is below n (the `*` gotcha); SEARCH SINCE compares whole days.
"""
from __future__ import annotations

import email
import email.policy
import imaplib
import inspect
import logging
import re
import ssl
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Callable, Iterable, Optional, Sequence
from urllib.parse import urlsplit

from .apply.contracts import Secret
from .mailstatus.contracts import (
    TIME_FMT,
    AuthResult,
    Cursor,
    MailBody,
    MailboxRole,
    MailFailure,
    MailHeader,
    MessageRef,
    ScanResult,
    SyncCode,
    TransportInfo,
)

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]{}]+", re.I)
# What `links=False` also hides: a bare "www." address, which a reader would open.
_WWW_RE = re.compile(r"\bwww\.[^\s<>\"'()\[\]{}]+", re.I)
LINK_TEXT = "[link]"
ATS_DOMAINS = ("myworkdayjobs.com", "greenhouse.io", "lever.co", "ashbyhq.com")
_SLD = {"com", "co", "edu", "gov", "org", "net", "ac"}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

GMAIL_CAPABILITY = "X-GM-EXT-1"
FETCH_CHUNK = 100                     # UIDs per UID FETCH (MS §5.3)
HEADER_FIELDS = ("FROM", "REPLY-TO", "SUBJECT", "DATE", "LIST-ID", "PRECEDENCE",
                 "AUTO-SUBMITTED", "X-AUTOREPLY", "X-AUTORESPOND", "AUTHENTICATION-RESULTS")
HEADER_ITEMS = ("(UID INTERNALDATE RFC822.SIZE X-GM-MSGID X-GM-THRID X-GM-LABELS "
                f"BODY.PEEK[HEADER.FIELDS ({' '.join(HEADER_FIELDS)})])")
SIZE_ITEMS = "(UID RFC822.SIZE)"
BODY_ITEMS = "(UID BODY.PEEK[])"
GMAIL_AUTHSERV = "mx.google.com"      # the only Authentication-Results trusted (Gmail's own)


# ---------------------------------------------------------------- the command guard (§5.6)

# A fetch item that sets \Seen: a body section without .PEEK (BODY[...], BINARY[...]),
# or RFC822 / RFC822.TEXT / RFC822.HEADER. RFC822.SIZE alone is metadata.
_SECTION_RE = re.compile(r"\b(BODY|BINARY)(\.PEEK)?\[", re.I)
_RFC822_RE = re.compile(r"\bRFC822(\.[A-Z]+)?", re.I)


def _check_fetch_items(items: str) -> None:
    """Raise ValueError for any fetch item that would mark a message read."""
    text = items if isinstance(items, str) else bytes(items).decode("ascii", "replace")
    for m in _SECTION_RE.finditer(text):
        if not m.group(2):
            raise ValueError(f"read-only: {m.group(1).upper()}[ without .PEEK is refused")
    for m in _RFC822_RE.finditer(text):
        if (m.group(1) or "").upper() != ".SIZE":
            raise ValueError("read-only: only RFC822.SIZE may be fetched among the RFC822 items")


class _ReadOnly:
    """The IMAP commands F-50 may send, and no others (MS §5.6).

    Wraps an `imaplib.IMAP4_SSL` (or a stand-in with its methods). It has no
    store, copy, move, expunge or append, and its only way to open a mailbox is
    `examine`, a read-only open (imaplib then sends EXAMINE). Nothing is
    forwarded by name: a method missing here can't be reached through it.
    """

    __slots__ = ("_conn",)

    def __init__(self, conn: Any):
        self._conn = conn

    def login(self, user: str, password: str):
        return self._conn.login(user, password)

    def capability(self):
        return self._conn.capability()

    def list(self, directory: str = '""', pattern: str = "*"):
        return self._conn.list(directory, pattern)

    def examine(self, name: str) -> tuple[str, int, int]:
        """Open `name` read-only. (typ, UIDVALIDITY, UIDNEXT); 0 for a value the
        server didn't report."""
        typ, _data = self._conn.select(quote_folder(name), readonly=True)
        if typ != "OK":
            return typ, 0, 0
        return typ, _response_int(self._conn, "UIDVALIDITY"), _response_int(self._conn, "UIDNEXT")

    def uid_search(self, *criteria: str):
        return self._conn.uid("SEARCH", *criteria)

    def uid_fetch(self, uids: str, items: str):
        _check_fetch_items(items)
        return self._conn.uid("FETCH", uids, items)

    def noop(self):
        return self._conn.noop()

    def logout(self):
        return self._conn.logout()


def _response_int(conn: Any, code: str) -> int:
    """An untagged response code EXAMINE left (`[UIDVALIDITY n]`, `[UIDNEXT n]`)."""
    try:
        _typ, data = conn.response(code)
    except (AttributeError, imaplib.IMAP4.error):
        return 0
    for item in data or []:
        if item is None:
            continue
        m = re.match(rb"\s*(\d+)", item if isinstance(item, bytes) else str(item).encode())
        if m:
            return int(m.group(1))
    return 0


def _logout(conn: Any) -> None:
    if conn is None:
        return
    try:
        conn.logout()
    except Exception:                                   # closing is best effort
        pass


# ---------------------------------------------------------------- domains (moved from apply/mail.py)

def host_of(url_or_host: str) -> str:
    """The lower-case host of a URL or a bare host name; "" when unparsable."""
    s = (url_or_host or "").strip()
    if "//" not in s:
        s = "//" + s
    try:
        return (urlsplit(s).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def domain_matches(host: str, domains: Iterable[str]) -> bool:
    """`host == d` or `host` ends with `.d` for any non-empty `d`."""
    h = (host or "").lower().rstrip(".")
    if not h:
        return False
    for d in domains:
        d = (d or "").strip().lower().lstrip(".")
        if d and (h == d or h.endswith("." + d)):
            return True
    return False


def registrable_domain(host: str) -> str:
    """The registrable domain of a host (or URL): `careers.dbs.com` -> `dbs.com`,
    `mail.dbs.com.sg` -> `dbs.com.sg`; "" for a single label. A short list of
    second-level labels under a two-letter country code stands in for the public
    suffix list (enough for the employers and platforms F-36 and F-50 meet)."""
    h = host_of(host)
    labels = [p for p in h.split(".") if p]
    if len(labels) < 2:
        return ""
    if (len(labels) >= 3 and labels[-2] in _SLD and len(labels[-1]) == 2
            and labels[-1].isalpha()):
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def employer_domain(careers_url: str) -> str:
    """The employer's registrable domain from its careers URL (apply_design §11.3);
    "" for an ATS host or an unparsable URL. `careers.dbs.com` -> `dbs.com`;
    `www.dbs.com.sg` -> `dbs.com.sg`."""
    host = host_of(careers_url)
    if not host or domain_matches(host, ATS_DOMAINS):
        return ""
    return registrable_domain(host)


def sender_domain(msg: Any) -> str:
    """The From address's domain, lower-case; "" when there is none."""
    addr = parseaddr(str(msg.get("From", "")))[1]
    return addr.rpartition("@")[2].strip().lower().rstrip(">") if "@" in addr else ""


# ---------------------------------------------------------------- folders and dates

def quote_folder(name: str) -> str:
    """A mailbox name as EXAMINE takes it. imaplib sends it as given, so a name
    with a space, a quote or another character an IMAP atom can't hold is quoted
    here; `INBOX` and `[Gmail]/Spam` go bare, as Gmail expects. The name is never
    decoded: localised names stay in modified UTF-7, exactly as LIST gave them."""
    if name and not any(c in name for c in ' "(){%*\\') and all(32 < ord(c) < 127 for c in name):
        return name
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


_INTERNALDATE_RE = re.compile(
    rb'INTERNALDATE "\s?(\d{1,2})-([A-Za-z]{3})-(\d{4}) (\d{2}):(\d{2}):(\d{2}) ([-+])(\d{2})(\d{2})"')


def internaldate(meta: Any) -> Optional[datetime]:
    """INTERNALDATE from a FETCH response line, as an aware UTC datetime; None
    when absent or unreadable."""
    if not meta:
        return None
    b = meta if isinstance(meta, bytes) else str(meta).encode("utf-8", "replace")
    m = _INTERNALDATE_RE.search(b)
    if not m:
        return None
    day, mon, year, hh, mm, ss, sign, zh, zm = (g.decode("ascii") for g in m.groups())
    try:
        month = _MONTHS.index(mon.capitalize()) + 1
        offset = timedelta(hours=int(zh), minutes=int(zm)) * (-1 if sign == "-" else 1)
        local = datetime(int(year), month, int(day), int(hh), int(mm), int(ss),
                         tzinfo=timezone(offset))
    except ValueError:
        return None
    return local.astimezone(timezone.utc)


def imap_date(d: datetime) -> str:
    """`02-Nov-2026`, the date form SEARCH SINCE takes."""
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"


def _parse_time(stamp: str) -> Optional[datetime]:
    """A store TIME_FMT stamp (or just its date) as an aware UTC datetime."""
    s = (stamp or "").strip()
    for fmt, n in ((TIME_FMT, 19), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(s[:n], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- special-use folders (§5.2)

_LIST_RE = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?P<delim>NIL|"(?:[^"\\]|\\.)*"|\S+)\s+(?P<name>.*?)\s*$',
                      re.I | re.S)


def _unquote(raw: bytes) -> str:
    s = raw.strip()
    if len(s) >= 2 and s[:1] == b'"' and s[-1:] == b'"':
        s = re.sub(rb'\\(.)', rb'\1', s[1:-1])
    return s.decode("utf-8", "replace")


def _list_entries(data: Any) -> list[tuple[frozenset[str], str]]:
    """(flags, raw name) per LIST line; a literal name arrives as a tuple."""
    out: list[tuple[frozenset[str], str]] = []
    for item in data or []:
        if item is None:
            continue
        if isinstance(item, tuple):
            head = item[0] if isinstance(item[0], bytes) else str(item[0]).encode()
            m = _LIST_RE.match(head.strip())
            name = (item[1] if isinstance(item[1], bytes) else str(item[1]).encode()).decode("utf-8", "replace")
        else:
            line = item if isinstance(item, bytes) else str(item).encode()
            m = _LIST_RE.match(line.strip())
            name = _unquote(m.group("name")) if m else ""
        if not m or not name:
            continue
        flags = frozenset(f.lower() for f in m.group("flags").decode("ascii", "replace").split())
        out += [(flags, name)]
    return out


def special_use_folders(conn: Any) -> dict[MailboxRole, str]:
    """{ALL: name, JUNK: name} from `LIST "" "*"` and the RFC 6154 flags `\\All`
    and `\\Junk` (MS §5.2). A role Gmail doesn't flag (hidden from IMAP, or not
    Gmail) is absent. The names are raw, as LIST gave them, ready for EXAMINE.

    Only a `list` the connection object really defines is called: a stand-in
    that answers every other name through `__getattr__` (a proxy, or a guard
    that refuses unknown commands) gets no LIST, and the caller falls back to
    its fixed names (apply/mail.py: `[Gmail]/Spam`). Errors propagate.
    """
    if inspect.getattr_static(conn, "list", None) is None:
        return {}
    typ, data = conn.list()
    if typ != "OK":
        return {}
    found: dict[MailboxRole, str] = {}
    for flags, name in _list_entries(data):
        if "\\all" in flags:
            found.setdefault(MailboxRole.ALL, name)
        if "\\junk" in flags:
            found.setdefault(MailboxRole.JUNK, name)
    return found


# ---------------------------------------------------------------- login and command failures (§12)

_THROTTLED = ("[overquota]", "[unavailable]", "[throttled]", "too many simultaneous connections",
              "account exceeded command or bandwidth limits")
_REFUSED = ("[authenticationfailed]", "invalid credentials", "login failed", "authenticate failed",
            "[authorizationfailed]", "authentication failed")


_NETWORK_ERRORS = (imaplib.IMAP4.abort, OSError, ssl.SSLError, TimeoutError, EOFError)


def login_code(exc: BaseException) -> SyncCode:
    """What a failed LOGIN means, as a code (MS §12). Never the server's text:
    Gmail's message can echo the username (MS §13).

    Throttling first, whatever the exception type (Gmail may say it in a BYE);
    then a dropped or unreachable connection; then Gmail's refusals by their
    words. Any other refusal at LOGIN also pauses the mailbox: retrying a
    password the server rejects is how an account gets locked (no retry storm).
    """
    if isinstance(exc, MailFailure):
        return exc.code
    text = str(exc).lower()
    if any(t in text for t in _THROTTLED):
        return SyncCode.RATE_LIMITED
    if isinstance(exc, _NETWORK_ERRORS):
        return SyncCode.NETWORK
    if "application-specific password" in text:
        return SyncCode.APP_PASSWORD_REQUIRED
    if "web browser" in text or "[webalert" in text:
        return SyncCode.WEB_LOGIN_REQUIRED
    if any(t in text for t in _REFUSED) or isinstance(exc, imaplib.IMAP4.error):
        return SyncCode.LOGIN_REFUSED
    return SyncCode.INTERNAL


def _op_code(exc: BaseException) -> SyncCode:
    """What a failure outside LOGIN means (connect, EXAMINE, SEARCH, FETCH)."""
    if isinstance(exc, MailFailure):
        return exc.code
    if any(t in str(exc).lower() for t in _THROTTLED):
        return SyncCode.RATE_LIMITED
    if isinstance(exc, _NETWORK_ERRORS):
        return SyncCode.NETWORK
    return SyncCode.INTERNAL


def _failure(exc: BaseException, code: Optional[SyncCode] = None) -> MailFailure:
    return exc if isinstance(exc, MailFailure) else MailFailure(code or _op_code(exc), type(exc).__name__)


# ---------------------------------------------------------------- scan plans (§5.3, pure)

PLAN_NOTHING = "nothing"     # same validity, nothing new
PLAN_FIRST = "first"         # no cursor: SEARCH SINCE the window
PLAN_RANGE = "range"         # same validity: SEARCH UID last+1:*, drop uid <= last
PLAN_RESCAN = "rescan"       # validity changed: SEARCH SINCE the last scan, dedupe upstream


@dataclass(frozen=True)
class ScanPlan:
    kind: str                       # PLAN_*
    search: tuple[str, ...]         # UID SEARCH criteria; () for PLAN_NOTHING
    after_uid: int                  # drop every UID <= this (the `*` gotcha); 0 keeps all
    validity: int                   # the UIDVALIDITY the cursor carries from now on
    last_uid: int                   # the position before this scan (0 when none applies)
    last_scan_at: str               # carried on each header's cursor_after


def _since(stamp: str) -> str:
    when = _parse_time(stamp)
    if when is None:
        raise ValueError("plan_scan needs a TIME_FMT stamp to search from")
    return imap_date(when - timedelta(days=1))


def plan_scan(cursor: Optional[Cursor], uidvalidity: int, uidnext: int,
              window_start: str, now: str) -> ScanPlan:
    """How to find the messages after `cursor` in a mailbox EXAMINE reported as
    (`uidvalidity`, `uidnext`). Pure (MS §5.3).

    - no cursor: SEARCH SINCE the day before `window_start` (SINCE compares whole
      days); the header gate drops what is older than the window.
    - same validity and `uidnext <= last + 1`: nothing to read.
    - same validity: SEARCH `UID last+1:*`, and every UID <= last is dropped,
      because `*` always matches the highest UID even when it is below last+1.
    - validity changed: the old UIDs mean nothing. SEARCH SINCE the day before
      the last scan (or the window); X-GM-MSGID dedupe drops what was processed.
    `now` is unused by the plan itself; it is the stamp `scan` gives end cursors.
    """
    del now
    if cursor is None:
        return ScanPlan(PLAN_FIRST, ("SINCE", _since(window_start)), 0, uidvalidity, 0, "")
    if int(cursor.validity) == int(uidvalidity):
        last = int(cursor.last_uid)
        if uidnext and uidnext <= last + 1:
            return ScanPlan(PLAN_NOTHING, (), last, uidvalidity, last, cursor.last_scan_at)
        return ScanPlan(PLAN_RANGE, ("UID", f"{last + 1}:*"), last, uidvalidity, last,
                        cursor.last_scan_at)
    since = cursor.last_scan_at if _parse_time(cursor.last_scan_at) else window_start
    return ScanPlan(PLAN_RESCAN, ("SINCE", _since(since)), 0, uidvalidity, 0, cursor.last_scan_at)


# ---------------------------------------------------------------- FETCH responses

_RECORD_START = re.compile(rb"^\s*\d+ \(")


def _records(data: Any) -> list[tuple[bytes, bytes]]:
    """(meta, literal) per message of an imaplib FETCH answer. Items after a
    literal (`b' X-GM-LABELS (...))'`) are added to that message's meta."""
    out: list[list[bytes]] = []
    for item in data or []:
        if item is None:
            continue
        if isinstance(item, tuple) and len(item) >= 2:
            meta = item[0] if isinstance(item[0], bytes) else str(item[0]).encode()
            raw = item[1] if isinstance(item[1], bytes) else str(item[1]).encode()
            out += [[meta, raw]]
            continue
        b = item if isinstance(item, bytes) else str(item).encode()
        if _RECORD_START.match(b) or not out:
            out += [[b, b""]]
        else:
            out[-1][0] += b
    return [(m, r) for m, r in out]


def _meta_int(meta: bytes, name: str) -> Optional[int]:
    m = re.search(rb"(?:^|[\s(])" + re.escape(name.encode()) + rb" (\d+)", meta)
    return int(m.group(1)) if m else None


_LABELS_RE = re.compile(rb"X-GM-LABELS \(([^)]*)\)")
_LABEL_TOKEN = re.compile(rb'"((?:[^"\\]|\\.)*)"|([^\s"()]+)')


def _meta_labels(meta: bytes) -> tuple[str, ...]:
    m = _LABELS_RE.search(meta)
    if not m:
        return ()
    out: list[str] = []
    for q, atom in _LABEL_TOKEN.findall(m.group(1)):
        tok = re.sub(rb"\\(.)", rb"\1", q) if q else atom
        out += [tok.decode("utf-8", "replace")]
    return tuple(out)


# ---------------------------------------------------------------- headers (§5.3, §6.2)

def _header(msg: Any, name: str) -> str:
    """A decoded header, whitespace collapsed; "" when absent or unparsable."""
    try:
        v = msg.get(name)
    except Exception:                                   # a malformed header: no value
        return ""
    if v is None:
        return ""
    try:
        return " ".join(str(v).split())
    except Exception:
        return ""


def _addresses(msg: Any, name: str) -> list[tuple[str, str]]:
    """(display name, address) for every address in the header."""
    try:
        values = msg.get_all(name) or []
    except Exception:
        return []
    out: list[tuple[str, str]] = []
    for v in values:
        try:
            addrs = getattr(v, "addresses", None)
        except Exception:
            addrs = None
        if addrs:
            out += [(str(a.display_name or ""), str(a.addr_spec or "")) for a in addrs]
        else:
            out += getaddresses([str(v)])
    return out


def auth_result(headers: Any, from_reg: str) -> AuthResult:
    """Gmail's verdict on who sent a message, from its Authentication-Results.

    Only the topmost header whose authserv-id is `mx.google.com` counts: Gmail
    adds its own above anything the sender wrote. `dmarc=pass` -> PASS,
    `dmarc=fail` -> FAIL; otherwise `dkim=pass` with `header.d` (or `header.i`)
    whose registrable domain is the From's (`from_reg`) -> PASS; else NONE.
    `headers` is a message, or the header values in order.
    """
    if hasattr(headers, "get_all"):
        values = [str(v) for v in (headers.get_all("Authentication-Results") or [])]
    elif isinstance(headers, (str, bytes)):
        values = [headers.decode("utf-8", "replace") if isinstance(headers, bytes) else headers]
    else:
        values = [str(v) for v in (headers or [])]
    ours = None
    for v in values:
        text = " ".join(v.split())
        if text.split(";", 1)[0].strip().lower() == GMAIL_AUTHSERV:
            ours = text
            break
    if ours is None:
        return AuthResult.NONE
    body = re.sub(r"\([^()]*\)", " ", ours.split(";", 1)[1] if ";" in ours else "")
    dmarc = ""
    dkim_aligned = False
    want = (from_reg or "").lower()
    for part in body.split(";"):
        words = part.split()
        if not words or "=" not in words[0]:
            continue
        method, _, result = words[0].lower().partition("=")
        props = dict(w.lower().split("=", 1) for w in words[1:] if "=" in w)
        if method == "dmarc" and not dmarc:
            dmarc = result
        elif method == "dkim" and result == "pass" and want:
            d = props.get("header.d") or props.get("header.i", "").rpartition("@")[2]
            if d and registrable_domain(d) == want:
                dkim_aligned = True
    if dmarc == "pass":
        return AuthResult.PASS
    if dmarc == "fail":
        return AuthResult.FAIL
    return AuthResult.PASS if dkim_aligned else AuthResult.NONE


def parse_header(meta: Any, raw: Any, ref: MessageRef, cursor_before: Cursor) -> MailHeader:
    """One message's header fetch as a `MailHeader` (MS §3, §5.3).

    `meta` is the FETCH line (UID, INTERNALDATE, RFC822.SIZE, X-GM-*), `raw` the
    header block. `cursor_after` is `cursor_before` moved to this message.
    """
    meta_b = meta if isinstance(meta, bytes) else str(meta or "").encode("utf-8", "replace")
    raw_b = raw if isinstance(raw, bytes) else str(raw or "").encode("utf-8", "replace")
    msg = email.message_from_bytes(raw_b, policy=email.policy.default)

    froms = _addresses(msg, "From")
    from_name, from_addr = froms[0] if froms else ("", "")
    from_addr = from_addr.strip().strip("<>").lower()
    from_local, at, from_domain = from_addr.rpartition("@")
    if not at:
        from_local, from_domain = "", ""
    from_domain = from_domain.rstrip(".")
    from_reg = registrable_domain(from_domain) if from_domain else ""

    reply_to_regs: list[str] = []
    for _n, addr in _addresses(msg, "Reply-To"):
        reg = registrable_domain(addr.rpartition("@")[2]) if "@" in addr else ""
        if reg and reg not in reply_to_regs:
            reply_to_regs += [reg]

    when = internaldate(meta_b)
    if when is None:
        try:
            when = parsedate_to_datetime(_header(msg, "Date"))
            when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError, IndexError):
            when = None
    received_at = when.astimezone(timezone.utc).strftime(TIME_FMT) if when else ""

    def present(name: str) -> bool:
        try:
            return msg.get(name) is not None
        except Exception:
            return True

    cursor_after = Cursor(cursor_before.account_id, ref.role, ref.mailbox, ref.validity,
                          ref.uid, cursor_before.last_scan_at)
    return MailHeader(
        ref=ref,
        gm_msgid=str(_meta_int(meta_b, "X-GM-MSGID") or ""),
        gm_thrid=str(_meta_int(meta_b, "X-GM-THRID") or ""),
        labels=_meta_labels(meta_b),
        received_at=received_at,
        size=int(_meta_int(meta_b, "RFC822.SIZE") or 0),
        from_addr=from_addr,
        from_name=" ".join(from_name.split()),
        from_domain=from_domain,
        from_reg=from_reg,
        from_local=from_local,
        reply_to_regs=tuple(reply_to_regs),
        subject=_header(msg, "Subject"),
        list_id=present("List-ID"),
        precedence=_header(msg, "Precedence").lower(),
        auto_submitted=_header(msg, "Auto-Submitted").lower(),
        autoreply_header=present("X-Autoreply") or present("X-Autorespond"),
        auth=auth_result(msg, from_reg),
        cursor_after=cursor_after,
    )


# ---------------------------------------------------------------- bodies (moved from apply/mail.py)

class _HtmlText(HTMLParser):
    """HTML -> text lines plus (href, anchor text) pairs. Parsed, never rendered:
    nothing remote is loaded."""
    _BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
              "table", "td", "th", "section", "article", "header", "footer"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._href: Optional[str] = None
        self._anchor: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in self._BLOCK:
            self.parts += ["\n"]
        if tag == "a":
            self._href = dict(attrs).get("href") or None
            self._anchor = []

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag == "a" and self._href is not None:
            self.links += [(self._href.strip(), " ".join("".join(self._anchor).split()))]
            self._href = None
        if tag in self._BLOCK:
            self.parts += ["\n"]

    def handle_data(self, data):
        if self._skip:
            return
        self.parts += [data]
        if self._href is not None:
            self._anchor += [data]

    def text(self) -> str:
        lines = (" ".join(l.split()) for l in "".join(self.parts).splitlines())
        return "\n".join(l for l in lines if l)


def hide_links(text: str) -> str:
    """Every http(s) URL and bare `www.` address in `text` replaced by `[link]`."""
    return _WWW_RE.sub(LINK_TEXT, URL_RE.sub(LINK_TEXT, text or ""))


def body_text(msg: email.message.EmailMessage, links: bool = True
              ) -> tuple[str, list[tuple[str, str]]]:
    """(text, [(url, anchor text)]): text/plain when present, else HTML as text.

    `links=True` (F-36, `apply.mail._body`): the URLs are kept in the text and
    listed, for the verification-link search. `links=False` (F-50): every URL in
    the text becomes `[link]` and the list is empty, so no link leaves this
    module (MS §5.6). The shape is the same either way.
    """
    plain = html = None
    for part in msg.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            content = part.get_content()
        except (LookupError, ValueError, AssertionError):
            payload = part.get_payload(decode=True) or b""
            content = payload.decode("utf-8", "replace")
        if ctype == "text/plain" and plain is None:
            plain = content
        elif ctype == "text/html" and html is None:
            html = content
    found: list[tuple[str, str]] = []
    text = ""
    if html is not None:
        p = _HtmlText()
        try:
            p.feed(html)
            p.close()
        except Exception:                               # malformed HTML: keep what parsed
            pass
        found = list(p.links)
        text = p.text()
    if plain is not None:
        text = plain
    if not links:
        return hide_links(text), []
    found += [(m.group(0).rstrip(".,;:!?"), "") for m in URL_RE.finditer(text)]
    return text, found


def _calendar_request(msg: Any) -> bool:
    """A text/calendar part that is an invitation (METHOD:REQUEST)."""
    for part in msg.walk():
        if part.get_content_type() != "text/calendar":
            continue
        if str(part.get_param("method", "") or "").upper() == "REQUEST":
            return True
        try:
            content = part.get_content()
        except (LookupError, ValueError, AssertionError):
            content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        if isinstance(content, bytes):
            content = content.decode("utf-8", "replace")
        if re.search(r"^METHOD:REQUEST\s*$", str(content), re.I | re.M):
            return True
    return False


def parse_body(raw: bytes) -> MailBody:
    """A full message as the stage reads it: text with `[link]`s, and whether it
    carries a calendar invitation."""
    msg = email.message_from_bytes(raw or b"", policy=email.policy.default)
    text, _ = body_text(msg, links=False)
    return MailBody(text=text, calendar_request=_calendar_request(msg))


# ---------------------------------------------------------------- the transport

def _chunks(seq: Sequence[int], n: int) -> Iterable[Sequence[int]]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _uid_list(data: Any) -> list[int]:
    out: list[int] = []
    for item in data or []:
        if item is None:
            continue
        b = item if isinstance(item, bytes) else str(item).encode()
        out += [int(x) for x in b.split() if x.isdigit()]
    return out


class ImapTransport:
    """`MailTransport` over Gmail IMAP, read-only (MS §3, §5.2-§5.6).

    One connection per account per sync, logged out by `close` (Gmail allows
    15 clients per account and the apply flow's watcher may hold one, MB §2).
    `connect` replaces `imaplib.IMAP4_SSL` (tests); it is called as
    `connect(host, port, timeout=timeout_s)`.
    """

    def __init__(self, host: str, port: int, username: str, password: Secret, *,
                 timeout_s: float = 20, connect: Optional[Callable[..., Any]] = None):
        if not isinstance(password, Secret):
            raise TypeError("ImapTransport takes the password as a contracts.Secret")
        self.host, self.port, self.username = host, int(port), username
        self._password = password
        self.timeout_s = timeout_s
        self._connect_fn = connect
        self._ro: Optional[_ReadOnly] = None
        self._folders: dict[MailboxRole, str] = {}
        self._open_box: Optional[tuple[str, int, int]] = None     # (name, validity, uidnext)
        self._account_id = 0                                      # the last scan's, for refind

    def __repr__(self) -> str:                    # no username: it is an address
        return f"ImapTransport({self.host}:{self.port})"

    # -- connection
    def open(self) -> TransportInfo:
        """Log in, check it is Gmail, find the folders. Raises MailFailure."""
        self.close()
        factory = self._connect_fn or imaplib.IMAP4_SSL     # looked up per call: patchable
        try:
            conn = factory(self.host, self.port, timeout=self.timeout_s)
        except Exception as exc:
            # A refused greeting is the server being unavailable, not a bug here.
            code = _op_code(exc)
            if code is SyncCode.INTERNAL and isinstance(exc, imaplib.IMAP4.error):
                code = SyncCode.NETWORK
            raise MailFailure(code, type(exc).__name__) from None
        ro = _ReadOnly(conn)
        try:
            ro.login(self.username, self._password.reveal())
        except Exception as exc:
            _logout(conn)
            raise MailFailure(login_code(exc), type(exc).__name__) from None
        try:
            typ, data = ro.capability()
            caps = tuple(_words(data)) if typ == "OK" else ()
            if GMAIL_CAPABILITY not in {c.upper() for c in caps}:
                raise MailFailure(SyncCode.NOT_GMAIL)
            special = special_use_folders(ro)
        except Exception as exc:
            _logout(conn)
            raise _failure(exc) from None
        folders: dict[MailboxRole, str] = {}
        notes: list[SyncCode] = []
        if MailboxRole.ALL in special:
            folders[MailboxRole.ALL] = special[MailboxRole.ALL]
        else:
            folders[MailboxRole.INBOX] = "INBOX"
            notes += [SyncCode.ALL_MAIL_HIDDEN]
        if MailboxRole.JUNK in special:
            folders[MailboxRole.JUNK] = special[MailboxRole.JUNK]
        else:
            notes += [SyncCode.JUNK_HIDDEN]
        self._ro, self._folders, self._open_box = ro, folders, None
        return TransportInfo(capabilities=caps, folders=dict(folders), notes=tuple(notes))

    def close(self) -> None:
        ro, self._ro, self._open_box = self._ro, None, None
        _logout(ro)

    def _need(self) -> _ReadOnly:
        if self._ro is None:
            raise MailFailure(SyncCode.INTERNAL, "not open")
        return self._ro

    def _examine(self, name: str) -> tuple[int, int]:
        typ, validity, uidnext = self._need().examine(name)
        if typ != "OK":
            self._open_box = None
            raise MailFailure(SyncCode.INTERNAL, "examine refused")
        self._open_box = (name, validity, uidnext)
        return validity, uidnext

    def _search(self, criteria: Sequence[str]) -> list[int]:
        typ, data = self._need().uid_search(*criteria)
        if typ != "OK":
            raise MailFailure(SyncCode.INTERNAL, "search refused")
        return _uid_list(data)

    def _fetch(self, uids: Sequence[int], items: str) -> dict[int, tuple[bytes, bytes]]:
        typ, data = self._need().uid_fetch(",".join(str(u) for u in uids), items)
        if typ != "OK":
            raise MailFailure(SyncCode.INTERNAL, "fetch refused")
        out: dict[int, tuple[bytes, bytes]] = {}
        for meta, raw in _records(data):
            uid = _meta_int(meta, "UID")
            if uid is not None and uid in uids:
                out[uid] = (meta, raw)
        return out

    def _headers(self, uids: Sequence[int], role: MailboxRole, mailbox: str, validity: int,
                 base: Cursor) -> list[MailHeader]:
        got = self._fetch(uids, HEADER_ITEMS)
        out: list[MailHeader] = []
        for uid in uids:
            if uid not in got:                          # gone since the search
                continue
            meta, raw = got[uid]
            out += [parse_header(meta, raw, MessageRef(role, mailbox, validity, uid), base)]
        return out

    # -- MailTransport
    def scan(self, role: MailboxRole, cursor: Optional[Cursor], *, account_id: int,
             window_start: str, limit: int, now: str) -> ScanResult:
        """Headers after `cursor` in the mailbox playing `role`, ascending UID,
        at most `limit` (MS §5.3). Raises MailFailure."""
        self._account_id = account_id
        mailbox = self._folders.get(role)
        if not mailbox:
            raise MailFailure(SyncCode.INTERNAL, "role not listed")
        try:
            validity, uidnext = self._examine(mailbox)
            plan = plan_scan(cursor, validity, uidnext, window_start, now)
            base = Cursor(account_id, role, mailbox, plan.validity, plan.last_uid, plan.last_scan_at)
            if plan.kind == PLAN_NOTHING:
                return ScanResult((), replace(base, last_scan_at=now), True)
            uids = sorted({u for u in self._search(plan.search) if u > plan.after_uid})
            taken = uids[:max(0, int(limit))]
            headers: list[MailHeader] = []
            for chunk in _chunks(taken, FETCH_CHUNK):
                headers += self._headers(chunk, role, mailbox, plan.validity, base)
        except Exception as exc:
            raise _failure(exc) from None
        if len(taken) < len(uids):
            return ScanResult(tuple(headers), None, False)
        # Nothing below UIDNEXT is left unread, so the cursor may move past mail
        # that arrived and was deleted, or that the search day boundary excluded.
        last = max([plan.last_uid, *taken, (uidnext - 1) if uidnext else 0])
        return ScanResult(tuple(headers), Cursor(account_id, role, mailbox, plan.validity, last, now), True)

    def fetch_body(self, ref: MessageRef, max_bytes: int) -> Optional[MailBody]:
        """The message's text (`[link]`s), or `MailBody("", ..., truncated=True)`
        above `max_bytes`; None when it is gone. Fetched with BODY.PEEK[] only."""
        try:
            box = self._open_box
            if box is None or box[0] != ref.mailbox or box[1] != ref.validity:
                validity, _uidnext = self._examine(ref.mailbox)     # (re)open, and look again
                if validity != ref.validity:
                    return None                         # the UIDs it named no longer apply
            sized = self._fetch([ref.uid], SIZE_ITEMS)
            if ref.uid not in sized:
                return None
            size = _meta_int(sized[ref.uid][0], "RFC822.SIZE") or 0
            if size > max_bytes:
                return MailBody("", False, truncated=True)
            got = self._fetch([ref.uid], BODY_ITEMS)
            if ref.uid not in got or not got[ref.uid][1]:
                return None
            raw = got[ref.uid][1]
        except Exception as exc:
            raise _failure(exc) from None
        return parse_body(raw)

    def refind(self, gm_msgid: str) -> Optional[MailHeader]:
        """The message with this X-GM-MSGID, searched in All Mail (or INBOX when
        All Mail is hidden), then Spam (MS §5.5). None when it is gone."""
        msgid = str(gm_msgid or "").strip()
        if not msgid.isdigit():
            return None
        roles = [r for r in (MailboxRole.ALL, MailboxRole.INBOX, MailboxRole.JUNK) if r in self._folders]
        try:
            for role in roles:
                mailbox = self._folders[role]
                validity, _uidnext = self._examine(mailbox)
                uids = sorted(self._search(("X-GM-MSGID", msgid)))
                if not uids:
                    continue
                base = Cursor(self._account_id, role, mailbox, validity, 0, "")
                found = self._headers(uids[:1], role, mailbox, validity, base)
                if found:
                    return found[0]
        except Exception as exc:
            raise _failure(exc) from None
        return None


def _words(data: Any) -> list[str]:
    """The words of an untagged answer (CAPABILITY)."""
    out: list[str] = []
    for item in data or []:
        if item is None:
            continue
        b = item if isinstance(item, bytes) else str(item).encode()
        out += b.decode("ascii", "replace").split()
    return out
