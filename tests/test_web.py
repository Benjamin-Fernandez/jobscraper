"""The web app: the SPA is served, and the API keeps its documented shapes.

Every test builds the app with `create_app(cfg, store_factory=...)`, handing it
a config that points at a fixture shortlist and a fake store. That is the seam
the design asks for: the web layer reads what the pipeline already produced
(PRD 8.2) and is tested without running the pipeline or touching a database.

PRD sections 8.5 and 8.6; tasks M7-T1 onwards.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from jobscraper.config import Config  # noqa: E402
from jobscraper.web.api import STATIC_DIR, create_app  # noqa: E402


def _cfg(**paths: str) -> Config:
    return Config({"paths": dict(paths),
                   "web": {"host": "127.0.0.1", "port": 8765}})


def _client(cfg: Config | None = None, store=None, **kw) -> TestClient:
    return TestClient(create_app(cfg or _cfg(),
                                 store_factory=(lambda: store) if store else None,
                                 **kw))


# ---------------------------------------------------------------- M7-T1

def test_web_serves_the_built_spa_at_root():
    assert (STATIC_DIR / "index.html").is_file(), (
        "the built UI is committed (M10-T3) - run `npm run build` in web/")
    r = _client().get("/")
    assert r.status_code == 200
    assert '<div id="app">' in r.text


def test_web_serves_the_bundles_the_page_references():
    """index.html's asset URLs must resolve, or the page is blank."""
    html = _client().get("/").text
    refs = [part.split('"', 1)[0] for part in html.split('src="')[1:]]
    refs += [part.split('"', 1)[0] for part in html.split('href="')[1:]]
    assets = [r for r in refs if "assets/" in r]
    assert assets, "index.html references no built assets"
    client = _client()
    for ref in assets:
        assert client.get("/" + ref.lstrip("./")).status_code == 200, ref


def test_web_explains_an_unbuilt_ui_instead_of_404ing():
    with tempfile.TemporaryDirectory() as tmp:
        r = _client(static_dir=Path(tmp)).get("/")
    assert r.status_code == 200
    assert "npm run build" in r.text


def test_web_binds_loopback_by_default():
    """No auth exists (R-9); binding wide by default is a regression (8.6)."""
    import os
    saved = os.environ.pop("JOBSCRAPER_HOST", None)
    try:
        assert Config({}).web["host"] == "127.0.0.1"
        assert Config({}).web["port"] == 8765
    finally:
        if saved is not None:
            os.environ["JOBSCRAPER_HOST"] = saved


def test_web_verb_is_wired_into_the_cli():
    from jobscraper.cli import build_parser, cmd_web
    assert build_parser().parse_args(["web"]).fn is cmd_web
