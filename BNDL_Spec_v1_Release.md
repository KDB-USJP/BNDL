# 🧩 BNDL File Format — *Release 1.0 (Geometry Nodes)*

> **BNDL** (“Bundle”) is a human-readable serialization of Blender node trees.  
> It enables round-tripping node graphs — export, version-control, diff, and replay — while preserving structure, values, and user overrides.

## 1. Purpose
BNDL provides a **plain-text representation** of Blender node trees (starting with *Geometry Nodes* in Blender 4.x).  
It’s designed for:
- Pipeline automation: generate procedural assets or templates via Python.  
- Version control: track node graph changes in Git or similar tools.  
- Cross-team exchange: hand off node structures without .blend files.  
- Archival: reconstruct exact node trees on any compatible Blender build.

The companion scripts are:

| Script | Function |
|--------|-----------|
| **exportbndl.py** | Scans a node tree and writes a `.bndl` text block. |
| **bndl2py.py** | Converts a `.bndl` file into a self-contained replay script `BNDL_Replay.py`. |
| **BNDL_Replay.py** | Recreates the original node tree in Blender, including user-edited values. |

## 2. Core Principles
- **Readable**: explicit statements (`Create`, `Connect`, `Set`, `SetUser`).  
- **Idempotent**: replaying multiple times yields identical results.  
- **Complete**: includes all node types, connections, and parameters.  
- **Scoped**: supports nested node groups and top-level modifiers.  
- **Forward-extensible**: future versions will add Shader and Compositor domains.

## 3. File Layout
A BNDL file is divided into **sections**, each beginning with a `# ===` header.

```text
# BNDL v1
# === GROUP DEFINITIONS ===
BEGIN GROUP NAMED GalaxySetup
    Create  [ Group Input | — | ] ~  ~ #1 ; type=NodeGroupInput
    Set     [ Group Input #1 ]:
        § Galaxy Scale § to <4.5>
    Connect [ Group Input #1 ] ○ Geometry  to  [ Group Output #1 ] ⦿ Result
END GROUP NAMED GalaxySetup

# === TOP LEVEL ===
Create  [ Group Input | — | ] ~  ~ #1 ; type=NodeGroupInput
Set     [ Group Input #1 ]:
    § Instance Object § to ⊞GLX_Star⊞
    § Instance Scale Min § to <0.0>
    § Instance Scale Max § to <20.0>

# === USER OVERRIDES ===
SetUser [ Group Input #1 ]:
    § Instance Scale Min § to <0.03>
    § Instance Scale Max § to <0.21>
    § Galaxy Scale § to <6.27>
    § Volume Density § to <50.26>
```

## 4. Statement Types
| Statement | Purpose | Example |
|------------|----------|---------|
| **Create** | Define a node and its type. | `Create [ Join Geometry | — | ] ~  ~ #1 ; type=GeometryNodeJoinGeometry` |
| **Connect** | Create a link between node sockets. | `Connect [ NodeA #1 ] ○ Geometry to [ NodeB #2 ] ⦿ Mesh` |
| **Set** | Assign default parameter values (from original tree). | `Set [ Node #1 ]: § Scale § to <1.0>` |
| **SetUser** | Assign user-edited parameter values (from modifier UI). These override `Set` during replay. | `SetUser [ Group Input #1 ]: § Scale § to <2.0>` |

## 5. Node Identification
Each node appears as:
```
[ Node Name | Label | GroupName ] ~  ~ #Index ; type=NodeType
```
- `Node Name` – internal node type name.  
- `Label` – user-visible label.  
- `GroupName` – parent group.  
- `#Index` – ordinal identifier.  
- `type=` – Blender node type ID.

## 6. Socket Markers
| Symbol | Meaning |
|:-------:|:--------|
| `○` | Input socket |
| `⦿` | Output socket |
| `§ … §` | Socket or UI field name |
| `⊞Name⊞` | Datablock reference |

## 7. Data Representation
| Data Kind | Example | Notes |
|------------|----------|-------|
| Number | `<3.14>` | Float or int. |
| Boolean | `<True>` | Case-insensitive. |
| Enum | `<Face Area>` | Mapped by UI label. |
| Vector / Color | `<(1.0, 0.5, 0.0)>` | Tuple syntax. |
| Datablock | `⊞MyMaterial⊞` | Recreates or proxies missing datablocks. |
| Units | `<90°>` `<1 cm>` `<0.01 m>` | Converted to Blender base units. |

## 8. Replay Lifecycle
1. **Export** – `exportbndl.py` writes `Create`, `Connect`, and `Set`.  
2. **Compile to Replay** – `bndl2py.py` emits `BNDL_Replay.py`.  
3. **Replay** – running the script rebuilds nodes, applies defaults and SetUser values, and mirrors Group Input defaults into the Geometry Nodes modifier UI.

## 9. Naming and Referencing Rules
- `Create` IDs (`#1`, `#2`, …) are local to their group.  
- Group names are unique.  
- Datablocks are linked or proxied as `bndlproxy_*`.  
- Frames and Reroutes are ignored.

## 10. Extending the Spec
Future versions will add:
- `# === SHADER NODES ===` and `# === COMPOSITOR NODES ===`
- `# === METADATA ===`
- Per-group `USER OVERRIDES` blocks.

## 11. Example Round Trip
| Step | Action | Result |
|------|--------|--------|
| ① | Build a node graph. | Geometry Nodes tree on object. |
| ② | Run `exportbndl.py`. | Creates `BNDL_Export` text block. |
| ③ | Run `bndl2py.py`. | Produces `BNDL_Replay.py`. |
| ④ | Run replay. | Recreates identical tree with SetUser values. |

## 12. Compatibility
- **Blender:** 4.0+ (`ng.interface` API).  
- **Domains:** Geometry Nodes.  
- **Compatibility:** forward only.

## 13. Example Visual Outcome
```
Instance Object     → GLX_Star
Instance Material   → GLX_Emit
Falloff Object      → Galaxia_Center
Galaxy Scale        → 6.270
Voxel Amount        → 505.180
```
✅ Replayed modifier matches original exactly.
