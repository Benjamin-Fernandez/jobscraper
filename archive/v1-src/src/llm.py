"""Stage C1 (extraction), C2 (adjudication) and D (second opinion).

Every result is cached by content hash, so a posting is never judged twice.
Which model does the judging is a transport question, answered by backends.py -
by default `claude -p`, the Claude Code CLI, which needs no API key. If no
transport is available the whole layer is skipped and the pipeline falls back to
rules plus local scoring.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

from . import backends
from .backends import BackendError
from .config import Profile
from .matching import extract_requirements
from .models import Candidate, JobFacts, TokenLedger, Verdict
from .store_v1 import Store

EXTRACT_SYSTEM = (
    "You extract structured facts from job postings. Return ONLY valid JSON. "
    "Never guess: use null when the posting does not say."
)

EXTRACT_INSTRUCTIONS = """For each job return an object with exactly these keys:
  id                    the id given
  countries             array of country names the role is based in, normalized
                        (e.g. ["Singapore"]). Empty array if truly unstated.
  is_singapore          true if the role can be based in Singapore, else false,
                        null if genuinely unstated
  seniority             one of: intern, new_grad, junior, mid, senior, lead, unknown
  yoe_min               minimum years of experience required, integer or null
  yoe_max               maximum years, integer or null
  intake_year           graduate-programme intake year as an integer, or null
  is_graduate_programme true if this is a structured graduate/associate programme
  sponsorship           one of: yes, no, unclear  (visa/work-pass sponsorship)
  role_family           one of: backend, infra, platform, quant_dev, sre, data,
                        ml, fullstack, frontend, embedded, security, other
  tech_stack            array of up to 8 lowercase technology names
  requires_clearance    true if security clearance or citizenship is required
Return {"results": [ ... ]} and nothing else."""

VERDICT_SYSTEM = (
    "You screen graduate software engineering roles for one candidate. "
    "Be decisive and concrete. Return ONLY valid JSON."
)

VERDICT_INSTRUCTIONS = """For each job return an object with exactly these keys:
  id          the id given
  verdict     one of: strong, possible, weak, reject
  confidence  a number between 0 and 1
  reason      at most 25 words, concrete: name the specific overlap or gap
  concerns    array of at most 3 short strings, or []
Judge fit for a graduating-2026 candidate seeking a first full-time role in
Singapore. Reject roles requiring substantial professional experience, roles
outside Singapore, internships, and non-engineering functions.
Return {"results": [ ... ]} and nothing else."""


def _key(job_id: str, jd_hash: str, pv: int, stage: str) -> str:
    return hashlib.sha256(
        f"{job_id}|{jd_hash}|{pv}|{stage}".encode()).hexdigest()[:32]


def _parse_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {}


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i:i + size] for i in range(0, len(items), max(size, 1))]


def _int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


class Judge:
    def __init__(self, profile: Profile, store: Store, budget: dict[str, Any],
                 ledger: TokenLedger, verbose: bool = True):
        self.profile = profile
        self.store = store
        self.budget = budget
        self.ledger = ledger
        self.verbose = verbose
        self.pv = profile.version
        self.backend = backends.build(budget)
        # A transport that is down stays down: a logged-out CLI would otherwise
        # burn its full timeout on every batch in the run.
        self.max_failures = int(budget.get("max_consecutive_failures", 3))
        self._failures = 0
        self._halted = False

    @property
    def enabled(self) -> bool:
        return self.backend.available and not self._halted

    @property
    def disabled_reason(self) -> str:
        if self._halted:
            return (f"{self.backend.name} transport halted after "
                    f"{self.max_failures} consecutive failures")
        return self.backend.unavailable_reason

    def describe(self) -> str:
        return self.backend.describe()

    def _over_budget(self) -> bool:
        return self.ledger.total >= int(self.budget.get("max_tokens_per_run", 10 ** 9))

    def _call(self, model: str, system: str, user: str,
              max_tokens: int = 4096) -> dict[str, Any]:
        """One round trip. Raises BackendError; callers already catch and log."""
        if self._halted:
            raise BackendError(self.disabled_reason)
        try:
            comp = self.backend.complete(model, system, user, max_tokens)
        except BackendError:
            self._failures += 1
            if self._failures >= self.max_failures:
                self._halted = True
                if self.verbose:
                    print(f"    ! {self.disabled_reason}; falling back to "
                          "local scoring for the rest of this run")
            raise
        self._failures = 0
        self.ledger.add(comp.input_tokens, comp.output_tokens)
        return _parse_json(comp.text)

    # ---------------- Stage C1 ----------------

    def extract(self, cands: list[Candidate]) -> None:
        pending: list[Candidate] = []
        for c in cands:
            cached = self.store.get_facts(c.job_id, self.pv)
            if cached:
                c.facts = cached
            else:
                pending.append(c)

        if not pending or not self.enabled:
            return

        limit = int(self.budget.get("jd_chars_for_extraction", 2500))
        model = self.budget.get("model_low", "claude-haiku-4-5-20251001")
        size = int(self.budget.get("extraction_batch", 8))

        for group in _chunks(pending, size):
            if self._halted:
                return
            if self._over_budget():
                if self.verbose:
                    print("    ! token budget reached; skipping remaining extraction")
                return
            blocks = []
            for c in group:
                jd = extract_requirements(c.raw.description, limit)
                blocks.append(
                    f"id={c.job_id}\ncompany={c.company.name}\n"
                    f"title={c.raw.title}\nlocation={c.raw.location or 'UNSTATED'}\n"
                    f"description:\n{jd or 'NO DESCRIPTION AVAILABLE'}\n---")
            user = EXTRACT_INSTRUCTIONS + "\n\nJobs:\n" + "\n".join(blocks)
            try:
                data = self._call(model, EXTRACT_SYSTEM, user)
            except Exception as exc:
                if self.verbose:
                    print(f"    ! extraction call failed: {exc}")
                continue

            by_id = {c.job_id: c for c in group}
            for item in data.get("results", []):
                c = by_id.get(str(item.get("id", "")))
                if not c:
                    continue
                facts = JobFacts(
                    job_id=c.job_id,
                    countries=[str(x) for x in (item.get("countries") or [])],
                    is_singapore=item.get("is_singapore"),
                    seniority=str(item.get("seniority") or "unknown"),
                    yoe_min=_int(item.get("yoe_min")),
                    yoe_max=_int(item.get("yoe_max")),
                    intake_year=_int(item.get("intake_year")),
                    is_graduate_programme=item.get("is_graduate_programme"),
                    sponsorship=str(item.get("sponsorship") or "unclear"),
                    role_family=str(item.get("role_family") or "other"),
                    tech_stack=[str(x) for x in (item.get("tech_stack") or [])][:8],
                    requires_clearance=item.get("requires_clearance"),
                    model=model)
                c.facts = facts
                self.store.save_facts(facts, self.pv)

    # ---------------- Stage C2 / D ----------------

    def adjudicate(self, cands: list[Candidate]) -> None:
        pending: list[Candidate] = []
        for c in cands:
            ck = _key(c.job_id, c.raw.jd_hash(), self.pv, "c2")
            cached = self.store.get_cached(ck)
            if cached:
                c.verdict = Verdict(
                    job_id=c.job_id, verdict=cached.get("verdict", "unknown"),
                    confidence=float(cached.get("confidence") or 0),
                    reason=cached.get("reason", ""),
                    concerns=cached.get("concerns") or [],
                    model=cached.get("_model", ""), stage="c2")
            else:
                pending.append(c)

        if not pending or not self.enabled:
            return

        limit = int(self.budget.get("jd_chars_for_verdict", 3000))
        size = int(self.budget.get("verdict_batch", 10))
        high_tiers = set(self.budget.get("second_opinion_tiers", []))
        model_high = self.budget.get("model_high", "claude-sonnet-5")
        model_low = self.budget.get("model_low", "claude-haiku-4-5-20251001")

        # Route by tier: spend more where the company matters more.
        hi = [c for c in pending if c.company.tier in high_tiers]
        lo = [c for c in pending if c.company.tier not in high_tiers]

        for bucket, model in ((hi, model_high), (lo, model_low)):
            for group in _chunks(bucket, size):
                if self._halted:
                    return
                if self._over_budget():
                    if self.verbose:
                        print("    ! token budget reached; skipping remaining verdicts")
                    return
                self._verdict_call(group, model, limit, stage="c2")

        if self.budget.get("profile") in ("thorough", "max"):
            self._second_opinion(cands, model_high, limit, high_tiers)

    def _verdict_call(self, group: list[Candidate], model: str, limit: int,
                      stage: str) -> None:
        blocks = []
        for c in group:
            jd = extract_requirements(c.raw.description, limit)
            facts = ""
            if c.facts:
                facts = (f"\nextracted: seniority={c.facts.seniority} "
                         f"yoe_min={c.facts.yoe_min} "
                         f"grad_programme={c.facts.is_graduate_programme} "
                         f"countries={','.join(c.facts.countries) or 'unknown'}")
            blocks.append(
                f"id={c.job_id}\ncompany={c.company.name} (tier {c.company.tier}, "
                f"{c.company.category})\ntitle={c.raw.title}\n"
                f"location={c.raw.location or 'UNSTATED'}{facts}\n"
                f"description:\n{jd or 'NO DESCRIPTION AVAILABLE'}\n---")

        user = (f"Candidate profile:\n{self.profile.summary}\n\n"
                + VERDICT_INSTRUCTIONS + "\n\nJobs:\n" + "\n".join(blocks))
        try:
            data = self._call(model, VERDICT_SYSTEM, user)
        except Exception as exc:
            if self.verbose:
                print(f"    ! verdict call failed: {exc}")
            return

        by_id = {c.job_id: c for c in group}
        for item in data.get("results", []):
            c = by_id.get(str(item.get("id", "")))
            if not c:
                continue
            v = Verdict(
                job_id=c.job_id,
                verdict=str(item.get("verdict") or "unknown").lower(),
                confidence=float(item.get("confidence") or 0),
                reason=str(item.get("reason") or "")[:220],
                concerns=[str(x)[:80] for x in (item.get("concerns") or [])][:3],
                model=model, stage=stage)
            c.verdict = v
            self.store.save_cached(
                _key(c.job_id, c.raw.jd_hash(), self.pv, stage), c.job_id, self.pv,
                stage, {"verdict": v.verdict, "confidence": v.confidence,
                        "reason": v.reason, "concerns": v.concerns}, model, 0, 0)

    def _second_opinion(self, cands: list[Candidate], model: str, limit: int,
                        tiers: set) -> None:
        """Re-judge borderline high-tier postings individually."""
        targets = [
            c for c in cands
            if c.company.tier in tiers and c.verdict
            and (c.verdict.verdict == "possible" or c.verdict.confidence < 0.6)
        ]
        for c in targets:
            if self._halted or self._over_budget():
                return
            ck = _key(c.job_id, c.raw.jd_hash(), self.pv, "d")
            if self.store.get_cached(ck):
                continue
            before = c.verdict
            self._verdict_call([c], model, limit, stage="d")
            after = c.verdict
            if before and after and after.verdict != before.verdict:
                after.verdict = "contested"
                after.reason = (f"contested: first pass {before.verdict}, "
                                f"second {after.stage} differed. "
                                f"{after.reason}")[:220]
