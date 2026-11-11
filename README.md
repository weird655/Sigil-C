# Sigil-C (印记-C) v2.0.0

Sigil-C 是一种面向系统编程、游戏底层内核（ECS、网格平流、细胞自动机）与高密度代码生成的 ISO C99 前缀印记转译语言。它采用“单字母词根 + 语法标点后缀”的双字符印记（2-Char Sigil）与从左向右的前缀类型记法，通过单文件递归下降转译器（`sigilc.py`）将 `.sigil` 源码转换为带 `#line` 映射的 ISO C99 代码，交由 GCC 或 Clang 进行后端编译与优化。

> **v2.0.0 语法升级（破坏兼容）**：只读限定符从 `c$` 改为 `c@`，旧写法 `c$` 不再接受；迁移时将源码中的 `c$` 替换为 `c@`。
>
> **v1.0.0 赋值印记迁移**：复合赋值统一为 `m+`、`m-`、`m*`、`m/`。旧写法 `a+`、`s-`、`d/` 已移除；从 v0.5.2 迁移时分别替换为 `m+`、`m-`、`m/`，`m*` 保持不变。

## 核心设计特点

* **双字符正交印记与前瞻消歧**：控制流以 `? / : / ~ / ! / ^ / ;` 结尾（如 `i?`、`e:`、`w~`、`f~`、`s?`、`k:`、`d:`、`r;`）；对 `v.` / `b.` 类型印记引入第 3 字符前瞻，自动区分 `(v.)` 空参类型与单字母结构体变量的成员访问 `v.x` / `b.x`。
* **统一赋值印记**：`m,` 表示普通赋值，`m+`、`m-`、`m*`、`m/` 表示复合赋值。`m` 标出状态修改，后缀标出运算；例如 `total m+ cell` 对应 C 的 `total += cell`。
* **前缀线性类型声明**：将指针（`p*`）、只读限定（`c@`）、易变对象限定（`v@`）、定长数组（`Type[N]` / `(p* Type)[N]`）与函数指针（`f^(...) -> Ret`）统一为从左向右的前缀组合结构，由 AST `format_c_declarator()` 展开为 C99 声明符。
* **纯表达式与赋值语句分离**：语法层将赋值语句（`parse_assign_or_expr_no_semi`）与纯表达式（`parse_pure_expr`）拆分为独立入口，禁止在 `i?`、`w~`、`f~` 条件判断或算术子表达式中混入 `m,`、`m-` 等赋值副作用。
* **受限子集静态检查**：内置针对当前语言子集的类型推导（涵盖一元/二元算子、指针加减与指针差 `ptrdiff_t`、三元 `const` 合并与常规算术提升）、深层左值 `const` 传播（含 `const` 结构体数组成员的只读元素传播）、完整对象类型（Complete Object Type）校验、C99 标准头文件内建函数签名识别、非 `void` 函数返回路径检查，以及带八进制/十六进制/除零/移位越界/64 位溢出检查的向零截断整数常量折叠。

### 完整平流更新示例

下面给出一个完整的 Sigil-C 函数：从 `rd` 缓冲区读取每个单元，计算后写入 `wr`，同时累计输入值。

```sigil
s{ SG {
    p* c@ u4 rd;
    p* u4 wr;
    u2 w;
    u2 h;
};

i4 advect(p* SG g) {
    p* c@ u4 src m, g->rd;
    p* u4 dst m, g->wr;
    u4 W m, (u4)g->w;
    u4 H m, (u4)g->h;

    i? (src =? dst) {
        r; -1;
    }

    u4 total m, 0;
    f~(u4 y m, 0; y < H; y m+ 1) {
        f~(u4 x m, 0; x < W; x m+ 1) {
            u4 idx m, y * W + x;
            u4 cell m, src[idx];
            dst[idx] m, (cell >> 2) + (cell >> 4);
            total m+ cell;
        }
    }
    r; (i4)total;
}
```

`SG` 保存源/目标缓冲区和网格尺寸。`src` 是指向只读 `u4` 的指针，`dst` 是可写指针；`m,` 表示初始化，`m+` 表示复合加法赋值，所以 `total m+ cell` 等价于 C 的 `total += cell`。`idx` 使用 `u4` 计算二维数组的线性下标，内层每轮读取一个 `cell`，将移位计算结果写入目标，并把原值累加到 `total`。

调用方需保证两个缓冲区各自至少有 `w * h` 个 `u4` 元素且彼此不重叠；函数会拒绝首地址相同的缓冲区。成功时返回累计值，错误时返回 `-1`，因此还需保证总和不超过 `i4` 的最大值，避免有符号转换超出范围。

### 硬件寄存器与 `volatile`

`p* v@ u4 timer_reg` 表示指向 `volatile u4` 的指针，生成 C99 声明为 `volatile uint32_t *timer_reg`。通过 `*timer_reg` 读写时，后端会保留 `volatile` 对象访问语义。`v@` 限定的是指向的寄存器；若要限定指针变量自身，写作 `v@ p* u4 timer_reg`。将整数硬件地址转换为指针由目标平台定义，`volatile` 也不提供原子性或内存屏障。

```sigil
u4 read_timer(v.) {
    /* 地址和转换方式须按目标平台/ABI 确认 */
    p* v@ u4 timer_reg m, (p* v@ u4)0x40000000;
    u4 timer_value m, *timer_reg;
    r; timer_value;
}
```

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
