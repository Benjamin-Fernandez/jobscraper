"""the reviewer's p2.py probe as it is, and with a fact-reading confirmer swapped in for its 'follow' column.
Usage: python tests/manual/probe_p2_facts.py [asis|facts]"""
import io, os, re, sys, contextlib
ROOT = os.getcwd()
sys.path[:0] = [ROOT + "/tests", ROOT + "/src", ROOT + "/docs/reviews/Q-121-closure-probes"]
os.environ["JOBSCRAPER_OLLAMA_AUTOSTART"] = "0"
import p2
from test_always_a1_final_r9 import facts_reader, facts_truth, G3_FACT_RULES
import re as _re

mode = sys.argv[1]
# the probe's own table knows the right answer for each label: use it as the facts' answer too (the facts say the same for the citizen)
CORRECT = dict(p2.CASES)

if mode == "facts":
    def truth(q):
        c = CORRECT.get(q)
        return c or ""
    orig_run = p2.run

    def run(label, mval, confirmer, meaning, klass):
        if confirmer != "follow":
            return orig_run(label, mval, confirmer, meaning, klass)
        # same pick as the probe's 'follow' column, except the G3 confirmation / meaning calls read the facts line
        correct = CORRECT[label]
        sq = p2.AL.status_question(p2.mk(label), "SG")
        t = p2.AL.status_truth(sq, p2.ctx())[0] if sq and sq.country else None
        follow_val = ("Yes" if t else "No") if t is not None else "Yes"

        def pick(q, w, o):
            w = str(w)
            if w.startswith("Facts about the applicant"):
                return truth(q)
            if "other than these facts say" in w:
                m = _re.search("answers «(.*?)»", w)
                v = m.group(1).strip().lower() if m else ""
                tt = truth(q).lower()
                return "no" if not tt or v == tt else "yes"
            if w.startswith("If the applicant answers"):
                m = _re.search("answers «(.*?)»", w)
                v = m.group(1).strip() if m else ""
                if meaning == "yes": return "yes"
                if meaning == "no": return "no"
                ref = correct if correct else follow_val
                return "no" if v.lower() == ref.lower() else "yes"
            return follow_val
        ask = p2.FakeAsk(lambda v: p2.lie(mval, klass), pick=pick, place="NONE")
        return p2.attempt(p2.mk(label), ask), ask
    p2.run = run

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    src = open(p2.__file__, encoding="utf-8").read()
    tail = src[src.index('if __name__ == "__main__":'):]          # only the probe's own main block; `run` stays the patched one
    g = dict(p2.__dict__)
    g["__name__"] = "__main__"
    exec(compile(tail, p2.__file__, "exec"), g)
out = buf.getvalue()
print(out)
print("MODE", mode, "wrong-value cells '!':", out.count("!"), " unknowable written '?':", out.count("?"))
