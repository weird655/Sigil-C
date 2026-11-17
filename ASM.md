# Sigil-ASM（实验）

**版本：v1.30.0**

> **源语法就是 Sigil-C**，不是另造 `io/loop` 小语言。  
> Sigil-ASM 只做一件事：把受限的 Sigil-C 子集直出 x86-64 汇编，**不做安全检查**。

---

## 1. 为什么叫 ASM

不是机器码，也不是完整 Sigil-C：

- 源文件仍是 `.sigil`
- 复用同一个 Lexer / Parser / AST
- 目标改成 x86-64 汇编
- `!` 飞线保留在源语言里，不做风险检查
- 溢出、生命周期、堆、越界：一律不管

它接近汇编的地方是**生成方式和限制**，不是让你手写汇编。

---

## 2. 用法

```bash
# Linux / WSL：SysV
python sigilc.py --asm src/main.sigil -o main.s
gcc main.s -o main

# Windows：Win64
python sigilc.py --asm src/main.sigil --asm-abi win64 -o main.s
gcc main.s -o main.exe
```

`--asm-abi` 默认按平台：

- Windows → `win64`
- Linux/WSL → `sysv`

`--raw-asm` 是同一个后端的隐藏别名。

---

## 3. 当前支持的 Sigil-C 子集

- 整数/指针局部变量
- 参数、返回值、直接函数调用
- `+ - * / %`、位运算、比较
- `i? / e:`、`w~`、`d~`、`f~`
- `b! / c^`
- 全局整数变量
- 字符串字面量 + `printf`
- 一元 `- ! ~ * &`
- 简单指针下标读取
- SysV 前 6 个参数 / Win64 前 4 个参数

---

## 4. `!` 飞线

`!` 飞线在 Sigil-C 里是什么，这里仍然是什么：

- **不查**生命周期
- **不查**溢出
- **不查**堆
- **不查**越界
- 不做 P0/P1

ASM 后端只负责把能降到当前子集的 AST 生成为汇编；无法降级的 `!` 形式直接报错，不静默猜测。

---

## 5. 明确不支持

- 结构体、数组、位域、浮点
- 复杂包/plant 形式
- 间接调用、函数指针
- 超过 6（SysV）/4（Win64）个参数
- 栈上传参
- 复杂 lvalue 写入
- 优化、寄存器分配、调度
- 调试信息

报错示例：

```text
ASM backend does not support ...
```

---

## 6. 设计

```text
Sigil-C source
  → Lexer → Parser → AST
  → AsmGenerator（栈机式暴力生成）
  → x86-64 AT&T
```

当前：

- 每个局部变量固定 8 字节栈槽
- 表达式结果放 `%rax`
- 二元运算 `pushq/popq`
- 不分配寄存器
- 不优化

---

## 7. 已验证

```sigil
i4 add(i4 a, i4 b) { r; a + b; }
i4 main(v.) {
    o! i4 x m, 2;
    o! i4 y m, 3;
    r; add(x, y);
}
```

返回 5；循环 `printf`、`for + if + global` 也已手工验证。

第 76 层是 ASM smoke。

---

## 8. 定位

> **Sigil-C：完整语言 + 安全边界 + C 后端。**  
> **Sigil-ASM：同一语法，极小子集，直出汇编，不查风险。**

不是生产工具，是暴力实验线。
