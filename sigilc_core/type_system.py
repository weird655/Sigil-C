"""Sigil-C type_system (generated split of sigilc.py)."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Tuple

from .lexer import EXTERNAL_C_SPELLING, NUMERIC_C_TYPES

if TYPE_CHECKING:
    from .nodes import ExprNode

@dataclass
class TypeNode:
    line: int
    col: int

@dataclass
class BaseType(TypeNode):
    c_name: str
    is_const: bool = False
    is_volatile: bool = False

@dataclass
class PointerType(TypeNode):
    pointee: TypeNode
    is_const: bool = False
    is_volatile: bool = False
    is_restrict: bool = False

@dataclass
class ArrayType(TypeNode):
    element_type: TypeNode
    size_expr: 'ExprNode'
    size_val: Optional[int] = None

@dataclass
class FunctionPointerType(TypeNode):
    param_decls: List[Tuple[TypeNode, Optional[str]]]
    return_type: TypeNode
    is_const: bool = False
    is_volatile: bool = False
    is_variadic: bool = False

def is_void_type(t: TypeNode) -> bool:
    return isinstance(t, BaseType) and t.c_name == "void"

def is_const_qualified(t: TypeNode) -> bool:
    if isinstance(t, ArrayType):
        return is_const_qualified(t.element_type)
    if isinstance(t, (BaseType, PointerType, FunctionPointerType)):
        return t.is_const
    return False

def is_volatile_qualified(t: TypeNode) -> bool:
    if isinstance(t, ArrayType):
        return is_volatile_qualified(t.element_type)
    if isinstance(t, (BaseType, PointerType, FunctionPointerType)):
        return t.is_volatile
    return False

def strip_top_qualifiers(t: TypeNode) -> TypeNode:
    if isinstance(t, BaseType):
        return BaseType(line=t.line, col=t.col, c_name=t.c_name, is_const=False, is_volatile=False)
    if isinstance(t, PointerType):
        return PointerType(line=t.line, col=t.col, pointee=t.pointee, is_const=False, is_volatile=False, is_restrict=False)
    if isinstance(t, FunctionPointerType):
        return FunctionPointerType(line=t.line, col=t.col, param_decls=t.param_decls, return_type=t.return_type, is_const=False, is_volatile=False, is_variadic=t.is_variadic)
    if isinstance(t, ArrayType):
        return ArrayType(line=t.line, col=t.col, element_type=strip_top_qualifiers(t.element_type), size_expr=t.size_expr, size_val=t.size_val)
    return t

def with_const(t: TypeNode) -> TypeNode:
    if isinstance(t, BaseType):
        return BaseType(line=t.line, col=t.col, c_name=t.c_name, is_const=True, is_volatile=t.is_volatile)
    if isinstance(t, PointerType):
        return PointerType(line=t.line, col=t.col, pointee=t.pointee, is_const=True, is_volatile=t.is_volatile, is_restrict=t.is_restrict)
    if isinstance(t, FunctionPointerType):
        return FunctionPointerType(line=t.line, col=t.col, param_decls=t.param_decls, return_type=t.return_type, is_const=True, is_volatile=t.is_volatile, is_variadic=t.is_variadic)
    if isinstance(t, ArrayType):
        return ArrayType(line=t.line, col=t.col, element_type=with_const(t.element_type), size_expr=t.size_expr, size_val=t.size_val)
    return t

def with_volatile(t: TypeNode) -> TypeNode:
    if isinstance(t, BaseType):
        return BaseType(line=t.line, col=t.col, c_name=t.c_name, is_const=t.is_const, is_volatile=True)
    if isinstance(t, PointerType):
        return PointerType(line=t.line, col=t.col, pointee=t.pointee, is_const=t.is_const, is_volatile=True, is_restrict=t.is_restrict)
    if isinstance(t, FunctionPointerType):
        return FunctionPointerType(line=t.line, col=t.col, param_decls=t.param_decls, return_type=t.return_type, is_const=t.is_const, is_volatile=True, is_variadic=t.is_variadic)
    if isinstance(t, ArrayType):
        return ArrayType(line=t.line, col=t.col, element_type=with_volatile(t.element_type), size_expr=t.size_expr, size_val=t.size_val)
    return t

def qualifiers_are_assignable(destination: TypeNode, source: TypeNode) -> bool:
    if isinstance(destination, ArrayType) and isinstance(source, ArrayType):
        return qualifiers_are_assignable(destination.element_type, source.element_type)
    return not (
        (is_const_qualified(source) and not is_const_qualified(destination))
        or (is_volatile_qualified(source) and not is_volatile_qualified(destination))
    )

def decay_parameter_type(t: TypeNode) -> TypeNode:
    """C99 6.7.5.3p7: 函数形参最外层数组退化为指针；非数组形参保留顶层 const/volatile 供函数体检查"""
    if isinstance(t, ArrayType):
        return PointerType(line=t.line, col=t.col, pointee=t.element_type, is_const=False)
    return t

def types_equal(a: TypeNode, b: TypeNode) -> bool:
    from .nodes import emit_expr  # 延迟导入，避免与 nodes 形成循环
    if type(a) is not type(b):
        return False
    if isinstance(a, BaseType) and isinstance(b, BaseType):
        return a.c_name == b.c_name and a.is_const == b.is_const and a.is_volatile == b.is_volatile
    if isinstance(a, PointerType) and isinstance(b, PointerType):
        return a.is_const == b.is_const and a.is_volatile == b.is_volatile and types_equal(a.pointee, b.pointee)
    if isinstance(a, ArrayType) and isinstance(b, ArrayType):
        same_len = (a.size_val == b.size_val) if (a.size_val is not None and b.size_val is not None) else (emit_expr(a.size_expr) == emit_expr(b.size_expr))
        return types_equal(a.element_type, b.element_type) and same_len
    if isinstance(a, FunctionPointerType) and isinstance(b, FunctionPointerType):
        if a.is_const != b.is_const or a.is_volatile != b.is_volatile or len(a.param_decls) != len(b.param_decls) or a.is_variadic != b.is_variadic:
            return False
        if not types_equal(strip_top_qualifiers(a.return_type), strip_top_qualifiers(b.return_type)):
            return False
        return all(types_equal(strip_top_qualifiers(decay_parameter_type(pa[0])), strip_top_qualifiers(decay_parameter_type(pb[0]))) for pa, pb in zip(a.param_decls, b.param_decls))
    return False

def types_compatible_for_assign(expected: TypeNode, actual: TypeNode) -> bool:
    exp_clean = expected if isinstance(expected, ArrayType) else strip_top_qualifiers(expected)
    act_clean = actual if isinstance(actual, ArrayType) else strip_top_qualifiers(actual)
    if types_equal(exp_clean, act_clean):
        return True
    if isinstance(exp_clean, BaseType) and isinstance(act_clean, BaseType):
        if exp_clean.c_name in NUMERIC_C_TYPES and act_clean.c_name in NUMERIC_C_TYPES:
            return True
    if isinstance(exp_clean, PointerType) and isinstance(act_clean, ArrayType):
        if types_equal(strip_top_qualifiers(exp_clean.pointee), strip_top_qualifiers(act_clean.element_type)):
            if qualifiers_are_assignable(exp_clean.pointee, act_clean.element_type):
                return True
    if isinstance(exp_clean, PointerType) and isinstance(act_clean, PointerType):
        if is_void_type(exp_clean.pointee) or is_void_type(act_clean.pointee):
            if qualifiers_are_assignable(exp_clean.pointee, act_clean.pointee):
                return True
        if types_equal(strip_top_qualifiers(exp_clean.pointee), strip_top_qualifiers(act_clean.pointee)):
            return qualifiers_are_assignable(exp_clean.pointee, act_clean.pointee)
    return False

def format_c_declarator(t: TypeNode, var_name: str = "") -> str:
    from .nodes import emit_expr  # 延迟导入：nodes 需要本模块的类型定义
    inner = var_name
    curr = t
    while True:
        if isinstance(curr, BaseType):
            qualifier_words = [q for enabled, q in ((curr.is_const, "const"), (curr.is_volatile, "volatile")) if enabled]
            prefix = " ".join(qualifier_words) + (" " if qualifier_words else "")
            c_name = EXTERNAL_C_SPELLING.get(curr.c_name, curr.c_name)
            return f"{prefix}{c_name}" + (f" {inner}" if inner else "")
        elif isinstance(curr, PointerType):
            qualifier_text = " ".join(q for enabled, q in ((curr.is_const, "const"), (curr.is_volatile, "volatile"), (curr.is_restrict, "restrict")) if enabled)
            ptr_str = f"* {qualifier_text} {inner}" if qualifier_text and inner else (f"* {qualifier_text}" if qualifier_text else f"*{inner}")
            if isinstance(curr.pointee, (ArrayType, FunctionPointerType)):
                inner = f"({ptr_str.strip()})"
            else:
                inner = ptr_str.strip()
            curr = curr.pointee
        elif isinstance(curr, ArrayType):
            dim_code = emit_expr(curr.size_expr)
            inner = f"{inner}[{dim_code}]"
            curr = curr.element_type
        elif isinstance(curr, FunctionPointerType):
            params_c = [format_c_declarator(pt, pname or "") for pt, pname in curr.param_decls]
            if curr.is_variadic:
                params_c.append("...")
            param_list_str = ", ".join(params_c) if params_c else "void"
            qualifier_text = " ".join(q for enabled, q in ((curr.is_const, "const"), (curr.is_volatile, "volatile")) if enabled)
            qual = f"{qualifier_text} " if qualifier_text else ""
            fn_inner = f"(*{qual}{inner})({param_list_str})"
            return format_c_declarator(curr.return_type, fn_inner)
        else:
            raise TypeError(f"Unknown TypeNode: {curr}")

