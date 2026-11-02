"""`jobscraper accounts list|add|export-edge` (Q-35 WP-T4, lane N WP-N1; apply_design §10.3,
§10.4, §14.1; F-35; NF-02; review Q-35-lanes-NR F8).

  - list: "no accounts yet" on an empty DB; rows show tenant, email and status, never a password;
  - add: a URL that is no ATS needing an account -> exit 2 and nothing stored; a bad email -> 2;
    an empty password -> 1 and nothing stored; otherwise the password goes to the vault under
    the canonical tenant service (forms A and B share it), the row is `created` (a `verified`
    row stays verified, a `signin_failed` row becomes `created`), and the password is never
    printed;
  - export-edge: writes the CSV in the DB's folder; `--confirm` deletes it and stamps its rows;
    nothing left -> "nothing to export" exit 0; `--confirm` with no file -> exit 1;
  - F8 (failing pin until lane N's fix): `--confirm` marks only the rows the export held, not
    an account created after the export.
The vault runs on an in-memory keyring backend (the real Credential Manager is never touched:
each test checks the swap took before any call). Temp DB and folders only.
Verify: python tests/run_tests.py -k accounts_cli
"""
from __future__ import annotations

import contextlib
import getpass
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

_W0 = len(WAITING)
NEEDS = ("jobscraper.cli:cmd_accounts", "jobscraper.apply.ats.workday:NAVIGATOR", "keyring")

EMAIL = "alex.testcase@example.com"
HOST = "exampleco.wd3.myworkdayjobs.com"
SERVICE = f"jobscraper:workday:{HOST}"
A_URL = "https://exampleco.wd3.myworkdayjobs.com/en-US/External/job/Singapore/Graduate-Engineer_REQ-0001"
B_URL = "https://wd3.myworkdaysite.com/recruiting/exampleco/External/job/Singapore/Graduate-Engineer_REQ-0001"
PW = "Synthetic-Passw0rd-not-real!"


def test_the_cli_module_imports():
    from jobscraper import cli
    assert hasattr(cli, "main")


@contextlib.contextmanager
def _world(password: str = PW):
    """(world, run, memory keyring). `run(*argv)` -> (code, stdout, stderr)."""
    import keyring
    from keyring.backend import KeyringBackend
    from keyring.errors import PasswordDeleteError
    from apply_flow_support import make_world
    from jobscraper import cli

    class Memory(KeyringBackend):
        priority = 1

        def __init__(self):
            super().__init__()
            self.d: dict[tuple[str, str], str] = {}

        def get_password(self, service, username):
            return self.d.get((service, username))

        def set_password(self, service, username, pw):
            self.d[(service, username)] = pw

        def delete_password(self, service, username):
            if (service, username) not in self.d:
                raise PasswordDeleteError("none")
            del self.d[(service, username)]

    saved_kr, saved_gp = keyring.get_keyring(), getpass.getpass
    mem = Memory()
    keyring.set_keyring(mem)
    assert keyring.get_keyring() is mem, "refusing to run against the real Credential Manager"
    getpass.getpass = lambda prompt="": password
    w = make_world()

    def run(*argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--config", str(w.cfg_path), *argv])
        return code, out.getvalue(), err.getvalue()
    try:
        yield w, run, mem
    finally:
        getpass.getpass = saved_gp
        keyring.set_keyring(saved_kr)
        w.close()


def _status(w, email=EMAIL):
    w.store.conn.commit()
    row = w.store.account("workday", HOST, email)
    return row and row["status"]


@needs(*NEEDS)
def test_list_on_an_empty_database():
    with _world() as (w, run, mem):
        code, out, _ = run("accounts", "list")
        assert code == 0 and "no accounts yet" in out


@needs(*NEEDS)
def test_add_refuses_a_url_that_needs_no_account_a_bad_email_and_an_empty_password():
    with _world() as (w, run, mem):
        code, _, err = run("accounts", "add", "--url", "https://job-boards.greenhouse.io/exampleco/jobs/1",
                           "--email", EMAIL)
        assert code == 2 and "not the URL of an ATS that needs an account" in err
        code, _, err = run("accounts", "add", "--url", A_URL, "--email", "not-an-email")
        assert code == 2 and "--email" in err
        assert mem.d == {} and w.store.accounts() == []
    with _world(password="") as (w, run, mem):
        code, _, err = run("accounts", "add", "--url", A_URL, "--email", EMAIL)
        assert code == 1 and "nothing stored" in err
        assert mem.d == {} and w.store.accounts() == []


@needs(*NEEDS)
def test_add_stores_the_password_under_the_canonical_tenant_and_never_prints_it():
    with _world() as (w, run, mem):
        code, out, err = run("accounts", "add", "--url", B_URL, "--email", EMAIL)     # form B
        assert code == 0, err
        assert mem.d == {(SERVICE, EMAIL): PW}
        assert _status(w) == "created"
        code, out2, _ = run("accounts", "list")
        assert code == 0 and HOST in out2 and EMAIL in out2 and "created" in out2
        for text in (out, err, out2):
            assert PW not in text
        w.store.set_account_status(w.store.account("workday", HOST, EMAIL)["id"], "verified")
        assert run("accounts", "add", "--url", A_URL, "--email", EMAIL)[0] == 0      # form A, same tenant
        assert _status(w) == "verified", "a verified row stays verified"
        assert len(w.store.accounts()) == 1 and len(mem.d) == 1
        w.store.set_account_status(w.store.account("workday", HOST, EMAIL)["id"], "signin_failed")
        assert run("accounts", "add", "--url", A_URL, "--email", EMAIL)[0] == 0
        assert _status(w) == "created", "a new password clears signin_failed"


@needs(*NEEDS)
def test_export_edge_then_confirm_then_nothing_left():
    with _world() as (w, run, mem):
        assert run("accounts", "export-edge", "--confirm")[0] == 1, "no export file yet"
        run("accounts", "add", "--url", A_URL, "--email", EMAIL)
        data = w.cfg.db_path.parent
        code, out, _ = run("accounts", "export-edge")
        assert code == 0 and PW not in out
        files = list(data.glob("edge_passwords_*.csv"))
        assert len(files) == 1 and files[0].parent == data
        code, out, _ = run("accounts", "export-edge", "--confirm")
        assert code == 0 and "1 account(s) marked" in out
        assert list(data.glob("edge_passwords_*.csv")) == []
        assert w.store.account("workday", HOST, EMAIL)["exported_to_edge_at"]
        code, out, _ = run("accounts", "export-edge")
        assert code == 0 and "nothing to export" in out


@needs(*NEEDS)
def test_confirm_marks_only_the_accounts_the_export_held():
    """Review Q-35-lanes-NR F8 (MEDIUM; failing pin until lane N's fix): an account created
    between `export-edge` and `--confirm` was never in the CSV, so it must stay unexported."""
    from jobscraper import vault
    from jobscraper.apply.contracts import Secret
    with _world() as (w, run, mem):
        run("accounts", "add", "--url", A_URL, "--email", EMAIL)
        assert run("accounts", "export-edge")[0] == 0
        late = "alex.backup@example.net"
        vault.put(SERVICE, late, Secret("Another-Synthetic-1!"))
        w.store.upsert_account("workday", HOST, late, SERVICE, "created")
        assert run("accounts", "export-edge", "--confirm")[0] == 0
        assert w.store.account("workday", HOST, EMAIL)["exported_to_edge_at"]
        assert w.store.account("workday", HOST, late)["exported_to_edge_at"] is None, \
            "F8: --confirm marked an account the export never held"


if WAITING[_W0:]:
    print(f"[test_accounts_cli] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
