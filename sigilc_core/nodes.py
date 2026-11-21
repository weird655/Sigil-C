"""Sigil-C nodes (generated split of sigilc.py)."""

from dataclasses import dataclass, field
from typing import Dict, List, NamedTuple, Optional, Tuple

from .type_system import BaseType, PointerType, TypeNode, format_c_declarator

_CHECKED_ARITH = False

def set_checked_arith(on: bool) -> None:
    global _CHECKED_ARITH
    _CHECKED_ARITH = on

_CHECK_TYPES = {
    "i1": ("i1", True), "int8_t": ("i1", True),
    "i2": ("i2", True), "int16_t": ("i2", True),
    "i4": ("i4", True), "int32_t": ("i4", True),
    "i8": ("i8", True), "int64_t": ("i8", True),
    "u1": ("u1", False), "uint8_t": ("u1", False),
    "u2": ("u2", False), "uint16_t": ("u2", False),
    "u4": ("u4", False), "uint32_t": ("u4", False),
    "u8": ("u8", False), "uint64_t": ("u8", False),
}


def _checked_kind(t) -> Optional[Tuple[str, bool]]:
    return _CHECK_TYPES.get(t.c_name) if isinstance(t, BaseType) else None

def checked_binary(op: str, left: str, right: str, t) -> Optional[str]:
    if not _CHECKED_ARITH:
        return None
    k = _checked_kind(t)
    if k is None:
        return None
    suf, signed = k
    if op in ("+", "-", "*") and signed:
        name = {"+": "add", "-": "sub", "*": "mul"}[op]
        return f"sigil_{name}_{suf}({left}, {right})"
    if op in ("/", "%"):
        name = {"/": "div", "%": "mod"}[op]
        return f"sigil_{name}_{suf}({left}, {right})"
    if op in ("<<", ">>"):
        name = {"<<": "shl", ">>": "shr"}[op]
        return f"sigil_{name}_{suf}({left}, {right})"
    return None


@dataclass
class Attribute:
    """a@(...) 里的一个属性：名字 + 已校验的实参文本。"""
    name: str
    args: List[str] = field(default_factory=list)

    def render(self) -> str:
        if not self.args:
            return self.name
        return f"{self.name}({', '.join(self.args)})"

@dataclass
class ExprNode:
    line: int
    col: int

@dataclass
class LiteralExpr(ExprNode):
    code: str
    lit_kind: str = 'INT_NUM'

@dataclass
class IdentExpr(ExprNode):
    name: str

@dataclass
class TnxFnExpr(ExprNode):
    name: str

@dataclass
class CastExpr(ExprNode):
    target_type: TypeNode
    operand: ExprNode

@dataclass
class UnaryExpr(ExprNode):
    op: str
    operand: ExprNode

@dataclass
class BinaryExpr(ExprNode):
    op: str
    left: ExprNode
    right: ExprNode

@dataclass
class TernaryExpr(ExprNode):
    cond: ExprNode
    then_expr: ExprNode
    else_expr: ExprNode

@dataclass
class CallExpr(ExprNode):
    callee: ExprNode
    args: List[ExprNode]

@dataclass
class IndexExpr(ExprNode):
    base: ExprNode
    index: ExprNode
    bound: Optional[int] = None

@dataclass
class MemberExpr(ExprNode):
    base: ExprNode
    field: str
    is_arrow: bool


@dataclass
class BitSliceExpr(ExprNode):
    base: ExprNode
    base_type: TypeNode
    offset: int = 0
    width: int = 1
    byte_index: Optional[int] = None

@dataclass
class StmtNode:
    line: int
    col: int

@dataclass
class PreprocNode(StmtNode):
    text: str

@dataclass
class VarDeclStmt(StmtNode):
    var_type: TypeNode
    name: str
    init_expr: Optional[ExprNode] = None
    is_static: bool = False
    attrs: List[Attribute] = field(default_factory=list)
    bit_width: Optional[int] = None

@dataclass
class AssignStmt(StmtNode):
    op: str
    target: ExprNode
    value: ExprNode

@dataclass
class ExprStmt(StmtNode):
    expr: ExprNode

@dataclass
class BlockStmt(StmtNode):
    stmts: List[StmtNode]

@dataclass
class IfStmt(StmtNode):
    cond: ExprNode
    then_block: BlockStmt
    else_branch: Optional[StmtNode] = None

@dataclass
class WhileStmt(StmtNode):
    cond: ExprNode
    body: BlockStmt

@dataclass
class ForStmt(StmtNode):
    init_stmt: Optional[StmtNode]
    cond_expr: Optional[ExprNode]
    step_stmt: Optional[StmtNode]
    body: BlockStmt

@dataclass
class CaseClause:
    line: int
    value: Optional[ExprNode]
    stmts: List[StmtNode]

@dataclass
class SwitchStmt(StmtNode):
    cond: ExprNode
    cases: List[CaseClause]

@dataclass
class ReturnStmt(StmtNode):
    expr: Optional[ExprNode]

@dataclass
class JumpStmt(StmtNode):
    keyword: str

@dataclass
class DoWhileStmt(StmtNode):
    body: BlockStmt
    cond: ExprNode

@dataclass
class StaticAssertStmt(StmtNode):
    cond: ExprNode
    message: str

@dataclass
class GotoStmt(StmtNode):
    label: str

@dataclass
class LabelStmt(StmtNode):
    name: str

@dataclass
class VaStmt(StmtNode):
    """`va_start(ap, last);` / `va_end(ap);` / `va_copy(dst, src);`"""
    kind: str
    ap: ExprNode
    last_name: Optional[str] = None
    ap2: Optional[ExprNode] = None

@dataclass
class StructDefNode(StmtNode):
    kind: str
    name: str
    alignment: Optional[int]
    fields: List[VarDeclStmt]
    emit_typedef: bool = True
    attrs: List[Attribute] = field(default_factory=list)

@dataclass
class ExternalTypeNode(StmtNode):
    """`x!` 外部类型：不生成定义，只登记字段供转译期检查。"""
    name: str
    c_spelling: str
    opaque: bool
    field_count: int = 0
    fields: Dict[str, TypeNode] = field(default_factory=dict)
    bitfields: Dict[str, int] = field(default_factory=dict)

@dataclass
class EnumDefNode(StmtNode):
    name: str
    items: List[Tuple[str, Optional[ExprNode]]]

@dataclass
class FuncDefNode(StmtNode):
    return_type: TypeNode
    name: str
    params: List[Tuple[TypeNode, str]]
    body: Optional[BlockStmt]
    is_static: bool = False
    attrs: List[Attribute] = field(default_factory=list)
    is_inline: bool = False
    is_variadic: bool = False

@dataclass
class TnxNode(StmtNode):
    name: str
    priority: int
    seq: int
    width: int
    payload: ExprNode
    next_name: Optional[str] = None
    locked: bool = True

@dataclass
class SizeofExpr(ExprNode):
    target_type: Optional[TypeNode]
    operand: Optional[ExprNode]

@dataclass
class AlignofExpr(ExprNode):
    target_type: TypeNode

@dataclass
class TrapStmt(StmtNode):
    """`d!`：立即终止执行（SIGIL_TRAP）。"""

@dataclass
class AggregateInit(ExprNode):
    """`{ e1, e2, ... }` 位置式聚合初始化；只允许出现在声明初始化位置。"""
    elements: List[ExprNode]

@dataclass
class DesignatedInit(ExprNode):
    """`{ .field m, value }` 指定式初始化元素（C99 的 `.field = value`）。"""
    field: str
    value: 'ExprNode'

@dataclass
class DesignatedIndex(ExprNode):
    """`{ [2] m, value }` 数组下标指定初始化元素（C99 的 `[2] = value`）。"""
    index_expr: ExprNode
    index_val: int
    value: 'ExprNode'

@dataclass
class CompoundLiteral(ExprNode):
    """`(Type){ ... }` 复合字面量。"""
    target_type: TypeNode
    init: 'AggregateInit'

@dataclass
class VaArgExpr(ExprNode):
    """`v^ ap, T` 读取下一个可变参，结果类型为 T。"""
    ap: ExprNode
    target_type: TypeNode

@dataclass
class OffsetofExpr(ExprNode):
    """`offsetof(Type, field)` 内建形式。"""
    target_type: TypeNode
    field: str

_SLICE_BYTES = {
    "uint8_t": 1, "int8_t": 1, "u1": 1, "i1": 1, "char": 1,
    "uint16_t": 2, "int16_t": 2, "u2": 2, "i2": 2,
    "uint32_t": 4, "int32_t": 4, "u4": 4, "i4": 4, "float": 4, "f4": 4,
    "uint64_t": 8, "int64_t": 8, "u8": 8, "i8": 8, "double": 8, "f8": 8,
}


def slice_uint_type(t: TypeNode) -> str:
    return "uint64_t" if _SLICE_BYTES.get(getattr(t, "c_name", ""), 4) >= 8 else "uint32_t"


def slice_mask(width: int) -> str:
    if width >= 64:
        return "~0ULL"
    return f"((1ULL << {width}) - 1)"


def emit_expr(e: ExprNode) -> str:
    if isinstance(e, LiteralExpr):
        return e.code
    if isinstance(e, AggregateInit):
        return "{ " + ", ".join(emit_expr(x) for x in e.elements) + " }"
    if isinstance(e, DesignatedInit):
        return f".{e.field} = {emit_expr(e.value)}"
    if isinstance(e, DesignatedIndex):
        return f"[{emit_expr(e.index_expr)}] = {emit_expr(e.value)}"
    if isinstance(e, CompoundLiteral):
        return f"(({format_c_declarator(e.target_type)}){emit_expr(e.init)})"
    if isinstance(e, VaArgExpr):
        return f"va_arg({emit_expr(e.ap)}, {format_c_declarator(e.target_type)})"
    if isinstance(e, OffsetofExpr):
        return f"offsetof({format_c_declarator(e.target_type)}, {e.field})"
    if isinstance(e, IdentExpr):
        return e.name
    if isinstance(e, TnxFnExpr):
        return e.name
    if isinstance(e, CastExpr):
        operand = emit_expr(e.operand)
        if _CHECKED_ARITH:
            k = _checked_kind(e.target_type)
            src = getattr(e.operand, "sem_type", None)
            if k is not None and isinstance(src, BaseType) and src.c_name in ("float", "double", "long double", "f4", "f8"):
                return f"sigil_f2i_{k[0]}((double)({operand}))"
        return f"(({format_c_declarator(e.target_type)})({operand}))"
    if isinstance(e, SizeofExpr):
        if e.target_type is not None:
            return f"sizeof({format_c_declarator(e.target_type)})"
        assert e.operand is not None
        return f"sizeof({emit_expr(e.operand)})"
    if isinstance(e, AlignofExpr):
        return f"SIGIL_ALIGNOF({format_c_declarator(e.target_type)})"
    if isinstance(e, UnaryExpr):
        operand = emit_expr(e.operand)
        if _CHECKED_ARITH and e.op == "*":
            return f"(*SIGIL_NONNULL({operand}))"
        if _CHECKED_ARITH and e.op == "-":
            k = _checked_kind(getattr(e, "sem_type", None))
            if k is not None and k[1]:
                return f"sigil_neg_{k[0]}({operand})"
        return f"({e.op}{operand})"
    if isinstance(e, BinaryExpr):
        left, right = emit_expr(e.left), emit_expr(e.right)
        st = getattr(e, "sem_type", None)
        if _CHECKED_ARITH and isinstance(st, PointerType) and e.op in ("+", "-"):
            lt = getattr(e.left, "sem_type", None)
            rt = getattr(e.right, "sem_type", None)
            if isinstance(lt, PointerType) and not isinstance(rt, PointerType):
                ptr, num = left, right
            elif e.op == "+" and isinstance(rt, PointerType) and not isinstance(lt, PointerType):
                ptr, num = right, left
            else:
                ptr, num = "", ""
            if ptr:
                elem = f"sizeof(*({ptr}))"
                return (f"(({format_c_declarator(st)})(sigil_ptr_add((void *)({ptr}), "
                        f"(ptrdiff_t)({num}), {elem}, __builtin_object_size(({ptr}), 0))))")
        checked = checked_binary(e.op, left, right, st)
        if checked is not None:
            return checked
        return f"({left} {e.op} {right})"
    if isinstance(e, TernaryExpr):
        return f"({emit_expr(e.cond)} ? {emit_expr(e.then_expr)} : {emit_expr(e.else_expr)})"
    if isinstance(e, CallExpr):
        callee = emit_expr(e.callee)
        if _CHECKED_ARITH:
            callee = f"SIGIL_NONNULL({callee})"
        return f"{callee}({', '.join(emit_expr(a) for a in e.args)})"
    if isinstance(e, IndexExpr):
        if e.bound is not None:
            return f"{emit_expr(e.base)}[SIGIL_IDX({emit_expr(e.index)}, {e.bound})]"
        if _CHECKED_ARITH and isinstance(getattr(e.base, "sem_type", None), PointerType):
            base = emit_expr(e.base)
            idx = emit_expr(e.index)
            return (f"{base}[sigil_cidx((void *)({base}), (uint64_t)({idx}), "
                    f"sizeof(*({base})), __builtin_object_size(({base}), 0))]")
        return f"{emit_expr(e.base)}[{emit_expr(e.index)}]"
    if isinstance(e, BitSliceExpr):
        base = emit_expr(e.base)
        if e.byte_index is not None:
            return f"(((unsigned char *)&({base}))[{e.byte_index}])"
        uint = slice_uint_type(e.base_type)
        return f"((({uint})({base}) >> {e.offset}) & {slice_mask(e.width)})"
    if isinstance(e, MemberExpr):
        base = emit_expr(e.base)
        if _CHECKED_ARITH and e.is_arrow:
            base = f"SIGIL_NONNULL({base})"
        return f"{base}{'->' if e.is_arrow else '.'}{e.field}"
    raise TypeError(f"Unknown ExprNode: {e}")


# ============================================================================
# 3. Recursive-Descent Parser & Static Semantic Analyzer
# ============================================================================

class ParseError(Exception):
    pass

class SemanticError(Exception):
    pass


class MultiError(SemanticError):
    """A batch of (line, column, message) diagnostics from one parse."""

    def __init__(self, items):
        self.items = list(items)
        super().__init__("\n".join(msg for _, _, msg in self.items))

ASSIGN_TOKENS = {
    'OP_ASSIGN': '=',
    'OP_ADD_ASSIGN': '+=',
    'OP_SUB_ASSIGN': '-=',
    'OP_MUL_ASSIGN': '*=',
    'OP_DIV_ASSIGN': '/=',
}

class Prov(NamedTuple):
    """指针来源：基对象、元素个数、相对基对象的元素偏移、基对象声明时的作用域深度。"""
    base: str
    size: int
    offset: int
    depth: int

