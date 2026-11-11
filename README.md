# Sigil-C (印记-C) v3.0.0

Sigil-C 是一种面向系统编程、游戏底层内核（ECS、网格平流、细胞自动机）与高密度代码生成的 ISO C99 前缀印记转译语言。它采用“单字母词根 + 语法标点后缀”的双字符印记（2-Char Sigil）与从左向右的前缀类型记法，通过单文件递归下降转译器（`sigilc.py`）将 `.sigil` 源码转换为带 `#line` 映射的 ISO C99 代码，交由 GCC 或 Clang 进行后端编译与优化。

> **v3.0.0 语法升级**：独立对象声明必须以 `o!` 开始，旧式裸声明不再接受：`SG ctx;` 改为 `o! SG ctx;`、`u4 n;` 改为 `o! u4 n;`。局部/全局对象及 `f~` 初始化声明均须添加；结构体字段与函数形参保留原写法。`o!` 只标记对象声明，不表示堆分配或构造。
>
> **v2.0.0 语法升级**：只读限定符从 `c$` 改为 `c@`，旧写法 `c$` 不再接受；迁移时将源码中的 `c$` 替换为 `c@`。
>
> **v1.0.0 赋值印记迁移**：复合赋值统一为 `m+`、`m-`、`m*`、`m/`。旧写法 `a+`、`s-`、`d/` 已移除；从 v0.5.2 迁移时分别替换为 `m+`、`m-`、`m/`，`m*` 保持不变。

## 核心设计特点

* **双字符正交印记与前瞻消歧**：控制流以 `? / : / ~ / ! / ^ / ;` 结尾（如 `i?`、`e:`、`w~`、`f~`、`s?`、`k:`、`d:`、`r;`）；对 `v.` / `b.` 类型印记引入第 3 字符前瞻，自动区分 `(v.)` 空参类型与单字母结构体变量的成员访问 `v.x` / `b.x`。
* **统一赋值印记**：`m,` 表示普通赋值，`m+`、`m-`、`m*`、`m/` 表示复合赋值。`m` 标出状态修改，后缀标出运算；例如 `total m+ cell` 对应 C 的 `total += cell`。
* **显式对象声明与前缀线性类型**：`o!` 标出局部/全局对象及 `f~` 初始化声明；指针（`p*`）、只读限定（`c@`）、易变对象限定（`v@`）、定长数组（`Type[N]` / `(p* Type)[N]`）与函数指针（`f^(...) -> Ret`）仍按从左向右的前缀组合结构展开为 C99 声明符。
* **纯表达式与赋值语句分离**：语法层将赋值语句（`parse_assign_or_expr_no_semi`）与纯表达式（`parse_pure_expr`）拆分为独立入口，禁止在 `i?`、`w~`、`f~` 条件判断或算术子表达式中混入 `m,`、`m-` 等赋值副作用。
* **受限子集静态检查**：内置针对当前语言子集的类型推导（涵盖一元/二元算子、指针加减与指针差 `ptrdiff_t`、三元 `const` 合并与常规算术提升）、深层左值 `const` 传播（含 `const` 结构体数组成员的只读元素传播）、完整对象类型（Complete Object Type）校验、C99 标准头文件内建函数签名识别、非 `void` 函数返回路径检查，以及带八进制/十六进制/除零/移位越界/64 位溢出检查的向零截断整数常量折叠。

## 指针指南：从声明读到访问

Sigil-C 把指针层级写在类型前缀里。下面用简短变量名，把“数组 → 指针 → 解引用/下标 → 写回”的关系逐步展开：

```sigil
/* 用户定义类型：rd 指向只读元素，wr 指向可写元素。 */
s{ SG {
    p* c@ u4 rd;
    p* u4 wr;
    u4 w;
    u4 h;
};

u4 pointer_guide_demo(v.) {
    /* 两个普通定长数组：每个数组包含三个 u4 元素。 */
    o! u4[3] source_values;
    o! u4[3] target_values;
    source_values[0] m, 17;
    source_values[1] m, 23;
    source_values[2] m, 41;

    /* 声明格式：o! + 类型 + 空格 + 对象名 + 分号；SG 是类型，ctx 是对象名。 */
    o! SG ctx;
    /* 保存缓冲区地址和网格尺寸；数组赋值时退化为首元素地址。 */
    ctx.rd m, source_values;
    ctx.wr m, target_values;
    ctx.w m, 3;
    ctx.h m, 1;

    /* ctx 是实际对象；a& ctx 取它的地址，初始化下面两个指针变量。 */
    /* ro_ctx 与 rw_ctx 指向同一个对象，但权限不同。 */
    o! p* c@ SG ro_ctx m, a& ctx;
    o! p* SG rw_ctx m, a& ctx;
    o! u4 read_w m, ro_ctx->w;
    /* 取消下一行注释会因只读左值写入而静态报错。 */
    /* ro_ctx->w m, 4; */
    rw_ctx->h m, 2;
    o! u4 written_h m, rw_ctx->h;

    /* src、dst 是普通变量名；它们的类型决定缓冲区的读写权限。 */
    o! p* c@ u4 src m, ro_ctx->rd;
    o! p* u4 dst m, rw_ctx->wr;

    /* p* 解引用；[1] 表示向后偏移一个 u4。 */
    o! u4 first m, p* src;
    o! u4 second m, src[1];
    dst[0] m, first;
    dst[1] m, second;

    /* c@ 修饰指针自身：地址固定，指向的 u4 仍可写。 */
    o! c@ p* u4 fixed_dst m, a& target_values[0];
    fixed_dst[2] m, source_values[2];

    /* p* p* u4 是 u4 **：先取回内层指针，再经双重解引用读值。 */
    o! p* p* u4 dst_slot m, a& dst;
    o! p* u4 dst2 m, p* dst_slot;
    o! u4 first_written m, p* p* dst_slot;
    o! u4 third_written m, dst2[2];

    r; first + second + first_written + third_written + read_w + written_h;
}

/* v@ 限定指向的硬件对象；读写都经过 volatile u4 左值。 */
u4 read_hardware_register(p* v@ u4 reg_addr) {
    r; p* reg_addr;
}
```

逐层对照 C99 声明：

| Sigil-C 类型 | C99 类型 | 含义 |
| :--- | :--- | :--- |
| `o! p* u4 p` | `uint32_t *p` | 指向可读写 `u4` 的可变指针 |
| `o! p* c@ u4 src` | `const uint32_t *src` | 指向只读 `u4` 的可变指针 |
| `o! c@ p* u4 fixed` | `uint32_t * const fixed` | 地址固定，目标 `u4` 可写 |
| `o! p* c@ SG ro_ctx` | `const SG *ro_ctx` | 指向用户定义结构体的只读指针 |
| `o! p* SG rw_ctx` | `SG *rw_ctx` | 指向用户定义结构体的可写指针 |
| `o! p* v@ u4 reg` | `volatile uint32_t *reg` | 指向易变 `u4`，适用于寄存器访问 |
| `o! p* p* u4 pp` | `uint32_t **pp` | 指向 `u4` 指针的指针 |

`SG` 定义了两个不同权限的缓冲区指针：`rd` 是只读元素指针，`wr` 是可写元素指针。数组赋给字段时退化为首元素地址；之后经 `ro_ctx->rd`、`rw_ctx->wr` 取出指针，分别初始化 `src` 和 `dst`，形成“结构体字段 → 局部指针 → 下标读写”的完整链路。`p* c@ SG` 只让结构体的直接成员经该指针不可写；它不会递归改变指针字段所指对象的权限，所以 `rd` 自身声明为 `p* c@ u4`，`wr` 声明为 `p* u4`。`p*` 每出现一次就多一层指针；`c@` / `v@` 修饰紧随其后的那一层；`a&` 取左值地址，表达式位置的 `p*` 解引用。数组和指针本身不携带长度，下标范围由调用方负责。

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
    o! p* c@ u4 src m, g->rd;
    o! p* u4 dst m, g->wr;
    o! u4 W m, (u4)g->w;
    o! u4 H m, (u4)g->h;

    i? (src =? dst) {
        r; -1;
    }

    o! u4 total m, 0;
    f~(o! u4 y m, 0; y < H; y m+ 1) {
        f~(o! u4 x m, 0; x < W; x m+ 1) {
            o! u4 idx m, y * W + x;
            o! u4 cell m, src[idx];
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

`o! p* v@ u4 timer_reg` 声明一个指向 `volatile u4` 的对象，生成 C99 声明为 `volatile uint32_t *timer_reg`。通过 `p* timer_reg` 读写时，后端会保留 `volatile` 对象访问语义。`v@` 限定的是指向的寄存器；若要限定指针变量自身，写作 `o! v@ p* u4 timer_reg`。将整数硬件地址转换为指针由目标平台定义，`volatile` 也不提供原子性或内存屏障。

```sigil
u4 read_timer(v.) {
    /* 地址和转换方式须按目标平台/ABI 确认 */
    o! p* v@ u4 timer_reg m, (p* v@ u4)0x40000000;
    o! u4 timer_value m, p* timer_reg;
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

# 3. 运行 7 层 71 项自动化测试套件（含黄金平流内核与本页最小示例的 GCC 实测）
python3 test_matrix.py
```

### 作为可链接模块使用（v3.1.0）

Sigil-C 生成的 `.c` 可以被普通 C 代码直接链接。加 `--emit-header` 会同时产出公共接口头文件：

```bash
# 生成 vec.c 与 vec.h（vec.h 只包含公开符号，s@ 修饰的内部符号被排除）
python3 sigilc.py vec.sigil -o vec.c --emit-header

# 普通 C 文件 include 它即可调用
gcc -std=c99 -Wall -Wextra -Werror -pedantic vec.c consumer.c -o demo
```

```c
#include "vec.h"           /* 类型定义 + 函数原型 + extern 全局，全自动生成 */

int main(void) {
    Vec2 a = { 3, 4 }, b = { 10, 2 };
    int d = dot(&a, &b);   /* Sigil-C 实现的函数 */
    return d == 38 ? 0 : 1;
}
```

其他命令行选项：

| 选项 | 作用 |
|---|---|
| `-o, --output PATH` | 输出 `.c` 路径 |
| `--emit-header` | 同时生成同名 `.h` |
| `--header PATH` | 指定头文件路径（隐含 `--emit-header`） |
| `--check` | 只做词法/语法/语义检查，不写任何文件 |
| `--version` / `-h` | 版本与帮助 |

## 最小可运行示例

以下示例（已纳入 `test_matrix.py` 端到端测试）按原 C 模板直接调用 `<stdio.h>` 的 `printf`，展示结构体声明、指向只读结构体的指针形参（`p* c@ Vec2`）、单字母结构体成员访问（`v.x`）与 `(v.)` 空参列表的自动区分，以及**逻辑与（`&.` → `&&`）**和**按位与（`&^` → `&`）**的明确区分：

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
    o! Vec2 u;
    o! Vec2 v;
    u.x m, 3;
    u.y m, 4;
    v.x m, 0x10;
    v.y m, 2;

    o! i4 res m, dot_product(a& u, a& v);
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
* **`CHANGELOG.md`**：版本演进记录、31→71 项测试覆盖增量明细与平流内核验证参数说明。
* **`sigilc.py` / `test_matrix.py`**：转译器源码与 71 项自动化验证脚本。
