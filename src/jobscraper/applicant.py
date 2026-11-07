"""The applicant profile: the facts an application form asks for (PRD F-10, F-11).

`data/applicant.yaml` (gitignored) holds who the owner is for an employer's
form: legal name, contact, Singapore work status, availability, pay, education,
experience, consents and the standing declarations (D-55). The owner fills it
from `config/applicant.example.yaml` (a public template with placeholders only)
and, from M21, through the Profile form, which saves through `save` here.

Foundation module (apply_design §2, §5): the web routers, the apply stage and
the orchestrator all read the profile, so this file imports nothing above
`config`. It never calls a model and never writes a log line with a value in it.

What it owns:
  - load / save / validate (§5.2 rules, every error names its dotted path)
  - normalise (Q-36, D-78): the owner types "Male", "non-binary", `no`, "per
    month", an unquoted 2020-03-15 or "Mar 2020"; `load` turns each into the
    canonical form once, so the resolver, the tailor and the form API only ever
    see canonical values
  - missing_for_apply / completeness (F-11: auto-apply refuses an incomplete
    profile, and the Profile tab shows a meter)
  - llm_extract (the allow-list of non-sensitive facts a model may see, §5.3)
  - grounding_text (the profile half of the tier-5 grounding corpus, §7.7)
  - redaction_values (the strings a log line must never carry, NF-02/NF-09)
  - computed_facts (experience months/years and graduation year, D-68 A-4)

Sensitive ("S") paths (§5.3) never reach a prompt and never reach a log.
"""
from __future__ import annotations

import calendar
import copy
import datetime as _dt
import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

from .apply.contracts import EXTRA_KEY_PATTERN, QuestionKind
from .config import ROOT

APPLICANT_PATH_DEFAULT = "data/applicant.yaml"          # config paths.applicant overrides
SCHEMA_VERSION = 1

# The original-resume names profile/resume_ingest.find_resume looks for. Copied,
# not imported: this is a foundation module and may not reach into a stage.
RESUME_NAMES = ("resume.pdf", "resume.docx")

# Singapore time for "today" (computed facts). A fixed offset, because tzdata is
# not guaranteed on Windows and Singapore has no daylight saving.
SGT = _dt.timezone(_dt.timedelta(hours=8))


class ApplicantError(Exception):
    """The profile file cannot be read, or a save was refused (invalid)."""

    # The etag of the bytes that could not be read (`load_with_etag`); "" when
    # there were none. Set by `load_with_etag`, so a caller can still report it.
    etag: str = ""

    def __init__(self, message: str, errors: Optional[list["FieldError"]] = None):
        super().__init__(message)
        self.errors = list(errors or [])


@dataclass(frozen=True)
class FieldError:
    path: str          # dotted, list index in brackets: "education[0].end"
    message: str       # plain English, names the rule


# --------------------------------------------------------------------------
# Paths the apply gate and the meter count (§5.2)
# --------------------------------------------------------------------------

REQUIRED_PATHS: tuple[str, ...] = (
    "identity.legal_first_name", "identity.legal_last_name",
    "contact.email", "contact.phone_country_code", "contact.phone_number",
    "contact.city", "contact.country",
    "singapore_status.residency_status",
    # D-75: the two work-rights maps are not here: they always have an answer
    # (the country's key, else `default`, else the standing answer; work_rights).
    "availability.notice_period_days", "availability.earliest_start_date",
    "pay.expected_salary.amount",
    "education",
    "consents.privacy_consent", "consents.certify_true",
)

RECOMMENDED_PATHS: tuple[str, ...] = (
    "contact.address_line1", "contact.postal_code",
    "singapore_status.ns_status", "singapore_status.race",
    "links.linkedin", "experience", "skills", "languages",
    "sourcing.how_heard_default", "identity.date_of_birth",
)

RESUME_PATH = "documents.resume"     # how a missing resume file is reported

# §5.3. A path here, or under a prefix ending ".", is sensitive. `contact.*`
# is sensitive except city and country (handled in `is_sensitive`).
SENSITIVE_PATHS: frozenset[str] = frozenset({
    "identity.date_of_birth", "identity.gender",
    "singapore_status.residency_status", "singapore_status.ns_status",
    "singapore_status.ord_date", "singapore_status.race",
    "singapore_status.race_other", "singapore_status.religion",
    "singapore_status.marital_status", "singapore_status.nric_last4",
})
SENSITIVE_PREFIXES: tuple[str, ...] = ("us_self_id", "declarations", "contact")
CONTACT_NOT_SENSITIVE = frozenset({"contact.city", "contact.country"})

# §5.3 allow-list: what a model may see. A dotted path; "x.*" = the whole block.
LLM_ALLOW: tuple[str, ...] = (
    "education", "experience", "skills", "attested_skills", "languages", "links",
    "availability", "pay.expected_salary", "sourcing.how_heard_default",
    "contact.city", "contact.country", "singapore_status.work_pass",
    "singapore_status.authorised_to_work", "singapore_status.requires_sponsorship",
)


def is_sensitive(path: str) -> bool:
    """True for an S path (§5.3). `path` is dotted, list indices allowed
    ("declarations.holdings[0]")."""
    bare = re.sub(r"\[\d+\]", "", path)
    if bare in CONTACT_NOT_SENSITIVE:
        return False
    if bare in SENSITIVE_PATHS:
        return True
    return any(bare == p or bare.startswith(p + ".") for p in SENSITIVE_PREFIXES)


# --------------------------------------------------------------------------
# Enums and formats (§5.2, §5.4)
# --------------------------------------------------------------------------

ENUMS: dict[str, tuple[str, ...]] = {
    "identity.name_order": ("western", "surname_first"),
    "identity.gender": ("male", "female", "non_binary", "decline"),
    "singapore_status.residency_status": ("citizen", "pr", "foreigner"),
    "singapore_status.work_pass": ("none_required", "ep", "s_pass", "dp", "ltvp_loc",
                                   "student_pass", "other"),
    "singapore_status.ns_status": ("completed", "serving", "exempted", "not_applicable"),
    "singapore_status.race": ("chinese", "malay", "indian", "eurasian", "other", "decline"),
    "singapore_status.marital_status": ("single", "married", "decline"),
    "us_self_id.eeo_gender": ("male", "female", "non_binary", "decline"),
    "us_self_id.eeo_race_ethnicity": ("asian", "black", "hispanic_latino", "white",
                                      "two_or_more", "native_american",
                                      "pacific_islander", "decline"),
    "us_self_id.veteran_status": ("not_a_veteran", "veteran", "decline"),
    "us_self_id.disability_status": ("no", "yes", "decline"),
    "pay.expected_salary.period": ("monthly", "annual"),
    "pay.current_salary.period": ("monthly", "annual"),
    "declarations.health_disclosure": ("decline",),
}
LIST_ENUMS: dict[str, tuple[str, ...]] = {
    "education[].grade_type": ("gpa", "cap", "honours_class"),
    "languages[].spoken": ("native", "fluent", "professional", "basic"),
    "languages[].written": ("native", "fluent", "professional", "basic"),
}

# Q-36 (D-78): natural spellings that are not just a case/space/hyphen variant of
# an allowed value. Keys are already lower-case with spaces and hyphens turned
# into underscores ("per month" -> "per_month"); a "." is dropped too ("p.a.").
_PERIOD_SYNONYMS: dict[str, str] = {
    "month": "monthly", "per_month": "monthly", "monthly": "monthly", "mth": "monthly",
    "year": "annual", "yearly": "annual", "annual": "annual",
    "per_annum": "annual", "pa": "annual",
}
ENUM_SYNONYMS: dict[str, dict[str, str]] = {
    "pay.expected_salary.period": _PERIOD_SYNONYMS,
    "pay.current_salary.period": _PERIOD_SYNONYMS,
}
# Any enum that has a "decline" value reads these as "decline" (same key form).
_DECLINE_SYNONYMS = frozenset({"prefer_not_to_say", "rather_not_say"})
# A quoted word for a plain boolean field (an unquoted yes/no is already a bool).
_TRUE_WORDS = frozenset({"yes", "true"})
_FALSE_WORDS = frozenset({"no", "false"})
# Month names for "Mar 2020" / "March 2020" (the first three letters, or "sept").
_MONTH_NAMES: dict[str, int] = {
    name: i for i, names in enumerate(
        (("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
         ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
         ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
         ("dec", "december")), start=1)
    for name in names}

BOOLS: tuple[str, ...] = (
    "availability.willing_to_relocate",
    "pay.expected_salary.negotiable",
    "consents.privacy_consent", "consents.data_retention_consent",
    "consents.talent_pool_opt_in", "consents.certify_true",
    "declarations.pep", "declarations.conflict_audit_independence",
    "declarations.shareholding_in_company", "declarations.relatives_at_company",
    "declarations.criminal_record", "declarations.bankruptcy",
    "declarations.regulatory_disciplinary", "declarations.non_compete",
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
COUNTRY_CODE_RE = re.compile(r"^\+\d{1,3}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
ISO2_RE = re.compile(r"^[A-Z]{2}$")
COUNTRY_PICK_MESSAGE = "is not a country code. Pick a country from the list"
URL_RE = re.compile(r"^https?://\S+$")

# Q-71 G1: every ISO 3166-1 alpha-2 code with its English short name. Static data
# (no dependency, nothing to install): the form's country pick-list and the
# check that contact.country, nationality and the work-rights map keys are real
# countries. A free-text box let "Singapore" be cut to "SI" (Slovenia) and saved.
COUNTRY_NAMES: dict[str, str] = {
    "AD": "Andorra",
    "AE": "United Arab Emirates",
    "AF": "Afghanistan",
    "AG": "Antigua and Barbuda",
    "AI": "Anguilla",
    "AL": "Albania",
    "AM": "Armenia",
    "AO": "Angola",
    "AQ": "Antarctica",
    "AR": "Argentina",
    "AS": "American Samoa",
    "AT": "Austria",
    "AU": "Australia",
    "AW": "Aruba",
    "AX": "Åland Islands",
    "AZ": "Azerbaijan",
    "BA": "Bosnia and Herzegovina",
    "BB": "Barbados",
    "BD": "Bangladesh",
    "BE": "Belgium",
    "BF": "Burkina Faso",
    "BG": "Bulgaria",
    "BH": "Bahrain",
    "BI": "Burundi",
    "BJ": "Benin",
    "BL": "Saint Barthélemy",
    "BM": "Bermuda",
    "BN": "Brunei",
    "BO": "Bolivia",
    "BQ": "Caribbean Netherlands",
    "BR": "Brazil",
    "BS": "Bahamas",
    "BT": "Bhutan",
    "BV": "Bouvet Island",
    "BW": "Botswana",
    "BY": "Belarus",
    "BZ": "Belize",
    "CA": "Canada",
    "CC": "Cocos (Keeling) Islands",
    "CD": "Congo (Democratic Republic)",
    "CF": "Central African Republic",
    "CG": "Congo (Republic)",
    "CH": "Switzerland",
    "CI": "Côte d'Ivoire",
    "CK": "Cook Islands",
    "CL": "Chile",
    "CM": "Cameroon",
    "CN": "China",
    "CO": "Colombia",
    "CR": "Costa Rica",
    "CU": "Cuba",
    "CV": "Cape Verde",
    "CW": "Curaçao",
    "CX": "Christmas Island",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DE": "Germany",
    "DJ": "Djibouti",
    "DK": "Denmark",
    "DM": "Dominica",
    "DO": "Dominican Republic",
    "DZ": "Algeria",
    "EC": "Ecuador",
    "EE": "Estonia",
    "EG": "Egypt",
    "EH": "Western Sahara",
    "ER": "Eritrea",
    "ES": "Spain",
    "ET": "Ethiopia",
    "FI": "Finland",
    "FJ": "Fiji",
    "FK": "Falkland Islands",
    "FM": "Micronesia",
    "FO": "Faroe Islands",
    "FR": "France",
    "GA": "Gabon",
    "GB": "United Kingdom",
    "GD": "Grenada",
    "GE": "Georgia",
    "GF": "French Guiana",
    "GG": "Guernsey",
    "GH": "Ghana",
    "GI": "Gibraltar",
    "GL": "Greenland",
    "GM": "Gambia",
    "GN": "Guinea",
    "GP": "Guadeloupe",
    "GQ": "Equatorial Guinea",
    "GR": "Greece",
    "GS": "South Georgia and the South Sandwich Islands",
    "GT": "Guatemala",
    "GU": "Guam",
    "GW": "Guinea-Bissau",
    "GY": "Guyana",
    "HK": "Hong Kong",
    "HM": "Heard Island and McDonald Islands",
    "HN": "Honduras",
    "HR": "Croatia",
    "HT": "Haiti",
    "HU": "Hungary",
    "ID": "Indonesia",
    "IE": "Ireland",
    "IL": "Israel",
    "IM": "Isle of Man",
    "IN": "India",
    "IO": "British Indian Ocean Territory",
    "IQ": "Iraq",
    "IR": "Iran",
    "IS": "Iceland",
    "IT": "Italy",
    "JE": "Jersey",
    "JM": "Jamaica",
    "JO": "Jordan",
    "JP": "Japan",
    "KE": "Kenya",
    "KG": "Kyrgyzstan",
    "KH": "Cambodia",
    "KI": "Kiribati",
    "KM": "Comoros",
    "KN": "Saint Kitts and Nevis",
    "KP": "North Korea",
    "KR": "South Korea",
    "KW": "Kuwait",
    "KY": "Cayman Islands",
    "KZ": "Kazakhstan",
    "LA": "Laos",
    "LB": "Lebanon",
    "LC": "Saint Lucia",
    "LI": "Liechtenstein",
    "LK": "Sri Lanka",
    "LR": "Liberia",
    "LS": "Lesotho",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "LY": "Libya",
    "MA": "Morocco",
    "MC": "Monaco",
    "MD": "Moldova",
    "ME": "Montenegro",
    "MF": "Saint Martin (French part)",
    "MG": "Madagascar",
    "MH": "Marshall Islands",
    "MK": "North Macedonia",
    "ML": "Mali",
    "MM": "Myanmar",
    "MN": "Mongolia",
    "MO": "Macao",
    "MP": "Northern Mariana Islands",
    "MQ": "Martinique",
    "MR": "Mauritania",
    "MS": "Montserrat",
    "MT": "Malta",
    "MU": "Mauritius",
    "MV": "Maldives",
    "MW": "Malawi",
    "MX": "Mexico",
    "MY": "Malaysia",
    "MZ": "Mozambique",
    "NA": "Namibia",
    "NC": "New Caledonia",
    "NE": "Niger",
    "NF": "Norfolk Island",
    "NG": "Nigeria",
    "NI": "Nicaragua",
    "NL": "Netherlands",
    "NO": "Norway",
    "NP": "Nepal",
    "NR": "Nauru",
    "NU": "Niue",
    "NZ": "New Zealand",
    "OM": "Oman",
    "PA": "Panama",
    "PE": "Peru",
    "PF": "French Polynesia",
    "PG": "Papua New Guinea",
    "PH": "Philippines",
    "PK": "Pakistan",
    "PL": "Poland",
    "PM": "Saint Pierre and Miquelon",
    "PN": "Pitcairn Islands",
    "PR": "Puerto Rico",
    "PS": "Palestine",
    "PT": "Portugal",
    "PW": "Palau",
    "PY": "Paraguay",
    "QA": "Qatar",
    "RE": "Réunion",
    "RO": "Romania",
    "RS": "Serbia",
    "RU": "Russia",
    "RW": "Rwanda",
    "SA": "Saudi Arabia",
    "SB": "Solomon Islands",
    "SC": "Seychelles",
    "SD": "Sudan",
    "SE": "Sweden",
    "SG": "Singapore",
    "SH": "Saint Helena",
    "SI": "Slovenia",
    "SJ": "Svalbard and Jan Mayen",
    "SK": "Slovakia",
    "SL": "Sierra Leone",
    "SM": "San Marino",
    "SN": "Senegal",
    "SO": "Somalia",
    "SR": "Suriname",
    "SS": "South Sudan",
    "ST": "São Tomé and Príncipe",
    "SV": "El Salvador",
    "SX": "Sint Maarten",
    "SY": "Syria",
    "SZ": "Eswatini",
    "TC": "Turks and Caicos Islands",
    "TD": "Chad",
    "TF": "French Southern Territories",
    "TG": "Togo",
    "TH": "Thailand",
    "TJ": "Tajikistan",
    "TK": "Tokelau",
    "TL": "Timor-Leste",
    "TM": "Turkmenistan",
    "TN": "Tunisia",
    "TO": "Tonga",
    "TR": "Türkiye",
    "TT": "Trinidad and Tobago",
    "TV": "Tuvalu",
    "TW": "Taiwan",
    "TZ": "Tanzania",
    "UA": "Ukraine",
    "UG": "Uganda",
    "UM": "US Minor Outlying Islands",
    "US": "United States",
    "UY": "Uruguay",
    "UZ": "Uzbekistan",
    "VA": "Vatican City",
    "VC": "Saint Vincent and the Grenadines",
    "VE": "Venezuela",
    "VG": "British Virgin Islands",
    "VI": "US Virgin Islands",
    "VN": "Vietnam",
    "VU": "Vanuatu",
    "WF": "Wallis and Futuna",
    "WS": "Samoa",
    "YE": "Yemen",
    "YT": "Mayotte",
    "ZA": "South Africa",
    "ZM": "Zambia",
    "ZW": "Zimbabwe",
}
NRIC_LAST4_RE = re.compile(r"^\d{3}[A-Z]$")
# A full NRIC/FIN anywhere in the file is refused (§5.2): letter, 7 digits, letter.
NRIC_ANYWHERE_RE = re.compile(r"(?<![A-Za-z0-9])[STFGMstfgm]\d{7}[A-Za-z](?![A-Za-z0-9])")
DAY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")

# Date fields and the formats each accepts ("day" = YYYY-MM-DD, "month" = YYYY-MM).
DATE_FIELDS: dict[str, tuple[str, ...]] = {
    "identity.date_of_birth": ("day",),
    "singapore_status.ord_date": ("month",),
    "availability.earliest_start_date": ("day",),
}
# education[] / experience[] start and end: YYYY-MM per the template; a full
# day is accepted too (computed_facts reads both, D-68 A-4).
ENTRY_DATE_FORMATS = ("month", "day")


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _get(profile: Any, path: str) -> Any:
    """The value at a dotted path, or None. No list indices (REQUIRED_PATHS
    have none)."""
    cur = profile
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _empty(v: Any) -> bool:
    return v is None or (isinstance(v, (str, list, dict, tuple)) and len(v) == 0) \
        or (isinstance(v, str) and not v.strip())


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _date_text(v: Any) -> Any:
    """YAML turns an unquoted 2026-01-05 into a date; read it back as text."""
    if isinstance(v, _dt.datetime):
        return v.date().isoformat()
    if isinstance(v, _dt.date):
        return v.isoformat()
    return v


def _parse_date(v: Any, formats: Iterable[str]) -> Optional[tuple[int, int, Optional[int]]]:
    """(year, month, day|None) if `v` is a real date in one of `formats`."""
    v = _date_text(v)
    if not isinstance(v, str):
        return None
    for fmt in formats:
        m = (DAY_RE if fmt == "day" else MONTH_RE).match(v.strip())
        if not m:
            continue
        y, mo = int(m.group(1)), int(m.group(2))
        if not 1 <= mo <= 12:
            return None
        if fmt == "day":
            d = int(m.group(3))
            if not 1 <= d <= calendar.monthrange(y, mo)[1]:
                return None
            return (y, mo, d)
        return (y, mo, None)
    return None


def _fmt_names(formats: Iterable[str]) -> str:
    return " or ".join("YYYY-MM-DD" if f == "day" else "YYYY-MM" for f in formats)


def _walk(value: Any, path: str = ""):
    """Yield (dotted path, leaf value) for every leaf in the profile."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, value


# --------------------------------------------------------------------------
# Normalisation (Q-36, D-78)
# --------------------------------------------------------------------------

def _canon_enum(v: Any, allowed: tuple[str, ...],
                synonyms: Optional[dict[str, str]] = None) -> Any:
    """The canonical spelling of an enum value, or `v` untouched when it still
    does not map (validate then reports it).

    Accepted on top of the exact spelling: any case and surrounding spaces
    ("Male "), spaces or hyphens for underscores ("non-binary", "not applicable"),
    the path's synonyms (pay periods), "prefer not to say" for "decline", and a
    YAML boolean for a yes/no enum (`disability_status: no` is read by YAML as
    False, not "no")."""
    if isinstance(v, bool):
        return ("yes" if v else "no") if {"yes", "no"} <= set(allowed) else v
    if not isinstance(v, str):
        return v
    token = re.sub(r"[\s\-_]+", "_", v.strip().lower()).strip("_")
    if token in allowed:
        return token
    if synonyms:
        hit = synonyms.get(token) or synonyms.get(token.replace(".", ""))
        if hit in allowed:
            return hit
    if "decline" in allowed and token in _DECLINE_SYNONYMS:
        return "decline"
    return v


def _canon_bool(v: Any) -> Any:
    """True/False for a quoted "yes"/"true"/"no"/"false" (any case, spaces
    around); anything else is returned as it is."""
    if isinstance(v, str):
        word = v.strip().lower()
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
    return v


_YEAR_MONTH_RE = re.compile(r"^(\d{4})/(\d{1,2})$")                 # 2020/03
_MONTH_YEAR_RE = re.compile(r"^(\d{1,2})/(\d{4})$")                 # 03/2020
_NAME_YEAR_RE = re.compile(r"^([A-Za-z]{3,9})\.?[\s,\-]*(\d{4})$")  # Mar 2020, March 2020
_DAY_MONTH_YEAR_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")   # 15/03/2020


def _canon_date(v: Any, formats: tuple[str, ...]) -> Any:
    """The canonical text of a date field, or `v` untouched when it does not map.

    `formats` is what the field accepts ("month" = YYYY-MM, "day" = YYYY-MM-DD).
    A YAML date or datetime (an unquoted 2020-03-15) becomes its ISO day, or
    YYYY-MM when the field is month-only. Text: an already valid value is kept
    (trimmed); a day given to a month-only field is cut to the month; for a
    month field "2020/03", "03/2020", "Mar 2020" and "March 2020" read as
    YYYY-MM; for a day field "15/03/2020" reads as day/month/year (Singapore
    order) and a real date. Other slash forms ("03/04/20", "2020/03/04") are
    ambiguous and stay as typed, so validate reports them."""
    if isinstance(v, _dt.datetime):
        v = v.date()
    if isinstance(v, _dt.date):
        return v.isoformat() if "day" in formats else f"{v.year:04d}-{v.month:02d}"
    if not isinstance(v, str):
        return v
    s = v.strip()
    if _parse_date(s, formats) is not None:
        return s
    if "month" in formats:
        day = _parse_date(s, ("day",))
        if day is not None:                        # "day" is not accepted: cut to the month
            return f"{day[0]:04d}-{day[1]:02d}"
        year = month = None
        m = _YEAR_MONTH_RE.match(s)
        if m:
            year, month = int(m.group(1)), int(m.group(2))
        else:
            m = _MONTH_YEAR_RE.match(s)
            if m:
                year, month = int(m.group(2)), int(m.group(1))
            else:
                m = _NAME_YEAR_RE.match(s)
                if m and m.group(1).lower() in _MONTH_NAMES:
                    year, month = int(m.group(2)), _MONTH_NAMES[m.group(1).lower()]
        if year is not None and 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
    if "day" in formats:
        m = _DAY_MONTH_YEAR_RE.match(s)
        if m:
            iso = f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
            if _parse_date(iso, ("day",)) is not None:
                return iso
    return v


def _set_at(profile: dict, path: str, fn) -> None:
    """Replace the value at a dotted `path` with `fn(value)`, in place, when
    every step down to it is a mapping and the key is there."""
    *parents, leaf = path.split(".")
    cur: Any = profile
    for part in parents:
        cur = cur.get(part) if isinstance(cur, dict) else None
    if isinstance(cur, dict) and leaf in cur:
        cur[leaf] = fn(cur[leaf])


def normalise(profile: Any) -> Any:
    """A copy of `profile` with every enum, plain boolean and date field in its
    canonical form (`_canon_enum`, `_canon_bool`, `_canon_date`); the argument is
    not changed. A value that still does not map is left as it is, for validate
    to report. Idempotent. `load`, `validate` and `save` all call it, so a
    profile typed by hand, edited in the form or built in code reads the same
    everywhere. Numbers, text and URLs are not touched.

    Entry dates (`education[]`, `experience[]`) keep a full day when one is given
    (D-68 A-4: computed_facts reads it); only a month-only field such as
    `singapore_status.ord_date` is cut to YYYY-MM."""
    if not isinstance(profile, dict):
        return profile
    out = copy.deepcopy(profile)
    for path, allowed in ENUMS.items():
        _set_at(out, path,
                lambda v, a=allowed, s=ENUM_SYNONYMS.get(path): _canon_enum(v, a, s))
    for path in BOOLS:
        _set_at(out, path, _canon_bool)
    for block in ("authorised_to_work", "requires_sponsorship"):
        m = _get(out, f"singapore_status.{block}")
        if isinstance(m, dict):
            for k in m:
                m[k] = _canon_bool(m[k])
    for path, formats in DATE_FIELDS.items():
        _set_at(out, path, lambda v, f=formats: _canon_date(v, f))
    for spec, allowed in LIST_ENUMS.items():
        lst_name, key = spec.split("[].")
        entries = out.get(lst_name)
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and key in entry:
                entry[key] = _canon_enum(entry[key], allowed)
    for lst_name in ("education", "experience"):
        entries = out.get(lst_name)
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict):
                for key in ("start", "end"):
                    if key in entry:
                        entry[key] = _canon_date(entry[key], ENTRY_DATE_FORMATS)
    return out


# --------------------------------------------------------------------------
# Load / save
# --------------------------------------------------------------------------

def _etag_of(data: Optional[bytes]) -> str:
    """The first 16 hex of the SHA-256 of `data`; "" for no file (None)."""
    return "" if data is None else hashlib.sha256(data).hexdigest()[:16]


def load_with_etag(path: str | os.PathLike) -> tuple[dict, str]:
    """(the profile at `path`, its etag), both taken from ONE read of the file
    (Q-30 F6). Reading the profile and the etag in two steps lets a hand edit or
    a CLI write land between them: the form would hold the old profile with the
    new etag, and its next save would overwrite that edit without a 409.

    The profile is normalised (`normalise`) and {} for a file that does not
    exist (etag ""). Raises ApplicantError on bytes that cannot be read or
    parsed or are not a mapping; the error's `.etag` is then the etag of the
    bytes that were read, so the Profile tab can still show it."""
    p = Path(path)
    data: Optional[bytes] = None
    try:
        try:
            data = p.read_bytes()
        except FileNotFoundError:
            return {}, ""
        except OSError as exc:
            raise ApplicantError(f"cannot read {p.name}: {type(exc).__name__}") from exc
        try:
            parsed = yaml.safe_load(data.decode("utf-8"))
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ApplicantError(f"cannot read {p.name}: {type(exc).__name__}") from exc
        if parsed is None:
            return {}, _etag_of(data)
        if not isinstance(parsed, dict):
            raise ApplicantError(f"{p.name} must be a mapping, got {type(parsed).__name__}")
        return normalise(parsed), _etag_of(data)
    except ApplicantError as exc:
        exc.etag = _etag_of(data)
        raise


def load(path: str | os.PathLike) -> dict:
    """The profile at `path`, normalised (`normalise`); {} if the file does not
    exist. Raises ApplicantError on YAML that cannot be read or is not a mapping."""
    return load_with_etag(path)[0]


COMMENTED_BACKUP_NAME = "applicant.commented-backup.yaml"   # matches data/applicant*.yaml (gitignored)
PREVIOUS_NAME = "applicant.prev.yaml"                       # ditto: the rolling previous copy


def etag(path: str | os.PathLike) -> str:
    """The lost-update guard (questions_design §3.1): the first 16 hex of the
    SHA-256 of the file's bytes, "" when the file is absent. The Profile form
    and the Questions card send it back; a mismatch is a 409, nothing saved.
    When the profile is read too, use `load_with_etag` (one read, one answer)."""
    p = Path(path)
    try:
        data = p.read_bytes()
    except FileNotFoundError:
        return ""
    return _etag_of(data)


def has_comments(path: str | os.PathLike) -> bool:
    """True when a line of the file starts (after blanks) with "#": a save
    would drop it, since PyYAML does not keep comments (§5.1)."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(line.lstrip().startswith("#") for line in text.splitlines())


def commented_backup_path(path: str | os.PathLike) -> Path:
    """Where the one-time copy with comments goes: beside the profile."""
    return Path(path).with_name(COMMENTED_BACKUP_NAME)


def previous_path(path: str | os.PathLike) -> Path:
    """Where the rolling previous copy goes: beside the profile, so it stays
    inside the gitignored `data/applicant*.yaml` set (NF-01)."""
    return Path(path).with_name(PREVIOUS_NAME)


def _keep_previous(p: Path, new_bytes: bytes) -> None:
    """Q-30 F7: before a write replaces `p`, keep what is there as
    `applicant.prev.yaml` (atomically, so a failed copy never costs the copy
    already kept). One rolling copy: the version before the last change.

    Nothing is rolled when the write would not change the file: the owner who
    presses Save twice must not push the real previous version out."""
    try:
        old = p.read_bytes()
    except FileNotFoundError:
        return                                  # a first save: nothing to keep
    if old == new_bytes:
        return
    prev = previous_path(p)
    if prev == p:
        return
    # ".yaml" ends the temp name too, so a crash that leaves it is still gitignored.
    fd, tmp = tempfile.mkstemp(prefix=prev.stem + ".", suffix=".yaml", dir=str(prev.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(old)
        os.replace(tmp, prev)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(path: str | os.PathLike, profile: dict, *, keep_commented_copy: bool = True,
         keep_previous: bool = True) -> None:
    """Normalise (`normalise`, Q-36), validate, then write atomically (tempfile in
    the same folder + os.replace). The file always holds the canonical spellings.

    Raises ApplicantError (with `.errors`) and writes nothing when the profile
    is invalid. Key order is kept (`sort_keys=False`); YAML comments are not.
    So the first save over a file that has comments first copies it to
    `applicant.commented-backup.yaml` (once: an existing copy is never
    overwritten), and the owner keeps their notes (questions_design §3.1).

    Every save that changes the file also keeps the version it replaces as
    `applicant.prev.yaml` (`keep_previous`, Q-30 F7). The form PUTs the whole
    profile, so a partial one (a UI bug, a stale tab) is valid and replaces the
    file; the file is gitignored, so git has no copy either (NF-01)."""
    profile = normalise(profile)
    errors = validate(profile)
    if errors:
        raise ApplicantError(f"{len(errors)} invalid field(s): "
                             + ", ".join(e.path for e in errors), errors)
    text = yaml.safe_dump(profile, sort_keys=False, allow_unicode=True)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if keep_commented_copy and p.is_file() and has_comments(p):
        backup = commented_backup_path(p)
        if not backup.exists():
            shutil.copy2(p, backup)
    if keep_previous:
        _keep_previous(p, text.encode("utf-8"))
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------
# Validation (§5.2)
# --------------------------------------------------------------------------

def validate(profile: dict) -> list[FieldError]:
    """Every rule in apply_design §5.2. Empty values are not errors here (a
    required one shows up in `missing_for_apply`); a value that is present
    must be well-formed. Messages name the rule and never repeat the value.

    Enum values are checked after `normalise` (Q-36), so "Male" or `no` pass and
    only a value that still maps to nothing is reported, with the allowed list."""
    errs: list[FieldError] = []

    def err(path: str, message: str) -> None:
        errs.append(FieldError(path, message))

    if not isinstance(profile, dict):
        return [FieldError("", "the profile must be a mapping")]
    profile = normalise(profile)

    version = profile.get("version")
    if version is not None and version != SCHEMA_VERSION:
        err("version", f"must be {SCHEMA_VERSION}")

    for block in ("identity", "contact", "singapore_status", "us_self_id", "availability",
                  "pay", "links", "documents", "sourcing", "consents", "declarations"):
        v = profile.get(block)
        if v is not None and not isinstance(v, dict):
            err(block, "must be a mapping")
    for block in ("education", "experience", "languages"):
        v = profile.get(block)
        if v is not None and not isinstance(v, list):
            err(block, "must be a list")

    # contact
    email = _get(profile, "contact.email")
    if not _empty(email) and not (isinstance(email, str) and EMAIL_RE.match(email.strip())):
        err("contact.email", "must be an email address (name@domain.tld)")
    # D-70 (§10.5): an optional second address, used only when an ATS says the
    # main one is already registered. Same format, and never the same address.
    backup = _get(profile, "contact.backup_email")
    if not _empty(backup):
        if not (isinstance(backup, str) and EMAIL_RE.match(backup.strip())):
            err("contact.backup_email", "must be an email address (name@domain.tld)")
        elif isinstance(email, str) and backup.strip().lower() == email.strip().lower():
            err("contact.backup_email", "must differ from contact.email")
    country = _get(profile, "contact.country")
    if not _empty(country) and country not in COUNTRY_NAMES:
        err("contact.country", COUNTRY_PICK_MESSAGE)
    postal = _get(profile, "contact.postal_code")
    if not _empty(postal) and country == "SG":
        if not re.fullmatch(r"\d{6}", str(postal).strip()):
            err("contact.postal_code", "must be exactly 6 digits in Singapore")
    cc = _get(profile, "contact.phone_country_code")
    if not _empty(cc) and not (isinstance(cc, str) and COUNTRY_CODE_RE.match(cc.strip())):
        err("contact.phone_country_code", "must be + followed by 1-3 digits, e.g. +65")
    phone = _get(profile, "contact.phone_number")
    if not _empty(phone):
        text = str(phone)
        if not re.fullmatch(r"[\d ]+", text):
            err("contact.phone_number", "must contain digits and spaces only")
        elif cc == "+65" and not re.fullmatch(r"[3689]\d{7}", text.replace(" ", "")):
            err("contact.phone_number",
                "a Singapore (+65) number has 8 digits starting with 3, 6, 8 or 9")
    nat = _get(profile, "singapore_status.nationality")
    if not _empty(nat) and nat not in COUNTRY_NAMES:
        err("singapore_status.nationality", COUNTRY_PICK_MESSAGE)

    # enums
    for path, allowed in ENUMS.items():
        v = _get(profile, path)
        if not _empty(v) and v not in allowed:
            err(path, "must be one of: " + ", ".join(allowed))
    for spec, allowed in LIST_ENUMS.items():
        lst_name, key = spec.split("[].")
        for i, entry in enumerate(profile.get(lst_name) or []):
            if isinstance(entry, dict) and not _empty(entry.get(key)) \
                    and entry.get(key) not in allowed:
                err(f"{lst_name}[{i}].{key}", "must be one of: " + ", ".join(allowed))

    # booleans
    for path in BOOLS:
        v = _get(profile, path)
        if v is not None and not isinstance(v, bool):
            err(path, "must be true or false")
    for block in ("authorised_to_work", "requires_sponsorship"):
        m = _get(profile, f"singapore_status.{block}")
        if m is None:
            continue
        if not isinstance(m, dict):
            err(f"singapore_status.{block}", "must map country codes to true/false")
            continue
        for k, v in m.items():
            if not (isinstance(k, str) and (ISO2_RE.match(k) or k == WORK_RIGHTS_DEFAULT)):
                err(f"singapore_status.{block}",
                    "keys must be 2-letter ISO country codes or default")
            elif k != WORK_RIGHTS_DEFAULT and k not in COUNTRY_NAMES:
                err(f"singapore_status.{block}", COUNTRY_PICK_MESSAGE)
            elif v is not None and not isinstance(v, bool):
                err(f"singapore_status.{block}.{k}", "must be true or false")

    # pay
    for which in ("expected_salary", "current_salary"):
        sal = _get(profile, f"pay.{which}")
        if sal is None:
            continue
        if not isinstance(sal, dict):
            err(f"pay.{which}", "must be a mapping with amount, currency and period")
            continue
        amt = sal.get("amount")
        # 0 is the template's "not filled yet" (missing_for_apply reports it);
        # anything else must be a positive whole number.
        if amt is not None and not (_is_int(amt) and amt >= 0):
            err(f"pay.{which}.amount", "must be a positive whole number")
        cur = sal.get("currency")
        if not _empty(cur) and not (isinstance(cur, str) and CURRENCY_RE.match(cur)):
            err(f"pay.{which}.currency", "must be a 3-letter currency code, e.g. SGD")
    mpy = _get(profile, "pay.months_per_year")
    if mpy is not None and not (_is_int(mpy) and 12 <= mpy <= 14):
        err("pay.months_per_year", "must be a whole number from 12 to 14")

    # availability
    npd = _get(profile, "availability.notice_period_days")
    if npd is not None and not (_is_int(npd) and npd >= 0):
        err("availability.notice_period_days", "must be a whole number of days, 0 or more")
    trav = _get(profile, "availability.willing_to_travel_pct")
    if trav is not None and not (_is_int(trav) and 0 <= trav <= 100):
        err("availability.willing_to_travel_pct", "must be a whole number from 0 to 100")

    # dates
    for path, formats in DATE_FIELDS.items():
        v = _get(profile, path)
        if not _empty(v) and _parse_date(v, formats) is None:
            err(path, f"must be a date as {_fmt_names(formats)}")

    # links
    links = profile.get("links")
    if isinstance(links, dict):
        for k, v in links.items():
            if k == "other":
                if v is None:
                    continue
                if not isinstance(v, list):
                    err("links.other", "must be a list of URLs")
                    continue
                for i, u in enumerate(v):
                    if not (isinstance(u, str) and URL_RE.match(u.strip())):
                        err(f"links.other[{i}]", "must start with http:// or https://")
            elif not _empty(v) and not (isinstance(v, str) and URL_RE.match(v.strip())):
                err(f"links.{k}", "must start with http:// or https://")

    # NRIC: last four only, and never a full NRIC anywhere in the file
    last4 = _get(profile, "singapore_status.nric_last4")
    if not _empty(last4) and not (isinstance(last4, str) and NRIC_LAST4_RE.match(last4)):
        err("singapore_status.nric_last4",
            "must be empty or the last 4 characters only (3 digits and a letter)")
    for path, v in _walk(profile):
        if isinstance(v, str) and NRIC_ANYWHERE_RE.search(v):
            err(path, "looks like a full NRIC/FIN: never store the full number")

    # education / experience entries
    for lst, need in (("education", ("institution", "degree")),
                      ("experience", ("employer", "title"))):
        for i, entry in enumerate(profile.get(lst) or []):
            base = f"{lst}[{i}]"
            if not isinstance(entry, dict):
                err(base, "must be a mapping")
                continue
            for k in need:
                if _empty(entry.get(k)):
                    err(f"{base}.{k}", "must not be empty")
            parsed = {}
            for k in ("start", "end"):
                v = entry.get(k)
                if _empty(v):
                    continue
                d = _parse_date(v, ENTRY_DATE_FORMATS)
                if d is None:
                    err(f"{base}.{k}", f"must be a date as {_fmt_names(ENTRY_DATE_FORMATS)}")
                else:
                    parsed[k] = d
            if "start" in parsed and "end" in parsed:
                s, e = parsed["start"], parsed["end"]
                if (s[0], s[1], s[2] or 1) > (e[0], e[1], e[2] or 31):
                    err(f"{base}.end", "must not be before start")

    for k in ("holdings", "relatives_employers"):
        v = _get(profile, f"declarations.{k}")
        if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            err(f"declarations.{k}", "must be a list of company names")
    for k in ("skills", "attested_skills"):
        v = profile.get(k)
        if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            err(k, "must be a list of words or phrases")

    errs.extend(validate_extra(profile.get("extra")))
    return errs


# --------------------------------------------------------------------------
# `extra:` - the owner's answers to questions employers asked (F-13, §6.1)
# --------------------------------------------------------------------------

EXTRA_KEY_RE = re.compile(EXTRA_KEY_PATTERN)
EXTRA_KINDS: tuple[str, ...] = tuple(k.value for k in QuestionKind)
EXTRA_TEXT_MAX = 2000
EXTRA_DATE_FORMATS = ("day", "month")
# Question metadata (employer text, or the owner's own labels): readable in a
# log line, unlike the answers themselves (questions_design §11).
EXTRA_META_FIELDS = frozenset({"labels", "title", "description", "seen", "kind", "sensitive"})


def _str_list(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _extra_answer_errors(kind: str, ans: dict, base: str,
                         scoped_only: bool = False) -> list[FieldError]:
    """`value` / `picks` / `seen` of one answer (an entry, or one by_employer
    override) checked for its kind. `base` is the dotted path of `ans`.
    `scoped_only`: an entry whose choice was answered for one employer only
    (D-76): its base `picks` may be empty, and then only the overrides apply."""
    out: list[FieldError] = []
    value = ans.get("value")
    if kind in ("choice", "multi"):
        if value is not None:
            out.append(FieldError(f"{base}.value",
                                  "must be empty for a choice: the answer is in picks"))
        picks, seen = ans.get("picks"), ans.get("seen")
        ok = True
        for name, lst in (("picks", picks), ("seen", seen)):
            if lst is not None and not _str_list(lst):
                out.append(FieldError(f"{base}.{name}", "must be a list of option labels"))
                ok = False
        if ok:
            if kind == "choice" and not picks and not scoped_only:
                out.append(FieldError(f"{base}.picks", "must name at least one option"))
            elif set(picks or []) - set(seen or []):
                out.append(FieldError(f"{base}.picks", "must be options that are also in seen"))
        return out
    if value is None:
        return out
    if kind == "yes_no" and not isinstance(value, bool):
        out.append(FieldError(f"{base}.value", "must be true or false"))
    elif kind == "text":
        if not isinstance(value, str):
            out.append(FieldError(f"{base}.value", "must be text"))
        elif len(value) > EXTRA_TEXT_MAX:
            out.append(FieldError(f"{base}.value",
                                  f"must be at most {EXTRA_TEXT_MAX} characters"))
    elif kind == "date" and _parse_date(value, EXTRA_DATE_FORMATS) is None:
        out.append(FieldError(f"{base}.value",
                              f"must be a date as {_fmt_names(EXTRA_DATE_FORMATS)}"))
    elif kind == "number" and (isinstance(value, bool)
                               or not isinstance(value, (int, float))):
        out.append(FieldError(f"{base}.value", "must be a number"))
    return out


def extra_entry_errors(key: Any, entry: Any) -> list[FieldError]:
    """Every §6.1 rule for one `extra` entry. Tier 3 skips an entry with any
    error (questions_design §11), so this is shared with the resolver."""
    base = f"extra.{key}"
    if not (isinstance(key, str) and EXTRA_KEY_RE.match(key)):
        return [FieldError(base, "keys must be lowercase letters, digits and _, "
                                 "starting with a letter (2-40 characters)")]
    if not isinstance(entry, dict):
        return [FieldError(base, "must be a mapping")]
    out: list[FieldError] = []
    kind = entry.get("kind")
    if kind not in EXTRA_KINDS:
        out.append(FieldError(f"{base}.kind", "must be one of: " + ", ".join(EXTRA_KINDS)))
    for name in ("title", "description"):
        v = entry.get(name)
        if v is not None and not isinstance(v, str):
            out.append(FieldError(f"{base}.{name}", "must be text"))
    labels = entry.get("labels")
    if not (_str_list(labels) and labels and all(x.strip() for x in labels)):
        out.append(FieldError(f"{base}.labels", "must be a non-empty list of question labels"))
    sens = entry.get("sensitive")
    if sens is not None and not isinstance(sens, bool):
        out.append(FieldError(f"{base}.sensitive", "must be true or false"))
    if kind not in EXTRA_KINDS:
        return out
    by_emp = entry.get("by_employer")
    out.extend(_extra_answer_errors(kind, entry, base,
                                    scoped_only=isinstance(by_emp, dict) and bool(by_emp)))
    if by_emp is None:
        return out
    if not isinstance(by_emp, dict):
        out.append(FieldError(f"{base}.by_employer",
                              "must map employer names to answers"))
        return out
    for emp, ans in by_emp.items():
        where = f"{base}.by_employer.{emp}"
        if not (isinstance(emp, str) and emp.strip()):
            out.append(FieldError(f"{base}.by_employer", "employer names must not be empty"))
        elif not isinstance(ans, dict):
            out.append(FieldError(where, "must be a mapping with value, picks and seen"))
        else:
            out.extend(_extra_answer_errors(kind, ans, where))
    return out


def validate_extra(extra: Any) -> list[FieldError]:
    """The `extra:` block (§6.1). Absent or empty is fine."""
    if extra is None:
        return []
    if not isinstance(extra, dict):
        return [FieldError("extra", "must be a mapping")]
    out: list[FieldError] = []
    for key, entry in extra.items():
        out.extend(extra_entry_errors(key, entry))
    return out


# --------------------------------------------------------------------------
# Completeness (F-11)
# --------------------------------------------------------------------------

# Q-71 G3: the two required consents count as filled only when True. A "No"
# is an answer, but an application cannot be sent on it: auto-apply would start,
# then stop at the consent / terms box (fail-closed, but a wasted run).
CONSENTS_MUST_BE_YES = ("consents.privacy_consent", "consents.certify_true")


def _filled(profile: dict, path: str) -> bool:
    if path == "education":
        return any(isinstance(e, dict) and not _empty(e.get("institution"))
                   and not _empty(e.get("degree")) and not _empty(e.get("end"))
                   for e in (profile.get("education") or []))
    v = _get(profile, path)
    if path == "pay.expected_salary.amount":
        return _is_int(v) and v > 0            # the template's 0 is "not filled"
    if path in CONSENTS_MUST_BE_YES:
        return v is True                       # "No" here only stops the run at the box
    return not _empty(v)


def resume_file(profile: dict, resume_dir: str | os.PathLike | None = None) -> Optional[Path]:
    """The resume file to upload on the original-resume path: `documents.resume`
    when set (relative = from the project root, then from `resume_dir`), else
    `<resume_dir>/resume.pdf` or `resume.docx` (the profile stage's names).
    None if no such file exists."""
    rdir = Path(resume_dir) if resume_dir else ROOT / "data"
    named = _get(profile, "documents.resume")
    if not _empty(named):
        p = Path(str(named))
        for cand in ([p] if p.is_absolute() else [ROOT / p, rdir / p]):
            if cand.is_file():
                return cand
        return None
    for name in RESUME_NAMES:
        if (rdir / name).is_file():
            return rdir / name
    return None


def _named_file(profile: dict, path: str, resume_dir: str | os.PathLike | None) -> Optional[Path]:
    """The file `profile[path]` names (relative = from the project root, then
    from `resume_dir`), or None when unset or not a file."""
    named = _get(profile, path)
    if _empty(named):
        return None
    p = Path(str(named))
    rdir = Path(resume_dir) if resume_dir else ROOT / "data"
    for cand in ([p] if p.is_absolute() else [ROOT / p, rdir / p]):
        if cand.is_file():
            return cand
    return None


def documents_status(profile: dict, resume_dir: str | os.PathLike | None = None) -> dict:
    """What the Files group shows (Q-71 G4): for the resume and the transcript,
    `{name, size, modified}` of the file in use, or None. `modified` is ISO 8601
    in UTC. Only the file name is returned, never a path: the owner's folder
    layout is nobody's business, and the page must not echo it."""
    profile = profile or {}

    def info(p: Optional[Path]) -> Optional[dict]:
        if p is None:
            return None
        try:
            st = p.stat()
        except OSError:
            return None
        when = _dt.datetime.fromtimestamp(st.st_mtime, tz=_dt.timezone.utc)
        return {"name": p.name, "size": st.st_size,
                "modified": when.isoformat(timespec="seconds")}

    return {"resume": info(resume_file(profile, resume_dir)),
            "transcript": info(_named_file(profile, "documents.transcript", resume_dir))}


def missing_for_apply(profile: dict, resume_dir: str | os.PathLike | None = None) -> list[str]:
    """REQUIRED_PATHS that are empty, as dotted paths, plus "documents.resume"
    when no resume file is found. Auto-apply refuses while this is non-empty."""
    out = [p for p in REQUIRED_PATHS if not _filled(profile or {}, p)]
    if resume_file(profile or {}, resume_dir) is None:
        out.append(RESUME_PATH)
    return out


def completeness(profile: dict) -> tuple[int, int]:
    """(filled, needed) over REQUIRED_PATHS + RECOMMENDED_PATHS: the meter."""
    paths = REQUIRED_PATHS + RECOMMENDED_PATHS
    return sum(1 for p in paths if _filled(profile or {}, p)), len(paths)


# --------------------------------------------------------------------------
# The Profile form's schema (F-11, questions_design §3.2): one source of truth
# --------------------------------------------------------------------------

FORM_KINDS = frozenset({"text", "email", "phone_cc", "digits", "int", "date", "month", "bool",
                        "enum", "country", "url", "list_text", "list_url", "entries", "salary",
                        "country_bool_map", "fixed"})


@dataclass(frozen=True)
class FormItem:
    """One widget of Profile -> Application details. `path` is the full dotted
    path ("contact.email"); for kind "entries" it is the list ("education") and
    `sub` holds the fields of one entry, with paths relative to it."""
    path: str
    label: str                                   # the exact UI text
    kind: str                                    # one of FORM_KINDS
    options: tuple[tuple[str, str], ...] = ()    # (value, label) for enum / fixed
    help: str = ""
    sub: tuple["FormItem", ...] = ()
    # Rendering hints (lane U): a salary that may be null ("I don't have one";
    # None = not required), a multi-line text box, one entry's name ("Add School"),
    # the sentence a fixed answer shows.
    nullable: Optional[bool] = None
    multiline: bool = False
    entry_label: str = ""
    fixed_text: str = ""


@dataclass(frozen=True)
class FormGroup:
    id: str
    title: str
    items: tuple[FormItem, ...]
    note: str = ""


def _enum_opts(path: str, labels: Optional[dict[str, str]] = None) -> tuple[tuple[str, str], ...]:
    """(value, label) for an ENUMS path. Without `labels`: "decline" is
    "Prefer not to say", any other value is capitalised with "_" read as a space."""
    allowed = ENUMS.get(path) or LIST_ENUMS.get(path) or ()
    out = []
    for v in allowed:
        if labels and v in labels:
            out.append((v, labels[v]))
        elif v == "decline":
            out.append((v, "Prefer not to say"))
        else:
            out.append((v, v.replace("_", " ").capitalize()))
    return tuple(out)


_I = FormItem
_COUNTRY_MAP_HELP = "Your answer for every country. Add a country only if it's different there."
_LEVELS = {"native": "Native", "fluent": "Fluent", "professional": "Professional",
           "basic": "Basic"}

FORM: tuple[FormGroup, ...] = (
    FormGroup("identity", "Name", (
        _I("identity.legal_first_name", "Legal first name", "text"),
        _I("identity.legal_last_name", "Legal last name", "text"),
        _I("identity.preferred_name", "Preferred name", "text"),
        _I("identity.name_order", "Name order", "enum", _enum_opts(
            "identity.name_order", {"western": "First name first",
                                    "surname_first": "Surname first"})),
        _I("identity.pronouns", "Pronouns", "text"),
        _I("identity.date_of_birth", "Date of birth", "date"),
        _I("identity.gender", "Gender", "enum", _enum_opts(
            "identity.gender", {"male": "Male", "female": "Female",
                                "non_binary": "Non-binary"})),
    )),
    FormGroup("contact", "Contact", (
        _I("contact.email", "Email for applications", "email",
           help="Used for every application and site account."),
        _I("contact.backup_email", "Backup email", "email",
           help="Used only when a site says the main address already has an account."),
        _I("contact.phone_country_code", "Phone country code", "phone_cc"),
        _I("contact.phone_number", "Phone number", "digits"),
        _I("contact.address_line1", "Address line 1", "text"),
        _I("contact.address_line2", "Address line 2", "text"),
        _I("contact.postal_code", "Postal code", "digits"),
        _I("contact.city", "City", "text"),
        _I("contact.country", "Country", "country"),
    )),
    FormGroup("singapore_status", "Work status", (
        _I("singapore_status.nationality", "Nationality", "country"),
        _I("singapore_status.residency_status", "Residency status", "enum", _enum_opts(
            "singapore_status.residency_status",
            {"citizen": "Singapore Citizen", "pr": "Singapore Permanent Resident",
             "foreigner": "Foreigner"})),
        _I("singapore_status.work_pass", "Work pass", "enum", _enum_opts(
            "singapore_status.work_pass",
            {"none_required": "None needed", "ep": "Employment Pass", "s_pass": "S Pass",
             "dp": "Dependant's Pass", "ltvp_loc": "LTVP with Letter of Consent",
             "student_pass": "Student's Pass", "other": "Other"})),
        _I("singapore_status.authorised_to_work", "Right to work", "country_bool_map",
           help=_COUNTRY_MAP_HELP),
        _I("singapore_status.requires_sponsorship", "Needs visa sponsorship",
           "country_bool_map", help=_COUNTRY_MAP_HELP),
        _I("singapore_status.ns_status", "National Service", "enum", _enum_opts(
            "singapore_status.ns_status",
            {"completed": "Completed", "serving": "Serving", "exempted": "Exempted",
             "not_applicable": "Not applicable"})),
        _I("singapore_status.ord_date", "ORD date", "month"),
        _I("singapore_status.race", "Race", "enum", _enum_opts(
            "singapore_status.race",
            {"chinese": "Chinese", "malay": "Malay", "indian": "Indian",
             "eurasian": "Eurasian", "other": "Other"})),
        _I("singapore_status.race_other", "Race, if other", "text"),
        _I("singapore_status.religion", "Religion", "text", help="Type your religion, or “decline” to not say."),
        _I("singapore_status.marital_status", "Marital status", "enum", _enum_opts(
            "singapore_status.marital_status", {"single": "Single", "married": "Married"})),
        _I("singapore_status.nric_last4", "NRIC, last 4 characters", "text",
           help="Only the last 4, such as 123A. Never the full NRIC."),
    )),
    FormGroup("us_self_id", "US equal-employment questions", (
        _I("us_self_id.eeo_gender", "Gender", "enum", _enum_opts(
            "us_self_id.eeo_gender", {"male": "Male", "female": "Female",
                                      "non_binary": "Non-binary"})),
        _I("us_self_id.eeo_race_ethnicity", "Race or ethnicity", "enum",
           _enum_opts("us_self_id.eeo_race_ethnicity", {
               "asian": "Asian", "black": "Black or African American",
               "hispanic_latino": "Hispanic or Latino", "white": "White",
               "two_or_more": "Two or more races",
               "native_american": "American Indian or Alaska Native",
               "pacific_islander": "Native Hawaiian or Pacific Islander"})),
        _I("us_self_id.veteran_status", "Veteran status", "enum",
           _enum_opts("us_self_id.veteran_status", {
               "not_a_veteran": "Not a veteran", "veteran": "Veteran"})),
        _I("us_self_id.disability_status", "Disability status", "enum",
           _enum_opts("us_self_id.disability_status", {
               "no": "No, I don't have a disability",
               "yes": "Yes, I have a disability"})),
    )),
    FormGroup("availability", "Availability", (
        _I("availability.notice_period_days", "Notice period, in days", "int"),
        _I("availability.earliest_start_date", "Earliest start date", "date"),
        _I("availability.willing_to_relocate", "Willing to relocate", "bool"),
        _I("availability.willing_to_travel_pct", "Willing to travel, % of the time", "int"),
    )),
    FormGroup("pay", "Pay", (
        _I("pay.expected_salary", "Expected salary", "salary",
           _enum_opts("pay.expected_salary.period",
                      {"monthly": "per month", "annual": "per year"}), nullable=False),
        _I("pay.current_salary", "Current salary", "salary",
           _enum_opts("pay.current_salary.period",
                      {"monthly": "per month", "annual": "per year"}), nullable=True),
        _I("pay.months_per_year", "Months of pay per year", "int",
           help="13 if you get the AWS (Annual Wage Supplement, a 13th-month bonus)."),
    )),
    FormGroup("education", "Education", (
        _I("education", "Education", "entries", sub=(
            _I("institution", "School", "text"),
            _I("degree", "Degree", "text"),
            _I("major", "Major", "text"),
            _I("minor", "Minor", "text"),
            _I("start", "Start", "month"),
            _I("end", "End, or expected end", "month"),
            _I("grade_type", "Grade type", "enum", _enum_opts(
                "education[].grade_type",
                {"gpa": "GPA", "cap": "CAP", "honours_class": "Honours class"})),
            _I("grade", "Grade", "text"),
            _I("grade_scale", "Out of", "text"),
        ), entry_label="School"),
    )),
    FormGroup("experience", "Experience", (
        _I("experience", "Experience", "entries", sub=(
            _I("employer", "Employer", "text"),
            _I("title", "Job title", "text"),
            _I("start", "Start", "month"),
            _I("end", "End", "month", help="Leave it empty if you still work here."),
            _I("location", "Location", "text"),
            _I("description", "What you did", "text", multiline=True),
        ), entry_label="Job"),
    )),
    FormGroup("skills_languages", "Skills and languages", (
        _I("skills", "Skills", "list_text"),
        _I("attested_skills", "Skills you confirmed", "list_text",
           help="Added when you click “I have this” in the resume tailor."),
        _I("languages", "Languages", "entries", sub=(
            _I("language", "Language", "text"),
            _I("spoken", "Spoken", "enum", _enum_opts("languages[].spoken", _LEVELS)),
            _I("written", "Written", "enum", _enum_opts("languages[].written", _LEVELS)),
        ), entry_label="Language"),
    )),
    FormGroup("links", "Links", (
        _I("links.linkedin", "LinkedIn", "url"),
        _I("links.github", "GitHub", "url"),
        _I("links.portfolio", "Portfolio", "url"),
        _I("links.other", "Other links", "list_url"),
    )),
    FormGroup("documents", "Files", (
        _I("documents.resume", "Resume file", "text",
           help="Leave empty to use data/resume.pdf or data/resume.docx."),
        _I("documents.transcript", "Transcript file", "text"),
    )),
    FormGroup("sourcing", "Sourcing", (
        _I("sourcing.how_heard_default", "How you heard about a job", "text"),
    )),
    FormGroup("consents", "Consents", (
        _I("consents.privacy_consent",
           "I consent to employers processing my application data", "bool"),
        _I("consents.data_retention_consent",
           "Employers may keep my data for future roles", "bool"),
        _I("consents.talent_pool_opt_in", "Add me to talent pools", "bool"),
        _I("consents.certify_true",
           "I certify the information I give is true and complete", "bool"),
    )),
    FormGroup("declarations", "Declarations", (
        _I("declarations.pep", "Are you a politically exposed person, or a family member "
                               "or close associate of one?", "bool"),
        _I("declarations.conflict_audit_independence",
           "Do you have an audit or independence conflict with an employer?", "bool"),
        _I("declarations.shareholding_in_company",
           "Do you hold shares or a financial interest in the employers you apply to?", "bool"),
        _I("declarations.holdings", "Companies you hold shares in", "list_text"),
        _I("declarations.relatives_at_company",
           "Do relatives of yours work at the employers you apply to?", "bool"),
        _I("declarations.relatives_employers", "Employers where a relative works", "list_text"),
        _I("declarations.criminal_record",
           "Have you ever been convicted of a criminal offence?", "bool"),
        _I("declarations.bankruptcy", "Have you ever been bankrupt?", "bool"),
        _I("declarations.regulatory_disciplinary",
           "Have you ever faced regulatory or disciplinary action?", "bool"),
        _I("declarations.non_compete",
           "Are you bound by a non-compete or similar agreement?", "bool"),
        _I("declarations.health_disclosure", "Health questions", "fixed",
           (("decline", "Always “Prefer not to say”"),),
           fixed_text="Always “Prefer not to say”"),
    ), note="Your standing answers. Change any that stop being true."),
    # Rendered from the profile, not from items: one row per `extra` entry (§3.2
    # group 15), then every leaf no item above covers, read-only (group 16).
    FormGroup("extra", "Answers you gave to application questions", ()),
    FormGroup("other", "Other keys in your file", (),
              note="These keys aren't in the form. They're kept as they are. "
                   "Edit them in data/applicant.yaml."),
)


def _under(path: str, paths: Iterable[str]) -> bool:
    """True when one of `paths` is `path` or lies inside it ("pay.expected_salary"
    covers "pay.expected_salary.amount")."""
    return any(p == path or p.startswith(path + ".") for p in paths)


# Q-71 G2: rendering hints that live beside FORM, not in its tuples, so the
# declarations group (edited on other branches) stays free of merge conflicts.
# Each is optional in the item JSON: a client that ignores them still works.
#
# YES_NO_CONTROL: a bool item whose path starts with one of these (a trailing
# "." = a prefix) or equals one is drawn as Yes / No radios (`control:
# "yes_no"`), not as a switch: the label is a question, and a switch reads as a
# setting. Consents keep the switch (their labels are statements).
YES_NO_CONTROL: tuple[str, ...] = ("declarations.", "availability.willing_to_relocate")
# NULLABLE_BOOL: Yes/No items where "not set" is a real answer (D-91: null =
# "ask me"), so the form offers a Clear link (`nullable_bool: true`).
NULLABLE_BOOL: frozenset[str] = frozenset({"declarations.willing_to_sign_nda"})
# SHOW_WHEN: a follow-up field matters only when another has one of `values`.
# Emitted as `show_when: {path, values}`; the form hides the item only when the
# condition is false and the item is empty and has no error (never wipes data).
SHOW_WHEN: dict[str, dict[str, Any]] = {
    "singapore_status.race_other": {"path": "singapore_status.race", "values": ["other"]},
    "declarations.holdings": {"path": "declarations.shareholding_in_company",
                              "values": [True]},
    "declarations.relatives_employers": {"path": "declarations.relatives_at_company",
                                         "values": [True]},
    "singapore_status.ord_date": {"path": "singapore_status.ns_status",
                                  "values": ["completed", "serving"]},
}
# AUTOCOMPLETE: HTML autocomplete tokens (WCAG 1.3.5). Absent = the client's
# default ("off"). The backup email is "off" on purpose: browsers would fill the
# main address into it.
AUTOCOMPLETE: dict[str, str] = {
    "identity.legal_first_name": "given-name", "identity.legal_last_name": "family-name",
    "identity.preferred_name": "nickname", "identity.date_of_birth": "bday",
    "contact.email": "email", "contact.backup_email": "off",
    "contact.phone_country_code": "tel-country-code", "contact.phone_number": "tel-national",
    "contact.address_line1": "address-line1", "contact.address_line2": "address-line2",
    "contact.postal_code": "postal-code", "contact.city": "address-level2",
    "contact.country": "country",
    "links.linkedin": "url", "links.github": "url", "links.portfolio": "url",
}


def _yes_no(path: str) -> bool:
    return any(path == p or (p.endswith(".") and path.startswith(p)) for p in YES_NO_CONTROL)


def country_options() -> list[dict]:
    """The country pick-list: Singapore first (the owner's home market), then
    every ISO country by name. Label "Singapore (SG)": the code stays visible
    where a form asks for it, and typing a name in a native <select> jumps to it."""
    rest = sorted((n, c) for c, n in COUNTRY_NAMES.items() if c != "SG")
    return [{"value": "SG", "label": f"{COUNTRY_NAMES['SG']} (SG)"}] +         [{"value": c, "label": f"{n} ({c})"} for n, c in rest]


def _item_json(item: FormItem, parent: str = "") -> dict:
    full = f"{parent}[0].{item.path}" if parent else item.path
    out = {
        "path": item.path, "label": item.label, "kind": item.kind,
        "options": (country_options() if item.kind == "country"
                    else [{"value": v, "label": lab} for v, lab in item.options]),
        "help": item.help,
        "required": not parent and _under(item.path, REQUIRED_PATHS),
        "recommended": not parent and _under(item.path, RECOMMENDED_PATHS),
        "sensitive": is_sensitive(full),
        "sub": [_item_json(s, item.path) for s in item.sub],
        "nullable": item.nullable, "multiline": item.multiline,
        "entry_label": item.entry_label, "fixed_text": item.fixed_text,
    }
    if item.kind == "country_bool_map":
        out["country_options"] = country_options()
    if not parent:                       # entry sub-fields have no such hints
        if item.kind == "bool" and _yes_no(item.path):
            out["control"] = "yes_no"
            if item.path in NULLABLE_BOOL:
                out["nullable_bool"] = True
        if item.path in SHOW_WHEN:
            out["show_when"] = copy.deepcopy(SHOW_WHEN[item.path])
        if item.path in AUTOCOMPLETE:
            out["autocomplete"] = AUTOCOMPLETE[item.path]
    return out


def form_json() -> list[dict]:
    """FORM as JSON for the web app, with the required / recommended /
    sensitive flags computed from REQUIRED_PATHS, RECOMMENDED_PATHS and
    is_sensitive (never written twice by hand). A group is `sensitive`
    ("Private") when every item in it is."""
    out = []
    for g in FORM:
        items = [_item_json(i) for i in g.items]
        out.append({"id": g.id, "title": g.title, "note": g.note, "items": items,
                    "sensitive": bool(items) and all(i["sensitive"] for i in items)})
    return out


_SET_PART = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def get_path(profile: Any, path: str) -> Any:
    """The value at a dotted path with list indices ("education[0].grade"), or None."""
    cur = profile
    for name, idx in _SET_PART.findall(path):
        if idx:
            i = int(idx)
            if not isinstance(cur, list) or i >= len(cur):
                return None
            cur = cur[i]
        else:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(name)
    return cur


def set_path(profile: dict, path: str, value: Any) -> None:
    """Write `value` at a dotted path, creating the mappings on the way; a
    list index past the end appends empty entries ("education[0].grade" on an
    empty list creates the first entry). Raises ValueError when a part of the
    path holds something else (a string where a mapping should be)."""
    parts = _SET_PART.findall(path)
    if not parts:
        raise ValueError("empty path")
    cur: Any = profile
    for i, (name, idx) in enumerate(parts):
        last = i == len(parts) - 1
        nxt_is_index = not last and bool(parts[i + 1][1])
        fresh: Any = [] if nxt_is_index else {}
        if idx:
            n = int(idx)
            if not isinstance(cur, list):
                raise ValueError(f"{path}: not a list")
            while len(cur) <= n:
                cur.append({})
            if last:
                cur[n] = value
            elif not isinstance(cur[n], (dict, list)):
                cur[n] = fresh
            cur = cur[n] if not last else cur
        else:
            if not isinstance(cur, dict):
                raise ValueError(f"{path}: not a mapping")
            if last:
                cur[name] = value
            else:
                if cur.get(name) is None:
                    cur[name] = fresh
                elif not isinstance(cur[name], (dict, list)):
                    raise ValueError(f"{path}: not a mapping")
                cur = cur[name]


def walk_leaves(value: Any):
    """(dotted path with [i] indices, leaf value) for every leaf of a profile."""
    yield from _walk(value)


def form_paths() -> list[str]:
    """Every path FORM covers (entries and maps cover what is inside them)."""
    return [i.path for g in FORM for i in g.items]


def json_safe(value: Any) -> Any:
    """A JSON-safe deep copy of a profile (YAML dates become ISO text)."""
    return _plain(value)


# --------------------------------------------------------------------------
# What a model may see, the grounding corpus, log redaction (§5.3, §7.7)
# --------------------------------------------------------------------------

def llm_extract(profile: dict) -> dict:
    """The non-sensitive allow-list (§5.3) as a nested dict, in the profile's
    shape. Nothing else from the profile ever reaches a prompt."""
    out: dict = {}
    for path in LLM_ALLOW:
        v = _get(profile or {}, path)
        if v is None:
            continue
        cur = out
        parts = path.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = _plain(v)
    return out


def _plain(v: Any) -> Any:
    """A JSON-safe deep copy (YAML dates become ISO text)."""
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return _date_text(v)


def today_sg() -> _dt.date:
    return _dt.datetime.now(SGT).date()


# --------------------------------------------------------------------------
# Work rights (D-75, questions_design §8.1): "always assume I have working rights"
# --------------------------------------------------------------------------

WORK_RIGHTS_DEFAULT = "default"                 # the map key for every country not listed
WORK_RIGHTS_MAPS = ("authorised_to_work", "requires_sponsorship")
# The standing answer when neither the country nor `default` is set (D-75).
WORK_RIGHTS_STANDING = {"authorised_to_work": True, "requires_sponsorship": False}


def work_right(profile: dict, which: str, country: str) -> tuple[bool, str]:
    """(value, where it came from) for one map: the country's own bool (source
    = its ISO code), else `default`'s ("default"), else the standing answer
    ("standing"). An absent or empty map therefore always has an answer."""
    m = _get(profile or {}, f"singapore_status.{which}")
    m = m if isinstance(m, dict) else {}
    code = (country or "").strip().upper()
    if isinstance(m.get(code), bool):
        return m[code], code
    if isinstance(m.get(WORK_RIGHTS_DEFAULT), bool):
        return m[WORK_RIGHTS_DEFAULT], WORK_RIGHTS_DEFAULT
    return WORK_RIGHTS_STANDING[which], "standing"


def work_rights(profile: dict, country: str) -> tuple[bool, bool]:
    """(authorised, needs_sponsorship) in `country` (ISO code)."""
    return (work_right(profile, "authorised_to_work", country)[0],
            work_right(profile, "requires_sponsorship", country)[0])


def work_rights_text(profile: dict) -> str:
    """The applicant's standing work rights as sentences, for the model (§8.1).
    With the defaults it is exactly "The applicant has the right to work and
    needs no visa sponsorship."; then one sentence per country whose value
    differs from its map's default. Not sensitive: it is the D-75 answer."""
    auth, _ = work_right(profile, "authorised_to_work", WORK_RIGHTS_DEFAULT)
    spons, _ = work_right(profile, "requires_sponsorship", WORK_RIGHTS_DEFAULT)
    out = [f"The applicant {'has' if auth else 'does not have'} the right to work and "
           f"{'needs' if spons else 'needs no'} visa sponsorship."]
    words = {("authorised_to_work", True): "has the right to work",
             ("authorised_to_work", False): "does not have the right to work",
             ("requires_sponsorship", True): "needs visa sponsorship",
             ("requires_sponsorship", False): "needs no visa sponsorship"}
    for which, default in (("authorised_to_work", auth), ("requires_sponsorship", spons)):
        m = _get(profile or {}, f"singapore_status.{which}")
        for code, v in (m.items() if isinstance(m, dict) else ()):
            if code != WORK_RIGHTS_DEFAULT and isinstance(v, bool) and v != default:
                out.append(f"For {code}: {words[(which, v)]}.")
    return " ".join(out)


def grounding_text(profile: dict, today: Optional[_dt.date] = None) -> str:
    """The profile part of the tier-5 grounding corpus (§7.7): every
    non-sensitive value one per line (the legal and preferred names, then the
    llm_extract allow-list), then the computed facts as sentences, then the
    work-rights sentence (D-75)."""
    lines: list[str] = []
    for path in ("identity.legal_first_name", "identity.legal_last_name",
                 "identity.preferred_name"):
        v = _get(profile or {}, path)
        if not _empty(v):
            lines.append(str(v))
    for _path, v in _walk(llm_extract(profile)):
        if v is None or isinstance(v, bool) or (isinstance(v, str) and not v.strip()):
            continue
        lines.append(str(v))
    f = computed_facts(profile or {}, today or today_sg())
    lines.append(f"Total professional experience: {f['experience_months']} months "
                 f"({f['experience_years']} years).")
    if f["graduation_year"]:
        lines.append(f"Graduation year: {f['graduation_year']}.")
    # D-75: the model is always told the standing work rights, and a choice
    # answer may quote them as evidence (§7.7). Always the last line.
    lines.append(work_rights_text(profile or {}))
    return "\n".join(lines)


_EXTRA_PATH = re.compile(r"^extra\.[^.\[]+\.(?:by_employer\.[^.\[]+\.)?([^.\[]+)")


def _is_extra_meta(path: str) -> bool:
    """True for a leaf under `extra.<key>.<meta>` or `...by_employer.<e>.seen`."""
    m = _EXTRA_PATH.match(path)
    return bool(m) and m.group(1) in EXTRA_META_FIELDS


def redaction_values(profile: dict) -> list[str]:
    """Strings a log line must never carry (NF-02, NF-09): every string value
    of 3+ characters in the profile, plus the phone and postal code as digits
    only (and the phone with its country code). Longest first, so a scrubber
    replaces "1 Example Road" before "Example".

    `extra` answers (`value`, `picks`, `by_employer`) are walked; its question
    metadata (`labels`, `title`, `description`, `seen`, `kind`, `sensitive`) is
    not: that is employer text, which the job log may show (questions_design §11)."""
    vals: set[str] = set()
    for path, v in _walk(profile or {}):
        if _is_extra_meta(path):
            continue
        v = _date_text(v)
        if isinstance(v, str) and len(v.strip()) >= 3:
            vals.add(v.strip())
    phone = re.sub(r"\D", "", str(_get(profile or {}, "contact.phone_number") or ""))
    cc = re.sub(r"\D", "", str(_get(profile or {}, "contact.phone_country_code") or ""))
    postal = re.sub(r"\D", "", str(_get(profile or {}, "contact.postal_code") or ""))
    for v in (phone, cc + phone if phone and cc else "", postal):
        if len(v) >= 3:
            vals.add(v)
    return sorted(vals, key=lambda s: (-len(s), s))


# --------------------------------------------------------------------------
# Computed facts (§5.1, D-68 A-4)
# --------------------------------------------------------------------------

def _pos(d: tuple[int, int, Optional[int]]) -> Fraction:
    """Month position: YYYY-MM -> start of that month; YYYY-MM-DD -> that day."""
    y, m, day = d
    base = Fraction(12 * y + (m - 1))
    if day is None:
        return base
    return base + Fraction(day - 1, calendar.monthrange(y, m)[1])


def _pos_end(d: tuple[int, int, Optional[int]]) -> Fraction:
    """End position: a YYYY-MM end counts its whole month, a day end its day."""
    y, m, day = d
    if day is None:
        return _pos(d) + 1
    return _pos(d) + Fraction(1, calendar.monthrange(y, m)[1])


def computed_facts(profile: dict, today: _dt.date) -> dict:
    """{"experience_months", "experience_years", "graduation_year"} (D-68 A-4).

    experience_months = the length of the union of every experience[] interval
    (internships count; education never does), whole months rounded down. An
    open end (null) runs to today; every end is clipped to today; an entry with
    no start or a start after today adds nothing. Overlapping or touching
    intervals merge, so 2024-05..2024-08 plus 2024-07..2024-12 is 8 months."""
    t = (today.year, today.month, today.day)
    now_end = _pos_end(t)
    spans: list[tuple[Fraction, Fraction]] = []
    for entry in (profile or {}).get("experience") or []:
        if not isinstance(entry, dict):
            continue
        s = _parse_date(entry.get("start"), ENTRY_DATE_FORMATS)
        if s is None:
            continue
        start = _pos(s)
        if start >= now_end:
            continue
        e_raw = entry.get("end")
        if _empty(e_raw):
            end = now_end
        else:
            e = _parse_date(e_raw, ENTRY_DATE_FORMATS)
            if e is None:
                continue
            end = min(_pos_end(e), now_end)
        if end > start:
            spans.append((start, end))
    total = Fraction(0)
    cur: Optional[list[Fraction]] = None
    for s, e in sorted(spans):
        if cur is not None and s <= cur[1]:
            cur[1] = max(cur[1], e)
            continue
        if cur is not None:
            total += cur[1] - cur[0]
        cur = [s, e]
    if cur is not None:
        total += cur[1] - cur[0]
    months = int(total)                      # floor: total is never negative
    grad = None
    for entry in (profile or {}).get("education") or []:
        if isinstance(entry, dict):
            d = _parse_date(entry.get("end"), ENTRY_DATE_FORMATS)
            if d and (grad is None or d[0] > grad):
                grad = d[0]
    return {"experience_months": months, "experience_years": months // 12,
            "graduation_year": grad}


# --------------------------------------------------------------------------
# Refresh from the resume (Q-44, q44_refresh_from_resume.md §3). Pure helpers:
# the orchestrator (tailor_flow.profile_proposals) reads the resume and hands
# plain dicts here; nothing below imports the tailor stage or calls a model.
# KA-4: facts are copied, never guessed. A date that cannot be read stays empty.
# --------------------------------------------------------------------------

_MONTHS = {name: i for i, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), start=1)}
_MONTHS.update({name[:3]: i for name, i in list(_MONTHS.items())})
_MONTHS["sept"] = 9

# One date token (§3.2): "Mon YYYY" / "Month YYYY", "MM/YYYY" or "YYYY-MM".
_RESUME_TOKEN = r"(?:[A-Za-z]{3,9}\.?\s+\d{4}|\d{1,2}/\d{4}|\d{4}-\d{2})"
_RESUME_OPEN = r"(?:present|current|now|ongoing|to\s+date)"
# D-106: the end date may carry an expected-graduation prefix; it is still the end.
_RESUME_EXPECTED = r"(?:expected:?|exp\.|exp|anticipated)"
_RESUME_RANGE_RE = re.compile(
    rf"^(?P<a>{_RESUME_TOKEN})\s*(?:(?:–|—|-|\bto\b)\s*(?:{_RESUME_EXPECTED}\s*)?"
    rf"(?P<b>{_RESUME_TOKEN}|{_RESUME_OPEN})|(?P<b2>to\s+date))$",
    re.IGNORECASE)
_RESUME_SINGLE_RE = re.compile(
    rf"^(?:(?P<exp>{_RESUME_EXPECTED})\s*)?(?P<a>{_RESUME_TOKEN})$", re.IGNORECASE)


def _resume_token(tok: str) -> Optional[str]:
    """One accepted token as YYYY-MM, or None (an unknown month name, month 13)."""
    t = tok.strip()
    m = re.match(r"^([A-Za-z]{3,9})\.?\s+(\d{4})$", t)
    if m:
        mo = _MONTHS.get(m.group(1).lower())
        y = int(m.group(2))
    else:
        m = re.match(r"^(\d{1,2})/(\d{4})$", t)
        if m:
            mo, y = int(m.group(1)), int(m.group(2))
        else:
            m = re.match(r"^(\d{4})-(\d{2})$", t)
            if not m:
                return None
            y, mo = int(m.group(1)), int(m.group(2))
    if not mo or not 1 <= mo <= 12:
        return None
    return f"{y:04d}-{mo:02d}"


def parse_resume_dates(text: Any) -> tuple[Optional[str], Optional[str], bool]:
    """(start, end, ok) for a resume's verbatim dates line (§3.2).

    "May 2024 – Aug 2024" -> ("2024-05", "2024-08", True); an open end
    (Present / Current / Now / To date / Ongoing) is `end None`. An end date may
    carry "Expected", "Expected:", "Exp." or "Anticipated" (D-106: the expected
    graduation, stored as the end). One token is both start and end, except
    after one of those prefixes, where it is the end only. A year
    with no month ("2021 – 2025") and anything else is (None, None, False): no
    month is invented. A range that ends before it starts is not understood
    either (it would not save)."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    fail: tuple[Optional[str], Optional[str], bool] = (None, None, False)
    if not t:
        return fail
    m = _RESUME_RANGE_RE.match(t)
    if m:
        start = _resume_token(m.group("a"))
        b = m.group("b") or m.group("b2")
        is_open = re.fullmatch(_RESUME_OPEN, b, re.IGNORECASE) is not None
        end = None if is_open else _resume_token(b)
        if start is None or (end is None and not is_open):
            return fail
        if end is not None and end < start:
            return fail
        return start, end, True
    m = _RESUME_SINGLE_RE.match(t)
    if m:
        tok = _resume_token(m.group("a"))
        if tok is None:
            return fail
        return (None, tok, True) if m.group("exp") else (tok, tok, True)
    return fail


_SKILL_CASE = {
    "sql": "SQL", "aws": "AWS", "c++": "C++", "node.js": "Node.js", "gcp": "GCP", "api": "API",
    "css": "CSS", "html": "HTML", "c#": "C#", "r": "R", "excel": "Excel", "git": "Git",
}


def skill_label(s: Any) -> str:
    """A resume skill as the form shows it: the Python twin of
    `web/src/applicantForm.js skillLabel` (the same cases pin both). An
    all-lowercase token is title cased ("machine learning" -> "Machine
    Learning"), a few known spellings are fixed ("sql" -> "SQL"), and anything
    that already has a capital ("PyTorch") is kept as it is."""
    t = re.sub(r"\s+", " ", str("" if s is None else s).strip())
    fixed = _SKILL_CASE.get(t.lower())
    if fixed:
        return fixed
    if t != t.lower():
        return t
    return re.sub(r"(^|[\s/-])([a-z])", lambda m: m.group(1) + m.group(2).upper(), t)


# ---- the proposals file and the template (§2) ----

PROPOSALS_NAME = "applicant.refresh.json"     # beside the profile, so inside gitignored data/
TEMPLATE_PATH = ROOT / "config" / "applicant.example.yaml"

# The fields a proposal fills, in the template's order. `from_resume` is last.
REFRESH_FIELDS = {
    "experience": ("employer", "title", "start", "end", "location", "description"),
    "education": ("institution", "degree", "major", "minor", "start", "end",
                  "grade_type", "grade", "grade_scale"),
}
REFRESH_ID = {"experience": ("employer", "title"), "education": ("institution", "degree")}


def proposals_path(applicant_path: str | os.PathLike) -> Path:
    """Where `profile --plan-applicant` keeps the resume-side facts: beside the
    applicant profile (no config key, design §2)."""
    return Path(applicant_path).with_name(PROPOSALS_NAME)


def load_proposals(path: str | os.PathLike) -> Optional[dict]:
    """The proposals file as a dict, or None when it is missing or unreadable."""
    import json
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_proposals(path: str | os.PathLike, proposals: dict) -> None:
    """Write the proposals file atomically (tempfile in the same folder +
    os.replace), so a reader never sees half a file."""
    import json
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=p.stem + ".", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(proposals, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_template(path: str | os.PathLike | None = None) -> dict:
    """`config/applicant.example.yaml` as a dict ({} when unreadable): its
    placeholder entries and skills are the ones a refresh may replace."""
    try:
        data = yaml.safe_load(Path(path or TEMPLATE_PATH).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def original_resume_hash(resume_dir: str | os.PathLike | None = None) -> Optional[str]:
    """`sha256:<hex>` of `<resume_dir>/resume.pdf` or `resume.docx` (the same
    value as profile/resume_ingest.file_hash, copied because this foundation
    module may not import a stage); None when there is no resume file."""
    rdir = Path(resume_dir) if resume_dir else ROOT / "data"
    for name in RESUME_NAMES:
        p = rdir / name
        if p.is_file():
            h = hashlib.sha256()
            with open(p, "rb") as fh:
                for block in iter(lambda: fh.read(1 << 16), b""):
                    h.update(block)
            return "sha256:" + h.hexdigest()
    return None


# ---- the plan (§3.4) ----

def _key(v: Any) -> str:
    """Match text: lowercase, punctuation to spaces, whitespace collapsed."""
    return " ".join(re.sub(r"[^\w\s]|_", " ", str(v or "").lower()).split())


def _pair_key(entry: dict, lst: str) -> str:
    org, title = REFRESH_ID[lst]
    return f"{_key(entry.get(org))}|{_key(entry.get(title))}"


def _org_key(entry: dict, lst: str) -> str:
    return _key(entry.get(REFRESH_ID[lst][0]))


def _clean_proposal(p: dict, lst: str) -> dict:
    """The entry a proposal saves as: its fields in template order (absent ones
    empty), `from_resume: true`, and none of the plan-only keys (`dates_text`,
    `subtitle`)."""
    out = {k: p.get(k, None if k in ("start", "end") else "") for k in REFRESH_FIELDS[lst]}
    out["from_resume"] = True
    return out


def _dates_note(p: dict) -> str:
    text = str(p.get("dates_text") or "")
    if parse_resume_dates(text)[2]:
        return ""
    return f'Dates not understood ("{text}"). Add them after saving.'


def _change_note(p: dict) -> str:
    parts = [_dates_note(p)]
    subtitle = str(p.get("subtitle") or "").strip()
    if subtitle:
        parts.append(f"Resume says: {subtitle}")
    return " ".join(x for x in parts if x)


def _merge_update(old: dict, p: dict, lst: str) -> dict:
    """The proposal, where a field it cannot fill (unread dates, "") takes the
    old value only when the old entry came from a resume, never from a template
    placeholder. A read open end ("Present") stays open. Keys outside the
    proposal's fields are kept the same way."""
    new = _clean_proposal(p, lst)
    if old.get("from_resume") is not True:
        return new
    dates_read = not _dates_note(p)
    for k in REFRESH_FIELDS[lst]:
        if _empty(new.get(k)) and not _empty(old.get(k)):
            if k in ("start", "end") and dates_read:
                continue
            new[k] = old[k]
    extra = {k: v for k, v in old.items() if k not in new}
    if extra:
        flag = new.pop("from_resume")
        new.update(extra)
        new["from_resume"] = flag
    return new


def _plan(profile: dict, proposals: dict, template: dict) -> list[dict]:
    """Every change with its private apply data (`_new`, `_anchor`, `_order`)."""
    changes: list[dict] = []
    seen_ids: dict[str, int] = {}

    def cid(lst: str, op: str, key: str) -> str:
        base = f"{lst}:{op}:{key}"
        n = seen_ids.get(base, 0) + 1
        seen_ids[base] = n
        return base if n == 1 else f"{base}#{n}"

    for lst in ("experience", "education"):
        existing = profile.get(lst) if isinstance(profile.get(lst), list) else []
        props = [p for p in (proposals.get(lst) or []) if isinstance(p, dict)]
        placeholders = {_pair_key(e, lst) for e in (template.get(lst) or []) if isinstance(e, dict)}
        is_placeholder = [isinstance(e, dict) and _pair_key(e, lst) in placeholders
                          for e in existing]
        replaceable = [isinstance(e, dict) and (e.get("from_resume") is True or is_placeholder[i])
                       for i, e in enumerate(existing)]
        match_e: dict[int, int] = {}            # existing index -> proposal index
        match_p: dict[int, int] = {}            # proposal index -> existing index
        for j, p in enumerate(props):           # exact org|title first
            k = _pair_key(p, lst)
            for i, e in enumerate(existing):
                if i not in match_e and isinstance(e, dict) and _pair_key(e, lst) == k:
                    match_e[i], match_p[j] = j, i
                    break
        free_e = [i for i, e in enumerate(existing) if i not in match_e and isinstance(e, dict)]
        free_p = [j for j in range(len(props)) if j not in match_p]
        for j in free_p:                        # then org alone, when unique on both sides
            org = _org_key(props[j], lst)
            if not org:
                continue
            es = [i for i in free_e if _org_key(existing[i], lst) == org]
            ps = [q for q in free_p if _org_key(props[q], lst) == org]
            if len(es) == 1 and len(ps) == 1 and es[0] not in match_e:
                match_e[es[0]], match_p[j] = j, es[0]

        for i, e in enumerate(existing):
            if not isinstance(e, dict):
                continue
            if i in match_e:
                p = props[match_e[i]]
                if not replaceable[i]:
                    changes.append({"id": cid(lst, "kept", _pair_key(p, lst)), "list": lst,
                                    "op": "kept", "index": i, "before": e, "after": None,
                                    "note": "", "default": False})
                    continue
                new = _merge_update(e, p, lst)
                if new == e:
                    continue
                changes.append({"id": cid(lst, "update", _pair_key(p, lst)), "list": lst,
                                "op": "update", "index": i, "before": e, "after": new,
                                "note": _change_note(p), "default": True, "_new": new})
            elif replaceable[i]:
                example = is_placeholder[i]
                changes.append({"id": cid(lst, "remove", _pair_key(e, lst)), "list": lst,
                                "op": "remove", "index": i, "before": e, "after": None,
                                "reason": "template" if example else "not_on_resume",
                                "note": ("Example entry from the template" if example
                                         else "No longer on your resume"),
                                "default": True})
        for j, p in enumerate(props):
            if j in match_p:
                continue
            # Just before the first matched entry that follows it in resume order.
            anchor = next((match_p[q] for q in range(j + 1, len(props)) if q in match_p),
                          len(existing))
            new = _clean_proposal(p, lst)
            changes.append({"id": cid(lst, "add", _pair_key(p, lst)), "list": lst, "op": "add",
                            "index": anchor, "before": None, "after": new,
                            "note": _change_note(p), "default": not _dates_note(p),
                            "_new": new, "_anchor": anchor, "_order": j})

    current = profile.get("skills") if isinstance(profile.get("skills"), list) else []
    resume_skills: list[str] = []
    for s in proposals.get("skills") or []:
        label = skill_label(s)
        if label and label.lower() not in {x.lower() for x in resume_skills}:
            resume_skills.append(label)
    template_skills = template.get("skills")
    if isinstance(template_skills, list) and template_skills and current == template_skills:
        if resume_skills != current:
            changes.append({"id": "skills:replace", "list": "skills", "op": "replace",
                            "index": None, "before": list(current), "after": resume_skills,
                            "note": "Example skills from the template", "default": True,
                            "_new": resume_skills})
    else:
        have = {str(x).strip().lower() for x in current}
        add = [s for s in resume_skills if s.lower() not in have]
        if add:
            changes.append({"id": "skills:add", "list": "skills", "op": "add", "index": None,
                            "before": list(current), "after": list(current) + add,
                            "note": "", "default": True, "_new": add})
    return changes


def _public(change: dict) -> dict:
    return {k: copy.deepcopy(v) for k, v in change.items() if not k.startswith("_")}


def refresh_plan(profile: dict, proposals: dict, template: dict) -> dict:
    """What a refresh from the resume would change (§3.4):
    `{changes: [{id, list, op, index, before, after, note, default}],
    skills: {add, not_on_resume}}`. Pure; nothing is saved.

    Only a replaceable entry changes: `from_resume: true`, or the template's
    placeholder (the same org and title as `config/applicant.example.yaml`). An
    entry the owner added or edited is `kept` when the resume has it too, and is
    never changed. Skills are only added (case-insensitive), except that the
    template's placeholder list is offered for replacing. `languages`, `links`,
    `attested_skills` and everything else are never part of a plan.

    `op` is update | add | remove | kept (entries) or add | replace (skills); a
    remove also carries `reason` (not_on_resume | template). `index` is the
    entry's position in the current list (for an add: the entry it goes before)."""
    changes = _plan(profile or {}, proposals or {}, template or {})
    skills = next((c for c in changes if c["list"] == "skills"), None)
    add = [] if skills is None else list(skills["_new"])
    return {"changes": [_public(c) for c in changes],
            "skills": {"add": add,
                       "not_on_resume": [str(s) for s in (proposals or {}).get("not_on_resume") or []]}}


def apply_refresh(profile: dict, proposals: dict, accept_ids: Iterable[str],
                  template: dict) -> tuple[dict, list[str]]:
    """(the new profile, the accepted ids that were not applied). The plan is
    computed again here, so only what it offers now can be applied; an id it
    does not know (or a `kept` row, which is info only) is reported, never
    applied. The caller validates and saves (`save`: atomic, comment backup)."""
    profile = copy.deepcopy(profile or {})
    accept = [str(a) for a in (accept_ids or [])]
    changes = _plan(profile, proposals or {}, template or {})
    by_id = {c["id"]: c for c in changes}
    chosen = {a for a in accept if a in by_id and by_id[a]["op"] != "kept"}
    ignored = [a for a in accept if a not in chosen]
    for lst in ("experience", "education"):
        mine = [c for c in changes if c["list"] == lst and c["id"] in chosen]
        if not mine:
            continue
        existing = list(profile.get(lst) or []) if isinstance(profile.get(lst), list) else []
        updates = {c["index"]: c["_new"] for c in mine if c["op"] == "update"}
        removes = {c["index"] for c in mine if c["op"] == "remove"}
        adds = sorted((c for c in mine if c["op"] == "add"), key=lambda c: c["_order"])
        out: list[Any] = []
        for i, e in enumerate(existing):
            out.extend(copy.deepcopy(c["_new"]) for c in adds if c["_anchor"] == i)
            if i in removes:
                continue
            out.append(copy.deepcopy(updates[i]) if i in updates else e)
        out.extend(copy.deepcopy(c["_new"]) for c in adds if c["_anchor"] >= len(existing))
        profile[lst] = out
    for c in changes:
        if c["list"] == "skills" and c["id"] in chosen:
            current = profile.get("skills") if isinstance(profile.get("skills"), list) else []
            profile["skills"] = (list(c["_new"]) if c["op"] == "replace"
                                 else list(current) + list(c["_new"]))
    return profile, ignored
