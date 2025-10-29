# geonodes_node2bndl_exporter.py — standalone BNDL v1.2 exporter (Geometry Nodes only)
# Paste into Blender's Text Editor and Run. It writes to a Text datablock named "BNDL_Export".
# Optional: set WRITE_FILE_PATH to also write a .bndl file to disk.

import bpy, re
from collections import defaultdict

# ============= CONFIG =============
WRITE_FILE_PATH = ""  # e.g. r"H:\Exports\my_tree.bndl" or "" to skip writing
TEXT_BLOCK_NAME = "BNDL_Export"
BNDL_VERSION = "1.2"
# ==================================

# ---------- Utilities ----------

# --- SetUser emission helpers (compare modifier overrides vs. GI defaults) ---
import math

def _ser_num(x):
    txt = f"{float(x):.9f}".rstrip("0").rstrip(".")
    if txt == "-0": txt = "0"
    return txt

_DB_SENTINELS = {
    "Material": ("❆", "❆"),
    "Object": ("⊞", "⊞"),
    "Collection": ("✸", "✸"),
    "Image": ("✷", "✷"),
    "Mesh": ("⧉", "⧉"),
    "Curve": ("𝒞", "𝒞"),
}

def _serialize_user_value(v):
    """Serialize a modifier-side value using the same visual rules as defaults."""
    # datablocks
    try:
        tname = type(v).__name__
        if tname in _DB_SENTINELS and hasattr(v, "name"):
            l, r = _DB_SENTINELS[tname]
            nm = v.name.replace(l, l + l)
            return f"{l}{nm}{r}"
    except Exception:
        pass
    # sequences (float/int)
    try:
        it = list(v)
        if all(isinstance(a, (int, float)) for a in it):
            return f"<{', '.join(_ser_num(a) for a in it)}>"
    except Exception:
        pass
    # bool
    if isinstance(v, bool):
        return "<True>" if v else "<False>"
    # number
    if isinstance(v, (int, float)):
        return f"<{_ser_num(v)}>"
    # string (we wrap defaults with ©…© in this exporter; mirror that)
    if isinstance(v, str):
        return f"©{v}©"
    return None

def _nearly_equal_nums(a, b, eps=1e-6):
    try:
        return abs(float(a) - float(b)) <= eps
    except Exception:
        return False

def _nearly_equal(a, b, eps=1e-6):
    try:
        la, lb = list(a), list(b)
        if len(la) == len(lb) and all(isinstance(x, (int,float)) for x in la+lb):
            return all(_nearly_equal_nums(x, y, eps) for x, y in zip(la, lb))
    except Exception:
        pass
    if isinstance(a, (int,float)) and isinstance(b, (int,float)):
        return _nearly_equal_nums(a, b, eps)
    return a == b

def _parse_gi_defaults_from_text(text):
    """Return ordered list of (display_name_with_optional_ordinal, serialized_value) for GI defaults."""
    rows = []
    lines = text.splitlines()
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i].rstrip()
        if ln.startswith("Set  [ Group Input #"):
            i += 1
            while i < n:
                kv = lines[i].rstrip()
                if not kv.startswith("§ "):
                    break
                m = re.match(r"^§\s+(.*?)\s+§\s+to\s+(.+)$", kv)
                if m:
                    rows.append((m.group(1), m.group(2)))
                i += 1
            continue
        i += 1
    return rows

def _iter_interface_input_items(ng):
    """Yield (index0, display_name, item) for INPUT interface sockets in order (Blender 4.x)."""
    iface = ng.interface
    idx = 0
    for it in getattr(iface, "items_tree", []):
        try:
            if getattr(it, "item_type", None) != 'SOCKET':
                continue
            if getattr(it, "in_out", None) != 'INPUT':
                continue
            disp = (getattr(it, "name", "") or "").strip()
            if not disp:
                disp = "input"
            yield idx, disp, it
            idx += 1
        except Exception:
            continue

def _read_mod_input_value(mod, it, idx0):
    """Try multiple keys to read the GN modifier's value for this interface item."""
    ident = getattr(it, "identifier", None) or getattr(it, "name", None)
    # mapping-like access
    try:
        if ident and ident in mod:
            return mod[ident]
    except Exception:
        pass
    # attribute
    try:
        if ident and hasattr(mod, ident):
            return getattr(mod, ident)
    except Exception:
        pass
    # common index-based fallbacks
    for key in (f"Input_{idx0+1}", f"Socket_{idx0+1}"):
        try:
            if key in mod:
                return mod[key]
        except Exception:
            pass
    return None

def _emit_setuser_block(ng, mod, existing_text):
    """Compare modifier values to GI defaults; emit SetUser block if any differ."""
    if ng is None or mod is None:
        return ""
    # 1) Gather the GI defaults already emitted (so names/ordinals match)
    gi_rows = _parse_gi_defaults_from_text(existing_text)
    if not gi_rows:
        return ""

    # 2) Build base-name → [(idx0, item)] map from the interface
    base_map = {}
    for idx0, disp, it in _iter_interface_input_items(ng):
        base_map.setdefault(disp, []).append((idx0, it))

    # 3) Walk defaults in the same order and probe the modifier for overrides
    overrides = []
    for disp_with_ord, def_ser in gi_rows:
        m = re.match(r"^(.*?)(?:\[(\d+)\])?$", disp_with_ord)
        base = m.group(1) if m else disp_with_ord
        want_ord = int(m.group(2)) if (m and m.group(2)) else 1
        lst = base_map.get(base, [])
        if not lst or want_ord > len(lst):
            continue
        idx0, it = lst[want_ord-1]
        user_raw = _read_mod_input_value(mod, it, idx0)
        if user_raw is None:
            continue
        user_ser = _serialize_user_value(user_raw)
        if user_ser is None:
            continue
        # quick textual equality
        if user_ser == def_ser:
            continue
        # approximate numeric/sequence equality (unwrap def_ser if it looks numeric)
        eq_val = False
        if def_ser.startswith("<") and def_ser.endswith(">"):
            try:
                parts = [p.strip() for p in def_ser[1:-1].split(",")]
                nums = [float(p) for p in parts if p]
                try:
                    ul = list(user_raw)
                except Exception:
                    ul = [user_raw]
                if len(nums) == len(ul):
                    eq_val = all(_nearly_equal_nums(a, b) for a, b in zip(nums, ul))
            except Exception:
                eq_val = False
        if eq_val:
            continue
        overrides.append((disp_with_ord, user_ser))

    if not overrides:
        return ""

    # 4) Emit new block
    out = []
    out.append("")
    out.append("# === USER OVERRIDES ===")
    out.append("SetUser  [ Group Input #1 ]:")
    for k, v in overrides:
        out.append(f"§ {k} § to {v}")
    out.append("")
    return "\n".join(out)

# --- User override (modifier) helpers for GI sockets ---

def _bndl_serialize_scalar(v):
    # ints/floats → <n>, bool → <True>/<False>, str → ©…©
    if isinstance(v, bool):
        return f"<{v}>"
    if isinstance(v, (int, float)):
        # Avoid scientific; keep stable decimals
        txt = f"{float(v):.9f}".rstrip("0").rstrip(".")
        if txt == "-0": txt = "0"
        return f"<{txt}>"
    if isinstance(v, str):
        # Wrap strings with the same sentinel you already use in the spec
        return f"©{v}©"
    return None  # caller decides

def _bndl_serialize_seq(v):
    # tuple/list/Vector/Color → <a, b, c(, d)>
    try:
        it = list(v)
    except Exception:
        return None
    scal = []
    for x in it:
        if isinstance(x, bool):
            scal.append(f"{x}")
        elif isinstance(x, (int, float)):
            txt = f"{float(x):.9f}".rstrip("0").rstrip(".")
            if txt == "-0": txt = "0"
            scal.append(txt)
        else:
            return None
    return f"<{', '.join(scal)}>"

# Datablock sentinels (match your v1.2 spec)
_DB_SENTINELS = {
    "Material": ("❆", "❆"),
    "Object": ("⊞", "⊞"),
    "Collection": ("✸", "✸"),
    "Image": ("✷", "✷"),
    "Mesh": ("⧉", "⧉"),
    "Curve": ("𝒞", "𝒞"),
}

def _bndl_serialize_datablock(v):
    # name only, wrapped in the correct sentinel pair; unknowns → None
    try:
        if v is None:
            return None
        id_type = type(v).__name__
        for k, (lft, rgt) in _DB_SENTINELS.items():
            if id_type == k:
                nm = getattr(v, "name", "")
                return f"{lft}{nm}{rgt}"
    except Exception:
        pass
    return None

def _serialize_for_bndl_value(v):
    """Try datablock → sequence → scalar; return serialized string or None."""
    s = _bndl_serialize_datablock(v)
    if s is not None: return s
    s = _bndl_serialize_seq(v)
    if s is not None: return s
    s = _bndl_serialize_scalar(v)
    if s is not None: return s
    return None

def _nearly_equal(a, b, eps=1e-6):
    try:
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)) and len(a) == len(b):
            return all(_nearly_equal(x, y, eps) for x, y in zip(a, b))
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(float(a) - float(b)) <= eps
        return a == b
    except Exception:
        return False

def _parse_defaults_from_bndl_text(text):
    """Extract the existing GI defaults block we already emitted:
       Returns (gi_block_present: bool, {display_name: serialized_value})"""
    gi_map = {}
    found = False
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i].rstrip()
        if ln.startswith("Set  [ Group Input #"):
            found = True
            i += 1
            while i < len(lines):
                kv = lines[i].rstrip()
                if not kv.startswith("§ "):  # end of block
                    break
                # § <Name> § to <value>
                m = re.match(r"^§\s+(.*?)\s+§\s+to\s+(.+)$", kv)
                if m:
                    k = m.group(1)
                    v = m.group(2)
                    gi_map[k] = v
                i += 1
            continue
        i += 1
    return found, gi_map

def _iter_gi_interface_inputs(ng):
    """Yield (display_name_with_ordinal, item) for INPUT interface sockets in order."""
    iface = ng.interface
    # Blender 4.x: items_tree includes panels and sockets. Filter to INPUT sockets.
    for it in getattr(iface, "items_tree", []):
        try:
            # Sockets have .item_type == 'SOCKET' and .in_out in {'INPUT','OUTPUT'}
            if getattr(it, "item_type", None) != 'SOCKET':
                continue
            if getattr(it, "in_out", None) != 'INPUT':
                continue
            # Display name as shown in UI
            disp = getattr(it, "name", "")
            # If duplicates exist, exporter already adds [n] ordinals to display names in BNDL.
            # We cannot know ordinals here, so we trust the defaults map to anchor names.
            yield disp, it
        except Exception:
            continue

def _read_iface_default(it):
    """Read the interface socket default. Supports scalars/sequences/bool/enums."""
    # Many GN sockets expose .default_value directly on the interface item in 4.x.
    dv = None
    # Try common attributes
    for attr in ("default_value", "value", "default_float", "default_int", "default_boolean"):
        if hasattr(it, attr):
            try:
                dv = getattr(it, attr)
                break
            except Exception:
                pass
    return dv

def _read_modifier_value_for_item(mod, it, index_zero_based):
    """Best-effort: fetch the user override stored on the Geometry Nodes modifier."""
    # Preferred: by stable identifier (if Blender exposes it)
    ident = getattr(it, "identifier", None) or getattr(it, "name", None)
    # Various access patterns across Blender 4.x minor versions:
    # 1) Custom prop-like mapping
    try:
        if ident and ident in mod:
            return mod[ident]
    except Exception:
        pass
    # 2) Attribute
    try:
        if ident and hasattr(mod, ident):
            return getattr(mod, ident)
    except Exception:
        pass
    # 3) Index-based fallbacks commonly seen in the UI: "Input_1" / "Socket_1"
    try:
        for keypat in (f"Input_{index_zero_based+1}", f"Socket_{index_zero_based+1}"):
            if keypat in mod:
                return mod[keypat]
    except Exception:
        pass
    return None

ALIASES = {
    "GeometryNodeGroupInput":  "Group Input",
    "GeometryNodeGroupOutput": "Group Output",
    "NodeGroupInput":          "Group Input",
    "NodeGroupOutput":         "Group Output",
    "GeometryNodeGroup":       "Group",
}

DB_SENTINELS = {
    "Material":   "❆",
    "Object":     "⊞",
    "Collection": "✸",
    "Image":      "✷",
    "Mesh":       "⧉",
    "Curve":      "𝒞",
}

def _escape_with_mark(name: str, mark: str) -> str:
    """Escape any sentinel found inside a datablock name by doubling it and warn."""
    if mark in name:
        print(f"[BNDL] Warning: datablock name contains sentinel {mark} → escaping in output: {name!r}")
    return name.replace(mark, mark + mark)

def norm_type(n):
    """Readable BNDL 'type' for a Blender node."""
    if n.bl_idname in ALIASES:
        return ALIASES[n.bl_idname]
    label = (getattr(n, "bl_label", "") or "").strip()
    if label:
        return label
    return (n.bl_idname
            .replace("GeometryNode","")
            .replace("FunctionNode","")
            .replace("ShaderNode",""))

def is_reroute(n):
    return n.bl_idname in {"NodeReroute", "GeometryNodeReroute"}

def is_frame(n):
    return n.bl_idname == "NodeFrame"

def _enum_label_safe(prop, enum_identifier):
    """Return UI label for enum identifier, safely across 4.x."""
    try:
        item = prop.enum_items[enum_identifier]
        return item.name
    except Exception:
        pass
    try:
        for it in prop.enum_items:
            if it.identifier == enum_identifier:
                return it.name
    except Exception:
        pass
    return ""

def ui_enum_label(n, prop_id):
    try:
        prop = n.bl_rna.properties[prop_id]
        ident = getattr(n, prop_id)
        return _enum_label_safe(prop, ident)
    except Exception:
        return ""

def node_variant_label(n):
    t = n.bl_idname
    if t in {"FunctionNodeMath", "ShaderNodeMath",
             "FunctionNodeVectorMath", "ShaderNodeVectorMath",
             "FunctionNodeBooleanMath", "ShaderNodeBooleanMath",
             "FunctionNodeCompare"}:
        return ui_enum_label(n, "operation")
    if t in {"FunctionNodeMapRange", "ShaderNodeMapRange"}:
        return ui_enum_label(n, "data_type")
    return ""

def _incoming_link_for(sock):
    nt = sock.node.id_data
    for ln in nt.links:
        if ln.to_socket == sock:
            return ln
    return None

def resolve_source_socket(from_sock):
    s = from_sock
    while is_reroute(s.node):
        ln = _incoming_link_for(s.node.inputs[0])
        if not ln:
            break
        s = ln.from_socket
    return s

def resolve_dest_socket(to_sock):
    s = to_sock
    while is_reroute(s.node):
        outs = [ln for ln in s.node.id_data.links if ln.from_socket == s.node.outputs[0]]
        if not outs:
            break
        s = outs[0].to_socket
    return s

def socket_position(sock):
    """Return zero-based position of this socket within its node's inputs/outputs (4.x: no .index).
    Use RNA pointer identity, not Python object identity (wrappers can differ)."""
    col = sock.node.outputs if getattr(sock, "is_output", False) else sock.node.inputs
    # Prefer RNA pointer identity
    try:
        sp = sock.as_pointer()
    except Exception:
        sp = None
    if sp is not None:
        for i, s in enumerate(col):
            try:
                if s.as_pointer() == sp:
                    return i
            except Exception:
                continue
    # Fallback to object identity (best-effort)
    for i, s in enumerate(col):
        if s is sock:
            return i
    return -1

def iter_links_collapsed(ng):
    """Yield (from_socket, to_socket) between non-reroute/frame nodes, collapsing reroutes."""
    seen = set()
    for ln in ng.links:
        dst = resolve_dest_socket(ln.to_socket)
        src = resolve_source_socket(ln.from_socket)
        if is_reroute(src.node) or is_reroute(dst.node) or is_frame(src.node) or is_frame(dst.node):
            continue
        # Use socket RNA pointers for dedupe; this distinguishes multiple links into a multi-input
        try:
            key = (src.as_pointer(), dst.as_pointer())
        except Exception:
            # Fallback to node pointers + computed positions
            src_i = socket_position(src)
            dst_i = socket_position(dst)
            key = (src.node.as_pointer(), src_i, dst.node.as_pointer(), dst_i)
        if key in seen:
            continue
        seen.add(key)
        yield (src, dst)


def _serialize_datablock(v):
    try:
        if isinstance(v, bpy.types.Material):
            m = DB_SENTINELS["Material"];   return f"{m}{_escape_with_mark(v.name, m)}{m}"
        if isinstance(v, bpy.types.Object):
            m = DB_SENTINELS["Object"];     return f"{m}{_escape_with_mark(v.name, m)}{m}"
        if isinstance(v, bpy.types.Collection):
            m = DB_SENTINELS["Collection"]; return f"{m}{_escape_with_mark(v.name, m)}{m}"
        if isinstance(v, bpy.types.Image):
            m = DB_SENTINELS["Image"];      return f"{m}{_escape_with_mark(v.name, m)}{m}"
        if isinstance(v, bpy.types.Mesh):
            m = DB_SENTINELS["Mesh"];       return f"{m}{_escape_with_mark(v.name, m)}{m}"
        if isinstance(v, bpy.types.Curve):
            m = DB_SENTINELS["Curve"];      return f"{m}{_escape_with_mark(v.name, m)}{m}"
    except Exception:
        pass
    return None

def serialize_default(sock):
    """Best-effort sentinel encoding for default values (unlinked inputs)."""
    if not hasattr(sock, "default_value"):
        return None
    v = sock.default_value
    # Datablocks
    db = _serialize_datablock(v)
    if db is not None:
        return db
    # Bool
    if isinstance(v, bool):
        return "<True>" if v else "<False>"
    # Number
    if isinstance(v, (int, float)):
        return f"<{v}>"
    # Vector/Color (3 or 4 floats)
    try:
        if hasattr(v, "__len__"):
            seq = list(v)
            if len(seq) in (3,4) and all(isinstance(x, (int,float)) for x in seq):
                inside = ", ".join(str(float(x)) for x in seq)
                return f"<{inside}>"
    except Exception:
        pass
    # String
    if isinstance(v, str):
        return f"©{v}©"
    return None

def _is_meaningful_serialized_default(txt: str) -> bool:
    """Heuristic to avoid spamming Set lines with 'zero/empty' values."""
    if txt is None:
        return False
    s = str(txt).strip()
    # Numbers / common zero vectors/colors
    if s in {"<0>", "<0.0>", "<0.000000>", "<0, 0, 0>", "<0.0, 0.0, 0.0>", "<0.0, 0.0, 0.0, 0.0>"}:
        return False
    # Booleans
    if s in {"<False>"}:
        return False
    # Empty string marker (string defaults are wrapped with ©…©)
    if s == "©©":
        return False
    return True

def sockets_dup_map(sockets):
    """Return dict of base name -> [ordinals] for duplicated names (1-based)."""
    m = defaultdict(list)
    for i, s in enumerate(sockets):
        nm = (s.name or "").strip()
        m[nm].append(i+1)
    return {k:v for k,v in m.items() if len(v) > 1}

def _display_names_for_sockets(sockets, is_inputs):
    """Return (list_of_display_names, per_socket_map) using duplicate ordinals and ○/⦿ aliases for unnamed."""
    base_alias = "input" if is_inputs else "output"
    counts = defaultdict(int)
    names = []
    per = {}
    for s in sockets:
        nm = (getattr(s, "name", "") or "").strip() or base_alias
        counts[nm] += 1
        disp = nm if counts[nm] == 1 else f"{nm}[{counts[nm]}]"
        names.append(disp)
        per[s] = disp
    return names, per

def declare_ports(kind, node_str, sockets, *, include_sock_meta=False):
    """Emit Declare Inputs/Outputs lines with deterministic duplicate ordinals and unnamed aliases."""
    if not sockets:
        return []
    is_inputs = (kind == "Inputs")
    disp_list, per = _display_names_for_sockets(sockets, is_inputs)
    parts = []
    for s, disp in zip(sockets, disp_list):
        badge = "⦿" if is_inputs else "○"
        seg = f"{badge} {disp}"
        if include_sock_meta and (getattr(s, "name", "") or "").strip() != disp:
            seg += f" ; sock=<{getattr(s, 'name', '') or ''}>"
        parts.append(seg)
    line = f"Declare {kind:<7} {node_str} : " + " , ".join(parts)
    out = [line]
    return out

def _is_meaningful_serialized_default(txt: str) -> bool:
    """Heuristic to avoid spamming Set lines with 'zero/empty' values."""
    if txt is None:
        return False
    s = str(txt).strip()
    # Numbers / common zero vectors/colors
    if s in {"<0>", "<0.0>", "<0.000000>", "<0, 0, 0>", "<0.0, 0.0, 0.0>", "<0.0, 0.0, 0.0, 0.0>"}:
        return False
    # Booleans
    if s in {"<False>"}:
        return False
    # Empty string marker (string defaults are wrapped with ©…©)
    if s == "©©":
        return False
    return True


def link_is_field(fr, to):
    """Visual heuristic only: use dotted links unless clearly geometry/object/material."""
    non_field = {"GEOMETRY","OBJECT","MATERIAL"}
    ft = (fr.type or "").upper()
    tt = (to.type or "").upper()
    return not (ft in non_field or tt in non_field)

def is_index_switch(n):
    return n.bl_idname == "GeometryNodeIndexSwitch" or getattr(n, "bl_label", "") == "Index Switch"

def export_index_switch_adjust(n, typ, nid):
    """Emit case count and case-label renames for Index Switch."""
    lines = []
    items = getattr(n, "index_switch_items", None)
    if items is not None:
        count = len(items)
        lines.append(f"Adjust  [ {typ} #{nid} ]  # Cases # to <{count}>")
        for i, it in enumerate(items, start=1):
            nm = (getattr(it, "name", "") or "").strip()
            if nm:
                lines.append(f"Rename  [ {typ} #{nid} ] ⦿ Case {i} to ~ {nm} ~")
    else:
        case_socks = [s for s in n.inputs if s.name.lower().startswith("case ")]
        if case_socks:
            lines.append(f"Adjust  [ {typ} #{nid} ]  # Cases # to <{len(case_socks)}>")
    return lines

def collect_node_props(n):
    """Collect (UI name, UI value) for node-level properties we want to serialize.
    - ENUM  → write UI label   as ©Label©
    - BOOLEAN → write <True>/<False>
    - POINTER (Object/Material/Collection/Image/Mesh/Curve) → write a sentinel-wrapped name
      using _serialize_datablock so the replay can recreate or proxy the target.
    """
    out = []
    # purely visual/readonly properties to skip
    skip = {
        "name","label","parent","location","width","height","hide","mute","select",
        "show_options","use_custom_color","color"
    }

    for p in n.bl_rna.properties:
        if p.is_readonly or p.identifier in skip:
            continue
        try:
            # 1) POINTER datablocks (this is what fixes Object Info, Set Material, etc.)
            if getattr(p, "type", "") == "POINTER" and hasattr(p, "fixed_type"):
                val = getattr(n, p.identifier, None)
                if val is None:
                    continue
                sent = _serialize_datablock(val)
                if sent is not None:
                    out.append((p.name, sent))
                    continue  # done with this prop

            # 2) ENUM → UI label
            if p.type == 'ENUM':
                # store UI label so replay can map it back to identifier
                from_name = ""
                try:
                    ident = getattr(n, p.identifier)
                    from_name = _enum_label_safe(p, ident)
                except Exception:
                    pass
                if from_name:
                    out.append((p.name, f"©{from_name}©"))
                continue

            # 3) BOOLEAN
            if p.type == 'BOOLEAN':
                val = bool(getattr(n, p.identifier))
                out.append((p.name, "<True>" if val else "<False>"))
                continue

            # 4) Numeric (INT/FLOAT) — only when the node has no inputs (e.g., Integer/Float input nodes)
            if p.type in {'INT', 'FLOAT'} and len(getattr(n, "inputs", ())) == 0:
                try:
                    val = getattr(n, p.identifier)
                    out.append((p.name, f"<{val}>"))
                    continue
                except Exception:
                    pass


            # (We deliberately skip numeric RNA props here; numeric defaults should be covered
            # by socket default serialization, which is layout-accurate for nodes.)
        except Exception:
            pass

    return out


# ---------- Core Exporter ----------

class _TreeExport:
    def __init__(self, node_tree):
        self.nt = node_tree
        self.lines_groups = []
        self.lines_top = []
        self._visited_groups = set()

    def _enumerate_nodes(self, nodes):
        """Per-tree numbering: type -> running count; returns dict node -> (typ, #id)."""
        counts = defaultdict(int)
        idx = {}
        for n in nodes:
            if is_reroute(n) or is_frame(n):
                continue
            typ = norm_type(n)
            counts[typ] += 1
            idx[n] = (typ, counts[typ])
        return idx

    def _export_group_block(self, ng):
        gname = ng.name
        if gname in self._visited_groups:
            return
        self._visited_groups.add(gname)

        nodes = [n for n in ng.nodes if not is_reroute(n) and not is_frame(n)]
        enum = self._enumerate_nodes(nodes)

        out = [f"START GROUP NAMED {gname}"]

        # Create + Rename + Index Switch Adjust
        for n in nodes:
            typ, nid = enum[n]
            if n.bl_idname == "GeometryNodeGroup":
                ref_name = n.node_tree.name if n.node_tree else "Unnamed"
                out.append(f"Create  [ Group |  | ] ~ {ref_name} ~ #{nid} ; type=GeometryNodeGroup")
            else:
                variant = node_variant_label(n)
                friendly = (n.label or "").strip()
                out.append(f"Create  [ {typ} | {variant or '—'} | ] ~ {friendly} ~ #{nid} ; type={n.bl_idname}")
            if n.label:
                out.append(f"Rename  [ {typ} #{nid} ] to ~ {n.label} ~")
            if is_index_switch(n):
                out.extend(export_index_switch_adjust(n, typ, nid))

        # --- v1.3 test: synthesize reroutes for *unlinked* GI outputs (group scope) ---
        gi_placeholder_links = []   # (gi_id, label, reroute_id) in group scope
        try:
            gi_node = None
            gi_id = None
            for _n in nodes:
                if _n.bl_idname == "NodeGroupInput":
                    gi_node = _n
                    gi_id = enum[_n][1]
                    break
            if gi_node is not None and gi_id is not None:
                rr_auto = 0
                gi_items = [item for item in ng.interface.items_tree
                            if getattr(item, "item_type", "") == 'SOCKET' and item.in_out == 'INPUT']
                for idx, it in enumerate(gi_items):
                    label = (getattr(it, "name", "") or "").strip()
                    if not label:
                        continue
                    s = gi_node.outputs[idx]
                    if not any(lnk.from_socket == s for lnk in ng.links):
                        rr_auto += 1
                        out.append(f"Create  [ Reroute | — | ] ~  ~ #{rr_auto} ; type=NodeReroute")
                        gi_placeholder_links.append((gi_id, label, rr_auto))
        except Exception:
            pass
        # --------------------------------------------------------------------------------

        # Declare ports
        for n in nodes:
            typ, nid = enum[n]
            node_str = f"[ {typ} #{nid} ]"

            if typ == "Group Input":
                gi = [item for item in ng.interface.items_tree
                    if getattr(item, "item_type", "") == 'SOCKET' and item.in_out == 'INPUT']

                out.extend(declare_ports("Outputs", node_str, gi))
                # --- v1.3: Expose GI outputs that are unlinked or only dead-end via reroutes ---
                try:
                    nt = self.nt
                    names, _ = _display_names_for_sockets(n.outputs, False)

                    def _gi_dead_end(sock):
                        # BFS forward through reroutes; if any path reaches a non-reroute consumer, NOT dead-end.
                        frontier, seen, steps = [sock], set(), 0
                        while frontier and steps < 1024:
                            s = frontier.pop()
                            steps += 1
                            sid = getattr(s, "as_pointer", lambda: id(s))()
                            if sid in seen:
                                continue
                            seen.add(sid)
                            outs = [ln for ln in nt.links if ln.from_socket == s]
                            if not outs:
                                return True  # no consumers at all
                            for lnk in outs:
                                nd = lnk.to_node
                                if is_reroute(nd):
                                    try:
                                        frontier.append(nd.outputs[0])
                                    except Exception:
                                        return True  # broken reroute behaves like dead-end
                                else:
                                    return False  # real consumer found
                        return True  # frontier exhausted without finding a real consumer

                    for s, label in zip(n.outputs, names):
                        if _gi_dead_end(s):
                            out.append(f"Expose  [ {typ} #{nid} ] ○ {label}")
                except Exception:
                    pass
                # -------------------------------------------------------------------------------


                # --- NEW: also export interface default values for Group Input sockets ---

                # We reuse serialize_default(...) by wrapping each interface item in a tiny shim
                # exposing .default_value so the serializer can do datablock sentinels etc.
                kv = []
                for it in gi:
                    try:
                        # Interface items have names shown in the UI; that is the display label we already declare.
                        disp = (getattr(it, "name", "") or "").strip()
                        if not disp:
                            continue
                        # Some interface items expose .default_value directly. If not, skip.
                        if not hasattr(it, "default_value"):
                            continue
                        class _Shim:
                            def __init__(self, dv):
                                self.default_value = dv
                        sv = serialize_default(_Shim(getattr(it, "default_value")))
                        if sv is not None:
                            kv.append((disp, sv))
                    except Exception:
                        pass
                if kv:
                    out.append(f"Set  {node_str}:")
                    for k, v in kv:
                        out.append(f"§ {k} § to {v}")

                # --- NEW: interface meta for Group Input (per-group) ---
                # --- NEW: interface meta for Group Input (per-group) ---
                meta_lines = []
                for it in gi:
                    try:
                        disp = (getattr(it, "name", "") or "").strip()
                        if not disp:
                            continue

                        # Description
                        desc = (getattr(it, "description", "") or "").strip()
                        if desc:
                            meta_lines.append(f"§ {disp}::Description § to ~{desc.replace('~','-')}~")

                        # Helper to append only-when-present
                        def _emit(suffix, val, *, quote=False):
                            if val is None:
                                return
                            if quote:
                                meta_lines.append(f"§ {disp}::{suffix} § to {repr(val)}")
                            else:
                                if isinstance(val, bool):
                                    meta_lines.append(f"§ {disp}::{suffix} § to " + ("<True>" if val else "<False>"))
                                elif isinstance(val, (int, float)):
                                    meta_lines.append(f"§ {disp}::{suffix} § to <{val}>")
                                else:
                                    meta_lines.append(f"§ {disp}::{suffix} § to {val}")

                        # Exact interface socket idname when available (preferred)
                        stype = None
                        if hasattr(it, "bl_socket_idname"):
                            stype = getattr(it, "bl_socket_idname", None)
                        elif hasattr(it, "socket_type"):
                            stype = getattr(it, "socket_type", None)
                        _emit("Socket Type", stype, quote=True)

                        # Structure (FIELD / VALUE)
                        if hasattr(it, "structure_type"):
                            _emit("Structure Type", getattr(it, "structure_type"), quote=True)

                        # Limits / UI
                        if hasattr(it, "subtype"):
                            _emit("Subtype", getattr(it, "subtype"), quote=True)
                        if hasattr(it, "min_value"):
                            _emit("Min", getattr(it, "min_value"))
                        if hasattr(it, "max_value"):
                            _emit("Max", getattr(it, "max_value"))
                        if hasattr(it, "hide_value"):
                            _emit("Hide Value", bool(getattr(it, "hide_value")))
                        if hasattr(it, "hide_in_modifier"):
                            _emit("Hide in Modifier", bool(getattr(it, "hide_in_modifier")))
                        if hasattr(it, "default_attribute"):
                            _emit("Default Attribute", getattr(it, "default_attribute"), quote=True)
                    except Exception:
                        pass

                if meta_lines:
                    out.append(f"Set  {node_str}:")
                    out.extend(meta_lines)


                if meta_lines:
                    out.append(f"Set  {node_str}:")
                    out.extend(meta_lines)



            elif typ == "Group Output":
                go = [item for item in ng.interface.items_tree
                      if getattr(item, "item_type", "") == 'SOCKET' and item.in_out == 'OUTPUT']
                out.extend(declare_ports("Inputs", node_str, go))
                # --- v1.3: Expose GO inputs that are unlinked or only dead-end via reroutes ---
                try:
                    nt = self.nt
                    names, _ = _display_names_for_sockets(n.inputs, True)

                    def _go_dead_end(sock):
                        # Walk backward through reroutes; if no real source, it’s dead-end.
                        steps = 0
                        s = sock
                        while steps < 1024:
                            steps += 1
                            ln = _incoming_link_for(s)
                            if not ln:
                                return True  # no source at all
                            nd = ln.from_node
                            if is_reroute(nd):
                                try:
                                    s = nd.inputs[0]
                                except Exception:
                                    return True
                                continue
                            return False  # real source exists
                        return True

                    for s, label in zip(n.inputs, names):
                        if _go_dead_end(s):
                            out.append(f"Expose  [ {typ} #{nid} ] ⦿ {label}")
                except Exception:
                    pass
                # -------------------------------------------------------------------------------


            else:
                out.extend(declare_ports("Inputs",  node_str, n.inputs))
                out.extend(declare_ports("Outputs", node_str, n.outputs))

        # --------------------------------------------------------------------------------
        # Set (unlinked defaults + enums/toggles) — use display names so duplicates get [2], [3], …
        for n in nodes:
            kv = []

            # 1) Unlinked INPUT socket defaults
            in_names, _ = _display_names_for_sockets(n.inputs, True)
            for s, disp in zip(n.inputs, in_names):
                if s.is_linked:
                    continue
                sv = serialize_default(s)
                if _is_meaningful_serialized_default(sv):
                    kv.append((disp, sv))

            # 2) OUTPUT socket defaults (e.g. 'Value' on a Value node)
            out_names, _ = _display_names_for_sockets(n.outputs, False)
            for s, disp in zip(n.outputs, out_names):
                if not hasattr(s, "default_value"):
                    continue
                sv = serialize_default(s)
                if _is_meaningful_serialized_default(sv):
                    kv.append((disp, sv))

            # 3) Node RNA props (enums/toggles/number props you already collect)
            kv.extend(collect_node_props(n))

            if kv:
                typ, nid = enum[n]
                out.append(f"Set  [ {typ} #{nid} ]:")
                for k, v in kv:
                    out.append(f"§ {k} § to {v}")


        # Connect synthesized reroutes before normal links
        if 'gi_placeholder_links' in locals():
            for _gi_id, _label, _rr_id in gi_placeholder_links:
                out.append(f"Connect  [ Group Input #{_gi_id} ] ○ {_label}  to  [ Reroute #{_rr_id} ] ⦿ Input")


        # Links (reroute-collapsed)
        for fr, to in iter_links_collapsed(ng):
            nf, nt = fr.node, to.node
            if nf not in enum or nt not in enum:
                continue
            tf, idf = enum[nf]
            tt, idt = enum[nt]
            dotted = "Connect⋯" if link_is_field(fr, to) else "Connect"
            in_names, _ = _display_names_for_sockets(nt.inputs, True)
            out_names, _= _display_names_for_sockets(nf.outputs, False)
            fi = socket_position(fr)
            ti = socket_position(to)
            onm = out_names[fi] if 0 <= fi < len(out_names) else (fr.name or "output")
            inm = in_names[ti]  if 0 <= ti < len(in_names)  else (to.name or "input")
            out.append(f"{dotted}  [ {tf} #{idf} ] ○ {onm}  to  [ {tt} #{idt} ] ⦿ {inm}")

        # PairZone (Simulation / Repeat)
        self._emit_zone_pairs(ng, enum, out)
        out.append(f"END GROUP NAMED {gname}")
        self.lines_groups.extend(out)

        # Recurse into nested groups
        for n in nodes:
            if n.bl_idname == "GeometryNodeGroup" and n.node_tree:
                self._export_group_block(n.node_tree)

    def _export_top(self):
        nodes = [n for n in self.nt.nodes if not is_reroute(n) and not is_frame(n)]
        enum = self._enumerate_nodes(nodes)
        out = []

        # Create + Rename + Index Switch Adjust
        for n in nodes:
            typ, nid = enum[n]
            if n.bl_idname == "GeometryNodeGroup":
                ref_name = n.node_tree.name if n.node_tree else "Unnamed"
                out.append(f"Create  [ Group |  | ] ~ {ref_name} ~ #{nid} ; type=GeometryNodeGroup")
            else:
                variant = node_variant_label(n)
                friendly = (n.label or "").strip()
                out.append(f"Create  [ {typ} | {variant or '—'} | ] ~ {friendly} ~ #{nid} ; type={n.bl_idname}")
            if n.label:
                out.append(f"Rename  [ {typ} #{nid} ] to ~ {n.label} ~")
            if is_index_switch(n):
                out.extend(export_index_switch_adjust(n, typ, nid))

        # Declare ports

        # --- v1.3 test: synthesize reroutes for *unlinked* GI outputs so they surface in replay ---
        gi_placeholder_links = []   # (gi_id, label, reroute_id)
        # Create the reroutes right after the initial Create pass, so they have IDs
        try:
            # Find the Group Input node and its enum id
            gi_node = None
            gi_id = None
            for _n in nodes:
                if _n.bl_idname == "NodeGroupInput":
                    gi_node = _n
                    gi_id = enum[_n][1]
                    break
            if gi_node is not None and gi_id is not None:
                # Number our synthetic reroutes locally (Reroute #1, #2, …)
                rr_auto = 0
                # use interface items for labels; skip blanks
                gi_items = [item for item in self.nt.interface.items_tree
                            if getattr(item, "item_type", "") == 'SOCKET' and item.in_out == 'INPUT']
                for idx, it in enumerate(gi_items):
                    label = (getattr(it, "name", "") or "").strip()
                    if not label:
                        continue
                    s = gi_node.outputs[idx]
                    # Only sockets with *no* outgoing links
                    if not any(lnk.from_socket == s for lnk in self.nt.links):
                        rr_auto += 1
                        out.append(f"Create  [ Reroute | — | ] ~  ~ #{rr_auto} ; type=NodeReroute")
                        gi_placeholder_links.append((gi_id, label, rr_auto))
        except Exception:
            pass
        # -------------------------------------------------------------------------------------------

        for n in nodes:
            typ, nid = enum[n]
            node_str = f"[ {typ} #{nid} ]"

            if typ == "Group Input":
                gi = [item for item in self.nt.interface.items_tree
                      if getattr(item, "item_type", "") == 'SOCKET' and item.in_out == 'INPUT']
                out.extend(declare_ports("Outputs", node_str, gi))

                # --- NEW: top-level Group Input defaults ---
                kv = []
                for it in gi:
                    try:
                        disp = (getattr(it, "name", "") or "").strip()
                        if not disp:
                            continue
                        if not hasattr(it, "default_value"):
                            continue
                        class _Shim:
                            def __init__(self, dv): self.default_value = dv
                        sv = serialize_default(_Shim(getattr(it, "default_value")))
                        if sv is not None:
                            kv.append((disp, sv))
                    except Exception:
                        pass
                if kv:
                    out.append(f"Set  {node_str}:")
                    for k, v in kv:
                        out.append(f"§ {k} § to {v}")

                # --- NEW: top-level Group Input meta (descriptions + flags/limits/attrs) ---
                meta_lines = []
                for it in gi:
                    try:
                        disp = (getattr(it, "name", "") or "").strip()
                        if not disp:
                            continue

                        # Description
                        desc = (getattr(it, "description", "") or "").strip()
                        if desc:
                            meta_lines.append(f"§ {disp}::Description § to ~{desc.replace('~','-')}~")

                        # Helper to append only-when-present
                        def _emit(suffix, val, *, quote=False):
                            if val is None:
                                return
                            if quote:
                                meta_lines.append(f"§ {disp}::{suffix} § to {repr(val)}")
                            else:
                                if isinstance(val, bool):
                                    meta_lines.append(f"§ {disp}::{suffix} § to " + ("<True>" if val else "<False>"))
                                elif isinstance(val, (int, float)):
                                    meta_lines.append(f"§ {disp}::{suffix} § to <{val}>")
                                else:
                                    meta_lines.append(f"§ {disp}::{suffix} § to {val}")

                        # Exact interface socket idname when available (preferred)
                        stype = None
                        if hasattr(it, "bl_socket_idname"):
                            stype = getattr(it, "bl_socket_idname", None)
                        elif hasattr(it, "socket_type"):
                            stype = getattr(it, "socket_type", None)
                        _emit("Socket Type", stype, quote=True)

                        # Structure (FIELD / VALUE)
                        if hasattr(it, "structure_type"):
                            _emit("Structure Type", getattr(it, "structure_type"), quote=True)

                        # Limits / UI
                        if hasattr(it, "subtype"):
                            _emit("Subtype", getattr(it, "subtype"), quote=True)
                        if hasattr(it, "min_value"):
                            _emit("Min", getattr(it, "min_value"))
                        if hasattr(it, "max_value"):
                            _emit("Max", getattr(it, "max_value"))
                        if hasattr(it, "hide_value"):
                            _emit("Hide Value", bool(getattr(it, "hide_value")))
                        if hasattr(it, "hide_in_modifier"):
                            _emit("Hide in Modifier", bool(getattr(it, "hide_in_modifier")))
                        if hasattr(it, "default_attribute"):
                            _emit("Default Attribute", getattr(it, "default_attribute"), quote=True)
                    except Exception:
                        pass

                if meta_lines:
                    out.append(f"Set  {node_str}:")
                    out.extend(meta_lines)

            elif typ == "Group Output":
                go = [item for item in self.nt.interface.items_tree
                      if getattr(item, "item_type", "") == 'SOCKET' and item.in_out == 'OUTPUT']
                out.extend(declare_ports("Inputs", node_str, go))
                # Meta for Group Output sockets (no default values here)
                meta_lines = []
                for it in go:
                    try:
                        disp = (getattr(it, "name", "") or "").strip()
                        if not disp:
                            continue
                        def _emit(suffix, val, *, quote=False):
                            if val is None:
                                return
                            if quote:
                                meta_lines.append(f"§ {disp}::{suffix} § to {repr(val)}")
                            else:
                                if isinstance(val, bool):
                                    meta_lines.append(f"§ {disp}::{suffix} § to " + ("<True>" if val else "<False>"))
                                elif isinstance(val, (int, float)):
                                    meta_lines.append(f"§ {disp}::{suffix} § to <{val}>")
                                else:
                                    meta_lines.append(f"§ {disp}::{suffix} § to {val}")
                        stype = getattr(it, "bl_socket_idname", None) if hasattr(it, "bl_socket_idname") else getattr(it, "socket_type", None)
                        _emit("Socket Type", stype, quote=True)
                        if hasattr(it, "structure_type"):
                            _emit("Structure Type", getattr(it, "structure_type"), quote=True)
                        if hasattr(it, "subtype"):
                            _emit("Subtype", getattr(it, "subtype"), quote=True)
                        if hasattr(it, "hide_in_modifier"):
                            _emit("Hide in Modifier", bool(getattr(it, "hide_in_modifier")))
                        desc = (getattr(it, "description", "") or "").strip()
                        if desc:
                            meta_lines.append(f"§ {disp}::Description § to ~{desc.replace('~','-')}~")
                    except Exception:
                        pass
                if meta_lines:
                    out.append(f"Set  {node_str}:")
                    out.extend(meta_lines)

            else:
                out.extend(declare_ports("Inputs",  node_str, n.inputs))
                out.extend(declare_ports("Outputs", node_str, n.outputs))

        # Set (unlinked defaults + enums/toggles) — use display names so duplicates get [2], [3], …
        for n in nodes:
            kv = []

            # 0) SPECIAL: Group Input interface — write defaults & metadata by port label
            try:
                if n.bl_idname in {'NodeGroupInput','GeometryNodeGroupInput'}:
                    iface = n.id_data.interface
                    # collect INPUT-side interface sockets
                    items = [it for it in getattr(iface, 'items_tree', [])
                            if getattr(it, 'item_type', '') == 'SOCKET' and getattr(it, 'in_out', '') == 'INPUT']
                    for it in items:
                        name = (getattr(it, 'name','') or '').strip()
                        # default value (any type, including datablocks)
                        if hasattr(it, 'default_value'):
                            dv = getattr(it, 'default_value')
                            kv.append((name, serialize_any(dv)))  # exports as `§ Port § to <...>`
                        # metadata (emit only if meaningful/non-empty)
                        if getattr(it, 'description', ''):
                            kv.append((f"{name}::Description", f"~{it.description}~"))
                        if hasattr(it, 'default_attribute') and it.default_attribute:
                            kv.append((f"{name}::Default Attribute", f"{it.default_attribute}"))
                        if hasattr(it, 'subtype') and it.subtype:
                            kv.append((f"{name}::Subtype", f"{it.subtype}"))
                        if hasattr(it, 'min_value'):
                            kv.append((f"{name}::Min", f"<{it.min_value}>"))
                        if hasattr(it, 'max_value'):
                            kv.append((f"{name}::Max", f"<{it.max_value}>"))
                        if hasattr(it, 'hide_value') and it.hide_value:
                            kv.append((f"{name}::Hide Value", "True"))
                        if hasattr(it, 'hide_in_modifier') and it.hide_in_modifier:
                            kv.append((f"{name}::Hide in Modifier", "True"))
                        if hasattr(it, 'structure_type') and it.structure_type:
                            kv.append((f"{name}::Structure Type", f"{it.structure_type}"))
                        if hasattr(it, 'socket_type') and it.socket_type:
                            kv.append((f"{name}::Socket Type", f"{it.socket_type}"))
                    # fall through to writing the KV block below
            except Exception:
                pass

            # 1) Unlinked INPUT socket defaults
            in_names, _ = _display_names_for_sockets(n.inputs, True)
            for s, disp in zip(n.inputs, in_names):
                if s.is_linked:
                    continue
                sv = serialize_default(s)
                if _is_meaningful_serialized_default(sv):
                    kv.append((disp, sv))

            # 2) OUTPUT socket defaults (e.g. 'Value' on a Value node)
            out_names, _ = _display_names_for_sockets(n.outputs, False)
            for s, disp in zip(n.outputs, out_names):
                if not hasattr(s, "default_value"):
                    continue
                sv = serialize_default(s)
                if _is_meaningful_serialized_default(sv):
                    kv.append((disp, sv))

            # 3) Node RNA props (enums/toggles/number props you already collect)
            kv.extend(collect_node_props(n))

            if kv:
                typ, nid = enum[n]
                out.append(f"Set  [ {typ} #{nid} ]:")
                for k, v in kv:
                    out.append(f"§ {k} § to {v}")



        # Connect synthesized reroutes first so replay sees the GI sockets
        if 'gi_placeholder_links' in locals():
            for _gi_id, _label, _rr_id in gi_placeholder_links:
                out.append(f"Connect  [ Group Input #{_gi_id} ] ○ {_label}  to  [ Reroute #{_rr_id} ] ⦿ Input")

        # Links (reroute-collapsed)
        for fr, to in iter_links_collapsed(self.nt):
            nf, nt = fr.node, to.node
            if nf not in enum or nt not in enum:
                continue
            tf, idf = enum[nf]
            tt, idt = enum[nt]
            dotted = "Connect⋯" if link_is_field(fr, to) else "Connect"
            in_names, _ = _display_names_for_sockets(nt.inputs, True)
            out_names, _= _display_names_for_sockets(nf.outputs, False)
            fi = socket_position(fr)
            ti = socket_position(to)
            onm = out_names[fi] if 0 <= fi < len(out_names) else (fr.name or "output")
            inm = in_names[ti]  if 0 <= ti < len(in_names)  else (to.name or "input")
            out.append(f"{dotted}  [ {tf} #{idf} ] ○ {onm}  to  [ {tt} #{idt} ] ⦿ {inm}")

        # PairZone (Simulation / Repeat)
        self._emit_zone_pairs(self.nt, enum, out)
        self.lines_top.extend(out)

        # Ensure any nested group blocks are exported
        for n in nodes:
            if n.bl_idname == "GeometryNodeGroup" and n.node_tree:
                self._export_group_block(n.node_tree)

    def _emit_zone_pairs(self, ng, enum, out):
        sims_in  = []
        sims_out = []
        reps_in  = []
        reps_out = []
        for n in ng.nodes:
            if is_reroute(n) or is_frame(n) or n not in enum:
                continue
            t, i = enum.get(n, (None, None))
            if n.bl_idname == "GeometryNodeSimulationInput":  sims_in.append((n, i))
            if n.bl_idname == "GeometryNodeSimulationOutput": sims_out.append((n, i))
            if n.bl_idname == "GeometryNodeRepeatInput":      reps_in.append((n, i))
            if n.bl_idname == "GeometryNodeRepeatOutput":     reps_out.append((n, i))
        def by_x(a): return a[0].location[0]
        sims_in.sort(key=by_x); sims_out.sort(key=by_x)
        reps_in.sort(key=by_x); reps_out.sort(key=by_x)
        for (ni, idi), (no, ido) in zip(sims_in, sims_out):
            out.append(f"PairZone  [ Simulation Input #{idi} ] <-> [ Simulation Output #{ido} ]")
        for (ni, idi), (no, ido) in zip(reps_in, reps_out):
            out.append(f"PairZone  [ Repeat Input #{idi} ] <-> [ Repeat Output #{ido} ]")

    def run(self):
        self.lines_groups = [f"# BNDL v{BNDL_VERSION}", "# === GROUP DEFINITIONS ==="]
        self.lines_top = ["# === TOP LEVEL ==="]
        self._export_top()
        return "\n".join(self.lines_groups + [""] + self.lines_top) + "\n"

# ---------- Runner ----------

def export_active_geonodes_to_bndl_text():
    """Find the first GN modifier on the active object, export to BNDL text."""
    obj = bpy.context.view_layer.objects.active
    if obj is None:
        raise RuntimeError("No active object. Select an object with a Geometry Nodes modifier.")

    mod = None
    for m in obj.modifiers:
        if m.type == 'NODES' and m.node_group:
            mod = m
            break

    if mod is None:
        raise RuntimeError("Active object has no Geometry Nodes modifier with a node group.")

    nt = mod.node_group
    if nt is None:
        raise RuntimeError("Geometry Nodes modifier has no node group data.")

    exp = _TreeExport(nt)
    text = exp.run()
    # Append SetUser block (modifier overrides vs. GI defaults), if any
    try:
        text += _emit_setuser_block(nt, mod, text)
    except Exception as _ex:
        print(f"[BNDL] WARN: SetUser generation failed: {_ex}")


    # Write to Text datablock
    tb = bpy.data.texts.get(TEXT_BLOCK_NAME) or bpy.data.texts.new(TEXT_BLOCK_NAME)
    tb.clear()
    tb.write(text)

    # Optional: also dump to file
    if WRITE_FILE_PATH:
        try:
            with open(bpy.path.abspath(WRITE_FILE_PATH), "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            print(f"[BNDL] Warning: failed to write file: {e}")

    # (SetUser already appended earlier)
    print(f"[BNDL] Export complete → Text: {TEXT_BLOCK_NAME}")
    return text

# Execute immediately when run from Text Editor:
try:
    export_active_geonodes_to_bndl_text()
except Exception as ex:
    print(f"[BNDL] ERROR: {ex}")
# End of exporter_1-2.py
