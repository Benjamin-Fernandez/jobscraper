"""Workday navigator (llm_fill_design §9.1, D-78; apply_design §9.4.1, §9.4.3,
§9.4.4, §9.4.11, §9.4.12; spike S-5 differences (a)-(f)).

Navigation and site structure only: open the posting, take the Apply choice,
handle the account wall, name the step, list the repeated sections, click Next
and Submit, read the confirmation. It never decides or types an answer: reading
and filling fields is generic (apply/page.py, apply/widgets.py,
apply/pagefill.py). The account form is the one place it types, and only the
identity's email and the vault password the flow hands it.

Rules that are MUST here:
  - `next_step` never clicks a button whose text says Submit: on the review page
    it returns `is_review=True` without a click; `submit` is the one click.
  - No Enter key anywhere (review Q-35 M8): Enter in a form input can submit the
    form implicitly, bypassing `submit_clicked_at` (NF-06). Buttons are clicked.
  - Workday hides some buttons behind a sibling `click_filter` div (S-5 a): a
    click that times out is retried on the preceding sibling, then the
    following one, then the parent (`_click`; a private copy until lane R's
    `widgets.click` lands, then removed in WP-N6).
  - The honeypot `beecatcher` input is never touched (S-5 e): only the account
    inputs named by automation id are filled.

Step ids (§9.1, review M7): the active progress-bar title without its "(current)
step N of M" prefix (S-5 d), slugged. Question pages and unknown titles keep the
position N (`questions_4`, `custom_<slug>_5`), so two pages titled "Application
Questions" get different ids and the flow's "same step twice" guard does not
mistake the second for being stuck.
"""
from __future__ import annotations

import re
import time
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from .. import browser as B
from ..classify import PageSignal, classify, visible_text
from ..contracts import (
    ApplyFailure, AttemptContext, EntryGroup, EntrySection, PasswordRules, ReasonCode, Secret,
    SignUpOutcome, StepResult, Tenant, ValueOrigin, WorkdayEntry,
)

# ---------------------------------------------------------------- tenant (AD §9.4.1)

FORM_A = re.compile(
    r"^https?://(?P<tenant>[\w-]+)\.(?P<wd>wd\d+)\.myworkdayjobs\.com"
    r"(?:/[a-z]{2}[-_][a-z]{2})?/(?P<site>[^/?#]+)(?P<rest>/[^?#]*)?", re.I)
FORM_B = re.compile(
    r"^https?://(?P<wd>wd\d+)\.myworkdaysite\.com(?:/[a-z]{2}[-_][a-z]{2})?"
    r"/recruiting/(?P<tenant>[\w-]+)/(?P<site>[^/?#]+)(?P<rest>/[^?#]*)?", re.I)
REQ_SUFFIX = re.compile(r"_(?P<req>[A-Za-z0-9-]+)$")
APPLY_SUFFIX = re.compile(r"/apply(?:/.*)?$", re.I)

# ---------------------------------------------------------------- selectors (S-5 confirmed unless K)

COOKIE_DECLINE = '[data-automation-id="legalNoticeDeclineButton"]'
COOKIE_NAME = re.compile(r"^(decline( all)?|reject( all)?|necessary only|accept necessary"
                         r"( cookies)?|only necessary( cookies)?)$", re.I)
APPLY_BUTTONS = ('[data-automation-id="adventureButton"]',
                 '[data-automation-id="jobPostingApplyButton"]')               # the 2nd: K
APPLY_NAME = re.compile(r"^apply( now)?$", re.I)
ENTRY_DIALOG = '[data-automation-id="wd-popup-frame"]'
ENTRY_IDS = {
    WorkdayEntry.AUTOFILL_WITH_RESUME: "autofillWithResume",
    WorkdayEntry.APPLY_MANUALLY: "applyManually",
    WorkdayEntry.USE_LAST_APPLICATION: "useMyLastApplication",
}
ENTRY_WAIT_S = 10

SIGN_IN_SUBMIT = '[data-automation-id="signInSubmitButton"]'
CREATE_SUBMIT = '[data-automation-id="createAccountSubmitButton"]'
VERIFY_PASSWORD = '[data-automation-id="verifyPassword"]'
EMAIL_INPUT = '[data-automation-id="email"], [data-automation-id="signIn-email"]'
PASSWORD_INPUT = '[data-automation-id="password"], [data-automation-id="signIn-password"]'
CREATE_CHECKBOX = '[data-automation-id="createAccountCheckbox"]'
CREATE_LINK = '[data-automation-id="createAccountLink"]'
SIGN_IN_LINK = '[data-automation-id="signInLink"], [data-automation-id="utilityButtonSignIn"]'
SIGN_IN_NAME = re.compile(r"^sign in$", re.I)
CODE_INPUT = ('input[autocomplete="one-time-code"], input[data-automation-id*="code" i], '
              'input[name*="code" i]')                                         # K: not met in S-5/S-5b
CODE_BUTTON_NAME = re.compile(r"^(verify|continue|confirm)$", re.I)

PROGRESS_BAR = '[data-automation-id="progressBar"]'
ACTIVE_STEP = '[data-automation-id="progressBarActiveStep"]'
FLOW_PAGE = '[data-automation-id="applyFlowPage"]'
NEXT_BUTTONS = ('[data-automation-id="bottom-navigation-next-button"]',
                '[data-automation-id="pageFooterNextButton"]')
NEXT_NAME = re.compile(r"^(save and continue|next)$", re.I)
SUBMIT_NAME = re.compile(r"^submit$", re.I)
SUBMIT_ANY = re.compile(r"submit", re.I)
ERROR_SELECTORS = ('[data-automation-id="inputAlert"], [data-automation-id="errorMessage"], '
                   '[data-automation-id="errorBanner"], [data-automation-id="errorWidgetBar"]')

# Step containers (AD §9.4.5 step 1): only when no progress bar names the step.
STEP_CONTAINERS = (
    ("contactInformationPage", "my_information"), ("myExperiencePage", "my_experience"),
    ("primaryQuestionnairePage", "questions_1"), ("secondaryQuestionnairePage", "questions_2"),
    ("voluntaryDisclosuresPage", "voluntary_disclosures"),
    ("selfIdentificationPage", "self_identify"), ("reviewJobApplicationPage", "review"),
)
STEP_TITLES = {
    "my information": "my_information",
    "my experience": "my_experience",
    "voluntary disclosures": "voluntary_disclosures",
    "self identify": "self_identify",
    "self identification": "self_identify",
    "review": "review",
    "autofill with resume": "autofill_with_resume",
}
QUESTION_TITLES = frozenset({"application questions", "questions", "additional questions",
                             "questionnaire"})
STEP_PREFIX = re.compile(r"^\s*(?:current\s+)?step\s+(\d+)\s+of\s+\d+\s*", re.I)

# Repeated sections (§9.1 entry_sections): automation id, else the heading.
SECTIONS = (
    ("workExperienceSection", "work_experience", "work experience"),
    ("educationSection", "education", "education"),
    ("languageSection", "languages", "languages"),
    ("websiteSection", "websites", "websites"),
    ("certificationSection", "certifications", "certifications"),
)
ENTRY_MARK = "data-jsnav-entry"
DELETE_MARK = "data-jsnav-delete"
ADD_MARK = "data-jsnav-add"

# Account outcomes (AD §9.4.3; S-5: the "already registered" copy was not met).
ALREADY_REGISTERED = re.compile(
    r"already (exists|in use|registered|been registered)|account (already )?exists"
    r"|email address is already|an account with this email", re.I)
LOCKED_TEXT = re.compile(r"locked|too many", re.I)
REJECTED_DETAIL = "The site rejected the saved password."
LOCKED_DETAIL = "The account is locked on this site."

# Confirmation (§9.1 after_submit; AD §9.4.11).
CONFIRM_TEXT = re.compile(r"application (has been )?submitted|thank you for (your )?appl"
                          r"|successfully submitted", re.I)
CONFIRM_URL = "/jobtasks/completed/application"
HOME_STATUS = re.compile(r"submitted|under consideration|application received|in review", re.I)

_SIGNAL_REASON = {
    PageSignal.CAPTCHA: ReasonCode.CAPTCHA,
    PageSignal.BOT_CHALLENGE: ReasonCode.BOT_CHALLENGE,
    PageSignal.TWO_FACTOR: ReasonCode.SMS_OR_2FA,
    PageSignal.CLOSED: ReasonCode.POSTING_CLOSED,
}


def job_url(url: str) -> str:
    """The posting page: the URL without any `/apply…` suffix, query or fragment."""
    p = urlsplit(str(url or "").strip())
    return urlunsplit((p.scheme, p.netloc, APPLY_SUFFIX.sub("", p.path), "", ""))


def entry_choice(offered: set[str] | frozenset[str], setting: str = "auto"
                 ) -> tuple[WorkdayEntry, str]:
    """The Apply choice under D-78 (§9.1 `choose_entry`) and the origin the
    later pages carry. `offered` holds WorkdayEntry values.

    "Autofill with Resume" when offered (the import is always taken; the file
    it reads is the tailored resume); else "Apply Manually". "Use My Last
    Application" is never chosen. `apply.workday_entry: manual` forces Apply
    Manually (opened by URL when the dialog does not offer it). No dialog at
    all → `direct`."""
    if not offered:
        return WorkdayEntry.DIRECT, ValueOrigin.SITE_DEFAULT.value
    if str(setting).strip().lower() != "manual" \
            and WorkdayEntry.AUTOFILL_WITH_RESUME.value in offered:
        return WorkdayEntry.AUTOFILL_WITH_RESUME, ValueOrigin.RESUME_IMPORT.value
    return WorkdayEntry.APPLY_MANUALLY, ValueOrigin.SITE_DEFAULT.value


def _norm_title(text: str) -> str:
    t = B.norm_text(text).replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()


def _slug(text: str, limit: int = 30) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", _norm_title(text))).strip("_")[:limit]


def step_from_title(raw: str) -> str:
    """A progress-bar item's text → step id (pure; §9.1, review M7)."""
    m = STEP_PREFIX.match(raw or "")
    n = m.group(1) if m else ""
    title = _norm_title(STEP_PREFIX.sub("", raw or "", count=1))
    if not title:
        return ""
    if title in STEP_TITLES:
        return STEP_TITLES[title]
    if title in QUESTION_TITLES:
        return f"questions_{n or 1}"
    return f"custom_{_slug(title)}" + (f"_{n}" if n else "")


def _visible(loc: Any) -> bool:
    try:
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False


def _first_visible(loc: Any, limit: int = 10) -> Optional[Any]:
    try:
        n = min(loc.count(), limit)
    except Exception:
        return None
    for i in range(n):
        try:
            if loc.nth(i).is_visible():
                return loc.nth(i)
        except Exception:
            continue
    return None


def _text(loc: Any) -> str:
    try:
        return re.sub(r"\s+", " ", loc.inner_text() or "").strip()
    except Exception:
        try:
            return (loc.get_attribute("aria-label") or "").strip()
        except Exception:
            return ""


def _click(page: Any, loc: Any, timeout_ms: int = 3000) -> str:
    """Click; when it times out, click the preceding sibling `click_filter`, then
    the following one, then the parent (S-5 a; spike `wd_click`). A private
    copy until lane R's `widgets.click` lands (WP-N6 removes it)."""
    try:
        loc.click(timeout=timeout_ms)
        return "direct"
    except Exception:
        pass
    for xp in ('xpath=preceding-sibling::div[@data-automation-id="click_filter"][1]',
               'xpath=following-sibling::div[@data-automation-id="click_filter"][1]',
               'xpath=..'):
        try:
            s = loc.locator(xp)
            if s.count():
                s.first.click(timeout=timeout_ms)
                return xp
        except Exception:
            continue
    raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "workday: a button would not take a click")


def dismiss_cookies(page: Any) -> bool:
    """Decline a cookie banner (S-5 f): `legalNoticeDeclineButton`, else a button
    named Decline / Reject / Necessary only. True when one was clicked."""
    cands = [page.locator(COOKIE_DECLINE)]
    try:
        cands.append(page.get_by_role("button", name=COOKIE_NAME))
    except Exception:
        pass
    for loc in cands:
        btn = _first_visible(loc, 5)
        if btn is None:
            continue
        try:
            btn.click(timeout=3000)
            page.wait_for_timeout(500)
            return True
        except Exception:
            continue
    return False


# Marks each repeated section, its entries and their Add/Delete controls so the
# reader and pagefill get plain CSS locators. Returns [{section, title, required,
# add, entries: [{index, title, mark, delete}]}].
_SECTIONS_JS = r"""
([sections, marks]) => {
  const [ENTRY, DEL, ADD] = marks;
  for (const m of marks) document.querySelectorAll('[' + m + ']').forEach(e => e.removeAttribute(m));
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const txt = e => (e ? (e.innerText || e.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const headingOf = el => {
    const ids = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
    const lab = ids.map(i => txt(document.getElementById(i))).join(' ').trim();
    if (lab) return lab;
    const h = el.querySelector('h1, h2, h3, h4, h5, h6, legend, [role="heading"]');
    return txt(h);
  };
  const found = [];
  for (const [aid, name] of sections) {
    for (const el of document.querySelectorAll('[data-automation-id="' + aid + '"]')) {
      if (vis(el)) found.push([el, name]);
    }
  }
  if (!found.length) {
    for (const h of document.querySelectorAll('h2, h3, h4, legend, [role="heading"]')) {
      const t = txt(h).replace(/[*]+$/, '').replace(/\(optional\)/i, '').trim().toLowerCase();
      for (const [aid, name, title] of sections) {
        if (t !== title) continue;
        const el = h.closest('section, fieldset, [role="region"]') || h.parentElement;
        if (el && vis(el) && !found.some(f => f[0] === el)) found.push([el, name]);
      }
    }
  }
  const panelSel = '[role="group"], [data-automation-id^="workExperience-"], '
    + '[data-automation-id^="education-"], [data-automation-id^="language-"], '
    + '[data-automation-id^="website-"], [data-automation-id^="certification-"]';
  const out = [];
  let n = 0;
  for (const [el, name] of found) {
    n += 1;
    const head = el.querySelector('h1, h2, h3, h4, legend, [role="heading"]');
    const title = txt(head) || name;
    const required = /\*/.test(txt(head)) || !!(head && head.querySelector('abbr'));
    let add = '';
    for (const b of el.querySelectorAll('button, [role="button"]')) {
      const t = txt(b) || (b.getAttribute('aria-label') || '');
      if (vis(b) && (b.getAttribute('data-automation-id') === 'Add'
                     || /^add( another)?\b/i.test(t.trim()))) {
        b.setAttribute(ADD, 's' + n); add = '[' + ADD + '="s' + n + '"]'; break;
      }
    }
    const kept = [];
    for (const c of el.querySelectorAll(panelSel)) {
      if (c === el || !vis(c)) continue;
      const m = headingOf(c).match(/(\d+)\s*$/);
      if (!m) continue;
      if (kept.some(k => k.el.contains(c))) continue;
      kept.push({el: c, index: parseInt(m[1], 10), title: headingOf(c)});
    }
    const entries = [];
    kept.forEach((k, i) => {
      const id = 's' + n + 'e' + (i + 1);
      k.el.setAttribute(ENTRY, id);
      let del = '';
      for (const b of k.el.querySelectorAll('button, [role="button"]')) {
        const t = (txt(b) || b.getAttribute('aria-label') || '').trim();
        if (b.getAttribute('data-automation-id') === 'panel-set-delete-button' || /^delete/i.test(t)) {
          b.setAttribute(DEL, id); del = '[' + DEL + '="' + id + '"]'; break;
        }
      }
      entries.push({index: k.index, title: k.title, mark: '[' + ENTRY + '="' + id + '"]', delete: del});
    });
    out.push({section: name, title, required, add, entries});
  }
  return out;
}
"""

_ERRORS_JS = r"""
(sel) => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const txt = e => (e ? (e.innerText || e.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const labelOf = el => {
    const id = el.getAttribute('id');
    let t = '';
    if (id) { const l = document.querySelector('label[for="' + CSS.escape(id) + '"]'); t = txt(l); }
    if (!t) {
      const box = el.closest('[data-automation-id^="formField"], fieldset, [role="group"]');
      if (box) t = txt(box.querySelector('label, legend'));
    }
    if (!t) t = el.getAttribute('aria-label') || '';
    return t.replace(/[*]+\s*$/, '').trim();
  };
  const out = [];
  for (const el of document.querySelectorAll('[aria-invalid="true"]')) {
    if (!vis(el) && !vis(el.parentElement)) continue;
    const t = labelOf(el);
    if (t && !out.includes(t)) out.push(t.slice(0, 120));
    if (out.length >= 20) return out;
  }
  if (!out.length) {
    for (const el of document.querySelectorAll(sel)) {
      const t = txt(el).replace(/^error:\s*/i, '');
      if (vis(el) && t && !out.includes(t)) out.push(t.slice(0, 120));
      if (out.length >= 20) break;
    }
  }
  return out;
}
"""

# The active progress-bar item's full text, its prefix included (S-5 d: the
# "current step N of M" part may sit in a visually hidden span).
_ACTIVE_STEP_JS = r"""
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return '';
  const t = s => (s || '').replace(/\s+/g, ' ').trim();
  let text = t(el.textContent);
  if (!/step\s+\d+\s+of\s+\d+/i.test(text)) {
    const li = el.closest('li');
    if (li && /step\s+\d+\s+of\s+\d+/i.test(t(li.textContent))) text = t(li.textContent);
    else if (/step\s+\d+\s+of\s+\d+/i.test(el.getAttribute('aria-label') || '')) text = t(el.getAttribute('aria-label'));
  }
  return text;
}
"""


class WorkdayNavigator:
    """`SiteNavigator` for Workday tenants (contracts v5)."""

    name = "workday"
    needs_account = True
    password_rules = PasswordRules(length=20, symbols="!@#$%^&*")
    mail_domains = ("myworkday.com", "myworkdayjobs.com", "myworkdaysite.com", "workday.com")
    # Hosts a verification link may point to, besides the tenant and the employer (AD §9.4.4).
    link_domains = ("myworkdayjobs.com", "myworkday.com", "myworkdaysite.com")
    otp_pattern = r"\b(\d{6})\b"

    # ---------------- tenant (AD §9.4.1) ----------------

    def match_url(self, url: str) -> Optional[Tenant]:
        """Forms A and B; both give the canonical `<tenant>.<wdN>.myworkdayjobs.com`
        host, so one tenant has one vault service whichever form a posting used."""
        s = str(url or "").strip()
        m = FORM_A.match(s) or FORM_B.match(s)
        if not m:
            return None
        tenant, wd = m.group("tenant").lower(), m.group("wd").lower()
        return Tenant("workday", f"{tenant}.{wd}.myworkdayjobs.com", tenant,
                      site=m.group("site"), posting_id=self._req_from_path(m.group("rest") or ""))

    @staticmethod
    def _req_from_path(rest: str) -> str:
        parts = [p for p in rest.split("/") if p]
        try:
            i = [p.lower() for p in parts].index("job")
        except ValueError:
            return ""
        seg = parts[i + 2] if len(parts) > i + 2 else ""
        m = REQ_SUFFIX.search(seg)
        return m.group("req") if m else ""

    def tenant_from_company(self, job: dict[str, Any]) -> Optional[Tenant]:
        """Provider `workday` and a Workday job URL → its tenant; the posting id
        is the job's `external_id` when the scraper stored one."""
        if str(job.get("provider") or "").strip().lower() != self.name:
            return None
        t = self.match_url(str(job.get("url") or ""))
        if t is None:
            return None
        ext = str(job.get("external_id") or "").strip()
        if ext and ext != t.posting_id:
            t = Tenant(t.ats, t.host, t.board, site=t.site, posting_id=ext)
        return t

    def precheck(self, ctx: AttemptContext) -> None:
        """Nothing to check before the browser (no public schema)."""
        return None

    # ---------------- open and the Apply choice (§9.1) ----------------

    def open(self, page: Any, ctx: AttemptContext) -> None:
        """The posting, a declined cookie banner, then the Apply button
        (`adventureButton`, an `<a role=button>` to `<job_url>/apply`)."""
        acfg = B.options_for(page)
        timeout_ms = acfg.step_timeout_s * 1000
        resp = page.goto(job_url(str(ctx.job.get("url") or "")), wait_until="domcontentloaded",
                         timeout=timeout_ms)
        status = resp.status if resp is not None else None
        B.settle(page)
        if dismiss_cookies(page):
            ctx.log("workday: cookie banner declined")
        end = time.monotonic() + timeout_ms / 1000
        while True:
            sig = classify(page, status)
            if sig in _SIGNAL_REASON:
                raise ApplyFailure(_SIGNAL_REASON[sig], "", step="open")
            btn = self._apply_button(page)
            if btn is not None:
                _click(page, btn)
                B.settle(page)
                dismiss_cookies(page)
                return
            if time.monotonic() >= end:
                raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "workday: no apply button",
                                   step="open")
            page.wait_for_timeout(500)

    def _apply_button(self, page: Any) -> Optional[Any]:
        for sel in APPLY_BUTTONS:
            btn = _first_visible(page.locator(sel), 5)
            if btn is not None:
                return btn
        for role in ("button", "link"):
            btn = _first_visible(page.get_by_role(role, name=APPLY_NAME), 5)
            if btn is not None:
                return btn
        return None

    def choose_entry(self, page: Any, ctx: AttemptContext) -> str:
        """The Start Your Application dialog (S-5): click "Autofill with Resume"
        when offered, else "Apply Manually" (`entry_choice`). Returns the
        ValueOrigin value later pages carry. No dialog within 10 s, or the
        account form / a wizard step already showing → `direct`."""
        setting = B.options_for(page).workday_entry
        end = time.monotonic() + ENTRY_WAIT_S
        offered: dict[str, Any] = {}
        while True:
            dialog = page.locator(ENTRY_DIALOG)
            if _visible(dialog):
                for entry, aid in ENTRY_IDS.items():
                    item = _first_visible(dialog.locator(f'[data-automation-id="{aid}"]'), 3)
                    if item is not None:
                        offered[entry.value] = item
                if offered:
                    break
            if self.account_wall(page) or self._wizard_visible(page) \
                    or time.monotonic() >= end:
                ctx.log("workday: entry direct (no Apply choice shown)")
                return ValueOrigin.SITE_DEFAULT.value
            page.wait_for_timeout(500)
        entry, origin = entry_choice(frozenset(offered), setting)
        if entry.value in offered:
            _click(page, offered[entry.value])
        else:                                   # manual asked for, but not offered: by URL (S-5)
            url = job_url(str(ctx.job.get("url") or "")) + "/apply/applyManually"
            page.goto(url, wait_until="domcontentloaded",
                      timeout=B.options_for(page).step_timeout_s * 1000)
        B.settle(page)
        dismiss_cookies(page)
        ctx.log(f"workday: entry {entry.value}")
        return origin

    def _wizard_visible(self, page: Any) -> bool:
        return _visible(page.locator(ACTIVE_STEP)) or _visible(page.locator(FLOW_PAGE))

    # ---------------- account wall (AD §9.4.3, S-5 c) ----------------

    def account_wall(self, page: Any) -> Optional[str]:
        """"sign_in" | "sign_up" when an account form shows, else None. These
        checks come first: the account form is wizard step 1 with the progress
        bar visible (S-5 c)."""
        if _visible(page.locator(SIGN_IN_SUBMIT)):
            return "sign_in"
        if _visible(page.locator(CREATE_SUBMIT)) or _visible(page.locator(VERIFY_PASSWORD)):
            return "sign_up"
        return None

    def _account_form_gone(self, page: Any) -> bool:
        return not (_visible(page.locator(SIGN_IN_SUBMIT)) or _visible(page.locator(CREATE_SUBMIT)))

    def _fill_account(self, page: Any, sel: str, value: str, what: str) -> None:
        loc = _first_visible(page.locator(sel), 3)
        if loc is None or not B.fill_text(loc, value):
            raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, f"workday: account form ({what})")

    def sign_in(self, page: Any, ctx: AttemptContext, password: Secret) -> None:
        """One sign-in submit with `ctx.email` and the vault password. Returns
        when the form is gone (the flow classifies a verify-email page next);
        LOGIN_FAILED when the site rejects it or says the account is locked.
        Never "Forgot password" (F-35)."""
        if not _visible(page.locator(SIGN_IN_SUBMIT)):
            link = _first_visible(page.locator(SIGN_IN_LINK), 3) \
                or _first_visible(page.get_by_role("button", name=SIGN_IN_NAME), 3)
            if link is None:
                raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "workday: no sign-in form",
                                   step="signing_in")
            _click(page, link)
            page.wait_for_timeout(1500)
        self._fill_account(page, EMAIL_INPUT, ctx.email, "email")
        self._fill_account(page, PASSWORD_INPUT, password.reveal(), "password")
        _click(page, page.locator(SIGN_IN_SUBMIT).first)
        timeout_s = B.options_for(page).step_timeout_s
        end = time.monotonic() + timeout_s
        while True:
            page.wait_for_timeout(1000)
            alerts = self._alert_texts(page)
            if alerts:
                detail = LOCKED_DETAIL if LOCKED_TEXT.search(" ".join(alerts)) else REJECTED_DETAIL
                raise ApplyFailure(ReasonCode.LOGIN_FAILED, detail, step="signing_in")
            if self._account_form_gone(page) or classify(page) is PageSignal.VERIFY_EMAIL:
                B.settle(page)
                return
            if time.monotonic() >= end:
                raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "workday: after sign in",
                                   step="signing_in")

    def sign_up(self, page: Any, ctx: AttemptContext, password: Secret) -> str:
        """Fill and submit Create Account for `ctx.email` (the vault already holds
        the password, AD §10.2) and tick the terms box when present (the flow
        checked `consents.privacy_consent` first). First match wins:
        already registered → field error (VALIDATION_ERROR "account form: …") →
        wizard → verify-email page → the sign-in form."""
        if not _visible(page.locator(CREATE_SUBMIT)):
            link = _first_visible(page.locator(CREATE_LINK), 3)
            if link is None:
                raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "workday: no create-account form",
                                   step="signing_up")
            _click(page, link)
            page.wait_for_timeout(1500)
        self._fill_account(page, EMAIL_INPUT, ctx.email, "email")
        self._fill_account(page, PASSWORD_INPUT, password.reveal(), "password")
        self._fill_account(page, VERIFY_PASSWORD, password.reveal(), "verify password")
        box = _first_visible(page.locator(CREATE_CHECKBOX), 3)
        if box is not None and not B.set_checkbox(box, True):
            raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "workday: account terms box",
                               step="signing_up")
        _click(page, page.locator(CREATE_SUBMIT).first)
        end = time.monotonic() + B.options_for(page).step_timeout_s
        while True:
            page.wait_for_timeout(1000)
            if ALREADY_REGISTERED.search(visible_text(page)):
                return SignUpOutcome.ALREADY_REGISTERED.value
            flagged = self.visible_errors(page)
            if flagged:
                raise ApplyFailure(ReasonCode.VALIDATION_ERROR,
                                   "account form: " + ", ".join(f[:60] for f in flagged[:2]),
                                   step="signing_up")
            if self._account_form_gone(page) and self._wizard_visible(page):
                B.settle(page)
                return SignUpOutcome.SIGNED_IN.value
            if classify(page) is PageSignal.VERIFY_EMAIL:
                return SignUpOutcome.VERIFY_EMAIL.value
            if _visible(page.locator(SIGN_IN_SUBMIT)) and not _visible(page.locator(CREATE_SUBMIT)):
                return SignUpOutcome.SIGN_IN.value
            if time.monotonic() >= end:
                raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "workday: after create account",
                                   step="signing_up")

    def enter_code(self, page: Any, ctx: AttemptContext, code: str) -> None:
        """An emailed code (AD §9.4.4; not met on the S-5/S-5b tenants): type it
        and press the page's Verify / Continue button (never a Submit)."""
        inp = _first_visible(page.locator(CODE_INPUT), 5)
        if inp is None or not B.fill_text(inp, code):
            raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "workday: code box",
                               step="verifying_email")
        btn = _first_visible(page.get_by_role("button", name=CODE_BUTTON_NAME), 3)
        if btn is not None:
            _click(page, btn)
            B.settle(page)

    def _alert_texts(self, page: Any) -> list[str]:
        """Visible `inputAlert` / `errorMessage` / banner texts (S-5 b)."""
        out: list[str] = []
        loc = page.locator(ERROR_SELECTORS)
        try:
            n = min(loc.count(), 10)
        except Exception:
            return out
        for i in range(n):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    t = _text(el)
                    if t:
                        out.append(t[:200])
            except Exception:
                continue
        return out

    # ---------------- the wizard (§9.1) ----------------

    def step_id(self, page: Any, ctx: AttemptContext) -> str:
        """The active progress-bar title, prefix stripped and slugged (keeping N
        for question and unknown pages, review M7); else the step container's
        id (AD §9.4.5); "" when neither shows."""
        try:
            raw = page.evaluate(_ACTIVE_STEP_JS, ACTIVE_STEP) or ""
        except Exception:
            raw = ""
        sid = step_from_title(raw)
        if sid:
            return sid
        for aid, sid in STEP_CONTAINERS:
            if _visible(page.locator(f'[data-automation-id="{aid}"]')):
                return sid
        return ""

    def scope(self, page: Any, ctx: AttemptContext) -> str:
        """The wizard's page container; "" (the generic default) when absent."""
        return FLOW_PAGE if _visible(page.locator(FLOW_PAGE)) else ""

    def entry_sections(self, page: Any, ctx: AttemptContext) -> list[EntrySection]:
        """Work experience, education, languages, websites, certifications: by
        section automation id (K), else by heading; entries = panels whose
        heading ends in a number; delete = `panel-set-delete-button` or a button
        named Delete…; add = `Add` / "Add" / "Add Another". Each control gets a
        `data-jsnav-*` mark so its locator is plain CSS."""
        try:
            raw = page.evaluate(_SECTIONS_JS, [[list(s) for s in SECTIONS],
                                               [ENTRY_MARK, DELETE_MARK, ADD_MARK]]) or []
        except Exception:
            return []
        out: list[EntrySection] = []
        for s in raw:
            entries = tuple(EntryGroup(section=s["section"], index=int(e["index"]),
                                       title=str(e["title"])[:120], locator=e["mark"],
                                       delete_locator=e.get("delete") or "")
                            for e in s.get("entries") or [])
            out.append(EntrySection(section=s["section"], title=str(s["title"])[:120],
                                    add_locator=s.get("add") or "",
                                    required=bool(s.get("required")), entries=entries))
        return out

    def _nav_button(self, page: Any) -> Optional[Any]:
        for sel in NEXT_BUTTONS:
            btn = _first_visible(page.locator(sel), 3)
            if btn is not None:
                return btn
        return None

    def next_step(self, page: Any, ctx: AttemptContext) -> StepResult:
        """Save and Continue / Next. On the review page the button reads Submit:
        report `is_review` and click nothing (submitting is `submit`, once).
        After the click wait ≤ `step_timeout_s` for another step or errors; the
        errors come back as the flagged fields' labels (no values)."""
        step = self.step_id(page, ctx)
        dismiss_cookies(page)
        btn = self._nav_button(page)
        if btn is None:
            btn = _first_visible(page.get_by_role("button", name=NEXT_NAME), 3)
        if btn is None:
            if self.submit_ready(page):
                return StepResult(step=step or "review", is_review=True)
            raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "workday: no next button", step=step)
        label = _text(btn)
        if SUBMIT_ANY.search(label) or (not label and step == "review"):
            return StepResult(step=step or "review", is_review=True)
        _click(page, btn)
        end = time.monotonic() + B.options_for(page).step_timeout_s
        while True:
            page.wait_for_timeout(500)
            now = self.step_id(page, ctx)
            if now and now != step:
                B.settle(page)
                return StepResult(step=now, is_review=(now == "review"))
            errors = self.visible_errors(page)
            if errors:
                return StepResult(step=step, errors=errors)
            if time.monotonic() >= end:
                return StepResult(step=now or step)

    def _submit_button(self, page: Any) -> Optional[Any]:
        btn = self._nav_button(page)
        if btn is not None and SUBMIT_NAME.match(_text(btn)):
            return btn
        return _first_visible(page.get_by_role("button", name=SUBMIT_NAME), 3)

    def submit_ready(self, page: Any) -> bool:
        """A visible Submit button (checked before the click is recorded)."""
        return self._submit_button(page) is not None

    def submit(self, page: Any, ctx: AttemptContext) -> None:
        """The review page's Submit, once (§9.1; AD §9.4.11)."""
        btn = self._submit_button(page)
        if btn is None:
            raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "workday: no submit", step="submit")
        _click(page, btn)

    def after_submit(self, page: Any, ctx: AttemptContext) -> Optional[str]:
        """One poll: confirmed:text | confirmed:url | confirmed:home | errors | None."""
        url = str(getattr(page, "url", "") or "")
        text = visible_text(page)
        if CONFIRM_TEXT.search(text):
            return "confirmed:text"
        if CONFIRM_URL in url.lower():
            return "confirmed:url"
        title = str(ctx.job.get("title") or "").strip()
        if "/userhome" in url.lower() and title and title.lower() in text.lower() \
                and HOME_STATUS.search(text):
            return "confirmed:home"
        if self.visible_errors(page):
            return "errors"
        return None

    def visible_errors(self, page: Any) -> tuple[str, ...]:
        """Labels of the fields marked `aria-invalid` (S-5 b), else the visible
        `inputAlert` / `errorMessage` / banner texts. Labels and the site's own
        messages only, never values."""
        try:
            return tuple(page.evaluate(_ERRORS_JS, ERROR_SELECTORS) or ())
        except Exception:
            return ()


NAVIGATOR = WorkdayNavigator()
