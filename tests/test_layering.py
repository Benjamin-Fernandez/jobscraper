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

Every module in the package is checked. v1's modules retired at M9-T1, so the
only exemptions left in LEGACY are the CLI entry points.
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
ORCHESTRATOR = {"pipeline", "company_search", "apply_flow", "tailor_flow"}
# company_search.py (M16) composes discovery, the adapters and the model to find
# careers sites for the user's own list - an orchestrator for the same reason.
# apply_flow.py / tailor_flow.py (M20, apply_design.md 2.3) compose the apply and
# tailor stages. The one orchestrator->orchestrator edge allowed: apply_flow may
# import tailor_flow (auto-apply tailors first, D-58).
ORCHESTRATOR_EDGES = {("apply_flow", "tailor_flow")}

# Stage modules: each does one step of the pipeline and knows nothing of the others.
STAGES = {"scheduler", "filter", "decide", "scrape", "profile", "apply", "tailor"}

# The stage packages' `contracts` modules are shared data shapes (standard library
# only). web/ may import exactly these and nothing else from the two packages, so
# `_local_imports` reports names inside them dotted ("apply.contracts").
CONTRACTS = {"apply.contracts", "tailor.contracts"}
DOTTED_PACKAGES = {"apply", "tailor"}

# Not a stage. shortlist.py only turns stored decisions into a file, which is why
# both pipeline.py and web/ are allowed to import it (PRD section 8.2).
PUBLISHER = {"shortlist"}

FOUNDATION = {"store", "config", "models", "net", "backends", "watchlist",
              "applicant", "vault"}

WEB_MAY_IMPORT = FOUNDATION | PUBLISHER | CONTRACTS

# Not layered code: the CLI entry points. v1's modules retired at M9-T1
# (kept at the v1-final tag), so the only exemptions left are these.
LEGACY = {"cli", "__main__", "__init__"}

SQL_TOKENS = ("SELECT ", "INSERT ", "UPDATE ", "DELETE FROM", "CREATE TABLE")


def _name(parts: list[str]) -> str:
    """A module's layer name: its top package, or one level deeper inside the
    DOTTED_PACKAGES (`apply.contracts`), so web/ can be allowed exactly that."""
    if parts[0] in DOTTED_PACKAGES and len(parts) > 1:
        return f"{parts[0]}.{parts[1]}"
    return parts[0]


def _top(name: str) -> str:
    return name.split(".")[0]


def _local_imports(path: Path) -> set[str]:
    """Names of sibling jobscraper modules this file imports.

    Top-level names (`store`, `filter`), except inside the apply/tailor packages,
    which are reported one level deeper (`apply.contracts`). A relative import is
    resolved against the importing file's own package, so `from .contracts import`
    in apply/resolve.py is `apply.contracts`.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pkg = list(path.relative_to(SRC).parts[:-1])      # the file's package path
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # `from .filter import x` / `from jobscraper.filter import x`
            if node.level:                       # relative
                up = node.level - 1
                base = pkg[:len(pkg) - up] if up <= len(pkg) else []
                mod = base + (node.module.split(".") if node.module else [])
                if node.module:
                    found.add(_name(mod))
                else:                            # `from . import filter`
                    found.update(_name(mod + [a.name]) for a in node.names)
            elif (node.module or "").startswith("jobscraper"):
                parts = node.module.split(".")[1:]
                if len(parts) == 1 and parts[0] in DOTTED_PACKAGES:
                    # `from jobscraper.apply import contracts`
                    found.update(_name(parts + [a.name]) for a in node.names)
                elif parts:
                    found.add(_name(parts))
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("jobscraper."):
                    found.add(_name(a.name.split(".")[1:]))
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
    bad = {_top(n) for n in _local_imports(store)} & (STAGES | PUBLISHER)
    assert not bad, (
        f"store.py imports {sorted(bad)} - data access must not reach upwards "
        "into the pipeline (PRD 8.2 rule 1)")


def test_stages_never_import_each_other():
    offenders = []
    for owner, path in _all_v2_files():
        if owner not in STAGES:
            continue
        # Its own package (`apply.contracts` from apply/resolve.py) is not a
        # crossing; any other stage, including the other's contracts, is.
        crossed = {_top(n) for n in _local_imports(path)} & (STAGES - {owner})
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
        crossed = {n for n in _local_imports(path)
                   if n not in WEB_MAY_IMPORT and _top(n) != "web"}
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
        for marker in ("/api/chat", "/api/tags", "import anthropic"):
            if marker in text:
                offenders.append(f"{path.relative_to(SRC)} contains {marker!r}")
    assert not offenders, (
        "backends.py is the single place that reaches a model (PRD 8.2 rule 5): "
        f"{offenders}")


def test_nothing_imports_the_orchestrator():
    """pipeline.py is the top of the stack. An import of it is a cycle.

    Orchestrators may not import each other either, except the pairs in
    ORCHESTRATOR_EDGES (apply_flow -> tailor_flow, apply_design.md 2.3).
    """
    offenders = []
    for _owner, path in _all_v2_files():
        allowed = {path.stem} | {dst for src, dst in ORCHESTRATOR_EDGES if src == path.stem}
        crossed = {_top(n) for n in _local_imports(path)} & ORCHESTRATOR - allowed
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


def test_foundation_modules_import_no_stage_or_orchestrator():
    """applicant.py and vault.py (M20) sit beside store.py at the bottom: they
    may use each other and the rest of the foundation, never a stage."""
    offenders = []
    for owner, path in _all_v2_files():
        if owner not in FOUNDATION:
            continue
        crossed = {_top(n) for n in _local_imports(path)} & (STAGES | ORCHESTRATOR | PUBLISHER)
        if crossed:
            offenders.append(f"{path.relative_to(SRC)} -> {sorted(crossed)}")
    assert not offenders, f"foundation must not reach upwards: {offenders}"


def test_apply_and_tailor_meet_only_through_their_flows():
    """The stage packages never import each other or an orchestrator; only
    apply_flow may import tailor_flow (apply design section 2.3, rule 4)."""
    offenders = []
    for owner, path in _all_v2_files():
        if owner not in DOTTED_PACKAGES:
            continue
        other = (DOTTED_PACKAGES - {owner}) | ORCHESTRATOR
        crossed = {_top(n) for n in _local_imports(path)} & other
        if crossed:
            offenders.append(f"{path.relative_to(SRC)} -> {sorted(crossed)}")
    assert not offenders, offenders


def test_the_layering_guard_catches_what_it_claims_to():
    """Self-check on synthetic sources (the guard itself must not rot): the
    import reader reports the stage packages' modules dotted, and only
    apply_flow -> tailor_flow is an exempt orchestrator edge."""
    import tempfile
    d = Path(tempfile.mkdtemp())
    f = d / "m.py"
    f.write_text("from jobscraper.apply.contracts import A\n"
                 "from jobscraper.tailor import contracts\n"
                 "from jobscraper.apply import flowy\n"
                 "from jobscraper.store import Store\n", encoding="utf-8")
    global SRC
    real, SRC = SRC, d                  # _local_imports resolves paths against SRC
    try:
        got = _local_imports(f)
    finally:
        SRC = real
    assert {"apply.contracts", "tailor.contracts", "apply.flowy", "store"} <= got
    assert ("apply_flow", "tailor_flow") in ORCHESTRATOR_EDGES
    assert ("tailor_flow", "apply_flow") not in ORCHESTRATOR_EDGES
    assert ("pipeline", "tailor_flow") not in ORCHESTRATOR_EDGES
