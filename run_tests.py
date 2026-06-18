
"""Discover and run all *_tests.py modules in the project.

Usage:
    python run_tests.py              # run everything, compact output
    python run_tests.py -v           # verbose (unittest default)
    python run_tests.py -v render_markdown  # only one module's tests
    python run_tests.py highlighters.python  # submodule tests
"""

from __future__ import annotations

import sys
import os
import unittest
import importlib
import pkgutil


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def _find_test_modules(root: str) -> list[str]:
    """Walk the project tree and return dotted names of all *_tests modules."""
    mods: list[str] = []

    def walk(package_path: str, package_prefix: str = ""):
        for entry in sorted(os.listdir(package_path)):
            full = os.path.join(package_path, entry)
            if entry.endswith("_tests.py"):
                name = entry[:-3]  
                dotted = f"{package_prefix}{name}" if package_prefix else name
                mods.append(dotted)
            elif os.path.isdir(full) and not entry.startswith(("_", ".")):
                sub_prefix = f"{package_prefix}{entry}." if package_prefix else f"{entry}."
                
                if os.path.exists(os.path.join(full, "__init__.py")):
                    walk(full, sub_prefix)

    walk(root)
    return mods


def main() -> int:
    argv = sys.argv[1:]

    
    filters: list[str] = []
    flags: list[str] = []
    for arg in argv:
        if arg.startswith("-"):
            flags.append(arg)
        else:
            filters.append(arg)

    test_modules = _find_test_modules(PROJECT_ROOT)

    if not test_modules:
        print("No *_tests.py modules found.", file=sys.stderr)
        return 1

    
    if filters:
        pattern = "|".join(filters)
        import re
        test_modules = [m for m in test_modules if re.search(pattern, m)]
        if not test_modules:
            print(f"No tests matching filter(s): {filters}", file=sys.stderr)
            return 1

    
    sys.path.insert(0, PROJECT_ROOT)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for mod_name in test_modules:
        try:
            mod = importlib.import_module(mod_name)
            tests = loader.loadTestsFromModule(mod)
            if tests.countTestCases():
                suite.addTests(tests)
        except Exception as e:
            print(f"Error loading {mod_name}: {e}", file=sys.stderr)

    if suite.countTestCases() == 0:
        print("No test cases found.", file=sys.stderr)
        return 1

    
    is_verbose = any(f in ("-v", "--verbose") for f in flags)
    runner = unittest.TextTestRunner(verbosity=2 if is_verbose else 1, failfast=False)
    result = runner.run(suite)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())