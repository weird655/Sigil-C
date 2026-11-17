"""Human-readable netlist for the !...! rewiring layer (the multimeter)."""
import json
import os
import re
from typing import Any, Dict, List


def _type_name(t) -> str:
    name = getattr(t, "c_name", None)
    if name:
        return str(name)
    return t.__class__.__name__.lower()


def _field_text(base_name: str, offset: int, width: int, byte_index) -> str:
    if byte_index is not None:
        return f"byte({base_name}, i={byte_index})"
    kind = "bit" if width == 1 else "bits"
    return f"{kind}({base_name}, k={offset}, w={width})"


def _namespace(filename: str) -> str:
    parts = filename.replace("\\", "/").split("/")[:-1]
    for part in parts:
        m = re.fullmatch(r"!([^!]+)!", part)
        if m:
            return m.group(1)
    base = filename.replace("\\", "/").split("/")[-1]
    m = re.match(r"!([A-Za-z_]\w*)!", base)
    return m.group(1) if m else ""


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _graph(parser) -> Dict[str, Any]:
    """Objects + morphisms of the ! rewiring net (directed multigraph)."""
    p = parser.pkgs
    c = parser.confine
    ns = _namespace(parser.filename)
    objects: Dict[str, Dict[str, object]] = {}
    edges: List[Dict[str, str]] = []

    def obj(oid: str, label: str, kind: str, **extra) -> None:
        if oid not in objects:
            objects[oid] = {"id": oid, "label": label, "kind": kind, **extra}

    def edge(src: str, dst: str, kind: str, label: str = "") -> None:
        edges.append({"source": src, "target": dst, "kind": kind,
                      "label": label or kind})

    if ns:
        obj(f"ns:{ns}", f"!{ns}!/", "namespace")

    for pid, name in p.packages.items():
        pkg = f"pkg:{pid}"
        obj(pkg, f"!{pid}! {name}", "package", package_id=pid, alias=name)
        if ns:
            edge(pkg, f"ns:{ns}", "in", "in namespace")
        if pid in p.fields:
            base_name, offset, width, byte_index = p.fields[pid][4], p.fields[pid][1], p.fields[pid][2], p.fields[pid][3]
            field = f"field:{pid}"
            obj(field, _field_text(base_name, offset, width, byte_index), "field")
            edge(pkg, field, "field", "bit/byte slice")
        elif name in p.targets:
            tgt = f"target:{p.targets[name]}"
            obj(tgt, p.targets[name], "target")
            edge(pkg, tgt, "binds", "binds")
        elif p.has_slot(pid):
            slot = f"slot:{pid}"
            obj(slot, f"__sigil_pkg_{pid}", "slot")
            edge(pkg, slot, "local-slot", "local slot")

    for name, target in p.aliases.items():
        alias = f"alias:{name}"
        tgt = f"target:{target}"
        obj(alias, name, "alias")
        obj(tgt, target, "target")
        edge(alias, tgt, "alias", "alias")

    for name, pid in p.local_alias.items():
        alias = f"alias:{name}"
        obj(alias, name, "alias")
        edge(alias, f"pkg:{pid}", "local-alias", "local alias")

    for pid, (_, offset, width, byte_index, base_name) in p.fields.items():
        field = f"field:{pid}"
        obj(field, _field_text(base_name, offset, width, byte_index), "field")
        edge(f"pkg:{pid}", field, "field", "bit/byte slice")

    for gid in c.groups:
        group = f"group:{gid}"
        obj(group, f"!/[{gid}]/!", "group")
        for fn in c.expand_short(gid):
            obj(f"target:{fn}", fn, "target")
            edge(group, f"target:{fn}", "member", "member")

    for gid in c.long_groups:
        group = f"group:{gid}"
        obj(group, f"!/[[{gid}]]/!", "group")
        for fn in c.expand_long(gid):
            obj(f"target:{fn}", fn, "target")
            edge(group, f"target:{fn}", "member", "member")

    for line, col, kind, gid, mask, allowed in c.gates:
        gate = f"gate:{line}:{col}"
        obj(gate, f"![{mask}]! {kind.lower()}", "gate")
        edge(gate, f"group:{gid}", "gates", "gates")
        for fn in allowed:
            obj(f"target:{fn}", fn, "target")
            edge(gate, f"target:{fn}", "allows", "allows")

    if getattr(parser, "file_gate_seen", False):
        gate = "gate:file"
        state = "on" if parser.file_gate_on else "off"
        obj(gate, f"!<+{parser.file_gate_category}+>! {state}", "gate")
        if ns:
            edge(gate, f"ns:{ns}", "gates-file", f"file gate {state}")

    for pid in p.armed:
        mine = f"landmine:{pid}"
        obj(mine, f"!{pid}!!", "landmine")
        edge(f"pkg:{pid}", mine, "armed", "armed")
        bound = p.armed_bound.get(pid)
        if bound:
            edge(mine, f"pkg:{pid}", "bound", f"bound at {bound[0]}:{bound[1]}")

    for pid, allowed in c.confined.items():
        for fn in allowed:
            obj(f"target:{fn}", fn, "target")
            edge(f"pkg:{pid}", f"target:{fn}", "confined", "confined to")

    return {
        "namespace": ns or None,
        "namespaces": [ns] if ns else [],
        "objects": list(objects.values()),
        "morphisms": edges,
        "category": {
            "objects": len(objects),
            "morphisms": len(edges),
            "composition": "paths compose through binds/alias/field edges; identities are implicit",
        },
    }


def render_graph(parser, fmt: str = "json") -> str:
    return render_graph_data(_graph(parser), fmt)


def render_graph_data(g, fmt: str = "json") -> str:
    if fmt == "viewer":
        return render_html({"objects": [], "morphisms": [], "namespaces": []})
    if fmt == "json":
        return json.dumps(g, ensure_ascii=False, indent=2) + "\n"
    if fmt == "dot":
        shapes = {"namespace": "component", "package": "box", "target": "ellipse",
                  "field": "note", "group": "folder", "gate": "diamond",
                  "landmine": "octagon", "slot": "box", "alias": "plaintext"}
        lines = ["digraph sigil {", "  rankdir=LR;"]
        for o in g["objects"]:
            lines.append(f'  "{_esc(o["id"])}" [label="{_esc(o["label"])}", '
                         f'shape={shapes.get(o["kind"], "ellipse")}];')
        for e in g["morphisms"]:
            lines.append(f'  "{_esc(e["source"])}" -> "{_esc(e["target"])}" '
                         f'[label="{_esc(e["label"])}"];')
        lines.append("}")
        return "\n".join(lines) + "\n"
    if fmt == "html":
        return render_html(g)
    if fmt == "mermaid":
        ids: Dict[str, str] = {}
        for i, o in enumerate(g["objects"]):
            ids[o["id"]] = f"n{i}"
        lines = ["flowchart LR"]
        for o in g["objects"]:
            lines.append(f'  {ids[o["id"]]}["{_esc(o["label"])}"]')
        for e in g["morphisms"]:
            lines.append(f'  {ids[e["source"]]} -->|"{_esc(e["label"])}"| {ids[e["target"]]}')
        return "\n".join(lines) + "\n"
    raise ValueError(f"unknown netlist format: {fmt} (use text/dot/json/mermaid)")


def merge_project_graphs(root: str, items) -> Dict[str, Any]:
    """Merge per-file graphs into one project graph with file nodes and uses edges."""
    project = f"project:{os.path.basename(os.path.abspath(root)) or 'project'}"
    objects: Dict[str, Dict[str, Any]] = {}
    raw_edges: List[Dict[str, str]] = []
    namespaces = set()
    producer: Dict[tuple, str] = {}

    def obj(oid: str, label: str, kind: str) -> None:
        objects.setdefault(oid, {"id": oid, "label": label, "kind": kind})

    def edge(src: str, dst: str, kind: str, label: str = "") -> None:
        raw_edges.append({"source": src, "target": dst, "kind": kind, "label": label or kind})

    def pref(rel: str, oid: str) -> str:
        if oid.startswith(("ns:", "project:", "file:")):
            return oid
        return f"file:{rel}:{oid}"

    obj(project, project, "project")

    # Pass 1: every file/namespace/package exists before uses are resolved.
    for rel, src, g in items:
        file_id = f"file:{rel}"
        obj(file_id, rel, "file")
        ns = g.get("namespace")
        if ns:
            namespaces.add(ns)
            obj(f"ns:{ns}", f"!{ns}!/", "namespace")
            edge(file_id, f"ns:{ns}", "in-file", "in file")
        for o in g.get("objects", []):
            oid = pref(rel, o["id"])
            obj(oid, o["label"], o["kind"])
            if o["kind"] == "package" and ns and o.get("package_id") is not None:
                producer[(ns, o["package_id"])] = oid

    # Pass 2: graph edges and cross-file uses.
    for rel, src, g in items:
        file_id = f"file:{rel}"
        ns = g.get("namespace")
        for e in g.get("morphisms", []):
            edge(pref(rel, e["source"]), pref(rel, e["target"]), e["kind"], e["label"])
        for m in re.finditer(r"!([a-z][a-z0-9_]*)\[(\d+)\]!", src):
            target = producer.get((m.group(1), m.group(2)))
            if target:
                edge(file_id, target, "uses", m.group(0))
        if ns:
            for m in re.finditer(r"!/\s*(\d+)\s*/!", src):
                target = producer.get((ns, m.group(1)))
                if target:
                    edge(file_id, target, "uses-local", f"!/{m.group(1)}/!")

    for ns in sorted(namespaces):
        edge(f"ns:{ns}", project, "in-project", "in project")

    edges = []
    seen = set()
    for e in raw_edges:
        key = (e["source"], e["target"], e["kind"], e["label"])
        if key not in seen:
            seen.add(key)
            edges.append(e)
    return {
        "namespace": None,
        "namespaces": sorted(namespaces),
        "project": project,
        "objects": list(objects.values()),
        "morphisms": edges,
        "category": {
            "objects": len(objects),
            "morphisms": len(edges),
            "composition": "files contain namespaces; namespaces contain packages; uses edges cross files",
        },
    }


def render_netlist(parser) -> str:
    p = parser.pkgs
    c = parser.confine
    ns = _namespace(parser.filename)
    lines: List[str] = [f"# Sigil-C netlist: {parser.filename}", "",
                        f"# namespace: {ns or '(none)'}", ""]
    if getattr(parser, "file_gate_seen", False):
        state = "on" if parser.file_gate_on else "off"
        lines += ["[file gate]", f"!<+{parser.file_gate_category}+>! = {state}", ""]
    lines.append("[packages]")
    seen = set()
    for pid, name in p.packages.items():
        seen.add(pid)
        if pid in p.fields:
            base_name, offset, width, byte_index = p.fields[pid][4], p.fields[pid][1], p.fields[pid][2], p.fields[pid][3]
            where = "local" if p.has_slot(pid) else "file"
            lines.append(f"!{pid}! {name} -> {_field_text(base_name, offset, width, byte_index)}   [{where} field]")
        elif name in p.targets:
            lines.append(f"!{pid}! {name} -> {p.targets[name]}   [file alias]")
        elif p.has_slot(pid):
            target = p.local.get(pid, "?")
            lines.append(f"!{pid}! {name} -> __sigil_pkg_{pid} (target {target})   [local slot]")
        else:
            lines.append(f"!{pid}! {name} -> (unbound)")
    for pid in sorted(set(p.slot_types) - seen):
        if pid in p.fields:
            continue
        target = p.local.get(pid, "?")
        tag = " [local slot]" if p.has_slot(pid) else " [type only]"
        lines.append(f"!{pid}! -> __sigil_pkg_{pid} (target {target}){tag}")
    for pid, (base_type, offset, width, byte_index, base_name) in p.fields.items():
        if pid in seen:
            continue
        where = "local" if p.has_slot(pid) else "file"
        lines.append(f"!{pid}! -> {_field_text(base_name, offset, width, byte_index)}   [{where} field]")
    if len(lines) == 2:
        lines.append("(none)")

    lines += ["", "[qualified]"]
    qualified = sorted(set(p.packages) | set(p.slot_types) | set(p.fields), key=int)
    if qualified and ns:
        for pid in qualified:
            lines.append(f"{ns}.{pid} -> !{pid}!")
    else:
        lines.append("(none)")

    lines += ["", "[fields]"]
    if p.fields:
        for pid, (base_type, offset, width, byte_index, base_name) in p.fields.items():
            where = "local" if p.has_slot(pid) else "file"
            lines.append(f"!{pid}! {_field_text(base_name, offset, width, byte_index)} [{where}]")
    else:
        lines.append("(none)")

    lines += ["", "[links]"]
    links = 0
    for left, right in p.aliases.items():
        lines.append(f"{left} <- {right}")
        links += 1
    for name, pid in p.local_alias.items():
        lines.append(f"!{pid}! <- {name}   [local]")
        links += 1
    if not links:
        lines.append("(none)")

    lines += ["", "[groups]"]
    groups = 0
    for gid in c.groups:
        lines.append(f"!/[{gid}]/! = {', '.join(c.expand_short(gid))}")
        groups += 1
    for gid in c.long_groups:
        lines.append(f"!/[[{gid}]]/! = {', '.join(c.expand_long(gid))}")
        groups += 1
    if not groups:
        lines.append("(none)")

    lines += ["", "[gates]"]
    if c.gates:
        for line, col, kind, gid, mask, allowed in c.gates:
            label = f"!/[[{gid}]]/!" if kind == 'LONG_GROUP' else f"!/[{gid}]/!"
            lines.append(f"![{mask}]! {label} -> {', '.join(allowed) if allowed else '(none)'}")
    else:
        lines.append("(none)")

    lines += ["", "[landmines]"]
    if p.armed:
        for pid in sorted(p.armed):
            name = p.packages.get(pid, "?")
            arm = p.arm_sites.get(pid)
            bound = p.armed_bound.get(pid)
            where = f"{arm[0]}:{arm[1]}" if arm else "?"
            if bound:
                lines.append(f"!{pid}!! {name} armed at {where}, bound at {bound[0]}:{bound[1]}")
            else:
                lines.append(f"!{pid}!! {name} armed at {where}, unbound")
    else:
        lines.append("(none)")

    lines += ["", "[confinement]"]
    if c.confined:
        for pid, allowed in c.confined.items():
            lines.append(f"!{pid}! -> {', '.join(sorted(allowed)) if allowed else '(none)'}")
    else:
        lines.append("(none)")
    return "\n".join(lines) + "\n"

_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SIGIL-C // WIRING TERMINAL</title>
<style>
:root{--bg:#0d0a06;--panel:#19130b;--line:#6b4f2a;--text:#f4e3b2;--muted:#b9985a;
--amber:#ffb000;--green:#9fd356;--red:#ff6b4a;--blue:#79c0ff;--purple:#bc8cff}
*{box-sizing:border-box}html,body{height:100%;margin:0;background:var(--bg);color:var(--text);
font:13px/1.45 "Courier New",ui-monospace,monospace;letter-spacing:.02em}
#app{display:grid;grid-template-columns:1fr 320px;grid-template-rows:54px 1fr;height:100%}
header{grid-column:1/3;display:flex;align-items:center;gap:14px;padding:0 16px;background:
repeating-linear-gradient(0deg,#19130b,#19130b 2px,#1d160d 2px,#1d160d 4px);border-bottom:2px solid var(--line)}
header b{font-size:14px;color:var(--amber);letter-spacing:.14em;text-shadow:0 0 8px #ffb00055}
header .stat{color:var(--muted);font-size:11px}#toolbar{margin-left:auto;display:flex;gap:6px}
button{background:#241a0f;color:var(--text);border:1px solid var(--line);border-radius:3px;
padding:5px 10px;cursor:pointer;font:12px "Courier New",monospace;letter-spacing:.08em;text-transform:uppercase}
button:hover{border-color:var(--amber);color:var(--amber)}
button.active{background:var(--amber);color:#120d08;border-color:var(--amber)}
#stage{position:relative;overflow:hidden;background:
radial-gradient(#6b4f2a33 1px,transparent 1px),linear-gradient(#ffffff04 1px,transparent 1px),#0b0805;
background-size:24px 24px,120px 120px,auto}
#stage:after{content:"";position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(
0deg,rgba(0,0,0,.10),rgba(0,0,0,.10) 1px,transparent 1px,transparent 3px);mix-blend-mode:multiply}
#wind{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;opacity:.55}
#svg{position:relative;z-index:1;width:100%;height:100%;display:block;cursor:grab}
#svg.panning{cursor:grabbing}
#panel{background:var(--panel);border-left:2px solid var(--line);padding:14px;overflow:auto}
#panel h2{font-size:11px;margin:14px 0 6px;color:var(--amber);letter-spacing:.14em;font-weight:700}
#panel .label{font-size:16px;font-weight:700;margin-bottom:4px;word-break:break-all;color:var(--amber)}
#panel .kind{display:inline-block;font-size:10px;padding:1px 7px;border:1px solid var(--line);
color:var(--muted);margin-bottom:10px;letter-spacing:.08em}
#panel ul{padding-left:18px;margin:6px 0 12px}#panel li{color:var(--muted);margin:3px 0}
#panel li b{color:var(--text);font-weight:600}
#legend{position:absolute;left:12px;bottom:12px;z-index:2;background:rgba(25,19,11,.94);
border:1px solid var(--line);border-radius:3px;padding:8px 10px;display:flex;gap:12px;flex-wrap:wrap;max-width:calc(100% - 24px)}
#legend span{display:inline-flex;align-items:center;gap:5px;color:var(--muted);font-size:10px}
.dot{width:9px;height:9px;border-radius:1px;box-shadow:0 0 6px currentColor}
#hint{position:absolute;right:12px;bottom:12px;z-index:2;color:var(--muted);font-size:10px;
background:rgba(25,19,11,.94);padding:4px 8px;border:1px solid var(--line);border-radius:3px}
#drop{position:absolute;inset:0;z-index:3;display:none;place-items:center;background:rgba(8,6,4,.55)}
#drop.hot{display:grid;background:rgba(255,176,0,.10)}
#drop .box{width:min(520px,80%);padding:36px;border:2px dashed var(--amber);background:var(--panel);
text-align:center;color:var(--amber);letter-spacing:.1em;box-shadow:0 0 28px #ffb00033}
#drop small{display:block;margin-top:10px;color:var(--muted);letter-spacing:.02em;font-size:11px}
.node{cursor:grab}.node text{fill:var(--text);font-size:12px;pointer-events:none;user-select:none}
.node rect{stroke-width:1.5;filter:drop-shadow(0 0 3px #000)}.node.selected rect{stroke:#fff;stroke-width:2.5}
.node.dim{opacity:.18}
.edge{fill:none;stroke:#8a6a38;stroke-width:1.4}.edge.hl{stroke:var(--amber);stroke-width:2.6}.edge.dim{opacity:.10}
.edge-label{fill:var(--muted);font-size:10px;pointer-events:none;paint-order:stroke;stroke:#0b0805;
stroke-width:3px;stroke-linejoin:round;opacity:0;transition:opacity .15s}
.edge-label.hl{fill:var(--amber);opacity:1}.show-labels .edge-label{opacity:1}
.via{fill:var(--amber);stroke:#0b0805;stroke-width:1}
.frame{fill:none;stroke-dasharray:6 5;stroke-width:1.2;opacity:.8}
@media (max-width:820px){#app{grid-template-columns:1fr;grid-template-rows:54px 1fr 230px}
#panel{border-left:0;border-top:2px solid var(--line)}}
</style>
</head>
<body>
<div id="app">
<header><b>SIGIL-C // WIRING TERMINAL</b><span class="stat" id="stats"></span>
<div id="toolbar"><button id="fit">Fit</button><button id="reset">Reset</button><button id="labels">Labels</button></div>
</header>
<div id="stage">
<canvas id="wind"></canvas>
<svg id="svg"><defs>
<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#b9985a"/></marker>
</defs><g id="viewport"><g id="frames"></g><g id="edges"></g><g id="nodes"></g></g></svg>
<div id="drop"><div class="box">DROP GRAPH .JSON<br><small>export: sigilc --netlist --netlist-format json -o graph.json</small></div></div>
<div id="legend"></div><div id="hint">drag nodes · wheel zoom · drag background pan · click node/edge</div>
</div>
<aside id="panel"><h2>DETAIL</h2><div id="detail">Click a node or edge.</div></aside>
</div>
<script>
const EMBEDDED = __GRAPH__;
const KIND_COLOR = {namespace:"#79c0ff",package:"#9fd356",target:"#ffb000",field:"#bc8cff",
  group:"#ff6b4a",gate:"#ff9f43",landmine:"#ff5c5c",slot:"#b9985a",alias:"#79c0ff",
  file:"#8a6a38",project:"#a371f7",plant:"#ff9f43"};
const KIND_LABEL = {namespace:"命名空间",package:"包",target:"目标",field:"字段切片",group:"集合/组",
  gate:"门",landmine:"地雷",slot:"局部槽",alias:"别名",file:"文件",project:"工程",plant:"发电厂"};
const EDGE_COLOR = {in:"#79c0ff",binds:"#9fd356",alias:"#79c0ff",field:"#bc8cff",member:"#ff6b4a",
  gates:"#ff9f43",allows:"#ff9f43",confined:"#ff5c5c",armed:"#ff5c5c",bound:"#ff5c5c",
  "in-file":"#8a6a38","in-project":"#d2a8ff",uses:"#ffb000","uses-local":"#ffb000","gates-file":"#ff6b4a",
  "in-plant":"#ff9f43",powers:"#ff9f43"};
const svg=document.getElementById("svg"), viewport=document.getElementById("viewport");
const frames=document.getElementById("frames"), edgeLayer=document.getElementById("edges"), nodeLayer=document.getElementById("nodes");
const panel=document.getElementById("detail"), stats=document.getElementById("stats");
const drop=document.getElementById("drop");
const RANK={plant:-2,project:-1,file:0,namespace:1,group:2,gate:2,landmine:3,package:4,field:5,alias:5,slot:6,target:7};
let GRAPH={objects:[],morphisms:[],namespaces:[]};
let nodes=[],edges=[],byId=new Map(),adj=new Map();
const nodeEls=new Map();let edgeEls=[];
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}

function initLayout(){
  const cols={};nodes.forEach(n=>{const c=RANK[n.kind]??4;(cols[c]=cols[c]||[]).push(n);});
  Object.keys(cols).forEach(c=>{cols[c].sort((a,b)=>a.label.localeCompare(b.label));});
  nodes.forEach(n=>{const c=RANK[n.kind]??4;const arr=cols[c],row=arr.indexOf(n);n.x=110+c*175;n.y=90+row*82;});
}
function shapeFor(kind){
  if(kind==="namespace")return{w:170,h:52,rx:5};
  if(kind==="group"||kind==="gate"||kind==="landmine")return{w:160,h:48,rx:20};
  return{w:170,h:46,rx:3};
}
const proj=n=>({x:n.x,y:n.y});
function addVia(x,y){const c=document.createElementNS("http://www.w3.org/2000/svg","circle");c.classList.add("via");
  c.setAttribute("cx",x);c.setAttribute("cy",y);c.setAttribute("r",3);frames.append(c);}
function frameFor(kind,title,members,color){
  if(!members.length)return;const pts=members.map(proj);const xs=pts.map(p=>p.x),ys=pts.map(p=>p.y);
  const x=Math.min(...xs)-24,y=Math.min(...ys)-28,w=Math.max(...xs)-x+190,h=Math.max(...ys)-y+80;
  const r=document.createElementNS("http://www.w3.org/2000/svg","rect");r.classList.add("frame");
  r.setAttribute("x",x);r.setAttribute("y",y);r.setAttribute("width",w);r.setAttribute("height",h);
  r.setAttribute("stroke",color);r.setAttribute("rx",10);
  const t=document.createElementNS("http://www.w3.org/2000/svg","text");t.setAttribute("x",x+10);
  t.setAttribute("y",y+18);t.textContent=title;t.setAttribute("fill",color);t.setAttribute("font-size","11");
  frames.append(r,t);
}
function buildGraph(data){
  if(!data||!Array.isArray(data.objects)||!Array.isArray(data.morphisms))throw new Error("not a netlist graph JSON");
  GRAPH=data;nodes=data.objects.map((o,i)=>({...o,x:0,y:0,idx:i}));
  byId=new Map(nodes.map(n=>[n.id,n]));
  edges=data.morphisms.filter(e=>byId.has(e.source)&&byId.has(e.target));
  adj=new Map(nodes.map(n=>[n.id,{out:[],in:[]}]));
  edges.forEach((e,i)=>{e.idx=i;adj.get(e.source).out.push(e);adj.get(e.target).in.push(e);});
  nodeEls.clear();edgeEls=[];nodeLayer.replaceChildren();edgeLayer.replaceChildren();
  document.getElementById("legend").replaceChildren();
  nodes.forEach(n=>{
    const g=document.createElementNS("http://www.w3.org/2000/svg","g");g.classList.add("node");g.dataset.id=n.id;
    const sh=shapeFor(n.kind);n.w=sh.w;n.h=sh.h;
    const r=document.createElementNS("http://www.w3.org/2000/svg","rect");
    r.setAttribute("width",sh.w);r.setAttribute("height",sh.h);r.setAttribute("rx",sh.rx);
    r.setAttribute("fill","#19130b");r.setAttribute("stroke",KIND_COLOR[n.kind]||"#b9985a");
    const t=document.createElementNS("http://www.w3.org/2000/svg","text");
    t.setAttribute("x",12);t.setAttribute("y",28);t.textContent=n.label.length>22?n.label.slice(0,21)+"…":n.label;
    g.append(r,t);nodeLayer.append(g);nodeEls.set(n.id,g);
  });
  edges.forEach((e,i)=>{
    const p=document.createElementNS("http://www.w3.org/2000/svg","path");p.classList.add("edge");p.dataset.idx=i;
    p.setAttribute("marker-end","url(#arrow)");p.setAttribute("stroke",EDGE_COLOR[e.kind]||"#8a6a38");
    const t=document.createElementNS("http://www.w3.org/2000/svg","text");t.classList.add("edge-label");t.textContent=e.label;
    edgeLayer.append(p,t);edgeEls.push({p,t,e});
  });
  stats.textContent=`${nodes.length} objects · ${edges.length} morphisms · ${data.project?(data.namespaces||[]).length+" namespaces":(data.namespace||"no namespace")}`;
  const legend=document.getElementById("legend");
  Object.keys(KIND_LABEL).forEach(k=>{if(!nodes.some(n=>n.kind===k))return;
    const s=document.createElement("span");s.innerHTML=`<i class="dot" style="background:${KIND_COLOR[k]}"></i>${KIND_LABEL[k]}`;legend.append(s);});
  initLayout();draw();fit();startWind();
}
function draw(){
  frames.replaceChildren();
  const nsList=GRAPH.namespaces||(GRAPH.namespace?[GRAPH.namespace]:[]);
  nsList.forEach(ns=>{
    const nsNode=`ns:${ns}`;
    const ids=new Set(nodes.filter(n=>n.kind!=="file"&&n.kind!=="project"&&
      edges.some(e=>e.target===nsNode&&e.source===n.id)).map(n=>n.id));
    let changed=true;while(changed){changed=false;edges.forEach(e=>{
      if(ids.has(e.source)&&!ids.has(e.target)&&["binds","field","alias","local-alias"].includes(e.kind)){ids.add(e.target);changed=true;}});}
    frameFor("namespace",`set: !${ns}!/`,nodes.filter(n=>ids.has(n.id)),KIND_COLOR.namespace);
  });
  nodes.filter(n=>n.kind==="group").forEach(g=>{
    const m=edges.filter(e=>e.source===g.id&&e.kind==="member").map(e=>byId.get(e.target)).filter(Boolean);
    frameFor("group",`set: ${g.label}`,m,KIND_COLOR.group);
  });
  const pairCount=new Map();edges.forEach(e=>{const k=[e.source,e.target].sort().join("|");pairCount.set(k,(pairCount.get(k)||0)+1);});
  const pairSeen=new Map();
  edgeEls.forEach(({p,t,e})=>{
    const a=byId.get(e.source),b=byId.get(e.target);if(!a||!b)return;
    const k=[e.source,e.target].sort().join("|"),n=pairCount.get(k),s=pairSeen.get(k)||0;pairSeen.set(k,s+1);
    const pa=proj(a),pb=proj(b),off=(s-(n-1)/2)*20,mx=(pa.x+pb.x)/2+off;
    p.setAttribute("d",`M ${pa.x} ${pa.y} H ${mx} V ${pb.y} H ${pb.x}`);
    t.setAttribute("x",mx);t.setAttribute("y",(pa.y+pb.y)/2-3);t.setAttribute("text-anchor","middle");
    addVia(mx,pa.y);addVia(mx,pb.y);
  });
  nodes.forEach(n=>{const g=nodeEls.get(n.id);const q=proj(n);g.setAttribute("transform",`translate(${q.x-n.w/2},${q.y-n.h/2})`);});
}
let view={x:0,y:0,k:1};
function applyTransform(){viewport.setAttribute("transform",`translate(${view.x},${view.y}) scale(${view.k})`);}
function fit(){if(!nodes.length){view={x:0,y:0,k:1};applyTransform();return;}
  const xs=nodes.map(n=>n.x),ys=nodes.map(n=>n.y);const x=Math.min(...xs)-200,y=Math.min(...ys)-160;
  const w=Math.max(...xs)-x+300,h=Math.max(...ys)-y+240,r=svg.getBoundingClientRect();
  view.k=Math.min(1.4,Math.min(r.width/w,r.height/h));view.x=(r.width-w*view.k)/2-x*view.k;view.y=(r.height-h*view.k)/2-y*view.k;applyTransform();}
let drag=null,pan=null;
svg.addEventListener("pointerdown",ev=>{
  const g=ev.target.closest&&ev.target.closest(".node");
  if(g){const n=byId.get(g.dataset.id);drag={n,dx:ev.clientX,dy:ev.clientY,ox:n.x,oy:n.y};svg.setPointerCapture(ev.pointerId);return;}
  pan={x:ev.clientX,y:ev.clientY,vx:view.x,vy:view.y};svg.classList.add("panning");svg.setPointerCapture(ev.pointerId);
});
svg.addEventListener("pointermove",ev=>{
  if(drag){drag.n.x=drag.ox+(ev.clientX-drag.dx)/view.k;drag.n.y=drag.oy+(ev.clientY-drag.dy)/view.k;draw();return;}
  if(pan){view.x=pan.vx+ev.clientX-pan.x;view.y=pan.vy+ev.clientY-pan.y;applyTransform();}
});
svg.addEventListener("pointerup",()=>{drag=null;pan=null;svg.classList.remove("panning");});
svg.addEventListener("wheel",ev=>{ev.preventDefault();const r=svg.getBoundingClientRect(),mx=ev.clientX-r.left,my=ev.clientY-r.top;
  const k=Math.max(.3,Math.min(2.4,view.k*(ev.deltaY<0?1.12:.89)));view.x=mx-(mx-view.x)*k/view.k;view.y=my-(my-view.y)*k/view.k;view.k=k;applyTransform();},{passive:false});
document.getElementById("fit").onclick=fit;
document.getElementById("reset").onclick=()=>{initLayout();draw();fit();};
document.getElementById("labels").onclick=()=>document.body.classList.toggle("show-labels");
function select(id){
  document.querySelectorAll(".node").forEach(g=>g.classList.toggle("selected",g.dataset.id===id));
  edgeEls.forEach(({p,t,e})=>{const hl=e.source===id||e.target===id;p.classList.toggle("hl",hl);t.classList.toggle("hl",hl);p.classList.toggle("dim",!hl);t.classList.toggle("dim",!hl);});
  const n=byId.get(id);if(!n)return;const a=adj.get(id);
  panel.innerHTML=`<div class="label">${esc(n.label)}</div><div class="kind">${KIND_LABEL[n.kind]||n.kind} · ${esc(n.id)}</div>
  <h2>OUT</h2><ul>${a.out.length?a.out.map(e=>`<li><b>${esc(e.kind)}</b> → ${esc(e.target)}</li>`).join(""):"<li>none</li>"}</ul>
  <h2>IN</h2><ul>${a.in.length?a.in.map(e=>`<li><b>${esc(e.kind)}</b> ← ${esc(e.source)}</li>`).join(""):"<li>none</li>"}</ul>`;
}
nodeLayer.addEventListener("click",ev=>{const g=ev.target.closest(".node");if(g)select(g.dataset.id);});
edgeLayer.addEventListener("click",ev=>{const p=ev.target.closest(".edge");if(!p)return;const {e}=edgeEls[+p.dataset.idx];
  panel.innerHTML=`<div class="label">${esc(e.label)}</div><div class="kind">${esc(e.kind)}</div><h2>MORPHISM</h2><ul><li><b>source</b> ${esc(e.source)}</li><li><b>target</b> ${esc(e.target)}</li></ul>`;});
// Drop-to-load: export JSON, then drag it here.
drop.addEventListener("dragover",ev=>{ev.preventDefault();drop.classList.add("hot");});
drop.addEventListener("dragleave",()=>drop.classList.remove("hot"));
window.addEventListener("dragover",ev=>{ev.preventDefault();drop.classList.add("hot");});
window.addEventListener("drop",async ev=>{
  ev.preventDefault();drop.classList.remove("hot");
  const file=ev.dataTransfer.files&&ev.dataTransfer.files[0];if(!file)return;
  try{const data=JSON.parse(await file.text());buildGraph(data);drop.style.display="none";}
  catch(err){drop.classList.add("hot");drop.querySelector(".box").innerHTML=`DROP FAILED<br><small>${esc(err.message)}</small>`;}
});
// Retro wind field background.
const windCanvas=document.getElementById("wind"),wctx=windCanvas.getContext("2d");
let windP=[];let windOn=false;
function resizeWind(){windCanvas.width=windCanvas.clientWidth;windCanvas.height=windCanvas.clientHeight;}
function initWind(){windP=[];const n=Math.min(90,Math.floor(windCanvas.width*windCanvas.height/14000));
  for(let i=0;i<n;i++)windP.push({x:Math.random()*windCanvas.width,y:Math.random()*windCanvas.height,
    a:Math.random()*6.28,s:.5+Math.random()*1.4,l:3+Math.random()*8});}
function windStep(t){
  if(!windOn)return;wctx.clearRect(0,0,windCanvas.width,windCanvas.height);wctx.lineWidth=1;
  for(const p of windP){
    const ang=Math.sin(p.x*.004+t*.00025)*1.1+Math.cos(p.y*.003)*0.7;
    p.x+=Math.cos(ang)*p.s;p.y+=Math.sin(ang)*p.s;
    if(p.x<0||p.x>windCanvas.width||p.y<0||p.y>windCanvas.height){p.x=Math.random()*windCanvas.width;p.y=Math.random()*windCanvas.height;}
    wctx.strokeStyle="rgba(255,176,0,.22)";wctx.beginPath();wctx.moveTo(p.x,p.y);
    wctx.lineTo(p.x-Math.cos(ang)*p.l,p.y-Math.sin(ang)*p.l);wctx.stroke();
  }
  requestAnimationFrame(windStep);
}
function startWind(){if(windOn)return;windOn=true;resizeWind();initWind();requestAnimationFrame(windStep);}
window.addEventListener("resize",()=>{resizeWind();initWind();});
if(EMBEDDED&&EMBEDDED.objects&&EMBEDDED.objects.length){buildGraph(EMBEDDED);}
else{drop.style.display="grid";resizeWind();initWind();}
</script>
</body></html>
"""


def render_html(g) -> str:
    payload = json.dumps(g, ensure_ascii=False).replace("<", "\\u003c")
    return _HTML.replace("__GRAPH__", payload)
