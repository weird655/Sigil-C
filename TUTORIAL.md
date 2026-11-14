# Sigil-C 教程

从零到"能交付的模块"。每章有一个能编译、能运行、输出确定的小程序；带 `main` 的代码块可以直接编译；其余是片段，默认已包含对应头文件。

## 怎么跑

```bash
# 单文件
python3 sigilc.py examples/tutorial/01_hello.sigil -o hello.c
gcc -std=c99 -Wall -Wextra -Werror -pedantic hello.c -o hello
./hello

# 或者让工具链代劳
python3 sigilc.py --build examples/tutorial -o app --run
```

约定：

- 示例编号 `01`–`21`，都在 `examples/tutorial/`
- 生成的 C 默认带 `#line`（报错指回 `.sigil`）；给 C 用户看时加 `--no-line`
- 所有示例都跑在 `-std=c99 -Wall -Wextra -Werror -pedantic` 下

---

# Part 0 · 入门

## 0.1 安装与工具链

需要 Python 3.10+ 与 gcc（clang 也可）。仓库里没有依赖要装：

```bash
python3 sigilc.py --version          # Sigil-C 1.1
python3 sigilc.py --check src        # 只检查，不写文件
python3 sigilc.py --build src -o app --run
```

`--init demo` 会生成一个最小工程（`src/main.sigil` + README + `.gitignore`）。

## 0.2 Hello, World

```sigil
#include <stdio.h>

i4 main(v.) {
    printf("Hello, World\n");
    r; 0;
}
```

`i4` 是 `int32_t`，`v.` 是 `void`，`r;` 是 `return`。生成的 C：

```c
int32_t main(void) {
    printf("Hello, World\n");
    return 0;
}
```

## 0.3 读懂错误信息

```text
error: a.sigil:3:5: Returning the address of local object 'x' would dangle after return
  --> a.sigil:3:5
     3 |     r; p@ x;
       |     ^
```

行:列 + 插入符 + 人话。`--check --json` 给工具链用的版本。

---

# Part 1 · 基础

## 1.1 变量与类型

```sigil
o! i4 count m, 3;          /* o! 可以省略：i4 count m, 3; */
o! u8 mask m, 0xFF00;      /* 定宽类型：u8 = uint64_t */
o! f8 ratio m, 1.5;
o! c1 ch m, 'A';
o! b. flag m, true;
```

| Sigil-C | C99 |
|---|---|
| `i1/i2/i4/i8` | `int8_t … int64_t` |
| `u1/u2/u4/u8` | `uint8_t … uint64_t` |
| `f4/f8` | `float/double` |
| `c1` | `char` |
| `b.` | `bool`（`stdbool.h`） |
| `v.` | `void` |

**要点**：类型写在名字前面，`o!` 只是"这里开始一个对象声明"的牌子。内置类型可以省略它，用户定义类型必须写。

## 1.2 常量与枚举

```sigil
#define LIMIT 50

e{ Mode { MODE_OFF m, 0, MODE_ON m, 1, MODE_TEST m, 2 };

i4 main(v.) {
    o! Mode m m, MODE_ON;
    r; (i4)m - 1;
}
```

- 字面量：`42`、`0xFF`、`1.5f`、`'A'`、`"str"`、`true` / `false` / `NULL`
- `#define` 只做透传 + 简单常量登记，**函数式宏不支持**
- 枚举用 `e{ Name { A m, 0, B m, 1 };`，值可省略（自动 +1）

## 1.3 运算符

| 类别 | Sigil-C 写法 |
|---|---|
| 算术 | `+ - * / mod` |
| 比较 | `==`（等于） `!=`（不等于） `< <= > >=` |
| 逻辑 | `&&`（与） `\|\|`（或） `!`（非） |
| 位运算 | `&` `\|` `^` `~` |
| 移位 | `<<` `>>` |
| 赋值 | `m,` `m+` `m-` `m*` `m/` |
| 成员 | `.` `->` |

```sigil
i? (a == b && c != 0) { x m, a | b; }
```

**为什么**：`&` 和 `|` 在 C 里同时是位运算和逻辑运算，单字符没法区分；Sigil-C 用第二个字符表态——`&` 位与、`&&` 逻辑与。

## 1.4 判断

```sigil
i? (score >= 60) {
    printf("pass\n");
} e: {
    i? (score >= 40) { printf("retry\n"); }
    e: { printf("fail\n"); }
}
```

没有 `else if` 关键字；`e:` 里再套一个 `i?` 就是 else-if。

## 1.5 循环

```sigil
w~ (i < n) { i m+ 1; }                    /* while */
f~ (o! i4 i m, 0; i < n; i m+ 1) { }      /* for */
d~ { i m+ 1; } w~ (i < n);                /* do-while */

w~ (1) {
    i? (stop) { b!; }                      /* break */
    i? (skip) { c^; }                      /* continue */
}
```

`b!` = break，`c^` = continue。

## 1.6 函数

```sigil
i4 add(i4 a, i4 b) { r; a + b; }

v. log_i4(i4 v) {
    printf("%d\n", v);
    r; ;                    /* void 提前返回 */
}

i4 main(v.) { r; add(1, 2); }
```

- 返回类型在前，参数是 `类型 名字`
- `v.` 表示 void；空参数写 `v.`
- 递归直接写；**互递归要先声明** `i4 odd(i4 n);`

## 1.7 作用域

```sigil
i4 main(v.) {
    o! i4 x m, 1;
    {
        o! i4 x m, 2;       /* 内层遮蔽 */
        printf("%d\n", x);  /* 2 */
    }
    r; x;                   /* 1 */
}
```

块作用域与 C 相同。区别在**指针来源**：局部对象的地址带"深度"，出了作用域再用会被拒绝（见 3.5）。

## 1.8 `s@` 与链接

```sigil
s@ v. helper(p* i4 p) { }      /* static：只在本翻译单元可见 */
```

`--emit-header` 生成 `.h` 时，`s@` 的符号不会出现——库的私有实现靠它。

---

# Part 2 · 数据

## 2.1 数组

```sigil
o! i4[5] a m, { 1, 2, 3, 4, 5 };
o! i4[5] b;
a[0] m, 9;
printf("%d\n", a[4]);
```

- 数组是**值**，不是指针；传参时按 C 规则退化为指针
- 常量下标在转译期查越界；`--bounds-check` 加运行期检查
- `z? a` 得元素个数 × 元素大小；`z? a[0]` 得单元素大小

## 2.2 字符串

```sigil
#include <string.h>

o! p* c@ c1 s m, "hello";
o! c1[16] buf;
strcpy(p@ buf[0], s);
printf("%d\n", (i4)strlen(s));
```

字符串就是 `p* c@ c1`（指向只读 char 的指针）。没有 `String` 类型，没有 GC，操作交给 libc。

## 2.3 结构体

`s{ Vec2 { i4 x; i4 y; };` 定义 `struct Vec2`；初始化用 `{ 3, 4 }`。

```sigil
s{ Vec2 { i4 x; i4 y; };

i4 dot(Vec2 a, Vec2 b) { r; a.x * b.x + a.y * b.y; }
v. scale(p* Vec2 v, i4 k) { v->x m* k; v->y m* k; }
```

传值 = 拷贝；要改原对象就传 `p* Vec2`。完整例子：`examples/tutorial/10_structs.sigil`。

## 2.4 共用体

```sigil
u{ Payload { i4 i; u4 u; f8 f; };
s{ Value { Kind kind; Payload data; };
```

`u{` 就是 C 的 `union`。C 没有和类型，标准做法是 `tag + union` 手写——Sigil-C 也一样。

## 2.5 位域

```sigil
s{ Flags {
    u4 a w! 3;
    u4 b w! 2;
    u4 c w! 5;
};

t! (z? Flags == 4, "Flags must fit in one u4");
```

- `w!N` 是指定位宽
- `a@(packed)` 去填充、`v@` 防优化——硬件寄存器场景
- 布局用 `t!` / `offsetof` 断言，不满足就编译失败

## 2.6 没有 typedef 怎么办

C 里 `typedef struct {...} Foo;` 是为了少写 `struct`。Sigil-C 不需要：`s{ Foo { ... };` 之后直接用 `Foo`。

外部头文件里的类型用 `x!` 登记：

```sigil
x! struct sockaddr_in { u2 sin_family; u2 sin_port; u4 sin_addr; };
```

不生成定义，只登记字段供检查；C 侧看到的是 `struct sockaddr_in`。

---

# Part 3 · 指针

## 3.1 指针基础

```sigil
o! i4 x m, 7;
o! p* i4 p m, p@ x;      /* &x */
printf("%d\n", p* p);    /* *p */
p* p m, 9;               /* *p = 9 */
```

- `p* T` 是"指向 T 的指针"
- `p@ x` 取地址，`p* p` 解引用
- `p*` 紧邻才是指针；`p * q` 是乘法（见 SYNTAX §0.7）

多指针可以缩写：`p2*` = `p* p*`，`p2@` = `p@ p@`，N ≥ 1；连续指针总深度上限 64，嵌套也受此限制。`p2 * q` 仍是乘法，空格不能省。

## 3.2 指针算术与数组

```sigil
o! i4[5] a m, { 1, 2, 3, 4, 5 };
o! p* i4 p m, p@ a[0];
o! p* i4 last m, p + 4;
printf("%d\n", p* last);
p m+ 1;                  /* 指针自增，是语句不是表达式 */
```

`p + n` 在表达式里可以用；`p m+ n` 是赋值语句。完整例子：`08_pointers.sigil`。

## 3.3 函数指针

```sigil
o! f^(i4, i4) -> i4 op m, add;
printf("%d\n", op(2, 3));
```

类型写法 `f^(参数类型...) -> 返回类型`。`v.` 返回写 `-> v.`。

## 3.4 回调与分派表

```sigil
o! (f^(i4, i4) -> i4)[3] TABLE m, { add, sub, mul };
TABLE[i](a, b);
```

这就是 C 的"函数指针数组"；虚拟机、状态机、命令表都用它。例子：`13_callbacks.sigil`、`examples/vm.sigil`。

## 3.5 指针来源与悬空

这是 Sigil-C 和 C 最大的区别。转译期会拒绝：

```sigil
p* i4 bad(v.) {
    o! i4 x m, 1;
    r; p@ x;          /* error: Returning the address of local object */
}
```

能挡的几类：

| 场景 | 结果 |
|---|---|
| 返回局部地址 | 转译期拒绝 |
| 局部地址存进全局/出参 | 转译期拒绝 |
| 指针活过它所指向的对象 | 转译期拒绝 |
| 跨函数逃逸（callee 存参数） | 转译期拒绝 |
| 常量下标越界 | 转译期拒绝 |
| `r@` 参数别名 | 转译期拒绝 |

挡不住的：堆、空指针、未初始化、窄化、有符号溢出、跨文件。见 README「它不挡什么」。

参数进来时来源未知，默认**不查也不报**；加 `--strict` 会把「无法证明来源的参数下标/解引用」直接拒掉：

```text
error: Cannot prove the bounds of parameter 'p' on subscript (cross-function provenance is not tracked)
```

---

## 3.6 三级指针：一个内存池

物理布局（8 个 u4，两个跨度 4 的块）：

```text
        ┌─────┬─────┬─────┬─────┬─────┬─────┬─────┬─────┐
 index  │  0  │  1  │  2  │  3  │  4  │  5  │  6  │  7  │
 value  │ 101 │ 202 │  ·  │  ·  │ 404 │  ·  │  ·  │  ·  │
        └─────┴─────┴─────┴─────┴─────┴─────┴─────┴─────┘
```

指针链：

```text
slot_alpha  ──►  raw_storage[0]      Block 0 的句柄
slot_beta   ──►  raw_storage[4]      Block 1 的句柄
free_slot   ──►  slot_alpha 或 slot_beta
                 (u4 **，指向某个槽位)
cursor_hub  ──►  &free_slot
                 (u4 ***，指向槽位指针本身)
```

完整源码（[`examples/pool.sigil`](examples/pool.sigil)，关键步骤有注释）：

```sigil
#include <stdio.h>

/* 内存池：多重指针嵌套 + 读写权限分流
   布局图与走读见 TUTORIAL §3.6「三级指针：一个内存池」 */

s{ Pool {
    p* c@ u4 arena_guard;     // 只读视图：审计探针
    p* u4 arena_raw;          // 可写物理池
    p* p* u4 free_slot;       // u4 **：当前空闲槽位
    p* p* p* u4 cursor_hub;   // u4 ***：指向 free_slot 本身
    u4 stride;                // 每块跨度
    u4 allocated;             // 已分配块数
};

p* u4 pool_acquire_block(p* Pool pool_rw, u4 init_tag) {
    o! p* p* u4 active_slot m, p* pool_rw->cursor_hub;   // u4 *** → u4 **
    o! p* u4 block_ptr m, p* active_slot;                // u4 **  → u4 *

    p* block_ptr m, init_tag;                            // 块首字写标记
    pool_rw->allocated m, pool_rw->allocated + 1;
    r; block_ptr;
}

v. pool_relocate_slot(p* p* u4 target_slot, p* u4 new_block, u4 payload) {
    p* target_slot m, new_block;      // 换绑槽位
    p* p* target_slot m, payload;     // 写新块首字
}

u4 memory_pool_demo(v.) {
    o! u4[8] raw_storage;
    raw_storage[0] m, 0;
    raw_storage[4] m, 0;

    o! p* u4 slot_alpha m, p@ raw_storage[0];   // Block 0
    o! p* u4 slot_beta  m, p@ raw_storage[4];   // Block 1

    o! Pool main_pool;
    main_pool.arena_guard m, raw_storage;
    main_pool.arena_raw   m, raw_storage;
    main_pool.free_slot   m, p@ slot_alpha;
    main_pool.cursor_hub  m, p@ main_pool.free_slot;
    main_pool.stride      m, 4;
    main_pool.allocated   m, 0;

    o! p* c@ Pool ro_pool m, p@ main_pool;   // 只读视图
    o! p* Pool rw_pool    m, p@ main_pool;   // 可写视图

    o! p* u4 blk_first m, pool_acquire_block(rw_pool, 101);
    blk_first[1] m, 202;

    rw_pool->free_slot m, p@ slot_beta;      // 推进游标

    o! p* u4 blk_second m, pool_acquire_block(rw_pool, 303);

    o! p* p* p* u4 hub_probe m, ro_pool->cursor_hub;
    o! u4 deep_read_val m, p* p* p* hub_probe;   // 穿透三层

    o! c@ p* p* u4 pinned_slot m, p@ slot_alpha; // 槽位地址锁死
    pool_relocate_slot(pinned_slot, blk_second, 404);

    o! p* c@ u4 guard_view m, ro_pool->arena_guard;
    o! u4 block0_head m, guard_view[0];
    o! u4 block0_next m, guard_view[1];
    o! u4 block1_head m, p* slot_alpha;
    o! u4 total_used  m, ro_pool->allocated;

    printf("block0: head=%u next=%u\n", block0_head, block0_next);
    printf("block1: head=%u (via slot_alpha)\n", block1_head);
    printf("deep_read=%u allocated=%u\n", deep_read_val, total_used);
    r; block0_head + block0_next + deep_read_val + block1_head + total_used;   // 1012
}

i4 main(v.) {
    u4 sum m, memory_pool_demo();
    printf("checksum=%u\n", sum);
    r; (i4)sum - 1012;
}
```

```text
block0: head=101 next=202
block1: head=404 (via slot_alpha)
deep_read=303 allocated=2
checksum=1012
```

三种权限写法在同一个结构体里分工：

| 写法 | 含义 | 用途 |
|---|---|---|
| `p* c@ u4` | 指向物只读 | 审计探针，禁止经它写入 |
| `p* u4` | 可写指针 | 物理池操作 |
| `c@ p* p* u4` | 指针自身只读 | 固定句柄，仍可改它指向的块 |

换 C 写同样的东西，声明要从星号中间往外读；这里从上到下就是「指针 → 只读 / 只读指针 → 类型」。

---

# Part 4 · 系统

## 4.1 输入输出

```sigil
#include <stdio.h>

i4 n m, 0;
scanf("%d", p@ n);
printf("%d %u %s %c %.2f\n", n, (u4)n, "ok", 'A', 1.5);
```

`#include` 会登记常用原型（`printf` / `scanf` / `sprintf` / `snprintf` / `sscanf` / `puts` / `putchar` / `getchar`）。

## 4.2 文件

```sigil
o! p* FILE f m, fopen("out.txt", "w");
i? (f == NULL) { r; 1; }
fprintf(f, "hello %d\n", 42);
fclose(f);
```

`FILE` 是不透明句柄，没有字段；`fopen/fclose/fread/fwrite/fgets/fputs/fprintf/fgetc/fputc/feof/fflush/remove/rename` 和 `stdin/stdout/stderr` 都已登记。例子：`14_files.sigil`。

## 4.3 预处理器边界

能用的：`#include`、`#define NAME 常量`（透传 + 常量登记）。

不能用的：函数式宏、条件编译、`#pragma` 里的代码生成。Sigil-C 不替代预处理器，只把它当 C 的一部分透传。

## 4.4 头文件与 `x!`

```bash
sigilc --build src -o app --emit-header   # 生成 .sigil-build/*.h
```

C 侧 `#include "foo.h"` 即可链接。外部头里的结构体用 `x!` 登记（2.6），字段不符只有 `t!` / `offsetof` 能抓。

## 4.5 强制类型转换

```sigil
o! f8 ratio m, 1.5;
o! i4 n m, (i4)ratio;     /* 截断 */
o! p* v. raw m, (p* v.)p@ n;
```

窄化是静默的（和 C 一样），README 明确列在"不挡"里。

## 4.6 错误处理与 `d!`

没有异常。错误处理是返回值：

```sigil
i4 rc m, do_work();
i? (rc != 0) { printf("failed: %d\n", rc); r; rc; }
```

不可恢复时 `d!;` 立即终止（GCC/Clang `__builtin_trap()`，其他后端 `abort()`），在 `s?` 里算终止语句，不会补 fallthrough。

---

## 4.7 C 标准库：有什么用什么

没有自己的标准库，`#include` 后直接用 libc：

| 头 | 已登记的原型 |
|---|---|
| `<stdio.h>` | printf / scanf / sprintf / snprintf / sscanf / puts / putchar / getchar；文件 API；stdin / stdout / stderr |
| `<stdlib.h>` | malloc / calloc / free / exit / abort / atoi / rand / srand / getenv |
| `<string.h>` | strlen / strcpy / strncpy / strcat / strcmp / strncmp / strchr / strrchr / strstr / memcpy / memmove / memset / memcmp |
| `<ctype.h>` | isalnum / isalpha / isdigit / islower / isspace / isupper / isxdigit / tolower / toupper |
| `<math.h>` | sqrt / fabs / sin / cos / tan / exp / log / floor / ceil / pow / fmod（Linux 链接加 `-lm`） |
| `<assert.h>` | assert |

不在表里的函数：手写原型 `i4 foo(p* c@ c1);`，或者用 `x!` 登记外部类型。`FILE` 已按不透明句柄登记（见 4.2）。

---

## 4.8 没有泛型怎么办：void* + 元素大小

C99 没有泛型，Sigil-C 也没有。办法和 C 一样：

| 需求 | 写法 |
|---|---|
| 任意类型的数组 | `p* v.` + 元素大小 `u4` |
| 排序 | `qsort(base, n, size, cmp)`，比较器 `f^(p* c@ v., p* c@ v.) -> i4` |
| 编译期按类型分派 | `g?`（转译期解析，不依赖 C11 的 `_Generic`） |

```sigil
i4 cmp(p* c@ v. a, p* c@ v. b) {
    o! p* c@ i4 x m, (p* c@ i4)a;
    o! p* c@ i4 y m, (p* c@ i4)b;
    r; (i4)(p* x - p* y);
}

qsort(p@ a[0], 5, z? i4, cmp);
```

完整例子：`21_qsort.sigil`。代价和 C 一样：运行时类型信息丢了，比较器里的强制转换要自己保证。

---

## 4.9 控制流梯度：一个例子把剩下的印记跑完

第 22 例 `22_control_flow.sigil` 专门覆盖前面没出现在教程里的印记：

| 印记 | 例子里的行为 |
|---|---|
| `f~` | 三段分号 for：`f~ (init; cond; step)` |
| `d~` | do-while：条件在循环体**之后**求值 |
| `s?` / `k:` / `d:` | switch，`k: 2:` 不写 `b!`，穿透到 `k: 3:` |
| `b!` / `c^` | `b!` 只跳出最近一层；`c^` 跳过本轮 |
| `g!` / `l!` | 回跳标签，带一个计数器避免死循环 |
| `g?` | 转译期按静态类型选分支 |
| `a?` | `alignof(i8)` |
| `i@` / `s@` | `s@ i@` 的 static inline |
| `x!` | 用 libc 的 `fpos_t` 注册外部类型 |
| `m/` | 除法赋值 |
| `\|` `^` `<<` `>>` | 位或 / 位异或 / 左移 / 右移 |
| `\|\|` `!` `!=` | 逻辑或 / 逻辑非 / 不等于 |
| `d!` | 不可达分支里的陷阱 |

输出：

```text
bits=4
acc=8
once=1
switch=6
nested=22
label=2 generic=1 align=8 inline=3 handle=1
```

`b!` 在内层循环里只跳出内层，外层的 `+10` 仍会执行——这是最容易读错的一处。

---

# Part 5 · 进阶

## 5.1 递归

见 `16_recursion.sigil`：`fib` 与汉诺塔。互递归要先声明：

```sigil
i4 is_odd(i4 n);
i4 is_even(i4 n) { r; (n == 0) ? 1 : is_odd(n - 1); }
```

## 5.2 可变参数

```sigil
i4 sum_all(u4 count, ...) {
    o! va_list ap;
    va_start(ap, count);
    o! i4 acc m, 0;
    o! u4 i m, 0;
    w~ (i < count) { acc m+ va_arg(ap, i4); i m+ 1; }
    va_end(ap);
    r; acc;
}
```

`va_start` / `va_arg` / `va_end` / `va_copy` 都是内建。例子：`15_varargs.sigil`。

## 5.3 栈与堆：三种标准写法

没有堆模型，但栈和堆都能用 C 的方式写对。三条法则各有一个可运行示例。

### 5.3.1 栈 + SBO：调用方分配

`18_stack_sbo.sigil`：小数组留在栈上，超过阈值才 `malloc`；被调函数只写区间，不分配。

```sigil
v. kernel(r@ p* c@ f4 in, r@ p* f4 out, u4 n) {
    o! u4 i m, 0;
    w~ (i < n) { out[i] m, in[i] * 2.0f + 1.0f; i m+ 1; }
}

o! f4[256] stack_buf;
o! p* f4 target m, p@ stack_buf[0];
i? (n > STACK_THRESHOLD) { target m, (p* f4)malloc(n * (z? f4)); }
```

- `r@` = `restrict`：两个区间不重叠，编译器才敢向量化
- 数组在栈上，函数返回随 `rsp` 回退，零 `free`
- 只有落进堆的那条路需要 `free`

### 5.3.2 Arena：把堆退化成栈

`19_arena.sigil`：一次请求 / 一帧里的对象都从一个线性池里切，`reset` 一次归零。

```sigil
p* u1 arena_alloc(p* Arena a, u4 size, u4 align) {
    o! u4 aligned m, (a->off + align - 1) & ~(align - 1);
    o! u4 next m, aligned + size;
    i? (next > a->cap) { r; NULL; }
    a->off m, next;
    r; a->base + aligned;
}
```

- 分配 = 对齐 + 一次加法，O(1)
- 回收 = `off m, 0`，O(1)，不分片
- 适合"批量同生命周期"的对象：请求、帧、关卡

### 5.3.3 SoA：消灭指针图

`20_soa.sigil`：不建 `Node* next` 的堆图，用连续数组 + 下标。

```sigil
s{ Graph { p* u4 ids; p* f8 w; p* u4 next; u4 n; };

g.next[i] m, i + 1;      /* 32 位下标，不是 64 位指针 */
```

- 同字段连续排列，缓存行全是有效载荷
- 硬件预取器只认等差数列
- 代价：插入/删除要搬数组

### 边界

重复释放、泄漏、悬空**不查**——这是 C 的活，它不抢。上面三种写法是"写对"，不是"被检查"。

## 5.4 未定义行为

转译期能拦的：常量越界、明显的悬空/逃逸。拦不住的：堆、空指针、未初始化、窄化、有符号溢出、跨文件。完整清单在 README「它不挡什么」+「四个实测」。

## 5.5 命令行参数

**尚未验证**。理论上可以写：

```sigil
i4 main(i4 argc, p* p* c1 argv) { r; 0; }
```

但没有示例、没有测试，不建议依赖。

---

# Part 6 · 工程

## 6.1 项目结构

```text
demo/
  src/
    main.sigil
  .gitignore
```

`--init demo` 生成。`--build demo/src -o demo/app` 会转译到 `src/.sigil-build/` 再链接。

## 6.2 构建

```bash
sigilc --build src -o app --run
sigilc --build src -o app --emit-header
sigilc --build src -o app --cc clang --cflags "-O2"
```

## 6.3 测试

- `sigilc --check src`：只做检查
- `sigilc --check src --json`：工具链格式
- `--fmt src --fmt-check`：空格纪律
- 生成的 C 用 `gcc -Wall -Wextra -Werror -pedantic` 编一遍
- 仓库自己的测试：`python tools/check.py`

## 6.4 发布

```bash
sigilc --build src -o app --emit-header
# 交付 .sigil 源码 + 生成的 .c/.h；不想带转译器就只给 C
```

生成物是纯 C99，随时可以"退出"：不再需要 Sigil-C 也能编译、链接、维护。

---

# Part 7 · 练习

## 7.1 经典题

1. 用 `p* u4` 写一个数组求和函数，越界用 `--bounds-check` 验证
2. 把 `examples/tutorial/04_calc.sigil` 的表达式求值改成支持括号
3. 用 `u{ }` + `e{ }` 写一个 JSON 值的最小表示（int/bool/string）
4. 用位域写一个 IPv4 头，`t!` 断言总长 20 字节
5. 用函数指针表实现一个 8 指令的栈虚拟机（参考 `examples/vm.sigil`）
6. 用 `FILE*` 实现 `wc -l`：读文件、统计行数、错误处理

## 7.2 自测

1. `p* u4` 和 `p * q` 有什么区别？为什么？
2. `o!` 什么时候可以省略？
3. `m,` 和 `=` 的区别是什么？为什么写操作要带牌？
4. `p@ x` 在什么情况下会被拒绝？
5. `s@` 对 `--emit-header` 有什么影响？
6. `f^` 类型的 `v.` 返回值怎么写？
7. `#include <string.h>` 之后为什么能直接调 `strlen`？
8. `--no-line` 改变的是什么？不改变什么？
9. 哪些 C 陷阱它拦不住？举三个。
10. 为什么它没有继承、没有标准库、没有包管理？

---

# 附录

## A 记号地图

控制流：`i?` `e:` `w~` `f~` `d~` `s?` `k:` `d:` `r;` `b!` `c^`
类型：`s{` `u{` `e{` `w!` `p*` `c@` `v@` `r@` `p@` `f^` `b.` `v.` `z?` `a?`
声明：`o!` `s@` `a@` `i@` `x!`
赋值：`m,` `m+` `m-` `m*` `m/`
运算符：`==` `!=` `&&` `||` `!` `|` `&` `^` `~` `->` `<<` `>>` `<=` `>=`
语句：`t!` `g!` `l!` `d!`

## B 示例索引

| 章节 | 文件 |
|---|---|
| 0–1 | `01_hello.sigil` |
| 2 | `02_primes.sigil` |
| 3 | `03_hexdump.sigil` |
| 4 | `04_calc.sigil` |
| 5 | `05_ringbuf.sigil` |
| 6 | `06_uart.sigil` |
| 7 | `07_library.sigil` |
| 8 指针 | `08_pointers.sigil` |
| 9 字符串 | `09_strings.sigil` |
| 10 结构体 | `10_structs.sigil` |
| 11 共用体 | `11_unions.sigil` |
| 12 位域 | `12_bitfields.sigil` |
| 13 回调 | `13_callbacks.sigil` |
| 14 文件 | `14_files.sigil` |
| 15 可变参数 | `15_varargs.sigil` |
| 16 递归 | `16_recursion.sigil` |
| 17 排序 | `17_sort.sigil` |
| 18 栈+SBO | `18_stack_sbo.sigil` |
| 19 Arena | `19_arena.sigil` |
| 20 SoA | `20_soa.sigil` |
| 21 qsort | `21_qsort.sigil` |
| 22 控制流 | `22_control_flow.sigil` |

## C 对照速查

| C | Sigil-C |
|---|---|
| `int x = 1;` | `i4 x m, 1;` |
| `if (x) {}` | `i? (x) {}` |
| `while (x) {}` | `w~ (x) {}` |
| `for (i=0;i<n;i++)` | `f~ (i m, 0; i < n; i m+ 1)` |
| `return x;` | `r; x;` |
| `*p` | `p* p` |
| `&x` | `p@ x` |
| `x == y` | `x == y` |
| `x && y` | `x && y` |
| `x & y` | `x & y` |
| `sizeof(T)` | `z? T` |
| `struct X {}` | `s{ X { ... };` |
| `unsigned int` | `u4` |
| `const char *` | `p* c@ c1` |
