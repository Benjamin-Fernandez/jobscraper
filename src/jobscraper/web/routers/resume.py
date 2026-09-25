"""`PUT /api/resume` - replace the resume the profile is derived from (M11-T4).

This is the only route that writes a file the user supplies, so it is narrow on
purpose (PRD M11, R-9):

- **A raw body, never a form.** A page on another site can make the browser
  send `multipart/form-data`, `application/x-www-form-urlencoded` or
  `text/plain` with no CORS preflight; it cannot send `application/pdf` or the
  DOCX type without one, and the app grants none. So those two are the only
  accepted types, and the form types are refused outright (`415`). PUT is
  itself never a "simple" method, which makes this belt and braces.
- **At most 5 MB**, checked against `Content-Length` before reading and against
  the bytes actually read, since a chunked body has no length to check (`413`).
- **Checked by content, not label**: `%PDF` for a PDF; for a DOCX a real ZIP
  holding `word/document.xml`. A file that is not what it claims is `415`.
- **Atomic**: the whole body is validated in memory first, then written to a
  temp file beside the target and renamed over it, so `data/` never holds half
  a resume. The other format is then removed, leaving exactly one resume for
  `profile/resume_ingest.find_resume` to pick up.

The UI follows a successful upload with `POST /api/jobs/profile`.
"""
from __future__ import annotations

import hashlib
import io
import os
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from jobscraper.config import Config
from jobscraper.web.deps import get_config

router = APIRouter(tags=["resume"])

MAX_BYTES = 5 * 1024 * 1024

PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# media type -> the file it becomes. Names match profile/resume_ingest.RESUME_NAMES.
TARGETS = {PDF_TYPE: "resume.pdf", DOCX_TYPE: "resume.docx"}

# Two uploads at once must not each delete the other's file.
_write_lock = threading.Lock()


def _media_type(request: Request) -> str:
    return request.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _looks_like(media: str, body: bytes) -> bool:
    if media == PDF_TYPE:
        return body.startswith(b"%PDF")
    if not body.startswith(b"PK\x03\x04"):
        return False
    try:                        # reads the ZIP directory only; nothing is inflated
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            return "word/document.xml" in z.namelist()
    except (zipfile.BadZipFile, ValueError, OSError):
        return False


def _save(directory: Path, name: str, body: bytes) -> None:
    """Write `body` to `directory/name` atomically, then drop the other format."""
    with _write_lock:
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(directory), prefix=".resume-",
                                   suffix=".part")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(body)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, directory / name)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        for other in TARGETS.values():
            if other != name:
                (directory / other).unlink(missing_ok=True)


@router.put("/resume")
async def put_resume(request: Request,
                     cfg: Config = Depends(get_config)) -> dict[str, Any]:
    """Save the raw request body as the resume; `{saved, bytes, sha256}`."""
    media = _media_type(request)
    if media not in TARGETS:
        raise HTTPException(
            status_code=415,
            detail=f"send the file itself as the body, with Content-Type "
                   f"{PDF_TYPE} or {DOCX_TYPE} (not a form upload)")

    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            too_big = int(declared) > MAX_BYTES
        except ValueError:
            raise HTTPException(status_code=400, detail="bad Content-Length")
        if too_big:
            raise HTTPException(status_code=413, detail="the resume is over 5 MB")

    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="the resume is over 5 MB")
    data = bytes(body)

    if not _looks_like(media, data):
        raise HTTPException(
            status_code=415,
            detail="the file is not a readable "
                   + ("PDF" if media == PDF_TYPE else "Word (.docx) document"))

    name = TARGETS[media]
    try:
        await run_in_threadpool(_save, cfg.resume_dir, name, data)
    except OSError as exc:
        raise HTTPException(status_code=500,
                            detail=f"could not save the resume: {exc.strerror or exc}")
    return {"saved": name, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}
