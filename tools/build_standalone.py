#!/usr/bin/env python3
"""Build a single-file Sigil-C runner.

    python tools/build_standalone.py --zipapp     # dist/sigilc.pyz (needs Python)
    python tools/build_standalone.py --onefile    # dist/sigilc[.exe] (needs PyInstaller)

The zipapp path is stdlib-only and is what CI can verify. The onefile path is
optional: PyInstaller is not a project dependency.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipapp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")


def build_zipapp() -> int:
    os.makedirs(DIST, exist_ok=True)
    target = os.path.join(DIST, "sigilc.pyz")
    with tempfile.TemporaryDirectory(prefix="sigilc-zipapp-") as stage:
        shutil.copy2(os.path.join(ROOT, "sigilc.py"), os.path.join(stage, "sigilc.py"))
        shutil.copytree(
            os.path.join(ROOT, "sigilc_core"),
            os.path.join(stage, "sigilc_core"),
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        with open(os.path.join(stage, "__main__.py"), "w", encoding="utf-8") as f:
            f.write("from sigilc import cli\n\nif __name__ == '__main__':\n    cli()\n")
        zipapp.create_archive(stage, target, interpreter="/usr/bin/env python3")
    print(f"zipapp: {target}")
    return 0


def build_onefile() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("onefile: PyInstaller is not installed", file=sys.stderr)
        print("  python -m pip install pyinstaller", file=sys.stderr)
        return 2
    os.makedirs(DIST, exist_ok=True)
    cmd = [
        sys.executable, "-m", "PyInstaller", "--onefile", "--name", "sigilc",
        "--distpath", DIST,
        "--workpath", os.path.join(ROOT, "build", "pyinstaller"),
        "--specpath", os.path.join(ROOT, "build"),
        os.path.join(ROOT, "sigilc.py"),
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)
    print(f"onefile: {os.path.join(DIST, 'sigilc.exe' if os.name == 'nt' else 'sigilc')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a single-file Sigil-C runner")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--zipapp", action="store_true", help="build dist/sigilc.pyz")
    group.add_argument("--onefile", action="store_true", help="build a PyInstaller onefile binary")
    args = ap.parse_args()
    return build_zipapp() if args.zipapp else build_onefile()


if __name__ == "__main__":
    sys.exit(main())
