#!/usr/bin/env python3
"""
Sigil-C v1.1 Compiler
Source -> DFA Lexer -> Recursive-Descent AST Parser -> Static Semantic Analyzer -> C99 Codegen
"""

import sys
import os
import re
import argparse
from dataclasses import dataclass, field
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
    'e{': 'KW_ENUM',     'o!': 'KW_OBJECT',   'f^': 'KW_FNPTR',    'p*': 'KW_PTR',
    'a&': 'KW_ADDR',
    'c@': 'KW_CONST',    'v@': 'KW_VOLATILE', 'v.': 'TYPE_VOID',   'b.': 'TYPE_BOOL',
    'z?': 'KW_SIZEOF',   's@': 'KW_STATIC',   'a@': 'KW_ATTR',
    'i@': 'KW_INLINE',   'w!': 'KW_BITFIELD', 't!': 'KW_STATIC_ASSERT',
    'd~': 'KW_DO',       'g!': 'KW_GOTO',     'l!': 'KW_LABEL',
    'r@': 'KW_RESTRICT',  'g?': 'KW_GENERIC',
    'x!': 'KW_EXTERNAL',
}

# x! 声明的外部类型：Sigil 侧名字 -> 生成 C 里的实际拼写
# （例如 x! struct sockaddr_in { ... }; 这里记 sockaddr_in -> "struct sockaddr_in"）
EXTERNAL_C_SPELLING: Dict[str, str] = {}

SIGIL_OPERATORS = {
    'm,': 'OP_ASSIGN',      'm+': 'OP_ADD_ASSIGN',  'm-': 'OP_SUB_ASSIGN',
    'm*': 'OP_MUL_ASSIGN',  'm/': 'OP_DIV_ASSIGN',  '=?': 'OP_EQ',
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
    'va_list': 'va_list',
}

INT_C_TYPES = {
    'int8_t', 'int16_t', 'int32_t', 'int64_t',
    'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
    'char', 'bool', 'int', 'size_t', 'ptrdiff_t', 'intptr_t', 'uintptr_t'
}

NUMERIC_C_TYPES = INT_C_TYPES | {'float', 'double', 'long double'}

# w! 位域：基底类型 -> 允许的最大位宽（C99 要求位域宽度不超过该类型位宽）
BITFIELD_WIDTH = {
    'bool': 1, 'char': 8,
    'int8_t': 8, 'uint8_t': 8,
    'int16_t': 16, 'uint16_t': 16,
    'int32_t': 32, 'uint32_t': 32,
    'int64_t': 64, 'uint64_t': 64,
    'int': 32, 'size_t': 64, 'ptrdiff_t': 64, 'intptr_t': 64, 'uintptr_t': 64,
}
VALID_SIMPLE_ESCAPES = set('abfnrtv\\\'"?0')
VALID_INTEGER_SUFFIXES = {
    '', 'u', 'U', 'l', 'L', 'll', 'LL',
    'ul', 'uL', 'Ul', 'UL', 'lu', 'lU', 'Lu', 'LU',
    'ull', 'uLL', 'Ull', 'ULL', 'llu', 'llU', 'LLu', 'LLU',
}

# ----------------------------------------------------------------------------
# a@(...) 属性白名单：词法记号 KW_ATTR 之后是括号内的 GNU 属性列表。
# 白名单同时充当"参数形状"与"允许的放置位置"两张表——未知属性、参数个数或
# 类型不符、放错声明种类，都在转译期报错，而不是留给后端 C 编译器去猜。
# ----------------------------------------------------------------------------
ATTR_NOARGS = {
    'unused', 'noreturn', 'packed', 'always_inline', 'noinline',
    'warn_unused_result', 'weak', 'malloc', 'pure', 'const', 'hot', 'cold',
    'returns_nonnull', 'constructor', 'destructor',
}
ATTR_ONE_INT = {'aligned'}                      # aligned(N)：N 为 2 的幂
ATTR_ONE_STRING = {'section', 'visibility', 'alias'}
ATTR_OPTIONAL_STRING = {'deprecated'}           # deprecated 或 deprecated("msg")
ATTR_INT_LIST = {'nonnull'}                     # nonnull(1) / nonnull(1, 2)

ATTR_TARGETS = {
    'packed': {'type'},
    'aligned': {'type', 'object', 'field'},
    'noreturn': {'function'},
    'always_inline': {'function'},
    'noinline': {'function'},
    'warn_unused_result': {'function'},
    'malloc': {'function'},
    'pure': {'function'},
    'const': {'function'},
    'hot': {'function'},
    'cold': {'function'},
    'returns_nonnull': {'function'},
    'constructor': {'function'},
    'destructor': {'function'},
    'alias': {'function'},
    'nonnull': {'function'},
    'unused': {'function', 'object', 'field', 'type'},
    'deprecated': {'function', 'object', 'field', 'type'},
    'weak': {'function', 'object'},
    'section': {'function', 'object'},
    'visibility': {'function', 'object'},
}

# 这些属性只对具有静态存储期的实体有意义，块作用域对象上出现即报错。
ATTR_FILE_SCOPE_ONLY = {'weak', 'section', 'visibility', 'alias'}

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
                if word in ('true', 'false'):
                    tokens.append(Token('BOOL_LIT', word, s_line, s_col, s_byte))
                elif word == 'NULL':
                    tokens.append(Token('NULL_LIT', word, s_line, s_col, s_byte))
                elif word in BASIC_TYPES:
                    tokens.append(Token('TYPE_INT', word, s_line, s_col, s_byte))
                else:
                    tokens.append(Token('IDENT', word, s_line, s_col, s_byte))
                continue

            if ch == '.' and nxt == '.' and self._peek(2) == '.':
                self._advance(3)
                tokens.append(Token('ELLIPSIS', '...', s_line, s_col, s_byte))
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
    is_volatile: bool = False

@dataclass
class PointerType(TypeNode):
    pointee: TypeNode
    is_const: bool = False
    is_volatile: bool = False
    is_restrict: bool = False

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
    is_volatile: bool = False
    is_variadic: bool = False

def is_void_type(t: TypeNode) -> bool:
    return isinstance(t, BaseType) and t.c_name == "void"

def is_const_qualified(t: TypeNode) -> bool:
    if isinstance(t, ArrayType):
        return is_const_qualified(t.element_type)
    if isinstance(t, (BaseType, PointerType, FunctionPointerType)):
        return t.is_const
    return False

def is_volatile_qualified(t: TypeNode) -> bool:
    if isinstance(t, ArrayType):
        return is_volatile_qualified(t.element_type)
    if isinstance(t, (BaseType, PointerType, FunctionPointerType)):
        return t.is_volatile
    return False

def strip_top_qualifiers(t: TypeNode) -> TypeNode:
    if isinstance(t, BaseType):
        return BaseType(line=t.line, col=t.col, c_name=t.c_name, is_const=False, is_volatile=False)
    if isinstance(t, PointerType):
        return PointerType(line=t.line, col=t.col, pointee=t.pointee, is_const=False, is_volatile=False, is_restrict=False)
    if isinstance(t, FunctionPointerType):
        return FunctionPointerType(line=t.line, col=t.col, param_decls=t.param_decls, return_type=t.return_type, is_const=False, is_volatile=False, is_variadic=t.is_variadic)
    if isinstance(t, ArrayType):
        return ArrayType(line=t.line, col=t.col, element_type=strip_top_qualifiers(t.element_type), size_expr=t.size_expr, size_val=t.size_val)
    return t

def with_const(t: TypeNode) -> TypeNode:
    if isinstance(t, BaseType):
        return BaseType(line=t.line, col=t.col, c_name=t.c_name, is_const=True, is_volatile=t.is_volatile)
    if isinstance(t, PointerType):
        return PointerType(line=t.line, col=t.col, pointee=t.pointee, is_const=True, is_volatile=t.is_volatile, is_restrict=t.is_restrict)
    if isinstance(t, FunctionPointerType):
        return FunctionPointerType(line=t.line, col=t.col, param_decls=t.param_decls, return_type=t.return_type, is_const=True, is_volatile=t.is_volatile, is_variadic=t.is_variadic)
    if isinstance(t, ArrayType):
        return ArrayType(line=t.line, col=t.col, element_type=with_const(t.element_type), size_expr=t.size_expr, size_val=t.size_val)
    return t

def with_volatile(t: TypeNode) -> TypeNode:
    if isinstance(t, BaseType):
        return BaseType(line=t.line, col=t.col, c_name=t.c_name, is_const=t.is_const, is_volatile=True)
    if isinstance(t, PointerType):
        return PointerType(line=t.line, col=t.col, pointee=t.pointee, is_const=t.is_const, is_volatile=True, is_restrict=t.is_restrict)
    if isinstance(t, FunctionPointerType):
        return FunctionPointerType(line=t.line, col=t.col, param_decls=t.param_decls, return_type=t.return_type, is_const=t.is_const, is_volatile=True, is_variadic=t.is_variadic)
    if isinstance(t, ArrayType):
        return ArrayType(line=t.line, col=t.col, element_type=with_volatile(t.element_type), size_expr=t.size_expr, size_val=t.size_val)
    return t

def qualifiers_are_assignable(destination: TypeNode, source: TypeNode) -> bool:
    if isinstance(destination, ArrayType) and isinstance(source, ArrayType):
        return qualifiers_are_assignable(destination.element_type, source.element_type)
    return not (
        (is_const_qualified(source) and not is_const_qualified(destination))
        or (is_volatile_qualified(source) and not is_volatile_qualified(destination))
    )

def decay_parameter_type(t: TypeNode) -> TypeNode:
    """C99 6.7.5.3p7: 函数形参最外层数组退化为指针；非数组形参保留顶层 const/volatile 供函数体检查"""
    if isinstance(t, ArrayType):
        return PointerType(line=t.line, col=t.col, pointee=t.element_type, is_const=False)
    return t

def types_equal(a: TypeNode, b: TypeNode) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, BaseType) and isinstance(b, BaseType):
        return a.c_name == b.c_name and a.is_const == b.is_const and a.is_volatile == b.is_volatile
    if isinstance(a, PointerType) and isinstance(b, PointerType):
        return a.is_const == b.is_const and a.is_volatile == b.is_volatile and types_equal(a.pointee, b.pointee)
    if isinstance(a, ArrayType) and isinstance(b, ArrayType):
        same_len = (a.size_val == b.size_val) if (a.size_val is not None and b.size_val is not None) else (emit_expr(a.size_expr) == emit_expr(b.size_expr))
        return types_equal(a.element_type, b.element_type) and same_len
    if isinstance(a, FunctionPointerType) and isinstance(b, FunctionPointerType):
        if a.is_const != b.is_const or a.is_volatile != b.is_volatile or len(a.param_decls) != len(b.param_decls) or a.is_variadic != b.is_variadic:
            return False
        if not types_equal(strip_top_qualifiers(a.return_type), strip_top_qualifiers(b.return_type)):
            return False
        return all(types_equal(strip_top_qualifiers(decay_parameter_type(pa[0])), strip_top_qualifiers(decay_parameter_type(pb[0]))) for pa, pb in zip(a.param_decls, b.param_decls))
    return False

def types_compatible_for_assign(expected: TypeNode, actual: TypeNode) -> bool:
    exp_clean = expected if isinstance(expected, ArrayType) else strip_top_qualifiers(expected)
    act_clean = actual if isinstance(actual, ArrayType) else strip_top_qualifiers(actual)
    if types_equal(exp_clean, act_clean):
        return True
    if isinstance(exp_clean, BaseType) and isinstance(act_clean, BaseType):
        if exp_clean.c_name in NUMERIC_C_TYPES and act_clean.c_name in NUMERIC_C_TYPES:
            return True
    if isinstance(exp_clean, PointerType) and isinstance(act_clean, ArrayType):
        if types_equal(strip_top_qualifiers(exp_clean.pointee), strip_top_qualifiers(act_clean.element_type)):
            if qualifiers_are_assignable(exp_clean.pointee, act_clean.element_type):
                return True
    if isinstance(exp_clean, PointerType) and isinstance(act_clean, PointerType):
        if is_void_type(exp_clean.pointee) or is_void_type(act_clean.pointee):
            if qualifiers_are_assignable(exp_clean.pointee, act_clean.pointee):
                return True
        if types_equal(strip_top_qualifiers(exp_clean.pointee), strip_top_qualifiers(act_clean.pointee)):
            return qualifiers_are_assignable(exp_clean.pointee, act_clean.pointee)
    return False

def format_c_declarator(t: TypeNode, var_name: str = "") -> str:
    inner = var_name
    curr = t
    while True:
        if isinstance(curr, BaseType):
            qualifiers = [q for enabled, q in ((curr.is_const, "const"), (curr.is_volatile, "volatile")) if enabled]
            prefix = " ".join(qualifiers) + (" " if qualifiers else "")
            c_name = EXTERNAL_C_SPELLING.get(curr.c_name, curr.c_name)
            return f"{prefix}{c_name}" + (f" {inner}" if inner else "")
        elif isinstance(curr, PointerType):
            qualifiers = " ".join(q for enabled, q in ((curr.is_const, "const"), (curr.is_volatile, "volatile"), (curr.is_restrict, "restrict")) if enabled)
            ptr_str = f"* {qualifiers} {inner}" if qualifiers and inner else (f"* {qualifiers}" if qualifiers else f"*{inner}")
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
            if curr.is_variadic:
                params_c.append("...")
            param_list_str = ", ".join(params_c) if params_c else "void"
            qualifiers = " ".join(q for enabled, q in ((curr.is_const, "const"), (curr.is_volatile, "volatile")) if enabled)
            qual = f"{qualifiers} " if qualifiers else ""
            fn_inner = f"(*{qual}{inner})({param_list_str})"
            return format_c_declarator(curr.return_type, fn_inner)
        else:
            raise TypeError(f"Unknown TypeNode: {curr}")

@dataclass
class Attribute:
    """a@(...) 里的一个属性：名字 + 已校验的实参文本。"""
    name: str
    args: List[str] = field(default_factory=list)

    def render(self) -> str:
        if not self.args:
            return self.name
        return f"{self.name}({', '.join(self.args)})"

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
    bound: Optional[int] = None

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
    is_static: bool = False
    attrs: List[Attribute] = field(default_factory=list)
    bit_width: Optional[int] = None

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
class DoWhileStmt(StmtNode):
    body: BlockStmt
    cond: ExprNode

@dataclass
class StaticAssertStmt(StmtNode):
    cond: ExprNode
    message: str

@dataclass
class GotoStmt(StmtNode):
    label: str

@dataclass
class LabelStmt(StmtNode):
    name: str

@dataclass
class VaStmt(StmtNode):
    """`va_start(ap, last);` / `va_end(ap);` / `va_copy(dst, src);`"""
    kind: str
    ap: ExprNode
    last_name: Optional[str] = None
    ap2: Optional[ExprNode] = None

@dataclass
class StructDefNode(StmtNode):
    kind: str
    name: str
    alignment: Optional[int]
    fields: List[VarDeclStmt]
    emit_typedef: bool = True
    attrs: List[Attribute] = field(default_factory=list)

@dataclass
class ExternalTypeNode(StmtNode):
    """`x!` 外部类型：不生成定义，只登记字段供转译期检查。"""
    name: str
    c_spelling: str
    opaque: bool
    field_count: int = 0

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
    is_static: bool = False
    attrs: List[Attribute] = field(default_factory=list)
    is_inline: bool = False
    is_variadic: bool = False

@dataclass
class SizeofExpr(ExprNode):
    target_type: Optional[TypeNode]
    operand: Optional[ExprNode]

@dataclass
class AggregateInit(ExprNode):
    """`{ e1, e2, ... }` 位置式聚合初始化；只允许出现在声明初始化位置。"""
    elements: List[ExprNode]

@dataclass
class DesignatedInit(ExprNode):
    """`{ .field m, value }` 指定式初始化元素（C99 的 `.field = value`）。"""
    field: str
    value: 'ExprNode'

@dataclass
class DesignatedIndex(ExprNode):
    """`{ [2] m, value }` 数组下标指定初始化元素（C99 的 `[2] = value`）。"""
    index_expr: ExprNode
    index_val: int
    value: 'ExprNode'

@dataclass
class CompoundLiteral(ExprNode):
    """`(Type){ ... }` 复合字面量。"""
    target_type: TypeNode
    init: 'AggregateInit'

@dataclass
class VaArgExpr(ExprNode):
    """`v^ ap, T` 读取下一个可变参，结果类型为 T。"""
    ap: ExprNode
    target_type: TypeNode

@dataclass
class OffsetofExpr(ExprNode):
    """`offsetof(Type, field)` 内建形式。"""
    target_type: TypeNode
    field: str

def emit_expr(e: ExprNode) -> str:
    if isinstance(e, LiteralExpr):
        return e.code
    if isinstance(e, AggregateInit):
        return "{ " + ", ".join(emit_expr(x) for x in e.elements) + " }"
    if isinstance(e, DesignatedInit):
        return f".{e.field} = {emit_expr(e.value)}"
    if isinstance(e, DesignatedIndex):
        return f"[{emit_expr(e.index_expr)}] = {emit_expr(e.value)}"
    if isinstance(e, CompoundLiteral):
        return f"(({format_c_declarator(e.target_type)}){emit_expr(e.init)})"
    if isinstance(e, VaArgExpr):
        return f"va_arg({emit_expr(e.ap)}, {format_c_declarator(e.target_type)})"
    if isinstance(e, OffsetofExpr):
        return f"offsetof({format_c_declarator(e.target_type)}, {e.field})"
    if isinstance(e, IdentExpr):
        return e.name
    if isinstance(e, CastExpr):
        return f"(({format_c_declarator(e.target_type)})({emit_expr(e.operand)}))"
    if isinstance(e, SizeofExpr):
        if e.target_type is not None:
            return f"sizeof({format_c_declarator(e.target_type)})"
        return f"sizeof({emit_expr(e.operand)})"
    if isinstance(e, UnaryExpr):
        return f"({e.op}{emit_expr(e.operand)})"
    if isinstance(e, BinaryExpr):
        return f"({emit_expr(e.left)} {e.op} {emit_expr(e.right)})"
    if isinstance(e, TernaryExpr):
        return f"({emit_expr(e.cond)} ? {emit_expr(e.then_expr)} : {emit_expr(e.else_expr)})"
    if isinstance(e, CallExpr):
        return f"{emit_expr(e.callee)}({', '.join(emit_expr(a) for a in e.args)})"
    if isinstance(e, IndexExpr):
        if e.bound is not None:
            return f"{emit_expr(e.base)}[SIGIL_IDX({emit_expr(e.index)}, {e.bound})]"
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
    def __init__(self, tokens: List[Token], filename: str = "<input>",
                 defines: Optional[Dict[str, str]] = None):
        self.tokens = tokens
        self.pos = 0
        self.filename = filename
        self.user_types: Dict[str, str] = {}
        self.struct_fields: Dict[str, Dict[str, TypeNode]] = {}
        self.complete_structs: Set[str] = set()
        self.enum_constants: Dict[str, int] = {}
        self.macro_consts: Dict[str, int] = {}
        # 指针来源：名字 -> (基对象, 元素个数, 相对基对象的偏移)
        self.prov: Dict[str, Tuple[str, int, int]] = {}
        self.local_objects: Set[str] = set()
        self.param_names: Set[str] = set()
        self.scopes: List[Dict[str, TypeNode]] = [{}]
        self.func_sigs: Dict[str, Tuple[List[TypeNode], TypeNode]] = {}
        self.func_defined: Set[str] = set()
        self.func_variadic: Set[str] = set()
        self.struct_bitfields: Dict[str, Dict[str, int]] = {}
        self.func_labels: Set[str] = set()
        self.func_gotos: List[Tuple[str, Token]] = []
        self.current_func_ret: Optional[TypeNode] = None
        self.current_func_variadic: bool = False
        self.loop_depth: int = 0
        self.switch_depth: int = 0
        for d_name, d_value in (defines or {}).items():
            self._register_macro_constant(Token('PREPROC', f"#define {d_name} {d_value}", 1, 1, 0))

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
        while idx < len(self.tokens) and self.tokens[idx].kind in ('KW_PTR', 'KW_CONST', 'KW_VOLATILE'):
            idx += 1
        if idx >= len(self.tokens):
            return False
        t = self.tokens[idx]
        if t.kind == 'LPAREN' and idx + 1 < len(self.tokens) and self.tokens[idx + 1].kind in ('KW_PTR', 'KW_CONST', 'KW_VOLATILE', 'KW_FNPTR'):
            return self._is_type_start_at(idx + 1)
        return t.kind in ('TYPE_INT', 'TYPE_VOID', 'TYPE_BOOL', 'KW_FNPTR') or (
            t.kind == 'IDENT' and t.value in self.user_types
        )

    def _is_type_start(self, tok: Token) -> bool:
        return self._is_type_start_at(self.pos)

    # ------------------------------------------------------------------
    # a@(...) 属性：解析、参数形状校验、放置位置校验
    # ------------------------------------------------------------------
    def _attr_int_value(self, tok: Token, raw: str) -> int:
        s = raw.rstrip('uUlL')
        try:
            if s.startswith(('0x', '0X')):
                return int(s, 16)
            if s.startswith(('0b', '0B')):
                return int(s, 2)
            if s.startswith('0') and len(s) > 1 and s.isdigit():
                return int(s, 8)
            return int(s, 10)
        except ValueError:
            raise SemanticError(
                f"{self.filename}:{tok.line}:{tok.col}: Attribute argument '{raw}' is not an integer constant")

    def _validate_attribute(self, name_tok: Token, name: str, args: List[str]):
        if name not in ATTR_TARGETS:
            known = ', '.join(sorted(ATTR_TARGETS))
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: Unknown attribute '{name}'. "
                f"Supported attributes: {known}")
        if name in ATTR_NOARGS:
            if args:
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: Attribute '{name}' takes no arguments")
            return
        if name in ATTR_ONE_INT:
            if len(args) != 1:
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: Attribute '{name}' takes exactly 1 integer argument")
            value = self._attr_int_value(name_tok, args[0])
            if value <= 0 or (value & (value - 1)) != 0:
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: Attribute '{name}' requires a positive power-of-2 argument, got {value}")
            return
        if name in ATTR_ONE_STRING:
            if len(args) != 1 or not args[0].startswith('"'):
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: Attribute '{name}' takes exactly 1 string literal argument")
            return
        if name in ATTR_OPTIONAL_STRING:
            if len(args) > 1 or (args and not args[0].startswith('"')):
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: Attribute '{name}' takes an optional string literal argument")
            return
        if name in ATTR_INT_LIST:
            if not args:
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: Attribute '{name}' requires at least 1 integer argument")
            for arg in args:
                if self._attr_int_value(name_tok, arg) <= 0:
                    raise SemanticError(
                        f"{self.filename}:{name_tok.line}:{name_tok.col}: Attribute '{name}' argument indices are 1-based and positive")
            return

    def parse_attrs(self) -> List[Attribute]:
        """解析一个或多个 a@(...) 组，返回已校验参数形状的属性列表。"""
        attrs: List[Attribute] = []
        while self._cur().kind == 'KW_ATTR':
            at_tok = self._eat('KW_ATTR')
            self._eat('LPAREN')
            if self._cur().kind == 'RPAREN':
                raise ParseError(
                    f"{self.filename}:{at_tok.line}:{at_tok.col}: 'a@' requires at least one attribute name")
            while True:
                name_tok = self._eat('IDENT')
                args: List[str] = []
                if self._cur().kind == 'LPAREN':
                    self._eat('LPAREN')
                    if self._cur().kind == 'RPAREN':
                        raise ParseError(
                            f"{self.filename}:{name_tok.line}:{name_tok.col}: Empty argument list for attribute '{name_tok.value}'")
                    while True:
                        tok = self._cur()
                        if tok.kind in ('INT_NUM', 'FLOAT_NUM', 'STRING', 'CHAR', 'IDENT'):
                            args.append(tok.value)
                            self._eat()
                        else:
                            raise ParseError(
                                f"{self.filename}:{tok.line}:{tok.col}: Expected attribute argument, got '{tok.value}'")
                        if self._cur().kind == 'COMMA':
                            self._eat('COMMA')
                        else:
                            break
                    self._eat('RPAREN')
                self._validate_attribute(name_tok, name_tok.value, args)
                attrs.append(Attribute(name=name_tok.value, args=args))
                if self._cur().kind == 'COMMA':
                    self._eat('COMMA')
                else:
                    break
            self._eat('RPAREN')
        return attrs

    def _check_attr_placement(self, attrs: List[Attribute], place: str, tok: Token,
                              file_scope: bool = True):
        seen: Set[str] = set()
        for attr in attrs:
            if place not in ATTR_TARGETS[attr.name]:
                raise SemanticError(
                    f"{self.filename}:{tok.line}:{tok.col}: Attribute '{attr.name}' cannot be applied to this "
                    f"{place} declaration")
            if attr.name in seen:
                raise SemanticError(
                    f"{self.filename}:{tok.line}:{tok.col}: Duplicate attribute '{attr.name}'")
            if not file_scope and attr.name in ATTR_FILE_SCOPE_ONLY:
                raise SemanticError(
                    f"{self.filename}:{tok.line}:{tok.col}: Attribute '{attr.name}' is only valid at file scope")
            seen.add(attr.name)

    def _sizeof_takes_type(self) -> bool:
        """z? 后面接的是类型还是表达式。

        只有"确定是类型"的前缀才按类型解析：内置类型、指针/限定符前缀、已知用户类型。
        其余一律按表达式解析——这样 z? (p* src) 稳定读作"解引用后取大小"，
        而 z? p* u4 稳定读作"取指针类型大小"，避免 p* 既是类型前缀又是解引用运算符的歧义。
        """
        t = self._cur()
        if t.kind in ('TYPE_INT', 'TYPE_VOID', 'TYPE_BOOL', 'KW_FNPTR', 'KW_PTR', 'KW_CONST', 'KW_VOLATILE'):
            return True
        return t.kind == 'IDENT' and t.value in self.user_types

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
            if expr.name in self.enum_constants:
                return self.enum_constants[expr.name]
            return self.macro_consts.get(expr.name)
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
        if isinstance(expr, CompoundLiteral):
            return expr.target_type
        if isinstance(expr, VaArgExpr):
            return expr.target_type
        if isinstance(expr, OffsetofExpr):
            return BaseType(line=expr.line, col=expr.col, c_name='size_t')
        if isinstance(expr, (AggregateInit, DesignatedInit, DesignatedIndex)):
            raise SemanticError(
                f"{self.filename}:{expr.line}:{expr.col}: Aggregate initializer '{{ ... }}' is only allowed as a declaration initializer or a compound literal")
        if isinstance(expr, LiteralExpr):
            if expr.lit_kind == 'BOOL':
                return BaseType(line=expr.line, col=expr.col, c_name='bool')
            if expr.lit_kind == 'NULL':
                return PointerType(line=expr.line, col=expr.col,
                                   pointee=BaseType(line=expr.line, col=expr.col, c_name='void'))
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

        if isinstance(expr, SizeofExpr):
            # sizeof 的结果类型是 size_t（已内置为整型，可与其它整型互相赋值）
            return BaseType(line=expr.line, col=expr.col, c_name='size_t')

        if isinstance(expr, UnaryExpr):
            sub_t = self._infer_expr_type(expr.operand)
            if expr.op == '*':
                if isinstance(sub_t, PointerType):
                    if not self._is_complete_object_type(sub_t.pointee):
                        raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Cannot dereference pointer to incomplete or void type")
                    pv = self._prov_of(expr.operand)
                    if pv is not None:
                        b_name, b_len, b_off = pv
                        if b_off < 0 or b_off >= b_len:
                            raise SemanticError(
                                f"{self.filename}:{expr.line}:{expr.col}: Dereferencing a pointer into '{b_name}' at "
                                f"element {b_off}, outside {b_len} element(s)")
                    return sub_t.pointee
                if isinstance(sub_t, ArrayType):
                    return sub_t.element_type
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Cannot dereference non-pointer type")
            if expr.op == '&':
                if isinstance(expr.operand, MemberExpr) and self._member_is_bitfield(expr.operand):
                    raise SemanticError(
                        f"{self.filename}:{expr.line}:{expr.col}: Cannot take the address ('a&') of bit-field '{expr.operand.field}'")
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
                pv = self._prov_of(expr.base)
                if pv is not None:
                    b_name, b_len, b_off = pv
                    c_idx = self._try_const(expr.index)
                    if c_idx is not None:
                        pos = b_off + c_idx
                        if pos < 0 or pos >= b_len:
                            raise SemanticError(
                                f"{self.filename}:{expr.line}:{expr.col}: Index {c_idx} through a pointer into "
                                f"'{b_name}' reaches element {pos}, outside {b_len} element(s)")
                    elif 0 <= b_off < b_len:
                        expr.bound = b_len - b_off
                return base_t.pointee
            if isinstance(base_t, ArrayType):
                if base_t.size_val is not None:
                    c_idx = self._eval_const_int_expr(expr.index)
                    if c_idx is not None and (c_idx < 0 or c_idx >= base_t.size_val):
                        raise SemanticError(
                            f"{self.filename}:{expr.line}:{expr.col}: Index {c_idx} is out of bounds for an array of "
                            f"{base_t.size_val} element(s)")
                    # 常量下标已在转译期校验，只有运行期才知道的才包边界检查
                    if c_idx is None:
                        expr.bound = base_t.size_val
                return base_t.element_type
            raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Subscripted value is neither array nor pointer")

        if isinstance(expr, MemberExpr):
            base_t = self._infer_expr_type(expr.base)
            if expr.is_arrow:
                if not isinstance(base_t, PointerType) or not isinstance(base_t.pointee, BaseType):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: '->' applied to non-struct pointer")
                struct_name = base_t.pointee.c_name
                parent_is_const = base_t.pointee.is_const
                parent_is_volatile = base_t.pointee.is_volatile
            else:
                if not isinstance(base_t, BaseType):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: '.' applied to non-struct type")
                struct_name = base_t.c_name
                parent_is_const = base_t.is_const
                parent_is_volatile = base_t.is_volatile

            if struct_name not in self.struct_fields:
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Type '{struct_name}' has no member fields")
            f_map = self.struct_fields[struct_name]
            if expr.field not in f_map:
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: '{struct_name}' has no member named '{expr.field}'")
            ft = f_map[expr.field]
            if parent_is_const:
                ft = with_const(ft)
            if parent_is_volatile:
                ft = with_volatile(ft)
            return ft

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
                    if is_void_type(lt.pointee) or is_void_type(rt.pointee) or types_equal(strip_top_qualifiers(lt.pointee), strip_top_qualifiers(rt.pointee)):
                        return BaseType(line=expr.line, col=expr.col, c_name='bool')
                if isinstance(lt, FunctionPointerType) and isinstance(rt, FunctionPointerType) and types_equal(strip_top_qualifiers(lt), strip_top_qualifiers(rt)):
                    return BaseType(line=expr.line, col=expr.col, c_name='bool')
                if (isinstance(lt, (PointerType, FunctionPointerType)) and self._is_null_ptr_const(expr.right, rt)) or (
                    isinstance(rt, (PointerType, FunctionPointerType)) and self._is_null_ptr_const(expr.left, lt)
                ):
                    return BaseType(line=expr.line, col=expr.col, c_name='bool')
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Invalid operands to equality operator '{op}'")
            if op in ('<', '<=', '>', '>='):
                if self._is_numeric_type(lt) and self._is_numeric_type(rt):
                    return BaseType(line=expr.line, col=expr.col, c_name='bool')
                if isinstance(lt, PointerType) and isinstance(rt, PointerType) and not is_void_type(lt.pointee) and types_equal(strip_top_qualifiers(lt.pointee), strip_top_qualifiers(rt.pointee)):
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
                    if not self._is_complete_object_type(lt.pointee) or not types_equal(strip_top_qualifiers(lt.pointee), strip_top_qualifiers(rt.pointee)):
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
        区分单纯赋值 (m,) 与算术复合赋值 (m+ / m- / m* / m/) 的类型规则:
        - m, (=): 遵循 types_compatible_for_assign(lhs_t, rhs_t)
        - m* (*=), m/ (/=): 左右两侧必须均为算术数值类型 (严禁指针参与 *= 或 /=)
        - m+ (+=), m- (-=): 允许 (数值 += 数值) 或 (非void指针 += 整型偏移)，严禁 (指针 += 指针)!
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

    def _try_const(self, expr: ExprNode) -> Optional[int]:
        try:
            return self._eval_const_int_expr(expr)
        except SemanticError:
            return None

    def _prov_of(self, expr: Optional[ExprNode]) -> Optional[Tuple[str, int, int]]:
        """指针来源：(基对象, 元素个数, 相对基对象的偏移)。推不出来就返回 None。"""
        if expr is None:
            return None
        if isinstance(expr, IdentExpr):
            return self.prov.get(expr.name)
        if isinstance(expr, CastExpr):
            return None
        if isinstance(expr, UnaryExpr) and expr.op == '&':
            inner = expr.operand
            if isinstance(inner, IdentExpr):
                return self.prov.get(inner.name)
            if isinstance(inner, IndexExpr):
                base = self._prov_of(inner.base)
                idx = self._try_const(inner.index)
                if base is not None and idx is not None:
                    b, n, off = base
                    return (b, n, off + idx)
            return None
        if isinstance(expr, BinaryExpr) and expr.op in ('+', '-'):
            left = self._prov_of(expr.left)
            if left is not None:
                k = self._try_const(expr.right)
                if k is not None:
                    b, n, off = left
                    return (b, n, off + k if expr.op == '+' else off - k)
            if expr.op == '+':
                right = self._prov_of(expr.right)
                if right is not None:
                    k = self._try_const(expr.left)
                    if k is not None:
                        b, n, off = right
                        return (b, n, off + k)
        return None

    def _address_of_local(self, expr: Optional[ExprNode]) -> Optional[str]:
        if isinstance(expr, UnaryExpr) and expr.op == '&':
            inner = expr.operand
            if isinstance(inner, IdentExpr) and inner.name in self.local_objects:
                return inner.name
            if isinstance(inner, MemberExpr) and isinstance(inner.base, IdentExpr) \
                    and inner.base.name in self.local_objects:
                return inner.base.name
        return None

    def _note_prov(self, name: str, decl_type: TypeNode, init_expr: Optional[ExprNode]) -> None:
        if isinstance(decl_type, ArrayType) and decl_type.size_val is not None:
            self.prov[name] = (name, decl_type.size_val, 0)
            return
        if isinstance(strip_top_qualifiers(decl_type), PointerType):
            p = self._prov_of(init_expr)
            if p is not None:
                self.prov[name] = p
            else:
                self.prov.pop(name, None)

    def _member_is_bitfield(self, me: MemberExpr) -> bool:
        try:
            base_t = self._infer_expr_type(me.base)
        except SemanticError:
            return False
        if me.is_arrow:
            if not isinstance(base_t, PointerType) or not isinstance(base_t.pointee, BaseType):
                return False
            sname = base_t.pointee.c_name
        else:
            if not isinstance(base_t, BaseType):
                return False
            sname = base_t.c_name
        return me.field in self.struct_bitfields.get(sname, {})

    def _is_null_ptr_const(self, expr: ExprNode, expr_t: TypeNode) -> bool:
        if isinstance(expr, LiteralExpr) and expr.lit_kind == 'NULL':
            return True
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
        if isinstance(strip_top_qualifiers(expected), (PointerType, FunctionPointerType)) and self._is_null_ptr_const(rhs_expr, actual):
            return True
        return False

    def _check_scalar_cond(self, cond: ExprNode, kw_name: str):
        ct = self._infer_expr_type(cond)
        if not self._is_scalar_type(ct):
            raise SemanticError(f"{self.filename}:{cond.line}:{cond.col}: Controlling expression of '{kw_name}' must have scalar type")

    def _register_macro_constant(self, ptok: Token):
        """把 `#define NAME <字面量>` 里的名字登记成常量，使 `.sigil` 表达式可以直接用它。
        函数式宏与复杂宏体只透传到生成代码，不在此登记。"""
        m = re.match(r'#\s*define\s+([A-Za-z_]\w*)\s+(.+?)\s*$', ptok.value.strip())
        if not m:
            return
        name, body = m.group(1), m.group(2)
        body = body.split('/*')[0].split('//')[0].strip()
        if not body:
            return
        if name in self.scopes[0]:
            return
        ln, cl = ptok.line, ptok.col
        if body.startswith('"'):
            self.scopes[0][name] = PointerType(ln, cl, BaseType(ln, cl, 'char', is_const=True))
            return
        if body.startswith("'"):
            self.scopes[0][name] = BaseType(ln, cl, 'char')
            return
        raw = body.rstrip('uUlL')
        try:
            if body.startswith(('0x', '0X', '0b', '0B')):
                val = int(raw, 0)
            elif body.startswith('0') and len(body) > 1 and body.isdigit():
                val = int(body, 8)
            else:
                val = int(raw, 10)
            self.macro_consts[name] = val
            self.scopes[0][name] = BaseType(ln, cl, 'uint32_t' if body.lower().endswith('u') else 'int32_t')
            return
        except ValueError:
            pass
        try:
            float(body.rstrip('fFlL'))
            self.scopes[0][name] = BaseType(ln, cl, 'float' if body.lower().endswith('f') else 'double')
        except ValueError:
            pass

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
        if isinstance(expr, LiteralExpr) and expr.lit_kind in ('FLOAT_NUM', 'STRING', 'CHAR', 'BOOL', 'NULL'):
            return True
        if isinstance(expr, AggregateInit):
            return all(self._is_static_const_init(e) for e in expr.elements)
        if isinstance(expr, (DesignatedInit, DesignatedIndex)):
            return self._is_static_const_init(expr.value)
        if isinstance(expr, CompoundLiteral):
            return self._is_static_const_init(expr.init)
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
            if t.c_name == 'va_list':
                return True
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
            merged_volatile = is_volatile_qualified(p1) or is_volatile_qualified(p2)
            if types_equal(strip_top_qualifiers(p1), strip_top_qualifiers(p2)):
                pt = strip_top_qualifiers(p1)
                if merged_const:
                    pt = with_const(pt)
                if merged_volatile:
                    pt = with_volatile(pt)
                return PointerType(line=expr.line, col=expr.col, pointee=pt)
            if is_void_type(p1) or is_void_type(p2):
                v_base = BaseType(line=expr.line, col=expr.col, c_name='void', is_const=merged_const, is_volatile=merged_volatile)
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
            return strip_top_qualifiers(t_then)
        if isinstance(t_else, (PointerType, FunctionPointerType)) and then_zero:
            return strip_top_qualifiers(t_else)

        if types_equal(strip_top_qualifiers(t_then), strip_top_qualifiers(t_else)):
            if is_const_qualified(t_then) or is_const_qualified(t_else):
                result_t = with_const(strip_top_qualifiers(t_then))
            else:
                result_t = strip_top_qualifiers(t_then)
            if is_volatile_qualified(t_then) or is_volatile_qualified(t_else):
                result_t = with_volatile(result_t)
            return result_t

        raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Incompatible branch types in ternary conditional expression")

    def parse_type(self) -> TypeNode:
        tok = self._cur()
        is_const = False
        is_volatile = False
        is_restrict = False
        while self._cur().kind in ('KW_CONST', 'KW_VOLATILE', 'KW_RESTRICT'):
            qualifier_tok = self._eat()
            if qualifier_tok.kind == 'KW_CONST':
                is_const = True
            elif qualifier_tok.kind == 'KW_VOLATILE':
                is_volatile = True
            else:
                is_restrict = True
        tok = self._cur()

        if tok.kind == 'KW_PTR':
            ptr_tok = self._eat('KW_PTR')
            base_node: TypeNode = PointerType(line=ptr_tok.line, col=ptr_tok.col, pointee=self.parse_type(), is_const=is_const, is_volatile=is_volatile, is_restrict=is_restrict)
        elif tok.kind == 'KW_FNPTR':
            fn_tok = self._eat('KW_FNPTR')
            self._eat('LPAREN')
            params: List[Tuple[TypeNode, Optional[str]]] = []
            seen_pnames = set()
            is_variadic = False
            if self._cur().kind == 'TYPE_VOID' and self.tokens[self.pos + 1].kind == 'RPAREN':
                self._eat('TYPE_VOID')
            elif self._cur().kind != 'RPAREN':
                while True:
                    if self._cur().kind == 'ELLIPSIS':
                        if not params:
                            raise SemanticError(
                                f"{self.filename}:{self._cur().line}:{self._cur().col}: "
                                f"A variadic function pointer requires at least one named parameter before '...'")
                        self._eat('ELLIPSIS')
                        is_variadic = True
                        break
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
            base_node = FunctionPointerType(line=fn_tok.line, col=fn_tok.col, param_decls=params, return_type=ret_type, is_const=is_const, is_volatile=is_volatile, is_variadic=is_variadic)
        elif tok.kind in ('TYPE_INT', 'TYPE_VOID', 'TYPE_BOOL'):
            t_tok = self._eat()
            c_map = {**BASIC_TYPES, 'v.': 'void', 'b.': 'bool'}
            base_node = BaseType(line=t_tok.line, col=t_tok.col, c_name=c_map[t_tok.value], is_const=is_const, is_volatile=is_volatile)
        elif tok.kind == 'IDENT' and tok.value in self.user_types:
            t_tok = self._eat('IDENT')
            base_node = BaseType(line=t_tok.line, col=t_tok.col, c_name=t_tok.value, is_const=is_const, is_volatile=is_volatile)
        elif tok.kind == 'LPAREN':
            self._eat('LPAREN')
            base_node = self.parse_type()
            self._eat('RPAREN')
            if is_const:
                base_node = with_const(base_node)
            if is_volatile:
                base_node = with_volatile(base_node)
        else:
            raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: Expected type specifier, got '{tok.value}'")

        if is_restrict:
            if isinstance(base_node, PointerType):
                base_node = PointerType(line=base_node.line, col=base_node.col, pointee=base_node.pointee,
                                        is_const=base_node.is_const, is_volatile=base_node.is_volatile,
                                        is_restrict=True)
            else:
                raise SemanticError(
                    f"{self.filename}:{tok.line}:{tok.col}: 'r@' (restrict) can only qualify a pointer type")

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
            attrs: List[Attribute] = []
            if self._cur().kind == 'KW_ATTR':
                attrs = self.parse_attrs()
            if self._cur().kind == 'PREPROC':
                if attrs:
                    tok = self._cur()
                    raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: 'a@' attributes cannot precede a preprocessor directive")
                ptok = self._eat('PREPROC')
                self._register_c99_header_builtins(ptok)
                self._register_macro_constant(ptok)
                top_nodes.append(PreprocNode(line=ptok.line, col=ptok.col, text=ptok.value))
            elif self._cur().kind == 'KW_EXTERNAL':
                top_nodes.append(self.parse_external())
            elif self._cur().kind in ('KW_STRUCT', 'KW_UNION'):
                top_nodes.append(self.parse_struct_or_union(attrs=attrs))
            elif self._cur().kind == 'KW_ENUM':
                if attrs:
                    tok = self._cur()
                    raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'a@' attributes are not supported on 'e{{' enum definitions")
                top_nodes.append(self.parse_enum())
            elif self._cur().kind == 'KW_STATIC_ASSERT':
                top_nodes.append(self.parse_static_assert())
            elif self._cur().kind == 'KW_OBJECT':
                object_tok = self._eat('KW_OBJECT')
                top_nodes.append(self.parse_top_decl_or_func(object_marker=object_tok, attrs=attrs))
            elif self._cur().kind in ('KW_STATIC', 'KW_INLINE'):
                is_static = False
                is_inline = False
                while self._cur().kind in ('KW_STATIC', 'KW_INLINE'):
                    mod_tok = self._eat()
                    if mod_tok.kind == 'KW_STATIC':
                        if is_static:
                            raise ParseError(f"{self.filename}:{mod_tok.line}:{mod_tok.col}: Duplicate 's@' storage class")
                        is_static = True
                    else:
                        if is_inline:
                            raise ParseError(f"{self.filename}:{mod_tok.line}:{mod_tok.col}: Duplicate 'i@' specifier")
                        is_inline = True
                if self._cur().kind == 'KW_OBJECT':
                    if is_inline:
                        raise SemanticError(
                            f"{self.filename}:{self._cur().line}:{self._cur().col}: 'i@' (inline) cannot be applied to an object declaration")
                    object_tok = self._eat('KW_OBJECT')
                    top_nodes.append(self.parse_top_decl_or_func(object_marker=object_tok, is_static=is_static, attrs=attrs))
                elif self._is_type_start(self._cur()):
                    top_nodes.append(self.parse_top_decl_or_func(is_static=is_static, is_inline=is_inline, attrs=attrs))
                else:
                    tok = self._cur()
                    raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: 's@' / 'i@' must be followed by a function, got '{tok.value}'")
            elif self._is_type_start(self._cur()):
                top_nodes.append(self.parse_top_decl_or_func(attrs=attrs))
            else:
                tok = self._cur()
                raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: Unexpected top-level token '{tok.value}'")
        return top_nodes

    def _check_compound_init(self, target: TypeNode, init: AggregateInit, name_tok: Token):
        is_aggregate = isinstance(target, ArrayType) or (
            isinstance(target, BaseType) and self.user_types.get(target.c_name) in ('struct', 'union'))
        if is_aggregate:
            self._check_brace_init(target, init, name_tok)
            return
        if len(init.elements) != 1 or isinstance(init.elements[0], (DesignatedInit, DesignatedIndex, AggregateInit)):
            raise SemanticError(
                f"{self.filename}:{init.line}:{init.col}: A scalar compound literal takes exactly one plain value, "
                f"e.g. (u4){{ 5 }}")
        elem = init.elements[0]
        et = self._infer_expr_type(elem)
        if not self._check_assign_compatible(target, elem, et):
            raise SemanticError(
                f"{self.filename}:{elem.line}:{elem.col}: Incompatible compound literal value: "
                f"expected '{format_c_declarator(target)}', got '{format_c_declarator(et)}'")

    def _check_bitfield_base(self, tok: Token, ft: TypeNode):
        if not isinstance(ft, BaseType) or ft.c_name not in BITFIELD_WIDTH:
            raise SemanticError(
                f"{self.filename}:{tok.line}:{tok.col}: 'w!' bit-field requires an integer base type, "
                f"got '{format_c_declarator(ft)}'")

    def parse_external(self) -> ExternalTypeNode:
        """`x!` 外部类型：不生成定义，只登记字段供转译期检查。

        x! struct sockaddr_in { u2 sin_family; ... };   /* C 里写作 struct sockaddr_in */
        x! pthread_t;                                   /* typedef 型不透明句柄 */
        """
        kw = self._eat('KW_EXTERNAL')
        c_prefix = ''
        if self._cur().kind == 'IDENT' and self._cur().value in ('struct', 'union', 'enum'):
            c_prefix = self._eat('IDENT').value
        name_tok = self._eat('IDENT')
        sigil_name = name_tok.value
        c_spelling = f"{c_prefix} {sigil_name}" if c_prefix else sigil_name
        if sigil_name in self.user_types:
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: '{sigil_name}' is already declared")
        if self._cur().kind == 'SEMI':
            self._eat('SEMI')
            if c_prefix == 'enum':
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: an external enum needs its constants declared separately")
            self.user_types[sigil_name] = c_prefix or 'struct'
            EXTERNAL_C_SPELLING[sigil_name] = c_spelling
            return ExternalTypeNode(line=kw.line, col=kw.col, name=sigil_name,
                                    c_spelling=c_spelling, opaque=True)
        if c_prefix == 'enum':
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: external enums cannot carry a field list")
        self._eat('LBRACE')
        fields: Dict[str, TypeNode] = {}
        count = 0
        while self._cur().kind != 'RBRACE':
            ft = self.parse_type()
            fname_tok = self._eat('IDENT')
            if self._cur().kind == 'KW_BITFIELD':
                bf_tok = self._eat('KW_BITFIELD')
                w_tok = self._eat('INT_NUM')
                width = self._attr_int_value(w_tok, w_tok.value)
                self._check_bitfield_base(bf_tok, ft)
                limit = BITFIELD_WIDTH[ft.c_name]
                if width < 1 or width > limit:
                    raise SemanticError(
                        f"{self.filename}:{bf_tok.line}:{bf_tok.col}: 'w!{width}' out of range for '{ft.c_name}': "
                        f"width must be 1..{limit}")
                self.struct_bitfields.setdefault(sigil_name, {})[fname_tok.value] = width
            self._validate_non_void_var(ft, fname_tok)
            if not self._is_complete_object_type(ft):
                raise SemanticError(
                    f"{self.filename}:{fname_tok.line}:{fname_tok.col}: Field '{fname_tok.value}' has incomplete type")
            if fname_tok.value in fields:
                raise SemanticError(
                    f"{self.filename}:{fname_tok.line}:{fname_tok.col}: Duplicate field '{fname_tok.value}' "
                    f"in external type '{sigil_name}'")
            fields[fname_tok.value] = ft
            self._eat('SEMI')
            count += 1
        if count == 0:
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: empty external type; write 'x! {sigil_name};' for an opaque handle")
        self._eat('RBRACE')
        self._eat('SEMI')
        self.user_types[sigil_name] = c_prefix or 'struct'
        self.struct_fields[sigil_name] = fields
        self.complete_structs.add(sigil_name)
        EXTERNAL_C_SPELLING[sigil_name] = c_spelling
        return ExternalTypeNode(line=kw.line, col=kw.col, name=sigil_name,
                                c_spelling=c_spelling, opaque=False, field_count=count)

    def parse_struct_or_union(self, attrs: Optional[List[Attribute]] = None) -> StructDefNode:
        attrs = attrs or []
        kw_tok = self._eat()
        kind = "struct" if kw_tok.kind == 'KW_STRUCT' else "union"
        name_tok = self._eat('IDENT')
        self._check_attr_placement(attrs, 'type', name_tok)
        if name_tok.value in self.user_types and self.user_types[name_tok.value] != kind:
            raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: '{name_tok.value}' defined as wrong kind of tag")
        tag_already_declared = name_tok.value in self.user_types

        if self._cur().kind == 'SEMI':
            if attrs:
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: 'a@' attributes require a {kind} definition, "
                    f"not a forward declaration of '{name_tok.value}'")
            self._eat('SEMI')
            if not tag_already_declared:
                self.user_types[name_tok.value] = kind
            return StructDefNode(line=kw_tok.line, col=kw_tok.col, kind=kind, name=name_tok.value,
                                alignment=None, fields=[], emit_typedef=not tag_already_declared, attrs=attrs)

        if name_tok.value in self.complete_structs:
            raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Redefinition of type '{name_tok.value}'")
        self.user_types[name_tok.value] = kind

        alignment = None
        if self._cur().kind == 'KW_ALIGN':
            align_tok = self._eat('KW_ALIGN')
            alignment = int(align_tok.value)
            if alignment <= 0 or (alignment & (alignment - 1)) != 0:
                raise SemanticError(f"{self.filename}:{align_tok.line}:{align_tok.col}: Alignment '{alignment}' must be a power of 2")

        if alignment is not None and any(a.name in ('packed', 'aligned') for a in attrs):
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: 'a!{alignment}' cannot be combined with "
                f"'a@(packed/aligned(...))' on the same type; use one alignment mechanism")

        self._eat('LBRACE')
        fields: List[VarDeclStmt] = []
        field_map: Dict[str, TypeNode] = {}
        while self._cur().kind != 'RBRACE':
            field_attrs: List[Attribute] = []
            if self._cur().kind == 'KW_ATTR':
                field_attrs = self.parse_attrs()
            ft = self.parse_type()
            bit_width = None
            if self._cur().kind == 'KW_BITFIELD':
                # 匿名零宽位域：`Type w! 0;` -> `Type : 0;`，强制下一个字段对齐
                bf_tok = self._eat('KW_BITFIELD')
                w_tok = self._eat('INT_NUM')
                width = self._attr_int_value(w_tok, w_tok.value)
                self._check_bitfield_base(bf_tok, ft)
                if width != 0:
                    raise SemanticError(
                        f"{self.filename}:{bf_tok.line}:{bf_tok.col}: An unnamed bit-field must be zero-width padding "
                        f"('{format_c_declarator(ft)} w! 0;'); give it a name for a real bit-field")
                if field_attrs:
                    raise SemanticError(
                        f"{self.filename}:{bf_tok.line}:{bf_tok.col}: Padding bit-field cannot carry 'a@' attributes")
                self._eat('SEMI')
                fields.append(VarDeclStmt(line=bf_tok.line, col=bf_tok.col, var_type=ft,
                                          name='', attrs=[], bit_width=0))
                continue
            fname_tok = self._eat('IDENT')
            if self._cur().kind == 'KW_BITFIELD':
                bf_tok = self._eat('KW_BITFIELD')
                w_tok = self._eat('INT_NUM')
                width = self._attr_int_value(w_tok, w_tok.value)
                self._check_bitfield_base(bf_tok, ft)
                limit = BITFIELD_WIDTH[ft.c_name]
                if width < 1 or width > limit:
                    raise SemanticError(
                        f"{self.filename}:{bf_tok.line}:{bf_tok.col}: 'w!{width}' out of range for '{ft.c_name}': "
                        f"width must be 1..{limit}")
                bit_width = width
            self._check_attr_placement(field_attrs, 'field', fname_tok)
            self._validate_non_void_var(ft, fname_tok)
            if not self._is_complete_object_type(ft):
                raise SemanticError(f"{self.filename}:{fname_tok.line}:{fname_tok.col}: Field '{fname_tok.value}' has incomplete type")
            if fname_tok.value in field_map:
                raise SemanticError(f"{self.filename}:{fname_tok.line}:{fname_tok.col}: Duplicate field '{fname_tok.value}' in {kind} '{name_tok.value}'")
            field_map[fname_tok.value] = ft
            if bit_width is not None:
                self.struct_bitfields.setdefault(name_tok.value, {})[fname_tok.value] = bit_width
            self._eat('SEMI')
            fields.append(VarDeclStmt(line=fname_tok.line, col=fname_tok.col, var_type=ft,
                                      name=fname_tok.value, attrs=field_attrs, bit_width=bit_width))
        if not fields:
            raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Empty {kind} '{name_tok.value}' is forbidden in ISO C99")
        self._eat('RBRACE')
        self._eat('SEMI')
        self.struct_fields[name_tok.value] = field_map
        self.complete_structs.add(name_tok.value)
        return StructDefNode(line=kw_tok.line, col=kw_tok.col, kind=kind, name=name_tok.value,
                            alignment=alignment, fields=fields, emit_typedef=not tag_already_declared,
                            attrs=attrs)

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

    def _parse_object_decl_after_name(self, decl_type: TypeNode, name_tok: Token,
                                      global_scope: bool = False, consume_semi: bool = True,
                                      is_static: bool = False,
                                      attrs: Optional[List[Attribute]] = None) -> VarDeclStmt:
        attrs = attrs or []
        self._validate_non_void_var(decl_type, name_tok)
        self._register_symbol(name_tok.value, decl_type, name_tok)
        init_expr = None
        if self._cur().kind == 'OP_ASSIGN':
            op_tok = self._eat('OP_ASSIGN')
            if self._cur().kind == 'LBRACE':
                init_expr = self.parse_brace_init()
                self._check_brace_init(decl_type, init_expr, name_tok)
            else:
                init_expr = self.parse_pure_expr()
                actual_t = self._infer_expr_type(init_expr)
                if not self._check_assign_compatible(decl_type, init_expr, actual_t):
                    raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Incompatible initializer type for '{name_tok.value}'")
            if global_scope and not self._is_static_const_init(init_expr):
                raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Global initializer for '{name_tok.value}' is not a compile-time constant")
        if consume_semi:
            self._eat('SEMI')
        if not global_scope:
            self.local_objects.add(name_tok.value)
        self._note_prov(name_tok.value, decl_type, init_expr)
        return VarDeclStmt(line=name_tok.line, col=name_tok.col, var_type=decl_type,
                           name=name_tok.value, init_expr=init_expr, is_static=is_static, attrs=attrs)

    def parse_brace_init(self) -> AggregateInit:
        """解析 `{ e1, e2, ... }`，允许嵌套与 C99 尾随逗号。"""
        lb = self._eat('LBRACE')
        if self._cur().kind == 'RBRACE':
            raise SemanticError(f"{self.filename}:{lb.line}:{lb.col}: Empty initializer list '{{ }}' is forbidden in ISO C99")
        elements: List[ExprNode] = []
        while True:
            if self._cur().kind == 'LBRACE':
                elements.append(self.parse_brace_init())
            elif (self._cur().kind == 'DOT' and self.tokens[self.pos + 1].kind == 'IDENT'
                  and self.tokens[self.pos + 2].kind == 'OP_ASSIGN'):
                dot_tok = self._eat('DOT')
                fld_tok = self._eat('IDENT')
                self._eat('OP_ASSIGN')
                if self._cur().kind == 'LBRACE':
                    val = self.parse_brace_init()
                else:
                    val = self.parse_pure_expr()
                elements.append(DesignatedInit(line=dot_tok.line, col=dot_tok.col,
                                               field=fld_tok.value, value=val))
            elif self._cur().kind == 'LBRACK':
                lb_tok = self._eat('LBRACK')
                idx_e = self.parse_pure_expr()
                idx_v = self._eval_const_int_expr(idx_e)
                if idx_v is None or idx_v < 0:
                    raise SemanticError(
                        f"{self.filename}:{lb_tok.line}:{lb_tok.col}: Array designator must be a non-negative integer constant")
                self._eat('RBRACK')
                self._eat('OP_ASSIGN')
                if self._cur().kind == 'LBRACE':
                    val = self.parse_brace_init()
                else:
                    val = self.parse_pure_expr()
                elements.append(DesignatedIndex(line=lb_tok.line, col=lb_tok.col,
                                                index_expr=idx_e, index_val=idx_v, value=val))
            else:
                elements.append(self.parse_pure_expr())
            if self._cur().kind == 'COMMA':
                self._eat('COMMA')
                if self._cur().kind == 'RBRACE':
                    break
            else:
                break
        self._eat('RBRACE')
        return AggregateInit(line=lb.line, col=lb.col, elements=elements)

    def _check_brace_init(self, target: TypeNode, init: AggregateInit, name_tok: Token):
        if isinstance(target, ArrayType):
            if any(isinstance(e, DesignatedInit) for e in init.elements):
                raise SemanticError(
                    f"{self.filename}:{init.line}:{init.col}: Struct designators '.field m,' cannot initialize an array")
            if any(isinstance(e, DesignatedIndex) for e in init.elements):
                seen_idx: Set[int] = set()
                for elem in init.elements:
                    if not isinstance(elem, DesignatedIndex):
                        raise SemanticError(
                            f"{self.filename}:{elem.line}:{elem.col}: Cannot mix designated '[index] m,' and positional "
                            f"initializers in one list")
                    if elem.index_val >= target.size_val:
                        raise SemanticError(
                            f"{self.filename}:{elem.line}:{elem.col}: Array designator [{elem.index_val}] out of range "
                            f"(size is {target.size_val})")
                    if elem.index_val in seen_idx:
                        raise SemanticError(
                            f"{self.filename}:{elem.line}:{elem.col}: Duplicate array designator [{elem.index_val}]")
                    seen_idx.add(elem.index_val)
                    self._check_init_element(target.element_type, elem.value, name_tok)
                return
            if len(init.elements) > target.size_val:
                raise SemanticError(
                    f"{self.filename}:{init.line}:{init.col}: Too many initializers for '{name_tok.value}': "
                    f"{len(init.elements)} given, array holds {target.size_val}")
            for elem in init.elements:
                self._check_init_element(target.element_type, elem, name_tok)
            return
        if isinstance(target, BaseType) and self.user_types.get(target.c_name) in ('struct', 'union'):
            kind = self.user_types[target.c_name]
            if target.c_name not in self.struct_fields:
                raise SemanticError(
                    f"{self.filename}:{init.line}:{init.col}: '{name_tok.value}' has incomplete type and cannot be initialized")
            fmap = self.struct_fields[target.c_name]
            if any(isinstance(e, DesignatedIndex) for e in init.elements):
                raise SemanticError(
                    f"{self.filename}:{init.line}:{init.col}: Array designators '[index] m,' cannot initialize a {kind}; use '.field m,'")
            if any(isinstance(e, DesignatedInit) for e in init.elements):
                seen: Set[str] = set()
                for elem in init.elements:
                    if not isinstance(elem, DesignatedInit):
                        raise SemanticError(
                            f"{self.filename}:{elem.line}:{elem.col}: Cannot mix designated '.field m,' and positional "
                            f"initializers in one list")
                    if elem.field not in fmap:
                        raise SemanticError(
                            f"{self.filename}:{elem.line}:{elem.col}: '{target.c_name}' has no member named '{elem.field}'")
                    if elem.field in seen:
                        raise SemanticError(
                            f"{self.filename}:{elem.line}:{elem.col}: Duplicate designated initializer for '{elem.field}'")
                    seen.add(elem.field)
                    self._check_init_element(fmap[elem.field], elem.value, name_tok)
                return
            fields = list(fmap.items())
            if kind == 'union':
                if len(init.elements) != 1:
                    raise SemanticError(
                        f"{self.filename}:{init.line}:{init.col}: Union '{target.c_name}' initializer takes exactly 1 element, "
                        f"got {len(init.elements)}")
            elif len(init.elements) > len(fields):
                raise SemanticError(
                    f"{self.filename}:{init.line}:{init.col}: Too many initializers for '{name_tok.value}': "
                    f"{len(init.elements)} given, {kind} has {len(fields)} fields")
            for (fname, ftype), elem in zip(fields, init.elements):
                self._check_init_element(ftype, elem, name_tok)
            return
        raise SemanticError(
            f"{self.filename}:{init.line}:{init.col}: Aggregate initializer requires an array, struct or union type, "
            f"but '{name_tok.value}' has type '{format_c_declarator(target)}'")

    def _check_init_element(self, target: TypeNode, elem: ExprNode, name_tok: Token):
        if isinstance(elem, AggregateInit):
            self._check_brace_init(target, elem, name_tok)
            return
        et = self._infer_expr_type(elem)
        if not self._check_assign_compatible(target, elem, et):
            raise SemanticError(
                f"{self.filename}:{elem.line}:{elem.col}: Incompatible initializer element for '{name_tok.value}': "
                f"expected '{format_c_declarator(target)}', got '{format_c_declarator(et)}'")

    def parse_top_decl_or_func(self, object_marker: Optional[Token] = None, is_static: bool = False,
                               attrs: Optional[List[Attribute]] = None,
                               is_inline: bool = False) -> StmtNode:
        attrs = attrs or []
        decl_type = self.parse_type()
        name_tok = self._eat('IDENT')

        if self._cur().kind == 'LPAREN':
            self._check_attr_placement(attrs, 'function', name_tok)
            if object_marker is not None:
                raise ParseError(f"{self.filename}:{object_marker.line}:{object_marker.col}: 'o!' introduces an object declaration, not a function")
            if isinstance(decl_type, ArrayType):
                raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Function '{name_tok.value}' cannot return array type")
            self._eat('LPAREN')
            params: List[Tuple[TypeNode, str]] = []
            seen_params = set()
            is_variadic = False
            if self._cur().kind == 'TYPE_VOID' and self.tokens[self.pos + 1].kind == 'RPAREN':
                self._eat('TYPE_VOID')
            elif self._cur().kind != 'RPAREN':
                while True:
                    if self._cur().kind == 'ELLIPSIS':
                        if not params:
                            raise SemanticError(
                                f"{self.filename}:{self._cur().line}:{self._cur().col}: "
                                f"A variadic function requires at least one named parameter before '...'")
                        self._eat('ELLIPSIS')
                        is_variadic = True
                        break
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
                if len(old_params) != len(param_types) or not types_equal(strip_top_qualifiers(old_ret), strip_top_qualifiers(decl_type)) or not all(types_equal(strip_top_qualifiers(a), strip_top_qualifiers(b)) for a, b in zip(old_params, param_types)):
                    raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Conflicting types for function '{name_tok.value}'")

            fn_ptr_equiv = FunctionPointerType(line=name_tok.line, col=name_tok.col, param_decls=[(pt, pn) for pt, pn in params], return_type=decl_type, is_variadic=is_variadic)
            self.scopes[0][name_tok.value] = fn_ptr_equiv
            self.func_sigs[name_tok.value] = (param_types, decl_type)
            if is_variadic:
                self.func_variadic.add(name_tok.value)

            if self._cur().kind == 'SEMI':
                self._eat('SEMI')
                return FuncDefNode(line=name_tok.line, col=name_tok.col, return_type=decl_type, name=name_tok.value, params=params, body=None, is_static=is_static, attrs=attrs, is_inline=is_inline, is_variadic=is_variadic)

            if any(not pname for _, pname in params):
                raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Function definition parameters must have names")
            if name_tok.value in self.func_defined:
                raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Redefinition of function '{name_tok.value}'")
            self.func_defined.add(name_tok.value)

            prev_ret = self.current_func_ret
            prev_variadic = self.current_func_variadic
            prev_labels = self.func_labels
            prev_gotos = self.func_gotos
            prev_prov = self.prov
            prev_locals = self.local_objects
            prev_params = self.param_names
            self.current_func_ret = decl_type
            self.current_func_variadic = is_variadic
            self.func_labels = set()
            self.func_gotos = []
            # 只保留文件作用域对象的来源，清掉上一个函数的局部
            self.prov = {k: v for k, v in prev_prov.items() if k in self.scopes[0]}
            self.local_objects = set()
            self.param_names = set()
            self.scopes.append({pname: pt for pt, pname in params})
            for _pt, pname in params:
                self.local_objects.add(pname)
                self.param_names.add(pname)
            body = self.parse_block(create_new_scope=False)
            self.scopes.pop()
            self.current_func_ret = prev_ret
            self.current_func_variadic = prev_variadic
            self.prov = prev_prov
            self.local_objects = prev_locals
            self.param_names = prev_params
            for (lname, ltok) in self.func_gotos:
                if lname not in self.func_labels:
                    raise SemanticError(
                        f"{self.filename}:{ltok.line}:{ltok.col}: 'g!' target '{lname}' has no matching 'l!' label "
                        f"in function '{name_tok.value}'")
            self.func_labels = prev_labels
            self.func_gotos = prev_gotos
            if not is_void_type(decl_type) and name_tok.value != 'main' and self._can_fall_through(body):
                raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Control reaches end of non-void function '{name_tok.value}' without returning a value")
            return FuncDefNode(line=name_tok.line, col=name_tok.col, return_type=decl_type, name=name_tok.value, params=params, body=body, is_static=is_static, attrs=attrs, is_inline=is_inline, is_variadic=is_variadic)

        if object_marker is None:
            raise ParseError(f"{self.filename}:{name_tok.line}:{name_tok.col}: File-scope object declarations must begin with 'o!'")
        self._check_attr_placement(attrs, 'object', name_tok, file_scope=True)
        return self._parse_object_decl_after_name(decl_type, name_tok, global_scope=True, is_static=is_static, attrs=attrs)

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
                if self._cur().kind == 'KW_OBJECT':
                    self._eat('KW_OBJECT')
                    vt = self.parse_type()
                    vname = self._eat('IDENT')
                    init_stmt = self._parse_object_decl_after_name(vt, vname, consume_semi=False)
                elif self._is_type_start(self._cur()):
                    decl_tok = self._cur()
                    raise ParseError(f"{self.filename}:{decl_tok.line}:{decl_tok.col}: Object declarations in a 'f~' initializer must begin with 'o!'")
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
            bad = self._address_of_local(expr)
            if bad is not None:
                raise SemanticError(
                    f"{self.filename}:{tok.line}:{tok.col}: Returning the address of local object '{bad}' would dangle "
                    f"after return")
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

        if tok.kind == 'KW_DO':
            self._eat('KW_DO')
            self.loop_depth += 1
            body = self.parse_block()
            self.loop_depth -= 1
            self._eat('KW_WHILE')
            self._eat('LPAREN')
            cond = self.parse_pure_expr()
            self._check_scalar_cond(cond, 'd~')
            self._eat('RPAREN')
            self._eat('SEMI')
            return DoWhileStmt(line=tok.line, col=tok.col, body=body, cond=cond)

        if tok.kind == 'KW_STATIC_ASSERT':
            return self.parse_static_assert()

        if tok.kind == 'KW_GOTO':
            self._eat('KW_GOTO')
            ltok = self._eat('IDENT')
            self._eat('SEMI')
            self.func_gotos.append((ltok.value, ltok))
            return GotoStmt(line=tok.line, col=tok.col, label=ltok.value)

        if tok.kind == 'KW_LABEL':
            self._eat('KW_LABEL')
            ltok = self._eat('IDENT')
            self._eat('SEMI')
            if ltok.value in self.func_labels:
                raise SemanticError(f"{self.filename}:{ltok.line}:{ltok.col}: Duplicate label '{ltok.value}' in this function")
            self.func_labels.add(ltok.value)
            return LabelStmt(line=tok.line, col=tok.col, name=ltok.value)

        if tok.kind == 'IDENT' and tok.value in ('va_start', 'va_end', 'va_copy') and self.tokens[self.pos + 1].kind == 'LPAREN':
            return self.parse_va_stmt()

        if tok.kind == 'KW_ATTR':
            attrs = self.parse_attrs()
            if self._cur().kind != 'KW_OBJECT':
                nxt = self._cur()
                raise ParseError(
                    f"{self.filename}:{nxt.line}:{nxt.col}: Block-scope 'a@' attributes must be followed by 'o!'")
            self._eat('KW_OBJECT')
            vt = self.parse_type()
            vname = self._eat('IDENT')
            self._check_attr_placement(attrs, 'object', vname, file_scope=False)
            return self._parse_object_decl_after_name(vt, vname, attrs=attrs)

        if tok.kind == 'KW_OBJECT':
            self._eat('KW_OBJECT')
            vt = self.parse_type()
            vname = self._eat('IDENT')
            return self._parse_object_decl_after_name(vt, vname)

        if self._is_type_start(tok):
            raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: Object declarations must begin with 'o!'")

        stmt = self.parse_assign_or_expr_no_semi()
        self._eat('SEMI')
        return stmt

    def parse_static_assert(self) -> StaticAssertStmt:
        tok = self._eat('KW_STATIC_ASSERT')
        self._eat('LPAREN')
        cond = self.parse_pure_expr()
        # 条件交给后端 C 编译器判定：sizeof 等本身就是整型常量表达式，
        # 在这里折叠会把 ABI 尺寸假设写死进转译器。
        self._eat('COMMA')
        msg = self._eat('STRING')
        self._eat('RPAREN')
        self._eat('SEMI')
        return StaticAssertStmt(line=tok.line, col=tok.col, cond=cond, message=msg.value)

    def parse_va_stmt(self) -> VaStmt:
        name_tok = self._eat('IDENT')
        self._eat('LPAREN')
        ap = self.parse_pure_expr()
        ap_t = self._infer_expr_type(ap)
        if not (isinstance(ap_t, BaseType) and ap_t.c_name == 'va_list'):
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: '{name_tok.value}' requires a 'va_list' object")
        if name_tok.value == 'va_start':
            if not self.current_func_variadic:
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: 'va_start' is only allowed inside a variadic function")
            self._eat('COMMA')
            last_tok = self._eat('IDENT')
            self._eat('RPAREN')
            self._eat('SEMI')
            return VaStmt(line=name_tok.line, col=name_tok.col, kind='start', ap=ap, last_name=last_tok.value)
        if name_tok.value == 'va_copy':
            self._eat('COMMA')
            src = self.parse_pure_expr()
            src_t = self._infer_expr_type(src)
            if not (isinstance(src_t, BaseType) and src_t.c_name == 'va_list'):
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: 'va_copy' source must be a 'va_list' object")
            self._eat('RPAREN')
            self._eat('SEMI')
            return VaStmt(line=name_tok.line, col=name_tok.col, kind='copy', ap=ap, ap2=src)
        self._eat('RPAREN')
        self._eat('SEMI')
        return VaStmt(line=name_tok.line, col=name_tok.col, kind='end', ap=ap)

    def parse_va_arg(self) -> VaArgExpr:
        name_tok = self._eat('IDENT')
        self._eat('LPAREN')
        ap = self.parse_pure_expr()
        ap_t = self._infer_expr_type(ap)
        if not (isinstance(ap_t, BaseType) and ap_t.c_name == 'va_list'):
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: 'va_arg' requires a 'va_list' object")
        self._eat('COMMA')
        target_t = self.parse_type()
        self._eat('RPAREN')
        if is_void_type(target_t) or not self._is_complete_object_type(target_t):
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: 'va_arg' type must be a complete object type")
        return VaArgExpr(line=name_tok.line, col=name_tok.col, ap=ap, target_type=target_t)

    def parse_offsetof(self) -> OffsetofExpr:
        name_tok = self._eat('IDENT')
        self._eat('LPAREN')
        target_t = self.parse_type()
        self._eat('COMMA')
        fld_tok = self._eat('IDENT')
        self._eat('RPAREN')
        if not (isinstance(target_t, BaseType)
                and self.user_types.get(target_t.c_name) in ('struct', 'union')
                and target_t.c_name in self.struct_fields):
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: 'offsetof' requires a complete struct/union type, "
                f"got '{format_c_declarator(target_t)}'")
        if fld_tok.value not in self.struct_fields[target_t.c_name]:
            raise SemanticError(
                f"{self.filename}:{fld_tok.line}:{fld_tok.col}: '{target_t.c_name}' has no member named '{fld_tok.value}'")
        return OffsetofExpr(line=name_tok.line, col=name_tok.col, target_type=target_t, field=fld_tok.value)

    def parse_generic(self) -> ExprNode:
        """`g? expr { T: e; ...; d: e }` —— 按控制表达式的静态类型选一条分支，转译期解析掉。"""
        g_tok = self._eat('KW_GENERIC')
        ctl = self.parse_unary()
        ctl_t = strip_top_qualifiers(self._infer_expr_type(ctl))
        self._eat('LBRACE')
        assocs: List[Tuple[Optional[TypeNode], ExprNode]] = []
        seen: Set[str] = set()
        has_default = False
        while self._cur().kind != 'RBRACE':
            if self._cur().kind == 'KW_DEFAULT':
                self._eat('KW_DEFAULT')      # `d:` 已经把冒号一起吃了
                if has_default:
                    raise SemanticError(f"{self.filename}:{g_tok.line}:{g_tok.col}: 'g?' allows at most one 'd:' association")
                has_default = True
                t = None
            else:
                t = self.parse_type()
                key = format_c_declarator(strip_top_qualifiers(t))
                if key in seen:
                    raise SemanticError(f"{self.filename}:{g_tok.line}:{g_tok.col}: Duplicate 'g?' association for type '{key}'")
                seen.add(key)
                self._eat('COLON')
            expr = self.parse_pure_expr()
            assocs.append((t, expr))
            if self._cur().kind == 'SEMI':
                self._eat('SEMI')
            elif self._cur().kind != 'RBRACE':
                bad = self._cur()
                raise ParseError(
                    f"{self.filename}:{bad.line}:{bad.col}: Expected ';' or '}}' after a 'g?' association, got '{bad.value}'")
        self._eat('RBRACE')
        if not assocs:
            raise SemanticError(f"{self.filename}:{g_tok.line}:{g_tok.col}: 'g?' requires at least one association")
        for t, expr in assocs:
            if t is not None and types_equal(strip_top_qualifiers(t), ctl_t):
                self._infer_expr_type(expr)
                return expr
        for t, expr in assocs:
            if t is None:
                self._infer_expr_type(expr)
                return expr
        raise SemanticError(
            f"{self.filename}:{g_tok.line}:{g_tok.col}: 'g?' has no association for '{format_c_declarator(ctl_t)}' and no 'd:' default")

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
                bad = self._address_of_local(rhs)
                if bad is not None and isinstance(lhs, IdentExpr):
                    escaping = lhs.name in self.param_names or (
                        lhs.name in self.scopes[0] and lhs.name not in self.local_objects)
                    if escaping:
                        raise SemanticError(
                            f"{self.filename}:{op_tok.line}:{op_tok.col}: Storing the address of local object "
                            f"'{bad}' into '{lhs.name}' would dangle after this function returns")
                if isinstance(lhs, IdentExpr):
                    self._note_prov(lhs.name, lhs_t, rhs)
            else:
                self._check_compound_assign_types(op_tok.kind, lhs_t, rhs_t, op_tok)
                if isinstance(lhs, IdentExpr) and op_tok.kind in ('OP_ADD_ASSIGN', 'OP_SUB_ASSIGN'):
                    pv = self.prov.get(lhs.name)
                    k = self._try_const(rhs)
                    if pv is not None:
                        if k is not None:
                            b_name, b_len, b_off = pv
                            self.prov[lhs.name] = (b_name, b_len,
                                                   b_off + k if op_tok.kind == 'OP_ADD_ASSIGN' else b_off - k)
                        else:
                            self.prov.pop(lhs.name, None)
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
        # z? 取类型或表达式的大小，结果为 size_t
        if tok.kind == 'KW_SIZEOF':
            self._eat('KW_SIZEOF')
            if self._sizeof_takes_type():
                target_t = self.parse_type()
                if is_void_type(target_t):
                    raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'z?' cannot be applied to 'v.' (void)")
                if not self._is_complete_object_type(target_t):
                    raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'z?' requires a complete object type")
                return SizeofExpr(line=tok.line, col=tok.col, target_type=target_t, operand=None)
            operand = self.parse_unary()
            if is_void_type(self._infer_expr_type(operand)):
                raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'z?' cannot be applied to 'v.' (void)")
            return SizeofExpr(line=tok.line, col=tok.col, target_type=None, operand=operand)

        # g? 按静态类型选分支（转译期解析，生成 C99 里只有被选中的那条）
        if tok.kind == 'KW_GENERIC':
            return self.parse_generic()

        # 支持显式类型转换表达式 (Type)expr，以及复合字面量 (Type){ ... }
        if tok.kind == 'LPAREN' and self._is_type_start_at(self.pos + 1):
            self._eat('LPAREN')
            target_t = self.parse_type()
            self._eat('RPAREN')
            if self._cur().kind == 'LBRACE':
                init = self.parse_brace_init()
                fake_tok = Token('IDENT', 'compound literal', tok.line, tok.col, 0)
                self._check_compound_init(target_t, init, fake_tok)
                return self.parse_postfix_tail(
                    CompoundLiteral(line=tok.line, col=tok.col, target_type=target_t, init=init))
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
        return self.parse_postfix_tail(self.parse_primary())

    def parse_postfix_tail(self, node: ExprNode) -> ExprNode:
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
        if tok.kind in ('BOOL_LIT', 'NULL_LIT'):
            self._eat()
            return LiteralExpr(line=tok.line, col=tok.col, code=tok.value,
                               lit_kind='BOOL' if tok.kind == 'BOOL_LIT' else 'NULL')
        if tok.kind == 'IDENT' and tok.value == 'va_arg' and self.tokens[self.pos + 1].kind == 'LPAREN':
            return self.parse_va_arg()
        if tok.kind == 'IDENT' and tok.value == 'offsetof' and self.tokens[self.pos + 1].kind == 'LPAREN':
            return self.parse_offsetof()
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

C99_HEADER_BODY = """#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdarg.h>
#include <stdlib.h>

#ifdef SIGIL_BOUNDS_CHECK
  #ifndef SIGIL_BOUNDS_HELPER_DEFINED
    #define SIGIL_BOUNDS_HELPER_DEFINED
    static inline uint64_t sigil_bounds_check(uint64_t i, uint64_t n) { if (i >= n) abort(); return i; }
  #endif
  #define SIGIL_IDX(i, n) ((ptrdiff_t)sigil_bounds_check((uint64_t)(i), (uint64_t)(n)))
#else
  #define SIGIL_IDX(i, n) (i)
#endif

#if defined(__STDC_VERSION__) && __STDC_VERSION__ >= 201112L && !defined(__STDC_NO_ALIGNAS__)
  #define SIGIL_HAS_ALIGNMENT 1
  #define SIGIL_ALIGNED_TAG(kind, name, n) kind name
  #define SIGIL_ALIGN_MEMBER(n) _Alignas(n)
  #define SIGIL_ALIGNOF(type) _Alignof(type)
#elif defined(_MSC_VER)
  #define SIGIL_HAS_ALIGNMENT 1
  #define SIGIL_ALIGNED_TAG(kind, name, n) __declspec(align(n)) kind name
  #define SIGIL_ALIGN_MEMBER(n)
  #define SIGIL_ALIGNOF(type) __alignof(type)
#elif defined(__GNUC__) || defined(__clang__)
  #define SIGIL_HAS_ALIGNMENT 1
  #define SIGIL_ALIGNED_TAG(kind, name, n) __extension__ kind __attribute__((aligned(n))) name
  #define SIGIL_ALIGN_MEMBER(n)
  #define SIGIL_ALIGNOF(type) __alignof__(type)
#else
  #define SIGIL_HAS_ALIGNMENT 0
  #define SIGIL_ALIGNED_TAG(kind, name, n) kind name
  #define SIGIL_ALIGN_MEMBER(n)
#endif

#if defined(__GNUC__) || defined(__clang__)
  #define SIGIL_HAS_ATTR 1
  #define SIGIL_ATTR(...) __attribute__((__VA_ARGS__))
#else
  #define SIGIL_HAS_ATTR 0
  #define SIGIL_ATTR(...)
#endif

#if defined(__STDC_VERSION__) && __STDC_VERSION__ >= 201112L
  #define SIGIL_STATIC_ASSERT(cond, msg) _Static_assert(cond, msg)
#else
  #define SIGIL_SA_CAT_(a, b) a##b
  #define SIGIL_SA_CAT(a, b) SIGIL_SA_CAT_(a, b)
  #if defined(__GNUC__) || defined(__clang__)
    #define SIGIL_STATIC_ASSERT(cond, msg) typedef char SIGIL_SA_CAT(sigil_static_assert_, __LINE__)[(cond) ? 1 : -1] __attribute__((unused))
  #else
    #define SIGIL_STATIC_ASSERT(cond, msg) typedef char SIGIL_SA_CAT(sigil_static_assert_, __LINE__)[(cond) ? 1 : -1]
  #endif
#endif

#if (defined(__GNUC__) && __GNUC__ >= 7) || defined(__clang__)
  #define SIGIL_FALLTHROUGH() __attribute__((fallthrough))
#else
  #define SIGIL_FALLTHROUGH() ((void)0)
#endif

"""

C99_HEADER = "/* Generated by Sigil-C v1.1 AST Compiler. DO NOT EDIT. */\n" + C99_HEADER_BODY

C99_PRELUDE = ("/* Sigil-C shared prelude: generated by Sigil-C. Include this once per build,\n"
               "   then let every generated .c/.h pick it up with --prelude. DO NOT EDIT. */\n"
               + C99_HEADER_BODY)

class CodeGenerator:
    def __init__(self, filename: str = "input.sigil", header_mode: bool = False,
                 prelude_include: Optional[str] = None, bounds_check: bool = False,
                 cli_defines: Optional[Dict[str, str]] = None):
        self.safe_filename = filename.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '')
        self.header_mode = header_mode
        self.prelude_include = prelude_include
        self.bounds_check = bounds_check
        self.cli_defines = cli_defines or {}
        self.lines: List[str] = []

    def _emit(self, code: str, line: int, indent: int = 0):
        pad = "    " * indent
        if self.header_mode:
            self.lines.append(f"{pad}{code}\n")
        else:
            self.lines.append(f'#line {line} "{self.safe_filename}"\n{pad}{code}\n')

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
        if self.bounds_check:
            self.lines.append("#define SIGIL_BOUNDS_CHECK 1\n")
        if self.prelude_include:
            self.lines.append(f'#include "{self.prelude_include}"\n')
        else:
            self.lines.append(C99_HEADER)
        self._emit_cli_defines()
        for node in nodes:
            self.gen_top(node)
        return "".join(self.lines)

    def generate_header(self, nodes: List[StmtNode], guard: str) -> str:
        self.lines.append(f"/* Public interface generated by Sigil-C from {self.safe_filename}. DO NOT EDIT. */\n")
        self.lines.append(f"#ifndef {guard}\n#define {guard}\n\n")
        if self.bounds_check:
            self.lines.append("#define SIGIL_BOUNDS_CHECK 1\n")
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
                for s in node.body.stmts:
                    self.gen_stmt(s, indent=1)
                self._emit("}", node.line)
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
            self._emit(f"{decl}{f' = {emit_expr(s.init_expr)}' if s.init_expr else ''};", s.line, indent)
        elif isinstance(s, AssignStmt):
            self._emit(f"{emit_expr(s.target)} {s.op} {emit_expr(s.value)};", s.line, indent)
        elif isinstance(s, ExprStmt):
            self._emit(f"{emit_expr(s.expr)};", s.line, indent)
        elif isinstance(s, ReturnStmt):
            self._emit(f"return{f' {emit_expr(s.expr)}' if s.expr else ''};", s.line, indent)
        elif isinstance(s, JumpStmt):
            self._emit(f"{s.keyword};", s.line, indent)
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
        return isinstance(last, (ReturnStmt, GotoStmt))

def compile_source(src: str, filename: str = "input.sigil", prelude: Optional[str] = None,
                   bounds_check: bool = False, defines: Optional[Dict[str, str]] = None) -> str:
    EXTERNAL_C_SPELLING.clear()
    tokens = Lexer(src, filename).tokenize()
    ast = Parser(tokens, filename, defines).parse_program()
    return CodeGenerator(filename, prelude_include=prelude, bounds_check=bounds_check,
                         cli_defines=defines).generate(ast)

def check_source(src: str, filename: str = "input.sigil", defines: Optional[Dict[str, str]] = None) -> None:
    """词法 + 语法 + 静态语义检查，不产生任何输出。"""
    EXTERNAL_C_SPELLING.clear()
    tokens = Lexer(src, filename).tokenize()
    Parser(tokens, filename, defines).parse_program()

def _header_guard(header_name: str) -> str:
    base = os.path.basename(header_name).upper()
    return "SIGIL_" + "".join(ch if ch.isalnum() else "_" for ch in base)

def compile_header(src: str, filename: str = "input.sigil", header_name: str = "output.h",
                   prelude: Optional[str] = None, bounds_check: bool = False,
                   defines: Optional[Dict[str, str]] = None) -> str:
    """生成公共接口头文件：类型定义 + 非 static 函数原型 + 非 static 全局 extern。"""
    EXTERNAL_C_SPELLING.clear()
    tokens = Lexer(src, filename).tokenize()
    ast = Parser(tokens, filename, defines).parse_program()
    return CodeGenerator(filename, header_mode=True, prelude_include=prelude,
                         bounds_check=bounds_check, cli_defines=defines).generate_header(ast, _header_guard(header_name))

def _print_error(exc: Exception, fname: str, src: str) -> None:
    """打印错误，并在能定位时给出源码片段与插入符。"""
    msg = str(exc)
    print(f"error: {msg}", file=sys.stderr)
    m = re.match(rf"{re.escape(fname)}:(\d+):(\d+):", msg)
    if not m:
        return
    line_no, col = int(m.group(1)), int(m.group(2))
    lines = src.splitlines()
    if line_no < 1 or line_no > len(lines):
        return
    text = lines[line_no - 1]
    print(f"  --> {fname}:{line_no}:{col}", file=sys.stderr)
    print(f"  {line_no:>4} | {text}", file=sys.stderr)
    print(f"       | {' ' * max(0, col - 1)}^", file=sys.stderr)

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="sigilc.py",
        description="Sigil-C v1.1 — transpile .sigil sources to ISO C99",
    )
    ap.add_argument("input", help="input .sigil source file")
    ap.add_argument("output", nargs="?", help="output .c path (default: <input>.c)")
    ap.add_argument("-o", "--output", dest="output_opt", metavar="PATH", help="output .c path")
    ap.add_argument("--emit-header", action="store_true",
                    help="also emit a C header next to the output (same basename, .h)")
    ap.add_argument("--header", metavar="PATH", help="explicit header output path (implies --emit-header)")
    ap.add_argument("--check", action="store_true", help="parse and type-check only; write nothing")
    ap.add_argument("--emit-prelude", metavar="PATH",
                    help="write the shared Sigil-C C prelude (macros) to PATH")
    ap.add_argument("--prelude", metavar="NAME",
                    help="include NAME instead of inlining the prelude macro block in generated files")
    ap.add_argument("--bounds-check", action="store_true",
                    help="emit #define SIGIL_BOUNDS_CHECK 1 so array subscripts are bounds-checked at run time")
    ap.add_argument("--define", metavar="NAME=VALUE", action="append", default=[],
                    help="predefine a macro constant (repeatable), like #define NAME VALUE")
    ap.add_argument("--version", action="version", version="Sigil-C 1.1")
    args = ap.parse_args(argv)

    in_path = args.input
    out_path = args.output_opt or args.output or (os.path.splitext(in_path)[0] + ".c")
    with open(in_path, "r", encoding="utf-8") as f:
        src = f.read()
    fname = os.path.basename(in_path)

    defines: Dict[str, str] = {}
    for item in args.define:
        if "=" not in item:
            print(f"error: --define expects NAME=VALUE, got '{item}'", file=sys.stderr)
            return 2
        d_name, d_value = item.split("=", 1)
        defines[d_name.strip()] = d_value.strip()

    if args.emit_prelude:
        with open(args.emit_prelude, "w", encoding="utf-8") as f:
            f.write(C99_PRELUDE)
        print(f"Prelude  {args.emit_prelude}")

    try:
        if args.check:
            check_source(src, fname, defines=defines)
            print(f"Checked {in_path}: OK")
            return 0

        c_src = compile_source(src, fname, prelude=args.prelude, bounds_check=args.bounds_check, defines=defines)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(c_src)
        print(f"Compiled {in_path} -> {out_path}")

        header_path = args.header or (os.path.splitext(out_path)[0] + ".h" if args.emit_header else None)
        if header_path:
            h_src = compile_header(src, fname, os.path.basename(header_path), prelude=args.prelude,
                                   bounds_check=args.bounds_check, defines=defines)
            with open(header_path, "w", encoding="utf-8") as f:
                f.write(h_src)
            print(f"Header   {header_path}")
    except (LexerError, ParseError, SemanticError) as e:
        _print_error(e, fname, src)
        return 1
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (LexerError, ParseError, SemanticError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
