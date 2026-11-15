"""Q7: availability. 45 typical Singapore work-rights wordings (rebuilt from the third pass's Q5) + 25 status / citizenship /
pass wordings. Run with (I) an idealised fake (tests/place_quote.sensible_quote) and (R) a realistic fake replaying the REAL
model's place replies (fixture; NONE for status wordings and for US wordings; the exact country for plain 'in Singapore'
wordings; whole phrase for open places). The model answers the CORRECT value for the sample owner (SG citizen, authorised
in SG, no sponsorship need), named class = what code names. Votes are faithful (the confirmer answers the correct value;
the meaning call says yes only for a wrong value)."""
import sys, re, json
sys.path.insert(0, "docs/reviews/Q-121-closure-probes"); sys.path.insert(0, "tests")
from h import *  # noqa
from place_quote import sensible_quote
FIXTURE = json.load(open("tests/fixtures/apply/place_replies_qwen3_14b.json", encoding="utf-8"))

Y, N = "Yes", "No"
W = [  # label, correct
    ("Are you legally authorised to work in Singapore?", Y),
    ("Are you authorised to work in Singapore?", Y),
    ("Are you legally authorized to work in Singapore?", Y),
    ("Are you eligible to work in Singapore?", Y),
    ("Are you entitled to work in Singapore?", Y),
    ("Do you have the right to work in Singapore?", Y),
    ("Do you have the legal right to work in Singapore?", Y),
    ("Are you legally permitted to work in Singapore?", Y),
    ("Are you currently authorised to work in Singapore without sponsorship?", Y),
    ("Do you have valid work authorisation for Singapore?", Y),
    ("Are you a Singapore citizen or Permanent Resident?", Y),
    ("Are you a Singapore citizen or PR?", Y),
    ("Are you a Singaporean or Singapore PR?", Y),
    ("Do you hold a valid Singapore work pass (Employment Pass / S Pass)?", N),
    ("Do you currently hold a valid Singapore work pass?", N),
    ("Do you hold an Employment Pass?", N),
    ("Do you hold an S Pass?", N),
    ("Will you now or in the future require sponsorship to work in Singapore?", N),
    ("Will you now or in the future require visa sponsorship?", N),
    ("Do you now or in the future require sponsorship for employment visa status?", N),
    ("Will you require sponsorship for a work pass to work in Singapore?", N),
    ("Do you require visa sponsorship to work in Singapore?", N),
    ("Do you need a work visa to work in Singapore?", N),
    ("Will you require a work visa to take up employment in Singapore?", N),
    ("Will you need the company to sponsor a work pass for you?", N),
    ("Do you require the company's support for a work pass application?", N),
    ("Do you require immigration support or relocation assistance to work in Singapore?", N),
    ("Do you have any restrictions on your right to work in Singapore?", N),
    ("Is your right to work in Singapore limited in any way?", N),
    ("Are there any restrictions on your ability to work in Singapore?", N),
    ("Are you subject to any employment restrictions in Singapore?", N),
    ("Do you have the right to work in the country where this role is based?", Y),
    ("Are you authorised to work in the country where the role is located?", Y),
    ("Are you legally authorized to work in the country in which you are applying?", Y),
    ("Are you legally authorised to work in the country you are applying to?", Y),
    ("Are you authorised to work in the location of this job?", Y),
    ("Do you have work authorisation for the country of this role?", Y),
    ("Can you legally work in this country?", Y),
    ("Do you currently reside in Singapore?", Y),
    ("Are you currently based in Singapore?", Y),
    ("Are you authorised to work in Singapore on a full-time basis?", Y),
    ("Are you able to work in Singapore under an Employment Pass?", N),
    ("Do you have unrestricted work rights in Singapore?", Y),
    ("Are you required to obtain a work pass before starting in Singapore?", N),
    ("Have you completed or are you exempt from National Service in Singapore?", Y),
    # --- 25 status / citizenship / pass wordings of the reviewer
    ("Are you a Singapore citizen?", Y),
    ("Are you a citizen of Singapore?", Y),
    ("Are you a Singapore PR?", N),
    ("Are you a Singapore Permanent Resident?", N),
    ("Are you a Singaporean?", Y),
    ("Do you hold Singapore citizenship?", Y),
    ("Do you hold a Singapore passport?", Y),
    ("Are you a Singapore citizen? (Y/N)", Y),
    ("Singapore citizen or PR?", Y),
    ("Are you a Singapore citizen or hold a Singapore PR?", Y),
    ("Are you a Malaysian citizen?", N),
    ("Are you a US citizen?", N),
    ("Do you hold a valid US work visa?", N),
    ("Do you hold a valid Singapore work permit?", N),
    ("Do you hold a valid Singapore Employment Pass?", N),
    ("Do you hold a Singapore S Pass or Work Permit?", N),
    ("Do you hold a Dependant's Pass or Long Term Visit Pass?", N),
    ("Are you a Singapore resident?", Y),
    ("Are you a permanent resident of Singapore?", N),
    ("Are you a citizen or permanent resident of Singapore?", Y),
    ("Do you hold Singapore citizenship or permanent residency?", Y),
    ("Do you have Singapore PR status?", N),
    ("Are you a Singapore national?", Y),
    ("Are you a Singapore citizen or a holder of a valid work pass?", Y),
    ("Please confirm that you are a Singapore citizen or Permanent Resident", Y),
]

def realistic(label):
    if label in FIXTURE:
        return FIXTURE[label]
    l = label.lower()
    if re.search(r"\bus\b|united states|usa", l):
        return "NONE"
    if re.search(r"outside|elsewhere|other than|any other", l):
        return sensible_quote(label)
    if "country in which you are applying" in l:
        return "the country in which you are applying"
    if re.search(r"country (where|of)|this country|location of|you are applying|this role", l):
        return "NONE"
    # status wordings: the real model answers NONE for 'Are you a Singapore citizen?', 'work pass', PR ...
    if re.search(r"citizen|\bpr\b|permanent resident|singaporean|national\b|passport|work pass|employment pass|s pass|permit|resident|status", l) \
            and not re.search(r"\b(in|within) singapore", l):
        return "NONE"
    if re.search(r"singapore", l):
        return "Singapore"
    return "NONE"

def run_all(mode):
    ans = emp = wrong = 0
    rows = []
    for label, correct in W:
        place = None if mode == "I" else realistic
        def pick(q, w, o, correct=correct):
            w = str(w)
            if w.startswith("If the applicant answers"):
                m = re.search(r"answers «(.*?)» to the question", w)
                return "no" if m and m.group(1).strip() == correct else "yes"
            return correct
        ask = FakeAsk(lambda v, correct=correct: lie(correct, None), pick=pick, place=place)
        res = attempt(mk(label), ask)
        s = "STOP" if is_stop(res) else (shown(res) or "-")
        calls = len(ask.users)
        if s == correct:
            ans += 1; tag = "ok"
        elif s in ("-", "STOP"):
            emp += 1; tag = "EMPTY"
        else:
            wrong += 1; tag = "WRONG"
        rows.append((tag, calls, len(ask.place_calls), label, s))
    return ans, emp, wrong, rows

for mode in ("I", "R"):
    a, e, w, rows = run_all(mode)
    print(f"== mode {mode}: answered-right {a} / empty {e} / wrong {w} of {len(W)}; model calls total {sum(r[1] for r in rows)}, place calls {sum(r[2] for r in rows)}")
    for tag, calls, pc, label, s in rows:
        if tag != "ok":
            print(f"   {tag:5} calls={calls} place={pc} | {label} -> {s}")
