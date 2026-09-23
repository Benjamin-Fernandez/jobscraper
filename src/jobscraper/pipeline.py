"""Wires the stages together. The only module that knows the whole sequence.

    sync watchlist -> schedule -> scrape -> prefilter -> vital extract
    -> decide -> shortlist

Stages never import each other; they are composed here. That is what keeps each
one testable alone and lets the order change without touching any of them.

The order is chosen so a crash is never worse than a no-op: the scrape timestamp
is written last, after the work it stands for is already durable.

Replaces v1's runner.py.

See PRD sections 8.2 and 8.3.
"""
