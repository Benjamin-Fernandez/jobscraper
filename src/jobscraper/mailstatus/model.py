"""F-50 model tier: the prompt for an email the rules can't sort, and the check
of the reply (MS section 6.5).

Design: docs/architecture/mail_status_design.md (MS) section 6.5; privacy
section 13. Builds and checks prompts only: it never calls the model.
`mailstatus_flow` calls `backend.complete(SYSTEM, user_prompt(...),
max_tokens=MAX_TOKENS, format=SCHEMA, temperature=TEMPERATURE, seed=SEED,
timeout=model_timeout_s)` and hands the reply to `parse`.

The boundary: the model only picks a category from a fixed list and points at
text; `parse` checks the pointer, and a model-tier verdict is never automatic
(MS 8 row 11a). An email written to manipulate the model can at most produce a
suggestion. Only the email goes into the prompt: no profile value, no employer
list, no address.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping, Optional

from .contracts import QUOTE_MAX, Category, MailBody, MailHeader, Tier, Verdict

SYSTEM = (
    "You read one email that a job applicant received about a job application. Say which "
    "update it gives. Never guess: if the email does not clearly say, answer unknown. Reply "
    "with JSON only.\n"
    "category: acknowledged (the application was received), assessment (an invitation to a "
    "test, coding challenge or one-way recorded video interview), interview (an invitation to, "
    "or the scheduling of, an interview with a person), offer (a job offer), rejected (the "
    "application will not go further), withdrawn (the application was withdrawn), "
    "posting_closed (the role was closed or put on hold), kept_on_file (details kept for future "
    "roles, without saying no to this one), portal_update (asks the applicant to log in to see "
    "an update), no_change (a reminder or thank-you that changes nothing), unknown.\n"
    "quote: the shortest sentence from the email that shows the category, copied exactly, at "
    "most 200 characters; \"\" for unknown.")

SCHEMA = {"type": "object",
          "properties": {"category": {"type": "string", "enum": [c.value for c in Category]},
                         "quote": {"type": "string", "maxLength": QUOTE_MAX}},
          "required": ["category", "quote"]}

MAX_TOKENS = 200
SEED = 7
TEMPERATURE = 0
ELLIPSIS = "…"

# imapread replaces every URL before the text leaves it (MS 5.6); this is the
# same rule once more, so a prompt never carries a link even from a subject.
_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_WS = re.compile(r"\s+")
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _clean(s: str) -> str:
    return _URL.sub("[link]", s or "")


def _parts(h: MailHeader, body: Optional[MailBody]) -> tuple[str, str]:
    subject = _WS.sub(" ", _clean(h.subject)).strip()
    text = _clean(body.text if body is not None else "")
    return subject, text


def user_prompt(h: MailHeader, body: Optional[MailBody], max_chars: int) -> str:
    """`SUBJECT: <subject>\\nEMAIL:\\n<text>`, the text cut to `max_chars` at the
    last line break that fits (a hard cut when there is none). A truncated body
    has no text, so the subject alone is read."""
    subject, text = _parts(h, body)
    limit = max(0, int(max_chars))
    if len(text) > limit:
        cut = text.rfind("\n", 0, limit + 1)
        text = text[:cut] if cut > 0 else text[:limit]
    return f"SUBJECT: {subject}\nEMAIL:\n{text}"


def norm_quote(s: str) -> str:
    """MS 6.5: casefolded, whitespace collapsed, "…" stripped."""
    return _WS.sub(" ", (s or "").replace(ELLIPSIS, " ").casefold()).strip()


def parse(reply: Any, h: MailHeader, body: Optional[MailBody], model_id: str = "") -> Verdict:
    """The model's reply as a MODEL-tier `Verdict`. `reply` is the completion text
    (or an object with `.text`, or an already-decoded mapping). Bad JSON, a
    category outside the enum, an empty quote for a category other than unknown,
    or a quote not found in the subject plus text gives UNKNOWN with
    status_words and `rule_id="model:<why>"` (a suggestion "unclear", MS 12)."""

    def unusable(why: str) -> Verdict:
        return Verdict(Category.UNKNOWN, Tier.MODEL, rule_id=f"model:{why}",
                       status_words=True, model=model_id)

    data = _decode(getattr(reply, "text", reply))
    if not isinstance(data, Mapping):
        return unusable("bad_json")
    raw_cat = data.get("category")
    try:
        category = Category(raw_cat.strip() if isinstance(raw_cat, str) else raw_cat)
    except (TypeError, ValueError):
        return unusable("bad_category")
    raw_quote = data.get("quote", "")
    if raw_quote is None:
        raw_quote = ""
    if not isinstance(raw_quote, str):
        return unusable("bad_quote")
    if category is Category.UNKNOWN:
        # The email had status words (that is why it was asked): ask the owner.
        return Verdict(Category.UNKNOWN, Tier.MODEL, rule_id="model:unknown",
                       status_words=True, model=model_id)
    needle = norm_quote(raw_quote)
    if not needle:
        return unusable("empty_quote")
    subject, text = _parts(h, body)
    if needle not in norm_quote(f"{subject}\n{text}"):
        return unusable("quote_not_found")
    quote = _WS.sub(" ", raw_quote).strip()
    if len(quote) > QUOTE_MAX:
        cut = quote.rfind(" ", 0, QUOTE_MAX)
        quote = quote[:cut if cut > 0 else QUOTE_MAX - 1].rstrip() + ELLIPSIS
    return Verdict(category, Tier.MODEL, quote=quote, rule_id="model:ok",
                   status_words=True, model=model_id)


def _decode(reply: Any) -> Any:
    if isinstance(reply, Mapping):
        return reply
    if isinstance(reply, (bytes, bytearray)):
        reply = reply.decode("utf-8", "replace")
    if not isinstance(reply, str):
        return None
    s = reply.strip()
    m = _FENCE.match(s)
    if m:
        s = m.group(1)
    try:
        return json.loads(s)
    except ValueError:
        return None
