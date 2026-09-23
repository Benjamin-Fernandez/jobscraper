"""Publish the accepted roles as a file the web app can read.

`data/shortlist.json` is regenerated from the database on every run and is safe
to delete. It carries no application status: that belongs in the database,
because a file the engine rewrites is the wrong place to keep something the user
typed.

This module is a publisher, not a pipeline stage - it is the one module that both
the pipeline and the web app may import.

See PRD sections 8.3[6] and 8.2.
"""
