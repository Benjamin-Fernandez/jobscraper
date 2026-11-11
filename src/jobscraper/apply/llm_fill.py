"""The model call of D-78 form filling (llm_fill_design §6, §11, §13; ADR-0006).

The local model says, per open field, WHERE the answer comes from (a fact ref, the
resume, the job posting, the value the site shows, or unknown) and, for resume/job/keep,
the value with a verbatim quote. It never writes a fact's value: the program does that
after the guards (`guards.decide`, `facts.fact_value`). This module only builds prompts
and schemas, makes the calls through `backends.py` (the one place that talks to a
model) and parses the replies into `ModelDecision`s.

Privacy (§6.5, H4, NF-02): every user prompt is built in full and then put through
`redact` with the profile's S values, so no private value reaches the model from the
resume, the job text, the page's current values or the options. Private facts are shown
as "set"/"empty" only (`facts.facts_text`). Nothing here logs; a prompt's text is never
logged or stored, only its hash (`CallLog.prompt_hashes`).

Failures (§11): a reply cut by the output cap is split in half (a one-field call is
re-asked once); a malformed reply is re-asked once; a timeout is a BackendError. What
still fails raises BackendError: pagefill turns that into `transport_failed`
(`model_unavailable`), never a captured question.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field as dc_field
from typing import Any, Iterable, Mapping, NamedTuple, Optional, Sequence

from ..backends import BackendError
from . import facts as F, guards, questions, resolve
from .contracts import (
    CHOICE_TYPES, Answer, AnswerStatus, Fact, FieldType, FillSource, ModelDecision, PageField,
    ResolveContext,
)
from .plan import is_generic, norm_label, tokens

FILL_PROMPT_VERSION = "fill:v2"
assert guards.RULE_ID == FILL_PROMPT_VERSION

SYSTEM = """You fill in part of a job application form for ONE applicant. For every field id, say where the
answer comes from and give it. Sources:
- profile / extra / standing: a FACT. Give its exact ref. The program writes the value from the fact,
  so for a private fact leave value "" (never guess a private value).
- resume: the value comes from RESUME; copy into evidence the exact words it comes from (at most
  25 words). Every word of the value must appear in the evidence.
- job: the same, from JOB.
- keep: the field's current value (set by the site) is right; quote the source that shows it.
- unknown: the sources don't settle it.
Rules:
1. Never invent. If the sources don't contain the answer, source "unknown".
2. For a field with options, copy ONE option exactly (several only where the field allows several).
3. Dates as YYYY-MM-DD, YYYY-MM or YYYY to match the field's parts. Phone number without the
   country code when the form has a separate country-code field.
4. Prefer FACTS for contact details, address, work rights, salary, availability, consents and
   declarations; prefer RESUME for work history, education, skills and dates.
5. Put only the part that belongs in each field: a job title without the company or team, a company
   without the title.
6. A question about one entry (a job's location, a language's level) must use facts stated for THAT
   entry. The applicant's home city is not a job's location. A language level comes only from
   profile languages.
7. A field with a generic question (for example "Please specify") belongs to the question in its
   CONTEXT; answer it only if that question's answer needs it.
8. Optional fields you have no source for: unknown. Don't pad free text."""
SECOND_SYSTEM = SYSTEM + "\nThis is a check of a single field."
PICK_SYSTEM = ("Pick the one option that means the same as the wanted answer for the question. "
               "Copy it exactly. If none means the same, answer \"\".")
RECHECK_SYSTEM = ("Copy, from RESUME ENTRY only, the lines that belong in this field for this entry. "
                  "Copy them exactly; never add words. If none belong, answer unknown.")
FINAL_LINE = "Answer with one JSON object keyed by field id."
PICK_FINAL_LINE = 'Answer with one JSON object: {"choice": "<one option copied exactly, or \\"\\">"}.'
RECHECK_FINAL_LINE = ('Answer with one JSON object: {"source": "resume" or "unknown", "ref": "", '
                      '"value": "<the copied lines>", "evidence": "<the same lines>"}.')

SOURCES = tuple(s.value for s in FillSource)
PRIVATE = "[private]"
RESUME_CHARS = 8000
JD_CHARS = 3000
EVIDENCE_MAX = 240
SEARCH_WORDS_MAX = 40
DEFAULTS = {"page_timeout_s": 120, "max_fields_per_call": 20, "long_list": 15}
SEED = 7
SECOND_TEMPERATURE = 0.7
TOKENS_PER_FIELD = 120
TOKENS_BASE = 200
TOKENS_MAX = 8000
TEXT_MAX = {FieldType.TEXTAREA: 1500}
TEXT_MAX_DEFAULT = 255


class Chunk(NamedTuple):
    """One model call's share of a page (§6.1): an entry group (with its matched source
    entry) or ≤ max_fields open fields outside groups. `locked` = the keys of fields shown
    as context only (`locked: true`); they are not in the output schema."""
    id: str
    entry: Optional[str]
    fields: tuple[PageField, ...]
    locked: tuple[str, ...] = ()


@dataclass
class CallLog:
    """What the calls of one page cost and which prompt answered which field (the
    audit's `model` and `prompt_hash`, PageOutcome.model_calls/model_seconds). Hashes
    only: a prompt's text is never kept."""
    model: str = ""
    calls: int = 0
    followups: int = 0                      # pick, second, recheck calls (max_followups)
    seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    prompt_eval_ns: list[int] = dc_field(default_factory=list)
    prompt_hashes: dict[str, str] = dc_field(default_factory=dict)   # field key -> prompt hash


# --------------------------------------------------------------------------
# Privacy
# --------------------------------------------------------------------------

_DIGITY = re.compile(r"^[\d\s+\-().]+$")


def _value_pattern(v: str) -> str:
    """A whole-run pattern for one S value: "cap" never turns "captcha" into
    "[private]tcha"; a phone-like value also matches its digits with any spacing."""
    digits = re.sub(r"\D", "", v)
    if _DIGITY.match(v) and len(digits) >= 6:
        return r"(?<!\d)" + r"[\s\-.()]*".join(re.escape(d) for d in digits) + r"(?!\d)"
    body = r"\s+".join(re.escape(p) for p in v.split())
    lead = r"(?<![A-Za-z0-9])" if v[:1].isalnum() else ""
    trail = r"(?![A-Za-z0-9])" if v[-1:].isalnum() else ""
    return lead + body + trail


def redact(text: str, s_values: Sequence[str]) -> str:
    """Every S value in `text` -> "[private]" (case-insensitive, longest first; phone
    numbers also as digit runs with any spacing). Applied to the whole user prompt of
    every call after it is built (§6.5), and to the schema's option lists."""
    out = text or ""
    for v in sorted({str(x).strip() for x in s_values or () if str(x).strip()},
                    key=lambda s: (-len(s), s)):
        if len(v) < 3:
            continue
        out = re.sub(_value_pattern(v), PRIVATE, out, flags=re.IGNORECASE)
    return out


def _contains_s(text: str, s_values: Sequence[str]) -> bool:
    return bool(text) and redact(text, s_values) != text


def _withhold(pf: PageField, s_values: Sequence[str]) -> bool:
    """§6.5: `current_set` instead of `current` for EMAIL/PHONE fields, G7 or contact
    labels, and any shown value that contains an S value."""
    if pf.field.type in (FieldType.EMAIL, FieldType.PHONE):
        return True
    if guards.sensitive_label(pf) or guards._phrases(guards.CONTACT_WORDS, tokens(pf.field.label)):
        return True
    return _contains_s(guards._text_of(pf.shown), s_values)


# --------------------------------------------------------------------------
# Chunks, views, schema, prompt
# --------------------------------------------------------------------------

def chunks(fields: Sequence[PageField], matches: Mapping[str, Optional[str]], max_fields: int,
           *, locked: Iterable[str] = ()) -> list[Chunk]:
    """§6.1: each matched entry group is one chunk; the other open fields go in chunks of
    ≤ max_fields, in page order. FILE fields, compose targets (a cover letter or "why join"
    text, §19.1: the tailor writes those, L8) and fields of unmatched groups (junk, E3)
    never reach the model. A locked field rides along as context in its group's chunk
    (outside groups: the chunk of the open field before it, else the first)."""
    lk = set(locked or ())
    max_fields = max(1, int(max_fields or DEFAULTS["max_fields_per_call"]))
    out: list[Chunk] = []
    groups: dict[str, list[PageField]] = {}
    plain: list[PageField] = []
    for pf in fields:
        if pf.field.type is FieldType.FILE or questions.compose_needed(pf.field, pf.group):
            continue
        if pf.group:
            if matches.get(pf.group):
                groups.setdefault(pf.group, []).append(pf)
            continue
        plain.append(pf)
    page_chunks: list[list[PageField]] = []
    pending_locked: list[PageField] = []
    cur: list[PageField] = []
    n_open = 0
    for pf in plain:
        if pf.field.key in lk:
            (cur if cur else pending_locked).append(pf)
            continue
        if n_open >= max_fields:
            page_chunks.append(cur)
            cur, n_open = [], 0
        if pending_locked:
            cur.extend(pending_locked)
            pending_locked = []
        cur.append(pf)
        n_open += 1
    if cur:
        page_chunks.append(cur)
    for i, fs in enumerate(page_chunks, start=1):
        out.append(Chunk(f"page#{i}", None, tuple(fs),
                         tuple(p.field.key for p in fs if p.field.key in lk)))
    for gid, fs in groups.items():
        if all(p.field.key in lk for p in fs):
            continue
        out.append(Chunk(gid, matches.get(gid), tuple(fs),
                         tuple(p.field.key for p in fs if p.field.key in lk)))
    order = {pf.field.key: i for i, pf in enumerate(fields)}
    out.sort(key=lambda c: order.get(c.fields[0].field.key, 0))
    return out


def _long_list(cfg: Mapping[str, Any]) -> int:
    return int((cfg or {}).get("long_list", DEFAULTS["long_list"]))


def _short_options(pf: PageField, cfg: Mapping[str, Any]) -> Optional[list[str]]:
    opts = [o.label for o in pf.field.options]
    if pf.field.type in (FieldType.DATE, FieldType.FILE) or not opts:
        return None
    if not pf.options_complete or len(opts) > _long_list(cfg):
        return None
    return opts


def field_view(pf: PageField, *, s_values: Sequence[str], cfg: Mapping[str, Any] = None,
               locked: Optional[Answer] = None, is_locked: bool = False) -> dict[str, Any]:
    """The model's view of one field (§6.2): id, question, kind, required, section /
    group_title, context (generic labels), help, options or options_note, current or
    current_set, parts, site_error, locked."""
    f = pf.field
    v: dict[str, Any] = {"id": f.key, "question": f.label, "kind": f.type.value,
                         "required": bool(f.required)}
    if pf.group_title:
        v["group_title"] = pf.group_title
    elif f.section:
        v["section"] = f.section
    if pf.context and is_generic(norm_label(f.label)):
        v["context"] = pf.context
    if f.description:
        v["help"] = f.description[:300]
    if is_locked:
        v["locked"] = True
        if (locked is not None and locked.status is AnswerStatus.FILLED and not locked.sensitive
                and isinstance(locked.value, (str, bool)) and len(str(locked.value)) <= 100):
            v["answer"] = str(locked.value).lower() if isinstance(locked.value, bool) \
                else locked.value
        return v
    if f.type is FieldType.DATE:
        if f.options:
            v["parts"] = [o.label for o in f.options]
    else:
        short = _short_options(pf, cfg or {})
        if short is not None:
            v["options"] = short
        elif f.options:
            ex = "; ".join(o.label for o in f.options[:5])
            v["options_note"] = f"{len(f.options)} options, for example: {ex}"
        elif not pf.options_complete:
            v["options_note"] = (f"a search list: give the words to search for "
                                 f"(at most {SEARCH_WORDS_MAX} characters)")
    if f.type is FieldType.MULTI_CHOICE:
        v["several"] = True
    if guards._has_shown(pf):
        if pf.origin in guards.SITE_ORIGINS and not _withhold(pf, s_values):
            v["current"] = pf.shown if isinstance(pf.shown, list) else str(pf.shown)[:1500]
        else:
            v["current_set"] = True
    if pf.error:
        v["site_error"] = pf.error[:200]
    return v


def _allowed(pf: PageField, chunk: Chunk, facts: Sequence[Fact],
             rctx: ResolveContext) -> list[str]:
    matches = {pf.group: chunk.entry} if pf.group else {}
    return guards.allowed_refs(pf, facts, matches, rctx)


def _value_schema(pf: PageField, cfg: Mapping[str, Any]) -> dict[str, Any]:
    f = pf.field
    if f.type is FieldType.CHECKBOX:
        return {"type": "string", "enum": ["true", "false", ""]}
    short = _short_options(pf, cfg)
    if short is not None and f.type is FieldType.MULTI_CHOICE:
        return {"type": "array", "items": {"type": "string", "enum": short}}
    if short is not None and (f.type in CHOICE_TYPES or f.type is FieldType.TYPEAHEAD):
        return {"type": "string", "enum": short + [""]}
    if f.type is FieldType.MULTI_CHOICE:
        return {"type": "array", "items": {"type": "string", "maxLength": 200}}
    limit = f.max_length or TEXT_MAX.get(f.type, TEXT_MAX_DEFAULT)
    if f.type is FieldType.TYPEAHEAD and not pf.options_complete:
        limit = SEARCH_WORDS_MAX
    return {"type": "string", "maxLength": int(limit)}


def schema(chunk: Chunk, facts: Sequence[Fact], rctx: ResolveContext, *,
           cfg: Mapping[str, Any] = None, only: Optional[Sequence[PageField]] = None,
           s_values: Sequence[str] = ()) -> dict[str, Any]:
    """The `format` of one call (§6.3): per open field an object with `source` (enum),
    `ref` (enum: the refs this field may cite + ""), `value` (enum for short lists and
    checkboxes, else a bounded string) and `evidence` (≤ 240). Option texts pass through
    `redact` like the prompt."""
    cfg = cfg or {}
    fields = list(only) if only is not None else _open(chunk)
    props: dict[str, Any] = {}
    for pf in fields:
        props[pf.field.key] = {
            "type": "object",
            "properties": {
                "source": {"type": "string", "enum": list(SOURCES)},
                "ref": {"type": "string", "enum": _allowed(pf, chunk, facts, rctx) + [""]},
                "value": _value_schema(pf, cfg),
                "evidence": {"type": "string", "maxLength": EVIDENCE_MAX},
            },
            "required": ["source", "ref", "value", "evidence"],
        }
    out = {"type": "object", "properties": props, "required": [pf.field.key for pf in fields]}
    if s_values:
        out = json.loads(redact(json.dumps(out, ensure_ascii=False), s_values))
    return out


def _open(chunk: Chunk) -> list[PageField]:
    lk = set(chunk.locked)
    return [pf for pf in chunk.fields if pf.field.key not in lk
            and pf.field.type is not FieldType.FILE]


def _job_text(rctx: ResolveContext) -> str:
    lines = [f"Company: {rctx.employer_name}" if rctx.employer_name else ""]
    title = getattr(rctx, "job_title", "") or ""
    if title:
        lines.append(f"Title: {title}")
    lines.append((rctx.jd_text or "")[:JD_CHARS])
    return "\n".join(x for x in lines if x)


def user_prompt(chunk: Chunk, facts: Sequence[Fact], rctx: ResolveContext, *, step_title: str,
                s_values: Sequence[str], cfg: Mapping[str, Any] = None,
                locked: Optional[Mapping[str, Answer]] = None,
                only: Optional[Sequence[PageField]] = None,
                blocks: Optional[Mapping[str, str]] = None) -> str:
    """The user prompt, fixed order (§6.2, TR-4, TR-11): FACTS, RESUME (entry chunks:
    RESUME ENTRY <id> only), JOB, PAGE, FIELDS (JSON) as one array, the final line. FACTS
    is the same text in every call of an attempt, and FACTS + RESUME in every non-entry
    call (prefix reuse, §13.2). Redacted as a whole."""
    cfg = cfg or {}
    asked = {pf.field.key for pf in (only if only is not None else _open(chunk))}
    lk = set(chunk.locked)
    views = []
    for pf in chunk.fields:
        k = pf.field.key
        if k in asked:
            views.append(field_view(pf, s_values=s_values, cfg=cfg))
        elif k in lk:
            views.append(field_view(pf, s_values=s_values, cfg=cfg, is_locked=True,
                                    locked=(locked or {}).get(k)))
    parts = ["FACTS:", F.facts_text(facts, show_private=bool(getattr(rctx, "model_sees_sensitive", False))), ""]
    if chunk.entry:
        b = (blocks if blocks is not None else F.entry_blocks(rctx)).get(chunk.entry, "")
        parts += [f"RESUME ENTRY {chunk.entry}:", b or "(none)", ""]
    else:
        parts += ["RESUME:", (rctx.resume_text or "")[:RESUME_CHARS], ""]
    parts += ["JOB:", _job_text(rctx), "", f"PAGE: {step_title}", "",
              "FIELDS (JSON):", json.dumps(views, ensure_ascii=False), FINAL_LINE]
    return redact("\n".join(parts), s_values)


# --------------------------------------------------------------------------
# Calls
# --------------------------------------------------------------------------

def _hash(system: str, user: str) -> str:
    return hashlib.sha256((system + user).encode("utf-8")).hexdigest()[:16]


def _call(backend, system: str, user: str, fmt: dict, *, max_tokens: int,
          timeout: Optional[float], temperature: float, cfg: Mapping[str, Any],
          stats: Optional[CallLog], keys: Sequence[str], followup: bool) -> tuple[str, str]:
    """One completion: (text, done_reason). TimeoutError -> BackendError."""
    kw: dict[str, Any] = {}
    if (cfg or {}).get("keep_alive"):
        kw["keep_alive"] = cfg["keep_alive"]
    t0 = time.monotonic()
    try:
        c = backend.complete(system, user, max_tokens=max_tokens, timeout=timeout, format=fmt,
                             temperature=temperature, seed=SEED, **kw)
    except TimeoutError as exc:
        raise BackendError(f"model call timed out ({type(exc).__name__})") from None
    finally:
        if stats is not None:
            stats.calls += 1
            stats.followups += 1 if followup else 0
            stats.seconds += time.monotonic() - t0
            stats.model = stats.model or str(getattr(backend, "model_id", "") or "")
    if stats is not None:
        stats.input_tokens += int(getattr(c, "input_tokens", 0) or 0)
        stats.output_tokens += int(getattr(c, "output_tokens", 0) or 0)
        stats.prompt_eval_ns.append(int(getattr(c, "prompt_eval_ns", 0) or 0))
        h = _hash(system, user)
        for k in keys:
            stats.prompt_hashes[k] = h
    return str(getattr(c, "text", "") or ""), str(getattr(c, "done_reason", "") or "")


def _parse_obj(text: str) -> Optional[dict]:
    try:
        v = json.loads(text)
    except (TypeError, ValueError):
        m = re.search(r"\{.*\}", text or "", re.S)
        if not m:
            return None
        try:
            v = json.loads(m.group(0))
        except ValueError:
            return None
    return v if isinstance(v, dict) else None


def _value(v: Any) -> Any:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return [str(x) for x in v if isinstance(x, (str, int, float)) and str(x).strip()]
    return "" if v is None else str(v)


def decision(key: str, raw: Any, via: str) -> ModelDecision:
    """One reply object -> ModelDecision (an unreadable one -> unknown)."""
    if not isinstance(raw, dict):
        return ModelDecision(key, FillSource.UNKNOWN, via=via)
    try:
        src = FillSource(str(raw.get("source") or "unknown").strip().lower())
    except ValueError:
        src = FillSource.UNKNOWN
    return ModelDecision(field_key=key, source=src, ref=str(raw.get("ref") or "").strip(),
                         value=_value(raw.get("value")),
                         evidence=str(raw.get("evidence") or "")[:EVIDENCE_MAX], via=via)


def _via(chunk: Chunk, fields: Sequence[PageField]) -> str:
    if any(pf.error for pf in fields):
        return "corrective"
    return f"entry:{chunk.id}" if chunk.entry else "page"


def _max_tokens(n: int) -> int:
    return min(TOKENS_MAX, TOKENS_PER_FIELD * max(1, n) + TOKENS_BASE)


def _timeout(cfg: Mapping[str, Any]) -> float:
    return float((cfg or {}).get("page_timeout_s", DEFAULTS["page_timeout_s"]))


def _ask_fields(backend, chunk: Chunk, fields: list[PageField], facts, rctx, *, system: str,
                temperature: float, step_title: str, s_values, cfg, locked, stats,
                via: str, may_split: bool, followup: bool) -> list[ModelDecision]:
    user = user_prompt(chunk, facts, rctx, step_title=step_title, s_values=s_values, cfg=cfg,
                       locked=locked, only=fields)
    fmt = schema(chunk, facts, rctx, cfg=cfg, only=fields, s_values=s_values)
    keys = [pf.field.key for pf in fields]
    for attempt in (1, 2):
        text, done = _call(backend, system, user, fmt, max_tokens=_max_tokens(len(fields)),
                           timeout=_timeout(cfg), temperature=temperature, cfg=cfg,
                           stats=stats, keys=keys, followup=followup)
        if done == "length":
            if len(fields) > 1 and may_split:
                half = len(fields) // 2
                kw = dict(system=system, temperature=temperature, step_title=step_title,
                          s_values=s_values, cfg=cfg, locked=locked, stats=stats, via=via,
                          may_split=False, followup=followup)
                return (_ask_fields(backend, chunk, fields[:half], facts, rctx, **kw)
                        + _ask_fields(backend, chunk, fields[half:], facts, rctx, **kw))
            if attempt == 1 and len(fields) == 1 and may_split:
                continue
            raise BackendError("model reply cut by the output cap")
        reply = _parse_obj(text)
        if reply is None:
            if attempt == 1:
                continue
            raise BackendError("model reply is not a JSON object")
        out = []
        for k in keys:                       # ids not asked are ignored (G1)
            if k in reply:
                out.append(decision(k, reply[k], via))
        return out
    raise BackendError("model reply cut by the output cap")


def ask(backend, chunk: Chunk, facts: Sequence[Fact], rctx: ResolveContext, *, step_title: str,
        s_values: Sequence[str], cfg: Mapping[str, Any] = None,
        locked: Optional[Mapping[str, Answer]] = None,
        stats: Optional[CallLog] = None) -> list[ModelDecision]:
    """One decision per open field the model answered (a missing id -> no decision; G1
    then makes it unknown, "no reply"). Raises BackendError on a transport failure, a
    timeout, or a reply still cut or malformed after its one retry (§11). `locked` (the
    lock answers) lets a non-private locked value show as context; `stats` collects the
    audit's model / prompt hashes and the page's call count and seconds."""
    fields = _open(chunk)
    if not fields:
        return []
    return _ask_fields(backend, chunk, fields, facts, rctx, system=SYSTEM, temperature=0.0,
                       step_title=step_title, s_values=s_values, cfg=cfg or {}, locked=locked,
                       stats=stats, via=_via(chunk, fields), may_split=True, followup=False)


def second_opinion(backend, field: PageField, chunk: Chunk, facts: Sequence[Fact],
                   rctx: ResolveContext, *, step_title: str, s_values: Sequence[str],
                   cfg: Mapping[str, Any] = None, stats: Optional[CallLog] = None) -> ModelDecision:
    """G5 (§6.4): the same field alone, SECOND_SYSTEM, temperature 0.7, seed 7, without
    the first answer. The caller compares (guards.decide's `second`)."""
    one = Chunk(chunk.id, chunk.entry, (field,), ())
    out = _ask_fields(backend, one, [field], facts, rctx, system=SECOND_SYSTEM,
                      temperature=SECOND_TEMPERATURE, step_title=step_title, s_values=s_values,
                      cfg=cfg or {}, locked=None, stats=stats, via="second", may_split=True,
                      followup=True)
    return out[0] if out else ModelDecision(field.field.key, FillSource.UNKNOWN, via="second")


def _one_shot(backend, system: str, user: str, fmt: dict, *, cfg, stats, keys,
              max_tokens: int) -> dict:
    """A follow-up call with one retry for a cut or malformed reply."""
    for attempt in (1, 2):
        text, done = _call(backend, system, user, fmt, max_tokens=max_tokens,
                           timeout=_timeout(cfg), temperature=0.0, cfg=cfg or {}, stats=stats,
                           keys=keys, followup=True)
        reply = _parse_obj(text) if done != "length" else None
        if reply is not None:
            return reply
    raise BackendError("model reply cut or not a JSON object")


def pick_refused(field: PageField, wanted: str, *, s_values: Sequence[str] = (),
                 sensitive: bool = False, deny: Sequence[str] = ()) -> bool:
    """Review F1: a pick prompt carries the wanted value itself, so it is never made for
    a sensitive answer (`Answer.sensitive`), an S question (G7, incl. a generic label's
    context), a value holding a free-text S value, or one of the applicant's enum S
    values (`facts.enum_s_values`: "Chinese", "Singapore Citizen", ...)."""
    w = str(wanted or "").strip()
    if sensitive or guards.sensitive_label(field) or _contains_s(w, s_values):
        return True
    n = norm_label(w)
    return any(n and n == norm_label(d) for d in deny or ())


def pick_option(backend, field: PageField, wanted: str, options: Sequence[str], *,
                s_values: Sequence[str], cfg: Mapping[str, Any] = None,
                stats: Optional[CallLog] = None, sensitive: bool = False,
                deny: Sequence[str] = ()) -> Optional[str]:
    """LL2/LL3 (§6.4): the option that means `wanted`, copied exactly, else None (an
    answer that is not one of `options` is no answer, G1). Widgets get this injected,
    with `sensitive=answer.sensitive` and `deny=facts.enum_s_values(profile)`: a refused
    pick (`pick_refused`) makes no call and returns None, so LL3 ends the field unknown
    (required) or cleared (optional) and no S value reaches the model (review F1)."""
    opts = [str(o) for o in options if str(o).strip()]
    if not opts or not str(wanted or "").strip():
        return None
    det = deterministic_pick(wanted, opts)
    if det is not None:
        return det                       # the program's own match: no prompt, nothing sent
    if pick_refused(field, wanted, s_values=s_values, sensitive=sensitive, deny=deny):
        return None
    user = redact("\n".join([
        f"QUESTION: {field.field.label}",
        f"WANTED: {wanted}",
        "OPTIONS (JSON):", json.dumps(opts, ensure_ascii=False),
        PICK_FINAL_LINE]), s_values)
    fmt = {"type": "object", "properties": {"choice": {"type": "string", "enum": opts + [""]}},
           "required": ["choice"]}
    fmt = json.loads(redact(json.dumps(fmt, ensure_ascii=False), s_values))
    reply = _one_shot(backend, PICK_SYSTEM, user, fmt, cfg=cfg, stats=stats,
                      keys=[field.field.key], max_tokens=TOKENS_BASE)
    choice = reply.get("choice")
    if not (isinstance(choice, str) and choice in opts):
        return None
    if guards.skill_list(field) and not names_wanted(choice, wanted):
        return None                                  # Q-46(b): "PyTorch" is not "Python"
    return choice


_PHONE_CODE = re.compile(r"^\+\s*(\d{1,4})$")      # the "+" is required: bare digits are not a code (review F9)


def deterministic_pick(wanted: str, options: Sequence[str]) -> Optional[str]:
    """Lane R wd_a 02: the one option the program can match on its own, else None. An
    option equal (normalised) to `wanted` or naming it as its "Category > Leaf" leaf, or
    for a phone code ("+65") the one option showing that code ("<Country> (+65)"). No
    model call is made, so the enum-S deny list (which keeps S values out of prompts) does
    not apply: a country named in a phone-code option is the program's match, not a
    model-chosen value."""
    hits = resolve.path_hits(options, wanted)          # whole path, leaf or parent
    m = _PHONE_CODE.match(str(wanted).strip())
    if not hits and m:
        code = re.compile(r"\+\s*" + m.group(1) + r"(?!\d)")
        hits = [o for o in options if code.search(o)]
    return hits[0] if len(hits) == 1 else None


def names_wanted(choice: str, wanted: str) -> bool:
    """Q-46(b): a suggestion names the wanted skill when every word of `wanted` occurs as
    a whole word in it ("Python (Programming Language)" names "Python"; "PyTorch" not)."""
    want = set(tokens(wanted))
    return bool(want) and want <= set(tokens(choice.split(" > ")[-1]))


def recheck_entry(backend, field: PageField, block: str, *, s_values: Sequence[str],
                  cfg: Mapping[str, Any] = None, stats: Optional[CallLog] = None) -> ModelDecision:
    """E4 / G11 / D-84 R3 (§6.4): a copy task on one entry field. The returned lines must
    each occur (normalised) in the entry's block, else the answer is rejected; unknown or
    rejected -> unknown (the imported value is never kept: optional -> cleared by G9,
    required -> stop). A kept answer has source `resume`, via `recheck`."""
    key = field.field.key
    view = field_view(field, s_values=s_values, cfg=cfg or {})
    view.pop("current", None)
    view.pop("current_set", None)
    user = redact("\n".join([
        "RESUME ENTRY:", block or "(none)", "",
        "FIELDS (JSON):", json.dumps([view], ensure_ascii=False),
        RECHECK_FINAL_LINE]), s_values)
    limit = field.field.max_length or TEXT_MAX.get(field.field.type, TEXT_MAX_DEFAULT)
    fmt = {"type": "object", "properties": {
        "source": {"type": "string", "enum": ["resume", "unknown"]},
        "ref": {"type": "string", "enum": [""]},
        "value": {"type": "string", "maxLength": int(limit)},
        "evidence": {"type": "string", "maxLength": EVIDENCE_MAX}},
        "required": ["source", "ref", "value", "evidence"]}
    reply = _one_shot(backend, RECHECK_SYSTEM, user, fmt, cfg=cfg, stats=stats, keys=[key],
                      max_tokens=min(TOKENS_MAX, int(limit) // 2 + TOKENS_BASE))
    raw = reply.get(key) if key in reply and isinstance(reply.get(key), dict) else reply
    d = decision(key, raw, "recheck")
    value = guards._text_of(d.value)
    if d.source is not FillSource.RESUME or not value.strip() \
            or not guards.lines_in_block(value, block):
        return ModelDecision(key, FillSource.UNKNOWN, via="recheck")
    return ModelDecision(key, FillSource.RESUME, "", value, value[:EVIDENCE_MAX], via="recheck")
