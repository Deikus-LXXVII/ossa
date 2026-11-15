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
STRENGTH_LAYER = 20.0            # MPa, typical across the layers
SAFETY = 3.0                     # on the weaker direction, for creep, heat and print defects
ALLOW = STRENGTH_LAYER / SAFETY
INFILLS = (0.20, 0.40, 0.80, 1.00)

# --- loads, kg (see docs/plans and the hardware reports; rounded up) ----------
KG = dict(board=1.0, cpu_block=0.45, ram_ssd=0.2, card=1.6, rad360=1.3, rad420=1.9, psu=3.2, fan140=0.2)
U_DIR = np.array([0.0, math.sqrt(0.5), math.sqrt(0.5)])
N_DIR = np.array([0.0, -math.sqrt(0.5), math.sqrt(0.5)])
DOWN = np.array([0.0, 0.0, -1.0])


def structural_parts():
    parts, _ = frame_v0.build_frame()
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
# Places meshed finer with --focus: (world point, radius mm, mesh step mm). The peak of the coarse run sits here, in the inner
# corner where the antler's tongue leaves the bar; a 7 mm mesh cannot resolve a corner or a fillet of a few mm.
FOCUS = [((-167.0, 340.0, 284.0), 12.0, 1.5), ((167.0, 340.0, 284.0), 12.0, 1.5)]      # 25 mm balls did not finish in 30 min on one core


def build_mesh(parts, h_max, h_min, focus=()):
    tmp = tempfile.mkdtemp()
    step = os.path.join(tmp, "skeleton.step")
    assy = cq.Assembly()
    for p in parts:
        assy.add(cq.Workplane("XY").newObject([p.blank if p.blank is not None else p.solid]), name=p.name)
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
    if focus:
        balls = []
        for (x, y, z), radius, h in focus:
            b = gmsh.model.mesh.field.add("Ball")
            for key, val in (("XCenter", x), ("YCenter", y), ("ZCenter", z), ("Radius", radius), ("Thickness", radius),
                             ("VIn", h), ("VOut", h_max)):
                gmsh.model.mesh.field.setNumber(b, key, val)
            balls.append(b)
        fmin = gmsh.model.mesh.field.add("Min")
        gmsh.model.mesh.field.setNumbers(fmin, "FieldsList", balls)
        gmsh.model.mesh.field.setAsBackgroundMesh(fmin)
        gmsh.option.setNumber("Mesh.MeshSizeMin", min(h_min, min(h for _, _, h in focus)))
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.model.mesh.generate(3)
    tags, coords, _ = gmsh.model.mesh.getNodes()
    pts = coords.reshape(-1, 3)
    index = np.zeros(int(tags.max()) + 1, dtype=np.int64)
    index[tags.astype(np.int64)] = np.arange(len(tags))
    tets = []
    for dim, tag in gmsh.model.getEntities(3):
        types, _, node_tags = gmsh.model.mesh.getElements(dim, tag)
        for t, nt in zip(types, node_tags):
            if t == 4:
                tets.append(index[nt.astype(np.int64)].reshape(-1, 4))
    gmsh.finalize()
    t = np.vstack(tets)
    used = np.unique(t)
    remap = -np.ones(len(pts), dtype=np.int64)
    remap[used] = np.arange(len(used))
    return MeshTet(pts[used].T.copy(), remap[t].T.copy())


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
    d, _ = tree.query(pts.reshape(-1, 3))
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


def load_vector(mesh, basis, scale=1.0):
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
    # 420: its weight splits into a part square to the cradle and a part down the slope held by the antlers
    w420 = KG["rad420"] * g
    u_face = hw.RAD420_BS[3]
    used = [(hw.RAD420_HOLES_X[4], hw.RAD420_HOLES_N[0]), (hw.RAD420_HOLES_X[5], hw.RAD420_HOLES_N[0]),
            (hw.RAD420_HOLES_X[5], hw.RAD420_HOLES_N[1]), (hw.RAD420_HOLES_X[1], hw.RAD420_HOLES_N[0]),
            (hw.RAD420_HOLES_X[0], hw.RAD420_HOLES_N[0]), (hw.RAD420_HOLES_X[0], hw.RAD420_HOLES_N[1])]
    for x, n in used:
        push("винт радиатора 420", near(mesh, hw.bp(hw.x_to_v(x), u_face + 5.0, n), 9.0), -U_DIR * math.sqrt(0.5) * w420 / 6)
    for s in (1, -1):
        cradle = np.array([hw.bp(hw.x_to_v(150.0 * s), u, hw.RAD420_BS[4] - 3.0) for u in np.linspace(316, 360, 6)])
        nodes = np.unique(np.concatenate([near(mesh, c, 9.0) for c in cradle]))
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


@BilinearForm
def stiffness(u, v, w):
    return 2.0 * w["mu"] * ddot(sym_grad(u), sym_grad(v)) + w["lam"] * trace(sym_grad(u)) * trace(sym_grad(v))


@LinearForm
def self_weight(v, w):
    return -w["rho"] * G * v.value[2]


def pick_solver():
    """MKL Pardiso on all cores where pypardiso is installed (x86), else scikit-fem's default (SuperLU, one core).
    STRENGTH_SOLVER=scipy forces the default, to compare the two."""
    if os.environ.get("STRENGTH_SOLVER") != "scipy":
        try:
            import pypardiso
            return (lambda A, b, **kw: pypardiso.spsolve(A.tocsr(), b)), "MKL Pardiso, все ядра"
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


def solve_case(mesh, basis, basis0, frac, infill, f_ext, unit, gscale=1.0):
    k = infill ** 2
    E = E0 * (frac + (1 - frac) * k)
    rho = RHO * (frac + (1 - frac) * infill)
    K = scaled_stiffness(unit, E)
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


def main():
    global WALL
    focus = FOCUS if "--focus" in sys.argv else ()
    argv = [a for a in sys.argv if a != "--focus"]
    h_max = float(argv[1]) if len(argv) > 1 else 7.0
    if len(argv) > 3:
        WALL = float(argv[3])                               # wall thickness, to compare perimeter counts
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

    mesh = build_mesh(parts, h_max, 2.5, focus)
    frac, area = wall_fraction(mesh)
    vol = mesh_volumes(mesh)
    order = int(argv[2]) if len(argv) > 2 else 2
    basis = Basis(mesh, ElementVector(ElementTetP2() if order == 2 else ElementTetP1()))
    basis0 = basis.with_element(ElementTetP0())
    out.append(f"СЕТКА: {mesh.t.shape[1]} тетраэдров, {basis.N // 3} узлов расчёта, элементы порядка {order}, шаг до {h_max:g} мм; "
               f"объём {vol.sum() / 1000:.0f} см³; доля стенки по объёму {float((frac * vol).sum() / vol.sum()) * 100:.0f} %; решатель: {SOLVER_NAME}")
    f1, log = load_vector(mesh, basis)
    out.append("НАГРУЗКИ (1 g): " + "; ".join(log))
    out.append(f"Допустимое напряжение в стенке: {ALLOW:.1f} МПа (прочность поперёк слоёв {STRENGTH_LAYER:.0f} МПа, запас {SAFETY:.0f})")
    out.append("")
    out.append(f"{'заполнение':>10} {'макс. прогиб':>13} {'у 420':>7} {'у 360':>7} {'стенка 99,9%':>13} {'стенка макс':>12} "
               f"{'запас':>6} {'заполн. 99,9%':>14} {'его прочн.':>10}")
    p420 = near(mesh, hw.bp(hw.x_to_v(hw.RAD420_HOLES_X[5]), hw.RAD420_BS[3] + 5.0, hw.RAD420_HOLES_N[1]), 10.0)
    p360 = near(mesh, hw.bp(hw.x_to_v(hw.RAD360_HOLES_X[-1]), hw.RAD360_HOLES_U[0], hw.RAD360_INNER_N - 6.0), 10.0)
    worst, peaks, spots = None, [], []
    unit = unit_stiffness(mesh, basis, basis0)
    cent = mesh.p.T[mesh.t.T].mean(axis=1)
    for infill in INFILLS:
        disp, vm_wall, vm_core, _ = solve_case(mesh, basis, basis0, frac, infill, f1, unit)
        mag = np.linalg.norm(disp, axis=1)
        wall = vm_wall[frac > 0.3]
        core = vm_core[frac < 0.7] if infill < 1 else np.array([0.0])
        core_strength = 0.3 * infill ** 1.5 * STRENGTH_IN_PLANE
        p999 = float(np.percentile(wall, 99.9))
        out.append(f"{int(infill * 100):>9}% {mag.max():>10.3f} мм {mag[p420].mean():>7.3f} {mag[p360].mean():>7.3f} "
                   f"{p999:>10.2f} МПа {wall.max():>9.2f} МПа {ALLOW / p999:>6.1f} "
                   f"{float(np.percentile(core, 99.9)):>11.3f} МПа {core_strength:>7.2f} МПа")
        if infill == INFILLS[0]:
            i = int(np.argmax(np.where(frac > 0.3, vm_wall, 0)))
            c = mesh.p.T[mesh.t.T[i]].mean(axis=0)
            j = int(np.argmax(mag))
            worst = (c, float(vm_wall[i]), mesh.p.T[j], float(mag[j]))
            vm = np.where(frac > 0.3, vm_wall, 0.0)
            for i in np.argsort(vm)[::-1]:                  # the five most loaded places, at least 30 mm apart
                if all(np.linalg.norm(cent[i] - q) > 30.0 for q, _ in peaks):
                    peaks.append((cent[i], float(vm[i])))
                    if len(peaks) == 5:
                        break
            for point, radius, h in focus:
                inside = np.linalg.norm(cent - np.array(point), axis=1) < radius
                spots.append((point, radius, h, int(inside.sum()), float(vm[inside].max())))
    out.append("")
    out.append("Перенос в руках: расчёт линейный, при 2 g все прогибы и напряжения удваиваются, запас делится на 2.")
    if worst:
        c, s, pj, m = worst
        out.append(f"Самое нагруженное место при 20 %: {s:.2f} МПа в точке X {c[0]:.0f}, Y {c[1]:.0f}, Z {c[2]:.0f}; "
                   f"наибольший прогиб {m:.3f} мм в точке X {pj[0]:.0f}, Y {pj[1]:.0f}, Z {pj[2]:.0f}.")
    if peaks:
        out.append("Пять самых нагруженных мест при 20 % (не ближе 30 мм друг к другу): "
                   + "; ".join(f"{s:.2f} МПа в X {c[0]:.0f}, Y {c[1]:.0f}, Z {c[2]:.0f}" for c, s in peaks) + ".")
    for point, radius, h, count, s in spots:
        out.append(f"Мелкая сетка {h:g} мм в радиусе {radius:g} мм от X {point[0]:.0f}, Y {point[1]:.0f}, Z {point[2]:.0f}: "
                   f"{count} тетраэдров, наибольшее напряжение стенки при 20 % {s:.2f} МПа (запас {ALLOW / s:.1f}).")
    out.append(f"Время расчёта {time.time() - t0:.0f} с.")
    text = "\n".join(out)
    with open(os.path.join(HERE, "report_strength_focus.txt" if focus else "report_strength.txt"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
