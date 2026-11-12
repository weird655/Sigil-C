# 贡献指南

这个仓库很小，规则只有一条：**改动必须能被机器验证**。下面是你需要的全部流程。

## 环境

- Python 3.10+
- `gcc`（C99；Windows 用 MSYS2 / MinGW）
- 开发工具：`python -m pip install ruff mypy coverage`

## 一键检查

```bash
python tools/check.py            # 编译 + ruff + mypy + 186 项测试
python tools/check.py --coverage # 同上，测试带覆盖率（门槛 85%）
python tools/fuzz.py --iterations 300   # 变异模糊测试（CI 跑 300 次）
python tools/propgen.py --count 40       # 随机合法程序，gcc 必须能编译
python tools/difftest.py                 # C 与 Sigil-C 同逻辑对拍
python tools/runcheck.py --count 30      # 随机程序输出 vs Python 参考值
python tools/bench.py --runs 20 --max-ms 500  # 性能基线（CI 卡 500ms）
```

CI 在 Ubuntu（py3.10 / 3.12）与 Windows 上跑同样的步骤。提交前本地必须全绿。

第 34 层是架构守卫：模块级依赖方向、只允许标准库、总行数与 `parser.py` 行数预算；分层说明见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

## 测试数字只有一处来源

测试数 = `test_matrix.py` 的输出（当前 186 项 / 29 层）。README、CHANGELOG 只是引用，不要手改数字；CI 的步骤名也不带数字。

## 加一个印记（或改语义）

按顺序改，缺一步 CI 或文档就对不上：

1. `sigilc.py`：`SIGIL_KEYWORDS` / `SIGIL_OPERATORS` 加词法条目
2. `sigilc.py`：`Parser` 里加解析分支（新节点放 AST 区）
3. `sigilc.py`：`CodeGenerator` 里加生成分支；需要宏就加到 `C99_HEADER_BODY`
4. `test_matrix.py`：新增一层，至少覆盖「接受 + 生成物可编译运行 + 一个拒绝用例」
5. `SYNTAX.md`：§0.5 分组计数、对应章节的表行
6. `README.md`：54 个印记的合计（如果总数变了）
7. `MIGRATION.md`：给出等价的 C 写法
8. `CHANGELOG.md`：记一条

总数变化时，`SYNTAX.md` 的合计、README 的合计、`a!N` 例外说明三处必须同时改。

## 代码约定

- 中文注释，解释**为什么**，不复述代码
- 空格即断句：`p* u4` 是指针，`p * q` 是乘法（见 SYNTAX §0.7）
- 长行不强制换行（中文按显示宽度算），但一个函数超过 ~80 行要拆
- 实现在 `sigilc_core/`（lexer → type_system → nodes → parser → codegen → api → cli），依赖必须单向；`sigilc.py` 只是入口壳，不要往里加逻辑

## 提交与 PR

- 一个 PR 一件事；说明「改了什么 / 为什么 / 怎么验证」
- 提交信息用英文，祈使句，首行 ≤ 72 字符
- PR 里贴 `python tools/check.py` 的输出
- 破坏性变更必须先在 issue 里讨论

## 发布

```bash
git tag -a v1.x -m "Sigil-C 1.x"
git push origin main
git push origin v1.x
```

推 tag 后 `.github/workflows/release.yml` 会自动建 GitHub Release（自动生成 release notes）。发版前确认：

- `python tools/check.py --coverage` 全绿
- `CHANGELOG.md` 有对应小节
- README 的状态段版本号与 tag 一致
