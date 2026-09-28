"""Find careers sites for the user's own list of companies (M16).

The user uploads a list - one company per line, in their order of preference -
and this works through it, in that order:

1. **Already watched?** A company whose name or key matches one being watched
   (watchlist.yaml, or found from an earlier list) is `watched`: nothing to find.
2. **Ask Qwen** where the company's careers page is (batched, ten names a
   call). Qwen answers from what it knows; it cannot browse, so its answer is a
   lead, never trusted on its own - and it is told to say null rather than guess.
3. **Prove it with discovery** (scrape/discovery.py): the careers URL is
   fingerprinted and sniffed for a known job board, and the name itself is
   probed against the boards' public APIs - so a company Qwen does not know can
   still be found.
4. **Read the board once.** Only a board that answers counts: the company is
   `found`, with how many roles it has open. Anything else is `failed`, with
   the reason in words.

A found company is then watched like any other: `watchlist.all_entries` syncs
it into `companies` beside watchlist.yaml's entries, so the next run scrapes
it - new ones first, in the user's order.

The plan caps how many companies a list may add (`Plan.max_companies`; the
owner's `local` plan has no cap). Only `found` and `watched` companies count:
a failed search costs nothing. Once the cap is reached the rest of the list is
`over_limit` - kept, and searched again if the cap allows later.

This module composes stages (discovery, the adapters, the model), so like
pipeline.py it is an orchestrator: only the CLI imports it.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from . import backends
from .config import Config
from .models import WatchedCompany
from .scrape import discovery
from .scrape.adapters import get_adapter
from .scrape.net import FetchError, HttpClient
from .store import Store, utcnow
from . import watchlist
from .watchlist import slugify

BATCH = 10

# Where each ATS's public board lives, for a company found by name alone.
BOARD_URLS = {
    "greenhouse": "https://job-boards.greenhouse.io/{slug}",
    "lever": "https://jobs.lever.co/{slug}",
    "ashby": "https://jobs.ashbyhq.com/{slug}",
    "smartrecruiters": "https://jobs.smartrecruiters.com/{slug}",
    "workable": "https://apply.workable.com/{slug}",
    "recruitee": "https://{slug}.recruitee.com",
}

SYSTEM_PROMPT = """\
You find the official careers pages of companies.

For each company name, give the company's official website and the URL of its
careers or jobs page, if you know them. The user is in Singapore: when a name
is ambiguous, prefer the company with a Singapore presence. If you are not sure
the company exists, or do not know its website, answer null for both - never
guess or invent a domain.

Reply with ONLY this JSON object:
{"companies": [{"name": "<the name exactly as given>",
                "website": "https://..." or null,
                "careers_url": "https://..." or null}, ...]}"""


def lookup_sites(backend: Any, names: list[str]) -> dict[str, Optional[str]]:
    """Qwen's lead on each company's careers page: lowercase name -> URL or
    None. A failed call is no leads at all - discovery still tries by name."""
    if not names or not getattr(backend, "available", False):
        return {}
    user = ("<companies>\n" + "\n".join(names) + "\n</companies>\n\n"
            "Respond with ONLY the JSON object described in the system prompt, "
            "one item per company, names exactly as given. Start with `{`.")
    try:
        comp = backend.complete(system=SYSTEM_PROMPT, user=user, max_tokens=2000)
    except backends.BackendError:
        return {}
    raw = _json(comp.text)
    out: dict[str, Optional[str]] = {}
    for item in raw.get("companies") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        url = _http(item.get("careers_url")) or _http(item.get("website"))
        out[str(item["name"]).strip().lower()] = url
    return out


def search(cfg: Config, store: Store, *, backend: Any = None,
           client: Optional[HttpClient] = None,
           resolve: Callable = discovery.resolve,
           fetch: Optional[Callable] = None,
           say: Callable[[str], Any] = print) -> dict[str, int]:
    """Search every company of the list not searched yet, in the user's order.
    Writes each result as soon as it is known, so the web app can show
    progress. Returns the list's counts by status."""
    plan = cfg.plan
    cap = plan.max_companies
    rows = store.company_list()
    counted = sum(1 for r in rows if r["status"] in ("found", "watched"))
    todo = [r for r in rows if r["status"] in ("pending", "searching", "over_limit")]
    say(f"company list: {len(rows)} companies, {len(todo)} to search"
        + (f", plan {plan.name} allows {cap}" if cap is not None else ""))

    known = _watched(store)
    backend = backend or backends.build(cfg.budget)
    if client is None:
        rc = cfg.run
        client = HttpClient(str(rc.get("user_agent", "JobScraper/2.0")),
                            timeout=float(rc.get("request_timeout", 25)),
                            delay=float(rc.get("rate_limit_delay", 0.7)), max_retries=1,
                            respect_robots=bool(rc.get("respect_robots", True)))

    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        unknown = [r["name"] for r in chunk if _match(known, r["name"]) is None]
        leads = lookup_sites(backend, unknown)
        for r in chunk:
            pos = r["position"]
            if cap is not None and counted >= cap:
                store.update_company_list_entry(
                    pos, status="over_limit", searched_at=None,
                    detail=f"the {plan.name} plan adds up to {cap} companies - not searched")
                say(f"  {pos:>4}. {r['name']}: over the plan's limit")
                continue
            store.update_company_list_entry(pos, status="searching", detail=None)
            result = _search_one(r["name"], known, leads.get(r["name"].lower()),
                                 client, resolve, fetch)
            store.update_company_list_entry(pos, searched_at=utcnow(), **result)
            if result["status"] in ("found", "watched"):
                counted += 1
            say(f"  {pos:>4}. {r['name']}: {result['status']} - {result['detail']}")

    # Watch what was found now, not at the next run: the Settings tab's company
    # count and the next run's due list both see it at once.
    store.sync_watchlist(watchlist.all_entries(cfg.watchlist_path, store))

    counts: dict[str, int] = {}
    for r in store.company_list():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts


# ---------------------------------------------------------------- one company

def _search_one(name: str, known: dict[str, WatchedCompany], lead: Optional[str],
                client: HttpClient, resolve: Callable,
                fetch: Optional[Callable]) -> dict[str, Any]:
    hit = _match(known, name)
    if hit is not None:
        return {"status": "watched", "company_key": hit.key, "careers_url": hit.careers_url,
                "provider": hit.provider, "slug": hit.slug, "feed_url": hit.feed_url,
                "postings": None, "detail": f"already watched as {hit.name}"}

    company = WatchedCompany(id=0, key=slugify(name) or name.lower(), name=name,
                             careers_url=lead or "")
    try:
        res = resolve(client, company)
    except Exception as exc:  # noqa: BLE001 - a bad site must not stop the list
        return _failed(f"could not look for a job board ({type(exc).__name__})")
    if not res.ok:
        why = "no careers site found" if not lead else "no job board found on its careers site"
        return _failed(why + ("" if lead else " (Qwen did not know one either)"))

    company.provider, company.slug, company.feed_url = res.provider, res.slug, res.feed_url
    try:
        jobs = (fetch or _fetch)(client, company)
    except FetchError as exc:
        return _failed(f"found a {res.provider} board but could not read it ({exc.kind})")
    except Exception as exc:  # noqa: BLE001
        return _failed(f"found a {res.provider} board but could not read it ({type(exc).__name__})")

    url = company.careers_url or _board_url(res.provider, res.slug) or res.feed_url or ""
    where = "its careers page" if res.provider == "generic_html" else f"a {res.provider} board"
    return {"status": "found", "company_key": company.key, "careers_url": url,
            "provider": res.provider, "slug": res.slug, "feed_url": res.feed_url,
            "postings": len(jobs),
            "detail": f"{where}, {len(jobs)} open role{'' if len(jobs) == 1 else 's'}"}


def _fetch(client: HttpClient, company: WatchedCompany) -> list:
    adapter = get_adapter(company.provider)
    if adapter is None:
        raise FetchError("schema", f"no adapter for {company.provider!r}")
    return adapter.fetch(client, company)


def _failed(detail: str) -> dict[str, Any]:
    return {"status": "failed", "company_key": None, "careers_url": None, "provider": None,
            "slug": None, "feed_url": None, "postings": None, "detail": detail}


def _watched(store: Store) -> dict[str, WatchedCompany]:
    """Enabled companies by lowercase name and by key."""
    out: dict[str, WatchedCompany] = {}
    for c in store.companies(enabled_only=True):
        out.setdefault(c.name.lower(), c)
        out.setdefault(c.key, c)
    return out


def _match(known: dict[str, WatchedCompany], name: str) -> Optional[WatchedCompany]:
    return known.get(name.lower()) or known.get(slugify(name))


def _board_url(provider: Optional[str], slug: Optional[str]) -> Optional[str]:
    pattern = BOARD_URLS.get(provider or "")
    return pattern.format(slug=slug) if pattern and slug else None


def _http(v: Any) -> Optional[str]:
    s = str(v or "").strip()
    return s if re.match(r"^https?://[^\s/]+\.[^\s]+", s) else None


def _json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        out = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        try:
            out = json.loads(m.group(0)) if m else {}
        except ValueError:
            out = {}
    return out if isinstance(out, dict) else {}
