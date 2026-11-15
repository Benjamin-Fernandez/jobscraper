"""Q3 (M7): _JOB_PLACE swallowing another place. work_place(pf, ctx) result + e2e with a model that quotes NONE
(the real model quotes NONE for pointing phrases) or the phrase."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
c = ctx()
LABELS = [
    ("Are you legally authorised to work in the country in which you are applying?", "SG"),
    ("Are you legally authorised to work in the country you are applying to?", "SG"),
    ("Are you legally authorised to work in the country you are applying for?", "SG"),
    ("Are you legally authorised to work in the country you're applying in?", "SG"),
    ("Are you authorised to work in the country of the posting?", "SG"),
    ("Are you authorised to work in the country of this posting?", "SG"),
    ("Are you authorised to work in the country of this advertisement?", "SG"),
    ("Are you authorised to work in the country of this application?", "SG"),
    ("Are you authorised to work where you are applying?", "SG"),
    ("Are you authorised to work in the country of the posting or your country of residence?", "?"),
    ("Are you authorised to work in the country of the posting or the US?", "?"),
    ("Are you authorised to work in the location you are applying for: London?", "?"),
    ("Are you authorised to work in the location you are applying for (London)?", "?"),
    ("Are you authorised to work in the country in which you are applying for citizenship?", "?"),
    ("Are you authorised to work in the country you are applying to from?", "?"),
    ("Are you authorised to work in the country you are applying for, Malaysia?", "?"),
    ("Are you authorised to work where you are applying from?", "?"),
    ("Are you authorised to work where you are applying from, India?", "?"),
    ("Are you authorised to work in the country of the posting and in Malaysia?", "?"),
    ("Are you authorised to work in the country in which you are applying and in the EU?", "?"),
    ("Are you a citizen of the country in which you are applying?", "?"),
    ("Do you hold a work permit for the country you are applying to?", "SG"),
    ("Do you need sponsorship for the country you are applying to?", "SG"),
    ("Are you authorised to work in the country of the application location?", "?"),
    ("Are you authorised to work in the country of the position and the country of your last employer?", "?"),
    ("Are you legally authorised to work in the country of this vacancy?", "?"),
    ("Are you authorised to work in the country of the advertisement, Thailand?", "?"),
    ("Where are you applying from? Are you authorised to work there?", "?"),
    ("Are you authorised to work in the country you are applying for or the UK?", "?"),
]
for label, expect in LABELS:
    pf = mk(label)
    wp = AL.work_place(pf, c)
    ask = FakeAsk(lambda v: lie("Yes", "work_right"), pick=lambda q, w, o: "no" if str(w).startswith("If the") else "Yes", place="NONE")
    res = attempt(pf, ask)
    out = "STOP" if is_stop(res) else (shown(res) or "-")
    cp = AL.code_place(pf, "SG")
    print(f"{label[:92]:92} wp={wp} cp=({','.join(sorted(cp[0])) or '-'},{int(cp[1])}) pure={AL.pure_work_label(pf,'SG',cp[0])} e2e={out} calls={len(ask.place_calls)}  expect={expect}")
