"""H1 evidence: what is written, with what source, for non-applicant status labels."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
for label in ["Is your spouse a Singapore citizen?", "Does the role require a Singapore citizen?",
              "Do you have a family member who is a Singapore citizen?", "Were you a Singapore PR before becoming a citizen?",
              "Is your referee a US citizen?", "Is your father a Singaporean?", "Is your spouse a Singapore PR?"]:
    ask = FakeAsk(lambda v: lie("Yes", "other_person"), pick=lambda q, w, o: "no" if str(w).startswith("If the") else "Yes", place="NONE")
    r = attempt(mk(label), ask)
    print(label, "->", what(r), "| calls", len(ask.picks))
