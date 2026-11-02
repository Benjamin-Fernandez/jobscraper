"""Builder for the synthetic Workday-like fixture pages (Q-35 WP-T1; not a test file).

The pages copy the DOM *structure* of the S-5b recordings (data-automation-id, aria-*, role,
label/for, fieldset/legend, role=group entry panels, segmented date sections, prompt pills,
attachments drop zone) and carry ONLY values from tests/fixtures/apply/applicant.sample.yaml
or placeholders ("Example Employer", "Example Role", REQ-0000). Nothing is copied from a
recording: the recordings hold personal data and never leave the session scratchpad.

One spec per step gives both outputs, so they can't drift:
  page.html    what lane R's reader reads (+ shim.js for widget behaviour)
  fields.json  what the reader must return (LF §3.1; the T3 oracle)
`python tests/llm_fill_pages.py` rewrites every fixture; test_llm_fill_fixtures checks they are
in sync. Expected-field keys: label, type (FieldType value), widget (LF §3.2 family), required,
options (sorted when `options_sorted`), shown, group, group_title, context, options_complete,
automation_id, parts.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "apply" / "llm_fill"
EMPLOYER = "Example Employer"
ROLE = "Example Role"

E = html.escape
_n = [0]


def _id(prefix: str) -> str:
    _n[0] += 1
    return f"{prefix}-{_n[0]}"


def _label(text: str, req: bool, for_id: str = "", tag: str = "label", lid: str = "") -> str:
    a = f' for="{for_id}"' if for_id else ""
    a += f' id="{lid}"' if lid else ""
    star = '<abbr title="required">*</abbr>' if req else ""
    return f"<{tag}{a}><span>{E(text)}{star}</span></{tag}>"


def _help(f: dict) -> tuple[str, str]:
    if not f.get("help"):
        return "", ""
    hid = _id("help")
    return f' aria-describedby="{hid}"', f'<div id="{hid}" class="help">{E(f["help"])}</div>'


# --------------------------------------------------------------------------- widgets
def w_text(f: dict) -> str:
    cid = f.get("id") or _id("input")
    da, hd = _help(f)
    req = ' aria-required="true"' if f.get("req") else ""
    t = f.get("type", "text")
    tag = (f'<textarea id="{cid}"{req}{da}>{E(f.get("value", ""))}</textarea>' if f["w"] == "textarea"
           else f'<input type="{t}" id="{cid}" name="{f["aid"][10:] or "x"}"{req}{da} value="{E(f.get("value", ""))}">')
    return (f'<div data-automation-id="{f["aid"]}">{_label(f["label"], f.get("req"), cid)}'
            f'<div><div>{tag}</div>{hd}</div></div>')


def w_listbox(f: dict, data: dict) -> str:
    cid = f.get("id") or _id("listbox")
    data["options"][cid] = f["options"]
    if f.get("drop"):
        data["drop"][cid] = f["drop"]
    v = f.get("value", "")
    return (f'<div data-automation-id="{f["aid"]}">{_label(f["label"], f.get("req"), cid)}<div><div><div>'
            f'<button aria-haspopup="listbox" type="button" value="{E(v)}" aria-label="{E(f["label"])} {E(v or "Select One")}" '
            f'name="{f["aid"][10:]}" id="{cid}">{E(v or "Select One")}</button>'
            f'<input type="text" class="hidden-value" value="{E(v)}"><span class="icon"></span>'
            f'</div></div></div></div>')


def _pill(text: str) -> str:
    return (f'<li role="presentation" data-automation-id="menuItem" data-uxi-widget-type="selectinputlistitem">'
            f'<div role="option" data-automation-id="selectedItem" tabindex="-1" title="{E(text)}" '
            f'aria-label="{E(text)}, press delete to clear value">'
            f'<div data-automation-id="DELETE_charm" role="presentation" tabindex="-1">x</div>'
            f'<p data-automation-id="promptOption">{E(text)}</p></div></li>')


def w_prompt(f: dict, data: dict) -> str:
    cid = f.get("id") or _id("prompt")
    data["options"][cid] = f["options"]
    if f.get("search"):
        data["search"][cid] = True
    pills = f.get("value") or []
    pills = [pills] if isinstance(pills, str) else pills
    req = "true" if f.get("req") else "false"
    multi = ' aria-multiselectable="true"' if f.get("multi") else ""
    aria = _id("aria")
    return (f'<div data-automation-id="{f["aid"]}">{_label(f["label"], f.get("req"), cid)}<div><div><div>'
            f'<div tabindex="-1" data-automation-id="multiSelectContainer" id="{_id("msc")}" data-uxi-widget-type="multiselect"{multi}>'
            f'<div data-automation-id="multiselectInputContainer"><div>'
            f'<input placeholder="Search" aria-invalid="false" aria-describedby="{aria}" aria-required="{req}" '
            f'tabindex="0" data-uxi-widget-type="selectinput" id="{cid}" value="">'
            f'<div data-automation-id="promptSelectionLabel"></div>'
            f'<div id="{aria}" data-automation-id="promptAriaInstruction" class="sr-only">options available</div></div>'
            f'<div tabindex="-1"><ul role="listbox" tabindex="0" data-automation-id="selectedItemList" '
            f'aria-label="items selected" data-uxi-widget-type="selectinputlist">{"".join(_pill(p) for p in pills)}</ul></div>'
            f'<span data-automation-id="promptIcon" data-uxi-widget-type="selectinputicon" aria-invalid="false" tabindex="-2">v</span>'
            f'</div></div></div></div></div></div>')


def w_radio(f: dict, data: dict) -> str:
    gid, lid = f.get("id") or _id("radiogroup"), _id("legend")
    name = f["aid"][10:] or gid
    if f.get("reveal"):
        data["reveal"][gid] = f["reveal"]
    rows = []
    for i, o in enumerate(f["options"]):
        rid = _id("radio")
        chk = o == f.get("value")
        rows.append(f'<div><div><input id="{rid}" name="{name}" type="radio" aria-checked="{"true" if chk else "false"}" '
                    f'value="{"true" if i == 0 else "false"}"{" checked" if chk else ""}><span></span></div>'
                    f'<label for="{rid}">{E(o)}</label></div>')
    req = ' aria-required="true"' if f.get("req") else ""
    return (f'<div data-automation-id="{f["aid"]}"><fieldset><legend>{_label(f["label"], f.get("req"), lid=lid)}</legend>'
            f'<div><div><div name="{name}" aria-labelledby="{lid}" id="{gid}"{req}>{"".join(rows)}</div></div></div>'
            f'</fieldset></div>')


def w_checkbox(f: dict) -> str:
    cid = f.get("id") or _id("checkbox")
    chk = f.get("value") is True
    req = "true" if f.get("req") else "false"
    return (f'<div data-automation-id="{f["aid"]}">{_label(f["label"], f.get("req"), cid)}<div><div><div><div>'
            f'<input id="{cid}" type="checkbox" aria-checked="{"true" if chk else "false"}" name="{f["aid"][10:]}" '
            f'aria-required="{req}"{" checked" if chk else ""}><span></span></div></div></div></div></div>')


def w_date(f: dict) -> str:
    lid, wid = _id("legend"), _id("dateWrapper")
    vals = f.get("value") or [""] * len(f["parts"])
    maxv = {"Day": "31", "Month": "12", "Year": "9999"}
    secs = []
    for p, v in zip(f["parts"], vals):
        did, iid = _id("display"), _id("date")
        req = ' aria-required="true"' if f.get("req") else ""
        secs.append(f'<div><div id="{did}" data-automation-id="dateSection{p}-display">{E(v or p[0] * (4 if p == "Year" else 2))}</div>'
                    f'<input role="spinbutton" aria-label="{p}" aria-valuemax="{maxv[p]}" aria-valuemin="1" '
                    f'aria-valuetext="{E(v or p)}"{req} id="{iid}" data-display="{did}" '
                    f'data-automation-id="dateSection{p}-input" value="{E(v)}" type="text"></div>')
    return (f'<div data-automation-id="{f["aid"]}"><fieldset><legend>{_label(f["label"], f.get("req"), lid=lid)}</legend>'
            f'<div><div><div id="{wid}" aria-labelledby="{lid}" role="group" data-automation-id="dateInputWrapper"><div>'
            f'{"<div>/</div>".join(secs)}</div><div aria-label="Calendar" data-automation-id="dateIcon" role="button">c</div>'
            f'</div></div></div></fieldset></div>')


def w_file(f: dict) -> str:
    cid, lid = f.get("id") or _id("file"), _id("filelabel")
    item = ""
    if f.get("value"):
        item = (f'<div data-automation-id="file-upload-item"><div data-automation-id="file-upload-item-name">{E(f["value"])}</div>'
                f'<div data-automation-id="file-upload-successful">Successfully Uploaded!</div>'
                f'<button type="button" data-automation-id="delete-file" aria-label="Delete file">Delete</button></div>')
    return (f'<div data-automation-id="{f["aid"]}">{_label(f["label"], f.get("req"), cid, lid=lid)}'
            f'<div data-automation-id="attachments-FileUpload" aria-labelledby="{lid}">'
            f'<div data-automation-id="file-upload-drop-zone"><div>Drop file here</div><div><div>or</div>'
            f'<button type="button" data-automation-id="select-files"><span>Select files</span></button></div></div>'
            f'<input data-automation-id="file-upload-input-ref" type="file" id="{cid}" class="hidden-file">{item}</div></div>')


def w_honeypot(f: dict) -> str:
    cid = _id("hp")
    return (f'<div data-automation-id="beecatcher">{_label(f["label"], False, cid)}'
            f'<input type="text" id="{cid}" name="website" value=""></div>')


def w_static(f: dict) -> str:
    return f'<div data-automation-id="{f.get("aid", "reviewItem")}"><h4>{E(f["label"])}</h4><p>{E(f.get("value", ""))}</p></div>'


def render(f: dict, data: dict) -> str:
    w = f["w"]
    fn = {"text": w_text, "textarea": w_text, "checkbox": w_checkbox, "date": w_date, "file": w_file,
          "honeypot": w_honeypot, "static": w_static}.get(w)
    if fn:
        out = fn(f)
    else:
        out = {"listbox": w_listbox, "prompt": w_prompt, "radio": w_radio}[w](f, data)
    if f.get("hidden_until"):
        out = f'<div id="{f["hidden_until"]}" hidden>{out}</div>'
    return out


SECTION_IDS = {"Work Experience": "work_experience", "Education": "education", "Languages": "languages",
               "Websites": "websites", "Certifications": "certifications"}


def render_section(sec: dict, data: dict) -> str:
    h4 = _id("sectionHeading")
    title = sec["section"]
    panels = []
    for i, fields in enumerate(sec["entries"], 1):
        h5 = _id("entryHeading")
        body = "".join(render(f, data) for f in fields)
        panels.append(f'<div role="group" aria-labelledby="{h5}" data-entry="{i}"><div><h5 id="{h5}">{E(title)} {i}</h5>'
                      f'<button type="button" data-automation-id="panel-set-delete-button" aria-label="Delete {E(title)} {i}">'
                      f'<span>Delete</span></button></div><div>{body}</div></div>')
    tpl = ""
    if sec.get("template"):
        _save = _n[0]
        blank = "".join(render(dict({k: v for k, v in f.items() if k != "value"},
                                    id=f'{f.get("aid", "x")[10:]}-new-__N__'),
                               {"options": {}, "drop": {}, "search": {}, "reveal": {}}) for f in sec["template"])
        _n[0] = _save
        tpl = (f'<template><div role="group" aria-labelledby="new-__N__" data-entry="__N__"><div><h5 id="new-__N__">{E(title)} __N__</h5>'
               f'<button type="button" data-automation-id="panel-set-delete-button" aria-label="Delete {E(title)} __N__">'
               f'<span>Delete</span></button></div><div>{blank}</div></div></template>')
    add = "Add Another" if sec["entries"] else "Add"
    return (f'<div role="group" aria-labelledby="{h4}" data-section="{SECTION_IDS.get(title, "other")}">'
            f'<h4 id="{h4}">{E(title)}</h4>{"".join(panels)}'
            f'<div><button type="button" data-automation-id="add-button">{add}</button></div>{tpl}</div>'
            f'<div data-automation-id="smartDivider"></div>')


CSS = """body{font-family:sans-serif;margin:0}main{padding:16px}
[data-automation-id^="formField-"]{margin:8px 0}.hidden-value,.hidden-file{display:none}
.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
[data-automation-id="selectedItemList"]{list-style:none;padding:0;margin:0;display:inline}
[data-automation-id="beecatcher"]{position:absolute;left:-10000px}
input,textarea,button{margin:2px}textarea{width:400px;height:60px}"""


def page_html(step: dict, *, shim: str) -> str:
    _n[0] = 0
    data = {"options": {}, "search": {}, "drop": {}, "reveal": {}, "next": step.get("next", "")}
    body = []
    for item in step["body"]:
        body.append(render_section(item, data) if "section" in item else render(item, data))
    n, m = step.get("n", 1), step.get("m", 1)
    progress = (f'<div data-automation-id="progressBar"><div data-automation-id="progressBarActiveStep">'
                f'<span class="sr-only">current step {n} of {m}</span>{E(step["title"])}</div></div>') if m > 1 else ""
    btn = step.get("button", "Save and Continue")
    inner = "".join(body)
    if step.get("form"):
        inner = f'<form action="#" method="post">{inner}<button type="submit">Send</button></form>'
    inner += "".join(render(f, data) for f in step.get("after_form", []))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{E(EMPLOYER)} Careers</title><style>{CSS}</style></head>
<body>
<div data-automation-id="header"><header><div data-automation-id="headerTitle"><h1>{E(EMPLOYER)}</h1></div>
<div data-automation-id="utilityButtonBar"><button aria-haspopup="listbox" aria-expanded="false" data-automation-id="utilityMenuButton" type="button">Settings</button></div>
<nav><button data-automation-id="navigationItem-Candidate Home" type="button">Candidate Home</button></nav></header></div>
<main><div data-automation-id="applyFlowPage">
<h2 data-automation-id="jobTitleHeading">{E(ROLE)} (REQ-0000)</h2>{progress}
<h3>{E(step["title"])}</h3>
{inner}
</div>
<div data-automation-id="pageFooter"><button type="button" data-automation-id="pageFooterBackButton">Back</button>
<button type="button" data-automation-id="pageFooterNextButton">{E(btn)}</button></div></main>
<footer data-automation-id="footerContainer"><a data-automation-id="privacyLink" href="#privacy">Privacy</a></footer>
<script type="application/json" id="shim-data">{json.dumps(data, ensure_ascii=False)}</script>
<script src="{shim}"></script>
</body></html>
"""


# --------------------------------------------------------------------------- expected reader output
TYPES = {"text": "text", "textarea": "textarea", "listbox": "dropdown", "radio": "radio",
         "checkbox": "checkbox", "date": "date", "file": "file"}
WIDGETS = {"text": "text", "textarea": "text", "listbox": "aria_listbox", "radio": "radio",
           "checkbox": "checkbox", "date": "segmented_date", "file": "file", "prompt": "prompt"}
INPUT_TYPES = {"email": "email", "tel": "phone", "url": "url", "number": "number"}


def _options(f: dict) -> list[str]:
    out = []
    for o in f.get("options") or []:
        out += [o] if isinstance(o, str) else [f'{o["cat"]} > {leaf}' for leaf in o["items"]]
    return out


def expected(f: dict, group: str = "", group_title: str = "") -> dict | None:
    w = f["w"]
    if w in ("honeypot", "static") or f.get("hidden_until"):
        return None
    pills = f.get("value") or []
    pills = [pills] if isinstance(pills, str) else pills
    if w == "prompt":
        typ = "multi_choice" if len(pills) > 1 else "typeahead"   # LF §3.1: several pills -> MULTI_CHOICE
        shown: object = pills if typ == "multi_choice" else (pills[0] if pills else "")
    elif w in ("text", "textarea"):
        typ = INPUT_TYPES.get(f.get("type", "text"), "text") if w == "text" else "textarea"
        shown = f.get("value", "")
    elif w == "checkbox":
        typ, shown = "checkbox", "true" if f.get("value") is True else "false"
    elif w == "date":
        typ, shown = "date", "/".join(v for v in (f.get("value") or []) if v)
    else:
        typ, shown = TYPES[w], f.get("value") or ""
    return {
        "label": f["label"], "type": typ, "widget": WIDGETS[w], "required": bool(f.get("req")),
        "options": sorted(_options(f)) if w in ("listbox", "radio", "prompt") and not f.get("search") else [],
        "options_sorted": True, "shown": shown, "group": group, "group_title": group_title,
        "context": f.get("context", ""), "options_complete": not f.get("search"),
        "automation_id": f["aid"] if w != "honeypot" else "", "parts": f.get("parts", []),
        "help": f.get("help", ""),
    }


def expected_fields(step: dict) -> list[dict]:
    out = []
    for item in list(step["body"]) + list(step.get("after_form", [])):
        if "section" in item:
            sid = SECTION_IDS.get(item["section"], "other")
            for i, fields in enumerate(item["entries"], 1):
                for f in fields:
                    e = expected(f, f"{sid}#{i}", f'{item["section"]} {i}')
                    if e:
                        out.append(e)
        else:
            e = expected(item)
            if e:
                out.append(e)
    return out


# --------------------------------------------------------------------------- the steps
YN = ["Yes", "No"]
HOW_HEARD = [{"cat": "Job Board", "items": ["LinkedIn", "JobStreet", "Indeed"]},
             {"cat": "Company Website", "items": ["Careers Page", "Talent Community"]},
             {"cat": "Referral", "items": ["Employee Referral", "Agency"]},
             "Career Fair", "Other"]
COUNTRIES = ["Singapore", "Malaysia", "United States of America"]
LEVELS = ["Beginner", "Intermediate", "Advanced", "Native"]


def my_information(n: int, m: int, *, address2_required: bool, nxt: str) -> dict:
    return {"title": "My Information", "n": n, "m": m, "next": nxt, "body": [
        {"w": "prompt", "label": "How Did You Hear About Us?", "aid": "formField-source", "req": True,
         "options": HOW_HEARD},
        {"w": "radio", "label": f"Have you previously worked for {EMPLOYER}?",
         "aid": "formField-candidateIsPreviousWorker", "req": True, "options": YN},
        {"w": "listbox", "label": "Country", "aid": "formField-country", "req": True, "options": COUNTRIES,
         "value": "Singapore"},
        {"w": "text", "label": "Given Name(s)", "aid": "formField-legalName--firstName", "req": True, "value": "Alex"},
        {"w": "text", "label": "Family Name", "aid": "formField-legalName--lastName", "req": True, "value": "Testcase"},
        {"w": "checkbox", "label": "I have a preferred name", "aid": "formField-preferredCheck", "value": False},
        {"w": "text", "label": "Address Line 1", "aid": "formField-addressLine1", "req": True, "value": "1 Example Road"},
        {"w": "text", "label": "Address Line 2", "aid": "formField-addressLine2", "req": address2_required},
        {"w": "honeypot", "label": "Leave this field blank (for robots)"},
        {"w": "text", "label": "Postal Code", "aid": "formField-postalCode", "req": True, "value": "000001"},
        {"w": "text", "label": "City", "aid": "formField-city", "value": "Singapore"},
        {"w": "listbox", "label": "Phone Device Type", "aid": "formField-phoneType", "req": True,
         "options": ["Mobile", "Home", "Work"]},
        {"w": "prompt", "label": "Country Phone Code", "aid": "formField-countryPhoneCode", "req": True,
         "options": ["Singapore (+65)", "Malaysia (+60)", "United States of America (+1)"], "search": True,
         "value": "Singapore (+65)"},
        {"w": "text", "label": "Phone Number", "aid": "formField-phoneNumber", "req": True, "value": "91234567"},
        {"w": "text", "label": "Phone Extension", "aid": "formField-extension"},
    ]}


def _job(title: str, company: str, loc: str, start: list, end: list, desc: str) -> list[dict]:
    return [
        {"w": "text", "label": "Job Title", "aid": "formField-jobTitle", "req": True, "value": title},
        {"w": "text", "label": "Company", "aid": "formField-companyName", "req": True, "value": company},
        {"w": "text", "label": "Location", "aid": "formField-location", "value": loc},
        {"w": "checkbox", "label": "I currently work here", "aid": "formField-currentlyWorkHere", "value": False},
        {"w": "date", "label": "From", "aid": "formField-startDate", "req": True, "parts": ["Month", "Year"], "value": start},
        {"w": "date", "label": "To", "aid": "formField-endDate", "req": True, "parts": ["Month", "Year"], "value": end},
        {"w": "textarea", "label": "Role Description", "aid": "formField-roleDescription", "value": desc},
    ]


def _lang(name: str, level: str) -> list[dict]:
    return [
        {"w": "listbox", "label": "Language", "aid": "formField-language", "req": True,
         "options": ["English", "Mandarin", "Malay", "Tamil", "Japanese"], "value": name},
        {"w": "checkbox", "label": "I am fluent in this language.", "aid": "formField-native", "value": level == "Native"},
        {"w": "listbox", "label": "Overall", "aid": "formField-languageProficiency", "req": True, "options": LEVELS,
         "value": level},
    ]


JUNK = "Projects: Campus Robot League - built a line-following robot in C++ for the university league."
MY_EXPERIENCE = {"title": "My Experience", "n": 3, "m": 7, "next": "../04-questions_1/page.html", "body": [
    {"section": "Work Experience", "template": _job("", "", "", ["", ""], ["", ""], ""), "entries": [
        # S-5b 2: the parser put the company into the title; S-5b 5: a Projects block appended
        _job("Software Engineering Intern, Example Logistics Pte Ltd", "Example Logistics Pte Ltd", "Singapore",
             ["5", "2024"], ["8", "2024"],
             "Built REST APIs in Python and Postgres for shipment tracking. " + JUNK),
        # S-5b 3: no location in this entry's resume block (the model takes the header's city)
        _job("Data Intern", "Sample Analytics", "Singapore", ["1", "2025"], ["6", "2025"],
             "Automated weekly reports with SQL and Python."),
        # E3: parser junk, no source entry (a project turned into a job)
        _job("Campus Robot League", "", "", ["", ""], ["", ""], "Built a line-following robot in C++."),
    ]},
    {"section": "Education", "entries": [[
        {"w": "text", "label": "School or University", "aid": "formField-schoolName", "req": True,
         "value": "Nanyang Example University"},
        # S-5b 6: this listbox shows the pick once but keeps no value (error after blur)
        {"w": "listbox", "label": "Degree", "aid": "formField-degree", "req": True,
         "options": ["Bachelor's Degree", "Master's Degree", "Diploma"], "value": "Bachelor's Degree", "drop": "once"},
        {"w": "prompt", "label": "Field of Study", "aid": "formField-fieldOfStudy",
         "options": ["Computer Engineering", "Computer Science", "Electrical Engineering"], "value": "Computer Engineering"},
        {"w": "text", "label": "Overall Result (GPA)", "aid": "formField-gradeAverage", "value": "4.20"},
        {"w": "date", "label": "From", "aid": "formField-firstYearAttended", "parts": ["Year"], "value": ["2021"]},
        {"w": "date", "label": "To (Actual or Expected)", "aid": "formField-lastYearAttended", "parts": ["Year"],
         "value": ["2025"]},
    ]]},
    {"section": "Languages", "entries": [
        _lang("English", "Native"),
        # S-5b 4: a language the profile doesn't list, with an invented level
        _lang("Japanese", "Advanced"),
    ]},
    {"w": "prompt", "label": "Type to Add Skills", "aid": "formField-skills", "search": True, "multi": True,
     "options": ["Python", "SQL", "PostgreSQL", "Git", "Java"], "value": ["Python", "SQL", "Git"]},
    {"section": "Websites", "entries": [[
        {"w": "text", "label": "URL", "aid": "formField-url", "req": True, "type": "url",
         "value": "https://github.com/example-alex-testcase"},
    ]]},
    {"w": "file", "label": "Resume/CV", "aid": "formField-resumeAttachments", "req": True,
     "value": "Alex_Testcase_Resume.pdf"},
    {"w": "text", "label": "LinkedIn Profile", "aid": "formField-linkedInAccount", "type": "url", "value": ""},
]}

Q1 = "Have you ever been employed by Example Employer or any of its subsidiaries?"
QUESTIONS_1 = {"title": "Application Questions", "n": 4, "m": 7, "next": "../05-questions_2/page.html", "body": [
    {"w": "listbox", "label": "Are you legally authorised to work in Singapore?",
     "aid": "formField-5eed0000000000000000000000000001", "req": True, "options": YN},
    {"w": "listbox", "label": "Will you now or in the future require sponsorship for an employment pass?",
     "aid": "formField-5eed0000000000000000000000000002", "req": True, "options": YN},
    {"w": "listbox", "label": "Are you a Singapore Citizen or Permanent Resident?",
     "aid": "formField-5eed0000000000000000000000000003", "req": True,
     "options": ["Singapore Citizen", "Singapore Permanent Resident", "Neither"]},
    {"w": "radio", "label": Q1, "aid": "formField-5eed0000000000000000000000000004", "req": True, "options": YN},
    {"w": "textarea", "label": "If yes, please specify", "aid": "formField-5eed0000000000000000000000000005",
     "context": Q1},
    {"w": "text", "label": "What is your expected monthly salary (SGD)?",
     "aid": "formField-5eed0000000000000000000000000010", "req": True,
     "help": "Numbers only, for example 4500."},
]}
QUESTIONS_2 = {"title": "Application Questions", "n": 5, "m": 7, "next": "../06-voluntary_disclosures/page.html",
               "body": [{"w": "text", "label": "What is your earliest available start date?",
                         "aid": "formField-5eed0000000000000000000000000011", "req": True}]}
VOLUNTARY = {"title": "Voluntary Disclosures", "n": 6, "m": 7, "next": "../07-review/page.html", "body": [
    {"w": "listbox", "label": "Gender", "aid": "formField-gender", "req": True,
     "options": ["Male", "Female", "I do not wish to disclose"]},
    {"w": "checkbox", "label": "I have read and consent to the processing of my personal data as set out in the privacy notice.",
     "aid": "formField-acceptTermsAndAgreements", "req": True, "value": False},
]}
REVIEW = {"title": "Review", "n": 7, "m": 7, "next": "", "button": "Submit", "body": [
    {"w": "static", "label": "Given Name(s)", "value": "Alex"},
    {"w": "static", "label": "Family Name", "value": "Testcase"},
    {"w": "static", "label": "Resume/CV", "value": "Alex_Testcase_Resume.pdf"},
    {"w": "static", "label": "What is your expected monthly salary (SGD)?", "value": "5000"},
]}
AUTOFILL = {"title": "Autofill with Resume", "n": 1, "m": 7, "next": "../02-my_information/page.html", "body": [
    {"w": "file", "label": "Upload a file (5MB max)", "aid": "formField-resumeAttachments", "req": True},
]}

STEPS = {
    "wd_a": {
        "01-autofill_with_resume": AUTOFILL,
        "02-my_information": my_information(2, 7, address2_required=False, nxt="../03-my_experience/page.html"),
        "03-my_experience": MY_EXPERIENCE,
        "04-questions_1": QUESTIONS_1,
        "05-questions_2": QUESTIONS_2,
        "06-voluntary_disclosures": VOLUNTARY,
        "07-review": REVIEW,
    },
    # tenant B (S-5b): stopped at My Information on a REQUIRED "Additional Address" line
    "wd_b": {"02-my_information": dict(my_information(2, 6, address2_required=True, nxt=""), title="My Information")},
}

# --------------------------------------------------------------------------- stubs (T3)
CATS40 = [{"cat": c, "items": [f"{c} {k}" for k in ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf")]}
          for c in ("Job Board", "Social Media", "Company Website", "Referral", "Event")] + \
         ["Career Fair", "Other", "Newspaper", "Radio", "University"]
STUBS = {
    "prompt_categories": {"title": "Categories", "body": [
        {"w": "prompt", "label": "How Did You Hear About Us?", "aid": "formField-source", "req": True, "options": CATS40}]},
    "listbox_error": {"title": "Listbox read-back", "body": [
        {"w": "listbox", "label": "Degree", "aid": "formField-degree", "req": True,
         "options": ["Bachelor's Degree", "Diploma"], "drop": "always", "id": "lb-always"},
        {"w": "listbox", "label": "Country", "aid": "formField-country", "req": True,
         "options": COUNTRIES, "drop": "once", "id": "lb-once"},
        {"w": "listbox", "label": "Phone Device Type", "aid": "formField-phoneType", "req": True,
         "options": ["Mobile", "Home"], "id": "lb-ok"}]},
    "dates": {"title": "Dates", "body": [
        {"w": "date", "label": "From", "aid": "formField-startDate", "req": True, "parts": ["Month", "Year"],
         "value": ["3", "2026"], "id": "d-prefilled"},
        {"w": "date", "label": "To", "aid": "formField-endDate", "parts": ["Month", "Year"]},
        {"w": "date", "label": "Date of Signature", "aid": "formField-dateSignedOn", "parts": ["Day", "Month", "Year"]},
        {"w": "date", "label": "Graduation Year", "aid": "formField-lastYearAttended", "parts": ["Year"]}]},
    "honeypot": {"title": "Dropped controls", "body": [
        {"w": "honeypot", "label": "Leave this field blank (for robots)"},
        {"w": "text", "label": "Given Name(s)", "aid": "formField-legalName--firstName", "req": True, "value": "Alex"}]},
    "file_slots": {"title": "Files", "body": [
        {"w": "file", "label": "Resume/CV", "aid": "formField-resumeAttachments", "req": True,
         "value": "Imported_Resume_Old.pdf"},
        {"w": "file", "label": "Transcript", "aid": "formField-transcript"},
        {"w": "file", "label": "Cover Letter", "aid": "formField-coverLetter", "req": True}]},
    "reveal": {"title": "Revealed follow-up (review H7)", "body": [
        {"w": "radio", "label": "Do you have any relatives working at Example Employer?", "aid": "formField-relatives",
         "req": True, "options": YN, "id": "rel-group", "reveal": {"when": "Yes", "show": "rel-details"}},
        {"w": "textarea", "label": "If yes, please specify", "aid": "formField-relativesDetails", "req": True,
         "hidden_until": "rel-details"}]},
    "enter_form": {"title": "Enter inside a form (review M8)", "form": True, "body": [
        {"w": "prompt", "label": "Country Phone Code", "aid": "formField-countryPhoneCode", "req": True,
         "options": ["Singapore (+65)", "Malaysia (+60)"], "search": True, "id": "enter-prompt"},
        {"w": "text", "label": "City", "aid": "formField-city", "id": "enter-text"}],
        # LF §3.2 / M8: Enter is allowed only in a prompt search box OUTSIDE a form with a submit control
        "after_form": [
            {"w": "prompt", "label": "Mobile Country Code", "aid": "formField-mobileCountryCode", "req": True,
             "options": ["Singapore (+65)", "Malaysia (+60)", "United States of America (+1)"], "search": True,
             "id": "outside-prompt"}]},
}


# The synthetic resume: its HEADER carries the sample's contact values (S paths) on purpose, so
# the "no S value in any prompt" oracle (review H4 / tester TR-1) has something to catch.
RESUME_SAMPLE = """Alex Testcase | Singapore | alex.testcase@example.com | Mobile: +65 9123 4567
1 Example Road, Singapore 000001

EXPERIENCE
Software Engineering Intern, Example Logistics Pte Ltd, Singapore (May 2024 - Aug 2024)
- Built REST APIs in Python and Postgres for shipment tracking.
Data Intern, Sample Analytics (Jan 2025 - Jun 2025)
- Automated weekly reports with SQL and Python.

PROJECTS
Campus Robot League - built a line-following robot in C++ for the university league.

EDUCATION
Nanyang Example University, Bachelor of Engineering (Computer Engineering), 2021 - 2025, CAP 4.20/5.00

SKILLS
Python, SQL, PostgreSQL, Git
Languages: English, Mandarin
"""
JD_SAMPLE = f"""{ROLE} at {EMPLOYER} (Singapore)
We are looking for a graduate software engineer to build internal tools in Python and SQL.
Requirements: a degree in Computer Engineering or Computer Science; Python; SQL; Git.
"""


# --------------------------------------------------------------------------- fake model replies
# Keyed "<group_title>|<question>" (group_title "" outside entries), the model's raw decision
# BEFORE the guards (LF §6.3). `kind`: page | entry | pick | recheck | second | corrective.
# pick/recheck `raw` shapes are ASSUMED until lane M pins them (review M6).
def _d(source: str, ref: str = "", value: object = "", evidence: str = "") -> dict:
    return {"source": source, "ref": ref, "value": value, "evidence": evidence}


MI = {
    # S-5b 1: the hierarchical list is mapped by the program (fact_value + pick_option, D-86 F7). The
    # model cites the fact with an empty value (LF §7 G2(d): empty or equal -> the program's value).
    # The S-5b reply ("Company careers website", the fact's own words) ends G2d unknown today: tester
    # question to the architect (2026-11-03) and the guard-table pin on the leaf form.
    "|How Did You Hear About Us?": _d("standing", "standing:how_heard", ""),
    f"|Have you previously worked for {EMPLOYER}?": _d("standing", "standing:worked_here", "No"),
    "|Country": _d("profile", "profile:contact.country", "Singapore"),
    "|Given Name(s)": _d("profile", "profile:identity.legal_first_name", "Alex"),
    "|Family Name": _d("profile", "profile:identity.legal_last_name", "Testcase"),
    "|I have a preferred name": _d("unknown"),
    "|Address Line 1": _d("profile", "profile:contact.address_line1"),
    "|Postal Code": _d("profile", "profile:contact.postal_code"),
    "|City": _d("profile", "profile:contact.city", "Singapore"),
    "|Phone Device Type": _d("resume", "", "Mobile", "Mobile"),
    "|Country Phone Code": _d("profile", "profile:contact.phone_country_code"),
    "|Phone Number": _d("profile", "profile:contact.phone_number"),
    "|Phone Extension": _d("unknown"),
}
# G5 (LF §7): every required choice the model chose (not a cited fact) gets a second opinion that
# must agree (lane R R3 run, 2026-11-03: wd_a/wd_b 02 lacked it). Keyed, repeatable.
SECONDS = [
    # a field whose read-back fails gets one corrective call (LF §8 step 11): the same citation again
    {"kind": "corrective", "repeat": True, "reply": {
        "|How Did You Hear About Us?": _d("standing", "standing:how_heard", ""),
        "|Country Phone Code": _d("profile", "profile:contact.phone_country_code")}},
    {"kind": "second", "repeat": True, "reply": {"|Phone Device Type": _d("resume", "", "Mobile", "Mobile")}},
    {"kind": "second", "repeat": True, "reply": {
        "|How Did You Hear About Us?": _d("standing", "standing:how_heard", "Company careers website")}},
]
REPLIES = {
    "wd_a": {
        "01-autofill_with_resume": [],          # FILE fields never reach the model
        "02-my_information": [
            {"kind": "page", "reply": dict(MI, **{"|Address Line 2": _d("unknown")})},
            {"kind": "pick", "match": "How Did You Hear About Us?", "raw": {"choice": "Company Website > Careers Page"}},
            *SECONDS,
        ],
        "03-my_experience": [
            {"kind": "entry", "reply": {
                # S-5b 2: the company kept inside the title (grounded, so only a rule/guard on the title catches it)
                "Work Experience 1|Job Title": _d("keep", "", "Software Engineering Intern, Example Logistics Pte Ltd",
                                                  "Software Engineering Intern, Example Logistics Pte Ltd"),
                "Work Experience 1|Company": _d("profile", "profile:experience[0].employer", "Example Logistics Pte Ltd"),
                "Work Experience 1|Location": _d("resume", "", "Singapore", "Example Logistics Pte Ltd, Singapore"),
                "Work Experience 1|I currently work here": _d("profile", "profile:experience[0].end", "false"),
                "Work Experience 1|From": _d("profile", "profile:experience[0].start", "2024-05"),
                "Work Experience 1|To": _d("profile", "profile:experience[0].end", "2024-08"),
                # S-5b 5: the parser's description kept with the Projects block (recheck replaces it)
                "Work Experience 1|Role Description": _d("keep", "", "", "Built REST APIs in Python and Postgres"),
            }},
            # G11 / D-84 R3: the title that names the company is rechecked against the entry's block
            # (keyed, so it is taken only by the Job Title recheck; listed before the entry-wide one)
            {"kind": "recheck", "reply": {
                "Work Experience 1|Job Title": _d("resume", "", "Software Engineering Intern",
                                                  "Software Engineering Intern")}},
            {"kind": "recheck", "match": "Work Experience 1",
             "raw": _d("resume", "", "Built REST APIs in Python and Postgres for shipment tracking.",
                       "Built REST APIs in Python and Postgres for shipment tracking.")},
            {"kind": "entry", "reply": {
                "Work Experience 2|Job Title": _d("profile", "profile:experience[1].title", "Data Intern"),
                "Work Experience 2|Company": _d("profile", "profile:experience[1].employer", "Sample Analytics"),
                # S-5b 3: the entry's location quoted from the resume HEADER (the home city)
                "Work Experience 2|Location": _d("resume", "", "Singapore", "Alex Testcase | Singapore"),
                "Work Experience 2|I currently work here": _d("profile", "profile:experience[1].end", "false"),
                "Work Experience 2|From": _d("profile", "profile:experience[1].start", "2025-01"),
                "Work Experience 2|To": _d("profile", "profile:experience[1].end", "2025-06"),
                "Work Experience 2|Role Description": _d("keep", "", "", "Automated weekly reports with SQL and Python."),
            }},
            {"kind": "recheck", "match": "Work Experience 2",
             "raw": _d("resume", "", "Automated weekly reports with SQL and Python.",
                       "Automated weekly reports with SQL and Python.")},
            {"kind": "entry", "reply": {
                "Education 1|School or University": _d("profile", "profile:education[0].institution",
                                                       "Nanyang Example University"),
                "Education 1|Degree": _d("profile", "profile:education[0].degree", "Bachelor's Degree"),
                "Education 1|Field of Study": _d("profile", "profile:education[0].major", "Computer Engineering"),
                "Education 1|Overall Result (GPA)": _d("profile", "profile:education[0].grade", "4.20"),
                "Education 1|From": _d("profile", "profile:education[0].start", "2021"),
                "Education 1|To (Actual or Expected)": _d("profile", "profile:education[0].end", "2025"),
            }},
            {"kind": "entry", "reply": {
                "Languages 1|Language": _d("profile", "profile:languages[0].language", "English"),
                "Languages 1|I am fluent in this language.": _d("profile", "profile:languages[0].spoken", "true"),
                "Languages 1|Overall": _d("profile", "profile:languages[0].spoken", "Native"),
            }},
            {"kind": "entry", "reply": {
                # S-5b 4: a level invented for a language the profile doesn't list
                "Languages 2|Language": _d("keep", "", "Japanese", ""),
                "Languages 2|I am fluent in this language.": _d("unknown"),
                "Languages 2|Overall": _d("resume", "", "Advanced", "Languages: English, Mandarin"),
            }},
            {"kind": "entry", "reply": {
                "Websites 1|URL": _d("profile", "profile:links.github", "https://github.com/example-alex-testcase"),
            }},
            {"kind": "page", "reply": {
                "|Type to Add Skills": _d("profile", "profile:skills", ["Python", "SQL", "Git"]),
                "|LinkedIn Profile": _d("profile", "profile:links.linkedin",
                                        "https://www.linkedin.com/in/example-alex-testcase"),
            }},
            # S-5b 6: Degree read back empty with a site error -> one corrective call
            {"kind": "corrective", "reply": {
                "Education 1|Degree": _d("profile", "profile:education[0].degree", "Bachelor's Degree")}},
        ],
        "04-questions_1": [
            {"kind": "page", "reply": {
                "|If yes, please specify": _d("unknown"),
                "|What is your expected monthly salary (SGD)?": _d("profile", "profile:pay.expected_salary", "5000"),
            }},
        ],
        "05-questions_2": [
            {"kind": "page", "reply": {
                "|What is your earliest available start date?":
                    _d("profile", "profile:availability.earliest_start_date", "2026-01-05")}},
        ],
        "06-voluntary_disclosures": [],         # gender and the consent are locks (L5)
        "07-review": [],
    },
    "wd_b": {
        "02-my_information": [
            # the required Additional Address: the model cites an empty profile path (S-5b tenant B)
            {"kind": "page", "reply": dict(MI, **{"|Address Line 2": _d("profile", "profile:contact.address_line2")})},
            {"kind": "pick", "match": "How Did You Hear About Us?", "raw": {"choice": "Company Website > Careers Page"}},
            *SECONDS,
        ],
    },
}


def build_all(dest: Path = FIX) -> dict[str, str]:
    """Every fixture file's text keyed by its path relative to `dest` (nothing written)."""
    out: dict[str, str] = {}
    for tenant, steps in STEPS.items():
        for name, step in steps.items():
            out[f"{tenant}/{name}/page.html"] = page_html(step, shim="../../shim.js")
            out[f"{tenant}/{name}/fields.json"] = json.dumps(expected_fields(step), indent=1, ensure_ascii=False) + "\n"
            out[f"{tenant}/{name}/reply.json"] = json.dumps({"calls": REPLIES[tenant][name]}, indent=1,
                                                            ensure_ascii=False) + "\n"
    out["resume_sample.txt"] = RESUME_SAMPLE
    out["jd_sample.txt"] = JD_SAMPLE
    for name, step in STUBS.items():
        out[f"stubs/{name}.html"] = page_html(dict(step, m=1), shim="../shim.js")
        out[f"stubs/{name}.fields.json"] = json.dumps(expected_fields(step), indent=1, ensure_ascii=False) + "\n"
    return out


def write_all(dest: Path = FIX) -> int:
    files = build_all(dest)
    for rel, text in files.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    return len(files)


if __name__ == "__main__":
    print(f"wrote {write_all()} fixture files under {FIX}", file=sys.stderr)
