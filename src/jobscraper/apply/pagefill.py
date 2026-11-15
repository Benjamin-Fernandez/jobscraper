"""One form page: read, lock, ask, guard, then change the page (D-78; llm_fill_design.md
§8 steps 1-13; WP-R3).

    fill_page(page, nav, ctx, rctx, services) -> PageOutcome

The order is the point (review M9, TR-7; LF §8, §10 E7):
  1-6  read the page, build the facts, lock what the program knows, replay cached
       decisions, ask the model about the rest (pick / recheck / second follow-ups),
       then `guards.decide` turns everything into Answers plus entry and G9 actions;
  7    a required field still unknown -> return with NOTHING on the page changed
       (no fill, clear, reset, delete or add; no classify either: nothing is typed);
  8    `services.classify(page)` (CAPTCHA / bot check raises, AD §8.4) and the deadline;
  9    entry deletes, entry adds (each added entry gets its own round), fills (only
       values that differ from what is shown; uploads go into `ctx.uploaded`), G9
       clears/resets/unticks, each with the widgets' strict read-back;
  10   revealed fields: re-read, fields not seen before get steps 3-9 (at most
       `max_reveal_rounds`); a required one left unknown stops the page;
  11   corrective pass: fields that failed or show a site error are asked again with
       their error (`llm_fill` marks such a chunk "corrective"), decided, filled once;
  12   `page.scan_required`: required controls still empty or in error get one more
       round; then unknown -> unknown_required, else fill_failed;
  13   fresh decisions go into the decision cache (§13.3).

Fill policy `always` (D-208, Q-121 WP-C1; llm_first_fill_design §4.1, §4.5, §8): a
second path, `_fill_page_always`, chosen by `rctx.fill_policy` (the code default is
`strict`, so the path above stays as built). It reads the page twice around a settle
wait (A1), binds entry slots to profile entries (`facts.bind_slots`), hands the fields
to `always.fill_page_always` (A2-A6: every field gets an answer), then applies them
through the same widgets with read-back (A7: classify first, surplus slots, fills, Adds,
revealed fields, one verification read) and one corrective round (A8). It never
returns `unknown_required`; `always.AlwaysStop` propagates to the flow.

A stop after step 9 leaves the page partly changed; nothing is ever submitted here
(the flow stops the attempt). Transport failures (BackendError, timeouts, a reply
still cut after its retry) and an exhausted deadline return `transport_failed`
with the affected rows noted "transport: ..." (`questions.TRANSPORT_NOTES`); they
are never captured as questions (§11).

The pure steps live in lane M's modules (`facts`, `locks`, `llm_fill`, `guards`);
this module only sequences them and touches the page through `page` / `widgets`.
No SQL and no direct model I/O here (NF-04): the model is reached through
`llm_fill` with `services.backend`, the cache through `services.cache_*`.

Field identity (review F6): reader keys can change when a site re-creates an
element, so every field's audit key is kept from the first time it is seen, and
origins (`known`) are recorded under both keys.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field as dc_field, replace as _replace
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from ..backends import BackendError
from .. import applicant
from . import always as AL
from . import briefing as BR
from . import facts as F
from . import guards as G
from . import llm_fill as L
from . import locks as K
from . import page as P
from . import questions as Q
from . import widgets as W
from .contracts import (
    Answer, AnswerSource, AnswerStatus, AnswerTier, AttemptContext, EntrySection, FieldType, FillPolicy,
    FillSource, ModelDecision, PageField, PageOutcome, ResolveContext, ValueOrigin,
)

L1_KEPT_NOTE = K.L1_KEPT_NOTE                            # locks: the file on the page is ours
TIMED_OUT_NOTE = "transport: timed out"
ENTRY_NOTE_PREFIX = "E5: another "                         # a section note (R3 F14, D-173), not a value failure
ENTRY_NOTE_TAIL = " - this value was typed"
TYPED_BEFORE_STOP_NOTE = "typed before the page stopped"  # N6a F6: the row is on the page; apply_flow keeps it applied
G9_FAILED_NOTE = "G9: cleared after failed fill"
DELETE_UNCONFIRMED_NOTE = "E3: delete not confirmed"
MISS_NOTES = ("search_miss", "no_option")                 # widgets notes: the list had nothing to take
UNAVAILABLE_NOTE = "transport: model unavailable"
DEFAULT_REVEAL_ROUNDS = 2
DEFAULT_FOLLOWUPS = 25
DEFAULT_LONG_LIST = 15
# Never replayed (§13.3; review F8): a second opinion counts one run as two, a corrective
# reply answers one page's site error, and a replayed recheck row ("cache:recheck") would
# meet the generic copy rule, while `recheck_targets` asks again anyway.
NO_CACHE_VIAS = ("second", "corrective", "recheck")
FACT_SOURCES = G.FACT_SOURCES                             # one definition, in guards (R3 F11)


class _Stop(Exception):
    """A transport failure or the deadline: the page ends `transport_failed`."""

    def __init__(self, note: str):
        super().__init__(note)
        self.note = note


@dataclass
class _Run:
    """One call of fill_page: what the steps share."""
    page: Any
    nav: Any
    ctx: AttemptContext
    rctx: ResolveContext
    services: Any
    cfg: dict
    stats: Any
    step: str = ""
    scope: str = ""
    sections: list = dc_field(default_factory=list)
    facts: list = dc_field(default_factory=list)
    sv: list = dc_field(default_factory=list)               # S values: never in a prompt (§6.5)
    sv_prompt: list = dc_field(default_factory=list)        # what prompts redact: [] when sees (D-105)
    sees: bool = False                                      # effective model_sees_sensitive (D-105)
    deny: list = dc_field(default_factory=list)             # enum S values: refused in pick prompts
    qv: list = dc_field(default_factory=list)               # D-202: values blanked in a stored unchecked quote
    hkey: bytes = b""                                       # facts.hash_key(rctx): keyed field_sig (D-86)
    blocks: dict = dc_field(default_factory=dict)
    today: str = ""
    inputs_hash: str = ""
    fields: dict = dc_field(default_factory=dict)           # reader key -> latest PageField
    order: list = dc_field(default_factory=list)            # reader keys, page order of first sight
    audit: dict = dc_field(default_factory=dict)            # reader key -> audit key (first seen, F6)
    known: dict = dc_field(default_factory=dict)            # reader/audit key -> ValueOrigin
    answers: dict = dc_field(default_factory=dict)          # reader key -> Answer
    decisions: dict = dc_field(default_factory=dict)        # reader key -> latest ModelDecision
    sigs: dict = dc_field(default_factory=dict)             # reader key -> field_sig
    chunk_of: dict = dc_field(default_factory=dict)         # reader key -> llm_fill.Chunk
    failed: dict = dc_field(default_factory=dict)           # reader key -> widgets note
    fresh: list = dc_field(default_factory=list)            # model decisions made on this page
    transport: str = ""                                     # set by a pick that failed in transport
    alias: dict = dc_field(default_factory=dict)            # re-created reader key -> the old key (F6)
    corrected: set = dc_field(default_factory=set)          # keys the corrective pass re-asked (F8)
    entry_failed: dict = dc_field(default_factory=dict)     # reader key -> section note: an E5 add that failed
    dead: set = dc_field(default_factory=set)               # keys of entries we confirmed deleted (F2)
    al: Any = None                                          # fill policy `always` only: `_AlwaysRun`


def fill_page(page: Any, nav: Any, ctx: AttemptContext, rctx: ResolveContext, services: Any) -> PageOutcome:
    """Fill one page (LF §8). Raises what `facts.check_entries` (PROFILE_INCOMPLETE) and
    `services.classify` (CAPTCHA / bot check) raise; everything else is in the outcome.
    Fill policy `always` (`rctx.fill_policy`, D-208) takes the second path below
    (`_fill_page_always`); `strict`, the default, is this one, unchanged."""
    if _policy(rctx) is FillPolicy.ALWAYS:
        return _fill_page_always(page, nav, ctx, rctx, services)
    run = _Run(page=page, nav=nav, ctx=ctx, rctx=rctx, services=services,
               cfg=dict(getattr(services, "cfg", None) or {}), stats=L.CallLog(model=services.model))
    # 1. step, scope, entry sections, the page's fields (§3; origins §3.3)
    run.step = nav.step_id(page, ctx)
    run.scope = nav.scope(page, ctx)
    run.sections = list(nav.entry_sections(page, ctx) or [])
    fields = _read(run, run.sections)
    # 2. facts and entry blocks; PROFILE_INCOMPLETE raises before anything changes
    run.today = services.today()
    run.facts = F.fact_catalogue(rctx.profile, rctx, today=run.today)
    F.check_entries(run.sections, rctx)
    run.sv = F.s_values(rctx.profile, rctx.account_email)
    # D-105 (Q-74 §4): with the effective switch on, a local model reads S values, so the
    # prompts and schemas are redacted with nothing; G7, `pick_option` (which keeps its
    # full redaction: it picks among site options) and any debug dump keep `run.sv`.
    run.sees = bool(getattr(rctx, "model_sees_sensitive", False))
    run.sv_prompt = [] if run.sees else run.sv
    run.deny = F.enum_s_values(rctx.profile)
    run.qv = F.quote_s_values(rctx, run.today)          # D-202: the switch does not change it
    run.hkey = F.hash_key(rctx)
    run.blocks = F.entry_blocks(rctx)
    run.inputs_hash = F.inputs_hash(L.redact(rctx.resume_text or "", run.sv_prompt), rctx.jd_text or "",
                                    sees_private=run.sees)
    try:
        # 3-6
        decision = _decide(run, fields, run.sections, {})
        # 7. a required unknown: nothing on the page has been changed (M9, TR-7)
        if decision.unknown_required:
            pending, unknown = _compose_split(run, decision.unknown_required)
            if unknown:
                return _outcome(run, unknown=unknown)
            # 7b. only compose targets are missing a text (§19.2): nothing on the page has been
            # changed; apply_flow writes the texts and calls fill_page again on this step
            return _outcome(run, compose=pending)
        # 8. classify before the first keystroke (M6), then the deadline
        services.classify(page)
        _time_left(run)
        # 9
        stop = _apply(run, decision, fields, run.sections)
        if stop:
            return _outcome(run, unknown=stop)
        # 10. revealed fields
        stop = _reveal_rounds(run, int(run.cfg.get("max_reveal_rounds", DEFAULT_REVEAL_ROUNDS)))
        if stop:
            return _outcome(run, unknown=stop)
        # 11. corrective pass, then G9 on optional fields we couldn't fill (review F1)
        _corrective(run)
        _clear_failed_optional(run)
        stop = _required_misses(run)
        if stop:
            return _outcome(run, unknown=stop)
        # 12. the required scan
        stop = _required_scan(run)
        if stop:
            return _outcome(run, unknown=stop)
    except _Stop as halt:
        return _transport(run, halt.note)
    except BackendError as exc:
        return _transport(run, _backend_note(exc))
    if run.transport:
        return _transport(run, run.transport)
    return _outcome(run)


# ------------------------------------------------------------------ steps 1, 3-6

def _read(run: _Run, sections: Sequence[EntrySection]) -> list[PageField]:
    """Read the scope; remember each field's first audit key and its latest PageField.
    A new reader key whose audit key equals an earlier field's is that field re-created
    (React re-render) ONLY when the earlier key is absent from this read (review F6:
    audit keys repeat by design, so a live or revealed field never inherits another's
    answer); it then takes over its answer and `run.alias` maps it to the old key."""
    fields = P.read_page(run.page, scope=run.scope, sections=list(sections), origin=run.ctx.prefill or "",
                         known=run.known, step=run.step, pre_import=run.ctx.pre_import or None)
    akeys = P.audit_keys(run.page, fields, run.step) if fields else {}
    here = {pf.field.key for pf in fields}
    by_audit = {a: k for k, a in run.audit.items()
                if k not in here and k not in run.dead and k not in run.alias.values()}
    for pf in fields:
        key = pf.field.key
        if key not in run.audit:
            old = by_audit.pop(akeys.get(key, ""), None) if akeys.get(key) else None
            run.audit[key] = run.audit.get(old, "") if old else akeys.get(key, "")
            if old:
                run.alias[key] = old
                if old in run.answers and key not in run.answers:
                    run.answers[key] = _replace(run.answers[old], field_key=key)
        if key not in run.fields:
            run.order.append(key)
        run.fields[key] = pf
    return fields


def _seen(run: _Run, pf: PageField) -> bool:
    """Decided on this page already (by reader key, or as a confirmed re-creation, F6)."""
    key = pf.field.key
    return key in run.answers or run.alias.get(key, "") in run.answers


def _decide(run: _Run, fields: Sequence[PageField], sections: Sequence[EntrySection],
            forced: dict[str, str]):
    """Steps 3-6 for `fields`: locks, cache replay, model chunks and follow-ups, decide.
    `forced`: group id -> source entry id for entries we added (E5)."""
    fields = list(fields)
    matches = dict(F.match_entries(list(sections), fields, run.rctx))
    matches.update(forced)
    # 3. locks (final; the model never sees a locked field as a question)
    locked = K.lock_page(fields, run.rctx, run.services.rules, today=run.today,
                         uploaded=run.ctx.uploaded, page_text=P.page_text(run.page, run.scope),
                         composed=run.ctx.composed, composed_files=run.ctx.composed_files,
                         audit=run.audit)
    quals = K.qualified_labels(fields)
    for pf in fields:
        run.sigs[pf.field.key] = F.field_sig(pf, quals.get(pf.field.key, ""), key=run.hkey)
    # 4. cached decisions go through the guards like fresh ones (§13.3)
    decisions = _cached(run, [pf for pf in fields if pf.field.key not in locked])
    cached = {d.field_key for d in decisions}
    # 5. the model, chunk by chunk (deadline before each call)
    for ch in L.chunks([pf for pf in fields if pf.field.key not in cached], matches,
                       int(run.cfg.get("max_fields_per_call", 20)), locked=list(locked)):
        for pf in ch.fields:
            run.chunk_of[pf.field.key] = ch
        if all(pf.field.key in locked for pf in ch.fields):
            continue
        _time_left(run)
        got = L.ask(run.services.backend, ch, run.facts, run.rctx, step_title=run.step,
                    s_values=run.sv_prompt, cfg=run.cfg, locked=locked, stats=run.stats)
        decisions += got
        run.fresh += got
    decisions += _long_list_picks(run, fields, decisions)
    by_key = {pf.field.key: pf for pf in fields}
    for key in G.recheck_targets(fields, decisions, matches, run.rctx, blocks=run.blocks):
        pf = by_key.get(key)
        if pf is None or not _followup_ok(run):
            continue
        _time_left(run)                                   # review F3: one way to time out
        d = L.recheck_entry(run.services.backend, pf, run.blocks.get(matches.get(pf.group) or "", ""),
                            s_values=run.sv_prompt, cfg=run.cfg, stats=run.stats)
        decisions.append(d)
        run.fresh.append(d)
    for d in decisions:
        run.decisions[d.field_key] = d
    # 6. the guards
    decision = G.decide(fields, locked, decisions, run.facts, run.rctx, matches=matches,
                        second=lambda pf: _second(run, pf, matches), today=run.today,
                        rules=run.services.rules, sections=list(sections), model=run.services.model,
                        prompt_hashes=run.stats.prompt_hashes, cfg=run.cfg, blocks=run.blocks)
    run.answers.update(decision.answers)
    return decision


def _long_list_picks(run: _Run, fields: Sequence[PageField], decisions: list) -> list:
    """LL2 (§6.4): a model answer on a fully read list longer than `long_list` (the model
    saw no enum) whose words name no option gets a `pick` call; decide then guards the
    picked option (G1, G4, G5). A fact answer never does: the program maps a fact onto an
    option itself or it stays unknown (D-86, G2(e)); short lists were an enum already."""
    long_list = int(run.cfg.get("long_list", DEFAULT_LONG_LIST))
    by_key = {pf.field.key: pf for pf in fields}
    out = []
    latest = {d.field_key: d for d in decisions}
    for key, d in latest.items():
        pf = by_key.get(key)
        if (pf is None or not G.is_choice(pf) or not pf.options_complete
                or len(pf.field.options) <= long_list or d.source in FACT_SOURCES
                or not isinstance(d.value, str) or not d.value.strip()
                or G.option_for(pf, d.value) is not None or not _followup_ok(run)):
            continue
        _time_left(run)
        choice = L.pick_option(run.services.backend, pf, d.value, [o.label for o in pf.field.options],
                               s_values=run.sv, cfg=run.cfg, stats=run.stats,   # D-105: pick keeps the full redaction
                               sensitive=G.sensitive_label(pf), deny=run.deny)
        pick = ModelDecision(key, d.source, d.ref, choice or "", d.evidence, via="pick")
        out.append(pick)
        run.fresh.append(pick)
    return out


def _second(run: _Run, pf: PageField, matches: dict) -> ModelDecision:
    """G5's second call. Past the deadline the page ends `transport_failed` "transport:
    timed out" (review F3: `decide` does not catch `_Stop`, so no question is captured for
    a field we merely ran out of time on); past `max_followups` it answers unknown (G5
    then keeps nothing; LF §13.1)."""
    key = pf.field.key
    _time_left(run)
    if not _followup_ok(run):
        return ModelDecision(key, FillSource.UNKNOWN, via="second")
    ch = run.chunk_of.get(key) or L.Chunk(f"one:{key}", matches.get(pf.group) if pf.group else None, (pf,))
    return L.second_opinion(run.services.backend, pf, ch, run.facts, run.rctx, step_title=run.step,
                            s_values=run.sv_prompt, cfg=run.cfg, stats=run.stats)


def _followup_ok(run: _Run) -> bool:
    return run.stats.followups < int(run.cfg.get("max_followups", DEFAULT_FOLLOWUPS))


def _time_left(run: _Run) -> None:
    if run.services.deadline_left() <= 0:
        raise _Stop(TIMED_OUT_NOTE)


# ------------------------------------------------------------------ step 9

def _apply(run: _Run, decision: Any, fields: Sequence[PageField],
           sections: Sequence[EntrySection]) -> tuple[str, ...]:
    """Entry deletes (verified, review F2), entry adds (a round each), then fills and G9
    resets in page order. Returns the unknown required keys of a stop, else ()."""
    targets, handled = list(fields), set()
    if decision.deletes:
        stop, handled = _delete_entries(run, decision, fields, sections)
        if stop:
            return stop
        # entries renumber and a site may re-create controls: fill from a fresh read (F5, F6)
        targets = [pf for pf in _read(run, run.sections)
                   if run.alias.get(pf.field.key, pf.field.key) in decision.answers]
    for pf in targets:
        key = pf.field.key
        src = run.alias.get(key, key)
        if src not in decision.answers or key in handled or src in handled:
            continue
        _apply_one(run, key, decision.answers[src], src in decision.resets)
    for section, source in decision.adds:
        stop = _add_entry(run, section, source)
        if stop:
            return stop
    return ()


def _delete_entries(run: _Run, decision: Any, fields: Sequence[PageField],
                    sections: Sequence[EntrySection]) -> tuple[tuple[str, ...], set]:
    """E3/E6, verified (review F2). Bottom-up clicks on each group's delete control, then
    `run.sections` is re-read. A delete counts only when the group was clicked and its own
    controls are gone from the page (per group, review R3 F12: a swallowed click on one
    group never demotes another group's real delete). The section's entry count is the
    independent second signal (review Q-80 M1): if the section still has more entries than
    `initial - confirmed`, the keys alone can't be trusted (a site may re-create list items
    without the reader's mark) and every group of that section is unconfirmed. A group that is still there (or
    had no delete control) is never skipped: its required fields stop the page (unknown,
    as E3's "no delete control" rule), its optional ones are reset (G9) or, when that
    can't be done, flagged PREFILLED unverified. Returns (stop keys, handled keys)."""
    groups = {f"{s.section}#{g.index}": g for s in sections for g in s.entries}
    initial = {s.section: len(s.entries) for s in sections}
    clicked: dict[str, bool] = {}
    for gid in sorted(decision.deletes, key=lambda g: -_index(g)):    # bottom up: the rest stay put
        g = groups.get(gid)
        clicked[gid] = bool(g is not None and g.delete_locator
                            and P.click(run.page, run.page.locator(g.delete_locator).first))
        run.page.wait_for_timeout(300)
    run.sections = list(run.nav.entry_sections(run.page, run.ctx) or [])
    left = {s.section: len(s.entries) for s in run.sections}
    stop: list[str] = []
    handled: set = set()
    alive_of = {gid: {pf.field.key for pf in fields if pf.group == gid and _present(run, pf)}
                for gid in decision.deletes}
    gone = {gid for gid in decision.deletes if clicked.get(gid) and not alive_of[gid]}
    for section in {g.rpartition("#")[0] for g in gone}:             # M1: the count must agree
        mine = {g for g in gone if g.rpartition("#")[0] == section}
        if left.get(section, 0) > initial.get(section, 0) - len(mine):
            run.services.log(f"E3: {section} has more entries than the confirmed deletes explain")
            gone -= mine
    for gid in decision.deletes:
        members = [pf for pf in fields if pf.group == gid]
        alive = alive_of[gid]
        if gid in gone:
            run.dead |= {pf.field.key for pf in members}             # gone: never inherited (F5/F6)
            continue
        run.services.log(f"E3: delete not confirmed for {gid}")
        for pf in members:
            key = pf.field.key
            handled.add(key)
            base = run.answers.get(key) or Answer(field_key=key, value=None, tier=AnswerTier.NONE, source="",
                                                  confidence=0.0)
            if pf.field.required:
                run.answers[key] = _replace(base, status=AnswerStatus.UNKNOWN, confidence=0.0,
                                            note=DELETE_UNCONFIRMED_NOTE)
                stop.append(key)
                continue
            r = W.reset_field(run.page, pf) if key in alive else None
            if r is not None and r.ok:
                _mark(run, key, ValueOrigin.EMPTY)
                run.answers[key] = _replace(base, value=None, option_labels=(), status=AnswerStatus.BLANK_OPTIONAL,
                                            confidence=0.0, note=f"{DELETE_UNCONFIRMED_NOTE}; G9: cleared")
            else:
                run.answers[key] = _replace(base, value=r.shown if r is not None else pf.shown, option_labels=(),
                                            tier=AnswerTier.NONE, source=pf.origin.value,
                                            status=AnswerStatus.PREFILLED, confidence=G.CONF_UNVERIFIED,
                                            note=G.UNVERIFIED_NOTE)
    return tuple(stop), handled


def _present(run: _Run, pf: PageField) -> bool:
    try:
        return run.page.locator(pf.field.locator).count() > 0
    except Exception:
        return True                                                  # can't tell: not confirmed gone


def _apply_one(run: _Run, key: str, ans: Answer, reset: bool) -> None:
    pf = run.fields[key]
    if reset:
        r = W.reset_field(run.page, pf)
        if not r.ok:          # the site keeps a value we can't verify: say so (G9 note, lane M)
            run.answers[key] = _replace(ans, status=AnswerStatus.PREFILLED, confidence=G.CONF_UNVERIFIED,
                                        note=G.UNVERIFIED_NOTE)
        else:
            _mark(run, key, ValueOrigin.EMPTY)
        return
    if ans.status is not AnswerStatus.FILLED:
        return
    if pf.field.type is FieldType.FILE:
        if ans.note == L1_KEPT_NOTE:
            return
        path = str(ans.value or "")
        if ans.source == AnswerSource.COMPOSED.value:     # K3: the value is the letter's text (§19.5)
            path = _composed_path(run, key)
        r = W.fill_field(run.page, pf, path, force=True)          # H6: replace what we didn't upload
        try:
            digest = hashlib.sha256(Path(path).read_bytes()).hexdigest() if r.ok else ""
        except OSError:                                   # review F10: an unreadable file is a failed upload
            digest = ""
        if r.ok and digest:
            run.ctx.uploaded[Path(path).name] = digest
            _mark(run, key, ValueOrigin.OURS)
        else:
            run.failed[key] = r.note or "readback"
        return
    value = _fill_value(pf, ans)
    r = W.fill_field(run.page, pf, value, pick=_picker(run, pf, ans))
    if run.transport:                                     # a pick timed out or lost the model
        raise _Stop(run.transport)
    if r.ok:
        _mark(run, key, ValueOrigin.OURS)
        run.failed.pop(key, None)
    else:
        run.failed[key] = r.note or "readback"


def _fill_value(pf: PageField, ans: Answer) -> Any:
    """The words to put in: the chosen options' verbatim labels when decide named them."""
    if ans.option_labels:
        if pf.field.type is FieldType.MULTI_CHOICE:
            return list(ans.option_labels)
        return ans.option_labels[0]
    return ans.value


def _picker(run: _Run, pf: PageField, ans: Answer):
    """LL3 (review F9): the pick a search-driven list needs at fill time. The model picks,
    then G4 checks the option against the answer's quote (or the program's words) BEFORE
    the widget clicks it; a failed check is no pick (-> the field fails, never a guess)."""
    if pf.field.type not in (FieldType.DROPDOWN, FieldType.RADIO, FieldType.TYPEAHEAD,
                             FieldType.MULTI_CHOICE):
        return None
    quote = ans.evidence or _text(ans.value)

    def pick(want: str, options: Sequence[str]) -> str:
        if run.services.deadline_left() <= 0:
            run.transport = run.transport or TIMED_OUT_NOTE  # review F3: ends the page, never fill_failed
        if run.transport or not _followup_ok(run):
            return ""
        try:
            got = L.pick_option(run.services.backend, pf, want, list(options), s_values=run.sv,
                                cfg=run.cfg, stats=run.stats, sensitive=ans.sensitive,
                                deny=run.deny) or ""
        except BackendError as exc:
            run.transport = _backend_note(exc)
            return ""
        return got if got and G.g4_ok(got, quote) else ""
    return pick


def _add_entry(run: _Run, section: str, source: str) -> tuple[str, ...]:
    """E5: click the section's Add, read the new entry, give it its own round (3-9).
    `run.sections` is fresh here (re-read after the deletes, review F5), and the new
    entry is found by count, not by a group id a deleted entry may have had. An Add
    that can't be clicked or yields no entry is reported, never silent (`_add_failed`)."""
    sec = next((s for s in run.sections if s.section == section), None)
    if sec is None or not sec.add_locator:
        return _add_failed(run, section, "no add control")
    count = len(sec.entries)
    if not P.click(run.page, run.page.locator(sec.add_locator).first):
        return _add_failed(run, section, "add click failed")
    run.page.wait_for_timeout(500)
    run.sections = list(run.nav.entry_sections(run.page, run.ctx) or [])
    after = next((s for s in run.sections if s.section == section), None)
    if after is None or len(after.entries) <= count:
        return _add_failed(run, section, "no entry appeared")
    new = [f"{section}#{g.index}" for g in sorted(after.entries, key=lambda g: g.index)[count:]]
    fields = [pf for pf in _read(run, run.sections) if pf.group in new and not _seen(run, pf)]
    if not fields:
        return _add_failed(run, section, "new entry has no fields")
    decision = _decide(run, fields, run.sections, {new[0]: source})
    if decision.unknown_required:
        return decision.unknown_required
    run.services.classify(run.page)
    _time_left(run)
    for key in [pf.field.key for pf in fields]:
        if key in decision.answers:
            _apply_one(run, key, decision.answers[key], key in decision.resets)
    return ()


def _add_failed(run: _Run, section: str, why: str) -> tuple[str, ...]:
    """Review F5 / R3 F14 (D-173): E5 asked for an entry the page didn't get; never silent
    and fail closed. Logged (the section name and the reason only), and the section's fields
    on the page (its required ones, else all of them) are listed in `fill_failed`
    (`run.entry_failed`, kept through the corrective pass), so a required one stops the flow
    `validation_error`: auto mode must not submit with fewer entries than the profile has.
    Those rows keep their own status and carry a SECTION note, not a claim that their value
    failed. The flow stops on any `fill_failed` row with that note, required or not (D-174).
    PageOutcome has no entry-level channel yet (next contract version)."""
    run.services.log(f"E5: add failed in {section}: {why}")
    keys = [k for k in run.order if k in run.fields and k not in run.dead
            and run.fields[k].group.rpartition("#")[0] == section]
    required = [k for k in keys if run.fields[k].field.required]
    note = f"{ENTRY_NOTE_PREFIX}{section.replace('_', ' ')} entry could not be added ({why}){ENTRY_NOTE_TAIL}"
    for key in required or keys:
        run.entry_failed[key] = note
    return ()


# ------------------------------------------------------------------ steps 10-12

def _reveal_rounds(run: _Run, rounds: int) -> tuple[str, ...]:
    """H7: fields our answers revealed get steps 3-9; a required one unknown stops."""
    for _ in range(max(0, rounds)):
        run.sections = list(run.nav.entry_sections(run.page, run.ctx) or [])
        new = [pf for pf in _read(run, run.sections) if not _seen(run, pf)]
        if not new:
            return ()
        decision = _decide(run, new, run.sections, {})
        if decision.unknown_required:
            return decision.unknown_required
        run.services.classify(run.page)
        _time_left(run)
        stop = _apply(run, decision, new, run.sections)
        if stop:
            return stop
    return ()


def _corrective(run: _Run) -> None:
    """Fields that failed or show a site error: asked again with the error, decided and
    filled once; what still fails stays in `failed` (LF §8 step 11)."""
    errors = {k: e for k, e in P.field_errors(run.page, scope=run.scope).items() if k}
    targets = set(run.failed) | set(errors)
    if not targets:
        return
    run.services.classify(run.page)
    fields = [pf for pf in _read(run, run.sections) if pf.field.key in targets]
    if not fields:
        return
    run.corrected |= {pf.field.key for pf in fields}      # F8: their first decision is not cached
    fields = [pf if pf.error else _replace(pf, error=errors.get(pf.field.key) or "not accepted") for pf in fields]
    locked = K.lock_page(fields, run.rctx, run.services.rules, today=run.today,
                         uploaded=run.ctx.uploaded, page_text=P.page_text(run.page, run.scope),
                         composed=run.ctx.composed, composed_files=run.ctx.composed_files,
                         audit=run.audit)
    open_ = [pf for pf in fields if pf.field.key not in locked and pf.field.type is not FieldType.FILE]
    decisions = [run.decisions[pf.field.key] for pf in fields if pf.field.key in run.decisions]
    if open_:
        _time_left(run)
        got = L.ask(run.services.backend, L.Chunk("corrective", None, tuple(open_)), run.facts, run.rctx,
                    step_title=run.step, s_values=run.sv_prompt, cfg=run.cfg, locked=locked, stats=run.stats)
        decisions += got
    matches = dict(F.match_entries(run.sections, fields, run.rctx))
    decision = G.decide(fields, locked, decisions, run.facts, run.rctx, matches=matches,
                        second=lambda pf: _second(run, pf, matches), today=run.today,
                        rules=run.services.rules, sections=run.sections, model=run.services.model,
                        prompt_hashes=run.stats.prompt_hashes, cfg=run.cfg, blocks=run.blocks)
    run.answers.update(decision.answers)
    for pf in fields:
        key = pf.field.key
        if key in decision.answers:
            run.fields[key] = pf
            _apply_one(run, key, decision.answers[key], key in decision.resets)


def _required_scan(run: _Run) -> tuple[str, ...]:
    """H7: required controls still empty or in error. Ones never decided get a round
    (as step 10); then unknown -> stop (unknown_required), anything else -> fill_failed."""
    hits = set(P.scan_required(run.page, run.scope))
    if not hits:
        return ()
    run.sections = list(run.nav.entry_sections(run.page, run.ctx) or [])
    fresh = [pf for pf in _read(run, run.sections) if pf.field.key in hits and not _seen(run, pf)]
    if fresh:
        decision = _decide(run, fresh, run.sections, {})
        if decision.unknown_required:
            return decision.unknown_required
        run.services.classify(run.page)
        _time_left(run)
        stop = _apply(run, decision, fresh, run.sections)
        if stop:                                          # review F9: an added entry's stop counts
            return stop
        hits = set(P.scan_required(run.page, run.scope))
    unknown = []
    for key in hits:
        ans = run.answers.get(key)
        if ans is None or ans.status in (AnswerStatus.UNKNOWN, AnswerStatus.UNGROUNDED):
            unknown.append(key)
        else:
            run.failed.setdefault(key, "required_scan")
    order = {k: i for i, k in enumerate(run.order)}
    return tuple(sorted(unknown, key=lambda k: order.get(k, len(order))))


def _clear_failed_optional(run: _Run) -> None:
    """Review F1 (G9, LL3, LF §11): an OPTIONAL field whose fill still failed after the
    corrective pass must not keep a value nobody backed. It is reset (BLANK_OPTIONAL,
    "G9: cleared after failed fill"); a widget with no empty state, or a reset the site
    ignores, leaves the row PREFILLED and unverified (`guards.UNVERIFIED_NOTE`) so the
    flow treats it as untrusted. Required fields stay in `failed` (the flow stops)."""
    for key in [k for k in run.order if k in run.failed]:
        pf = run.fields.get(key)
        if pf is None or pf.field.required:
            continue
        r = W.reset_field(run.page, pf)
        base = run.answers.get(key) or Answer(field_key=key, value=None, tier=AnswerTier.NONE, source="",
                                              confidence=0.0)
        if r.ok:
            _mark(run, key, ValueOrigin.EMPTY)
            run.answers[key] = _replace(base, value=None, option_labels=(), status=AnswerStatus.BLANK_OPTIONAL,
                                        confidence=0.0, note=f"{G9_FAILED_NOTE} ({run.failed[key]})")
        else:
            run.answers[key] = _replace(base, value=r.shown, option_labels=(), tier=AnswerTier.NONE,
                                        source=pf.origin.value, status=AnswerStatus.PREFILLED,
                                        confidence=G.CONF_UNVERIFIED, note=G.UNVERIFIED_NOTE)
        del run.failed[key]


def _required_misses(run: _Run) -> tuple[str, ...]:
    """Review F4 (LF §6.4 LL3, §11; LF §8 step 10 allows the stop): a REQUIRED field whose
    list offered no option we may take (`search_miss`, `no_option`) is unknown -> captured,
    so the owner can answer it. A value the page would not keep (`readback`, `site_error`,
    `not_decided`) stays fill_failed."""
    out = []
    for key in [k for k in run.order if k in run.failed]:
        pf = run.fields.get(key)
        if pf is None or not pf.field.required or run.failed[key] not in MISS_NOTES:
            continue
        base = run.answers.get(key) or Answer(field_key=key, value=None, tier=AnswerTier.NONE, source="",
                                              confidence=0.0)
        run.answers[key] = _replace(base, status=AnswerStatus.UNKNOWN, confidence=0.0,
                                    note=f"LL3: no option found ({run.failed[key]})")
        del run.failed[key]
        out.append(key)
    return tuple(out)


# ------------------------------------------------------------------ step 13 and the outcome

def _job_id(run: _Run) -> str:
    """The cache's job key. A job row (`store.job_for_apply`) carries `job_id`, not `id`:
    keying on `id` made every job share the key "" and replay each other's decisions
    (N6a review note; WP-N6b)."""
    job = run.ctx.job or {}
    return str(job.get("job_id") or job.get("id") or "")


def _cached(run: _Run, fields: Sequence[PageField]) -> list[ModelDecision]:
    """Replayed decisions (via "cache:<via>"); a row whose cited facts changed is a miss."""
    if not run.cfg.get("cache", True) or not fields:
        return []
    sigs = {pf.field.key: run.sigs.get(pf.field.key, "") for pf in fields}
    fields_by_key = {pf.field.key: pf for pf in fields}
    rows = run.services.cache_get(_job_id(run), [s for s in sigs.values() if s],
                                  L.FILL_PROMPT_VERSION, run.services.model, run.inputs_hash) or {}
    out = []
    for key, sig in sigs.items():
        row = rows.get(sig)
        if not row:
            continue
        d = row.get("decision") or {}
        refs = [d["ref"]] if d.get("ref") else []
        if F.facts_used_hash(refs, run.rctx, today=run.today) != row.get("facts_used_hash"):
            continue
        try:
            source = FillSource(d.get("source", ""))
        except ValueError:
            continue
        if source is FillSource.UNKNOWN and fields_by_key[key].field.required:
            continue                                      # F13: never replay a required unknown
        out.append(ModelDecision(key, source, d.get("ref", ""), d.get("value"), d.get("evidence", ""),
                                 via=f"cache:{d.get('via', 'page')}"))
    return out


def stored_quote(evidence: str, a: Optional[Answer], values: Sequence[str]) -> str:
    """D-202 (Q-113): the model's quote as the audit row and the decision cache store it.
    Verbatim only when the guards checked it and the field took a value
    (`guards.quote_checked`: resume, posting or non-private-fact text, which a replay
    re-reads in G3); every other quote (rejected, fact-cited, unknown, a trusted keep)
    with each of `values` (`facts.quote_s_values`) as "[private]". The same with the
    switch on or off. A row with no quote (locks, resolve tiers, composed texts) stays ""."""
    if a is not None and G.quote_checked(a):
        return evidence
    return L.redact(evidence or "", values)


def _stored_value(value: Any, a: Optional[Answer], values: Sequence[str]) -> Any:
    """D-202 (Q-113 tester O1): a cached resume/job/keep decision's model value, by the same
    rule as its quote: verbatim when the guards checked the quote and the field took it,
    else each string (a list: each string item) redacted; None, bools and numbers as they
    are. Replay never fills from a redacted value: the resume/job route takes a model value
    only through a checked quote (and "[private]" fails G3 there), a keep fills the shown
    value, and a fact decision is cached with no value."""
    if a is not None and G.quote_checked(a):
        return value
    if isinstance(value, str):
        return L.redact(value, values)
    if isinstance(value, (list, tuple)):
        return [L.redact(x, values) if isinstance(x, str) else x for x in value]
    return value


def _cache_put(run: _Run, unknown: Sequence[str] = ()) -> None:
    """The latest fresh decision per field (no G5 or corrective replies, no required `unknown` (F13);
    no value for a fact decision: the program recomputes it, §13.3). `unknown`: the fields the
    page stopped on (a required fact with no value, a required unknown): their decisions are
    not stored, so the retry after the owner fills the fact asks the model again (F13)."""
    if not run.cfg.get("cache", True) or not run.fresh:
        return
    latest: dict[str, ModelDecision] = {}
    for d in run.fresh:
        if d.via in NO_CACHE_VIAS or d.field_key in run.corrected:
            continue                                      # F8: not a decision the site refused
        if d.via == "pick" and not d.value:
            latest.pop(d.field_key, None)                 # F8: no negative pick rows
            continue
        pf = run.fields.get(d.field_key)
        if d.field_key in unknown:
            latest.pop(d.field_key, None)
            continue
        if d.source is FillSource.UNKNOWN and pf is not None and pf.field.required:
            latest.pop(d.field_key, None)                 # R3 re-review F13: a required unknown (the
            continue                                      # stop) is never stored: a retry asks again
        latest[d.field_key] = d
    rows = []
    for key, d in latest.items():
        sig = run.sigs.get(key)
        if not sig:
            continue
        keep_value = d.source in (FillSource.RESUME, FillSource.JOB, FillSource.KEEP)
        rows.append({"field_sig": sig, "prompt_version": L.FILL_PROMPT_VERSION, "model": run.services.model,
                     "inputs_hash": run.inputs_hash,
                     "facts_used_hash": F.facts_used_hash([d.ref] if d.ref else [], run.rctx, today=run.today),
                     "decision": {"source": d.source.value, "ref": d.ref,
                                  "evidence": stored_quote(d.evidence, run.answers.get(key), run.qv),
                                  "value": (_stored_value(d.value, run.answers.get(key), run.qv)
                                            if keep_value else None), "via": d.via}})
    if rows:
        run.services.cache_put(_job_id(run), rows)


def _mark(run: _Run, key: str, origin: ValueOrigin) -> None:
    """Record who put the field's value (F6: under the reader key and the audit key)."""
    run.known[key] = origin
    if run.audit.get(key):
        run.known[run.audit[key]] = origin


def _composed_path(run: _Run, key: str) -> str:
    """The file written from a composed text: `ctx.composed_files` is keyed by audit key."""
    files = run.ctx.composed_files or {}
    return str(files.get(run.audit.get(key, "")) or files.get(key) or "")


def _compose_split(run: _Run, keys: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(compose keys, other unknown keys) among a stop's required unknowns (§19.2). A compose
    target is pending when its lock left it unwritten (`compose_needed` note) and either
    `apply.compose.enabled` (`services.compose_enabled`) or it is a FILE target with an owner
    answer (the answer becomes the letter). Otherwise it stays a plain unknown: captured as
    `compose_needed: off`."""
    on = bool(getattr(run.services, "compose_enabled", False))
    pending, other = [], []
    for k in keys:
        pf, a = run.fields.get(k), run.answers.get(k)
        target = (pf is not None and a is not None and Q.compose_needed(pf.field, pf.group)
                  and (a.note or "").startswith(Q.COMPOSE_NOTE))
        if target and (on or (pf.field.type is FieldType.FILE
                              and Q.owner_compose_text(pf.field, run.rctx))):
            pending.append(k)
        else:
            other.append(k)
    return tuple(pending), tuple(other)


def _outcome(run: _Run, *, unknown: Sequence[str] = (), compose: Sequence[str] = ()) -> PageOutcome:
    # 13. the decision cache, on a finished page AND on a stop: the retry after the owner
    # answers the captured question replays every other decision (§13.3). Never on a
    # transport failure (`_transport`).
    _cache_put(run, unknown)
    answers = dict(run.answers)
    if unknown:
        _note_typed(run, answers)
    why = {**run.entry_failed, **run.failed}
    failed = [k for k in run.order if k in why and k not in unknown]
    for k in failed:
        if k not in answers:
            continue
        if k in run.entry_failed and k not in run.failed:
            # the section's problem; this value was typed and keeps its status in the audit
            answers[k] = _replace(answers[k], note="; ".join(n for n in (answers[k].note, why[k]) if n))
            continue
        answers[k] = _replace(answers[k], status=AnswerStatus.FILL_FAILED,
                              note=answers[k].note or f"fill: {why[k]}")
    fields = [run.fields[k] for k in run.order if k in run.fields]
    return PageOutcome(step=run.step, fields=fields, answers=answers, unknown_required=tuple(unknown),
                       fill_failed=tuple(failed), model_calls=run.stats.calls,
                       model_seconds=round(run.stats.seconds, 3), transport_failed=False,
                       compose_needed=tuple(compose))


def _note_typed(run: _Run, answers: dict) -> None:
    """N6a F6: a stop or a transport failure after step 9 leaves some values on the employer's
    page. Those filled rows say so (`TYPED_BEFORE_STOP_NOTE`), so the flow does not write them
    as "not applied". A stop at step 7 typed nothing (`run.known` has no OURS), so its rows
    stay decided-only."""
    for k, a in list(answers.items()):
        if a.status is AnswerStatus.FILLED and run.known.get(k) is ValueOrigin.OURS:
            answers[k] = _replace(a, note="; ".join(n for n in (a.note, TYPED_BEFORE_STOP_NOTE) if n))


def _backend_note(exc: BaseException) -> str:
    """N6a F5: a model call that ran out of time (`llm_fill` turns TimeoutError into a
    BackendError "... timed out"; httpx's read timeout names itself) is a timeout, not a
    missing model, so the flow's detail can tell them apart."""
    text = str(exc).lower()
    return TIMED_OUT_NOTE if ("timed out" in text or "timeout" in text) else UNAVAILABLE_NOTE


def _transport(run: _Run, note: str) -> PageOutcome:
    """§11: no capture; every field without an answer is noted "transport: ...". A lane
    note about the deadline: it comes back the same way ("transport: timed out")."""
    answers = dict(run.answers)
    _note_typed(run, answers)
    for key in run.order:
        if key not in answers:
            answers[key] = Answer(field_key=key, value=None, tier=AnswerTier.NONE, source="",
                                  confidence=0.0, status=AnswerStatus.UNKNOWN, note=note)
    # Q-93: a pick that fails mid-fill leaves every row answered, so no row would say why the
    # page stopped and the flow's detail fell back to "timed out" even for a refusing model.
    # The cause then rides on the first row's note (first in the note, where the flow reads it).
    if not any((a.note or "").lower().startswith("transport:") for a in answers.values()):
        first = next((k for k in run.order if k in answers), None)
        if first is not None and note.lower().startswith("transport:"):
            answers[first] = _replace(answers[first], note="; ".join(n for n in (note, answers[first].note) if n))
    fields = [run.fields[k] for k in run.order if k in run.fields]
    return PageOutcome(step=run.step, fields=fields, answers=answers, unknown_required=(),
                       fill_failed=(), model_calls=run.stats.calls,
                       model_seconds=round(run.stats.seconds, 3), transport_failed=True)


def _index(gid: str) -> int:
    tail = gid.rpartition("#")[2]
    return int(tail) if tail.isdigit() else 0


def _text(v: Any) -> str:
    return "; ".join(str(x) for x in v) if isinstance(v, list) else str(v or "")


# ------------------------------------------------------------------ fill policy `always` (Q-121 WP-C1)
#
# llm_first_fill_design §4.1 A1 and A7-A9, §4.4 (query ladder), §4.5 (entries), §8, §9.
# The answers come from `always.fill_page_always` (A2-A6); this part reads, binds entry
# slots, and changes the page through the same widgets the strict path uses.

SETTLE_MS = 1500                     # A1: `apply.llm_fill.settle_ms`
ADD_WAIT_MS = 500
HIDDEN_NOTE = "not visible: never filled"                      # K10
PASSWORD_NOTE = "password field: never read into a prompt"     # K1 backstop
NO_LABEL_NOTE = "no label"                                     # A1
SURPLUS_NOTE = "surplus entry: no profile entry left for it"   # §4.5
REVERTED_NOTE = "reverted"                                     # A7 verification read
SCAN_ERROR = "The site requires an answer here."               # A8 problem for an empty required field
ALWAYS_VIA = "always"
_PLACE_WORDS = ("city", "town", "location", "located", "based")
_SCHOOL_WORDS = ("school", "university", "institution", "college")
_CHOICE_WIDGET_TYPES = (FieldType.DROPDOWN, FieldType.RADIO, FieldType.TYPEAHEAD, FieldType.MULTI_CHOICE)


def _policy(rctx: Any) -> FillPolicy:
    """`rctx.fill_policy` (contract v7); anything unreadable is the default, strict."""
    v = getattr(rctx, "fill_policy", FillPolicy.STRICT)
    try:
        return FillPolicy(getattr(v, "value", v))
    except ValueError:
        return FillPolicy.STRICT


@dataclass
class _AlwaysRun:
    """What the `always` steps of one page share (beside `_Run`)."""
    brief: Any                                              # contracts.Briefing
    ask: Any                                                # always.Ask over services.backend
    pctx: Any                                               # always.PageCtx for R2 picks at fill time
    profile: dict
    order: dict                                             # list -> briefing.entry_order
    stats: Any                                              # always.CallStats (counts only)
    before: int = 0                                         # F2-F6 answers on earlier pages
    guesses: int = 0                                        # F2-F6 answers on this page so far
    entries: dict = dc_field(default_factory=dict)          # slot group id -> source entry id
    stand: list = dc_field(default_factory=list)            # stand-in sections from label runs
    surplus: tuple = ()
    adds: list = dc_field(default_factory=list)
    fb: dict = dc_field(default_factory=dict)               # key -> a code fallback wrote it
    sk: dict = dc_field(default_factory=dict)               # key -> S1 kept the standing answer
    expected: dict = dc_field(default_factory=dict)         # key -> the read-back after our fill
    model_keys: set = dc_field(default_factory=set)         # main-pass model answers (cache rows)
    corrected: set = dc_field(default_factory=set)          # keys of the A8 round (never cached)
    classes: dict = dc_field(default_factory=dict)          # key -> `class[:which]` of its answer (A1-A, cache rows)


def _fill_page_always(page: Any, nav: Any, ctx: AttemptContext, rctx: ResolveContext,
                      services: Any) -> PageOutcome:
    """Fill one page under fill policy `always` (D-208). Raises what `facts.check_entries`
    (PROFILE_INCOMPLETE), `services.classify` (CAPTCHA / bot check) and
    `always.fill_page_always` (`AlwaysStop`: owner_fact_missing, document_missing, the
    content failure) raise; transport failures come back `transport_failed`."""
    run = _Run(page=page, nav=nav, ctx=ctx, rctx=rctx, services=services,
               cfg=dict(getattr(services, "cfg", None) or {}), stats=L.CallLog(model=services.model))
    with P.always_reader():
        try:
            return _always_steps(run)
        except _Stop as halt:
            return _always_transport(run, halt.note)
        except (BackendError, TimeoutError) as exc:
            return _always_transport(run, _backend_note(exc))


def _always_steps(run: _Run) -> PageOutcome:
    page, nav, ctx, rctx, services = run.page, run.nav, run.ctx, run.rctx, run.services
    run.step = nav.step_id(page, ctx)
    run.scope = nav.scope(page, ctx)
    run.today = services.today()
    # A1: read, let the site restore what it restores, read again (rev note: settle re-read).
    run.sections = list(nav.entry_sections(page, ctx) or [])
    _read(run, run.sections)
    page.wait_for_timeout(int(run.cfg.get("settle_ms", SETTLE_MS)))
    run.sections = list(nav.entry_sections(page, ctx) or [])
    fields = _read(run, run.sections)
    F.check_entries(run.sections, rctx)                     # §9: profile_incomplete stays
    run.qv = F.quote_s_values(rctx, run.today)              # D-202 rule for stored rows
    profile = applicant.normalise(dict(rctx.profile or {}))
    # §7.1: the flow builds the briefing once per attempt; read with getattr so fakes work.
    brief = getattr(services, "briefing", None) or BR.build(rctx.profile, rctx, today=run.today)
    timeout = run.cfg.get("page_timeout_s")
    ask = AL.backend_ask(services.backend, timeout=float(timeout) if timeout else None,
                         keep_alive=run.cfg.get("keep_alive") or None)
    stats = AL.CallStats()
    pctx = AL.PageCtx(brief=brief, rctx=rctx, profile=profile, ask=ask, rules=services.rules,
                      today=run.today, cfg=run.cfg, step_title=run.step or "this page",
                      job=BR.job_block(rctx, today=run.today), stats=stats)
    run.al = _AlwaysRun(brief=brief, ask=ask, pctx=pctx, profile=profile,
                        order={lst: BR.entry_order(profile, lst) for lst in ("education", "experience")},
                        stats=stats, before=int(getattr(services, "attempt_fallbacks", 0) or 0))
    fields = _always_view(run, fields)
    todo = _always_prepare(run, fields, bind=True)
    # A2-A6: nothing on the page has been changed yet
    out = _always_round(run, todo)
    if out.transport_failed:
        return _always_transport(run, UNAVAILABLE_NOTE)
    if out.compose_needed:                                  # §4.8: the flow composes, then calls again
        return _always_outcome(run, compose=out.compose_needed)
    # A7: classify before the first keystroke, then the deadline
    services.classify(page)
    _time_left(run)
    _always_surplus(run)
    _always_apply(run, [pf.field.key for pf in todo])
    _always_adds(run)
    _always_reveal(run, int(run.cfg.get("max_reveal_rounds", DEFAULT_REVEAL_ROUNDS)))
    _always_verify(run)
    # A8: one corrective round, then the required scan
    _always_corrective(run)
    _always_scan(run)
    if run.transport:
        return _always_transport(run, run.transport)
    return _always_outcome(run)


def _always_read(run: _Run) -> list[PageField]:
    run.sections = list(run.nav.entry_sections(run.page, run.ctx) or [])
    return _always_view(run, _read(run, run.sections))


def _always_view(run: _Run, fields: Sequence[PageField]) -> list[PageField]:
    """§4.5 "detection is a hint": ungrouped fields whose label set repeats get stand-in
    slot groups (`facts.label_runs`); `run.fields` holds the grouped PageField."""
    groups, stand = F.label_runs(fields, run.sections)
    if stand:
        run.al.stand = stand
    out = []
    for pf in fields:
        if pf.field.key in groups:
            pf = _replace(pf, group=groups[pf.field.key])
            run.fields[pf.field.key] = pf
        out.append(pf)
    return out


def _skip_answer(key: str, note: str) -> Answer:
    return Answer(field_key=key, value=None, tier=AnswerTier.NONE, source="", confidence=0.0,
                  status=AnswerStatus.SKIPPED, rule_id=AL.PROMPT_VERSION, note=note)


def _always_prepare(run: _Run, fields: Sequence[PageField], *, bind: bool) -> list[PageField]:
    """A1 field rules before the model sees anything: a password input is never read (K1;
    READER_JS skips them, this re-checks), a field with no label and no options is skipped
    unless the site marks it invalid, an invisible field is never filled (K10), and surplus
    entry slots are not asked (§4.5). `bind`: bind entry slots to source entries."""
    al = run.al
    if bind:
        plan = F.bind_slots(list(run.sections) + list(al.stand), fields, run.rctx, al.order,
                            max_entries=run.cfg.get("max_entries"))
        al.entries.update(plan.entries)
        al.surplus, al.adds = plan.surplus, list(plan.adds)
    types = P.control_types(run.page, [pf.field.key for pf in fields])
    todo = []
    for pf in fields:
        key = pf.field.key
        if types.get(key) == "password":
            run.answers[key] = _skip_answer(key, PASSWORD_NOTE)
        elif not pf.field.label.strip() and not pf.field.options and not pf.error:
            run.answers[key] = _skip_answer(key, NO_LABEL_NOTE)
        elif pf.group and pf.group in al.surplus:
            continue                                        # `_always_surplus`
        elif not P.shown_visible(run.page, pf):
            run.answers[key] = _skip_answer(key, HIDDEN_NOTE)
        else:
            todo.append(pf)
    return todo


def _always_round(run: _Run, fields: Sequence[PageField], *, corrective: bool = False) -> PageOutcome:
    """A2-A6 for `fields` (always.fill_page_always) and the bookkeeping: answers, fallback
    and S1 marks per key, the F2-F6 count for the attempt cap."""
    al = run.al
    _time_left(run)
    out = AL.fill_page_always(
        list(fields), brief=al.brief, rctx=run.rctx, ask=al.ask, rules=run.services.rules,
        today=run.today, cfg=run.cfg, step_title=run.step, uploaded=run.ctx.uploaded,
        page_text=P.page_text(run.page, run.scope), composed=run.ctx.composed,
        composed_files=run.ctx.composed_files, audit=run.audit,
        attempt_fallbacks=al.before + al.guesses, entries=al.entries, stats=al.stats,
        classes=al.classes)
    if out.transport_failed:
        return out
    run.answers.update(out.answers)
    for k, a in out.answers.items():
        al.fb[k] = k in out.fallback
        al.sk[k] = k in out.standing_kept
        if k in out.fallback and a.assumed:
            al.guesses += 1                                 # F2-F6 (F0/F1 are not assumed)
        if corrective:
            al.corrected.add(k)
        elif a.tier is AnswerTier.LLM and k not in out.fallback:
            al.model_keys.add(k)
    return out


def _always_apply(run: _Run, keys: Sequence[str]) -> None:
    for key in keys:
        if key in run.answers and key not in run.dead:
            _always_apply_one(run, key, run.answers[key])
        if run.transport:
            raise _Stop(run.transport)


def _blank(v: Any) -> bool:
    return v is None or v == [] or (isinstance(v, str) and not v.strip())


def _always_apply_one(run: _Run, key: str, ans: Answer) -> None:
    """A7 for one field: a FILLED value is put in with the widgets' strict read-back (a
    remote typeahead through the query ladder); an optional field the model left empty
    that shows a site value is cleared (G9 mechanics); a kept site value (PREFILLED), an
    UNKNOWN left empty for the site's validation and a skipped field are left alone."""
    pf = run.fields[key]
    if ans.status is AnswerStatus.BLANK_OPTIONAL:
        if pf.origin in G.SITE_ORIGINS and not _blank(pf.shown) and P.shown_visible(run.page, pf):
            r = W.reset_field(run.page, pf)
            if r.ok:
                _mark(run, key, ValueOrigin.EMPTY)
            else:
                run.answers[key] = _replace(ans, value=r.shown, status=AnswerStatus.PREFILLED,
                                            confidence=G.CONF_UNVERIFIED, note=G.UNVERIFIED_NOTE)
        return
    if ans.status is not AnswerStatus.FILLED:
        return
    if not P.shown_visible(run.page, pf):                   # K10: re-checked before each fill
        run.answers[key] = _replace(ans, status=AnswerStatus.SKIPPED, note=HIDDEN_NOTE)
        return
    if pf.field.type is FieldType.FILE:
        _apply_one(run, key, ans, False)                    # the strict upload mechanics (P1)
        return
    search = AL.is_search(pf) and not ans.option_labels
    wanted = ans.option_labels[0] if ans.option_labels else _text(ans.value)
    pick = _always_picker(run, pf, wanted)
    if search:
        r = W.fill_search(run.page, pf, W.query_ladder(wanted, _query_fallbacks(run, pf)), pick=pick)
    else:
        r = W.fill_field(run.page, pf, _fill_value(pf, ans), pick=pick)
    if not r.ok:
        run.failed[key] = r.note or "readback"
        return
    _mark(run, key, ValueOrigin.OURS)
    run.failed.pop(key, None)
    run.al.expected[key] = r.shown
    if pf.field.type is not FieldType.MULTI_CHOICE and (r.picked or search) and isinstance(r.shown, str) \
            and r.shown and r.shown != ans.value:
        run.answers[key] = _replace(ans, value=r.shown, option_labels=(r.shown,))


def _always_picker(run: _Run, pf: PageField, wanted: str):
    """§4.4 at fill time (`pick_refused` is strict only): the options the widget lists go to
    `always.ladder` with the decided words (R0, R1), then one R2 pick call on the shared
    prefix. Transport failures end the page (`run.transport`)."""
    if pf.field.type not in _CHOICE_WIDGET_TYPES:
        return None

    def pick(want: str, options: Sequence[str]) -> str:
        words = wanted or want
        hit, _rung = AL.ladder(words, list(options))
        if hit:
            return hit
        if run.services.deadline_left() <= 0:
            run.transport = run.transport or TIMED_OUT_NOTE
        if run.transport:
            return ""
        try:
            return AL.pick_call(run.al.pctx, pf, words, list(options)) or ""
        except (BackendError, TimeoutError) as exc:
            run.transport = _backend_note(exc)
            return ""
    return pick


def _query_fallbacks(run: _Run, pf: PageField) -> list[str]:
    """§4.4 family fallbacks for a remote typeahead: a place -> `contact.city`, then the
    country; a school -> the bound (else the newest) entry's institution without a leading
    "The" / "University of"."""
    prof = run.al.profile
    toks = set(F.tokens(" ".join((pf.field.label, pf.field.description))))
    out: list[str] = []
    if toks & set(_PLACE_WORDS):
        city = applicant.get_path(prof, "contact.city")
        country = str(applicant.get_path(prof, "contact.country") or "")
        out += [str(city or ""), applicant.COUNTRY_NAMES.get(country.upper(), country)]
    if toks & set(_SCHOOL_WORDS):
        entry = run.al.entries.get(pf.group, "")
        if not entry.startswith("education[") and run.al.order.get("education"):
            entry = f"education[{run.al.order['education'][0]}]"
        inst = str(applicant.get_path(prof, f"{entry}.institution") or "") if entry else ""
        inst = re.sub(r"^\s*the\s+", "", inst, flags=re.I)
        out.append(re.sub(r"^\s*university\s+of\s+", "", inst, flags=re.I))
    return [x for x in out if x and x.strip()]


def _always_surplus(run: _Run) -> None:
    """§4.5 surplus slots: deleted when they have a delete control (bottom up, confirmed
    by the slot's controls being gone); otherwise an optional field showing a value is
    cleared, and a required one is left as shown with an audit note."""
    al = run.al
    if not al.surplus:
        return
    groups = {f"{s.section}#{g.index}": g for s in run.sections for g in s.entries}
    clicked = False
    for gid in sorted(al.surplus, key=lambda g: -_index(g)):
        members = [k for k in run.order if k in run.fields and run.fields[k].group == gid]
        g = groups.get(gid)
        if g is not None and g.delete_locator and P.click(run.page, run.page.locator(g.delete_locator).first):
            clicked = True
            run.page.wait_for_timeout(300)
            if not any(_present(run, run.fields[k]) for k in members):
                run.dead |= set(members)
                run.services.log(f"E3: surplus entry deleted ({gid})")
                continue
        for k in members:
            pf = run.fields[k]
            if not _blank(pf.shown) and not pf.field.required:
                r = W.reset_field(run.page, pf)
                if r.ok:
                    _mark(run, k, ValueOrigin.EMPTY)
                    run.answers[k] = Answer(field_key=k, value=None, tier=AnswerTier.NONE, source="",
                                            confidence=0.0, status=AnswerStatus.BLANK_OPTIONAL,
                                            rule_id=AL.PROMPT_VERSION, note=f"{SURPLUS_NOTE}; cleared")
                    continue
            if _blank(pf.shown):
                run.answers[k] = _skip_answer(k, f"{SURPLUS_NOTE}; left empty")
            else:
                run.answers[k] = Answer(field_key=k, value=pf.shown, tier=AnswerTier.NONE,
                                        source=pf.origin.value, confidence=G.CONF_UNVERIFIED,
                                        status=AnswerStatus.PREFILLED, rule_id=AL.PROMPT_VERSION,
                                        note=f"{SURPLUS_NOTE}; left as shown")
    if clicked:
        run.sections = list(run.nav.entry_sections(run.page, run.ctx) or [])


def _always_adds(run: _Run) -> None:
    """§4.5 Adding: one "Add another" click per wanted entry; the new slot is bound to its
    source entry and gets its own round (A2-A7). A failed Add is a note in the job log
    ("1 of 2 education entries added"), not a stop (rev L7; WP-F1 branches E5 on the policy)."""
    al = run.al
    wanted: dict[str, int] = {}
    added: dict[str, int] = {}
    why_of: dict[str, str] = {}
    for section, eid in list(al.adds):
        wanted[section] = wanted.get(section, 0) + 1
        why = _always_add_one(run, section, eid)
        if why:
            why_of.setdefault(section, why)
        else:
            added[section] = added.get(section, 0) + 1
    for section, n in wanted.items():
        if added.get(section, 0) < n:
            run.services.log(f"E5: {added.get(section, 0)} of {n} {section.replace('_', ' ')} entries "
                             f"added ({why_of.get(section, 'add failed')})")


def _always_add_one(run: _Run, section: str, eid: str) -> str:
    _time_left(run)
    sec = next((s for s in run.sections if s.section == section), None)
    if sec is None or not sec.add_locator:
        return "no add control"
    count = len(sec.entries)
    if not P.click(run.page, run.page.locator(sec.add_locator).first):
        return "add click failed"
    run.page.wait_for_timeout(ADD_WAIT_MS)
    fields = _always_read(run)
    after = next((s for s in run.sections if s.section == section), None)
    if after is None or len(after.entries) <= count:
        return "no entry appeared"
    new = F.group_id(section, sorted(after.entries, key=lambda g: g.index)[count].index)
    fresh = [pf for pf in fields if pf.group == new and not _seen(run, pf)]
    if not fresh:
        return "new entry has no fields"
    run.al.entries[new] = eid
    todo = _always_prepare(run, fresh, bind=False)
    out = _always_round(run, todo)
    if out.transport_failed:
        raise _Stop(UNAVAILABLE_NOTE)
    run.services.classify(run.page)
    _time_left(run)
    _always_apply(run, [pf.field.key for pf in todo])
    return ""


def _always_reveal(run: _Run, rounds: int) -> None:
    """A7 revealed fields: re-read; fields not seen before get A1-A7, at most `rounds`."""
    for _ in range(max(0, rounds)):
        new = [pf for pf in _always_read(run) if not _seen(run, pf) and pf.field.key not in run.dead]
        if not new:
            return
        todo = _always_prepare(run, new, bind=False)
        out = _always_round(run, todo)
        if out.transport_failed:
            raise _Stop(UNAVAILABLE_NOTE)
        run.services.classify(run.page)
        _time_left(run)
        _always_apply(run, [pf.field.key for pf in todo])


def _always_verify(run: _Run) -> None:
    """A7 verification read: every value we filled is read again; one the site reverted is
    filled once more, else the field is `fill_failed` ("reverted")."""
    for key, want in list(run.al.expected.items()):
        pf = run.fields.get(key)
        if pf is None or key in run.dead or key in run.failed or not _present(run, pf):
            continue
        if W.same(pf, W.read(run.page, pf), want):
            continue
        r = W.fill_field(run.page, pf, want)
        if not (r.ok and W.same(pf, W.read(run.page, pf), want)):
            run.failed[key] = REVERTED_NOTE


def _always_corrective(run: _Run) -> None:
    """A8: fields that failed, show a site error, or are required and still empty get one
    round with their error (always's TASK_CORRECT, then A5/A6) and are filled once. What
    still fails stays in `failed` (the flow ends `validation_error`)."""
    errors = {k: e for k, e in P.field_errors(run.page, scope=run.scope).items() if k}
    hits = set(P.scan_required(run.page, run.scope))
    skipped = {k for k, a in run.answers.items() if a.status is AnswerStatus.SKIPPED}
    surplus = {k for k, pf in run.fields.items() if pf.group and pf.group in run.al.surplus}
    targets = (set(run.failed) | set(errors) | hits) - run.dead - skipped - surplus
    if not targets:
        return
    run.services.classify(run.page)
    fields = []
    for pf in _always_read(run):
        k = pf.field.key
        if k not in targets:
            continue
        if not pf.error:
            pf = _replace(pf, error=errors.get(k) or (SCAN_ERROR if k in hits and k not in run.failed
                                                     else "not accepted"))
        run.fields[k] = pf
        fields.append(pf)
    if not fields:
        return
    out = _always_round(run, fields, corrective=True)
    if out.transport_failed:
        raise _Stop(UNAVAILABLE_NOTE)
    for pf in fields:
        run.failed.pop(pf.field.key, None)
    _always_apply(run, [pf.field.key for pf in fields])


def _always_scan(run: _Run) -> None:
    """The required scan after A8: what is still empty or in error is `fill_failed`."""
    for key in P.scan_required(run.page, run.scope):
        if key not in run.dead:
            run.failed.setdefault(key, "required_scan")


def _always_cache_put(run: _Run) -> None:
    """§8 fill cache under `always`: the same key shape; prompt_version `always:v2`;
    inputs_hash = sha(briefing.hash + JD + "always"); values stored with the D-202 rule
    (`stored_quote`, `_stored_value`); no corrective, fallback or pick rows. A1-A (§17.3): each
    row carries the field's `class[:which]` in its decision (`always.fill_page_always(classes=)`),
    and a field without one gets no row."""
    al = run.al
    if al is None or not run.cfg.get("cache", True):
        return
    inputs = hashlib.sha256((str(al.brief.hash) + (run.rctx.jd_text or "") + "always")
                            .encode("utf-8")).hexdigest()[:16]
    hkey = F.hash_key(run.rctx)
    pfs = [run.fields[k] for k in run.order if k in run.fields]
    quals = K.qualified_labels(pfs)
    rows = []
    for pf in pfs:
        k = pf.field.key
        a = run.answers.get(k)
        if (a is None or k not in al.model_keys or k in al.corrected or al.fb.get(k) or k in run.failed
                or a.status not in (AnswerStatus.FILLED, AnswerStatus.BLANK_OPTIONAL, AnswerStatus.PREFILLED)):
            continue
        if not al.classes.get(k):
            continue                                        # A1-A: no class, no row (never a code-only replay)
        ref = a.source if a.source.startswith(("profile:", "extra:", "standing:")) else ""
        rows.append({"field_sig": F.field_sig(pf, quals.get(k, ""), key=hkey),
                     "prompt_version": AL.PROMPT_VERSION, "model": run.services.model,
                     "inputs_hash": inputs,
                     "facts_used_hash": F.facts_used_hash([ref] if ref else [], run.rctx, today=run.today),
                     "decision": {"source": a.source, "ref": ref,
                                  "evidence": stored_quote(a.evidence, a, run.qv),
                                  "value": _stored_value(a.value, a, run.qv), "assumed": bool(a.assumed),
                                  "via": ALWAYS_VIA, "class": al.classes[k]}})
    if rows:
        run.services.cache_put(_job_id(run), rows)


def always_row_decision(key: str, row: Mapping[str, Any]) -> Optional[ModelDecision]:
    """A1-A (§17.3, pin 28): a fill-cache row written under `always` -> the ModelDecision to
    replay, with `klass` / `which` rebuilt from the stored `class`, or None (a MISS: the field
    is asked again) when the row has no readable class or another prompt version. Replay
    under `always` is OFF today (`_always_steps` never reads the cache): a switch-on calls
    this on each `services.cache_get(..., AL.PROMPT_VERSION, ...)` row, after the same
    `facts_used_hash` check `_cached` makes. A class-less row must never be replayed as the
    model's silent key: code could then take it as code-only."""
    if row.get("prompt_version", AL.PROMPT_VERSION) != AL.PROMPT_VERSION:
        return None
    d = row.get("decision") or {}
    klass, which = AL.parse_class(d.get("class"))
    if klass is None:
        return None
    stored = str(d.get("source") or "")                     # an Answer's source: "default:<rule>", "profile:<path>", "assumption"
    try:
        source = FillSource(stored.partition(":")[0])
    except ValueError:
        return None
    ref = d.get("ref") or (stored if source is FillSource.DEFAULT else "")
    return ModelDecision(key, source, ref, d.get("value"), d.get("evidence", ""),
                         via=f"cache:{d.get('via', ALWAYS_VIA)}", assumed=bool(d.get("assumed")),
                         klass=klass, which=which)


def _always_outcome(run: _Run, *, compose: Sequence[str] = ()) -> PageOutcome:
    """A9: answers, fill_failed, the per-page counts; `unknown_required` is always ()."""
    _always_cache_put(run)
    al = run.al
    answers = dict(run.answers)
    failed = [k for k in run.order if k in run.failed and k not in run.dead]
    for k in failed:
        if k in answers:
            answers[k] = _replace(answers[k], status=AnswerStatus.FILL_FAILED,
                                  note=answers[k].note or f"fill: {run.failed[k]}")
    keys = [k for k in run.order if k in answers]
    assumed = tuple(k for k in keys if answers[k].assumed)
    fallback = tuple(k for k in keys if al.fb.get(k))
    standing = tuple(k for k in keys if al.sk.get(k))
    filled = sum(1 for k in keys if answers[k].status in (AnswerStatus.FILLED, AnswerStatus.PREFILLED))
    run.services.log(f"page {run.step or 'form'}: {filled} answered, {len(assumed)} assumed, "
                     f"{len(fallback)} fallback, {len(standing)} standing kept, {al.stats.calls} calls, "
                     f"{round(al.stats.seconds)} s")
    fields = [run.fields[k] for k in run.order if k in run.fields]
    return PageOutcome(step=run.step, fields=fields, answers=answers, unknown_required=(),
                       fill_failed=tuple(failed), model_calls=al.stats.calls,
                       model_seconds=round(al.stats.seconds, 3), transport_failed=False,
                       compose_needed=tuple(compose), assumed=assumed, fallback=fallback,
                       standing_kept=standing)


def _always_transport(run: _Run, note: str) -> PageOutcome:
    out = _transport(run, note)
    if run.al is None:
        return out
    return _replace(out, model_calls=run.al.stats.calls, model_seconds=round(run.al.stats.seconds, 3))
