"""NF-01: the owner's personal files can never be committed by accident.

`git check-ignore` must succeed for every path the apply/tailor features write
under data/ (the repo is public). Skipped cleanly when git is not available.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATHS = ["data/applicant.yaml", "data/master_resume.json",
         "data/tailored/x.docx", "data/apply/x.png"]


def test_personal_data_paths_are_gitignored():
    if shutil.which("git") is None:
        return                                   # nothing to check with
    probe = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        return                                   # not a git checkout (e.g. an export)
    missing = []
    for rel in PATHS:
        r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", rel],
                           capture_output=True, text=True)
        if r.returncode != 0:
            missing.append(rel)
    assert not missing, f"not gitignored (NF-01): {missing}"
