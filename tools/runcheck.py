#!/usr/bin/env python3
"""执行语义测试：随机生成 u4 程序，在 Python 里算出同一个表达式的值，
再运行转译生成的二进制，比较它打印的数字。

    python tools/runcheck.py --count 30 --seed 1

只生成不溢出的运算（值 < 2^31），避免把 C 的有符号溢出 UB 混进来。
"""
import argparse
import os
import random
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import sigilc  # noqa: E402


def gen_expr(rng, depth, names, values):
    if depth <= 0:
        if rng.random() < 0.5:
            v = rng.randrange(0, 100)
            return str(v), v
        name = rng.choice(names)
        return name, values[name]
    pick = rng.random()
    if pick < 0.15:
        text, value = gen_expr(rng, depth - 1, names, values)
        return f"(~^{text})", (~value) & 0xFFFFFFFF
    left, lv = gen_expr(rng, depth - 1, names, values)
    right, rv = gen_expr(rng, depth - 1, names, values)
    if pick < 0.35:
        return f"({left} + {right})", lv + rv
    if pick < 0.55:
        return f"({left} * {right})", lv * rv
    if pick < 0.7:
        return f"({left} &^ {right})", lv & rv
    if pick < 0.85:
        return f"({left} |^ {right})", lv | rv
    return f"({left} ^^ {right})", lv ^ rv


def gen_program(rng):
    names = [f"x{i}" for i in range(3)]
    values = {name: rng.randrange(1, 50) for name in names}
    lines = [f"    o! u4 {name} m, {values[name]};" for name in names]
    text, value = gen_expr(rng, 3, names, values)
    # 保证每个变量都被用到，否则 gcc -Werror 会报 unused
    for name in names:
        if name not in text:
            text = f"({text} + {name})"
            value += values[name]
    lines.append(f'    printf("%u\\n", (u4){text});')
    lines.append("    r; 0;")
    src = "#include <stdio.h>\n\ni4 main(v.) {\n" + "\n".join(lines) + "\n}\n"
    return src, value & 0xFFFFFFFF


def main():
    ap = argparse.ArgumentParser(description="Sigil-C 执行语义测试")
    ap.add_argument("--count", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    work = tempfile.mkdtemp(prefix="sigil-run-")
    for n in range(args.count):
        src, expected = gen_program(rng)
        c_path = os.path.join(work, f"r{n}.c")
        with open(c_path, "w", encoding="utf-8") as f:
            f.write(sigilc.compile_source(src, "runcheck.sigil", line_directives=False))
        exe = os.path.join(work, f"r{n}")
        proc = subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", c_path, "-o", exe],
            capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"FAIL: program {n} did not compile\n{src}\n{proc.stderr[:500]}", file=sys.stderr)
            return 1
        run = subprocess.run([exe], capture_output=True, text=True, timeout=10)
        got = run.stdout.strip()
        if got != str(expected):
            print(f"FAIL: program {n} printed {got!r}, expected {expected}\n{src}", file=sys.stderr)
            return 1
    print(f"runcheck: {args.count} programs, seed {args.seed}, outputs match Python reference")
    return 0


if __name__ == "__main__":
    sys.exit(main())
