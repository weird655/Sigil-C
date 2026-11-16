# Sigil-C 使用手册

**版本：v1.8.3**

> Core v1 是稳定面；`!` 飞线层是 Layer 2 实验面。使用 `!` 前先读 [`COMPATIBILITY.md`](COMPATIBILITY.md)。
>
> 本文是官方使用教程与规范；`!` 的完整教程统一在 [`WIRING.md`](WIRING.md)。

---

## 0. 范围与安全

### 稳定性

| 面 | 状态 | 承诺 |
|---|---|---|
| Core v1（非 `!` 语法） | 冻结 | v1.x 只加不改 |
| Layer 2 `!` 飞线层 | 实验 | 允许使用，不纳入 Core v1 冻结 |
| libc 覆盖 | 封闭集合 | v1.x 不扩名单 |

### 三条安全规则

1. 改代码前先提交或备份。
2. 局部包不离开函数；函数返回后槽会悬垂。
3. 不把 `!` 当安全边界；它没有借用检查、生命周期或运行时保护。

构建前先检查：

```bash
sigilc --check src
sigilc --build src -o app --run
```

---

## 1. 安装与五分钟上手

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

单文件 zipapp：

```bash
python3 tools/build_standalone.py --zipapp
python3 dist/sigilc.pyz --version
```

---

## 2. 项目布局与命名空间

```text
src/
├── !math!/
│   └── core.sigil
└── !main!/
    └── main.sigil
```

规则：

- `!name!/` 是命名空间目录；整棵子树归 `name`
- 命名空间名：1–8 字符，`[a-z][a-z0-9_]*`
- 不允许嵌套 `!a!/!b!/`
- 全项目最多 16 个命名空间
- 没有 `!name!/` 目录时，`!name!.sigil` 文件前缀作为兼容回退
- 文件大小不设限；函数数量不设这个预算；上帝文件允许

### 预算

| 项 | 上限 |
|---|---:|
| 命名空间 | 16 |
| 每命名空间包声明 | 64，编号 0–63 |
| 每命名空间函数包导出 | 32 |

> 可以类比为 16 个配电箱、每箱 64 个空开、32 个开关；正文按命名空间/包/导出描述。

超出预算在 `--build` 扫描阶段直接失败，不进入编译。

> 命名空间不改 C 符号名：`!math!` 和 `!util!` 都写 `add` 仍会撞。`--build` 会在转译期报 `duplicate C symbol 'add'`，建议手动改名（如 `math_add`）。

---

## 3. 包、别名与导出

### 3.1 声明与绑定

```sigil
o! i4 v m, 5;

!1! P;          /* 声明包 1，别名 P */
!2! Q;          /* 声明包 2，别名 Q */
!2! m, v;       /* 包 2 指向文件级变量 v */
```

| 写法 | 含义 |
|---|---|
| `!n! NAME;` | 声明包；`NAME` 是别名，不是 C 变量 |
| `!n! m, target;` | 绑定；target 必须是文件级变量/函数 |
| `!/n/!` | 本地访问，lvalue；只在本文件 |
| `!name[n]!` | 外部访问，只支持函数包 |

### 3.2 本地访问

```sigil
i4 get(v.) {
    r; !/2/!;
}
```

本地访问不加命名空间前缀；`!/n/!` 只在本文件内。同命名空间的兄弟文件也要写 `!math[n]!`。

### 3.3 函数包导出

```sigil
i4 add(i4 a, i4 b) {
    r; a + b;
}

!1! P;
!1! m, add;      /* 导出 math.1 -> add */
```

外部调用：

```sigil
i4 main(v.) {
    r; !math[1]!(2, 3);
}
```

- 只有文件级函数包可跨文件导出
- 变量包 `!n! m, v;` 只登记，不导出
- `main` / `s@` 不导出
- 不支持重载；同名函数只保留第一个原型
- `!math[n]!` 只在 `--build` 中解析；单文件直接编译不认

构建：

```bash
sigilc --build src -o app --run
```

`.sigil-build/packages.txt`：

```text
math.1 -> src/!math!/core.sigil
math.1 target -> add
```

完整飞线语法、封锁域、地雷、切片见 [`WIRING.md`](WIRING.md)。

---

## 4. 外部扩展（C 侧）

### 4.1 libc

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
- 名单是封闭集合，见 [`STDLIB.md`](STDLIB.md)
- Linux 数学函数需要 `-lm`，放在源文件之后
- 不做“万能标准库”；v1.x 不扩名单

### 4.2 外部类型 `x!`

```sigil
#include <netinet/in.h>
#include <stddef.h>

x! struct sockaddr_in {
    u2 sin_family;
    u2 sin_port;
    u4 sin_addr;
};

t! (offsetof(sockaddr_in, sin_addr) == 4, "layout drift");
```

- 只登记字段，不生成定义；使用系统头里的类型
- 不透明句柄 `x! pthread_t;` 只允许过指针
- 字段访问、`offsetof`、`z?` 按登记类型检查
- 用 `t!` + `offsetof` 钉住布局假设
- 每个标量/数组/指针字段会自动生成 `SIGIL_STATIC_ASSERT` 比较宽度；位域除外（C 不能对它做 sizeof）

### 4.3 头文件输出

```bash
sigilc lib.sigil -o lib.c --emit-header
# 生成 lib.c + lib.h，供 C 侧调用
```

共享前导头：

```bash
sigilc lib.sigil -o lib.c --emit-header \
    --emit-prelude sigil_prelude.h --prelude sigil_prelude.h
```

### 4.4 多文件构建

```bash
sigilc --build src -o app --run
```

- 扫描顶层函数签名，注入其他文件原型
- 每个文件各自生成 C，统一链接
- 外部飞线 `!name[n]!` 在同一阶段解析
- ABI 就是 C ABI；没有自己的运行时

### 4.5 只读工具

```bash
sigilc --check src
sigilc --netlist src/!math!/core.sigil
sigilc --fmt src --fmt-check
```

`--netlist` 是单文件网表，会输出 `# namespace:`；跨文件包索引看 `.sigil-build/packages.txt`。

---

## 5. 使用规范

### MUST

- 命名空间目录用 `!name!/`，全小写，1–8 字符
- 包号 `0–63`，不写前导零
- 外部调用写 `!math[n]!`，本地写 `!/n/!`
- 跨文件只导出文件级函数包
- 含 `!math[n]!` 的源码用 `--build` 构建
- 提交前跑 `--check`、`--build` 和测试

### SHOULD

- 一个目录一个命名空间，不嵌套
- 上帝文件可以大，但包声明按命名空间算
- 变量包只做本地接线
- 外部类型用 `x!` + `t!` 钉布局
- 数学函数链接 `-lm`
- C 的 `sizeof` 写成 `z? 类型`（如 `z? i4`）

### NEVER

- 不要用 `!` 做安全边界或生命周期保证
- 不要把局部包带出函数
- 不要跨文件访问变量包/局部包
- 不要嵌套 `!a!/!b!/`
- 不要把 `![...]!` 当包引用
- 不要扩“万能标准库”名单

---

## 6. 错误对照表

| 错误 | 原因 | 修法 |
|---|---|---|
| `namespace '!X!' is invalid` | 超 8 字符/大写/非法字符 | 改小写 1–8 字符 |
| `package !64! ... 0-63` | 包号越界 | 用 0–63 |
| `too many packages in namespace` | 一箱超 64 个包声明 | 拆命名空间或删包 |
| `too many namespaces` | 超 16 个命名空间 | 合并目录 |
| `nested package namespaces` | `!a!/!b!/` | 只留一层 |
| `duplicate package !N!` | 同空间重复包号 | 改号或合并 |
| `package '!math[1]!' is not exported` | 目标不是函数包/未绑定 | 用 `!1! m, function;` |
| `namespace '!nope!' is not declared` | 没有对应目录/前缀 | 建 `!nope!/` 或改前缀 |
| `package '!math[9]!' is not declared` | 包号不存在 | 声明 `!9! NAME;` 或改号 |
| `targets variable 'x'` | 变量包不导出 | 跨文件只导出函数包 |
| `duplicate C symbol 'add'` | 两个文件同名 C 函数 | 改名，如 `math_add` |
| `x! field width drift` | `x!` 登记宽度与真实头不符 | 改登记类型 |
| `Undeclared identifier 'sizeof'` | 用了 C 的 sizeof | 写 `z? 类型` |
| `Undeclared identifier` | 外部飞线没用 `--build` | 用项目构建 |
| `data definition has no type` | 变量包跨文件 | 不要导出变量 |

---

**先断电，再接线。小心触电。**
