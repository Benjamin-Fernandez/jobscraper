"""The watchlist file: what it accepts, and what it refuses to accept quietly.

Most of these are rejection tests. That is the point - this file is hand-edited,
so the failure mode that matters is a typo the loader shrugs off, leaving a
company silently unscraped and looking like a network problem.

PRD section 8.4 and task M1-T1.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobscraper.watchlist import (WatchlistEntry, WatchlistError,  # noqa: E402
                                  enabled_only, load, parse, render_entry,
                                  slugify)

MINIMAL = """
version: 1
companies:
  - name: Jane Street
    careers_url: https://www.janestreet.com/join-jane-street/open-roles/
"""


def _refuses(text: str, *needles: str) -> str:
    """Assert parse() rejects this text, and that the message is useful."""
    try:
        parse(text)
    except WatchlistError as exc:
        msg = str(exc)
        for n in needles:
            assert n in msg, f"message should mention {n!r}, got: {msg}"
        return msg
    raise AssertionError(f"should have been refused: {text!r}")


# ---------------------------------------------------------------- accepting


def test_two_lines_is_a_valid_entry():
    """The whole point of replacing the spreadsheet: adding a company is trivial."""
    entries = parse(MINIMAL)
    assert len(entries) == 1
    e = entries[0]
    assert e.name == "Jane Street"
    assert e.careers_url.startswith("https://")
    assert e.key == "jane-street", "key defaults to a slug of the name"
    assert e.enabled is True, "entries are enabled unless they say otherwise"
    assert e.provider is None and e.slug is None and e.feed_url is None


def test_optional_fields_are_read_when_present():
    entries = parse("""
companies:
  - name: OKX
    key: okx-global
    careers_url: https://www.okx.com/careers
    provider: greenhouse
    slug: okx
    feed_url: https://boards-api.greenhouse.io/v1/boards/okx/jobs
    enabled: false
    notes: SG office confirmed
""")
    e = entries[0]
    assert e.key == "okx-global", "an explicit key overrides the slug"
    assert (e.provider, e.slug) == ("greenhouse", "okx")
    assert e.feed_url.endswith("/jobs")
    assert e.enabled is False
    assert e.notes == "SG office confirmed"


def test_enabled_only_filters_disabled_companies():
    entries = parse("""
companies:
  - name: Alpha
    careers_url: https://alpha.example/careers
  - name: Beta
    careers_url: https://beta.example/careers
    enabled: false
""")
    assert [e.name for e in enabled_only(entries)] == ["Alpha"]


def test_slugify_handles_the_awkward_real_names():
    # These are real entries from the v1 workbook.
    assert slugify("Google / DeepMind") == "google-deepmind"
    assert slugify("Shopee / Sea Group") == "shopee-sea-group"
    assert slugify("JD.com") == "jd-com"
    assert slugify("Alibaba / AliCloud") == "alibaba-alicloud"
    assert slugify("  OKX  ") == "okx"


# ---------------------------------------------------------------- refusing


def test_duplicate_entry_is_refused_and_names_both_lines():
    """The same company twice. Caught on key, since equal names slug equally."""
    msg = _refuses("""
companies:
  - name: Stripe
    careers_url: https://stripe.com/jobs
  - name: Stripe
    careers_url: https://stripe.com/careers
""", "duplicate", "Stripe", "line")
    # Both offenders must be locatable, not just the second one - otherwise you
    # are searching 229 entries for the first half of the problem.
    assert msg.count("line") >= 2, f"should cite both lines, got: {msg}"


def test_duplicate_name_is_refused_even_when_keys_differ():
    """Distinct keys get past the key check; the name is still ambiguous."""
    msg = _refuses("""
companies:
  - name: Stripe
    key: stripe-one
    careers_url: https://stripe.com/jobs
  - name: Stripe
    key: stripe-two
    careers_url: https://stripe.com/careers
""", "duplicate name", "Stripe", "line")
    assert msg.count("line") >= 2, f"should cite both lines, got: {msg}"


def test_duplicate_key_is_refused_even_when_names_differ():
    """Two names that slug to the same key would merge into one database row."""
    _refuses("""
companies:
  - name: Jane Street
    careers_url: https://a.example/careers
  - name: jane street
    careers_url: https://b.example/careers
""", "duplicate")


def test_malformed_url_is_refused():
    for bad in ("janestreet.com/careers", "ftp://x.example/jobs", "not a url", ""):
        _refuses(f"""
companies:
  - name: Test Co
    careers_url: {bad!r}
""", "careers_url")


def test_missing_required_fields_are_refused():
    _refuses("companies:\n  - careers_url: https://x.example/careers\n", "name")
    _refuses("companies:\n  - name: Test Co\n", "careers_url")


def test_a_typo_in_a_field_name_is_refused_not_ignored():
    """The failure this guards: `carers_url` scrapes nothing and looks like a 404."""
    _refuses("""
companies:
  - name: Test Co
    careers_url: https://x.example/careers
    carers_url: https://x.example/oops
""", "unknown field", "carers_url")


def test_structural_problems_are_refused_with_a_clear_message():
    _refuses("", "empty")
    _refuses("companies: []\n", "empty")
    _refuses("version: 1\n", "companies")
    _refuses("companies: not-a-list\n", "must be a list")
    _refuses("- name: Test\n", "mapping")
    _refuses("companies:\n  - just a string\n", "mapping")
    _refuses("companies:\n  - name: X\n    careers_url: https://x.example/c\n"
             "    enabled: yeah\n", "enabled")


def test_broken_yaml_says_so_rather_than_crashing():
    _refuses("companies:\n  - name: [unclosed\n", "not valid YAML")


# ---------------------------------------------------------------- round trip


def test_load_reads_a_real_file_and_reports_a_missing_one():
    tmp = Path(tempfile.mkdtemp()) / "watchlist.yaml"
    tmp.write_text(MINIMAL, encoding="utf-8")
    assert [e.name for e in load(tmp)] == ["Jane Street"]

    missing = tmp.parent / "nope.yaml"
    try:
        load(missing)
        raise AssertionError("a missing watchlist must be an error, not an empty list")
    except WatchlistError as exc:
        assert "seed_watchlist" in str(exc), "the error should say how to fix it"


def test_rendered_entries_parse_back_to_the_same_values():
    """render_entry feeds `watchlist add`; anything it writes must be readable."""
    original = parse("""
companies:
  - name: Grab
    careers_url: https://grab.careers/jobs
    provider: workday
    slug: grab
    enabled: false
    notes: "tricky: colon in a note"
""")[0]
    text = "companies:\n" + render_entry(original)
    back = parse(text)[0]
    for field in ("key", "name", "careers_url", "provider", "slug", "enabled",
                  "notes"):
        assert getattr(back, field) == getattr(original, field), (
            f"{field} did not survive the round trip: "
            f"{getattr(original, field)!r} -> {getattr(back, field)!r}")


def test_rendering_omits_defaults_so_a_minimal_entry_stays_minimal():
    e = WatchlistEntry(key="grab", name="Grab",
                       careers_url="https://grab.careers/jobs")
    text = render_entry(e)
    assert "key:" not in text, "a key equal to the slug is noise"
    assert "enabled:" not in text, "enabled is the default"
    assert "notes:" not in text
    assert text.count("\n") == 1, f"expected a two-line entry, got:\n{text}"
