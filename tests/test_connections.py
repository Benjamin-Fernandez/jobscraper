"""Q-100 T1-A oracles: the Connected accounts hub backend (q100_ui_design sections 2.3, 3, 4.4;
D-191 no secret to the browser, D-195 rulings, D-196 need_reason / pending_mail).
Verify: `python tests/run_tests.py -k connections`.

Two layers, no network and no real vault:
- `compose()` is pure. Every case of tests/fixtures/connections_rows.json (one per section 2.3
  row) is composed from raw store rows and the (id, state, code) it names is asserted.
- `GET /api/connections` runs through `create_app` over a real temp DB, an in-memory keyring
  that holds a marker "password", a spy in place of the mail child, and a stub probe.
"""
from __future__ import annotations

import contextlib
import copy
import json
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_flow_support import memory_keyring, tmpdir  # noqa: E402

ROWS = json.loads((Path(__file__).resolve().parent / "fixtures" / "connections_rows.json")
                  .read_text(encoding="utf-8"))
MARKER = "S3CRET-MARKER"
EVIL = {"Origin": "https://evil.example"}
OLLAMA_URL = "http://ollama-host.test:11434"
ENV_KEYS = ("JOBSCRAPER_BACKEND", "JOBSCRAPER_OLLAMA_URL")


@contextlib.contextmanager
def _clean_env():
    """The model resolution reads two env vars; a developer's shell must not matter."""
    saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


# ------------------------------------------------------------------ the pure composer

class FakeStore:
    """The three reads compose makes: mail_accounts(), accounts(), get_setting()."""

    def __init__(self, mail=None, accounts=None, settings=None, mail_error=None, accounts_error=None):
        self.mail, self.accts, self.settings = mail or [], accounts or [], settings or {}
        self.mail_error, self.accounts_error = mail_error, accounts_error

    def mail_accounts(self, enabled_only=False):
        if self.mail_error:
            raise self.mail_error
        return copy.deepcopy(self.mail)

    def accounts(self):
        if self.accounts_error:
            raise self.accounts_error
        return copy.deepcopy(self.accts)

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)


def _effective(case_inputs: dict) -> dict:
    """defaults + the case's overrides, with the three config shorthands expanded."""
    inputs = copy.deepcopy(ROWS["defaults"])
    ins = copy.deepcopy(case_inputs)
    cfg = inputs["cfg"]
    if "cfg_apply_mail" in ins:
        cfg["apply_mail"] = ins.pop("cfg_apply_mail")
    if "cfg_apply_mail_backup" in ins:
        cfg["apply_mail_backup"] = ins.pop("cfg_apply_mail_backup")
    if "cfg_model" in ins:
        m = ins.pop("cfg_model")
        cfg["budget_enable_llm"], cfg["budget_backend"] = m["enable_llm"], m["backend"]
    inputs.update(ins)
    return inputs


def _config(c: dict):
    from jobscraper.config import Config
    return Config({
        "paths": {"db": "unused.db"},
        "budget": {"enable_llm": c["budget_enable_llm"], "backend": c["budget_backend"],
                   "ollama_model": c["budget_model"]},
        "mail_status": {"enabled": c["mail_status_enabled"]},
        "apply": {"profile_dir": c["apply_profile_dir"], "edge_sync": c["apply_edge_sync"],
                  "mail": c["apply_mail"], "mail_backup": c["apply_mail_backup"]},
    })


def _compose(case_inputs: dict, *, vault_has=None, store=None, cfg=None) -> dict:
    from jobscraper.web.connections import compose
    inp = _effective(case_inputs)
    has = inp["vault_has"]
    return compose(
        cfg or _config(inp["cfg"]),
        store or FakeStore(mail=inp["mail_accounts"], accounts=inp["ats_accounts"]),
        inp["mail_runner"], inp["job_view"], inp["model_snapshot"],
        vault_has or (lambda service, user: bool(has.get(f"{service}|{user}", False))),
        lambda d: bool(inp["edge"]["lockfile_busy"]),
        inp["now"],
        lambda d: bool(inp["edge"]["profile_dir_exists"]))


def _find(body: dict, id_: str) -> dict:
    if id_.startswith("account:"):
        want = int(id_.split(":", 1)[1])
        rows = [r for r in body["employer_accounts"] if r["id"] == want]
    else:
        rows = [i for i in body["items"] if i["id"] == id_]
    assert len(rows) == 1, f"{id_}: expected one, got {len(rows)}"
    return rows[0]


def _case(name: str, **override) -> dict:
    ins = copy.deepcopy(ROWS["cases"][name]["inputs"])
    ins.update(override)
    return ins


def _model(body: dict) -> dict:
    return _find(body, "model")


def test_connections_every_section_2_3_row_maps_to_its_state_and_code():
    cases = ROWS["cases"]
    assert len(cases) >= 47
    with _clean_env():
        bad = []
        for name, case in cases.items():
            body = _compose(case["inputs"])
            want = case["expect"]
            got = _find(body, want["id"])
            if (got["state"], got["code"]) != (want["state"], want["code"]):
                bad.append(f"{name}: want {want['state']}/{want['code']}, got {got['state']}/{got['code']}")
        assert not bad, "\n".join(bad)


def test_connections_response_shape_is_schema_v1():
    with _clean_env():
        body = _compose({})
    assert set(body) == {"version", "checked_at", "attention", "items", "employer_accounts", "no_account_needed"}
    assert body["version"] == 1 and body["checked_at"] == ROWS["defaults"]["now"]
    assert body["no_account_needed"] == ["greenhouse", "lever", "ashby"]
    ids = [i["id"] for i in body["items"]]
    assert ids == ["gmail", "apply-mailbox", "apply-mailbox:backup", "edge", "model", "employer-accounts"], ids
    keys = {"id", "kind", "state", "code", "message", "optional", "stored_in", "checked_at",
            "next_check_at", "last_ok_at", "retry_after", "facts"}
    assert all(set(i) == keys for i in body["items"])
    assert all(i["state"] in {"connected", "attention", "neutral", "not_set_up", "paused", "checking"}
               for i in body["items"])


def test_connections_attention_counts_the_items_in_attention():
    with _clean_env():
        everything = _compose(_case("gmail_paused_login_refused",
                                    ats_accounts=ROWS["cases"]["employer_signin_failed"]["inputs"]["ats_accounts"],
                                    cfg_apply_mail=ROWS["cases"]["apply_mailbox_no_password"]["inputs"]["cfg_apply_mail"]))
    n = sum(1 for i in everything["items"] if i["state"] == "attention")
    assert n >= 3 and everything["attention"] == n


# ------------------------------------------------------------------ need_now / need_reason / pending_mail (D-196)

# case -> (need_reason, pending_mail); rule order a (running job: apply is "application",
# other model users "run", mailtest none), b in-flight attempt, c model_unavailable within
# 24 h, d mail waiting. A negative case reads null.
NEED = {
    "model_unreachable_need_now": ("run", 0),            # a: tailor
    "model_missing_need_now": ("run", 0),                # a: scrape
    "need_now_a_job_running": ("run", 0),                # a: profile
    "need_now_a_mailtest_does_not_count": (None, 0),
    "need_now_b_attempt_in_flight": ("application", 0),
    "need_now_b_attempt_in_flight_stale": (None, 0),       # D-198 M3: started 2 h or more ago
    "need_now_c_model_unavailable_recent": ("application", 0),
    "need_now_c_model_unavailable_old": (None, 0),
    "need_now_d_pending_model": ("mail", 5),
    "model_unreachable_idle": (None, 0),
    "model_missing_idle": (None, 0),
    "model_ok": (None, 0),
    "model_probing": (None, 0),
    "model_ai_off_enable_llm": (None, 0),
    "model_ai_off_backend": (None, 0),
    "model_misconfigured": (None, 0),
}


def test_connections_need_now_and_need_reason_for_every_rule():
    assert {n for n, c in ROWS["cases"].items() if c["expect"]["id"] == "model"} == set(NEED) | {
        n for n, c in ROWS["cases"].items() if c["expect"]["id"] == "model" and n not in NEED}
    with _clean_env():
        bad = []
        for name, (reason, mail) in NEED.items():
            facts = _model(_compose(ROWS["cases"][name]["inputs"]))["facts"]
            got = (facts.get("need_reason"), facts.get("pending_mail"), facts.get("need_now"))
            if got != (reason, mail, reason is not None):
                bad.append(f"{name}: want {(reason, mail, reason is not None)}, got {got}")
        assert not bad, "\n".join(bad)


def test_connections_rule_a_a_running_apply_job_is_an_application_other_kinds_are_a_run():
    with _clean_env():
        for kind, want in (("apply", "application"), ("tailor", "run"), ("scrape", "run"), ("profile", "run"),
                           ("run", "run"), ("mailtest", None)):
            jv = {"current": {"state": "running", "kind": kind}, "attempts_in_flight": [], "last_attempts": {}}
            facts = _model(_compose({"job_view": jv, "model_snapshot": ROWS["cases"]["model_ok"]["inputs"].get("model_snapshot")}))["facts"]
            assert facts["need_reason"] == want, (kind, facts)
            assert facts["need_now"] is (want is not None), (kind, facts)
        # a job that is not running (finished, cancelled) waits on nothing
        for state in ("done", "failed", "cancelled", "idle"):
            jv = {"current": {"state": state, "kind": "apply"}, "attempts_in_flight": [], "last_attempts": {}}
            assert _model(_compose({"job_view": jv}))["facts"]["need_reason"] is None, state


def test_connections_need_reason_follows_the_rule_order_a_b_c_d():
    a = {"state": "running", "kind": "apply"}
    b = [{"id": 1, "job_id": "j", "state": "filling", "started_at": "2026-11-11T09:00:00"}]   # 12 min before now
    c = ROWS["cases"]["need_now_c_model_unavailable_recent"]["inputs"]["job_view"]["last_attempts"]
    d = ROWS["cases"]["need_now_d_pending_model"]["inputs"]["mail_accounts"]
    with _clean_env():
        def reason(**jv):
            view = {"current": None, "attempts_in_flight": [], "last_attempts": {}, **jv}
            mail = d if jv.pop("with_mail", True) else []
            return _model(_compose({"job_view": view, "mail_accounts": mail}))["facts"]
        assert reason(current=a, attempts_in_flight=b, last_attempts=c)["need_reason"] == "application"  # a: apply
        assert reason(current={"state": "running", "kind": "tailor"}, attempts_in_flight=b,
                      last_attempts=c)["need_reason"] == "run"                                           # a beats b
        assert reason(attempts_in_flight=b, last_attempts=c)["need_reason"] == "application"            # b
        assert reason(last_attempts=c)["need_reason"] == "application"                                  # c
        f = reason()
        assert f["need_reason"] == "mail" and f["pending_mail"] == 5                                    # d last
        # pending_mail is the count whatever else is waiting
        f = reason(current={"state": "running", "kind": "tailor"})
        assert f["need_reason"] == "run" and f["pending_mail"] == 5


def test_connections_rule_b_counts_an_attempt_started_less_than_2h_ago_and_ignores_older_ones():
    """D-198 M3: an attempt row left in a live state by a crashed run must not hold
    the model 'needed' for ever. now = 2026-11-11T09:12:00, so the cut is 07:12:00:
    started_at at or before it is ignored, after it counts."""
    snap = ROWS["cases"]["need_now_b_attempt_in_flight"]["inputs"]["model_snapshot"]

    def reason(*started):
        flight = [{"id": 50 + i, "job_id": f"job-{i}", "state": "filling", "started_at": s}
                  for i, s in enumerate(started)]
        jv = {"current": None, "attempts_in_flight": flight, "last_attempts": {}}
        return _model(_compose({"job_view": jv, "model_snapshot": snap}))["facts"]
    with _clean_env():
        for s in ("2026-11-11T09:11:00", "2026-11-11T08:12:00", "2026-11-11T07:12:01"):
            f = reason(s)
            assert (f["need_reason"], f["need_now"]) == ("application", True), s
        # (the exact second 07:12:00 is not pinned: see comms/outbox/tester.md, boundary note)
        for s in ("2026-11-11T07:11:59", "2026-11-11T07:11:00", "2026-11-11T05:00:00", "2026-11-09T09:00:00"):
            f = reason(s)
            assert (f["need_reason"], f["need_now"]) == (None, False), s
        # an in-flight row with no started_at counts (unknown is not stale)
        jv = {"current": None, "last_attempts": {}, "attempts_in_flight": [{"id": 50, "job_id": "j", "state": "filling"}]}
        assert _model(_compose({"job_view": jv, "model_snapshot": snap}))["facts"]["need_reason"] == "application"
        # the window is IN_FLIGHT_HOURS = 2 (D-198)
        from jobscraper.web.connections import IN_FLIGHT_HOURS
        assert IN_FLIGHT_HOURS == 2
        # one fresh among stale ones is enough; all stale is not
        assert reason("2026-11-10T01:00:00", "2026-11-11T09:00:00")["need_reason"] == "application"
        assert reason("2026-11-10T01:00:00", "2026-11-11T03:00:00")["need_reason"] is None
        # a stale attempt does not outrank rules c and d below it
        c = ROWS["cases"]["need_now_c_model_unavailable_recent"]["inputs"]["job_view"]["last_attempts"]
        jv = {"current": None, "last_attempts": c,
              "attempts_in_flight": [{"id": 50, "job_id": "j", "state": "filling", "started_at": "2026-11-11T01:00:00"}]}
        assert _model(_compose({"job_view": jv, "model_snapshot": snap}))["facts"]["need_reason"] == "application"
        # a stale in-flight attempt leaves an unreachable model neutral, not attention
        stale = _model(_compose(ROWS["cases"]["need_now_b_attempt_in_flight_stale"]["inputs"]))
        assert (stale["state"], stale["code"]) == ("neutral", "unreachable")


def _mailbox_case(primary: str, backup: str, vault_has: dict, backup_host: str = "") -> dict:
    return {"cfg_apply_mail": {"host": "imap.gmail.com", "port": 993, "username": primary},
            "cfg_apply_mail_backup": {"host": backup_host, "port": 993, "username": backup},
            "vault_has": vault_has}


def test_connections_m2_a_backup_with_the_primarys_username_is_no_item_and_counts_nothing_twice():
    """D-198 M2: the same username (case-insensitive, trimmed) is one mailbox, not two.
    No `apply-mailbox:backup` item, and a missing password is one attention, not two."""
    no_pw = {"jobscraper:imap:imap.gmail.com|apply@example.com": False}
    ok = {"jobscraper:imap:imap.gmail.com|apply@example.com": True}
    with _clean_env():
        base = _compose(_mailbox_case("apply@example.com", "", no_pw))        # backup unset
        for backup in ("apply@example.com", "APPLY@Example.com", "  apply@example.com  ", " Apply@EXAMPLE.com"):
            for vault_has, state in ((no_pw, "attention"), (ok, "connected")):
                body = _compose(_mailbox_case("apply@example.com", backup, vault_has))
                ids = [i["id"] for i in body["items"]]
                assert "apply-mailbox:backup" not in ids, (backup, ids)
                assert ids == ["gmail", "apply-mailbox", "edge", "model", "employer-accounts"], (backup, ids)
                assert _find(body, "apply-mailbox")["state"] == state
                assert body["attention"] == sum(1 for i in body["items"] if i["state"] == "attention")
        # a missing password counts once: the attention total is that of the mailbox alone
        body = _compose(_mailbox_case("apply@example.com", "Apply@Example.com", no_pw))
        assert [i["id"] for i in body["items"] if i["state"] == "attention"] == ["apply-mailbox"]
        assert body["attention"] == base["attention"] == 1
        # the primary's own facts say the backup is not separate
        assert _find(body, "apply-mailbox")["facts"]["backup_separate"] is False


def test_connections_m2_a_different_backup_username_is_still_its_own_item():
    """The M2 rule is about equal usernames only: a real backup keeps its item and its own count."""
    pw = {"jobscraper:imap:imap.gmail.com|apply@example.com": True,
          "jobscraper:imap:imap.gmail.com|other@example.com": False}
    with _clean_env():
        body = _compose(_mailbox_case("apply@example.com", "other@example.com", pw))
    assert _find(body, "apply-mailbox:backup")["state"] == "attention"
    assert _find(body, "apply-mailbox")["facts"]["backup_separate"] is True
    assert body["attention"] == 1


def test_connections_h1_the_employer_fix_url_must_reach_the_workday_tenant():
    """D-198 H1/M1: the fix command prints `--url https://<tenant_host>/careers`. The CLI
    resolves a URL through the navigators' match_url; the bare host root names no tenant
    and exits 2 (`accounts add` -> 'no known ATS'), which is why the hub appends /careers."""
    from jobscraper.cli import _account_tenant
    for host in ("acme.wd3.myworkdayjobs.com", "example.wd5.myworkdayjobs.com"):
        got = _account_tenant(f"https://{host}/careers")
        assert got is not None, host
        ats, tenant = got
        assert ats == "workday" and tenant.host == host, (ats, tenant)
        assert _account_tenant(f"https://{host}/") is None, host
        assert _account_tenant(f"https://{host}") is None, host
    # the sample hosts the hub is shown with
    hosts = {a["tenant_host"] for c in ROWS["cases"].values() for a in c["inputs"].get("ats_accounts", [])}
    assert hosts
    for host in hosts:
        assert _account_tenant(f"https://{host}/careers") is not None, host


def test_connections_pending_mail_sums_every_mailbox_and_ignores_bad_counts():
    base = copy.deepcopy(ROWS["cases"]["need_now_d_pending_model"]["inputs"]["mail_accounts"][0])

    def row(i, counts):
        r = copy.deepcopy(base)
        r["id"], r["address"] = i, f"owner{i}@example.com"
        r["last_counts_json"] = counts if isinstance(counts, str) or counts is None else json.dumps(counts)
        return r
    with _clean_env():
        f = _model(_compose({"mail_accounts": [row(1, {"pending_model": 3}), row(2, {"pending_model": 4}),
                                               row(3, "not json"), row(4, None), row(5, {"scanned": 9})]}))["facts"]
        assert (f["pending_mail"], f["need_reason"]) == (7, "mail")
        f = _model(_compose({"mail_accounts": [row(1, {"pending_model": 0})]}))["facts"]
        assert (f["pending_mail"], f["need_reason"], f["need_now"]) == (0, None, False)
        assert _model(_compose({}))["facts"]["pending_mail"] == 0


def test_connections_model_facts_are_fixed_words_and_numbers_only():
    with _clean_env():
        for name in NEED:
            facts = _model(_compose(ROWS["cases"][name]["inputs"]))["facts"]
            assert set(facts) == {"backend", "model", "local", "need_now", "need_reason", "pending_mail"}, (name, facts)
            assert facts["need_reason"] in (None, "run", "application", "mail"), (name, facts)
            assert isinstance(facts["pending_mail"], int) and not isinstance(facts["pending_mail"], bool)


def test_connections_a_down_ollama_is_attention_only_when_something_waits():
    with _clean_env():
        idle = _model(_compose(ROWS["cases"]["model_unreachable_idle"]["inputs"]))
        busy = _model(_compose(ROWS["cases"]["model_unreachable_need_now"]["inputs"]))
    assert (idle["state"], idle["code"]) == ("neutral", "unreachable")
    assert (busy["state"], busy["code"]) == ("attention", "unreachable")


def test_connections_the_web_sample_agrees_with_the_d196_facts_and_the_switched_off_rule():
    sample = json.loads((Path(__file__).resolve().parent.parent / "web" / "tests" / "fixtures"
                         / "connections.sample.json").read_text(encoding="utf-8"))
    models = [i for i in sample["items"] if i["kind"] == "model"]
    assert len(models) == 1
    for name, v in sample["variants"].items():
        it = v.get("item")
        if it and it["kind"] == "model":
            want = NEED[name]
            assert (it["facts"]["need_reason"], it["facts"]["pending_mail"]) == want, name
            assert it["facts"]["need_now"] is (want[0] is not None), name
    assert (models[0]["facts"]["need_reason"], models[0]["facts"]["pending_mail"]) == (None, 0)
    off = [i for i in sample["items"] if i["id"] == "gmail:1"][0]
    assert off["code"] == "switched_off" and off["next_check_at"] is None
    assert sample["variants"]["gmail_switched_off"]["item"]["next_check_at"] is None

# ------------------------------------------------------------------ D-195 rulings

def test_connections_d195_1_exists_no_password_is_attention_with_its_own_code():
    with _clean_env():
        body = _compose(ROWS["cases"]["employer_exists_no_password"]["inputs"])
    row = _find(body, "account:15")
    assert (row["state"], row["code"], row["status"]) == ("attention", "exists_no_password", "exists_no_password")
    assert (_find(body, "employer-accounts")["state"], _find(body, "employer-accounts")["code"]) == (
        "attention", "exists_no_password")


def test_connections_d195_2_a_failed_last_signin_stays_connected_and_raises_no_badge():
    base = ROWS["cases"]["employer_created_ok"]["inputs"]
    rows = copy.deepcopy(base["ats_accounts"])
    for status in ("created", "verified"):
        rows[0]["status"], rows[0]["last_signin_ok"] = status, 0
        with _clean_env():
            body = _compose({**copy.deepcopy(base), "ats_accounts": copy.deepcopy(rows)})
        row = _find(body, "account:11")
        assert (row["state"], row["code"]) == ("connected", "ok" if status == "created" else "verified"), row
        assert row["last_signin_ok"] is False
        assert _find(body, "employer-accounts")["state"] == "connected"
        assert body["attention"] == 0
    # null reads as ok, 1 as ok
    for v in (None, 1):
        rows[0]["status"], rows[0]["last_signin_ok"] = "created", v
        with _clean_env():
            row = _find(_compose({**copy.deepcopy(base), "ats_accounts": copy.deepcopy(rows)}), "account:11")
        assert (row["state"], row["code"]) == ("connected", "ok"), (v, row)


def test_connections_d195_3_the_employer_summary_takes_the_worst_rows_code():
    ok = ROWS["cases"]["employer_created_ok"]["inputs"]["ats_accounts"][0]
    failed = ROWS["cases"]["employer_signin_failed"]["inputs"]["ats_accounts"][0]
    nopw = ROWS["cases"]["employer_exists_no_password"]["inputs"]["ats_accounts"][0]
    unconfirmed = ROWS["cases"]["employer_creating"]["inputs"]["ats_accounts"][0]
    has = {f"{r['vault_service']}|{r['email']}": True for r in (ok, failed, nopw, unconfirmed)}
    with _clean_env():
        def summary(*rows):
            return _find(_compose({"ats_accounts": [copy.deepcopy(r) for r in rows], "vault_has": has}),
                         "employer-accounts")
        s = summary(ok, unconfirmed)
        assert (s["state"], s["code"]) == ("neutral", "unconfirmed")
        s = summary(ok, unconfirmed, failed)
        assert (s["state"], s["code"]) == ("attention", "signin_failed")
        assert s["facts"] == {"total": 3, "attention": 1}
        s = summary(ok, nopw, unconfirmed)
        assert (s["state"], s["code"]) == ("attention", "exists_no_password")
        s = summary(ok)
        assert (s["state"], s["code"]) == ("connected", "ok")
        s = summary()
        assert (s["state"], s["code"], s["facts"]) == ("not_set_up", "none", {"total": 0, "attention": 0})


def test_connections_d195_4_a_switched_off_gmail_is_paused_with_no_next_check():
    with _clean_env():
        body = _compose(ROWS["cases"]["gmail_switched_off"]["inputs"])
        row = _find(body, "gmail:1")
        assert (row["state"], row["code"]) == ("paused", "switched_off")
        assert row["next_check_at"] is None, "D-196: no check happens while it is off"
        assert row["facts"]["enabled"] is False
        assert body["attention"] == 0
        # the same row switched on, timer running: it has a next check
        ins = _case("gmail_ok_timer_running")
        on = _find(_compose(ins), "gmail:11")
        assert on["next_check_at"] == "2026-11-11T09:20:00"


def test_connections_d195_5_a_paused_gmail_with_an_unlisted_code_is_attention_with_that_codes_words():
    from jobscraper.mailstatus.contracts import SYNC_TEXTS, SyncCode
    base = copy.deepcopy(ROWS["cases"]["gmail_paused_login_refused"]["inputs"])
    with _clean_env():
        for code in (SyncCode.VAULT_ERROR, SyncCode.RULES_INVALID, SyncCode.INTERNAL, SyncCode.DB_BUSY):
            ins = copy.deepcopy(base)
            ins["mail_accounts"][0]["state_code"] = code.value
            row = _find(_compose(ins), "gmail:3")
            assert (row["state"], row["code"]) == ("attention", code.value), code
            assert row["message"] == SYNC_TEXTS[code], code


def test_connections_d195_6_no_mailbox_is_the_id_gmail_without_a_number():
    with _clean_env():
        body = _compose({})
    gm = [i for i in body["items"] if i["kind"] == "gmail"]
    assert [i["id"] for i in gm] == ["gmail"]
    assert (gm[0]["state"], gm[0]["code"], gm[0]["optional"]) == ("not_set_up", "none", True)


# ------------------------------------------------------------------ mail parity

def test_connections_every_sync_code_has_the_same_message_as_the_mail_card():
    from jobscraper.mailstatus.contracts import SyncCode
    from jobscraper.web.routers.mail import account_view
    base = copy.deepcopy(ROWS["cases"]["gmail_paused_login_refused"]["inputs"]["mail_accounts"][0])
    codes = [c.value for c in SyncCode] + ["a_code_from_the_future", None]
    with _clean_env():
        bad = []
        for code in codes:
            row = copy.deepcopy(base)
            row["state_code"] = code
            item = _find(_compose({"mail_accounts": [row]}), f"gmail:{row['id']}")
            want = account_view(row)["message"]
            if item["message"] != want:
                bad.append(f"{code}: hub {item['message']!r} != card {want!r}")
        assert not bad, "\n".join(bad)
    assert len(codes) >= 19


# ------------------------------------------------------------------ no secret in compose

def _walk(value, path="$"):
    if isinstance(value, dict):
        for k, v in value.items():
            yield f"{path}.{k}", k, v
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk(v, f"{path}[{i}]")


def test_connections_has_password_is_always_a_boolean_and_no_other_secret_key_exists():
    with _clean_env():
        bodies = [_compose(c["inputs"]) for c in ROWS["cases"].values()]
    seen = 0
    for body in bodies:
        for path, key, val in _walk(body):
            low = key.lower()
            if key == "has_password":
                seen += 1
                assert isinstance(val, bool), (path, val)
            else:
                assert not any(w in low for w in ("password", "secret", "token", "credential", "vault_service")), path
    assert seen >= 10


def test_connections_a_vault_that_holds_the_marker_never_puts_it_or_its_target_in_the_body():
    ins = _case("apply_mailbox_ok", ats_accounts=ROWS["cases"]["employer_created_ok"]["inputs"]["ats_accounts"])
    asked = []

    def vault_has(service, user):
        asked.append((service, user))
        return True
    with _clean_env():
        body = _compose(ins, vault_has=vault_has)
    text = json.dumps(body)
    assert asked, "the vault was asked yes or no"
    assert "jobscraper:" not in text and MARKER not in text and "vault_service" not in text
    assert _find(body, "apply-mailbox")["facts"]["has_password"] is True


def test_connections_a_failing_source_degrades_only_its_own_item_with_fixed_copy():
    class VaultBoom(Exception):
        pass
    leak = f"{MARKER} jobscraper:imap:imap.gmail.com owner@example.com"

    def vault_has(service, user):
        raise VaultBoom(leak)
    ins = _case("apply_mailbox_ok", ats_accounts=ROWS["cases"]["employer_created_ok"]["inputs"]["ats_accounts"])
    with _clean_env():
        body = _compose(ins, vault_has=vault_has)
        box = _find(body, "apply-mailbox")
        assert (box["state"], box["code"]) == ("neutral", "check_failed")
        assert box["message"] == "Couldn't check this just now. Try again in a moment."
        assert _find(body, "account:11")["code"] == "check_failed"
        assert _find(body, "edge")["state"] in ("not_set_up", "connected")      # untouched
        mail = _compose({}, store=FakeStore(mail_error=RuntimeError(leak)))
        assert (_find(mail, "gmail")["state"], _find(mail, "gmail")["code"]) == ("neutral", "check_failed")
        acc = _compose({}, store=FakeStore(accounts_error=RuntimeError(leak)))
        assert _find(acc, "employer-accounts")["code"] == "check_failed"
        assert _find(acc, "model")["code"] in ("probing", "ok", "unreachable", "ai_off")
    for b in (body, mail, acc):
        assert leak not in json.dumps(b) and MARKER not in json.dumps(b) and "jobscraper:" not in json.dumps(b)


def test_connections_the_edge_profile_path_is_read_but_never_sent():
    tmp = tmpdir("conn_edge_")
    with _clean_env():
        ins = _case("edge_ok")
        c = _effective(ins)["cfg"]
        c["apply_profile_dir"] = str(tmp)           # a path with the Windows user name in it
        body = _compose(ins, cfg=_config(c))
    text = json.dumps(body)
    assert _find(body, "edge")["facts"] == {"exists": True, "in_use": False, "sync": False, "last_used_at": None}
    assert str(tmp) not in text and str(tmp).replace("\\", "\\\\") not in text and "apply-profile" not in text


# ------------------------------------------------------------------ the web layer

class MailSpy:
    """A `MailCommand` that fails the test if anything ever asks for a child."""

    def __init__(self):
        self.calls = []

    def __call__(self, kind, opts):
        self.calls.append((kind, dict(opts)))
        raise AssertionError(f"GET /api/connections must not start a mail child ({kind})")


class ProbeStub:
    """Stands in for backends.probe: counts calls, optionally blocks until released."""

    def __init__(self, ok=True, code="", block=False):
        self.ok, self.code, self.block = ok, code, block
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, budget):
        from jobscraper.backends import Probe
        with self._lock:
            self.calls += 1
        self.started.set()
        if self.block:
            self.release.wait(10)
        return Probe(ok=self.ok, code=self.code, backend="ollama", model="example-model:8b", local=True)


def _wait_until(fn, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.01)
    return False


@contextlib.contextmanager
def _web(probe=None, *, budget=None, seed_rows=True, store_factory=None):
    """(client, cfg, mem, spy, probe, tmp): a real temp DB with a mailbox, an employer account
    and an application mailbox whose passwords are the MARKER in the in-memory keyring."""
    from fastapi.testclient import TestClient
    from jobscraper.config import Config
    from jobscraper.store import Store
    from jobscraper.web.api import create_app
    from jobscraper.web.connections import ModelHealth
    from jobscraper import vault
    tmp = tmpdir("conn_web_")
    profile = tmp / "edge-profile"
    profile.mkdir()
    raw = {"paths": {"db": str(tmp / "t.db"), "shortlist": str(tmp / "none.json"),
                     "applicant": str(tmp / "none.yaml")},
           "web": {"host": "127.0.0.1", "port": 8768},
           "budget": budget or {"enable_llm": True, "backend": "ollama", "ollama_model": "example-model:8b",
                                "ollama_url": OLLAMA_URL},
           "apply": {"profile_dir": str(profile),
                     "mail": {"host": "imap.gmail.com", "port": 993, "username": "apply.owner@example.com"}}}
    cfg = Config(raw)
    probe = probe or ProbeStub()
    spy = MailSpy()
    with _clean_env(), memory_keyring() as mem:
        if seed_rows:
            st = Store(cfg.db_path)
            from jobscraper.mailstatus.contracts import CONSENT_VERSION
            st.mail_account_add("owner@example.com", vault_service="jobscraper:imap:imap.gmail.com",
                                consent_version=CONSENT_VERSION, first_sync_from="2026-10-01T00:00:00",
                                now="2026-11-01T00:00:00")
            st.upsert_account("workday", "acme.wd3.myworkdayjobs.com", "owner+1@example.com",
                              "jobscraper:workday:acme.wd3.myworkdayjobs.com", "created")
            st.close()
            for service, user in (("jobscraper:imap:imap.gmail.com", "owner@example.com"),
                                  (vault.imap_service("imap.gmail.com"), "apply.owner@example.com"),
                                  ("jobscraper:workday:acme.wd3.myworkdayjobs.com", "owner+1@example.com")):
                mem.d[(service, user)] = MARKER
        app = create_app(cfg, static_dir=tmp / "no_static", mail_command=spy, mail_timer=False,
                         **({"store_factory": store_factory} if store_factory else {}))
        app.state.model_health = ModelHealth(lambda: cfg.budget, probe=probe)
        try:
            with TestClient(app, base_url="http://localhost") as client:
                yield SimpleNamespace(client=client, cfg=cfg, mem=mem, spy=spy, probe=probe, tmp=tmp, app=app)
        finally:
            probe.release.set()
            t = app.state.model_health._thread
            if t is not None:
                t.join(5)


def test_connections_get_returns_the_hub_without_any_secret_path_or_url():
    with _web() as w:
        r = w.client.get("/api/connections")
        assert r.status_code == 200, r.text
        assert r.headers["cache-control"] == "no-store"
        body = r.json()
        assert body["version"] == 1
        kinds = [i["kind"] for i in body["items"]]
        assert kinds == ["gmail", "apply_mailbox", "apply_mailbox", "edge", "model", "employer_accounts"], kinds
        box = [i for i in body["items"] if i["id"] == "apply-mailbox"][0]
        assert (box["state"], box["code"], box["facts"]["has_password"]) == ("connected", "ok", True)
        assert [a["state"] for a in body["employer_accounts"]] == ["connected"]
        assert body["employer_accounts"][0]["has_password"] is True
        assert [i for i in body["items"] if i["kind"] == "edge"][0]["code"] == "ok"
        assert any(c[0] == "get" for c in w.mem.calls), "the vault was asked"
        assert not any(c[0] in ("set", "delete") for c in w.mem.calls), "and only read"
        text = r.text
        home = str(Path.home())
        for needle in (MARKER, "jobscraper:", "11434", "ollama-host.test", home, home.replace("\\", "\\\\"),
                       home.replace("\\", "/"), str(w.tmp), str(w.tmp).replace("\\", "\\\\"), "Traceback"):
            assert needle not in text, needle
        for path, key, val in _walk(body):
            if key == "has_password":
                assert isinstance(val, bool), path


def test_connections_no_api_get_ever_returns_the_marker_a_vault_target_the_model_url_or_the_user_dir():
    with _web() as w:
        paths = sorted(p for p, ops in w.app.openapi()["paths"].items()
                       if "get" in ops and "{" not in p and p.startswith("/api"))
        assert "/api/connections" in paths and len(paths) >= 8, paths
        home = str(Path.home())
        needles = (MARKER, "jobscraper:imap", "jobscraper:workday", "ollama-host.test", "11434",
                   home, home.replace("\\", "\\\\"), home.replace("\\", "/"))
        for p in paths:
            r = w.client.get(p)
            for n in needles:
                assert n not in r.text, (p, n, r.status_code)
        assert not any(c[0] in ("set", "delete") for c in w.mem.calls)
        assert w.spy.calls == []


def test_connections_get_never_reads_a_mailbox_or_starts_a_sync():
    import imaplib
    real = (imaplib.IMAP4, imaplib.IMAP4_SSL)

    def boom(*a, **k):
        raise AssertionError("GET /api/connections opened an IMAP connection")
    imaplib.IMAP4 = imaplib.IMAP4_SSL = boom
    try:
        with _web() as w:
            for _ in range(3):
                assert w.client.get("/api/connections").status_code == 200
            assert w.spy.calls == [], "no sync / connect child was asked for"
            assert w.app.state.mail.status()["running"] is False
            st = w.client.get("/api/connections").json()
            assert st["items"][0]["facts"]["counts"] == {}
    finally:
        imaplib.IMAP4, imaplib.IMAP4_SSL = real


def test_connections_the_model_check_is_a_202_and_a_foreign_origin_is_refused():
    with _web() as w:
        r = w.client.post("/api/connections/model/check")
        assert r.status_code == 202, r.text
        assert set(r.json()) == {"checking"} and isinstance(r.json()["checking"], bool)
        assert _wait_until(lambda: w.probe.calls >= 1)
        assert _wait_until(lambda: not w.app.state.model_health.in_flight)
        before = w.probe.calls
        r = w.client.post("/api/connections/model/check", headers=EVIL)
        assert r.status_code == 403, r.text
        time.sleep(0.05)
        assert w.probe.calls == before, "a refused request starts nothing"
        # GET is not guarded by Origin (reads), and POST is the only verb here
        assert w.client.get("/api/connections", headers=EVIL).status_code == 200
        assert w.client.put("/api/connections/model/check").status_code in (404, 405)


def test_connections_get_does_not_wait_for_a_slow_probe_and_shows_checking():
    probe = ProbeStub(block=True)
    with _web(probe) as w:
        t0 = time.time()
        r = w.client.get("/api/connections")
        elapsed = time.time() - t0
        assert r.status_code == 200 and elapsed < 0.5, elapsed
        model = [i for i in r.json()["items"] if i["id"] == "model"][0]
        assert (model["state"], model["code"]) == ("checking", "probing"), model
        assert probe.started.wait(2), "the probe runs in the background"
        t0 = time.time()
        r = w.client.get("/api/connections")      # still blocked: still answers at once
        assert time.time() - t0 < 0.5
        assert [i for i in r.json()["items"] if i["id"] == "model"][0]["state"] == "checking"
        probe.release.set()
        assert _wait_until(lambda: not w.app.state.model_health.in_flight)
        model = [i for i in w.client.get("/api/connections").json()["items"] if i["id"] == "model"][0]
        assert (model["state"], model["code"]) == ("connected", "ok"), model
        assert probe.calls == 1


def test_connections_at_most_one_probe_runs_at_a_time():
    probe = ProbeStub(block=True)
    with _web(probe) as w:
        mh = w.app.state.model_health
        barrier = threading.Barrier(12)
        errors = []

        def hit(i):
            try:
                barrier.wait(5)
                if i % 3 == 0:
                    w.client.post("/api/connections/model/check")
                else:
                    mh.snapshot()
            except Exception as exc:                         # noqa: BLE001
                errors.append(exc)
        threads = [threading.Thread(target=hit, args=(i,)) for i in range(12)]
        [t.start() for t in threads]
        [t.join(10) for t in threads]
        assert not errors, errors
        assert probe.started.wait(2)
        time.sleep(0.1)
        assert probe.calls == 1, probe.calls
        live = [t for t in threading.enumerate() if t.name == "model-health-probe" and t.is_alive()]
        assert len(live) == 1, live
        assert mh.in_flight is True
        mh.snapshot(force=True)
        assert probe.calls == 1, "force does not stack a second probe on a running one"
        probe.release.set()
        assert _wait_until(lambda: not mh.in_flight)
        mh.snapshot(force=True)                              # now it may start another
        assert _wait_until(lambda: probe.calls == 2)


def test_connections_the_probe_is_cached_for_a_minute_after_success_and_15_seconds_after_failure():
    from jobscraper.web.connections import ModelHealth
    now = [1_000.0]
    budget = {"enable_llm": True, "backend": "ollama", "ollama_model": "m"}
    with _clean_env():
        for ok, ttl in ((True, 60), (False, 15)):
            probe = ProbeStub(ok=ok, code="" if ok else "unreachable")
            mh = ModelHealth(lambda: budget, probe=probe, clock=lambda: now[0])
            assert mh.snapshot() is None, "no answer yet: the first call starts the probe"
            assert _wait_until(lambda: not mh.in_flight) and probe.calls == 1
            now[0] += ttl - 1
            first = mh.snapshot()
            assert first["ok"] is ok and probe.calls == 1, "still fresh"
            now[0] += 2
            mh.snapshot()
            assert _wait_until(lambda: probe.calls == 2), f"stale after {ttl} s"
            assert _wait_until(lambda: not mh.in_flight)


def test_connections_a_probe_that_raises_reads_unreachable_and_clears_in_flight():
    from jobscraper.web.connections import ModelHealth

    def boom(budget):
        raise RuntimeError(f"{MARKER} {OLLAMA_URL}")
    with _clean_env():
        mh = ModelHealth(lambda: {"enable_llm": True, "backend": "ollama", "ollama_model": "m"}, probe=boom)
        mh.snapshot()
        assert _wait_until(lambda: not mh.in_flight)
        snap = mh.snapshot()
    assert snap["ok"] is False and snap["code"] == "unreachable"
    assert MARKER not in json.dumps(snap) and "11434" not in json.dumps(snap)


def test_connections_off_and_misconfigured_come_from_config_and_are_never_probed():
    for budget, state, code in (({"enable_llm": False, "backend": "ollama"}, "paused", "ai_off"),
                                ({"enable_llm": True, "backend": "off"}, "paused", "ai_off"),
                                ({"enable_llm": True, "backend": "mystery"}, "attention", "misconfigured")):
        probe = ProbeStub()
        with _web(probe, budget=budget) as w:
            model = [i for i in w.client.get("/api/connections").json()["items"] if i["id"] == "model"][0]
            assert (model["state"], model["code"]) == (state, code), (budget, model)
            assert w.client.post("/api/connections/model/check").status_code == 202
            time.sleep(0.05)
            assert probe.calls == 0, budget


def test_connections_an_unreachable_model_is_neutral_until_a_job_waits_on_it():
    probe = ProbeStub(ok=False, code="unreachable")
    with _web(probe) as w:
        w.client.get("/api/connections")
        assert _wait_until(lambda: not w.app.state.model_health.in_flight)
        m = [i for i in w.client.get("/api/connections").json()["items"] if i["id"] == "model"][0]
        assert (m["state"], m["code"], m["facts"]["need_now"], m["facts"]["need_reason"]) == (
            "neutral", "unreachable", False, None)
        assert "11434" not in json.dumps(m) and "ollama-host" not in json.dumps(m)


def test_connections_a_database_that_cannot_open_is_a_503_with_a_code_only():
    def broken():
        raise RuntimeError(f"cannot open {MARKER}")
    with _web(store_factory=broken, seed_rows=False) as w:
        r = w.client.get("/api/connections")
        assert r.status_code == 503 and r.json() == {"code": "unavailable"}
        assert MARKER not in r.text
