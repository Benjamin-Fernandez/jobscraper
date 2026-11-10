"""WP-T7 (Q-45) rows for `questions.compose_needed` and its capture (llm_fill_design §19.1, §19.2,
§19.3 step 3, §19.6; contracts v5 `QuestionReason.COMPOSE_NEEDED`). Also the file the build plan
names for WP-M5's page-capture oracles (`-k apply_questions_page`); the other M5 cases live in
test_questions_capture_page.py and test_llm_fill_probes.py.

  - which fields are compose targets: a FILE labelled (or helped) cover letter / motivation letter;
    a TEXTAREA outside entry groups with a cover-letter or motive label; nothing else;
  - a required target the program could not write is captured per posting, reason `compose_needed`,
    for each of the three notes (`off`, `failed check`, `no master`), the note kept readable for
    the QuestionCard hint (§19.6); an optional target and a transport failure are never captured;
  - the saved answer is per posting: the qualified label carries `compose @<employer>#<sha8(jd)>`.
Skip-clean until `questions.compose_needed` and `capture_page` exist. Verify: -k apply_questions_page
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

_W0 = len(WAITING)
NEEDS = ("jobscraper.apply.questions:compose_needed", "jobscraper.apply.questions:capture_page",
         "jobscraper.apply.contracts:QuestionReason.COMPOSE_NEEDED")


def _form(label, ftype, *, description="", required=True):
    from jobscraper.apply.contracts import FormField
    return FormField(key="k", label=label, type=ftype, required=required, description=description,
                     step="questions")


def _unknown(key, note):
    from jobscraper.apply.contracts import Answer, AnswerStatus as AS, AnswerTier
    return Answer(field_key=key, value=None, tier=AnswerTier.NONE, source="", confidence=0.0,
                  status=AS.UNKNOWN, note=note)


@needs(*NEEDS)
def test_compose_targets_are_cover_letters_and_motivation_texts_only():
    from jobscraper.apply import questions as Q
    from jobscraper.apply.contracts import FieldType as FT
    yes = [("Cover Letter", FT.FILE, ""), ("Upload your resume or CV", FT.FILE, "Add a cover letter too"),
           ("Motivation letter", FT.FILE, ""), ("Cover letter", FT.TEXTAREA, ""),
           ("Why do you want to join us?", FT.TEXTAREA, ""),
           ("Why are you interested in working at Example?", FT.TEXTAREA, ""),
           ("Why do you want to apply for this role?", FT.TEXTAREA, ""),
           ("What motivates you to apply?", FT.TEXTAREA, ""),
           ("What excites you about this role?", FT.TEXTAREA, "")]
    no = [("Describe a project you are proud of", FT.TEXTAREA, ""),
          ("Why did you leave your last job?", FT.TEXTAREA, ""),
          ("Why do you want to join us?", FT.TEXT, ""),           # a one-line TEXT is not composed
          ("Transcript", FT.FILE, ""), ("Portfolio", FT.FILE, ""), ("Resume", FT.FILE, ""),
          ("First name", FT.TEXT, "")]
    for label, t, desc in yes:
        assert Q.compose_needed(_form(label, t, description=desc)) is True, (label, t)
    for label, t, desc in no:
        assert Q.compose_needed(_form(label, t, description=desc)) is False, (label, t)


@needs(*NEEDS)
def test_a_textarea_inside_an_entry_group_is_not_a_compose_target():
    from jobscraper.apply import questions as Q
    from jobscraper.apply.contracts import FieldType as FT
    f = _form("Why do you want to join us?", FT.TEXTAREA)
    assert Q.compose_needed(f, "") is True and Q.compose_needed(f, "work_experience#1") is False


@needs(*NEEDS)
def test_each_compose_note_is_captured_per_posting_with_reason_compose_needed():
    from jobscraper.apply import questions as Q
    from jobscraper.apply.contracts import FieldType as FT, QuestionReason
    import llm_fill_t2 as T
    import test_llm_fill_probes as P
    for note in ("compose_needed: off", "compose_needed: failed check", "compose_needed: no master"):
        fields = [P._pf("cl", "Cover Letter", FT.FILE), P._pf("why", "Why do you want to join us?", FT.TEXTAREA)]
        labels = {}
        for jd in ("Build data pipelines.", "Design chips."):
            ctx = T.rctx(jd_text=jd)
            got = {c.field_key: c for c in Q.capture_page(
                fields, {"cl": _unknown("cl", note), "why": _unknown("why", note)}, ctx, T.rules())}
            assert set(got) == {"cl", "why"}, (note, set(got))
            for c in got.values():
                assert c.reason is QuestionReason.COMPOSE_NEEDED, (note, c.reason)
                assert c.required is True and not c.sensitive
                assert note.split(": ", 1)[1] in c.note, (note, c.note)       # the hint's key survives
                assert re.search(r"compose @[^#]+#[0-9a-f]{8}$", c.label_norm), c.label_norm
            labels[jd] = got["why"].label_norm
        a, b = labels.values()
        assert a != b, "the saved answer is per posting (sha8 of the JD), never reused for another job"


@needs(*NEEDS)
def test_an_optional_target_and_a_transport_failure_are_never_captured():
    from jobscraper.apply import questions as Q
    from jobscraper.apply.contracts import FieldType as FT
    import llm_fill_t2 as T
    import test_llm_fill_probes as P
    fields = [P._pf("cl", "Cover Letter", FT.FILE, required=False),
              P._pf("why", "Why do you want to join us?", FT.TEXTAREA, required=False),
              P._pf("m", "What motivates you to apply?", FT.TEXTAREA)]
    answers = {"cl": _unknown("cl", "cover letter is optional"), "why": _unknown("why", "compose_needed: off"),
               "m": _unknown("m", "transport: the model did not answer")}
    assert Q.capture_page(fields, answers, T.rctx(), T.rules()) == []


if WAITING[_W0:]:
    print(f"[test_apply_questions_page] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
