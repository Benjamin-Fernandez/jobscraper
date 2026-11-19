"""Q4: 30 new labels aimed at what was added since 599fd44 (M2: sentence punctuation / an opening bracket ends the follower
run; new function words once / whilst / whenever / effective / starting / commencing / beginning / immediately; _JOB_PLACE).
exp = what is right: 'SG' (Singapore's facts), or 'empty' (two places / an unknown place / another country: no truth).
Replies: the one a decent model gives for a Singapore wording ('Singapore' / 'this country' / 'here'), and NONE (the real
model for status-like wordings). A written value from Singapore's facts where exp is 'empty' is marked '!!'."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S1-probes")
from h2 import *  # noqa

L = [
    ("Are you authorised to work in Singapore (including Hong Kong)?", "empty", "Singapore"),
    ("Are you authorised to work in Singapore (and Malaysia)?", "empty", "Singapore"),
    ("Are you authorised to work in Singapore; Malaysia; Indonesia?", "empty", "Singapore"),
    ("Are you authorised to work in Singapore; Hong Kong; Tokyo?", "empty", "Singapore"),
    ("Are you authorised to work in Singapore? Applicants for Hong Kong roles answer No.", "empty", "Singapore"),
    ("Are you authorised to work in Singapore? (or in the US)", "empty", "Singapore"),
    ("Are you authorised to work in Singapore, Hong Kong or Tokyo?", "empty", "Singapore"),
    ("Are you authorised to work in Singapore from Malaysia?", "empty", "Singapore"),
    ("Are you authorised to work in Singapore as well as Malaysia?", "empty", "Singapore"),
    ("Are you authorised to work in Singapore starting from our Tokyo office?", "empty", "Singapore"),
    ("Are you authorised to work in Singapore effective in the US?", "empty", "Singapore"),
    ("Are you authorised to work in Singapore whilst based in Malaysia?", "empty", "Singapore"),
    ("Are you authorised to work in Singapore once relocated to Hong Kong?", "empty", "Singapore"),
    ("Are you authorised to work in Singapore beginning in Tokyo?", "empty", "Singapore"),
    ("Do you have the right to work in the country where this role is based? (US applicants only)", "empty", "this country"),
    ("Do you have the right to work here or in the US?", "empty", "here"),
    ("Are you authorised to work in this country and the US?", "empty", "this country"),
    ("Are you authorised to work in the country where this role is based or elsewhere?", "empty", "the country where this role is based"),
    ("Are you authorised to work in the country in which you are applying or the US?", "empty", "the country in which you are applying"),
    ("Where you are applying, are you authorised to work?", "SG", "where you are applying"),
    ("Are you authorised to work in the location of this job, or any other?", "empty", "the location of this job"),
    ("Are you authorised to work in the country you are applying to or residing in?", "empty", "the country you are applying to"),
    ("Do you require sponsorship to work in the country of this posting or the UK?", "empty", "the country of this posting"),
    ("Do you have the right to work here (US)?", "empty", "here"),
    ("Are you eligible to work in Singapore. If you are in Malaysia, select No.", "empty", "Singapore"),
    ("Are you authorised to work in Singapore. Are you authorised to work in the US?", "empty", "Singapore"),
    ("Are you authorised to work in Singapore - or the US?", "empty", "Singapore"),
    ("Do you have the right to work in Singapore and the right to work in the US?", "empty", "Singapore"),
    ("Are you authorised to work in Singapore immediately?", "SG", "Singapore"),
    ("Are you authorised to work in Singapore effective immediately? Please answer honestly.", "SG", "Singapore"),
    ("Are you authorised to work in Singapore (full-time)?", "SG", "Singapore"),
]
if __name__ == "__main__":
    bad = 0
    for label, exp, rep in L:
        cells = []
        for r_ in (rep, "NONE"):
            ask = FakeAsk(lambda v: lie("Yes", "work_right"), pick=make_pick("faithful", "Yes", "Yes"), place=r_)
            res = attempt(mk(label), ask, None)
            w = "STOP" if is_stop(res) else (shown(res) or "-")
            wr = w in ("Yes", "No")
            mark = "!!" if (exp == "empty" and wr) else ("e" if exp == "SG" and not wr else "")
            if mark == "!!":
                bad += 1
            cells.append(f"{r_[:12]:12}->{w}{mark}")
        print(f"{label[:84]:84} exp={exp:5} | " + " | ".join(cells))
    print("wrong-country-or-multi-place writes:", bad)
