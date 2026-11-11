# Sigil-C (印记-C) v2.0.0

Sigil-C 是一种面向系统编程、游戏底层内核（ECS、网格平流、细胞自动机）与高密度代码生成的 ISO C99 前缀印记转译语言。它采用“单字母词根 + 语法标点后缀”的双字符印记（2-Char Sigil）与从左向右的前缀类型记法，通过单文件递归下降转译器（`sigilc.py`）将 `.sigil` 源码转换为带 `#line` 映射的 ISO C99 代码，交由 GCC 或 Clang 进行后端编译与优化。

> **v2.0.0 语法升级（破坏兼容）**：只读限定符从 `c$` 改为 `c@`，旧写法 `c$` 不再接受；迁移时将源码中的 `c$` 替换为 `c@`。
>
> **v1.0.0 赋值印记迁移**：复合赋值统一为 `m+`、`m-`、`m*`、`m/`。旧写法 `a+`、`s-`、`d/` 已移除；从 v0.5.2 迁移时分别替换为 `m+`、`m-`、`m/`，`m*` 保持不变。

## 核心设计特点

* **双字符正交印记与前瞻消歧**：控制流以 `? / : / ~ / ! / ^ / ;` 结尾（如 `i?`、`e:`、`w~`、`f~`、`s?`、`k:`、`d:`、`r;`）；对 `v.` / `b.` 类型印记引入第 3 字符前瞻，自动区分 `(v.)` 空参类型与单字母结构体变量的成员访问 `v.x` / `b.x`。
* **统一赋值印记**：`m,` 表示普通赋值，`m+`、`m-`、`m*`、`m/` 表示复合赋值。`m` 标出状态修改，后缀标出运算；例如 `total m+ cell` 对应 C 的 `total += cell`。
* **前缀线性类型声明**：将指针（`p*`）、只读限定（`c@`）、定长数组（`Type[N]` / `(p* Type)[N]`）与函数指针（`f^(...) -> Ret`）统一为从左向右的前缀组合结构，由 AST `format_c_declarator()` 展开为 C99 声明符。
* **纯表达式与赋值语句分离**：语法层将赋值语句（`parse_assign_or_expr_no_semi`）与纯表达式（`parse_pure_expr`）拆分为独立入口，禁止在 `i?`、`w~`、`f~` 条件判断或算术子表达式中混入 `m,`、`m-` 等赋值副作用。
* **受限子集静态检查**：内置针对当前语言子集的类型推导（涵盖一元/二元算子、指针加减与指针差 `ptrdiff_t`、三元 `const` 合并与常规算术提升）、深层左值 `const` 传播（含 `const` 结构体数组成员的只读元素传播）、完整对象类型（Complete Object Type）校验、C99 标准头文件内建函数签名识别、非 `void` 函数返回路径检查，以及带八进制/十六进制/除零/移位越界/64 位溢出检查的向零截断整数常量折叠。

### 紧凑平流更新示例

下面摘出平流内核中读取、计算、写回和累计的部分；`...` 表示省略的循环与外围代码：

```sigil
p* c@ u4 src m, g->rd;
p* u4 dst m, g->wr;
u4 total m, 0;
...
u4 cell m, src[y * W + x];
dst[y * W + x] m, (cell >> 2) + (cell >> 4);
total m+ cell;
...
r; (i4)total;
```

逐行看：`p* c@ u4 src` 声明指向只读 `u4` 元素的源指针；`p* u4 dst` 是可写目标指针。`m,` 用于初始化变量，`total m+ cell` 则把当前单元值累加到 `total`，相当于 C 的 `total += cell`。中间两行从源数组读取 `cell`，按移位公式计算后写入目标数组。最后 `r;` 返回累计结果，并将 `u4` 转为 `i4`；实际使用时应保证 `total` 落在 `i4` 可表示范围内。

## 快速开始

### 环境要求

* Python 3.8+（仅使用标准库）
* GCC 或 Clang（支持 `-std=c99`）

### 编译与验证工作流

```bash
# 1. 将 Sigil-C 源码转译为 ISO C99 代码
python3 sigilc.py golden.sigil -o golden.c

# 2. 使用 GCC C99 严格模式编译
gcc -std=c99 -O2 -Wall -Wextra -Werror -pedantic golden.c -c

# 3. 运行 6 层 65 项自动化测试套件（含黄金平流内核与本页最小示例的 GCC 实测）
python3 test_matrix.py
```

## 最小可运行示例

以下示例（已纳入 `test_matrix.py` 第 65 项端到端测试）按原 C 模板直接调用 `<stdio.h>` 的 `printf`，展示结构体声明、指向只读结构体的指针形参（`p* c@ Vec2`）、单字母结构体成员访问（`v.x`）与 `(v.)` 空参列表的自动区分，以及**逻辑与（`&.` → `&&`）**和**按位与（`&^` → `&`）**的明确区分：

**Sigil-C 源码（`minimal.sigil`）**：

```c
#include <stdio.h>

s{ Vec2 {
    i4 x;
    i4 y;
};

i4 dot_product(p* c@ Vec2 a, p* c@ Vec2 b) {
    r; (a->x * b->x) + (a->y * b->y);
}

i4 main(v.) {
    Vec2 u;
    Vec2 v;
    u.x m, 3;
    u.y m, 4;
    v.x m, 0x10;
    v.y m, 2;

    i4 res m, dot_product(a& u, a& v);
    /* &. 为逻辑与 (&&)，&^ 为按位与 (&)，=? 为相等比较 (==) */
    i? (res > 0 &. (res &^ 1) =? 0) {
        printf("dot = %d\n", (int)res);
    }
    r; 0;
}
```

**转译生成的 ISO C99 代码（`minimal.c`）**：

```c
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>

typedef struct Vec2 Vec2;
struct Vec2 {
    int32_t x;
    int32_t y;
};

int32_t dot_product(const Vec2 *a, const Vec2 *b) {
    return ((a->x * b->x) + (a->y * b->y));
}

int32_t main(void) {
    Vec2 u;
    Vec2 v;
    u.x = 3;
    u.y = 4;
    v.x = 0x10;
    v.y = 2;
    int32_t res = dot_product((&u), (&v));
    if (((res > 0) && ((res & 1) == 0))) {
        printf("dot = %d\n", (int)res);
    }
    return 0;
}
```

## 核心文件说明

* **`README.md`**：项目介绍、安装使用与原生 C 模板最小可运行示例。
* **`SYNTAX.md`**：印记符号速查表、前缀类型绑定规则、运算符静态语义与语言子集边界。
* **`CHANGELOG.md`**：版本演进记录、31→65 项测试覆盖增量明细与平流内核验证参数说明。
* **`sigilc.py` / `test_matrix.py`**：转译器源码与 65 项自动化验证脚本。
