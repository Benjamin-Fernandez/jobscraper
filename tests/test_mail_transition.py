"""WP-T3 oracles: status transitions (mail_status_design.md 8, D-151 c; build plan WP-T3,
WP-S3). Verify: `python tests/run_tests.py -k mail_transition`. Every row of the MS 8 table,
in order; the golden change rows run in test_mail_rules.

Skip-clean until `jobscraper.mailstatus.transition` exists; after that
`test_mail_transition_oracles_are_live` fails if any oracle here still waits.

ASSUMED call shapes (build plan WP-S3):
  transition.build_policy(statuses, raw_mail_status_cfg) -> Policy
  transition.decide(app, verdict, match, h, policy, *, candidates=()) -> Change
For an AMBIGUOUS match these oracles pass the first candidate as `app` and every candidate,
in order, as `candidates`; "the first candidate's reason" (row 4) is candidates[0]'s.
Change has no candidates field (MS 3), so the remaining candidates of row 4 aren't checked.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_support import (  # noqa: E402
    TRANSITION, WAITING, app_candidate, assert_live, build_policy, decide, golden_policy_raw,
    golden_statuses, needs, note_waiting, unit_header,
)

_W0 = len(WAITING)
RECEIVED = "2026-10-26T09:00:00"       # unit_header's default Date, in UTC


def _c():
    from jobscraper.mailstatus import contracts
    return contracts


def _app(status="applied", job_id="a1", **kw):
    d = dict(job_id=job_id, status=status, company_names=("Example Corp",), role="Graduate Analyst",
             employer_domains=("example.com",), owner_changed_at="2026-09-01T09:00:00",
             last_event_at="2026-09-01T09:00:00")
    d.update(kw)
    return app_candidate(d)


def _h(role="all", auth="pass", received_at=RECEIVED):
    h, _b = unit_header("Example Corp <careers@example.com>", "Your application", "Hello.",
                        role=role, auth=auth)
    return dataclasses.replace(h, received_at=received_at)


def _v(category, tier="rule", status_words=True):
    c = _c()
    return c.Verdict(c.Category(category), c.Tier(tier), quote="Quoted sentence.",
                     rule_id="x.y" if tier == "rule" else "", status_words=status_words,
                     model="" if tier == "rule" else "local-model")


def _m(kind="strong", job_id="a1", candidates=(), signals=()):
    c = _c()
    sig = tuple(c.Signal(x) for x in signals)
    if kind == "ambiguous":
        return c.MatchResult(c.MatchKind.AMBIGUOUS, None, tuple(candidates), sig)
    return c.MatchResult(c.MatchKind(kind), job_id, (), sig)


def _decide(app, category, *, tier="rule", status_words=True, kind="strong", role="all",
            auth="pass", received_at=RECEIVED, policy=None, signals=()):
    return decide(app, _v(category, tier, status_words), _m(kind, app.job_id, signals=signals),
                  _h(role, auth, received_at),
                  policy or build_policy())


def _is(ch, kind, reason, to="<any>", frm="<any>"):
    c = _c()
    got = (ch.kind, ch.reason)
    assert got == (c.ChangeKind(kind), c.Reason(reason)), f"{ch} != {kind}/{reason}"
    if to != "<any>":
        assert ch.to_status == to, f"{ch}: to_status != {to}"
    if frm != "<any>":
        assert ch.from_status == frm, f"{ch}: from_status != {frm}"


# ------------------------------------------------------------------ the policy

@needs(TRANSITION)
def test_mail_transition_build_policy_reads_the_config_and_drops_missing_targets():
    c = _c()
    p = build_policy()
    assert p.statuses == golden_statuses()
    assert dict(p.ranks) == {"to_apply": 0, "applied": 1, "assessment": 2, "interviewing": 3, "offer": 4}
    assert p.terminal == frozenset({"rejected", "withdrawn"})
    assert p.category_status[c.Category.INTERVIEW] == "interviewing"
    assert p.category_status[c.Category.POSTING_CLOSED] == "rejected"
    assert all(isinstance(k, c.Category) for k in p.category_status)
    assert p.suggest_only == frozenset({c.Category.POSTING_CLOSED, c.Category.KEPT_ON_FILE})
    assert p.junk_auto == frozenset({c.Category.ACKNOWLEDGED}) and p.require_auth is True
    short = build_policy(statuses=[s for s in golden_statuses() if s != "assessment"])
    assert c.Category.ASSESSMENT not in short.category_status
    assert short.category_status[c.Category.OFFER] == "offer"
    raw = dict(golden_policy_raw(), require_auth=False)
    assert build_policy(raw=raw).require_auth is False


# ------------------------------------------------------------------ rows 1-3

@needs(TRANSITION)
def test_mail_transition_row1_no_change_changes_nothing_first():
    for kind in ("strong", "weak"):
        _is(_decide(_app(), "no_change", kind=kind), "none", "no_update")
    _is(_decide(_app("rejected"), "no_change", tier="model"), "none", "no_update")


@needs(TRANSITION)
def test_mail_transition_row2_unknown_or_no_target():
    _is(_decide(_app(), "unknown", status_words=True), "suggest", "unclear", to=None)
    _is(_decide(_app(), "unknown", status_words=False), "none", "no_status_words")
    _is(_decide(_app("rejected"), "unknown", status_words=True), "suggest", "unclear", to=None)
    short = build_policy(statuses=[s for s in golden_statuses() if s != "assessment"])
    _is(_decide(_app(), "assessment", policy=short), "suggest", "unclear", to=None)
    _is(_decide(_app(), "assessment", status_words=False, policy=short), "none", "no_status_words")


@needs(TRANSITION)
def test_mail_transition_row3_portal_update_asks_to_check_the_portal():
    for status in ("applied", "interviewing", "rejected"):
        _is(_decide(_app(status), "portal_update"), "suggest", "portal_check", to=None)
    _is(_decide(_app(), "portal_update", kind="weak", auth="none"), "suggest", "portal_check", to=None)


# ------------------------------------------------------------------ row 4 (ambiguous)

def _ambiguous(apps, category, **kw):
    c = _c()
    m = _m("ambiguous", candidates=[a.job_id for a in apps])
    return decide(apps[0], _v(category), m, _h(**kw), build_policy(), candidates=apps)


@needs(TRANSITION)
def test_mail_transition_row4_ambiguous_never_auto_picks():
    a, b = _app("applied", "a1"), _app("applied", "a2", role="Data Analyst")
    _is(_ambiguous([a, b], "interview"), "suggest", "several_applications", to="interviewing")
    # One candidate drops out (same status); the one left is still only suggested.
    a, b = _app("interviewing", "a1"), _app("applied", "a2")
    _is(_ambiguous([a, b], "interview"), "suggest", "several_applications", to="interviewing")
    a, b = _app("applied", "a1"), _app("offer", "a2")
    _is(_ambiguous([a, b], "assessment"), "suggest", "several_applications", to="assessment")
    # A row-5 suggestion keeps its candidate in.
    a, b = _app("on_hold", "a1"), _app("interviewing", "a2")
    _is(_ambiguous([a, b], "interview"), "suggest", "several_applications", to="interviewing")


@needs(TRANSITION)
def test_mail_transition_row4_all_candidates_drop_out_with_the_first_ones_reason():
    a, b = _app("offer", "a1"), _app("interviewing", "a2")
    _is(_ambiguous([a, b], "interview"), "none", "backwards")
    _is(_ambiguous([b, a], "interview"), "none", "same_status")
    a = _app("applied", "a1", owner_changed_at="2026-10-30T09:00:00")
    b = _app("rejected", "a2", last_event_at="2026-10-30T09:00:00")
    _is(_ambiguous([a, b], "interview"), "none", "owner_newer")
    _is(_ambiguous([b, a], "interview"), "none", "terminal")


# ------------------------------------------------------------------ rows 5-9

@needs(TRANSITION)
def test_mail_transition_row5_an_owner_added_status_is_only_suggested():
    p = build_policy(statuses=list(golden_statuses()) + ["on_hold"])
    _is(_decide(_app("on_hold"), "interview", policy=p), "suggest", "custom_status",
        to="interviewing", frm="on_hold")
    _is(_decide(_app("on_hold"), "rejected", policy=p), "suggest", "custom_status", to="rejected")


@needs(TRANSITION)
def test_mail_transition_row6_owner_newer_than_the_mail():
    newer = _app("applied", owner_changed_at="2026-10-27T09:00:00")
    _is(_decide(newer, "interview"), "none", "owner_newer")
    _is(_decide(_app("rejected", owner_changed_at="2026-10-27T09:00:00",
                     last_event_at="2026-10-01T09:00:00"), "interview"), "none", "owner_newer")
    same = _app("applied", owner_changed_at=RECEIVED)                  # not newer: goes on
    _is(_decide(same, "interview"), "auto", "forward", to="interviewing")
    _is(_decide(_app("applied", owner_changed_at=None), "interview"), "auto", "forward")


@needs(TRANSITION)
def test_mail_transition_row7_terminal_versus_reopen():
    late = dict(last_event_at="2026-10-01T09:00:00")
    for cat in ("assessment", "interview", "offer"):
        _is(_decide(_app("rejected", **late), cat), "suggest", "reopen", frm="rejected")
        _is(_decide(_app("withdrawn", **late), cat), "suggest", "reopen")
    _is(_decide(_app("rejected", **late), "interview"), "suggest", "reopen", to="interviewing")
    for cat in ("withdrawn", "posting_closed", "kept_on_file"):                    # terminal target
        _is(_decide(_app("rejected", **late), cat), "none", "terminal")
    # Row 7a (D-161): an acknowledgement or rejection newer than the closed application's last event,
    # with no role / req id / thread hit, may be about an application not added -> a question.
    for cat in ("rejected", "acknowledged"):
        _is(_decide(_app("rejected", **late), cat), "suggest", "maybe_untracked", to=None)
        for sig in ("role", "req_id", "thread"):               # names a tracked closed role: silent
            _is(_decide(_app("rejected", **late), cat, signals=(sig,)), "none", "terminal")
    # Employer-only signals are what a 7a match carries.
    _is(_decide(_app("rejected", **late), "rejected", signals=("employer_domain", "name_in_body")),
        "suggest", "maybe_untracked", to=None)
    older = dict(last_event_at="2026-10-28T09:00:00", owner_changed_at="2026-09-01T09:00:00")
    _is(_decide(_app("rejected", **older), "interview"), "none", "terminal")
    _is(_decide(_app("rejected", last_event_at=RECEIVED), "offer"), "none", "terminal")


@needs(TRANSITION)
def test_mail_transition_row8_same_status_and_row9_backwards_raise_nothing():
    _is(_decide(_app("applied"), "acknowledged"), "none", "same_status")
    _is(_decide(_app("interviewing"), "interview"), "none", "same_status")
    _is(_decide(_app("interviewing"), "assessment"), "none", "backwards")
    _is(_decide(_app("offer"), "acknowledged"), "none", "backwards")
    _is(_decide(_app("assessment"), "acknowledged", kind="weak", auth="none"), "none", "backwards")
    # A terminal target from any open status is forward.
    _is(_decide(_app("offer"), "rejected"), "auto", "forward", to="rejected", frm="offer")
    _is(_decide(_app("to_apply"), "withdrawn"), "auto", "forward", to="withdrawn")


# ------------------------------------------------------------------ rows 10-11 (the bar)

@needs(TRANSITION)
def test_mail_transition_forward_and_confident_is_automatic():
    _is(_decide(_app("to_apply"), "acknowledged"), "auto", "forward", to="applied", frm="to_apply")
    _is(_decide(_app("applied"), "assessment"), "auto", "forward", to="assessment", frm="applied")
    _is(_decide(_app("assessment"), "interview"), "auto", "forward", to="interviewing")
    _is(_decide(_app("interviewing"), "offer"), "auto", "forward", to="offer")
    _is(_decide(_app("applied"), "offer"), "auto", "forward", to="offer")          # skipping ranks
    # Spam: acknowledgements are in junk_auto.
    _is(_decide(_app("to_apply"), "acknowledged", role="junk"), "auto", "forward", to="applied")
    no_auth = build_policy(raw=dict(golden_policy_raw(), require_auth=False))
    _is(_decide(_app(), "interview", auth="none", policy=no_auth), "auto", "forward")


@needs(TRANSITION)
def test_mail_transition_row11_the_bar_in_order():
    junk_noauth = dict(role="junk", auth="none")
    # (a) model tier first, whatever else misses the bar
    _is(_decide(_app(), "interview", tier="model"), "suggest", "model_tier", to="interviewing", frm="applied")
    _is(_decide(_app(), "posting_closed", tier="model", kind="weak", **junk_noauth), "suggest", "model_tier")
    # (b) suggest-only categories
    _is(_decide(_app(), "posting_closed"), "suggest", "closed_role", to="rejected")
    _is(_decide(_app(), "kept_on_file"), "suggest", "kept_on_file", to="rejected")
    _is(_decide(_app(), "posting_closed", kind="weak", **junk_noauth), "suggest", "closed_role")
    extra = build_policy(raw=dict(golden_policy_raw(),
                                  suggest_only=["posting_closed", "kept_on_file", "offer"]))
    _is(_decide(_app("interviewing"), "offer", policy=extra), "suggest", "suggest_only", to="offer")
    # (c) weak match
    _is(_decide(_app(), "interview", kind="weak"), "suggest", "weak_match", to="interviewing")
    _is(_decide(_app(), "interview", kind="weak", **junk_noauth), "suggest", "weak_match")
    # (d) from Spam, unless the category is in junk_auto
    _is(_decide(_app(), "interview", role="junk"), "suggest", "from_spam", to="interviewing")
    _is(_decide(_app(), "interview", **junk_noauth), "suggest", "from_spam")
    _is(_decide(_app("to_apply"), "acknowledged", **junk_noauth), "suggest", "unauthenticated")
    # (e) unauthenticated
    for auth in ("none", "fail"):
        _is(_decide(_app(), "interview", auth=auth), "suggest", "unauthenticated", to="interviewing")


@needs(TRANSITION)
def test_mail_transition_rows_fire_in_table_order():
    """Where two rows hold, the earlier one decides (MS 8: "the first rule that fires wins")."""
    newer = dict(owner_changed_at="2026-10-27T09:00:00")
    _is(_decide(_app("rejected", **newer), "no_change"), "none", "no_update")         # 1 before 6, 7
    _is(_decide(_app("rejected", **newer), "portal_update"), "suggest", "portal_check")   # 3 before 6, 7
    p = build_policy(statuses=list(golden_statuses()) + ["on_hold"])
    _is(_decide(_app("on_hold", **newer), "interview", policy=p), "suggest", "custom_status")  # 5 before 6
    _is(_decide(_app("interviewing", **newer), "assessment"), "none", "owner_newer")  # 6 before 9
    _is(_decide(_app("interviewing"), "interview", tier="model"), "none", "same_status")  # 8 before 11
    a, b = _app("applied", "a1"), _app("applied", "a2")                                # 1-3 before 4
    _is(_ambiguous([a, b], "no_change"), "none", "no_update")
    _is(_ambiguous([a, b], "portal_update"), "suggest", "portal_check", to=None)
    _is(_ambiguous([a, b], "unknown"), "suggest", "unclear", to=None)


def test_mail_transition_oracles_are_live():
    assert_live(TRANSITION, _W0, "test_mail_transition")


note_waiting("test_mail_transition", _W0)
