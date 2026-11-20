"""Sigil-C codegen (generated split of sigilc.py)."""

from typing import Dict, List, Optional

from .nodes import (
    AssignStmt,
    Attribute,
    BitSliceExpr,
    BlockStmt,
    DoWhileStmt,
    EnumDefNode,
    ExprStmt,
    ExternalTypeNode,
    ForStmt,
    FuncDefNode,
    GotoStmt,
    IdentExpr,
    IfStmt,
    IndexExpr,
    JumpStmt,
    LabelStmt,
    MemberExpr,
    PreprocNode,
    ReturnStmt,
    StaticAssertStmt,
    StmtNode,
    StructDefNode,
    SwitchStmt,
    TnxFnExpr,
    TnxNode,
    TrapStmt,
    UnaryExpr,
    VarDeclStmt,
    VaStmt,
    WhileStmt,
    checked_binary,
    emit_expr,
    set_checked_arith,
    slice_mask,
    slice_uint_type,
)
from .preamble import C99_HEADER, C99_HEADER_BODY, CHECKED_HEADER
from .type_system import ArrayType, BaseType, PointerType, format_c_declarator


def _field_size_expr(ftype) -> Optional[str]:
    """C expression for the registered field size, or None if unknown."""
    if isinstance(ftype, BaseType):
        return f"sizeof({format_c_declarator(ftype)})"
    if isinstance(ftype, PointerType):
        return "sizeof(void *)"
    if isinstance(ftype, ArrayType) and ftype.size_val is not None:
        inner = _field_size_expr(ftype.element_type)
        if inner:
            return f"({inner} * {ftype.size_val})"
    return None


TNX_HELPER = """\
/* TNX prepared-packet descriptors: 10 priority lanes x 16 sequence slots. */
typedef union SigilTnxPayload {
    void *data;
    void (*fn)(void);
} SigilTnxPayload;

typedef struct SigilTnxNode {
    int32_t width;
    SigilTnxPayload payload;
    const struct SigilTnxNode *next;
    uint8_t locked;
    uint8_t priority;
    uint8_t seq;
} SigilTnxNode;

typedef struct SigilTnxQueue {
    const SigilTnxNode *slot[10][16];
} SigilTnxQueue;

static inline void sigil_tnx_queue_init(SigilTnxQueue *q) {
    int p, s;
    for (p = 0; p < 10; p++)
        for (s = 0; s < 16; s++) q->slot[p][s] = NULL;
}

static inline int sigil_tnx_push(SigilTnxQueue *q, const SigilTnxNode *n) {
    if (!q || !n || !n->locked || n->priority > 9 || n->seq > 15) return -1;
    if (q->slot[n->priority][n->seq]) return -1;
    q->slot[n->priority][n->seq] = n;
    return 0;
}

static inline const SigilTnxNode *sigil_tnx_pop(SigilTnxQueue *q) {
    int p, s;
    if (!q) return NULL;
    for (p = 9; p >= 0; p--) {
        for (s = 0; s < 16; s++) {
            if (q->slot[p][s]) {
                const SigilTnxNode *n = q->slot[p][s];
                q->slot[p][s] = NULL;
                return n;
            }
        }
    }
    return NULL;
}

"""

class CodeGenerator:
    def __init__(self, filename: str = "input.sigil", header_mode: bool = False,
                 prelude_include: Optional[str] = None, bounds_check: bool = False,
                 cli_defines: Optional[Dict[str, str]] = None,
                 line_directives: bool = True, trap_trace: bool = False,
                 shadow_stack: bool = False, namespace: str = "", checked_arith: bool = False, checked_strict: bool = False):
        self.safe_filename = filename.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '')
        self.line_directives = line_directives
        self.header_mode = header_mode
        self.prelude_include = prelude_include
        self.bounds_check = bounds_check
        self.trap_trace = trap_trace
        self.shadow_stack = shadow_stack
        self.checked_arith = checked_arith or checked_strict
        self.checked_strict = checked_strict
        self._tmp_counter = 0
        self.namespace = namespace
        self.cli_defines = cli_defines or {}
        self.lines: List[str] = []

    def _emit(self, code: str, line: int, indent: int = 0):
        pad = "    " * indent
        if self.header_mode:
            self.lines.append(f"{pad}{code}\n")
        elif self.line_directives:
            self.lines.append(f'#line {line} "{self.safe_filename}"\n{pad}{code}\n')
        else:
            self.lines.append(f"{pad}{code}\n")

    def _attrs_c(self, attrs: List[Attribute]) -> str:
        """属性列表 → 'SIGIL_ATTR(a, b(...))'；无属性时返回空串。"""
        if not attrs:
            return ""
        return "SIGIL_ATTR(" + ", ".join(a.render() for a in attrs) + ")"

    @staticmethod
    def _has_abi_attrs(attrs: List[Attribute]) -> bool:
        """packed / aligned 会影响类型布局，后端不支持属性时不能静默丢弃。"""
        return any(a.name in ('packed', 'aligned') for a in attrs)

    def _emit_cli_defines(self) -> None:
        for name, value in self.cli_defines.items():
            self.lines.append(f"#ifndef {name}\n#define {name} {value}\n#endif\n")

    def generate(self, nodes: List[StmtNode]) -> str:
        set_checked_arith(self.checked_arith)
        if self.bounds_check:
            self.lines.append("#define SIGIL_BOUNDS_CHECK 1\n")
        if self.checked_arith:
            self.lines.append("#define SIGIL_CHECKED_ARITH 1\n")
        if self.checked_strict:
            self.lines.append("#define SIGIL_CHECKED_STRICT 1\n")
        if self.trap_trace:
            self.lines.append("#define SIGIL_TRAP_TRACE 1\n")
        if self.shadow_stack:
            self.lines.append("#define SIGIL_SHADOW_STACK 1\n")
        if self.prelude_include:
            self.lines.append(f'#include "{self.prelude_include}"\n')
        else:
            self.lines.append(C99_HEADER)
        if self.checked_arith:
            self.lines.append(CHECKED_HEADER)
        self._emit_cli_defines()
        tnx_nodes = [n for n in nodes if isinstance(n, TnxNode)]
        if tnx_nodes:
            self.lines.append(TNX_HELPER)
            for n in tnx_nodes:
                self.lines.append(f"extern const SigilTnxNode {n.name};\n")
        for node in nodes:
            self.gen_top(node)
        return "".join(self.lines)

    def generate_header(self, nodes: List[StmtNode], guard: str) -> str:
        self.lines.append(f"/* Public interface generated by Sigil-C from {self.safe_filename}. DO NOT EDIT. */\n")
        self.lines.append(f"#ifndef {guard}\n#define {guard}\n\n")
        if self.bounds_check:
            self.lines.append("#define SIGIL_BOUNDS_CHECK 1\n")
        if self.checked_arith:
            self.lines.append("#define SIGIL_CHECKED_ARITH 1\n")
        if self.checked_strict:
            self.lines.append("#define SIGIL_CHECKED_STRICT 1\n")
        if self.prelude_include:
            self.lines.append(f'#include "{self.prelude_include}"\n')
        else:
            self.lines.append(C99_HEADER_BODY)
        self._emit_cli_defines()
        for node in nodes:
            self.gen_top(node)
        self.lines.append(f"\n#endif /* {guard} */\n")
        return "".join(self.lines)

    def gen_top(self, node: StmtNode):
        if isinstance(node, PreprocNode):
            self._emit(node.text, node.line, indent=0)
        elif isinstance(node, StructDefNode):
            if node.emit_typedef:
                self._emit(f"typedef {node.kind} {node.name} {node.name};", node.line)
            if node.fields:
                if node.alignment:
                    self._emit("#if SIGIL_HAS_ALIGNMENT", node.line)
                if self._has_abi_attrs(node.attrs):
                    self._emit("#if !SIGIL_HAS_ATTR", node.line)
                    self._emit(
                        f'#error "Sigil-C a@(packed/aligned) on type {node.name} requires a GNU-compatible compiler"',
                        node.line,
                    )
                    self._emit("#endif", node.line)
                if node.alignment:
                    self._emit(f"SIGIL_ALIGNED_TAG({node.kind}, {node.name}, {node.alignment}) {{", node.line)
                else:
                    self._emit(f"{node.kind} {node.name} {{", node.line)
                for index, f in enumerate(node.fields):
                    align_member = f"SIGIL_ALIGN_MEMBER({node.alignment}) " if index == 0 and node.alignment else ""
                    field_decl = format_c_declarator(f.var_type, f.name)
                    if f.bit_width is not None:
                        field_decl = f"{field_decl} : {f.bit_width}"
                    field_attr = self._attrs_c(f.attrs)
                    if field_attr:
                        field_decl = f"{field_decl} {field_attr}"
                    self._emit(f"{align_member}{field_decl};", f.line, indent=1)
                type_attr = self._attrs_c(node.attrs)
                self._emit(f"}} {type_attr};" if type_attr else "};", node.line)
                if node.alignment:
                    self._emit(
                        f"typedef char SIGIL_ALIGN_CHECK_{node.name}[(SIGIL_ALIGNOF({node.name}) >= {node.alignment}) ? 1 : -1];",
                        node.line,
                    )
                    self._emit("#else", node.line)
                    self._emit(
                        f'#error "Sigil-C a!{node.alignment} requires C11 _Alignas or a supported compiler alignment extension"',
                        node.line,
                    )
                    self._emit("#endif", node.line)
        elif isinstance(node, ExternalTypeNode):
            if node.opaque:
                self._emit(f"/* x! {node.name} -> '{node.c_spelling}' (opaque, from a system header) */", node.line)
            else:
                self._emit(f"/* x! {node.name} -> '{node.c_spelling}' ({node.field_count} checked field(s), "
                           f"definition comes from the system header) */", node.line)
                # x! only registers fields; without this, g? branches trust the
                # registered type while C reads the real header. One combined
                # assert avoids duplicate __LINE__ typedef names.
                checks = []
                for fname, ftype in node.fields.items():
                    if fname in node.bitfields:
                        continue
                    expected = _field_size_expr(ftype)
                    if expected is None:
                        continue
                    checks.append(
                        f"sizeof((({node.c_spelling} *)0)->{fname}) == {expected}")
                if checks:
                    self._emit(
                        f'SIGIL_STATIC_ASSERT(({" && ".join(checks)}), '
                        f'"x! field width drift: {node.name}");',
                        node.line,
                    )
        elif isinstance(node, EnumDefNode):
            self._emit(f"typedef enum {node.name} {{", node.line)
            for idx, (iname, ival) in enumerate(node.items):
                comma = "," if idx < len(node.items) - 1 else ""
                self._emit(f"{iname}{f' = {emit_expr(ival)}' if ival else ''}{comma}", node.line, indent=1)
            self._emit(f"}} {node.name};", node.line)
        elif isinstance(node, FuncDefNode):
            params_c = [format_c_declarator(pt, pname) for pt, pname in node.params]
            if node.is_variadic:
                params_c.append("...")
            fn_sig = format_c_declarator(node.return_type, f"{node.name}({', '.join(params_c) if params_c else 'void'})")
            attr = self._attrs_c(node.attrs)
            attr_prefix = f"{attr} " if attr else ""
            storage = ("static " if node.is_static else "") + ("inline " if node.is_inline else "")
            if self.header_mode:
                if node.body is None:
                    if not node.is_static:
                        self._emit(f"{storage}{attr_prefix}{fn_sig};", node.line)
                    return
                if node.is_static and node.is_inline:
                    self._emit(f"{storage}{attr_prefix}{fn_sig} {{", node.line)
                    for s in node.body.stmts:
                        self.gen_stmt(s, indent=1)
                    self._emit("}", node.line)
                elif not node.is_static:
                    self._emit(f"{storage}{attr_prefix}{fn_sig};", node.line)
                return
            if node.body is None:
                self._emit(f"{storage}{attr_prefix}{fn_sig};", node.line)
            else:
                self._emit(f"{storage}{attr_prefix}{fn_sig} {{", node.line)
                if self.shadow_stack:
                    safe_name = node.name.replace('\\', '\\\\').replace('"', '\\"')
                    self._emit(f'SIGIL_FRAME_SCOPE("{safe_name}");', node.line, indent=1)
                for s in node.body.stmts:
                    self.gen_stmt(s, indent=1)
                self._emit("}", node.line)
        elif isinstance(node, TnxNode):
            if isinstance(node.payload, TnxFnExpr):
                payload = f"{{ .fn = (void (*)(void))({emit_expr(node.payload)}) }}"
            else:
                payload = f"{{ .data = (void *)({emit_expr(node.payload)}) }}"
            nxt = f"&{node.next_name}" if node.next_name else "NULL"
            self._emit(
                f"const SigilTnxNode {node.name} = {{ {node.width}, {payload}, {nxt}, "
                f"1, {node.priority}, {node.seq} }};", node.line)
        elif isinstance(node, StaticAssertStmt):
            self._emit(f"SIGIL_STATIC_ASSERT({emit_expr(node.cond)}, {node.message});", node.line)
        elif isinstance(node, VarDeclStmt):
            decl = format_c_declarator(node.var_type, node.name)
            attr = self._attrs_c(node.attrs)
            if attr:
                decl = f"{decl} {attr}"
            if self.header_mode:
                if not node.is_static:
                    self._emit(f"extern {decl};", node.line)
                return
            if node.is_static:
                self._emit(f"static {decl}{f' = {emit_expr(node.init_expr)}' if node.init_expr else ''};", node.line, indent=0)
            else:
                self.gen_stmt(node, indent=0)

    def _emit_slice_assign(self, s: AssignStmt, indent: int) -> None:
        t = s.target
        assert isinstance(t, BitSliceExpr)
        base = emit_expr(t.base)
        value = emit_expr(s.value)
        typ = format_c_declarator(t.base_type)
        if t.byte_index is not None:
            idx = t.byte_index
            if s.op == '=':
                self._emit(f"((unsigned char *)&({base}))[{idx}] = (unsigned char)({value});", s.line, indent)
            else:
                op = s.op[:-1]
                self._emit(
                    f"((unsigned char *)&({base}))[{idx}] = "
                    f"(unsigned char)(((unsigned char *)&({base}))[{idx}] {op} ({value}));", s.line, indent)
            return
        uint = slice_uint_type(t.base_type)
        mask = slice_mask(t.width)
        clear = f"~((({uint}){mask}) << {t.offset})"
        if s.op == '=':
            rhs = f"((({uint})({value}) & {mask}) << {t.offset})"
        else:
            op = s.op[:-1]
            cur = f"((({uint})({base}) >> {t.offset}) & {mask})"
            rhs = f"(((({cur}) {op} ({uint})({value})) & {mask}) << {t.offset})"
        self._emit(
            f"{base} = ({typ})(((({uint})({base})) & {clear}) | {rhs});", s.line, indent)

    def _format_inline_stmt(self, s: Optional[StmtNode]) -> str:
        if s is None:
            return ""
        if isinstance(s, VarDeclStmt):
            d = format_c_declarator(s.var_type, s.name)
            return f"{d} = {emit_expr(s.init_expr)}" if s.init_expr else d
        if isinstance(s, AssignStmt):
            return f"{emit_expr(s.target)} {s.op} {emit_expr(s.value)}"
        if isinstance(s, ExprStmt):
            return emit_expr(s.expr)
        raise TypeError(f"Unsupported inline stmt: {s}")

    def gen_stmt(self, s: StmtNode, indent: int):
        if isinstance(s, PreprocNode):
            self._emit(s.text, s.line, indent=0)
        elif isinstance(s, VarDeclStmt):
            decl = format_c_declarator(s.var_type, s.name)
            attr = self._attrs_c(s.attrs)
            if attr:
                decl = f"{decl} {attr}"
            if s.init_expr is not None:
                init = f" = {emit_expr(s.init_expr)}"
            elif self.checked_arith and not s.is_static:
                init = " = {0}"
            else:
                init = ""
            self._emit(f"{decl}{init};", s.line, indent)
        elif isinstance(s, AssignStmt):
            if isinstance(s.target, BitSliceExpr):
                self._emit_slice_assign(s, indent)
            else:
                target = emit_expr(s.target)
                value = emit_expr(s.value)
                call = None
                if self.checked_arith and s.op != "=":
                    t = getattr(s.target, "sem_type", None)
                    if isinstance(s.target, IdentExpr):
                        call = checked_binary(s.op[:-1], target, value, t)
                    elif isinstance(s.target, MemberExpr) and getattr(s.target, "is_bitfield", False):
                        bt = getattr(s.target.base, "sem_type", None)
                        call = checked_binary(s.op[:-1], f"(__sigil_ck_bf_{self._tmp_counter + 1}->{s.target.field})", value, t)
                        if call is not None:
                            self._tmp_counter += 1
                            tmp = f"__sigil_ck_bf_{self._tmp_counter}"
                            assert bt is not None
                            base = emit_expr(s.target.base)
                            if isinstance(bt, PointerType):
                                self._emit(f"{format_c_declarator(bt)} {tmp} = {base};", s.line, indent)
                            else:
                                self._emit(f"{format_c_declarator(bt)} *{tmp} = &({base});", s.line, indent)
                            self._emit(f"{tmp}->{s.target.field} = {call};", s.line, indent)
                            call = ""
                    elif isinstance(s.target, (IndexExpr, MemberExpr, UnaryExpr)):
                        call = checked_binary(s.op[:-1], f"(*__sigil_ck_{self._tmp_counter + 1})", value, t)
                        if call is not None:
                            self._tmp_counter += 1
                            tmp = f"__sigil_ck_{self._tmp_counter}"
                            assert t is not None
                            self._emit(f"{format_c_declarator(t)} *{tmp} = &({target});", s.line, indent)
                            self._emit(f"*{tmp} = {call};", s.line, indent)
                            call = ""
                if call is not None:
                    if call:
                        self._emit(f"{target} = {call};", s.line, indent)
                else:
                    self._emit(f"{target} {s.op} {value};", s.line, indent)
        elif isinstance(s, ExprStmt):
            self._emit(f"{emit_expr(s.expr)};", s.line, indent)
        elif isinstance(s, ReturnStmt):
            self._emit(f"return{f' {emit_expr(s.expr)}' if s.expr else ''};", s.line, indent)
        elif isinstance(s, JumpStmt):
            self._emit(f"{s.keyword};", s.line, indent)
        elif isinstance(s, TrapStmt):
            self._emit("SIGIL_TRAP();", s.line, indent)
        elif isinstance(s, DoWhileStmt):
            self._emit("do {", s.line, indent)
            for sub in s.body.stmts:
                self.gen_stmt(sub, indent + 1)
            self._emit(f"}} while ({emit_expr(s.cond)});", s.line, indent)
        elif isinstance(s, StaticAssertStmt):
            self._emit(f"SIGIL_STATIC_ASSERT({emit_expr(s.cond)}, {s.message});", s.line, indent)
        elif isinstance(s, GotoStmt):
            self._emit(f"goto {s.label};", s.line, indent)
        elif isinstance(s, LabelStmt):
            self._emit(f"{s.name}: ;", s.line, indent)
        elif isinstance(s, VaStmt):
            if s.kind == 'start':
                self._emit(f"va_start({emit_expr(s.ap)}, {s.last_name});", s.line, indent)
            elif s.kind == 'copy':
                assert s.ap2 is not None
                self._emit(f"va_copy({emit_expr(s.ap)}, {emit_expr(s.ap2)});", s.line, indent)
            else:
                self._emit(f"va_end({emit_expr(s.ap)});", s.line, indent)
        elif isinstance(s, BlockStmt):
            self._emit("{", s.line, indent)
            for sub in s.stmts:
                self.gen_stmt(sub, indent + 1)
            self._emit("}", s.line, indent)
        elif isinstance(s, IfStmt):
            self._emit(f"if ({emit_expr(s.cond)}) {{", s.line, indent)
            for sub in s.then_block.stmts:
                self.gen_stmt(sub, indent + 1)
            if s.else_branch is None:
                self._emit("}", s.line, indent)
            elif isinstance(s.else_branch, IfStmt):
                self._emit("} else", s.else_branch.line, indent)
                self.gen_stmt(s.else_branch, indent)
            elif isinstance(s.else_branch, BlockStmt):
                self._emit("} else {", s.else_branch.line, indent)
                for sub in s.else_branch.stmts:
                    self.gen_stmt(sub, indent + 1)
                self._emit("}", s.else_branch.line, indent)
        elif isinstance(s, WhileStmt):
            self._emit(f"while ({emit_expr(s.cond)}) {{", s.line, indent)
            for sub in s.body.stmts:
                self.gen_stmt(sub, indent + 1)
            self._emit("}", s.line, indent)
        elif isinstance(s, ForStmt):
            init_c = self._format_inline_stmt(s.init_stmt)
            cond_c = emit_expr(s.cond_expr) if s.cond_expr else ""
            step_c = self._format_inline_stmt(s.step_stmt)
            self._emit(f"for ({init_c}; {cond_c}; {step_c}) {{", s.line, indent)
            for sub in s.body.stmts:
                self.gen_stmt(sub, indent + 1)
            self._emit("}", s.line, indent)
        elif isinstance(s, SwitchStmt):
            self._emit(f"switch ({emit_expr(s.cond)}) {{", s.line, indent)
            for idx, c in enumerate(s.cases):
                if c.value is not None:
                    self._emit(f"case {emit_expr(c.value)}: {{", c.line, indent + 1)
                else:
                    self._emit("default: {", c.line, indent + 1)
                for sub in c.stmts:
                    self.gen_stmt(sub, indent + 2)
                if idx < len(s.cases) - 1 and not self._case_terminates(c.stmts):
                    # 本语言不自动补 break：不写 b!/r;/g! 就是 C 的穿透语义。
                    # 用 GCC/Clang 的 fallthrough 属性显式标注，避免 -Wextra 告警。
                    self._emit("SIGIL_FALLTHROUGH();", c.line, indent + 2)
                self._emit("}", c.line, indent + 1)
            self._emit("}", s.line, indent)

    @staticmethod
    def _case_terminates(stmts: List[StmtNode]) -> bool:
        if not stmts:
            return False
        last = stmts[-1]
        if isinstance(last, JumpStmt) and last.keyword == 'break':
            return True
        return isinstance(last, (ReturnStmt, GotoStmt, TrapStmt))

