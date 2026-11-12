"""Sigil-C nodes (generated split of sigilc.py)."""

from dataclasses import dataclass, field
from typing import List, NamedTuple, Optional, Tuple

from .type_system import TypeNode, format_c_declarator


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
    if isinstance(e, CastExpr):
        return f"(({format_c_declarator(e.target_type)})({emit_expr(e.operand)}))"
    if isinstance(e, SizeofExpr):
        if e.target_type is not None:
            return f"sizeof({format_c_declarator(e.target_type)})"
        assert e.operand is not None
        return f"sizeof({emit_expr(e.operand)})"
    if isinstance(e, AlignofExpr):
        return f"SIGIL_ALIGNOF({format_c_declarator(e.target_type)})"
    if isinstance(e, UnaryExpr):
        return f"({e.op}{emit_expr(e.operand)})"
    if isinstance(e, BinaryExpr):
        return f"({emit_expr(e.left)} {e.op} {emit_expr(e.right)})"
    if isinstance(e, TernaryExpr):
        return f"({emit_expr(e.cond)} ? {emit_expr(e.then_expr)} : {emit_expr(e.else_expr)})"
    if isinstance(e, CallExpr):
        return f"{emit_expr(e.callee)}({', '.join(emit_expr(a) for a in e.args)})"
    if isinstance(e, IndexExpr):
        if e.bound is not None:
            return f"{emit_expr(e.base)}[SIGIL_IDX({emit_expr(e.index)}, {e.bound})]"
        return f"{emit_expr(e.base)}[{emit_expr(e.index)}]"
    if isinstance(e, MemberExpr):
        return f"{emit_expr(e.base)}{'->' if e.is_arrow else '.'}{e.field}"
    raise TypeError(f"Unknown ExprNode: {e}")


# ============================================================================
# 3. Recursive-Descent Parser & Static Semantic Analyzer
# ============================================================================

class ParseError(Exception):
    pass

class SemanticError(Exception):
    pass

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

