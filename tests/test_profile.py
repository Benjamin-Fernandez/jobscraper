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


# ----------------------------------------------------- M2-T2: derived profile

import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402

import yaml  # noqa: E402

from jobscraper.backends import Completion, OffBackend  # noqa: E402
from jobscraper.config import ROOT, Config  # noqa: E402

MODEL_ANSWER = {
    "summary": "New graduate   backend engineer with Python and Java.",
    "skills": ["Python", "Java", "Spring Boot", "kubernetes", "python", " PostgreSQL "],
    "years_experience": 0,
    "graduation": "2026-08",
    "target_titles": ["Software Engineers", "Backend Engineer",
                      "site reliability engineer", "DevOps Engineer"],
    "title_aliases": {"SRE": "site reliability engineer",
                      "swe": "software engineer",
                      "pm": "product manager"},
}


class StubBackend:
    """Stands in for `claude -p`. Records every call; answers like a model would,
    fenced JSON included, so the parser is exercised too."""

    name = "stub"
    available = True
    unavailable_reason = ""

    def __init__(self, answer=None, raw: str | None = None):
        self.answer = MODEL_ANSWER if answer is None else answer
        self.raw = raw
        self.calls: list[tuple[str, str, str]] = []

    def complete(self, model, system, user, max_tokens=4096):
        self.calls.append((model, system, user))
        text = self.raw if self.raw is not None else (
            "```json\n" + json.dumps(self.answer) + "\n```")
        return Completion(text=text, input_tokens=10, output_tokens=10)


def _quiet(*_a, **_k):
    pass


def _profile_dir() -> tuple[Path, Config]:
    d = _tmp()
    fixture.make_pdf(d / "resume.pdf")
    cfg = Config({"paths": {"profile": str(d / "profile.derived.yaml"),
                            "profile_overrides": str(d / "overrides.yaml"),
                            "resume_dir": str(d)},
                  "budget": {"model": "stub-model"}})
    return d, cfg


def _derived(cfg: Config) -> dict:
    return yaml.safe_load(cfg.profile_path.read_text(encoding="utf-8"))


def test_profile_derive_writes_the_spec_yaml():
    d, cfg = _profile_dir()
    stub = StubBackend()
    res = ri.ingest(cfg, backend=stub, log=_quiet)
    assert res.status == "derived"
    assert len(stub.calls) == 1, "exactly one model call"
    model, system, user = stub.calls[0]
    assert model == "stub-model"
    assert "Alex Tan" in user, "the resume text is what the model reads"
    # Sent bare, haiku wrote a Markdown write-up of the resume instead of JSON.
    assert "<resume>" in user and "JSON" in user.split("</resume>")[-1], \
        "the output contract must be restated after the resume"
    assert "plausibly" in system and "lowercase" in system and "singular" in system

    y = _derived(cfg)
    assert y["source_file"] == "resume.pdf"
    assert y["source_hash"] == ri.file_hash(d / "resume.pdf")
    assert y["profile_version"] == 1
    assert y["summary"] == "New graduate backend engineer with Python and Java."
    assert y["skills"] == ["python", "java", "spring boot", "kubernetes", "postgresql"]
    assert y["target_titles"] == ["software engineer", "backend engineer",
                                  "site reliability engineer", "devops engineer"]
    assert y["title_aliases"] == {"sre": "site reliability engineer",
                                  "swe": "software engineer"}, \
        "an alias pointing at a title we do not target is dropped"
    assert y["years_experience"] == 0 and str(y["graduation"]) == "2026-08"
    assert y["parsed_at"]


def test_profile_model_quirks_are_normalised():
    """Seen live from haiku: graduation as an object, and skills bundled as
    'a/b' or 'x (y, z)' - forms a keyword matcher can never hit."""
    _d, cfg = _profile_dir()
    answer = dict(MODEL_ANSWER,
                  graduation={"degree": "BEng", "expected_date": "August 2026"},
                  skills=["TypeScript/JavaScript", "CI/CD", "TCP/IP networking",
                          "authentication (OAuth2, Okta SSO)", "python"])
    ri.ingest(cfg, backend=StubBackend(answer), log=_quiet)
    y = _derived(cfg)
    assert str(y["graduation"]) == "2026-08"
    assert y["skills"] == ["typescript", "javascript", "ci/cd", "tcp/ip networking",
                           "authentication", "oauth2", "okta sso", "python"]


def test_profile_model_alias_shapes_are_tolerated():
    """Aliases are secondary. A model answering them as a list must not sink the
    whole profile; the hand-edited overrides file stays strict."""
    for shape in ([{"alias": "SRE", "title": "site reliability engineer"}],
                  [["sre", "site reliability engineer"]],
                  "sre means site reliability engineer"):
        _d, cfg = _profile_dir()
        ri.ingest(cfg, backend=StubBackend(dict(MODEL_ANSWER, title_aliases=shape)),
                  log=_quiet)
        got = _derived(cfg)["title_aliases"]
        assert got in ({"sre": "site reliability engineer"}, {}), (shape, got)


def test_profile_graduation_forms():
    for raw, want in (("2026-08", "2026-08"), ("Aug 2026", "2026-08"),
                      ("August 2026", "2026-08"), ("2026", "2026"),
                      ("sometime", None), (None, None)):
        assert ri._graduation(raw) == want, (raw, ri._graduation(raw))


def test_profile_unchanged_resume_makes_no_model_call():
    _d, cfg = _profile_dir()
    stub = StubBackend()
    ri.ingest(cfg, backend=stub, log=_quiet)
    with _Counter() as counter:
        res = ri.ingest(cfg, backend=stub, log=_quiet)
    assert res.status == "unchanged"
    assert len(stub.calls) == 1 and counter.calls == 0
    assert _derived(cfg)["profile_version"] == 1


def test_profile_unchanged_resume_says_so():
    _d, cfg = _profile_dir()
    ri.ingest(cfg, backend=StubBackend(), log=_quiet)
    said: list[str] = []
    ri.ingest(cfg, backend=StubBackend(), log=said.append)
    assert any("resume unchanged" in s for s in said), said


def test_profile_version_bumps_when_the_resume_changes_the_profile():
    d, cfg = _profile_dir()
    ri.ingest(cfg, backend=StubBackend(), log=_quiet)
    fixture.make_pdf(d / "resume.pdf", lines=["Alex Tan", "Now knows Rust"])
    answer = dict(MODEL_ANSWER, skills=["python", "rust"])
    res = ri.ingest(cfg, backend=StubBackend(answer), log=_quiet)
    assert res.status == "derived" and res.profile_version == 2
    assert _derived(cfg)["profile_version"] == 2


def test_profile_refresh_with_identical_result_keeps_the_version():
    """A version bump re-decides the whole corpus (Q3). Re-deriving the same
    profile must not pay that cost for nothing."""
    _d, cfg = _profile_dir()
    ri.ingest(cfg, backend=StubBackend(), log=_quiet)
    stub = StubBackend()
    res = ri.ingest(cfg, backend=stub, force=True, log=_quiet)
    assert len(stub.calls) == 1, "force re-derives"
    assert res.profile_version == 1


def test_profile_bad_model_output_writes_nothing():
    _d, cfg = _profile_dir()
    for raw in ("Sorry, I cannot help with that.",
                json.dumps({"summary": "x", "skills": []}),
                json.dumps(dict(MODEL_ANSWER, target_titles="engineer"))):
        try:
            ri.ingest(cfg, backend=StubBackend(raw=raw), log=_quiet)
        except ri.ProfileError:
            assert not cfg.profile_path.exists()
            continue
        raise AssertionError(f"should refuse model output: {raw!r}")


def test_profile_unavailable_backend_is_a_clear_error():
    _d, cfg = _profile_dir()
    try:
        ri.ingest(cfg, backend=OffBackend("budget.backend is `off`"), log=_quiet)
    except ri.ProfileError as exc:
        assert "off" in str(exc)
        return
    raise AssertionError("an unavailable backend must raise ProfileError")


def _write_overrides(cfg: Config, text: str) -> None:
    cfg.profile_overrides_path.write_text(text, encoding="utf-8")


def test_profile_overrides_merge_additively():
    _d, cfg = _profile_dir()
    ri.ingest(cfg, backend=StubBackend(), log=_quiet)
    _write_overrides(cfg, """
skills: [Rust, python]
skills_remove: [java]
target_titles: [Backend Developers]
target_titles_remove: [devops engineer]
title_aliases: {be: backend engineer}
summary: "My own words."
years_experience: 1
""")
    p = ri.load_derived_profile(cfg)
    assert p["skills"] == ["python", "spring boot", "kubernetes", "postgresql", "rust"]
    assert p["target_titles"] == ["software engineer", "backend engineer",
                                  "site reliability engineer", "backend developer"]
    assert "devops engineer" not in p["target_titles"], "target_titles_remove drops it"
    assert p["title_aliases"]["be"] == "backend engineer"
    assert p["title_aliases"]["sre"] == "site reliability engineer"
    assert p["summary"] == "My own words." and p["years_experience"] == 1
    # the generated file itself is untouched by the merge
    assert "devops engineer" in _derived(cfg)["target_titles"]


def test_profile_contract_shape():
    """Contract 1 (PRD 0.6): what Lanes A and B build against."""
    _d, cfg = _profile_dir()
    ri.ingest(cfg, backend=StubBackend(), log=_quiet)
    p = ri.load_derived_profile(cfg)
    assert isinstance(p["profile_version"], int)
    assert isinstance(p["summary"], str) and p["summary"]
    assert isinstance(p["years_experience"], int)
    for key in ("skills", "target_titles"):
        assert p[key] and all(isinstance(s, str) for s in p[key])
    assert all(isinstance(k, str) and isinstance(v, str)
               for k, v in p["title_aliases"].items())


def test_profile_overrides_unknown_key_is_refused():
    """A typo in a hand-edited file must not be shrugged off."""
    _d, cfg = _profile_dir()
    ri.ingest(cfg, backend=StubBackend(), log=_quiet)
    _write_overrides(cfg, "skils: [rust]\n")
    try:
        ri.load_derived_profile(cfg)
    except ri.ProfileError as exc:
        assert "skils" in str(exc)
        return
    raise AssertionError("unknown override key must raise")


def test_profile_overrides_cannot_set_the_version():
    _d, cfg = _profile_dir()
    ri.ingest(cfg, backend=StubBackend(), log=_quiet)
    _write_overrides(cfg, "profile_version: 99\n")
    try:
        ri.load_derived_profile(cfg)
    except ri.ProfileError as exc:
        assert "profile_version" in str(exc)
        return
    raise AssertionError("profile_version is engine-owned")


def test_profile_overrides_edit_bumps_version_without_a_model_call():
    _d, cfg = _profile_dir()
    stub = StubBackend()
    ri.ingest(cfg, backend=stub, log=_quiet)
    _write_overrides(cfg, "skills: [rust]\n")
    res = ri.ingest(cfg, backend=stub, log=_quiet)
    assert len(stub.calls) == 1, "an overrides edit needs no model"
    assert res.profile_version == 2
    assert ri.load_derived_profile(cfg)["profile_version"] == 2
    # a comment-only edit changes nothing that matters
    _write_overrides(cfg, "# just a note\nskills: [rust]\n")
    assert ri.ingest(cfg, backend=stub, log=_quiet).profile_version == 2


def test_profile_bump_by_hand():
    _d, cfg = _profile_dir()
    ri.ingest(cfg, backend=StubBackend(), log=_quiet)
    assert ri.bump_profile_version(cfg) == 2
    assert ri.load_derived_profile(cfg)["profile_version"] == 2


def test_profile_missing_derived_file_is_a_clear_error():
    _d, cfg = _profile_dir()
    try:
        ri.load_derived_profile(cfg)
    except ri.ProfileError as exc:
        assert "profile --refresh" in str(exc)
        return
    raise AssertionError("no derived profile must raise ProfileError")


def test_profile_committed_overrides_template_is_a_no_op():
    """The template shipped in config/ must load, and change nothing."""
    tmpl = ROOT / "config" / "profile.overrides.yaml"
    assert tmpl.is_file()
    _d, cfg = _profile_dir()
    ri.ingest(cfg, backend=StubBackend(), log=_quiet)
    before = ri.load_derived_profile(cfg)
    _write_overrides(cfg, tmpl.read_text(encoding="utf-8"))
    after = ri.load_derived_profile(cfg)
    assert before == after


def test_profile_cli_show_prints_the_profile():
    from jobscraper import cli

    d, cfg = _profile_dir()
    ri.ingest(cfg, backend=StubBackend(), log=_quiet)
    cfg_file = d / "config.yaml"
    cfg_file.write_text(yaml.safe_dump(cfg.raw), encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = cli.main(["--config", str(cfg_file), "profile", "--show"])
    text = out.getvalue()
    assert rc == 0, text
    assert "profile_version: 1" in text
    assert "spring boot" in text and "site reliability engineer" in text


# ------------------------------------------------------ M2-T3: keyword overlap

from jobscraper.profile.keywords import overlap  # noqa: E402

# PRD 8.3[3]: `min_overlap: 2` in config/rules.yaml (Lane B's file). Restated
# here so this test pins the scorer against the floor the filter will use.
FLOOR = 2

SKILLS = ["python", "java", "spring boot", "fastapi", "kubernetes", "postgresql",
          "kafka", "docker", "go", "rest api", "ci/cd", "microservices", "aws"]

BACKEND_JD = """
Backend Engineer, Payments. You will build microservices in Java and Spring
Boot, design REST APIs, and run them on Kubernetes (k8s) with Docker. Our data
lives in Postgres and Kafka. Experience with Go or Python is a plus; we ship
through CI/CD on AWS.
"""

MARKETING_JD = """
Growth Marketing Manager. Own our go-to-market strategy and go above and beyond
for every launch. Run campaigns across paid social and email, report funnel
metrics in Excel and Google Analytics, and manage the content calendar in
HubSpot. Strong communication and storytelling skills; SEO experience a plus.
"""


def test_keywords_backend_jd_clears_the_floor():
    score, matched = overlap(BACKEND_JD, SKILLS)
    assert score >= FLOOR * 3, (score, matched)
    for s in ("java", "spring boot", "kubernetes", "postgresql", "kafka", "go",
              "python", "rest api", "ci/cd", "microservices", "aws", "docker"):
        assert s in matched, f"{s} should match: {matched}"
    assert "fastapi" not in matched


def test_keywords_marketing_jd_is_below_the_floor():
    score, matched = overlap(MARKETING_JD, SKILLS)
    assert score < FLOOR, (score, matched)
    assert "go" not in matched, "'go-to-market' is not the Go language"


def test_keywords_multiword_skill_weighs_double():
    assert overlap("We use Spring Boot.", ["spring boot"]) == (2, ["spring boot"])
    assert overlap("We use Python.", ["python"]) == (1, ["python"])


def test_keywords_match_whole_tokens_only():
    assert overlap("JavaScript and MySQL", ["java", "sql"]) == (0, [])
    assert overlap("Spring is here; boot camp", ["spring boot"]) == (0, [])


def test_keywords_symbol_skills():
    score, matched = overlap("Modern C++ and C# services", ["c++", "c#", "c"])
    assert matched == ["c++", "c#"], "the C in C++ is not the C language"
    assert overlap("Node.js or NodeJS", ["node.js"]) == (1, ["node.js"])
    assert overlap("ASP.NET on .NET 8", [".net"])[1] == [".net"]


def test_keywords_common_variants_fold():
    assert overlap("k8s", ["kubernetes"])[1] == ["kubernetes"]
    assert overlap("Postgres 16", ["postgresql"])[1] == ["postgresql"]
    assert overlap("Golang services", ["go"])[1] == ["go"]
    assert overlap("REST APIs", ["rest api"])[1] == ["rest api"]
    assert overlap("a microservice", ["microservices"])[1] == ["microservices"]


def test_keywords_each_skill_counts_once():
    assert overlap("python python PYTHON", ["python"]) == (1, ["python"])
    assert overlap("python", ["Python", "python "]) == (1, ["Python"])


def test_keywords_report_matches_in_skill_order():
    score, matched = overlap("kafka then java", ["java", "kafka", "rust"])
    assert (score, matched) == (2, ["java", "kafka"])


def test_keywords_empty_inputs():
    assert overlap("", SKILLS) == (0, [])
    assert overlap(BACKEND_JD, []) == (0, [])
    assert overlap(BACKEND_JD, ["", "   "]) == (0, [])
