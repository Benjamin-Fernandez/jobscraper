"""The browser layer: one Edge session per apply run, the fill primitives every
adapter uses, and the evidence (screenshots, HTML) each attempt leaves.

Design: apply_design.md §8.1-§8.3 (F-34, NF-05); spike S-1/S-3.

ATS-agnostic on purpose. Nothing here knows Greenhouse, Workday or Lever: an
adapter finds a control (a Playwright `Locator`) and hands it to a primitive.
Adapters never send input with raw Playwright calls (§8.2), so pacing, the
"never press Enter" rule and the read-back check live in one place.

API for adapters (all synchronous Playwright):

    BrowserSession(cfg: ApplyConfig)       one per run; .start() / with-block,
        .new_page() -> Page                a tab per attempt
        .hold(seconds)                     keep the window open (dry run); returns
                                           early when the owner closes it
        .close()
    options_for(page) -> ApplyConfig       the session's settings (step_timeout_s,
                                           type_delay_ms, action_pause_ms, ...)

    Fill primitives, each returns True only after reading the value back:
        fill_text(loc, value)                       text, textarea, tel, email
        choose_react_select(page, loc, label)       react-select (Greenhouse, Ashby)
        choose_native(loc, label)                   <select>
        choose_listbox(page, button, label)         aria listbox button (Workday)
        choose_radio(container, label)              radio by its label text
        set_checkbox(loc, on)                       one tick box
        typeahead(page, loc, text, pick)            type, then pick a suggestion
        upload(loc, path)                           (hidden) <input type=file>
        settle(page)                                load state + the NF-05 pause

    Evidence:
        screenshot(page, attempt_dir, seq, step) -> "NN-<step>.png" path
        dump_html(page, attempt_dir) -> "failed.html" path
        norm_text(s), slug(s)                       comparison / file-name helpers

Launch arguments follow §8.1 verbatim except one Python spelling: Playwright's
JS `viewport: null` is `no_viewport=True` in Python (used when headed, so the
page fills the window). No stealth, no user-agent change, no fingerprint flags.
"""
from __future__ import annotations

import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from ..config import ApplyConfig

# react-select's open menu. A bare [role="option"] also matches ~250 hidden
# intl-tel-input country items on Greenhouse (S-3), so the scope matters.
REACT_SELECT_OPTIONS = '.select__menu [role="option"]'
REACT_SELECT_CONTROL = ("xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '),"
                        " ' select__control ')][1]")
# Suggestions of a typeahead: react-select menus and ARIA listboxes.
SUGGESTION_OPTIONS = '.select__menu [role="option"], [role="listbox"] [role="option"]'

_SESSIONS: dict[int, "BrowserSession"] = {}      # id(context) -> session, for options_for


# ---------------------------------------------------------------- session

class BrowserSession:
    """One persistent-profile Edge for one `apply` job run (§8.1).

    The profile directory can be open in one process only; the web app's
    single job slot already guarantees that.
    """

    def __init__(self, cfg: ApplyConfig, *, profile_dir: Optional[str] = None):
        self.cfg = cfg
        self.profile_dir = os.path.expandvars(profile_dir or cfg.profile_dir)
        self._pw = None
        self._cm = None
        self.context = None

    def start(self) -> "BrowserSession":
        from playwright.sync_api import sync_playwright

        Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
        self._cm = sync_playwright()
        self._pw = self._cm.__enter__()
        kwargs: dict[str, Any] = dict(
            user_data_dir=self.profile_dir, channel="msedge", headless=not self.cfg.headed,
            ignore_default_args=["--disable-sync"] if self.cfg.edge_sync else None,
            locale="en-SG", timezone_id="Asia/Singapore", accept_downloads=False)
        if self.cfg.headed:
            kwargs["no_viewport"] = True
        try:
            self.context = self._pw.chromium.launch_persistent_context(**kwargs)
        except Exception:
            self._cm.__exit__(None, None, None)
            raise
        _SESSIONS[id(self.context)] = self
        return self

    __enter__ = start

    def new_page(self):
        """A tab for one attempt. The blank first tab of a fresh window is reused."""
        pages = self.context.pages
        if len(pages) == 1 and pages[0].url in ("about:blank", "") and not getattr(self, "_used_first", False):
            self._used_first = True
            return pages[0]
        return self.context.new_page()

    def hold(self, seconds: float) -> None:
        """Keep the window open for up to `seconds` (a dry run's filled form,
        F-37). Returns as soon as the owner closes the last tab or the window."""
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end:
            try:
                pages = self.context.pages
            except Exception:
                return
            if not pages:
                return
            try:                                  # a Playwright wait also pumps the close events
                pages[0].wait_for_timeout(min(1000.0, max(1.0, (end - time.monotonic()) * 1000)))
            except Exception:
                continue

    def close(self) -> None:
        if self.context is not None:
            _SESSIONS.pop(id(self.context), None)
            try:
                self.context.close()
            except Exception:
                pass
            self.context = None
        if self._cm is not None:
            try:
                self._cm.__exit__(None, None, None)
            except Exception:
                pass
            self._cm = self._pw = None

    def __exit__(self, *exc) -> None:
        self.close()


def options_for(page: Any) -> ApplyConfig:
    """The ApplyConfig of the session that opened `page` (the defaults for a
    page from elsewhere, e.g. a test's own browser)."""
    try:
        s = _SESSIONS.get(id(page.context))
    except Exception:
        s = None
    return s.cfg if s else ApplyConfig()


# ---------------------------------------------------------------- helpers

_QUOTES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'",
                         "“": '"', "”": '"', " ": " "})


def norm_text(s: Any) -> str:
    """Text as compared on screen: NFKC, straight quotes, case-folded, single
    spaces. (Not the resolver's label normaliser: that one also drops
    punctuation; this one only forgives typography.)"""
    s = unicodedata.normalize("NFKC", str(s or "")).translate(_QUOTES)
    return re.sub(r"\s+", " ", s).strip().casefold()


def slug(step: str) -> str:
    """A step id safe for a file name: [a-z0-9_-] (§8.3)."""
    return re.sub(r"[^a-z0-9_-]+", "-", str(step).lower()).strip("-") or "step"


def _page_of(loc: Any) -> Any:
    return loc.page


def _pause(page: Any, ms: Optional[int] = None) -> None:
    ms = options_for(page).action_pause_ms if ms is None else ms
    if ms > 0:
        page.wait_for_timeout(ms)


def _poll(page: Any, timeout_ms: int, fn: Callable[[], Any], step_ms: int = 100) -> Any:
    """Call `fn` until it returns something truthy or `timeout_ms` passes."""
    end = time.monotonic() + timeout_ms / 1000
    while True:
        got = fn()
        if got or time.monotonic() >= end:
            return got
        page.wait_for_timeout(step_ms)


def _texts(loc: Any) -> list[str]:
    try:
        return loc.all_inner_texts()
    except Exception:
        return []


def _pick_label(texts: Sequence[str], label: str) -> Optional[int]:
    """Index of the option equal to `label` (normalised), else of the ONLY
    option containing it, else None."""
    want = norm_text(label)
    normed = [norm_text(t) for t in texts]
    exact = [i for i, t in enumerate(normed) if t == want]
    if exact:
        return exact[0]
    contains = [i for i, t in enumerate(normed) if want and want in t]
    return contains[0] if len(contains) == 1 else None


# ---------------------------------------------------------------- fill primitives (§8.2)

def fill_text(loc: Any, value: str, *, type_delay_ms: Optional[int] = None) -> bool:
    """Fill and read back. Widgets that reformat (intl-tel-input adds spaces)
    are compared ignoring spaces; a mismatch gets one retry by typing."""
    value = "" if value is None else str(value)

    def same() -> bool:
        try:
            got = loc.input_value()
        except Exception:
            return False
        return re.sub(r"\s+", "", got) == re.sub(r"\s+", "", value)

    try:
        loc.fill(value)
        if same():
            return True
        delay = options_for(_page_of(loc)).type_delay_ms if type_delay_ms is None else type_delay_ms
        loc.fill("")
        loc.press_sequentially(value, delay=delay)
        return same()
    except Exception:
        return False


def _react_control_text(loc: Any) -> str:
    try:
        ctl = loc.locator(REACT_SELECT_CONTROL)
        if ctl.count():
            return ctl.first.inner_text()
    except Exception:
        pass
    return ""


def choose_react_select(page: Any, loc: Any, label: str, *,
                        type_delay_ms: Optional[int] = None, timeout_ms: int = 5000) -> bool:
    """Pick `label` in a react-select (S-3): click, type the first 30 chars,
    wait for the menu option equal to it (else the only one containing it),
    click that option, read the control's text back. Never presses Enter."""
    delay = options_for(page).type_delay_ms if type_delay_ms is None else type_delay_ms
    try:
        loc.click()
        loc.press_sequentially(str(label)[:30], delay=delay)
        opts = page.locator(REACT_SELECT_OPTIONS)
        idx = _poll(page, timeout_ms, lambda: _pick_label(_texts(opts), label))
        if idx is None:
            _abandon(loc)
            return False
        opts.nth(idx).click()
    except Exception:
        _abandon(loc)
        return False
    want = norm_text(label)
    return bool(_poll(page, 2000, lambda: want in norm_text(_react_control_text(loc))))


def _abandon(loc: Any) -> None:
    """Leave a search box as found: clear what we typed, close the menu."""
    try:
        loc.fill("")
        loc.press("Escape")
    except Exception:
        pass


def choose_native(loc: Any, label: str) -> bool:
    """A native <select>: choose by visible label, read the selected text back."""
    try:
        loc.select_option(label=label)
        got = loc.evaluate("e => e.selectedIndex >= 0 ? e.options[e.selectedIndex].text : ''")
        return norm_text(got) == norm_text(label)
    except Exception:
        return False


def choose_listbox(page: Any, button: Any, label: str, *, timeout_ms: int = 5000) -> bool:
    """An ARIA listbox behind a button (Workday): open it, click the option
    with exactly this text inside the open listbox, read the button back."""
    try:
        button.click()
        opts = page.locator('[role="listbox"] [role="option"]')

        def exact():
            want = norm_text(label)
            for i, t in enumerate(_texts(opts)):
                if norm_text(t) == want:
                    return i + 1          # 0 is a valid index: shift so it is truthy
            return None
        hit = _poll(page, timeout_ms, exact)
        if not hit:
            page.keyboard.press("Escape")
            return False
        opts.nth(hit - 1).click()
        return bool(_poll(page, 2000, lambda: norm_text(label) in norm_text(button.inner_text())))
    except Exception:
        return False


def choose_radio(container: Any, label: str) -> bool:
    """Click the radio whose label text equals `label` (normalised); verify
    it is checked."""
    want = norm_text(label)
    try:
        labels = container.locator("label")
        for i in range(labels.count()):
            lab = labels.nth(i)
            if norm_text(lab.inner_text()) != want:
                continue
            target = lab.get_attribute("for")
            inp = (container.page.locator(f'[id="{target}"]') if target
                   else lab.locator('input[type="radio"]'))
            lab.click()
            return inp.count() > 0 and inp.first.is_checked()
        radio = container.get_by_role("radio", name=label, exact=True)
        if radio.count():
            radio.first.check()
            return radio.first.is_checked()
    except Exception:
        pass
    return False


def set_checkbox(loc: Any, on: bool) -> bool:
    """Tick or untick one box and verify it."""
    try:
        if on:
            loc.check()
        else:
            loc.uncheck()
        return loc.is_checked() == bool(on)
    except Exception:
        return False


def typeahead(page: Any, loc: Any, text: str,
              pick: Callable[[list[str]], Optional[int]], *,
              options: str = SUGGESTION_OPTIONS, timeout_ms: int = 5000,
              type_delay_ms: Optional[int] = None) -> bool:
    """Type `text`, wait for suggestions (`options` selector), click the one
    `pick(labels)` returns the index of; None or no suggestion -> False.
    Reads back the input's value or its react-select control's text."""
    delay = options_for(page).type_delay_ms if type_delay_ms is None else type_delay_ms
    try:
        loc.click()
        loc.press_sequentially(str(text), delay=delay)
        opts = page.locator(options)
        labels = _poll(page, timeout_ms, lambda: [t for t in _texts(opts) if t.strip()])
        if not labels:
            _abandon(loc)
            return False
        idx = pick(_texts(opts))
        if idx is None:
            _abandon(loc)
            return False
        chosen = _texts(opts)[idx]
        opts.nth(idx).click()
    except Exception:
        _abandon(loc)
        return False
    want = norm_text(chosen)

    def shown() -> bool:
        try:
            val = loc.input_value()
        except Exception:
            val = ""
        return want in norm_text(val) or want in norm_text(_react_control_text(loc))
    return bool(_poll(page, 2000, shown))


def upload(loc: Any, path: str, *, timeout_ms: int = 15000) -> bool:
    """Attach a file to a (possibly hidden) file input; wait until its name
    shows on the page (or the input reports it)."""
    name = Path(path).name
    try:
        loc.set_input_files(path)
    except Exception:
        return False
    page = _page_of(loc)

    def shown() -> bool:
        try:
            files = loc.evaluate("e => Array.from(e.files || []).map(f => f.name)") or []
            if name not in files:
                return False
            body = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
        except Exception:
            return False
        return name in body or not _has_name_display(page)
    return bool(_poll(page, timeout_ms, shown, step_ms=250))


def _has_name_display(page: Any) -> bool:
    """Some forms never print the file name; then the input's own file list is
    the read-back. A page that prints names somewhere is expected to show it."""
    try:
        return page.locator(".file-name, [class*='file-name'], [class*='filename']").count() > 0
    except Exception:
        return False


def settle(page: Any, pause_ms: Optional[int] = None) -> None:
    """Let the page catch up: DOM loaded, network quiet (≤ 5 s), then the
    fixed NF-05 pause (`action_pause_ms`). No random jitter."""
    try:
        page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    _pause(page, pause_ms)


def pause(page: Any) -> None:
    """The fixed pause after each field (NF-05)."""
    _pause(page)


# ---------------------------------------------------------------- evidence (§8.3)

def screenshot(page: Any, attempt_dir: Path, seq: int, step: str) -> str:
    """Full-page `NN-<step>.png` in the attempt's folder; "" if the page is gone.
    File names never carry personal values (step ids only)."""
    attempt_dir = Path(attempt_dir)
    attempt_dir.mkdir(parents=True, exist_ok=True)
    path = attempt_dir / f"{seq:02d}-{slug(step)}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception:
        return ""
    return str(path)


def dump_html(page: Any, attempt_dir: Path) -> str:
    """The page's HTML as `failed.html` (on a failure); "" if unreadable."""
    attempt_dir = Path(attempt_dir)
    attempt_dir.mkdir(parents=True, exist_ok=True)
    path = attempt_dir / "failed.html"
    try:
        path.write_text(page.content(), encoding="utf-8")
    except Exception:
        return ""
    return str(path)
