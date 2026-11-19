#!/usr/bin/env python
"""Q-121 unlock review A: run the 12-form corpus through always.fill_page_always with a scripted model.

    JOBSCRAPER_OLLAMA_AUTOSTART=0 python docs/reviews/Q-121-unlock-A-probes/run_corpus.py [competent|realistic|both] [--form 05]

No real model, no network, no browser; the sample applicant of tests/fixtures/apply/applicant.sample.yaml.
Reuses tests/test_always_fill.py (FakeAsk, say, _profile) and tests/llm_fill_t2.py (rctx, pf, rules).
After a page STOP (an AlwaysStop) the field that caused it is dropped and the page re-run, so every stop
reason of a form is listed (diagnosis mode); "ready" needs a form with no stop and no required field left empty.
Writes results_<mode>.json next to this file.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("JOBSCRAPER_OLLAMA_AUTOSTART", "0")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
CORPUS = HERE.parent / "Q-121-unlock-A-corpus"

import llm_fill_t2 as T                                    # noqa: E402
from place_quote import is_place_call, label_of, sensible_quote  # noqa: E402
from test_always_fill import FakeAsk, TODAY, _profile, say  # noqa: E402
from jobscraper.apply import always as AL, briefing as BR   # noqa: E402
from jobscraper.apply.contracts import AnswerStatus, FieldType  # noqa: E402

CLS = {"ord": "ordinary", "wr": "work_right", "sp": "sponsorship", "priv": "consent_privacy",
       "ret": "consent_retention", "mkt": "marketing", "cert": "certification", "ack": "acknowledgement",
       "oth": "other_person"}
LONG = {"dec": "declaration", "sid": "self_id", "of": "owner_fact"}
PROTECTED_SHORT = ("dec", "wr", "sp", "priv", "ret", "mkt", "cert", "ack", "sid")
PLACE_FIXTURE = json.loads((ROOT / "tests/fixtures/apply/place_replies_qwen3_14b.json").read_text(encoding="utf-8"))
STATUS_WORDS = re.compile(r"citizen|permanent resident|\bpr\b|work pass|immigration status|work authori[sz]ation status|"
                          r"residency status|nationality|citizenship|status in singapore", re.I)


def klass(short: str) -> str:
    if ":" in short:
        a, b = short.split(":", 1)
        return f"{LONG.get(a, a)}:{b}"
    return CLS.get(short, short)


# ----------------------------------------------------------------------------- corpus
def macros() -> dict:
    out, cur = {}, None
    for ln in (CORPUS / "_macros.txt").read_text(encoding="utf-8").splitlines():
        ln = ln.rstrip("\r")
        m = re.match(r"\[(\w+)\]", ln)
        if m:
            cur = out.setdefault(m.group(1), [])
        elif ln.strip() and cur is not None:
            cur.append(ln)
    return out


def parse(path: Path, mac: dict) -> dict:
    form = {"file": path.name, "pages": []}
    page = None

    def add(ln):
        p = [x.strip() for x in ln.split("|")] + [""] * 8
        e = dict(key=p[0], type=p[1], req=(p[2] == "R"), label=p[3], opts=[o for o in p[4].split(";") if o],
                 short=p[5], ans=p[6], help=p[7])
        page["fields"].append(e)

    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.rstrip("\r")
        if not ln.strip() or ln.startswith("#"):
            continue
        if ln.startswith("@form"):
            _, rest = ln.split(" ", 1)
            n, style, emp, title = [x.strip() for x in rest.split("|")]
            form.update(name=n, style=style, employer=emp, title=title)
        elif ln.startswith("@page"):
            page = {"title": ln[5:].strip(), "fields": []}
            form["pages"].append(page)
        elif ln.startswith("@use"):
            for m in mac[ln.split()[1]]:
                add(m)
        else:
            add(ln)
    return form


def ftype(e) -> FieldType:
    return FieldType[e["type"]]


def build_pf(e):
    return T.pf(e["key"], e["label"], ftype(e), required=e["req"], options=tuple(e["opts"]))


# ----------------------------------------------------------------------------- the scripted model
class Scripted(FakeAsk):
    """FakeAsk plus the confirmation / meaning / own-fact / experience answers a competent model gives."""

    def __init__(self, form, mode):
        self.form, self.mode = form, mode
        self.by_label = {}
        self.fields = {}
        for pg in form["pages"]:
            for e in pg["fields"]:
                self.by_label.setdefault(re.sub(r"\s+", " ", e["label"]).strip(), e)
                self.fields[e["key"]] = e
        self.protected = [e["key"] for pg in form["pages"] for e in pg["fields"]
                          if e["short"].split(":")[0] in PROTECTED_SHORT]
        # realistic: class "ordinary" on every 5th protected field; one wrong answer on the 3rd Yes/No protected
        # radio/dropdown of declaration / work-right / sponsorship kind; silent on the first two optional ordinary
        self.blind = {k for i, k in enumerate(self.protected) if i % 5 == 2}
        yn = [k for k in self.protected if self.fields[k]["short"].split(":")[0] in ("dec", "wr", "sp")
              and set(o.lower() for o in self.fields[k]["opts"]) >= {"yes", "no"}]
        self.wrong = yn[2] if len(yn) > 2 else (yn[-1] if yn else None)
        opt = [e["key"] for pg in form["pages"] for e in pg["fields"]
               if not e["req"] and e["short"] == "ord" and e["ans"] not in ("~", "") and e["type"] in ("TEXT", "URL", "TEXTAREA")]
        self.silent = set(opt[:2]) if mode == "realistic" else set()
        self.log = []
        self._lastuser = ""
        super().__init__(self._answer, pick=self._pick, place=self._place)

    # ---- the main pass
    def _answer(self, v):
        e = self.fields.get(v["id"])
        if e is None or e["ans"] in ("~", ""):
            return None
        if e["key"] in self.silent:
            return None
        ans = e["ans"]
        assumed = ans.startswith("?")
        ans = ans.lstrip("?")
        short = e["short"].split(":")[0]
        if self.mode == "realistic" and e["key"] == self.wrong:
            ans = {"yes": "No", "no": "Yes"}.get(ans.lower(), ans)
            if ans not in e["opts"]:
                ans = next((o for o in e["opts"] if o.lower() != e["ans"].lower()), ans)
        if e["type"] == "MULTI_CHOICE":
            value = [a for a in ans.split(";")]
        else:
            value = ans
        cls = klass(e["short"])
        if self.mode == "realistic" and e["key"] in self.blind:
            cls = "ordinary"
        if assumed:
            d = say(value, "assumption", "", True, "no basis in the profile; neutral answer", klass=cls)
        elif short in ("dec", "sid", "priv", "ret", "mkt", "cert", "ack"):
            rule = {"dec": "default:no_declaration", "sid": "default:self_id", "priv": "default:consent",
                    "ret": "default:consent", "mkt": "default:talent_pool", "cert": "default:consent",
                    "ack": "default:consent"}[short]
            d = say(value, "default", rule, False, "standing rule", klass=cls)
        else:
            d = say(value, "profile", "", False, "from the profile", klass=cls)
        return d

    # ---- the place call: the real model's behaviour, per the fixture
    def _place(self, label):
        if label in PLACE_FIXTURE:
            return PLACE_FIXTURE[label]
        if re.search(r"\bUS\b|U\.S\.|United States|\bUSA\b", label):
            return "NONE"
        if STATUS_WORDS.search(label) and not re.search(r"(?:in|within|for)\s+(?:the\s+)?Singapore", label):
            return "NONE"       # the real model quotes no place for "Are you a Singapore citizen?" / "citizen or PR?" (fixture)
        return sensible_quote(label)

    # ---- confirmation / meaning / own-fact / experience calls (a competent model, both modes)
    def __call__(self, messages, schema, **kw):
        self._lastuser = messages[1]["content"]
        return super().__call__(messages, schema, **kw)

    def _pick(self, q, w, o):
        task = self._lastuser.rstrip().splitlines()[-1]
        e = self.by_label.get(re.sub(r"\s+", " ", str(q)).strip()) or next(
            (x for k, x in self.by_label.items() if k.startswith(str(q)[:60])), None)
        ans = (e["ans"].lstrip("?") if e else "")
        if task.startswith("Does QUESTION ask for"):
            return "Yes" if "Yes" in o else ""
        if task.startswith("WANTED is one yes/no question about the applicant's experience"):
            return "yes" if "yes" in o else ""
        if task.startswith("QUESTION is a tick box"):
            return "yes" if ans == "true" else "no"
        if task.startswith("WANTED is a yes/no check"):
            m = re.search(r"answers «(.*?)» to", w)
            said = m.group(1) if m else ""
            return "no" if said.lower() == ans.lower() else "yes"
        if ans in o:                        # TASK_CONFIRM and TASK_PICK
            return ans
        wl = str(w).lower()
        for opt in o:
            if opt.lower() == wl or opt.lower() in wl or wl in opt.lower():
                return opt
        return ""


# ----------------------------------------------------------------------------- run
def run_form(form, mode, profile):
    ask = Scripted(form, mode)
    r = T.rctx(profile, employer_name=form["employer"], ats=form["style"], resume_path="C:/fake/resume.pdf",
               account_email=profile["contact"]["email"])
    b = BR.build(profile, r, today=TODAY)
    res = {"form": form["name"], "style": form["style"], "employer": form["employer"], "pages": [],
           "stops": [], "empty_required": [], "answered": 0, "optional_empty": 0, "assumed": 0, "fields": 0,
           "required": 0, "wrong_written": []}
    for pg in form["pages"]:
        fields = [build_pf(e) for e in pg["fields"]]
        ents = {e["key"]: e for e in pg["fields"]}
        page = {"title": pg["title"], "n": len(fields), "calls": 0, "base_cap": 0, "stops": [], "ready": True}
        dropped = []
        calls = 0
        for _ in range(8):
            live = [f for f in fields if f.field.key not in dropped]
            if not live:
                break
            ask.sizes.clear()
            before = len(ask.users)
            try:
                chunks = AL.plan_chunks([f for f in live], {})
                out = AL.fill_page_always(live, brief=b, rctx=r, ask=ask, rules=T.rules(), today=TODAY,
                                          step_title=pg["title"], uploaded={}, page_text="")
                calls += len(ask.users) - before
                page["base_cap"] = 3 * len(chunks) + AL.CALLS_PAGE_EXTRA
                break
            except AL.AlwaysStop as s:
                calls += len(ask.users) - before
                st = {"page": pg["title"], "reason": s.reason.value, "detail": s.detail, "field": s.field_key,
                      "label": s.label or (ents.get(s.field_key) or {}).get("label", "")}
                page["stops"].append(st)
                res["stops"].append(st)
                page["ready"] = False
                if s.field_key and s.field_key in ents:
                    dropped.append(s.field_key)
                    continue
                out = None
                break
            except Exception as ex:                   # noqa: BLE001
                st = {"page": pg["title"], "reason": "EXCEPTION", "detail": f"{type(ex).__name__}: {ex}"[:200], "field": "", "label": ""}
                page["stops"].append(st)
                res["stops"].append(st)
                page["ready"] = False
                out = None
                break
        page["calls"] = calls
        if dropped:
            for k in dropped:
                if ents[k]["req"]:
                    res["empty_required"].append({"page": pg["title"], "key": k, "label": ents[k]["label"],
                                                  "why": "STOP: " + next(s["reason"] + ": " + s["detail"] for s in page["stops"] if s["field"] == k)})
        res["fields"] += len(fields)
        res["required"] += sum(1 for e in pg["fields"] if e["req"])
        if out is not None:
            for k, a in out.answers.items():
                e = ents[k]
                filled = a.status is AnswerStatus.FILLED and a.value not in (None, "", [])
                if a.status is AnswerStatus.SKIPPED:
                    continue
                if k in out.compose_needed:          # written by the tailor round trip (apply_flow 7b): counted apart
                    res["composed"] = res.get("composed", 0) + 1
                    continue
                if k == ask.wrong and mode == "realistic":
                    res["injected"] = {"label": e["label"], "model_said": "flipped " + e["ans"].lstrip("?"),
                                       "class": "ordinary" if k in ask.blind else klass(e["short"]),
                                       "wrote": (", ".join(a.option_labels) if a.option_labels else str(a.value)) if filled else "(empty)",
                                       "truth": e["ans"].lstrip("?"), "source": a.source, "note": a.note[:100]}
                if filled:
                    res["answered"] += 1
                    if a.assumed:
                        res["assumed"] += 1
                    # compare with the truth (protected fields only): a wrong value written is a finding
                    truth = e["ans"].lstrip("?")
                    shown = ", ".join(a.option_labels) if a.option_labels else str(a.value)
                    if e["short"].split(":")[0] in PROTECTED_SHORT and truth not in ("~", "") and e["type"] != "MULTI_CHOICE":
                        if truth.lower() != shown.lower() and not (e["type"] == "CHECKBOX" and truth.lower() == shown.lower()):
                            res["wrong_written"].append({"key": k, "label": e["label"], "wrote": shown, "truth": truth,
                                                         "source": a.source, "note": a.note})
                elif e["req"]:
                    page["ready"] = False
                    res["empty_required"].append({"page": pg["title"], "key": k, "label": e["label"],
                                                  "why": a.note or "no answer", "class": e["short"]})
                else:
                    res["optional_empty"] += 1
        else:
            # whole page lost (no field named): every required field of the page counts as empty
            for e in pg["fields"]:
                if e["req"] and e["key"] not in dropped:
                    res["empty_required"].append({"page": pg["title"], "key": e["key"], "label": e["label"],
                                                  "why": "PAGE STOP: " + page["stops"][-1]["reason"] + " " + page["stops"][-1]["detail"][:120]})
        res["pages"].append(page)
    res["place_calls"] = len(ask.place_calls)
    res["ready"] = not res["stops"] and not res["empty_required"]
    return res


def main():
    mode = next((a for a in sys.argv[1:] if a in ("competent", "realistic", "both")), "both")
    only = sys.argv[sys.argv.index("--form") + 1] if "--form" in sys.argv else ""
    mac = macros()
    forms = [parse(p, mac) for p in sorted(CORPUS.glob("[0-9][0-9]_*.txt"))]
    profile = _profile()
    for m in (["competent", "realistic"] if mode == "both" else [mode]):
        results = [run_form(f, m, profile) for f in forms if f["name"].startswith(only)]
        (HERE / f"results_{m}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
        print(f"=== {m}: {sum(r['ready'] for r in results)}/{len(results)} forms ready")
        for r in results:
            print(f"{r['form']:36s} fields {r['fields']:3d} req {r['required']:3d} answered {r['answered']:3d} "
                  f"assumed {r['assumed']:2d} optional-empty {r['optional_empty']:2d} req-empty {len(r['empty_required']):2d} "
                  f"stops {len(r['stops'])} calls {[p['calls'] for p in r['pages']]} place {r['place_calls']} "
                  f"{'READY' if r['ready'] else 'NOT READY'} wrong {len(r['wrong_written'])}")


if __name__ == "__main__":
    main()
