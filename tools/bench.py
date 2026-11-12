#!/usr/bin/env python3
"""转译耗时基线：默认跑 examples/vm.sigil 20 次，取中位数。

    python tools/bench.py --runs 20 --max-ms 1500

超过 --max-ms 以退出码 1 结束，CI 用它挡住明显的性能回退。
"""
import argparse
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import sigilc  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Sigil-C 转译性能基线")
    ap.add_argument("--file", default=os.path.join("examples", "vm.sigil"))
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--max-ms", type=float, default=1500.0)
    args = ap.parse_args()

    path = args.file if os.path.isabs(args.file) else os.path.join(ROOT, args.file)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    samples = []
    for _ in range(args.runs):
        t0 = time.perf_counter()
        sigilc.compile_source(src, "bench.sigil")
        samples.append((time.perf_counter() - t0) * 1000.0)

    median = statistics.median(samples)
    worst = max(samples)
    print(f"bench: {args.file} median {median:.1f} ms, max {worst:.1f} ms, {args.runs} runs")
    if median > args.max_ms:
        print(f"bench: FAIL - median {median:.1f} ms exceeds limit {args.max_ms:.1f} ms", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
