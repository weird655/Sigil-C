"""T N X prepared-packet descriptors.

TNX is a bounded priority mailbox descriptor:
    T3A { width 8; payload !handler!; next T3B; locked; }

N is priority 0-9 (higher first), X is sequence 0-9/A-F (lower first).
The descriptor itself is immutable; queue storage lives in generated C.
"""
from .nodes import LiteralExpr, SemanticError, TnxFnExpr, TnxNode

_TNX_BYTES = {
    'int8_t': 1, 'uint8_t': 1, 'char': 1, 'bool': 1,
    'int16_t': 2, 'uint16_t': 2,
    'int32_t': 4, 'uint32_t': 4, 'float': 4, 'f4': 4,
    'int64_t': 8, 'uint64_t': 8, 'double': 8, 'f8': 8,
    'long double': 16,
    'u1': 1, 'i1': 1, 'u2': 2, 'i2': 2,
    'u4': 4, 'i4': 4, 'u8': 8, 'i8': 8,
}


def type_bytes(t):
    c = getattr(t, 'c_name', None)
    if c in _TNX_BYTES:
        return _TNX_BYTES[c]
    if type(t).__name__ in ('PointerType', 'FunctionPointerType'):
        return 8
    return None


def parse(parser) -> TnxNode:
    tok = parser._eat('KW_TNX')
    name = tok.value
    if name in parser.tnx_nodes:
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: Duplicate TNX container '{name}'")
    parser._eat('LBRACE')
    width = None
    payload = None
    next_name = None
    locked = False
    seen = set()
    while parser._cur().kind != 'RBRACE':
        f = parser._eat('IDENT')
        key = f.value
        if key in seen:
            raise SemanticError(
                f"{parser.filename}:{f.line}:{f.col}: Duplicate TNX field '{key}'")
        seen.add(key)
        if key == 'width':
            n = parser._eat('INT_NUM')
            lit = LiteralExpr(line=n.line, col=n.col, code=n.value, lit_kind='INT_NUM')
            v = parser._eval_const_int_expr(lit)
            if v is None or v <= 0:
                raise SemanticError(
                    f"{parser.filename}:{n.line}:{n.col}: TNX width must be a positive constant")
            width = v
            parser._eat('SEMI')
        elif key == 'payload':
            payload = parser.parse_pure_expr()
            parser._eat('SEMI')
        elif key == 'next':
            nxt = parser._eat('KW_TNX')
            next_name = nxt.value
            parser._eat('SEMI')
        elif key == 'locked':
            locked = True
            parser._eat('SEMI')
        else:
            raise SemanticError(
                f"{parser.filename}:{f.line}:{f.col}: Unknown TNX field '{key}'")
    parser._eat('RBRACE')

    if width is None or payload is None or not locked:
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: TNX requires width, payload, and locked")

    if isinstance(payload, TnxFnExpr):
        pbytes = 8
    else:
        pbytes = type_bytes(parser._infer_expr_type(payload))
    if pbytes is None:
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: TNX payload has unknown byte width")
    if pbytes > width:
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: TNX payload is {pbytes} bytes, width is {width}")

    node = TnxNode(line=tok.line, col=tok.col, name=name,
                   priority=int(name[1]), seq=int(name[2], 16), width=width,
                   payload=payload, next_name=next_name, locked=True)
    parser.tnx_nodes[name] = node
    return node


def validate(parser) -> None:
    for name, n in parser.tnx_nodes.items():
        if n.next_name is None:
            continue
        if n.next_name == name:
            raise SemanticError(
                f"{parser.filename}:{n.line}:{n.col}: TNX '{name}' cannot point to itself")
        target = parser.tnx_nodes.get(n.next_name)
        if target is None:
            raise SemanticError(
                f"{parser.filename}:{n.line}:{n.col}: TNX next target '{n.next_name}' does not exist")
        if target.priority != n.priority:
            raise SemanticError(
                f"{parser.filename}:{n.line}:{n.col}: TNX next target must share priority {n.priority}")
    for name in parser.tnx_nodes:
        cur = name
        local = set()
        while cur in parser.tnx_nodes and parser.tnx_nodes[cur].next_name:
            if cur in local:
                raise SemanticError(
                    f"{parser.filename}:{parser.tnx_nodes[name].line}:{parser.tnx_nodes[name].col}: TNX next cycle at '{cur}'")
            local.add(cur)
            cur = parser.tnx_nodes[cur].next_name
