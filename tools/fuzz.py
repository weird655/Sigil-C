#!/usr/bin/env python3
"""确定性变异模糊测试。

对一组合法源码做随机插入/删除/替换/截断，然后把结果喂给转译器。唯一允许的结果是
三种编译错误（LexerError / ParseError / SemanticError）——其他异常、崩溃或挂起都算 bug。

    python tools/fuzz.py --iterations 500 --seed 1
"""
import argparse
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import sigilc  # noqa: E402  (需要先把仓库根放进 sys.path)

CORPUS = [
    "i4 main(v.) { r; 0; }\n",
    "s{ Vec2 { i4 x; i4 y; }; i4 main(v.) { o! Vec2 p m, { 1, 2 }; r; p.x; }\n",
    "e{ Mode { M_A m, 0, M_B m, 1 }; i4 main(v.) { r; (i4)M_B; }\n",
    "i4 f(p* u4 p, u4 n) { o! u4 i m, 0; w~ (i < n) { p[i] m, i; i m+ 1; } r; 0; }\n",
    "s? (x) { k: 1: { r; 1; } d: { r; 0; } }\n",
    "#define N 4\ni4 main(v.) { r; N; }\n",
    "/* comment */\ni4 main(v.) { r; 0; } /* tail */\n",
    "f^ (i4) -> v. handler; i4 main(v.) { r; 0; }\n",
    "i4 main(v.) { o! f4 x m, 1.5f; r; (i4)(x * 2.0f); }\n",
    'i4 main(v.) { printf("hi %d\\n", 3); r; 0; }\n',
]

ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789{}[]()<>=!@#$%^&*~;:,._\\n\"' \t"


def _mutate(rng, src):
    op = rng.randrange(4)
    if not src:
        return rng.choice(ALPHABET)
    i = rng.randrange(len(src))
    if op == 0:
        return src[:i] + rng.choice(ALPHABET) + src[i:]
    if op == 1:
        return src[:i] + src[i + 1:]
    if op == 2:
        return src[:i] + rng.choice(ALPHABET) + src[i + 1:]
    cut = rng.randrange(len(src) + 1)
    return src[:cut]


def run(iterations, seed):
    rng = random.Random(seed)
    for n in range(iterations):
        src = _mutate(rng, rng.choice(CORPUS))
        try:
            sigilc.compile_source(src, "fuzz.sigil")
        except (sigilc.LexerError, sigilc.ParseError, sigilc.SemanticError):
            continue
        except BaseException as exc:  # noqa: BLE001 - 任何其他异常都是 fuzz 发现
            print(f"FAIL: iteration {n} raised {type(exc).__name__}: {exc}", file=sys.stderr)
            print("source:", repr(src), file=sys.stderr)
            return n
    return iterations


def main():
    ap = argparse.ArgumentParser(description="Sigil-C 变异模糊测试")
    ap.add_argument("--iterations", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    done = run(args.iterations, args.seed)
    if done != args.iterations:
        return 1
    print(f"fuzz: {done} iterations, seed {args.seed}, only expected errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
