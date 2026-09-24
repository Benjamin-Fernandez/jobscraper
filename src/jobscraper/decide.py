"""The only step that costs anything: ask a cheap model to judge a posting.

Two halves. `vital_extract` reduces a job description to the few hundred
characters that actually decide the question - location, experience, the top of
the requirements - discarding culture copy and benefits boilerplate. Then one
batched call to the cheapest available model returns accept or reject.

What the model says is not the last word. Location and the experience ceiling are
re-checked in code afterwards, so no amount of model confidence can put a
non-Singapore or over-senior role on the shortlist.

See PRD sections 8.3[4] and 8.3[5].
"""
from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# [4] Vital extract - free, and the single number that decides what a run costs
# ---------------------------------------------------------------------------
#
# The extract is four labelled lines, always in this order, always present:
#
#   LOCATION: <location field verbatim> | <first body line naming a place>
#   EXPERIENCE: <sentences about years, experience, degree, graduate, entry>
#   REQUIREMENTS: <top of the requirements/qualifications section>
#   ROLE: <top of the responsibilities section>
#
# A part that cannot be found is the literal UNSTATED, so the model can tell
# "the posting does not say" apart from "the extractor dropped it".
#
# The budget is shared, and spent in order of what the post-conditions guard
# (PRD 8.3[5]): location first, then experience, then requirements, then role.
# That ordering is what guarantees the location and the years survive even when
# a 12k-character JD is squeezed into 800.

UNSTATED = "UNSTATED"

# Per-part ceilings at the default 800-character budget. They scale with `limit`.
_DEFAULT_LIMIT = 800
_CAP_LOCATION = 160
_CAP_EXPERIENCE = 260
_CAP_REQUIREMENTS = 400        # PRD: "first 400 chars of the requirements section"
_CAP_ROLE = 200                # PRD: "first 200 chars after the responsibilities heading"
_MIN_ROLE = 100                # requirements may not starve the role line below this
_CAP_SENTENCE = 180

# Section headings. Ported from v1 `matching.py::REQ_HEADINGS` and extended
# (PRD 8.3[4] says extend, not duplicate; v1 is retired in M9, so the heuristic
# now lives here). Two tiers each: the first names the hard bar explicitly, the
# second is the softer "about you" family, used only when tier one is absent.
_REQ_STRONG = re.compile(
    r"requirement|qualification|what we require|what you.{0,12}need|"
    r"must[- ]haves?|minimum|basic qualifications|essential", re.I)
_REQ_SOFT = re.compile(
    r"who you are|about you|what you.{0,12}bring|we.{0,6}re looking for|"
    r"what we.{0,6}(?:value|look for)|your (?:profile|background|skills)|"
    r"skills|experience|preferred", re.I)
_ROLE_STRONG = re.compile(
    r"responsibilit|what you.{0,12}(?:do|be doing)|duties|day[- ]to[- ]day|"
    r"your (?:impact|mission)|key (?:tasks|accountabilities)", re.I)
_ROLE_SOFT = re.compile(
    r"the role|your role|about the (?:role|job|position)|the opportunity|"
    r"in this role|role overview|job description", re.I)

# Headings that plainly end a section even though they match nothing above.
_SECTION_STOP = re.compile(
    r"benefit|perks|what we offer|why join|life at|about (?:us|the company)|"
    r"equal opportunit|diversity|compensation|salary|how to apply|"
    r"applicant|privacy", re.I)

_EXPERIENCE_WORDS = re.compile(
    r"\byears?\b|\byrs?\b|experienc|\bdegree\b|\bgraduat|\bentry\b", re.I)
# Same shape as the prefilter's years pattern (PRD 8.3[3]): "5+ years",
# "2-5 years", "3 to 5 yrs". A sentence carrying a number outranks one without.
_YEARS_NUMBER = re.compile(
    r"\d{1,2}\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*)?\+?\s*(?:years?|yrs?)\b",
    re.I)

# Where the job is, strongest evidence first.
_PLACE_TIERS = (
    re.compile(r"\bsingapore\b|\bsg\b", re.I),
    re.compile(r"\blocations?\b|\blocated\b|\bbased (?:in|out of)\b|\brelocat\w*|"
               r"\boffices? in\b", re.I),
    re.compile(r"\bremote\b|\bhybrid\b|\bon-?site\b|\bin-office\b", re.I),
)

_WS = re.compile(r"\s+")
_BULLET = re.compile(r"^[\s\-•*·●▪>]+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
_LABELS = ("LOCATION: ", "\nEXPERIENCE: ", "\nREQUIREMENTS: ", "\nROLE: ")


def vital_extract(title: str, location: str, jd_text: str,
                  limit: int = _DEFAULT_LIMIT) -> str:
    """Reduce a JD to the <= `limit` characters the decision needs.

    `title` is part of the interface (PRD section 0.6, contract 4) but is not
    repeated in the output: the decide prompt carries it per posting already.
    """
    del title
    scale = max(limit, 1) / _DEFAULT_LIMIT
    text = jd_text or ""
    lines = _clean_lines(text)
    sentences = [s for line, _ in lines for s in _split_sentences(line)]
    budget = max(limit - sum(len(lbl) for lbl in _LABELS), 0)

    # 1. Location: the field verbatim, plus the body's own place line.
    field = _norm(location) or UNSTATED
    place = _first_place_sentence(sentences) or UNSTATED
    loc_text = _fit_pair(field, place, min(int(_CAP_LOCATION * scale), budget))
    budget -= len(loc_text)

    # 2. Experience: numbered-years sentences first, then the rest, in order.
    exp_parts = _experience_sentences(sentences)
    exp_text = _filled(exp_parts, min(int(_CAP_EXPERIENCE * scale), budget))
    budget -= len(exp_text)
    shown = _key(exp_text)
    already = {_key(p) for p in exp_parts if _key(p) and _key(p) in shown}

    # 3. Requirements, minus what EXPERIENCE already said; the role keeps a floor.
    role_floor = min(int(_MIN_ROLE * scale), budget)
    req_body = [s for s in _section(lines, text, _REQ_STRONG, _REQ_SOFT)
                if _key(s) not in already]
    req_text = _filled(req_body, min(int(_CAP_REQUIREMENTS * scale),
                                     max(budget - role_floor, 0)))
    budget -= len(req_text)

    # 4. Role: whatever is left, up to its own ceiling.
    role_body = _section(lines, text, _ROLE_STRONG, _ROLE_SOFT)
    role_text = _filled(role_body, min(int(_CAP_ROLE * scale), budget))

    out = "".join(lbl + part for lbl, part in
                  zip(_LABELS, (loc_text, exp_text, req_text, role_text)))
    return out[:limit]          # belt and braces: the budget is a hard contract


# -- helpers -----------------------------------------------------------------

def _norm(text: str) -> str:
    """Collapse all whitespace (including non-breaking spaces) to single spaces."""
    return _WS.sub(" ", text or "").strip()


def _key(text: str) -> str:
    return _norm(text).lower()


def _clean_lines(text: str) -> list[tuple[str, bool]]:
    """Non-empty lines, whitespace-normalised, as (text, was_a_bullet).

    The bullet flag matters: a short bullet ("- Python") looks exactly like a
    heading once its marker is gone, and must not end a section early.
    """
    out = []
    for raw in text.splitlines():
        bullet = _BULLET.match(raw)
        line = _norm(raw[bullet.end():] if bullet else raw)
        if line:
            out.append((line, bool(bullet and bullet.group().strip())))
    return out


def _split_sentences(line: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(line) if s.strip()]


def _clip(text: str, cap: int) -> str:
    """Cut to `cap` characters, at a word boundary where one is near."""
    if cap <= 0:
        return ""
    if len(text) <= cap:
        return text
    if cap <= 3:
        return text[:cap]
    cut = text[:cap - 3]
    space = cut.rfind(" ")
    if space > cap // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:") + "..."


def _window(sentence: str, match: Optional[re.Match], cap: int) -> str:
    """A long sentence, trimmed so the part that matched stays in view."""
    if len(sentence) <= cap or match is None or match.start() < cap // 2:
        return _clip(sentence, cap)
    start = max(0, match.start() - 40)
    space = sentence.rfind(" ", 0, start)
    start = space + 1 if space > 0 else start
    return _clip("..." + sentence[start:], cap)


def _filled(parts: list[str], cap: int) -> str:
    """Whole parts joined while they fit; UNSTATED when there are none."""
    if not parts:
        return _clip(UNSTATED, cap)
    out = ""
    for part in parts:
        candidate = f"{out} {part}" if out else part
        if len(candidate) <= cap:
            out = candidate
        elif not out:
            return _clip(part, cap)
        else:
            break
    return out


def _fit_pair(left: str, right: str, cap: int) -> str:
    """`left | right` in `cap` characters; the verbatim field keeps priority."""
    whole = f"{left} | {right}"
    if len(whole) <= cap:
        return whole
    left = _clip(left, max(cap // 2, cap - len(right) - 3))
    return _clip(f"{left} | {_clip(right, max(cap - len(left) - 3, 0))}", cap)


def _first_place_sentence(sentences: list[str]) -> str:
    for tier in _PLACE_TIERS:
        for s in sentences:
            m = tier.search(s)
            if m:
                return _window(s, m, 120)
    return ""


def _experience_sentences(sentences: list[str]) -> list[str]:
    numbered: list[str] = []
    other: list[str] = []
    seen: set[str] = set()
    for s in sentences:
        hit = _EXPERIENCE_WORDS.search(s)
        if not hit or _key(s) in seen:
            continue
        seen.add(_key(s))
        m = _YEARS_NUMBER.search(s)
        (numbered if m else other).append(_window(s, m or hit, _CAP_SENTENCE))
    return numbered + other


def _looks_like_heading(line: str, bullet: bool = False) -> bool:
    """Short, unpunctuated, not a bullet and not a sentence: a section title."""
    if bullet or len(line) > 60 or len(line.split()) > 8:
        return False
    return not line.endswith((".", ",", ";")) and bool(re.search(r"[A-Za-z]", line))


def _section(lines: list[tuple[str, bool]], raw: str, strong: re.Pattern,
             soft: re.Pattern) -> list[str]:
    """The sentences under the first heading matching `strong` (else `soft`).

    Line-based first, because most JDs keep headings on their own line. If the
    text was flattened to one line, fall back to v1's approach: find the heading
    phrase anywhere and read on from there.
    """
    for pattern in (strong, soft):
        for i, (line, bullet) in enumerate(lines):
            if _looks_like_heading(line, bullet) and pattern.search(line):
                body = _section_body(lines[i + 1:], strong, soft)
                if body:
                    return body
    for pattern in (strong, soft):
        m = pattern.search(raw)
        if m:
            rest = re.sub(r"^\w*\s*:?\s*", "", raw[m.end():], count=1)
            body = _split_sentences(_norm(rest[:_CAP_REQUIREMENTS * 3]))
            if body:
                return body
    return []


def _section_body(lines: list[tuple[str, bool]], strong: re.Pattern,
                  soft: re.Pattern) -> list[str]:
    """Sentences until a heading that belongs to some other section."""
    body: list[str] = []
    for line, bullet in lines:
        if _looks_like_heading(line, bullet):
            if _SECTION_STOP.search(line):
                break
            if strong.search(line) or soft.search(line):
                continue            # "WHO YOU ARE" then "MINIMUM QUALIFICATIONS"
            if body:
                break               # a different section starts
            continue
        body.extend(_split_sentences(line))
    return body
