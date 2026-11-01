"""Answer resolution: every form field gets exactly one Answer (apply_design §7, KA-2).

Tiers, in PRD F-32 order, first answer wins:

  1 field map    the adapter tagged the field with a Canonical (§7.2)       1.0
  2 profile rule config/questions.yaml synonyms -> a profile path (§7.3)    0.95
  3 memory       the owner's own past corrections (§7.4, read-only in M20)  0.95
  4 declaration  attestations from the standing declarations (§7.5)         0.95
  5 local model  Ollama, grounded against profile + resume + JD (§7.6-7.7)  0.9/0.8

A tier "answers" only with a value valid for the field: one of the offered
options for a choice, a non-empty string within `max_length` for text. When
nothing answers, a required field is `unknown` (the attempt fails before
anything is typed) and an optional one is `blank_optional`.

Fail closed (ADR-0003): a sensitive (S) fact or an attestation that does not
map onto the offered options stops at `unknown` - it never reaches the model.
Fields the adapter tagged with a Canonical are owned by the profile: when the
field map has no value, only the owner's memory (tier 3) may still answer.

This module never logs and never sees a store: memory arrives as a callable
and the model as a `backends.Backend` handed in by apply_flow.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Union

import yaml

from .. import applicant
from .contracts import (
    CHOICE_TYPES, Answer, AnswerStatus, AnswerTier, Canonical, FieldType, FormField,
    Option, ResolveContext,
)
from . import declarations
from .plan import norm_label, phrase_match_tokens, tokens

MemoryLookup = Callable[[str, str, str], Optional[str]]

CONF_FIELD_MAP = 1.0
CONF_PROFILE = 0.95
CONF_MEMORY = 0.95
CONF_DECLARATION = 0.95

TEXT_TYPES = frozenset({FieldType.TEXT, FieldType.TEXTAREA, FieldType.EMAIL, FieldType.PHONE,
                        FieldType.NUMBER, FieldType.URL, FieldType.DATE, FieldType.TYPEAHEAD})
SINGLE_CHOICE = frozenset({FieldType.DROPDOWN, FieldType.RADIO})

KINDS = frozenset({"bool", "enum", "text", "number", "salary", "date", "url", "country"})

# --------------------------------------------------------------------------
# Countries (§7.2 COUNTRY, §7.3.2 country): ISO 3166-1 alpha-2 -> name, demonym.
# SG first; the rest cover every country questions.yaml names in its excludes.
# --------------------------------------------------------------------------

COUNTRIES: dict[str, tuple[str, str]] = {
    "SG": ("Singapore", "Singaporean"),
    "MY": ("Malaysia", "Malaysian"),
    "ID": ("Indonesia", "Indonesian"),
    "TH": ("Thailand", "Thai"),
    "VN": ("Vietnam", "Vietnamese"),
    "PH": ("Philippines", "Filipino"),
    "CN": ("China", "Chinese"),
    "HK": ("Hong Kong", "Hong Konger"),
    "TW": ("Taiwan", "Taiwanese"),
    "JP": ("Japan", "Japanese"),
    "KR": ("South Korea", "South Korean"),
    "IN": ("India", "Indian"),
    "AU": ("Australia", "Australian"),
    "NZ": ("New Zealand", "New Zealander"),
    "US": ("United States", "American"),
    "GB": ("United Kingdom", "British"),
    "CA": ("Canada", "Canadian"),
    "DE": ("Germany", "German"),
    "FR": ("France", "French"),
    "NL": ("Netherlands", "Dutch"),
    "IE": ("Ireland", "Irish"),
    "CH": ("Switzerland", "Swiss"),
    "AR": ("Argentina", "Argentine"),
    "BR": ("Brazil", "Brazilian"),
}

# --------------------------------------------------------------------------
# Option vocabularies (§7.3.2)
# --------------------------------------------------------------------------

YES_PREFIXES = ("yes", "y", "true", "i am", "i do", "i have", "i will", "i can",
                "authorised", "authorized")
NO_PREFIXES = ("no", "n", "false", "i am not", "i do not", "i don't", "i dont",
               "i have not", "i will not", "not")
DECLINE_PHRASES = ("decline", "prefer not", "choose not", "not wish", "don't wish",
                   "dont wish", "do not wish", "rather not", "not to disclose",
                   "not to answer", "not to say", "don't want to answer",
                   "do not want to answer")

# US self-identification values -> option phrases (§7.2 EEO_*). "decline" is
# handled by DECLINE_PHRASES.
EEO_VALUE_MAP: dict[Canonical, dict[str, tuple[str, ...]]] = {
    Canonical.EEO_GENDER: {
        "male": ("male", "man"), "female": ("female", "woman"),
        "non_binary": ("non binary", "nonbinary"),
    },
    Canonical.EEO_RACE: {
        "asian": ("asian",), "black": ("black or african american", "black", "african american"),
        "hispanic_latino": ("hispanic or latino", "hispanic", "latino"),
        "white": ("white",), "two_or_more": ("two or more races", "two or more"),
        "native_american": ("american indian or alaska native", "american indian",
                            "native american"),
        "pacific_islander": ("native hawaiian or other pacific islander", "pacific islander",
                             "native hawaiian"),
    },
    Canonical.EEO_VETERAN: {
        "not_a_veteran": ("i am not a protected veteran", "not a protected veteran",
                          "not a veteran"),
        "veteran": ("i identify as one or more of the classifications of protected veteran",
                    "identify as one or more", "i am a protected veteran"),
    },
    Canonical.EEO_DISABILITY: {
        "yes": ("yes i have a disability", "i have a disability"),
        "no": ("no i do not have a disability", "i do not have a disability",
               "no i don't have a disability", "i don't have a disability"),
    },
}
EEO_PATHS: dict[Canonical, str] = {
    Canonical.EEO_GENDER: "us_self_id.eeo_gender",
    Canonical.EEO_RACE: "us_self_id.eeo_race_ethnicity",
    Canonical.EEO_HISPANIC: "us_self_id.eeo_race_ethnicity",
    Canonical.EEO_VETERAN: "us_self_id.veteran_status",
    Canonical.EEO_DISABILITY: "us_self_id.disability_status",
}

# Canonicals whose value is an S fact (§5.3): answers carry sensitive=True.
SENSITIVE_CANONICALS = frozenset({
    Canonical.EMAIL, Canonical.PHONE, Canonical.PHONE_COUNTRY_CODE,
    Canonical.ADDRESS_LINE1, Canonical.ADDRESS_LINE2, Canonical.POSTAL_CODE,
    Canonical.EEO_GENDER, Canonical.EEO_RACE, Canonical.EEO_HISPANIC,
    Canonical.EEO_VETERAN, Canonical.EEO_DISABILITY, Canonical.PREVIOUS_WORKER,
})


# --------------------------------------------------------------------------
# questions.yaml (§7.3.1)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    key: str                                   # a profile path, or computed.<name>
    kind: str
    sensitive: bool
    synonyms: tuple[tuple[str, ...], ...]      # normalised token tuples
    exclude: tuple[tuple[str, ...], ...] = ()
    value_map: dict[str, tuple[str, ...]] = dc_field(default_factory=dict)

    def score(self, label_toks: Sequence[str]) -> int:
        """Token count of the longest matching synonym; 0 if an exclude matches."""
        if any(phrase_match_tokens(x, label_toks) for x in self.exclude):
            return 0
        return max((len(s) for s in self.synonyms if phrase_match_tokens(s, label_toks)),
                   default=0)


@dataclass(frozen=True)
class QuestionRules:
    rules: tuple[Rule, ...] = ()

    @classmethod
    def load(cls, path: Union[str, Path]) -> "QuestionRules":
        return load_rules(path)

    def select(self, label_norm: str) -> tuple[list[Rule], int]:
        """The top-scoring rules for a label and their score (§7.3.1 selection).
        One rule = a match; two or more = a tie (tier 2 does not answer)."""
        toks = label_norm.split()
        best, top = [], 0
        for r in self.rules:
            s = r.score(toks)
            if s > top:
                best, top = [r], s
            elif s and s == top:
                best.append(r)
        return best, top


def _phrase_list(raw: Any, where: str) -> tuple[tuple[str, ...], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        raise ValueError(f"{where}: must be a list of phrases")
    out = tuple(tuple(tokens(p)) for p in raw)
    if any(not t for t in out):
        raise ValueError(f"{where}: a phrase is empty after normalisation")
    return out


def load_rules(path: Union[str, Path]) -> QuestionRules:
    """Read questions.yaml. A missing file = no rules; an invalid one raises
    ValueError naming the bad key (D-69)."""
    p = Path(path)
    if not p.exists():
        return QuestionRules()
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{p.name}: not valid YAML ({type(exc).__name__})") from exc
    if not isinstance(data, dict) or not isinstance(data.get("questions", []), list):
        raise ValueError(f"{p.name}: expected a mapping with a `questions` list")
    rules, seen = [], set()
    for i, e in enumerate(data.get("questions") or []):
        key = e.get("key") if isinstance(e, dict) else None
        where = f"questions[{i}] ({key or '?'})"
        if not isinstance(key, str) or not key:
            raise ValueError(f"{where}: missing key")
        if key in seen:
            raise ValueError(f"{where}: duplicate key")
        seen.add(key)
        kind = e.get("kind")
        if kind not in KINDS:
            raise ValueError(f"{where}: kind must be one of {sorted(KINDS)}")
        synonyms = _phrase_list(e.get("synonyms"), f"{where}.synonyms")
        if not synonyms:
            raise ValueError(f"{where}: needs at least one synonym")
        vm_raw = e.get("value_map") or {}
        if not isinstance(vm_raw, dict):
            raise ValueError(f"{where}.value_map: must be a mapping")
        value_map = {}
        for v, phrases in vm_raw.items():
            if not isinstance(phrases, list) or not all(isinstance(x, str) for x in phrases):
                raise ValueError(f"{where}.value_map.{v}: must be a list of phrases")
            value_map[str(v)] = tuple(phrases)
        if kind == "enum" and not value_map:
            raise ValueError(f"{where}: an enum needs a value_map")
        rules.append(Rule(key=key, kind=kind, sensitive=bool(e.get("sensitive", False)),
                          synonyms=synonyms,
                          exclude=_phrase_list(e.get("exclude"), f"{where}.exclude"),
                          value_map=value_map))
    return QuestionRules(tuple(rules))


# --------------------------------------------------------------------------
# Profile access
# --------------------------------------------------------------------------

_PART = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def profile_value(profile: dict, path: str, today: Optional[_dt.date] = None) -> Any:
    """The value at a dotted path with list indices ("education[0].end"), or
    computed.<name> from applicant.computed_facts. None when absent."""
    if path.startswith("computed."):
        facts = applicant.computed_facts(profile, today or applicant.today_sg())
        return facts.get(path.split(".", 1)[1])
    cur: Any = profile
    for name, idx in _PART.findall(path):
        if idx:
            i = int(idx)
            if not isinstance(cur, list) or i >= len(cur):
                return None
            cur = cur[i]
        else:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(name)
    if path == "languages" and isinstance(cur, list):
        return ", ".join(f"{x.get('language')} ({x.get('spoken')})" if x.get("spoken")
                         else str(x.get("language"))
                         for x in cur if isinstance(x, dict) and x.get("language")) or None
    return cur


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or v == [] or v == {}


def full_name(profile: dict) -> str:
    first = str(profile_value(profile, "identity.legal_first_name") or "").strip()
    last = str(profile_value(profile, "identity.legal_last_name") or "").strip()
    if profile_value(profile, "identity.name_order") == "surname_first":
        return f"{last} {first}".strip()
    return f"{first} {last}".strip()


# --------------------------------------------------------------------------
# Fitting a value onto a field (§7.3.2). Each returns (value, option_labels)
# or None when the value does not fit.
# --------------------------------------------------------------------------

Fit = tuple[Any, tuple[str, ...]]


def _opts(f: FormField) -> list[tuple[Option, list[str]]]:
    return [(o, tokens(o.label)) for o in f.options]


def _choose(f: FormField, chosen: Sequence[Option]) -> Fit:
    labels = tuple(o.label for o in chosen)
    if f.type is FieldType.MULTI_CHOICE:
        return list(labels), labels
    return labels[0], labels


def _starts(toks: Sequence[str], prefix: str) -> bool:
    p = prefix.split()
    return list(toks[:len(p)]) == p


def polarity(label: str) -> Optional[bool]:
    """True for a yes-label, False for a no-label, None otherwise. No-prefixes
    are tested first so "i am not" never counts as yes."""
    toks = tokens(label)
    if any(_starts(toks, p) for p in NO_PREFIXES):
        return False
    if any(_starts(toks, p) for p in YES_PREFIXES):
        return True
    return None


def fit_bool(f: FormField, value: Any) -> Optional[Fit]:
    """bool -> the one option of that polarity; text gets Yes/No; a single
    checkbox is ticked for true. A required checkbox is never left unticked
    on purpose (that would not answer it), so false + required -> None."""
    if not isinstance(value, bool):
        return None
    if f.type is FieldType.CHECKBOX:
        if not value and f.required:
            return None
        return ("true" if value else "false"), ()
    if f.type in CHOICE_TYPES:
        hits = [o for o, _t in _opts(f) if polarity(o.label) is value]
        return _choose(f, hits) if len(hits) == 1 else None
    if f.type in (FieldType.TEXT, FieldType.TEXTAREA, FieldType.TYPEAHEAD):
        return ("Yes" if value else "No"), ()
    return None


def decline_option(f: FormField) -> Optional[Option]:
    """The first offered option that says "prefer not to say" in any wording."""
    phrases = [p.split() for p in DECLINE_PHRASES]
    for o, toks in _opts(f):
        if any(phrase_match_tokens(p, toks) for p in phrases):
            return o
    return None


def fit_decline(f: FormField) -> Optional[Fit]:
    if f.type not in CHOICE_TYPES:
        return None
    o = decline_option(f)
    return _choose(f, [o]) if o else None


def _match_options(f: FormField, phrases: Sequence[str]) -> list[Option]:
    """Options whose label equals one of `phrases`, else options whose label
    contains one as a phrase."""
    ptoks = [tokens(p) for p in phrases if tokens(p)]
    opts = _opts(f)
    equal = [o for o, t in opts if any(t == p for p in ptoks)]
    if equal:
        return equal
    return [o for o, t in opts if any(phrase_match_tokens(p, t) for p in ptoks)]


def fit_enum(f: FormField, value: Any, value_map: dict[str, Sequence[str]]) -> Optional[Fit]:
    """enum -> exactly one option: by the value_map phrases, then by the enum
    value itself ("_" read as a space). "decline" -> the decline option."""
    if _blank(value) or f.type not in CHOICE_TYPES:
        return None
    value = str(value)
    if value == "decline":
        return fit_decline(f)
    hits = _match_options(f, value_map.get(value, ()))
    if not hits:
        hits = _match_options(f, [value.replace("_", " ")])
    return _choose(f, hits) if len(hits) == 1 else None


def fit_text(f: FormField, value: Any) -> Optional[Fit]:
    """url / text: the value as is, never truncated. On a choice field: the
    option equal to the value, else the one containing it."""
    if _blank(value) or isinstance(value, (dict, list, bool)):
        return None
    text = str(value).strip()
    if f.type in CHOICE_TYPES:
        hits = _match_options(f, [text])
        return _choose(f, hits) if len(hits) == 1 else None
    if f.type not in TEXT_TYPES or f.type is FieldType.NUMBER:
        return None
    if f.max_length is not None and len(text) > f.max_length:
        return None
    return text, ()


_NUM = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k)?")
_BELOW = re.compile(r"\b(below|under|less than|up to)\b")
_ABOVE = re.compile(r"\b(above|over|more than|and above)\b|\+")


def parse_range(label: str) -> Optional[tuple[float, float]]:
    """A numeric range in an option label: "0-1 years", "S$3,000 - S$4,000",
    "Below 3000", "5000 and above", "3k-4k", "5+". Inclusive bounds."""
    low = label.lower()
    nums = []
    for m in _NUM.finditer(low):
        n = float(m.group(1).replace(",", ""))
        nums.append(n * 1000 if m.group(2) else n)
    if not nums:
        return None
    if _BELOW.search(low):
        return (float("-inf"), nums[0])
    if _ABOVE.search(low):
        return (nums[0], float("inf"))
    if len(nums) >= 2:
        return (min(nums[0], nums[1]), max(nums[0], nums[1]))
    return (nums[0], nums[0])


def _int_text(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else str(n)


def fit_number(f: FormField, value: Any) -> Optional[Fit]:
    """A number: text inputs get the integer; options are read as ranges and
    the unique one containing the value is chosen."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if f.type in SINGLE_CHOICE:
        hits = [o for o in f.options
                if (r := parse_range(o.label)) is not None and r[0] <= value <= r[1]]
        return _choose(f, hits) if len(hits) == 1 else None
    if f.type in (FieldType.TEXT, FieldType.NUMBER, FieldType.TEXTAREA):
        return _int_text(value), ()
    return None


_CURRENCY_CODES = ("SGD", "USD", "EUR", "GBP", "MYR", "INR", "AUD", "HKD", "CNY", "RMB",
                   "JPY", "IDR", "PHP", "THB", "VND", "KRW", "TWD", "NZD", "CAD", "CHF")
# Currency signs; a letter just before "S$" / "A$" makes it another sign (US$, HK$).
_CURRENCY_SYMBOLS = ((re.compile(r"(?<![A-Za-z])S\$"), "SGD"), (re.compile(r"US\$"), "USD"),
                     (re.compile(r"HK\$"), "HKD"), (re.compile(r"(?<![A-Za-z])A\$"), "AUD"),
                     (re.compile("€"), "EUR"), (re.compile("£"), "GBP"),
                     (re.compile(r"\bRM\b"), "MYR"), (re.compile("₹"), "INR"))


def _currencies(text: str) -> set[str]:
    """Currencies a label or its options name, by code or sign."""
    found = {c for c in _CURRENCY_CODES if re.search(rf"\b{c}\b", text.upper())}
    found |= {code for pat, code in _CURRENCY_SYMBOLS if pat.search(text)}
    return {"CNY" if c == "RMB" else c for c in found}


def fit_salary(f: FormField, value: Any, months_per_year: int = 12) -> Optional[Fit]:
    """§7.3.2 salary: the period from the label (annual = monthly x
    months_per_year), a foreign currency in the label or options -> no answer,
    text gets digits only. No current salary -> "0" only for a required
    "current" question, else no answer."""
    label_toks = tokens(f.label)
    if value is None:
        if f.required and "current" in label_toks and f.type in (FieldType.TEXT,
                                                                 FieldType.NUMBER):
            return "0", ()
        return None
    if not isinstance(value, dict) or not isinstance(value.get("amount"), int) \
            or isinstance(value.get("amount"), bool) or value["amount"] <= 0:
        return None
    currency = str(value.get("currency") or "SGD").upper()
    seen = _currencies(f.label + " " + " ".join(o.label for o in f.options))
    if seen - {currency}:
        return None
    norm = " ".join(label_toks)
    if re.search(r"\b(annual|annum|yearly|per year|p a)\b", norm):
        period = "annual"
    elif re.search(r"\b(month|monthly|per month)\b", norm):
        period = "monthly"
    else:
        period = value.get("period") or "monthly"
    months = months_per_year
    amount = float(value["amount"])
    have = value.get("period") or "monthly"
    if have == "monthly" and period == "annual":
        amount *= months
    elif have == "annual" and period == "monthly":
        amount = round(amount / months)
    return fit_number(f, amount)


def country_names(code: Any) -> tuple[str, ...]:
    if not isinstance(code, str):
        return ()
    return COUNTRIES.get(code.strip().upper(), ())


def fit_country(f: FormField, code: Any) -> Optional[Fit]:
    """ISO code -> the option equal to the country name (or demonym), else
    the one containing it; text gets the name."""
    names = country_names(code)
    if not names:
        return None
    if f.type in CHOICE_TYPES:
        hits = _match_options(f, names)
        return _choose(f, hits) if len(hits) == 1 else None
    if f.type in (FieldType.TEXT, FieldType.TYPEAHEAD):
        return names[0], ()
    return None


def fit_date(f: FormField, value: Any) -> Optional[Fit]:
    """ISO from the profile; the adapter formats it."""
    if isinstance(value, (_dt.date, _dt.datetime)):
        value = value.isoformat()[:10]
    if _blank(value) or not isinstance(value, str):
        return None
    if f.type in (FieldType.DATE, FieldType.TEXT):
        return value.strip(), ()
    return None


def fit_kind(f: FormField, kind: str, value: Any, *, value_map=None,
             profile: Optional[dict] = None) -> Optional[Fit]:
    if kind == "bool":
        return fit_bool(f, value)
    if kind == "enum":
        return fit_enum(f, value, value_map or {})
    if kind == "number":
        return fit_number(f, value)
    if kind == "salary":
        mpy = profile_value(profile or {}, "pay.months_per_year")
        ok = isinstance(mpy, int) and not isinstance(mpy, bool) and mpy > 0
        return fit_salary(f, value, mpy if ok else 12)
    if kind == "date":
        return fit_date(f, value)
    if kind == "country":
        return fit_country(f, value)
    return fit_text(f, value)          # text, url


# --------------------------------------------------------------------------
# Answers
# --------------------------------------------------------------------------

class _Stop:
    """A tier found the profile owns this fact but it fits no offered option:
    resolution ends here (required -> unknown, optional -> blank_optional)."""
    def __init__(self, note: str, sensitive: bool = False):
        self.note, self.sensitive = note, sensitive


def _answer(f: FormField, fit: Fit, tier: AnswerTier, source: str, conf: float, *,
            rule_id: str = "", sensitive: bool = False, note: str = "") -> Answer:
    value, labels = fit
    return Answer(field_key=f.key, value=value, tier=tier, source=source, confidence=conf,
                  status=AnswerStatus.FILLED, option_labels=tuple(labels), rule_id=rule_id,
                  sensitive=sensitive, note=note)


def _final(f: FormField, *, note: str = "", sensitive: bool = False,
           status: Optional[AnswerStatus] = None) -> Answer:
    """The post-tier rule: required -> unknown, optional -> blank_optional."""
    st = status or (AnswerStatus.UNKNOWN if f.required else AnswerStatus.BLANK_OPTIONAL)
    return Answer(field_key=f.key, value=None, tier=AnswerTier.NONE, source="",
                  confidence=0.0, status=st, sensitive=sensitive, note=note)


def _today_iso() -> str:
    return applicant.today_sg().isoformat()


# ---------------------------------------------------------------- tier 1

def _field_map_value(c: Canonical, f: FormField, ctx: ResolveContext) -> Optional[Fit]:
    p = ctx.profile
    pv = lambda path: profile_value(p, path)          # noqa: E731
    if c is Canonical.FIRST_NAME:
        return fit_text(f, pv("identity.legal_first_name"))
    if c is Canonical.LAST_NAME:
        return fit_text(f, pv("identity.legal_last_name"))
    if c in (Canonical.FULL_NAME, Canonical.SELF_ID_NAME):
        return fit_text(f, full_name(p))
    if c is Canonical.PREFERRED_NAME:
        return fit_text(f, pv("identity.preferred_name"))
    if c is Canonical.EMAIL:
        return fit_text(f, pv("contact.email"))
    if c is Canonical.PHONE:
        digits = re.sub(r"\D", "", str(pv("contact.phone_number") or ""))
        return fit_text(f, digits)
    if c is Canonical.PHONE_COUNTRY_CODE:
        cc = str(pv("contact.phone_country_code") or "").strip()
        if not cc:
            return None
        if f.type in CHOICE_TYPES:
            pat = re.compile(re.escape(cc) + r"(?!\d)")
            hits = [o for o in f.options if pat.search(o.label)]
            return _choose(f, hits) if len(hits) == 1 else None
        return fit_text(f, cc)
    if c is Canonical.PHONE_DEVICE_TYPE:
        hits = _match_options(f, ["mobile"])
        return _choose(f, hits) if len(hits) == 1 else fit_text(f, "Mobile")
    if c is Canonical.ADDRESS_LINE1:
        return fit_text(f, pv("contact.address_line1"))
    if c is Canonical.ADDRESS_LINE2:
        return fit_text(f, pv("contact.address_line2"))
    if c is Canonical.CITY:
        return fit_text(f, pv("contact.city"))
    if c is Canonical.POSTAL_CODE:
        return fit_text(f, pv("contact.postal_code"))
    if c is Canonical.COUNTRY:
        names = country_names(pv("contact.country"))
        if not names:
            return None
        if f.type in CHOICE_TYPES:
            hits = _match_options(f, names[:1])
            return _choose(f, hits) if len(hits) == 1 else None
        return fit_text(f, names[0])
    if c is Canonical.LOCATION:
        return fit_text(f, pv("contact.city"))
    if c is Canonical.CURRENT_COMPANY:
        for e in p.get("experience") or []:
            if isinstance(e, dict) and _blank(e.get("end")) and not _blank(e.get("employer")):
                return fit_text(f, e["employer"])
        return None
    if c in (Canonical.LINKEDIN, Canonical.GITHUB, Canonical.PORTFOLIO):
        return fit_text(f, pv(f"links.{c.value}"))
    if c is Canonical.WEBSITE:
        return fit_text(f, pv("links.portfolio") or pv("links.github"))
    if c is Canonical.RESUME:
        return (ctx.resume_path, ()) if ctx.resume_path else None
    if c in EEO_PATHS:
        v = pv(EEO_PATHS[c])
        if _blank(v):
            return None
        if c is Canonical.EEO_HISPANIC:
            if v == "decline":
                return fit_decline(f)
            return fit_bool(f, v == "hispanic_latino")
        if v == "decline":
            return fit_decline(f)
        return fit_enum(f, v, EEO_VALUE_MAP.get(c, {}))
    if c in (Canonical.CONSENT_PRIVACY, Canonical.CONSENT_RETENTION,
             Canonical.CONSENT_TALENT_POOL):
        return fit_bool(f, pv(f"consents.{c.value}"))
    if c is Canonical.TERMS_AGREEMENT:
        return fit_bool(f, pv("consents.privacy_consent"))
    if c is Canonical.SELF_ID_DATE:
        return fit_date(f, _today_iso())
    if c is Canonical.HOW_HEARD:
        v = pv("sourcing.how_heard_default")
        if f.type in CHOICE_TYPES:
            got = fit_text(f, v) if not _blank(v) else None
            if got:
                return got
            hits = _match_options(f, ["career", "careers", "website"])
            if not hits:
                hits = [o for o in f.options if re.search(r"career|website", o.label, re.I)]
            return _choose(f, hits[:1]) if hits else None
        return fit_text(f, v)
    if c is Canonical.PREVIOUS_WORKER:
        return fit_bool(f, declarations.prior_employment(p, ctx.employer_name,
                                                         ctx.employer_aliases))
    return None


def _tier1(f: FormField, ctx: ResolveContext) -> Union[Answer, _Stop, None]:
    c = f.canonical
    if c is None:
        return None
    sensitive = c in SENSITIVE_CANONICALS
    if c is Canonical.COVER_LETTER:
        return None                      # optional -> blank; required -> tier 5 (§7.2)
    fit = _field_map_value(c, f, ctx)
    if fit is None:
        return _Stop(f"field map {c.value}: no value fits", sensitive)
    return _answer(f, fit, AnswerTier.FIELD_MAP, f"field_map:{c.value}", CONF_FIELD_MAP,
                   rule_id=c.value, sensitive=sensitive)


# ---------------------------------------------------------------- tier 2

@dataclass
class _Tier2:
    answer: Optional[Answer] = None
    stop: Optional[_Stop] = None
    sensitive: bool = False              # a sensitive key matched: never tier 5
    note: str = ""


def _tier2(f: FormField, label_norm: str, ctx: ResolveContext,
           rules: QuestionRules) -> _Tier2:
    best, _score = rules.select(label_norm)
    if not best:
        return _Tier2()
    if len(best) > 1:
        return _Tier2(sensitive=any(r.sensitive for r in best),
                      note="ambiguous: " + ", ".join(r.key for r in best))
    r = best[0]
    value = profile_value(ctx.profile, r.key)
    fit = fit_kind(f, r.kind, value, value_map=r.value_map, profile=ctx.profile)
    # TODO(D-70 yes_if): a Yes/No label on an enum key ("Are you a Singapore
    # Citizen?") needs the architect's `yes_if` rule (arch/Q-22-workday-first),
    # not specified when this was built. Until then fit_enum finds no option for
    # it, so a sensitive key stops at unknown below and nothing is guessed.
    if fit is not None:
        return _Tier2(answer=_answer(f, fit, AnswerTier.PROFILE_RULE, f"profile:{r.key}",
                                     CONF_PROFILE, rule_id=r.key, sensitive=r.sensitive),
                      sensitive=r.sensitive)
    if r.sensitive:
        return _Tier2(stop=_Stop(f"profile rule {r.key}: no offered option fits", True),
                      sensitive=True)
    return _Tier2(note=f"profile rule {r.key}: no value fits")


# ---------------------------------------------------------------- tier 3

def _tier3(f: FormField, label_norm: str, ctx: ResolveContext,
           memory: Optional[MemoryLookup]) -> Optional[Answer]:
    if memory is None or not label_norm:
        return None
    raw = None
    for ats in (ctx.ats or "*", "*"):
        try:
            raw = memory(label_norm, f.type.value, ats)
        except Exception:                 # a broken memory row must not end the attempt
            raw = None
        if raw is not None:
            break
    if raw is None:
        return None
    try:
        stored = json.loads(raw)
    except (TypeError, ValueError):
        return None
    fit: Optional[Fit] = None
    if f.type in CHOICE_TYPES:
        wanted = stored if isinstance(stored, list) else [stored]
        if not wanted or not all(isinstance(w, str) for w in wanted):
            return None
        by_norm = {norm_label(o.label): o for o in f.options}
        chosen = [by_norm.get(norm_label(w)) for w in wanted]
        if None in chosen or (f.type in SINGLE_CHOICE and len(chosen) != 1):
            return None
        fit = _choose(f, chosen)
    elif f.type is FieldType.CHECKBOX:
        if stored in ("true", "false", True, False):
            fit = (("true" if stored in ("true", True) else "false"), ())
    elif isinstance(stored, str):
        fit = fit_text(f, stored) if f.type is not FieldType.NUMBER else (
            (stored.strip(), ()) if stored.strip() else None)
    if fit is None:
        return None
    return _answer(f, fit, AnswerTier.MEMORY, f"memory:{label_norm}", CONF_MEMORY,
                   rule_id=label_norm)


# ---------------------------------------------------------------- tiers 4, 5 (WP-P5, WP-P6)

def _tier4(f: FormField, label_norm: str, ctx: ResolveContext):
    """Declarations (§7.5). Returns (Answer or None, is_attestation). A
    classified field always gets its final Answer here (never tier 5)."""
    label = declarations.classify(label_norm, norm_label(f.description))
    if label is None:
        return None, False
    return declarations.answer(label, f, ctx), True


def _tier5(f: FormField, ctx: ResolveContext, backend: Any) -> Optional[Answer]:
    """The local model (WP-P6)."""
    return None


# ---------------------------------------------------------------- the resolver

def resolve_field(f: FormField, ctx: ResolveContext, *, backend: Any, rules: QuestionRules,
                  memory: Optional[MemoryLookup]) -> Answer:
    """One field through the tiers (§7)."""
    if f.type is FieldType.HIDDEN:
        return _final(f, status=AnswerStatus.SKIPPED, note="hidden")
    label_norm = norm_label(f.label)

    # Tier 1. A canonical field belongs to the profile: when the field map has no
    # value, only the owner's memory may still answer it (no rule, no model).
    if f.canonical is not None:
        t1 = _tier1(f, ctx)
        if isinstance(t1, Answer):
            return t1
        if f.canonical is Canonical.COVER_LETTER:
            if not f.required:
                return _final(f, note="cover letter is optional")
            return _tier5(f, ctx, backend) or _final(f, note="no cover letter")
        return _tier3(f, label_norm, ctx, memory) or _final(
            f, note=t1.note if isinstance(t1, _Stop) else "",
            sensitive=isinstance(t1, _Stop) and t1.sensitive)

    t2 = _tier2(f, label_norm, ctx, rules)
    if t2.answer:
        return t2.answer
    if t2.stop:
        return _final(f, note=t2.stop.note, sensitive=True)

    t3 = _tier3(f, label_norm, ctx, memory)
    if t3:
        return t3

    t4, attestation = _tier4(f, label_norm, ctx)
    if t4 is not None:
        return t4

    notes = [n for n in (t2.note,) if n]
    if not t2.sensitive and not attestation:
        t5 = _tier5(f, ctx, backend)
        if t5 is not None:
            return t5
    return _final(f, note="; ".join(notes))


def resolve_all(fields: Sequence[FormField], ctx: ResolveContext, *, backend: Any,
                rules: QuestionRules, memory: Optional[MemoryLookup]) -> dict[str, Answer]:
    """Every field -> exactly one Answer, keyed by field key (§7).

    Alternative inputs (`alt_of`, e.g. Greenhouse `resume_text` beside
    `resume`) are resolved after their primary and skipped when it answers;
    the alternative of an unanswered optional cover letter stays blank too."""
    out: dict[str, Answer] = {}
    by_key = {f.key: f for f in fields}
    primaries = [f for f in fields if not f.alt_of]
    alternatives = [f for f in fields if f.alt_of]
    for f in primaries:
        out[f.key] = resolve_field(f, ctx, backend=backend, rules=rules, memory=memory)
    for f in alternatives:
        prim = out.get(f.alt_of)
        if prim is not None and prim.fills:
            out[f.key] = _final(f, status=AnswerStatus.SKIPPED,
                                note=f"alternative to {f.alt_of}, which is answered")
            continue
        pf = by_key.get(f.alt_of)
        if pf is not None and pf.canonical is Canonical.COVER_LETTER and not f.required:
            out[f.key] = _final(f, note="cover letter is optional")
            continue
        out[f.key] = resolve_field(f, ctx, backend=backend, rules=rules, memory=memory)
    return {f.key: out[f.key] for f in fields}
