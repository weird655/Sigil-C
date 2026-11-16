# 栈过载演示（stack_overload）

两个版本，**都不用堆**，都不是 Sigil-C 的语言特性。

## 模拟栈：`simulated.sigil`

静态 `u4[128]` arena 自己管帧、栈顶和 canary：

- push 三个 4-word 帧
- 快照 arena
- 对 frame 1 越界写 6 words
- 扫描 canary 和字节差异，打印侵入了哪些帧/哪些 word

```bash
python3 sigilc.py examples/stack_overload/simulated.sigil -o sim.c
cc -std=c99 -Wall -Wextra -Werror -pedantic sim.c -o sim
./sim
```

输出：

```text
before: 3 frames, 4 words each
overload frame 1 by 6 words...
live frames: 3
  frame 1 canary INVADED at word 9
  frame 2 canary INVADED at word 14
  word 9: 0xdeadbeef -> 0x41414141
  ...
invaded words: 6
```

这是**定义行为**，可重复；它演示“如果栈可观测，溢出长什么样”。

## 真栈：`real.sigil`

本地 `volatile u4[4]` 数组，循环写 8 个 word；越界写是 UB，靠
AddressSanitizer 抓现场。

```bash
# Linux / macOS，先确保 cc 支持 -fsanitize=address
python3 sigilc.py examples/stack_overload/real.sigil -o real.c --no-bounds-check
cc -std=c99 -O0 -g -fsanitize=address -fno-omit-frame-pointer real.c -o real
./real
```

`run.sh` 封装了这两步；Windows 的 MinGW 通常没有 `libasan`，请在 WSL 或
Linux 上跑。ASan 会打印 `stack-buffer-overflow`、函数名和越界偏移。

## 边界

- 模拟版是安全的、可进 CI；真栈版是 UB 演示，不进 CI
- 真栈版必须 `--no-bounds-check`；默认边界检查会先 abort
- 真栈布局依编译器/ABI/优化等级；canary、ASLR、栈保护都会改变结果
- 没有堆分配：模拟版用静态 arena，真栈版用本地数组
- 不要把这个当成“可控侵入”；它只是演示和诊断
