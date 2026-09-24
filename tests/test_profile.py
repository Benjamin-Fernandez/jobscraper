"""The profile stage: resume in, derived profile out, and the keyword scorer.

Every resume here is synthetic, built at test time by
`tests/fixtures/make_resume_fixture.py`. The real resume is git-ignored and the
repo is public; no test may read it. No test reaches a model either - the one
model call is exercised against a stub backend.

Test names carry the word they are verified by: M2-T1 runs `-k resume`.

PRD section 8.3[1] and tasks M2-T1, M2-T2, M2-T3.
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE / "fixtures"))

import make_resume_fixture as fixture  # noqa: E402
from jobscraper.profile import resume_ingest as ri  # noqa: E402


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="jobscraper-profile-"))


class _Counter:
    """Wraps extract_text so a test can prove how often extraction ran."""

    def __init__(self):
        self.calls = 0
        self.real = ri.extract_text

    def __call__(self, path):
        self.calls += 1
        return self.real(path)

    def __enter__(self):
        ri.extract_text = self
        return self

    def __exit__(self, *exc):
        ri.extract_text = self.real


# ------------------------------------------------------------ M2-T1: ingest


def test_resume_pdf_text_is_extracted():
    d = _tmp()
    fixture.make_pdf(d / "resume.pdf")
    text = ri.extract_text(d / "resume.pdf")
    assert "Alex Tan" in text
    assert "Spring Boot" in text and "Kubernetes" in text
    assert "CI/CD" in text


def test_resume_docx_text_includes_tables():
    d = _tmp()
    fixture.make_docx(d / "resume.docx")
    text = ri.extract_text(d / "resume.docx")
    assert "Alex Tan" in text
    assert "Terraform" in text, "skills laid out in a table must not be lost"


def test_resume_hash_is_prefixed_sha256_of_the_bytes():
    d = _tmp()
    p = fixture.make_pdf(d / "resume.pdf")
    expected = "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
    assert ri.file_hash(p) == expected


def test_resume_pdf_is_preferred_over_docx():
    d = _tmp()
    fixture.make_docx(d / "resume.docx")
    assert ri.find_resume(d).name == "resume.docx"
    fixture.make_pdf(d / "resume.pdf")
    assert ri.find_resume(d).name == "resume.pdf"


def test_resume_missing_is_a_clear_error():
    d = _tmp()
    try:
        ri.find_resume(d)
    except ri.ResumeError as exc:
        assert "resume.pdf" in str(exc) and str(d) in str(exc)
        return
    raise AssertionError("a missing resume must raise ResumeError")


def test_resume_without_a_text_layer_is_refused():
    """A scanned image PDF extracts to nothing. Deriving a profile from an empty
    string would silently mis-filter every posting, so it must fail loudly."""
    d = _tmp()
    fixture.make_pdf(d / "resume.pdf", lines=[])
    try:
        ri.load_resume(d)
    except ri.ResumeError as exc:
        assert "text" in str(exc).lower()
        return
    raise AssertionError("an empty text layer must raise ResumeError")


def test_resume_unchanged_is_extracted_once():
    """The M2-T1 verify: ingest twice, extraction runs once."""
    d = _tmp()
    fixture.make_pdf(d / "resume.pdf")
    with _Counter() as counter:
        first = ri.load_resume(d)
        second = ri.load_resume(d, previous_hash=first.source_hash)
    assert counter.calls == 1, f"extraction ran {counter.calls} times"
    assert first.changed and "Alex Tan" in first.text
    assert not second.changed and second.text == ""
    assert second.source_hash == first.source_hash


def test_resume_edited_file_is_extracted_again():
    d = _tmp()
    fixture.make_pdf(d / "resume.pdf")
    with _Counter() as counter:
        first = ri.load_resume(d)
        fixture.make_pdf(d / "resume.pdf", lines=["Alex Tan", "Now knows Rust"])
        second = ri.load_resume(d, previous_hash=first.source_hash)
    assert counter.calls == 2
    assert second.changed and "Rust" in second.text
    assert second.source_hash != first.source_hash


def test_resume_force_extracts_even_when_unchanged():
    d = _tmp()
    fixture.make_pdf(d / "resume.pdf")
    first = ri.load_resume(d)
    with _Counter() as counter:
        again = ri.load_resume(d, previous_hash=first.source_hash, force=True)
    assert counter.calls == 1 and again.changed and again.text
