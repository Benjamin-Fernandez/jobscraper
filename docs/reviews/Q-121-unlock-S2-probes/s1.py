"""S1: the class stamp. For each exit path of a consent / declaration field (always policy), the Answer's `field_class`, its
source, and whether web.remember.remember_refusal refuses "Answer for next time". Fake models only."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S2-probes")
from g import *  # noqa
from g import _profile
from jobscraper import apply_flow
from jobscraper.web import remember

p_sample = prof("sample")
p_false = prof("allfalse")


def row_of(pf, res):
    return apply_flow.audit_row("Application", pf.field, res)


def line(name, pf, ask, p):
    res = attempt(pf, ask, p)
    if is_stop(res):
        print(f"{name:52} STOP {res.reason.value}")
        return
    row = row_of(pf, res)
    ref = remember.remember_refusal(row)
    print(f"{name:52} out={out_of(res):10} src={res.source[:28]:28} class={row['field_class'] or '(none)':26} refused={ref.value if ref else 'NO (offered)'}")


CB, YNQ = "CHECKBOX", "RADIO"
agree = lambda k: FakeAsk(lambda v: lie("true", k), pick=lambda q, w, o: "yes", place="NONE")
yes = lambda k: FakeAsk(lambda v: lie("Yes", k), pick=lambda q, w, o: "Yes", place="NONE")

print("-- consent paths (sample profile unless noted)")
line("1 profile-set privacy box, model agrees", mk("I agree to the Privacy Policy", CB, (), required=True), agree("consent_privacy"), p_sample)
line("1b profile-set false marketing box (optional)", mk("Subscribe to our newsletter", CB, (), required=False), agree("marketing"), p_sample)
line("2 optional box, model basis NONE, code key marketing", mk("Subscribe to our newsletter", CB, (), required=False),
     FakeAsk(lambda v: say(None, "none", "", False, "optional", klass="marketing"), place="NONE"), p_sample)
line("2b optional privacy box, model NONE, class ordinary", mk("I agree to the Privacy Policy", CB, (), required=False),
     FakeAsk(lambda v: say(None, "none", "", False, "optional", klass="ordinary"), place="NONE"), p_sample)
line("2c optional box, model NONE, no class", mk("Subscribe to our newsletter", CB, (), required=False),
     FakeAsk(lambda v: say(None, "none", "", False, "optional", klass=NO_CLASS), place="NONE"), p_sample)
line("3 required box, model silent (no reply)", mk("I agree to the Privacy Policy", CB, (), required=True), FakeAsk(), p_sample)
line("4 required certify box, model refuses", mk("I certify that the information provided is true and complete", CB, (), required=True), agree("certification"), p_false)
line("4b certify box, model ticks (model source)", mk("I certify that the information provided is true and complete", CB, (), required=True), agree("certification"), p_sample)
line("4c acknowledgement of terms, model ticks", mk("I accept the terms of use", CB, (), required=True), agree("acknowledgement"), p_sample)
line("5 internal sharing (share_end)", mk("I agree that my details may be shared with the hiring team", CB, (), required=False), agree("consent_privacy"), p_sample)
line("5b third-party sharing yes/no (share_end)", mk("I agree that my details may be shared with other companies", YNQ, YN, required=True), yes("consent_privacy"), p_sample)
line("6 unkeyed marketing box, model says marketing", mk("I agree to receive emails from Example Employer", CB, (), required=False), agree("marketing"), p_sample)
line("6b unkeyed marketing box, model says ordinary", mk("I agree to receive emails from Example Employer", CB, (), required=False), agree("ordinary"), p_sample)
line("7 pre-ticked marketing (site default), model keep", mk("Subscribe to our newsletter", CB, (), required=False, shown="true", origin=ValueOrigin.SITE_DEFAULT),
     FakeAsk(lambda v: say(None, "keep", "", False, "site", klass="marketing"), place="NONE"), p_sample)
print("-- declaration paths (sample profile: none applies)")
line("8 model No, class declaration (first pass)", mk("Have you ever been convicted of a criminal offence?"), FakeAsk(lambda v: lie("No", "declaration:criminal_record"), pick=pick_faithful("No", "No"), place="NONE"), p_sample)
line("8b model Yes -> vote -> truth written", mk("Have you ever been convicted of a criminal offence?"), FakeAsk(lambda v: lie("Yes", "declaration:criminal_record"), pick=pick_faithful("No", "No"), place="NONE"), p_sample)
line("8c model silent -> protective end / last resort", mk("Have you ever been convicted of a criminal offence?"), FakeAsk(), p_sample)
line("8d unread wording, model ordinary (director of any co.)", mk("Are you a director of any company?"), FakeAsk(lambda v: lie("No", "ordinary"), place="NONE"), p_sample)
line("8e optional declaration, model NONE", mk("Are you a politically exposed person?", required=False), FakeAsk(lambda v: say(None, "none", "", False, "x", klass="declaration:pep"), place="NONE"), p_sample)
line("8f NDA willingness (ordinary, D9)", mk("Are you willing to sign a non-disclosure agreement?"), FakeAsk(lambda v: lie("Yes", "ordinary"), place="NONE"), p_sample)
line("8g pre-selected adverse Yes, required, vote fails", mk("Have you ever been convicted of a criminal offence?", shown="Yes", origin=ValueOrigin.SITE_DEFAULT), FakeAsk(pick=pick_by("", "")), p_sample)
