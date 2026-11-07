"""F-50 status transitions: what an email does to an application (MS section 8).

Design: docs/architecture/mail_status_design.md (MS) section 8 and D-91 c.
Requirements F-50l, F-50m (the change the store writes and undoes).

Pure: `decide` turns a verdict, a match and the application's current state
into a `Change`; the store writes it in one transaction and re-checks the
status there (MS 5.4 step 8). Forward-only: backwards, same-status and
owner-newer mail change nothing and raise no suggestion, because late
acknowledgements and assessment reminders after an interview are common
(MS 8, "how D-91 c is read"). Only a confident, unique, rule-tier match is
automatic; every other forward move becomes a suggestion.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Iterable, Optional, Sequence

from .contracts import (AppCandidate, AuthResult, Category, Change, ChangeKind, MailboxRole,
                        MailHeader, MatchKind, MatchResult, Policy, Reason, Tier, Verdict)

# MS 10.4 defaults, used for a key the raw config lacks.
DEFAULT_RANKS = {"to_apply": 0, "applied": 1, "assessment": 2, "interviewing": 3, "offer": 4}
DEFAULT_TERMINAL = ("rejected", "withdrawn")
DEFAULT_CATEGORY_STATUS = {"acknowledged": "applied", "assessment": "assessment",
                           "interview": "interviewing", "offer": "offer", "rejected": "rejected",
                           "withdrawn": "withdrawn", "posting_closed": "rejected",
                           "kept_on_file": "rejected"}
DEFAULT_SUGGEST_ONLY = ("posting_closed", "kept_on_file")
DEFAULT_JUNK_AUTO = ("acknowledged",)

# Row 7: the stages after which a closed application may be reopened (a suggestion).
REOPEN_CATEGORIES = frozenset({Category.ASSESSMENT, Category.INTERVIEW, Category.OFFER})
# Row 11 b: the reason a suggest-only category gives.
_SUGGEST_ONLY_REASON = {Category.POSTING_CLOSED: Reason.CLOSED_ROLE,
                        Category.KEPT_ON_FILE: Reason.KEPT_ON_FILE}
# Categories `category_status` can't map: decided by rows 1-3 alone.
_NO_TARGET = frozenset({Category.NO_CHANGE, Category.UNKNOWN})


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def build_policy(statuses: Iterable[str], raw: Any = None) -> Policy:
    """The `Policy` from `applications.statuses` and the `mail_status` block (a
    mapping, or an object with those attributes). A category whose target is
    not in `statuses`, or is neither ranked nor terminal, is dropped, so it
    behaves like `unknown` (doctor warns, MS 8). Unknown keys and values are
    ignored, as everywhere in config."""
    statuses = tuple(str(s) for s in statuses)
    ranks: dict[str, int] = {}
    for k, v in dict(_get(raw, "ranks", DEFAULT_RANKS)).items():
        try:
            ranks[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    terminal = frozenset(str(s) for s in _get(raw, "terminal", DEFAULT_TERMINAL))
    category_status: dict[Category, str] = {}
    for k, v in dict(_get(raw, "category_status", DEFAULT_CATEGORY_STATUS)).items():
        cat = _category(k)
        target = str(v) if v is not None else ""
        if (cat is None or cat in _NO_TARGET or target not in statuses
                or (target not in ranks and target not in terminal)):
            continue
        category_status[cat] = target
    return Policy(statuses=statuses, ranks=MappingProxyType(ranks), terminal=terminal,
                  category_status=MappingProxyType(category_status),
                  suggest_only=_categories(_get(raw, "suggest_only", DEFAULT_SUGGEST_ONLY)),
                  junk_auto=_categories(_get(raw, "junk_auto", DEFAULT_JUNK_AUTO)),
                  require_auth=as_bool(_get(raw, "require_auth", True), True))


_FALSE = frozenset({"false", "no", "0", "off", "n", "f"})
_TRUE = frozenset({"true", "yes", "1", "on", "y", "t"})


def as_bool(value: Any, default: bool) -> bool:
    """D-104 (g): a config boolean. `bool("false")` is True, so a quoted YAML
    'false' / 'no' / '0' would otherwise turn a safety switch on or off by
    accident. Anything unreadable keeps `default` (for require_auth: on)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        s = value.strip().lower()
        if s in _FALSE:
            return False
        if s in _TRUE:
            return True
    return default


def _get(raw: Any, key: str, default: Any) -> Any:
    if raw is None:
        return default
    value = raw.get(key) if hasattr(raw, "get") else getattr(raw, key, None)
    return default if value is None else value


def _category(value: Any) -> Optional[Category]:
    try:
        return Category(value)
    except ValueError:
        return None


def _categories(values: Iterable[Any]) -> frozenset[Category]:
    return frozenset(c for c in (_category(v) for v in values) if c is not None)


# ---------------------------------------------------------------------------
# Decision (MS 8 table; the first row that fires wins)
# ---------------------------------------------------------------------------

def decide(app: Optional[AppCandidate], verdict: Verdict, match: MatchResult, h: MailHeader,
           policy: Policy, *, candidates: Sequence[AppCandidate] = ()) -> Change:
    """MS 8 rows 1-11. For an AMBIGUOUS match, `candidates` are the applications
    named by `match.candidates` (the flow passes them; `app` is then only a
    fallback). An ambiguous change carries no from_status: each candidate's own
    status is what the flow stores with the suggestion (`remaining_candidates`)."""
    ambiguous = match.kind is MatchKind.AMBIGUOUS
    frm = None if ambiguous or app is None else app.status
    if match.kind is MatchKind.NONE:            # the flow stores UNMATCHED before this
        return Change(ChangeKind.NONE, Reason.NO_APPLICATION, frm)
    cat = verdict.category
    # 1
    if cat is Category.NO_CHANGE:
        return Change(ChangeKind.NONE, Reason.NO_UPDATE, frm)
    target = policy.category_status.get(cat)
    # 2 (portal_update has no target by design: row 3 decides it)
    if cat is Category.UNKNOWN or (target is None and cat is not Category.PORTAL_UPDATE):
        if verdict.status_words:
            return Change(ChangeKind.SUGGEST, Reason.UNCLEAR, frm)
        return Change(ChangeKind.NONE, Reason.NO_STATUS_WORDS, frm)
    # 3
    if cat is Category.PORTAL_UPDATE:
        return Change(ChangeKind.SUGGEST, Reason.PORTAL_CHECK, frm)
    # 4: rows 5-9 per candidate; never an automatic pick.
    if ambiguous:
        pool = _pool(app, match, candidates)
        settled = [(a, _settle(a, cat, target, h, policy)) for a in pool]
        left = [a for a, ch in settled if ch is None or ch.kind is not ChangeKind.NONE]
        if not left:
            if settled:
                first_app, first = settled[0]
                return Change(ChangeKind.NONE, first.reason, first_app.status)
            return Change(ChangeKind.NONE, Reason.NO_APPLICATION)
        return Change(ChangeKind.SUGGEST, Reason.SEVERAL_APPLICATIONS, None, target)
    if app is None:
        return Change(ChangeKind.NONE, Reason.NO_APPLICATION)
    # 5-9
    settled = _settle(app, cat, target, h, policy)
    if settled is not None:
        return settled
    # 10-11: a forward move; the bar for AUTO.
    return _bar(app, verdict, match, h, policy, target)


def remaining_candidates(app: Optional[AppCandidate], verdict: Verdict, match: MatchResult,
                         h: MailHeader, policy: Policy, *,
                         candidates: Sequence[AppCandidate] = ()) -> tuple[AppCandidate, ...]:
    """Row 4: the candidates a `several_applications` suggestion offers (the ones
    rows 5-9 don't settle as NONE), in the matcher's order. `Change` has no field
    for them, so the flow calls this to fill the suggestion's candidates."""
    if match.kind is not MatchKind.AMBIGUOUS:
        return ()
    target = policy.category_status.get(verdict.category)
    if target is None:
        return ()
    out = []
    for a in _pool(app, match, candidates):
        ch = _settle(a, verdict.category, target, h, policy)
        if ch is None or ch.kind is not ChangeKind.NONE:
            out.append(a)
    return tuple(out)


def _pool(app: Optional[AppCandidate], match: MatchResult,
          candidates: Sequence[AppCandidate]) -> list[AppCandidate]:
    """The ambiguous candidates, in `match.candidates` order when it names them."""
    cands = list(candidates) or ([app] if app is not None else [])
    if match.candidates:
        by_id = {a.job_id: a for a in cands}
        named = [by_id[j] for j in match.candidates if j in by_id]
        if named:
            return named
    return cands


def _settle(app: AppCandidate, cat: Category, target: str, h: MailHeader,
            policy: Policy) -> Optional[Change]:
    """Rows 5-9 for one application; None means a forward move (row 10)."""
    status = app.status
    terminal = policy.terminal
    # 5
    if status not in policy.ranks and status not in terminal:
        return Change(ChangeKind.SUGGEST, Reason.CUSTOM_STATUS, status, target)
    # 6
    if app.owner_changed_at and app.owner_changed_at > h.received_at:
        return Change(ChangeKind.NONE, Reason.OWNER_NEWER, status)
    # 7
    if status in terminal:
        if target in terminal:
            return Change(ChangeKind.NONE, Reason.TERMINAL, status)
        if cat in REOPEN_CATEGORIES and (not app.last_event_at or h.received_at > app.last_event_at):
            return Change(ChangeKind.SUGGEST, Reason.REOPEN, status, target)
        return Change(ChangeKind.NONE, Reason.TERMINAL, status)
    # 8
    if target == status:
        return Change(ChangeKind.NONE, Reason.SAME_STATUS, status)
    # 9 (moving to a terminal status from an open one is forward)
    rank = policy.ranks.get(target)
    if target not in terminal and rank is not None and rank < policy.ranks[status]:
        return Change(ChangeKind.NONE, Reason.BACKWARDS, status)
    return None


def _bar(app: AppCandidate, verdict: Verdict, match: MatchResult, h: MailHeader,
         policy: Policy, target: str) -> Change:
    """Row 11, in order: a rule-tier verdict, a category that isn't suggest-only,
    a STRONG match, not from Spam (acknowledgements excepted), Gmail-authenticated."""
    cat = verdict.category

    def suggest(reason: Reason) -> Change:
        return Change(ChangeKind.SUGGEST, reason, app.status, target)

    if verdict.tier is Tier.MODEL:
        return suggest(Reason.MODEL_TIER)
    if cat in policy.suggest_only:
        return suggest(_SUGGEST_ONLY_REASON.get(cat, Reason.SUGGEST_ONLY))
    if match.kind is MatchKind.WEAK:
        return suggest(Reason.WEAK_MATCH)
    if h.ref.role == MailboxRole.JUNK and cat not in policy.junk_auto:
        return suggest(Reason.FROM_SPAM)
    if policy.require_auth and h.auth != AuthResult.PASS:
        return suggest(Reason.UNAUTHENTICATED)
    return Change(ChangeKind.AUTO, Reason.FORWARD, app.status, target)
