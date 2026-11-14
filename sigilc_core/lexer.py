"""Sigil-C lexer (generated split of sigilc.py)."""

from dataclasses import dataclass
from typing import Dict, List


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
    'p@': 'KW_ADDR',
    'c@': 'KW_CONST',    'v@': 'KW_VOLATILE', 'v.': 'TYPE_VOID',   'b.': 'TYPE_BOOL',
    'z?': 'KW_SIZEOF',   's@': 'KW_STATIC',   'a@': 'KW_ATTR',
    'i@': 'KW_INLINE',   'w!': 'KW_BITFIELD', 't!': 'KW_STATIC_ASSERT',
    'd~': 'KW_DO',       'g!': 'KW_GOTO',     'l!': 'KW_LABEL',
    'r@': 'KW_RESTRICT',  'g?': 'KW_GENERIC',
    'x!': 'KW_EXTERNAL',   'a?': 'KW_ALIGNOF',
    'd!': 'KW_TRAP',
}

# x! 声明的外部类型：Sigil 侧名字 -> 生成 C 里的实际拼写
# （例如 x! struct sockaddr_in { ... }; 这里记 sockaddr_in -> "struct sockaddr_in"）
EXTERNAL_C_SPELLING: Dict[str, str] = {}

SIGIL_OPERATORS = {
    'm,': 'OP_ASSIGN',      'm+': 'OP_ADD_ASSIGN',  'm-': 'OP_SUB_ASSIGN',
    'm*': 'OP_MUL_ASSIGN',  'm/': 'OP_DIV_ASSIGN',  '==': 'OP_EQ',
    '!=': 'OP_NE',          '&&': 'OP_LAND',        '||': 'OP_LOR',
    '->': 'ARROW',          '<<': 'OP_SHL',         '>>': 'OP_SHR',
    '<=': 'OP_LE',          '>=': 'OP_GE',
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
            suffix_chars = []
            while self.pos < self.n and self._peek() in 'uUlL':
                suffix_chars.append(self._advance())
            # 转换为标准 C99 十六进制字面量以保证 gcc -std=c99 -pedantic 零警告
            buf.append(hex(int(''.join(bin_digits), 2)) + ''.join(suffix_chars))
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
            suffix_text = literal[len(literal.rstrip('uUlL')):]
            if suffix_text not in VALID_INTEGER_SUFFIXES:
                raise LexerError(f"{self.filename}:{start_line}:{start_col}: Invalid C99 integer suffix '{suffix_text}'")

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

            if ch == 'p' and nxt.isdigit():
                j = 1
                while self._peek(j).isdigit():
                    j += 1
                if self._peek(j) in ('*', '@'):
                    digits = self.src[self.pos + 1:self.pos + j]
                    depth = int(digits)
                    if not 1 <= depth <= 15:
                        raise LexerError(f"{self.filename}:{s_line}:{s_col}: Pointer depth {depth} is outside 1..15")
                    suffix = self._peek(j)
                    kind = 'KW_PTR' if suffix == '*' else 'KW_ADDR'
                    self._advance(j + 1)
                    for _ in range(depth):
                        tokens.append(Token(kind, 'p' + suffix, s_line, s_col, s_byte))
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
                elif word == 'mod':
                    tokens.append(Token('PERCENT', word, s_line, s_col, s_byte))
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
                '%': 'PERCENT', '<': 'LT',     '>': 'GT',
                '&': 'OP_BAND', '|': 'OP_BOR', '^': 'OP_BXOR',
                '~': 'OP_BNOT', '!': 'OP_LNOT',
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

