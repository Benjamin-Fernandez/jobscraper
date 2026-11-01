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
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from ..contracts import (
    ApplyFailure, AttemptContext, Canonical, FieldType, FormField, FormPlan, Option,
    PasswordRules, ReasonCode, Tenant,
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


def board_base() -> str:
    return os.environ.get("JOBSCRAPER_GH_BOARD_BASE", _BOARD_BASE).rstrip("/")


def api_base() -> str:
    return os.environ.get("JOBSCRAPER_GH_API_BASE", _API_BASE).rstrip("/")


def html_to_text(s: Any) -> str:
    """Schema descriptions are HTML: tags dropped, entities decoded, spaces tidied."""
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", str(s or ""), flags=re.I)
    text = _html.unescape(re.sub(r"<[^>]+>", " ", text))
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def _tokens(label: str) -> list[str]:
    """Label tokens for the §9.1.2 phrase match: lower case, runs of anything
    but [a-z0-9+#'] are one break. (A local stand-in for `plan.norm_label`, which
    lane P owns; the two agree on these link labels. WP-B9 may switch to it.)"""
    text = html_to_text(label).lower().replace("(required)", " ").replace("(optional)", " ")
    return [t.strip("'") for t in re.split(r"[^a-z0-9+#']+", text) if t.strip("'")]


def _phrase_match(phrase: str, tokens: list[str]) -> bool:
    want = phrase.split()
    if len(want) == 1 and len(tokens) > 4:            # §7.1 one-token rule
        return False
    return any(tokens[i:i + len(want)] == want for i in range(len(tokens) - len(want) + 1))


def link_canonical(label: str) -> Optional[Canonical]:
    """LINKEDIN / GITHUB / WEBSITE when exactly one of them phrase-matches."""
    toks = _tokens(label)
    hits = [c for c, phrases in LINK_PHRASES if any(_phrase_match(p, toks) for p in phrases)]
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


ADAPTER = GreenhouseAdapter()
