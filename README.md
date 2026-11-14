# Sigil-C（印记-C）

一个小实验项目：把 `.sigil` 转译成 ISO C99。45 个双字符记号 + C99 运算符，外加一些编译期检查。

> 一句话概括：把数据流写在字面上的 C。

[![ci](https://github.com/weird655/Sigil-C/actions/workflows/ci.yml/badge.svg)](https://github.com/weird655/Sigil-C/actions/workflows/ci.yml)
[![tests](https://img.shields.io/badge/tests-201%20%2F%2042%20layers-brightgreen)](test_matrix.py)
[![output](https://img.shields.io/badge/output-ISO%20C99-blue)](#)
[![license](https://img.shields.io/badge/license-CC%20BY%204.0-lightgrey)](LICENSE)

---

## 有什么，没有什么

| 有什么 | 没有什么（为什么） |
|---|---|
| **C99 表面层**：45 个双字符印记 + C 运算符，转译成纯 C99 | 新运行时 —— 有运行时就不再是"表面层"，生成物必须能独立用 gcc 编 |
| **可检查的写法**：`m` 写操作、指针带来源 | 更安全的 C 本身 —— 堆、空指针、未初始化要做数据流分析，单遍转译做不到 |
| **转译期检查**：常量越界、悬空、跨函数逃逸、`r@` 违约 | 跨文件分析 —— 只看单个翻译单元，跨文件要链接期信息 |
| **可退出的产物**：`#line` 映射、`--no-line` 交付、`.h` 输出 | 自己的标准库 —— 直接用 C 的 libc，省掉一整套生态维护 |
| **完整工具链**：build / fmt / check / init / LSP | 包管理与构建系统 —— 交给 C 侧，不另造一套 |

一句话：**不是更快的 C，是"读一遍就能验证"的 C。**

---

## 设计原则

- **最小充分记法**：每个记号必须承载语义；不承载语义的语法不加。
- **空格即断句**：`p* u4` 是指针，`p * q` 是乘法；`o! p* u4 counter` 读作四段（声明 / 指针 / 类型 / 名字）。
- **写操作带牌**：所有状态修改都经 `m` 家族，且不能藏在表达式里——副作用可枚举。
- **生成物可退出**：纯 C99 + `#line`，随时可以丢掉转译器只留生成代码；
  要交给 C 程序员时加 `--no-line`，每行不再插 `#line`。



## 快速开始

需要 Python 3.8+ 与 gcc（clang 亦可）。

```bash
python3 sigilc.py examples/tutorial/01_hello.sigil -o hello.c
gcc -std=c99 -Wall -Wextra -Werror -pedantic hello.c -o hello
./hello
```

```text
Sigil-C tutorial
area(4 x 6) = 24
```

生成的 C 带 `#line`，gcc 报错直接指回 `.sigil`：

```c
#line 11 "01_hello.sigil"
    printf("Sigil-C tutorial\n");
```

---

## 工具链

```bash
# 单文件：转译 + 编译
python3 sigilc.py app.sigil -o app.c
gcc -std=c99 -Wall -Wextra -Werror -pedantic app.c -o app

# 多文件：转译目录下所有 .sigil，再链接成一个可执行文件
python3 sigilc.py --build src -o app --run
#   src/a.sigil -> src/.sigil-build/a.c
#   gcc -std=c99 ... a.c b.c -o app

# 需要给 C 用户链接时，加 --emit-header 同时产出 .sigil-build/*.h
python3 sigilc.py --build src -o app --emit-header
```

新建工程：

```bash
python3 sigilc.py --init demo        # 生成 demo/src/main.sigil、README、.gitignore
python3 sigilc.py --build demo/src -o demo/app --run
```

批量检查（不改文件）：

```bash
python3 sigilc.py --check src          # 整个目录
python3 sigilc.py --check src/a.sigil
python3 sigilc.py --check src --json   # 机器可读诊断（编辑器 / CI）
```

格式化：按空格纪律重排（`--write` 就地写回，`--fmt-check` 只检查、CI 用）：

```bash
python3 sigilc.py --fmt src --write
python3 sigilc.py --fmt src --fmt-check    # 有未格式化文件时退出码为 1
```

`--build` 的其他开关：`--cc clang` 换编译器、`--cflags "-std=c99 -O2"` 换旗标、
`--bounds-check` / `--define` / `--prelude` 会透传给每个文件。

装成命令（可选）：

```bash
pip install -e .
sigilc --build src -o app --run
```

### 编辑器：LSP

`sigilc.py --lsp` 是一个零依赖 LSP 服务（stdio JSON-RPC）：

- 打开/修改文件时推送诊断（与 `--check` 同一套检查，带 range）
- 补全（**默认关闭**，启动加 `--lsp-completion`）：补的是**结构片段**而不是单词——`i?` 展开为 `i? (cond) { ... }`，`s?` 展开为 case 骨架，`s{` 展开为结构体桩，`o!` 展开为 `o! type name;`
- 文档大纲：函数、结构体 / 联合体、枚举（成员作子项）、全局变量

Neovim（内置 LSP）示例：

```lua
vim.lsp.start({
  name = "sigil-c",
  cmd = { "python3", "/path/to/sigilc.py", "--lsp" },
  root_dir = vim.fn.getcwd(),
})
```

Helix、Emacs（lsp-mode）、Sublime LSP 等通用客户端用同一行命令即可。
VS Code 需要额外的客户端扩展；本仓库的 `editors/vscode/` 只含语法高亮。

编辑器：`editors/vscode/` 是最小 VS Code 语法扩展（`.sigil` 高亮、注释与括号配置），
把它复制到 `%USERPROFILE%\.vscode\extensions\sigil-c-1.1.0` 后重启即可。

## 它挡什么

| 问题 | 时机 | 例子 |
|---|---|---|
| 常量下标越界 | 转译期 | `a[5]`，`a` 只有 3 个元素 |
| 指针偏移越界 | 转译期 | `p m+ 3` 之后 `p* p` |
| 返回局部地址 | 转译期 | `r; p@ x;` |
| 局部地址进全局 / 出参 | 转译期 | `g m, p@ x;` |
| 指针活过基对象 | 转译期 | 块内取址，块外使用 |
| 跨函数逃逸 | 转译期 | callee 存参数进全局，caller 传局部地址 |
| `restrict` 违约 | 转译期 | `sum(arr, arr)` |
| 丢 `const` / 指针整数混用 | 转译期 | `o! p* u4 q m, p;`（`p` 是只读） |
| 运行期下标越界 | 运行期 | 加 `--bounds-check` 后 `abort()` |

上表之外的问题不拦——见下一节；逐条实测见 [`MIGRATION.md`](MIGRATION.md)（迁移对照）。

---

## 它不挡什么

| 不挡 | 说明 |
|---|---|
| 堆 | `malloc` / `free` 需自己声明原型，没有堆模型；重复释放、泄漏、悬空不查 |
| 空指针 | 不做空值分析 |
| 未初始化 | 不做定值分析 |
| 窄化 | `c1 c m, 300` 与 C 一样静默截断 |
| 有符号溢出 | 常量折叠拦常量，变量运算不拦 |
| 外部头结构体 | 用 `x!` 手工登记字段；登记错了只有 `t!` + `offsetof` 断言能抓 |
| 指针参数长度 | 参数来源未知，越界不查 |
| 跨文件分析 | 单翻译单元内的函数调用有来源摘要（返回 / 出参）；跨文件、递归、函数指针仍不建模，`--strict` 会把无法证明的参数访问拒掉 |

### 四个实测

| 场景 | 例子 | 转译器 | 实际结果（Windows 示例） |
|---|---|---|---|
| 指针参数长度 | `read(p@ a[0], 100)` 里 `p[i]` | 接受，生成 `p[i]`（**不**加 `SIGIL_IDX`） | 不崩，读到越界内存（UB） |
| 空指针 | `f(0)` 后 `p* p` | 接受 | `0xC0000005` 访问违规 |
| 未初始化 | `o! i4 x; r; x;` | 接受 | 随机返回值；`gcc -Wall` 会警告 |
| 堆 | `free(p); free(p);` | 接受（`malloc` / `free` 需手写原型） | `0xC0000374` 堆损坏 |

> 错误码是 Windows 平台的示例：Linux 上分别是 `Segmentation fault` 与 `free(): double free detected` + abort，macOS 上是 `EXC_BAD_ACCESS`。

指针参数那条尤其要说明：`--bounds-check` 也救不了——参数进来时来源未知，函数内 `p[i]` 不会生成 `SIGIL_IDX`，只能在调用方保证长度。

```sigil
i4 read(p* u4 p, u4 i) { r; (i4)p[i]; }   /* → int32_t read(uint32_t *p, uint32_t i) { return p[i]; } */
```

**空指针**：`0` 是空指针常量，按 C99 语义可隐式转任意指针，所以 `f(0)` 能过类型检查——Sigil-C 保留这条。

```sigil
i4 f(p* u4 p) { r; (i4)p* p; }
i4 main(v.) { r; f(0); }
```

**未初始化**：`o! i4 x;`（裸声明）与 `o! i4 x m, 0;`（带初始化）都合法——`o!` 只标出声明，不强制初始化；转译器不查未初始化，所以裸声明放行。

```sigil
o! i4 x;      /* 裸声明合法，转译器不查未初始化 */
r; x;
```

**堆**：`malloc` / `free` 不是内建，得手写原型；`p* i4` 传给 `p* v.` 参数是隐式转换（C 与 Sigil-C 都允许）；转译器没有堆模型，重复释放照单全收。

```sigil
p* v. malloc(u8 n);
v. free(p* v. p);

o! p* i4 p m, (p* i4)malloc(z? i4);
free(p);   /* p* i4 → p* v. 隐式转换，合法 */
free(p);   /* 重复释放，转译器照单全收 */
```

实际代码应检查 `malloc` 返回值：`i? (p == NULL) { ... }`——Sigil-C 不替你检查。

## 适用与不适用

| 适合 | 不适合 |
|---|---|
| 单文件、重指针、重二进制的工具 | 全栈、GUI、网络服务 |
| 嵌入式 / 寄存器映射 / 协议解析 | 依赖大量系统头字段的工程 |
| 需要"读一遍能验证"的库模块 | 需要包管理与生态的项目 |
| AI 生成 + 人审查的代码 | 多人长期演进的代码库 |

## 语言速览

```sigil
s{ Vec2 { i4 x; i4 y; };

i4 dot(p* c@ Vec2 a, p* c@ Vec2 b) {
    r; a->x * b->x + a->y * b->y;
}

i4 main(v.) {
    o! Vec2 u m, { 3, 4 };
    o! Vec2 v m, { 0x10, 2 };
    i? (dot(p@ u, p@ v) == 56) { printf("ok\n"); }
    r; 0;
}
```

生成：

```c
typedef struct Vec2 Vec2;
struct Vec2 { int32_t x; int32_t y; };

int32_t dot(const Vec2 *a, const Vec2 *b) {
    return ((a->x * b->x) + (a->y * b->y));
}

int32_t main(void) {
    Vec2 u = { 3, 4 };
    Vec2 v = { 0x10, 2 };
    if ((dot((&u), (&v)) == 56)) { printf("ok\n"); }
    return 0;
}
```

书写规格只有一条主线：**空格即断句**——`p* u4` 是「指针 + 类型」，`p * q` 是乘法。完整规矩见 [`SYNTAX.md`](SYNTAX.md) §0.8。

`o!` 是对象声明前缀；**基类型直接开头时可省**（`u4 x;`），用户定义类型与指针仍必须写：

```sigil
u4 counter m, 0;        /* 可省 */
o! SG ctx;                /* 用户类型必须 */
o! p* u4 slot;            /* 指针必须 */
```

**指针怎么读**——从左往右，每层一个记号：

| Sigil-C | C99 | 含义 |
|---|---|---|
| `p* u4` | `uint32_t *` | 指向可写 u4 的指针 |
| `p* c@ u4` | `const uint32_t *` | 指向只读 u4 |
| `c@ p* u4` | `uint32_t * const` | 地址固定，指向物可写 |
| `p* p* u4` | `uint32_t **` | 二级指针 |
| `p* v@ u4` | `volatile uint32_t *` | 指向易变对象 |
| `r@ p* u4` | `uint32_t * restrict` | 只此一条访问路径 |
| `f^(u4) -> u4` | `uint32_t (*)(uint32_t)` | 函数指针 |

印记与运算符的完整定义在 [`SYNTAX.md`](SYNTAX.md)；逐步讲解见 [`TUTORIAL.md`](TUTORIAL.md) 第 3 章。

> **书写约定**：`p*` 紧邻才是指针，乘法要写 `p * q`；写成 `p*q` 会在类型检查报错（被当成解引用），不是静默歧义。见 [`SYNTAX.md`](SYNTAX.md) §0.7。

---

### 标准库

没有自己的标准库，直接用 C 的：

```sigil
#include <string.h>

o! c1[8] buf;
strcpy(p@ buf[0], "hi");
o! i4 n m, (i4)strlen(p@ buf[0]);
```

`#include` 会登记常用原型：`<stdio.h>` / `<stdlib.h>` / `<string.h>` / `<ctype.h>` / `<math.h>` / `<assert.h>`。不在表里的函数手写原型（`i4 foo(...);`），或先用 `x!` 登记外部类型；`math.h` 在 Linux 链接时加 `-lm`。

文件 I/O 也是 C 的：`FILE` 是不透明句柄，`#include <stdio.h>` 后直接用 `p* FILE`：

```sigil
o! p* FILE f m, fopen("out.txt", "w");
i? (f == NULL) { r; 1; }
fprintf(f, "hello %d\n", 42);
fclose(f);
```

`stdin` / `stdout` / `stderr` 同时可用；`FILE` 没有字段，解引用会被拒绝。

## 栈与堆：三种标准写法

栈和堆不是 Sigil-C 的概念，是 C 的；它只提供把两者写对的形状。三条法则各有一个可运行示例：

| 写法 | 解决什么 | 例子 |
|---|---|---|
| **栈 + SBO** | 小对象留栈，超过阈值才进堆；调用方分配，被调方只写 `r@` 区间 | [`18_stack_sbo.sigil`](examples/tutorial/18_stack_sbo.sigil) |
| **Arena** | 把堆退化成栈：分配 = 对齐 + 加法，回收 = 游标归零 | [`19_arena.sigil`](examples/tutorial/19_arena.sigil) |
| **SoA** | 连续数组 + 32 位下标替代指针图，缓存行满载荷 | [`20_soa.sigil`](examples/tutorial/20_soa.sigil) |

```sigil
v. kernel(r@ p* c@ f4 in, r@ p* f4 out, u4 n) {
    o! u4 i m, 0;
    w~ (i < n) { out[i] m, in[i] * 2.0f + 1.0f; i m+ 1; }
}
```

`r@` 让两个区间互不重叠；Arena 用 `off` 当 `sp`，SoA 用 `u4` 下标代替 `p*` 指针。

三个示例都进测试（第 18 层），完整解释见 [`TUTORIAL.md`](TUTORIAL.md) §5.3。

## 45 个印记 + C 运算符

| 组 | 数量 | 印记 |
|---|---|---|
| 控制流 | 11 | `i?` `e:` `w~` `f~` `d~` `s?` `k:` `d:` `r;` `b!` `c^` |
| 类型定义 | 4 | `s{` `u{` `e{` `w!` |
| 声明与修饰 | 5 | `o!` `s@` `a@` `i@` `x!` |
| 类型构造与限定 | 5 | `p*` `c@` `v@` `r@` `f^` |
| 类型与查询 | 5 | `b.` `v.` `z?` `g?` `a?` |
| 赋值 | 5 | `m,` `m+` `m-` `m*` `m/` |
| 运算符与取址 | 6 | `p@` `->` `<<` `>>` `<=` `>=` |
| 语句 | 4 | `t!` `g!` `l!` `d!` |

合计 **45**：40 个"字母 + 标点"、5 个"标点 + 标点"，全部 2 字符。
另有 **10 个 C99 运算符**（不是双字符印记）：`&&` `||` `!` `&` `|` `^` `~` `==` `!=`，以及 `mod`。

不算印记的：`a!N`（对齐，字母 + `!` + 2 的幂）、`...`（变参）、`true` / `false` / `NULL`（字面量）、`offsetof` / `va_start` / `va_arg` / `va_end` / `va_copy`（内建）。

## 命令行

```bash
python3 sigilc.py <input.sigil> [-o out.c] [选项]
```

| 选项 | 作用 |
|---|---|
| `-o, --output PATH` | 输出路径（单文件模式是 `.c`，`--build` 模式是可执行文件） |
| `--emit-header` | 同时生成同名 `.h`（`--build` 下为每个源文件生成） |
| `--header PATH` | 指定头文件路径（隐含 `--emit-header`；不能与 `--build` 同用） |
| `--check PATH` | 只做检查，不写文件；PATH 可以是文件或目录 |
| `--json` | 配合 `--check`：输出结构化诊断 |
| `--build [DIR]` | 转译 DIR 下所有 `.sigil` 并链接成一个可执行文件 |
| `--run` | 配合 `--build`：构建后直接运行 |
| `--cc NAME` / `--cflags "<flags>"` | 换编译器 / 旗标（`--build`） |
| `--fmt [PATH]` | 按空格纪律格式化；省略 PATH 表示当前目录 |
| `--write` | 配合 `--fmt`：就地写回（不加则打到 stdout） |
| `--fmt-check` | 配合 `--fmt`：只报告需要格式化的文件（退出码 1） |
| `--init [DIR]` | 生成最小工程（`src/main.sigil` + README + `.gitignore`） |
| `--force` | 配合 `--init`：覆盖已存在的文件 |
| `--lsp` | 启动 LSP（stdio JSON-RPC） |
| `--lsp-completion` | 配合 `--lsp`：开启片段补全（默认关闭） |
| `--strict` | 拒绝来源无法证明的参数下标/解引用。研究开关：22 个教程示例里 5 个用了参数下标，会失败；默认关闭 |
| `--no-line` | 不生成 `#line`：交付源更像普通 C（报错指向 `.c`；注释不随行） |
| `--bounds-check` | 运行期数组下标检查（默认开启，越界 `abort()`） |
| `--no-bounds-check` | 关闭运行期下标检查（release 用） |
| `--define NAME=VALUE` | 预定义宏常量，可重复 |
| `--emit-prelude PATH` | 导出共享宏前导头 |
| `--prelude NAME` | 改用 `#include "NAME"`，不内联宏 |
| `--version` / `-h` | 版本与帮助 |

---

## 示例

| 中文名 | 文件 | 讲什么 | 输出 |
|---|---|---|---|
| 教程配套 | [`tutorial/01..22`](examples/tutorial/) | 软件 / 嵌入 / 硬件三线 | 见 `TUTORIAL.md`（教程） |
| 虚拟机 | [`vm.sigil`](examples/vm.sigil) | 函数指针表 + 字节码 | `42` |
| 寄存器映射 | [`regmap.sigil`](examples/regmap.sigil) | `packed` + 位域 + `offsetof` 断言 | `ctrl=0x005d` |
| 回调表 | [`callbacks.sigil`](examples/callbacks.sigil) | 全局函数指针表 | `quit after 2 ticks` |
| 帧解析 | [`wire.sigil`](examples/wire.sigil) | 大端帧解析 | `frames=2 bytes=9` |
| 内存池 | [`pool.sigil`](examples/pool.sigil) | 三级指针、读写视图分流 | `checksum=1012` |

内存池的布局图、指针链和权限表在 [`TUTORIAL.md`](TUTORIAL.md) §3.6。

虚拟机那台机器的核心只有这几行（节选）：

```sigil
o! (f^(p* VM) -> v.)[10] DISPATCH m, { op_push, op_add, ..., op_halt };
o! (p* c@ c1)[10] NAMES m, { "PUSH", "ADD", ... };
DISPATCH[op](vm);
```

C 里对应 `void (*DISPATCH[10])(VM *)`——名字埋在星号中间；这里从左往右读完。

---

## 作为库使用

生成的 `.c` 可以被普通 C 代码链接，加 `--emit-header` 同时产出公共头文件：

```bash
python3 sigilc.py vec.sigil -o vec.c --emit-header
gcc -std=c99 -Wall -Wextra -Werror -pedantic vec.c app.c -o app
```

```c
#include "vec.h"          /* 类型、原型、extern 全局，全自动生成 */

int main(void) {
    Vec2 a = { 3, 4 }, b = { 10, 2 };
    return dot(&a, &b) == 38 ? 0 : 1;
}
```

`s@` 修饰的符号是文件内部链接，不会进头文件。**C 用户不需要安装转译器。**

---

## 文档

| 中文名 | 文件 | 内容 |
|---|---|---|
| 教程 | [`TUTORIAL.md`](TUTORIAL.md) | Part 0–7：从 Hello 到指针/文件/回调/栈堆三写法，22 个可运行示例 |
| 速查表 | [`SYNTAX.md`](SYNTAX.md) | 印记与运算符清单、类型绑定、运算符优先级、**书写规格（空格纪律）** §0.8 |
| 迁移对照 | [`MIGRATION.md`](MIGRATION.md) | C → Sigil-C 对照，23 条陷阱逐条实测 |
| 更新日志 | [`CHANGELOG.md`](CHANGELOG.md) | 版本演进与每层测试的覆盖明细 |
| 贡献指南 | [`CONTRIBUTING.md`](CONTRIBUTING.md) | 环境、一键检查、加印记清单、发布流程 |
| 架构 | [`ARCHITECTURE.md`](ARCHITECTURE.md) | 分层、依赖方向、预算、非目标 |
| 汇编实验 | [Sigil-ASM](https://github.com/weird655/Sigil-ASM) | 独立的 `.sigil → x86-64` 概念验证，与 Sigil-C 分仓 |

> 文件名是英文，第一列是中文名——按中文找即可。

---

## 内部结构

实现拆成 `sigilc_core/` 包，`sigilc.py` 只是入口壳（保留 `python sigilc.py` 与 `pip install` 的用法）：

```text
.sigil → Lexer（DFA，双字符印记）
       → Parser（递归下降 + AST）
       → 静态检查（类型 / 边界 / 指针来源 / 逃逸）
       → CodeGenerator（C99 + #line）
```

| 模块 | 内容 |
|---|---|
| `lexer.py` | `Token`、45 个印记表 + 运算符表、DFA 词法器 |
| `type_system.py` | `TypeNode` 家族、类型等价、C 声明符格式化 |
| `nodes.py` | AST 节点、`emit_expr`、`Prov` |
| `parser.py` | 递归下降 + 静态检查（类型 / 来源 / 逃逸） |
| `codegen.py` | `CodeGenerator`（C99 + `#line`） |
| `api.py` | `compile_source` / `check_source` / `compile_header` / 格式化 / LSP |
| `cli.py` | `main` / `cli`（参数、`--build`、`--check`、`--init`） |

依赖单向：`lexer → type_system → nodes → parser → codegen → api → cli`；`sigilc.py` 从 `sigilc_core` 转出全部公开名字。

依赖方向、预算和非目标由 [`ARCHITECTURE.md`](ARCHITECTURE.md) 定义，第 34 层测试强制。

## 测试矩阵

201 项 / 42 层，每层一个主题：

| 层 | 主题 |
|---|---|
| 1–4 | 词法、语法、类型、运算符 |
| 5–6 | 结构体 / 联合体 / 枚举、控制流 |
| 7–10 | sizeof / 属性 / 初始化 / 语言补全 |
| 11–13 | 声明、表达式、越界防护 |
| 14–16 | 外部类型、指针来源、跨函数逃逸 |
| 17–18 | 示例、教程 |
| 19–20 | `o!` 省略、内存池 |
| 21–24 | build / fmt / check / 头文件 |
| 25–28 | init / LSP / 大纲 / 低频印记 |
| 29–31 | framing / CLI 进程内 / 模糊测试 |
| 32–33 | 属性测试 / LSP 全流程 |
| 34 | 架构守卫（依赖方向 / 标准库 / 预算） |
| 35 | libc 头文件原型登记 |
| 36 | FILE* 不透明句柄与文件 I/O |
| 37–38 | 差分执行（C vs Sigil-C） / 随机程序执行比对 |
| 39 | stdin 驱动的程序 |
| 40 | 遮蔽作用域的来源还原 |
| 41 | `--strict` 拒绝无法证明的参数访问 |
| 42 | 跨函数来源摘要（返回 / 出参） |
| 43 | 调用点长度契约（常量下标 / `--strict`） |

## 测试与 CI

```bash
python3 test_matrix.py        # 201 项 / 42 层，需要 gcc
```

每层都编译并运行生成的 C（`-std=c99 -Wall -Wextra -Werror -pedantic`），其中第 17、18 层直接构建 `examples/` 与教程程序并断言输出。**测试数字以 `test_matrix.py` 的输出为准**，README 与 CHANGELOG 只是引用。

本地一键质量门：

```bash
python tools/check.py            # py_compile → ruff → mypy → 201 项测试
python tools/check.py --coverage # 附覆盖率（门槛 85%）
python tools/fuzz.py --iterations 300   # 确定性变异测试
python tools/propgen.py --count 30       # 随机合法程序 -> gcc
python tools/difftest.py                 # 7 组同逻辑 C / Sigil-C 对拍（含 stdin）
python tools/runcheck.py --count 30      # 随机程序的输出与 Python 参考值比对
python tools/bench.py --runs 20 --max-ms 500  # 转译耗时基线
```

CI 在 `ubuntu-latest` 上用 Python 3.10 / 3.12 跑完整矩阵；另有一个 `windows-latest` job 做 `py_compile`、`--check examples`、转译 VM 示例，并在有 gcc 时编译运行：

[`ci.yml`](.github/workflows/ci.yml) · [最近一次运行](https://github.com/weird655/Sigil-C/actions/workflows/ci.yml)

---

## 常见问题

**为什么不做成 Rust / Go 那样的独立语言？**
目标不是替代运行时，而是给 C 换一层可检查的表面。产物是纯 C99，可以用 `gcc` 直接编译、被普通 C 代码链接。

**能上生产吗？**
取决于用途。单文件、重指针、重二进制的模块风险较低；堆、空指针、未初始化这些边界它不拦（见「它不挡什么」），需要你自己守。

**45 个印记 + C 运算符会不会太多？**
是闭集，而且冻结。学的时候按需查 [`SYNTAX.md`](SYNTAX.md)（速查表），不用一次背完。

**`p*` 为什么看起来像乘法？**
不是缺陷：`p*` 必须紧邻，乘法必须留空格；写成 `p*q` 会直接报类型错误（被当成解引用）。见 [`SYNTAX.md`](SYNTAX.md) §0.7。

**和 C 的关系是什么？**
`.sigil` 是源，C 是目标。`#line` 映射让 gcc 报错指回 `.sigil`；哪天不想用了，保留生成的 `.c` 即可。

**有包管理 / 标准库吗？**
没有，也不打算有。它是小工具，不是生态。

## 状态

- **维护模式**：不再新增语言记号；修复缺陷、补文档、少量 C99 完备性补充（如 libc 原型、跨函数来源摘要）仍会接受。
- 版本 **1.1**，tag `v1.1` + [GitHub Release](https://github.com/weird655/Sigil-C/releases/tag/v1.1) 已发布；语法冻结（v1.x 只加不改）。
- 201 项测试，Windows、WSL Ubuntu、GitHub Actions 三处通过；ruff / mypy 零告警，覆盖率门槛 85%。
- 已有：45 个印记 + C 运算符、指针来源、跨函数逃逸、`r@` 校验、外部类型 `x!`、头文件输出、LSP（诊断 / 大纲 / 片段补全）、格式化器、多文件构建、栈/堆三写法。
- 未做：堆模型、完整头文件解析、跨文件分析、包管理。

## 版本策略

- **v1.x 只加不改**：既有 `.sigil` 源码与印记/运算符不再破坏性变更。
- 必须改动时，先给一个版本的弃用期，再在下个主版本移除。
- 印记集合冻结：新增印记必须有非它不可的场景，并同步进 `SYNTAX.md` 与 `t!` 测试。
- 生成物永远可退出：纯 C99 + `#line`，随时可以丢掉转译器只留生成代码。

---

## 许可证

- **代码**：MIT，全文见 [`LICENSE`](LICENSE)。
- **文档**：CC BY 4.0，全文见 [`LICENSE-CC-BY-4.0`](LICENSE-CC-BY-4.0)。

> 代码用 MIT 是软件惯例（含免责条款、无 copyleft、与 C / Python 生态兼容）；文档用 CC BY 是因为它本来就是写给读的。

> 这是一种深奥难懂的语言——它的语法和汇编一样简单。

最后的话：[MEMORIAL.md](MEMORIAL.md)。
