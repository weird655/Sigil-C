# 赛博纪念：Sigil-C

> 这里躺着一个编译器。它没有运行时，也没有用户。
> 它只留下 54 个双字符记号，和一条被证明过的规则：空格也是语法。

---

## 它相信的事

**线性表意。** 程序是一条从左到右的线：一个记号一个意思，一行一个动作，不回头找大括号，不猜编译器补了几个零。

**写操作带牌。** 所有状态修改都经 `m` 家族，副作用可以数出来。

**生成物可退出。** 转译成纯 C99，带 `--line` 也带 `--no-line`；哪天不用它了，留下的 C 还能编。

**不造生态。** 标准库用 C 的，工具链用 Python 的，运行时不存在。

## 它留下什么

| 物件 | 位置 |
|---|---|
| 54 个记号的闭集 | [`SYNTAX.md`](SYNTAX.md) |
| 20 个可运行示例 | [`TUTORIAL.md`](TUTORIAL.md) + [`examples/`](examples/) |
| 指针来源、悬空、逃逸、`r@` 违约的检查 | `sigilc_core/parser.py` |
| 199 项测试、40 层矩阵 | [`test_matrix.py`](test_matrix.py) |
| 一个 tag、一个 Release | `v1.1` |
| 一段被写下来的边界 | [`ARCHITECTURE.md`](ARCHITECTURE.md) |

## 墓志铭

```sigil
#include <stdio.h>

i4 main(v.) {
    printf("sigil-c 1.1\n");
    r; 0;
}
```

生成的 C：

```c
int32_t main(void) {
    printf("sigil-c 1.1\n");
    return 0;
}
```

它连告别都不需要 `#line`。

## 最后一条规则

> 这是一种深奥难懂的语言——它的语法和汇编一样简单。

维护模式：只修 bug，不增长。

2026-11-13
