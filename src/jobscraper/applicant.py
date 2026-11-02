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
# Load / save
# --------------------------------------------------------------------------

def load(path: str | os.PathLike) -> dict:
    """The profile at `path`; {} if the file does not exist. Raises
    ApplicantError on YAML that cannot be read or is not a mapping."""
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
    return data


COMMENTED_BACKUP_NAME = "applicant.commented-backup.yaml"   # matches data/applicant*.yaml (gitignored)


def etag(path: str | os.PathLike) -> str:
    """The lost-update guard (questions_design §3.1): the first 16 hex of the
    SHA-256 of the file's bytes, "" when the file is absent. The Profile form
    and the Questions card send it back; a mismatch is a 409, nothing saved."""
    p = Path(path)
    try:
        data = p.read_bytes()
    except FileNotFoundError:
        return ""
    return hashlib.sha256(data).hexdigest()[:16]


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


def save(path: str | os.PathLike, profile: dict, *, keep_commented_copy: bool = True) -> None:
    """Validate, then write atomically (tempfile in the same folder + os.replace).

    Raises ApplicantError (with `.errors`) and writes nothing when the profile
    is invalid. Key order is kept (`sort_keys=False`); YAML comments are not.
    So the first save over a file that has comments first copies it to
    `applicant.commented-backup.yaml` (once: an existing copy is never
    overwritten), and the owner keeps their notes (questions_design §3.1)."""
    errors = validate(profile)
    if errors:
        raise ApplicantError(f"{len(errors)} invalid field(s): "
                             + ", ".join(e.path for e in errors), errors)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if keep_commented_copy and p.is_file() and has_comments(p):
        backup = commented_backup_path(p)
        if not backup.exists():
            shutil.copy2(p, backup)
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
    must be well-formed. Messages name the rule and never repeat the value."""
    errs: list[FieldError] = []

    def err(path: str, message: str) -> None:
        errs.append(FieldError(path, message))

    if not isinstance(profile, dict):
        return [FieldError("", "the profile must be a mapping")]

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
            if not (isinstance(k, str) and (ISO2_RE.match(k) or k == WORK_RIGHTS_DEFAULT)):
                err(f"singapore_status.{block}",
                    "keys must be 2-letter ISO country codes or default")
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
        _I("singapore_status.religion", "Religion", "text", help="Or leave it as decline."),
        _I("singapore_status.marital_status", "Marital status", "enum", _enum_opts(
            "singapore_status.marital_status", {"single": "Single", "married": "Married"})),
        _I("singapore_status.nric_last4", "NRIC, last 4 characters", "text",
           help="Only the last 4, such as 123A. Never the full NRIC."),
    )),
    FormGroup("us_self_id", "US equal-employment questions", (
        _I("us_self_id.eeo_gender", "Gender", "enum", _enum_opts("us_self_id.eeo_gender")),
        _I("us_self_id.eeo_race_ethnicity", "Race or ethnicity", "enum",
           _enum_opts("us_self_id.eeo_race_ethnicity")),
        _I("us_self_id.veteran_status", "Veteran status", "enum",
           _enum_opts("us_self_id.veteran_status")),
        _I("us_self_id.disability_status", "Disability status", "enum",
           _enum_opts("us_self_id.disability_status")),
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
           help="13 if you count the AWS bonus."),
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


def _item_json(item: FormItem, parent: str = "") -> dict:
    full = f"{parent}[0].{item.path}" if parent else item.path
    return {
        "path": item.path, "label": item.label, "kind": item.kind,
        "options": [{"value": v, "label": lab} for v, lab in item.options],
        "help": item.help,
        "required": not parent and _under(item.path, REQUIRED_PATHS),
        "recommended": not parent and _under(item.path, RECOMMENDED_PATHS),
        "sensitive": is_sensitive(full),
        "sub": [_item_json(s, item.path) for s in item.sub],
        "nullable": item.nullable, "multiline": item.multiline,
        "entry_label": item.entry_label, "fixed_text": item.fixed_text,
    }


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
