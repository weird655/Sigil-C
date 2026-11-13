"""Sigil-C parser (generated split of sigilc.py)."""

import re
from typing import Dict, List, Optional, Set, Tuple

from . import provenance
from .lexer import (
    ATTR_FILE_SCOPE_ONLY,
    ATTR_INT_LIST,
    ATTR_NOARGS,
    ATTR_ONE_INT,
    ATTR_ONE_STRING,
    ATTR_OPTIONAL_STRING,
    ATTR_TARGETS,
    BASIC_TYPES,
    BITFIELD_WIDTH,
    EXTERNAL_C_SPELLING,
    INT_C_TYPES,
    NUMERIC_C_TYPES,
    Token,
)
from .nodes import (
    ASSIGN_TOKENS,
    AggregateInit,
    AlignofExpr,
    AssignStmt,
    Attribute,
    BinaryExpr,
    BlockStmt,
    CallExpr,
    CaseClause,
    CastExpr,
    CompoundLiteral,
    DesignatedIndex,
    DesignatedInit,
    DoWhileStmt,
    EnumDefNode,
    ExprNode,
    ExprStmt,
    ExternalTypeNode,
    ForStmt,
    FuncDefNode,
    GotoStmt,
    IdentExpr,
    IfStmt,
    IndexExpr,
    JumpStmt,
    LabelStmt,
    LiteralExpr,
    MemberExpr,
    OffsetofExpr,
    ParseError,
    PreprocNode,
    Prov,
    ReturnStmt,
    SemanticError,
    SizeofExpr,
    StaticAssertStmt,
    StmtNode,
    StructDefNode,
    SwitchStmt,
    TernaryExpr,
    TrapStmt,
    UnaryExpr,
    VaArgExpr,
    VarDeclStmt,
    VaStmt,
    WhileStmt,
)
from .type_system import (
    ArrayType,
    BaseType,
    FunctionPointerType,
    PointerType,
    TypeNode,
    decay_parameter_type,
    format_c_declarator,
    is_const_qualified,
    is_void_type,
    is_volatile_qualified,
    strip_top_qualifiers,
    types_compatible_for_assign,
    types_equal,
    with_const,
    with_volatile,
)


class Parser:
    def __init__(self, tokens: List[Token], filename: str = "<input>",
                 defines: Optional[Dict[str, str]] = None,
                 strict_provenance: bool = False):
        self.tokens = tokens
        self.strict_provenance = strict_provenance
        self.pos = 0
        self.filename = filename
        self.user_types: Dict[str, str] = {}
        self.struct_fields: Dict[str, Dict[str, TypeNode]] = {}
        self.complete_structs: Set[str] = set()
        self.enum_constants: Dict[str, int] = {}
        self.macro_consts: Dict[str, int] = {}
        # 指针来源：名字 -> (基对象, 元素个数, 相对基对象的偏移)
        self.prov: Dict[str, Prov] = {}
        self._prov_saved: List[Dict[str, Optional[Prov]]] = []
        self.local_objects: Set[str] = set()
        self.param_names: Set[str] = set()
        # 跨函数逃逸：函数名 -> 被写进全局的参数名
        self.cur_func_name: Optional[str] = None
        self.cur_escape: Set[str] = set()
        self.escape_params: Dict[str, Set[str]] = {}
        self.func_param_names: Dict[str, List[str]] = {}
        self.func_summaries: Dict[str, provenance.FuncProvSummary] = {}
        self.cur_summary: Optional[provenance.FuncProvSummary] = None
        self.cur_params: List[str] = []
        self._summary_stack: List[Tuple[object, List[str]]] = []
        self.pending_calls: List[Tuple[str, List[Tuple[ExprNode, Optional['Prov']]], int, int]] = []
        # 局部 r@ 指针承诺独占访问的基对象 -> 声明时的作用域深度
        self.restricted: Dict[str, int] = {}
        self.scopes: List[Dict[str, TypeNode]] = [{}]
        self.func_sigs: Dict[str, Tuple[List[TypeNode], TypeNode]] = {}
        self.func_defined: Set[str] = set()
        self.func_variadic: Set[str] = set()
        self.struct_bitfields: Dict[str, Dict[str, int]] = {}
        self.func_labels: Set[str] = set()
        self.func_gotos: List[Tuple[str, Token]] = []
        self.current_func_ret: Optional[TypeNode] = None
        self.current_func_variadic: bool = False
        self.loop_depth: int = 0
        self.switch_depth: int = 0
        for d_name, d_value in (defines or {}).items():
            self._register_macro_constant(Token('PREPROC', f"#define {d_name} {d_value}", 1, 1, 0))

    def _cur(self) -> Token:
        return self.tokens[self.pos]

    def _eat(self, kind: Optional[str] = None) -> Token:
        tok = self._cur()
        if kind and tok.kind != kind:
            raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: Expected '{kind}', got '{tok.kind}' ('{tok.value}')")
        self.pos += 1
        return tok

    def _is_type_start_at(self, start_idx: int) -> bool:
        idx = start_idx
        while idx < len(self.tokens) and self.tokens[idx].kind in ('KW_PTR', 'KW_CONST', 'KW_VOLATILE'):
            idx += 1
        if idx >= len(self.tokens):
            return False
        t = self.tokens[idx]
        if t.kind == 'LPAREN' and idx + 1 < len(self.tokens) and self.tokens[idx + 1].kind in ('KW_PTR', 'KW_CONST', 'KW_VOLATILE', 'KW_FNPTR'):
            return self._is_type_start_at(idx + 1)
        return t.kind in ('TYPE_INT', 'TYPE_VOID', 'TYPE_BOOL', 'KW_FNPTR') or (
            t.kind == 'IDENT' and t.value in self.user_types
        )

    def _is_type_start(self, tok: Token) -> bool:
        return self._is_type_start_at(self.pos)

    def _can_omit_object_marker(self, tok: Token) -> bool:
        """基类型关键字开头的对象声明可以省略 `o!`：`u4 x;`、`b. flag;`。

        指针（`p*`）、限定（`c@` / `v@` / `r@`）与用户定义类型仍然必须写 `o!`：
        前者的字形与解引用表达式相同，后者是普通标识符，省掉就无法靠字面区分。
        """
        if tok.kind not in ('TYPE_INT', 'TYPE_BOOL'):
            return False
        nxt = self.tokens[self.pos + 1] if self.pos + 1 < len(self.tokens) else None
        return nxt is not None and nxt.kind in ('IDENT', 'LBRACK')

    # ------------------------------------------------------------------
    # a@(...) 属性：解析、参数形状校验、放置位置校验
    # ------------------------------------------------------------------
    def _attr_int_value(self, tok: Token, raw: str) -> int:
        s = raw.rstrip('uUlL')
        try:
            if s.startswith(('0x', '0X')):
                return int(s, 16)
            if s.startswith(('0b', '0B')):
                return int(s, 2)
            if s.startswith('0') and len(s) > 1 and s.isdigit():
                return int(s, 8)
            return int(s, 10)
        except ValueError:
            raise SemanticError(
                f"{self.filename}:{tok.line}:{tok.col}: Attribute argument '{raw}' is not an integer constant")

    def _validate_attribute(self, name_tok: Token, name: str, args: List[str]):
        if name not in ATTR_TARGETS:
            known = ', '.join(sorted(ATTR_TARGETS))
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: Unknown attribute '{name}'. "
                f"Supported attributes: {known}")
        if name in ATTR_NOARGS:
            if args:
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: Attribute '{name}' takes no arguments")
            return
        if name in ATTR_ONE_INT:
            if len(args) != 1:
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: Attribute '{name}' takes exactly 1 integer argument")
            value = self._attr_int_value(name_tok, args[0])
            if value <= 0 or (value & (value - 1)) != 0:
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: Attribute '{name}' requires a positive power-of-2 argument, got {value}")
            return
        if name in ATTR_ONE_STRING:
            if len(args) != 1 or not args[0].startswith('"'):
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: Attribute '{name}' takes exactly 1 string literal argument")
            return
        if name in ATTR_OPTIONAL_STRING:
            if len(args) > 1 or (args and not args[0].startswith('"')):
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: Attribute '{name}' takes an optional string literal argument")
            return
        if name in ATTR_INT_LIST:
            if not args:
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: Attribute '{name}' requires at least 1 integer argument")
            for arg in args:
                if self._attr_int_value(name_tok, arg) <= 0:
                    raise SemanticError(
                        f"{self.filename}:{name_tok.line}:{name_tok.col}: Attribute '{name}' argument indices are 1-based and positive")
            return

    def parse_attrs(self) -> List[Attribute]:
        """解析一个或多个 a@(...) 组，返回已校验参数形状的属性列表。"""
        attrs: List[Attribute] = []
        while self._cur().kind == 'KW_ATTR':
            at_tok = self._eat('KW_ATTR')
            self._eat('LPAREN')
            if self._cur().kind == 'RPAREN':
                raise ParseError(
                    f"{self.filename}:{at_tok.line}:{at_tok.col}: 'a@' requires at least one attribute name")
            while True:
                name_tok = self._eat('IDENT')
                args: List[str] = []
                if self._cur().kind == 'LPAREN':
                    self._eat('LPAREN')
                    if self._cur().kind == 'RPAREN':
                        raise ParseError(
                            f"{self.filename}:{name_tok.line}:{name_tok.col}: Empty argument list for attribute '{name_tok.value}'")
                    while True:
                        tok = self._cur()
                        if tok.kind in ('INT_NUM', 'FLOAT_NUM', 'STRING', 'CHAR', 'IDENT'):
                            args.append(tok.value)
                            self._eat()
                        else:
                            raise ParseError(
                                f"{self.filename}:{tok.line}:{tok.col}: Expected attribute argument, got '{tok.value}'")
                        if self._cur().kind == 'COMMA':
                            self._eat('COMMA')
                        else:
                            break
                    self._eat('RPAREN')
                self._validate_attribute(name_tok, name_tok.value, args)
                attrs.append(Attribute(name=name_tok.value, args=args))
                if self._cur().kind == 'COMMA':
                    self._eat('COMMA')
                else:
                    break
            self._eat('RPAREN')
        return attrs

    def _check_attr_placement(self, attrs: List[Attribute], place: str, tok: Token,
                              file_scope: bool = True):
        seen: Set[str] = set()
        for attr in attrs:
            if place not in ATTR_TARGETS[attr.name]:
                raise SemanticError(
                    f"{self.filename}:{tok.line}:{tok.col}: Attribute '{attr.name}' cannot be applied to this "
                    f"{place} declaration")
            if attr.name in seen:
                raise SemanticError(
                    f"{self.filename}:{tok.line}:{tok.col}: Duplicate attribute '{attr.name}'")
            if not file_scope and attr.name in ATTR_FILE_SCOPE_ONLY:
                raise SemanticError(
                    f"{self.filename}:{tok.line}:{tok.col}: Attribute '{attr.name}' is only valid at file scope")
            seen.add(attr.name)

    def _sizeof_takes_type(self) -> bool:
        """z? 后面接的是类型还是表达式。

        只有"确定是类型"的前缀才按类型解析：内置类型、指针/限定符前缀、已知用户类型。
        其余一律按表达式解析——这样 z? (p* src) 稳定读作"解引用后取大小"，
        而 z? p* u4 稳定读作"取指针类型大小"，避免 p* 既是类型前缀又是解引用运算符的歧义。
        """
        t = self._cur()
        if t.kind in ('TYPE_INT', 'TYPE_VOID', 'TYPE_BOOL', 'KW_FNPTR', 'KW_PTR', 'KW_CONST', 'KW_VOLATILE'):
            return True
        return t.kind == 'IDENT' and t.value in self.user_types

    def _lookup_symbol(self, name: str, tok: Token) -> TypeNode:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Undeclared identifier '{name}'")

    def _register_symbol(self, name: str, t: TypeNode, tok: Token):
        if name in self.scopes[-1]:
            raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Redefinition of '{name}' in the same scope")
        self.scopes[-1][name] = t

    def _validate_non_void_var(self, t: TypeNode, tok: Token):
        if is_void_type(t):
            raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Variable or field '{tok.value}' cannot have type 'v.' (void)")
        if isinstance(t, ArrayType) and is_void_type(t.element_type):
            raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Array of 'v.' (void) is illegal")
        if not self._is_complete_object_type(t):
            raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Variable or parameter '{tok.value}' has incomplete type")

    def _eval_const_int_expr(self, expr: ExprNode) -> Optional[int]:
        """纯整数常量表达式求值 (C99 向零截断除法/取模、比较、逻辑、三元、位运算，无浮点精度损失)"""
        if isinstance(expr, LiteralExpr):
            if expr.lit_kind == 'INT_NUM':
                s = expr.code.rstrip('uUlL')
                try:
                    if s.startswith(('0x', '0X', '0b', '0B')):
                        return int(s, 0)
                    if s.startswith('0') and len(s) > 1 and s.isdigit():
                        return int(s, 8)
                    return int(s, 10)
                except ValueError:
                    return None
            if expr.lit_kind == 'CHAR':
                inner = expr.code[1:-1]
                if len(inner) == 1:
                    return ord(inner)
                if inner.startswith('\\'):
                    esc_map = {'a': 7, 'b': 8, 'f': 12, 'n': 10, 'r': 13, 't': 9, 'v': 11, '\\': 92, "'": 39, '"': 34, '?': 63}
                    rest = inner[1:]
                    if rest in esc_map:
                        return esc_map[rest]
                    if rest.startswith('x'):
                        return int(rest[1:], 16)
                    if all(c in '01234567' for c in rest):
                        return int(rest, 8)
            return None
        if isinstance(expr, IdentExpr):
            if expr.name in self.enum_constants:
                return self.enum_constants[expr.name]
            return self.macro_consts.get(expr.name)
        if isinstance(expr, CastExpr):
            if isinstance(expr.target_type, BaseType) and expr.target_type.c_name in INT_C_TYPES:
                return self._eval_const_int_expr(expr.operand)
            return None
        if isinstance(expr, UnaryExpr):
            val = self._eval_const_int_expr(expr.operand)
            if val is None:
                return None
            if expr.op == '-':
                res_u = -val
                if res_u < -(1 << 63) or res_u >= (1 << 64):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Integer constant overflow out of 64-bit range")
                return res_u
            if expr.op == '+': return val
            if expr.op == '~': return ~val
            if expr.op == '!': return 1 if val == 0 else 0
        if isinstance(expr, TernaryExpr):
            cv = self._eval_const_int_expr(expr.cond)
            if cv is None:
                return None
            return self._eval_const_int_expr(expr.then_expr if cv != 0 else expr.else_expr)
        if isinstance(expr, BinaryExpr):
            lv = self._eval_const_int_expr(expr.left)
            if lv is None:
                return None
            if expr.op == '&&':
                if lv == 0:
                    return 0
                rv = self._eval_const_int_expr(expr.right)
                return int(bool(rv)) if rv is not None else None
            if expr.op == '||':
                if lv != 0:
                    return 1
                rv = self._eval_const_int_expr(expr.right)
                return int(bool(rv)) if rv is not None else None
            rv = self._eval_const_int_expr(expr.right)
            if rv is None:
                return None
            res: Optional[int] = None
            if expr.op == '+': res = lv + rv
            elif expr.op == '-': res = lv - rv
            elif expr.op == '*': res = lv * rv
            elif expr.op in ('/', '%'):
                if rv == 0:
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Division or modulo by zero in integer constant expression")
                # C99 6.5.5p6: 纯整数向零截断除法与余数 a == (a/b)*b + a%b
                q = -(abs(lv) // abs(rv)) if (lv < 0) ^ (rv < 0) else (abs(lv) // abs(rv))
                res = q if expr.op == '/' else (lv - q * rv)
            elif expr.op == '<<':
                if rv < 0 or rv >= 64:
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Shift count {rv} out of range [0, 63] in constant expression")
                if lv < 0:
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Left shift of negative value {lv} in constant expression")
                res = lv << rv
            elif expr.op == '>>':
                if rv < 0 or rv >= 64:
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Shift count {rv} out of range [0, 63] in constant expression")
                res = lv >> rv
            if res is not None:
                if res < -(1 << 63) or res >= (1 << 64):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Integer constant overflow out of 64-bit range")
                return res
            if expr.op == '|': return lv | rv
            if expr.op == '&': return lv & rv
            if expr.op == '^': return lv ^ rv
            if expr.op == '==': return int(lv == rv)
            if expr.op == '!=': return int(lv != rv)
            if expr.op == '<':  return int(lv < rv)
            if expr.op == '<=': return int(lv <= rv)
            if expr.op == '>':  return int(lv > rv)
            if expr.op == '>=': return int(lv >= rv)
            if expr.op == '&&': return int(bool(lv) and bool(rv))
            if expr.op == '||': return int(bool(lv) or bool(rv))
        return None

    def _infer_expr_type(self, expr: ExprNode) -> TypeNode:
        if isinstance(expr, CompoundLiteral):
            return expr.target_type
        if isinstance(expr, VaArgExpr):
            return expr.target_type
        if isinstance(expr, OffsetofExpr):
            return BaseType(line=expr.line, col=expr.col, c_name='size_t')
        if isinstance(expr, (AggregateInit, DesignatedInit, DesignatedIndex)):
            raise SemanticError(
                f"{self.filename}:{expr.line}:{expr.col}: Aggregate initializer '{{ ... }}' is only allowed as a declaration initializer or a compound literal")
        if isinstance(expr, LiteralExpr):
            if expr.lit_kind == 'BOOL':
                return BaseType(line=expr.line, col=expr.col, c_name='bool')
            if expr.lit_kind == 'NULL':
                return PointerType(line=expr.line, col=expr.col,
                                   pointee=BaseType(line=expr.line, col=expr.col, c_name='void'))
            if expr.lit_kind == 'STRING':
                return PointerType(line=expr.line, col=expr.col, pointee=BaseType(line=expr.line, col=expr.col, c_name='char', is_const=True))
            if expr.lit_kind == 'CHAR':
                return BaseType(line=expr.line, col=expr.col, c_name='char')
            if expr.lit_kind == 'FLOAT_NUM':
                if expr.code.endswith(('f', 'F')):
                    float_type = 'float'
                elif expr.code.endswith(('l', 'L')):
                    float_type = 'long double'
                else:
                    float_type = 'double'
                return BaseType(line=expr.line, col=expr.col, c_name=float_type)
            # INT_NUM (包括 0xFE 十六进制整数，严格推导为整型，修复 'E' 误判为浮点的问题)
            return BaseType(line=expr.line, col=expr.col, c_name='uint32_t' if expr.code.lower().endswith('u') else 'int32_t')

        if isinstance(expr, IdentExpr):
            return self._lookup_symbol(expr.name, Token('IDENT', expr.name, expr.line, expr.col, 0))

        if isinstance(expr, CastExpr):
            src_t = self._infer_expr_type(expr.operand)
            dst_t = expr.target_type
            if is_void_type(dst_t):
                return dst_t
            if not self._is_scalar_type(dst_t) or not self._is_scalar_type(src_t):
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Cast requires scalar types (unless casting to 'v.')")
            dst_is_float = isinstance(dst_t, BaseType) and dst_t.c_name in ('float', 'double', 'long double')
            src_is_float = isinstance(src_t, BaseType) and src_t.c_name in ('float', 'double', 'long double')
            if (dst_is_float and isinstance(src_t, (PointerType, FunctionPointerType))) or (src_is_float and isinstance(dst_t, (PointerType, FunctionPointerType))):
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Cannot cast between floating-point and pointer type")
            return dst_t

        if isinstance(expr, SizeofExpr):
            # sizeof 的结果类型是 size_t（已内置为整型，可与其它整型互相赋值）
            return BaseType(line=expr.line, col=expr.col, c_name='size_t')

        if isinstance(expr, AlignofExpr):
            return BaseType(line=expr.line, col=expr.col, c_name='size_t')

        if isinstance(expr, UnaryExpr):
            sub_t = self._infer_expr_type(expr.operand)
            if expr.op == '*':
                if isinstance(sub_t, PointerType):
                    if not self._is_complete_object_type(sub_t.pointee):
                        raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Cannot dereference pointer to incomplete or void type")
                    pv = self._prov_live(self._prov_of(expr.operand), expr)
                    if pv is None:
                        provenance.check_param_access(self, expr.operand, expr, "dereference")
                    if pv is not None:
                        if pv.offset < 0 or pv.offset >= pv.size:
                            raise SemanticError(
                                f"{self.filename}:{expr.line}:{expr.col}: Dereferencing a pointer into '{pv.base}' at "
                                f"element {pv.offset}, outside {pv.size} element(s)")
                    return sub_t.pointee
                if isinstance(sub_t, ArrayType):
                    return sub_t.element_type
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Cannot dereference non-pointer type")
            if expr.op == '&':
                self._check_restricted_base(expr.operand)
                if isinstance(expr.operand, MemberExpr) and self._member_is_bitfield(expr.operand):
                    raise SemanticError(
                        f"{self.filename}:{expr.line}:{expr.col}: Cannot take the address ('p@') of bit-field '{expr.operand.field}'")
                if not isinstance(expr.operand, (IdentExpr, IndexExpr, MemberExpr)) and not (isinstance(expr.operand, UnaryExpr) and expr.operand.op == '*'):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Cannot take address ('p@') of rvalue expression")
                return PointerType(line=expr.line, col=expr.col, pointee=sub_t)
            if expr.op == '!':
                if not self._is_scalar_type(sub_t):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Logical NOT ('!') requires scalar operand")
                return BaseType(line=expr.line, col=expr.col, c_name='bool')
            if expr.op == '~':
                if not self._is_int_type(sub_t):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Bitwise NOT ('~') requires integer operand")
                return sub_t
            if expr.op in ('+', '-'):
                if not self._is_numeric_type(sub_t):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Unary '{expr.op}' requires arithmetic operand")
                return sub_t
            return sub_t

        if isinstance(expr, IndexExpr):
            self._check_restricted_base(expr.base)
            base_t = self._infer_expr_type(expr.base)
            idx_t = self._infer_expr_type(expr.index)
            if not (isinstance(idx_t, BaseType) and (idx_t.c_name in INT_C_TYPES or self.user_types.get(idx_t.c_name) == 'enum')):
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Array subscript is not an integer")
            if isinstance(base_t, PointerType):
                if not self._is_complete_object_type(base_t.pointee):
                    raise SemanticError(
                        f"{self.filename}:{expr.line}:{expr.col}: Cannot subscript pointer to incomplete or void type"
                    )
                pv = self._prov_live(self._prov_of(expr.base), expr)
                if pv is None:
                    provenance.check_param_access(self, expr.base, expr, "subscript", self._try_const(expr.index))
                if pv is not None:
                    c_idx = self._try_const(expr.index)
                    if c_idx is not None:
                        pos = pv.offset + c_idx
                        if pos < 0 or pos >= pv.size:
                            raise SemanticError(
                                f"{self.filename}:{expr.line}:{expr.col}: Index {c_idx} through a pointer into "
                                f"'{pv.base}' reaches element {pos}, outside {pv.size} element(s)")
                    elif 0 <= pv.offset < pv.size:
                        expr.bound = pv.size - pv.offset
                return base_t.pointee
            if isinstance(base_t, ArrayType):
                if base_t.size_val is not None:
                    c_idx = self._eval_const_int_expr(expr.index)
                    if c_idx is not None and (c_idx < 0 or c_idx >= base_t.size_val):
                        raise SemanticError(
                            f"{self.filename}:{expr.line}:{expr.col}: Index {c_idx} is out of bounds for an array of "
                            f"{base_t.size_val} element(s)")
                    # 常量下标已在转译期校验，只有运行期才知道的才包边界检查
                    if c_idx is None:
                        expr.bound = base_t.size_val
                return base_t.element_type
            raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Subscripted value is neither array nor pointer")

        if isinstance(expr, MemberExpr):
            self._check_restricted_base(expr.base)
            base_t = self._infer_expr_type(expr.base)
            if expr.is_arrow:
                if not isinstance(base_t, PointerType) or not isinstance(base_t.pointee, BaseType):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: '->' applied to non-struct pointer")
                struct_name = base_t.pointee.c_name
                parent_is_const = base_t.pointee.is_const
                parent_is_volatile = base_t.pointee.is_volatile
            else:
                if not isinstance(base_t, BaseType):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: '.' applied to non-struct type")
                struct_name = base_t.c_name
                parent_is_const = base_t.is_const
                parent_is_volatile = base_t.is_volatile

            if struct_name not in self.struct_fields:
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Type '{struct_name}' has no member fields")
            f_map = self.struct_fields[struct_name]
            if expr.field not in f_map:
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: '{struct_name}' has no member named '{expr.field}'")
            ft = f_map[expr.field]
            if parent_is_const:
                ft = with_const(ft)
            if parent_is_volatile:
                ft = with_volatile(ft)
            return ft

        if isinstance(expr, CallExpr):
            if isinstance(expr.callee, IdentExpr) and expr.callee.name in self.func_sigs:
                _, ret_t = self.func_sigs[expr.callee.name]
                return ret_t
            callee_t = self._infer_expr_type(expr.callee)
            if isinstance(callee_t, FunctionPointerType):
                return callee_t.return_type
            raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Called object is not a function or function pointer")

        if isinstance(expr, TernaryExpr):
            t_then = self._infer_expr_type(expr.then_expr)
            t_else = self._infer_expr_type(expr.else_expr)
            return self._resolve_ternary_type(expr, t_then, t_else)

        if isinstance(expr, BinaryExpr):
            lt = self._decay_rvalue(self._infer_expr_type(expr.left))
            rt = self._decay_rvalue(self._infer_expr_type(expr.right))
            op = expr.op
            if op in ('&&', '||'):
                if not self._is_scalar_type(lt) or not self._is_scalar_type(rt):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Logical operator '{op}' requires scalar operands")
                return BaseType(line=expr.line, col=expr.col, c_name='bool')
            if op in ('==', '!='):
                if self._is_numeric_type(lt) and self._is_numeric_type(rt):
                    return BaseType(line=expr.line, col=expr.col, c_name='bool')
                if isinstance(lt, PointerType) and isinstance(rt, PointerType):
                    if is_void_type(lt.pointee) or is_void_type(rt.pointee) or types_equal(strip_top_qualifiers(lt.pointee), strip_top_qualifiers(rt.pointee)):
                        return BaseType(line=expr.line, col=expr.col, c_name='bool')
                if isinstance(lt, FunctionPointerType) and isinstance(rt, FunctionPointerType) and types_equal(strip_top_qualifiers(lt), strip_top_qualifiers(rt)):
                    return BaseType(line=expr.line, col=expr.col, c_name='bool')
                if (isinstance(lt, (PointerType, FunctionPointerType)) and self._is_null_ptr_const(expr.right, rt)) or (
                    isinstance(rt, (PointerType, FunctionPointerType)) and self._is_null_ptr_const(expr.left, lt)
                ):
                    return BaseType(line=expr.line, col=expr.col, c_name='bool')
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Invalid operands to equality operator '{op}'")
            if op in ('<', '<=', '>', '>='):
                if self._is_numeric_type(lt) and self._is_numeric_type(rt):
                    return BaseType(line=expr.line, col=expr.col, c_name='bool')
                if isinstance(lt, PointerType) and isinstance(rt, PointerType) and not is_void_type(lt.pointee) and types_equal(strip_top_qualifiers(lt.pointee), strip_top_qualifiers(rt.pointee)):
                    return BaseType(line=expr.line, col=expr.col, c_name='bool')
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Invalid operands to relational operator '{op}'")
            if op == '+':
                if self._is_numeric_type(lt) and self._is_numeric_type(rt):
                    return self._usual_arith_type(expr, lt, rt)
                if isinstance(lt, PointerType) and self._is_int_type(rt):
                    if not self._is_complete_object_type(lt.pointee):
                        raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Pointer addition requires pointer to complete object type")
                    return lt
                if self._is_int_type(lt) and isinstance(rt, PointerType):
                    if not self._is_complete_object_type(rt.pointee):
                        raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Pointer addition requires pointer to complete object type")
                    return rt
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Invalid operands to binary '+'")
            if op == '-':
                if self._is_numeric_type(lt) and self._is_numeric_type(rt):
                    return self._usual_arith_type(expr, lt, rt)
                if isinstance(lt, PointerType) and self._is_int_type(rt):
                    if not self._is_complete_object_type(lt.pointee):
                        raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Pointer subtraction requires pointer to complete object type")
                    return lt
                if isinstance(lt, PointerType) and isinstance(rt, PointerType):
                    if not self._is_complete_object_type(lt.pointee) or not types_equal(strip_top_qualifiers(lt.pointee), strip_top_qualifiers(rt.pointee)):
                        raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Pointer subtraction requires pointers to compatible complete object types")
                    return BaseType(line=expr.line, col=expr.col, c_name='ptrdiff_t')
                raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Invalid operands to binary '-'")
            if op in ('*', '/'):
                if not (self._is_numeric_type(lt) and self._is_numeric_type(rt)):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Operator '{op}' requires arithmetic operands")
                return self._usual_arith_type(expr, lt, rt)
            if op in ('%', '<<', '>>', '|', '&', '^'):
                if not (self._is_int_type(lt) and self._is_int_type(rt)):
                    raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Operator '{op}' requires integer operands")
                return self._usual_arith_type(expr, lt, rt)
            return lt

        return BaseType(line=expr.line, col=expr.col, c_name='int32_t')

    def _check_modifiable_lvalue(self, expr: ExprNode, op_tok: Token):
        if not isinstance(expr, (IdentExpr, IndexExpr, MemberExpr)) and not (isinstance(expr, UnaryExpr) and expr.op == '*'):
            raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Left-hand side of '{op_tok.value}' is not a modifiable lvalue")

        lhs_t = self._infer_expr_type(expr)
        if is_const_qualified(lhs_t):
            raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Cannot assign to const-qualified lvalue")
        if isinstance(lhs_t, ArrayType):
            raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Array type is not a modifiable lvalue")

    def _check_compound_assign_types(self, op_kind: str, lhs_t: TypeNode, rhs_t: TypeNode, op_tok: Token):
        """
        区分单纯赋值 (m,) 与算术复合赋值 (m+ / m- / m* / m/) 的类型规则:
        - m, (=): 遵循 types_compatible_for_assign(lhs_t, rhs_t)
        - m* (*=), m/ (/=): 左右两侧必须均为算术数值类型 (严禁指针参与 *= 或 /=)
        - m+ (+=), m- (-=): 允许 (数值 += 数值) 或 (非void指针 += 整型偏移)，严禁 (指针 += 指针)!
        """
        if op_kind == 'OP_ASSIGN':
            if not types_compatible_for_assign(lhs_t, rhs_t):
                raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Incompatible types in assignment 'm,'")
            return

        lhs_is_num = isinstance(lhs_t, BaseType) and (lhs_t.c_name in NUMERIC_C_TYPES or self.user_types.get(lhs_t.c_name) == 'enum')
        rhs_is_num = isinstance(rhs_t, BaseType) and (rhs_t.c_name in NUMERIC_C_TYPES or self.user_types.get(rhs_t.c_name) == 'enum')
        rhs_is_int = isinstance(rhs_t, BaseType) and (rhs_t.c_name in INT_C_TYPES or self.user_types.get(rhs_t.c_name) == 'enum')

        if op_kind in ('OP_MUL_ASSIGN', 'OP_DIV_ASSIGN'):
            if not (lhs_is_num and rhs_is_num):
                raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Operator '{op_tok.value}' requires numeric operands")
            return

        if op_kind in ('OP_ADD_ASSIGN', 'OP_SUB_ASSIGN'):
            if lhs_is_num and rhs_is_num:
                return
            if isinstance(lhs_t, PointerType) and rhs_is_int:
                if not self._is_complete_object_type(lhs_t.pointee):
                    raise SemanticError(
                        f"{self.filename}:{op_tok.line}:{op_tok.col}: Pointer arithmetic '{op_tok.value}' requires pointer to a complete object type"
                    )
                return
            raise SemanticError(
                f"{self.filename}:{op_tok.line}:{op_tok.col}: Invalid operands to '{op_tok.value}' (pointer += pointer or non-integer pointer offset is forbidden)"
            )

    def _is_int_type(self, t: TypeNode) -> bool:
        return isinstance(t, BaseType) and (t.c_name in INT_C_TYPES or self.user_types.get(t.c_name) == 'enum')

    def _is_numeric_type(self, t: TypeNode) -> bool:
        return isinstance(t, BaseType) and (t.c_name in NUMERIC_C_TYPES or self.user_types.get(t.c_name) == 'enum')

    def _is_scalar_type(self, t: TypeNode) -> bool:
        t_dec = self._decay_rvalue(t)
        return self._is_numeric_type(t_dec) or isinstance(t_dec, (PointerType, FunctionPointerType))

    def _decay_rvalue(self, t: TypeNode) -> TypeNode:
        if isinstance(t, ArrayType):
            return PointerType(line=t.line, col=t.col, pointee=t.element_type, is_const=False)
        return t

    def _try_const(self, expr: ExprNode) -> Optional[int]:
        try:
            return self._eval_const_int_expr(expr)
        except SemanticError:
            return None

    def _param_name(self, expr: Optional[ExprNode]) -> Optional[str]:
        """若表达式根上是一个参数名，返回它；用于 --strict 的"来源未知"诊断。"""
        if expr is None:
            return None
        if isinstance(expr, IdentExpr):
            return expr.name if expr.name in self.param_names else None
        if isinstance(expr, BinaryExpr):
            return self._param_name(expr.left)
        if isinstance(expr, CastExpr):
            return self._param_name(expr.operand)
        if isinstance(expr, IndexExpr):
            return self._param_name(expr.base)
        if isinstance(expr, MemberExpr):
            return self._param_name(expr.base)
        return None

    def _prov_of(self, expr: Optional[ExprNode]) -> Optional[Prov]:
        """指针来源：(基对象, 元素个数, 相对基对象的偏移, 基对象作用域深度)。推不出来返回 None。"""
        if expr is None:
            return None
        call_prov = getattr(expr, "_call_prov", None)
        if call_prov is not None:
            return call_prov
        if isinstance(expr, IdentExpr):
            return self.prov.get(expr.name)
        if isinstance(expr, CastExpr):
            return None
        if isinstance(expr, UnaryExpr) and expr.op == '&':
            inner = expr.operand
            if isinstance(inner, IdentExpr):
                return self.prov.get(inner.name)
            if isinstance(inner, IndexExpr):
                base = self._prov_of(inner.base)
                idx = self._try_const(inner.index)
                if base is not None and idx is not None:
                    return Prov(base.base, base.size, base.offset + idx, base.depth)
            return None
        if isinstance(expr, BinaryExpr) and expr.op in ('+', '-'):
            left = self._prov_of(expr.left)
            if left is not None:
                k = self._try_const(expr.right)
                if k is not None:
                    return Prov(left.base, left.size,
                                left.offset + k if expr.op == '+' else left.offset - k, left.depth)
            if expr.op == '+':
                right = self._prov_of(expr.right)
                if right is not None:
                    k = self._try_const(expr.left)
                    if k is not None:
                        return Prov(right.base, right.size, right.offset + k, right.depth)
        return None

    def _prov_live(self, prov: Optional[Prov], expr: ExprNode) -> Optional[Prov]:
        """来源的基对象必须还在作用域内；否则指针已经悬垂。"""
        if prov is None:
            return None
        if prov.depth >= len(self.scopes):
            raise SemanticError(
                f"{self.filename}:{expr.line}:{expr.col}: Pointer refers to '{prov.base}', which is out of scope here")
        return prov

    def _address_of_local(self, expr: Optional[ExprNode]) -> Optional[str]:
        if isinstance(expr, UnaryExpr) and expr.op == '&':
            inner = expr.operand
            if isinstance(inner, IdentExpr) and inner.name in self.local_objects:
                return inner.name
            if isinstance(inner, MemberExpr) and isinstance(inner.base, IdentExpr) \
                    and inner.base.name in self.local_objects:
                return inner.base.name
        return None

    def _param_source(self, expr: Optional[ExprNode]) -> Optional[str]:
        """表达式是否携带某个形参的地址/指针值（跨函数逃逸摘要用）。"""
        if expr is None:
            return None
        if isinstance(expr, IdentExpr) and expr.name in self.param_names:
            return expr.name
        if isinstance(expr, UnaryExpr) and expr.op == '&':
            inner = expr.operand
            if isinstance(inner, IdentExpr) and inner.name in self.param_names:
                return inner.name
            if isinstance(inner, IndexExpr) and isinstance(inner.base, IdentExpr) \
                    and inner.base.name in self.param_names:
                return inner.base.name
        p = self._prov_of(expr)
        if p is not None and p.base in self.param_names:
            return p.base
        return None

    def _target_is_global(self, lhs: ExprNode) -> bool:
        return isinstance(lhs, IdentExpr) and lhs.name in self.scopes[0] and lhs.name not in self.local_objects

    def _check_restricted_base(self, expr: ExprNode) -> None:
        if isinstance(expr, IdentExpr) and expr.name in self.restricted:
            if self.restricted[expr.name] < len(self.scopes):
                raise SemanticError(
                    f"{self.filename}:{expr.line}:{expr.col}: '{expr.name}' is accessed through another path while a "
                    f"'r@' (restrict) pointer claims exclusive access to it")

    def _check_calls(self) -> None:
        for fname, provs, line, col in self.pending_calls:
            sig = self.func_sigs.get(fname)
            if sig is None:
                continue
            params = sig[0]
            esc = self.escape_params.get(fname, set())
            pnames = self.func_param_names.get(fname, [])
            if esc:
                for idx, (_arg, prov) in enumerate(provs):
                    if idx >= len(pnames) or pnames[idx] not in esc:
                        continue
                    if prov is not None and prov.depth >= 1:
                        raise SemanticError(
                            f"{self.filename}:{line}:{col}: Argument {idx + 1} of '{fname}' points to local object "
                            f"'{prov.base}', but '{fname}' stores it into a global; it would dangle after this function returns")
            for i, pt in enumerate(params):
                if not (isinstance(pt, PointerType) and pt.is_restrict):
                    continue
                if i >= len(provs):
                    continue
                prov_i = provs[i][1]
                if prov_i is None:
                    continue
                base_i = prov_i.base
                for j, (_a2, p2) in enumerate(provs):
                    if j == i or p2 is None:
                        continue
                    if p2.base == base_i:
                        raise SemanticError(
                            f"{self.filename}:{line}:{col}: Parameter {i + 1} of '{fname}' is 'r@' (restrict) but "
                            f"argument {j + 1} aliases the same object '{base_i}'")

    def _note_prov(self, name: str, decl_type: TypeNode, init_expr: Optional[ExprNode]) -> None:
        if self._prov_saved:
            frame = self._prov_saved[-1]
            if name not in frame:
                frame[name] = self.prov.get(name)
        depth = len(self.scopes) - 1
        if isinstance(decl_type, ArrayType) and decl_type.size_val is not None:
            self.prov[name] = Prov(name, decl_type.size_val, 0, depth)
            return
        if isinstance(strip_top_qualifiers(decl_type), PointerType):
            p = self._prov_of(init_expr)
            if p is not None and init_expr is not None:
                p = self._prov_live(p, init_expr)
            if p is not None:
                self.prov[name] = p
            else:
                self.prov.pop(name, None)
            return
        # 标量/结构体对象本身：把它的地址当作一个元素的来源
        self.prov[name] = Prov(name, 1, 0, depth)

    def _member_is_bitfield(self, me: MemberExpr) -> bool:
        try:
            base_t = self._infer_expr_type(me.base)
        except SemanticError:
            return False
        if me.is_arrow:
            if not isinstance(base_t, PointerType) or not isinstance(base_t.pointee, BaseType):
                return False
            sname = base_t.pointee.c_name
        else:
            if not isinstance(base_t, BaseType):
                return False
            sname = base_t.c_name
        return me.field in self.struct_bitfields.get(sname, {})

    def _is_null_ptr_const(self, expr: ExprNode, expr_t: TypeNode) -> bool:
        if isinstance(expr, LiteralExpr) and expr.lit_kind == 'NULL':
            return True
        if not self._is_int_type(expr_t):
            return False
        try:
            return self._eval_const_int_expr(expr) == 0
        except SemanticError:
            return False

    def _usual_arith_type(self, expr: ExprNode, a: TypeNode, b: TypeNode) -> BaseType:
        assert isinstance(a, BaseType) and isinstance(b, BaseType)
        names = {a.c_name, b.c_name}
        if 'long double' in names:
            return BaseType(line=expr.line, col=expr.col, c_name='long double')
        if 'double' in names:
            return BaseType(line=expr.line, col=expr.col, c_name='double')
        if 'float' in names:
            return BaseType(line=expr.line, col=expr.col, c_name='float')
        if 'uint64_t' in names or 'size_t' in names or 'uintptr_t' in names:
            return BaseType(line=expr.line, col=expr.col, c_name='uint64_t')
        if 'int64_t' in names or 'ptrdiff_t' in names or 'intptr_t' in names:
            return BaseType(line=expr.line, col=expr.col, c_name='int64_t')
        if 'uint32_t' in names:
            return BaseType(line=expr.line, col=expr.col, c_name='uint32_t')
        return BaseType(line=expr.line, col=expr.col, c_name='int32_t')

    def _check_assign_compatible(self, expected: TypeNode, rhs_expr: ExprNode, actual: TypeNode) -> bool:
        if types_compatible_for_assign(expected, actual):
            return True
        if self._is_numeric_type(expected) and self._is_numeric_type(actual):
            return True
        if isinstance(strip_top_qualifiers(expected), (PointerType, FunctionPointerType)) and self._is_null_ptr_const(rhs_expr, actual):
            return True
        return False

    def _check_scalar_cond(self, cond: ExprNode, kw_name: str):
        ct = self._infer_expr_type(cond)
        if not self._is_scalar_type(ct):
            raise SemanticError(f"{self.filename}:{cond.line}:{cond.col}: Controlling expression of '{kw_name}' must have scalar type")

    def _register_macro_constant(self, ptok: Token):
        """把 `#define NAME <字面量>` 里的名字登记成常量，使 `.sigil` 表达式可以直接用它。
        函数式宏与复杂宏体只透传到生成代码，不在此登记。"""
        m = re.match(r'#\s*define\s+([A-Za-z_]\w*)\s+(.+?)\s*$', ptok.value.strip())
        if not m:
            return
        name, body = m.group(1), m.group(2)
        body = body.split('/*')[0].split('//')[0].strip()
        if not body:
            return
        if name in self.scopes[0]:
            return
        ln, cl = ptok.line, ptok.col
        if body.startswith('"'):
            self.scopes[0][name] = PointerType(ln, cl, BaseType(ln, cl, 'char', is_const=True))
            return
        if body.startswith("'"):
            self.scopes[0][name] = BaseType(ln, cl, 'char')
            return
        raw = body.rstrip('uUlL')
        try:
            if body.startswith(('0x', '0X', '0b', '0B')):
                val = int(raw, 0)
            elif body.startswith('0') and len(body) > 1 and body.isdigit():
                val = int(body, 8)
            else:
                val = int(raw, 10)
            self.macro_consts[name] = val
            self.scopes[0][name] = BaseType(ln, cl, 'uint32_t' if body.lower().endswith('u') else 'int32_t')
            return
        except ValueError:
            pass
        try:
            float(body.rstrip('fFlL'))
            self.scopes[0][name] = BaseType(ln, cl, 'float' if body.lower().endswith('f') else 'double')
        except ValueError:
            pass

    def _register_c99_header_builtins(self, ptok: Token):
        txt = ptok.value.replace(" ", "")
        ln, cl = ptok.line, ptok.col
        t_int = BaseType(ln, cl, 'int')
        t_void = BaseType(ln, cl, 'void')
        t_size = BaseType(ln, cl, 'size_t')
        t_cstr = PointerType(ln, cl, BaseType(ln, cl, 'char', is_const=True))
        t_vptr = PointerType(ln, cl, BaseType(ln, cl, 'void'))
        t_cvptr = PointerType(ln, cl, BaseType(ln, cl, 'void', is_const=True))
        t_buf = PointerType(ln, cl, BaseType(ln, cl, 'char'))
        t_u32 = BaseType(ln, cl, 'uint32_t')
        t_double = BaseType(ln, cl, 'double')

        def reg_fn(name: str, params: List[TypeNode], ret: TypeNode, variadic: bool = False):
            if name not in self.scopes[0]:
                self.scopes[0][name] = FunctionPointerType(ln, cl, [(p, f"p{i}") for i, p in enumerate(params)], ret, is_variadic=variadic)
                if not variadic:
                    self.func_sigs[name] = (params, ret)

        if '<stdio.h>' in txt:
            # FILE 是 C 的 opaque 句柄：只登记类型名，不登记字段
            if 'FILE' not in self.user_types:
                self.user_types['FILE'] = 'external'
                EXTERNAL_C_SPELLING['FILE'] = 'FILE'
            t_file = PointerType(ln, cl, BaseType(ln, cl, 'FILE'))
            for stream in ('stdin', 'stdout', 'stderr'):
                self.scopes[0].setdefault(stream, t_file)
            reg_fn('fopen', [t_cstr, t_cstr], t_file)
            reg_fn('freopen', [t_cstr, t_cstr, t_file], t_file)
            reg_fn('fclose', [t_file], t_int)
            reg_fn('fflush', [t_file], t_int)
            reg_fn('fread', [t_vptr, t_size, t_size, t_file], t_size)
            reg_fn('fwrite', [t_cvptr, t_size, t_size, t_file], t_size)
            reg_fn('fgets', [t_buf, t_int, t_file], t_buf)
            reg_fn('fputs', [t_cstr, t_file], t_int)
            reg_fn('fgetc', [t_file], t_int)
            reg_fn('fputc', [t_int, t_file], t_int)
            reg_fn('feof', [t_file], t_int)
            reg_fn('fprintf', [t_file, t_cstr], t_int, variadic=True)
            reg_fn('remove', [t_cstr], t_int)
            reg_fn('rename', [t_cstr, t_cstr], t_int)
            reg_fn('printf', [t_cstr], t_int, variadic=True)
            reg_fn('scanf', [t_cstr], t_int, variadic=True)
            reg_fn('getchar', [], t_int)
            reg_fn('sprintf', [t_buf, t_cstr], t_int, variadic=True)
            reg_fn('snprintf', [t_buf, t_size, t_cstr], t_int, variadic=True)
            reg_fn('sscanf', [t_cstr, t_cstr], t_int, variadic=True)
            reg_fn('puts', [t_cstr], t_int)
            reg_fn('putchar', [t_int], t_int)
        if '<stdlib.h>' in txt:
            reg_fn('malloc', [t_size], t_vptr)
            reg_fn('calloc', [t_size, t_size], t_vptr)
            reg_fn('free', [t_vptr], t_void)
            reg_fn('exit', [t_int], t_void)
            reg_fn('abort', [], t_void)
            reg_fn('atoi', [t_cstr], t_int)
            reg_fn('qsort', [t_vptr, t_size, t_size, FunctionPointerType(ln, cl, [(t_cvptr, "a"), (t_cvptr, "b")], BaseType(ln, cl, 'int32_t'))], t_void)
            reg_fn('rand', [], t_int)
            reg_fn('srand', [t_u32], t_void)
            reg_fn('getenv', [t_cstr], t_buf)
        if '<string.h>' in txt:
            reg_fn('memcpy', [t_vptr, t_cvptr, t_size], t_vptr)
            reg_fn('memmove', [t_vptr, t_cvptr, t_size], t_vptr)
            reg_fn('memset', [t_vptr, t_int, t_size], t_vptr)
            reg_fn('memcmp', [t_cvptr, t_cvptr, t_size], t_int)
            reg_fn('strlen', [t_cstr], t_size)
            reg_fn('strcpy', [t_buf, t_cstr], t_buf)
            reg_fn('strncpy', [t_buf, t_cstr, t_size], t_buf)
            reg_fn('strcat', [t_buf, t_cstr], t_buf)
            reg_fn('strcmp', [t_cstr, t_cstr], t_int)
            reg_fn('strncmp', [t_cstr, t_cstr, t_size], t_int)
            reg_fn('strchr', [t_cstr, t_int], t_buf)
            reg_fn('strrchr', [t_cstr, t_int], t_buf)
            reg_fn('strstr', [t_cstr, t_cstr], t_buf)
        if '<ctype.h>' in txt:
            for name in ('isalnum', 'isalpha', 'isdigit', 'islower', 'isspace',
                         'isupper', 'isxdigit'):
                reg_fn(name, [t_int], t_int)
            reg_fn('tolower', [t_int], t_int)
            reg_fn('toupper', [t_int], t_int)
        if '<math.h>' in txt:
            for name in ('sqrt', 'fabs', 'sin', 'cos', 'tan', 'exp', 'log', 'floor', 'ceil'):
                reg_fn(name, [t_double], t_double)
            reg_fn('pow', [t_double, t_double], t_double)
            reg_fn('fmod', [t_double, t_double], t_double)
        if '<assert.h>' in txt:
            reg_fn('assert', [t_int], t_void)

    def _sequence_flow(self, stmts: List[StmtNode]) -> Set[str]:
        outcomes = {"fallthrough"}
        for stmt in stmts:
            if "fallthrough" not in outcomes:
                break
            outcomes = (outcomes - {"fallthrough"}) | self._statement_flow(stmt)
        return outcomes

    def _statement_flow(self, stmt: StmtNode) -> Set[str]:
        """Possible exits from a statement: return, break, continue, or fallthrough."""
        if isinstance(stmt, TrapStmt):
            return {"return"}
        if isinstance(stmt, ReturnStmt):
            return {"return"}
        if isinstance(stmt, JumpStmt):
            return {stmt.keyword}
        if isinstance(stmt, BlockStmt):
            return self._sequence_flow(stmt.stmts)
        if isinstance(stmt, IfStmt):
            outcomes = self._statement_flow(stmt.then_block)
            if stmt.else_branch is None:
                outcomes.add("fallthrough")
            else:
                outcomes |= self._statement_flow(stmt.else_branch)
            return outcomes
        if isinstance(stmt, SwitchStmt):
            outcomes = set()
            has_default = any(case.value is None for case in stmt.cases)
            for start in range(len(stmt.cases)):
                case_outcomes = {"fallthrough"}
                for case in stmt.cases[start:]:
                    if "fallthrough" not in case_outcomes:
                        break
                    case_outcomes = (case_outcomes - {"fallthrough"}) | self._sequence_flow(case.stmts)
                if "break" in case_outcomes:
                    case_outcomes = (case_outcomes - {"break"}) | {"fallthrough"}
                outcomes |= case_outcomes
            if not has_default:
                outcomes.add("fallthrough")
            return outcomes
        if isinstance(stmt, (WhileStmt, ForStmt)):
            body_outcomes = self._statement_flow(stmt.body)
            cond = stmt.cond if isinstance(stmt, WhileStmt) else stmt.cond_expr
            always_true = cond is None
            if cond is not None:
                try:
                    cond_value = self._eval_const_int_expr(cond)
                except SemanticError:
                    cond_value = None
                always_true = cond_value is not None and cond_value != 0
            outcomes = set()
            if "return" in body_outcomes:
                outcomes.add("return")
            if not always_true or "break" in body_outcomes:
                outcomes.add("fallthrough")
            return outcomes
        return {"fallthrough"}

    def _can_fall_through(self, stmt: StmtNode) -> bool:
        return "fallthrough" in self._statement_flow(stmt)

    def _is_static_arithmetic_const_expr(self, expr: ExprNode) -> bool:
        if self._eval_const_int_expr(expr) is not None:
            return True
        if isinstance(expr, LiteralExpr):
            return expr.lit_kind in ('INT_NUM', 'FLOAT_NUM', 'CHAR')
        if isinstance(expr, IdentExpr):
            return expr.name in self.enum_constants
        if isinstance(expr, CastExpr):
            return self._is_numeric_type(expr.target_type) and self._is_static_arithmetic_const_expr(expr.operand)
        if isinstance(expr, UnaryExpr) and expr.op in ('+', '-', '!', '~'):
            return self._is_static_arithmetic_const_expr(expr.operand) and self._is_numeric_type(self._infer_expr_type(expr))
        if isinstance(expr, BinaryExpr):
            return (
                self._is_static_arithmetic_const_expr(expr.left)
                and self._is_static_arithmetic_const_expr(expr.right)
                and self._is_numeric_type(self._infer_expr_type(expr))
            )
        if isinstance(expr, TernaryExpr):
            return (
                self._is_static_arithmetic_const_expr(expr.cond)
                and self._is_static_arithmetic_const_expr(expr.then_expr)
                and self._is_static_arithmetic_const_expr(expr.else_expr)
                and self._is_numeric_type(self._infer_expr_type(expr))
            )
        return False

    def _is_static_const_init(self, expr: ExprNode) -> bool:
        if self._eval_const_int_expr(expr) is not None:
            return True
        if self._is_static_arithmetic_const_expr(expr):
            return True
        if isinstance(expr, LiteralExpr) and expr.lit_kind in ('FLOAT_NUM', 'STRING', 'CHAR', 'BOOL', 'NULL'):
            return True
        if isinstance(expr, AggregateInit):
            return all(self._is_static_const_init(e) for e in expr.elements)
        if isinstance(expr, (DesignatedInit, DesignatedIndex)):
            return self._is_static_const_init(expr.value)
        if isinstance(expr, CompoundLiteral):
            return self._is_static_const_init(expr.init)
        if isinstance(expr, CastExpr):
            return self._is_static_const_init(expr.operand)
        if isinstance(expr, UnaryExpr) and expr.op in ('-', '+'):
            return self._is_static_const_init(expr.operand)
        if isinstance(expr, UnaryExpr) and expr.op == '&' and isinstance(expr.operand, IdentExpr):
            return expr.operand.name in self.scopes[0]
        if isinstance(expr, IdentExpr) and expr.name in self.func_sigs:
            return True
        return False

    def _is_complete_object_type(self, t: TypeNode) -> bool:
        if isinstance(t, BaseType):
            if t.c_name == 'void':
                return False
            if t.c_name == 'va_list':
                return True
            if t.c_name in NUMERIC_C_TYPES or self.user_types.get(t.c_name) == 'enum':
                return True
            if t.c_name in self.user_types:
                return t.c_name in self.complete_structs
            return False
        if isinstance(t, (PointerType, FunctionPointerType)):
            return True
        if isinstance(t, ArrayType):
            return self._is_complete_object_type(t.element_type)
        return False

    def _resolve_ternary_type(self, expr: TernaryExpr, t_then: TypeNode, t_else: TypeNode) -> TypeNode:
        then_num = isinstance(t_then, BaseType) and (t_then.c_name in NUMERIC_C_TYPES or self.user_types.get(t_then.c_name) == 'enum')
        else_num = isinstance(t_else, BaseType) and (t_else.c_name in NUMERIC_C_TYPES or self.user_types.get(t_else.c_name) == 'enum')
        if then_num and else_num:
            assert isinstance(t_then, BaseType) and isinstance(t_else, BaseType)
            names = {t_then.c_name, t_else.c_name}
            if 'long double' in names:
                return BaseType(line=expr.line, col=expr.col, c_name='long double')
            if 'double' in names:
                return BaseType(line=expr.line, col=expr.col, c_name='double')
            if 'float' in names:
                return BaseType(line=expr.line, col=expr.col, c_name='float')
            if 'uint64_t' in names:
                return BaseType(line=expr.line, col=expr.col, c_name='uint64_t')
            if 'int64_t' in names:
                return BaseType(line=expr.line, col=expr.col, c_name='int64_t')
            if 'uint32_t' in names:
                return BaseType(line=expr.line, col=expr.col, c_name='uint32_t')
            return BaseType(line=expr.line, col=expr.col, c_name='int32_t')

        if isinstance(t_then, PointerType) and isinstance(t_else, PointerType):
            p1, p2 = t_then.pointee, t_else.pointee
            merged_const = is_const_qualified(p1) or is_const_qualified(p2)
            merged_volatile = is_volatile_qualified(p1) or is_volatile_qualified(p2)
            if types_equal(strip_top_qualifiers(p1), strip_top_qualifiers(p2)):
                pt = strip_top_qualifiers(p1)
                if merged_const:
                    pt = with_const(pt)
                if merged_volatile:
                    pt = with_volatile(pt)
                return PointerType(line=expr.line, col=expr.col, pointee=pt)
            if is_void_type(p1) or is_void_type(p2):
                v_base = BaseType(line=expr.line, col=expr.col, c_name='void', is_const=merged_const, is_volatile=merged_volatile)
                return PointerType(line=expr.line, col=expr.col, pointee=v_base)

        try:
            then_zero = then_num and self._eval_const_int_expr(expr.then_expr) == 0
        except SemanticError:
            then_zero = False
        try:
            else_zero = else_num and self._eval_const_int_expr(expr.else_expr) == 0
        except SemanticError:
            else_zero = False

        if isinstance(t_then, (PointerType, FunctionPointerType)) and else_zero:
            return strip_top_qualifiers(t_then)
        if isinstance(t_else, (PointerType, FunctionPointerType)) and then_zero:
            return strip_top_qualifiers(t_else)

        if types_equal(strip_top_qualifiers(t_then), strip_top_qualifiers(t_else)):
            if is_const_qualified(t_then) or is_const_qualified(t_else):
                result_t = with_const(strip_top_qualifiers(t_then))
            else:
                result_t = strip_top_qualifiers(t_then)
            if is_volatile_qualified(t_then) or is_volatile_qualified(t_else):
                result_t = with_volatile(result_t)
            return result_t

        raise SemanticError(f"{self.filename}:{expr.line}:{expr.col}: Incompatible branch types in ternary conditional expression")

    def parse_type(self) -> TypeNode:
        tok = self._cur()
        is_const = False
        is_volatile = False
        is_restrict = False
        while self._cur().kind in ('KW_CONST', 'KW_VOLATILE', 'KW_RESTRICT'):
            qualifier_tok = self._eat()
            if qualifier_tok.kind == 'KW_CONST':
                is_const = True
            elif qualifier_tok.kind == 'KW_VOLATILE':
                is_volatile = True
            else:
                is_restrict = True
        tok = self._cur()

        if tok.kind == 'KW_PTR':
            ptr_tok = self._eat('KW_PTR')
            base_node: TypeNode = PointerType(line=ptr_tok.line, col=ptr_tok.col, pointee=self.parse_type(), is_const=is_const, is_volatile=is_volatile, is_restrict=is_restrict)
        elif tok.kind == 'KW_FNPTR':
            fn_tok = self._eat('KW_FNPTR')
            self._eat('LPAREN')
            params: List[Tuple[TypeNode, Optional[str]]] = []
            seen_pnames = set()
            is_variadic = False
            if self._cur().kind == 'TYPE_VOID' and self.tokens[self.pos + 1].kind == 'RPAREN':
                self._eat('TYPE_VOID')
            elif self._cur().kind != 'RPAREN':
                while True:
                    if self._cur().kind == 'ELLIPSIS':
                        if not params:
                            raise SemanticError(
                                f"{self.filename}:{self._cur().line}:{self._cur().col}: "
                                f"A variadic function pointer requires at least one named parameter before '...'")
                        self._eat('ELLIPSIS')
                        is_variadic = True
                        break
                    pt = decay_parameter_type(self.parse_type())
                    self._validate_non_void_var(pt, fn_tok)
                    pname = None
                    if self._cur().kind == 'IDENT':
                        ptok = self._eat('IDENT')
                        if ptok.value in seen_pnames:
                            raise SemanticError(f"{self.filename}:{ptok.line}:{ptok.col}: Duplicate parameter '{ptok.value}' in function pointer")
                        seen_pnames.add(ptok.value)
                        pname = ptok.value
                    params.append((pt, pname))
                    if self._cur().kind == 'COMMA':
                        self._eat('COMMA')
                    else:
                        break
            self._eat('RPAREN')
            self._eat('ARROW')
            ret_type = self.parse_type()
            if isinstance(ret_type, ArrayType):
                raise SemanticError(f"{self.filename}:{fn_tok.line}:{fn_tok.col}: Function cannot return array type")
            base_node = FunctionPointerType(line=fn_tok.line, col=fn_tok.col, param_decls=params, return_type=ret_type, is_const=is_const, is_volatile=is_volatile, is_variadic=is_variadic)
        elif tok.kind in ('TYPE_INT', 'TYPE_VOID', 'TYPE_BOOL'):
            t_tok = self._eat()
            c_map = {**BASIC_TYPES, 'v.': 'void', 'b.': 'bool'}
            base_node = BaseType(line=t_tok.line, col=t_tok.col, c_name=c_map[t_tok.value], is_const=is_const, is_volatile=is_volatile)
        elif tok.kind == 'IDENT' and tok.value in self.user_types:
            t_tok = self._eat('IDENT')
            base_node = BaseType(line=t_tok.line, col=t_tok.col, c_name=t_tok.value, is_const=is_const, is_volatile=is_volatile)
        elif tok.kind == 'LPAREN':
            self._eat('LPAREN')
            base_node = self.parse_type()
            self._eat('RPAREN')
            if is_const:
                base_node = with_const(base_node)
            if is_volatile:
                base_node = with_volatile(base_node)
        else:
            raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: Expected type specifier, got '{tok.value}'")

        if is_restrict:
            if isinstance(base_node, PointerType):
                base_node = PointerType(line=base_node.line, col=base_node.col, pointee=base_node.pointee,
                                        is_const=base_node.is_const, is_volatile=base_node.is_volatile,
                                        is_restrict=True)
            else:
                raise SemanticError(
                    f"{self.filename}:{tok.line}:{tok.col}: 'r@' (restrict) can only qualify a pointer type")

        dims: List[Tuple[ExprNode, int]] = []
        while self._cur().kind == 'LBRACK':
            lb = self._eat('LBRACK')
            if is_void_type(base_node) or not self._is_complete_object_type(base_node):
                raise SemanticError(f"{self.filename}:{lb.line}:{lb.col}: Cannot declare array of incomplete or 'v.' (void) type")
            dim_e = self.parse_pure_expr()
            c_val = self._eval_const_int_expr(dim_e)
            if c_val is None or c_val <= 0:
                raise SemanticError(f"{self.filename}:{lb.line}:{lb.col}: Array size must be a positive integer constant expression")
            self._eat('RBRACK')
            dims.append((dim_e, c_val))

        for d_expr, d_val in reversed(dims):
            base_node = ArrayType(line=tok.line, col=tok.col, element_type=base_node, size_expr=d_expr, size_val=d_val)

        return base_node

    def parse_program(self) -> List[StmtNode]:
        top_nodes: List[StmtNode] = []
        while self._cur().kind != 'EOF':
            attrs: List[Attribute] = []
            if self._cur().kind == 'KW_ATTR':
                attrs = self.parse_attrs()
            if self._cur().kind == 'PREPROC':
                if attrs:
                    tok = self._cur()
                    raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: 'a@' attributes cannot precede a preprocessor directive")
                ptok = self._eat('PREPROC')
                self._register_c99_header_builtins(ptok)
                self._register_macro_constant(ptok)
                top_nodes.append(PreprocNode(line=ptok.line, col=ptok.col, text=ptok.value))
            elif self._cur().kind == 'KW_EXTERNAL':
                top_nodes.append(self.parse_external())
            elif self._cur().kind in ('KW_STRUCT', 'KW_UNION'):
                top_nodes.append(self.parse_struct_or_union(attrs=attrs))
            elif self._cur().kind == 'KW_ENUM':
                if attrs:
                    tok = self._cur()
                    raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'a@' attributes are not supported on 'e{{' enum definitions")
                top_nodes.append(self.parse_enum())
            elif self._cur().kind == 'KW_STATIC_ASSERT':
                top_nodes.append(self.parse_static_assert())
            elif self._cur().kind == 'KW_OBJECT':
                object_tok = self._eat('KW_OBJECT')
                top_nodes.append(self.parse_top_decl_or_func(object_marker=object_tok, attrs=attrs))
            elif self._cur().kind in ('KW_STATIC', 'KW_INLINE'):
                is_static = False
                is_inline = False
                while self._cur().kind in ('KW_STATIC', 'KW_INLINE'):
                    mod_tok = self._eat()
                    if mod_tok.kind == 'KW_STATIC':
                        if is_static:
                            raise ParseError(f"{self.filename}:{mod_tok.line}:{mod_tok.col}: Duplicate 's@' storage class")
                        is_static = True
                    else:
                        if is_inline:
                            raise ParseError(f"{self.filename}:{mod_tok.line}:{mod_tok.col}: Duplicate 'i@' specifier")
                        is_inline = True
                if self._cur().kind == 'KW_OBJECT':
                    if is_inline:
                        raise SemanticError(
                            f"{self.filename}:{self._cur().line}:{self._cur().col}: 'i@' (inline) cannot be applied to an object declaration")
                    object_tok = self._eat('KW_OBJECT')
                    top_nodes.append(self.parse_top_decl_or_func(object_marker=object_tok, is_static=is_static, attrs=attrs))
                elif self._is_type_start(self._cur()):
                    top_nodes.append(self.parse_top_decl_or_func(is_static=is_static, is_inline=is_inline, attrs=attrs))
                else:
                    tok = self._cur()
                    raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: 's@' / 'i@' must be followed by a function, got '{tok.value}'")
            elif self._is_type_start(self._cur()):
                top_nodes.append(self.parse_top_decl_or_func(attrs=attrs))
            else:
                tok = self._cur()
                raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: Unexpected top-level token '{tok.value}'")
        self._check_calls()
        return top_nodes

    def _check_compound_init(self, target: TypeNode, init: AggregateInit, name_tok: Token):
        is_aggregate = isinstance(target, ArrayType) or (
            isinstance(target, BaseType) and self.user_types.get(target.c_name) in ('struct', 'union'))
        if is_aggregate:
            self._check_brace_init(target, init, name_tok)
            return
        if len(init.elements) != 1 or isinstance(init.elements[0], (DesignatedInit, DesignatedIndex, AggregateInit)):
            raise SemanticError(
                f"{self.filename}:{init.line}:{init.col}: A scalar compound literal takes exactly one plain value, "
                f"e.g. (u4){{ 5 }}")
        elem = init.elements[0]
        et = self._infer_expr_type(elem)
        if not self._check_assign_compatible(target, elem, et):
            raise SemanticError(
                f"{self.filename}:{elem.line}:{elem.col}: Incompatible compound literal value: "
                f"expected '{format_c_declarator(target)}', got '{format_c_declarator(et)}'")

    def _check_bitfield_base(self, tok: Token, ft: TypeNode):
        if not isinstance(ft, BaseType) or ft.c_name not in BITFIELD_WIDTH:
            raise SemanticError(
                f"{self.filename}:{tok.line}:{tok.col}: 'w!' bit-field requires an integer base type, "
                f"got '{format_c_declarator(ft)}'")

    def parse_external(self) -> ExternalTypeNode:
        """`x!` 外部类型：不生成定义，只登记字段供转译期检查。

        x! struct sockaddr_in { u2 sin_family; ... };   /* C 里写作 struct sockaddr_in */
        x! pthread_t;                                   /* typedef 型不透明句柄 */
        """
        kw = self._eat('KW_EXTERNAL')
        c_prefix = ''
        if self._cur().kind == 'IDENT' and self._cur().value in ('struct', 'union', 'enum'):
            c_prefix = self._eat('IDENT').value
        name_tok = self._eat('IDENT')
        sigil_name = name_tok.value
        c_spelling = f"{c_prefix} {sigil_name}" if c_prefix else sigil_name
        if sigil_name in self.user_types:
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: '{sigil_name}' is already declared")
        if self._cur().kind == 'SEMI':
            self._eat('SEMI')
            if c_prefix == 'enum':
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: an external enum needs its constants declared separately")
            self.user_types[sigil_name] = c_prefix or 'struct'
            EXTERNAL_C_SPELLING[sigil_name] = c_spelling
            return ExternalTypeNode(line=kw.line, col=kw.col, name=sigil_name,
                                    c_spelling=c_spelling, opaque=True)
        if c_prefix == 'enum':
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: external enums cannot carry a field list")
        self._eat('LBRACE')
        fields: Dict[str, TypeNode] = {}
        count = 0
        while self._cur().kind != 'RBRACE':
            ft = self.parse_type()
            fname_tok = self._eat('IDENT')
            if self._cur().kind == 'KW_BITFIELD':
                bf_tok = self._eat('KW_BITFIELD')
                w_tok = self._eat('INT_NUM')
                width = self._attr_int_value(w_tok, w_tok.value)
                self._check_bitfield_base(bf_tok, ft)
                assert isinstance(ft, BaseType)
                limit = BITFIELD_WIDTH[ft.c_name]
                if width < 1 or width > limit:
                    raise SemanticError(
                        f"{self.filename}:{bf_tok.line}:{bf_tok.col}: 'w!{width}' out of range for '{ft.c_name}': "
                        f"width must be 1..{limit}")
                self.struct_bitfields.setdefault(sigil_name, {})[fname_tok.value] = width
            self._validate_non_void_var(ft, fname_tok)
            if not self._is_complete_object_type(ft):
                raise SemanticError(
                    f"{self.filename}:{fname_tok.line}:{fname_tok.col}: Field '{fname_tok.value}' has incomplete type")
            if fname_tok.value in fields:
                raise SemanticError(
                    f"{self.filename}:{fname_tok.line}:{fname_tok.col}: Duplicate field '{fname_tok.value}' "
                    f"in external type '{sigil_name}'")
            fields[fname_tok.value] = ft
            self._eat('SEMI')
            count += 1
        if count == 0:
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: empty external type; write 'x! {sigil_name};' for an opaque handle")
        self._eat('RBRACE')
        self._eat('SEMI')
        self.user_types[sigil_name] = c_prefix or 'struct'
        self.struct_fields[sigil_name] = fields
        self.complete_structs.add(sigil_name)
        EXTERNAL_C_SPELLING[sigil_name] = c_spelling
        return ExternalTypeNode(line=kw.line, col=kw.col, name=sigil_name,
                                c_spelling=c_spelling, opaque=False, field_count=count)

    def parse_struct_or_union(self, attrs: Optional[List[Attribute]] = None) -> StructDefNode:
        attrs = attrs or []
        kw_tok = self._eat()
        kind = "struct" if kw_tok.kind == 'KW_STRUCT' else "union"
        name_tok = self._eat('IDENT')
        self._check_attr_placement(attrs, 'type', name_tok)
        if name_tok.value in self.user_types and self.user_types[name_tok.value] != kind:
            raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: '{name_tok.value}' defined as wrong kind of tag")
        tag_already_declared = name_tok.value in self.user_types

        if self._cur().kind == 'SEMI':
            if attrs:
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: 'a@' attributes require a {kind} definition, "
                    f"not a forward declaration of '{name_tok.value}'")
            self._eat('SEMI')
            if not tag_already_declared:
                self.user_types[name_tok.value] = kind
            return StructDefNode(line=kw_tok.line, col=kw_tok.col, kind=kind, name=name_tok.value,
                                alignment=None, fields=[], emit_typedef=not tag_already_declared, attrs=attrs)

        if name_tok.value in self.complete_structs:
            raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Redefinition of type '{name_tok.value}'")
        self.user_types[name_tok.value] = kind

        alignment = None
        if self._cur().kind == 'KW_ALIGN':
            align_tok = self._eat('KW_ALIGN')
            alignment = int(align_tok.value)
            if alignment <= 0 or (alignment & (alignment - 1)) != 0:
                raise SemanticError(f"{self.filename}:{align_tok.line}:{align_tok.col}: Alignment '{alignment}' must be a power of 2")

        if alignment is not None and any(a.name in ('packed', 'aligned') for a in attrs):
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: 'a!{alignment}' cannot be combined with "
                f"'a@(packed/aligned(...))' on the same type; use one alignment mechanism")

        self._eat('LBRACE')
        fields: List[VarDeclStmt] = []
        field_map: Dict[str, TypeNode] = {}
        while self._cur().kind != 'RBRACE':
            field_attrs: List[Attribute] = []
            if self._cur().kind == 'KW_ATTR':
                field_attrs = self.parse_attrs()
            ft = self.parse_type()
            bit_width = None
            if self._cur().kind == 'KW_BITFIELD':
                # 匿名零宽位域：`Type w! 0;` -> `Type : 0;`，强制下一个字段对齐
                bf_tok = self._eat('KW_BITFIELD')
                w_tok = self._eat('INT_NUM')
                width = self._attr_int_value(w_tok, w_tok.value)
                self._check_bitfield_base(bf_tok, ft)
                if width != 0:
                    raise SemanticError(
                        f"{self.filename}:{bf_tok.line}:{bf_tok.col}: An unnamed bit-field must be zero-width padding "
                        f"('{format_c_declarator(ft)} w! 0;'); give it a name for a real bit-field")
                if field_attrs:
                    raise SemanticError(
                        f"{self.filename}:{bf_tok.line}:{bf_tok.col}: Padding bit-field cannot carry 'a@' attributes")
                self._eat('SEMI')
                fields.append(VarDeclStmt(line=bf_tok.line, col=bf_tok.col, var_type=ft,
                                          name='', attrs=[], bit_width=0))
                continue
            fname_tok = self._eat('IDENT')
            if self._cur().kind == 'KW_BITFIELD':
                bf_tok = self._eat('KW_BITFIELD')
                w_tok = self._eat('INT_NUM')
                width = self._attr_int_value(w_tok, w_tok.value)
                self._check_bitfield_base(bf_tok, ft)
                assert isinstance(ft, BaseType)
                limit = BITFIELD_WIDTH[ft.c_name]
                if width < 1 or width > limit:
                    raise SemanticError(
                        f"{self.filename}:{bf_tok.line}:{bf_tok.col}: 'w!{width}' out of range for '{ft.c_name}': "
                        f"width must be 1..{limit}")
                bit_width = width
            self._check_attr_placement(field_attrs, 'field', fname_tok)
            self._validate_non_void_var(ft, fname_tok)
            if not self._is_complete_object_type(ft):
                raise SemanticError(f"{self.filename}:{fname_tok.line}:{fname_tok.col}: Field '{fname_tok.value}' has incomplete type")
            if fname_tok.value in field_map:
                raise SemanticError(f"{self.filename}:{fname_tok.line}:{fname_tok.col}: Duplicate field '{fname_tok.value}' in {kind} '{name_tok.value}'")
            field_map[fname_tok.value] = ft
            if bit_width is not None:
                self.struct_bitfields.setdefault(name_tok.value, {})[fname_tok.value] = bit_width
            self._eat('SEMI')
            fields.append(VarDeclStmt(line=fname_tok.line, col=fname_tok.col, var_type=ft,
                                      name=fname_tok.value, attrs=field_attrs, bit_width=bit_width))
        if not fields:
            raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Empty {kind} '{name_tok.value}' is forbidden in ISO C99")
        self._eat('RBRACE')
        self._eat('SEMI')
        self.struct_fields[name_tok.value] = field_map
        self.complete_structs.add(name_tok.value)
        return StructDefNode(line=kw_tok.line, col=kw_tok.col, kind=kind, name=name_tok.value,
                            alignment=alignment, fields=fields, emit_typedef=not tag_already_declared,
                            attrs=attrs)

    def parse_enum(self) -> EnumDefNode:
        kw_tok = self._eat('KW_ENUM')
        name_tok = self._eat('IDENT')
        if name_tok.value in self.user_types:
            raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Redefinition of enum '{name_tok.value}'")
        self.user_types[name_tok.value] = "enum"
        self._eat('LBRACE')
        items: List[Tuple[str, Optional[ExprNode]]] = []
        next_val = 0
        while self._cur().kind != 'RBRACE':
            item_tok = self._eat('IDENT')
            val_expr = None
            if self._cur().kind == 'OP_ASSIGN':
                self._eat('OP_ASSIGN')
                val_expr = self.parse_pure_expr()
                c_val = self._eval_const_int_expr(val_expr)
                if c_val is None:
                    raise SemanticError(f"{self.filename}:{item_tok.line}:{item_tok.col}: Enumerator value for '{item_tok.value}' is not an integer constant")
                next_val = c_val
            items.append((item_tok.value, val_expr))
            self.enum_constants[item_tok.value] = next_val
            next_val += 1
            self._register_symbol(item_tok.value, BaseType(line=item_tok.line, col=item_tok.col, c_name="int", is_const=True), item_tok)
            if self._cur().kind == 'COMMA':
                self._eat('COMMA')
            else:
                break
        if not items:
            raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Empty enum '{name_tok.value}' is forbidden in ISO C99")
        self._eat('RBRACE')
        self._eat('SEMI')
        return EnumDefNode(line=kw_tok.line, col=kw_tok.col, name=name_tok.value, items=items)

    def _parse_object_decl_after_name(self, decl_type: TypeNode, name_tok: Token,
                                      global_scope: bool = False, consume_semi: bool = True,
                                      is_static: bool = False,
                                      attrs: Optional[List[Attribute]] = None) -> VarDeclStmt:
        attrs = attrs or []
        self._validate_non_void_var(decl_type, name_tok)
        self._register_symbol(name_tok.value, decl_type, name_tok)
        init_expr: Optional[ExprNode] = None
        if self._cur().kind == 'OP_ASSIGN':
            op_tok = self._eat('OP_ASSIGN')
            if self._cur().kind == 'LBRACE':
                init_expr = self.parse_brace_init()
                self._check_brace_init(decl_type, init_expr, name_tok)
            else:
                init_expr = self.parse_pure_expr()
                actual_t = self._infer_expr_type(init_expr)
                if not self._check_assign_compatible(decl_type, init_expr, actual_t):
                    raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Incompatible initializer type for '{name_tok.value}'")
            if global_scope and not self._is_static_const_init(init_expr):
                raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Global initializer for '{name_tok.value}' is not a compile-time constant")
        if consume_semi:
            self._eat('SEMI')
        if not global_scope:
            self.local_objects.add(name_tok.value)
        self._note_prov(name_tok.value, decl_type, init_expr)
        if isinstance(decl_type, PointerType) and decl_type.is_restrict and name_tok.value in self.prov:
            self.restricted[self.prov[name_tok.value].base] = len(self.scopes) - 1
        return VarDeclStmt(line=name_tok.line, col=name_tok.col, var_type=decl_type,
                           name=name_tok.value, init_expr=init_expr, is_static=is_static, attrs=attrs)

    def parse_brace_init(self) -> AggregateInit:
        """解析 `{ e1, e2, ... }`，允许嵌套与 C99 尾随逗号。"""
        lb = self._eat('LBRACE')
        if self._cur().kind == 'RBRACE':
            raise SemanticError(f"{self.filename}:{lb.line}:{lb.col}: Empty initializer list '{{ }}' is forbidden in ISO C99")
        elements: List[ExprNode] = []
        while True:
            if self._cur().kind == 'LBRACE':
                elements.append(self.parse_brace_init())
            elif (self._cur().kind == 'DOT' and self.tokens[self.pos + 1].kind == 'IDENT'
                  and self.tokens[self.pos + 2].kind == 'OP_ASSIGN'):
                dot_tok = self._eat('DOT')
                fld_tok = self._eat('IDENT')
                self._eat('OP_ASSIGN')
                val: ExprNode
                if self._cur().kind == 'LBRACE':
                    val = self.parse_brace_init()
                else:
                    val = self.parse_pure_expr()
                elements.append(DesignatedInit(line=dot_tok.line, col=dot_tok.col,
                                               field=fld_tok.value, value=val))
            elif self._cur().kind == 'LBRACK':
                lb_tok = self._eat('LBRACK')
                idx_e = self.parse_pure_expr()
                idx_v = self._eval_const_int_expr(idx_e)
                if idx_v is None or idx_v < 0:
                    raise SemanticError(
                        f"{self.filename}:{lb_tok.line}:{lb_tok.col}: Array designator must be a non-negative integer constant")
                self._eat('RBRACK')
                self._eat('OP_ASSIGN')
                if self._cur().kind == 'LBRACE':
                    val = self.parse_brace_init()
                else:
                    val = self.parse_pure_expr()
                elements.append(DesignatedIndex(line=lb_tok.line, col=lb_tok.col,
                                                index_expr=idx_e, index_val=idx_v, value=val))
            else:
                elements.append(self.parse_pure_expr())
            if self._cur().kind == 'COMMA':
                self._eat('COMMA')
                if self._cur().kind == 'RBRACE':
                    break
            else:
                break
        self._eat('RBRACE')
        return AggregateInit(line=lb.line, col=lb.col, elements=elements)

    def _check_brace_init(self, target: TypeNode, init: AggregateInit, name_tok: Token):
        if isinstance(target, ArrayType):
            size_val = target.size_val
            if size_val is None:
                raise SemanticError(f"{self.filename}:{init.line}:{init.col}: Array initializer target has no fixed size")
            if any(isinstance(e, DesignatedInit) for e in init.elements):
                raise SemanticError(
                    f"{self.filename}:{init.line}:{init.col}: Struct designators '.field m,' cannot initialize an array")
            if any(isinstance(e, DesignatedIndex) for e in init.elements):
                seen_idx: Set[int] = set()
                for elem in init.elements:
                    if not isinstance(elem, DesignatedIndex):
                        raise SemanticError(
                            f"{self.filename}:{elem.line}:{elem.col}: Cannot mix designated '[index] m,' and positional "
                            f"initializers in one list")
                    if elem.index_val >= size_val:
                        raise SemanticError(
                            f"{self.filename}:{elem.line}:{elem.col}: Array designator [{elem.index_val}] out of range "
                            f"(size is {size_val})")
                    if elem.index_val in seen_idx:
                        raise SemanticError(
                            f"{self.filename}:{elem.line}:{elem.col}: Duplicate array designator [{elem.index_val}]")
                    seen_idx.add(elem.index_val)
                    self._check_init_element(target.element_type, elem.value, name_tok)
                return
            if len(init.elements) > size_val:
                raise SemanticError(
                    f"{self.filename}:{init.line}:{init.col}: Too many initializers for '{name_tok.value}': "
                    f"{len(init.elements)} given, array holds {size_val}")
            for elem in init.elements:
                self._check_init_element(target.element_type, elem, name_tok)
            return
        if isinstance(target, BaseType) and self.user_types.get(target.c_name) in ('struct', 'union'):
            kind = self.user_types[target.c_name]
            if target.c_name not in self.struct_fields:
                raise SemanticError(
                    f"{self.filename}:{init.line}:{init.col}: '{name_tok.value}' has incomplete type and cannot be initialized")
            fmap = self.struct_fields[target.c_name]
            if any(isinstance(e, DesignatedIndex) for e in init.elements):
                raise SemanticError(
                    f"{self.filename}:{init.line}:{init.col}: Array designators '[index] m,' cannot initialize a {kind}; use '.field m,'")
            if any(isinstance(e, DesignatedInit) for e in init.elements):
                seen: Set[str] = set()
                for elem in init.elements:
                    if not isinstance(elem, DesignatedInit):
                        raise SemanticError(
                            f"{self.filename}:{elem.line}:{elem.col}: Cannot mix designated '.field m,' and positional "
                            f"initializers in one list")
                    if elem.field not in fmap:
                        raise SemanticError(
                            f"{self.filename}:{elem.line}:{elem.col}: '{target.c_name}' has no member named '{elem.field}'")
                    if elem.field in seen:
                        raise SemanticError(
                            f"{self.filename}:{elem.line}:{elem.col}: Duplicate designated initializer for '{elem.field}'")
                    seen.add(elem.field)
                    self._check_init_element(fmap[elem.field], elem.value, name_tok)
                return
            fields = list(fmap.items())
            if kind == 'union':
                if len(init.elements) != 1:
                    raise SemanticError(
                        f"{self.filename}:{init.line}:{init.col}: Union '{target.c_name}' initializer takes exactly 1 element, "
                        f"got {len(init.elements)}")
            elif len(init.elements) > len(fields):
                raise SemanticError(
                    f"{self.filename}:{init.line}:{init.col}: Too many initializers for '{name_tok.value}': "
                    f"{len(init.elements)} given, {kind} has {len(fields)} fields")
            for (fname, ftype), elem in zip(fields, init.elements):
                self._check_init_element(ftype, elem, name_tok)
            return
        raise SemanticError(
            f"{self.filename}:{init.line}:{init.col}: Aggregate initializer requires an array, struct or union type, "
            f"but '{name_tok.value}' has type '{format_c_declarator(target)}'")

    def _check_init_element(self, target: TypeNode, elem: ExprNode, name_tok: Token):
        if isinstance(elem, AggregateInit):
            self._check_brace_init(target, elem, name_tok)
            return
        et = self._infer_expr_type(elem)
        if not self._check_assign_compatible(target, elem, et):
            raise SemanticError(
                f"{self.filename}:{elem.line}:{elem.col}: Incompatible initializer element for '{name_tok.value}': "
                f"expected '{format_c_declarator(target)}', got '{format_c_declarator(et)}'")

    def parse_top_decl_or_func(self, object_marker: Optional[Token] = None, is_static: bool = False,
                               attrs: Optional[List[Attribute]] = None,
                               is_inline: bool = False) -> StmtNode:
        attrs = attrs or []
        start_tok = self._cur()
        decl_type = self.parse_type()
        name_tok = self._eat('IDENT')

        if self._cur().kind == 'LPAREN':
            self._check_attr_placement(attrs, 'function', name_tok)
            if object_marker is not None:
                raise ParseError(f"{self.filename}:{object_marker.line}:{object_marker.col}: 'o!' introduces an object declaration, not a function")
            if isinstance(decl_type, ArrayType):
                raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Function '{name_tok.value}' cannot return array type")
            self._eat('LPAREN')
            params: List[Tuple[TypeNode, str]] = []
            seen_params = set()
            is_variadic = False
            if self._cur().kind == 'TYPE_VOID' and self.tokens[self.pos + 1].kind == 'RPAREN':
                self._eat('TYPE_VOID')
            elif self._cur().kind != 'RPAREN':
                while True:
                    if self._cur().kind == 'ELLIPSIS':
                        if not params:
                            raise SemanticError(
                                f"{self.filename}:{self._cur().line}:{self._cur().col}: "
                                f"A variadic function requires at least one named parameter before '...'")
                        self._eat('ELLIPSIS')
                        is_variadic = True
                        break
                    raw_pt = self.parse_type()
                    pt = decay_parameter_type(raw_pt)
                    pname = ''
                    if self._cur().kind == 'IDENT':
                        p_tok = self._eat('IDENT')
                        self._validate_non_void_var(pt, p_tok)
                        if p_tok.value in seen_params:
                            raise SemanticError(f"{self.filename}:{p_tok.line}:{p_tok.col}: Duplicate parameter '{p_tok.value}'")
                        seen_params.add(p_tok.value)
                        pname = p_tok.value
                    else:
                        self._validate_non_void_var(pt, name_tok)
                    params.append((pt, pname))
                    if self._cur().kind == 'COMMA':
                        self._eat('COMMA')
                    else:
                        break
            self._eat('RPAREN')

            param_types = [pt for pt, _ in params]

            if name_tok.value in self.scopes[0]:
                if name_tok.value not in self.func_sigs:
                    raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: '{name_tok.value}' redeclared as different kind of symbol")
                old_params, old_ret = self.func_sigs[name_tok.value]
                if len(old_params) != len(param_types) or not types_equal(strip_top_qualifiers(old_ret), strip_top_qualifiers(decl_type)) or not all(types_equal(strip_top_qualifiers(a), strip_top_qualifiers(b)) for a, b in zip(old_params, param_types)):
                    raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Conflicting types for function '{name_tok.value}'")

            fn_ptr_equiv = FunctionPointerType(line=name_tok.line, col=name_tok.col, param_decls=[(pt, pn) for pt, pn in params], return_type=decl_type, is_variadic=is_variadic)
            self.scopes[0][name_tok.value] = fn_ptr_equiv
            self.func_sigs[name_tok.value] = (param_types, decl_type)
            if is_variadic:
                self.func_variadic.add(name_tok.value)

            if self._cur().kind == 'SEMI':
                self._eat('SEMI')
                return FuncDefNode(line=name_tok.line, col=name_tok.col, return_type=decl_type, name=name_tok.value, params=params, body=None, is_static=is_static, attrs=attrs, is_inline=is_inline, is_variadic=is_variadic)

            if any(not pname for _, pname in params):
                raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Function definition parameters must have names")
            if name_tok.value in self.func_defined:
                raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Redefinition of function '{name_tok.value}'")
            self.func_defined.add(name_tok.value)

            prev_ret = self.current_func_ret
            prev_variadic = self.current_func_variadic
            prev_labels = self.func_labels
            prev_gotos = self.func_gotos
            prev_prov = self.prov
            prev_locals = self.local_objects
            prev_params = self.param_names
            self.current_func_ret = decl_type
            self.current_func_variadic = is_variadic
            self.func_labels = set()
            self.func_gotos = []
            # 只保留文件作用域对象的来源，清掉上一个函数的局部
            self.prov = {k: v for k, v in prev_prov.items() if k in self.scopes[0]}
            self.local_objects = set()
            self.param_names = set()
            prev_cur_name = self.cur_func_name
            prev_escape = self.cur_escape
            prev_restricted = self.restricted
            self.cur_func_name = name_tok.value
            self.cur_escape = set()
            self.restricted = {}
            self.func_param_names[name_tok.value] = [pname for _, pname in params]
            self.scopes.append({pname: pt for pt, pname in params})
            for _pt, pname in params:
                self.local_objects.add(pname)
                self.param_names.add(pname)
            provenance.begin_function(self, params)
            body = self.parse_block(create_new_scope=False)
            provenance.end_function(self, name_tok.value)
            self.scopes.pop()
            self.escape_params[name_tok.value] = self.cur_escape
            self.cur_func_name = prev_cur_name
            self.cur_escape = prev_escape
            self.restricted = prev_restricted
            self.current_func_ret = prev_ret
            self.current_func_variadic = prev_variadic
            self.prov = prev_prov
            self.local_objects = prev_locals
            self.param_names = prev_params
            for (lname, ltok) in self.func_gotos:
                if lname not in self.func_labels:
                    raise SemanticError(
                        f"{self.filename}:{ltok.line}:{ltok.col}: 'g!' target '{lname}' has no matching 'l!' label "
                        f"in function '{name_tok.value}'")
            self.func_labels = prev_labels
            self.func_gotos = prev_gotos
            if not is_void_type(decl_type) and name_tok.value != 'main' and self._can_fall_through(body):
                raise SemanticError(f"{self.filename}:{name_tok.line}:{name_tok.col}: Control reaches end of non-void function '{name_tok.value}' without returning a value")
            return FuncDefNode(line=name_tok.line, col=name_tok.col, return_type=decl_type, name=name_tok.value, params=params, body=body, is_static=is_static, attrs=attrs, is_inline=is_inline, is_variadic=is_variadic)

        if object_marker is None:
            if start_tok.kind in ('TYPE_INT', 'TYPE_BOOL'):
                self._check_attr_placement(attrs, 'object', name_tok, file_scope=True)
                return self._parse_object_decl_after_name(decl_type, name_tok, global_scope=True,
                                                          is_static=is_static, attrs=attrs)
            raise ParseError(f"{self.filename}:{name_tok.line}:{name_tok.col}: File-scope object declarations must begin with 'o!'")
        self._check_attr_placement(attrs, 'object', name_tok, file_scope=True)
        return self._parse_object_decl_after_name(decl_type, name_tok, global_scope=True, is_static=is_static, attrs=attrs)

    def _push_scope(self, names: Optional[Dict[str, TypeNode]] = None) -> None:
        """进入作用域时开一张遮蔽表：只记录本层声明覆盖了哪些外层来源。"""
        self.scopes.append(names if names is not None else {})
        self._prov_saved.append({})

    def _pop_scope(self) -> None:
        """退出作用域：被遮蔽的外层来源还原；本层新声明的来源保留，供悬空检测。"""
        self.scopes.pop()
        saved = self._prov_saved.pop()
        for name, prev in saved.items():
            if prev is not None:
                self.prov[name] = prev

    def parse_block(self, create_new_scope: bool = True) -> BlockStmt:
        lb = self._eat('LBRACE')
        if create_new_scope:
            self._push_scope()
        stmts: List[StmtNode] = []
        while self._cur().kind != 'RBRACE':
            stmts.append(self.parse_stmt())
        self._eat('RBRACE')
        if create_new_scope:
            self._pop_scope()
        return BlockStmt(line=lb.line, col=lb.col, stmts=stmts)

    def parse_stmt(self) -> StmtNode:
        tok = self._cur()
        if tok.kind == 'PREPROC':
            ptok = self._eat('PREPROC')
            return PreprocNode(line=ptok.line, col=ptok.col, text=ptok.value)
        if tok.kind == 'LBRACE':
            return self.parse_block(create_new_scope=True)
        if tok.kind == 'KW_IF':
            self._eat('KW_IF')
            self._eat('LPAREN')
            cond = self.parse_pure_expr()
            self._check_scalar_cond(cond, 'i?')
            self._eat('RPAREN')
            then_blk = self.parse_block()
            else_br = None
            if self._cur().kind == 'KW_ELSE':
                self._eat('KW_ELSE')
                else_br = self.parse_stmt() if self._cur().kind == 'KW_IF' else self.parse_block()
            return IfStmt(line=tok.line, col=tok.col, cond=cond, then_block=then_blk, else_branch=else_br)

        if tok.kind == 'KW_WHILE':
            self._eat('KW_WHILE')
            self._eat('LPAREN')
            cond = self.parse_pure_expr()
            self._check_scalar_cond(cond, 'w~')
            self._eat('RPAREN')
            self.loop_depth += 1
            body = self.parse_block()
            self.loop_depth -= 1
            return WhileStmt(line=tok.line, col=tok.col, cond=cond, body=body)

        if tok.kind == 'KW_FOR':
            self._eat('KW_FOR')
            self._eat('LPAREN')
            self._push_scope()
            init_stmt: Optional[StmtNode] = None
            if self._cur().kind != 'SEMI':
                if self._cur().kind == 'KW_OBJECT':
                    self._eat('KW_OBJECT')
                    vt = self.parse_type()
                    vname = self._eat('IDENT')
                    init_stmt = self._parse_object_decl_after_name(vt, vname, consume_semi=False)
                elif self._is_type_start(self._cur()):
                    decl_tok = self._cur()
                    if not self._can_omit_object_marker(decl_tok):
                        raise ParseError(f"{self.filename}:{decl_tok.line}:{decl_tok.col}: Object declarations in a 'f~' initializer must begin with 'o!'")
                    vt = self.parse_type()
                    vname = self._eat('IDENT')
                    init_stmt = self._parse_object_decl_after_name(vt, vname, consume_semi=False)
                else:
                    init_stmt = self.parse_assign_or_expr_no_semi()
            self._eat('SEMI')
            cond_expr = None if self._cur().kind == 'SEMI' else self.parse_pure_expr()
            if cond_expr is not None:
                self._check_scalar_cond(cond_expr, 'f~')
            self._eat('SEMI')
            step_stmt = None if self._cur().kind == 'RPAREN' else self.parse_assign_or_expr_no_semi()
            self._eat('RPAREN')
            self.loop_depth += 1
            body = self.parse_block()
            self.loop_depth -= 1
            self._pop_scope()
            return ForStmt(line=tok.line, col=tok.col, init_stmt=init_stmt, cond_expr=cond_expr, step_stmt=step_stmt, body=body)

        if tok.kind == 'KW_SWITCH':
            return self.parse_switch()

        if tok.kind == 'KW_TRAP':
            self._eat('KW_TRAP')
            self._eat('SEMI')
            return TrapStmt(line=tok.line, col=tok.col)

        if tok.kind == 'KW_RETURN':
            self._eat('KW_RETURN')
            if self.current_func_ret is None:
                raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'r;' (return) outside of function")
            expr = None if self._cur().kind == 'SEMI' else self.parse_pure_expr()
            self._eat('SEMI')
            if is_void_type(self.current_func_ret) and expr is not None:
                raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'v.' (void) function cannot return a value")
            if not is_void_type(self.current_func_ret):
                if expr is None:
                    raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Non-void function must return a value")
                ret_expr_t = self._infer_expr_type(expr)
                if not self._check_assign_compatible(self.current_func_ret, expr, ret_expr_t):
                    raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Incompatible return type")
            if expr is not None:
                self._prov_live(self._prov_of(expr), expr)
            bad = self._address_of_local(expr)
            if bad is not None:
                raise SemanticError(
                    f"{self.filename}:{tok.line}:{tok.col}: Returning the address of local object '{bad}' would dangle "
                    f"after return")
            ret_stmt = ReturnStmt(line=tok.line, col=tok.col, expr=expr)
            provenance.note_return(self, ret_stmt)
            return ret_stmt

        if tok.kind == 'KW_BREAK':
            self._eat('KW_BREAK')
            self._eat('SEMI')
            if self.loop_depth == 0 and self.switch_depth == 0:
                raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'b!' (break) statement not within loop or switch")
            return JumpStmt(line=tok.line, col=tok.col, keyword="break")

        if tok.kind == 'KW_CONTINUE':
            self._eat('KW_CONTINUE')
            self._eat('SEMI')
            if self.loop_depth == 0:
                raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'c^' (continue) statement not within a loop")
            return JumpStmt(line=tok.line, col=tok.col, keyword="continue")

        if tok.kind == 'KW_DO':
            self._eat('KW_DO')
            self.loop_depth += 1
            body = self.parse_block()
            self.loop_depth -= 1
            self._eat('KW_WHILE')
            self._eat('LPAREN')
            cond = self.parse_pure_expr()
            self._check_scalar_cond(cond, 'd~')
            self._eat('RPAREN')
            self._eat('SEMI')
            return DoWhileStmt(line=tok.line, col=tok.col, body=body, cond=cond)

        if tok.kind == 'KW_STATIC_ASSERT':
            return self.parse_static_assert()

        if tok.kind == 'KW_GOTO':
            self._eat('KW_GOTO')
            ltok = self._eat('IDENT')
            self._eat('SEMI')
            self.func_gotos.append((ltok.value, ltok))
            return GotoStmt(line=tok.line, col=tok.col, label=ltok.value)

        if tok.kind == 'KW_LABEL':
            self._eat('KW_LABEL')
            ltok = self._eat('IDENT')
            self._eat('SEMI')
            if ltok.value in self.func_labels:
                raise SemanticError(f"{self.filename}:{ltok.line}:{ltok.col}: Duplicate label '{ltok.value}' in this function")
            self.func_labels.add(ltok.value)
            return LabelStmt(line=tok.line, col=tok.col, name=ltok.value)

        if tok.kind == 'IDENT' and tok.value in ('va_start', 'va_end', 'va_copy') and self.tokens[self.pos + 1].kind == 'LPAREN':
            return self.parse_va_stmt()

        if tok.kind == 'KW_ATTR':
            attrs = self.parse_attrs()
            if self._cur().kind != 'KW_OBJECT':
                nxt = self._cur()
                raise ParseError(
                    f"{self.filename}:{nxt.line}:{nxt.col}: Block-scope 'a@' attributes must be followed by 'o!'")
            self._eat('KW_OBJECT')
            vt = self.parse_type()
            vname = self._eat('IDENT')
            self._check_attr_placement(attrs, 'object', vname, file_scope=False)
            return self._parse_object_decl_after_name(vt, vname, attrs=attrs)

        if tok.kind == 'KW_OBJECT':
            self._eat('KW_OBJECT')
            vt = self.parse_type()
            vname = self._eat('IDENT')
            return self._parse_object_decl_after_name(vt, vname)

        if self._is_type_start(tok):
            if self._can_omit_object_marker(tok):
                vt = self.parse_type()
                vname = self._eat('IDENT')
                return self._parse_object_decl_after_name(vt, vname)
            raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: Object declarations must begin with 'o!'")

        stmt = self.parse_assign_or_expr_no_semi()
        self._eat('SEMI')
        return stmt

    def parse_static_assert(self) -> StaticAssertStmt:
        tok = self._eat('KW_STATIC_ASSERT')
        self._eat('LPAREN')
        cond = self.parse_pure_expr()
        # 条件交给后端 C 编译器判定：sizeof 等本身就是整型常量表达式，
        # 在这里折叠会把 ABI 尺寸假设写死进转译器。
        self._eat('COMMA')
        msg = self._eat('STRING')
        self._eat('RPAREN')
        self._eat('SEMI')
        return StaticAssertStmt(line=tok.line, col=tok.col, cond=cond, message=msg.value)

    def parse_va_stmt(self) -> VaStmt:
        name_tok = self._eat('IDENT')
        self._eat('LPAREN')
        ap = self.parse_pure_expr()
        ap_t = self._infer_expr_type(ap)
        if not (isinstance(ap_t, BaseType) and ap_t.c_name == 'va_list'):
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: '{name_tok.value}' requires a 'va_list' object")
        if name_tok.value == 'va_start':
            if not self.current_func_variadic:
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: 'va_start' is only allowed inside a variadic function")
            self._eat('COMMA')
            last_tok = self._eat('IDENT')
            self._eat('RPAREN')
            self._eat('SEMI')
            return VaStmt(line=name_tok.line, col=name_tok.col, kind='start', ap=ap, last_name=last_tok.value)
        if name_tok.value == 'va_copy':
            self._eat('COMMA')
            src = self.parse_pure_expr()
            src_t = self._infer_expr_type(src)
            if not (isinstance(src_t, BaseType) and src_t.c_name == 'va_list'):
                raise SemanticError(
                    f"{self.filename}:{name_tok.line}:{name_tok.col}: 'va_copy' source must be a 'va_list' object")
            self._eat('RPAREN')
            self._eat('SEMI')
            return VaStmt(line=name_tok.line, col=name_tok.col, kind='copy', ap=ap, ap2=src)
        self._eat('RPAREN')
        self._eat('SEMI')
        return VaStmt(line=name_tok.line, col=name_tok.col, kind='end', ap=ap)

    def parse_va_arg(self) -> VaArgExpr:
        name_tok = self._eat('IDENT')
        self._eat('LPAREN')
        ap = self.parse_pure_expr()
        ap_t = self._infer_expr_type(ap)
        if not (isinstance(ap_t, BaseType) and ap_t.c_name == 'va_list'):
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: 'va_arg' requires a 'va_list' object")
        self._eat('COMMA')
        target_t = self.parse_type()
        self._eat('RPAREN')
        if is_void_type(target_t) or not self._is_complete_object_type(target_t):
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: 'va_arg' type must be a complete object type")
        return VaArgExpr(line=name_tok.line, col=name_tok.col, ap=ap, target_type=target_t)

    def parse_offsetof(self) -> OffsetofExpr:
        name_tok = self._eat('IDENT')
        self._eat('LPAREN')
        target_t = self.parse_type()
        self._eat('COMMA')
        fld_tok = self._eat('IDENT')
        self._eat('RPAREN')
        if not (isinstance(target_t, BaseType)
                and self.user_types.get(target_t.c_name) in ('struct', 'union')
                and target_t.c_name in self.struct_fields):
            raise SemanticError(
                f"{self.filename}:{name_tok.line}:{name_tok.col}: 'offsetof' requires a complete struct/union type, "
                f"got '{format_c_declarator(target_t)}'")
        if fld_tok.value not in self.struct_fields[target_t.c_name]:
            raise SemanticError(
                f"{self.filename}:{fld_tok.line}:{fld_tok.col}: '{target_t.c_name}' has no member named '{fld_tok.value}'")
        return OffsetofExpr(line=name_tok.line, col=name_tok.col, target_type=target_t, field=fld_tok.value)

    def parse_generic(self) -> ExprNode:
        """`g? expr { T: e; ...; d: e }` —— 按控制表达式的静态类型选一条分支，转译期解析掉。"""
        g_tok = self._eat('KW_GENERIC')
        ctl = self.parse_unary()
        ctl_t = strip_top_qualifiers(self._infer_expr_type(ctl))
        self._eat('LBRACE')
        assocs: List[Tuple[Optional[TypeNode], ExprNode]] = []
        seen: Set[str] = set()
        has_default = False
        while self._cur().kind != 'RBRACE':
            if self._cur().kind == 'KW_DEFAULT':
                self._eat('KW_DEFAULT')      # `d:` 已经把冒号一起吃了
                if has_default:
                    raise SemanticError(f"{self.filename}:{g_tok.line}:{g_tok.col}: 'g?' allows at most one 'd:' association")
                has_default = True
                t = None
            else:
                t = self.parse_type()
                key = format_c_declarator(strip_top_qualifiers(t))
                if key in seen:
                    raise SemanticError(f"{self.filename}:{g_tok.line}:{g_tok.col}: Duplicate 'g?' association for type '{key}'")
                seen.add(key)
                self._eat('COLON')
            expr = self.parse_pure_expr()
            assocs.append((t, expr))
            if self._cur().kind == 'SEMI':
                self._eat('SEMI')
            elif self._cur().kind != 'RBRACE':
                bad = self._cur()
                raise ParseError(
                    f"{self.filename}:{bad.line}:{bad.col}: Expected ';' or '}}' after a 'g?' association, got '{bad.value}'")
        self._eat('RBRACE')
        if not assocs:
            raise SemanticError(f"{self.filename}:{g_tok.line}:{g_tok.col}: 'g?' requires at least one association")
        for t, expr in assocs:
            if t is not None and types_equal(strip_top_qualifiers(t), ctl_t):
                self._infer_expr_type(expr)
                return expr
        for t, expr in assocs:
            if t is None:
                self._infer_expr_type(expr)
                return expr
        raise SemanticError(
            f"{self.filename}:{g_tok.line}:{g_tok.col}: 'g?' has no association for '{format_c_declarator(ctl_t)}' and no 'd:' default")

    def parse_switch(self) -> SwitchStmt:
        sw_tok = self._eat('KW_SWITCH')
        self._eat('LPAREN')
        cond = self.parse_pure_expr()
        cond_t = self._infer_expr_type(cond)
        if not isinstance(cond_t, BaseType) or (cond_t.c_name not in INT_C_TYPES and self.user_types.get(cond_t.c_name) != "enum"):
            raise SemanticError(f"{self.filename}:{sw_tok.line}:{sw_tok.col}: Switch quantity is not an integer or enum")
        self._eat('RPAREN')
        self._eat('LBRACE')
        self.switch_depth += 1
        cases: List[CaseClause] = []
        seen_case_vals: Set[int] = set()
        has_default = False

        while self._cur().kind != 'RBRACE':
            if self._cur().kind == 'KW_CASE':
                c_tok = self._eat('KW_CASE')
                c_val = self.parse_pure_expr()
                const_int = self._eval_const_int_expr(c_val)
                if const_int is None:
                    raise SemanticError(f"{self.filename}:{c_tok.line}:{c_tok.col}: Case label does not reduce to an integer constant")
                if const_int in seen_case_vals:
                    raise SemanticError(f"{self.filename}:{c_tok.line}:{c_tok.col}: Duplicate case value '{const_int}'")
                seen_case_vals.add(const_int)
                self._eat('COLON')
                self._push_scope()
                c_stmts: List[StmtNode] = []
                while self._cur().kind not in ('KW_CASE', 'KW_DEFAULT', 'RBRACE'):
                    c_stmts.append(self.parse_stmt())
                self._pop_scope()
                cases.append(CaseClause(line=c_tok.line, value=c_val, stmts=c_stmts))
            elif self._cur().kind == 'KW_DEFAULT':
                d_tok = self._eat('KW_DEFAULT')
                if has_default:
                    raise SemanticError(f"{self.filename}:{d_tok.line}:{d_tok.col}: Multiple 'd:' (default) labels in one switch")
                has_default = True
                if self._cur().kind == 'COLON':
                    self._eat('COLON')
                self._push_scope()
                d_stmts: List[StmtNode] = []
                while self._cur().kind not in ('KW_CASE', 'KW_DEFAULT', 'RBRACE'):
                    d_stmts.append(self.parse_stmt())
                self._pop_scope()
                cases.append(CaseClause(line=d_tok.line, value=None, stmts=d_stmts))
            else:
                tok = self._cur()
                raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: Expected 'k:' (case) or 'd:' (default) inside switch")
        self.switch_depth -= 1
        self._eat('RBRACE')
        return SwitchStmt(line=sw_tok.line, col=sw_tok.col, cond=cond, cases=cases)

    def parse_assign_or_expr_no_semi(self) -> StmtNode:
        tok = self._cur()
        lhs = self.parse_ternary()
        if self._cur().kind in ASSIGN_TOKENS:
            op_tok = self._eat()
            self._check_modifiable_lvalue(lhs, op_tok)
            rhs = self.parse_pure_expr()
            lhs_t = self._infer_expr_type(lhs)
            rhs_t = self._infer_expr_type(rhs)
            if op_tok.kind == 'OP_ASSIGN':
                if not self._check_assign_compatible(lhs_t, rhs, rhs_t):
                    raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Incompatible types in assignment 'm,'")
                bad = self._address_of_local(rhs)
                if bad is not None and isinstance(lhs, IdentExpr):
                    escaping = lhs.name in self.param_names or (
                        lhs.name in self.scopes[0] and lhs.name not in self.local_objects)
                    if escaping:
                        raise SemanticError(
                            f"{self.filename}:{op_tok.line}:{op_tok.col}: Storing the address of local object "
                            f"'{bad}' into '{lhs.name}' would dangle after this function returns")
                if isinstance(lhs, IdentExpr) and isinstance(strip_top_qualifiers(lhs_t), PointerType):
                    self._note_prov(lhs.name, lhs_t, rhs)
                if self.cur_func_name is not None:
                    src = self._param_source(rhs)
                    if src is not None and self._target_is_global(lhs):
                        self.cur_escape.add(src)
            else:
                self._check_compound_assign_types(op_tok.kind, lhs_t, rhs_t, op_tok)
                if isinstance(lhs, IdentExpr) and op_tok.kind in ('OP_ADD_ASSIGN', 'OP_SUB_ASSIGN'):
                    pv = self.prov.get(lhs.name)
                    k = self._try_const(rhs)
                    if pv is not None:
                        if k is not None:
                            self.prov[lhs.name] = Prov(
                                pv.base, pv.size,
                                pv.offset + k if op_tok.kind == 'OP_ADD_ASSIGN' else pv.offset - k,
                                pv.depth)
                        else:
                            self.prov.pop(lhs.name, None)
            assign_stmt = AssignStmt(line=op_tok.line, col=op_tok.col, op=ASSIGN_TOKENS[op_tok.kind],
                                     target=lhs, value=rhs)
            provenance.note_assign(self, assign_stmt)
            return assign_stmt
        self._infer_expr_type(lhs)
        return ExprStmt(line=tok.line, col=tok.col, expr=lhs)

    def parse_pure_expr(self) -> ExprNode:
        node = self.parse_ternary()
        if self._cur().kind in ASSIGN_TOKENS:
            op_tok = self._cur()
            raise SemanticError(
                f"{self.filename}:{op_tok.line}:{op_tok.col}: "
                f"Side-effect assignment operator '{op_tok.value}' ({ASSIGN_TOKENS[op_tok.kind]}) "
                f"is forbidden inside pure/conditional expressions; use '-' for subtraction or move assignment to a standalone statement."
            )
        return node

    def parse_ternary(self) -> ExprNode:
        cond = self.parse_lor()
        if self._cur().kind == 'QUESTION':
            q_tok = self._eat('QUESTION')
            self._check_scalar_cond(cond, '?:')
            then_e = self.parse_pure_expr()
            self._eat('COLON')
            else_e = self.parse_ternary()
            node = TernaryExpr(line=q_tok.line, col=q_tok.col, cond=cond, then_expr=then_e, else_expr=else_e)
            self._infer_expr_type(node)
            return node
        return cond

    def parse_lor(self) -> ExprNode:
        node = self.parse_land()
        while self._cur().kind == 'OP_LOR':
            op_tok = self._eat()
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op='||', left=node, right=self.parse_land())
        return node

    def parse_land(self) -> ExprNode:
        node = self.parse_bor()
        while self._cur().kind == 'OP_LAND':
            op_tok = self._eat()
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op='&&', left=node, right=self.parse_bor())
        return node

    def parse_bor(self) -> ExprNode:
        node = self.parse_bxor()
        while self._cur().kind == 'OP_BOR':
            op_tok = self._eat()
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op='|', left=node, right=self.parse_bxor())
        return node

    def parse_bxor(self) -> ExprNode:
        node = self.parse_band()
        while self._cur().kind == 'OP_BXOR':
            op_tok = self._eat()
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op='^', left=node, right=self.parse_band())
        return node

    def parse_band(self) -> ExprNode:
        node = self.parse_equality()
        while self._cur().kind == 'OP_BAND':
            op_tok = self._eat()
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op='&', left=node, right=self.parse_equality())
        return node

    def parse_equality(self) -> ExprNode:
        node = self.parse_relational()
        while self._cur().kind in ('OP_EQ', 'OP_NE'):
            op_tok = self._eat()
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op='==' if op_tok.kind == 'OP_EQ' else '!=', left=node, right=self.parse_relational())
        return node

    def parse_relational(self) -> ExprNode:
        node = self.parse_shift()
        rel_map = {'LT': '<', 'GT': '>', 'OP_LE': '<=', 'OP_GE': '>='}
        while self._cur().kind in rel_map:
            op_tok = self._eat()
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op=rel_map[op_tok.kind], left=node, right=self.parse_shift())
        return node

    def parse_shift(self) -> ExprNode:
        node = self.parse_additive()
        while self._cur().kind in ('OP_SHL', 'OP_SHR'):
            op_tok = self._eat()
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op=op_tok.value, left=node, right=self.parse_additive())
        return node

    def parse_additive(self) -> ExprNode:
        node = self.parse_multiplicative()
        while self._cur().kind in ('PLUS', 'MINUS'):
            op_tok = self._eat()
            right = self.parse_multiplicative()
            self._check_not_void_expr(node, op_tok)
            self._check_not_void_expr(right, op_tok)
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op=op_tok.value, left=node, right=right)
        return node

    def parse_multiplicative(self) -> ExprNode:
        node = self.parse_unary()
        while self._cur().kind in ('STAR', 'SLASH', 'PERCENT'):
            op_tok = self._eat()
            right = self.parse_unary()
            self._check_not_void_expr(node, op_tok)
            self._check_not_void_expr(right, op_tok)
            op = '%' if op_tok.kind == 'PERCENT' else op_tok.value
            node = BinaryExpr(line=op_tok.line, col=op_tok.col, op=op, left=node, right=right)
        return node

    def _check_not_void_expr(self, expr: ExprNode, op_tok: Token):
        t = self._infer_expr_type(expr)
        if is_void_type(t):
            raise SemanticError(f"{self.filename}:{op_tok.line}:{op_tok.col}: Void value cannot be used in expression")

    def parse_unary(self) -> ExprNode:
        tok = self._cur()
        # z? 取类型或表达式的大小，结果为 size_t
        if tok.kind == 'KW_SIZEOF':
            self._eat('KW_SIZEOF')
            if self._sizeof_takes_type():
                target_t = self.parse_type()
                if is_void_type(target_t):
                    raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'z?' cannot be applied to 'v.' (void)")
                if not self._is_complete_object_type(target_t):
                    raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'z?' requires a complete object type")
                return SizeofExpr(line=tok.line, col=tok.col, target_type=target_t, operand=None)
            operand = self.parse_unary()
            if is_void_type(self._infer_expr_type(operand)):
                raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'z?' cannot be applied to 'v.' (void)")
            return SizeofExpr(line=tok.line, col=tok.col, target_type=None, operand=operand)

        # a? 取对齐字节数，结果 size_t
        if tok.kind == 'KW_ALIGNOF':
            self._eat('KW_ALIGNOF')
            if not self._sizeof_takes_type():
                raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'a?' requires a type operand")
            target_t = self.parse_type()
            if is_void_type(target_t) or not self._is_complete_object_type(target_t):
                raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: 'a?' requires a complete object type")
            return AlignofExpr(line=tok.line, col=tok.col, target_type=target_t)

        # g? 按静态类型选分支（转译期解析，生成 C99 里只有被选中的那条）
        if tok.kind == 'KW_GENERIC':
            return self.parse_generic()

        # 支持显式类型转换表达式 (Type)expr，以及复合字面量 (Type){ ... }
        if tok.kind == 'LPAREN' and self._is_type_start_at(self.pos + 1):
            self._eat('LPAREN')
            target_t = self.parse_type()
            self._eat('RPAREN')
            if self._cur().kind == 'LBRACE':
                init = self.parse_brace_init()
                fake_tok = Token('IDENT', 'compound literal', tok.line, tok.col, 0)
                self._check_compound_init(target_t, init, fake_tok)
                return self.parse_postfix_tail(
                    CompoundLiteral(line=tok.line, col=tok.col, target_type=target_t, init=init))
            operand = self.parse_unary()
            return CastExpr(line=tok.line, col=tok.col, target_type=target_t, operand=operand)

        unary_map = {'MINUS': '-', 'PLUS': '+', 'OP_LNOT': '!', 'OP_BNOT': '~', 'KW_PTR': '*', 'KW_ADDR': '&'}
        if tok.kind in unary_map:
            self._eat()
            operand = self.parse_unary()
            node = UnaryExpr(line=tok.line, col=tok.col, op=unary_map[tok.kind], operand=operand)
            self._infer_expr_type(node)
            return node
        return self.parse_postfix()

    def parse_postfix(self) -> ExprNode:
        return self.parse_postfix_tail(self.parse_primary())

    def parse_postfix_tail(self, node: ExprNode) -> ExprNode:
        while True:
            tok = self._cur()
            if tok.kind == 'LBRACK':
                self._eat('LBRACK')
                idx_e = self.parse_pure_expr()
                self._eat('RBRACK')
                node = IndexExpr(line=tok.line, col=tok.col, base=node, index=idx_e)
                self._infer_expr_type(node)
            elif tok.kind in ('DOT', 'ARROW'):
                self._eat()
                field_tok = self._eat('IDENT')
                node = MemberExpr(line=tok.line, col=tok.col, base=node, field=field_tok.value, is_arrow=(tok.kind == 'ARROW'))
                self._infer_expr_type(node)
            elif tok.kind == 'LPAREN':
                self._eat('LPAREN')
                args: List[ExprNode] = []
                if self._cur().kind != 'RPAREN':
                    while True:
                        args.append(self.parse_pure_expr())
                        if self._cur().kind == 'COMMA':
                            self._eat('COMMA')
                        else:
                            break
                self._eat('RPAREN')

                callee_t = self._infer_expr_type(node)
                if isinstance(callee_t, FunctionPointerType):
                    expected_params = [pt for pt, _ in callee_t.param_decls]
                    if callee_t.is_variadic:
                        if len(args) < len(expected_params):
                            raise SemanticError(
                                f"{self.filename}:{tok.line}:{tok.col}: Variadic callable expects at least {len(expected_params)} arguments, got {len(args)}"
                            )
                    elif len(args) != len(expected_params):
                        raise SemanticError(
                            f"{self.filename}:{tok.line}:{tok.col}: Callable expects {len(expected_params)} arguments, got {len(args)}"
                        )
                    for idx, arg_e in enumerate(args, 1):
                        act_t = self._infer_expr_type(arg_e)
                        self._check_restricted_base(arg_e)
                        self._prov_live(self._prov_of(arg_e), arg_e)
                        if is_void_type(act_t):
                            raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Argument {idx} cannot have 'v.' (void) type")
                        if idx <= len(expected_params):
                            exp_t = expected_params[idx - 1]
                            if not self._check_assign_compatible(exp_t, arg_e, act_t):
                                raise SemanticError(
                                    f"{self.filename}:{tok.line}:{tok.col}: Incompatible type for argument {idx} in call"
                                )
                else:
                    raise SemanticError(f"{self.filename}:{tok.line}:{tok.col}: Called object is not a function or function pointer")

                if isinstance(node, IdentExpr) and node.name in self.func_sigs:
                    self.pending_calls.append(
                        (node.name, [(a, self._prov_of(a)) for a in args], node.line, node.col))
                node = CallExpr(line=tok.line, col=tok.col, callee=node, args=args)
                provenance.apply_call(self, node)
            else:
                break
        return node

    def parse_primary(self) -> ExprNode:
        tok = self._cur()
        if tok.kind in ('INT_NUM', 'FLOAT_NUM', 'STRING', 'CHAR'):
            self._eat()
            return LiteralExpr(line=tok.line, col=tok.col, code=tok.value, lit_kind=tok.kind)
        if tok.kind in ('BOOL_LIT', 'NULL_LIT'):
            self._eat()
            return LiteralExpr(line=tok.line, col=tok.col, code=tok.value,
                               lit_kind='BOOL' if tok.kind == 'BOOL_LIT' else 'NULL')
        if tok.kind == 'IDENT' and tok.value == 'va_arg' and self.tokens[self.pos + 1].kind == 'LPAREN':
            return self.parse_va_arg()
        if tok.kind == 'IDENT' and tok.value == 'offsetof' and self.tokens[self.pos + 1].kind == 'LPAREN':
            return self.parse_offsetof()
        if tok.kind == 'IDENT':
            self._eat('IDENT')
            self._lookup_symbol(tok.value, tok)
            return IdentExpr(line=tok.line, col=tok.col, name=tok.value)
        if tok.kind == 'LPAREN':
            self._eat('LPAREN')
            e = self.parse_pure_expr()
            self._eat('RPAREN')
            return e
        raise ParseError(f"{self.filename}:{tok.line}:{tok.col}: Unexpected token '{tok.value}'")


# ============================================================================
# 4. C99 Code Generator
