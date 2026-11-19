"""The consent wordings of the S2 review: (label, needs, neg, kind).
needs: keys of the owner's consents that must ALL be true for the box to be agreed ("privacy" "retention" "talent" "cert"),
       "NEVER" (third-party sharing: truth False in every profile), None (no owner truth: reported, not judged).
neg: an opt-out wording (ticking / Yes means the applicant REFUSES).
All employers are made up (Example Employer is the sample profile's; Northwind, Example Co)."""
P, R, M, C = "privacy", "retention", "talent", "cert"
W = [
    # ---- privacy
    ("I consent to the collection, use and disclosure of my personal data as described in the Privacy Notice", (P,), False),
    ("I agree to the processing of my personal data for recruitment purposes", (P,), False),
    ("I have read and agree to the Privacy Policy", (P,), False),
    ("I acknowledge that my data will be processed in accordance with the Example Employer privacy policy", (P,), False),
    ("Do you consent to Example Employer processing your personal information in connection with your application?", (P,), False),
    ("I understand and accept the Data Protection Notice", (P,), False),
    ("By submitting this form you agree to our Terms of Use and Privacy Policy", (P,), False),
    ("I authorise Northwind to collect, use and disclose my personal data for employment purposes, in accordance with the PDPA", (P,), False),
    ("I consent to my personal data being transferred outside Singapore for processing", (P,), False),
    ("I agree to Example Co's use of my information as set out in the Candidate Privacy Policy, including transfer to servers in the EU", (P,), False),
    ("I have read and understood the privacy policy", (P,), False),
    ("I agree that my details may be shared with the hiring team and HR", (P,), False),
    ("I consent to my data being processed by service providers acting on behalf of Example Employer", (P,), False),
    ("I understand that our applicant tracking provider will process my personal data on behalf of Example Employer", (P,), False),
    # ---- retention
    ("Keep my application on file for future opportunities", (R,), False),
    ("I agree that Example Employer may retain my CV for up to 24 months", (R,), False),
    ("Consider me for other roles at Example Employer", (R,), False),
    ("Allow us to store your details for future vacancies", (R,), False),
    ("Yes, keep my data on file for future roles", (R,), False),
    ("I would like Example Employer to keep my application active and contact me about relevant roles", (R, M), False),
    ("I'm happy for you to keep my details and let me know about future roles", (R, M), False),
    # ---- marketing / talent pool
    ("I agree to receive job alerts", (M,), False),
    ("Join our talent community", (M,), False),
    ("Subscribe to our newsletter", (M,), False),
    ("I agree to be contacted about future job opportunities by email", (M,), False),
    ("I consent to receive marketing communications", (M,), False),
    ("Keep me informed about events and webinars", (M,), False),
    ("I would like to receive tailored job recommendations", (M,), False),
    ("Northwind may from time to time contact you with news, offers, events and job alerts. I agree to receive such messages.", (M,), False),
    ("I agree to receive SMS or WhatsApp messages about job openings", (M,), False),
    # ---- bundles
    ("I agree to the privacy notice and to receive job alerts", (P, M), False),
    ("I agree to the Privacy Policy and to my details being kept on file for future roles", (P, R), False),
    ("I accept the terms and conditions and would like to receive our newsletter", (M,), False),
    ("I agree to the processing of my data and to being contacted about other vacancies", (P, M), False),
    ("By ticking this box, you confirm that you have read our Privacy Policy and give your consent for your information to be stored in our talent pool for future opportunities", (P, R), False),
    # ---- certification / acknowledgement
    ("I certify that the information provided is true and complete", (C,), False),
    ("I confirm that all information in this application is accurate", (C,), False),
    ("I declare that the above is true to the best of my knowledge", (C,), False),
    ("I understand that false statements may result in dismissal", (C,), False),
    ("I confirm that I am at least 18 years old", (C,), False),
    ("I acknowledge that I have read and understood the Candidate Privacy Notice", (P,), False),
    ("I acknowledge that I have read the terms of use", None, False),
    # ---- third-party sharing (never)
    ("I agree that Example Employer may share my details with its partner companies", "NEVER", False),
    ("I consent to my application being shared with other companies in our network", "NEVER", False),
    ("I agree to my CV being passed to hiring partners", "NEVER", False),
    ("We may disclose your information to our customers", "NEVER", False),
    ("I consent to sharing my profile with portfolio companies", "NEVER", False),
    ("I agree to share my data with our parent company", "NEVER", False),
    ("I consent to my details being provided to background-check vendors", "NEVER", False),
    ("I agree my information may be disclosed to government agencies", "NEVER", False),
    ("I agree to my details being shared with referees", "NEVER", False),
    ("Share my profile with sister companies of Example Employer", "NEVER", False),
    ("I agree my data may be sent to franchisees", "NEVER", False),
    ("I agree to my personal data being shared with third-party recruiters", "NEVER", False),
    ("I allow Example Employer to share my resume with our clients", "NEVER", False),
    ("I agree that Example Employer may share my information with our trusted partners", "NEVER", False),
    ("I agree my personal data may be shared with our subsidiaries", "NEVER", False),
    ("Example Employer may share my application with group affiliates", "NEVER", False),
    # ---- opt-out / double negatives
    ("Tick if you do NOT want to be contacted about other roles", (M,), True),
    ("Untick to opt out of job alerts", (M,), True),
    ("I do not consent to receive marketing emails", (M,), True),
    ("I do not want my details kept on file", (R,), True),
    ("Do not keep my application after this process ends", (R,), True),
    ("I do not agree to the processing of my personal data", (P,), True),
    ("Please do not contact me about other vacancies", (M,), True),
    ("I opt out of the talent community", (M,), True),
    # ---- hidden consent in a declaration-looking label
    ("I declare that I agree to be contacted by partners", "NEVER", False),
    ("I confirm that I consent to marketing communications", (M,), False),
    ("I declare that I have read the privacy policy and consent to the processing of my data", (P,), False),
    ("I declare that I am happy for my CV to be kept on file", (R,), False),
    # ---- other
    ("I give permission for Example Employer to contact my previous employers", None, False),
    ("I consent to a background check", None, False),
    ("I agree to receive communications about my application", None, False),
]


# the wordings k1.py found unkeyed by code (no consent frame): the owner's truth is the talent-pool opt-in (M), or the
# privacy consent (P) / none (None) where the wording is not marketing
W_UNKEYED = [
    ("I agree to receive emails from Example Employer", (M,), False),
    ("I consent to receive communications from Example Employer", (M,), False),
    ("Opt in to SMS notifications", (M,), False),
    ("Yes, send me updates", (M,), False),
    ("I agree to be contacted by Example Employer's recruitment team", (M,), False),
    ("I consent to Example Employer contacting me about opportunities", (M,), False),
    ("I agree to be added to the Example Employer talent network", (M,), False),
    ("I would like to receive emails with career tips", (M,), False),
    ("Allow Example Employer to reach out to me with similar roles", (M,), False),
    ("I'd like to hear about career opportunities", (M,), False),
    ("Keep in touch", (M,), False),
    ("I would like to stay connected with Example Employer", (M,), False),
    ("I want to be notified of new openings", (M,), False),
    ("I agree to be contacted for market research surveys", (M,), False),
    ("I consent to the use of my data for research and analytics", (P,), False),
    ("I agree to the use of AI tools in evaluating my application", (P,), False),
]


# G1: a status word inside a consent / marketing / certification wording must never change its handling
W_STATUS = [
    ("I consent to the collection and use of my personal data as a Singapore citizen or PR under the PDPA", (P,), False),
    ("I agree to the privacy policy and confirm I am a Singapore citizen", (P,), False),
    ("I certify that I am a Singapore citizen and that the information provided is true and complete", (C,), False),
    ("I acknowledge that I have read the notice for Singapore citizen applicants", None, False),
    ("Keep my application on file; I am a Singapore citizen", (R,), False),
    ("I am a Singapore citizen and agree to receive job alerts", (M,), False),
    ("I agree to share my details with partner firms. I am a Singapore PR", "NEVER", False),
    ("I am a permanent resident and I agree to the privacy notice", (P,), False),
    ("Singapore citizens: tick to join our talent community", (M,), False),
    ("Are you a Singapore citizen and do you agree to receive our newsletter?", (M,), False),
    ("I confirm that my spouse is a Singapore citizen and that the information I gave is true", (C,), False),
    ("I agree that Example Employer may keep my details on file; I hold a Singapore work pass", (R,), False),
    ("Do you consent to the processing of your personal data as a Singapore citizen?", (P,), False),
    ("I am a Singapore citizen. I would like to receive updates and offers from Example Employer", (M,), False),
]
