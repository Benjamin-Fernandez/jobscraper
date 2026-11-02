"""Spike S-5b (Q-23b, D-78): one step per call against the Edge kept by keeper.py.

  python drive.py <tenant> <cmd> [args]
    snap NAME          record the page (html, png, automation ids)
    goto URL           navigate + dismiss a cookie banner + record
    click SELECTOR     click (Workday click_filter sibling fallback) + record
    js CODE            evaluate a JS expression, print the JSON result (exploration)
    account            create the Workday account (password stored BEFORE the click)
    signin             sign in with the vault password
    verify             wait (read-only IMAP) for the verification link and open it
    page [--nofill]    read every field -> local model -> guard -> fill -> record
    next               Save and Continue / Next, then report field errors
    submit             Review page only, all guards held, click Submit ONCE

Run directory: $S5B_OUT/<tenant>/ (scratchpad; personal data, never committed).
Tenant settings (job url, employer, cdp port) come from $S5B_OUT/tenants.json.
Never prints the email address, the password or a verification link.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "src"))
sys.path.insert(0, str(HERE))

import llmfill as L                                    # noqa: E402
from jobscraper import vault                           # noqa: E402
from jobscraper.apply import browser as B              # noqa: E402
from jobscraper.apply.contracts import PasswordRules   # noqa: E402

MAIN = Path(os.environ.get("JOBSCRAPER_MAIN", HERE.parent.parent))
OUT = Path(os.environ["S5B_OUT"])
PROFILE = MAIN / "data" / "applicant.yaml"
RESUME = MAIN / "data" / "resume.pdf"


def _email() -> str:
    import keyring
    c = keyring.get_credential(vault.imap_service("imap.gmail.com"), None)
    if c is None or not c.username:
        raise SystemExit("no Credential Manager entry for the application mailbox")
    return c.username


def _scrub(s: str) -> str:
    e = _email()
    return re.sub(re.escape(e), "<email>", str(s), flags=re.I)


class Ctx:
    def __init__(self, tenant: str):
        self.tenant = tenant
        self.cfg = json.loads((OUT / "tenants.json").read_text(encoding="utf-8"))[tenant]
        self.dir = OUT / tenant
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.dir / "state.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {
            "seq": 0, "stops": [], "submitted": False, "pages": []}
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{self.cfg['port']}")
        ctx = self.browser.contexts[0]
        pages = [p for p in ctx.pages if not p.url.startswith("devtools")]
        self.page = pages[-1]

    def save(self):
        self.state_path.write_text(json.dumps(self.state, indent=1), encoding="utf-8")

    def close(self):
        self.save()
        try:
            self._pw.stop()
        except Exception:
            pass

    def rec(self, name: str) -> str:
        self.state["seq"] += 1
        stem = f"{self.state['seq']:02d}-{B.slug(name)}"
        p = self.page
        try:
            html = p.content()
            html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)
            (self.dir / f"{stem}.html").write_text(html, encoding="utf-8")
        except Exception:
            pass
        try:
            p.screenshot(path=str(self.dir / f"{stem}.png"), full_page=True)
        except Exception:
            pass
        ids_path = self.dir / "automation_ids.json"
        ids = json.loads(ids_path.read_text()) if ids_path.exists() else {}
        try:
            ids[stem] = {"url": p.url, "title": L.page_title(p),
                         "botcheck": p.evaluate(L.BOTCHECK_JS),
                         "ids": p.evaluate("() => [...new Set([...document.querySelectorAll('[data-automation-id]')].map(e => e.getAttribute('data-automation-id')))].sort()")}
        except Exception as exc:
            ids[stem] = {"error": type(exc).__name__}
        ids_path.write_text(json.dumps(ids, indent=1), encoding="utf-8")
        self.save()
        return stem


def dismiss_cookies(page) -> str:
    for sel in ('[data-automation-id="legalNoticeDeclineButton"]',
                'button:has-text("Decline")', 'button:has-text("Reject")',
                'button:has-text("Accept necessary")', 'button:has-text("Necessary only")'):
        loc = page.locator(sel)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=3000)
                page.wait_for_timeout(500)
                return sel
        except Exception:
            continue
    return ""


def wd_click(page, loc) -> str:
    """Click; Workday hides some submit buttons behind a sibling click_filter div."""
    try:
        loc.first.click(timeout=3000)
        return "direct"
    except Exception:
        pass
    for xp in ('xpath=preceding-sibling::div[@data-automation-id="click_filter"][1]',
               'xpath=following-sibling::div[@data-automation-id="click_filter"][1]',
               'xpath=..'):
        s = loc.first.locator(xp)
        try:
            if s.count():
                s.first.click(timeout=3000)
                return xp
        except Exception:
            continue
    raise RuntimeError("could not click")


def errors(page) -> list[dict]:
    try:
        return page.evaluate(L.ERRORS_JS)
    except Exception:
        return []


def botcheck(page) -> bool:
    try:
        return bool(page.evaluate(L.BOTCHECK_JS))
    except Exception:
        return False


# ------------------------------------------------------------------ commands

def cmd_snap(c: Ctx, name: str):
    print(c.rec(name), "|", L.page_title(c.page), "| botcheck:", botcheck(c.page))


def cmd_goto(c: Ctx, url: str):
    c.page.goto(url, wait_until="domcontentloaded")
    B.settle(c.page, 1500)
    print("cookie:", dismiss_cookies(c.page) or "none")
    print(c.rec("goto"), "|", L.page_title(c.page), "| botcheck:", botcheck(c.page))


def cmd_click(c: Ctx, sel: str):
    how = wd_click(c.page, c.page.locator(sel))
    B.settle(c.page, 2000)
    dismiss_cookies(c.page)
    print("clicked via", how, "|", c.rec("click"), "|", L.page_title(c.page),
          "| errors:", _scrub(errors(c.page)), "| botcheck:", botcheck(c.page))


def cmd_js(c: Ctx, code: str):
    print(_scrub(json.dumps(c.page.evaluate(code), ensure_ascii=False)[:6000]))


def _account_json(c: Ctx, **kw):
    p = c.dir / "account.json"
    a = json.loads(p.read_text()) if p.exists() else {}
    a.update(kw)
    p.write_text(json.dumps(a, indent=1), encoding="utf-8")
    return a


def cmd_account(c: Ctx):
    page = c.page
    host = urlsplit(page.url).hostname
    service = vault.service_for("workday", host)
    email = _email()
    attempts = c.state.get("account_attempts", 0)
    if attempts >= 2:
        raise SystemExit("account attempt limit (2) reached")
    if vault.get(service, email) is not None:
        print("vault already has a password for", service, "-> use signin")
        return
    if not page.locator('[data-automation-id="createAccountSubmitButton"]').count():
        wd_click(page, page.locator('[data-automation-id="createAccountLink"]'))
        page.wait_for_timeout(1500)
    if botcheck(page):
        raise SystemExit("bot check on the account page: stop")
    secret = vault.generate(PasswordRules())
    vault.put(service, email, secret)                 # stored BEFORE the sign-up click
    _account_json(c, host=host, vault_service=service, password_stored_at=L.now())
    ok = [B.fill_text(page.locator('[data-automation-id="email"]').first, email),
          B.fill_text(page.locator('[data-automation-id="password"]').first, secret.reveal()),
          B.fill_text(page.locator('[data-automation-id="verifyPassword"]').first, secret.reveal())]
    box = page.locator('[data-automation-id="createAccountCheckbox"]')
    if box.count():
        ok.append(B.set_checkbox(box.first, True))
    print("filled:", ok)
    if not all(ok):
        raise SystemExit("account form did not read back: not submitted")
    c.state["account_attempts"] = attempts + 1
    c.save()
    _account_json(c, create_clicked_at=L.now())
    wd_click(page, page.locator('[data-automation-id="createAccountSubmitButton"]'))
    B.settle(page, 4000)
    errs = errors(page)
    _account_json(c, create_result_title=L.page_title(page), create_errors=_scrub(errs))
    print(c.rec("account-created"), "|", L.page_title(page), "| errors:", _scrub(errs),
          "| botcheck:", botcheck(page))


def cmd_signin(c: Ctx):
    page = c.page
    host = urlsplit(page.url).hostname
    email = _email()
    secret = vault.get(vault.service_for("workday", host), email)
    if secret is None:
        raise SystemExit("no vault password for this tenant")
    if not page.locator('[data-automation-id="signInSubmitButton"]').count():
        lk = page.locator('[data-automation-id="signInLink"], [data-automation-id="utilityButtonSignIn"]')
        if lk.count():
            wd_click(page, lk)
            page.wait_for_timeout(1500)
    ok = [B.fill_text(page.locator('[data-automation-id="email"]').first, email),
          B.fill_text(page.locator('[data-automation-id="password"]').first, secret.reveal())]
    print("filled:", ok)
    wd_click(page, page.locator('[data-automation-id="signInSubmitButton"]'))
    B.settle(page, 4000)
    print(c.rec("signed-in"), "|", L.page_title(page), "| errors:", _scrub(errors(page)),
          "| botcheck:", botcheck(page))


def cmd_verify(c: Ctx):
    import datetime as dt
    from jobscraper.apply import mail
    email = _email()
    a = json.loads((c.dir / "account.json").read_text())
    since = dt.datetime.strptime(a["create_clicked_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    w = mail.MailWatcher("imap.gmail.com", 993, email,
                         vault.get(vault.imap_service("imap.gmail.com"), email))
    v = w.wait_for(since_utc=since, sender_domains=["myworkday.com", "myworkdayjobs.com", "workday.com"],
                   link_domains=["myworkdayjobs.com", "myworkday.com"], otp_pattern=None,
                   want="link", wait_s=300, poll_s=15, to_addr=email)
    print("verification", v.kind, "from", v.sender_domain, "at", v.received_at)
    c.page.goto(v.value, wait_until="domcontentloaded")
    B.settle(c.page, 3000)
    _account_json(c, verified_at=L.now(), verification_sender=v.sender_domain)
    print(c.rec("verified"), "|", L.page_title(c.page), "| errors:", _scrub(errors(c.page)))


def _load_inputs():
    from jobscraper.profile.resume_ingest import extract_text
    raw, sens, ptext = L.load_profile(str(PROFILE))
    rtext = extract_text(str(RESUME))
    return raw, sens, ptext, rtext


def cmd_page(c: Ctx, nofill: bool = False, extra: str = ""):
    page = c.page
    if botcheck(page):
        c.state["stops"].append("bot check seen")
        c.save()
        raise SystemExit("bot check: stop")
    title = L.page_title(page)
    stem = f"{c.state['seq'] + 1:02d}-{B.slug(title)}"
    fields = L.read_fields(page)
    errs = errors(page)
    for e in errs:
        for f in fields:
            if e.get("field") == f["id"]:
                f["error"] = e["text"]
    (c.dir / f"fields_{stem}.json").write_text(json.dumps(fields, indent=1, ensure_ascii=False), encoding="utf-8")
    raw, sens, ptext, rtext = _load_inputs()
    job = {"employer": c.cfg["employer"], "title": c.cfg["title"], "location": c.cfg.get("location", ""),
           "page": title}
    be = L.make_backend()
    answers, meta = L.ask_model(be, fields, ptext, rtext, job, c.dir / f"prompt_{stem}.json", extra)
    L.resolve_choices(be, fields, answers)
    corpus = "\n".join([ptext, rtext, L.STANDING, json.dumps(job), yaml_dump(raw)])
    decisions, stops = L.guard(fields, answers, sens, corpus)
    for d in decisions:
        if d["kind"] == "file":
            L.file_decision(page, d, title, str(RESUME))
            if d["action"] == "skip" and d["required"]:
                stops.append(f"required file slot that is not the resume: {d['label']!r}")
    if not nofill:
        L.fill(page, be, decisions)
        B.settle(page, 1500)
    ap = c.dir / "answers.json"
    allans = json.loads(ap.read_text(encoding="utf-8")) if ap.exists() else {}
    allans[stem] = {"title": title, "model": meta, "stops": stops, "answers": decisions,
                    "recorded_at": L.now()}
    ap.write_text(json.dumps(allans, indent=1, ensure_ascii=False), encoding="utf-8")
    c.state["pages"].append({"stem": stem, "title": title, "meta": meta, "stops": stops})
    ps = c.state.setdefault("page_stops", {})
    ps[title] = stops                                  # a re-ask replaces this page's stops
    c.state["stops"] = sorted({s for v in ps.values() for s in v} |
                              {s for s in c.state["stops"] if s.startswith("bot check")})
    rec = c.rec(f"filled-{title}")
    print(f"page {title!r}: {len(fields)} fields, model {meta['latency_s']}s "
          f"({meta['input_tokens']} in / {meta['output_tokens']} out, {meta['done_reason']}) -> {rec}")
    for d in decisions:
        v = "<S>" if any(fl.startswith("sensitive") for fl in d.get("flags", [])) else _scrub(str(d["value"]))[:50]
        print(f"  [{d['kind'][:5]:5}] {'*' if d['required'] else ' '} {str(d['label'])[:55]:55} | {d['source']:14} | "
              f"{d['action']:5} {d.get('filled', ''):6} | {v} {d.get('flags') or ''}")
    print("STOPS:", stops or "none", "| errors after fill:", _scrub([e['text'] for e in errors(page)]))


def yaml_dump(x) -> str:
    import yaml
    return yaml.safe_dump(x, allow_unicode=True)


NEXT_SEL = ('[data-automation-id="pageFooterNextButton"], [data-automation-id="bottom-navigation-next-button"], '
            'button:has-text("Save and Continue"), button:has-text("Next")')


def cmd_next(c: Ctx):
    page = c.page
    before = L.page_title(page)
    btn = page.locator(NEXT_SEL)
    label = (btn.first.inner_text() or "").strip() if btn.count() else ""
    if re.search(r"submit", label, re.I):
        raise SystemExit("the next button is Submit: use the submit command")
    wd_click(page, btn)
    B.settle(page, 3000)
    after = L.page_title(page)
    errs = errors(page)
    print(f"next: {before!r} -> {after!r} | errors: {_scrub([e['text'] for e in errs])} | botcheck: {botcheck(page)}")
    print(c.rec(f"after-next-{after}"))


def cmd_submit(c: Ctx):
    page = c.page
    if c.state.get("submitted") or c.state.get("submit_clicked_at"):
        raise SystemExit("already submitted/clicked once: never resubmit")
    if c.state["stops"]:
        raise SystemExit(f"guards did not hold: {c.state['stops']}")
    if not (c.dir / "answers.json").exists():
        raise SystemExit("answers.json missing")
    title = L.page_title(page)
    if not re.search(r"review", title, re.I):
        raise SystemExit(f"not on the Review page ({title!r})")
    if botcheck(page):
        raise SystemExit("bot check: stop")
    btn = page.locator(NEXT_SEL)
    label = (btn.first.inner_text() or "").strip() if btn.count() else ""
    if not re.search(r"submit", label, re.I):
        raise SystemExit(f"no Submit button (found {label!r})")
    c.rec("review-before-submit")
    c.state["submit_clicked_at"] = L.now()
    c.save()
    wd_click(page, btn)
    B.settle(page, 6000)
    conf = page.evaluate("() => { const d = document.querySelector('[role=dialog], [data-automation-id=\"congratulationsPopup\"], h2');"
                         " return d ? (d.innerText || '').replace(/\\s+/g,' ').trim().slice(0, 400) : document.title; }")
    errs = errors(page)
    c.state["submitted"] = not errs
    c.state["confirmation"] = _scrub(conf)
    _account_json(c, submitted=not errs, submitted_at=L.now(), confirmation_text=_scrub(conf),
                  submit_errors=_scrub([e["text"] for e in errs]))
    print(c.rec("after-submit"), "| confirmation:", _scrub(conf), "| errors:", _scrub(errs))


def main(argv):
    tenant, cmd, *args = argv
    c = Ctx(tenant)
    try:
        if cmd == "snap":
            cmd_snap(c, args[0] if args else "snap")
        elif cmd == "goto":
            cmd_goto(c, args[0])
        elif cmd == "click":
            cmd_click(c, args[0])
        elif cmd == "js":
            cmd_js(c, args[0])
        elif cmd == "account":
            cmd_account(c)
        elif cmd == "signin":
            cmd_signin(c)
        elif cmd == "verify":
            cmd_verify(c)
        elif cmd == "read":
            for f in L.read_fields(c.page):
                o = f.get("options")
                print(f"[{f['kind'][:5]:5}] {'*' if f['required'] else ' '} {f['label'][:60]:60} | sec={f.get('section','')[:40]} "
                      f"| cur={_scrub(str(f.get('current','')))[:30]!r} | opts={len(o) if o is not None else '-'}"
                      f"{' ' + str(o[:6]) if o else ''} | {f['automation_id']}")
        elif cmd == "page":
            extra = ""
            if "--reask" in args:
                prev = c.state.get("page_stops", {}).get(L.page_title(c.page), [])
                extra = ("SECOND PASS. These required fields were left unanswered on the first pass: "
                         + "; ".join(prev) + ". A required field may be answered by splitting or "
                         "reformatting PROFILE or RESUME data (for example one address line into its street "
                         "and block/house-number parts across two fields), as long as nothing is invented. "
                         "If the sources still do not contain it, keep source unknown.\n\n")
            cmd_page(c, nofill="--nofill" in args, extra=extra)
        elif cmd == "next":
            cmd_next(c)
        elif cmd == "submit":
            cmd_submit(c)
        else:
            raise SystemExit(f"unknown command {cmd}")
    finally:
        c.close()


if __name__ == "__main__":
    main(sys.argv[1:])
