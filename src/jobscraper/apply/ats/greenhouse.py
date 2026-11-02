"""Greenhouse adapter (apply_design §9.1; D-70 §9.1.1 MyGreenhouse).

Greenhouse publishes each posting's form as JSON (`?questions=true` on the
public Job Board API), so the whole plan is built before Edge opens and every
field is addressed on the page as `[id="<schema name>"]` (S-3: the DOM id
equals the schema field name, numeric ids included).

Dev/test hook (NF-08): `JOBSCRAPER_GH_BOARD_BASE` and `JOBSCRAPER_GH_API_BASE`
replace `https://job-boards.greenhouse.io` and `https://boards-api.greenhouse.io`,
so the local fixture form and schema can stand in for the real site in a
smoke run. Unset (always, in normal use) means the real hosts.
"""
from __future__ import annotations

import html as _html
import os
import re
import time
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import urlsplit

from .. import browser as B
from ..classify import PageSignal, classify, visible_text
from ..plan import any_phrase
from ..contracts import (
    Answer, ApplyFailure, AttemptContext, Canonical, FieldType, FormField, FormPlan, Option,
    PasswordRules, ReasonCode, Secret, StepResult, Tenant,
)

BOARD_HOST = "job-boards.greenhouse.io"
_BOARD_BASE = "https://" + BOARD_HOST
_API_BASE = "https://boards-api.greenhouse.io"

URL_RE = re.compile(
    r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_app\?for=)?"
    r"(?P<board>[\w.-]+)(?:/jobs/|&token=)(?P<id>\d+)", re.I)
GH_JID_RE = re.compile(r"[?&]gh_jid=(\d+)")

SCHEMA_TYPES = {
    "input_text": FieldType.TEXT,
    "textarea": FieldType.TEXTAREA,
    "input_file": FieldType.FILE,
    "input_hidden": FieldType.HIDDEN,
    "multi_value_single_select": FieldType.DROPDOWN,
    "multi_value_multi_select": FieldType.MULTI_CHOICE,
}
CANONICAL_BY_NAME = {
    "first_name": Canonical.FIRST_NAME,
    "last_name": Canonical.LAST_NAME,
    "preferred_name": Canonical.PREFERRED_NAME,
    "email": Canonical.EMAIL,
    "phone": Canonical.PHONE,
    "resume": Canonical.RESUME,
    "cover_letter": Canonical.COVER_LETTER,
}
COMPLIANCE_BY_NAME = {
    "gender": Canonical.EEO_GENDER,
    "race": Canonical.EEO_RACE,
    "hispanic_ethnicity": Canonical.EEO_HISPANIC,
    "veteran_status": Canonical.EEO_VETERAN,
    "disability_status": Canonical.EEO_DISABILITY,
}
# Demographic questions: an EEO canonical when the label names the topic
# (checked in this order: "hispanic" before "race"/"ethnicity").
DEMOGRAPHIC_BY_LABEL = (
    (re.compile(r"hispanic|latin[oax]", re.I), Canonical.EEO_HISPANIC),
    (re.compile(r"gender|\bsex\b", re.I), Canonical.EEO_GENDER),
    (re.compile(r"\brace\b|ethnicity|ethnic", re.I), Canonical.EEO_RACE),
    (re.compile(r"veteran", re.I), Canonical.EEO_VETERAN),
    (re.compile(r"disabilit", re.I), Canonical.EEO_DISABILITY),
)
# §9.1.2 (D-70): link canonicals by phrase match on single input_text questions.
LINK_PHRASES = (
    (Canonical.LINKEDIN, ("linkedin",)),
    (Canonical.GITHUB, ("github",)),
    (Canonical.WEBSITE, ("website", "portfolio", "personal site")),
)

# §9.1 Open / Submit / Confirmation / Code / Errors
FORM_MARKER = '[id="first_name"]'
EXTRA_CLOSED = (r"[?&]error=true",)                  # Greenhouse's closed-posting redirect
SUBMIT_TEXT = re.compile(r"submit", re.I)
CONFIRM_TEXT = re.compile(
    r"thank you for applying|application (has been )?(received|submitted)"
    r"|we('ve| have) received your application", re.I)
CODE_TEXT = re.compile(r"security code", re.I)
CODE_INPUTS = ('input[autocomplete="one-time-code"], input[id*="security" i], '
               'input[name*="security" i], input[id*="code" i]')
ERROR_MARKERS = (".helper-text--error",)
REQUIRED_TEXT = "This field is required"
# Types filled through the react-select helper on Greenhouse (DROPDOWN, RADIO shown as select).
REACT_TYPES = (FieldType.DROPDOWN, FieldType.RADIO, FieldType.MULTI_CHOICE, FieldType.TYPEAHEAD)

# §9.1.1 MyGreenhouse (D-70). Selectors pending spike S-6.
AUTOFILL_NAME = re.compile(r"autofill (with )?(my ?greenhouse|greenhouse)|autofill my application", re.I)
DIALOG_CLOSE_NAME = re.compile(r"^(close|cancel|not now|no thanks)$", re.I)
REMOVE_NAME = re.compile(r"remove|delete", re.I)
FILE_NAME_RE = re.compile(r"[^\s/\\]+\.(?:pdf|docx?|txt|rtf|odt)\b", re.I)

_SIGNAL_REASON = {
    PageSignal.CAPTCHA: ReasonCode.CAPTCHA,
    PageSignal.BOT_CHALLENGE: ReasonCode.BOT_CHALLENGE,
    PageSignal.TWO_FACTOR: ReasonCode.SMS_OR_2FA,
    PageSignal.CLOSED: ReasonCode.POSTING_CLOSED,
}


def board_base() -> str:
    return os.environ.get("JOBSCRAPER_GH_BOARD_BASE", _BOARD_BASE).rstrip("/")


def api_base() -> str:
    return os.environ.get("JOBSCRAPER_GH_API_BASE", _API_BASE).rstrip("/")


def html_to_text(s: Any) -> str:
    """Schema descriptions are HTML: tags dropped, entities decoded, spaces tidied."""
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", str(s or ""), flags=re.I)
    text = _html.unescape(re.sub(r"<[^>]+>", " ", text))
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def link_canonical(label: str) -> Optional[Canonical]:
    """LINKEDIN / GITHUB / WEBSITE when exactly one of them phrase-matches the
    label (§9.1.2, D-70): `plan.any_phrase`, i.e. §7.1 normalisation and the
    one-token rule ("LinkedIn URL" is tagged; "Please share your LinkedIn
    profile or another link to your work" is not; "LinkedIn or GitHub" is two
    canonicals, so none)."""
    hits = [c for c, phrases in LINK_PHRASES if any_phrase(phrases, label)]
    return hits[0] if len(hits) == 1 else None


def _status_of(exc: BaseException) -> Optional[int]:
    """The HTTP status an HTTP client error carries (net.FetchError has
    `.status`), without importing the scrape stage."""
    st = getattr(exc, "status", None)
    return st if isinstance(st, int) else None


class GreenhouseAdapter:
    name = "greenhouse"
    needs_account = False
    password_rules = PasswordRules()
    mail_domains = ("greenhouse.io", "greenhouse-mail.io")
    otp_pattern = r"\b([A-Za-z0-9]{8})\b"          # pending S-4
    # The site prefill this adapter may apply (D-70 §9.1.1); apply_flow reads it
    # to defer the planning-time unanswerable check until after the prefill.
    prefill_source = "mygreenhouse"

    def __init__(self) -> None:
        self._plans: dict[int, FormPlan] = {}       # attempt id -> plan (read_step)

    # ---------------- tenant ----------------

    def match_url(self, url: str) -> Optional[Tenant]:
        m = URL_RE.search(str(url or ""))
        if not m:
            return None
        return Tenant("greenhouse", BOARD_HOST, m.group("board"), posting_id=m.group("id"))

    def tenant_from_company(self, job: dict[str, Any]) -> Optional[Tenant]:
        """Board = the company's slug (board token); posting = the job's
        external id, else the id in its URL (`/jobs/<id>` or `gh_jid=<id>`)."""
        if str(job.get("provider") or "").lower() != self.name:
            return None
        url = str(job.get("url") or "")
        from_url = self.match_url(url)
        board = str(job.get("slug") or "").strip() or (from_url.board if from_url else "")
        posting = str(job.get("external_id") or "").strip()
        if not posting.isdigit():
            m = GH_JID_RE.search(url)
            posting = m.group(1) if m else (from_url.posting_id if from_url else "")
        if not board or not posting:
            return None
        return Tenant("greenhouse", BOARD_HOST, board, posting_id=posting)

    def posting_url(self, tenant: Tenant) -> str:
        return f"{board_base()}/{tenant.board}/jobs/{tenant.posting_id}"

    def embed_url(self, tenant: Tenant) -> str:
        return f"{board_base()}/embed/job_app?for={tenant.board}&token={tenant.posting_id}"

    # ---------------- plan (§9.1 Plan, Mapping) ----------------

    def plan_from_schema(self, ctx: AttemptContext) -> Optional[FormPlan]:
        t = ctx.tenant
        url = f"{api_base()}/v1/boards/{t.board}/jobs/{t.posting_id}?questions=true"
        try:
            data = ctx.http.get_json(url)
        except Exception as exc:
            if _status_of(exc) in (404, 410):
                raise ApplyFailure(ReasonCode.POSTING_CLOSED, "", step="planning") from None
            raise
        if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
            raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "greenhouse: schema", step="planning")
        plan = FormPlan(ats=self.name, job_id=str(ctx.job.get("job_id", "")),
                        apply_url=self.posting_url(t), source="schema",
                        fields=self._fields(data))
        self._plans[ctx.attempt_id] = plan
        return plan

    def _fields(self, data: dict[str, Any]) -> list[FormField]:
        out: list[FormField] = []
        out += self._question_fields(data.get("questions") or [], section="questions")
        loc = self._location_field(data.get("location_questions") or [])
        if loc:
            out.append(loc)
        for block in data.get("compliance") or []:
            out += self._question_fields((block or {}).get("questions") or [], section="compliance",
                                         canonical_by_name=COMPLIANCE_BY_NAME)
        demo = data.get("demographic_questions") or {}
        for q in (demo.get("questions") if isinstance(demo, dict) else None) or []:
            out.append(self._demographic_field(q))
        out += self._consent_fields(data.get("data_compliance") or [])
        # Not in the schema: the phone's country react-select beside #phone (S-3).
        out.append(FormField(key="country", label="Country", type=FieldType.DROPDOWN,
                             required=False, section="questions",
                             canonical=Canonical.PHONE_COUNTRY_CODE, locator='[id="country"]'))
        return out

    def _question_fields(self, questions: list[dict[str, Any]], *, section: str,
                         canonical_by_name: Optional[dict[str, Canonical]] = None) -> list[FormField]:
        by_name = canonical_by_name if canonical_by_name is not None else CANONICAL_BY_NAME
        out = []
        for q in questions:
            fields = q.get("fields") or []
            label = html_to_text(q.get("label")) or ""
            desc = html_to_text(q.get("description"))
            types = [SCHEMA_TYPES.get(f.get("type"), FieldType.TEXT) for f in fields]
            file_key = next((f.get("name") for f, ty in zip(fields, types) if ty is FieldType.FILE), "")
            only_text = len(fields) == 1 and fields[0].get("type") == "input_text"
            for f, ty in zip(fields, types):
                name = str(f.get("name") or "")
                canonical = by_name.get(name)
                if canonical is None and section == "questions" and only_text:
                    canonical = link_canonical(label)
                out.append(FormField(
                    key=name, label=label, type=ty, required=bool(q.get("required")),
                    options=tuple(Option(str(v.get("label", "")), str(v.get("value", "")))
                                  for v in (f.get("values") or [])),
                    section=section, description=desc, canonical=canonical,
                    locator=f'[id="{name}"]',
                    alt_of=file_key if (ty is FieldType.TEXTAREA and file_key) else ""))
        return out

    def _location_field(self, questions: list[dict[str, Any]]) -> Optional[FormField]:
        """`location_questions` (latitude/longitude hidden + a location text) is
        one react-select on the page, `#candidate-location` (S-3)."""
        if not questions:
            return None
        main = next((q for q in questions
                     if any(f.get("type") != "input_hidden" for f in q.get("fields") or [])),
                    questions[-1])
        return FormField(key="candidate-location", label=html_to_text(main.get("label")) or "Location",
                         type=FieldType.TYPEAHEAD,
                         required=any(bool(q.get("required")) for q in questions),
                         section="location", canonical=Canonical.LOCATION,
                         locator='[id="candidate-location"]')

    def _demographic_field(self, q: dict[str, Any]) -> FormField:
        label = html_to_text(q.get("label"))
        canonical = next((c for rx, c in DEMOGRAPHIC_BY_LABEL if rx.search(label)), None)
        ty = SCHEMA_TYPES.get(q.get("type"), FieldType.DROPDOWN)
        key = str(q.get("id"))
        return FormField(
            key=key, label=label, type=ty, required=bool(q.get("required")),
            options=tuple(Option(str(o.get("label", "")), str(o.get("id", "")))
                          for o in (q.get("answer_options") or [])),
            section="demographic", canonical=canonical, locator=f'[id="{key}"]')

    def _consent_fields(self, blocks: list[dict[str, Any]]) -> list[FormField]:
        out = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if b.get("requires_processing_consent"):
                out.append(FormField(
                    key="gdpr_processing_consent_given", type=FieldType.CHECKBOX, required=True,
                    label="I consent to the processing of my personal data for this application",
                    section="data_compliance", canonical=Canonical.CONSENT_PRIVACY,
                    locator='[id="gdpr_processing_consent_given_1"]'))
            if b.get("requires_retention_consent"):
                out.append(FormField(
                    key="gdpr_retention_consent_given", type=FieldType.CHECKBOX, required=True,
                    label="I consent to my data being kept for future roles",
                    section="data_compliance", canonical=Canonical.CONSENT_RETENTION,
                    locator='[id="gdpr_retention_consent_given_1"]'))
        return out

    def plan_for(self, ctx: AttemptContext) -> Optional[FormPlan]:
        return self._plans.get(ctx.attempt_id)

    def forget(self, ctx: AttemptContext) -> None:
        """Drop the attempt's cached plan (apply_flow calls this when it ends)."""
        self._plans.pop(ctx.attempt_id, None)

    # ---------------- open (§9.1 Open) ----------------

    def open(self, page: Any, ctx: AttemptContext) -> None:
        """The posting page (the form is on it, S-3); the embed form when the
        board redirects to the employer's own site. `#first_name` must appear
        within `step_timeout_s`; else the page says why (closed, CAPTCHA, bot
        wall) or it is `page_unrecognised`."""
        timeout_ms = B.options_for(page).step_timeout_s * 1000
        resp = page.goto(self.posting_url(ctx.tenant), wait_until="domcontentloaded",
                         timeout=timeout_ms)
        status = resp.status if resp is not None else None
        if urlsplit(page.url).netloc.lower() != urlsplit(board_base()).netloc.lower():
            ctx.log("greenhouse: posting page left the board; opening the embedded form")
            resp = page.goto(self.embed_url(ctx.tenant), wait_until="domcontentloaded",
                             timeout=timeout_ms)
            status = resp.status if resp is not None else None
        B.settle(page)
        end = time.monotonic() + timeout_ms / 1000
        while True:
            if page.locator(FORM_MARKER).count():
                return
            sig = classify(page, status, extra_closed=EXTRA_CLOSED)
            if sig in _SIGNAL_REASON:
                raise ApplyFailure(_SIGNAL_REASON[sig], "", step="open")
            if time.monotonic() >= end:
                raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "greenhouse: application",
                                   step="open")
            page.wait_for_timeout(500)

    def account_wall(self, page: Any) -> Optional[str]:
        return None

    def sign_in(self, page: Any, ctx: AttemptContext, password: Secret) -> None:
        raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "greenhouse: no accounts", step="sign_in")

    def sign_up(self, page: Any, ctx: AttemptContext, password: Secret) -> str:
        raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "greenhouse: no accounts", step="sign_up")

    # ---------------- locators ----------------

    @staticmethod
    def locator(page: Any, f: FormField) -> Any:
        """`[id="<name>"]` (S-3); a single checkbox is `[id="<name>_1"]`."""
        if f.locator:
            return page.locator(f.locator).first
        key = f"{f.key}_1" if f.type is FieldType.CHECKBOX else f.key
        return page.locator(f'[id="{key}"]').first

    @staticmethod
    def _block(loc: Any) -> Any:
        """The field's own block: the nearest ancestor that holds a label."""
        return loc.locator("xpath=ancestor::*[.//label][1]")

    # ---------------- read (§9.1, D-70 §9.1.1) ----------------

    def read_step(self, page: Any, ctx: AttemptContext) -> tuple[str, list[FormField]]:
        """One page: the plan's fields that are on it."""
        plan = self._plans.get(ctx.attempt_id)
        if plan is None:
            raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "greenhouse: no plan", step="application")
        present = [f for f in plan.fields
                   if f.type is FieldType.HIDDEN or self.locator(page, f).count()]
        return "application", present

    def read_values(self, page: Any, ctx: AttemptContext,
                    fields: Sequence[FormField]) -> dict[str, Any]:
        """What each field shows now (D-70 §9.1.1): "" when empty, "true"/
        "false" for a checkbox, the file name for a file, a list for multi."""
        out: dict[str, Any] = {}
        for f in fields:
            loc = self.locator(page, f)
            try:
                if not loc.count() or f.type is FieldType.HIDDEN:
                    out[f.key] = ""
                elif f.type is FieldType.CHECKBOX:
                    out[f.key] = "true" if loc.is_checked() else "false"
                elif f.type is FieldType.FILE:
                    out[f.key] = self._shown_file(loc)
                elif f.type is FieldType.MULTI_CHOICE:
                    ctl = loc.locator(B.REACT_SELECT_CONTROL)
                    out[f.key] = [t.strip() for t in ctl.locator(".select__multi-value__label").all_inner_texts()]
                elif f.type in REACT_TYPES or f.key == "country":
                    ctl = loc.locator(B.REACT_SELECT_CONTROL)
                    single = ctl.locator(".select__single-value")
                    out[f.key] = single.first.inner_text().strip() if single.count() else ""
                else:
                    out[f.key] = loc.input_value()
            except Exception:
                out[f.key] = ""
        return out

    def _shown_file(self, loc: Any) -> str:
        try:
            files = loc.evaluate("e => Array.from(e.files || []).map(f => f.name)") or []
            if files:
                return files[0]
            m = FILE_NAME_RE.search(self._block(loc).first.inner_text())
            return m.group(0) if m else ""
        except Exception:
            return ""

    # ---------------- MyGreenhouse (D-70 §9.1.1) ----------------

    def prefill(self, page: Any, ctx: AttemptContext) -> str:
        """Click "Autofill with MyGreenhouse" when the profile is signed in, and
        report "mygreenhouse" once the form stops changing; "" otherwise. Never
        types an email or asks for a code: a sign-in prompt is closed and the
        attempt falls back to the full fill."""
        acfg = B.options_for(page)
        if not acfg.mygreenhouse:
            return ""
        btn = self._autofill_button(page)
        if btn is None:
            ctx.log("mygreenhouse: no button")
            return ""
        plan = self._plans.get(ctx.attempt_id)
        fields = [f for f in (plan.fields if plan else []) if f.type is not FieldType.HIDDEN]
        before = self.read_values(page, ctx, fields)
        host = urlsplit(page.url).netloc.lower()
        n_pages = len(page.context.pages)
        btn.click()
        end = time.monotonic() + acfg.mygreenhouse_wait_s
        result = ""
        while time.monotonic() < end:
            page.wait_for_timeout(1000)
            blocked = self._close_sign_in(page, ctx, host, n_pages)
            now = self.read_values(page, ctx, fields)
            if now != before:
                result = self._wait_stable(page, ctx, fields, now, end)
                break
            if blocked:
                ctx.log("mygreenhouse: not signed in")
                break
        else:
            ctx.log("mygreenhouse: no effect")
        ctx.screenshot(page, "mygreenhouse")
        if result:
            ctx.log("mygreenhouse: autofilled")
        return result

    def _autofill_button(self, page: Any) -> Optional[Any]:
        for role in ("button", "link"):
            cands = page.get_by_role(role, name=AUTOFILL_NAME)
            for i in range(min(cands.count(), 5)):
                if cands.nth(i).is_visible():
                    return cands.nth(i)
        return None

    def _close_sign_in(self, page: Any, ctx: AttemptContext, host: str, n_pages: int) -> bool:
        """Undo a sign-in detour (popup, navigation away, dialog). True if one
        was seen. Nothing is typed into it."""
        seen = False
        extra = page.context.pages[n_pages:]
        for p in extra:
            seen = True
            try:
                p.close()
            except Exception:
                pass
        if urlsplit(page.url).netloc.lower() != host:
            seen = True
            try:
                page.go_back(wait_until="domcontentloaded")
            except Exception:
                pass
            if not page.locator(FORM_MARKER).count():
                self.open(page, ctx)
        # A sign-in dialog (an email box, or sign-in / code text) - and in M20
        # any other dialog too (e.g. a "share your profile" consent; S-6 will
        # tell) - counts as not signed in, and is closed.
        dialogs = page.locator('[role="dialog"]')
        for i in range(min(dialogs.count(), 5)):
            d = dialogs.nth(i)
            if not _safe_visible(d):
                continue
            seen = True
            closer = d.locator('[aria-label="Close"]')
            if not closer.count():
                closer = d.get_by_role("button", name=DIALOG_CLOSE_NAME)
            try:
                if closer.count():
                    closer.first.click()
                else:
                    page.keyboard.press("Escape")
            except Exception:
                pass
        return seen

    def _wait_stable(self, page: Any, ctx: AttemptContext, fields: list[FormField],
                     last: dict[str, Any], end: float) -> str:
        while time.monotonic() < end:
            page.wait_for_timeout(1000)
            now = self.read_values(page, ctx, fields)
            if now == last:
                return "mygreenhouse"
            last = now
        return "mygreenhouse"

    # ---------------- fill (§9.1 Fill) ----------------

    def fill(self, page: Any, ctx: AttemptContext, fields: Sequence[FormField],
             answers: dict[str, Answer]) -> list[str]:
        """Fill every answer that `fills`, `country` before `phone`. Returns
        the keys that would not take their value."""
        order = sorted(fields, key=lambda f: 0 if f.key == "country" else 1)
        failed: list[str] = []
        for f in order:
            a = answers.get(f.key)
            if a is None or not a.fills or f.type is FieldType.HIDDEN:
                continue
            ok = self._fill_one(page, f, a)
            if not ok:
                failed.append(f.key)
                ctx.log(f"greenhouse: field did not take its value: {f.label[:80]}")
            B.pause(page)
        return failed

    def _fill_one(self, page: Any, f: FormField, a: Answer) -> bool:
        loc = self.locator(page, f)
        if not loc.count():
            return False
        labels = list(a.option_labels) or (a.value if isinstance(a.value, list) else [str(a.value)])
        if f.type is FieldType.FILE:
            return self._replace_file(page, loc, str(a.value))
        if f.type is FieldType.CHECKBOX:
            return B.set_checkbox(loc, str(a.value).strip().lower() == "true")
        if f.type is FieldType.TYPEAHEAD:
            want = B.norm_text(labels[0])
            return B.typeahead(page, loc, labels[0], lambda ls: next(
                (i for i, t in enumerate(ls) if B.norm_text(t).startswith(want)), None))
        if f.type in (FieldType.DROPDOWN, FieldType.RADIO, FieldType.MULTI_CHOICE):
            if not f.options:                 # async options (the phone country): pick by content
                want = B.norm_text(labels[0])
                return B.typeahead(page, loc, labels[0], lambda ls: next(
                    (i for i, t in enumerate(ls) if want in B.norm_text(t)), None))
            return all(B.choose_react_select(page, loc, lab) for lab in labels)
        return B.fill_text(loc, str(a.value))

    def _replace_file(self, page: Any, loc: Any, path: str) -> bool:
        """Upload our file; first remove one already attached (MyGreenhouse's
        resume is never sent, D-70). Read back: the shown name is ours."""
        name = Path(path).name
        shown = self._shown_file(loc)
        if shown and shown != name:
            block = self._block(loc).first
            remover = block.get_by_role("button", name=REMOVE_NAME)
            if not remover.count():
                remover = block.locator('[aria-label*="remove" i]')
            try:
                if remover.count():
                    remover.first.click()
                    B.pause(page)
            except Exception:
                pass
        if not B.upload(loc, path):
            return False
        return self._shown_file(loc) == name

    # ---------------- next, submit, confirmation (§9.1) ----------------

    def next_step(self, page: Any, ctx: AttemptContext) -> StepResult:
        """One page: the form is its own review page."""
        return StepResult(step="application", is_review=True, errors=self.visible_errors(page))

    def submit_ready(self, page: Any) -> bool:
        """A visible Submit button is on the page (checked before the click is
        recorded, so a missing button fails instead of counting as sent)."""
        btn = page.locator('button[type="submit"]').filter(has_text=SUBMIT_TEXT)
        return any(_safe_visible(btn.nth(i)) for i in range(min(btn.count(), 5)))

    def submit(self, page: Any, ctx: AttemptContext) -> None:
        btn = page.locator('button[type="submit"]').filter(has_text=SUBMIT_TEXT)
        if not btn.count():
            raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "greenhouse: submit button", step="submit")
        btn.first.click()

    def after_submit(self, page: Any, ctx: AttemptContext) -> Optional[str]:
        """One poll: confirmed:url / confirmed:text / code_required / errors / None."""
        if "/confirmation" in urlsplit(page.url).path:
            return "confirmed:url"
        text = visible_text(page)
        if CONFIRM_TEXT.search(text):
            return "confirmed:text"
        if CODE_TEXT.search(text) and self._code_input(page) is not None:
            return "code_required"
        if self.visible_errors(page):
            return "errors"
        return None

    def _code_input(self, page: Any) -> Optional[Any]:
        cands = page.locator(CODE_INPUTS)
        for i in range(min(cands.count(), 5)):
            if _safe_visible(cands.nth(i)):
                return cands.nth(i)
        return None

    def enter_code(self, page: Any, ctx: AttemptContext, code: str) -> None:
        inp = self._code_input(page)
        if inp is None or not B.fill_text(inp, code):
            raise ApplyFailure(ReasonCode.PAGE_UNRECOGNISED, "greenhouse: security code box",
                               step="verifying_email")

    def visible_errors(self, page: Any) -> tuple[str, ...]:
        """Labels of the fields the page marks invalid, and visible error
        notes. Labels and the site's own messages only, never values."""
        out: list[str] = []
        bad = page.locator('[aria-invalid="true"]')
        for i in range(min(bad.count(), 20)):
            el = bad.nth(i)
            if not _safe_visible(el) and not _safe_visible(self._block(el).first):
                continue
            el_id = el.get_attribute("id") or ""
            lab = page.locator(f'label[for="{el_id}"]') if el_id else None
            text = lab.first.inner_text().strip() if lab is not None and lab.count() else el_id
            if text and text not in out:
                out.append(text)
        for sel in ERROR_MARKERS:
            notes = page.locator(sel)
            for i in range(min(notes.count(), 20)):
                if _safe_visible(notes.nth(i)) and not out:
                    out.append(notes.nth(i).inner_text().strip())
        if not out and REQUIRED_TEXT.lower() in visible_text(page).lower():
            out.append(REQUIRED_TEXT)
        return tuple(out)


def _safe_visible(loc: Any) -> bool:
    try:
        return loc.is_visible()
    except Exception:
        return False


ADAPTER = GreenhouseAdapter()
