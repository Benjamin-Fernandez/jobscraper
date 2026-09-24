"""The free prefilter: reject what does not need a model to reject.

Every new posting passes through here before anything is spent on it. Rules are
declared in `config/rules.yaml`, evaluated in declaration order, first rejection
wins - and the deciding rule is recorded, so every rejection can be explained
rather than guessed at.

The rules are data, not code. Adding, disabling or reordering one is a YAML edit;
adding a new *kind* of rule is one function in the registry here.

Two things this module deliberately does not do. It does not import `profile/`:
the derived profile arrives as a plain dict and the skill-overlap scorer as a
callable, both handed in by `pipeline.py` (PRD section 0.6, contracts 1-3), so a
stage never reaches into another. And it does not import v1's `matching.py`,
which is retired in M9: the location and years logic that v1 got right is ported
here instead, with the v2 precedence on top.

See PRD section 8.3[3].
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

import yaml

from .config import ROOT

# `(text, skills) -> (score, matched_skills)` - PRD 0.6 contract 2.
Scorer = Callable[[str, list[str]], tuple[int, list[str]]]

DEFAULT_RULES_PATH = ROOT / "config" / "rules.yaml"

# The years pattern v1's `min_years_required` used, with two corrections: a
# range's floor is captured ("2-5 years" -> 2, and "2 to 5" / en dash too), and
# a number is not read out of the middle of a longer one ("150 years" is not 50).
DEFAULT_YEARS_PATTERN = (
    r"(?<!\d)(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*)?\+?\s*"
    r"(?:years?|yrs?)\b")
DEFAULT_IGNORE_ABOVE = 30


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    """One declared rule. `spec` is its YAML block; `compiled` is what the kind
    precomputed from it at load time, so a bad regex fails at load, not mid-run."""
    id: str
    kind: str
    enabled: bool
    spec: Mapping[str, Any]
    compiled: Mapping[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class RuleSet:
    """The loaded rules, in evaluation order.

    `hash` is the §8.4 `rules_hash`: sha256 of the canonicalised document, so
    comments and spacing do not invalidate cached verdicts but any real edit does.
    """
    version: int
    rules: tuple[Rule, ...]
    hash: str
    ceiling_years: Optional[int] = None
    path: Optional[Path] = None


@dataclass(frozen=True)
class Outcome:
    """What one rule said about one posting.

    `verdict` is `pass`, `reject` or `skip` (the rule had nothing to judge on).
    `detail` is the matched text for a reject - what `filter explain` prints.
    """
    verdict: str
    detail: str = ""
    score: Optional[int] = None


@dataclass(frozen=True)
class RuleTrace:
    rule_id: str
    kind: str
    verdict: str            # pass | reject | skip | disabled
    detail: str


@dataclass(frozen=True)
class FilterResult:
    """PRD 0.6 contract 3. `trace` has one entry per declared rule, in order."""
    passed: bool
    reject_rule: Optional[str]
    reject_detail: Optional[str]
    overlap_score: Optional[int]
    trace: tuple[RuleTrace, ...]


@dataclass(frozen=True)
class Context:
    """What a rule kind gets to look at. Kinds read fields through `field()`."""
    title: str
    location: str
    description: str
    profile: Mapping[str, Any]
    scorer: Optional[Scorer]

    def field(self, name: str) -> str:
        return {"title": self.title, "location": self.location,
                "description": self.description}.get(name, "")


# ---------------------------------------------------------------------------
# The registry: a new rule kind is one decorated function
# ---------------------------------------------------------------------------

Check = Callable[[Rule, Context], Outcome]
Prepare = Callable[[Mapping[str, Any], "_LoadEnv"], Mapping[str, Any]]


@dataclass(frozen=True)
class Kind:
    check: Check
    prepare: Optional[Prepare] = None


KINDS: dict[str, Kind] = {}


def rule_kind(name: str, prepare: Optional[Prepare] = None):
    """Register `check(rule, ctx) -> Outcome` as the rule kind `name`.

    `prepare(spec, env) -> dict` optionally precomputes (and validates) whatever
    the check needs; raise ValueError from it to reject a bad rule at load.
    """
    def register(check: Check) -> Check:
        KINDS[name] = Kind(check, prepare)
        return check
    return register


@dataclass(frozen=True)
class _LoadEnv:
    """Document-level settings a kind may default from."""
    ceiling_years: Optional[int]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_rules(path: str | Path | None = None) -> RuleSet:
    """Read, validate and compile `rules.yaml`. Raises ValueError on any problem."""
    p = Path(path) if path else DEFAULT_RULES_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise ValueError(f"{p}: expected a mapping with a `rules:` list")

    ceiling = data.get("ceiling_years")
    env = _LoadEnv(ceiling_years=int(ceiling) if ceiling is not None else None)
    rules: list[Rule] = []
    seen: set[str] = set()
    for i, spec in enumerate(data["rules"]):
        if not isinstance(spec, dict) or not spec.get("id"):
            raise ValueError(f"{p}: rule #{i + 1} needs an `id`")
        rid = str(spec["id"])
        if rid in seen:
            raise ValueError(f"{p}: duplicate rule id {rid!r}")
        seen.add(rid)
        kind = str(spec.get("kind", ""))
        if kind not in KINDS:
            raise ValueError(f"{p}: rule {rid!r} has unknown kind {kind!r} "
                             f"(known: {', '.join(sorted(KINDS))})")
        enabled = spec.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"{p}: rule {rid!r}: `enabled` must be true or false")
        prepare = KINDS[kind].prepare
        try:
            compiled = dict(prepare(spec, env)) if prepare else {}
        except (ValueError, TypeError, re.error) as exc:
            raise ValueError(f"{p}: rule {rid!r}: {exc}") from exc
        rules.append(Rule(rid, kind, enabled, dict(spec), compiled))

    return RuleSet(version=int(data.get("version", 1)), rules=tuple(rules),
                   hash=_canonical_hash(data), ceiling_years=env.ceiling_years,
                   path=p)


def _canonical_hash(data: Any) -> str:
    canon = json.dumps(data, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Evaluating
# ---------------------------------------------------------------------------

def evaluate(posting: Any, ruleset: RuleSet, profile: Optional[Mapping[str, Any]],
             scorer: Optional[Scorer] = None) -> FilterResult:
    """Run every rule, in order; the first rejection decides.

    `posting` is anything with `title`, `location` and `description` - a dict or
    an object. Every rule is evaluated even after a rejection so the trace is
    complete for `filter explain`; rules are pure and local, so this is free.
    """
    ctx = Context(title=_get(posting, "title"), location=_get(posting, "location"),
                  description=_get(posting, "description"),
                  profile=profile or {}, scorer=scorer)
    trace: list[RuleTrace] = []
    decided: Optional[tuple[str, str]] = None
    overlap: Optional[int] = None
    for rule in ruleset.rules:
        if not rule.enabled:
            trace.append(RuleTrace(rule.id, rule.kind, "disabled", ""))
            continue
        out = KINDS[rule.kind].check(rule, ctx)
        if out.score is not None:
            overlap = out.score
        trace.append(RuleTrace(rule.id, rule.kind, out.verdict, out.detail))
        if out.verdict == "reject" and decided is None:
            decided = (rule.id, out.detail)
    return FilterResult(passed=decided is None,
                        reject_rule=decided[0] if decided else None,
                        reject_detail=decided[1] if decided else None,
                        overlap_score=overlap, trace=tuple(trace))


def render(result: FilterResult) -> str:
    """Human-readable verdict plus per-rule trace - shared by `filter test`/`explain`."""
    if result.passed:
        head = "PASS - no rule rejected this posting"
    else:
        head = f"REJECT by {result.reject_rule}: {result.reject_detail}"
    lines = [head]
    if result.overlap_score is not None:
        lines.append(f"overlap score: {result.overlap_score}")
    width = max((len(t.rule_id) for t in result.trace), default=0)
    for t in result.trace:
        mark = "  <- deciding rule" if (not result.passed
                                         and t.rule_id == result.reject_rule) else ""
        detail = f"  {t.detail}" if t.detail else ""
        lines.append(f"  {t.rule_id:<{width}}  {t.verdict.upper():<8}{detail}{mark}")
    return "\n".join(lines)


def _get(posting: Any, name: str) -> str:
    value = posting.get(name) if isinstance(posting, Mapping) \
        else getattr(posting, name, None)
    return "" if value is None else str(value)


# ---------------------------------------------------------------------------
# Shared helpers for the kinds
# ---------------------------------------------------------------------------

def _str_list(value: Any, what: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise ValueError(f"`{what}` must be a list")
    return [str(v) for v in value]


def _profile_value(ctx: Context, source: Optional[str]) -> Any:
    """Resolve `profile.<key>` against the injected profile dict."""
    if not source:
        return None
    return ctx.profile.get(source.split(".", 1)[1])


def _check_source(spec: Mapping[str, Any], key: str) -> Optional[str]:
    source = spec.get(key)
    if source is None:
        return None
    if not isinstance(source, str) or not source.startswith("profile.") \
            or len(source) <= len("profile."):
        raise ValueError(f"`{key}` must look like `profile.<key>`, got {source!r}")
    return source


def _fields(spec: Mapping[str, Any], default: list[str]) -> list[str]:
    if "fields" in spec:
        return _str_list(spec["fields"], "fields")
    if "field" in spec:
        return [str(spec["field"])]
    return default


def _word_alternation(tokens: Iterable[str]) -> Optional[re.Pattern]:
    """`\\b(?:a|b c)\\b`, longest first, so `all offices` wins over `all`."""
    words = sorted({t.strip().lower() for t in tokens if t.strip()},
                   key=len, reverse=True)
    if not words:
        return None
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b",
                      re.I)


# ---------------------------------------------------------------------------
# Kind 1: regex_deny - title_deny, and (with allow/vague tokens) location
# ---------------------------------------------------------------------------

# Words that carry no geography. Ported from v1 `matching.py::_LOC_FILLER`: once
# the vague tokens are stripped, a residue made only of these is still
# location-free, while anything else left standing is a place we did not allow.
_LOC_FILLER = re.compile(
    r"\b(?:remote|hybrid|on[- ]?site|onsite|in[- ]?office|office|offices|based|"
    r"only|first|friendly|optional|preferred|flexible|work from home|wfh|"
    r"national|nationwide|home|full[- ]?time|permanent|other|location|"
    r"locations)\b", re.I)
_ANY_WORD = re.compile(r"[^\W_]", re.UNICODE)


def _prepare_regex_deny(spec: Mapping[str, Any], _env: _LoadEnv) -> dict:
    patterns = (_str_list(spec.get("patterns"), "patterns")
                + _str_list(spec.get("extra"), "extra"))
    allow = _str_list(spec.get("allow_tokens"), "allow_tokens")
    remote = _str_list(spec.get("remote_tokens",
                                ["remote", "anywhere", "distributed"]),
                       "remote_tokens")
    return {
        "field": _fields(spec, ["title"])[0],
        "patterns": [re.compile(p, re.I) for p in patterns],
        "allow": _word_alternation(allow),
        "vague": _word_alternation(_str_list(spec.get("vague_tokens"),
                                             "vague_tokens")),
        "remote": _word_alternation(remote) if spec.get("reject_remote") else None,
    }


@rule_kind("regex_deny", prepare=_prepare_regex_deny)
def _regex_deny(rule: Rule, ctx: Context) -> Outcome:
    """Reject on any matching pattern.

    With `allow_tokens` the rule becomes default-deny, which is how
    `location_explicit` implements the §8.3[3] precedence table: allow token ->
    pass; remote token -> reject; deny pattern -> reject; nothing but vague
    tokens and filler -> pass (for the model); anything else -> reject.
    """
    c = rule.compiled
    value = ctx.field(c["field"])
    allow, remote, vague = c["allow"], c["remote"], c["vague"]

    if allow is not None:
        m = allow.search(value)
        if m:
            return Outcome("pass", f"allowed: {m.group(0).lower()}")
    if remote is not None:
        m = remote.search(value)
        if m:
            return Outcome("reject", m.group(0).lower())
    for pattern in c["patterns"]:
        m = pattern.search(value)
        if m:
            return Outcome("reject", m.group(0).lower())
    if allow is None:
        return Outcome("pass")

    # Default-deny: strip what is vague and what is filler; judge the residue.
    residue = vague.sub(" ", value) if vague is not None else value
    residue = _LOC_FILLER.sub(" ", residue)
    if not _ANY_WORD.search(residue):
        return Outcome("pass", "vague: left for the model" if value.strip()
                       else "blank: left for the model")
    return Outcome("reject", " ".join(re.findall(r"[^\W_]+", residue.lower())))


# ---------------------------------------------------------------------------
# Kind 2: any_match - title_allow (D-10)
# ---------------------------------------------------------------------------

_TITLE_TOKEN = re.compile(r"[^\W_]+(?:[+#]+)?(?:-[^\W_]+)*", re.UNICODE)


def _title_tokens(text: str) -> set[str]:
    """Lowercase words, with `back-end` also as `back`, `end`, `backend`, and a
    trailing plural `s` also dropped - both only ever add tokens, never remove."""
    tokens: set[str] = set()
    for tok in _TITLE_TOKEN.findall(text.lower()):
        parts = tok.split("-")
        tokens.update([tok, "".join(parts), *parts])
    tokens.update({t[:-1] for t in tokens if len(t) > 3 and t.endswith("s")})
    tokens.discard("")
    return tokens


def _prepare_any_match(spec: Mapping[str, Any], _env: _LoadEnv) -> dict:
    match = spec.get("match", "token_subset")
    if match != "token_subset":
        raise ValueError(f"`match: {match}` is not supported (use token_subset)")
    return {
        "field": _fields(spec, ["title"])[0],
        "source": _check_source(spec, "source"),
        "aliases": _check_source({"aliases": spec.get("aliases",
                                                      "profile.title_aliases")},
                                 "aliases"),
        "extra": _str_list(spec.get("extra"), "extra"),
    }


def _fold_aliases(text: str, aliases: Any) -> str:
    low = text.lower()
    if not isinstance(aliases, Mapping):
        return low
    for short in sorted(aliases, key=lambda k: len(str(k)), reverse=True):
        low = re.sub(r"\b" + re.escape(str(short).lower()) + r"\b",
                     " " + str(aliases[short]).lower() + " ", low)
    return low


@rule_kind("any_match", prepare=_prepare_any_match)
def _any_match(rule: Rule, ctx: Context) -> Outcome:
    """Pass when every word of at least one target is present, in any order."""
    c = rule.compiled
    targets = _str_list(_profile_value(ctx, c["source"]), "source") + c["extra"]
    targets = [t for t in targets if t.strip()]
    if not targets:
        return Outcome("skip", "no targets: source is empty and no extra")
    have = _title_tokens(_fold_aliases(ctx.field(c["field"]),
                                       _profile_value(ctx, c["aliases"])))
    for target in targets:
        want = {t for t in _TITLE_TOKEN.findall(target.lower())}
        if want and want <= have:
            return Outcome("pass", f"matched: {target.lower()}")
    return Outcome("reject", f"matches none of {len(targets)} target titles")


# ---------------------------------------------------------------------------
# Kind 3: max_number - experience_ceiling (D-12)
# ---------------------------------------------------------------------------

def _prepare_max_number(spec: Mapping[str, Any], env: _LoadEnv) -> dict:
    pattern = re.compile(str(spec.get("pattern", DEFAULT_YEARS_PATTERN)), re.I)
    if pattern.groups < 1:
        raise ValueError("`pattern` needs a capture group around the number")
    ceiling = spec.get("max", env.ceiling_years)
    if ceiling is None:
        raise ValueError("`max` is required (or set top-level ceiling_years)")
    return {
        "fields": _fields(spec, ["title", "description"]),
        "pattern": pattern,
        "max": int(ceiling),
        "ignore_above": int(spec.get("ignore_above", DEFAULT_IGNORE_ABOVE)),
    }


def _lowest_number(texts: Iterable[str], pattern: re.Pattern,
                   ignore_above: int) -> Optional[tuple[int, str]]:
    """The lowest plausible number stated, with the text that stated it."""
    best: Optional[tuple[int, str]] = None
    for text in texts:
        for m in pattern.finditer(text or ""):
            try:
                n = int(m.group(1))
            except (TypeError, ValueError):
                continue
            if 0 <= n <= ignore_above and (best is None or n < best[0]):
                best = (n, m.group(0).lower())
    return best


@rule_kind("max_number", prepare=_prepare_max_number)
def _max_number(rule: Rule, ctx: Context) -> Outcome:
    """Reject when the LOWEST stated number exceeds `max` (PRD 8.3[3] semantics)."""
    c = rule.compiled
    found = _lowest_number((ctx.field(f) for f in c["fields"]), c["pattern"],
                           c["ignore_above"])
    if found is None:
        return Outcome("pass", "none stated")
    n, text = found
    if n > c["max"]:
        return Outcome("reject", text)
    return Outcome("pass", f"lowest stated: {text}")


def min_years_required(text: str) -> Optional[int]:
    """The lowest years-of-experience figure in `text`, or None.

    The v2 home of v1's `matching.py::min_years_required` - same "lowest stated
    wins" contract, which `tests/test_filter.py` holds the two to jointly.
    """
    found = _lowest_number([text], re.compile(DEFAULT_YEARS_PATTERN, re.I),
                           DEFAULT_IGNORE_ABOVE)
    return found[0] if found else None


# ---------------------------------------------------------------------------
# Kind 4: overlap_floor - keyword_floor
# ---------------------------------------------------------------------------

def _prepare_overlap_floor(spec: Mapping[str, Any], _env: _LoadEnv) -> dict:
    return {
        "fields": _fields(spec, ["title", "description"]),
        "source": _check_source(spec, "source"),
        "extra": _str_list(spec.get("extra"), "extra"),
        "min": int(spec.get("min_overlap", 1)),
        "skip_when_empty": spec.get("skip_when_empty"),
    }


@rule_kind("overlap_floor", prepare=_prepare_overlap_floor)
def _overlap_floor(rule: Rule, ctx: Context) -> Outcome:
    """Reject when the injected scorer finds fewer than `min_overlap` skills."""
    c = rule.compiled
    if ctx.scorer is None:
        return Outcome("skip", "no scorer supplied")
    empty_field = c["skip_when_empty"]
    if empty_field and not ctx.field(str(empty_field)).strip():
        return Outcome("skip", f"no {empty_field}: left for the model")
    skills = _str_list(_profile_value(ctx, c["source"]), "source") + c["extra"]
    skills = [s for s in skills if s.strip()]
    if not skills:
        return Outcome("skip", "no skills: source is empty and no extra")
    text = "\n".join(ctx.field(f) for f in c["fields"])
    score, matched = ctx.scorer(text, skills)
    detail = f"overlap {score} (min {c['min']})"
    if matched:
        detail += ": " + ", ".join(matched[:8])
    return Outcome("reject" if score < c["min"] else "pass", detail, int(score))
