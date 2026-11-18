# Sigil-C for VS Code

`.sigil` 语法高亮 + **实时 LSP 诊断**（错误 + 未使用局部变量警告）。

## 安装（本地目录）

把整个 `editors/vscode` 复制到 VS Code 扩展目录，然后重启编辑器：

- Windows：`%USERPROFILE%\.vscode\extensions\sigil-c-1.3.3`
- macOS / Linux：`~/.vscode/extensions/sigil-c-1.3.3`

打开任意 `.sigil` 文件，右下角应显示 **Sigil-C**，底部 Problems 面板会实时刷新诊断。

## 命令

| 命令 | 快捷键 |
|---|---|
| Sigil-C: Check Current File | `Ctrl+Alt+C` |
| Sigil-C: Format Current File | `Ctrl+Alt+F` |
| Sigil-C: Build Workspace | 命令面板 |
| Sigil-C: Show Output | 命令面板 |
| Sigil-C: Restart Language Server | 命令面板 |

## 打包 / 发布

```bash
cd editors/vscode
npm install
npx @vscode/vsce package     # 生成 .vsix
npx @vscode/vsce publish     # 需要 publisher PAT
```

Marketplace publisher：`weird655`。

## 配置

| 设置 | 默认 | 说明 |
|---|---|---|
| `sigilC.pythonPath` | `python`（Windows）/ `python3` | Python 解释器 |
| `sigilC.cliPath` | `sigilc.py` | `sigilc.py` 路径，绝对或工作区相对 |
| `sigilC.diagnostics` | `true` | 是否启用实时诊断 |

扩展启动：

```text
<python> <sigilc.py> --lsp
```

通过 JSON-RPC `publishDiagnostics` 接收：

- 词法/语法/语义错误（severity 1）
- 未使用局部变量警告（severity 2）

## 覆盖范围

| 类别 | 例子 |
|---|---|
| 控制流 | `i?` `e:` `w~` `f~` `s?` `k:` `r;` `b!` `c^` |
| 声明 | `o!` `s@` `i@` `x!` `t!` `g!` `l!` `w!` `a!16` |
| 指针 / 限定 | `p*` `c@` `v@` `r@` `p@` `f^` `b.` `v.` `z?` `g?` |
| 赋值 | `m,` `m+` `m-` `m*` `m/` |
| 运算符 | `==` `!=` `&&` `||` `|` `&` `^` `->` `<<` `>>` `<=` `>=` |
| 其它 | 数字、字符串、字符、`//` 与 `/* */` 注释、预处理行 |

## 未做

- 语义补全 / 跳转 / 重命名
- 跨文件索引
- 保存时自动修复

补全可以使用：

```bash
python sigilc.py --lsp --lsp-completion
```

然后把扩展的启动参数改成带 `--lsp-completion`。
