"""Use a different answer next time (Q-127 W1; q127_profile_questions_design B.2b, B.5, B.11).

One click on an application's "What was sent" saves the owner's answer for the question it
was asked as an `extra` entry in `data/applicant.yaml` (resolver tier 3 and the briefing read
it on every later form). This module is the whole of that write path:

- `remember_refusal(row)` - the one pure check the GET (`can_remember`) and the POST share:
  H3 (an answer that follows the owner's details is never overridden from here: declarations,
  consents, standing rows, profile rows, work rights, sponsorship, self-ID, owner facts and
  files), then "too general" (a bare "Please specify" is no question), then H2 (another saved
  answer already holds the label).
- `plan_key(extra, label_norm)` - the key rule (H2): the exact-label lookup runs first over
  EVERY `extra` entry, so two entries never hold one label; a label of its own is updated, a
  shared one is refused, a new one gets `slug_key(label_norm, existing keys)`. A captured
  `questions` row's key is never the key written to: it came from a model's naming and may
  already name another entry. Nothing here changes any entry but the one for this label.
- `remember(...)` - validates the value against the field's kind, writes through the profile
  router's etag guard and write lock and `applicant.save` (the one atomic writer), then marks
  the attempt's captured questions answered. It never starts an application.

The normaliser, the generic-label test and the key slug are copies of `apply/plan.py` and
`apply/questions.py`: web/ may import only the contracts (NF-04). A parity pin keeps them equal
(tests/test_q127_web.py compares the slug; request in the software-engineer outbox for the rest).
No value, label or employer name is ever written to a log line here.
"""
from __future__ import annotations

import copy
import json
import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Optional

from jobscraper import applicant
from jobscraper.apply.contracts import (EXTRA_EMPLOYER_FIELD, GENERIC_LABELS, REMEMBER_REFUSAL_TEXTS,
                                        RememberRefusal, follows_your_details)
from jobscraper.store import utcnow
from jobscraper.web.routers.applicant import PROFILE_WRITE_LOCK, load_for_write, ready_to_retry_jobs

KINDS = ("yes_no", "choice", "multi", "text", "date", "number")
CHOICE_KINDS = ("choice", "multi")
TITLE_MAX = 60
SHOWN_MAX = 300

# ---- the label normaliser (copy of apply/plan.py norm_label, §7.1 steps 1-6) --------------------
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'"})
_NOISE = ("(required)", "(optional)", "*")
_NOT_TOKEN = re.compile(r"[^a-z0-9+#']+")
_LEADING_NUMBER = re.compile(r"^\d+ ")
_BLOCK_TAGS = frozenset({"br", "p", "div", "li", "ul", "ol", "tr", "td", "th",
                         "h1", "h2", "h3", "h4", "h5", "h6"})
_STOP_WORDS = frozenset("a an the of in on for to and or your you are is do does have has what "
                        "which please select enter provide".split())


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag, attrs) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append(" ")


def _html_to_text(text: str) -> str:
    if "<" not in text and "&" not in text:
        return text
    p = _Text()
    p.feed(text)
    p.close()
    return "".join(p.parts)


def _clean_token(tok: str) -> str:
    if tok.endswith("'s"):
        tok = tok[:-2]
    return tok.strip("'")


def norm_label(label: str) -> str:
    """The normalised wording of a label or an option (same rules as `apply.plan.norm_label`)."""
    text = unicodedata.normalize("NFKC", _html_to_text(label or "")).lower()
    text = text.translate(_APOSTROPHES)
    for noise in _NOISE:
        text = text.replace(noise, " ")
    tokens = [_clean_token(t) for t in _NOT_TOKEN.sub(" ", text).split()]
    text = " ".join(t for t in tokens if t)
    text = _LEADING_NUMBER.sub("", text)
    return " ".join(text.split())


def is_generic(label_norm: str) -> bool:
    """A label that cannot identify a question alone ("Please specify", a one-word label)
    (`apply.plan.is_generic`). A label qualified with its context ("please specify | ...")
    is not generic."""
    norm = norm_label(label_norm)
    if norm in GENERIC_LABELS:
        return True
    return len([t for t in norm.split() if t not in _STOP_WORDS]) < 2


def slug_key(label_norm: str, existing: Any = ()) -> str:
    """The deterministic `extra` key for a label (`apply.questions.slug_key` with plain
    existing keys): its first 4 tokens that are not stop words, joined with "_", at most 40
    characters, a letter first, the next free `_2`, `_3` when the name is held."""
    toks = [re.sub(r"[^a-z0-9_]", "", t) for t in label_norm.split() if t not in _STOP_WORDS]
    base = "_".join([t for t in toks if t][:4])
    base = re.sub(r"_+", "_", base).strip("_")[:40].rstrip("_") or "question"
    if not base[0].isalpha() or len(base) < 2:
        base = ("q_" + base)[:40].rstrip("_")
    taken = {str(k) for k in existing}
    if base not in taken:
        return base
    n = 2
    while True:
        suffix = f"_{n}"
        name = base[:40 - len(suffix)].rstrip("_") + suffix
        if name not in taken:
            return name
        n += 1


def _words(text: Any) -> str:
    return " ".join(str(text).casefold().split())


# ---- the check ---------------------------------------------------------------------------------

FILE_TYPES = ("file", "hidden")          # a file or a hidden field has no answer to remember


def label_norm_of(row: dict[str, Any], captured: Optional[dict[str, Any]]) -> str:
    """The label the answer is saved under: the captured question's (the capture stage's
    qualified label, "norm | context" for a generic one), else the audit row's."""
    if captured and str(captured.get("label_norm") or "").strip():
        return str(captured["label_norm"]).strip()
    return str(row.get("label_norm") or "").strip()


def label_holders(extra: Any, label_norm: str) -> list[str]:
    """The keys of every `extra` entry that lists this exact label (H2)."""
    if not isinstance(extra, dict):
        return []
    want = _words(label_norm)
    return [k for k, e in extra.items()
            if isinstance(e, dict) and isinstance(e.get("labels"), list)
            and any(_words(x) == want for x in e["labels"])]


def _own_entry(entry: dict[str, Any], label_norm: str) -> bool:
    """An entry made for this one label alone: its labels are exactly [label_norm], it is not a
    promoted topic and has no per-employer overrides (so a new value cannot be shadowed)."""
    labels = entry.get("labels")
    return (isinstance(labels, list) and len(labels) == 1 and _words(labels[0]) == _words(label_norm)
            and not entry.get("promoted") and not entry.get("by_employer"))


def plan_key(extra: Any, label_norm: str) -> tuple[str, Optional[str]]:
    """H2. ("update", key) when exactly one entry is this label's own; ("shared", None) when any
    other entry holds the label (several, a shared list, a promoted topic, per-employer
    overrides); ("new", slug) otherwise. Never a captured question's key."""
    holders = label_holders(extra, label_norm)
    if not holders:
        return "new", slug_key(label_norm, extra.keys() if isinstance(extra, dict) else ())
    if len(holders) == 1 and _own_entry(extra[holders[0]], label_norm):
        return "update", holders[0]
    return "shared", None


def remember_refusal(row: dict[str, Any], *, captured: Optional[dict[str, Any]] = None,
                     extra: Any = None) -> Optional[RememberRefusal]:
    """Why "Use a different answer next time" is not offered for this audit row, or None.
    `row` is an `apply_answers` row; `captured` the question the attempt captured for the field
    (`store.attempt_field_question`); `extra` the profile's `extra` block when known (the
    shared-answer test needs it; the GET and the POST both pass it).

    H3: refused whatever the label or the value when the row's source or class says its answer
    follows the owner's details (`contracts.follows_your_details`), and for a file."""
    if str(row.get("field_type") or "") in FILE_TYPES:
        return RememberRefusal.FOLLOWS_YOUR_DETAILS
    if follows_your_details(str(row.get("source") or ""), str(row.get("field_class") or "")):
        return RememberRefusal.FOLLOWS_YOUR_DETAILS
    label = label_norm_of(row, captured)
    if not label or is_generic(label):
        return RememberRefusal.TOO_GENERAL
    if extra is not None and plan_key(extra, label)[0] == "shared":
        return RememberRefusal.SHARED_ANSWER
    return None


def refusal_text(code: RememberRefusal, label: str = "") -> str:
    text = REMEMBER_REFUSAL_TEXTS[code]
    return text.format(label=label) if "{label}" in text else text


# ---- the field's kind and options ---------------------------------------------------------------

def option_pairs(row: dict[str, Any], captured: Optional[dict[str, Any]]) -> list[tuple[str, str]]:
    """[(label as offered, normalised)] from the audit row's `options_json`, else the captured
    question's options (whose `norm` the capture stage computed)."""
    raw = row.get("options_json")
    items: list[Any] = []
    if isinstance(raw, str) and raw.strip():
        try:
            items = json.loads(raw)
        except ValueError:
            items = []
    elif isinstance(raw, list):
        items = raw
    out: list[tuple[str, str]] = []
    for o in items if isinstance(items, list) else []:
        label = o.get("label") if isinstance(o, dict) else o
        if isinstance(label, str) and label.strip():
            out.append((label, norm_label(label)))
    if not out and captured:
        for o in captured.get("options") or []:
            if isinstance(o, dict) and o.get("label"):
                out.append((str(o["label"]), str(o.get("norm") or norm_label(str(o["label"])))))
    return out


def option_labels(row: dict[str, Any], captured: Optional[dict[str, Any]]) -> list[str]:
    return [lab for lab, _n in option_pairs(row, captured)]


_YES = ("yes", "y", "true", "checked", "on")
_NO = ("no", "n", "false", "unchecked", "off")


def field_kind(row: dict[str, Any], captured: Optional[dict[str, Any]]) -> Optional[str]:
    """The widget kind of the field: the captured question's (the capture stage's), else read
    from the field type and options. None for a file or a hidden field."""
    if captured and str(captured.get("kind") or "") in KINDS:
        return str(captured["kind"])
    ftype = str(row.get("field_type") or "")
    if ftype in FILE_TYPES:
        return None
    if ftype == "checkbox":
        return "yes_no"
    if ftype == "multi_choice":
        return "multi"
    if ftype in ("dropdown", "radio"):
        norms = {n for _l, n in option_pairs(row, captured)}
        return "yes_no" if norms and norms <= set(_YES + _NO) and len(norms) == 2 else "choice"
    if ftype == "number":
        return "number"
    if ftype == "date":
        return "date"
    return "text"


# ---- the value ---------------------------------------------------------------------------------

def _err(path: str, message: str) -> applicant.FieldError:
    return applicant.FieldError(path, message)


def _as_bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, list) and len(v) == 1:
        return _as_bool(v[0])
    if isinstance(v, str):
        w = norm_label(v)
        if w in _YES:
            return True
        if w in _NO:
            return False
    return None


def _as_number(v: Any) -> Any:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v.strip()) if "." in v else int(v.strip())
        except ValueError:
            return None
    return None


@dataclass
class Built:
    """The value part of an entry, the words shown for it and what `corrected_json` keeps."""
    fields: dict[str, Any] = field(default_factory=dict)
    shown: str = ""
    corrected: Any = None
    errors: list[applicant.FieldError] = field(default_factory=list)


def build_value(kind: str, value: Any, picks: Any, options: list[tuple[str, str]]) -> Built:
    """Check the owner's answer against the field's kind (yes_no, choice / multi with picks from
    the options seen, text, number, date) and shape it as the entry's `value` / `picks` /
    `seen`. A pick is an option label as offered; the entry stores the normalised wording."""
    out = Built()
    if kind in CHOICE_KINDS:
        chosen = picks if isinstance(picks, list) else ([value] if isinstance(value, str) else None)
        if not chosen or not all(isinstance(p, str) and p.strip() for p in chosen):
            out.errors.append(_err("picks", "choose an option"))
            return out
        if not options:
            out.errors.append(_err("picks", "this question's options are not on record"))
            return out
        by_norm = {n: lab for lab, n in options}
        norms: list[str] = []
        for p in chosen:
            n = norm_label(p)
            if n not in by_norm:
                out.errors.append(_err("picks", "is not one of this question's options"))
                return out
            if n not in norms:
                norms.append(n)
        if kind == "choice" and len(norms) > 1:
            out.errors.append(_err("picks", "choose exactly one option"))
            return out
        out.fields = {"value": None, "picks": norms,
                      "seen": list(dict.fromkeys(n for _l, n in options))}
        out.shown = ", ".join(by_norm[n] for n in norms)
        out.corrected = [by_norm[n] for n in norms]
        return out
    given = value if value is not None else (picks[0] if isinstance(picks, list) and picks else None)
    if kind == "yes_no":
        b = _as_bool(given)
        if b is None:
            out.errors.append(_err("value", "answer Yes or No"))
            return out
        out.fields, out.shown, out.corrected = {"value": b}, "Yes" if b else "No", b
    elif kind == "number":
        n = _as_number(given)
        if n is None:
            out.errors.append(_err("value", "give a number"))
            return out
        out.fields, out.shown, out.corrected = {"value": n}, str(n), n
    else:                                           # text, date
        if not isinstance(given, str) or not given.strip():
            out.errors.append(_err("value", "give an answer"))
            return out
        text = given.strip()
        out.fields, out.shown, out.corrected = {"value": text}, text, text
    return out


def shown(value: Any) -> str:
    """A remembered or sent value as one short line."""
    if value is None or isinstance(value, dict):
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)
    text = " ".join(text.split())
    return text if len(text) <= SHOWN_MAX else text[:SHOWN_MAX - 1] + "…"


def short_title(label: str) -> str:
    """The question's wording as the entry's title: at most 60 characters, cut at a word."""
    t = " ".join((label or "").split())
    if len(t) <= TITLE_MAX:
        return t
    return t[:TITLE_MAX + 1].rsplit(" ", 1)[0].rstrip(" ,;:-") or t[:TITLE_MAX]


# ---- the write ---------------------------------------------------------------------------------

class RememberError(Exception):
    """A refusal the route turns into `{detail: code, text, errors?}` with `status`."""

    def __init__(self, status: int, code: str, text: str = "",
                 errors: Optional[list[applicant.FieldError]] = None):
        super().__init__(code)
        self.status, self.code, self.text, self.errors = status, code, text, errors or []


def _employer_name(store: Any, job_id: str) -> str:
    job = store.get_job(job_id)
    name = (job or {}).get("company")
    if not name:
        name = (store.application(job_id) or {}).get("company")
    return str(name or "").strip()


def employer_of(store: Any, job_id: str) -> str:
    """The employer's display name for a job ("" when unknown)."""
    return _employer_name(store, job_id)


def remember(cfg: Any, store: Any, *, job_id: str, attempt_id: int, answer_id: int,
             value: Any = None, picks: Any = None, only_employer: bool = True,
             etag: str = "") -> dict[str, Any]:
    """Save the owner's answer for next time. Returns `{key, remembered_text, ready_to_retry,
    etag}`; raises `RememberError` (404 not_found, 422 follows_your_details / too_general /
    invalid, 409 shared_answer) or the profile router's 409 `changed` / `unreadable`. Writes
    nothing on any refusal. Starts no application and calls no model."""
    row = store.answer_row(answer_id)
    if row is None or int(row["attempt_id"]) != int(attempt_id) or str(row["job_id"]) != job_id:
        raise RememberError(404, "not_found")
    captured = store.attempt_field_question(attempt_id, row["field_key"])
    refusal = remember_refusal(row, captured=captured)
    label = label_norm_of(row, captured)
    if refusal is not None:
        raise RememberError(422, refusal.value, refusal_text(refusal, str(row.get("label") or "")))
    kind = field_kind(row, captured)
    if kind is None:                                                    # unreachable: files are refused
        raise RememberError(422, RememberRefusal.FOLLOWS_YOUR_DETAILS.value)
    built = build_value(kind, value, picks, option_pairs(row, captured))
    if built.errors:
        raise RememberError(422, "invalid", errors=built.errors)
    employer = _employer_name(store, job_id) if only_employer else ""
    if only_employer and not employer:
        raise RememberError(422, "invalid", errors=[_err(
            "only_employer", "the employer is not known; save it for every application instead")])

    with PROFILE_WRITE_LOCK:
        current = load_for_write(cfg, etag)
        extra = current.get("extra")
        if extra is not None and not isinstance(extra, dict):
            raise RememberError(422, "invalid", errors=[_err("extra", "must be a mapping")])
        state, key = plan_key(extra or {}, label)
        if state == "shared":
            raise RememberError(409, RememberRefusal.SHARED_ANSWER.value,
                                refusal_text(RememberRefusal.SHARED_ANSWER))
        sensitive = bool(row.get("sensitive")) or bool((captured or {}).get("sensitive"))
        entry: dict[str, Any] = {"title": short_title(str(row.get("label") or "")) or key,
                                 "description": "", "kind": kind, "sensitive": sensitive,
                                 "labels": [label], **built.fields}
        if only_employer:
            entry[EXTRA_EMPLOYER_FIELD] = employer
        errors = applicant.extra_entry_errors(key, entry)
        if errors:
            raise RememberError(422, "invalid", errors=errors)
        profile = copy.deepcopy(current)
        profile.setdefault("extra", {})
        if not isinstance(profile["extra"], dict):
            profile["extra"] = {}
        profile["extra"][key] = entry
        try:
            applicant.save(cfg.applicant_path, profile, tolerate_unchanged_extra=current)
        except applicant.ApplicantError as exc:
            raise RememberError(422, "invalid", errors=exc.errors)
        store.mark_answer_corrected(answer_id, json.dumps(built.corrected, ensure_ascii=False), utcnow())
        saved = applicant.load(cfg.applicant_path)
        ready = job_id in ready_to_retry_jobs(store, saved)
        new_etag = applicant.etag(cfg.applicant_path)
    return {"key": key, "remembered_text": built.shown, "ready_to_retry": ready, "etag": new_etag}


# ---- Settings -> Answers you corrected --------------------------------------------------------

def entry_value_text(entry: dict[str, Any]) -> str:
    """The answer of an `extra` entry in words: Yes / No, the chosen options (the normalised
    wording), the text, number or date. "" when it has none."""
    kind = str(entry.get("kind") or "")
    if kind in CHOICE_KINDS:
        return shown(entry.get("picks") or [])
    return shown(entry.get("value"))


def forgettable(entry: Any) -> bool:
    """An entry the list shows and Forget may remove: a saved answer, never a promoted topic."""
    return isinstance(entry, dict) and not entry.get("promoted")
