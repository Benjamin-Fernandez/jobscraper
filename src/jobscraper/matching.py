"""Stage A (rule filters) and Stage B (local scoring). Both cost zero tokens.

Stage A is deliberately conservative: a rule may only reject what is unambiguous.
A posting killed here is never seen again, so ambiguity is passed downstream rather
than resolved by guessing.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable, Optional

from .config import Profile
from .models import Candidate, ScoreBreakdown

TOKEN_RE = re.compile(r"[a-z0-9+#./-]+")
YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?year", re.I)

TIER_POINTS = {"T1": 100.0, "T2": 80.0, "T3": 60.0, "T4": 45.0, "Gov": 65.0}

# Titles that carry engineering signal even when no allow-pattern matches.
TITLE_TOKENS = {
    "engineer", "engineering", "developer", "software", "technology",
    "technical", "quant", "quantitative", "data", "platform", "infrastructure",
    "backend", "frontend", "fullstack", "cloud", "security", "systems",
    "programmer", "architect", "devops", "sre", "analyst", "associate",
    "graduate",
}

REQ_HEADINGS = re.compile(
    r"(requirement|qualification|what you.{0,12}(need|bring)|who you are|"
    r"skills|about you|we.{0,6}re looking for|minimum|basic qualifications|"
    r"preferred)", re.I)


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall((text or "").lower())


def extract_requirements(text: str, limit: int) -> str:
    """Trim a JD toward its requirements section before truncation."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    m = REQ_HEADINGS.search(text)
    if m:
        start = max(0, m.start() - 200)
        return text[start:start + limit]
    return text[:limit]


# --------------------------------------------------------------------------
# Stage A
# --------------------------------------------------------------------------

def _has(text: str, needles: Iterable[str]) -> Optional[str]:
    low = text.lower()
    for n in needles:
        if n in low:
            return n
    return None


# Filler that carries no geography once the ambiguous tokens are removed, so a
# residue made only of these still counts as genuinely location-free.
_LOC_FILLER = re.compile(
    r"\b(?:remote|hybrid|on[- ]?site|onsite|in[- ]?office|office|based|only|"
    r"first|friendly|optional|preferred|flexible|work from home|wfh|national|"
    r"nationwide|home|full[- ]?time|permanent|other|location|locations)\b")


def location_verdict(location: str, profile: Profile) -> str:
    """-> 'singapore' | 'elsewhere' | 'ambiguous'.

    Default-DENY. The allow list is a single country, so an enumerated deny list
    can never be complete ("Zug, Switzerland" and "Aarhus, Denmark" are not on
    it, and would otherwise sail through as ambiguous). A location string that
    states somewhere concrete and does not name Singapore is elsewhere.
    Only genuinely vague strings are routed onward for the model to normalize.

    "Remote" is only vague when it is *unqualified*. A remote role pinned to a
    region we cannot work in ("US Remote", "Remote - Canada", "SF, NY, Remote")
    names somewhere concrete and is rejected like any other foreign location:
    the visa makes it unreachable regardless of where the desk is. So the
    ambiguous tokens are stripped and whatever is left over decides. That way a
    region we have never enumerated ("Remote - Bulgaria") still fails closed.
    """
    loc = (location or "").strip().lower()
    if not loc:
        return "ambiguous"
    if re.search(r"\bsingapore\b|\bsingapura\b|\bsg\b", loc):
        return "singapore"
    # Explicit foreign hint beats any "remote" in the same string.
    if profile.loc_deny_re is not None and profile.loc_deny_re.search(loc):
        return "elsewhere"

    residue = loc
    matched_hint = False
    for hint in sorted(profile.loc_ambiguous, key=len, reverse=True):
        if hint in residue:
            matched_hint = True
            residue = residue.replace(hint, " ")
    if not matched_hint:
        return "elsewhere"

    residue = _LOC_FILLER.sub(" ", residue)
    # Anything alphanumeric still standing is a place we did not allow.
    if re.search(r"[a-z0-9]", residue):
        return "elsewhere"
    return "ambiguous"


def min_years_required(text: str) -> Optional[int]:
    if not text:
        return None
    found = [int(m) for m in YEARS_RE.findall(text) if str(m).isdigit()]
    found = [f for f in found if 0 <= f <= 30]
    return min(found) if found else None


def stage_a(cand: Candidate, profile: Profile) -> bool:
    """Apply hard filters. Sets filter_reason and returns pass/fail."""
    title = cand.raw.title or ""

    for pat in profile.deny_res:
        if pat.search(title):
            cand.stage_a_pass = False
            cand.filter_reason = f"title denied: {pat.pattern[:40]}"
            return False

    allowed = any(p.search(title) for p in profile.allow_res)
    if not allowed:
        toks = set(tokenize(title))
        if not (toks & TITLE_TOKENS):
            cand.stage_a_pass = False
            cand.filter_reason = "title carries no engineering signal"
            return False

    verdict = location_verdict(cand.raw.location, profile)
    if verdict == "elsewhere":
        cand.stage_a_pass = False
        cand.filter_reason = f"location outside Singapore: {cand.raw.location[:60]}"
        return False
    cand.location_ambiguous = verdict == "ambiguous"

    floor = min_years_required(cand.raw.description)
    if floor is not None and floor >= profile.experience["hard_floor_reject"]:
        cand.stage_a_pass = False
        cand.filter_reason = f"requires {floor}+ years"
        return False

    et = (cand.raw.employment_type or "").lower()
    if any(w in et for w in ("intern", "temporary", "contract", "part")):
        cand.stage_a_pass = False
        cand.filter_reason = f"employment type: {cand.raw.employment_type}"
        return False

    cand.stage_a_pass = True
    return True


# --------------------------------------------------------------------------
# Stage B
# --------------------------------------------------------------------------

class Bm25:
    """Compact BM25 over the current batch of postings."""

    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.72):
        self.k1, self.b = k1, b
        self.n = max(len(docs), 1)
        self.avg_len = (sum(len(d) for d in docs) / self.n) if docs else 1.0
        self.avg_len = max(self.avg_len, 1.0)
        self.df: Counter = Counter()
        for d in docs:
            self.df.update(set(d))

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def score(self, doc: list[str], query: list[str]) -> float:
        if not doc:
            return 0.0
        tf = Counter(doc)
        dl = len(doc)
        total = 0.0
        for term in query:
            f = tf.get(term, 0)
            if not f:
                continue
            denom = f + self.k1 * (1 - self.b + self.b * dl / self.avg_len)
            total += self.idf(term) * (f * (self.k1 + 1)) / denom
        return total


def _saturate(raw: float, half: float) -> float:
    """Map an unbounded positive score onto 0-100, stable across runs."""
    return 100.0 * raw / (raw + half) if raw > 0 else 0.0


def skill_overlap(text_tokens: set[str], text_low: str,
                  profile: Profile) -> tuple[float, list[str]]:
    weights = {"core": 3.0, "strong": 2.0, "domain": 2.0, "weak": 1.0}
    raw = 0.0
    hits: list[str] = []
    for group, skills in profile.skill_groups().items():
        w = weights.get(group, 1.0)
        for skill in skills:
            found = (skill in text_low) if (" " in skill or "." in skill) \
                else (skill in text_tokens)
            if found:
                raw += w
                hits.append(skill)
    return _saturate(raw, 14.0), hits


def title_affinity(title: str, role_hint: str, profile: Profile) -> float:
    score = 0.0
    if any(p.search(title) for p in profile.allow_res):
        score += 60.0
    low = title.lower()
    if re.search(r"\b(graduate|new ?grad|campus|university|early career|20\s?2[67])\b",
                 low):
        score += 25.0
    hint_tokens = {t for t in tokenize(role_hint) if len(t) > 2 and t != "swe"}
    if hint_tokens:
        overlap = len(hint_tokens & set(tokenize(title))) / len(hint_tokens)
        score += 15.0 * overlap
    return min(score, 100.0)


def category_prior_score(text_low: str, category: str, profile: Profile) -> float:
    terms = profile.category_prior(category)
    if not terms:
        return 0.0
    hits = sum(1 for t in terms if str(t).lower() in text_low)
    return 100.0 * hits / len(terms)


def score_batch(cands: list[Candidate], profile: Profile) -> None:
    """Score every candidate in place. Only call on Stage-A survivors."""
    if not cands:
        return

    docs = [tokenize(f"{c.raw.title}\n{c.raw.department}\n{c.raw.description}")
            for c in cands]
    bm = Bm25(docs)

    base_query = tokenize(profile.summary) + [
        t for s in profile.all_skills() for t in tokenize(s)]

    w = profile.weights
    for cand, doc in zip(cands, docs):
        query = list(base_query) + tokenize(cand.company.role_type_hint) + [
            t for s in profile.category_prior(cand.company.category)
            for t in tokenize(str(s))]

        text_low = f"{cand.raw.title}\n{cand.raw.description}".lower()
        tok_set = set(doc)

        bm_norm = _saturate(bm.score(doc, query), 12.0)
        overlap, _hits = skill_overlap(tok_set, text_low, profile)
        title = title_affinity(cand.raw.title, cand.company.role_type_hint, profile)
        tier = TIER_POINTS.get(cand.company.tier, 50.0)
        cat = category_prior_score(text_low, cand.company.category, profile)

        total = (w["bm25"] * bm_norm + w["skill_overlap"] * overlap
                 + w["title_affinity"] * title + w["tier_bonus"] * tier
                 + w["category_prior"] * cat)

        cand.score = ScoreBreakdown(
            total=round(total, 1), bm25=round(bm_norm, 1),
            skill_overlap=round(overlap, 1), title_affinity=round(title, 1),
            tier_bonus=round(tier, 1), category_prior=round(cat, 1))


def apply_facts(cand: Candidate, profile: Profile) -> bool:
    """Re-filter using Stage C1 extraction. Returns False if now rejected."""
    f = cand.facts
    if not f:
        return True
    if f.is_singapore is False:
        cand.stage_a_pass = False
        cand.filter_reason = (
            "extracted location not Singapore: " + ",".join(f.countries))
        return False
    if f.seniority in ("mid", "senior", "lead", "staff", "principal", "intern"):
        cand.stage_a_pass = False
        cand.filter_reason = f"extracted seniority: {f.seniority}"
        return False
    ceiling = profile.experience["ceiling_years"]
    if f.yoe_min is not None and f.yoe_min > ceiling:
        cand.stage_a_pass = False
        cand.filter_reason = f"extracted {f.yoe_min}+ years required"
        return False
    return True
