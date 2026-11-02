"""Shared helpers for the D-70 apply oracles (not a test file: the runner ignores it).

Test files do `sys.path.insert(0, str(Path(__file__).parent))` then `from apply_support import ...`.
`needs` works as in tests/test_apply_contracts.py: the decorated test is not defined (the runner
never sees it) until the named module / attribute exists; one line at import says what waits.
"""
from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FIX = ROOT / "tests" / "fixtures" / "apply"
SAMPLE = FIX / "applicant.sample.yaml"

WAITING: list[tuple[str, str]] = []


def missing(spec: str) -> str:
    """'' if `spec` (`module` or `module:Attr.attr`) is importable, else what is missing."""
    mod, _, attr = spec.partition(":")
    try:
        obj = importlib.import_module(mod)
    except ModuleNotFoundError as e:
        if e.name and (mod == e.name or mod.startswith(e.name + ".")):
            return mod
        raise
    for part in filter(None, attr.split(".")):
        if not hasattr(obj, part):
            return spec
        obj = getattr(obj, part)
    return ""


def needs(*specs: str):
    gone = [m for m in (missing(s) for s in specs) if m]

    def deco(fn):
        if gone:
            WAITING.append((fn.__name__, gone[0]))
            return None
        return fn
    return deco


def profile(**contact) -> dict:
    p = copy.deepcopy(yaml.safe_load(SAMPLE.read_text(encoding="utf-8")))
    p["contact"].update(contact)
    return p
