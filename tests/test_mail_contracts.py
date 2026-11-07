"""WP-T0 oracles: `mailstatus/contracts.py` v1 (mail_status_design.md section 3; BP WP-T0).

Two halves, one set of oracles (`_check_*` below):
  1. The design listing (runs now): the python block of MS section 3 is executed as a scratch
     module and every oracle runs on it, so the design itself is self-consistent.
  2. The real module (skip-clean): once `src/jobscraper/mailstatus/contracts.py` exists the
     same oracles run on it, plus "it is MS section 3": the same top-level names, enum
     members, dataclass fields and defaults, constants and texts (WP-S0 transcribes verbatim).
     A change to either side without the other fails here; raise CONTRACT_VERSION and update
     the design together.
Engineers: `python tests/run_tests.py -k mail_contracts` is the WP-S0 Verify.
"""
from __future__ import annotations

import ast
import dataclasses
import enum
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import ROOT, WAITING, missing, needs  # noqa: E402

_W0 = len(WAITING)
DESIGN = ROOT / "docs" / "architecture" / "mail_status_design.md"
REAL = ROOT / "src" / "jobscraper" / "mailstatus" / "contracts.py"
MOD = "jobscraper.mailstatus.contracts"


# ------------------------------------------------------------------ the design listing

def _design_source() -> str:
    """The first ```python block after the MS section 3 heading."""
    text = DESIGN.read_text(encoding="utf-8")
    start = text.index("## 3. Contracts")
    m = re.search(r"```python\n(.*?)\n```", text[start:], re.S)
    assert m, "MS section 3 has no python block"
    return m.group(1) + "\n"


def _design_module() -> types.ModuleType:
    """MS section 3 executed as a module (registered so dataclasses resolve it)."""
    name = "_ms3_contracts_listing"
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    exec(compile(_design_source(), "mail_status_design.md#3", "exec"), mod.__dict__)
    return mod


def _real():
    import importlib
    return importlib.import_module(MOD)


# ------------------------------------------------------------------ the oracles

def _check_version_and_constants(c) -> None:
    assert c.CONTRACT_VERSION == 1
    assert c.CONSENT_VERSION == "mail-consent:v1"
    assert c.MODEL_PROMPT_VERSION == "mail:v1"
    assert (c.GMAIL_HOST, c.GMAIL_PORT) == ("imap.gmail.com", 993)
    assert (c.QUOTE_MAX, c.SUBJECT_MAX) == (200, 120)
    from jobscraper import store
    assert c.TIME_FMT == store.TIME_FMT
    pat = re.compile(c.ADDRESS_PATTERN)
    for good in ("someone@example.com", "first.last+jobs@mail.example.org"):
        assert pat.fullmatch(good), good
    for bad in ("someone@example", "some one@example.com", "@example.com", "a@@example.com", ""):
        assert not pat.fullmatch(bad), bad


def _check_enums(c) -> None:
    for e in (c.MailboxRole, c.AccountState, c.SyncCode, c.Category, c.Outcome, c.Reason,
              c.AuthResult, c.Signal, c.MatchKind, c.Tier, c.ChangeKind):
        assert issubclass(e, str) and issubclass(e, enum.Enum), e      # stored as text
        assert len({m.value for m in e}) == len(list(e)), f"{e.__name__} repeats a value"
    assert {m.value for m in c.Category} == {
        "acknowledged", "assessment", "interview", "offer", "rejected", "withdrawn",
        "posting_closed", "kept_on_file", "portal_update", "no_change", "unknown"}
    assert {m.value for m in c.MailboxRole} == {"all", "junk", "inbox"}
    assert {m.value for m in c.AuthResult} == {"pass", "fail", "none"}
    assert [m.value for m in c.Signal] == ["thread", "employer_domain", "tenant",
                                           "name_in_sender", "name_in_subject",
                                           "name_in_body", "role", "req_id"]


def _check_code_sets(c) -> None:
    S, R = c.SyncCode, c.Reason
    assert c.PAUSING_CODES == {S.NOT_SET_UP, S.LOGIN_REFUSED, S.APP_PASSWORD_REQUIRED,
                               S.WEB_LOGIN_REQUIRED}
    assert c.NOTE_CODES == {S.ALL_MAIL_HIDDEN, S.JUNK_HIDDEN}
    assert not c.PAUSING_CODES & c.NOTE_CODES
    assert not c.SKIP_REASONS & c.SUGGEST_REASONS, "the skip and suggest Reason sets overlap"
    assert R.FORWARD not in c.SKIP_REASONS | c.SUGGEST_REASONS
    assert c.SKIP_REASONS <= set(R) and c.SUGGEST_REASONS <= set(R)
    # The header and content gates (MS 6.2) can only give skip reasons.
    assert {R.TOO_OLD, R.OWN_MAIL, R.AUTO_REPLY, R.JOB_BOARD, R.NOT_JOB_MAIL, R.BULK,
            R.ACCOUNT_MAIL, R.JOB_ALERT, R.OUTREACH} == c.SKIP_REASONS


def _check_texts(c) -> None:
    S, R = c.SyncCode, c.Reason
    assert set(c.SYNC_TEXTS) == set(S) - {S.OK}, (
        f"SYNC_TEXTS must cover every SyncCode except OK: missing "
        f"{sorted(m.value for m in set(S) - {S.OK} - set(c.SYNC_TEXTS))}")
    need = set(c.SUGGEST_REASONS) | {R.FORWARD}
    assert need <= set(c.REASON_TEXTS), (
        f"REASON_TEXTS lacks {sorted(m.value for m in need - set(c.REASON_TEXTS))}")
    texts = list(c.SYNC_TEXTS.values()) + list(c.REASON_TEXTS.values()) + [c.CONSENT_TEXT]
    for t in texts:
        assert isinstance(t, str) and t.strip() == t and t, repr(t)
        assert t[0].isupper() and t.endswith("."), f"sentence case with a full stop: {t!r}"
        assert "{" not in t and "TODO" not in t, f"placeholder in owner text: {t!r}"
    assert "never" in c.CONSENT_TEXT and "app password" in c.SYNC_TEXTS[S.LOGIN_REFUSED]


def _check_shapes(c) -> None:
    S = c.SyncCode
    frozen = (c.Cursor, c.MessageRef, c.MailHeader, c.MailBody, c.ScanResult, c.TransportInfo,
              c.AppCandidate, c.MatchResult, c.Verdict, c.Change, c.Policy)
    for cls in frozen:
        assert dataclasses.is_dataclass(cls) and cls.__dataclass_params__.frozen, cls.__name__
    for cls in (c.AccountReport, c.SyncReport):
        assert dataclasses.is_dataclass(cls) and not cls.__dataclass_params__.frozen

    ref = c.MessageRef(c.MailboxRole.ALL, "[Gmail]/All Mail", 7, 42)
    try:
        ref.uid = 43
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("MessageRef must be frozen")

    assert c.MailBody("text", False).truncated is False
    v = c.Verdict(c.Category.UNKNOWN, c.Tier.RULE)
    assert (v.quote, v.rule_id, v.status_words, v.model) == ("", "", False, "")
    m = c.MatchResult(c.MatchKind.NONE)
    assert (m.job_id, m.candidates, m.signals, m.platform) == (None, (), (), "")
    ch = c.Change(c.ChangeKind.NONE, c.Reason.SAME_STATUS)
    assert (ch.from_status, ch.to_status) == (None, None)
    pol = c.Policy(statuses=("applied",), ranks={"applied": 1}, terminal=frozenset(),
                   category_status={}, suggest_only=frozenset())
    assert pol.junk_auto == {c.Category.ACKNOWLEDGED} and pol.require_auth is True
    assert c.TransportInfo(capabilities=(), folders={}).notes == ()

    # AccountReport.counts: every COUNT_KEYS key at 0, and never shared between instances.
    a, b = c.AccountReport(1), c.AccountReport(2)
    assert list(a.counts) == list(c.COUNT_KEYS) and set(a.counts.values()) == {0}
    a.counts["scanned"] += 5
    assert b.counts["scanned"] == 0, "AccountReport.counts is shared between instances"
    assert a.code is S.OK and a.notes == ()
    r1, r2 = c.SyncReport(None, S.OK), c.SyncReport(None, S.OK)
    r1.accounts.append(a)
    assert r2.accounts == [], "SyncReport.accounts is shared between instances"
    assert len(c.COUNT_KEYS) == len(set(c.COUNT_KEYS)) == 10

    # MailFailure: a RuntimeError that carries a code and a detail.
    e = c.MailFailure(S.NETWORK, "TimeoutError")
    assert isinstance(e, RuntimeError) and e.code is S.NETWORK and e.detail == "TimeoutError"
    assert str(e) == "network: TimeoutError" and str(c.MailFailure(S.INTERNAL)) == "internal"


def _check_transport_protocol(c) -> None:
    class Minimal:
        def open(self): ...
        def scan(self, role, cursor, *, account_id, window_start, limit, now): ...
        def fetch_body(self, ref, max_bytes): ...
        def refind(self, gm_msgid): ...
        def close(self): ...

    class NoRefind:
        def open(self): ...
        def scan(self, role, cursor, *, account_id, window_start, limit, now): ...
        def fetch_body(self, ref, max_bytes): ...
        def close(self): ...

    assert isinstance(Minimal(), c.MailTransport)
    assert not isinstance(NoRefind(), c.MailTransport)
    assert not isinstance(object(), c.MailTransport)


def _check_stdlib_only(source: str) -> None:
    tops = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            tops |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "contracts.py imports nothing relative (stdlib only)"
            tops.add((node.module or "").split(".")[0])
    outside = {t for t in tops if t != "__future__" and t not in sys.stdlib_module_names}
    assert not outside, f"contracts.py must import only the stdlib, not {sorted(outside)}"


_ORACLES = (_check_version_and_constants, _check_enums, _check_code_sets, _check_texts,
            _check_shapes, _check_transport_protocol)


# ------------------------------------------------------------------ half 1: the design

def test_mail_contracts_design_listing_meets_the_oracles():
    c = _design_module()
    for check in _ORACLES:
        check(c)
    _check_stdlib_only(_design_source())


# ------------------------------------------------------------------ half 2: the module

@needs(MOD)
def test_mail_contracts_module_meets_the_oracles():
    c = _real()
    for check in _ORACLES:
        check(c)


@needs(MOD)
def test_mail_contracts_module_imports_only_the_stdlib():
    _check_stdlib_only(REAL.read_text(encoding="utf-8"))
    assert (REAL.parent / "__init__.py").exists()


def _top_level_names(source: str) -> set[str]:
    out: set[str] = set()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            out |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
    return out


def _same(name: str, want, got) -> list[str]:
    """Differences between the design's object and the module's, as text."""
    if isinstance(want, type) and issubclass(want, enum.Enum):
        w = [(m.name, m.value) for m in want]
        g = [(m.name, m.value) for m in got] if isinstance(got, type) else None
        return [] if w == g else [f"{name}: members {g} != design {w}"]
    if isinstance(want, type) and dataclasses.is_dataclass(want):
        def shape(cls):
            fs = []
            for f in dataclasses.fields(cls):
                d = f.default if f.default is not dataclasses.MISSING else (
                    f.default_factory() if f.default_factory is not dataclasses.MISSING
                    else "<required>")
                fs.append((f.name, _plain(d)))
            return fs, cls.__dataclass_params__.frozen
        if not (isinstance(got, type) and dataclasses.is_dataclass(got)):
            return [f"{name}: not a dataclass"]
        return [] if shape(want) == shape(got) else [
            f"{name}: fields {shape(got)} != design {shape(want)}"]
    if isinstance(want, type):                          # Protocol, MailFailure
        wm = {k for k in vars(want) if not k.startswith("_")}
        gm = {k for k in vars(got) if not k.startswith("_")} if isinstance(got, type) else set()
        bases = [b.__name__ for b in want.__mro__[1:]]
        gb = [b.__name__ for b in got.__mro__[1:]] if isinstance(got, type) else []
        return [] if (wm == gm and bases == gb) else [f"{name}: methods/bases differ"]
    return [] if _plain(want) == _plain(got) else [f"{name}: {got!r} != design {want!r}"]


def _plain(v):
    """Enum members as their values, so the two modules' enums compare."""
    if isinstance(v, enum.Enum):
        return v.value
    if isinstance(v, (frozenset, set)):
        return frozenset(_plain(x) for x in v)
    if isinstance(v, (tuple, list)):
        return type(v)(_plain(x) for x in v)
    if isinstance(v, dict):
        return {_plain(k): _plain(x) for k, x in v.items()}
    return v


@needs(MOD)
def test_mail_contracts_module_is_the_design_listing():
    want_src, got_src = _design_source(), REAL.read_text(encoding="utf-8")
    want_names, got_names = _top_level_names(want_src), _top_level_names(got_src)
    assert want_names == got_names, (
        f"contracts.py vs MS section 3: missing {sorted(want_names - got_names)}, "
        f"extra {sorted(got_names - want_names)}")
    d, c = _design_module(), _real()
    diffs = [x for n in sorted(want_names) for x in _same(n, getattr(d, n), getattr(c, n))]
    assert not diffs, "contracts.py differs from MS section 3:\n  " + "\n  ".join(diffs)


def test_mail_contracts_oracles_are_live():
    """Skip-clean only while contracts.py is absent: once it exists, every oracle above
    must be defined (a missing name is a failure, not a quiet skip)."""
    if missing(MOD):
        print(f"[test_mail_contracts] waiting for {MOD}: the design half ran")
        return
    mine = WAITING[_W0:]
    assert not mine, f"oracles still waiting although {MOD} exists: {mine}"
