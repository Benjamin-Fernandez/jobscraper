"""Pin for Q-29: tier-2 excludes match at any label length (apply.resolve.Rule.score).

The one-token rule of apply_design 7.1 ("email" must not match a long sentence) is for synonyms.
An exclude only ever removes a candidate, so a one-token exclude such as `uk` must also act on a
long label: "Are you legally authorised to work in the UK?" must never resolve to the Singapore row.
Fixed on `personal` (eng/Q-29-exclude-match); a branch that does not have that fix fails these.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobscraper.apply import resolve as R  # noqa: E402
from jobscraper.apply.plan import norm_label, tokens  # noqa: E402

QUESTIONS = ROOT / "config" / "questions.yaml"
SG_KEY = "singapore_status.authorised_to_work.SG"
UK_LABEL = "Are you legally authorised to work in the UK?"
COUNTRIES = ["the UK", "Canada", "Australia", "India", "Germany", "Malaysia", "China", "Japan",
             "Argentina", "Europe", "the USA"]


def _rule(synonyms, exclude):
    return R.Rule(key="k", kind="bool", sensitive=False,
                  synonyms=tuple(tuple(tokens(s)) for s in synonyms),
                  exclude=tuple(tuple(tokens(x)) for x in exclude))


def _sg_rule():
    rules = R.QuestionRules.load(QUESTIONS)
    return next(r for r in rules.rules if r.key == SG_KEY)


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


def test_the_singapore_row_never_answers_a_long_label_naming_another_country():
    sg = _sg_rule()
    for c in COUNTRIES:
        label = f"Are you legally authorised to work in {c}?"
        assert sg.score(tokens(label)) == 0, label
    rules = R.QuestionRules.load(QUESTIONS)
    chosen, score = rules.select(norm_label(UK_LABEL))
    assert SG_KEY not in [r.key for r in chosen], "the UK question must not resolve to the SG row"


def test_the_uk_question_stays_off_the_sg_row_even_with_the_in_country_excludes_stripped():
    sg = _sg_rule()
    stripped = dataclasses.replace(sg, exclude=tuple(x for x in sg.exclude if x[0] != "in"))
    assert len(stripped.exclude) < len(sg.exclude) or not any(x[0] == "in" for x in sg.exclude)
    for c in COUNTRIES:
        if c == "the USA":
            continue                                      # `usa` is a one-token exclude too, but see below
        label = f"Are you legally authorised to work in {c}?"
        assert stripped.score(tokens(label)) == 0, \
            f"only the one-token exclude is left, and it must still act: {label}"
    assert stripped.score(tokens("Are you legally authorised to work in the USA?")) == 0
    assert stripped.score(tokens(UK_LABEL)) == 0


def test_the_singapore_row_still_answers_its_own_questions():
    sg = _sg_rule()
    for label in ("Are you legally authorised to work in Singapore?",
                  "Are you legally authorized to work in the country where you live?",
                  "Do you have the right to work in Singapore?",
                  "Work authorisation"):
        assert sg.score(tokens(label)) > 0, label
