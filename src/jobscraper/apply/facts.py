"""Facts the model may cite, and how the program turns one into a value (llm_fill_design §5).

D-78 lets the local model choose, field by field, *where* an answer comes from; the
program, not the model, then writes every value that comes from the applicant's own
data. This module is that program side, and it is pure (no browser, no model, no store):

  fact_catalogue  every fact the model may cite: `profile:<path>` leaves, the owner's
                  `extra:<key>` answers usable at this employer, `standing:<id>` facts
                  (today, full name, experience years, work rights, ...) (§5.1)
  facts_text      the FACTS block, one fact per line, byte-identical for an attempt (§6.2)
  fact_value      ref + field -> the value written, by the deterministic mappers
                  (`resolve.fit_*`); None = no fit (§5.3)
  relevant        G2(b): may this fact answer this question at all? (§5.3, D-84 R4)
  match_entries   which site entry (a job, a school) is which source entry (§10 E2)
  entry_blocks    the text block each source entry is checked against (§5.2, G3/G6)
  s_values        S values that must never be in a prompt (§6.5); `llm_fill.redact`
                  scrubs them
  today_sg, field_sig, inputs_hash, facts_used_hash: the clock and cache keys (§13.3)

Privacy (NF-02, H4): a private fact (every path outside `applicant.LLM_ALLOW` except the
legal and preferred names, and every sensitive `extra` answer) reaches the model only as
"set" / "empty"; its value reaches the page only through `fact_value`. Nothing here logs.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import hmac
import json
import re
from typing import Any, Iterable, Mapping, Optional, Sequence, Union

from .. import applicant
from . import declarations, resolve
from .contracts import (
    CHOICE_TYPES, ApplyFailure, Canonical, EntrySection, Fact, FieldType, FormField, Option,
    PageField, ReasonCode, ResolveContext,
)
from .plan import STOP_WORDS, content_tokens, contains_run, is_generic, norm_label, tokens

Fit = resolve.Fit
FieldLike = Union[PageField, FormField]

# --------------------------------------------------------------------------
# Catalogue (§5.1)
# --------------------------------------------------------------------------

# Names that may be shown besides the llm_extract allow-list (§5.1).
NAME_PATHS = ("identity.legal_first_name", "identity.legal_last_name", "identity.preferred_name")
# Single facts although they are mappings/lists in the file (fit_salary reads the mapping).
SALARY_PATHS = ("pay.expected_salary", "pay.current_salary")
ENTRY_LISTS = ("experience", "education", "languages")
SKIP_KEYS = frozenset({"version", "extra"})
ENTRY_META = frozenset({"from_resume"})

STANDING_IDS: tuple[tuple[str, str, str, bool], ...] = (
    # (id, title, mapping kind, private)
    ("today", "Today's date", "date", False),
    ("full_name", "Full legal name", "text", False),
    ("experience_years", "Years of professional experience", "number", False),
    ("experience_months", "Months of professional experience", "number", False),
    ("graduation_year", "Graduation year", "number", False),
    ("work_rights", "Right to work and visa sponsorship", "text", False),
    ("worked_here", "Worked for this employer before", "bool", False),
    ("current_employee_here", "Currently employed by this employer", "bool", False),
    ("previously_applied", "Applied to this employer before", "bool", False),
    ("how_heard", "How you heard about this job", "text", False),
    ("account_email", "Email address of this application", "text", True),
)
# Tier-2 rows that speak for a standing fact (questions.yaml `computed.*` keys).
STANDING_RULE_KEYS = {"experience_years": "computed.experience_years",
                      "graduation_year": "computed.graduation_year"}

# G2(b) relevance (§5.3): words that name the same thing. Phrases, normalised, whole words.
FACT_TITLE_SYNONYMS: tuple[tuple[str, ...], ...] = (
    ("phone", "mobile", "contact number", "telephone", "handphone", "cell"),
    ("postal", "zip", "postcode", "postal code", "zip code"),
    ("address", "street", "unit", "block"),
    ("birth", "dob", "born"),
    ("city", "town", "location"),
    ("country", "nation"),
    ("school", "university", "institution", "college", "polytechnic"),
    ("degree", "qualification", "diploma"),
    ("major", "field of study", "discipline", "specialisation", "specialization"),
    ("employer", "company", "organisation", "organization"),
    ("title", "position", "role", "job title"),
    ("start", "from", "begin", "commencement"),
    ("end", "to", "until", "finish", "completion", "graduation"),
    ("first", "given"),
    ("last", "family", "surname"),
    ("salary", "pay", "compensation", "remuneration"),
    ("notice", "notice period"),
    ("earliest", "availability", "available"),
    ("portfolio", "website", "personal website"),
    ("spoken", "speaking", "proficiency", "level", "fluency"),
    ("written", "writing", "proficiency", "level"),
    ("grade", "gpa", "cap", "score", "honours"),
    ("description", "responsibilities", "duties", "what you did"),
    ("relocate", "relocation"),
    ("hear", "heard", "source", "referral"),
    ("email", "e mail"),
)
# Title words too common to make a fact relevant on their own ("Company name" is not a
# first name; "Marital status" is not a residency status).
TITLE_GENERIC = frozenset({"name", "number", "date", "status", "type", "file", "other", "current",
                           "your", "yes", "no", "if"})
# D-84 R4: a label about another person is never answered with the applicant's own
# contact or identity facts.
OTHER_PERSON = ("emergency", "next of kin", "kin", "referee", "referees", "reference",
                "references", "spouse", "partner", "guardian", "parent", "parents", "manager",
                "supervisor")
CONTACT_IDENTITY_REFS = ("profile:contact.", "profile:identity.", "standing:full_name",
                         "standing:account_email")

_INDEX = re.compile(r"\[\d+\]")


def bare(path: str) -> str:
    """`experience[1].title` -> `experience.title` (FORM and allow-list paths)."""
    return _INDEX.sub("", path)


def _visible(path: str) -> bool:
    b = bare(path)
    if b in NAME_PATHS:
        return True
    return any(b == p or b.startswith(p + ".") for p in applicant.LLM_ALLOW)


def _template_entry(lst: str, e: Any) -> bool:
    """The template's example rows ("Example Pte Ltd", "Example University") are not the
    owner's history (§5.1). Matched on the whole company-normalised name, so a real
    employer whose name merely starts with "Example" is kept."""
    if not isinstance(e, dict):
        return True
    if lst == "experience":
        return declarations.employer_norm(str(e.get("employer") or "")) == "example"
    if lst == "education":
        return declarations.employer_norm(str(e.get("institution") or "")) == "example university"
    return False


def _form_item(path: str) -> tuple[Optional[applicant.FormItem], Optional[applicant.FormItem]]:
    """(FORM item, its entries sub-item or None) for a bare path."""
    return applicant.form_item(path)


def _title(path: str) -> str:
    """Plain words for a profile path, from the Profile form's labels."""
    it, sub = _form_item(path)
    m = re.match(r"^(experience|education|languages)\[(\d+)\]", path)
    if it is not None and sub is not None and m:
        return f"{it.entry_label or it.label} {int(m.group(2)) + 1}: {sub.label}"
    if it is not None:
        rest = bare(path)[len(it.path):].strip(".")
        return f"{it.label} ({rest})" if rest else it.label
    return bare(path).rsplit(".", 1)[-1].replace("_", " ").capitalize()


def _kind(path: str, value: Any) -> str:
    b = bare(path)
    if b in SALARY_PATHS:
        return "salary"
    if isinstance(value, bool):
        return "bool"
    list_enum = re.sub(r"^(\w+)\.", r"\1[].", b)
    if b in applicant.ENUMS or list_enum in applicant.LIST_ENUMS:
        return "enum"
    if b in applicant.DATE_FIELDS or re.match(r"^(experience|education)\.(start|end)$", b):
        return "date"
    if b in ("contact.country", "singapore_status.nationality"):
        return "country"
    if b.startswith("links."):
        return "url"
    if b.startswith("documents."):
        return "file"
    if isinstance(value, (int, float)):
        return "number"
    return "text"


def _text(value: Any) -> str:
    """A fact value as the model reads it."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict):                          # a salary
        amt, cur = value.get("amount"), value.get("currency") or ""
        per = {"monthly": "per month", "annual": "per year"}.get(str(value.get("period") or ""), "")
        neg = " (negotiable)" if value.get("negotiable") else ""
        return " ".join(str(x) for x in (amt, cur, per) if x not in (None, "")) + neg
    if isinstance(value, list):
        return ", ".join(str(x) for x in value if x not in (None, ""))
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()[:10]
    return "" if value is None else str(value).strip()


def _is_set(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value.get("amount"))
    return not (value is None or value == [] or value == {}
                or (isinstance(value, str) and not value.strip()))


def _leaves(profile: dict):
    """(path, value) per profile fact: leaves, except salaries and lists of plain
    values (one fact each), entry metadata, template rows, `version` and `extra`."""
    def walk(v: Any, path: str):
        if path in SALARY_PATHS:
            yield path, v
        elif isinstance(v, dict):
            for k, x in v.items():
                if str(k) in ENTRY_META and re.search(r"\]$", path):
                    continue
                yield from walk(x, f"{path}.{k}" if path else str(k))
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            for i, x in enumerate(v):
                if path in ENTRY_LISTS and _template_entry(path, x):
                    continue
                yield from walk(x, f"{path}[{i}]")
        else:
            yield path, v
    for k, v in (profile or {}).items():
        if str(k) in SKIP_KEYS:
            continue
        yield from walk(v, str(k))


def _entry_of(path: str) -> str:
    m = re.match(r"^((?:experience|education|languages)\[\d+\])\.", path)
    if m:
        return m.group(1)
    m = re.match(r"^(links\.(?:linkedin|github|portfolio))$", path)
    return m.group(1) if m else ""


def _employer_tokens(names: Iterable[str]) -> list[list[str]]:
    out = []
    for n in names:
        t = declarations.employer_norm(n or "").split()
        if t:
            out.append(t)
    return out


def other_employers(rctx: ResolveContext, *, composed: bool = False) -> list[list[str]]:
    """G12: company-token lists of the other employers whose names must not appear in a
    kept or cited text here: `rctx.other_employers` minus this employer and its aliases.
    D-84 R1: for a text the model composes, the applicant's own employers (profile
    experience and resume entries) are removed too, so a cover letter may name them."""
    mine = [rctx.employer_name, *rctx.employer_aliases]
    own: list[str] = []
    if composed:
        own += [str(e.get("employer") or "") for e in (rctx.profile or {}).get("experience") or []
                if isinstance(e, dict)]
        own += [str(e.get("institution") or "") for e in (rctx.profile or {}).get("education") or []
                if isinstance(e, dict)]
    out = []
    for name in rctx.other_employers:
        if any(declarations.company_match(name, m) for m in mine if m):
            continue
        if any(declarations.company_match(name, o) for o in own if o):
            continue
        if composed and _named_in_resume_entries(name, rctx):
            continue
        out += _employer_tokens([name])
    return out


def _named_in_resume_entries(name: str, rctx: ResolveContext) -> bool:
    toks = declarations.employer_norm(name).split()
    return bool(toks) and any(contains_run(tokens(text), toks)
                              for _id, kind, text in rctx.resume_entries
                              if kind in ("experience", "education"))


def names_other_employer(text: str, employers: Sequence[Sequence[str]]) -> bool:
    """G12: does `text` phrase-match one of the employers (company tokens, whole words)?"""
    toks = tokens(text)
    return any(contains_run(toks, list(e)) for e in employers)


def _extra_usable(key: str, entry: Any, rctx: ResolveContext,
                  others: Sequence[Sequence[str]]) -> Optional[tuple[dict, bool]]:
    """(the answer here, employer-scoped?) for a citable `extra` entry, else None.
    §5.1: a generic-label entry only when scoped to this employer (F1, §12.1); never one
    whose answer names another employer (G12)."""
    if applicant.extra_entry_errors(key, entry):
        return None
    ans, scope = resolve.employer_answer(entry, rctx)
    labels = [str(x).split(" | ", 1)[0] for x in entry.get("labels") or []]
    if labels and all(is_generic(x) for x in labels) and not scope:
        return None
    if isinstance(entry.get("by_employer"), dict) and entry["by_employer"] and not scope \
            and "value" not in entry and "picks" not in entry:
        return None
    words = _text(ans.get("value")) + " " + " ".join(str(x) for x in ans.get("picks") or [])
    if names_other_employer(words, others):
        return None
    return ans, bool(scope)


def extra_scoped(key: str, rctx: ResolveContext) -> bool:
    """True when `extra.<key>` has a `by_employer` answer for this employer (G12, §12.1)."""
    entry = ((rctx.profile or {}).get("extra") or {}).get(key)
    return isinstance(entry, dict) and bool(resolve.employer_answer(entry, rctx)[1])


def _standing_values(profile: dict, rctx: ResolveContext, today: str) -> dict[str, Any]:
    try:
        day = _dt.date.fromisoformat(today)
    except (TypeError, ValueError):
        day = applicant.today_sg()
    comp = applicant.computed_facts(profile, day)
    return {
        "today": today,
        "full_name": resolve.full_name(profile),
        "experience_years": comp["experience_years"],
        "experience_months": comp["experience_months"],
        "graduation_year": comp["graduation_year"],
        "work_rights": applicant.work_rights_text(profile),
        "worked_here": declarations.prior_employment(profile, rctx.employer_name,
                                                     rctx.employer_aliases),
        "current_employee_here": declarations.current_employment(profile, rctx.employer_name,
                                                                 rctx.employer_aliases),
        "previously_applied": bool(rctx.previously_applied),
        "how_heard": resolve.profile_value(profile, "sourcing.how_heard_default")
        or "The employer's careers website",
        "account_email": rctx.account_email or resolve.profile_value(profile, "contact.email"),
    }


def _model_may_read(path: str) -> bool:
    """D-105 / Q-74 §4: a private profile leaf the local model may be shown when
    `rctx.model_sees_sensitive` is on: the paths `llm_extract(sensitive=True)` adds.
    Never `extra` or a standing private fact (they stay "set"/"empty")."""
    b = bare(path)
    return any(b == p or b.startswith(p + ".") for p in applicant.LLM_ALLOW_SENSITIVE)


def fact_catalogue(profile: dict, rctx: ResolveContext, *, today: str) -> list[Fact]:
    """Every fact the model may cite on this attempt, in the fixed order profile,
    extra, standing (§5.1). Pure and deterministic, so FACTS is byte-identical
    across the calls of an attempt (TR-11). With `rctx.model_sees_sensitive` (D-105,
    a local model) a private profile fact on the S allow-list carries its value, so
    FACTS can show it; `private` keeps its meaning (G2d, G7, the audit)."""
    profile = applicant.normalise(profile or {})
    reads = bool(getattr(rctx, "model_sees_sensitive", False))
    out: list[Fact] = []
    for path, value in _leaves(profile):
        private = not _visible(path)
        is_set = _is_set(value)
        shown = is_set and (not private or (reads and _model_may_read(path)))
        out.append(Fact(ref=f"profile:{path}", title=_title(path),
                        value=_text(value) if shown else "",
                        private=private, is_set=is_set, kind=_kind(path, value),
                        entry=_entry_of(path)))
    others = other_employers(rctx)
    for key, entry in ((profile.get("extra") or {}) if isinstance(profile.get("extra"), dict)
                       else {}).items():
        got = _extra_usable(str(key), entry, rctx, others)
        if got is None:
            continue
        ans, _scoped = got
        private = entry.get("sensitive") is True
        words = _text(ans.get("value")) if "value" in ans else _text(list(ans.get("picks") or []))
        is_set = bool(words) or isinstance(ans.get("value"), bool)
        out.append(Fact(ref=f"extra:{key}", title=str(entry.get("title") or key),
                        value="" if private else words, private=private, is_set=is_set,
                        kind=str(entry.get("kind") or "text")))
    values = _standing_values(profile, rctx, today)
    for sid, title, kind, private in STANDING_IDS:
        v = values.get(sid)
        is_set = _is_set(v) or isinstance(v, bool)
        out.append(Fact(ref=f"standing:{sid}", title=title,
                        value="" if private or not is_set else _text(v),
                        private=private, is_set=is_set, kind=kind))
    return out


def listed(fact: Fact) -> bool:
    """Is the fact in FACTS (and so citable)? Empty non-private facts are left out (§5.1)."""
    return fact.private or fact.is_set


def facts_text(facts: Sequence[Fact], *, show_private: bool = False) -> str:
    """The FACTS block: one line per listed fact, in catalogue order (§5.1, §6.2).
    A private fact shows only whether it is set; with `show_private` (D-105, a local
    model) one that carries a value shows `private: <value>`. The model still cites
    the ref with value "" and the program writes the value."""
    lines = []
    for f in facts:
        if not listed(f):
            continue
        if f.private and show_private and f.value:
            lines.append(f"{f.ref} | {f.title} | private: {f.value}")
        elif f.private:
            lines.append(f"{f.ref} | {f.title} | private, {'set' if f.is_set else 'empty'}")
        else:
            lines.append(f"{f.ref} | {f.title} | {f.value}")
    return "\n".join(lines)


def by_ref(facts: Sequence[Fact]) -> dict[str, Fact]:
    return {f.ref: f for f in facts}


# --------------------------------------------------------------------------
# fact_value and relevance (§5.3)
# --------------------------------------------------------------------------

def _ff(field: FieldLike) -> FormField:
    return field.field if isinstance(field, PageField) else field


def rule_match(path: str, field: FieldLike, rules: Any) -> Optional[resolve.Rule]:
    """The tier-2 row that answers this field for `path`: the unique top-scoring row
    for the label (§7.3.1, as tier 2 picks it) when its key, or a virtual `yes_if`
    row's parent, is `path`. None otherwise (another row wins, a tie, no row)."""
    if rules is None or not getattr(rules, "rules", None):
        return None
    f = _ff(field)
    best, _score = rules.select(norm_label(f.label), f)
    if len(best) != 1:
        return None
    r = best[0]
    return r if r.key == path or (r.is_virtual and r.parent == path) else None


def _form_value_map(path: str, value: Any) -> dict[str, tuple[str, ...]]:
    """The Profile form's own wording of an enum value ("none_required" -> "None needed"),
    used when no tier-2 row supplies a value_map."""
    _it, sub = _form_item(path)
    item = sub or _it
    if item is None or not isinstance(value, str):
        return {}
    labels = tuple(lab for v, lab in item.options if v == value)
    return {value: labels} if labels else {}


def _profile_fit(path: str, f: FormField, rctx: ResolveContext, rules: Any) -> Optional[Fit]:
    profile = rctx.profile or {}
    r = rule_match(path, f, rules)
    if r is not None and r.is_virtual:                   # §7.3.3 yes_if
        value = resolve.profile_value(profile, r.parent)
        if resolve._blank(value):
            return None
        if value == "decline":
            return resolve.fit_decline(f)
        return resolve.fit_bool(f, str(value) in r.yes_values)
    value = resolve.profile_value(profile, path)
    b = bare(path)
    if b.startswith("singapore_status.authorised_to_work.") \
            or b.startswith("singapore_status.requires_sponsorship."):
        which, code = b.split(".")[1], b.split(".")[2]   # D-75: a map always has an answer
        value = applicant.work_right(profile, which, code)[0]
    if b == "contact.phone_number":
        value = re.sub(r"\D", "", str(value or ""))       # digits only, as tier 1 wrote it
    if r is not None and r.kind != "country_bool":
        return resolve.fit_kind(f, r.kind, value, value_map=r.value_map, profile=profile)
    kind = _kind(path, value)
    if kind == "file":
        return None
    if kind == "enum":
        return resolve.fit_enum(f, value, _form_value_map(path, value))
    return resolve.fit_kind(f, kind, value, profile=profile)


def _standing_fit(sid: str, f: FormField, rctx: ResolveContext, today: str) -> Optional[Fit]:
    v = _standing_values(rctx.profile or {}, rctx, today).get(sid)
    if sid == "today":
        return resolve.fit_date(f, v)
    if sid in ("experience_years", "experience_months", "graduation_year"):
        return resolve.fit_number(f, v) if isinstance(v, int) else None
    if sid in ("worked_here", "current_employee_here", "previously_applied"):
        return resolve.fit_bool(f, bool(v))
    if sid == "how_heard":
        return resolve.field_map_fit(Canonical.HOW_HEARD, f, rctx)
    if sid == "account_email":
        return resolve.fit_text(f, v)
    return resolve.fit_text(f, v)                    # full_name, work_rights


def fact_value(ref: str, field: FieldLike, rctx: ResolveContext, rules: Any, *,
               today: str = "") -> Optional[Fit]:
    """The value the program writes for a cited fact: (value, option_labels), or None
    when the fact is empty or fits none of the field's options (§5.3). For a private
    fact this is the only way its value reaches the page. A "Category > Leaf" list
    (LL1) is also tried by its leaves, so the program, not the model, maps a fact onto
    a hierarchical option (D-86, review F7)."""
    fit = _fact_value(ref, field, rctx, rules, today=today)
    if fit is None:
        fit = _leaf_fit(ref, field, rctx, rules, today=today)
    return fit


def _leaf_fit(ref: str, field: FieldLike, rctx: ResolveContext, rules: Any, *,
              today: str = "") -> Optional[Fit]:
    """`fact_value` against the leaves of a "Category > Leaf" option list; a leaf that
    occurs under two categories is ambiguous (None)."""
    f = _ff(field)
    if f.fit_type not in CHOICE_TYPES or not any(" > " in o.label for o in f.options):
        return None
    by_leaf: dict[str, list[str]] = {}
    for o in f.options:
        by_leaf.setdefault(o.label.split(" > ")[-1].strip(), []).append(o.label)
    leaf_field = dataclasses.replace(f, options=tuple(Option(leaf) for leaf in by_leaf))
    if isinstance(field, PageField):
        leaf_field = dataclasses.replace(field, field=leaf_field)
    fit = _fact_value(ref, leaf_field, rctx, rules, today=today)
    if fit is None:
        return None
    full: list[str] = []
    for leaf in fit[1]:
        hits = by_leaf.get(leaf, [])
        if len(hits) != 1:
            return None
        full.append(hits[0])
    labels = tuple(full)
    return (list(labels) if f.type is FieldType.MULTI_CHOICE else labels[0]), labels


def _fact_value(ref: str, field: FieldLike, rctx: ResolveContext, rules: Any, *,
                today: str = "") -> Optional[Fit]:
    f = _ff(field)
    ns, _, name = ref.partition(":")
    if not name:
        return None
    if ns == "profile":
        return _profile_fit(name, f, rctx, rules)
    if ns == "extra":
        entry = ((rctx.profile or {}).get("extra") or {}).get(name)
        if not isinstance(entry, dict) or applicant.extra_entry_errors(name, entry):
            return None
        ans, _scope = resolve.employer_answer(entry, rctx)
        return resolve.extra_fit(f, str(entry.get("kind")), ans)
    if ns == "standing":
        return _standing_fit(name, f, rctx, today or applicant.today_sg().isoformat())
    return None


def _phrases_in(phrases: Iterable[str], toks: Sequence[str]) -> set[str]:
    return {p for p in phrases if contains_run(toks, p.split())}


def about_other_person(field: FieldLike) -> bool:
    """D-84 R4: the question is about someone other than the applicant (an emergency
    contact, a referee, next of kin, ...). Read from the label, the entry heading and
    the section; help text and context only for a generic label ("Please specify"), so
    "Email" with help "the hiring manager will contact you here" stays the applicant's
    own question (review F5)."""
    f = _ff(field)
    parts = [f.label, f.section]
    if isinstance(field, PageField):
        parts.append(field.group_title)
    if is_generic(norm_label(f.label)):
        parts += [f.description, field.context if isinstance(field, PageField) else ""]
    return bool(_phrases_in(OTHER_PERSON, tokens(" ".join(p for p in parts if p))))


# Q-46(a): a field inside a past-entry section (a job, a school) is about that entry, so
# the applicant's own contact/address facts never answer it, with or without an entry
# group (the reader may not have grouped it).
ENTRY_SECTION_PHRASES = ("work experience", "experience", "employment", "work history",
                         "employment history", "education", "academic", "school")
ADDRESS_WORDS = ("address", "city", "town", "country", "postal", "postcode", "zip",
                 "street", "location")


def in_entry_section(field: FieldLike) -> bool:
    """Q-46(a): the field sits in a repeated past-entry section (its entry group, its
    group heading or its section names work experience / education)."""
    f = _ff(field)
    parts = [f.section.replace("_", " ")]
    if isinstance(field, PageField):
        if field.group:
            return True
        parts.append(field.group_title)
    return bool(_phrases_in(ENTRY_SECTION_PHRASES, tokens(" ".join(p for p in parts if p))))


def _own_contact_ref(ref: str) -> bool:
    """A contact/identity ref or one naming an address part (`contact.city`, ...)."""
    if ref.startswith(CONTACT_IDENTITY_REFS):
        return True
    ns, _, name = ref.partition(":")
    if ns == "profile" and ("[" in name or name.split(".", 1)[0] in PROFILE_LIST.values()):
        return False                                 # an entry's own path (experience[1].location)
    return bool(set(re.split(r"[._\[\]]+", name.lower())) & set(ADDRESS_WORDS))


# Q-46(c): "worked here" / "current employee here" answer only a question about THIS
# employer (it says us / our / here / this company, or names the employer or an alias);
# "Have you ever worked for the Government?" is not one.
EMPLOYER_STANDING_REFS = ("standing:worked_here", "standing:current_employee_here")
THIS_EMPLOYER_RUNS = declarations.THIS_EMPLOYER_RUNS      # one list, in declarations (D-90 (4))


def names_this_employer(field: FieldLike, rctx: Optional[ResolveContext]) -> bool:
    """Q-46(c): the label (or its help text) refers to the employer of this application.
    The one implementation is `declarations.names_this_employer` (tier 4 uses it too)."""
    f = _ff(field)
    return declarations.names_this_employer(f"{f.label} {f.description}",
                                            declarations.employer_names_of(rctx))


OWN_DETAIL_PATHS = ("identity.legal_first_name", "identity.legal_last_name",
                    "identity.preferred_name", "contact.city")


def own_details(rctx: ResolveContext) -> tuple[list[list[str]], list[str]]:
    """D-84 R4 on every route (review F2): the applicant's own name parts, full name and
    home city as token runs, plus the free-text S values (email, phone, address, ...)."""
    p = applicant.normalise(rctx.profile or {})
    runs: list[list[str]] = []
    for path in OWN_DETAIL_PATHS:
        v = resolve.profile_value(p, path)
        if isinstance(v, str) and tokens(v):
            runs.append(tokens(v))
    full = _standing_values(p, rctx, "1970-01-01").get("full_name")
    if isinstance(full, str) and tokens(full):
        runs.append(tokens(full))
    return runs, s_values(p, rctx.account_email or "")


def names_own_detail(text: str, rctx: ResolveContext,
                     details: Optional[tuple[list[list[str]], list[str]]] = None) -> bool:
    """True when `text` carries one of the applicant's own details (`own_details`)."""
    runs, svals = details if details is not None else own_details(rctx)
    toks = tokens(text or "")
    if any(contains_run(toks, r) for r in runs):
        return True
    low, digits = (text or "").lower(), re.sub(r"\D", "", text or "")
    for v in svals:
        d = re.sub(r"\D", "", v)
        if v.lower() in low or (len(d) >= 6 and d == re.sub(r"[\s+\-().]", "", v) and d in digits):
            return True
    return False


def _title_words(title: str, ref: str) -> set[str]:
    if re.match(r"^profile:(experience|education|languages)\[\d+\]\.", ref):
        title = title.split(":", 1)[-1]            # the entry's own word is not the question
    return {t for t in content_tokens(title) if t not in TITLE_GENERIC and not t.isdigit()}


def _synonym_hit(title_toks: Sequence[str], label_toks: Sequence[str]) -> bool:
    for group in FACT_TITLE_SYNONYMS:
        if _phrases_in(group, title_toks) and _phrases_in(group, label_toks):
            return True
    return False


def relevant(ref: str, field: FieldLike, rules: Any, *, facts: Sequence[Fact] = (),
             rctx: Optional[ResolveContext] = None) -> bool:
    """G2(b): True when the fact can be about this question (§5.3): a tier-2 row for its
    path (or the `extra` entry's labels) matches the label, or the label shares a content
    word with the fact's title or a FACT_TITLE_SYNONYMS group. Never for the applicant's
    contact/identity facts on a question about another person (D-84 R4)."""
    f = _ff(field)
    if ref.startswith(CONTACT_IDENTITY_REFS) and about_other_person(field):
        return False
    if _own_contact_ref(ref) and in_entry_section(field):
        return False                                 # Q-46(a): an entry's Location is not home
    if ref in EMPLOYER_STANDING_REFS and not names_this_employer(field, rctx):
        return False                                 # Q-46(c): "worked for the Government"
    ns, _, name = ref.partition(":")
    label_norm = norm_label(f.label)
    if ns == "profile" and rule_match(name, f, rules) is not None:
        return True
    if ns == "standing" and name in STANDING_RULE_KEYS \
            and rules is not None and getattr(rules, "rules", None):
        best, _s = rules.select(label_norm, f)
        if len(best) == 1 and best[0].key == STANDING_RULE_KEYS[name]:
            return True
    if ns == "extra" and rctx is not None:
        entry = ((rctx.profile or {}).get("extra") or {}).get(name)
        labels = entry.get("labels") if isinstance(entry, dict) else None
        if isinstance(labels, list) and any(isinstance(x, str) and (
                norm_label(x) == label_norm or x.split(" | ", 1)[0].strip() == label_norm)
                for x in labels):
            return True
    fact = by_ref(facts).get(ref) if facts else None
    title = fact.title if fact else _ref_title(ref, rctx)
    words = _title_words(title, ref)
    label_toks = [t for t in label_norm.split() if t not in STOP_WORDS and t not in TITLE_GENERIC]
    if words & set(label_toks):
        return True
    title_toks = norm_label(title.split(":", 1)[-1] if ":" in title else title).split()
    return _synonym_hit(title_toks, label_norm.split())


def _ref_title(ref: str, rctx: Optional[ResolveContext]) -> str:
    ns, _, name = ref.partition(":")
    if ns == "profile":
        return _title(name)
    if ns == "standing":
        return next((t for sid, t, _k, _p in STANDING_IDS if sid == name), name)
    if ns == "extra" and rctx is not None:
        entry = ((rctx.profile or {}).get("extra") or {}).get(name)
        if isinstance(entry, dict):
            return str(entry.get("title") or name)
    return name.replace("_", " ")


# --------------------------------------------------------------------------
# Entries (§5.2, §10 E2)
# --------------------------------------------------------------------------

# Site section -> source entry kind (resume_entries kinds; profile list names).
SECTION_KINDS = {"work_experience": "experience", "experience": "experience",
                 "education": "education", "languages": "language", "language": "language",
                 "websites": "link", "links": "link", "certifications": "other"}
PROFILE_LIST = {"experience": "experience", "education": "education", "language": "languages"}
NAME_WORDS = {"experience": ("company", "employer", "organisation", "organization"),
              "education": ("school", "university", "institution", "college"),
              "language": ("language",), "link": ("url", "website", "link", "linkedin")}
TITLE_WORDS = {"experience": ("title", "position", "role"),
               "education": ("degree", "qualification")}
MATCH_MIN = 0.5            # E2: overlap coefficient with an employer match
MATCH_MIN_NO_NAME = 0.8    # E2: with no employer shown


def overlap(a: Iterable[str], b: Iterable[str]) -> float:
    """The overlap coefficient |A ∩ B| / min(|A|, |B|) (§10 E2, TR-10); 0 when one is empty."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def _url_norm(u: str) -> str:
    u = (u or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def _shown_text(v: Any) -> str:
    return ", ".join(v) if isinstance(v, list) else str(v or "")


def _site_parts(kind: str, group_fields: Sequence[PageField]) -> tuple[str, str]:
    """(the shown employer/school/language/url, the shown title/degree) of a site entry."""
    name = title = ""
    for pf in group_fields:
        toks = tokens(pf.field.label)
        shown = _shown_text(pf.shown).strip()
        if not shown:
            continue
        if not name and (any(w in toks for w in NAME_WORDS.get(kind, ()))
                         or (kind == "link" and pf.field.type is FieldType.URL)):
            name = shown
        elif not title and any(w in toks for w in TITLE_WORDS.get(kind, ())):
            title = shown
    return name, title


def _block_from_entry(lst: str, e: dict) -> str:
    """A profile entry's own facts as a block (the corpus when the resume has none)."""
    t = applicant.json_safe(e)
    if lst == "experience":
        lines = [t.get("title"), t.get("employer"), t.get("location"),
                 " to ".join(str(x) for x in (t.get("start"), t.get("end") or "present") if x),
                 t.get("description")]
    elif lst == "education":
        lines = [", ".join(str(x) for x in (t.get("degree"), t.get("major")) if x),
                 t.get("institution"),
                 " to ".join(str(x) for x in (t.get("start"), t.get("end")) if x),
                 f"{t.get('grade_type') or 'grade'} {t.get('grade')}/{t.get('grade_scale')}"
                 if t.get("grade") else ""]
    else:
        lines = [f"{t.get('language')}: spoken {t.get('spoken') or '-'}, "
                 f"written {t.get('written') or '-'}"]
    return "\n".join(str(x) for x in lines if x)


def source_entries(kind: str, rctx: ResolveContext) -> list[tuple[str, str, str, str]]:
    """(entry id, name, title, block) per source entry of a kind: the profile's entries
    when it has any (template rows dropped), else `rctx.resume_entries` (§10 E2)."""
    profile = rctx.profile or {}
    if kind == "link":
        links = profile.get("links") or {}
        return [(f"links.{k}", str(links.get(k)), "", str(links.get(k)))
                for k in ("linkedin", "github", "portfolio")
                if isinstance(links, dict) and links.get(k)]
    lst = PROFILE_LIST.get(kind)
    out = []
    if lst:
        for i, e in enumerate(profile.get(lst) or []):
            if not isinstance(e, dict) or _template_entry(lst, e):
                continue
            if kind == "experience":
                name, title = str(e.get("employer") or ""), str(e.get("title") or "")
            elif kind == "education":
                name, title = str(e.get("institution") or ""), str(e.get("degree") or "")
            else:
                name, title = str(e.get("language") or ""), ""
            out.append((f"{lst}[{i}]", name, title, _block_from_entry(lst, e)))
    if out or kind == "language":
        return out
    return [(eid, "", "", text) for eid, k, text in rctx.resume_entries if k == kind]


def _score(kind: str, site_name: str, site_title: str, src: tuple[str, str, str, str]) -> float:
    _eid, name, title, block = src
    if kind == "language":
        return 1.0 if site_name and norm_label(site_name) == norm_label(name) else 0.0
    if kind == "link":
        return 1.0 if site_name and _url_norm(site_name) == _url_norm(name) else 0.0
    if name:                                           # a profile entry
        if site_name:
            if not declarations.company_match(site_name, name):
                return 0.0
            if not site_title or not title:
                return MATCH_MIN                       # employer alone: titles to fill
            ov = overlap(content_tokens(site_title), content_tokens(title))
            return ov if ov >= MATCH_MIN else 0.0
        ov = overlap(content_tokens(site_title), content_tokens(title))
        return ov if ov >= MATCH_MIN_NO_NAME else 0.0
    first = block.strip().splitlines()[0] if block.strip() else ""
    if site_name:                                      # a resume entry (text only)
        emp = declarations.employer_norm(site_name).split()
        if not emp or not contains_run(tokens(block), emp):
            return 0.0
        if not site_title:
            return MATCH_MIN
        ov = overlap(content_tokens(site_title), content_tokens(first))
        return ov if ov >= MATCH_MIN else 0.0
    ov = overlap(content_tokens(site_title), content_tokens(first))
    return ov if ov >= MATCH_MIN_NO_NAME else 0.0


def group_id(section: str, index: int) -> str:
    return f"{section}#{index}"


def match_entries(sections: Sequence[EntrySection], fields: Sequence[PageField],
                  rctx: ResolveContext) -> dict[str, Optional[str]]:
    """E2: site entry group id -> the source entry id it is, or None (junk, E3).
    A site entry matches X when the shown employer/school company-matches X's and the
    title/degree overlap is >= 0.5 (>= 0.8 with no employer shown); languages by name,
    websites by URL. The unique best wins; a tie is unmatched; a source entry is
    matched once (the higher score, then the earlier site entry)."""
    out: dict[str, Optional[str]] = {}
    claims: dict[str, tuple[float, str]] = {}
    for sec in sections:
        kind = SECTION_KINDS.get(sec.section, "other")
        sources = source_entries(kind, rctx) if kind != "other" else \
            [(eid, "", "", text) for eid, k, text in rctx.resume_entries if k == "other"]
        for g in sec.entries:
            gid = group_id(sec.section, g.index)
            gf = [pf for pf in fields if pf.group == gid]
            site_name, site_title = _site_parts(kind, gf)
            scored = sorted(((_score(kind, site_name, site_title, s), s[0]) for s in sources),
                            reverse=True)
            out[gid] = None
            if not scored or scored[0][0] <= 0:
                continue
            if len(scored) > 1 and scored[1][0] == scored[0][0]:
                continue                                 # a tie: unmatched
            sc, eid = scored[0]
            prev = claims.get(eid)
            if prev is not None:
                if prev[0] >= sc:
                    continue
                out[prev[1]] = None
            claims[eid] = (sc, gid)
            out[gid] = eid
    return out


def entry_blocks(rctx: ResolveContext, profile: Optional[dict] = None) -> dict[str, str]:
    """Source entry id -> its block (§5.2): the master resume's entry when
    `rctx.resume_entries` has one for that entry, else the profile entry's own facts.
    A profile entry takes the resume entry that E2-matches it, so a block always
    belongs to the same job or school as the entry's facts."""
    rctx_p = rctx if profile is None else dataclasses.replace(rctx, profile=profile)
    out: dict[str, str] = {}
    for kind in ("experience", "education", "language", "link", "other"):
        resume = [(eid, text) for eid, k, text in rctx_p.resume_entries if k == kind]
        srcs = source_entries(kind, rctx_p) if kind != "other" else \
            [(eid, "", "", text) for eid, text in resume]
        for eid, name, title, block in srcs:
            if not name:                         # a resume entry is its own block
                out[eid] = block
                continue
            best = None
            if kind in ("experience", "education"):
                hits = [(_score(kind, name, title, (rid, "", "", text)), rid, text)
                        for rid, text in resume]
                hits = sorted((h for h in hits if h[0] > 0), reverse=True)
                if hits and (len(hits) == 1 or hits[1][0] < hits[0][0]):
                    best = hits[0][2]
            out[eid] = best if best else block
    return out


def entry_fact_text(facts: Sequence[Fact], entry: str) -> str:
    """The visible facts of one entry, one value per line (part of its G3 corpus)."""
    return "\n".join(f.value for f in facts if f.entry == entry and not f.private and f.value)


def check_entries(sections: Sequence[EntrySection], rctx: ResolveContext) -> None:
    """§5.2: a page showing imported entries for a section the applicant has no source
    entries for (no profile entries, no resume entries) cannot be checked: raise
    ApplyFailure(PROFILE_INCOMPLETE, <section>) before anything is changed."""
    for sec in sections:
        if not sec.entries:
            continue
        kind = SECTION_KINDS.get(sec.section)
        if kind not in ("experience", "education"):
            continue
        if not source_entries(kind, rctx):
            raise ApplyFailure(ReasonCode.PROFILE_INCOMPLETE, sec.section)


# --------------------------------------------------------------------------
# Privacy (§6.5), clock and cache keys (§13.3)
# --------------------------------------------------------------------------

def _date_forms(iso: str) -> list[str]:
    return applicant.date_forms(iso)           # moved to applicant (Q-74 R2), one copy


def s_values(profile: dict, account_email: str) -> list[str]:
    """The free-text S values that must never be in a prompt (§6.5, H4): contact values
    except city/country (email, backup email, phone in its usual spellings, address lines,
    postal code), the date of birth in common date forms, NRIC last 4, ORD date, race
    "other" text, a free-text religion, and the account email (required: under D-72
    the ATS account's mailbox differs from contact.email; pass `rctx.account_email`,
    review F4). Enum S values (gender,
    race, residency, NS, marital status) are ordinary words and are not listed; locks
    and G7 keep the model off those questions. Longest first; 3+ characters."""
    p = applicant.normalise(profile or {})
    get = lambda path: resolve.profile_value(p, path)       # noqa: E731
    vals: list[str] = []
    contact = p.get("contact") if isinstance(p.get("contact"), dict) else {}
    for k, v in contact.items():
        if f"contact.{k}" in applicant.CONTACT_NOT_SENSITIVE or k in ("phone_country_code",):
            continue
        if isinstance(v, str) and v.strip():
            vals.append(v.strip())
    phone = re.sub(r"\D", "", str(get("contact.phone_number") or ""))
    cc = re.sub(r"\D", "", str(get("contact.phone_country_code") or ""))
    if phone:
        vals += [phone, f"{phone[:4]} {phone[4:]}", f"{phone[:4]}-{phone[4:]}"]
        if cc:
            vals += [f"+{cc}{phone}", f"{cc}{phone}", f"+{cc} {phone}",
                     f"+{cc} {phone[:4]} {phone[4:]}", f"({cc}) {phone}"]
    postal = re.sub(r"\D", "", str(get("contact.postal_code") or ""))
    if postal:
        vals.append(postal)
    dob = applicant.json_safe(get("identity.date_of_birth"))
    if isinstance(dob, str):
        vals += _date_forms(dob.strip())
    for path in ("singapore_status.nric_last4", "singapore_status.race_other"):
        v = get(path)
        if isinstance(v, str) and v.strip():
            vals.append(v.strip())
    ord_date = applicant.json_safe(get("singapore_status.ord_date"))
    if isinstance(ord_date, str) and ord_date.strip():
        vals += _date_forms(ord_date.strip())
    religion = get("singapore_status.religion")
    if isinstance(religion, str) and religion.strip() and religion.strip().lower() != "decline":
        vals.append(religion.strip())
    if account_email and account_email.strip():
        vals.append(account_email.strip())
    uniq = {v for v in vals if len(v) >= 3}
    return sorted(uniq, key=lambda s: (-len(s), s))


def enum_s_values(profile: dict) -> list[str]:
    """The applicant's private values that `s_values` leaves out because they are ordinary
    words (gender, race, residency, NS, marital status, nationality, EEO answers): each
    private leaf's value and its Profile-form wording. `redact` must not use them (they
    would blank "Chinese" the language); `llm_fill.pick_option` refuses to send any of
    them to the model (review F1). Lowercase, 2+ characters."""
    p = applicant.normalise(profile or {})
    out: set[str] = set()
    for path, v in _leaves(p):
        if _visible(path) or isinstance(v, (dict, list)) or v is None or isinstance(v, bool):
            continue
        text = str(applicant.json_safe(v)).strip()
        if len(text) < 2:
            continue
        out.add(text.lower())
        for labels in _form_value_map(path, text).values():
            out.update(x.strip().lower() for x in labels if len(x.strip()) >= 2)
    return sorted(out)


def today_sg(now_utc: float) -> str:
    """Today in Asia/Singapore (UTC+8) as YYYY-MM-DD for a UTC epoch (TR-5): 16:00Z is
    already the next day."""
    return _dt.datetime.fromtimestamp(float(now_utc), applicant.SGT).date().isoformat()


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def hash_key(rctx: ResolveContext) -> bytes:
    """The HMAC key of every stored hash that covers a personal value (`field_sig`,
    `facts_used_hash`): sha256 of the profile's S values and the account email, so a
    stored hash can't be brute-forced back to a short private value (NF-02)."""
    return hashlib.sha256("\n".join(s_values(rctx.profile or {}, rctx.account_email or ""))
                          .encode("utf-8")).digest()


def field_sig(field: PageField, qualified_label: str, *, key: bytes) -> str:
    """The cache key of one field (§13.3): kind, qualified label, sorted option norms,
    group, origin and the shown value, as an HMAC with `hash_key(rctx)` (D-86, review F8:
    a site-prefilled phone or postal code can't be recovered from the stored key)."""
    f = field.field
    opts = sorted(norm_label(o.label) for o in f.options)
    shown = _shown_text(field.shown)
    msg = "\n".join([f.type.value, qualified_label, "\x1f".join(opts), field.group,
                     field.origin.value, norm_label(shown)])
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def inputs_hash(redacted_resume: str, jd_text: str, *, sees_private: bool = False) -> str:
    """sha256(redacted resume text + JD text)[:16] (§13.3): a cache row is reused only
    for the same resume and posting."""
    # `sees_private` (D-105, the effective switch) is folded in: flipping it re-runs cached
    # fills once, because the prompt text changed.
    return _sha16((redacted_resume or "") + "\n\x1e\n" + (jd_text or "")
                  + ("\n\x1e\x1dprivate-visible" if sees_private else ""))


def facts_used_hash(refs: Iterable[str], rctx: ResolveContext, *, today: str = "") -> str:
    """A keyed hash of the current values of the cited facts (§13.3): a row whose hash no
    longer matches is a miss, so answering one question in Profile only re-asks the
    decisions that cited what changed. Keyed with the profile's own S values, so a
    stored hash cannot be brute-forced back to a short private value (NF-02)."""
    profile = rctx.profile or {}
    parts = []
    for ref in sorted(set(r for r in refs if r)):
        ns, _, name = ref.partition(":")
        if ns == "profile":
            v = applicant.json_safe(resolve.profile_value(profile, name))
        elif ns == "extra":
            v = applicant.json_safe(((profile.get("extra") or {}).get(name)))
        elif ns == "standing":
            v = applicant.json_safe(_standing_values(profile, rctx, today or "1970-01-01")
                                    .get(name)) if name != "today" else "today"
        else:
            v = None
        parts.append(ref + "=" + json.dumps(v, sort_keys=True, ensure_ascii=False, default=str))
    return hmac.new(hash_key(rctx), "\n".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def is_choice(field: FieldLike) -> bool:
    return _ff(field).fit_type in CHOICE_TYPES
