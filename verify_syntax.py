"""Quick verification that all migrated modules have valid Python syntax."""

import os
import py_compile
import sys

SRC_DIR = os.path.join(os.path.dirname(__file__), "src", "linkforge")
TESTS_DIR = os.path.join(os.path.dirname(__file__), "tests")


def check_python_files(directory, label):
    print(f"\n=== Checking {label} ===")
    errors = []
    for root, _, files in os.walk(directory):
        for f in files:
            if f.endswith(".py"):
                filepath = os.path.join(root, f)
                try:
                    py_compile.compile(filepath, doraise=True)
                    print(f"  OK   {os.path.relpath(filepath)}")
                except py_compile.PyCompileError as e:
                    errors.append((filepath, str(e)))
                    print(f"  FAIL {os.path.relpath(filepath)}: {e}")
    return errors


src_errors = check_python_files(SRC_DIR, "src/linkforge")
test_errors = check_python_files(TESTS_DIR, "tests")

print("\n=== Summary ===")
if src_errors:
    print(f"src errors: {len(src_errors)}")
    sys.exit(1)
else:
    print("src: all files compile cleanly")

if test_errors:
    print(f"tests errors: {len(test_errors)}")
    sys.exit(1)
else:
    print("tests: all files compile cleanly")

print("\nAll Python files have valid syntax.")
