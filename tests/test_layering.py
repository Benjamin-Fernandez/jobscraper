"""The module boundaries from PRD section 8.2, enforced instead of hoped for.

A layered design decays quietly. Someone needs one value from another stage,
adds an import, and three days later the stages cannot be tested apart any more.
This test reads every module's imports with `ast` - no importing, no executing -
and fails the moment a boundary is crossed.

The rules, in the order they matter:

  1. store.py imports no stage module. It is the bottom of the stack; if data
     access reaches upwards, nothing above it can be tested in isolation.
  2. Stage modules do not import each other. pipeline.py composes them. This is
     what lets the order change without editing the stages.
  3. web/ imports no stage module. The web app reads what the pipeline already
     decided; it never re-runs a decision.
  4. Only store.py contains SQL. That single fact is what makes the Postgres
     path in PRD section 8.4 one module's work instead of a search-and-replace.
  5. backends.py is the only module that talks to a model.
  6. Nothing imports pipeline.py. It is the top of the stack; an import of it
     from below is a cycle waiting to happen.

Rules are checked against the v2 modules only. v1 modules still in the tree are
listed in LEGACY and skipped - they are retired by M9-T1, and failing on them
now would just mean a permanently red test with no action attached.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "jobscraper"
sys.path.insert(0, str(ROOT / "src"))

# The orchestrator. The one module allowed to import every stage - composing them
# is its whole job. Nothing may import it back.
ORCHESTRATOR = {"pipeline"}

# Stage modules: each does one step of the pipeline and knows nothing of the others.
STAGES = {"scheduler", "filter", "decide", "scrape", "profile"}

# Not a stage. shortlist.py only turns stored decisions into a file, which is why
# both pipeline.py and web/ are allowed to import it (PRD section 8.2).
PUBLISHER = {"shortlist"}

FOUNDATION = {"store", "config", "models", "net", "backends", "watchlist"}

WEB_MAY_IMPORT = FOUNDATION | PUBLISHER

# v1 modules awaiting retirement in M9-T1. Excluded from the rules on purpose.
LEGACY = {"runner", "output", "serve", "ingest", "cursor", "matching", "llm",
          "review", "adapters", "discovery", "cli", "__main__", "__init__"}

SQL_TOKENS = ("SELECT ", "INSERT ", "UPDATE ", "DELETE FROM", "CREATE TABLE")


def _local_imports(path: Path) -> set[str]:
    """Names of sibling jobscraper modules this file imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # `from .filter import x` / `from jobscraper.filter import x`
            if node.level:                       # relative
                if node.module:
                    found.add(node.module.split(".")[0])
                else:                            # `from . import filter`
                    found.update(a.name.split(".")[0] for a in node.names)
            elif (node.module or "").startswith("jobscraper"):
                parts = node.module.split(".")
                if len(parts) > 1:
                    found.add(parts[1])
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("jobscraper."):
                    found.add(a.name.split(".")[1])
    return found


def _all_v2_files() -> list[tuple[str, Path]]:
    """Every v2 source file, paired with the layer name it belongs to."""
    files = []
    for p in sorted(SRC.rglob("*.py")):
        rel = p.relative_to(SRC)
        owner = rel.parts[0] if len(rel.parts) > 1 else p.stem
        if len(rel.parts) == 1 and p.stem in LEGACY:
            continue
        files.append((owner, p))
    return files


def test_store_never_imports_a_stage():
    store = SRC / "store.py"
    if not store.exists():
        return
    bad = _local_imports(store) & (STAGES | PUBLISHER)
    assert not bad, (
        f"store.py imports {sorted(bad)} - data access must not reach upwards "
        "into the pipeline (PRD 8.2 rule 1)")


def test_stages_never_import_each_other():
    offenders = []
    for owner, path in _all_v2_files():
        if owner not in STAGES:
            continue
        crossed = _local_imports(path) & (STAGES - {owner})
        if crossed:
            offenders.append(f"{path.relative_to(SRC)} -> {sorted(crossed)}")
    assert not offenders, (
        "stages must be composed by pipeline.py, not wired to each other "
        f"(PRD 8.2 rule 2): {offenders}")


def test_web_never_imports_a_stage():
    offenders = []
    for owner, path in _all_v2_files():
        if owner != "web":
            continue
        crossed = _local_imports(path) - WEB_MAY_IMPORT - {"web"}
        if crossed:
            offenders.append(f"{path.relative_to(SRC)} -> {sorted(crossed)}")
    assert not offenders, (
        "web/ may import only "
        f"{sorted(WEB_MAY_IMPORT)} (PRD 8.2 rule 3): {offenders}")


def test_only_store_contains_sql():
    offenders = []
    for _owner, path in _all_v2_files():
        if path.name == "store.py":
            continue
        text = path.read_text(encoding="utf-8")
        hits = [t.strip() for t in SQL_TOKENS if t in text]
        if hits:
            offenders.append(f"{path.relative_to(SRC)} contains {hits}")
    assert not offenders, (
        "SQL belongs in store.py alone - that is what keeps the Postgres path "
        f"in PRD 8.4 to one module (rule 4): {offenders}")


def test_only_backends_talks_to_a_model():
    offenders = []
    for _owner, path in _all_v2_files():
        if path.name == "backends.py":
            continue
        text = path.read_text(encoding="utf-8")
        for marker in ("import anthropic", "messages.create("):
            if marker in text:
                offenders.append(f"{path.relative_to(SRC)} contains {marker!r}")
    assert not offenders, (
        "backends.py is the single place that reaches a model (PRD 8.2 rule 5): "
        f"{offenders}")


def test_nothing_imports_the_orchestrator():
    """pipeline.py is the top of the stack. An import of it is a cycle."""
    offenders = []
    for _owner, path in _all_v2_files():
        if path.stem in ORCHESTRATOR:
            continue
        crossed = _local_imports(path) & ORCHESTRATOR
        if crossed:
            offenders.append(f"{path.relative_to(SRC)} -> {sorted(crossed)}")
    assert not offenders, (
        "pipeline.py composes the stages; nothing may import it back "
        f"(PRD 8.2): {offenders}")


def test_every_v2_module_is_classified():
    """A new module must be given a layer, not left to drift unchecked."""
    known = ORCHESTRATOR | STAGES | PUBLISHER | FOUNDATION | LEGACY | {"web"}
    seen = {p.stem if len(p.relative_to(SRC).parts) == 1
            else p.relative_to(SRC).parts[0]
            for p in SRC.rglob("*.py")}
    unclassified = seen - known
    assert not unclassified, (
        f"modules {sorted(unclassified)} belong to no layer. Add them to STAGES, "
        "PUBLISHER, FOUNDATION or LEGACY in this file and to PRD section 8.2 - "
        "an unclassified module is one no boundary rule protects.")
