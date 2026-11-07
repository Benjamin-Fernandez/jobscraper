"""The module boundaries from PRD section 8.2, enforced instead of hoped for.

A layered design decays quietly. Someone needs one value from another stage,
adds an import, and three days later the stages cannot be tested apart any more.
This test reads every module's imports with `ast` - no importing, no executing -
and fails the moment a boundary is crossed.

The rules, in the order they matter:

  1. store.py imports no stage module. It is the bottom of the stack; if data
     access reaches upwards, nothing above it can be tested in isolation.
  2. Stage modules do not import each other. pipeline.py composes them. This is
     what lets the order change without editing the stages.
  3. web/ imports no stage module. The web app reads what the pipeline already
     decided; it never re-runs a decision.
  4. Only store.py contains SQL. That single fact is what makes the Postgres
     path in PRD section 8.4 one module's work instead of a search-and-replace.
  5. backends.py is the only module that talks to a model.
  6. Nothing imports pipeline.py. It is the top of the stack; an import of it
     from below is a cycle waiting to happen.
  7. Foundation modules (applicant.py, vault.py, ...) import no stage, publisher
     or orchestrator - except the contracts modules (apply.contracts,
     tailor.contracts, mailstatus.contracts), the stdlib-only data shapes web/
     may import too (D-73).
  8. F-50 (mail_status_design.md 2.2): imapread.py is the foundation module that
     speaks IMAP, and web/ may not import it; mailstatus/ is a stage package that
     imports only itself; mailstatus_flow.py is its orchestrator. No module that
     touches the mailbox may contain a write command (STORE, COPY, MOVE, EXPUNGE,
     APPEND, a non-read-only SELECT, smtplib).

Every module in the package is checked. v1's modules retired at M9-T1, so the
only exemptions left in LEGACY are the CLI entry points.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jobscraper"
sys.path.insert(0, str(ROOT / "src"))

# The orchestrator. The one module allowed to import every stage - composing them
# is its whole job. Nothing may import it back.
ORCHESTRATOR = {"pipeline", "company_search", "apply_flow", "tailor_flow",
                "mailstatus_flow"}
# company_search.py (M16) composes discovery, the adapters and the model to find
# careers sites for the user's own list - an orchestrator for the same reason.
# apply_flow.py / tailor_flow.py (M20, apply_design.md 2.3) compose the apply and
# tailor stages. The one orchestrator->orchestrator edge allowed: apply_flow may
# import tailor_flow (auto-apply tailors first, D-58). mailstatus_flow.py (F-50,
# mail_status_design.md 2.2 rule 3) composes the mailstatus stage, imapread, the
# vault, the store and backends; it adds no edge.
ORCHESTRATOR_EDGES = {("apply_flow", "tailor_flow")}

# Stage modules: each does one step of the pipeline and knows nothing of the others.
STAGES = {"scheduler", "filter", "decide", "scrape", "profile", "apply", "tailor",
          "mailstatus"}

# The stage packages' `contracts` modules are shared data shapes (standard library
# only). web/ may import exactly these and nothing else from the packages, so
# `_local_imports` reports names inside them dotted ("apply.contracts").
CONTRACTS = {"apply.contracts", "tailor.contracts", "mailstatus.contracts"}
DOTTED_PACKAGES = {"apply", "tailor", "mailstatus"}

# Not a stage. shortlist.py only turns stored decisions into a file, which is why
# both pipeline.py and web/ are allowed to import it (PRD section 8.2).
PUBLISHER = {"shortlist"}

# imapread.py (F-50) is the only module that speaks IMAP for mail status; it sits
# here so that both apply/mail.py and mailstatus_flow.py can use it.
FOUNDATION = {"store", "config", "models", "net", "backends", "watchlist",
              "applicant", "vault", "imapread"}

# web/ may use the foundation (the vault included) but never imapread: the web
# process starts a `mail sync` child instead of reading mail itself (MS 2.2 rule 4).
WEB_MAY_IMPORT = (FOUNDATION - {"imapread"}) | PUBLISHER | CONTRACTS

# The modules that touch a mailbox (MS 2.2 rule 5). A missing one is skipped: the
# set grows as F-50 lands, and apply/mail.py exists today.
MAILBOX_MODULES = ("imapread.py", "mailstatus", "mailstatus_flow.py", "apply/mail.py")

# Not layered code: the CLI entry points. v1's modules retired at M9-T1
# (kept at the v1-final tag), so the only exemptions left are these.
LEGACY = {"cli", "__main__", "__init__"}

SQL_TOKENS = ("SELECT ", "INSERT ", "UPDATE ", "DELETE FROM", "CREATE TABLE")


def _name(parts: list[str]) -> str:
    """A module's layer name: its top package, or one level deeper inside the
    DOTTED_PACKAGES (`apply.contracts`), so web/ can be allowed exactly that."""
    if parts[0] in DOTTED_PACKAGES and len(parts) > 1:
        return f"{parts[0]}.{parts[1]}"
    return parts[0]


def _top(name: str) -> str:
    return name.split(".")[0]


def _local_imports(path: Path) -> set[str]:
    """Names of sibling jobscraper modules this file imports.

    Top-level names (`store`, `filter`), except inside the apply/tailor packages,
    which are reported one level deeper (`apply.contracts`). A relative import is
    resolved against the importing file's own package, so `from .contracts import`
    in apply/resolve.py is `apply.contracts`.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pkg = list(path.relative_to(SRC).parts[:-1])      # the file's package path
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # `from .filter import x` / `from jobscraper.filter import x`
            if node.level:                       # relative
                up = node.level - 1
                base = pkg[:len(pkg) - up] if up <= len(pkg) else []
                mod = base + (node.module.split(".") if node.module else [])
                if node.module:
                    found.add(_name(mod))
                else:                            # `from . import filter`
                    found.update(_name(mod + [a.name]) for a in node.names)
            elif (node.module or "").startswith("jobscraper"):
                parts = node.module.split(".")[1:]
                if len(parts) == 1 and parts[0] in DOTTED_PACKAGES:
                    # `from jobscraper.apply import contracts`
                    found.update(_name(parts + [a.name]) for a in node.names)
                elif parts:
                    found.add(_name(parts))
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("jobscraper."):
                    found.add(_name(a.name.split(".")[1:]))
    return found


def _all_v2_files() -> list[tuple[str, Path]]:
    """Every v2 source file, paired with the layer name it belongs to."""
    files = []
    for p in sorted(SRC.rglob("*.py")):
        rel = p.relative_to(SRC)
        owner = rel.parts[0] if len(rel.parts) > 1 else p.stem
        if len(rel.parts) == 1 and p.stem in LEGACY:
            continue
        files.append((owner, p))
    return files


def test_store_never_imports_a_stage():
    store = SRC / "store.py"
    if not store.exists():
        return
    bad = {_top(n) for n in _local_imports(store)} & (STAGES | PUBLISHER)
    assert not bad, (
        f"store.py imports {sorted(bad)} - data access must not reach upwards "
        "into the pipeline (PRD 8.2 rule 1)")


def test_stages_never_import_each_other():
    offenders = []
    for owner, path in _all_v2_files():
        if owner not in STAGES:
            continue
        # Its own package (`apply.contracts` from apply/resolve.py) is not a
        # crossing; any other stage, including the other's contracts, is.
        crossed = {_top(n) for n in _local_imports(path)} & (STAGES - {owner})
        if crossed:
            offenders.append(f"{path.relative_to(SRC)} -> {sorted(crossed)}")
    assert not offenders, (
        "stages must be composed by pipeline.py, not wired to each other "
        f"(PRD 8.2 rule 2): {offenders}")


def _web_crossings(imports: set[str]) -> set[str]:
    """What a web/ module may not import: anything outside WEB_MAY_IMPORT and web/."""
    return {n for n in imports if n not in WEB_MAY_IMPORT and _top(n) != "web"}


def test_web_never_imports_a_stage():
    offenders = []
    for owner, path in _all_v2_files():
        if owner != "web":
            continue
        crossed = _web_crossings(_local_imports(path))
        if crossed:
            offenders.append(f"{path.relative_to(SRC)} -> {sorted(crossed)}")
    assert not offenders, (
        "web/ may import only "
        f"{sorted(WEB_MAY_IMPORT)} (PRD 8.2 rule 3): {offenders}")


def _sql_hits(text: str) -> list[str]:
    """The SQL_TOKENS in `text` that no word character runs into: `UPDATE x SET`
    is SQL, while the enum lines `PORTAL_UPDATE = ...` and `NO_UPDATE = ...`
    (mailstatus/contracts.py) are not."""
    return [t.strip() for t in SQL_TOKENS if re.search(r"(?<!\w)" + re.escape(t), text)]


def test_only_store_contains_sql():
    offenders = []
    for _owner, path in _all_v2_files():
        if path.name == "store.py":
            continue
        text = path.read_text(encoding="utf-8")
        hits = _sql_hits(text)
        if hits:
            offenders.append(f"{path.relative_to(SRC)} contains {hits}")
    assert not offenders, (
        "SQL belongs in store.py alone - that is what keeps the Postgres path "
        f"in PRD 8.4 to one module (rule 4): {offenders}")


def test_only_backends_talks_to_a_model():
    offenders = []
    for _owner, path in _all_v2_files():
        if path.name == "backends.py":
            continue
        text = path.read_text(encoding="utf-8")
        for marker in ("/api/chat", "/api/tags", "import anthropic"):
            if marker in text:
                offenders.append(f"{path.relative_to(SRC)} contains {marker!r}")
    assert not offenders, (
        "backends.py is the single place that reaches a model (PRD 8.2 rule 5): "
        f"{offenders}")


def test_nothing_imports_the_orchestrator():
    """pipeline.py is the top of the stack. An import of it is a cycle.

    Orchestrators may not import each other either, except the pairs in
    ORCHESTRATOR_EDGES (apply_flow -> tailor_flow, apply_design.md 2.3).
    """
    offenders = []
    for _owner, path in _all_v2_files():
        allowed = {path.stem} | {dst for src, dst in ORCHESTRATOR_EDGES if src == path.stem}
        crossed = {_top(n) for n in _local_imports(path)} & ORCHESTRATOR - allowed
        if crossed:
            offenders.append(f"{path.relative_to(SRC)} -> {sorted(crossed)}")
    assert not offenders, (
        "pipeline.py composes the stages; nothing may import it back "
        f"(PRD 8.2): {offenders}")


def _unclassified(src: Path) -> set[str]:
    """Top-level modules and packages under `src` that belong to no layer."""
    known = ORCHESTRATOR | STAGES | PUBLISHER | FOUNDATION | LEGACY | {"web"}
    seen = {p.stem if len(p.relative_to(src).parts) == 1
            else p.relative_to(src).parts[0]
            for p in src.rglob("*.py")}
    return seen - known


def test_every_v2_module_is_classified():
    """A new module must be given a layer, not left to drift unchecked."""
    unclassified = _unclassified(SRC)
    assert not unclassified, (
        f"modules {sorted(unclassified)} belong to no layer. Add them to STAGES, "
        "PUBLISHER, FOUNDATION or LEGACY in this file and to PRD section 8.2 - "
        "an unclassified module is one no boundary rule protects.")


def _foundation_crossings(imports: set[str]) -> set[str]:
    """What a foundation module may not import: any stage, orchestrator or
    publisher module - except the contracts modules (CONTRACTS), which are
    stdlib-only data shapes (D-73; vault.py imports `Secret` and `PasswordRules`
    from apply.contracts, apply_design section 10.1). Anything else inside the
    apply/tailor packages (`apply.resolve`, `tailor.validator`) stays forbidden."""
    return {n for n in imports
            if n not in CONTRACTS and _top(n) in (STAGES | ORCHESTRATOR | PUBLISHER)}


def test_foundation_modules_import_no_stage_or_orchestrator():
    """applicant.py and vault.py (M20) sit beside store.py at the bottom: they
    may use each other and the rest of the foundation, and exactly the contracts
    modules (CONTRACTS, as web/ may), never a stage (D-73)."""
    offenders = []
    for owner, path in _all_v2_files():
        if owner not in FOUNDATION:
            continue
        crossed = _foundation_crossings(_local_imports(path))
        if crossed:
            offenders.append(f"{path.relative_to(SRC)} -> {sorted(crossed)}")
    assert not offenders, f"foundation must not reach upwards: {offenders}"


def test_apply_and_tailor_meet_only_through_their_flows():
    """The stage packages never import each other or an orchestrator; only
    apply_flow may import tailor_flow (apply design section 2.3, rule 4)."""
    offenders = []
    for owner, path in _all_v2_files():
        if owner not in DOTTED_PACKAGES:
            continue
        other = (DOTTED_PACKAGES - {owner}) | ORCHESTRATOR
        crossed = {_top(n) for n in _local_imports(path)} & other
        if crossed:
            offenders.append(f"{path.relative_to(SRC)} -> {sorted(crossed)}")
    assert not offenders, offenders


def _imports_of_source(text: str, rel: str = "m.py") -> set[str]:
    """`_local_imports` on a synthetic source file (it resolves paths against SRC,
    so SRC is pointed at a scratch directory for the call). `rel` places the file
    inside a package (`mailstatus/rules.py`) so relative imports resolve there."""
    import tempfile
    d = Path(tempfile.mkdtemp())
    f = d / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    global SRC
    real, SRC = SRC, d
    try:
        return _local_imports(f)
    finally:
        SRC = real


def test_the_layering_guard_catches_what_it_claims_to():
    """Self-check on synthetic sources (the guard itself must not rot): the
    import reader reports the stage packages' modules dotted, only
    apply_flow -> tailor_flow is an exempt orchestrator edge, and the foundation
    rule (D-73) lets a foundation module import exactly the contracts modules."""
    got = _imports_of_source("from jobscraper.apply.contracts import A\n"
                             "from jobscraper.tailor import contracts\n"
                             "from jobscraper.apply import flowy\n"
                             "from jobscraper.store import Store\n")
    assert {"apply.contracts", "tailor.contracts", "apply.flowy", "store"} <= got
    assert ("apply_flow", "tailor_flow") in ORCHESTRATOR_EDGES
    assert ("tailor_flow", "apply_flow") not in ORCHESTRATOR_EDGES
    assert ("pipeline", "tailor_flow") not in ORCHESTRATOR_EDGES

    # Foundation, allowed: the contracts modules in every import spelling, and
    # other foundation modules.
    for src in ("from jobscraper.apply.contracts import Secret, PasswordRules\n",
                "from .apply.contracts import Secret\n",
                "from jobscraper.apply import contracts\n",
                "from jobscraper.tailor.contracts import T\n",
                "import jobscraper.apply.contracts\n",
                "from jobscraper.store import Store\n"
                "from jobscraper.vault import Vault\n"):
        assert not _foundation_crossings(_imports_of_source(src)), src

    # Foundation, forbidden: any other module of a stage package, a whole stage
    # package, a plain stage, the publisher, an orchestrator - alone or beside
    # an allowed contracts import (which must not mask it).
    for src, bad in (
            ("from jobscraper.apply.resolve import R\n", {"apply.resolve"}),
            ("from jobscraper.apply import resolve\n", {"apply.resolve"}),
            ("from jobscraper.apply import contracts, resolve\n", {"apply.resolve"}),
            ("from jobscraper.apply.contracts import Secret\n"
             "from jobscraper.apply.resolve import R\n", {"apply.resolve"}),
            ("from jobscraper.tailor.validator import V\n", {"tailor.validator"}),
            ("import jobscraper.apply.resolve\n", {"apply.resolve"}),
            ("from . import apply\n", {"apply"}),
            ("from jobscraper.filter import f\n", {"filter"}),
            ("from jobscraper.shortlist import s\n", {"shortlist"}),
            ("from jobscraper.apply_flow import a\n", {"apply_flow"})):
        assert _foundation_crossings(_imports_of_source(src)) == bad, src


# ------------------------------------------------------------------ F-50 mail status
# mail_status_design.md 2.2 (rules 1-6) and 2.1 ("the stage depends only on its own
# contracts").

WRITE_COMMANDS = frozenset({"STORE", "COPY", "MOVE", "EXPUNGE", "APPEND"})
_COMMAND_SENDERS = frozenset({"uid", "xatom", "_simple_command", "_command"})


def _mailbox_writes(text: str) -> list[str]:
    """Mailbox-write commands in one source file (MS 2.2 rule 5), as `line: what`.

    Read with `ast`, so comments and docstrings that *say* "never STORE" don't
    count. The design's token list is applied to code:
      - `smtplib` imported or named;
      - a string that is exactly a write command ("STORE", "COPY", "MOVE",
        "EXPUNGE", "APPEND"), and such a command as the first argument of
        `uid`/`xatom`/`_simple_command` in any case (`conn.uid("store", ...)`);
      - the imaplib write methods: `.store(` and `.expunge(` always, `.move(`
        unless it is `shutil.move`, and `.copy(` / `.append(` with two or more
        positional arguments (imaplib's take 2 and 4; `list.append(x)`,
        `dict.copy()` and `copy.copy(x)` take at most 1, so they stay legal);
      - `readonly=` anything but `True`, and a `.select(` without `readonly=True`.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(text)):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            found += [f"{line}: import {a.name}" for a in node.names
                      if a.name.split(".")[0] == "smtplib"]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "smtplib":
                found.append(f"{line}: from smtplib")
        elif isinstance(node, ast.Name) and node.id == "smtplib":
            found.append(f"{line}: smtplib")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.strip() in WRITE_COMMANDS:
                found.append(f"{line}: {node.value!r}")
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "readonly" and not (isinstance(kw.value, ast.Constant)
                                                 and kw.value.value is True):
                    found.append(f"{line}: readonly={ast.unparse(kw.value)}")
            if not isinstance(node.func, ast.Attribute):
                continue
            name, nargs = node.func.attr, len(node.args)
            receiver = node.func.value
            if name in ("store", "expunge"):
                found.append(f"{line}: .{name}(")
            elif name == "move" and not (isinstance(receiver, ast.Name)
                                         and receiver.id == "shutil"):
                found.append(f"{line}: .move(")
            elif name in ("copy", "append") and nargs >= 2:
                found.append(f"{line}: .{name}( with {nargs} arguments")
            elif name in _COMMAND_SENDERS and node.args:
                first = node.args[0]
                words = first.value.split() if (isinstance(first, ast.Constant)
                                                and isinstance(first.value, str)) else []
                if words and words[0].upper() in WRITE_COMMANDS:
                    found.append(f"{line}: .{name}({first.value!r}")
            elif name == "select":
                ro = [kw.value for kw in node.keywords if kw.arg == "readonly"]
                if nargs >= 2:
                    ro.append(node.args[1])
                if not any(isinstance(v, ast.Constant) and v.value is True for v in ro):
                    found.append(f"{line}: .select( without readonly=True")
    return found


def _mailbox_files(src: Path) -> list[Path]:
    """The MAILBOX_MODULES that exist under `src` (a package counts all its files)."""
    out: list[Path] = []
    for rel in MAILBOX_MODULES:
        p = src / rel
        if p.is_dir():
            out += sorted(p.rglob("*.py"))
        elif p.exists():
            out.append(p)
    return out


def test_mail_modules_never_write_the_mailbox():
    """F-50g / D-151 d: imapread.py, mailstatus/**, mailstatus_flow.py and
    apply/mail.py read mail and nothing else (MS 2.2 rule 5, 5.6)."""
    files = _mailbox_files(SRC)
    assert SRC / "apply" / "mail.py" in files, "apply/mail.py moved: update MAILBOX_MODULES"
    offenders = [f"{p.relative_to(SRC)} {hit}"
                 for p in files for hit in _mailbox_writes(p.read_text(encoding="utf-8"))]
    assert not offenders, (
        "a module that touches the mailbox contains a write command; mail is "
        f"read-only by construction (F-50g, MS 5.6): {offenders}")


def test_mailstatus_stage_imports_only_itself():
    """MS 2.1: the stage never touches IMAP or the model; the flow hands it parsed
    headers, body text and store rows, and the stage depends only on its own
    contracts. So every mailstatus/ file imports only mailstatus.* (no imapread,
    no backends, no store, no other stage)."""
    offenders = []
    for owner, path in _all_v2_files():
        if owner != "mailstatus":
            continue
        crossed = {n for n in _local_imports(path) if _top(n) != "mailstatus"}
        if crossed:
            offenders.append(f"{path.relative_to(SRC)} -> {sorted(crossed)}")
    assert not offenders, offenders


def test_the_mail_layering_rules_catch_what_they_claim_to():
    """Self-check for MS 2.2 rules 1-6 on synthetic sources and a scratch tree."""
    import tempfile

    # Rules 1-3: the sets.
    assert "imapread" in FOUNDATION and "imapread" not in WEB_MAY_IMPORT
    assert "mailstatus" in STAGES and "mailstatus" in DOTTED_PACKAGES
    assert "mailstatus.contracts" in CONTRACTS and "mailstatus.contracts" in WEB_MAY_IMPORT
    assert "mailstatus_flow" in ORCHESTRATOR
    assert not {e for e in ORCHESTRATOR_EDGES if "mailstatus_flow" in e}

    # Every new module has a layer (test_every_v2_module_is_classified would fail
    # the moment mailstatus/ lands without these sets).
    tree = Path(tempfile.mkdtemp())
    for rel in ("imapread.py", "mailstatus/__init__.py", "mailstatus/contracts.py",
                "mailstatus/rules.py", "mailstatus_flow.py", "web/mailsync.py"):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_text("", encoding="utf-8")
    assert _unclassified(tree) == set()

    # Rule 6, foundation: mailstatus.contracts in every spelling is allowed ...
    for src in ("from jobscraper.mailstatus.contracts import MailHeader\n",
                "from jobscraper.mailstatus import contracts\n",
                "import jobscraper.mailstatus.contracts\n",
                "from .mailstatus.contracts import Cursor\n"):
        assert not _foundation_crossings(_imports_of_source(src)), src
    # ... any other mailstatus module or the flow is not.
    for src, bad in (
            ("from jobscraper.mailstatus.rules import R\n", {"mailstatus.rules"}),
            ("from jobscraper.mailstatus import contracts, match\n", {"mailstatus.match"}),
            ("from jobscraper.mailstatus.contracts import Cursor\n"
             "from jobscraper.mailstatus.model import parse\n", {"mailstatus.model"}),
            ("from jobscraper.mailstatus_flow import sync\n", {"mailstatus_flow"})):
        assert _foundation_crossings(_imports_of_source(src)) == bad, src

    # Rule 4, web/: the vault and the mail contracts yes; imapread, the stage and
    # the flow no.
    for src in ("from jobscraper.vault import Vault\n",
                "from jobscraper.mailstatus.contracts import CONSENT_VERSION\n",
                "from jobscraper.store import Store\n"):
        assert not _web_crossings(_imports_of_source(src)), src
    for src, bad in (("from jobscraper.imapread import ImapTransport\n", {"imapread"}),
                     ("import jobscraper.imapread\n", {"imapread"}),
                     ("from jobscraper.mailstatus.rules import load_rules\n",
                      {"mailstatus.rules"}),
                     ("from jobscraper.mailstatus_flow import sync\n", {"mailstatus_flow"})):
        assert _web_crossings(_imports_of_source(src)) == bad, src

    # Inside the package a relative import of a sibling resolves to mailstatus.*;
    # apply/ is another stage package (test_apply_and_tailor_meet_only_through_their_flows
    # iterates DOTTED_PACKAGES, so it now covers mailstatus too).
    got = _imports_of_source("from .contracts import Verdict\nfrom . import rules\n",
                             rel="mailstatus/match.py")
    assert got == {"mailstatus.contracts", "mailstatus.rules"}, got
    got = _imports_of_source("from jobscraper.apply.contracts import Secret\n",
                             rel="mailstatus/rules.py")
    assert {_top(n) for n in got} & (DOTTED_PACKAGES - {"mailstatus"}) == {"apply"}

    # Rule 5: the write scanner, positives ...
    for src in ('conn.store("1", "+FLAGS", "\\\\Seen")\n',
                "conn.expunge()\n",
                'conn.copy("1:3", "Trash")\n',
                'conn.append("INBOX", None, None, b"x")\n',
                'conn.move("1", "Trash")\n',
                'conn.uid("STORE", "7", "+FLAGS", "(\\\\Seen)")\n',
                'conn.uid("move", "7", "Trash")\n',
                'conn.xatom("EXPUNGE")\n',
                'conn.select("INBOX", readonly=False)\n',
                'conn.select("INBOX")\n',
                'conn.select("INBOX", False)\n',
                "import smtplib\n",
                "from smtplib import SMTP\n",
                'CMD = "APPEND"\n'):
        assert _mailbox_writes(src), f"the write scanner missed: {src!r}"
    # ... and what must stay legal: list/dict methods, copy.copy, shutil.move, a
    # read-only select, the Store object, comments, and a docstring naming the commands.
    for src in ('"""Never STORE, COPY, MOVE, EXPUNGE or APPEND."""\n',
                "parts.append(x)\n", "d2 = d.copy()\n", "import copy\nc = copy.copy(x)\n",
                "import shutil\nshutil.move(a, b)\n",
                'conn.select("INBOX", readonly=True)\n',
                'conn.uid("SEARCH", None, "UID", "5:*")\n',
                'conn.uid("FETCH", "5", "(BODY.PEEK[])")\n',
                "store.mail_record(account_id=1)\n", "# conn.store(...)\n"):
        assert not _mailbox_writes(src), f"false positive: {src!r} -> {_mailbox_writes(src)}"

    # The SQL guard: real SQL outside store.py is caught; enum members whose names
    # end in a SQL keyword are not (mailstatus/contracts.py PORTAL_UPDATE, NO_UPDATE).
    assert _sql_hits('cur.execute("UPDATE jobs SET status = ?")') == ["UPDATE"]
    assert _sql_hits('q = f"SELECT id FROM t"\n') == ["SELECT"]
    assert _sql_hits("x = 'DELETE FROM t'") == ["DELETE FROM"]
    assert _sql_hits("    PORTAL_UPDATE = \"portal_update\"\n"
                     "    NO_UPDATE = \"no_update\"\n") == []
    assert _sql_hits("AUTO_SELECT = 1\nPRE_CREATE TABLE\n") == []
