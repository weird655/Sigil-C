# 迁移说明

## 当前主分支：`a&` → `p@`

取地址从 `a&` 改为 `p@`，原因是识别而不是输入：

- `p*` 是"指针 / 解引用"，`p@` 是"取地址"，同属 `p` 家族
- `@` 读作 at，和地址/位置相关；`&` 只是一个不表意的符号
- `c@` 仍然是只读，两个 `@` 各有所指：`c@` 管权限，`p@` 管地址

旧写法 `a&` 不再接受；迁移就是文本替换 `a&` → `p@`。

# C → Sigil-C 迁移对照

这不是"重写"，是**换记法 + 让转译器接手一部分 C 里靠人守的规矩**。

本文所有"拦住 / 没拦"的结论，都是用仓库里的 `sigilc.py` 逐条实测出来的（`--check`），不是设计承诺。凡是没拦的，会明确标出来——这份文档的价值就在于它不吹。

图例：🟥 转译期拦住　🟡 运行期（需 `--bounds-check`）　⬜ 仍需自己注意

---

## 0. 总览

| # | 经典 C 陷阱 | Sigil-C | 靠什么 |
|---|---|---|---|
| 1 | 常量下标越界 | 🟥 | 数组长度在类型里 |
| 2 | 运行期下标越界 | 🟡 | `SIGIL_IDX(i, N)` + `--bounds-check` |
| 3 | 返回局部变量地址 | 🟥 | 局部对象集合 |
| 4 | 局部地址存进全局 / 出参 | 🟥 | 同上 |
| 5 | 指针活过它指向的对象 | 🟥 | 来源 + 作用域深度 |
| 6 | 指针加偏移后越界解引用 | 🟥 | 来源偏移追踪 |
| 7 | 从 `a[i]` 取的指针再下标越界 | 🟥 | 同上 |
| 8 | 函数把入参存进全局，调用方传局部地址 | 🟥 | 跨函数逃逸摘要 |
| 9 | `restrict` 违约（同一对象两个参数） | 🟥 | 调用点来源比对 |
| 10 | 局部 `restrict` 指针声明后又走别的路径 | 🟥 | 受限基对象表 |
| 11 | 丢掉 `const` 的指针赋值 | 🟥 | 类型检查 |
| 12 | 指针与整数混用 | 🟥 | 类型检查 |
| 13 | 函数指针参数个数/类型错 | 🟥 | 调用校验 |
| 14 | 结构体成员名拼错 | 🟥 | 字段表 |
| 15 | 窄化赋值（`char c = 300`） | ⬜ | 不拦，C 也一样静默截断 |
| 16 | 未初始化局部变量 | ⬜ | 不做定值分析 |
| 17 | 空指针解引用 | ⬜ | 不做空值分析 |
| 18 | 堆：`malloc` 失败、`free` 后使用、双重 `free` | ⬜ | 不建模堆 |
| 19 | 有符号溢出 | ⬜ | 常量折叠会拦常量溢出，变量不拦 |
| 20 | `switch` 忘 `break` | ⬜ | 语义同 C，但会显式标 `SIGIL_FALLTHROUGH()` |
| 21 | 数组退化成指针后 `sizeof` | ⬜ | 语义同 C（`z? p` 就是指针大小） |
| 22 | 位域的符号性/布局 | ⬜ | 实现定义，和 C 一样 |
| 23 | 函数式宏的副作用 | ⬜ | 函数式宏本就不支持，宏只收字面量常量 |

**一句话**：C 里"编译器管不了、只能靠人"的越界与生命周期问题，这里大部分前移到转译期；**堆、空指针、未初始化、溢出仍然归你**。

---

## 1. 机械映射表（改 80% 的代码只需要这张）

| C | Sigil-C | 备注 |
|---|---|---|
| `int32_t` / `uint32_t` / `int8_t` | `i4` / `u4` / `i1` | 定宽 |
| `double` / `float` | `f8` / `f4` | |
| `char` | `c1` | |
| `size_t` | `z?` 的结果类型 | 也可直接写 `size_t` |
| `const T *p` | `p* c@ T p` | 只读指向物 |
| `T *p` | `p* T p` | |
| `T **p` | `p* p* T p` | 从右往左读反了：这里是从左往右 |
| `const T * const p` | `c@ p* c@ T p` | |
| `restrict T *p` | `r@ p* T p` | |
| `T *p = &x;` | `o! p* T p m, p@ x;` | |
| `T x;`（T 为用户类型） | `o! T x;` | 内建基类型可省 `o!`：`u4 x;` |
| `T a[N];` | `o! T[N] a;` | **维度在类型前缀里** |
| `x = v;` | `x m, v;` | |
| `x += v;` / `x -= v;` | `x m+ v;` / `x m- v;` | |
| `x *= v;` / `x /= v;` | `x m* v;` / `x m/ v;` | |
| `x++;` | `x m+ 1;` | |
| `a & b` / `a \| b` / `a ^ b` | `a & b` / `a \| b` / `a ^ b` | **位**运算 |
| `a && b` / `a \|\| b` | `a && b` / `a \|\| b` | **逻辑**运算（短路的那个） |
| `!a` | `!a` | 逻辑非 |
| `if (c) { } else { }` | `i? (c) { } e: { }` | |
| `while (c) { }` | `w~ (c) { }` | |
| `do { } while (c);` | `d~ { } w~ (c);` | |
| `for (i = 0; i < n; i++)` | `f~ (o! i4 i m, 0; i < n; i m+ 1) { }` | |
| `switch (v) { case 1: … default: }` | `s? (v) { k: 1: … d: … }` | |
| `break;` / `continue;` | `b!;` / `c^;` | |
| `return x;` / `return;` | `r; x;` / `r; ;` | `r;` 自带分号，空返回要再补一个 |
| `goto L;` / `L:` | `g! L;` / `l! L;` | 标签**不带冒号** |
| `struct { … } Name;` | `s{ Name { … };` | |
| `union { … } Name;` | `u{ Name { … };` | |
| `enum { A, B } Name;` | `e{ Name { A m, 0, B m, 1 };` | |
| `typedef` | **不需要** | 名字就是类型 |
| `sizeof x` / `sizeof(T)` | `z? x` / `z? T` | |
| `_Alignof(T)` | `a? T` | 结果 `size_t` |
| `abort()` / `__builtin_trap()` | `d!;` | 立即终止 |
| `offsetof(T, f)` | `offsetof(T, f)` | 内建 |
| `__attribute__((packed))` | `a@(packed)` | 白名单 |
| `__attribute__((aligned(16)))` | `a@(aligned(16))` | |
| `_Alignas(16)` | `a@(aligned(16))`（对象）；`a!16` 只用于 `s{`/`u{` 定义 | |
| `static`（文件作用域） | `s@` | |
| `inline` | `i@` | `s@ i@` = `static inline` |
| `unsigned x : 3;` | `u4 x w! 3;` | |
| `_Static_assert(c, "m");` | `t! (c, "m");` | |
| `int (*f)(int)` | `f^(i4) -> i4 f` | |
| `...` 变参 | `...` | 读取用 `va_list` / `va_arg` |
| `#define N 64` | `#define N 64` 或 `--define N=64` | 仅字面量常量 |
| `struct sockaddr_in` 等外部类型 | `x! struct sockaddr_in { … };` | 见 §4 |

---

## 2. 逐条陷阱对照（实测）

### 2.1 常量下标越界 🟥

```c
int a[3] = {1, 2, 3};
return a[5];                 /* 越界，C 编译器不管 */
```

```sigil
o! u4[3] a m, { 1, 2, 3 };
r; (i4)a[5];
```

```
error: Index 5 is out of bounds for an array of 3 element(s)
```

### 2.2 运行期下标越界 🟡

```sigil
o! u4[3] a m, { 1, 2, 3 };
r; (i4)a[i];
```

转译期放行，生成 `a[SIGIL_IDX(i, 3)]`。默认 `SIGIL_IDX` 展开为 `(i)`（零开销）；加 `--bounds-check` 后展开为检查函数，越界直接 `abort()`。

### 2.3 返回局部变量地址 🟥

```c
int *f(void) { int x = 1; return &x; }   /* 悬垂 */
```

```sigil
p* u4 f(v.) { o! u4 x m, 1; r; p@ x; }
```

```
error: Returning the address of local object 'x' would dangle after return
```

### 2.4 局部地址存进全局或出参 🟥

```sigil
o! p* u4 g;
v. f(v.) { o! u4 x m, 1; g m, p@ x; }
```

```
error: Storing the address of local object 'x' into 'g' would dangle after this function returns
```

出参同罪：`out m, p@ x;` → 同样的诊断。

### 2.5 指针活过它指向的对象 🟥

```c
int *p;
{ int x = 1; p = &x; }
use(p);                       /* x 已死 */
```

```sigil
o! p* u4 p;
i? (1) { o! u4 x m, 1; p m, p@ x; }
o! u4 y m, p* p;
```

```
error: Pointer refers to 'x', which is out of scope here
```

解引用、拷贝、当实参传出去——三种用法都会拦。

### 2.6 指针加偏移后越界解引用 🟥

```c
int a[3]; int *p = a;
p += 3;  return *p;           /* 一过末尾就解引用 */
```

```sigil
o! u4[3] a m, { 1, 2, 3 };
o! p* u4 p m, p@ a[0];
p m+ 3;
r; (i4)p* p;
```

```
error: Dereferencing a pointer into 'a' at element 3, outside 3 element(s)
```

### 2.7 从 `a[i]` 取的指针再下标 🟥

```sigil
o! p* u4 p m, p@ a[1];        /* 只剩 2 个元素可用 */
r; (i4)p[2];
```

```
error: Index 2 through a pointer into 'a' reaches element 3, outside 3 element(s)
```

### 2.8 跨函数逃逸 🟥

```c
int *slot;
void keep(int *p) { slot = p; }
void f(void) { int x = 1; keep(&x); }   /* 返回后 slot 悬垂 */
```

```sigil
o! p* u4 slot;
v. keep(p* u4 p) { slot m, p; }
v. f(v.) { o! u4 x m, 1; keep(p@ x); }
```

```
error: Argument 1 of 'keep' points to local object 'x', but 'keep' stores it into a global;
       it would dangle after this function returns
```

### 2.9 `restrict` 违约：同一对象两个参数 🟥

```c
void sum(int *restrict a, int *restrict b);
sum(arr, arr);                /* UB，C 静默接受 */
```

```sigil
u4 sum(r@ p* u4 a, p* u4 b) { r; a[0] + b[0]; }
sum(arr, arr);
```

```
error: Parameter 1 of 'sum' is 'r@' (restrict) but argument 2 aliases the same object 'arr'
```

### 2.10 局部 `restrict` 声明后又绕路 🟥

```sigil
o! r@ p* u4 p m, p@ arr[0];   /* 承诺：只经 p 访问 arr */
o! u4 x m, arr[1];            /* 违约 */
```

```
error: 'arr' is accessed through another path while a 'r@' (restrict) pointer claims exclusive access to it
```

### 2.11 丢掉 `const` 🟥

```c
const uint32_t *p; uint32_t *q = p;   /* 丢 const，C 会警告但你转个型就过去了 */
```

```sigil
v. f(p* c@ u4 p) { o! p* u4 q m, p; }
```

```
error: Incompatible initializer type for 'q'
```

（想硬来只能显式强转，那就已经是故意了。）

### 2.12 指针与整数混用 🟥

```sigil
o! p* u4 p m, 0;
o! u4 x m, p + 1;             /* 指针赋给整数 */
```

```
error: Incompatible initializer type for 'x'
```

### 2.13 函数指针参数错 🟥

```sigil
o! f^(i4) -> i4 fp m, g;
o! i4 x m, fp(1, 2);
```

```
error: Callable expects 1 arguments, got 2
```

### 2.14 成员名拼错 🟥

```sigil
s{ P { i4 x; };
v. f(v.) { o! P p; p.y m, 1; }
```

```
error: 'P' has no member named 'y'
```

---

## 3. 没拦的（这部分请按 C 的纪律来）

### 3.1 窄化赋值 ⬜

```sigil
o! c1 c m, 300;               /* 生成 char c = 300; 静默截断成 44 */
```

常量在范围外也不报。**C 同样静默**，所以这不是退步，但也别指望它兜底。

### 3.2 未初始化局部 ⬜

```sigil
o! i4 x;
r; x;                         /* 未定义值，原样生成 */
```

没有定值分析。

### 3.3 空指针解引用 ⬜

```sigil
o! p* u4 p m, 0;
r; (i4)p* p;                  /* 不拦 */
```

没有空值分析。

### 3.4 堆 ⬜

`malloc` / `free` **不是内建**，需要自己声明原型：

```sigil
p* v. malloc(u8 n);
v. free(p* v. p);

v. f(v.) { o! p* i4 p m, (p* i4)malloc(z? i4); free(p); }
```

没有堆模型，所以：分配失败、`free` 后使用、双重 `free`、泄漏——**全部归你**。

### 3.5 有符号溢出 ⬜

常量折叠会拦常量溢出；变量运算不拦，和 C 一样。

### 3.6 `switch` 忘 `break` ⬜

语义与 C 一致（会穿透）。区别是：未终止的 case 会被显式标上 `SIGIL_FALLTHROUGH()`，`-Wextra -Werror` 下不会静默。这是**可读性收益，不是安全收益**。

### 3.7 `sizeof` 用在退化后的指针上 ⬜

```sigil
u4 f(p* u4 p) { r; (u4)(z? p); }   /* 指针大小，不是数组大小 */
```

和 C 完全一致。想拿数组长度，在同一个作用域里用 `z? a / z? a[0]`。

### 3.8 位域布局与符号性 ⬜

实现定义，和 C 一样。`w!` 只校验"宽度不超过基底类型"。

---

## 4. 直接写不了的 C，以及逃生舱

| C 写法 | 状态 | 逃生方式 |
|---|---|---|
| 函数式宏 `#define SQ(x) ((x)*(x))` | 不支持 | 写成 `i@` 函数，或保持 C 侧宏 |
| `#define` 非字面量常量 | 不支持 | `--define NAME=VALUE` 或源文件里保留 `#define` 并只当文本透传 |
| 系统头里的结构体 | 默认是黑盒 | `x! struct sockaddr_in { … };` 声明字段，**不生成定义** |
| `typeof` / `__builtin_*` | 不支持 | 预处理行原样透传，但类型检查盲区 |
| 位运算优先级/隐式转换规则 | 与 C 一致 | 无需迁移 |
| `goto` 跳出多层 | 支持 | `g!` / `l!` |

---

## 5. 迁移步骤（建议按这个顺序）

1. **机械替换**：按 §1 的对照表换类型、指针、赋值、控制流。这一步不用动逻辑。
2. **`--check` 通读**：`python3 sigilc.py app.sigil --check`，把 🟥 类错误逐条改掉——它们大多是真 bug，不是搬家噪音。
3. **补上 ⬜ 的纪律**：堆、空指针、未初始化、窄化。这些 C 里怎么防，这里还怎么防。
4. **钉住假设**：把 ABI/布局假设写成 `t!` + `offsetof` / `z?` 断言，编译期就炸，而不是运行到客户机才炸。
5. **发布库**：`--emit-header` 出 `.h`，`s@` 的符号自动排除；生成的 `.c` 可以被普通 C 代码 `#include` 并链接。

---

## 6. 为什么这套能拦住（一句话版）

C 里数据流散落在 `=`、`++`、`*p =`、`f(&x)`、宏展开里；Sigil-C 把**写**收进 `m` 家族、且禁止出现在表达式里，于是"谁改了谁"在语法层就是可枚举的。**指针来源**（从哪个对象来、偏移多少、作用域多深）也是同一份信息的延伸。

> 反过来说：这套东西给你的是**词法可见 + 早期报警**，不是借用检查器。别名经函数指针、经堆、经多层转换之后就断了——这部分永远归你。

## 运算符：C 派

| 旧 | 新 |
|---|---|
| `&.` `\|.` `!.` | `&&` `\|\|` `!` |
| `&^` `\|^` `^^` `~^` | `&` `\|` `^` `~` |
| `=?` `!?` | `==` `!=` |
| `%` | `mod`（`%` 暂留兼容别名） |

取地址的 `p@` 已经让 `&` 空出来，位/逻辑/相等因此可以回到 C99 拼写。
