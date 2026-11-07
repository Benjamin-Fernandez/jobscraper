"""WP-T6 oracles: `jobscraper mail sync` and `mail accounts ...` (mail_status_design.md 10.3, 4, 13).
Verify: `python tests/run_tests.py -k cli_mail`.

The CLI runs in process (`cli.main(argv)`) on a written temp config.yaml, the FakeMailServer
behind the real ImapTransport, and the in-memory keyring. `model: false` keeps the local model
out of it. No network, no real keyring entry.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_support import GMAIL_LOGIN_ERRORS, WAITING, FakeMailServer, assert_live, needs, note_waiting  # noqa: E402
from mail_flow_support import (  # noqa: E402
    ADDRESS, PASSWORD, config, golden_mail, memory_keyring, rows, seed, tmpdir,
)

_W0 = len(WAITING)
CLI = "jobscraper.cli:cmd_mail_status"
REFUSED = next(k for k, v in GMAIL_LOGIN_ERRORS.items() if v == "login_refused")
SERVICE = "jobscraper:imap:imap.gmail.com"


def _consent():
    from jobscraper.mailstatus.contracts import CONSENT_VERSION
    return CONSENT_VERSION


@contextlib.contextmanager
def _cli(mail_status=None):
    """Yields (call, mem, srv, cfg); call(argv, stdin="") -> (exit, stdout, stderr)."""
    from jobscraper import cli, imapread
    from jobscraper.store import Store
    with memory_keyring() as mem:
        cfg, path = config(tmpdir("cli_mail_"), {"model": False, **(mail_status or {})}, write=True)
        st = Store(cfg.db_path)
        seed(st)
        st.close()
        srv = FakeMailServer()

        def call(argv, stdin=""):
            out, err = io.StringIO(), io.StringIO()
            saved = sys.stdin
            sys.stdin = io.StringIO(stdin)
            try:
                with srv.patched(imapread), contextlib.redirect_stdout(out), \
                        contextlib.redirect_stderr(err):
                    code = cli.main(["--config", str(path), *argv])
            finally:
                sys.stdin = saved
            return code, out.getvalue(), err.getvalue()
        yield call, mem, srv, cfg


def _add(call, stdin=PASSWORD + "\n", *extra):
    return call(["mail", "accounts", "add", "--address", ADDRESS, "--password-stdin",
                 "--consent", _consent(), "--json", *extra], stdin)


def _db(cfg, sql, *args):
    from jobscraper.store import Store
    st = Store(cfg.db_path)
    try:
        return rows(st, sql, *args)
    finally:
        st.close()


@needs(CLI)
def test_cli_mail_add_json_prints_one_line_and_stores_nothing_on_a_refused_login():
    with _cli() as (call, mem, srv, cfg):
        srv.login_error = REFUSED
        code, out, err = _add(call)
        assert code == 1 and out.splitlines() == [json.dumps({"result": "login_refused"})], out
        assert mem.d == {} and not [c for c in mem.calls if c[0] == "set"]
        assert _db(cfg, "SELECT COUNT(*) FROM mail_accounts") == [(0,)]
        for text in (out, err):
            assert "CANARYpw" not in text and ADDRESS not in text


@needs(CLI)
def test_cli_mail_add_ok_then_exists_and_reads_exactly_one_stdin_line():
    with _cli() as (call, mem, srv, cfg):
        saved_in = io.StringIO(PASSWORD + "\nnext line stays\n")
        from jobscraper import cli, imapread
        out = io.StringIO()
        old = sys.stdin
        sys.stdin = saved_in
        try:
            with srv.patched(imapread), contextlib.redirect_stdout(out):
                code = cli.main(["--config", str(Path(cfg.db_path).parent / "config.yaml"),
                                 "mail", "accounts", "add", "--address", ADDRESS,
                                 "--password-stdin", "--consent", _consent(), "--json"])
        finally:
            sys.stdin = old
        assert code == 0 and json.loads(out.getvalue()) == {"result": "ok", "account_id": 1}
        assert len(out.getvalue().strip().splitlines()) == 1
        assert saved_in.read() == "next line stays\n", "--password-stdin reads one line only"
        assert mem.d[(SERVICE, ADDRESS)] == PASSWORD.replace(" ", ""), "spaces dropped"
        code, out, _ = _add(call)
        assert code == 1 and json.loads(out)["result"] == "exists", out
        assert json.loads(out).get("account_id") in (None, 1)
        assert _db(cfg, "SELECT COUNT(*) FROM mail_accounts") == [(1,)]


@needs(CLI)
def test_cli_mail_add_needs_the_current_consent_and_a_sane_address():
    with _cli() as (call, mem, srv, cfg):
        code, out, _ = call(["mail", "accounts", "add", "--address", ADDRESS, "--password-stdin",
                             "--json"], PASSWORD + "\n")
        assert code == 1 and json.loads(out) == {"result": "bad_input"}
        code, out, _ = call(["mail", "accounts", "add", "--address", ADDRESS, "--password-stdin",
                             "--consent", "v0-old", "--json"], PASSWORD + "\n")
        assert code == 1 and json.loads(out) == {"result": "bad_input"}
        code, out, _ = call(["mail", "accounts", "add", "--address", "not an address",
                             "--password-stdin", "--consent", _consent(), "--json"], PASSWORD + "\n")
        assert code == 1 and json.loads(out) == {"result": "bad_input"}, out
        assert srv.commands("LOGIN") == [] and mem.d == {}


@needs(CLI)
def test_cli_mail_sync_prints_ids_and_counts_only():
    with _cli() as (call, mem, srv, cfg):
        assert _add(call)[0] == 0
        golden_mail(srv)
        code, out, err = call(["mail", "sync"])
        assert code == 0, (out, err)
        lines = out.strip().splitlines()
        assert len(lines) == 1 and lines[0].startswith("account 1: ") and lines[0].endswith("(ok)"), lines
        assert "2 updated" in lines[0]
        assert ADDRESS not in out + err and "Northwind" not in out + err and "@" not in out
        assert _db(cfg, "SELECT trigger FROM mail_sync_runs") == [("cli",)]
        code, out, _ = call(["mail", "sync"])
        assert code == 0 and "0 scanned" in out


@needs(CLI)
def test_cli_mail_sync_disabled_and_nothing_due():
    with _cli({"enabled": False}) as (call, mem, srv, cfg):
        code, out, err = call(["mail", "sync"])
        assert code == 1 and out == "" and err.startswith("mail sync: "), (out, err)
    with _cli() as (call, mem, srv, cfg):
        code, out, err = call(["mail", "sync", "--trigger", "timer"])
        assert code == 0 and out.startswith("mail sync: no mailbox"), (code, out, err)


@needs(CLI)
def test_cli_mail_set_password_on_off_and_remove():
    with _cli() as (call, mem, srv, cfg):
        assert _add(call)[0] == 0
        code, out, _ = call(["mail", "accounts", "set-password", "--id", "9", "--password-stdin",
                             "--json"], "x\n")
        assert code == 1 and json.loads(out) == {"result": "not_found"}
        srv.login_error = REFUSED
        code, out, _ = call(["mail", "accounts", "set-password", "--id", "1", "--password-stdin",
                             "--json"], "newCANARYpw2\n")
        assert code == 1 and json.loads(out)["result"] == "login_refused"
        assert mem.d[(SERVICE, ADDRESS)] == PASSWORD.replace(" ", ""), "a refused password isn't kept"
        srv.login_error = None
        code, out, _ = call(["mail", "accounts", "set-password", "--id", "1", "--password-stdin",
                             "--json"], "newCANARYpw2\n")
        assert code == 0 and json.loads(out) == {"result": "ok", "account_id": 1}
        assert mem.d[(SERVICE, ADDRESS)] == "newCANARYpw2"
        assert call(["mail", "accounts", "off", "--id", "1"])[0] == 0
        assert _db(cfg, "SELECT enabled FROM mail_accounts") == [(0,)]
        code, out, _ = call(["mail", "accounts", "list"])
        assert code == 0 and " off " in out and "CANARYpw" not in out and "newCANARY" not in out
        code, out, _ = call(["mail", "accounts", "remove", "--id", "1"])
        assert code == 0 and "disconnected" in out and "stays" not in out
        assert mem.d == {} and _db(cfg, "SELECT COUNT(*) FROM mail_accounts") == [(0,)]


def test_cli_mail_oracles_are_live():
    assert_live(CLI, _W0, "test_cli_mail")


note_waiting("test_cli_mail", _W0)
