#!/usr/bin/env python3
"""Emit a per-function contract summary as JSON.

This is the "observable half" of a contract system: what a function reads,
writes, calls, and how many elements it requires from each pointer parameter.
It does not enforce anything; it gives other tools and reviewers something
machine-checkable to compare against.

    python tools/contracts.py app.sigil
    python tools/contracts.py app.sigil -o app.contracts.json
"""
import argparse
import json
import os
import sys
from dataclasses import fields, is_dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sigilc_core.lexer import Lexer  # noqa: E402
from sigilc_core.nodes import (  # noqa: E402
    AssignStmt,
    CallExpr,
    ExprNode,
    FuncDefNode,
    IdentExpr,
    IndexExpr,
    LiteralExpr,
    StmtNode,
    UnaryExpr,
    VarDeclStmt,
)
from sigilc_core.parser import Parser  # noqa: E402


def children(node):
    if is_dataclass(node):
        for f in fields(node):
            value = getattr(node, f.name)
            if isinstance(value, (ExprNode, StmtNode)):
                yield value
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, (ExprNode, StmtNode)):
                        yield item


def walk(node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(list(children(current))))


def const_int(expr):
    if isinstance(expr, LiteralExpr) and expr.lit_kind == "INT_NUM":
        try:
            return int(expr.code, 0)
        except ValueError:
            return None
    return None


def param_root(expr, params):
    if isinstance(expr, IdentExpr):
        return expr.name if expr.name in params else None
    if isinstance(expr, UnaryExpr):
        return param_root(expr.operand, params)
    if isinstance(expr, IndexExpr):
        return param_root(expr.base, params)
    return None


def contract_for(fn, summaries):
    params = [name for _type, name in fn.params]
    reads, writes, assigns, calls = set(), set(), set(), []
    requires_len = {}
    locals_ = set()

    for node in walk(fn.body):
        if isinstance(node, VarDeclStmt):
            locals_.add(node.name)
        if isinstance(node, IdentExpr) and node.name in params:
            reads.add(node.name)
        elif isinstance(node, CallExpr) and isinstance(node.callee, IdentExpr):
            calls.append(node.callee.name)
        elif isinstance(node, IndexExpr):
            root = param_root(node.base, params)
            index = const_int(node.index)
            if root is not None and index is not None:
                requires_len[root] = max(requires_len.get(root, 0), index + 1)
        elif isinstance(node, UnaryExpr) and node.op == "*":
            root = param_root(node.operand, params)
            if root is not None:
                requires_len[root] = max(requires_len.get(root, 1), 1)
        elif isinstance(node, AssignStmt):
            target = node.target
            if isinstance(target, IdentExpr):
                if target.name in params:
                    writes.add(target.name)
                else:
                    assigns.add(target.name)
            else:
                root = param_root(target, params)
                if root is not None:
                    writes.add(root)

    summary = summaries.get(fn.name)
    returns = []
    out_writes = []
    if summary is not None:
        for source in summary.returns:
            if 0 <= source.param < len(params):
                returns.append({"param": params[source.param], "offset": source.offset})
        for write in summary.out_writes:
            if write.dst_param < len(params) and write.src_param < len(params):
                out_writes.append({
                    "dst": params[write.dst_param],
                    "dst_offset": write.dst_offset,
                    "src": params[write.src_param],
                    "src_offset": write.src_offset,
                })

    return {
        "params": params,
        "returns": returns,
        "out_writes": out_writes,
        "reads": sorted(reads),
        "writes": sorted(writes),
        "assigns_globals": sorted(assigns - locals_),
        "requires_len": dict(sorted(requires_len.items())),
        "calls": sorted(set(calls)),
        "effects": sorted(set(writes) | (assigns - locals_) | set(calls)),
    }


def contracts_for_source(text, filename):
    parser = Parser(Lexer(text, filename).tokenize(), filename)
    ast = parser.parse_program()
    funcs = [node for node in ast if isinstance(node, FuncDefNode)]
    return {
        "file": filename,
        "functions": {fn.name: contract_for(fn, parser.func_summaries) for fn in funcs},
    }


def main():
    ap = argparse.ArgumentParser(description="Emit per-function contract summaries as JSON")
    ap.add_argument("input")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    text = open(args.input, encoding="utf-8").read()
    data = contracts_for_source(text, args.input)
    rendered = json.dumps(data, indent=2, sort_keys=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="\n") as f:
            f.write(rendered + "\n")
        print(f"contracts: {args.input} -> {args.output}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
