"""Q-128, the strings that came from `src/`: "Application details" became "Your details" in the contract
texts (`arch/Q-128-strings`) and in the CLI (`eng/Q-128-strings`).

  * the missing-details stop's text / hint through the Applications attempt view, and the queue pause
    payload (`GET /api/apply/status`.queue.paused) that carry them;
  * the CLI lines (doctor profile line, `applicant refresh-resume`) through the q44 fakes and a temp
    config: nothing is run against the repository's `data/`;
  * a sweep: no owner-facing string literal in `src/jobscraper` says "Application details".
    ALLOWED, and why: docstrings and comments (developers read them; comments are not in the AST),
    and the log lines that begin "application details check" (they are matched against the job log by
    `cli.SKIP_MODEL_DOWN` / `Profile.vue`; the owner never sees them).
Verify: python tests/run_tests.py -k q128
"""
from __future__ import annotations

import ast
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_q44_refresh import _cfg_with_applicant, _patched, _ready_props, _ready_world_profile, _run  # noqa: E402
from test_q76_attempts import _row  # noqa: E402

from jobscraper import applicant  # noqa: E402
from jobscraper.apply import contracts as C  # noqa: E402
from jobscraper.web.routers.applications import attempt_view  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "src" / "jobscraper"


# ---- the contract texts ---------------------------------------------------------------------------

def test_q128_the_missing_details_stop_says_your_details_in_text_and_hint():
    v = attempt_view(_row(state="failed", reason_code="profile_incomplete", reason_detail="contact.email"))
    assert v["text"] == "Your details are missing: contact.email."
    assert v["hint"] == "Fill them in under Profile → Your details, then try again."
    assert "pplication details" not in v["text"] + v["hint"]


def test_q128_the_contract_tables_hold_the_new_sentences_and_no_old_one():
    t = C.REASON_TEXTS[C.ReasonCode.PROFILE_INCOMPLETE]
    assert (t.text, t.hint) == ("Your details are missing: {detail}.",
                                "Fill them in under Profile → Your details, then try again.")
    q = C.QUEUE_PAUSE_TEXTS[C.QueuePause.PROFILE_INCOMPLETE]
    assert (q.text, q.hint) == ("Your details are missing: {detail}.",
                                "Fill them in under Profile → Your details, then resume.")
    for copy in list(C.REASON_TEXTS.values()) + list(C.QUEUE_PAUSE_TEXTS.values()):
        assert "pplication details" not in copy.text + copy.hint, copy


def test_q128_the_queue_pause_payload_says_your_details_then_resume():
    from jobscraper.web.routers.apply import _pause_copy
    p = _pause_copy(C.QueuePause.PROFILE_INCOMPLETE.value, "contact.email, contact.city", "2026-11-19T10:00:00Z")
    assert p["text"] == "Your details are missing: contact.email, contact.city."
    assert p["hint"] == "Fill them in under Profile → Your details, then resume."
    assert p["reason"] == "profile_incomplete"


# ---- the CLI lines --------------------------------------------------------------------------------

def test_q128_the_doctor_profile_line_says_your_details():
    from jobscraper import cli
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        missing = Path(tmp) / "nope.yaml"
        line = cli._profile_shape_lines(missing)
        assert line == ["profile shape  no profile file yet (fill it in under Profile -> Your details)"], line
        bad = Path(tmp) / "bad.yaml"
        bad.write_text("a: [unclosed\n", encoding="utf-8")
        line = cli._profile_shape_lines(bad)
        assert len(line) == 1 and line[0].endswith("open Profile -> Your details to fix it"), line
        assert "pplication details" not in " ".join(line)


def test_q128_refresh_resume_prints_your_details_and_a_readable_heading_DEFECT_space():
    """DEFECT (cli.py:1107, eng/Q-128-strings e06f540: the f-string reads "from{...}", no space): the heading must read "Update your details from <source>" with a space before the source."""
    from jobscraper import cli
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        cfg, path = _cfg_with_applicant(tmp, _ready_world_profile())
        props = _ready_props("sha256:r1")
        with _patched(cli, profile_proposals=lambda c, b: props, build=lambda budget: object()):
            rc, out, err = _run(cli._applicant_refresh, cfg, False)
            assert rc == 0 and err == ""
            heading = [ln for ln in out.splitlines() if ln.startswith("Update your details")]
            assert len(heading) == 1, out
            assert re.match(r"^Update your details from \S", heading[0]), repr(heading[0])
            assert "pplication details" not in out
            rc, out, _ = _run(cli._applicant_refresh, cfg, True)
            assert "Saved" in out and "Check them in Profile -> Your details." in out, out
            assert "pplication details" not in out
            rc, out, _ = _run(cli._applicant_refresh, cfg, True)       # nothing left to save
        assert "Your details match your resume." in out, out
        assert "pplication details" not in out
        assert applicant.validate(applicant.load(path)) == []


def test_q128_the_cli_help_says_your_details():
    import argparse
    from jobscraper.cli import build_parser

    def helps(p):
        yield p.format_help()
        for a in p._actions:
            if isinstance(a, argparse._SubParsersAction):
                for child in a.choices.values():
                    yield from helps(child)

    texts = list(helps(build_parser()))
    assert len(texts) > 10
    for t in texts:
        assert "pplication details" not in t, t
    joined = " ".join(" ".join(t.split()) for t in texts)
    assert "compare the resume with your details" in joined
    assert "compare your resume with your details and show what would change" in joined

# ---- the sweep ------------------------------------------------------------------------------------

OLD = re.compile(r"application details?", re.I)
LOG_LINE = re.compile(r"^application details check", re.I)      # matched against the job log; never shown


def _strings(tree):
    """Every string constant that is not a docstring, with its line."""
    doc = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                doc.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc:
            yield node.lineno, node.value


def _shown_old_strings(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [f"{path.relative_to(SRC.parent.parent)}:{n}: {s.strip()[:80]}"
            for n, s in _strings(tree) if OLD.search(s) and not LOG_LINE.match(s.strip())]


def test_q128_no_owner_facing_string_in_src_says_application_details():
    files = sorted(SRC.rglob("*.py"))
    assert len(files) > 40 and (SRC / "apply" / "contracts.py") in files and (SRC / "cli.py") in files
    found = [hit for f in files for hit in _shown_old_strings(f)]
    assert found == [], "\n".join(found)


def test_q128_the_src_sweep_sees_a_planted_string_and_skips_docstrings_comments_and_log_lines():
    tree = ast.parse(
        '"""Module doc: Application details."""\n'
        'def f():\n'
        '    """Docstring about application details."""\n'
        '    # comment about Application details\n'
        '    a = "Fill them in under Profile -> Application details"\n'
        '    b = "application details check skipped: X"\n'
        '    return a, b\n')
    got = [(n, s) for n, s in _strings(tree) if OLD.search(s) and not LOG_LINE.match(s.strip())]
    assert got == [(5, "Fill them in under Profile -> Application details")], got
