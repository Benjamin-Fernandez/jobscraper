"""1(f): S3 frames whole-label or not. Model answers the TRUE value with class work_right (or none); report the
vote calls it took, the source, assumed, what was written. Then a wrong model."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
from h import _profile, _pf, _run, _one

LABELS = [
    ("Are you a Singapore citizen?", "Yes"),
    ("Are you a Singapore citizen", "Yes"),
    ("Are you a Singapore citizen? (Y/N)", "Yes"),
    ("Are you a Singapore citizen? *", "Yes"),
    ("Are you a Singapore citizen? (required)", "Yes"),
    ("Please confirm: are you a Singapore citizen?", "Yes"),
    ("Are you a Singapore citizen? Please select one.", "Yes"),
    ("Are you a Singapore citizen? If not, please state your visa type.", "Yes"),
    ("Are you a Singapore citizen? Are you a Singapore PR?", "Yes"),
    ("Are you a Singapore citizen or PR?", "Yes"),
    ("Are you a Singapore citizen or a Permanent Resident?", "Yes"),
    ("Are you a Singapore Citizen or Permanent Resident?", "Yes"),
    ("Are you a Singaporean?", "Yes"),
    ("Are you a Singaporean or Singapore PR?", "Yes"),
    ("Do you hold Singapore citizenship?", "Yes"),
    ("Do you hold a Singapore passport?", "Yes"),
    ("Are you a citizen of Singapore?", "Yes"),
    ("Are you a national of Singapore?", "Yes"),
    ("Are you a Singapore PR?", "No"),
    ("Are you a Singapore Permanent Resident?", "No"),
    ("Are you a US citizen?", "No"),
    ("Are you a Malaysian?", "No"),
    ("Are you a citizen of the United States?", "No"),
    ("Do you hold a UK passport?", "No"),
    ("Are you a Singapore citizen or a US citizen?", None),
    ("Are you a Singapore citizen by descent?", "Yes"),
    ("Are you currently a Singapore citizen?", "Yes"),
    ("Are you still a Singapore citizen?", "Yes"),
]
for label, right in LABELS:
    out = []
    for mname, mval in (("right", right), ("wrong", None if right is None else ("No" if right == "Yes" else "Yes"))):
        if mval is None:
            continue
        for klass in ("work_right", "ordinary"):
            def pick(q, w, o, right=right):
                w = str(w)
                if w.startswith("If the applicant answers"):
                    import re
                    m = re.search(r"answers «(.*?)» to the question", w)
                    return "no" if m and m.group(1).strip() == right else "yes"
                return right
            ask = FakeAsk(lambda v, mval=mval, klass=klass: lie(mval, klass), pick=pick, place="NONE")
            res = attempt(mk(label), ask)
            s = "STOP" if is_stop(res) else (shown(res) or "-")
            src = "" if is_stop(res) else str(res.source).split(":")[-1][:14]
            a = "" if is_stop(res) else ("A" if res.assumed else "")
            out.append(f"{mname[0]}/{klass[:4]}={s}{a}[{src}] calls={len(ask.picks)}")
    print(f"{label[:62]:62} | " + " | ".join(out))
