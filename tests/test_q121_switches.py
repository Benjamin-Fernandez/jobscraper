"""Q-121 lane P (D-229): the three consent SWITCHES in Profile -> Your details -> Consents and
declarations (`consents.group_sharing`, `consents.third_party_sharing`, `consents.background_checks`).
Product pins: the form shows them off by default; an old details file without the keys is
unchanged by a save; a switch that is off is a decision, NEVER a missing detail; a waiting
application turns "ready to try again" only once the switch is ON; the model's briefing says
yes / no for each (no when unset); the filler reads the key it knows with absent = False.

Real app over a temp config, temp DB and a temp COPY of the sample details file; the job manager
is a fake; no model, no network, nothing from data/. Made-up people and employers only.
Verify: python tests/run_tests.py -k q121_switches
"""
from __future__ import annotations

import copy
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import SAMPLE, profile as sample_profile  # noqa: E402

from jobscraper import applicant  # noqa: E402
from jobscraper.apply import contracts as C  # noqa: E402

KEYS = ("consents.group_sharing", "consents.third_party_sharing", "consents.background_checks")
OLD_FOUR = ("consents.privacy_consent", "consents.data_retention_consent",
            "consents.talent_pool_opt_in", "consents.certify_true")


@contextmanager
def _world(prof: dict | None = None, text: str | None = None):
    """(client, applicant path, cfg) over a temp copy of the sample details file."""
    from fastapi.testclient import TestClient
    from jobscraper.config import Config
    from jobscraper.web.api import create_app
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        path = data / "applicant.yaml"
        if text is not None:
            path.write_text(text, encoding="utf-8", newline="\n")
        else:
            path.write_text(yaml.safe_dump(prof if prof is not None else sample_profile(),
                                           sort_keys=False), encoding="utf-8", newline="\n")
        cfg = Config({"paths": {"db": str(data / "jobscraper.db"), "applicant": str(path),
                                "shortlist": str(data / "shortlist.json"),
                                "profile": str(data / "profile.derived.yaml"), "resume_dir": str(data)},
                      "web": {"host": "127.0.0.1", "port": 8765}})
        with TestClient(create_app(cfg), base_url="http://localhost") as client:
            yield client, path, cfg


def _disk(path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _consents(p: dict) -> dict:
    return dict((p.get("consents") or {}))


def _without_switches(p: dict) -> dict:
    p = copy.deepcopy(p)
    for k in KEYS:
        (p.get("consents") or {}).pop(k.split(".", 1)[1], None)
    return p


# ---- P1: the form -------------------------------------------------------------------------------

def test_p1_the_consents_group_lists_the_four_old_consents_then_the_three_switches_in_order():
    group = next(g for g in applicant.form_json() if g["id"] == "consents")
    paths = [i["path"] for i in group["items"]]
    assert paths == list(OLD_FOUR) + list(KEYS), paths
    by_path = {i["path"]: i for i in group["items"]}
    for sw in C.CONSENT_SWITCHES:
        item = by_path[sw.key]
        assert item["kind"] == "bool"
        assert item["default_off"] is True, "the page needs this to say 'off' rather than 'not set'"
        assert item["label"] == sw.title and item["help"] == sw.help, "text comes from the contract"
        assert item["required"] is False and item["recommended"] is False, "a switch is never a missing detail"
    for p in OLD_FOUR:
        assert "default_off" not in by_path[p], "the four old consents are unchanged"


def test_p1_the_switches_are_in_the_consents_and_declarations_section_and_in_the_get_payload():
    sec = next(s for s in applicant.sections_json() if s["id"] == "consents_declarations")
    assert sec["title"] == "Consents and declarations"
    assert list(KEYS) == [p for p in sec["paths"] if p in KEYS], "the three, in order"
    assert all(k in sec["paths"] for k in OLD_FOUR)
    with _world() as (c, _p, _cfg):
        body = c.get("/api/applicant").json()
        assert body["form"] == applicant.form_json(), "the page renders exactly the server's form"
        assert any(k in s["paths"] for s in body["sections"] for k in KEYS)


def test_p1_every_switch_path_is_a_form_item_so_a_link_to_it_has_a_target():
    for k in KEYS:
        item, _sub = applicant.form_item(k)
        assert item is not None and item.kind == "bool", k
    item, _ = applicant.form_item(C.NOT_ANSWERED_WORK_RIGHTS_KEY)
    assert item is not None, "the place link's target is a form item too"


# ---- P2: an existing details file without the keys ----------------------------------------------

def test_p2_a_file_without_the_keys_loads_and_nothing_about_it_is_missing_or_counted():
    base = _without_switches(sample_profile())
    assert not any(k.split(".", 1)[1] in base["consents"] for k in KEYS)
    with _world(base) as (c, path, cfg):
        body = c.get("/api/applicant").json()
        assert body["errors"] == []
        assert not [m for m in body["missing"] if m.startswith("consents.") and m in KEYS]
        # the same profile with all three explicitly OFF and all three explicitly ON reads the same
        off, on = copy.deepcopy(base), copy.deepcopy(base)
        for k in KEYS:
            off["consents"][k.split(".", 1)[1]] = False
            on["consents"][k.split(".", 1)[1]] = True
        for other in (off, on):
            assert applicant.missing_for_apply(other, cfg.resume_dir) == body["missing"]
            assert applicant.completeness(other) == applicant.completeness(base)
            assert not [e for e in applicant.validate(other)]
        assert c.get("/api/apply/status").json()["details_needed"] == \
            applicant.dedupe_by_item(list(dict.fromkeys(body["missing"]))), \
            "the badge inputs hold the missing list and nothing about the switches"


def test_p2_saving_another_section_writes_none_of_the_three_keys():
    base = _without_switches(sample_profile())
    with _world(base) as (c, path, _cfg):
        got = c.get("/api/applicant").json()
        edited = got["profile"]
        edited["identity"]["preferred_name"] = "Sam"
        r = c.put("/api/applicant", json={"profile": edited, "etag": got["etag"]})
        assert r.status_code == 200, r.text
        on_disk = _disk(path)
        assert on_disk["identity"]["preferred_name"] == "Sam"
        for k in KEYS:
            assert k.split(".", 1)[1] not in _consents(on_disk), f"{k} must not appear by itself"
        assert _consents(on_disk) == _consents(base)


def test_p2_turning_one_switch_on_changes_only_that_key_and_the_etag():
    base = _without_switches(sample_profile())
    with _world(base) as (c, path, _cfg):
        got = c.get("/api/applicant").json()
        before = _disk(path)
        edited = got["profile"]
        edited.setdefault("consents", {})["group_sharing"] = True
        r = c.put("/api/applicant", json={"profile": edited, "etag": got["etag"]})
        assert r.status_code == 200, r.text
        assert r.json()["etag"] != got["etag"]
        after = _disk(path)
        assert _consents(after)["group_sharing"] is True
        expected = copy.deepcopy(before)
        expected["consents"]["group_sharing"] = True
        assert after == expected, "nothing but that one key changed"
        assert "third_party_sharing" not in _consents(after) and "background_checks" not in _consents(after)
        assert c.get("/api/applicant").json()["missing"] == got["missing"], "still nothing 'missing'"


def test_p2_a_non_boolean_switch_is_422_at_its_path_and_nothing_is_written():
    base = _without_switches(sample_profile())
    for bad in ("maybe", 5, ["x"]):   # ("yes"/"true" are normalised to a bool, as for every bool)
        with _world(base) as (c, path, _cfg):
            got = c.get("/api/applicant").json()
            before = Path(path).read_bytes()
            edited = got["profile"]
            edited.setdefault("consents", {})["third_party_sharing"] = bad
            r = c.put("/api/applicant", json={"profile": edited, "etag": got["etag"]})
            assert r.status_code == 422, (bad, r.text)
            assert "consents.third_party_sharing" in {e["path"] for e in r.json()["errors"]}, r.text
            assert Path(path).read_bytes() == before


def test_p2_switching_one_back_off_writes_false_and_it_is_still_not_missing():
    """PINNED BEHAVIOUR: off is written as an explicit `false` (not removed): the owner's
    decision is on file, and the filler reads False either way."""
    base = _without_switches(sample_profile())
    with _world(base) as (c, path, cfg):
        got = c.get("/api/applicant").json()
        edited = got["profile"]
        edited.setdefault("consents", {})["background_checks"] = True
        got2 = c.put("/api/applicant", json={"profile": edited, "etag": got["etag"]}).json()
        edited = got2["profile"]
        edited["consents"]["background_checks"] = False
        r = c.put("/api/applicant", json={"profile": edited, "etag": got2["etag"]})
        assert r.status_code == 200, r.text
        assert _consents(_disk(path)).get("background_checks") is False
        assert r.json()["missing"] == got["missing"]
        assert applicant.missing_for_apply(_disk(path), cfg.resume_dir) == got["missing"]


# ---- P3: never counted; "ready to try again" only once the switch is ON ------------------------------

def _waiting_world(switch_value):
    from test_q127_web import _world as app_world

    def edit(p):
        for k in KEYS:
            p["consents"].pop(k.split(".", 1)[1], None)
        if switch_value is not None:
            p["consents"]["group_sharing"] = switch_value
    return app_world([], profile_edit=edit, reason="consent_refused",
                     waiting_path="consents.group_sharing")


def _last(client, ids):
    return [r for r in client.get("/api/applications").json()
            if r["job_id"] == ids["job"]][0]["last_attempt"]


def test_p3_a_waiting_application_never_counts_a_switch_that_is_off_but_is_ready_only_once_it_is_on():
    for off_value in (None, False):          # unset, and explicitly off
        with _waiting_world(off_value) as (client, cfg, ids):
            body = client.get("/api/applicant").json()
            assert [w for w in body["waiting"] if "consents.group_sharing" in w["paths"]], \
                "the application is waiting on the switch (the Applications row says so)"
            assert "consents.group_sharing" not in body["needed_by"], "status line / section state"
            status = client.get("/api/apply/status").json()
            assert "consents.group_sharing" not in status["details_needed"], "the shell badge"
            assert "consents.group_sharing" not in status["details_needed_by"]
            assert _last(client, ids)["ready_to_retry"] is False
            assert not [w for w in body["waiting"] if w["ready"]]

            got = client.get("/api/applicant").json()
            edited = got["profile"]
            edited["consents"]["group_sharing"] = True
            r = client.put("/api/applicant", json={"profile": edited, "etag": got["etag"]})
            assert r.status_code == 200, r.text
            assert _last(client, ids)["ready_to_retry"] is True, "ready only after the switch is on"
            assert "consents.group_sharing" not in client.get("/api/applicant").json()["needed_by"]


def test_p3_an_ordinary_missing_detail_is_still_counted_beside_it():
    """Control: the exemption is the three switches only (a wrong exemption would hide real gaps)."""
    from test_q127_web import _world as app_world

    def blank(p):
        p["identity"]["date_of_birth"] = None
        for k in KEYS:
            p["consents"].pop(k.split(".", 1)[1], None)
    with app_world([], profile_edit=blank, reason="owner_fact_missing",
                   waiting_path="identity.date_of_birth") as (client, cfg, ids):
        assert "identity.date_of_birth" in client.get("/api/apply/status").json()["details_needed"]
        assert "identity.date_of_birth" in client.get("/api/applicant").json()["needed_by"]


# ---- P5: the model's briefing --------------------------------------------------------------------------

def _briefing_for(profile: dict) -> str:
    from jobscraper.apply import briefing as BR
    import llm_fill_t2 as T
    return BR.build(profile, T.rctx(profile), today="2026-11-12").text


def _sentence(text: str) -> str:
    start = text.index("Three consents are separate")
    return text[start:text.index(".", text.index("record checks", start)) + 1]


def test_p5_the_briefing_states_each_switch_yes_or_no_and_no_when_unset():
    from apply_flow_support import sample_profile as flow_profile
    unset = flow_profile()
    for k in KEYS:
        (unset.get("consents") or {}).pop(k.split(".", 1)[1], None)
    s = _sentence(_briefing_for(unset))
    assert s.count(": no") == 3 and ": yes" not in s, s
    for what in ("group of companies", "other companies", "background, reference and record checks"):
        assert what in s
    one = copy.deepcopy(unset)
    one["consents"]["third_party_sharing"] = True
    s1 = _sentence(_briefing_for(one))
    assert s1.count(": yes") == 1 and s1.count(": no") == 2
    assert s1.index("other companies") < s1.index(": yes") < s1.index("record checks"), s1
    allon = copy.deepcopy(unset)
    for k in KEYS:
        allon["consents"][k.split(".", 1)[1]] = True
    assert _sentence(_briefing_for(allon)).count(": yes") == 3


def test_p5_the_briefing_leaks_nothing_else_new_and_the_old_lines_are_unchanged():
    """Compare the briefing with the switches unset and all on: the ONLY lines that differ are the
    three profile lines of the switches (yes / not set) and the one sentence; no line is added, no
    key name or path appears in the sentence, no unrelated profile line moved."""
    from apply_flow_support import sample_profile as flow_profile
    a = flow_profile()
    for k in KEYS:
        (a.get("consents") or {}).pop(k.split(".", 1)[1], None)
    b = copy.deepcopy(a)
    for k in KEYS:
        b["consents"][k.split(".", 1)[1]] = True
    ta, tb = _briefing_for(a), _briefing_for(b)
    la, lb = ta.splitlines(), tb.splitlines()
    assert len(la) == len(lb), "no line was added or removed"
    changed = [(x, y) for x, y in zip(la, lb) if x != y]
    own = [(x, y) for x, y in changed if x.startswith("profile:consents.") and any(k in x for k in KEYS)]
    other = [pair for pair in changed if pair not in own]
    assert len(own) == 3, changed
    assert len(other) == 1 and "Three consents are separate" in other[0][0], other
    for x, y in own:
        assert x.endswith("(not set)") and y.endswith("| yes"), (x, y)
    sentence = _sentence(ta)
    for k in KEYS:
        assert k not in sentence and k.split(".", 1)[1] not in sentence, "no key name in the rule"
    assert "default_off" not in ta


# ---- P6: the filler's reader defaults to OFF -----------------------------------------------------------

def test_p6_the_filler_reads_the_third_party_key_with_absent_as_false():
    from jobscraper.apply import always
    assert always.SHARE_CONSENT_KEY == "consents.third_party_sharing" == KEYS[1]
    import inspect
    src = inspect.getsource(always.share_rule)
    assert "isinstance(v, bool) else False" in src, "an absent or non-bool key is False"
    # behaviour: an absent key gives truth False and a refusal key
    from apply_flow_support import sample_profile as flow_profile
    p = flow_profile()
    (p.get("consents") or {}).pop("third_party_sharing", None)
    assert applicant.get_path(p, always.SHARE_CONSENT_KEY) is None
    assert always.SHARE_DEFAULT_SOURCE.startswith("default:"), "the basis says it is a default"


def test_p6_the_other_two_switches_are_read_by_the_filler_RED_UNTIL_THE_CONSENTS_LANE_MERGES():
    """The group-sharing and background-checks keys are not read by always.py on this base (two
    engineers add them on other branches). A cheap pin: the module names both keys, and its
    protective default is False. Red until then, by design; do not weaken."""
    from jobscraper.apply import always
    text = Path(always.__file__).read_text(encoding="utf-8")
    for k in (KEYS[0], KEYS[2]):
        assert k in text or k.split(".", 1)[1] in text, f"always.py does not read {k} yet"
