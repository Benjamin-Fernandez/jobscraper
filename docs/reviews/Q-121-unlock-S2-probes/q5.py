"""Q5: realistic REQUIRED privacy / data-processing consent wordings, the sample profile (privacy + retention true, talent false),
a model that agrees under class consent_privacy. Prints TICKED or STOP for the required box, and which key fired.
Second part: the same wordings as a REQUIRED yes/no question (a third-party sharing question is answered No, D-225)."""
import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S2-probes")
from g import *  # noqa

Q = [
 "I have read and agree to the Example Employer Candidate Privacy Notice",
 "I consent to Example Employer collecting, using and storing my personal data for the purpose of processing my application",
 "I acknowledge that my personal data will be processed by Example Employer and its service providers in accordance with the Privacy Policy",
 "I understand that my information will be shared with Example Employer's affiliates and subsidiaries for recruitment purposes",
 "I consent to the transfer of my personal data to Example Employer group companies located outside my country of residence",
 "I agree that Example Employer may disclose my personal data to third parties who provide services to it",
 "By submitting this application I consent to my data being processed by Example Employer and its recruitment partners",
 "I agree to the collection, use and disclosure of my personal data by Example Employer and its related corporations as set out in the PDPA notice",
 "I authorise Example Employer to share my application with the hiring manager and interview panel",
 "I consent to Example Employer's applicant tracking provider processing my personal data on its behalf",
 "I agree that my personal data may be processed by vendors engaged by Example Employer to support recruitment",
 "I understand my data will be stored on servers operated by our cloud service provider",
 "I consent to my personal information being shared with Example Employer's recruitment agencies",
 "I agree that my CV may be forwarded to relevant hiring teams within Example Employer",
 "I consent to Example Employer sharing my data with background screening providers for employment verification",
 "I consent to my personal data being shared with other members of the Example Employer group for the purpose of considering me for roles",
 "I have read the privacy statement and consent to my data being processed by Example Employer and its third-party processors",
 "I agree to the Terms of Use and acknowledge the Privacy Policy",
 "I give my consent to Example Employer to process my personal data as described in the privacy policy, including sharing with its parent company",
 "I confirm I have read the Data Protection Notice and agree that my details are shared with the group HR department",
 "I agree that Example Employer may share my details with its partners who help with recruitment",
 "I agree that my application data may be shared with our service providers and professional advisers",
 "I consent to the processing of my sensitive personal data by Example Employer and companies acting on its instructions",
 "I agree that my information can be passed to our recruitment process outsourcing provider",
 "I understand that Example Employer may share my personal data with regulators and government authorities where required by law",
 "I consent to the use of my personal data by Example Employer and its sister companies for recruitment purposes",
 "I accept that my application and personal details will be reviewed by Example Employer's HR team and relevant business units",
 "I consent to Example Employer disclosing my personal data to its clients for the purpose of placing me",
 "I agree for my data to be shared with companies within the Example Employer network",
 "I agree to my details being processed by Example Employer and external service providers on its behalf",
]
p = prof("sample")
stops = 0
rows = []
for lab in Q:
    c = ctx(p)
    f = mk(lab, "CHECKBOX", (), required=True)
    k = AL.code_key_full(f, c)
    ask = FakeAsk(lambda v: lie("true", "consent_privacy"), pick=lambda q, w, o: "yes", place="NONE")
    r1 = attempt(mk(lab, "CHECKBOX", (), required=True), ask, p)
    ask = FakeAsk(lambda v: lie("Yes", "consent_privacy"), pick=lambda q, w, o: "Yes", place="NONE")
    r2 = attempt(mk(lab, "RADIO", YN, required=True), ask, p)
    kind = "share" if k.share else ("internal" if k.internal else (k.klass.value if k.klass else "none"))
    stops += is_stop(r1)
    rows.append((lab, kind, out_of(r1), out_of(r2)))
    print(f"{'STOP' if is_stop(r1) else 'tick'} | {kind:9} | yn={out_of(r2):8} | {lab[:110]}")
print("box stops:", stops, "of", len(Q))
