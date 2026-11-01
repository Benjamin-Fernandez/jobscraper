"""Matcher, alias loader, dictionary and deterministic JD-term extraction.

Design: docs/architecture/tailor_design.md section 4 (matcher, dictionary,
extraction) and section 6.1 (aliases.yaml loader). Independent of
`profile/keywords.py`, which folds variants together on purpose: here a term
matches only the spelling it is asked for, so "coverage" means "the JD's own
word is on the resume".

Nothing here reads a resume or calls a model. HTML-to-text is injected by the
orchestrator (`html_to_text` is never imported from `scrape/`).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Optional

import yaml

from .contracts import JdTerm

KINDS = frozenset({"tool", "language", "framework", "platform", "practice", "domain", "soft"})
DEFAULT_AMBIGUOUS = frozenset({"go", "c", "r"})
MAX_JD_CHARS = 12000


class AliasError(ValueError):
    """aliases.yaml is malformed, or a string is claimed by two entries."""


# ---------------------------------------------------------------------------
# 4.1 Matcher
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#]*(?:\.[A-Za-z0-9+#]+)*")
# Between two tokens of one term only whitespace, or one separator with optional
# blanks around it ("CI/CD", "machine-learning"), may sit. Without this, "Spring.
# Boot" or a list break would read as "Spring Boot".
_GAP = re.compile(r"^(?:\s+|[ \t]*[/\-–][ \t]*)$")


def token_key(token: str) -> str:
    """Lowercase; ".js" folds to "js"; a trailing s is dropped on tokens longer
    than 3 chars that do not end "ss" ("APIs" = "API"). No alias folding."""
    k = token.lower().replace(".js", "js")
    if len(k) > 3 and k.endswith("s") and not k.endswith("ss"):
        k = k[:-1]
    return k


def tokens(text: str) -> list[tuple[int, int, str]]:
    """(start, end, token) for every token of `text`."""
    return [(m.start(), m.end(), m.group()) for m in _TOKEN.finditer(text)]


def keys(text: str) -> tuple[str, ...]:
    return tuple(token_key(m.group()) for m in _TOKEN.finditer(text))


@lru_cache(maxsize=128)
def _scan(text: str, ambiguous: frozenset) -> tuple:
    """Text tokens as (start, end, key); a lowercase ambiguous token ("go" in
    "go-live") gets a key no term can have, so it also breaks runs."""
    out = []
    for m in _TOKEN.finditer(text):
        tok = m.group()
        k = token_key(tok)
        if k in ambiguous and tok == tok.lower():
            k = "\x00" + k
        out.append((m.start(), m.end(), k))
    return tuple(out)


def _match_at(text: str, toks: tuple, i: int, kt: tuple[str, ...]) -> Optional[int]:
    """Index of the last token if `kt` matches the run starting at token i."""
    n = len(kt)
    if i + n > len(toks):
        return None
    for j in range(n):
        if toks[i + j][2] != kt[j]:
            return None
        if j and not _GAP.match(text[toks[i + j - 1][1]:toks[i + j][0]]):
            return None
    return i + n - 1


def find(text: str, term: str, ambiguous: Iterable[str] = DEFAULT_AMBIGUOUS) -> list[tuple[int, int]]:
    """Character spans (first token start, last token end) of `term` in `text`.
    The surface is `text[start:end]`."""
    kt = keys(term)
    if not kt:
        return []
    toks = _scan(text, frozenset(ambiguous))
    spans = []
    for i in range(len(toks)):
        last = _match_at(text, toks, i, kt)
        if last is not None:
            spans.append((toks[i][0], toks[last][1]))
    return spans


# ---------------------------------------------------------------------------
# 6.1 aliases.yaml loader
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AliasEntry:
    canonical: str
    variants: tuple[str, ...] = ()
    instances: tuple[str, ...] = ()
    kind: str = ""

    def strings(self) -> tuple[str, ...]:
        return (self.canonical, *self.variants, *self.instances)


@dataclass(frozen=True)
class Aliases:
    entries: tuple[AliasEntry, ...]
    ambiguous: frozenset
    hash: str = ""

    @classmethod
    def load(cls, path: str | Path) -> "Aliases":
        raw = Path(path).read_bytes()
        try:
            data = yaml.safe_load(raw.decode("utf-8")) or {}
        except yaml.YAMLError as exc:
            raise AliasError(f"{Path(path).name}: not valid YAML ({type(exc).__name__})") from exc
        if not isinstance(data, dict) or not isinstance(data.get("terms"), list):
            raise AliasError(f"{Path(path).name}: needs a 'terms' list")
        seen_str: dict[str, str] = {}
        seen_key: dict[tuple, str] = {}
        entries = []
        for i, t in enumerate(data["terms"]):
            if not isinstance(t, dict) or not str(t.get("canonical", "")).strip():
                raise AliasError(f"terms[{i}]: canonical is required")
            canon = str(t["canonical"]).strip()
            kind = str(t.get("kind", "")).strip()
            if kind and kind not in KINDS:
                raise AliasError(f"{canon}: kind {kind!r} is not one of {sorted(KINDS)}")
            variants = tuple(str(v).strip() for v in (t.get("variants") or []))
            instances = tuple(str(v).strip() for v in (t.get("instances") or []))
            e = AliasEntry(canon, variants, instances, kind)
            for s in e.strings():
                low = s.lower()
                if low in seen_str:
                    raise AliasError(f"{s!r} is in two entries: {seen_str[low]!r} and {canon!r}")
                seen_str[low] = canon
            ck = keys(canon)
            if ck in seen_key:
                raise AliasError(f"canonicals {seen_key[ck]!r} and {canon!r} are the same token key")
            seen_key[ck] = canon
            entries.append(e)
        amb = frozenset(str(x).lower() for x in (data.get("ambiguous") or DEFAULT_AMBIGUOUS))
        return cls(tuple(entries), amb, hashlib.sha256(raw).hexdigest())


def aliases_hash(path: str | Path) -> str:
    """SHA-256 of the file bytes: part of the tailor inputs hash (section 11.2)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 4.2 Dictionary
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Hit:
    start: int
    end: int
    canonical: str          # alias canonical, else the string lowercased
    string: str             # the dictionary string that matched


class Dictionary:
    """Every aliases.yaml canonical, variant and instance, plus extra strings
    (the applicant's skills, attested skills, the master's skills items)."""

    def __init__(self, aliases: Aliases, extra: Iterable[str] = ()):
        self.aliases = aliases
        self.ambiguous = aliases.ambiguous
        self._by_key: dict[tuple, tuple[str, str, Optional[AliasEntry]]] = {}
        self._entry_of: dict[str, AliasEntry] = {}
        for e in aliases.entries:
            for s in e.strings():
                self._by_key.setdefault(keys(s), (s, e.canonical, e))
                self._entry_of[s.lower()] = e
        for s in extra:
            s = str(s).strip()
            kt = keys(s)
            if kt and kt not in self._by_key:
                self._by_key[kt] = (s, s.lower(), None)
        self._first: dict[str, list[tuple]] = {}
        for kt in self._by_key:
            self._first.setdefault(kt[0], []).append(kt)
        for lst in self._first.values():
            lst.sort(key=lambda k: -len(k))
        self.hash = aliases.hash

    def strings(self) -> list[str]:
        return sorted((v[0] for v in self._by_key.values()),
                      key=lambda s: (-len(keys(s)), s.lower()))

    def entry(self, term: str) -> Optional[AliasEntry]:
        """The aliases entry a string (or its token key) belongs to."""
        e = self._entry_of.get(term.lower())
        if e is not None:
            return e
        hit = self._by_key.get(keys(term))
        return hit[2] if hit else None

    def canonical_of(self, term: str) -> str:
        hit = self._by_key.get(keys(term))
        return hit[1] if hit else term.strip().lower()

    def hits(self, text: str) -> list[Hit]:
        """Dictionary hits with the overlap rule: when spans overlap keep the
        longest (token count), then the earliest ("Spring Boot" suppresses
        "Spring"). Returned in text order."""
        toks = _scan(text, self.ambiguous)
        cand = []
        for i in range(len(toks)):
            for kt in self._first.get(toks[i][2], ()):
                last = _match_at(text, toks, i, kt)
                if last is not None:
                    cand.append((len(kt), i, toks[i][0], toks[last][1], kt))
        cand.sort(key=lambda c: (-c[0], c[1]))
        taken: list[tuple[int, int]] = []
        out = []
        for _n, _i, s, e, kt in cand:
            if any(s < te and ts < e for ts, te in taken):
                continue
            taken.append((s, e))
            string, canon, _entry = self._by_key[kt]
            out.append(Hit(s, e, canon, string))
        out.sort(key=lambda h: h.start)
        return out


def load_dictionary(aliases_path: str | Path, extra: Iterable[str] = ()) -> Dictionary:
    return Dictionary(Aliases.load(aliases_path), extra)


# ---------------------------------------------------------------------------
# 4.3 Deterministic extraction
# ---------------------------------------------------------------------------

_HTML = re.compile(r"<[a-z][a-z0-9]*[\s>/]", re.I)
_ITEM = re.compile(r"^(?:[-*•▪◦‣●]|\d{1,3}[.)](?=\s))")
_PREFERRED_HEAD = re.compile(
    r"nice to have|preferred|bonus|desirable|good to have|a plus|advantage|optional", re.I)
_PREFERRED_LINE = re.compile(r"is a plus|preferred|nice to have|bonus|advantageous", re.I)
_SMALL = frozenset("a an and as at by for in of on or the to with".split())
_SENT_PUNCT = re.compile(r"[.!?;]")
_KNOCKOUT = re.compile(
    r"citizen|permanent resident|\bPR\b|work pass|employment pass|visa|sponsorship|"
    r"right to work|must be (based|located) in|security clearance", re.I)


def looks_like_html(text: str) -> bool:
    return bool(_HTML.search(text or ""))


def jd_text(raw: str, html_to_text: Optional[Callable[[str], str]] = None,
            max_chars: int = MAX_JD_CHARS) -> str:
    """Step 1: the JD as plain text, truncated."""
    text = raw or ""
    if html_to_text is not None and looks_like_html(text):
        text = html_to_text(text)
    return text[:max_chars]


def _is_heading(line: str) -> bool:
    words = line.split()
    if not words or len(words) > 8:
        return False
    if line.endswith(":"):
        return True
    if _SENT_PUNCT.search(line):
        return False
    for i, w in enumerate(words):
        if not w[0].isalpha() or w[0].isupper():
            continue
        if i > 0 and w.lower() in _SMALL:
            continue
        return False
    return True


def _line_labels(text: str) -> list[tuple[int, int, bool]]:
    """(start, end, required) per non-empty line, walking top to bottom."""
    out = []
    required = True
    pos = 0
    for raw in re.split(r"(\r?\n)", text):
        if raw in ("\n", "\r\n"):
            pos += len(raw)
            continue
        line = raw.strip()
        start = pos + (len(raw) - len(raw.lstrip()))
        end = start + len(line)
        pos += len(raw)
        if not line:
            continue
        if _ITEM.match(line):
            label = required and not _PREFERRED_LINE.search(line)
        elif _is_heading(line):
            required = not _PREFERRED_HEAD.search(line)
            label = required
        else:
            label = required and not _PREFERRED_LINE.search(line)
        out.append((start, end, label))
    return out


def extract(jd: str, dictionary: Dictionary, max_chars: int = MAX_JD_CHARS) -> list[JdTerm]:
    """Dictionary terms of a JD in JD order (first hit), status unset. Terms are
    grouped by canonical; the spelling is the first hit's surface; a term with
    any required hit is required."""
    text = jd[:max_chars]
    labels = _line_labels(text)
    order: list[str] = []
    seen: dict[str, JdTerm] = {}
    for h in dictionary.hits(text):
        required = True
        for s, e, lab in labels:
            if s <= h.start <= e:
                required = lab
                break
        t = seen.get(h.canonical)
        if t is None:
            seen[h.canonical] = JdTerm(term=text[h.start:h.end], canonical=h.canonical,
                                       required=required)
            order.append(h.canonical)
        elif required:
            t.required = True
    return [seen[c] for c in order]


def knockouts(jd: str) -> list[str]:
    """JD lines that read as application questions (citizenship, visa...)."""
    out = []
    for line in re.split(r"\r?\n", jd):
        line = line.strip()
        if line and len(line) <= 200 and _KNOCKOUT.search(line):
            out.append(line)
            if len(out) == 5:
                break
    return out
