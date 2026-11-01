"""NF-01: the owner's personal files for auto-apply and the tailor are never committed.

Runs `git check-ignore` (local, no network) on each path the PRD and both designs name.
The repo is public; a .gitignore edit that drops one of these lines fails here.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PRIVATE = [
    "data/applicant.yaml",                 # applicant profile (F-10)
    "data/applicant.backup.yaml",
    "data/master_resume.json",             # parsed resume (F-20)
    "data/tailored/x/Alex_Testcase_Resume.docx",   # tailored files (F-24)
    "data/tailored/x/Alex_Testcase_Resume.pdf",
    "data/apply/1/01-form.png",            # screenshots and page HTML (F-34, F-38)
    "data/apply/1/failed.html",
    "data/edge_passwords_20261102.csv",    # Edge password export (F-35)
    "data/resume.pdf",
    "data/jobscraper.db",
]

PUBLIC = [                                 # must stay committable
    "config/applicant.example.yaml",
    "tests/fixtures/apply/applicant.sample.yaml",
    "tests/fixtures/apply/greenhouse/gh_dataiku.json",
]


def _ignored(path: str) -> bool:
    r = subprocess.run(["git", "check-ignore", "-q", "--no-index", path], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode in (0, 1), r.stderr
    return r.returncode == 0


def test_nf01_personal_paths_are_gitignored():
    if not shutil.which("git"):
        raise AssertionError("git is needed for the NF-01 check")
    leaks = [p for p in PRIVATE if not _ignored(p)]
    assert not leaks, f"these would be committable (NF-01): {leaks}"


def test_nf01_templates_and_fixtures_stay_committable():
    blocked = [p for p in PUBLIC if _ignored(p)]
    assert not blocked, f"these must not be ignored: {blocked}"
