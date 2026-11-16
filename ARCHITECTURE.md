# 架构

这份文档是给维护者的：**哪些是刻意的小，哪些是刻意不做**。超大型系统的维护成本我们不接。

## 定位

- 不造运行时，只造 C99 表面层
- 单翻译单元分析、**零第三方运行时依赖**
- 一个入口壳（`sigilc.py`）+ 一个包（`sigilc_core/`）

## 非目标

- 包管理、标准库、插件生态
- 跨文件分析、堆生命周期、多线程
- 通用 C 替代品
- 超过 5k 行的核心

## 分层与依赖方向

```text
cli → api → codegen → parser → nodes → type_system → lexer
                    ↘ preamble → version
```

| 模块 | 职责 | 允许依赖 |
|---|---|---|
| `lexer.py` | Token、45 个印记表 + 运算符表、DFA | 无 |
| `version.py` | 版本号唯一来源 | 无 |
| `preamble.py` | 生成文件开头的可移植宏 | `version` |
| `type_system.py` | `TypeNode`、类型等价、C 声明符 | `lexer` |
| `nodes.py` | AST 节点、`emit_expr`、`Prov` | `type_system` |
| `netlist.py` | 飞线网表渲染（万用表） | 无 |
| `confine.py` | 封锁域 `![mask]!` 与协调集 `!/[id]/!` | `nodes` |
| `packages.py` | 实验性 `!n!` 包别名（娱乐，勿用） | `nodes` |
| `provenance.py` | 跨函数来源摘要（返回来源 / 出参回写） | `nodes` |
| `parser.py` | 递归下降 + 静态检查 | `lexer` `nodes` `provenance` `type_system` |
| `codegen.py` | C99 + `#line` 生成 | `preamble` `nodes` `type_system` |
| `api.py` | 编译、检查、格式化、LSP | `codegen` `lexer` `nodes` `parser` |
| `cli.py` | 参数与工具链命令 | `api` `lexer` `nodes` `preamble` `version` |

规则由 `test_matrix.py` 第 34 层强制：模块级 import 必须命中上表、无环、只允许标准库、总行数 ≤ 6200、`parser.py` ≤ 2700、`provenance.py` ≤ 400、`packages.py` ≤ 450、`confine.py` ≤ 400、`netlist.py` ≤ 200。

**唯一的例外**：`type_system` 在函数内延迟导入 `nodes`（`format_c_declarator` / `types_equal` 需要 `emit_expr`）。不要再增加新的函数内跨层导入——要加先在 issue 里说明。

## 数据流

```text
.sigil → Lexer → Parser（类型 / 指针来源 / 逃逸）→ CodeGenerator → C99
```

## 不变量

- 版本号只在 `sigilc_core/version.py` 一处
- 前导宏只在 `preamble.py` 一处
- 运行时只 import 标准库（`sys.stdlib_module_names`）
- `sigilc.py` 只做转发，不放逻辑
- `--line` 默认开、`--no-line` 交付用（见 README）

## 预算（测试会红）

| 项 | 上限 |
|---|---|
| `sigilc_core/` 总行数 | 6200 |
| `parser.py` | 2700 |
| `provenance.py` | 400 |
| `packages.py` | 450 |
| `confine.py` | 400 |
| `netlist.py` | 200 |

超预算时先拆模块或删功能，**不上调预算**。

## 扩展点

- 加印记 / 改语义：按 `CONTRIBUTING.md` 的清单走
- 新工具命令：进 `cli.py`，重逻辑放 `api.py`
- 新生成物宏：进 `preamble.py`，不要散落在 codegen

## 维护策略

- v1.x 只加不改；破坏性变更要弃用期
- 发版：`CONTRIBUTING.md` 的发布段（tag → `release.yml`）
- 不引入第三方运行时依赖；测试/检查工具（ruff/mypy/coverage）只进 CI

## 附录：配电箱 v1（未实现，原始第一版）

> **状态：历史设计，未实现，不可用，不提供开关。** 它不是当前 `!n!` 的一部分，也不会有 `--wire-guard` 这个 flag。用户不需要、也不能手工接这个配电箱。

### 为什么叫"不能补上"

配电箱（frame-token guard）不是外挂，它必须从局部包降级的第一天就在：

- 每个局部包绑定、包套包、`!>n<!` 别名都要带 token
- 每个函数入口要 push token，每个 return 要汇到 epilogue 去 pop
- 每次 `!/n/!` 访问要先查 token 是否还在活跃栈

 retrofit 进现有 codegen 等于改所有局部包的降级、所有返回路径和 ABI。它不是"加个 flag"，是"换一台配电柜"。所以只能作为原始第一版留在档案里。

### v1 的设

- 活跃帧 token 用一个 32 层的 LIFO 栈：`uint32_t frames[32]`，128 字节
- 文件级包 token = 0，访问零检查
- 局部包槽多一个 `uint32_t tok`；绑定写当前帧 token
- 包套包 / `!>n<!` 复制 token，不复制"当前帧"
- 访问：token 不在栈里 → `SIGIL_TRAP()`
- 32 层溢出 → 入口 trap，不覆盖活帧
- 退出：pop 自己的 token；递归/嵌套只影响自己
- `longjmp`、多线程、裸 `p*` 仍是洞；文档要标

### 为什么

- 128 字节不大，但每个含局部包的函数都要 prologue/epilogue，所有 return 都要改道
- 它把"飞线"变成"带保险丝的飞线"，复杂度和维护成本都上一个台阶
- Layer 2 最终选择了**裸危险**：不给生命周期、不升堆、不加 token；悬垂就是悬垂

### 当前真实状态

- 没有 frame token，没有 guard 表，没有 `--wire-guard`
- `--shadow-stack` 只是诊断：打印 Sigil 帧 id/名字，不做 token 校验、不阻止悬垂；它不是配电箱 v1
- 局部包悬垂仍是 UB；`-Wdangling-pointer` 被 preamble 关掉
- `--netlist` 只能看静态网表，不能看运行时死活
- 危险工具，请勿使用

