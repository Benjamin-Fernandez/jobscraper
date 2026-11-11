"""Pin for Q-29: tier-2 excludes match at any label length (apply.resolve.Rule.score).

D-75 (WP-A04, 2026-11-10) replaced the four per-country rows of config/questions.yaml with two
`country_bool` rows that carry no country excludes: the resolver detects the country from the label
(`label_countries`) and answers from that country's value. The two synthetic exclude tests below still
pin `Rule.score`; the three real-file tests now pin the same guarantee under D-75: a question about
another country is never answered with the applicant's SINGAPORE work right.

The one-token rule of apply_design 7.1 ("email" must not match a long sentence) is for synonyms.
An exclude only ever removes a candidate, so a one-token exclude such as `uk` must also act on a
long label: "Are you legally authorised to work in the UK?" must never resolve to the Singapore row.
Fixed on `personal` (eng/Q-29-exclude-match); a branch that does not have that fix fails these.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from jobscraper.apply import resolve as R  # noqa: E402
from jobscraper.apply.plan import norm_label, tokens  # noqa: E402

QUESTIONS = ROOT / "config" / "questions.yaml"
AUTH_KEY = "singapore_status.authorised_to_work"
UK_LABEL = "Are you legally authorised to work in the UK?"
COUNTRIES = ["the UK", "Canada", "Australia", "India", "Germany", "Malaysia", "China", "Japan",
             "Argentina", "Europe", "the USA"]


def _rule(synonyms, exclude):
    return R.Rule(key="k", kind="bool", sensitive=False,
                  synonyms=tuple(tuple(tokens(s)) for s in synonyms),
                  exclude=tuple(tuple(tokens(x)) for x in exclude))


CODES = {"the UK": "GB", "Canada": "CA", "Australia": "AU", "India": "IN", "Germany": "DE",
         "Malaysia": "MY", "China": "CN", "Japan": "JP", "Argentina": "AR", "Europe": "EU", "the USA": "US"}


def _auth_rule():
    rules = R.QuestionRules.load(QUESTIONS)
    return next(r for r in rules.rules if r.key == AUTH_KEY)


def _ask(label, authorised, **kw):
    """The label through the real resolver over the real rules file; the model must not be asked."""
    from questions_support import StubBackend, profile, resolve_one, with_work_rights, yes_no
    spy = StubBackend([{"choice": 0, "evidence": "x"}] * 4)
    prof = with_work_rights(authorised, {"SG": False, "default": False}, base=profile())
    a = resolve_one(yes_no("q", label), prof, QUESTIONS, backend=spy, **kw)
    assert spy.calls == [], f"the model must not be asked for {label!r}"
    return a


def test_a_one_token_exclude_scores_zero_on_a_label_of_five_tokens_or_more():
    r = _rule(["legally authorised to work"], ["uk"])
    long_label = tokens(UK_LABEL)
    assert len(long_label) >= 5
    assert r.score(long_label) == 0, "the `uk` exclude must act on a long label (Q-29)"
    assert r.score(tokens("Authorised to work uk")) == 0, "and still on a short one"
    assert r.score(tokens("Are you legally authorised to work in Singapore?")) == 4, \
        "no exclude matches: the synonym scores its token count"


def test_an_exclude_needs_a_whole_token_run_not_a_substring():
    r = _rule(["legally authorised to work"], ["uk"])
    assert r.score(tokens("Are you legally authorised to work in Dundee, Ukraine or Luke's Place?")) == 4, \
        "'uk' inside 'ukraine' is not the token uk"
    r2 = _rule(["legally authorised to work"], ["united kingdom"])
    assert r2.score(tokens("Are you legally authorised to work in the United Kingdom now?")) == 0
    assert r2.score(tokens("Are you legally authorised to work in the united states now?")) == 4


def test_a_label_naming_another_country_resolves_to_the_country_row_for_that_country_never_sg():
    """(a) The UK question selects the country_bool row; the country comes out as GB, and the answer is
    the UK value (here No) although the Singapore value is Yes. Same for every other country."""
    rules = R.QuestionRules.load(QUESTIONS)
    chosen, _score = rules.select(norm_label(UK_LABEL))
    assert [r.key for r in chosen] == [AUTH_KEY] and chosen[0].kind == "country_bool"
    assert R.label_countries(norm_label(UK_LABEL)) == {"GB"}
    for c in COUNTRIES:
        label = f"Are you legally authorised to work in {c}?"
        code = CODES[c]
        assert R.label_countries(norm_label(label)) == {code}, label
        a = _ask(label, {"SG": True, code: False})             # SG says Yes; the named country says No
        assert a.rule_id == AUTH_KEY and a.value is not None, (label, a)
        assert a.source == f"profile:{AUTH_KEY}.{code}", (label, a.source)
        assert tuple(a.option_labels) == ("No",), (label, a.option_labels)


def test_a_country_with_no_value_of_its_own_takes_the_default_or_standing_answer_never_the_sg_key():
    """The UK question with a map that only has SG: the answer comes from `default` / the standing
    answer (source says so), never from the SG key."""
    a = _ask(UK_LABEL, {"SG": False})                           # standing answer is Yes; SG's own is No
    assert a.source == f"profile:{AUTH_KEY}.standing", a.source
    assert tuple(a.option_labels) == ("Yes",), a.option_labels
    b = _ask(UK_LABEL, {"SG": True, "default": False})
    assert b.source == f"profile:{AUTH_KEY}.default" and tuple(b.option_labels) == ("No",), (b.source, b.option_labels)


def test_the_singapore_labels_still_resolve_to_the_row_with_country_sg():
    """(b) Singapore, "the country where you live" (residence country SG in the sample), a label naming
    no country (the job's, SG) and "right to work in Singapore" are all answered from the SG key; the
    map's default and the US key say No, so only the SG key can give Yes."""
    rules = R.QuestionRules.load(QUESTIONS)
    for label in ("Are you legally authorised to work in Singapore?",
                  "Are you legally authorized to work in the country where you live?",
                  "Do you have the right to work in Singapore?",
                  "Work authorisation"):
        chosen, _ = rules.select(norm_label(label))
        assert [r.key for r in chosen] == [AUTH_KEY], label
        a = _ask(label, {"SG": True, "US": False, "default": False})
        assert a.rule_id == AUTH_KEY and a.source == f"profile:{AUTH_KEY}.SG", (label, a.source)
        assert tuple(a.option_labels) == ("Yes",), (label, a.option_labels)


def test_the_country_row_has_no_country_excludes_the_country_is_detected_not_excluded():
    """(c) Replaces "the UK question stays off the SG row even with the `in` excludes stripped": under
    D-75 the row carries no country excludes at all (nothing to strip), so the guarantee is the
    detection pinned above. Here: the real rows are `country_bool`, exclude-free for the authorised
    row, and the sponsorship row excludes only `without`."""
    rules = R.QuestionRules.load(QUESTIONS)
    by_key = {r.key: r for r in rules.rules}
    auth = by_key[AUTH_KEY]
    spons = by_key["singapore_status.requires_sponsorship"]
    assert auth.kind == spons.kind == "country_bool"
    assert auth.exclude == (), auth.exclude
    assert spons.exclude == (("without",),), spons.exclude
    assert not [k for k in by_key if k.startswith(AUTH_KEY + ".")], "no per-country keys remain"
