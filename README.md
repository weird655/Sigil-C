# Sigil-C（印记-C）

把 C 写成**从左往右读**的样子。编译到 ISO C99，越界、悬垂、逃逸挡在编译前。

[![ci](https://github.com/weird655/Sigil-C/actions/workflows/ci.yml/badge.svg)](https://github.com/weird655/Sigil-C/actions/workflows/ci.yml)
[![tests](https://img.shields.io/badge/tests-169%20%2F%2018%20layers-brightgreen)](test_matrix.py)
[![output](https://img.shields.io/badge/output-ISO%20C99-blue)](#)
[![license](https://img.shields.io/badge/license-CC%20BY%204.0-lightgrey)](LICENSE)

---

## 它是什么，不是什么

| 是 | 不是 |
|---|---|
| C99 的**表面层**：52 个双字符印记，转译为纯 C99 | 新运行时：没有 GC、没有 VM、零开销 |
| **可检查的写法**：写操作带 `m`，指针带来源 | 更安全的 C 本身：堆、空指针、未初始化仍归你 |
| **可退出**的产物：`#line` 映射 + 标准 C | 有生态的语言：没有包管理、没有标准库 |
| 适合单文件、重指针、重二进制的程序 | 适合全栈、GUI、需要大量系统头的工程 |

一句话：**不是更快的 C，是"读一遍就能验证"的 C。**

---

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

## 它挡什么

| 问题 | 时机 | 例子 |
|---|---|---|
| 常量下标越界 | 转译期 | `a[5]`，`a` 只有 3 个元素 |
| 指针偏移越界 | 转译期 | `p m+ 3` 之后 `p* p` |
| 返回局部地址 | 转译期 | `r; a& x;` |
| 局部地址进全局 / 出参 | 转译期 | `g m, a& x;` |
| 指针活过基对象 | 转译期 | 块内取址，块外使用 |
| 跨函数逃逸 | 转译期 | callee 存参数进全局，caller 传局部地址 |
| `restrict` 违约 | 转译期 | `sum(arr, arr)` |
| 丢 `const` / 指针整数混用 | 转译期 | `o! p* u4 q m, p;`（`p` 是只读） |
| 运行期下标越界 | 运行期 | 加 `--bounds-check` 后 `abort()` |

堆、空指针、未初始化、窄化、有符号溢出**不在保护范围**——完整清单和实测输出见 [`MIGRATION.md`](MIGRATION.md)。

---

## 语言速览

```sigil
s{ Vec2 { i4 x; i4 y; };

i4 dot(p* c@ Vec2 a, p* c@ Vec2 b) {
    r; a->x * b->x + a->y * b->y;
}

i4 main(v.) {
    o! Vec2 u m, { 3, 4 };
    o! Vec2 v m, { 0x10, 2 };
    i? (dot(a& u, a& v) =? 56) { printf("ok\n"); }
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

52 个印记的完整定义在 [`SYNTAX.md`](SYNTAX.md)；逐步讲解见 [`TUTORIAL.md`](TUTORIAL.md) 第 3 章。

> **已知弱点**：`p*` 与乘法在字形上撞脸。书写约定见 [`SYNTAX.md`](SYNTAX.md) §0.7。

---

## 命令行

```bash
python3 sigilc.py <input.sigil> [-o out.c] [选项]
```

| 选项 | 作用 |
|---|---|
| `-o, --output PATH` | 输出 `.c` 路径（默认同名 `.c`） |
| `--emit-header` | 同时生成同名 `.h` |
| `--header PATH` | 指定头文件路径（隐含 `--emit-header`） |
| `--check` | 只做检查，不写任何文件 |
| `--bounds-check` | 运行期数组下标检查（越界 `abort()`） |
| `--define NAME=VALUE` | 预定义宏常量，可重复 |
| `--emit-prelude PATH` | 导出共享宏前导头 |
| `--prelude NAME` | 改用 `#include "NAME"`，不内联宏 |
| `--version` / `-h` | 版本与帮助 |

---

## 示例

| 文件 | 讲什么 | 输出 |
|---|---|---|
| [`tutorial/01..07`](examples/tutorial/) | 教程配套：软件 / 嵌入 / 硬件 | 见 [`TUTORIAL.md`](TUTORIAL.md) |
| [`vm.sigil`](examples/vm.sigil) | 堆栈虚拟机：函数指针表 + 字节码 | `42` |
| [`regmap.sigil`](examples/regmap.sigil) | MMIO：`packed` + 位域 + `offsetof` 断言 | `ctrl=0x005d` |
| [`callbacks.sigil`](examples/callbacks.sigil) | 全局函数指针表 | `quit after 2 ticks` |
| [`wire.sigil`](examples/wire.sigil) | 大端帧解析 | `frames=2 bytes=9` |

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

| 文件 | 内容 |
|---|---|
| [`TUTORIAL.md`](TUTORIAL.md) | 教程：软件 / 嵌入 / 硬件三个方向，每章一个可运行程序 |
| [`SYNTAX.md`](SYNTAX.md) | 52 个印记的闭集清单、类型绑定、运算符优先级 |
| [`MIGRATION.md`](MIGRATION.md) | C → Sigil-C 对照，23 条陷阱逐条实测 |
| [`CHANGELOG.md`](CHANGELOG.md) | 版本演进与每层测试的覆盖明细 |

---

## 测试与 CI

```bash
python3 test_matrix.py        # 169 项 / 18 层，需要 gcc
```

每层都编译并运行生成的 C（`-std=c99 -Wall -Wextra -Werror -pedantic`），其中第 17、18 层直接构建 `examples/` 与教程程序并断言输出。

CI 在 `ubuntu-latest` 上用 Python 3.10 / 3.12 各跑一遍：

[`ci.yml`](.github/workflows/ci.yml) · [最近一次运行](https://github.com/weird655/Sigil-C/actions/workflows/ci.yml)

---

## 版本策略

- **v1.x 只加不改**：既有 `.sigil` 源码与 52 个印记不再破坏性变更。
- 必须改动时，先给一个版本的弃用期，再在下个主版本移除。
- 印记集合冻结：新增印记必须有非它不可的场景，并同步进 `SYNTAX.md` 与 `t!` 测试。
- 生成物永远可退出：纯 C99 + `#line`，随时可以丢掉转译器只留生成代码。

---

## 许可证

代码与文档以 **CC BY 4.0** 发布，全文见 [`LICENSE`](LICENSE)。可复制、修改、再分发（含商业用途），保留署名与许可证链接即可。

> CC BY 4.0 不含专利授权条款；如需软件惯例，可叠加 MIT 双许可。
