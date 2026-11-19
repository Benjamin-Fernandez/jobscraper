"""What does code's own key (always.code_key) say for the sponsorship wordings where a wrong 'Yes' got through?"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_corpus as RC                                           # noqa: E402
from run_corpus import AL, T, TODAY, _profile, BR                # noqa: E402
from jobscraper import applicant                                 # noqa: E402

p = _profile()
r = T.rctx(p)
ctx = AL.PageCtx(brief=BR.build(p, r, today=TODAY), rctx=r, profile=applicant.normalise(dict(p)),
                 ask=lambda *a, **k: {"text": "{}", "done_reason": "stop"}, rules=T.rules(), today=TODAY, step_title="x")
for lab in ["Will you require us to sponsor you for a work visa?",
            "Would you need Example Co to sponsor you?",
            "Will you require Contoso Logistics to sponsor you for a work visa or employment pass now or in the future?",
            "Will you require visa sponsorship?", "Do you need the company to sponsor your work pass?",
            "Will you require sponsorship for a work visa or employment pass now or in the future?"]:
    pf = T.pf("f", lab, RC.FieldType.RADIO, required=True, options=("Yes", "No"))
    print(f"{lab[:75]:77s} code key = {AL.code_key(pf, ctx)}")
