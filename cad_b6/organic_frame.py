#!/usr/bin/env python3
"""Organic outer layer over the plate skeleton: a sketch of the form.

Run:  .venv/bin/python cad_b6/organic_frame.py
Out:  previews/b6_shell_organic_<view>.png

The skeleton in frame_v0.py holds every component and is shown in light grey. The organic layer
(dark) is decoration fixed to the skeleton: bones that frame the fans and trace the outer form, and
films of threads pulled across the open spaces. The fans set its level: it lies in the planes of
their outer faces. Nothing here carries a component, has fixings, is split for printing or is
checked yet. Everything stays inside the radiators' span (|X| <= 229).
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hardware as hw
import hoses
import shell_concepts as sc
import frame_v0                                # after shell_concepts: cadquery has to load before vtk

K = 15.0                                   # blend radius at the joints


def bp(u, n, x):
    y, z = hw.bp(0, u, n)[1:]
    return (x, y, z)


# The fans set the level of the organic layer: it lies in the planes of their outer faces.
FAN360_N = hw.RAD360_BS[5]                 # outer face of the 360's fans
FACE_N = FAN360_N - 6.5                    # centre line of a bone lying flush with that face
LIP_U = hw.RAD360_BS[2] - 6.5              # just below the 360's lower edge
CARD_N = hw.GPU_BS[5]                      # the card's outer edge
PLA_GAP = 10.0                             # PLA keeps this far from the graphics card and the PSU
CARD_BONE_U, CARD_BONE_N = 118.0, CARD_N + PLA_GAP + 8.0   # a bone over the card's top edge, clear of it
SWEEP_X = 170.0                            # the flank sweeps pass this far out, clear of the card's ends
SILL = frame_v0.sill_geometry()            # the skeleton's front sill: section (Y, Z), the light slit's cutter
SILL_RIDGE = SILL["pts"][2]                # (Y, Z) of its upper edge, above the light line
SILL_GAP = 2.5                             # the organic layer keeps this far from the sill
BROW = [(-158, 8, 150), (0, 6, 157), (158, 8, 150)]        # bone across the front, well below the card
LIP_BONE = [bp(LIP_U, FACE_N, -190), bp(LIP_U - 1, FACE_N + 1, -60), bp(LIP_U - 1, FACE_N + 1, 60),
            bp(LIP_U, FACE_N, 190)]
CARD_BONE = [bp(CARD_BONE_U, CARD_BONE_N, -SWEEP_X), bp(CARD_BONE_U + 1, CARD_BONE_N + 1, 0),
             bp(CARD_BONE_U, CARD_BONE_N, SWEEP_X)]
RING_X = {1: sum(hw.FAN_SIDE_X["fan_side_right"]) / 2 + 2.5, -1: sum(hw.FAN_SIDE_X["fan_side_left"]) / 2}
BASE = {s: [(160 * s, 40, -4), (163 * s, 110, -5), (161 * s, 196, -4), (166 * s, 290, -5), (166 * s, 356, -4)]
        for s in (1, -1)}


def sill_sdf(G):
    """Signed distance to the front sill's prism (pocket and channel ignored); never more than the true distance outside."""
    X, Y, Z = G
    d = np.abs(X) - frame_v0.SILL_HALF_X
    pts = list(SILL["pts"])
    for (y0, z0), (y1, z1) in zip(pts, pts[1:] + pts[:1]):
        ny, nz = -(z1 - z0), y1 - y0                       # outward normal: the section runs clockwise in (Y, Z)
        d = np.maximum(d, ((Y - y0) * ny + (Z - z0) * nz) / math.hypot(ny, nz))
    return d


def ring(s):
    """Closed bone round a side fan, in the fan's own thickness."""
    (u0, u1), (n0, n1) = hw.FAN_SIDE_U, hw.FAN_SIDE_N
    a, b, c, e = u0 - 5, u1 + 5, n0 - 6, n1 + 6
    um, nm = (a + b) / 2, (c + e) / 2
    pts = [(a, nm), (a, e - 14), (a + 14, e), (um, e + 1), (b - 14, e), (b, e - 14), (b, nm), (b, c + 14),
           (b - 14, c), (um, c - 1), (a + 14, c), (a, c + 14), (a, nm)]
    return [bp(u, n, RING_X[s]) for u, n in pts]


def front_sweep(s):
    """From the front foot up past the card's edge to the corner of the 360's lip."""
    return [(158 * s, 22, 4), (164 * s, 10, 100), (166 * s, 9, 152), bp(CARD_BONE_U, CARD_BONE_N, SWEEP_X * s),
            bp(LIP_U, FACE_N, 190 * s)]


def rear_sweep(s):
    """From the fan ring, under the 420 and down the back to the rear foot."""
    x = RING_X[s]
    return [bp(hw.FAN_SIDE_U[1] + 5, 84, x), bp(300, 40, x - 2 * s), bp(332, -34, x - 10 * s),
            (x - 16 * s, 362, 150), (176 * s, 372, 40), (166 * s, 368, -6)]


def side_bone(s):
    """Past the end of the 360, flush with its fans, and down to the skeleton's neck."""
    return [bp(LIP_U, FACE_N, 190 * s), bp(240, FACE_N + 1, 204 * s), bp(300, FACE_N - 2, 203 * s),
            bp(301, 126, 203 * s), bp(298, 116, 190 * s)]


def bone(r_a, r_mid, r_b):
    """Radius profile of a bone: thick at both joints, slim in the middle."""
    def prof(t):
        w = (2 * t - 1) ** 2
        end = r_a if t < 0.5 else r_b
        return r_mid + (end - r_mid) * w
    return prof


def bones(G):
    d = np.full(G[0].shape, 1e9, dtype=np.float32)

    def add(ctrl, r0, r1=None, k=K):
        nonlocal d
        d = sc.smin(d, sc.tube(G, ctrl, r0, r1), k)

    def knot(p, r, k=K):
        nonlocal d
        X, Y, Z = G
        d = sc.smin(d, np.sqrt((X - p[0]) ** 2 + (Y - p[1]) ** 2 + (Z - p[2]) ** 2) - r, k)

    add(LIP_BONE, bone(7, 5.5, 7))
    add(CARD_BONE, bone(6.5, 5, 6.5))
    add(BROW, bone(7, 5, 7))
    for s in (1, -1):
        add(ring(s), 5.5)
        add(front_sweep(s), bone(10, 6, 8))
        add(rear_sweep(s), bone(7, 5.5, 10))
        add(side_bone(s), bone(7, 5, 7))
        # ties to the skeleton: the 360's arm, and the card's supports
        add([bp(LIP_U, FACE_N, 190 * s), bp(LIP_U + 3, 142, 186 * s), bp(190, 113, 172.5 * s)], bone(7, 5, 7))
        for p, r in ((front_sweep(s)[0], 13), (rear_sweep(s)[-1], 13), (bp(LIP_U, FACE_N, 190 * s), 10)):
            knot(p, r)
    return d


# ---------------------------------------------------------------------------
# Films: thin strands pulled between two bones, like a viscous liquid being stretched
# ---------------------------------------------------------------------------
WEB_VOX = 1.25


def film(a_ctrl, b_ctrl, n, seed, r_a=8.0, r_b=8.0, sag=(0.0, 0.0, -1.0), sag_mm=10.0, links=3):
    """Mesh of a film of n strands between bone A and bone B (both given as control points)."""
    rng = np.random.default_rng(seed)
    A, Bc = sc.spline(a_ctrl, step=4.0), sc.spline(b_ctrl, step=4.0)
    lo = np.minimum(A.min(axis=0), Bc.min(axis=0)) - 16.0
    hi = np.maximum(A.max(axis=0), Bc.max(axis=0)) + 16.0
    xs, ys, zs = (np.arange(lo[i], hi[i] + WEB_VOX, WEB_VOX, dtype=np.float32) for i in range(3))
    G = np.meshgrid(xs, ys, zs, indexing="ij")
    d = sc.smin(sc.tube(G, a_ctrl, r_a), sc.tube(G, b_ctrl, r_b))
    ta = np.clip(np.linspace(0.04, 0.96, n) + rng.normal(0, 0.035, n), 0.02, 0.98)
    tb = np.clip(ta + rng.normal(0, 0.11, n), 0.02, 0.98)
    mids = []
    sag = np.array(sag, dtype=float)
    for i in range(n):
        p0 = A[int(ta[i] * (len(A) - 1))]
        p1 = Bc[int(tb[i] * (len(Bc) - 1))]
        along = (p1 - p0) / np.linalg.norm(p1 - p0)
        jitter = rng.normal(0, 5.0, 3)
        jitter -= along * (jitter @ along)
        mid = (p0 + p1) / 2 + sag * rng.uniform(0.3, 1.0) * sag_mm + jitter
        mids.append(mid)
        r_end0, r_end1, r_mid = rng.uniform(3.4, 5.0), rng.uniform(3.4, 5.0), rng.uniform(1.7, 2.3)
        d = sc.smin(d, sc.tube(G, [p0, mid, p1], bone(r_end0, r_mid, r_end1)), 10.0)
    for _ in range(links):                               # a few cross-threads between neighbours
        i = int(rng.integers(0, n - 1))
        f0, f1 = rng.uniform(0.25, 0.75), rng.uniform(0.25, 0.75)
        q0 = A[int(ta[i] * (len(A) - 1))] * (1 - f0) + Bc[int(tb[i] * (len(Bc) - 1))] * f0
        q1 = A[int(ta[i + 1] * (len(A) - 1))] * (1 - f1) + Bc[int(tb[i + 1] * (len(Bc) - 1))] * f1
        d = sc.smin(d, sc.tube(G, [q0, (q0 + q1) / 2 + sag * 3.0, q1], bone(2.8, 1.6, 2.8)), 7.0)
    d = sc.keep_clear(G, d)
    Gb = sc.to_bs(G)
    for b in (hw.DIMMS_BS, hw.IO_ZONE_BS, hw.ATX24_BS, hw.EPS_BS):
        d = np.maximum(d, 3.0 - sc.box_world(Gb, b))
    d = np.maximum(d, SILL_GAP - sill_sdf(G))
    d = np.maximum(d, np.abs(G[0]) - 229.0)
    vox, sc.VOX = sc.VOX, WEB_VOX
    try:
        return sc.mesh(xs, ys, zs, d)
    finally:
        sc.VOX = vox


def films():
    out = []
    lip_l = [bp(LIP_U, FACE_N, -190), bp(LIP_U - 1, FACE_N + 1, -60), bp(LIP_U - 1, FACE_N + 1, 28)]
    lip_r = [bp(LIP_U - 1, FACE_N + 1, 44), bp(LIP_U - 1, FACE_N + 1, 110), bp(LIP_U, FACE_N, 190)]
    # The gap between the card's outer edge and the 360's lower edge, at the level the fans set.
    # On the left the CPU hoses lie in that same surface, so the threads dip underneath them.
    cu, cn = CARD_BONE_U, CARD_BONE_N
    out.append(film([bp(cu, cn, -SWEEP_X), bp(cu + 1, cn + 1, -60), bp(cu + 1, cn + 1, 28)], lip_l,
                    8, seed=3, r_a=6.0, r_b=6.0, sag=(0.0, 0.707, -0.707), sag_mm=20, links=3))
    out.append(film([bp(cu + 1, cn + 1, 44), bp(cu + 1, cn + 1, 100), bp(cu, cn, SWEEP_X)], lip_r,
                    9, seed=8, r_a=6.0, r_b=6.0, sag=(0.0, 0.707, -0.707), sag_mm=4, links=4))
    # a sparse veil across the open front, from the sill's upper edge (behind the light line) up to the brow, well below the card
    ry, rz = SILL_RIDGE
    out.append(film([(-135, ry + 1, rz + 5), (0, ry + 1, rz + 6), (135, ry + 1, rz + 5)], BROW, 7, seed=41, r_a=5.0, r_b=6.0,
                    sag=(0.0, 1.0, 0.0), sag_mm=5, links=2))
    for s, dense in ((-1, True), (1, False)):
        r = ring(s)
        (u0, u1), (n0, n1) = hw.FAN_SIDE_U, hw.FAN_SIDE_N
        x = RING_X[s]
        # round each side fan the threads run out to the bones that surround it
        out.append(film([bp(u0 - 5, n0 + 10, x), bp(u0 - 5, 28, x), bp(u0 - 5, n1 - 10, x)],
                        front_sweep(s)[1:4], 6 if dense else 4, seed=50 + s, r_a=5.0, r_b=7.0,
                        sag=(0.4 * s, 0.0, 0.0), sag_mm=8, links=2))
        out.append(film([bp(u0 + 12, n0 - 6, x), bp(190, n0 - 7, x), bp(u1 - 12, n0 - 6, x)], BASE[s][:4],
                        8 if dense else 5, seed=60 + s, r_a=5.0, r_b=6.5, sag=(0.4 * s, 0.0, 0.0), sag_mm=10))
        out.append(film([bp(u0 + 12, n1 + 6, x), bp(190, n1 + 7, x), bp(u1 - 12, n1 + 6, x)],
                        side_bone(s)[:3], 6 if dense else 4, seed=70 + s, r_a=5.0, r_b=5.5,
                        sag=(0.5 * s, 0.0, 0.0), sag_mm=6, links=2))
        # the rear window over the PSU's side
        out.append(film(BASE[s][2:], rear_sweep(s)[1:5], 9 if dense else 5, seed=80 + s, r_a=6.5, r_b=6.5,
                        sag=(0.4 * s, 0.0, 0.0), sag_mm=9))
    return out


def main():
    import vtk
    xs, ys, zs, X, Y, Z = sc.grid()
    G = (X, Y, Z)
    sc.CLEAR = 4.0
    sc.HOT_CLEAR = PLA_GAP
    d = sc.keep_clear(G, bones(G))
    d = np.maximum(d, SILL_GAP - sill_sdf(G))
    Gb = sc.to_bs(G)
    for b in (hw.DIMMS_BS, hw.IO_ZONE_BS):
        d = np.maximum(d, 2.0 - sc.box_world(Gb, b))
    d = np.maximum(d, np.abs(X) - 229.0)                  # stay inside the radiators' span
    layer = sc.mesh(xs, ys, zs, d)
    vol = float((d < 0).sum()) * sc.VOX ** 3 / 1000.0
    both = vtk.vtkAppendPolyData()
    both.AddInputData(layer)
    webs = films()
    for w in webs:
        both.AddInputData(w)
    both.Update()
    b = both.GetOutput().GetBounds()
    print(f"органический слой: объём костей ≈ {vol:.0f} см³ ({vol * 1.04:.0f} г сплошного ABS), плёнок {len(webs)}, "
          f"X {b[0]:.0f}..{b[1]:.0f}, Y {b[2]:.0f}..{b[3]:.0f}, Z {b[4]:.0f}..{b[5]:.0f}")
    parts, _ = frame_v0.build_frame()
    extras = [(SILL["cuts"]["slit"], (1.0, 0.86, 0.35), 1.0)]           # the light line; the sill itself is a skeleton part
    sc.render("organic", both.GetOutput(), hw.build_hardware(), parts, hoses.routes(), extras)


if __name__ == "__main__":
    main()
