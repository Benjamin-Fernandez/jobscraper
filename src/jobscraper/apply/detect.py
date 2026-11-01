"""Which ATS a job is on, and the tenant to apply to (apply_design §9.0, F-31).

Order: the company's watchlist provider when an adapter of that name is
registered (its `tenant_from_company`), then every adapter's `match_url` on the
job's URL in registry order. Neither -> ApplyFailure(UNSUPPORTED_ATS) naming the
provider or the URL's host (no personal value can be in either).
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from .ats import REGISTRY
from .contracts import ApplyFailure, AtsAdapter, ReasonCode, Tenant


def detect(job: dict[str, Any]) -> tuple[AtsAdapter, Tenant]:
    provider = str(job.get("provider") or "").strip().lower()
    adapter = REGISTRY.get(provider)
    if adapter is not None:
        tenant = adapter.tenant_from_company(job)
        if tenant is not None:
            return adapter, tenant
    url = str(job.get("url") or "")
    for adapter in REGISTRY.values():
        tenant = adapter.match_url(url)
        if tenant is not None:
            return adapter, tenant
    raise ApplyFailure(ReasonCode.UNSUPPORTED_ATS,
                       provider or urlsplit(url).netloc.lower() or "no URL", step="planning")
