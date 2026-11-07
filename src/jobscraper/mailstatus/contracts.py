"""F-50 application status from email: shared data shapes (mail_status_design.md §3).

Standard library only. Imported by imapread.py (foundation, D-73), the mailstatus
stage, mailstatus_flow.py, the CLI and web/. Never by store.py (it takes plain
values). Raise CONTRACT_VERSION on any change; a breaking change needs an ADR.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Mapping, Optional, Protocol, runtime_checkable

CONTRACT_VERSION = 1
CONSENT_VERSION = "mail-consent:v1"
MODEL_PROMPT_VERSION = "mail:v1"
GMAIL_HOST = "imap.gmail.com"
GMAIL_PORT = 993
QUOTE_MAX = 200                    # evidence quote, characters
SUBJECT_MAX = 120                  # subject kept on evidence rows, characters
TIME_FMT = "%Y-%m-%dT%H:%M:%S"     # store.TIME_FMT (UTC, naive text)
ADDRESS_PATTERN = r"[^@\s]+@[^@\s]+\.[^@\s]+"    # re.fullmatch; same shape as cli._EMAIL_RE


class MailboxRole(str, enum.Enum):
    ALL = "all"        # \All (All Mail)
    JUNK = "junk"      # \Junk (Spam)
    INBOX = "inbox"    # read instead of ALL only when \All is not listed


class AccountState(str, enum.Enum):
    OK = "ok"              # last check finished, or none yet
    ERROR = "error"        # last check failed; retried after retry_after
    BACKOFF = "backoff"    # Gmail asked to slow down; retried after retry_after
    PAUSED = "paused"      # login refused or no password; only the owner resumes it


class SyncCode(str, enum.Enum):
    OK = "ok"
    PARTIAL = "partial"                    # cap or deadline reached; continues next sync
    BUSY = "busy"                          # another sync holds the lease
    DISABLED = "disabled"                  # mail_status.enabled is false
    NOT_SET_UP = "not_set_up"              # no password in the vault
    LOGIN_REFUSED = "login_refused"
    APP_PASSWORD_REQUIRED = "app_password_required"
    WEB_LOGIN_REQUIRED = "web_login_required"
    NETWORK = "network"
    RATE_LIMITED = "rate_limited"
    NOT_GMAIL = "not_gmail"                # no X-GM-EXT-1 capability
    ALL_MAIL_HIDDEN = "all_mail_hidden"    # note: INBOX + Spam read instead
    JUNK_HIDDEN = "junk_hidden"            # note: Spam not read
    VAULT_ERROR = "vault_error"
    RULES_INVALID = "rules_invalid"
    DB_BUSY = "db_busy"
    INTERNAL = "internal"


PAUSING_CODES = frozenset({SyncCode.NOT_SET_UP, SyncCode.LOGIN_REFUSED,
                           SyncCode.APP_PASSWORD_REQUIRED, SyncCode.WEB_LOGIN_REQUIRED})
NOTE_CODES = frozenset({SyncCode.ALL_MAIL_HIDDEN, SyncCode.JUNK_HIDDEN})


class Category(str, enum.Enum):
    ACKNOWLEDGED = "acknowledged"
    ASSESSMENT = "assessment"          # tests, coding challenges, one-way video (HireVue on-demand)
    INTERVIEW = "interview"            # a conversation with a person, incl. live video
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    POSTING_CLOSED = "posting_closed"
    KEPT_ON_FILE = "kept_on_file"      # alone: details kept, no clear "no"
    PORTAL_UPDATE = "portal_update"    # "log in to view": polarity unknown
    NO_CHANGE = "no_change"            # model only: reminder or thank-you that changes nothing
    UNKNOWN = "unknown"


class Outcome(str, enum.Enum):         # mail_messages.outcome
    SKIPPED = "skipped"
    UNMATCHED = "unmatched"
    APPLIED = "applied"
    SUGGESTED = "suggested"
    NO_CHANGE = "no_change"
    PENDING_MODEL = "pending_model"


class Reason(str, enum.Enum):          # mail_messages.reason, mail_evidence.reason
    # skipped (gates, §6.2)
    TOO_OLD = "too_old"
    OWN_MAIL = "own_mail"
    AUTO_REPLY = "auto_reply"
    JOB_BOARD = "job_board"
    NOT_JOB_MAIL = "not_job_mail"
    BULK = "bulk"
    ACCOUNT_MAIL = "account_mail"
    JOB_ALERT = "job_alert"
    OUTREACH = "outreach"
    # unmatched
    NO_APPLICATION = "no_application"
    # no change (§8)
    NO_UPDATE = "no_update"
    NO_STATUS_WORDS = "no_status_words"
    SAME_STATUS = "same_status"
    BACKWARDS = "backwards"
    OWNER_NEWER = "owner_newer"
    TERMINAL = "terminal"
    VANISHED = "vanished"
    # applied
    FORWARD = "forward"
    # suggested
    MODEL_TIER = "model_tier"
    WEAK_MATCH = "weak_match"
    SEVERAL_APPLICATIONS = "several_applications"
    REOPEN = "reopen"
    CLOSED_ROLE = "closed_role"
    KEPT_ON_FILE = "kept_on_file"
    SUGGEST_ONLY = "suggest_only"
    FROM_SPAM = "from_spam"
    UNAUTHENTICATED = "unauthenticated"
    CUSTOM_STATUS = "custom_status"
    PORTAL_CHECK = "portal_check"
    UNCLEAR = "unclear"
    MODEL_UNAVAILABLE = "model_unavailable"    # also: pending
    BACKFILLED = "backfilled"                  # owner_newer, but the application was entered after the email (D-157 h)
    # pending
    MODEL_DEFERRED = "model_deferred"


SKIP_REASONS = frozenset({Reason.TOO_OLD, Reason.OWN_MAIL, Reason.AUTO_REPLY,
                          Reason.JOB_BOARD, Reason.NOT_JOB_MAIL, Reason.BULK,
                          Reason.ACCOUNT_MAIL, Reason.JOB_ALERT, Reason.OUTREACH})
SUGGEST_REASONS = frozenset({Reason.MODEL_TIER, Reason.WEAK_MATCH,
                             Reason.SEVERAL_APPLICATIONS, Reason.REOPEN,
                             Reason.CLOSED_ROLE, Reason.KEPT_ON_FILE, Reason.SUGGEST_ONLY,
                             Reason.FROM_SPAM, Reason.UNAUTHENTICATED,
                             Reason.CUSTOM_STATUS, Reason.PORTAL_CHECK, Reason.UNCLEAR,
                             Reason.MODEL_UNAVAILABLE, Reason.BACKFILLED})


class AuthResult(str, enum.Enum):      # Gmail's Authentication-Results (mx.google.com)
    PASS = "pass"      # dmarc=pass, or dkim=pass with d= aligned to the From domain
    FAIL = "fail"      # dmarc=fail
    NONE = "none"      # anything else, or no header


class Signal(str, enum.Enum):
    THREAD = "thread"
    EMPLOYER_DOMAIN = "employer_domain"
    TENANT = "tenant"
    NAME_IN_SENDER = "name_in_sender"
    NAME_IN_SUBJECT = "name_in_subject"
    NAME_IN_BODY = "name_in_body"
    ROLE = "role"
    REQ_ID = "req_id"


class MatchKind(str, enum.Enum):
    STRONG = "strong"
    WEAK = "weak"
    AMBIGUOUS = "ambiguous"
    NONE = "none"


class Tier(str, enum.Enum):
    RULE = "rule"
    MODEL = "model"


class ChangeKind(str, enum.Enum):
    AUTO = "auto"
    SUGGEST = "suggest"
    NONE = "none"


# ---------------------------------------------------------------- transport

@dataclass(frozen=True)
class Cursor:
    account_id: int
    role: MailboxRole
    mailbox: str           # the name LIST gave (re-resolved every sync)
    validity: int          # UIDVALIDITY; 0 for a transport without one
    last_uid: int          # highest position fully processed
    last_scan_at: str      # UTC TIME_FMT of the last scan that reached the end


@dataclass(frozen=True)
class MessageRef:
    role: MailboxRole
    mailbox: str
    validity: int
    uid: int


@dataclass(frozen=True)
class MailHeader:
    ref: MessageRef
    gm_msgid: str                      # X-GM-MSGID, decimal text
    gm_thrid: str                      # X-GM-THRID, decimal text
    labels: tuple[str, ...]            # X-GM-LABELS raw tokens; only \Sent and \Draft are read
    received_at: str                   # INTERNALDATE, UTC TIME_FMT
    size: int                          # RFC822.SIZE
    from_addr: str                     # lower-case
    from_name: str                     # display name, decoded
    from_domain: str                   # host part of from_addr
    from_reg: str                      # registrable domain of from_domain
    from_local: str                    # local part, lower-case
    reply_to_regs: tuple[str, ...]     # registrable domains of Reply-To
    subject: str                       # decoded
    list_id: bool                      # a List-ID header is present
    precedence: str                    # lower-case, "" when absent
    auto_submitted: str                # lower-case, "" when absent
    autoreply_header: bool             # X-Autoreply or X-Autorespond present
    auth: AuthResult
    cursor_after: Cursor               # the cursor once this message's outcome is stored


@dataclass(frozen=True)
class MailBody:
    text: str                  # text/plain, else HTML as text; every URL replaced by "[link]"
    calendar_request: bool     # a text/calendar part with METHOD:REQUEST
    truncated: bool = False    # size > max_body_bytes: text is "" (classify from the subject)


@dataclass(frozen=True)
class ScanResult:
    headers: tuple[MailHeader, ...]    # ascending UID, at most `limit`
    end_cursor: Optional[Cursor]       # store after the last header when complete; else None
    complete: bool                     # False: more messages remain (cap)


@dataclass(frozen=True)
class TransportInfo:
    capabilities: tuple[str, ...]
    folders: Mapping[MailboxRole, str]     # role -> mailbox name, from special-use flags
    notes: tuple[SyncCode, ...] = ()       # ALL_MAIL_HIDDEN, JUNK_HIDDEN


class MailFailure(RuntimeError):
    """A transport failure. `detail` never holds an address, subject or secret."""

    def __init__(self, code: SyncCode, detail: str = ""):
        super().__init__(f"{code.value}: {detail}" if detail else code.value)
        self.code = code
        self.detail = detail


@runtime_checkable
class MailTransport(Protocol):
    """Read-only access to one mailbox. imapread.ImapTransport implements it; a
    Gmail API (gmail.readonly) transport could replace it (ADR-0007)."""

    def open(self) -> TransportInfo: ...                  # login; raises MailFailure

    def scan(self, role: MailboxRole, cursor: Optional[Cursor], *, account_id: int,
             window_start: str, limit: int, now: str) -> ScanResult: ...

    def fetch_body(self, ref: MessageRef, max_bytes: int) -> Optional[MailBody]: ...  # None: gone

    def refind(self, gm_msgid: str) -> Optional[MailHeader]: ...   # pending-model retry

    def close(self) -> None: ...


# ---------------------------------------------------------------- matching and decisions

@dataclass(frozen=True)
class AppCandidate:
    """One tracked application as the matcher sees it (store.mail_match_context)."""
    job_id: str
    status: str
    company_names: tuple[str, ...]     # applications.company, companies.name (raw)
    role: str                          # applications.role or jobs.title (raw)
    employer_domains: tuple[str, ...]  # registrable; careers_url and a non-ATS posting host
    tenants: tuple[str, ...]           # lower-case first host labels: apply_attempts.tenant_host, plus any
                                       # jobs.url / applications.url / companies.careers_url host under a
                                       # rules `tenant_sites` suffix (match.tenants_from_hosts; E1)
    board_slugs: tuple[str, ...]       # companies.slug for greenhouse/lever/ashby
    req_ids: tuple[str, ...]           # jobs.external_id with a digit, >= 5 characters
    threads: tuple[str, ...]           # gm_thrid of messages already matched to it
    owner_changed_at: Optional[str]    # latest app_events.at with by IS NULL
    last_event_at: Optional[str]
    first_event_at: Optional[str] = None  # earliest app_events.at: when the application was entered (D-157 h)


@dataclass(frozen=True)
class MatchResult:
    kind: MatchKind
    job_id: Optional[str] = None
    candidates: tuple[str, ...] = ()   # AMBIGUOUS: the job ids that fit
    signals: tuple[Signal, ...] = ()
    platform: str = ""                 # rules platform id of the sender, or ""


@dataclass(frozen=True)
class Verdict:
    category: Category
    tier: Tier
    quote: str = ""          # <= QUOTE_MAX, verified present in subject or text
    rule_id: str = ""        # phrase id, "conflict:<a>+<b>", or "model:<detail>"
    status_words: bool = False
    model: str = ""


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    reason: Reason
    from_status: Optional[str] = None
    to_status: Optional[str] = None    # None with SUGGEST: "check the portal / the email"


@dataclass(frozen=True)
class Policy:
    """config mail_status (§10.4), checked against applications.statuses."""
    statuses: tuple[str, ...]
    ranks: Mapping[str, int]
    terminal: frozenset[str]
    category_status: Mapping[Category, str]
    suggest_only: frozenset[Category]
    junk_auto: frozenset[Category] = frozenset({Category.ACKNOWLEDGED})
    require_auth: bool = True


# ---------------------------------------------------------------- reports

COUNT_KEYS = ("scanned", "duplicates", "skipped", "bodies", "matched", "applied",
              "suggested", "unmatched", "pending_model", "model_calls")


@dataclass
class AccountReport:
    account_id: int
    code: SyncCode = SyncCode.OK
    notes: tuple[SyncCode, ...] = ()
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(COUNT_KEYS, 0))


@dataclass
class SyncReport:
    run_id: Optional[int]
    code: SyncCode
    accounts: list[AccountReport] = field(default_factory=list)


# ---------------------------------------------------------------- owner-facing text (§11.3)

CONSENT_TEXT = (
    "JobScraper will read this mailbox while the app is open, checking for new mail "
    "every few minutes. It reads the sender and subject of each email, and the text only "
    "of emails from employers and hiring sites. It never sends, deletes or moves mail, "
    "never marks it as read and never opens links. Nothing leaves this PC: only the "
    "local AI model may read an email the rules can't sort. You can turn this off or "
    "disconnect at any time.")

SYNC_TEXTS: dict[SyncCode, str] = {
    SyncCode.PARTIAL: "Still catching up. The next check starts in a minute.",
    SyncCode.BUSY: "A check is already running.",
    SyncCode.DISABLED: "Email updates are turned off in config.yaml (mail_status.enabled).",
    SyncCode.NOT_SET_UP: "Paused: no app password is stored for this mailbox. Enter it again to continue.",
    SyncCode.LOGIN_REFUSED: ("Paused: Gmail refused the app password. It may have been revoked, "
                             "which happens when you change your Google password. Create a new "
                             "app password and enter it here."),
    SyncCode.APP_PASSWORD_REQUIRED: ("Paused: Gmail needs an app password, not your Google "
                                     "password. Create one at myaccount.google.com/apppasswords."),
    SyncCode.WEB_LOGIN_REQUIRED: ("Paused: Google blocked the sign-in as unusual. Sign in to "
                                  "Gmail in your browser, then click Check now."),
    SyncCode.NETWORK: "Couldn't reach Gmail. JobScraper will try again later.",
    SyncCode.RATE_LIMITED: "Gmail asked JobScraper to slow down. It will try again in an hour.",
    SyncCode.NOT_GMAIL: "This mailbox doesn't look like Gmail. Only Gmail is supported.",
    SyncCode.ALL_MAIL_HIDDEN: ("All Mail is hidden from IMAP, so archived mail is missed. Reading "
                               "Inbox and Spam only. To fix it, in Gmail open Settings > Labels "
                               "and tick Show in IMAP for All Mail."),
    SyncCode.JUNK_HIDDEN: ("Spam is hidden from IMAP, so updates Gmail filed as spam are missed. "
                           "To fix it, in Gmail open Settings > Labels and tick Show in IMAP for Spam."),
    SyncCode.VAULT_ERROR: "Couldn't read the app password from Windows Credential Manager.",
    SyncCode.RULES_INVALID: ("The email rules file (config/mail_rules.yaml) has an error, so "
                             "nothing was checked. The log names the entry."),
    SyncCode.DB_BUSY: "The database was busy. The next check continues from here.",
    SyncCode.INTERNAL: ("Something went wrong during the check. It's in the log; the next "
                        "check continues from here."),
}

REASON_TEXTS: dict[Reason, str] = {
    Reason.FORWARD: "Updated from this email.",
    Reason.MODEL_TIER: "Read by the local AI model, so it needs your OK.",
    Reason.WEAK_MATCH: "The email names the employer, but not clearly this application.",
    Reason.SEVERAL_APPLICATIONS: "You have more than one application at this employer. Pick the one this email is about.",
    Reason.REOPEN: "This application is closed, but this email is newer.",
    Reason.CLOSED_ROLE: "The employer says the role is closed or on hold.",
    Reason.KEPT_ON_FILE: "The employer kept your details on file without saying no.",
    Reason.SUGGEST_ONLY: "JobScraper is set to ask you before this kind of change.",
    Reason.FROM_SPAM: "This email was in Spam.",
    Reason.UNAUTHENTICATED: "Gmail couldn't confirm who sent this email.",
    Reason.CUSTOM_STATUS: "This application has a status JobScraper doesn't change on its own.",
    Reason.PORTAL_CHECK: "The employer posted an update. Log in to their site to see it.",
    Reason.UNCLEAR: "The email is about this application, but JobScraper couldn't tell what changed.",
    Reason.MODEL_UNAVAILABLE: "JobScraper couldn't read this email because the AI model wasn't running.",
    Reason.BACKFILLED: "You added this application after this email arrived.",
}
