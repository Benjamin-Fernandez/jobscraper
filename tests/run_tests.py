"""Run every test in tests/, print a tally, exit non-zero if anything failed.

    python tests/run_tests.py                 everything
    python tests/run_tests.py -k filter       only matching tests
    python tests/run_tests.py -v              show each test, not just failures

There is no pytest dependency here on purpose: the whole point of this project
is that it runs from a clean Python checkout with nothing installed. A test is
any `test_*` function in any `tests/test_*.py`; a test passes if it returns
without raising.

`-k` matches a substring against BOTH the module name and the function name, so
`-k filter` picks up all of `test_filter.py`, and `-k location` picks up
`test_location_is_default_deny` wherever it lives. Thirteen tasks in the v2 build
ledger verify themselves with `-k`, so this behaviour is a contract, not a
convenience.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import traceback
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent

# Tests import the package as `jobscraper.*`; make that work without installing.
sys.path.insert(0, str(ROOT / "src"))


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses and pickling can find the module.
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)
    return mod


def _selected(module_name: str, func_name: str, needle: str) -> bool:
    if not needle:
        return True
    needle = needle.lower()
    return needle in module_name.lower() or needle in func_name.lower()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="run_tests")
    ap.add_argument("-k", dest="needle", default="",
                    help="only run tests whose module or function name contains this")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print every test, not just failures")
    args = ap.parse_args(argv)

    files = sorted(TESTS_DIR.glob("test_*.py"))
    if not files:
        print("no test files found", file=sys.stderr)
        return 1

    total = passed = 0
    failures: list[tuple[str, str, str]] = []

    for path in files:
        try:
            mod = _load(path)
        except Exception:
            # A module that will not import is a failure, not a silent skip.
            failures.append((path.stem, "<import>", traceback.format_exc()))
            print(f"{path.stem:<24} IMPORT ERROR")
            total += 1
            continue

        tests = [(n, f) for n, f in sorted(vars(mod).items())
                 if n.startswith("test_") and callable(f)
                 and _selected(path.stem, n, args.needle)]
        if not tests:
            continue

        file_passed = 0
        for name, fn in tests:
            total += 1
            try:
                fn()
            except Exception:
                failures.append((path.stem, name, traceback.format_exc()))
                if args.verbose:
                    print(f"  FAIL  {path.stem}::{name}")
            else:
                passed += 1
                file_passed += 1
                if args.verbose:
                    print(f"  pass  {path.stem}::{name}")

        flag = "" if file_passed == len(tests) else "   <-- failures"
        print(f"{path.stem:<24} {file_passed}/{len(tests)}{flag}")

    if failures:
        print("\n" + "=" * 70)
        for mod_name, test_name, tb in failures:
            print(f"\nFAIL  {mod_name}::{test_name}\n{tb}")

    if total == 0:
        print(f"\nno tests matched -k {args.needle!r}", file=sys.stderr)
        return 1

    print(f"\n{passed}/{total} passed" + (f"  (-k {args.needle!r})" if args.needle else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
