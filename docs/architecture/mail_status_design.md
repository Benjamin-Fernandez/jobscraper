# Application status from email (F-50; Q-60; D-90, D-91; KA-3)

Architect, 2026-11-02, branch `int/Q-60-mail-status`. Stage B. Input: `docs/research/mail_status_brief.md` (cited **MB §n**). ADR: `adr/0007-mail-status-imap.md`. Build plan: `mail_status_build_plan.md` (**BP**). Status: READY for stage-E review.

**In one paragraph.** With the owner's opt-in per mailbox, JobScraper reads one or more Gmail accounts over IMAP, read-only, using an app password from Credential Manager. While the web app runs, a timer starts `python -m jobscraper mail sync` as a separate process at start-up and then every 10 minutes. Each sync goes through every message after the stored cursor in All Mail and Spam. It reads headers first and fetches a body only for mail from a hiring platform or a tracked employer. It matches the message to one tracked application, classifies it with phrase rules (falling back to the local Qwen only for matched mail the rules can't sort), and then either moves the application forward automatically or leaves a suggestion. Every change carries a short quote from the email as evidence and can be undone. Nothing is ever written to the mailbox, no link is opened, and nothing from mail reaches a log.

---

## 1. Requirements (F-50, EARS)

| ID | Requirement |
|---|---|
| F-50a | WHEN the owner gives a Gmail address and app password in Settings or with `mail accounts add`, and ticks the consent box, THE SYSTEM SHALL test a read-only login first. Only if the login succeeds SHALL it store the password in Credential Manager (`jobscraper:imap:imap.gmail.com`, user = address) and record the account with the consent time and consent-text version. IF the login fails THE SYSTEM SHALL store nothing and SHALL say why in plain words. |
| F-50b | WHERE the application mailbox (`apply.mail`, D-72) is set up THE SYSTEM SHALL offer it first, as "Use this mailbox", without asking for its password again. |
| F-50c | THE SYSTEM SHALL read a mailbox only while its switch is on. WHEN the owner disconnects it THE SYSTEM SHALL delete its cursor, its processed-message log, its open suggestions and its account row, and its vault entry too unless email verification (`apply.mail`) also uses it. |
| F-50d | WHILE the web app runs THE SYSTEM SHALL sync every mailbox that is switched on, at start-up and every `mail_status.interval_min` minutes, without taking the JobManager slot. A sync SHALL process every message after the cursor up to the newest, in UID order, in the mailboxes Gmail flags `\All` and `\Junk`. |
| F-50e | WHEN the app starts after being closed THE SYSTEM SHALL continue from the stored cursor. No message SHALL be skipped, and none SHALL be processed twice: X-GM-MSGID dedupes across mailboxes, Spam moves and UIDVALIDITY changes. |
| F-50f | WHEN a mailbox has no cursor yet THE SYSTEM SHALL start from the earliest open application's date minus 1 day, but no earlier than `first_sync_max_days` (180) before now. |
| F-50g | THE SYSTEM SHALL open mailboxes only with EXAMINE and fetch only with BODY.PEEK or header items. It SHALL never send STORE, COPY, MOVE, EXPUNGE, APPEND or SMTP, never mark mail read, never open a link from mail and never load remote content. |
| F-50h | THE SYSTEM SHALL fetch a message body only after the header gate passes: the sender is a hiring platform or a tracked employer, or the message is in a thread already matched to an application, and it is not bulk mail or job-board mail. |
| F-50i | THE SYSTEM SHALL never treat the owner's own sent mail, auto-replies, verification, security-code, account or password mail (D-85), job alerts, talent-community newsletters, job-board mail or recruiter outreach as a status. |
| F-50j | THE SYSTEM SHALL match a message to an application only through the signals in §7. WHEN several applications fit THE SYSTEM SHALL not choose one: it SHALL leave a suggestion listing them. |
| F-50k | THE SYSTEM SHALL classify with the deterministic phrase rules in `config/mail_rules.yaml` first. Only for gated, matched messages the rules can't decide SHALL it ask the local model. The model SHALL choose one fixed category, or `unknown`, and give a quote that code checks appears in the message. |
| F-50l | WHEN a confident, unique match points to a *forward* status THE SYSTEM SHALL apply it automatically, offer and rejected included, with `app_events.by = 'mail'` and an evidence row. It SHALL never move a status backwards and never override an owner change newer than the email. A forward move that isn't confident or unique SHALL become a suggestion. |
| F-50m | WHEN the owner clicks Undo on an email-made change that is still the application's latest event THE SYSTEM SHALL restore the previous status and its `applied_at`. The same message SHALL never apply again. |
| F-50n | WHEN the owner accepts a suggestion THE SYSTEM SHALL apply it, if the application's status hasn't changed since the suggestion was made. WHEN the owner dismisses it THE SYSTEM SHALL close it. |
| F-50o | THE SYSTEM SHALL show, per mailbox, when it was last checked, the result counts, the folders it reads, and any failure in plain words. It SHALL offer "Check now" and the CLI verb `mail sync`. |
| F-50p | IF Gmail refuses the login THEN THE SYSTEM SHALL pause that mailbox, SHALL not retry on the timer, and SHALL say how to fix it. IF the network is down or Gmail throttles THEN THE SYSTEM SHALL back off and try again later. |
| F-50q | IF All Mail is hidden from IMAP THEN THE SYSTEM SHALL read INBOX and Spam instead and SHALL say so. IF the model is unavailable or busy THEN THE SYSTEM SHALL keep using the rules and SHALL retry the undecided messages later. |
| F-50r | THE SYSTEM SHALL log only counts, codes, account ids and platform domains: never an address, display name, subject, body, quote or password. It SHALL store no bodies or links, and SHALL store a subject (≤ 120 characters) and a quote (≤ 200 characters) only on evidence rows. |
| F-50s | THE SYSTEM SHALL store a message's outcome and the cursor advance in the same transaction. |
| F-50t | THE SYSTEM SHALL take sender platforms, gates and phrases from `config/mail_rules.yaml`, so that a new sender or phrase needs no code change (§14). |

**D-91 trace:** (a) → §4, §5, ADR. (b) → §4. (c) → §8. (d) → §5.6, §6.2, §13. (e) → §5.2.

---

## 2. Components and layering

### 2.1 Files

| File | Layer | Role |
|---|---|---|
| `src/jobscraper/imapread.py` (new) | **foundation** | The only module that speaks IMAP for F-50. `ImapTransport` implements `MailTransport`. Holds a command guard (§5.6), the special-use LIST lookup, the scan plans (§5.3), header and body parsing, the Authentication-Results check, and the helpers moved from `apply/mail.py` (`body_text`, `sender_domain`, `domain_matches`, `employer_domain`, `registrable_domain`, `login_code`) |
| `src/jobscraper/mailstatus/__init__.py`, `contracts.py` (new) | stage package | §3, transcribed verbatim (WP-S0) |
| `mailstatus/rules.py` | stage | Loads and validates the rules file; header gate, content gate, phrase classifier, quotes (§6). Pure |
| `mailstatus/match.py` | stage | Company and role normalisation, signals, matcher (§7). Pure |
| `mailstatus/transition.py` | stage | Rank order and the decision table (§8). Pure |
| `mailstatus/model.py` | stage | `SYSTEM`, `SCHEMA`, `user_prompt`, `parse` (§6.5). Builds and checks prompts only; never calls the model |
| `src/jobscraper/mailstatus_flow.py` (new) | **orchestrator** | `sync`, `connect`, `set_password`. Wires the vault, the transport, the store, the stage and `backends`. Owns the per-message order and the lease |
| `store.py` | foundation | The DDL and methods in §9. Plain values only: it never imports `mailstatus.contracts` (layering rule 1) |
| `config.py`, `config/config.yaml` | foundation | `mail_status:` block (§10.4); `assessment` added to `applications.statuses` |
| `config/mail_rules.yaml` (new) | data (researcher) | Platforms, job boards, gates, phrases (§6.1) |
| `cli.py` | CLI | `mail sync`, `mail accounts list\|add\|set-password\|on\|off\|remove` (§10.3) |
| `web/mailsync.py` (new) | web | `MailSyncRunner`: the timer, "Check now", and the connect child with the password on stdin (§10) |
| `web/routers/mail.py` (new), `web/routers/applications.py`, `web/api.py` | web | API §11.1; events gain `by` and `mail`; the runner starts in `create_app(mail_timer=True)` |
| `apply/mail.py` | stage (apply) | Uses `imapread` for helpers and the special-use Spam lookup (§5.7). No other behaviour change |
| `web/src/components/MailCard.vue`, `MailSuggestions.vue`, `MailEvidence.vue` (new); `tabs/Settings.vue`, `tabs/Applications.vue`, `stages.js`, `style.css` | SPA | §11 |

**Why this placement** (ADR-0007): F-50 is not applying, so it gets its own stage package, `mailstatus/`, with its own orchestrator, `mailstatus_flow.py`, beside `apply_flow`. Stages can't import `apply/`, so the IMAP primitives move down into the foundation (`imapread.py`), where both `apply/mail.py` and the new orchestrator can use them. The stage itself never touches IMAP or the model: the flow hands it parsed headers, plain body text and store rows. The stage depends only on its own contracts.

### 2.2 Layering changes (the tester edits `tests/test_layering.py`; WP-T0)

1. `FOUNDATION |= {"imapread"}`.
2. `STAGES |= {"mailstatus"}`; `DOTTED_PACKAGES |= {"mailstatus"}`; `CONTRACTS |= {"mailstatus.contracts"}` (so `imapread.py` and `web/` may import it, per D-73).
3. `ORCHESTRATOR |= {"mailstatus_flow"}` (no new `ORCHESTRATOR_EDGES`).
4. `WEB_MAY_IMPORT = (FOUNDATION - {"imapread"}) | PUBLISHER | CONTRACTS`. The web layer may use `vault` but never `imapread`.
5. A new test, `test_mail_modules_never_write_the_mailbox`, scans `imapread.py`, `mailstatus/**`, `mailstatus_flow.py` and `apply/mail.py` for `smtplib`, `.store(`, `.copy(`, `.move(`, `.expunge(`, `.append(`, `"STORE"`, `"COPY"`, `"MOVE"`, `"EXPUNGE"`, `"APPEND"` and `readonly=False`.
6. Self-check cases: `from jobscraper.mailstatus.contracts import X` is allowed for the foundation; `from jobscraper.mailstatus.rules import R` is forbidden; `test_apply_and_tailor_meet_only_through_their_flows` now also covers `mailstatus` (it iterates `DOTTED_PACKAGES`).

Order: WP-T0 must merge **together with** WP-S0. `test_every_v2_module_is_classified` fails as soon as `mailstatus/` exists without the new sets.

### 2.3 Document changes (planner; BP WP-P1)

- PRD §5: a new §5.6 "Application status from email (KA-3)" holding F-50a–t from §1.
- PRD §6: the KA-3 row adds F-50.
- PRD NF-02: add "mail-status account passwords".
- PRD NF-04 and §8.2: add "`mailstatus/` is a stage package, `mailstatus_flow.py` is its orchestrator, and `imapread.py` is the foundation module that speaks IMAP; `web/` may not import it".
- `docs/DESIGN.md` §8.2 module map: add the three modules; boundary rules: "web/ may import the foundation except `imapread.py`".
- `docs/OVERVIEW.md`: one paragraph.

---

## 3. Contracts: `src/jobscraper/mailstatus/contracts.py` (v1; WP-S0 transcribes verbatim)

```python
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
                             Reason.MODEL_UNAVAILABLE})


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
    tenants: tuple[str, ...]           # Workday tenants (first host label), lower-case
    board_slugs: tuple[str, ...]       # companies.slug for greenhouse/lever/ashby
    req_ids: tuple[str, ...]           # jobs.external_id with a digit, >= 5 characters
    threads: tuple[str, ...]           # gm_thrid of messages already matched to it
    owner_changed_at: Optional[str]    # latest app_events.at with by IS NULL
    last_event_at: Optional[str]


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
}
```

---

## 4. Mailbox connection and consent

**Account identity.** A mailbox is an `mail_accounts` row (§9) keyed on its lower-case address. Its password lives in the vault as `jobscraper:imap:imap.gmail.com` with user = the address. This is the same key shape as D-52, and `vault.imap_service` already says two Gmail accounts share the service and differ by username. Only Gmail is supported (D-90): the host is fixed to `GMAIL_HOST`, and `open()` refuses a server without `X-GM-EXT-1` (`not_gmail`).

**Connect (another Gmail).** Settings → the address, the app password and the consent box → `POST /api/mail/accounts`. The route parses the JSON body itself; no pydantic model holds the password, so a validation error can never echo it back (FastAPI's 422 echoes `input`). It wraps the password in `Secret` straight away. It then checks the inputs: an address that fully matches `ADDRESS_PATTERN` (contracts; web/ may not import `cli`), a consent version equal to `CONSENT_VERSION` and a non-empty password; anything else → `400 {"code": "bad_input", "detail": "Enter your Gmail address and app password, and tick the box."}`. Then it calls `MailSyncRunner.connect`. That runs `python -m jobscraper mail accounts add --address A --consent mail-consent:v1 --password-stdin --json` as a child process with `input=` the password plus a newline, so the password is never in argv, env or a file, and waits up to 45 s. The child runs `mailstatus_flow.connect`:
0. an address already in `mail_accounts` → print `{"result": "exists"}`, exit 1 (the route answers `409 {"code": "exists", "detail": "This mailbox is already connected."}`);
1. strip the whitespace (Gmail shows the code in groups of 4); `open()` (login, CAPABILITY, LIST); `close()`;
2. on a `MailFailure` → print `{"result": "<code>"}`, exit 1, store nothing;
3. on success → `vault.put` (which reads the entry back) → `store.mail_account_add(...)` with `consent_at=now` and `consent_version` → print `{"result": "ok", "account_id": N}`.

The route answers `200 {"ok": true, "account_id": N}` and asks the runner to sync now (trigger `connect`), or `400 {"code", "detail": SYNC_TEXTS[code]}`. The CLI form without `--password-stdin` prompts with `getpass` and prints `CONSENT_TEXT` first, asking for `y`.

**The application mailbox first (F-50b).** `GET /api/mail` reports `application_mailbox` when `apply.mail.host == imap.gmail.com`, `apply.mail.username` is set and the vault holds its entry (a local `vault.get`, no network). The card shows it above the "another Gmail" form. "Use this mailbox" → `POST /api/mail/accounts/application {consent_version}` → the child `mail accounts add --use-application --consent ...` runs the same steps without the password: it reuses the existing entry and stores the row with `shared_with_apply = 1`.

**Switch.** `PATCH /api/mail/accounts/{id} {"enabled": false}` is a store write only. A sync already running finishes its current message; the next sync skips the mailbox. The cursor and history are kept, so switching it back on continues where it stopped.

**Disconnect (F-50c).** `DELETE /api/mail/accounts/{id}`: `vault.delete` unless `shared_with_apply` (or the address equals `apply.mail.username` / `apply.mail_backup.username`), then `store.mail_account_delete(id)`. That deletes the cursors, the `mail_messages` rows, and the open or dismissed suggestions. It keeps the evidence rows of changes already made (they are part of the application's history, like notes) and drops their `account_id` link. Reconnecting later starts a new first sync.

**Change app password.** `PUT /api/mail/accounts/{id}/password` → the child `mail accounts set-password --id N --password-stdin` tests the login, then `vault.put`, then state `ok`, then a sync.

**Consent record.** `consent_at`, `consent_version` (`CONSENT_VERSION`). Changing `CONSENT_TEXT` in a way that widens what is read requires a new version; the card then asks again before the next sync (`consent_version != CONSENT_VERSION` → the sync skips the account, and the UI shows the consent box again).

---

## 5. Incremental sync (`imapread` + `mailstatus_flow`)

### 5.1 One sync

```
mail sync ─▶ store.mail_run_begin (lease) ──busy──▶ exit BUSY
  for each account (enabled, consent current, not PAUSED unless trigger in manual|cli|connect,
                    retry_after <= now):
    vault.get ─▶ transport.open() ─▶ folders by special-use
    ctx = store.mail_match_context()           (applications + threads, once per account)
    for role in (ALL or INBOX, JUNK):
      scan = transport.scan(role, cursor, window_start, limit, now)
      for h in scan.headers (ascending UID):           ── stop at deadline / body cap → PARTIAL
        seen(gm_msgid)?  ─yes─▶ store.mail_cursor_set(h.cursor_after)
        process(h) ─▶ store.mail_record(..., cursor=h.cursor_after)   ← one transaction (F-50s)
      if scan.complete: store.mail_cursor_set(scan.end_cursor)
    retry pending_model rows (§5.5)
    transport.close(); store.mail_account_set(state, counts)
  store.mail_purge(now); store.mail_run_end(...)
```

### 5.2 Folders (D-91 e)

`LIST "" "*"`; parse each line's flags. `\All` → ALL, `\Junk` → JUNK. The raw name goes back to EXAMINE unchanged (quoted as needed, never decoded, because localised names are modified UTF-7). If `\All` is missing → read `INBOX` (role INBOX) and note `all_mail_hidden`. If `\Junk` is missing → note `junk_hidden`. Folders are re-resolved every sync; a cursor whose `mailbox` name changed but whose UIDVALIDITY matches simply carries on.

### 5.3 Scan plans (pure `imapread.plan_scan(cursor, status, window_start)`)

`EXAMINE` gives `UIDVALIDITY` and `UIDNEXT`.

| Case | Plan |
|---|---|
| no cursor (first sync of this role) | `UID SEARCH SINCE <day(window_start) − 1>` → if empty: complete, `end_cursor = (validity, UIDNEXT − 1, now)`; else RANGE from the smallest UID |
| same validity, `UIDNEXT <= last_uid + 1` | nothing; complete, `end_cursor = (validity, last_uid, now)` |
| same validity | RANGE: `UID SEARCH UID <last+1>:*`, **drop UIDs ≤ last** (the `*` gotcha, MB §2) |
| validity changed | RESCAN: `UID SEARCH SINCE <day(last_scan_at) − 1>` under the new validity → RANGE from the smallest (empty → as the empty first-sync case, with the new validity); X-GM-MSGID dedupe drops what was already processed |

RANGE: sort ascending, take the first `limit` (`max_headers_per_sync`, default 2000), `UID FETCH` in chunks of 100 with `(UID INTERNALDATE RFC822.SIZE X-GM-MSGID X-GM-THRID X-GM-LABELS BODY.PEEK[HEADER.FIELDS (FROM REPLY-TO SUBJECT DATE LIST-ID PRECEDENCE AUTO-SUBMITTED X-AUTOREPLY X-AUTORESPOND AUTHENTICATION-RESULTS)])`. Each header's `cursor_after = (account, role, name, validity, uid, cursor.last_scan_at)`. `complete` is true when nothing was cut. Then `end_cursor = (validity, max(last processed, UIDNEXT − 1), now)`, because nothing below UIDNEXT remains unprocessed.

The first-sync window (F-50f) is fixed when the account is added: `first_sync_from = clamp(min(applied_at of non-terminal applications; first event at of to_apply ones) − 1 day, now − first_sync_max_days, now − 1 day)`. Mail older than it, found by a RANGE (for example mail moved in from elsewhere), is skipped as `too_old` from its header. X-GM-RAW is not used: SINCE plus the header gate is enough, and the RANGE plan keeps the cursor UID-ordered (MB §2).

### 5.4 Processing one message (flow; pure stage calls in bold)

1. **Dedupe:** `store.mail_seen_many(account, [gm_msgid])`; a hit advances only the cursor (no row; counted as `duplicates`).
2. **Header gate** `rules.header_gate(h, rules, own, window_start, threads, employer_regs)` (§6.2). A skip → `Outcome.SKIPPED` with the reason (and `sender_domain = ""` for `not_job_mail`, `own_mail` and `too_old`, so personal mail leaves no trace beyond its id).
3. **Body:** `transport.fetch_body(ref, max_body_bytes)` with `BODY.PEEK[]`. If `size > max_body_bytes` → `MailBody("", False, truncated=True)`: the subject alone is classified. `None` (the message was deleted in between) → `NO_CHANGE / vanished`. A dropped connection stops the scan without advancing (PARTIAL). At most `max_bodies_per_sync` (200); when the cap is reached the scan stops *before* this message.
4. **Content gate** `rules.content_gate(h, body, rules, in_matched_thread)` → a skip reason or None.
5. **Match** `match.match(h, body, ctx, rules)` (§7). `NONE` → `UNMATCHED / no_application`.
6. **Classify** `rules.classify(h, body, rules)` (§6.3). If the verdict is `UNKNOWN` with `status_words` (including a conflict), the model tier follows (§6.5). If the model is unavailable, deferred (`--defer-model`) or over `model_max_calls` → `PENDING_MODEL` with reason `model_unavailable` or `model_deferred`.
7. **Transition** `transition.decide(app, verdict, match, h, policy)` (§8) → `Change`.
8. `store.mail_record(...)`: the message row, plus the status change, the event and the evidence for `AUTO`, or the evidence row for `SUGGEST`, plus the cursor upsert, all in **one transaction** (F-50s). For `AUTO` the store re-reads the status inside the transaction. If it no longer equals `change.from_status` (the owner changed it a moment ago), the row is stored as `NO_CHANGE / owner_newer` and nothing else is written.

### 5.5 Pending-model retry

After the scans, for rows `outcome = pending_model`, `retries < 3` and `processed_at > now − retry_model_days`, oldest first, while the model budget lasts: `transport.refind(gm_msgid)` (`UID SEARCH X-GM-MSGID n` in ALL or INBOX, then JUNK) → `fetch_body` → steps 4–8 again, with `store.mail_resolve_pending` (an update of the row, no cursor). If the model is still unavailable → `retries + 1`. When retries or age run out → `SUGGEST(to=None, model_unavailable)`, with the quote from the first status-word sentence (or the subject). `refind` None → `NO_CHANGE / vanished`.

### 5.6 Read-only by construction (F-50g, D-91 d)

`imapread` wraps `imaplib.IMAP4_SSL` in `_ReadOnly`, which exposes only `login`, `capability`, `list`, `examine(name)` (= `select(name, readonly=True)`), `uid_search(*criteria)`, `uid_fetch(uids, items)`, `noop` and `logout`. It has no `store`, `copy`, `move`, `expunge`, `append` or `select(readonly=False)`. `uid_fetch` refuses any item string with `BODY[` not preceded by `.PEEK`, or with `RFC822` other than `RFC822.SIZE`. Bodies are parsed with `email.policy.default`; HTML is turned into text (no rendering, nothing remote); every URL is replaced by `[link]` before the text leaves `imapread`. No link list is returned. The connection limit (15 clients, MB §2) is respected with one connection per account, logged out after each sync.

### 5.7 `apply/mail.py` Spam fix (MB §7 item 8; its own WP-I2)

`MailWatcher._scan` and `newest_from` read `("INBOX", junk)`, where `junk = imapread.special_use_folders(conn).get(MailboxRole.JUNK)`, falling back to the current `FOLDERS[1]` when LIST gives no `\Junk` (non-Gmail hosts). `_body`, `_sender_domain`, `domain_matches`, `employer_domain` and `_host` become aliases of the `imapread` functions, so existing callers and tests keep working. Nothing else changes (F-36 behaviour, D-85 code reading).

---

## 6. Classification (`mailstatus/rules.py`, `mailstatus/model.py`)

### 6.1 The rules file `config/mail_rules.yaml` (researcher-owned; `cfg.mail_rules_path`)

```yaml
version: 1
platforms:                        # sender domains that carry hiring mail for many employers
  - {id: greenhouse, kind: ats, domains: [greenhouse-mail.io, greenhouse.io]}
  - {id: workday, kind: ats, domains: [myworkday.com], tenant_from_local_part: true}
  - {id: hirevue, kind: assessment, domains: [hirevue.com]}
job_boards: [linkedin.com, indeed.com, indeedemail.com, jobstreet.com, mycareersfuture.gov.sg, glassdoor.com]
company_suffixes: [pte, ltd, limited, private, inc, llc, plc, corp, corporation, co, company, group, holdings, singapore, sg]
common_word_names: [sea, grab]     # company names also used as ordinary words: body text alone never matches them
bulk: {list_id: true, precedence: [bulk, list, junk]}
gates:                             # lists of phrase entries
  auto_reply: [{id: ar.ooo, re: "out of (the )?office", in: subject}]
  account: [{id: acc.verify_email, re: "verify your email( address)?"}, {id: acc.security_code, re: "security code"}]
  job_alert: [{id: alert.jobs_you_may_like, re: "jobs you may (like|be interested in)"}]
  outreach: [{id: out.came_across, re: "came across your (profile|resume|cv)"}]
categories:                        # keys = Category values except no_change, unknown
  acknowledged:
    phrases: [{id: ack.thank_applying, re: "thank you for applying"}]
    weak: ["next steps"]
  interview:
    phrases: [{id: int.invite, re: "invite you to (an|a) interview"},
              {id: int.calendar, re: "interview", calendar: true}]
dominates:                         # when several categories hit, the key beats the listed ones
  offer: [acknowledged, assessment, interview]
  rejected: [acknowledged, assessment, interview, kept_on_file, posting_closed]
  interview: [acknowledged, assessment]
  assessment: [acknowledged]
  withdrawn: [acknowledged]
  posting_closed: [acknowledged, kept_on_file]
  kept_on_file: [acknowledged]
```

**Phrase entry:** `{id, re, in: any|subject|body (default any), calendar: false}`. `id` is unique across the file and matches `[a-z0-9_.]+`. `re` is compiled with `re.IGNORECASE` and wrapped as `(?<!\w)(?:re)(?!\w)`. `calendar: true` hits only when the body has a `METHOD:REQUEST` calendar part. **Weak** entries are plain words (same wrapping): they never decide anything; they only mark `status_words` (worth asking the model). **Validation** (`RulesError` naming the file and entry → sync code `rules_invalid`): `version == 1`, known keys only, category keys ⊆ `Category`, `dominates` keys and values ⊆ category keys, every regex compiles, domains lower-case without `@`, ids unique. Every sync is a new process, so an edit applies at the next check without a restart. Seed content: the brief's §3 and §4 tables (researcher WP-R1).

### 6.2 Gates (in this order; the first hit decides)

**Header gate** (no body yet):
1. `too_old`: `received_at < first_sync_from`.
2. `own_mail`: `\Sent` or `\Draft` in labels, or `from_addr` ∈ own addresses (every connected account, `apply.mail.username`, profile `contact.email` and `contact.backup_email`).
3. `auto_reply`: `auto_submitted` starts with `auto-replied` (RFC 3834; `auto-generated` is *not* skipped, because ATS notifications use it), or `autoreply_header`, or a `gates.auto_reply` phrase with `in: subject`.
4. `job_board`: `from_reg` or a Reply-To domain is in `job_boards`.
5. `not_job_mail` unless one of these holds: `from_reg` or a Reply-To domain matches a platform domain (suffix match), or an employer domain of any tracked application, or `gm_thrid` is in a matched thread.
6. `bulk`: `list_id` (when `bulk.list_id`) or `precedence` ∈ `bulk.precedence`, unless the message is in a matched thread.

**Content gate** (body text plus subject): `auto_reply`, then `account` (verification, security code, password reset, account created; the bare word "confirm" is deliberately absent, MB §4), then `job_alert` (includes talent-community welcomes and newsletters), then `outreach` (skipped only when not in a matched thread).

### 6.3 Rule classifier

`hits` = the categories with at least one phrase hit in the subject or text. `portal_update` drops out when anything else hits. The winner is the unique `w` with `hits − {w} ⊆ dominates[w]`. If there is one, the verdict is `Verdict(w, RULE, quote, rule_id=<first hit id of w>, status_words=True)`. With several hits and no winner → `Verdict(UNKNOWN, RULE, rule_id="conflict:a+b", status_words=True)`. With no hits → `UNKNOWN`, with `status_words` = any weak word hit, a calendar request, or ≥ 20% of the letters non-Latin (non-English mail goes to the model, MB §4).

**Quote:** the sentence holding the deciding hit (split on `(?<=[.!?])\s+` and newlines), whitespace collapsed. If it is longer than `QUOTE_MAX`, a window of `QUOTE_MAX` characters around the hit, cut at word boundaries and marked with "…". A rule quote is present by construction.

### 6.4 Domain decisions (MB §7 item 6)

| Case | Decision | Why |
|---|---|---|
| HireVue one-way ("on-demand", "digital", "pre-recorded" video interview) | **assessment** | No person on the other side; it is scored like a test. A *live* video interview booked through HireVue is **interview**. Phrases are filed that way |
| Posting closed or put on hold | its own category, `posting_closed` → **suggestion** to `rejected` (reason `closed_role`) | "On hold" can reopen, and "closed" doesn't always mean "you were rejected". "Position has been filled" stays a **rejected** phrase |
| Application withdrawn | `withdrawn` → automatic to `withdrawn` | A terminal forward move; the owner usually did it on the portal |
| Kept on file **with** a rejection phrase | `rejected` (dominates) | MB §4 |
| Kept on file **alone**, in mail about a matched application | `kept_on_file` → **suggestion** to `rejected` (reason `kept_on_file`) | It usually means "no", but it doesn't say so |
| "Welcome to our talent community" and newsletters | content gate `job_alert`: skipped | Not about an application |
| Portal "log in to view" notice | `portal_update` → **suggestion with no target** ("Log in to their site to see it") | Polarity unknown; never guess (MB §4) |
| Reminder, reschedule, "thank you for completing" | no special category; the stage phrase decides; forward-only makes it harmless | A reminder for an assessment does mean the assessment stage |
| **`assessment` status** | **added** to `applications.statuses` between `applied` and `interviewing` (config change, WP-F2), with a stage colour (WP-U2) | Online tests are a distinct, common step in Singapore new-grad hiring; filing them under `interviewing` would be wrong, and under `applied` would lose them. The owner may veto (§15) |

### 6.5 Model tier (`mailstatus/model.py`; the flow calls `backend.complete`)

**When:** a gated, matched (`STRONG`, `WEAK` or `AMBIGUOUS`) message whose rule verdict is `UNKNOWN` with `status_words`, while `mail_status.model` is on and the budget lasts.

`SYSTEM` (constant):
```
You read one email that a job applicant received about a job application. Say which update it gives. Never guess: if the email does not clearly say, answer unknown. Reply with JSON only.
category: acknowledged (the application was received), assessment (an invitation to a test, coding challenge or one-way recorded video interview), interview (an invitation to, or the scheduling of, an interview with a person), offer (a job offer), rejected (the application will not go further), withdrawn (the application was withdrawn), posting_closed (the role was closed or put on hold), kept_on_file (details kept for future roles, without saying no to this one), portal_update (asks the applicant to log in to see an update), no_change (a reminder or thank-you that changes nothing), unknown.
quote: the shortest sentence from the email that shows the category, copied exactly, at most 200 characters; "" for unknown.
```
`user_prompt(h, body, max_chars)`: `SUBJECT: <subject>\nEMAIL:\n<text cut to model_max_chars at a line break>`. Only the email itself goes in: no profile data, no employer list, no address. URLs are already `[link]`. `SCHEMA = {"type": "object", "properties": {"category": {"type": "string", "enum": [<Category values>]}, "quote": {"type": "string", "maxLength": 200}}, "required": ["category", "quote"]}`. The call is `backend.complete(SYSTEM, user, max_tokens=200, format=SCHEMA, temperature=0, seed=7, timeout=model_timeout_s)`.

`parse(reply, h, body) -> Verdict(tier=MODEL)`. Bad JSON, a category outside the enum, an empty quote for a non-unknown category, or a quote whose normalised form (casefolded, whitespace collapsed, "…" stripped) is not a substring of the normalised subject plus text → `UNKNOWN` with `status_words=True` and `rule_id="model:<why>"`. A `BackendError` or `backend.available == False` → pending (§5.4 step 6). **The boundary:** the model only picks a category from a fixed list and points at text; code checks the pointer, and model-tier verdicts are never automatic (§8 rule 11a). An email written to manipulate the model ("ignore your instructions…") can at most produce a suggestion.

---

## 7. Matching (`mailstatus/match.py`)

**Candidates:** every application (terminal ones included, so a late email about a closed application doesn't attach to a sibling), from `store.mail_match_context()`.

**Normalisation:** `norm_company(name)`: NFKD, accents stripped, casefold, `&` → `and`, punctuation → space, trailing `company_suffixes` tokens removed repeatedly ("Example Holdings Pte Ltd" → "example"). The variants of an application's employer are its `company_names`, its `board_slugs` (hyphens → spaces), its `tenants`, and the first label of each employer domain, all normalised. `norm_role(title)`: casefold, punctuation → space, collapsed, with bracketed suffixes such as "(m/f/d)" removed.

**Signals per application:**

| Signal | Holds when | Employer strength |
|---|---|---|
| `thread` | `gm_thrid ∈ app.threads` | decides alone |
| `employer_domain` | `from_reg` or a Reply-To domain ∈ `app.employer_domains` | strong |
| `tenant` | the platform has `tenant_from_local_part` and `from_local` ∈ `app.tenants` | strong |
| `name_in_sender` | a variant occurs as whole words in `norm(from_name)` | strong |
| `name_in_subject` | a variant occurs in `norm(subject)` | strong |
| `name_in_body` | a variant occurs in the normalised text. Variants of one token under 5 characters, or listed in `common_word_names`, count only in the raw text with the original capitalisation | weak |
| `role` | `norm_role(app.role)` occurs in the subject or text, or ≥ 80% of its tokens (at least 2) occur in one line | — |
| `req_id` | an `app.req_ids` value occurs as a whole word | — (counts as `role`) |

**Decision:**
1. Some application has `thread` → it, `STRONG`. If several do (a shared thread) → continue below with those as the candidates.
2. `E` = applications with an employer signal. If `E` is empty → `NONE`.
3. If `E` spans several companies (by normalised name), keep those with the strongest employer signal tier. A tie across companies → `AMBIGUOUS`.
4. `R` = the applications in `E` with `role` or `req_id`. If `|R| = 1` → that one, `STRONG`. If `|R| > 1` → `AMBIGUOUS(R)`.
5. If `|R| = 0` and `|E| = 1` → that one, `STRONG` with a strong employer signal, else `WEAK`.
6. If `|R| = 0` and `|E| > 1` → `AMBIGUOUS(E)`.

**Saved roles (`to_apply`)** are ordinary candidates: an acknowledgement moves them to `applied` (rank 0 → 1, automatic when confident), with `applied_at` set from the email date. **Mail for untracked roles:** `UNMATCHED / no_application`. Only its row (id, date, sender domain) and a count ("4 job emails matched no tracked application") are kept: no list and no subject. A list would mean storing subjects of mail about applications JobScraper doesn't track. That is a later feature if wanted (§15).

---

## 8. Status transitions (`mailstatus/transition.py`; D-91 c)

**Rank order** (config `mail_status.ranks`): `to_apply 0 < applied 1 < assessment 2 < interviewing 3 < offer 4`. **Terminal:** `rejected`, `withdrawn`. Moving to a terminal status from any open one counts as forward. **Category → status:** `acknowledged→applied, assessment→assessment, interview→interviewing, offer→offer, rejected→rejected, withdrawn→withdrawn, posting_closed→rejected, kept_on_file→rejected`. `policy.suggest_only = {posting_closed, kept_on_file}`. A target missing from `applications.statuses` is dropped from `category_status` when the `Policy` is built (doctor warns), so its category behaves like `unknown`.

`decide(app, verdict, match, h, policy) -> Change`. The first rule that fires wins:

| # | Condition | Change |
|---|---|---|
| 1 | category `no_change` | NONE `no_update` |
| 2 | category `unknown` (or no target) | `status_words` ? SUGGEST(to=None, `unclear`) : NONE `no_status_words` |
| 3 | category `portal_update` | SUGGEST(to=None, `portal_check`) |
| 4 | match `AMBIGUOUS` | rows 5–9 are evaluated per candidate, and the candidates they settle as NONE drop out. If none are left → NONE with the first candidate's reason. Otherwise → SUGGEST(to=target, `several_applications`, the remaining candidates). It never auto-picks, even when only one is left |
| 5 | `app.status` neither ranked nor terminal (an owner-added status) | SUGGEST(`custom_status`) |
| 6 | `app.owner_changed_at > h.received_at` | NONE `owner_newer` |
| 7 | `app.status` terminal | target terminal → NONE `terminal`; category ∈ {assessment, interview, offer} and `h.received_at > app.last_event_at` → SUGGEST(`reopen`); else NONE `terminal` |
| 8 | target == `app.status` | NONE `same_status` |
| 9 | target not terminal and rank(target) < rank(status) | NONE `backwards` |
| 10 | (forward) | go to the bar |
| 11 | **bar for AUTO**, in order: (a) `tier == MODEL` → SUGGEST `model_tier`; (b) category ∈ suggest_only → SUGGEST `closed_role` / `kept_on_file` / `suggest_only`; (c) match `WEAK` → SUGGEST `weak_match`; (d) `h.ref.role == JUNK` and category ∉ `junk_auto` → SUGGEST `from_spam`; (e) `require_auth` and `h.auth != PASS` → SUGGEST `unauthenticated` | else **AUTO `forward`** |

**"Confident, unique":** a rule-tier verdict, a `STRONG` match, a category that isn't suggest-only, not from Spam (except acknowledgements), and Gmail-authenticated. **How D-91 c's "anything else → a suggestion" is read:** forward moves that miss the bar become suggestions, and so do the explicit cases in rows 2–5 and 7. Backwards moves (row 9), same-status mail (row 8) and mail older than an owner change (row 6) change nothing *and* raise no suggestion. Without that, every late acknowledgement and every assessment reminder after an interview would ask a question. Out-of-order mail of that kind is common (MB §4).

**Who wrote it.** An automatic change writes `app_events(by='mail', at=now)`. `applied_at` is the email date when the move leaves `to_apply`. The evidence row has `kind='auto'`, `event_id`, the quote, the subject (≤ 120 characters), the sender domain, `received_at`, the category, tier, rule id or model, the reason and `prev_applied_at`. An accepted suggestion writes the same event (`by='mail'`), and its evidence row moves to `state='accepted'` with `event_id`.

**Undo (F-50m).** `POST /api/mail/evidence/{id}/undo` → `store.mail_undo(id, now)`. It is allowed only when `event_id` is the application's latest event. It writes `app_events(from=to_status, to=from_status, by=NULL)`, restores `applied_at` to `prev_applied_at` and sets the evidence `state='undone'`. If the event isn't the latest → 409 `not_latest` ("Can't undo: the status changed after this email. Set it by hand."). The message's row stays, so a re-sync can't re-apply it (dedupe by X-GM-MSGID).

**Accept / dismiss (F-50n).** `mail_accept(id, job_id, now)`: for an ambiguous suggestion, `job_id` must be one of `candidates`. The application's current status must equal `from_status` (for an ambiguous one, the status the chosen candidate had when the suggestion was made, stored in `candidates_json`); otherwise 409 `changed`. The target must still be forward per rows 6–9; otherwise 409 `changed`. On success the status is set, the event (`by='mail'`) and the evidence are written, and `mail_messages.job_id` is set, so the thread signal works for later mail. A suggestion with no target can only be dismissed ("Got it"). Open suggestions whose application status has since changed are marked `superseded` when listed.

---

## 9. Storage (`store.py`; additive; `SCHEMA_VERSION` 4 → 5)

```sql
-- F-50 mail status (mail_status_design §9). No bodies, no links, no passwords, no
-- addresses except the owner's own mailbox address in mail_accounts.
CREATE TABLE IF NOT EXISTS mail_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address TEXT NOT NULL UNIQUE,              -- lower-case Gmail address = IMAP user = vault user
    host TEXT NOT NULL DEFAULT 'imap.gmail.com',
    port INTEGER NOT NULL DEFAULT 993,
    vault_service TEXT NOT NULL,               -- jobscraper:imap:<host>; never the password
    shared_with_apply INTEGER NOT NULL DEFAULT 0,  -- 1 = the D-72 mailbox: disconnect keeps the vault entry
    enabled INTEGER NOT NULL DEFAULT 1,        -- the owner's switch
    consent_at TEXT NOT NULL, consent_version TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'ok',          -- AccountState
    state_code TEXT,                           -- SyncCode of the last failure, NULL when ok
    notes TEXT,                                -- comma list of NOTE_CODES
    fail_count INTEGER NOT NULL DEFAULT 0, retry_after TEXT,
    first_sync_from TEXT NOT NULL,             -- §5.3 window start, fixed at connect
    last_sync_at TEXT, last_ok_at TEXT,
    last_counts_json TEXT,                     -- COUNT_KEYS -> int
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mail_cursors (
    account_id INTEGER NOT NULL,
    role TEXT NOT NULL,                        -- MailboxRole
    mailbox TEXT NOT NULL, uidvalidity INTEGER NOT NULL,
    last_uid INTEGER NOT NULL,                 -- highest UID whose outcome is stored
    last_scan_at TEXT NOT NULL,
    PRIMARY KEY (account_id, role)
);
CREATE TABLE IF NOT EXISTS mail_messages (     -- one row per processed message: dedupe + audit
    account_id INTEGER NOT NULL,
    gm_msgid TEXT NOT NULL, gm_thrid TEXT,
    role TEXT NOT NULL, uidvalidity INTEGER NOT NULL, uid INTEGER NOT NULL,
    received_at TEXT NOT NULL,
    sender_domain TEXT NOT NULL DEFAULT '',    -- "" for not_job_mail / own_mail / too_old
    outcome TEXT NOT NULL, reason TEXT NOT NULL,
    category TEXT, tier TEXT, rule_id TEXT,
    job_id TEXT,                               -- the matched application
    match_json TEXT,                           -- {"kind","signals":[...],"candidates":[...]}; no text
    retries INTEGER NOT NULL DEFAULT 0,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (account_id, gm_msgid)
);
CREATE INDEX IF NOT EXISTS idx_mail_messages_thread ON mail_messages(gm_thrid);
CREATE INDEX IF NOT EXISTS idx_mail_messages_job ON mail_messages(job_id);
CREATE INDEX IF NOT EXISTS idx_mail_messages_outcome ON mail_messages(outcome, processed_at);
CREATE TABLE IF NOT EXISTS mail_evidence (     -- automatic changes and suggestions
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER,                        -- NULL after the mailbox is disconnected (no Gmail link then)
    gm_msgid TEXT NOT NULL,
    job_id TEXT,                               -- NULL for an ambiguous suggestion
    candidates_json TEXT,                      -- [{"job_id","status"}] when ambiguous
    kind TEXT NOT NULL CHECK (kind IN ('auto', 'suggestion')),
    state TEXT NOT NULL,                       -- auto: applied | undone; suggestion: open | accepted | dismissed | superseded
    event_id INTEGER,                          -- app_events.id once a change is made
    from_status TEXT, to_status TEXT,          -- to_status NULL: check the email or portal
    category TEXT NOT NULL, tier TEXT NOT NULL, rule_id TEXT, model TEXT,
    reason TEXT NOT NULL,
    received_at TEXT NOT NULL, sender_domain TEXT NOT NULL,
    subject TEXT NOT NULL,                     -- <= SUBJECT_MAX
    quote TEXT NOT NULL,                       -- <= QUOTE_MAX, verified present
    prev_applied_at TEXT,
    created_at TEXT NOT NULL, decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_mail_evidence_job ON mail_evidence(job_id);
CREATE INDEX IF NOT EXISTS idx_mail_evidence_open ON mail_evidence(kind, state);
CREATE INDEX IF NOT EXISTS idx_mail_evidence_event ON mail_evidence(event_id);
CREATE TABLE IF NOT EXISTS mail_sync_runs (    -- the lease and the last result
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger TEXT NOT NULL,                     -- startup | timer | manual | connect | cli
    state TEXT NOT NULL,                       -- running | ok | partial | failed | abandoned
    started_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL, finished_at TEXT,
    pid INTEGER, code TEXT, counts_json TEXT
);
```

**Methods** (plain values in, dicts out; the engineer writes the SQL):

| Method | Notes |
|---|---|
| `mail_accounts(enabled_only=False)`, `mail_account(id)`, `mail_account_add(address, *, host, port, vault_service, shared_with_apply, consent_version, first_sync_from, now) -> int`, `mail_account_set(id, **fields)`, `mail_account_delete(id)` | `add` on an existing address raises `ValueError`; `delete` per §4 |
| `mail_cursor(account_id, role)`, `mail_cursor_set(cursor: dict)` | upsert |
| `mail_seen_many(account_id, gm_msgids) -> set[str]` | |
| `mail_match_context() -> list[dict]` | the `AppCandidate` fields in one query (applications ⟕ jobs ⟕ companies, distinct `apply_attempts.tenant_host`, owner and last event times, threads from `mail_messages`) |
| `mail_record(*, account_id, message: dict, cursor: dict, change: dict \| None, evidence: dict \| None, now) -> dict` | **one transaction**; the re-check inside (§5.4 step 8); returns `{outcome, event_id, evidence_id}`. Uses a non-committing `_write_status(job_id, status, at, by, applied_at)` that `set_application_status` is refactored to call too |
| `mail_pending(account_id, now, retry_days)`, `mail_resolve_pending(account_id, gm_msgid, message, change, evidence, now)` | update, not insert; same single transaction |
| `mail_suggestions()`, `mail_accept(id, job_id, now) -> (bool, code)`, `mail_dismiss(id, now)`, `mail_undo(id, now) -> (bool, code)`, `mail_evidence_for(job_ids) -> dict` | §8. Codes: `ok`, `changed`, `not_latest`, `not_found`, `not_open` |
| `mail_run_begin(trigger, pid, now, ttl_s) -> Optional[int]` | `BEGIN IMMEDIATE`; a `running` row whose `heartbeat_at > now − ttl_s` → None; older running rows → `abandoned`; inserts and returns the id |
| `mail_run_heartbeat(id, now)`, `mail_run_end(id, state, code, counts_json, now)`, `mail_last_run()` | |
| `mail_purge(now)` | `mail_messages` with `job_id IS NULL` and `processed_at < now − 180 d`; suggestions `dismissed`/`superseded` older than 90 d; keeps the newest 200 `mail_sync_runs` |
| `application_events(job_id)` | **adds** `by` and `evidence_id` (LEFT JOIN `mail_evidence ON event_id`) |
| `delete_application(job_id)`, `relink_orphan_applications()` | also delete or move `mail_evidence` rows and null or move `mail_messages.job_id` |

**Retention.** Matched message rows and evidence live as long as the application. Unmatched and skipped rows live 180 days: by then the cursor is far past them and only the thread signal could use them, and skipped rows have no thread value. **Never stored:** bodies, links, display names, addresses of senders or recipients, Message-ID, attachments, the password, and subjects of unmatched mail.

**Migration and the concurrent session.** All five tables come from `CREATE TABLE IF NOT EXISTS`; `_migrate` needs no `ALTER`. `SCHEMA_VERSION = 5` with the comment `5: F-50 mail_* tables`. The number is only a record (the upsert never downgrades). If the concurrent session also bumps to 5, the merge sets `SCHEMA_VERSION = 6`, and the comment lists both changes. Their DDL is independent, so either order of opening is safe. Before the merge into `personal`, the live database is backed up (as before the SCHEMA 4 merge).

---

## 10. Running while the app runs

### 10.1 `web/mailsync.py`: `MailSyncRunner(cfg, data_dir, store_factory, job_manager: JobManager, command, clock=time.time)`

- **Not the JobManager.** A sync is its own child process, `python -m jobscraper mail sync --trigger <t> [--account N] [--defer-model]`, spawned with `web.jobs.child_env()` and `web.jobs._spawn_kwargs()`. It logs to `data/jobs/mail/<stamp>-mailsync.log` (newest 20 kept). It never takes the run/apply slot.
- **Timer** (a daemon thread). It starts only when `create_app(mail_timer=True)`, which `cmd_web` passes unless `JOBSCRAPER_MAIL_SYNC=0`. Tests and dev instances default to off. First tick after `startup_delay_s` (60 s), then every `interval_min` (10). The next tick comes after `catchup_delay_s` (60 s) when the last run ended `partial`. A tick spawns only if `mail_status.enabled`, the store lists an enabled account that isn't paused, and its own previous child has exited. A shutdown handler (`app.router.add_event_handler("shutdown", runner.stop)`) stops the thread; a running child finishes on its own.
- **Model courtesy:** `--defer-model` is added when `job_manager.current(tail=1)["state"] == "running"`, so the GPU stays with a run or an apply attempt; deferred messages are retried later (§5.5).
- `trigger("manual")` ("Check now") → spawns now, or reports `busy`. `connect(...)`, `use_application(...)` and `set_password(...)` run the short child of §4 synchronously (`subprocess.run(..., input=..., timeout=45)`), then trigger `connect`.
- `status()` → `{running, started_at, next_at}`; the rest of the state is read from the store.

### 10.2 Single flight across processes

The lease is `store.mail_run_begin(ttl_s = sync_timeout_s + 60)`. The child renews `heartbeat_at` after every chunk of headers and before each model call. A crashed child's lease goes stale after the TTL; the next run marks it `abandoned` and proceeds. The CLI, the live app and a second web process all go through the same lease. A dev instance has its own database copy, so it would have its own lease. That is why dev instances keep `JOBSCRAPER_MAIL_SYNC=0` (§15 R3).

**When the app isn't running:** nothing syncs (D-90: "when the application is running"). At the next start the first tick continues from each cursor; a backlog drains in `partial` runs one minute apart.

### 10.3 CLI (`cli.py`)

`mail sync [--trigger cli] [--account N] [--defer-model]`. It prints one line per account, `account 2: 37 scanned, 3 read, 1 updated, 2 to review, 4 unmatched (ok)`, and exits 0 for ok or partial, 1 otherwise. Also `mail accounts list` (id, address, on/off, state, last check), `mail accounts add (--address A | --use-application) [--password-stdin] [--json] [--consent VERSION]`, `mail accounts set-password --id N [--password-stdin]`, `mail accounts on|off --id N`, `mail accounts remove --id N`. Existing `mail set-password` and `mail test` (F-36) are unchanged.

### 10.4 Config (`config.py` `MailStatusConfig.from_raw`; `config/config.yaml`)

```yaml
mail_status:                   # F-50: application status from email (docs/architecture/mail_status_design.md)
  enabled: true                # master switch; each mailbox has its own switch in Settings
  interval_min: 10             # 5-120
  startup_delay_s: 60
  catchup_delay_s: 60
  first_sync_max_days: 180
  max_headers_per_sync: 2000
  max_bodies_per_sync: 200
  max_body_bytes: 5000000      # larger: classified from the subject
  sync_timeout_s: 600
  model: true
  model_max_calls: 20
  model_max_chars: 6000
  model_timeout_s: 60
  retry_model_days: 3
  require_auth: true           # automatic changes need Gmail DKIM/DMARC pass
  ranks: {to_apply: 0, applied: 1, assessment: 2, interviewing: 3, offer: 4}
  terminal: [rejected, withdrawn]
  category_status: {acknowledged: applied, assessment: assessment, interview: interviewing,
                    offer: offer, rejected: rejected, withdrawn: withdrawn,
                    posting_closed: rejected, kept_on_file: rejected}
  suggest_only: [posting_closed, kept_on_file]
  junk_auto: [acknowledged]
```
`applications.statuses: [to_apply, applied, assessment, interviewing, offer, rejected, withdrawn]`. `cfg.mail_rules_path = self._path("mail_rules", "config/mail_rules.yaml")`. Out-of-range values are clamped. Unknown keys are ignored, as in `TailorConfig`.

---

## 11. UI and API

### 11.1 API (`web/routers/mail.py`; JSON; writes guarded by `CrossSiteWriteGuard`)

| Route | Body → answer |
|---|---|
| `GET /api/mail` | `{enabled, interval_min, consent: {version, text}, application_mailbox: {address, ready, connected} \| null, accounts: [{id, address, enabled, shared_with_apply, state, code, message, notes: [{code, message}], last_sync_at, last_ok_at, first_sync_from, counts}], sync: {running, started_at, next_at, last: {state, code, finished_at}}, open_suggestions}` |
| `POST /api/mail/accounts` | `{address, app_password, consent_version}` → `200 {ok, account_id}` \| `400 {code, detail}` \| `409 {code: "exists", detail}`. Never echoes the input |
| `POST /api/mail/accounts/application` | `{consent_version}` → as above |
| `PUT /api/mail/accounts/{id}/password` | `{app_password}` → as above |
| `PATCH /api/mail/accounts/{id}` | `{enabled}` → the account view |
| `DELETE /api/mail/accounts/{id}` | → `{ok, vault_kept}` |
| `POST /api/mail/sync` | → `202 {started: true}` \| `409 {code: "busy", detail}` \| `400 {code: "no_mailbox"}` |
| `GET /api/mail/suggestions` | `{suggestions: [{id, job_id, company, role, status, to_status, category, reason, reason_text, quote, subject, sender_domain, received_at, candidates: [{job_id, company, role, status}], gmail_url}]}` |
| `POST /api/mail/suggestions/{id}/accept` | `{job_id?}` → `{ok, status}` \| `409 {code, detail}` |
| `POST /api/mail/suggestions/{id}/dismiss` | → `{ok}` |
| `POST /api/mail/evidence/{id}/undo` | → `{ok, status}` \| `409 {code, detail}` |
| `GET /api/applications` (changed) | each event gains `by` and `mail: {evidence_id, kind: auto\|accepted, state, quote, subject, sender_domain, received_at, gmail_url, undoable} \| null` |

`gmail_url` is built by the router from the account's address (joined through `account_id`; null after a disconnect) and `gm_msgid`: `https://mail.google.com/mail/?authuser=<address>#all/<hex(gm_msgid)>`. The X-GM-MSGID hex form is the web id (MB §2). It is a link we build to the owner's own Gmail, never one taken from mail; if the format ever stops working, only the button breaks.

### 11.2 Where it sits

**Settings:** a new section, "Email", holding `MailCard.vue`. **Applications:** `MailSuggestions.vue` sits above the stage strip and is hidden when empty. In the History timeline, an event with `by === 'mail'` gets a "From email" badge; expanding it (`MailEvidence.vue`) shows the quote, the sender domain and date, "Open in Gmail" and "Undo". `stages.js` adds `assessment: 'Assessment'`; `style.css` adds `--stage-assessment` (a teal between applied blue and interviewing amber), with `.pill` and `.status-select` rules.

### 11.3 Copy (design:ux-copy; sentence case, verbs on buttons)

| Element | Copy |
|---|---|
| Section title / intro | **Application updates from email** · "Connect Gmail and JobScraper updates your applications when employers write: received, assessment, interview, offer or rejection. Each change shows the email line it came from, and you can undo it." |
| Application mailbox | "**Your application mailbox** · {address} is already set up for email verification, so no password is needed." Button **Use this mailbox** |
| Another Gmail | Fields "Gmail address", "App password" (masked, `autocomplete="off"`). Help: "A 16-character code from your Google Account (it needs 2-Step Verification). Your normal Google password won't work." Link "Create an app password". Button **Connect mailbox** (disabled until consent is ticked); while working: "Checking the login…" |
| Consent | `CONSENT_TEXT`, then the checkbox "Read this mailbox for application updates" |
| Row status | ok: "Checked {relative time}. {applied} updated, {suggested} to review." · none yet: "Not checked yet. The first check reads mail from {date}." · running: "Checking…" · off: "Off. JobScraper isn't reading this mailbox." · failure: `SYNC_TEXTS[code]` · notes: `SYNC_TEXTS[note]` · pending: "{n} emails are waiting for the AI model." · unmatched: "{n} job emails matched no tracked application." |
| Row actions | Switch "Read this mailbox"; **Check now**; **Change app password**; **Disconnect** |
| Disconnect dialog | Title "Disconnect {address}?" Body: "JobScraper stops reading this mailbox and deletes its app password from Windows Credential Manager, its place in the mailbox and its list of checked emails. Status changes already made stay in each application's history." Shared mailbox: the password sentence becomes "The app password stays, because email verification for auto-apply uses it." Buttons **Disconnect** / **Keep connected** |
| Toasts | "Connected. The first check has started." · "Check finished: {n} updated, {m} to review." · "Back to {status}." |
| Suggestions panel | Title "From your email" with a count; subtitle "Updates JobScraper wasn't sure enough to make." Item: "{Company} · {Role}" / "Email says: {Status}" (or "Check the email") / "“{quote}”" / "{sender domain} · {date}" / `reason_text`. Buttons **Set to {Status}** and **Dismiss**; with no target: **Got it**; ambiguous: the select "Which application?" then **Set to {Status}**; plus **Open in Gmail** |
| Conflicts | Accept 409: "This application changed after the email. Set the status by hand if you still want this." · Undo 409: "Can't undo: the status changed after this email. Set it by hand." |
| Timeline badge | **From email**; tooltip "{sender domain}, {date}" |

---

## 12. Failure and degradation

| Condition | Detected by | Result | Account state / retry | Shown |
|---|---|---|---|---|
| No password in the vault | `vault.get` → None | account skipped | PAUSED `not_set_up` | `SYNC_TEXTS` |
| App password revoked or wrong | LOGIN `AUTHENTICATIONFAILED` / "invalid credentials" | stop this account | PAUSED `login_refused`; the timer never retries; Check now or a new password tries once | yes |
| Account password instead of an app password | "application-specific password required" | as above | PAUSED `app_password_required` | yes |
| Google security block | `[ALERT]` "log in via your web browser" | as above | PAUSED `web_login_required` | yes |
| Network down, DNS, TLS, timeout (20 s) | `OSError`, `ssl.SSLError`, `IMAP4.abort` | stop this account at a message boundary | ERROR `network`; `retry_after = now + interval × min(2^(fails−1), 6)` | yes |
| Throttled | `[OVERQUOTA]`, `[UNAVAILABLE]`, `[THROTTLED]`, "Too many simultaneous connections" | stop | BACKOFF `rate_limited`, `retry_after = now + 60 min` | yes |
| Not Gmail | no `X-GM-EXT-1` | refuse | ERROR `not_gmail`, `retry_after = now + 24 h` | yes |
| All Mail hidden / Spam hidden | LIST lacks `\All` / `\Junk` | read INBOX + Spam / skip Spam | note `all_mail_hidden` / `junk_hidden` | yes |
| UIDVALIDITY changed | EXAMINE | RESCAN (§5.3) + dedupe | ok; logged as a count | no |
| Connection dropped mid-scan | `IMAP4.abort`, `OSError` | cursor stays at the last stored message | ERROR `network` → PARTIAL at the next check | yes |
| Cap or deadline reached | flow counters | stop before the next message | run `partial`; next check in 60 s | "Still catching up" |
| Message deleted between header and body | FETCH empty | `NO_CHANGE / vanished`, advance | — | no |
| Body larger than `max_body_bytes` | `RFC822.SIZE` | classify the subject only | — | no |
| Model unavailable / deferred / over budget | `backend.available`, `BackendError`, flag, counter | `PENDING_MODEL`, retried ≤ 3 times within 3 days, then a `model_unavailable` suggestion | — | "{n} emails are waiting for the AI model." |
| Model answer unusable or quote not found | `parse` | `UNKNOWN` → `unclear` suggestion | — | via the suggestion |
| Rules file invalid | `RulesError` at start | nothing processed | run failed `rules_invalid` | yes |
| Database busy or locked | `sqlite3.OperationalError` in `mail_record` | rollback; cursor unchanged; stop | run failed `db_busy` | yes |
| Owner changed the status while a sync ran | re-check in `mail_record` | `NO_CHANGE / owner_newer` | — | no |
| Child crashed | stale lease | next run `abandoned` → continues from the cursors | — | last run "failed" |
| Unexpected exception | catch-all per account | stop that account; log the traceback with no mail values | ERROR `internal` | yes |
| `mail_status.enabled: false` | config | the timer doesn't spawn; `mail sync` exits `disabled` | — | yes |
| Consent text version changed | `consent_version != CONSENT_VERSION` | account skipped | — | the consent box again |

No retry storm: per account, at most one connect attempt per timer tick, with backoff on network errors and none on auth errors. Google can lock an account that keeps sending a wrong password; the PAUSED state prevents that.

---

## 13. Privacy and logging (principle 6, NF-01, NF-02)

- **Logs** (`log`, the CLI output, `data/jobs/mail/*.log`) may contain: account ids, counts, `SyncCode`/`Reason` values, platform ids and sender *domains* of matched or platform mail, job ids, UIDVALIDITY changes, timings. **Never:** an address (the account is "account 2"), a display name, a subject, a quote, body text, a URL, X-GM-MSGID or Message-ID, or the password. `MailFailure.detail` holds an exception class name only; login errors go through `imapread.login_code`, which returns a code, never the server text (the server text can echo the username).
- **Prompts** go only to the local backend and contain only the email (§6.5). No profile value is added.
- **The password** exists in the web request body, a `Secret` in the web process, the child's stdin, and Credential Manager. Never in argv, env, files, logs, the DB or responses.
- **Never opened:** links (URLs are replaced before the text leaves `imapread`) and remote content (HTML is parsed, never rendered).
- **Fixtures are synthetic** (`tests/fixtures/mail/`): employers like "Example Corp" on `example.com`/`example.org`, real platform domains (public), and no real mail. Golden cases are built from the *shapes* in MB §3–§4 (and later from the researcher's header-only counts, MB §7 item 1), never from copied messages.
- **Public repo:** `config/mail_rules.yaml` holds platform domains, public company names (`common_word_names`) and phrases only.

---

## 14. Extension walkthrough

**A new ATS sender** (example: a platform sending as `noreply@mail.newats.example`), in 4 steps and no code edits:
1. Add `{id: newats, kind: ats, domains: [newats.example]}` under `platforms` in `config/mail_rules.yaml`. If the local part names the employer, as Workday's does, add `tenant_from_local_part: true`.
2. Add a synthetic golden case: `tests/fixtures/mail/golden/newats_ack.eml` plus its expected row in `tests/fixtures/mail/golden.yaml` (`category`, `match`, `change`).
3. Run `python tests/run_tests.py -k mail_rules`. It validates the file and runs every golden case.
4. Done. The next sync is a new process that loads the file, so no restart is needed.

**A new phrase** (example: a rejection worded "we won't be taking your application further"), in 3 steps: add `{id: rej.not_taking_further, re: "(won't|will not) be taking your application (any )?further"}` under `categories.rejected.phrases`; add a golden case; run `-k mail_rules`.

**Only these need code:** a new category (a `Category` member, a `category_status` entry and the prompt list: contracts v2 plus an ADR note) or a new transport (implement `MailTransport`, choose it in `mailstatus_flow`: ADR-0007).

---

## 15. Decisions, owner questions, risks

**Decided here:** placement and the timer (ADR-0007); HireVue on-demand → assessment; `posting_closed` and lone `kept_on_file` → suggestions; the `assessment` status added; model-tier verdicts never automatic; automatic changes need Gmail authentication and, outside acknowledgements, not Spam; no unmatched list; no X-GM-RAW; no IDLE (polling every 10 minutes is enough, MB §2); disconnect keeps the evidence of changes already made.

**For the owner (with recommendations; none blocks the build):**
1. Which mailboxes: **recommend** the application Gmail only, at first. The personal one can be connected later from the same card (its first sync reads 180 days of headers, mostly gated out unread).
2. Automatic offer and rejected (D-91 c says yes): **recommend** keeping it, with this design's bar (authenticated, not Spam, a rule hit, a unique strong match) and Undo.
3. The new `assessment` status in the dropdown: **recommend** yes; vetoing it is a one-line config change (assessment mail then becomes a suggestion with no target).
4. The first real sync reads the owner's real mailbox: **recommend** that the owner triggers it ("Use this mailbox"), after the merge go-ahead (D-90).

**Risks:**
- R1: app passwords are withdrawn by Google → ADR-0007 fallback (`gmail.readonly` transport).
- R2: `require_auth` may turn too many ATS mails into suggestions if their DKIM doesn't align → the researcher's header-only spike (BP WP-R2) measures the pass rate, and `require_auth: false` is the switch.
- R3: a dev instance (8768) with a copied database would read the real mailbox → `JOBSCRAPER_MAIL_SYNC=0` is the default for dev (CLAUDE.md note: Coordinator).
- R4: the concurrent session's `SCHEMA_VERSION` or ADR number collides → §9 rule; renumber this ADR at merge if 0007 is taken.
- R5: common-word employer names mis-match → `common_word_names` plus the bar (a body-only name is `WEAK` → suggestion).
- R6: Qwen and an apply run competing for the GPU → `--defer-model`.

**D-91 notes for the Coordinator:** none of D-91 is contradicted. Two readings are recorded in §8: "anything else → suggestion" covers forward moves below the bar, not backwards or stale mail; and "confident" excludes model-tier verdicts.

---

## 16. Test strategy (the tester; details in BP §2)

Pure oracles for the rules, gates, classifier, matcher, transitions and model parse. A fake IMAP server (`tests/mail_support.py`) speaking LIST, EXAMINE, UID SEARCH and UID FETCH with X-GM items records every command: the "no STORE ever" and "PEEK only" oracles, cursor resume, UIDVALIDITY change, the `n:*` gotcha, first window, Spam-to-All-Mail dedupe. Store oracles: atomicity (inject a failure in `mail_record` → the cursor is unchanged), lease, undo, accept, dismiss, cascade. A flow canary test plants a marker string in a subject, a body, a display name and an address; the marker must appear in no log record, no CLI output and no job log. Web oracles: the password appears in no response, including the 422 and 400 paths; the timer is off in tests; Check now → 409 while busy; DELETE keeps a shared vault entry. Vitest: the card states and the suggestion actions.

---

## 17. Requirement map

| Req | Design | Build (BP) | Tests (BP §2) |
|---|---|---|---|
| F-50a | §4, §11.1, §11.3 | F3 `connect`, F4, F5, U1 | T5, T6 |
| F-50b | §4 | F3, F5, U1 | T6 |
| F-50c | §4, §9 (`mail_account_delete`) | F1, F5, U1 | T5, T6 |
| F-50d | §5.1, §5.2, §10.1, §10.2 | I1, F3, F5 | T4, T5, T6 |
| F-50e | §5.3, §5.4 step 1, §9 | I1, F1, F3 | T4, T5 |
| F-50f | §5.3 | I1, F3 | T4 |
| F-50g | §5.6, §2.2 rule 5 | I1, I2 | T0, T4 |
| F-50h | §6.2 header gate, §5.4 step 3 | S1, F3 | T2, T5 |
| F-50i | §6.2 | S1 (+ R1 data) | T2 |
| F-50j | §7 | S2 | T3 |
| F-50k | §6.3, §6.5 | S1, S3, F3 | T2, T3 |
| F-50l | §8 | S3, F1 | T3, T5 |
| F-50m | §8 Undo, §9 | F1, F5, U2 | T5, T6 |
| F-50n | §8 Accept / dismiss | F1, F5, U2 | T5, T6 |
| F-50o | §10.3, §11 | F4, F5, U1 | T6 |
| F-50p | §12 | I1 `login_code`, F3 | T4, T5 |
| F-50q | §5.2, §5.5, §12 | I1, F3 | T4, T5 |
| F-50r | §9, §13 | all; I1 (URL replacement), F3 (logging) | T5 canary, T6 |
| F-50s | §5.4 step 8, §9 `mail_record` | F1, F3 | T5 |
| F-50t | §6.1, §14 | S1, R1 | T2 |
| NF-02 | §4, §13 | F3, F5 | T6 |
| NF-04 | §2 | S0, T0 | T0 |
| MB §7 item 8 (Spam) | §5.7 | I2 | T4 |
