"""Deterministic rewrite: variant swaps, skills order, bullet relevance order.

Design: docs/architecture/tailor_design.md section 6.2 (swaps) and 6.3 (order,
headline). There is no model here: the LLM rewrite is the M22 layer (D-67) and
`tailor.llm` is off. Truthfulness by construction: a swap only ever replaces a
resume string with a TRUE SYNONYM from aliases.yaml (or appends a curated
"instance of" claim), and protected fields (titles, employers, dates,
locations, subtitles, headings, contact) are never touched.
"""
from __future__ import annotations

import copy
import re
from typing import Iterable, Optional

from .contracts import (Bullet, BulletChange, JdTerm, MasterResume, SectionKind,
                        TermStatus, WEIGHT_PREFERRED, WEIGHT_REQUIRED)
from .terms import DEFAULT_AMBIGUOUS, Dictionary, find, keys

_ARTICLE = re.compile(r"(?:^|(?<=\s))(a|an|A|An)(\s+)$")
_AN_LETTERS = set("AEFHILMNORSX")


def _is_acronym(s: str) -> bool:
    return 2 <= len(s) <= 5 and not any(c.islower() for c in s) and any(c.isalpha() for c in s)


def _article(new: str, old: str) -> str:
    first = new[:1]
    if _is_acronym(new.split()[0] if new.split() else new):
        an = first in _AN_LETTERS
    else:
        an = first.lower() in "aeiou"
    word = "an" if an else "a"
    return word.capitalize() if old[:1].isupper() else word


class _Swapper:
    """Applies the swap terms to texts in document order, remembering which
    acronym expansions and instance annotations have been used."""

    def __init__(self, terms: list[JdTerm], dictionary: Dictionary):
        self.terms = terms
        self.amb = dictionary.ambiguous or DEFAULT_AMBIGUOUS
        self.expanded: set[str] = set()      # canonical of terms whose first use is done
        self.used: dict[str, list[str]] = {}  # bookkeeping per call

    def text(self, text: str) -> tuple[str, list[str]]:
        used: list[str] = []
        for t in self.terms:
            new, did = self._one(text, t)
            if did:
                used.append(t.term)
                text = new
        return text, used

    def _one(self, text: str, t: JdTerm) -> tuple[str, bool]:
        if t.via == "instance":
            if t.canonical in self.expanded:
                return text, False
            spans = find(text, t.variant, self.amb)
            if not spans:
                return text, False
            _s, e = spans[0]
            self.expanded.add(t.canonical)
            return text[:e] + f" ({t.term})" + text[e:], True
        spans = find(text, t.variant, self.amb)
        if not spans:
            return text, False
        acronym_dir = _is_acronym(t.term) and not _is_acronym(t.variant)
        edits = []
        for s, e in spans:
            surface = text[s:e]
            new = t.term
            if acronym_dir and t.canonical not in self.expanded:
                new = f"{surface} ({t.term})"
                self.expanded.add(t.canonical)
            edits.append((s, e, new))
        for s, e, new in reversed(edits):
            head = text[:s]
            m = _ARTICLE.search(head)
            if m:
                art = _article(new, m.group(1))
                head = head[:m.start(1)] + art + m.group(2)
            text = head + new + text[e:]
        return text, True


def _swap_terms(terms: Iterable[JdTerm]) -> list[JdTerm]:
    return [t for t in terms if t.status is TermStatus.PRESENT_VARIANT
            and t.via in ("alias", "acronym", "instance") and t.variant]


def swap(master: MasterResume, terms: Iterable[JdTerm],
         dictionary: Dictionary) -> tuple[MasterResume, list[BulletChange]]:
    """Section 6.2. Returns a new document (the master is not mutated) and one
    BulletChange(source="swap") per changed bullet."""
    doc = copy.deepcopy(master)
    sw = _swap_terms(terms)
    changes: list[BulletChange] = []
    if not sw:
        return doc, changes
    swapper = _Swapper(sw, dictionary)
    if doc.summary:
        doc.summary, _ = swapper.text(doc.summary)
    for sec in doc.sections:
        for entry in sec.entries:
            fresh = []
            for b in entry.bullets:
                new, used = swapper.text(b.text)
                if new != b.text:
                    changes.append(BulletChange(b.id, entry.id, b.text, new, "swap",
                                                keywords_used=used))
                    b = Bullet(b.id, new)
                fresh.append(b)
            entry.bullets = fresh
        if sec.kind is SectionKind.SKILLS and sec.items:
            sec.items = _swap_items(sec.items, sw)
    return doc, changes


def _swap_items(items: list[str], sw: list[JdTerm]) -> list[str]:
    out, seen = [], set()
    for item in items:
        for t in sw:
            if t.via != "instance" and keys(item) == keys(t.variant):
                item = t.term
                break
        k = keys(item)
        if k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# 6.3 order
# ---------------------------------------------------------------------------

def bullet_scores(master: MasterResume, terms: Iterable[JdTerm],
                  ambiguous=DEFAULT_AMBIGUOUS) -> dict[int, int]:
    """Relevance of each bullet: sum of weights of the distinct JD terms whose
    JD spelling occurs in it (each term once per bullet)."""
    terms = list(terms)
    out = {}
    for _e, b in master.bullets():
        out[b.id] = sum(WEIGHT_REQUIRED if t.required else WEIGHT_PREFERRED
                        for t in terms if find(b.text, t.term, ambiguous))
    return out


def order_skills(items: list[str], terms: Iterable[JdTerm],
                 attested: Iterable[str] = (), ambiguous=DEFAULT_AMBIGUOUS,
                 add_attested: bool = True) -> list[str]:
    """Required terms present (JD order), then preferred, then the rest in
    master order; then attested JD terms that are missing, in JD spelling."""
    terms = list(terms)
    placed: list[int] = []
    for group in ([t for t in terms if t.required], [t for t in terms if not t.required]):
        for t in group:
            for i, item in enumerate(items):
                if i not in placed and find(item, t.term, ambiguous):
                    placed.append(i)
    out = [items[i] for i in placed] + [it for i, it in enumerate(items) if i not in placed]
    if add_attested:
        att = {keys(a) for a in attested if a}
        have = {keys(i) for i in out}
        for t in terms:
            if (t.attested or keys(t.canonical) in att or keys(t.term) in att) \
                    and t.status is TermStatus.MISSING and keys(t.term) not in have:
                out.append(t.term)
                have.add(keys(t.term))
    return out


def reorder(master: MasterResume, terms: Iterable[JdTerm], attested: Iterable[str] = (),
            ambiguous=DEFAULT_AMBIGUOUS) -> MasterResume:
    """Bullets by descending relevance within each entry (stable: ties keep
    master order), skills list per `order_skills`. A new document."""
    terms = list(terms)
    doc = copy.deepcopy(master)
    scores = bullet_scores(doc, terms, ambiguous)
    for sec in doc.sections:
        for e in sec.entries:
            if len(e.bullets) > 1:
                pos = {b.id: i for i, b in enumerate(e.bullets)}
                e.bullets.sort(key=lambda b: (-scores[b.id], pos[b.id]))
    skills = [s for s in doc.sections if s.kind is SectionKind.SKILLS]
    for n, sec in enumerate(skills):
        sec.items = order_skills(sec.items, terms, attested, ambiguous, add_attested=(n == 0))
    return doc


def headline(job_title: str, enabled: bool) -> str:
    """D-60: the job title verbatim, as a line under the name."""
    return (job_title or "").strip() if enabled else ""


def change_log(master: MasterResume, swaps: Iterable[BulletChange], final: MasterResume,
               trimmed: Iterable[BulletChange] = ()) -> list[BulletChange]:
    """Every kept bullet in output order (unchanged ones included, so the
    relevance order is visible), then the trimmed ones."""
    by_id = {c.bullet_id: c for c in swaps}
    before = {b.id: b.text for _e, b in master.bullets()}
    out = []
    for e, b in final.bullets():
        c = by_id.get(b.id)
        out.append(c if c else BulletChange(b.id, e.id, before[b.id], b.text, "unchanged"))
    return out + list(trimmed)
