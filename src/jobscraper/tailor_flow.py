"""Orchestrator: tailor the resume to one job (KA-4, M20 deterministic tailor).

Design: docs/architecture/tailor_design.md sections 2, 11, 12, 13, 19. This
module composes the `tailor/` stage; it is the only place that touches the
store, the resume file on disk and the scrape adapters (the stage gets
`extract_text`, `html_to_text` and the backend injected by being called with
them here).

Truthful by construction: code decides facts. The model is asked for one thing
only, to split the resume into fields once per resume hash (`master.parse`);
everything per job (terms, mapping, swaps, order, validation, rendering) is
deterministic, and any exception becomes a `failed` result and row, never a
half-written file. Job logs carry counts and ids only, never resume text.

`tailor_for_apply` is what auto-apply calls (D-58, D-70): it returns the
current tailored file when there is one, else tailors, and always hands back
paths plus coverage. A failed result means "upload the original resume".
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from .config import Config
from .profile import resume_ingest
from .scrape.adapters import get_adapter, html_to_text
from .scrape.net import HttpClient
from .store import Store, utcnow
from .models import RawJob
from .tailor import (compose as compose_mod, mapping, master as master_mod, render, rewrite,
                     storage, terms, validate)
from .tailor.contracts import (BulletChange, ComposeRequest, ComposeResult, IssueCode, JdTerm,
                               MasterResume, SectionKind, TailorResult, TailorStatus, TermStatus,
                               ValidationIssue)

log = logging.getLogger(__name__)

MODE = "deterministic"      # D-67: `tailor.llm` is the M22 layer and is not built


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _say(say: Optional[Callable[[str], None]], msg: str) -> None:
    (say or log.info)(msg)


def load_applicant(cfg: Config) -> dict[str, Any]:
    """The applicant profile as a dict ({} when `data/applicant.yaml` is absent
    or unreadable). Only identity names, `skills` and `attested_skills` are used
    here; full validation is the profile module's job (lane P)."""
    path = cfg._path("applicant", "data/applicant.yaml")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _strings(value: Any) -> list[str]:
    return [str(x).strip() for x in (value or []) if str(x).strip()] if isinstance(value, list) else []


def _term_dict(t: JdTerm) -> dict[str, Any]:
    d = asdict(t)
    d["status"] = t.status.value
    return d


def _term_from(d: dict[str, Any]) -> JdTerm:
    return JdTerm(term=d["term"], canonical=d.get("canonical", ""), required=bool(d.get("required")),
                  source=d.get("source", "dictionary"), status=TermStatus(d.get("status", "missing")),
                  variant=d.get("variant", ""), via=d.get("via", ""), related=d.get("related", ""),
                  attested=bool(d.get("attested")))


def _change_dict(c: BulletChange) -> dict[str, Any]:
    return {"bullet_id": c.bullet_id, "entry_id": c.entry_id, "before": c.before, "after": c.after,
            "source": c.source, "keywords_used": c.keywords_used,
            "issues": [{"code": i.code.value, "detail": i.detail} for i in c.issues]}


def _change_from(d: dict[str, Any]) -> BulletChange:
    return BulletChange(d["bullet_id"], d["entry_id"], d["before"], d["after"], d["source"],
                        d.get("keywords_used", []),
                        [ValidationIssue(IssueCode(i["code"]), d["bullet_id"], i.get("detail", ""))
                         for i in d.get("issues", [])])


def _issue_dicts(issues: list[ValidationIssue]) -> list[dict[str, Any]]:
    return [{"code": i.code.value, "bullet_id": i.bullet_id, "detail": i.detail} for i in issues]


def _safe_error(exc: BaseException) -> str:
    """`Type: message`, with no resume text: the messages of this stage are built
    from ids and counts; anything else is cut short."""
    return f"{type(exc).__name__}: {str(exc)[:160]}"


def _fetch_description(cfg: Config, store: Store, job: dict[str, Any]) -> str:
    """Hydrate a posting that came without a description, the way
    `pipeline._hydrate` does, and keep it (`store.set_description`)."""
    company = store.get_company(job["company_id"])
    adapter = get_adapter(company.provider) if company and company.provider else None
    if adapter is None:
        return ""
    rc = cfg.run
    client = HttpClient(user_agent=rc.get("user_agent", "JobScraper/2.0"),
                        timeout=float(rc.get("request_timeout", 25)),
                        delay=float(rc.get("rate_limit_delay", 0.7)),
                        max_retries=int(rc.get("max_retries", 3)),
                        respect_robots=bool(rc.get("respect_robots", True)))
    raw = RawJob(external_id=job["external_id"] or "", title=job["title"] or "",
                 url=job["url"] or "", location=job["location"] or "")
    try:
        adapter.hydrate(client, company, raw)
    except Exception:
        return ""
    if raw.description:
        store.set_description(job["job_id"], raw.description)
    return raw.description


def ensure_master(cfg: Config, backend) -> tuple[MasterResume, str, str]:
    """(master, resume_hash, resume text). Parses (one model call) only when the
    resume file's hash changed or the cache fails its leaf check. Public since
    Q-44: the profile job's application-details check reads the same master."""
    path = resume_ingest.find_resume(cfg.resume_dir)
    rhash = resume_ingest.file_hash(path)
    text = resume_ingest.extract_text(path)
    m = master_mod.load(cfg.master_resume_path, rhash, text)
    if m is None:
        m = master_mod.parse(text, backend, resume_hash=rhash, source_name=path.name,
                             page_count=master_mod.page_count(path, render.docx_pages))
        master_mod.save(cfg.master_resume_path, m)
    return m, rhash, text


def _inputs_hash(resume_hash: str, jd_hash: str, aliases_hash: str, attested: list[str],
                 skills: list[str], cfg: Config) -> str:
    t = cfg.tailor
    body = json.dumps([resume_hash, jd_hash, aliases_hash, sorted(a.lower() for a in attested),
                       sorted(s.lower() for s in skills), render.TEMPLATE_VERSION, MODE,
                       bool(t.headline), bool(t.llm_terms), bool(t.pdf)])
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _result_from_row(row: dict[str, Any], cfg: Config) -> TailorResult:
    d = storage.job_dir(cfg.tailored_dir, row["job_id"])
    blob = json.loads(row["changes_json"]) if row.get("changes_json") else {}
    return TailorResult(
        job_id=row["job_id"], ok=row["status"] != "failed", status=TailorStatus(row["status"]),
        mode=row["mode"], tailored_id=row["id"],
        docx_path=str(d / row["docx_name"]) if row.get("docx_name") else None,
        pdf_path=str(d / row["pdf_name"]) if row.get("pdf_name") else None,
        coverage_before=row.get("coverage_before") or 0.0, coverage_after=row.get("coverage_after") or 0.0,
        title_match=bool(row.get("title_match")),
        terms=[_term_from(t) for t in json.loads(row["terms_json"] or "[]")],
        changes=[_change_from(c) for c in blob.get("changes", [])],
        summary_before=blob.get("summary", {}).get("before", ""),
        summary_after=blob.get("summary", {}).get("after", ""),
        skills_after=blob.get("skills_after", []),
        knockouts=json.loads(row["knockouts_json"] or "[]"), model=row.get("model") or "",
        error=row.get("error") or "")


def _fail(store: Store, job_id: str, error: str, *, base: dict[str, Any], persist: bool,
          directory: Optional[Path] = None, names: tuple = ()) -> TailorResult:
    """A failed result, and (unless report-only) a `failed` row. The files of a
    failed attempt are deleted at once (D-59)."""
    if directory is not None:
        storage.delete_files(directory, names)
    res = TailorResult(job_id=job_id, ok=False, status=TailorStatus.FAILED, mode=MODE, error=error)
    if persist:
        res.tailored_id = store.add_tailored({
            "job_id": job_id, "inputs_hash": base.get("inputs_hash", ""),
            "resume_hash": base.get("resume_hash", ""), "jd_hash": base.get("jd_hash", ""),
            "mode": MODE, "status": "failed", "error": error})
    return res


# ---------------------------------------------------------------------------
# the orchestrator
# ---------------------------------------------------------------------------

def tailor(cfg: Config, store: Store, job_id: str, *, backend, report_only: bool = False,
           force: bool = False, say: Optional[Callable[[str], None]] = None) -> TailorResult:
    """Tailor the resume to one job. `report_only` stops after coverage before
    (no swaps, no files, no row). Without `force`, a current tailored file for
    the same inputs is returned as is (section 11.2)."""
    base: dict[str, Any] = {}
    persist = not report_only
    jdir: Optional[Path] = None
    names: tuple = ()
    try:
        if not cfg.tailor.enabled:
            return _fail(store, job_id, "tailor is disabled in config", base=base, persist=False)
        job = store.get_job(job_id)
        if job is None:
            return _fail(store, job_id, "unknown job", base=base, persist=False)

        applicant = load_applicant(cfg)
        attested = _strings(applicant.get("attested_skills"))
        a_skills = _strings(applicant.get("skills"))

        master, rhash, _text = ensure_master(cfg, backend)
        base["resume_hash"] = rhash

        raw = job.get("jd_text") or _fetch_description(cfg, store, job)
        jd = terms.jd_text(raw or "", html_to_text, cfg.tailor.max_jd_chars)
        if not jd.strip():
            return _fail(store, job_id, "the job has no description to match against",
                         base=base, persist=persist)
        jd_hash = hashlib.sha256(jd.encode("utf-8")).hexdigest()
        base["jd_hash"] = jd_hash
        dictionary = terms.load_dictionary(cfg.aliases_path, [*a_skills, *attested, *master.skills()])
        ihash = _inputs_hash(rhash, jd_hash, dictionary.hash, attested, a_skills, cfg)
        base["inputs_hash"] = ihash
        jdir = storage.job_dir(cfg.tailored_dir, job_id)

        if persist and not force:
            row = store.current_tailored(job_id, ihash, jdir)
            if row is not None:
                _say(say, f"tailor {job_id}: reusing the current file (nothing changed)")
                return _result_from_row(row, cfg)

        # ---- terms, mapping, coverage before ----
        found = terms.extract(jd, dictionary, cfg.tailor.max_jd_chars)
        found = mapping.classify(found, master, dictionary, attested)
        before = mapping.coverage(found, mapping.resume_text(master), dictionary.ambiguous)
        knock = terms.knockouts(jd)
        by = {s: sum(1 for t in found if t.status is s) for s in TermStatus}
        _say(say, f"tailor {job_id}: terms={len(found)} (required {sum(t.required for t in found)}) "
                  f"exact={by[TermStatus.PRESENT_EXACT]} variant={by[TermStatus.PRESENT_VARIANT]} "
                  f"missing={by[TermStatus.MISSING]} coverage {before:.0%}")
        title = job.get("title") or ""
        head = rewrite.headline(title, cfg.tailor.headline)
        result = TailorResult(job_id=job_id, ok=True, status=TailorStatus.DRAFT, mode=MODE,
                              coverage_before=before, coverage_after=before, title_match=bool(head),
                              terms=found, knockouts=knock, summary_before=master.summary,
                              summary_after=master.summary)
        if report_only:
            return result

        # ---- swaps, guarded by the bullet validator ----
        swapped, swaps = rewrite.swap(master, found, dictionary)
        ctx = validate.BulletContext(dictionary=dictionary)
        for c in swaps:
            c.issues = validate.bullet(c.before, c.after, ctx)
            if c.issues:                         # fail closed: keep the master text
                c.source, c.after = "fallback", c.before
                for s in swapped.sections:
                    for e in s.entries:
                        e.bullets = [type(b)(b.id, c.before) if b.id == c.bullet_id else b
                                     for b in e.bullets]
        if swapped.summary != master.summary and validate.bullet(master.summary, swapped.summary, ctx):
            swapped.summary = master.summary

        ordered = rewrite.reorder(swapped, found, attested, dictionary.ambiguous)
        violations = validate.invariants(master, ordered, attested, swapped=swapped)
        if violations:
            raise RuntimeError("invariant: " + "; ".join(violations))

        # ---- render, page ceiling, round trip ----
        applicant_name = storage.file_name(applicant, master, "docx")
        names = (applicant_name, storage.file_name(applicant, master, "pdf"))
        docx_path, pdf_path = jdir / names[0], jdir / names[1]
        ceiling = (master.page_count if str(cfg.tailor.page_ceiling).lower() == "auto"
                   else max(1, int(cfg.tailor.page_ceiling)))
        scores = rewrite.bullet_scores(ordered, found, dictionary.ambiguous)
        fit = render.fit_pages(ordered, applicant, docx_path, pdf_path, ceiling, scores, head,
                               want_pdf=cfg.tailor.pdf)
        issues = list(fit.issues)
        bad = render.roundtrip(docx_path, fit.document, resume_ingest.extract_text)
        if bad:
            return _fail(store, job_id, "round trip: " + ", ".join(i.detail for i in bad),
                         base=base, persist=persist, directory=jdir, names=names)
        pdf_ok = fit.pdf and pdf_path.exists()
        if pdf_ok:
            bad_pdf = render.roundtrip(pdf_path, fit.document, resume_ingest.extract_text)
            if bad_pdf:
                storage.delete_files(jdir, (names[1],))
                pdf_ok = False
                issues += [ValidationIssue(IssueCode.PDF_UNAVAILABLE, detail="round trip failed"), *bad_pdf]
        after = mapping.coverage(found, resume_ingest.extract_text(docx_path), dictionary.ambiguous)

        changes = rewrite.change_log(master, swaps, fit.document, fit.trimmed)
        result.changes, result.issues = changes, issues
        result.coverage_after = after
        result.summary_after = fit.document.summary
        result.skills_after = fit.document.skills()
        result.docx_path = str(docx_path)
        result.pdf_path = str(pdf_path) if pdf_ok else None
        result.model = ""
        n = lambda src: sum(1 for c in changes if c.source == src)       # noqa: E731
        _say(say, f"rewrite: bullets={len(changes) - n('trimmed')} swapped={n('swap')} llm=0 "
                  f"fallback={n('fallback')} trimmed={n('trimmed')}")
        _say(say, "files: " + names[0] + (", .pdf" if pdf_ok else "")
             + (f" ({fit.pages} pages)" if fit.pages else ""))
        _say(say, f"tailor {job_id}: coverage {before:.0%} -> {after:.0%}")

        result.tailored_id = store.add_tailored({
            "job_id": job_id, "inputs_hash": ihash, "resume_hash": rhash, "jd_hash": jd_hash,
            "mode": MODE, "model": "", "options_json": json.dumps({"template": render.TEMPLATE_VERSION}),
            "status": "draft", "docx_name": names[0], "docx_sha256": storage.sha256(docx_path),
            "pdf_name": names[1] if pdf_ok else None,
            "pdf_sha256": storage.sha256(pdf_path) if pdf_ok else None,
            "coverage_before": before, "coverage_after": after, "title_match": int(bool(head)),
            "terms_json": json.dumps([_term_dict(t) for t in found]),
            "knockouts_json": json.dumps(knock),
            "changes_json": json.dumps({"changes": [_change_dict(c) for c in changes],
                                        "summary": {"before": master.summary, "after": fit.document.summary},
                                        "skills_after": result.skills_after}),
            "issues_json": json.dumps(_issue_dicts(issues))})
        return result
    except Exception as exc:                     # any failure -> a failed result, never a crash
        log.warning("tailor %s failed: %s", job_id, type(exc).__name__)
        return _fail(store, job_id, _safe_error(exc), base=base, persist=persist,
                     directory=jdir, names=names)


def tailor_for_apply(cfg: Config, store: Store, job_id: str, *, backend,
                     say: Optional[Callable[[str], None]] = None) -> TailorResult:
    """What auto-apply calls (D-58, D-70): the current tailored file if there is
    one, else a fresh tailoring. `result.ok` False means upload the original
    resume; `result.error` says why (for the job log). Use `upload_path` to pick
    the file."""
    return tailor(cfg, store, job_id, backend=backend, report_only=False, force=False, say=say)


def upload_path(result: TailorResult, resume_format: str = "pdf") -> Optional[str]:
    """The file to upload: the PDF when asked for and present, else the DOCX;
    None when tailoring failed (use the original resume)."""
    if not result.ok:
        return None
    if resume_format == "pdf" and result.pdf_path and Path(result.pdf_path).exists():
        return result.pdf_path
    return result.docx_path if result.docx_path and Path(result.docx_path).exists() else None


def purge(cfg: Config, store: Store, now: str) -> int:
    """D-59 retention, called by `cmd_purge` (the pipeline calls the same
    `tailor.storage.purge` at the end of a run)."""
    t = cfg.tailor
    return storage.purge(store, cfg.tailored_dir, now, t.draft_days, t.sent_days_after_close,
                         t.closed_statuses)


def _cached_master(cfg: Config) -> Optional[MasterResume]:
    """The cached master when it matches the current resume file; else None. Never
    parses (no model call) and never raises (D-68)."""
    try:
        path = resume_ingest.find_resume(cfg.resume_dir)
        text = resume_ingest.extract_text(path)
        return master_mod.load(cfg.master_resume_path, resume_ingest.file_hash(path), text)
    except Exception:
        return None


def master_text(cfg: Config) -> Optional[str]:
    """The cached master's resume text (summary, entry fields, bullets, items;
    contact excluded) when the cache matches the current resume file; else
    None. Never parses (no model call) and never raises (D-68)."""
    m = _cached_master(cfg)
    try:
        return mapping.resume_text(m) if m else None
    except Exception:
        return None


# Master section kind -> `ResolveContext.resume_entries` kind (llm_fill_design §5.2).
_ENTRY_KINDS = {SectionKind.EXPERIENCE: "experience", SectionKind.EDUCATION: "education"}


def resume_entries(cfg: Config) -> tuple[tuple[str, str, str], ...]:
    """The cached master's entries as `(id, kind, text)` for `ResolveContext.resume_entries`
    (llm_fill_design §5.2, WP-N6b): id `experience[0]`, `education[2]`, ... one running index
    over all entries in reading order; kind `experience` or `education`, every other entry (projects,
    leadership, awards, certifications) `other`, and a certification or award line without
    an entry is an `other` of its own. `text` is the entry's fields (title first) then its
    bullets, verbatim; contact and skills never appear. Cached master only: no parse, no
    model call, never raises, `()` on a miss (the `master_text` pattern)."""
    m = _cached_master(cfg)
    if m is None:
        return ()
    try:
        out: list[tuple[str, str, str]] = []

        def add(kind: str, text: str) -> None:
            if text.strip():
                out.append((f"{kind}[{len(out)}]", kind, text))   # one running index (design 5.2)

        for s in m.sections:
            kind = _ENTRY_KINDS.get(s.kind, "other")
            for e in s.entries:
                lines = [e.title, e.organisation, e.location, e.dates, e.subtitle,
                         *(b.text for b in e.bullets)]
                add(kind, "\n".join(x.strip() for x in lines if x and x.strip()))
            if s.kind in (SectionKind.AWARDS, SectionKind.CERTIFICATIONS):
                for item in s.items:
                    add("other", item.strip())
        return tuple(out)
    except Exception:
        return ()


def alias_groups(cfg: Config) -> tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]:
    """`((canonical, *variants), ...)` per aliases entry (instances excluded) and
    the ambiguous tokens; `((), ())` when the file is missing or invalid (D-68)."""
    try:
        a = terms.Aliases.load(cfg.aliases_path)
    except Exception:
        return (), ()
    return tuple((e.canonical, *e.variants) for e in a.entries), tuple(sorted(a.ambiguous))


# ---------------------------------------------------------------------------
# Q-45: composed texts (cover letter, "why join"; llm_fill_design section 19, KA-4)
# ---------------------------------------------------------------------------

def compose(cfg: Config, req: ComposeRequest, *, backend, redact: Callable[..., str]) -> ComposeResult:
    """One composed text for `req` (design 19.3/19.4), from the CACHED master only: no
    resume parse, so a miss is `ComposeResult(ok=False, error="no master")` (run
    `python -m jobscraper tailor` once). `redact(text, s_values)` is the apply stage's S-value
    scrubber, passed in by apply_flow (stages don't import each other); the whole user
    prompt goes through it. The model writes the words, `tailor.compose.check` (C1-C7)
    decides; one retry. Never raises on a model failure (`error="transport: <kind>"`) and
    never logs a text."""
    m = _cached_master(cfg)
    if m is None:
        return ComposeResult(False, error="no master")
    try:
        applicant = load_applicant(cfg)
        attested = _strings(applicant.get("attested_skills"))
        dictionary = terms.load_dictionary(
            cfg.aliases_path, [*_strings(applicant.get("skills")), *attested, *m.skills()])
    except Exception as exc:    # a broken aliases file: tailoring fails the same way
        return ComposeResult(False, error=f"setup: {type(exc).__name__}")
    return compose_mod.compose(req, m, dictionary, backend=backend, redact=redact,
                               attested=attested)


def write_letter(text: str, path: str | Path, fmt: str) -> str:
    """Write a composed letter to `path` and return it (design 19.3 step 2). `fmt` is
    `docx` (one clean column in the tailor template's font and page, plain paragraphs,
    no name and no contact block) or `txt` (UTF-8, blank line between paragraphs); anything
    else is a programming error (ValueError). Paragraphs are the text's blank-line blocks,
    or its lines when it has none. Creates the folder; the caller picks a free name."""
    path = Path(path)
    if fmt not in ("docx", "txt"):
        raise ValueError(f"unknown letter format: {fmt!r}")
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]
    if len(blocks) == 1:
        blocks = [x.strip() for x in blocks[0].splitlines() if x.strip()] or blocks
    paras = [" ".join(b.split()) for b in blocks]
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "txt":
        path.write_text("\n\n".join(paras) + "\n", encoding="utf-8")
        return str(path)
    import docx
    from docx.shared import Cm, Pt
    d = docx.Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Cm(2.2)
    normal = d.styles["Normal"]
    render._font(normal, 11)
    normal.paragraph_format.space_after = Pt(8)
    normal.paragraph_format.line_spacing = 1.1
    for para in paras:
        d.add_paragraph(para)
    d.save(str(path))
    return str(path)


# ---------------------------------------------------------------------------
# Q-44: proposals for the application details, from the resume
# ---------------------------------------------------------------------------

DESCRIPTION_MAX = 500       # q44 design 3.1: the first bullet, cut at a space, nothing added


def _first_bullet(entry) -> str:
    text = entry.bullets[0].text.strip() if entry.bullets else ""
    if len(text) <= DESCRIPTION_MAX:
        return text
    cut = text[:DESCRIPTION_MAX]
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else cut).rstrip()


def _on_resume(skill: str, text: str) -> bool:
    """`skill` appears in `text` as a whole word (or phrase), case-insensitively."""
    words = skill.split()
    if not words:
        return False
    pattern = r"(?<!\w)" + r"\s+".join(re.escape(w) for w in words) + r"(?!\w)"
    return re.search(pattern, text, re.IGNORECASE) is not None


def profile_proposals(cfg: Config, backend) -> dict[str, Any]:
    """The resume-side facts the Profile tab offers for the application details
    (q44_refresh_from_resume.md 3.1, 3.3), as the proposals file holds them:
    `{resume_hash, source_name, created_at, experience, education, skills,
    not_on_resume}`. KA-4: every value is copied from the parsed master, never
    guessed. A location is the entry's own (never the contact line), a date
    that `applicant.parse_resume_dates` cannot read stays empty, education's
    major and grade stay empty (its subtitle travels as a note), and only the
    experience and education sections count. An entry without both its org and
    its title is left out: it could not be saved.

    A derived skill is proposed only when the resume text has it as a whole
    word; the ones the derive step implied go to `not_on_resume` and are never
    added. One model call at most: `ensure_master` parses only a stale cache."""
    from . import applicant as applicant_mod

    m, rhash, raw_text = ensure_master(cfg, backend)
    out: dict[str, Any] = {"resume_hash": rhash, "source_name": m.source_name,
                           "created_at": utcnow(), "experience": [], "education": [],
                           "skills": [], "not_on_resume": []}
    for section, e in m.entries():
        org, title = e.organisation.strip(), e.title.strip()
        if section.kind not in (SectionKind.EXPERIENCE, SectionKind.EDUCATION) or not (org and title):
            continue
        start, end, _ok = applicant_mod.parse_resume_dates(e.dates)
        if section.kind is SectionKind.EXPERIENCE:
            out["experience"].append({
                "employer": org, "title": title, "start": start, "end": end,
                "location": e.location.strip(), "description": _first_bullet(e),
                "from_resume": True, "dates_text": e.dates})
        else:
            out["education"].append({
                "institution": org, "degree": title, "major": "", "minor": "",
                "start": start, "end": end, "grade_type": "", "grade": "", "grade_scale": "",
                "from_resume": True, "dates_text": e.dates, "subtitle": e.subtitle})

    text = " ".join((mapping.resume_text(m) or raw_text or "").split())
    try:
        derived = yaml.safe_load(cfg.profile_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        derived = {}
    seen: set[str] = set()
    for s in _strings(derived.get("skills") if isinstance(derived, dict) else None):
        label = applicant_mod.skill_label(s)
        if not label or label.lower() in seen:
            continue
        seen.add(label.lower())
        out["skills" if _on_resume(s, text) else "not_on_resume"].append(label)
    log.info("application details check: %d experience, %d education, %d skills "
             "(%d not on the resume)", len(out["experience"]), len(out["education"]),
             len(out["skills"]), len(out["not_on_resume"]))
    return out
