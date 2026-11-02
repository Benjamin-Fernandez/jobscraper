"""Widget families: fill a field and read it back (D-78; llm_fill_design.md §3.2; WP-R2).

Generic on purpose: a widget dialect (a Workday prompt, a react-select, a
segmented date) is recognised by DOM pattern here, once for every site; a
navigator never fills (LF §9.4: a widget the families don't know is a change
to this file, not to a site module). Ported from the S-5b prototype
(`spikes/llm_fill/llmfill.py` fill, _choose_prompt, _type_date, file_decision;
`drive.py` wd_click), reusing the `browser.py` primitives.

    FAMILIES[name] = Family(detect, options, fill, read, reset)   the registry, in ORDER
    fill(page, pf, value, *, pick=None, force=False) -> bool    read back equal, no site error
    reset(page, pf) -> bool          empty / placeholder / untick (review H3, LF §7 G9)
    fill_field / reset_field         the same, returning Filled (read-back value + reason)
    read(page, pf) -> Value          what the field shows now
    error(page, pf) -> str           the site's error text for the field now
    same(pf, shown, value) -> bool   normalised equality (dates by role, multi as sets)
    detect(page, loc) -> str         the family of a control
    click(page, loc) -> str          click with the Workday click_filter fallbacks
                                     (navigators use it too; defined in page.py)

Rules (LF §3.2, review Q-35 M8, M14), all MUST:
  - Every family reads back: `fill` is ok only when the field then shows the
    intended value (normalised) and the site shows no error for it after blur.
    For a listbox that is the S-5b strict read-back (text shown, site value empty).
  - A search that finds nothing clears what was typed (never leaves search text).
  - Dates are typed by section role; a YYYY-MM value fills Day "01" only when the
    field has a Day section; equal dates ("2026-03" = "3/2026") are not retyped.
  - Multi-select: wrong pills are removed first, each wanted item added, the
    result compared as a set.
  - Upload: ok when the file name shows in the field's container within 30 s
    (Workday empties `input.files` after its own upload).
  - Enter is pressed only in a Workday prompt's search box, and never in an input
    inside a <form> that has a submit control (an implicit submit would bypass the
    submit-once guard, NF-06).

`pick`: the caller's option chooser for words that equal no option exactly
(LF §6.4 LL2/LL3); it gets (wanted words, visible options) and returns one of the
options or "". A widget never substitutes an option on its own (review Q-35-NR
F1): it takes the option equal to the decided value (normalised), or the leaf of
a "Category > Leaf" option equal to it, else only what `pick` returned; the
read-back must then equal the decided value, or the picked option where `pick`
chose. F9: the pick runs at fill time, after the guards, so the caller's `pick`
must carry the guard: R3 passes `llm_fill.pick_option` followed by the G4 check
(an option failing G4 -> ""), which validates the option before the click;
`Filled.picked` lists what `pick` chose for the audit. No model call here (NF-04).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from . import browser as B
from .contracts import FieldType, PageField, Value
from .page import (
    FIELD_ERROR_JS, HELPERS_JS, OPEN_WAIT_MS, PLACEHOLDER_RE, SHOWN_JS, blur_active, click,
    collect_options, date_parts, option_locator, selector, visible_options,
)

Picker = Callable[[str, Sequence[str]], str]

UPLOAD_TIMEOUT_S = 30          # LF §3.2: the file name must show within 30 s
SEARCH_WAIT_MS = 5000          # a search's results
MAX_LEVELS = 3                 # sub-lists followed when an option opens another list

ORDER = ("segmented_date", "file", "native_select", "aria_listbox", "prompt", "react_select",
         "combobox", "radio", "checkbox_group", "checkbox", "text")


@dataclass(frozen=True)
class Family:
    """One widget family (LF §3.2): how to recognise, list, fill and read a control.
    `fill(page, loc, value, pf, pick)` returns the value it set (the option text it
    chose) and raises FillMiss(note) when it could not; `fill()` below adds the
    read-back."""
    name: str
    detect: Callable[[Any, Any], bool]
    options: Callable[[Any, Any], list[str]]
    fill: Callable[[Any, Any, Value, PageField, Optional[Picker]], Value]
    read: Callable[[Any, Any], Value]
    reset: Callable[[Any, Any, PageField], bool]     # back to empty / the placeholder; False = can't


@dataclass(frozen=True)
class Filled:
    """The result of `fill` / `clear`: `shown` is what the page holds after the
    read-back (the audit value, review H3); `note` says why it failed (no values)."""
    ok: bool
    shown: Value
    error: str = ""
    note: str = ""             # unchanged | no_control | no_option | search_miss | readback | site_error
                               # | unsupported | not_decided
    picked: tuple[str, ...] = ()   # options the caller's `pick` chose (F9: for the audit and a re-check)


# ------------------------------------------------------------------ public API

def fill(page: Any, pf: PageField, value: Value, *, pick: Optional[Picker] = None,
         force: bool = False) -> bool:
    """True only when the field then shows `value` (normalised) and no site error
    (LF §3.2, review M14). `fill_field` gives the read-back and the reason."""
    return fill_field(page, pf, value, pick=pick, force=force).ok


def reset(page: Any, pf: PageField) -> bool:
    """True when the field reads back empty afterwards (`reset_field` for details)."""
    return reset_field(page, pf).ok


def fill_field(page: Any, pf: PageField, value: Value, *, pick: Optional[Picker] = None,
               force: bool = False) -> Filled:
    """Put `value` into the field and read it back (LF §3.2, review M14). A field that
    already shows the value without an error is left alone unless `force` (a file
    this attempt did not upload is replaced, review H6)."""
    loc = _loc(page, pf)
    if not _count(loc):
        return Filled(False, "", note="no_control")
    fam = FAMILIES.get(pf.widget) or FAMILIES["text"]
    if not force:
        shown, err = read(page, pf), error(page, pf)
        if same(pf, shown, value) and not err:
            return Filled(True, shown, note="unchanged")
    blur_active(page)                     # the site's blur validation runs before our click moves anything
    try:
        loc.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        pass
    note = ""
    picks: list[str] = []

    def recording(want: str, options: Sequence[str]) -> str:
        got = pick(want, options) if pick is not None else ""
        if got and any(B.norm_text(o) == B.norm_text(got) for o in options):
            picks.append(got)                 # only an offered option counts as picked
        return got
    try:
        chosen = fam.fill(page, loc, value, pf, recording if pick is not None else None)
    except FillMiss as miss:
        chosen, note = None, miss.note
    except Exception:
        chosen, note = None, "error"
    _blur(page, loc)
    B.pause(page)
    shown, err = read(page, pf), error(page, pf)
    picked = tuple(picks)
    if chosen is None:
        return Filled(False, shown, err, note=note or "no_option", picked=picked)
    if not _decided(pf, chosen, value, picked):
        return Filled(False, shown, err, note="not_decided", picked=picked)   # F1: never a substitute
    if err:
        return Filled(False, shown, err, note="site_error", picked=picked)
    # F1: the page must show the decided value (or, item by item, what `pick` chose)
    if not same(pf, shown, chosen if picked else value):
        return Filled(False, shown, err, note="readback", picked=picked)
    return Filled(True, shown, picked=picked)


def _decided(pf: PageField, chosen: Value, value: Value, picked: Sequence[str]) -> bool:
    """Every item a family set is the decided value's item (normalised; a
    "Category > Leaf" by its leaf) or an option the caller's `pick` returned."""
    if pf.field.type in (FieldType.MULTI_CHOICE,) or isinstance(chosen, list):
        allowed = {_choice_norm(v) for v in _as_list(value)} | {_choice_norm(p) for p in picked}
        return all(_choice_norm(c) in allowed for c in _as_list(chosen))
    if same(pf, chosen, value):
        return True
    return any(_choice_norm(chosen) == _choice_norm(p) for p in picked)


def reset_field(page: Any, pf: PageField) -> Filled:
    """Back to empty (LF §3.2, §7 G9; review H3): text cleared, a list back to its
    placeholder, pills and chips removed, boxes unticked, a file removed. ok only
    when the read-back is empty; a widget with no empty state (a radio group, a
    listbox without a placeholder option) reports note "unsupported"."""
    loc = _loc(page, pf)
    if not _count(loc):
        return Filled(False, "", note="no_control")
    blur_active(page)
    fam = FAMILIES.get(pf.widget) or FAMILIES["text"]
    try:
        done = fam.reset(page, loc, pf)
    except Exception:
        done = False
    _blur(page, loc)
    B.pause(page)
    shown = read(page, pf)
    empty = shown in ("", [], None) or (pf.field.type is FieldType.CHECKBOX and shown == "false")
    if not done:
        return Filled(empty, shown, error(page, pf), note="" if empty else "unsupported")
    return Filled(empty, shown, error(page, pf), note="" if empty else "readback")


def read(page: Any, pf: PageField) -> Value:
    """What the field shows now, in the reader's shape (LF §3.1 "Shown value")."""
    loc = _loc(page, pf)
    multi = pf.field.type is FieldType.MULTI_CHOICE
    try:
        v = loc.evaluate(SHOWN_JS, {"widget": pf.widget, "multi": multi})
    except Exception:
        return [] if multi else ""
    if multi:
        return [str(x) for x in (v or []) if str(x).strip()] if isinstance(v, list) else ([v] if v else [])
    return "; ".join(v) if isinstance(v, list) else ("" if v is None else str(v))


def error(page: Any, pf: PageField) -> str:
    """The site's error text for this field now ("" when none)."""
    try:
        return _loc(page, pf).evaluate(FIELD_ERROR_JS, {"widget": pf.widget}) or ""
    except Exception:
        return ""


def options(page: Any, pf: PageField) -> list[str]:
    """The field's options as the family lists them (opens lists behind buttons)."""
    fam = FAMILIES.get(pf.widget) or FAMILIES["text"]
    return fam.options(page, _loc(page, pf))


def detect(page: Any, loc: Any) -> str:
    """The family name of a control (the first in ORDER that recognises it), "" if none."""
    for name in ORDER:
        try:
            if FAMILIES[name].detect(page, loc):
                return name
        except Exception:
            continue
    return ""


def same(pf: PageField, shown: Value, value: Value) -> bool:
    """Shown value equals the intended one, as a person would read it: case, spacing
    typography and punctuation runs ignored (AD §7.1); a "Category > Leaf" path equals its leaf; multi values
    as sets; dates by role (LF §3.2: "2026-03" = "3/2026"); phones by digits;
    checkboxes as booleans; files by name."""
    kind = pf.field.type
    if kind is FieldType.MULTI_CHOICE or isinstance(value, list):
        a = {_choice_norm(x) for x in _as_list(shown)}
        b = {_choice_norm(x) for x in _as_list(value)}
        return a == b
    s, v = _as_text(shown), _as_text(value)
    if kind is FieldType.CHECKBOX:
        return _truthy(s) == _truthy(v)
    if kind is FieldType.DATE:
        return same_date(v, s, date_parts(pf))
    if kind is FieldType.FILE:
        return bool(v) and B.norm_text(Path(v).name) == B.norm_text(Path(s).name if s else "")
    if kind is FieldType.PHONE:
        ds, dv = re.sub(r"\D", "", s), re.sub(r"\D", "", v)
        return ds == dv if (ds or dv) else B.norm_text(s) == B.norm_text(v)
    if kind is FieldType.NUMBER:
        try:
            return float(s.replace(",", "")) == float(v.replace(",", ""))
        except ValueError:
            return B.norm_text(s) == B.norm_text(v)
    if kind in (FieldType.DROPDOWN, FieldType.RADIO, FieldType.TYPEAHEAD):
        return _choice_norm(s) == _choice_norm(v) or _value_norm(s) == _value_norm(v)
    return _text_norm(s) == _text_norm(v)


def same_date(value: str, shown: str, roles: Sequence[str] = ()) -> bool:
    """An ISO date ("2026-03", "2026-03-04", "2026") against a shown one: the reader's
    section values in page order ("3/2026") with their roles, or another ISO date.
    Compared by role (never by sorted numbers: 4/3 and 3/4 differ); a Day the value
    lacks counts as 1 (that is what we type)."""
    want = _iso_parts(value)
    if not want:
        return False
    got = _iso_parts(shown)
    if not got:
        nums = [int(n) for n in re.findall(r"\d+", shown or "")]
        if not nums:
            return False
        if roles and len(roles) == len(nums) and all(roles):
            got = dict(zip(roles, nums))
        elif len(nums) == 1:
            got = {"year": nums[0]}
        else:
            return False
    for role in ("year", "month", "day"):
        if role in got:
            w = want.get(role, 1 if role == "day" else None)
            if w is None or got[role] != w:
                return False
        elif role in want and roles and role in roles:
            return False
    return "year" in got


# ------------------------------------------------------------------ families: fill

class FillMiss(Exception):
    """A family could not set the value; `note` is a `Filled.note` code (no values)."""

    def __init__(self, note: str):
        super().__init__(note)
        self.note = note


def _fail(page: Any, note: str) -> Value:
    raise FillMiss(note)


def _fill_text(page: Any, loc: Any, value: Value, pf: PageField, pick: Optional[Picker]) -> Value:
    v = _as_text(value)
    if pf.field.type is FieldType.DATE:
        t = (_safe(lambda: loc.get_attribute("type"), "") or "").lower()
        if t == "date" and re.fullmatch(r"\d{4}-\d{2}", v):
            v += "-01"
        if t == "month":
            v = v[:7]
    if not B.fill_text(loc, v):
        return _fail(page, "readback")
    _safe(lambda: loc.press("Tab"), None)
    return v


def _fill_native(page: Any, loc: Any, value: Value, pf: PageField, pick: Optional[Picker]) -> Value:
    opts = [o.label for o in pf.field.options] or _static_options(page, loc, "native_select")
    wants = _as_list(value) if pf.field.type is FieldType.MULTI_CHOICE else [_as_text(value)]
    chosen = [_match(w, opts, pick) for w in wants]
    if not all(chosen):
        return _fail(page, "no_option")
    try:
        loc.select_option(label=chosen if pf.field.type is FieldType.MULTI_CHOICE else chosen[0])
    except Exception:
        return _fail(page, "no_option")
    return chosen if pf.field.type is FieldType.MULTI_CHOICE else chosen[0]


def _fill_listbox(page: Any, loc: Any, value: Value, pf: PageField, pick: Optional[Picker]) -> Value:
    want = _as_text(value)
    if not click(page, loc, timeout_ms=4000):
        return _fail(page, "no_control")
    try:
        got = _choose_in_open_list(page, want, pick)
    finally:
        if _list_open(page):
            _escape(page)
    if not got:
        return _fail(page, "no_option")
    # strict read-back (S-5b failure 6): the button shows the option; fill() then checks the error
    ok = B._poll(page, 2000, lambda: _choice_norm(_safe(loc.inner_text, "")) == _choice_norm(got))
    return got if ok else _fail(page, "readback")


def _fill_prompt(page: Any, loc: Any, value: Value, pf: PageField, pick: Optional[Picker]) -> Value:
    """Workday prompt (selectinput / promptOption / selectedItem pills). Port of the
    spike's _choose_prompt: wrong pills removed first; each wanted item: an option
    shown on open, else a search (typed; Enter only where safe), exact match first,
    then `pick`; sub-lists followed up to MAX_LEVELS; a "Category > Leaf" path is
    clicked level by level. Success = the leaves show as pills."""
    multi = pf.field.type is FieldType.MULTI_CHOICE
    wants = _as_list(value) if multi else [_as_text(value)]
    wants = [w for w in wants if w.strip()]
    if not wants:
        return _fail(page, "no_option")
    leaves = {_choice_norm(w) for w in wants}
    for _ in range(12):                                   # wrong pills out first
        pills = _pills(loc)
        wrong = [i for i, p in enumerate(pills) if _choice_norm(p) not in leaves]
        if not wrong:
            break
        if not _remove_pill(page, loc, wrong[0]):
            return _fail(page, "readback")
    chosen: list[str] = []
    for want in wants:
        if _choice_norm(want) in {_choice_norm(p) for p in _pills(loc)}:
            chosen.append(want.split(" > ")[-1].strip())
            continue
        got = _prompt_add(page, loc, want, pf, pick)
        if not got:
            _abandon_search(page, loc)
            return _fail(page, "search_miss")
        chosen.append(got)
    if _list_open(page):
        _escape(page)
    return chosen if multi else chosen[0]


def _prompt_add(page: Any, loc: Any, want: str, pf: PageField, pick: Optional[Picker]) -> str:
    if not click(page, loc, timeout_ms=4000):
        return ""
    opts = B._poll(page, OPEN_WAIT_MS, lambda: visible_options(page)) or []
    path = [p.strip() for p in want.split(" > ") if p.strip()]
    if len(path) > 1 and option_locator(page, path[0]) is not None:
        for part in path:                                  # "Category > Leaf", level by level
            o = B._poll(page, OPEN_WAIT_MS, lambda: option_locator(page, part))
            if o is None:
                return ""
            o.click(timeout=4000)
            page.wait_for_timeout(300)
        leaf = path[-1]
        ok = B._poll(page, 3000, lambda: _choice_norm(leaf) in {_choice_norm(p) for p in _pills(loc)})
        return leaf if ok else ""
    leaf = path[-1] if path else want
    if not any(B.norm_text(o) == B.norm_text(leaf) for o in opts):
        try:
            loc.fill("")
            loc.press_sequentially(leaf[:40], delay=B.options_for(page).type_delay_ms)
        except Exception:
            return ""
        if _enter_safe(loc):                               # the one allowed Enter (M8): a prompt's search box
            _safe(lambda: loc.press("Enter"), None)        # Workday prompts search on Enter
        opts = B._poll(page, SEARCH_WAIT_MS, lambda: [o for o in visible_options(page)
                                                      if not PLACEHOLDER_RE.match(o)]) or []
        if not opts:
            return ""
    for _level in range(MAX_LEVELS):
        choice = _match(leaf, opts, pick)
        if not choice:
            return ""
        target = option_locator(page, choice)
        if target is None:
            return ""
        target.click(timeout=4000)
        page.wait_for_timeout(300)
        after = visible_options(page)
        if after and after != opts and choice not in after:
            opts = after                                   # a sub-list opened
            continue
        ok = B._poll(page, 3000, lambda: _choice_norm(choice) in {_choice_norm(p) for p in _pills(loc)})
        return choice if ok else ""
    return ""


def _fill_react(page: Any, loc: Any, value: Value, pf: PageField, pick: Optional[Picker]) -> Value:
    """react-select (Greenhouse, AD §8.2): type the first 30 characters, pick the
    option equal to the words (normalised), else the caller's `pick`; never an
    option merely containing them (review F1). Multi: wrong chips removed first.
    Never presses Enter."""
    multi = pf.field.type is FieldType.MULTI_CHOICE
    wants = [w for w in (_as_list(value) if multi else [_as_text(value)]) if w.strip()]
    if not wants:
        return _fail(page, "no_option")
    ctl = loc.locator(B.REACT_SELECT_CONTROL).first
    if multi:
        keep = {_choice_norm(w) for w in wants}
        for _ in range(12):
            chips = ctl.locator(".select__multi-value")
            texts = [_safe(lambda i=i: chips.nth(i).locator(".select__multi-value__label").inner_text(), "")
                     for i in range(_count(chips))]
            wrong = [i for i, t in enumerate(texts) if _choice_norm(t) not in keep]
            if not wrong:
                break
            rm = chips.nth(wrong[0]).locator(".select__multi-value__remove")
            if not _count(rm) or not click(page, rm):
                return _fail(page, "readback")
            page.wait_for_timeout(150)
    chosen: list[str] = []
    for want in wants:
        if multi and _choice_norm(want) in {_choice_norm(t) for t in
                                            _safe(lambda: ctl.locator(".select__multi-value__label").all_inner_texts(), [])}:
            chosen.append(want)
            continue
        got = _react_pick(page, loc, want, pick)
        if not got:
            return _fail(page, "search_miss")
        chosen.append(got)
    return chosen if multi else chosen[0]


def _react_pick(page: Any, loc: Any, want: str, pick: Optional[Picker]) -> str:
    delay = B.options_for(page).type_delay_ms
    leaf = want.split(" > ")[-1].strip()
    try:
        click(page, loc)
        loc.fill("")
        loc.press_sequentially(leaf[:30], delay=delay)
        opts = page.locator(B.REACT_SELECT_OPTIONS)
        texts = B._poll(page, SEARCH_WAIT_MS, lambda: [t for t in B._texts(opts) if t.strip()]) or []
        choice = _match(leaf, texts, pick)
        if not choice:
            B._abandon(loc)
            return ""
        idx = [B.norm_text(t) for t in B._texts(opts)].index(B.norm_text(choice))
        opts.nth(idx).click(timeout=4000)
        return choice
    except Exception:
        B._abandon(loc)
        return ""


def _fill_combobox(page: Any, loc: Any, value: Value, pf: PageField, pick: Optional[Picker]) -> Value:
    want = _as_text(value).split(" > ")[-1].strip()
    if not want:
        return _fail(page, "no_option")
    picked: list[str] = []

    def chooser(labels: list[str]) -> Optional[int]:
        choice = _match(want, labels, pick)
        if not choice:
            return None
        picked.append(choice)
        return [B.norm_text(t) for t in labels].index(B.norm_text(choice))
    try:
        loc.fill("")
    except Exception:
        pass
    if not B.typeahead(page, loc, want[:40], chooser, options=B.SUGGESTION_OPTIONS):
        _abandon_search(page, loc)                        # M14: a miss leaves no typed text
        return _fail(page, "search_miss")
    return picked[-1] if picked else want


def _fill_radio(page: Any, loc: Any, value: Value, pf: PageField, pick: Optional[Picker]) -> Value:
    opts = [o.label for o in pf.field.options] or _static_options(page, loc, "radio")
    choice = _match(_as_text(value), opts, pick)
    if not choice:
        return _fail(page, "no_option")
    if B.choose_radio(loc, choice):
        return choice
    # a label covered by an overlay (Workday click_filter): click the radio itself
    for cand in (loc.get_by_role("radio", name=choice, exact=True), loc.get_by_label(choice, exact=True)):
        try:
            if _count(cand) and click(page, cand.first):
                return choice
        except Exception:
            continue
    return _fail(page, "readback")


def _fill_checkbox(page: Any, loc: Any, value: Value, pf: PageField, pick: Optional[Picker]) -> Value:
    on = _truthy(_as_text(value))
    if not _set_box(page, loc, on):
        return _fail(page, "readback")
    return "true" if on else "false"


def _fill_checkbox_group(page: Any, loc: Any, value: Value, pf: PageField, pick: Optional[Picker]) -> Value:
    opts = [o.label for o in pf.field.options] or _static_options(page, loc, "checkbox_group")
    wants = [_match(w, opts, pick) for w in _as_list(value)]
    if not all(wants):
        return _fail(page, "no_option")
    want = {B.norm_text(w) for w in wants}
    boxes = loc.locator('input[type="checkbox"], [role="checkbox"]')
    for i in range(_count(boxes)):
        box = boxes.nth(i)
        label = _safe(lambda: box.evaluate(_BOX_LABEL_JS), "")
        if not label:
            continue
        if not _set_box(page, box, B.norm_text(label) in want):
            return _fail(page, "readback")
    return list(wants)


def _fill_date(page: Any, loc: Any, value: Value, pf: PageField, pick: Optional[Picker]) -> Value:
    """Segmented date (Workday): each section typed by its role, never by position.
    A YYYY-MM value types Day "01" only when a Day section exists (port of _type_date)."""
    v = _as_text(value).strip()
    m = re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", v)
    if not m:
        return _fail(page, "no_option")
    y, mo, d = m.group(1), m.group(2), m.group(3)
    roles = date_parts(pf)
    sections = loc.locator('[role="spinbutton"], input[data-automation-id^="dateSection"]')
    n = _count(sections)
    if not n or (roles and len(roles) != n):
        roles = [_safe(lambda i=i: sections.nth(i).evaluate(_ROLE_JS), "") for i in range(n)]
    if "month" in roles and not mo:
        return _fail(page, "no_option")                    # a month the value doesn't give: never guessed
    for i, role in enumerate(roles):
        part = {"year": y, "month": (mo or "").zfill(2), "day": (d or "01").zfill(2)}.get(role, "")
        if not part:
            return _fail(page, "no_option")
        s = sections.nth(i)
        try:
            s.click(timeout=2000)
        except Exception:                                  # Workday lays a dateSection*-display div over it
            _safe(lambda: s.evaluate("e => e.focus()"), None)
        _safe(lambda: page.keyboard.press("Control+A"), None)
        page.keyboard.type(part, delay=B.options_for(page).type_delay_ms)
        page.wait_for_timeout(100)
    _safe(lambda: page.keyboard.press("Tab"), None)
    return v


def _fill_file(page: Any, loc: Any, value: Value, pf: PageField, pick: Optional[Picker]) -> Value:
    """Attach `value` (a local path). Another file shown in the field is removed
    first (D-70: the tailored resume replaces an imported one); ok when our name
    shows in the field's container within 30 s, or the input lists it when the
    page prints no names."""
    path = _as_text(value)
    name = Path(path).name
    if not path or not Path(path).is_file():
        return _fail(page, "no_option")
    old = _safe(lambda: loc.evaluate(SHOWN_JS, {"widget": "file", "multi": False}), "") or ""
    if old:
        _remove_files(page, loc)
        gone = B._poll(page, 5000, lambda: not (_safe(lambda: loc.evaluate(SHOWN_JS, {"widget": "file", "multi": False}), "") or ""))
        if not gone:
            return _fail(page, "readback")
    try:
        loc.set_input_files(path)
    except Exception:
        return _fail(page, "no_control")
    ok = B._poll(page, UPLOAD_TIMEOUT_S * 1000, lambda: _safe(lambda: loc.evaluate(_FILE_SHOWN_JS, name), False),
                 step_ms=250)
    return name if ok else _fail(page, "readback")


# ------------------------------------------------------------------ families: clear

def _clear_text(page: Any, loc: Any, pf: PageField) -> bool:
    if not B.fill_text(loc, ""):
        return False
    _safe(lambda: loc.press("Tab"), None)
    return True


def _clear_native(page: Any, loc: Any, pf: PageField) -> bool:
    try:
        if pf.field.type is FieldType.MULTI_CHOICE:
            loc.select_option([])
            return True
        first = loc.evaluate("e => e.options.length ? {v: e.options[0].value, t: e.options[0].text} : null")
        if first and (first["v"] == "" or PLACEHOLDER_RE.match(first["t"].strip())):
            loc.select_option(index=0)
            return True
    except Exception:
        pass
    return False


def _clear_listbox(page: Any, loc: Any, pf: PageField) -> bool:
    if not click(page, loc, timeout_ms=4000):
        return False
    try:
        opts = B._poll(page, OPEN_WAIT_MS, lambda: visible_options(page)) or []
        ph = next((o for o in opts if PLACEHOLDER_RE.match(o)), "")
        o = option_locator(page, ph) if ph else None
        if o is None:
            return False
        o.click(timeout=4000)
        return True
    finally:
        if _list_open(page):
            _escape(page)


def _clear_prompt(page: Any, loc: Any, pf: PageField) -> bool:
    for _ in range(12):
        if not _pills(loc):
            break
        if not _remove_pill(page, loc, 0):
            return False
    _abandon_search(page, loc)
    return not _pills(loc)


def _clear_react(page: Any, loc: Any, pf: PageField) -> bool:
    ctl = loc.locator(B.REACT_SELECT_CONTROL).first
    clear_btn = ctl.locator('.select__clear-indicator')
    if _count(clear_btn):
        return bool(click(page, clear_btn.first))
    removes = ctl.locator(".select__multi-value__remove")
    for _ in range(12):
        if not _count(removes):
            return True
        if not click(page, removes.first):
            return False
    return False


def _clear_checkbox(page: Any, loc: Any, pf: PageField) -> bool:
    return _set_box(page, loc, False)


def _clear_checkbox_group(page: Any, loc: Any, pf: PageField) -> bool:
    boxes = loc.locator('input[type="checkbox"], [role="checkbox"]')
    return all(_set_box(page, boxes.nth(i), False) for i in range(_count(boxes)))


def _clear_date(page: Any, loc: Any, pf: PageField) -> bool:
    sections = loc.locator('[role="spinbutton"], input[data-automation-id^="dateSection"]')
    for i in range(_count(sections)):
        s = sections.nth(i)
        try:
            s.click(timeout=2000)
        except Exception:
            _safe(lambda: s.evaluate("e => e.focus()"), None)
        _safe(lambda: page.keyboard.press("Control+A"), None)
        _safe(lambda: page.keyboard.press("Backspace"), None)
    return True


def _clear_file(page: Any, loc: Any, pf: PageField) -> bool:
    _remove_files(page, loc)
    _safe(lambda: loc.set_input_files([]), None)
    return bool(B._poll(page, 5000, lambda: not (_safe(lambda: loc.evaluate(
        SHOWN_JS, {"widget": "file", "multi": False}), "") or "")))


def _clear_radio(page: Any, loc: Any, pf: PageField) -> bool:
    return False                                           # a radio group has no empty state


_CLEARERS: dict[str, Callable[[Any, Any, PageField], bool]] = {
    "text": _clear_text, "combobox": _clear_text, "native_select": _clear_native,
    "aria_listbox": _clear_listbox, "prompt": _clear_prompt, "react_select": _clear_react,
    "checkbox": _clear_checkbox, "checkbox_group": _clear_checkbox_group,
    "segmented_date": _clear_date, "file": _clear_file, "radio": _clear_radio,
}



# ------------------------------------------------------------------ families: detect, options, read

_DETECT_JS = {
    "segmented_date": "e => e.matches('[role=\"spinbutton\"], input[data-automation-id^=\"dateSection\"]') || "
                      "!!e.querySelector('[role=\"spinbutton\"], input[data-automation-id^=\"dateSection\"]')",
    "file": "e => e.matches('input[type=\"file\"]')",
    "native_select": "e => e.tagName === 'SELECT'",
    "aria_listbox": "e => e.matches('button[aria-haspopup=\"listbox\"]') || (e.getAttribute('role') === 'combobox' "
                    "&& !['INPUT', 'TEXTAREA'].includes(e.tagName) && !e.querySelector('input, textarea'))",
    "prompt": "e => e.tagName === 'INPUT' && (e.getAttribute('data-uxi-widget-type') === 'selectinput' || "
              "!!(e.closest('[data-automation-id^=\"formField-\"]') && e.closest('[data-automation-id^=\"formField-\"]')"
              ".querySelector('[data-automation-id=\"multiSelectContainer\"], [data-automation-id=\"selectedItemList\"]')))",
    "react_select": "e => !!e.closest('.select__control') || /\\bselect__input\\b/.test(e.className || '')",
    "combobox": "e => e.getAttribute('role') === 'combobox' || "
                "['list', 'both'].includes((e.getAttribute('aria-autocomplete') || '').toLowerCase())",
    "radio": "e => e.matches('input[type=\"radio\"], [role=\"radio\"]') || "
             "(!e.matches('input') && !!e.querySelector('input[type=\"radio\"], [role=\"radio\"]'))",
    "checkbox_group": "e => !e.matches('input') && e.querySelectorAll('input[type=\"checkbox\"], [role=\"checkbox\"]').length > 1",
    "checkbox": "e => e.matches('input[type=\"checkbox\"], [role=\"checkbox\"]')",
    "text": "e => e.matches('input, textarea')",
}

_STATIC_OPTIONS_JS = "(el, w) => {" + HELPERS_JS + r"""
  if (w === 'native_select') return [...el.options].filter((o, i) => o.text.trim() && !(o.value === '' && i === 0) && !PLACEHOLDER.test(o.text.trim())).map(o => o.text.replace(/\s+/g, ' ').trim());
  if (w === 'radio' || w === 'checkbox_group') return unitOf(el, w).map(radioText);
  return [];
}
"""

_BOX_LABEL_JS = "(el) => {" + HELPERS_JS + "return radioText(el); }"

_ROLE_JS = r"""e => { const s = ((e.getAttribute('aria-label') || '') + ' ' + (e.getAttribute('data-automation-id') || '')).toLowerCase();
  return /day/.test(s) ? 'day' : /month/.test(s) ? 'month' : /year/.test(s) ? 'year' : ''; }"""

# Our file's name shows in the field's container, or the input lists it when the page prints no names.
_FILE_SHOWN_JS = "(el, name) => {" + HELPERS_JS + r"""
  const cont = containerOf(el);
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  if (cont && norm(txt(cont)).includes(norm(name))) return true;
  const files = [...(el.files || [])].map(f => f.name);
  return files.includes(name) && !(cont && FILE_RE.test(txt(cont)));
}
"""

# Review M8 / LF §3.2: Enter only outside a <form> that has a submit control: [type=submit],
# a <button> with no type (a submit button by HTML's default), a button named Submit, or no
# submit control but a single text-like input (HTML's implicit submission submits that form too).
_ENTER_SAFE_JS = r"""e => { const f = e.form || e.closest('form'); if (!f) return true;
  if (f.querySelector('[type="submit"], button:not([type]), input[type="image"]')) return false;
  if ([...f.querySelectorAll('button, [role="button"], input[type="button"]')].some(b => /^\s*submit\b/i.test(b.innerText || b.value || b.getAttribute('aria-label') || ''))) return false;
  const blocking = [...f.querySelectorAll('input')].filter(i => ['text', 'search', 'url', 'tel', 'email', 'password', 'date', 'month', 'week', 'time', 'datetime-local', 'number', ''].includes((i.getAttribute('type') || '').toLowerCase()));
  return blocking.length > 1; }"""


def _detector(name: str) -> Callable[[Any, Any], bool]:
    js = _DETECT_JS[name]
    return lambda page, loc: bool(loc.evaluate(js))


def _static_options(page: Any, loc: Any, widget: str) -> list[str]:
    return _safe(lambda: loc.evaluate(_STATIC_OPTIONS_JS, widget), []) or []


def _options_for(widget: str) -> Callable[[Any, Any], list[str]]:
    if widget in ("aria_listbox", "prompt", "react_select", "combobox"):
        return lambda page, loc: collect_options(page, loc, widget)[0]
    return lambda page, loc: _static_options(page, loc, widget)


def _reader_for(widget: str) -> Callable[[Any, Any], Value]:
    return lambda page, loc: _safe(lambda: loc.evaluate(SHOWN_JS, {"widget": widget, "multi": False}), "")


_FILLERS: dict[str, Callable[..., Value]] = {
    "segmented_date": _fill_date, "file": _fill_file, "native_select": _fill_native,
    "aria_listbox": _fill_listbox, "prompt": _fill_prompt, "react_select": _fill_react,
    "combobox": _fill_combobox, "radio": _fill_radio, "checkbox_group": _fill_checkbox_group,
    "checkbox": _fill_checkbox, "text": _fill_text,
}

FAMILIES: dict[str, Family] = {
    name: Family(name=name, detect=_detector(name), options=_options_for(name),
                 fill=_FILLERS[name], read=_reader_for(name), reset=_CLEARERS[name])
    for name in ORDER
}


# ------------------------------------------------------------------ helpers

def _loc(page: Any, pf: PageField) -> Any:
    return page.locator(pf.field.locator or selector(pf.field.key)).first


def _count(loc: Any) -> int:
    return _safe(loc.count, 0) or 0


def _safe(fn: Callable[[], Any], default: Any) -> Any:
    try:
        return fn()
    except Exception:
        return default


def _escape(page: Any) -> None:
    _safe(lambda: page.keyboard.press("Escape"), None)
    _safe(lambda: page.wait_for_timeout(150), None)


def _blur(page: Any, loc: Any) -> None:
    blur_active(page)


def _list_open(page: Any) -> bool:
    return bool(visible_options(page))


def _enter_safe(loc: Any) -> bool:
    """Review M8: Enter only where no implicit form submit can follow."""
    return bool(_safe(lambda: loc.evaluate(_ENTER_SAFE_JS), False))


def _abandon_search(page: Any, loc: Any) -> None:
    """Leave a search box empty and its list closed (M14: a miss clears the typed text)."""
    _safe(lambda: loc.fill(""), None)
    _escape(page)


def _pills(loc: Any) -> list[str]:
    return _safe(lambda: loc.evaluate(SHOWN_JS, {"widget": "prompt", "multi": True}), []) or []


def _remove_pill(page: Any, loc: Any, index: int) -> bool:
    """Remove the index-th chosen pill of a prompt (its DELETE_charm, else the pill)."""
    before = len(_pills(loc))
    ff = loc.locator('xpath=ancestor::*[starts-with(@data-automation-id,"formField-")][1]')
    scope = ff.first if _count(ff) else loc.locator("xpath=ancestor::*[.//*[@data-automation-id='selectedItem']][1]").first
    pill = scope.locator('[data-automation-id="selectedItem"]').nth(index)
    charm = pill.locator('[data-automation-id="DELETE_charm"]')
    target = charm.first if _count(charm) else pill
    if not click(page, target):
        return False
    return bool(B._poll(page, 2000, lambda: len(_pills(loc)) < before))


def _remove_files(page: Any, loc: Any) -> None:
    """Click the remove/delete control(s) next to an attached file."""
    cont = loc.locator('xpath=ancestor::*[starts-with(@data-automation-id,"formField-")][1]')
    if not _count(cont):
        cont = loc.locator("xpath=ancestor::*[.//button][1]")
    if not _count(cont):
        return
    rx = re.compile(r"\b(remove|delete)\b", re.I)
    for _ in range(4):
        btns = cont.first.get_by_role("button", name=rx)
        if not _count(btns):
            btns = cont.first.locator('[aria-label*="remove" i], [aria-label*="delete" i], [data-automation-id*="delete" i]')
        if not _count(btns):
            return
        if not click(page, btns.first):
            return
        page.wait_for_timeout(300)


def _set_box(page: Any, loc: Any, on: bool) -> bool:
    """Tick/untick one box; a styled box is clicked through its label or click_filter."""
    if B.set_checkbox(loc, on):
        return True
    state = lambda: _safe(lambda: loc.evaluate(  # noqa: E731
        "e => e.tagName === 'INPUT' ? e.checked : e.getAttribute('aria-checked') === 'true'"), None)
    if state() == on:
        return True
    lab_id = _safe(lambda: loc.get_attribute("id"), "")
    if lab_id:
        lab = page.locator(f'label[for="{lab_id}"]')
        if _count(lab):
            _safe(lambda: lab.first.click(timeout=3000), None)
            if state() == on:
                return True
    click(page, loc)
    return state() == on


def _choose_in_open_list(page: Any, want: str, pick: Optional[Picker]) -> str:
    """In an open listbox: the option equal to `want` (or each level of a
    "Category > Leaf" path), else `pick`; clicked. Returns the option clicked."""
    path = [p.strip() for p in want.split(" > ") if p.strip()] or [want]
    opts = B._poll(page, OPEN_WAIT_MS, lambda: [o for o in visible_options(page) if not PLACEHOLDER_RE.match(o)]) or []
    if len(path) > 1 and option_locator(page, path[0]) is not None:
        for part in path:
            o = B._poll(page, OPEN_WAIT_MS, lambda: option_locator(page, part))
            if o is None:
                return ""
            o.click(timeout=4000)
            page.wait_for_timeout(200)
        return path[-1]
    choice = _match(path[-1], opts, pick)
    if not choice:
        return ""
    o = option_locator(page, choice)
    if o is None:
        return ""
    o.click(timeout=4000)
    return choice


def _match(want: str, options: Sequence[str], pick: Optional[Picker]) -> str:
    """The option equal to `want` (on-screen text, else the only one equal under AD §7.1
    normalisation, as `same` reads back), else the only option whose "Category > Leaf"
    leaf equals it, else `pick(want, options)` when it returns one of the options.
    Never a near match ("Computer Engineering Technology" for "Computer Engineering",
    "JavaScript" for "Java"): that is the caller's pick or a miss (review F1)."""
    if not want or not options:
        return ""
    w = B.norm_text(want)
    for o in options:
        if B.norm_text(o) == w:
            return o
    hits = [o for o in options if _value_norm(o) == _value_norm(want)]
    if len(hits) == 1:
        return hits[0]
    leaf = _choice_norm(want)
    hits = [o for o in options if _choice_norm(o) == leaf]
    if len(hits) == 1:
        return hits[0]
    if pick is not None:
        try:
            got = pick(want, list(options))
        except Exception:
            got = ""
        if got and any(B.norm_text(o) == B.norm_text(got) for o in options):
            return next(o for o in options if B.norm_text(o) == B.norm_text(got))
    return ""


def _as_list(v: Value) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    s = str(v)
    return [p.strip() for p in s.split(";") if p.strip()] if ";" in s else ([s] if s.strip() else [])


def _as_text(v: Value) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return str(v)


def _truthy(s: str) -> bool:
    return B.norm_text(s) in ("true", "yes", "y", "1", "checked", "on")


def _value_norm(s: Any) -> str:
    """A value as AD §7.1 compares it (steps 1-4 and 6: typography, case, punctuation
    runs to one space) without step 5: a leading number is part of a value ("1 year")."""
    t = B.norm_text(s).replace("(required)", " ").replace("(optional)", " ")
    t = re.sub(r"[^\w+#']+", " ", t).replace("_", " ")
    return re.sub(r"\s+", " ", re.sub(r"(^|\s)'|'(\s|$)", " ", t)).strip()


def _choice_norm(s: Any) -> str:
    return _value_norm(str(s or "").split(" > ")[-1])


def _text_norm(s: str) -> str:
    return _value_norm(s)


def _iso_parts(s: str) -> dict[str, int]:
    m = re.fullmatch(r"\s*(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?\s*", s or "")
    if not m:
        return {}
    out = {"year": int(m.group(1))}
    if m.group(2):
        out["month"] = int(m.group(2))
    if m.group(3):
        out["day"] = int(m.group(3))
    return out
