"""The ATS modules auto-apply knows (apply_design §9, §15; llm_fill_design §9).

REGISTRY maps a name - equal to the watchlist provider - to one instance per
ATS. Detection (`apply/detect.py`) tries them in this order. Under D-78 an
entry implements `apply.contracts.SiteNavigator` (navigation only); Greenhouse
also keeps the older `AtsAdapter` fill-side methods until the cleanup WP-C1.
Adding an ATS is one line here plus its module (llm_fill_design §9.4).
"""
from __future__ import annotations

from typing import Any

from .greenhouse import ADAPTER as _GREENHOUSE
from .workday import NAVIGATOR as _WORKDAY

REGISTRY: dict[str, Any] = {        # AtsAdapter (pre-D-78 path) and/or SiteNavigator
    "greenhouse": _GREENHOUSE,
    "workday": _WORKDAY,
}
