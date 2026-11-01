"""Render the tailored resume: clean DOCX template, PDF through Word, page
ceiling, round-trip check.

Design: docs/architecture/tailor_design.md section 10. The template is built in
code (python-docx) so it is parse-safe for an ATS: one column, no tables, text
boxes, images, fields or header/footer text, built-in heading and bullet
styles. A produced file is only kept if it survives re-extraction with the
app's own extractor (the round trip).

Word (pywin32) is optional: without it there is a DOCX and no PDF, with a
PDF_UNAVAILABLE issue, never an error.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .contracts import (BulletChange, IssueCode, MasterResume, SectionKind,
                        ValidationIssue)
from .master import forms, norm
from . import storage

log = logging.getLogger(__name__)

TEMPLATE_VERSION = 1
FONT = "Calibri"
TEXT_WIDTH_CM = 17.4
WORD_TIMEOUT_S = 90
MAX_TRIM_ROUNDS = 10

_HEADINGS = {
    SectionKind.SUMMARY: "Summary", SectionKind.EXPERIENCE: "Experience",
    SectionKind.EDUCATION: "Education", SectionKind.PROJECTS: "Projects",
    SectionKind.SKILLS: "Skills", SectionKind.LEADERSHIP: "Leadership",
    SectionKind.AWARDS: "Awards", SectionKind.CERTIFICATIONS: "Certifications",
}


def heading_text(section) -> str:
    return section.heading if section.kind is SectionKind.OTHER else _HEADINGS[section.kind]


def _has_content(section) -> bool:
    return bool(section.entries or section.items)


def rendered_headings(document: MasterResume) -> list[str]:
    out = ["Summary"] if document.summary else []
    return out + [heading_text(s) for s in document.sections if _has_content(s)]


# ---------------------------------------------------------------------------
# 10.1 DOCX template
# ---------------------------------------------------------------------------

def _font(style_or_run, size_pt: float, bold: Optional[bool] = None, italic: Optional[bool] = None):
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor
    f = style_or_run.font
    f.name = FONT
    f.size = Pt(size_pt)
    if bold is not None:
        f.bold = bold
    if italic is not None:
        f.italic = italic
    f.color.rgb = RGBColor(0, 0, 0)
    el = getattr(style_or_run, "element", None)
    rpr = (el.get_or_add_rPr() if hasattr(el, "get_or_add_rPr") else None)
    if rpr is None and hasattr(el, "rPr"):
        rpr = el.rPr
    fonts = rpr.find(qn("w:rFonts")) if rpr is not None else None
    if fonts is not None:
        for attr in list(fonts.attrib):
            if "Theme" in attr:
                del fonts.attrib[attr]
        fonts.set(qn("w:eastAsia"), FONT)


def render_docx(document: MasterResume, applicant: Optional[dict], path: str | Path,
                headline: str = "") -> Path:
    """Write the clean one-column resume to `path`."""
    import docx
    from docx.enum.style import WD_STYLE_TYPE
    from docx.enum.text import WD_TAB_ALIGNMENT
    from docx.shared import Cm, Pt

    d = docx.Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Cm(1.8)

    normal = d.styles["Normal"]
    _font(normal, 10.5)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.line_spacing = 1.0
    h1 = d.styles["Heading 1"]
    _font(h1, 11.5, bold=True)
    h1.paragraph_format.space_before = Pt(8)
    h1.paragraph_format.space_after = Pt(2)
    bullet_style = d.styles["List Bullet"]
    bullet_style.paragraph_format.space_after = Pt(0)

    c = document.contact
    p = d.add_paragraph()
    r = p.add_run(c.name)
    _font(r, 18, bold=True)
    if headline:
        r = d.add_paragraph().add_run(headline)
        _font(r, 11)
    line = " | ".join(x for x in (c.email, c.phone, c.location, *c.links) if x)
    if line:
        d.add_paragraph(line)

    if document.summary:
        d.add_paragraph("Summary", style="Heading 1")
        d.add_paragraph(document.summary)

    for s in document.sections:
        if not _has_content(s):
            continue
        d.add_paragraph(heading_text(s), style="Heading 1")
        for e in s.entries:
            if e.title or e.organisation or e.location or e.dates:
                hp = d.add_paragraph()
                hp.paragraph_format.space_before = Pt(4)
                hp.paragraph_format.tab_stops.add_tab_stop(Cm(TEXT_WIDTH_CM), WD_TAB_ALIGNMENT.RIGHT)
                if e.title:
                    hp.add_run(e.title).bold = True
                if e.organisation:
                    hp.add_run((", " if e.title else "") + e.organisation)
                if e.location:
                    hp.add_run(" — " + e.location)
                if e.dates:
                    hp.add_run("\t" + e.dates)
            if e.subtitle:
                d.add_paragraph().add_run(e.subtitle).italic = True
            for b in e.bullets:
                d.add_paragraph(b.text, style="List Bullet")
        if s.items:
            if s.kind is SectionKind.SKILLS:
                d.add_paragraph(", ".join(s.items))
            else:
                for it in s.items:
                    d.add_paragraph(it, style="List Bullet")

    cp = d.core_properties
    cp.title = "Resume"
    cp.author = storage.display_name(applicant, document) or c.name
    cp.last_modified_by = ""
    cp.comments = ""
    cp.subject = ""
    cp.keywords = ""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(path))
    return path


# ---------------------------------------------------------------------------
# 10.3 PDF through Word
# ---------------------------------------------------------------------------

def _word(docx_path: Path, pdf_path: Optional[Path], timeout: float) -> Optional[int]:
    """Open `docx_path` in Word on a worker thread (COM needs its own apartment),
    return its page count and, when `pdf_path` is given, export a PDF. None on
    any failure or timeout; Word is always quit."""
    result: dict[str, Any] = {}

    def work() -> None:
        try:
            import pythoncom
            import win32com.client
        except ImportError:
            result["err"] = "ImportError"
            return
        pythoncom.CoInitialize()
        word = doc = None
        try:
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            doc = word.Documents.Open(str(docx_path.resolve()), ReadOnly=True,
                                      AddToRecentFiles=False)
            pages = int(doc.ComputeStatistics(2))
            if pdf_path is not None:
                doc.ExportAsFixedFormat(str(pdf_path.resolve()), 17)
            result["pages"] = pages
        except Exception as exc:                 # COM raises many types
            result["err"] = type(exc).__name__
        finally:
            for fn in (lambda: doc.Close(False), lambda: word.Quit()):
                try:
                    fn()
                except Exception:
                    pass
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        log.warning("word: timed out after %ss", timeout)
        return None
    if "err" in result:
        log.info("word: unavailable (%s)", result["err"])
        return None
    return result.get("pages")


def word_pdf(docx_path: str | Path, pdf_path: str | Path,
             timeout: float = WORD_TIMEOUT_S) -> Optional[int]:
    """Export a PDF of the DOCX through Word; the page count, or None."""
    pdf = Path(pdf_path)
    pages = _word(Path(docx_path), pdf, timeout)
    if pages is None or not pdf.exists():
        try:
            pdf.unlink()
        except OSError:
            pass
        return None
    return pages


def docx_pages(docx_path: str | Path, timeout: float = WORD_TIMEOUT_S) -> Optional[int]:
    """Word's page count of a DOCX (master.page_count's `word_pages`)."""
    return _word(Path(docx_path), None, timeout)


# ---------------------------------------------------------------------------
# 10.2 page ceiling
# ---------------------------------------------------------------------------

@dataclass
class FitResult:
    document: MasterResume
    pages: Optional[int]
    pdf: bool                                   # a PDF was produced for the final document
    trimmed: list[BulletChange] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)


def _trim_one(document: MasterResume, scores: dict[int, int]) -> Optional[BulletChange]:
    """Drop the lowest-score bullet among entries with more than 2 kept bullets
    (ties: the last such bullet in reading order)."""
    best = None
    n = 0
    for _s, e in document.entries():
        if len(e.bullets) > 2:
            for b in e.bullets:
                n += 1
                key = (scores.get(b.id, 0), -n)
                if best is None or key < best[0]:
                    best = (key, e, b)
    if best is None:
        return None
    _k, e, b = best
    e.bullets = [x for x in e.bullets if x.id != b.id]
    return BulletChange(b.id, e.id, b.text, "", "trimmed",
                        issues=[ValidationIssue(IssueCode.PAGE_TRIM, b.id)])


def fit_pages(document: MasterResume, applicant: Optional[dict], docx_path: str | Path,
              pdf_path: str | Path, ceiling: int, scores: dict[int, int], headline: str = "",
              want_pdf: bool = True,
              to_pdf: Callable[[Path, Path], Optional[int]] = word_pdf,
              max_rounds: int = MAX_TRIM_ROUNDS) -> FitResult:
    """Render, count pages through Word, trim until within `ceiling`. The last
    round's DOCX (and PDF) belong to the returned document."""
    docx_path, pdf_path = Path(docx_path), Path(pdf_path)
    issues: list[ValidationIssue] = []
    trimmed: list[BulletChange] = []
    pages: Optional[int] = None
    pdf = False
    for rnd in range(max_rounds + 1):
        render_docx(document, applicant, docx_path, headline)
        pages = to_pdf(docx_path, pdf_path) if want_pdf else None
        pdf = pages is not None
        if pages is None:
            if want_pdf:
                issues.append(ValidationIssue(IssueCode.PDF_UNAVAILABLE, detail="page count unknown"))
            break
        if pages <= ceiling:
            break
        if rnd == max_rounds:
            issues.append(ValidationIssue(IssueCode.PAGE_TRIM, detail="still over"))
            break
        ch = _trim_one(document, scores)
        if ch is None:
            issues.append(ValidationIssue(IssueCode.PAGE_TRIM, detail="still over"))
            break
        trimmed.append(ch)
        issues.append(ValidationIssue(IssueCode.PAGE_TRIM, ch.bullet_id))
    return FitResult(document, pages, pdf, trimmed, issues)


# ---------------------------------------------------------------------------
# 10.4 round trip
# ---------------------------------------------------------------------------

def roundtrip(path: str | Path, document: MasterResume,
              extract_text: Callable[[Path], str]) -> list[ValidationIssue]:
    """Re-extract the file with the app's own extractor and look for, in this
    order: the name, each rendered section heading, then every entry's
    organisation and dates string. One issue per miss, detail names the kind."""
    text = extract_text(Path(path))
    both = forms(text)
    issues: list[ValidationIssue] = []

    def miss(what: str) -> None:
        issues.append(ValidationIssue(IssueCode.ROUNDTRIP, detail=what))

    def find_from(needle: str, pos: list[int]) -> bool:
        n = norm(needle)
        for form_i, hay in enumerate(both):
            at = hay.find(n, pos[form_i])
            if at >= 0:
                pos[form_i] = at + len(n)
                return True
        return False

    def anywhere(needle: str) -> bool:
        n = norm(needle)
        return any(n in hay for hay in both)

    pos = [0, 0]
    if document.contact.name and not find_from(document.contact.name, pos):
        miss("name")
    for h in rendered_headings(document):
        if not find_from(h, pos):
            miss(f"heading {h}")
    for _s, e in document.entries():
        if e.organisation and not anywhere(e.organisation):
            miss(f"organisation of {e.id}")
        if e.dates and not anywhere(e.dates):
            miss(f"dates of {e.id}")
    return issues
