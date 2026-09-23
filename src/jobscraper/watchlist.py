"""The companies to monitor, and the rules for keeping them in sync.

`config/watchlist.yaml` is the source of truth for *which* companies exist; the
`companies` table is the source of truth for their *history* - staleness, failure
counts, quarantine. This module loads and validates the file and defines the
identity rules that let the two be reconciled without losing history.

Rows are keyed on `key`, a stable slug, never on the display name. Renaming a
company in the YAML must not reset its scrape history or orphan its failure
counters, and a display name is not a stable identifier.

Replaces v1's ingest.py, which read a three-sheet Excel workbook.

See PRD section 8.4.
"""
