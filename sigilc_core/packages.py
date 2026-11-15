"""Experimental cross-layer package aliases: `!n!`, `!/n/!`, `!>n<!`.

Entertainment feature. `!n!` is a global alias slot; `!/n/!` is its target;
`!>n<!` is a global bidirectional alias (both names share one storage).
No copies, no stack frames, no jumps. See SYNTAX.md.
"""
from typing import Dict

from .nodes import IdentExpr, SemanticError


class PackageTable:
    def __init__(self) -> None:
        self.packages: Dict[str, str] = {}   # package id -> alias name
        self.targets: Dict[str, str] = {}    # alias name -> target name
        self.aliases: Dict[str, str] = {}    # global alias B -> A

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


def parse_decl(parser) -> None:
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
        return
    name_tok = parser._eat('IDENT')
    parser._eat('SEMI')
    if pid in parser.pkgs.packages:
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: Package '!{pid}!' is already declared")
    parser.pkgs.packages[pid] = name_tok.value


def parse_link(parser) -> None:
    parser._eat()  # PKG3
    left = parser._eat('IDENT')
    right = parser._eat('IDENT')
    parser._eat('SEMI')
    parser.pkgs.aliases[right.value] = left.value


def parse_use(parser, tok) -> IdentExpr:
    parser._eat()
    return IdentExpr(line=tok.line, col=tok.col, name=parser.pkgs.target(parser, tok.value, tok))
