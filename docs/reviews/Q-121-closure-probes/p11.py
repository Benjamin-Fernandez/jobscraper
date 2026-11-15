"""Q4: M8 neutral words + consent_both_known. Part A: retention_pure over 40 wordings. Part B: end to end, a basis-none
model reply naming a class, over four profiles; optional and required."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
from h import _profile, _pf, _run, _one
from h import _profile
c = ctx()
A = """Keep my application on file for future roles
Keep my details active and available to relevant partners
Match my skills with suitable opportunities at relevant companies
I would like to become a member of your talent community
I would like Example Employer to keep my CV on file
Keep my application active for future roles
Retain my information for future consideration
Please keep my details on file for other suitable roles that match my skills
I authorize Example Employer Pte Ltd to keep my personal data on file for two years
Keep my details on file and match me with relevant roles
Keep my profile active and available for relevant opportunities
Keep my CV on file and I would like to be contacted about relevant roles
Keep my CV on file I wish to be notified of matching roles
Keep my details on file and I want to hear about relevant roles
Keep my details on file I am happy to be called about suitable roles
Keep my CV on file and let relevant hiring managers see it
Keep my CV on file and make it available to relevant teams
Keep my details on file and I would like to become a candidate for relevant roles at Example Employer Pte Ltd
Keep my details on file and match my skills with roles at Inc
Retain my data and make my profile available to relevant roles
Keep my application on file for future roles and I would like updates
Keep my details active and available
Keep my details on file at Example Employer and its Co
Keep my information on file and I would like to become eligible for suitable roles
Keep my CV on file I am available to start
I want Example Employer to keep my details active
Keep my profile active so relevant opportunities match my skills
Store my application and match it to relevant vacancies at Ltd
Keep my resume on file for relevant roles and become part of the pool
Keep my details on file I would like relevant roles
Keep my details on file I would like you to match my skills
Keep my details on file and consider me for any relevant position available
Keep my details on file at Example Employer Pte Ltd Sdn Bhd GmbH
Maintain my profile and match my skills with active vacancies
Keep my details on file I would like to be considered for similar roles at other Example Employer group Co
Hold my application active and available
I want to keep my CV active at Example Employer
I'd like Example Employer to keep my CV on file""".splitlines()
print("PART A retention_pure (True = the box is pure retention: ticked from data_retention_consent alone)")
for lab in A:
    print(f"  {AL.retention_pure(lab, c)!s:5} retain_frame={AL.retain_frame(lab)!s:5} | {lab}")

print("PART B end to end: optional checkbox, model reply basis NONE naming a class")
def prof(**kw):
    p = _profile()
    for k, v in kw.items():
        p["consents"][k] = v
    return p
PROFS = {"sample(ret T, pool F)": _profile(),
         "all false": prof(privacy_consent=False, data_retention_consent=False, talent_pool_opt_in=False, certify_true=False),
         "all true": prof(privacy_consent=True, data_retention_consent=True, talent_pool_opt_in=True, certify_true=True)}
BL = [("Keep my application on file for future roles", "consent_retention"),
      ("I would like Example Employer to keep my CV on file", "consent_retention"),
      ("Keep my application on file and send me job alerts", "consent_retention"),
      ("Keep my application on file and send me job alerts", "marketing"),
      ("I agree to the processing of my personal data", "consent_privacy"),
      ("I agree to the privacy policy", "consent_privacy"),
      ("I confirm the information provided is true and complete", "certification"),
      ("I acknowledge that I have read the application notice", "acknowledgement"),
      ("Send me emails about events and new roles", "marketing"),
      ("Sign me up for the newsletter", "marketing"),
      ("Keep my details and share them with our partner firms", "consent_retention"),
      ("Contact me about other opportunities", "consent_retention"),
      ("I agree to be contacted by Example Employer about other roles", "consent_retention"),
      ("I consent to the transfer of my data to our affiliates", "consent_privacy"),
      ("I agree to receive marketing communications", "consent_privacy"),
      ]
for label, klass in BL:
    row = []
    for pname, p in PROFS.items():
        for required in (False, True):
            ask = FakeAsk(lambda v, klass=klass: say(None, "none", "", False, "none", klass=klass), pick=pick_by("", ""), place="NONE")
            res = attempt(mk(label, "CHECKBOX", (), required=required), ask, p)
            s = ("STOP:" + res.reason.value) if is_stop(res) else ("TICK" if is_ticked(res) else "-")
            row.append(f"{s}")
    print(f"{label[:58]:58} {klass[:11]:11} | " + " ".join(f"{x:22}" for x in row))
print("cols: sample(opt,req) | all false(opt,req) | all true(opt,req)")
