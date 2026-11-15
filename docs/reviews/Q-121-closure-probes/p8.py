"""Q2 (L5): partial quotes. For each label a model that quotes only 'Singapore' (or the stated quote). Print: quoted_place
result, code_place (found, unknown, place), work_place countries, and end to end what is written for a wrong-by-Singapore
model (Singapore truth: authorised=Yes) when the label's real place is something else."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa

# (label, quote the model gives, the place the question REALLY asks about: SG / other)
CASES = [
    ("Are you authorised to work in Singapore and Malaysia?", "Singapore", "other"),
    ("Are you authorised to work in Singapore or Malaysia?", "Singapore", "other"),
    ("Are you authorised to work in Singapore as well as Malaysia?", "Singapore", "other"),
    ("Are you authorised to work in Singapore after relocating from Jakarta to Kuala Lumpur?", "Singapore", "other"),
    ("Are you authorised to work in Singapore after relocating to Jakarta?", "Singapore", "other"),
    ("Are you authorised to work in Singapore while based in Vietnam?", "Singapore", "other"),
    ("Are you authorised to work in Singapore until you move to our Tokyo office?", "Singapore", "other"),
    ("Are you authorised to work in Singapore permanently or elsewhere temporarily?", "Singapore", "other"),
    ("Are you authorised to work in Singapore before transferring to the US?", "Singapore", "other"),
    ("Are you authorised to work in Singapore as well as the US?", "Singapore", "other"),
    ("Are you authorised to work in Singapore, Malaysia and Indonesia?", "Singapore", "other"),
    ("Are you authorised to work in Singapore and the US?", "Singapore", "other"),
    ("Are you authorised to work in Singapore under a Malaysian work permit?", "Singapore", "?"),
    ("Are you authorised to work in Singapore from Malaysia?", "Singapore", "other"),
    ("Are you authorised to work in Singapore from Bangkok?", "Singapore", "other"),
    ("Are you authorised to work in Singapore for a Tokyo-based employer?", "Singapore", "?"),
    ("Are you authorised to work in Singapore for a client in Australia?", "Singapore", "?"),
    ("Are you authorised to work in Singapore once relocated from London?", "Singapore", "other"),
    ("Are you authorised to work in Singapore when travelling to Germany?", "Singapore", "other"),
    ("Are you authorised to work in Singapore if you relocate from Penang?", "Singapore", "other"),
    ("Are you authorised to work in Singapore since moving from Hanoi?", "Singapore", "other"),
    ("Are you authorised to work in Singapore than in Malaysia?", "Singapore", "other"),
    ("Are you authorised to work in Singapore via a Hong Kong entity?", "Singapore", "other"),
    ("Are you authorised to work in Singapore per the Dubai office policy?", "Singapore", "?"),
    ("Are you authorised to work in Singapore during your stay in Kuala Lumpur?", "Singapore", "other"),
    ("Are you authorised to work in Singapore on a Penang-issued permit?", "Singapore", "?"),
    ("Are you authorised to work in Singapore or the Philippines?", "Singapore", "other"),
    ("Are you authorised to work in Singapore without sponsorship from Malaysia?", "Singapore", "?"),
    ("Are you authorised to work in Singapore without leaving Perth?", "Singapore", "other"),
    ("Are you authorised to work in Singapore if hired by our Sydney team?", "Singapore", "?"),
    ("Are you authorised to work in Singapore after a transfer to Zurich?", "Singapore", "other"),
    ("Are you authorised to work in Singapore as a Berlin resident?", "Singapore", "other"),
    ("Are you authorised to work in Singapore before you start in Toronto?", "Singapore", "other"),
    ("Are you authorised to work in Singapore at the Mumbai delivery centre?", "Singapore", "other"),
    ("Are you authorised to work in Singapore and in Seoul?", "Singapore", "other"),
    ("Are you authorised to work in Singapore for our Auckland office?", "Singapore", "other"),
    ("Are you authorised to work in Singapore for any employer?", "Singapore", "SG"),
    ("Are you authorised to work in Singapore permanently?", "Singapore", "SG"),
    ("Are you authorised to work in Singapore under an Employment Pass?", "Singapore", "SG"),
    ("Are you authorised to work in Singapore without sponsorship?", "Singapore", "SG"),
    ("Are you authorised to work in Singapore full-time?", "Singapore", "SG"),
    ("Are you authorised to work in Singapore without restrictions?", "Singapore", "SG"),
    ("Are you authorised to work in Singapore at any time?", "Singapore", "SG"),
    ("Are you authorised to work in the Singapore office?", "Singapore", "SG"),
    ("Are you authorised to work in Singapore's Jurong office?", "Singapore", "?"),
    ("Are you authorised to work in Singapore Airlines?", "Singapore", "?"),
]
print(f"{'label':88} qp   code_place(found,unk,place)  wp           e2e(model Yes)")
for label, quote, real in CASES:
    qp = AL.quoted_place(quote, label, "SG")
    pf = mk(label)
    cp = AL.code_place(pf, "SG")
    cp_s = f"({','.join(sorted(cp[0])) or '-'},{int(cp[1])},{int(cp[2])})"
    ask = FakeAsk(lambda v: lie("Yes", "work_right"), pick=lambda q, w, o: "no" if str(w).startswith("If the") else "Yes", place=quote)
    res = attempt(pf, ask)
    out = "STOP" if is_stop(res) else (shown(res) or "-")
    note = "" if is_stop(res) else (" " + str(res.note)[:34])
    flag = ""
    if real == "other" and out not in ("-", "STOP"):
        flag = "  <== WRONG-PLACE WRITE"
    print(f"{label[:88]:88} {qp or '-':3}  {cp_s:22}  {out}{note}{flag}")
