"""The ONE helper behind every scripted model's answer to the D-220 place call (not a test file; no imports beyond `re`/`json`).

The place call (always.py `place_call`): system = SYSTEM_ALWAYS; the user message holds `QUESTION (JSON): "<label>"`,
`WANTED: ...`, `OPTIONS (JSON): ["NONE"]` and, LAST, a TASK line starting `Quote the words of QUESTION that say where the work
would be`; the schema is `{"quote": string}` and the reply is read from `quote`.

`sensible_quote(label)` is what a decent model quotes: the "outside ..." / "anywhere ..." / "any other country" phrase first; else the
words naming a country or place after in / within / for (a leading "in" is NOT part of the quote); else "NONE". It never invents
words: the result is always a substring of the label (or "NONE"). A test that needs a lying, garbage or not-in-the-label reply
scripts it explicitly (`FakeAsk(place=...)`); this default must never be what makes a WRONG-model test pass.
"""
from __future__ import annotations

import json
import re

PLACE_TASK_HEAD = "Quote the words of QUESTION"

_OPEN = re.compile(
    r"\b((?i:outside|other than|excluding|except|anywhere|any other country|any country|any location|abroad|overseas)"
    r"(?:\s+(?:of\s+|the\s+)?[A-Z][\w'.\-]*(?:\s+(?:of\s+|the\s+)?[A-Z][\w'.\-]*)*)?)")
_NAMED = re.compile(
    r"\b(?:in|within|for)\s+((?:the\s+)?[A-Z][\w'.\-]*(?:\s+(?:of\s+|the\s+)?[A-Z][\w'.\-]*)*)")


def is_place_call(user: str) -> bool:
    """True for the place call's user message (its LAST line is the TASK line)."""
    lines = (user or "").rstrip().splitlines()
    return bool(lines) and lines[-1].startswith(PLACE_TASK_HEAD) and "== FIELDS (JSON) ==" not in user


def label_of(user: str) -> str:
    """The label inside `QUESTION (JSON): "<label>"`."""
    m = re.search(r"^QUESTION \(JSON\): (.*)$", user, re.M)
    if not m:
        return ""
    try:
        return str(json.loads(m.group(1)))
    except ValueError:
        return m.group(1)


def sensible_quote(label: str) -> str:
    """What a sensible model quotes for `label`, or "NONE"."""
    m = _OPEN.search(label)
    if m:
        return m.group(1).strip()
    m = _NAMED.search(label)
    if m:
        return m.group(1).strip()
    return "NONE"
