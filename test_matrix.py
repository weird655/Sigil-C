#!/usr/bin/env python3
import os
import sys
import tempfile
import subprocess
from sigilc import (
    Lexer, Parser, CodeGenerator, compile_source, compile_header, check_source,
    LexerError, ParseError, SemanticError, format_c_declarator
)

def run_test_matrix():
    passed = 0
    total = 0
    failures = []

    def assert_ok(layer, desc, fn):
        nonlocal passed, total
        total += 1
        try:
            fn()
        except Exception as e:
            failures.append((layer, desc, f"{type(e).__name__}: {e}"))
            print(f"  [FAIL] [{layer}] {desc} -> {type(e).__name__}: {e}")
            return
        passed += 1
        print(f"  [PASS] [{layer}] {desc}")

    def assert_raises(layer, desc, exc_type, code_str):
        nonlocal passed, total
        total += 1
        try:
            compile_source(code_str, "neg_test.sigil")
        except exc_type as e:
            passed += 1
            print(f"  [PASS] [{layer}] {desc} -> Caught {exc_type.__name__}: {e}")
        except Exception as e:
            failures.append((layer, desc, f"expected {exc_type.__name__}, got {type(e).__name__}: {e}"))
            print(f"  [FAIL] [{layer}] {desc} -> expected {exc_type.__name__}, got {type(e).__name__}: {e}")
        else:
            failures.append((layer, desc, f"expected {exc_type.__name__}, but compilation succeeded"))
            print(f"  [FAIL] [{layer}] {desc} -> expected {exc_type.__name__}, but compilation succeeded")

    gcc_ver = subprocess.run(["gcc", "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    uname_info = subprocess.run(["uname", "-srm"], capture_output=True, text=True).stdout.strip()
    print(f"=== SIGIL-C v1.1 AUTOMATED TEST MATRIX ({gcc_ver} | {uname_info}) ===")

    # Layer 1: Lexer (9 Tests)
    def test_lexer_basic():
        src = '/* multi\nline i? r; */\n#define MAX_VAL \\\n  100\np* c@ c1 s m, "str i? \\n \\x41";\nc1 ch m, \'\\x41\';\ni4 hex m, 0xFE;\nf4 sci m, 1.25e+3f;'
        toks = Lexer(src, "lex.sigil").tokenize()
        kinds = [t.kind for t in toks]
        assert 'PREPROC' in kinds and 'STRING' in kinds and 'CHAR' in kinds and 'INT_NUM' in kinds and 'FLOAT_NUM' in kinds

    assert_ok("1. Lexer", "Multi-line comments, line-start #define, escapes, 0xFE INT_NUM vs FLOAT_NUM, UTF-8 offsets", test_lexer_basic)
    assert_raises("1. Lexer", "Reject mid-line stray '#'", LexerError, "i4 x m, 1; #define BAD 2")
    assert_raises("1. Lexer", "Reject invalid string escape '\\q'", LexerError, 'p* c@ c1 s m, "bad\\q";')
    assert_raises("1. Lexer", "Reject overlong hex escape '\\x4142' in char literal", LexerError, "c1 c m, '\\x4142';")
    assert_raises("1. Lexer", "Reject multi-char literal 'ab'", LexerError, "c1 c m, 'ab';")
    assert_raises("1. Lexer", "Reject malformed float '1.2.3'", LexerError, "f4 x m, 1.2.3;")
    assert_raises("1. Lexer", "Reject malformed number '123abc'", LexerError, "i4 x m, 123abc;")
    assert_raises("1. Lexer", "Reject raw '=' operator", LexerError, "i4 x = 1;")
    assert_raises("1. Lexer", "Reject raw '|' operator", LexerError, "i4 x m, 1 | 2;")
    assert_raises("1. Lexer", "Reject out-of-range octal escape \"\\400\"", LexerError, r"c1 c m, '\400';")
    assert_raises("1. Lexer", "Reject invalid digit '9' in C99 octal integer constant '09'", LexerError, "i4 x m, 09;")

    # Layer 2: Parser & Hex/Constant Folding Tests (2 Tests)
    def test_parser_hex_and_const_folding():
        src = """
        e{ Mode { M_A m, 0xFE, M_B m, (17 % 5) + (10 / -3) };
        i4 test_fn(i4 a, p* i4 out_ptr) {
            o! i4 x m, 0xFE;
            p* out_ptr m, (i4)x;
            s? (a) {
                k: 0xFE: { x m+ 1; b!; }
                k: (8 % 3): { x m- 1; b!; }
                d: { x m, 0; b!; }
            }
            r; x;
        }
        """
        c_code = compile_source(src, "parse_test.sigil")
        assert "case 0xFE:" in c_code and "case (8 % 3):" in c_code

    assert_ok("2. Parser", "Hex 0xFE integer inference, C99truncation % and / in constant folding, explicit cast (i4)x", test_parser_hex_and_const_folding)

    def test_parser_void_params_union_and_ptrdiff():
        src = r"""
        u{ WordUnion a!16 { u4 u; i4 i; };
        i4 helper(v.) { r; 0b1010; }
        i4 test_ext(p* i4 p, p* i4 q, f^(v.) -> i4 cb) {
            o! ptrdiff_t diff m, p - q;
            o! p* i4 null_p m, 0;
            o! WordUnion w;
            w.u m, (u4)cb();
            s? ((i4)diff) {
                k: '\n': { r; 1; }
                k: '\101': { r; 2; }
                k: 077: { o! i4 local_tmp m, 10; r; local_tmp; }
                k: (0 &. (1 / 0)): { o! i4 local_tmp m, 20; r; local_tmp; }
                d: { i? (null_p =? 0) { r; (i4)w.u; } }
            }
            r; 0;
        }
        f^(v.) -> i4 get_helper_fn(i4 sel) {
            r; (sel > 0) ? helper : 0;
        }
        """
        c_code = compile_source(src, "ext_test.sigil")
        assert "int32_t helper(void)" in c_code and "SIGIL_ALIGNED_TAG(union, WordUnion, 16)" in c_code

    assert_ok("2. Parser", "(v.) empty params, 0b1010 binary literal, escaped char case labels, union a!16, ptrdiff_t (p - q), null ptr 0", test_parser_void_params_union_and_ptrdiff)

    # Layer 3: Type AST & Declarator Unroller
    def test_type_declarators():
        cases = [
            ("i4[4][8]", "mat", "int32_t mat[4][8]"),
            ("p* i4[8]", "row_ptr", "int32_t (*row_ptr)[8]"),
            ("p* c@ u1", "ptr_to_const", "const uint8_t *ptr_to_const"),
            ("c@ p* u1", "const_ptr", "uint8_t * const const_ptr"),
            ("c@ p* c@ u1", "const_ptr_to_const", "const uint8_t * const const_ptr_to_const"),
            ("(p* u1)[4]", "ptr_arr", "uint8_t *ptr_arr[4]"),
            ("p* c@ p* u1", "ptr_to_const_ptr", "uint8_t * const *ptr_to_const_ptr"),
            ("c@ p* p* u1", "const_ptr_to_ptr", "uint8_t ** const const_ptr_to_ptr"),
            ("f^(u4 id, f^(i4 err) -> v. on_err) -> i4", "hook", "int32_t (*hook)(uint32_t id, void (*on_err)(int32_t err))"),
        ]
        for sigil_t, var_name, expected_c in cases:
            toks = Lexer(sigil_t, "type.sigil").tokenize()
            t_node = Parser(toks, "type.sigil").parse_type()
            assert format_c_declarator(t_node, var_name) == expected_c

    assert_ok("3. Type AST", "2D arrays, pointer-to-array, const-ptr vs ptr-to-const, nested function pointers", test_type_declarators)

    def test_array_const_size_equivalence():
        src = "v. f(p* i4[8] a, p* i4[4 + 4] b, p* i4[0x08] c) { o! p* i4[8] x m, b; x m, c; }"
        compile_source(src, "arr_eq.sigil")

    assert_ok("3. Type AST", "Compile-time array dimension equivalence (i4[8] == i4[4 + 4] == i4[0x08])", test_array_const_size_equivalence)

    # Layer 4: Static Semantic Checks (23 Negative Tests)
    assert_raises("4. Semantic", "Reject side-effect 'm-' inside loop condition y < (h m- 1)", SemanticError,
                  "v. f(i4 h) { f~ (o! i4 y m, 0; y < (h m- 1); y m+ 1) { r;; } }")
    assert_raises("4. Semantic", "Reject pointer += pointer (p m+ q)", SemanticError,
                  "v. f(p* i4 p, p* i4 q) { p m+ q; }")
    assert_raises("4. Semantic", "Reject pointer *= integer (p m* 2)", SemanticError,
                  "v. f(p* i4 p) { p m* 2; }")
    assert_raises("4. Semantic", "Reject incompatible ternary branches (pointer vs integer)", SemanticError,
                  "v. f(i4 c, p* i4 p) { o! i4 x m, (c > 0) ? p : 1; }")
    assert_raises("4. Semantic", "Reject undeclared identifier", SemanticError,
                  "v. f() { unknown_var m, 1; }")
    assert_raises("4. Semantic", "Reject local variable redefinition", SemanticError,
                  "v. f() { o! i4 a m, 1; o! i4 a m, 2; }")
    assert_raises("4. Semantic", "Reject global variable redefinition", SemanticError,
                  "o! i4 g m, 1; o! i4 g m, 2;")
    assert_raises("4. Semantic", "Reject duplicate struct field", SemanticError,
                  "s{ Node { i4 x; i4 x; };")
    assert_raises("4. Semantic", "Reject non-power-of-2 struct alignment a!63", SemanticError,
                  "s{ Node a!63 { i4 x; };")
    assert_raises("4. Semantic", "Reject direct assignment to const variable (c@)", SemanticError,
                  "v. f() { o! c@ i4 k m, 5; k m, 6; }")
    assert_raises("4. Semantic", "Reject dereference write '*ptr m, 10' when ptr is p* c@ u1", SemanticError,
                  "v. f(p* c@ u1 ptr) { p* ptr m, 10; }")
    assert_raises("4. Semantic", "Reject indexed write 'ptr[0] m, 10' when ptr is p* c@ u1", SemanticError,
                  "v. f(p* c@ u1 ptr) { ptr[0] m, 10; }")
    assert_raises("4. Semantic", "Reject member write 'node.x m, 1' when struct variable is const (c@ Node)", SemanticError,
                  "s{ Node { i4 x; }; v. f(c@ Node n) { n.x m, 1; }")
    assert_raises("4. Semantic", "Reject member write 'p->x m, 1' when pointer is p* c@ Node", SemanticError,
                  "s{ Node { i4 x; }; v. f(p* c@ Node p) { p->x m, 1; }")
    assert_raises("4. Semantic", "Reject assignment to array member 'n.arr m, ...'", SemanticError,
                  "s{ Node { i4[4] arr; }; v. f(Node n, p* i4 p) { n.arr m, p; }")
    assert_raises("4. Semantic", "Reject conflicting function prototype vs definition signature", SemanticError,
                  "i4 foo(i4 a); i4 foo(i4 a, i4 b) { r; a + b; }")
    assert_raises("4. Semantic", "Reject duplicate function definition (two bodies)", SemanticError,
                  "i4 foo(i4 a) { r; a; } i4 foo(i4 a) { r; a + 1; }")
    assert_raises("4. Semantic", "Reject function pointer call with wrong argument count", SemanticError,
                  "v. f(f^(i4 a, i4 b) -> i4 cb) { o! i4 res m, cb(1); }")
    assert_raises("4. Semantic", "Reject incompatible return expression type (returning pointer from i4 function)", SemanticError,
                  "i4 f(p* i4 ptr) { r; ptr; }")
    assert_raises("4. Semantic", "Reject non-integer switch condition (switching on float f4)", SemanticError,
                  "v. f(f4 x) { s? (x) { d: { b!; } } }")
    assert_raises("4. Semantic", "Reject non-constant case label (k: var:)", SemanticError,
                  "v. f(i4 x, i4 y) { s? (x) { k: y: { b!; } } }")
    assert_raises("4. Semantic", "Reject duplicate case value (k: 2: and k: (8 % 3): which both equal 2)", SemanticError,
                  "v. f(i4 x) { s? (x) { k: 2: { b!; } k: (8 % 3): { b!; } } }")
    assert_raises("4. Semantic", "Reject multiple d: (default) labels in one switch", SemanticError,
                  "v. f(i4 x) { s? (x) { d: { b!; } d: { b!; } } }")
    assert_raises("4. Semantic", "Reject pointer arithmetic 'p m+ 1' on pointer to incomplete struct", SemanticError,
                  "s{ Incomplete; v. f(p* Incomplete p) { p m+ 1; }")
    assert_raises("4. Semantic", "Reject pointer arithmetic 'p m- 1' on void pointer (p* v.)", SemanticError,
                  "v. f(p* v. p) { p m- 1; }")
    assert_raises("4. Semantic", "Reject nested function pointer assignment with mismatched inner callback parameter type", SemanticError,
                  "v. f(f^(i4 a, f^(f4 x) -> v. cb) -> i4 bad) { o! f^(i4 a, f^(u1 x) -> v. cb) -> i4 good m, bad; }")
    assert_raises("4. Semantic", "Reject dereference write on ternary (c ? pm : pc) due to const qualification propagation", SemanticError,
                  "v. f(i4 c, p* u1 pm, p* c@ u1 pc) { p* ((c > 0) ? pm : pc) m, 1; }")
    assert_raises("4. Semantic", "Reject compile-time constant division by zero (10 / 0)", SemanticError,
                  "v. f(i4 x) { s? (x) { k: (10 / 0): { b!; } } }")
    assert_raises("4. Semantic", "Reject compile-time constant shift count out of range (1 << 65)", SemanticError,
                  "v. f(i4 x) { s? (x) { k: (1 << 65): { b!; } } }")
    assert_raises("4. Semantic", "Reject declaring value variable of incomplete struct type", SemanticError,
                  "s{ Incomplete; v. f(v.) { o! Incomplete x; }")
    assert_raises("4. Semantic", "Reject taking address ('a&') of rvalue expression", SemanticError,
                  "v. f(i4 x) { o! p* i4 p m, a& (x + 1); }")
    assert_raises("4. Semantic", "Reject bitwise operator '&^' on floating-point operand", SemanticError,
                  "v. f(f4 x) { o! i4 y m, x &^ 1; }")
    assert_raises("4. Semantic", "Reject binary pointer addition (p + q)", SemanticError,
                  "v. f(p* i4 p, p* i4 q) { o! p* i4 r m, p + q; }")
    assert_raises("4. Semantic", "Reject binary pointer addition (p + 1) on incomplete struct pointer", SemanticError,
                  "s{ Incomplete; v. f(p* Incomplete p) { o! p* Incomplete q m, p + 1; }")
    assert_raises("4. Semantic", "Reject explicit cast from float (f4) to pointer (p* i4)", SemanticError,
                  "v. f(f4 x) { o! p* i4 p m, (p* i4)x; }")
    assert_raises("4. Semantic", "Reject non-scalar struct condition in 'i?' (if) statement", SemanticError,
                  "s{ Node { i4 x; }; v. f(Node n) { i? (n) { r;; } }")
    assert_raises("4. Semantic", "Reject 'b!' (break) outside of loop or switch", SemanticError,
                  "v. f(v.) { b!; }")
    assert_raises("4. Semantic", "Reject 'c^' (continue) inside switch when not enclosed in a loop", SemanticError,
                  "v. f(i4 x) { s? (x) { d: { c^; } } }")
    assert_raises("4. Semantic", "Reject returning a value from a 'v.' (void) function", SemanticError,
                  "v. f(i4 x) { r; x; }")
    assert_raises("4. Semantic", "Reject duplicate octal/decimal case value (k: 010: and k: 8:)", SemanticError,
                  "v. f(i4 x) { s? (x) { k: 010: { b!; } k: 8: { b!; } } }")
    assert_raises("4. Semantic", "Reject indexed write 'n.arr[0] m, 1' when parent struct 'n' is c@ Node (C99 6.7.3p8)", SemanticError,
                  "s{ Node { i4[4] arr; }; v. f(c@ Node n) { n.arr[0] m, 1; }")
    assert_raises("4. Semantic", "Reject decaying const struct array member 'n.arr' to non-const pointer 'p* i4'", SemanticError,
                  "s{ Node { i4[4] arr; }; v. f(c@ Node n) { o! p* i4 p m, n.arr; }")
    assert_raises("4. Semantic", "Reject non-void function lacking a 'r;' (return) statement", SemanticError,
                  "i4 bad_fn(i4 x) { o! i4 y m, x + 1; }")
    assert_raises("4. Semantic", "Reject non-void function with partial return path (if without else)", SemanticError,
                  "i4 partial_fn(i4 x) { i? (x > 0) { r; x; } }")
    assert_raises("4. Semantic", "Reject non-constant global variable initializer (referencing runtime variable)", SemanticError,
                  "o! i4 g1 m, 1; o! i4 g2 m, g1 + 1;")
    assert_raises("4. Semantic", "Reject unnamed 'v.' (void) parameter mixed with other parameters in function pointer", SemanticError,
                  "v. f(f^(v., i4) -> i4 cb) { r;; }")
    assert_raises("4. Semantic", "Reject ordered relational comparison '<' on void* (p* v.) pointers", SemanticError,
                  "v. f(p* v. a, p* v. b) { o! b. c m, a < b; }")
    assert_raises("4. Semantic", "Reject compile-time constant left shift of negative integer (-2 << 1)", SemanticError,
                  "v. f(i4 x) { s? (x) { k: (-2 << 1): { b!; } } }")

    # Layer 5 & 6: Codegen & End-to-End GCC -pedantic -Werror Runtime Edge-Case Verification
    with open("golden.sigil") as f:
        golden_sigil = f.read()

    def test_integration_gcc():
        c_code = compile_source(golden_sigil, "golden.sigil")
        with open("golden.c", "w") as f:
            f.write(c_code)

        runner_c = """
#include "golden.c"

int main(void) {
    /* 1. 测试缓冲区别名拦截 (buffer_read == buffer_write 必须返回 -1) */
    uint32_t alias_buf[25] = {0};
    uint8_t  wind[25]      = {0};
    ScentGridContext ctx;
    ctx.buffer_read  = alias_buf;
    ctx.buffer_write = alias_buf;
    ctx.wind_dir     = wind;
    ctx.width        = 5;
    ctx.height       = 5;
    assert(step_scent_advection_conserved(&ctx, MODE_ADVECT) == -1);

    /* 2. 测试边界格非零质量 + 四源扇入 (4 * 255 = 1020，绝不发生 uint8_t 回绕!) */
    uint32_t buf_a[25] = {0};
    uint32_t buf_b[25] = {0};

    /* 边界角点 (0,0) 放置 103 质量，向东 (dir=1) 移动 */
    buf_a[0 * 5 + 0] = 103;
    wind[0 * 5 + 0]  = 1;

    /* 四个源全部汇聚向中心格 (2,2)，每格初始 255，验证 828 不回绕为 60 */
    buf_a[2 * 5 + 2] = 255; wind[2 * 5 + 2] = 0; /* 原地保留 255 */
    buf_a[2 * 5 + 1] = 255; wind[2 * 5 + 1] = 1; /* 东移 (+1, 0) -> (2,2), moved=191 */
    buf_a[1 * 5 + 2] = 255; wind[1 * 5 + 2] = 3; /* 南移 (0, +1) -> (2,2), moved=191 */
    buf_a[2 * 5 + 3] = 255; wind[2 * 5 + 3] = 4; /* 西移 (-1, 0) -> (2,2), moved=191 */

    uint32_t sum_before = 0;
    for (int i = 0; i < 25; i++) sum_before += buf_a[i];

    ctx.buffer_read  = buf_a;
    ctx.buffer_write = buf_b;
    assert(step_scent_advection_conserved(&ctx, MODE_ADVECT) == 0);

    uint32_t sum_after = 0;
    for (int i = 0; i < 25; i++) sum_after += buf_b[i];

    /* 验证中心格 (2,2) 收到 255 + 191*3 = 828 (未回绕!)，且全场总质量 (含边界) 1123 == 1123 */
    assert(buf_b[2 * 5 + 2] == 828u);
    assert(sum_before == 1123u && sum_after == 1123u);

    /* 3. 验证 0xFE (254) 作为整型参与回调计算: 7 * 100 + 254 = 954 */
    int32_t cb_res = invoke_with_hook(7u, sample_callback);
    assert(cb_res == 954);

    printf("Integration Runner Verified: Mass=%u->%u (CenterFanIn=%u), Hook0xFE=%d\\n",
           sum_before, sum_after, buf_b[2 * 5 + 2], cb_res);
    return 0;
}
"""
        with open("test_runner.c", "w") as f:
            f.write(runner_c)

        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "test_runner.c", "-o", "test_runner"],
            check=True
        )
        res = subprocess.run(["./test_runner"], capture_output=True, text=True, check=True)
        print("    GCC Binary Output:", res.stdout.strip())

    assert_ok("5 & 6. Codegen + GCC Integration", "Compile golden.sigil with gcc -std=c99 -Wall -Wextra -Werror -pedantic and assert boundary/fan-in/aliasing", test_integration_gcc)

    def test_readme_minimal_example_gcc():
        minimal_sigil = r"""
#include <stdio.h>

s{ Vec2 {
    i4 x;
    i4 y;
};

i4 dot_product(p* c@ Vec2 a, p* c@ Vec2 b) {
    r; (a->x * b->x) + (a->y * b->y);
}

i4 main(v.) {
    o! Vec2 u;
    o! Vec2 v;
    u.x m, 3;
    u.y m, 4;
    v.x m, 0x10;
    v.y m, 2;

    o! i4 res m, dot_product(a& u, a& v);
    /* &. 为逻辑与 (&&)，&^ 为按位与 (&)，=? 为相等比较 (==) */
    i? (res > 0 &. (res &^ 1) =? 0) {
        printf("dot = %d\n", (int)res);
    }
    r; 0;
}
"""
        c_src = compile_source(minimal_sigil, "minimal.sigil")
        with open("minimal.c", "w") as f:
            f.write(c_src)
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "minimal.c", "-o", "minimal_bin"],
            check=True
        )
        out = subprocess.run(["./minimal_bin"], capture_output=True, text=True, check=True).stdout.strip()
        assert out == "dot = 56"

    assert_ok("5 & 6. Codegen + GCC Integration", "Compile & execute README minimal.sigil with gcc -std=c99 -Wall -Wextra -Werror -pedantic", test_readme_minimal_example_gcc)
    # Layer 7: sizeof / s@ / header emission
    def test_sizeof_forms():
        src = """
        s{ Vec2 { i4 x; i4 y; };
        u4 f(p* u4 p) {
            o! u4[8] a;
            o! u4 n m, z? u4;
            o! u4 m2 m, z? p* u4;
            o! u4 k m, z? Vec2;
            o! u4 arr m, z? u4[3];
            o! u4 e m, z? n;
            o! u4 d m, z? (p* p);
            o! u4 len m, z? a / z? a[0];
            r; n + m2 + k + arr + e + d + len;
        }
        """
        c = compile_source(src, "sizeof.sigil")
        assert "sizeof(uint32_t)" in c
        assert "sizeof(uint32_t *)" in c
        assert "sizeof(Vec2)" in c
        assert "sizeof(uint32_t [3])" in c
        assert "sizeof((*p))" in c
        assert "(sizeof(a) / sizeof(a[0]))" in c

    assert_ok("7. sizeof", "z? takes builtin/pointer/array/user types and expressions, result is size_t", test_sizeof_forms)
    assert_raises("7. sizeof", "Reject z? applied to void", SemanticError, "u4 f(v.) { r; z? v.; }")
    assert_raises("7. sizeof", "Reject z? on incomplete struct type", SemanticError, "s{ Fwd; u4 f(v.) { r; z? Fwd; }")

    def test_static_and_header():
        src = """
        s{ Vec2 { i4 x; i4 y; };
        e{ Mode { MODE_A m, 0 };
        s@ o! u4 hidden_counter m, 0;
        o! u4 shown_counter m, 0;
        s@ i4 hidden_helper(i4 v) { hidden_counter m+ 1; r; v * 2; }
        i4 api_fn(i4 v) { r; hidden_helper(v) + 1; }
        u4 api_size(v.) { r; z? Vec2; }
        """
        c = compile_source(src, "api.sigil")
        assert "static uint32_t hidden_counter = 0;" in c
        assert "static int32_t hidden_helper(int32_t v) {" in c
        assert "uint32_t shown_counter = 0;" in c
        h = compile_header(src, "api.sigil", "api.h")
        assert "#ifndef SIGIL_API_H" in h
        assert "int32_t api_fn(int32_t v);" in h
        assert "uint32_t api_size(void);" in h
        assert "extern uint32_t shown_counter;" in h
        assert "hidden_helper" not in h and "hidden_counter" not in h
        assert "struct Vec2 {" in h and "MODE_A" in h

    assert_ok("7. sizeof", "s@ emits static and internal symbols are excluded from the header", test_static_and_header)

    def test_header_end_to_end():
        sigil = """
        s{ Vec2 { i4 x; i4 y; };
        s@ o! u4 calls m, 0;
        i4 dot(p* c@ Vec2 a, p* c@ Vec2 b) {
            calls m+ 1;
            r; (a->x * b->x) + (a->y * b->y);
        }
        u4 vec_bytes(v.) { r; z? Vec2; }
        u4 call_count(v.) { r; calls; }
        """
        with open("api.sigil", "w") as f:
            f.write(sigil)
        with open("api.c", "w") as f:
            f.write(compile_source(sigil, "api.sigil"))
        with open("api.h", "w") as f:
            f.write(compile_header(sigil, "api.sigil", "api.h"))
        with open("consumer.c", "w") as f:
            f.write(
                '#include <stdio.h>\n'
                '#include "api.h"\n'
                'int main(void) {\n'
                '    Vec2 a = { 3, 4 };\n'
                '    Vec2 b = { 10, 2 };\n'
                '    int d = dot(&a, &b);\n'
                '    printf("%d %u %u\\n", d, (unsigned)vec_bytes(), (unsigned)call_count());\n'
                '    return 0;\n'
                '}\n'
            )
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "api.c", "consumer.c", "-o", "api_bin"],
            check=True
        )
        out = subprocess.run(["./api_bin"], capture_output=True, text=True, check=True).stdout.strip()
        assert out == "38 8 1", out

    assert_ok("7. sizeof", "Generated .h consumed by an independent .c file: compile, link, run", test_header_end_to_end)

    def test_differential_vs_c():
        """同一算法用 Sigil-C 与手写 C 各实现一遍，逐位比对结果。

        这是转译器最该有的测试：前六层验的是"转译器自己的行为"，
        这一层验的是"生成的代码与手写 C 语义等价"。
        """
        sigil = """
        s{ Pair { i4 a; i4 b; };

        i4 kernel_sum(p* c@ u4 src, u4 n) {
            o! u4 acc m, 0;
            f~(o! u4 i m, 0; i < n; i m+ 1) {
                acc m+ src[i];
            }
            r; (i4)acc;
        }

        i4 kernel_mix(p* c@ u4 src, p* u4 dst, u4 n) {
            f~(o! u4 i m, 0; i < n; i m+ 1) {
                dst[i] m, (src[i] >> 2) + (src[i] >> 4);
            }
            r; 0;
        }

        i4 pair_dot(p* c@ Pair p, u4 n) {
            o! i4 acc m, 0;
            f~(o! u4 i m, 0; i < n; i m+ 1) {
                acc m+ p[i].a * p[i].b;
            }
            r; acc;
        }
        """
        with open("diff.sigil", "w") as f:
            f.write(sigil)
        with open("diff.c", "w") as f:
            f.write(compile_source(sigil, "diff.sigil"))

        ref = r"""
#include <stdio.h>
#include <string.h>
#include "diff.c"

static int32_t ref_sum(const uint32_t *src, uint32_t n) {
    uint32_t acc = 0;
    for (uint32_t i = 0; i < n; i++) acc += src[i];
    return (int32_t)acc;
}

static int32_t ref_mix(const uint32_t *src, uint32_t *dst, uint32_t n) {
    for (uint32_t i = 0; i < n; i++) dst[i] = (src[i] >> 2) + (src[i] >> 4);
    return 0;
}

static int32_t ref_dot(const Pair *p, uint32_t n) {
    int32_t acc = 0;
    for (uint32_t i = 0; i < n; i++) acc += p[i].a * p[i].b;
    return acc;
}

int main(void) {
    enum { N = 257 };
    uint32_t src[N], got[N], want[N];
    Pair pairs[N];

    /* 确定性伪随机：LCG，避免平台相关的 rand() */
    uint32_t s = 12345u;
    for (int i = 0; i < N; i++) {
        s = s * 1103515245u + 12345u;
        src[i] = s;
        pairs[i].a = (int32_t)(s >> 3);
        pairs[i].b = (int32_t)(s >> 11);
    }

    int32_t a1 = kernel_sum(src, N),  b1 = ref_sum(src, N);
    if (a1 != b1) { printf("sum mismatch: %d vs %d\n", (int)a1, (int)b1); return 1; }

    memset(got, 0, sizeof got); memset(want, 0, sizeof want);
    kernel_mix(src, got, N);
    ref_mix(src, want, N);
    if (memcmp(got, want, sizeof got) != 0) { printf("mix mismatch\n"); return 2; }

    int32_t a3 = pair_dot(pairs, N), b3 = ref_dot(pairs, N);
    if (a3 != b3) { printf("dot mismatch: %d vs %d\n", (int)a3, (int)b3); return 3; }

    printf("diff ok: sum=%d mix=%u dot=%d\n", (int)a1, (unsigned)got[0], (int)a3);
    return 0;
}
"""
        with open("diff_ref.c", "w") as f:
            f.write(ref)
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O2", "diff_ref.c", "-o", "diff_bin"],
            check=True
        )
        out = subprocess.run(["./diff_bin"], capture_output=True, text=True, check=True).stdout.strip()
        assert out.startswith("diff ok:"), out

    assert_ok("7. sizeof", "Differential: Sigil-C output vs hand-written C, 257 elements, bit-identical", test_differential_vs_c)

    # Layer 8: GNU attributes a@(...)
    def test_attr_packed_abi():
        sigil = """
        a@(packed) s{ Packet { u1 kind; u4 id; };
        """
        with open("attr_packed.sigil", "w") as f:
            f.write(sigil)
        with open("attr_packed.c", "w") as f:
            f.write(compile_source(sigil, "attr_packed.sigil"))
        with open("attr_packed.h", "w") as f:
            f.write(compile_header(sigil, "attr_packed.sigil", "attr_packed.h"))
        with open("attr_packed_use.c", "w") as f:
            f.write(
                '#include <stdio.h>\n'
                '#include "attr_packed.h"\n'
                'int main(void) { printf("%zu\\n", sizeof(Packet)); return 0; }\n'
            )
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic",
             "attr_packed.c", "attr_packed_use.c", "-o", "attr_packed_bin"],
            check=True
        )
        out = subprocess.run(["./attr_packed_bin"], capture_output=True, text=True, check=True).stdout.strip()
        assert out == "5", out

    assert_ok("8. attr", "a@(packed) changes the ABI: header-aware consumer sees sizeof == 5", test_attr_packed_abi)

    def test_attr_aligned_type():
        sigil = "a@(aligned(16)) s{ Small { u4 x; };"
        with open("attr_aligned.c", "w") as f:
            f.write(compile_source(sigil, "attr_aligned.sigil"))
        with open("attr_aligned.h", "w") as f:
            f.write(compile_header(sigil, "attr_aligned.sigil", "attr_aligned.h"))
        with open("attr_aligned_use.c", "w") as f:
            f.write(
                '#include <stdio.h>\n'
                '#include "attr_aligned.h"\n'
                'int main(void) { printf("%zu\\n", sizeof(Small)); return 0; }\n'
            )
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic",
             "attr_aligned.c", "attr_aligned_use.c", "-o", "attr_aligned_bin"],
            check=True
        )
        out = subprocess.run(["./attr_aligned_bin"], capture_output=True, text=True, check=True).stdout.strip()
        assert out == "16", out

    assert_ok("8. attr", "a@(aligned(16)) on a type forces 16-byte granularity (sizeof 4 -> 16)", test_attr_aligned_type)

    def test_attr_field_alignment():
        sigil = """
        s{ Node { u1 tag; a@(aligned(8)) u4 seq; };
        """
        with open("attr_field.c", "w") as f:
            f.write(compile_source(sigil, "attr_field.sigil"))
        with open("attr_field.h", "w") as f:
            f.write(compile_header(sigil, "attr_field.sigil", "attr_field.h"))
        with open("attr_field_use.c", "w") as f:
            f.write(
                '#include <stdio.h>\n'
                '#include <stddef.h>\n'
                '#include "attr_field.h"\n'
                'int main(void) { printf("%zu\\n", offsetof(Node, seq)); return 0; }\n'
            )
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic",
             "attr_field.c", "attr_field_use.c", "-o", "attr_field_bin"],
            check=True
        )
        out = subprocess.run(["./attr_field_bin"], capture_output=True, text=True, check=True).stdout.strip()
        assert out == "8", out

    assert_ok("8. attr", "Field-level a@(aligned(8)) moves the member to offset 8", test_attr_field_alignment)

    def test_attr_function_placement():
        sigil = """
        a@(noreturn) v. die_now(v.) { w~ (1) { } }
        a@(unused) s@ i4 helper(v.) { r; 1; }
        a@(deprecated("use fast_path")) i4 slow_path(v.) { r; 2; }
        a@(section(".data.fast")) o! u4 counter m, 0;
        """
        c_src = compile_source(sigil, "attr_fn.sigil")
        with open("attr_fn.c", "w") as f:
            f.write(c_src)
        # 定义处属性必须在声明符之前，否则 GCC 报错
        assert "SIGIL_ATTR(noreturn) void die_now(void) {" in c_src, c_src
        assert "static SIGIL_ATTR(unused) int32_t helper(void) {" in c_src, c_src
        assert 'SIGIL_ATTR(deprecated("use fast_path")) int32_t slow_path(void) {' in c_src, c_src
        assert 'uint32_t counter SIGIL_ATTR(section(".data.fast")) = 0;' in c_src, c_src
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "-c", "attr_fn.c"],
            check=True
        )

    assert_ok("8. attr", "Function/object attributes emit before the declarator and compile clean under -Werror", test_attr_function_placement)

    def test_attr_header_and_guards():
        sigil = """
        a@(packed) s{ Wire { u1 kind; u8 payload; };
        a@(noreturn) v. halt_all(v.) { w~ (1) { } }
        u4 wire_size(v.) { r; (u4)z? Wire; }
        """
        h_src = compile_header(sigil, "attr_h.sigil", "attr_h.h")
        c_src = compile_source(sigil, "attr_h.sigil")
        assert "} SIGIL_ATTR(packed);" in h_src, h_src
        assert "SIGIL_ATTR(noreturn) void halt_all(void);" in h_src, h_src
        # 属性宏在 .c 与 .h 中都可用，且 ABI 属性带有后端能力门
        assert "#define SIGIL_HAS_ATTR 1" in h_src and "#define SIGIL_HAS_ATTR 1" in c_src
        assert "#if !SIGIL_HAS_ATTR" in h_src and "#if !SIGIL_HAS_ATTR" in c_src
        # 生成的 C 里不应残留 sigil 写法（只在 #error 文案里提到 a@）
        assert all(not line.lstrip().startswith("a@") for line in h_src.splitlines()), h_src

    assert_ok("8. attr", "Public header carries attributes and the SIGIL_HAS_ATTR capability gate", test_attr_header_and_guards)

    assert_raises("8. attr", "Reject unknown attribute name",
                  SemanticError, "a@(no_such_attr) o! u4 x m, 0;")
    assert_raises("8. attr", "Reject a@(packed) on a function",
                  SemanticError, "a@(packed) i4 f(v.) { r; 0; }")
    assert_raises("8. attr", "Reject non-power-of-2 a@(aligned(3))",
                  SemanticError, "a@(aligned(3)) o! u4 x m, 0;")
    assert_raises("8. attr", "Reject attributes on a forward declaration",
                  SemanticError, "a@(packed) s{ Foo;")
    assert_raises("8. attr", "Reject file-scope-only attribute on a block-scope object",
                  SemanticError, "i4 f(v.) { a@(section(\".x\")) o! u4 t m, 0; r; 0; }")
    assert_raises("8. attr", "Reject duplicate attributes on one declaration",
                  SemanticError, "a@(unused, unused) s@ i4 f(v.) { r; 0; }")
    assert_raises("8. attr", "Reject wrong argument kind for a string attribute",
                  SemanticError, "a@(section(1)) o! u4 x m, 0;")

    # Layer 9: literals and aggregate initialization
    def test_bool_literals():
        sigil = """
        i4 main(v.) {
            o! b. ok m, true;
            o! b. no m, false;
            i? (ok &. !.no) { r; 0; }
            r; 1;
        }
        """
        with open("lit_bool.c", "w") as f:
            f.write(compile_source(sigil, "lit_bool.sigil"))
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "lit_bool.c", "-o", "lit_bool_bin"],
            check=True
        )
        rc = subprocess.run(["./lit_bool_bin"], check=False).returncode
        assert rc == 0, rc

    assert_ok("9. init", "true / false literals emit stdbool tokens and drive a branch", test_bool_literals)

    def test_null_literal():
        sigil = """
        i4 main(v.) {
            o! p* u4 p m, NULL;
            o! f^(v.) -> u4 cb m, NULL;
            i? (p =? NULL) { i? (cb =? NULL) { r; 0; } }
            r; 1;
        }
        """
        with open("lit_null.c", "w") as f:
            f.write(compile_source(sigil, "lit_null.sigil"))
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "lit_null.c", "-o", "lit_null_bin"],
            check=True
        )
        rc = subprocess.run(["./lit_null_bin"], check=False).returncode
        assert rc == 0, rc

    assert_ok("9. init", "NULL initializes object pointers and function pointers, compares equal", test_null_literal)

    def test_struct_aggregate_init():
        sigil = """
        s{ Vec2 { f8 x; f8 y; };
        i4 main(v.) {
            o! Vec2 p m, { 3.0, 4.0 };
            r; (i4)(p.x + p.y);
        }
        """
        with open("init_struct.c", "w") as f:
            f.write(compile_source(sigil, "init_struct.sigil"))
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "init_struct.c", "-o", "init_struct_bin"],
            check=True
        )
        rc = subprocess.run(["./init_struct_bin"], check=False).returncode
        assert rc == 7, rc

    assert_ok("9. init", "Struct aggregate initializer { 3.0, 4.0 } becomes a C99 brace initializer", test_struct_aggregate_init)

    def test_nested_aggregate_and_zero_fill():
        sigil = """
        s{ Vec2 { u4 x; u4 y; };
        s{ Line { Vec2 a; Vec2 b; };
        o! u4[3] table m, { 10, 20, 12 };
        i4 main(v.) {
            o! Line ln m, { { 1, 2 }, { 3, 4 } };
            o! u4[2] partial m, { 5 };
            r; (i4)(table[0] + table[1] + table[2] + ln.a.x + ln.b.y + partial[0] + partial[1]);
        }
        """
        with open("init_nested.c", "w") as f:
            f.write(compile_source(sigil, "init_nested.sigil"))
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "init_nested.c", "-o", "init_nested_bin"],
            check=True
        )
        rc = subprocess.run(["./init_nested_bin"], check=False).returncode
        assert rc == 52, rc

    assert_ok("9. init", "Nested struct/array initializers plus C99 zero-fill for short lists", test_nested_aggregate_and_zero_fill)

    assert_raises("9. init", "Reject too many struct initializers",
                  SemanticError, "s{ P { u4 a; u4 b; }; i4 main(v.) { o! P p m, { 1, 2, 3 }; r; 0; }")
    assert_raises("9. init", "Reject too many array initializers",
                  SemanticError, "i4 main(v.) { o! u4[2] a m, { 1, 2, 3 }; r; 0; }")
    assert_raises("9. init", "Reject aggregate initializer on a scalar",
                  SemanticError, "i4 main(v.) { o! u4 x m, { 1 }; r; 0; }")
    assert_raises("9. init", "Reject more than one union initializer",
                  SemanticError, "u{ U { u4 a; f4 b; }; i4 main(v.) { o! U u m, { 1, 2 }; r; 0; }")
    assert_raises("9. init", "Reject NULL assigned to a non-pointer",
                  SemanticError, "i4 main(v.) { o! u4 x m, NULL; r; 0; }")
    assert_raises("9. init", "Reject empty initializer list",
                  SemanticError, "i4 main(v.) { o! u4[2] a m, { }; r; 0; }")
    assert_raises("9. init", "Reject incompatible initializer element type",
                  SemanticError, 's{ P { u4 a; }; i4 main(v.) { o! P p m, { "str" }; r; 0; }')
    assert_raises("9. init", "Reject non-constant element in a global aggregate initializer",
                  SemanticError, "o! i4 g m, 1; o! u4[2] t m, { 1, g }; i4 main(v.) { r; 0; }")

    # Layer 10: inline / bit-fields / variadics / static assert / do-while / goto / prelude
    def test_static_inline_header():
        sigil = """
        s@ i@ i4 sat_add(i4 a, i4 b) { r; a + b; }
        """
        with open("inl.h", "w") as f:
            f.write(compile_header(sigil, "inl.sigil", "inl.h"))
        h = open("inl.h").read()
        assert "static inline int32_t sat_add(int32_t a, int32_t b) {" in h, h
        with open("inl_use.c", "w") as f:
            f.write('#include "inl.h"\nint main(void) { return sat_add(20, 22) == 42 ? 0 : 1; }\n')
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "inl_use.c", "-o", "inl_bin"],
            check=True
        )
        assert subprocess.run(["./inl_bin"], check=False).returncode == 0

    assert_ok("10. control", "s@ i@ emits a static inline definition into the public header", test_static_inline_header)

    def test_bitfields():
        sigil = """
        s{ Ctrl { u4 enable w! 1; u4 mode w! 3; u4 rsvd w! 28; };
        i4 main(v.) {
            o! Ctrl c;
            c.enable m, 1;
            c.mode m, 5;
            i? (c.enable =? 1) { r; (i4)(z? Ctrl) + (i4)c.mode; }
            r; 1;
        }
        """
        with open("bf.c", "w") as f:
            f.write(compile_source(sigil, "bf.sigil"))
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "bf.c", "-o", "bf_bin"],
            check=True
        )
        rc = subprocess.run(["./bf_bin"], check=False).returncode
        assert rc == 9, rc   # sizeof(Ctrl) == 4, mode == 5

    assert_ok("10. control", "w! bit-fields pack into 4 bytes and read back", test_bitfields)

    assert_raises("10. control", "Reject a bit-field wider than its base type",
                  SemanticError, "s{ C { u4 x w! 33; }; i4 main(v.) { r; 0; }")
    assert_raises("10. control", "Reject a bit-field on a non-integer base type",
                  SemanticError, "s{ C { f4 x w! 3; }; i4 main(v.) { r; 0; }")
    assert_raises("10. control", "Reject taking the address of a bit-field",
                  SemanticError, "s{ C { u4 b w! 1; }; i4 main(v.) { o! C c; o! p* u4 q m, a& c.b; r; 0; }")

    def test_variadic():
        sigil = """
        i4 trace_write(p* c@ c1 fmt, ...) { r; (i4)(p* fmt); }
        i4 main(v.) {
            i? (trace_write("x", 1, 2) =? 120) { r; 0; }
            r; 1;
        }
        """
        with open("va.c", "w") as f:
            f.write(compile_source(sigil, "va.sigil"))
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "va.c", "-o", "va_bin"],
            check=True
        )
        assert subprocess.run(["./va_bin"], check=False).returncode == 0

    assert_ok("10. control", "... declares and defines variadic functions; extra args are accepted", test_variadic)

    assert_raises("10. control", "Reject '...' before any named parameter",
                  SemanticError, "i4 f(...) { r; 0; } i4 main(v.) { r; 0; }")

    def test_static_assert_pass():
        sigil = 't! (z? u4 =? 4, "u4 must be 4 bytes"); i4 main(v.) { r; 0; }'
        with open("sa_ok.c", "w") as f:
            f.write(compile_source(sigil, "sa_ok.sigil"))
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "sa_ok.c", "-o", "sa_ok_bin"],
            check=True
        )
        assert subprocess.run(["./sa_ok_bin"], check=False).returncode == 0

    assert_ok("10. control", "t! emits a compile-time assertion that holds", test_static_assert_pass)

    def test_static_assert_fail():
        sigil = 't! (z? u4 =? 5, "u4 is not 5 bytes"); i4 main(v.) { r; 0; }'
        with open("sa_bad.c", "w") as f:
            f.write(compile_source(sigil, "sa_bad.sigil"))
        rc = subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "-c", "sa_bad.c", "-o", "sa_bad.o"],
            check=False, capture_output=True
        ).returncode
        assert rc != 0, "a false t! must fail to compile"

    assert_ok("10. control", "t! with a false condition fails at C compile time", test_static_assert_fail)

    def test_do_while():
        sigil = """
        i4 main(v.) {
            o! i4 n m, 0;
            d~ { n m+ 1; } w~ (n < 3);
            r; n;
        }
        """
        with open("dowhile.c", "w") as f:
            f.write(compile_source(sigil, "dowhile.sigil"))
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "dowhile.c", "-o", "dowhile_bin"],
            check=True
        )
        rc = subprocess.run(["./dowhile_bin"], check=False).returncode
        assert rc == 3, rc

    assert_ok("10. control", "d~ / w~ do-while runs the body before testing", test_do_while)

    def test_goto_label():
        sigil = """
        i4 main(v.) {
            o! i4 n m, 0;
            l! again;
            n m+ 1;
            i? (n < 3) { g! again; }
            r; n;
        }
        """
        with open("goto.c", "w") as f:
            f.write(compile_source(sigil, "goto.sigil"))
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "goto.c", "-o", "goto_bin"],
            check=True
        )
        rc = subprocess.run(["./goto_bin"], check=False).returncode
        assert rc == 3, rc

    assert_ok("10. control", "g! / l! emit a goto/backward-label loop", test_goto_label)

    assert_raises("10. control", "Reject a g! target with no matching l! label",
                  SemanticError, "i4 main(v.) { g! nowhere; r; 0; }")

    def test_shared_prelude():
        from sigilc import C99_PRELUDE
        with open("sigil_prelude.h", "w") as f:
            f.write(C99_PRELUDE)
        with open("pa.c", "w") as f:
            f.write(compile_source("u4 alpha(v.) { r; 1; }", "pa.sigil", prelude="sigil_prelude.h"))
        with open("pb.c", "w") as f:
            f.write(compile_source("u4 beta(v.) { r; 2; }", "pb.sigil", prelude="sigil_prelude.h"))
        src = open("pa.c").read()
        assert '#include "sigil_prelude.h"' in src, src
        assert "#define SIGIL_ATTR" not in src, src
        with open("pab_use.c", "w") as f:
            f.write(
                '#include <stdint.h>\n'
                'uint32_t alpha(void); uint32_t beta(void);\n'
                'int main(void) { return (alpha() + beta()) == 3 ? 0 : 1; }\n'
            )
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "-I.", "pa.c", "pb.c", "pab_use.c", "-o", "pab_bin"],
            check=True
        )
        assert subprocess.run(["./pab_bin"], check=False).returncode == 0

    assert_ok("10. control", "--emit-prelude / --prelude share one macro header instead of duplicating it", test_shared_prelude)

    def test_switch_fallthrough():
        sigil = """
        i4 f(i4 x) {
            o! i4 n m, 0;
            s? (x) {
                k: 1: n m+ 1;
                k: 2: n m+ 10; b!;
                d: n m, 99;
            }
            r; n;
        }
        i4 main(v.) {
            i? (f(1) =? 11) { i? (f(3) =? 99) { r; 0; } }
            r; 1;
        }
        """
        with open("fall.c", "w") as f:
            f.write(compile_source(sigil, "fall.sigil"))
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "fall.c", "-o", "fall_bin"],
            check=True
        )
        assert subprocess.run(["./fall_bin"], check=False).returncode == 0

    assert_ok("10. control", "Switch falls through unless b!/r;/g! ends the case (C semantics, marked explicitly)", test_switch_fallthrough)

    # Layer 11: restrict / bit-field padding / designated initializers
    def test_restrict_qualifier():
        sigil = """
        u4 sum(r@ p* u4 src, u4 n) {
            o! u4 acc m, 0;
            o! u4 i m, 0;
            w~ (i < n) { acc m+ src[i]; i m+ 1; }
            r; acc;
        }
        i4 main(v.) { o! u4[3] a m, { 1, 2, 3 }; r; (i4)sum(a, 3) - 6; }
        """
        with open("restr.c", "w") as f:
            f.write(compile_source(sigil, "restr.sigil"))
        c_src = open("restr.c").read()
        assert "uint32_t * restrict src" in c_src, c_src
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "restr.c", "-o", "restr_bin"],
            check=True
        )
        assert subprocess.run(["./restr_bin"], check=False).returncode == 0

    assert_ok("11. decl", "r@ emits a C99 restrict-qualified pointer", test_restrict_qualifier)

    assert_raises("11. decl", "Reject r@ on a non-pointer type",
                  SemanticError, "i4 main(v.) { o! r@ u4 x m, 1; r; 0; }")

    def test_padding_bitfield():
        sigil = """
        s{ Flags { u1 a w! 3; u1 w! 0; u1 b w! 3; };
        i4 main(v.) {
            o! Flags f;
            f.a m, 5;
            f.b m, 6;
            r; (i4)(z? Flags) + (i4)f.a + (i4)f.b;
        }
        """
        with open("pad.c", "w") as f:
            f.write(compile_source(sigil, "pad.sigil"))
        c_src = open("pad.c").read()
        assert "uint8_t : 0;" in c_src, c_src
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "pad.c", "-o", "pad_bin"],
            check=True
        )
        rc = subprocess.run(["./pad_bin"], check=False).returncode
        assert rc == 13, rc   # sizeof(Flags) == 2 due to the zero-width padding, +5 +6

    assert_ok("11. decl", "Unnamed zero-width w! padding forces the next field to a new unit", test_padding_bitfield)

    assert_raises("11. decl", "Reject an unnamed bit-field with a non-zero width",
                  SemanticError, "s{ P { u4 w! 3; }; i4 main(v.) { r; 0; }")

    def test_designated_init():
        sigil = """
        s{ Vec2 { f8 x; f8 y; };
        s{ Line { Vec2 a; Vec2 b; };
        i4 main(v.) {
            o! Vec2 v m, { .y m, 4.0, .x m, 3.0 };
            o! Line ln m, { .b m, { .y m, 6.0, .x m, 5.0 }, .a m, { .x m, 1.0, .y m, 2.0 } };
            r; (i4)(v.x + v.y) + (i4)(ln.a.x + ln.b.y);
        }
        """
        with open("desig.c", "w") as f:
            f.write(compile_source(sigil, "desig.sigil"))
        c_src = open("desig.c").read()
        assert ".y = 4.0, .x = 3.0" in c_src, c_src
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "desig.c", "-o", "desig_bin"],
            check=True
        )
        rc = subprocess.run(["./desig_bin"], check=False).returncode
        assert rc == 14, rc   # v: 3+4, ln.a.x + ln.b.y: 1+6

    assert_ok("11. decl", "{ .y m, 4.0 } designated initializers, out of order and nested", test_designated_init)

    assert_raises("11. decl", "Reject a designated initializer for an unknown field",
                  SemanticError, "s{ P { u4 a; }; i4 main(v.) { o! P p m, { .z m, 1 }; r; 0; }")
    assert_raises("11. decl", "Reject mixing designated and positional initializers",
                  SemanticError, "s{ P { u4 a; u4 b; }; i4 main(v.) { o! P p m, { .a m, 1, 2 }; r; 0; }")
    assert_raises("11. decl", "Reject duplicate designated initializers for one field",
                  SemanticError, "s{ P { u4 a; }; i4 main(v.) { o! P p m, { .a m, 1, .a m, 2 }; r; 0; }")
    assert_raises("11. decl", "Reject designated initializers on arrays",
                  SemanticError, "i4 main(v.) { o! u4[2] a m, { .a m, 1 }; r; 0; }")

    # Layer 12: compound literals / array designators / va_list / g?
    def test_compound_literal():
        sigil = """
        s{ Vec2 { f8 x; f8 y; };
        i4 main(v.) {
            o! f8 fy m, (Vec2){ 3.0, 4.0 }.y;
            o! f8 fx m, (Vec2){ .x m, 5.0, .y m, 1.0 }.x;
            o! u4 n m, (u4){ 7 };
            r; (i4)fy + (i4)fx + (i4)n;
        }
        """
        with open("clit.c", "w") as f:
            f.write(compile_source(sigil, "clit.sigil"))
        c_src = open("clit.c").read()
        assert "((Vec2){ 3.0, 4.0 }).y" in c_src, c_src
        assert "((uint32_t){ 7 })" in c_src, c_src
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "clit.c", "-o", "clit_bin"],
            check=True
        )
        rc = subprocess.run(["./clit_bin"], check=False).returncode
        assert rc == 16, rc   # 4 + 5 + 7

    assert_ok("12. expr", "Compound literals work as postfix bases and with designators", test_compound_literal)

    assert_raises("12. expr", "Reject a scalar compound literal with two values",
                  SemanticError, "i4 main(v.) { o! u4 n m, (u4){ 1, 2 }; r; 0; }")

    def test_array_designated_index():
        sigil = """
        i4 main(v.) {
            o! u4[4] a m, { [2] m, 7, [0] m, 5 };
            r; (i4)(a[0] + a[2] + a[3]);
        }
        """
        with open("adesig.c", "w") as f:
            f.write(compile_source(sigil, "adesig.sigil"))
        c_src = open("adesig.c").read()
        assert "{ [2] = 7, [0] = 5 }" in c_src, c_src
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "adesig.c", "-o", "adesig_bin"],
            check=True
        )
        rc = subprocess.run(["./adesig_bin"], check=False).returncode
        assert rc == 12, rc   # 5 + 7 + 0

    assert_ok("12. expr", "[index] m, value array designators with zero-fill", test_array_designated_index)

    assert_raises("12. expr", "Reject an array designator past the array bound",
                  SemanticError, "i4 main(v.) { o! u4[2] a m, { [5] m, 1 }; r; 0; }")
    assert_raises("12. expr", "Reject duplicate array designators",
                  SemanticError, "i4 main(v.) { o! u4[2] a m, { [0] m, 1, [0] m, 2 }; r; 0; }")
    assert_raises("12. expr", "Reject mixing array designators and positional values",
                  SemanticError, "i4 main(v.) { o! u4[2] a m, { [0] m, 1, 2 }; r; 0; }")

    def test_va_list_reading():
        sigil = """
        i4 sum_all(u4 count, ...) {
            o! va_list ap;
            va_start(ap, count);
            o! i4 acc m, 0;
            o! u4 i m, 0;
            w~ (i < count) { acc m+ va_arg(ap, i4); i m+ 1; }
            va_end(ap);
            r; acc;
        }
        i4 main(v.) { r; sum_all(3, 1, 2, 3) - 6; }
        """
        with open("va2.c", "w") as f:
            f.write(compile_source(sigil, "va2.sigil"))
        c_src = open("va2.c").read()
        assert "va_start(ap, count);" in c_src, c_src
        assert "va_arg(ap, int32_t)" in c_src, c_src
        assert "va_end(ap);" in c_src, c_src
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "va2.c", "-o", "va2_bin"],
            check=True
        )
        assert subprocess.run(["./va2_bin"], check=False).returncode == 0

    assert_ok("12. expr", "va_list + va_start/va_arg/va_end read real variadic arguments", test_va_list_reading)

    assert_raises("12. expr", "Reject va_start outside a variadic function",
                  SemanticError, "i4 f(v.) { o! va_list ap; va_start(ap, x); r; 0; }")
    assert_raises("12. expr", "Reject va_arg of a void type",
                  SemanticError, "i4 sum_all(u4 c, ...) { o! va_list ap; va_start(ap, c); o! i4 x m, va_arg(ap, v.); r; x; }")

    def test_generic_static_resolution():
        sigil = """
        i4 pick(i4 n) { r; g? n { i4: n + 10; f8: 20; d: 30 }; }
        i4 fallback(v.) { r; g? 1.5 { i4: 1; d: 2 }; }
        i4 main(v.) { r; pick(1) + fallback() - 13; }
        """
        with open("gen.c", "w") as f:
            f.write(compile_source(sigil, "gen.sigil"))
        c_src = open("gen.c").read()
        assert "_Generic" not in c_src, c_src          # 转译期已解析掉
        assert "return (n + 10);" in c_src, c_src
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "gen.c", "-o", "gen_bin"],
            check=True
        )
        assert subprocess.run(["./gen_bin"], check=False).returncode == 0   # 11 + 2 - 13

    assert_ok("12. expr", "g? resolves to one branch at transpile time (C99 output, no _Generic)", test_generic_static_resolution)

    assert_raises("12. expr", "Reject g? with no matching association and no default",
                  SemanticError, "i4 f(f8 x) { r; g? x { i4: 1 }; }")
    assert_raises("12. expr", "Reject duplicate g? associations for one type",
                  SemanticError, "i4 f(i4 x) { r; g? x { i4: 1; i4: 2; }; }")

    # Layer 13: macro constants / offsetof / va_copy / pragma / bounds
    def test_macros_offsetof():
        sigil = """
        #define TABLE_N 3
        #define SCALE 10

        s{ Row { u1 tag; u4 value; };

        i4 main(v.) {
            o! u4[TABLE_N] t m, { 1, 2, 3 };
            o! u4 sum m, 0;
            o! u4 i m, 0;
            w~ (i < TABLE_N) { sum m+ t[i]; i m+ 1; }
            t! (offsetof(Row, value) =? 4, "value offset");
            r; (i4)(sum * SCALE) + (i4)offsetof(Row, value);
        }
        """
        with open("moff.c", "w") as f:
            f.write(compile_source(sigil, "moff.sigil"))
        c_src = open("moff.c").read()
        assert "#define TABLE_N 3" in c_src, c_src
        assert "offsetof(Row, value)" in c_src, c_src
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "moff.c", "-o", "moff_bin"],
            check=True
        )
        rc = subprocess.run(["./moff_bin"], check=False).returncode
        assert rc == 64, rc   # 6 * 10 + offsetof(value) == 4

    assert_ok("13. safety", "#define literals usable as constants; offsetof() builtin", test_macros_offsetof)

    def test_va_copy():
        sigil = """
        i4 sum_two(u4 count, ...) {
            o! va_list a;
            o! va_list b;
            va_start(a, count);
            va_copy(b, a);
            o! i4 s m, 0;
            o! u4 i m, 0;
            w~ (i < count) { s m+ va_arg(a, i4); i m+ 1; }
            va_end(a);
            va_end(b);
            r; s;
        }
        i4 main(v.) { r; sum_two(2, 4, 5) - 9; }
        """
        with open("vacopy.c", "w") as f:
            f.write(compile_source(sigil, "vacopy.sigil"))
        c_src = open("vacopy.c").read()
        assert "va_copy(b, a);" in c_src, c_src
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "vacopy.c", "-o", "vacopy_bin"],
            check=True
        )
        assert subprocess.run(["./vacopy_bin"], check=False).returncode == 0

    assert_ok("13. safety", "va_copy duplicates a va_list that has already been started", test_va_copy)

    def test_pragma_passthrough():
        sigil = """
        #pragma GCC diagnostic ignored "-Wunused-parameter"
        i4 id(i4 x) { r; x; }
        i4 main(v.) { r; id(0); }
        """
        with open("prag.c", "w") as f:
            f.write(compile_source(sigil, "prag.sigil"))
        c_src = open("prag.c").read()
        assert "#pragma GCC diagnostic ignored" in c_src, c_src
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "prag.c", "-o", "prag_bin"],
            check=True
        )
        assert subprocess.run(["./prag_bin"], check=False).returncode == 0

    assert_ok("13. safety", "#pragma lines pass through to the generated C", test_pragma_passthrough)

    assert_raises("13. safety", "Reject a constant array index past the bound at transpile time",
                  SemanticError, "i4 main(v.) { o! u4[3] a m, { 1, 2, 3 }; r; (i4)a[5]; }")
    assert_raises("13. safety", "Reject a negative constant array index at transpile time",
                  SemanticError, "i4 main(v.) { o! u4[3] a m, { 1, 2, 3 }; r; (i4)a[-1]; }")

    def test_runtime_bounds_check():
        good = """
        i4 main(v.) { o! u4[3] a m, { 1, 2, 3 }; o! u4 i m, 2; r; (i4)a[i]; }
        """
        bad = """
        i4 main(v.) { o! u4[3] a m, { 1, 2, 3 }; o! u4 i m, 5; r; (i4)a[i]; }
        """
        with open("bc_ok.c", "w") as f:
            f.write(compile_source(good, "bc_ok.sigil", bounds_check=True))
        with open("bc_bad.c", "w") as f:
            f.write(compile_source(bad, "bc_bad.sigil", bounds_check=True))
        for name in ("bc_ok", "bc_bad"):
            subprocess.run(
                ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", name + ".c", "-o", name + "_bin"],
                check=True
            )
        assert "#define SIGIL_BOUNDS_CHECK 1" in open("bc_ok.c").read()
        assert "SIGIL_IDX(i, 3)" in open("bc_ok.c").read()
        ok_rc = subprocess.run(["./bc_ok_bin"], check=False).returncode
        bad_rc = subprocess.run(["./bc_bad_bin"], check=False).returncode
        assert ok_rc == 3, ok_rc          # a[2] == 3, no abort
        assert bad_rc != 0, bad_rc        # out-of-range aborts

    assert_ok("13. safety", "--bounds-check aborts on a runtime out-of-range subscript", test_runtime_bounds_check)

    # Layer 14: x! external types / --define / error snippets
    def test_external_type():
        with open("sys_fake.h", "w") as f:
            f.write(
                "#include <stdint.h>\n"
                "struct sockaddr_fake { uint16_t sin_family; uint16_t sin_port; uint32_t sin_addr; };\n"
                "typedef struct pthread_fake { uint64_t opaque; } pthread_fake;\n"
            )
        sigil = """
        #include "sys_fake.h"

        x! struct sockaddr_fake {
            u2 sin_family;
            u2 sin_port;
            u4 sin_addr;
        };

        x! pthread_fake;

        u4 family_of(p* c@ sockaddr_fake sa) { r; (u4)sa->sin_family; }

        i4 main(v.) {
            t! (offsetof(sockaddr_fake, sin_addr) =? 4, "layout drift");
            o! sockaddr_fake sa;
            sa.sin_family m, 2;
            sa.sin_port m, 80;
            sa.sin_addr m, 0x7f000001;
            o! p* pthread_fake h m, NULL;
            i? (h =? NULL) { r; (i4)(family_of(a& sa) + (u4)(z? sockaddr_fake)); }
            r; 1;
        }
        """
        with open("ext.c", "w") as f:
            f.write(compile_source(sigil, "ext.sigil"))
        c_src = open("ext.c").read()
        assert "struct sockaddr_fake {" not in c_src, c_src          # 定义来自系统头，不重复生成
        assert "const struct sockaddr_fake *sa" in c_src, c_src    # 生成 C 用真实拼写
        assert "offsetof(struct sockaddr_fake, sin_addr)" in c_src, c_src
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "ext.c", "-o", "ext_bin"],
            check=True
        )
        rc = subprocess.run(["./ext_bin"], check=False).returncode
        assert rc == 10, rc   # family 2 + sizeof 8

    assert_ok("14. v1.1 ext", "x! registers external struct fields without emitting a definition", test_external_type)

    assert_raises("14. v1.1 ext", "Reject member access on an opaque external handle",
                  SemanticError, "x! pthread_fake; i4 main(v.) { o! p* pthread_fake h; h->opaque m, 1; r; 0; }")
    assert_raises("14. v1.1 ext", "Reject a duplicate external type name",
                  SemanticError, "x! pthread_t; x! pthread_t; i4 main(v.) { r; 0; }")
    assert_raises("14. v1.1 ext", "Reject an external type with an empty field list",
                  SemanticError, "x! struct empty { }; i4 main(v.) { r; 0; }")

    def test_cli_defines():
        sigil = "i4 main(v.) { o! u4[N] a; o! u4 i m, 0; w~ (i < N) { a[i] m, i; i m+ 1; } r; (i4)a[N - 1] - (N - 1); }"
        with open("defs.c", "w") as f:
            f.write(compile_source(sigil, "defs.sigil", defines={"N": "4"}))
        c_src = open("defs.c").read()
        assert "#define N 4" in c_src, c_src
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "defs.c", "-o", "defs_bin"],
            check=True
        )
        assert subprocess.run(["./defs_bin"], check=False).returncode == 0

    assert_ok("14. v1.1 ext", "--define seeds a macro constant into both checking and generated C", test_cli_defines)

    def test_error_snippet():
        import sys as _sys
        import sigilc as _sigilc
        with open("snip.sigil", "w") as f:
            f.write("i4 main(v.) { o! u4[3] a m, { 1, 2, 3 }; r; (i4)a[5]; }")
        res = subprocess.run(
            [_sys.executable, _sigilc.__file__, "snip.sigil", "--check"],
            capture_output=True, text=True
        )
        assert res.returncode != 0, res.stdout
        assert "-->" in res.stderr, res.stderr
        assert "^" in res.stderr, res.stderr

    assert_ok("14. v1.1 ext", "Compile errors print a source snippet with a caret", test_error_snippet)

    # Layer 15: v1.1 pointer provenance (bounds through pointers / dangling)
    def test_pointer_provenance_ok():
        sigil = """
        i4 main(v.) {
            o! u4[3] a m, { 10, 20, 30 };
            o! p* u4 p m, a& a[1];
            r; (i4)p[0] + (i4)p[1];
        }
        """
        with open("prov.c", "w") as f:
            f.write(compile_source(sigil, "prov.sigil"))
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "prov.c", "-o", "prov_bin"],
            check=True
        )
        rc = subprocess.run(["./prov_bin"], check=False).returncode
        assert rc == 50, rc   # 20 + 30

    assert_ok("15. v1.1 ptr", "Provenance tracks a pointer into a[1] and allows p[0]..p[1]", test_pointer_provenance_ok)

    assert_raises("15. v1.1 ptr", "Reject a constant index through a pointer past the base object",
                  SemanticError, "i4 f(v.) { o! u4[3] a m, { 1, 2, 3 }; o! p* u4 p m, a& a[1]; r; (i4)p[2]; }")
    assert_raises("15. v1.1 ptr", "Reject dereferencing a pointer advanced past the base object",
                  SemanticError, "i4 f(v.) { o! u4[3] a m, { 1, 2, 3 }; o! p* u4 p m, a& a[0]; p m+ 3; r; (i4)p* p; }")

    def test_pointer_dynamic_bound():
        sigil = """
        i4 main(v.) {
            o! u4[3] a m, { 1, 2, 3 };
            o! p* u4 p m, a& a[1];
            o! u4 i m, 0;
            r; (i4)p[i];
        }
        """
        with open("pbound.c", "w") as f:
            f.write(compile_source(sigil, "pbound.sigil"))
        c_src = open("pbound.c").read()
        assert "SIGIL_IDX(i, 2)" in c_src, c_src     # 3 元素、起点偏移 1 -> 只剩 2 个
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "pbound.c", "-o", "pbound_bin"],
            check=True
        )
        assert subprocess.run(["./pbound_bin"], check=False).returncode == 2

    assert_ok("15. v1.1 ptr", "A dynamic pointer index reuses SIGIL_IDX with the remaining length", test_pointer_dynamic_bound)

    assert_raises("15. v1.1 ptr", "Reject returning the address of a local object",
                  SemanticError, "p* u4 f(v.) { o! u4 x m, 1; r; a& x; }")
    assert_raises("15. v1.1 ptr", "Reject storing the address of a local into a global",
                  SemanticError, "o! p* u4 g; v. f(v.) { o! u4 x m, 1; g m, a& x; }")
    assert_raises("15. v1.1 ptr", "Reject storing the address of a local into an out-parameter",
                  SemanticError, "v. f(p* u4 out) { o! u4 x m, 1; out m, a& x; }")

    def test_pointer_dangling_ok():
        sigil = """
        o! u4 g m, 5;
        p* u4 addr_of_global(v.) { r; a& g; }
        v. local_ptr(v.) {
            o! u4 x m, 1;
            o! p* u4 p m, a& x;
            o! u4 y m, p* p;
        }
        i4 main(v.) { r; (i4)(p* addr_of_global()) + (i4)(z? p* u4) - 8; }
        """
        check_source(sigil, "dangle_ok.sigil")

    assert_ok("15. v1.1 ptr", "Global addresses and locals pointing at locals stay legal", test_pointer_dangling_ok)

    assert_raises("15. v1.1 ptr", "Reject using a pointer whose base object has left scope",
                  SemanticError, "i4 f(v.) { o! p* u4 p; i? (1) { o! u4 x m, 1; p m, a& x; } r; (i4)p* p; }")
    assert_raises("15. v1.1 ptr", "Reject copying a pointer whose base object has left scope",
                  SemanticError, "v. f(v.) { o! p* u4 p; i? (1) { o! u4 x m, 1; p m, a& x; } o! p* u4 q m, p; }")
    assert_raises("15. v1.1 ptr", "Reject passing a pointer whose base object has left scope",
                  SemanticError,
                  "u4 rd(p* u4 p) { r; p* p; } i4 f(v.) { o! p* u4 p; i? (1) { o! u4 x m, 1; p m, a& x; } r; (i4)rd(p); }")

    def test_pointer_scope_ok():
        sigil = """
        o! u4 g m, 1;
        i4 keep(p* u4 p) { r; (i4)p* p; }
        i4 f(i4 a) {
            o! i4 x m, 1;
            s? (a) { k: 1: { x m+ 1; b!; } d: { x m, 0; } }
            o! u4 base m, 7;
            o! p* u4 p m, a& base;
            i? (1) { o! u4 y m, keep(p) + (i4)p* p; }
            o! p* u4 gp m, a& g;
            r; x + (i4)p* gp;
        }
        i4 main(v.) { r; f(1) - 8; }
        """
        check_source(sigil, "scope_ok.sigil")

    assert_ok("15. v1.1 ptr", "In-scope pointers, globals and switch-local assignments stay legal", test_pointer_scope_ok)

    # Layer 16: v1.1 cross-function escape and r@ promise checks
    assert_raises("16. v1.1 xfn", "Reject passing a local address to a callee that stores it into a global",
                  SemanticError,
                  "o! p* u4 g; v. keep(p* u4 p) { g m, p; } v. f(v.) { o! u4 x m, 1; keep(a& x); }")

    def test_escape_ok_cases():
        sigil = """
        o! u4 gv m, 1;
        o! p* u4 g;
        v. keep(p* u4 p) { g m, p; }
        v. keep_local(p* u4 p) { o! p* u4 local m, p; o! u4 t m, p* local; }
        v. f(v.) { keep(a& gv); keep_local(a& gv); }
        """
        check_source(sigil, "escape_ok.sigil")

    assert_ok("16. v1.1 xfn", "Global addresses and local-only stores are not escapes", test_escape_ok_cases)

    assert_raises("16. v1.1 xfn", "Reject passing one object to an r@ parameter and another parameter",
                  SemanticError,
                  "u4 sum(r@ p* u4 a, p* u4 b) { r; a[0] + b[0]; } i4 f(v.) { o! u4[4] arr m, { 1, 2, 3, 4 }; r; (i4)sum(arr, arr); }")
    assert_raises("16. v1.1 xfn", "Reject touching an object directly after a local r@ pointer claims it",
                  SemanticError,
                  "i4 f(v.) { o! u4[4] arr m, { 1, 2, 3, 4 }; o! r@ p* u4 p m, a& arr[0]; o! u4 x m, arr[1]; r; (i4)x; }")

    def test_restrict_ok_cases():
        sigil = """
        u4 sum(r@ p* u4 a, r@ p* u4 b) { r; a[0] + b[0]; }
        i4 f(v.) {
            o! u4[2] x m, { 1, 2 };
            o! u4[2] y m, { 3, 4 };
            o! u4 s m, sum(x, y);
            o! r@ p* u4 p m, a& x[0];
            o! u4 t m, p[1];
            r; (i4)s + (i4)t;
        }
        """
        check_source(sigil, "restrict_ok.sigil")

    assert_ok("16. v1.1 xfn", "Distinct objects per r@ parameter and access through the r@ pointer stay legal",
              test_restrict_ok_cases)

    # Layer 17: shipped examples build and run
    EXAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples")

    def build_example(name):
        src = open(os.path.join(EXAMPLES, name + ".sigil"), encoding="utf-8").read()
        with open(name + ".c", "w") as f:
            f.write(compile_source(src, name + ".sigil"))
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", name + ".c", "-o", name + "_bin"],
            check=True
        )
        return subprocess.run(["./" + name + "_bin"], capture_output=True, text=True, check=True).stdout

    def test_example_regmap():
        out = build_example("regmap")
        assert "ctrl=0x005d" in out, out
        assert "enable=1 parity=2 stop=1 div=5" in out, out
        assert "tx_ready=1" in out, out

    assert_ok("17. examples", "regmap: packed MMIO block, bitfield overlay, offsetof asserts", test_example_regmap)

    def test_example_callbacks():
        out = build_example("callbacks")
        assert "quit after 2 ticks, 2 keys, last='b'" in out, out

    assert_ok("17. examples", "callbacks: global function-pointer table with static handlers", test_example_callbacks)

    def test_example_wire():
        out = build_example("wire")
        assert 'frame 0 kind=1 len=3 more=0 parity=0 payload="ABC"' in out, out
        assert 'frame 1 kind=2 len=2 more=0 parity=1 payload="hi"' in out, out
        assert "frames=2 bytes=9" in out, out

    assert_ok("17. examples", "wire: big-endian frame parse with bitfield header overlay", test_example_wire)

    # Layer 18: tutorial programs build and run
    TUTORIAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples", "tutorial")

    def build_tutorial(name):
        src = open(os.path.join(TUTORIAL, name + ".sigil"), encoding="utf-8").read()
        with open(name + ".c", "w") as f:
            f.write(compile_source(src, name + ".sigil"))
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", name + ".c", "-o", name + "_bin"],
            check=True
        )
        return subprocess.run(["./" + name + "_bin"], capture_output=True, text=True, check=True).stdout

    def test_tut_hello():
        out = build_tutorial("01_hello")
        assert "area(4 x 6) = 24" in out, out

    assert_ok("18. tutorial", "01 hello: variable, function, printf", test_tut_hello)

    def test_tut_primes():
        out = build_tutorial("02_primes")
        assert "count=15" in out, out
        assert "47 " in out, out

    assert_ok("18. tutorial", "02 primes: while loop, bool array, macro constant", test_tut_primes)

    def test_tut_hexdump():
        out = build_tutorial("03_hexdump")
        assert "|Sigil-C ......AB|" in out, out
        assert "| ~..3DUf|" in out, out

    assert_ok("18. tutorial", "03 hexdump: const pointer parameter, 16-byte rows", test_tut_hexdump)

    def test_tut_calc():
        out = build_tutorial("04_calc")
        assert "6*7=42" in out, out
        assert "1/0=0" in out, out

    assert_ok("18. tutorial", "04 calc: enum-indexed function-pointer table", test_tut_calc)

    def test_tut_ringbuf():
        out = build_tutorial("05_ringbuf")
        assert "popped: 1 2 3 4 5 6 7" in out, out
        assert "dropped: 3" in out, out

    assert_ok("18. tutorial", "05 ringbuf: volatile fields, full-ring drop counting", test_tut_ringbuf)

    def test_tut_uart():
        out = build_tutorial("06_uart")
        assert "ctrl=0x2587 enable=1 mode=3 baud=1200" in out, out

    assert_ok("18. tutorial", "06 uart: packed block, bitfield overlay, offsetof asserts", test_tut_uart)

    def test_tut_library():
        src = open(os.path.join(TUTORIAL, "07_library.sigil"), encoding="utf-8").read()
        h = compile_header(src, "07_library.sigil", "lib.h")
        assert "uint32_t scale(" in h, h
        assert "clamp_u4" not in h, h

    assert_ok("18. tutorial", "07 library: --emit-header keeps s@ symbols internal", test_tut_library)

    # Layer 19: builtin-type objects may omit o!
    def test_omit_marker_builtin():
        sigil = "u4 g m, 7;\ni4 main(v.) { u4 x m, 3; r; (i4)(g + x) - 10; }"
        with open("nomark.c", "w") as f:
            f.write(compile_source(sigil, "nomark.sigil"))
        subprocess.run(
            ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "nomark.c", "-o", "nomark_bin"],
            check=True
        )
        assert subprocess.run(["./nomark_bin"], check=False).returncode == 0

    assert_ok("19. marker", "Builtin-type objects may omit o! at file and block scope", test_omit_marker_builtin)

    assert_raises("19. marker", "User-defined type objects still require o!",
                  ParseError, "s{ SG { i4 x; }; i4 main(v.) { SG ctx; r; 0; }")
    assert_raises("19. marker", "Pointer declarations still require o!",
                  ParseError, "i4 main(v.) { p* u4 p; r; 0; }")

    def test_omit_marker_for():
        sigil = "i4 main(v.) { o! i4 s m, 0; f~ (u4 i m, 0; i < 3; i m+ 1) { s m+ (i4)i; } r; s - 3; }"
        check_source(sigil, "for_nomark.sigil")

    assert_ok("19. marker", "A f~ initializer may omit o! for builtin types", test_omit_marker_for)

    # Layer 20: pool example - multi-level pointers and read/write split
    def test_example_pool():
        out = build_example("pool")
        assert "block0: head=101 next=202" in out, out
        assert "block1: head=404 (via slot_alpha)" in out, out
        assert "deep_read=303 allocated=2" in out, out
        assert "checksum=1012" in out, out

        # README 里嵌的是同一份源码：漂移就红
        repo = os.path.dirname(os.path.abspath(__file__))
        readme = open(os.path.join(repo, "README.md"), encoding="utf-8").read()
        head = readme.index("完整源码（[`examples/pool.sigil`]")
        block = readme[head:].split("```sigil\n", 1)[1].split("\n```", 1)[0]
        src = open(os.path.join(EXAMPLES, "pool.sigil"), encoding="utf-8").read().rstrip("\n")
        assert block.strip() == src.strip(), "README pool block drifted from examples/pool.sigil"

    assert_ok("20. pool", "pool: p* chains, const split, c@ p* pinned slot, o! entities", test_example_pool)

    # Layer 21: --build links a directory of .sigil files
    def test_build_mode():
        work = tempfile.mkdtemp(prefix="sigil-build-")
        src_dir = os.path.join(work, "src")
        os.makedirs(src_dir)
        with open(os.path.join(src_dir, "a.sigil"), "w") as f:
            f.write("i4 triple(i4 x) { r; x * 3; }\n")
        with open(os.path.join(src_dir, "b.sigil"), "w") as f:
            f.write('#include <stdio.h>\ni4 triple(i4 x);\ni4 main(v.) { printf("%d\\n", triple(7)); r; 0; }\n')
        exe = os.path.join(work, "app")
        r = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sigilc.py"),
             "--build", src_dir, "-o", exe, "--run"],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "21" in r.stdout, r.stdout
        assert os.path.exists(os.path.join(src_dir, ".sigil-build", "a.c"))

    assert_ok("21. build", "--build transpiles a directory and links the results", test_build_mode)

    if failures:
        print(f"=== {passed}/{total} PASSED, {len(failures)} FAILED ===")
        for layer, desc, why in failures:
            print(f"  - [{layer}] {desc}\n      {why}")
        raise SystemExit(1)
    print(f"=== ALL {passed}/{total} TESTS IN 21-LAYER MATRIX PASSED! ===")

if __name__ == "__main__":
    run_test_matrix()
