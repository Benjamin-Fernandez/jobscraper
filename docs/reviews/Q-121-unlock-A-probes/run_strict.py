#!/usr/bin/env python
"""Q-121 unlock review A, step 4: the STRICT filler (what is live today) on the same corpus.

    JOBSCRAPER_OLLAMA_AUTOSTART=0 python docs/reviews/Q-121-unlock-A-probes/run_strict.py

Strict path = pagefill._decide steps 3-6 without a browser: locks (`locks.lock_page`: files, email, declarations,
work rights, tier-2 rows, consents, owner memory), then a COMPETENT scripted model that answers every field whose
true answer is a fact in the catalogue (profile / standing, by value) or a line of the resume (verbatim quote), and
says `unknown` for the rest (strict has no default rules, no assumed answers), then `guards.decide`.
A required field that ends unknown / ungrounded = the attempt stops and the owner is asked (strict's stop).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_corpus as RC                                          # noqa: E402
from run_corpus import T, TODAY, _profile                        # noqa: E402
from jobscraper.apply import facts as F, guards as G, locks as K, llm_fill as L   # noqa: E402
from jobscraper.apply.contracts import AnswerStatus, FillSource, ModelDecision    # noqa: E402


def nrm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def main():
    mac = RC.macros()
    forms = [RC.parse(p, mac) for p in sorted(RC.CORPUS.glob("[0-9][0-9]_*.txt"))]
    profile = _profile()
    out = []
    for form in forms:
        r = T.rctx(profile, employer_name=form["employer"], ats=form["style"], resume_path="C:/fake/resume.pdf",
                   account_email=profile["contact"]["email"], model_sees_sensitive=True)
        facts = F.fact_catalogue(r.profile, r, today=TODAY)
        by_val = {}
        for f in facts:
            if f.value:
                by_val.setdefault(nrm(f.value), f)
        resume = nrm(r.resume_text)
        res = {"form": form["name"], "required": 0, "locked": 0, "model_answered": 0, "unknown_required": [], "filled_required": 0}
        for pg in form["pages"]:
            fields = [RC.build_pf(e) for e in pg["fields"]]
            ents = {e["key"]: e for e in pg["fields"]}
            locked = K.lock_page(fields, r, T.rules(), today=TODAY, uploaded={}, page_text="", composed=None,
                                 composed_files=None, audit={})
            decisions = []
            for pf in fields:
                k = pf.field.key
                if k in locked:
                    continue
                e = ents[k]
                ans = e["ans"].lstrip("?")
                if e["ans"].startswith("?") or ans in ("~", ""):
                    decisions.append(ModelDecision(k, FillSource.UNKNOWN))
                    continue
                if e["type"] == "MULTI_CHOICE":
                    ans_v = ans.split(";")
                    decisions.append(ModelDecision(k, FillSource.UNKNOWN))
                    continue
                f = by_val.get(nrm(ans)) or next((x for k2, x in by_val.items() if len(nrm(ans)) > 3 and (nrm(ans) in k2 or k2 in nrm(ans)) and len(k2) > 3), None)
                if f is not None:
                    decisions.append(ModelDecision(k, FillSource.PROFILE, ref=f.ref, value=ans, evidence=""))
                elif len(nrm(ans)) > 12 and nrm(ans) in resume:
                    decisions.append(ModelDecision(k, FillSource.RESUME, value=ans, evidence=ans))
                else:
                    decisions.append(ModelDecision(k, FillSource.UNKNOWN))
            dec = G.decide(fields, locked, decisions, facts, r, matches={}, second=lambda pf: ModelDecision(pf.field.key, FillSource.UNKNOWN),
                           today=TODAY, rules=T.rules(), model="fake")
            for pf in fields:
                k = pf.field.key
                a = dec.answers[k]
                if not pf.field.required:
                    continue
                res["required"] += 1
                filled = a.status is AnswerStatus.FILLED and a.value not in (None, "", [])
                if filled:
                    res["filled_required"] += 1
                    res["locked" if k in locked else "model_answered"] += 1
                elif (a.note or "").startswith(("G2a", "G2b")):
                    res["scoping_artefact"] = res.get("scoping_artefact", 0) + 1     # no entry sections in this harness: counted as answered for strict
                else:
                    res["unknown_required"].append({"label": ents[k]["label"][:90], "why": (a.note or a.status.value)[:90]})
        out.append(res)
        print(f"{res['form']:34s} required {res['required']:3d}  answered {res['filled_required']:3d} "
              f"(locks {res['locked']}, model {res['model_answered']})  scoping-artefact {res.get('scoping_artefact',0):2d} (counted answered below)  UNANSWERED {len(res['unknown_required']):2d}")
    (HERE / "results_strict.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("total required", sum(o["required"] for o in out), "unanswered", sum(len(o["unknown_required"]) for o in out),
          "artefact", sum(o.get("scoping_artefact", 0) for o in out))


if __name__ == "__main__":
    main()
