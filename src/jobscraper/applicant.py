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
  - normalise (Q-36, D-78): the owner types "Male", "non-binary", `no` or "per
    month"; `load` turns each into the canonical spelling once, so the resolver,
    the tailor and the form API only ever see canonical values
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
import os
import re
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

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
    "singapore_status.authorised_to_work.SG",
    "singapore_status.requires_sponsorship.SG",
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
URL_RE = re.compile(r"^https?://\S+$")
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
    the path's synonyms (pay periods), and a YAML boolean for a yes/no enum
    (`disability_status: no` is read by YAML as False, not "no")."""
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
    """A copy of `profile` with every enum field in its canonical spelling
    (`_canon_enum`); the argument is not changed. A value that still does not
    map is left as it is. Idempotent. `load`, `validate` and `save` all call it,
    so a profile typed by hand, edited in the form or built in code reads the
    same everywhere. Other fields (booleans, dates, numbers) are not touched."""
    if not isinstance(profile, dict):
        return profile
    out = copy.deepcopy(profile)
    for path, allowed in ENUMS.items():
        _set_at(out, path,
                lambda v, a=allowed, s=ENUM_SYNONYMS.get(path): _canon_enum(v, a, s))
    for spec, allowed in LIST_ENUMS.items():
        lst_name, key = spec.split("[].")
        entries = out.get(lst_name)
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and key in entry:
                entry[key] = _canon_enum(entry[key], allowed)
    return out


# --------------------------------------------------------------------------
# Load / save
# --------------------------------------------------------------------------

def load(path: str | os.PathLike) -> dict:
    """The profile at `path`, normalised (`normalise`); {} if the file does not
    exist. Raises ApplicantError on YAML that cannot be read or is not a mapping."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise ApplicantError(f"cannot read {p.name}: {type(exc).__name__}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApplicantError(f"{p.name} must be a mapping, got {type(data).__name__}")
    return normalise(data)


def save(path: str | os.PathLike, profile: dict) -> None:
    """Normalise, validate, then write atomically (tempfile in the same folder
    + os.replace). The file always holds the canonical spellings.

    Raises ApplicantError (with `.errors`) and writes nothing when the profile
    is invalid. YAML comments do not survive a save; the Profile form is the
    editor once there is one (§5.1)."""
    profile = normalise(profile)
    errors = validate(profile)
    if errors:
        raise ApplicantError(f"{len(errors)} invalid field(s): "
                             + ", ".join(e.path for e in errors), errors)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            yaml.safe_dump(profile, fh, sort_keys=False, allow_unicode=True)
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
    if not _empty(country) and not (isinstance(country, str) and ISO2_RE.match(country)):
        err("contact.country", "must be a 2-letter ISO country code, e.g. SG")
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
    if not _empty(nat) and not (isinstance(nat, str) and ISO2_RE.match(nat)):
        err("singapore_status.nationality", "must be a 2-letter ISO country code, e.g. SG")

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
            if not (isinstance(k, str) and ISO2_RE.match(k)):
                err(f"singapore_status.{block}", "keys must be 2-letter ISO country codes")
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
    return errs


# --------------------------------------------------------------------------
# Completeness (F-11)
# --------------------------------------------------------------------------

def _filled(profile: dict, path: str) -> bool:
    if path == "education":
        return any(isinstance(e, dict) and not _empty(e.get("institution"))
                   and not _empty(e.get("degree")) and not _empty(e.get("end"))
                   for e in (profile.get("education") or []))
    v = _get(profile, path)
    if path == "pay.expected_salary.amount":
        return _is_int(v) and v > 0            # the template's 0 is "not filled"
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


def grounding_text(profile: dict, today: Optional[_dt.date] = None) -> str:
    """The profile part of the tier-5 grounding corpus (§7.7): every
    non-sensitive value one per line (the legal and preferred names, then the
    llm_extract allow-list), then the computed facts as sentences."""
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
    return "\n".join(lines)


def redaction_values(profile: dict) -> list[str]:
    """Strings a log line must never carry (NF-02, NF-09): every string value
    of 3+ characters in the profile, plus the phone and postal code as digits
    only (and the phone with its country code). Longest first, so a scrubber
    replaces "1 Example Road" before "Example"."""
    vals: set[str] = set()
    for _path, v in _walk(profile or {}):
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
