"""Human-readable netlist for the !...! rewiring layer (the multimeter)."""
import json
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
        "objects": list(objects.values()),
        "morphisms": edges,
        "category": {
            "objects": len(objects),
            "morphisms": len(edges),
            "composition": "paths compose through binds/alias/field edges; identities are implicit",
        },
    }


def render_graph(parser, fmt: str = "json") -> str:
    g = _graph(parser)
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


def render_netlist(parser) -> str:
    p = parser.pkgs
    c = parser.confine
    ns = _namespace(parser.filename)
    lines: List[str] = [f"# Sigil-C netlist: {parser.filename}", "",
                        f"# namespace: {ns or '(none)'}", ""]
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
<title>Sigil-C net graph</title>
<style>
:root{--bg:#0e1117;--panel:#161b22;--line:#30363d;--text:#e6edf3;--muted:#8b949e;
--ns:#58a6ff;--pkg:#3fb950;--target:#d29922;--field:#bc8cff;--group:#ff7b72;--gate:#f0883e;--mine:#f85149;--alias:#79c0ff}
*{box-sizing:border-box}html,body{height:100%;margin:0;background:var(--bg);color:var(--text);font:13px/1.45 ui-sans-serif,system-ui,"Segoe UI",sans-serif}
#app{display:grid;grid-template-columns:1fr 320px;grid-template-rows:52px 1fr;height:100%}
header{grid-column:1/3;display:flex;align-items:center;gap:14px;padding:0 16px;background:var(--panel);border-bottom:1px solid var(--line)}
header b{font-size:14px}header .stat{color:var(--muted)}#toolbar{margin-left:auto;display:flex;gap:8px}
button{background:#21262d;color:var(--text);border:1px solid var(--line);border-radius:6px;padding:5px 10px;cursor:pointer}
button:hover{border-color:var(--ns)}#stage{position:relative;overflow:hidden}
#svg{width:100%;height:100%;display:block;cursor:grab}#svg.panning{cursor:grabbing}
#panel{background:var(--panel);border-left:1px solid var(--line);padding:14px;overflow:auto}
#panel h2{font-size:13px;margin:0 0 8px;color:var(--muted);font-weight:600}
#panel .label{font-size:16px;font-weight:700;margin-bottom:4px;word-break:break-all}
#panel .kind{display:inline-block;font-size:11px;padding:1px 7px;border-radius:10px;background:#21262d;color:var(--muted);margin-bottom:10px}
#panel ul{padding-left:18px;margin:6px 0 12px}#panel li{color:var(--muted);margin:3px 0}
#panel li b{color:var(--text);font-weight:600}#legend{position:absolute;left:12px;bottom:12px;background:rgba(22,27,34,.9);
border:1px solid var(--line);border-radius:8px;padding:10px 12px;display:flex;gap:12px;flex-wrap:wrap;max-width:calc(100% - 24px)}
#legend span{display:inline-flex;align-items:center;gap:5px;color:var(--muted);font-size:11px}.dot{width:9px;height:9px;border-radius:50%}
#legend .line{width:14px;height:0;border-top:2px solid var(--muted)}
.node{cursor:grab}.node text{fill:var(--text);font-size:12px;pointer-events:none;user-select:none}
.node rect{stroke-width:1.5}.node.selected rect{stroke:#fff;stroke-width:2.5}.node.dim{opacity:.18}
.edge{fill:none;stroke:#484f58;stroke-width:1.4}.edge.hl{stroke:#fff;stroke-width:2.6}.edge.dim{opacity:.10}
.edge-label{fill:var(--muted);font-size:10px;pointer-events:none;paint-order:stroke;stroke:#0e1117;stroke-width:3px;stroke-linejoin:round;opacity:0;transition:opacity .15s}.edge-label.hl{fill:#fff;opacity:1}.show-labels .edge-label{opacity:1}
.hidden{display:none}.frame{fill:none;stroke-dasharray:6 5;stroke-width:1.2;opacity:.8}
#hint{position:absolute;right:12px;bottom:12px;color:var(--muted);font-size:11px;background:rgba(22,27,34,.9);
padding:4px 8px;border-radius:6px;border:1px solid var(--line)}
@media (max-width:820px){#app{grid-template-columns:1fr;grid-template-rows:52px 1fr 230px}#panel{border-left:0;border-top:1px solid var(--line)}}
</style>
</head>
<body>
<div id="app">
<header><b>Sigil-C net graph</b><span class="stat" id="stats"></span>
<div id="toolbar"><button id="fit">Fit</button><button id="reset">Reset</button><button id="labels">Labels</button></div>
</header>
<div id="stage">
<svg id="svg"><defs>
<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#8b949e"/></marker>
</defs><g id="viewport"><g id="frames"></g><g id="edges"></g><g id="nodes"></g></g></svg>
<div id="legend"></div><div id="hint">drag nodes · wheel zoom · drag background pan · click node/edge</div>
</div>
<aside id="panel"><h2>DETAIL</h2><div id="detail">Click a node or edge.</div></aside>
</div>
<script>
const GRAPH = __GRAPH__;
const KIND_COLOR = {namespace:"#58a6ff",package:"#3fb950",target:"#d29922",field:"#bc8cff",
  group:"#ff7b72",gate:"#f0883e",landmine:"#f85149",slot:"#8b949e",alias:"#79c0ff"};
const KIND_LABEL = {namespace:"命名空间",package:"包",target:"目标",field:"字段切片",group:"集合/组",
  gate:"门",landmine:"地雷",slot:"局部槽",alias:"别名"};
const EDGE_COLOR = {in:"#1f6feb",binds:"#3fb950",alias:"#79c0ff",field:"#bc8cff",member:"#ff7b72",
  gates:"#f0883e",allows:"#f0883e",confined:"#f85149",armed:"#f85149",bound:"#f85149"};
const svg=document.getElementById("svg"), viewport=document.getElementById("viewport");
const frames=document.getElementById("frames"), edgeLayer=document.getElementById("edges"), nodeLayer=document.getElementById("nodes");
const panel=document.getElementById("detail"), stats=document.getElementById("stats");
const nodes=GRAPH.objects.map((o,i)=>({...o,x:0,y:0,vx:0,vy:0,idx:i}));
const byId=new Map(nodes.map(n=>[n.id,n]));
const edges=GRAPH.morphisms.filter(e=>byId.has(e.source)&&byId.has(e.target));
const adj=new Map(nodes.map(n=>[n.id,{out:[],in:[]}]));
edges.forEach((e,i)=>{e.idx=i;adj.get(e.source).out.push(e);adj.get(e.target).in.push(e);});
stats.textContent=`${nodes.length} objects · ${edges.length} morphisms · ${GRAPH.namespace||"no namespace"}`;

function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function initLayout(){
  const rank={namespace:0,group:1,gate:1,landmine:2,package:3,field:4,alias:4,slot:5,target:6};
  const cols={}; nodes.forEach(n=>{const c=rank[n.kind]??4;(cols[c]=cols[c]||[]).push(n);});
  Object.keys(cols).forEach(c=>{cols[c].sort((a,b)=>a.label.localeCompare(b.label));});
  nodes.forEach(n=>{const c=rank[n.kind]??4;const arr=cols[c],row=arr.indexOf(n);n.x=110+c*175;n.y=90+row*82;});
}
initLayout();

const nodeEls=new Map();
function shapeFor(kind){
  if(kind==="namespace") return {w:170,h:52,rx:12};
  if(kind==="group"||kind==="gate"||kind==="landmine") return {w:160,h:48,rx:24};
  return {w:170,h:46,rx:8};
}
nodes.forEach(n=>{
  const g=document.createElementNS("http://www.w3.org/2000/svg","g");g.classList.add("node");g.dataset.id=n.id;
  const s=shapeFor(n.kind);n.w=s.w;n.h=s.h;
  const r=document.createElementNS("http://www.w3.org/2000/svg","rect");
  r.setAttribute("width",s.w);r.setAttribute("height",s.h);r.setAttribute("rx",s.rx);
  r.setAttribute("fill","#161b22");r.setAttribute("stroke",KIND_COLOR[n.kind]||"#8b949e");
  const t=document.createElementNS("http://www.w3.org/2000/svg","text");
  t.setAttribute("x",12);t.setAttribute("y",28);t.textContent=n.label.length>22?n.label.slice(0,21)+"…":n.label;
  g.append(r,t);nodeLayer.append(g);nodeEls.set(n.id,g);
});

const edgeEls=[];
edges.forEach((e,i)=>{
  const p=document.createElementNS("http://www.w3.org/2000/svg","path");p.classList.add("edge");p.dataset.idx=i;
  p.setAttribute("marker-end","url(#arrow)");p.setAttribute("stroke",EDGE_COLOR[e.kind]||"#484f58");
  const t=document.createElementNS("http://www.w3.org/2000/svg","text");t.classList.add("edge-label");t.textContent=e.label;
  edgeLayer.append(p,t);edgeEls.push({p,t,e});
});

function frameFor(kind,title,members,color){
  if(!members.length)return;
  const xs=members.map(n=>n.x),ys=members.map(n=>n.y);
  const x=Math.min(...xs)-24,y=Math.min(...ys)-28,w=Math.max(...xs)-x+190,h=Math.max(...ys)-y+80;
  const r=document.createElementNS("http://www.w3.org/2000/svg","rect");r.classList.add("frame");
  r.setAttribute("x",x);r.setAttribute("y",y);r.setAttribute("width",w);r.setAttribute("height",h);
  r.setAttribute("stroke",color);r.setAttribute("rx",14);
  const t=document.createElementNS("http://www.w3.org/2000/svg","text");t.setAttribute("x",x+10);t.setAttribute("y",y+18);t.textContent=title;t.setAttribute("fill",color);t.setAttribute("font-size","11");
  frames.append(r,t);
}

function draw(){
  frames.replaceChildren();
  const ns=GRAPH.namespace;if(ns){
    const m=nodes.filter(n=>n.kind==="package"||n.kind==="target"||n.kind==="field");
    frameFor("namespace",`set: !${ns}!/`,m,KIND_COLOR.namespace);
  }
  nodes.filter(n=>n.kind==="group").forEach(g=>{
    const m=edges.filter(e=>e.source===g.id&&e.kind==="member").map(e=>byId.get(e.target)).filter(Boolean);
    frameFor("group",`set: ${g.label}`,m,KIND_COLOR.group);
  });
  const pairCount=new Map();
  edges.forEach(e=>{const k=[e.source,e.target].sort().join("|");pairCount.set(k,(pairCount.get(k)||0)+1);});
  const pairSeen=new Map();
  edgeEls.forEach(({p,t,e})=>{
    const a=byId.get(e.source),b=byId.get(e.target);if(!a||!b)return;
    const k=[e.source,e.target].sort().join("|");const n=pairCount.get(k),s=pairSeen.get(k)||0;pairSeen.set(k,s+1);
    const dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1;const off=(s-(n-1)/2)*20;
    const mx=(a.x+b.x)/2-dy/d*off,my=(a.y+b.y)/2+dx/d*off;
    p.setAttribute("d",`M ${a.x+a.w/2} ${a.y+a.h/2} Q ${mx} ${my} ${b.x+b.w/2} ${b.y+b.h/2}`);
    t.setAttribute("x",mx);t.setAttribute("y",my-3);t.setAttribute("text-anchor","middle");
  });
  nodes.forEach(n=>{const g=nodeEls.get(n.id);g.setAttribute("transform",`translate(${n.x-n.w/2},${n.y-n.h/2})`);});
}

function applyTransform(){viewport.setAttribute("transform",`translate(${view.x},${view.y}) scale(${view.k})`);}
let view={x:0,y:0,k:1};
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
function fit(){if(!nodes.length){view={x:0,y:0,k:1};applyTransform();return;}const xs=nodes.map(n=>n.x),ys=nodes.map(n=>n.y);const x=Math.min(...xs)-200,y=Math.min(...ys)-160;
  const w=Math.max(...xs)-x+300,h=Math.max(...ys)-y+240;const r=svg.getBoundingClientRect();
  view.k=Math.min(1.4,Math.min(r.width/w,r.height/h));view.x=(r.width-w*view.k)/2-x*view.k;view.y=(r.height-h*view.k)/2-y*view.k;applyTransform();}
document.getElementById("fit").onclick=fit;document.getElementById("reset").onclick=()=>{initLayout();draw();fit();};
document.getElementById("labels").onclick=()=>document.body.classList.toggle("show-labels");

function select(id){
  document.querySelectorAll(".node").forEach(g=>g.classList.toggle("selected",g.dataset.id===id));
  edgeEls.forEach(({p,t,e})=>{const hl=e.source===id||e.target===id;p.classList.toggle("hl",hl);t.classList.toggle("hl",hl);p.classList.toggle("dim",!hl);t.classList.toggle("dim",!hl);});
  const n=byId.get(id);if(!n)return;
  const a=adj.get(id);
  panel.innerHTML=`<div class="label">${esc(n.label)}</div><div class="kind">${KIND_LABEL[n.kind]||n.kind} · ${esc(n.id)}</div>
  <h2>OUT</h2><ul>${a.out.length?a.out.map(e=>`<li><b>${esc(e.kind)}</b> → ${esc(e.target)}</li>`).join(""):"<li>none</li>"}</ul>
  <h2>IN</h2><ul>${a.in.length?a.in.map(e=>`<li><b>${esc(e.kind)}</b> ← ${esc(e.source)}</li>`).join(""):"<li>none</li>"}</ul>`;
}
nodeLayer.addEventListener("click",ev=>{const g=ev.target.closest(".node");if(g)select(g.dataset.id);});
edgeLayer.addEventListener("click",ev=>{const p=ev.target.closest(".edge");if(!p)return;const {e}=edgeEls[+p.dataset.idx];
  panel.innerHTML=`<div class="label">${esc(e.label)}</div><div class="kind">${esc(e.kind)}</div><h2>MORPHISM</h2><ul><li><b>source</b> ${esc(e.source)}</li><li><b>target</b> ${esc(e.target)}</li></ul>`;});
const legend=document.getElementById("legend");
Object.keys(KIND_LABEL).forEach(k=>{if(!nodes.some(n=>n.kind===k))return;const s=document.createElement("span");s.innerHTML=`<i class="dot" style="background:${KIND_COLOR[k]}"></i>${KIND_LABEL[k]}`;legend.append(s);});
draw();fit();
</script>
</body></html>
"""


def render_html(g) -> str:
    payload = json.dumps(g, ensure_ascii=False).replace("<", "\\u003c")
    return _HTML.replace("__GRAPH__", payload)
