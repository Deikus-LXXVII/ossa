#!/usr/bin/env python3
"""Feasibility study (no revision): both side fans raised and mirrored, so that the board's rear connectors are open towards -X.

docs/plans/external-cables.md has the problem; cad_b6/report_study_side_fans.txt has the findings. This script changes no committed file: the fans' places and the hose
routes it tries live here and in memory. Hardware dimensions come from hardware.py and hoses.py, never retyped.

Method. The hoses are drawn as rods of 3 mm segments, so their length is exact; a first guess is the shortest path through the free space (a 3 mm lattice in board space),
lengthened step by step to the true length so that it buckles into whatever room there is, with the rules as penalties (bend radius, 5 mm clearances, hose gap, corridor,
envelope). Random via points make several starts. A rod that meets the rules is then fitted by waypoints joined with hoses.fillet_path (the project's helper, arcs of one
radius), against 0.6 mm surface samples, and the result is measured on the solids with the project's hose chains and solid_distance. Only that measurement counts.

Stages (each can be run alone):
  fields   voxelise the fixed obstacles on a 1.5 mm grid, distance fields to out/study_side_fans/fields.npz (about 1 minute)
  scan     table of fan places (D, u0, n0) and straights s: does the CPU pair have a route (about 20 minutes)
  case K   K = f140 or f120: rods, fit, exact measurement and pictures for the CPU pair, and the card's pair where it has to move (about 30 minutes each)
  polish K re-fit a case's routes that are short of a rule on the solids
  report   write cad_b6/report_study_side_fans.txt from the above

Run:  .venv/bin/python cad_b6/study_side_fans.py <stage> [K]
Out:  previews/b6_study_fans_<view>_<K>.png, cad_b6/report_study_side_fans.txt
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cadquery as cq  # noqa: E402,F401  (before vtk, see render_vtk.py)
from scipy import ndimage  # noqa: E402

import drive_access as da  # noqa: E402
import frame_v0  # noqa: E402
import hardware as hw  # noqa: E402
import hoses  # noqa: E402

OUT = os.path.join(ROOT, "out", "study_side_fans")
VOX = 1.5
# grid box, world mm: wide enough for |X| 229 + clearance, the front plane and the antlers' rear
GRID_X = (-246.0, 246.0)
GRID_Y = (-14.0, 400.0)
GRID_Z = (-20.0, 400.0)

# What the study redraws, so it is not an obstacle: the two fans and their brackets, the two hose guides, both hose keep-outs (the study's own routes
# replace them).
REDRAWN_PARTS = ("fan_bracket_left", "fan_bracket_right", "hose_guide_cpu", "hose_guide_gpu")
REDRAWN_HW = ("fan_side_left", "fan_side_right", "cpu_hoses", "gpu_hoses")
# The hose's own ends are not obstacles to it: the CPU block it leaves (checked separately, from 12 mm along the route) and the 420's port.
OWN_ENDS_HW = ("rad420_ports", "cpu_block")


def grid_axes():
    xs = np.arange(GRID_X[0], GRID_X[1] + 1e-6, VOX)
    ys = np.arange(GRID_Y[0], GRID_Y[1] + 1e-6, VOX)
    zs = np.arange(GRID_Z[0], GRID_Z[1] + 1e-6, VOX)
    return xs, ys, zs


def voxelise_local(solid, xs, ys, zs):
    """Occupancy of one solid on the grid; only the part of the grid round its bounding box is stencilled."""
    b = frame_v0.bbox_of(solid)           # (x0, x1, y0, y1, z0, z1)
    lo = [max(int(np.floor((b[2 * k] - a[0]) / VOX)) - 1, 0) for k, a in enumerate((xs, ys, zs))]
    hi = [min(int(np.ceil((b[2 * k + 1] - a[0]) / VOX)) + 2, len(a)) for k, a in enumerate((xs, ys, zs))]
    shape = tuple(h - l for l, h in zip(lo, hi))
    origin = (xs[lo[0]], ys[lo[1]], zs[lo[2]])
    occ = da.voxelise(solid, origin, shape, VOX)
    return occ, lo, hi


def occupancy(solids, xs, ys, zs):
    full = np.zeros((len(xs), len(ys), len(zs)), dtype=bool)
    for s in solids:
        for one in s.Solids():
            occ, lo, hi = voxelise_local(one, xs, ys, zs)
            full[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]] |= occ
    return full


def edt(occ):
    """Distance in mm from each voxel centre to the nearest occupied voxel centre (0 inside), float32."""
    return ndimage.distance_transform_edt(~occ, sampling=VOX).astype(np.float32)


def build_fields(path=os.path.join(OUT, "fields.npz")):
    t0 = time.time()
    parts, _ = frame_v0.build_frame()
    hardware = hw.build_hardware()
    xs, ys, zs = grid_axes()
    frame = [p.solid for p in parts if p.name not in REDRAWN_PARTS]
    fixed = [s for k, s in hardware.items() if k not in REDRAWN_HW + OWN_ENDS_HW and k != "io_zone"]
    print(f"built the model {time.time() - t0:.0f} s")
    f_frame = edt(occupancy(frame, xs, ys, zs))
    print(f"frame field {time.time() - t0:.0f} s")
    f_hw = edt(occupancy(fixed, xs, ys, zs))
    print(f"hardware field {time.time() - t0:.0f} s")
    f_block = edt(occupancy([hardware["cpu_block"]], xs, ys, zs))
    # for the card's hoses: the card they leave and the 360's port box they enter are their own ends, not obstacles
    fixed_g = [s for k, s in hardware.items() if k not in REDRAWN_HW + OWN_ENDS_HW + ("gpu", "rad360_ports", "io_zone")]
    f_hwg = edt(occupancy(fixed_g, xs, ys, zs))
    f_gpu = edt(occupancy([hardware["gpu"]], xs, ys, zs))
    os.makedirs(OUT, exist_ok=True)
    np.savez_compressed(path, frame=f_frame, hw=f_hw, block=f_block, hwg=f_hwg, gpu=f_gpu, xs=xs, ys=ys, zs=zs)
    print(f"saved {path} {time.time() - t0:.0f} s")


# ---------------------------------------------------------------------------
# Fields in use
# ---------------------------------------------------------------------------
class Fields:
    """The distance fields of build_fields(), sampled by trilinear interpolation at points in board space (v, u, n)."""

    def __init__(self, path=os.path.join(OUT, "fields.npz")):
        f = np.load(path)
        self.xs, self.ys, self.zs = f["xs"], f["ys"], f["zs"]
        self.f = {k: f[k] for k in ("frame", "hw", "block", "hwg", "gpu") if k in f}
        self.g = {k: np.stack(np.gradient(v, VOX), axis=0) for k, v in self.f.items()}      # (3, nx, ny, nz): d/dX, d/dY, d/dZ

    def _idx(self, p):
        w = world_of(p)
        return np.stack([(w[:, 0] - self.xs[0]) / VOX, (w[:, 1] - self.ys[0]) / VOX, (w[:, 2] - self.zs[0]) / VOX])

    def dist(self, name, p):
        return ndimage.map_coordinates(self.f[name], self._idx(p), order=1, mode="nearest")

    def dist_grad(self, name, p):
        """(d, grad d) at points p (N x 3, board space); the gradient is in board space."""
        i = self._idx(p)
        d = ndimage.map_coordinates(self.f[name], i, order=1, mode="nearest")
        gw = np.stack([ndimage.map_coordinates(self.g[name][k], i, order=1, mode="nearest") for k in range(3)], axis=1)
        return d, gw @ ROT           # world gradient -> board space: g_b = R^T g_w, rows of gw are g_w, so gw @ R


C = hw.C
ROT = np.array([[1.0, 0.0, 0.0], [0.0, C, -C], [0.0, C, C]])         # columns: world directions of v, u, n


def world_of(p):
    """World points of board-space points p (N x 3): the same as hw.bp, vectorised."""
    p = np.asarray(p, float)
    return np.stack([hw.ORIGIN[0] + p[:, 0], hw.ORIGIN[1] + (p[:, 1] - p[:, 2]) * C, hw.ORIGIN[2] + (p[:, 1] + p[:, 2]) * C], axis=1)


def box_sdf(p, b):
    """Signed distance (positive outside) and its gradient from points p (N x 3) to the box b = (v0, v1, u0, u1, n0, n1)."""
    lo, hi = np.array(b[0::2], float), np.array(b[1::2], float)
    q = np.maximum(lo - p, 0) + np.maximum(p - hi, 0)
    d_out = np.linalg.norm(q, axis=1)
    sgn = np.where(p < lo, -1.0, np.where(p > hi, 1.0, 0.0))
    g = np.where(d_out[:, None] > 1e-9, sgn * q / np.maximum(d_out[:, None], 1e-9), 0.0)
    inside = d_out <= 1e-9
    if inside.any():
        pen = np.concatenate([p - lo, hi - p], axis=1)           # penetration depth from each of the six faces
        k = pen[inside].argmin(axis=1)
        d_out = d_out.copy()
        d_out[inside] = -pen[inside].min(axis=1)
        gi = np.zeros((int(inside.sum()), 3))
        for row, kk in enumerate(k):
            gi[row, kk % 3] = -1.0 if kk < 3 else 1.0
        g[inside] = gi
    return d_out, g


# ---------------------------------------------------------------------------
# The rod: a hose as N segments of equal length, so its length is exact by construction
# ---------------------------------------------------------------------------
from scipy.optimize import minimize  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402

CLEAR_PART = 5.0        # check 9: a frame part is 5 mm from the hose's keep-out (true radius + HOSE_ALLOW)
CLEAR_HW = 5.0          # the brief: 5 mm from the hose's own surface to hardware, a fan included
HOSE_GAP = 2.7          # surface to surface of the two hoses of a pair: what the model has today (hose_routes.py: 2.7 mm CPU, 3.6 GPU)
VOXEL_SAFETY = 0.5      # the search keeps this much more than the rule, the 1.5 mm grid is good to about 0.75 mm; every result is re-measured on the solids
# the connector aperture's open zone: the io_zone's footprint (board edge to 50 mm out) carried on to the fans' inner face, X -204 .. -122. A hose is 5 mm
# from it. It is the volume the owner wants free so that cables can leave towards -X.
CORRIDOR_BS = (hw.x_to_v(-204.0), 0.0, hw.IO_ZONE_BS[2], hw.IO_ZONE_BS[3], hw.IO_ZONE_BS[4], hw.IO_ZONE_BS[5])
STAGES = ((1e2, 1e2, 1.0), (1e3, 1e3, 10.0), (1e4, 1e4, 100.0), (1e5, 1e5, 1e3), (1e6, 1e6, 1e4))


class Spec:
    """One pair of hoses as the rod needs it. Hose h starts at starts[h] going along t_start and ends at ends[h] arriving along t_end, the last `straight` mm
    of it straight. Every distance is from the hose's centre line."""

    def __init__(self, kind, fans, extra_boxes=()):
        self.kind = kind
        cpu = kind == "cpu"
        spec = hoses.CPU_HOSE if cpu else hoses.GPU_HOSE
        spare = hoses.CPU_SPARE if cpu else hoses.GPU_SPARE
        self.r = hw.CPU_HOSE_R if cpu else hw.GPU_HOSE_R
        self.r_keep = self.r + hw.HOSE_ALLOW
        self.length = spec["length"] - spare
        self.n = int(round(self.length / 3.0))                       # 144 for the CPU pair (432 mm), 145 for the card's (435 mm): 3 mm segments
        self.bend = spec["min_bend"]
        self.c_part = self.r_keep + CLEAR_PART
        self.c_hw = self.r + CLEAR_HW
        self.c_hh = 2 * self.r + HOSE_GAP
        self.field_hw = "hw" if cpu else "hwg"
        self.field_own = "block" if cpu else "gpu"                   # the component the hose leaves: ignored for the first few mm
        self.fans = list(fans)
        self.boxes = ([CORRIDOR_BS] if cpu else []) + list(extra_boxes)
        pair = hoses.routes()[kind][0]
        self.starts = [np.array(hoses.world_to_bs(h["pts"][0])) for h in pair]
        self.ends = [np.array(hoses.world_to_bs(h["pts"][-1])) for h in pair]
        self.t_start = np.array([0.0, 0.0, 1.0]) if cpu else np.array([1.0, 0.0, 0.0])
        self.t_end = np.array([0.0, 1.0, 0.0]) if cpu else np.array([0.0, 0.0, 1.0])
        # the planes: (normal, offset): normal . p >= offset. |X| <= ENVELOPE_X for the keep-out, Y >= ENVELOPE_Y0 for the keep-out
        self.planes = []
        if cpu:
            self.planes.append((np.array([1.0, 0, 0]), hw.x_to_v(-hw.ENVELOPE_X + self.r_keep) + 0.3))
        else:
            self.planes.append((np.array([-1.0, 0, 0]), -hw.x_to_v(hw.ENVELOPE_X - self.r_keep) + 0.3))
        self.planes.append((np.array([0.0, C, -C]), hw.ENVELOPE_Y0 + self.r_keep + 0.5 - hw.ORIGIN[1]))

    def fixed(self, h, ds, straight):
        s, e = self.starts[h], self.ends[h]
        nfe = int(round(straight / ds))
        vals = {0: s, 1: s + ds * self.t_start}
        for k in range(nfe + 1):
            vals[self.n - k] = e - k * ds * self.t_end
        return vals


def rod_cost(spec, ps, w, ds, own_from=8):
    tot = 0.0
    grads = [np.zeros_like(p) for p in ps]
    for h, p in enumerate(ps):
        g = grads[h]
        d = p[1:] - p[:-1]
        l = np.linalg.norm(d, axis=1)
        e = l - ds
        tot += w["len"] * np.sum(e ** 2)
        gd = (2 * w["len"] * e / l)[:, None] * d
        g[1:] += gd
        g[:-1] -= gd
        q = p[:-2] - 2 * p[1:-1] + p[2:]
        m = np.linalg.norm(q, axis=1)
        ex = np.maximum(0, m - ds * ds / w["R"])
        tot += w["curv"] * np.sum(ex ** 2)
        gq = (2 * w["curv"] * ex / np.maximum(m, 1e-9))[:, None] * q
        g[:-2] += gq
        g[1:-1] -= 2 * gq
        g[2:] += gq
        for name, c in (("frame", spec.c_part + VOXEL_SAFETY), (spec.field_hw, spec.c_hw + VOXEL_SAFETY)):
            dd, gg = FIELDS.dist_grad(name, p)
            ex = np.maximum(0, c - dd)
            tot += w["clr"] * np.sum(ex ** 2)
            g += (-2 * w["clr"] * ex)[:, None] * gg
        dd, gg = FIELDS.dist_grad(spec.field_own, p[own_from:])
        ex = np.maximum(0, spec.c_hw + VOXEL_SAFETY - dd)
        tot += w["clr"] * np.sum(ex ** 2)
        g[own_from:] += (-2 * w["clr"] * ex)[:, None] * gg
        for b in spec.fans + spec.boxes:
            dd, gg = box_sdf(p, b)
            ex = np.maximum(0, spec.c_hw + 0.3 - dd)
            tot += w["clr"] * np.sum(ex ** 2)
            g += (-2 * w["clr"] * ex)[:, None] * gg
        for nrm, off in spec.planes:
            ex = np.maximum(0, off - p @ nrm)
            tot += w["clr"] * np.sum(ex ** 2)
            g += (-2 * w["clr"] * ex)[:, None] * nrm[None, :]
    if len(ps) == 2:
        a, b = ps
        for i, js in enumerate(cKDTree(b).query_ball_point(a, spec.c_hh + 1)):
            for j in js:
                dv = a[i] - b[j]
                dist = np.linalg.norm(dv)
                if dist < spec.c_hh + 0.3:
                    ex = spec.c_hh + 0.3 - dist
                    tot += w["hh"] * ex ** 2
                    gg = (-2 * w["hh"] * ex / max(dist, 1e-9)) * dv
                    grads[0][i] += gg
                    grads[1][j] -= gg
    return tot, grads


def rod_optimise(spec, ps0, which, ds, straight, stages=STAGES, maxiter=400, bend=None):
    """Move the rods ps0 (hose indices `which`) to the least violation of the rules at segment length ds."""
    ps = [p.copy() for p in ps0]
    fx = [spec.fixed(h, ds, straight) for h in which]
    for h in range(len(ps)):
        for i, v in fx[h].items():
            ps[h][i] = v
    free = [np.array([i for i in range(spec.n + 1) if i not in fx[h]]) for h in range(len(ps))]

    def unpack(x):
        o = 0
        for h in range(len(ps)):
            k = len(free[h]) * 3
            ps[h][free[h]] = x[o:o + k].reshape(-1, 3)
            o += k
    x = np.concatenate([ps[h][free[h]].ravel() for h in range(len(ps))])
    last = None
    for (wl, wc, wcl) in stages:
        w = dict(len=wl, curv=wc, clr=wcl, hh=wcl, R=bend or spec.bend + 1.5)

        def f(x):
            unpack(x)
            t, g = rod_cost(spec, ps, w, ds)
            return t, np.concatenate([g[h][free[h]].ravel() for h in range(len(ps))])
        res = minimize(f, x, jac=True, method="L-BFGS-B", options=dict(maxiter=maxiter, maxfun=maxiter * 2, ftol=1e-13, gtol=1e-9))
        x, last = res.x, res.fun
        unpack(x)
    return ps, last


def rod_report(spec, ps, ds):
    """Per hose: length, worst length error, smallest bend radius, and the smallest clearance as 'surface to the thing' for each kind of thing."""
    rows = []
    for p in ps:
        d = np.linalg.norm(np.diff(p, axis=0), axis=1)
        q = np.linalg.norm(p[:-2] - 2 * p[1:-1] + p[2:], axis=1)
        rows.append(dict(len=d.sum(), lenerr=abs(d - ds).max(), Rmin=ds * ds / q.max(),
                         frame=FIELDS.dist("frame", p).min() - spec.r_keep, hw=FIELDS.dist(spec.field_hw, p).min() - spec.r,
                         own=FIELDS.dist(spec.field_own, p[8:]).min() - spec.r,
                         fan=min(box_sdf(p, b)[0].min() for b in spec.fans) - spec.r,
                         box=min([box_sdf(p, b)[0].min() for b in spec.boxes] or [99.0]) - spec.r,
                         plane=min(float((p @ n).min() - o) for n, o in spec.planes)))
    if len(ps) == 2:
        dd, _ = cKDTree(ps[1]).query(ps[0])
        rows.append(dict(hh=dd.min() - 2 * spec.r))
    return rows


# ---------------------------------------------------------------------------
# A first guess: the shortest path through the free space on a 3 mm lattice in board space (no bend radius, no exact length), through an optional via point
# ---------------------------------------------------------------------------
from scipy.sparse import coo_matrix  # noqa: E402
from scipy.sparse.csgraph import dijkstra  # noqa: E402

LAT = 3.0
LAT_V, LAT_U, LAT_N = (-125.0, 347.0), (40.0, 322.0), (-100.0, 217.0)


class Lattice:
    def __init__(self):
        self.vg = np.arange(LAT_V[0], LAT_V[1], LAT)
        self.ug = np.arange(LAT_U[0], LAT_U[1], LAT)
        self.ng = np.arange(LAT_N[0], LAT_N[1], LAT)
        V, U, N = np.meshgrid(self.vg, self.ug, self.ng, indexing="ij")
        self.P = np.stack([V, U, N], axis=-1).reshape(-1, 3)
        self.shape = V.shape
        self.d = {k: FIELDS.dist(k, self.P).reshape(self.shape) for k in FIELDS.f}

    def node(self, p):
        return tuple(int(round((p[k] - a[0]) / LAT)) for k, a in enumerate((self.vg, self.ug, self.ng)))

    def free(self, spec, tol=0.75):
        m = (self.d["frame"] >= spec.c_part + tol) & (self.d[spec.field_hw] >= spec.c_hw + tol)
        for b in spec.fans + spec.boxes:
            m &= box_sdf(self.P, b)[0].reshape(self.shape) >= spec.c_hw
        for nrm, off in spec.planes:
            m &= (self.P @ nrm).reshape(self.shape) >= off
        return m

    def shortest(self, mask, a, b):
        idx = -np.ones(mask.shape, int)
        idx[mask] = np.arange(mask.sum())
        rows, cols, w = [], [], []
        for (i, j, k) in [(i, j, k) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1) if (i, j, k) > (0, 0, 0)]:
            sa = tuple(slice(max(0, -d), mask.shape[t] - max(0, d)) for t, d in enumerate((i, j, k)))
            sb = tuple(slice(max(0, d), mask.shape[t] - max(0, -d)) for t, d in enumerate((i, j, k)))
            ia, ib = idx[sa], idx[sb]
            ok = (ia >= 0) & (ib >= 0)
            rows.append(ia[ok])
            cols.append(ib[ok])
            w.append(np.full(int(ok.sum()), LAT * np.sqrt(i * i + j * j + k * k)))
        g = coo_matrix((np.concatenate(w), (np.concatenate(rows), np.concatenate(cols))), shape=(int(mask.sum()),) * 2)
        ia, ib = idx[a], idx[b]
        if ia < 0 or ib < 0:
            return None
        d, pred = dijkstra(g, directed=False, indices=ia, return_predecessors=True)
        if not np.isfinite(d[ib]):
            return None
        path = [ib]
        while path[-1] != ia:
            path.append(pred[path[-1]])
        inv = np.argwhere(mask)
        return np.array([[self.vg[i], self.ug[j], self.ng[k]] for i, j, k in (inv[q] for q in path[::-1])])


def first_guess(lat, spec, h, straight, via=None, mask=None):
    """Rod points (n + 1 of them) along the shortest free path of hose h, through `via` if given; None when there is none."""
    m = lat.free(spec).copy() if mask is None else mask.copy()
    s, e = spec.starts[h], spec.ends[h]
    a = lat.node(s + 14.0 * spec.t_start)
    b = lat.node(e - straight * spec.t_end)
    m[a] = m[b] = True
    if via is None:
        pts = lat.shortest(m, a, b)
    else:
        c = lat.node(via)
        if not m[c]:
            return None
        p1, p2 = lat.shortest(m, a, c), lat.shortest(m, c, b)
        pts = None if p1 is None or p2 is None else np.vstack([p1, p2[1:]])
    if pts is None:
        return None
    full = np.vstack([s, s + 7.0 * spec.t_start, pts, e - 0.5 * straight * spec.t_end, e])
    cum = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(full, axis=0), axis=1))])
    t = np.linspace(0, cum[-1], spec.n + 1)
    return np.stack([np.interp(t, cum, full[:, k]) for k in range(3)], axis=1)


def violation(spec, rows):
    """Worst shortfall in mm against the rules (0 or less: every rule met) over a rod report."""
    v = []
    for x in rows[:len(spec.starts)]:
        v += [spec.bend - x["Rmin"], CLEAR_PART - x["frame"], CLEAR_HW - x["hw"], CLEAR_HW - x["own"], CLEAR_HW - x["fan"], CLEAR_HW - x["box"], -x["plane"], 10 * x["lenerr"]]
    if len(rows) > len(spec.starts):
        v.append(HOSE_GAP - rows[-1]["hh"])
    return max(v)


def rod_solve(spec, straight, vias=None, step=0.1, maxiter=400, bend=None, lat=None):
    """Both hoses of the pair from a first guess, lengthened step by step from the shortest path to the true length (the rod buckles into the free space), with the
    rules enforced as penalties at every step. Returns (rods, report, violation) or None."""
    lat = lat or Lattice()
    vias = vias or (None, None)
    ps = [first_guess(lat, spec, h, straight, vias[h]) for h in (0, 1)]
    if any(p is None for p in ps):
        return None
    target = spec.length / spec.n
    ds = min(float(np.linalg.norm(np.diff(p, axis=0), axis=1).mean()) for p in ps)
    while True:
        ps, _ = rod_optimise(spec, ps, [0, 1], ds, straight, maxiter=maxiter, bend=bend)
        if ds >= target - 1e-9:
            break
        ds = min(ds + step, target)
    rows = rod_report(spec, ps, ds)
    return ps, rows, violation(spec, rows)


VIA_BOX = {"cpu": ((-70, 90), (130, 290), (50, 115)), "gpu": ((150, 340), (60, 290), (-90, 110))}
_LAT = None


def _init_worker():
    global _LAT
    load_fields()
    _LAT = Lattice()


def _job(args):
    kind, fans, straight, vias, bend = args
    spec = Spec(kind, fans)
    r = rod_solve(spec, straight, vias, bend=bend, lat=_LAT)
    return None if r is None else (r[2], r[0], r[1], args)


def multistart(pool, kind, fans, straight, restarts=9, seed=1, bend=None):
    """Random via points make the first guess go different ways round the obstacles; each start is solved on its own. Returns the results, best first
    (violation, rods, report, job)."""
    rng = np.random.default_rng(seed)
    box = VIA_BOX[kind]
    jobs = [(kind, fans, straight, (None, None), bend)]
    for _ in range(restarts):
        v = np.array([rng.uniform(*b) for b in box])
        off = np.array([rng.uniform(0, 25), rng.uniform(-10, 10), rng.uniform(0, 25)])
        jobs.append((kind, fans, straight, (tuple(v), tuple(v + off)), bend))
    res = [r for r in pool.map(_job, jobs) if r is not None]
    return sorted(res, key=lambda r: r[0])


# ---------------------------------------------------------------------------
# From the rod to a route the project can draw: waypoints joined by hoses.fillet_path (arcs of one radius), solved to the exact length
# ---------------------------------------------------------------------------
from scipy.optimize import least_squares  # noqa: E402


def simplify(p, tol):
    """Douglas-Peucker: indices of the vertices of a polyline within tol of the points p."""
    keep = [0, len(p) - 1]
    stack = [(0, len(p) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        d = p[b] - p[a]
        L = np.linalg.norm(d)
        seg = p[a + 1:b] - p[a]
        dist = np.linalg.norm(seg - np.outer(seg @ d / L ** 2, d), axis=1) if L > 1e-9 else np.linalg.norm(seg, axis=1)
        k = int(dist.argmax())
        if dist[k] > tol:
            keep.append(a + 1 + k)
            stack += [(a, a + 1 + k), (a + 1 + k, b)]
    return sorted(keep)


BEND_MARGIN = 0.05      # the fit asks for this much over the bend radius; refine() raises it when the measured route is under
FILLET_EXTRA = 1.0      # the fillets are drawn at bend + this, so that where two arcs share a short run and are cut back, the smallest radius used stays at or over the bend


def route_of(wps, bend):
    pts, length, rmin, tang = hoses.fillet_path(wps, [bend] * (len(wps) - 2))
    return pts, length, rmin, tang


# ---------------------------------------------------------------------------
# Exact measurement of a pair of routes on the solids, with the project's own chains and keep-outs
# ---------------------------------------------------------------------------
def world_route(wps, bend):
    """The fillet path of board-space waypoints, as world points (what hoses.py works in) and the world tangents of its first and last run."""
    pts, length, rmin, (t0, t1) = route_of(wps, bend + FILLET_EXTRA)
    return world_of(np.asarray(pts)), length, rmin, (ROT @ t0, ROT @ t1)


def _tube(chain, r):
    """The sweep with round joints; where OCC makes an invalid solid of it (frame_v0.hose_tube meets this on the CPU hose B) the mitred sweep, and last the
    cylinders and spheres of cables.chain_solid, which a distance query takes as it is."""
    for transition in ("round", "right"):
        try:
            return hw.hose_chain(chain, r, transition=transition)
        except Exception:      # noqa: BLE001 - AssertionError of hose_chain or OCC's Standard_Failure: try the next way
            continue
    import cables
    return cables.chain_solid(chain, r)


def hose_solids(kind, wps_pair):
    """Per hose: (true tube, keep-out tube, world sample points), built the way hardware.hose_solid builds a keep-out: the chain of every third sample, ending at
    the port box's face (the 420's for the CPU hoses, the 360's for the card's)."""
    cpu = kind == "cpu"
    box = hw.RAD420_PORTS_BS if cpu else hw.RAD360_PORTS_BS
    r = hw.CPU_HOSE_R if cpu else hw.GPU_HOSE_R
    out = []
    for w in wps_pair:
        pts, _length, _rmin, (t0, _t1) = world_route(w, hoses.BEND_R)
        chain = hoses.chain_points(hoses.trim_to_box(pts, box), t0)
        out.append((_tube(chain, r), _tube(chain, r + hw.HOSE_ALLOW), pts))
    return out


def measure_pair(kind, wps_pair, parts, hardware, fans):
    """Exact distances, mm: hose keep-out to every frame part (check 9's rule: 5), true hose to every piece of hardware (5), the two hoses to each other, and
    to the fans and the connector corridor. Returns a list of rows (what, hose, distance, needed) and the lengths and bends."""
    cpu = kind == "cpu"
    tubes = hose_solids(kind, wps_pair)
    rows = []
    mine = ("cpu_hoses", "rad420_ports", "cpu_block", "io_zone") if cpu else ("gpu_hoses", "rad360_ports", "gpu", "io_zone")
    for h, (tube, keep, pts) in enumerate(tubes):
        bt, bk = frame_v0.bbox_of(tube), frame_v0.bbox_of(keep)
        for p in parts:
            if p.name in REDRAWN_PARTS:
                continue
            if frame_v0.bbox_gap(frame_v0.bbox_of(p.solid), bk) > 12:
                continue
            rows.append((p.name, h, frame_v0.solid_distance(keep, p.solid), CLEAR_PART))
        for k, sol in list(hardware.items()) + [(f"fan_new_{i}", f) for i, f in enumerate(fans)] + [("corridor", hw.bs_box(*CORRIDOR_BS) if cpu else None)]:
            if sol is None or k in mine or k in REDRAWN_HW:
                continue
            if frame_v0.bbox_gap(frame_v0.bbox_of(sol), bt) > 12:
                continue
            rows.append(("hw:" + k, h, frame_v0.solid_distance(tube, sol), CLEAR_HW))
        own = hardware["cpu_block"] if cpu else hardware["gpu"]
        # the component the hose leaves: only from 12 mm along (the hose stands on it at its start)
        far = [q for q in pts if np.linalg.norm(q - pts[0]) > 12.0]
        if far:
            rows.append(("own start " + ("cpu_block" if cpu else "gpu") + " (points over 12 mm from the start)", h,
                         min(float(own.distance(cq.Vertex.makeVertex(*q))) for q in far[::4]) - (hw.CPU_HOSE_R if cpu else hw.GPU_HOSE_R), CLEAR_HW))
    rows.append(("hose x hose", 0, frame_v0.solid_distance(tubes[0][0], tubes[1][0]), HOSE_GAP))
    for h, w in enumerate(wps_pair):
        rows.append(("bend radius (smallest arc of the route)", h, route_of(w, hoses.BEND_R + FILLET_EXTRA)[2], hoses.BEND_R))
    return rows, tubes


def exact_ok(rows):
    return all(d >= need - 1e-6 for (_n, _h, d, need) in rows)


# ---------------------------------------------------------------------------
# The cases
# ---------------------------------------------------------------------------
FAN_X = {"left": (-229.0, -204.0), "right": (204.0, 229.0)}        # outer face at the owner's limit |X| 229, a pure mirror of each other


def fan_boxes(D, u0, n0, right_x=None):
    """(left box, right box) of two D x D x 25 fans, mirrored, in board space."""
    rx = right_x or FAN_X["right"]
    return ((hw.x_to_v(FAN_X["left"][0]), hw.x_to_v(FAN_X["left"][1]), u0, u0 + D, n0, n0 + D),
            (hw.x_to_v(rx[0]), hw.x_to_v(rx[1]), u0, u0 + D, n0, n0 + D))


SURF_SPACING = 0.6       # mm between the sample points on the solids' surfaces, for the fit's distance queries (the voxel field is good to about 1 mm, this to about 0.35)


def board_of(w):
    """Board-space (v, u, n) of world points, vectorised: the inverse of world_of."""
    a, b = (w[..., 1] - hw.ORIGIN[1]) / C, (w[..., 2] - hw.ORIGIN[2]) / C
    return np.stack([w[..., 0] - hw.ORIGIN[0], (a + b) / 2, (b - a) / 2], axis=-1)


def surface_points(solid, spacing=SURF_SPACING, region=None):
    """Points on the surface of a solid, at most `spacing` apart (the tessellation's triangles, each cut into a grid of that pitch); region = ((v0, v1), (u0, u1),
    (n0, n1)) in board space keeps the triangles that touch that box."""
    out = []
    for one in solid.Solids():
        verts, tris = one.tessellate(0.25, 0.5)
        V = np.array([(v.x, v.y, v.z) for v in verts])
        T = np.array(tris)
        if region is not None:
            Bd = board_of(V)[T]                                   # (triangles, 3, 3)
            keep = np.ones(len(T), bool)
            for k in range(3):
                keep &= (Bd[:, :, k].max(axis=1) >= region[k][0]) & (Bd[:, :, k].min(axis=1) <= region[k][1])
            T = T[keep]
        if not len(T):
            continue
        A, B, Cc = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
        edge = np.maximum.reduce([np.linalg.norm(B - A, axis=1), np.linalg.norm(Cc - B, axis=1), np.linalg.norm(A - Cc, axis=1)])
        m = np.clip(np.ceil(edge / spacing).astype(int), 1, 400)
        for mm in np.unique(m):
            sel = m == mm
            ij = np.array([(i, j) for i in range(mm + 1) for j in range(mm + 1 - i)], float) / mm
            a, b = A[sel][:, None, :], (B - A)[sel][:, None, :]
            c = (Cc - A)[sel][:, None, :]
            out.append((a + ij[None, :, 0:1] * b + ij[None, :, 1:2] * c).reshape(-1, 3))
    return np.vstack(out) if out else np.zeros((0, 3))


class Surfaces:
    """Nearest-surface-point distance in place of the voxel field, for the exact fit. Only outside points are measured (a hose centre is never inside)."""

    def __init__(self, parts, hardware, region):
        t0 = time.time()
        grp = {"frame": [p.solid for p in parts if p.name not in REDRAWN_PARTS],
               "hw": [s_ for k, s_ in hardware.items() if k not in REDRAWN_HW + OWN_ENDS_HW + ("io_zone",)],
               "hwg": [s_ for k, s_ in hardware.items() if k not in REDRAWN_HW + OWN_ENDS_HW + ("gpu", "rad360_ports", "io_zone")],
               "block": [hardware["cpu_block"]], "gpu": [hardware["gpu"]]}
        self.t = {}
        for k, sols in grp.items():
            pts = np.vstack([surface_points(s_, region=region) for s_ in sols])
            self.t[k] = cKDTree(pts)
            del pts
        print(f"surface trees {time.time() - t0:.0f} s: " + ", ".join(f"{k} {t.n}" for k, t in self.t.items()), flush=True)

    def near(self, board_pts, radius):
        """A copy that keeps only the surface points within `radius` mm of the given board-space points (the rods): the fit moves a route by a few mm."""
        out = object.__new__(Surfaces)
        q = cKDTree(world_of(board_pts))
        out.t = {}
        for k, t in self.t.items():
            d, _ = q.query(t.data, distance_upper_bound=radius)
            keep = np.isfinite(d)
            out.t[k] = cKDTree(t.data[keep]) if keep.any() else cKDTree(np.array([[1e6, 1e6, 1e6]]))
        return out

    def dist(self, name, p):
        return self.t[name].query(world_of(p))[0]


DIST = None          # the distance function the fit uses: the voxel field's, or a Surfaces object's


def _dist(name, p):
    return (DIST or FIELDS).dist(name, p)


def _samples(pts, m=160):
    cum = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    t = np.linspace(0, cum[-1], m)
    return np.stack([np.interp(t, cum, pts[:, q]) for q in range(3)], axis=1)


def route_shortfalls(spec, pts, margin_frame, margin_hw):
    """Shortfalls (mm, 0 where the rule is met) of sampled route points against the grid rules; margins are extra distance asked of the grid."""
    out = [np.maximum(0, spec.c_part + margin_frame - _dist("frame", pts)), np.maximum(0, spec.c_hw + margin_hw - _dist(spec.field_hw, pts)),
           np.maximum(0, spec.c_hw + margin_hw - _dist(spec.field_own, pts[6:]))]
    for b in spec.fans + spec.boxes:
        out.append(np.maximum(0, spec.c_hw + margin_hw - box_sdf(pts, b)[0]))
    for nrm, off in spec.planes:
        out.append(np.maximum(0, off + 0.2 - pts @ nrm))
    return np.concatenate(out)


def fit_joint(spec, rods, straight, tol, margin_frame=0.45, margin_hw=0.45, nfev=150, init=None):
    """Both hoses at once: waypoints from each rod's simplified corners, then least squares on the rules, the exact length, the bend and the gap between the hoses."""
    mids = []
    for h in (0, 1):
        s, e = spec.starts[h], spec.ends[h]
        if init is not None:                       # a warm start: the waypoints of an earlier fit
            mids.append(np.array(init[h][2:-2]))
            continue
        idx = simplify(rods[h], tol)
        m = np.array([q for q in rods[h][idx][1:-1] if np.linalg.norm(q - s) > 8.0 and np.linalg.norm(q - (e - straight * spec.t_end)) > 5.0])
        mids.append(m)
    ks = [len(m) for m in mids]

    def wps_of(x):
        o, out = 0, []
        for h in (0, 1):
            s, e = spec.starts[h], spec.ends[h]
            m = x[o:o + 3 * ks[h]].reshape(ks[h], 3)
            lead = s + spec.t_start * x[o + 3 * ks[h]]
            out.append([s, lead] + list(m) + [e - straight * spec.t_end, e])
            o += 3 * ks[h] + 1
        return out

    def resid(x):
        res, samp = [], []
        for h, w in enumerate(wps_of(x)):
            pts, length, rmin, _ = route_of(w, spec.bend + FILLET_EXTRA)
            sp = _samples(np.asarray(pts))
            samp.append(sp)
            res += [np.array([(length - spec.length) * 5.0, max(0.0, spec.bend + BEND_MARGIN - rmin) * 5.0]), route_shortfalls(spec, sp, margin_frame, margin_hw) * 3.0,
                    cKDTree(sp).query(rods[h][::3])[0] * 0.02]
        d, _ = cKDTree(samp[1]).query(samp[0])
        res.append(np.maximum(0, spec.c_hh + 0.3 - d) * 3.0)
        return np.concatenate(res)
    leads = [6.0, 6.0] if init is None else [float((init[h][1] - spec.starts[h]) @ spec.t_start) for h in (0, 1)]
    x0 = np.concatenate([np.concatenate([mids[h].ravel(), [leads[h]]]) for h in (0, 1)])
    r = least_squares(resid, x0, method="trf", diff_step=1e-3, max_nfev=nfev)
    return wps_of(r.x), r.cost


def pair_shortfall(spec, wps, margin_frame=0.45, margin_hw=0.45):
    """Largest shortfall of a pair of routes on the grid, mm (0 when all rules are met)."""
    worst, samp = 0.0, []
    for w in wps:
        pts, length, rmin, _ = route_of(w, spec.bend + FILLET_EXTRA)
        sp = _samples(np.asarray(pts))
        samp.append(sp)
        worst = max(worst, float(route_shortfalls(spec, sp, margin_frame, margin_hw).max()), spec.bend - rmin, abs(length - spec.length))
    d, _ = cKDTree(samp[1]).query(samp[0])
    return max(worst, float(spec.c_hh - d.min()))


_FIT_ARGS = None


def _fit_job(tol):
    spec, rods, straight, mf, mh = _FIT_ARGS
    wps, _cost = fit_joint(spec, rods, straight, tol, mf, mh, nfev=80)
    return tol, wps, pair_shortfall(spec, wps, mf, mh)


def fit_pair(spec, rods, straight, tols=(7.0, 9.0, 11.0, 14.0), margin_frame=0.45, margin_hw=0.45):
    """The fit with the fewest corners that meets the rules on the grid (ties: the smallest shortfall). The tolerances run in forked processes, which share the
    surface trees."""
    import multiprocessing as mp
    global _FIT_ARGS
    _FIT_ARGS = (spec, rods, straight, margin_frame, margin_hw)
    with mp.get_context("fork").Pool(len(tols)) as pool:
        res = pool.map(_fit_job, tols)
    cands = [(sf_ <= 0.05, -sum(len(w) for w in wps) if sf_ <= 0.05 else -sf_, wps) for (_t, wps, sf_) in res]
    cands.sort(key=lambda c: c[:2], reverse=True)
    print("  fit: " + ", ".join(f"tol {t:g}: {sum(len(w) for w in wps)} points, shortfall {sf_:.2f}" for (t, wps, sf_) in res), flush=True)
    return cands[0][2]


FIELDS = None


def load_fields():
    global FIELDS
    if FIELDS is None:
        FIELDS = Fields()
    return FIELDS


# ---------------------------------------------------------------------------
# Pictures
# ---------------------------------------------------------------------------
VIEWS = {"left": ((-1.0, 0.0, 0.0), (0, 0, 1), True), "front_left": ((-0.75, -1.25, 0.70), (0, 0, 1), False), "top": ((0.0, -0.35, 1.0), (0, 1, 0), False),
         "board": ((0.0, -C, C), (0, C, C), True)}        # "board": looking along the board's normal, from the component side, u up


def render_case(tag, parts, hardware, fans, tubes, extra_boxes=(), views=("left", "front_left", "board")):
    """The skeleton faint, the hardware, the new fans in teal, the new hoses opaque, the connector corridor in pink."""
    import vtk
    import render_vtk
    import hose_routes
    for view in views:
        ren = vtk.vtkRenderer()
        ren.SetBackground(1, 1, 1)
        for pt in parts:
            if pt.name in REDRAWN_PARTS:
                continue
            for a in render_vtk._actors(pt.solid, render_vtk.FRAME_RGB, opacity=0.35, edges=False):
                ren.AddActor(a)
        for name, solid in hardware.items():
            if name in hw.KEEP_OUT or name in REDRAWN_HW:
                continue
            for a in render_vtk._actors(solid, render_vtk.HW_RGB.get(name, (0.6, 0.6, 0.6)), opacity=0.45, edges=True, edge_opacity=0.25):
                ren.AddActor(a)
        for f in fans:
            for a in render_vtk._actors(f, (0.05, 0.62, 0.66), opacity=0.55, edges=True, edge_opacity=0.5):
                ren.AddActor(a)
        for b in extra_boxes:
            for a in render_vtk._actors(hw.bs_box(*b), (0.85, 0.2, 0.5), opacity=0.18, edges=True, edge_opacity=0.3):
                ren.AddActor(a)
        for pts, r, rgb in tubes:
            ren.AddActor(hose_routes.tube_actor(pts, r, rgb))
        win = vtk.vtkRenderWindow()
        win.SetOffScreenRendering(1)
        win.SetSize(1500, 1150)
        win.SetAlphaBitPlanes(1)
        win.SetMultiSamples(0)
        win.AddRenderer(ren)
        ren.SetUseDepthPeeling(1)
        ren.SetMaximumNumberOfPeels(8)
        ren.UseFXAAOn()
        cam = ren.GetActiveCamera()
        d, up, par = VIEWS[view]
        cam.SetFocalPoint(0, 150, 150)
        cam.SetPosition(d[0] * 1000, 150 + d[1] * 1000, 150 + d[2] * 1000)
        cam.SetViewUp(*up)
        if par:
            cam.ParallelProjectionOn()
        ren.ResetCamera()
        cam.Zoom(1.1)
        win.Render()
        grab = vtk.vtkWindowToImageFilter()
        grab.SetInput(win)
        grab.Update()
        wr = vtk.vtkPNGWriter()
        path = os.path.join(ROOT, "previews", f"b6_study_fans_{view}_{tag}.png")
        wr.SetFileName(path)
        wr.SetInputConnection(grab.GetOutputPort())
        wr.Write()
        print("->", path)


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------
SCAN = [(140, 96, 41, 40), (140, 96, 41, 20), (140, 96, 41, 15), (140, 96, 41, 10), (140, 96, 37, 10),
        (120, 76, 41, 40), (120, 90, 41, 40), (120, 100, 41, 40),
        (120, 110, 41, 20), (120, 108, 41, 15), (120, 114, 41, 10), (120, 120, 41, 10),
        (120, 110, 61, 20), (120, 120, 61, 10)]
LEFT_OK = 0.30        # a rod solution counts as a find when no rule is short by more than this many mm (the fit to exact routes then has to meet them all)


def stage_scan(logname="scan.txt"):
    """Does the CPU pair have a route (rod, voxel rules) for a fan of size D at (u0, n0) with a straight of s mm in front of each port?"""
    import multiprocessing as mp
    lines = ["D    u0   n0   s   worst shortfall (mm)  smallest bend a/b       frame a/b    hardware a/b  fan a/b     starts ok"]
    with mp.Pool(10, initializer=_init_worker) as pool:
        for (D, u0, n0, s) in SCAN:
            fans = [fan_boxes(D, u0, n0)[0]]
            res = multistart(pool, "cpu", fans, float(s))
            if not res:
                lines.append(f"{D:<4} {u0:<4} {n0:<3} {s:<3} no start")
                continue
            v, _ps, rows, _job = res[0]
            a, b = rows[0], rows[1]
            lines.append(f"{D:<4} {u0:<4} {n0:<3} {s:<3} {v:8.2f}  {'YES' if v <= LEFT_OK else 'no ':<4} bend {a['Rmin']:5.1f}/{b['Rmin']:5.1f}   frame {a['frame']:4.1f}/{b['frame']:4.1f}   "
                         f"hw {a['hw']:4.1f}/{b['hw']:4.1f}   fan {a['fan']:4.1f}/{b['fan']:4.1f}   {sum(1 for r in res if r[0] <= LEFT_OK)}/{len(res)}")
            print(lines[-1], flush=True)
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, logname), "w").write("\n".join(lines) + "\n")


def refine(kind, spec, rods, straight, parts, hardware, fans, rounds=5):
    """Fit, measure on the solids, and where a rule is short on the solids raise the grid's margin for that kind of obstacle by the shortfall and fit again."""
    global DIST, BEND_MARGIN
    BEND_MARGIN = 0.05
    full = DIST
    DIST = full.near(np.vstack(rods), 30.0)
    mf = mh = 0.45
    for k in range(rounds):
        wps = fit_pair(spec, rods, straight, margin_frame=mf, margin_hw=mh)
        rows, tubes = measure_pair(kind, wps, parts, hardware, fans)
        is_part = lambda n: not (n.startswith("hw:") or n.startswith("own") or n == "hose x hose" or n.startswith("bend"))      # noqa: E731
        short_f = max([need - d for (n, _h, d, need) in rows if is_part(n)] + [0.0])
        short_h = max([need - d for (n, _h, d, need) in rows if need == CLEAR_HW and not is_part(n) and n != "hose x hose" and not n.startswith("bend")] + [0.0])
        short_b = max([need - d for (n, _h, d, need) in rows if n.startswith("bend")] + [0.0])
        gap = max([need - d for (n, _h, d, need) in rows if n == "hose x hose"] + [0.0])
        print(f"  {kind} round {k}: margins frame {mf:.2f} hw {mh:.2f}; shortfall on the solids: parts {short_f:.2f} hardware {short_h:.2f} hose gap {gap:.2f} bend {short_b:.2f}", flush=True)
        if short_f <= 1e-6 and short_h <= 1e-6 and gap <= 1e-6 and short_b <= 1e-6:
            break
        BEND_MARGIN += short_b + 0.1 if short_b > 0 else 0.0
        mf += short_f + 0.25 if short_f > 0 else 0.0
        mh += short_h + 0.25 if short_h > 0 else 0.0
        spec.c_hh += gap + 0.25 if gap > 0 else 0.0
    DIST = full
    return wps, rows, tubes


def stage_routes(case):
    """Routes for one case: rods, fillet fit, exact measurement, pictures. case = dict(name, D, u0, n0, s, right_x, gpu)."""
    import multiprocessing as mp
    load_fields()
    D, u0, n0, s = case["D"], case["u0"], case["n0"], float(case["s"])
    left, right = fan_boxes(D, u0, n0, case.get("right_x"))
    t0 = time.time()
    parts, _ = frame_v0.build_frame()
    hardware = hw.build_hardware()
    print(f"model {time.time() - t0:.0f} s", flush=True)
    fans = [hw.bs_box(*left), hw.bs_box(*right)]
    global DIST
    DIST = Surfaces(parts, hardware, region=((-135.0, 150.0), (60.0, 335.0), (-40.0, 235.0)))
    out = dict(case=case, left=left, right=right)
    with mp.Pool(10, initializer=_init_worker) as pool:
        spec = Spec("cpu", [left])
        res = multistart(pool, "cpu", [left], s, restarts=19)
        out["cpu_rod_violation"] = res[0][0]
        wps, rows, tubes = refine("cpu", spec, res[0][1], s, parts, hardware, fans)
        out["cpu_wps"], out["cpu_rows"], out["cpu_lengths"] = wps, rows, [route_of(w, spec.bend + FILLET_EXTRA)[1:3] for w in wps]
        print("CPU pair exact:", "ok" if exact_ok(rows) else "FAILS", flush=True)
        if case["gpu"] == "moved":
            DIST = Surfaces(parts, hardware, region=((150.0, 352.0), (40.0, 335.0), (-110.0, 235.0)))
            specg = Spec("gpu", [right])
            resg = multistart(pool, "gpu", [right], float(case.get("gpu_s", 40.0)), restarts=29, seed=7)
            out["gpu_rod_violation"] = resg[0][0]
            wpg, rowsg, tubesg = refine("gpu", specg, resg[0][1], float(case.get("gpu_s", 40.0)), parts, hardware, fans)
            out["gpu_wps"], out["gpu_rows"], out["gpu_lengths"] = wpg, rowsg, [route_of(w, specg.bend + FILLET_EXTRA)[1:3] for w in wpg]
            print("GPU pair exact:", "ok" if exact_ok(rowsg) else "FAILS", flush=True)
    return out, parts, hardware, fans, tubes


CASES = {
    "f140": dict(name="140 x 140", D=140, u0=96, n0=41, s=10, gpu="moved", gpu_s=40.0),
    "f120": dict(name="120 x 120", D=120, u0=114, n0=41, s=10, gpu="as is"),
}


def polish(kind, spec, wps, rods, straight, parts, hardware, fans, rounds=6, nfev=300):
    """Warm-started fits of an earlier pair of routes, as long as the measured routes are short of a rule on the solids; the bend and the margins grow by what was short."""
    global DIST, BEND_MARGIN
    BEND_MARGIN = 0.05
    full = DIST
    DIST = full.near(np.vstack(rods), 30.0)
    mf = mh = 0.45
    for k in range(rounds):
        rows, tubes = measure_pair(kind, wps, parts, hardware, fans)
        is_part = lambda n: not (n.startswith("hw:") or n.startswith("own") or n == "hose x hose" or n.startswith("bend"))      # noqa: E731
        short = {"f": max([need - d for (n, _h, d, need) in rows if is_part(n)] + [0.0]),
                 "h": max([need - d for (n, _h, d, need) in rows if need == CLEAR_HW and not is_part(n) and n != "hose x hose" and not n.startswith("bend")] + [0.0]),
                 "b": max([need - d for (n, _h, d, need) in rows if n.startswith("bend")] + [0.0]),
                 "g": max([need - d for (n, _h, d, need) in rows if n == "hose x hose"] + [0.0])}
        print(f"  {kind} polish {k}: shortfall on the solids {short}", flush=True)
        if max(short.values()) <= 1e-6:
            break
        BEND_MARGIN += short["b"] + 0.1 if short["b"] > 0 else 0.0
        mf += short["f"] + 0.2 if short["f"] > 0 else 0.0
        mh += short["h"] + 0.2 if short["h"] > 0 else 0.0
        spec.c_hh += short["g"] + 0.2 if short["g"] > 0 else 0.0
        wps, _cost = fit_joint(spec, rods, straight, 0.0, mf, mh, nfev=nfev, init=wps)
    DIST = full
    return wps, rows, tubes


def stage_polish(key):
    import pickle
    load_fields()
    c = CASES[key]
    path = os.path.join(OUT, f"{key}.pkl")
    out = pickle.load(open(path, "rb"))
    left, right = out["left"], out["right"]
    parts, _ = frame_v0.build_frame()
    hardware = hw.build_hardware()
    fans = [hw.bs_box(*left), hw.bs_box(*right)]
    global DIST
    DIST = Surfaces(parts, hardware, region=((-135.0, 150.0), (60.0, 335.0), (-40.0, 235.0)))
    spec = Spec("cpu", [left])
    rods = [np.asarray(route_of(w, spec.bend + FILLET_EXTRA)[0]) for w in out["cpu_wps"]]       # the earlier routes themselves keep the fit near where it was
    wps, rows, tubes = polish("cpu", spec, out["cpu_wps"], rods, float(c["s"]), parts, hardware, fans)
    out["cpu_wps"], out["cpu_rows"] = wps, rows
    out["cpu_lengths"] = [route_of(w, spec.bend + FILLET_EXTRA)[1:3] for w in wps]
    pickle.dump(out, open(path, "wb"))
    cpu = [(t[2], hw.CPU_HOSE_R, (0.10, 0.10, 0.11)) for t in tubes]
    if c["gpu"] == "moved":
        gtubes = hose_solids("gpu", out["gpu_wps"])
        gpu = [(t[2], hw.GPU_HOSE_R, (0.42, 0.24, 0.12)) for t in gtubes]
    else:
        gpu = [(h["pts"], hw.GPU_HOSE_R, (0.42, 0.24, 0.12)) for h in hoses.routes()["gpu"][0]]
    render_case(key, parts, hardware, fans, cpu + gpu, extra_boxes=[CORRIDOR_BS])


def stage_case(key):
    import pickle
    out, parts, hardware, fans, tubes = stage_routes(CASES[key])
    cpu = [(t[2], hw.CPU_HOSE_R, (0.10, 0.10, 0.11)) for t in tubes]
    if CASES[key]["gpu"] == "moved":
        gtubes = hose_solids("gpu", out["gpu_wps"])
        gpu = [(t[2], hw.GPU_HOSE_R, (0.42, 0.24, 0.12)) for t in gtubes]
    else:
        gpu = [(np.array([hoses.world_to_bs(p) for p in h["pts"]]) if False else h["pts"], hw.GPU_HOSE_R, (0.42, 0.24, 0.12)) for h in hoses.routes()["gpu"][0]]
    os.makedirs(OUT, exist_ok=True)
    pickle.dump(out, open(os.path.join(OUT, f"{key}.pkl"), "wb"))
    render_case(key, parts, hardware, fans, cpu + gpu, extra_boxes=[CORRIDOR_BS])
    for kind in ("cpu", "gpu"):
        for (what, h, d, need) in out.get(f"{kind}_rows", []):
            print(f"{kind} {what:60s} hose {h} {d:7.2f}  need {need:g}  {'' if d >= need - 1e-6 else 'SHORT'}")


VIDEO_BRACKET_X = -124.0              # the card's video outputs face -X from here; u 76..127, n 5..115 (docs/plans/external-cables.md)
VIDEO_UN = ((76.0, 127.0), (5.0, 115.0))
VIDEO_PLUG = 80.0                     # a DisplayPort plug with its bend, about


def extras(out, tubes_cpu_world, tubes_gpu_world=()):
    """Facts about a case that are not hose rules: the video outputs, the cables that cross a new place, the fan leads. Returns text lines."""
    import cables
    lines = []
    left, right = out["left"], out["right"]
    # the video outputs
    gap_x = FAN_X["left"][1] - VIDEO_BRACKET_X
    lines.append(f"video outputs: the left fan's inner face is X {FAN_X['left'][1]:g}, {abs(gap_x):.1f} mm from the bracket plane X {VIDEO_BRACKET_X:g} (the plug needs about {VIDEO_PLUG:g})")
    ou, on = (max(left[2], VIDEO_UN[0][0]), min(left[3], VIDEO_UN[0][1])), (max(left[4], VIDEO_UN[1][0]), min(left[5], VIDEO_UN[1][1]))
    if ou[1] > ou[0] and on[1] > on[0]:
        lines.append(f"  the fan stands in front of the outputs over u {ou[0]:g}..{ou[1]:g}, n {on[0]:g}..{on[1]:g} ({(ou[1] - ou[0]) * (on[1] - on[0]):.0f} of {(VIDEO_UN[0][1] - VIDEO_UN[0][0]) * (VIDEO_UN[1][1] - VIDEO_UN[1][0]):.0f} mm2 of the bracket's face); the rest of the outputs face open air")
    else:
        lines.append("  the fan does not stand in front of the outputs")
    zone = (hw.x_to_v(VIDEO_BRACKET_X - VIDEO_PLUG), hw.x_to_v(VIDEO_BRACKET_X), VIDEO_UN[0][0], VIDEO_UN[0][1], VIDEO_UN[1][0], VIDEO_UN[1][1])
    for h, pts in enumerate(tubes_cpu_world):
        d = box_sdf(board_of(pts), zone)[0].min() - hw.CPU_HOSE_R
        lines.append(f"  CPU hose {'ab'[h]} to the plug zone (X {VIDEO_BRACKET_X - VIDEO_PLUG:g}..{VIDEO_BRACKET_X:g}, u {VIDEO_UN[0][0]:g}..{VIDEO_UN[0][1]:g}, n {VIDEO_UN[1][0]:g}..{VIDEO_UN[1][1]:g}): {d:.1f} mm")
    # cables near the new places
    rts = cables.build_routes()
    for name, rt in rts.items():
        best = {}
        for pts, r in rt.strands:
            bp_ = board_of(np.asarray(pts))
            for lab, box in (("left fan", left), ("right fan", right)):
                best[lab] = min(best.get(lab, 1e9), box_sdf(bp_, box)[0].min() - r)
            for h, hp in enumerate(tubes_cpu_world):
                dd, _ = cKDTree(hp).query(np.asarray(pts))
                best[f"CPU hose {'ab'[h]}"] = min(best.get(f"CPU hose {'ab'[h]}", 1e9), dd.min() - r - hw.CPU_HOSE_R)
            for h, hp in enumerate(tubes_gpu_world):
                dd, _ = cKDTree(hp).query(np.asarray(pts))
                best[f"card hose {'ab'[h]}"] = min(best.get(f"card hose {'ab'[h]}", 1e9), dd.min() - r - hw.GPU_HOSE_R)
        near = {k: v for k, v in best.items() if v < 15.0}
        if near:
            lines.append(f"  cable {name}: " + ", ".join(f"{k} {v:.1f} mm" for k, v in sorted(near.items(), key=lambda kv: kv[1])))
    return lines


SUMMARY = [
    "SUMMARY",
    "  YES for both sizes, at a price the plan has not got today: the straight run in front of each 420 port goes from 40 mm to 10 mm, and the hoses take a long way round.",
    "  What binds is the S-bend that takes each CPU hose from the lane inside the fan (X -192.8, the fan's inner face -204 plus 11.2) out to the port line (X -220.6): two arcs of",
    "  35 mm need about 56 mm along u, and the fan's up-slope edge u1 = u0 + D plus 11.2 mm must be behind it. So the limit found is u1 <= about 251 - 1.3 s (s = the straight in mm):",
    "  s 10 -> u1 up to about 238; s 15 -> about 231; s 40 -> about 200. The lower edge (n 41 against 37) and the fan's n range do not change that.",
    "  140 x 140, n 41..181: u0 96 (the lowest the front plane allows: Y -0.1) -> u1 236 -> s 10 only. The right fan then needs the card's hoses moved, and 3 mm further out (X 204..229,",
    "     the mirror of the left): at X 201..226 the card's hoses cannot take the turn out of the card's end, 34 mm between the card's end and the fan's face against R 35 (best 32.5).",
    "  120 x 120, n 41..161: u0 114..116 -> u1 234..236 -> s 10; the card's hoses stay as they are (6.4 mm from the right fan at X 201..226 from u0 114 on, 9.4 mm at X 204..229; the route of the card's hoses was not changed or re-measured).",
    "     With s 40 the 120 mm fan would need u0 <= about 80 (u0 76 works), where the card's hoses have to move too.",
    "  120 makes the CPU route easier by 20 mm of u1 at the same u0: it takes the plan's straight of 40 mm at u0 76..80 or 15 mm at u0 108, where the 140 takes only 10 mm at u0 96.",
    "  Every rule is met on the solids in both cases; clearances of 5.1..5.5 mm are the rule's own 5 mm plus what the fit was asked to keep (the hoses sit on the limit at several places).",
]
CHANGES = [
    "WHAT ELSE HAS TO CHANGE",
    "  fan_bracket_left, fan_bracket_right: they hang on rib_A at u 121 (X +-158). The left fan moves 24 mm outwards (inner face X -180 -> -204), the right one 0..3 mm, so a leg from the rib",
    "    to the fan's face is 46 mm long and crosses the lane the hoses use (CPU hose b is 5.9 mm from the 140 left fan, card hose a 5.8 mm from the 140 right fan): the plate and leg have to be",
    "    redrawn round the routes, or the fans held from the outer face / the 420's antler. Both brackets are new parts.",
    "  hose_guide_cpu (on neck_left at the old lane) and hose_guide_gpu (on rib_A_right, up-slope run behind the board) stand where the old routes were: both are redrawn or dropped. The new CPU",
    "    routes have 8 to 12 bends in free air (rise to n 150, S-bends, rise again); a guide or a tie point is needed where a hose could sag, not decided here.",
    "  hoses.py: the CPU routes and, for 140, the card's, are new waypoint lists; FLANK_RUN goes from 40 to 10 mm; hardware.py: FAN_SIDE_X, FAN_SIDE_U, FAN_SIDE_N (fan_side_left, fan_side_right are",
    "    one place mirrored), FAN_SIDE_IN, CPU hose keep-outs follow from hoses.py. IO_ZONE_BS stays (the corridor of this study is its footprint carried out to the fans' inner face).",
    "  cables: fan_left in cables.py starts at the old inner face (X -180) and has to be redrawn from the new fan (24 mm further out, and its u 177.5 stands inside the new fan's span);",
    "    fan_right starts at the old rear edge (u 260), the new fan ends at u 234..236. Neither crosses the new hoses (see the list above); the leads stay within their 400 mm (233 mm free today).",
    "  the card's video outputs (bracket X -124, u 76..127, n 5..115): the left fan's inner face is X -204, exactly 80 mm from the bracket plane, the plug's 80 mm with no margin; the 140 fan stands in front of",
    "    41 % of the bracket's face (u 96..127, n 41..115), the 120 fan in front of 17 % (u 114..127). The rest, and everything below n 41, faces open air. gpu_post still has to become a frame.",
    "  the organic layer: the left flank window moves up with the fan; the hoses stay 10 mm inside it by the rule that exists for the card and the PSU (not checked here, the layer is ignored).",
    "  frame check 8 does not see the fans (hardware): the 140 fan's lowest front corner is at Y -0.1, the 120's at Y 26.8.",
]
UNVERIFIED = [
    "NOT VERIFIED",
    "  the hoses as real objects: they are centre lines of 12.4 and 11.2 mm hoses with a 35 mm bend; their stiffness, twist and sag are not modelled, and routes with 8 to 12 bends in air are only as good as that.",
    "  the hose length (450 mm from the spec sheet; the product page says 500, which would add 50 mm of slack to every route and not be taken up by these shapes without a rerun).",
    "  the ports' and collars' real positions (the project's numbers are used, +-3 mm on the CPU block's collars), and that the hose can leave a collar at the bend the routes assume.",
    "  a 10 mm straight in front of a port: whether the ARCTIC and MSI hose ends need more than 10 mm square to the radiator face. This is the plan's number that has to go.",
    "  the organic layer and anything printed that is not in frame_v0.build_frame; cables only against the routes drawn in cables.py today; the new fan leads are not routed.",
    "  the search is not exhaustive: the rods start from shortest paths and random via points (8..20 starts); a NO in the scan means no start found a route, not a proof. The distances of a YES are exact.",
]


def route_text(label, wps, kind):
    spec_bend = hoses.BEND_R
    pts, length, rmin, _t = route_of(wps, spec_bend + FILLET_EXTRA)
    rows = [f"  {label}: {len(wps)} way-points, length {length:.2f} mm (target {hoses.CPU_HOSE['length'] - hoses.CPU_SPARE if kind == 'cpu' else hoses.GPU_HOSE['length'] - hoses.GPU_SPARE:g}), smallest bend radius {rmin:.2f} mm",
            "    board space (v, u, n), X = v - 122: " + " ".join("(" + ", ".join(f"{float(x):.1f}" for x in q) + ")" for q in wps)]
    return rows


def stage_report():
    import pickle
    lines = ["Study: both side fans raised and mirrored, so that the board's rear connectors are open towards -X.",
             "Run:  .venv/bin/python cad_b6/study_side_fans.py fields | scan | case f140 | case f120 | report     (nothing committed is changed)", ""]
    lines += ["RULES USED",
              f"  hose bend radius >= {hoses.BEND_R:g} mm; length exactly as hoses.py solves it (CPU {hoses.CPU_HOSE['length'] - hoses.CPU_SPARE:g}, card {hoses.GPU_HOSE['length'] - hoses.GPU_SPARE:g} mm)",
              f"  frame parts: check 9's rule, keep-out (hose radius + {hw.HOSE_ALLOW:g}) >= {CLEAR_PART:g} mm from every part; hardware (fans, radiators, card, board): the hose's own surface >= {CLEAR_HW:g} mm",
              f"  the two hoses of a pair: surface gap >= {HOSE_GAP:g} mm (the model's today: 2.7 CPU, 3.6 card)",
              f"  the connector corridor, X {FAN_X['left'][1]:g}..{hw.IO_ZONE_BS[1] - 122:g} (the io_zone's footprint carried on to the fans' inner face): the hose surface >= {CLEAR_HW:g} mm from it",
              "  envelope as check 8: keep-out inside |X| 229 and Y >= 0; the fans' outer faces at |X| 229 (a pure mirror), 25 mm thick",
              "  distances measured on the solids with the project's own hose chains (hoses.chain_points, trimmed at the port boxes) and solid_distance; the search used a 1.5 mm voxel field, the fit 0.6 mm surface samples", ""]
    lines += SUMMARY + [""]
    scan = os.path.join(OUT, "scan.txt")
    if os.path.exists(scan):
        lines += ["SEARCH: does the CPU pair have a route for a fan D x D at (u0, n0) with s mm straight in front of each port? (rods of exact length, voxel rules; YES = no rule short by more than 0.3 mm)"]
        lines += ["  " + l for l in open(scan).read().splitlines()] + [""]
    for key in ("f140", "f120"):
        path = os.path.join(OUT, f"{key}.pkl")
        if not os.path.exists(path):
            continue
        o = pickle.load(open(path, "rb"))
        c = o["case"]
        lines += [f"CASE {c['name']}: fans at u {c['u0']:g}..{c['u0'] + c['D']:g}, n {c['n0']:g}..{c['n0'] + c['D']:g}, left X {FAN_X['left'][0]:g}..{FAN_X['left'][1]:g}, right X {o['right'][0] - 0 + hw.ORIGIN[0]:g}..{o['right'][1] + hw.ORIGIN[0]:g}; straight in front of each 420 port {c['s']:g} mm",
                  f"  front corner of the fan: Y {60 + (c['u0'] - (c['n0'] + c['D'])) * C:.1f} (front plane 0)"]
        lines += route_text("CPU hose a (to the port at n 42.1)", o["cpu_wps"][0], "cpu") + route_text("CPU hose b (to the port at n 65.9)", o["cpu_wps"][1], "cpu")
        rows = o["cpu_rows"]
        lines.append("  CPU hoses, nearest things (exact, mm; hose a / hose b):")
        names = sorted({r[0] for r in rows})
        tab = []
        for n in names:
            d = {r[1]: r[2] for r in rows if r[0] == n}
            tab.append((min(d.values()), n, d))
        for dmin, n, d in sorted(tab)[:12]:
            lines.append(f"    {n:62s} {d.get(0, float('nan')):6.2f} / {d.get(1, float('nan')):6.2f}   (needs {[r[3] for r in rows if r[0] == n][0]:g})")
        world = [world_route(w, hoses.BEND_R)[0] for w in o["cpu_wps"]]
        gworld = [world_route(w, hoses.BEND_R)[0] for w in o["gpu_wps"]] if c["gpu"] == "moved" else [h["pts"] for h in hoses.routes()["gpu"][0]]
        lines += extras(o, world, gworld)
        if c["gpu"] == "moved":
            lines.append("  the card's hoses, moved (the right fan stands 3 mm further out, X 204..229):")
            lines += route_text("card hose a", o["gpu_wps"][0], "gpu") + route_text("card hose b", o["gpu_wps"][1], "gpu")
            tab = []
            for n in sorted({r[0] for r in o["gpu_rows"]}):
                d = {r[1]: r[2] for r in o["gpu_rows"] if r[0] == n}
                tab.append((min(d.values()), n, d))
            for dmin, n, d in sorted(tab)[:10]:
                lines.append(f"    {n:62s} {d.get(0, float('nan')):6.2f} / {d.get(1, float('nan')):6.2f}")
        lines.append("")
    lines += CHANGES + [""] + UNVERIFIED
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(HERE, "report_study_side_fans.txt"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "fields"
    if stage == "fields":
        build_fields()
    elif stage == "scan":
        stage_scan()
    elif stage == "case":
        stage_case(sys.argv[2])
    elif stage == "polish":
        stage_polish(sys.argv[2])
    elif stage == "report":
        load_fields()
        stage_report()
