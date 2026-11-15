"""Experimental cross-layer package aliases: `!n!`, `!/n/!`, `!>n<!`.

Entertainment feature. File-scope bindings are compile-time aliases; local
bindings use a global `void *` slot and a cast on every access. No lifetime
checks: a package to a local frame dangles after return.
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
from .type_system import BaseType, PointerType


class PackageTable:
    def __init__(self) -> None:
        self.packages: Dict[str, str] = {}   # package id -> alias name
        self.targets: Dict[str, str] = {}    # alias name -> target name
        self.aliases: Dict[str, str] = {}    # global alias B -> A
        self.slot_types: Dict[str, object] = {}
        self.local: Dict[str, str] = {}
        self.local_alias: Dict[str, str] = {}  # name -> package id

    def resolve(self, name: str) -> str:
        return self.aliases.get(name, name)

    def target(self, parser, pid: str, tok) -> str:
        name = self.packages.get(pid)
        if name is None:
            raise SemanticError(
                f"{parser.filename}:{tok.line}:{tok.col}: Package '!{pid}!' is not declared")
        target = self.targets.get(name)
        if target is None:
            raise SemanticError(
                f"{parser.filename}:{tok.line}:{tok.col}: Package '!{pid}!' is not bound to a name")
        return target

    def has_slot(self, pid: str) -> bool:
        return pid in self.slot_types and self.slot_types[pid] is not None


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


def _ensure_slot(parser, pid: str, tok) -> str:
    if _slot(pid) not in parser.scopes[0]:
        slot = _slot(pid)
        parser.pending_slots.append(
            VarDeclStmt(line=tok.line, col=tok.col,
                        var_type=_void_ptr(tok.line, tok.col), name=slot, is_static=True))
        parser.scopes[0][slot] = _void_ptr(tok.line, tok.col)
    return _slot(pid)


def parse_decl(parser) -> Optional[VarDeclStmt]:
    tok = parser._eat()  # PKG1
    pid = tok.value
    if parser._cur().kind == 'PKG_BIND':
        parser._eat('PKG_BIND')
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
    target = parser._eat('IDENT')
    parser._eat('SEMI')
    pid = tok.value
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
    left_type = parser._lookup_symbol(left.value, left)
    parser._lookup_symbol(right.value, right)
    parser.pkgs.slot_types[pid] = left_type
    parser.pkgs.local_alias[right.value] = pid
    slot = _ensure_slot(parser, pid, tok)
    addr = UnaryExpr(line=tok.line, col=tok.col, op='&',
                     operand=IdentExpr(line=left.line, col=left.col, name=left.value))
    cast = CastExpr(line=tok.line, col=tok.col, target_type=_void_ptr(tok.line, tok.col), operand=addr)
    bind = AssignStmt(line=tok.line, col=tok.col, op='=',
                      target=IdentExpr(line=tok.line, col=tok.col, name=slot), value=cast)
    # keep the aliased declaration "used" so -Wunused-variable does not fire
    use = ExprStmt(line=tok.line, col=tok.col, expr=CastExpr(
        line=tok.line, col=tok.col, target_type=BaseType(line=tok.line, col=tok.col, c_name='void'),
        operand=IdentExpr(line=right.line, col=right.col, name=right.value)))
    return [bind, use]


def parse_use(parser, tok):
    parser._eat()
    pid = tok.value
    if parser.pkgs.has_slot(pid):
        return _deref(parser, pid, tok)
    return IdentExpr(line=tok.line, col=tok.col, name=parser.pkgs.target(parser, pid, tok))


def local_expr(parser, name: str, tok):
    pid = parser.pkgs.local_alias[name]
    return _deref(parser, pid, tok)


def parse_link(parser) -> None:
    parser._eat()  # PKG3
    left = parser._eat('IDENT')
    right = parser._eat('IDENT')
    parser._eat('SEMI')
    parser.pkgs.aliases[right.value] = left.value
