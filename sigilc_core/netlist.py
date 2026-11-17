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
