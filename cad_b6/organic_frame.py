#!/usr/bin/env python3
"""Organic outer layer over the plate skeleton: one printable-in-principle solid with its fixings.

Run:  .venv/bin/python cad_b6/organic_frame.py
Out:  previews/b6_shell_organic_<view>.png, cad_b6/report_organic.txt, out/organic/field.npz

The skeleton in frame_v0.py holds every component and is shown in light grey. The organic layer
(dark, PLA) is decoration fixed to the skeleton: bones that frame the fans and trace the outer form,
and films of strands pulled across the open spaces. The fans set its level: it lies in the planes of
their outer faces. It carries no component.

Everything is one signed-distance field on one grid, so the layer is one solid:
- members: bones, film strands, and a stub from each fixing pad to the nearest bone;
- carved back from the hardware, the hoses, the board's keep-outs, the sill and the skeleton;
- fixing pads: flat discs that sit on a skeleton face, one M3 screw each into a heat-set insert in the
  ABS part. Where they are is hardware.ORGANIC_PADS; frame_v0.py cuts the insert pilot there.
Checks at the end: every pad sits on its part's face on an M3 pilot of that part, with room for the insert
and away from the part's other holes; pads clear the hardware and the hoses; the layer is one connected
piece that contains every pad.
Not done here: the split into printable pieces, and the strength run (organic_strength.py).
"""
from __future__ import annotations

import math
import os
import sys
import time

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hardware as hw
import hoses
import shell_concepts as sc
import frame_v0                                # after shell_concepts: cadquery has to load before vtk

K = 15.0                                   # blend radius at the joints
VOX = 1.5                                  # grid step of the one field, mm
PLA_RHO = 1.24                             # g/cm3

# Strength rules (docs/plans/cables-and-organic.md): nothing thinner than these.
STRAND_R_MID = (3.0, 3.6)                  # film strand radius at mid-span (was 1.7..2.3)
STRAND_R_END = (4.5, 6.0)                  # and where it leaves a bone (was 3.4..5.0)
LINK_R = (3.4, 2.6)                        # cross-thread: at its ends, at mid-span (was 2.8, 1.6)
STRAND_SLENDER = 36.0                      # a strand's mid radius is at least its length / this: a 30 N push at mid-span stays near 10 MPa

# Bone radii: (at one joint, mid-span, at the other joint), or one number for a constant radius
BONE_R = {"lip": (7, 5.5, 7), "card": (6.5, 5, 6.5), "brow": (7, 5, 7), "ring": 6.5, "front": (10, 6, 8), "rear": (7, 5.5, 10),
          "side": (7, 5, 7), "base": 6.5}
CRUMB_CM3 = 6.0                            # loose pieces smaller than this (one strand cut at both ends is about 4) are carving crumbs and are dropped
MIN_THICK = 4.5                            # carving leaves slivers; whatever is thinner than this is removed

# Fixings to the skeleton
PAD_R, PAD_H = 8.0, 5.0                    # pad disc on a skeleton face
SCREW_R, HEAD_R, HEAD_REACH = 1.75, 3.6, 45.0   # M3 clearance through the pad; head and driver channel above it
KNOT_R = 10.0                              # a knot of material round every pad, so the driver channel leaves walls even where a bone lies on the pad
DRIVER_FREE = 11.0                         # beyond the knot no bone's centre line may come this close to the screw axis (the channel would cut it)
STUB = (6.5, 5.5, 6.5)                     # stub from pad to bone: radius at pad, mid, bone
RING_TIE = (6.5, 5.5, 6.5)                 # the left ring's tie to the front sweep: radius at the ring, mid, the sweep
GAP_SKEL = 2.0                             # the layer keeps this far from every skeleton part, except at the pads
GAP_KEEP = 3.0                             # and from the board's keep-out boxes
GAP_HW = 4.0                               # and from hardware and hoses
PAD_SEAT = 4.0                             # flat skeleton face a pad needs round its screw (the skeleton's own rule round a screw); the rim may overhang a narrow member
PAD_HOLE_WALL = 2.1                        # material kept between an insert pilot and a part's own hole
STUB_CONE_DEG = 35.0                       # a stub does not leave the pad inside this cone about the screw axis (driver access)


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
TOP_FILM_L_U0 = 186.0                      # left fan, film from the ring's top to the side bone: first thread past the CPU hoses (hose b at u 170 + 6.2 + GAP_HW + a thread's radius)
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


RING_OFF = 10.0                            # the ring's centre line stands this far outside the fan's frame: its radius plus the hardware gap
RING_TOP = {1: 18.0, -1: RING_OFF}         # above the fan: on the right the fan bracket's rail lies 6 mm above the fan, so the ring passes over it
RING_R_FEET = (70.0, -30.0)                # right side: n where the arch ends on its near side and on its far side
RING_L_GAP = (26.0, 94.0)                  # left side: the stretch of the far side (n) left open for the CPU hose guide


def ring(s):
    """Bone round a side fan, in the fan's own thickness.
    Left: a ring open on its far side, where the CPU hose guide and the hoses sit. Right: the graphics card's hoses run along the fan's near side and under it, so the ring is an arch
    over the fan from the near side to the far side; the hoses close the frame."""
    (u0, u1), (n0, n1) = hw.FAN_SIDE_U, hw.FAN_SIDE_N
    a, b, c, e = u0 - RING_OFF, u1 + RING_OFF, n0 - RING_OFF, n1 + RING_TOP[s]
    um, nm = (a + b) / 2, (c + e) / 2
    if s > 0:
        pts = [(a, RING_R_FEET[0]), (a, e - 14), (a + 14, e), (um, e + 1), (b - 14, e), (b, e - 14), (b, nm), (b, RING_R_FEET[1])]
    else:
        pts = [(b, RING_L_GAP[0]), (b, c + 14), (b - 14, c), (um, c - 1), (a + 14, c), (a, c + 14), (a, nm), (a, e - 14), (a + 14, e),
               (um, e + 1), (b - 14, e), (b, RING_L_GAP[1])]
    return [bp(u, n, RING_X[s]) for u, n in pts]


def front_sweep(s):
    """From the front foot up past the card's edge to the corner of the 360's lip.
    On the left the CPU hoses turn down the flank exactly between the card's edge and that corner, so the sweep stops at the card's edge."""
    pts = [(158 * s, 22, 4), (164 * s, 10, 100), (166 * s, 9, 152), bp(CARD_BONE_U, CARD_BONE_N, SWEEP_X * s)]
    return pts + [bp(LIP_U, FACE_N, 190 * s)] if s > 0 else pts


def rear_sweep(s):
    """From the fan ring's far side, outside the neck, under the 420 and down the back to the rear foot."""
    x = RING_X[s]
    top = [bp(hw.FAN_SIDE_U[1] + RING_OFF, 84, x), bp(292, 20, 204 * s)] if s > 0 else \
        [bp(hw.FAN_SIDE_U[1] + RING_OFF, RING_L_GAP[0] - 2, x), bp(294, -6, 204 * s)]        # left: from the ring's lower end, under the hose guide
    return top + [bp(298 if s > 0 else 300, -28 if s > 0 else -30, 202 * s), bp(332, -38, 196 * s),
            (x - 16 * s, 362, 150), (169 * s, 372, 44), (166 * s, 368, -6)]      # down the rear post close enough to lie on its pad


def side_bone(s):
    """From the lip's corner out past the end of the 360, flush with its fans, and down to the skeleton's neck."""
    return [bp(LIP_U, FACE_N, 190 * s), bp(LIP_U + 4, FACE_N, 206 * s), bp(240, FACE_N + 1, 209 * s), bp(300, FACE_N - 2, 208 * s),
            bp(301, 126, 205 * s), bp(298, 116, 190 * s)]


def bone(r_a, r_mid, r_b):
    """Radius profile of a bone: thick at both joints, slim in the middle."""
    def prof(t):
        w = (2 * t - 1) ** 2
        end = r_a if t < 0.5 else r_b
        return r_mid + (end - r_mid) * w
    return prof


# ---------------------------------------------------------------------------
# Members: every tube of the layer as data (control points, radius profile, blend)
# ---------------------------------------------------------------------------
def bone_members():
    """The bones. Returns (members, named centre lines for the stubs to tie to)."""
    out, lines = [], {}

    def add(name, ctrl, prof, k=K):
        out.append(("tube", ctrl, prof, k))
        lines[name] = sc.spline(ctrl, step=6.0)

    add("lip", LIP_BONE, bone(*BONE_R["lip"]))
    add("card", CARD_BONE, bone(*BONE_R["card"]))
    add("brow", BROW, bone(*BONE_R["brow"]))
    for s, tag in ((1, "R"), (-1, "L")):
        add("ring_" + tag, ring(s), BONE_R["ring"])
        add("front_" + tag, front_sweep(s), bone(*BONE_R["front"]))
        add("rear_" + tag, rear_sweep(s), bone(*BONE_R["rear"]))
        add("side_" + tag, side_bone(s), bone(*BONE_R["side"]))
        add("base_" + tag, BASE[s], BONE_R["base"])
        for p, r in ((front_sweep(s)[0], 13), (rear_sweep(s)[-1], 13), (bp(LIP_U, FACE_N, 190 * s), 10)):
            out.append(("ball", p, r, K))
    # Left ring: its upper front corner hangs from the end of the front sweep. The CPU hoses cross between the ring's top and the
    # side bone at u 141 to 170, so no film thread can hold the ring there; this tie passes in front of them, at u 114 to 118.
    (u0, _u1), (_n0, n1) = hw.FAN_SIDE_U, hw.FAN_SIDE_N
    corner = bp(u0 - RING_OFF + 4, n1 + RING_OFF - 5, RING_X[-1])
    end = np.array(front_sweep(-1)[-1], dtype=float)
    mid = (np.array(corner, dtype=float) + end) / 2
    add("ring_tie_L", [corner, tuple(mid), tuple(end)], bone(*RING_TIE))
    # Its upper far corner, next to the ring's open end, hangs from the lower end of the side bone: the span from the first tie to the
    # first film thread (u 186) is 72 mm and a push on the open end bent the ring's top there.
    far = np.array(bp(_u1 + RING_OFF - 14, n1 + RING_OFF, RING_X[-1]), dtype=float)
    end2 = np.array(side_bone(-1)[-1], dtype=float)
    add("ring_tie_L2", [tuple(far), tuple((far + end2) / 2), tuple(end2)], bone(*RING_TIE))
    return out, lines


def film_members(a_ctrl, b_ctrl, n, seed, r_a=8.0, r_b=8.0, sag=(0.0, 0.0, -1.0), sag_mm=10.0, links=3):
    """A film of n strands between bone A and bone B, like a viscous liquid being stretched."""
    rng = np.random.default_rng(seed)
    A, Bc = sc.spline(a_ctrl, step=4.0), sc.spline(b_ctrl, step=4.0)
    out = [("tube", a_ctrl, r_a, sc.SMOOTH), ("tube", b_ctrl, r_b, sc.SMOOTH)]
    ta = np.clip(np.linspace(0.04, 0.96, n) + rng.normal(0, 0.035, n), 0.02, 0.98)
    tb = np.clip(ta + rng.normal(0, 0.11, n), 0.02, 0.98)
    sag = np.array(sag, dtype=float)
    for i in range(n):
        p0 = A[int(ta[i] * (len(A) - 1))]
        p1 = Bc[int(tb[i] * (len(Bc) - 1))]
        along = (p1 - p0) / np.linalg.norm(p1 - p0)
        jitter = rng.normal(0, 5.0, 3)
        jitter -= along * (jitter @ along)
        mid = (p0 + p1) / 2 + sag * rng.uniform(0.3, 1.0) * sag_mm + jitter
        r_end0, r_end1, r_mid = rng.uniform(*STRAND_R_END), rng.uniform(*STRAND_R_END), rng.uniform(*STRAND_R_MID)
        r_mid = max(r_mid, float(np.linalg.norm(p1 - p0)) / STRAND_SLENDER)
        r_end0, r_end1 = max(r_end0, r_mid + 1.5), max(r_end1, r_mid + 1.5)
        out.append(("tube", [p0, mid, p1], bone(r_end0, r_mid, r_end1), 10.0))
    for _ in range(links):                               # a few cross-threads between neighbours
        i = int(rng.integers(0, n - 1))
        f0, f1 = rng.uniform(0.25, 0.75), rng.uniform(0.25, 0.75)
        q0 = A[int(ta[i] * (len(A) - 1))] * (1 - f0) + Bc[int(tb[i] * (len(Bc) - 1))] * f0
        q1 = A[int(ta[i + 1] * (len(A) - 1))] * (1 - f1) + Bc[int(tb[i + 1] * (len(Bc) - 1))] * f1
        out.append(("tube", [q0, (q0 + q1) / 2 + sag * 3.0, q1], bone(LINK_R[0], LINK_R[1], LINK_R[0]), 7.0))
    return out


def film_list():
    out = []
    lip_l = [bp(LIP_U, FACE_N, -190), bp(LIP_U - 1, FACE_N + 1, -60), bp(LIP_U - 1, FACE_N + 1, 28)]
    lip_r = [bp(LIP_U - 1, FACE_N + 1, 44), bp(LIP_U - 1, FACE_N + 1, 110), bp(LIP_U, FACE_N, 190)]
    # The gap between the card's outer edge and the 360's lower edge, at the level the fans set.
    # On the left the CPU hoses (450 mm) run below that surface, at n 131 and 140: the threads pass over them, as on the right.
    # (With the 500 mm hoses the run lay in the surface and the threads dipped 20 mm underneath it.)
    cu, cn = CARD_BONE_U, CARD_BONE_N
    out.append(film_members([bp(cu, cn, -SWEEP_X), bp(cu + 1, cn + 1, -60), bp(cu + 1, cn + 1, 28)], lip_l,
                            8, seed=3, r_a=6.0, r_b=6.0, sag=(0.0, 0.707, -0.707), sag_mm=4, links=3))
    out.append(film_members([bp(cu + 1, cn + 1, 44), bp(cu + 1, cn + 1, 100), bp(cu, cn, SWEEP_X)], lip_r,
                            9, seed=8, r_a=6.0, r_b=6.0, sag=(0.0, 0.707, -0.707), sag_mm=4, links=4))
    # a sparse veil across the open front, from the sill's upper edge (behind the light line) up to the brow, well below the card
    ry, rz = SILL_RIDGE
    out.append(film_members([(-135, ry + 1, rz + 5), (0, ry + 1, rz + 6), (135, ry + 1, rz + 5)], BROW, 7, seed=41,
                            r_a=5.0, r_b=6.0, sag=(0.0, 1.0, 0.0), sag_mm=5, links=2))
    for s, dense in ((-1, True), (1, True)):             # the right side was sparser in the first sketch; its fan ring then hung on too few strands
        (u0, u1), (n0, n1) = hw.FAN_SIDE_U, hw.FAN_SIDE_N
        x = RING_X[s]
        # round each side fan the threads run out to the bones that surround it
        a, b, c = u0 - RING_OFF, u1 + RING_OFF, n0 - RING_OFF
        top = n1 + RING_TOP[s]
        near = [bp(a, RING_R_FEET[0] + 2, x), bp(a, (RING_R_FEET[0] + n1) / 2, x), bp(a, n1 - 4, x)] if s > 0 else \
            [bp(a, n0 + 10, x), bp(a, 28, x), bp(a, n1 - 10, x)]
        out.append(film_members(near, front_sweep(s)[1:4], 6 if dense else 4, seed=50 + s,
                                r_a=5.0, r_b=7.0, sag=(0.4 * s, 0.0, 0.0), sag_mm=8, links=2))
        if s < 0:                                           # under the right fan the hoses run where this film would hang
            out.append(film_members([bp(u0 + 12, c, x), bp(190, c - 1, x), bp(u1 - 12, c, x)], BASE[s][:4],
                                    8 if dense else 5, seed=60 + s, r_a=5.0, r_b=6.5, sag=(0.4 * s, 0.0, 0.0), sag_mm=10))
        # Left: the CPU hoses cross between the ring's top and the side bone at u 141 to 170, so the threads start beyond them.
        ua = u0 + 12 if s > 0 else TOP_FILM_L_U0
        out.append(film_members([bp(ua, top, x), bp((ua + u1 - 12) / 2, top + 1, x), bp(u1 - 12, top, x)],
                                side_bone(s)[:3], 6 if dense else 4, seed=70 + s, r_a=5.0, r_b=5.5,
                                sag=(0.5 * s, 0.0, 0.0), sag_mm=6, links=2))
        # the rear window over the PSU's side
        out.append(film_members(BASE[s][2:], rear_sweep(s)[2:6], 9 if dense else 5, seed=80 + s, r_a=6.5, r_b=6.5,
                                sag=(0.4 * s, 0.0, 0.0), sag_mm=9))
    return out


# ---------------------------------------------------------------------------
# Fixings: pads on skeleton faces. Their places are hardware.ORGANIC_PADS (name -> part, centre on the part's outer face, side), the
# single source: the skeleton cuts an M3 insert pilot at each. Here is only what ties a pad to its bone: the bone's name (None takes the nearest).
# A pad also keeps clear of every other part, the hardware (PLA_GAP from the card and the PSU) and the hoses, and has a free line for the driver;
# place_anchors fails if a pad of the table does not. (The right rib's upper front arm cannot take one: it is 2 mm from the card. Tried and
# dropped: the visor arms, whose outward face is a 10 mm edge, and the neck's lower half, which hoses, the 420 and the rib close in.)
# ---------------------------------------------------------------------------
BONE_OF = {"front_foot": None, "sill_end": "front", "base_mid": "base", "rear_foot": "rear", "rear_post": "rear", "neck_top": "side"}
PAD_PILOT_TOL = 0.01                       # mm: a pad's screw axis and its pilot's axis coincide within this
PAD_FACE_TOL = 0.05                        # mm: a pad's centre is on its part's face within this
PAD_FACE_PROBE = 3.0                       # mm: where the face is read, off the pilot's axis


def face_hit(solid, y, z, s):
    """X of the part's outer face at (y, z), seen from outside on side s; None if the ray misses."""
    import cadquery as cq
    bb = solid.BoundingBox()
    xs = np.arange(bb.xmax + 0.5, bb.xmin - 0.5, -0.5) if s > 0 else np.arange(bb.xmin - 0.5, bb.xmax + 0.5, 0.5)
    prev = None
    for x in xs:
        if solid.isInside(cq.Vector(float(x), float(y), float(z))):
            if prev is None:
                return None
            lo, hi = (x, prev) if s > 0 else (prev, x)          # refine the face between the last miss and the first hit
            for _ in range(12):
                mid = (lo + hi) / 2
                inside = solid.isInside(cq.Vector(float(mid), float(y), float(z)))
                if (s > 0) == inside:
                    lo = mid
                else:
                    hi = mid
            return (lo + hi) / 2
        prev = x
    return None


def is_pilot_of(h, q, s):
    """True if the hole `h` is the M3 insert pilot of a pad centred at q on a face whose outward normal is (s, 0, 0): its mouth at q, its axis along -s X."""
    d = np.array(h.d)
    return (h.kind == "M3" and h.pilot and np.linalg.norm(d - np.array([-float(s), 0.0, 0.0])) < 1e-6
            and np.linalg.norm(np.array(h.point(frame_v0.OVERSHOOT)) - np.array(q, dtype=float)) < PAD_PILOT_TOL)


def pad_fits(part, q, s):
    """None if a pad at q on the part's outer face fits, else the reason. The pad's own pilot is not a hole too close to it; every other hole is."""
    import cadquery as cq
    depth = hw.M3_PILOT_DEPTH
    for h in (0.5, depth):
        for a in np.linspace(0, 2 * math.pi, 12, endpoint=False):
            for r in ((hw.M3_PILOT_D / 2 + PAD_SEAT,) if h < 1 else (hw.M3_PILOT_D / 2 + hw.M3_MIN_WALL,)):
                pt = cq.Vector(q[0] - s * h, q[1] + r * math.cos(a), q[2] + r * math.sin(a))
                if not part.solid.isInside(pt):
                    return "less than 4 mm of flat face round the screw" if h < 1 else "no material round the insert at its depth"
    axis0, axis1 = np.array(q), np.array(q) - np.array([s * depth, 0.0, 0.0])
    for h in part.holes:
        if is_pilot_of(h, q, s):
            continue
        need = h.r + hw.M3_PILOT_D / 2 + PAD_HOLE_WALL
        for t in np.arange(0.0, h.length + 0.5, 1.0):
            c = np.array(h.point(float(t)))
            w = np.clip((c - axis0) @ (axis1 - axis0) / ((axis1 - axis0) @ (axis1 - axis0)), 0.0, 1.0)
            if np.linalg.norm(c - (axis0 + w * (axis1 - axis0))) < need:
                return f"{need - np.linalg.norm(c - (axis0 + w * (axis1 - axis0))):.1f} mm too close to the part's {h.kind} hole"
    return None


def pad_clear(part, q, s, parts, hware):
    """None if a pad at q keeps its distances from the other parts, the hardware and the hoses, else the reason."""
    import cadquery as cq
    pad = cq.Solid.makeCylinder(PAD_R, PAD_H, cq.Vector(*map(float, q)), cq.Vector(float(s), 0.0, 0.0))
    for p in parts:
        if p is not part and p.solid.distance(pad) < 1.0:
            return f"less than 1 mm from {p.name}"
    for k, solid in hware.items():
        need = 5.0 if k in hw.HOSES else PLA_GAP if k in ("gpu", "psu") else GAP_HW
        if k in hw.KEEP_OUT and k not in hw.HOSES:
            continue
        if solid.distance(pad) < need:
            return f"less than {need:g} mm from {k}"
    return None


def driver_blocked(q, s, lines):
    """None if the screwdriver has a free line to the pad, else the bone in its way."""
    q, nrm = np.array(q), np.array([float(s), 0.0, 0.0])
    for name, pts in lines.items():
        v = pts - q
        h = v @ nrm
        rad = np.linalg.norm(v - np.outer(h, nrm), axis=1)
        if ((h > 2 * KNOT_R - 4) & (h < HEAD_REACH) & (rad < DRIVER_FREE)).any():
            return f"the bone {name} crosses the driver's path"
    return None


def pad_pilot_failures(anchors, parts):
    """Failure lines of the check "every pad sits on an M3 pilot": the pad's screw axis coincides within PAD_PILOT_TOL with an M3 insert pilot of
    its part (mouth on the pad's centre, axis into the part), and the part's face is at the pad's centre within PAD_FACE_TOL."""
    by_name = {p.name: p for p in parts}
    out = []
    for a in anchors:
        part, q, s = by_name.get(a["part"]), a["q"], int(round(a["n"][0]))
        if part is None:
            out.append(f"{a['name']}: no part {a['part']}")
            continue
        if not any(is_pilot_of(h, q, s) for h in part.holes):
            near = min((np.linalg.norm(np.array(h.point(frame_v0.OVERSHOOT)) - np.array(q)) for h in part.holes if h.kind == "M3" and h.pilot), default=float("nan"))
            out.append(f"{a['name']}: the screw axis at ({q[0]:.2f}, {q[1]:.2f}, {q[2]:.2f}) along X lies on no M3 pilot of {part.name} within {PAD_PILOT_TOL:g} mm"
                       f" (the nearest M3 pilot mouth is {near:.2f} mm away)")
        # the face is read beside the bore (the pilot is empty on the axis): 3 mm off the axis, in four directions, between the bore (r 2) and the insert's wall ring
        xs = [face_hit(part.solid, q[1] + dy, q[2] + dz, s) for dy, dz in ((PAD_FACE_PROBE, 0.0), (-PAD_FACE_PROBE, 0.0), (0.0, PAD_FACE_PROBE), (0.0, -PAD_FACE_PROBE))]
        if any(x is None or abs(x - q[0]) > PAD_FACE_TOL for x in xs):
            out.append(f"{a['name']}: the pad's centre X {q[0]:.2f} is not on {part.name}'s face (the face beside the bore is at X "
                       + ", ".join("none" if x is None else f"{x:.2f}" for x in xs) + ")")
    return out


def place_anchors(parts, lines, hware, pads=None):
    """The pads of hardware.ORGANIC_PADS, each checked to fit its part, with the bone point its stub ties to. Fails if one does not fit."""
    pads = hw.ORGANIC_PADS if pads is None else pads
    by_name = {p.name: p for p in parts}
    out = []
    for name, (pname, q, s) in pads.items():
        tag = name[-1]
        kind = name[:-2]
        want = BONE_OF[kind]
        part = by_name[pname]
        q, nrm = np.array(q, dtype=float), np.array([float(s), 0.0, 0.0])
        why = pad_fits(part, q, s) or pad_clear(part, q, s, parts, hware) or driver_blocked(q, s, lines)
        assert why is None, f"pad {name} on {part.name} at {tuple(q)}: {why}"
        best = None
        for bname, pts in lines.items():
            if want is not None and bname != f"{want}_{tag}":
                continue
            if not bname.endswith("_" + tag) and bname not in ("lip", "card", "brow"):
                continue
            v = pts - (q + nrm * PAD_H)
            dist = np.linalg.norm(v, axis=1)
            cosang = (v @ nrm) / np.maximum(dist, 1e-6)
            ok = (dist > 10.0) & (cosang < math.cos(math.radians(STUB_CONE_DEG)))
            if ok.any():
                i = int(np.argmin(np.where(ok, dist, 1e9)))
                if best is None or dist[i] < best[0]:
                    best = (float(dist[i]), bname, pts[i])
        assert best is not None, f"pad {name}: no bone to tie to"
        out.append(dict(name=name, part=part.name, q=q, n=nrm, bone=best[1], tie=best[2], stub_len=best[0]))
    return out


# ---------------------------------------------------------------------------
# The field
# ---------------------------------------------------------------------------
class Field:
    """One signed-distance grid for the whole layer. Every operation works on the block of the grid it can reach."""

    def __init__(self, vox=VOX):
        self.vox = vox
        self.xs = np.arange(-sc.X_LIM, sc.X_LIM + vox, vox, dtype=np.float32)
        self.ys = np.arange(sc.Y0, sc.Y1 + vox, vox, dtype=np.float32)
        self.zs = np.arange(sc.Z0, sc.Z1 + vox, vox, dtype=np.float32)
        self.d = np.full((len(self.xs), len(self.ys), len(self.zs)), 1e9, dtype=np.float32)

    def block(self, lo, hi):
        sl = []
        for axis, c in enumerate((self.xs, self.ys, self.zs)):
            i0 = max(int(math.floor((lo[axis] - c[0]) / self.vox)), 0)
            i1 = min(int(math.ceil((hi[axis] - c[0]) / self.vox)) + 1, len(c))
            sl.append(slice(i0, max(i1, i0)))
        sl = tuple(sl)
        G = np.meshgrid(self.xs[sl[0]], self.ys[sl[1]], self.zs[sl[2]], indexing="ij")
        return sl, G

    def add(self, member):
        kind = member[0]
        if kind == "tube":
            _, ctrl, prof, k = member
            pts = sc.spline(ctrl)
            rmax = max(prof(t) for t in np.linspace(0, 1, 21)) if callable(prof) else float(prof)
            pad = rmax + k + 2 * self.vox
            sl, G = self.block(pts.min(axis=0) - pad, pts.max(axis=0) + pad)
            self.d[sl] = sc.smin(self.d[sl], sc.tube(G, ctrl, prof), k)
        else:
            _, p, r, k = member
            pad = r + k + 2 * self.vox
            sl, (X, Y, Z) = self.block(np.array(p) - pad, np.array(p) + pad)
            self.d[sl] = sc.smin(self.d[sl], np.sqrt((X - p[0]) ** 2 + (Y - p[1]) ** 2 + (Z - p[2]) ** 2) - r, k)

    def carve_world_box(self, b, gap):
        sl, G = self.block((b[0] - gap - 2, b[2] - gap - 2, b[4] - gap - 2), (b[1] + gap + 2, b[3] + gap + 2, b[5] + gap + 2))
        self.d[sl] = np.maximum(self.d[sl], gap - sc.box_world(G, b))

    def carve_bs_box(self, b, gap):
        corners = np.array([hw.bp(v, u, n) for v in b[:2] for u in b[2:4] for n in b[4:]])
        sl, G = self.block(corners.min(axis=0) - gap - 2, corners.max(axis=0) + gap + 2)
        self.d[sl] = np.maximum(self.d[sl], gap - sc.box_world(sc.to_bs(G), b))

    def carve_polyline(self, pts, r):
        pts = np.asarray(pts, dtype=float)
        sl, (X, Y, Z) = self.block(pts.min(axis=0) - r - 2, pts.max(axis=0) + r + 2)
        dh = np.full(X.shape, 1e9, dtype=np.float32)
        for a in pts:
            dh = np.minimum(dh, (X - a[0]) ** 2 + (Y - a[1]) ** 2 + (Z - a[2]) ** 2)
        self.d[sl] = np.maximum(self.d[sl], r - np.sqrt(dh))

    def cylinder(self, q, n, r, h0, h1):
        """(block, signed distance) of a capped cylinder: axis from q + h0 n to q + h1 n."""
        q, n = np.asarray(q, dtype=float), np.asarray(n, dtype=float)
        ends = np.array([q + h0 * n, q + h1 * n])
        sl, (X, Y, Z) = self.block(ends.min(axis=0) - r - 2, ends.max(axis=0) + r + 2)
        vx, vy, vz = X - q[0], Y - q[1], Z - q[2]
        h = vx * n[0] + vy * n[1] + vz * n[2]
        rad = np.sqrt(np.maximum(vx * vx + vy * vy + vz * vz - h * h, 0.0))
        return sl, np.maximum(np.maximum(rad - r, h0 - h), h - h1)


def skeleton_distance(F, parts):
    """Distance from every grid point to the skeleton (0 inside it), from a voxelisation of the parts."""
    import vtk
    from vtk.util import numpy_support
    occ = np.zeros(F.d.shape, dtype=bool)
    for p in parts:
        verts, tris = p.solid.tessellate(0.3)
        pd = vtk.vtkPolyData()
        vp = vtk.vtkPoints()
        vp.SetData(numpy_support.numpy_to_vtk(np.array([(v.x, v.y, v.z) for v in verts], dtype=np.float64), deep=True))
        pd.SetPoints(vp)
        cells = vtk.vtkCellArray()
        for t in tris:
            cells.InsertNextCell(3, t)
        pd.SetPolys(cells)
        bb = p.solid.BoundingBox()
        sl, _ = F.block((bb.xmin - 2, bb.ymin - 2, bb.zmin - 2), (bb.xmax + 2, bb.ymax + 2, bb.zmax + 2))
        ext = [sl[0].start, sl[0].stop - 1, sl[1].start, sl[1].stop - 1, sl[2].start, sl[2].stop - 1]
        st = vtk.vtkPolyDataToImageStencil()
        st.SetInputData(pd)
        st.SetOutputOrigin(float(F.xs[0]), float(F.ys[0]), float(F.zs[0]))
        st.SetOutputSpacing(F.vox, F.vox, F.vox)
        st.SetOutputWholeExtent(*ext)
        st.Update()
        conv = vtk.vtkImageStencilToImage()
        conv.SetInputConnection(st.GetOutputPort())
        conv.SetInsideValue(1)
        conv.SetOutsideValue(0)
        conv.SetOutputScalarTypeToUnsignedChar()
        conv.Update()
        img = conv.GetOutput()
        arr = numpy_support.vtk_to_numpy(img.GetPointData().GetScalars())
        shape = (sl[0].stop - sl[0].start, sl[1].stop - sl[1].start, sl[2].stop - sl[2].start)
        occ[sl] |= arr.reshape(shape, order="F").astype(bool)
    return ndimage.distance_transform_edt(~occ, sampling=F.vox).astype(np.float32), float(occ.sum()) * F.vox ** 3 / 1000.0


def build(parts, hware, vox=VOX):
    """The whole layer. Returns the field, the anchors and the numbers for the report."""
    F = Field(vox)
    bones_m, lines = bone_members()
    anchors = place_anchors(parts, lines, hware)
    members = list(bones_m)
    for fm in film_list():
        members += fm
    for a in anchors:
        members.append(("ball", tuple(a["q"] + a["n"] * (KNOT_R - 4.0)), KNOT_R, 8.0))
        members.append(("tube", [a["q"] + a["n"] * (PAD_H * 0.6), (a["q"] + a["n"] * PAD_H + a["tie"]) / 2 + a["n"] * 3.0, a["tie"]], bone(*STUB), 8.0))
    for m in members:
        F.add(m)
    # carve back from everything that is not the layer
    for b in (hw.RAD360_BS, hw.RAD420_ENV_BS, hw.BOARD_BS):
        F.carve_bs_box(b, GAP_HW)
    F.carve_bs_box(hw.GPU_BS, PLA_GAP)
    F.carve_world_box(hw.PSU_W, PLA_GAP)
    for name in hw.FAN_SIDE_NAMES:
        F.carve_bs_box(hw.fan_side_bs(name), GAP_HW)
    for b in (hw.DIMMS_BS, hw.IO_ZONE_BS, hw.ATX24_BS, hw.EPS_BS):
        F.carve_bs_box(b, GAP_KEEP)
    for name, (pair, spec) in hoses.routes().items():
        for h in pair:
            F.carve_polyline(h["pts"][::4], spec["r"] + GAP_HW + 1.0)
    bb = (-frame_v0.SILL_HALF_X, frame_v0.SILL_HALF_X, min(y for y, _ in SILL["pts"]), max(y for y, _ in SILL["pts"]),
          min(z for _, z in SILL["pts"]), max(z for _, z in SILL["pts"]))
    sl, G = F.block((bb[0] - 6, bb[2] - 6, bb[4] - 6), (bb[1] + 6, bb[3] + 6, bb[5] + 6))
    F.d[sl] = np.maximum(F.d[sl], SILL_GAP - sill_sdf(G))
    skel, skel_cm3 = skeleton_distance(F, parts)
    np.maximum(F.d, GAP_SKEL - skel, out=F.d)
    np.maximum(F.d, -(F.zs + 15.0)[None, None, :], out=F.d)                  # desk
    np.maximum(F.d, -F.ys[None, :, None], out=F.d)                           # front plane
    np.maximum(F.d, (np.abs(F.xs) - hw.ENVELOPE_X)[:, None, None], out=F.d)  # the radiators' span
    # carving leaves thin slivers where a strand grazes a keep-out: remove what is thinner than MIN_THICK (a morphological opening)
    solid = F.d < 0
    core = ndimage.distance_transform_edt(solid, sampling=F.vox) > MIN_THICK / 2
    opened = ndimage.distance_transform_edt(~core, sampling=F.vox) <= MIN_THICK / 2
    thin = solid & ~opened
    F.d[thin] = 0.6 * F.vox
    thin_cm3 = float(thin.sum()) * F.vox ** 3 / 1000.0
    # pads sit on the skeleton, so they come after the carving; then the screw and its driver channel
    for a in anchors:
        sl, cyl = F.cylinder(a["q"], a["n"], PAD_R, 0.0, PAD_H)
        F.d[sl] = sc.smin(F.d[sl], cyl, 3.0)
    for a in anchors:
        sl, cyl = F.cylinder(a["q"], a["n"], SCREW_R, -1.0, PAD_H + 0.5)
        F.d[sl] = np.maximum(F.d[sl], -cyl)
        sl, cyl = F.cylinder(a["q"], a["n"], HEAD_R, PAD_H, PAD_H + HEAD_REACH)
        F.d[sl] = np.maximum(F.d[sl], -cyl)
    lab, n = ndimage.label(F.d < 0)
    sizes = ndimage.sum(F.d < 0, lab, index=np.arange(1, n + 1)) * F.vox ** 3 / 1000.0
    crumbs = [i + 1 for i in range(n) if sizes[i] < CRUMB_CM3]
    if crumbs:
        F.d[np.isin(lab, crumbs)] = F.vox
    return F, anchors, dict(skeleton_cm3=skel_cm3, members=len(members), crumbs=len(crumbs), crumb_cm3=float(sizes[[i - 1 for i in crumbs]].sum()) if crumbs else 0.0, thin_cm3=thin_cm3, lines=lines)


def bitten(F, lines, parts, hware):
    """Where the clearances cut into a bone: runs of its centre line that are no longer inside the layer, and what is nearest."""
    import cadquery as cq
    out = []
    solid = F.d < 0
    for name, pts in lines.items():
        idx = [tuple(int(round((c - g[0]) / F.vox)) for c, g in zip(q, (F.xs, F.ys, F.zs))) for q in pts]
        gone = [not (0 <= i[0] < solid.shape[0] and 0 <= i[1] < solid.shape[1] and 0 <= i[2] < solid.shape[2] and solid[i]) for i in idx]
        k = 0
        while k < len(pts):
            if not gone[k]:
                k += 1
                continue
            j = k
            while j + 1 < len(pts) and gone[j + 1]:
                j += 1
            mid = pts[(k + j) // 2]
            length = float(np.linalg.norm(np.diff(pts[max(k - 1, 0):min(j + 2, len(pts))], axis=0), axis=1).sum())
            v = cq.Vertex.makeVertex(*map(float, mid))
            cands = [(p.solid.distance(v), p.name) for p in parts] + [(s_.distance(v), "hw:" + n_) for n_, s_ in hware.items() if n_ not in hw.KEEP_OUT or n_ in hw.HOSES]
            dist, who = min(cands)
            out.append((name, length, mid, who, dist))
            k = j + 1
    return out


def check(F, anchors, parts, hware, lines):
    """Checks of the built layer. Returns (lines for the report, failures)."""
    import cadquery as cq
    out, fails = [], []
    solid = F.d < 0
    lab, n = ndimage.label(solid)
    sizes = ndimage.sum(solid, lab, index=np.arange(1, n + 1)) * F.vox ** 3 / 1000.0
    order = np.argsort(sizes)[::-1]
    main = int(order[0]) + 1
    out.append(f"Объём слоя {sizes.sum():.0f} см³, {sizes.sum() * PLA_RHO:.0f} г сплошного PLA; связных кусков {n}: "
               + ", ".join(f"{sizes[i]:.1f}" for i in order[:8]) + " см³" + (" ..." if n > 8 else ""))
    if n > 1:
        loose = []
        for i in order[1:]:
            c = ndimage.center_of_mass(lab == (i + 1))
            loose.append(f"{sizes[i]:.1f} см³ у X {F.xs[int(c[0])]:.0f}, Y {F.ys[int(c[1])]:.0f}, Z {F.zs[int(c[2])]:.0f}")
        fails.append(f"слой не одно тело: отдельных кусков {n - 1}: " + "; ".join(loose[:10]))
    out.append("")
    out.append(f"{'крепление':14} {'деталь каркаса':18} {'центр площадки X, Y, Z':>26} {'до оси пилота':>14} {'кость':>9} {'стойка, мм':>11} {'до железа':>22} {'до шлангов':>11}")
    fails += pad_pilot_failures(anchors, parts)
    by_part = {p.name: p for p in parts}
    hoses_h = {k: v for k, v in hware.items() if k in hw.HOSES}
    solids_h = {k: v for k, v in hware.items() if k not in hw.KEEP_OUT}
    for a in anchors:
        q, nrm = a["q"], a["n"]
        pad = cq.Solid.makeCylinder(PAD_R, PAD_H, cq.Vector(*map(float, q)), cq.Vector(*map(float, nrm)))
        near = min(((pad.distance(s_), k) for k, s_ in solids_h.items()), key=lambda t: t[0])
        hose = min((pad.distance(s_) for s_ in hoses_h.values()))
        i = tuple(int(round((c - g[0]) / F.vox)) for c, g in zip(q + nrm * (PAD_H * 0.5) + np.array([0.0, PAD_R * 0.6, 0.0]), (F.xs, F.ys, F.zs)))
        joined = lab[i] == main
        off = min((float(np.linalg.norm(np.array(h.point(frame_v0.OVERSHOOT)) - q)) for h in by_part[a["part"]].holes if h.kind == "M3" and h.pilot), default=float("nan"))
        out.append(f"{a['name']:14} {a['part']:18} {q[0]:8.1f} {q[1]:8.1f} {q[2]:8.1f} {off:11.2f} мм {a['bone']:>9} {a['stub_len']:11.0f} "
                   f"{near[0]:8.1f} мм {near[1]:>10} {hose:8.1f} мм" + ("" if joined else "   НЕ СОЕДИНЕНО С ТЕЛОМ"))
        hot = PLA_GAP if near[1] in ("gpu", "psu") else GAP_HW
        if near[0] < hot:
            fails.append(f"{a['name']}: площадка в {near[0]:.1f} мм от {near[1]} (нужно {hot:g})")
        if hose < 5.0:
            fails.append(f"{a['name']}: площадка в {hose:.1f} мм от шланга (нужно 5)")
        if not joined:
            fails.append(f"{a['name']}: площадка не соединена с основным телом слоя")
        for p in parts:
            if p.name != a["part"] and p.solid.distance(pad) < 1.0:
                fails.append(f"{a['name']}: площадка в {p.solid.distance(pad):.1f} мм от детали {p.name} (нужно 1)")
    cuts = bitten(F, lines, parts, hware)
    out.append("")
    if cuts:
        out.append("Кости, перерезанные зазорами (длина разрыва по оси кости, середина разрыва, что рядом):")
        for name, length, mid, who, dist in sorted(cuts, key=lambda c: -c[1]):
            out.append(f"  {name:9} {length:5.0f} мм у X {mid[0]:5.0f}, Y {mid[1]:4.0f}, Z {mid[2]:4.0f}: {who} в {dist:.1f} мм")
    else:
        out.append("Ни одна кость не перерезана зазорами.")
    return out, fails


def main():
    t0 = time.time()
    parts, _ = frame_v0.build_frame()
    parts = [p for p in parts]
    hware = hw.build_hardware()
    F, anchors, info = build(parts, hware)
    lines, fails = check(F, anchors, parts, hware, info['lines'])
    b = np.argwhere(F.d < 0)
    lo, hi = b.min(axis=0), b.max(axis=0)
    head = [f"ОРГАНИЧЕСКИЙ СЛОЙ (PLA), одно поле с шагом {F.vox:g} мм, элементов {info['members']}, время {time.time() - t0:.0f} с",
            f"Габарит X {F.xs[lo[0]]:.0f}..{F.xs[hi[0]]:.0f}, Y {F.ys[lo[1]]:.0f}..{F.ys[hi[1]]:.0f}, Z {F.zs[lo[2]]:.0f}..{F.zs[hi[2]]:.0f}",
            f"Правила прочности: нить плёнки в середине Ø{2 * STRAND_R_MID[0]:g}..{2 * STRAND_R_MID[1]:g} мм, у кости Ø{2 * STRAND_R_END[0]:g}..{2 * STRAND_R_END[1]:g}; "
            f"поперечная нить Ø{2 * LINK_R[1]:g}..{2 * LINK_R[0]:g}; стойка крепления Ø{2 * STUB[1]:g}..{2 * STUB[0]:g}",
            f"Крепления: {len(anchors)} площадок Ø{2 * PAD_R:g} x {PAD_H:g} мм на гранях каркаса, винт M3 в резьбовую вставку в ABS "
            f"(места из hw.ORGANIC_PADS; пилот M3 под каждую вырезан в каркасе, ось винта лежит на оси пилота). Зазоры слоя: каркас {GAP_SKEL:g}, запретные зоны платы {GAP_KEEP:g}, железо и шланги {GAP_HW:g}, "
            f"видеокарта и БП {PLA_GAP:g} мм."]
    head.append(f"Крошки после вырезания зазоров (отдельные куски меньше {CRUMB_CM3:g} см³) удалены: {info['crumbs']} шт., {info['crumb_cm3']:.1f} см³. Перемычки тоньше {MIN_THICK:g} мм удалены: {info['thin_cm3']:.1f} см³.")
    text = "\n".join(head + [""] + lines + [""] + (["ПРОВЕРКИ НЕ ПРОЙДЕНЫ:"] + ["  - " + f for f in fails] if fails else ["Все проверки пройдены."]))
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_organic.txt"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)
    out_dir = os.path.join(sc.ROOT, "out", "organic")
    os.makedirs(out_dir, exist_ok=True)
    np.savez_compressed(os.path.join(out_dir, "field.npz"), d=F.d, xs=F.xs, ys=F.ys, zs=F.zs,
                        pads=np.array([np.concatenate([a["q"], a["n"]]) for a in anchors]), names=np.array([a["name"] for a in anchors]))
    vox, sc.VOX = sc.VOX, F.vox
    try:
        shell = sc.mesh(F.xs, F.ys, F.zs, F.d)
    finally:
        sc.VOX = vox
    extras = [(SILL["cuts"]["slit"], (1.0, 0.86, 0.35), 1.0)]           # the light line; the sill itself is a skeleton part
    sc.render("organic", shell, hware, parts, hoses.routes(), extras)
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
