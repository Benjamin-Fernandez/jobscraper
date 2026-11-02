"""Spike S-5b (Q-23b, D-78): LLM-driven generic form filling, first prototype.

Not production code. The parts:
  read_fields(page)        GENERIC page reader: every visible, enabled control with its
                           question text, kind, required flag, options (verbatim, opened
                           when they live behind a button), current value and a locator.
  ask_model(...)           one local-model call per page (backends.OllamaBackend, JSON
                           schema with one property per field; choice values are enums).
  guard(...)               fail closed: required + unknown, ungrounded free text,
                           sensitive values not from the profile.
  fill(...)                the generic primitives (apply/browser.py) + prompt/date glue.

No personal value is hard-coded here: the profile (data/applicant.yaml), the resume
(data/resume.pdf) and the mailbox login are read at run time and never printed.
Sensitive profile values are redacted from the prompt (template rule "S = never sent
to the AI model"); the model names the profile key and the program fills the value.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import time
from pathlib import Path
from typing import Any, Optional

import yaml

from jobscraper import backends
from jobscraper.apply import browser as B

# ------------------------------------------------------------------ inputs

SENSITIVE = {
    "identity.date_of_birth", "identity.gender", "singapore_status.residency_status",
    "singapore_status.ns_status", "singapore_status.ord_date", "singapore_status.race",
    "singapore_status.race_other", "singapore_status.religion",
    "singapore_status.marital_status", "singapore_status.nric_last4",
    "us_self_id.eeo_gender", "us_self_id.eeo_race_ethnicity", "us_self_id.veteran_status",
    "us_self_id.disability_status", "declarations.health_disclosure",
}
SENSITIVE_LABEL = re.compile(
    r"date of birth|birth ?date|\bdob\b|gender|\bsex\b|race|ethnic|religio|nric|"
    r"national id|identity (card|number)|disabilit|veteran|marital|pronoun", re.I)

STANDING = """STANDING FACTS (always true for this applicant; owner decisions D-55, D-75):
- Declarations: every declaration question is answered "No": politically exposed person (PEP), conflict of interest, audit independence conflict, shareholding in the company, relatives working at the company, criminal record/convictions, bankruptcy, regulatory or disciplinary action, non-compete or restrictive agreement.
- Work rights: the applicant is legally authorised to work in every country asked about and does NOT need visa or work-permit sponsorship anywhere.
- Health / medical questions: decline to answer ("prefer not to say" / "decline").
- The applicant has never worked for this employer before and is not a current employee.
- How the applicant heard about the job: the employer's careers website."""


def _placeholder_experience(e: dict) -> bool:
    """The template's example row ("Example Pte Ltd") is not the owner's history."""
    return str(e.get("employer", "")).strip().lower().startswith("example ")


def load_profile(path: str) -> tuple[dict, dict, str]:
    """(full profile, sensitive values by key, redacted profile text for the prompt).

    Lenient normalisation (D-78): enum strings lower-cased, YAML booleans kept.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    raw.pop("version", None)
    raw["experience"] = [e for e in (raw.get("experience") or []) if not _placeholder_experience(e)]
    sens: dict[str, Any] = {}
    red: dict[str, Any] = json.loads(json.dumps(raw, default=str))
    for key in SENSITIVE:
        a, b = key.split(".")
        if isinstance(red.get(a), dict) and b in red[a]:
            v = red[a][b]
            sens[key] = v.strip().lower() if isinstance(v, str) and b not in ("nric_last4", "date_of_birth", "ord_date") else v
            red[a][b] = f"<SENSITIVE:{key}>" if v not in ("", None) else ""
    # drop empty values so the model is not tempted by blanks
    def prune(x):
        if isinstance(x, dict):
            return {k: prune(v) for k, v in x.items() if v not in ("", None, [], {})}
        if isinstance(x, list):
            return [prune(v) for v in x]
        return x
    red = prune(red)
    if not red.get("experience"):
        red["experience_note"] = "No work history in the profile: take it from the RESUME."
    return raw, sens, yaml.safe_dump(red, sort_keys=False, allow_unicode=True)


# ------------------------------------------------------------------ the generic reader

READER_JS = r"""
() => {
  const vis = el => { if (!el || !el.isConnected) return false; const r = el.getBoundingClientRect();
    const st = getComputedStyle(el); return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  const txt = el => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const uniq = a => [...new Set(a.filter(Boolean))];
  const ffOf = el => el.closest('[data-automation-id^="formField-"]') || el.closest('fieldset') || el.closest('[role="group"]');
  const labelOf = el => {
    const parts = [];
    const lb = el.getAttribute('aria-labelledby');
    if (lb) lb.split(/\s+/).forEach(id => { const e = document.getElementById(id); if (e && e !== el) parts.push(txt(e)); });
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) parts.push(txt(l)); }
    if (!parts.length) { const ff = ffOf(el); if (ff) { const l = ff.querySelector('legend, label'); if (l) parts.push(txt(l)); } }
    if (!parts.length && el.getAttribute('aria-label')) parts.push(el.getAttribute('aria-label'));
    if (!parts.length && el.placeholder) parts.push(el.placeholder);
    return uniq(parts).join(' | ');
  };
  const sectionOf = el => {
    const out = []; let a = el.parentElement;
    while (a && a !== document.body && out.length < 2) {
      let h = null;
      if (a.getAttribute && a.getAttribute('role') === 'group' && a.getAttribute('aria-labelledby')) {
        const e = document.getElementById(a.getAttribute('aria-labelledby').split(/\s+/)[0]); if (e) h = txt(e);
      }
      if (!h) { const c = a.querySelector(':scope > h2, :scope > h3, :scope > h4, :scope > div > h3, :scope > div > h4, :scope > [role="heading"]'); if (c) h = txt(c); }
      if (h && !out.includes(h)) out.push(h);
      a = a.parentElement;
    }
    return out.reverse().join(' > ');
  };
  const reqOf = (el, label) => el.getAttribute('aria-required') === 'true' || el.required ||
    /\*\s*$/.test(label) || !!(ffOf(el) && ffOf(el).querySelector('abbr[title="required"], abbr'));
  const honeypot = el => {
    const s = ((el.getAttribute('data-automation-id') || '') + ' ' + (el.name || '') + ' ' + labelOf(el)).toLowerCase();
    return s.includes('beecatcher') || s.includes('for robots') || s.includes('honeypot');
  };
  const fields = []; let n = 0;
  const mark = el => { let id = el.getAttribute('data-llmfill'); if (!id) { id = 'f' + (++n) + '_' + Math.random().toString(36).slice(2, 6); el.setAttribute('data-llmfill', id); } return id; };
  document.querySelectorAll('[data-llmfill]').forEach(e => e.removeAttribute('data-llmfill'));
  const done = new Set();
  const base = (el, kind, extra) => {
    const label = labelOf(el);
    return Object.assign({ id: mark(el), kind, label: label.replace(/\*\s*$/, '').trim(), section: sectionOf(el),
      required: reqOf(el, label), automation_id: (ffOf(el) || el).getAttribute('data-automation-id') || '',
      html_id: el.id || '' }, extra || {});
  };
  // date groups (segmented spinbuttons) first
  document.querySelectorAll('[role="spinbutton"], input[data-automation-id^="dateSection"]').forEach(sb => {
    if (done.has(sb) || !vis(sb) || sb.disabled) return;
    const g = ffOf(sb) || sb.parentElement;
    const parts = [...g.querySelectorAll('[role="spinbutton"], input[data-automation-id^="dateSection"]')].filter(vis);
    parts.forEach(p => done.add(p));
    const names = parts.map(p => (p.getAttribute('aria-label') || p.getAttribute('data-automation-id') || '').replace(/dateSection|-input/g, ''));
    const vals = parts.map(p => p.value || '');      // aria-valuetext holds the MM/DD/YYYY placeholder
    const f = base(g, 'date', { parts: names, current: vals.some(Boolean) ? vals.join('/') : '' });
    f.label = f.label || labelOf(parts[0]);
    fields.push(f);
  });
  document.querySelectorAll('input, textarea, select, button[aria-haspopup="listbox"]').forEach(el => {
    if (done.has(el)) return;
    if (el.closest('header, nav, footer, [role="banner"], [role="navigation"], [role="contentinfo"], [data-automation-id="header"], [data-automation-id="utilityButtonBar"]')) return;
    const t = (el.type || '').toLowerCase();
    if (el.tagName === 'INPUT' && ['hidden', 'submit', 'button', 'image', 'reset'].includes(t)) return;
    if (t === 'file') { if (el.disabled) return; done.add(el); fields.push(base(el, 'file', { current: el.files && el.files.length ? el.files[0].name : '' })); return; }
    if (!vis(el) || el.disabled || el.readOnly) return;
    if (honeypot(el)) { done.add(el); return; }
    if (t === 'password') { done.add(el); return; }
    if (t === 'radio') {
      const g = el.closest('fieldset') || el.closest('[role="radiogroup"]') || ffOf(el) || el.parentElement;
      if (done.has(g)) return; done.add(g);
      const radios = [...g.querySelectorAll('input[type="radio"]')].filter(r => vis(r) || vis(r.parentElement));
      const optText = r => { const l = r.id && document.querySelector(`label[for="${CSS.escape(r.id)}"]`); return l ? txt(l) : (r.getAttribute('aria-label') || r.value); };
      const legend = g.querySelector('legend') ? txt(g.querySelector('legend')) : labelOf(g);
      const checked = radios.find(r => r.checked);
      const f = base(g, 'radio', { options: radios.map(optText), current: checked ? optText(checked) : '' });
      f.label = legend.replace(/\*\s*$/, '').trim(); f.required = f.required || /\*/.test(legend) || radios.some(r => r.required || r.getAttribute('aria-required') === 'true');
      fields.push(f); return;
    }
    if (t === 'checkbox') { done.add(el); fields.push(base(el, 'checkbox', { current: el.checked ? 'checked' : 'unchecked' })); return; }
    if (el.tagName === 'SELECT') { done.add(el); fields.push(base(el, 'select', { options: [...el.options].map(o => o.text.trim()).filter(Boolean), current: el.selectedIndex >= 0 ? el.options[el.selectedIndex].text.trim() : '' })); return; }
    if (el.tagName === 'BUTTON') { done.add(el); const cur = txt(el); fields.push(base(el, 'listbox', { current: /^select one$/i.test(cur) ? '' : cur, options: null })); return; }
    if (el.tagName === 'TEXTAREA') { done.add(el); fields.push(base(el, 'textarea', { current: el.value })); return; }
    // searchable prompt / combobox inputs
    const ff = ffOf(el);
    if (el.getAttribute('data-uxi-widget-type') === 'selectinput' || el.getAttribute('role') === 'combobox') {
      done.add(el);
      const pills = ff ? [...ff.querySelectorAll('[data-automation-id="selectedItem"]')].map(p => p.getAttribute('title') ||
        (p.getAttribute('aria-label') || '').replace(/,\s*press delete.*$/i, '') || txt(p)) : [];
      fields.push(base(el, 'prompt', { current: uniq(pills).join('; '), options: null, multi: !!(ff && ff.querySelector('[data-automation-id="multiSelectContainer"], [data-automation-id="selectedItemList"]')) }));
      return;
    }
    done.add(el); fields.push(base(el, 'text', { current: el.value, input_type: t }));
  });
  return fields;
}
"""

OPTION_SEL = ('[role="listbox"]:visible [role="option"], '
              '[data-automation-id="promptOption"]:visible')


OPTS_JS = r"""
() => { const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const out = [];
  document.querySelectorAll('[role="listbox"] [role="option"], [data-automation-id="promptOption"]').forEach(e => {
    if (!vis(e) || e.closest('[data-automation-id="selectedItemList"]')) return;   // chosen pills are not options
    const t = (e.getAttribute('data-automation-label') || e.innerText || '').replace(/\s+/g, ' ').trim();
    if (t && !out.includes(t) && !/^no items\.?$/i.test(t)) out.push(t);
  });
  return out.slice(0, 400); }
"""


def _visible_options(page) -> list[str]:
    try:
        return page.evaluate(OPTS_JS)
    except Exception:
        return []


CATS_JS = r"""
() => [...document.querySelectorAll('[role="listbox"] [role="option"], [data-automation-id="promptOption"]')]
  .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !e.closest('[data-automation-id="selectedItemList"]'); })
  .filter(e => !!e.querySelector('svg[class*="chevron-right"], [data-automation-id*="chevron"]'))
  .map(e => (e.getAttribute('data-automation-label') || e.innerText || '').replace(/\s+/g, ' ').trim())
"""


def _expand_categories(page, loc, top: list[str]) -> list[str]:
    """Hierarchical prompt: options with a right chevron open a sub-list. Read one
    level down and return 'Category > Leaf' paths (leaves kept as they are)."""
    try:
        cats = page.evaluate(CATS_JS)
    except Exception:
        cats = []
    if not cats:
        return top
    out = [o for o in top if o not in cats]
    for cat in cats:
        try:
            page.keyboard.press("Escape")
            loc.click(timeout=4000)
            page.wait_for_timeout(600)
            o = _option_loc(page, cat)
            if o is None:
                continue
            o.click()
            page.wait_for_timeout(900)
            kids = [k for k in _visible_options(page) if k != cat and k not in top]
            out += [f"{cat} > {k}" for k in kids] or [cat]
        except Exception:
            out.append(cat)
    page.keyboard.press("Escape")
    return out


def _option_loc(page, choice: str):
    """The visible option with exactly this text (not a chosen pill)."""
    loc = page.locator(OPTION_SEL)
    want = B.norm_text(choice)
    for i in range(min(loc.count(), 400)):
        o = loc.nth(i)
        try:
            if o.evaluate("e => !!e.closest('[data-automation-id=\"selectedItemList\"]')"):
                continue
            t = o.get_attribute("data-automation-label") or o.inner_text() or ""
        except Exception:
            continue
        if B.norm_text(t) == want:
            return o
    return None


def read_fields(page) -> list[dict]:
    """The generic read, then the options that live behind a button or a prompt
    (opened, read, closed with Escape; nothing is chosen)."""
    fields = page.evaluate(READER_JS)
    for f in fields:
        if f["kind"] not in ("listbox", "prompt"):
            continue
        loc = page.locator(f'[data-llmfill="{f["id"]}"]')
        try:
            loc.click(timeout=4000)
            page.wait_for_timeout(700)
            opts = _visible_options(page)
            if f["kind"] == "listbox":
                opts = [o for o in opts if not re.fullmatch(r"select one", o, re.I)]
            elif opts:
                opts = _expand_categories(page, loc, opts)
            f["options"] = opts
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
        except Exception as exc:
            f["options"] = []
            f["read_error"] = type(exc).__name__
    return fields


# ------------------------------------------------------------------ the model

SYSTEM = """You fill in one page of a job application form for ONE applicant, field by field.
Use ONLY these sources: PROFILE (the applicant's own data file), RESUME (the applicant's resume text), STANDING FACTS, JOB.
For every field id give:
- value: the answer. For a field with options, copy ONE option exactly (or "" when none fits). Checkbox: "checked" or "unchecked". Date: ISO "YYYY-MM-DD", "YYYY-MM" or "YYYY" to match the field's parts. Phone number without the country code when the form has a separate country code field.
- source: "profile" | "resume" | "standing" | "keep_prefilled" | "unknown".
- profile_key: the dotted PROFILE key you used (e.g. contact.city), else "".
- evidence: a short verbatim quote (<= 12 words) from the source that supports the value.
Rules:
1. Never invent. If the sources do not contain the answer, source="unknown", value="".
2. A field's "current" value was prefilled by the site from the resume. If it agrees with the sources keep it: source="keep_prefilled", value=current. If it is wrong, give the correct value with its real source.
3. Sensitive data (date of birth, gender, race/ethnicity, religion, national ID, disability, veteran, marital status, residency status): PROFILE shows <SENSITIVE:key>. Answer source="profile", profile_key=that key, value="" (the program fills the real value). Never guess these.
4. Prefer the RESUME for education, work history, skills and dates; prefer PROFILE for contact details, address, work rights, salary, availability, consents.
5. Terms / privacy / consent checkboxes: follow PROFILE consents. Talent-pool / marketing opt-ins: follow PROFILE (unchecked when false).
6. Optional fields you have no data for: source="unknown", value="". Do not pad free-text fields.
7. Put only the part that belongs in each field: a job title without the company or team name, a company name without the title.
8. A sub-question about one entry (a job's location, a language's proficiency level) must use facts stated FOR THAT ENTRY. The applicant's home location is not a job's location. A language level comes from PROFILE languages (native/fluent -> the highest level); a language that is not in PROFILE languages has an unknown level."""


def _field_schema(f: dict) -> dict:
    opts = f.get("options")
    if f["kind"] == "checkbox":
        val = {"type": "string", "enum": ["checked", "unchecked", ""]}
    elif opts and len(opts) > LONG_LIST:
        val = {"type": "string"}          # long list: say it in words, pick_option matches it
    elif f["kind"] in ("radio", "select", "listbox") and opts:
        val = {"type": "string", "enum": list(dict.fromkeys(opts + [""]))}
    elif f["kind"] == "prompt" and opts and not f.get("multi_free"):
        cur = [c.strip() for c in str(f.get("current") or "").split(";") if c.strip()]
        val = {"type": "string", "enum": list(dict.fromkeys(opts + cur + [""]))}
    else:
        val = {"type": "string"}
    return {"type": "object", "properties": {
        "value": val,
        "source": {"type": "string", "enum": ["profile", "resume", "standing", "keep_prefilled", "unknown"]},
        "profile_key": {"type": "string"},
        "evidence": {"type": "string"}},
        "required": ["value", "source", "profile_key", "evidence"]}


def _field_view(f: dict) -> dict:
    v = {"id": f["id"], "question": f["label"], "kind": f["kind"], "required": f["required"]}
    if f.get("section"):
        v["section"] = f["section"]
    if f.get("current"):
        v["current"] = f["current"]
    if f.get("options") and len(f["options"]) <= LONG_LIST:
        v["options"] = f["options"]
    elif f.get("options"):
        v["note_options"] = (f"{len(f['options'])} options (e.g. {f['options'][:5]}): give the answer in "
                             "plain words from the sources; the program matches it to the list")
    if f.get("parts"):
        v["parts"] = f["parts"]
    if f["kind"] == "prompt":
        v["note"] = ("searchable list: give the option text to search for and pick"
                     + (" (several allowed, separate with ';')" if f.get("multi") else ""))
    if f.get("error"):
        v["site_error"] = f["error"]
    return v


def ask_model(backend, fields: list[dict], profile_text: str, resume_text: str,
              job: dict, log_path: Optional[Path] = None, extra: str = "") -> tuple[dict, dict]:
    asked = [f for f in fields if f["kind"] != "file"]
    if not asked:
        return {}, {"latency_s": 0, "input_tokens": 0, "output_tokens": 0, "done_reason": "no_call",
                    "n_fields": 0, "model": backend.model_id}
    schema ={"type": "object", "properties": {f["id"]: _field_schema(f) for f in asked},
              "required": [f["id"] for f in asked]}
    today = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=8))).strftime("%Y-%m-%d")
    user = (f"JOB:\n{json.dumps(job, ensure_ascii=False)}\n\n{STANDING}\n- Today's date is {today} "
            f"(use it where a form asks for today's date, e.g. next to a declaration).\n\nPROFILE (YAML):\n{profile_text}\n"
            f"RESUME (text):\n{resume_text}\n\n{extra}"
            f"FIELDS (JSON):\n{json.dumps([_field_view(f) for f in asked], ensure_ascii=False, indent=1)}\n\n"
            "Answer with one JSON object keyed by field id.")
    t0 = time.monotonic()
    comp = backend.complete(SYSTEM, user, max_tokens=8000, format=schema, timeout=900)
    dt = time.monotonic() - t0
    try:
        answers = json.loads(comp.text)
    except ValueError:
        answers = {}
    meta = {"latency_s": round(dt, 1), "input_tokens": comp.input_tokens,
            "output_tokens": comp.output_tokens, "done_reason": comp.done_reason,
            "n_fields": len(asked), "model": backend.model_id}
    if log_path:
        log_path.write_text(json.dumps({"system": SYSTEM, "user": user, "schema": schema,
                                        "raw": comp.text, "meta": meta}, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    return answers, meta


LONG_LIST = 15


def resolve_choices(backend, fields: list[dict], answers: dict) -> None:
    """A value for a long list is matched to one option: exact first, else a
    focused one-field model call (pick_option). Recorded as matched_by."""
    for f in fields:
        a = answers.get(f["id"])
        opts = f.get("options") or []
        if not a or not opts or not a.get("value") or a.get("source") == "unknown":
            continue
        v = a["value"]
        exact = next((o for o in opts if B.norm_text(o) == B.norm_text(v)
                      or B.norm_text(o.split(" > ")[-1]) == B.norm_text(v)), None)
        if exact:
            a["value"], a["matched_by"] = exact, "exact"
            continue
        if a.get("source") == "keep_prefilled" and v == f.get("current"):
            continue
        got = pick_option(backend, f["label"], v, opts)
        a["said"], a["value"], a["matched_by"] = v, got, "pick_option"


def pick_option(backend, question: str, target: str, options: list[str]) -> str:
    """Second-stage pick for searchable lists: which listed option is `target`?"""
    if not options:
        return ""
    schema = {"type": "object", "properties": {"option": {"type": "string", "enum": options + [""]}},
              "required": ["option"]}
    comp = backend.complete(
        "Pick the one option that means the same as the wanted answer for the question. "
        "Copy it exactly. If none means the same, answer \"\".",
        json.dumps({"question": question, "wanted": target, "options": options}, ensure_ascii=False),
        max_tokens=200, format=schema, timeout=120)
    try:
        return json.loads(comp.text).get("option", "")
    except ValueError:
        return ""


# ------------------------------------------------------------------ guards

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9@.+]+", " ", B.norm_text(s)).strip()


def _tokens(s: str) -> list[str]:
    return [t for t in _norm(s).split() if len(t) > 1]


def grounded(text: str, corpus_tokens: set, need: float) -> bool:
    toks = _tokens(text)
    if not toks:
        return False
    return sum(t in corpus_tokens for t in toks) / len(toks) >= need


SYN = {
    "male": ["male", "man"], "female": ["female", "woman"], "non_binary": ["non binary", "non-binary"],
    "decline": ["prefer not", "decline", "do not wish", "don't wish", "not wish", "choose not",
                "not to disclose", "not to say", "rather not", "not declared", "not specified"],
    "citizen": ["citizen"], "pr": ["permanent resident"], "foreigner": ["foreigner", "foreign"],
    "single": ["single"], "married": ["married"], "no": ["no"], "yes": ["yes"],
    "not_a_veteran": ["not a protected veteran", "not a veteran", "i am not"],
    "indian": ["indian"], "chinese": ["chinese"], "malay": ["malay"], "eurasian": ["eurasian"],
    "completed": ["completed"], "serving": ["serving"], "exempted": ["exempt"],
}


def map_sensitive(value: Any, options: Optional[list[str]]) -> str:
    """The profile's sensitive value -> an option, deterministically (never inferred)."""
    if isinstance(value, bool):
        value = "yes" if value else "no"
    v = str(value or "").strip()
    if not options:
        return v
    want = SYN.get(v.lower(), [v.lower()])
    nopts = [(o, _norm(o)) for o in options]
    for w in want:                                  # option starting with the word
        hits = [o for o, n in nopts if n == _norm(w) or n.startswith(_norm(w) + " ")]
        if len(hits) == 1:
            return hits[0]
    for w in want:                                  # option containing it as a word
        hits = [o for o, n in nopts if re.search(rf"\b{re.escape(_norm(w))}\b", n)]
        if len(hits) == 1:
            return hits[0]
    return ""


def guard(fields: list[dict], answers: dict, sens: dict, corpus: str) -> tuple[list[dict], list[str]]:
    """Merge model answers into fill decisions; return (decisions, stop_reasons)."""
    ctoks = set(_tokens(corpus))
    out, stops = [], []
    for f in fields:
        if f["kind"] == "file":
            out.append({**_pub(f), "value": "", "source": "glue", "evidence": "", "action": "skip_file"})
            continue
        a = answers.get(f["id"]) or {}
        val, src = str(a.get("value", "") or ""), a.get("source", "unknown")
        key, ev = str(a.get("profile_key", "") or ""), str(a.get("evidence", "") or "")
        d = {**_pub(f), "value": val, "source": src, "profile_key": key, "evidence": ev,
             "action": "fill", "flags": []}
        sensitive = SENSITIVE_LABEL.search(f["label"] or "") or key in SENSITIVE
        if sensitive and f["kind"] != "checkbox":
            if key in SENSITIVE and sens.get(key) not in (None, ""):
                mapped = map_sensitive(sens[key], f.get("options"))
                d["value"], d["source"] = mapped, "profile" if mapped else "unknown"
                d["flags"].append("sensitive_from_profile" if mapped else "sensitive_no_option_match")
                d["evidence"] = f"<{key}>"
            elif src == "keep_prefilled" and f.get("current"):
                d["flags"].append("sensitive_kept_prefilled")
            else:
                d["value"], d["source"] = "", "unknown"
                d["flags"].append("sensitive_not_in_profile")
        if d["source"] == "keep_prefilled":
            if not f.get("current"):
                d["source"], d["value"] = "unknown", ""
            else:
                d["value"], d["action"] = f["current"], "keep"
        if (d["source"] == "unknown" and f["kind"] in ("text", "textarea") and f.get("current")
                and not f["required"]):
            d["value"], d["action"] = "", "clear"      # a prefilled value nothing supports goes
            d["flags"].append("cleared_unsupported_prefill")
            out.append(d)
            continue
        if d["source"] == "unknown" or (d["value"] == "" and d["action"] != "keep"):
            d["action"] = "skip"
            if f["required"] and not f.get("current"):
                stops.append(f"required field unanswered: {f['label']!r} ({f['kind']})")
            out.append(d)
            continue
        # grounding for free text the model wrote itself
        if f["kind"] in ("text", "textarea") and d["action"] == "fill" and "sensitive_from_profile" not in d["flags"]:
            ev_ok = grounded(ev, ctoks, 0.8)
            val_ok = grounded(val, ctoks, 0.6) or bool(re.fullmatch(r"[\d +()-]+", val))
            if not (ev_ok and val_ok):
                d["flags"].append(f"ungrounded(ev={ev_ok},val={val_ok})")
                if f["required"]:
                    stops.append(f"required free text not grounded: {f['label']!r}")
                d["action"] = "skip"
        if f["kind"] == "checkbox" and d["value"] == "checked" and not f["required"]:
            d["flags"].append("optional_checkbox_ticked")
        if d["action"] == "fill" and d["value"] == (f.get("current") or ""):
            d["action"] = "keep"
        if d["action"] == "fill" and f["kind"] == "date" and _same_date(d["value"], f.get("current") or ""):
            d["action"] = "keep"
        out.append(d)
    return out, stops


def _same_date(iso: str, shown: str) -> bool:
    """'2026-03' vs Workday's '3/2026' (month/year parts joined with '/')."""
    a = [int(x) for x in re.findall(r"\d+", iso or "")]
    b = [int(x) for x in re.findall(r"\d+", shown or "")]
    if not a or not b:
        return False
    return sorted(a) == sorted(b)


def _pub(f: dict) -> dict:
    return {k: f.get(k) for k in ("id", "kind", "label", "section", "required", "current",
                                  "options", "automation_id", "parts")}


# ------------------------------------------------------------------ fill

def _type_date(page, loc, value: str, parts: list[str]) -> bool:
    m = re.fullmatch(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", value.strip())
    if not m:
        return False
    y, mo, d = m.group(1), m.group(2) or "01", m.group(3) or "01"
    spins = loc.locator('[role="spinbutton"], input[data-automation-id^="dateSection"]')
    try:
        for i in range(spins.count()):
            nm = (parts[i] if i < len(parts) else "").lower()
            s = spins.nth(i)
            v = y if "year" in nm else mo if "month" in nm else d if "day" in nm else ""
            if not v:
                return False
            try:
                s.click(timeout=2000)
            except Exception:          # Workday lays a dateSection*-display div over the input
                s.evaluate("e => e.focus()")
            page.keyboard.type(v, delay=60)
            page.wait_for_timeout(150)
        page.keyboard.press("Tab")
        return True
    except Exception:
        return False


def _choose_prompt(page, backend, loc, f: dict, value: str) -> bool:
    """Searchable prompt: for each wanted item, type it, pick the option the model
    confirms (exact match first), follow sub-lists up to 3 levels. A 'Category > Leaf'
    path (from the reader's expansion) is clicked level by level. Wrong pills are
    removed first; success = the leaf shows as a chosen pill."""
    ff = loc.locator('xpath=ancestor::*[starts-with(@data-automation-id,"formField-")][1]')
    pills = ff.locator('[data-automation-id="selectedItem"]')

    def pill_texts():
        return [B.norm_text(re.sub(r",\s*press delete.*$", "", pills.nth(i).get_attribute("aria-label") or "", flags=re.I))
                for i in range(pills.count())]
    wants = [w.strip() for w in value.split(";") if w.strip()] or [value]
    leaves = [B.norm_text(w.split(" > ")[-1]) for w in wants]
    if sorted(pill_texts()) == sorted(leaves):
        return True
    for _ in range(pills.count()):                    # clear what is wrong
        charm = pills.first.locator('[data-automation-id="DELETE_charm"]')
        (charm.first if charm.count() else pills.first).click()
        page.wait_for_timeout(400)
    ok = True
    for want in wants:
        try:
            loc.click(timeout=4000)
            page.wait_for_timeout(500)
            opts = _visible_options(page)
            path = [p.strip() for p in want.split(" > ")]
            if len(path) > 1 and _option_loc(page, path[0]) is not None:
                for part in path:
                    o = _option_loc(page, part)
                    if o is None:
                        break
                    o.click()
                    page.wait_for_timeout(900)
                page.keyboard.press("Escape")
                ok = ok and B.norm_text(path[-1]) in pill_texts()
                continue
            want = path[-1]
            if not any(B.norm_text(o) == B.norm_text(want) for o in opts):
                loc.fill("")
                loc.press_sequentially(want[:40], delay=40)
                page.keyboard.press("Enter")          # Workday prompts search on Enter
                page.wait_for_timeout(1500)
                opts = _visible_options(page)
            picked = False
            for _level in range(3):
                choice = next((o for o in opts if B.norm_text(o) == B.norm_text(want)), "") \
                    or pick_option(backend, f["label"], want, opts)
                if not choice:
                    break
                target = _option_loc(page, choice)
                if target is None:
                    break
                target.click()
                page.wait_for_timeout(1000)
                after = _visible_options(page)
                if after and after != opts and choice not in after:
                    opts = after                      # a sub-list opened
                    continue
                picked = True
                break
            page.keyboard.press("Escape")
            ok = ok and picked and bool(pills.count())
        except Exception:
            ok = False
    return ok


RESUME_WORDS = re.compile(r"resume|r[ée]sum[ée]|\bcv\b|curriculum|drop (off )?your|autofill", re.I)


def file_decision(page, d: dict, title: str, resume_path: str) -> None:
    """File inputs never reach the model: a resume slot gets the resume (once)."""
    ctx = " ".join([d.get("label") or "", d.get("section") or "", d.get("automation_id") or "", title])
    try:
        body = page.evaluate("() => document.body.innerText")
    except Exception:
        body = ""
    name = Path(resume_path).name
    if not RESUME_WORDS.search(ctx) and not RESUME_WORDS.search(body[:3000]):
        d.update(action="skip", source="unknown", evidence="not a resume slot")
        return
    if d.get("current") or re.search(re.escape(name), body, re.I):
        d.update(action="keep", source="keep_prefilled", evidence="resume already attached")
        return
    d.update(action="fill", value=resume_path, source="profile", evidence="documents.resume / data/resume.pdf")


def fill(page, backend, decisions: list[dict]) -> None:
    for d in decisions:
        if d["action"] == "clear":
            loc = page.locator(f'[data-llmfill="{d["id"]}"]').first
            d["filled"] = "ok" if B.fill_text(loc, "") else "FAILED"
            continue
        if d["action"] != "fill":
            d["filled"] = d["action"]
            continue
        if d["kind"] == "file":
            ok = B.upload(page.locator(f'[data-llmfill="{d["id"]}"]').first, d["value"], timeout_ms=30000)
            page.wait_for_timeout(3000)
            if not ok:      # Workday empties input.files after its own upload; the name shows instead
                ok = Path(d["value"]).name.lower() in (page.evaluate("() => document.body.innerText") or "").lower()
            d["filled"] = "ok" if ok else "FAILED"
            continue
        loc = page.locator(f'[data-llmfill="{d["id"]}"]').first
        k, v = d["kind"], d["value"]
        ok = False
        try:
            loc.scroll_into_view_if_needed(timeout=3000)
            if k in ("text", "textarea"):
                ok = B.fill_text(loc, v)
                try:
                    loc.press("Tab")
                except Exception:
                    pass
            elif k == "select":
                ok = B.choose_native(loc, v)
            elif k == "listbox":
                ok = B.choose_listbox(page, loc, v)
            elif k == "radio":
                ok = B.choose_radio(loc, v)
            elif k == "checkbox":
                inp = loc
                ok = B.set_checkbox(inp, v == "checked")
                if not ok:                                  # styled box: click its label
                    lab = page.locator(f'label[for="{loc.get_attribute("id")}"]')
                    if lab.count():
                        lab.first.click()
                        ok = inp.is_checked() == (v == "checked")
            elif k == "date":
                ok = _type_date(page, loc, v, d.get("parts") or [])
            elif k == "prompt":
                ok = _choose_prompt(page, backend, loc, d, v)
        except Exception as exc:
            d["fill_error"] = type(exc).__name__
        d["filled"] = "ok" if ok else "FAILED"
        page.wait_for_timeout(250)


# ------------------------------------------------------------------ page facts

ERRORS_JS = r"""
() => {
  const txt = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const out = [];
  document.querySelectorAll('[data-automation-id="inputAlert"], [data-automation-id="errorMessage"], [data-automation-id="errorBanner"] li, [role="alert"]').forEach(e => {
    const t = txt(e); if (!t || /page is loaded$/i.test(t)) return;
    let field = null; const p = e.id ? document.querySelector(`[aria-describedby~="${CSS.escape(e.id)}"]`) : null;
    const host = p || (e.closest('[data-automation-id^="formField-"]') || {}).querySelector?.('[data-llmfill]') || null;
    if (host) field = host.getAttribute('data-llmfill') || (host.closest('[data-llmfill]') || {}).getAttribute?.('data-llmfill') || null;
    out.push({ text: t, field });
  });
  return out;
}
"""

BOTCHECK_JS = r"""
() => !!document.querySelector('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], iframe[title*="challenge" i], .g-recaptcha, .h-captcha, .cf-turnstile, #px-captcha')
"""


def page_title(page) -> str:
    try:
        t = page.evaluate("""() => { const c = document.querySelector('[data-automation-id="progressBarActiveStep"]');
          const h = document.querySelector('h2'); return ((c && c.innerText) || (h && h.innerText) || document.title || '').replace(/\\s+/g,' ').trim(); }""")
    except Exception:
        t = ""
    return re.sub(r"^(current )?step \d+ of \d+\s*", "", t, flags=re.I)


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_backend():
    return backends.OllamaBackend(model="qwen3:14b", timeout=900, num_ctx=32768)
