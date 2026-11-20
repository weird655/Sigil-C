"""vN hard-resistor declarations.

vN is a read-only compile-time byte slot:
    v1 { v/ data v/ u2 v/ value ; }
The data type/value must occupy exactly the rated capacity and the result is
emitted as a const-qualified global/local. Assignment and address-taking are
rejected by the parser.
"""
from typing import Optional

from .lexer import Token
from .nodes import ExprNode, LiteralExpr, ParseError, SemanticError, VarDeclStmt
from .type_system import BaseType, FunctionPointerType, PointerType, TypeNode, format_c_declarator

_VRES_BYTES = {
    'int8_t': 1, 'uint8_t': 1, 'char': 1, 'bool': 1,
    'int16_t': 2, 'uint16_t': 2,
    'int32_t': 4, 'uint32_t': 4, 'float': 4, 'f4': 4,
    'int64_t': 8, 'uint64_t': 8, 'double': 8, 'f8': 8,
    'long double': 16,
    'u1': 1, 'i1': 1, 'u2': 2, 'i2': 2,
    'u4': 4, 'i4': 4, 'u8': 8, 'i8': 8,
}


def _type_bytes(t: TypeNode) -> Optional[int]:
    c = getattr(t, 'c_name', None)
    if c in _VRES_BYTES:
        return _VRES_BYTES[c]
    if isinstance(t, (PointerType, FunctionPointerType)):
        return 8
    return None


def _literal_bytes(parser, e: ExprNode, tok: Token) -> Optional[int]:
    if not isinstance(e, LiteralExpr):
        return None
    if e.lit_kind == 'BOOL':
        return 1
    if e.lit_kind in ('INT_NUM', 'CHAR'):
        v = parser._eval_const_int_expr(e)
        if v is None:
            return None
        if v < 0:
            raise SemanticError(
                f"{parser.filename}:{tok.line}:{tok.col}: vN capacity is unsigned; negative value {v} does not fit")
        for cap in (1, 2, 4, 8):
            if v <= (1 << (cap * 8)) - 1:
                return cap
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: vN value {v} exceeds 8 bytes")
    return None


def parse(parser, top_level: bool) -> VarDeclStmt:
    tok = parser._eat('KW_VRES')
    name = tok.value
    if name in parser.scopes[-1]:
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: Duplicate hard resistor '{name}' in this scope")
    parser._eat('LBRACE')
    parser._eat('VSLASH')
    data = parser.parse_pure_expr()
    parser._eat('VSLASH')
    cap_tok = parser._eat('TYPE_INT')
    cap = {'u1': 1, 'u2': 2, 'u4': 4, 'u8': 8}.get(cap_tok.value)
    if cap is None:
        raise SemanticError(
            f"{parser.filename}:{cap_tok.line}:{cap_tok.col}: vN capacity must be u1/u2/u4/u8, got '{cap_tok.value}'")
    parser._eat('VSLASH')
    ret = parser.parse_pure_expr()
    parser._eat('SEMI')
    if parser._cur().kind != 'RBRACE':
        raise ParseError(
            f"{parser.filename}:{parser._cur().line}:{parser._cur().col}: vN must contain exactly one v/ assertion")
    parser._eat('RBRACE')

    data_t = parser._infer_expr_type(data)
    data_bytes = _literal_bytes(parser, data, tok)
    if data_bytes is None:
        data_bytes = _type_bytes(data_t)
    if data_bytes is None:
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: vN data has unsupported size for '{format_c_declarator(data_t)}'")
    if data_bytes != cap:
        if data_bytes > cap:
            raise SemanticError(
                f"{parser.filename}:{tok.line}:{tok.col}: vN capacity mismatch: {name} data is {data_bytes} bytes, resistor is u{cap}")
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: vN redundant capacity: {name} data is {data_bytes} bytes, resistor is u{cap}")

    ret_t = parser._infer_expr_type(ret)
    ret_bytes = _literal_bytes(parser, ret, tok)
    if ret_bytes is None:
        ret_bytes = _type_bytes(ret_t)
    if ret_bytes is None:
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: vN return has unsupported size for '{format_c_declarator(ret_t)}'")
    if ret_bytes > cap:
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: vN return is {ret_bytes} bytes, exceeds resistor u{cap}")
    if top_level and not parser._is_static_const_init(ret):
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: vN return must be a compile-time constant at file scope")

    ctype = BaseType(line=tok.line, col=tok.col, c_name=f'uint{cap * 8}_t', is_const=True)
    parser._register_symbol(name, ctype, tok)
    parser.hard_resistors.add(name)
    return VarDeclStmt(line=tok.line, col=tok.col, var_type=ctype, name=name,
                       init_expr=ret, is_static=False)
