"""Human-readable netlist for the !...! rewiring layer (the multimeter)."""
import re
from typing import List


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
