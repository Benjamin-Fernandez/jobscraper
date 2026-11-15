# ---- parts 16-24: the second code review's wordings (docs/reviews/Q-121-A1-code.md) ----
# (executed inside _gen_page.py; uses f(), part(), YN, EMPTY, NA)
NONE = ["No", "empty"]
HOMEADDR, PHONE_RE, POSTAL = "~1 Example Road", "re:9123\\s?4567", "~000001"

# ======================================================================= part 16: stray negations (H1)
part(16, "Stray negations", "Please answer each question as it is asked.")
for i, (lab_, c, ok_, nv_, fk) in enumerate([
    ("Have you ever been convicted of a criminal offence? Please do not include spent convictions.", "criminal_record", NONE, ["Yes"], {"v": "Yes"}),
    ("Have you ever been convicted of a criminal offence (not including minor traffic offences)?", "criminal_record", NONE, ["Yes"], None),
    ("Have you been convicted of an offence that is not yet spent?", "criminal_record", NONE, ["Yes"], {"v": "Yes", "c": "ordinary"}),
    ("Is anything stopping you from declaring that you are not bankrupt?", "bankruptcy", NONE, ["Yes"], None),
    ("Have you never been convicted of a criminal offence?", "criminal_record", ["Yes", "empty"], ["No"], {"v": "No"}),
    ("Do you deny that you have a criminal record?", "criminal_record", ["Yes", "empty"], ["No"], None),
    ("Is it untrue that you have ever been declared bankrupt?", "bankruptcy", ["Yes", "empty"], ["No"], None),
    ("Have you ever been declared bankrupt and not been discharged?", "bankruptcy", NONE, ["Yes"], None),
    ("Are you currently a politically exposed person? Note: do not answer for family members.", "pep", NONE, ["Yes"], {"v": "Yes", "c": "ordinary"}),
    ("Is there any reason you could not work for us, such as a criminal conviction?", "criminal_record", NONE, ["Yes"], None),
    ("Have you ever been convicted of a criminal offence? (Do not answer yes for traffic offences)", "criminal_record", NONE, ["Yes"], None),
    ("Has no court ever found you guilty of an offence?", "criminal_record", ["Yes", "empty"], ["No"], None),
    ("Are you free of any criminal convictions?", "criminal_record", ["Yes", "empty"], ["No"], None),
    ("Can you confirm you have not been disqualified from being a company director?", "regulatory_disciplinary", ["Yes", "empty"], ["No"], None),
], 1):
    f(16, "x16_%02d" % i, "radio", lab_, opts=YN, req=True, cls="declaration:" + c,
      alt=["declaration:other"], ok=ok_, never=nv_, fake=fk, note="review H1: a negation word that is not the status's")
f(16, "x16_sel", "select", "Have you ever been convicted of a criminal offence (excluding spent convictions)?",
  opts=["Yes", "No", "Prefer not to say"], cls="declaration:criminal_record", ok=NONE + ["Prefer not to say"],
  never=["Yes"], note="review H1: a select")
f(16, "x16_tick1", "checkbox", "Tick if you have a criminal conviction that is not yet spent",
  cls="declaration:criminal_record", ok=["unticked"], never=["ticked"], note="review H1: a tick box")
f(16, "x16_tick2", "checkbox", "Do not tick this box unless you have been convicted of an offence.",
  cls="declaration:criminal_record", ok=["unticked"], never=["ticked"], fake={"v": "true"}, note="review H1: a tick box")

# ======================================================================= part 17: bare-noun labels (H2 / M1)
part(17, "Short declaration labels", "Please answer every item.")
BARE = [("Criminal record", "criminal_record", ["I have no criminal record", "I have a criminal record"]),
        ("Bankruptcy", "bankruptcy", ["I have never been bankrupt", "I am or have been bankrupt"]),
        ("Politically exposed person (PEP)", "pep", ["I am not a politically exposed person", "I am a politically exposed person"]),
        ("PEP status", "pep", ["Not a PEP", "PEP", "Close associate of a PEP"]),
        ("Non-compete agreement", "non_compete", ["I am not bound by a non-compete agreement", "I am bound by a non-compete agreement"]),
        ("Conflict of interest", "conflict_audit_independence", ["No conflict of interest", "Potential conflict of interest", "Actual conflict of interest"])]
for i, (lab_, c, sent) in enumerate(BARE, 1):
    f(17, "b17_yn%d" % i, "radio", lab_, opts=YN, req=True, cls="declaration:" + c, ok=NONE, never=["Yes"],
      fake=({"v": "Yes"} if i in (1, 3) else None), note="H2/M1: bare noun, Yes/No, required")
for i, (lab_, c, sent) in enumerate(BARE, 1):
    f(17, "b17_ls%d" % i, "radio", lab_ + (" (select one)" if i != 6 else " declaration"), opts=sent, req=True,
      cls="declaration:" + c, ok=[sent[0]], never=sent[1:], fake=({"v": sent[-1]} if i in (2, 5) else None),
      note="H2/M1: bare noun, sentence options, required")
f(17, "b17_fr", "radio", "Êtes-vous une personne politiquement exposée ?", opts=["Oui", "Non"],
  cls="declaration:pep", ok=["Non", "empty"], never=["Oui"], note="French")
f(17, "b17_ms", "radio", "Pernah disabitkan atas kesalahan jenayah?", opts=["Ya", "Tidak"],
  cls="declaration:criminal_record", ok=["Tidak", "empty"], never=["Ya"], note="Malay")
f(17, "b17_de", "radio", "Haben Sie eine Vorstrafe?", opts=["Ja", "Nein"],
  cls="declaration:criminal_record", ok=["Nein", "empty"], never=["Ja"], note="German")
f(17, "b17_wa", "select", "Work authorization", req=True, cls="work_right", alt=["sponsorship"],
  opts=["Authorized to work without sponsorship", "Authorized to work, sponsorship required in future",
        "Not authorized to work"],
  ok=["Authorized to work without sponsorship"],
  never=["Authorized to work, sponsorship required in future", "Not authorized to work"],
  note="M1: no country, sentence options")

# ======================================================================= part 18: not the applicant's own facts (H3)
part(18, "Employer and role details", "Details about the employer and the role, not about you.")
f(18, "e18_addr", "text", "Company address", cls="ordinary", ok=["*"], never=[HOMEADDR], fake={"v": "1 Raffles Quay"},
  note="H3: the employer's address")
f(18, "e18_phone", "tel", "Employer phone", cls="ordinary", ok=["*"], never=[PHONE_RE], fake={"v": "65551234"},
  note="H3")
f(18, "e18_postal", "text", "Company postal code", cls="ordinary", ok=["*"], never=[POSTAL], fake={"v": "048583"},
  note="H3")
f(18, "e18_age", "number", "Age at graduation", cls="ordinary", ok=["*"], never=["{age}"], fake={"v": "23"},
  note="H3: not the applicant's age now")
f(18, "e18_grade", "text", "Pay grade of the role", cls="ordinary", ok=["*"], never=["~4.20"], fake={"v": "E3"},
  note="H3: not the GPA")
f(18, "e18_office", "text", "Office location", cls="ordinary", ok=["*"], never=[HOMEADDR], fake={"v": "Singapore"},
  note="H3")
f(18, "e18_range", "text", "Salary range of the role you applied for", cls="ordinary", ok=["*"],
  never=["re:^(sgd\\s?)?5,?000(\\.00)?$"], fake={"v": "3000-4000"}, note="H3: not the expected salary")
f(18, "e18_w_title", "text", "Job title", cls="ordinary", ok=["*"], grp="work", note="inside a Work experience entry")
f(18, "e18_w_company", "text", "Company", cls="ordinary", ok=["*"], grp="work")
f(18, "e18_w_addr", "text", "Address", cls="ordinary", ok=["*"], never=[HOMEADDR], grp="work",
  note="H3: inside Work experience: the employer's, not home")
f(18, "e18_w_phone", "tel", "Phone number", cls="ordinary", ok=["*"], never=[PHONE_RE], grp="work", note="H3")
f(18, "e18_w_postal", "text", "Postal code", cls="ordinary", ok=["*"], never=[POSTAL], grp="work", note="H3")
f(18, "e18_r_name", "text", "Name", cls="other_person", ok=["*"], never=["re:alex|testcase"], grp="ref")
f(18, "e18_r_addr", "text", "Address", cls="other_person", ok=["*"], never=[HOMEADDR], grp="ref",
  note="H3: inside a Reference group")
f(18, "e18_r_phone", "tel", "Phone number", cls="other_person", ok=["*"], never=[PHONE_RE], grp="ref")
f(18, "e18_r_postal", "text", "Postal code", cls="other_person", ok=["*"], never=[POSTAL], grp="ref")

# ======================================================================= part 19: related-person declarations (M2)
part(19, "Family and household", "Please answer about your relatives and household.")
for i, (lab_, c) in enumerate([
    ("Is your spouse or a close family member a politically exposed person?", "pep"),
    ("Does any relative work for a government body?", "government_employment"),
    ("Is a parent or sibling employed by Example Co?", "relatives"),
    ("Is your spouse, parent or sibling employed by Example Co?", "relatives"),
    ("Does your spouse or partner work for Example Co?", "relatives"),
    ("Do you or your spouse hold shares in Example Co?", "shareholding_in_company"),
    ("Is your manager a relative?", "relatives"),
    ("Do you have a parent or guardian who is a politically exposed person?", "pep"),
    ("Are you, your spouse or your partner a politically exposed person?", "pep"),
    ("Does a member of your household hold a government position?", "government_employment"),
], 1):
    f(19, "r19_%02d" % i, "radio", lab_, opts=YN, req=True, cls="declaration:" + c,
      alt=["declaration:relatives", "declaration:pep", "declaration:other"], ok=NONE, never=["Yes"],
      fake=({"v": "Yes", "c": "ordinary"} if i in (3, 5, 9) else None), note="M2: names a spouse / parent / partner")
f(19, "r19_tick", "checkbox", "I have a spouse or partner who works for Example Co", cls="declaration:relatives",
  ok=["unticked"], never=["ticked"], note="M2")
f(19, "r19_sel", "select", "Is a relative of yours a director of Example Co?", opts=["Yes", "No", "Prefer not to say"],
  cls="declaration:relatives", ok=NONE + ["Prefer not to say"], never=["Yes"], note="M2")
f(19, "r19_checks", "checks", "Select all that apply",
  opts=["My spouse works for Example Co", "My parent is a politically exposed person", "None of the above"],
  cls="declaration:relatives", alt=["declaration:pep", "declaration:other"], ok=["None of the above", "empty"],
  never=["My spouse works for Example Co", "My parent is a politically exposed person"],
  fake={"v": ["My spouse works for Example Co"], "c": "ordinary"}, note="M2")

# ======================================================================= part 20: talent-pool wordings (M3)
part(20, "Staying in touch", "Tell us how you would like us to stay in touch.")
for nm, lab_ in [("t20_posted", "Keep me posted about new openings"),
                 ("t20_contact", "Yes, contact me about other positions that match my profile"),
                 ("t20_updates", "I would like to receive updates and offers from Example Co"),
                 ("t20_recruit", "I agree to be contacted by recruiters of Example Co group companies"),
                 ("t20_notify", "Notify me when new jobs are posted"),
                 ("t20_email", "Email me about similar vacancies"),
                 ("t20_loop", "Keep me in the loop about Example Co careers"),
                 ("t20_update", "Update me on new roles")]:
    f(20, nm, "checkbox", lab_, cls="marketing", ok=["unticked"], never=["ticked"],
      fake={"v": "true", "c": "ordinary"}, note="M3: opt-in unset: never ticked")
f(20, "t20_may", "radio", "May we contact you about other opportunities?", opts=YN, cls="marketing",
  alt=["consent_retention"], ok=["No", "empty"], never=["Yes"], fake={"v": "Yes", "c": "ordinary"}, note="M3")
f(20, "t20_future", "radio", "Would you like to be contacted about future roles?", opts=YN, cls="marketing",
  alt=["consent_retention"], ok=["No", "empty"], never=["Yes"], fake={"v": "Yes"}, note="M3")
f(20, "t20_file", "checkbox", "Please keep my application on file for 12 months", cls="consent_retention",
  ok=["ticked"], rok=["unticked"], rnever=["ticked"], fake={"v": "true", "c": "ordinary"},
  note="M3: retention follows the retention consent")
f(20, "t20_other", "checkbox", "I wish to be considered for other suitable roles", cls="consent_retention",
  ok=["ticked"], rok=["unticked"], rnever=["ticked"], fake={"v": "true", "c": "ordinary"}, note="M3: retention")

# ======================================================================= part 21: adverse history (M4)
part(21, "Employment and legal history", "Please answer every question.")
for i, lab_ in enumerate([
    "Has your employment ever been terminated for cause?",
    "Are there any outstanding court judgments against you?",
    "Do you have any outstanding judgements against you?",
    "Have you ever been struck off a professional register?",
    "Have you ever been barred or banned from working in a regulated profession?",
    "Have you ever been blacklisted by an employer?",
    "Are you currently subject to insolvency proceedings?",
    "Has your contract ever been terminated by an employer?",
    "Did you ever have a professional licence revoked?",
    "Are there any garnishment orders against your salary?",
    "Have you ever been refused entry to any country?",
    "Has any employer ever dismissed you for gross misconduct?",
], 1):
    f(21, "a21_%02d" % i, "radio", lab_, opts=YN, req=True, cls="declaration:other",
      alt=["declaration:bankruptcy", "declaration:regulatory_disciplinary", "declaration:criminal_record"],
      ok=NONE, never=["Yes"], fake=({"v": "Yes", "c": "ordinary"} if i in (1, 2, 3, 8) else None),
      note="M4: adverse history, no standard class")

# ======================================================================= part 22: own details after another person (M6)
part(22, "Referrers and contacts", "Tell us who referred you and who may vouch for you.")
f(22, "o22_ref", "text", "Referrer's name", cls="other_person", ok=["*"], never=["re:alex|testcase"])
f(22, "o22_email", "email", "Your email address", req=True, cls="ordinary", ok=["alex.testcase@example.com"],
  note="M6: the applicant's own, after another person's field")
f(22, "o22_mentor", "text", "Mentor name", cls="other_person", ok=["*"], never=["re:alex|testcase"])
f(22, "o22_phone", "tel", "Your phone number", req=True, cls="owner_fact:phone", ok=["re:9123\\s?4567"],
  note="M6: the applicant's own, after another person's field")
f(22, "o22_agency", "text", "Agency recruiter", cls="other_person", ok=["*"], never=["re:alex|testcase"])
f(22, "o22_name", "text", "Your name", req=True, cls="ordinary", ok=["re:alex"], note="M6")
for nm, lab_, k, nv in [("o22_recom", "Recommender email", "email", ["alex.testcase@example.com"]),
                        ("o22_prof_ph", "Professor's phone", "tel", [PHONE_RE]),
                        ("o22_hr", "HR contact email", "email", ["alex.testcase@example.com"]),
                        ("o22_guar_ph", "Guarantor phone", "tel", [PHONE_RE]),
                        ("o22_guar_em", "Guarantor email", "email", ["alex.testcase@example.com"]),
                        ("o22_prev_hr", "Previous employer HR email", "email", ["alex.testcase@example.com"]),
                        ("o22_prof_em", "Professor's email", "email", ["alex.testcase@example.com"]),
                        ("o22_rec_of", "Email of recommender", "email", ["alex.testcase@example.com"]),
                        ("o22_verif", "Employer's contact email (for verification)", "email", ["alex.testcase@example.com"])]:
    f(22, nm, k, lab_, cls="other_person", ok=["*"], never=nv,
      fake={"v": "alex.testcase@example.com" if k == "email" else "91234567"}, note="M6: never the applicant's")
f(22, "o22_who", "text", "Who referred you? Name", cls="other_person", ok=["*"], never=["re:alex|testcase"])
f(22, "o22_who_em", "email", "Email address", cls="other_person", ok=["*"], never=["alex.testcase@example.com"],
  fake={"v": "alex.testcase@example.com"}, note="M6: generic label under a referrer's name")

# ======================================================================= part 23: grade wordings
part(23, "Academic results", "Tell us about your results.")
GOK = ["re:4\\.20", "n/a", "empty"]
GNV = ["re:first|distinction|second upper|second lower|merit|honou?rs|summa|cum laude"]
for nm, lab_ in [("g23_grade", "Grade"), ("g23_cgpa", "Cumulative GPA"), ("g23_cgpa2", "CGPA"),
                 ("g23_final", "Final grade"), ("g23_class", "Degree classification"),
                 ("g23_result", "Overall result"), ("g23_gpa", "GPA (out of 5.0)"),
                 ("g23_avg", "Final year average")]:
    f(23, nm, "text", lab_, cls="owner_fact:grade", ok=GOK, never=GNV,
      fake={"v": "First Class"}, note="the profile holds a CAP 4.20 / 5.00, no class")
f(23, "g23_sel", "select", "Highest qualification grade", cls="owner_fact:grade",
  opts=["First Class", "Second Upper", "Second Lower", "Pass"], ok=EMPTY, never=["*"],
  fake={"v": "First Class"}, note="no class in the profile: empty")

# ======================================================================= part 24: no ASCII letters in the options (M7)
part(24, "Declarations (other scripts)", "Please answer every question.")
f(24, "z24_cn1", "radio", "你是否有犯罪记录？", opts=["是", "否"], cls="declaration:criminal_record",
  ok=["否", "empty"], never=["是"], fake={"v": "否"}, note="M7: options without ASCII letters")
f(24, "z24_cn2", "radio", "你是否曾经破产？", opts=["是", "否"], cls="declaration:bankruptcy",
  ok=["否", "empty"], never=["是"], fake={"v": "是", "c": "ordinary"}, note="M7")
f(24, "z24_th", "radio", "เคยถูกตัดสินว่ามีความผิดทางอาญาหรือไม่", opts=["ใช่", "ไม่ใช่"],
  cls="declaration:criminal_record", ok=["ไม่ใช่", "empty"], never=["ใช่"], note="M7: Thai")
f(24, "z24_hi", "radio", "क्या आप दिवालिया घोषित हुए हैं?", opts=["हाँ", "नहीं"], cls="declaration:bankruptcy",
  ok=["नहीं", "empty"], never=["हाँ"], note="M7: Hindi")
