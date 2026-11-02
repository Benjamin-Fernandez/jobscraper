"""Read-only IMAP: find an ATS verification link or code (apply_design.md §11).

Stage module (apply/). Imports only the contracts and the vault (foundation).

What it may do to the mailbox (F-36, NF-02):
  - log in, open INBOX and `[Gmail]/Spam` with `select(folder, readonly=True)`
    (imaplib then sends EXAMINE), SEARCH, and FETCH with `BODY.PEEK[]` (PEEK:
    never sets \\Seen), then log out;
  - never STORE, COPY, MOVE, EXPUNGE, APPEND, and never SMTP.
What it may log: "verification mail found (link|code) from <sender domain>".
Never the URL, the code, a subject, an address or the password.

Two mailboxes (§11.5, D-70): the primary address uses `apply.mail`; the backup
address uses `apply.mail_backup` when its host and username are set, else the
main mailbox (a backup that forwards into, or is an alias of, the main inbox).
`wait_for(..., to_addr=...)` keeps only messages addressed to that address, so
one inbox receiving both never confuses the two accounts.
"""
from __future__ import annotations

import email
import email.policy
import imaplib
import logging
import re
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Callable, Iterable, Mapping, NamedTuple, Optional, Sequence
from urllib.parse import urlsplit

from .. import vault
from .contracts import ApplyFailure, ReasonCode, Secret, Verification

log = logging.getLogger(__name__)

FOLDERS = ("INBOX", "[Gmail]/Spam")
TIME_FMT = "%Y-%m-%dT%H:%M:%S"                  # store.TIME_FMT
DEFAULT_OTP = r"\b(\d{6})\b"
VERIFY_WORDS = re.compile(r"verify|verification|activate|confirm|validate", re.I)
CODE_LINE = re.compile(r"code", re.I)
URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]{}]+", re.I)
RECIPIENT_HEADERS = ("To", "Cc", "Delivered-To", "X-Original-To", "X-Forwarded-To")
SLACK_S = 60                                    # keep mail received ≥ since − 60 s
ATS_DOMAINS = ("myworkdayjobs.com", "greenhouse.io", "lever.co", "ashbyhq.com")
_SLD = {"com", "co", "edu", "gov", "org", "net", "ac"}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

DEFAULT_HOST = "imap.gmail.com"
DEFAULT_PORT = 993
DEFAULT_WAIT_S = 300
DEFAULT_POLL_S = 10


class MailError(RuntimeError):
    """The mailbox could not be reached or refused the login. No secret inside."""


# ---------------------------------------------------------------- settings (§11.5, §14.3)

class Mailbox(NamedTuple):
    host: str
    port: int
    username: str


def _cfg_attr(obj: Any, *path: str) -> Any:
    for p in path:
        if obj is None:
            return None
        obj = getattr(obj, p, None)
    return obj


def effective_settings(cfg: Any, get_setting: Callable[[str], Optional[str]]) -> dict[str, Any]:
    """The mail settings in force: the `settings` table over `config.yaml`'s
    `apply:` block over the defaults (§14.3).

    Keys: `apply.mail.host|port|username|wait_s|poll_s` and
    `apply.mail_backup.host|port|username`. The username lives only in the
    settings table (never in config.yaml: the repo is public).
    `cfg.apply` may be absent (before lane B's config lands): defaults apply.
    """
    ac = _cfg_attr(cfg, "apply")
    base = {
        "apply.mail.host": _cfg_attr(ac, "mail", "host") or DEFAULT_HOST,
        "apply.mail.port": _cfg_attr(ac, "mail", "port") or DEFAULT_PORT,
        "apply.mail.username": _cfg_attr(ac, "mail", "username") or "",
        "apply.mail.wait_s": _cfg_attr(ac, "mail", "wait_s") or DEFAULT_WAIT_S,
        "apply.mail.poll_s": _cfg_attr(ac, "mail", "poll_s") or DEFAULT_POLL_S,
        "apply.mail_backup.host": _cfg_attr(ac, "mail_backup", "host") or "",
        "apply.mail_backup.port": _cfg_attr(ac, "mail_backup", "port") or DEFAULT_PORT,
        "apply.mail_backup.username": _cfg_attr(ac, "mail_backup", "username") or "",
    }
    out: dict[str, Any] = {}
    for key, default in base.items():
        v = get_setting(key)
        v = default if v is None or str(v).strip() == "" else str(v).strip()
        if isinstance(default, int):
            try:
                v = int(v)
            except (TypeError, ValueError):
                v = default
        out[key] = v
    return out


def _setting(settings: Mapping[str, Any], key: str) -> Any:
    """`settings[key]` for the flat settings-table form (`{"apply.mail.host": ...}`,
    what `effective_settings` returns), else the nested form
    (`{"apply": {"mail": {"host": ...}}}`, how the web API groups it)."""
    if not isinstance(settings, Mapping):
        return None
    if key in settings:
        return settings.get(key)
    obj: Any = settings
    for part in key.split("."):
        if not isinstance(obj, Mapping):
            return None
        obj = obj.get(part)
    return obj


def mailbox_settings(settings: Mapping[str, Any], backup: bool = False) -> Mailbox:
    """The raw `apply.mail` (or `apply.mail_backup`) host, port, username; any may be ""."""
    pre = "apply.mail_backup." if backup else "apply.mail."
    try:
        port = int(_setting(settings, pre + "port") or DEFAULT_PORT)
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    return Mailbox(str(_setting(settings, pre + "host") or "").strip().lower(), port,
                   str(_setting(settings, pre + "username") or "").strip())


def backup_is_separate(settings: Mapping[str, Any]) -> bool:
    """True when `apply.mail_backup` names its own mailbox (host and username set)."""
    b = mailbox_settings(settings, backup=True)
    return bool(b.host and b.username)


def _contact(profile: Any, key: str) -> str:
    contact = (profile or {}).get("contact") if isinstance(profile, Mapping) else None
    v = contact.get(key) if isinstance(contact, Mapping) else None
    return str(v or "").strip().lower()


def mailbox_for(address: str, profile: Any, settings: Mapping[str, Any]) -> Optional[Mailbox]:
    """The mailbox that receives mail for `address` (§11.5), or None when it is
    not set up (no host or username) or the address is neither of the profile's.

    `contact.email` → `apply.mail`; `contact.backup_email` → `apply.mail_backup`
    when its host and username are set, else `apply.mail`.
    """
    a = (address or "").strip().lower()
    if not a:
        return None
    if a == _contact(profile, "email"):
        box = mailbox_settings(settings)
    elif a == _contact(profile, "backup_email"):
        box = (mailbox_settings(settings, backup=True) if backup_is_separate(settings)
               else mailbox_settings(settings))
    else:
        return None
    return box if box.host and box.username else None


def mailbox_password(box: Mailbox) -> Optional[Secret]:
    """The IMAP password from the vault: `jobscraper:imap:<host>`, user = username."""
    return vault.get(vault.imap_service(box.host), box.username)


def watcher_for(address: str, profile: Any, settings: Mapping[str, Any],
                **kw: Any) -> "MailWatcher":
    """A `MailWatcher` on `address`'s mailbox; `ApplyFailure(MAIL_NOT_SET_UP)` when
    the host, username or password is missing (§11.2, §11.5)."""
    box = mailbox_for(address, profile, settings)
    pw = mailbox_password(box) if box else None
    if box is None or pw is None:
        raise ApplyFailure(ReasonCode.MAIL_NOT_SET_UP,
                           "no mailbox host, username or password for this address")
    return MailWatcher(box.host, box.port, box.username, pw, **kw)


# ---------------------------------------------------------------- domains (§11.3)

def _host(url_or_host: str) -> str:
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


def employer_domain(careers_url: str) -> str:
    """The employer's registrable domain from its careers URL (§11.3); "" for an
    ATS host or an unparsable URL. `careers.dbs.com` → `dbs.com`;
    `www.dbs.com.sg` → `dbs.com.sg`."""
    host = _host(careers_url)
    if not host or domain_matches(host, ATS_DOMAINS):
        return ""
    labels = host.split(".")
    if len(labels) < 2:
        return ""
    if (len(labels) >= 3 and labels[-2] in _SLD and len(labels[-1]) == 2
            and labels[-1].isalpha()):
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


# ---------------------------------------------------------------- message parsing

class _HtmlText(HTMLParser):
    """HTML → text lines plus (href, anchor text) pairs."""
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
            self.parts.append("\n")
        if tag == "a":
            self._href = dict(attrs).get("href") or None
            self._anchor = []

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag == "a" and self._href is not None:
            self.links.append((self._href.strip(), " ".join("".join(self._anchor).split())))
            self._href = None
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        self.parts.append(data)
        if self._href is not None:
            self._anchor.append(data)

    def text(self) -> str:
        lines = (" ".join(l.split()) for l in "".join(self.parts).splitlines())
        return "\n".join(l for l in lines if l)


def _body(msg: email.message.EmailMessage) -> tuple[str, list[tuple[str, str]]]:
    """(text, [(url, anchor text)]): text/plain when present, else HTML as text."""
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
    links: list[tuple[str, str]] = []
    text = ""
    if html is not None:
        p = _HtmlText()
        try:
            p.feed(html)
            p.close()
        except Exception:                               # malformed HTML: keep what parsed
            pass
        links = list(p.links)
        text = p.text()
    if plain is not None:
        text = plain
    for m in URL_RE.finditer(text):
        links.append((m.group(0).rstrip(".,;:!?"), ""))
    return text, links


def _sender_domain(msg) -> str:
    addr = parseaddr(str(msg.get("From", "")))[1]
    return addr.rpartition("@")[2].strip().lower().rstrip(">") if "@" in addr else ""


def _addressed_to(msg, to_addr: str) -> bool:
    want = to_addr.strip().lower()
    for h in RECIPIENT_HEADERS:
        for v in msg.get_all(h, []) or []:
            if want in str(v).lower():
                return True
            for _name, addr in getaddresses([str(v)]):
                if addr.strip().lower() == want:
                    return True
    return False


def find_link(links: Sequence[tuple[str, str]], link_domains: Sequence[str]) -> Optional[str]:
    """The first http(s) link on an allowed domain that reads like verification (§11.1)."""
    for url, anchor in links:
        if not url.lower().startswith(("http://", "https://")):
            continue
        if not domain_matches(_host(url), link_domains):
            continue
        if VERIFY_WORDS.search(url) or VERIFY_WORDS.search(anchor or ""):
            return url
    return None


def find_code(text: str, otp_pattern: Optional[str]) -> Optional[str]:
    """The first line containing "code", searched with that line and the next (§11.1).

    Blank lines are dropped first, so "next" is the next line with text: plain
    mails put the code in its own paragraph ("...this code:", blank, "K7P2M9QX")."""
    pat = re.compile(otp_pattern or DEFAULT_OTP)
    lines = [l for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        if not CODE_LINE.search(line):
            continue
        m = pat.search("\n".join(lines[i:i + 2]))
        if m:
            return m.group(1) if m.groups() else m.group(0)
        return None
    return None


def _internaldate(meta: bytes) -> Optional[datetime]:
    t = imaplib.Internaldate2tuple(meta) if meta else None
    if t is None:
        return None
    return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)


def _date_header(msg) -> Optional[datetime]:
    try:
        d = parsedate_to_datetime(str(msg.get("Date", "")))
    except (TypeError, ValueError, IndexError):
        return None
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _fetched(data: Any) -> tuple[bytes, bytes]:
    """(meta, raw message) from an imaplib FETCH response."""
    for item in data or []:
        if isinstance(item, tuple) and len(item) >= 2:
            meta = item[0] if isinstance(item[0], bytes) else str(item[0]).encode()
            raw = item[1] if isinstance(item[1], bytes) else str(item[1]).encode()
            return meta, raw
    return b"", b""


def _imap_date(d: datetime) -> str:
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"


def _quote_folder(name: str) -> str:
    """imaplib sends the name as given; quote only names with a space or quote
    (`[Gmail]/Spam` goes bare, as Gmail and the design §11.1 call expect)."""
    if any(c in name for c in ' "'):
        return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return name


def _classify_login_error(exc: Exception) -> str:
    text = str(exc)
    if "application-specific password required" in text.lower():
        return ("app password rejected: Google wants an app password, not the account "
                "password. Create one at https://myaccount.google.com/apppasswords and "
                "store it with `python -m jobscraper mail set-password`")
    if re.search(r"authenticationfailed|invalid credentials|login failed|authenticate failed",
                 text, re.I):
        return ("login rejected: the username or app password is wrong (store a new one "
                "with `python -m jobscraper mail set-password`)")
    return f"login rejected by the server ({type(exc).__name__})"


# ---------------------------------------------------------------- the watcher (§11.1)

@dataclass
class _Candidate:
    when: datetime
    msg: Any


class MailWatcher:
    """Polls one mailbox, read-only, for a verification link or code."""

    def __init__(self, host: str, port: int, username: str, password: Secret,
                 timeout_s: float = 20, *,
                 connect: Optional[Callable[..., Any]] = None,
                 sleep: Optional[Callable[[float], None]] = None,
                 clock: Optional[Callable[[], float]] = None):
        if not isinstance(password, Secret):
            raise TypeError("MailWatcher takes the password as a contracts.Secret")
        self.host, self.port, self.username = host, int(port), username
        self._password = password
        self.timeout_s = timeout_s
        self._connect_fn = connect
        # None = look up time.sleep / time.monotonic at call time (patchable in tests)
        self._sleep_fn, self._clock_fn = sleep, clock

    def _sleep(self, s: float) -> None:
        (self._sleep_fn or time.sleep)(s)

    def _clock(self) -> float:
        return (self._clock_fn or time.monotonic)()

    def __repr__(self) -> str:
        return f"MailWatcher({self.host}:{self.port})"

    # -- connection
    def _connect(self):
        factory = self._connect_fn or imaplib.IMAP4_SSL   # looked up per call: patchable
        try:
            conn = factory(self.host, self.port, timeout=self.timeout_s)
        except (OSError, ssl.SSLError, imaplib.IMAP4.error) as exc:
            raise MailError(f"could not connect to {self.host}:{self.port} "
                            f"({type(exc).__name__})") from None
        try:
            conn.login(self.username, self._password.reveal())
        except imaplib.IMAP4.error as exc:
            _logout(conn)
            raise MailError(_classify_login_error(exc).replace(self.username, "<user>")) from None
        return conn

    def _open(self, conn, folder: str) -> bool:
        """EXAMINE the folder (read-only). False when it does not exist."""
        try:
            typ, _ = conn.select(_quote_folder(folder), readonly=True)
        except imaplib.IMAP4.abort:
            raise
        except imaplib.IMAP4.error:
            return False
        return typ == "OK"

    def _scan(self, conn, since_utc: datetime, seen: set) -> list[_Candidate]:
        out: list[_Candidate] = []
        floor = since_utc - timedelta(seconds=SLACK_S)
        for folder in FOLDERS:
            if not self._open(conn, folder):
                continue
            typ, data = conn.search(None, "SINCE", _imap_date(since_utc - timedelta(days=1)))
            if typ != "OK":
                continue
            ids = (data[0] or b"").split() if data else []
            for mid in reversed(ids):
                key = (folder, mid)
                if key in seen:
                    continue
                seen.add(key)
                typ, fdata = conn.fetch(mid, "(INTERNALDATE BODY.PEEK[])")
                if typ != "OK":
                    continue
                meta, raw = _fetched(fdata)
                if not raw:
                    continue
                msg = email.message_from_bytes(raw, policy=email.policy.default)
                when = _internaldate(meta) or _date_header(msg)
                if when is None or when < floor:
                    continue
                out.append(_Candidate(when, msg))
        return out

    # -- the wait
    def wait_for(self, *, since_utc: datetime, sender_domains: Sequence[str],
                 link_domains: Sequence[str], otp_pattern: Optional[str], want: str,
                 wait_s: int = DEFAULT_WAIT_S, poll_s: int = DEFAULT_POLL_S,
                 to_addr: Optional[str] = None) -> Verification:
        """Poll until a matching message yields what `want` asks for.

        want: "link" | "code" | "either". Raises
        `ApplyFailure(EMAIL_VERIFICATION_TIMEOUT)` after `wait_s`, and
        `ApplyFailure(MAIL_NOT_SET_UP)` when the mailbox refuses the login.
        """
        if want not in ("link", "code", "either"):
            raise ValueError(f"want must be link, code or either, not {want!r}")
        if since_utc.tzinfo is None:
            since_utc = since_utc.replace(tzinfo=timezone.utc)
        deadline = self._clock() + max(0, wait_s)
        conn = None
        seen: set = set()
        pending: list[_Candidate] = []          # matching senders, newest first
        try:
            while True:
                try:
                    if conn is None:
                        conn = self._connect()
                        seen = set()
                    pending.extend(self._scan(conn, since_utc, seen))
                except MailError as exc:
                    if "login rejected" in str(exc) or "app password" in str(exc):
                        raise ApplyFailure(ReasonCode.MAIL_NOT_SET_UP,
                                           "the mailbox rejected the login") from None
                    log.warning("mailbox unreachable, retrying: %s", exc)
                    conn = None
                except (imaplib.IMAP4.abort, OSError, ssl.SSLError) as exc:
                    log.warning("mailbox connection dropped (%s); reconnecting",
                                type(exc).__name__)
                    _logout(conn)
                    conn = None
                pending.sort(key=lambda c: c.when, reverse=True)
                found = self._pick(pending, sender_domains, link_domains, otp_pattern,
                                   want, to_addr)
                if found is not None:
                    log.info("verification mail found (%s) from %s",
                             found.kind, found.sender_domain)
                    return found
                pending.clear()                 # checked and not useful
                left = deadline - self._clock()
                if left <= 0:
                    raise ApplyFailure(ReasonCode.EMAIL_VERIFICATION_TIMEOUT,
                                       f"no verification mail within {wait_s} s")
                self._sleep(min(max(1, poll_s), left))
        finally:
            _logout(conn)

    @staticmethod
    def _pick(cands: list[_Candidate], sender_domains, link_domains, otp_pattern,
              want, to_addr) -> Optional[Verification]:
        for c in cands:
            sender = _sender_domain(c.msg)
            if not domain_matches(sender, sender_domains):
                continue
            if to_addr and not _addressed_to(c.msg, to_addr):
                continue
            text, links = _body(c.msg)
            stamp = c.when.astimezone(timezone.utc).strftime(TIME_FMT)
            if want in ("link", "either"):
                url = find_link(links, link_domains)
                if url:
                    return Verification("link", url, sender, stamp)
            if want in ("code", "either"):
                code = find_code(text, otp_pattern)
                if code:
                    return Verification("code", code, sender, stamp)
        return None


def _logout(conn) -> None:
    if conn is None:
        return
    try:
        conn.logout()
    except Exception:
        pass


# ---------------------------------------------------------------- mail test (§14.1)

def test_connection(host: str, port: int, username: str, password: Secret,
                    *, timeout_s: float = 20,
                    connect: Optional[Callable[..., Any]] = None) -> str:
    """Log in, EXAMINE INBOX, count messages. "ok: N messages in INBOX", or MailError."""
    w = MailWatcher(host, port, username, password, timeout_s, connect=connect)
    conn = w._connect()
    try:
        typ, data = conn.select("INBOX", readonly=True)
        if typ != "OK":
            raise MailError("logged in, but INBOX could not be opened read-only")
        try:
            n = int((data[0] or b"0").decode() if isinstance(data[0], bytes) else data[0])
        except (TypeError, ValueError, IndexError):
            n = 0
        return f"ok: {n} messages in INBOX"
    except (imaplib.IMAP4.abort, OSError) as exc:
        raise MailError(f"connection dropped ({type(exc).__name__})") from None
    finally:
        _logout(conn)


def newest_from(host: str, port: int, username: str, password: Secret, domain: str,
                *, timeout_s: float = 20,
                connect: Optional[Callable[..., Any]] = None) -> Optional[str]:
    """`mail test --find-from DOMAIN` (spike S-4): the UTC time of the newest
    INBOX/Spam message whose sender's domain matches, or None. Fetches only
    INTERNALDATE and the From header (PEEK), never a body."""
    w = MailWatcher(host, port, username, password, timeout_s, connect=connect)
    conn = w._connect()
    best: Optional[datetime] = None
    try:
        for folder in FOLDERS:
            if not w._open(conn, folder):
                continue
            typ, data = conn.search(None, "FROM", f'"{domain}"')
            if typ != "OK" or not data:
                continue
            for mid in reversed((data[0] or b"").split()[-50:]):
                typ, fdata = conn.fetch(mid, "(INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM)])")
                if typ != "OK":
                    continue
                meta, raw = _fetched(fdata)
                msg = email.message_from_bytes(raw or b"", policy=email.policy.default)
                if not domain_matches(_sender_domain(msg), [domain]):
                    continue
                when = _internaldate(meta)
                if when and (best is None or when > best):
                    best = when
                break                           # newest matching id in this folder
    finally:
        _logout(conn)
    return best.strftime(TIME_FMT) if best else None
