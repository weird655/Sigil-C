"""Sigil-ASM: experimental direct x86-64 System V backend.

This is deliberately a brute-force first cut: integer/pointer locals,
arithmetic, comparisons, branches, loops, direct calls and string literals.
Unsupported constructs fail loudly instead of silently miscompiling.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .lexer import EXTERNAL_C_SPELLING, Lexer
from .nodes import (
    AssignStmt,
    BinaryExpr,
    BlockStmt,
    CallExpr,
    CastExpr,
    DoWhileStmt,
    ExprNode,
    ExprStmt,
    ForStmt,
    FuncDefNode,
    IdentExpr,
    IfStmt,
    IndexExpr,
    JumpStmt,
    LiteralExpr,
    PreprocNode,
    ReturnStmt,
    StmtNode,
    TernaryExpr,
    TrapStmt,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)
from .parser import Parser
from .type_system import ArrayType, BaseType, PointerType


class AsmError(Exception):
    pass


_TYPE_SIZE = {
    "i1": 1, "u1": 1, "char": 1, "bool": 1,
    "i2": 2, "u2": 2, "short": 2,
    "i4": 4, "u4": 4, "int": 4, "unsigned": 4, "uint32_t": 4, "int32_t": 4,
    "i8": 8, "u8": 8, "long": 8, "uint64_t": 8, "int64_t": 8,
}


def _type_size(t) -> int:
    if isinstance(t, (PointerType, ArrayType)):
        return 8 if isinstance(t, PointerType) else 8
    if isinstance(t, BaseType):
        if t.c_name in _TYPE_SIZE:
            return _TYPE_SIZE[t.c_name]
        if t.c_name in ("float",):
            return 4
        if t.c_name in ("double", "long double"):
            return 8
    return 8


def _is_global_name(name: str, globals_: Dict[str, str]) -> bool:
    return name in globals_


class AsmGenerator:
    def __init__(self, filename: str = "input.sigil", abi: str = "sysv"):
        self.filename = filename
        self.abi = abi
        self.lines: List[str] = []
        self.strings: Dict[str, str] = {}
        self.globals: Dict[str, str] = {}
        self.locals: Dict[str, int] = {}
        self.frame_size = 0
        self.used = 0
        self.label_id = 0
        self.ret_label = ""
        self.break_labels: List[str] = []
        self.continue_labels: List[str] = []
        self.string_id = 0

    def emit(self, text: str = "") -> None:
        self.lines.append(("    " + text) if text else "")

    def label(self, prefix: str = "L") -> str:
        self.label_id += 1
        return f".L{prefix}{self.label_id}"

    def fail(self, why: str) -> None:
        raise AsmError(f"{self.filename}: ASM backend does not support {why}")

    # ------------------------------------------------------------------ types
    def slot(self, name: str) -> int:
        if name not in self.locals:
            self.used += 8
            self.locals[name] = self.used
        return self.locals[name]

    def mem(self, name: str) -> str:
        return f"-{self.slot(name)}(%rbp)"

    def global_mem(self, name: str) -> str:
        return f"{name}(%rip)"

    # --------------------------------------------------------------- functions
    def collect_vars(self, stmt: Optional[StmtNode]) -> None:
        if stmt is None:
            return
        if isinstance(stmt, VarDeclStmt):
            if not stmt.is_static:
                self.slot(stmt.name)
        elif isinstance(stmt, BlockStmt):
            for s in stmt.stmts:
                self.collect_vars(s)
        elif isinstance(stmt, IfStmt):
            self.collect_vars(stmt.then_block)
            self.collect_vars(stmt.else_branch)
        elif isinstance(stmt, (WhileStmt, DoWhileStmt)):
            self.collect_vars(stmt.body)
        elif isinstance(stmt, ForStmt):
            self.collect_vars(stmt.init_stmt)
            self.collect_vars(stmt.body)

    def gen_function(self, fn: FuncDefNode) -> None:
        if fn.body is None:
            return
        self.locals = {}
        self.used = 0
        self.break_labels = []
        self.continue_labels = []
        # params first
        for _, pname in fn.params:
            self.slot(pname)
        self.collect_vars(fn.body)
        self.frame_size = ((self.used + 15) // 16) * 16
        self.ret_label = self.label("ret")
        self.lines.append(f".globl {fn.name}")
        self.lines.append(f"{fn.name}:")
        self.emit("pushq %rbp")
        self.emit("movq %rsp, %rbp")
        if self.frame_size:
            self.emit(f"subq ${self.frame_size}, %rsp")
        if self.abi == "win64":
            regs = ["%rcx", "%rdx", "%r8", "%r9"]
            regs32 = ["%ecx", "%edx", "%r8d", "%r9d"]
        else:
            regs = ["%rdi", "%rsi", "%rdx", "%rcx", "%r8", "%r9"]
            regs32 = ["%edi", "%esi", "%edx", "%ecx", "%r8d", "%r9d"]
        for i, (ptype, pname) in enumerate(fn.params):
            if i >= len(regs):
                self.fail(f"more than {len(regs)} parameters for {self.abi} ASM backend")
            if _type_size(ptype) == 8:
                self.emit(f"movq {regs[i]}, {self.mem(pname)}")
            else:
                self.emit(f"movslq {regs32[i]}, %rax")
                self.emit(f"movq %rax, {self.mem(pname)}")
        self.gen_stmt(fn.body)
        if not self.lines or self.lines[-1] != f"{self.ret_label}:":
            self.lines.append(f"{self.ret_label}:")
        self.emit("leave")
        self.emit("ret")
        self.lines.append("")

    # --------------------------------------------------------------- statements
    def gen_stmt(self, stmt: Optional[StmtNode]) -> None:
        if stmt is None:
            return
        if isinstance(stmt, BlockStmt):
            for s in stmt.stmts:
                self.gen_stmt(s)
            return
        if isinstance(stmt, VarDeclStmt):
            if stmt.is_static:
                self.fail("static local variables")
            if stmt.init_expr is not None:
                self.expr(stmt.init_expr)
            else:
                self.emit("xorl %eax, %eax")
            self.emit(f"movq %rax, {self.mem(stmt.name)}")
            return
        if isinstance(stmt, ExprStmt):
            self.expr(stmt.expr)
            return
        if isinstance(stmt, AssignStmt):
            self.gen_assign(stmt)
            return
        if isinstance(stmt, ReturnStmt):
            if stmt.expr is not None:
                self.expr(stmt.expr)
            else:
                self.emit("xorl %eax, %eax")
            self.emit(f"jmp {self.ret_label}")
            return
        if isinstance(stmt, IfStmt):
            else_l = self.label("else")
            end_l = self.label("endif")
            self.expr(stmt.cond)
            self.emit("testq %rax, %rax")
            self.emit(f"jz {else_l}")
            self.gen_stmt(stmt.then_block)
            self.emit(f"jmp {end_l}")
            self.lines.append(f"{else_l}:")
            if stmt.else_branch is not None:
                self.gen_stmt(stmt.else_branch)
            self.lines.append(f"{end_l}:")
            return
        if isinstance(stmt, WhileStmt):
            top = self.label("while")
            end = self.label("endwhile")
            self.break_labels.append(end)
            self.continue_labels.append(top)
            self.lines.append(f"{top}:")
            self.expr(stmt.cond)
            self.emit("testq %rax, %rax")
            self.emit(f"jz {end}")
            self.gen_stmt(stmt.body)
            self.emit(f"jmp {top}")
            self.lines.append(f"{end}:")
            self.break_labels.pop()
            self.continue_labels.pop()
            return
        if isinstance(stmt, DoWhileStmt):
            top = self.label("do")
            cont = self.label("docont")
            end = self.label("enddo")
            self.break_labels.append(end)
            self.continue_labels.append(cont)
            self.lines.append(f"{top}:")
            self.gen_stmt(stmt.body)
            self.lines.append(f"{cont}:")
            self.expr(stmt.cond)
            self.emit("testq %rax, %rax")
            self.emit(f"jnz {top}")
            self.lines.append(f"{end}:")
            self.break_labels.pop()
            self.continue_labels.pop()
            return
        if isinstance(stmt, ForStmt):
            top = self.label("for")
            cont = self.label("forcont")
            end = self.label("endfor")
            if stmt.init_stmt is not None:
                self.gen_stmt(stmt.init_stmt)
            self.break_labels.append(end)
            self.continue_labels.append(cont)
            self.lines.append(f"{top}:")
            if stmt.cond_expr is not None:
                self.expr(stmt.cond_expr)
                self.emit("testq %rax, %rax")
                self.emit(f"jz {end}")
            self.gen_stmt(stmt.body)
            self.lines.append(f"{cont}:")
            if stmt.step_stmt is not None:
                self.gen_stmt(stmt.step_stmt)
            self.emit(f"jmp {top}")
            self.lines.append(f"{end}:")
            self.break_labels.pop()
            self.continue_labels.pop()
            return
        if isinstance(stmt, JumpStmt):
            if stmt.keyword == "break":
                if not self.break_labels:
                    self.fail("break outside loop")
                self.emit(f"jmp {self.break_labels[-1]}")
            elif stmt.keyword == "continue":
                if not self.continue_labels:
                    self.fail("continue outside loop")
                self.emit(f"jmp {self.continue_labels[-1]}")
            else:
                self.fail(f"jump {stmt.keyword}")
            return
        if isinstance(stmt, TrapStmt):
            self.emit("ud2")
            return
        if isinstance(stmt, PreprocNode):
            return
        self.fail(type(stmt).__name__)

    def gen_assign(self, stmt: AssignStmt) -> None:
        if isinstance(stmt.target, IdentExpr):
            name = stmt.target.name
            if stmt.op == "=":
                self.expr(stmt.value)
            else:
                self.load_lvalue(name)
                self.emit("pushq %rax")
                self.expr(stmt.value)
                self.emit("movq %rax, %rcx")
                self.emit("popq %rax")
                self.binop(stmt.op[:-1], "%rcx")
            if name in self.globals:
                self.emit(f"movq %rax, {self.global_mem(name)}")
            else:
                self.emit(f"movq %rax, {self.mem(name)}")
            return
        self.fail("non-identifier assignment in ASM backend")

    def load_lvalue(self, name: str) -> None:
        if name in self.globals:
            self.emit(f"movq {self.global_mem(name)}, %rax")
        else:
            self.emit(f"movq {self.mem(name)}, %rax")

    # --------------------------------------------------------------- expressions
    def expr(self, e: ExprNode) -> None:
        if isinstance(e, LiteralExpr):
            self.gen_literal(e)
            return
        if isinstance(e, IdentExpr):
            if e.name in self.globals:
                self.emit(f"movq {self.global_mem(e.name)}, %rax")
            elif e.name in self.locals:
                self.emit(f"movq {self.mem(e.name)}, %rax")
            else:
                self.fail(f"identifier '{e.name}' (function pointers/externs)")
            return
        if isinstance(e, UnaryExpr):
            self.gen_unary(e)
            return
        if isinstance(e, BinaryExpr):
            self.gen_binary(e)
            return
        if isinstance(e, CastExpr):
            self.expr(e.operand)
            size = _type_size(e.target_type)
            if size == 1:
                self.emit("movsbq %al, %rax")
            elif size == 2:
                self.emit("movswq %ax, %rax")
            elif size == 4:
                self.emit("movslq %eax, %rax")
            return
        if isinstance(e, CallExpr):
            self.gen_call(e)
            return
        if isinstance(e, IndexExpr):
            self.gen_index(e)
            return
        if isinstance(e, TernaryExpr):
            else_l = self.label("tern_else")
            end_l = self.label("tern_end")
            self.expr(e.cond)
            self.emit("testq %rax, %rax")
            self.emit(f"jz {else_l}")
            self.expr(e.then_expr)
            self.emit(f"jmp {end_l}")
            self.lines.append(f"{else_l}:")
            self.expr(e.else_expr)
            self.lines.append(f"{end_l}:")
            return
        self.fail(type(e).__name__)

    def gen_literal(self, e: LiteralExpr) -> None:
        code = e.code.strip()
        if e.lit_kind == "STRING":
            label = f".Lstr{self.string_id}"
            self.string_id += 1
            self.strings[label] = code
            self.emit(f"leaq {label}(%rip), %rax")
            return
        if e.lit_kind == "CHAR":
            try:
                val = ord(code.strip("'"))
            except Exception:
                self.fail(f"char literal {code}")
            self.emit(f"movq ${val}, %rax")
            return
        if e.lit_kind == "FLOAT_NUM":
            self.fail("float literal")
        raw = code.replace("u", "").replace("U", "").replace("l", "").replace("L", "")
        try:
            val = int(raw, 0)
        except ValueError:
            self.fail(f"integer literal {code}")
        self.emit(f"movq ${val}, %rax")

    def gen_unary(self, e: UnaryExpr) -> None:
        if e.op == "&":
            if isinstance(e.operand, IdentExpr):
                name = e.operand.name
                if name in self.globals:
                    self.emit(f"leaq {self.global_mem(name)}, %rax")
                else:
                    self.emit(f"leaq {self.mem(name)}, %rax")
                return
            self.fail("address-of non-identifier")
        self.expr(e.operand)
        if e.op == "-":
            self.emit("negq %rax")
        elif e.op == "!":
            self.emit("testq %rax, %rax")
            self.emit("sete %al")
            self.emit("movzbq %al, %rax")
        elif e.op == "~":
            self.emit("notq %rax")
        elif e.op == "+":
            pass
        elif e.op == "*":
            self.emit("movq (%rax), %rax")
        else:
            self.fail(f"unary {e.op}")

    def gen_binary(self, e: BinaryExpr) -> None:
        op = e.op
        if op in ("&&", "||"):
            end = self.label("logicend")
            short = self.label("logicshort")
            self.expr(e.left)
            self.emit("testq %rax, %rax")
            self.emit(f"{'jz' if op == '&&' else 'jnz'} {short}")
            self.expr(e.right)
            self.emit("testq %rax, %rax")
            self.emit("setne %al")
            self.emit("movzbq %al, %rax")
            self.emit(f"jmp {end}")
            self.lines.append(f"{short}:")
            self.emit(f"movq ${0 if op == '&&' else 1}, %rax")
            self.lines.append(f"{end}:")
            return
        self.expr(e.left)
        self.emit("pushq %rax")
        self.expr(e.right)
        self.emit("movq %rax, %rcx")
        self.emit("popq %rax")
        if op in ("+", "-", "*", "&", "|", "^"):
            self.binop(op, "%rcx")
            return
        if op in ("/", "%"):
            self.emit("cqto")
            self.emit("idivq %rcx")
            if op == "%":
                self.emit("movq %rdx, %rax")
            return
        if op in ("<<", ">>"):
            self.emit("movq %rcx, %rcx")
            self.emit("salq %cl, %rax" if op == "<<" else "sarq %cl, %rax")
            return
        if op in ("==", "!=", "<", "<=", ">", ">="):
            self.emit("cmpq %rcx, %rax")
            cc = {"==": "e", "!=": "ne", "<": "l", "<=": "le", ">": "g", ">=": "ge"}[op]
            self.emit(f"set{cc} %al")
            self.emit("movzbq %al, %rax")
            return
        self.fail(f"binary {op}")

    def binop(self, op: str, rhs: str) -> None:
        ins = {"+": "addq", "-": "subq", "*": "imulq", "&": "andq", "|": "orq", "^": "xorq"}.get(op)
        if ins is None:
            self.fail(f"binary {op}")
        self.emit(f"{ins} {rhs}, %rax")

    def gen_index(self, e: IndexExpr) -> None:
        self.expr(e.base)
        self.emit("pushq %rax")
        self.expr(e.index)
        self.emit("movq %rax, %rcx")
        self.emit("popq %rax")
        self.emit("leaq (%rax,%rcx,1), %rax")
        self.emit("movq (%rax), %rax")

    def gen_call(self, e: CallExpr) -> None:
        if not isinstance(e.callee, IdentExpr):
            self.fail("indirect call")
        assert isinstance(e.callee, IdentExpr)
        name = e.callee.name
        for a in e.args:
            self.expr(a)
            self.emit("pushq %rax")
        regs = (["%rcx", "%rdx", "%r8", "%r9"] if self.abi == "win64"
                else ["%rdi", "%rsi", "%rdx", "%rcx", "%r8", "%r9"])
        if len(e.args) > len(regs):
            self.fail(f"more than {len(regs)} call arguments for {self.abi} ASM backend")
        for i in range(len(e.args) - 1, -1, -1):
            self.emit(f"popq {regs[i]}")
        self.emit("xorl %eax, %eax")
        self.emit("subq $32, %rsp")
        self.emit(f"call {name}")
        self.emit("addq $32, %rsp")

    # --------------------------------------------------------------- top level
    def generate(self, nodes: List[StmtNode]) -> str:
        funcs = []
        for node in nodes:
            if isinstance(node, PreprocNode):
                continue
            if isinstance(node, VarDeclStmt):
                self.globals[node.name] = "global"
                if node.init_expr is None:
                    self.lines.append(f".comm {node.name},8,8")
                else:
                    self.lines.append(".data")
                    self.lines.append(".align 8")
                    self.lines.append(f"{node.name}:")
                    # only integer constant globals
                    if isinstance(node.init_expr, LiteralExpr):
                        self.gen_literal(node.init_expr)
                        # gen_literal emitted into .text; use value directly instead
                        self.lines.pop()
                        raw = node.init_expr.code
                        self.lines.append(f"    .quad {raw}")
                    else:
                        self.fail("non-constant global initializer")
                continue
            if isinstance(node, FuncDefNode):
                funcs.append(node)
                continue
            self.fail(type(node).__name__)
        self.lines.append(".text")
        for fn in funcs:
            self.gen_function(fn)
        if self.strings:
            self.lines.append(".section .rodata")
            for label, code in self.strings.items():
                self.lines.append(f"{label}:")
                self.lines.append(f"    .string {code}")
        return "\n".join(self.lines) + "\n"


def compile_asm(src: str, filename: str = "input.sigil", abi: str = "sysv") -> str:
    EXTERNAL_C_SPELLING.clear()
    tokens = Lexer(src, filename).tokenize()
    ast = Parser(tokens, filename).parse_program()
    return AsmGenerator(filename, abi).generate(ast)
