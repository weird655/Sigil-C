# Sigil-C 使用手册

**版本：v1.8.0 · 小心触电**

> 这是一份“能照着做”的手册：先安全，再上手，再讲清本地飞线、外部飞线、外部扩展和硬性规范。
>
> **Core v1 是稳定面；`!` 是 Layer 2 实验面。** 用 `!` 之前先读 [`COMPATIBILITY.md`](COMPATIBILITY.md)。

---

## 0. 安全须知（先断电）

`!` 不是安全指针，是编译期接线。它能把名字、存储、可见性重新接一遍；接错不会在编译期全部拦住。

三条铁律：

1. **先备份，再接线**：改 `.sigil` 前先提交或复制。
2. **局部包不过夜**：函数内的 `!n!` 局部槽在函数返回后悬垂；不要把它带出函数。
3. **不拿 `!` 当安全边界**：没有借用检查、没有生命周期、没有运行时保护。需要这些，用别的工具。

断电顺序：

```bash
sigilc --check src            # 先检查，不生成
sigilc --build src -o app     # 再构建
./app                         # 最后上电
```

---

## 1. 五分钟上手

```bash
python3 sigilc.py --version
python3 sigilc.py examples/tutorial/01_hello.sigil -o hello.c
cc -std=c99 hello.c -o hello
./hello
```

装成命令：

```bash
python3 -m pip install .
sigilc --version
```

多文件：

```bash
sigilc --build src -o app --run
```

---

## 2. 项目布局：电箱、空开、开关

```text
src/
├── !math!/
│   └── core.sigil
└── !main!/
    └── main.sigil
```

- `!name!/` 是**电箱**（命名空间目录）
- `!n!` 是**空开**（包声明）
- `!n! m, function;` 是**开关**（函数包导出）
- 本地用 `!/n/!`；外部用 `!name[n]!`

### 硬预算

| 项 | 上限 |
|---|---:|
| 电箱 `!name!/` | 全项目 16 个 |
| 每箱空开 `!n!` | 64 个，`n ∈ 0–63` |
| 每箱开关（函数包导出） | 32 个 |
| 命名空间名 | 1–8 字符，`[a-z][a-z0-9_]*` |
| 嵌套命名空间 | 不允许 |

**上帝文件允许**：函数数量不限，文件大小不设这个预算；包声明按命名空间算，不按文件算。

---

## 3. 本地飞线

本地飞线只在当前文件/当前电箱内用，**不加电箱前缀**。

```sigil
o! i4 v m, 5;

!1! P;          /* 声明包 1，别名 P */
!2! Q;          /* 声明包 2，别名 Q */
!2! m, v;       /* 包 2 指向变量 v */

i4 get(v.) {
    r; !/2/!;   /* 读 v，不加 !math! 前缀 */
}
```

- `!n! P;` 是声明；`P` 是包别名，不是 C 变量
- `!n! m, target;` 是绑定；target 必须是文件级变量/函数
- `!/n/!` 是本地访问：读、写、调用
- 变量包和函数包都可在本地用；跨文件只导出函数包

**局部包**（函数内）：

```sigil
i4 f(v.) {
    o! i4 x m, 1;
    !1! m, x;
    r; !/1/!;
}
```

局部包用全局 `void *` 槽，函数返回后悬垂；只在函数内用完，别返回、别存。

---

## 4. 外部飞线

外部飞线跨文件/跨目录，**必须加电箱名和方括号**：

```sigil
!math[1]!(2, 3)
```

不是：

```sigil
!math!1!()     /* 旧写法，已弃用 */
!{math}[1]!()  /* 不要花括号 */
```

### 完整例子

`src/!math!/core.sigil`：

```sigil
i4 add(i4 a, i4 b) {
    r; a + b;
}

!1! P;
!1! m, add;      /* 导出 math.1 -> add */
```

`src/!main!/main.sigil`：

```sigil
i4 main(v.) {
    r; !math[1]!(2, 3);
}
```

```bash
sigilc --build src -o app --run   # 退出码 5
```

`.sigil-build/packages.txt`：

```text
math.1 -> src/!math!/core.sigil
math.1 target -> add
```

### 外部飞线的规则

| 规则 | 说明 |
|---|---|
| 只导出函数包 | `!n! m, function;`；变量包只登记，不导出 |
| 只走 `--build` | `!math[n]!` 在项目预处理阶段解析；单文件直接编译不认 |
| 不导出 `main` / `s@` | `main` 唯一；`s@` 是文件内部链接 |
| 不支持重载 | 同名函数只保留第一个原型 |
| 不支持跨文件变量/类型 | 全局变量、结构体、枚举、链接、封锁域、netlist 仍单文件 |
| 不允许嵌套电箱 | `!a!/!b!/` 直接失败 |

### 导出预算

每个电箱最多 **32 个函数包导出**。变量包、局部包、内部函数不占“开关”名额，但也不跨文件可用。

---

## 5. 外部扩展（C 侧）

“外部扩展”不是包管理器，是 C 互操作面。

### 5.1 libc 头文件

```sigil
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

i4 main(v.) {
    printf("%d\n", (i4)strtod("3.5", NULL));
    r; 0;
}
```

- `#include` 决定登记哪些原型
- 名单是**封闭集合**，见 [`STDLIB.md`](STDLIB.md)
- Linux 数学函数要 `-lm`；`gcc ... -lm` 放在源文件后
- 不做“万能标准库”；v1.x 不扩名单

### 5.2 外部类型 `x!`

只登记字段，不生成定义，使用系统头里的那份：

```sigil
#include <netinet/in.h>

x! struct sockaddr_in {
    u2 sin_family;
    u2 sin_port;
    u4 sin_addr;
};

t! (offsetof(sockaddr_in, sin_addr) == 4, "layout drift");
```

- `x! struct Name { fields };`：登记字段，生成 C 用真实拼写
- `x! pthread_t;`：不透明句柄，只允许过指针；访问字段报错
- 不生成定义；布局错误用 `t!` + `offsetof` 钉死

### 5.3 头文件输出

```bash
sigilc lib.sigil -o lib.c --emit-header
# 生成 lib.c + lib.h，给 C 侧调用
```

共享前导头：

```bash
sigilc lib.sigil -o lib.c --emit-header \
    --emit-prelude sigil_prelude.h --prelude sigil_prelude.h
```

### 5.4 多文件构建

```bash
sigilc --build src -o app --run
```

- 自动扫描顶层函数签名，注入其他文件原型
- 每个文件各自生成 C，统一链接
- 外部飞线 `!name[n]!` 在同一阶段解析
- 仍是 C99 工具链，ABI 就是 C ABI

### 5.5 只读工具

```bash
sigilc --check src                 # 静态检查
sigilc --netlist src/!math!/core.sigil   # 单文件网表
sigilc --fmt src --fmt-check       # 格式检查
```

`--netlist` 仍是**单文件**网表；跨文件包索引看 `.sigil-build/packages.txt`。

---

## 6. 严谨使用规范（MUST / SHOULD / NEVER）

### MUST

- 电箱目录名用 `!name!/`，全小写，1–8 字符
- 包号 `0–63`，不写前导零
- 外部调用写 `!math[n]!`，本地写 `!/n/!`
- 跨文件只导出文件级函数包
- 构建用 `--build`，不要单文件直接编译含 `!math[n]!` 的源码
- 提交前跑 `sigilc --check` + `--build` + 测试

### SHOULD

- 一个目录一个电箱；不要嵌套
- 上帝文件可以大，但包声明按命名空间算
- 变量包只做本地接线，不要指望跨文件
- 外部类型用 `x!` + `t!` 钉布局
- 数学函数链接 `-lm`

### NEVER

- 不要用 `!` 做安全边界/生命周期保证
- 不要把局部包带出函数
- 不要跨文件访问变量包/局部包
- 不要嵌套 `!a!/!b!/`
- 不要把 `![...]!` 当包引用（它是封锁/集合）
- 不要扩“万能标准库”名单；缺口就是缺口

---

## 7. 错误对照表

| 错误 | 原因 | 修法 |
|---|---|---|
| `namespace '!X!' is invalid` | 名字超 8 字符/大写/非法字符 | 改小写 1–8 字符 |
| `package !64! ... 0-63` | 包号越界 | 用 0–63 |
| `too many packages in namespace` | 一箱超 64 个包声明 | 拆电箱或删包 |
| `too many namespaces` | 超 16 个电箱 | 合并目录 |
| `nested package namespaces` | `!a!/!b!/` | 只留一层 |
| `duplicate package !N!` | 同箱重复包号 | 改号或合并 |
| `package '!math[1]!' is not exported` | 目标不是函数包/未绑定 | 用 `!1! m, function;` |
| `Undeclared identifier` | 外部飞线没用 `--build` | 用项目构建 |
| `data definition has no type` | 变量包跨文件 | 不要导出变量 |

---

**先断电，再接线。小心触电。**
