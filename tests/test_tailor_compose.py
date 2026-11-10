"""WP-T7 (Q-45), the K1 part: the composed-text call and its checks C1-C7 (llm_fill_design §19.4,
§19.5; tailor_design §7.4, §8.1; build plan WP-K1 "Done when"; LF §16 "Compose" row; KA-4).

Written against the spec, not the code. Everything goes through the two public entry points the
build plan fixes: `tailor_flow.compose(cfg, ComposeRequest, *, backend, redact) -> ComposeResult`
(cached master only) and `tailor_flow.write_letter(text, path, fmt) -> str`. The model is a
scripted fake that records every call; the master is the synthetic case_a master with an invented
contact block; no network, no Ollama, temp dir only.

  - C1-C7 each reject their probe (EMPTY/LENGTH, NUMBER_ADDED, FACT_ADDED, VERB_UPGRADE,
    PRIVATE_VALUE with no value in the detail, OTHER_EMPLOYER, PLACEHOLDER); a clean reply passes;
  - the prompt: JOB -> QUESTION -> RESUME order, `redact` applied to the WHOLE user prompt (retry
    included), no S value and no contact block in anything the model saw;
  - call options: temperature 0.3, seed 7, top_k 20, max_tokens = 2 * max_words + 100, schema
    `{"text": string, maxLength: max_chars}`;
  - retry: exactly once, with a `FIX:` line, never echoing a private value; two failures -> ok=False;
  - `error="no master"` on a master-cache miss (the model is not called); `transport: ...` on a
    backend failure; no text (reply, question, JD, resume) ever reaches a log record;
  - `write_letter` writes the requested format (docx / txt), plain paragraphs, no contact block.

Skip-clean until WP-K1 exists. Verify: python tests/run_tests.py -k tailor_compose
"""
from __future__ import annotations

import contextlib
import copy
import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, missing  # noqa: E402

_W0 = len(WAITING)
GATE = ("jobscraper.tailor.contracts:ComposeRequest", "jobscraper.tailor.contracts:ComposeResult",
        "jobscraper.tailor.compose", "jobscraper.tailor_flow:compose", "jobscraper.tailor_flow:write_letter")


def _gone() -> str:
    for spec in GATE:                                   # in order, stop at the first gap
        try:
            gap = missing(spec)
        except ImportError:
            gap = spec
        if gap:
            return gap
    return ""


_GAP = _gone()


def needs_compose(fn):
    if _GAP:
        WAITING.append((fn.__name__, _GAP))
        return None
    return fn


ROOT = Path(__file__).resolve().parents[1]
CASE_A = ROOT / "tests" / "fixtures" / "tailor" / "case_a" / "master.json"
PHONE, PHONE_DIGITS, EMAIL = "+65 9123 4567", "6591234567", "jane.tan@example.test"
NAME = "Jane Tan"
EMPLOYER, TITLE = "Orbit Analytics", "Data Engineer"

# 69 words; says only what the case_a master says (Acme, REST APIs, Python, Postgres, k8s, GitHub
# Actions, p95, 35%, ML, 82%) plus the employer and the role by name.
CLEAN = ("I want to join Orbit Analytics as a Data Engineer because I enjoy turning messy data into "
         "reliable systems. At Acme Logistics Pte Ltd I built REST APIs in Python and Postgres for "
         "shipment tracking, and I deployed services on k8s with GitHub Actions. I cut p95 latency "
         "35% and trained an ML model that reached 82% accuracy. I would like to bring that "
         "practical experience to your team.")


# ------------------------------------------------------------------ fakes and a world

class FakeModel:
    """Scripted replies (str = the `text` to return, Exception = raise). Records every call."""
    name = "fakemodel"
    model_id = "fake-model:1b"
    available = True

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def complete(self, system, user, max_tokens=4096, schema=None, timeout=None, *, format=None,
                 temperature=None, seed=None, top_k=None, keep_alive=None):
        from jobscraper.backends import Completion
        self.calls.append(dict(system=system, user=user, max_tokens=max_tokens,
                               schema=format or schema, temperature=temperature, seed=seed,
                               top_k=top_k))
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(r, Exception):
            raise r
        return Completion(json.dumps({"text": r}), 10, 10)

    @property
    def prompts(self) -> str:
        return "\n".join(c["system"] + "\n" + c["user"] for c in self.calls)


def _identity(text, s_values):
    return text


def _master_dict(edit=None) -> dict:
    data = json.loads(CASE_A.read_text(encoding="utf-8"))
    data["resume_hash"] = "sha256:t7"
    data["contact"].update(name=NAME, email=EMAIL, phone=PHONE)
    if edit:
        edit(data)
    return data


@contextlib.contextmanager
def _world(master=True, edit=None):
    """A temp world whose cached master is the case_a master (`edit(dict)` changes it first); the
    resume-file layer is stubbed on `tailor_flow.resume_ingest`, so no PDF is parsed. Yields cfg."""
    from apply_flow_support import make_world
    from jobscraper.profile import resume_ingest
    from jobscraper.tailor import master as master_mod
    w = make_world()
    saved = (resume_ingest.find_resume, resume_ingest.extract_text, resume_ingest.file_hash)
    try:
        m = master_mod.from_dict(_master_dict(edit))
        if master:
            master_mod.save(w.cfg.master_resume_path, m)
        text = "\n".join(master_mod._leaves(m))
        resume_ingest.find_resume = lambda d: Path(d) / "resume.pdf"
        resume_ingest.extract_text = lambda p: text
        resume_ingest.file_hash = lambda p: "sha256:t7"
        yield w.cfg
    finally:
        resume_ingest.find_resume, resume_ingest.extract_text, resume_ingest.file_hash = saved
        w.close()


def _req(**over):
    from jobscraper.tailor.contracts import ComposeRequest
    base = dict(kind="answer", question="Why do you want to join us?", employer=EMPLOYER,
                employer_aliases=(), job_title=TITLE,
                jd_text="Build data pipelines for the analytics platform. Kafka experience is a plus.",
                max_words=150, max_chars=1500, s_values=(), other_employers=())
    base.update(over)
    return ComposeRequest(**base)


def _compose(cfg, model, req=None, redact=_identity):
    from jobscraper import tailor_flow
    return tailor_flow.compose(cfg, req or _req(), backend=model, redact=redact)


NL1, NL2 = chr(10), chr(10) * 2


def _codes(res) -> set[str]:
    return {i.code.value for i in res.issues}


def _rejects(cfg, reply, code, **req_over):
    """The probe `reply` (returned twice) is rejected with `code`, after exactly one retry."""
    model = FakeModel(reply)
    res = _compose(cfg, model, _req(**req_over))
    assert not res.ok and res.text == "", (code, res.ok, res.text[:60])
    assert code in _codes(res), (code, sorted(_codes(res)), [i.detail for i in res.issues])
    assert res.attempts == 2 and len(model.calls) == 2, (res.attempts, len(model.calls))
    return res, model


# ------------------------------------------------------------------ clean reply and the call

def test_the_compose_oracles_load():
    assert len(CLEAN.split()) == 69 and CASE_A.is_file()
    assert "[" not in CLEAN and "@" not in CLEAN


@needs_compose
def test_a_clean_reply_passes_on_the_first_attempt():
    with _world() as cfg:
        model = FakeModel(CLEAN)
        res = _compose(cfg, model)
        assert res.ok, (sorted(_codes(res)), [i.detail for i in res.issues], res.error)
        assert res.text == CLEAN and res.issues == () and res.error == ""
        assert res.attempts == 1 and len(model.calls) == 1
        assert res.model == "fake-model:1b" and res.prompt_hash, (res.model, res.prompt_hash)


@needs_compose
def test_an_alias_of_a_master_skill_and_the_employer_names_are_not_added_facts():
    """C3 compares canonical facts: "PostgreSQL" is the master's "Postgres"; the employer, its
    aliases and the job title are allowed names."""
    text = CLEAN.replace("Postgres", "PostgreSQL").replace("Orbit Analytics", "Orbit")
    with _world() as cfg:
        res = _compose(cfg, FakeModel(text), _req(employer_aliases=("Orbit",)))
        assert res.ok, (sorted(_codes(res)), [i.detail for i in res.issues])


@needs_compose
def test_the_call_options_the_schema_and_the_prompt_order():
    with _world() as cfg:
        model = FakeModel(CLEAN)
        assert _compose(cfg, model, _req(max_words=150, max_chars=900)).ok
        c = model.calls[0]
        assert (c["temperature"], c["seed"], c["top_k"]) == (0.3, 7, 20), c
        assert c["max_tokens"] == 2 * 150 + 100, c["max_tokens"]
        sch = c["schema"]
        assert sch and sch["properties"]["text"]["type"] == "string"
        assert sch["properties"]["text"]["maxLength"] == 900 and "text" in sch["required"]
        u = c["user"]
        assert u.index("JOB:") < u.index("QUESTION:") < u.index("RESUME:"), "JOB -> QUESTION -> RESUME"
        assert "Orbit Analytics" in u and "Data Engineer" in u and "Why do you want to join us?" in u
        assert "REST APIs" in u, "the master's text is in the RESUME block"
        assert "at most 150 words" in c["system"] and "RESUME" in c["system"]
        assert "Data Engineer" not in c["system"], "employer text goes in the user prompt only"


@needs_compose
def test_a_letter_asks_for_a_letter_and_a_long_job_description_is_cut():
    jd = "x" * 2990 + " TAILMARKER " + "y" * 500
    with _world() as cfg:
        model = FakeModel(" ".join(["I built REST APIs in Python."] * 20))
        _compose(cfg, model, _req(kind="letter", question="Cover letter upload", jd_text=jd,
                                  max_words=250))
        c = model.calls[0]
        assert "cover letter" in c["system"].lower()
        assert "TAILMARKER" not in c["user"], "JD cut to its first 3000 characters"
        assert c["max_tokens"] == 2 * 250 + 100


# ------------------------------------------------------------------ C1-C7 probes

@needs_compose
def test_c1_empty_and_wrong_length_replies_are_rejected():
    with _world() as cfg:
        _rejects(cfg, "", "empty")
        _rejects(cfg, "Hello there, I am keen.", "length")                         # 5 words < 20 (answer)
        _rejects(cfg, " ".join(["Python"] * 160), "length")                         # > max_words 150
        _rejects(cfg, CLEAN, "length", max_chars=200)                               # 69 words, chars > 200
        _rejects(cfg, " ".join(["I built REST APIs in Python."] * 8), "length",     # 40 words < 80 (letter)
                 kind="letter", max_words=250)


@needs_compose
def test_c2_a_number_the_master_does_not_have_is_rejected():
    with _world() as cfg:
        for extra in ("I also cut costs by 90% last year.", "In 2019 I won a prize.",
                      "I mentored 12 interns."):
            res, _m = _rejects(cfg, CLEAN + " " + extra, "number_added")
        assert any(i.detail.startswith("90") for i in _rejects(
            cfg, CLEAN + " I also cut costs by 90% last year.", "number_added")[0].issues)


@needs_compose
def test_c3_a_skill_only_the_job_description_names_is_rejected():
    """The JD says "Kafka experience is a plus"; the master has no Kafka."""
    with _world() as cfg:
        res, _m = _rejects(cfg, CLEAN + " I also have strong Kafka experience.", "fact_added")
        assert any("kafka" in i.detail.lower() for i in res.issues), [i.detail for i in res.issues]
        _rejects(cfg, CLEAN + " I am comfortable with Docker and RabbitMQ.", "fact_added")


@needs_compose
def test_c3_d183_a_capitalised_sentence_start_word_is_a_fact_candidate_wherever_the_sentence_starts():
    """LF 19.4 D-183: "Stripe taught me to ship." names a company the master and the posting never
    mention. It must be caught at the text start, after ". " and after a blank line."""
    sentence = "Stripe taught me to ship."
    with _world() as cfg:
        for reply in (sentence + " " + CLEAN,                  # at the text start
                      CLEAN + " " + sentence,                  # after ". "
                      CLEAN + NL2 + sentence,                  # after a blank line
                      CLEAN + NL1 + sentence):                 # after a line break
            res, _m = _rejects(cfg, reply, "fact_added")
            assert any(i.detail.lower() == "stripe" for i in res.issues),                 (reply[:30], [i.detail for i in res.issues])


@needs_compose
def test_c3_d183_ordinary_sentence_openers_pass_when_the_rest_is_clean():
    openers = ("Building tools for people is what I enjoy.",
               "My work on REST APIs taught me to care about reliability.",
               "During my internship I learned a great deal.",
               "This is why I want the role.")
    with _world() as cfg:
        for sentence in openers:
            for reply in (sentence + " " + CLEAN, CLEAN + " " + sentence, CLEAN + NL2 + sentence):
                res = _compose(cfg, FakeModel(reply))
                assert res.ok, (sentence, sorted(_codes(res)), [i.detail for i in res.issues])



@needs_compose
def test_c3_d183_a_sentence_start_word_the_master_holds_in_lower_case_passes():
    """The master says "pandas" in lower case; "Pandas ..." opening a sentence is the same word. On a
    master without it, the same sentence is an added fact."""
    sentence = "Pandas is a library I have used."

    def has_pandas(d):
        d["sections"][1]["entries"][0]["bullets"][0]["text"] += " Wrote reports with pandas."
    with _world(edit=has_pandas) as cfg:
        res = _compose(cfg, FakeModel(CLEAN + " " + sentence))
        assert res.ok, (sorted(_codes(res)), [i.detail for i in res.issues])
        res = _compose(cfg, FakeModel(sentence + " " + CLEAN))
        assert res.ok, (sorted(_codes(res)), [i.detail for i in res.issues])
    with _world() as cfg:
        res, _m = _rejects(cfg, CLEAN + " " + sentence, "fact_added")
        assert any(i.detail.lower() == "pandas" for i in res.issues), [i.detail for i in res.issues]


@needs_compose
def test_c4_a_stronger_verb_is_rejected_unless_the_master_has_it():
    with _world() as cfg:
        res, _m = _rejects(cfg, CLEAN + " I led the data team and owned the roadmap.", "verb_upgrade")
        assert any(i.detail.lower() in ("led", "owned") for i in res.issues), [i.detail for i in res.issues]

    def has_led(d):
        d["sections"][1]["entries"][0]["bullets"][0]["text"] = \
            "Led a small team that built REST APIs in Python and Postgres for shipment tracking."
    with _world(edit=has_led) as cfg:
        res = _compose(cfg, FakeModel(CLEAN + " I led the Python work."))
        assert res.ok, (sorted(_codes(res)), [i.detail for i in res.issues])


@needs_compose
def test_c5_a_private_value_is_rejected_and_no_issue_names_it():
    secrets = (PHONE, PHONE_DIGITS, EMAIL, "12 Fictional Road")
    probes = {
        "the phone as given": f"Call me on {PHONE}.",
        "the phone in digit runs": "My number is 9123 4567.",
        "the phone with no spaces": f"Reach me at {PHONE_DIGITS}.",
        "the email": f"Write to {EMAIL}.",
        "another email": "Write to someone@mail.example.",
        "a listed S value": "I live at 12 Fictional Road.",
        "a link the master lacks": "My work is at github.com/jane-tan-demo.",
    }
    with _world() as cfg:
        for name, sentence in probes.items():
            res, _m = _rejects(cfg, CLEAN + " " + sentence, "private_value", s_values=secrets)
            for i in res.issues:
                blob = f"{i.code.value} {i.detail}".lower()
                for s in secrets + ("9123", "4567", "jane-tan-demo", "fictional"):
                    assert s.lower() not in blob, (name, "issue detail names a private value")


@needs_compose
def test_c5_a_long_digit_run_and_an_email_are_private_even_without_s_values():
    with _world() as cfg:
        _rejects(cfg, CLEAN + " My number is 9123 4567.", "private_value", s_values=())
        _rejects(cfg, CLEAN + " Write to jane@elsewhere.example.", "private_value", s_values=())


@needs_compose
def test_c6_a_watchlist_employer_the_applicant_never_worked_for_is_rejected():
    with _world() as cfg:
        _rejects(cfg, CLEAN + " I admire Globex Corporation for its culture.", "other_employer",
                 other_employers=("Globex Corporation",))
        _rejects(cfg, CLEAN + " I also respect Initech.", "other_employer",
                 other_employers=("Initech Pte Ltd", "Hooli"))
        res = _compose(cfg, FakeModel(CLEAN), _req(other_employers=("Globex Corporation", "Hooli")))
        assert res.ok, "an employer that is not named is not a hit"


@needs_compose
def test_c7_placeholders_are_rejected():
    with _world() as cfg:
        for bit in ("Sincerely, [Name]", "Dear <hiring manager>,", "Lorem ipsum dolor sit amet.",
                    "Regards, your name", "I like company name very much."):
            _rejects(cfg, CLEAN + " " + bit, "placeholder")


# ------------------------------------------------------------------ privacy of the prompt

@needs_compose
def test_redact_covers_the_whole_user_prompt_and_the_retry():
    """`redact(user_prompt, s_values)` is applied to JOB, QUESTION and RESUME alike, and again to
    the retry prompt: three markers, one in each block, are gone from every recorded prompt."""
    seen = []

    def redact(text, s_values):
        seen.append((text, tuple(s_values)))
        return text.replace("Orbit", "#J#").replace("hobby", "#Q#").replace("Acme", "#R#")
    with _world() as cfg:
        model = FakeModel(CLEAN + " I also have strong Kafka experience.", CLEAN)
        res = _compose(cfg, model, _req(question="Tell us about your hobby", s_values=("sv-1", "sv-2")),
                       redact=redact)
        assert res.ok and len(model.calls) == 2
        assert len(seen) >= 2 and all(s == ("sv-1", "sv-2") for _t, s in seen)
        assert all("JOB:" in t and "QUESTION:" in t and "RESUME:" in t for t, _s in seen[:2]), \
            "the whole prompt is redacted in one piece"
        for c in model.calls:
            assert "#J#" in c["user"] and "#Q#" in c["user"] and "#R#" in c["user"]
            for raw in ("Orbit", "hobby", "Acme"):
                assert raw not in c["user"], raw


@needs_compose
def test_no_s_value_and_no_contact_block_reach_the_model():
    from jobscraper.apply import llm_fill
    from llm_fill_support import find_secrets, sample_secrets
    secrets = sample_secrets() + [PHONE, PHONE_DIGITS, EMAIL]
    with _world() as cfg:
        model = FakeModel(CLEAN + " I also have strong Kafka experience.", CLEAN)
        req = _req(question=f"Why join us? (write to {EMAIL} or call {PHONE})",
                   jd_text=f"Contact the team on {PHONE}. Kafka is a plus. Reference {EMAIL}.",
                   s_values=tuple(secrets))
        res = _compose(cfg, model, req, redact=llm_fill.redact)
        assert res.ok and len(model.calls) == 2
        assert not find_secrets(model.prompts, secrets), "an S value reached a prompt"
        for token in (PHONE, PHONE_DIGITS, EMAIL, NAME):
            assert token not in model.prompts, "the contact block is not in the RESUME text"


# ------------------------------------------------------------------ retry

@needs_compose
def test_the_retry_happens_once_with_a_fix_line_then_passes():
    with _world() as cfg:
        model = FakeModel(CLEAN + " I also have strong Kafka experience.", CLEAN)
        res = _compose(cfg, model)
        assert res.ok and res.text == CLEAN and res.attempts == 2 and len(model.calls) == 2
        u1, u2 = model.calls[0]["user"], model.calls[1]["user"]
        assert "FIX:" not in u1 and "FIX:" in u2
        fix = u2[u2.index("FIX:"):]
        assert "fact_added" in fix and "kafka" in fix.lower(), fix
        assert u2.split("FIX:")[0].strip() == u1.strip(), "the retry repeats the prompt, then adds the line"
        assert model.calls[0]["system"] == model.calls[1]["system"]


@needs_compose
def test_two_failures_end_it_with_no_third_call_and_no_text():
    with _world() as cfg:
        model = FakeModel(CLEAN + " I led it.", CLEAN + " I also have Kafka.", CLEAN)
        res = _compose(cfg, model)
        assert not res.ok and res.text == "" and res.attempts == 2 and len(model.calls) == 2
        assert res.error == "" and res.issues, "a check failure, not an error"
        assert [i.code.value for i in res.issues] and "verb_upgrade" not in _codes(res), \
            "issues describe the last attempt"
        assert "fact_added" in _codes(res)


@needs_compose
def test_the_fix_line_never_echoes_a_private_value():
    with _world() as cfg:
        model = FakeModel(CLEAN + f" Call {PHONE} or write {EMAIL}.", CLEAN)
        res = _compose(cfg, model, _req(s_values=(PHONE, EMAIL)))
        assert res.ok and len(model.calls) == 2
        u2 = model.calls[1]["user"]
        fix = u2[u2.index("FIX:"):]
        assert "private_value" in fix
        for bit in (PHONE, PHONE_DIGITS, "9123", "4567", EMAIL, "jane.tan"):
            assert bit not in fix, "the FIX line names a category, never the value"


# ------------------------------------------------------------------ errors and logging

@needs_compose
def test_a_master_cache_miss_is_no_master_and_the_model_is_not_called():
    with _world(master=False) as cfg:
        model = FakeModel(CLEAN)
        res = _compose(cfg, model)
        assert not res.ok and res.error == "no master" and res.text == ""
        assert model.calls == [], "no master -> no model call, no resume parse"


@needs_compose
def test_a_stale_master_hash_is_also_no_master():
    from jobscraper.profile import resume_ingest
    with _world() as cfg:
        resume_ingest.file_hash = lambda p: "sha256:another-resume"          # restored by _world
        res = _compose(cfg, FakeModel(CLEAN))
        assert not res.ok and res.error == "no master"


@needs_compose
def test_a_backend_failure_is_a_transport_error_with_no_text():
    from jobscraper.backends import BackendError
    with _world() as cfg:
        res = _compose(cfg, FakeModel(BackendError("connection refused: " + EMAIL)))
        assert not res.ok and res.error.startswith("transport"), res.error
        assert res.text == "" and EMAIL not in res.error and CLEAN[:20] not in res.error


@needs_compose
def test_no_text_is_ever_logged():
    marker_reply, marker_q, marker_jd = "Quillfeather", "Zephyrtown", "Mossbridge"
    sent = (CLEAN + f" {marker_reply} led it. Write to {EMAIL}.")
    records: list[str] = []

    class Grab(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage() + " " + str(record.args))
    h, root = Grab(level=logging.DEBUG), logging.getLogger()
    old = root.level
    root.addHandler(h)
    root.setLevel(logging.DEBUG)
    try:
        with _world() as cfg:
            ok = _compose(cfg, FakeModel(CLEAN, CLEAN), _req(question=f"Why join {marker_q}?",
                                                              jd_text=f"{marker_jd} " * 5))
            bad = _compose(cfg, FakeModel(sent, sent), _req(question=f"Why join {marker_q}?",
                                                             jd_text=f"{marker_jd} " * 5,
                                                             s_values=(EMAIL,)))
            assert ok.ok and not bad.ok
    finally:
        root.removeHandler(h)
        root.setLevel(old)
    blob = "\n".join(records)
    for needle in (marker_reply, marker_q, marker_jd, EMAIL, "REST APIs", "Acme", "Orbit Analytics",
                   "shipment tracking", CLEAN[:30]):
        assert needle not in blob, f"a text fragment reached the log: {needle!r}"


# ------------------------------------------------------------------ write_letter

LETTER = ("Dear Hiring Team,\n\nI am keen to join Orbit Analytics as a Data Engineer.\n\n"
          "At Acme Logistics I built REST APIs in Python.\n\nThank you for your time.")


@needs_compose
def test_write_letter_writes_a_docx_of_plain_paragraphs_and_returns_the_path():
    import tempfile
    from jobscraper import tailor_flow
    d = Path(tempfile.mkdtemp(prefix="t7_letter_"))
    path = d / "attempt-7" / "cover_letter.docx"                     # the folder does not exist yet
    out = tailor_flow.write_letter(LETTER, path, "docx")
    assert Path(out) == path and path.is_file()
    assert path.read_bytes()[:2] == b"PK", "a real .docx (zip) file"
    import docx
    paras = [p.text for p in docx.Document(str(path)).paragraphs if p.text.strip()]
    assert paras == ["Dear Hiring Team,", "I am keen to join Orbit Analytics as a Data Engineer.",
                     "At Acme Logistics I built REST APIs in Python.", "Thank you for your time."], paras
    joined = " ".join(paras)
    assert NAME not in joined and "@" not in joined, "no name and no contact block"


@needs_compose
def test_write_letter_writes_utf8_text_for_txt_and_keeps_the_text():
    import tempfile
    from jobscraper import tailor_flow
    d = Path(tempfile.mkdtemp(prefix="t7_letter_"))
    path = d / "cover_letter.txt"
    out = tailor_flow.write_letter("Dear team,\n\nI like café data – and APIs.", path, "txt")
    assert Path(out) == path
    body = path.read_text(encoding="utf-8")
    assert "café data – and APIs." in body and body.count("Dear team,") == 1
    assert not path.read_bytes().startswith(b"PK"), "txt is not a docx"


if WAITING[_W0:]:
    print(f"[test_tailor_compose] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
