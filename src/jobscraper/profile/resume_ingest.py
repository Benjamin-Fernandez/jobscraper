"""Resume ingest: turn the resume on disk into the profile every stage matches on.

Why this exists. v1 kept the candidate's skills and target roles in a
hand-written `config/profile.yaml`, which drifted from the actual resume the day
it was written. v2 makes the resume the single source of truth (D-1): drop a new
`data/resume.pdf` in, and the match vocabulary follows.

Why it is cheap. The resume changes a handful of times a year, the pipeline runs
several times a day. So the stage is keyed on the file's SHA-256: when the hash
matches the one recorded in the derived profile, nothing is extracted and no
model is called. Extraction and the model call happen on change only.

This module covers the text half (M2-T1): find the file, hash it, extract its
text. Nothing here is PDF- or DOCX-specific beyond `_EXTRACTORS`.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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
