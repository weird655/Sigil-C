#!/usr/bin/env python3
"""本地质量门：编译 → 静态检查 → 类型检查 → 测试。

CI 跑的是同样四步（ubuntu 的 quality job）。用法：

    python tools/check.py            # 全跑
    python tools/check.py --skip-tests
    python tools/check.py --coverage # 测试用 coverage 跑，并打印覆盖率
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = ["sigilc.py", "sigilc_core", "test_matrix.py", "tools/check.py", "tools/fuzz.py", "tools/bench.py", "tools/difftest.py", "tools/runcheck.py"]


def _run(title, cmd):
    print(f"\n== {title} ==")
    print("$ " + " ".join(cmd))
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    if rc != 0:
        print(f"FAILED: {title} (exit {rc})", file=sys.stderr)
        return False
    return True


def main():
    ap = argparse.ArgumentParser(description="Sigil-C 本地质量门")
    ap.add_argument("--skip-tests", action="store_true", help="只跑静态检查")
    ap.add_argument("--skip-lint", action="store_true", help="没有 ruff / mypy 时用")
    ap.add_argument("--coverage", action="store_true", help="测试跑覆盖率")
    args = ap.parse_args()

    py = sys.executable
    steps = [("py_compile", [py, "-m", "compileall", "-q", *SOURCES])]

    if not args.skip_lint:
        steps.append(("ruff", [py, "-m", "ruff", "check", *SOURCES]))
        steps.append(("mypy", [py, "-m", "mypy", "sigilc_core", "sigilc.py"]))

    if not args.skip_tests:
        if args.coverage:
            steps.append(("tests + coverage", [py, "-m", "coverage", "run", "test_matrix.py"]))
            steps.append(("coverage report", [py, "-m", "coverage", "report"]))
        else:
            steps.append(("tests", [py, "test_matrix.py"]))

    for title, cmd in steps:
        if not _run(title, cmd):
            return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
