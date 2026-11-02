"""Spike S-5b: print the answers table (last pass per step) from <run dir>/answers.json.

  python table.py <run dir> [title-substring ...]

Columns: step | label | req | value | source (profile key / resume / site prefill / program).
Prints the email address as <email>; never prints a password (none is stored there).
"""
import json
import re
import sys
from pathlib import Path


def main(run_dir, *only):
    ans = json.loads((Path(run_dir) / "answers.json").read_text(encoding="utf-8"))
    last = {}
    for stem in sorted(ans):
        last[ans[stem]["title"]] = ans[stem]
    for title, page in last.items():
        if only and not any(o.lower() in title.lower() for o in only):
            continue
        for d in page["answers"]:
            v = str(d.get("value") or "")
            if d.get("kind") == "file":
                v = Path(v).name if v else ("(kept)" if d.get("action") == "keep" else "")
            v = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", "<email>", v)
            src = d.get("source", "")
            if src == "keep_prefilled":
                src = "site prefill kept"
            elif d.get("profile_key"):
                src = f"{src}:{d['profile_key']}"
            if any(str(f).startswith("sensitive_from_profile") for f in d.get("flags") or []):
                src = f"program:{d.get('profile_key')}"
            act = d.get("action")
            if act in ("skip", "clear"):
                v = f"(empty; {act})"
            sec = (d.get("section") or "").split(" > ")[-1]
            lab = f"{sec}: {d.get('label')}" if sec and sec != title else str(d.get("label"))
            print(f"{title[:22]} | {lab[:60]} | {'Y' if d.get('required') else 'N'} | {v[:70]} | {src}")


if __name__ == "__main__":
    main(*sys.argv[1:])
