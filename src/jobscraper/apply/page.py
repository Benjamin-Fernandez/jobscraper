"""The generic page reader (D-78; llm_fill_design.md §3.1, §3.3; WP-R1).

One reader for every ATS: it turns what a person sees on a form page into
`PageField`s (contracts v5). Site modules only navigate (`SiteNavigator`); they
never read or fill fields, so a new ATS needs no reader change (LF §9.4).
Ported from the S-5b prototype (`spikes/llm_fill/llmfill.py` READER_JS,
read_fields, _expand_categories, ERRORS_JS), then the LF rules applied:
date sections by their values, honeypots dropped, help text, context and entry
groups, and value provenance.

    read_page(page, *, scope, sections, origin, known, step) -> list[PageField]
    field_errors(page, *, scope) -> {reader key: error text}  ("" = not tied to a field)
    entry_sections(page, scope) -> list[EntrySection]          the generic default
    page_text(page, scope) -> str                              visible text (review check, L1)
    scan_required(page, scope) -> keys                         required fields empty or in error (H7)
    audit_keys(page, fields, step) -> {reader key: "<step>:<site id>[#n]"}  (AD §6)
    click(page, loc) -> str                                    click with the Workday
                                                               click_filter fallbacks
    shown_contains(shown, values) -> bool                      TR-1 / review H4 helper

Keys. Each field's key is the reader's mark `data-llmfill="f<n>_<token>"` on the
control (the group container for radios, checkbox groups and dates). A mark
stays on its element across reads, so a re-read after our own fills (review
H7) keeps the keys of the fields it saw before and gives new keys only to
fields that appeared; `FormField.locator` is the CSS that finds the mark.
Limit (review F6): a site that re-creates an element (React re-render) drops
the mark, so the re-read gives that field a new reader key. Hence `known` may
also be keyed by audit key (site id based, survives a re-render), and a field
in a repeated entry gets its entry's index (`#<n>`, AD §6), so a field revealed
between two entries does not renumber them. What stays the caller's job (R3):
store each field's audit key the first time it is seen and key its own
records (origins, decisions, uploads) by it as well as by the reader key; an
ungrouped repeat keeps an ordinal `#n` that can shift when a same-id field
appears before it, and a slug(label) key changes if the label does.

Reading never chooses anything: lists that live behind a button or a search
box are opened, read and closed with Escape. No Enter key, no typing.

Field encoding notes for the model side (lane M) and `pagefill`:
  - DATE fields list their sections in `field.options`, in page order, as
    `Option(label=<the section's name>, value="day"|"month"|"year"|"")`;
    `date_parts(pf)` returns the roles. They are not choices.
  - `shown` for a date is the section values joined with "/" in page order
    ("3/2026"); `date_iso(pf)` turns it into "2026-03".
  - `context` is set on every field (the previous field's label in the same
    entry group, else the same section); LF §12.1 uses it for generic labels.
"""
from __future__ import annotations

import logging
import random
import re
from dataclasses import replace as _replace
from typing import Any, Iterable, Mapping, Optional, Sequence

from . import browser as B
from .contracts import (
    EntryGroup, EntrySection, FieldType, FormField, Option, PageField, Value, ValueOrigin,
)

_LOG = logging.getLogger(__name__)
MAX_OPTIONS = 400             # LF §3.1: lists are read up to this many options
DESCRIPTION_MAX = 300          # LF §3.1: help text cut
OPEN_WAIT_MS = 1500            # how long a just-opened list may take to show its options

# Widget families whose options appear only when the control is opened.
DYNAMIC_WIDGETS = frozenset({"aria_listbox", "prompt", "react_select", "combobox"})

# Option texts that are placeholders, not answers ("Select One", "Please select", "--").
PLACEHOLDER_RE = re.compile(
    r"^(select( one| an option| one or more)?|please select( one| an option)?|choose( one| an option)?|"
    r"-+|none selected|no items|no options|no results( found)?|type to search|loading)\s*(\.{1,3}|…)?$", re.I)

# The section names of contracts `EntrySection.section`, by heading words.
SECTION_WORDS = (
    ("work_experience", re.compile(r"\b(work|employment|experience|job|position)s?\b", re.I)),
    ("education", re.compile(r"\b(education|school|universit\w*|degree|qualification)s?\b", re.I)),
    ("languages", re.compile(r"\blanguages?\b", re.I)),
    ("websites", re.compile(r"\b(websites?|links?|urls?|social)\b", re.I)),
    ("certifications", re.compile(r"\b(certificat\w*|licen[cs]es?)\b", re.I)),
)

# ------------------------------------------------------------------ shared JS helpers

# Plain JS functions shared by every evaluate below (each evaluate is self-contained).
HELPERS_JS = r"""
  const EXCL = 'header, nav, footer, [role="banner"], [role="navigation"], [role="contentinfo"]';
  const CTRL = 'input:not([type="hidden"]), textarea, select, button[aria-haspopup="listbox"], ' +
               '[role="combobox"], [role="spinbutton"], [role="radio"], [role="checkbox"]';
  const DATE_SEL = '[role="spinbutton"], input[data-automation-id^="dateSection"]';
  const ERR_SEL = '[data-automation-id="inputAlert"], [data-automation-id="errorMessage"], [role="alert"], ' +
                  '.helper-text--error, [class*="error-message"], [class*="errorMessage"], [class*="field-error"], ' +
                  '[id$="-error"], [id$="_error"]';
  const HELP_SEL = '[data-automation-id*="helpText" i], [data-automation-id*="instruction" i], ' +
                   '[class*="help-text" i], [class*="helpText"], [class*="description" i], [class*="hint" i]';
  const PLACEHOLDER = /^(select( one| an option| one or more)?|please select( one| an option)?|choose( one| an option)?|-+|none selected)\s*(\.{1,3}|…)?$/i;
  const FILE_RE = /[\w][^\s\/\\]*\.(?:pdf|docx?|txt|rtf|odt)\b/i;
  const txt = el => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const vis = el => {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    if (r.right + window.scrollX <= -500 || r.bottom + window.scrollY <= -500) return false;   // parked off-page
    const st = getComputedStyle(el);
    return st.visibility !== 'hidden' && st.display !== 'none';
  };
  const ctlVis = el => vis(el) || [...(el.labels || [])].some(vis) || vis(el.parentElement);
  const isDate = el => el.matches(DATE_SEL);
  const isRadio = el => (el.type || '').toLowerCase() === 'radio' || el.getAttribute('role') === 'radio';
  const isCheck = el => (el.type || '').toLowerCase() === 'checkbox' || el.getAttribute('role') === 'checkbox';
  const labelText = l => {
    if (!l) return '';
    if (!l.querySelector('input, select, textarea, [role="listbox"]')) return txt(l);
    const c = l.cloneNode(true);
    c.querySelectorAll('input, select, textarea, [role="listbox"], [role="option"]').forEach(x => x.remove());
    return (c.textContent || '').replace(/\s+/g, ' ').trim();
  };
  // The field's container: the largest ancestor that holds no other field (a Workday
  // formField-*, a fieldset or a radiogroup ends the walk at once).
  const containerOf = (el, unit) => {
    unit = unit || [el];
    const ours = c => unit.includes(c) || unit.some(u => u.contains(c));
    const only = a => [...a.querySelectorAll(CTRL)].every(c => ours(c) || (!vis(c) && (c.type || '') !== 'file'));
    let best = null, a = el.parentElement, depth = 0;
    while (a && a !== document.body && depth < 8) {
      if (!only(a)) break;
      best = a;
      if (a.matches('[data-automation-id^="formField-"], fieldset, [role="radiogroup"]')) return a;
      a = a.parentElement; depth++;
    }
    return best || el;
  };
  const idText = ids => (ids || '').split(/\s+/).filter(Boolean).map(id => document.getElementById(id)).filter(Boolean);
  // LF §3.1 label order: aria-labelledby, label[for] (or a wrapping label), the container's
  // legend/label, aria-label, placeholder.
  const labelOf = (el, cont) => {
    const lb = idText(el.getAttribute('aria-labelledby')).filter(e => e !== el && !e.contains(el)).map(txt).filter(Boolean);
    if (lb.length) return [...new Set(lb)].join(' ');
    const ls = [...(el.labels || [])].map(labelText).filter(Boolean);
    if (ls.length) return ls[0];
    const c = cont || containerOf(el);
    if (c) {
      const l = c.matches('fieldset') && c.querySelector(':scope > legend') ? c.querySelector(':scope > legend') : c.querySelector('legend, label');
      const t = labelText(l); if (t) return t;
    }
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
    if (el.placeholder) return el.placeholder.trim();
    return '';
  };
  const cleanLabel = s => (s || '').replace(/\s*\*\s*$/, '').replace(/\s*\(required\)\s*$/i, '').trim();
  const reqOf = (el, rawLabel, cont, unit) => {
    unit = unit || [el];
    if (unit.some(u => u.getAttribute('aria-required') === 'true' || u.required)) return true;
    if (el.getAttribute('aria-required') === 'true') return true;
    if (/\*\s*$/.test(rawLabel) || /\(required\)\s*$/i.test(rawLabel)) return true;
    if (cont && (cont.getAttribute('aria-required') === 'true' ||
                 cont.querySelector('abbr[title*="required" i], [aria-label="required" i]'))) return true;
    return false;
  };
  const isErr = e => e.matches(ERR_SEL);
  const errorOf = (el, cont, unit) => {
    unit = unit || [el];
    const out = [];
    const add = e => { const t = txt(e); if (t && !/page is loaded$/i.test(t) && !out.includes(t)) out.push(t); };
    unit.concat([el]).forEach(u => idText(u.getAttribute('aria-describedby')).filter(isErr).forEach(add));
    if (cont) cont.querySelectorAll(ERR_SEL).forEach(e => { if (!e.querySelector(CTRL) && vis(e)) add(e); });
    if (!out.length && unit.concat([el]).some(u => u.getAttribute('aria-invalid') === 'true')) out.push('The site marks this field as invalid.');
    return out.join(' ');
  };
  const helpOf = (el, cont, unit, labelEls) => {
    unit = unit || [el];
    const out = [];
    const add = e => { if (!e || isErr(e) || labelEls.includes(e) || e.querySelector(CTRL)) return; const t = txt(e); if (t && !out.includes(t)) out.push(t); };
    unit.concat([el]).forEach(u => idText(u.getAttribute('aria-describedby')).forEach(add));
    if (!out.length && cont) cont.querySelectorAll(HELP_SEL).forEach(e => { if (vis(e)) add(e); });
    return out.join(' ').slice(0, %DESC%);
  };
  const sectionOf = el => {
    const out = []; let a = el.parentElement;
    while (a && a !== document.body && out.length < 2) {
      let h = null;
      if (a.getAttribute && a.getAttribute('role') === 'group' && a.getAttribute('aria-labelledby')) {
        const e = idText(a.getAttribute('aria-labelledby'))[0]; if (e) h = txt(e);
      }
      if (!h) {
        const c = a.querySelector(':scope > h2, :scope > h3, :scope > h4, :scope > div > h3, :scope > div > h4, :scope > [role="heading"], :scope > legend');
        if (c && !c.contains(el)) h = txt(c);
      }
      if (h && !out.includes(h)) out.push(h);
      a = a.parentElement;
    }
    return out.reverse().join(' > ');
  };
  const radioText = r => {
    const ls = [...(r.labels || [])].map(labelText).filter(Boolean);
    if (ls.length) return ls[0];
    if (r.getAttribute('aria-label')) return r.getAttribute('aria-label').trim();
    const lb = idText(r.getAttribute('aria-labelledby')).map(txt).filter(Boolean);
    if (lb.length) return lb.join(' ');
    return r.tagName === 'INPUT' ? (r.value || '') : txt(r);
  };
  const isOn = r => r.tagName === 'INPUT' ? !!r.checked : r.getAttribute('aria-checked') === 'true';
  const unitOf = (el, widget) => {
    if (widget === 'radio' || widget === 'checkbox_group') {
      const sel = widget === 'radio' ? 'input[type="radio"], [role="radio"]' : 'input[type="checkbox"], [role="checkbox"]';
      return [...el.querySelectorAll(sel)].filter(ctlVis);
    }
    if (widget === 'segmented_date') return [...el.querySelectorAll(DATE_SEL)].filter(vis);
    return [el];
  };
  const pillsOf = cont => cont ? [...cont.querySelectorAll('[data-automation-id="selectedItem"]')].map(p =>
      p.getAttribute('title') || (p.getAttribute('aria-label') || '').replace(/,\s*press delete.*$/i, '') || txt(p))
      .map(s => s.trim()).filter(Boolean) : [];
  const reactCtl = el => el.closest('.select__control') || (el.closest('.select__container, [class*="select__container"]') || {}).querySelector?.('.select__control') || null;
  const fileName = (el, cont) => {
    const fs = el.files && el.files.length ? el.files[0].name : '';
    if (fs) return fs;
    const m = (cont ? txt(cont) : '').match(FILE_RE);
    return m ? m[0] : '';
  };
  // What the field shows now (LF §3.1 "Shown value"); `multi` -> a list.
  const shownOf = (el, widget, multi) => {
    const cont = el.__llmCont || containerOf(el, unitOf(el, widget));
    switch (widget) {
      case 'segmented_date': {
        const vals = unitOf(el, widget).map(p => (p.value || '').trim());   // never aria-valuetext (it holds MM/DD/YYYY)
        return vals.some(Boolean) ? vals.join('/') : '';
      }
      case 'file': return fileName(el, cont);
      case 'native_select': {
        const sel = [...el.selectedOptions || []].filter(o => !(o.value === '' && o.index === 0) && !PLACEHOLDER.test(o.text.trim()) && o.text.trim());
        const t = sel.map(o => o.text.replace(/\s+/g, ' ').trim());
        return el.multiple ? t : (t[0] || '');
      }
      case 'aria_listbox': { const t = txt(el); return PLACEHOLDER.test(t) ? '' : t; }
      case 'prompt': { const p = [...new Set(pillsOf(cont))]; return multi ? p : (p[0] || ''); }
      case 'react_select': {
        const ctl = reactCtl(el);
        if (multi) return ctl ? [...ctl.querySelectorAll('.select__multi-value__label')].map(txt).filter(Boolean) : [];
        const s = ctl && ctl.querySelector('.select__single-value');
        return s ? txt(s) : '';
      }
      case 'radio': { const on = unitOf(el, widget).find(isOn); return on ? radioText(on) : ''; }
      case 'checkbox': return isOn(el) ? 'true' : 'false';
      case 'checkbox_group': return unitOf(el, widget).filter(isOn).map(radioText);
      default: return el.value == null ? '' : String(el.value);
    }
  };
""".replace("%DESC%", str(DESCRIPTION_MAX))

# The reader (LF §3.1). Returns one record per field in page order.
READER_JS = "(arg) => {" + HELPERS_JS + r"""
  const root = arg.scope ? document.querySelector(arg.scope) : document.body;
  if (!root) return [];
  const excluded = el => { const x = el.closest(EXCL); return !!x && (root === document.body || root.contains(x)) && x !== root; };
  const honeypot = (el, label) => {
    if (el.closest('[data-automation-id="beecatcher"]')) return true;
    const s = [el.getAttribute('data-automation-id'), el.name, el.id, label].join(' ').toLowerCase();
    return /beecatcher|for robots|honey ?pot|honey_pot|honey-pot/.test(s);
  };
  const resolve = loc => {
    try {
      if (/^xpath=/.test(loc) || /^\(?\//.test(loc)) {
        const xp = loc.replace(/^xpath=/, '');
        return document.evaluate(xp, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
      }
      return document.querySelector(loc.replace(/^css=/, ''));
    } catch (e) { return null; }
  };
  const groups = (arg.groups || []).map(g => Object.assign({}, g, { el: resolve(g.locator) })).filter(g => g.el);
  const groupOf = el => { let best = null; groups.forEach(g => { if (g.el.contains(el) && (!best || best.el.contains(g.el))) best = g; }); return best; };
  // Marks: kept across reads (stable keys); new elements continue the numbering.
  let n = 0;
  document.querySelectorAll('[data-llmfill]').forEach(e => { const m = /^f(\d+)_/.exec(e.getAttribute('data-llmfill') || ''); if (m) n = Math.max(n, +m[1]); });
  const mark = el => { let id = el.getAttribute('data-llmfill'); if (!id) { id = 'f' + (++n) + '_' + arg.token; el.setAttribute('data-llmfill', id); } return id; };
  const fields = [];
  const done = new Set();
  const push = (el, widget, kind, extra, unit, labelSrc) => {
    unit = unit || [el];
    const cont = containerOf(labelSrc || el, unit);
    el.__llmCont = cont;
    const raw = (extra && extra.rawLabel != null) ? extra.rawLabel : labelOf(labelSrc || el, cont);
    const labelEls = [...((labelSrc || el).labels || [])].concat(idText((labelSrc || el).getAttribute('aria-labelledby')));
    const label = cleanLabel(raw);
    if (honeypot(labelSrc || el, label)) { unit.forEach(u => done.add(u)); done.add(el); return; }
    const g = groupOf(el);
    const multi = kind === 'multi_choice';
    const rec = Object.assign({
      id: mark(el), widget, kind, label, section: sectionOf(el), required: reqOf(labelSrc || el, raw, cont, unit),
      description: helpOf(labelSrc || el, cont, unit, labelEls), error: errorOf(labelSrc || el, cont, unit),
      shown: shownOf(el, widget, multi), options: [], parts: [],
      group: g ? g.id : '', group_title: g ? g.title : '',
      max_length: (el.maxLength && el.maxLength > 0 && el.maxLength < 1000000) ? el.maxLength : null,
    }, extra || {});
    delete rec.rawLabel;
    delete el.__llmCont;
    fields.push(rec);
    unit.forEach(u => done.add(u)); done.add(el);
  };
  const dateGroup = sb => {
    // the largest ancestor whose date sections have distinct roles and no other control
    const role = p => { const s = ((p.getAttribute('aria-label') || '') + ' ' + (p.getAttribute('data-automation-id') || '')).toLowerCase();
      return /day/.test(s) ? 'day' : /month/.test(s) ? 'month' : /year/.test(s) ? 'year' : ''; };
    let g = sb.parentElement, best = sb.parentElement, depth = 0;
    while (g && g !== root.parentElement && depth < 6) {
      const parts = [...g.querySelectorAll(DATE_SEL)].filter(vis);
      const roles = parts.map(role);
      const others = [...g.querySelectorAll(CTRL)].filter(c => !isDate(c) && vis(c));
      if (others.length || new Set(roles).size !== roles.length) break;
      best = g;
      if (g.matches('[data-automation-id^="formField-"], fieldset, [role="group"]')) break;
      g = g.parentElement; depth++;
    }
    const parts = [...best.querySelectorAll(DATE_SEL)].filter(vis);
    return { g: best, parts, roles: parts.map(role) };
  };
  const radioGroup = el => {
    const fs = el.closest('fieldset, [role="radiogroup"]');
    if (fs) return fs;
    let a = el.parentElement, depth = 0;
    const sel = 'input[type="radio"], [role="radio"]';
    const named = el.name ? [...root.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`)] : [];
    while (a && a !== root.parentElement && depth < 6) {
      const rs = [...a.querySelectorAll(sel)];
      if (named.length ? named.every(r => a.contains(r)) : rs.length > 1) return a.matches('[data-automation-id^="formField-"]') ? a : (a.closest('[data-automation-id^="formField-"]') && a.closest('[data-automation-id^="formField-"]').querySelectorAll(sel).length === rs.length ? a.closest('[data-automation-id^="formField-"]') : a);
      a = a.parentElement; depth++;
    }
    return el.parentElement;
  };
  const checkGroup = el => {
    const g = el.closest('fieldset, [role="group"], [data-automation-id^="formField-"]');
    if (!g || !root.contains(g)) return null;
    const boxes = [...g.querySelectorAll('input[type="checkbox"], [role="checkbox"]')].filter(ctlVis);
    if (boxes.length < 2) return null;
    const others = [...g.querySelectorAll(CTRL)].filter(c => !isCheck(c) && vis(c));
    if (others.length) return null;
    const head = g.matches('fieldset') ? g.querySelector(':scope > legend') : (idText(g.getAttribute('aria-labelledby'))[0] || g.querySelector('legend, [id*="label" i], label:not([for])'));
    const ht = head ? txt(head) : '';
    if (!ht || boxes.some(b => radioText(b) === ht)) return null;
    return { g, boxes, head: ht };
  };
  // The question of a radio group that has no legend: a label in the group that is no
  // option's label, else the group's own text without the options, else the text just before it.
  const groupQuestion = (g, unit) => {
    const optLabels = new Set(unit.flatMap(r => [...(r.labels || [])]));
    const own = [...g.querySelectorAll('legend, label')].find(l => !optLabels.has(l) && !unit.some(r => l.contains(r)) && txt(l));
    if (own) return txt(own);
    const c = g.cloneNode(true);
    c.querySelectorAll('label, input, select, textarea, button, [role="radio"], [role="checkbox"], ' + ERR_SEL).forEach(x => x.remove());
    const t = (c.textContent || '').replace(/\s+/g, ' ').trim();
    if (t) return t.slice(0, 300);
    const prev = g.previousElementSibling;
    if (prev && !prev.querySelector(CTRL) && txt(prev)) return txt(prev).slice(0, 300);
    return labelOf(g, containerOf(g, unit.concat([g])));
  };
  // The visible control that opens a hidden file input: a visible label for it, or a visible
  // button next to it (same parent) that is no other field's control and no submit/reset
  // (review N6a F4). The parent must be a field-like container, not the form or page wrapper
  // that also holds the Submit button.
  // Q-93 (D-175): a button counts only if it says it picks a file (its text, aria-label or
  // title names attach/upload/browse/choose/select/file/resume/CV/curriculum/document; "replace"
  // and "change" only beside a file word) or points at this input (aria-controls = its id); a
  // "Cancel" or "Help" button beside a hidden input proves nothing. Unicode-aware word edges so
  // "Résumé" matches (the ASCII word boundary would not); an icon-only button stays out.
  const FILE_WORDS = /(?<!\p{L})(files?|r[eé]sum[eé]|cv|documents?)(?!\p{L})/iu;
  const PICK_WORDS = /(?<!\p{L})(attach\p{L}*|upload\p{L}*|browse|choose|select|curriculum)(?!\p{L})/iu;
  const SWAP_WORDS = /(?<!\p{L})(replace|change)(?!\p{L})/iu;
  const pickText = t => FILE_WORDS.test(t) || PICK_WORDS.test(t) || (SWAP_WORDS.test(t) && FILE_WORDS.test(t));
  const pickerButton = (c, el) => vis(c) && c.matches('button, [role="button"]') && !c.matches(CTRL) &&
    !['submit', 'reset'].includes(c.type || '') &&
    (pickText([txt(c), c.getAttribute('aria-label') || '', c.getAttribute('title') || ''].join(' ')) ||
     !!(el && el.id && c.getAttribute('aria-controls') === el.id));
  const fileTrigger = el => {
    if ([...(el.labels || [])].some(vis)) return true;
    const p = el.parentElement;
    if (!p || p.matches('form, main, body')) return false;
    return [...p.children].some(c => c !== el && ((pickerButton(c, el))
      || (vis(c) && c.tagName === 'LABEL' && c.htmlFor === el.id && el.id)));
  };
  // A hidden file input's label: the first label in its parent that names no other control.
  const fileLabel = el => {
    const p = el.parentElement;
    const l = p && [...p.querySelectorAll('label, legend')].find(x => !x.htmlFor && !x.querySelector(CTRL) && txt(x));
    return l ? txt(l) : '';
  };
  const CAND = CTRL + ', input[type="file"]';
  const skips = [];
  for (const el of root.querySelectorAll(CAND)) {
    if (done.has(el) || excluded(el)) continue;
    const tag = el.tagName, t = (el.type || '').toLowerCase(), role = el.getAttribute('role');
    if (tag === 'INPUT' && ['hidden', 'submit', 'button', 'image', 'reset', 'password'].includes(t)) { done.add(el); continue; }
    const off = el.disabled || el.getAttribute('aria-disabled') === 'true';
    if (isDate(el)) {
      if (!vis(el) || off) continue;
      const d = dateGroup(el);
      d.parts.forEach(p => done.add(p));
      const opts = d.parts.map((p, i) => ({ label: (p.getAttribute('aria-label') || (p.getAttribute('data-automation-id') || '').replace(/^dateSection|-input$/g, '')).trim(), value: d.roles[i] }));
      push(d.g, 'segmented_date', 'date', { options: opts }, d.parts, d.parts[0]);
      continue;
    }
    if (t === 'file') {
      if (off) continue;
      const cont = containerOf(el);
      // A display:none file input is the target of a visible control (Greenhouse: an
      // "Attach" button next to it, or a label[for]); any other hidden input stays out.
      // A visible container alone proves nothing (N6a F4): it must hold a picker button.
      const trigger = !vis(el) && (fileTrigger(el) || (vis(cont) && [...cont.querySelectorAll('button, [role="button"]')].some(c => pickerButton(c, el))));
      if (!(vis(el) || trigger)) {
        // Q-93 review M2: a hidden file input with no picker control is left out; say so (label only).
        skips.push({ skipped: 'file', label: cleanLabel(labelOf(el, cont) || fileLabel(el) || '').slice(0, 80) });
        continue;
      }
      // Its label is the field's own label (no label[for] points at a hidden input).
      const own = labelOf(el, cont) ? null : fileLabel(el);
      push(el, 'file', 'file', own ? { rawLabel: own } : undefined);
      continue;
    }
    if (tag === 'SELECT') {
      if (!vis(el) || off) continue;
      const opts = [...el.options].filter((o, i) => o.text.trim() && !(o.value === '' && i === 0) && !PLACEHOLDER.test(o.text.trim()))
                     .map(o => ({ label: o.text.replace(/\s+/g, ' ').trim(), value: o.value }));
      push(el, 'native_select', el.multiple ? 'multi_choice' : 'dropdown', { options: opts });
      continue;
    }
    if (tag === 'BUTTON' || (role === 'combobox' && !['INPUT', 'TEXTAREA'].includes(tag))) {
      if (tag !== 'BUTTON' && el.querySelector('input, textarea')) continue;       // its inner input is the field
      if (!vis(el) || off) continue;
      push(el, 'aria_listbox', 'dropdown');
      continue;
    }
    if (isRadio(el)) {
      if (!ctlVis(el) || off) continue;
      const g = radioGroup(el);
      if (done.has(g)) { done.add(el); continue; }
      const unit = [...g.querySelectorAll('input[type="radio"], [role="radio"]')].filter(ctlVis);
      const legend = g.matches('fieldset') && g.querySelector(':scope > legend') ? txt(g.querySelector(':scope > legend'))
                   : (idText(g.getAttribute('aria-labelledby')).map(txt).join(' ') || groupQuestion(g, unit));
      push(g, 'radio', 'radio', { options: unit.map(r => ({ label: radioText(r), value: r.value || '' })), rawLabel: legend }, unit);
      continue;
    }
    if (isCheck(el)) {
      if (!ctlVis(el) || off) continue;
      const cg = checkGroup(el);
      if (cg) {
        push(cg.g, 'checkbox_group', 'multi_choice', { options: cg.boxes.map(b => ({ label: radioText(b), value: b.value || '' })), rawLabel: cg.head }, cg.boxes);
        continue;
      }
      push(el, 'checkbox', 'checkbox', { rawLabel: radioText(el) || labelOf(el) });
      continue;
    }
    // inputs and textareas
    const ctl = reactCtl(el);
    const visible = vis(el) || (ctl && vis(ctl));
    if (!visible || off) continue;
    const ff = el.closest('[data-automation-id^="formField-"]');
    if (el.getAttribute('data-uxi-widget-type') === 'selectinput' ||
        (ff && ff.querySelector('[data-automation-id="multiSelectContainer"], [data-automation-id="selectedItemList"]'))) {
      const cont = containerOf(el);
      const pills = [...new Set(pillsOf(cont))];
      push(el, 'prompt', pills.length >= 2 ? 'multi_choice' : 'typeahead');
      continue;
    }
    if (ctl || /\bselect__input\b/.test(el.className || '')) {
      const multi = !!(ctl && ctl.querySelector('.select__value-container--is-multi'));
      push(el, 'react_select', multi ? 'multi_choice' : 'typeahead');
      continue;
    }
    if (el.readOnly || el.getAttribute('aria-readonly') === 'true') continue;
    if (role === 'combobox' || ['list', 'both'].includes((el.getAttribute('aria-autocomplete') || '').toLowerCase())) {
      push(el, 'combobox', 'typeahead');
      continue;
    }
    if (tag === 'TEXTAREA') { push(el, 'text', 'textarea'); continue; }
    const kinds = { email: 'email', tel: 'phone', url: 'url', number: 'number', date: 'date', month: 'date' };
    const extra = {};
    if (t === 'date') extra.options = [{ label: 'Year', value: 'year' }, { label: 'Month', value: 'month' }, { label: 'Day', value: 'day' }];
    if (t === 'month') extra.options = [{ label: 'Year', value: 'year' }, { label: 'Month', value: 'month' }];
    push(el, 'text', kinds[t] || 'text', extra);
  }
  return fields.concat(skips);
}
"""

# One field's shown value / error (read-back; widgets.read, widgets.error).
SHOWN_JS = "(el, arg) => {" + HELPERS_JS + r"""
  return shownOf(el, arg.widget, !!arg.multi);
}
"""

FIELD_ERROR_JS = "(el, arg) => {" + HELPERS_JS + r"""
  const unit = unitOf(el, arg.widget);
  const src = arg.widget === 'segmented_date' && unit.length ? unit[0] : el;
  return errorOf(src, containerOf(src, unit), unit);
}
"""

# Every error message on the page and the field it belongs to (S-5: inputAlert + aria-invalid).
ERRORS_JS = "(arg) => {" + HELPERS_JS + r"""
  const root = arg.scope ? (document.querySelector(arg.scope) || document.body) : document.body;
  const out = [];
  const keyOf = e => {
    const host = e.id ? document.querySelector(`[aria-describedby~="${CSS.escape(e.id)}"]`) : null;
    if (host) { const m = host.closest('[data-llmfill]'); if (m) return m.getAttribute('data-llmfill'); }
    let a = e.parentElement, depth = 0;
    while (a && a !== document.body && depth < 8) {
      if (a.hasAttribute('data-llmfill')) return a.getAttribute('data-llmfill');
      const marks = [...a.querySelectorAll('[data-llmfill]')];
      if (marks.length === 1) return marks[0].getAttribute('data-llmfill');
      if (marks.length > 1) return '';
      a = a.parentElement; depth++;
    }
    return '';
  };
  root.querySelectorAll(ERR_SEL + ', [data-automation-id="errorBanner"] li').forEach(e => {
    if (e.querySelector(CTRL) || !vis(e)) return;
    const t = txt(e);
    if (!t || /page is loaded$/i.test(t)) return;
    out.push({ key: keyOf(e), text: t });
  });
  root.querySelectorAll('[data-llmfill]').forEach(m => {
    const unit = [m].concat([...m.querySelectorAll('input, select, textarea, [role]')]);
    if (unit.some(u => u.getAttribute('aria-invalid') === 'true')) out.push({ key: m.getAttribute('data-llmfill'), text: '', invalid: true });
  });
  return out;
}
"""

# Visible options of whatever list is open now (not chosen pills; placeholders dropped).
OPTIONS_JS = r"""
(max) => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const out = [];
  document.querySelectorAll('[role="listbox"] [role="option"], [data-automation-id="promptOption"], .select__menu [role="option"]').forEach(e => {
    if (!vis(e) || e.closest('[data-automation-id="selectedItemList"]')) return;   // chosen pills are not options
    const t = (e.getAttribute('data-automation-label') || e.innerText || '').replace(/\s+/g, ' ').trim();
    if (t && !out.includes(t)) out.push(t);
  });
  return out.slice(0, max);
}
"""

# Options that open a sub-list (a right chevron): Workday's hierarchical prompts (S-5b).
CATEGORIES_JS = r"""
() => [...document.querySelectorAll('[role="listbox"] [role="option"], [data-automation-id="promptOption"]')]
  .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !e.closest('[data-automation-id="selectedItemList"]'); })
  .filter(e => !!e.querySelector('svg[class*="chevron-right"], [data-automation-id*="chevron"]') || e.getAttribute('aria-haspopup') === 'true')
  .map(e => (e.getAttribute('data-automation-label') || e.innerText || '').replace(/\s+/g, ' ').trim())
"""

# The generic entry_sections (LF §9.1 last row, generic form): numbered headings are entries,
# "Add"/"Add Another" buttons are section add controls, "Delete"/"Remove" in an entry deletes it.
ENTRIES_JS = "(arg) => {" + HELPERS_JS + r"""
  const root = arg.scope ? (document.querySelector(arg.scope) || document.body) : document.body;
  ['data-llmfill-entry', 'data-llmfill-add', 'data-llmfill-del'].forEach(a => document.querySelectorAll(`[${a}]`).forEach(e => e.removeAttribute(a)));
  const HEADS = 'h1, h2, h3, h4, h5, h6, [role="heading"], legend';
  const NUM = /^(.*?\S)\s*#?\s*(\d{1,2})\s*\*?$/;
  const nameOf = b => ((b.getAttribute('aria-label') || '') + ' ' + txt(b)).trim();
  const buttons = [...root.querySelectorAll('button, [role="button"]')].filter(vis);
  const addBtns = buttons.filter(b => /^add( another)?\b/i.test(txt(b)) || /^add( another)?\b/i.test(b.getAttribute('aria-label') || ''));
  const heads = [...root.querySelectorAll(HEADS)].filter(vis);
  const numbered = heads.filter(h => NUM.test(txt(h)));
  const plain = heads.filter(h => !NUM.test(txt(h)));
  const norm = s => (s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').replace(/s\b/g, '').trim();
  const like = (a, b) => { a = norm(a); b = norm(b); return !!a && !!b && (a === b || a.includes(b) || b.includes(a)); };
  // sections from their add buttons: the button's largest ancestor holding no other add
  // button; the title from its aria-label ("Add Work Experience"), else the nearest heading before it
  const sections = [];
  addBtns.forEach((b, i) => {
    let a = b.parentElement, best = b.parentElement;
    while (a && a !== document.body.parentElement) {
      if (addBtns.some(o => o !== b && a.contains(o))) break;
      best = a;
      if (a === root) break;
      a = a.parentElement;
    }
    const before = plain.filter(x => (x.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) && !x.contains(b));
    const nearest = before.length ? before[before.length - 1] : null;
    const fromAria = (b.getAttribute('aria-label') || '').replace(/^add( another)?\s*/i, '').trim();
    const title = fromAria || (nearest ? txt(nearest) : '');
    let el = best;
    if (nearest && best.contains(nearest)) { let c = b.parentElement; while (c && c !== best && !c.contains(nearest)) c = c.parentElement; el = c || best; }
    const sid = 's' + (i + 1);
    b.setAttribute('data-llmfill-add', sid);
    sections.push({ id: sid, el, title: title.replace(/\s*\*\s*$/, ''), required: /\*\s*$/.test(title), add: `[data-llmfill-add="${sid}"]`, entries: [] });
  });
  let k = 0;
  numbered.forEach(h => {
    const m = txt(h).match(NUM);
    if (/\d|\bstep\b|\bof$|\bpage\b/i.test(m[1])) return;           // "Step 2 of 5", "Page 1"
    let panel = null;
    const lab = h.id ? root.querySelector(`[role="group"][aria-labelledby~="${CSS.escape(h.id)}"]`) : null;
    if (lab) panel = lab;
    else if (h.tagName === 'LEGEND') panel = h.parentElement;
    else {
      let a = h.parentElement;
      while (a && a !== root.parentElement) {
        if (numbered.some(o => o !== h && a.contains(o))) break;
        if (addBtns.some(o => a.contains(o))) break;
        if (plain.some(o => a.contains(o) && !o.contains(h))) break;
        if (a.querySelector(CTRL)) panel = a;
        a = a.parentElement;
      }
    }
    if (!panel || !panel.querySelector(CTRL)) return;
    const eid = 'e' + (++k);
    panel.setAttribute('data-llmfill-entry', eid);
    const del = [...panel.querySelectorAll('button, [role="button"]')].filter(vis).find(b => /^(delete|remove)\b/i.test(txt(b)) || /^(delete|remove)\b/i.test(b.getAttribute('aria-label') || ''));
    if (del) del.setAttribute('data-llmfill-del', eid);
    const holding = sections.filter(s => s.el && s.el.contains(panel));
    let sec = holding.find(s => like(s.title, m[1]))
           || sections.find(s => !s.el && s.base === m[1])
           || holding.filter(s => s.el !== root && s.el !== document.body && s.entries.every(e => e.base === m[1]))
                     .sort((x, y) => (x.el.contains(y.el) ? 1 : -1))[0];
    if (!sec) { sec = { id: 'b' + (sections.length + 1), el: null, title: m[1], required: false, add: '', entries: [], base: m[1] }; sections.push(sec); }
    sec.entries.push({ index: +m[2], title: txt(h).replace(/\s*\*\s*$/, ''), base: m[1], locator: `[data-llmfill-entry="${eid}"]`, del: del ? `[data-llmfill-del="${eid}"]` : '' });
  });
  return sections.map(s => ({ title: s.title, required: !!s.required, add: s.add, entries: s.entries,
                              base: s.entries.length ? s.entries[0].base : '' }));
}
"""

PAGE_TEXT_JS = "(arg) => {" + HELPERS_JS + r"""
  const root = arg.scope ? (document.querySelector(arg.scope) || document.body) : document.body;
  if (!root) return '';
  const skip = 'script, style, noscript, template, ' + EXCL;
  const out = [];
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = w.nextNode())) {
    const p = node.parentElement;
    if (!p) continue;
    const x = p.closest(skip);
    if (x && (root === document.body || root.contains(x)) && x !== root) continue;
    if (!p.getClientRects().length) continue;
    const st = getComputedStyle(p);
    if (st.visibility === 'hidden' || st.display === 'none') continue;
    const t = node.nodeValue.replace(/\s+/g, ' ').trim();
    if (t) out.push(t);
  }
  root.querySelectorAll('input:not([type="hidden"]):not([type="password"]), textarea').forEach(e => {
    if (e.closest(skip) || !e.getClientRects().length) return;
    if (['checkbox', 'radio', 'file', 'submit', 'button', 'image', 'reset'].includes((e.type || '').toLowerCase())) return;
    if (e.value) out.push(e.value.replace(/\s+/g, ' ').trim());
  });
  return out.join(' ');
}
"""

AUDIT_IDS_JS = r"""
(keys) => keys.map(k => {
  const el = document.querySelector(`[data-llmfill="${CSS.escape(k)}"]`);
  if (!el) return '';
  const ff = el.closest('[data-automation-id^="formField-"]');
  if (ff) return ff.getAttribute('data-automation-id').replace(/^formField-/, '');
  const inner = el.matches('input, select, textarea, button') ? el : (el.querySelector('input, select, textarea, button') || el);
  const aid = el.getAttribute('data-automation-id') || inner.getAttribute('data-automation-id') || '';
  if (aid) return aid;
  if (inner.name) return inner.name;
  const id = el.id || inner.id || '';
  return /^(input|field|react-select|select|textarea)?[-_:]?\d+[-_]?|^:r|^\d/.test(id) ? '' : id;
})
"""


# ------------------------------------------------------------------ public API

def selector(key: str) -> str:
    """The CSS that finds a field's control (or its group container) by its reader key."""
    return f'[data-llmfill="{key}"]'


def locator(page: Any, field: Any) -> Any:
    """The Playwright locator of a PageField / FormField / key."""
    key = getattr(getattr(field, "field", field), "key", field)
    return page.locator(selector(str(key))).first


def read_page(page: Any, *, scope: str = "", sections: Sequence[EntrySection] = (),
              origin: Any = "", known: Optional[Mapping[str, Any]] = None, step: str = "",
              pre_import: Optional[Mapping[str, str]] = None, options: bool = True,
              rng: Optional[random.Random] = None) -> list[PageField]:
    """Every visible, enabled field inside `scope` (CSS; "" = the page minus header,
    nav, footer and the banner/navigation/contentinfo landmarks), in page order.

    `sections`: the step's entry sections (`nav.entry_sections()`); a field inside
    one of their entries gets `group = "<section>#<index>"` and `group_title`.
    `origin`: who put the values shown on this first read (LF §3.3): the
    ValueOrigin value `choose_entry` returned; "" = `site_default`. A field whose
    key is in `known` keeps that origin instead (a re-read: OURS for what we
    typed, the first read's origin for the rest). `known` may be keyed by reader
    key or by audit key (pass `step`): the reader key wins, the audit key is the
    fallback for an element the site re-created (review F6). Empty values are EMPTY.
    `pre_import` (review M3; `AttemptContext.pre_import`, keyed by audit key
    `<step>:<site id>[#n]`, so pass `step`): a value equal to what the form showed
    before the import is `site_default`, not the import's.
    `options=False` skips opening lists (their options stay empty).
    `rng`: the source of the per-read key token (tests pass a seeded one).
    A page that can't be evaluated (navigating, closed) raises Playwright's error.
    """
    token = "".join((rng or random).choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(4))
    groups = [{"id": f"{s.section}#{g.index}", "title": g.title, "locator": g.locator}
              for s in sections for g in s.entries if g.locator]
    raw = page.evaluate(READER_JS, {"scope": scope, "token": token, "groups": groups}) or []
    for r in [r for r in raw if r.get("skipped")]:           # Q-93 review M2: a trace, no applicant values
        _LOG.info("hidden file input skipped: no picker control%s", f" ({r['label']})" if r.get("label") else "")
    raw = [r for r in raw if not r.get("skipped")]
    site = _origin(origin)
    known = dict(known or {})
    out: list[PageField] = []
    last_label: dict[str, str] = {}
    for r in raw:
        kind = FieldType(r["kind"])
        widget = r["widget"]
        opts = [Option(label=str(o.get("label", "")), value=str(o.get("value", ""))) for o in r.get("options") or []]
        complete = True
        if options and widget in DYNAMIC_WIDGETS:
            labels, complete = collect_options(page, page.locator(selector(r["id"])).first, widget)
            opts = [Option(label=t) for t in labels]
        shown = _value(r.get("shown"), multi=kind is FieldType.MULTI_CHOICE)
        ctx_key = r.get("group") or r.get("section") or ""
        field = FormField(
            key=r["id"], label=r.get("label", ""), type=kind, required=bool(r.get("required")),
            options=tuple(opts), step=step, section=r.get("section", ""),
            description=r.get("description", ""), max_length=r.get("max_length"),
            locator=selector(r["id"]))
        out.append(PageField(
            field=field, widget=widget, shown=shown, origin=_origin_of(r["id"], kind, shown, known, site),
            context=last_label.get(ctx_key, ""), group=r.get("group", ""), group_title=r.get("group_title", ""),
            options_complete=complete, error=r.get("error", "")))
        if field.label:
            last_label[ctx_key] = field.label
    seen = {pf.field.key for pf in out}
    imported = bool(pre_import) and site is not ValueOrigin.SITE_DEFAULT
    akeys = audit_keys(page, out, step) if imported or any(k not in seen for k in known) else {}
    if known and akeys:                       # F6: a re-created element found by its audit key
        out = [_replace(pf, origin=_origin_of(akeys[pf.field.key], pf.field.type, pf.shown, known, site))
               if pf.field.key not in known and akeys.get(pf.field.key) in known else pf for pf in out]
    if imported:
        out = [_replace(pf, origin=ValueOrigin.SITE_DEFAULT)
               if (pf.origin is site and pf.field.key not in known
                   and akeys.get(pf.field.key) not in known
                   and akeys.get(pf.field.key) in pre_import
                   and B.norm_text(_text(pf.shown)) == B.norm_text(pre_import[akeys[pf.field.key]]))
               else pf for pf in out]
    return out


def scan_required(page: Any, scope: str = "") -> tuple[str, ...]:
    """Keys of the visible required fields that are empty (an unticked required box
    counts) or show a site error now: the deterministic check before Next and before
    Submit (LF §8 step 12, "Before Submit"; review H7). Lists are not opened."""
    fields = read_page(page, scope=scope, options=False)
    return tuple(pf.field.key for pf in fields
                 if pf.field.required and (_is_empty(pf.field.type, pf.shown) or pf.error))


def field_errors(page: Any, *, scope: str = "") -> dict[str, str]:
    """Each field's visible error text by reader key (fields marked by an earlier
    `read_page`). Messages tied to no field (an error banner) are joined under "".
    A field the site marks `aria-invalid` without a message gets a generic text."""
    rows = _safe(lambda: page.evaluate(ERRORS_JS, {"scope": scope}), []) or []
    out: dict[str, list[str]] = {}
    for r in rows:
        if r.get("invalid"):
            continue
        out.setdefault(r.get("key") or "", []).append(r.get("text", ""))
    for r in rows:
        if r.get("invalid") and r.get("key") and r["key"] not in out:
            out[r["key"]] = ["The site marks this field as invalid."]
    return {k: " ".join(dict.fromkeys(t for t in v if t)) for k, v in out.items() if any(v)}


def entry_sections(page: Any, scope: str = "") -> list[EntrySection]:
    """Repeated sections (jobs, schools, languages, websites, ...) found by page
    structure: an entry is a panel under a heading ending in a number ("Work
    Experience 2"); its delete control is a button named Delete/Remove in it; a
    section's add control is a button named Add / Add Another. A section with an
    add control and no entries is listed with `entries=()`. Locators are CSS on
    marks this call sets (`data-llmfill-entry`, `-add`, `-del`)."""
    rows = _safe(lambda: page.evaluate(ENTRIES_JS, {"scope": scope}), []) or []
    out: list[EntrySection] = []
    used: dict[str, int] = {}
    for r in rows:
        title = r.get("title") or r.get("base") or ""
        name = section_name(r.get("base") or title)
        raw_entries = r.get("entries") or []
        # A numbered heading alone ("Question 1") is not a repeated entry: an unknown kind
        # of section counts only with an add or a delete control (E3 deletes junk entries).
        if name.startswith("other_") and not r.get("add") and not any(e.get("del") for e in raw_entries):
            continue
        if not raw_entries and not r.get("add"):
            continue
        n = used.get(name, 0)
        used[name] = n + 1
        if n:
            name = f"{name}_{n + 1}"
        entries = tuple(EntryGroup(section=name, index=int(e["index"]), title=e.get("title", ""),
                                   locator=e["locator"], delete_locator=e.get("del", ""))
                        for e in raw_entries)
        out.append(EntrySection(section=name, title=title, add_locator=r.get("add", ""),
                                required=bool(r.get("required")), entries=entries))
    return out


def section_name(title: str) -> str:
    """`work_experience | education | languages | websites | certifications | other_<slug>`."""
    for name, rx in SECTION_WORDS:
        if rx.search(title or ""):
            return name
    return "other_" + (re.sub(r"[^a-z0-9]+", "_", (title or "").lower()).strip("_") or "section")


def page_text(page: Any, scope: str = "") -> str:
    """The visible text inside `scope` (or the page minus header/nav/footer),
    whitespace-collapsed, plus the values of visible text inputs. For the review
    check (LF §8) and the L1 page-text match."""
    return _safe(lambda: page.evaluate(PAGE_TEXT_JS, {"scope": scope}), "") or ""


def audit_keys(page: Any, fields: Sequence[PageField], step: str) -> dict[str, str]:
    """`<step>:<site id>[#n]` per reader key (AD §6 key rules, LF §3.1): the Workday
    formField automation id, else the control's automation id, `name` or a
    hand-written html id, else slug(label). An id that repeats in one step gets
    `#<entry index>` inside a repeated entry (AD §6: stable when another entry or a
    revealed field appears), else `#1`, `#2`, ... in page order; a clash left over
    gets `.1`, `.2`. Computed per read: R3 keeps the first one it saw (F6)."""
    keys = [pf.field.key for pf in fields]
    ids = _safe(lambda: page.evaluate(AUDIT_IDS_JS, keys), None) or [""] * len(keys)
    base = []
    for pf, sid in zip(fields, ids):
        sid = sid or _slug(pf.field.label) or "field"
        base.append(f"{step}:{sid}" if step else sid)
    counts: dict[str, int] = {}
    for b in base:
        counts[b] = counts.get(b, 0) + 1
    ordinal: dict[str, int] = {}
    cand: list[str] = []
    for pf, b in zip(fields, base):
        if counts[b] > 1:
            gi = _group_index(pf.group)
            if gi:
                b = f"{b}#{gi}"
            else:
                ordinal[b] = ordinal.get(b, 0) + 1
                b = f"{b}#{ordinal[b]}"
        cand.append(b)
    again: dict[str, int] = {}
    for c in cand:
        again[c] = again.get(c, 0) + 1
    clash: dict[str, int] = {}
    out: dict[str, str] = {}
    for pf, c in zip(fields, cand):
        if again[c] > 1:
            clash[c] = clash.get(c, 0) + 1
            c = f"{c}.{clash[c]}"
        out[pf.field.key] = c
    return out


def _group_index(group: str) -> int:
    """The entry index of a `<section>#<index>` group ("" or no index -> 0)."""
    tail = (group or "").rpartition("#")[2]
    return int(tail) if tail.isdigit() else 0


# ------------------------------------------------------------------ options (LF §3.1 "Options")

def collect_options(page: Any, loc: Any, widget: str) -> tuple[list[str], bool]:
    """Open the list behind a listbox button / prompt / react-select / combobox, read
    its visible options (≤ MAX_OPTIONS; chosen pills and placeholders excluded),
    expand one level of categories as "Category > Leaf" (prompts, listboxes), close
    it with Escape. Returns (options, complete): complete=False when nothing showed
    (a search-driven list whose options appear only after typing)."""
    try:
        opts = []
        for _attempt in range(2):
            # Blur first: a site that shows a validation message on blur (Workday's
            # inputAlert) moves the page under the click otherwise; one retry if nothing opened.
            blur_active(page)
            if not click(page, loc, timeout_ms=4000):
                return [], False
            opts = B._poll(page, OPEN_WAIT_MS, lambda: _visible_options(page)) or []
            if opts:
                break
        opts = [o for o in opts if not PLACEHOLDER_RE.match(o)]
        if opts and widget in ("prompt", "aria_listbox"):
            opts = expand_categories(page, loc, opts)
        return opts[:MAX_OPTIONS], bool(opts)
    except Exception:
        return [], False
    finally:
        _escape(page)


def expand_categories(page: Any, loc: Any, top: list[str]) -> list[str]:
    """A hierarchical list: options with a right chevron open a sub-list. Read one
    level down; return 'Category > Leaf' paths, leaves kept as they are (S-5b
    failure 1: "How did you hear about us?")."""
    cats = _safe(lambda: page.evaluate(CATEGORIES_JS), []) or []
    if not cats:
        return top
    out = [o for o in top if o not in cats]
    for cat in cats:
        try:
            _escape(page)
            click(page, loc, timeout_ms=4000)
            B._poll(page, OPEN_WAIT_MS, lambda: _visible_options(page))
            o = option_locator(page, cat)
            if o is None:
                out.append(cat)
                continue
            o.click(timeout=4000)
            kids = B._poll(page, OPEN_WAIT_MS, lambda: [k for k in _visible_options(page)
                                                        if k != cat and k not in top]) or []
            kids = [k for k in kids if not PLACEHOLDER_RE.match(k)]
            out += [f"{cat} > {k}" for k in kids] or [cat]
        except Exception:
            out.append(cat)
        if len(out) >= MAX_OPTIONS:
            break
    _escape(page)
    return out[:MAX_OPTIONS]


OPTION_SEL = ('[role="listbox"] [role="option"], [data-automation-id="promptOption"], '
              '.select__menu [role="option"]')


def option_locator(page: Any, text: str) -> Optional[Any]:
    """The visible option whose text equals `text` (normalised), not a chosen pill."""
    want = B.norm_text(text)
    loc = page.locator(OPTION_SEL)
    for i in range(min(_safe(loc.count, 0), MAX_OPTIONS)):
        o = loc.nth(i)
        try:
            if not o.is_visible() or o.evaluate(
                    "e => !!e.closest('[data-automation-id=\"selectedItemList\"]')"):
                continue
            t = o.get_attribute("data-automation-label") or o.inner_text() or ""
        except Exception:
            continue
        if B.norm_text(t) == want:
            return o
    return None


def visible_options(page: Any) -> list[str]:
    """The options of the list open now (public for widgets)."""
    return _visible_options(page)


def _visible_options(page: Any) -> list[str]:
    return _safe(lambda: page.evaluate(OPTIONS_JS, MAX_OPTIONS), []) or []


# ------------------------------------------------------------------ click (S-5 item 2)

CLICK_FALLBACKS = (
    ("click_filter_before", 'xpath=preceding-sibling::div[@data-automation-id="click_filter"][1]'),
    ("click_filter_after", 'xpath=following-sibling::div[@data-automation-id="click_filter"][1]'),
    ("parent", "xpath=.."),
)


def click(page: Any, loc: Any, *, timeout_ms: int = 3000) -> str:
    """Click `loc`; when the click times out (Workday lays a `click_filter` div over
    some controls), click the preceding sibling `div[data-automation-id="click_filter"]`,
    then the following one, then the parent (S-5 item 2; spike `wd_click`). Returns
    how it clicked ("direct", "click_filter_before", "click_filter_after", "parent"),
    "" when nothing could be clicked. Navigators use it too (`widgets.click`)."""
    target = loc.first if hasattr(loc, "first") else loc
    try:
        target.click(timeout=timeout_ms)
        return "direct"
    except Exception:
        pass
    for how, xp in CLICK_FALLBACKS:
        try:
            s = target.locator(xp)
            if s.count():
                s.first.click(timeout=timeout_ms)
                return how
        except Exception:
            continue
    return ""


# ------------------------------------------------------------------ value helpers

def date_parts(pf: PageField) -> list[str]:
    """The roles of a DATE field's sections in page order ("month", "year", ...)."""
    return [o.value for o in pf.field.options] if pf.field.type is FieldType.DATE else []


def date_iso(pf: PageField, shown: Value = None) -> str:
    """A date field's shown value as ISO ("3/2026" with sections month, year -> "2026-03");
    "" when it can't be read."""
    shown = pf.shown if shown is None else shown
    if not isinstance(shown, str) or not shown.strip():
        return ""
    if re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", shown.strip()):
        return shown.strip()
    nums = re.findall(r"\d+", shown)
    roles = date_parts(pf)
    if len(roles) != len(nums) or not all(roles):
        return ""
    got = dict(zip(roles, (int(n) for n in nums)))
    if "year" not in got:
        return ""
    out = f"{got['year']:04d}"
    if "month" in got:
        out += f"-{got['month']:02d}"
        if "day" in got:
            out += f"-{got['day']:02d}"
    return out


def shown_contains(shown: Value, values: Iterable[str]) -> bool:
    """True when the shown value contains any of `values` (TR-1 / review H4: such a
    field's `current` is withheld from the prompt and sent as `current_set`).
    Case-insensitive; a value with 6+ digits (a phone number, a postal code) also
    matches by digits, with or without a country code."""
    parts = shown if isinstance(shown, list) else [shown or ""]
    text = " ".join(str(p) for p in parts)
    low = B.norm_text(text)
    digits = re.sub(r"\D", "", text)
    for v in values:
        v = str(v or "").strip()
        if not v:
            continue
        nv = B.norm_text(v)
        if len(nv) >= 3 and nv in low:
            return True
        dv = re.sub(r"\D", "", v)
        if len(dv) >= 6 and digits:
            if dv in digits or (len(digits) >= 6 and digits in dv):
                return True
    return False


# ------------------------------------------------------------------ internals

def _origin(origin: Any) -> ValueOrigin:
    if isinstance(origin, ValueOrigin):
        return origin if origin is not ValueOrigin.EMPTY else ValueOrigin.SITE_DEFAULT
    try:
        o = ValueOrigin(str(origin or ""))
    except ValueError:
        return ValueOrigin.SITE_DEFAULT
    return o if o is not ValueOrigin.EMPTY else ValueOrigin.SITE_DEFAULT


def _is_empty(kind: FieldType, shown: Value) -> bool:
    if isinstance(shown, list):
        return not shown
    s = (shown or "").strip()
    return not s or (kind is FieldType.CHECKBOX and s == "false")


def _origin_of(key: str, kind: FieldType, shown: Value, known: Mapping[str, Any],
               site: ValueOrigin) -> ValueOrigin:
    if _is_empty(kind, shown):
        return ValueOrigin.EMPTY
    if key in known:
        try:
            o = ValueOrigin(getattr(known[key], "value", known[key]))
        except ValueError:
            o = site
        return site if o is ValueOrigin.EMPTY else o
    return site


def _text(v: Value) -> str:
    return "; ".join(str(x) for x in v) if isinstance(v, list) else str(v or "")


def _value(v: Any, *, multi: bool) -> Value:
    if multi:
        if isinstance(v, list):
            return [str(x) for x in v if str(x).strip()]
        return [v] if v else []
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return "" if v is None else str(v)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:60]


def blur_active(page: Any) -> None:
    """Take focus off whatever has it (the site's blur validation runs now, not
    under the next click)."""
    try:
        page.evaluate("() => { const a = document.activeElement; if (a && a !== document.body && a.blur) a.blur(); }")
        page.wait_for_timeout(50)
    except Exception:
        pass


def _escape(page: Any) -> None:
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
    except Exception:
        pass


def _safe(fn: Any, default: Any) -> Any:
    try:
        return fn()
    except Exception:
        return default
