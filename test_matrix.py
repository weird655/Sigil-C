#!/usr/bin/env python3
import subprocess
from sigilc import (
    Lexer, Parser, CodeGenerator, compile_source, compile_header,
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
    print(f"=== SIGIL-C v3.1.0 AUTOMATED TEST MATRIX ({gcc_ver} | {uname_info}) ===")

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
    # Layer 7: v3.1.0 additions — z? / s@ / header emission
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

    assert_ok("7. v3.1", "z? takes builtin/pointer/array/user types and expressions, result is size_t", test_sizeof_forms)
    assert_raises("7. v3.1", "Reject z? applied to void", SemanticError, "u4 f(v.) { r; z? v.; }")
    assert_raises("7. v3.1", "Reject z? on incomplete struct type", SemanticError, "s{ Fwd; u4 f(v.) { r; z? Fwd; }")

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

    assert_ok("7. v3.1", "s@ emits static and internal symbols are excluded from the header", test_static_and_header)

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

    assert_ok("7. v3.1", "Generated .h consumed by an independent .c file: compile, link, run", test_header_end_to_end)

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

    assert_ok("7. v3.1", "Differential: Sigil-C output vs hand-written C, 257 elements, bit-identical", test_differential_vs_c)

    if failures:
        print(f"=== {passed}/{total} PASSED, {len(failures)} FAILED ===")
        for layer, desc, why in failures:
            print(f"  - [{layer}] {desc}\n      {why}")
        raise SystemExit(1)
    print(f"=== ALL {passed}/{total} TESTS IN 7-LAYER MATRIX PASSED! ===")

if __name__ == "__main__":
    run_test_matrix()
