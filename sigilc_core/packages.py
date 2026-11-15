"""Experimental package aliases: `!n!`, `!/n/!`, `!>n<!`.

Dangerous feature. File-scope bindings are compile-time aliases; local
bindings use a global `void *` slot. Packages can be nested (a package bound
to another package copies its binding), and `!>n<!` links form a global
alias chain with type and cycle checks. No lifetime checks.
"""
from typing import Dict, Optional

from .nodes import (
    AssignStmt,
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


def parse_decl(parser) -> Optional[VarDeclStmt]:
    tok = parser._eat()  # PKG1
    pid = tok.value
    if parser._cur().kind == 'PKG_BIND':
        parser._eat('PKG_BIND')
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
    return None


def parse_bind_local(parser, tok):
    parser._eat('PKG1')
    parser._eat('PKG_BIND')
    pid = tok.value
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
