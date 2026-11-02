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
from dataclasses import dataclass, field as dc_field, replace as _replace
from pathlib import Path
from typing import Any, Optional, Sequence

from . import page as P
from . import widgets as W
from .contracts import (
    Answer, AnswerStatus, AnswerTier, AttemptContext, EntrySection, FieldType, FillSource,
    ModelDecision, PageField, PageOutcome, ResolveContext, ValueOrigin,
)

L1_KEPT_NOTE = "L1: kept, uploaded in this attempt"     # locks: the file on the page is ours
TIMED_OUT_NOTE = "transport: timed out"
UNAVAILABLE_NOTE = "transport: model unavailable"
DEFAULT_REVEAL_ROUNDS = 2
DEFAULT_FOLLOWUPS = 25
DEFAULT_LONG_LIST = 15
NO_CACHE_VIAS = ("second", "corrective")                 # page-specific: never replayed
FACT_SOURCES = frozenset({FillSource.PROFILE, FillSource.EXTRA, FillSource.STANDING})


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
    mods: Any
    cfg: dict
    stats: Any
    step: str = ""
    scope: str = ""
    sections: list = dc_field(default_factory=list)
    facts: list = dc_field(default_factory=list)
    sv: list = dc_field(default_factory=list)
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


def fill_page(page: Any, nav: Any, ctx: AttemptContext, rctx: ResolveContext, services: Any) -> PageOutcome:
    """Fill one page (LF §8). Raises what `facts.check_entries` (PROFILE_INCOMPLETE) and
    `services.classify` (CAPTCHA / bot check) raise; everything else is in the outcome."""
    from . import facts as F, guards as G, llm_fill as L, locks as K    # lane M, same stage
    from ..backends import BackendError

    class _Mods:
        pass
    mods = _Mods()
    mods.F, mods.G, mods.L, mods.K, mods.BackendError = F, G, L, K, BackendError
    run = _Run(page=page, nav=nav, ctx=ctx, rctx=rctx, services=services, mods=mods,
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
    run.blocks = F.entry_blocks(rctx)
    run.inputs_hash = F.inputs_hash(L.redact(rctx.resume_text or "", run.sv), rctx.jd_text or "")
    try:
        # 3-6
        decision = _decide(run, fields, run.sections, {})
        # 7. a required unknown: nothing on the page has been changed (M9, TR-7)
        if decision.unknown_required:
            return _outcome(run, unknown=decision.unknown_required)
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
        # 11. corrective pass
        _corrective(run)
        # 12. the required scan
        stop = _required_scan(run)
        if stop:
            return _outcome(run, unknown=stop)
    except _Stop as halt:
        return _transport(run, halt.note)
    except BackendError:
        return _transport(run, UNAVAILABLE_NOTE)
    if run.transport:
        return _transport(run, run.transport)
    # 13. the decision cache
    _cache_put(run)
    return _outcome(run)


# ------------------------------------------------------------------ steps 1, 3-6

def _read(run: _Run, sections: Sequence[EntrySection]) -> list[PageField]:
    """Read the scope; remember each field's first audit key and its latest PageField."""
    fields = P.read_page(run.page, scope=run.scope, sections=list(sections), origin=run.ctx.prefill or "",
                         known=run.known, step=run.step, pre_import=run.ctx.pre_import or None)
    akeys = P.audit_keys(run.page, fields, run.step) if fields else {}
    by_audit = {a: k for k, a in run.audit.items()}
    for pf in fields:
        key = pf.field.key
        if key not in run.audit:
            old = by_audit.get(akeys.get(key, ""))
            run.audit[key] = run.audit.get(old, "") if old else akeys.get(key, "")
            if old and old in run.answers and key not in run.answers:   # a re-created element (F6)
                run.answers[key] = _replace(run.answers[old], field_key=key)
        if key not in run.fields:
            run.order.append(key)
        run.fields[key] = pf
    return fields


def _seen(run: _Run, pf: PageField) -> bool:
    """Decided on this page already (by reader key, or by audit key after a re-render)."""
    key = pf.field.key
    if key in run.answers:
        return True
    a = run.audit.get(key, "")
    return bool(a) and any(run.audit.get(k) == a for k in run.answers)


def _decide(run: _Run, fields: Sequence[PageField], sections: Sequence[EntrySection],
            forced: dict[str, str]):
    """Steps 3-6 for `fields`: locks, cache replay, model chunks and follow-ups, decide.
    `forced`: group id -> source entry id for entries we added (E5)."""
    F, G, L, K = run.mods.F, run.mods.G, run.mods.L, run.mods.K
    fields = list(fields)
    matches = dict(F.match_entries(list(sections), fields, run.rctx))
    matches.update(forced)
    # 3. locks (final; the model never sees a locked field as a question)
    locked = K.lock_page(fields, run.rctx, run.services.rules, today=run.today,
                         uploaded=run.ctx.uploaded, page_text=P.page_text(run.page, run.scope))
    quals = K.qualified_labels(fields)
    for pf in fields:
        run.sigs[pf.field.key] = F.field_sig(pf, quals.get(pf.field.key, ""))
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
                    s_values=run.sv, cfg=run.cfg, locked=locked, stats=run.stats)
        decisions += got
        run.fresh += got
    decisions += _long_list_picks(run, fields, decisions)
    by_key = {pf.field.key: pf for pf in fields}
    for key in G.recheck_targets(fields, decisions, matches, run.rctx, blocks=run.blocks):
        pf = by_key.get(key)
        if pf is None or not _followup_ok(run):
            continue
        d = L.recheck_entry(run.services.backend, pf, run.blocks.get(matches.get(pf.group) or "", ""),
                            s_values=run.sv, cfg=run.cfg, stats=run.stats)
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
    """LL2 (§6.4): an answer on a fully read list whose words name no option gets a
    `pick` call when the list is longer than `long_list` (the model saw no enum) or the
    answer cites a fact (the words are the fact's, not an option; guards path G2e).
    decide then guards the picked option (G1, G4, G5)."""
    G, L = run.mods.G, run.mods.L
    long_list = int(run.cfg.get("long_list", DEFAULT_LONG_LIST))
    by_key = {pf.field.key: pf for pf in fields}
    out = []
    latest = {d.field_key: d for d in decisions}
    for key, d in latest.items():
        pf = by_key.get(key)
        if (pf is None or not G.is_choice(pf) or not pf.options_complete
                or not (len(pf.field.options) > long_list or d.source in FACT_SOURCES)
                or not isinstance(d.value, str) or not d.value.strip()
                or G.option_for(pf, d.value) is not None or not _followup_ok(run)):
            continue
        _time_left(run)
        choice = L.pick_option(run.services.backend, pf, d.value, [o.label for o in pf.field.options],
                               s_values=run.sv, cfg=run.cfg, stats=run.stats)
        pick = ModelDecision(key, d.source, d.ref, choice or "", d.evidence, via="pick")
        out.append(pick)
        run.fresh.append(pick)
    return out


def _second(run: _Run, pf: PageField, matches: dict) -> ModelDecision:
    """G5's second call; past the follow-up budget or the deadline it answers unknown
    (G5 then keeps nothing)."""
    L = run.mods.L
    key = pf.field.key
    if not _followup_ok(run) or run.services.deadline_left() <= 0:
        return ModelDecision(key, FillSource.UNKNOWN, via="second")
    ch = run.chunk_of.get(key) or L.Chunk(f"one:{key}", matches.get(pf.group) if pf.group else None, (pf,))
    return L.second_opinion(run.services.backend, pf, ch, run.facts, run.rctx, step_title=run.step,
                            s_values=run.sv, cfg=run.cfg, stats=run.stats)


def _followup_ok(run: _Run) -> bool:
    return run.stats.followups < int(run.cfg.get("max_followups", DEFAULT_FOLLOWUPS))


def _time_left(run: _Run) -> None:
    if run.services.deadline_left() <= 0:
        raise _Stop(TIMED_OUT_NOTE)


# ------------------------------------------------------------------ step 9

def _apply(run: _Run, decision: Any, fields: Sequence[PageField],
           sections: Sequence[EntrySection]) -> tuple[str, ...]:
    """Entry deletes, entry adds (a round each), then fills and G9 resets in page order.
    Returns the unknown required keys of an added entry's round (a stop), else ()."""
    groups = {f"{s.section}#{g.index}": g for s in sections for g in s.entries}
    for gid in sorted(decision.deletes, key=lambda g: -_index(g)):    # bottom up: the rest stay put
        g = groups.get(gid)
        if g is not None and g.delete_locator:
            P.click(run.page, run.page.locator(g.delete_locator).first)
            run.page.wait_for_timeout(300)
    deleted = set(decision.deletes)
    for key in [pf.field.key for pf in fields]:
        if key not in decision.answers or run.fields[key].group in deleted:
            continue
        _apply_one(run, key, decision.answers[key], key in decision.resets)
    for section, source in decision.adds:
        stop = _add_entry(run, section, source)
        if stop:
            return stop
    return ()


def _apply_one(run: _Run, key: str, ans: Answer, reset: bool) -> None:
    G = run.mods.G
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
        r = W.fill_field(run.page, pf, path, force=True)          # H6: replace what we didn't upload
        if r.ok:
            run.ctx.uploaded[Path(path).name] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            _mark(run, key, ValueOrigin.OURS)
        else:
            run.failed[key] = r.note or "readback"
        return
    value = _fill_value(pf, ans)
    r = W.fill_field(run.page, pf, value, pick=_picker(run, pf, ans))
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
    G, L = run.mods.G, run.mods.L
    if pf.field.type not in (FieldType.DROPDOWN, FieldType.RADIO, FieldType.TYPEAHEAD,
                             FieldType.MULTI_CHOICE):
        return None
    quote = ans.evidence or _text(ans.value)

    def pick(want: str, options: Sequence[str]) -> str:
        if run.transport or not _followup_ok(run) or run.services.deadline_left() <= 0:
            return ""
        try:
            got = L.pick_option(run.services.backend, pf, want, list(options), s_values=run.sv,
                                cfg=run.cfg, stats=run.stats) or ""
        except run.mods.BackendError:
            run.transport = UNAVAILABLE_NOTE
            return ""
        return got if got and G.g4_ok(got, quote) else ""
    return pick


def _add_entry(run: _Run, section: str, source: str) -> tuple[str, ...]:
    """E5: click the section's Add, read the new entry, give it its own round (3-9)."""
    sec = next((s for s in run.sections if s.section == section), None)
    if sec is None or not sec.add_locator:
        return ()
    before = {f"{s.section}#{g.index}" for s in run.sections for g in s.entries}
    if not P.click(run.page, run.page.locator(sec.add_locator).first):
        return ()
    run.page.wait_for_timeout(500)
    run.sections = list(run.nav.entry_sections(run.page, run.ctx) or [])
    new = [f"{s.section}#{g.index}" for s in run.sections for g in s.entries
           if s.section == section and f"{s.section}#{g.index}" not in before]
    if not new:
        return ()
    fields = [pf for pf in _read(run, run.sections) if pf.group in new and not _seen(run, pf)]
    if not fields:
        return ()
    decision = _decide(run, fields, run.sections, {new[0]: source})
    if decision.unknown_required:
        return decision.unknown_required
    run.services.classify(run.page)
    _time_left(run)
    for key in [pf.field.key for pf in fields]:
        if key in decision.answers:
            _apply_one(run, key, decision.answers[key], key in decision.resets)
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
    G, L, K = run.mods.G, run.mods.L, run.mods.K
    fields = [pf for pf in _read(run, run.sections) if pf.field.key in targets]
    if not fields:
        return
    fields = [pf if pf.error else _replace(pf, error=errors.get(pf.field.key) or "not accepted") for pf in fields]
    locked = K.lock_page(fields, run.rctx, run.services.rules, today=run.today,
                         uploaded=run.ctx.uploaded, page_text=P.page_text(run.page, run.scope))
    open_ = [pf for pf in fields if pf.field.key not in locked and pf.field.type is not FieldType.FILE]
    decisions = [run.decisions[pf.field.key] for pf in fields if pf.field.key in run.decisions]
    if open_:
        _time_left(run)
        got = L.ask(run.services.backend, L.Chunk("corrective", None, tuple(open_)), run.facts, run.rctx,
                    step_title=run.step, s_values=run.sv, cfg=run.cfg, locked=locked, stats=run.stats)
        decisions += got
    matches = dict(run.mods.F.match_entries(run.sections, fields, run.rctx))
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
        _apply(run, decision, fresh, run.sections)
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


# ------------------------------------------------------------------ step 13 and the outcome

def _cached(run: _Run, fields: Sequence[PageField]) -> list[ModelDecision]:
    """Replayed decisions (via "cache:<via>"); a row whose cited facts changed is a miss."""
    F, L = run.mods.F, run.mods.L
    if not run.cfg.get("cache", True) or not fields:
        return []
    sigs = {pf.field.key: run.sigs.get(pf.field.key, "") for pf in fields}
    rows = run.services.cache_get(str(run.ctx.job.get("id", "")), [s for s in sigs.values() if s],
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
        out.append(ModelDecision(key, source, d.get("ref", ""), d.get("value"), d.get("evidence", ""),
                                 via=f"cache:{d.get('via', 'page')}"))
    return out


def _cache_put(run: _Run) -> None:
    """The latest fresh decision per field (no G5 or corrective replies; no value for a
    fact decision: the program recomputes it, §13.3)."""
    F, L = run.mods.F, run.mods.L
    if not run.cfg.get("cache", True) or not run.fresh:
        return
    latest: dict[str, ModelDecision] = {}
    for d in run.fresh:
        if d.via not in NO_CACHE_VIAS:
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
                     "decision": {"source": d.source.value, "ref": d.ref, "evidence": d.evidence,
                                  "value": d.value if keep_value else None, "via": d.via}})
    if rows:
        run.services.cache_put(str(run.ctx.job.get("id", "")), rows)


def _mark(run: _Run, key: str, origin: ValueOrigin) -> None:
    """Record who put the field's value (F6: under the reader key and the audit key)."""
    run.known[key] = origin
    if run.audit.get(key):
        run.known[run.audit[key]] = origin


def _outcome(run: _Run, *, unknown: Sequence[str] = ()) -> PageOutcome:
    answers = dict(run.answers)
    failed = [k for k in run.order if k in run.failed and k not in unknown]
    for k in failed:
        if k in answers:
            answers[k] = _replace(answers[k], status=AnswerStatus.FILL_FAILED,
                                  note=answers[k].note or f"fill: {run.failed[k]}")
    fields = [run.fields[k] for k in run.order if k in run.fields]
    return PageOutcome(step=run.step, fields=fields, answers=answers, unknown_required=tuple(unknown),
                       fill_failed=tuple(failed), model_calls=run.stats.calls,
                       model_seconds=round(run.stats.seconds, 3), transport_failed=False)


def _transport(run: _Run, note: str) -> PageOutcome:
    """§11: no capture; every field without an answer is noted "transport: ...". A lane
    note about the deadline: it comes back the same way ("transport: timed out")."""
    answers = dict(run.answers)
    for key in run.order:
        if key not in answers:
            answers[key] = Answer(field_key=key, value=None, tier=AnswerTier.NONE, source="",
                                  confidence=0.0, status=AnswerStatus.UNKNOWN, note=note)
    fields = [run.fields[k] for k in run.order if k in run.fields]
    return PageOutcome(step=run.step, fields=fields, answers=answers, unknown_required=(),
                       fill_failed=(), model_calls=run.stats.calls,
                       model_seconds=round(run.stats.seconds, 3), transport_failed=True)


def _index(gid: str) -> int:
    tail = gid.rpartition("#")[2]
    return int(tail) if tail.isdigit() else 0


def _text(v: Any) -> str:
    return "; ".join(str(x) for x in v) if isinstance(v, list) else str(v or "")
