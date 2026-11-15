"""Confinement groups and lockdown blocks for the dangerous !n! feature.

Short groups `!/[id]/! m, f1, f2;` use a binary mask (`![101]!`).
Long groups `!/[[id]]/! m, f1, f2, ...;` are immutable and select members by
1-based position list (`![1,3,5]!`) or `![*]!` for all.
"""
from typing import Dict, List, Optional, Set, Tuple

from .nodes import SemanticError


class Confinement:
    def __init__(self) -> None:
        self.groups: Dict[str, List[Tuple[str, str]]] = {}
        self.long_groups: Dict[str, List[Tuple[str, str]]] = {}
        self.confined: Dict[str, Set[str]] = {}
        self.frames: List[Set[str]] = []

    def _expand(self, kind: str, gid: str, seen: Set[Tuple[str, str]]) -> List[str]:
        key = (kind, gid)
        mapping = self.long_groups if kind == "long" else self.groups
        if gid not in mapping:
            label = f"!/[[{gid}]]/!" if kind == "long" else f"!/[{gid}]/!"
            raise SemanticError(f"Coordination group '{label}' is not declared")
        if key in seen:
            raise SemanticError(f"Coordination group '!/[{gid}]/!' contains itself")
        out: List[str] = []
        for ref_kind, value in mapping[gid]:
            members = [value] if ref_kind == "name" else self._expand(ref_kind, value, seen | {key})
            for member in members:
                if member not in out:
                    out.append(member)
        return out

    def expand_short(self, gid: str) -> List[str]:
        return self._expand("short", gid, set())

    def expand_long(self, gid: str) -> List[str]:
        return self._expand("long", gid, set())

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


def _parse_members(parser, token_kind: str) -> List[Tuple[str, str]]:
    members: List[Tuple[str, str]] = []
    while True:
        item = parser._cur()
        if item.kind in ('GROUP', 'LONG_GROUP'):
            parser._eat()
            members.append(("long" if item.kind == 'LONG_GROUP' else "group", item.value))
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
    return members


def parse_group(parser) -> None:
    tok = parser._eat('GROUP')
    parser._eat('OP_ASSIGN')
    members = _parse_members(parser, 'GROUP')
    if tok.value in parser.confine.groups or tok.value in parser.confine.long_groups:
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: Group '!/[{tok.value}]/!' is already declared")
    parser.confine.groups[tok.value] = members


def parse_long_group(parser) -> None:
    tok = parser._eat('LONG_GROUP')
    parser._eat('OP_ASSIGN')
    members = _parse_members(parser, 'LONG_GROUP')
    if tok.value in parser.confine.groups or tok.value in parser.confine.long_groups:
        raise SemanticError(
            f"{parser.filename}:{tok.line}:{tok.col}: Group '!/[[{tok.value}]]/!' is already declared")
    parser.confine.long_groups[tok.value] = members


def parse_lockdown(parser) -> None:
    lock_tok = parser._eat('LOCK')
    mask = lock_tok.value
    target = parser._eat()
    if target.kind == 'LONG_GROUP':
        members = parser.confine.expand_long(target.value)
        if mask == '*':
            allowed = set(members)
        else:
            chosen: Set[str] = set()
            for part in mask.split(','):
                part = part.strip()
                try:
                    pos = int(part)
                except ValueError:
                    raise SemanticError(
                        f"{parser.filename}:{lock_tok.line}:{lock_tok.col}: "
                        f"Long-group selection needs positions like ![1,3]! or ![ * ]!")
                if not 1 <= pos <= len(members):
                    raise SemanticError(
                        f"{parser.filename}:{lock_tok.line}:{lock_tok.col}: "
                        f"Position {pos} is outside 1..{len(members)}")
                chosen.add(members[pos - 1])
            allowed = chosen
    else:
        members = parser.confine.expand_short(target.value)
        if len(mask) != len(members) or any(bit not in '01' for bit in mask):
            raise SemanticError(
                f"{parser.filename}:{lock_tok.line}:{lock_tok.col}: Mask '![{mask}]!' needs "
                f"{len(members)} bit(s)")
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
        elif cur.kind == 'LONG_GROUP':
            parse_long_group(parser)
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
