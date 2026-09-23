"""The companies to monitor, and the rules for keeping them in sync.

`config/watchlist.yaml` is the source of truth for *which* companies exist; the
`companies` table is the source of truth for their *history* - staleness, failure
counts, quarantine. This module loads and validates the file and defines the
identity rules that let the two be reconciled without losing history.

Rows are keyed on `key`, a stable slug, never on the display name. Renaming a
company in the YAML must not reset its scrape history or orphan its failure
counters, and a display name is not a stable identifier.

A minimal entry is two lines:

    - name: Jane Street
      careers_url: https://www.janestreet.com/join-jane-street/open-roles/

Everything else is optional and may be written back by discovery.

Validation errors carry the line number, because a 229-entry file is not
something you want to bisect by hand.

Replaces v1's ingest.py, which read a three-sheet Excel workbook.

See PRD section 8.4.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

import yaml

# src/jobscraper/watchlist.py -> src/jobscraper -> src -> <root>
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "config" / "watchlist.yaml"

# Fields an entry may carry. Anything else is a typo, and saying so beats
# silently ignoring it - a misspelled `carers_url` would otherwise scrape
# nothing and look like a network problem.
KNOWN_FIELDS = {"key", "name", "careers_url", "provider", "slug", "feed_url",
                "enabled", "notes"}

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


class WatchlistError(ValueError):
    """The watchlist file is unusable. The message says which entry and line."""


@dataclass
class WatchlistEntry:
    """One company to monitor. `key` is identity; everything else can change."""

    key: str
    name: str
    careers_url: str
    provider: Optional[str] = None
    slug: Optional[str] = None
    feed_url: Optional[str] = None
    enabled: bool = True
    notes: str = ""
    line: int = 0                       # where it sits in the file, for errors

    def as_dict(self, include_learned: bool = True) -> dict[str, Any]:
        """The entry as YAML-ready data, omitting anything left at its default."""
        out: dict[str, Any] = {"name": self.name, "careers_url": self.careers_url}
        if self.key != slugify(self.name):
            out["key"] = self.key
        if include_learned:
            for f in ("provider", "slug", "feed_url"):
                v = getattr(self, f)
                if v:
                    out[f] = v
        if not self.enabled:
            out["enabled"] = False
        if self.notes:
            out["notes"] = self.notes
        return out


def slugify(name: str) -> str:
    """A stable key from a display name: 'Google / DeepMind' -> 'google-deepmind'."""
    return _SLUG_STRIP.sub("-", (name or "").strip().lower()).strip("-")


class _LineLoader(yaml.SafeLoader):
    """SafeLoader that records the source line of every mapping."""


def _mapping_with_line(loader: _LineLoader, node: yaml.MappingNode) -> dict:
    mapping = yaml.SafeLoader.construct_mapping(loader, node, deep=True)
    # 1-based, to match what an editor shows.
    mapping["__line__"] = node.start_mark.line + 1
    return mapping


_LineLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_with_line)


def _at(line: int) -> str:
    return f" (line {line})" if line else ""


def _str_field(raw: dict, key: str, line: int, label: str) -> Optional[str]:
    v = raw.get(key)
    if v is None:
        return None
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        raise WatchlistError(
            f"{label}: `{key}` must be text, got {type(v).__name__}{_at(line)}")
    v = str(v).strip()
    return v or None


def parse(raw_text: str, source: str = "watchlist.yaml") -> list[WatchlistEntry]:
    """Validate watchlist YAML text into entries. Raises WatchlistError."""
    try:
        doc = yaml.load(raw_text, Loader=_LineLoader)
    except yaml.YAMLError as exc:
        raise WatchlistError(f"{source} is not valid YAML: {exc}") from exc

    if doc is None:
        raise WatchlistError(f"{source} is empty")
    if not isinstance(doc, dict):
        raise WatchlistError(
            f"{source} must be a mapping with a `companies:` list, "
            f"got {type(doc).__name__}")

    companies = doc.get("companies")
    if companies is None:
        raise WatchlistError(f"{source} has no `companies:` list")
    if not isinstance(companies, list):
        raise WatchlistError(
            f"{source}: `companies` must be a list, got {type(companies).__name__}")

    entries: list[WatchlistEntry] = []
    by_key: dict[str, WatchlistEntry] = {}
    by_name: dict[str, WatchlistEntry] = {}

    for index, raw in enumerate(companies, start=1):
        if not isinstance(raw, dict):
            raise WatchlistError(
                f"{source}: entry #{index} must be a mapping with at least "
                f"`name` and `careers_url`, got {type(raw).__name__}")

        raw = dict(raw)                                  # never mutate the caller's data
        line = int(raw.pop("__line__", 0) or 0)
        label = f"{source}: entry #{index}"

        unknown = set(raw) - KNOWN_FIELDS
        if unknown:
            raise WatchlistError(
                f"{label} has unknown field(s) {sorted(unknown)}{_at(line)}. "
                f"Known fields: {sorted(KNOWN_FIELDS)}")

        name = _str_field(raw, "name", line, label)
        if not name:
            raise WatchlistError(f"{label} has no `name`{_at(line)}")
        label = f"{source}: {name!r}"

        careers_url = _str_field(raw, "careers_url", line, label)
        if not careers_url:
            raise WatchlistError(f"{label} has no `careers_url`{_at(line)}")
        parsed = urlparse(careers_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise WatchlistError(
                f"{label}: `careers_url` must be an http(s) URL, got "
                f"{careers_url!r}{_at(line)}")

        key = _str_field(raw, "key", line, label) or slugify(name)
        if not key:
            raise WatchlistError(
                f"{label}: cannot derive a key from this name; set `key:` "
                f"explicitly{_at(line)}")

        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise WatchlistError(
                f"{label}: `enabled` must be true or false, got "
                f"{enabled!r}{_at(line)}")

        entry = WatchlistEntry(
            key=key,
            name=name,
            careers_url=careers_url,
            provider=_str_field(raw, "provider", line, label),
            slug=_str_field(raw, "slug", line, label),
            feed_url=_str_field(raw, "feed_url", line, label),
            enabled=enabled,
            notes=_str_field(raw, "notes", line, label) or "",
            line=line)

        # Identity must be unique, or the database sync in M3-T1b would merge
        # two companies into one row and silently lose one of them.
        clash = by_key.get(entry.key)
        if clash is not None:
            raise WatchlistError(
                f"{source}: duplicate key {entry.key!r} - {clash.name!r}"
                f"{_at(clash.line)} and {entry.name!r}{_at(entry.line)}. "
                "Set an explicit `key:` on one of them.")
        clash = by_name.get(entry.name.lower())
        if clash is not None:
            raise WatchlistError(
                f"{source}: duplicate name {entry.name!r}"
                f"{_at(clash.line)} and{_at(entry.line)}")

        by_key[entry.key] = entry
        by_name[entry.name.lower()] = entry
        entries.append(entry)

    if not entries:
        raise WatchlistError(f"{source}: `companies` is empty")
    return entries


def load(path: Optional[Path] = None) -> list[WatchlistEntry]:
    """Read and validate the watchlist. Raises WatchlistError."""
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        raise WatchlistError(
            f"{p} not found. Generate it with `python scripts/seed_watchlist.py`, "
            "or write it by hand - a minimal entry is a name and a careers_url.")
    return parse(p.read_text(encoding="utf-8"), source=p.name)


def enabled_only(entries: Iterable[WatchlistEntry]) -> list[WatchlistEntry]:
    return [e for e in entries if e.enabled]


def render_entry(entry: WatchlistEntry) -> str:
    """One entry as a YAML list item.

    Rendering per entry rather than dumping the whole document is deliberate: it
    lets `watchlist add` (M1-T5) append text to the file without re-serialising
    it, so hand-written comments and key order survive.
    """
    data = entry.as_dict()
    lines = [f"  - name: {_scalar(data['name'])}"]
    for k in ("key", "careers_url", "provider", "slug", "feed_url", "enabled",
              "notes"):
        if k in data:
            lines.append(f"    {k}: {_scalar(data[k])}")
    return "\n".join(lines)


def _scalar(v: Any) -> str:
    """Quote only when YAML would otherwise misread the value."""
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v)
    if not s:
        return '""'
    needs_quotes = (
        s[0] in "&*?|-<>=!%@`{[\"'#"
        or s.strip() != s
        or ": " in s
        or s.endswith(":")
        or s.lower() in ("true", "false", "null", "yes", "no", "on", "off", "~")
    )
    if needs_quotes:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s
