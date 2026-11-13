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
| `provenance.py` | 跨函数来源摘要（返回来源 / 出参回写） | `nodes` |
| `parser.py` | 递归下降 + 静态检查 | `lexer` `nodes` `provenance` `type_system` |
| `codegen.py` | C99 + `#line` 生成 | `preamble` `nodes` `type_system` |
| `api.py` | 编译、检查、格式化、LSP | `codegen` `lexer` `nodes` `parser` |
| `cli.py` | 参数与工具链命令 | `api` `lexer` `nodes` `preamble` `version` |

规则由 `test_matrix.py` 第 34 层强制：模块级 import 必须命中上表、无环、只允许标准库、总行数 ≤ 5200、`parser.py` ≤ 2600、`provenance.py` ≤ 400。

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
| `sigilc_core/` 总行数 | 5200 |
| `parser.py` | 2600 |
| `provenance.py` | 400 |

超预算时先拆模块或删功能，**不上调预算**。

## 扩展点

- 加印记 / 改语义：按 `CONTRIBUTING.md` 的清单走
- 新工具命令：进 `cli.py`，重逻辑放 `api.py`
- 新生成物宏：进 `preamble.py`，不要散落在 codegen

## 维护策略

- v1.x 只加不改；破坏性变更要弃用期
- 发版：`CONTRIBUTING.md` 的发布段（tag → `release.yml`）
- 不引入第三方运行时依赖；测试/检查工具（ruff/mypy/coverage）只进 CI
