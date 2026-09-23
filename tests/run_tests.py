"""Run every test in tests/, print a tally, exit non-zero if anything failed.

    python tests/run_tests.py                 everything
    python tests/run_tests.py -k filter       only matching tests
    python tests/run_tests.py -v              show each test, not just failures

There is no pytest dependency here on purpose: the whole point of this project
is that it runs from a clean Python checkout with nothing installed. A test is
any `test_*` function defined in a `tests/test_*.py`; it passes if it returns
without raising.

`-k` matches a substring against BOTH the module name and the function name, so
`-k filter` picks up all of `test_filter.py`, and `-k location` picks up
`test_location_is_default_deny` wherever it lives. Thirteen tasks in the v2 build
ledger verify themselves with `-k`, so this behaviour is a contract.

That contract is why `-k` also gates *importing*. The ledger builds the project
one milestone at a time, so at any moment some test file imports something that
does not exist yet - `test_web.py` needs FastAPI long before M7 installs it. If a
selective run imported every file regardless, one not-yet-buildable module would
fail an earlier task's acceptance command for reasons that have nothing to do
with it. So: when `-k` is given and a file's name does not match it, an import
failure skips that file quietly. When the file's name *does* match, or no `-k`
was given, an import failure is a hard failure - it is exactly what you asked to
run.

The limit of that rule: a needle matching only a *function* inside a file whose
*name* does not match still needs the file imported, so `-k location` cannot find
tests in a module that will not import. Name test files after what they cover and
this never bites.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import traceback
from pathlib import Path
from types import ModuleType
from typing import Optional, Sequence

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent

# Tests import the package as `jobscraper.*`; make that work without installing.
sys.path.insert(0, str(ROOT / "src"))


def _load(path: Path) -> ModuleType:
    """Import one test file by path, without it needing to be on sys.path.

    The module is registered in `sys.modules` under its bare stem before being
    executed, so dataclasses and pickling can resolve it. That assumes test file
    stems never collide with a real installed module name - true here, where
    every one is `test_*`.
    """
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)
    return mod


def _selected(module_name: str, func_name: str, needle: str) -> bool:
    """True if this test matches `-k`, comparing module name and function name."""
    if not needle:
        return True
    needle = needle.lower()
    return needle in module_name.lower() or needle in func_name.lower()


def _tests_in(mod: ModuleType, stem: str, needle: str) -> list[tuple[str, object]]:
    """The `test_*` functions this module actually defines, in name order.

    `__module__` is checked so a helper imported from elsewhere is not re-run -
    and re-blamed - under every module that imports it.
    """
    return [(name, fn) for name, fn in sorted(vars(mod).items())
            if name.startswith("test_") and callable(fn)
            and getattr(fn, "__module__", stem) == stem
            and _selected(stem, name, needle)]


def main(argv: Optional[Sequence[str]] = None) -> int:
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
    skipped: list[str] = []
    failures: list[tuple[str, str, str]] = []

    for path in files:
        stem = path.stem
        # A file the needle names is one you asked for: its failure is real.
        # A file it does not name is incidental, and may legitimately not be
        # buildable yet at this point in the ledger.
        required = not args.needle or args.needle.lower() in stem.lower()
        try:
            mod = _load(path)
        except Exception:
            if required:
                failures.append((stem, "<import>", traceback.format_exc()))
                print(f"{stem:<24} IMPORT ERROR")
                total += 1
            else:
                skipped.append(stem)
            continue

        tests = _tests_in(mod, stem, args.needle)
        if not tests:
            continue

        file_passed = 0
        for name, fn in tests:
            total += 1
            try:
                fn()
            # SystemExit and KeyboardInterrupt are not Exceptions. Without this,
            # a stray sys.exit() in one test would end the whole run with no
            # tally and no traceback - a silent truncation of the suite.
            except (Exception, SystemExit):
                failures.append((stem, name, traceback.format_exc()))
                if args.verbose:
                    print(f"  FAIL  {stem}::{name}")
            else:
                passed += 1
                file_passed += 1
                if args.verbose:
                    print(f"  pass  {stem}::{name}")

        flag = "" if file_passed == len(tests) else "   <-- failures"
        print(f"{stem:<24} {file_passed}/{len(tests)}{flag}")

    if skipped:
        print(f"\nskipped (will not import, and -k {args.needle!r} does not name "
              f"them): {', '.join(skipped)}")

    if failures:
        print("\n" + "=" * 70)
        for mod_name, test_name, tb in failures:
            print(f"\nFAIL  {mod_name}::{test_name}\n{tb}")

    if total == 0:
        print(f"\nno tests matched -k {args.needle!r}", file=sys.stderr)
        return 1

    print(f"\n{passed}/{total} passed"
          + (f"  (-k {args.needle!r})" if args.needle else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
