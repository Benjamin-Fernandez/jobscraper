"""Page-state classifier: is this page a form we may fill, or a stop sign?

Design: apply_design.md §8.4 (F-38, F-36). Called after every navigation,
before each step's fill, after each Next and while waiting for a confirmation.
It only looks; it never clicks, types or waits out anything. The checks run in
the design's order and the first that matches wins:

  1. captcha        a VISIBLE challenge widget (reCAPTCHA bframe / v2 checkbox,
                    hCaptcha, Cloudflare Turnstile). The invisible reCAPTCHA
                    Enterprise anchor (`size=invisible`) and `.grecaptcha-badge`
                    sit on every Greenhouse board and are NOT a challenge [S-3].
  2. bot_challenge  Cloudflare / PerimeterX interstitials, block-page text,
                    HTTP 403 / 429 on the main document.
  3. two_factor     a one-time-code prompt that mentions a phone or an app.
  4. verify_email   "check your inbox"-style text with no application form.
  5. closed         HTTP 404 / 410, or closed-posting text.
  6. error_page     HTTP >= 500.

ATS-agnostic: adapters (Greenhouse, Workday, Lever, ...) pass their own extra
markers through `extra_closed` / `extra_errors` instead of editing this file.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Iterable, Optional


class PageSignal(str, Enum):
    OK = "ok"
    CAPTCHA = "captcha"
    BOT_CHALLENGE = "bot_challenge"
    TWO_FACTOR = "two_factor"
    VERIFY_EMAIL = "verify_email"
    CLOSED = "closed"
    ERROR_PAGE = "error_page"


# 1. Challenge widgets, each counted only when visible and taller than 30 px.
CAPTCHA_SELECTORS = (
    'iframe[src*="recaptcha"][src*="bframe"]',
    'iframe[title*="recaptcha challenge" i]',
    'iframe[src*="recaptcha"][src*="anchor"]:not([src*="size=invisible"])',   # v2 checkbox
    'iframe[src*="hcaptcha.com"][src*="frame=challenge"]',
    'iframe[src*="hcaptcha.com"][src*="frame=checkbox"]',
    'iframe[src*="challenges.cloudflare.com"]',
    ".cf-turnstile",
)
MIN_CHALLENGE_HEIGHT = 30

# 2. Bot walls.
BOT_TITLES = ("just a moment...",)
BOT_SELECTORS = ("#challenge-form", "#cf-challenge-running", "#px-captcha")
BOT_TEXT = re.compile(
    r"verify you are human|checking your browser|access denied.*reference #|unusual traffic",
    re.I | re.S)

# 3-4. Codes and email checks.
OTP_INPUT = 'input[autocomplete="one-time-code"]'
CODE_TEXT = re.compile(
    r"verification code|one-time (pass)?code|authenticator|two-step|2-step|two-factor", re.I)
PHONE_TEXT = re.compile(r"\bsms\b|text message|\bphone\b|\bmobile\b|authenticator app", re.I)
VERIFY_EMAIL_TEXT = re.compile(
    r"verify your email|check your (email|inbox)|we('ve| have) sent (you )?an? (email|link|code)"
    r"|confirm your email|security code", re.I)
# "Application form fields" for the verify_email rule: visible inputs a person types into.
FORM_FIELDS = ('input:not([type="hidden"]):not([type="submit"]):not([type="button"])'
               ':not([autocomplete="one-time-code"]), textarea, select')

# 5. Closed postings.
CLOSED_TEXT = re.compile(
    r"no longer (accepting applications|available|open)|position has been filled"
    r"|job (is )?not found|this job has expired|posting (has )?closed", re.I)


def classify(page: Any, status: Optional[int] = None, *,
             extra_closed: Iterable[str] = (), extra_errors: Iterable[str] = ()) -> PageSignal:
    """What the page in front of us is (apply_design §8.4).

    `status` is the HTTP status of the main document when the caller has it
    (the `Response` of `page.goto`). `extra_closed`: regexes an adapter adds,
    matched against the visible text and the URL (e.g. Greenhouse's
    `[?&]error=true`). `extra_errors`: CSS selectors an adapter adds; a visible
    match is an error page (e.g. Workday's `[data-automation-id="errorMessage"]`).
    """
    # 1. captcha: a visible widget only.
    for sel in CAPTCHA_SELECTORS:
        if _any_visible(page, sel, min_height=MIN_CHALLENGE_HEIGHT):
            return PageSignal.CAPTCHA

    title = _safe(lambda: page.title(), "").strip().lower()
    text = visible_text(page)

    # 2. bot walls
    if title in BOT_TITLES or status in (403, 429):
        return PageSignal.BOT_CHALLENGE
    if any(_count(page, sel) for sel in BOT_SELECTORS) or BOT_TEXT.search(text):
        return PageSignal.BOT_CHALLENGE

    # 3-4. a code prompt: phone/app -> two_factor; email -> verify_email
    otp = _any_visible(page, OTP_INPUT)
    if (otp or CODE_TEXT.search(text)) and PHONE_TEXT.search(text) \
            and not VERIFY_EMAIL_TEXT.search(text):
        return PageSignal.TWO_FACTOR
    if VERIFY_EMAIL_TEXT.search(text) and not _any_visible(page, FORM_FIELDS):
        return PageSignal.VERIFY_EMAIL

    # 5. closed
    if status in (404, 410) or CLOSED_TEXT.search(text):
        return PageSignal.CLOSED
    url = _safe(lambda: page.url, "")
    for pattern in extra_closed:
        if re.search(pattern, text, re.I) or re.search(pattern, url, re.I):
            return PageSignal.CLOSED

    # 6. errors
    if status is not None and status >= 500:
        return PageSignal.ERROR_PAGE
    for sel in extra_errors:
        if _any_visible(page, sel):
            return PageSignal.ERROR_PAGE
    return PageSignal.OK


def visible_text(page: Any) -> str:
    """The page's rendered text (`innerText`: display:none content excluded),
    "" when the page cannot be read (navigating, closed)."""
    return _safe(lambda: page.evaluate("() => document.body ? document.body.innerText : ''"), "") or ""


def _count(page: Any, selector: str) -> int:
    return _safe(lambda: page.locator(selector).count(), 0)


def _any_visible(page: Any, selector: str, *, min_height: float = 0) -> bool:
    """True when at least one element matching `selector` is visible (and, with
    `min_height`, taller than that). Hidden matches are skipped, not fatal."""
    loc = page.locator(selector)
    n = _safe(loc.count, 0)
    for i in range(min(n, 20)):
        el = loc.nth(i)
        if not _safe(el.is_visible, False):
            continue
        if min_height:
            box = _safe(el.bounding_box, None)
            if not box or box.get("height", 0) <= min_height:
                continue
        return True
    return False


def _safe(fn, default):
    """Run a read-only Playwright call; a page that is navigating or closed
    reads as `default` instead of raising into the flow."""
    try:
        return fn()
    except Exception:
        return default
