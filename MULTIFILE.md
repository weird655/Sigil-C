# 多文件 / 跨文件支持

状态：**v1.5.0（函数包 + 文件命名空间）**

`--build DIR` 现在会先扫描目录下所有 `.sigil` 的顶层函数签名，把**其他文件的原型**注入当前文件，再各自生成 C、统一链接。

## 用法

```text
src/
├── math.sigil
└── main.sigil
```

`math.sigil`：

```sigil
i4 add(i4 a, i4 b) {
    r; a + b;
}
```

`main.sigil`：

```sigil
i4 main(v.) {
    r; add(2, 3);
}
```

```bash
sigilc --build src -o app --run
```

不需要手写 `.h`，也不需要 `#include`。

## 它做了什么

1. 读入所有 `.sigil`
2. 扫描顶层函数签名（正则，单行签名）
3. 对每个文件，把**其他文件**的原型拼到源码前面
4. 各自 `compile_source` → `.sigil-build/*.c`
5. 一次 `gcc` 链接

生成的 C 里会多一行：

```c
int32_t add(int32_t a, int32_t b);
```

这是跨文件调用的“桥”，不是新的运行时。

## 支持

- 多文件、子目录
- 跨文件函数调用
- 返回值/参数类型
- `v.` 空返回
- 指针参数（`p* u4` 等）
- 与 `--emit-header` 共存（头文件仍给 C 侧用）

## 不支持

- 跨文件结构体/联合体/枚举定义共享
- 跨文件全局变量（没有 extern 机制）
- `import` / 模块 / 命名空间
- 函数重载、同名不同签名
- 多行函数签名
- 宏跨文件
- `s@` 静态函数跨文件（按 C 语义不可见）
- 真正的分离编译/增量编译

> 这是“函数级跨文件”，不是模块系统。类型/全局/模块要么写进同一文件，要么等下一层。

## `!` 文件命名空间与外部调用（v1.5.0）

文件前缀 `!name!` 登记命名空间；文件内仍用 `!n!`。

`!math!.sigil`：

```sigil
o! i4 v m, 5;
!1! P;
!2! Q;
!2! m, v;
i4 get(v.) { r; !/2/!; }
!1! m, get;
```

- 本地调用**不加前缀**：`!/2/!`
- 外部调用**必须加前缀**：`!math!1!()` → 文件级 `get()`
- `!math!2!` 会改写成 `v`，但跨文件全局变量还没有 extern 机制，暂不支持

`.sigil-build/packages.txt`：

```text
math.1 -> !math!.sigil
math.2 -> !math!.sigil
math.2 target -> v
math.1 target -> get
```

规则：

- 只有 `!n! m, function;` 这种**文件级函数包**可跨文件调用
- 本地槽、封锁域、链接、地雷、长集合仍只在本文件内
- 同一个 `math.N` 跨文件重复声明，构建失败
- `--netlist` 仍是单文件网表

## 边界

- 原型扫描是**文本级**的：函数签名必须在一行内，`{` 紧跟 `)`。
- 同名函数只保留第一个原型；真正的重复定义交给 C 链接器报错。
- `main` 和 `s@` 不导出。
- 跨文件 `#include` 仍是 C 预处理器行为，不参与 Sigil-C 符号解析。

## 测试

第 55 层：

```text
math.sigil: i4 add(i4 a, i4 b)
main.sigil: r; add(2, 3);
build -> app
exit code 5
```

## 下一步

1. 项目级符号表（类型/全局/枚举）
2. `import`/`module` 语法
3. 真正的分离编译与增量
4. 跨文件 static/可见性规则
