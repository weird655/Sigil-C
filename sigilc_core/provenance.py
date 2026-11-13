"""跨函数指针来源摘要（Phase 1+2）。

记录每个函数的：
  - 哪些形参（带常量偏移）可能通过 `r;` 返回给调用方；
  - 哪些出参会把某个形参的来源写进去（`*dst = src` / `dst[k] = src`）。

保守原则：推不出来的一律标 `unknown`，调用点按"没有来源"处理，绝不假装安全。
递归调用、函数指针、结构体字段回写都不建模。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .nodes import (
    AssignStmt,
    BinaryExpr,
    CallExpr,
    ExprNode,
    IdentExpr,
    IndexExpr,
    Prov,
    ReturnStmt,
    SemanticError,
    UnaryExpr,
)


@dataclass(frozen=True)
class RetSource:
    param: int
    offset: int


@dataclass(frozen=True)
class OutWrite:
    dst_param: int
    dst_offset: int
    src_param: int
    src_offset: int


@dataclass
class FuncProvSummary:
    returns: List[RetSource] = field(default_factory=list)
    out_writes: List[OutWrite] = field(default_factory=list)
    required_len: Dict[int, int] = field(default_factory=dict)
    unknown: bool = False


def _const_int(expr: ExprNode) -> Optional[int]:
    if isinstance(expr, UnaryExpr) and expr.op in ("-", "+") and isinstance(expr.operand, IdentExpr) is False:
        inner = _const_int(expr.operand)
        if inner is not None:
            return -inner if expr.op == "-" else inner
    if hasattr(expr, "code") and isinstance(getattr(expr, "code"), str):
        try:
            return int(getattr(expr, "code").rstrip("uUlL"), 0)
        except ValueError:
            return None
    return None


def _root_param(expr: Optional[ExprNode], params: List[str]) -> Optional[int]:
    if isinstance(expr, IdentExpr):
        return params.index(expr.name) if expr.name in params else None
    if isinstance(expr, UnaryExpr) and expr.op == "&":
        return _root_param(expr.operand, params)
    if isinstance(expr, IndexExpr):
        return _root_param(expr.base, params)
    if isinstance(expr, BinaryExpr):
        left = _root_param(expr.left, params)
        return left if left is not None else _root_param(expr.right, params)
    return None


def _param_offset(expr: Optional[ExprNode], params: List[str]) -> Optional[Tuple[int, int]]:
    """返回 (形参下标, 常量元素偏移)；推不出来返回 None。"""
    if isinstance(expr, IdentExpr):
        return (params.index(expr.name), 0) if expr.name in params else None
    if isinstance(expr, UnaryExpr) and expr.op == "&":
        return _param_offset(expr.operand, params)
    if isinstance(expr, IndexExpr):
        base = _param_offset(expr.base, params)
        idx = _const_int(expr.index)
        if base is not None and idx is not None:
            return (base[0], base[1] + idx)
        return None
    if isinstance(expr, BinaryExpr) and expr.op in ("+", "-"):
        left = _param_offset(expr.left, params)
        right = _const_int(expr.right)
        if left is not None and right is not None:
            return (left[0], left[1] + (right if expr.op == "+" else -right))
        return None
    return None


def _lvalue_offset(target: ExprNode, params: List[str]) -> Optional[Tuple[int, int]]:
    """`*dst` / `dst[k]` 中 dst 的 (形参下标, 偏移)。"""
    if isinstance(target, UnaryExpr) and target.op == "*":
        return _param_offset(target.operand, params)
    if isinstance(target, IndexExpr):
        base = _param_offset(target.base, params)
        idx = _const_int(target.index)
        if base is not None and idx is not None:
            return (base[0], base[1] + idx)
    if isinstance(target, UnaryExpr) and target.op == "&":
        return _param_offset(target.operand, params)
    return None


def check_param_access(parser, root, expr, kind, const_index=None) -> None:
    """pv 未知的参数访问：--strict 拒绝；否则记录长度要求。"""
    name = parser._param_name(root)
    if name is None:
        return
    if parser.strict_provenance:
        raise SemanticError(
            f"{parser.filename}:{expr.line}:{expr.col}: Cannot prove the bounds of parameter "
            f"'{name}' on {kind} (cross-function provenance is not tracked); "
            f"pass a bounded array or drop --strict")
    need = 1 if const_index is None else const_index + 1
    if need > 0:
        note_required_len(parser, name, need)


def note_required_len(parser, name: str, need: int) -> None:
    if parser.cur_summary is None or name not in parser.cur_params:
        return
    idx = parser.cur_params.index(name)
    parser.cur_summary.required_len[idx] = max(parser.cur_summary.required_len.get(idx, 0), need)


def note_return(parser, stmt: ReturnStmt) -> None:
    if parser.cur_summary is None or stmt.expr is None:
        return
    got = _param_offset(stmt.expr, parser.cur_params)
    if got is not None:
        parser.cur_summary.returns.append(RetSource(got[0], got[1]))
    elif _root_param(stmt.expr, parser.cur_params) is not None:
        parser.cur_summary.unknown = True


def note_assign(parser, stmt: AssignStmt) -> None:
    summary = parser.cur_summary
    if summary is None:
        return
    dst = _lvalue_offset(stmt.target, parser.cur_params)
    src = _param_offset(stmt.value, parser.cur_params)
    if dst is None:
        if _root_param(stmt.target, parser.cur_params) is not None:
            summary.unknown = True
        return
    if src is None:
        if _root_param(stmt.value, parser.cur_params) is not None:
            summary.unknown = True
        return
    summary.out_writes.append(OutWrite(dst[0], dst[1], src[0], src[1]))


def apply_call(parser, call: CallExpr) -> None:
    if not isinstance(call.callee, IdentExpr):
        return
    summary = parser.func_summaries.get(call.callee.name)
    if summary is None:
        return
    for param_idx, need in summary.required_len.items():
        if param_idx >= len(call.args):
            continue
        prov = parser._prov_of(call.args[param_idx])
        if prov is not None:
            if prov.offset + need > prov.size:
                raise SemanticError(
                    f"{parser.filename}:{call.line}:{call.col}: call to '{call.callee.name}' requires "
                    f"{need} element(s) from argument {param_idx + 1}, but '{prov.base}' provides "
                    f"{prov.size - prov.offset}")
        elif parser.strict_provenance:
            raise SemanticError(
                f"{parser.filename}:{call.line}:{call.col}: call to '{call.callee.name}' requires "
                f"{need} element(s) from argument {param_idx + 1}, but its provenance is unknown "
                f"(drop --strict to allow unchecked)")
    if summary.unknown:
        return
    if len(summary.returns) == 1:
        src = summary.returns[0]
        if src.param < len(call.args):
            prov = parser._prov_of(call.args[src.param])
            if prov is not None:
                setattr(call, "_call_prov", Prov(prov.base, prov.size, prov.offset + src.offset, prov.depth))
    depth = len(parser.scopes) - 1
    for w in summary.out_writes:
        if w.dst_param >= len(call.args) or w.src_param >= len(call.args):
            continue
        sp = parser._prov_of(call.args[w.src_param])
        dst_arg = call.args[w.dst_param]
        if sp is None:
            continue
        if isinstance(dst_arg, UnaryExpr) and dst_arg.op == "&" and isinstance(dst_arg.operand, IdentExpr):
            parser.prov[dst_arg.operand.name] = Prov(
                sp.base, sp.size, sp.offset + w.src_offset + w.dst_offset, depth)

def begin_function(parser, params) -> None:
    parser._summary_stack.append((parser.cur_summary, parser.cur_params))
    parser.cur_summary = FuncProvSummary()
    parser.cur_params = [pname for _, pname in params]


def end_function(parser, name: str) -> None:
    parser.func_summaries[name] = parser.cur_summary
    parser.cur_summary, parser.cur_params = parser._summary_stack.pop()

