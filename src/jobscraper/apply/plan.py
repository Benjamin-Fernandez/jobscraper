"""Form plans and label normalisation (apply_design §6, §7.1).

Every rule that reads a question's wording - the tier-2 synonym table, the
declaration classifier, option mapping - first puts the text through
`norm_label`, and compares phrases with `phrase_match`. Keeping both here, in
one place, is what makes "the same label" mean the same thing to every tier.

HTML is stripped with the standard library's `html.parser`: stages do not
import each other, so `scrape/`'s helpers are out of reach (WP-P4).
"""
from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser
from typing import Iterable, Sequence

from .contracts import GENERIC_LABELS

# Curly quotes and look-alikes that mean an apostrophe (§7.1 step 2).
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'"})
_NOISE = ("(required)", "(optional)", "*")
_NOT_TOKEN = re.compile(r"[^a-z0-9+#']+")
_LEADING_NUMBER = re.compile(r"^\d+ ")
# Tags that separate words; inline ones (<b>, <span>) join the text around them.
_BLOCK_TAGS = frozenset({"br", "p", "div", "li", "ul", "ol", "tr", "td", "th",
                         "h1", "h2", "h3", "h4", "h5", "h6"})


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag, attrs) -> None:
        if tag in _BLOCK_TAGS:                          # <br>, <p>: a word break
            self.parts.append(" ")

    def handle_endtag(self, tag) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append(" ")


def html_to_text(text: str) -> str:
    """Tags out, entities decoded. Plain text passes through unchanged."""
    if "<" not in text and "&" not in text:
        return text
    p = _Text()
    p.feed(text)
    p.close()
    return "".join(p.parts)


def _clean_token(tok: str) -> str:
    """Keep an apostrophe inside a word ("don't", D-69); drop a trailing "'s"
    ("company's" -> "company") and any apostrophe at the token's ends."""
    if tok.endswith("'s"):
        tok = tok[:-2]
    return tok.strip("'")


def norm_label(label: str) -> str:
    """apply_design §7.1, steps 1-6:

    1 tags stripped, NFKC, lowercase   2 curly apostrophes -> '
    3 "(required)", "(optional)", "*" deleted
    4 every run of characters outside [a-z0-9+#'] -> one space; "'" kept inside
      a word, dropped at a token's ends, trailing "'s" dropped
    5 a leading list number dropped ("1 ", "12 ")   6 spaces collapsed
    """
    text = unicodedata.normalize("NFKC", html_to_text(label or "")).lower()
    text = text.translate(_APOSTROPHES)
    for noise in _NOISE:
        text = text.replace(noise, " ")
    tokens = [_clean_token(t) for t in _NOT_TOKEN.sub(" ", text).split()]
    text = " ".join(t for t in tokens if t)
    text = _LEADING_NUMBER.sub("", text)
    return " ".join(text.split())


def tokens(text: str) -> list[str]:
    """`norm_label(text)` split into tokens."""
    return norm_label(text).split()


def contains_run(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    """True if `needle` occurs as a contiguous run in `haystack`."""
    n = len(needle)
    if n == 0 or n > len(haystack):
        return False
    first = needle[0]
    for i in range(len(haystack) - n + 1):
        if haystack[i] == first and list(haystack[i:i + n]) == list(needle):
            return True
    return False


def phrase_match_tokens(phrase: Sequence[str], label: Sequence[str]) -> bool:
    """`phrase_match` on already-normalised token lists. A one-token phrase
    matches only a label of 4 tokens or fewer (so "email" does not match
    "may we email you about other roles")."""
    if len(phrase) == 1 and len(label) > 4:
        return False
    return contains_run(label, phrase)


def phrase_match(phrase: str, label: str) -> bool:
    """§7.1: `norm_label(phrase)` occurs as a contiguous token run in
    `norm_label(label)`, with the one-token rule above."""
    return phrase_match_tokens(tokens(phrase), tokens(label))


def any_phrase(phrases: Iterable[str], label: str) -> bool:
    """True if any of `phrases` phrase-matches `label`."""
    lt = tokens(label)
    return any(phrase_match_tokens(tokens(p), lt) for p in phrases)


# --------------------------------------------------------------------------
# Generic labels (review Q-30 F1, llm_fill_design §12.1)
# --------------------------------------------------------------------------

# questions_design §5.2: words that carry no meaning of their own in a label. Kept here
# (questions.py re-exports it) so `is_generic` needs no import of a module that imports this one.
STOP_WORDS = frozenset("a an the of in on for to and or your you are is do does have has what "
                       "which please select enter provide".split())


def content_tokens(text: str) -> list[str]:
    """`tokens(text)` minus the §5.2 stop words, in order."""
    return [t for t in tokens(text) if t not in STOP_WORDS]


def is_generic(label_norm: str) -> bool:
    """F1: a label that cannot identify a question alone ("Please specify",
    "Details", a one-word label): in GENERIC_LABELS, or fewer than 2 content
    tokens after the stop words. Such a label is matched and captured with its
    context, never by the label alone."""
    norm = norm_label(label_norm)
    if norm in GENERIC_LABELS:
        return True
    return len([t for t in norm.split() if t not in STOP_WORDS]) < 2


def qualified_label(label: str, description: str = "", context: str = "", *,
                    step: str = "", ordinal: int = 0) -> str:
    """F1 (§12.1): the label a question is matched, captured and saved under.

    Generic: `norm(label) | norm(description or context)`; with neither (review
    M1), `norm(label) | @<step>#<ordinal>` (ordinal = the field's position among
    the step's generic fields), so a context-less "Please specify" still means
    one place on one form. Non-generic: `norm(label)`."""
    norm = norm_label(label)
    if not is_generic(norm):
        return norm
    qual = norm_label(description or "") or norm_label(context or "")
    if qual:
        return f"{norm} | {qual}"
    return f"{norm} | @{step}#{int(ordinal)}"
