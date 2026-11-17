# Sigil-C 飞线层教程（Layer 2）

**状态：v1.15.0，允许使用，实验性，不纳入 Core v1 冻结。** 见 [`COMPATIBILITY.md`](COMPATIBILITY.md)。

> 这是 `!` 家族的唯一教程。`SYNTAX.md` 是规范速查，`MULTIFILE.md` 只讲 `--build` 的多文件行为。
>
> **危险工具，请勿使用。** 没有生命周期检查；局部包在函数返回后悬垂。

---

## 0. 规范前强边界

先读 [`BOUNDARIES.md`](BOUNDARIES.md)：

- `x!` 不校验位域宽度；位域 ABI 要自己断言。
- 命名空间函数名不得与局部变量/参数/字段同名；token 改名不区分作用域。

## 1. 术语

| 术语 | 写法 | 说明 |
|---|---|---|
| 命名空间 | `!math!/` 目录 | 目录级作用域；全项目 ≤16 个 |
| 包 | `!1!` | 编译期包槽，编号 0–63 |
| 包别名 | `!1! P;` 的 `P` | Sigil-C 别名，不是 C 变量 |
| 目标 | `!1! m, add;` 的 `add` | 文件级函数或变量 |
| 本地引用 | `!/1/!` | 本文件优先；同命名空间的导出函数包也可解析 |
| 外部引用 | `!math[1]!` | 跨文件访问，只支持函数包 |
| 导出 | `!1! m, function;` | 外部可见的函数包 |

---

## 2. 目录与预算

```text
src/
├── !math!/
│   └── core.sigil
└── !main!/
    └── main.sigil
```

- `!name!/` 是命名空间目录；整棵子树归 `name`
- 命名空间名：1–8 字符，`[a-z][a-z0-9_]*`
- 不允许嵌套 `!a!/!b!/`
- 全项目 ≤16 个命名空间
- 每个命名空间 ≤64 个包声明，编号 0–63
- 每个命名空间 ≤64 个函数包导出
- 文件大小不设限；函数数量不设这个预算；上帝文件允许

预算可以类比为：16 个配电箱，每箱 64 个空开、64 个开关。**只是类比，文档正文用命名空间/包/导出。**

---

## 3. 本地飞线

```sigil
o! i4 v m, 5;

!1! P;          /* 声明包 1，别名 P */
!2! Q;          /* 声明包 2，别名 Q */
!2! m, v;       /* 包 2 指向文件级变量 v */

i4 get(v.) {
    r; !/2/!;   /* 本地访问，不加命名空间前缀 */
}
```

规则：

- `!n! NAME;`：声明包，`NAME` 是别名
- `!n! m, target;`：绑定；target 必须是文件级变量/函数
- `!/n/!`：本文件声明优先；若本文件没声明，同命名空间的导出函数包会解析到目标函数
- 文件级绑定是编译期别名，零运行时
- 变量包和函数包都可本地使用；跨文件只导出函数包

### 局部包

```sigil
i4 f(v.) {
    o! i4 x m, 1;
    !1! m, x;
    r; !/1/!;
}
```

- 局部包用全局 `void *` 槽 + 类型转换
- 函数返回后悬垂，编译器不检查
- 只在函数内用完；不要返回、不要存到全局

---

## 4. 外部飞线

外部引用写 `!name[n]!`；只在 `--build` 项目构建中解析。

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
math.1 target -> math_add
```

规则：

- 只导出文件级函数包
- 变量包 `!n! m, v;` 只登记，不导出
- `main` / `s@` 不导出
- 同名函数只保留第一个原型；不支持重载
- 不支持跨文件变量/类型/链接/封锁/netlist
- 命名空间会改 C 符号名：`!math!` 的 `add` 生成 `math_add`；跨箱同名不再撞
- `!math[n]!` 不能单文件直接编译

---

## 5. 双向焊接 `!>n<!`

```sigil
o! i4 base m, 10;
!>2<! base other;   /* other 与 base 同一存储 */

i4 main(v.) {
    other m, 20;
    r; base;         /* 20 */
}
```

- 文件级：B 与 A 是同一块存储，解析期改名
- 局部级：B 经包槽读写 A
- 多条 `!>` 形成链；环和类型不匹配编译期拒绝
- 没有运行时版本号，改一边另一边立刻变

---

## 6. 封锁域与协调集

协调集把入口函数编组；封锁域把包关进去，只有 mask 为 1 的函数能访问。

```sigil
!/[0]/! m, f1, f2, f3;      /* 短集合，id 也可以是变量名 */

![101]! !/[0]/! {
    !1! secret;
    !1! m, base;
}

i4 f1(v.) { r; !/1/!; }    /* 放行 */
i4 f2(v.) { r; !/1/!; }    /* 拒绝：中间位 0 */
i4 f3(v.) { r; !/1/!; }    /* 放行 */
```

- 短集合用二进制 mask，**不写逗号**：`![101]!`
- mask 位数必须等于展开后的成员数
- 集合可嵌套；深度优先、去重、环拒绝
- 封锁域可嵌套；内层与外层按交集收缩
- 域外包仍全局可见；域内包只由 mask 放行
- 不检查函数是否存在/签名是否一致

### 长集合

```sigil
!/[[0]]/! m, fn1, fn2, fn3, fn4, fn5, fn6, fn7, fn8, fn9, fn10;

![1,3,5]! !/[[0]]/! {      /* 长集合用 1 基位置，写逗号 */
    !1! X;
    !1! m, base;
}
```

- 短集合 `![101]!`；长集合 `![1,3,5]!`；全开 `![*]!`
- 长集合声明后不可再赋值
- 位置越界编译期拒绝

---

## 7. 地雷包 `!n!!`

```sigil
!1!! m, base;     /* 唯一绑定 */
```

- 第二次绑定、普通 `!n!` 重绑、`!>k<!` 抢名都会编译期失败
- 错误同时给出首次与第二次位置
- 只保证“只绑一次”，不保证生命周期安全

---

## 8. 位/字节切片

```sigil
o! u4 reg m, 0;

!1! FLAG;   !1! m, bit(reg, 3);       /* 第 3 位 */
!2! FIELD;  !2! m, bits(reg, 4, 3);   /* 从第 4 位起 3 位 */
!3! BYTE0;  !3! m, byte(reg, 0);      /* 第 0 个字节 */

i4 main(v.) {
    !/1/! m, 1;          /* 置位 */
    !/2/! m, 5;          /* 写 3 位字段 */
    !/3/! m, 0x5A;       /* 写字节 */
    r; 0;
}
```

- `bit(expr,k)`：整数；单 bit
- `bits(expr,k,w)`：整数；宽度 w
- `byte(expr,i)`：整数/浮点；对象字节
- 写入是读改写；不是零成本
- `--netlist` 的 `[fields]` 段会列出切片

---

## 9. 万用表与 trap

```bash
sigilc --netlist file.sigil                         # 文本网表
sigilc --netlist --netlist-format json file.sigil  # 对象/态射 JSON
sigilc --netlist --netlist-format dot file.sigil   # Graphviz DOT
sigilc --netlist --netlist-format mermaid file.sigil # Mermaid
sigilc --netlist --netlist-format html file.sigil -o graph.html # 自包含 HTML\nsigilc --build src --netlist --netlist-format json -o graph.json   # 先导出数据\nsigilc --build src --netlist --netlist-format viewer -o viewer.html # 空壳，拖 JSON 进去
sigilc --build src --netlist --netlist-format html -o project.html # 跨文件项目图
```

- `viewer` 是空壳 HTML：把 `--netlist-format json` 导出的 `.json` 拖进去才开始渲染
- 2D PCB 视图：直角走线、过孔、暗色网格；复古终端 UI + 动态风场背景
- `--netlist` 文本模式打印 `# namespace:`、`[qualified]` 与 packages/fields/links/groups/gates/landmines/confinement
- 图模式输出 `objects` + `morphisms`（有向多重图，不是树）；包、目标、字段、组、门、地雷都是对象
- `--build DIR --netlist` 合并整个项目：文件节点、共享命名空间、跨文件 `uses` 边
- HTML 模式自带 SVG 视图：节点拖拽、画布缩放/平移、点节点看入/出边、集合框、并行边曲线
- 示例：[`docs/netgraph-2d.png`](docs/netgraph-2d.png) / [`docs/viewer.png`](docs/viewer.png)
- **单文件**，不跨文件
- `--trap-trace` 与 `--shadow-stack` 互斥、默认关；调试用，不进 release
- `--shadow-stack` 不是生命周期检查

---

## 10. 预算与错误表

| 项 | 上限 |
|---|---:|
| 命名空间 | 16 |
| 每命名空间包声明 | 64（0–63） |
| 每命名空间函数包导出 | 64 |
| 命名空间名 | 1–8 字符小写 |

| 错误 | 原因 | 修法 |
|---|---|---|
| `namespace ... invalid` | 名字非法 | 小写 1–8 字符 |
| `package !64! ... 0-63` | 包号越界 | 用 0–63 |
| `too many packages` | 一箱超 64 | 拆命名空间或删包 |
| `too many namespaces` | 超 16 | 合并目录 |
| `nested package namespaces` | 嵌套目录 | 只留一层 |
| `duplicate package !N!` | 同空间重复 | 改号或合并 |
| `package '!math[1]!' is not exported` | 非函数包/未绑定 | 用 `!1! m, function;` |
| `namespace '!nope!' is not declared` | 没有对应目录/前缀 | 建 `!nope!/` 或改前缀 |
| `package '!math[9]!' is not declared` | 包号不存在 | 声明 `!9! NAME;` 或改号 |
| `targets variable 'x'` | 变量包不导出 | 跨文件只导出函数包 |
| `has no file-level binding` | 声明了没绑定 | 用 `!n! m, function;` |

---

## 11. 安全规则

- `!` 不是安全指针；没有借用检查、生命周期、运行时保护
- 局部包不过夜：不要带出函数
- 跨文件只导出函数包；变量/类型/组/地雷/切片不跨文件
- 不要把 `![...]!` 当包引用；它只管封锁/集合
- 预算不是建议，是构建期硬限制；超限直接失败
- 先 `--check`，再 `--build`，最后上电
- 出问题先看 `packages.txt` 和 `--netlist`，不要猜

**先断电，再接线。小心触电。**
