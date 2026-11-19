"""Q-121 lane W (D-229, contract v10): "What was filled" says WHY a field was left empty. Route pins
for `GET /api/applications/{job}/attempts/{att}/answers`: the four reason keys on every row, the
fixed sentence + hint + code + key for each kind of stop (the always policy AND the strict filler
that runs today), and above all PRIVACY: nothing the filler stored (note, label, captured
question, path, URL, e-mail, a quoted model sentence) reaches the page through them.

Real app over a temp config, temp DB and a temp COPY of the sample details file (the Q-127 web
harness); fake job manager; no model, no network, nothing from data/; made-up names only.
Verify: python tests/run_tests.py -k q121_reasons_web
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_q127_web import R, _answers, _world  # noqa: E402

from jobscraper import applicant  # noqa: E402
from jobscraper.apply import contracts as C  # noqa: E402

NA = C.NotAnsweredReason
EMPTY4 = ("reason", "reason_hint", "reason_code", "reason_key")
GROUP = "consents.group_sharing"


def row(name, label, *, note="", status="unknown", required=True, field_class="", ftype="text",
        question=None, job=1):
    """One audit row. `question` = (reason, target_path) adds a captured question for the field."""
    r = R(name, label, ftype=ftype, status=status, assumed=False, required=required,
          field_class=field_class, value=None, job=job, source="none",
          capture=(f"k_{name}", "model") if question else None)
    r["_note"], r["_question"] = note, question
    return r


def _world_with(rows, **kw):
    """The Q-127 world, then each row's note and captured question written into the database."""
    from contextlib import contextmanager

    @contextmanager
    def cm():
        with _world(rows, **kw) as (client, cfg, ids):
            con = sqlite3.connect(str(cfg.db_path))
            try:
                for r in rows:
                    con.execute("UPDATE apply_answers SET note = ? WHERE id = ?",
                                (r["_note"] or None, ids["a:" + r["name"]]))
                    if r["_question"]:
                        reason, target = r["_question"]
                        con.execute("UPDATE questions SET reason = ?, target_path = ? WHERE id = ?",
                                    (reason, target, ids["q:" + r["name"]]))
                con.commit()
            finally:
                con.close()
            yield client, cfg, ids
    return cm()


def _by_label(client, ids, **kw) -> dict:
    resp = _answers(client, ids, **kw)
    assert resp.status_code == 200, resp.text
    return {f["label"]: f for f in resp.json()["fields"]}


def _finite_sentences() -> tuple[set, set]:
    texts, hints = set(), set(C.NOT_ANSWERED_ROW_HINTS)
    details = list(C.CONSENT_REFUSED_DETAILS.values()) + [C.NOT_ANSWERED_ANY_DETAIL]
    for entry in C.NOT_ANSWERED_REASONS.values():
        for d in details:
            texts.add(entry.text.format(detail=d))
        if entry.hint:
            hints.add(entry.hint)
    return texts, hints


# ---- W1: the keys, and each kind of stop -------------------------------------------------------------

ALWAYS_ROWS = [
    row("consent", "Share my application with group companies", note=f"not agreed: {GROUP}",
        field_class="consent_sharing:group"),
    row("place", "Are you authorised to work in Atlantis", note="work rights: place not recognised",
        field_class="work_right"),
    row("unclassed", "Describe your best project", note="not classed"),
    row("person", "Referee's phone number", note="never the applicant's own contact"),
    row("optional", "Anything else we should know", required=False),
    row("filled", "Your favourite colour", status="filled"),
]


def test_w1_every_row_has_exactly_the_contract_keys_and_an_answered_row_has_empty_reasons():
    with _world_with(ALWAYS_ROWS) as (client, cfg, ids):
        body = _answers(client, ids).json()
        for f in body["fields"]:
            assert set(f) == set(C.ANSWERS_FIELD_KEYS), sorted(set(f) ^ set(C.ANSWERS_FIELD_KEYS))
        got = {f["label"]: f for f in body["fields"]}
        filled = got["Your favourite colour"]
        assert filled["status"] == "not_sent", "a dry-run / stopped attempt: filled but not sent"
        assert all(filled[k] == "" for k in EMPTY4)


def test_w1_a_sent_row_has_empty_reasons():
    rows = [row("sent", "Your favourite colour", status="filled", job=2)]
    with _world_with(rows) as (client, cfg, ids):
        got = _by_label(client, ids, attempt="attempt2", job="job2")
        assert got["Your favourite colour"]["status"] == "sent"
        assert all(got["Your favourite colour"][k] == "" for k in EMPTY4)


def test_w1_an_always_attempt_each_kind_of_stop_has_its_fixed_sentence_hint_code_and_key():
    with _world_with(ALWAYS_ROWS) as (client, cfg, ids):
        got = _by_label(client, ids)
    c = got["Share my application with group companies"]
    assert c["status"] == "not_answered" and c["reason_code"] == "consent_not_agreed"
    assert c["reason_key"] == GROUP
    assert c["reason"] == C.NOT_ANSWERED_REASONS[NA.CONSENT_NOT_AGREED].text.format(
        detail=C.CONSENT_REFUSED_DETAILS[GROUP])
    assert c["reason_hint"] == C.NOT_ANSWERED_REASONS[NA.CONSENT_NOT_AGREED].hint
    p = got["Are you authorised to work in Atlantis"]
    assert p["reason_code"] == "place_unknown" and p["reason_key"] == C.NOT_ANSWERED_WORK_RIGHTS_KEY
    assert p["reason"] == C.NOT_ANSWERED_REASONS[NA.PLACE_UNKNOWN].text
    n = got["Describe your best project"]
    assert (n["reason_code"], n["reason_key"]) == ("not_in_details", "")
    assert n["reason"] == C.NOT_ANSWERED_REASONS[NA.NOT_IN_DETAILS].text
    assert n["reason_hint"] == C.NOT_ANSWERED_HINT_REMEMBER, "a required, rememberable row"
    o = got["Referee's phone number"]
    assert (o["reason_code"], o["reason_key"]) == ("other_person", "")
    assert o["reason"] == C.NOT_ANSWERED_REASONS[NA.OTHER_PERSON].text
    opt = got["Anything else we should know"]
    assert (opt["reason_code"], opt["reason_key"]) == ("unknown", "")
    assert opt["reason"] == C.NOT_ANSWERED_REASONS[NA.UNKNOWN].text
    assert opt["reason_hint"] == C.NOT_ANSWERED_HINT_OPTIONAL


STRICT_ROWS = [
    row("norule", "Describe your leadership style", question=("no_rule", "")),
    row("nofit", "Pick your preferred work pattern", question=("no_option_fits", "")),
    row("compose", "Write a short cover letter", question=("compose_needed", "")),
    row("attest", "Confirm your degree classification", question=("attestation_unclear", "")),
    row("gap", "What is your date of birth", question=("profile_gap", "identity.date_of_birth")),
    row("gapx", "What is your mystery detail", question=("profile_gap", "nothing.known_here")),
    row("bare", "Tell us about your hobbies"),                       # no note, no question
    row("marker", "Describe your best project", note="not classed",
        question=("profile_gap", "identity.date_of_birth")),         # a marker wins over the question
    row("protected", "Do you have a conflict of interest", field_class="declaration:pep",
        question=("no_option_fits", "")),                            # follows the details: still read
    row("ungrounded", "Which certificate do you hold", status="ungrounded",
        question=("ungrounded", "")),
]


def test_w1_a_strict_attempt_reads_the_captured_question_for_its_reason_and_key():
    with _world_with(STRICT_ROWS) as (client, cfg, ids):
        got = _by_label(client, ids)
    def of(label): return (got[label]["reason_code"], got[label]["reason_key"])
    assert of("Describe your leadership style") == ("not_in_details", "")
    assert of("Pick your preferred work pattern") == ("no_option_fits", "")
    assert of("Write a short cover letter") == ("compose_needed", "")
    assert of("Confirm your degree classification") == ("not_confirmed", "")
    assert of("What is your date of birth") == ("detail_missing", "identity.date_of_birth"), \
        "profile_gap with a path the form knows: the key is that path"
    assert of("What is your mystery detail") == ("detail_missing", ""), \
        "a path the form does not know: no key (no link beats a wrong link)"
    assert of("Tell us about your hobbies") == ("no_answer", ""), "required, empty note, no question"
    assert got["Tell us about your hobbies"]["reason"] == C.NOT_ANSWERED_REASONS[NA.NO_ANSWER].text
    assert of("Describe your best project") == ("not_in_details", ""), "the note's marker wins; no key"
    assert of("Do you have a conflict of interest") == ("no_option_fits", ""), \
        "a protected row's capture is still read for its reason"
    assert of("Which certificate do you hold") == ("not_confirmed", "")
    for f in got.values():
        assert f["status"] == "not_answered"
        assert f["reason"] and f["reason_hint"], "every not-answered row says why and what to do"


def test_w1_a_row_that_cannot_be_remembered_never_hints_at_next_time():
    rows = [
        row("one", "Salary", question=("no_rule", "")),                  # one-word label: too general
        row("file", "Upload your portfolio", ftype="file", question=("no_rule", "")),
        row("decl", "Do you have a conflict of interest", field_class="declaration:pep"),
        row("cons", "Share my application with group companies", field_class="consent_sharing:group"),
        row("ok", "Describe your best project", question=("no_rule", "")),
    ]
    with _world_with(rows) as (client, cfg, ids):
        got = _by_label(client, ids)
    refused = [f for f in got.values() if not f["can_remember"]]
    assert len(refused) >= 4 and got["Describe your best project"]["can_remember"] is True
    for f in refused:
        assert "next time" not in f["reason_hint"], (f["label"], f["reason_hint"])
        assert f["reason_hint"], "a hint is still given"
    assert "next time" in got["Describe your best project"]["reason_hint"]
    assert got["Salary"]["reason_hint"] == C.NOT_ANSWERED_HINT_BY_HAND


# ---- W2: PRIVACY ------------------------------------------------------------------------------------------

NOTE_LEAK = ("Northwind Holdings Ltd", r"C:\Users\sam.sample\Documents\cv-final.pdf",
             "https://northwind.example/apply?id=42", "sam.sample@example.com",
             "I think the applicant is probably a citizen of Narnia")
QUESTION_LEAK = ("Example Co Secret Programme", "https://exampleco.example/careers/q9",
                 "sam.sample.question@example.com")
LABEL_LEAK = "Northwind label leak"


def _hostile_rows():
    note = " ".join(NOTE_LEAK)
    rows = []
    for i, base in enumerate(("", "not agreed: consents.group_sharing", "work rights: place not recognised",
                              "not classed", "the check did not agree", "left empty for the site's validation: ")):
        rows.append(row(f"h{i}", f"{LABEL_LEAK} {i}", note=f"{base} {note}".strip(),
                        field_class="consent_sharing:group" if i == 1 else "",
                        question=("profile_gap", QUESTION_LEAK[1]) if i % 2 else ("no_rule", QUESTION_LEAK[0])))
    rows.append(row("hq", f"{LABEL_LEAK} q", note=note,
                    question=("profile_gap", r"C:\Users\sam.sample\data\applicant.yaml")))
    rows.append(row("hq2", f"{LABEL_LEAK} q2", note=note, question=("profile_gap", QUESTION_LEAK[2])))
    rows.append(row("hq3", f"{LABEL_LEAK} q3", note=note, question=("profile_gap", "Identity.Dob")))
    return rows


def test_w2_nothing_stored_reaches_the_reason_fields_and_the_note_reaches_nowhere():
    rows = _hostile_rows()
    with _world_with(rows) as (client, cfg, ids):
        resp = _answers(client, ids)
        assert resp.status_code == 200, resp.text
        fields = resp.json()["fields"]
        assert len(fields) == len(rows)
        reason_blob = json.dumps([[f[k] for k in EMPTY4] for f in fields])
        whole = resp.text
    for secret in NOTE_LEAK + QUESTION_LEAK + (r"C:\Users", "C:\\\\Users", "applicant.yaml", LABEL_LEAK, "Northwind", "https://", "@example.com"):
        assert secret not in reason_blob, f"leaked into a reason field: {secret!r}"
    for secret in NOTE_LEAK:
        assert secret not in whole, f"the stored note reached the page: {secret!r}"
    for secret in QUESTION_LEAK:
        assert secret not in whole, f"the captured question reached the page: {secret!r}"
    assert [f["label"] for f in fields] == [r["label"] for r in rows], "the label stays the row's own label"


def test_w2_every_sentence_is_one_of_the_contracts_and_every_key_is_empty_or_a_form_item():
    texts, hints = _finite_sentences()
    with _world_with(_hostile_rows() + STRICT_ROWS + ALWAYS_ROWS) as (client, cfg, ids):
        fields = _answers(client, ids).json()["fields"]
    seen = set()
    for f in fields:
        if f["status"] != "not_answered":
            assert all(f[k] == "" for k in EMPTY4)
            continue
        assert f["reason"] in texts, f["reason"]
        assert f["reason_hint"] in hints, f["reason_hint"]
        assert f["reason_code"] in {c.value for c in NA}
        if f["reason_key"]:
            item, sub = applicant.form_item(f["reason_key"])
            assert (item or sub) is not None, f"{f['reason_key']!r} is not a Your-details item"
            assert f["reason_code"] in {c.value for c in C.NOT_ANSWERED_KEY_CODES}
        seen.add(f["reason_code"])
    assert {"consent_not_agreed", "place_unknown", "detail_missing", "not_in_details", "no_answer"} <= seen
    # a hostile captured path never becomes a key
    bad = [f for f in fields if f["label"].startswith(LABEL_LEAK + " q")]
    assert bad and all(f["reason_key"] == "" for f in bad), [f["reason_key"] for f in bad]


# ---- W5: the refused-consent stop, to the switch, to "ready to try again" ---------------------------------------------

def test_w5_a_refused_group_sharing_stop_links_to_a_real_switch_and_turns_ready_once_it_is_on():
    rows = [row("consent", "Share my application with group companies", note=f"not agreed: {GROUP}",
                field_class="consent_sharing:group")]
    with _world_with(rows, reason="consent_refused", waiting_path=GROUP) as (client, cfg, ids):
        f = _by_label(client, ids)["Share my application with group companies"]
        assert (f["reason_code"], f["reason_key"]) == ("consent_not_agreed", GROUP)
        body = client.get("/api/applicant").json()
        section = next(s for s in body["sections"] if GROUP in s["paths"])
        assert section["title"] == "Consents and declarations"
        item, _sub = applicant.form_item(f["reason_key"])
        assert item is not None and item.kind == "bool"

        def ready():
            att = [r for r in client.get("/api/applications").json() if r["job_id"] == ids["job"]][0]
            return att["last_attempt"]["ready_to_retry"]
        assert ready() is False
        assert GROUP not in client.get("/api/apply/status").json()["details_needed"], "never a missing detail"
        edited = body["profile"]
        edited.setdefault("consents", {})[GROUP.split(".", 1)[1]] = True
        r = client.put("/api/applicant", json={"profile": edited, "etag": body["etag"]})
        assert r.status_code == 200, r.text
        assert ready() is True
