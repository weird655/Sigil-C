#!/usr/bin/env python3
"""
Sigil-C v0.5.2 Compiler
Source -> DFA Lexer -> Recursive-Descent AST Parser -> Static Semantic Analyzer -> C99 Codegen
"""

import sys
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Set

# ============================================================================
# 1. DFA Lexer
# ============================================================================

@dataclass
class Token:
    kind: str
    value: str
    line: int
    col: int
    byte_offset: int

SIGIL_KEYWORDS = {
    'i?': 'KW_IF',       'e:': 'KW_ELSE',     'w~': 'KW_WHILE',    'f~': 'KW_FOR',
    'r;': 'KW_RETURN',   'b!': 'KW_BREAK',    'c^': 'KW_CONTINUE', 's?': 'KW_SWITCH',
    'k:': 'KW_CASE',     'd:': 'KW_DEFAULT',  's{': 'KW_STRUCT',   'u{': 'KW_UNION',
    'e{': 'KW_ENUM',     'f^': 'KW_FNPTR',    'p*': 'KW_PTR',      'a&': 'KW_ADDR',
    'c$': 'KW_CONST',    'v.': 'TYPE_VOID',   'b.': 'TYPE_BOOL',
}

SIGIL_OPERATORS = {
    'm,': 'OP_ASSIGN',      'a+': 'OP_ADD_ASSIGN',  's-': 'OP_SUB_ASSIGN',
    'm*': 'OP_MUL_ASSIGN',  'd/': 'OP_DIV_ASSIGN',  '=?': 'OP_EQ',
    '!?': 'OP_NE',          '&.': 'OP_LAND',        '|.': 'OP_LOR',
    '!.': 'OP_LNOT',        '|^': 'OP_BOR',         '&^': 'OP_BAND',
    '^^': 'OP_BXOR',        '~^': 'OP_BNOT',        '->': 'ARROW',
    '<<': 'OP_SHL',         '>>': 'OP_SHR',         '<=': 'OP_LE',
    '>=': 'OP_GE',
}

BASIC_TYPES = {
    'i1': 'int8_t',   'i2': 'int16_t',   'i4': 'int32_t',   'i8': 'int64_t',
    'u1': 'uint8_t',  'u2': 'uint16_t',  'u4': 'uint32_t',  'u8': 'uint64_t',
    'ui1': 'uint8_t', 'ui2': 'uint16_t', 'ui4': 'uint32_t', 'ui8': 'uint64_t',
    'f4': 'float',    'f8': 'double',    'fl': 'long double', 'x4': 'int32_t', 'c1': 'char',
    'int': 'int',     'char': 'char',    'float': 'float',  'double': 'double',
    'size_t': 'size_t', 'ptrdiff_t': 'ptrdiff_t',
    'intptr_t': 'intptr_t', 'uintptr_t': 'uintptr_t',
    'int8_t': 'int8_t', 'int16_t': 'int16_t', 'int32_t': 'int32_t', 'int64_t': 'int64_t',
    'uint8_t': 'uint8_t', 'uint16_t': 'uint16_t', 'uint32_t': 'uint32_t', 'uint64_t': 'uint64_t',
}

INT_C_TYPES = {
    'int8_t', 'int16_t', 'int32_t', 'int64_t',
    'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
    'char', 'bool', 'int', 'size_t', 'ptrdiff_t', 'intptr_t', 'uintptr_t'
}

NUMERIC_C_TYPES = INT_C_TYPES | {'float', 'double', 'long double'}
VALID_SIMPLE_ESCAPES = set('abfnrtv\\\'"?0')
VALID_INTEGER_SUFFIXES = {
    '', 'u', 'U', 'l', 'L', 'll', 'LL',
    'ul', 'uL', 'Ul', 'UL', 'lu', 'lU', 'Lu', 'LU',
    'ull', 'uLL', 'Ull', 'ULL', 'llu', 'llU', 'LLu', 'LLU',
}

class LexerError(Exception):
    pass

class Lexer:
    def __init__(self, source: str, filename: str = "<input>"):
        self.src = source
        self.filename = filename
        self.pos = 0
        self.line = 1
        self.col = 1
        self.byte_offset = 0
        self.n = len(source)
        self.at_line_start = True

    def _peek(self, offset: int = 0) -> str:
        idx = self.pos + offset
        return self.src[idx] if idx < self.n else ''

    def _advance(self, count: int = 1) -> str:
        res = self.src[self.pos : self.pos + count]
        for ch in res:
            self.byte_offset += len(ch.encode('utf-8'))
            if ch == '\n':
                self.line += 1
                self.col = 1
                self.at_line_start = True
            else:
                self.col += 1
        self.pos += count
        return res

    def _scan_escape(self, s_line: int, s_col: int) -> str:
        esc = self._advance()
        if esc in '01234567':
            oct_digits = [esc]
            while len(oct_digits) < 3 and self.pos < self.n and self._peek() in '01234567':
                oct_digits.append(self._advance())
            oct_val = int(''.join(oct_digits), 8)
            if oct_val > 0o377:
                raise LexerError(f"{self.filename}:{s_line}:{s_col}: Octal escape '\\{''.join(oct_digits)}' out of range (max \\377)")
            return '\\' + ''.join(oct_digits)
        if esc in VALID_SIMPLE_ESCAPES:
            return '\\' + esc
        if esc == 'x':
            hex_digits = []
            while self.pos < self.n and (self._peek().isdigit() or self._peek() in 'abcdefABCDEF'):
                hex_digits.append(self._advance())
            if not hex_digits or len(hex_digits) > 2:
                raise LexerError(f"{self.filename}:{s_line}:{s_col}: \\x escape must have 1 or 2 hex digits (got {len(hex_digits)})")
            return '\\x' + ''.join(hex_digits)
        raise LexerError(f"{self.filename}:{s_line}:{s_col}: Unknown escape sequence '\\{esc}'")

    def _scan_number(self, start_line: int, start_col: int, start_byte: int) -> Token:
        buf = []
        is_float = False
        if self._peek() == '0' and self._peek(1) in ('x', 'X'):
            buf.append(self._advance(2))
            hex_digits = 0
            while self.pos < self.n and (self._peek().isdigit() or self._peek() in 'abcdefABCDEF'):
                buf.append(self._advance())
                hex_digits += 1
            has_hex_dot = self._peek() == '.'
            if has_hex_dot:
                buf.append(self._advance())
                while self.pos < self.n and (self._peek().isdigit() or self._peek() in 'abcdefABCDEF'):
                    buf.append(self._advance())
                    hex_digits += 1
            if not hex_digits:
                raise LexerError(f"{self.filename}:{start_line}:{start_col}: Invalid hex literal")
            if self._peek() in ('p', 'P'):
                is_float = True
                buf.append(self._advance())
                if self._peek() in ('+', '-'):
                    buf.append(self._advance())
                if not self._peek().isdigit():
                    raise LexerError(f"{self.filename}:{start_line}:{start_col}: Malformed exponent in hexadecimal float literal")
                while self.pos < self.n and self._peek().isdigit():
                    buf.append(self._advance())
                if self._peek() in 'fFlL':
                    buf.append(self._advance())
            elif has_hex_dot:
                raise LexerError(f"{self.filename}:{start_line}:{start_col}: Hexadecimal floating literal requires a 'p' exponent")
            else:
                while self.pos < self.n and self._peek() in 'uUlL':
                    buf.append(self._advance())
        elif self._peek() == '0' and self._peek(1) in ('b', 'B'):
            self._advance(2)
            bin_digits = []
            while self.pos < self.n and self._peek() in ('0', '1'):
                bin_digits.append(self._advance())
            if not bin_digits:
                raise LexerError(f"{self.filename}:{start_line}:{start_col}: Invalid binary literal")
            suffix = []
            while self.pos < self.n and self._peek() in 'uUlL':
                suffix.append(self._advance())
            # 转换为标准 C99 十六进制字面量以保证 gcc -std=c99 -pedantic 零警告
            buf.append(hex(int(''.join(bin_digits), 2)) + ''.join(suffix))
        else:
            starts_zero = (self._peek() == '0')
            while self.pos < self.n and self._peek().isdigit():
                buf.append(self._advance())
            if self._peek() == '.':
                is_float = True
                digits_before_dot = len(buf)
                buf.append(self._advance())
                digits_after_dot_start = self.pos
                while self.pos < self.n and self._peek().isdigit():
                    buf.append(self._advance())
                if digits_before_dot == 0 and self.pos == digits_after_dot_start:
                    raise LexerError(f"{self.filename}:{start_line}:{start_col}: Malformed float literal after '.'")
            if self._peek() in ('e', 'E'):
                is_float = True
                buf.append(self._advance())
                if self._peek() in ('+', '-'):
                    buf.append(self._advance())
                if not self._peek().isdigit():
                    raise LexerError(f"{self.filename}:{start_line}:{start_col}: Malformed exponent in number literal")
                while self.pos < self.n and self._peek().isdigit():
                    buf.append(self._advance())

            if is_float:
                if self._peek() in 'fFlL':
                    buf.append(self._advance())
            else:
                digits_str = ''.join(buf)
                if starts_zero and len(digits_str) > 1 and any(c not in '01234567' for c in digits_str):
                    raise LexerError(f"{self.filename}:{start_line}:{start_col}: Invalid digit in octal constant '{digits_str}'")
                while self.pos < self.n and self._peek() in 'uUlL':
                    buf.append(self._advance())

        literal = ''.join(buf)
        if not is_float:
            suffix = literal[len(literal.rstrip('uUlL')):]
            if suffix not in VALID_INTEGER_SUFFIXES:
                raise LexerError(f"{self.filename}:{start_line}:{start_col}: Invalid C99 integer suffix '{suffix}'")

        if self._peek() == '.' or self._peek().isalpha() or self._peek() == '_':
            raise LexerError(f"{self.filename}:{start_line}:{start_col}: Invalid trailing character '{self._peek()}' in number literal")

        tok_kind = 'FLOAT_NUM' if is_float else 'INT_NUM'
        return Token(tok_kind, ''.join(buf), start_line, start_col, start_byte)

    def tokenize(self) -> List[Token]:
        tokens: List[Token] = []
        while self.pos < self.n:
            ch = self._peek()
            nxt = self._peek(1)
            s_line, s_col, s_byte = self.line, self.col, self.byte_offset

            if ch in ' \t\r\n':
                self._advance()
                continue

            if ch == '/' and nxt == '/':
                while self.pos < self.n and self._peek() != '\n':
                    self._advance()
                continue

            if ch == '/' and nxt == '*':
                self._advance(2)
                closed = False
                while self.pos < self.n:
                    if self._peek() == '*' and self._peek(1) == '/':
                        self._advance(2)
                        closed = True
                        break
                    self._advance()
                if not closed:
                    raise LexerError(f"{self.filename}:{s_line}:{s_col}: Unterminated block comment")
                continue

            if ch == '#':
                if not self.at_line_start:
                    raise LexerError(f"{self.filename}:{s_line}:{s_col}: Stray '#' in program (preprocessor directives must start at logical line beginning)")
                buf = []
                while self.pos < self.n:
                    c = self._advance()
                    buf.append(c)
                    if c == '\\' and self._peek() == '\n':
                        buf.append(self._advance())
                    elif c == '\n':
                        break
                tokens.append(Token('PREPROC', ''.join(buf).rstrip('\n'), s_line, s_col, s_byte))
                continue

            self.at_line_start = False

            if ch == '"':
                buf = [self._advance()]
                while self.pos < self.n:
                    c = self._peek()
                    if c == '\n' or c == '':
                        raise LexerError(f"{self.filename}:{s_line}:{s_col}: Unterminated string literal")
                    if c == '\\':
                        self._advance()
                        buf.append(self._scan_escape(self.line, self.col))
                    elif c == '"':
                        buf.append(self._advance())
                        break
                    else:
                        buf.append(self._advance())
                else:
                    raise LexerError(f"{self.filename}:{s_line}:{s_col}: Unterminated string literal")
                tokens.append(Token('STRING', ''.join(buf), s_line, s_col, s_byte))
                continue

            if ch == "'":
                buf = [self._advance()]
                char_count = 0
                while self.pos < self.n:
                    c = self._peek()
                    if c == '\n' or c == '':
                        raise LexerError(f"{self.filename}:{s_line}:{s_col}: Unterminated char literal")
                    if c == '\\':
                        self._advance()
                        buf.append(self._scan_escape(self.line, self.col))
                        char_count += 1
                    elif c == "'":
                        buf.append(self._advance())
                        break
                    else:
                        buf.append(self._advance())
                        char_count += 1
                else:
                    raise LexerError(f"{self.filename}:{s_line}:{s_col}: Unterminated char literal")
                if char_count != 1:
                    raise LexerError(f"{self.filename}:{s_line}:{s_col}: Character literal must contain exactly 1 character (got {char_count})")
                tokens.append(Token('CHAR', ''.join(buf), s_line, s_col, s_byte))
                continue

            if ch == 'a' and nxt == '!':
                self._advance(2)
                num_buf = []
                while self.pos < self.n and self._peek().isdigit():
                    num_buf.append(self._advance())
                if not num_buf:
                    raise LexerError(f"{self.filename}:{s_line}:{s_col}: Expected alignment power after 'a!'")
                tokens.append(Token('KW_ALIGN', ''.join(num_buf), s_line, s_col, s_byte))
                continue

            two_char = ch + nxt
            if two_char in SIGIL_KEYWORDS:
                if two_char in ("v.", "b.") and (self._peek(2).isalnum() or self._peek(2) == "_"):
                    pass  # 紧接标识符时（如 v.x 或 b.flag）拆分为结构体变量 IDENT + DOT 成员访问
                else:
                    self._advance(2)
                    tokens.append(Token(SIGIL_KEYWORDS[two_char], two_char, s_line, s_col, s_byte))
                    continue

            if two_char in SIGIL_OPERATORS:
                self._advance(2)
                tokens.append(Token(SIGIL_OPERATORS[two_char], two_char, s_line, s_col, s_byte))
                continue

            if ch.isalpha() or ch == '_':
                ident_buf = []
                while self.pos < self.n and (self._peek().isalnum() or self._peek() == '_'):
                    ident_buf.append(self._advance())
                word = ''.join(ident_buf)
                if word in BASIC_TYPES:
                    tokens.append(Token('TYPE_INT', word, s_line, s_col, s_byte))
                else:
                    tokens.append(Token('IDENT', word, s_line, s_col, s_byte))
                continue

            if ch.isdigit() or (ch == '.' and nxt.isdigit()):
                tokens.append(self._scan_number(s_line, s_col, s_byte))
                continue

            single_map = {
                '(': 'LPAREN', ')': 'RPAREN', '[': 'LBRACK', ']': 'RBRACK',
                '{': 'LBRACE', '}': 'RBRACE', ';': 'SEMI',   ',': 'COMMA',
                '.': 'DOT',    '?': 'QUESTION', ':': 'COLON',
                '+': 'PLUS',   '-': 'MINUS',  '*': 'STAR',   '/': 'SLASH',
                '%': 'PERCENT','<': 'LT',     '>': 'GT',
            }
            if ch in single_map:
                self._advance()
                tokens.append(Token(single_map[ch], ch, s_line, s_col, s_byte))
                continue

            raise LexerError(f"{self.filename}:{s_line}:{s_col}: Unexpected character {repr(ch)}")

        tokens.append(Token('EOF', '', self.line, self.col, self.byte_offset))
        return tokens


# ============================================================================
# 2. AST Nodes & Type System
# ============================================================================

@dataclass
class TypeNode:
    line: int
    col: int

@dataclass
class BaseType(TypeNode):
    c_name: str
    is_const: bool = False

@dataclass
class PointerType(TypeNode):
    pointee: TypeNode
    is_const: bool = False

@dataclass
class ArrayType(TypeNode):
    element_type: TypeNode
    size_expr: 'ExprNode'
    size_val: Optional[int] = None

@dataclass
class FunctionPointerType(TypeNode):
    param_decls: List[Tuple[TypeNode, Optional[str]]]
    return_type: TypeNode
    is_const: bool = False
    is_variadic: bool = False

def is_void_type(t: TypeNode) -> bool:
    return isinstance(t, BaseType) and t.c_name == "void"

def is_const_qualified(t: TypeNode) -> bool:
    if isinstance(t, (BaseType, PointerType, FunctionPointerType)):
        return t.is_const
    return False

def strip_top_const(t: TypeNode) -> TypeNode:
    if isinstance(t, BaseType):
        return BaseType(line=t.line, col=t.col, c_name=t.c_name, is_const=False)
    if isinstance(t, PointerType):
        return PointerType(line=t.line, col=t.col, pointee=t.pointee, is_const=False)
    if isinstance(t, FunctionPointerType):
        return FunctionPointerType(line=t.line, col=t.col, param_decls=t.param_decls, return_type=t.return_type, is_const=False, is_variadic=t.is_variadic)
    return t

def with_const(t: TypeNode) -> TypeNode:
    if isinstance(t, BaseType):
        return BaseType(line=t.line, col=t.col, c_name=t.c_name, is_const=True)
    if isinstance(t, PointerType):
        return PointerType(line=t.line, col=t.col, pointee=t.pointee, is_const=True)
    if isinstance(t, FunctionPointerType):
        return FunctionPointerType(line=t.line, col=t.col, param_decls=t.param_decls, return_type=t.return_type, is_const=True, is_variadic=t.is_variadic)
    if isinstance(t, ArrayType):
        return ArrayType(line=t.line, col=t.col, element_type=with_const(t.element_type), size_expr=t.size_expr, size_val=t.size_val)
    return t

def decay_parameter_type(t: TypeNode) -> TypeNode:
    """C99 6.7.5.3p7: 函数形参的最外层数组 T[N][M] 退化为指向子数组的指针 T (*)[M]，保留形参自身顶层 const 供函数体内部作用域检查"""
    if isinstance(t, ArrayType):
        return PointerType(line=t.line, col=t.col, pointee=t.element_type, is_const=False)
    return t

def types_equal(a: TypeNode, b: TypeNode) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, BaseType) and isinstance(b, BaseType):
        return a.c_name == b.c_name and a.is_const == b.is_const
    if isinstance(a, PointerType) and isinstance(b, PointerType):
        return a.is_const == b.is_const and types_equal(a.pointee, b.pointee)
    if isinstance(a, ArrayType) and isinstance(b, ArrayType):
        same_len = (a.size_val == b.size_val) if (a.size_val is not None and b.size_val is not None) else (emit_expr(a.size_expr) == emit_expr(b.size_expr))
        return types_equal(a.element_type, b.element_type) and same_len
    if isinstance(a, FunctionPointerType) and isinstance(b, FunctionPointerType):
        if len(a.param_decls) != len(b.param_decls) or a.is_variadic != b.is_variadic:
            return False
        if not types_equal(strip_top_const(a.return_type), strip_top_const(b.return_type)):
            return False
        return all(types_equal(strip_top_const(decay_parameter_type(pa[0])), strip_top_const(decay_parameter_type(pb[0]))) for pa, pb in zip(a.param_decls, b.param_decls))
    return False

def types_compatible_for_assign(expected: TypeNode, actual: TypeNode) -> bool:
    exp_clean = strip_top_const(expected)
    act_clean = strip_top_const(actual)
    if types_equal(exp_clean, act_clean):
        return True
    if isinstance(exp_clean, BaseType) and isinstance(act_clean, BaseType):
        if exp_clean.c_name in NUMERIC_C_TYPES and act_clean.c_name in NUMERIC_C_TYPES:
            return True
    if isinstance(exp_clean, PointerType) and isinstance(act_clean, ArrayType):
        if types_equal(strip_top_const(exp_clean.pointee), strip_top_const(act_clean.element_type)):
            if not is_const_qualified(act_clean.element_type) or is_const_qualified(exp_clean.pointee):
                return True
    if isinstance(exp_clean, PointerType) and isinstance(act_clean, PointerType):
        if is_void_type(exp_clean.pointee) or is_void_type(act_clean.pointee):
            if not is_const_qualified(act_clean.pointee) or is_const_qualified(exp_clean.pointee):
                return True
        if types_equal(strip_top_const(exp_clean.pointee), strip_top_const(act_clean.pointee)):
            if is_const_qualified(act_clean.pointee) and not is_const_qualified(exp_clean.pointee):
                return False
            return True
    return False

def format_c_declarator(t: TypeNode, var_name: str = "") -> str:
    inner = var_name
    curr = t
    while True:
        if isinstance(curr, BaseType):
            prefix = "const " if curr.is_const else ""
            return f"{prefix}{curr.c_name}" + (f" {inner}" if inner else "")
        elif isinstance(curr, PointerType):
            if curr.is_const:
                ptr_str = f"* const {inner}" if inner else "* const"
            else:
                ptr_str = f"*{inner}"
            if isinstance(curr.pointee, (ArrayType, FunctionPointerType)):
                inner = f"({ptr_str.strip()})"
            else:
                inner = ptr_str.strip()
            curr = curr.pointee
        elif isinstance(curr, ArrayType):
            dim_code = emit_expr(curr.size_expr)
            inner = f"{inner}[{dim_code}]"
            curr = curr.element_type
        elif isinstance(curr, FunctionPointerType):
            params_c = [format_c_declarator(pt, pname or "") for pt, pname in curr.param_decls]
            param_list_str = ", ".join(params_c) if params_c else "void"
            qual = "const " if curr.is_const else ""
            fn_inner = f"(*{qual}{inner})({param_list_str})"
            return format_c_declarator(curr.return_type, fn_inner)
        else:
            raise TypeError(f"Unknown TypeNode: {curr}")

@dataclass
class ExprNode:
    line: int
    col: int

@dataclass
class LiteralExpr(ExprNode):
    code: str
    lit_kind: str = 'INT_NUM'

@dataclass
class IdentExpr(ExprNode):
    name: str

@dataclass
class CastExpr(ExprNode):
    target_type: TypeNode
    operand: ExprNode

@dataclass
class UnaryExpr(ExprNode):
    op: str
    operand: ExprNode

@dataclass
class BinaryExpr(ExprNode):
    op: str
    left: ExprNode
    right: ExprNode

@dataclass
class TernaryExpr(ExprNode):
    cond: ExprNode
    then_expr: ExprNode
    else_expr: ExprNode

@dataclass
class CallExpr(ExprNode):
    callee: ExprNode
    args: List[ExprNode]

@dataclass
class IndexExpr(ExprNode):
    base: ExprNode
    index: ExprNode

@dataclass
class MemberExpr(ExprNode):
    base: ExprNode
    field: str
    is_arrow: bool

@dataclass
class StmtNode:
    line: int
    col: int

@dataclass
class PreprocNode(StmtNode):
    text: str

@dataclass
class VarDeclStmt(StmtNode):
    var_type: TypeNode
    name: str
    init_expr: Optional[ExprNode] = None

@dataclass
class AssignStmt(StmtNode):
    op: str
    target: ExprNode
    value: ExprNode

@dataclass
class ExprStmt(StmtNode):
    expr: ExprNode

@dataclass
class BlockStmt(StmtNode):
    stmts: List[StmtNode]

@dataclass
class IfStmt(StmtNode):
    cond: ExprNode
    then_block: BlockStmt
    else_branch: Optional[StmtNode] = None

@dataclass
class WhileStmt(StmtNode):
    cond: ExprNode
    body: BlockStmt

@dataclass
class ForStmt(StmtNode):
    init_stmt: Optional[StmtNode]
    cond_expr: Optional[ExprNode]
    step_stmt: Optional[StmtNode]
    body: BlockStmt

@dataclass
class CaseClause:
    line: int
    value: Optional[ExprNode]
    stmts: List[StmtNode]

@dataclass
class SwitchStmt(StmtNode):
    cond: ExprNode
    cases: List[CaseClause]

@dataclass
class ReturnStmt(StmtNode):
    expr: Optional[ExprNode]

@dataclass
class JumpStmt(StmtNode):
    keyword: str

@dataclass
class StructDefNode(StmtNode):
    kind: str
    name: str
    alignment: Optional[int]
    fields: List[VarDeclStmt]

@dataclass
class EnumDefNode(StmtNode):
    name: str
    items: List[Tuple[str, Optional[ExprNode]]]

@dataclass
class FuncDefNode(StmtNode):
    return_type: TypeNode
    name: str
    params: List[Tuple[TypeNode, str]]
    body: Optional[BlockStmt]

def emit_expr(e: ExprNode) -> str:
    if isinstance(e, LiteralExpr):
        return e.code
    if isinstance(e, IdentExpr):
        return e.name
    if isinstance(e, CastExpr):
        return f"(({format_c_declarator(e.target_type)})({emit_expr(e.operand)}))"
    if isinstance(e, UnaryExpr):
        return f"({e.op}{emit_expr(e.operand)})"
    if isinstance(e, BinaryExpr):
        return f"({emit_expr(e.left)} {e.op} {emit_expr(e.right)})"
    if isinstance(e, TernaryExpr):
        return f"({emit_expr(e.cond)} ? {emit_expr(e.then_expr)} : {emit_expr(e.else_expr)})"
    if isinstance(e, CallExpr):
        return f"{emit_expr(e.callee)}({', '.join(emit_expr(a) for a in e.args)})"
    if isinstance(e, IndexExpr):
        return f"{emit_expr(e.base)}[{emit_expr(e.index)}]"
    if isinstance(e, MemberExpr):
        return f"{emit_expr(e.base)}{'->' if e.is_arrow else '.'}{e.field}"
    raise TypeError(f"Unknown ExprNode: {e}")


# ============================================================================
# 3. Recursive-Descent Parser & Static Semantic Analyzer
# ============================================================================

class ParseError(Exception):
    pass

class SemanticError(Exception):
    pass

ASSIGN_TOKENS = {
    'OP_ASSIGN': '=',
    'OP_ADD_ASSIGN': '+=',
    'OP_SUB_ASSIGN': '-=',
    'OP_MUL_ASSIGN': '*=',
    'OP_DIV_ASSIGN': '/=',
}

class Parser:
    def __init__(self, tokens: List[Token], filename: str = "<input>"):
        self.tokens = tokens
        self.pos = 0
        self.filename = filename
        self.user_types: Dict[str, str] = {}
        self.struct_fields: Dict[str, Dict[str, TypeNode]] = {}
        self.complete_structs: Set[str] = set()
        self.enum_constants: Dict[str, int] = {}
        self.scopes: List[Dict[str, TypeNode]] = [{}]
        self.func_sigs: Dict[str, Tuple[List[TypeNode], TypeNode]] = {}
        self.func_defined: Set[str] = set()
        self.current_func_ret: Optional[TypeNode] = None
        self.loop_depth: int = 0
        self.switch_depth: int = 0

    def _cur(self) -> Token:
        return self.tokens[self.pos]

    def _eat(self, kind: Optional[str] = None) -> Token:
        tok = self._cur()
        if kind and tok.kind != kind:
            raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: Expected '{kind}', got '{tok.kind}' ('{tok.value}')")
        self.pos += 1
        return tok

    def _is_type_start_at(self, start_idx: int) -> bool:
        idx = start_idx
        while idx < len(self.tokens) and self.tokens[idx].kind in ('KW_PTR', 'KW_CONST'):
            idx += 1
        if idx >= len(self.tokens):
            return False
        t = self.tokens[idx]
        if t.kind == 'LPAREN' and idx + 1 < len(self.tokens) and self.tokens[idx + 1].kind in ('KW_PTR', 'KW_CONST', 'KW_FNPTR'):
            return self._is_type_start_at(idx + 1)
        return t.kind in ('TYPE_INT', 'TYPE_VOID', 'TYPE_BOOL', 'KW_FNPTR') or (
            t.kind == 'IDENT' and t.value in self.user_types
        )

    def _is_type_start(self, tok: Token) -> bool:
        return self._is_type_start_at(self.pos)

    def _lookup_symbol(self, name: str, tok: Token) -> TypeNode:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Undeclared identifier '{name}'")

    def _register_symbol(self, name: str, t: TypeNode, tok: Token):
        if name in self.scopes[-1]:
            raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Redefinition of '{name}' in the same scope")
        self.scopes[-1][name] = t

    def _validate_non_void_var(self, t: TypeNode, tok: Token):
        if is_void_type(t):
            raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Variable or field '{tok.value}' cannot have type 'v.' (void)")
        if isinstance(t, ArrayType) and is_void_type(t.element_type):
            raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Array of 'v.' (void) is illegal")
        if not self._is_complete_object_type(t):
            raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Variable or parameter '{tok.value}' has incomplete type")

    def _eval_const_int_expr(self, expr: ExprNode) -> Optional[int]:
        """纯整数常量表达式求值 (C99 向零截断除法/取模、比较、逻辑、三元、位运算，无浮点精度损失)"""
        if isinstance(expr, LiteralExpr):
            if expr.lit_kind == 'INT_NUM':
                s = expr.code.rstrip('uUlL')
                try:
                    if s.startswith(('0x', '0X', '0b', '0B')):
                        return int(s, 0)
                    if s.startswith('0') and len(s) > 1 and s.isdigit():
                        return int(s, 8)
                    return int(s, 10)
                except ValueError:
                    return None
            if expr.lit_kind == 'CHAR':
                inner = expr.code[1:-1]
                if len(inner) == 1:
                    return ord(inner)
                if inner.startswith('\\'):
                    esc_map = {'a': 7, 'b': 8, 'f': 12, 'n': 10, 'r': 13, 't': 9, 'v': 11, '\\': 92, "'": 39, '"': 34, '?': 63}
                    rest = inner[1:]
                    if rest in esc_map:
                        return esc_map[rest]
                    if rest.startswith('x'):
                        return int(rest[1:], 16)
                    if all(c in '01234567' for c in rest):
                        return int(rest, 8)
            return None
        if isinstance(expr, IdentExpr):
            return self.enum_constants.get(expr.name, None)
        if isinstance(expr, CastExpr):
            if isinstance(expr.target_type, BaseType) and expr.target_type.c_name in INT_C_TYPES:
                return self._eval_const_int_expr(expr.operand)
            return None
        if isinstance(expr, UnaryExpr):
            val = self._eval_const_int_expr(expr.operand)
            if val is None:
                return None
            if expr.op == '-':
                res_u = -val
                if res_u < -(1 << 63) or res_u >= (1 << 64):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Integer constant overflow out of 64-bit range")
                return res_u
            if expr.op == '+': return val
            if expr.op == '~': return ~val
            if expr.op == '!': return 1 if val == 0 else 0
        if isinstance(expr, TernaryExpr):
            cv = self._eval_const_int_expr(expr.cond)
            if cv is None:
                return None
            return self._eval_const_int_expr(expr.then_expr if cv != 0 else expr.else_expr)
        if isinstance(expr, BinaryExpr):
            lv = self._eval_const_int_expr(expr.left)
            if lv is None:
                return None
            if expr.op == '&&':
                if lv == 0:
                    return 0
                rv = self._eval_const_int_expr(expr.right)
                return int(bool(rv)) if rv is not None else None
            if expr.op == '||':
                if lv != 0:
                    return 1
                rv = self._eval_const_int_expr(expr.right)
                return int(bool(rv)) if rv is not None else None
            rv = self._eval_const_int_expr(expr.right)
            if rv is None:
                return None
            res: Optional[int] = None
            if expr.op == '+': res = lv + rv
            elif expr.op == '-': res = lv - rv
            elif expr.op == '*': res = lv * rv
            elif expr.op in ('/', '%'):
                if rv == 0:
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Division or modulo by zero in integer constant expression")
                # C99 6.5.5p6: 纯整数向零截断除法与余数 a == (a/b)*b + a%b
                q = -(abs(lv) // abs(rv)) if (lv < 0) ^ (rv < 0) else (abs(lv) // abs(rv))
                res = q if expr.op == '/' else (lv - q * rv)
            elif expr.op == '<<':
                if rv < 0 or rv >= 64:
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Shift count {rv} out of range [0, 63] in constant expression")
                if lv < 0:
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Left shift of negative value {lv} in constant expression")
                res = lv << rv
            elif expr.op == '>>':
                if rv < 0 or rv >= 64:
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Shift count {rv} out of range [0, 63] in constant expression")
                res = lv >> rv
            if res is not None:
                if res < -(1 << 63) or res >= (1 << 64):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Integer constant overflow out of 64-bit range")
                return res
            if expr.op == '|': return lv | rv
            if expr.op == '&': return lv & rv
            if expr.op == '^': return lv ^ rv
            if expr.op == '==': return int(lv == rv)
            if expr.op == '!=': return int(lv != rv)
            if expr.op == '<':  return int(lv < rv)
            if expr.op == '<=': return int(lv <= rv)
            if expr.op == '>':  return int(lv > rv)
            if expr.op == '>=': return int(lv >= rv)
            if expr.op == '&&': return int(bool(lv) and bool(rv))
            if expr.op == '||': return int(bool(lv) or bool(rv))
        return None

    def _infer_expr_type(self, expr: ExprNode) -> TypeNode:
        if isinstance(expr, LiteralExpr):
            if expr.lit_kind == 'STRING':
                return PointerType(line=expr.line, col=expr.col, pointee=BaseType(line=expr.line, col=expr.col, c_name='char', is_const=True))
            if expr.lit_kind == 'CHAR':
                return BaseType(line=expr.line, col=expr.col, c_name='char')
            if expr.lit_kind == 'FLOAT_NUM':
                if expr.code.endswith(('f', 'F')):
                    float_type = 'float'
                elif expr.code.endswith(('l', 'L')):
                    float_type = 'long double'
                else:
                    float_type = 'double'
                return BaseType(line=expr.line, col=expr.col, c_name=float_type)
            # INT_NUM (包括 0xFE 十六进制整数，严格推导为整型，修复 'E' 误判为浮点的问题)
            return BaseType(line=expr.line, col=expr.col, c_name='uint32_t' if expr.code.lower().endswith('u') else 'int32_t')

        if isinstance(expr, IdentExpr):
            return self._lookup_symbol(expr.name, Token('IDENT', expr.name, expr.line, expr.col, 0))

        if isinstance(expr, CastExpr):
            src_t = self._infer_expr_type(expr.operand)
            dst_t = expr.target_type
            if is_void_type(dst_t):
                return dst_t
            if not self._is_scalar_type(dst_t) or not self._is_scalar_type(src_t):
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Cast requires scalar types (unless casting to 'v.')")
            dst_is_float = isinstance(dst_t, BaseType) and dst_t.c_name in ('float', 'double', 'long double')
            src_is_float = isinstance(src_t, BaseType) and src_t.c_name in ('float', 'double', 'long double')
            if (dst_is_float and isinstance(src_t, (PointerType, FunctionPointerType))) or (src_is_float and isinstance(dst_t, (PointerType, FunctionPointerType))):
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Cannot cast between floating-point and pointer type")
            return dst_t

        if isinstance(expr, UnaryExpr):
            sub_t = self._infer_expr_type(expr.operand)
            if expr.op == '*':
                if isinstance(sub_t, PointerType):
                    if not self._is_complete_object_type(sub_t.pointee):
                        raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Cannot dereference pointer to incomplete or void type")
                    return sub_t.pointee
                if isinstance(sub_t, ArrayType):
                    return sub_t.element_type
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Cannot dereference non-pointer type")
            if expr.op == '&':
                if not isinstance(expr.operand, (IdentExpr, IndexExpr, MemberExpr)) and not (isinstance(expr.operand, UnaryExpr) and expr.operand.op == '*'):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Cannot take address ('a&') of rvalue expression")
                return PointerType(line=expr.line, col=expr.col, pointee=sub_t)
            if expr.op == '!':
                if not self._is_scalar_type(sub_t):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Logical NOT ('!.') requires scalar operand")
                return BaseType(line=expr.line, col=expr.col, c_name='bool')
            if expr.op == '~':
                if not self._is_int_type(sub_t):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Bitwise NOT ('~^') requires integer operand")
                return sub_t
            if expr.op in ('+', '-'):
                if not self._is_numeric_type(sub_t):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Unary '{expr.op}' requires arithmetic operand")
                return sub_t
            return sub_t

        if isinstance(expr, IndexExpr):
            base_t = self._infer_expr_type(expr.base)
            idx_t = self._infer_expr_type(expr.index)
            if not (isinstance(idx_t, BaseType) and (idx_t.c_name in INT_C_TYPES or self.user_types.get(idx_t.c_name) == 'enum')):
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Array subscript is not an integer")
            if isinstance(base_t, PointerType):
                if not self._is_complete_object_type(base_t.pointee):
                    raise SemanticError(
                        f"{self.filename}:{expr.line}:{expr.col}: Cannot subscript pointer to incomplete or void type"
                    )
                return base_t.pointee
            if isinstance(base_t, ArrayType):
                return base_t.element_type
            raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Subscripted value is neither array nor pointer")

        if isinstance(expr, MemberExpr):
            base_t = self._infer_expr_type(expr.base)
            if expr.is_arrow:
                if not isinstance(base_t, PointerType) or not isinstance(base_t.pointee, BaseType):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: '->' applied to non-struct pointer")
                struct_name = base_t.pointee.c_name
                parent_is_const = base_t.pointee.is_const
            else:
                if not isinstance(base_t, BaseType):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: '.' applied to non-struct type")
                struct_name = base_t.c_name
                parent_is_const = base_t.is_const

            if struct_name not in self.struct_fields:
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Type '{struct_name}' has no member fields")
            f_map = self.struct_fields[struct_name]
            if expr.field not in f_map:
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: '{struct_name}' has no member named '{expr.field}'")
            ft = f_map[expr.field]
            return with_const(ft) if parent_is_const else ft

        if isinstance(expr, CallExpr):
            if isinstance(expr.callee, IdentExpr) and expr.callee.name in self.func_sigs:
                _, ret_t = self.func_sigs[expr.callee.name]
                return ret_t
            callee_t = self._infer_expr_type(expr.callee)
            if isinstance(callee_t, FunctionPointerType):
                return callee_t.return_type
            raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Called object is not a function or function pointer")

        if isinstance(expr, TernaryExpr):
            t_then = self._infer_expr_type(expr.then_expr)
            t_else = self._infer_expr_type(expr.else_expr)
            return self._resolve_ternary_type(expr, t_then, t_else)

        if isinstance(expr, BinaryExpr):
            lt = self._decay_rvalue(self._infer_expr_type(expr.left))
            rt = self._decay_rvalue(self._infer_expr_type(expr.right))
            op = expr.op
            if op in ('&&', '||'):
                if not self._is_scalar_type(lt) or not self._is_scalar_type(rt):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Logical operator '{op}' requires scalar operands")
                return BaseType(line=expr.line, col=expr.col, c_name='bool')
            if op in ('==', '!='):
                if self._is_numeric_type(lt) and self._is_numeric_type(rt):
                    return BaseType(line=expr.line, col=expr.col, c_name='bool')
                if isinstance(lt, PointerType) and isinstance(rt, PointerType):
                    if is_void_type(lt.pointee) or is_void_type(rt.pointee) or types_equal(strip_top_const(lt.pointee), strip_top_const(rt.pointee)):
                        return BaseType(line=expr.line, col=expr.col, c_name='bool')
                if isinstance(lt, FunctionPointerType) and isinstance(rt, FunctionPointerType) and types_equal(strip_top_const(lt), strip_top_const(rt)):
                    return BaseType(line=expr.line, col=expr.col, c_name='bool')
                if (isinstance(lt, (PointerType, FunctionPointerType)) and self._is_null_ptr_const(expr.right, rt)) or (
                    isinstance(rt, (PointerType, FunctionPointerType)) and self._is_null_ptr_const(expr.left, lt)
                ):
                    return BaseType(line=expr.line, col=expr.col, c_name='bool')
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Invalid operands to equality operator '{op}'")
            if op in ('<', '<=', '>', '>='):
                if self._is_numeric_type(lt) and self._is_numeric_type(rt):
                    return BaseType(line=expr.line, col=expr.col, c_name='bool')
                if isinstance(lt, PointerType) and isinstance(rt, PointerType) and not is_void_type(lt.pointee) and types_equal(strip_top_const(lt.pointee), strip_top_const(rt.pointee)):
                    return BaseType(line=expr.line, col=expr.col, c_name='bool')
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Invalid operands to relational operator '{op}'")
            if op == '+':
                if self._is_numeric_type(lt) and self._is_numeric_type(rt):
                    return self._usual_arith_type(expr, lt, rt)
                if isinstance(lt, PointerType) and self._is_int_type(rt):
                    if not self._is_complete_object_type(lt.pointee):
                        raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Pointer addition requires pointer to complete object type")
                    return lt
                if self._is_int_type(lt) and isinstance(rt, PointerType):
                    if not self._is_complete_object_type(rt.pointee):
                        raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Pointer addition requires pointer to complete object type")
                    return rt
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Invalid operands to binary '+'")
            if op == '-':
                if self._is_numeric_type(lt) and self._is_numeric_type(rt):
                    return self._usual_arith_type(expr, lt, rt)
                if isinstance(lt, PointerType) and self._is_int_type(rt):
                    if not self._is_complete_object_type(lt.pointee):
                        raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Pointer subtraction requires pointer to complete object type")
                    return lt
                if isinstance(lt, PointerType) and isinstance(rt, PointerType):
                    if not self._is_complete_object_type(lt.pointee) or not types_equal(strip_top_const(lt.pointee), strip_top_const(rt.pointee)):
                        raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Pointer subtraction requires pointers to compatible complete object types")
                    return BaseType(line=expr.line, col=expr.col, c_name='ptrdiff_t')
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Invalid operands to binary '-'")
            if op in ('*', '/'):
                if not (self._is_numeric_type(lt) and self._is_numeric_type(rt)):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Operator '{op}' requires arithmetic operands")
                return self._usual_arith_type(expr, lt, rt)
            if op in ('%', '<<', '>>', '|', '&', '^'):
                if not (self._is_int_type(lt) and self._is_int_type(rt)):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Operator '{op}' requires integer operands")
                return self._usual_arith_type(expr, lt, rt)
            return lt

        return BaseType(line=expr.line, col=expr.col, c_name='int32_t')

    def _check_modifiable_lvalue(self, expr: ExprNode, op_tok: Token):
        if not isinstance(expr, (IdentExpr, IndexExpr, MemberExpr)) and not (isinstance(expr, UnaryExpr) and expr.op == '*'):
            raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Left-hand side of '{op_tok.value}' is not a modifiable lvalue")

        lhs_t = self._infer_expr_type(expr)
        if is_const_qualified(lhs_t):
            raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Cannot assign to const-qualified lvalue")
        if isinstance(lhs_t, ArrayType):
            raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Array type is not a modifiable lvalue")

    def _check_compound_assign_types(self, op_kind: str, lhs_t: TypeNode, rhs_t: TypeNode, op_tok: Token):
        """
        区分单纯赋值 (m,) 与算术复合赋值 (a+ / s- / m* / d/) 的类型规则:
        - m, (=): 遵循 types_compatible_for_assign(lhs_t, rhs_t)
        - m* (*=), d/ (/=): 左右两侧必须均为算术数值类型 (严禁指针参与 *= 或 /=)
        - a+ (+=), s- (-=): 允许 (数值 += 数值) 或 (非void指针 += 整型偏移)，严禁 (指针 += 指针)!
        """
        if op_kind == 'OP_ASSIGN':
            if not types_compatible_for_assign(lhs_t, rhs_t):
                raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Incompatible types in assignment 'm,'")
            return

        lhs_is_num = isinstance(lhs_t, BaseType) and (lhs_t.c_name in NUMERIC_C_TYPES or self.user_types.get(lhs_t.c_name) == 'enum')
        rhs_is_num = isinstance(rhs_t, BaseType) and (rhs_t.c_name in NUMERIC_C_TYPES or self.user_types.get(rhs_t.c_name) == 'enum')
        rhs_is_int = isinstance(rhs_t, BaseType) and (rhs_t.c_name in INT_C_TYPES or self.user_types.get(rhs_t.c_name) == 'enum')

        if op_kind in ('OP_MUL_ASSIGN', 'OP_DIV_ASSIGN'):
            if not (lhs_is_num and rhs_is_num):
                raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Operator '{op_tok.value}' requires numeric operands")
            return

        if op_kind in ('OP_ADD_ASSIGN', 'OP_SUB_ASSIGN'):
            if lhs_is_num and rhs_is_num:
                return
            if isinstance(lhs_t, PointerType) and rhs_is_int:
                if not self._is_complete_object_type(lhs_t.pointee):
                    raise SemanticError(
                        f"{self.filename}:{op_tok.line}:{op_tok.col}: Pointer arithmetic '{op_tok.value}' requires pointer to a complete object type"
                    )
                return
            raise SemanticError(
                f"{self.filename}:{op_tok.line}:{op_tok.col}: Invalid operands to '{op_tok.value}' (pointer += pointer or non-integer pointer offset is forbidden)"
            )

    def _is_int_type(self, t: TypeNode) -> bool:
        return isinstance(t, BaseType) and (t.c_name in INT_C_TYPES or self.user_types.get(t.c_name) == 'enum')

    def _is_numeric_type(self, t: TypeNode) -> bool:
        return isinstance(t, BaseType) and (t.c_name in NUMERIC_C_TYPES or self.user_types.get(t.c_name) == 'enum')

    def _is_scalar_type(self, t: TypeNode) -> bool:
        t_dec = self._decay_rvalue(t)
        return self._is_numeric_type(t_dec) or isinstance(t_dec, (PointerType, FunctionPointerType))

    def _decay_rvalue(self, t: TypeNode) -> TypeNode:
        if isinstance(t, ArrayType):
            return PointerType(line=t.line, col=t.col, pointee=t.element_type, is_const=False)
        return t

    def _is_null_ptr_const(self, expr: ExprNode, expr_t: TypeNode) -> bool:
        if not self._is_int_type(expr_t):
            return False
        try:
            return self._eval_const_int_expr(expr) == 0
        except SemanticError:
            return False

    def _usual_arith_type(self, expr: ExprNode, a: TypeNode, b: TypeNode) -> BaseType:
        assert isinstance(a, BaseType) and isinstance(b, BaseType)
        names = {a.c_name, b.c_name}
        if 'long double' in names:
            return BaseType(line=expr.line, col=expr.col, c_name='long double')
        if 'double' in names:
            return BaseType(line=expr.line, col=expr.col, c_name='double')
        if 'float' in names:
            return BaseType(line=expr.line, col=expr.col, c_name='float')
        if 'uint64_t' in names or 'size_t' in names or 'uintptr_t' in names:
            return BaseType(line=expr.line, col=expr.col, c_name='uint64_t')
        if 'int64_t' in names or 'ptrdiff_t' in names or 'intptr_t' in names:
            return BaseType(line=expr.line, col=expr.col, c_name='int64_t')
        if 'uint32_t' in names:
            return BaseType(line=expr.line, col=expr.col, c_name='uint32_t')
        return BaseType(line=expr.line, col=expr.col, c_name='int32_t')

    def _check_assign_compatible(self, expected: TypeNode, rhs_expr: ExprNode, actual: TypeNode) -> bool:
        if types_compatible_for_assign(expected, actual):
            return True
        if self._is_numeric_type(expected) and self._is_numeric_type(actual):
            return True
        if isinstance(strip_top_const(expected), (PointerType, FunctionPointerType)) and self._is_null_ptr_const(rhs_expr, actual):
            return True
        return False

    def _check_scalar_cond(self, cond: ExprNode, kw_name: str):
        ct = self._infer_expr_type(cond)
        if not self._is_scalar_type(ct):
            raise SemanticError(f"{self.filename}:{cond.line}:{cond.col}: Controlling expression of '{kw_name}' must have scalar type")

    def _register_c99_header_builtins(self, ptok: Token):
        txt = ptok.value.replace(" ", "")
        ln, cl = ptok.line, ptok.col
        t_int = BaseType(ln, cl, 'int')
        t_void = BaseType(ln, cl, 'void')
        t_size = BaseType(ln, cl, 'size_t')
        t_cstr = PointerType(ln, cl, BaseType(ln, cl, 'char', is_const=True))
        t_vptr = PointerType(ln, cl, BaseType(ln, cl, 'void'))
        t_cvptr = PointerType(ln, cl, BaseType(ln, cl, 'void', is_const=True))

        def reg_fn(name: str, params: List[TypeNode], ret: TypeNode, variadic: bool = False):
            if name not in self.scopes[0]:
                self.scopes[0][name] = FunctionPointerType(ln, cl, [(p, f"p{i}") for i, p in enumerate(params)], ret, is_variadic=variadic)
                if not variadic:
                    self.func_sigs[name] = (params, ret)

        if '<stdio.h>' in txt:
            reg_fn('printf', [t_cstr], t_int, variadic=True)
            reg_fn('puts', [t_cstr], t_int)
            reg_fn('putchar', [t_int], t_int)
        if '<stdlib.h>' in txt:
            reg_fn('malloc', [t_size], t_vptr)
            reg_fn('calloc', [t_size, t_size], t_vptr)
            reg_fn('free', [t_vptr], t_void)
            reg_fn('exit', [t_int], t_void)
            reg_fn('abort', [], t_void)
        if '<string.h>' in txt:
            reg_fn('memcpy', [t_vptr, t_cvptr, t_size], t_vptr)
            reg_fn('memset', [t_vptr, t_int, t_size], t_vptr)
            reg_fn('memcmp', [t_cvptr, t_cvptr, t_size], t_int)
            reg_fn('strlen', [t_cstr], t_size)
        if '<assert.h>' in txt:
            reg_fn('assert', [t_int], t_void)

    def _sequence_flow(self, stmts: List[StmtNode]) -> Set[str]:
        outcomes = {"fallthrough"}
        for stmt in stmts:
            if "fallthrough" not in outcomes:
                break
            outcomes = (outcomes - {"fallthrough"}) | self._statement_flow(stmt)
        return outcomes

    def _statement_flow(self, stmt: StmtNode) -> Set[str]:
        """Possible exits from a statement: return, break, continue, or fallthrough."""
        if isinstance(stmt, ReturnStmt):
            return {"return"}
        if isinstance(stmt, JumpStmt):
            return {stmt.keyword}
        if isinstance(stmt, BlockStmt):
            return self._sequence_flow(stmt.stmts)
        if isinstance(stmt, IfStmt):
            outcomes = self._statement_flow(stmt.then_block)
            if stmt.else_branch is None:
                outcomes.add("fallthrough")
            else:
                outcomes |= self._statement_flow(stmt.else_branch)
            return outcomes
        if isinstance(stmt, SwitchStmt):
            outcomes: Set[str] = set()
            has_default = any(case.value is None for case in stmt.cases)
            for start in range(len(stmt.cases)):
                case_outcomes = {"fallthrough"}
                for case in stmt.cases[start:]:
                    if "fallthrough" not in case_outcomes:
                        break
                    case_outcomes = (case_outcomes - {"fallthrough"}) | self._sequence_flow(case.stmts)
                if "break" in case_outcomes:
                    case_outcomes = (case_outcomes - {"break"}) | {"fallthrough"}
                outcomes |= case_outcomes
            if not has_default:
                outcomes.add("fallthrough")
            return outcomes
        if isinstance(stmt, (WhileStmt, ForStmt)):
            body_outcomes = self._statement_flow(stmt.body)
            cond = stmt.cond if isinstance(stmt, WhileStmt) else stmt.cond_expr
            always_true = cond is None
            if cond is not None:
                try:
                    cond_value = self._eval_const_int_expr(cond)
                except SemanticError:
                    cond_value = None
                always_true = cond_value is not None and cond_value != 0
            outcomes: Set[str] = set()
            if "return" in body_outcomes:
                outcomes.add("return")
            if not always_true or "break" in body_outcomes:
                outcomes.add("fallthrough")
            return outcomes
        return {"fallthrough"}

    def _can_fall_through(self, stmt: StmtNode) -> bool:
        return "fallthrough" in self._statement_flow(stmt)

    def _is_static_arithmetic_const_expr(self, expr: ExprNode) -> bool:
        if self._eval_const_int_expr(expr) is not None:
            return True
        if isinstance(expr, LiteralExpr):
            return expr.lit_kind in ('INT_NUM', 'FLOAT_NUM', 'CHAR')
        if isinstance(expr, IdentExpr):
            return expr.name in self.enum_constants
        if isinstance(expr, CastExpr):
            return self._is_numeric_type(expr.target_type) and self._is_static_arithmetic_const_expr(expr.operand)
        if isinstance(expr, UnaryExpr) and expr.op in ('+', '-', '!', '~'):
            return self._is_static_arithmetic_const_expr(expr.operand) and self._is_numeric_type(self._infer_expr_type(expr))
        if isinstance(expr, BinaryExpr):
            return (
                self._is_static_arithmetic_const_expr(expr.left)
                and self._is_static_arithmetic_const_expr(expr.right)
                and self._is_numeric_type(self._infer_expr_type(expr))
            )
        if isinstance(expr, TernaryExpr):
            return (
                self._is_static_arithmetic_const_expr(expr.cond)
                and self._is_static_arithmetic_const_expr(expr.then_expr)
                and self._is_static_arithmetic_const_expr(expr.else_expr)
                and self._is_numeric_type(self._infer_expr_type(expr))
            )
        return False

    def _is_static_const_init(self, expr: ExprNode) -> bool:
        if self._eval_const_int_expr(expr) is not None:
            return True
        if self._is_static_arithmetic_const_expr(expr):
            return True
        if isinstance(expr, LiteralExpr) and expr.lit_kind in ('FLOAT_NUM', 'STRING', 'CHAR'):
            return True
        if isinstance(expr, CastExpr):
            return self._is_static_const_init(expr.operand)
        if isinstance(expr, UnaryExpr) and expr.op in ('-', '+'):
            return self._is_static_const_init(expr.operand)
        if isinstance(expr, UnaryExpr) and expr.op == '&' and isinstance(expr.operand, IdentExpr):
            return expr.operand.name in self.scopes[0]
        if isinstance(expr, IdentExpr) and expr.name in self.func_sigs:
            return True
        return False

    def _is_complete_object_type(self, t: TypeNode) -> bool:
        if isinstance(t, BaseType):
            if t.c_name == 'void':
                return False
            if t.c_name in NUMERIC_C_TYPES or self.user_types.get(t.c_name) == 'enum':
                return True
            if t.c_name in self.user_types:
                return t.c_name in self.complete_structs
            return False
        if isinstance(t, (PointerType, FunctionPointerType)):
            return True
        if isinstance(t, ArrayType):
            return self._is_complete_object_type(t.element_type)
        return False

    def _resolve_ternary_type(self, expr: TernaryExpr, t_then: TypeNode, t_else: TypeNode) -> TypeNode:
        then_num = isinstance(t_then, BaseType) and (t_then.c_name in NUMERIC_C_TYPES or self.user_types.get(t_then.c_name) == 'enum')
        else_num = isinstance(t_else, BaseType) and (t_else.c_name in NUMERIC_C_TYPES or self.user_types.get(t_else.c_name) == 'enum')
        if then_num and else_num:
            assert isinstance(t_then, BaseType) and isinstance(t_else, BaseType)
            names = {t_then.c_name, t_else.c_name}
            if 'long double' in names:
                return BaseType(line=expr.line, col=expr.col, c_name='long double')
            if 'double' in names:
                return BaseType(line=expr.line, col=expr.col, c_name='double')
            if 'float' in names:
                return BaseType(line=expr.line, col=expr.col, c_name='float')
            if 'uint64_t' in names:
                return BaseType(line=expr.line, col=expr.col, c_name='uint64_t')
            if 'int64_t' in names:
                return BaseType(line=expr.line, col=expr.col, c_name='int64_t')
            if 'uint32_t' in names:
                return BaseType(line=expr.line, col=expr.col, c_name='uint32_t')
            return BaseType(line=expr.line, col=expr.col, c_name='int32_t')

        if isinstance(t_then, PointerType) and isinstance(t_else, PointerType):
            p1, p2 = t_then.pointee, t_else.pointee
            merged_const = is_const_qualified(p1) or is_const_qualified(p2)
            if types_equal(strip_top_const(p1), strip_top_const(p2)):
                pt = with_const(p1) if merged_const else strip_top_const(p1)
                return PointerType(line=expr.line, col=expr.col, pointee=pt)
            if is_void_type(p1) or is_void_type(p2):
                v_base = BaseType(line=expr.line, col=expr.col, c_name='void', is_const=merged_const)
                return PointerType(line=expr.line, col=expr.col, pointee=v_base)

        try:
            then_zero = then_num and self._eval_const_int_expr(expr.then_expr) == 0
        except SemanticError:
            then_zero = False
        try:
            else_zero = else_num and self._eval_const_int_expr(expr.else_expr) == 0
        except SemanticError:
            else_zero = False

        if isinstance(t_then, (PointerType, FunctionPointerType)) and else_zero:
            return strip_top_const(t_then)
        if isinstance(t_else, (PointerType, FunctionPointerType)) and then_zero:
            return strip_top_const(t_else)

        if types_equal(strip_top_const(t_then), strip_top_const(t_else)):
            if is_const_qualified(t_then) or is_const_qualified(t_else):
                return with_const(t_then)
            return strip_top_const(t_then)

        raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Incompatible branch types in ternary conditional expression")

    def parse_type(self) -> TypeNode:
        tok = self._cur()
        is_const = False
        if tok.kind == 'KW_CONST':
            self._eat('KW_CONST')
            is_const = True
            tok = self._cur()

        if tok.kind == 'KW_PTR':
            ptr_tok = self._eat('KW_PTR')
            base_node: TypeNode = PointerType(line=ptr_tok.line, col=ptr_tok.col, pointee=self.parse_type(), is_const=is_const)
        elif tok.kind == 'KW_FNPTR':
            fn_tok = self._eat('KW_FNPTR')
            self._eat('LPAREN')
            params: List[Tuple[TypeNode, Optional[str]]] = []
            seen_pnames = set()
            if self._cur().kind == 'TYPE_VOID' and self.tokens[self.pos + 1].kind == 'RPAREN':
                self._eat('TYPE_VOID')
            elif self._cur().kind != 'RPAREN':
                while True:
                    pt = decay_parameter_type(self.parse_type())
                    self._validate_non_void_var(pt, fn_tok)
                    pname = None
                    if self._cur().kind == 'IDENT':
                        ptok = self._eat('IDENT')
                        if ptok.value in seen_pnames:
                            raise SemanticError(f"{self.filename}:{ptok.line}:{ptok.col}: Duplicate parameter '{ptok.value}' in function pointer")
                        seen_pnames.add(ptok.value)
                        pname = ptok.value
                    params.append((pt, pname))
                    if self._cur().kind == 'COMMA':
                        self._eat('COMMA')
                    else:
                        break
            self._eat('RPAREN')
            self._eat('ARROW')
            ret_type = self.parse_type()
            if isinstance(ret_type, ArrayType):
                raise SemanticError(f"{self.filename}:{fn_tok.line}:{fn_tok.col}: Function cannot return array type")
            base_node = FunctionPointerType(line=fn_tok.line, col=fn_tok.col, param_decls=params, return_type=ret_type, is_const=is_const)
        elif tok.kind in ('TYPE_INT', 'TYPE_VOID', 'TYPE_BOOL'):
            t_tok = self._eat()
            c_map = {**BASIC_TYPES, 'v.': 'void', 'b.': 'bool'}
            base_node = BaseType(line=t_tok.line, col=t_tok.col, c_name=c_map[t_tok.value], is_const=is_const)
        elif tok.kind == 'IDENT' and tok.value in self.user_types:
            t_tok = self._eat('IDENT')
            base_node = BaseType(line=t_tok.line, col=t_tok.col, c_name=t_tok.value, is_const=is_const)
        elif tok.kind == 'LPAREN':
            self._eat('LPAREN')
            base_node = self.parse_type()
            self._eat('RPAREN')
            if is_const:
                base_node = with_const(base_node)
        else:
            raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: Expected type specifier, got '{tok.value}'")

        dims: List[Tuple[ExprNode, int]] = []
        while self._cur().kind == 'LBRACK':
            lb = self._eat('LBRACK')
            if is_void_type(base_node) or not self._is_complete_object_type(base_node):
                raise SemanticError(f"{self.filename}:{lb.line}:{lb.col}: Cannot declare array of incomplete or 'v.' (void) type")
            dim_e = self.parse_pure_expr()
            c_val = self._eval_const_int_expr(dim_e)
            if c_val is None or c_val <= 0:
                raise SemanticError(f"{self.filename}:{lb.line}:{lb.col}: Array size must be a positive integer constant expression")
            self._eat('RBRACK')
            dims.append((dim_e, c_val))

        for d_expr, d_val in reversed(dims):
            base_node = ArrayType(line=tok.line, col=tok.col, element_type=base_node, size_expr=d_expr, size_val=d_val)

        return base_node

    def parse_program(self) -> List[StmtNode]:
        top_nodes: List[StmtNode] = []
        while self._cur().kind != 'EOF':
            if self._cur().kind == 'PREPROC':
                ptok = self._eat('PREPROC')
                self._register_c99_header_builtins(ptok)
                top_nodes.append(PreprocNode(line=ptok.line, col=ptok.col, text=ptok.value))
            elif self._cur().kind in ('KW_STRUCT', 'KW_UNION'):
                top_nodes.append(self.parse_struct_or_union())
            elif self._cur().kind == 'KW_ENUM':
                top_nodes.append(self.parse_enum())
            elif self._is_type_start(self._cur()):
                top_nodes.append(self.parse_top_decl_or_func())
            else:
                tok = self._cur()
                raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: Unexpected top-level token '{tok.value}'")
        return top_nodes

    def parse_struct_or_union(self) -> StructDefNode:
        kw_tok = self._eat()
        kind = "struct" if kw_tok.kind == 'KW_STRUCT' else "union"
        name_tok = self._eat('IDENT')
        if name_tok.value in self.complete_structs:
            raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Redefinition of type '{name_tok.value}'")
        if name_tok.value in self.user_types and self.user_types[name_tok.value] != kind:
            raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: '{name_tok.value}' defined as wrong kind of tag")
        self.user_types[name_tok.value] = kind

        if self._cur().kind == 'SEMI':
            self._eat('SEMI')
            return StructDefNode(line=kw_tok.line, col=kw_tok.col, kind=kind, name=name_tok.value, alignment=None, fields=[])

        alignment = None
        if self._cur().kind == 'KW_ALIGN':
            align_tok = self._eat('KW_ALIGN')
            alignment = int(align_tok.value)
            if alignment <= 0 or (alignment & (alignment - 1)) != 0:
                raise SemanticError(f"{self.filename}:{align_tok.line}:{align_tok.col}: Alignment '{alignment}' must be a power of 2")

        self._eat('LBRACE')
        fields: List[VarDeclStmt] = []
        field_map: Dict[str, TypeNode] = {}
        while self._cur().kind != 'RBRACE':
            ft = self.parse_type()
            fname_tok = self._eat('IDENT')
            self._validate_non_void_var(ft, fname_tok)
            if not self._is_complete_object_type(ft):
                raise SemanticError(f"{self.filename}:{fname_tok.line}:{fname_tok.col}: Field '{fname_tok.value}' has incomplete type")
            if fname_tok.value in field_map:
                raise SemanticError(f"{self.filename}:{fname_tok.line}:{fname_tok.col}: Duplicate field '{fname_tok.value}' in {kind} '{name_tok.value}'")
            field_map[fname_tok.value] = ft
            self._eat('SEMI')
            fields.append(VarDeclStmt(line=fname_tok.line, col=fname_tok.col, var_type=ft, name=fname_tok.value))
        if not fields:
            raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Empty {kind} '{name_tok.value}' is forbidden in ISO C99")
        self._eat('RBRACE')
        self._eat('SEMI')
        self.struct_fields[name_tok.value] = field_map
        self.complete_structs.add(name_tok.value)
        return StructDefNode(line=kw_tok.line, col=kw_tok.col, kind=kind, name=name_tok.value, alignment=alignment, fields=fields)

    def parse_enum(self) -> EnumDefNode:
        kw_tok = self._eat('KW_ENUM')
        name_tok = self._eat('IDENT')
        if name_tok.value in self.user_types:
            raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Redefinition of enum '{name_tok.value}'")
        self.user_types[name_tok.value] = "enum"
        self._eat('LBRACE')
        items: List[Tuple[str, Optional[ExprNode]]] = []
        next_val = 0
        while self._cur().kind != 'RBRACE':
            item_tok = self._eat('IDENT')
            val_expr = None
            if self._cur().kind == 'OP_ASSIGN':
                self._eat('OP_ASSIGN')
                val_expr = self.parse_pure_expr()
                c_val = self._eval_const_int_expr(val_expr)
                if c_val is None:
                    raise SemanticError(f"{self.filename}:{item_tok.line}:{item_tok.col}: Enumerator value for '{item_tok.value}' is not an integer constant")
                next_val = c_val
            items.append((item_tok.value, val_expr))
            self.enum_constants[item_tok.value] = next_val
            next_val += 1
            self._register_symbol(item_tok.value, BaseType(line=item_tok.line, col=item_tok.col, c_name="int", is_const=True), item_tok)
            if self._cur().kind == 'COMMA':
                self._eat('COMMA')
            else:
                break
        if not items:
            raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Empty enum '{name_tok.value}' is forbidden in ISO C99")
        self._eat('RBRACE')
        self._eat('SEMI')
        return EnumDefNode(line=kw_tok.line, col=kw_tok.col, name=name_tok.value, items=items)

    def parse_top_decl_or_func(self) -> StmtNode:
        decl_type = self.parse_type()
        name_tok = self._eat('IDENT')

        if self._cur().kind == 'LPAREN':
            if isinstance(decl_type, ArrayType):
                raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Function '{name_tok.value}' cannot return array type")
            self._eat('LPAREN')
            params: List[Tuple[TypeNode, str]] = []
            seen_params = set()
            if self._cur().kind == 'TYPE_VOID' and self.tokens[self.pos + 1].kind == 'RPAREN':
                self._eat('TYPE_VOID')
            elif self._cur().kind != 'RPAREN':
                while True:
                    raw_pt = self.parse_type()
                    pt = decay_parameter_type(raw_pt)
                    pname = ''
                    if self._cur().kind == 'IDENT':
                        p_tok = self._eat('IDENT')
                        self._validate_non_void_var(pt, p_tok)
                        if p_tok.value in seen_params:
                            raise SemanticError(f"{self.filename}:{p_tok.line}:{p_tok.col}: Duplicate parameter '{p_tok.value}'")
                        seen_params.add(p_tok.value)
                        pname = p_tok.value
                    else:
                        self._validate_non_void_var(pt, name_tok)
                    params.append((pt, pname))
                    if self._cur().kind == 'COMMA':
                        self._eat('COMMA')
                    else:
                        break
            self._eat('RPAREN')

            param_types = [pt for pt, _ in params]

            if name_tok.value in self.scopes[0]:
                if name_tok.value not in self.func_sigs:
                    raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: '{name_tok.value}' redeclared as different kind of symbol")
                old_params, old_ret = self.func_sigs[name_tok.value]
                if len(old_params) != len(param_types) or not types_equal(strip_top_const(old_ret), strip_top_const(decl_type)) or not all(types_equal(strip_top_const(a), strip_top_const(b)) for a, b in zip(old_params, param_types)):
                    raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Conflicting types for function '{name_tok.value}'")

            fn_ptr_equiv = FunctionPointerType(line=name_tok.line, col=name_tok.col, param_decls=[(pt, pn) for pt, pn in params], return_type=decl_type)
            self.scopes[0][name_tok.value] = fn_ptr_equiv
            self.func_sigs[name_tok.value] = (param_types, decl_type)

            if self._cur().kind == 'SEMI':
                self._eat('SEMI')
                return FuncDefNode(line=name_tok.line, col=name_tok.col, return_type=decl_type, name=name_tok.value, params=params, body=None)

            if any(not pname for _, pname in params):
                raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Function definition parameters must have names")
            if name_tok.value in self.func_defined:
                raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Redefinition of function '{name_tok.value}'")
            self.func_defined.add(name_tok.value)

            prev_ret = self.current_func_ret
            self.current_func_ret = decl_type
            self.scopes.append({pname: pt for pt, pname in params})
            body = self.parse_block(create_new_scope=False)
            self.scopes.pop()
            self.current_func_ret = prev_ret
            if not is_void_type(decl_type) and name_tok.value != 'main' and self._can_fall_through(body):
                raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Control reaches end of non-void function '{name_tok.value}' without returning a value")
            return FuncDefNode(line=name_tok.line, col=name_tok.col, return_type=decl_type, name=name_tok.value, params=params, body=body)

        self._validate_non_void_var(decl_type, name_tok)
        self._register_symbol(name_tok.value, decl_type, name_tok)
        init_expr = None
        if self._cur().kind == 'OP_ASSIGN':
            op_tok = self._eat('OP_ASSIGN')
            init_expr = self.parse_pure_expr()
            actual_t = self._infer_expr_type(init_expr)
            if not self._check_assign_compatible(decl_type, init_expr, actual_t):
                raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Incompatible initializer type for '{name_tok.value}'")
            if not self._is_static_const_init(init_expr):
                raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Global initializer for '{name_tok.value}' is not a compile-time constant")
        self._eat('SEMI')
        return VarDeclStmt(line=name_tok.line, col=name_tok.col, var_type=decl_type, name=name_tok.value, init_expr=init_expr)

    def parse_block(self, create_new_scope: bool = True) -> BlockStmt:
        lb = self._eat('LBRACE')
        if create_new_scope:
            self.scopes.append({})
        stmts: List[StmtNode] = []
        while self._cur().kind != 'RBRACE':
            stmts.append(self.parse_stmt())
        self._eat('RBRACE')
        if create_new_scope:
            self.scopes.pop()
        return BlockStmt(line=lb.line, col=lb.col, stmts=stmts)

    def parse_stmt(self) -> StmtNode:
        tok = self._cur()
        if tok.kind == 'PREPROC':
            ptok = self._eat('PREPROC')
            return PreprocNode(line=ptok.line, col=ptok.col, text=ptok.value)
        if tok.kind == 'LBRACE':
            return self.parse_block(create_new_scope=True)
        if tok.kind == 'KW_IF':
            self._eat('KW_IF')
            self._eat('LPAREN')
            cond = self.parse_pure_expr()
            self._check_scalar_cond(cond, 'i?')
            self._eat('RPAREN')
            then_blk = self.parse_block()
            else_br = None
            if self._cur().kind == 'KW_ELSE':
                self._eat('KW_ELSE')
                else_br = self.parse_stmt() if self._cur().kind == 'KW_IF' else self.parse_block()
            return IfStmt(line=tok.line, col=tok.col, cond=cond, then_block=then_blk, else_branch=else_br)

        if tok.kind == 'KW_WHILE':
            self._eat('KW_WHILE')
            self._eat('LPAREN')
            cond = self.parse_pure_expr()
            self._check_scalar_cond(cond, 'w~')
            self._eat('RPAREN')
            self.loop_depth += 1
            body = self.parse_block()
            self.loop_depth -= 1
            return WhileStmt(line=tok.line, col=tok.col, cond=cond, body=body)

        if tok.kind == 'KW_FOR':
            self._eat('KW_FOR')
            self._eat('LPAREN')
            self.scopes.append({})
            init_stmt = None
            if self._cur().kind != 'SEMI':
                if self._is_type_start(self._cur()):
                    vt = self.parse_type()
                    vname = self._eat('IDENT')
                    self._validate_non_void_var(vt, vname)
                    self._register_symbol(vname.value, vt, vname)
                    vinit = None
                    if self._cur().kind == 'OP_ASSIGN':
                        op_tok = self._eat('OP_ASSIGN')
                        vinit = self.parse_pure_expr()
                        actual_t = self._infer_expr_type(vinit)
                        if not self._check_assign_compatible(vt, vinit, actual_t):
                            raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Incompatible initializer type for '{vname.value}'")
                    init_stmt = VarDeclStmt(line=vname.line, col=vname.col, var_type=vt, name=vname.value, init_expr=vinit)
                else:
                    init_stmt = self.parse_assign_or_expr_no_semi()
            self._eat('SEMI')
            cond_expr = None if self._cur().kind == 'SEMI' else self.parse_pure_expr()
            if cond_expr is not None:
                self._check_scalar_cond(cond_expr, 'f~')
            self._eat('SEMI')
            step_stmt = None if self._cur().kind == 'RPAREN' else self.parse_assign_or_expr_no_semi()
            self._eat('RPAREN')
            self.loop_depth += 1
            body = self.parse_block()
            self.loop_depth -= 1
            self.scopes.pop()
            return ForStmt(line=tok.line, col=tok.col, init_stmt=init_stmt, cond_expr=cond_expr, step_stmt=step_stmt, body=body)

        if tok.kind == 'KW_SWITCH':
            return self.parse_switch()

        if tok.kind == 'KW_RETURN':
            self._eat('KW_RETURN')
            if self.current_func_ret is None:
                raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'r;' (return) outside of function")
            expr = None if self._cur().kind == 'SEMI' else self.parse_pure_expr()
            self._eat('SEMI')
            if is_void_type(self.current_func_ret) and expr is not None:
                raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'v.' (void) function cannot return a value")
            if not is_void_type(self.current_func_ret):
                if expr is None:
                    raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Non-void function must return a value")
                ret_expr_t = self._infer_expr_type(expr)
                if not self._check_assign_compatible(self.current_func_ret, expr, ret_expr_t):
                    raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Incompatible return type")
            return ReturnStmt(line=tok.line, col=tok.col, expr=expr)

        if tok.kind == 'KW_BREAK':
            self._eat('KW_BREAK')
            self._eat('SEMI')
            if self.loop_depth == 0 and self.switch_depth == 0:
                raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'b!' (break) statement not within loop or switch")
            return JumpStmt(line=tok.line, col=tok.col, keyword="break")

        if tok.kind == 'KW_CONTINUE':
            self._eat('KW_CONTINUE')
            self._eat('SEMI')
            if self.loop_depth == 0:
                raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'c^' (continue) statement not within a loop")
            return JumpStmt(line=tok.line, col=tok.col, keyword="continue")

        if self._is_type_start(tok):
            vt = self.parse_type()
            vname = self._eat('IDENT')
            self._validate_non_void_var(vt, vname)
            self._register_symbol(vname.value, vt, vname)
            vinit = None
            if self._cur().kind == 'OP_ASSIGN':
                op_tok = self._eat('OP_ASSIGN')
                vinit = self.parse_pure_expr()
                actual_t = self._infer_expr_type(vinit)
                if not self._check_assign_compatible(vt, vinit, actual_t):
                    raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Incompatible initializer type for '{vname.value}'")
            self._eat('SEMI')
            return VarDeclStmt(line=vname.line, col=vname.col, var_type=vt, name=vname.value, init_expr=vinit)

        stmt = self.parse_assign_or_expr_no_semi()
        self._eat('SEMI')
        return stmt

    def parse_switch(self) -> SwitchStmt:
        sw_tok = self._eat('KW_SWITCH')
        self._eat('LPAREN')
        cond = self.parse_pure_expr()
        cond_t = self._infer_expr_type(cond)
        if not isinstance(cond_t, BaseType) or (cond_t.c_name not in INT_C_TYPES and self.user_types.get(cond_t.c_name) != "enum"):
            raise SemanticError(f"{self.filename}:{sw_tok.line}:{sw_tok.col}: Switch quantity is not an integer or enum")
        self._eat('RPAREN')
        self._eat('LBRACE')
        self.switch_depth += 1
        cases: List[CaseClause] = []
        seen_case_vals: Set[int] = set()
        has_default = False

        while self._cur().kind != 'RBRACE':
            if self._cur().kind == 'KW_CASE':
                c_tok = self._eat('KW_CASE')
                c_val = self.parse_pure_expr()
                const_int = self._eval_const_int_expr(c_val)
                if const_int is None:
                    raise SemanticError(f"{self.filename}:{c_tok.line}:{c_tok.col}: Case label does not reduce to an integer constant")
                if const_int in seen_case_vals:
                    raise SemanticError(f"{self.filename}:{c_tok.line}:{c_tok.col}: Duplicate case value '{const_int}'")
                seen_case_vals.add(const_int)
                self._eat('COLON')
                self.scopes.append({})
                c_stmts: List[StmtNode] = []
                while self._cur().kind not in ('KW_CASE', 'KW_DEFAULT', 'RBRACE'):
                    c_stmts.append(self.parse_stmt())
                self.scopes.pop()
                cases.append(CaseClause(line=c_tok.line, value=c_val, stmts=c_stmts))
            elif self._cur().kind == 'KW_DEFAULT':
                d_tok = self._eat('KW_DEFAULT')
                if has_default:
                    raise SemanticError(f"{self.filename}:{d_tok.line}:{d_tok.col}: Multiple 'd:' (default) labels in one switch")
                has_default = True
                if self._cur().kind == 'COLON':
                    self._eat('COLON')
                self.scopes.append({})
                d_stmts: List[StmtNode] = []
                while self._cur().kind not in ('KW_CASE', 'KW_DEFAULT', 'RBRACE'):
                    d_stmts.append(self.parse_stmt())
                self.scopes.pop()
                cases.append(CaseClause(line=d_tok.line, value=None, stmts=d_stmts))
            else:
                tok = self._cur()
                raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: Expected 'k:' (case) or 'd:' (default) inside switch")
        self.switch_depth -= 1
        self._eat('RBRACE')
        return SwitchStmt(line=sw_tok.line, col=sw_tok.col, cond=cond, cases=cases)

    def parse_assign_or_expr_no_semi(self) -> StmtNode:
        tok = self._cur()
        lhs = self.parse_ternary()
        if self._cur().kind in ASSIGN_TOKENS:
            op_tok = self._eat()
            self._check_modifiable_lvalue(lhs, op_tok)
            rhs = self.parse_pure_expr()
            lhs_t = self._infer_expr_type(lhs)
            rhs_t = self._infer_expr_type(rhs)
            if op_tok.kind == 'OP_ASSIGN':
                if not self._check_assign_compatible(lhs_t, rhs, rhs_t):
                    raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Incompatible types in assignment 'm,'")
            else:
                self._check_compound_assign_types(op_tok.kind, lhs_t, rhs_t, op_tok)
            return AssignStmt(line=op_tok.line, col=op_tok.col, op=ASSIGN_TOKENS[op_tok.kind], target=lhs, value=rhs)
        self._infer_expr_type(lhs)
        return ExprStmt(line=tok.line, col=tok.col, expr=lhs)

    def parse_pure_expr(self) -> ExprNode:
        node = self.parse_ternary()
        if self._cur().kind in ASSIGN_TOKENS:
            op_tok = self._cur()
            raise SemanticError(
                f"{self.filename}:{op_tok.line}:{op_tok.col}: "
                f"Side-effect assignment operator '{op_tok.value}' ({ASSIGN_TOKENS[op_tok.kind]}) "
                f"is forbidden inside pure/conditional expressions; use '-' for subtraction or move assignment to a standalone statement."
            )
        return node

    def parse_ternary(self) -> ExprNode:
        cond = self.parse_lor()
        if self._cur().kind == 'QUESTION':
            q_tok = self._eat('QUESTION')
            self._check_scalar_cond(cond, '?:')
            then_e = self.parse_pure_expr()
            self._eat('COLON')
            else_e = self.parse_ternary()
            node = TernaryExpr(line=q_tok.line, col=q_tok.col, cond=cond, then_expr=then_e, else_expr=else_e)
            self._infer_expr_type(node)
            return node
        return cond

    def parse_lor(self) -> ExprNode:
        node = self.parse_land()
        while self._cur().kind == 'OP_LOR':
            op_tok = self._eat()
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op='||', left=node, right=self.parse_land())
        return node

    def parse_land(self) -> ExprNode:
        node = self.parse_bor()
        while self._cur().kind == 'OP_LAND':
            op_tok = self._eat()
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op='&&', left=node, right=self.parse_bor())
        return node

    def parse_bor(self) -> ExprNode:
        node = self.parse_bxor()
        while self._cur().kind == 'OP_BOR':
            op_tok = self._eat()
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op='|', left=node, right=self.parse_bxor())
        return node

    def parse_bxor(self) -> ExprNode:
        node = self.parse_band()
        while self._cur().kind == 'OP_BXOR':
            op_tok = self._eat()
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op='^', left=node, right=self.parse_band())
        return node

    def parse_band(self) -> ExprNode:
        node = self.parse_equality()
        while self._cur().kind == 'OP_BAND':
            op_tok = self._eat()
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op='&', left=node, right=self.parse_equality())
        return node

    def parse_equality(self) -> ExprNode:
        node = self.parse_relational()
        while self._cur().kind in ('OP_EQ', 'OP_NE'):
            op_tok = self._eat()
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op='==' if op_tok.kind == 'OP_EQ' else '!=', left=node, right=self.parse_relational())
        return node

    def parse_relational(self) -> ExprNode:
        node = self.parse_shift()
        rel_map = {'LT': '<', 'GT': '>', 'OP_LE': '<=', 'OP_GE': '>='}
        while self._cur().kind in rel_map:
            op_tok = self._eat()
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op=rel_map[op_tok.kind], left=node, right=self.parse_shift())
        return node

    def parse_shift(self) -> ExprNode:
        node = self.parse_additive()
        while self._cur().kind in ('OP_SHL', 'OP_SHR'):
            op_tok = self._eat()
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op=op_tok.value, left=node, right=self.parse_additive())
        return node

    def parse_additive(self) -> ExprNode:
        node = self.parse_multiplicative()
        while self._cur().kind in ('PLUS', 'MINUS'):
            op_tok = self._eat()
            right = self.parse_multiplicative()
            self._check_not_void_expr(node, op_tok)
            self._check_not_void_expr(right, op_tok)
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op=op_tok.value, left=node, right=right)
        return node

    def parse_multiplicative(self) -> ExprNode:
        node = self.parse_unary()
        while self._cur().kind in ('STAR', 'SLASH', 'PERCENT'):
            op_tok = self._eat()
            right = self.parse_unary()
            self._check_not_void_expr(node, op_tok)
            self._check_not_void_expr(right, op_tok)
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op=op_tok.value, left=node, right=right)
        return node

    def _check_not_void_expr(self, expr: ExprNode, op_tok: Token):
        t = self._infer_expr_type(expr)
        if is_void_type(t):
            raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Void value cannot be used in expression")

    def parse_unary(self) -> ExprNode:
        tok = self._cur()
        # 支持显式类型转换表达式 (Type)expr，如 (u4)w * (u4)h
        if tok.kind == 'LPAREN' and self._is_type_start_at(self.pos + 1):
            self._eat('LPAREN')
            target_t = self.parse_type()
            self._eat('RPAREN')
            operand = self.parse_unary()
            return CastExpr(line=tok.line, col=tok.col, target_type=target_t, operand=operand)

        unary_map = {'MINUS': '-', 'PLUS': '+', 'OP_LNOT': '!', 'OP_BNOT': '~', 'KW_PTR': '*', 'KW_ADDR': '&'}
        if tok.kind in unary_map:
            self._eat()
            operand = self.parse_unary()
            node = UnaryExpr(line=tok.line, col=tok.col, op=unary_map[tok.kind], operand=operand)
            self._infer_expr_type(node)
            return node
        return self.parse_postfix()

    def parse_postfix(self) -> ExprNode:
        node = self.parse_primary()
        while True:
            tok = self._cur()
            if tok.kind == 'LBRACK':
                self._eat('LBRACK')
                idx_e = self.parse_pure_expr()
                self._eat('RBRACK')
                node = IndexExpr(line=tok.line, col=tok.col, base=node, index=idx_e)
                self._infer_expr_type(node)
            elif tok.kind in ('DOT', 'ARROW'):
                self._eat()
                field_tok = self._eat('IDENT')
                node = MemberExpr(line=tok.line, col=tok.col, base=node, field=field_tok.value, is_arrow=(tok.kind == 'ARROW'))
                self._infer_expr_type(node)
            elif tok.kind == 'LPAREN':
                self._eat('LPAREN')
                args: List[ExprNode] = []
                if self._cur().kind != 'RPAREN':
                    while True:
                        args.append(self.parse_pure_expr())
                        if self._cur().kind == 'COMMA':
                            self._eat('COMMA')
                        else:
                            break
                self._eat('RPAREN')

                callee_t = self._infer_expr_type(node)
                if isinstance(callee_t, FunctionPointerType):
                    expected_params = [pt for pt, _ in callee_t.param_decls]
                    if callee_t.is_variadic:
                        if len(args) < len(expected_params):
                            raise SemanticError(
                                f"{self.filename}:{tok.line}:{tok.col}: Variadic callable expects at least {len(expected_params)} arguments, got {len(args)}"
                            )
                    elif len(args) != len(expected_params):
                        raise SemanticError(
                            f"{self.filename}:{tok.line}:{tok.col}: Callable expects {len(expected_params)} arguments, got {len(args)}"
                        )
                    for idx, arg_e in enumerate(args, 1):
                        act_t = self._infer_expr_type(arg_e)
                        if is_void_type(act_t):
                            raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Argument {idx} cannot have 'v.' (void) type")
                        if idx <= len(expected_params):
                            exp_t = expected_params[idx - 1]
                            if not self._check_assign_compatible(exp_t, arg_e, act_t):
                                raise SemanticError(
                                    f"{self.filename}:{tok.line}:{tok.col}: Incompatible type for argument {idx} in call"
                                )
                else:
                    raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Called object is not a function or function pointer")

                node = CallExpr(line=tok.line, col=tok.col, callee=node, args=args)
            else:
                break
        return node

    def parse_primary(self) -> ExprNode:
        tok = self._cur()
        if tok.kind in ('INT_NUM', 'FLOAT_NUM', 'STRING', 'CHAR'):
            self._eat()
            return LiteralExpr(line=tok.line, col=tok.col, code=tok.value, lit_kind=tok.kind)
        if tok.kind == 'IDENT':
            self._eat('IDENT')
            self._lookup_symbol(tok.value, tok)
            return IdentExpr(line=tok.line, col=tok.col, name=tok.value)
        if tok.kind == 'LPAREN':
            self._eat('LPAREN')
            e = self.parse_pure_expr()
            self._eat('RPAREN')
            return e
        raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: Unexpected token '{tok.value}'")


# ============================================================================
# 4. C99 Code Generator
# ============================================================================

C99_HEADER = """/* Generated by Sigil-C v0.5.2 AST Compiler. DO NOT EDIT. */
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#if defined(_MSC_VER)
  #define SIGIL_ALIGNED_TAG(kind, name, n) __declspec(align(n)) kind name
#elif defined(__GNUC__) || defined(__clang__)
  #define SIGIL_ALIGNED_TAG(kind, name, n) __extension__ kind __attribute__((aligned(n))) name
#else
  #define SIGIL_ALIGNED_TAG(kind, name, n) kind name
#endif

"""

class CodeGenerator:
    def __init__(self, filename: str = "input.sigil"):
        self.safe_filename = filename.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '')
        self.lines: List[str] = [C99_HEADER]

    def _emit(self, code: str, line: int, indent: int = 0):
        pad = "    " * indent
        self.lines.append(f'#line {line} "{self.safe_filename}"\n{pad}{code}\n')

    def generate(self, nodes: List[StmtNode]) -> str:
        for node in nodes:
            self.gen_top(node)
        return "".join(self.lines)

    def gen_top(self, node: StmtNode):
        if isinstance(node, PreprocNode):
            self._emit(node.text, node.line, indent=0)
        elif isinstance(node, StructDefNode):
            self._emit(f"typedef {node.kind} {node.name} {node.name};", node.line)
            if node.fields:
                if node.alignment:
                    self._emit(f"SIGIL_ALIGNED_TAG({node.kind}, {node.name}, {node.alignment}) {{", node.line)
                else:
                    self._emit(f"{node.kind} {node.name} {{", node.line)
                for f in node.fields:
                    self._emit(f"{format_c_declarator(f.var_type, f.name)};", f.line, indent=1)
                self._emit("};", node.line)
        elif isinstance(node, EnumDefNode):
            self._emit(f"typedef enum {node.name} {{", node.line)
            for idx, (iname, ival) in enumerate(node.items):
                comma = "," if idx < len(node.items) - 1 else ""
                self._emit(f"{iname}{f' = {emit_expr(ival)}' if ival else ''}{comma}", node.line, indent=1)
            self._emit(f"}} {node.name};", node.line)
        elif isinstance(node, FuncDefNode):
            params_c = [format_c_declarator(pt, pname) for pt, pname in node.params]
            fn_sig = format_c_declarator(node.return_type, f"{node.name}({', '.join(params_c) if params_c else 'void'})")
            if node.body is None:
                self._emit(f"{fn_sig};", node.line)
            else:
                self._emit(f"{fn_sig} {{", node.line)
                for s in node.body.stmts:
                    self.gen_stmt(s, indent=1)
                self._emit("}", node.line)
        elif isinstance(node, VarDeclStmt):
            self.gen_stmt(node, indent=0)

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
            self._emit(f"{decl}{f' = {emit_expr(s.init_expr)}' if s.init_expr else ''};", s.line, indent)
        elif isinstance(s, AssignStmt):
            self._emit(f"{emit_expr(s.target)} {s.op} {emit_expr(s.value)};", s.line, indent)
        elif isinstance(s, ExprStmt):
            self._emit(f"{emit_expr(s.expr)};", s.line, indent)
        elif isinstance(s, ReturnStmt):
            self._emit(f"return{f' {emit_expr(s.expr)}' if s.expr else ''};", s.line, indent)
        elif isinstance(s, JumpStmt):
            self._emit(f"{s.keyword};", s.line, indent)
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
            for c in s.cases:
                if c.value is not None:
                    self._emit(f"case {emit_expr(c.value)}: {{", c.line, indent + 1)
                else:
                    self._emit("default: {", c.line, indent + 1)
                for sub in c.stmts:
                    self.gen_stmt(sub, indent + 2)
                self._emit("}", c.line, indent + 1)
            self._emit("}", s.line, indent)

def compile_source(src: str, filename: str = "input.sigil") -> str:
    tokens = Lexer(src, filename).tokenize()
    ast = Parser(tokens, filename).parse_program()
    return CodeGenerator(filename).generate(ast)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 sigilc.py <input.sigil> [-o output.c | output.c]")
        sys.exit(1)
    in_path = sys.argv[1]
    if len(sys.argv) >= 4 and sys.argv[2] == "-o":
        out_path = sys.argv[3]
    elif len(sys.argv) > 2:
        out_path = sys.argv[2]
    else:
        out_path = os.path.splitext(in_path)[0] + ".c"
    with open(in_path, "r", encoding="utf-8") as f:
        c_src = compile_source(f.read(), os.path.basename(in_path))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(c_src)
    print(f"Compiled {in_path} -> {out_path}")
