# Experiments

Not part of the compiler, not in CI, not maintained. Kept as evidence.

## `toy_asm.py` — Sigil-C straight to x86-64 assembly

A farewell experiment: it takes the real `.sigil` AST and lowers it to GNU as
(SysV on Linux, Microsoft x64 on Windows), with no C in between.

Supported, deliberately tiny:

- `i4` functions with up to 4 `i4` parameters
- body: exactly one `r; <expr>;`
- integer literals, parameters, `+ - *`, calls to functions in the file

Everything else raises `unsupported`.

```bash
python experiments/toy_asm.py experiments/demo.sigil -o demo.s
gcc demo.s -o demo
./demo
echo $?
```

Exit code: `42`.

What a real backend would still need: all statements and types, struct layout,
varargs, floating point, the full ABI on every platform, relocations/object
formats, and an optimizer. That is why the shipped compiler emits C99 and lets
gcc/clang do the rest.
