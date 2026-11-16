"""The finished build as a Cycles render: the exported model plus stand-ins for the bought components.

Runs inside Blender (5.2 LTS), headless:
    blender -b --factory-startup --python cad_b6/blender_scene.py -- --data DIR --out DIR [options]
        --data DIR      scene.npz and scene.json written by cad_b6/render_blender.py
        --out DIR       where the pictures go, as b6_render_<view>.png
        --views a,b     which of front_left, front_right, rear, hero (default: all four); inside and left are two more, for inspection
        --res WxH       picture size (default 2560x1920)
        --samples N     Cycles samples (default 400)
        --device D      GPU (default; CUDA or OptiX, whichever starts) or CPU
        --blend FILE    also save the scene as a .blend file
        --hide a,b      leave collections (skeleton, organic, hoses, cables, standins) or objects whose name starts so out of the picture,
                        e.g. --views inside --hide organic,rad360,fan360 --suffix _inside to look at the board
        --suffix S      appended to the picture names
        --check-only    build the scene, run the checks, render nothing

Exact, from the export: the skeleton parts, the organic layer, the hoses, the cables (centre lines and radii), the light line's slit.
Stand-ins, built here from the constants of hardware.py (scene.json "hw"): fans, radiators, motherboard, graphics card, CPU block, power
supply, front I/O module, drives, hose fittings and cable plugs. No logos, no textures from anywhere; every surface is a procedural material.

Three checks are printed before rendering:
  bounds  every stand-in that stands for a block-out box of hardware.py lies inside that box
  tubes   no hose and no cable passes through a stand-in (their own ends excepted)
  frame   no stand-in that is not held inside a block-out box (plugs, fittings, the card's bracket, the board's furniture) cuts a printed part
"""
import argparse
import json
import math
import os
import sys
import time

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import tessellate_polygon

MM = 0.001
PI = math.pi

# ---------------------------------------------------------------------------------------------------------------------
# Arguments and data
# ---------------------------------------------------------------------------------------------------------------------
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--views", default="front_left,front_right,rear,hero")
ap.add_argument("--res", default="2560x1920")
ap.add_argument("--samples", type=int, default=400)
ap.add_argument("--device", default="GPU")
ap.add_argument("--blend", default="")
ap.add_argument("--hide", default="", help="for looking inside: collections or object-name prefixes to leave out of the picture")
ap.add_argument("--suffix", default="")
ap.add_argument("--check-only", action="store_true")
ARGS = ap.parse_args(argv)

with open(os.path.join(ARGS.data, "scene.json")) as fh:
    SCENE = json.load(fh)
NPZ = np.load(os.path.join(ARGS.data, "scene.npz"))
HW = SCENE["hw"]
MESH = {m["name"]: m for m in SCENE["meshes"]}
ORIGIN = Vector(HW["ORIGIN"])
BS = Matrix.Translation(ORIGIN) @ Matrix.Rotation(math.radians(HW["TILT_DEG"]), 4, "X")     # board space (v, u, n) -> world, mm
WORLD = Matrix.Identity(4)
T0 = time.time()


def x_to_v(x):
    return x - ORIGIN[0]


def frame(o, x, z):
    """Placement (mm): origin o, local x along `x`, local z along `z`, local y = z cross x."""
    x, z = Vector(x).normalized(), Vector(z).normalized()
    y = z.cross(x)
    return Matrix(((x[0], y[0], z[0], o[0]), (x[1], y[1], z[1], o[1]), (x[2], y[2], z[2], o[2]), (0, 0, 0, 1)))


def to_m(M):
    out = M.copy()
    for k in range(3):
        out[k][3] *= MM
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------------------------------------------------
MATS = {}


def principled(name, base, rough, metallic=0.0, coat=0.0, coat_rough=0.08, emit=None, strength=0.0, spec=0.5):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*base, 1.0) if len(base) == 3 else base
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Coat Weight"].default_value = coat
    b.inputs["Coat Roughness"].default_value = coat_rough
    b.inputs["Specular IOR Level"].default_value = spec
    if emit is not None:
        b.inputs["Emission Color"].default_value = (*emit, 1.0)
        b.inputs["Emission Strength"].default_value = strength
    MATS[name] = m
    return m, b


def node(nt, kind, **props):
    n = nt.nodes.new(kind)
    for k, v in props.items():
        setattr(n, k, v)
    return n


def math_node(nt, op, a, b=None):
    n = node(nt, "ShaderNodeMath", operation=op)
    for k, x in enumerate((a, b)):
        if x is None:
            continue
        if isinstance(x, (int, float)):
            n.inputs[k].default_value = x
        else:
            nt.links.new(x, n.inputs[k])
    return n.outputs[0]


def bump(nt, bsdf, height, strength, distance_mm):
    n = node(nt, "ShaderNodeBump")
    n.inputs["Strength"].default_value = strength
    n.inputs["Distance"].default_value = distance_mm * MM
    nt.links.new(height, n.inputs["Height"])
    nt.links.new(n.outputs["Normal"], bsdf.inputs["Normal"])


def make_materials():
    # printed parts: the two blacks must read as two materials
    m, b = principled("abs", (0.022, 0.022, 0.024), 0.60)                     # matte black ABS
    nt = m.node_tree
    z = node(nt, "ShaderNodeSeparateXYZ")
    nt.links.new(node(nt, "ShaderNodeNewGeometry").outputs["Position"], z.inputs[0])
    lines = math_node(nt, "SINE", math_node(nt, "MULTIPLY", z.outputs["Z"], 2 * PI / (0.8 * MM)))   # a hint of layer lines, 0.8 mm apart so that they survive the picture's scale
    bump(nt, b, lines, 0.3, 0.06)
    principled("petg", (0.012, 0.012, 0.013), 0.36, coat=0.12, coat_rough=0.30)                    # satin black PETG
    principled("nylon", (0.045, 0.045, 0.043), 0.72)                                               # black PA6, dull and slightly grey

    # hoses and cables: a braided sleeve from the tube's own (a, b) coordinates, see tube_mesh()
    for name, base, hi, rough, depth in (("hose", (0.010, 0.010, 0.010), (0.055, 0.055, 0.058), 0.55, 0.25),
                                         ("cable", (0.012, 0.012, 0.012), (0.050, 0.050, 0.052), 0.68, 0.18)):
        m, b = principled(name, base, rough)
        nt = m.node_tree
        uv = node(nt, "ShaderNodeSeparateXYZ")
        nt.links.new(node(nt, "ShaderNodeUVMap").outputs["UV"], uv.inputs[0])
        wa = math_node(nt, "ABSOLUTE", math_node(nt, "SINE", math_node(nt, "MULTIPLY", uv.outputs["X"], PI)))
        wb = math_node(nt, "ABSOLUTE", math_node(nt, "SINE", math_node(nt, "MULTIPLY", uv.outputs["Y"], PI)))
        h = math_node(nt, "MULTIPLY", wa, wb)
        mix = node(nt, "ShaderNodeMix", data_type="RGBA")
        mix.inputs["A"].default_value = (*base, 1.0)
        mix.inputs["B"].default_value = (*hi, 1.0)
        nt.links.new(h, mix.inputs["Factor"])
        nt.links.new(mix.outputs["Result"], b.inputs["Base Color"])
        bump(nt, b, h, 0.8, depth)

    principled("rad_paint", (0.016, 0.016, 0.017), 0.42)
    principled("rad_fin", (0.022, 0.022, 0.023), 0.50, metallic=0.3)
    principled("fan_frame", (0.020, 0.020, 0.021), 0.36)
    principled("fan_blade", (0.028, 0.028, 0.030), 0.27)
    principled("fan_sticker", (0.06, 0.06, 0.065), 0.22, metallic=0.6)
    principled("pcb", (0.010, 0.013, 0.014), 0.38, coat=0.4, coat_rough=0.25)
    principled("heatsink", (0.075, 0.078, 0.085), 0.34, metallic=1.0)          # dark anodised aluminium
    principled("heatsink_black", (0.022, 0.022, 0.024), 0.30, metallic=1.0)
    principled("plastic_black", (0.018, 0.018, 0.019), 0.45)
    principled("plastic_grey", (0.11, 0.11, 0.115), 0.5)
    principled("slot", (0.035, 0.035, 0.038), 0.5)
    principled("gpu_shroud", (0.020, 0.020, 0.022), 0.33, metallic=0.85)
    principled("gpu_accent", (0.16, 0.165, 0.175), 0.28, metallic=1.0)
    principled("gpu_back", (0.050, 0.052, 0.058), 0.30, metallic=1.0)
    principled("gpu_strip", (0.02, 0.02, 0.02), 0.4, emit=(0.80, 0.90, 1.0), strength=0.7)
    principled("black_nickel", (0.050, 0.050, 0.055), 0.22, metallic=1.0)      # fittings, screws, brackets
    principled("steel", (0.32, 0.32, 0.33), 0.32, metallic=1.0)
    principled("gold", (0.80, 0.55, 0.18), 0.3, metallic=1.0)
    principled("psu", (0.014, 0.014, 0.015), 0.48)
    principled("void", (0.002, 0.002, 0.002), 0.9)
    principled("hdd_body", (0.060, 0.060, 0.064), 0.5, metallic=0.9)
    principled("hdd_cover", (0.20, 0.20, 0.21), 0.3, metallic=1.0)
    principled("light", (0.9, 0.9, 0.9), 0.5, emit=(1.0, 0.50, 0.20), strength=1.5)      # warm white, about 3000 K
    principled("led_white", (0.5, 0.5, 0.5), 0.5, emit=(1.0, 0.97, 0.92), strength=1.2)
    m, b = principled("desk", (0.26, 0.257, 0.253), 0.50)
    nt = m.node_tree
    noise = node(nt, "ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 3.0
    noise.inputs["Detail"].default_value = 6.0
    ramp = node(nt, "ShaderNodeMapRange")
    ramp.inputs["To Min"].default_value, ramp.inputs["To Max"].default_value = 0.42, 0.60
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Value"])
    nt.links.new(ramp.outputs["Result"], b.inputs["Roughness"])


# ---------------------------------------------------------------------------------------------------------------------
# Mesh building
# ---------------------------------------------------------------------------------------------------------------------
STANDINS = []        # (object, tag): what the two checks look at
COLL = {}


def collection(name):
    if name not in COLL:
        COLL[name] = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(COLL[name])
    return COLL[name]


def make_obj(name, V, F, mat, M=WORLD, coll="standins", smooth=30.0, bevel=0.0, solidify=0.0, subsurf=0, uv=None, weighted=True, recalc=True):
    """A mesh object from vertices in mm (local) and faces, placed by M (mm). smooth: angle in degrees over which an edge stays sharp, None = flat."""
    me = bpy.data.meshes.new(name)
    V = np.asarray(V, dtype=np.float64).reshape(-1, 3) * MM
    if isinstance(F, np.ndarray):
        k = F.shape[1]
        me.vertices.add(len(V))
        me.vertices.foreach_set("co", V.ravel())
        me.loops.add(F.size)
        me.loops.foreach_set("vertex_index", F.ravel().astype(np.int32))
        me.polygons.add(len(F))
        me.polygons.foreach_set("loop_start", np.arange(0, F.size, k, dtype=np.int32))
        me.polygons.foreach_set("loop_total", np.full(len(F), k, dtype=np.int32))
        me.update(calc_edges=True)
    else:
        me.from_pydata(V.tolist(), [], F)
    me.validate()
    if uv is not None:
        idx = np.empty(len(me.loops), dtype=np.int32)
        me.loops.foreach_get("vertex_index", idx)
        me.uv_layers.new(name="UVMap").data.foreach_set("uv", np.asarray(uv, dtype=np.float32)[idx].ravel())
    if recalc:
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me)
        bm.free()
    if smooth is not None:
        me.shade_smooth()
        if smooth < 180.0:
            me.set_sharp_from_angle(angle=math.radians(smooth))
    me.materials.append(MATS[mat])
    ob = bpy.data.objects.new(name, me)
    ob.matrix_world = to_m(M)
    collection(coll).objects.link(ob)
    if solidify:
        md = ob.modifiers.new("solid", "SOLIDIFY")
        md.thickness, md.offset = solidify * MM, 0.0
    if subsurf:
        md = ob.modifiers.new("subd", "SUBSURF")
        md.levels = md.render_levels = subsurf
    if bevel:
        md = ob.modifiers.new("bevel", "BEVEL")
        md.width, md.segments, md.limit_method, md.angle_limit = bevel * MM, 3, "ANGLE", math.radians(35)
    if weighted and smooth is not None and smooth < 180.0 and not subsurf:
        md = ob.modifiers.new("wn", "WEIGHTED_NORMAL")
        md.keep_sharp, md.weight = True, 60
    return ob


def circle(cx, cy, r, n=32, a0=0.0):
    return [(cx + r * math.cos(a0 + 2 * PI * k / n), cy + r * math.sin(a0 + 2 * PI * k / n)) for k in range(n)]


def rect(x0, x1, y0, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def rrect(x0, x1, y0, y1, r, n=6):
    out = []
    for cx, cy, a in ((x1 - r, y0 + r, -PI / 2), (x1 - r, y1 - r, 0.0), (x0 + r, y1 - r, PI / 2), (x0 + r, y0 + r, PI)):
        out += [(cx + r * math.cos(a + PI / 2 * k / n), cy + r * math.sin(a + PI / 2 * k / n)) for k in range(n + 1)]
    return out


class MB:
    """Collects vertices (mm) and faces of one object."""

    def __init__(self):
        self.v, self.f = [], []

    def add(self, verts, faces):
        n = len(self.v)
        self.v.extend(tuple(map(float, p)) for p in verts)
        self.f.extend(tuple(int(i) + n for i in f) for f in faces)
        return self

    def box(self, x0, x1, y0, y1, z0, z1):
        v = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
        return self.add(v, [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)])

    def prism(self, loops, z0, z1):
        """A flat profile (the first loop is the outline, the others are holes), in the local xy plane, from z0 to z1."""
        flat = [p for lp in loops for p in lp]
        tris = tessellate_polygon([[Vector((p[0], p[1], 0.0)) for p in lp] for lp in loops])
        n = len(flat)
        verts = [(p[0], p[1], z0) for p in flat] + [(p[0], p[1], z1) for p in flat]
        faces = [t for t in tris] + [(a + n, b + n, c + n) for a, b, c in tris]
        k = 0
        for lp in loops:
            m = len(lp)
            faces += [(k + i, k + (i + 1) % m, n + k + (i + 1) % m, n + k + i) for i in range(m)]
            k += m
        return self.add(verts, faces)

    def cyl(self, p0, p1, r, n=40, r1=None):
        p0, p1 = Vector(p0), Vector(p1)
        a = (p1 - p0).normalized()
        e = a.orthogonal().normalized()
        g = a.cross(e)
        r1 = r if r1 is None else r1
        verts = []
        for p, rr in ((p0, r), (p1, r1)):
            verts += [p + rr * (math.cos(2 * PI * k / n) * e + math.sin(2 * PI * k / n) * g) for k in range(n)]
        faces = [(k, (k + 1) % n, n + (k + 1) % n, n + k) for k in range(n)] + [tuple(range(n)), tuple(range(n, 2 * n))]
        return self.add(verts, faces)

    def tube(self, pts, r, n=8, closed=False):
        V, F, _ = tube_mesh(np.asarray(pts, dtype=np.float64), r, n, closed=closed, caps=not closed)
        return self.add(V, F)

    def moved(self, M):
        out = MB()
        out.v = [tuple(M @ Vector(p)) for p in self.v]
        out.f = list(self.f)
        return out

    def merge(self, other, M=None):
        o = other.moved(M) if M is not None else other
        return self.add(o.v, o.f)

    def obj(self, name, mat, M=WORLD, tag=None, **kw):
        ob = make_obj(name, self.v, self.f, mat, M, **kw)
        STANDINS.append((ob, tag))
        return ob


def tube_mesh(P, r, sides, closed=False, caps=True, braid_w=None):
    """A round tube along the polyline P. Returns vertices, faces and per-vertex (a, b): the two families of a braid, each a whole number of
    strands round the tube, so the weave closes on itself."""
    P = np.asarray(P, dtype=np.float64)
    keep = np.ones(len(P), dtype=bool)
    keep[1:] = np.linalg.norm(np.diff(P, axis=0), axis=1) > 1e-6
    P = P[keep]
    n = len(P)
    if closed:
        T = np.roll(P, -1, axis=0) - np.roll(P, 1, axis=0)
    else:
        T = np.gradient(P, axis=0)
    T /= np.linalg.norm(T, axis=1)[:, None]
    N = np.zeros_like(P)
    first = np.array(Vector(T[0]).orthogonal().normalized())
    for i in range(n):
        first = first - T[i] * first.dot(T[i])
        first /= np.linalg.norm(first)
        N[i] = first
    B = np.cross(T, N)
    ang = np.linspace(0.0, 2 * PI, sides + 1)
    ring = np.cos(ang)[None, :, None] * N[:, None, :] + np.sin(ang)[None, :, None] * B[:, None, :]
    V = (P[:, None, :] + r * ring).reshape(-1, 3)
    w = sides + 1
    faces = []
    rows = n if closed else n - 1
    for i in range(rows):
        i2 = (i + 1) % n
        faces += [(i * w + j, i * w + j + 1, i2 * w + j + 1, i2 * w + j) for j in range(sides)]
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    nb = max(6, int(round(2 * PI * r / (braid_w or 2.4))))
    pitch = 2 * PI * r / nb
    U = np.tile(np.arange(w) / sides, n)
    Sv = np.repeat(s, w)
    uv = np.stack([nb * U + Sv / pitch, nb * U - Sv / pitch], axis=1)
    V = V.tolist()
    if caps and not closed:
        for i in (0, n - 1):
            V.append(P[i].tolist())
            c = len(V) - 1
            faces += [(c, i * w + j, i * w + j + 1) for j in range(sides)]
        uv = np.vstack([uv, np.zeros((2, 2))])
    return V, faces, uv


def boolean_cut(ob, cutters):
    """Cut the cutter objects out of ob (exact solver) and drop them."""
    for c in cutters:
        md = ob.modifiers.new("cut", "BOOLEAN")
        md.operation, md.solver, md.object = "DIFFERENCE", "EXACT", c
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    old = ob.data
    for md in list(ob.modifiers):
        if md.type == "BOOLEAN":
            ob.modifiers.remove(md)
    ob.data = me
    bpy.data.meshes.remove(old)
    for c in cutters:
        STANDINS[:] = [(o, t) for o, t in STANDINS if o is not c]
        bpy.data.objects.remove(c)


# ---------------------------------------------------------------------------------------------------------------------
# The exact model
# ---------------------------------------------------------------------------------------------------------------------
PART_MAT = {"ABS": "abs", "PA6": "nylon"}
TUBES = []          # (name, kind, points (n, 3) mm, radius)


def build_exact():
    for m in SCENE["meshes"]:
        V, F = NPZ[m["key"] + "_v"], NPZ[m["key"] + "_f"]
        if m["kind"] == "part":
            make_obj(m["name"], V, F, PART_MAT[m["material"]], coll="skeleton", smooth=28.0, recalc=False)
        elif m["kind"] == "organic":
            make_obj(m["name"], V, F, "petg", coll="organic", smooth=180.0, recalc=False)
    for t in SCENE["tubes"]:
        P = NPZ[t["key"] + "_p"].astype(np.float64)
        hose = t["kind"].startswith("hose")
        sides = 24 if hose else (20 if t["r"] >= 6 else (14 if t["r"] >= 4 else 10))
        V, F, uv = tube_mesh(P, t["r"], sides, braid_w=2.6 if hose else 1.9)
        make_obj(t["name"], V, F, "hose" if hose else "cable", coll="hoses" if hose else "cables", smooth=180.0, uv=uv, recalc=False)
        TUBES.append((t["name"], t["kind"], P, t["r"]))


def bs_of(P):
    """World points (mm) in board space (v, u, n)."""
    Minv = BS.inverted()
    return np.array([tuple(Minv @ Vector(p)) for p in np.asarray(P, dtype=np.float64).reshape(-1, 3)])


# ---------------------------------------------------------------------------------------------------------------------
# Fans
# ---------------------------------------------------------------------------------------------------------------------
def rotor(r_hub, r_tip, t, blades, phase, z_lo=2.0, z_hi=None):
    """Hub and swept blades about local z, between z = 0 (intake) and z = t. Returns (hub, blades) builders."""
    z_hi = t - 5.0 if z_hi is None else z_hi
    hub = MB().cyl((0, 0, z_lo), (0, 0, z_hi), r_hub, 56)
    bl = MB()
    ns, nc = 10, 8
    for k in range(blades):
        th0 = phase + 2 * PI * k / blades
        verts = []
        for i in range(ns):
            s = i / (ns - 1)
            r = r_hub - 1.0 + s * (r_tip - r_hub + 1.0)
            span = (2 * PI / blades) * (1.02 - 0.22 * s)
            h = (z_hi - z_lo - 2.0) * (1.0 - 0.12 * s)
            for j in range(nc):
                c = j / (nc - 1)
                a = th0 + 0.60 * s ** 1.25 + (c - 0.5) * span
                z = (z_lo + z_hi) / 2 + (0.5 - c) * h + 1.2 * math.sin(PI * c)
                verts.append((r * math.cos(a), r * math.sin(a), z))
        faces = [(i * nc + j, i * nc + j + 1, (i + 1) * nc + j + 1, (i + 1) * nc + j) for i in range(ns - 1) for j in range(nc - 1)]
        bl.add(verts, faces)
    return hub, bl


def build_fan(name, M, size, t, pitch, open_d, blades, phase, tag):
    """A frame fan in its own frame: square in xy about the origin, air from z = 0 (intake) to z = t (the struts and the motor are on that side)."""
    N = 144
    th = np.arange(N) * 2 * PI / N
    c, s = np.cos(th), np.sin(th)
    k = 14.0
    r_out = (size / 2) / (np.abs(c) ** k + np.abs(s) ** k) ** (1 / k)
    r_in = np.minimum(open_d / 2, (size / 2 - 2.0) / np.maximum(np.abs(c), np.abs(s)))
    r_d = np.minimum(r_in + 1.8, r_out - 0.05)
    outer, inner, duct = (list(zip(r * c, r * s)) for r in (r_out, r_in, r_d))
    corners = [(sx * pitch / 2, sy * pitch / 2) for sx in (-1, 1) for sy in (-1, 1)]
    holes = [circle(x, y, 2.15, 14) for x, y in corners]
    fl = 3.6
    fr = MB()
    fr.prism([outer, inner] + holes, 0.0, fl)
    fr.prism([outer, inner] + holes, t - fl, t)
    fr.prism([duct, inner], fl, t - fl)
    for x, y in corners:
        fr.cyl((x, y, fl), (x, y, t - fl), 4.4, 20)
    r_hub = 0.30 * open_d / 2 + 1.0
    r_open = float(r_in.min())
    st = MB().cyl((0, 0, t - 4.6), (0, 0, t - 0.8), r_hub * 0.96, 48)
    off = r_hub * 0.55
    for q in range(4):
        x0, x1 = math.sqrt((0.8 * r_hub) ** 2 - off ** 2), math.sqrt((r_open + 1.0) ** 2 - off ** 2)
        st.merge(MB().box(x0, x1, off - 2.2, off + 2.2, t - 4.2, t - 1.0), Matrix.Rotation(q * PI / 2 + 0.35, 4, "Z"))
    hub, bl = rotor(r_hub, r_open - 1.6, t, blades, phase)
    fr.obj(name + "_frame", "fan_frame", M, tag, smooth=35.0)
    st.obj(name + "_struts", "fan_frame", M, tag, smooth=35.0)
    hub.obj(name + "_hub", "fan_blade", M, tag, bevel=1.2)
    bl.obj(name + "_blades", "fan_blade", M, tag, smooth=180.0, solidify=1.4, subsurf=1)
    MB().cyl((0, 0, t - 0.8), (0, 0, t - 0.6), r_hub * 0.78, 48).obj(name + "_sticker", "fan_sticker", M, tag)


# ---------------------------------------------------------------------------------------------------------------------
# Radiators
# ---------------------------------------------------------------------------------------------------------------------
def build_radiator(name, M, L, W, T, tank, holes_x, hole_pitch, tubes, tag):
    """A radiator core in its own frame: x along the length (0..L), y across the width (0..W), z through the thickness (0..T).
    End tanks, side rails with the fan holes on both faces, flat tubes along x and folded fins between them, as real geometry."""
    body = MB()
    body.box(0, tank, 0, W, 0, T)
    body.box(L - tank, L, 0, W, 0, T)
    edge = (W - hole_pitch) / 2
    fw = edge + 5.0
    for y0, y1, hy in ((0.0, fw, edge), (W - fw, W, W - edge)):
        loops = [rect(tank - 0.5, L - tank + 0.5, y0, y1)] + [circle(x, hy, 1.8, 12) for x in holes_x if tank + 3 < x < L - tank - 3]
        body.prism(loops, 0.0, 1.2)
        body.prism(loops, T - 1.2, T)
    body.box(tank - 0.5, L - tank + 0.5, 0.0, 1.4, 1.2, T - 1.2)
    body.box(tank - 0.5, L - tank + 0.5, W - 1.4, W, 1.2, T - 1.2)
    body.obj(name + "_body", "rad_paint", M, tag, bevel=0.8)

    core = MB()
    y_lo, y_hi, tt = 2.0, W - 2.0, 1.7
    pitch = (y_hi - y_lo - tt) / (tubes - 1)
    ys = [y_lo + tt / 2 + k * pitch for k in range(tubes)]
    for y in ys:
        core.box(tank - 0.5, L - tank + 0.5, y - tt / 2, y + tt / 2, 2.2, T - 2.2)
    core.obj(name + "_tubes", "rad_fin", M, tag, smooth=None)

    fold = 1.6                                         # one fold of the fin ribbon, mm
    xs = np.arange(tank, L - tank + 1e-6, fold / 2)
    K = len(xs)
    V, F, base = [], [], 0
    for a, b in zip(ys[:-1], ys[1:]):
        y = np.where(np.arange(K) % 2 == 0, a + tt / 2, b - tt / 2)
        lo = np.stack([xs, y, np.full(K, 2.8)], axis=1)
        hi = np.stack([xs, y, np.full(K, T - 2.8)], axis=1)
        V += [lo, hi]
        i = np.arange(K - 1)
        F.append(np.stack([base + i, base + i + 1, base + K + i + 1, base + K + i], axis=1))
        base += 2 * K
    ob = make_obj(name + "_fins", np.vstack(V), np.vstack(F).astype(np.int32), "rad_fin", M, smooth=None, recalc=False)
    STANDINS.append((ob, tag))


def build_cooling():
    r360, r420 = HW["RAD360_BS"], HW["RAD420_BS"]
    # the 360: core towards the board (n 122..152), fans on the outer face, blowing in
    n0, n1 = HW["RAD360_CORE_N"]
    M = BS @ frame((r360[0], r360[2], n0), (1, 0, 0), (0, 0, 1))
    hx = [x_to_v(x) - r360[0] for x in HW["RAD360_HOLES_X"]]
    hu = HW["RAD360_HOLES_U"]
    fan_x = [(hx[2 * k] + hx[2 * k + 1]) / 2 for k in range(3)]
    tank = fan_x[0] - 60.0
    build_radiator("rad360", M, r360[1] - r360[0], r360[3] - r360[2], n1 - n0, tank, hx, hu[1] - hu[0], 13, "rad360")
    f0, f1 = HW["RAD360_FAN_N"]
    for k, x in enumerate(fan_x):
        Mf = BS @ frame((r360[0] + x, (hu[0] + hu[1]) / 2, f1), (1, 0, 0), (0, 0, -1))
        build_fan(f"fan360_{k}", Mf, 120.0, f1 - f0, hu[1] - hu[0], 116.0, 9, 0.5 + 1.3 * k, "rad360")

    # the 420: core towards the board (u 310..348), the bracket plate's 3 mm, fans on the outer face (u 351..378) blowing down-slope
    cu, cn = HW["RAD420_CORE_U"], HW["RAD420_CORE_N"]
    M = BS @ frame((r420[0], cu[0], cn[1]), (1, 0, 0), (0, 1, 0))
    P14 = HW["FAN_P14"]
    hx = [x_to_v(x) - r420[0] for x in HW["RAD420_HOLES_X"]]
    tank = x_to_v(HW["RAD420_FAN_X"][0]) - P14["frame"] / 2 - r420[0]
    build_radiator("rad420", M, r420[1] - r420[0], cn[1] - cn[0], cu[1] - cu[0], tank, hx, P14["pitch"], 15, "rad420")
    fu = HW["RAD420_FAN_U"]
    for k, x in enumerate(HW["RAD420_FAN_X"]):
        Mf = BS @ frame((x_to_v(x), fu[1], HW["RAD420_MID_N"]), (1, 0, 0), (0, -1, 0))
        build_fan(f"fan420_{k}", Mf, P14["frame"], fu[1] - fu[0], P14["pitch"], P14["opening_d"], 7, 0.2 + 0.9 * k, "rad420")

    # the two side fans, blowing out
    uc, nc = HW["FAN_CENTRE_UN"]
    for name, (x0, x1) in HW["FAN_SIDE_X"].items():
        inner = HW["FAN_SIDE_INNER_X"][name]
        out = -HW["FAN_SIDE_IN"][name]
        Mf = BS @ frame((x_to_v(inner), uc, nc), (0, 1, 0), (out, 0, 0))
        build_fan(name, Mf, HW["FAN_SIDE_U"][1] - HW["FAN_SIDE_U"][0], abs(x1 - x0), HW["FAN_PITCH"], HW["FAN_APERTURE_D"], 7, 0.9 if out > 0 else 0.1, name)

    # fittings: a ferrule where a hose leaves the CPU block or the card, and the port collar between the hose's end and the radiator's tank
    rise, port_r = HW["RAD420_PORT_RISE"], HW["RAD420_PORT_D"] / 2
    fit = MB()
    for name, kind, P, r in TUBES:
        if not kind.startswith("hose"):
            continue
        for end, nxt, at_rad in ((P[0], P[1], False), (P[-1], P[-2], True)):
            e = Vector(end)
            d = (Vector(nxt) - e).normalized()            # along the hose, away from its end
            if at_rad:                                    # the hose runs into the port collar; no ferrule here, the CPU hose guide grips the hose right at the port
                fit.cyl(e + 0.5 * d, e - rise * d, port_r, 36)
                fit.cyl(e - (rise - 5.0) * d, e - rise * d, port_r + 2.0, 6)
            else:
                fit.cyl(e - 1.0 * d, e + 15.0 * d, r + 2.0, 32)
                fit.cyl(e + 15.0 * d, e + 17.0 * d, r + 2.0, 32, r1=r + 0.6)
                fit.cyl(e + 0.5 * d, e - 3.0 * d, r + 3.5, 6)
    fit.obj("hose_fittings", "black_nickel", WORLD, None, bevel=0.5)


# ---------------------------------------------------------------------------------------------------------------------
# Motherboard, memory, CPU block, graphics card
# ---------------------------------------------------------------------------------------------------------------------
def fins(mb, v0, v1, u0, u1, n0, n1, base, along, count):
    """A heatsink: a base and `count` fins standing on it, running along 'v' or 'u'."""
    mb.box(v0, v1, u0, u1, n0, n0 + base)
    span = (u1 - u0) if along == "v" else (v1 - v0)
    w = span / (2 * count - 1)
    for k in range(count):
        a = 2 * k * w
        if along == "v":
            mb.box(v0, v1, u0 + a, u0 + a + w, n0 + base, n1)
        else:
            mb.box(v0 + a, v0 + a + w, u0, u1, n0 + base, n1)


def cable_end(name):
    """Board-space end point of a cable's last strands: (points, radius)."""
    ends = [(bs_of(P[-1])[0], r) for n, k, P, r in TUBES if n.startswith("cable_" + name + "_")]
    return ends


def build_board():
    b = HW["BOARD_BS"]
    pcb = MB().prism([rect(b[0], b[1], b[2], b[3])] + [circle(v, u, HW["ATX_HOLE_D"] / 2, 16) for v, u in HW["ATX_HOLES"]], -1.6, 0.0)
    pcb.obj("board_pcb", "pcb", BS, "board", smooth=None)
    scr = MB()
    for v, u in HW["ATX_HOLES"]:
        scr.cyl((v, u, 0.0), (v, u, 2.2), 3.3, 20)
    scr.obj("board_screws", "black_nickel", BS, None, bevel=0.4)

    io = HW["IO_ZONE_BS"]
    u0, u1 = io[2] + 1.5, b[3] - 1.0
    hs = MB()
    hs.box(2, 46, u0, u1, 0, 40)                                          # rear I/O block and its cover
    fins(hs, 49, 85, 162, 292, 0, 30, 9, "u", 6)                           # VRM heatsink beside the socket
    fins(hs, 56, 172, 267, 290, 0, 26, 9, "v", 4)                          # VRM heatsink above the socket
    hs.obj("board_heatsinks", "heatsink", BS, None, bevel=1.0)
    plate = MB().box(-1.2, 0.0, u0, u1, -1.6, 40.0)
    plate.obj("board_io_plate", "heatsink_black", BS, None, smooth=None)
    ports, gold = MB(), MB()
    for pu, pw, pn, ph in ((160, 14, 6, 15), (178, 14, 6, 15), (196, 16, 4, 14), (196, 14, 20, 15), (216, 14, 6, 15), (234, 14, 6, 15), (252, 16, 5, 7), (252, 9, 16, 4)):
        ports.box(-1.5, -1.2, pu, pu + pw, pn, pn + ph)
    for pu in (274, 290):
        gold.cyl((-9.0, pu, 14.0), (-1.2, pu, 14.0), 3.1, 20)
    for k in range(5):
        ports.cyl((-1.6, 272 + 6.5 * k, 30.0), (-1.2, 272 + 6.5 * k, 30.0), 2.6, 16)
    ports.obj("board_io_ports", "void", BS, None, smooth=None)
    gold.obj("board_antenna_posts", "gold", BS, None)

    covers = MB()
    covers.box(60, 178, 132, 150, 0, 6.5)                                  # M.2 cover under the socket
    covers.box(50, 142, 30, 56, 0, 6.5)                                    # M.2 cover between the lower slots
    covers.box(150, 228, 28, 72, 0, 9.5)                                   # chipset heatsink
    covers.obj("board_covers", "heatsink", BS, None, bevel=1.2)

    slots, latch = MB(), MB()
    for k in (0, 2, 5):
        u = HW["SLOT_U"][k]
        slots.box(46, 135, u - 3.7, u + 3.7, 0, 10.5)
        latch.box(135, 141, u - 3.7, u + 3.7, 0, 9.0)
    slots.obj("board_slots", "slot", BS, None, bevel=0.5)
    latch.obj("board_slot_latches", "plastic_grey", BS, None, bevel=0.5)

    # memory: four sticks in the block-out's box
    d = HW["DIMMS_BS"]
    n_st = 4
    step = (d[1] - d[0]) / n_st
    sl, st, bar = MB(), MB(), MB()
    for k in range(n_st):
        vc = d[0] + step * (k + 0.5)
        sl.box(vc - 3.2, vc + 3.2, d[2] + 1, d[3] - 1, 0, 5.5)
        st.box(vc - 2.9, vc + 2.9, d[2] + 6.3, d[3] - 4.3, 5.5, 40.5)
        bar.box(vc - 2.1, vc + 2.1, d[2] + 8.0, d[3] - 6.0, 40.5, 44.0)
    sl.obj("dimm_slots", "slot", BS, "dimms", bevel=0.4)
    st.obj("dimm_sticks", "heatsink_black", BS, "dimms", bevel=0.8)
    bar.obj("dimm_bars", "plastic_grey", BS, "dimms", bevel=0.8)

    # headers, and a plug on every cable's end
    top = HW["HEADER_TOP_N"]
    hd, plugs = MB(), MB()
    a = HW["ATX24_BS"]
    hd.box(a[0] + 7.5, a[1], a[2] + 2, a[3], 0, top)
    e = HW["EPS_BS"]
    for nm in ("CPU_PWR1", "CPU_PWR2"):
        v, u = HW["HEADERS"][nm]
        hd.box(v - 7, v + 7, e[2] + 3.5, e[3] - 0.5, 0, top)
    big = {"ATX_PWR1", "CPU_PWR1", "CPU_PWR2"}
    for nm, (v, u) in HW["HEADERS"].items():
        if nm in big:
            continue
        if nm in HW["HEADERS_LYING"]:
            hd.box(v - 6, v + 5, u - 6.5, u + 6.5, 0, 8.0)
        elif nm == "JUSB3":
            hd.box(v - 4.5, v + 4.5, u - 10, u + 10, 0, top)
        elif u > 150 or v > 122:
            hd.box(v - 2.5, v + 2.5, u - 5, u + 5, 0, 8.5) if v > 230 or v < 30 else hd.box(v - 5, v + 5, u - 2.5, u + 2.5, 0, 8.5)
        else:
            hd.box(v - 5, v + 5, u - 2.5, u + 2.5, 0, 8.5)
    hd.obj("board_headers", "slot", BS, None, bevel=0.3)
    for nm in HW["CABLES"]:
        ends = cable_end(nm)
        if not ends or nm == "gpu12v":             # the card's plug is built with the card
            continue
        P = np.array([p for p, r in ends])
        r = ends[0][1]
        if nm == "usbc":                                   # the lying plug: enters along -v, beside the board's edge
            p = P[0]
            L, th = HW["LYING_PLUG"]["length"], HW["LYING_PLUG"]["thick"]
            plugs.box(p[0], p[0] + L, p[1] - 6.0, p[1] + 6.0, p[2] - th / 2, p[2] + th / 2)
            continue
        n_end = float(P[:, 2].min())
        pad_v, pad_u = (5.5, 4.5) if r >= 4 else (4.0, 3.0)
        if nm == "usb3":
            pad_v, pad_u = 4.5, 10.0
        if nm.startswith("eps"):
            pad_v, pad_u = 7.0, 5.5
        plugs.box(P[:, 0].min() - pad_v, P[:, 0].max() + pad_v, P[:, 1].min() - pad_u, min(P[:, 1].max() + pad_u, b[3] + 4.0), min(n_end, 8.5), n_end + (14.0 if r >= 4 else 4.0))
    plugs.obj("board_plugs", "plastic_black", BS, None, bevel=0.5)


def build_cpu_block():
    sv, su = HW["CPU_SOCKET_VU"]
    R, top, base = HW["CPU_BODY_R"], HW["CPU_BODY_TOP_N"], HW["CPU_BASE_N"]
    body = MB().cyl((sv, su, base), (sv, su, top - 8.0), R, 96)
    body.prism([circle(sv, su, R, 96), circle(sv, su, R - 9.0, 72)], top - 8.0, top)
    lu = HW["CPU_LUG_U"]
    body.box(sv - HW["CPU_LUG_HALF_V"], sv + HW["CPU_LUG_HALF_V"], lu[0], lu[1] + 6.0, 24.0, HW["CPU_COLLAR_TOP_N"])
    body.obj("cpu_block_body", "plastic_black", BS, "cpu_block", bevel=1.5)
    ring = MB().prism([circle(sv, su, R - 8.6, 72), circle(sv, su, R - 10.4, 72)], top - 7.0, top - 0.4)
    ring.obj("cpu_block_ring", "gpu_accent", BS, "cpu_block")
    Mf = BS @ frame((sv, su, top - 1.5), (1, 0, 0), (0, 0, -1))
    hub, bl = rotor(10.0, R - 11.5, 8.0, 9, 0.3, z_lo=1.0, z_hi=6.5)
    hub.obj("cpu_block_fan_hub", "fan_blade", Mf, "cpu_block", bevel=0.8)
    bl.obj("cpu_block_fan_blades", "fan_blade", Mf, "cpu_block", smooth=180.0, solidify=0.8, subsurf=1)
    gr = MB()
    for r in (13.0, 21.0, 29.0):
        gr.tube([(sv + r * math.cos(a), su + r * math.sin(a), top - 0.9) for a in np.linspace(0, 2 * PI, 64, endpoint=False)], 0.7, 8, closed=True)
    for q in range(4):
        a = q * PI / 2 + PI / 4
        gr.tube([(sv + r * math.cos(a), su + r * math.sin(a), top - 0.9) for r in (4.0, R - 9.5)], 0.9, 8)
    gr.cyl((sv, su, top - 1.6), (sv, su, top - 0.2), 6.0, 32)
    gr.obj("cpu_block_grille", "black_nickel", BS, "cpu_block", smooth=180.0)
    mount = MB()
    for q in range(4):
        a = q * PI / 2 + PI / 4
        x, y = sv + 55.0 * math.cos(a), su + 55.0 * math.sin(a)
        mount.cyl((x, y, 0.0), (x, y, 19.0), 4.2, 20)
    for a in (PI / 4, -PI / 4):
        mount.merge(MB().box(-57.0, 57.0, -6.0, 6.0, base + 1.0, base + 4.0), Matrix.Translation((sv, su, 0)) @ Matrix.Rotation(a, 4, "Z"))
    mount.obj("cpu_block_mount", "black_nickel", BS, None, bevel=0.5)


def build_gpu():
    g = HW["GPU_BS"]
    v0, v1, u0, u1, n1 = 0.0, g[1], g[2], g[3], g[5]
    slot_u, under = HW["GPU_SLOT_U"], HW["GPU_UNDERSIDE_N"]
    sock = HW["GPU_PWR_SOCKET"]
    mouth = n1 - sock["recess"]
    pcb = MB().box(v0, v1 - 8, slot_u - 0.8, slot_u + 0.8, under, n1 - 10)
    pcb.box(48, 133, slot_u - 0.8, slot_u + 0.8, 4.0, under)
    pcb.obj("gpu_pcb", "pcb", BS, "gpu", smooth=None)

    notch = (sock["v"] - 15.0, sock["v"] + 15.0, sock["u"] - 7.5, u1 + 1.0, mouth, n1 + 1.0)
    fan_v, fan_n, fan_r = 186.0, (under + n1) / 2 + 1.0, 46.0
    shroud = MB().box(v0 + 2, v1, u0 + 2.0, slot_u - 0.8, under + 1.0, n1 - 0.3).obj("gpu_shroud", "gpu_shroud", BS, "gpu")
    cut = [MB().box(*notch).obj("cut_notch", "void", BS),
           MB().cyl((fan_v, u0 - 1.0, fan_n), (fan_v, u0 + 17.0, fan_n), fan_r, 96).obj("cut_fan", "void", BS)]
    boolean_cut(shroud, cut)
    md = shroud.modifiers.new("bevel", "BEVEL")
    md.width, md.segments, md.limit_method, md.angle_limit = 2.2 * MM, 3, "ANGLE", math.radians(35)

    back = MB().box(v0, v1, slot_u + 0.8, u1, under + 1.0, n1).obj("gpu_backplate", "gpu_back", BS, "gpu")
    boolean_cut(back, [MB().box(*notch).obj("cut_notch2", "void", BS)])
    md = back.modifiers.new("bevel", "BEVEL")
    md.width, md.segments, md.limit_method, md.angle_limit = 0.6 * MM, 2, "ANGLE", math.radians(35)

    # the cooler's face (looks down and forward): a plate with the fan's opening and two accent bars
    face = MB().prism([rrect(v0 + 8, v1 - 6, under + 6, n1 - 6, 6.0), circle(fan_v, fan_n, fan_r - 1.5, 96)], 0.0, 2.0)
    face.obj("gpu_face", "gpu_back", BS @ frame((0, u0 + 2.0, 0), (1, 0, 0), (0, -1, 0)), "gpu", bevel=0.5)
    acc = MB()
    acc.box(v0 + 16, fan_v - fan_r - 14, u0 - 0.0, u0 + 0.6, n1 - 34, n1 - 30)
    acc.box(v0 + 16, fan_v - fan_r - 30, u0 - 0.0, u0 + 0.6, under + 26, under + 30)
    acc.obj("gpu_accents", "gpu_accent", BS, "gpu", smooth=None)
    Mf = BS @ frame((fan_v, u0 + 3.0, fan_n), (1, 0, 0), (0, 1, 0))
    hub, bl = rotor(15.0, fan_r - 3.0, 13.0, 11, 0.4, z_lo=0.5, z_hi=11.0)
    hub.obj("gpu_fan_hub", "fan_blade", Mf, "gpu", bevel=1.0)
    bl.obj("gpu_fan_blades", "fan_blade", Mf, "gpu", smooth=180.0, solidify=1.0, subsurf=1)
    MB().cyl((0, 0, 0.2), (0, 0, 0.5), 11.0, 40).obj("gpu_fan_cap", "fan_sticker", Mf, "gpu")

    top = MB()                                       # the lettering face: a raised panel, an inlay and a row of vents, so the shroud has some shape
    top.prism([rrect(v0 + 10, sock["v"] - 22, u0 + 5, slot_u - 6, 3.0)], n1 - 0.3, n1)
    top.prism([rrect(sock["v"] + 22, v1 - 8, u0 + 5, slot_u - 6, 3.0)], n1 - 0.3, n1)
    top.obj("gpu_top_panels", "gpu_back", BS, "gpu", bevel=0.25)
    inlay = MB().box(v0 + 16, sock["v"] - 30, slot_u - 14.0, slot_u - 11.0, n1 - 0.2, n1)
    inlay.obj("gpu_top_inlay", "gpu_accent", BS, "gpu", smooth=None)
    vents = MB()
    for k in range(12):
        vents.box(v0 + 18 + 7.0 * k, v0 + 21.5 + 7.0 * k, u0 + 10, u0 + 30, n1 - 0.05, n1)
    vents.obj("gpu_top_vents", "void", BS, "gpu", smooth=None)
    # the lettering face (n = top): a softly lit strip, no lettering; the 12V-2x6 socket in its notch with the cable's plug
    MB().box(v0 + 150, v1 - 16, u0 + 8.5, u0 + 12.0, n1 - 1.2, n1).obj("gpu_lit_strip", "gpu_strip", BS, "gpu", smooth=None)
    MB().box(sock["v"] - 9.5, sock["v"] + 9.5, sock["u"] - 4.5, sock["u"] + 4.5, mouth - 9.0, mouth).obj("gpu_pwr_socket", "slot", BS, "gpu", smooth=None)
    plug = MB().box(sock["v"] - 10.5, sock["v"] + 10.5, sock["u"] - 6.0, sock["u"] + 6.0, mouth, mouth + HW["GPU12V_PLUG"])
    plug.obj("gpu_pwr_plug", "plastic_black", BS, None, bevel=0.6)

    # the bracket: two slots wide, its tab on the surface hardware.py names, vents and four ports drawn on it
    tab = HW["GPU_BRACKET_TAB_N"]
    bu0, bu1 = u1 - 38.7, u1
    br = MB().box(g[0], g[0] + 1.0, bu0, bu1, -4.0, tab + 1.0)
    br.box(g[0] - 11.5, g[0] + 1.0, bu0, bu1 - 16.0, tab, tab + 1.0)
    br.obj("gpu_bracket", "steel", BS, None, smooth=None)
    marks = MB()
    for k in range(9):
        marks.box(g[0] - 0.15, g[0], bu0 + 3.0, bu0 + 15.0, 14 + 9.5 * k, 18 + 9.5 * k)
    for k in range(3):
        marks.box(g[0] - 0.15, g[0], bu1 - 15.0, bu1 - 9.5, 18 + 24.0 * k, 34.5 + 24.0 * k)
    marks.box(g[0] - 0.15, g[0], bu1 - 15.0, bu1 - 9.0, 90, 105)
    marks.obj("gpu_bracket_marks", "void", BS, None, smooth=None)
    # where the hoses leave the card's end
    ends = [bs_of(P[0])[0] for n, k, P, r in TUBES if k == "hose_gpu"]
    blk = MB().box(v1 - 9, v1, min(e[1] for e in ends) - 12, max(e[1] for e in ends) + 12, min(e[2] for e in ends) - 13, max(e[2] for e in ends) + 13)
    blk.obj("gpu_hose_block", "gpu_accent", BS, "gpu", bevel=1.0)


# ---------------------------------------------------------------------------------------------------------------------
# Power supply, front I/O, light line, drives
# ---------------------------------------------------------------------------------------------------------------------
def build_psu():
    x0, x1, y0, y1, z0, z1 = HW["PSU_W"]
    cx, cy, R = (x0 + x1) / 2, (y0 + y1) / 2, 59.0
    split = z1 - 24.0
    body = MB().box(x0, x1, y0 + 1.5, y1 - 1.0, z0, split)
    body.prism([rect(x0, x1, y0 + 1.5, y1 - 1.0), circle(cx, cy, R, 96)], split, z1)
    body.obj("psu_body", "psu", WORLD, "psu", bevel=0.8)
    Mf = frame((cx, cy, z1 - 2.5), (1, 0, 0), (0, 0, -1))
    hub, bl = rotor(19.0, R - 2.5, 20.0, 9, 0.7, z_lo=1.0, z_hi=17.0)
    hub.obj("psu_fan_hub", "fan_blade", Mf, "psu", bevel=1.0)
    bl.obj("psu_fan_blades", "fan_blade", Mf, "psu", smooth=180.0, solidify=1.3, subsurf=1)
    gr = MB()
    for r in np.arange(12.0, R, 6.5):
        gr.tube([(cx + r * math.cos(a), cy + r * math.sin(a), z1 - 0.9) for a in np.linspace(0, 2 * PI, 96, endpoint=False)], 0.75, 8, closed=True)
    for q in range(4):
        a = q * PI / 2 + PI / 4
        gr.tube([(cx + r * math.cos(a), cy + r * math.sin(a), z1 - 0.9) for r in (9.0, R + 1.0)], 0.9, 8)
    gr.cyl((cx, cy, z1 - 2.2), (cx, cy, z1 - 0.1), 11.0, 40)
    gr.obj("psu_grille", "black_nickel", WORLD, "psu", smooth=180.0)

    # modular face (Y = y0): every socket of the field, and a plug on each cable that starts here
    field = HW["PSU_SOCKET_FIELD"]
    socks = MB()

    def sock(x, z, w, h):
        socks.box(x - w / 2, x + w / 2, y0, y0 + 2.0, z - h / 2, z + h / 2)

    for name, (x, y, z) in field.items():
        if name == "mb":
            sock(x - 19.5, z, 22.0, 10.5)
            sock(x + 11.5, z, 37.0, 10.5)
        elif name.startswith("gpu"):
            sock(x, z, 20.0, 9.5)
        else:
            sock(x, z, 13.5, 13.5)
    for x in (18.5, 33.5, 48.5):
        for z in (49.0, 67.0):
            sock(x, z, 12.5, 9.5)
    socks.obj("psu_sockets", "slot", WORLD, "psu", bevel=0.4)
    plugs = MB()
    for name, kind, P, r in TUBES:
        if kind == "cable" and name.endswith("_0") and abs(P[0][1] - y0) < 1.0:
            x, _, z = P[0]
            w, h = (62.0, 11.5) if r > 10 else (20.5, 10.5) if r > 6.5 else (14.5, 14.5)
            plugs.box(x - w / 2, x + w / 2, y0 - 15.0, y0 + 0.2, z - h / 2, z + h / 2)
    plugs.obj("psu_plugs", "plastic_black", WORLD, None, bevel=0.6)

    # rear face (Y = y1, seen through the bulkhead's window): inlet and switch on the -X side, perforation beside them
    rear = MB()
    rear.box(-62.0, -32.0, y1 - 1.0, y1 - 0.4, 30.0, 56.0)
    rear.box(-22.0, -8.0, y1 - 1.0, y1 - 0.4, 33.0, 53.0)
    for i in range(11):
        for j in range(10):
            rear.cyl((4.0 + 5.6 * i + (2.8 if j % 2 else 0.0), y1 - 1.0, 14.0 + 6.2 * j), (4.0 + 5.6 * i + (2.8 if j % 2 else 0.0), y1 - 0.9, 14.0 + 6.2 * j), 2.5, 6)
    rear.obj("psu_rear_marks", "void", WORLD, "psu", smooth=None)
    pins = MB()
    for dx in (-8.0, 0.0, 8.0):
        pins.box(-47.0 + dx - 0.9, -47.0 + dx + 0.9, y1 - 0.4, y1 - 0.2, 40.0, 46.0)
    pins.box(-20.0, -10.0, y1 - 0.4, y1, 35.0, 51.0)
    pins.obj("psu_rear_pins", "plastic_grey", WORLD, "psu", bevel=0.2)


def build_front_io():
    x0, x1, y0, y1, z0, z1 = HW["FRONT_IO_W"]
    zc = (z0 + z1) / 2
    MB().box(x0, x1, y0 + 1.2, y1, z0, z1).obj("front_io_housing", "plastic_black", WORLD, "front_io", bevel=0.5)
    # the row, from the power button at the -X end (the USB cables leave at the +X end, where the sill's window is)
    xb = x0 + 5.0 + HW["FRONT_IO_BUTTON_D"] / 2
    xs = [xb + o for o in HW["FRONT_IO_OFFSETS"]]
    row = dict(zip(["power", "phones", "mic", "usb_a1", "usb_a2", "usb_c"], xs))
    usb_a, usb_c = (13.4, 6.0), (9.2, 3.4)
    loops = [rrect(x0, x1, z0, z1, 1.5)]
    loops.append(circle(row["power"], zc, HW["FRONT_IO_BUTTON_D"] / 2 + 0.4, 48))
    loops += [circle(row[k], zc, 3.0, 24) for k in ("phones", "mic")]
    loops += [rrect(row[k] - usb_a[0] / 2, row[k] + usb_a[0] / 2, zc - usb_a[1] / 2, zc + usb_a[1] / 2, 0.6, 3) for k in ("usb_a1", "usb_a2")]
    loops.append(rrect(row["usb_c"] - usb_c[0] / 2, row["usb_c"] + usb_c[0] / 2, zc - usb_c[1] / 2, zc + usb_c[1] / 2, 1.6, 6))
    led0 = row["usb_c"] + usb_c[0] / 2 + 6.0
    led = (led0, min(led0 + HW["FRONT_IO_LED_SLIT_BEYOND"] - 6.0, x1 - 4.0))
    loops.append(rrect(led[0], led[1], zc - 0.8, zc + 0.8, 0.7, 3))
    Mface = frame((0, y0 + 1.2, 0), (1, 0, 0), (0, -1, 0))          # local x = X, local y = Z, local z = -Y: the plate lies in the front plane
    MB().prism(loops, 0.0, 1.0).obj("front_io_plate", "heatsink_black", Mface, "front_io", smooth=None)
    MB().box(x0 + 1, x1 - 1, y0 + 2.6, y0 + 3.0, z0 + 1, z1 - 1).obj("front_io_wells", "void", WORLD, "front_io", smooth=None)
    btn = MB().cyl((row["power"], y0 + 0.25, zc), (row["power"], y0 + 2.6, zc), HW["FRONT_IO_BUTTON_D"] / 2, 48)
    btn.obj("front_io_button", "gpu_accent", WORLD, "front_io", bevel=0.5)
    metal = MB()
    for k in ("phones", "mic"):
        metal.prism([circle(row[k], zc, 3.0, 24), circle(row[k], zc, 1.8, 16)], -0.7, 1.15)
    for k in ("usb_a1", "usb_a2"):
        metal.prism([rect(row[k] - usb_a[0] / 2, row[k] + usb_a[0] / 2, zc - usb_a[1] / 2, zc + usb_a[1] / 2),
                     rect(row[k] - usb_a[0] / 2 + 0.5, row[k] + usb_a[0] / 2 - 0.5, zc - usb_a[1] / 2 + 0.5, zc + usb_a[1] / 2 - 0.5)], -0.8, 1.15)
    metal.prism([rrect(row["usb_c"] - usb_c[0] / 2, row["usb_c"] + usb_c[0] / 2, zc - usb_c[1] / 2, zc + usb_c[1] / 2, 1.6, 6),
                 rrect(row["usb_c"] - usb_c[0] / 2 + 0.45, row["usb_c"] + usb_c[0] / 2 - 0.45, zc - usb_c[1] / 2 + 0.45, zc + usb_c[1] / 2 - 0.45, 1.2, 6)], -0.8, 1.15)
    metal.obj("front_io_shells", "steel", Mface, "front_io", smooth=None)
    tongues = MB()
    for k in ("usb_a1", "usb_a2"):
        tongues.box(row[k] - 5.6, row[k] + 5.6, zc - 2.3, zc - 0.4, -1.2, 1.0)
    tongues.box(row["usb_c"] - 3.3, row["usb_c"] + 3.3, zc - 0.35, zc + 0.35, -1.2, 1.0)
    tongues.obj("front_io_tongues", "plastic_grey", Mface, "front_io", smooth=None)
    MB().box(led[0], led[1], y0 + 1.4, y0 + 2.2, zc - 0.8, zc + 0.8).obj("front_io_led", "led_white", WORLD, "front_io", smooth=None)


def build_light_line():
    """The diffuser in the sill's slit: the exported cutter, kept just under the sill's face so that it glows in the slit."""
    V = bs_of(NPZ[MESH["light_slit"]["key"] + "_v"])
    lo, hi = V.min(axis=0), V.max(axis=0)
    top = HW["SILL"]["n_face"] - 0.25
    g = 0.05                                             # clear of the slit's walls, so the two surfaces do not coincide
    MB().box(lo[0] + g, hi[0] - g, lo[1] + g, hi[1] - g, lo[2] + g, top).obj("light_line", "light", BS, None, smooth=None)


def build_drives():
    lay = HW["DRIVE_LAYOUT"]
    sata = HW["DRIVE_SATA"]
    for side, sx in HW["DRIVE_SIDES"].items():
        def X(a, b):
            return sorted((sx * a, sx * b))
        o, i = lay["faces"]["outer"], lay["faces"]["inner"]
        xa, xb, ya, yb, za, zb = o["body"]
        d = o["dir"]
        MB().box(*X(xa, xb - 1.6 * d if d > 0 else xb), ya, yb, za, zb).obj(f"hdd_{side}_body", "hdd_body", WORLD, f"drive_{side}", bevel=1.0)
        MB().box(*X(xb - 1.6, xb), ya + 1.5, yb - 1.5, za + 1.5, zb - 1.5).obj(f"hdd_{side}_cover", "hdd_cover", WORLD, f"drive_{side}", bevel=0.5)
        xa2, xb2, ya2, yb2, za2, zb2 = i["body"]
        MB().box(*X(xa2, xb2), ya2, yb2, za2, zb2).obj(f"ssd_{side}", "plastic_black", WORLD, f"drive_{side}", bevel=0.6)
        con = MB()
        for f in (o, i):
            x = f["pb_x"] + f["dir"] * sata["above_bottom"]
            y = f["body"][2] + sata["from_edge"]
            con.box(*X(x - 0.01, x + f["dir"] * 3.4), y, y + sata["length"], f["body"][5] - 5.0, f["body"][5] - 0.2)
        con.obj(f"drive_{side}_sata", "slot", WORLD, f"drive_{side}", smooth=None)


# ---------------------------------------------------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------------------------------------------------
BS_BOXES = {"board", "gpu", "cpu_block", "rad360", "rad420", "dimms", "fan_side_right", "fan_side_left"}


def world_verts(ob):
    V = np.empty(len(ob.data.vertices) * 3)
    ob.data.vertices.foreach_get("co", V)
    V = V.reshape(-1, 3)
    M = np.array(ob.matrix_world)
    return (V @ M[:3, :3].T + M[:3, 3]) / MM


def run_checks():
    bad = 0
    groups = {}
    for ob, tag in STANDINS:
        if tag:
            groups.setdefault(tag, []).append(world_verts(ob))
    for tag, parts in sorted(groups.items()):
        V = np.vstack(parts)
        box = NPZ[MESH[tag]["key"] + "_v"].astype(np.float64)
        if tag in BS_BOXES:
            V, box = bs_of(V), bs_of(box)
        over = np.maximum(box.min(axis=0) - V.min(axis=0), V.max(axis=0) - box.max(axis=0)).max()
        ok = over < 0.06
        bad += not ok
        print(f"bounds  {tag:16s} {'ok  ' if ok else 'FAIL'} stand-in reaches {max(over, 0.0):.2f} mm past its box; fills "
              + " x ".join(f"{a:.0f}/{b:.0f}" for a, b in zip(V.max(axis=0) - V.min(axis=0), box.max(axis=0) - box.min(axis=0))))
    trees = []
    for ob, tag in STANDINS:
        if ob.name.endswith("_fins") or ob.name in ("hose_fittings",):
            continue
        V = world_verts(ob)
        polys = [tuple(p.vertices) for p in ob.data.polygons]
        trees.append((ob.name, BVHTree.FromPolygons([Vector(p) for p in V], polys)))
    for name, kind, P, r in TUBES:
        skip_end = max(30.0, 3.5 * r)          # a tube's own ends stand in a plug, a socket or a fitting
        s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
        mid = P[(s > skip_end) & (s < s[-1] - skip_end)]
        for oname, tree in trees:
            worst = None
            for p in mid:
                hit = tree.find_nearest(Vector(p), r)
                if hit[0] is not None and (worst is None or hit[3] < worst):
                    worst = hit[3]
            if worst is not None and worst < r - 0.3:
                bad += 1
                print(f"tubes   FAIL {name} (r {r}) comes within {worst:.1f} mm of the surface of {oname}")
    printed = []
    for ob in bpy.data.objects:
        if ob.type == "MESH" and any(c.name in ("skeleton", "organic") for c in ob.users_collection):
            V = world_verts(ob)
            printed.append((ob.name, BVHTree.FromPolygons([Vector(p) for p in V], [tuple(p.vertices) for p in ob.data.polygons])))
    for ob, tag in STANDINS:
        if tag is not None:
            continue
        V = world_verts(ob)
        tree = BVHTree.FromPolygons([Vector(p) for p in V], [tuple(p.vertices) for p in ob.data.polygons])
        for pname, ptree in printed:
            pairs = tree.overlap(ptree)
            if pairs:
                bad += 1
                print(f"frame   FAIL {ob.name} cuts {pname} ({len(pairs)} face pairs)")
    print(f"checks: {'all passed' if not bad else str(bad) + ' FAILED'}  ({time.time() - T0:.0f} s)")
    return bad


# ---------------------------------------------------------------------------------------------------------------------
# Stage, light, camera
# ---------------------------------------------------------------------------------------------------------------------
CENTRE = Vector((0.0, 190.0, 150.0))        # mm: about the middle of the build
VIEWS = {   # name: direction from the model to the eye, lens in mm, the box the camera frames (None = everything), room round it, f-stop
    "front_left": ((-0.80, -1.20, 0.52), 62.0, None, 0.06, None),
    "front_right": ((0.88, -1.12, 0.48), 62.0, None, 0.06, None),
    "rear": ((-0.85, 1.20, 0.50), 62.0, None, 0.06, None),
    "hero": ((-0.42, -1.0, 0.27), 80.0, (-215.0, 215.0, -5.0, 150.0, -15.0, 300.0), 0.02, 9.0),
    "inside": ((0.10, -0.75, 1.0), 62.0, None, 0.04, None),          # for looking at the board: use with --hide organic,rad360,fan360
    "left": ((-1.0, 0.25, 0.30), 62.0, None, 0.06, None),
}


def build_stage():
    desk_z = HW["DESK_Z"]
    rig = bpy.data.objects.new("rig", None)
    rig.location = Vector((CENTRE[0], CENTRE[1], 0.0)) * MM
    collection("stage").objects.link(rig)
    # a seamless sweep: the desk, rising into a wall behind the build
    prof = [(-4000.0, 0.0)] + [(2200.0 + 900.0 * math.sin(a), 900.0 - 900.0 * math.cos(a)) for a in np.linspace(0, PI / 2, 24)] + [(3100.0, 4500.0)]
    V = [(x, y, z + desk_z) for y, z in prof for x in (-6000.0, 6000.0)]
    F = [(2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2) for i in range(len(prof) - 1)]
    sweep = make_obj("sweep", V, F, "desk", coll="stage", smooth=180.0, weighted=False)
    sweep.parent = rig

    def area(name, loc, size, power, colour=(1, 1, 1), target=(0.0, 0.0, 0.18)):
        L = bpy.data.lights.new(name, "AREA")
        L.shape, L.size, L.size_y = "RECTANGLE", size[0], size[1]
        L.energy, L.color = power, colour
        ob = bpy.data.objects.new(name, L)
        ob.location = loc
        ob.rotation_euler = (Vector(loc) - Vector(target)).to_track_quat("Z", "Y").to_euler()
        ob.visible_camera = False
        ob.parent = rig
        collection("stage").objects.link(ob)
        return ob

    area("key", (-1.5, -1.3, 1.7), (1.6, 1.6), 90.0, (1.0, 0.97, 0.94))
    area("fill", (1.9, -1.2, 0.7), (1.8, 1.4), 22.0, (0.94, 0.97, 1.0))
    area("top", (0.1, 0.1, 2.3), (2.4, 1.6), 45.0)
    area("rim", (1.3, 1.5, 1.5), (0.9, 1.8), 110.0, (0.92, 0.96, 1.0))
    area("kicker", (-1.9, 1.0, 0.9), (0.5, 2.0), 45.0)
    area("low_front", (-0.2, -2.0, 0.25), (2.4, 0.5), 16.0)

    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    bpy.context.scene.world = world
    nt = world.node_tree
    bg = nt.nodes["Background"]
    hdr = os.path.join(bpy.utils.system_resource("DATAFILES"), "studiolights", "world", "studio.exr")
    if os.path.exists(hdr):          # the studio light probe that ships with Blender: something for the satin layer to reflect
        env = node(nt, "ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(hdr)
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 0.30
    else:
        bg.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1.0)
        bg.inputs["Strength"].default_value = 0.4
    return rig


def frame_points(box):
    if box is None:
        pts = []
        for ob in bpy.context.scene.objects:
            if ob.type == "MESH" and ob.name != "sweep" and not ob.hide_render:
                pts += [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        return pts
    x0, x1, y0, y1, z0, z1 = box
    return [Vector((x, y, z)) * MM for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]


def aim_camera(cam, rig, view):
    direction, lens, box, room, fstop = VIEWS[view]
    d = Vector(direction).normalized()
    rig.rotation_euler = (0.0, 0.0, math.atan2(d.x, -d.y))
    cam.data.lens = lens
    cam.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
    bpy.context.view_layer.update()
    pts = frame_points(box)
    loc, _ = cam.camera_fit_coords(bpy.context.evaluated_depsgraph_get(), [c for p in pts for c in p])
    mid = sum(pts, Vector()) / len(pts)
    cam.location = loc + d * room * (loc - mid).length
    cam.data.dof.use_dof = fstop is not None
    if fstop is not None:
        cam.data.dof.aperture_fstop = fstop
        cam.data.dof.focus_distance = (cam.location - Vector((0.0, 0.03, 0.09))).length     # on the sill
    bpy.context.view_layer.update()


def setup_render():
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    w, h = (int(x) for x in ARGS.res.lower().split("x"))
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = w, h, 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.film_transparent = False
    c = sc.cycles
    c.samples = ARGS.samples
    c.use_adaptive_sampling, c.adaptive_threshold = True, 0.008
    c.use_denoising = True
    try:
        c.denoiser = "OPENIMAGEDENOISE"
        c.denoising_use_gpu = ARGS.device == "GPU"
    except Exception as e:      # noqa: BLE001
        print("denoiser:", e)
    c.max_bounces, c.diffuse_bounces, c.glossy_bounces = 8, 4, 6
    c.sample_clamp_indirect = 8.0
    device = "CPU"
    if ARGS.device == "GPU":
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for kind in ("OPTIX", "CUDA"):
            try:
                prefs.compute_device_type = kind
                prefs.refresh_devices()
                gpus = [dv for dv in prefs.devices if dv.type == kind]
                if gpus:
                    for dv in prefs.devices:
                        dv.use = dv.type == kind
                    device = kind + " " + gpus[0].name
                    break
            except Exception as e:      # noqa: BLE001
                print(kind, "not available:", e)
    c.device = "CPU" if device == "CPU" else "GPU"
    print("render device:", device)
    vs = sc.view_settings
    for vt in ("AgX", "Filmic", "Standard"):
        try:
            vs.view_transform = vt
            break
        except TypeError:
            pass
    for look in ("AgX - Medium High Contrast", "Medium High Contrast", "AgX - Base Contrast"):
        try:
            vs.look = look
            break
        except TypeError:
            pass
    vs.exposure = 0.25
    print("view transform:", vs.view_transform, "/", vs.look)
    try:                                 # a little bloom round the light line
        ng = bpy.data.node_groups.new("ossa_comp", "CompositorNodeTree")
        ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        rl, gl, out = ng.nodes.new("CompositorNodeRLayers"), ng.nodes.new("CompositorNodeGlare"), ng.nodes.new("NodeGroupOutput")
        gl.inputs["Type"].default_value = "Bloom"
        gl.inputs["Threshold"].default_value = 0.9
        gl.inputs["Strength"].default_value = 0.35
        gl.inputs["Size"].default_value = 0.35
        ng.links.new(rl.outputs["Image"], gl.inputs["Image"])
        ng.links.new(gl.outputs["Image"], out.inputs["Image"])
        sc.compositing_node_group = ng
    except Exception as e:      # noqa: BLE001
        print("no bloom:", e)
    return device


def main():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    make_materials()
    build_exact()
    build_cooling()
    build_board()
    build_cpu_block()
    build_gpu()
    build_psu()
    build_front_io()
    build_light_line()
    build_drives()
    print(f"scene built: {len(bpy.data.objects)} objects ({time.time() - T0:.0f} s)")
    bpy.context.view_layer.update()
    run_checks()
    for key in filter(None, ARGS.hide.split(",")):
        for ob in bpy.data.objects:
            if ob.name.startswith(key) or any(c.name == key for c in ob.users_collection):
                ob.hide_render = True
    rig = build_stage()
    cam = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    cam.data.sensor_width = 36.0
    cam.data.clip_start, cam.data.clip_end = 0.05, 50.0
    collection("stage").objects.link(cam)
    bpy.context.scene.camera = cam
    device = setup_render()
    if ARGS.blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(ARGS.blend))
    if ARGS.check_only:
        return
    os.makedirs(ARGS.out, exist_ok=True)
    for view in ARGS.views.split(","):
        aim_camera(cam, rig, view)
        path = os.path.join(os.path.abspath(ARGS.out), f"b6_render_{view}{ARGS.suffix}.png")
        bpy.context.scene.render.filepath = path
        t = time.time()
        bpy.ops.render.render(write_still=True)
        print(f"rendered {view}: {time.time() - t:.0f} s on {device} -> {path}")


main()
