# Sigil-C libc 覆盖（封闭集合）

状态：**v1.9.1**
定位：**不是自建标准库，也不是“万能标准库”；是 C99 libc 的封闭原型覆盖。** `#include <...>` 决定登记哪些函数；生成的 C 直接调用 libc。

> **名单封闭。** 不在 v1.x 扩名单；要加名字，先过命名/版本预算，而不是“缺什么补什么”。

## 覆盖矩阵

| 头 | 已登记 |
|---|---|
| `<stdio.h>` | `printf` `fprintf` `sprintf` `snprintf` `sscanf` `scanf` `puts` `putchar` `fopen` `freopen` `fclose` `fread` `fwrite` `fgets` `fputs` `fgetc` `fputc` `feof` `fflush` `remove` `rename` `getchar` |
| `<stdlib.h>` | `malloc` `calloc` `free` `exit` `abort` `atoi` `atof` `strtod` `strtof` `strtol` `strtoul` `strtoll` `strtoull` `abs` `labs` `llabs` `qsort` `rand` `srand` `getenv` `system` |
| `<string.h>` | `memcpy` `memmove` `memset` `memcmp` `memchr` `strlen` `strcpy` `strncpy` `strcat` `strncat` `strcmp` `strncmp` `strchr` `strrchr` `strstr` `strspn` `strcspn` `strpbrk` `strtok` `strerror` |
| `<math.h>` | `sqrt` `fabs` `sin` `cos` `tan` `asin` `acos` `atan` `atan2` `sinh` `cosh` `tanh` `exp` `exp2` `log` `log2` `log10` `pow` `fmod` `hypot` `fmin` `fmax` `floor` `ceil` `round` `trunc` `isnan` `isfinite` `isinf` `signbit` |
| `<time.h>` | `time` `clock` `difftime` |
| `<ctype.h>` | `isalnum` `isalpha` `isdigit` `islower` `isspace` `isupper` `isxdigit` `tolower` `toupper` |
| `<errno.h>` | `errno` |
| `<assert.h>` | `assert` |

## 没有覆盖

- `<wchar.h>` / `<wctype.h>` / 宽字符
- `<complex.h>` / 复数
- `<locale.h>` / 本地化
- `<signal.h>` / 信号
- `<setjmp.h>` / 非局部跳转
- `<threads.h>` / 线程、原子
- `struct tm` 字段、`localtime`、`strftime`、`mktime`
- `<limits.h>` / `<float.h>` 的宏常量
- POSIX / Win32 API（需要按项目单独 `x!` 登记）
- 自己的容器/字符串/分配器库

## 使用

```sigil
#include <stdlib.h>
#include <string.h>
#include <math.h>

i4 main(v.) {
    o! p* c@ c1 text m, "3.5px";
    o! p* c1 end;
    o! f8 x m, strtod(text, p@ end);
    o! c1[16] buf m, {0};
    strcpy(p@ buf[0], "ab");
    strncat(p@ buf[0], "cdef", 2);
    r; (i4)(x * 10.0);
}
```

- 声明 `#include` 后，对应函数才会登记进符号表
- 生成 C 里仍然只有 `#include <...>` 和调用
- 没有包管理、没有模块、没有自动链接；链接仍由 C 工具链负责
- Linux 上数学函数需要 -lm（Windows 通常隐式链接）；gcc ... -lm 放在源文件之后

## 测试

第 54 层 `stdlib`：

- `strtod` 解析 `"3.5px"` → 35
- `strcpy` + `strncat` → `abcd`
- `atan2(0,-1)` + `round` → 3
- `time(NULL)` > 0
- `errno` 可读写

## 封闭策略

- 不在 v1.x 新增 libc 名字；缺口列在这里就是缺口。
- 不做 `std/` 容器/字符串/分配器库；没有模块/包管理，不硬造。
- 新名字必须有明确使用场景、测试和版本预算，不能因为“万能”而膨胀。
- 当前名单就是上限，不是起点。
