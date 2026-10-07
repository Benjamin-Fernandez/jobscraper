"""The job titles the title filter searches for, and Qwen's recommendations (M15).

Two things live here:

* **The user's titles.** Once the user edits them in the web app they are stored
  in the `settings` table (`target_titles`, a JSON list) and replace the resume's
  `target_titles` for the prefilter's `title_allow` rule. While unset, the resume's
  titles are used, exactly as before M15.

  Changing them must re-check the prefilter - a posting rejected for its title
  may now pass - but must not throw away the model's answers, which never
  depended on titles. So the prefilter's cache key (`rules_hash` in the
  `prefilter` table) folds the titles in, and the decision cache is untouched
  (M15-D6). With no user titles the key is the plain rules hash, so upgrading
  re-checks nothing.

* **Recommendations.** One Qwen call reads the resume and the titles already
  chosen, works out the field of study and past internships/jobs, and proposes up
  to `plan.max_title_suggestions` further titles. It runs as a CLI command
  (`jobscraper titles suggest`), which the web app starts as a background job
  (M15-D7) - the web layer never reaches a model itself.

Only backends.py talks to a model (PRD 8.2); this module hands it a prompt.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from typing import Any, Optional

from .. import backends
from .resume_ingest import _MAX_PROMPT_CHARS, ProfileError, _parse_json

# The storage keys and the title rules are shared with the web app, which may
# not import this stage (PRD 8.2); they live in models.py.
from ..models import (MAX_TITLE_CHARS, SUGGEST_BATCH, SUGGESTIONS_KEY,  # noqa: F401
                      USER_TITLES_KEY,
                      dedupe_titles as dedupe, normalise_title as normalise,
                      parse_titles_json as parse_user_titles)

# ---------------------------------------------------------------- user titles


def apply(profile: dict[str, Any], user_titles: Optional[list[str]]) -> dict[str, Any]:
    """The profile the prefilter reads: the user's titles, when set, replace the
    resume's `target_titles`. Nothing else changes."""
    if not user_titles:
        return profile
    return dict(profile, target_titles=list(user_titles))


def prefilter_key(rules_hash: str, user_titles: Optional[list[str]]) -> str:
    """The prefilter cache key: the rules hash, with the user's titles folded in
    when they are set. Order and case do not matter - the filter ignores both."""
    if not user_titles:
        return rules_hash
    basis = rules_hash + "\n" + json.dumps(sorted(t.lower() for t in user_titles))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- recommendations

SYSTEM_PROMPT = """\
You recommend job titles for one early-career job seeker to search for on
company careers sites.

Read their resume and the titles they have already chosen. Work out their field
of study and their past internships, jobs and substantial projects. Then
recommend further titles that:
- are real, common titles that appear word for word on job boards (for example
  "software engineer", "data analyst", "technology analyst", "product manager").
  Never invent a title by stacking words ("observability automation engineer",
  "platform operations engineer" are made up; "site reliability engineer" and
  "devops engineer" are real);
- are written in lowercase, singular, with no company name, no seniority word
  (senior, staff, principal, lead, head, director, vp) and no level (i, ii, iii);
- fit this person's level - a graduate or entry-level candidate with at most
  about {ceiling} years of experience;
- follow from their degree, internships, skills, the titles they chose and the
  areas they say they are open to - spread across those areas rather than
  listing many variants of one role;
- are NOT already among their chosen titles, nor a trivial variant of one
  (a plural, a reordering, an abbreviation);
- are NOT among the titles already suggested to them - they saw those and chose
  not to add them - nor a trivial variant of one.

Reply with ONLY this JSON object:
{{"field_of_study": "<degree and subject, or empty if the resume does not say>",
  "experience": ["<role> at <organisation> (internship | job | project)", ...],
  "suggestions": [{{"title": "<title>", "why": "<one short clause>"}}, ...]}}

Give exactly {limit} new suggestions, the strongest first, when that many
relevant titles remain. Give fewer only when no more relevant titles exist, and an
empty list when nothing relevant is left - never fill the list by repeating a
chosen or already-suggested title."""


def suggest(backend: Any, resume_text: str, profile: dict[str, Any],
            current: list[str], limit: int, *, ceiling_years: int = 3,
            interests: Optional[list[str]] = None,
            already_suggested: Optional[list[str]] = None,
            now: Optional[str] = None) -> dict[str, Any]:
    """One Qwen call. Returns what the settings table stores under
    SUGGESTIONS_KEY: `field_of_study`, `experience`, `suggestions` (at most
    `limit`, none already chosen), `generated_at`, `model`, `based_on`."""
    if not getattr(backend, "available", False):
        reason = getattr(backend, "unavailable_reason", "") or "no backend"
        raise ProfileError(f"cannot recommend titles - model unavailable: {reason}")
    limit = max(1, int(limit))
    chosen = dedupe(current)
    seen = dedupe(already_suggested or [])
    skills = ", ".join(str(s) for s in (profile.get("skills") or [])[:40])
    user = ("<resume>\n" + (resume_text or "")[:_MAX_PROMPT_CHARS] + "\n</resume>\n\n"
            + "<skills>" + skills + "</skills>\n"
            + "<open_to>" + "; ".join(str(i) for i in (interests or [])) + "</open_to>\n"
            + "<chosen_titles>\n" + "\n".join(chosen or ["(none yet)"]) + "\n</chosen_titles>\n"
            + "<already_suggested>\n" + "\n".join(seen or ["(none yet)"]) + "\n</already_suggested>\n\n"
            + f"Respond with ONLY the JSON object described in the system prompt - "
              f"keys field_of_study, experience, suggestions ({limit} new titles, "
              "none chosen or already suggested). Start your reply with `{`.")
    system = SYSTEM_PROMPT.format(ceiling=int(ceiling_years), limit=limit)
    try:
        comp = backend.complete(system=system, user=user, max_tokens=1500)
    except backends.BackendError as exc:
        raise ProfileError(f"model call failed: {exc}") from exc
    raw = _parse_json(comp.text)
    if not raw:
        raise ProfileError("the model did not return the JSON object asked for")

    taken = {t.lower() for t in chosen} | {t.lower() for t in seen}
    picked: list[dict[str, str]] = []
    for item in raw.get("suggestions") or []:
        title = normalise((item or {}).get("title") if isinstance(item, dict) else item)
        if not title or title.lower() in taken:
            continue
        taken.add(title.lower())
        why = str(item.get("why") or "").strip()[:160] if isinstance(item, dict) else ""
        picked.append({"title": title.lower(), "why": why})
        if len(picked) >= limit:
            break

    experience = [re.sub(r"\s+", " ", str(e)).strip()[:160]
                  for e in (raw.get("experience") or []) if str(e).strip()][:8]
    return {
        "generated_at": now or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "model": getattr(backend, "model_id", "") or getattr(backend, "name", ""),
        "based_on": chosen,
        "field_of_study": re.sub(r"\s+", " ", str(raw.get("field_of_study") or "")).strip()[:160],
        "experience": experience,
        "suggestions": picked,
    }


def recommend(backend: Any, resume_text: str, profile: dict[str, Any],
              current: list[str], previous: Optional[dict[str, Any]], *,
              limit: int = SUGGEST_BATCH, attempts: int = 2, **kw: Any) -> dict[str, Any]:
    """What "Recommend titles" stores (M17): `limit` titles that are neither
    chosen nor suggested before. A second call tops up a short answer. Only
    when nothing new at all is found do the earlier suggestions not yet chosen
    come back, flagged `repeated`. `seen` remembers every title ever suggested,
    so the next request asks for different ones."""
    prev = previous if isinstance(previous, dict) else {}
    earlier = [i for i in (prev.get("suggestions") or []) if isinstance(i, dict)]
    seen = dedupe(list(prev.get("seen") or []) + [str(i.get("title") or "") for i in earlier])
    picked: list[dict[str, str]] = []
    result: Optional[dict[str, Any]] = None
    for attempt in range(max(1, attempts)):
        need = limit - len(picked)
        if need <= 0:
            break
        try:
            answer = suggest(backend, resume_text, profile, current, need,
                             already_suggested=seen + [p["title"] for p in picked], **kw)
        except ProfileError:
            if result is None:
                raise
            break                       # keep what the first call found
        result = answer
        picked.extend(answer["suggestions"])
    assert result is not None
    chosen = {t.lower() for t in dedupe(current)}
    out = dict(result, suggestions=picked[:limit], repeated=False)
    out["seen"] = dedupe(seen + [p["title"] for p in picked])[-300:]
    if not picked:
        again = [i for i in earlier if str(i.get("title") or "").lower() not in chosen]
        if again:
            out["suggestions"] = again[:limit]
            out["repeated"] = True
    return out
