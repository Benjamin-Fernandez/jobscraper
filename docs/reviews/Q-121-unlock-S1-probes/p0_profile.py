import sys
sys.path.insert(0, "docs/reviews/Q-121-unlock-S1-probes")
from h2 import *  # noqa
from h2 import _profile
p = _profile()
print(p["singapore_status"])
print(p.get("personal"), p.get("contact", {}).get("country"))
print(sorted(p.keys()))
