"""Tier 4: declarations and attestations (apply_design §7.5, PRD F-33, D-55).

Questions like "Are you a politically exposed person?", "Do you hold shares
in this company?" or "Have you previously worked for us?" are statements the
owner signs. They are answered only from the profile's standing declarations
(D-55: "No" unless the owner says otherwise) and from facts in the data
(prior employment from `experience[]`, a previous application from the
store) - never by the model, and never by guessing: a question that looks like
an attestation but cannot be pinned to one class fails closed.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from .contracts import DeclarationLabel
from .plan import norm_label

# Tokens dropped before comparing company names (only while others remain).
_COMPANY_NOISE = frozenset({"pte", "ltd", "limited", "inc", "llc", "corp", "corporation",
                            "co", "plc", "group", "holdings", "the", "singapore", "sg", "bank"})


def _company_tokens(name: str) -> list[str]:
    toks = norm_label(name or "").split()
    kept = [t for t in toks if t not in _COMPANY_NOISE]
    return kept or toks


def company_match(a: str, b: str) -> bool:
    """§7.5: both names normalised (§7.1) with legal-form and filler tokens
    dropped (only while other tokens remain); a match if equal or one token
    list is a prefix of the other. "DBS Bank Ltd" ~ "DBS"; "Grab" ~ "Grab
    Financial Group" (on a declaration a truthful Yes beats a wrong No)."""
    ta, tb = _company_tokens(a), _company_tokens(b)
    if not ta or not tb:
        return False
    n = min(len(ta), len(tb))
    return ta[:n] == tb[:n]


def _matches_employer(name: str, employer: str, aliases: Iterable[str]) -> bool:
    return any(company_match(name, e) for e in (employer, *aliases) if e)


def prior_employment(profile: dict, employer: str, aliases: Iterable[str] = ()) -> bool:
    """True if any `experience[].employer` company-matches the employer or one
    of its aliases (internships count, D-55)."""
    aliases = tuple(aliases)
    return any(isinstance(e, dict) and _matches_employer(str(e.get("employer") or ""),
                                                         employer, aliases)
               for e in (profile or {}).get("experience") or [])


def current_employment(profile: dict, employer: str, aliases: Iterable[str] = ()) -> bool:
    """D-69: true only if a matching `experience[]` entry has no end date."""
    aliases = tuple(aliases)
    return any(isinstance(e, dict) and e.get("end") in (None, "")
               and _matches_employer(str(e.get("employer") or ""), employer, aliases)
               for e in (profile or {}).get("experience") or [])
