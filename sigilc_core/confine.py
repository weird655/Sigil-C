"""Confinement groups and lockdown blocks for the dangerous !n! feature.

`!/[id]/! = f1, f2, ...;` registers a coordination group. `![mask]! !/[id]/! { ... }`
confines the packages declared inside: only functions whose bit in the mask is
1 may reference them. Nested lockdowns intersect their allowed sets.
"""
from typing import Dict, List, Optional, Set, Tuple

from .nodes import SemanticError


class Confinement:
    def __init__(self) -> None:
        self.groups: Dict[str, List[Tuple[str, str]]] = {}
        self.confined: Dict[str, Set[str]] = {}
        self.frames: List[Set[str]] = []

    def _expand(self, gid: str, seen: Set[str]) -> List[str]:
        if gid not in self.groups:
            raise SemanticError(f"Coordination group '!/[{gid}]/!' is not declared")
        if gid in seen:
            raise SemanticError(f"Coordination group '!/[{gid}]/!' contains itself")
        out: List[str] = []
        for kind, value in self.groups[gid]:
            members = [value] if kind == "name" else self._expand(value, seen | {gid})
            for member in members:
                if member not in out:
                    out.append(member)
        return out

    def expand(self, gid: str) -> List[str]:
        return self._expand(gid, set())

    def current_allowed(self) -> Optional[Set[str]]:
        return self.frames[-1] if self.frames else None

    def check(self, parser, pid: str, tok) -> None:
        allowed = self.confined.get(pid)
        if allowed is None:
            return
        current = parser.cur_func_name
        if current is None or current not in allowed:
            raise SemanticError(
                f"{parser.filename}:{tok.line}:{tok.col}: Package '!{pid}!' is confined; "
                f"'{current or '<top>'}' is not in the allowed group")


def parse_group(parser) -> None:
    tok = parser._eat('GROUP')
    parser._eat('PKG_BIND')
    members: List[Tuple[str, str]] = []
    while True:
        item = parser._cur()
        if item.kind == 'GROUP':
            parser._eat()
            members.append(("group", item.value))
        elif item.kind == 'IDENT':
            parser._eat()
            members.append(("name", item.value))
        else:
            raise SemanticError(
                f"{parser.filename}:{item.line}:{item.col}: Expected a function name or group")
        if parser._cur().kind == 'COMMA':
            parser._eat('COMMA')
            continue
        break
    parser._eat('SEMI')
    if tok.value in parser.confine.groups:
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: Group '!/[{tok.value}]/!' is already declared")
    parser.confine.groups[tok.value] = members


def parse_lockdown(parser) -> None:
    lock_tok = parser._eat('LOCK')
    mask = lock_tok.value
    group_tok = parser._eat('GROUP')
    members = parser.confine.expand(group_tok.value)
    if len(mask) != len(members):
        raise SemanticError(
            f"{parser.filename}:{lock_tok.line}:{lock_tok.col}: Mask '![{mask}]!' needs "
            f"{len(members)} bit(s), got {len(mask)}")
    allowed = {name for name, bit in zip(members, mask) if bit == '1'}
    outer = parser.confine.current_allowed()
    if outer is not None:
        allowed &= outer
    parser._eat('LBRACE')
    before = set(parser.pkgs.packages)
    parser.confine.frames.append(allowed)
    while parser._cur().kind != 'RBRACE':
        cur = parser._cur()
        if cur.kind == 'GROUP':
            parse_group(parser)
        elif cur.kind == 'LOCK':
            parse_lockdown(parser)
        elif cur.kind == 'PKG1':
            from . import packages
            packages.parse_decl(parser)
        else:
            raise SemanticError(
                f"{parser.filename}:{cur.line}:{cur.col}: A lockdown block may only contain "
                f"package declarations, groups and nested lockdowns")
    parser._eat('RBRACE')
    parser.confine.frames.pop()
    for pid in set(parser.pkgs.packages) - before:
        parser.confine.confined[pid] = parser.confine.confined.get(pid, allowed) & allowed
