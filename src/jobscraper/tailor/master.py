"""Master resume: parse once per resume hash, check it, cache it.

Design: docs/architecture/tailor_design.md section 3. The one model call in
M20's tailor: it only SPLITS the resume into fields; code assigns every id and a
leaf check proves each field is text that really occurs in the resume (a model
that "fixes" a word is caught and retried once, then refused).

Logged: counts only, never resume text (section 19).
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .contracts import (Bullet, Contact, Entry, MasterResume, Section, SectionKind)

log = logging.getLogger(__name__)

CACHE_VERSION = 1
MAX_TEXT_CHARS = 20000
TIME_FMT = "%Y-%m-%dT%H:%M:%S"


class MasterParseError(RuntimeError):
    """The model's split of the resume is not faithful to the resume."""


SYSTEM_PROMPT = (
    "You split a resume into structured JSON. Copy text EXACTLY as it appears in the resume:\n"
    "same words, same spelling, same capitalisation, same numbers. Do not fix, shorten, merge,\n"
    "reword or translate anything. Leave out bullet symbols (•, -, ▪). If a value is absent, use \"\".\n"
    "Each job, degree, project or role is one entry. Each bullet point is one string in \"bullets\".\n"
    "Skills-like sections (lists of items) go in \"items\", one item per comma- or line-separated value."
)

_S = {"type": "string"}
SCHEMA: dict[str, Any] = {
    "type": "object", "required": ["contact", "summary", "sections"],
    "properties": {
        "contact": {"type": "object", "required": ["name", "email", "phone", "location", "links"],
                    "properties": {"name": _S, "email": _S, "phone": _S, "location": _S,
                                   "links": {"type": "array", "items": _S}}},
        "summary": _S,
        "sections": {"type": "array", "items": {
            "type": "object", "required": ["heading", "kind", "entries", "items"],
            "properties": {
                "heading": _S,
                "kind": {"type": "string", "enum": [k.value for k in SectionKind]},
                "entries": {"type": "array", "items": {
                    "type": "object",
                    "required": ["title", "organisation", "location", "dates", "subtitle", "bullets"],
                    "properties": {"title": _S, "organisation": _S, "location": _S, "dates": _S,
                                   "subtitle": _S, "bullets": {"type": "array", "items": _S}}}},
                "items": {"type": "array", "items": _S}}}},
    },
}

_DASHES = "‐‑‒–—―"
_BULLETS = "•▪◦●‣∙·­"


def norm(s: str) -> str:
    """NFKC, dashes to "-", curly quotes straight, bullet glyphs and soft
    hyphens deleted, whitespace collapsed, casefolded (section 3.3)."""
    s = unicodedata.normalize("NFKC", s)
    for c in _DASHES:
        s = s.replace(c, "-")
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    for c in _BULLETS:
        s = s.replace(c, "")
    return re.sub(r"\s+", " ", s).strip().casefold()


def forms(text: str) -> tuple[str, str]:
    """The text in both forms the leaf check accepts: as is, and with PDF
    line-break hyphenation joined ("infra- structure")."""
    n = norm(text)
    return n, re.sub(r"(\w)- (\w)", r"\1\2", n)


def _leaves(master: MasterResume) -> list[str]:
    c = master.contact
    out = [c.name, c.email, c.phone, c.location, *c.links, master.summary]
    for s in master.sections:
        out.append(s.heading)
        out += s.items
        for e in s.entries:
            out += [e.title, e.organisation, e.location, e.dates, e.subtitle]
            out += [b.text for b in e.bullets]
    return out


def leaf_check(master: MasterResume, text: str) -> list[str]:
    """Leaves (non-empty strings) that do not occur in `text`, as given."""
    a, b = forms(text)
    bad = []
    for leaf in _leaves(master):
        n = norm(leaf)
        if n and n not in a and n not in b:
            bad.append(leaf)
    return bad


# ---------------------------------------------------------------------------
# JSON <-> MasterResume
# ---------------------------------------------------------------------------

def to_dict(master: MasterResume) -> dict[str, Any]:
    return {
        "resume_hash": master.resume_hash, "source_name": master.source_name,
        "contact": {"name": master.contact.name, "email": master.contact.email,
                    "phone": master.contact.phone, "location": master.contact.location,
                    "links": list(master.contact.links)},
        "summary": master.summary, "page_count": master.page_count,
        "parsed_by": master.parsed_by, "parsed_at": master.parsed_at,
        "sections": [{
            "heading": s.heading, "kind": s.kind.value, "items": list(s.items),
            "entries": [{"id": e.id, "title": e.title, "organisation": e.organisation,
                         "location": e.location, "dates": e.dates, "subtitle": e.subtitle,
                         "bullets": [{"id": b.id, "text": b.text} for b in e.bullets]}
                        for e in s.entries]} for s in master.sections],
    }


def from_dict(m: dict[str, Any]) -> MasterResume:
    return MasterResume(
        resume_hash=m.get("resume_hash", ""), source_name=m.get("source_name", ""),
        contact=Contact(**{k: m["contact"].get(k, [] if k == "links" else "")
                           for k in ("name", "email", "phone", "location", "links")}),
        summary=m.get("summary", ""), page_count=int(m.get("page_count", 1)),
        parsed_by=m.get("parsed_by", ""), parsed_at=m.get("parsed_at", ""),
        sections=[Section(
            heading=s["heading"], kind=SectionKind(s["kind"]), items=list(s.get("items", [])),
            entries=[Entry(id=e["id"], title=e.get("title", ""), organisation=e.get("organisation", ""),
                           location=e.get("location", ""), dates=e.get("dates", ""),
                           subtitle=e.get("subtitle", ""),
                           bullets=[Bullet(b["id"], b["text"]) for b in e.get("bullets", [])])
                     for e in s.get("entries", [])]) for s in m.get("sections", [])])


def _s(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _build(data: dict[str, Any]) -> MasterResume:
    """Model JSON -> MasterResume, ids assigned by code in reading order."""
    c = data.get("contact") or {}
    contact = Contact(name=_s(c.get("name")), email=_s(c.get("email")), phone=_s(c.get("phone")),
                      location=_s(c.get("location")),
                      links=[_s(x) for x in (c.get("links") or []) if _s(x)])
    summary = _s(data.get("summary"))
    sections: list[Section] = []
    eid = bid = 0
    for raw in data.get("sections") or []:
        try:
            kind = SectionKind(_s(raw.get("kind")))
        except ValueError:
            kind = SectionKind.OTHER
        items = [_s(x) for x in (raw.get("items") or []) if _s(x)]
        entries = []
        for re_ in raw.get("entries") or []:
            eid += 1
            bullets = []
            for t in re_.get("bullets") or []:
                if _s(t):
                    bid += 1
                    bullets.append(Bullet(bid, _s(t)))
            entries.append(Entry(id=f"e{eid}", title=_s(re_.get("title")),
                                 organisation=_s(re_.get("organisation")),
                                 location=_s(re_.get("location")), dates=_s(re_.get("dates")),
                                 subtitle=_s(re_.get("subtitle")), bullets=bullets))
        if kind is SectionKind.SUMMARY:
            if not summary:
                summary = " ".join(items + [b.text for e in entries for b in e.bullets])
            continue
        sections.append(Section(heading=_s(raw.get("heading")), kind=kind,
                                entries=entries, items=items))
    return MasterResume(resume_hash="", source_name="", contact=contact, summary=summary,
                        sections=sections)


def _complete(backend, system: str, user: str, max_tokens: int):
    """Ask for JSON under the schema. P1 (backend per-call options) names the
    parameter `format`; until it lands the transport calls it `schema`."""
    params = inspect.signature(backend.complete).parameters
    kw = {"format": SCHEMA} if "format" in params else {"schema": SCHEMA}
    if "temperature" in params:
        kw["temperature"] = 0
    return backend.complete(system, user, max_tokens, **kw)


def parse(text: str, backend, *, resume_hash: str = "", source_name: str = "",
          page_count: int = 1) -> MasterResume:
    """One model call (a second only after a failed leaf check). Raises
    MasterParseError when the split is unreadable or still not faithful."""
    text = text[:MAX_TEXT_CHARS]
    user = f"RESUME TEXT:\n{text}"
    for attempt in (1, 2):
        comp = _complete(backend, SYSTEM_PROMPT, user, 6000)
        try:
            data = json.loads(comp.text)
            master = _build(data)
        except (ValueError, TypeError, AttributeError) as exc:
            raise MasterParseError(f"master parse: unreadable model output ({type(exc).__name__})")
        bad = leaf_check(master, text)
        if not bad:
            master.resume_hash, master.source_name = resume_hash, source_name
            master.page_count = page_count
            master.parsed_by = getattr(backend, "model_id", "") or getattr(backend, "name", "")
            master.parsed_at = datetime.now(timezone.utc).strftime(TIME_FMT)
            ents = sum(len(s.entries) for s in master.sections)
            log.info("master parse: %d sections, %d entries, %d bullets",
                     len(master.sections), ents, sum(1 for _ in master.bullets()))
            return master
        log.warning("leaf check failed on %d strings", len(bad))
        if attempt == 1:
            user += ("\n\nTHESE STRINGS ARE NOT IN THE RESUME, COPY EXACTLY: "
                     + " | ".join(b[:80] for b in bad[:10]))
    raise MasterParseError(f"master parse: leaf check failed on {len(bad)} strings")


def load(path: str | Path, resume_hash: str, text: str) -> Optional[MasterResume]:
    """The cached master when its hash matches and the leaf check still passes
    against the current text (a hand edit is allowed but checked); else None."""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("version") != CACHE_VERSION or data.get("resume_hash") != resume_hash:
            return None
        master = from_dict(data["master"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return None if leaf_check(master, text) else master


def save(path: str | Path, master: MasterResume) -> None:
    """Atomic write of the cache file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = {"version": CACHE_VERSION, "resume_hash": master.resume_hash,
            "source_name": master.source_name, "page_count": master.page_count,
            "parsed_by": master.parsed_by, "parsed_at": master.parsed_at,
            "master": to_dict(master)}
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(body, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def page_count(path: str | Path, word_pages: Optional[Callable[[Path], Optional[int]]] = None) -> int:
    """PDF: its page count. DOCX: Word's count through the injected
    `word_pages` (render.docx_pages), else 1 when Word is unavailable."""
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return max(1, len(PdfReader(str(p)).pages))
    if word_pages is not None:
        try:
            n = word_pages(p)
        except Exception:
            n = None
        if n:
            return int(n)
    return 1
