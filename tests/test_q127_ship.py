"""Q-127 pre-ship pins for the three fixes of the independent code review (docs/reviews/Q-127-ship-code.md):

  M1  a STRICT stop stores its question sightings under the AUDIT key (the `one:...` key the
      `apply_answers` rows carry), so "Answer for next time" (`web.remember.remember`) finds the
      captured question: the question row goes open -> answered, `ready_to_retry` is True, a captured
      sensitive question keeps `sensitive: true` in the written entry; what the attempt filled or
      stored is the same with the remap disabled (only the sighting's key differs);
  M3  `facts.about_other_person(pf, rctx=<strict rctx>)` keeps the applicant's own email / phone out
      of another person's block ("Your email address" under "Referee details"); with an `always` rctx
      or no rctx the always filler's relaxation still applies. A parity table compares the strict
      result with `personal`'s own function: the old module is rebuilt from `git show
      personal:src/jobscraper/apply/facts.py` when that branch is readable, and the expected booleans
      are ALSO pinned in the table (so the pin holds without git);
  L2  two openers of one v6 database at once, and the deterministic variant where another connection
      adds a column between the opener's `table_info` check and its `ALTER`.

The release pin for "a STRICT attempt runs nothing from the always filler even with the full new code
present" is tests/test_always_lock.py (both entry points patched to raise); it is not repeated here.

Fakes, temp databases and temp files only. The one browser pin runs headless Edge on an inline page
(skip-clean where Edge is missing, like the other page-fill pins). Made-up employer names only.
Verify: python tests/run_tests.py -k q127_ship
"""
from __future__ import annotations

import contextlib
import dataclasses
import importlib.util
import sqlite3
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_fill_t2 as T  # noqa: E402
import test_apply_flow_n6a as N  # noqa: E402

from jobscraper import applicant, apply_flow  # noqa: E402
from jobscraper.apply import facts as F, guards as G, locks  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    AnswerStatus, AttemptState as ST, FieldType as FT, FillPolicy, FormField, PageField, ReasonCode as RC,
)
from jobscraper.store import SCHEMA_VERSION, Store  # noqa: E402
from jobscraper.web import remember as REM  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LABEL = "Describe your ideal weekend."
AUDIT_KEY = "one:describe_your_ideal_weekend"


# ================================================================== M1: the sighting key is the audit key

def _stop_run(*, sensitive=False, remap=True):
    """One STRICT attempt that stops on a required unknown with a non-generic label. Returns
    (world, job id, result, say). `remap=False` runs the pre-fix capture (the akeys argument dropped)."""
    w, jid = N.world()
    nav = N.FakeNav()

    def script(n, s):
        fields = [N.pf("a", "First name"), N.pf("q", LABEL, ftype=FT.TEXTAREA)]
        unknown = N.ans("q", None, status=AnswerStatus.UNKNOWN, note="model: unknown")
        if sensitive:
            unknown = dataclasses.replace(unknown, sensitive=True)
        return N.outcome("one", fields, {"a": N.ans("a", "Alex"), "q": unknown}, unknown_required=("q",))

    real = apply_flow._Run.capture
    if not remap:
        def old_capture(self, at, job, fields, answers, rctx, *, page=False, akeys=None):
            return real(self, at, job, fields, answers, rctx, page=page)
        apply_flow._Run.capture = old_capture
    try:
        with N.scripted(nav, script):
            r, _f, say, _m = N.run(w, jid, nav)
    finally:
        apply_flow._Run.capture = real
    assert r.state is ST.FAILED and r.reason is RC.UNANSWERABLE_REQUIRED, (r.state, r.reason, r.reason_detail)
    return w, jid, r, say, nav


def _sighting_keys(w, attempt_id):
    return [r[0] for r in w.store.conn.execute(
        "SELECT field_key FROM question_sightings WHERE attempt_id = ? ORDER BY id", (attempt_id,))]


def _stable(w, attempt_id):
    """What the attempt stored about its answers, without ids and timestamps."""
    out = []
    for row in w.store.answers(attempt_id):
        out.append({k: v for k, v in sorted(row.items())
                    if k != "id" and not k.endswith("_at") and k != "attempt_id"})
    return out


def _remember(w, jid, r, row, **kw):
    return REM.remember(w.cfg, w.store, job_id=jid, attempt_id=r.attempt_id, answer_id=row["id"],
                        etag=applicant.etag(w.cfg.applicant_path), **kw)


def test_q127_ship_m1_a_strict_stop_stores_its_sighting_under_the_audit_key():
    w, jid, r, _say, _nav = _stop_run()
    try:
        rows = {x["field_key"]: x for x in w.store.answers(r.attempt_id)}
        assert AUDIT_KEY in rows and rows[AUDIT_KEY]["status"] == "unknown", sorted(rows)
        assert _sighting_keys(w, r.attempt_id) == [AUDIT_KEY], _sighting_keys(w, r.attempt_id)
        found = w.store.attempt_field_question(r.attempt_id, AUDIT_KEY)
        assert found is not None and found["status"] == "open", found
        assert w.store.attempt_field_question(r.attempt_id, "q") is None, "the reader key is no longer a sighting key"
    finally:
        w.close()


def test_q127_ship_m1_answer_for_next_time_finds_the_question_and_makes_the_job_ready_to_retry():
    w, jid, r, _say, _nav = _stop_run()
    try:
        row = next(x for x in w.store.answers(r.attempt_id) if x["field_key"] == AUDIT_KEY)
        assert [q["status"] for q in w.store.question_rows()] == ["open"]
        before = w.store.retry_candidates()
        assert len(before) == 1 and before[0]["job_id"] == jid and before[0]["open"] == 1, before
        reply = _remember(w, jid, r, row, value="Hiking and a long breakfast")
        assert reply["ready_to_retry"] is True, reply
        assert [q["status"] for q in w.store.question_rows()] == ["answered"]
        after = w.store.retry_candidates()
        assert len(after) == 1 and (after[0]["open"], after[0]["dismissed"]) == (0, 0), after
        entry = applicant.load(w.cfg.applicant_path)["extra"][reply["key"]]
        assert entry["sensitive"] is False and entry["labels"], entry
    finally:
        w.close()


def test_q127_ship_m1_a_sensitive_captured_question_stays_sensitive_in_the_written_entry():
    w, jid, r, _say, _nav = _stop_run(sensitive=True)
    try:
        assert w.store.attempt_field_question(r.attempt_id, AUDIT_KEY)["sensitive"] is True
        row = next(x for x in w.store.answers(r.attempt_id) if x["field_key"] == AUDIT_KEY)
        reply = _remember(w, jid, r, row, value="Private answer")
        entry = applicant.load(w.cfg.applicant_path)["extra"][reply["key"]]
        assert entry["sensitive"] is True, entry
        assert reply["ready_to_retry"] is True
    finally:
        w.close()


def test_q127_ship_m1_the_remap_changes_only_the_sighting_key_never_what_was_filled():
    """The same stop with the remap disabled: identical result, audit rows, navigator calls and
    counters; only the sighting key differs (`q` before the fix), and then "Answer for next time"
    finds no captured question (the sensitive flag would be lost): the old behaviour, proved here."""
    new = _stop_run(sensitive=True)
    old = _stop_run(sensitive=True, remap=False)
    try:
        (w1, _j1, r1, say1, nav1), (w2, _j2, r2, say2, nav2) = new, old
        assert (r1.state, r1.reason, r1.reason_detail, r1.step) == (r2.state, r2.reason, r2.reason_detail, r2.step)
        assert _stable(w1, r1.attempt_id) == _stable(w2, r2.attempt_id)
        assert nav1.calls == nav2.calls and "next" not in nav1.calls
        assert [(q["label_norm"] if "label_norm" in q else q["label"], q["status"], q["sensitive"])
                for q in w1.store.question_rows()] == \
               [(q["label_norm"] if "label_norm" in q else q["label"], q["status"], q["sensitive"])
                for q in w2.store.question_rows()]
        assert _sighting_keys(w1, r1.attempt_id) == [AUDIT_KEY]
        assert _sighting_keys(w2, r2.attempt_id) == ["q"], "pre-fix: the reader key"
        assert w2.store.attempt_field_question(r2.attempt_id, AUDIT_KEY) is None
        assert say1.text.count("question captured") == say2.text.count("question captured") == 1
    finally:
        new[0].close()
        old[0].close()


# ================================================================== M3: another person's block under strict

STRICT = T.rctx()
ALWAYS = T.rctx(fill_policy=FillPolicy.ALWAYS)


def _pf(label, section="", typ=FT.TEXT, group_title=""):
    return PageField(FormField("k", label, typ, False, section=section), widget="text", group_title=group_title)


def test_q127_ship_m3_the_strict_rctx_is_the_default_and_always_is_not():
    assert STRICT.fill_policy is FillPolicy.STRICT and ALWAYS.fill_policy is FillPolicy.ALWAYS


def test_q127_ship_m3_own_email_and_phone_labels_in_another_persons_block_are_about_that_person_under_strict():
    for label, section, typ in (("Your email address", "Referee details", FT.EMAIL),
                                ("My phone number", "Emergency contact", FT.PHONE)):
        p = _pf(label, section, typ)
        assert F.about_other_person(p, rctx=STRICT) is True, label
        # the always filler's relaxation: an always rctx, or no rctx (the filler's own callers)
        assert F.about_other_person(p, rctx=ALWAYS) is False, label
        assert F.about_other_person(p) is False, label
        # the same through a group heading
        g = _pf(label, "", typ, group_title=section)
        assert F.about_other_person(g, rctx=STRICT) is True, label


def test_q127_ship_m3_the_email_lock_and_the_own_detail_guard_leave_another_persons_fields_alone_under_strict():
    email = _pf("Your email address", "Referee details", FT.EMAIL)
    assert locks._email_lock(email, STRICT) is None
    open_ = locks._email_lock(email, ALWAYS)
    assert open_ is not None and open_.status is AnswerStatus.FILLED and open_.value == T.EMAIL, open_
    # the guard a model / resume / keep answer meets
    for rctx, expect in ((STRICT, True), (ALWAYS, False)):
        c = G._Ctx([email], {}, [], rctx, {}, {}, T.TODAY, T.rules(), [], None, {}, {}, None)
        assert G._own_detail_for_other(c, email, T.EMAIL) is expect, rctx.fill_policy
    phone = _pf("My phone number", "Emergency contact", FT.PHONE)
    c = G._Ctx([phone], {}, [], STRICT, {}, {}, T.TODAY, T.rules(), [], None, {}, {}, None)
    own_phone = T.sample_profile()["contact"]["phone_number"] if "phone_number" in T.sample_profile().get("contact", {}) \
        else None
    if own_phone:
        assert G._own_detail_for_other(c, phone, own_phone) is True
    # facts.relevant: the applicant's phone fact is not offered for another person's phone under strict
    assert F.relevant("profile:contact.phone_number", phone, T.rules(), rctx=STRICT) is False
    # and an ordinary own-details block is untouched
    own = _pf("Your email address", "Contact details", FT.EMAIL)
    assert locks._email_lock(own, STRICT) is not None


def test_q127_ship_m3_a_strict_page_fill_leaves_the_applicants_email_out_of_a_referee_block():
    """One end-to-end strict `pagefill.fill_page` on an inline page (headless Edge; skip-clean without
    it): the fieldset is "Referee details", the field reads "Your email address". The fake model
    (strict=False: any call answers nothing) cannot fill it either; the field stays empty and the
    applicant's email appears nowhere on the page."""
    from llm_fill_support import FakeFillBackend, browser_page
    import test_apply_pagefill as PF
    got = browser_page()
    if got is None:
        return
    pw, browser, pg = got
    try:
        pg.set_content(
            '<div data-automation-id="applyFlowPage"><form>'
            '<fieldset><legend>Referee details</legend>'
            '<label for="re">Your email address</label><input id="re" type="email" name="re">'
            '</fieldset></form></div>')
        with tempfile.TemporaryDirectory() as tmp:
            ctx, rctx = PF._world(Path(tmp))
            assert rctx.fill_policy is FillPolicy.STRICT
            sv = PF.FakeServices(FakeFillBackend(replies=[], strict=False), pg)
            pg.evaluate(PF.INPUTS)
            from jobscraper.apply.pagefill import fill_page
            out = fill_page(pg, PF.FakeNav("one"), ctx, rctx, sv)
            own = rctx.account_email or rctx.profile["contact"]["email"]
            assert pg.input_value("#re") == "", pg.input_value("#re")
            assert own not in pg.content() or pg.input_value("#re") == ""
            assert all(a.value != own for a in out.answers.values()), out.answers
    finally:
        browser.close()
        pw.stop()


def _personal_facts():
    """`personal`'s facts module, rebuilt from git, or None when the branch is not readable."""
    try:
        done = subprocess.run(["git", "show", "personal:src/jobscraper/apply/facts.py"], capture_output=True,
                              text=True, encoding="utf-8", cwd=ROOT, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0 or "def about_other_person" not in done.stdout:
        return None
    spec = importlib.util.spec_from_loader("jobscraper.apply._facts_personal", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "jobscraper.apply"
    try:
        exec(compile(done.stdout, "personal:src/jobscraper/apply/facts.py", "exec"), mod.__dict__)
    except Exception:                                  # noqa: BLE001 - an old module that cannot load here
        return None
    return mod


# (label, section, type, personal's result, this branch's STRICT result). Twelve pairs where the two agree
# (the 7 the engineer ran side by side among them), then pairs where strict refuses MORE than `personal`.
PARITY = [
    ("Your email address", "Referee details", FT.EMAIL, True, True),
    ("My phone number", "Emergency contact", FT.PHONE, True, True),
    ("Your email address", "Contact details", FT.EMAIL, False, False),
    ("Email address", "Referee details", FT.EMAIL, True, True),
    ("Phone", "Emergency contact", FT.PHONE, True, True),
    ("Your full name", "Next of kin", FT.TEXT, True, True),
    ("My name", "Personal details", FT.TEXT, False, False),
    ("Your referee's email", "Referees", FT.EMAIL, True, True),
    ("Your mobile", "Supervisor details", FT.PHONE, True, True),
    ("Mobile number", "Contact", FT.PHONE, False, False),
    ("Your email", "About you", FT.EMAIL, False, False),
    ("Full name", "Personal details", FT.TEXT, False, False),
]
STRICTER = [      # strict refuses more than personal (never fills more): pinned as they are
    ("Your phone number", "Referrer", FT.PHONE, False, True),
    ("Applicant's name", "Referrers and contacts", FT.TEXT, False, True),
    ("My address", "Guarantor", FT.TEXT, False, True),
]


def test_q127_ship_m3_strict_matches_personals_function_on_twelve_pairs_and_never_fills_more():
    old = _personal_facts()
    for label, section, typ, personal, strict in PARITY:
        p = _pf(label, section, typ)
        assert F.about_other_person(p, rctx=STRICT) is strict, (label, section)
        assert personal == strict, "the table's parity rows must agree"
        if old is not None:
            assert old.about_other_person(p) is personal, ("personal's function changed", label, section)
    for label, section, typ, personal, strict in STRICTER:
        p = _pf(label, section, typ)
        assert F.about_other_person(p, rctx=STRICT) is strict, (label, section)
        if old is not None:
            assert old.about_other_person(p) is personal, ("personal's function changed", label, section)
        assert strict or not personal, "strict must never be less strict than personal"
    assert len(PARITY) == 12
    # the two always-side relaxations the table does not cover: always / no rctx never exceed the old answer
    for label, section, typ, personal, _s in PARITY:
        p = _pf(label, section, typ)
        assert F.about_other_person(p, rctx=ALWAYS) <= personal, (label, section)


# ================================================================== L2: two openers of one older database

DROPS = (("apply_answers", "assumed"), ("apply_answers", "field_class"),
         ("apply_attempts", "entries_note"), ("apply_attempts", "trial"))


def _v6_db(path: Path) -> dict[str, int]:
    """A database as v6 left it: a real store with a few rows, then the four later columns dropped and
    the version put back to 6. Returns {table: row count}."""
    st = Store(path)
    cid = st.insert_company("exampleco", "Example Co", "https://exampleco.example")
    st.set_setting("apply.mode", "dry_run")
    st.commit()
    st.close()
    raw = sqlite3.connect(str(path))
    for table, col in DROPS:
        raw.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
    raw.execute("UPDATE meta SET value = '6' WHERE key = 'schema_version'")
    raw.commit()
    counts = _counts(raw)
    raw.close()
    assert cid
    return counts


def _counts(conn) -> dict[str, int]:
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}


def _check_migrated(path: Path, before: dict[str, int]) -> None:
    raw = sqlite3.connect(str(path))
    try:
        assert raw.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert raw.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == str(SCHEMA_VERSION) == "9"
        for table, col in DROPS:
            cols = [r[1] for r in raw.execute(f"PRAGMA table_info({table})")]
            assert cols.count(col) == 1, (table, col, cols)
        after = _counts(raw)
        assert after == {**before, **{k: v for k, v in after.items() if k not in before}} or after == before, (before, after)
        assert {k: after[k] for k in before} == before, (before, after)
    finally:
        raw.close()


def test_q127_ship_l2_two_threads_opening_the_same_v6_database_both_succeed():
    for rnd in range(10):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "db" / "jobscraper.db"
            before = _v6_db(path)
            barrier, errors, stores = threading.Barrier(2), [], []

            def opener():
                try:
                    barrier.wait(timeout=10)
                    st = Store(path, check_same_thread=False)
                    stores.append(st)
                except Exception as exc:                    # noqa: BLE001 - reported below
                    errors.append(repr(exc))
            threads = [threading.Thread(target=opener) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
            assert not errors, (rnd, errors)
            assert len(stores) == 2, rnd
            for st in stores:
                st.ping()
                st.close()
            _check_migrated(path, before)


def test_q127_ship_l2_a_column_added_by_another_connection_first_is_not_an_error():
    """Deterministic: just before each `ALTER TABLE ... ADD COLUMN`, a second connection adds the same
    column (what the live app does when a CLI run starts together with it). The first opener goes on."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / "db" / "jobscraper.db"
        before = _v6_db(path)
        real = Store._add_column
        raced: list[tuple[str, str]] = []

        def racing(self, table, decl):
            self.conn.commit()                                # let the other connection write
            other = sqlite3.connect(str(path), timeout=5)
            try:
                other.execute(f"ALTER TABLE {table} ADD COLUMN {decl}")
                other.commit()
            finally:
                other.close()
            raced.append((table, decl.split()[0]))
            return real(self, table, decl)                    # the real one meets "duplicate column"
        Store._add_column = racing
        try:
            st = Store(path)                                   # must not raise
        finally:
            Store._add_column = real
        st.ping()
        st.close()
        assert sorted(raced) == sorted(DROPS), raced           # all four raced, all four tolerated
        _check_migrated(path, before)
        # and a third, ordinary open of the migrated file is a no-op
        Store(path).close()
        _check_migrated(path, before)


def test_q127_ship_l2_any_other_alter_error_is_still_raised():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        st = Store(Path(tmp) / "x.db")
        try:
            try:
                st._add_column("no_such_table", "c TEXT")
            except sqlite3.OperationalError as exc:
                assert "no such table" in str(exc)
            else:
                raise AssertionError("a non-duplicate error must not be swallowed")
        finally:
            st.close()
