"""Validator: the bullet check and the resume-wide invariants.

Design: docs/architecture/tailor_design.md section 8.1 and 8.3. Everything here
is deterministic code. In M20 the only rewriter is the deterministic swap, so
`bullet()` guards the swap output (it passes by construction; this catches
bugs). The M22 additions (verb upgrades, direction flips, number words, the
summary check) are NOT here: D-67 moved them with the LLM rewrite.

A violation of the invariants is a failure, never a silent fix.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Optional

from .contracts import IssueCode, MasterResume, SectionKind, ValidationIssue
from .terms import Dictionary, keys, tokens

_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)*(?:%|[kKmMbB]|x)?(?![A-Za-z0-9])")
_NUMBER_TOKEN = re.compile(r"^\d[\d.,]*(?:[kKmMbB]|x)?$")
_STOP_FACTS = frozenset(
    "i january february march april may june july august september october november december "
    "monday tuesday wednesday thursday friday saturday sunday".split())
_SENT_START = re.compile(r"[.!?]\s+$")


@dataclass
class BulletContext:
    dictionary: Dictionary
    allowed_terms: tuple = ()      # M22: terms the entry already supports


def _mask(text: str, dictionary: Dictionary):
    """(hits, text with each dictionary-hit span blanked)."""
    hits = dictionary.hits(text)
    chars = list(text)
    for h in hits:
        for i in range(h.start, h.end):
            chars[i] = " "
    return hits, "".join(chars)


def numbers(text: str, dictionary: Dictionary) -> Counter:
    """Multiset of standalone numeric tokens outside every dictionary-hit span
    (D-69): "k8s", "S3", "p95" yield nothing; "S$1.2M" yields "1.2M"."""
    _hits, masked = _mask(text, dictionary)
    out = Counter()
    for m in _NUMBER.finditer(masked):
        tok = m.group()
        if re.fullmatch(r"\d{1,3}(,\d{3})+", tok):
            tok = tok.replace(",", "")
        out[tok] += 1
    return out


def facts(text: str, dictionary: Dictionary) -> set[str]:
    """Fact tokens: dictionary canonicals (lowercased, so Postgres = PostgreSQL),
    plus, outside dictionary spans, acronyms, capitalised words not at a
    sentence start, and letter+digit tokens ("p95"). Numbers are not facts."""
    hits, masked = _mask(text, dictionary)
    out = {h.canonical.lower() for h in hits}
    for start, _end, tok in tokens(masked):
        if _NUMBER_TOKEN.match(tok):
            continue
        letters = [c for c in tok if c.isalpha()]
        low = tok.lower()
        if low in _STOP_FACTS or not letters:
            continue
        if tok[0].isdigit():
            continue
        has_digit = any(c.isdigit() for c in tok)
        if has_digit:
            out.add(low)
        elif len(tok) >= 2 and not any(c.islower() for c in letters):
            out.add(low)                                       # acronym
        elif tok[0].isupper() and len(letters) >= 2:
            before = masked[:start]
            if before.strip() and not _SENT_START.search(before):
                out.add(low)                                   # capitalised, mid-sentence
    return out


def bullet(src: str, out: str, ctx: BulletContext) -> list[ValidationIssue]:
    """Section 8.1: empty, numbers, facts, length. `detail` is the offending
    token(s), never a whole bullet."""
    if not out.strip():
        return [ValidationIssue(IssueCode.EMPTY)]
    d = ctx.dictionary
    issues: list[ValidationIssue] = []
    ns, no = numbers(src, d), numbers(out, d)
    for tok in sorted((no - ns).elements()):
        issues.append(ValidationIssue(IssueCode.NUMBER_ADDED, detail=tok))
    for tok in sorted((ns - no).elements()):
        issues.append(ValidationIssue(IssueCode.NUMBER_DROPPED, detail=tok))
    fs, fo = facts(src, d), facts(out, d)
    for tok in sorted(fo - fs):
        issues.append(ValidationIssue(IssueCode.FACT_ADDED, detail=tok))
    for tok in sorted(fs - fo):
        issues.append(ValidationIssue(IssueCode.FACT_DROPPED, detail=tok))
    if not (0.6 * len(src) <= len(out) <= 1.4 * len(src)):
        issues.append(ValidationIssue(IssueCode.LENGTH, detail=f"{len(src)} -> {len(out)} chars"))
    return issues


def entry_ids(input_ids: Iterable[int], output_ids: Iterable[int]) -> list[ValidationIssue]:
    """Entry-level id check (model output, M22): each input id exactly once."""
    inp, outl = list(input_ids), list(output_ids)
    issues = []
    cnt = Counter(outl)
    for i in inp:
        if cnt[i] == 0:
            issues.append(ValidationIssue(IssueCode.ID_MISSING, i))
    for i in sorted(cnt):
        if i not in inp:
            issues.append(ValidationIssue(IssueCode.ID_UNKNOWN, i))
        elif cnt[i] > 1:
            issues.append(ValidationIssue(IssueCode.ID_DUPLICATE, i))
    return issues


def invariants(master: MasterResume, document: MasterResume, attested: Iterable[str] = (),
               swapped: Optional[MasterResume] = None) -> list[str]:
    """Section 8.3: violations (empty = ok). Protected fields, headings, entry
    ids and order byte-equal; bullets never leave their entry; contact
    byte-equal; skills items only from the master's items (after swaps, when
    `swapped` is given) or attested terms; with `swapped`, every kept bullet is
    exactly its post-swap text."""
    v: list[str] = []
    if document.contact != master.contact:
        v.append("contact changed")
    if [s.heading for s in document.sections] != [s.heading for s in master.sections]:
        v.append("section headings or order changed")
        return v
    for sm, sd in zip(master.sections, document.sections):
        if sm.kind != sd.kind:
            v.append(f"section kind changed in {sm.heading}")
        if [e.id for e in sm.entries] != [e.id for e in sd.entries]:
            v.append(f"entries changed in {sm.heading}")
            continue
        for em, ed in zip(sm.entries, sd.entries):
            for f in ("title", "organisation", "location", "dates", "subtitle"):
                if getattr(em, f) != getattr(ed, f):
                    v.append(f"{f} of {em.id} changed")
            mine = {b.id for b in em.bullets}
            seen = [b.id for b in ed.bullets]
            if not set(seen) <= mine:
                v.append(f"bullet moved into {em.id}")
            if len(seen) != len(set(seen)):
                v.append(f"duplicate bullet in {em.id}")
        if sm.kind is not SectionKind.SKILLS and sm.items != sd.items:
            v.append(f"items changed in {sm.heading}")
    if swapped is not None:
        after = {b.id: b.text for _e, b in swapped.bullets()}
        for _e, b in document.bullets():
            if after.get(b.id) != b.text:
                v.append(f"bullet {b.id} is not its post-swap text")
        if document.summary != swapped.summary:
            v.append("summary is not its post-swap text")
    if swapped is not None:
        # Without the post-swap document the swapped spellings cannot be judged.
        base = {keys(i) for i in swapped.skills()} | {keys(a) for a in attested}
        extra = [i for i in document.skills() if keys(i) not in base]
        if extra:
            v.append(f"{len(extra)} skills item(s) not from the master or attested")
    return v
