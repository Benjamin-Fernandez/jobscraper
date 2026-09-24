"""Resume ingest: turn the resume on disk into the profile every stage matches on.

Why this exists. v1 kept the candidate's skills and target roles in a
hand-written `config/profile.yaml`, which drifted from the actual resume the day
it was written. v2 makes the resume the single source of truth (D-1): drop a new
`data/resume.pdf` in, and the match vocabulary follows.

Why it is cheap. The resume changes a handful of times a year, the pipeline runs
several times a day. So the stage is keyed on the file's SHA-256: when the hash
matches the one recorded in the derived profile, nothing is extracted and no
model is called. Extraction and the model call happen on change only.

Two halves:

  text      (M2-T1) find the file, hash it, extract its text. Nothing is PDF-
            or DOCX-specific beyond `_EXTRACTORS`.
  profile   (M2-T2) one cheap model call turns that text into
            `data/profile.derived.yaml` (PRD 8.3[1]); `load_derived_profile`
            merges `config/profile.overrides.yaml` on top. That merged dict is
            contract 1 of PRD 0.6 - what the filter and decide stages consume.

Why the overrides are a separate file. The derived file is regenerated whenever
the resume changes, so hand edits there would be lost. The overrides file is
never written by code. Its lists are additive, its scalars replace, and its
`*_remove` lists drop generated entries the user disagrees with.

`profile_version` - the key decisions are cached under (PRD 8.3[5]). It is
engine-owned and only ever goes up. `ingest()` bumps it when:
  1. re-deriving produced a profile that differs from the one on disk (a
     re-derive that comes back identical keeps the version, so a forced refresh
     does not re-decide the whole corpus for nothing - see open question Q3);
  2. the overrides file's *content* changed (comments do not count). No model
     call is needed for this; the file's hash is recorded in the derived YAML;
  3. by hand: `python -m jobscraper profile --bump`, or `bump_profile_version`.
The decision cache (M4-T3) needs nothing more than to key on the merged
profile's `profile_version`.

Only backends.py talks to a model (PRD 8.2); this module hands it a prompt.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from .. import backends
from ..config import Config

# First found wins. PDF first: it is what people actually send to employers,
# so it is the version most likely to be current.
RESUME_NAMES = ("resume.pdf", "resume.docx")


class ResumeError(RuntimeError):
    """The resume is missing or unreadable. Never guessed around - a wrong
    profile silently mis-filters every posting downstream (M2-T0)."""


@dataclass(frozen=True)
class ResumeText:
    path: Path
    source_hash: str        # "sha256:<hex>", the form profile.derived.yaml stores
    text: str               # "" when unchanged: extraction was skipped
    changed: bool


def find_resume(resume_dir: str | Path) -> Path:
    resume_dir = Path(resume_dir)
    for name in RESUME_NAMES:
        p = resume_dir / name
        if p.is_file():
            return p
    raise ResumeError(
        f"no resume found - put {' or '.join(RESUME_NAMES)} in {resume_dir}")


def file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return "sha256:" + h.hexdigest()


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _docx_text(path: Path) -> str:
    import docx

    doc = docx.Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    # Resumes lay skills out in tables; paragraphs alone would drop them.
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


_EXTRACTORS = {".pdf": _pdf_text, ".docx": _docx_text}


def _tidy(text: str) -> str:
    """Collapse the whitespace noise extractors leave, keep line structure."""
    lines = (re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines())
    return "\n".join(ln for ln in lines if ln)


def extract_text(path: str | Path) -> str:
    path = Path(path)
    fn = _EXTRACTORS.get(path.suffix.lower())
    if fn is None:
        raise ResumeError(f"unsupported resume format: {path.name}")
    try:
        raw = fn(path)
    except ResumeError:
        raise
    except Exception as exc:
        raise ResumeError(f"could not read {path.name}: {exc}") from exc
    return _tidy(raw)


def load_resume(resume_dir: str | Path, previous_hash: Optional[str] = None,
                force: bool = False) -> ResumeText:
    """Hash the resume; extract its text only if the hash moved (or `force`).

    `previous_hash` is the `source_hash` of the profile already on disk. When it
    matches, the returned `text` is empty and `changed` is False - the caller
    has nothing to do.
    """
    path = find_resume(resume_dir)
    digest = file_hash(path)
    if not force and previous_hash and previous_hash == digest:
        return ResumeText(path, digest, "", changed=False)
    text = extract_text(path)
    if not text.strip():
        raise ResumeError(
            f"{path.name} has no extractable text - is it a scanned image? "
            "Export it from the original document instead.")
    return ResumeText(path, digest, text, changed=True)


# ================================================================ profile


class ProfileError(RuntimeError):
    """The derived profile could not be produced or read. Nothing is written."""


# Keys the model produces; the derived file adds its own bookkeeping around them.
_DERIVED_KEYS = ("summary", "skills", "years_experience", "graduation",
                 "target_titles", "title_aliases")

_OVERRIDE_LISTS = ("skills", "target_titles")
_OVERRIDE_REMOVES = ("skills_remove", "target_titles_remove")
_OVERRIDE_SCALARS = ("summary", "years_experience", "graduation")
_OVERRIDE_KEYS = (_OVERRIDE_LISTS + _OVERRIDE_REMOVES + _OVERRIDE_SCALARS
                  + ("title_aliases",))

# Resumes are a page or two. The cap only guards against a pathological file.
_MAX_PROMPT_CHARS = 20000
_SUMMARY_WORDS = 80

SYSTEM_PROMPT = """\
You read a candidate's resume and describe them for a job-matching engine.
Return ONLY one JSON object - no prose, no code fence - with exactly these keys:

"summary": one factual paragraph of at most 80 words, third person: level,
  strongest technical skills, domains worked in. It is shown verbatim to a model
  that judges job postings for this candidate.

"skills": technical skills as lowercase canonical names, ONE per entry, as they
  would be written in a job description: programming languages, frameworks,
  libraries, databases, cloud platforms, infrastructure and tooling, e.g.
  "python", "spring boot", "postgresql", "kubernetes", "github actions", plus
  established engineering terms such as "microservices", "rest api", "ci/cd",
  "distributed systems". Use the common full name ("postgresql" not "postgres",
  "kubernetes" not "k8s"). Never combine entries ("typescript" and "javascript",
  not "typescript/javascript"; no parentheses). No soft skills, no spoken
  languages, no activities or domains such as "backend development",
  "full-stack development", "payment systems" or "database optimization".

"target_titles": the job titles this candidate would plausibly be HIRED under -
  NOT the titles the resume literally contains. Infer them from the skills and
  experience: a resume listing Ansible, Kubernetes and ArgoCD implies
  "site reliability engineer" and "devops engineer" even if those words never
  appear in it. These titles are matched against posting titles, so use the
  exact short form employers post. Choose from this vocabulary whenever a title
  fits: software engineer, backend engineer, frontend engineer, full stack
  engineer, platform engineer, infrastructure engineer, site reliability
  engineer, devops engineer, cloud engineer, systems engineer, data engineer,
  machine learning engineer, ai engineer, security engineer, mobile engineer,
  embedded engineer, blockchain engineer - and the "developer" form of any of
  them (e.g. "backend developer"). Go outside it only for a title that is
  equally common on job boards. Never invent or lengthen a title: "backend
  software engineer", "cloud systems engineer" and "microservices engineer" are
  wrong. Always include "software engineer" for anyone who writes software.
  Every title in lowercase singular form, with no seniority or level words (no
  junior, senior, graduate, intern, i, ii). Give 6 to 12 titles, most likely
  first.

"title_aliases": an object mapping abbreviations or variants that appear in job
  titles onto one of your target_titles, e.g. {"sre": "site reliability
  engineer", "swe": "software engineer"}. Lowercase.

"years_experience": integer years of full-time professional experience AFTER
  graduating. Internships never count, however long or full-time, nor do
  part-time or student roles. A student or new graduate whose experience is all
  internships is 0.

"graduation": "YYYY-MM" of the most recent degree completion, past or expected,
  or null if none is stated.
"""


@dataclass(frozen=True)
class IngestResult:
    status: str             # "unchanged" | "derived" | "overrides-changed"
    profile_version: int
    message: str


# ---------------------------------------------------------------- parsing


def _parse_json(text: str) -> dict[str, Any]:
    """Ported from llm.py (legacy, not importable from a stage): tolerate a code
    fence or a sentence around the object; anything else is an empty dict."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        out = json.loads(text)
        return out if isinstance(out, dict) else {}
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                out = json.loads(m.group(0))
                return out if isinstance(out, dict) else {}
            except Exception:
                pass
    return {}


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


# Role nouns whose plural is a plain trailing "s". The prompt asks for singular
# titles; this catches the model forgetting, without mangling "devops" or
# "systems engineer".
_PLURAL_ROLE = re.compile(
    r"(engineer|developer|architect|analyst|scientist|consultant|specialist"
    r"|administrator|programmer|manager|researcher|designer|technologist)s$")


def _singular(title: str) -> str:
    return _PLURAL_ROLE.sub(r"\1", title)


def _explode_skill(skill: str) -> list[str]:
    """One technology per entry, so the keyword matcher can find each.

    "authentication (oauth2, okta sso)" -> authentication, oauth2, okta sso.
    "typescript/javascript" -> typescript, javascript - but only when every part
    is a single real word: "ci/cd", "ai/ml" and "tcp/ip networking" are single
    terms and stay.
    """
    m = re.fullmatch(r"(.*?)\s*\((.*)\)\s*", skill)
    if m:
        parts = [m.group(1)] + m.group(2).split(",")
        return [p for part in parts for p in _explode_skill(_norm(part))]
    pieces = [p.strip() for p in skill.split("/")]
    if len(pieces) > 1 and all(len(p) >= 3 and " " not in p for p in pieces):
        return pieces
    return [skill] if skill else []


_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


def _graduation(value: Any) -> Optional[str]:
    """"YYYY-MM" (or "YYYY"), from whatever shape the model chose; else None."""
    if isinstance(value, dict):   # seen live: {"degree": ..., "expected_date": ...}
        dated = [v for k, v in value.items() if "date" in str(k).lower()]
        value = dated[0] if dated else None
    if value is None:
        return None
    s = _norm(value)
    m = re.search(r"\b(\d{4})-(\d{1,2})\b", s)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"\b([a-z]{3})[a-z]*\.?\s+(\d{4})\b", s)
    if m and m.group(1) in _MONTHS:
        return f"{m.group(2)}-{_MONTHS[m.group(1)]:02d}"
    m = re.fullmatch(r"(\d{4})", s)
    return m.group(1) if m else None


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for s in items:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _str_list(value: Any, key: str, source: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ProfileError(f"{source}: `{key}` must be a list of strings")
    return [_norm(v) for v in value]


def _aliases(value: Any, source: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProfileError(f"{source}: `title_aliases` must be a mapping")
    out = {}
    for k, v in value.items():
        k, v = _norm(k), _singular(_norm(v))
        if k and v and k != v:
            out[k] = v
    return out


def _alias_pairs(value: Any) -> dict[str, str]:
    """Coerce the model's aliases to a mapping. Seen live: a list instead of an
    object. Aliases are secondary, so an unusable shape becomes {} rather than
    failing the whole profile. (The overrides file stays strict: `_aliases`.)"""
    if isinstance(value, dict):
        return value
    out: dict[str, str] = {}
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                vals = [v for v in item.values() if isinstance(v, str)]
                if len(vals) == 2:
                    out[vals[0]] = vals[1]
            elif (isinstance(item, (list, tuple)) and len(item) == 2
                  and all(isinstance(v, str) for v in item)):
                out[item[0]] = item[1]
    return out


def _years(value: Any, source: str) -> int:
    if value is None:
        return 0
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        raise ProfileError(f"{source}: `years_experience` must be a number, "
                           f"got {value!r}")


def _validate(raw: dict[str, Any]) -> dict[str, Any]:
    """Model answer -> the derived keys, normalised. Refuses rather than guesses."""
    src = "model output"
    if not raw:
        raise ProfileError(f"{src}: no JSON object found")
    summary = raw.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ProfileError(f"{src}: `summary` missing or empty")
    summary = " ".join(summary.split()[:_SUMMARY_WORDS])

    skills = _dedupe([p for s in _str_list(raw.get("skills"), "skills", src)
                      for p in _explode_skill(s)])
    titles = _dedupe([_singular(t) for t in
                      _str_list(raw.get("target_titles"), "target_titles", src)])
    if not skills:
        raise ProfileError(f"{src}: `skills` is empty")
    if not titles:
        raise ProfileError(f"{src}: `target_titles` is empty")
    # An alias is only useful if it folds onto a title we are looking for.
    aliases = {k: v for k, v in _aliases(_alias_pairs(raw.get("title_aliases")),
                                         src).items()
               if v in titles}
    return {
        "summary": summary,
        "skills": skills,
        "years_experience": _years(raw.get("years_experience"), src),
        "graduation": _graduation(raw.get("graduation")),
        "target_titles": titles,
        "title_aliases": aliases,
    }


# ---------------------------------------------------------------- files


def _read_yaml(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProfileError(f"{path} is not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ProfileError(f"{path} must be a mapping")
    return data


_HEADER = """\
# GENERATED from your resume by `python -m jobscraper profile`. Do not edit:
# this file is rewritten whenever the resume changes. Put corrections in
# config/profile.overrides.yaml instead (PRD section 8.3[1]).
"""


def _write_derived(path: Path, doc: dict[str, Any]) -> None:
    """Atomic write: a crash mid-write must not leave half a profile behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _HEADER + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True,
                                    width=88)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load_overrides(path: str | Path) -> dict[str, Any]:
    """Read and validate the overrides file. Missing file = no overrides."""
    path = Path(path)
    data = _read_yaml(path) or {}
    unknown = sorted(set(data) - set(_OVERRIDE_KEYS))
    if unknown:
        hint = (" (profile_version is engine-owned; use `profile --bump`)"
                if "profile_version" in unknown else "")
        raise ProfileError(f"{path}: unknown key(s) {unknown}{hint}; "
                           f"allowed: {list(_OVERRIDE_KEYS)}")
    out: dict[str, Any] = {}
    for key in _OVERRIDE_LISTS + _OVERRIDE_REMOVES:
        out[key] = _str_list(data.get(key), key, str(path))
    out["title_aliases"] = _aliases(data.get("title_aliases"), str(path))
    for key in _OVERRIDE_SCALARS:
        if data.get(key) is not None:
            out[key] = data[key]
    if "summary" in out:
        out["summary"] = " ".join(str(out["summary"]).split())
    if "years_experience" in out:
        out["years_experience"] = _years(out["years_experience"], str(path))
    if "graduation" in out:
        out["graduation"] = str(out["graduation"])
    return out


def _overrides_hash(overrides: dict[str, Any]) -> str:
    """Hash of the parsed content, so a comment-only edit changes nothing."""
    blob = json.dumps(overrides, sort_keys=True, ensure_ascii=True)
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


def merge_overrides(derived: dict[str, Any],
                    overrides: dict[str, Any]) -> dict[str, Any]:
    """Lists extend, scalars replace, `*_remove` drops (PRD 8.3[1])."""
    merged = {k: derived.get(k) for k in _DERIVED_KEYS}
    merged["profile_version"] = int(derived.get("profile_version", 1))

    skills = [_norm(s) for s in derived.get("skills") or []]
    titles = [_singular(_norm(t)) for t in derived.get("target_titles") or []]
    skills += overrides.get("skills", [])
    titles += [_singular(t) for t in overrides.get("target_titles", [])]
    drop_skills = set(overrides.get("skills_remove", []))
    drop_titles = {_singular(t) for t in overrides.get("target_titles_remove", [])}
    merged["skills"] = _dedupe([s for s in skills if s not in drop_skills])
    merged["target_titles"] = _dedupe([t for t in titles if t not in drop_titles])

    aliases = dict(derived.get("title_aliases") or {})
    aliases.update(overrides.get("title_aliases", {}))
    merged["title_aliases"] = aliases

    for key in _OVERRIDE_SCALARS:
        if key in overrides:
            merged[key] = overrides[key]
    merged["summary"] = str(merged.get("summary") or "")
    merged["years_experience"] = _years(merged.get("years_experience"), "profile")
    return merged


def load_derived_profile(cfg: Config) -> dict[str, Any]:
    """Contract 1 (PRD 0.6): derived profile + overrides, merged.

    Reads only - never calls the model. The pipeline runs `ingest(cfg)` first
    (a no-op unless something changed) and then this.
    """
    derived = _read_yaml(cfg.profile_path)
    if not derived:
        raise ProfileError(
            f"no derived profile at {cfg.profile_path} - run "
            "`python -m jobscraper profile --refresh` to build it from your resume")
    return merge_overrides(derived, load_overrides(cfg.profile_overrides_path))


# ---------------------------------------------------------------- the stage


def derive_profile(text: str, backend: Any, model: str) -> dict[str, Any]:
    """The one model call. Returns the validated derived keys."""
    if not getattr(backend, "available", False):
        reason = getattr(backend, "unavailable_reason", "") or "no backend"
        raise ProfileError(f"cannot derive the profile - model unavailable: {reason}")
    # The resume goes in fenced, with the output contract restated after it. Sent
    # bare, a small model reads the resume as the task and writes a Markdown
    # write-up instead of JSON (observed live with haiku via `claude -p`).
    user = ("<resume>\n" + text[:_MAX_PROMPT_CHARS] + "\n</resume>\n\n"
            "Respond with ONLY the JSON object described in the system prompt - "
            "keys summary, skills, target_titles, title_aliases, "
            "years_experience, graduation. Start your reply with `{`.")
    try:
        comp = backend.complete(model=model, system=SYSTEM_PROMPT,
                                user=user, max_tokens=2000)
    except backends.BackendError as exc:
        raise ProfileError(f"model call failed: {exc}") from exc
    return _validate(_parse_json(comp.text))


def ingest(cfg: Config, *, backend: Any = None, force: bool = False,
           log: Callable[[str], Any] = print) -> IngestResult:
    """Stage [1]. Cheap unless the resume or the overrides changed.

    `backend` defaults to `backends.build(cfg.budget)` and is only built when a
    model call is actually needed. `force` re-derives even when the resume hash
    is unchanged (`profile --refresh`).
    """
    old = _read_yaml(cfg.profile_path) or {}
    old_version = int(old.get("profile_version", 0) or 0)
    overrides = load_overrides(cfg.profile_overrides_path)
    ov_hash = _overrides_hash(overrides)

    resume = load_resume(cfg.resume_dir, previous_hash=old.get("source_hash"),
                         force=force or not old)

    if not resume.changed:
        if old.get("overrides_hash") == ov_hash:
            msg = f"resume unchanged (profile_version {old_version})"
            log(msg)
            return IngestResult("unchanged", old_version, msg)
        doc = dict(old, profile_version=old_version + 1, overrides_hash=ov_hash)
        _write_derived(cfg.profile_path, doc)
        msg = (f"resume unchanged; overrides changed - profile_version "
               f"{old_version} -> {old_version + 1}")
        log(msg)
        return IngestResult("overrides-changed", old_version + 1, msg)

    model = str(cfg.budget.get("model") or "")
    if not model:
        raise ProfileError("budget.model is not set in config.yaml")
    if backend is None:
        backend = backends.build(cfg.budget)
    log(f"deriving profile from {resume.path.name} with {model} ...")
    fields = derive_profile(resume.text, backend, model)

    same = bool(old) and all(old.get(k) == fields[k] for k in _DERIVED_KEYS)
    if not old_version:
        version = 1
    elif same and old.get("overrides_hash") == ov_hash:
        version = old_version
    else:
        version = old_version + 1

    doc = {
        "source_file": resume.path.name,
        "source_hash": resume.source_hash,
        "parsed_at": _dt.date.today().isoformat(),
        "profile_version": version,
        **fields,
        "overrides_hash": ov_hash,
    }
    _write_derived(cfg.profile_path, doc)
    msg = (f"profile derived: {len(fields['skills'])} skills, "
           f"{len(fields['target_titles'])} target titles, "
           f"profile_version {version}")
    log(msg)
    return IngestResult("derived", version, msg)


def bump_profile_version(cfg: Config) -> int:
    """Force a new profile_version - every cached decision becomes stale."""
    old = _read_yaml(cfg.profile_path)
    if not old:
        raise ProfileError(f"no derived profile at {cfg.profile_path} to bump")
    version = int(old.get("profile_version", 0) or 0) + 1
    _write_derived(cfg.profile_path, dict(old, profile_version=version))
    return version
