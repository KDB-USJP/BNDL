# BNDL
The Blender Node Description Language (BNDL) exports and imports human-readable text descriptions of blender node trees

# BNDL — Blender Node Description Language  
### *Release 1.0 · Geometry Nodes Edition*
<img width="1008" height="506" alt="image" src="https://github.com/user-attachments/assets/c933cf20-36a2-430f-8b9e-979c47467d87" />

BNDL (“Bundle”) is a **plain-text format for Blender node trees**.  
It captures every node, connection, and parameter — including user-edited values —  
so that you can **export, version, and recreate** Geometry Node setups precisely.

---

## What It Does

| Step | Action | Script |
|------|---------|--------|
| **1️⃣ Export** | Reads the current node tree and writes a readable `.bndl` file. | `exportbndl.py` |
| **2️⃣ Compile** | Converts the `.bndl` into a runnable replay script. | `bndl2py.py` |
| **3️⃣ Replay** (Not Open Source; internal tool) | Recreates the entire node graph on an active object. | `BNDL_Replay.py` |

After replay, the new Geometry Nodes modifier looks and behaves **exactly like the source**,  
complete with datablocks, default values, and *user overrides*.

---

## Why Use It?

- ✅ **Version Control Friendly** — plain text, diffable in Git.  
- ✅ **Pipeline Ready** — automatable with Python, no `.blend` files needed.  
- ✅ **Cross-Project Sync** — share or reproduce node trees across machines.  
- ✅ **Archival & Debugging** — snapshot node setups for comparison or QA.  

---

## Example Snippet

```text
# BNDL v1
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
```

Replay produces a Geometry Nodes modifier with:
```
Instance Object  → GLX_Star
Galaxy Scale     → 6.27
```

---

## Current Scope

| Domain | Status | Notes |
|---------|---------|-------|
| Geometry Nodes | ✅ Complete | Supports all built-in Geometry Nodes. |
| Shader / Material Nodes | 🚧 Planned | Future release. |
| Compositor Nodes | 🚧 Planned | Future release. |

---

## File Overview

| File | Description |
|------|--------------|
| `exportbndl.py` | Exports current Geometry Node tree to `.bndl`. |
| `bndl2py.py` | Converts `.bndl` into a Python replay script. |
| `BNDL_Spec_v1_Release.md` | Full specification for Release 1.0. |
| `BNDL_Replay.py` | Auto-generated script that rebuilds the node tree. |

---

## Requirements

- **Blender 4.0+** (uses new `ng.interface` API)  
- **Python 3.10+** (built into Blender 4.x)

---

## Next Steps

1. Install or open the add-on (coming soon).  
2. Run **“Export BNDL”** to capture your active Geometry Node tree.  
3. Run **“Replay BNDL”** to reconstruct it anywhere.

---

## License

MIT License — open for all non-destructive workflows, educational and production use.
