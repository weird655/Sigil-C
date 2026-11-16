# 安装与单文件运行

## 1. pip / pipx

```bash
python3 -m pip install .
sigilc --version
sigilc --build src -o app --run
```

开发态：

```bash
python3 -m pip install -e .
```

`pyproject.toml` 注册了三个等价入口：`sigilc`、`sigil` 与 `sunberry-c`。

## 2. 单文件 zipapp（需要 Python）

```bash
python3 tools/build_standalone.py --zipapp
python3 dist/sigilc.pyz --version
```

产物是 `dist/sigilc.pyz`：单文件、无第三方依赖，但运行机需要 Python 3.8+。

## 3. 单文件原生二进制（可选，需要 PyInstaller）

```bash
python3 -m pip install pyinstaller
python3 tools/build_standalone.py --onefile
dist/sigilc.exe --version        # Windows
# 或 dist/sigilc --version       # Linux/macOS
```

PyInstaller 未安装时脚本会给出提示并退出，不会假装生成。

## 4. 直接运行源码（零安装）

```bash
python3 sigilc.py --version
python3 sigilc.py hello.sigil -o hello.c
```

## 5. 验证安装

```bash
printf 'i4 main(v.) { r; 0; }\n' > /tmp/hello.sigil
sigilc /tmp/hello.sigil -o /tmp/hello.c
cc -std=c99 /tmp/hello.c -o /tmp/hello
/tmp/hello
```

## 边界

- 安装包只含转译器与 `sigilc_core`，不含教程/示例/编辑器插件
- 生成的 C 是 C99 + `#line`；交付时不需要安装 Sigil-C
- Layer 2 `!` 是实验层，安装成功不代表它受 v1 兼容承诺保护
