# Sigil-C 教程：三种码，一条路

这门语言不大，所以教程也短。八章，每章一个能跑的程序，按三个方向铺开：

- **软件**（第 1–4 章）：普通程序，变量、控制流、指针、函数指针
- **嵌入**（第 5 章）：`volatile`、环形缓冲、丢帧计数
- **硬件**（第 6–7 章）：寄存器映射、位域、帧解析

最后三章讲发布、踩坑和让 AI 帮你写。

所有代码都在 [`examples/tutorial/`](examples/tutorial/)，每章末尾有完整文件路径。**教程里的代码和仓库里的文件是同一份**，测试层会编译并运行它们。

---

## 第 0 章：装好，跑起来

需要 Python 3.8+ 和 gcc（clang 也行）。

```bash
python3 sigilc.py examples/tutorial/01_hello.sigil -o hello.c
gcc -std=c99 -Wall -Wextra -Werror -pedantic hello.c -o hello
./hello
```

就三步：**转译 → 编译 → 运行**。转译器只做一件事：把 `.sigil` 变成标准 C99。

打开生成的 `hello.c`，你会看到 `#line` 指令：

```c
#line 7 "01_hello.sigil"
    printf("Sigil-C tutorial\n");
```

它的意思是"这一行来自 01_hello.sigil 第 7 行"。所以 gcc 报错时会直接指回你的源文件——生成物不是黑盒。

---

## 第 1 章 软件：变量、函数、打印

```sigil
#include <stdio.h>

i4 area(i4 w, i4 h) { r; w * h; }

i4 main(v.) {
    o! i4 w m, 4;
    o! i4 h m, 6;
    printf("Sigil-C tutorial\n");
    printf("area(%d x %d) = %d\n", w, h, area(w, h));
    r; 0;
}
```

输出：

```
Sigil-C tutorial
area(4 x 6) = 24
```

**这里每个记号都在说一件事：**

| 写法 | 意思 | C 里对应 |
|---|---|---|
| `i4` | 32 位有符号整数 | `int32_t` |
| `o!` | 声明一个对象 | `int32_t w` |
| `m,` | 赋值（写） | `=` |
| `r;` | 返回 | `return` |
| `v.` | 空类型 / 无参数 | `void` |

`o!` 和 `m,` 看着多两个字符，但它们把"这里在声明"和"这里在写"标了出来。回头看代码时，你不用找 `=` 猜哪个是赋值。

📄 [`examples/tutorial/01_hello.sigil`](examples/tutorial/01_hello.sigil)

---

## 第 2 章 软件：控制流与数组

埃氏筛，50 以内：

```sigil
#define LIMIT 50

i4 main(v.) {
    o! b.[LIMIT] sieve;
    o! i4 i m, 2;
    w~ (i < LIMIT) { sieve[i] m, true; i m+ 1; }

    i m, 2;
    w~ (i * i < LIMIT) {
        i? (sieve[i]) {
            o! i4 j m, i * i;
            w~ (j < LIMIT) { sieve[j] m, false; j m+ i; }
        }
        i m+ 1;
    }
    ...
}
```

输出：

```
primes below 50:
2 3 5 7 11 13 17 19 23 29 31 37 41 43 47
count=15
```

三个控制流印记：

| 印记 | C | 读法 |
|---|---|---|
| `i? (c) { } e: { }` | `if / else` | `?` 问，`e:` 否则 |
| `w~ (c) { }` | `while` | `~` 循环 |
| `f~ (init; cond; step) { }` | `for` | 同理 |

数组维度写在**类型**里：`b.[LIMIT] sieve`，不是 `bool sieve[LIMIT]`。这条是整门语言最反 C 直觉的地方，但读起来是从左往右的。

**它替你挡的**：下面这行会被当场拒绝。

```sigil
o! u4[3] a m, { 1, 2, 3 };
r; (i4)a[5];          /* error: Index 5 is out of bounds for an array of 3 element(s) */
```

C 里这是未定义行为，编译器通常不管。

📄 [`examples/tutorial/02_primes.sigil`](examples/tutorial/02_primes.sigil)

---

## 第 3 章 软件：指针与边界

一个真能用的 hexdump：

```sigil
v. dump(p* c@ u1 buf, u4 n) {
    o! u4 off m, 0;
    w~ (off < n) {
        printf("%04x  ", off);
        o! u4 i m, 0;
        w~ (i < 16) {
            i? (off + i < n) { printf("%02x ", buf[off + i]); }
            e: { printf("   "); }
            i m+ 1;
        }
        printf(" |");
        ...
    }
}
```

输出：

```
0000  53 69 67 69 6c 2d 43 20 00 01 02 7f 80 ff 41 42  |Sigil-C ......AB|
0010  20 7e 00 0a 33 44 55 66                          | ~..3DUf|
```

**指针怎么读**：

| 写法 | C | 读法 |
|---|---|---|
| `p* u1` | `uint8_t *` | 指向 u1 的指针 |
| `p* c@ u1` | `const uint8_t *` | 指向只读 u1 的指针 |
| `a& x` | `&x` | 取地址 |

从左往右读：`p*` 是"指针"，`c@` 是"只读"，最后才是类型。C 的 `const uint8_t *` 要先把 `const` 绑到 `uint8_t` 上，再发现它修饰的是指向物——这里不用脑内括号。

**它替你挡的**：从 `a[1]` 取的指针只剩 2 个元素：

```sigil
o! u4[3] a m, { 1, 2, 3 };
o! p* u4 p m, a& a[1];
r; (i4)p[2];        /* error: Index 2 through a pointer into 'a' reaches element 3, outside 3 element(s) */
```

它记住了"这根指针从哪来、走了多远"。这层追踪是这门语言最实的东西。

📄 [`examples/tutorial/03_hexdump.sigil`](examples/tutorial/03_hexdump.sigil)

---

## 第 4 章 软件：函数指针表

```sigil
o! (f^(i4, i4) -> i4)[4] OPS m, { do_add, do_sub, do_mul, do_div };

i4 eval(i4 a, Op op, i4 b) { r; OPS[(i4)op](a, b); }
```

C 里这个声明是 `int (*OPS[4])(int, int)`——名字埋在中间。Sigil-C 从左到右：**函数指针（`f^`）→ 参数表 → 返回类型 → 数组维度 → 名字**。

输出：

```
1+2=3
9-4=5
6*7=42
8/2=4
1/0=0
```

表在编译期就用函数名填好了，没有运行时注册，也没有 `if/else` 链。

📄 [`examples/tutorial/04_calc.sigil`](examples/tutorial/04_calc.sigil)

---

## 第 5 章 嵌入：volatile 与环形缓冲

中断里写、主循环里读，用 `v@` 告诉编译器"别优化掉这次访问"：

```sigil
s{ Ring {
    v@ u4 head;
    v@ u4 tail;
    v@ u4 dropped;
    v@ u1[CAP] data;
};

b. ring_push(p* Ring rb, u1 v) {
    o! u4 next m, (rb->head + 1) % CAP;
    i? (next =? rb->tail) { rb->dropped m+ 1; r; false; }
    rb->data[rb->head] m, v;
    rb->head m, next;
    r; true;
}
```

输出：

```
popped: 1 2 3 4 5 6 7
dropped: 3
```

容量 8 的环形缓冲实际只能放 7 个——第 8 个进来时 `next` 会撞上 `tail`，这时候我们计数丢帧而不是覆盖数据。这是嵌入里最经典的取舍。

**命名雷区**：变量别叫 `r`。`r;` 是返回印记，`o! Ring r;` 会被词法器拆成 `o! Ring` + `r;` 然后报语法错。叫 `rb`、`rs` 都行。

📄 [`examples/tutorial/05_ringbuf.sigil`](examples/tutorial/05_ringbuf.sigil)

---

## 第 6 章 硬件：寄存器映射

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

u{ CtrlReg {
    u4 raw;
    CtrlBits bits;
};

t! (offsetof(Uart, data) =? 4, "data register must sit at offset 4");
t! (offsetof(Uart, ctrl) =? 8, "ctrl register must sit at offset 8");
t! (z? Uart =? 12, "Uart block must be 12 bytes");
```

输出：

```
ctrl=0x2587 enable=1 mode=3 baud=1200
status=0x2 data=0
```

三件事同时发生：

1. `a@(packed)` 保证没有隐藏填充（否则 `status` 后面可能补 0 字节）
2. 位域 `CtrlBits` 和 `raw` 共用 4 字节，写位域再读原始值就是硬件协议
3. `t!` 断言把布局钉死在编译期——换编译器/换平台如果布局变了，**编译就失败**，而不是运行到板子上才发现

这是 Sigil-C 相对 C 最直接的收益之一：C 里你只能写注释说"这个结构体必须是 12 字节"，这里能让编译器替你站岗。

📄 [`examples/tutorial/06_uart.sigil`](examples/tutorial/06_uart.sigil)

---

## 第 7 章 硬件：帧解析

完整代码在 [`examples/wire.sigil`](examples/wire.sigil)，这里只讲结构：

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
```

输出：

```
frame 0 kind=1 len=3 more=0 parity=0 payload="ABC"
frame 1 kind=2 len=2 more=0 parity=1 payload="hi"
frames=2 bytes=9
```

三个要点：

- **头部 2 字节**，位域直接叠在原始字节上，不需要手工移位
- **端序只出现在一处**：`be16()` 函数；换小端只改它
- **每次读 payload 前先检查剩余长度**，越界是被显式挡住的

📄 [`examples/wire.sigil`](examples/wire.sigil)

---

## 第 8 章 发布成库

写一个只导出 `scale` 的文件：

```sigil
s@ u4 clamp_u4(u4 v, u4 lo, u4 hi) { ... }   /* s@ = 文件内部链接 */

u4 scale(p* c@ u4 src, u4 n, u4 max) { ... }
```

```bash
python3 sigilc.py examples/tutorial/07_library.sigil -o lib.c --emit-header
# 产出 lib.c 和 lib.h
```

`lib.h` 里只有导出的符号：

```c
uint32_t scale(const uint32_t *src, uint32_t n, uint32_t max);
```

`clamp_u4` 被 `s@` 挡住，不会出现在头文件里。

C 用户怎么用：

```bash
gcc app.c lib.c -I. -o app
```

**他们不需要装 Sigil-C。** 这是它区别于玩具语言的地方：你用什么写是你的事，交付物是标准 C。

📄 [`examples/tutorial/07_library.sigil`](examples/tutorial/07_library.sigil)

---

## 第 9 章 十个坑

| # | 坑 | 正确写法 |
|---|---|---|
| 1 | 变量叫 `r`，`o! T r;` 被当成返回印记 | 改名 `rb` / `rs`，或写成 `r ;`（加空格） |
| 2 | 位或写成 `\|.` | `\|.` 是逻辑或；位或是 `\|^`，异或是 `^^`，位与是 `&^` |
| 3 | 全局对象忘了 `o!` | 文件作用域一律要 `o!` |
| 4 | 形参没用，`-Werror` 报错 | 函数体里写 `(v.)arg;` 消费掉 |
| 5 | `l! label:` 带冒号 | 标签不带冒号：`l! again;`，跳转 `g! again;` |
| 6 | `a!16` 想对齐对象 | `a!16` 只用于 `s{`/`u{` 定义；对象用 `a@(aligned(16))` |
| 7 | 空返回写 `r;` | 要写 `r; ;`（`r;` 自带分号） |
| 8 | 把 `char c = 300` 这类窄化当安全 | 不拦，和 C 一样静默截断 |
| 9 | 以为指针参数有长度 | 参数来源未知，不做越界检查 |
| 10 | 手改生成的 `.c` | 只改 `.sigil`；`.c` 标了 `DO NOT EDIT` |

前七条会在转译期或编译期拦住你，后三条是纪律问题——完整清单见 [`MIGRATION.md`](MIGRATION.md)。

---

## 第 10 章 让 AI 帮你写

这套记号的另一个用处：AI 写它比写 C 更容易被检查。

给 AI 的 5 条规则：

1. **只许用 52 个印记**，不确定就查 [`SYNTAX.md`](SYNTAX.md)，不要发明
2. **写操作必须带 `m`**：`x m, 1` 不是 `x = 1`
3. **每段代码必须过 `--check`**，再看生成 C
4. **报错先读插入符那一行**，`-->` 指向的就是问题列
5. **别猜语法**，跑一遍比想十分钟快

验证循环：

```bash
python3 sigilc.py x.sigil --check          # 语法 + 类型 + 边界
python3 sigilc.py x.sigil -o x.c           # 生成
gcc -std=c99 -Wall -Wextra -Werror -pedantic x.c -o x
./x
```

AI 常犯的错（都是实测见过的）：

| 错误 | 表现 | 修法 |
|---|---|---|
| 位运算用 `\|.` | 生成 `\|\|`，结果变布尔 | 换 `\|^` |
| 忘了 `o!` | "File-scope object declarations must begin with 'o!'" | 补 `o!` |
| `r@` 加在非指针上 | 类型错误 | `r@` 只修饰指针 |

**结论**：AI 不是"会写 Sigil-C"，是"写错了会被抓住"。这才是它比裸 C 强的地方。

---

## 第 11 章 接下来写什么

按难度：

1. **CRC32**（50 行）：位运算 + 查表，练 `|^` 和 `&^`
2. **内存池**（100 行）：在 `u1[1024]` 上做空闲链表，练指针来源
3. **PNG 头解析**（100 行）：位域 + 大端，`wire.sigil` 的直系亲属
4. **小 VM**（150 行）：已经有一个现成的 [`examples/vm.sigil`](examples/vm.sigil)
5. **配置解析器**（180 行）：字符串扫描，会逼你把边界检查用熟

写完之后，如果它真的被你每天用——那这门语言对你就成立了。

---

## 一句话总结

三种码，一套检查：

- **软件**：越界、悬垂、指针走丢 → 转译期拦
- **嵌入**：`volatile`、环形缓冲、丢帧 → 语义和 C 一致，但写操作可见
- **硬件**：布局、位域、端序 → `t!` + `offsetof` 钉死 ABI

它不试图变成另一种语言，只是让 C 的这三点变得**看得见**。
