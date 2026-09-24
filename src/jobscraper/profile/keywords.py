"""Keyword overlap: how many of the candidate's skills a posting mentions.

Why it exists. The prefilter's last free rule (PRD 8.3[3], `min_overlap`) drops
postings that share almost no vocabulary with the resume, before any model sees
them. It has to be cheap, and it has to be *explainable*: the UI and
`filter explain` show which skills matched, so a user who disagrees with a
rejection can see exactly why and fix it in `profile.overrides.yaml`.

Why not BM25 or embeddings. Both give a number nobody can argue with. This gives
a list of matched skills, and a score that is just their weighted count.

The rules, all of them:
  - Text and skills are tokenised the same way: lowercase, split on anything
    but letters, digits, `+`, `#` and inner dots - so "c++", "c#", "node.js"
    and ".net" survive as tokens, and "ci/cd" becomes "ci" "cd".
  - Tokens are folded: a trailing plural "s" is dropped ("apis" = "api"),
    ".js" names lose the dot ("node.js" = "nodejs"), and a few ubiquitous
    variants map to one name (k8s, postgres, golang - see `_ALIASES`).
  - A skill matches when its tokens appear consecutively in the text. Whole
    tokens only: "java" never matches "javascript".
  - Each skill counts once, however often it appears. A multi-word skill
    ("spring boot") counts 2 - two words in a row is much stronger evidence
    than one - and a single-word skill counts 1.
  - "go", "c" and "r" are also ordinary English. They match only when
    capitalised in the text ("Go", "C") or spelled out ("golang").

`overlap` is contract 2 of PRD 0.6. filter.py never imports this module; the
pipeline hands it the function (stages do not import each other, 8.2).
"""
from __future__ import annotations

import re

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#]*(?:\.[A-Za-z0-9+#]+)*")

_ALIASES = {
    "k8s": "kubernetes",
    "postgres": "postgresql",
    "golang": "go",
    "reactjs": "react",
    "vuejs": "vue",
}

# Skills that are also everyday words. Lowercase in running text, they are
# almost always the word ("go-to-market", "go above and beyond").
_AMBIGUOUS = {"go", "c", "r"}

MULTIWORD_WEIGHT = 2
SINGLE_WEIGHT = 1


def _canon(token: str) -> str:
    t = token.lower()
    if t.endswith(".js"):
        t = t[:-3] + "js"
    t = _ALIASES.get(t, t)
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        t = t[:-1]
    return t


def _skill_tokens(skill: str) -> tuple[str, ...]:
    return tuple(_canon(m.group()) for m in _TOKEN.finditer(skill or ""))


def _text_ngrams(text: str, max_n: int) -> set[tuple[str, ...]]:
    """Every run of 1..max_n consecutive tokens. An ambiguous word written in
    lowercase breaks the run rather than joining it."""
    runs: list[list[str]] = [[]]
    for m in _TOKEN.finditer(text or ""):
        raw = m.group()
        if raw in _AMBIGUOUS:        # lowercase "go" / "c" / "r": the word
            runs.append([])
            continue
        runs[-1].append(_canon(raw))
    grams: set[tuple[str, ...]] = set()
    for run in runs:
        for n in range(1, max_n + 1):
            for i in range(len(run) - n + 1):
                grams.add(tuple(run[i:i + n]))
    return grams


def overlap(text: str, skills: list[str]) -> tuple[int, list[str]]:
    """Score `text` against `skills`: (weighted count, matched skills).

    Matched skills come back as given, in the order of `skills`.
    """
    wanted: list[tuple[str, tuple[str, ...]]] = []
    seen: set[tuple[str, ...]] = set()
    for skill in skills or []:
        toks = _skill_tokens(skill)
        if toks and toks not in seen:
            seen.add(toks)
            wanted.append((skill, toks))
    if not wanted or not text:
        return 0, []

    grams = _text_ngrams(text, max(len(t) for _s, t in wanted))
    score, matched = 0, []
    for skill, toks in wanted:
        if toks in grams:
            matched.append(skill)
            score += MULTIWORD_WEIGHT if len(skill.split()) > 1 else SINGLE_WEIGHT
    return score, matched
