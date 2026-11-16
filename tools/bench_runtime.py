#!/usr/bin/env python3
"""Runtime benchmark: C baseline vs Sigil-C generated C.

    python tools/bench_runtime.py --runs 7

Each case is compiled with gcc -O2 and executed `runs` times; the median wall
time is reported. This is a local measurement, not a CI gate: machine noise,
OS scheduling and process startup are part of the number.
"""
import argparse
import os
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import sigilc  # noqa: E402

CASES = ("alias", "local", "bit", "byte")


def build(cc: str, src: str, out: str) -> None:
    subprocess.run([cc, "-std=c99", "-O2", "-o", out, src], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def timed(exe: str) -> float:
    t0 = time.perf_counter()
    r = subprocess.run([exe], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError(f"{exe} exited {r.returncode}: {r.stderr.decode(errors='replace')[:300]}")
    return (time.perf_counter() - t0) * 1000.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument("--cc", default="gcc")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = []
    with tempfile.TemporaryDirectory(prefix="sigil-bench-") as work:
        for name in CASES:
            c_path = os.path.join(work, name + "_c.c")
            s_path = os.path.join(work, name + "_sigil.c")
            c_exe = os.path.join(work, name + "_c.exe")
            s_exe = os.path.join(work, name + "_sigil.exe")
            with open(os.path.join(ROOT, "benchmarks", name + ".c"), encoding="utf-8") as f:
                c_src = f.read()
            with open(c_path, "w", encoding="utf-8") as f:
                f.write(c_src)
            with open(os.path.join(ROOT, "benchmarks", name + ".sigil"), encoding="utf-8") as f:
                sigil_src = f.read()
            with open(s_path, "w", encoding="utf-8") as f:
                f.write(sigilc.compile_source(sigil_src, name + ".sigil"))
            build(args.cc, c_path, c_exe)
            build(args.cc, s_path, s_exe)
            c_times = [timed(c_exe) for _ in range(args.runs)]
            s_times = [timed(s_exe) for _ in range(args.runs)]
            c_ms = statistics.median(c_times)
            s_ms = statistics.median(s_times)
            rows.append((name, c_ms, s_ms, s_ms / c_ms if c_ms else 0.0))
            print(f"{name:8s} C {c_ms:8.2f} ms  Sigil {s_ms:8.2f} ms  ratio {s_ms / c_ms:5.2f}x",
                  file=sys.stderr)

    if args.json:
        import json
        print(json.dumps([{"case": n, "c_ms": c, "sigil_ms": s, "ratio": r}
                          for n, c, s, r in rows], indent=2))
    else:
        print("| case | C ms | Sigil ms | ratio |")
        print("|---|---:|---:|---:|")
        for n, c, s, r in rows:
            print(f"| {n} | {c:.2f} | {s:.2f} | {r:.2f}x |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
