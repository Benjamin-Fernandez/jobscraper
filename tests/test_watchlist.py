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


# ---------------------------------------------------------------- M1-T5 verbs
#
# `add` and `disable` edit a hand-written file. The contract is that they change
# only what they were asked to change: every comment, blank line, key order and
# line ending elsewhere in the file comes through byte for byte.

COMMENTED = """\
# The companies JobScraper watches.
#   a hand-written header the user cares about
version: 1
companies:
  - name: Alpha
    careers_url: https://alpha.example/careers   # trailing comment
    provider: greenhouse
    slug: alpha

  # a comment between entries
  - name: Beta
    careers_url: https://beta.example/careers
    enabled: true        # keep an eye on this one
    notes: |
      multi-line note
      enabled: not a real key
"""


def _tmp_watchlist(text: str = COMMENTED, newline: str = "\n") -> Path:
    p = Path(tempfile.mkdtemp()) / "watchlist.yaml"
    p.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return p


def _refused(fn, *args, needles=(), **kw) -> str:
    try:
        fn(*args, **kw)
    except WatchlistError as exc:
        for n in needles:
            assert n in str(exc), f"message should mention {n!r}, got: {exc}"
        return str(exc)
    raise AssertionError(f"{fn.__name__}{args} should have been refused")


def test_add_appends_a_minimal_entry_and_every_comment_survives():
    """The M1-T5 Verify: add to a temp file, reload, new entry valid, comments kept."""
    from jobscraper.watchlist import add_entry
    p = _tmp_watchlist()
    added = add_entry(p, "Jane Street",
                      "https://www.janestreet.com/join-jane-street/open-roles/")
    assert added.key == "jane-street"

    after = p.read_text(encoding="utf-8")
    assert after.startswith(COMMENTED), "the existing text must be untouched"
    tail = after[len(COMMENTED):].strip("\n")
    assert tail == ("  - name: Jane Street\n    careers_url: "
                    "https://www.janestreet.com/join-jane-street/open-roles/"), (
        f"expected a two-line minimal entry, got:\n{tail}")

    entries = load(p)                              # re-validates the whole file
    assert [e.key for e in entries] == ["alpha", "beta", "jane-street"]
    assert entries[-1].enabled and entries[-1].provider is None
    for comment in ("# The companies JobScraper watches.", "# trailing comment",
                    "# a comment between entries", "# keep an eye on this one"):
        assert comment in after


def test_add_keeps_crlf_line_endings():
    """The real file is CRLF on Windows checkouts; a mixed file is a noisy diff."""
    from jobscraper.watchlist import add_entry
    p = _tmp_watchlist(newline="\r\n")
    original = p.read_bytes()
    add_entry(p, "Gamma", "https://gamma.example/jobs")
    raw = p.read_bytes()
    assert raw.startswith(original)
    assert b"\n" not in raw.replace(b"\r\n", b""), "a bare LF crept in"
    assert [e.name for e in load(p)][-1] == "Gamma"


def test_add_quotes_a_name_containing_a_hash():
    """' #' starts a YAML comment: unquoted, "Acme #1 Corp" would reload as "Acme"
    (found by the M9 code review)."""
    from jobscraper.watchlist import add_entry
    p = _tmp_watchlist()
    add_entry(p, "Acme #1 Corp", "https://acme.example/careers")
    assert [e.name for e in load(p)][-1] == "Acme #1 Corp"


def test_add_takes_an_explicit_key():
    from jobscraper.watchlist import add_entry
    p = _tmp_watchlist()
    add_entry(p, "Alpha Asia", "https://asia.alpha.example/careers", key="alpha-sg")
    assert load(p)[-1].key == "alpha-sg"


def test_add_refuses_a_duplicate_with_the_loader_error_and_writes_nothing():
    from jobscraper.watchlist import add_entry
    p = _tmp_watchlist()
    before = p.read_bytes()
    msg = _refused(add_entry, p, "alpha", "https://other.example/jobs",
                   needles=("duplicate", "alpha"))
    assert msg.count("line") >= 2, f"should cite both lines, got: {msg}"
    _refused(add_entry, p, "Beta", "https://b2.example/jobs", key="beta-2",
             needles=("duplicate name",))
    assert p.read_bytes() == before, "a refused add must leave the file untouched"


def test_add_refuses_an_invalid_entry_and_writes_nothing():
    from jobscraper.watchlist import add_entry
    p = _tmp_watchlist()
    before = p.read_bytes()
    _refused(add_entry, p, "Delta", "delta.example/jobs", needles=("careers_url",))
    _refused(add_entry, p, "", "https://x.example/jobs", needles=("name",))
    _refused(add_entry, p, "Two\nLines", "https://x.example/jobs")
    assert p.read_bytes() == before


def test_add_refuses_when_companies_is_not_the_last_block():
    """Appending text is only safe at the end of `companies:`. If something else
    follows it, the entry would land in the wrong place - refuse, do not guess."""
    from jobscraper.watchlist import add_entry
    p = _tmp_watchlist(COMMENTED + "extra:\n")
    before = p.read_bytes()
    _refused(add_entry, p, "Gamma", "https://gamma.example/jobs",
             needles=("companies",))
    assert p.read_bytes() == before


def test_add_matches_the_files_own_list_indent():
    from jobscraper.watchlist import add_entry
    p = _tmp_watchlist("companies:\n- name: Alpha\n  careers_url: https://a.example/c\n")
    add_entry(p, "Gamma", "https://gamma.example/jobs")
    assert p.read_text(encoding="utf-8").endswith(
        "\n- name: Gamma\n  careers_url: https://gamma.example/jobs\n")
    assert [e.name for e in load(p)] == ["Alpha", "Gamma"]


def test_add_refuses_to_touch_an_already_broken_file():
    from jobscraper.watchlist import add_entry
    p = _tmp_watchlist("companies:\n  - name: Alpha\n")
    _refused(add_entry, p, "Gamma", "https://gamma.example/jobs",
             needles=("careers_url",))


def _changed_lines(before: str, after: str) -> list[tuple[str, str]]:
    import difflib
    sm = difflib.SequenceMatcher(a=before.splitlines(), b=after.splitlines())
    return [(" | ".join(before.splitlines()[i1:i2]), " | ".join(after.splitlines()[j1:j2]))
            for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]


def test_disable_inserts_enabled_false_and_changes_nothing_else():
    from jobscraper.watchlist import disable_entry
    p = _tmp_watchlist()
    entry, changed = disable_entry(p, "alpha")
    assert changed and entry.key == "alpha"
    after = p.read_text(encoding="utf-8")
    assert _changed_lines(COMMENTED, after) == [("", "    enabled: false")], (
        f"only one inserted line expected:\n{after}")
    by_key = {e.key: e for e in load(p)}
    assert by_key["alpha"].enabled is False
    assert by_key["beta"].enabled is True
    assert by_key["alpha"].provider == "greenhouse", "other fields untouched"


def test_disable_flips_an_existing_enabled_line_and_keeps_its_comment():
    from jobscraper.watchlist import disable_entry
    p = _tmp_watchlist()
    disable_entry(p, "Beta")                       # an exact name works too
    after = p.read_text(encoding="utf-8")
    assert _changed_lines(COMMENTED, after) == [
        ("    enabled: true        # keep an eye on this one",
         "    enabled: false        # keep an eye on this one")]
    beta = {e.key: e for e in load(p)}["beta"]
    assert beta.enabled is False
    assert "enabled: not a real key" in beta.notes, "block-scalar text untouched"


def test_disable_keeps_crlf_and_handles_the_last_line_without_a_newline():
    from jobscraper.watchlist import disable_entry
    p = _tmp_watchlist("companies:\n  - name: Alpha\n    careers_url: https://a.example/c",
                       newline="\r\n")
    disable_entry(p, "alpha")
    raw = p.read_bytes()
    assert b"\n" not in raw.replace(b"\r\n", b""), "a bare LF crept in"
    assert load(p)[0].enabled is False


def test_disable_is_a_no_op_on_a_disabled_entry():
    from jobscraper.watchlist import disable_entry
    p = _tmp_watchlist()
    disable_entry(p, "beta")
    before = p.read_bytes()
    entry, changed = disable_entry(p, "beta")
    assert changed is False and entry.enabled is False
    assert p.read_bytes() == before


def test_disable_refuses_an_unknown_key():
    from jobscraper.watchlist import disable_entry
    p = _tmp_watchlist()
    before = p.read_bytes()
    _refused(disable_entry, p, "nope", needles=("nope",))
    assert p.read_bytes() == before


def test_disable_refuses_a_flow_style_entry_rather_than_mangling_it():
    from jobscraper.watchlist import disable_entry
    text = "companies:\n  - {name: Alpha, careers_url: 'https://a.example/c'}\n"
    p = _tmp_watchlist(text)
    _refused(disable_entry, p, "alpha")
    assert p.read_text(encoding="utf-8") == text


def _cli(*argv: str) -> tuple[int, str, str]:
    import contextlib
    import io
    from jobscraper.cli import main
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def test_watchlist_cli_list_add_disable_round_trip():
    p = _tmp_watchlist()
    code, out, _ = _cli("watchlist", "list", "--file", str(p))
    assert code == 0
    assert out.strip().splitlines()[-1] == "2 companies, 2 enabled"
    assert "greenhouse" in out and "Beta" in out

    code, out, _ = _cli("watchlist", "add", "Gamma", "https://gamma.example/jobs",
                        "--file", str(p))
    assert code == 0 and "gamma" in out
    code, out, _ = _cli("watchlist", "disable", "alpha", "--file", str(p))
    assert code == 0 and "disabled" in out

    code, out, _ = _cli("watchlist", "list", "--file", str(p))
    assert out.strip().splitlines()[-1] == "3 companies, 2 enabled"


def test_watchlist_cli_reports_a_refusal_on_stderr_with_exit_1():
    p = _tmp_watchlist()
    before = p.read_bytes()
    code, out, err = _cli("watchlist", "add", "Alpha", "https://x.example/jobs",
                          "--file", str(p))
    assert code == 1 and "duplicate" in err
    code, _, err = _cli("watchlist", "disable", "nope", "--file", str(p))
    assert code == 1 and "nope" in err
    assert p.read_bytes() == before
