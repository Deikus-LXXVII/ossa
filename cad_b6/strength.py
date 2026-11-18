#!/usr/bin/env python3
"""Strength and stiffness of the ABS skeleton without printing it, and plastic needed per infill.

Run:  .venv/bin/python cad_b6/strength.py [mesh_max_mm] [element order 1|2] [wall mm] [--focus]
Out:  cad_b6/report_strength.txt and the same on stdout
      --focus meshes the places in FOCUS finer and writes cad_b6/report_strength_focus.txt instead

Method (linear static finite elements, tetrahedra):
- every load-bearing part of frame_v0.py, without its holes, meshed together as one bonded body;
- fixed where the feet stand on the desk; loaded by the weight of each component at its mounts and
  by the frame's own weight;
- infill: an element within 1.6 mm of the surface is solid wall (4 perimeters); the rest is infill
  of fraction f with stiffness E * f^2 and density rho * f (Gibson-Ashby for an open cell core).
  Elements that straddle the wall get the volume-weighted mix.
Revision 11, second pass: the 420 is a body in the model. Its core (hardware.rad420, u 310..348) is meshed as a block of modulus E_CORE, tied to the
two antler plates only over a washer-sized patch at each of the twelve fan screws; its weight (the part along the slope) is a body force on the block, which
acts at its centre of mass. Every other component keeps its load model. `point` is the load model of the first pass: no radiator body, the radiator's
weight pushed into the plates as twelve point loads. The report gives both; `stiff` is the one the allowable is judged on (see REPORT_WHY).
What this does not cover: strength across layers and print orientation, creep under steady load
near warm radiators, pull-out of threaded inserts, slip in bolted joints (joints are taken as rigid).
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import time

import cadquery as cq
import gmsh
import numpy as np
from scipy.spatial import cKDTree
from skfem import Basis, BilinearForm, ElementTetP0, ElementTetP1, ElementTetP2, ElementVector, LinearForm, MeshTet, asm, condense, solve
from skfem.assembly.form.coo_data import COOData
from skfem.helpers import ddot, sym_grad, trace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frame_v0
import hardware as hw

HERE = os.path.dirname(os.path.abspath(__file__))

# --- material: printed ABS -------------------------------------------------
E0, NU = 2000.0, 0.35            # MPa; typical for printed ABS along the layers
RHO = 1.04e-9                    # tonne / mm^3
G = 9810.0                       # mm / s^2
WALL = 1.6                       # mm, four 0.4 mm perimeters
STRENGTH_IN_PLANE = 35.0         # MPa, typical tensile strength along the layers
STRENGTH_LAYER = frame_v0.ABS_STRENGTH_LAYER   # MPa, typical across the layers (revision 13: the numbers live in frame_v0.py, whose hand calculations of the fan bracket and the card's post use them)
SAFETY = frame_v0.ABS_SAFETY     # on the weaker direction, for creep, heat and print defects
ALLOW = STRENGTH_LAYER / SAFETY
INFILLS = (0.20, 0.40, 0.80, 1.00)

# --- the 420 as a stiff body (revision 11, second pass) ----------------------
# Modulus of the radiator core, MPa. It is a brazed aluminium assembly (flat tubes, fins, two end tanks, side plates); solid aluminium is 70000. The tubes and fins
# are thin, so the assembly is far less stiff than the metal: 10000 is about a seventh of it, five times the printed ABS's own 2000. What matters is the ratio to the
# 3 mm plate: the block's bending stiffness per mm of width, E t^3 / 12 over its 38 mm, is about ten thousand times the plate's. A lower figure for the metal is on
# the safe side (the less the block stiffens, the more the plates have to carry); STRENGTH_E_CORE overrides it to see how much it matters.
E_CORE = float(os.environ.get("STRENGTH_E_CORE", 10000.0))
MODELS = ("point", "stiff", "stiff-rigid")
MODEL_NAME = {"stiff-rigid": f"то же, но узлы пластины на пятне жёстко привязаны к ближайшим узлам тела (прямое прочтение «связь по пятну»; напряжение у края пятна растёт с измельчением сетки)",
              "point": "нагрузка точками в винтах (первый проход ревизии 11, радиатор без жёсткости)",
              "stiff": f"радиатор как жёсткое тело (E = {E_CORE:g} МПа), связь с пластинами только в 12 винтах, по пятну Ø{hw.RAD420_SCREW_PATCH_D:g} мм, вес в центре масс"}
REPORT_WHY = ("Допустимое напряжение пластин проверяется по случаю «жёсткое тело»: радиатор это паяная алюминиевая сборка 138 x 38 мм, по жёсткости на изгиб на порядки выше "
              "3 мм пластика, и двигается как одно тело; случай «точки» не даёт ему жёсткости и заставляет тонкие перемычки пластины самих разносить вес верхних винтов, "
              "чего настоящий радиатор не допускает. Это поправка модели нагрузки, не послабление допуска: допустимое то же.")

# --- loads, kg (see docs/plans and the hardware reports; rounded up) ----------
KG = dict(board=1.0, cpu_block=0.45, ram_ssd=0.2, card=frame_v0.CARD_KG, rad360=1.3, rad420=1.9, psu=3.2, fan140=frame_v0.FAN_KG)      # revision 14a: the card's mass lives in frame_v0.py, whose hand calculation of gpu_rest uses it
U_DIR = np.array([0.0, math.sqrt(0.5), math.sqrt(0.5)])
N_DIR = np.array([0.0, -math.sqrt(0.5), math.sqrt(0.5)])
DOWN = np.array([0.0, 0.0, -1.0])


def structural_parts():
    parts, _ = frame_v0.build_frame()
    # revision 14a: front_io_carrier hung from the sill's end blocks and touched nothing, so it was left out (a free body in the bonded mesh). Revision 18: it stands on beam_front's top face
    # and is screwed to it, so it is a body of the mesh like every part it touches
    return [p for p in parts if not p.name.startswith("hose_guide")]


# ---------------------------------------------------------------------------
# Plastic per infill
# ---------------------------------------------------------------------------
def mass_table(parts):
    rows, tot = [], np.zeros(len(INFILLS))
    for p in parts:
        vol, area = float(p.solid.Volume()), float(p.solid.Area())
        shell = min(area * WALL, vol)
        m = np.array([(shell + f * (vol - shell)) / 1000.0 * 1.04 for f in INFILLS])
        rows.append((p.name, vol / 1000.0, m))
        tot += m
    return rows, tot


# ---------------------------------------------------------------------------
# Mesh
# ---------------------------------------------------------------------------
# Places meshed finer with --focus: (world point, radius mm, mesh step mm). Revision 11 moved the antler: the root is where the tongue leaves the chord
# (X +-168, board u 363, n -22), where the plate leaves the chord (X +-175, u 349.5, n -17) and the plate's thin lower edge where it hangs without a chord
# (X +-130, n -17); the web between the middle fan and the next one is X +-72, n 40. A 7 mm mesh cannot resolve a 4 mm web, a corner or a fillet of a few mm.
_CN = frame_v0.CHORD_N
FOCUS = [((s * x, *hw.bp_yz(u, n)), 12.0, 1.5) for s in (-1, 1) for (x, u, n) in
         ((168.0, 363.0, _CN[0]), (frame_v0.CHORD_X0 + 20.0, 349.5, _CN[1]), (hw.RAD420_HOLES_X[-1], 349.5, hw.RAD420_HOLES_N[0]), (130.0, 349.5, _CN[1]), (70.0, 349.5, 40.0))]

# Regions of the 420's bracket, for the report: (label, |X| range, u range, n range) in board space; the largest wall stress (20 % infill) among the elements whose centre lies in each.
_PU = (hw.RAD420_PLATE_U[0] - 0.1, hw.RAD420_PLATE_U[1] + 0.1)
REGIONS = [("язык, стык с хордой (|X| 158..178, n < хорды)", (frame_v0.X_OUT, 178.0), frame_v0.CHORD_U, (-60.0, _CN[0])),
           ("хорда (|X| от 158, n -22..-17, u 338..388)", (frame_v0.CHORD_X0, 229.0), frame_v0.CHORD_U, _CN),
           ("корень пластины: над хордой (|X| от 158, n -17..-5)", (frame_v0.CHORD_X0, 229.0), _PU, (_CN[1], -5.0)),
           ("пластина без хорды, нижняя кромка (|X| < 158, n -17..-5)", (0.0, frame_v0.CHORD_X0), _PU, (_CN[1], -5.0)),
           ("перемычка между вентиляторами (|X| 68..72, n -5..124)", (67.9, 72.1), _PU, (-5.0, 124.0)),
           ("остальная пластина (n -5..124)", (0.0, 229.0), _PU, (-5.0, 124.0))]


def core_block():
    """The 420's core as a solid in the world: hardware.rad420's first solid (u 310..348)."""
    return hw.bs_box(*hw.RAD420_BS[:2], *hw.RAD420_CORE_U, *hw.RAD420_CORE_N)


def tie_points(side_signs=(1, -1)):
    """World points on the core's face u = RAD420_CORE_U[1] under each of the twelve fan screws."""
    u = hw.RAD420_CORE_U[1]
    return [np.array(hw.bp(hw.x_to_v(x), u, n)) for side in side_signs for (x, n) in frame_v0.antler_holes_xn(side)]


def build_mesh(parts, h_max, h_min, focus=(), stiff=False):
    """The skeleton as one bonded mesh. stiff=True adds the 420's core as a block that touches the antlers' plates; the nodes it shares with them are
    split in two (one for the block, one for the plate), so the block is joined to the plates only by the couplings of tie_matrix at the twelve screws.
    Returns (mesh, is_core per element)."""
    tmp = tempfile.mkdtemp()
    step = os.path.join(tmp, "skeleton.step")
    assy = cq.Assembly()
    for p in parts:
        assy.add(cq.Workplane("XY").newObject([p.blank if p.blank is not None else p.solid]), name=p.name)
    if stiff:
        assy.add(cq.Workplane("XY").newObject([core_block()]), name="rad420_core")
    assy.save(step)
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    vols = gmsh.model.occ.importShapes(step)
    vols = [v for v in vols if v[0] == 3]
    gmsh.model.occ.fragment(vols, [])                      # bond touching parts: shared faces, one mesh
    gmsh.model.occ.synchronize()
    gmsh.option.setNumber("Mesh.MeshSizeMax", h_max)
    gmsh.option.setNumber("Mesh.MeshSizeMin", h_min)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.Algorithm3D", 10)
    balls_at = list(focus)
    if stiff:                                              # the washer patches need a few nodes each: a finer mesh round the screws
        balls_at += [(tuple(c), 9.0, 2.5) for c in tie_points()]
    if balls_at:
        balls = []
        for (x, y, z), radius, h in balls_at:
            b = gmsh.model.mesh.field.add("Ball")
            for key, val in (("XCenter", x), ("YCenter", y), ("ZCenter", z), ("Radius", radius), ("Thickness", radius),
                             ("VIn", h), ("VOut", h_max)):
                gmsh.model.mesh.field.setNumber(b, key, val)
            balls.append(b)
        fmin = gmsh.model.mesh.field.add("Min")
        gmsh.model.mesh.field.setNumbers(fmin, "FieldsList", balls)
        gmsh.model.mesh.field.setAsBackgroundMesh(fmin)
        gmsh.option.setNumber("Mesh.MeshSizeMin", min(h_min, min(h for _, _, h in balls_at)))
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.model.mesh.generate(3)
    tags, coords, _ = gmsh.model.mesh.getNodes()
    pts = coords.reshape(-1, 3)
    index = np.zeros(int(tags.max()) + 1, dtype=np.int64)
    index[tags.astype(np.int64)] = np.arange(len(tags))
    tets, core_flags = [], []
    core_centre = np.array(hw.bp(sum(hw.RAD420_BS[:2]) / 2.0, sum(hw.RAD420_CORE_U) / 2.0, hw.RAD420_MID_N))
    for dim, tag in gmsh.model.getEntities(3):
        types, _, node_tags = gmsh.model.mesh.getElements(dim, tag)
        is_core = stiff and bool(np.linalg.norm(np.array(gmsh.model.occ.getCenterOfMass(dim, tag)) - core_centre) < 1.0)
        for t, nt in zip(types, node_tags):
            if t == 4:
                el = index[nt.astype(np.int64)].reshape(-1, 4)
                tets.append(el)
                core_flags.append(np.full(len(el), is_core))
    gmsh.finalize()
    t = np.vstack(tets)
    core_el = np.concatenate(core_flags)
    if stiff:
        assert core_el.any(), "the 420's core was not found among the meshed volumes"
        pts, t = split_core(pts, t, core_el)
    used = np.unique(t)
    remap = -np.ones(len(pts), dtype=np.int64)
    remap[used] = np.arange(len(used))
    return MeshTet(pts[used].T.copy(), remap[t].T.copy()), core_el


def split_core(pts, t, core_el):
    """Give the block its own copy of every node it shares with the plates, so the two are not bonded anywhere: the block and the plates meet only through the
    couplings at the twelve screws (tie_groups, tie_matrix). Returns the points and the tetrahedra."""
    shared = np.intersect1d(np.unique(t[core_el]), np.unique(t[~core_el]))
    remap = np.arange(len(pts))
    remap[shared] = np.arange(len(pts), len(pts) + len(shared))
    t = t.copy()
    t[core_el] = remap[t[core_el]]
    return np.vstack([pts, pts[shared]]), t


def tie_groups(mesh, is_core):
    """The twelve washer patches on the face where the block meets the plates (u = RAD420_CORE_U[1]): for each patch, the block's nodes and the plate's nodes
    on it with weights proportional to the face area each carries (they sum to 1 on each side). Returns [(core nodes, core weights, plate nodes, plate weights)]."""
    core_node = np.zeros(mesh.p.shape[1], bool)
    core_node[np.unique(mesh.t[:, is_core])] = True
    fac = mesh.facets[:, mesh.boundary_facets()].T
    P = mesh.p.T
    A, B, Cc = P[fac[:, 0]], P[fac[:, 1]], P[fac[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(B - A, Cc - A), axis=1)
    u_of = lambda q: hw.bs_of(*q)[1]
    u_face = hw.RAD420_CORE_U[1]
    on_plane = np.array([all(abs(u_of(q) - u_face) < 1e-3 for q in (a, b, c)) for a, b, c in zip(A, B, Cc)])
    cen = (A + B + Cc) / 3.0
    u_dir = np.array(hw.U_DIR)
    groups = []
    for c in tie_points():
        d = cen - c
        d = d - np.outer(d @ u_dir, u_dir)
        sel = on_plane & (np.linalg.norm(d, axis=1) <= hw.RAD420_SCREW_PATCH_D / 2.0)
        sides = []
        for want_core in (True, False):
            f = sel & (core_node[fac[:, 0]] == want_core)
            w = np.zeros(mesh.p.shape[1])
            for k in range(3):
                np.add.at(w, fac[f, k], area[f] / 3.0)
            nodes = np.where(w > 0)[0]
            sides += [nodes, w[nodes] / w[nodes].sum()]
        groups.append(tuple(sides))
    return groups


def tie_matrix(basis, groups, k, mesh=None, rigid=False):
    """Penalty coupling (k, N/mm) of the block to the plates at each patch: the average displacement of the block's nodes on the patch equals that of the plate's
    nodes on it, for each of the three components. The plate is not made rigid over the patch (that would make the stress at its rim grow without limit as the mesh is
    refined); the force the screw carries is spread over the patch's area, like a washer's bearing pressure."""
    rows, cols, vals = [], [], []
    for cn, cw, pn, pw in groups:
        for comp in range(3):
            if rigid:
                # the literal tie: every plate node on the patch moves with the block's nearest node. The stress at the patch's rim then grows as the mesh is refined
                # (a rigid punch on an elastic plate), so this variant is a sensitivity run, not the case the allowable is judged on.
                _, near_c = cKDTree(mesh.p.T[cn]).query(mesh.p.T[pn])
                for pi, ci in zip(pn, cn[near_c]):
                    dofs = np.array([basis.nodal_dofs[comp, ci], basis.nodal_dofs[comp, pi]])
                    rows.append(np.repeat(dofs, 2))
                    cols.append(np.tile(dofs, 2))
                    vals.append(k * np.array([1.0, -1.0, -1.0, 1.0]))
                continue
            dofs = np.concatenate([basis.nodal_dofs[comp, cn], basis.nodal_dofs[comp, pn]])
            coef = np.concatenate([cw, -pw])
            rows.append(np.repeat(dofs, len(dofs)))
            cols.append(np.tile(dofs, len(dofs)))
            vals.append(k * np.outer(coef, coef).ravel())
    import scipy.sparse as sp
    return sp.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(basis.N, basis.N)).tocsr()


def wall_fraction(mesh):
    """Fraction of each element that lies within WALL of the outer surface."""
    facets = mesh.facets[:, mesh.boundary_facets()]
    A, B, C = (mesh.p[:, facets[i]].T for i in range(3))
    area = 0.5 * np.linalg.norm(np.cross(B - A, C - A), axis=1)
    n = np.maximum((area / 0.6).astype(int), 1)            # about one sample per 0.6 mm^2
    rng = np.random.default_rng(1)
    idx = np.repeat(np.arange(len(area)), n)
    r1, r2 = np.sqrt(rng.random(len(idx))), rng.random(len(idx))
    samples = (1 - r1)[:, None] * A[idx] + (r1 * (1 - r2))[:, None] * B[idx] + (r1 * r2)[:, None] * C[idx]
    tree = cKDTree(np.vstack([samples, A, B, C]))
    P = mesh.p.T[mesh.t.T]                                  # (nel, 4, 3)
    cen = P.mean(axis=1)
    # a lattice of points inside each element, so the wall share is right even where elements are coarse
    m = 5
    bary = np.array([(i, j, k, m - i - j - k) for i in range(m + 1) for j in range(m + 1 - i)
                     for k in range(m + 1 - i - j)], dtype=float)
    bary = (bary + 0.25) / (m + 1.0)                        # pulled slightly inside
    pts = np.einsum("sb,ebc->esc", bary, P)
    d, _ = tree.query(pts.reshape(-1, 3), workers=-1)
    return (d.reshape(len(P), -1) < WALL).mean(axis=1), float(area.sum())


# ---------------------------------------------------------------------------
# Loads
# ---------------------------------------------------------------------------
def near(mesh, point, radius):
    d = np.linalg.norm(mesh.p.T - np.array(point), axis=1)
    idx = np.where(d < radius)[0]
    if len(idx) == 0:
        idx = np.array([int(np.argmin(d))])
    return idx


def load_vector(mesh, basis, stiff=False, scale=1.0):
    f = np.zeros(basis.N)
    log = []

    def push(label, nodes, force):
        for c in range(3):
            f[basis.nodal_dofs[c, nodes]] += force[c] / len(nodes)
        log.append(f"{label}: {np.linalg.norm(force):.1f} Н на {len(nodes)} узлов")

    g = 9.81 * scale
    # board with CPU block, memory, SSD and half the card through the slot: nine standoffs
    w_board = (KG["board"] + KG["cpu_block"] + KG["ram_ssd"] + 0.5 * KG["card"]) * g
    for v, u in hw.ATX_HOLES:
        push("стойка платы", near(mesh, hw.bp(v, u, hw.ATX_TRAY_N + 3.0), 7.0), DOWN * w_board / len(hw.ATX_HOLES))
    # the other half of the card: bracket post on the left, rest under the free end on the right
    gu0, gu1 = hw.GPU_BS[2], hw.GPU_BS[3]
    push("стойка планки карты", near(mesh, hw.bp(-12.0, (gu0 + gu1) / 2, 100.0), 14.0), DOWN * 0.25 * KG["card"] * g)
    push("упор под картой", near(mesh, hw.bp(hw.x_to_v(150.0), gu0 - 4.0, 80.0), 14.0), DOWN * 0.25 * KG["card"] * g)
    # 360 on its two arms: four screws
    for x in (hw.RAD360_HOLES_X[0], hw.RAD360_HOLES_X[-1]):
        for u in hw.RAD360_HOLES_U:
            push("винт радиатора 360", near(mesh, hw.bp(hw.x_to_v(x), u, hw.RAD360_INNER_N - 6.0), 9.0),
                 DOWN * KG["rad360"] * g / 4)
    # 420: its weight splits into a part square to the cradle and a part down the slope held by the antlers' plates (revision 11: clamped between the
    # fans and the core, so the load acts at the plate's mid-plane), 12 screws, six in each half. Stiff-body case: the down-slope part is a body force on the
    # radiator's core (core_load), so it reaches the plates through the ties at the screws and acts at the core's centre of mass; the cradle's part is as before.
    w420 = KG["rad420"] * g
    u_plate = sum(hw.RAD420_PLATE_U) / 2.0
    used = [(x, n) for side in (1, -1) for (x, n) in frame_v0.antler_holes_xn(side)]
    if not stiff:
        for x, n in used:
            push("винт радиатора 420", near(mesh, hw.bp(hw.x_to_v(x), u_plate, n), 9.0), -U_DIR * math.sqrt(0.5) * w420 / len(used))
    for s in (1, -1):
        cradle = np.array([hw.bp(hw.x_to_v(150.0 * s), u, hw.RAD420_BS[4] - 3.0) for u in np.linspace(316, 360, 6)])
        nodes = np.unique(np.concatenate([near(mesh, c, 9.0) for c in cradle]))
        # revision 11: the antlers' chord now passes 1 mm above the cradle; the cradle's load is carried by the rib's own nodes (n at or below the cradle's plane,
        # inside the rib's X range), not by the chord's
        pts = mesh.p.T[nodes]
        n_of = ((pts[:, 2] - hw.ORIGIN[2]) - (pts[:, 1] - hw.ORIGIN[1])) / hw.C / 2.0
        rib = (n_of < hw.RAD420_BS[4] - 2.5) & (np.abs(pts[:, 0]) < frame_v0.X_OUT + 0.01)
        nodes = nodes[rib] if rib.any() else nodes
        push("ложе радиатора 420", nodes, -N_DIR * math.sqrt(0.5) * w420 / 2)
    # PSU on the two skids
    p = mesh.p
    for y0, y1 in ((183.0, 207.0), (323.0, 347.0)):
        nodes = np.where((np.abs(p[0]) < 76) & (p[1] > y0) & (p[1] < y1) & (p[2] > -2.5) & (p[2] < 1.0))[0]
        push("поперечина под БП", nodes, DOWN * KG["psu"] * g / 2)
    # side fans on their brackets
    for name in hw.FAN_SIDE_NAMES:
        x = hw.FAN_SIDE_INNER_X[name] + 5.0 * hw.FAN_SIDE_IN[name]
        corners = [hw.FAN_SIDE_HOLES_UN[c] for c in "AC"]         # the two down-slope corners every bracket holds
        nodes = np.unique(np.concatenate([near(mesh, hw.bp(hw.x_to_v(x), u, n), 9.0) for u, n in corners]))
        push(f"кронштейн {name}", nodes, DOWN * KG["fan140"] * g)
    return f, log


@LinearForm
def core_force(v, w):
    return w["fx"] * v.value[0] + w["fy"] * v.value[1] + w["fz"] * v.value[2]


def core_load(mesh, basis, basis0, is_core, scale=1.0):
    """The part of the 420's weight along the slope as a body force on the core block: 0.71 of its weight, down the slope (-u), spread over the block's volume,
    so that the resultant acts at the block's centre of mass. Returns the load vector and its log line."""
    w = KG["rad420"] * 9.81 * scale * math.sqrt(0.5)
    vol = mesh_volumes(mesh)
    per_vol = np.where(is_core, w / vol[is_core].sum(), 0.0)
    d = -np.array(hw.U_DIR)
    f = asm(core_force, basis, fx=basis0.interpolate(per_vol * d[0]), fy=basis0.interpolate(per_vol * d[1]), fz=basis0.interpolate(per_vol * d[2]))
    return f, f"вес 420 вдоль уклона, тело радиатора: {w:.1f} Н в центре масс на {int(is_core.sum())} элементов"


@BilinearForm
def stiffness(u, v, w):
    return 2.0 * w["mu"] * ddot(sym_grad(u), sym_grad(v)) + w["lam"] * trace(sym_grad(u)) * trace(sym_grad(v))


@LinearForm
def self_weight(v, w):
    return -w["rho"] * G * v.value[2]


def accelerate_ldlt(A, b):
    """Solve the condensed stiffness system with Accelerate's sparse LDLT (macldlt), from its upper triangle. The stiffness is positive definite: a negative or
    zero pivot, or a residual far above a direct solve's, stops the run."""
    import macldlt
    import scipy.sparse as sp
    upper = sp.triu(A, format="csc")
    upper.sort_indices()
    ldlt = macldlt.LDLTSolver(upper, triangle="upper")
    neg, zero, _ = ldlt.inertia()
    if neg or zero:
        raise RuntimeError(f"stiffness not positive definite: {neg} negative and {zero} zero pivots")
    x = ldlt.solve(b)
    rel = np.linalg.norm(A @ x - b) / np.linalg.norm(b)
    if not rel < 1e-6:
        raise RuntimeError(f"Accelerate LDLT residual {rel:.1e}")
    return x


def pick_solver():
    """MKL Pardiso on all cores where pypardiso is installed (x86), else Accelerate's sparse LDLT on all cores where macldlt is installed (Apple
    silicon), else scikit-fem's default (SuperLU, one core). STRENGTH_SOLVER=scipy forces the default, to compare."""
    if os.environ.get("STRENGTH_SOLVER") != "scipy":
        try:
            import pypardiso
            return (lambda A, b, **kw: pypardiso.spsolve(A.tocsr(), b)), "MKL Pardiso, все ядра"
        except ImportError:
            pass
        try:
            import macldlt  # noqa: F401
            return (lambda A, b, **kw: accelerate_ldlt(A, b)), "Accelerate LDLT, все ядра"
        except ImportError:
            pass
    return None, "SuperLU, одно ядро"


SOLVER, SOLVER_NAME = pick_solver()


def unit_stiffness(mesh, basis, basis0):
    """Element stiffness matrices for a modulus of 1 MPa. With one Poisson ratio the stiffness is linear in each
    element's modulus, so every infill case scales these instead of assembling again (assembly is most of the run time)."""
    one = np.ones(mesh.t.shape[1])
    lam = one * NU / ((1 + NU) * (1 - 2 * NU))
    mu = one / (2 * (1 + NU))
    return stiffness.coo_data(basis, lam=basis0.interpolate(lam), mu=basis0.interpolate(mu))


def scaled_stiffness(unit, E):
    nb = unit.local_shape
    data = (unit.data.reshape(nb[1], nb[0], -1) * E).ravel()        # data[j, i, element], as scikit-fem lays it out
    return COOData(unit.indices, data, unit.shape, unit.local_shape).tocsr()


def solve_case(mesh, basis, basis0, frac, infill, f_ext, unit, gscale=1.0, is_core=None, k_tie=None):
    k = infill ** 2
    E = E0 * (frac + (1 - frac) * k)
    rho = RHO * (frac + (1 - frac) * infill)
    if is_core is not None and is_core.any():
        E = np.where(is_core, E_CORE, E)                    # the radiator: stiff, and its weight is the body force in f_ext, not gravity on its elements
        rho = np.where(is_core, 0.0, rho)
    K = scaled_stiffness(unit, E)
    if k_tie is not None:
        K = K + k_tie
    f = f_ext + gscale * asm(self_weight, basis, rho=basis0.interpolate(rho))
    feet = np.where(mesh.p[2] < -14.4)[0]
    D = basis.nodal_dofs[:, feet].ravel()
    u = solve(*condense(K, f, D=D), solver=SOLVER)
    # strain per element (constant for linear tetrahedra) -> stress in the wall material and in the infill
    grad = basis.interpolate(u).grad                        # (3, 3, nel, nqp)
    eps = 0.5 * (grad + np.transpose(grad, (1, 0, 2, 3))).mean(axis=3)
    tr = eps[0, 0] + eps[1, 1] + eps[2, 2]

    def von_mises(Emod):
        la = Emod * NU / ((1 + NU) * (1 - 2 * NU))
        m = Emod / (2 * (1 + NU))
        s = 2 * m * eps
        for i in range(3):
            s[i, i] = s[i, i] + la * tr
        return np.sqrt(0.5 * ((s[0, 0] - s[1, 1]) ** 2 + (s[1, 1] - s[2, 2]) ** 2 + (s[2, 2] - s[0, 0]) ** 2)
                       + 3 * (s[0, 1] ** 2 + s[1, 2] ** 2 + s[0, 2] ** 2))

    vm_wall = von_mises(E0)
    vm_core = von_mises(E0 * k)
    disp = u[basis.nodal_dofs].T                             # (nnodes, 3), at the mesh vertices
    return disp, vm_wall, vm_core, float(rho @ mesh_volumes(mesh)) * 1e6   # kg -> g via tonne


def mesh_volumes(mesh):
    P = mesh.p.T[mesh.t.T]
    return np.abs(np.einsum("ij,ij->i", P[:, 1] - P[:, 0], np.cross(P[:, 2] - P[:, 0], P[:, 3] - P[:, 0]))) / 6.0


_PREPARED = {}


def prepare(parts, h_max, order, focus, stiff):
    """Mesh, wall fraction, bases and unit element stiffness. The two stiff models share one mesh, so the second takes the first's instead of building it again."""
    key = (stiff, h_max, order, tuple(focus))
    if key not in _PREPARED:
        _PREPARED.clear()
        mesh, is_core = build_mesh(parts, h_max, 2.5, focus, stiff=stiff)
        frac, _ = wall_fraction(mesh)
        basis = Basis(mesh, ElementVector(ElementTetP2() if order == 2 else ElementTetP1()))
        basis0 = basis.with_element(ElementTetP0())
        _PREPARED[key] = (mesh, is_core, np.where(is_core, 0.0, frac), basis, basis0, unit_stiffness(mesh, basis, basis0))
    return _PREPARED[key]


def run_model(model, parts, h_max, order, focus):
    """One load model, every infill. Returns (lines for the report, summary) where the summary holds the plate's regional maxima, the 420's sag and the focus
    balls' maxima at 20 % infill."""
    stiff = model.startswith("stiff")
    t0 = time.time()
    out = [f"МОДЕЛЬ НАГРУЗКИ «{model}»: {MODEL_NAME[model]}"]
    mesh, is_core, frac, basis, basis0, unit = prepare(parts, h_max, order, focus, stiff)
    vol = mesh_volumes(mesh)
    abs_el = ~is_core
    out.append(f"СЕТКА: {mesh.t.shape[1]} тетраэдров ({int(is_core.sum())} в теле радиатора), {basis.N // 3} узлов расчёта, элементы порядка {order}, шаг до {h_max:g} мм; "
               f"объём ABS {vol[abs_el].sum() / 1000:.0f} см³; доля стенки по объёму {float((frac * vol)[abs_el].sum() / vol[abs_el].sum()) * 100:.0f} %; решатель: {SOLVER_NAME}")
    k_tie = None
    if stiff:
        groups = tie_groups(mesh, is_core)
        counts = [(len(g[0]), len(g[2])) for g in groups]
        how = ("узлы пластины на пятне жёстко привязаны к ближайшим узлам тела" if model == "stiff-rigid" else
               "среднее перемещение узлов тела на пятне равно среднему по узлам пластины, с весами по площади; пластина на пятне не делается жёсткой")
        out.append(f"Связь тела радиатора с пластинами: {len(groups)} пятен Ø{hw.RAD420_SCREW_PATCH_D:g} мм под винтами ({how}), узлов на пятне: тело {min(c for c, _ in counts)}..{max(c for c, _ in counts)}, пластина "
                   f"{min(p for _, p in counts)}..{max(p for _, p in counts)}; вне пятен грани не связаны.")
        assert min(min(c) for c in counts) >= 3, f"a screw patch has only {min(min(c) for c in counts)} nodes: refine the mesh round the screws"
        k_tie = tie_matrix(basis, groups, 1.0e3 * E_CORE * hw.RAD420_SCREW_PATCH_D, mesh, rigid=model == "stiff-rigid")
    f1, log = load_vector(mesh, basis, stiff)
    if stiff:
        fc, line = core_load(mesh, basis, basis0, is_core)
        f1 = f1 + fc
        log.append(line)
    out.append("НАГРУЗКИ (1 g): " + "; ".join(log))
    out.append(f"Допустимое напряжение в стенке: {ALLOW:.1f} МПа (прочность поперёк слоёв {STRENGTH_LAYER:.0f} МПа, запас {SAFETY:.0f})")
    out.append("")
    out.append(f"{'заполнение':>10} {'макс. прогиб':>13} {'у 420':>7} {'у 360':>7} {'стенка 99,9%':>13} {'стенка макс':>12} "
               f"{'запас':>6} {'заполн. 99,9%':>14} {'его прочн.':>10}")
    p420 = near(mesh, hw.bp(hw.x_to_v(hw.RAD420_HOLES_X[5]), sum(hw.RAD420_PLATE_U) / 2.0, hw.RAD420_HOLES_N[1]), 10.0)
    p360 = near(mesh, hw.bp(hw.x_to_v(hw.RAD360_HOLES_X[-1]), hw.RAD360_HOLES_U[0], hw.RAD360_INNER_N - 6.0), 10.0)
    pcore = np.unique(mesh.t[:, is_core]) if stiff else None
    worst, peaks, spots, regions, sag = None, [], [], [], {}
    cent = mesh.p.T[mesh.t.T].mean(axis=1)
    for infill in INFILLS:
        disp, vm_wall, vm_core, _ = solve_case(mesh, basis, basis0, frac, infill, f1, unit, is_core=is_core, k_tie=k_tie)
        mag = np.linalg.norm(disp, axis=1)
        mag_abs = np.where(np.isin(np.arange(len(mag)), np.unique(mesh.t[:, abs_el])), mag, 0.0)
        wall = vm_wall[(frac > 0.3) & abs_el]
        core = vm_core[(frac < 0.7) & abs_el] if infill < 1 else np.array([0.0])
        core_strength = 0.3 * infill ** 1.5 * STRENGTH_IN_PLANE
        p999 = float(np.percentile(wall, 99.9))
        out.append(f"{int(infill * 100):>9}% {mag_abs.max():>10.3f} мм {mag[p420].mean():>7.3f} {mag[p360].mean():>7.3f} "
                   f"{p999:>10.2f} МПа {wall.max():>9.2f} МПа {ALLOW / p999:>6.1f} "
                   f"{float(np.percentile(core, 99.9)):>11.3f} МПа {core_strength:>7.2f} МПа")
        if infill == INFILLS[0]:
            sag["plate_screw"] = float(mag[p420].mean())
            if stiff:
                sag["core"] = float(mag[pcore].mean())
            vm = np.where((frac > 0.3) & abs_el, vm_wall, 0.0)
            i = int(np.argmax(vm))
            c = cent[i]
            j = int(np.argmax(mag_abs))
            worst = (c, float(vm[i]), mesh.p.T[j], float(mag_abs[j]))
            for i in np.argsort(vm)[::-1]:                  # the five most loaded places, at least 30 mm apart
                if all(np.linalg.norm(cent[i] - q) > 30.0 for q, _ in peaks):
                    peaks.append((cent[i], float(vm[i])))
                    if len(peaks) == 5:
                        break
            ux, uy, uz = cent[:, 0], cent[:, 1], cent[:, 2]
            n_c = ((uz - hw.ORIGIN[2]) - (uy - hw.ORIGIN[1])) / hw.C / 2.0
            u_c = ((uz - hw.ORIGIN[2]) + (uy - hw.ORIGIN[1])) / hw.C / 2.0
            for label, (x0, x1), (c0, c1), (n0, n1) in REGIONS:
                sel = (np.abs(ux) >= x0) & (np.abs(ux) <= x1) & (u_c >= c0) & (u_c <= c1) & (n_c >= n0) & (n_c <= n1) & (frac > 0.3) & abs_el
                if sel.any():
                    i = int(np.argmax(np.where(sel, vm_wall, 0.0)))
                    regions.append((label, int(sel.sum()), float(vm_wall[i]), cent[i]))
            for point, radius, h in focus:
                inside = (np.linalg.norm(cent - np.array(point), axis=1) < radius) & abs_el
                spots.append((point, radius, h, int(inside.sum()), float(vm[inside].max()) if inside.any() else 0.0))
    out.append("")
    if worst:
        c, s_, pj, m = worst
        out.append(f"Самое нагруженное место при 20 %: {s_:.2f} МПа в точке X {c[0]:.0f}, Y {c[1]:.0f}, Z {c[2]:.0f}; "
                   f"наибольший прогиб {m:.3f} мм в точке X {pj[0]:.0f}, Y {pj[1]:.0f}, Z {pj[2]:.0f}.")
    if peaks:
        out.append("Пять самых нагруженных мест при 20 % (не ближе 30 мм друг к другу): "
                   + "; ".join(f"{s_:.2f} МПа в X {c[0]:.0f}, Y {c[1]:.0f}, Z {c[2]:.0f}" for c, s_ in peaks) + ".")
    for label, count, sv, c in regions:
        out.append(f"Антлер 420, {label}: {count} элементов стенки, наибольшее напряжение при 20 % {sv:.2f} МПа в X {c[0]:.0f}, Y {c[1]:.0f}, Z {c[2]:.0f} (допустимо {ALLOW:.1f}, запас {ALLOW / sv:.1f}).")
    for point, radius, h, count, s_ in spots:
        out.append(f"Мелкая сетка {h:g} мм в радиусе {radius:g} мм от X {point[0]:.0f}, Y {point[1]:.0f}, Z {point[2]:.0f}: "
                   f"{count} тетраэдров, наибольшее напряжение стенки при 20 % {s_:.2f} МПа (запас {ALLOW / s_:.1f}).")
    out.append(f"Прогиб 420 при 20 %: у верхнего внешнего винта пластины {sag['plate_screw']:.2f} мм" + (f", среднее по телу радиатора {sag['core']:.2f} мм" if stiff else "") + ".")
    out.append(f"Время расчёта модели «{model}» {time.time() - t0:.0f} с.")
    return out, dict(regions=regions, spots=spots, sag=sag, worst=worst, peaks=peaks)


def main():
    global WALL
    focus = FOCUS if "--focus" in sys.argv else ()
    argv = [a for a in sys.argv if a != "--focus"]
    h_max = float(argv[1]) if len(argv) > 1 else 7.0
    if len(argv) > 3:
        WALL = float(argv[3])                               # wall thickness, to compare perimeter counts
    wanted = [m for m in os.environ.get("STRENGTH_MODELS", "").split(",") if m]      # e.g. STRENGTH_MODELS=stiff to skip the point-load case
    models = tuple(m for m in MODELS if not wanted or m in wanted)
    out = []
    t0 = time.time()
    parts = structural_parts()
    rows, tot = mass_table(parts)
    out.append(f"ПЛАСТИК НА СКЕЛЕТ (ABS 1,04 г/см³; стенка {WALL:g} мм, остальное заполнение)")
    out.append(f"{'деталь':22}{'объём, см³':>11}" + "".join(f"{int(f * 100):>8}%" for f in INFILLS))
    for name, vol, m in rows:
        out.append(f"{name:22}{vol:11.1f}" + "".join(f"{x:9.0f}" for x in m))
    out.append(f"{'ИТОГО, г':22}{sum(r[1] for r in rows):11.1f}" + "".join(f"{x:9.0f}" for x in tot))
    out.append("")
    order = int(argv[2]) if len(argv) > 2 else 2
    summary = {}
    for model in models:
        lines, summary[model] = run_model(model, parts, h_max, order, focus)
        out += lines
        out.append("")
    out.append("Перенос в руках: расчёт линейный, при 2 g все прогибы и напряжения удваиваются, запас делится на 2.")
    if "point" in summary and "stiff" in summary:
        cols = [m for m in MODELS if m in summary]
        out.append("")
        out.append(f"ПЛАСТИНЫ 420, СЛУЧАИ РЯДОМ (стенка при 20 %, МПа; допустимо {ALLOW:.1f}; судится случай «stiff», запас в последней колонке)")
        out.append(f"{'место':64}" + "".join(f"{m:>13}" for m in cols) + f"{'запас stiff':>13}")
        tabs = {m: dict((r[0], r[2]) for r in summary[m]["regions"]) for m in cols}
        for label in tabs["stiff"]:
            out.append(f"{label:64}" + "".join(f"{tabs[m][label]:>13.2f}" if label in tabs[m] else f"{'-':>13}" for m in cols) + f"{ALLOW / tabs['stiff'][label]:>13.1f}")
        out.append(f"{'прогиб у верхнего внешнего винта пластины, мм':64}" + "".join(f"{summary[m]['sag']['plate_screw']:>13.2f}" for m in cols))
        out.append(f"{'прогиб тела радиатора (среднее), мм':64}" + "".join(f"{summary[m]['sag'].get('core', float('nan')):>13.2f}" for m in cols))
        out.append(f"Почему судится «stiff»: {REPORT_WHY}")
    out.append(f"Время расчёта {time.time() - t0:.0f} с.")
    text = "\n".join(out)
    with open(os.path.join(HERE, "report_strength_focus.txt" if "--focus" in sys.argv else "report_strength.txt"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
