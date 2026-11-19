#!/usr/bin/env python
"""Focused one-field probes behind the findings of Q-121-unlock-A (wordings varied one at a time).

    JOBSCRAPER_OLLAMA_AUTOSTART=0 python docs/reviews/Q-121-unlock-A-probes/probe_cases.py [group]

Each case = one required field alone on a page, scripted model per `model`:
  competent  right class, true answer      blind  class "ordinary", true answer      wrong  class "ordinary", flipped answer
Prints what the filler wrote or why it stopped / left empty. No real model.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_corpus as RC                      # noqa: E402
from run_corpus import AL, T, TODAY, _profile, BR, Scripted   # noqa: E402

YN = "Yes;No"


def case(label, ans, short, typ="RADIO", opts=YN, model="competent", req=True, profile=None):
    flip = {"yes": "No", "no": "Yes"}
    e = dict(key="f1", type=typ, req=req, label=label, opts=[o for o in opts.split(";") if o], short=short, ans=ans, help="")
    form = {"name": "probe", "style": "workday", "employer": "Example Co", "title": "x",
            "pages": [{"title": "Probe", "fields": [e]}]}
    ask = Scripted(form, "competent")
    cls = RC.klass(short)
    if model in ("blind", "wrong"):
        ask.blind = {"f1"}
        ask.mode = "realistic"
        ask.wrong = "f1" if model == "wrong" else None
    p = profile or _profile()
    r = T.rctx(p, employer_name="Example Co", ats="workday", resume_path="C:/fake/resume.pdf", account_email=p["contact"]["email"])
    b = BR.build(p, r, today=TODAY)
    pf = RC.build_pf(e)
    try:
        out = AL.fill_page_always([pf], brief=b, rctx=r, ask=ask, rules=T.rules(), today=TODAY,
                                  step_title="Probe", uploaded={}, page_text="")
    except AL.AlwaysStop as s:
        return f"STOP {s.reason.value}: {s.detail}"
    a = out.answers["f1"]
    if a.value in (None, "", []):
        return f"EMPTY ({a.status.value}) {a.note[:110]}"
    shown = ", ".join(a.option_labels) if a.option_labels else str(a.value)
    return f"wrote {shown!r} src={a.source} assumed={a.assumed} {a.note[:70]}"


GROUPS = {
 "sponsor": [
  ("Will you require Contoso Logistics to sponsor you for a work visa or employment pass now or in the future?", "No", "sp"),
  ("Will you require sponsorship for a work visa or employment pass now or in the future?", "No", "sp"),
  ("Will you require us to sponsor you for a work visa?", "No", "sp"),
  ("Do you need the company to sponsor your work pass?", "No", "sp"),
  ("Will you now or in the future require sponsorship for employment visa status?", "No", "sp"),
  ("Will you require visa sponsorship?", "No", "sp"),
 ],
 "bank": [
  ("Do you have any outside business interests or shareholdings that could conflict with your duties at Northwind Bank?", "No", "dec:conflict_audit_independence"),
  ("Do you have any outside business interests that could conflict with your duties at Northwind?", "No", "dec:conflict_audit_independence"),
  ("Have you previously applied to Northwind Bank?", "No", "dec:previously_applied"),
  ("Are you currently employed by Northwind Bank?", "No", "dec:current_employee_at_company"),
  ("Have you ever been employed by Northwind Bank or any of its subsidiaries before?", "No", "dec:prior_employment_at_company"),
  ("Do you have any relatives or close friends working in Meridian Bank?", "No", "dec:relatives_at_company"),
  ("Are you legally authorised to work in Singapore for Northwind Bank?", "Yes", "wr"),
  ("Are you willing to undergo a background check by Northwind Bank?", "Yes", "ord"),
  ("Why do you want to join Northwind Bank?", "x", "ord", "TEXT", ""),
  ("How did you hear about Northwind Bank?", "Company website", "ord", "DROPDOWN", "Company website;LinkedIn;Other"),
 ],
 "privacy": [
  ("I consent to Blue Heron Studios storing my personal data for 12 months for the purposes of this recruitment process.", "true", "priv", "CHECKBOX", ""),
  ("I consent to Blue Heron Studios processing my personal data for the purposes of this recruitment process.", "true", "priv", "CHECKBOX", ""),
  ("I agree that my personal data may be stored for 12 months for this recruitment.", "true", "priv", "CHECKBOX", ""),
  ("I consent to the collection, use and disclosure of my personal data for recruitment purposes in accordance with the PDPA.", "true", "priv", "CHECKBOX", ""),
  ("I consent to Acme storing my data for 12 months so it can contact me about other opportunities.", "true", "ret", "CHECKBOX", ""),
 ],
 "authorise": [
  ("I authorise Pinnacle Insurance to verify my education, employment history and criminal record.", "true", "ack", "CHECKBOX", ""),
  ("I consent to Lumen carrying out background, reference and criminal record checks before I am hired.", "true", "ack", "CHECKBOX", ""),
  ("I authorise the company to conduct background checks.", "true", "ack", "CHECKBOX", ""),
  ("I authorise Pinnacle Insurance to verify my education and employment history.", "true", "ack", "CHECKBOX", ""),
  ("I understand that a criminal record check will be done.", "true", "ack", "CHECKBOX", ""),
 ],
 "sharing": [
  ("I consent to my personal data being shared with Acme Trading's affiliates and group companies, in Singapore and overseas, for recruitment purposes.", "true", "priv", "CHECKBOX", ""),
  ("I consent to Meridian Bank and its related corporations, affiliates and service providers collecting, using and disclosing my personal data for employment purposes.", "true", "priv", "CHECKBOX", ""),
  ("I understand that Initech will share my personal data with its group companies and service providers for processing my application.", "true", "priv", "CHECKBOX", ""),
  ("I consent to disclosure to our affiliated funds and portfolio companies where necessary.", "true", "priv", "CHECKBOX", ""),
  ("I consent to my data being transferred to and processed by group companies in other countries.", "true", "priv", "CHECKBOX", ""),
  ("I consent to the use of my personal data by Example Co and its service providers for recruitment.", "true", "priv", "CHECKBOX", ""),
  ("I consent to Example Co sharing my data with third parties for recruitment purposes.", "true", "priv", "CHECKBOX", ""),
 ],
 "privacy2": [
  ("I consent to Blue Heron Studios storing my personal data for the purposes of this recruitment process.", "true", "priv", "CHECKBOX", ""),
  ("I consent to Blue Heron Studios storing my personal data for 12 months.", "true", "priv", "CHECKBOX", ""),
  ("I consent to my personal data being retained for 12 months for the purposes of this recruitment process.", "true", "priv", "CHECKBOX", ""),
  ("I agree to the Candidate Privacy Notice and to my data being stored for up to 2 years for this application.", "true", "priv", "CHECKBOX", ""),
  ("I consent to Kestrel Labs storing my personal data for 12 months for recruitment purposes", "true", "ret", "CHECKBOX", ""),
  ("I would like to be kept on file for future opportunities", "true", "ret", "CHECKBOX", ""),
 ],
 "status2": [
  ("Your work authorisation status in Singapore", "Citizen", "wr", "DROPDOWN", "Citizen;Permanent Resident;Employment Pass;S Pass"),
  ("Your work authorisation status in Singapore", "Citizen", "wr", "RADIO", "Citizen;Permanent Resident;Employment Pass;S Pass"),
  ("Singapore work pass type", "Not applicable", "wr", "DROPDOWN", "Not applicable;Employment Pass;S Pass;Student Pass"),
  ("Are you legally authorized to work in the United States?", "No", "wr"),
  ("Are you eligible to work in the US?", "No", "wr"),
  ("Do you require sponsorship to work in the United States?", "No", "sp"),
  ("Are you legally authorised to work in Malaysia?", "No", "wr"),
 ],
 "sponsor2": [
  ("Will you require us to sponsor you for a work visa?", "No", "sp"),
  ("Do you require us to sponsor your visa?", "No", "sp"),
  ("Would you need Example Co to sponsor you?", "No", "sp"),
  ("Are you going to need a company to sponsor an employment pass for you?", "No", "sp"),
 ],
 "salary": [
  ("Last drawn monthly salary (SGD)", "~", "of:salary_current", "NUMBER", ""),
  ("Current / last drawn monthly salary (SGD)", "~", "of:salary_current", "TEXT", ""),
  ("Current salary (SGD per month)", "~", "of:salary_current", "TEXT", ""),
 ],
 "status": [
  ("What is your current immigration status in Singapore?", "Citizen", "wr", "DROPDOWN", "Citizen;Permanent Resident;Employment Pass;S Pass"),
  ("Are you a Singapore citizen?", "Yes", "wr"),
  ("Are you a Singapore Citizen or Permanent Resident?", "Yes", "wr"),
  ("Are you a citizen or permanent resident?", "Yes", "wr"),
  ("Do you hold a valid Singapore work pass?", "No", "wr"),
  ("Do you require a work pass to work in Singapore?", "No", "wr"),
 ],
}


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else ""
    for g, cases in GROUPS.items():
        if want and want != g:
            continue
        print(f"--- {g}")
        for c in cases:
            label, ans, short = c[0], c[1], c[2]
            typ = c[3] if len(c) > 3 else "RADIO"
            opts = c[4] if len(c) > 4 else YN
            models = ("competent", "blind", "wrong") if g in ("sponsor", "sponsor2", "status", "status2") else ("competent",)
            for m in models:
                try:
                    res = case(label, ans, short, typ, opts, m)
                except Exception as ex:                 # noqa: BLE001
                    res = f"EXC {type(ex).__name__}: {ex}"[:150]
                print(f"[{m[:4]}] {label[:96]!r}\n        -> {res}")


if __name__ == "__main__":
    main()
