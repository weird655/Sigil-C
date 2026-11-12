"""Sigil-C cli (generated split of sigilc.py)."""

import argparse
import os
import sys
from typing import List, Optional

from .api import (
    _build_project,
    _check_targets,
    _format_targets,
    _init_project,
    _lsp_run,
    _parse_defines,
    _print_error,
    compile_header,
    compile_source,
)
from .lexer import LexerError
from .nodes import ParseError, SemanticError
from .parser import C99_PRELUDE


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="sigilc.py",
        description="Sigil-C v1.1 - transpile .sigil sources to ISO C99",
    )
    ap.add_argument("input", nargs="?", help="input .sigil source file")
    ap.add_argument("output", nargs="?", help="output .c path (default: <input>.c)")
    ap.add_argument("-o", "--output", dest="output_opt", metavar="PATH", help="output path")
    ap.add_argument("--emit-header", action="store_true",
                    help="also emit a C header next to the output (same basename, .h)")
    ap.add_argument("--header", metavar="PATH", help="explicit header output path (implies --emit-header)")
    ap.add_argument("--check", action="store_true", help="parse and type-check only; write nothing")
    ap.add_argument("--emit-prelude", metavar="PATH",
                    help="write the shared Sigil-C C prelude (macros) to PATH")
    ap.add_argument("--prelude", metavar="NAME",
                    help="include NAME instead of inlining the prelude macro block in generated files")
    ap.add_argument("--bounds-check", action="store_true",
                    help="emit #define SIGIL_BOUNDS_CHECK 1 so array subscripts are bounds-checked at run time")
    ap.add_argument("--define", metavar="NAME=VALUE", action="append", default=[],
                    help="predefine a macro constant (repeatable), like #define NAME VALUE")
    ap.add_argument("--lsp", action="store_true", help="run a minimal LSP server on stdio")
    ap.add_argument("--lsp-completion", action="store_true",
                    help="with --lsp: enable snippet completion (off by default)")
    ap.add_argument("--init", metavar="DIR", nargs="?", const=".", default=None,
                    help="scaffold a minimal project in DIR")
    ap.add_argument("--force", action="store_true", help="with --init: overwrite existing files")
    ap.add_argument("--json", action="store_true", help="with --check: emit JSON diagnostics")
    ap.add_argument("--fmt", metavar="PATH", nargs="?", const=".", default=None,
                    help="format a .sigil file (stdout) or every .sigil under PATH with --write")
    ap.add_argument("--write", action="store_true", help="with --fmt: rewrite files in place")
    ap.add_argument("--fmt-check", action="store_true",
                    help="with --fmt: only report files that need formatting (exit 1 if any)")
    ap.add_argument("--build", metavar="DIR", nargs="?", const=".", default=None,
                    help="transpile every .sigil under DIR and link them into one executable")
    ap.add_argument("--run", action="store_true", help="with --build: run the executable afterwards")
    ap.add_argument("--cc", default="gcc", help="C compiler used by --build (default: gcc)")
    ap.add_argument("--cflags", default="-std=c99 -Wall -Wextra -Werror -pedantic",
                    help="compiler flags used by --build")
    ap.add_argument("--no-line", action="store_true",
                    help="omit #line directives so the generated C reads like ordinary C")

    ap.add_argument("--version", action="version", version="Sigil-C 1.1")
    args = ap.parse_args(argv)

    defines = _parse_defines(args.define)
    if defines is None:
        return 2

    if args.lsp:
        return _lsp_run(args.lsp_completion)

    if args.init is not None:
        return _init_project(args.init, args.force)

    if args.build is not None:
        if args.header:
            print("error: --header is not supported with --build; use --emit-header", file=sys.stderr)
            return 2
        return _build_project(args, defines)

    if args.fmt is not None:
        return _format_targets(args.fmt, args.write, args.fmt_check)

    if not args.input:
        ap.error("input is required unless --build DIR is given")

    if args.check:
        return _check_targets(args.input, defines, json_out=args.json)

    in_path = args.input
    out_path = args.output_opt or args.output or (os.path.splitext(in_path)[0] + ".c")
    with open(in_path, "r", encoding="utf-8") as f:
        src = f.read()
    fname = os.path.basename(in_path)

    if args.emit_prelude:
        with open(args.emit_prelude, "w", encoding="utf-8") as f:
            f.write(C99_PRELUDE)
        print(f"Prelude  {args.emit_prelude}")

    try:
        c_src = compile_source(src, fname, prelude=args.prelude, bounds_check=args.bounds_check,
                               defines=defines, line_directives=not args.no_line)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(c_src)
        print(f"Compiled {in_path} -> {out_path}")

        header_path = args.header or (os.path.splitext(out_path)[0] + ".h" if args.emit_header else None)
        if header_path:
            h_src = compile_header(src, fname, os.path.basename(header_path), prelude=args.prelude,
                                   bounds_check=args.bounds_check, defines=defines)
            with open(header_path, "w", encoding="utf-8") as f:
                f.write(h_src)
            print(f"Header   {header_path}")
    except (LexerError, ParseError, SemanticError) as e:
        _print_error(e, fname, src)
        return 1
    return 0


def cli() -> None:
    try:
        sys.exit(main())
    except (LexerError, ParseError, SemanticError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    cli()
