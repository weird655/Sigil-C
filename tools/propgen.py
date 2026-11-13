#!/usr/bin/env python3
"""属性测试：随机生成**类型正确**的程序，转译后用 gcc 编译。

不运行程序，只验证「合法的 .sigil 一定产出合法的 C99」。任何一次失败都会打印
随机种子与源码，便于复现。

    python tools/propgen.py --count 30 --seed 1
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

LITERALS = ["0", "1", "2", "3", "7", "13", "255", "1000"]
BINOPS = ["m+", "m-", "m*", "m/", "m%", "&", "|", "^", "<<", ">>"]


def gen_expr(rng, depth, names):
    """只生成 i4 表达式：字面量 / 变量 / 二元 / 一元 / 三元 / 强制转换。"""
    if depth <= 0:
        return rng.choice(LITERALS) if rng.random() < 0.6 else rng.choice(names)
    pick = rng.random()
    if pick < 0.45:
        op = rng.choice(["+", "-", "*", "&", "|", "^"])
        return f"({gen_expr(rng, depth - 1, names)} {op} {gen_expr(rng, depth - 1, names)})"
    if pick < 0.55:
        return f"(~{gen_expr(rng, depth - 1, names)})"
    if pick < 0.65:
        return f"(-{gen_expr(rng, depth - 1, names)})"
    if pick < 0.78:
        # 除法/取模的右操作数固定非零
        return f"({gen_expr(rng, depth - 1, names)} {rng.choice(['/', '%'])} {rng.choice(['1', '2', '3', '7'])})"
    if pick < 0.9:
        return f"((i4)({gen_expr(rng, depth - 1, names)}))"
    return f"(({gen_expr(rng, depth - 1, names)} != 0) ? {gen_expr(rng, depth - 1, names)} : {gen_expr(rng, depth - 1, names)})"


def gen_program(rng):
    names = [f"x{i}" for i in range(4)]
    lines = []
    for name in names:
        lines.append(f"    o! i4 {name} m, {rng.choice(LITERALS)};")
    for _ in range(rng.randrange(0, 4)):
        lines.append(f"    {rng.choice(names)} m, {gen_expr(rng, 2, names)};")
    if rng.random() < 0.5:
        lines.append(f"    i? ({rng.choice(names)} != 0) {{ {rng.choice(names)} m, {gen_expr(rng, 2, names)}; }}")
    lines.append(f"    r; {gen_expr(rng, 3, names)};")
    return "i4 main(v.) {\n" + "\n".join(lines) + "\n}\n"


def main():
    ap = argparse.ArgumentParser(description="Sigil-C 属性测试")
    ap.add_argument("--count", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    work = tempfile.mkdtemp(prefix="sigil-prop-")
    for n in range(args.count):
        src = gen_program(rng)
        try:
            c_src = sigilc.compile_source(src, "prop.sigil")
        except (sigilc.LexerError, sigilc.ParseError, sigilc.SemanticError) as exc:
            print(f"FAIL: generated program {n} was rejected: {exc}", file=sys.stderr)
            print(src, file=sys.stderr)
            return 1
        c_path = os.path.join(work, f"p{n}.c")
        with open(c_path, "w", encoding="utf-8") as f:
            f.write(c_src)
        obj = os.path.join(work, f"p{n}.o")
        proc = subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-pedantic", "-c", c_path, "-o", obj],
            capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"FAIL: generated program {n} produced C that gcc rejects", file=sys.stderr)
            print(src, file=sys.stderr)
            print(proc.stderr[:800], file=sys.stderr)
            return 1
    print(f"propgen: {args.count} programs, seed {args.seed}, all compile")
    return 0


if __name__ == "__main__":
    sys.exit(main())
