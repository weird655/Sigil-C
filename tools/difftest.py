#!/usr/bin/env python3
"""差分测试：同一逻辑分别用 C 和 Sigil-C 写，各自编译运行，比较输出与退出码。

    python tools/difftest.py

任何一组输出不一致就打印两边的源码与输出。
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import sigilc  # noqa: E402

CASES = [
    {
        "name": "loop-sum",
        "c": "#include <stdio.h>\nint main(void){int s=0;for(int i=1;i<=10;i++)s+=i;printf(\"%d\\n\",s);return 0;}\n",
        "sigil": '#include <stdio.h>\n\ni4 main(v.) {\n    o! i4 s m, 0;\n    o! i4 i m, 1;\n    w~ (i <= 10) { s m+ i; i m+ 1; }\n    printf("%d\\n", s);\n    r; 0;\n}\n',
    },
    {
        "name": "struct-by-value",
        "c": "#include <stdio.h>\nstruct Vec2{int x,y;};\nint dot(struct Vec2 a,struct Vec2 b){return a.x*b.x+a.y*b.y;}\nint main(void){struct Vec2 p={3,4},q={1,2};printf(\"%d\\n\",dot(p,q));return 0;}\n",
        "sigil": '#include <stdio.h>\n\ns{ Vec2 { i4 x; i4 y; };\n\ni4 dot(Vec2 a, Vec2 b) {\n    r; a.x * b.x + a.y * b.y;\n}\n\ni4 main(v.) {\n    o! Vec2 p m, { 3, 4 };\n    o! Vec2 q m, { 1, 2 };\n    printf("%d\\n", dot(p, q));\n    r; 0;\n}\n',
    },
    {
        "name": "pointer-walk",
        "c": "#include <stdio.h>\nint main(void){int a[5]={1,2,3,4,5};int *p=a;int s=0;for(int i=0;i<5;i++)s+=*(p+i);printf(\"%d\\n\",s);return 0;}\n",
        "sigil": '#include <stdio.h>\n\ni4 main(v.) {\n    o! i4[5] a m, { 1, 2, 3, 4, 5 };\n    o! p* i4 p m, a& a[0];\n    o! i4 s m, 0;\n    o! i4 i m, 0;\n    w~ (i < 5) { s m+ p[i]; i m+ 1; }\n    printf("%d\\n", s);\n    r; 0;\n}\n',
    },
    {
        "name": "switch-fallthrough",
        "c": "#include <stdio.h>\nint main(void){int s=0,n=2;switch(n){case 1:s+=1;/* fall through */case 2:s+=2;/* fall through */case 3:s+=3;break;default:s=9;}printf(\"%d\\n\",s);return 0;}\n",
        "sigil": '#include <stdio.h>\n\ni4 main(v.) {\n    o! i4 s m, 0;\n    o! i4 n m, 2;\n    s? (n) {\n        k: 1: { s m+ 1; }\n        k: 2: { s m+ 2; }\n        k: 3: { s m+ 3; b!; }\n        d: { s m, 9; }\n    }\n    printf("%d\\n", s);\n    r; 0;\n}\n',
    },
    {
        "name": "recursion",
        "c": "#include <stdio.h>\nint fib(int n){return n<=1?n:fib(n-1)+fib(n-2);}\nint main(void){printf(\"%d\\n\",fib(10));return 0;}\n",
        "sigil": '#include <stdio.h>\n\ni4 fib(i4 n) {\n    r; (n <= 1) ? n : fib(n - 1) + fib(n - 2);\n}\n\ni4 main(v.) {\n    printf("%d\\n", fib(10));\n    r; 0;\n}\n',
    },
    {
        "name": "libc-string",
        "c": "#include <stdio.h>\n#include <string.h>\n#include <ctype.h>\nint main(void){const char*s=\"a1b2c3\";int d=0;for(int i=0;i<(int)strlen(s);i++)if(isdigit(s[i]))d++;printf(\"%d\\n\",d);return 0;}\n",
        "sigil": '#include <stdio.h>\n#include <string.h>\n#include <ctype.h>\n\ni4 main(v.) {\n    o! p* c@ c1 s m, "a1b2c3";\n    o! i4 d m, 0;\n    o! i4 i m, 0;\n    w~ (i < (i4)strlen(s)) {\n        i? (isdigit(s[i]) !? 0) { d m+ 1; }\n        i m+ 1;\n    }\n    printf("%d\\n", d);\n    r; 0;\n}\n',
    },
]


def _run(exe):
    return subprocess.run([exe], capture_output=True, text=True, timeout=20)


def main():
    work = tempfile.mkdtemp(prefix="sigil-diff-")
    failures = 0
    for case in CASES:
        name = case["name"]
        c_path = os.path.join(work, name + ".c")
        with open(c_path, "w", encoding="utf-8") as f:
            f.write(case["c"])
        ref_exe = os.path.join(work, name + "_ref")
        subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic",
                        c_path, "-o", ref_exe], check=True)

        gen_c = os.path.join(work, name + "_gen.c")
        with open(gen_c, "w", encoding="utf-8") as f:
            f.write(sigilc.compile_source(case["sigil"], name + ".sigil", line_directives=False))
        gen_exe = os.path.join(work, name + "_gen")
        subprocess.run(["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic",
                        gen_c, "-o", gen_exe], check=True, capture_output=True)

        ref = _run(ref_exe)
        gen = _run(gen_exe)
        if (ref.stdout, ref.returncode) != (gen.stdout, gen.returncode):
            failures += 1
            print(f"FAIL {name}: C={ref.stdout!r}/{ref.returncode} Sigil={gen.stdout!r}/{gen.returncode}",
                  file=sys.stderr)
            print("sigil source:\n" + case["sigil"], file=sys.stderr)
        else:
            print(f"ok   {name}: {ref.stdout.strip()!r}")

    if failures:
        print(f"difftest: {failures}/{len(CASES)} cases differ", file=sys.stderr)
        return 1
    print(f"difftest: {len(CASES)} cases, C and Sigil-C outputs agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
