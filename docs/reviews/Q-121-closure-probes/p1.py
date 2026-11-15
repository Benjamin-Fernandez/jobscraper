import sys
sys.path.insert(0, "docs/reviews/Q-121-closure-probes")
from h import *  # noqa
c = ctx()
labels = """Are you a Singapore citizen?
Is your spouse a Singapore citizen?
Are your parents Singapore PRs?
Is your referee a US citizen?
Does the role require a Singapore citizen?
Singapore citizens only: are you applying for this role?
Have you ever renounced Singapore citizenship?
Are you a citizen of a country other than Singapore?
Do you hold dual citizenship?
Are you a Singapore citizen or a citizen of any ASEAN state?
Were you a Singapore PR before becoming a citizen?
Are you in the process of applying for Singapore PR?
Do you intend to apply for Singapore citizenship?
Are you a Singapore PR?
Are you a Singapore Permanent Resident?
Are you a Singaporean?
Are you a Malaysian citizen?
Are you a citizen of Malaysia?
Are you a US citizen?
Are you a citizen of the United States?
Do you hold a Singapore passport?
Do you hold a valid Singapore work pass?
Do you hold an Employment Pass?
Do you hold a Singapore Employment Pass?
Do you hold an S Pass?
Do you hold a UK visa?
Do you hold a valid US work visa?
Are you a Singapore citizen or PR?
Are you a Singapore citizen and a PR?
Is your spouse a Singapore PR?
Is your father a Singaporean?
Is your mother a Singapore citizen or PR?
Do you have a family member who is a Singapore citizen?
Do you have a relative who works for us and is a Singapore citizen?
Are you a former Singapore citizen?
Are you not a Singapore citizen?
Are you a non-Singapore citizen?
Are you a Singapore citizen by birth?
Are you a Singapore citizen by registration?
Are you a naturalised Singapore citizen?
Are you a Singapore citizen or hold a valid work pass?
Have you held Singapore PR status for more than 2 years?
Are you a Singapore PR holder?
Are you a Singapore citizen who has completed National Service?
Are you a Singapore citizen currently residing overseas?
Are you a Singapore citizen working in Malaysia?
Will you be a Singapore citizen by the start date?
Would you like to become a Singapore citizen?
Is your emergency contact a Singapore citizen?
Is the person you referred a Singapore citizen?
Your Singapore citizenship status
Singapore citizen
Singapore Citizen?
Singapore PR
Citizenship
Nationality
Are you a citizen?
Are you a permanent resident?
Are you a Singapore resident?
Are you a resident of Singapore?
Do you reside in Singapore?
Are you a tax resident of Singapore?
Are you a non-resident of Singapore?
Do you hold Singapore citizenship?
Do you hold Singapore citizenship or PR?
Do you hold Singapore PR?
Do you hold dual Singapore and Malaysian citizenship?
Are you a Singapore national?
Are you a Singapore citizen? (Y/N)
Are you a Singapore citizen?*
Please confirm: are you a Singapore citizen?
Are you a Singapore citizen? Please select Yes or No.
Are you a Singapore citizen? If yes, please provide your NRIC number.
Are you a Singapore citizen? Do you have a valid passport?
Are you a Singapore citizen? Are you eligible for the Singapore government scholarship?
Singapore Citizens and PRs only: are you eligible?
Are you a Singapore citizen or Singapore PR, and are you available full time?
Do you have a Singapore NRIC?
NRIC / FIN
Passport number
Passport
Passport nationality
Do you hold a valid work pass?
Do you require a work pass?
Do you hold a valid Employment Pass?
FIN number
Employment Pass expiry date
What type of work pass do you hold?
Are you a Singapore citizen, PR or foreigner?""".splitlines()
for lab in labels:
    for ft, opts in (("RADIO", YN), ("CHECKBOX", ())):
        pf = mk(lab, ft, opts)
        try:
            sq = AL.status_question(pf, "SG")
        except Exception as e:
            print("ERR", lab, repr(e))
            continue
        if sq is None:
            r = "-"
        else:
            tr = AL.status_truth(sq, c)
            r = f"country={sq.country!r} kinds={sorted(sq.kinds)} join={sq.join!r} passes={sq.passes} truth={tr[0]} src={tr[1].split(':')[-1]} k={tr[2]}"
        key = AL.code_key_full(pf, c)
        print(f"{ft[:3]} | {lab[:78]:78} | {r} | key={key.klass.value if key.klass else None}:{key.which}")
