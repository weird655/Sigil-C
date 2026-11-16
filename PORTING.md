# Porting Probes: 3 external-style attempts

日期：2026-11-16  
状态：**external-style probes（外部风格探针），不是完整 OSS 项目的移植**。

真实的第三方仓库移植需要选定具体项目、版本、构建系统和依赖；本轮先做三个“外部项目里最常见形状”的最小探针，记录摩擦点。

| 探针 | 来源形状 | 结果 |
|---|---|---|
| `crc32.sigil` | zlib/PNG 的 tableless CRC32 | ✅ 编译运行，`cbf43926` |
| `ringbuf.sigil` | UART/DMA 固定容量环形缓冲 | ✅ 编译运行，`sum=28 count=0`，overflow 两次 |
| `json_number.sigil` | cJSON 风格 JSON 数字转换 | ❌ 编译失败：`strtod` 未注册 |

## 失败点

### 1. `strtod` / `errno` / `isfinite` 不在 libc 子集

```text
error: json_number.sigil:10:20: Undeclared identifier 'strtod'
```

Sigil-C 的 `#include <stdlib.h>` 只登记了部分函数（`malloc/free/atoi/...`），`strtod` 没有登记。JSON 数字解析要么：

- 手写十进制/指数解析（可控，但重复造轮子）
- 或把 `strtod` 加进 libc 原型表（需要改编译器，且 `errno`/`isfinite` 也要跟上）

这是**真实外部项目移植会撞上的第一类问题**：libc 子集不等于完整 libc。

### 2. 字符串字面量类型摩擦

`p* c1 text m, "3.14159";` 会报 `Incompatible initializer type`，要写 `p* c@ c1`。
这是 C 的 `const char*` 语义，不是 bug；但对从 C 直接搬代码的人是额外步骤。

### 3. 没有动态数组 / 通用容器

三个探针都用固定数组绕过了；真实项目里的 `vector`/`hashmap`/`string builder` 需要自己写或引入第三方。Sigil-C 的定位是“C 的形状”，不是“自带容器库”。

## 成功的点

- `crc32`：位运算、`u4`、`p* c@ u1`、数组初始化都直接可用
- `ringbuf`：`mod`、全局数组、`v.` 空返回、`i?/e:` 都正常
- 两者生成的 C 都能用 `-Wall -Wextra -Werror -pedantic` 编译

## 结论

| 维度 | 结果 |
|---|---|
| 算法/位运算/固定数组 | 可直接写 |
| libc 覆盖 | 不够完整，`strtod` 这类会卡住 |
| 字符串/const | 需要适应 `p* c@ c1` |
| 容器/生态 | 没有，需自带 |
| 完整第三方项目 | **未完成**；需要选定具体仓库后逐个函数移植 |

下一轮如果要做“真项目”，建议选：

1. 单文件、无堆、无 libc 深依赖的 C 库（如 CRC/Base64/ringbuf）
2. 再选一个依赖 `strtod`/`errno` 的（如 JSON）
3. 最后选一个带容器/分配器的，专门暴露生态缺口

本轮不假装完成“3 个真实外部项目”；它只完成了 3 个外部风格的失败/成功探针。
