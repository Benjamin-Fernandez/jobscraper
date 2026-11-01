"""Where tailored files live, what they are called, and when they are deleted.

Design: docs/architecture/tailor_design.md section 10.1 (file naming) and 11
(storage and retention, D-59). Files go under the gitignored `data/tailored/
<job_id>/` (NF-01); the file name is `<First>_<Last>_Resume.<ext>`.

The store is passed in as an object by whoever calls `purge` (the pipeline and
`cmd_purge`), so this stage never imports `store`.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from .contracts import MasterResume

log = logging.getLogger(__name__)

_NAME_PART = re.compile(r"[^A-Za-z0-9-]")
_JOB_PART = re.compile(r"[^A-Za-z0-9_-]")


def _identity(applicant: Optional[dict]) -> tuple[str, str]:
    ident = (applicant or {}).get("identity") or {}
    return str(ident.get("legal_first_name") or "").strip(), str(ident.get("legal_last_name") or "").strip()


def display_name(applicant: Optional[dict], master: MasterResume) -> str:
    first, last = _identity(applicant)
    return f"{first} {last}".strip() or master.contact.name


def file_name(applicant: Optional[dict], master: MasterResume, ext: str = "docx") -> str:
    """`Jane_Tan_Resume.docx` from the applicant's legal names, else the master
    contact name split on its first space; each part reduced to [A-Za-z0-9-]."""
    first, last = _identity(applicant)
    if not (first or last):
        first, _, last = master.contact.name.strip().partition(" ")
    parts = [p for p in (_NAME_PART.sub("", first), _NAME_PART.sub("", last)) if p]
    return "_".join([*parts, "Resume"]) + "." + ext.lstrip(".")


def safe_job_id(job_id: str) -> str:
    return _JOB_PART.sub("_", job_id) or "job"


def job_dir(tailored_dir: str | Path, job_id: str) -> Path:
    return Path(tailored_dir) / safe_job_id(job_id)


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def delete_files(directory: str | Path, names: Iterable[Optional[str]]) -> int:
    """Delete the named files in `directory` and the directory when it ends up
    empty. Returns how many files were removed."""
    d = Path(directory)
    n = 0
    for name in names:
        if not name:
            continue
        p = d / Path(name).name          # never a path out of the directory
        try:
            p.unlink()
            n += 1
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("could not delete a tailored file: %s", type(exc).__name__)
    try:
        d.rmdir()
    except OSError:
        pass
    return n
