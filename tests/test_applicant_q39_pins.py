"""Q-39 pins for the Q-30 review fixes F6 and F7 (docs/reviews/Q-30.md): the profile and its etag come
from ONE read of the file, and every save that changes the file keeps the version it replaces as
`applicant.prev.yaml`. (F2 is a web fix: `web/tests/applicantForm.mergeEdits.test.js` and the "F2" suite of
`web/tests/ApplicationDetails.test.js`. The Questions-answer half of F7 is in `test_web_questions.py`.)

Synthetic data only (the tests/fixtures/apply sample), every file in a temp folder, `git check-ignore` is
local; no network, never data/ or port 8765. The runner is not pytest: a test is a plain `test_*` function.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from questions_support import ROOT, SAMPLE, profile  # noqa: E402

PREV = "applicant.prev.yaml"
BROKEN_YAML = b"identity: [unclosed\n  - : :\n"
NOT_UTF8 = b"identity:\n  legal_first_name: \xff\xfe bad \x80\n"
NOT_A_MAPPING = b"- one\n- two\n"


def _A():
    import jobscraper.applicant as A
    return A


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _dump(p: dict) -> bytes:
    return yaml.safe_dump(p, sort_keys=False).encode("utf-8")


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


def _named(**ident) -> dict:
    p = profile()
    p["identity"].update(ident)
    return p


@contextmanager
def _patched(owner, name, new):
    old = getattr(owner, name)
    setattr(owner, name, new)
    try:
        yield
    finally:
        setattr(owner, name, old)


def _ignored(rel: str) -> bool:
    r = subprocess.run(["git", "check-ignore", "-q", "--no-index", rel], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode in (0, 1), r.stderr
    return r.returncode == 0


@contextmanager
def _web(*, raw: bytes | None = None, prof: dict | None = None):
    """(client, applicant path, cfg) over a temp config: the real app, a temp DB and a temp applicant file.
    `raw` writes those bytes, `prof` dumps a profile, neither leaves the file absent."""
    from fastapi.testclient import TestClient
    from jobscraper.config import Config
    from jobscraper.web.api import create_app
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        path = data / "applicant.yaml"
        if raw is not None:
            path.write_bytes(raw)
        elif prof is not None:
            path.write_bytes(_dump(prof))
        cfg = Config({"paths": {"db": str(data / "jobscraper.db"), "applicant": str(path),
                                "shortlist": str(data / "shortlist.json"),
                                "profile": str(data / "profile.derived.yaml"), "resume_dir": str(data)},
                      "web": {"host": "127.0.0.1", "port": 8765}})
        with TestClient(create_app(cfg), base_url="http://localhost") as client:
            yield client, path, cfg


# ================================================================== F6: one read for the profile and the etag

def test_q39_f6_load_with_etag_of_a_missing_file_is_empty_and_has_no_etag():
    A = _A()
    path = _tmp() / "applicant.yaml"
    assert A.load_with_etag(path) == ({}, "")
    assert A.load(path) == {} and A.etag(path) == ""


def test_q39_f6_load_with_etag_pairs_the_loaded_profile_with_the_hash_of_the_file_bytes():
    A = _A()
    path = _tmp() / "applicant.yaml"
    raw = _dump(_named(preferred_name="Lex"))
    path.write_bytes(raw)
    prof, tag = A.load_with_etag(path)
    assert tag == _sha(raw) == A.etag(path) and len(tag) == 16
    assert prof == A.load(path) and prof["identity"]["preferred_name"] == "Lex"


def test_q39_f6_an_empty_file_is_an_empty_profile_with_a_real_etag_unlike_a_missing_one():
    A = _A()
    path = _tmp() / "applicant.yaml"
    path.write_bytes(b"")
    prof, tag = A.load_with_etag(path)
    assert prof == {} and tag == _sha(b"") != ""


def test_q39_f6_an_unreadable_file_raises_an_error_that_carries_the_etag_of_the_bytes_read():
    A = _A()
    for raw in (BROKEN_YAML, NOT_UTF8, NOT_A_MAPPING):
        path = _tmp() / "applicant.yaml"
        path.write_bytes(raw)
        try:
            A.load_with_etag(path)
        except A.ApplicantError as exc:
            assert exc.etag == _sha(raw) == A.etag(path) != "", raw
        else:
            raise AssertionError(f"ApplicantError expected for {raw!r}")
        try:
            A.load(path)
        except A.ApplicantError:
            pass
        else:
            raise AssertionError("load() must raise too")
        assert path.read_bytes() == raw, "reading never changes the file"


def test_q39_f6_a_non_utf8_file_is_an_applicant_error_not_a_decode_error():
    A = _A()
    path = _tmp() / "applicant.yaml"
    path.write_bytes(NOT_UTF8)
    try:
        A.load_with_etag(path)
    except A.ApplicantError as exc:
        assert "UnicodeDecodeError" not in type(exc).__name__
    except UnicodeDecodeError:                          # pragma: no cover - the defect this pins
        raise AssertionError("a file that is not UTF-8 must be an ApplicantError (F6)")


def test_q39_f6_the_file_is_read_once_and_a_swap_after_that_read_cannot_split_profile_and_etag():
    A = _A()
    path = _tmp() / "applicant.yaml"
    old_bytes = _dump(_named(preferred_name="Old"))
    new_bytes = _dump(_named(preferred_name="New"))
    path.write_bytes(old_bytes)
    real = Path.read_bytes
    reads: list[int] = []

    def swapping(self):
        data = real(self)
        if self == path:
            reads.append(1)
            if len(reads) == 1:
                path.write_bytes(new_bytes)             # a hand edit lands right after the first read
        return data

    with _patched(Path, "read_bytes", swapping):
        prof, tag = A.load_with_etag(path)
    assert len(reads) == 1, f"load_with_etag read the file {len(reads)} times"
    assert prof["identity"]["preferred_name"] == "Old", "the profile is the bytes that were read"
    assert tag == _sha(old_bytes), "the etag is the hash of those same bytes, not of the swapped file"
    assert path.read_bytes() == new_bytes and A.etag(path) != tag, "so a save with this etag is a 409"


def test_q39_f6_get_applicant_answers_profile_and_etag_from_one_read_even_if_the_file_is_swapped():
    old_bytes = _dump(_named(preferred_name="Old"))
    new_bytes = _dump(_named(preferred_name="New"))
    with _web(raw=old_bytes) as (c, path, _cfg):
        real = Path.read_bytes
        reads: list[int] = []

        def swapping(self):
            data = real(self)
            if self == path:
                reads.append(1)
                if len(reads) == 1:
                    path.write_bytes(new_bytes)
            return data

        with _patched(Path, "read_bytes", swapping):
            r = c.get("/api/applicant")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(reads) == 1, f"GET read the file {len(reads)} times"
        assert body["profile"]["identity"]["preferred_name"] == "Old"
        assert body["etag"] == _sha(old_bytes), "old profile with the OLD etag, never the new one"
        # the form PUTs what it was shown: the swapped-in edit must be refused, not overwritten
        r = c.put("/api/applicant", json={"profile": body["profile"], "etag": body["etag"]})
        assert r.status_code == 409 and r.json()["detail"] == "changed", r.text
        assert path.read_bytes() == new_bytes, "the hand edit survives"


def test_q39_f6_the_put_reply_derives_profile_and_etag_from_one_read_of_what_was_saved():
    A = _A()
    with _web(prof=_named(preferred_name="Old")) as (c, path, _cfg):
        got = c.get("/api/applicant").json()
        edited = got["profile"]
        edited["identity"]["preferred_name"] = "Lex"
        swapped = _dump(_named(preferred_name="Hand"))
        real_read, real_save = Path.read_bytes, A.save
        seen: dict = {"saved": False, "swapped": False}

        def save_then_flag(*a, **k):
            real_save(*a, **k)
            seen["saved"] = True

        def swapping(self):
            data = real_read(self)
            if self == path and seen["saved"] and not seen["swapped"]:
                seen["swapped"], seen["bytes"] = True, data
                path.write_bytes(swapped)               # lands between the save and the reply's read
            return data

        with _patched(A, "save", save_then_flag), _patched(Path, "read_bytes", swapping):
            r = c.put("/api/applicant", json={"profile": edited, "etag": got["etag"]})
        assert r.status_code == 200, r.text
        assert seen["swapped"], "the reply must read the file after the save"
        body = r.json()
        assert body["profile"]["identity"]["preferred_name"] == "Lex"
        assert body["etag"] == _sha(seen["bytes"]), "the reply's etag is the hash of the bytes it parsed"
        r = c.put("/api/applicant", json={"profile": body["profile"], "etag": body["etag"]})
        assert r.status_code == 409 and r.json()["detail"] == "changed", "the hand edit is not overwritten"
        assert path.read_bytes() == swapped


def test_q39_f6_get_on_an_unreadable_file_is_200_with_the_etag_of_those_bytes_and_put_is_refused():
    for raw in (BROKEN_YAML, NOT_UTF8, NOT_A_MAPPING):
        with _web(raw=raw) as (c, path, _cfg):
            r = c.get("/api/applicant")
            assert r.status_code == 200, (raw, r.text)
            body = r.json()
            assert body["profile"] == {} and body["file"]["error"], raw
            assert body["etag"] == _sha(raw) != "", "the form still gets an etag for the bytes on disk"
            assert body["file"]["exists"] is True
            r = c.put("/api/applicant", json={"profile": profile(), "etag": body["etag"]})
            assert r.status_code == 409 and r.json()["detail"] == "unreadable", r.text
            assert path.read_bytes() == raw, "a file that could not be shown is never overwritten"
            assert not (path.parent / PREV).exists(), "and no prev copy is made either"


def test_q39_f6_get_on_a_missing_file_is_an_empty_profile_with_an_empty_etag():
    with _web() as (c, path, _cfg):
        assert not path.exists()
        body = c.get("/api/applicant").json()
        assert body["profile"] == {} and body["etag"] == "" and body["file"]["exists"] is False
        assert not body["file"]["error"]


# ================================================================== F7: one rolling previous copy

def test_q39_f7_previous_path_is_applicant_prev_yaml_beside_the_profile():
    A = _A()
    d = _tmp()
    assert A.previous_path(d / "applicant.yaml") == d / PREV
    assert A.PREVIOUS_NAME == PREV
    assert A.previous_path(d / "applicant.yaml").parent == d


def test_q39_f7_a_first_save_has_nothing_to_keep_and_writes_no_prev():
    A = _A()
    d = _tmp()
    path = d / "applicant.yaml"
    A.save(path, profile())
    assert path.is_file() and not (d / PREV).exists()
    assert sorted(p.name for p in d.iterdir()) == ["applicant.yaml"], "no stray temp file either"


def test_q39_f7_a_changing_save_keeps_the_replaced_bytes_as_prev_and_the_next_one_rolls_it():
    A = _A()
    d = _tmp()
    path = d / "applicant.yaml"
    A.save(path, _named(preferred_name="One"))
    v1 = path.read_bytes()
    A.save(path, _named(preferred_name="Two"))
    v2 = path.read_bytes()
    assert v2 != v1
    assert (d / PREV).read_bytes() == v1, "prev holds exactly the bytes the save replaced"
    A.save(path, _named(preferred_name="Three"))
    assert (d / PREV).read_bytes() == v2, "one rolling copy: the version before the LAST change"
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["identity"]["preferred_name"] == "Three"
    assert sorted(p.name for p in d.iterdir()) == [PREV, "applicant.yaml"], "no temp file is left behind"


def test_q39_f7_a_hand_written_file_is_kept_byte_for_byte_by_its_first_web_save():
    A = _A()
    d = _tmp()
    path = d / "applicant.yaml"
    path.write_bytes(SAMPLE.read_bytes())               # comments, hand layout
    original = path.read_bytes()
    p = A.load(path)
    p["identity"]["preferred_name"] = "Lex"
    A.save(path, p)
    assert (d / PREV).read_bytes() == original
    assert (d / "applicant.commented-backup.yaml").read_bytes() == original, "the comments copy is unchanged"


def test_q39_f7_a_save_that_does_not_change_the_file_does_not_roll_prev():
    A = _A()
    d = _tmp()
    path = d / "applicant.yaml"
    path.write_bytes(SAMPLE.read_bytes())
    original = path.read_bytes()
    p = A.load(path)
    p["identity"]["preferred_name"] = "Lex"
    A.save(path, p)                                     # rewrites the file; prev = the hand-written bytes
    saved = path.read_bytes()
    assert (d / PREV).read_bytes() == original and saved != original
    A.save(path, A.load(path))                          # "Save" pressed again with nothing changed
    A.save(path, A.load(path))
    assert path.read_bytes() == saved
    assert (d / PREV).read_bytes() == original, "a second identical Save must not push the real previous out"


def test_q39_f7_an_invalid_save_writes_neither_the_profile_nor_prev():
    A = _A()
    d = _tmp()
    path = d / "applicant.yaml"
    A.save(path, _named(preferred_name="One"))
    A.save(path, _named(preferred_name="Two"))
    file_before, prev_before = path.read_bytes(), (d / PREV).read_bytes()
    bad = _named(preferred_name="Three")
    bad["contact"]["postal_code"] = "12345"             # Singapore postal codes are 6 digits
    try:
        A.save(path, bad)
    except A.ApplicantError as exc:
        assert "contact.postal_code" in {e.path for e in exc.errors}
    else:
        raise AssertionError("an invalid profile must not be saved")
    assert path.read_bytes() == file_before and (d / PREV).read_bytes() == prev_before
    assert sorted(p.name for p in d.iterdir()) == [PREV, "applicant.yaml"]
    # and with no prev yet: an invalid save creates none
    d2 = _tmp()
    only = d2 / "applicant.yaml"
    only.write_bytes(_dump(profile()))
    try:
        A.save(only, bad)
    except A.ApplicantError:
        pass
    assert not (d2 / PREV).exists() and only.read_bytes() == _dump(profile())


def test_q39_f7_keep_previous_false_writes_no_prev():
    A = _A()
    d = _tmp()
    path = d / "applicant.yaml"
    A.save(path, _named(preferred_name="One"))
    A.save(path, _named(preferred_name="Two"), keep_previous=False)
    assert not (d / PREV).exists()
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["identity"]["preferred_name"] == "Two"


def test_q39_f7_a_save_writes_only_inside_the_profiles_folder():
    A = _A()
    root = _tmp()
    d = root / "data"
    d.mkdir()
    (root / "elsewhere").mkdir()
    (root / "elsewhere" / "keep.txt").write_text("x", encoding="utf-8")
    path = d / "applicant.yaml"
    path.write_bytes(SAMPLE.read_bytes())               # comments: also exercises the commented copy
    made: list[Path] = []
    real = tempfile.mkstemp

    def spy(*a, **k):
        fd, name = real(*a, **k)
        made.append(Path(name))
        return fd, name

    p = A.load(path)
    p["identity"]["preferred_name"] = "Lex"
    with _patched(tempfile, "mkstemp", spy):
        A.save(path, p)
    assert made and all(m.parent == d for m in made), f"temp files outside the profile folder: {made}"
    files = sorted(str(x.relative_to(root)).replace("\\", "/") for x in root.rglob("*") if x.is_file())
    assert files == ["data/applicant.commented-backup.yaml", "data/applicant.prev.yaml",
                     "data/applicant.yaml", "elsewhere/keep.txt"], files


def test_q39_f7_the_prev_file_and_its_temp_name_match_the_nf01_gitignore_pattern():
    A = _A()
    d = _tmp()
    path = d / "applicant.yaml"
    A.save(path, _named(preferred_name="One"))
    made: list[str] = []
    real = tempfile.mkstemp

    def spy(*a, **k):
        fd, name = real(*a, **k)
        made.append(Path(name).name)
        return fd, name

    with _patched(tempfile, "mkstemp", spy):
        A.save(path, _named(preferred_name="Two"))
    prev_temps = [n for n in made if n.startswith("applicant.prev.")]
    assert prev_temps, f"the prev copy is written through a temp file: {made}"
    for name in [PREV, *prev_temps]:
        assert name.endswith(".yaml") and _ignored(f"data/{name}"), \
            f"data/{name} would be committable: the repo is public (NF-01, `data/applicant*.yaml`)"


def test_q39_f7_the_temp_name_of_the_profile_write_is_gitignored_too():
    # DEFECT (low): `save` writes the profile through `applicant.yaml.<rand>.tmp`. `data/applicant*.yaml`
    # does not match that name, so a crash or a kill between the write and `os.replace` leaves the owner's
    # personal data in an untracked file that `git add -A` would stage in the public repo. The prev temp
    # was given a `.yaml` suffix for exactly this reason (applicant.py `_keep_previous`); the profile's own
    # temp name needs the same (e.g. suffix ".yaml").
    A = _A()
    d = _tmp()
    path = d / "applicant.yaml"
    A.save(path, _named(preferred_name="One"))
    made: list[str] = []
    real = tempfile.mkstemp

    def spy(*a, **k):
        fd, name = real(*a, **k)
        made.append(Path(name).name)
        return fd, name

    with _patched(tempfile, "mkstemp", spy):
        A.save(path, _named(preferred_name="Two"))
    loose = [n for n in made if not _ignored(f"data/{n}")]
    assert not loose, f"these temp names are not covered by the gitignore (NF-01): {loose}"


# ---------------------------------------------------------------- F7 through the web routes

def test_q39_f7_a_partial_put_replaces_the_profile_but_the_old_full_one_is_kept_in_prev():
    with _web(prof=profile()) as (c, path, _cfg):
        old = path.read_bytes()
        got = c.get("/api/applicant").json()
        partial = {"version": 1, "identity": {"preferred_name": "Lex"}}      # e.g. a UI bug
        r = c.put("/api/applicant", json={"profile": partial, "etag": got["etag"]})
        assert r.status_code == 200, r.text
        prev = path.parent / PREV
        assert prev.read_bytes() == old, "prev is the whole profile that was replaced"
        kept = yaml.safe_load(prev.read_text(encoding="utf-8"))
        assert kept["contact"]["email"] == profile()["contact"]["email"]
        assert "contact" not in yaml.safe_load(path.read_text(encoding="utf-8")), "the partial PUT did replace it"


def test_q39_f7_put_rolls_prev_on_a_change_and_not_on_an_identical_save():
    with _web(prof=profile()) as (c, path, _cfg):
        v0 = path.read_bytes()
        got = c.get("/api/applicant").json()
        edited = got["profile"]
        edited["identity"]["preferred_name"] = "Lex"
        r = c.put("/api/applicant", json={"profile": edited, "etag": got["etag"]})
        assert r.status_code == 200, r.text
        v1 = path.read_bytes()
        prev = path.parent / PREV
        assert v1 != v0 and prev.read_bytes() == v0
        again = r.json()                                 # the form's next Save: same profile, fresh etag
        r = c.put("/api/applicant", json={"profile": again["profile"], "etag": again["etag"]})
        assert r.status_code == 200, r.text
        assert path.read_bytes() == v1 and prev.read_bytes() == v0, "an identical re-save keeps the real previous"
        edited2 = r.json()["profile"]
        edited2["identity"]["preferred_name"] = "Lexi"
        r = c.put("/api/applicant", json={"profile": edited2, "etag": r.json()["etag"]})
        assert r.status_code == 200, r.text
        assert prev.read_bytes() == v1, "a later change rolls it forward"


def test_q39_f7_a_422_or_409_put_keeps_the_file_and_makes_no_prev():
    with _web(prof=profile()) as (c, path, _cfg):
        before = path.read_bytes()
        got = c.get("/api/applicant").json()
        bad = got["profile"]
        bad["contact"]["postal_code"] = "12345"
        r = c.put("/api/applicant", json={"profile": bad, "etag": got["etag"]})
        assert r.status_code == 422, r.text
        r = c.put("/api/applicant", json={"profile": got["profile"], "etag": "0000000000000000"})
        assert r.status_code == 409 and r.json()["detail"] == "changed", r.text
        assert path.read_bytes() == before
        assert not (path.parent / PREV).exists()
