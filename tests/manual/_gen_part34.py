# Part 34 of tests/fixtures/apply/always_rehearsal.html (exec'd by _gen_page.py in its namespace: part, f, YN are defined there).
# ======================================================================= part 34: the closure review's H1 / H2 / G rows (D-222 S1-S3, D-223 G, D-224)
# Rows for the fixes of docs/reviews/Q-121-closure.md (the engineer's G round): H1 a consent box or question that merely names a
# status is decided by the consents (sample: privacy true, retention true, talent-pool FALSE), never by the nationality; H2 a
# question about another person is never answered from the applicant's nationality; National Service follows `ns_status`
# (completed); D-224 5a third-party sharing is never ticked; plain status rows the earlier parts lack; G3 wordings (by birth, since
# 2020) have no code truth: Yes or empty, never No. Notes carry the prefix `G-`. Under --fake the meaning call is unusable, so a
# row that needs a vote ends EMPTY (counted as over-protection where the expected value is not empty).
part(34, "Consents, other people and status wordings", "A few questions that mention citizenship or sharing.")
f(34, "h1_priv_box", "checkbox", "I consent to the collection and use of my personal data as a Singapore citizen or PR under the PDPA",
  cls="consent_privacy", ok=["ticked"], never=[], fake={"v": "true"}, cfm="yes",
  note="G-H1: the privacy box follows the sample's privacy consent (true): ticked, never decided by the nationality")
f(34, "h1_mkt_box", "checkbox", "I am a Singapore citizen and agree to receive job alerts", cls="marketing",
  ok=["unticked"], never=["ticked"], fake={"v": "true"}, cfm="yes",
  note="G-H1: marketing: the talent-pool opt-in is false: never ticked because the owner is a citizen")
f(34, "h1_ret_box", "checkbox", "Keep my application on file; I am a Singapore citizen", cls="consent_retention", alt=["marketing"],
  ok=["unticked"], never=["ticked"], fake={"v": "true"}, cfm="yes",
  note="G-H1: a keep-on-file box with a residue needs both consents (the pool is false): never ticked")
f(34, "h1_priv_rad", "radio", "Do you consent to the processing of your personal data as a Singapore citizen?", opts=YN, req=True,
  cls="consent_privacy", ok=["Yes", "empty"], never=["No"], fake={"v": "No"}, cfm="Yes",
  note="G-H1: the radio follows the privacy consent (true): Yes or empty, never No")
f(34, "h1_mkt_rad", "radio", "As a Singapore citizen, do you agree to be contacted about other roles?", opts=YN, cls="marketing",
  ok=["No", "empty"], never=["Yes"], fake={"v": "Yes"}, cfm="Yes",
  note="G-H1: marketing, pool false: never Yes because the owner is a citizen")
f(34, "h2_spouse", "radio", "Is your spouse a Singapore citizen?", opts=YN, cls="declaration:other", alt=["other_person"],
  ok=["No", "empty"], never=["Yes"], fake={"v": "Yes"}, cfm="Yes",
  note="G-H2: another person's status is never the applicant's nationality (Yes would be)")
f(34, "h2_spouse_pr", "radio", "Is your spouse a Singapore PR?", opts=YN, cls="declaration:other", alt=["other_person"],
  ok=["No", "empty"], never=["Yes"], fake={"v": "Yes"}, cfm="Yes",
  note="G-H2: as above, the residency fact this time (the owner is a citizen, not a PR): never Yes")
f(34, "h2_ns", "radio", "Have you completed Singapore National Service?", opts=YN, req=True, cls="ordinary", ok=["Yes"], never=["No"],
  fake={"v": "No"}, note="G-H2 / D-224 5b: ns_status is completed: Yes (the National Service key wins over any status reading)")
f(34, "sh_box1", "checkbox", "Keep my CV on file and let recruiters from partner firms see it", cls="consent_privacy",
  alt=["consent_retention", "marketing"], ok=["unticked"], never=["ticked"], fake={"v": "true"}, cfm="yes",
  note="G-5a: sharing with a third party is its own consent: no profile consent covers it: never ticked")
f(34, "sh_box2", "checkbox", "I agree that my details may be shared with our trusted partners", cls="consent_privacy",
  alt=["marketing"], ok=["unticked"], never=["ticked"], fake={"v": "true"}, cfm="yes", note="G-5a: as above")
f(34, "sh_box3", "checkbox", "Consider me for future roles and share my details with hiring managers across the group",
  cls="consent_privacy", alt=["consent_retention", "marketing"], ok=["unticked"], never=["ticked"], fake={"v": "true"}, cfm="yes",
  note="G-5a: as above")
f(34, "sh_rad", "radio", "May we share your CV with our clients?", opts=YN, cls="consent_privacy", alt=["marketing"],
  ok=["No", "empty"], never=["Yes"], fake={"v": "Yes"}, cfm="Yes", note="G-5a: a yes/no on sharing with a third party is No")
f(34, "pl_passport", "radio", "Do you hold a Singapore passport?", opts=YN, req=True, cls="work_right", ok=["Yes"], never=["No"],
  fake={"v": "Yes"}, note="D-222 S3: a canonical status frame: the profile fact, no further call")
f(34, "pl_box", "checkbox", "I am a Singapore citizen", cls="work_right", ok=["ticked"], never=[], fake={"v": "true"}, cfm="yes",
  note="D-224 1: a tick box whose whole label is a plain status statement: ticked for the citizen (a vote decides it: "
       "unticked under --fake is over-protection)")
f(34, "g3_birth", "radio", "Are you a Singapore citizen by birth?", opts=YN, cls="work_right", ok=["Yes", "empty"], never=["No"],
  fake={"v": "Yes"}, cfm="Yes", note="G-G3: no code truth for 'by birth': the model plus one confirmation, else empty; never No")
f(34, "g3_since", "radio", "Have you been a Singapore citizen since 2020?", opts=YN, cls="work_right", ok=["Yes", "empty"],
  never=["No"], fake={"v": "Yes"}, cfm="Yes", note="G-G3: as above")

# D-226 (Q-121 G2): a status question that names NO country is about the job's country (here Singapore), and only where the status
# word is the predicate; the same words in another sense are no status question. Notes carry the prefix `G2-`.
f(34, "g2_cit_pr", "radio", "Are you a citizen or permanent resident?", opts=YN, req=True, cls="work_right", ok=["Yes"], never=["No"],
  fake={"v": "Yes"}, note="G2-D226: a no-country status question is about the job's country: answered Yes from the profile, a must-answer row")
f(34, "g2_foreigner", "radio", "Are you a foreigner?", opts=YN, req=True, cls="work_right", ok=["No", "empty"], never=["Yes"],
  fake={"v": "Yes"}, cfm="No", note="G2-D226: a foreigner is not a citizen of the job's country: the citizen is No; a model Yes is overruled by one confirmation")
f(34, "g2_pr_exp", "radio", "Do you have PR experience?", opts=YN, cls="ordinary", ok=["*"], never=[], fake={"v": "No"},
  note="G2-D226 guard: PR here is public relations, no status question: any ordinary answer; never from the residency fact "
       "(the source is pinned in tests/test_always_a1_final_r10.py)")
f(34, "g2_pr_prof", "radio", "Are you a PR professional?", opts=YN, cls="ordinary", ok=["*"], never=[], fake={"v": "No"},
  note="G2-D226 guard: as above (a tail that is no clause word makes it no status question)")
