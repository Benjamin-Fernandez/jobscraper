"""Map JD terms onto the master resume and compute "JD keyword coverage".

Design: docs/architecture/tailor_design.md section 5. Code decides presence;
no model is asked whether the resume "implies" a term (brief 5B).
"""
from __future__ import annotations

import dataclasses
from typing import Iterable

from .contracts import JdTerm, MasterResume, TermStatus, WEIGHT_PREFERRED, WEIGHT_REQUIRED
from .terms import DEFAULT_AMBIGUOUS, Dictionary, find, keys


def resume_text(master: MasterResume) -> str:
    """The master's leaves joined by newlines (contact excluded): summary, every
    entry field, bullets, items (section 5.1)."""
    parts = [master.summary]
    for s in master.sections:
        for e in s.entries:
            parts += [e.title, e.organisation, e.location, e.dates, e.subtitle]
            parts += [b.text for b in e.bullets]
        parts += s.items
    return "\n".join(p for p in parts if p)


def _first_surface(text: str, term: str, ambiguous) -> str:
    spans = find(text, term, ambiguous)
    return text[spans[0][0]:spans[0][1]] if spans else ""


def _is_subrun(small: tuple, big: tuple) -> bool:
    n = len(small)
    return n < len(big) and any(big[i:i + n] == small for i in range(len(big) - n + 1))


def classify(terms: Iterable[JdTerm], master: MasterResume, dictionary: Dictionary,
             attested: Iterable[str] = ()) -> list[JdTerm]:
    """Section 5.1: present_exact, present_variant (alias / instance), missing
    (with `related`), and the attested flag. Returns new JdTerm objects."""
    text = resume_text(master)
    amb = dictionary.ambiguous or DEFAULT_AMBIGUOUS
    att = {keys(a) for a in attested if a}
    strings = dictionary.strings()
    out = []
    for t in terms:
        t = dataclasses.replace(t, status=TermStatus.MISSING, variant="", via="", related="")
        t.attested = keys(t.canonical) in att or keys(t.term) in att
        if find(text, t.term, amb):
            t.status = TermStatus.PRESENT_EXACT
        else:
            entry = dictionary.entry(t.term)
            found = False
            if entry is not None:
                tk = keys(t.term)
                for cand in (entry.canonical, *entry.variants):
                    if keys(cand) == tk:
                        continue
                    surf = _first_surface(text, cand, amb)
                    if surf:
                        t.status, t.variant, t.via = TermStatus.PRESENT_VARIANT, surf, "alias"
                        found = True
                        break
                if not found:
                    for cand in entry.instances:
                        surf = _first_surface(text, cand, amb)
                        if surf:
                            t.status, t.variant, t.via = TermStatus.PRESENT_VARIANT, surf, "instance"
                            found = True
                            break
            if not found:
                tk = keys(t.term)
                for s in strings:
                    if _is_subrun(keys(s), tk):
                        surf = _first_surface(text, s, amb)
                        if surf:
                            t.related = surf
                            break
        out.append(t)
    return out


def coverage(terms: Iterable[JdTerm], text: str, ambiguous=DEFAULT_AMBIGUOUS) -> float:
    """Weighted share of the terms whose JD spelling occurs in `text`
    (required 2, preferred 1); 0 when there are no terms (section 5.2)."""
    total = hit = 0
    for t in terms:
        w = WEIGHT_REQUIRED if t.required else WEIGHT_PREFERRED
        total += w
        if find(text, t.term, ambiguous):
            hit += w
    return hit / total if total else 0.0
