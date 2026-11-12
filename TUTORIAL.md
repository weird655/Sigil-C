# Sigil-C 教程

把 C 写成**从左往右读**的样子。

三个方向、七个程序，全部在 [`examples/tutorial/`](examples/tutorial/)。教程里的代码就是仓库里的文件，测试层会编译并运行它们。

印记的规则只有一条：**一个字母 + 一个标点，两个字符必须紧邻**。本教程用到二十多个，学到哪算哪。

---

## 0 · 三步走

```bash
python3 sigilc.py examples/tutorial/01_hello.sigil -o hello.c
gcc -std=c99 -Wall -Wextra -Werror -pedantic hello.c -o hello
./hello
```

转译、编译、运行。转译器只做一件事：`.sigil` → 标准 C99。

生成的 C 里有 `#line`：

```c
#line 11 "01_hello.sigil"
    printf("Sigil-C tutorial\n");
```

gcc 报错会直接指回你的源文件。**生成物不是黑盒。**

---

## 1 · 软件：一个函数

**本章新增** `o!` 声明 · `m,` 赋值 · `r;` 返回 · `v.` 空类型 / 空参数 · 类型 `i4`

> **本质**：`o!` 标出声明，`m,` 标出写。读代码时不用找 `=` 猜哪个是赋值。

```sigil
#include <stdio.h>

i4 area(i4 w, i4 h) { r; w * h; }

i4 main(v.) {
    o! i4 w m, 4;                 /* 声明 + 初始化 */
    o! i4 h m, 6;
    printf("Sigil-C tutorial\n");
    printf("area(%d x %d) = %d\n", w, h, area(w, h));
    r; 0;
}
```

```text
Sigil-C tutorial
area(4 x 6) = 24
```

**要点**

- `v.` 是空类型，也是空参数列表——`main(v.)` 就是 `int main(void)`
- `r;` 自带分号；空返回要写 `r; ;`
- `o!` 在基类型直接开头时可省（`u4 w m, 4;`）；用户定义类型与指针仍必须写

📄 [`examples/tutorial/01_hello.sigil`](examples/tutorial/01_hello.sigil)

---

## 2 · 软件：控制流与数组

**本章新增** `w~` 循环 · `i?` 条件 · `e:` 否则 · `m+` 自增 · 类型 `b.` · 数组维度 `T[N]`

> **本质**：维度写在**类型**里——`b.[LIMIT]` 是 `bool[LIMIT]`，不是 `bool x[LIMIT]`。

```sigil
#define LIMIT 50

i4 main(v.) {
    o! b.[LIMIT] sieve;           /* bool sieve[50] */
    o! i4 i m, 2;
    w~ (i < LIMIT) { sieve[i] m, true; i m+ 1; }

    i m, 2;
    w~ (i * i < LIMIT) {
        i? (sieve[i]) {           /* 是素数才筛 */
            o! i4 j m, i * i;
            w~ (j < LIMIT) { sieve[j] m, false; j m+ i; }
        }
        i m+ 1;
    }

    o! i4 count m, 0;
    printf("primes below %d:\n", LIMIT);
    i m, 2;
    w~ (i < LIMIT) {
        i? (sieve[i]) { printf("%d ", i); count m+ 1; }
        i m+ 1;
    }
    printf("\ncount=%d\n", count);
    r; 0;
}
```

```text
primes below 50:
2 3 5 7 11 13 17 19 23 29 31 37 41 43 47
count=15
```

**要点**

- 常量下标越界，转译期就断：

  ```sigil
  o! u4[3] a m, { 1, 2, 3 };
  r; (i4)a[5];   /* Index 5 is out of bounds for an array of 3 element(s) */
  ```

- 运行期下标走 `SIGIL_IDX`，加 `--bounds-check` 才真正检查

📄 [`examples/tutorial/02_primes.sigil`](examples/tutorial/02_primes.sigil)

---

## 3 · 软件：指针与边界

**本章新增** `p*` 指针 · `c@` 只读 · `a&` 取地址 · `&.` 逻辑与 · 类型 `u1` `c1`

> **本质**：指针带**来源**——从哪个数组来、偏移多少、还剩几个元素。

```sigil
v. dump(p* c@ u1 buf, u4 n) {
    o! u4 off m, 0;
    w~ (off < n) {                       /* 每行 16 字节 */
        printf("%04x  ", off);

        o! u4 i m, 0;
        w~ (i < 16) {
            i? (off + i < n) { printf("%02x ", buf[off + i]); }
            e: { printf("   "); }        /* 不足 16 字节补空格 */
            i m+ 1;
        }

        printf(" |");
        i m, 0;
        w~ (i < 16 &. off + i < n) {     /* &. 逻辑与，短路 */
            o! u1 c m, buf[off + i];
            i? (c >= 0x20 &. c < 0x7f) { printf("%c", (c1)c); }
            e: { printf("."); }          /* 不可打印字节显示点 */
            i m+ 1;
        }
        printf("|\n");
        off m+ 16;
    }
}
```

```text
0000  53 69 67 69 6c 2d 43 20 00 01 02 7f 80 ff 41 42  |Sigil-C ......AB|
0010  20 7e 00 0a 33 44 55 66                          | ~..3DUf|
```

**要点**

- `p* c@ u1` = `const uint8_t *`，从左往右读：指针 → 只读 → 类型
- 越界不靠人记：

  ```sigil
  o! u4[3] a m, { 1, 2, 3 };
  o! p* u4 p m, a& a[1];   /* 只剩 2 个元素 */
  r; (i4)p[2];             /* Index 2 ... reaches element 3, outside 3 element(s) */
  ```

📄 [`examples/tutorial/03_hexdump.sigil`](examples/tutorial/03_hexdump.sigil)

---

## 4 · 软件：函数指针表

**本章新增** `e{` 枚举 · `f^` 函数指针

> **本质**：C 里声明从中间读，这里从左往右。

```sigil
o! (f^(i4, i4) -> i4)[4] OPS m, { do_add, do_sub, do_mul, do_div };
```

对应的 C 是 `int (*OPS[4])(int, int)`——名字埋在星号中间。这里依次是：**函数指针 → 参数 → 返回 → 数组维度 → 名字**。

```text
1+2=3
9-4=5
6*7=42
8/2=4
1/0=0
```

**要点**

- 表在编译期用函数名填好，没有运行时注册
- `1/0=0` 是 `do_div` 里的保护，不是除零

📄 [`examples/tutorial/04_calc.sigil`](examples/tutorial/04_calc.sigil)

---

## 5 · 嵌入：volatile 环形缓冲

**本章新增** `s{` 结构体 · `v@` volatile

> **本质**：`v@` 告诉编译器"这次访问不能省"——中断里写、主循环里读。

```sigil
s{ Ring {
    v@ u4 head;
    v@ u4 tail;
    v@ u4 dropped;
    v@ u1[CAP] data;
};

b. ring_push(p* Ring rb, u1 v) {
    o! u4 next m, (rb->head + 1) % CAP;
    i? (next =? rb->tail) {          /* 满：丢帧，不覆盖 */
        rb->dropped m+ 1;
        r; false;
    }
    rb->data[rb->head] m, v;
    rb->head m, next;
    r; true;
}
```

```text
popped: 1 2 3 4 5 6 7
dropped: 3
```

**要点**

- 容量 8 的环实际放 7 个：`head + 1 == tail` 即满
- 满了丢新帧而不是覆盖旧帧——嵌入里最经典的取舍
- **命名雷区**：变量别叫 `r`。`r;` 是返回印记，`o! Ring r;` 会被拆成 `o! Ring` + `r;` 然后报语法错

📄 [`examples/tutorial/05_ringbuf.sigil`](examples/tutorial/05_ringbuf.sigil)

---

## 6 · 硬件：寄存器映射

**本章新增** `u{` 联合体 · `w!` 位域 · `a@(packed)` 紧凑布局 · `t!` 编译期断言 · `z?` sizeof · 内建 `offsetof`

> **本质**：布局是协议。`t!` 让它编译期就被检查，而不是上板子才发现。

```sigil
a@(packed) s{ Uart {
    v@ u4 status;
    v@ u4 data;
    v@ u4 ctrl;
};

s{ CtrlBits {
    u4 enable w! 1;
    u4 mode   w! 2;
    u4 baud   w! 13;
};

u{ CtrlReg {                 /* raw 与 bits 共用 4 字节 */
    u4 raw;
    CtrlBits bits;
};

t! (offsetof(Uart, data) =? 4, "data register must sit at offset 4");
t! (offsetof(Uart, ctrl) =? 8, "ctrl register must sit at offset 8");
t! (z? Uart =? 12, "Uart block must be 12 bytes");
```

```text
ctrl=0x2587 enable=1 mode=3 baud=1200
status=0x2 data=0
```

**要点**

- `packed` 去掉隐藏填充；`v@` 保证访问落到内存
- 位域与原始寄存器共用一块内存：写位域 = 写寄存器
- 换平台布局变了 → **编译失败**，不是运行到现场才发现

📄 [`examples/tutorial/06_uart.sigil`](examples/tutorial/06_uart.sigil)

---

## 7 · 硬件：帧解析

**本章新增** `|^` 位或（`|.` 是逻辑或，别混）· 类型 `u2`

> **本质**：端序只出现在一个函数里。

完整代码 [`examples/wire.sigil`](examples/wire.sigil)：

```sigil
s{ FrameFlags {
    u2 kind   w! 4;
    u2 len    w! 10;
    u2 more   w! 1;
    u2 parity w! 1;
};

u{ FrameHeader {
    u2 raw;
    FrameFlags bits;
};

u2 be16(p* c@ u1 p) { r; (u2)(((u4)p[0] << 8) |^ (u4)p[1]); }
```

```text
frame 0 kind=1 len=3 more=0 parity=0 payload="ABC"
frame 1 kind=2 len=2 more=0 parity=1 payload="hi"
frames=2 bytes=9
```

**要点**

- 位域直接叠在原始字节上，不手工移位
- 换小端只改 `be16` 一处
- 每次读 payload 前先检查剩余长度

📄 [`examples/wire.sigil`](examples/wire.sigil)

---

## 8 · 发布成库

**本章新增** `s@` 文件内部链接

> **本质**：你用什么写是你的事，交付物是标准 C。

```sigil
s@ u4 clamp_u4(u4 v, u4 lo, u4 hi) { ... }   /* 内部链接，不进头文件 */

u4 scale(p* c@ u4 src, u4 n, u4 max) { ... }
```

```bash
python3 sigilc.py examples/tutorial/07_library.sigil -o lib.c --emit-header
gcc app.c lib.c -I. -o app        # C 用户：不需要装 Sigil-C
```

生成的 `lib.h` 里只有公开符号：

```c
uint32_t scale(const uint32_t *src, uint32_t n, uint32_t max);
```

**要点**

- `s@` 挡住内部符号；头文件只导出该导出的
- `main` 也会出现在头里，正式发布时把它拆到单独文件

📄 [`examples/tutorial/07_library.sigil`](examples/tutorial/07_library.sigil)

---

## 9 · 十个坑

| # | 坑 | 正确写法 | 何时被抓 |
|:--:|---|---|---|
| 1 | 变量叫 `r`，`o! T r;` 撞返回印记 | 改名 `rb`，或写 `r ;` | 转译期 |
| 2 | 位或写成 `\|.` | `\|.` 是逻辑或；位或用 `\|^` | 行为错 / 编译期 |
| 3 | 用户类型 / 指针对象忘 `o!` | 内建基类型可省，其余一律 `o!` | 转译期 |
| 4 | 形参没用，`-Werror` 报错 | `(v.)arg;` 消费掉 | 编译期 |
| 5 | `l! label:` 带冒号 | `l! again;` | 转译期 |
| 6 | 想用 `a!16` 对齐对象 | 对象用 `a@(aligned(16))` | 转译期 |
| 7 | 空返回写 `r;` | `r; ;` | 转译期 |
| 8 | 窄化赋值当安全 | 不拦，和 C 一样截断 | 不抓 |
| 9 | 以为指针参数有长度 | 参数来源未知，不查 | 不抓 |
| 10 | 手改生成的 `.c` | 只改 `.sigil` | 纪律 |

前七条有机器兜底，后三条靠人。完整清单见 [`MIGRATION.md`](MIGRATION.md)。

---

## 10 · 让 AI 帮你写

> **本质**：AI 不是"会写"，是"写错了会被抓住"。

**五条规则**

1. 只许用 [`SYNTAX.md`](SYNTAX.md) 里的印记，不确定就查
2. 写操作必须带 `m`
3. 每段代码必须过 `--check`
4. 报错先读 `-->` 那一行和插入符
5. 别猜语法，跑一遍比想十分钟快

**验证循环**

```bash
python3 sigilc.py x.sigil --check
python3 sigilc.py x.sigil -o x.c
gcc -std=c99 -Wall -Wextra -Werror -pedantic x.c -o x && ./x
```

**AI 常犯的三个错**

| 错 | 表现 | 修法 |
|---|---|---|
| 位运算用 `\|.` | 生成 `\|\|`，结果变布尔 | `\|^` |
| 忘 `o!` | "must begin with 'o!'" | 补 `o!` |
| `r@` 加在非指针上 | 类型错误 | `r@` 只修饰指针 |

---

## 11 · 练习

1. **CRC32**（50 行）：`|^` `&^` `<<`
2. **内存池**（100 行）：在 `u1[1024]` 上做空闲链表
3. **PNG 头解析**（100 行）：位域 + 大端
4. **小 VM**（150 行）：已有 [`examples/vm.sigil`](examples/vm.sigil)
5. **配置解析**（180 行）：字符串扫描 + 边界

---

## 12 · 记号地图（复习）

学到这你应该认识这些了——**打勾的是教程用过的**，其余是同一家族的邻居。

| 家族 | 印记 | 作用 |
|---|---|---|
| 声明 / 写 | ✓ `o!` ✓ `m,` ✓ `m+` ✓ `r;` ✓ `v.` ✓ `s@` `m-` `m*` `m/` | 对象、赋值、返回、链接 |
| 控制 | ✓ `i?` ✓ `e:` ✓ `w~` `f~` `s?` `k:` `d:` `b!` `c^` | 分支、循环、派发、跳出 |
| 指针 / 限定 | ✓ `p*` ✓ `c@` ✓ `a&` ✓ `v@` `r@` | 指针、只读、取址、只此一路 |
| 类型 | ✓ `s{` ✓ `u{` ✓ `e{` ✓ `w!` ✓ `a@(...)` `a!N` | 结构、联合、枚举、位域、属性 |
| 检查 | ✓ `t!` ✓ `z?` ✓ `offsetof` | 编译期断言、大小、偏移 |
| 运算 | ✓ `&.` ✓ `=?` ✓ `\|^` `\|.` `&^` `^^` `!?` `!.` | 逻辑 / 比较 / 位 |
| 类型名 | ✓ `i4` ✓ `u4` ✓ `u2` ✓ `u1` ✓ `c1` ✓ `b.` `f4` `f8` | 定宽整数、字符、布尔、浮点 |

完整 52 项见 [`SYNTAX.md`](SYNTAX.md)。

---

## 结语

三条线，同一套检查：

| 方向 | 你担心的 | 谁兜底 |
|---|---|---|
| 软件 | 越界、悬垂、指针走丢 | 转译期 |
| 嵌入 | `volatile` 语义、环形缓冲 | 语义同 C，写操作可见 |
| 硬件 | 布局、位域、端序 | `t!` + `offsetof` |

它不试图变成另一种语言，只是让 C 的这三点**看得见**。
