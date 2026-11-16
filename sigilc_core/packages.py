"""Layer 2 experimental: allowed, but not part of the Core v1 freeze.

Package aliases: `!n!`, `!/n/!`, `!>n<!`.

Dangerous feature. File-scope bindings are compile-time aliases; local
bindings use a global `void *` slot. Packages can be nested (a package bound
to another package copies its binding), and `!>n<!` links form a global
alias chain with type and cycle checks. No lifetime checks.
"""
from typing import Dict, Optional, Set, Tuple

from .nodes import (
    AssignStmt,
    BitSliceExpr,
    CastExpr,
    ExprStmt,
    IdentExpr,
    SemanticError,
    UnaryExpr,
    VarDeclStmt,
)
from .type_system import BaseType, PointerType, types_equal


class PackageTable:
    def __init__(self) -> None:
        self.packages: Dict[str, str] = {}   # package id -> alias name
        self.targets: Dict[str, str] = {}    # alias name -> target name
        self.aliases: Dict[str, str] = {}    # global alias B -> A
        self.slot_types: Dict[str, object] = {}
        self.local: Dict[str, str] = {}
        self.local_alias: Dict[str, str] = {}  # name -> package id
        self.fields: Dict[str, Tuple[object, int, int, Optional[int], str]] = {}
        self.armed: Set[str] = set()
        self.arm_sites: Dict[str, Tuple[int, int]] = {}
        self.armed_bound: Dict[str, Tuple[int, int]] = {}

    def resolve(self, name: str) -> str:
        seen = set()
        while name in self.aliases and name not in seen:
            seen.add(name)
            name = self.aliases[name]
        return name

    def add_alias(self, parser, left: str, right: str, tok) -> None:
        if left == right:
            raise SemanticError(
                f"{parser.filename}:{tok.line}:{tok.col}: '!>{tok.value}<!' cannot link '{left}' to itself")
        cur = left
        seen = set()
        while cur in self.aliases:
            if cur in seen or cur == right:
                raise SemanticError(
                    f"{parser.filename}:{tok.line}:{tok.col}: '!>{tok.value}<!' would create an alias cycle")
            seen.add(cur)
            cur = self.aliases[cur]
        if cur == right:
            raise SemanticError(
                f"{parser.filename}:{tok.line}:{tok.col}: '!>{tok.value}<!' would create an alias cycle")
        self.aliases[right] = left

    def has_slot(self, pid: str) -> bool:
        return pid in self.slot_types and self.slot_types[pid] is not None

    def armed_name(self, name: str):
        resolved = self.resolve(name)
        for pid in self.armed:
            pname: Optional[str] = self.packages.get(pid)
            if pname is None:
                continue
            if pname == name or self.targets.get(pname) == resolved:
                return pid
        linked = self.local_alias.get(name)
        return linked if linked in self.armed else None

    def target(self, parser, pid: str, tok):
        if self.has_slot(pid):
            return f"slot:{pid}"
        name = self.packages.get(pid)
        if name is None:
            raise SemanticError(
                f"{parser.filename}:{tok.line}:{tok.col}: Package '!{pid}!' is not declared")
        target = self.targets.get(name)
        if target is None:
            raise SemanticError(
                f"{parser.filename}:{tok.line}:{tok.col}: Package '!{pid}!' is not bound to a name")
        return target


def _slot(pid: str) -> str:
    return f"__sigil_pkg_{pid}"


def _void_ptr(line: int, col: int) -> PointerType:
    return PointerType(line=line, col=col, pointee=BaseType(line=line, col=col, c_name='void'))


def _deref(parser, pid: str, tok):
    target_type = parser.pkgs.slot_types[pid]
    ptr_t = PointerType(line=tok.line, col=tok.col, pointee=target_type)
    return UnaryExpr(
        line=tok.line, col=tok.col, op='*',
        operand=CastExpr(line=tok.line, col=tok.col, target_type=ptr_t,
                         operand=IdentExpr(line=tok.line, col=tok.col, name=_slot(pid))))


def _ensure_slot(parser, pid: str, tok, init=None) -> str:
    slot = _slot(pid)
    if slot not in parser.scopes[0]:
        parser.pending_slots.append(
            VarDeclStmt(line=tok.line, col=tok.col,
                        var_type=_void_ptr(tok.line, tok.col), name=slot,
                        init_expr=init, is_static=True))
        parser.scopes[0][slot] = _void_ptr(tok.line, tok.col)
    return slot


def _lookup_type(parser, name: str, tok):
    pid = parser.pkgs.local_alias.get(name)
    if pid is not None:
        return parser.pkgs.slot_types[pid]
    return parser._lookup_symbol(name, tok)


def _address(parser, name: str, tok):
    pid = parser.pkgs.local_alias.get(name)
    if pid is not None:
        return IdentExpr(line=tok.line, col=tok.col, name=_slot(pid))
    return UnaryExpr(line=tok.line, col=tok.col, op='&',
                     operand=IdentExpr(line=tok.line, col=tok.col, name=name))


def _copy_slot(parser, dst: str, src: str, tok):
    parser.pkgs.slot_types[dst] = parser.pkgs.slot_types[src]
    parser.pkgs.local[dst] = parser.pkgs.local.get(src, "")
    dst_slot = _ensure_slot(parser, dst, tok)
    src_slot = _slot(src)
    return AssignStmt(line=tok.line, col=tok.col, op='=',
                      target=IdentExpr(line=tok.line, col=tok.col, name=dst_slot),
                      value=IdentExpr(line=tok.line, col=tok.col, name=src_slot))


_TYPE_BYTES = {
    "uint8_t": 1, "int8_t": 1, "u1": 1, "i1": 1, "char": 1,
    "uint16_t": 2, "int16_t": 2, "u2": 2, "i2": 2,
    "uint32_t": 4, "int32_t": 4, "u4": 4, "i4": 4, "float": 4, "f4": 4,
    "uint64_t": 8, "int64_t": 8, "u8": 8, "i8": 8, "double": 8, "f8": 8,
}


def _type_bytes(t) -> int:
    return _TYPE_BYTES.get(getattr(t, "c_name", ""), 1)


def _parse_slice_binding(parser, pid: str, tok, local: bool):
    kind_tok = parser._eat('IDENT')
    kind = kind_tok.value
    parser._eat('LPAREN')
    base_tok = parser._eat('IDENT')
    base_type = parser._lookup_symbol(base_tok.value, base_tok)
    c_name = getattr(base_type, "c_name", "")
    if kind in ('bit', 'bits') and not (c_name.startswith('i') or c_name.startswith('u')):
        raise SemanticError(
            f"{parser.filename}:{kind_tok.line}:{kind_tok.col}: '{kind}' needs an integer target, got '{c_name}'")
    parser._eat('COMMA')
    first = parser.parse_pure_expr()
    first_val = parser._eval_const_int_expr(first)
    if first_val is None:
        raise SemanticError(
            f"{parser.filename}:{kind_tok.line}:{kind_tok.col}: '{kind}' offset/index must be a constant")
    bits = _type_bytes(base_type) * 8
    if kind == 'byte':
        if not 0 <= first_val < _type_bytes(base_type):
            raise SemanticError(
                f"{parser.filename}:{kind_tok.line}:{kind_tok.col}: byte index {first_val} outside 0..{_type_bytes(base_type) - 1}")
        offset = 0
        width = 8
        byte_index = first_val
    else:
        offset = first_val
        if kind == 'bit':
            width = 1
        else:
            parser._eat('COMMA')
            w_expr = parser.parse_pure_expr()
            w_val = parser._eval_const_int_expr(w_expr)
            if w_val is None or w_val <= 0:
                raise SemanticError(
                    f"{parser.filename}:{kind_tok.line}:{kind_tok.col}: 'bits' width must be a positive constant")
            width = w_val
        if offset < 0 or width <= 0 or offset + width > bits:
            raise SemanticError(
                f"{parser.filename}:{kind_tok.line}:{kind_tok.col}: slice {offset}+{width} exceeds {bits} bits")
        byte_index = None
    parser._eat('RPAREN')
    parser._eat('SEMI')
    parser.pkgs.fields[pid] = (base_type, offset, width, byte_index, base_tok.value)
    if local:
        parser.pkgs.slot_types[pid] = base_type
        slot = _ensure_slot(parser, pid, tok)
        addr = UnaryExpr(line=tok.line, col=tok.col, op='&',
                         operand=IdentExpr(line=base_tok.line, col=base_tok.col, name=base_tok.value))
        cast = CastExpr(line=tok.line, col=tok.col, target_type=_void_ptr(tok.line, tok.col), operand=addr)
        return AssignStmt(line=tok.line, col=tok.col, op='=',
                          target=IdentExpr(line=tok.line, col=tok.col, name=slot), value=cast)
    return None


def _landmine_bind(parser, pid: str, tok) -> None:
    first = parser.pkgs.armed_bound.get(pid)
    if first is not None:
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: Landmine '!{pid}!!' already armed at "
            f"{first[0]}:{first[1]} (second bind at {tok.line}:{tok.col})")
    parser.pkgs.armed_bound[pid] = (tok.line, tok.col)


def parse_decl(parser) -> Optional[VarDeclStmt]:
    tok = parser._eat()  # PKG1 / PKG1_ARMED
    pid = tok.value
    armed = tok.kind == 'PKG1_ARMED'
    if parser._cur().kind == 'OP_ASSIGN':
        parser._eat('OP_ASSIGN')
        if armed:
            if pid not in parser.pkgs.packages:
                raise SemanticError(
                    f"{parser.filename}:{tok.line}:{tok.col}: Bind '!{pid}!!' with '!{pid}!! NAME;' first")
            if pid not in parser.pkgs.armed:
                raise SemanticError(
                    f"{parser.filename}:{tok.line}:{tok.col}: '!{pid}!!' was not declared as a landmine")
            _landmine_bind(parser, pid, tok)
        elif pid in parser.pkgs.armed:
            raise SemanticError(
                f"{parser.filename}:{tok.line}:{tok.col}: Landmine '!{pid}!!' must be bound with '!{pid}!! m, target;'")
        cur = parser._cur()
        if (cur.kind == 'IDENT' and cur.value in ('bit', 'bits', 'byte')
                and parser.tokens[parser.pos + 1].kind == 'LPAREN'):
            if pid not in parser.pkgs.packages:
                raise SemanticError(
                    f"{parser.filename}:{tok.line}:{tok.col}: Bind '!{pid}!' with '!{pid}! NAME;' first")
            return _parse_slice_binding(parser, pid, tok, local=False)
        if parser._cur().kind in ('PKG1', 'PKG2'):
            src_tok = parser._eat()
            parser._eat('SEMI')
            name = parser.pkgs.packages.get(pid)
            if name is None:
                raise SemanticError(
                    f"{parser.filename}:{tok.line}:{tok.col}: Bind '!{pid}!' with '!{pid}! NAME;' first")
            if parser.pkgs.has_slot(src_tok.value):
                if name in parser.pkgs.targets:
                    raise SemanticError(
                        f"{parser.filename}:{tok.line}:{tok.col}: Package '!{pid}!' is already bound")
                parser.pkgs.slot_types[pid] = parser.pkgs.slot_types[src_tok.value]
                parser.pkgs.local[pid] = parser.pkgs.local.get(src_tok.value, "")
                _ensure_slot(parser, pid, tok, init=IdentExpr(
                    line=tok.line, col=tok.col, name=_slot(src_tok.value)))
                return None
            src = parser.pkgs.target(parser, src_tok.value, src_tok)
            if name in parser.pkgs.targets:
                raise SemanticError(
                    f"{parser.filename}:{tok.line}:{tok.col}: Package '!{pid}!' is already bound")
            parser.pkgs.targets[name] = src
            parser.pkgs.aliases[name] = src
            return None
        target = parser._eat('IDENT')
        parser._eat('SEMI')
        name = parser.pkgs.packages.get(pid)
        if name is None:
            raise SemanticError(
                f"{parser.filename}:{tok.line}:{tok.col}: Bind '!{pid}!' with '!{pid}! NAME;' first")
        if name in parser.pkgs.targets:
            raise SemanticError(
                f"{parser.filename}:{tok.line}:{tok.col}: Package '!{pid}!' is already bound")
        parser.pkgs.targets[name] = target.value
        parser.pkgs.aliases[name] = target.value
        return None
    name_tok = parser._eat('IDENT')
    parser._eat('SEMI')
    if pid in parser.pkgs.packages:
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: Package '!{pid}!' is already declared")
    parser.pkgs.packages[pid] = name_tok.value
    if armed:
        parser.pkgs.armed.add(pid)
        parser.pkgs.arm_sites[pid] = (tok.line, tok.col)
    return None


def parse_bind_local(parser, tok):
    parser._eat()
    parser._eat('OP_ASSIGN')
    pid = tok.value
    armed = tok.kind == 'PKG1_ARMED'
    if armed:
        if pid not in parser.pkgs.packages:
            raise SemanticError(
                f"{parser.filename}:{tok.line}:{tok.col}: Bind '!{pid}!!' with '!{pid}!! NAME;' first")
        if pid not in parser.pkgs.armed:
            raise SemanticError(
                f"{parser.filename}:{tok.line}:{tok.col}: '!{pid}!!' was not declared as a landmine")
        _landmine_bind(parser, pid, tok)
    elif pid in parser.pkgs.armed:
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: Landmine '!{pid}!!' must be bound with '!{pid}!! m, target;'")
    cur = parser._cur()
    if (cur.kind == 'IDENT' and cur.value in ('bit', 'bits', 'byte')
            and parser.tokens[parser.pos + 1].kind == 'LPAREN'):
        return _parse_slice_binding(parser, pid, tok, local=True)
    if parser._cur().kind in ('PKG1', 'PKG2'):
        src_tok = parser._eat()
        parser._eat('SEMI')
        if parser.pkgs.has_slot(src_tok.value):
            return _copy_slot(parser, pid, src_tok.value, tok)
        src = parser.pkgs.target(parser, src_tok.value, src_tok)
        src_type = parser._lookup_symbol(src, src_tok)
        parser.pkgs.slot_types[pid] = src_type
        parser.pkgs.local[pid] = src
        slot = _ensure_slot(parser, pid, tok)
        cast = CastExpr(line=tok.line, col=tok.col, target_type=_void_ptr(tok.line, tok.col),
                        operand=UnaryExpr(line=tok.line, col=tok.col, op='&',
                                          operand=IdentExpr(line=tok.line, col=tok.col, name=src)))
        return AssignStmt(line=tok.line, col=tok.col, op='=',
                          target=IdentExpr(line=tok.line, col=tok.col, name=slot), value=cast)
    target = parser._eat('IDENT')
    parser._eat('SEMI')
    target_type = parser._lookup_symbol(target.value, target)
    parser.pkgs.slot_types[pid] = target_type
    parser.pkgs.local[pid] = target.value
    slot = _ensure_slot(parser, pid, tok)
    addr = UnaryExpr(line=tok.line, col=tok.col, op='&',
                     operand=IdentExpr(line=target.line, col=target.col, name=target.value))
    cast = CastExpr(line=tok.line, col=tok.col, target_type=_void_ptr(tok.line, tok.col), operand=addr)
    return AssignStmt(line=tok.line, col=tok.col, op='=',
                      target=IdentExpr(line=tok.line, col=tok.col, name=slot), value=cast)


def parse_link_local(parser, tok):
    parser._eat('PKG3')
    left = parser._eat('IDENT')
    right = parser._eat('IDENT')
    parser._eat('SEMI')
    pid = tok.value
    left_type = _lookup_type(parser, left.value, left)
    right_type = _lookup_type(parser, right.value, right)
    if not types_equal(left_type, right_type):
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: '!>{pid}<!' needs matching types")
    if parser.pkgs.armed_name(right.value) is not None:
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: '!>{pid}<!' cannot overwrite landmine '{right.value}'")
    parser.pkgs.slot_types[pid] = left_type
    parser.pkgs.local_alias[right.value] = pid
    slot = _ensure_slot(parser, pid, tok)
    value = _address(parser, left.value, left)
    if not isinstance(value, UnaryExpr):
        # left is already a package slot; copy the pointer, not the address of a deref
        value = CastExpr(line=tok.line, col=tok.col, target_type=_void_ptr(tok.line, tok.col),
                         operand=value)
    bind = AssignStmt(line=tok.line, col=tok.col, op='=',
                      target=IdentExpr(line=tok.line, col=tok.col, name=slot), value=value)
    use = ExprStmt(line=tok.line, col=tok.col, expr=CastExpr(
        line=tok.line, col=tok.col, target_type=BaseType(line=tok.line, col=tok.col, c_name='void'),
        operand=IdentExpr(line=right.line, col=right.col, name=right.value)))
    return [bind, use]


def parse_use(parser, tok):
    parser._eat()
    pid = tok.value
    if pid in parser.pkgs.fields:
        base_type, offset, width, byte_index, base_name = parser.pkgs.fields[pid]
        if parser.pkgs.has_slot(pid):
            ptr_t = PointerType(line=tok.line, col=tok.col, pointee=base_type)
            base = UnaryExpr(line=tok.line, col=tok.col, op='*',
                             operand=CastExpr(line=tok.line, col=tok.col, target_type=ptr_t,
                                              operand=IdentExpr(line=tok.line, col=tok.col, name=_slot(pid))))
        else:
            base = IdentExpr(line=tok.line, col=tok.col, name=base_name)
        return BitSliceExpr(line=tok.line, col=tok.col, base=base, base_type=base_type,
                            offset=offset, width=width, byte_index=byte_index)
    if parser.pkgs.has_slot(pid):
        return _deref(parser, pid, tok)
    return IdentExpr(line=tok.line, col=tok.col,
                     name=parser.pkgs.target(parser, pid, tok))


def local_expr(parser, name: str, tok):
    pid = parser.pkgs.local_alias[name]
    return _deref(parser, pid, tok)


def parse_link(parser) -> None:
    parser._eat()  # PKG3
    left = parser._eat('IDENT')
    right = parser._eat('IDENT')
    parser._eat('SEMI')
    if parser.pkgs.armed_name(right.value) is not None:
        raise SemanticError(
            f"{parser.filename}:{left.line}:{left.col}: '!>{left.value}<!' cannot overwrite landmine '{right.value}'")
    left_type = parser._lookup_symbol(left.value, left)
    right_type = parser._lookup_symbol(right.value, right)
    if not types_equal(left_type, right_type):
        raise SemanticError(
            f"{parser.filename}:{left.line}:{left.col}: '!>{left.value}<!' needs matching types")
    parser.pkgs.add_alias(parser, parser.pkgs.resolve(left.value),
                          parser.pkgs.resolve(right.value), left)


def begin_function(parser) -> None:
    parser._pkg_saved.append((dict(parser.pkgs.local_alias), dict(parser.pkgs.local)))


def end_function(parser) -> None:
    local_alias, local = parser._pkg_saved.pop()
    parser.pkgs.local_alias = local_alias
    parser.pkgs.local = local
