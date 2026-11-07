"""Helpers for the F-50 store, flow, CLI and web oracles (WP-T5, WP-T6; not a test file).

A temp config + DB seeded with two Northwind applications (the golden set's nw-dataeng
`to_apply` and nw-analyst `interviewing`), a fake backend, a log capture, and the in-memory
keyring from vault_support. Never a real mailbox, keyring entry or the live DB.
"""
from __future__ import annotations

import contextlib
import io
import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Optional

import yaml

from mail_support import ROOT, eml, make_eml
from vault_support import memory_keyring  # noqa: F401  (re-exported)

NOW = "2026-11-02T12:00:00"
ADDRESS = "alex.applicant@inbox.example"
PASSWORD = "CANARYpw abcd efgh"                  # stored without spaces
CANARY = "CANARYsubj42"
NW_NEWS = ("Northwind Traders Hiring <no-reply@us.greenhouse-mail.io>",
           "An update on your application",
           "Hi Alex, there is news about your application to Northwind Traders. "
           "Please read the update carefully when you can.")


def config(tmp: Path, mail_status: Optional[dict] = None, *, rules: Optional[Path] = None,
           write: bool = False):
    """A Config on a temp DB; `write=True` also writes config.yaml (for the CLI) and
    returns (cfg, path)."""
    from jobscraper.config import Config
    raw = {"paths": {"db": str(tmp / "t.db"), "shortlist": str(tmp / "none.json"),
                     "mail_rules": str(rules or ROOT / "config" / "mail_rules.yaml"),
                     "applicant": str(tmp / "none.yaml")},
           "web": {"host": "127.0.0.1", "port": 8768}}
    if mail_status is not None:
        raw["mail_status"] = mail_status
    cfg = Config(raw)
    if not write:
        return cfg
    path = tmp / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return cfg, path


def tmpdir(prefix: str = "mailt_") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def seed(st, *, at: str = "2026-09-15T09:00:00") -> None:
    """Northwind with two applications on Greenhouse (careers on boards.greenhouse.io)."""
    c = st.conn
    c.execute("INSERT INTO companies (key, name, careers_url, provider, slug) VALUES "
              "('northwind', 'Northwind Traders Pte Ltd', 'https://boards.greenhouse.io/northwind', "
              "'greenhouse', 'northwind')")
    cid = c.execute("SELECT id FROM companies WHERE key='northwind'").fetchone()[0]
    for jid, title, n in (("nw-dataeng", "Graduate Data Engineer", 1111),
                          ("nw-analyst", "Graduate Analyst", 2222)):
        c.execute("INSERT INTO jobs (job_id, company_id, title, url) VALUES (?,?,?,?)",
                  (jid, cid, title, f"https://boards.greenhouse.io/northwind/jobs/{n}"))
    c.commit()
    st.set_application_status("nw-dataeng", "to_apply", company="Northwind Traders Pte Ltd",
                              role="Graduate Data Engineer")
    st.set_application_status("nw-analyst", "interviewing", company="Northwind Traders Pte Ltd",
                              role="Graduate Analyst")
    c.execute("UPDATE app_events SET at = ?", (at,))
    c.commit()


def statuses(st) -> dict[str, str]:
    return {r["job_id"]: r["status"] for r in st.applications()}


def golden_mail(srv) -> None:
    """The acknowledgement (nw-dataeng -> applied) and the rejection (nw-analyst)."""
    srv.deliver(eml("ack_gh_saved_role.eml"), gm_msgid="1800000000000001001",
                gm_thrid="1800000000000001001")
    srv.deliver(eml("rej_not_move_forward.eml"), gm_msgid="1800000000000001019",
                gm_thrid="1800000000000001019")


def news(srv, gm_msgid: str, *, subject: str = NW_NEWS[1], body: str = NW_NEWS[2],
         date: str = "Mon, 26 Oct 2026 09:00:00 +0000", to=("inbox", "all")) -> str:
    srv.deliver(make_eml(NW_NEWS[0], subject, body, date=date), gm_msgid=gm_msgid, to=to)
    return gm_msgid


class FakeBackend:
    """`backends` stand-in: `available`, `model_id`, `complete(system, user, **kw)`."""
    model_id = "fake-model"

    def __init__(self, reply: Any = None, *, fail: bool = False, available: bool = True):
        self.reply = reply or {"category": "unknown", "quote": ""}
        self.fail, self.available, self.calls = fail, available, []

    def complete(self, system, user, **kw):
        self.calls.append({"system": system, "user": user, **kw})
        if self.fail:
            raise RuntimeError("backend down: echo of " + user[:40])

        class R:
            text = json.dumps(self.reply)
        return R()


@contextlib.contextmanager
def captured_logs():
    """Every log record at DEBUG and up, as text."""
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setLevel(logging.DEBUG)
    h.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    old = root.level
    root.addHandler(h)
    root.setLevel(logging.DEBUG)
    try:
        yield buf
    finally:
        root.removeHandler(h)
        root.setLevel(old)


def connect(cfg, srv, *, now: str = NOW, address: str = ADDRESS, password: str = PASSWORD):
    """Connect the account through the flow (the login test runs against `srv`)."""
    from jobscraper import imapread, mailstatus_flow as flow
    from jobscraper.apply.contracts import Secret
    from jobscraper.mailstatus.contracts import CONSENT_VERSION
    with srv.patched(imapread):
        return flow.connect(cfg, address=address, password=Secret(password),
                            consent_version=CONSENT_VERSION, now=now)


def run(cfg, srv, *, trigger: str = "timer", now: str = NOW, **kw):
    from jobscraper import imapread, mailstatus_flow as flow
    with srv.patched(imapread):
        return flow.sync(cfg, trigger=trigger, now=now, **kw)


def rows(st, sql: str, *args) -> list[tuple]:
    return [tuple(r) for r in st.conn.execute(sql, args).fetchall()]
