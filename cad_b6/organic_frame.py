#!/usr/bin/env python3
"""Organic outer layer over the plate skeleton: one printable-in-principle solid with its fixings.

Run:  .venv/bin/python cad_b6/organic_frame.py
Out:  previews/b6_shell_organic_<view>.png, cad_b6/report_organic.txt, out/organic/field.npz

The skeleton in frame_v0.py holds every component and is shown in light grey. The organic layer
(dark, PETG, ABS the fallback) is decoration fixed to the skeleton: bones that frame the fans and trace the outer form,
and films of strands pulled across the open spaces. The fans set its level: it lies in the planes of
their outer faces. It carries no component.

Everything is one signed-distance field on one grid, so the layer is one solid:
- members: bones, film strands, and a stub from each fixing pad to the nearest bone;
- carved back from the hardware, the hoses, the board's keep-outs, the sill and the skeleton;
- fixing pads: flat discs that sit on a skeleton face, one M3 screw each into a heat-set insert in the
  ABS part. Where they are is hardware.ORGANIC_PADS; frame_v0.py cuts the insert pilot there.
Checks at the end: every pad sits on its part's face on an M3 pilot of that part, with room for the insert
and away from the part's other holes; pads clear the hardware and the hoses; the layer is one connected
piece that contains every pad. Revision 14b (flanks redrawn for the side fans at |X| 235..260): nothing beyond
|X| 260; both rings whole (closed, not cut or notched by a carve); no material in io_zone, gpu_out_zone or the
prism that continues gpu_out_zone out to the fan's outer face. Those three read the field only (field_checks),
so cad_b6/test_organic.py can damage a saved field and expect them to fail.
Revision 17 (docs/plans/rear-panel.md): the layer is built as named pieces (PIECES), each with its own members, pads and field on the common grid: `main` (the layer of before)
and `rear_panel` (a frame with a film over the opening above psu_bulkhead, held at four corners: two pads on the bulkhead's rear face, one on each rib_B post's rear face).
A later piece is carved back from the earlier ones by GAP_PIECE. field.npz keeps `d` as the union of the pieces and adds `pieces`, `pad_piece`, `d_<piece>` and `heads`.
The checks of the pieces read only those arrays (piece_checks: the arrays' layout, each piece one body holding its pads, the pieces GAP_PIECE apart, a piece other than
`main` fits the bed standing and turned about the vertical, nothing in front of psu_bulkhead's screw heads). cad_b6/organic_manifest.py fingerprints the pieces.
Not done here: the split of `main` into printable pieces, and the strength run (organic_strength.py).
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
LAYER_RHO = 1.27                           # g/cm3, PETG (ABS, the fallback, is 1.04)

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
PAD_R, PAD_H = 8.0, hw.ORGANIC_PAD_H      # pad disc on a skeleton face; its thickness is what the screw clamps, so it is hardware.py's
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
HOT_GAP = 10.0                             # the layer keeps this far from the graphics card and the PSU, which run hot
GAP_PIECE = 3.0                            # revision 17 (docs/plans/rear-panel.md): the layer's pieces are put on separately, so each keeps this far from the others; a later piece is carved back from the earlier ones
CARD_BONE_U, CARD_BONE_N = 118.0, CARD_N + HOT_GAP + 8.0   # a bone over the card's top edge, clear of it
SWEEP_X = 170.0                            # the flank sweeps pass this far out, clear of the card's ends
NEAR_FILM_N0 = 50.0                        # right fan: the film from the ring's near side to the front sweep starts at this n, above the card's hoses
UNDER_FILM = {-1: False, 1: False}         # revision 14b: no film from a ring's bottom to the base. Left: the hand's way up to the board's connectors passes under the fan (zone_access.py);
                                           # right: the card's hoses run under the fan
TOP_FILM_L_U0 = 186.0                      # left fan, film from the ring's top to the side bone: first thread past the CPU hoses (hose b at u 170 + 6.2 + GAP_HW + a thread's radius)
SILL = frame_v0.sill_geometry()            # the skeleton's front sill: section (Y, Z), the light slit's cutter
SILL_RIDGE = SILL["pts"][2]                # (Y, Z) of its upper edge, above the light line
SILL_GAP = 2.5                             # the organic layer keeps this far from the sill
BROW = [(-158, 8, 150), (0, 6, 157), (158, 8, 150)]        # bone across the front, well below the card
LIP_BONE = [bp(LIP_U, FACE_N, -190), bp(LIP_U - 1, FACE_N + 1, -60), bp(LIP_U - 1, FACE_N + 1, 60),
            bp(LIP_U, FACE_N, 190)]
CARD_BONE = [bp(CARD_BONE_U, CARD_BONE_N, -SWEEP_X), bp(CARD_BONE_U + 1, CARD_BONE_N + 1, 0),
             bp(CARD_BONE_U, CARD_BONE_N, SWEEP_X)]
RING_X = {1: sum(hw.FAN_SIDE_X["fan_side_right"]) / 2, -1: sum(hw.FAN_SIDE_X["fan_side_left"]) / 2}    # both rings in their fan's mid-plane
REAR_BEND_X = 176.5                        # the layer's own: the rear sweep's bend above the rear post, X, clear of the post's driver path (|X| 174..203 round Y 374, Z 50)
REAR_FROM_N = -20.0                        # revision 14b: the rear sweep leaves the ring's far side here, below the CPU hoses' run to the 420's ports (n 42 and up on the left)
REAR_MID = (296.0, -36.0, 222.0)           # the layer's own (u, n, |X|): between the ring and the 420's lower edge (n -16), inside the 420's end
REAR_UNDER = (332.0, -38.0, 196.0)         # the layer's own (u, n, |X|): under the 420's core, before the sweep turns down the back
BASE = {s: [(160 * s, 40, -4), (163 * s, 110, -5), (161 * s, 196, -4), (166 * s, 290, -5), (166 * s, 356, -4)]
        for s in (1, -1)}                  # revision 14b, second pass: whole on both sides again, at its height and radius of before the first pass (the first pass opened and lowered it
                                           # for a hand's route under the board that ended below io_zone, which no hand holding a plug uses)
RING_TIE_L3_BASE_Y = 100.0                 # revision 14b, second pass: the left ring's lower front corner is strutted to the base bone here, just behind the front foot's pad (Y 60)


def sill_sdf(G):
    """Signed distance to the front sill's prism (pocket and channel ignored); never more than the true distance outside."""
    X, Y, Z = G
    d = np.abs(X) - frame_v0.SILL_HALF_X
    pts = list(SILL["pts"])
    for (y0, z0), (y1, z1) in zip(pts, pts[1:] + pts[:1]):
        ny, nz = -(z1 - z0), y1 - y0                       # outward normal: the section runs clockwise in (Y, Z)
        d = np.maximum(d, ((Y - y0) * ny + (Z - z0) * nz) / math.hypot(ny, nz))
    return d


RING_R = BONE_R["ring"]
RING_OFF = RING_R + GAP_HW + VOX           # 12: the ring's centre line stands this far from the fan's box, so its surface keeps GAP_HW and one voxel more (the carve does not notch it)
RING_STEP = 5.0                            # control points along the ring, mm
RING_CHECK_STEP = 1.0                      # the ring checks read the field this often along the centre line, mm
RING_MIN_DEPTH = RING_R - VOX              # a whole ring: every point of its centre line lies this deep inside the layer (a notch deeper than one voxel fails)
OUT_PRISM_U1 = 100.0                       # revision 14b: nothing of the layer in front of the card's outputs up to this u (the ring's near side passes above it, its surface at u 101.5)
OUT_PRISM_BS = (hw.x_to_v(-hw.ENVELOPE_FAN_X), hw.GPU_OUT_ZONE_BS[0], hw.GPU_OUT_ZONE_BS[2], OUT_PRISM_U1, *hw.GPU_OUT_ZONE_BS[4:])    # gpu_out_zone continued out to the fan's outer face
OUT_PRISM_GAP = 1.0                        # the carve keeps this far from the prism
EMPTY_BOXES = {"io_zone": hw.IO_ZONE_BS, "gpu_out_zone": hw.GPU_OUT_ZONE_BS, "out_prism": OUT_PRISM_BS}     # board-space boxes the layer has no voxel in


def ring_un():
    """(u, n) of a ring's centre line: the fan's frame offset by RING_OFF, straight sides and quarter circles round the corners, closed (it ends past its start)."""
    (u0, u1), (n0, n1) = hw.FAN_SIDE_U, hw.FAN_SIDE_N
    corners = ((u1, n1, 0.0), (u0, n1, 90.0), (u0, n0, 180.0), (u1, n0, 270.0))       # D, C, A, B, anticlockwise in (u, n)
    pts = []
    for cu, cn, a0 in corners:
        k = max(int(math.ceil(RING_OFF * math.pi / 2 / RING_STEP)), 2)
        arc = [(cu + RING_OFF * math.cos(math.radians(a0 + 90.0 * i / k)), cn + RING_OFF * math.sin(math.radians(a0 + 90.0 * i / k))) for i in range(k + 1)]
        if pts:
            p, q = np.array(pts[-1]), np.array(arc[0])
            m = max(int(math.ceil(np.linalg.norm(q - p) / RING_STEP)), 1)
            pts += [tuple(p + (q - p) * j / m) for j in range(1, m)]
        pts += arc
    p, q = np.array(pts[-1]), np.array(pts[0])
    m = max(int(math.ceil(np.linalg.norm(q - p) / RING_STEP)), 1)
    pts += [tuple(p + (q - p) * j / m) for j in range(1, m)]
    return pts + pts[:3]


def ring(s):
    """Bone round a side fan, in the fan's mid-plane: a closed loop RING_OFF outside the fan's box, the same on both sides (revision 14b). The reasons for the old arch on the
    right (the bracket's rail, the card's hoses beside the old fan) and the gap on the left (the CPU hose guide on the neck) are gone since revisions 13 and 14a."""
    return [bp(u, n, RING_X[s]) for u, n in ring_un()]


def front_sweep(s):
    """From the front foot up past the card's edge to the corner of the 360's lip.
    On the left the CPU hoses turn down the flank exactly between the card's edge and that corner, so the sweep stops at the card's edge."""
    pts = [(158 * s, 22, 4), (164 * s, 10, 100), (166 * s, 9, 152), bp(CARD_BONE_U, CARD_BONE_N, SWEEP_X * s)]
    return pts + [bp(LIP_U, FACE_N, 190 * s)] if s > 0 else pts


def rear_sweep(s):
    """From the fan ring's far side, below the CPU hoses' run to the 420's ports, under the 420 and down the back to the rear foot. The same on both sides."""
    return [bp(hw.FAN_SIDE_U[1] + RING_OFF, REAR_FROM_N, RING_X[s]), bp(*REAR_MID[:2], REAR_MID[2] * s), bp(*REAR_UNDER[:2], REAR_UNDER[2] * s),
            (REAR_BEND_X * s, 362, 150), (169 * s, 372, 44), (166 * s, 368, -6)]      # down the rear post close enough to lie on its pad


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
    # side bone at u 141 to 170, so no film thread can hold the ring there; this tie passes in front of them, at u 112 to 118. It also stands in for the film from the
    # ring's near side to the front sweep, which on the left would hang in front of the card's outputs (revision 14b): it stays above n 100.
    (u0, _u1), (_n0, n1) = hw.FAN_SIDE_U, hw.FAN_SIDE_N
    corner = bp(u0 - RING_OFF * math.sqrt(0.5), n1 + RING_OFF * math.sqrt(0.5), RING_X[-1])      # on the ring's arc round the fan's corner C
    end = np.array(front_sweep(-1)[-1], dtype=float)
    mid = (np.array(corner, dtype=float) + end) / 2
    add("ring_tie_L", [corner, tuple(mid), tuple(end)], bone(*RING_TIE))
    # Its upper far corner, next to the ring's open end, hangs from the lower end of the side bone: the span from the first tie to the
    # first film thread (u 186) is 72 mm and a push on the open end bent the ring's top there.
    far = np.array(bp(_u1 + RING_OFF - 14, n1 + RING_OFF, RING_X[-1]), dtype=float)
    end2 = np.array(side_bone(-1)[-1], dtype=float)
    add("ring_tie_L2", [tuple(far), tuple((far + end2) / 2), tuple(end2)], bone(*RING_TIE))
    # Revision 14b, second pass: its lower front corner (fan corner A) hangs from nothing else, and a 30 N push there moved it 9.6 mm (no film on its near side, which would hang in
    # front of the card's outputs, nor under it, which is the hand's way up to the board's connectors). This strut runs from the corner forward and down to the base bone behind
    # the front foot, below the outputs' prism (n stays near -50, the prism starts at n 10) and in front of the hand's way under the fan.
    n0 = hw.FAN_SIDE_N[0]
    low = np.array(bp(u0 - RING_OFF * math.sqrt(0.5), n0 - RING_OFF * math.sqrt(0.5), RING_X[-1]), dtype=float)      # on the ring's arc round the fan's corner A
    line = sc.spline(BASE[-1], step=2.0)
    end3 = line[int(np.argmin(np.abs(line[:, 1] - RING_TIE_L3_BASE_Y)))]
    add("ring_tie_L3", [tuple(low), tuple((low + end3) / 2), tuple(end3)], bone(*RING_TIE))
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
    for s in (-1, 1):
        (u0, u1), (n0, n1) = hw.FAN_SIDE_U, hw.FAN_SIDE_N
        x = RING_X[s]
        # round each side fan the threads run out to the bones that surround it
        a, top = u0 - RING_OFF, n1 + RING_OFF
        if s > 0:
            # from the ring's near side to the front sweep, above the card's hoses (they run along the fan's near side at n 25 and below). Not on the left: there the
            # card's outputs face this side and the film would hang in front of them; ring_tie_L holds that corner instead.
            near = [bp(a, NEAR_FILM_N0, x), bp(a, (NEAR_FILM_N0 + n1) / 2, x), bp(a, n1 - 4, x)]
            out.append(film_members(near, front_sweep(s)[1:4], 6, seed=50 + s, r_a=5.0, r_b=7.0, sag=(0.4 * s, 0.0, 0.0), sag_mm=8, links=2))
        if UNDER_FILM[s]:
            c = n0 - RING_OFF
            out.append(film_members([bp(u0 + 12, c, x), bp(190, c - 1, x), bp(u1 - 12, c, x)], BASE[s][:4],
                                    8, seed=60 + s, r_a=5.0, r_b=6.5, sag=(0.4 * s, 0.0, 0.0), sag_mm=10))
        # Left: the CPU hoses cross between the ring's top and the side bone at u 141 to 170, so the threads start beyond them.
        ua = u0 + 12 if s > 0 else TOP_FILM_L_U0
        out.append(film_members([bp(ua, top, x), bp((ua + u1 - 12) / 2, top + 1, x), bp(u1 - 12, top, x)],
                                side_bone(s)[:3], 6, seed=70 + s, r_a=5.0, r_b=5.5,
                                sag=(0.5 * s, 0.0, 0.0), sag_mm=6, links=2))
        # the rear window over the PSU's side
        out.append(film_members(BASE[s][2:], rear_sweep(s)[1:5], 9, seed=80 + s, r_a=6.5, r_b=6.5,
                                sag=(0.4 * s, 0.0, 0.0), sag_mm=9))
    return out


# ---------------------------------------------------------------------------
# Pieces (revision 17, docs/plans/rear-panel.md). A piece is a name, its members, its pads (the rows of hardware.ORGANIC_PADS that name it) and its own field on the
# common grid. They are built in this order; a later piece is carved back from the earlier ones by GAP_PIECE. The layer of before revision 17 is the piece `main`.
# ---------------------------------------------------------------------------
PIECES = ("main", "rear_panel")

# The rear panel: a frame with a film of strands across the opening above psu_bulkhead, held at four corners (revision 17, second step): two pads on the bulkhead's end
# blocks and two on rib_B's posts, all on rear faces (normal +Y). The numbers are the panel's own, from the fourth sketch (docs/plans/sketches/rear_panel_sketch.py): the frame's centre line stands 131 from X 0, inside the posts'
# inner faces (X 142) by its radius and the gap to the skeleton; the lower bar over the bulkhead's top (Z 92), clear of the sled's top (Z 145, it stands behind the drive's
# body, which ends at Y 357.6); the upper bar behind the posts' rear faces (Y 348) and under the 420's fans.
PANEL_R = 6.5                                                   # the frame's bars
PANEL_CORNER_R = 9.0                                            # a ball on each corner of the frame
PANEL_LOW = [(-131.0, 384.0, 104.0), (0.0, 386.0, 106.0), (131.0, 384.0, 104.0)]
PANEL_TOP = [(-131.0, 360.0, 250.0), (0.0, 362.0, 253.0), (131.0, 360.0, 250.0)]
PANEL_SIDE_BOW = (2.0, 2.0)                                     # the side bars bow this far outward (along X) and back (along +Y) at mid-height
PANEL_FILM = dict(n=9, seed=17, sag=(0.0, 1.0, 0.3), sag_mm=6.0, links=5)
PANEL_LEG = (8.0, 7.0, 8.0)                                     # a leg from each pad to the frame's corner on its side (radius at the pad, mid, the corner)
PANEL_BRACE = (7.5, 7.0, 7.5)                                   # two more from each hip pad to the lower bar: over the bulkhead's top edge the panel is only as thick as the room
PANEL_BRACE_X = (115.0, 100.0)                                  # behind the bulkhead (Y 383 to PANEL_Y_FLAT), so it is made wide there; they meet the bar at these |X| ...
PANEL_BRACE_YZ = (384.0, 105.0)                                 # ... and this (Y, Z)
PANEL_Y_FLAT = 391.5                                            # nothing of the panel behind this plane (10 mm behind the skeleton's rear, Y 381); the knots get a flat rear face here
# Pads that get no automatic stub: their piece declares their legs. Pad kind -> the kinds of leg it gets (panel_legs): `leg_low` to the frame's lower corner on its side
# (bowed 3 mm along the pad's normal), `brace` the two to the lower bar at PANEL_BRACE_X (bowed 2 mm), `leg_top` to the frame's upper corner on its side (bowed 2 mm).
OWN_LEGS = {"panel_hip": ("leg_low", "brace"), "panel_top": ("leg_top",)}


def panel_frame():
    """The rear panel's frame and film. Returns (members, named centre lines, films)."""
    out, lines = [], {}

    def add(name, ctrl, prof, k=K):
        out.append(("tube", ctrl, prof, k))
        lines[name] = sc.spline(ctrl, step=6.0)

    low, top = PANEL_LOW, PANEL_TOP
    bow_x, bow_y = PANEL_SIDE_BOW
    for s, tag, i in ((-1, "L", 0), (1, "R", -1)):
        a, b = low[i], top[i]
        mid = (a[0] + s * bow_x, (a[1] + b[1]) / 2 + bow_y, (a[2] + b[2]) / 2)
        add("panel_side_" + tag, [a, mid, b], PANEL_R)
        out += [("ball", a, PANEL_CORNER_R, K), ("ball", b, PANEL_CORNER_R, K)]
    add("panel_low", low, PANEL_R)
    add("panel_top", top, PANEL_R)
    film = film_members(low, top, PANEL_FILM["n"], seed=PANEL_FILM["seed"], r_a=PANEL_R, r_b=PANEL_R, sag=PANEL_FILM["sag"], sag_mm=PANEL_FILM["sag_mm"], links=PANEL_FILM["links"])
    return out, lines, [film[2:]]               # the film's own two bars are panel_low and panel_top, already drawn above (drawn twice, a bar would swell by a quarter of the blend)


def panel_legs(a):
    """The legs of a rear-panel pad, the kinds OWN_LEGS names for its kind: `leg_low` to the frame's lower corner on its side, `brace` two to the lower bar, `leg_top` to the
    frame's upper corner on its side. Shaped like the stubs (blend 8, bowed along the pad's normal)."""
    q, n = a["q"], a["n"]
    s = 1.0 if q[0] > 0 else -1.0
    kinds = OWN_LEGS[a["name"][:-2]]
    out = []

    def leg(end, prof, bow):
        end = np.array(end, dtype=float)
        out.append(("tube", [q + n * (PAD_H * 0.6), (q + n * PAD_H + end) / 2 + n * bow, end], bone(*prof), 8.0))

    if "leg_low" in kinds:
        leg(PANEL_LOW[-1] if s > 0 else PANEL_LOW[0], PANEL_LEG, 3.0)
    if "brace" in kinds:
        for bx in PANEL_BRACE_X:
            leg((s * bx, *PANEL_BRACE_YZ), PANEL_BRACE, 2.0)
    if "leg_top" in kinds:
        leg(PANEL_TOP[-1] if s > 0 else PANEL_TOP[0], PANEL_LEG, 2.0)
    unknown = set(kinds) - {"leg_low", "brace", "leg_top"}
    assert not unknown and out, f"pad {a['name']}: unknown leg kinds {sorted(unknown)} or no leg"
    return out


# ---------------------------------------------------------------------------
# Fixings: pads on skeleton faces. Their places are hardware.ORGANIC_PADS (name -> part, centre on the part's outer face, side), the
# single source: the skeleton cuts an M3 insert pilot at each. Here is only what ties a pad to its bone: the bone's name (None takes the nearest).
# A pad also keeps clear of every other part, the hardware (HOT_GAP from the card and the PSU) and the hoses, and has a free line for the driver;
# place_anchors fails if a pad of the table does not. (The right rib's upper front arm cannot take one: it is 2 mm from the card. Tried and
# dropped: the visor arms, whose outward face is a 10 mm edge, and the neck's lower half, which hoses, the 420 and the rib close in.)
# ---------------------------------------------------------------------------
BONE_OF = {"front_foot": None, "sill_end": "front", "base_mid": "base", "rear_foot": "rear", "rear_post": "rear", "neck_top": "side"}
PAD_PILOT_TOL = 0.01                       # mm: a pad's screw axis and its pilot's axis coincide within this
PAD_FACE_TOL = 0.05                        # mm: a pad's centre is on its part's face within this
PAD_FACE_PROBE = 3.0                       # mm: where the face is read, off the pilot's axis


def across(n):
    """A unit vector across the normal n: Y with its part along n taken off (Y itself for a pad on an X face, which is how the checks took it before revision 17), or Z where n lies along Y."""
    n = np.asarray(n, dtype=float)
    for a in ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        e = np.array(a) - n * (n @ np.array(a))
        if np.linalg.norm(e) > 0.5:
            return e / np.linalg.norm(e)
    raise ValueError(f"no direction across {tuple(n)}")


def pad_frame(n):
    """(e1, e2): two unit vectors across the pad's normal n and across each other, e1 = across(n)."""
    n = np.asarray(n, dtype=float)
    e1 = across(n)
    return e1, np.cross(n, e1)


def face_hit(solid, p, n):
    """Where the part's face lies on the line through p along the unit vector n, seen from outside (from +n): t such that the face is at p + t n; None if the ray misses."""
    import cadquery as cq
    p, n = np.asarray(p, dtype=float), np.asarray(n, dtype=float)
    bb = frame_v0.exact_bound_box(solid)
    proj = [(np.array([x, y, z]) - p) @ n for x in (bb.xmin, bb.xmax) for y in (bb.ymin, bb.ymax) for z in (bb.zmin, bb.zmax)]
    ts = np.arange(max(proj) + 0.5, min(proj) - 0.5, -0.5)

    def inside(t):
        return solid.isInside(cq.Vector(*map(float, p + t * n)))
    prev = None
    for t in ts:
        if inside(t):
            if prev is None:
                return None
            lo, hi = t, prev                                   # refine the face between the last miss and the first hit
            for _ in range(12):
                mid = (lo + hi) / 2
                if inside(mid):
                    lo = mid
                else:
                    hi = mid
            return (lo + hi) / 2
        prev = t
    return None


def is_pilot_of(h, q, n):
    """True if the hole `h` is the M3 insert pilot of a pad centred at q on a face whose outward normal is n: its mouth at q, its axis along -n."""
    d = np.array(h.d)
    return (h.kind == "M3" and h.pilot and np.linalg.norm(d + np.asarray(n, dtype=float)) < 1e-6
            and np.linalg.norm(np.array(h.point(frame_v0.OVERSHOOT)) - np.array(q, dtype=float)) < PAD_PILOT_TOL)


def pad_fits(part, q, n):
    """None if a pad at q on the part's face with outward normal n fits, else the reason. The pad's own pilot is not a hole too close to it; every other hole is."""
    import cadquery as cq
    q, n = np.asarray(q, dtype=float), np.asarray(n, dtype=float)
    e1, e2 = pad_frame(n)
    depth = hw.M3_PILOT_DEPTH
    for h in (0.5, depth):
        for a in np.linspace(0, 2 * math.pi, 12, endpoint=False):
            for r in ((hw.M3_PILOT_D / 2 + PAD_SEAT,) if h < 1 else (hw.M3_PILOT_D / 2 + hw.M3_MIN_WALL,)):
                pt = q - h * n + r * math.cos(a) * e1 + r * math.sin(a) * e2
                if not part.solid.isInside(cq.Vector(*map(float, pt))):
                    return "less than 4 mm of flat face round the screw" if h < 1 else "no material round the insert at its depth"
    axis0, axis1 = q, q - depth * n
    for h in part.holes:
        if is_pilot_of(h, q, n):
            continue
        need = h.r + hw.M3_PILOT_D / 2 + PAD_HOLE_WALL
        for t in np.arange(0.0, h.length + 0.5, 1.0):
            c = np.array(h.point(float(t)))
            w = np.clip((c - axis0) @ (axis1 - axis0) / ((axis1 - axis0) @ (axis1 - axis0)), 0.0, 1.0)
            if np.linalg.norm(c - (axis0 + w * (axis1 - axis0))) < need:
                return f"{need - np.linalg.norm(c - (axis0 + w * (axis1 - axis0))):.1f} mm too close to the part's {h.kind} hole"
    return None


def pad_clear(part, q, n, parts, hware):
    """None if a pad at q (outward normal n) keeps its distances from the other parts, the hardware and the hoses, else the reason."""
    import cadquery as cq
    pad = cq.Solid.makeCylinder(PAD_R, PAD_H, cq.Vector(*map(float, q)), cq.Vector(*map(float, n)))
    for p in parts:
        if p is not part and p.solid.distance(pad) < 1.0:
            return f"less than 1 mm from {p.name}"
    for k, solid in hware.items():
        need = 5.0 if k in hw.HOSES else HOT_GAP if k in ("gpu", "psu") else GAP_HW
        if k in hw.KEEP_OUT and k not in hw.HOSES:
            continue
        if solid.distance(pad) < need:
            return f"less than {need:g} mm from {k}"
    return None


def driver_blocked(q, n, lines):
    """None if the screwdriver has a free line to the pad (along its normal n), else the bone in its way."""
    q, nrm = np.asarray(q, dtype=float), np.asarray(n, dtype=float)
    for name, pts in lines.items():
        v = pts - q
        h = v @ nrm
        rad = np.linalg.norm(v - np.outer(h, nrm), axis=1)
        if ((h > 2 * KNOT_R - 4) & (h < HEAD_REACH) & (rad < DRIVER_FREE)).any():
            return f"the bone {name} crosses the driver's path"
    return None


def pad_pilot_failures(anchors, parts):
    """Failure lines of the check "every pad sits on an M3 pilot": the pad's screw axis coincides within PAD_PILOT_TOL with an M3 insert pilot of
    its part (mouth on the pad's centre, axis into the part along minus the pad's normal), and the part's face is at the pad's centre within PAD_FACE_TOL."""
    by_name = {p.name: p for p in parts}
    out = []
    for a in anchors:
        part, q, n = by_name.get(a["part"]), np.asarray(a["q"], dtype=float), np.asarray(a["n"], dtype=float)
        if part is None:
            out.append(f"{a['name']}: no part {a['part']}")
            continue
        if not any(is_pilot_of(h, q, n) for h in part.holes):
            near = min((np.linalg.norm(np.array(h.point(frame_v0.OVERSHOOT)) - q) for h in part.holes if h.kind == "M3" and h.pilot), default=float("nan"))
            out.append(f"{a['name']}: the screw axis at ({q[0]:.2f}, {q[1]:.2f}, {q[2]:.2f}) along ({n[0]:g}, {n[1]:g}, {n[2]:g}) lies on no M3 pilot of {part.name} within {PAD_PILOT_TOL:g} mm"
                       f" (the nearest M3 pilot mouth is {near:.2f} mm away)")
        # the face is read beside the bore (the pilot is empty on the axis): 3 mm off the axis, in four directions across the normal, between the bore (r 2) and the insert's wall ring
        e1, e2 = pad_frame(n)
        ts = [face_hit(part.solid, q + du * e1 + dv * e2, n) for du, dv in ((PAD_FACE_PROBE, 0.0), (-PAD_FACE_PROBE, 0.0), (0.0, PAD_FACE_PROBE), (0.0, -PAD_FACE_PROBE))]
        if any(t is None or abs(t) > PAD_FACE_TOL for t in ts):
            out.append(f"{a['name']}: the pad's centre ({q[0]:.2f}, {q[1]:.2f}, {q[2]:.2f}) is not on {part.name}'s face (the face beside the bore is at "
                       + ", ".join("none" if t is None else f"{t:+.2f}" for t in ts) + " mm along the pad's normal from it)")
    return out


def place_anchors(parts, lines, hware, pads=None, driver_lines=None):
    """The pads of hardware.ORGANIC_PADS (or `pads`, rows of the same form), each checked to fit its part, with the bone point its stub ties to. Fails if one does not fit.
    A pad whose kind is in OWN_LEGS gets no automatic stub (tie None): its piece declares its legs. driver_lines: the centre lines the driver's path is tested against (default `lines`)."""
    pads = hw.ORGANIC_PADS if pads is None else pads
    by_name = {p.name: p for p in parts}
    out = []
    for name, (pname, q, nrm, _piece) in pads.items():
        tag = name[-1]
        kind = name[:-2]
        part = by_name[pname]
        q, nrm = np.array(q, dtype=float), np.array(nrm, dtype=float)
        why = pad_fits(part, q, nrm) or pad_clear(part, q, nrm, parts, hware) or driver_blocked(q, nrm, lines if driver_lines is None else driver_lines)
        assert why is None, f"pad {name} on {part.name} at {tuple(q)}: {why}"
        if kind in OWN_LEGS:
            out.append(dict(name=name, part=part.name, q=q, n=nrm, bone="+".join(OWN_LEGS[kind]), tie=None, stub_len=float("nan")))
            continue
        want = BONE_OF[kind]
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


def carve_layer(F, parts, skel):
    """Carve a piece back from everything that is not the layer, in the order build() carved the layer before revision 17. skel: {} on the first call, which fills it with the
    skeleton's distance field (the same grid serves every piece)."""
    for b in (hw.RAD360_BS, hw.RAD420_ENV_BS, hw.BOARD_BS):
        F.carve_bs_box(b, GAP_HW)
    F.carve_bs_box(hw.GPU_BS, HOT_GAP)
    F.carve_world_box(hw.PSU_W, HOT_GAP)
    for name in hw.FAN_SIDE_NAMES:
        F.carve_bs_box(hw.fan_side_bs(name), GAP_HW)
    for b in (hw.DIMMS_BS, hw.IO_ZONE_BS, hw.GPU_OUT_ZONE_BS, hw.ATX24_BS, hw.EPS_BS):
        F.carve_bs_box(b, GAP_KEEP)
    F.carve_bs_box(OUT_PRISM_BS, OUT_PRISM_GAP)                                   # nothing in front of the card's outputs out to the fan's outer face
    for name, (pair, spec) in hoses.routes().items():
        for h in pair:
            F.carve_polyline(h["pts"][::4], spec["r"] + GAP_HW + 1.0)
    bb = (-frame_v0.SILL_HALF_X, frame_v0.SILL_HALF_X, min(y for y, _ in SILL["pts"]), max(y for y, _ in SILL["pts"]),
          min(z for _, z in SILL["pts"]), max(z for _, z in SILL["pts"]))
    sl, G = F.block((bb[0] - 6, bb[2] - 6, bb[4] - 6), (bb[1] + 6, bb[3] + 6, bb[5] + 6))
    F.d[sl] = np.maximum(F.d[sl], SILL_GAP - sill_sdf(G))
    if not skel:
        skel["d"], skel["cm3"] = skeleton_distance(F, parts)
    np.maximum(F.d, GAP_SKEL - skel["d"], out=F.d)
    np.maximum(F.d, -(F.zs + 15.0)[None, None, :], out=F.d)                  # desk
    np.maximum(F.d, -F.ys[None, :, None], out=F.d)                           # front plane
    np.maximum(F.d, (np.abs(F.xs) - hw.ENVELOPE_FAN_X)[:, None, None], out=F.d)  # revision 14b: the fans' outer faces (it was the radiators' span, which cut the rings off)


def carve_panel(F, hware):
    """What the rear panel is carved from besides carve_layer: each body of the drives (hw.DRIVES) and its mirror image (the same room on the right, where no bay is built, so the
    panel stays mirrored) by HOT_GAP, each body's exact box; and the plane PANEL_Y_FLAT."""
    for name in hw.DRIVES:
        for body in hware[name].Solids():
            b = frame_v0.exact_box(body)
            F.carve_world_box(b, HOT_GAP)
            F.carve_world_box((-b[1], -b[0], *b[2:]), HOT_GAP)
    np.maximum(F.d, (F.ys - PANEL_Y_FLAT)[None, :, None], out=F.d)


def finish_piece(F, anchors):
    """After the carving: thin slivers out, the pads, the screw and its driver channel, the crumbs out. Returns (thin cm3, crumbs, crumb cm3)."""
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
    return thin_cm3, len(crumbs), float(sizes[[i - 1 for i in crumbs]].sum()) if crumbs else 0.0


def build(parts, hware, vox=VOX):
    """The whole layer, piece by piece (PIECES). Returns (the union's field, the anchors of every piece in PIECES' order, {piece: its field}, the numbers for the report)."""
    frames = {"main": bone_members() + (film_list(),)}
    if "rear_panel" in PIECES:
        frames["rear_panel"] = panel_frame()
    all_lines = {k: v for _m, lines, _f in frames.values() for k, v in lines.items()}
    skel, fields, anchors, info = {}, {}, [], dict(members=0, crumbs=0, crumb_cm3=0.0, thin_cm3=0.0, lines=all_lines, per_piece={})
    for piece in PIECES:
        bones_m, lines, films = frames[piece]
        pads = {k: v for k, v in hw.ORGANIC_PADS.items() if v[3] == piece}
        own = place_anchors(parts, lines, hware, pads, driver_lines=all_lines)
        members = list(bones_m)
        for fm in films:
            members += fm
        for a in own:
            members.append(("ball", tuple(a["q"] + a["n"] * (KNOT_R - 4.0)), KNOT_R, 8.0))
            if a["tie"] is not None:
                members.append(("tube", [a["q"] + a["n"] * (PAD_H * 0.6), (a["q"] + a["n"] * PAD_H + a["tie"]) / 2 + a["n"] * 3.0, a["tie"]], bone(*STUB), 8.0))
            else:
                members += panel_legs(a)
        F = Field(vox)
        for m in members:
            F.add(m)
        carve_layer(F, parts, skel)
        if piece == "rear_panel":
            carve_panel(F, hware)
        for prev in fields.values():                                            # a later piece keeps GAP_PIECE from the earlier ones
            np.maximum(F.d, GAP_PIECE - prev.d, out=F.d)
        thin_cm3, crumbs, crumb_cm3 = finish_piece(F, own)
        fields[piece] = F
        anchors += own
        info["members"] += len(members)
        info["crumbs"] += crumbs
        info["crumb_cm3"] += crumb_cm3
        info["thin_cm3"] += thin_cm3
        info["per_piece"][piece] = dict(members=len(members), crumbs=crumbs, crumb_cm3=crumb_cm3, thin_cm3=thin_cm3)
    U = Field(vox)
    U.d = np.minimum.reduce([f.d for f in fields.values()]) if len(fields) > 1 else fields[PIECES[0]].d.copy()
    info["skeleton_cm3"] = skel["cm3"]
    return U, anchors, fields, info


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


def ring_cut_failures(cuts):
    """Revision 14b: a ring is never cut (bitten's runs on a ring are failures); other bones may end in a part and are only reported."""
    return [f"кольцо {name} перерезано зазором на {length:.0f} мм у X {mid[0]:.1f}, Y {mid[1]:.0f}, Z {mid[2]:.0f} ({who} в {dist:.1f} мм)"
            for name, length, mid, who, dist in cuts if name in ("ring_L", "ring_R")]


# ---------------------------------------------------------------------------
# Checks that read only the field (revision 14b), so that test_organic.py can damage a copy of a saved field and expect them to fail
# ---------------------------------------------------------------------------
def sample_field(d, xs, ys, zs, pts):
    """The field at world points, trilinear between grid points; outside the grid it is empty (positive)."""
    pts = np.asarray(pts, dtype=float)
    idx = [(pts[:, k] - float(g[0])) / float(g[1] - g[0]) for k, g in enumerate((xs, ys, zs))]
    return ndimage.map_coordinates(d, idx, order=1, mode="constant", cval=1e9)


def ring_lines():
    """{name: centre line} of the two rings, sampled every RING_CHECK_STEP mm."""
    return {"ring_" + tag: sc.spline(ring(s), step=RING_CHECK_STEP) for s, tag in ((1, "R"), (-1, "L"))}


def bs_box_mask(xs, ys, zs, b):
    """Grid points inside a board-space box (v0, v1, u0, u1, n0, n1)."""
    v = (np.asarray(xs, dtype=float) - hw.ORIGIN[0])[:, None, None]
    y, z = (np.asarray(ys, dtype=float) - hw.ORIGIN[1])[None, :, None], (np.asarray(zs, dtype=float) - hw.ORIGIN[2])[None, None, :]
    u, n = (y + z) * hw.C, (z - y) * hw.C
    return (v >= b[0]) & (v <= b[1]) & (u >= b[2]) & (u <= b[3]) & (n >= b[4]) & (n <= b[5])


def field_checks(d, xs, ys, zs):
    """Checks of the layer that read its field only: nothing beyond the fans' outer faces (|X| ENVELOPE_FAN_X), both rings whole (every point of the centre line at
    least RING_MIN_DEPTH inside the layer, so a ring cut or notched by a carve fails), no voxel of the layer in io_zone, gpu_out_zone or the prism in front of the card's
    outputs. Returns (lines for the report, failures)."""
    out, fails = [], []
    solid = d < 0
    vol = float(xs[1] - xs[0]) ** 3 / 1000.0
    cols = np.any(solid, axis=(1, 2))
    xmax = float(np.abs(np.asarray(xs)[cols]).max()) if cols.any() else 0.0
    beyond = int(solid[np.abs(np.asarray(xs)) > hw.ENVELOPE_FAN_X].sum())
    out.append(f"Наибольший |X| слоя {xmax:.1f} мм (предел {hw.ENVELOPE_FAN_X:g}, наружные грани боковых вентиляторов); вокселей за пределом {beyond}")
    if beyond:
        fails.append(f"слой выходит за |X| {hw.ENVELOPE_FAN_X:g}: {beyond} вокселей, {beyond * vol:.1f} см³, наибольший |X| {xmax:.1f}")
    for name, line in ring_lines().items():
        val = sample_field(d, xs, ys, zs, line)
        i = int(np.argmax(val))
        depth = -float(val[i])
        out.append(f"Кольцо {name}: ось внутри слоя на всей длине ({len(line)} точек через {RING_CHECK_STEP:g} мм), наименьшая глубина оси {depth:.2f} мм (нужно {RING_MIN_DEPTH:g}: радиус "
                   f"{RING_R:g} минус воксель) у X {line[i][0]:.1f}, Y {line[i][1]:.0f}, Z {line[i][2]:.0f}")
        if depth < RING_MIN_DEPTH:
            fails.append(f"кольцо {name} не цело: ось лишь на {depth:.2f} мм внутри слоя (нужно {RING_MIN_DEPTH:g}) у X {line[i][0]:.1f}, Y {line[i][1]:.0f}, Z {line[i][2]:.0f}")
    for name, b in EMPTY_BOXES.items():
        n = int((solid & bs_box_mask(xs, ys, zs, b)).sum())
        out.append(f"Слой в {name} (v {b[0]:g}..{b[1]:g}, u {b[2]:g}..{b[3]:g}, n {b[4]:g}..{b[5]:g}): {n} вокселей, {n * vol:.1f} см³")
        if n:
            fails.append(f"слой стоит в {name}: {n} вокселей, {n * vol:.1f} см³")
    return out, fails


# ---------------------------------------------------------------------------
# Checks of the pieces (revision 17) that read only the saved arrays (a dict like out/organic/field.npz), so that test_organic.py can damage a copy and expect them to fail
# ---------------------------------------------------------------------------
BED_NOT_SPLIT = {"main": "not split into printable pieces yet (docs/plans/rear-panel.md): its extents are reported, not judged"}
GAP_WINDOW = 30.0                                              # mm: gap_checks measures the distance between two pieces up to this (farther is reported as "farther than")
HEAD_PART = "psu_bulkhead"                                     # the part whose screw heads on its rear face the layer must leave reachable
HEAD_CYL_R = (hw.UNC6_HEAD_D + hw.TOOL_PLAY) / 2               # 3.6: a 6-32 head's corridor (UNC6_HEAD_D and TOOL_PLAY are ASSUMPTIONS), which is also HEAD_R; it covers the M3 heads (hw.M3_HEAD_D)


def piece_fields(z):
    """{piece: its field} from the saved arrays."""
    return {str(p): z["d_" + str(p)] for p in z["pieces"]}


def grid_vox(z):
    return float(z["xs"][1] - z["xs"][0])


def body_checks(z):
    """Each piece is one connected body and holds every one of its own pads: the pad's join point (half way up the disc, 0.6 of its radius off the screw across the pad's normal)
    lies in the piece's body. Returns (lines, failures, {pad: joined})."""
    xs, ys, zs, vox = z["xs"], z["ys"], z["zs"], grid_vox(z)
    names, of_piece = [str(n) for n in z["names"]], [str(p) for p in z["pad_piece"]]
    fields = piece_fields(z)
    out, fails, joined = [], [], {}
    for name, piece in zip(names, of_piece):
        if piece not in fields:
            fails.append(f"ORGANIC_PIECES the pad {name} names the piece {piece}, which the field does not have")
    for piece, d in fields.items():
        solid = d < 0
        lab, n = ndimage.label(solid)
        if n == 0:
            fails.append(f"ORGANIC_PIECES {piece}: the piece has no solid voxel")
            continue
        sizes = ndimage.sum(solid, lab, index=np.arange(1, n + 1)) * vox ** 3 / 1000.0
        order = np.argsort(sizes)[::-1]
        big = int(order[0]) + 1
        out.append(f"Кусок {piece}: {sizes.sum():.1f} см³, {sizes.sum() * LAYER_RHO:.0f} г сплошного PETG; связных тел {n}: " + ", ".join(f"{sizes[i]:.1f}" for i in order[:8]) + " см³" + (" ..." if n > 8 else ""))
        if n > 1:
            loose = []
            for i in order[1:]:
                c = ndimage.center_of_mass(lab == (i + 1))
                loose.append(f"{sizes[i]:.1f} cm3 at X {xs[int(c[0])]:.0f}, Y {ys[int(c[1])]:.0f}, Z {zs[int(c[2])]:.0f}")
            fails.append(f"ORGANIC_PIECES {piece} is not one body: {n - 1} separate bodies besides the largest: " + "; ".join(loose[:10]))
        mine = [i for i, p in enumerate(of_piece) if p == piece]
        if not mine:
            fails.append(f"ORGANIC_PIECES {piece} holds no pad")
        for i in mine:
            q, nrm = np.asarray(z["pads"][i][:3], dtype=float), np.asarray(z["pads"][i][3:], dtype=float)
            pt = q + nrm * (PAD_H * 0.5) + across(nrm) * (PAD_R * 0.6)
            idx = tuple(int(round((c - g[0]) / vox)) for c, g in zip(pt, (xs, ys, zs)))
            ok = all(0 <= k < m for k, m in zip(idx, lab.shape)) and lab[idx] == big
            joined[names[i]] = bool(ok)
            if not ok:
                fails.append(f"ORGANIC_PIECES {names[i]}: the pad is not joined to the body of the piece {piece} (its disc beside the screw, at X {pt[0]:.1f}, Y {pt[1]:.1f}, Z {pt[2]:.1f}, is not in it)")
    return out, fails, joined


def gap_checks(z):
    """The least distance between the solids of any two pieces: the least distance between their voxels' centres less one voxel (each solid's surface stands about half a voxel
    beyond its last centre, as for the extents). Fails under GAP_PIECE less one voxel, that is when two voxel centres are closer than GAP_PIECE."""
    vox = grid_vox(z)
    fields = piece_fields(z)
    names = list(fields)
    out, fails = [], []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            sa, sb = fields[a] < 0, fields[b] < 0
            if not sa.any() or not sb.any():
                fails.append(f"ORGANIC_PIECES {a} / {b}: {'both are' if not sa.any() and not sb.any() else (a if not sa.any() else b) + ' is'} empty, their distance is not measured")
                continue
            small, large = (sa, sb) if sa.sum() <= sb.sum() else (sb, sa)
            idx = np.argwhere(small)
            m = int(math.ceil(max(GAP_WINDOW, GAP_PIECE) / vox)) + 1    # the window round the smaller piece: anything of the other beyond it is farther than GAP_WINDOW
            win = tuple(slice(max(int(lo) - m, 0), int(hi) + m + 1) for lo, hi in zip(idx.min(axis=0), idx.max(axis=0)))
            lw = large[win]
            centre = float(ndimage.distance_transform_edt(~lw, sampling=vox)[small[win]].min()) if lw.any() else float("inf")
            gap = centre - vox
            out.append(f"Куски {a} и {b}: наименьшее расстояние между телами {gap:.2f} мм (между центрами вокселей {centre:.2f} минус воксель; нужно {GAP_PIECE:g} без вокселя, {GAP_PIECE - vox:g})"
                       if math.isfinite(gap) else f"Куски {a} и {b}: дальше {GAP_WINDOW:g} мм друг от друга")
            if gap < GAP_PIECE - vox:
                fails.append(f"ORGANIC_PIECES {a} and {b} are {gap:.2f} mm apart (voxel centres {centre:.2f}), they must keep {GAP_PIECE:g} less one voxel ({GAP_PIECE - vox:g})")
    return out, fails


def piece_extents(d, xs, ys, zs):
    """[(lo, hi)] per world axis of a piece: the span of its solid voxels' centres widened by half a voxel each way (the extent is the span plus one voxel); None if empty."""
    solid = d < 0
    vox = float(xs[1] - xs[0])
    out = []
    for axis, g in enumerate((xs, ys, zs)):
        cols = np.flatnonzero(np.any(solid, axis=tuple(k for k in range(3) if k != axis)))
        if not len(cols):
            return None
        out.append((float(g[cols[0]]) - vox / 2, float(g[cols[-1]]) + vox / 2))
    return out


BED_ANGLES = np.arange(180)                                    # whole degrees about the vertical that bed_fit tries (a turn by 180 gives the same extents)


def bed_fit(d, xs, ys, zs):
    """How a piece stands on the bed as built (Z up), turned about the vertical: for every angle of BED_ANGLES the extents along the two turned horizontal directions and along Z,
    each the span of the solid voxels' centres plus what one voxel's cube adds: along Z one voxel, along a horizontal direction turned by the angle a
    vox * (|cos a| + |sin a|), the cube's own extent along that direction (one voxel on the grid's axes, 1.41 voxels at 45 degrees; "plus one voxel" would be 0.6 mm short there).
    Returns dict(angle, u, v, height, fits, any_fits) for the best angle (the one with the smallest larger horizontal
    extent; the first such), or None if the piece has no solid voxel. fits: that angle's u, v and height are all at most frame_v0.MAX_PART."""
    solid = d < 0
    if not solid.any():
        return None
    vox = float(xs[1] - xs[0])
    zcols = np.flatnonzero(solid.any(axis=(0, 1)))
    height = float(zs[zcols[-1]] - zs[zcols[0]]) + vox
    ij = np.argwhere(solid.any(axis=2))                                       # the columns: the turn about Z does not depend on Z
    px, py = np.asarray(xs, dtype=float)[ij[:, 0]], np.asarray(ys, dtype=float)[ij[:, 1]]
    if len(px) > 3:                                                           # a span is reached on the convex hull: only its corners are turned
        from scipy.spatial import ConvexHull, QhullError
        try:
            corners = ConvexHull(np.column_stack([px, py])).vertices
            px, py = px[corners], py[corners]
        except QhullError:                                                    # all on one line: keep every point
            pass
    a = np.radians(BED_ANGLES.astype(float))
    c, s = np.cos(a)[:, None], np.sin(a)[:, None]
    u = px[None, :] * c + py[None, :] * s
    v = -px[None, :] * s + py[None, :] * c
    cube = vox * (np.abs(c[:, 0]) + np.abs(s[:, 0]))                          # a voxel's cube along a turned horizontal direction (the same along both)
    eu = u.max(axis=1) - u.min(axis=1) + cube
    ev = v.max(axis=1) - v.min(axis=1) + cube
    big = np.maximum(eu, ev)
    k = int(np.argmin(big))
    lim = frame_v0.MAX_PART
    ok = (eu <= lim) & (ev <= lim) & (height <= lim)
    return dict(angle=int(BED_ANGLES[k]), u=float(eu[k]), v=float(ev[k]), height=height, fits=bool(ok[k]), any_fits=bool(ok.any()))


def bed_checks(z):
    """A piece must fit the printer's bed standing as it stands on the case (Z up), turned about the vertical by some whole degree (bed_fit): both horizontal extents and the
    height at most frame_v0.MAX_PART. The pieces of BED_NOT_SPLIT are reported only. Every piece's extents along the world axes are reported too."""
    out, fails = [], []
    for piece, d in piece_fields(z).items():
        ext = piece_extents(d, z["xs"], z["ys"], z["zs"])
        fit = bed_fit(d, z["xs"], z["ys"], z["zs"])
        if ext is None or fit is None:
            fails.append(f"ORGANIC_PIECES {piece}: the piece has no solid voxel, its extents are not measured")
            continue
        size = [hi - lo for lo, hi in ext]
        out.append(f"Кусок {piece}: габарит X {ext[0][0]:.2f}..{ext[0][1]:.2f} ({size[0]:.1f}), Y {ext[1][0]:.2f}..{ext[1][1]:.2f} ({size[1]:.1f}), Z {ext[2][0]:.2f}..{ext[2][1]:.2f} ({size[2]:.1f}) мм; "
                   f"стоя, как на корпусе, и повёрнутый вокруг вертикали лучше всего на {fit['angle']}°: {fit['u']:.1f} x {fit['v']:.1f} мм на столе, высота {fit['height']:.1f} мм; "
                   + (f"не проверяется по столу: {BED_NOT_SPLIT[piece]}" if piece in BED_NOT_SPLIT else
                      f"стол {frame_v0.MAX_PART:g} мм: {'помещается' if fit['any_fits'] else 'НЕ помещается ни под одним углом'}. Печатается стоя и повёрнутым; на принтере это не пробовали; поддержки, прилипание к столу и то, достаёт ли сопло до углов стола, эта проверка не смотрит"))
        if piece not in BED_NOT_SPLIT and not fit["any_fits"]:
            fails.append(f"ORGANIC_PIECES {piece} does not fit the bed at any whole degree about the vertical: at best ({fit['angle']} degrees) {fit['u']:.1f} x {fit['v']:.1f} mm, "
                         f"{fit['height']:.1f} mm tall; the most is {frame_v0.MAX_PART:g} each way")
    return out, fails


def screw_heads(parts):
    """(k, 6) array: for every screw head on HEAD_PART's rear face, the point on the face and the outward axis. A 6-32cb counterbore (the PSU's screws) has its mouth on the face
    (h.point(OVERSHOOT)) and the head comes out along -d; an M3c clearance hole (the drive sleds' flange screws, from behind) has the head at its end with the larger Y."""
    part = next(p for p in parts if p.name == HEAD_PART)
    rows = []
    for h in part.holes:
        d = np.array(h.d, dtype=float)
        if h.kind == "6-32cb":
            rows.append((*h.point(frame_v0.OVERSHOOT), *(-d)))
        elif h.kind == "M3c":
            if h.point(h.length)[1] >= h.start[1]:
                rows.append((*h.point(h.length - frame_v0.OVERSHOOT), *d))
            else:
                rows.append((*h.point(frame_v0.OVERSHOOT), *(-d)))
    return np.array(rows, dtype=float).reshape(-1, 6)


def cylinder_mask(xs, ys, zs, q, n, r, h0, h1):
    """(block, mask) of the grid points inside the capped cylinder of radius r on the axis from q + h0 n to q + h1 n."""
    q, n = np.asarray(q, dtype=float), np.asarray(n, dtype=float)
    ends = np.array([q + h0 * n, q + h1 * n])
    lo, hi = ends.min(axis=0) - r, ends.max(axis=0) + r
    sl = tuple(slice(int(np.searchsorted(g, a)), int(np.searchsorted(g, b, side="right"))) for g, a, b in zip((xs, ys, zs), lo, hi))
    X, Y, Z = np.meshgrid(np.asarray(xs[sl[0]], dtype=float), np.asarray(ys[sl[1]], dtype=float), np.asarray(zs[sl[2]], dtype=float), indexing="ij")
    vx, vy, vz = X - q[0], Y - q[1], Z - q[2]
    h = vx * n[0] + vy * n[1] + vz * n[2]
    rad = np.sqrt(np.maximum(vx * vx + vy * vy + vz * vz - h * h, 0.0))
    return sl, (h >= h0) & (h <= h1) & (rad <= r)


def head_checks(z):
    """No solid voxel of any piece in the cylinder behind each screw head of HEAD_PART's rear face: from the face along the head's axis for HEAD_REACH, radius HEAD_CYL_R. The heads
    are z["heads"] (screw_heads); none, or a cylinder with no grid point in it, is a failure."""
    out, fails = [], []
    heads = np.asarray(z["heads"], dtype=float).reshape(-1, 6)
    fields = piece_fields(z)
    out.append(f"Головки винтов на задней грани {HEAD_PART}: {len(heads)} цилиндров, радиус {HEAD_CYL_R:g} мм, {HEAD_REACH:g} мм от грани по оси головки")
    if not len(heads):
        fails.append(f"ORGANIC_PIECES no screw head found on {HEAD_PART}'s rear face: nothing is checked")
    for row in heads:
        q, n = row[:3], row[3:]
        sl, m = cylinder_mask(z["xs"], z["ys"], z["zs"], q, n, HEAD_CYL_R, 0.0, HEAD_REACH)
        if not m.any():
            fails.append(f"ORGANIC_PIECES the cylinder behind the head at X {q[0]:.1f}, Y {q[1]:.1f}, Z {q[2]:.1f} has no grid point: nothing is checked there")
            continue
        hits = {piece: int((d[sl][m] < 0).sum()) for piece, d in fields.items()}
        out.append(f"  головка у X {q[0]:6.1f}, Y {q[1]:.1f}, Z {q[2]:5.1f}: точек сетки в цилиндре {int(m.sum())}, вокселей слоя " + ", ".join(f"{k} {v}" for k, v in hits.items()))
        for piece, k in hits.items():
            if k:
                fails.append(f"ORGANIC_PIECES {piece} has {k} voxels in the way of the screw head at X {q[0]:.1f}, Y {q[1]:.1f}, Z {q[2]:.1f} on {HEAD_PART}")
    return out, fails


def layout_failures(z):
    """Failures of the arrays' layout, which the other checks of the pieces take for granted (each of them passes when it has nothing to judge): `pieces` is not empty and
    each has its field d_<piece>; `d` is the minimum of the pieces' fields, exactly; every pad (a row of `pads`, a name of `names`) names one of the pieces in `pad_piece`.
    Returns (failures, fatal): fatal when the other checks cannot run on these arrays."""
    fails = []
    pieces = [str(p) for p in np.atleast_1d(z.get("pieces", np.array([], dtype=str)))]
    if not pieces:
        return ["ORGANIC_PIECES the field has no piece: nothing of the layer would be judged"], True
    missing = [p for p in pieces if "d_" + p not in z]
    if missing:
        return [f"ORGANIC_PIECES the field names the piece {p} but has no field d_{p}" for p in missing], True
    union = np.minimum.reduce([z["d_" + p] for p in pieces]) if len(pieces) > 1 else z["d_" + pieces[0]]
    d = z["d"]
    if d.shape != union.shape:
        fails.append(f"ORGANIC_PIECES d has the shape {d.shape}, the pieces' fields {union.shape}")
    elif not np.array_equal(d, union):
        fails.append(f"ORGANIC_PIECES d is not the minimum of the pieces' fields: {int(np.count_nonzero(d != union))} voxels differ "
                     f"({int(np.count_nonzero((d < 0) != (union < 0)))} of them solid in one and not in the other)")
    names, of_piece, n_pads = [str(n) for n in z["names"]], [str(p) for p in z["pad_piece"]], len(np.asarray(z["pads"]).reshape(-1, 6))
    if n_pads != len(names):
        fails.append(f"ORGANIC_PIECES {n_pads} pad rows and {len(names)} pad names")
    for i, name in enumerate(names):
        if i >= len(of_piece) or not of_piece[i]:
            fails.append(f"ORGANIC_PIECES the pad {name} names no piece")
    if len(of_piece) > len(names):
        fails.append(f"ORGANIC_PIECES {len(of_piece)} pieces named for {len(names)} pads")
    return fails, False


def piece_checks(z):
    """All checks of the pieces on the saved arrays. Returns (lines, failures, {pad: joined})."""
    fails, fatal = layout_failures(z)
    if fatal:
        return [], fails, {}
    out, fl, joined = body_checks(z)
    fails += fl
    for f in (gap_checks, bed_checks, head_checks):
        o, fl = f(z)
        out += o
        fails += fl
    return out, fails, joined


def saved_arrays(F, anchors, fields, parts):
    """The dict organic_frame.py saves as out/organic/field.npz: d (the union of the pieces, what every reader takes as the layer), the grid, the pads ((n, 6): centre and normal)
    and their names, the pieces' names, the piece of each pad, one field per piece (d_<piece>) and the screw heads of HEAD_PART (screw_heads)."""
    z = dict(d=F.d, xs=F.xs, ys=F.ys, zs=F.zs, pads=np.array([np.concatenate([a["q"], a["n"]]) for a in anchors]), names=np.array([a["name"] for a in anchors]),
             pieces=np.array(list(fields)), pad_piece=np.array([hw.ORGANIC_PADS[a["name"]][3] for a in anchors]), heads=screw_heads(parts))
    for piece, f in fields.items():
        z["d_" + piece] = f.d
    return z


def check(F, anchors, parts, hware, lines, z):
    """Checks of the built layer. Returns (lines for the report, failures)."""
    import cadquery as cq
    out, fails = [], []
    p_lines, p_fails, joined = piece_checks(z)
    out += p_lines
    fails += p_fails
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
        ok = joined.get(a["name"], False)
        off = min((float(np.linalg.norm(np.array(h.point(frame_v0.OVERSHOOT)) - q)) for h in by_part[a["part"]].holes if h.kind == "M3" and h.pilot), default=float("nan"))
        out.append(f"{a['name']:14} {a['part']:18} {q[0]:8.1f} {q[1]:8.1f} {q[2]:8.1f} {off:11.2f} мм {a['bone']:>9} {a['stub_len']:11.0f} "
                   f"{near[0]:8.1f} мм {near[1]:>10} {hose:8.1f} мм" + ("" if ok else "   НЕ СОЕДИНЕНО С ТЕЛОМ"))
        hot = HOT_GAP if near[1] in ("gpu", "psu") else GAP_HW
        if near[0] < hot:
            fails.append(f"{a['name']}: площадка в {near[0]:.1f} мм от {near[1]} (нужно {hot:g})")
        if hose < 5.0:
            fails.append(f"{a['name']}: площадка в {hose:.1f} мм от шланга (нужно 5)")
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
    fails += ring_cut_failures(cuts)
    out.append("")
    f_lines, f_fails = field_checks(F.d, F.xs, F.ys, F.zs)
    return out + f_lines, fails + f_fails


SIDE_DIFFERENCES = (
    "Левый и правый фланги зеркальны, кроме мест, где этого требуют шланги или видеовыходы карты:",
    "  - передний изгиб (front_*): слева кончается у края карты (между ним и углом губы вниз по флангу идут шланги CPU), справа доходит до угла губы;",
    "  - плёнка от верха кольца к боковой кости: справа от u 132, слева от u 186 (шланги CPU пересекают этот промежуток на u 141..170);",
    "  - плёнка от ближней стороны кольца к переднему изгибу только справа; слева она висела бы перед видеовыходами карты, вместо неё ring_tie_L (выше n 100);",
    "  - ring_tie_L2 (верхний дальний угол левого кольца к нижнему концу боковой кости) только слева: держит верх кольца там, где нет плёнки;",
    "  - плёнки под вентилятором нет ни с одной стороны: слева под вентилятором рука поднимается к разъёмам платы (zone_access.py), справа идут шланги карты;",
    "  - ring_tie_L3 (нижний передний угол левого кольца к нижней кости за передней опорой) только слева: справа этот угол держит плёнка ближней стороны, слева её нет;",
    "  - нижняя кость (base_*) и задняя плёнка (от base у Y 196 до заднего изгиба) одинаковы с обеих сторон, как до первого прохода ревизии 14b.",
)


def flank_report(F, parts, hware):
    """Report lines of revision 14b: the rings' offset and their nearest neighbours, the layer's least distance to the side fans' leads."""
    import cadquery as cq
    from scipy.spatial import cKDTree
    import drive_access
    out = [f"Кольца вокруг боковых вентиляторов: замкнутые, ось в {RING_OFF:g} мм от коробки вентилятора (радиус {RING_R:g} + зазор {GAP_HW:g} + воксель {VOX:g}), "
           f"в средней плоскости вентилятора, X {RING_X[1]:g} и {RING_X[-1]:g}"]
    for s, tag in ((1, "R"), (-1, "L")):
        pts = sc.spline(ring(s), step=3.0)
        wire = cq.Wire.makePolygon([cq.Vector(*map(float, p)) for p in pts])
        rows = sorted([(p.solid.distance(wire), p.name) for p in parts] + [(sol.distance(wire), "hw:" + k) for k, sol in hware.items()])
        out.append(f"  ring_{tag}, от оси до ближайших (мм): " + ", ".join(f"{n} {d:.1f}" for d, n in rows[:7])
                   + f"; до стола {pts[:, 2].min() - hw.DESK_Z:.0f}, до передней плоскости {pts[:, 1].min() - hw.ENVELOPE_Y0:.0f}")
    idx = np.argwhere(F.d < 0)
    tree = cKDTree(np.stack([F.xs[idx[:, 0]], F.ys[idx[:, 1]], F.zs[idx[:, 2]]], axis=1))
    strands, _ = drive_access.cable_strands()
    for cname in hw.FAN_SIDE_CABLES:
        best = float("inf")
        for p, r in strands.get(cname, ()):
            p = np.asarray(p, dtype=float)
            seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
            sc_ = np.concatenate([[0.0], np.cumsum(seg)])
            t = np.arange(0.0, sc_[-1] + 0.5, 0.5)
            q = np.stack([np.interp(t, sc_, p[:, k]) for k in range(3)], axis=1)
            best = min(best, float((tree.query(q)[0] - r).min()) - F.vox / 2)
        out.append(f"  провод вентилятора {cname}: до слоя {best:.1f} мм (от поверхности провода до ближайшего вокселя слоя минус полвокселя)")
    return out


def main():
    t0 = time.time()
    parts, _ = frame_v0.build_frame()
    parts = [p for p in parts]
    hware = hw.build_hardware()
    F, anchors, fields, info = build(parts, hware)
    z = saved_arrays(F, anchors, fields, parts)
    lines, fails = check(F, anchors, parts, hware, info['lines'], z)
    lines += [""] + flank_report(F, parts, hware) + [""] + list(SIDE_DIFFERENCES)
    b = np.argwhere(F.d < 0)
    lo, hi = b.min(axis=0), b.max(axis=0)
    head = [f"ОРГАНИЧЕСКИЙ СЛОЙ (PETG, запасной вариант ABS), одно поле с шагом {F.vox:g} мм, элементов {info['members']}, время {time.time() - t0:.0f} с",
            f"Габарит X {F.xs[lo[0]]:.0f}..{F.xs[hi[0]]:.0f}, Y {F.ys[lo[1]]:.0f}..{F.ys[hi[1]]:.0f}, Z {F.zs[lo[2]]:.0f}..{F.zs[hi[2]]:.0f}",
            f"Правила прочности: нить плёнки в середине Ø{2 * STRAND_R_MID[0]:g}..{2 * STRAND_R_MID[1]:g} мм, у кости Ø{2 * STRAND_R_END[0]:g}..{2 * STRAND_R_END[1]:g}; "
            f"поперечная нить Ø{2 * LINK_R[1]:g}..{2 * LINK_R[0]:g}; стойка крепления Ø{2 * STUB[1]:g}..{2 * STUB[0]:g}",
            f"Крепления: {len(anchors)} площадок Ø{2 * PAD_R:g} x {PAD_H:g} мм на гранях каркаса, винт M3 x {frame_v0.screw_fit(PAD_H)[0]} с шайбой в резьбовую вставку в ABS "
            f"(места из hw.ORGANIC_PADS; пилот M3 под каждую вырезан в каркасе, ось винта лежит на оси пилота). Зазоры слоя: каркас {GAP_SKEL:g}, запретные зоны платы {GAP_KEEP:g}, железо и шланги {GAP_HW:g}, "
            f"видеокарта и БП {HOT_GAP:g} мм."]
    head.append(f"Крошки после вырезания зазоров (отдельные куски меньше {CRUMB_CM3:g} см³) удалены: {info['crumbs']} шт., {info['crumb_cm3']:.1f} см³. Перемычки тоньше {MIN_THICK:g} мм удалены: {info['thin_cm3']:.1f} см³.")
    head.append(f"Куски слоя (ревизия 17), в порядке постройки, каждый со своим полем; поздний держит {GAP_PIECE:g} мм от ранних: " + "; ".join(
        f"{k}: элементов {v['members']}, крошек {v['crumbs']} ({v['crumb_cm3']:.1f} см³), перемычек {v['thin_cm3']:.1f} см³" for k, v in info["per_piece"].items()))
    text = "\n".join(head + [""] + lines + [""] + (["ПРОВЕРКИ НЕ ПРОЙДЕНЫ:"] + ["  - " + f for f in fails] if fails else ["Все проверки пройдены."]))
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_organic.txt"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)
    out_dir = os.path.join(sc.ROOT, "out", "organic")
    os.makedirs(out_dir, exist_ok=True)
    np.savez_compressed(os.path.join(out_dir, "field.npz"), **z)
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
