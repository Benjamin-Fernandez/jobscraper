"""Spike S-5b: single-field model re-check of a prefilled free-text field.

  python recheck.py <tenant> <css of the textarea/input> <index> <entry name>

The resume parser of an ATS can put text from other resume sections into one job's
description. The model checks the prefilled text against the resume and, when it mixes
sections, returns only that entry's lines verbatim; the program fills it only when the
answer is grounded in the resume (>= 90% of its tokens).
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "src"))
sys.path.insert(0, str(HERE))

import llmfill as L                                           # noqa: E402
from jobscraper.apply import browser as B                     # noqa: E402
from jobscraper.profile.resume_ingest import extract_text     # noqa: E402

SYS = ("You check one prefilled job-application field against the applicant's RESUME. The field is the role "
       "description of ONE job. If the current text also contains text that belongs to other resume sections "
       "(other jobs, projects, skills), answer contains_other_sections and give in value ONLY the lines listed "
       "under that job in the RESUME, copied verbatim. Otherwise answer correct and copy the current text.")


def main(tenant, css, idx, entry):
    from playwright.sync_api import sync_playwright
    out = Path(os.environ["S5B_OUT"])
    cfg = json.loads((out / "tenants.json").read_text())[tenant]
    main_dir = Path(os.environ["JOBSCRAPER_MAIN"])
    resume = extract_text(str(main_dir / "data" / "resume.pdf"))
    pw = sync_playwright().start()
    br = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{cfg['port']}")
    page = [p for p in br.contexts[0].pages if not p.url.startswith("devtools")][-1]
    ta = page.locator(css).nth(int(idx))
    cur = ta.input_value()
    be = L.make_backend()
    schema = {"type": "object", "properties": {
        "verdict": {"type": "string", "enum": ["correct", "contains_other_sections"]},
        "value": {"type": "string"}}, "required": ["verdict", "value"]}
    user = (json.dumps({"job": entry, "field": "Role Description", "current": cur}, ensure_ascii=False)
            + "\n\nRESUME:\n" + resume)
    t0 = time.monotonic()
    comp = be.complete(SYS, user, max_tokens=3000, format=schema, timeout=600)
    dt = round(time.monotonic() - t0, 1)
    ans = json.loads(comp.text)
    ok = L.grounded(ans["value"], set(L._tokens(resume)), 0.9) and len(ans["value"]) < len(cur)
    (out / tenant / f"prompt_recheck_{B.slug(entry)}.json").write_text(json.dumps(
        {"system": SYS, "user": user, "raw": comp.text, "latency_s": dt}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("latency", dt, "verdict", ans["verdict"], "len", len(cur), "->", len(ans["value"]), "grounded+shorter", ok)
    if ok:      # S-5b: qwen3:14b answered "correct" yet returned the trimmed text; the value decides
        print("filled", B.fill_text(ta, ans["value"]))
        print("now ends:", repr(ta.input_value()[-100:]))
    pw.stop()


if __name__ == "__main__":
    main(*sys.argv[1:5])
