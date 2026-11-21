"""Sigil-C api (generated split of sigilc.py)."""

import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

from .codegen import CodeGenerator
from .lexer import EXTERNAL_C_SPELLING, SIGIL_KEYWORDS, SIGIL_OPERATORS, Lexer, LexerError
from .netlist import merge_project_graphs, render_graph, render_graph_data, render_netlist
from .nodes import (
    EnumDefNode,
    ExternalTypeNode,
    FuncDefNode,
    MultiError,
    ParseError,
    SemanticError,
    StructDefNode,
    VarDeclStmt,
)
from .parser import Parser


def compile_source(src: str, filename: str = "input.sigil", prelude: Optional[str] = None,
                   bounds_check: bool = False, defines: Optional[Dict[str, str]] = None,
                   line_directives: bool = True, strict: bool = False,
                   trap_trace: bool = False, shadow_stack: bool = False, namespace: str = "",
                   effects: Optional[Dict[str, Any]] = None, checked: bool = False,
                   checked_strict: bool = False, checked_external: bool = False,
                   allow_external: Optional[Set[str]] = None,
                   known_functions: Optional[Set[str]] = None,
                   line_offset: int = 0) -> str:
    if trap_trace and shadow_stack:
        raise ValueError("trap_trace and shadow_stack are separate modes; pick one")
    EXTERNAL_C_SPELLING.clear()
    tokens = Lexer(src, filename, line_offset=line_offset).tokenize()
    ast = Parser(tokens, filename, defines, strict_provenance=strict, effects=effects,
                checked=checked or checked_strict or checked_external,
                checked_external=checked_external, allow_external=allow_external,
                known_functions=known_functions).parse_program()
    return CodeGenerator(filename, prelude_include=prelude, bounds_check=bounds_check,
                         cli_defines=defines, line_directives=line_directives,
                         trap_trace=trap_trace, shadow_stack=shadow_stack,
                         namespace=namespace, checked_arith=checked or checked_external,
                         checked_strict=checked_strict).generate(ast)

def check_source(src: str, filename: str = "input.sigil", defines: Optional[Dict[str, str]] = None,
                 strict: bool = False) -> None:
    """词法 + 语法 + 静态语义检查，不产生任何输出。"""
    EXTERNAL_C_SPELLING.clear()
    tokens = Lexer(src, filename).tokenize()
    Parser(tokens, filename, defines, strict_provenance=strict).parse_program()

def netlist_source(src: str, filename: str = "input.sigil",
                   defines: Optional[Dict[str, str]] = None, strict: bool = False, namespace: str = "",
                   format: str = "text") -> str:
    """解析并返回飞线网表，不生成 C。"""
    EXTERNAL_C_SPELLING.clear()
    tokens = Lexer(src, filename).tokenize()
    parser = Parser(tokens, filename, defines, strict_provenance=strict)
    parser.parse_program()
    return render_netlist(parser) if format == "text" else render_graph(parser, format)

def project_netlist_source(root: str, defines: Optional[Dict[str, str]] = None,
                           strict: bool = False, format: str = "json") -> str:
    """Merge every .sigil under root into one project graph."""
    sources = _collect_sources(root)
    if not sources:
        raise ValueError(f"no .sigil files under '{root}'")
    items = []
    for src_path in sources:
        rel = os.path.relpath(src_path, root)
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()
        # The single-file parser does not know !math[n]!; replace external
        # calls with 0 for structural parsing. The original src still feeds
        # the uses edges and file labels.
        parse_src = re.sub(r"!([a-z][a-z0-9_]*)\[(\d+)\]!\s*\([^()]*\)", "0", src)
        parse_src = re.sub(r"!([a-z][a-z0-9_]*)\[(\d+)\]!", "0", parse_src)
        parse_src = re.sub(r"!/\s*(\d+)\s*/!\s*\([^()]*\)", "0", parse_src)
        items.append((rel, src, json.loads(netlist_source(
            parse_src, rel, defines, strict, format="json"))))
    if format == "text":
        parts = [f"# project: {os.path.abspath(root)}"]
        for rel, src, _ in items:
            parts.append(f"\n# file: {rel}\n{netlist_source(src, rel, defines, strict, format='text')}")
        return "\n".join(parts)
    plants, plant_error = _project_plant_scan(root, sources)
    if plant_error:
        raise ValueError(plant_error)
    graph = merge_project_graphs(root, items)
    _attach_plant_nodes(graph, root, plants)
    return render_graph_data(graph, format)


def _attach_plant_nodes(graph, root: str, plants) -> None:
    objects = {o["id"]: o for o in graph["objects"]}
    edges = graph["morphisms"]
    seen = {(e["source"], e["target"], e["kind"]) for e in edges}
    for plant_dir, info in sorted(plants.items()):
        rel = os.path.relpath(plant_dir, root).replace("\\", "/")
        pid = f"plant:{rel}"
        if pid not in objects:
            objects[pid] = {"id": pid, "label": f"!<+{info['category']}+>! {'on' if info['on'] else 'off'}",
                            "kind": "plant"}
            graph["objects"].append(objects[pid])
        for box in info["boxes"]:
            ns = box[1:-1]
            nid = f"ns:{ns}"
            if nid in objects:
                key = (pid, nid, "powers")
                if key not in seen:
                    seen.add(key)
                    edges.append({"source": pid, "target": nid, "kind": "powers",
                                  "label": f"plant {'on' if info['on'] else 'off'}"})
        prefix = f"file:{rel}"
        for oid in list(objects):
            if oid.startswith(prefix) and oid != pid:
                key = (oid, pid, "in-plant")
                if key not in seen:
                    seen.add(key)
                    edges.append({"source": oid, "target": pid, "kind": "in-plant", "label": "in plant"})
    graph["category"]["objects"] = len(graph["objects"])
    graph["category"]["morphisms"] = len(edges)


def _header_guard(header_name: str) -> str:
    base = os.path.basename(header_name).upper()
    return "SIGIL_" + "".join(ch if ch.isalnum() else "_" for ch in base)

def compile_header(src: str, filename: str = "input.sigil", header_name: str = "output.h",
                   prelude: Optional[str] = None, bounds_check: bool = False,
                   defines: Optional[Dict[str, str]] = None, strict: bool = False, namespace: str = "") -> str:
    """生成公共接口头文件：类型定义 + 非 static 函数原型 + 非 static 全局 extern。"""
    EXTERNAL_C_SPELLING.clear()
    tokens = Lexer(src, filename).tokenize()
    ast = Parser(tokens, filename, defines, strict_provenance=strict).parse_program()
    return CodeGenerator(filename, header_mode=True, prelude_include=prelude,
                         bounds_check=bounds_check, cli_defines=defines,
                         namespace=namespace).generate_header(ast, _header_guard(header_name))

def _print_error_at(msg: str, fname: str, src: str, line_no: int, col: int) -> None:
    print(f"error: {msg}", file=sys.stderr)
    lines = src.splitlines()
    if line_no < 1 or line_no > len(lines):
        return
    text = lines[line_no - 1]
    print(f"  --> {fname}:{line_no}:{col}", file=sys.stderr)
    print(f"  {line_no:>4} | {text}", file=sys.stderr)
    print(f"       | {' ' * max(0, col - 1)}^", file=sys.stderr)


def _print_error(exc: Exception, fname: str, src: str) -> None:
    """打印错误，并在能定位时给出源码片段与插入符。"""
    if isinstance(exc, MultiError):
        for line, col, msg in exc.items:
            _print_error_at(msg, fname, src, line, col)
        return
    msg = str(exc)
    m = re.match(rf"{re.escape(fname)}:(\d+):(\d+):", msg)
    if not m:
        print(f"error: {msg}", file=sys.stderr)
        return
    _print_error_at(msg, fname, src, int(m.group(1)), int(m.group(2)))

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


def _lsp_warnings(text: str):
    """Cheap, conservative warnings: locals declared but never used."""
    warnings = []
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if "o!" in stripped or "s@" in stripped:
            m = re.search(r"([A-Za-z_]\w*)\s*(?:m,|;|=|\[)", stripped)
            if not m:
                continue
            name = m.group(1)
            if name.startswith("__") or len(re.findall(r"\b" + re.escape(name) + r"\b", text)) > 1:
                continue
            warnings.append({
                "range": {
                    "start": {"line": idx, "character": max(0, line.find(name))},
                    "end": {"line": idx, "character": max(0, line.find(name)) + len(name)},
                },
                "severity": 2,
                "source": "sigil-c",
                "message": f"unused local '{name}'",
            })
        if "f~" in stripped and "(" in stripped:
            m = re.search(r"\(\s*(?:[A-Za-z_]\w*\s+)+([A-Za-z_]\w*)\s+m,", stripped)
            if m:
                name = m.group(1)
                if len(re.findall(r"\b" + re.escape(name) + r"\b", text)) == 1:
                    col = max(0, line.find(name))
                    warnings.append({
                        "range": {"start": {"line": idx, "character": col},
                                  "end": {"line": idx, "character": col + len(name)}},
                        "severity": 2, "source": "sigil-c",
                        "message": f"unused loop variable '{name}'",
                    })
    return warnings


def _lsp_diagnostics(uri: str, text: str):
    def one(msg: str, line: int, col: int):
        m = re.match(r"^(.*?):(\d+):(\d+):\s*(.*)$", msg)
        if m:
            line = int(m.group(2))
            col = int(m.group(3))
            msg = m.group(4)
        return {
            "range": {
                "start": {"line": max(0, line - 1), "character": max(0, col - 1)},
                "end": {"line": max(0, line - 1), "character": max(0, col)},
            },
            "severity": 1,
            "source": "sigil-c",
            "message": msg,
        }

    try:
        check_source(text, _lsp_uri_path(uri))
        return _lsp_warnings(text)
    except MultiError as e:
        return [one(msg, line, col) for line, col, msg in e.items]
    except (LexerError, ParseError, SemanticError) as e:
        msg = str(e)
        m = re.match(r"^(.*?):(\d+):(\d+):\s*(.*)$", msg)
        line, col = (int(m.group(2)), int(m.group(3))) if m else (1, 1)
        return [one(msg, line, col)]


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


def _check_targets(target: str, defines: Dict[str, str], json_out: bool = False,
                   strict: bool = False) -> int:
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
        with open(path, "r", encoding="utf-8") as handle:
            src = handle.read()
        rel = os.path.relpath(path)
        try:
            check_source(src, rel, defines=defines, strict=strict)
        except (LexerError, ParseError, SemanticError) as e:
            failures.append((rel, src, e))

    if json_out:
        diagnostics = []
        for rel, _src, exc in failures:
            if isinstance(exc, MultiError):
                for line, col, msg in exc.items:
                    m = re.match(r"^(.*?):(\d+):(\d+):\s*(.*)$", msg)
                    fpath = m.group(1) if m else rel
                    diagnostics.append({
                        "file": os.path.abspath(fpath) if os.path.exists(fpath) else fpath,
                        "line": line, "column": col,
                        "severity": "error",
                        "message": m.group(4) if m else msg,
                    })
                continue
            msg = str(exc)
            m = re.match(r"^(.*?):(\d+):(\d+):\s*(.*)$", msg)
            if m:
                fpath = m.group(1)
                diagnostics.append({
                    "file": os.path.abspath(fpath) if os.path.exists(fpath) else fpath,
                    "line": int(m.group(2)),
                    "column": int(m.group(3)),
                    "severity": "error",
                    "message": m.group(4),
                })
            else:
                diagnostics.append({"file": os.path.abspath(rel), "line": 0, "column": 0,
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
        with open(path, "r", encoding="utf-8") as handle:
            src = handle.read()
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


_PROJECT_PROTO_RE = re.compile(
    r"^\s*((?:(?:p\*|p@|c@|v@)\s*)*[A-Za-z_][\w.]*)"
    r"\s+([A-Za-z_]\w*)\s*\(([^()]*)\)\s*\{",
    re.M,
)


def _project_prototypes(src: str, ns: str = "", mangle: bool = True) -> List[str]:
    """Extract top-level function signatures from one .sigil source.

    Cross-file MVP: functions only, one-line signatures. Static (s@) and main
    are not exported.
    """
    out: List[str] = []
    seen = set()
    for m in _PROJECT_PROTO_RE.finditer(src):
        ret, name, params = m.group(1).strip(), m.group(2), m.group(3).strip()
        if name == "main" or "s@" in ret or name in seen:
            continue
        seen.add(name)
        out_name = f"{ns}_{name}" if mangle and ns and name != "main" else name
        out.append(f"{ret} {out_name}({params});")
    return out


_PROJECT_PKG_DECL_RE = re.compile(r"^\s*!(\d+)!!?", re.M)


def _project_dir_namespaces(rel: str) -> List[str]:
    """Directory-level namespaces: `!math!/core.sigil` -> ['math']."""
    parts = rel.replace("\\", "/").split("/")[:-1]
    out: List[str] = []
    for part in parts:
        m = re.fullmatch(r"!([^!]+)!", part)
        if m:
            out.append(m.group(1))
    return out


def _project_namespace(rel: str) -> str:
    """Primary namespace: nearest `!name!` directory, else file prefix fallback."""
    dirs = _project_dir_namespaces(rel)
    if dirs:
        return dirs[0]
    base = os.path.basename(rel)
    m = re.match(r"!([A-Za-z_]\w*)!", base)
    return m.group(1) if m else ""


_PROJECT_NS_RE = re.compile(r"^[a-z][a-z0-9_]{0,7}$")
_PLANT_FILE = "plant.sigil"
_PLANT_GATE_RE = re.compile(r"^\s*!<\+([^+>]+)\+>!\s*(on|off)\s*;", re.M)
_PLANT_CAT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,18}$")
_PROJECT_MAX_NAMESPACES = 16
_PROJECT_MAX_PACKAGES = 64
_PROJECT_MAX_PACKAGE_ID = 63
_PROJECT_MAX_EXPORTS = 64


def _project_plant_scan(root: str, sources: List[str]):
    """Find plant.sigil manifests and the 16-box limit per plant."""
    plants = {}
    for src_path in sources:
        if os.path.basename(src_path) != _PLANT_FILE:
            continue
        plant_dir = os.path.dirname(src_path)
        with open(src_path, "r", encoding="utf-8") as f:
            text = f.read()
        m = _PLANT_GATE_RE.search(text)
        if not m:
            return None, f"{src_path}: plant manifest needs !<+cat+>! on; or off;"
        category, state = m.group(1), m.group(2)
        if not _PLANT_CAT_RE.fullmatch(category):
            return None, f"{src_path}: invalid plant category '{category}' (1-18 ASCII letters/digits/_.-)"
        boxes = []
        try:
            entries = sorted(os.listdir(plant_dir))
        except OSError as e:
            return None, f"{src_path}: cannot list plant directory: {e}"
        for name in entries:
            full = os.path.join(plant_dir, name)
            if os.path.isdir(full) and re.fullmatch(r"![^!]+!", name):
                boxes.append(name)
        if len(boxes) > _PROJECT_MAX_NAMESPACES:
            return None, (f"{src_path}: too many boxes in plant '{category}' "
                          f"({len(boxes)} > {_PROJECT_MAX_NAMESPACES})")
        plants[plant_dir] = {"category": category, "on": state == "on", "boxes": boxes}
    return plants, None


def _project_plant_for(path: str, plants: Dict[str, Dict[str, object]]) -> Optional[str]:
    d = os.path.dirname(path)
    while True:
        if d in plants:
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _project_effects(sources_text: Dict[str, str],
                     raw_prototypes: Dict[str, List[str]]) -> Dict[str, Dict[str, Any]]:
    """Collect P1 return/retains effects across project files."""
    effects: Dict[str, Dict[str, Any]] = {}
    for rel, text in sources_text.items():
        prototypes = raw_prototypes.get(rel, [])
        # P1 effects only matter when the file exposes a pointer/function-pointer API.
        if not any(re.search(r"p\d*\*|f\^", proto) for proto in prototypes):
            continue
        prepared = "\n".join(prototypes) + "\n" + text
        prepared = re.sub(r"!([A-Za-z_]\w*)\[(\d+)\]!\s*\([^()]*\)", "0", prepared)
        prepared = re.sub(r"!([A-Za-z_]\w*)\[(\d+)\]!", "0", prepared)
        try:
            parser = Parser(Lexer(prepared, rel).tokenize(), rel)
            parser.parse_program()
        except Exception:
            continue
        ns = _project_namespace(rel)
        for name, summary in parser.func_summaries.items():
            key = f"{ns}_{name}" if ns and name != "main" else name
            effects[key] = {
                "summary": summary,
                "escape": set(parser.escape_params.get(name, set())),
                "params": list(parser.func_param_names.get(name, [])),
            }
    return effects




def _project_package_ids(src: str) -> List[str]:
    """Package IDs declared in one source (not references like !/1/!)."""
    seen = set()
    out: List[str] = []
    for m in _PROJECT_PKG_DECL_RE.finditer(src):
        pid = m.group(1)
        if pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out

_PROJECT_PKG_BIND_RE = re.compile(r"^\s*!(\d+)!\s+m,\s*([A-Za-z_]\w*)\s*;", re.M)
_PROJECT_EXT_REF_RE = re.compile(r"!([A-Za-z_]\w*)\[(\d+)\]!")
_PROJECT_LOCAL_REF_RE = re.compile(r"!/\s*(\d+)\s*/!")


def _project_package_bindings(src: str) -> Dict[str, str]:
    """Package id -> file-level target name for `!n! m, target;`."""
    out: Dict[str, str] = {}
    for m in _PROJECT_PKG_BIND_RE.finditer(src):
        out.setdefault(m.group(1), m.group(2))
    return out


def _rewrite_local_packages(src: str, ns: str, local_ids: Set[str],
                             exports: Dict[str, str]) -> str:
    """Resolve `!/n/!` to a same-namespace exported function when not local."""
    def repl(m):
        pid = m.group(1)
        if pid in local_ids:
            return m.group(0)
        key = f"{ns}.{pid}" if ns else pid
        return exports.get(key, m.group(0))
    return _PROJECT_LOCAL_REF_RE.sub(repl, src)


def _rewrite_external_packages(src: str, exports: Dict[str, str],
                                package_ids: Dict[str, Dict[str, str]],
                                bindings: Dict[str, str],
                                namespaces: Set[str], filename: str) -> str:
    """Rewrite `!name[n]!` to the exported function name, with specific errors."""
    def repl(m):
        ns, pid = m.group(1), m.group(2)
        key = f"{ns}.{pid}"
        line = src.count("\n", 0, m.start()) + 1
        col = m.start() - src.rfind("\n", 0, m.start())
        where = f"{filename}:{line}:{col}"
        if ns not in namespaces:
            raise SemanticError(
                f"{where}: namespace '!{ns}!' is not declared; "
                f"use an !{ns}!/ directory or !{ns}!.sigil prefix")
        if pid not in package_ids.get(ns, {}):
            declared = ", ".join(sorted(package_ids.get(ns, {}), key=int)) or "(none)"
            raise SemanticError(
                f"{where}: package '!{ns}[{pid}]!' is not declared in namespace "
                f"'{ns}' (declared: {declared})")
        if key not in exports:
            if key in bindings:
                raise SemanticError(
                    f"{where}: package '!{ns}[{pid}]!' targets variable "
                    f"'{bindings[key]}'; only file-level function packages are exported")
            raise SemanticError(
                f"{where}: package '!{ns}[{pid}]!' is declared but has no file-level "
                f"binding; use '!{pid}! m, function;'")
        return exports[key]
    return _PROJECT_EXT_REF_RE.sub(repl, src)


def _rename_function_calls(src: str, mapping: Dict[str, str]) -> str:
    """Rename function identifiers by token, not raw text.

    This covers definitions, calls, prototypes, package bindings and bare
    function pointers (`p@ add`), while leaving strings/comments alone and
    skipping member names after `.` / `->`.
    """
    if not mapping:
        return src
    tokens = Lexer(src, "rename.sigil").tokenize()
    lines = src.splitlines(keepends=True)
    line_starts = [0]
    for line in lines:
        line_starts.append(line_starts[-1] + len(line))
    edits = []
    for idx, tok in enumerate(tokens):
        if tok.kind != "IDENT" or tok.value not in mapping:
            continue
        prev = tokens[idx - 1].kind if idx else ""
        if prev in ("DOT", "ARROW"):
            continue
        start_off = line_starts[min(tok.line - 1, len(line_starts) - 1)] + tok.col - 1
        if src[start_off:start_off + len(tok.value)] != tok.value:
            found = src.find(tok.value, line_starts[tok.line - 1] if tok.line <= len(lines) else 0)
            if found < 0:
                continue
            start_off = found
        edits.append((start_off, start_off + len(tok.value), mapping[tok.value]))
    for start_off, end_off, new_name in sorted(edits, reverse=True):
        src = src[:start_off] + new_name + src[end_off:]
    return src


def _build_project(args, defines: Dict[str, str]) -> int:
    """把目录下所有 .sigil 转译到 .sigil-build/，再用 gcc 链接成一个可执行文件。"""
    root = args.build
    sources = _collect_sources(root)
    if not sources:
        print(f"error: no .sigil files under '{root}'", file=sys.stderr)
        return 1
    plants, plant_error = _project_plant_scan(root, sources)
    if plant_error:
        print(f"error: {plant_error}", file=sys.stderr)
        return 1
    compile_sources = [s for s in sources if os.path.basename(s) != _PLANT_FILE]
    if not compile_sources:
        print(f"error: no compilable .sigil files under '{root}'", file=sys.stderr)
        return 1

    out_dir = os.path.join(root, ".sigil-build")
    c_paths: List[str] = []
    sources_text: Dict[str, str] = {}
    prototypes: Dict[str, List[str]] = {}
    raw_prototypes: Dict[str, List[str]] = {}
    for src_path in compile_sources:
        rel = os.path.relpath(src_path, root)
        with open(src_path, "r", encoding="utf-8") as f:
            text = f.read()
        plant_dir = _project_plant_for(src_path, plants)
        if plant_dir is not None:
            if _PLANT_GATE_RE.search(text):
                print(f"error: {rel}: !<+cat+>! is only allowed in plant.sigil", file=sys.stderr)
                return 1
            plant = plants[plant_dir]
            if not plant["on"]:
                text = f"/* plant off: {plant['category']} */\n!<+{plant['category']}+>! off;\n" + text
        sources_text[rel] = text
        raw_prototypes[rel] = _project_prototypes(text, mangle=False)
        prototypes[rel] = _project_prototypes(text, _project_namespace(rel))
    effects = _project_effects(sources_text, raw_prototypes)
    project_functions = set()
    for _protos in prototypes.values():
        for _proto in _protos:
            _m = re.search(r'([A-Za-z_]\w*)\s*\(', _proto)
            if _m:
                project_functions.add(_m.group(1))
    package_index: Dict[str, Dict[str, str]] = {}
    for rel, text in sources_text.items():
        ns = _project_namespace(rel)
        for pid in _project_package_ids(text):
            key = f"{ns}.{pid}" if ns else pid
            bucket = package_index.setdefault(ns, {})
            if pid in bucket:
                print(f"error: duplicate package !{pid}! in namespace '{ns}' "
                      f"({bucket[pid]} and {rel})", file=sys.stderr)
                return 1
            bucket[pid] = rel
    namespaces = set()
    namespace_packages: Dict[str, int] = {}
    for rel, text in sources_text.items():
        dirs = _project_dir_namespaces(rel)
        if len(dirs) > 1:
            print(f"error: nested package namespaces in {rel} "
                  f"({', '.join(dirs)}); use one directory level", file=sys.stderr)
            return 1
        ns = _project_namespace(rel)
        if ns:
            if not _PROJECT_NS_RE.fullmatch(ns):
                print(f"error: namespace '!{ns}!' in {rel} is invalid "
                      f"(1-8 chars, lowercase [a-z][a-z0-9_]*)", file=sys.stderr)
                return 1
            namespaces.add(ns)
        ids = _project_package_ids(text)
        ns_key = ns or ""
        namespace_packages[ns_key] = namespace_packages.get(ns_key, 0) + len(ids)
        if namespace_packages[ns_key] > _PROJECT_MAX_PACKAGES:
            print(f"error: too many packages in namespace '{ns or '<global>'}' "
                  f"({namespace_packages[ns_key]} > {_PROJECT_MAX_PACKAGES})", file=sys.stderr)
            return 1
        for pid in ids:
            if not pid.isdigit() or int(pid) > _PROJECT_MAX_PACKAGE_ID:
                print(f"error: package !{pid}! in {rel} exceeds the budget "
                      f"(IDs must be 0-{_PROJECT_MAX_PACKAGE_ID})", file=sys.stderr)
                return 1
            if pid != str(int(pid)):
                print(f"error: package !{pid}! in {rel} has a non-canonical ID "
                      f"(leading zero)", file=sys.stderr)
                return 1
    if not plants and len(namespaces) > _PROJECT_MAX_NAMESPACES:
        print(f"error: too many namespaces ({len(namespaces)} > "
              f"{_PROJECT_MAX_NAMESPACES})", file=sys.stderr)
        return 1
    renames_by_ns: Dict[str, Dict[str, str]] = {}
    for rel, raws in raw_prototypes.items():
        ns = _project_namespace(rel)
        if not ns:
            continue
        for proto in raws:
            m = re.match(r".*?\b([A-Za-z_]\w*)\s*\(", proto)
            if m and m.group(1) != "main":
                renames_by_ns.setdefault(ns, {})[m.group(1)] = f"{ns}_{m.group(1)}"
    function_names = set()
    symbol_owner: Dict[str, str] = {}
    for rel, protos in prototypes.items():
        for proto in protos:
            m = re.match(r".*?\b([A-Za-z_]\w*)\s*\(", proto)
            if not m:
                continue
            name = m.group(1)
            function_names.add(name)
            if name in symbol_owner:
                other = symbol_owner[name]
                print(f"error: duplicate C symbol '{name}' in {other} and {rel}; "
                      f"namespaces do not rename C symbols (try '{_project_namespace(rel)}"
                      f"_{name}')", file=sys.stderr)
                return 1
            symbol_owner[name] = rel
    bindings_all: Dict[str, str] = {}
    for rel, text in sources_text.items():
        ns = _project_namespace(rel)
        for pid, target in _project_package_bindings(text).items():
            bindings_all[f"{ns}.{pid}" if ns else pid] = target
    exports: Dict[str, str] = {}
    for rel, text in sources_text.items():
        ns = _project_namespace(rel)
        for pid, target in _project_package_bindings(text).items():
            # Only function-target packages are cross-file exports.
            mangled = f"{ns}_{target}" if ns else target
            if mangled in function_names:
                exports[f"{ns}.{pid}" if ns else pid] = mangled
    export_counts: Dict[str, int] = {}
    for key in exports:
        ns = key.rsplit(".", 1)[0] if "." in key else ""
        export_counts[ns] = export_counts.get(ns, 0) + 1
        if export_counts[ns] > _PROJECT_MAX_EXPORTS:
            print(f"error: too many exported packages in namespace '{ns or '<global>'}' "
                  f"({export_counts[ns]} > {_PROJECT_MAX_EXPORTS})", file=sys.stderr)
            return 1
    map_path = os.path.join(out_dir, "packages.txt")
    os.makedirs(out_dir, exist_ok=True)
    with open(map_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# project package index\n")
        for rel, text in sources_text.items():
            ns = _project_namespace(rel)
            for pid in _project_package_ids(text):
                f.write(f"{ns + '.' if ns else ''}{pid} -> {rel}\n")
        for key, target in exports.items():
            f.write(f"{key} target -> {target}\n")
    for src_path in compile_sources:
        rel = os.path.relpath(src_path, root)
        c_path = os.path.join(out_dir, os.path.splitext(rel)[0] + ".c")
        os.makedirs(os.path.dirname(c_path) or out_dir, exist_ok=True)
        others: List[str] = []
        for other, protos in prototypes.items():
            if other != rel:
                others.extend(protos)
        prefix = ""
        if others:
            prefix = "/* project prototypes */\n" + "\n".join(sorted(set(others))) + "\n"
        prefix_lines = prefix.count("\n")
        src = sources_text[rel]
        try:
            ns = _project_namespace(rel)
            src = _rename_function_calls(src, renames_by_ns.get(ns, {}))
            src = _rewrite_local_packages(src, ns,
                                          set(_project_package_ids(src)), exports)
            src = _rewrite_external_packages(src, exports, package_index,
                                             bindings_all, namespaces, rel)
            c_src = compile_source(prefix + src, rel, prelude=args.prelude,
                                   line_offset=prefix_lines,
                                   bounds_check=args.bounds_check, defines=defines,
                                   line_directives=not args.no_line, strict=args.strict,
                                   effects=effects, checked=getattr(args, "checked", False),
                                   checked_strict=getattr(args, "checked_strict", False),
                                   checked_external=getattr(args, "checked_external", False),
                                   allow_external=set(getattr(args, "allow_external", []) or []),
                                   known_functions=project_functions)
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
    cflags = args.cflags
    if getattr(args, "checked", False) or getattr(args, "checked_strict", False):
        cflags += " -fno-strict-aliasing"
    if getattr(args, "asan", False) and getattr(args, "tsan", False):
        raise ValueError("--asan and --tsan are separate modes")
    sanitizers = []
    if getattr(args, "ub_check", False):
        sanitizers.append("undefined")
        cflags += " -ftrapv"
    if getattr(args, "asan", False):
        sanitizers.append("address")
        cflags += " -fno-omit-frame-pointer -g"
    if getattr(args, "tsan", False):
        sanitizers.append("thread")
        cflags += " -g"
    if sanitizers:
        cflags += " -fsanitize=" + ",".join(sanitizers)
        if "undefined" in sanitizers:
            cflags += " -fno-sanitize-recover=all"
    cmd = [args.cc] + cflags.split() + c_paths + ["-o", exe]
    print("Link      " + " ".join(cmd))
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        return rc
    print(f"Built     {exe}")
    if args.run:
        sys.stdout.flush()
        return subprocess.run([os.path.abspath(exe)]).returncode
    return 0


