"""AN: aggregate the c1 grid TSVs (c1_all_*.tsv). Per wording and category: the cells, grouped by (shape, profile) and model class.
Usage: python an.py [category]   (HIGH default). Only profiles 'sample' and 'allfalse' are interesting for HIGH; 'alltrue' and 'sample' for MISS."""
import collections
import glob
import sys

cat = sys.argv[1] if len(sys.argv) > 1 else "HIGH"
rows = []
for f in sorted(glob.glob("docs/reviews/Q-121-unlock-S2-probes/c1_all_*.tsv")):
    for line in open(f, encoding="utf-8").read().splitlines():
        p = line.split("\t")
        if len(p) >= 7 and p[0] == cat:
            rows.append(p)
by = collections.defaultdict(list)
for r in rows:
    by[r[1]].append(r)
print(cat, "cells", len(rows), "wordings", len(by))
for lab, rs in sorted(by.items()):
    profs = collections.Counter(r[3] for r in rs)
    classes = collections.Counter(r[4] for r in rs)
    behs = collections.Counter(r[5] for r in rs)
    shapes = collections.Counter(r[2] for r in rs)
    print(f"{lab[:70]:70} n={len(rs):3} prof={dict(profs)} cls={dict(classes)} beh={dict(behs)} shapes={dict(shapes)}")
