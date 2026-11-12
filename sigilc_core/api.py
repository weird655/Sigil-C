"""Sigil-C api (generated split of sigilc.py)."""

import json
import os
import re
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

from .codegen import CodeGenerator
from .lexer import EXTERNAL_C_SPELLING, SIGIL_KEYWORDS, SIGIL_OPERATORS, Lexer, LexerError
from .nodes import EnumDefNode, ExternalTypeNode, FuncDefNode, ParseError, SemanticError, StructDefNode, VarDeclStmt
from .parser import Parser


def compile_source(src: str, filename: str = "input.sigil", prelude: Optional[str] = None,
                   bounds_check: bool = False, defines: Optional[Dict[str, str]] = None) -> str:
    EXTERNAL_C_SPELLING.clear()
    tokens = Lexer(src, filename).tokenize()
    ast = Parser(tokens, filename, defines).parse_program()
    return CodeGenerator(filename, prelude_include=prelude, bounds_check=bounds_check,
                         cli_defines=defines).generate(ast)

def check_source(src: str, filename: str = "input.sigil", defines: Optional[Dict[str, str]] = None) -> None:
    """词法 + 语法 + 静态语义检查，不产生任何输出。"""
    EXTERNAL_C_SPELLING.clear()
    tokens = Lexer(src, filename).tokenize()
    Parser(tokens, filename, defines).parse_program()

def _header_guard(header_name: str) -> str:
    base = os.path.basename(header_name).upper()
    return "SIGIL_" + "".join(ch if ch.isalnum() else "_" for ch in base)

def compile_header(src: str, filename: str = "input.sigil", header_name: str = "output.h",
                   prelude: Optional[str] = None, bounds_check: bool = False,
                   defines: Optional[Dict[str, str]] = None) -> str:
    """生成公共接口头文件：类型定义 + 非 static 函数原型 + 非 static 全局 extern。"""
    EXTERNAL_C_SPELLING.clear()
    tokens = Lexer(src, filename).tokenize()
    ast = Parser(tokens, filename, defines).parse_program()
    return CodeGenerator(filename, header_mode=True, prelude_include=prelude,
                         bounds_check=bounds_check, cli_defines=defines).generate_header(ast, _header_guard(header_name))

def _print_error(exc: Exception, fname: str, src: str) -> None:
    """打印错误，并在能定位时给出源码片段与插入符。"""
    msg = str(exc)
    print(f"error: {msg}", file=sys.stderr)
    m = re.match(rf"{re.escape(fname)}:(\d+):(\d+):", msg)
    if not m:
        return
    line_no, col = int(m.group(1)), int(m.group(2))
    lines = src.splitlines()
    if line_no < 1 or line_no > len(lines):
        return
    text = lines[line_no - 1]
    print(f"  --> {fname}:{line_no}:{col}", file=sys.stderr)
    print(f"  {line_no:>4} | {text}", file=sys.stderr)
    print(f"       | {' ' * max(0, col - 1)}^", file=sys.stderr)

_FMT_SIGILS = set(SIGIL_KEYWORDS) | set(SIGIL_OPERATORS)


def _split_code_comment(text: str) -> Tuple[str, str]:
    """把一行拆成 (代码, 注释)。跳过字符串/字符里的 // 和 /*。"""
    i = 0
    n = len(text)
    in_str = in_chr = False
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif in_chr:
            if c == "\\":
                i += 2
                continue
            if c == "'":
                in_chr = False
        else:
            if c == '"':
                in_str = True
            elif c == "'":
                in_chr = True
            elif c == "/" and i + 1 < n and text[i + 1] in "/*":
                return text[:i], text[i:]
        i += 1
    return text, ""


def _normalize_code(code: str) -> str:
    """按空格纪律重排一行代码；只做安全操作，不合并会形成印记的相邻字符。"""
    out: List[str] = []
    i = 0
    n = len(code)
    in_str = in_chr = False
    while i < n:
        c = code[i]
        if in_str or in_chr:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(code[i + 1])
                i += 2
                continue
            if in_str and c == '"':
                in_str = False
            elif in_chr and c == "'":
                in_chr = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "'":
            in_chr = True
            out.append(c)
            i += 1
            continue
        if c in " \t":
            j = i
            while j < n and code[j] in " \t":
                j += 1
            nxt = code[j] if j < n else ""
            if nxt:
                if nxt in ",;)]:":
                    prev_char = out[-1] if out else ""
                    if prev_char and (prev_char.isalnum() or prev_char == "_") and (prev_char + nxt) in _FMT_SIGILS:
                        if out[-1] != " ":
                            out.append(" ")
                elif out and out[-1] not in "([ ":
                    out.append(" ")
            i = j
            continue
        if c in ",;)]:":
            if out and out[-1] == " " and len(out) >= 2:
                prev_char = out[-2]
                if (prev_char.isalnum() or prev_char == "_") and (prev_char + c) in _FMT_SIGILS:
                    out.append(c)
                    i += 1
                    continue
                out.pop()
            out.append(c)
            i += 1
            if c in ",;:" and i < n and code[i] not in " \t)]}":
                out.append(" ")
            continue
        if c in "([":
            out.append(c)
            i += 1
            while i < n and code[i] in " \t":
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out).rstrip()


def format_source(src: str) -> str:
    """规范空格与注释列；保留行结构与缩进，不改语义。"""
    out_lines: List[str] = []
    in_preproc = False
    in_block = False
    for raw in src.splitlines():
        if not raw.strip():
            out_lines.append("")
            in_preproc = False
            continue
        stripped = raw.lstrip(" \t")
        indent = raw[: len(raw) - len(stripped)]
        if in_block:
            out_lines.append(raw.rstrip())
            if "*/" in stripped:
                in_block = False
            continue
        if in_preproc or stripped.startswith("#"):
            out_lines.append(raw.rstrip())
            in_preproc = stripped.endswith("\\")
            continue
        code, comment = _split_code_comment(stripped)
        if not code.strip():
            out_lines.append(raw.rstrip())
            if comment.startswith("/*") and "*/" not in comment:
                in_block = True
            continue
        if comment.startswith("/*") and "*/" not in comment:
            in_block = True
        body = _normalize_code(code)
        line = indent + body
        if comment:
            line = line + "  " + comment if body else indent + comment
        out_lines.append(line.rstrip())
    text = "\n".join(out_lines)
    return text + ("\n" if src.endswith("\n") else "")


_INIT_MAIN = """#include <stdio.h>

/* 由 `sigilc.py --init` 生成 */

i4 main(v.) {
    printf("hello, sigil\\n");
    r; 0;
}
"""

_INIT_README = """# {name}

用 Sigil-C 写的小项目。

```bash
python3 sigilc.py --build src -o app --run
```
"""


_LSP_TYPES = ["i1", "i2", "i4", "i8", "u1", "u2", "u4", "u8", "f4", "f8",
              "c1", "b.", "v.", "size_t", "ptrdiff_t", "va_list", "offsetof"]


def _lsp_read(stream):
    headers = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        key, _, value = line.decode("ascii", "replace").partition(":")
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    body = stream.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _lsp_write(stream, payload) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    stream.write(b"Content-Length: %d\r\n\r\n" % len(data))
    stream.write(data)
    stream.flush()


def _lsp_uri_path(uri: str) -> str:
    if uri.startswith("file://"):
        return uri[7:]
    return "buffer.sigil"


def _lsp_diagnostics(uri: str, text: str):
    try:
        check_source(text, _lsp_uri_path(uri))
        return []
    except (LexerError, ParseError, SemanticError) as e:
        msg = str(e)
        m = re.match(r"^(.*?):(\d+):(\d+):\s*(.*)$", msg)
        if m:
            line = max(0, int(m.group(2)) - 1)
            col = max(0, int(m.group(3)) - 1)
            message = m.group(4)
        else:
            line, col, message = 0, 0, msg
        return [{
            "range": {
                "start": {"line": line, "character": col},
                "end": {"line": line, "character": col + 1},
            },
            "severity": 1,
            "source": "sigil-c",
            "message": message,
        }]


_LSP_SNIPPETS = {
    "i?": ("i? (${1:cond}) {\n\t$0\n}", "if"),
    "e:": ("e: {\n\t$0\n}", "else"),
    "w~": ("w~ (${1:cond}) {\n\t$0\n}", "while"),
    "f~": ("f~ (${1:init}; ${2:cond}; ${3:step}) {\n\t$0\n}", "for"),
    "d~": ("d~ {\n\t$0\n} w~ (${1:cond});", "do-while"),
    "s?": ("s? (${1:value}) {\n\tk: ${2:0}: {\n\t\t$0\n\t}\n}", "switch"),
    "o!": ("o! ${1:i4} ${2:name};", "object"),
    "m,": ("m, ${1:value};", "assign"),
    "m+": ("m+ ${1:value};", "add-assign"),
    "m-": ("m- ${1:value};", "sub-assign"),
    "p*": ("p* ${1:u4}", "pointer"),
    "r;": ("r; ${1:value};", "return"),
    "a?": ("a? ${1:u4}", "alignof"),
    "t!": ("t! (${1:cond}, \"${2:message}\");", "static assert"),
    "d!": ("d!;", "trap"),
    "s{": ("s{ ${1:Name} {\n\t$0\n};", "struct"),
    "u{": ("u{ ${1:Name} {\n\t$0\n};", "union"),
    "e{": ("e{ ${1:Name} {\n\t${2:A} m, 0,\n};", "enum"),
    "x!": ("x! struct ${1:Name} {\n\t$0\n};", "external type"),
    "g!": ("g! ${1:label};", "goto"),
    "l!": ("l! ${1:label};", "label"),
    "w!": (" w! ${1:1};", "bitfield"),
    "f^": ("f^(${1:i4}) -> ${2:v.}", "function pointer"),
}


def _lsp_capabilities(completion_enabled: bool):
    caps: Dict[str, object] = {"textDocumentSync": 1, "documentSymbolProvider": True}
    if completion_enabled:
        caps["completionProvider"] = {"triggerCharacters": [" "]}
    return caps


def _lsp_completion_items(prefix: str = ""):
    """结构片段补全：补的是印记后面的形状，不是单个单词。"""
    items: List[Dict[str, object]] = []
    for label in sorted(_LSP_SNIPPETS):
        insert, detail = _LSP_SNIPPETS[label]
        items.append({"label": label, "kind": 14, "detail": detail,
                      "insertText": insert, "insertTextFormat": 2})
    for name in _LSP_TYPES:
        items.append({"label": name, "kind": 25, "detail": "type"})
    for name in ("true", "false", "NULL"):
        items.append({"label": name, "kind": 12, "detail": "literal"})
    if prefix:
        items = [item for item in items if str(item["label"]).startswith(prefix)]
    return items


def _lsp_word_prefix(text: str, line: int, character: int) -> str:
    lines = text.splitlines()
    if line < 0 or line >= len(lines):
        return ""
    prefix = lines[line][:max(0, character)]
    m = re.search(r"[A-Za-z0-9_]+$", prefix)
    return m.group(0) if m else ""


def _lsp_document_symbols(text: str):
    try:
        tokens = Lexer(text, "buffer.sigil").tokenize()
        ast = Parser(tokens, "buffer.sigil").parse_program()
    except (LexerError, ParseError, SemanticError):
        return []

    def make(node, name: str, kind: int, children=None):
        line = max(0, getattr(node, "line", 1) - 1)
        col = max(0, getattr(node, "col", 1) - 1)
        span = {"start": {"line": line, "character": col},
                "end": {"line": line, "character": col + max(1, len(name))}}
        symbol = {"name": name, "kind": kind, "range": span, "selectionRange": span}
        if children:
            symbol["children"] = children
        return symbol

    out = []
    for node in ast:
        if isinstance(node, FuncDefNode):
            out.append(make(node, node.name, 12))
        elif isinstance(node, StructDefNode):
            out.append(make(node, node.name, 23))
        elif isinstance(node, EnumDefNode):
            kids = [make(node, item[0], 22) for item in node.items]
            out.append(make(node, node.name, 10, kids))
        elif isinstance(node, VarDeclStmt):
            out.append(make(node, node.name, 13))
        elif isinstance(node, ExternalTypeNode):
            out.append(make(node, node.name, 23))
    return out


def _lsp_run(completion_enabled: bool = False) -> int:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    docs = {}
    while True:
        msg = _lsp_read(stdin)
        if msg is None:
            return 0
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            _lsp_write(stdout, {
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"capabilities": _lsp_capabilities(completion_enabled)},
            })
        elif method == "initialized":
            pass
        elif method == "textDocument/didOpen":
            doc = params["textDocument"]
            docs[doc["uri"]] = doc["text"]
            _lsp_write(stdout, {
                "jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                "params": {"uri": doc["uri"], "diagnostics": _lsp_diagnostics(doc["uri"], doc["text"])},
            })
        elif method == "textDocument/didChange":
            uri = params["textDocument"]["uri"]
            text = params["contentChanges"][-1]["text"]
            docs[uri] = text
            _lsp_write(stdout, {
                "jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                "params": {"uri": uri, "diagnostics": _lsp_diagnostics(uri, text)},
            })
        elif method == "textDocument/didClose":
            uri = params["textDocument"]["uri"]
            docs.pop(uri, None)
            _lsp_write(stdout, {
                "jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                "params": {"uri": uri, "diagnostics": []},
            })
        elif method == "textDocument/completion":
            if not completion_enabled:
                _lsp_write(stdout, {
                    "jsonrpc": "2.0", "id": msg_id,
                    "result": {"isIncomplete": False, "items": []},
                })
            else:
                uri = params["textDocument"]["uri"]
                pos = params.get("position") or {}
                prefix = _lsp_word_prefix(docs.get(uri, ""), pos.get("line", 0), pos.get("character", 0))
                _lsp_write(stdout, {
                    "jsonrpc": "2.0", "id": msg_id,
                    "result": {"isIncomplete": False, "items": _lsp_completion_items(prefix)},
                })
        elif method == "textDocument/documentSymbol":
            uri = params["textDocument"]["uri"]
            _lsp_write(stdout, {
                "jsonrpc": "2.0", "id": msg_id,
                "result": _lsp_document_symbols(docs.get(uri, "")),
            })
        elif method == "shutdown":
            _lsp_write(stdout, {"jsonrpc": "2.0", "id": msg_id, "result": None})
        elif method == "exit":
            return 0
        elif msg_id is not None:
            _lsp_write(stdout, {
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            })


def _init_project(target: str, force: bool) -> int:
    """生成一个最小可运行工程：src/main.sigil + README + .gitignore。"""
    files = {
        os.path.join(target, "src", "main.sigil"): _INIT_MAIN,
        os.path.join(target, "README.md"): _INIT_README.format(name=os.path.basename(os.path.abspath(target))),
        os.path.join(target, ".gitignore"): ".sigil-build/\n",
    }
    if not force:
        existing = [path for path in files if os.path.exists(path)]
        if existing:
            print("error: files already exist (use --force to overwrite): " + ", ".join(existing), file=sys.stderr)
            return 1
    for path, content in files.items():
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        print(f"Created  {path}")
    print(f"Next     python3 sigilc.py --build {os.path.join(target, 'src')} -o app --run")
    return 0


def _check_targets(target: str, defines: Dict[str, str], json_out: bool = False) -> int:
    """对单个文件或目录下所有 .sigil 做词法/语法/语义检查，不写文件。"""
    if os.path.isdir(target):
        files = _collect_sources(target)
    elif os.path.isfile(target):
        files = [target]
    else:
        print(f"error: '{target}' is not a file or directory", file=sys.stderr)
        return 1
    if not files:
        print(f"error: no .sigil files under '{target}'", file=sys.stderr)
        return 1

    failures = []
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        rel = os.path.relpath(path)
        try:
            check_source(src, rel, defines=defines)
        except (LexerError, ParseError, SemanticError) as e:
            failures.append((rel, src, e))

    if json_out:
        diagnostics = []
        for rel, _src, exc in failures:
            msg = str(exc)
            m = re.match(r"^(.*?):(\d+):(\d+):\s*(.*)$", msg)
            if m:
                diagnostics.append({
                    "file": os.path.abspath(m.group(1)) if os.path.exists(m.group(1)) else m.group(1),
                    "line": int(m.group(2)),
                    "column": int(m.group(3)),
                    "severity": "error",
                    "message": m.group(4),
                })
            else:
                diagnostics.append({"file": os.path.abspath(path), "line": 0, "column": 0,
                                    "severity": "error", "message": msg})
        print(json.dumps({"ok": not failures, "checked": len(files),
                          "diagnostics": diagnostics}, ensure_ascii=False))
        return 1 if failures else 0

    for rel, src, exc in failures:
        _print_error(exc, rel, src)
    if failures:
        print(f"{len(failures)}/{len(files)} file(s) failed", file=sys.stderr)
        return 1
    print(f"Checked {len(files)} file(s): OK")
    return 0


def _format_targets(target: str, write: bool, check_only: bool) -> int:
    if os.path.isdir(target):
        files = _collect_sources(target)
    elif os.path.isfile(target):
        files = [target]
    else:
        print(f"error: '{target}' is not a file or directory", file=sys.stderr)
        return 1
    if not files:
        print(f"error: no .sigil files under '{target}'", file=sys.stderr)
        return 1
    if not write and not check_only and len(files) > 1:
        print("error: formatting to stdout needs a single file; add --write for directories", file=sys.stderr)
        return 1

    changed = 0
    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        fmt = format_source(src)
        if fmt == src:
            continue
        changed += 1
        if check_only:
            print(f"needs format: {path}")
        elif write:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(fmt)
            print(f"Formatted {path}")
        else:
            sys.stdout.write(fmt)
    if check_only:
        return 1 if changed else 0
    return 0


def _parse_defines(items: List[str]) -> Optional[Dict[str, str]]:
    defines: Dict[str, str] = {}
    for item in items:
        if "=" not in item:
            print(f"error: --define expects NAME=VALUE, got '{item}'", file=sys.stderr)
            return None
        d_name, d_value = item.split("=", 1)
        defines[d_name.strip()] = d_value.strip()
    return defines


def _collect_sources(root: str) -> List[str]:
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in ('.git', '.sigil-build'))
        for name in sorted(filenames):
            if name.endswith(".sigil"):
                found.append(os.path.join(dirpath, name))
    return found


def _build_project(args, defines: Dict[str, str]) -> int:
    """把目录下所有 .sigil 转译到 .sigil-build/，再用 gcc 链接成一个可执行文件。"""
    root = args.build
    sources = _collect_sources(root)
    if not sources:
        print(f"error: no .sigil files under '{root}'", file=sys.stderr)
        return 1

    out_dir = os.path.join(root, ".sigil-build")
    c_paths: List[str] = []
    for src_path in sources:
        rel = os.path.relpath(src_path, root)
        c_path = os.path.join(out_dir, os.path.splitext(rel)[0] + ".c")
        os.makedirs(os.path.dirname(c_path) or out_dir, exist_ok=True)
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()
        try:
            c_src = compile_source(src, rel, prelude=args.prelude,
                                   bounds_check=args.bounds_check, defines=defines)
        except (LexerError, ParseError, SemanticError) as e:
            _print_error(e, rel, src)
            return 1
        with open(c_path, "w", encoding="utf-8") as f:
            f.write(c_src)
        print(f"Transpile {src_path} -> {c_path}")
        c_paths.append(c_path)
        if args.emit_header:
            h_path = os.path.splitext(c_path)[0] + ".h"
            try:
                h_src = compile_header(src, rel, os.path.basename(h_path), prelude=args.prelude,
                                       bounds_check=args.bounds_check, defines=defines)
            except (LexerError, ParseError, SemanticError) as e:
                _print_error(e, rel, src)
                return 1
            with open(h_path, "w", encoding="utf-8") as f:
                f.write(h_src)
            print(f"Header    {h_path}")

    exe = args.output_opt or args.output or "a.out"
    if os.name == "nt" and not exe.lower().endswith(".exe"):
        exe += ".exe"
    cmd = [args.cc] + args.cflags.split() + c_paths + ["-o", exe]
    print("Link      " + " ".join(cmd))
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        return rc
    print(f"Built     {exe}")
    if args.run:
        sys.stdout.flush()
        return subprocess.run([os.path.abspath(exe)]).returncode
    return 0


