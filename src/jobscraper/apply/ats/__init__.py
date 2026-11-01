"""The ATS adapters auto-apply knows (apply_design §9, §15).

REGISTRY maps a name - equal to the watchlist provider - to one adapter
instance implementing `apply.contracts.AtsAdapter`. Detection (`apply/detect.py`)
tries them in this order. Adding an ATS is one line here plus its module
(apply_design §15); M21 lanes each add their own line.
"""
from __future__ import annotations

from ..contracts import AtsAdapter

REGISTRY: dict[str, AtsAdapter] = {}
