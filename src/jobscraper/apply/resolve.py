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
import hashlib
import json
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, Union

import yaml

from .. import applicant
from ..backends import BackendError
from .contracts import (
    CHOICE_TYPES, Answer, AnswerStatus, AnswerTier, Canonical, FieldType, FormField,
    Option, ResolveContext,
)
from . import declarations
from .plan import contains_run, norm_label, phrase_match_tokens, tokens

MemoryLookup = Callable[[str, str, str], Optional[str]]

CONF_FIELD_MAP = 1.0
CONF_PROFILE = 0.95
CONF_MEMORY = 0.95
CONF_DECLARATION = 0.95

TEXT_TYPES = frozenset({FieldType.TEXT, FieldType.TEXTAREA, FieldType.EMAIL, FieldType.PHONE,
                        FieldType.NUMBER, FieldType.URL, FieldType.DATE, FieldType.TYPEAHEAD})
SINGLE_CHOICE = frozenset({FieldType.DROPDOWN, FieldType.RADIO})

KINDS = frozenset({"bool", "enum", "text", "number", "salary", "date", "url", "country",
                   "country_bool"})

# D-75 (questions_design §8.2): `kind: country_bool` answers a right-to-work or
# sponsorship question for whichever country the label names, from these maps.
COUNTRY_BOOL_KEYS = frozenset({"singapore_status.authorised_to_work",
                               "singapore_status.requires_sponsorship"})

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

# D-75 (questions_design §8.2 step 1): extra names a work-rights label may use
# for a country. ISO codes are not aliases except those written here, and the
# token "us" alone is never one ("are you authorised to work for us").
COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "US": ("united states", "united states of america", "u s", "u s a", "usa", "america"),
    "GB": ("uk", "u k", "britain", "great britain", "england"),
    "EU": ("european union", "eu", "eea", "europe"),
    "AE": ("uae", "united arab emirates"),
}
# A label naming no country that asks about where the applicant lives means
# contact.country; any other such label means the job's country.
RESIDENCE_PHRASES = ("where you live", "where you reside", "country of residence",
                     "where you currently live")


def _country_phrases() -> list[tuple[str, tuple[str, ...]]]:
    out = [(code, tuple(tokens(name))) for code, (name, _demonym) in COUNTRIES.items()]
    out += [(code, tuple(tokens(a))) for code, names in COUNTRY_ALIASES.items() for a in names]
    return [(c, t) for c, t in out if t]


_COUNTRY_PHRASES = _country_phrases()


def label_countries(label_norm: str) -> set[str]:
    """The ISO codes (and "EU") a normalised label names, by contiguous token
    phrase: country names plus COUNTRY_ALIASES. Unlike tier-2 synonyms, a
    one-token name matches in a label of any length ("eligible to work in
    canada"). Demonyms are not used."""
    toks = label_norm.split()
    return {code for code, phrase in _COUNTRY_PHRASES if contains_run(toks, phrase)}


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
    # A virtual `yes_if` entry (§7.3.3): key "<parent>#<id>", kind bool; Yes when
    # the parent enum's profile value is one of `yes_values`.
    parent: str = ""
    yes_values: frozenset[str] = frozenset()

    @property
    def is_virtual(self) -> bool:
        return bool(self.parent)

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

    def select(self, label_norm: str, f: Optional[FormField] = None) -> tuple[list[Rule], int]:
        """The top-scoring rules for a label and their score (§7.3.1 selection),
        among the entries a field of this shape may take (§7.3.3). One rule = a
        match; two or more = a tie (tier 2 does not answer)."""
        toks = label_norm.split()
        best, top = [], 0
        for r in self.rules:
            if f is not None and not _candidate(r, f, toks):
                continue
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
        if kind == "country_bool":
            if key not in COUNTRY_BOOL_KEYS:
                raise ValueError(f"{where}: kind country_bool is allowed only on "
                                 + " and ".join(sorted(COUNTRY_BOOL_KEYS)))
            if value_map or e.get("yes_if") is not None:
                raise ValueError(f"{where}: kind country_bool takes no value_map or yes_if")
        sensitive = bool(e.get("sensitive", False))
        rules.append(Rule(key=key, kind=kind, sensitive=sensitive, synonyms=synonyms,
                          exclude=_phrase_list(e.get("exclude"), f"{where}.exclude"),
                          value_map=value_map))
        rules.extend(_yes_if_rules(e, key, kind, sensitive, value_map, seen))
    return QuestionRules(tuple(rules))


_YES_IF_ID = re.compile(r"^[a-z0-9_]+$")


def _yes_if_rules(e: dict, key: str, kind: str, sensitive: bool,
                  value_map: dict[str, tuple[str, ...]], seen: set[str]) -> list[Rule]:
    """The virtual entries of an enum's `yes_if` list (§7.3.3). Any problem
    raises ValueError naming `<key>#<id>`."""
    raw = e.get("yes_if")
    if raw is None:
        return []
    if kind != "enum":
        raise ValueError(f"{key}#?: yes_if is allowed on kind enum only")
    if not isinstance(raw, list):
        raise ValueError(f"{key}#?: yes_if must be a list of rules")
    out = []
    for item in raw:
        rid = item.get("id") if isinstance(item, dict) else None
        name = f"{key}#{rid if isinstance(rid, str) and rid else '?'}"
        if not isinstance(item, dict) or not isinstance(rid, str) or not _YES_IF_ID.match(rid):
            raise ValueError(f"{name}: needs an id of [a-z0-9_]+")
        if name in seen:
            raise ValueError(f"{name}: duplicate id")
        seen.add(name)
        values = item.get("values")
        if not isinstance(values, list) or not values \
                or not all(isinstance(v, str) and v in value_map for v in values):
            raise ValueError(f"{name}: values must be a non-empty subset of value_map's keys")
        synonyms = _phrase_list(item.get("synonyms"), name)
        exclude = _phrase_list(item.get("exclude"), f"{name}.exclude")
        if not synonyms:
            raise ValueError(f"{name}: needs at least one synonym")
        out.append(Rule(key=name, kind="bool", sensitive=sensitive, synonyms=synonyms,
                        exclude=exclude, parent=key, yes_values=frozenset(values)))
    return out


QUESTION_WORDS = frozenset({"are", "is", "do", "does", "have", "has", "will", "would", "can",
                            "were", "was"})


def bool_shaped(f: FormField) -> bool:
    """§7.3.3: a single checkbox, or a dropdown/radio offering exactly one yes
    option, one no option, at most one decline option and nothing else."""
    if f.type is FieldType.CHECKBOX:
        return True
    if f.type not in SINGLE_CHOICE or not f.options:
        return False
    yes = no = dec = 0
    for o in f.options:
        if _is_decline(o.label):
            dec += 1
            continue
        pol = polarity(o.label)
        if pol is True:
            yes += 1
        elif pol is False:
            no += 1
        else:
            return False
    return yes == 1 and no == 1 and dec <= 1


def _candidate(r: Rule, f: FormField, label_toks: Sequence[str]) -> bool:
    """May this entry answer a field of this shape (§7.3.3)?"""
    if bool_shaped(f):
        # plain bool entries + virtual yes_if entries + the D-75 work-rights maps
        return r.kind in ("bool", "country_bool")
    if f.type in CHOICE_TYPES:
        return not r.is_virtual
    if f.type in (FieldType.TEXT, FieldType.TEXTAREA):
        return not r.is_virtual or (bool(label_toks) and label_toks[0] in QUESTION_WORDS)
    return not r.is_virtual


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
        hits = [o for o in f.options
                if not _is_decline(o.label) and polarity(o.label) is value]
        return _choose(f, hits) if len(hits) == 1 else None
    if f.type in (FieldType.TEXT, FieldType.TEXTAREA, FieldType.TYPEAHEAD):
        return ("Yes" if value else "No"), ()
    return None


def _is_decline(label: str) -> bool:
    """A "prefer not to say" option ("I don't wish to answer" is not a No)."""
    toks = tokens(label)
    return any(phrase_match_tokens(p.split(), toks) for p in DECLINE_PHRASES)


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
        # D-70 (§10.5): the account identity in use, so the form's email matches it.
        return fit_text(f, ctx.account_email or pv("contact.email"))
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
    best, _score = rules.select(label_norm, f)
    if not best:
        return _Tier2()
    if len(best) > 1:
        return _Tier2(sensitive=any(r.sensitive for r in best),
                      note="ambiguous: " + ", ".join(r.key for r in best))
    r = best[0]
    if r.kind == "country_bool":
        return _tier2_country_bool(f, label_norm, ctx, r)
    if r.is_virtual:
        # §7.3.3 yes_if: a Yes/No question answered from the parent enum.
        value = profile_value(ctx.profile, r.parent)
        if _blank(value):
            fit = None
        elif value == "decline":
            fit = fit_decline(f)
        else:
            fit = fit_bool(f, str(value) in r.yes_values)
        source = f"profile:{r.parent}"
    else:
        value = profile_value(ctx.profile, r.key)
        fit = fit_kind(f, r.kind, value, value_map=r.value_map, profile=ctx.profile)
        source = f"profile:{r.key}"
    if fit is not None:
        return _Tier2(answer=_answer(f, fit, AnswerTier.PROFILE_RULE, source,
                                     CONF_PROFILE, rule_id=r.key, sensitive=r.sensitive),
                      sensitive=r.sensitive)
    if r.sensitive:
        return _Tier2(stop=_Stop(f"profile rule {r.key}: no offered option fits", True),
                      sensitive=True)
    return _Tier2(note=f"profile rule {r.key}: no value fits")


WORK_RIGHTS_CONFLICT = "work rights differ"     # the note capture reads as reason `conflict`


def work_rights_countries(label_norm: str, ctx: ResolveContext) -> list[str]:
    """The countries a work-rights label asks about (§8.2 steps 1-2): those it
    names; else the applicant's country when it asks where they live; else the
    job's country (`ctx.job_country`, "this country", "where this job is")."""
    named = label_countries(label_norm)
    if named:
        return sorted(named)
    toks = label_norm.split()
    if any(contains_run(toks, p.split()) for p in RESIDENCE_PHRASES):
        home = profile_value(ctx.profile, "contact.country")
        if isinstance(home, str) and home.strip():
            return [home.strip().upper()]
    return [(ctx.job_country or "SG").strip().upper()]


def _tier2_country_bool(f: FormField, label_norm: str, ctx: ResolveContext,
                        r: Rule) -> _Tier2:
    """D-75 (§8.2 steps 3-6): the work-rights map's value for each country the
    label means. Countries that disagree stop the field (never the model);
    options that are not Yes/No leave it to the later tiers (not sensitive)."""
    which = r.key.rsplit(".", 1)[1]
    toks = set(label_norm.split())
    # "Can you work in the US without sponsorship?": authorised and needs none.
    without = (which == "authorised_to_work" and "without" in toks
               and bool(toks & {"sponsor", "sponsorship", "visa"}))
    countries = work_rights_countries(label_norm, ctx)
    values: dict[str, tuple[bool, str]] = {}
    for c in countries:
        v, src = applicant.work_right(ctx.profile, which, c)
        if without:
            v = v and not applicant.work_right(ctx.profile, "requires_sponsorship", c)[0]
        values[c] = (v, src)
    if len({v for v, _src in values.values()}) > 1:
        return _Tier2(stop=_Stop(f"{WORK_RIGHTS_CONFLICT}: " + ", ".join(countries)))
    value, src = values[countries[0]]
    fit = fit_bool(f, value)
    if fit is None:
        return _Tier2(note=f"profile rule {r.key}: no value fits")
    return _Tier2(answer=_answer(f, fit, AnswerTier.PROFILE_RULE, f"profile:{r.key}.{src}",
                                 CONF_PROFILE, rule_id=r.key, sensitive=False))


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


SYSTEM_PROMPT = """You answer one question on a job application for the applicant described below.
Rules:
1. Use only facts in APPLICANT, RESUME or JOB. Never invent an employer, title, date, degree,
   number, skill or tool.
2. If the facts do not settle the answer, answer unknown (choice -1, or unknown true).
3. For a choice question, pick the option the facts support, and copy into "evidence" a short
   exact quote (3-200 characters) from APPLICANT, RESUME or JOB that supports it.
4. For free text, write plain first-person sentences, no greeting or sign-off, within the
   character limit. Mention only skills and experience present in APPLICANT or RESUME.
Return JSON only, matching the schema."""

RULE_ID_LLM = "llm:v1"
CONF_LLM_CHOICE = 0.9
CONF_LLM_TEXT = 0.8
SEED = 7
PROMPT_CHARS = 6000
TEXT_LIMITS = {FieldType.TEXT: 255, FieldType.TEXTAREA: 1500}
COVER_LETTER_LIMIT = 2500


def _llm_kind(f: FormField) -> Optional[str]:
    """choice | multi | number | text, or None when the field is not one the
    model may answer (§7.6 eligibility; a box to tick, a file, an email, a
    phone, a date, a URL or a typeahead stays with tiers 1-4)."""
    if f.canonical is Canonical.COVER_LETTER:
        return "text" if f.required else None
    if f.type in SINGLE_CHOICE:
        return "choice" if f.options else None
    if f.type is FieldType.MULTI_CHOICE:
        return "multi" if f.options else None
    if f.type is FieldType.NUMBER:
        return "number"
    if f.type in (FieldType.TEXT, FieldType.TEXTAREA):
        return "text"
    return None


def _text_limit(f: FormField) -> int:
    if f.max_length:
        return int(f.max_length)
    if f.canonical is Canonical.COVER_LETTER:
        return COVER_LETTER_LIMIT
    return TEXT_LIMITS.get(f.type, 255)


def llm_schema(kind: str, n: int = 0, limit: int = 255) -> dict:
    """The JSON schema sent as `format` (§7.6)."""
    if kind == "choice":
        return {"type": "object", "properties": {
            "choice": {"type": "integer", "minimum": -1, "maximum": n - 1},
            "evidence": {"type": "string", "maxLength": 200}},
            "required": ["choice", "evidence"]}
    if kind == "multi":
        return {"type": "object", "properties": {
            "choices": {"type": "array", "items": {"type": "integer", "minimum": 0,
                                                   "maximum": n - 1},
                        "uniqueItems": True, "maxItems": n},
            "unknown": {"type": "boolean"},
            "evidence": {"type": "string", "maxLength": 200}},
            "required": ["choices", "unknown", "evidence"]}
    if kind == "number":
        return {"type": "object", "properties": {
            "unknown": {"type": "boolean"}, "value": {"type": "number"}},
            "required": ["unknown", "value"]}
    return {"type": "object", "properties": {
        "unknown": {"type": "boolean"}, "text": {"type": "string", "maxLength": limit}},
        "required": ["unknown", "text"]}


def user_prompt(f: FormField, kind: str, ctx: ResolveContext, limit: int) -> str:
    """§7.6 user prompt. Only llm_extract + computed facts from the profile:
    no S value can reach it."""
    facts = applicant.computed_facts(ctx.profile, applicant.today_sg())
    # D-75: the model is always told the standing work rights (not sensitive).
    person = dict(applicant.llm_extract(ctx.profile), computed=facts,
                  work_rights=applicant.work_rights_text(ctx.profile))
    lines = [f"QUESTION: {f.label}", f"HELP: {f.description}",
             f"TYPE: {kind}", f"REQUIRED: {'yes' if f.required else 'no'}"]
    if kind == "text":
        lines.append(f"LIMIT: {limit} characters")
    if kind in ("choice", "multi"):
        lines.append("OPTIONS:")
        lines += [f"{i}. {o.label}" for i, o in enumerate(f.options)]
    lines += ["", "APPLICANT (JSON):", json.dumps(person, ensure_ascii=False),
              "", "RESUME:", (ctx.resume_text or "")[:PROMPT_CHARS],
              "", f"JOB: {ctx.employer_name}", (ctx.jd_text or "")[:PROMPT_CHARS]]
    return "\n".join(lines)


def prompt_hash(system: str, user: str) -> str:
    return hashlib.sha256((system + "\n\n" + user).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- grounding (§7.7)

_DIGIT_COMMA = re.compile(r"(?<=\d),(?=\d)")
_NUMBER_TOKEN = re.compile(r"(?<![A-Za-z0-9])\d[\d,.]*%?(?![A-Za-z0-9])")
_YEAR = re.compile(r"(?<![A-Za-z0-9])(?:19|20)\d\d(?![A-Za-z0-9])")
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
CAPITAL_ALLOW = frozenset({"i", "i'm", "i've", "singapore", "english", *MONTHS, *WEEKDAYS})
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:['’][A-Za-z]+)?")


def corpus_norm(text: str) -> str:
    """Lowercase, whitespace collapsed, "," removed inside digit groups."""
    return " ".join(_DIGIT_COMMA.sub("", text or "").lower().split())


def corpus_text(ctx: ResolveContext) -> str:
    """Profile (non-sensitive) + resume + JD + employer name (§7.7)."""
    return "\n".join([applicant.grounding_text(ctx.profile), ctx.resume_text or "",
                      ctx.jd_text or "", ctx.employer_name or ""])


def _number_norm(tok: str) -> str:
    tok = tok.rstrip(".,").replace(",", "").rstrip("%")
    return tok[:-2] if tok.endswith(".0") else tok


def _corpus_numbers(cnorm: str) -> set[str]:
    return {_number_norm(m.group(0)) for m in _NUMBER_TOKEN.finditer(cnorm)}


def _has_word(cnorm: str, word: str) -> bool:
    return re.search(r"(?<![a-z0-9+#])" + re.escape(word.lower()) + r"(?![a-z0-9+#])",
                     cnorm) is not None


def _term_pattern(term: str) -> re.Pattern:
    body = r"\s+".join(re.escape(p) for p in term.split())
    return re.compile(r"(?<![A-Za-z0-9+#])" + body + r"(?![A-Za-z0-9+#])", re.IGNORECASE)


def _term_in(text: str, term: str, ambiguous: frozenset[str]) -> bool:
    """Whole-token, case-insensitive; an ambiguous token ("go", "c", "r")
    counts only when written not all-lowercase."""
    for m in _term_pattern(term).finditer(text):
        if term.lower() in ambiguous and m.group(0) == m.group(0).lower():
            continue
        return True
    return False


def _dictionary(ctx: ResolveContext) -> list[tuple[str, tuple[str, ...]]]:
    """(term, its alias group) for every alias-group member, profile skill and
    attested skill."""
    out: list[tuple[str, tuple[str, ...]]] = []
    for group in ctx.alias_groups:
        for term in group:
            out.append((term, tuple(group)))
    p = ctx.profile or {}
    for term in list(p.get("skills") or []) + list(p.get("attested_skills") or []):
        if isinstance(term, str) and term.strip():
            group = next((g for g in ctx.alias_groups
                          if any(t.lower() == term.lower() for t in g)), (term,))
            out.append((term, tuple(group)))
    return out


def grounded(kind: str, reply: dict, ctx: ResolveContext, *, n_options: int = 0,
             limit: int = 255, corpus: Optional[str] = None) -> list[str]:
    """The violations of one model reply (§7.7); [] = grounded. Violations
    name only the offending tokens, never a profile value."""
    raw = corpus if corpus is not None else corpus_text(ctx)
    cnorm = corpus_norm(raw)
    v: list[str] = []
    if kind in ("choice", "multi"):
        idx = [reply.get("choice")] if kind == "choice" else list(reply.get("choices") or [])
        if any(not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < n_options
               for i in idx):
            v.append("choice out of range")
        ev = corpus_norm(str(reply.get("evidence") or ""))
        if len(ev) < 3:
            v.append("no evidence quote")
        elif ev not in cnorm:
            v.append("evidence not found: " + ev[:60])
        return v
    if kind == "number":
        val = reply.get("value")
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return ["no number"]
        txt = _int_text(val)
        if not re.search(r"(?<![\d.])" + re.escape(txt) + r"(?![\d]|\.\d)", cnorm):
            v.append(f"number not found: {txt}")
        return v
    # text
    text = str(reply.get("text") or "").strip()
    if not text:
        return ["empty text"]
    if len(text) > limit:
        v.append(f"longer than {limit} characters")
    numbers = _corpus_numbers(cnorm)
    for m in _NUMBER_TOKEN.finditer(text):
        n = _number_norm(m.group(0))
        if n and n not in numbers:
            v.append(f"number {n}")
    for m in _YEAR.finditer(text):
        if m.group(0) not in numbers and f"year {m.group(0)}" not in v \
                and f"number {m.group(0)}" not in v:
            v.append(f"year {m.group(0)}")
    for m in _WORD.finditer(text):
        w = m.group(0)
        if w.lower() in MONTHS and (w.lower() != "may" or w[0].isupper()) \
                and not _has_word(cnorm, w):
            v.append(f"month {w}")
    amb = frozenset(a.lower() for a in ctx.alias_ambiguous)
    seen_terms: set[str] = set()
    for term, group in _dictionary(ctx):
        key = term.lower()
        if key in seen_terms or not _term_in(text, term, amb):
            continue
        seen_terms.add(key)
        if not any(_term_in(raw, g, amb) for g in group):
            v.append(f"term {term}")
    sentence_start = True
    pos = 0
    for m in _WORD.finditer(text):
        between = text[pos:m.start()]
        if pos and re.search(r"[.!?]\s*$|[\r\n]", between):
            sentence_start = True
        w = m.group(0)
        if w[0].isupper() and not sentence_start and w.lower().replace("’", "'") \
                not in CAPITAL_ALLOW and not _has_word(cnorm, w):
            v.append(f"word {w}")
        sentence_start = False
        pos = m.end()
    return list(dict.fromkeys(v))


# ---------------------------------------------------------------- tier 5 (§7.6)

class _Unavailable(Exception):
    pass


def _ask(backend: Any, user: str, kind: str, schema: dict, max_tokens: int,
         temperature: float) -> Optional[dict]:
    """One model call. None = the reply was not the JSON asked for."""
    try:
        comp = backend.complete(SYSTEM_PROMPT, user, max_tokens, format=schema,
                                temperature=temperature, seed=SEED)
    except BackendError as exc:
        raise _Unavailable() from exc
    try:
        data = json.loads(comp.text)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _is_unknown(kind: str, reply: dict) -> bool:
    if kind == "choice":
        return reply.get("choice") == -1
    return bool(reply.get("unknown"))


def _llm_failed(f: FormField, ungrounded: bool, note: str, model: str, phash: str) -> Answer:
    if f.required:
        st = AnswerStatus.UNGROUNDED if ungrounded else AnswerStatus.UNKNOWN
    else:
        st = AnswerStatus.BLANK_OPTIONAL
    return Answer(field_key=f.key, value=None, tier=AnswerTier.LLM if ungrounded
                  else AnswerTier.NONE, source="llm" if ungrounded else "",
                  confidence=0.0, status=st, rule_id=RULE_ID_LLM if ungrounded else "",
                  model=model, prompt_hash=phash, note=note[:300])


def _tier5(f: FormField, ctx: ResolveContext, backend: Any) -> Optional[Answer]:
    """The local model (§7.6), checked by `grounded` (§7.7). None when the
    field is not one the model may answer; otherwise a final Answer."""
    kind = _llm_kind(f)
    if kind is None:
        return None
    model = str(getattr(backend, "model_id", "") or "")
    if backend is None or not getattr(backend, "available", False):
        return _llm_failed(f, False, "model unavailable", model, "")
    limit = _text_limit(f)
    n = len(f.options)
    schema = llm_schema(kind, n, limit)
    user = user_prompt(f, kind, ctx, limit)
    phash = prompt_hash(SYSTEM_PROMPT, user)
    corpus = corpus_text(ctx)
    try:
        if kind == "text":
            return _tier5_text(f, ctx, backend, user, schema, limit, corpus, model)
        replies = []
        for temp in (0, 0.7):
            r = _ask(backend, user, kind, schema, 200, temp)
            if r is None:
                return _llm_failed(f, False, "model reply was not the JSON asked for",
                                   model, phash)
            if _is_unknown(kind, r):
                return _llm_failed(f, False, "model: the facts do not settle it", model, phash)
            bad = grounded(kind, r, ctx, n_options=n, corpus=corpus)
            if bad:
                return _llm_failed(f, True, "ungrounded: " + "; ".join(bad), model, phash)
            replies.append(r)
    except _Unavailable:
        return _llm_failed(f, False, "model unavailable", model, phash)
    a, b = replies
    if kind == "choice":
        same = a["choice"] == b["choice"]
        chosen = [f.options[a["choice"]]]
    elif kind == "multi":
        same = set(a["choices"]) == set(b["choices"])
        chosen = [f.options[i] for i in sorted(set(a["choices"]))]
        if not chosen:
            return _llm_failed(f, False, "model chose nothing", model, phash)
    else:
        same = a["value"] == b["value"]
    if not same:
        return _llm_failed(f, False, "model runs disagree", model, phash)
    if kind == "number":
        fit = (_int_text(a["value"]), ())
    else:
        fit = _choose(f, chosen)
    return Answer(field_key=f.key, value=fit[0], tier=AnswerTier.LLM, source="llm",
                  confidence=CONF_LLM_CHOICE, status=AnswerStatus.FILLED,
                  option_labels=tuple(fit[1]), rule_id=RULE_ID_LLM, model=model,
                  prompt_hash=phash)


def _tier5_text(f: FormField, ctx: ResolveContext, backend: Any, user: str, schema: dict,
                limit: int, corpus: str, model: str) -> Answer:
    """One call at temperature 0.3; one retry naming the violations."""
    prompt = user
    bad: list[str] = []
    for attempt in range(2):
        if attempt:
            prompt = user + "\n\nPREVIOUS ANSWER WAS REJECTED BECAUSE: " + "; ".join(bad)
        phash = prompt_hash(SYSTEM_PROMPT, prompt)
        r = _ask(backend, prompt, "text", schema, limit // 2 + 100, 0.3)
        if r is None:
            bad = ["reply was not the JSON asked for"]
            continue
        if _is_unknown("text", r):
            return _llm_failed(f, False, "model: the facts do not settle it", model, phash)
        bad = grounded("text", r, ctx, limit=limit, corpus=corpus)
        if not bad:
            note = "cover letter text" if f.canonical is Canonical.COVER_LETTER else ""
            return Answer(field_key=f.key, value=str(r.get("text")).strip(),
                          tier=AnswerTier.LLM, source="llm", confidence=CONF_LLM_TEXT,
                          status=AnswerStatus.FILLED, rule_id=RULE_ID_LLM, model=model,
                          prompt_hash=phash, note=note)
    return _llm_failed(f, True, "ungrounded: " + "; ".join(bad), model, phash)


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
    if t2.stop:                       # a sensitive no-fit, or D-75 countries that disagree
        return _final(f, note=t2.stop.note, sensitive=t2.stop.sensitive)

    t3 = _tier3(f, label_norm, ctx, memory)
    if t3:
        return t3

    t4, attestation = _tier4(f, label_norm, ctx)
    if t4 is not None:
        return t4

    if not t2.sensitive and not attestation:
        t5 = _tier5(f, ctx, backend)
        if t5 is not None:
            if t2.note and not t5.fills:          # keep why tier 2 passed it on
                t5.note = f"{t2.note}; {t5.note}" if t5.note else t2.note
            return t5
    return _final(f, note=t2.note)


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
