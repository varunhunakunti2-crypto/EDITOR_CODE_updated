"""Master Test Runner - Runs all test suites for the project.

Usage:
    python tests/test_all.py
"""
import sys
import subprocess
import os

SCRIPTS = [
    "tests/smoke_test.py",
    "tests/room_analysis_check.py",
    "tests/flow_check.py",
    "tests/admin_check.py",
    "tests/shop_flow_check.py",
    "tests/placement_check.py",
    "tests/backend_check.py",
    "tests/depth_check.py",
    "tests/browser_check.py",
]

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(base_dir)

    print("=" * 60)
    print("STARTING COMPLETE PROJECT TEST SUITE (/test-everything)")
    print("=" * 60)

    results = {}
    for script in SCRIPTS:
        script_path = os.path.join(base_dir, script)
        if not os.path.exists(script_path):
            continue
        print(f"\n>>> Running {script} ...")
        proc = subprocess.run([sys.executable, script_path], cwd=base_dir)
        results[script] = proc.returncode == 0

    print("\n" + "=" * 60)
    print("FINAL TEST SUMMARY")
    print("=" * 60)
    all_passed = True
    for script, passed in results.items():
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_passed = False
        print(f"[{status}] {script}")
    print("=" * 60)

    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
