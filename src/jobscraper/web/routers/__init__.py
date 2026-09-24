"""One module per API domain, discovered at startup rather than listed.

PRD section 8.5 requires that a new tab be one registry line, one `.vue` file and
one router - touching nothing else (M7-T4 proves it). A hand-maintained list of
routers in `api.py` would make that four files. So every module in this package
that defines a module-level `router` (a FastAPI `APIRouter`) is mounted under
`/api` automatically, in name order.

Import everything as `jobscraper.<module>`, not relatively: the layering guard
(tests/test_layering.py) reads a relative import's first segment as a top-level
module name, so `from .deps import x` would be misread as importing a stage.
"""
