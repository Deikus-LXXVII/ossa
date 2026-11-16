#!/usr/bin/env python3
"""B6 «Шатёр»: structural skeleton v0.

Every component of hardware.py gets a named holder with real fasteners.
Ribs, necks, arms, antlers are flat plates extruded along X from 2D YZ
outlines (capsules, rectangles, discs); cross members are boxes; holes are
cylinders. No lofts, no splines.

Revision 8 rounds the skeleton's corners: plates on their 2D outline (cad_b6/rounding.py), box members along their long edges,
joints with a 3D fillet. build_frame(rounded=False) is the skeleton as it was before, the reference for check 12 and for the contact areas.
Revision 8a lets a rounding take contact area (a contact keeps 97 % of its unrounded area and 4 mm of flat contact round every screw).
Revision 9 adds front_sill (the front sill for the I/O module and the light line, hardware front_io and light_strip are PLACEHOLDERS) and a
material per part: ABS for the skeleton, PA6 for the two hose guides.

Run from the repo root:  .venv/bin/python cad_b6/frame_v0.py
Out: cad_b6/report_frame_v0.txt, cad_b6/b6_frame_v0.step,
     previews/b6_frame_v0.png, previews/b6_frame_v0_bare.png,
     previews/b6_frame_v0_exploded.png
"""

from __future__ import annotations

import itertools
import math
import os
import sys
import weakref
from dataclasses import dataclass, field

import cadquery as cq
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import PolyCollection
from matplotlib.colors import to_rgb
from matplotlib.patches import Patch
from cadquery import Compound, Solid, Vector, Vertex

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import hardware as hw  # noqa: E402
import hoses  # noqa: E402
import rounding as rd  # noqa: E402

PREVIEWS = os.path.join(ROOT, "previews")
os.makedirs(PREVIEWS, exist_ok=True)

ABS_DENSITY = 1.04      # g/cm^3
PA6_DENSITY = 1.14      # g/cm^3, unfilled PA6 (1.13..1.15)
DENSITY = {"ABS": ABS_DENSITY, "PA6": PA6_DENSITY}
# material of every part in this file (revision 9): load-bearing parts are ABS, the two hose guides that snap over the hose are PA6.
# The PLA layer (organic_frame.py, the light diffuser) is not in this file.
MATERIALS = ("ABS", "PA6")
WALL_T = 1.6            # 4 perimeters x 0.4 mm
INFILL = 0.20
MAX_PART = 290.0
VOL_EPS = 1.0           # mm^3, part x hardware / part x part
CLOSE_MM = 5.0
FRAME_RGB = (0.62, 0.63, 0.66)

# ribs
X_IN, X_MID, X_OUT = 142.0, 150.0, 158.0
RIB_T = X_OUT - X_IN


# ---------------------------------------------------------------------------
# 2D outlines in the YZ plane, extruded along X
# ---------------------------------------------------------------------------
def _seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


@dataclass
class Cap:
    """Stadium of width w around the segment p -> q (Y, Z)."""
    p: tuple
    q: tuple
    w: float

    def contains(self, pt, margin=0.0):
        return _seg_dist(pt, self.p, self.q) <= self.w / 2 - margin

    def solid(self, x0, x1):
        (py, pz), (qy, qz) = self.p, self.q
        L = math.hypot(qy - py, qz - pz)
        wp = cq.Workplane("YZ", origin=(x0, 0, 0)).center((py + qy) / 2, (pz + qz) / 2)
        if L < 1e-6:
            wp = wp.circle(self.w / 2)
        else:
            ang = math.degrees(math.atan2(qz - pz, qy - py))
            wp = wp.slot2D(L + self.w, self.w, ang)
        return wp.extrude(x1 - x0).val()


@dataclass
class Rect:
    y0: float
    y1: float
    z0: float
    z1: float

    def contains(self, pt, margin=0.0):
        return (self.y0 + margin <= pt[0] <= self.y1 - margin
                and self.z0 + margin <= pt[1] <= self.z1 - margin)

    def solid(self, x0, x1):
        return (cq.Workplane("YZ", origin=(x0, 0, 0)).moveTo(self.y0, self.z0)
                .rect(self.y1 - self.y0, self.z1 - self.z0, centered=False)
                .extrude(x1 - x0).val())


@dataclass
class Disc:
    c: tuple
    d: float

    def contains(self, pt, margin=0.0):
        return math.hypot(pt[0] - self.c[0], pt[1] - self.c[1]) <= self.d / 2 - margin

    def solid(self, x0, x1):
        return (cq.Workplane("YZ", origin=(x0, 0, 0)).center(*self.c)
                .circle(self.d / 2).extrude(x1 - x0).val())


@dataclass
class Poly:
    pts: list

    def contains(self, pt, margin=0.0):
        """Inside the polygon and at least `margin` from every edge."""
        x, y = pt
        inside_ = False
        n = len(self.pts)
        for i in range(n):
            (x0, y0), (x1, y1) = self.pts[i], self.pts[(i + 1) % n]
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                inside_ = not inside_
        if not inside_:
            return False
        return all(_seg_dist(pt, self.pts[i], self.pts[(i + 1) % n]) >= margin for i in range(n))

    def solid(self, x0, x1):
        return (cq.Workplane("YZ", origin=(x0, 0, 0)).polyline(self.pts).close()
                .extrude(x1 - x0).val())


def outline_solid(prims, x0, x1):
    return fuse_all([p.solid(x0, x1) for p in prims])


def inside(prims, pt, margin):
    return any(p.contains(pt, margin) for p in prims)


# ---------------------------------------------------------------------------
# Solid helpers
# ---------------------------------------------------------------------------
def fuse_all(solids):
    acc = solids[0]
    for s in solids[1:]:
        acc = acc.fuse(s)
    return acc.clean()


def cyl(p, d, dia, length):
    return Solid.makeCylinder(dia / 2.0, length, Vector(*p), Vector(*d))


def cut_all(solid, cuts):
    cuts = [c.solid if isinstance(c, Hole) else c for c in cuts]
    return solid.cut(*cuts) if cuts else solid


def mirror_x(solid):
    return solid.mirror("YZ")


def n_solids(shape):
    return len(shape.Solids())


# ---------------------------------------------------------------------------
# Revision 8: rounding of the skeleton's sharp corners.
# Plates are rounded on their 2D outline before the face is extruded (rounding.py); box members get their long edges
# rounded by cutting a wedge. A rounding is only accepted when it keeps every contact area, every hole's wall ring and
# every clearance (see rounding.Guard); a corner that cannot be rounded stays sharp and is written to ROUND_LOG.
# ---------------------------------------------------------------------------
ROUND_CONVEX, ROUND_CONCAVE, ROUND_MIN = 6.0, 8.0, 2.0    # mm: outside corners, inside corners, smallest radius worth making
BOX_R = 3.0                                                 # mm: long edges of the box members
COLLAR = 4.0                                                # mm: a box member keeps its end face's outline for this length
ROUND_LOG: list = []                                        # rounding.Entry per corner / edge, reset by build_frame
KEEP_SHARP: dict = {}                                       # part name -> [(y, z, reason)] corners declared sharp (a face that touches something)
ROUND = None                                                # RoundCtx while a rounded frame is being built, else None
_A_LAYER: dict = {}                                         # with_rest -> rib_A's outline prism, for rib_B's lap cut
_CTX: dict = {}                                             # id(hardware) -> (hardware, RoundCtx)


class RoundCtx:
    """What a rounding is judged against: the hardware and the other parts as built without rounding, once as they are
    and once mirrored in X (a left-hand part is built right-handed and mirrored afterwards, so it sees the mirror image)."""

    def __init__(self, hardware, ref_parts):
        plain, mirrored = [], []
        for k, s in hardware.items():
            role = "hose" if k in hw.HOSES else "keepout" if k in hw.KEEP_OUT else "hw"
            plain.append(rd.Neighbor(k, s, role))
            mirrored.append(rd.Neighbor(k + "~", mirror_x(s), role))
        for p in ref_parts:
            plain.append(rd.Neighbor(p.name, p.solid, "part"))
            mirrored.append(rd.Neighbor(p.name + "~", mirror_x(p.solid), "part"))
        self.sets = {1: plain, -1: mirrored}
        self.cache: dict = {}        # (what, geometry of the input) -> (result, log entries): a second build of the same frame replays it
        self.ledger: dict = {}       # (part, neighbour) -> mm2 of contact the part has given up to rounding so far in this build (revision 8a)
        self.a0: dict = {}           # (part, neighbour) -> the unrounded contact area; it never changes for one hardware set

    @staticmethod
    def share(name):
        """Share of the 3 % contact allowance a part may take against `name`: half against another rounded plate (which takes the other half), else all."""
        return 0.5 if name.rstrip("~").startswith(PLATE_PREFIXES) else 1.0

    def guard(self, tvec, rings, own, sides, extra=(), post_cuts=()):
        nb, ex, me = self.neighbors(sides, own, extra)
        screws = [(h.start, h.d, h.screw_r()) for h in getattr(rings, "holes", ())]
        return rd.Guard(nb, tvec, rings=rings, post_cuts=post_cuts, exclude=ex, selfshape=me, screws=screws,
                        ledger=self.ledger, own=own[0], share=self.share, a0=self.a0)

    def remembered(self, key, make):
        """make() -> result, with the ROUND_LOG entries it adds remembered under `key` and replayed on a repeat call."""
        key = key + (tuple(sorted(self.ledger.items())),)      # the allowance already spent decides what is accepted
        hit = self.cache.get(key)
        if hit is not None:
            ROUND_LOG.extend(hit[1])
            for k, v in hit[2].items():
                self.ledger[k] = self.ledger.get(k, 0.0) + v
            return hit[0]
        n0 = len(ROUND_LOG)
        before = dict(self.ledger)
        out = make()
        delta = {k: v - before.get(k, 0.0) for k, v in self.ledger.items() if v - before.get(k, 0.0) != 0.0}
        self.cache[key] = (out, list(ROUND_LOG[n0:]), delta)
        return out

    def neighbors(self, sides, own, extra=()):
        items = [n for s in sides for n in self.sets[s]] + list(extra)
        me = next((n.shape for n in self.sets[sides[0]] if n.name in (own[0], own[0] + "~")), None)     # the part before rounding
        return rd.Neighbors(items), {x for o in own for x in (o, o + "~")}, me


class HoleRings(list):
    """The wall rings of hole_rings(), remembering the holes they come from: rounding.Guard reads the screws' axes (revision 8a)."""
    holes: tuple = ()


def hole_rings(holes):
    """Cylinders of radius hole + minimum wall along every hole: the material a rounding must leave alone."""
    out = HoleRings(cyl(h.start, h.d, 2 * (h.r + h.wall), h.length) for h in holes)
    out.holes = tuple(holes)
    return out


def rounded_like(solid, axis, name, *, sides, own, rings=(), post_cuts=(), keep=(), extra=(),
                 convex=ROUND_CONVEX, concave=ROUND_CONCAVE):
    """`solid` is a prism along `axis`. When a rounded frame is being built, return the same prism with the corners of its
    outline rounded; otherwise return it unchanged. sides: +1 for a part that is built where it stands, -1 for one built
    right-handed and mirrored afterwards. own: names that are this part (not neighbours). rings: cylinders to leave
    alone. post_cuts: cuts applied to the prism afterwards. keep: [((x, y, z), reason)] corners that stay sharp."""
    if ROUND is None:
        return solid
    bb = bbox_of(solid)
    key = ("outline", name, tuple(round(float(a), 4) for a in axis), round(solid.Volume(), 2), tuple(round(x, 2) for x in bb), tuple(sides), convex, concave,
           tuple(round(x, 2) for r in rings for x in bbox_of(r)), tuple(round(x, 2) for c in post_cuts for x in bbox_of(c)))
    return ROUND.remembered(key, lambda: _rounded_like(solid, axis, name, sides, own, rings, post_cuts, keep, extra, convex, concave))


def _rounded_like(solid, axis, name, sides, own, rings, post_cuts, keep, extra, convex, concave):
    ax = np.array(axis, float)
    ax /= np.linalg.norm(ax)
    faces = [f for f in solid.Faces() if f.geomType() == "PLANE" and float(np.array(f.normalAt().toTuple()) @ ax) < -0.9999]
    face = min(faces, key=lambda f: float(np.array(f.Center().toTuple()) @ ax))
    proj = [float(np.array(v.toTuple()) @ ax) for v in solid.Vertices()]
    tvec = Vector(*(ax * (max(proj) - min(proj))))
    guard = ROUND.guard(tvec, rings, own, sides, extra, post_cuts)
    new = rd.round_face(face, part=name, convex_r=convex, concave_r=concave, r_min=ROUND_MIN, guard=guard,
                        keep=keep, log=ROUND_LOG)
    return rd.extrude_face(new, tvec)


def corner_wedge(bounds, axis, hi_i, hi_j, r, a0, a1):
    """The sliver of a box between its edge along `axis` and a rounding of radius r, for the section corner that is the
    max (hi) or min side of the two other axes, from a0 to a1 along the axis. `bounds` = (lo, hi) in the box's own
    axis-aligned frame. It starts 1 mm outside the box so no face of the cutter lies on a face of the part."""
    i, j = [k for k in range(3) if k != axis]
    lo, hi = bounds
    pi, pj = (hi[i] if hi_i else lo[i]), (hi[j] if hi_j else lo[j])
    si, sj = (-1.0 if hi_i else 1.0), (-1.0 if hi_j else 1.0)
    ui = sorted((pi - si * 1.0, pi + si * r))
    uj = sorted((pj - sj * 1.0, pj + sj * r))
    dims, org = [0.0] * 3, [0.0] * 3
    dims[axis], dims[i], dims[j] = a1 - a0, ui[1] - ui[0], uj[1] - uj[0]
    org[axis], org[i], org[j] = a0, ui[0], uj[0]
    c = [0.0] * 3
    c[axis], c[i], c[j] = a0, pi + si * r, pj + sj * r
    d = [0.0] * 3
    d[axis] = 1.0
    return Solid.makeBox(*dims, Vector(*org)).cut(Solid.makeCylinder(r, a1 - a0, Vector(*c), Vector(*d)))


def un_of(y, z):
    """Board-space (u, n) of a world (Y, Z) point."""
    a, b = (y - hw.ORIGIN[1]) / hw.C, (z - hw.ORIGIN[2]) / hw.C      # u - n and u + n
    return (a + b) / 2, (b - a) / 2


def edge_info(e):
    """(midpoint, unit direction) of an edge as numpy arrays."""
    a, b = np.array(e.startPoint().toTuple()), np.array(e.endPoint().toTuple())
    return (a + b) / 2, (b - a) / max(float(np.linalg.norm(b - a)), 1e-12)


def junction_fillet(solid, name, label, pick, *, sides, own, rings=(), extra=(), radii=None):
    """Rule 4: fillet the concave edges of `solid` that `pick(edge)` selects (a boss, tongue, ear or leg meeting its plate) with the
    largest radius from 8 mm down to 2 that the kernel accepts and the Guard allows (the added material must overlap no neighbour,
    keep 5 mm from the hoses and 2 mm from hardware it was not already as close to, and stay out of the holes' walls)."""
    if ROUND is None:
        return solid
    key = ("junction", name, label, round(solid.Volume(), 2), tuple(round(x, 2) for x in bbox_of(solid)), tuple(sides), tuple(radii or ()))
    return ROUND.remembered(key, lambda: _junction_fillet(solid, name, label, pick, sides, own, rings, extra, radii))


def _junction_fillet(solid, name, label, pick, sides, own, rings, extra, radii):
    radii = radii or [round(8.0 - 0.5 * k, 3) for k in range(13)]
    table = rd.edge_table(solid)
    edges = [e for e, fs in table if rd.is_concave(solid, e, fs) and pick(e)]
    where = tuple(round(float(x), 2) for x in edge_info(edges[0])[0]) if edges else (0.0, 0.0, 0.0)
    who = f"{name}: {label}" + (f" ({len(edges)} edges)" if len(edges) > 1 else "")
    if not edges:
        ROUND_LOG.append(rd.Entry(who, where, "junction", 0.0, 0.0, "no concave edge found there"))
        return solid
    guard = ROUND.guard((0.0, 0.0, 0.0), rings, own, sides, extra)

    def trial(k):
        try:
            new = solid.fillet(radii[k], edges)
        except Exception as exc:      # noqa: BLE001 - the kernel refusing a fillet is an ordinary outcome here
            return None, f"the kernel could not fillet it ({type(exc).__name__})"
        if not new.isValid() or len(new.Solids()) != 1:
            return None, "the kernel returned an invalid solid"
        added = new.cut(solid)
        ok, why = guard.judge("concave", added)
        return (new if ok else None), why

    best = rd.largest_passing(len(radii), trial)
    if best is None:
        ROUND_LOG.append(rd.Entry(who, where, "junction", 0.0, 0.0, trial(0)[1]))
        return solid
    ROUND_LOG.append(rd.Entry(who, where, "junction", 0.0, radii[best], "" if best == 0 else (trial(best - 1)[1] or "largest radius that fits")))
    return trial(best)[0]


def round_box(solid, bounds, axis, name, specs, *, place=None, rings=(), rmax=BOX_R):
    """Round the long edges of an axis-aligned box. specs: [(hi_i, hi_j, a0, a1, why)]: one per section corner to round,
    the stretch along the axis, and why it is not rounded (None = round it). `place` moves a cutter from the box's own frame
    to where the box stands (board space). Radius BOX_R, then down to ROUND_MIN if the cutter would enter a hole's wall ring."""
    if ROUND is None:
        return solid
    i, j = [k for k in range(3) if k != axis]
    for (hi_i, hi_j, a0, a1, why) in specs:
        corner = [0.0, 0.0, 0.0]
        corner[axis], corner[i], corner[j] = (a0 + a1) / 2, bounds[1 if hi_i else 0][i], bounds[1 if hi_j else 0][j]
        pt = tuple(round(float(x), 2) for x in (corner if place is None else place(Vertex.makeVertex(*corner)).toTuple()))
        if why:
            ROUND_LOG.append(rd.Entry(name, pt, "edge", 90.0, 0.0, why))
            continue
        r, done, bad = rmax, False, ""
        while r >= ROUND_MIN - 1e-9:
            w = corner_wedge(bounds, axis, hi_i, hi_j, r, a0, a1)
            if place is not None:
                w = place(w)
            hit = next((x for x in rings if w.intersect(x).Volume() > 0.01), None)
            if hit is None:
                solid = solid.cut(w)
                done = True
                break
            bad = "the rounding would cut into a hole's wall"
            r = round(r - 0.5, 6)
        ROUND_LOG.append(rd.Entry(name, pt, "edge", 90.0, r if done else 0.0,
                                  "" if done and r >= rmax - 1e-9 else bad))
    return solid.clean()


# ---------------------------------------------------------------------------
# Holes: every cutter that makes an insert pilot or a clearance hole is a Hole record, so the
# checks can measure the solid at the hole instead of trusting the code that cut it.
# ---------------------------------------------------------------------------
OVERSHOOT = 0.5          # a cutter starts this far outside the face it enters
# clearance hole kinds: (diameter, minimum wall around it). M5 has no insert in the plan; it takes the M4 wall.
CLEAR_KINDS = {
    "M3c": (hw.M3_CLEAR_D, hw.M3_MIN_WALL),      # also 6-32
    "M4c": (hw.M4_CLEAR_D, hw.M4_MIN_WALL),
    "M5c": (hw.M5_CLEAR_D, hw.M4_MIN_WALL),
}


def _unit(d):
    L = math.sqrt(sum(c * c for c in d))
    return tuple(c / L for c in d)


@dataclass
class Hole:
    """A cylindrical cutter: starts at `start`, runs along unit vector `d` for `length`."""
    kind: str                # "M3", "M4", "M4S" (insert pilots) or "M3c", "M4c", "M5c" (clearance)
    start: tuple
    d: tuple
    r: float
    length: float
    wall: float              # minimum wall the insert / screw needs around the hole
    pilot: bool
    solid: object = None
    _spans: tuple = None     # (blank, spans) cache

    def __post_init__(self):
        if self.solid is None:
            self.solid = cyl(self.start, self.d, 2 * self.r, self.length)

    def point(self, t):
        return tuple(s0 + t * c for s0, c in zip(self.start, self.d))

    def screw_r(self):
        """Radius the 4 mm of flat contact around a screw (revision 8a) is measured from: the insert's pilot, which is what the screw's
        other half has, so both parts of a joint judge the same screw with the same reach."""
        twin = {"M4c": hw.M4_PILOT_D / 2, "M3c": hw.M3_PILOT_D / 2}
        return max(self.r, twin.get(self.kind, 0.0))

    def mirrored(self):
        return Hole(self.kind, (-self.start[0], self.start[1], self.start[2]),
                    (-self.d[0], self.d[1], self.d[2]), self.r, self.length, self.wall, self.pilot)

    def moved(self, dx, dy, dz):
        return Hole(self.kind, (self.start[0] + dx, self.start[1] + dy, self.start[2] + dz),
                    self.d, self.r, self.length, self.wall, self.pilot)

    def describe(self):
        p = self.point(OVERSHOOT)
        return (f"{self.kind} {'pilot' if self.pilot else 'clearance'} at ({p[0]:.1f}, {p[1]:.1f}, {p[2]:.1f}) "
                f"along ({self.d[0]:.2f}, {self.d[1]:.2f}, {self.d[2]:.2f})")


def pilot(org, d, kind):
    """Insert pilot starting at the part face point `org`, going into the material along d."""
    dia, depth, wall = hw.INSERTS[kind]
    d = _unit(d)
    start = tuple(o - OVERSHOOT * c for o, c in zip(org, d))
    return Hole(kind, start, d, dia / 2.0, depth + OVERSHOOT, wall, True)


def clear_hole(kind, start, d, length):
    dia, wall = CLEAR_KINDS[kind]
    return Hole(kind, tuple(start), _unit(d), dia / 2.0, length, wall, False)


# ---------------------------------------------------------------------------
# Rib outlines (Y, Z)
# ---------------------------------------------------------------------------
P_DIAG0 = hw.bp_yz(-10, -20)
P_DIAG1 = hw.bp_yz(280, -20)

FOOT_W = 20.0
SHAPE_A = [
    Cap((hw.ENVELOPE_Y0 + FOOT_W / 2, -5), (40, -5), FOOT_W),    # foot pad; the plan starts it at Y 8, which is 2 mm in front of the fans
    Cap((40, -5), P_DIAG0, 20),                      # web (deviation, see report)
    Cap(P_DIAG0, P_DIAG1, 28),                       # diagonal under the board
    Cap((195, 136), (195, -3), 22),                  # mid leg
    Cap((188, -5), (212, -5), 20),                   # mid leg foot
]
REST_W = 16.0           # gpu_rest finger width; its upper face is the card's lower face (u = GPU_BS[2])
REST_U = hw.GPU_BS[2] - REST_W / 2
SHAPE_A_REST = [Cap(hw.bp_yz(REST_U, -10), hw.bp_yz(REST_U, 104), REST_W)]   # gpu_rest, right only

# board beams: three rows, section n BEAM_N0..tray, half-width in u
BEAM_N0 = -28.5
BEAM_N_MID = (BEAM_N0 + hw.ATX_TRAY_N) / 2
# section extent in u, as offsets from the row (the standoff bosses stay on the row). beam_top is 20 wide as before but
# moved 3.5 mm down-slope, away from the 420's core face at u = RAD420_BS[2] (revision 6): u row - 13.5 .. row + 6.5.
BEAM_SPAN = {"beam_low": (-10.0, 10.0), "beam_mid": (-15.0, 15.0), "beam_top": (-13.5, 6.5)}
BEAM_ROW = dict(zip(("beam_low", "beam_mid", "beam_top"), hw.ATX_ROWS_U))
BEAM_TOP_END = hw.bp_yz(BEAM_ROW["beam_top"], BEAM_N_MID)     # (Y, Z) of rib_B's boss for beam_top's end bolts (column at u = row)
IO_CLEAR = 2.0          # nose of rib_B is trimmed to stay this far from the I/O keep-out

# Cradle for the 420, which stands at 90 deg to the board: its underside is the plane n = RAD420_BS[4] (a 45 deg face
# rising to the back); the cradle's top is the plane n = CRADLE_N, 3 mm below it for a rubber pad. The post is carried
# up to that plane and on to POST_REAR_Y at the height where it ends, so that the antler tongue has material behind it.
CRADLE_PAD = 3.0
CRADLE_N = hw.RAD420_BS[4] - CRADLE_PAD
CRADLE_U = (hw.RAD420_BS[2] + 2.0, 364.0)      # plan: u 312..376. Rear end at 364: rib_B would be 298 mm tall, 290 allowed
POST_REAR_Y = 348.0
P_CRADLE0 = hw.bp_yz(CRADLE_U[0], CRADLE_N)
P_CRADLE1 = hw.bp_yz(CRADLE_U[1], CRADLE_N)
POST = Poly([(P_CRADLE0[0], -5), P_CRADLE0, P_CRADLE1, (POST_REAR_Y, P_CRADLE1[1]), (POST_REAR_Y, -5)])
SHAPE_B = [
    Cap((200, -5), (372, -5), 20),                   # runner
    POST,                                            # post with the cradle on top
    Cap((326, 226), (266, 212), 28),                 # nose
    Cap((373, -5), (373, 88), 18),                   # tail post
    Disc(BEAM_TOP_END, 19),                          # local boss for beam_top's end bolts (24 until the 420 stood up: it came within 0.05 mm)
]

# lap joints: (zone box Y0, Y1, Z0, Z1), A keeps inner half, B outer half where A is present
LAP_ZONES = [(250.0, 300.0, 190.0, 245.0), (185.0, 225.0, -16.0, 10.0)]
LAP_BOLTS = [(262.0, 205.0), (268.0, 210.0), (212.0, -5.0)]       # (Y, Z)
LAP_KIND = "M4S"

# cross-member end bolts (Y, Z)
def _yz(u, n):
    return hw.bp_yz(u, n)


def _beam_bolts(name):
    row = BEAM_ROW[name]
    if name == "beam_top":     # one column of two, stacked in n, on the row: the section now reaches 6.5 up-slope and 13.5 down-slope of it
        return [_yz(row, BEAM_N_MID - 4.9), _yz(row, BEAM_N_MID + 4.9)]
    return [_yz(row - 5.0, BEAM_N_MID), _yz(row + 5.0, BEAM_N_MID)]


# PSU bulkhead plate sits on the PSU's IEC face
BULK_T = 6.0
BULK_Y0, BULK_Y1 = hw.PSU_REAR_Y - BULK_T, hw.PSU_REAR_Y + BULK_T      # end bosses; plate is PSU_REAR_Y..BULK_Y1
BULK_Z = (hw.DESK_Z, hw.PSU_W[5] + 6.0)
# 360 visor arm: plate centred on the outer hole column, 12 thick; bar n RAD360_INNER_N-14 .. RAD360_INNER_N
RAD360_X_ARM = max(hw.RAD360_HOLES_X)
ARM_HALF_T = 6.0
ARM_T = 14.0
ARM_U0 = 186.0
ARM_MID_N = hw.RAD360_INNER_N - ARM_T / 2           # mid-thickness of the arm: the n of the radiator screws' mount points
HOSE_CLEAR = 5.0         # required gap between a frame part and the hose keep-outs (check 9)
# Neck: a straight strut along n, 3 mm clear of the 420's core face, |X| 180..192, stopping 2 mm under the 360's inner face.
NECK_X = (180.0, 192.0)
NECK_U1 = hw.RAD420_BS[2] - 3.0
NECK_U = (NECK_U1 - 23.0, NECK_U1)                 # 284..307; plan 287..307 (centred on u = 297), see DEVIATIONS (the joint bolts need it)
NECK_N = (-58.0, hw.RAD360_INNER_N - 2.0)          # plan: n -30..115; lower end moved to -58, upper end 120, see DEVIATIONS
# Arm-to-neck joint (revision 6, no hinge): two M4 bolts along X, insert pilots (M4S) in the arm, clearance holes in the neck.
# The arm's radiator screw at u = RAD360_HOLES_U[1] runs along n through the whole bar, so a bolt there would cross it:
# the bolts keep 6.9 mm from it (pilot Ø5.6 + 2.1 wall + the screw hole's radius 2.0) and 4.35 mm inside the neck's u edge.
# That leaves u 288.35..290.1 only, so the two bolts are spread along n instead: the arm gets a knee below its bar.
JOINT_U = 289.2
JOINT_MIN_SPACING = 20.0
JOINT_N = (hw.RAD360_INNER_N - 8.0, hw.RAD360_INNER_N - 28.5)         # n 114 and 93.5: 20.5 apart
KNEE_U = (NECK_U[0], JOINT_U + 5.3)                # arm tab below the bar, 284..294.5; the radiator screw's hole at u 297 stays clear of it
KNEE_N0 = JOINT_N[1] - 5.5                         # n 88
ARM_NOTCH_U = (hw.RAD360_PORTS_BS[2] - 1.0, hw.RAD360_PORTS_BS[3] + 1.0)      # 1 mm clear of the port keep-out at both ends
ARM_NOTCH_X = hw.RAD360_PORTS_BS[0] + hw.ORIGIN[0] - 1.0  # world X of the arm's outer face where it passes the right-hand tank (1 mm gap)
PAD_N = (NECK_N[0], -22.0)                         # spacer pad between rib_B and the neck, same u as the strut
END_BOLTS = {
    "beam_front":   [(10.0, 0.0), (30.0, 0.0)],
    "beam_low":     _beam_bolts("beam_low"),
    "beam_mid":     _beam_bolts("beam_mid"),
    "beam_top":     _beam_bolts("beam_top"),
    "skid_front":   [(197.0, -5.0)],
    "skid_rear":    [(330.5, -5.0), (339.5, -5.0)],
    "psu_bulkhead": [(hw.PSU_REAR_Y, 5.0), (hw.PSU_REAR_Y, 80.0)],
}
END_KIND = {"beam_mid": "M4S"}      # the gpu_post bolts need the short insert
HOLDING_RIB = {      # which rib outline(s) the bolt must lie inside
    "beam_front": ("A",), "beam_low": ("A",),
    "beam_mid": ("A",), "beam_top": ("B",), "skid_front": ("A", "B"),
    "skid_rear": ("B",), "psu_bulkhead": ("B",),
}

NECK_BOLTS = [hw.bp_yz(sum(NECK_U) / 2, n) for n in (-34.0, -52.0)]      # (Y, Z), along X through pad + neck into rib_B's post
TONGUE_BOLTS = [hw.bp_yz(350.0, n) for n in (-30.0, -46.0)]               # (Y, Z), along X through the antler tongue into rib_B's post
GPU_POST_U0 = hw.GPU_BS[2] - 2.6       # under the card's bracket end, 2.6 mm past its lower face
GPU_POST_BS = (-20, -5.5, GPU_POST_U0, 146, hw.ATX_TRAY_N, hw.GPU_BRACKET_TAB_N)
GPU_POST_V = -10.5
GPU_POST_U = (131.0, 139.0)

GUIDE_PARTS = ("hose_guide_cpu", "hose_guide_gpu")
GUIDE_HOSE = {"hose_guide_cpu": "cpu_hoses", "hose_guide_gpu": "gpu_hoses"}     # the keep-out a guide is exempt from in check 2
GUIDE_LEN = 12.0          # along the hose
GUIDE_PLAY = 0.3          # channel diameter = hose diameter + 0.6: radius = the true hose radius + this (revision 6)
GUIDE_MOUTH = 0.75        # the open side is this x the hose diameter wide, so the hose snaps in
GUIDE_RIM = 2.5           # material around a channel, in n
GUIDE_WALL_MIN, GUIDE_WALL_MAX = 0.2, 0.5     # check 10: channel wall to the true hose, mm
GUIDE_T = 10.0            # plate thickness on the neck / rib face
GUIDE_CPU_U = (274.0, 274.0 + GUIDE_LEN)       # on the last straight run into the 420's port (its keep-out ends at u 288)
GUIDE_CPU_FOOT_U = (272.0, 300.0)              # the foot reaches over the neck, which starts at u 284
GUIDE_CPU_BOLT_U = 294.0
GUIDE_GPU_U = (166.0, 166.0 + GUIDE_LEN)       # on the up-slope run behind the board, where both hoses are straight
GUIDE_GPU_BOLT_N = -20.0                       # on rib_A's diagonal, whose axis is n = -20
GUIDE_GPU_PLATE_N1 = -6.0

# Side fans (revision 7). Each 140 mm fan is screwed to a printed bracket by its corner holes (M4S inserts in the bracket, screws
# from the fan's outer face) and the bracket is bolted to that side's rib_A. The bracket lies on the fan's inner face (the
# side towards the board) as a plate, BRACKET_T thick. Its outline is a C: a spine along n just outside the fan's open
# circle on the low-u side, an ear under each screw it uses, a bar along the low-n edge when the fan's B corner is used,
# and a leg that carries it across the gap to the rib's outer face. No part of it enters the circle (check 11).
BRACKET_T = 10.0                                          # plate thickness along X
BRACKET_EAR = hw.M4S_PILOT_D / 2 + hw.M4S_MIN_WALL        # half-side of the ear around a pilot: 4.9
_AP_R = hw.FAN_APERTURE_D / 2
BRACKET_SPINE_U = (116.0, hw.FAN_CENTRE_UN[0] - _AP_R - 1.0)       # 116..122: 1 mm outside the circle, whose low-u point is u 123
BAR_N = (hw.FAN_CENTRE_UN[1] - _AP_R - 0.5 - 7.5, hw.FAN_CENTRE_UN[1] - _AP_R - 0.5)   # -47..-39.5: 0.5 mm under the circle, 7.5 wide
BRACKET_LEG_U = (116.0, 127.0)                            # the leg's footprint on the rib: u 116..127, n -34..-6 = the diagonal's full width
BRACKET_LEG_N = (-34.0, -6.0)
BRACKET_BOLT_U = 121.0                                    # two M4 along X through rib_A into the leg, stacked in n
BRACKET_BOLT_N = (-26.0, -14.0)
BRACKET_BOLTS = [hw.bp_yz(BRACKET_BOLT_U, n) for n in BRACKET_BOLT_N]      # (Y, Z), the same on both ribs
# the corners each bracket screws to from the fan's inner face. A and C only on the right: B and D are within 4.1 mm of gpu_hoses
# (needs 5), see DEVIATIONS; the right bracket reaches D from the outside instead (BRACKET_TAB, revision 7a)
BRACKET_CORNERS = {"fan_bracket_left": ("A", "B", "C"), "fan_bracket_right": ("A", "C")}
BRACKET_FAN = {"fan_bracket_left": "fan_side_left", "fan_bracket_right": "fan_side_right"}
# Revision 7a: the right bracket reaches a third corner from OUTSIDE. A rail runs along the outside of the fan's top edge (n 98.5..104,
# in the fan's own thickness, RAIL_INSET short of the fan's inner face so it keeps clear of the hoses that rise just inside) up-slope
# to RAIL_U1, and ends in a tab folded over the fan's outer face at corner D. The fan screw goes in from outside through the tab's
# clearance hole. Nothing passes |X| = 229.
BRACKET_TAB = {"fan_bracket_right": "D"}                  # bracket -> the corner it reaches over the fan's outer face
RAIL_N = (hw.FAN_SIDE_N[1] + 0.5, hw.FAN_SIDE_N[1] + 6.0)  # 98.5..104: 0.5 mm clear of the fan's top edge, 5.5 wide
RAIL_INSET = 1.0                                          # the rail's inboard face stands this far outside the fan's inner face
RAIL_U1 = hw.FAN_SIDE_U[1] + 2.0                          # 262
TAB_T = 2.5                                               # tab thickness along X
TAB_WALL = 4.0                                            # material around the tab's clearance hole
RAIL_GROUP = ("root", "rail", "knuckle", "tab")
RAIL_CONVEX: dict = {"rail": 2.0}                         # the rail is 5.5 wide: a 6 mm radius would eat the whole end of it and the joint to the root block
BRACKET_RAIL_X = hw.FAN_SIDE_INNER_X["fan_side_right"]              # |X| beyond the plate (X 191..201): the rail group
FAN_PILOT_KIND = "M4S"
FAN_MIN_SCREWS = 3                                        # revision 7: at least three of the four corner holes
FASTENERS: list[dict] = []
BOLT_CHECKS: list[tuple] = []     # (label, ok, detail)


def fastener(item, part, kind, count, note=""):
    FASTENERS.append(dict(item=item, part=part, kind=kind, count=count, note=note))


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------
@dataclass
class Part:
    name: str
    solid: object             # the printed shape, holes drilled
    note: str
    holes: list = field(default_factory=list)      # Hole records in this part's own (left or right) coordinates
    blank: object = None      # the shape before any hole is cut (window and lap cuts applied)
    holds: str = ""
    material: str = "ABS"     # ABS or PA6 (revision 9); the PLA layer is not in this file


def drill(blank, holes, extra_cuts=()):
    """Cut every hole (and any other cutter) out of the blank. Returns (solid, holes, blank)."""
    blank = cut_all(blank, extra_cuts)
    return cut_all(blank, holes), list(holes), blank


def lap_cut_boxes(half: str, with_rest: bool = True):
    """Boxes removed from A (outer half) or B (inner half, only where A is) inside the lap zones. B follows the rib A it
    laps with (`with_rest`: the right one), as rounded, so the two halves still fit."""
    out = []
    a_slab = _A_LAYER.get(with_rest)
    if a_slab is None:
        a_slab = outline_solid(SHAPE_A, X_IN - 1, X_MID)
    for (y0, y1, z0, z1) in LAP_ZONES:
        if half == "A":
            out.append(hw.wbox(X_MID, X_OUT + 1, y0, y1, z0, z1))
        else:
            out.append(hw.wbox(X_IN - 1, X_MID, y0, y1, z0, z1).intersect(a_slab))
    return out


def x_clear(y, z, x0=X_IN - OVERSHOOT, x1=X_OUT + OVERSHOOT, kind="M4c"):
    return clear_hole(kind, (x0, y, z), (1, 0, 0), x1 - x0)


def end_pilot_holes(name):
    """Pilots in a cross member's end faces (X = +-142), along X."""
    kind = END_KIND.get(name, "M4")
    holes = []
    for (y, z) in END_BOLTS[name]:
        holes.append(pilot((X_IN, y, z), (-1, 0, 0), kind))
        holes.append(pilot((-X_IN, y, z), (1, 0, 0), kind))
    return holes


def rib_a_holes(with_rest: bool):
    holes = []
    for name, pts in END_BOLTS.items():
        if "A" in HOLDING_RIB[name]:
            holes += [x_clear(y, z) for (y, z) in pts]
    for (y, z) in LAP_BOLTS:      # insert pilots in the inner half, from the X = 150 face
        holes.append(pilot((X_MID, y, z), (-1, 0, 0), LAP_KIND))
    for (y, z) in BRACKET_BOLTS:  # fan bracket bolts: clearance through the rib, the insert is in the bracket's leg
        holes.append(x_clear(y, z))
    if with_rest:                 # right rib only: the GPU hose guide's bolt, into the outer face
        holes.append(pilot((X_OUT, *guide_gpu_bolt()), (-1, 0, 0), "M4"))
        holes += tie_pilots("rib_A_right")     # the cable tie points under the rail (the diagonal's underside)
    holes += organic_pilots("rib_A_right" if with_rest else "rib_A_left", mirrored=not with_rest)     # the organic layer's pads, on the outer face
    return holes


def build_rib_a(with_rest: bool):
    prims = SHAPE_A + (SHAPE_A_REST if with_rest else [])
    name = "rib_A_right" if with_rest else "rib_A_left"
    holes = rib_a_holes(with_rest)
    cuts = lap_cut_boxes("A")
    s = outline_solid(prims, X_IN, X_OUT)
    s = rounded_like(s, (1, 0, 0), name, sides=(1,) if with_rest else (-1,), own=(name,),
                     rings=hole_rings(holes), post_cuts=cuts)
    _A_LAYER[with_rest] = s
    return drill(cut_all(s, cuts), holes)


def build_rib_b(side=1):
    name = "rib_B_right" if side > 0 else "rib_B_left"
    s = outline_solid(SHAPE_B, X_IN, X_OUT)
    # keep the nose out of the I/O keep-out: trim everything above n = io n0 - IO_CLEAR (before rounding, so the trim's corners are rounded too)
    v0, v1 = hw.x_to_v(X_IN - 1), hw.x_to_v(X_OUT + 1)
    io_v0, io_v1, io_u0, io_u1, io_n0, io_n1 = hw.IO_ZONE_BS
    s = s.cut(hw.bs_box(v0, v1, io_u0, io_u1, io_n0 - IO_CLEAR, io_n1))
    holes = []
    for name_, pts in END_BOLTS.items():
        if "B" in HOLDING_RIB[name_]:
            holes += [x_clear(y, z) for (y, z) in pts]
    for (y, z) in LAP_BOLTS:      # clearance through the outer half
        holes.append(x_clear(y, z, X_MID - 0.3, X_OUT + OVERSHOOT))
    for (y, z) in TONGUE_BOLTS:   # antler tongue, along X into the post's outer face
        holes.append(pilot((X_OUT, y, z), (-1, 0, 0), "M4"))
    for (y, z) in NECK_BOLTS:     # neck pad, along X into the post's outer face
        holes.append(pilot((X_OUT, y, z), (-1, 0, 0), "M4"))
    holes += organic_pilots(name, mirrored=side < 0)      # the organic layer's pads, on the outer face
    if side > 0:                  # right rib only, like the rail's: the cable tie points on the inner face (the PSU's cables run on the right)
        holes += tie_pilots("rib_B_right")
    cuts = lap_cut_boxes("B", side > 0)
    # revision 8a: the ends of the cradle surface are rounded like any other outside corner (the pad is not a listed contact)
    s = rounded_like(s, (1, 0, 0), name, sides=(1,) if side > 0 else (-1,), own=(name,),
                     rings=hole_rings(holes), post_cuts=cuts)
    return drill(cut_all(s, cuts), holes)


def bs_place(shape):
    """A shape built in board-space axes (v, u, n) as (x, y, z), moved to where it stands: the placement bs_box applies."""
    return shape.rotate(Vector(0, 0, 0), Vector(1, 0, 0), hw.TILT_DEG).translate(Vector(*hw.ORIGIN))


def all_corners(a0, a1, skip=None):
    """round_box specs for the four section corners of a member from a0 to a1; skip = {(hi_i, hi_j): why}."""
    skip = skip or {}
    return [(hi_i, hi_j, a0, a1, skip.get((hi_i, hi_j))) for hi_i in (False, True) for hi_j in (False, True)]


BEAM_FRONT_Y, BEAM_FRONT_Z = (0.0, 40.0), (-10.0, 10.0)      # beam_front's section (the sill stands on its top face)

# Front sill (revision 9): a bar across X -SILL_HALF_X..SILL_HALF_X on beam_front, its face a plane parallel to the board (45 deg), with a pocket
# for hw front_io, a channel for hw light_strip and a slit from the channel to the face. Wall thicknesses are the part's own numbers; where the
# module and the strip are is hardware.py's (placeholders until the module is measured).
SILL_HALF_X = 140.0
SILL_FACE_WALL = 5.0          # material between the module (and the channel) and the face, normal to it: the skin the port cut-outs will go through
SILL_TOP_WALL = 10.0          # behind the channel along the face, so the ridge can take a 6 mm rounding and keep SILL_RING_WALL
SILL_REAR_WALL = 5.0          # behind the pocket
SILL_POCKET_PLAY = 0.4        # the pocket is the module's box plus this on the ends, the rear and the top (it is open at the front and at the bottom)
SILL_CHANNEL_PLAY = 0.3       # the channel is the strip's box plus this on every side, and runs through both ends of the sill
SILL_RING_WALL = 3.0          # a rounding keeps this much material round the channel
SILL_BOLTS = [(-105.0, 10.0), (-105.0, 30.0), (118.0, 10.0), (118.0, 30.0)]      # (X, Y): M4 from below, clearance through beam_front, pilot in the sill
SILL_PROBE_DEPTH = 3.0        # check 5: the axis point of a module screw lies this far into the wall of the pocket
# Cable window (skeleton pass 1): one opening through the rear wall for the module's front cables (USB 3, USB-C, power switch, audio). PLACEHOLDER like the
# module it follows: its numbers are offsets from hw.FRONT_IO_W, so it moves with the module when the real one is measured. The light line's lead
# needs no window of its own: the channel is open through both ends of the sill (see the notes).
SILL_WINDOW_INSET = 5.0       # the window ends this far inside the module's right end
SILL_WINDOW_W = 50.0          # its width along X
SILL_WINDOW_Z_LOW = 4.0       # its lower edge above the module's underside (the rear wall keeps this strip under it)
SILL_WINDOW_Z_TOP = 0.0       # its upper edge above the module's top (it stays under the pocket's roof, which is SILL_POCKET_PLAY higher)
SILL_WINDOW_R = ROUND_CONCAVE  # its four corners are inside corners of the wall: the concave radius


def sill_geometry():
    """Everything about the sill that follows from hardware.py's module and strip: the section (Y, Z) polygon, the cutters, the ring."""
    z0 = BEAM_FRONT_Z[1]
    io, ls = hw.FRONT_IO_W, hw.LIGHT_STRIP_BS
    y_rear = io[3] + SILL_POCKET_PLAY + SILL_REAR_WALL
    n_pocket = hw.bs_of(0.0, hw.ENVELOPE_Y0, io[5] + SILL_POCKET_PLAY)[2]       # the pocket's top front edge, along the board's normal
    n_face = max(n_pocket, ls[5] + SILL_CHANNEL_PLAY) + SILL_FACE_WALL
    u_top = ls[3] + SILL_CHANNEL_PLAY + SILL_TOP_WALL
    u_front = n_face + (hw.ENVELOPE_Y0 - hw.ORIGIN[1]) / hw.C               # the face reaches the front plane Y = ENVELOPE_Y0 here
    n_rear = u_top - (y_rear - hw.ORIGIN[1]) / hw.C                          # the back slope (u = u_top) reaches the rear plane here
    pts = [(hw.ENVELOPE_Y0, z0), hw.bp_yz(u_front, n_face), hw.bp_yz(u_top, n_face), hw.bp_yz(u_top, n_rear), (y_rear, z0)]
    v0, v1 = hw.x_to_v(-SILL_HALF_X - 1.0), hw.x_to_v(SILL_HALF_X + 1.0)
    u_c = (ls[2] + ls[3]) / 2
    wx1 = io[1] - SILL_WINDOW_INSET
    window_xz = (wx1 - SILL_WINDOW_W, wx1, io[4] + SILL_WINDOW_Z_LOW, io[5] + SILL_WINDOW_Z_TOP)
    window = hw.wbox(window_xz[0], window_xz[1], io[3] + SILL_POCKET_PLAY - 1.0, y_rear + 1.0, window_xz[2], window_xz[3])
    window = window.fillet(SILL_WINDOW_R, [e for e in window.Edges() if abs(e.startPoint().x - e.endPoint().x) < 1e-6 and abs(e.startPoint().z - e.endPoint().z) < 1e-6])
    cuts = dict(
        pocket=hw.wbox(io[0] - SILL_POCKET_PLAY, io[1] + SILL_POCKET_PLAY, hw.ENVELOPE_Y0 - 1.0, io[3] + SILL_POCKET_PLAY, z0 - 1.0, io[5] + SILL_POCKET_PLAY),
        channel=hw.bs_box(v0, v1, ls[2] - SILL_CHANNEL_PLAY, ls[3] + SILL_CHANNEL_PLAY, ls[4] - SILL_CHANNEL_PLAY, ls[5] + SILL_CHANNEL_PLAY),
        slit=hw.bs_box(ls[0], ls[1], u_c - hw.LIGHT_LINE_W / 2, u_c + hw.LIGHT_LINE_W / 2, ls[5] - 1.0, n_face + 1.0),
        window=window)
    ring = hw.bs_box(v0, v1, ls[2] - SILL_CHANNEL_PLAY - SILL_RING_WALL, ls[3] + SILL_CHANNEL_PLAY + SILL_RING_WALL,
                     ls[4] - SILL_CHANNEL_PLAY - SILL_RING_WALL, ls[5] + SILL_CHANNEL_PLAY + SILL_RING_WALL)
    return dict(z0=z0, pts=pts, cuts=cuts, ring=ring, n_face=n_face, u_top=u_top, y_rear=y_rear, window_xz=window_xz)


def organic_pilots(name, mirrored=False):
    """M3 insert pilots for the organic layer's pads on part `name` (hw.ORGANIC_PADS), along X into the part from the pad's centre on its outer face.
    mirrored: the part is built right-handed and mirrored afterwards (the left ribs and neck), so the pilots go in its own coordinates."""
    k = -1.0 if mirrored else 1.0
    return [pilot((k * x, y, z), (-k * s, 0.0, 0.0), "M3") for (part, (x, y, z), s) in hw.ORGANIC_PADS.values() if part == name]


# ---------------------------------------------------------------------------
# Cable tie points (skeleton pass 2, docs/plans/cables-and-organic.md "Cable fixing"). A tie point is an M3 insert pilot in the underside of
# a beam or of the right rib's rail; one printed part, tie_bridge (ABS since 16 Nov 2026: a hook-and-loop strap goes through it, nothing snaps or flexes), is screwed to it: a foot with an M3 clearance hole and, beside the
# hole, an arch whose slot a 12 mm hook-and-loop strap or a cable tie passes through. The shape is built once (in its own frame) and
# placed at every tie point; the cables are not looked at here, cables.py keeps its 3 mm from every bridge and reports the distances.
# ---------------------------------------------------------------------------
TIE_FOOT_T = 3.0              # the foot, which the screw's head bears on
TIE_HOLE_END = 5.5            # from the hole's axis to the foot's end (the M3 head is 5.5 across)
TIE_ARCH_START = 5.0          # the arch starts this far along from the hole's axis: a screwdriver clears the post
TIE_POST = 2.5                # the arch's two posts, along the foot
TIE_SLOT_W = 12.5             # the strap's width 12 + 0.5 play, along the foot
TIE_SLOT_H = 3.5              # the strap's thickness doubled (hook and loop) + play, above the foot
TIE_BAR_T = 2.5               # the arch's roof; 3 + 3.5 + 2.5 = 9 high
TIE_W = 13.0                  # across the foot, which is how far the strap runs through the arch; the beams' flat underside is 14 (20 less two 3 mm roundings)
TIE_ARCH_END = TIE_ARCH_START + 2 * TIE_POST + TIE_SLOT_W
TIE_H = TIE_FOOT_T + TIE_SLOT_H + TIE_BAR_T
TIE_FACE_N = {"beam_low": BEAM_N0, "beam_mid": BEAM_N0, "beam_top": BEAM_N0, "rib_A_right": -34.0}      # n of the underside a bridge stands on; the rail's is the diagonal's axis n -20 less half its 28 width
TIE_UNDER = tuple(-c for c in hw.N_DIR)                                                               # on an underside the bridge goes out along -n
_TIE_LOCAL: dict = {}


def tie_point(row, k, host, pt, normal, direction, face):
    """One tie point: `pt` is the world point of the hole's axis on the host's face, `normal` the unit vector out of that face (the bridge stands out along it, the pilot goes in
    along its opposite), `direction` the unit vector in the face from the hole to the arch (the foot's long side), `face` says which face in words."""
    assert abs(sum(a * b for a, b in zip(normal, direction))) < 1e-9, "a bridge's direction lies in its face"
    return dict(row=row, k=k, host=host, pt=tuple(float(c) for c in pt), normal=tuple(normal), dir=tuple(direction), face=face)


def _tie_points():
    """The tie points, in the order of their rows. Each has the world point of the hole's axis on its host's face, the face's outward normal and the direction to the arch.
    First pass (undersides: X, and u or the beam's middle): rows mid, rail (the right rib's rail), low, top. Second pass (docs/plans/cables-and-organic.md, "Tie points, second pass"):
    a tie point stays only if a cable (one of the six in cables.TIE_ROUTES) comes within cables.TIE_REACH of its strap slot, and new ones stand where a bend of 30 deg or
    more or a stretch of 150 mm needs one: rows leg (the inner face X 142 of rib A's mid leg), post (the inner face of rib B's post) and skid (the top of skid_front,
    a bridge that stands on the face and overhangs its front edge). The places were found by distance queries against the built solids and the routes (cables.py reports
    what each one serves); k is the first pass's number where the bridge is the same one, so the names stay."""
    centre = {b: BEAM_ROW[b] + sum(BEAM_SPAN[b]) / 2 for b in BEAM_ROW}         # u of the middle of each beam's flat underside (beam_top's section is not centred on its row)
    plus_x, minus_x, plus_u, minus_u = (1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), tuple(hw.U_DIR), tuple(-c for c in hw.U_DIR)
    rows = [("mid", "beam_mid", centre["beam_mid"], [(3, 84.0, plus_x)]),      # first pass's X 20 and 52 are gone: no cable within 30 mm of them
            ("rail", "rib_A_right", None, [(2, 149.0, minus_u, 103.0), (3, 149.0, plus_u, 185.0), (4, 149.0, plus_u, 216.0)]),   # first pass's u 72 is gone: the nearest cable is 33 mm away
            ("low", "beam_low", centre["beam_low"], [(1, 60.0, minus_x), (2, 102.0, minus_x)]),     # low_2 moved from X 90 (arch towards +X) to X 102 (towards -X): USB-C's dive is then 21 mm away, not 31
            ("top", "beam_top", centre["beam_top"], [(2, 109.0, plus_x)])]        # first pass's X 77 is gone: the nearest cable is 45 mm away
    out = []
    for name, host, u, pts in rows:
        for pt in pts:
            k, x, d = pt[0], pt[1], pt[2]
            out.append(tie_point(name, k, host, hw.bp(hw.x_to_v(x), pt[3] if u is None else u, TIE_FACE_N[host]), TIE_UNDER, d,
                                 "underside of the rail" if host == "rib_A_right" else "underside of the beam"))
    up = (0.0, 0.0, 1.0)
    inner = (-1.0, 0.0, 0.0)             # the inner faces of the right ribs, X 142, look towards -X
    out += [tie_point("leg", 1, "rib_A_right", (X_IN, 196.0, 36.0), inner, up, "inner face, mid leg"),        # ATX's 45 deg corner and EPS 1's 36 deg corner
            tie_point("leg", 2, "rib_A_right", (X_IN, 194.0, 72.0), inner, up, "inner face, mid leg"),        # USB 3's 90 deg corner at the foot of the gap
            tie_point("post", 1, "rib_B_right", (X_IN, 336.0, 104.0), inner, (0.0, -1.0, 0.0), "inner face, post"),      # the 90 deg corners of EPS 1 and EPS 2 at the foot of the gap
            tie_point("skid", 1, "skid_front", (102.0, 195.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0), "top face")]   # EPS 2 round the PSU's front corner: the foot overhangs the front edge (Y 185)
    return out


TIE_POINTS: list[dict] = _tie_points()


def tie_name(tp):
    return f"tie_bridge_{tp['row']}_{tp['k']}"


def tie_face_point(tp):
    """World point of the tie point's axis on the host's face."""
    return tp["pt"]


def tie_slot_centre(tp):
    """World point in the middle of a bridge's strap slot: where a strap or tie holds a cable, which cables.py measures its tie distances to."""
    x = TIE_ARCH_START + TIE_POST + TIE_SLOT_W / 2
    z = TIE_FOOT_T + TIE_SLOT_H / 2
    return tuple(p + x * a + z * n for p, a, n in zip(tp["pt"], tp["dir"], tp["normal"]))


def tie_bridge_local():
    """The bridge in its own frame, built once: origin on the hole's axis at the foot's underside, +z out of the host (the bridge's height), +x towards the arch,
    y across. No hole in it: the hole is cut where the bridge is placed. Printed foot down: the slot's roof is a 12.5 x 13 bridge 3 mm up, no overhang
    beyond that."""
    if "solid" not in _TIE_LOCAL:
        foot = Solid.makeBox(TIE_ARCH_END + TIE_HOLE_END, TIE_W, TIE_FOOT_T, Vector(-TIE_HOLE_END, -TIE_W / 2, 0))
        arch = Solid.makeBox(TIE_ARCH_END - TIE_ARCH_START, TIE_W, TIE_H - TIE_FOOT_T, Vector(TIE_ARCH_START, -TIE_W / 2, TIE_FOOT_T))
        slot = Solid.makeBox(TIE_SLOT_W, TIE_W + 2.0, TIE_SLOT_H, Vector(TIE_ARCH_START + TIE_POST, -TIE_W / 2 - 1.0, TIE_FOOT_T))
        _TIE_LOCAL["solid"] = foot.fuse(arch).cut(slot).clean()
    return _TIE_LOCAL["solid"]


def build_tie_bridge(tp):
    """tie_bridge placed at tie point `tp`: (solid with the hole, [Hole], blank)."""
    pt, normal = tie_face_point(tp), tp["normal"]
    plane = cq.Plane(origin=Vector(*pt), xDir=Vector(*tp["dir"]), normal=Vector(*normal))
    blank = tie_bridge_local().moved(cq.Location(plane))
    start = tuple(p + (TIE_FOOT_T + OVERSHOOT) * c for p, c in zip(pt, normal))
    hole = clear_hole("M3c", start, tuple(-c for c in normal), TIE_FOOT_T + 2 * OVERSHOOT)
    return drill(blank, [hole])


def tie_pilot_wall(host, tp):
    """The wall left round the tie point's pilot in part `host`: the thickest ring round the bore that is all material (to the surface or to the next hole), up to 8 mm."""
    pt = tie_face_point(tp)
    h = next(h for h in host.holes if h.pilot and h.kind == "M3" and math.dist(h.point(OVERSHOOT), pt) < 0.01 and max(abs(a + b) for a, b in zip(h.d, tp["normal"])) < 1e-6)
    spans = material_spans(host.blank, h)
    lo, hi = 0.0, 8.0
    for _ in range(9):
        mid = (lo + hi) / 2
        if wall_deficit(host.solid, h, spans, mid) > WALL_EPS:
            hi = mid
        else:
            lo = mid
    return lo


def tie_pilots(host):
    """The M3 insert pilots of the tie points on `host`, along n into the part from its underside."""
    return [pilot(tie_face_point(tp), tuple(-c for c in tp["normal"]), "M3") for tp in TIE_POINTS if tp["host"] == host]


def sill_holes():
    g = sill_geometry()
    holes = [pilot((x, y, g["z0"]), (0, 0, 1), "M4") for (x, y) in SILL_BOLTS]          # from beam_front's top face up into the sill
    for (pt, d) in hw.FRONT_IO_SCREWS:                                                    # the module's screws, along X into the pocket's end walls
        org = tuple(c + k * SILL_POCKET_PLAY for c, k in zip(pt, d))
        holes.append(pilot(org, d, hw.FRONT_IO_SCREW_KIND))
    holes += organic_pilots("front_sill")                                                 # the organic layer's two pads, on the end faces
    return holes


def build_front_sill():
    g = sill_geometry()
    holes = sill_holes()
    cuts = list(g["cuts"].values())
    prism = Poly(g["pts"]).solid(-SILL_HALF_X, SILL_HALF_X)
    rings = hole_rings(holes)
    rings.append(g["ring"])
    s = rounded_like(prism, (1, 0, 0), "front_sill", sides=(1,), own=("front_sill",), rings=rings, post_cuts=cuts)
    return drill(s, holes, cuts)


def build_beam_front():
    """The tie between the two front feet. Revision 9: the front sill and the module stand on its top face, so the top edges stay sharp (a
    contact face, as on the skids), and four M4 clearance holes from below carry the sill's bolts."""
    holes = end_pilot_holes("beam_front")
    z_lo, z_hi = BEAM_FRONT_Z
    holes += [clear_hole("M4c", (x, y, z_lo - OVERSHOOT), (0, 0, 1), z_hi - z_lo + 2 * OVERSHOOT) for (x, y) in SILL_BOLTS]
    lo, hi = (-X_IN, BEAM_FRONT_Y[0], z_lo), (X_IN, BEAM_FRONT_Y[1], z_hi)
    s = hw.wbox(lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])
    top = "the top face carries the front sill and the I/O module: rounding its edges would take contact area"
    s = round_box(s, (lo, hi), 0, "beam_front", all_corners(lo[0] + COLLAR, hi[0] - COLLAR, {(False, True): top, (True, True): top}),
                  rings=hole_rings(holes))
    return drill(s, holes)


def beam_holes(name):
    """Pilots into the standoff bosses, the end pilots, and (beam_mid) the gpu_post bolt clearance holes, in the order they were first cut."""
    row_u = BEAM_ROW[name]
    holes = []
    for (v, u) in hw.ATX_HOLES:
        if u == row_u:      # M3 insert pilots from the board underside down into the boss
            holes.append(pilot(hw.bp(v, u, hw.ATX_BOARD_N), [-c for c in hw.N_DIR], "M3"))
    holes += end_pilot_holes(name)
    holes += tie_pilots(name)      # the cable tie points, from the underside up into the beam
    if name == "beam_mid":     # clearance for the gpu_post bolts, along n through the beam
        for u in GPU_POST_U:
            holes.append(clear_hole("M4c", hw.bp(GPU_POST_V, u, BEAM_N0 - OVERSHOOT), hw.N_DIR, 22.0))
    return holes


def build_beam(name):
    row_u, (lo, hi) = BEAM_ROW[name], BEAM_SPAN[name]
    holes = beam_holes(name)
    v0, v1 = hw.x_to_v(-X_IN), hw.x_to_v(X_IN)
    s = hw.bs_box(v0, v1, row_u + lo, row_u + hi, BEAM_N0, hw.ATX_TRAY_N)
    s = round_box(s, ((v0, row_u + lo, BEAM_N0), (v1, row_u + hi, hw.ATX_TRAY_N)), 0, name,
                  all_corners(v0 + COLLAR, v1 - COLLAR), place=bs_place, rings=hole_rings(holes))
    bosses = []
    for (v, u) in hw.ATX_HOLES:
        if u == row_u:      # standoff boss, 1 mm sunk into the beam, up to the board underside
            bosses.append(Solid.makeCylinder(BOSS_R, 1.0 + hw.ATX_STANDOFF_H,
                                             Vector(*hw.bp(v, u, hw.ATX_TRAY_N - 1.0)),
                                             Vector(*hw.N_DIR)))
    s = fuse_all([s] + bosses)
    # the fillet's foot (boss radius + fillet radius) must stay on the beam's flat top, i.e. inside the 3 mm edge rounding
    r_top = min(hw.ATX_STANDOFF_H - 1.35, min(-lo, hi) - BOX_R - BOSS_R - 0.3)
    if r_top < ROUND_MIN:
        if ROUND is not None:
            ROUND_LOG.append(rd.Entry(f"{name}: boss meets beam", (0.0, 0.0, 0.0), "junction", 0.0, 0.0,
                                      f"a fillet of {ROUND_MIN:g} mm or more would reach past the start of the {BOX_R:g} mm edge rounding: the flat top is "
                                      f"{min(-lo, hi) - BOX_R:.1f} mm from the boss axis, the boss radius is {BOSS_R:g}"))
        return drill(s, holes)

    def pick(e):      # the boss's base circle on the beam's top face
        return e.geomType() == "CIRCLE" and abs(e.radius() - BOSS_R) < 1e-3 and abs(un_of(*np.array(e.arcCenter().toTuple())[1:])[1] - hw.ATX_TRAY_N) < 1e-2
    s = junction_fillet(s, name, "boss meets beam", pick, sides=(1,), own=(name,), rings=hole_rings(holes),
                        radii=[round(r_top - 0.5 * k, 3) for k in range(int((r_top - ROUND_MIN) / 0.5) + 1)])
    return drill(s, holes)


def build_skid(name, y0, y1):
    holes = end_pilot_holes(name) + tie_pilots(name)      # the cable tie points on the skid's top face (only skid_front has any)
    lo, hi = (-X_IN, y0, -10.0), (X_IN, y1, 0.0)
    s = hw.wbox(lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])
    top = "the top face carries the PSU: rounding its edges would take contact area"
    s = round_box(s, (lo, hi), 0, name, all_corners(lo[0] + COLLAR, hi[0] - COLLAR, {(False, True): top, (True, True): top}),
                  rings=hole_rings(holes))
    return drill(s, holes)


BOSS_R = 5.0               # standoff boss radius
BULK_BLOCK_X = 122.0       # the end blocks of the bulkhead start here
BULK_R = 2.75              # the plate is 6 mm thick: a radius of 3 would leave no flat on the edge
BULK_WINDOW = (-63.0, 63.0, 12.0, 74.0)      # X0, X1, Z0, Z1: IEC, switch and fan

# Drive sleds (docs/plans/cables-and-organic.md, "Drive bays, pass 1"). Where the drives stand and every hole pattern is hardware.py's (hw.drive_layout); what is here is
# the sled's own: a 5 mm plate in the YZ plane, a boss round each drive screw hole, a counterbore from the far face under each head, and a flange at the rear end
# that two M4 screws from behind (through the bulkhead's flank) hold. The foot is the plate's bottom face, flat, on skid_rear's top face.
SLED_FLOOR = 3.0                  # material left under each screw head, between the counterbore's floor and the drive's board: the screw then enters screw_len - 3.0 (3.35 for 6-32 x 6.35, 2.0 for M3 x 5)
SLED_BOSS_R = 4.5                 # boss radius round a hole
SLED_CB_PLAY = 0.8                # counterbore diameter = screw head + this
SLED_FRONT = 4.0                  # the plate starts this far in front of the outer drive's side edge
SLED_TOP_GAP = 5.0                # the plate stops this far under the drives' connector end (the plug zone is above that end)
SLED_FLANGE_Y = 13.0              # the flange's depth against the bulkhead's front face: the M4 pilot is 9.1 deep, 3.9 mm of floor
SLED_FLANGE_Z = (18.0, 88.0)      # its height: the bulkhead's rounded top edge starts at Z 89.25
SLED_FLANGE_HALF_X = 7.0          # its half width about the plate's mid-plane: the pilot's 5.6 plus 2 x 2.1 wall is 9.8
SLED_BOLT_Z = (30.0, 76.0)        # the two M4 screws along Y through the bulkhead's flank, stacked in Z
SLED_BOLT_KIND = "M4"
SLED_BOLT_X = sum(hw.drive_layout()["plate_x"]) / 2     # on the plate's mid-plane (right bay; the left is the mirror image)
SLED_ORDER = ("a sled that carries a 3.5 inch drive and an inner 2.5 inch drive takes the inner drive first: its screw heads end up under the 3.5 inch drive "
              "(the outer face's counterbores are covered by it, the heads stay below the face)")


def sled_holes():
    """(holes, counterbore cutters, probes) of one right-hand sled. holes: the clearance bores of the drive screws and the two M4 pilots in the flange. probes: per drive
    hole (face, form, y, z, bore start x, direction from the far face into the sled)."""
    lay = hw.drive_layout()
    px0, px1 = lay["plate_x"]
    holes, cuts = [], []
    for face, fc in lay["faces"].items():
        F = fc["spec"]
        far = px0 if face == "outer" else px1               # the face the screw comes in from: opposite to the drive
        d = fc["dir"]                                        # towards the drive's side: from the far face through the plate and the boss
        depth_cb = hw.DRIVE_PLATE_T + hw.DRIVE_BOSS_H - SLED_FLOOR
        for (y, z) in fc["holes"]:
            holes.append(clear_hole("M3c", (far - d * OVERSHOOT, y, z), (d, 0, 0), hw.DRIVE_PLATE_T + hw.DRIVE_BOSS_H + 2 * OVERSHOOT))
            cuts.append(cyl((far - d * OVERSHOOT, y, z), (d, 0, 0), F["head_d"] + SLED_CB_PLAY, depth_cb + OVERSHOOT))
    for z in SLED_BOLT_Z:
        holes.append(pilot((SLED_BOLT_X, hw.PSU_REAR_Y, z), (0, -1, 0), SLED_BOLT_KIND))
    return holes, cuts


def sled_bosses():
    lay = hw.drive_layout()
    px0, px1 = lay["plate_x"]
    out = []
    for face, fc in lay["faces"].items():
        base = px1 if face == "outer" else px0
        d = fc["dir"]
        for (y, z) in fc["holes"]:
            out.append(cyl((base - d * 0.5, y, z), (d, 0, 0), 2 * SLED_BOSS_R, hw.DRIVE_BOSS_H + 0.5))      # 0.5 mm sunk into the plate
    return out


def build_drive_sled(side=1):
    """One sled, built right-handed. side -1: the same, as the left one will be (mirrored by the caller); the rounding sees the mirror image of the neighbours."""
    name = "drive_sled_right" if side > 0 else "drive_sled_left"
    lay = hw.drive_layout()
    px0, px1 = lay["plate_x"]
    y_front = lay["faces"]["outer"]["body"][2] - SLED_FRONT
    holes, cuts = sled_holes()
    rings = hole_rings(holes)
    plate = Rect(y_front, hw.PSU_REAR_Y, 0.0, lay["z_top"] - SLED_TOP_GAP).solid(px0, px1)
    foot = "the foot's bottom face and the rear face against the bulkhead are contacts: this corner joins them and its rounding would take 30 mm2 from the bulkhead contact, which the bulkhead's own top edge has already cut by 1.3 %"
    plate = rounded_like(plate, (1, 0, 0), name, sides=(1,) if side > 0 else (-1,), own=(name,), rings=rings, keep=(((px0, hw.PSU_REAR_Y, 0.0), foot),))
    flange = Rect(hw.PSU_REAR_Y - SLED_FLANGE_Y, hw.PSU_REAR_Y, *SLED_FLANGE_Z).solid(SLED_BOLT_X - SLED_FLANGE_HALF_X, SLED_BOLT_X + SLED_FLANGE_HALF_X)
    lip = "the flange's rear face lies against the bulkhead: its two rear corners stay whole, the bulkhead's own top edge has already taken 1.3 % of the contact and the allowance is 3 %"
    fx = SLED_BOLT_X - SLED_FLANGE_HALF_X
    flange = rounded_like(flange, (1, 0, 0), name + " flange", sides=(1,) if side > 0 else (-1,), own=(name,), rings=rings,
                          keep=tuple(((fx, hw.PSU_REAR_Y, z), lip) for z in SLED_FLANGE_Z))
    s = fuse_all([plate, flange] + sled_bosses())
    return drill(s, holes, cuts)


def build_psu_bulkhead():
    lo, hi = (-X_IN, hw.PSU_REAR_Y, BULK_Z[0]), (X_IN, BULK_Y1, BULK_Z[1])
    plate = hw.wbox(lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])
    window = hw.wbox(BULK_WINDOW[0], BULK_WINDOW[1], hw.PSU_REAR_Y - 1.0, BULK_Y1 + 1.0, BULK_WINDOW[2], BULK_WINDOW[3])
    holes = []
    for (x, z) in hw.PSU_HOLES:
        holes.append(clear_hole("M3c", (x, hw.PSU_REAR_Y - OVERSHOOT, z), (0, 1, 0), 7.0))
    for sgn in hw.DRIVE_SIDES.values():          # the drive sleds' flange screws, through the flank, from behind
        for z in SLED_BOLT_Z:
            holes.append(clear_hole("M4c", (sgn * SLED_BOLT_X, hw.PSU_REAR_Y - OVERSHOOT, z), (0, 1, 0), BULK_T + 2 * OVERSHOOT))
    holes += end_pilot_holes("psu_bulkhead")
    desk = "the bottom face stands on the desk (a contact pad)"
    plate = round_box(plate, (lo, hi), 0, "psu_bulkhead", all_corners(-BULK_BLOCK_X, BULK_BLOCK_X, {(False, False): desk, (True, False): desk}),
                      rings=hole_rings(holes), rmax=BULK_R)      # between the end blocks; the blocks keep their sharp ends
    blocks = [hw.wbox(BULK_BLOCK_X, X_IN, BULK_Y0, BULK_Y1, BULK_Z[0], BULK_Z[1]),
              hw.wbox(-X_IN, -BULK_BLOCK_X, BULK_Y0, BULK_Y1, BULK_Z[0], BULK_Z[1])]
    s = fuse_all([plate] + blocks)
    return drill(s, holes, [window])


# Revision 11: the 420's bracket is a plate clamped between the fans and the core, in the 3 mm gap hardware.py keeps there (RAD420_PLATE_U), one half
# on each side of X 0. It takes the six fan screws of its half and leaves the three fan openings clear (hardware.rad420_fan_opening). Below the
# fans' underside (n -16, the fans are 140 mm wide, 1 mm wider than the core) a chord, as wide in u as the foot, runs from rib_B's outer face to the radiator's
# end and joins the foot on rib_B's outer face: the tongue with its two M4 bolts. The old 10 mm plate on the fans' outer face, its bar and its finger are gone.
# Second pass: the chord is out of |X| < CHORD_X0, where the drive bay's sled passes (drive_access.py), and keeps CHORD_FAN_GAP clear of the fans.
ANTLER_U = hw.RAD420_PLATE_U                                            # the plate: between core and fans, 3 thick
ANTLER_T = ANTLER_U[1] - ANTLER_U[0]
ANTLER_X1 = hw.ENVELOPE_X - 1.0                                         # the plate and the chord end 1 mm inside the radiator's end
ANTLER_PLATE_X0 = 40.0                                                  # the plate starts here: nearer X 0 the web over the middle fan's opening is only the 2 mm of the fans' frame (up to X 16.6) and the end edge is too short to round
CHORD_FAN_GAP = 1.0                                                     # the plate's lower edge and the chord's top face stand this far below the fans' underside (n -16)
ANTLER_N = (hw.RAD420_FAN_N[0] - CHORD_FAN_GAP, hw.ENVELOPE_N)          # the plate: from the chord's top to the fans' top face (no part rises above the 420)
CHORD_U = (338.0, 388.0)                                                # the chord: as wide as the foot, so a load on the plate reaches the tongue over the foot's full width
CHORD_H = 5.0                                                           # and this tall, below the plate's lower edge
CHORD_N = (ANTLER_N[0] - CHORD_H, ANTLER_N[0])
CHORD_X0 = X_OUT                                                        # the chord starts at rib_B's outer face: over the rib's cradle (X 142..158) the 2 mm between the fans (n -16) and the cradle (n -18) leave no room for it
CHORD_ROUND = 2.4                                                       # the chord's outline corners: two of them share a 5 mm end, so each takes under half of it
RIB_X = (ANTLER_X1 - 6.0, ANTLER_X1)                                    # the end rib: stiffens the plate's end bar, beyond the fans' end (X 210), where the plate is only 3 mm thick and 18 mm wide
RIB_U = (ANTLER_U[1], float(hw.RAD420_FAN_U[1]))                        # and stands on its back face as far as the fans' outer face: nothing sticks out behind the 420
RIB_N = (ANTLER_N[0], ANTLER_N[1])                                      # the plate's whole height, from the chord to the top face
RIB_ROUND = 2.9                                                         # the rib's top corners: the two share its 6 mm end, so each takes under half of it
TONGUE_T = 10.0
TONGUE_X = (X_OUT, X_OUT + TONGUE_T)                                    # laps onto the rib's outer face
TONGUE_U = CHORD_U
TONGUE_N = (-56.0, CHORD_N[0])


def bsx(x0, x1, u0, u1, n0, n1):
    """A box between world X x0..x1 (right side) and board-space u, n ranges."""
    return hw.bs_box(hw.x_to_v(x0), hw.x_to_v(x1), u0, u1, n0, n1)


TONGUE_OUTLINE = Poly([hw.bp_yz(u, n) for u, n in ((TONGUE_U[0], TONGUE_N[0]), (TONGUE_U[1], TONGUE_N[0]),
                                                  (TONGUE_U[1], TONGUE_N[1]), (TONGUE_U[0], TONGUE_N[1]))])


def antler_holes_xn(side=1):
    """(x, n) of the six fan screws an antler takes, read from hardware.py's table: the four of the outer fan and the two nearer ones of the
    middle fan, that is the three columns on this side of the centre line, in both rows. side = +1 right, -1 left."""
    xs = sorted(x * side for x in hw.RAD420_HOLES_X if x * side > 0)       # distance from the centre line
    return [(side * x, n) for x in xs for n in hw.RAD420_HOLES_N]


def antler_openings(u0, u1):
    """The fan openings the right-hand plate has to leave clear: the middle fan's (it runs through the plate's end) and the outer fan's (inside the plate)."""
    return [hw.rad420_fan_opening(k, u0, u1) for k, cx in enumerate(hw.RAD420_FAN_X) if cx >= 0]


def antler_plate_blank():
    """The plate before rounding: a box over the half's length with the middle fan's opening cut out (it runs through the end, so it is part of the outline
    that is rounded). The outer fan's opening is inside the plate and is cut after the rounding (rounding.round_face works on the outer wire)."""
    u0, u1 = ANTLER_U
    return bsx(ANTLER_PLATE_X0, ANTLER_X1, u0, u1, *ANTLER_N).cut(antler_openings(u0 - 1.0, u1 + 1.0)[0])


def antler_chord_blank():
    """The chord: a box under the plate's lower edge, from rib_B's outer face to the plate's end."""
    return bsx(CHORD_X0, ANTLER_X1, *CHORD_U, *CHORD_N)


def build_antler_right(side=1):
    name = "antler_right" if side > 0 else "antler_left"
    u0, u1 = ANTLER_U
    holes = []
    for (x, n) in antler_holes_xn(+1):      # 6-32 through the plate, along u: the screws go from the fan side through fan and plate into the core
        holes.append(clear_hole("M3c", hw.bp(hw.x_to_v(x), u0 - OVERSHOOT, n), hw.U_DIR, ANTLER_T + 2 * OVERSHOOT))
    for (y, z) in TONGUE_BOLTS:             # M4 clearance through the tongue, along X
        holes.append(x_clear(y, z, TONGUE_X[0] - OVERSHOOT, TONGUE_X[1] + OVERSHOOT))
    rings = hole_rings(holes)
    sides = (1,) if side > 0 else (-1,)
    inner = antler_openings(u0 - 1.0, u1 + 1.0)[1:]              # inside the plate: cut after the rounding, which the Guard is told
    air = rd.Neighbor("fan openings", Compound.makeCompound(antler_openings(u0 - 1.0, u1 + 1.0)), "keepout")      # a rounding must not add plate to an opening (check 14)
    plate = rounded_like(antler_plate_blank(), hw.U_DIR, name + " plate", sides=sides, own=(name,), rings=rings, post_cuts=inner, extra=[air])
    plate = cut_all(plate, inner)
    keep = [(hw.bp(hw.x_to_v(CHORD_X0), CHORD_U[0], CHORD_N[0]), "the tongue's inner face continues this wall: no edge")]
    chord = rounded_like(antler_chord_blank(), hw.U_DIR, name + " chord", sides=sides, own=(name,), rings=rings, keep=keep, convex=CHORD_ROUND)
    flush = "flush with the chord's face above it: not a corner of the fused part"
    keep = [(hw.bp(hw.x_to_v(TONGUE_X[0]), u, TONGUE_N[1]), flush) for u in TONGUE_U]
    tongue = rounded_like(bsx(*TONGUE_X, *TONGUE_U, *TONGUE_N), (1, 0, 0), name + " tongue", sides=sides, own=(name,), rings=rings, keep=keep)
    flush = "flush with the chord's top face: not a corner of the fused part"
    keep = [(hw.bp(hw.x_to_v(x), u, RIB_N[0]), flush) for x in RIB_X for u in RIB_U]
    rib = rounded_like(bsx(*RIB_X, *RIB_U, *RIB_N), hw.U_DIR, name + " end rib", sides=sides, own=(name,), rings=rings, keep=keep, convex=RIB_ROUND)
    s = fuse_all([plate, chord, tongue, rib])

    def pick(e):      # the tongue's outer side (X 168) where it leaves the chord's underside: along u
        m, d = edge_info(e)
        return abs(abs(float(d @ np.array(hw.U_DIR))) - 1) < 1e-6 and abs(m[0] - TONGUE_X[1]) < 1e-3 \
            and abs(un_of(m[1], m[2])[1] - CHORD_N[0]) < 1e-2
    s = junction_fillet(s, name, "tongue meets chord", pick, sides=sides, own=(name,), rings=rings)
    return drill(s, holes)


def _rect_poly(u0, u1, n0, n1):
    return Poly([hw.bp_yz(u, n) for u, n in ((u0, n0), (u1, n0), (u1, n1), (u0, n1))])


JOINT_BOLTS = [hw.bp_yz(JOINT_U, n) for n in JOINT_N]      # (Y, Z), along X through neck and arm


def build_neck_right(guide_pilot=False, side=1):
    """Straight strut along n at |X| 180..192, u 284..307, and the spacer pad |X| 158..180 behind its lower end. The two
    joint bolts to the visor arm pass through it at n 114 and 93.5. Returns solid, holes, blank and the YZ outlines of
    strut and pad for the bolt checks."""
    name = "neck_right" if side > 0 else "neck_left"
    holes = [x_clear(y, z, NECK_X[0] - OVERSHOOT, NECK_X[1] + OVERSHOOT) for (y, z) in JOINT_BOLTS]
    for (y, z) in NECK_BOLTS:
        holes.append(x_clear(y, z, X_OUT - OVERSHOOT, X_OUT - OVERSHOOT + 35.0))
    if guide_pilot:                         # the left neck carries the CPU hose guide: one M4S in its outer face
        holes.append(pilot((NECK_X[1], *guide_cpu_geometry()[3]), (-1, 0, 0), "M4S"))
    holes += organic_pilots(name, mirrored=side < 0)      # the organic layer's pad on the strut's outer face
    rings = hole_rings(holes)
    sides = (1,) if side > 0 else (-1,)
    strut = bsx(*NECK_X, NECK_U[0], NECK_U[1], NECK_N[0], NECK_N[1])
    pad = bsx(X_OUT, NECK_X[0], NECK_U[0], NECK_U[1], PAD_N[0], PAD_N[1])
    strut = rounded_like(strut, (1, 0, 0), name + " strut", sides=sides, own=(name,), rings=rings)
    pad = rounded_like(pad, (1, 0, 0), name + " pad", sides=sides, own=(name,), rings=rings)
    s = fuse_all([strut, pad])

    def pick(e):      # where the pad's top face meets the strut's inner face: along u, at X = 180, at the pad's top n
        m, d = edge_info(e)
        return abs(abs(float(d @ np.array(hw.U_DIR))) - 1) < 1e-6 and abs(abs(m[0]) - NECK_X[0]) < 1e-3 \
            and abs(un_of(m[1], m[2])[1] - PAD_N[1]) < 1e-2
    s = junction_fillet(s, name, "pad meets strut", pick, sides=sides, own=(name,), rings=rings)
    outlines = dict(
        strut=[_rect_poly(NECK_U[0], NECK_U[1], NECK_N[0], NECK_N[1])],
        pad=[_rect_poly(NECK_U[0], NECK_U[1], PAD_N[0], PAD_N[1])])
    return drill(s, holes) + (outlines,)


def build_arm_right(notched=True):
    """Bar under the 360's inner face with the two screws into the radiator, a knee below the bar for the second joint
    bolt, and the two joint bolts' pilots on the neck's side. The bar is as wide as the neck is far (X to NECK_X[0]) so
    the two parts meet face to face.
    notched: right arm only, where it passes the 360's port tank; the outer face is cut back to ARM_NOTCH_X."""
    name = "visor_arm_right" if notched else "visor_arm_left"
    n0 = hw.RAD360_INNER_N - ARM_T
    x0, x1 = RAD360_X_ARM - ARM_HALF_T, NECK_X[0]
    holes = [pilot((x1, y, z), (-1, 0, 0), "M4S") for (y, z) in JOINT_BOLTS]      # joint bolts, from the neck's side
    v = hw.x_to_v(RAD360_X_ARM)
    for u in hw.RAD360_HOLES_U:    # along n through the bar at the outer column
        holes.append(clear_hole("M3c", hw.bp(v, u, hw.RAD360_INNER_N - 18.0), hw.N_DIR, 18.0))
    notch = bsx(ARM_NOTCH_X, x1 + 1, ARM_NOTCH_U[0], ARM_NOTCH_U[1], n0 - 1, hw.RAD360_INNER_N + 1)
    s = bsx(x0, x1, ARM_U0, hw.BOARD_BS[3], n0, hw.RAD360_INNER_N)
    s = s.fuse(bsx(x0, x1, KNEE_U[0], KNEE_U[1], KNEE_N0, n0)).clean()
    s = rounded_like(s, (1, 0, 0), name, sides=(1,) if notched else (-1,), own=(name,), rings=hole_rings(holes),
                     post_cuts=[notch] if notched else ())
    if notched:
        s = s.cut(notch)
    return drill(s, holes)


def hose_at(pair, idx, u):
    """Hose `idx` of a pair where its route (hoses.routes()) crosses board-space u: the world centre point, the
    unit direction there (world) and the point in board space (v, u, n)."""
    pts = hoses.routes()[pair][0][idx]["pts"]
    q = [hoses.world_to_bs(p) for p in pts]
    for k in range(len(pts) - 1):
        u0, u1 = q[k][1], q[k + 1][1]
        if u1 > u0 and u0 <= u <= u1:
            d = pts[k + 1] - pts[k]
            d = d / float((d ** 2).sum() ** 0.5)
            p = pts[k] + (u - u0) / (u1 - u0) * (pts[k + 1] - pts[k])
            return p, d, hoses.world_to_bs(p)
    raise ValueError(f"hose {pair}[{idx}] never reaches u = {u}")


def guide_hose_r(pair):
    return hw.CPU_HOSE_R if pair == "cpu" else hw.GPU_HOSE_R


def guide_channel(pair, idx, u, side, shrink=0.0):
    """Cutters for one channel: a cylinder along the true hose of radius hose + GUIDE_PLAY (minus `shrink`, which only the
    tests use) and the slot that opens it towards world X * `side`, GUIDE_MOUTH x the hose diameter wide. Both are 40 mm
    long along the hose; the slot runs from the hose axis outwards."""
    r_h = guide_hose_r(pair)
    p, d, _ = hose_at(pair, idx, u)
    org = p - 20.0 * d
    ex = np.array([side, 0.0, 0.0])
    ex = ex - float(ex @ d) * d
    ex = ex / float(np.linalg.norm(ex))
    channel = Solid.makeCylinder(r_h + GUIDE_PLAY - shrink, 40.0, Vector(*org), Vector(*d))
    plane = cq.Plane(origin=tuple(org), xDir=tuple(ex), normal=tuple(d))
    slot = cq.Workplane(plane).center(30.0, 0).rect(60.0, GUIDE_MOUTH * 2 * r_h).extrude(40.0).val()
    return [channel, slot]


def guide_tip(pair, idx_list, u_lo, u_hi, side):
    """World X of the end of a shelf: past the hose axis by the channel radius, where the axis reaches furthest out
    over the guide's length (the GPU run is not square to X, so its axis shifts along the guide)."""
    reach = max(side * (hose_at(pair, i, u)[0][0]) for i in idx_list for u in (u_lo, u_hi))
    return side * (reach + guide_hose_r(pair) + GUIDE_PLAY)


def guide_cpu_geometry():
    """(n range of the guide, board-space centres of the two channels, n of the bolt, (Y, Z) of the bolt)."""
    u_mid = sum(GUIDE_CPU_U) / 2
    r_ch = hw.CPU_HOSE_R + GUIDE_PLAY
    centres = [hose_at("cpu", i, u_mid)[2] for i in (0, 1)]
    n_lo, n_hi = centres[0][2] - r_ch - GUIDE_RIM, centres[1][2] + r_ch + GUIDE_RIM
    n_bolt = (n_lo + n_hi) / 2
    return (n_lo, n_hi), centres, n_bolt, hw.bp_yz(GUIDE_CPU_BOLT_U, n_bolt)


def guide_not_rounded(name):
    """The hose guides keep their edges: every outer edge of the foot or plate is also an edge of a shelf, and the shelf's wall around its
    channel is GUIDE_RIM thick (the mouth's lip about 2 mm). A 3 mm radius on those edges takes the wall to zero where the channel leaves the
    shelf's end faces (the arc is tangent 3 mm in, the channel radius is 6.3..6.5 of the 9 mm half-height), and at 2 mm it leaves 0.5 mm."""
    if ROUND is not None:
        ROUND_LOG.append(rd.Entry(name, (0.0, 0.0, 0.0), "layer", 0.0, 0.0,
                                  f"not rounded: the channel wall is {GUIDE_RIM:g} mm and the mouth's lip about 2 mm; a {BOX_R:g} mm radius on the shelf edges "
                                  f"takes the wall to 0 at the shelf's end faces, a 2 mm radius leaves 0.5 mm; the foot's corners are corners of the shelves"))


def build_hose_guide_cpu(shrink=0.0):
    """Left-hand guide: a foot on the left neck's outer face and two shelves that carry the CPU pair on the last straight
    run into the 420's port. Each shelf has a channel of hose diameter + 0.6 mm, open towards -X through a mouth of
    0.75 x the hose diameter."""
    u_mid = sum(GUIDE_CPU_U) / 2
    (n_lo, n_hi), centres, n_bolt, (y, z) = guide_cpu_geometry()
    r_ch = hw.CPU_HOSE_R + GUIDE_PLAY
    x_neck = -NECK_X[1]
    x_foot = x_neck - GUIDE_T
    x_tip = guide_tip("cpu", (0, 1), *GUIDE_CPU_U, -1)
    foot = bsx(x_foot, x_neck, GUIDE_CPU_FOOT_U[0], GUIDE_CPU_FOOT_U[1], n_lo, n_hi)
    shelves = [bsx(x_tip, x_neck, GUIDE_CPU_U[0], GUIDE_CPU_U[1], n - r_ch - GUIDE_RIM, n + r_ch + GUIDE_RIM)
               for _, _, n in centres]
    s = fuse_all([foot] + shelves)
    s = s.cut(*[c for i in (0, 1) for c in guide_channel("cpu", i, u_mid, -1, shrink)])
    holes = [x_clear(y, z, x_foot - OVERSHOOT, x_neck + OVERSHOOT)]
    guide_not_rounded("hose_guide_cpu")
    return drill(s, holes), (y, z)


def guide_gpu_bolt():
    """(Y, Z) of the guide's bolt on rib_A_right's outer face."""
    return hw.bp_yz(sum(GUIDE_GPU_U) / 2, GUIDE_GPU_BOLT_N)


def build_hose_guide_gpu(shrink=0.0):
    """Right-hand guide: a plate on rib_A_right's outer face and two shelves that reach out to the GPU pair on its
    up-slope run behind the board; channels as in the CPU guide, open towards +X."""
    u_mid = sum(GUIDE_GPU_U) / 2
    centres = [hose_at("gpu", i, u_mid)[2] for i in (0, 1)]
    r_ch = hw.GPU_HOSE_R + GUIDE_PLAY
    n_lo = min(c[2] for c in centres) - r_ch - GUIDE_RIM
    x_tips = [guide_tip("gpu", (i,), *GUIDE_GPU_U, 1) for i in (0, 1)]
    plate = bsx(X_OUT, X_OUT + GUIDE_T, GUIDE_GPU_U[0], GUIDE_GPU_U[1], n_lo, GUIDE_GPU_PLATE_N1)
    shelves = [bsx(X_OUT, x_tip, GUIDE_GPU_U[0], GUIDE_GPU_U[1], n - r_ch - GUIDE_RIM, n + r_ch + GUIDE_RIM)
               for (_, _, n), x_tip in zip(centres, x_tips)]
    s = fuse_all([plate] + shelves)
    s = s.cut(*[c for i in (0, 1) for c in guide_channel("gpu", i, u_mid, 1, shrink)])
    y, z = guide_gpu_bolt()
    holes = [x_clear(y, z, X_OUT - OVERSHOOT, X_OUT + GUIDE_T + OVERSHOOT)]
    guide_not_rounded("hose_guide_gpu")
    return drill(s, holes), (y, z)


def fan_bracket_geometry(name):
    """(plate X range, leg X range, rib-face X, direction towards the board) of a bracket, world X."""
    fan = BRACKET_FAN[name]
    face, d = hw.FAN_SIDE_INNER_X[fan], hw.FAN_SIDE_IN[fan]
    far = face + d * BRACKET_T
    rib_face = -d * X_OUT
    plate = tuple(sorted((far, face)))
    leg = tuple(sorted((rib_face, far - d * 1.0)))       # 1 mm into the plate so the two fuse
    return plate, leg, rib_face, d


def build_fan_bracket(name):
    """C-shaped plate on the fan's inner face plus a leg to the rib's outer face. Pilots: M4S under each used fan corner,
    M4 in the leg's rib face for the two rib bolts."""
    fan = BRACKET_FAN[name]
    plate, leg, rib_face, d = fan_bracket_geometry(name)
    corners = BRACKET_CORNERS[name]
    pos = {k: hw.FAN_SIDE_HOLES_UN[k] for k in corners}
    r = BRACKET_EAR
    plate_boxes = []                    # the C: ears, spine, bar (one layer, one outline)
    layers = []                         # everything else, each a box of its own
    rail = name in BRACKET_TAB
    for k, (u, n) in pos.items():
        low_n = n < hw.FAN_CENTRE_UN[1]
        n0, n1 = (BAR_N[1] - 0.5, n + r) if low_n else (n - r, n + r)
        u0 = BRACKET_SPINE_U[1] - 0.5 if u < hw.FAN_CENTRE_UN[0] else u - r
        plate_boxes.append(bsx(*plate, u0, u + r, n0, n1))
    n_top = max(pos[k][1] + r for k in pos)
    if rail:
        n_top = RAIL_N[1]               # the spine climbs past the fan's top edge to meet the rail
    n_bot = BAR_N[0] if "B" in pos else min(BAR_N[1] - 0.5, *(pos[k][1] - r for k in pos))
    plate_boxes.append(bsx(*plate, *BRACKET_SPINE_U, n_bot, n_top))
    if "B" in pos:
        plate_boxes.append(bsx(*plate, BRACKET_SPINE_U[0], pos["B"][0] + r, BAR_N[0], BAR_N[1]))
    layers.append(("leg", bsx(*leg, *BRACKET_LEG_U, *BRACKET_LEG_N)))
    tab_hole = None
    if rail:
        x_out = hw.FAN_SIDE_X[fan][0 if d > 0 else 1]                    # the fan's outer face
        x_rail_in = hw.FAN_SIDE_INNER_X[fan] - d * RAIL_INSET
        x_tab = tuple(sorted((x_out, x_out - d * TAB_T)))
        x_knuckle = tuple(sorted((x_out + d * 1.0, x_out - d * 1.0)))    # 1 mm either side of the fan's outer face, fuses rail and tab
        tu, tn = hw.FAN_SIDE_HOLES_UN[BRACKET_TAB[name]]
        t_half = hw.M4_CLEAR_D / 2 + TAB_WALL
        layers.append(("root", bsx(*sorted((plate[0] if d < 0 else plate[1], x_out)), BRACKET_SPINE_U[0], BRACKET_SPINE_U[1], *RAIL_N)))   # root block: plate face to outer face
        layers.append(("rail", bsx(*sorted((x_rail_in, x_out)), BRACKET_SPINE_U[1] - 1.0, RAIL_U1, *RAIL_N)))
        layers.append(("knuckle", bsx(*x_knuckle, tu - t_half, RAIL_U1, RAIL_N[0], RAIL_N[1])))
        layers.append(("tab", bsx(*x_tab, tu - t_half, RAIL_U1, tn - t_half, RAIL_N[1])))
        tab_hole = (tu, tn, x_tab)
    holes = []
    for k, (u, n) in pos.items():       # fan screws: from the fan's inner face into the plate, away from the fan
        y, z = hw.bp_yz(u, n)
        holes.append(pilot((hw.FAN_SIDE_INNER_X[fan], y, z), (d, 0, 0), FAN_PILOT_KIND))
    for (y, z) in BRACKET_BOLTS:        # rib bolts: insert pilots in the leg's face on the rib
        holes.append(pilot((rib_face, y, z), (math.copysign(1.0, rib_face), 0, 0), "M4"))   # away from the rib: +X on the right, -X on the left
    if tab_hole:                        # the tab's fan screw: Ø4.5 clearance from outside, the screw runs into the fan's own hole
        tu, tn, (xa, xb) = tab_hole
        y, z = hw.bp_yz(tu, tn)
        holes.append(x_clear(y, z, xa - OVERSHOOT, xb + OVERSHOOT))
    rings = hole_rings(holes)
    extra = [rd.Neighbor("aperture", aperture_cylinder(fan), "keepout")] if ROUND is not None else []   # the fan's open circle: a probe, not hardware
    kw = dict(sides=(1,), own=(name,), rings=rings, extra=extra)
    solids = [rounded_like(fuse_all(plate_boxes), (1, 0, 0), name + " plate", **kw)]
    for label, box in layers:
        if label in RAIL_GROUP:     # revision 8a: rounded with the radius that keeps its joints (the rail is 5.5 wide, so 2 mm); see below
            solids.append(rounded_like(box, (1, 0, 0), f"{name} {label}", convex=RAIL_CONVEX.get(label, ROUND_CONVEX), **kw))
        else:
            solids.append(rounded_like(box, (1, 0, 0), f"{name} {label}", **kw))
    s = fuse_all(solids)
    if ROUND is not None and name in BRACKET_TAB and n_solids(s) != 1:
        # the rail group (2.5..5.5 mm thin, joined by 1 mm overlaps) is rounded only when the bracket stays one solid; if not, leave the group as drawn
        ROUND_LOG.append(rd.Entry(name, (0.0, 0.0, 0.0), "layer", 0.0, 0.0,
                                  "rail, root block, knuckle and tab (2.5..5.5 mm thin, joined by 1 mm overlaps): rounding any of them cut the joints into two solids"))
        s = fuse_all([solids[0]] + [box if lab in RAIL_GROUP else solids[1 + i] for i, (lab, box) in enumerate(layers)])
    x_join = plate[0] if d < 0 else plate[1]          # the plate's face towards the rib, where the leg joins it

    def pick(e):      # the leg's four sides where they meet that face
        m, dd = edge_info(e)
        if abs(float(dd[0])) > 1e-6 or abs(m[0] - x_join) > 1e-3:
            return False
        u, n = un_of(m[1], m[2])
        (u0, u1), (n0, n1) = BRACKET_LEG_U, BRACKET_LEG_N
        return (abs(u - u0) < 1e-2 or abs(u - u1) < 1e-2) and n0 - 1e-2 <= n <= n1 + 1e-2 \
            or (abs(n - n0) < 1e-2 or abs(n - n1) < 1e-2) and u0 - 1e-2 <= u <= u1 + 1e-2
    s = junction_fillet(s, name, "leg meets plate", pick, **kw)
    return drill(s, holes)


def build_gpu_post():
    s = hw.bs_box(*GPU_POST_BS)
    holes = []
    for u in GPU_POST_U:
        holes.append(pilot(hw.bp(GPU_POST_V, u, hw.ATX_TRAY_N), hw.N_DIR, "M4"))
    v0, v1, u0, u1, n0, n1 = GPU_POST_BS
    # the long edges run along n; the foot stands on beam_mid, so the first COLLAR mm keep the foot's outline; the top end is free
    s = round_box(s, ((v0, u0, n0), (v1, u1, n1)), 2, "gpu_post", all_corners(n0 + COLLAR, n1), place=bs_place,
                  rings=hole_rings(holes))
    return drill(s, holes)


def build_frame(rounded=True, hardware=None):
    """The parts and the neck outlines. rounded=False builds the skeleton as it was before revision 8 (sharp corners): the
    reference every rounding is judged against, and what test_checks.py swaps in to prove check 12 bites."""
    global ROUND
    ctx = None
    if rounded:
        hardware = hardware if hardware is not None else hw.build_hardware()
        hit = _CTX.get(id(hardware))
        if hit is None or hit[0] is not hardware:
            ref, _ = build_frame(rounded=False)
            hit = (hardware, RoundCtx(hardware, ref))
            _CTX[id(hardware)] = hit
        ctx = hit[1]
        ctx.ledger.clear()
    # module state is per build: a second call must not double the registry
    FASTENERS.clear()
    BOLT_CHECKS.clear()
    ROUND_LOG.clear()
    KEEP_SHARP.clear()
    _A_LAYER.clear()
    ROUND = ctx
    try:
        return _build_frame()
    finally:
        ROUND = None


def _build_frame():
    parts: list[Part] = []

    def add(name, built, note, material="ABS"):
        solid, holes, blank = built
        parts.append(Part(name, solid, note, list(holes), blank, material=material))

    def add_mirror(name, built, note, material="ABS"):
        solid, holes, blank = built
        parts.append(Part(name, mirror_x(solid), note, [h.mirrored() for h in holes], mirror_x(blank), material=material))

    add("rib_A_right", build_rib_a(True), "right rib, front + diagonal + mid leg + gpu_rest finger")
    add_mirror("rib_A_left", build_rib_a(False), "left rib, front + diagonal + mid leg")
    add("rib_B_right", build_rib_b(1), "right rib, rear post: runner, post, nose, tail post")
    add_mirror("rib_B_left", build_rib_b(-1), "left rib, rear post")

    add("beam_front", build_beam_front(), "front beam, ties the front feet; carries the front sill (4 x M4 from below)")
    add("front_sill", build_front_sill(),
        "front sill X +-140: 45 deg face parallel to the board, pocket for the I/O module (PLACEHOLDER box), channel and slit for the light line, 4 x M4 into beam_front, 2 x M3 for the module (PLACEHOLDER)")
    add("fan_bracket_right", build_fan_bracket("fan_bracket_right"),
        "right side fan bracket: plate on the fan's inner face (corners A, C), leg to rib_A_right's outer face, 2 x M4")
    add("fan_bracket_left", build_fan_bracket("fan_bracket_left"),
        "left side fan bracket: C-plate on the fan's inner face (corners A, B, C), leg to rib_A_left's outer face, 2 x M4")
    for name, row in BEAM_ROW.items():
        add(name, build_beam(name), f"ATX tray beam, row u = {row}, 3 standoff bosses")
    add("skid_front", build_skid("skid_front", 185, 205), "PSU skid, front")
    add("skid_rear", build_skid("skid_rear", 325, 345), "PSU skid, rear")
    add("psu_bulkhead", build_psu_bulkhead(), "PSU bulkhead with IEC window, 4 PSU screw holes, M4 clearance holes for the drive sleds' flanges (only on the side that has a bay)")
    for bay, sgn in hw.DRIVE_SIDES.items():          # hw.DRIVE_SIDES lists the bays that are built
        if sgn > 0:
            add(f"drive_sled_{bay}", build_drive_sled(sgn),
                "right drive sled: 5 mm plate beside the PSU, bosses and counterbored 6-32 / M3 holes for a 3.5 inch drive (outer face) and a 2.5 inch drive (inner face), flange with 2 x M4 inserts against the bulkhead, foot on skid_rear")
        else:
            add_mirror(f"drive_sled_{bay}", build_drive_sled(sgn),
                       "left drive sled: the right one mirrored in X; flange with 2 x M4 inserts against the bulkhead, foot on skid_rear")

    add("antler_right", build_antler_right(1), "420 bracket on the fan face + tongue on the rib's outer face, right")
    add_mirror("antler_left", build_antler_right(-1), "420 bracket on the fan face + tongue on the rib's outer face, left")

    *neck, neck_prims = build_neck_right(side=1)
    add("neck_right", tuple(neck), "neck: strut along n + spacer pad, right; 2 x M4 clearance to the visor arm")
    *neck_l, _ = build_neck_right(guide_pilot=True, side=-1)
    add_mirror("neck_left", tuple(neck_l), "neck: strut along n + spacer pad, left; 2 x M4 clearance to the visor arm; carries the CPU hose guide")
    add("visor_arm_right", build_arm_right(True), "360 visor arm, right (2 x M4S to the neck, knee below the bar), notched at the port tank")
    add_mirror("visor_arm_left", build_arm_right(False), "360 visor arm, left (2 x M4S to the neck, knee below the bar)")

    add("gpu_post", build_gpu_post(), "card bracket post, left side (PLACEHOLDER geometry)")

    g_cpu, _ = build_hose_guide_cpu()
    add("hose_guide_cpu", g_cpu, "CPU hose guide: foot on the left neck, two channels open to -X, 1 x M4S", material="PA6")
    g_gpu, _ = build_hose_guide_gpu()
    add("hose_guide_gpu", g_gpu, "GPU hose guide: plate on rib_A_right's outer face, two channels open to +X, 1 x M4", material="PA6")

    for tp in TIE_POINTS:
        add(tie_name(tp), build_tie_bridge(tp),
            f"cable tie bridge {tp['row']} {tp['k']}: foot on {tp['host']}'s {tp['face']} at world ({tp['pt'][0]:.1f}, {tp['pt'][1]:.1f}, {tp['pt'][2]:.1f}), 1 x M3 into its insert, a 12.5 x 3.5 slot for a hook-and-loop strap", material="ABS")

    # --- fastener registry: what the plan lists per hardware item. The counts below are written down by
    # hand; run_checks derives the real ones from the solids (derive_mounts) and fails if they differ.
    n_atx = len(hw.ATX_HOLES)
    fastener("board", "beam_low/beam_mid/beam_top", "M3 insert", n_atx,
             "9 standoff bosses, 3 per beam; board underside n=-2 touches the bosses")
    fastener("rad420", "antler_left + antler_right", "6-32", 2 * len(antler_holes_xn(1)),
             f"{len(antler_holes_xn(1))} per antler along u: the fan screws, from the fans' outer face through the fan and the {ANTLER_T:g} mm plate into the core "
             f"(the four of the outer fan and the two nearer ones of the middle fan); {ANTLER_T:g} mm longer than the stock screw")
    fastener("rad360", "visor_arm_left + visor_arm_right", "6-32", 2 * len(hw.RAD360_HOLES_U),
             "2 per arm along n at u = 192, 297")
    fastener("psu", "psu_bulkhead (+ skid_front, skid_rear support)", "6-32", len(hw.PSU_PATTERN),
             f"{len(hw.PSU_HOLES)} holes, standard pattern seen from behind (inlet at -X); PSU rests on the skids")
    for fan, bracket in (("fan_side_left", "fan_bracket_left"), ("fan_side_right", "fan_bracket_right")):
        k = len(BRACKET_CORNERS[bracket]) + (bracket in BRACKET_TAB)
        tab = f"; corner {BRACKET_TAB[bracket]} through a tab over the fan's outer face (screw from outside, clearance hole)" if bracket in BRACKET_TAB else ""
        fastener(fan, bracket, FAN_PILOT_KIND + " insert", k,
                 f"corners {', '.join(BRACKET_CORNERS[bracket])} of 4 (needs >= {FAN_MIN_SCREWS}): screws from the fan's outer face into the plate{tab}")
    fastener("front_io", "front_sill", hw.FRONT_IO_SCREW_KIND + " insert", len(hw.FRONT_IO_SCREWS),
             "PLACEHOLDER: 2 along X into the end walls of the sill's pocket; the module's screws are not known until it is measured")
    fastener("gpu", "gpu_post (left) + rib_A_right gpu_rest (right)", "M4 insert", 2,
             "post: 2 M4 into beam_mid; rest: bears the card edge, no screw")
    # structural
    fastener("lap A<->B", "rib_A/rib_B x2", "M4 insert", 2 * len(LAP_BOLTS),
             "3 per side (2 top, 1 bottom); clearance in B, pilot in A")
    for name, pts in END_BOLTS.items():
        fastener(f"{name} ends", "ribs", "M4 insert", 2 * len(pts),
                 f"{len(pts)} per end, pilots in the member")
    fastener("antler tongue", "antler_L/R -> rib_B_L/R post", "M4 insert", 4, "2 per side along X into the post's outer face")
    fastener("neck pad", "neck_L/R -> rib_B_L/R post", "M4 insert", 4, "2 per side along X")
    fastener("visor joint", "visor_arm + neck", "M4S insert", 4,
             "two per side, along X at u 289.2, n 114 and 93.5 (pilot in the arm, clearance in the neck); no hinge")
    fastener("fan brackets", "fan_bracket_L/R -> rib_A_L/R", "M4 insert", 2 * len(BRACKET_BOLTS),
             "2 per side along X at u 121, n -26 and -14: clearance through the rib, pilot in the bracket's leg; heads on the rib's inner face")
    fastener("hose_guide_cpu", "hose_guide_cpu -> neck_left", "M4S insert", 1, "1 along X into the left neck's outer face")
    fastener("hose_guide_gpu", "hose_guide_gpu -> rib_A_right", "M4 insert", 1, "1 along X into the right rib's outer face")
    fastener("gpu_post", "gpu_post -> beam_mid", "M4 insert", 2, "along n")
    fastener("front_sill", "front_sill -> beam_front", "M4 insert", len(SILL_BOLTS),
             "2 per end block along Z: clearance through beam_front from below, pilot in the sill's bottom face; heads under the beam")
    fastener("tie_pilot", "/".join(dict.fromkeys(t["host"] for t in TIE_POINTS)), "M3 insert", len(TIE_POINTS),
             "the cable tie points (TIE_POINTS): one pilot each, into the part's face along the face's inward normal (along n into an underside, along X into a rib's inner face, along Z into the skid's top); rows: " + ", ".join(
                 f"{r} {sum(1 for t in TIE_POINTS if t['row'] == r)}" for r in dict.fromkeys(t["row"] for t in TIE_POINTS)))
    fastener("tie_bridge", "tie_bridge_* -> the tie points", "M3 screw", len(TIE_POINTS),
             "one M3 x 10 through the bridge's foot (4 mm clearance hole) into the insert; the bridge is ABS, the same part at every point")
    for side_name in hw.DRIVE_SIDES:
        faces = hw.drive_layout()["faces"]
        fastener(f"drive_{side_name}", f"drive_sled_{side_name}", "6-32 x 6.35 + M3 x 5", DRIVE_SCREWS,
                 f"{len(faces['outer']['holes'])} 6-32 x 6.35 on the 3.5 inch drive (outer face), {len(faces['inner']['holes'])} M3 x 5 on the 2.5 inch drive (inner face): each from the face "
                 f"opposite the drive, head in a counterbore, {SLED_FLOOR:g} mm of material under it, so the screw enters 6.35 - {SLED_FLOOR:g} = {faces['outer']['spec']['screw_len'] - SLED_FLOOR:.2f} mm "
                 f"(standard {faces['outer']['spec']['enter'][0]:g}..{faces['outer']['spec']['enter'][1]:g}) and 5 - {SLED_FLOOR:g} = {faces['inner']['spec']['screw_len'] - SLED_FLOOR:.2f} mm (at most {faces['inner']['spec']['enter'][1]:g}); "
                 f"assembly order: {SLED_ORDER}")
    fastener("drive sled flanges", "drive_sled_* -> psu_bulkhead", SLED_BOLT_KIND + " insert", len(hw.DRIVE_SIDES) * len(SLED_BOLT_Z),
             f"{len(SLED_BOLT_Z)} per sled along Y at X {', '.join(f'{sg * SLED_BOLT_X:g}' for sg in hw.DRIVE_SIDES.values())}, Z {SLED_BOLT_Z[0]:g} and {SLED_BOLT_Z[1]:g}: clearance holes through the bulkhead's flank, pilots in the flange; screws from behind (heads on the bulkhead's rear face)")
    fastener("organic", "rib_A_L/R, rib_B_L/R, neck_L/R, front_sill", "M3 insert", len(hw.ORGANIC_PADS),
             "the PLA layer's pads (hw.ORGANIC_PADS): 6 a side, one pilot each along X into the outer face; the screw and the pad are in organic_frame.py")
    return parts, neck_prims


# ---------------------------------------------------------------------------
# Bolt geometry checks (positions inside outlines)
# ---------------------------------------------------------------------------
def check_bolts(neck_prims):
    BOLT_CHECKS.clear()
    shapes = {"A": SHAPE_A, "B": SHAPE_B}
    cr = hw.M4_CLEAR_D / 2
    for name, pts in END_BOLTS.items():
        for pt in pts:
            for r in HOLDING_RIB[name]:
                # beam_top's bolts must also keep the insert wall (2.1 mm) around the clearance hole
                m = cr + (hw.M4_MIN_WALL if name == "beam_top" else 0.0)
                ok = inside(shapes[r], pt, m)
                BOLT_CHECKS.append((f"{name} end bolt ({pt[0]:.1f},{pt[1]:.1f}) in rib {r}", ok, ""))
    for pt in LAP_BOLTS:
        for r in "AB":
            ok = inside(shapes[r], pt, hw.M4S_PILOT_D / 2 + hw.M4S_MIN_WALL if r == "A" else cr)
            BOLT_CHECKS.append((f"lap bolt ({pt[0]:.1f},{pt[1]:.1f}) in rib {r}", ok, ""))
    pr = hw.M4_PILOT_D / 2 + hw.M4_MIN_WALL
    for pt in NECK_BOLTS:
        ok = inside(neck_prims["strut"], pt, cr + hw.M4_MIN_WALL) and inside(neck_prims["pad"], pt, cr + hw.M4_MIN_WALL) \
            and inside(SHAPE_B, pt, pr)
        BOLT_CHECKS.append((f"neck bolt ({pt[0]:.1f},{pt[1]:.1f}) in neck + pad + rib_B", ok, ""))
    arm_prims = [_rect_poly(ARM_U0, hw.BOARD_BS[3], hw.RAD360_INNER_N - ARM_T, hw.RAD360_INNER_N),
                 _rect_poly(KNEE_U[0], KNEE_U[1], KNEE_N0, hw.RAD360_INNER_N - ARM_T)]
    for pt in JOINT_BOLTS:     # clearance wall in the strut, pilot wall in the arm (bar or knee), and 20 mm between the two bolts
        ok = inside(neck_prims["strut"], pt, cr + hw.M4_MIN_WALL) and inside(arm_prims, pt, hw.M4S_PILOT_D / 2 + hw.M4S_MIN_WALL)
        BOLT_CHECKS.append((f"joint bolt ({pt[0]:.1f},{pt[1]:.1f}) in neck strut + visor arm", ok, ""))
    gap = math.dist(JOINT_BOLTS[0], JOINT_BOLTS[1])
    BOLT_CHECKS.append((f"joint bolts {gap:.1f} mm apart (>= {JOINT_MIN_SPACING:g})", gap >= JOINT_MIN_SPACING, ""))
    leg = [_rect_poly(*BRACKET_LEG_U, *BRACKET_LEG_N)]
    for pt in BRACKET_BOLTS:       # clearance wall in rib_A, pilot wall in the bracket's leg
        ok = inside(SHAPE_A, pt, cr + hw.M4_MIN_WALL) and inside(leg, pt, pr)
        BOLT_CHECKS.append((f"fan bracket bolt ({pt[0]:.1f},{pt[1]:.1f}) in rib_A + bracket leg", ok, ""))
    gap = math.dist(BRACKET_BOLTS[0], BRACKET_BOLTS[1])
    BOLT_CHECKS.append((f"fan bracket bolts {gap:.1f} mm apart (>= 2 x pilot + wall = {hw.M4_PILOT_D + hw.M4_MIN_WALL:.1f})",
                        gap >= hw.M4_PILOT_D + hw.M4_MIN_WALL, ""))
    for pt in TONGUE_BOLTS:
        ok = inside([TONGUE_OUTLINE], pt, cr + hw.M4_MIN_WALL) and inside(SHAPE_B, pt, pr)
        BOLT_CHECKS.append((f"tongue bolt ({pt[0]:.1f},{pt[1]:.1f}) in antler tongue + rib_B", ok, ""))
    # front sill (revision 9): the four bolts inside beam_front's top face and inside the sill's section, clear of the pocket; the module's two screws inside the wall
    g = sill_geometry()
    sill_section = [Poly(g["pts"])]
    pr4 = hw.M4_PILOT_D / 2 + hw.M4_MIN_WALL
    io = hw.FRONT_IO_W
    for (x, y) in SILL_BOLTS:
        in_beam = BEAM_FRONT_Y[0] + cr + hw.M4_MIN_WALL <= y <= BEAM_FRONT_Y[1] - cr - hw.M4_MIN_WALL and abs(x) <= X_IN - cr - hw.M4_MIN_WALL
        in_sill = inside(sill_section, (y, g["z0"] + pr4 + 0.1), pr4)        # the pilot opens in the bottom face, so only the sides count
        in_block = (-SILL_HALF_X + pr4 <= x <= io[0] - SILL_POCKET_PLAY - pr4) or (io[1] + SILL_POCKET_PLAY + pr4 <= x <= SILL_HALF_X - pr4)
        BOLT_CHECKS.append((f"sill bolt (X {x:.1f}, Y {y:.1f}) inside beam_front's top face, the sill's section and an end block", in_beam and in_sill and in_block, ""))
    pr_io = hw.INSERTS[hw.FRONT_IO_SCREW_KIND][0] / 2 + hw.INSERTS[hw.FRONT_IO_SCREW_KIND][2]
    for (pt, d) in hw.FRONT_IO_SCREWS:
        ok = inside(sill_section, (pt[1], pt[2]), pr_io)
        BOLT_CHECKS.append((f"I/O module screw (Y {pt[1]:.1f}, Z {pt[2]:.1f}) inside the sill's section with the {hw.FRONT_IO_SCREW_KIND} wall (PLACEHOLDER)", ok, ""))
    # beam end bolts also inside the member's own section (pilot + insert wall)
    for name, row in BEAM_ROW.items():
        lo, hi = BEAM_SPAN[name]
        for (y, z) in END_BOLTS[name]:
            # back to (u, n)
            a, b = (y - hw.ORIGIN[1]) / hw.C, (z - hw.ORIGIN[2]) / hw.C
            u, n = (a + b) / 2, (b - a) / 2
            m = hw.INSERTS[END_KIND.get(name, "M4")]
            r = m[0] / 2 + m[2]
            ok = (row + lo + r <= u <= row + hi - r) and (BEAM_N0 + r <= n <= hw.ATX_TRAY_N - r)
            BOLT_CHECKS.append((f"{name} bolt (u={u:.1f}, n={n:.1f}) pilot inside section", ok, ""))
    # drive sleds: the flange screws' X, Z in the bulkhead's flank, clear of the PSU's screws, the window and the end blocks; the pilots inside the flange's section
    m4 = hw.INSERTS[SLED_BOLT_KIND]
    flange = Rect(SLED_BOLT_X - SLED_FLANGE_HALF_X, SLED_BOLT_X + SLED_FLANGE_HALF_X, *SLED_FLANGE_Z)
    for z in SLED_BOLT_Z:
        x = SLED_BOLT_X
        wall = cr + hw.M4_MIN_WALL
        in_flank = BULK_WINDOW[1] + wall <= x <= BULK_BLOCK_X - wall and BULK_Z[0] + wall <= z <= BULK_Z[1] - wall - BULK_R
        gap_psu = min(math.dist((x, z), px) for px in hw.PSU_HOLES) - cr - hw.M3_CLEAR_D / 2
        BOLT_CHECKS.append((f"drive sled bolt (X {x:.1f}, Z {z:.1f}) in the bulkhead's flank: outside the window (|X| {BULK_WINDOW[1]:g}) and the end blocks (|X| {BULK_BLOCK_X:g}) by the M4 wall, "
                            f"{gap_psu:.1f} mm of wall to the PSU's screw holes (needs {hw.M4_MIN_WALL:g})", in_flank and gap_psu >= hw.M4_MIN_WALL, ""))
        ok = flange.contains((x, z), m4[0] / 2 + m4[2])
        BOLT_CHECKS.append((f"drive sled bolt (X {x:.1f}, Z {z:.1f}) pilot inside the flange's section (X, Z) with the {SLED_BOLT_KIND} wall", ok, ""))
    gap = abs(SLED_BOLT_Z[1] - SLED_BOLT_Z[0])
    BOLT_CHECKS.append((f"drive sled bolts {gap:.1f} mm apart (>= pilot + wall = {m4[0] + m4[2]:.1f})", gap >= m4[0] + m4[2], ""))
    sections = {"beam_front": Rect(0, 40, -10, 10),
                "skid_front": Rect(185, 205, -10, 0), "skid_rear": Rect(325, 345, -10, 0),
                "psu_bulkhead": Rect(BULK_Y0, BULK_Y1, BULK_Z[0], BULK_Z[1])}
    for name, sec in sections.items():
        m = hw.INSERTS[END_KIND.get(name, "M4")]
        for pt in END_BOLTS[name]:
            ok = sec.contains(pt, m[0] / 2 + m[2])
            BOLT_CHECKS.append((f"{name} bolt ({pt[0]:.1f},{pt[1]:.1f}) pilot inside section", ok, ""))


# ---------------------------------------------------------------------------
# Geometry queries
# ---------------------------------------------------------------------------
class BooleanFailure(RuntimeError):
    """An OCC boolean or distance query raised, or returned something that contradicts the geometry.
    It is never turned into 0: callers either let it propagate or record a check failure."""


_BBOX = weakref.WeakKeyDictionary()      # Shape -> bbox; BoundingBox() is the optimal one, 25 ms on a drilled part, and the
                                        # hole checks ask for the same part's box thousands of times


def bbox_of(shape):
    hit = _BBOX.get(shape)
    if hit is None:
        b = shape.BoundingBox()
        hit = (b.xmin, b.xmax, b.ymin, b.ymax, b.zmin, b.zmax)
        _BBOX[shape] = hit
    return hit


def bbox_gap(a, b):
    gx = max(a[0] - b[1], b[0] - a[1], 0)
    gy = max(a[2] - b[3], b[2] - a[3], 0)
    gz = max(a[4] - b[5], b[4] - a[5], 0)
    return math.sqrt(gx * gx + gy * gy + gz * gz)


def bbox_overlap(a, b):
    """Smallest overlap of two boxes along an axis; <= 0 means the boxes share no interior."""
    return min(min(a[1], b[1]) - max(a[0], b[0]),
               min(a[3], b[3]) - max(a[2], b[2]),
               min(a[5], b[5]) - max(a[4], b[4]))


BBOX_TOL = 1e-3          # mm, boxes closer than this count as touching
CROSS_VOL = 0.5          # mm^3, a second boolean may remove at most this much when intersect found nothing


_DIST: dict = {}        # (id a, id b) -> (a, b, distance): inter_vol asks for the distance of a pair and run_checks asks again; the shapes are kept so the ids stay theirs


def solid_distance(a, b):
    cacheable = not isinstance(a, cq.Vertex) and not isinstance(b, cq.Vertex)
    if cacheable:
        hit = _DIST.get((id(a), id(b)))
        if hit is not None and hit[0] is a and hit[1] is b:
            return hit[2]
    try:
        d = float(a.distance(b))
    except Exception as e:      # noqa: BLE001 - re-raised as a check failure, not swallowed
        raise BooleanFailure(f"distance() raised {type(e).__name__}: {e}") from e
    if cacheable:
        _DIST[(id(a), id(b))] = (a, b, d)
    return d


def memo_call(memo, objs, tag, fn, *args, extra=()):
    """fn(*args), remembered in `memo` (a dict) under the identity of the solids in `objs` plus `extra`, when a memo is
    given. test_checks.py passes one so that a damaged copy of the model only recomputes what touches the damaged part;
    the objects are kept in the entry, so their ids cannot be reused, and a hit must be the very same objects."""
    if memo is None:
        return fn(*args)
    key = (tag,) + tuple(id(o) for o in objs) + tuple(extra)
    hit = memo.get(key)
    if hit is not None and len(hit[0]) == len(objs) and all(x is y for x, y in zip(hit[0], objs)):
        return hit[1]
    val = fn(*args)
    memo[key] = (tuple(objs), val)
    return val


def inter_vol(a, b):
    """Volume of a x b in mm^3. Raises BooleanFailure when the answer cannot be trusted:
    intersect() raised, or it found nothing for two shapes whose boxes overlap and that are not
    provably apart (distance() > 0) while a second boolean (cut) says material is shared."""
    ba, bb = bbox_of(a), bbox_of(b)
    try:
        c = a.intersect(b)
    except Exception as e:      # noqa: BLE001
        raise BooleanFailure(f"intersect() raised {type(e).__name__}: {e}") from e
    solids = [] if (c is None or c.isNull()) else c.Solids()
    if solids:
        return float(sum(s.Volume() for s in solids))
    if bbox_overlap(ba, bb) <= BBOX_TOL:
        return 0.0                         # boxes share no interior: nothing can overlap
    if solid_distance(a, b) > BBOX_TOL:
        return 0.0                         # boxes overlap but the shapes are apart
    try:                                   # touching or overlapping: ask a second boolean
        shared = float(a.Volume()) - float(a.cut(b).Volume())
    except Exception as e:      # noqa: BLE001
        raise BooleanFailure(f"intersect() found nothing for touching shapes and cut() raised "
                             f"{type(e).__name__}: {e}") from e
    if shared > CROSS_VOL:
        raise BooleanFailure(f"intersect() found nothing but cut() removes {shared:.2f} mm3")
    return 0.0


def mass_estimate(solid, material="ABS"):
    """(volume cm3, mass g at 100 %, mass g at 4 walls / 20 % infill) for a part in `material` (DENSITY)."""
    rho = DENSITY[material]
    vol_mm3 = float(solid.Volume())
    area = float(solid.Area())
    vol_cm3 = vol_mm3 / 1000.0
    m100 = vol_cm3 * rho
    shell = min(area * WALL_T, vol_mm3)
    inner = max(vol_mm3 - shell, 0.0)
    m20 = (shell + INFILL * inner) / 1000.0 * rho
    return vol_cm3, m100, m20


# ---------------------------------------------------------------------------
# Holes: where the bore runs through material, is it empty, how thick is the wall
# ---------------------------------------------------------------------------
SPAN_STEP = 0.25         # mm between samples along the bore axis
SPAN_MARGIN = 0.05       # mm: wall rings stop this far from a face so end faces do not coincide
BORE_SHRINK = 0.1        # mm off the bore radius when probing it for material (no coincident surfaces)
BORE_EPS = 0.5           # mm^3 of material tolerated inside a bore
WALL_EPS = 0.5           # mm^3 of missing material tolerated in the wall ring
MOUNT_TOL = 0.2          # mm, axis point to hole wall, derived hardware mounts (check 5)


def material_spans(blank, hole):
    """(t0, t1) intervals along the bore where its axis runs inside the part's undrilled material."""
    if hole._spans is not None and hole._spans[0] is blank:
        return hole._spans[1]

    def inside(t):
        return blank.isInside(Vector(*hole.point(t)))

    n = int(math.ceil(hole.length / SPAN_STEP))
    ts = [min(i * SPAN_STEP, hole.length) for i in range(n + 1)]
    flags = [inside(t) for t in ts]

    def edge(lo, hi, want_lo):
        for _ in range(16):
            mid = (lo + hi) / 2
            if inside(mid) == want_lo:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    spans, start = [], (ts[0] if flags[0] else None)
    for i in range(1, len(ts)):
        if flags[i] and not flags[i - 1]:
            start = edge(ts[i - 1], ts[i], False)
        elif not flags[i] and flags[i - 1]:
            spans.append((start, edge(ts[i - 1], ts[i], True)))
            start = None
    if start is not None:
        spans.append((start, ts[-1]))
    spans = [(a + SPAN_MARGIN, b - SPAN_MARGIN) for a, b in spans if b - a > 2 * SPAN_MARGIN + 0.02]
    hole._spans = (blank, spans)
    return spans


def wall_deficit(solid, hole, spans, wall):
    """mm^3 of the ring of thickness `wall` around the bore (over its material spans) that is not solid."""
    total = 0.0
    R = hole.r + wall
    for (a, b) in spans:
        outer = cyl(hole.point(a), hole.d, 2 * R, b - a)
        want = math.pi * (R * R - hole.r * hole.r) * (b - a)
        total += max(0.0, want - inter_vol(solid, outer))
    return total


def measured_wall(solid, hole, spans):
    lo, hi = 0.0, hole.wall
    for _ in range(9):
        mid = (lo + hi) / 2
        if wall_deficit(solid, hole, spans, mid) > WALL_EPS:
            hi = mid
        else:
            lo = mid
    return lo


def check_hole(p, h):
    """Failure lines (CHECK7) of one recorded hole of part `p`; empty when it is drilled and keeps its wall."""
    label = f"{p.name}: {h.describe()}"
    out = []
    try:
        spans = material_spans(p.blank, h)
        if not spans:
            return [f"CHECK7 {label} does not run through this part's material"]
        probe = cyl(h.start, h.d, 2 * (h.r - BORE_SHRINK), h.length)
        v = inter_vol(p.solid, probe)
        if v >= BORE_EPS:
            return [f"CHECK7 {label} is not drilled: {v:.1f} mm3 of material inside the bore"]
        if wall_deficit(p.solid, h, spans, h.wall) > WALL_EPS:
            w = measured_wall(p.solid, h, spans)
            out.append(f"CHECK7 {label} has wall {w:.2f} mm < {h.wall} mm (to the surface or to the next hole)")
    except BooleanFailure as e:
        out.append(f"CHECK7 {label}: BOOLEAN FAILED: {e}")
    return out


def check_holes(parts, failures, memo=None):
    """Every recorded hole: lies in the part's material, is empty, and keeps the minimum wall to the
    surface and to every other hole (a neighbouring hole is void inside the ring, so it counts)."""
    n = 0
    for p in parts:
        for h in p.holes:
            n += 1
            failures += memo_call(memo, (p.solid, p.blank, h), "hole", check_hole, p, h)
    return n


# ---------------------------------------------------------------------------
# Check 5: mounts derived from the solids
# ---------------------------------------------------------------------------
DRIVE_SCREWS = sum(len(fc["holes"]) for fc in hw.drive_layout()["faces"].values())          # per bay: 6 on the 3.5 inch drive + 4 on the 2.5 inch drive
EXPECTED_MOUNTS = {"board": 9, "rad420": 2 * len(antler_holes_xn(1)), "rad360": 4, "psu": 4, "gpu_post": 2, "gpu_rest": 1, "front_io": 2, "organic": 12,
                   "tie_pilot": len(TIE_POINTS), "tie_bridge": len(TIE_POINTS), **{k: DRIVE_SCREWS for k in hw.DRIVES}}
ORGANIC_PROBE_DEPTH = 3.0      # check 5: the axis point of a pad's pilot lies this far in from the face
MIN_MOUNTS = {"fan_side_left": FAN_MIN_SCREWS, "fan_side_right": FAN_MIN_SCREWS}     # at least this many of the four corner holes
FAN_HOLDER = {"fan_side_left": "fan_bracket_left", "fan_side_right": "fan_bracket_right"}
DRIVE_PROBE_DEPTH = 1.5        # check 5: the axis point of a drive screw lies this far into the boss and plate from the drive's board (the boss is 1 mm high, the bore is empty to the head)
FAN_PROBE_DEPTH = 1.5          # axis point inside the pilot, from the fan face: the pilot is 5.0 deep, so at 1.5 the bore wall (r 2.8) is the nearest material


def mount_points():
    """(item, holder part, point on the hole axis inside the holder's thickness, hole radius, corner) for every
    mounting position, read from hardware.py's tables as they are at the moment of the call."""
    out = []
    for (v, u) in hw.ATX_HOLES:
        holder = next((nm for nm, row in BEAM_ROW.items() if abs(row - u) < 1e-6), None)
        out.append(("board", holder, hw.bp(v, u, hw.ATX_BOARD_N - 3.0), hw.M3_PILOT_D / 2, None))
    for side, holder in ((1, "antler_right"), (-1, "antler_left")):
        for (x, n) in antler_holes_xn(side):
            out.append(("rad420", holder, hw.bp(hw.x_to_v(x), ANTLER_U[0] + ANTLER_T / 2, n), hw.M3_CLEAR_D / 2, None))
    for holder, x in (("visor_arm_right", max(hw.RAD360_HOLES_X)), ("visor_arm_left", min(hw.RAD360_HOLES_X))):
        for u in hw.RAD360_HOLES_U:
            out.append(("rad360", holder, hw.bp(hw.x_to_v(x), u, ARM_MID_N), hw.M3_CLEAR_D / 2, None))
    for (x, z) in hw.PSU_HOLES:
        out.append(("psu", "psu_bulkhead", (x, hw.PSU_REAR_Y + BULK_T / 2, z), hw.M3_CLEAR_D / 2, None))
    for (pt, d) in hw.FRONT_IO_SCREWS:      # the module's screws: the axis point inside the pocket's end wall, which must be an empty bore of the insert's radius
        probe = tuple(c + k * (SILL_POCKET_PLAY + SILL_PROBE_DEPTH) for c, k in zip(pt, d))
        out.append(("front_io", "front_sill", probe, hw.INSERTS[hw.FRONT_IO_SCREW_KIND][0] / 2, None))
    for (holder, (x, y, z), sgn) in hw.ORGANIC_PADS.values():      # the organic layer's pads: the axis point inside the pilot, which must be an empty bore of the insert's radius
        out.append(("organic", holder, (x - sgn * ORGANIC_PROBE_DEPTH, y, z), hw.M3_PILOT_D / 2, None))
    for tp in TIE_POINTS:      # the cable tie points: an empty M3 pilot bore in the host (axis point 3 mm in from the underside) and an empty clearance bore in the bridge's foot, on the same axis
        pt = tie_face_point(tp)
        out.append(("tie_pilot", tp["host"], tuple(c - ORGANIC_PROBE_DEPTH * k for c, k in zip(pt, tp["normal"])), hw.M3_PILOT_D / 2, None))
        out.append(("tie_bridge", tie_name(tp), tuple(c + TIE_FOOT_T / 2 * k for c, k in zip(pt, tp["normal"])), hw.M3_CLEAR_D / 2, None))
    for item, side in zip(hw.DRIVES, hw.DRIVE_SIDES.values()):      # the drives' screws: an empty clearance bore on the axis, 1.5 mm into the sled from the drive's board
        for fc in hw.drive_layout()["faces"].values():
            for (y, z) in fc["holes"]:
                out.append((item, "drive_sled_" + item.split("_")[1], (side * (fc["pb_x"] - fc["dir"] * DRIVE_PROBE_DEPTH), y, z), hw.M3_CLEAR_D / 2, None))
    for fan, holder in FAN_HOLDER.items():
        x = hw.FAN_SIDE_INNER_X[fan] + hw.FAN_SIDE_IN[fan] * FAN_PROBE_DEPTH
        x_out = hw.FAN_SIDE_X[fan][0 if hw.FAN_SIDE_IN[fan] > 0 else 1]
        x_tab = x_out - hw.FAN_SIDE_IN[fan] * TAB_T / 2                      # mid-thickness of a tab over the fan's outer face
        for corner, (u, n) in hw.FAN_SIDE_HOLES_UN.items():
            # inner face: an insert pilot in the plate. Outer face: a clearance hole in a tab (revision 7a), looked for at every corner
            # of every fan; a corner counts once if either has a hole. The fan's flat outer face has no material at the probe.
            out.append((fan, holder, hw.bp(hw.x_to_v(x), u, n), hw.M4S_PILOT_D / 2, corner))
            out.append((fan, holder, hw.bp(hw.x_to_v(x_tab), u, n), hw.M4_CLEAR_D / 2, corner))
    return out


def hole_at(part, pt, r):
    """None if the solid has an empty bore of radius r whose axis passes through pt, else why not."""
    if part.solid.isInside(Vector(*pt)):
        return "the axis point is inside material"
    d = solid_distance(cq.Vertex.makeVertex(*pt), part.solid)
    if abs(d - r) > MOUNT_TOL:
        return f"the axis point is {d:.2f} mm from material, a hole of radius {r:.2f} needs {r:.2f} +- {MOUNT_TOL}"
    return None


def derive_mounts(parts, contacts, failures, memo=None):
    """Count, per hardware item, the mounting positions of hardware.py that have a hole in their holder."""
    byname = {p.name: p for p in parts}
    got = {k: 0 for k in list(EXPECTED_MOUNTS) + list(MIN_MOUNTS)}
    fan_corners: dict = {k: set() for k in MIN_MOUNTS}          # corners with a hole on either face
    for item, holder, pt, r, corner in mount_points():
        part = byname.get(holder)
        if part is None:
            failures.append(f"CHECK5 {item} at ({pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f}): no holder part {holder}")
            continue
        try:
            why = memo_call(memo, (part.solid,), "mount", hole_at, part, pt, r, extra=(tuple(pt), r))
        except BooleanFailure as e:
            failures.append(f"CHECK5 {item} in {holder}: BOOLEAN FAILED: {e}")
            continue
        if why and item in MIN_MOUNTS:
            pass                    # a fan corner without a screw is allowed: only the count is checked, below
        elif why:
            failures.append(f"CHECK5 {item} position ({pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f}) has no hole in "
                            f"{holder}: {why}")
        elif corner is not None:
            fan_corners[item].add(corner)
        else:
            got[item] += 1
    for item, cs in fan_corners.items():
        got[item] = len(cs)
    # card: the bracket post is bolted to beam_mid at both screws, the right rib's finger touches the card
    if "gpu_post" in byname and "beam_mid" in byname:
        for u in GPU_POST_U:
            try:
                pt_post, pt_beam = hw.bp(GPU_POST_V, u, hw.ATX_TRAY_N + 4.0), hw.bp(GPU_POST_V, u, BEAM_N_MID)
                why_post = memo_call(memo, (byname["gpu_post"].solid,), "mount", hole_at, byname["gpu_post"], pt_post,
                                     hw.M4_PILOT_D / 2, extra=(tuple(pt_post), hw.M4_PILOT_D / 2))
                why_beam = memo_call(memo, (byname["beam_mid"].solid,), "mount", hole_at, byname["beam_mid"], pt_beam,
                                     hw.M4_CLEAR_D / 2, extra=(tuple(pt_beam), hw.M4_CLEAR_D / 2))
            except BooleanFailure as e:
                failures.append(f"CHECK5 gpu_post screw at u = {u}: BOOLEAN FAILED: {e}")
                continue
            if why_post or why_beam:
                failures.append(f"CHECK5 gpu_post screw at u = {u}: post {why_post or 'ok'}; beam_mid {why_beam or 'ok'}")
            else:
                got["gpu_post"] += 1
    if ("rib_A_right", "gpu") in contacts:
        got["gpu_rest"] = 1
    for item, n in EXPECTED_MOUNTS.items():
        if got[item] != n:
            failures.append(f"CHECK5 {item}: {got[item]} positions have a hole in the solids, the plan needs {n}")
    for item, n in MIN_MOUNTS.items():
        if got[item] < n:
            failures.append(f"CHECK5 {item}: {got[item]} of 4 corner holes have a screw hole in {FAN_HOLDER[item]}, the plan needs at least {n}")
    # the hand-written registry must agree with what the solids show
    registry = {"board": "board", "rad420": "rad420", "rad360": "rad360", "psu": "psu", "front_io": "front_io",
                "fan_side_left": "fan_side_left", "fan_side_right": "fan_side_right", "gpu": "gpu_post",
                "organic": "organic", "tie_pilot": "tie_pilot", "tie_bridge": "tie_bridge",
                **{k: k for k in hw.DRIVES}}       # fastener item -> derived item
    for item, derived_item in registry.items():
        listed = sum(f["count"] for f in FASTENERS if f["item"] == item)
        if listed != got[derived_item]:
            failures.append(f"CHECK5 {item}: the fastener list says {listed}, the solids show {got[derived_item]}")
    return got


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
# zero-gap contacts the plan describes (part, hardware)
INTENDED_CONTACTS = {
    ("beam_low", "board"), ("beam_mid", "board"), ("beam_top", "board"),     # standoff bosses
    ("fan_bracket_left", "fan_side_left"), ("fan_bracket_right", "fan_side_right"),     # the plate on the fan's inner face
    ("skid_front", "psu"), ("skid_rear", "psu"), ("psu_bulkhead", "psu"),
    ("rib_A_right", "gpu"),                                                  # gpu_rest finger
    ("beam_front", "front_io"),                                              # revision 9: the module's underside (Z 10, placeholder) is beam_front's top face
    ("visor_arm_right", "rad360"), ("visor_arm_left", "rad360"),
    ("antler_right", "rad420"), ("antler_left", "rad420"),
    *((f"drive_sled_{bay}", f"drive_{bay}") for bay in hw.DRIVE_SIDES),            # the bosses' tops carry the drives' boards
}
# part-part zero-gap contacts are all planned (lap, member ends, antler tongue, pad, post-on-beam)


TIE_CLEAR = 2.0          # mm: a bridge keeps this from every part but its host and from every hardware solid (a contact is intended only where the plan lists it)


def check_tie_bridges(parts, hardware, pb, hb, contacts, pp_contact, failures, memo=None):
    """Check 3b. One zero-gap contact is planned per bridge: its foot on its host's underside (it is screwed there). Any other contact is a failure, and so is any other
    part or hardware solid within TIE_CLEAR. Returns [(bridge, host, nearest other name, its distance)]."""
    byname = {p.name: p for p in parts}
    rows = []
    for tp in TIE_POINTS:
        name, host = tie_name(tp), tp["host"]
        b = byname.get(name)
        if b is None:
            failures.append(f"CHECK3 tie bridge {name}: not in the parts list")
            continue
        touching = {y if x == name else x for (x, y) in pp_contact if name in (x, y)}
        if touching != {host}:
            failures.append(f"CHECK3 tie bridge {name} touches {sorted(touching) or 'nothing'}, the plan lists only its host {host}")
        for (a, hn) in contacts:
            if a == name:
                failures.append(f"CHECK3 tie bridge {name} touches hardware {hn}: no contact with hardware is planned")
        near = (None, float("inf"))
        for tag, items in (("part", [(q.name, q.solid, pb[q.name]) for q in parts if q.name not in (name, host)]),
                           ("hw", [(k, v, hb[k]) for k, v in hardware.items()])):
            for qn, qs, qb in items:
                if bbox_gap(pb[name], qb) > TIE_CLEAR + 4.0:
                    continue
                d = _guard(failures, "CHECK3", f"tie bridge {name} x {qn}", memo_call, memo, (b.solid, qs), "dist", solid_distance, b.solid, qs)
                if d is None:
                    continue
                if d < near[1]:
                    near = (qn, d)
                if d < TIE_CLEAR - 1e-6:
                    failures.append(f"CHECK3 tie bridge {name} is {d:.2f} mm from {qn}, needs {TIE_CLEAR:g}")
        rows.append((name, host, near[0], near[1]))
    return rows


def _guard(failures, tag, label, fn, *args):
    """Run fn; a BooleanFailure becomes a named check failure and the result is None."""
    try:
        return fn(*args)
    except BooleanFailure as e:
        failures.append(f"{tag} {label}: BOOLEAN FAILED: {e}")
        return None


_NMAX: dict = {}


def part_n_max(p):
    """Highest board-space n of a part (the solid expressed in board space). Cached per solid object, which stays
    referenced by the cache so its id cannot be reused."""
    hit = _NMAX.get(id(p.solid))
    if hit is None or hit[0] is not p.solid:
        hit = (p.solid, float(hw.to_board(p.solid).BoundingBox().zmax))
        _NMAX[id(p.solid)] = hit
    return hit[1]


def check_envelope(parts, hardware, pb, hb, failures):
    """Check 8. Returns {'parts': (max |X|, part, min Y, part), 'hoses': (...), 'top': ...}. The 'top' entry is the
    frame's highest Z (part), the highest n (part) against the 420's top face, and the 420's highest Z."""
    out = {}
    n_top = max((part_n_max(p), p.name) for p in parts)
    z_top = max((pb[p.name][5], p.name) for p in parts)
    out["top"] = (z_top[0], z_top[1], n_top[0], n_top[1], hb["rad420"][5] if "rad420" in hb else float("nan"))
    for p in parts:
        n = part_n_max(p)
        if n > hw.ENVELOPE_N + 1e-6:
            failures.append(f"CHECK8 {p.name} rises above the 420's top face: n = {n:.2f}, limit {hw.ENVELOPE_N:g}")
    for tag, items in (("parts", [(p.name, pb[p.name]) for p in parts]),
                       ("hoses", [(k, hb[k]) for k in hw.HOSES if k in hb]),
                       ("front", [(k, hb[k]) for k in hw.FRONT_HARDWARE if k in hb])):
        if not items:
            continue
        mx = max(((max(abs(b[0]), abs(b[1])), n) for n, b in items))
        my = min(((b[2], n) for n, b in items))
        out[tag] = (mx[0], mx[1], my[0], my[1])
        for n, b in items:
            if max(abs(b[0]), abs(b[1])) > hw.ENVELOPE_X + 1e-6:
                failures.append(f"CHECK8 {n} reaches |X| = {max(abs(b[0]), abs(b[1])):.2f}, limit {hw.ENVELOPE_X:g}")
            if b[2] < hw.ENVELOPE_Y0 - 1e-6:
                failures.append(f"CHECK8 {n} reaches Y = {b[2]:.2f}, in front of {hw.ENVELOPE_Y0:g}")
    return out


def check_hose_clearance(parts, hardware, pb, hb, failures, memo=None):
    """Check 9. Distance of every part that is not a guide to each hose keep-out; returns the list of
    (part, hose, distance) for every pair within 30 mm."""
    rows = []
    for p in parts:
        if p.name in GUIDE_PARTS:
            continue
        for hn in hw.HOSES:
            if hn not in hardware or bbox_gap(pb[p.name], hb[hn]) > 30.0:
                continue
            d = _guard(failures, "CHECK9", f"part x hose {p.name} x {hn}", memo_call, memo, (p.solid, hardware[hn]), "dist",
                       solid_distance, p.solid, hardware[hn])
            if d is None:
                continue
            rows.append((p.name, hn, d))
            if d < HOSE_CLEAR - 1e-6:
                failures.append(f"CHECK9 {p.name} is {d:.2f} mm from {hn}, needs {HOSE_CLEAR:g}")
    return sorted(rows, key=lambda r: r[2])


_TUBES: dict = {}


def hose_tube(line, r):
    """The sweep with round joints; on the CPU hose B at its true radius OCC makes an invalid solid of it, so the
    mitred sweep ("right") is used then (volume within 0.01 % of pi r^2 L, joints turn by under 20 deg)."""
    try:
        return hw.hose_chain(line, r)
    except AssertionError:
        return hw.hose_chain(line, r, transition="right")


def true_tubes():
    """{'cpu_hoses': [tube, tube], 'gpu_hoses': [...]}: the route of hoses.py swept with the hose's own radius, not the
    keep-out radius. They are for check 10 only and never go into the hardware keep-outs."""
    if not _TUBES:
        chains = hoses.keepout_chains()
        for name, lines in chains.items():
            r = hw.CPU_HOSE_R if name == "cpu_hoses" else hw.GPU_HOSE_R
            _TUBES[name] = [hose_tube(line, r) for line in lines]
    return _TUBES


def mouth_probe(pair, idx, u, side, width):
    """A slab along the hose from its axis outwards through the open side of a guide, `width` wide and 10 mm long."""
    r_h = guide_hose_r(pair)
    p, d, _ = hose_at(pair, idx, u)
    ex = np.array([side, 0.0, 0.0])
    ex = ex - float(ex @ d) * d
    ex = ex / float(np.linalg.norm(ex))
    org = p - 5.0 * d
    plane = cq.Plane(origin=tuple(org), xDir=tuple(ex), normal=tuple(d))
    return cq.Workplane(plane).center(15.0, 0).rect(30.0, width).extrude(10.0).val()


GUIDE_SPEC = {"hose_guide_cpu": ("cpu", "cpu_hoses", -1, sum(GUIDE_CPU_U) / 2),
              "hose_guide_gpu": ("gpu", "gpu_hoses", 1, sum(GUIDE_GPU_U) / 2)}
MOUTH_TOL = 0.4         # mm: a slab this much narrower than the mouth must pass it, one this much wider must not


def check_guides(parts, failures, memo=None):
    """Check 10. For each hose guide and each hose it holds: the guide's solid does not intersect a tube of the true hose
    radius (volume < VOL_EPS), the channel wall is GUIDE_WALL_MIN..GUIDE_WALL_MAX from that tube, and the mouth is
    GUIDE_MOUTH x the hose diameter wide. Returns rows (guide, hose index, overlap mm3, wall mm, mouth ok)."""
    rows = []
    tubes = true_tubes()
    for p in parts:
        if p.name not in GUIDE_SPEC:
            continue
        pair, hose_name, side, u_mid = GUIDE_SPEC[p.name]
        mouth = GUIDE_MOUTH * 2 * guide_hose_r(pair)
        for i, tube in enumerate(tubes[hose_name]):
            label = f"{p.name} x {hose_name}[{i}]"
            v = _guard(failures, "CHECK10", label, memo_call, memo, (p.solid, tube), "iv", inter_vol, p.solid, tube)
            d = _guard(failures, "CHECK10", label, memo_call, memo, (p.solid, tube), "dist", solid_distance, p.solid, tube)
            def probe_vol(w):
                try:
                    return memo_call(memo, (p.solid,), "mouth", lambda: inter_vol(p.solid, mouth_probe(pair, i, u_mid, side, w)),
                                     extra=(pair, i, round(w, 4)))
                except BooleanFailure as e:
                    failures.append(f"CHECK10 {label}: BOOLEAN FAILED: {e}")
                    return None
            narrow, wide = probe_vol(mouth - MOUTH_TOL), probe_vol(mouth + MOUTH_TOL)
            if None in (v, d, narrow, wide):
                continue
            mouth_ok = narrow < VOL_EPS and wide >= VOL_EPS
            rows.append((p.name, i, v, d, mouth_ok))
            if v >= VOL_EPS:
                failures.append(f"CHECK10 {label}: the guide intersects the true hose by {v:.1f} mm3")
            if not GUIDE_WALL_MIN <= d <= GUIDE_WALL_MAX:
                failures.append(f"CHECK10 {label}: channel wall is {d:.2f} mm from the true hose, needs "
                                f"{GUIDE_WALL_MIN:g}..{GUIDE_WALL_MAX:g}")
            if not mouth_ok:
                failures.append(f"CHECK10 {label}: the mouth is not {mouth:.1f} mm wide (a {mouth - MOUTH_TOL:.1f} mm slab "
                                f"overlaps {narrow:.1f} mm3, a {mouth + MOUTH_TOL:.1f} mm slab {wide:.1f} mm3)")
    return rows


def aperture_cylinder(fan):
    """The fan's open circle (hardware.FAN_APERTURE_D) as a cylinder along X, from 20 mm past the fan's outer face to 60 mm
    inside its inner face: long enough to cover a bracket's plate and its leg. It is a probe, not hardware."""
    face, d = hw.FAN_SIDE_INNER_X[fan], hw.FAN_SIDE_IN[fan]
    x_out_face = hw.FAN_SIDE_X[fan][0 if d > 0 else 1]
    y, z = hw.bp_yz(*hw.FAN_CENTRE_UN)
    x0, x1 = sorted((x_out_face - d * 20.0, face + d * 60.0))
    return cyl((x0, y, z), (1, 0, 0), hw.FAN_APERTURE_D, x1 - x0)


def check_apertures(parts, failures, memo=None):
    """Check 11. No bracket material inside the open circle of its fan. Returns rows (bracket, overlap mm3, distance mm)."""
    rows = []
    for p in parts:
        fan = BRACKET_FAN.get(p.name)
        if fan is None:
            continue
        cylinder = aperture_cylinder(fan)
        v = _guard(failures, "CHECK11", f"{p.name} x aperture of {fan}", inter_vol, p.solid, cylinder)
        d = _guard(failures, "CHECK11", f"{p.name} x aperture of {fan}", solid_distance, p.solid, cylinder)
        if v is None or d is None:
            continue
        rows.append((p.name, v, d))
        if v >= VOL_EPS:
            failures.append(f"CHECK11 {p.name} has {v:.1f} mm3 inside the open circle of {fan} (diameter {hw.FAN_APERTURE_D:g})")
    return rows


# ---------------------------------------------------------------------------
# Check 14 (revision 11): the 420's bracket plates leave the fans' openings clear and keep the wall round every fan screw
# ---------------------------------------------------------------------------
MIN_WEB = 2.0              # nothing of an antler may be narrower than this, measured on its section at the plate's mid-plane (revision 11, second pass)
WEB_RES = 0.1              # mm per pixel of that section; the radius found is good to about one pixel, so a failure is a web under MIN_WEB - 0.1


def web_section(solid, res=WEB_RES):
    """The section of `solid` by the plane through the plate's middle (u = ANTLER_U mid), rasterised in (X, n): (mask, xs, ns, res)."""
    import trimesh
    from matplotlib.path import Path
    vs, fs = tessellate(solid, 0.05)
    mesh = trimesh.Trimesh(vs, fs, process=False)
    sec = mesh.section(plane_origin=np.array(hw.bp(0.0, sum(ANTLER_U) / 2.0, 0.0)), plane_normal=np.array(hw.U_DIR))
    loops = [np.array([(q[0], un_of(q[1], q[2])[1]) for q in line]) for line in (sec.discrete if sec is not None else [])]
    if not loops:
        return np.zeros((1, 1), bool), np.zeros(1), np.zeros(1), res
    allp = np.vstack(loops)
    xs = np.arange(allp[:, 0].min() - 1.0, allp[:, 0].max() + 1.0, res)
    ns = np.arange(allp[:, 1].min() - 1.0, allp[:, 1].max() + 1.0, res)
    X, N = np.meshgrid(xs, ns)
    P = np.c_[X.ravel(), N.ravel()]
    mask = np.zeros(len(P), bool)
    for lp in loops:
        mask ^= Path(lp).contains_points(P)             # even-odd: an inner loop is a hole
    return mask.reshape(X.shape), xs, ns, res


def narrow_pieces(section, r):
    """Pieces of the section that no disc of radius r fits in, other than the tips of its corners: the section opened by a disc of radius r, what is left of it
    opened by a disc of 0.5 mm (a corner's tip is thinner than that, a web is not). Returns [(area mm2, (x0, x1), (n0, n1))]."""
    from scipy import ndimage
    mask, xs, ns, res = section
    core = ndimage.distance_transform_edt(mask) * res >= r
    left = mask & ~(ndimage.distance_transform_edt(~core) * res <= r)
    kept = ndimage.distance_transform_edt(left) * res >= 0.5
    left = left & (ndimage.distance_transform_edt(~kept) * res <= 0.5)
    lab, k = ndimage.label(left)
    out = []
    for i in range(1, k + 1):
        yy, xx = np.where(lab == i)
        out.append((len(yy) * res * res, (float(xs[xx.min()]), float(xs[xx.max()])), (float(ns[yy.min()]), float(ns[yy.max()]))))
    return out


def narrowest_web(solid):
    """(width mm, (x range), (n range)) of the narrowest web of the section: the widest disc (bisection, 0.02 mm) that fits everywhere but in a corner's tip.
    Returns (inf, None, None) when no piece is narrower than 3 mm."""
    section = web_section(solid)
    lo, hi = 0.5, 1.5
    if not narrow_pieces(section, hi):
        return float("inf"), None, None
    for _ in range(6):
        mid = (lo + hi) / 2.0
        lo, hi = (mid, hi) if not narrow_pieces(section, mid) else (lo, mid)
    pieces = narrow_pieces(section, hi)
    big = max(pieces, key=lambda q: q[0]) if pieces else (0.0, None, None)
    return 2.0 * hi, big[1], big[2]


def check_420_plates(parts, failures, memo=None):
    """Check 14. (a) No antler material inside the open air path of any of the 420's three fans (hardware.rad420_fan_opening: a circle of
    140 cut to 136 across the flats, probed through the whole stack u 310..378, so the plate, the chord and the tongue are all measured).
    (b) Every one of the twelve fan screws has its wall of material round the hole (the part's own wall rule, measured on the solid).
    Returns {'openings': [(part, fan k, overlap mm3, distance mm)], 'screws': [(part, x, n, ok)]}."""
    out = {"openings": [], "screws": []}
    probes = [hw.rad420_fan_opening(k, hw.RAD420_BS[2], hw.RAD420_BS[3]) for k in range(len(hw.RAD420_FAN_X))]
    n_ok = 0
    for p in parts:
        if not p.name.startswith("antler"):
            continue
        for k, probe in enumerate(probes):
            v = _guard(failures, "CHECK14", f"{p.name} x opening of fan {k}", inter_vol, p.solid, probe)
            d = _guard(failures, "CHECK14", f"{p.name} x opening of fan {k}", solid_distance, p.solid, probe)
            if v is None or d is None:
                continue
            out["openings"].append((p.name, k, v, d))
            if v >= VOL_EPS:
                failures.append(f"CHECK14 {p.name} has {v:.1f} mm3 inside the opening of the 420's fan {k} (centre X {hw.RAD420_FAN_X[k]:g})")
        for h in p.holes:
            if abs(abs(float(np.dot(h.d, hw.U_DIR))) - 1.0) > 1e-6:
                continue                      # the tongue's bolts run along X: not fan screws
            try:
                spans = material_spans(p.blank, h)
                deficit = wall_deficit(p.solid, h, spans, h.wall) if spans else float("inf")
            except BooleanFailure as e:
                failures.append(f"CHECK14 {p.name}: {h.describe()}: BOOLEAN FAILED: {e}")
                continue
            ok = bool(spans) and deficit <= WALL_EPS
            n_ok += ok
            pt = h.point(OVERSHOOT)
            out["screws"].append((p.name, pt, ok))
            if not ok:
                failures.append(f"CHECK14 {p.name}: the fan screw at ({pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f}) has no wall of {h.wall:g} mm of plate round it")
    need = 2 * len(antler_holes_xn(1))
    if n_ok != need:
        failures.append(f"CHECK14 {n_ok} of the {need} fan screws of the 420 have their wall of plate round them")
    # (c) no sliver: nothing of an antler (the blank, before its holes: the wall round a hole is the hole check's) is narrower than MIN_WEB
    out["webs"] = []
    for p in parts:
        if p.name.startswith("antler"):
            w, xr, nr = _guard(failures, "CHECK14", f"{p.name} narrowest web", memo_call, memo, (p.blank if p.blank is not None else p.solid,), "web", narrowest_web,
                               p.blank if p.blank is not None else p.solid) or (float("nan"), None, None)
            out["webs"].append((p.name, w, xr, nr))
            if w < MIN_WEB - 0.1:
                failures.append(f"CHECK14 {p.name} has a web {w:.2f} mm wide at |X| {abs(xr[0]):.1f}..{abs(xr[1]):.1f}, n {nr[0]:.1f}..{nr[1]:.1f}: nothing of the plate may be narrower than {MIN_WEB:g} mm")
    # (d) the chord and the plate's lower edge keep CHORD_FAN_GAP clear of the fans' underside (n -16) wherever they stand under the fans
    air = hw.bs_box(*hw.RAD420_FAN_V, *hw.RAD420_FAN_U, hw.RAD420_FAN_N[0] - CHORD_FAN_GAP + 0.01, hw.RAD420_FAN_N[0] - 0.01)
    out["underside"] = []
    for p in parts:
        if p.name.startswith("antler"):
            v = _guard(failures, "CHECK14", f"{p.name} x the fans' underside", memo_call, memo, (p.solid, air), "iv", inter_vol, p.solid, air)
            if v is None:
                continue
            out["underside"].append((p.name, v))
            if v >= VOL_EPS:
                failures.append(f"CHECK14 {p.name} has {v:.1f} mm3 within {CHORD_FAN_GAP:g} mm below the underside of the 420's fans (n {hw.RAD420_FAN_N[0]:g}): the chord must keep clear of them")
    return out


# ---------------------------------------------------------------------------
# Check 12 (revision 8): sharp outline corners that remain on the plates
# ---------------------------------------------------------------------------
PLATE_PREFIXES = ("rib_A", "rib_B", "neck_", "visor_arm", "antler", "fan_bracket")      # the parts whose outlines are rounded
CORNER_CLASSES = ("lap", "allowance", "hole", "nofit", "kernel", "declared", "junction", "contact", "open")
_REF_PARTS: dict = {}


def plate_axes(name):
    """Extrusion directions of a plate's outline: the edges that run along them are its outline corners. None for the other parts."""
    if not name.startswith(PLATE_PREFIXES):
        return None
    return [(1.0, 0.0, 0.0)] + ([tuple(hw.U_DIR)] if name.startswith("antler") else [])


def bracket_join_x(name):
    """|X| of the plate's face towards the rib, where the bracket's leg joins it."""
    plate, _, _, d = fan_bracket_geometry(name)
    return abs(plate[0] if d < 0 else plate[1])


def plate_accept(name):
    """A filter for sharp_axial_edges: drops edges that run along an extrusion direction without being an outline corner.
    antler: the plate and the chord are extruded along u (their corners are edges along u) and the tongue along X (X 158..168); the tongue's
    rim edges along u (X 158 and 168, below the chord) and the plate's and chord's long rim edges along X are not corners.
    visor_arm_right: the 5 mm step of the notch is a cut, not an outline corner."""
    if name.startswith("antler"):
        lo, hi = TONGUE_X

        def accept(e):
            d = e["b"] - e["a"]
            xs = sorted((abs(float(e["a"][0])), abs(float(e["b"][0]))))
            length = float(np.linalg.norm(d))
            if abs(float(d[0])) / length < 0.9999:
                if abs(float(np.dot(d, hw.U_DIR))) / length < 0.9999:
                    return False                                                # along n: a rim edge of the end rib, not an outline corner
                n = un_of(float(e["mid"][1]), float(e["mid"][2]))[1]            # along u: a corner of the plate, the chord or the rib, unless it is a rim edge of the tongue
                return not (xs[0] >= lo - 0.5 and xs[1] <= hi + 0.5 and n <= TONGUE_N[1] + 0.5)
            return xs[0] >= lo - 0.5 and xs[1] <= hi + 0.5                      # along X: a corner of the tongue only inside its X range
        return accept
    if name.startswith("visor_arm"):
        return lambda e: e["length"] > NECK_X[0] - ARM_NOTCH_X + 0.5
    return None


def reference_parts():
    """The skeleton as built without rounding, once (a copy of the registries is put back afterwards: build_frame resets them)."""
    if not _REF_PARTS:
        saved = (list(FASTENERS), list(BOLT_CHECKS), list(ROUND_LOG), {k: list(v) for k, v in KEEP_SHARP.items()})
        parts, _ = build_frame(rounded=False)
        FASTENERS[:], BOLT_CHECKS[:], ROUND_LOG[:] = saved[0], saved[1], saved[2]
        KEEP_SHARP.clear()
        KEEP_SHARP.update(saved[3])
        _REF_PARTS["parts"] = {p.name: p for p in parts}
    return _REF_PARTS["parts"]


_REF_SHARP: dict = {}


def ref_sharp(name):
    """Number of sharp outline corners on the unrounded part."""
    if name not in _REF_SHARP:
        _REF_SHARP[name] = len(rd.sharp_axial_edges(reference_parts()[name].solid, plate_axes(name), accept=plate_accept(name), caps=False))
    return _REF_SHARP[name]


def log_reason(p, y, z):
    """The ROUND_LOG reason why the outline corner of plate `p` at world (Y, Z) was left sharp, or None. Left parts are built right-handed and
    mirrored, so their log entries have the mirrored X; Y and Z are the same."""
    for e in ROUND_LOG:
        if e.radius == 0 and e.kind in ("convex", "concave") and e.part.startswith(p.name.split(" ")[0]) \
                and abs(e.pt[1] - y) < 0.6 and abs(e.pt[2] - z) < 0.6:
            return e.reason
    return None


def reason_class(text):
    """Short class of a ROUND_LOG reason for the report."""
    if text.startswith("it would take") or "flat contact around the screw" in text:
        return "allowance"
    if "hole" in text:
        return "hole"
    if text.startswith("no radius"):
        return "nofit"
    if "kernel" in text:
        return "kernel"
    return "other"


def classify_corners(p, others, memo=None):
    """Sharp outline corners of plate `p` and why each is allowed to stay: 'lap' (a step of a lap joint), 'allowance' (the corner's rounding would
    take more contact area than the 97 % floor leaves, or flat contact within 4 mm of a screw; ROUND_LOG says so), 'hole' (it would cut a
    hole's wall or the access to a screw head), 'nofit' (no radius of 2 mm or more fits between the neighbouring edges), 'kernel' (the
    kernel could not make the fillet), 'declared' (KEEP_SHARP, the bracket's rail group), 'junction' (the run-out of a fillet), 'contact'
    (a face of the part lies against hardware or another part within the reach of the largest radius and the log has no entry: a step cut
    by a neighbour), or 'open' (nothing excuses it). others: rounding.Neighbors of the hardware and the other parts."""
    edges = memo_call(memo, (p.solid,), "sharp", lambda: rd.sharp_axial_edges(p.solid, plate_axes(p.name), accept=plate_accept(p.name)))   # depends on the part alone
    patches = others.patches(p.solid.Faces(), bbox_of(p.solid), exclude=(p.name,)) if edges else []
    rows = []
    for e in edges:
        y, z = float(e["mid"][1]), float(e["mid"][2])
        on_zone_edge = any(((abs(y - y0) < 0.6 or abs(y - y1) < 0.6) and z0 - 0.6 <= z <= z1 + 0.6)
                           or ((abs(z - z0) < 0.6 or abs(z - z1) < 0.6) and y0 - 0.6 <= y <= y1 + 0.6)
                           for (y0, y1, z0, z1) in LAP_ZONES)
        in_zone = any(y0 - 0.6 <= y <= y1 + 0.6 and z0 - 0.6 <= z <= z1 + 0.6 for (y0, y1, z0, z1) in LAP_ZONES)
        logged = log_reason(p, y, z)
        if on_zone_edge and e["length"] <= RIB_T / 2 + 0.1:         # a step of the lap joint: half the rib's thickness long, on the zone's boundary
            why = "lap"
        elif p.name.startswith("rib_") and in_zone and e["length"] <= RIB_T / 2 + 0.1 and logged is None:
            why = "lap"                 # inside a lap zone, half the rib's thickness long, not a corner of the outline: the step where the rib's outline meets the other half's cut
        elif any(abs(y - dy) < 0.6 and abs(z - dz) < 0.6 for (dy, dz, _) in KEEP_SHARP.get(p.name, ())):
            why = "declared"
        elif p.name.startswith("fan_bracket") and p.name in BRACKET_TAB and (abs(float(e["mid"][0])) > BRACKET_RAIL_X + 0.5
                                                                            or un_of(y, z)[1] > hw.FAN_SIDE_N[1]):
            why = reason_class(logged) if logged else "declared"        # the rail group of the right bracket
        elif p.name.startswith("fan_bracket") and e["length"] <= 7.0 and abs(abs(float(e["mid"][0])) - bracket_join_x(p.name)) <= 7.0:
            why = "junction"            # the run-out of the leg-to-plate fillet: a few mm long next to the plate's face
        elif logged:
            why = reason_class(logged)
        elif any(rd.bbox_gap(rd.bbox_of(e["edge"]), rd.bbox_of(patch)) <= ROUND_CONCAVE
                 and solid_distance(e["edge"], patch) <= ROUND_CONCAVE + 1e-6 for _, patch in patches):
            why = "contact"             # a contact patch within reach of the largest radius, no log entry: the edge is a step where a neighbour's outline cut this one
        else:
            why = "open"
        rows.append((why, y, z, e["angle"], e["length"]))
    return rows


def check_corners(parts, hardware, pb, hb, failures, memo=None):
    """Check 12. Per plate: how many sharp outline corners it has now and how many its unrounded build has. Fails when a plate has no
    fewer (nothing was rounded). Returns rows (part, now, before). explain_corners() says why the remaining ones are allowed."""
    rows = []
    for p in parts:
        if plate_axes(p.name) is None:
            continue
        edges = _guard(failures, "CHECK12", p.name, memo_call, memo, (p.solid,), "sharp0",       # without the end caps: cheaper, and the count is all this needs
                       lambda: rd.sharp_axial_edges(p.solid, plate_axes(p.name), accept=plate_accept(p.name), caps=False))
        if edges is None:
            continue
        now = len(edges)
        before = ref_sharp(p.name)
        rows.append((p.name, now, before))
        if before > 0 and now >= before:
            failures.append(f"CHECK12 {p.name}: no corner of this plate was rounded: {now} sharp outline corners, "
                            f"as many as the unrounded part has ({before})")
    return rows


# ---------------------------------------------------------------------------
# Check 13 (drive bays): every hole pattern of a sled agrees with hardware.py's table, the material under each head gives a screw penetration inside the standard's
# limits, a head has room, and the bay stays inside its envelope
# ---------------------------------------------------------------------------
HEAD_SAMPLE_FROM = 0.25          # mm: the head's room is probed from this deep under the far face down to the head's height
RUN_STEP, RUN_MAX = 0.1, 8.0     # mm: the run of material under a head is searched this finely, at most this far
POS_TOL = 0.05                   # mm: a recorded hole's axis against the table's position


def solid_run(solid, p, d):
    """How far (mm) the solid stays solid from point p, which lies on a face, along the unit vector d; found by sampling isInside and bisecting the last step."""
    def inside(t):
        return solid.isInside(Vector(*(c + t * k for c, k in zip(p, d))))
    t = 0.02
    if not inside(t):
        return 0.0
    while t < RUN_MAX and inside(t + RUN_STEP):
        t += RUN_STEP
    if t >= RUN_MAX:
        return RUN_MAX
    lo, hi = t, t + RUN_STEP
    for _ in range(14):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if inside(mid) else (lo, mid)
    return (lo + hi) / 2


def check_drive_bays(parts, hardware, failures, contacts=(), pp_contact=()):
    """Check 13. Returns one row per bay: dict(bay, sled, holes, run (min, max mm of material under a head), pen {form: (min, max)}, head (the smallest room), box).
    contacts, pp_contact: the zero-gap pairs of checks 2 and 3: the sled's bosses must carry its drive, its foot must stand on skid_rear and its flange must lie against psu_bulkhead."""
    byname = {p.name: p for p in parts}
    touching = set(pp_contact) | {(b, a) for a, b in pp_contact}
    rows = []
    for side_name, side in hw.DRIVE_SIDES.items():
        sled = byname.get(f"drive_sled_{side_name}")
        if sled is None:
            failures.append(f"CHECK13 part drive_sled_{side_name} is missing")
            continue
        row = dict(bay=side_name, sled=sled.name, holes=0, run={}, pen={}, head={})
        if (sled.name, f"drive_{side_name}") not in set(contacts):
            failures.append(f"CHECK13 {sled.name} does not carry drive_{side_name}: no zero-gap contact between the bosses and the drive's board")
        for other, what in (("skid_rear", "stand on"), ("psu_bulkhead", "stand against")):
            if (sled.name, other) not in touching:
                failures.append(f"CHECK13 {sled.name} does not {what} {other}: no zero-gap contact")
        recorded = [h for h in sled.holes if h.kind == "M3c"]
        n_table = 0
        for face, fc in hw.drive_layout()["faces"].items():
            F = fc["spec"]
            into = (-side * fc["dir"], 0.0, 0.0)                    # from the drive's board into the sled
            far_into = (side * fc["dir"], 0.0, 0.0)                 # from the face the screw comes in from, towards the drive
            r_head = F["head_d"] / 2
            r_bore = hw.M3_CLEAR_D / 2
            rho = (r_bore + r_head + SLED_CB_PLAY / 2) / 2          # between the bore and the counterbore's wall: on the floor under the head
            far_x = side * (hw.drive_layout()["plate_x"][0] if face == "outer" else hw.drive_layout()["plate_x"][1])
            runs, heads = [], []
            for (y, z) in fc["holes"]:
                n_table += 1
                if not any(abs(h.start[1] - y) < POS_TOL and abs(h.start[2] - z) < POS_TOL for h in recorded):
                    failures.append(f"CHECK13 {sled.name}: no recorded {F['thread']} hole at the table's (Y {y:.2f}, Z {z:.2f}) for the {face} drive")
                run = solid_run(sled.solid, (side * fc["pb_x"], y + rho, z), into)
                runs.append(run)
                pen = F["screw_len"] - run
                lo, hi = F["enter"]
                if not (lo - 1e-6 <= pen <= hi + 1e-6):
                    failures.append(f"CHECK13 {sled.name}: the {F['thread']} screw at (Y {y:.2f}, Z {z:.2f}) enters the {face} drive {pen:.2f} mm (the material under its head is {run:.2f} mm), standard {lo:g}..{hi:g}")
                # room for the head: no material at the head's radius from just under the far face to the head's height
                room = 0.0
                for k in range(0, 11):
                    t = HEAD_SAMPLE_FROM + (F["head_h"] - HEAD_SAMPLE_FROM) * k / 10
                    if any(sled.solid.isInside(Vector(far_x + far_into[0] * t, y + r_head * math.cos(a), z + r_head * math.sin(a))) for a in np.linspace(0, 2 * math.pi, 16, endpoint=False)):
                        break
                    room = t
                heads.append(room)
                if room < F["head_h"] - 1e-6:
                    failures.append(f"CHECK13 {sled.name}: the head of the {F['thread']} screw at (Y {y:.2f}, Z {z:.2f}) has room only {room:.2f} mm under the {face} face, it is {F['head_h']:g} high")
            row["run"][face] = (min(runs), max(runs))
            row["pen"][face] = (F["screw_len"] - max(runs), F["screw_len"] - min(runs))
            row["head"][face] = min(heads)
        if len(recorded) != n_table:
            failures.append(f"CHECK13 {sled.name}: {len(recorded)} drive screw holes recorded, the table has {n_table}")
        row["holes"] = n_table
        boxes = [bbox_of(sled.solid), bbox_of(hardware[f"drive_{side_name}"]), bbox_of(hardware[f"drive_plugs_{side_name}"])]
        ex, ey, ez = hw.DRIVE_ENVELOPE
        row["box"] = (min(min(abs(b[0]), abs(b[1])) if b[0] * b[1] > 0 else 0.0 for b in boxes), max(max(abs(b[0]), abs(b[1])) for b in boxes),
                      min(b[2] for b in boxes), max(b[3] for b in boxes), min(b[4] for b in boxes), max(b[5] for b in boxes))
        inside_env = ex[0] - 1e-6 <= row["box"][0] and row["box"][1] <= ex[1] + 1e-6 and ey[0] - 1e-6 <= row["box"][2] and row["box"][3] <= ey[1] + 1e-6 \
            and ez[0] - 1e-6 <= row["box"][4] and row["box"][5] <= ez[1] + 1e-6
        if not inside_env:
            failures.append(f"CHECK13 {side_name} bay (sled, drives, plug zones) is X {row['box'][0]:.1f}..{row['box'][1]:.1f}, Y {row['box'][2]:.1f}..{row['box'][3]:.1f}, "
                            f"Z {row['box'][4]:.1f}..{row['box'][5]:.1f}: outside the envelope |X| {ex[0]:g}..{ex[1]:g}, Y {ey[0]:g}..{ey[1]:g}, Z {ez[0]:g}..{ez[1]:g}")
        rows.append(row)
    return rows


def contact_area(a, b):
    """Area (mm2) where planar faces of solid `a` lie flat against planar faces of solid `b`."""
    nb = rd.Neighbor("b", b, "part")
    return rd.Neighbors([nb]).contact_area(nb, a.Faces())


def contact_faces(a, b):
    nb = rd.Neighbor("b", b, "part")
    return rd.Neighbors([nb]).contact_faces(nb, a.Faces())


def screw_flat_area(faces, hole):
    """Area (mm2) of the contact `faces` within SCREW_FLAT of the edge of `hole`, for a hole whose axis is square to them; None when it is not."""
    ax = np.array(hole.d, float)
    p = np.array(hole.start, float)
    reach = hole.screw_r() + rd.SCREW_FLAT
    total, seen = 0.0, False
    for fc in faces:
        n, d, _ = rd._plane_of(fc)
        dn = float(n @ ax)
        if abs(dn) < 0.999:
            continue
        q = p + ((d - float(n @ p)) / dn) * ax
        if rd.bbox_gap(rd.bbox_of(fc), (q[0], q[0], q[1], q[1], q[2], q[2])) > reach:
            continue
        seen = True
        disc = cyl(tuple(q - 1.0 * ax), tuple(ax), 2 * reach, 2.0)
        r = fc.intersect(disc)
        if r is not None and not r.isNull():
            total += sum(x.Area() for x in r.Faces())
    return total if seen else None


def check_contact_areas(parts, hardware, res):
    """Revision 8a's limit, measured on the finished solids: every zero-gap contact the report lists (part x hardware and
    part x part) keeps at least CONTACT_FLOOR (97 %) of the area it has in the unrounded skeleton, and at least as much flat contact
    within SCREW_FLAT (4 mm) of the edge of each screw hole as that skeleton has (a screw whose hole leaves less than 4 mm of contact in
    the unrounded skeleton is held to what it had). Adds failures 'CONTACT ...' to res['failures'] and returns rows (a, b, area before,
    area now); res['screw_flat'] gets rows (a, b, hole, before, after) for every screw that crosses a contact."""
    ref = reference_parts()
    byname = {p.name: p for p in parts}
    rows, screws = [], []
    for a, b in sorted(res["contacts"]) + sorted(res["pp_contact"]):
        if a not in ref or (b not in hardware and b not in ref):
            continue
        sb1 = hardware[b] if b in hardware else byname[b].solid
        sb0 = hardware[b] if b in hardware else ref[b].solid
        f1, f0 = contact_faces(byname[a].solid, sb1), contact_faces(ref[a].solid, sb0)
        a1, a0 = sum(x.Area() for x in f1), sum(x.Area() for x in f0)
        rows.append((a, b, a0, a1))
        if a1 < rd.CONTACT_FLOOR * a0 - 1e-3:
            res["failures"].append(f"CONTACT {a} x {b}: the contact area fell from {a0:.3f} to {a1:.3f} mm2, {100 * a1 / a0:.1f} % of the unrounded area "
                                   f"(floor {100 * rd.CONTACT_FLOOR:.0f} %)")
        if a1 >= a0 - 1e-3:
            continue                    # nothing was taken from this contact: the screws around it are as they were
        holes = list(byname[a].holes) + (list(byname[b].holes) if b in byname else [])
        for h in holes:
            w0 = screw_flat_area(f0, h)
            if w0 is None or w0 < 1e-3:
                continue
            w1 = screw_flat_area(f1, h) or 0.0
            screws.append((a, b, h.describe(), w0, w1))
            if w1 < w0 - 1e-3:
                res["failures"].append(f"CONTACT {a} x {b}: the flat contact within {rd.SCREW_FLAT:g} mm of the screw hole ({h.describe()}) fell from {w0:.2f} to {w1:.2f} mm2")
    res["contact_areas"] = rows
    res["screw_flat"] = screws
    return rows


def explain_corners(parts, hardware, memo=None):
    """For the report: per plate the sharp outline corners that remain, by excuse. Returns rows (part, now, before,
    {excuse: n}, [open corners])."""
    out = []
    pb = {p.name: bbox_of(p.solid) for p in parts}
    items = [rd.Neighbor(k, v, "hw") for k, v in hardware.items() if k not in hw.KEEP_OUT] + \
            [rd.Neighbor(p.name, p.solid, "part") for p in parts]
    for p in parts:
        if plate_axes(p.name) is None:
            continue
        near = [n for n in items if n.name != p.name and bbox_gap(pb[p.name], bbox_of(n.shape)) <= 1e-3]
        rows = memo_call(memo, (p.solid,) + tuple(n.shape for n in near), "corners", classify_corners, p, rd.Neighbors(near), memo)
        by = {w: sum(1 for c in rows if c[0] == w) for w in CORNER_CLASSES}
        out.append((p.name, len(rows), ref_sharp(p.name), by, [c for c in rows if c[0] == "open"]))
    return out


def run_checks(hardware, parts, memo=None):
    failures: list[str] = []
    res: dict = {}

    # 1. hardware x hardware
    hh = []
    for (an, a), (bn, b) in itertools.combinations(hardware.items(), 2):
        v = _guard(failures, "CHECK1", f"hardware {an} x {bn}", memo_call, memo, (a, b), "iv", inter_vol, a, b)
        if v is None:
            continue
        hh.append((an, bn, v))
        if v > 0.0 + 1e-6:
            failures.append(f"CHECK1 hardware {an} x {bn}: {v:.2f} mm3")
    res["hh"] = hh

    hb = {k: bbox_of(v) for k, v in hardware.items()}
    pb = {p.name: bbox_of(p.solid) for p in parts}

    # 2. part x hardware
    ph, close, contacts = [], [], []
    for p in parts:
        for hn, hs in hardware.items():
            if bbox_gap(pb[p.name], hb[hn]) > CLOSE_MM:
                continue
            if GUIDE_HOSE.get(p.name) == hn:
                continue                    # a guide holds its own hose: it is measured against the true hose in check 10
            v = _guard(failures, "CHECK2", f"part x hardware {p.name} x {hn}", memo_call, memo, (p.solid, hs), "iv",
                       inter_vol, p.solid, hs)
            d = _guard(failures, "CHECK2", f"part x hardware {p.name} x {hn}", memo_call, memo, (p.solid, hs), "dist",
                       solid_distance, p.solid, hs)
            if v is None or d is None:
                continue
            ph.append((p.name, hn, v, d))
            if v >= VOL_EPS:
                failures.append(f"CHECK2 part x hardware {p.name} x {hn}: {v:.2f} mm3")
            if d < 1e-3:
                contacts.append((p.name, hn))
            elif d < CLOSE_MM:
                close.append((p.name, hn, d))
    res["ph"], res["close"], res["contacts"] = ph, sorted(close, key=lambda t: t[2]), contacts

    # 3. part x part
    pp, pp_contact = [], []
    for a, b in itertools.combinations(parts, 2):
        if bbox_gap(pb[a.name], pb[b.name]) > 1e-6:
            continue
        v = _guard(failures, "CHECK3", f"part x part {a.name} x {b.name}", memo_call, memo, (a.solid, b.solid), "iv",
                   inter_vol, a.solid, b.solid)
        if v is None:
            continue
        pp.append((a.name, b.name, v))
        if v >= VOL_EPS:
            failures.append(f"CHECK3 part x part {a.name} x {b.name}: {v:.2f} mm3")
        else:
            d = _guard(failures, "CHECK3", f"part x part {a.name} x {b.name}", memo_call, memo, (a.solid, b.solid), "dist",
                       solid_distance, a.solid, b.solid)
            if d is not None and d < 1e-3:
                pp_contact.append((a.name, b.name))
    res["pp"], res["pp_contact"] = pp, pp_contact

    # 3b. every tie bridge touches its host and nothing else, and keeps TIE_CLEAR from every other part and every hardware solid
    res["tie"] = check_tie_bridges(parts, hardware, pb, hb, contacts, pp_contact, failures, memo)

    # 4. size
    sizes = []
    for p in parts:
        b = pb[p.name]
        d = (b[1] - b[0], b[3] - b[2], b[5] - b[4])
        sizes.append((p.name, d))
        if max(d) > MAX_PART:
            failures.append(f"CHECK4 {p.name} is {max(d):.1f} mm (> {MAX_PART})")
    res["sizes"] = sizes

    # 5. holders and fasteners, derived from the solids at the positions hardware.py lists
    res["mounts"] = derive_mounts(parts, contacts, failures, memo)
    names = {p.name for p in parts}
    for need in ("gpu_post", "rib_A_right"):
        if need not in names:
            failures.append(f"CHECK5 missing part {need}")

    # 6. lowest point
    low = []
    allowed_low = {"rib_A_right", "rib_A_left", "rib_B_right", "rib_B_left", "psu_bulkhead"}
    for p in parts:
        z = pb[p.name][4]
        low.append((p.name, z))
        if z < hw.DESK_Z - 1e-6:
            failures.append(f"CHECK6 {p.name} below the desk: z = {z:.2f}")
        if z < hw.DESK_Z + 1e-6 and p.name not in allowed_low:
            failures.append(f"CHECK6 {p.name} touches the desk but is not a foot/runner/bulkhead")
    res["low"] = low

    # 8. envelope: nothing past |X| = ENVELOPE_X or in front of Y = ENVELOPE_Y0, frame parts and hose keep-outs alike
    res["envelope"] = check_envelope(parts, hardware, pb, hb, failures)

    # 9. every frame part except the guides keeps HOSE_CLEAR from the hose keep-outs
    res["hose_gaps"] = check_hose_clearance(parts, hardware, pb, hb, failures, memo)

    # 10. the guides hold the true hose snugly
    res["guides"] = check_guides(parts, failures, memo)

    # 11. the side fans' apertures stay open
    res["apertures"] = check_apertures(parts, failures)

    # 14. the 420's bracket plates stay out of the fans' openings and keep the wall round every fan screw
    res["plates420"] = check_420_plates(parts, failures, memo)

    # 12. sharp outline corners that remain on the plates; fails only for a plate where nothing was rounded
    res["corners"] = check_corners(parts, hardware, pb, hb, failures, memo)

    # 13. the drive bays: hole patterns, screw penetration, head room, envelope
    res["drives"] = check_drive_bays(parts, hardware, failures, contacts, pp_contact)

    # 7. extra sanity: one connected solid per part, bolt positions inside outlines, every hole drilled
    #    with the wall its insert or screw needs
    for p in parts:
        k = n_solids(p.solid)
        if k != 1:
            failures.append(f"CHECK7 {p.name}: {k} separate solids (disconnected)")
    for label, ok, _ in BOLT_CHECKS:
        if not ok:
            failures.append(f"CHECK7 bolt outside outline: {label}")
    res["n_holes"] = check_holes(parts, failures, memo)
    res["failures"] = failures
    return res


# ---------------------------------------------------------------------------
# Tessellation and previews
# ---------------------------------------------------------------------------
def tessellate(shape, tol=0.5):
    vs, fs = [], []
    off = 0
    for s in shape.Solids():
        v, f = s.tessellate(tol)
        if not v:
            continue
        vs += [[p.x, p.y, p.z] for p in v]
        fs += [[i + off for i in tri] for tri in f]
        off += len(v)
    return np.array(vs, float), np.array(fs, int)


def shade(tri, light1, light2, base, ambient):
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n = n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)
    l1 = np.array(light1, float)
    l1 /= np.linalg.norm(l1)
    l2 = np.array(light2, float)
    l2 /= np.linalg.norm(l2)
    inten = np.clip(ambient + 0.62 * np.abs(n @ l1) + 0.25 * np.abs(n @ l2), 0, 1)
    return np.clip(np.array(base)[None, :] * inten[:, None], 0, 1)


def project(P, kind):
    P = np.atleast_2d(P)
    if kind == "front":
        return np.stack([P[:, 0], P[:, 2]], 1)
    if kind == "side":           # from the left (-X): front on the right
        return np.stack([-P[:, 1], P[:, 2]], 1)
    if kind == "iso_fl":
        r = np.array([1, -1, 0.0]) / math.sqrt(2)
        view = np.array([1, 1, -1.0]) / math.sqrt(3)
    else:                        # iso_rr
        r = np.array([-1, 1, 0.0]) / math.sqrt(2)
        view = np.array([-1, -1, -1.0]) / math.sqrt(3)
    up = np.cross(r, view)
    up /= np.linalg.norm(up)
    return np.stack([P @ r, P @ up], 1)


def depth(tri, kind):
    c = tri.mean(axis=1)
    if kind == "front":
        return c[:, 1]
    if kind == "side":
        return c[:, 0]
    if kind == "iso_fl":
        return c @ np.array([1, 1, -1.0])
    return c @ np.array([-1, -1, -1.0])


VIEW_TITLES = {
    "iso_fl": "Изометрия спереди-слева",
    "iso_rr": "Изометрия сзади-справа",
    "front": "Вид спереди",
    "side": "Вид слева (перед справа)",
}


def draw_view(ax, kind, frame_meshes, hw_meshes, hw_alpha=0.30):
    ax.set_facecolor("#16171a")
    ax.set_title(VIEW_TITLES[kind], color="#dddddd", fontsize=11, pad=6)
    ax.set_aspect("equal")
    ax.tick_params(colors="#888888", labelsize=7)
    for sp in ax.spines.values():
        sp.set_color("#444444")
    light1, light2 = (0.6, -0.5, 0.8), (-0.3, 0.4, 0.5)
    if kind == "iso_rr":
        light1, light2 = (-0.6, 0.5, 0.8), (0.3, -0.3, 0.5)
    tris, cols, deps = [], [], []
    for name, (v, f, base) in hw_meshes.items():
        t = v[f]
        c = shade(t, light1, light2, base, 0.30)
        tris.append(t)
        a = 0.08 if name in hw.KEEP_OUT else hw_alpha
        cols.append(np.hstack([c, np.full((len(c), 1), a)]))
        deps.append(depth(t, kind))
    for name, (v, f, base) in frame_meshes.items():
        t = v[f]
        c = shade(t, light1, light2, base, 0.35)
        tris.append(t)
        cols.append(np.hstack([c, np.ones((len(c), 1))]))
        deps.append(depth(t, kind))
    tri = np.concatenate(tris)
    col = np.concatenate(cols)
    dep = np.concatenate(deps)
    order = np.argsort(-dep)
    tri, col = tri[order], col[order]
    pr = project(tri.reshape(-1, 3), kind).reshape(-1, 3, 2)
    ax.add_collection(PolyCollection(pr, facecolors=col, edgecolors=(0, 0, 0, 0.10),
                                     linewidths=0.1, closed=True))
    ax.autoscale_view()
    if kind in ("front", "side"):
        ax.set_xlabel("X мм" if kind == "front" else "Y мм (перед справа)", color="#888888")
        ax.set_ylabel("Z мм", color="#888888")
        ax.grid(True, color="#2a2a2e", lw=0.5)
    else:
        ax.set_xticks([])
        ax.set_yticks([])


def frame_color(i):
    k = 0.90 + 0.10 * ((i * 7) % 5) / 4.0
    return tuple(min(1.0, c * k) for c in FRAME_RGB)


def render(hardware, parts, with_hw, path, title, offsets=None):
    hw_meshes = {}
    if with_hw:
        for k, s in hardware.items():
            v, f = tessellate(s, 0.8)
            hw_meshes[k] = (v, f, np.array(to_rgb(hw.HW_COLORS[k])))
    fr = {}
    for i, p in enumerate(parts):
        v, f = tessellate(p.solid, 0.5)
        if offsets is not None:
            v = v + np.array(offsets.get(p.name, (0, 0, 0)), float)
        fr[p.name] = (v, f, np.array(frame_color(i)))
    if offsets is not None:
        fig, axes = plt.subplots(1, 2, figsize=(16, 8), facecolor="#101012")
        for ax, kind in zip(axes, ("iso_fl", "iso_rr")):
            draw_view(ax, kind, fr, hw_meshes)
    else:
        fig, axes = plt.subplots(2, 2, figsize=(15, 13), facecolor="#101012")
        for ax, kind in zip(axes.ravel(), ("iso_fl", "iso_rr", "front", "side")):
            draw_view(ax, kind, fr, hw_meshes)
    fig.suptitle(title, color="#eeeeee", fontsize=14, y=0.985)
    handles = [Patch(facecolor=FRAME_RGB, label="каркас ABS")]
    if with_hw:
        handles += [Patch(facecolor=to_rgb(c), alpha=0.5, label=k) for k, c in hw.HW_COLORS.items()]
    fig.legend(handles=handles, loc="lower center", ncol=len(handles), frameon=False,
               fontsize=8, labelcolor="#cccccc")
    plt.tight_layout(rect=(0, 0.03, 1, 0.965))
    fig.savefig(path, dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)


def explode_offsets(parts):
    off = {}
    for p in parts:
        n = p.name
        o = np.zeros(3)
        side = -1.0 if n.endswith("left") else 1.0
        if n.startswith("rib_A"):
            o = np.array([side * 60, -25, 0])
        elif n.startswith("rib_B"):
            o = np.array([side * 60, 25, 0])
        elif n.startswith("antler"):
            o = np.array([side * 30, 45, 15])
        elif n.startswith("neck"):
            o = np.array([side * 90, 20, 25])
        elif n.startswith("visor_arm"):
            o = np.array([side * 90, -10, 20])
        elif n.startswith("fan_bracket"):
            o = np.array([side * 70, 0, 0])
        elif n == "beam_front":
            o = np.array([0, -40, 0])
        elif n == "front_sill":
            o = np.array([0, -40, 45])
        elif n.startswith("beam_"):
            o = np.array([0, 0, -45]) + np.array([0, 0, 0])
        elif n.startswith("skid"):
            o = np.array([0, 0, -45])
        elif n == "psu_bulkhead":
            o = np.array([0, 45, 0])
        elif n == "gpu_post":
            o = np.array([-45, -20, 30])
        off[n] = tuple(o)
    return off


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
RU_REASONS = [
    (r"it would take contact area from (.*)", r"скругление отняло бы площадь контакта у \1"),
    (r"it would take (\S+) mm2 from the (\S+) mm2 contact with (\S+): (\S+) mm2 of the (\S+) % allowance is left after what the corners still to come need at the smallest radius",
     r"скругление сняло бы \1 мм² с контакта \3 (\2 мм²); от допуска \5 % осталось \4 мм² за вычетом нужного остальным углам"),
    (r"it would leave less than (\S+) mm of flat contact around the screw at (.*)", r"скругление оставило бы меньше \1 мм плоского контакта вокруг винта в \2"),
    (r"the top face carries the front sill and the I/O module: rounding its edges would take contact area", "верхняя грань несёт порог и модуль: скругление её рёбер отняло бы площадь контакта (14 % при 3 мм)"),
    (r"it would cut into a hole's wall", "скругление врезалось бы в стенку отверстия"),
    (r"the rounding would cut into a hole's wall", "скругление врезалось бы в стенку отверстия"),
    (r"the added material would close in on a hole", "добавленный материал закрыл бы подход к отверстию (головка винта)"),
    (r"the added material would overlap (\S+) \((.*)\)", r"добавленный материал вошёл бы в \1 (\2)"),
    (r"the added material would come within (\S+) mm of (\S+)", r"добавленный материал подошёл бы к \2 ближе \1 мм"),
    (r"no radius of (\S+)\.\.(\S+) mm fits between the neighbouring edges", r"радиус \1..\2 мм не помещается между соседними рёбрами"),
    (r"the corner was consumed by a neighbouring fillet", "угол поглощён соседней галтелью"),
    (r"the kernel returned an outline of the wrong sense", "ядро вернуло контур с неверным знаком"),
    (r"the kernel could not fillet it \((.*)\)", r"ядро не смогло сделать галтель (\1) на большем радиусе"),
    (r"the kernel returned an invalid solid", "ядро вернуло невалидное тело"),
    (r"largest radius that fits", "наибольший радиус, который проходит"),
    (r"no concave edge found there", "вогнутое ребро не найдено"),
    (r"the cradle surface \(the 420's pad\) ends here", "здесь кончается поверхность кредла (прокладка под 420)"),
    (r"the top face carries the PSU: rounding its edges would take contact area", "верхняя грань несёт БП: скругление её рёбер отняло бы площадь контакта"),
    (r"the bottom face stands on the desk \(a contact pad\)", "нижняя грань стоит на столе (контактная площадка)"),
    (r"a fillet of (\S+) mm or more would reach past the start of the (\S+) mm edge rounding: the flat top is (\S+) mm from the boss axis, the boss radius is (\S+)",
     r"галтель от \1 мм вышла бы за начало скругления кромки \2 мм: плоский верх в \3 мм от оси бобышки, радиус бобышки \4"),
    (r"rail, root block, knuckle and tab \(2.5..5.5 mm thin, joined by 1 mm overlaps\): rounding any of them cut the joints into two solids",
     "рельс, корневой блок, шарнир и лапка (2.5..5.5 мм, соединены нахлёстами по 1 мм): скругление любой из них разрывало соединения на два тела (проверено)"),
    (r"not rounded: the channel wall is (\S+) mm and the mouth's lip about 2 mm; a (\S+) mm radius on the shelf edges takes the wall to 0 at the shelf's end faces, a 2 mm radius leaves 0.5 mm; the foot's corners are corners of the shelves",
     r"не скруглена: стенка канала \1 мм, губа горловины около 2 мм; радиус \2 мм на рёбрах полок сводит стенку к 0 на торцах полок, радиус 2 мм оставляет 0.5 мм; углы стопы - углы полок"),
]


def ru_reason(text):
    import re
    for pat, rep in RU_REASONS:
        text, n = re.subn(pat, rep, text)
        if n:
            break
    return text.replace("mm2", "мм²").replace("mm3", "мм³")


def bay_neighbours(subject, parts, hardware, own, k=5, reach=40.0):
    """The k nearest other solids to `subject` (a solid): [(name, distance)], parts as they are, hardware as hw:name; `own` names are left out (the bay's own sled, drive and plug zone)."""
    sb = bbox_of(subject)
    rows = []
    for q in parts:
        if q.name not in own and bbox_gap(sb, bbox_of(q.solid)) <= reach:
            rows.append((q.name, solid_distance(subject, q.solid)))
    for n, sol in hardware.items():
        if n not in own and bbox_gap(sb, bbox_of(sol)) <= reach:
            rows.append(("hw:" + n, solid_distance(subject, sol)))
    return sorted(rows, key=lambda t: t[1])[:k]


def drive_bay_lines(parts, hardware, res):
    """Report lines of the drive bays (check 13): where everything stands, the screws, the clearances, the assembly order."""
    lay = hw.drive_layout()
    byname = {p.name: p for p in parts}
    L = []
    px0, px1 = lay["plate_x"]
    o, i = lay["faces"]["outer"], lay["faces"]["inner"]
    L.append("Отсеки под диски (проход 1, docs/plans/cables-and-organic.md, «Drive bays, pass 1»): салазки сбоку от БП (слева); диск стоит на дальнем торце разъёмом вверх. "
             "Отсек один, левый (наружная грань смотрит в -X; строится правосторонним и зеркалится по X); правого отсека нет: кабели БП идут через его объём (см. hardware.DRIVE_SIDES). Места дисков и таблицы отверстий - hardware.py (стандарты: SFF-8301 для 3.5, SFF-8201 для 2.5, SFF-8323/8223 разъём).")
    L.append(f"  Пластина {hw.DRIVE_PLATE_T:g} мм: X {px0:g}..{px1:g}; от БП (X {hw.PSU_W[1]:g}): воздух {hw.DRIVE_PSU_AIR:g} мм, внутренний диск 2.5 (X {i['body'][0]:g}..{i['body'][1]:g}), бобышка {hw.DRIVE_BOSS_H:g} мм, пластина, "
             f"бобышка, внешний диск 3.5 (X {o['body'][0]:g}..{o['body'][1]:g}). Разъёмы всех дисков на Z {lay['z_top']:g} (сверху), зона штекеров {hw.DRIVE_PLUG_ZONE:g} мм выше (ПРЕДПОЛОЖЕНИЕ, источника нет).")
    for nm in (f"drive_sled_{bay}" for bay in hw.DRIVE_SIDES):
        if nm in byname:
            sg = hw.DRIVE_SIDES[nm.rsplit("_", 1)[1]]
            b = bbox_of(byname[nm].solid)
            L.append(f"  {nm}: X {b[0]:.1f}..{b[1]:.1f}  Y {b[2]:.1f}..{b[3]:.1f}  Z {b[4]:.1f}..{b[5]:.1f}; пластина Y {b[2]:.1f}..{hw.PSU_REAR_Y:g}, Z {b[4]:g}..{lay['z_top'] - SLED_TOP_GAP:g}; "
                     f"фланец у стенки {SLED_FLANGE_Y:g} мм (Y {hw.PSU_REAR_Y - SLED_FLANGE_Y:g}..{hw.PSU_REAR_Y:g}, Z {SLED_FLANGE_Z[0]:g}..{SLED_FLANGE_Z[1]:g}, X +-{SLED_BOLT_X - SLED_FLANGE_HALF_X:g}..{SLED_BOLT_X + SLED_FLANGE_HALF_X:g}); "
                     f"2 x M4 вдоль Y в X {sg * SLED_BOLT_X:g}, Z {SLED_BOLT_Z[0]:g} и {SLED_BOLT_Z[1]:g} (проходные Ø{hw.M4_CLEAR_D:g} в стенке psu_bulkhead, вставки {SLED_BOLT_KIND} во фланце); ступня - нижняя грань на skid_rear (Z 0)")
    for nm in hw.DRIVES:
        b = bbox_of(hardware[nm])
        L.append(f"  {nm}: X {b[0]:.1f}..{b[1]:.1f}  Y {b[2]:.1f}..{b[3]:.1f}  Z {b[4]:.1f}..{b[5]:.1f} (3.5: Y {o['body'][2]:g}..{o['body'][3]:g}, Z {o['body'][4]:g}..{o['body'][5]:g}; "
                 f"2.5: Y {i['body'][2]:g}..{i['body'][3]:g}, Z {i['body'][4]:g}..{i['body'][5]:g}, центр по Y совпадает с 3.5)")
    for face, fc in (("внешняя грань, 3.5 дюйма, 6-32 x 6.35", o), ("внутренняя грань, 2.5 дюйма, M3 x 5", i)):
        L.append(f"  Винты, {face} (Y, Z): " + "; ".join(f"({y:.2f}, {z:.2f})" for y, z in fc["holes"]))
    L.append(f"  Каждое отверстие: проходное Ø{hw.M3_CLEAR_D:g}, зенковка Ø(головка + {SLED_CB_PLAY:g}) со стороны, противоположной диску, под головкой {SLED_FLOOR:g} мм материала (пластина {hw.DRIVE_PLATE_T:g} + бобышка {hw.DRIVE_BOSS_H:g} - зенковка), "
             f"бобышка Ø{2 * SLED_BOSS_R:g} x {hw.DRIVE_BOSS_H:g} мм со стороны диска. Измерено по телам: " + "; ".join(
                 f"{r['bay']}: материал под головкой {min(v[0] for v in r['run'].values()):.2f}..{max(v[1] for v in r['run'].values()):.2f} мм, "
                 f"3.5 входит {r['pen']['outer'][0]:.2f} мм (норма {o['spec']['enter'][0]:g}..{o['spec']['enter'][1]:g}), 2.5 входит {r['pen']['inner'][0]:.2f} мм (норма до {i['spec']['enter'][1]:g}), "
                 f"место под головку {min(r['head'].values()):.2f} из {o['spec']['head_h']:g} мм" for r in res.get("drives", [])) + ".")
    L.append(f"  Порядок сборки: {SLED_ORDER}.")
    L.append("  Ближайшее к каждому телу отсека, мм (контакт по плану - нулевой зазор: болты и бобышки, ступня, фланец):")
    for side in hw.DRIVE_SIDES:
        own = {f"drive_sled_{side}", f"drive_{side}", f"drive_plugs_{side}"}      # the bay's own three bodies are not neighbours
        for label, subject in ((f"drive_sled_{side}", byname[f"drive_sled_{side}"].solid), (f"drive_{side}", hardware[f"drive_{side}"]), (f"drive_plugs_{side}", hardware[f"drive_plugs_{side}"])):
            near = bay_neighbours(subject, parts, hardware, own)
            L.append(f"      {label:20s} " + ", ".join(f"{n} {d:.2f}" for n, d in near))
    return L


def format_report(hardware, parts, res, memo=None):
    L = []
    w = L.append
    w("B6 «Шатёр»: структурный каркас v0")
    w("=" * 72)
    w("Оси: X вправо (вид спереди), Y вглубь (перед = 0), Z вверх. Стол Z = -15.")
    w("")
    w(f"Детали (AABB мм, материал, объём, масса: ABS {ABS_DENSITY} и PA6 {PA6_DENSITY} г/см³; 100 % и 4 стенки/20 % заполнения, формула v1)")
    t100 = t20 = tvol = 0.0
    mass = {}
    per_material = {m: [0, 0.0, 0.0, 0.0] for m in MATERIALS}       # parts, cm3, g at 100 %, g at 4 walls / 20 %
    for p in parts:
        b = bbox_of(p.solid)
        vol, m100, m20 = mass_estimate(p.solid, p.material)
        mass[p.name] = (vol, m100, m20)
        t100 += m100
        t20 += m20
        tvol += vol
        pm = per_material[p.material]
        pm[0] += 1
        pm[1] += vol
        pm[2] += m100
        pm[3] += m20
        w(f"  {p.name:18s} {p.material:3s} X {b[0]:7.1f}..{b[1]:7.1f}  Y {b[2]:7.1f}..{b[3]:7.1f}  Z {b[4]:7.1f}..{b[5]:7.1f}"
          f"  | {vol:7.1f} см³  {m100:6.1f} г / {m20:6.1f} г")
        w(f"      {p.note}")
    w(f"  ИТОГО {len(parts)} деталей: {tvol:.0f} см³   100 % {t100:.0f} г   4 стенки/20 % ~ {t20:.0f} г")
    w("Масса по материалам (слой PLA оболочки и диффузор света - не в этом файле):")
    for m in MATERIALS:
        n, v, m100, m20 = per_material[m]
        w(f"  {m:4s} {n:2d} деталей: {v:7.1f} см³   100 % {m100:7.1f} г   4 стенки/20 % ~ {m20:7.1f} г")
    w("  ABS: каркас, всё несущее. PA6 (нейлон yxpolyer, не наполненный, чёрный): две направляющие шлангов (горловина защёлкивается на шланге). "
      "PLA: органическая оболочка (organic_frame.py) и диффузор светлой линии из прозрачного PLA; PLA не несёт нагрузки и держится "
      "не ближе 10 мм к видеокарте и БП, 4 мм к радиаторам и вентиляторам (в этом файле таких деталей нет).")
    w("")
    w("Крепёж железа (держатель, количество)")
    for f in FASTENERS:
        w(f"  {f['item']:22s} {f['part']:48s} {f['kind']:13s} x{f['count']:<2d} {f['note']}")
    w("")
    w(f"Подпорки GPU: gpu_post (левый торец, M4 в beam_mid) + gpu_rest (палец правого ребра A, плоскость u = {hw.GPU_BS[2]:.1f}).")
    w("")
    w("Намеренные контакты с нулевым зазором, деталь x железо:")
    for a, b in sorted(res["contacts"]):
        tag = "по плану" if (a, b) in INTENDED_CONTACTS else "НЕ в плане"
        w(f"  {a:16s} x {b:11s} {tag}")
    w("")
    w("Контакты деталь x деталь (нулевой зазор, объём пересечения < 1 мм³):")
    for a, b in sorted(res["pp_contact"]):
        w(f"  {a:16s} x {b}")
    w("")
    w(f"Зазоры < {CLOSE_MM:.0f} мм, деталь x железо (минимум по паре):")
    for a, b, d in res["close"]:
        w(f"  {a:16s} x {b:11s} {d:5.2f} мм")
    if not res["close"]:
        w("  нет")
    w("")
    allb = [bbox_of(p.solid) for p in parts]
    allh = [bbox_of(h) for k, h in hardware.items() if k not in hw.KEEP_OUT]

    def env(bs):
        return (min(b[0] for b in bs), max(b[1] for b in bs), min(b[2] for b in bs),
                max(b[3] for b in bs), min(b[4] for b in bs), max(b[5] for b in bs))
    ef, eh, ea = env(allb), env(allh), env(allb + allh)
    for lab, e in (("каркас", ef), ("железо", eh), ("каркас + железо", ea)):
        w(f"Габарит {lab:16s}: {e[1]-e[0]:6.1f} x {e[3]-e[2]:6.1f} x {e[5]-e[4]:6.1f} (Ш x Г x В)"
          f"   X {e[0]:.0f}..{e[1]:.0f}  Y {e[2]:.0f}..{e[3]:.0f}  Z {e[4]:.0f}..{e[5]:.0f}")
    w("")
    w("Воздушный поток")
    w(f"  420: стоит под 90° к плате за её верхним краем. Сердцевина с портами на грани u = {hw.RAD420_CORE_U[0]} (к плате), "
      f"вентиляторы на внешней грани (u {hw.RAD420_FAN_U[0]}..{hw.RAD420_FAN_U[1]}) дуют вниз по склону вдоль платы. Между сердцевиной (u {hw.RAD420_CORE_U[0]}..{hw.RAD420_CORE_U[1]}) "
      f"и вентиляторами зажата пластина кронштейна (u {hw.RAD420_PLATE_U[0]}..{hw.RAD420_PLATE_U[1]}, ревизия 11).")
    w(f"  360: вентиляторы на внешней стороне (n {hw.RAD360_FAN_N[0]:g}..{hw.RAD360_FAN_N[1]:g}) дуют внутрь от передней грани, "
      f"к плате (сердцевина n {hw.RAD360_CORE_N[0]:g}..{hw.RAD360_CORE_N[1]:g}).")
    fl, fr = hw.FAN_SIDE_X["fan_side_left"], hw.FAN_SIDE_X["fan_side_right"]
    w(f"  Боковые 2 x 140 (ревизия 7): по одному под каждым концом 360, на флангах, дуют НАРУЖУ. Правый X {fr[0]:g}..{fr[1]:g}, левый X {fl[0]:g}..{fl[1]:g}, "
      f"оба u {hw.FAN_SIDE_U[0]:g}..{hw.FAN_SIDE_U[1]:g}, n {hw.FAN_SIDE_N[0]:g}..{hw.FAN_SIDE_N[1]:g}. Передних вентиляторов нет: воздух входит "
      f"через оба радиатора, идёт над платой и выходит вбок.")
    w("")
    w("Шланги (cad_b6/hose_routes.py, маршруты в cad_b6/hoses.py; keep-out = шланг + 1.8 мм)")
    import hose_routes                    # lazy: it draws with vtk
    for line in hose_routes.table_lines():
        w("  " + line)
    gaps = []
    for hn in hw.HOSES:
        for nm, sol in [(p.name, p.solid) for p in parts] + [(k, v) for k, v in hardware.items() if k not in hw.HOSES]:
            d = solid_distance(hardware[hn], sol)
            if d < 10.0:
                gaps.append(f"{hn} x {nm} {d:.2f}")
    w("  Keep-out шлангов, ближе 10 мм, мм: " + (", ".join(sorted(gaps, key=lambda t: float(t.rsplit(' ', 1)[1]))) or "нет"))
    w("")
    w("Проверки")
    nh = len(res["hh"])
    w(f"  1. железо x железо: {nh} пар, пересечений 0                    "
      + ("PASS" if not any(f.startswith('CHECK1') for f in res['failures']) else "FAIL"))
    w(f"  2. деталь x железо: {len(res['ph'])} близких пар, объём < {VOL_EPS:.0f} мм³ у каждой   "
      + ("PASS" if not any(f.startswith('CHECK2') for f in res['failures']) else "FAIL"))
    w(f"  3. деталь x деталь: {len(res['pp'])} пар с пересекающимися габаритами, объём < {VOL_EPS:.0f} мм³ у каждой; каждый из {len(TIE_POINTS)} мостиков кабельных точек касается только своей детали "
      f"и держит {TIE_CLEAR:g} мм от остального   "
      + ("PASS" if not any(f.startswith('CHECK3') for f in res['failures']) else "FAIL"))
    mx = max(max(d) for _, d in res["sizes"])
    w(f"  4. размеры <= {MAX_PART:.0f} мм: максимум {mx:.1f} мм             "
      + ("PASS" if not any(f.startswith('CHECK4') for f in res['failures']) else "FAIL"))
    m = res["mounts"]
    w(f"  5. держатели и крепёж, считаются по телам (отверстие на оси в держателе): board {m['board']}, rad420 {m['rad420']}, "
      f"rad360 {m['rad360']}, psu {m['psu']}, side fans {m['fan_side_left']} (L) + {m['fan_side_right']} (R) of 4 corners, "
      f"gpu post {m['gpu_post']} + rest {m['gpu_rest']}, front_io {m['front_io']} (PLACEHOLDER-винты модуля в front_sill), "
      f"органическая оболочка {m['organic']} пилотов M3 под площадки (hw.ORGANIC_PADS), кабельные точки {m['tie_pilot']} пилотов M3 в деталях + {m['tie_bridge']} отверстий в мостиках (TIE_POINTS)   "
      + ("PASS" if not any(f.startswith('CHECK5') for f in res['failures']) else "FAIL"))
    lz = min(z for _, z in res["low"])
    w(f"  6. нижняя точка >= -15: минимум {lz:.2f}                      "
      + ("PASS" if not any(f.startswith('CHECK6') for f in res['failures']) else "FAIL"))
    w(f"  7. (доп.) связность, болты внутри контуров, {res['n_holes']} отверстий: полость пуста и стенка до поверхности "
      f"и до соседних отверстий >= 2.1 мм (M4/M4S/M4 проходное/M5) или 1.6 мм (M3, 6-32)   "
      + ("PASS" if not any(f.startswith('CHECK7') for f in res['failures']) else "FAIL"))
    ev = res["envelope"]
    w(f"  8. огибающая |X| <= {hw.ENVELOPE_X:g}, Y >= {hw.ENVELOPE_Y0:g}: детали max |X| {ev['parts'][0]:.1f} ({ev['parts'][1]}), "
      f"min Y {ev['parts'][2]:.1f} ({ev['parts'][3]}); шланги (keep-out R 8.0/7.8) max |X| {ev['hoses'][0]:.1f} ({ev['hoses'][1]}), "
      f"min Y {ev['hoses'][2]:.1f} ({ev['hoses'][3]}); верх: не выше грани n = {hw.ENVELOPE_N:g} (верхняя грань 420), максимум n "
      f"{ev['top'][2]:.2f} ({ev['top'][3]}); верх каркаса Z = {ev['top'][0]:.1f} ({ev['top'][1]}), верх 420 Z = {ev['top'][4]:.1f}; "
      f"железо спереди (front_io, light_strip, PLACEHOLDER) max |X| {ev['front'][0]:.1f} ({ev['front'][1]}), min Y {ev['front'][2]:.1f} ({ev['front'][3]})   "
      + ("PASS" if not any(f.startswith('CHECK8') for f in res['failures']) else "FAIL"))
    hg = res["hose_gaps"]
    w(f"  9. детали (кроме направляющих) >= {HOSE_CLEAR:g} мм от шлангов: минимум {hg[0][2]:.2f} мм ({hg[0][0]} x {hg[0][1]}), "
      f"затем " + ", ".join(f"{a} x {b} {d:.2f}" for a, b, d in hg[1:4]) + "   "
      + ("PASS" if not any(f.startswith('CHECK9') for f in res['failures']) else "FAIL"))
    gr = res["guides"]
    w(f"  10. направляющие держат шланг по настоящему радиусу: {len(gr)} пар направляющая x шланг, пересечение с трубой радиуса шланга < {VOL_EPS:g} мм³ "
      f"(макс. {max(r[2] for r in gr):.2f}), стенка канала {min(r[3] for r in gr):.2f}..{max(r[3] for r in gr):.2f} мм "
      f"(нужно {GUIDE_WALL_MIN:g}..{GUIDE_WALL_MAX:g}), горловина {GUIDE_MOUTH:g} x диаметр шланга: "
      + ("да" if all(r[4] for r in gr) else "НЕТ") + "   "
      + ("PASS" if not any(f.startswith('CHECK10') for f in res['failures']) else "FAIL"))
    ap = res["apertures"]
    w(f"  11. (доп.) отверстие бокового вентилятора открыто: в круге Ø{hw.FAN_APERTURE_D:g} вокруг центра нет материала кронштейна: "
      + ", ".join(f"{a} {v:.2f} мм³ (зазор {d:.2f} мм)" for a, v, d in ap) + "   "
      + ("PASS" if not any(f.startswith('CHECK11') for f in res['failures']) else "FAIL"))
    cr = explain_corners(parts, hardware, memo)
    tot_now, tot_before = sum(r[1] for r in cr), sum(r[2] for r in cr)
    tot = {k: sum(r[3][k] for r in cr) for k in CORNER_CLASSES}
    w(f"  12. (доп.) острые углы контуров на плитах (ребро вдоль направления выдавливания, излом граней > {rd.SHARP_DEG:g}°, радиус < 2 мм): "
      f"осталось {tot_now} из {tot_before} на нескруглённых деталях ({len(cr)} плит); из них без объяснения {tot['open']}; "
      f"по причинам: шаг нахлёста (вырез, не угол контура) {tot['lap']}, предел 97 % площади контакта или 4 мм плоскости у винта {tot['allowance']}, "
      f"стенка отверстия или головка винта {tot['hole']}, радиус от 2 мм не помещается {tot['nofit']}, ядро не смогло {tot['kernel']}, "
      f"объявлено (группа рельса, не разрывает деталь) {tot['declared']}, сбег галтели {tot['junction']}, ступень от выреза соседа {tot['contact']}; "
      f"падает только если на плите не скруглён ни один угол: наименьшее число убранных углов на плиту "
      f"{min(r[2] - r[1] for r in cr)}   "
      + ("PASS" if not any(f.startswith('CHECK12') for f in res['failures']) else "FAIL"))
    for name, now, before, by, op in cr:
        w(f"      {name:18s} острых {now:2d} из {before:2d}: " + ", ".join(f"{k} {by[k]}" for k in CORNER_CLASSES if by[k])
          + "".join(f"; без объяснения Y {c[1]:.1f} Z {c[2]:.1f} {c[3]:.0f}° длина {c[4]:.1f}" for c in op))
    dr = res.get("drives", [])
    if dr:
        o_, i_ = hw.drive_layout()["faces"]["outer"]["spec"], hw.drive_layout()["faces"]["inner"]["spec"]
        w(f"  13. (доп.) отсеки под диски: у каждых салазок рисунок отверстий совпадает с таблицей hardware.py ({dr[0]['holes']} отверстий на отсек, по записям Hole и по телам), материал под головкой "
          f"{min(v[0] for r in dr for v in r['run'].values()):.2f}..{max(v[1] for r in dr for v in r['run'].values()):.2f} мм, винт 3.5 входит {min(r['pen']['outer'][0] for r in dr):.2f} мм (стандарт {o_['enter'][0]:g}..{o_['enter'][1]:g}), "
          f"винт 2.5 входит {min(r['pen']['inner'][0] for r in dr):.2f} мм (стандарт до {i_['enter'][1]:g}), под каждой головкой есть место, отсек (салазки, диски, зоны штекеров) внутри |X| {hw.DRIVE_ENVELOPE[0][0]:g}..{hw.DRIVE_ENVELOPE[0][1]:g}, "
          f"Y {hw.DRIVE_ENVELOPE[1][0]:g}..{hw.DRIVE_ENVELOPE[1][1]:g}, Z {hw.DRIVE_ENVELOPE[2][0]:g}..{hw.DRIVE_ENVELOPE[2][1]:g}: " + "; ".join(f"{r['bay']} X {r['box'][0]:.1f}..{r['box'][1]:.1f}, Y {r['box'][2]:.1f}..{r['box'][3]:.1f}, Z {r['box'][4]:.1f}..{r['box'][5]:.1f}" for r in dr)
          + "   " + ("PASS" if not any(f.startswith('CHECK13') for f in res['failures']) else "FAIL"))
    p4 = res.get("plates420") or {}
    if p4:
        op = p4["openings"]
        w(f"  14. (доп.) пластины 420 (ревизия 11): в отверстиях трёх вентиляторов (круг Ø{hw.FAN_P14['opening_d']:g}, срезанный до {hw.FAN_P14['opening_flats']:g} по лыскам, "
          f"сквозь весь пакет u {hw.RAD420_BS[2]}..{hw.RAD420_BS[3]}) нет материала пластин: наибольший объём {max(v for _, _, v, _ in op):.2f} мм³, наименьший зазор {min(d for _, _, _, d in op):.2f} мм "
          f"({min(op, key=lambda r: r[3])[0]}, вентилятор {min(op, key=lambda r: r[3])[1]}); стенка пластины вокруг каждого из {len(p4['screws'])} винтов вентиляторов не меньше {hw.M3_MIN_WALL:g} мм: "
          f"{sum(1 for _, _, ok in p4['screws'] if ok)} из {len(p4['screws'])}; самая узкая перемычка пластины {min(wd for _, wd, _, _ in p4['webs']):.2f} мм "
          f"(не меньше {MIN_WEB:g}; {min(p4['webs'], key=lambda r: r[1])[0]}, |X| {abs(min(p4['webs'], key=lambda r: r[1])[2][0]):.0f}..{abs(min(p4['webs'], key=lambda r: r[1])[2][1]):.0f}, "
          f"n {min(p4['webs'], key=lambda r: r[1])[3][0]:.0f}..{min(p4['webs'], key=lambda r: r[1])[3][1]:.0f}); под низом вентиляторов (n {hw.RAD420_FAN_N[0]:g}) на {CHORD_FAN_GAP:g} мм материала антлеров нет "
          f"(наибольший объём {max(v for _, v in p4['underside']):.2f} мм³)   "
          + ("PASS" if not any(f.startswith('CHECK14') for f in res['failures']) else "FAIL"))
    w("")
    w("Скругление (ревизии 8 и 8a)")
    ref = reference_parts()
    mb = {p.name: mass_estimate(ref[p.name].solid, p.material) for p in parts}
    t0v = sum(m[0] for m in mb.values())
    t0_100 = sum(m[1] for m in mb.values())
    t0_20 = sum(m[2] for m in mb.values())
    w(f"  Масса до и после скругления (материалы по деталям): объём {t0v:.0f} -> {tvol:.0f} см³ ({tvol - t0v:+.1f}), 100 % {t0_100:.0f} -> {t100:.0f} г ({t100 - t0_100:+.1f}), "
      f"4 стенки/20 % {t0_20:.0f} -> {t20:.0f} г ({t20 - t0_20:+.1f})")
    for p in parts:
        v0, v1 = mb[p.name][0], mass[p.name][0]
        if abs(v1 - v0) >= 0.005:
            w(f"      {p.name:18s} {v0:8.1f} -> {v1:8.1f} см³ ({v1 - v0:+.2f})")
    done = [e for e in ROUND_LOG if e.radius > 0]
    short = [e for e in done if e.reason]
    sharp = [e for e in ROUND_LOG if e.radius == 0]
    w(f"  Скруглено {len(done)} углов, рёбер и стыков (из них радиус меньше желаемого у {len(short)}), оставлено острыми {len(sharp)}. "
      f"Желаемые радиусы: внутренние углы {ROUND_CONCAVE:g} мм, внешние {ROUND_CONVEX:g} мм, длинные рёбра коробчатых деталей {BOX_R:g} мм, галтель стыка до {ROUND_CONCAVE:g} мм; меньше {ROUND_MIN:g} мм не делается.")
    w(f"  Правило ревизии 8a: скругление может отнять площадь у контакта из отчёта, если контакт сохраняет не меньше {100 * rd.CONTACT_FLOOR:.0f} % своей площади без скругления "
      f"и не меньше {rd.SCREW_FLAT:g} мм плоского контакта вокруг каждого винта (от края самого большого отверстия винта, то есть от пилота вставки). "
      f"Две скруглённые плиты на одном контакте делят допуск пополам (по 1.5 %); допуск делится между углами так, чтобы каждый угол, который проходит по стенкам и винтам, получил хотя бы 2 мм.")
    ca = res.get("contact_areas") or []
    if ca:
        lost = [r for r in ca if r[3] < r[2] - 1e-3]
        grown = [r for r in ca if r[3] > r[2] + 1e-3]
        w(f"  Площади контактов (zero-gap, деталь x железо и деталь x деталь), без скругления -> теперь: {len(ca)} пар, потеряли площадь {len(lost)}, "
          f"выросли {len(grown)} (галтели внутренних углов добавили материал на плоскости контакта); "
          f"наименьшая доля {min(100 * r[3] / r[2] for r in ca):.2f} % (пол {100 * rd.CONTACT_FLOOR:.0f} %), наибольшее изменение {max(r[3] - r[2] for r in ca):+.2f} мм²   "
          + ("PASS" if not any(f.startswith('CONTACT') for f in res['failures']) else "FAIL"))
        w("  Контакты, потерявшие площадь (до -> после, доля):")
        for a, b, a0, a1 in sorted(lost, key=lambda r: r[3] / r[2]):
            w(f"      {a:18s} x {b:18s} {a0:9.2f} -> {a1:9.2f} мм² ({a1 - a0:+.2f}, {100 * a1 / a0:.2f} %)")
        w("  Контакты, выросшие в площади (галтели):")
        for a, b, a0, a1 in sorted(grown, key=lambda r: r[2] - r[3]):
            w(f"      {a:18s} x {b:18s} {a0:9.2f} -> {a1:9.2f} мм² ({a1 - a0:+.2f})")
        sf = res.get("screw_flat") or []
        w(f"  Плоский контакт в {rd.SCREW_FLAT:g} мм вокруг винта: {len(sf)} винтов пересекают контакт, потерявший площадь, у каждого площадь в круге не уменьшилась "
          f"(наименьшее {min((r[4] - r[3] for r in sf), default=0.0):+.4f} мм²)")
    w("  Меньше желаемого (радиус, причина):")
    for e in short:
        w(f"      {e.part:34s} {e.kind:8s} Y {e.pt[1]:.1f} Z {e.pt[2]:.1f}  r = {e.radius:g}: {ru_reason(e.reason)}")
    w("  Оставлено острым (причина):")
    for e in sharp:
        loc = "" if e.kind in ("layer", "junction") and e.pt == (0.0, 0.0, 0.0) else f"X {e.pt[0]:.1f} Y {e.pt[1]:.1f} Z {e.pt[2]:.1f}"
        w(f"      {e.part:34s} {e.kind:8s} {loc:30s} {ru_reason(e.reason)}")
    w("")
    g = sill_geometry()
    sl = next((p for p in parts if p.name == "front_sill"), None)
    if sl is not None:
        w("Передний порог front_sill и светлая линия (ревизия 9; всё железо тут PLACEHOLDER до обмера модуля)")
        b = bbox_of(sl.solid)
        w(f"  Сечение (Y, Z): " + " -> ".join(f"({y:.1f}, {z:.1f})" for y, z in g["pts"]) + f"; лицо - плоскость n = {g['n_face']:.2f} (параллельна плате, 45°), "
          f"задний гребень u = {g['u_top']:.1f}. Габарит X {b[0]:.0f}..{b[1]:.0f}, Y {b[2]:.1f}..{b[3]:.1f}, Z {b[4]:.1f}..{b[5]:.1f}: одна деталь "
          f"{b[1] - b[0]:.0f} мм <= {MAX_PART:.0f}, делить пополам не нужно.")
        io = hw.FRONT_IO_W
        w(f"  Карман: бокс модуля front_io X {io[0]:g}..{io[1]:g}, Y {io[2]:g}..{io[3]:g}, Z {io[4]:g}..{io[5]:g} плюс {SILL_POCKET_PLAY:g} мм с боков, сзади и сверху; открыт спереди и снизу "
          f"(модуль встаёт спереди и опирается на верх beam_front). Два винта {hw.FRONT_IO_SCREW_KIND} (PLACEHOLDER) вдоль X в торцевые стенки кармана. Отверстий под порты нет.")
        ls = hw.LIGHT_STRIP_BS
        w(f"  Канал светлой линии: бокс light_strip (X {hw.LIGHT_STRIP_X[0]:g}..{hw.LIGHT_STRIP_X[1]:g}, {hw.LIGHT_STRIP_SECTION[0]:g} x {hw.LIGHT_STRIP_SECTION[1]:g} мм по u, n, "
          f"u {ls[2]:g}..{ls[3]:g}, n {ls[4]:.2f}..{ls[5]:.2f}) плюс {SILL_CHANNEL_PLAY:g} мм, насквозь через оба торца порога (дышит); щель {hw.LIGHT_LINE_W:g} мм от канала к лицу "
          f"(диффузор {hw.LIGHT_DIFFUSER_T:g} мм из прозрачного PLA сядет в неё; посадочного места под диффузор пока нет). Ленка до {hw.LIGHT_STRIP_W_MAX:g} мм стоит на ABS, "
          f"от светодиодов до диффузора не меньше {hw.LIGHT_LED_TO_DIFFUSER_MIN:g} мм (в канале глубиной {hw.LIGHT_STRIP_SECTION[1]:g} мм это держится только при диффузоре в щели стенки, не в канале).")
        w(f"  Крепление к beam_front: {len(SILL_BOLTS)} x M4 снизу (проходные Ø{hw.M4_CLEAR_D:g} в beam_front, вставки M4 в нижней грани порога), по 2 в каждом концевом блоке: "
          + ", ".join(f"(X {x:g}, Y {y:g})" for x, y in SILL_BOLTS) + ".")
        wx0, wx1, wz0, wz1 = g["window_xz"]
        w(f"  Окно для кабелей в задней стенке (PLACEHOLDER, как модуль): X {wx0:g}..{wx1:g}, Z {wz0:g}..{wz1:g} насквозь через стенку {SILL_REAR_WALL:g} мм (Y {g['y_rear'] - SILL_REAR_WALL:g}..{g['y_rear']:g}), углы R {SILL_WINDOW_R:g}. "
          f"Заданы смещениями от hw.FRONT_IO_W: правый конец модуля минус {SILL_WINDOW_INSET:g}, ширина {SILL_WINDOW_W:g}, низ на {SILL_WINDOW_Z_LOW:g} мм выше низа модуля, верх по верху модуля. Винты модуля и их стенки в окно не попадают. "
          f"Отдельного окна для кабеля светлой линии нет: канал открыт через оба торца порога.")
        w(f"  Крепления органической оболочки: {len(organic_pilots('front_sill'))} пилота M3 в торцевых гранях (X +-{SILL_HALF_X:g}), см. hw.ORGANIC_PADS.")
        w(f"  Зазоры: до front_io {solid_distance(sl.solid, hardware['front_io']):.2f} мм, до light_strip {solid_distance(sl.solid, hardware['light_strip']):.2f} мм "
          f"(это зазоры кармана и канала по плану, не контакты); beam_front x front_io 0.00 мм: низ модуля стоит на верхней грани балки (контакт по плану: Z 10 у обоих).")
        w("")
    if TIE_POINTS:
        w(f"Кабельные точки крепления (проход 2 скелета, docs/plans/cables-and-organic.md, «Cable fixing»): {len(TIE_POINTS)} штифтов M3: в нижних гранях beam_low, beam_mid, beam_top и правого рельса (rib_A_right), во внутренних гранях правых рёбер (средняя нога rib_A_right, пост rib_B_right) и в верхней грани skid_front, "
          f"на каждом мостик tie_bridge (ABS, одна форма). Мостик {TIE_ARCH_END + TIE_HOLE_END:g} x {TIE_W:g} x {TIE_H:g} мм: лапа {TIE_FOOT_T:g} мм с проходным отверстием M3 Ø{hw.M3_CLEAR_D:g} "
          f"и арка рядом, в арке щель {TIE_SLOT_W:g} x {TIE_SLOT_H:g} мм под липучку 12 мм или стяжку (вдоль стороны {TIE_W:g} мм). Печать лапой вниз: потолок щели - мостик {TIE_SLOT_W:g} мм на высоте {TIE_FOOT_T:g} мм, "
          f"других нависаний нет. Винт M3 x 10 с головкой на лапе. Мостик держит {TIE_CLEAR:g} мм от всех деталей, кроме своей, и от железа; 3 мм до кабелей проверяет cables.py.")
        w(f"  {'мостик':18} {'деталь':12} {'грань':22} {'мир (X, Y, Z) оси отверстия на грани':38} {'стенка штифта':>14} {'ближайшая другая деталь':>34}")
        byname_ = {q.name: q for q in parts}
        near = {r[0]: (r[2], r[3]) for r in res.get("tie", [])}
        for tp in TIE_POINTS:
            pt = tie_face_point(tp)
            nm = tie_name(tp)
            wall = tie_pilot_wall(byname_[tp["host"]], tp)
            who, d = near.get(nm, ("-", float("nan")))
            w(f"  {nm:18} {tp['host']:12} {tp['face']:22} ({pt[0]:7.1f}, {pt[1]:7.1f}, {pt[2]:7.1f}){'':8} {('>= 8' if wall > 7.9 else format(wall, '.2f')):>11} мм {(who + ' ' + format(d, '.1f') + ' мм') if who else 'ничего ближе ' + format(TIE_CLEAR + 4.0, 'g') + ' мм':>34}")
        w("")
    if any(q.name.startswith("drive_sled") for q in parts):
        for line in drive_bay_lines(parts, hardware, res):
            w(line)
        w("")
    w("Положение болтов (Y, Z):")
    for label, ok, _ in BOLT_CHECKS:
        w(f"  {'ok ' if ok else 'BAD'} {label}")
    w("")
    if res["failures"]:
        w("ПРОВАЛЕНО:")
        for f in res["failures"]:
            w(f"  - {f}")
    else:
        w("ASSERTS: все проверки пройдены.")
    w("")
    w("Отклонения от плана")
    for d in DEVIATIONS:
        w(f"  - {d}")
    w("")
    w("Открытые вопросы")
    for o in OPEN_ITEMS:
        w(f"  - {o}")
    return "\n".join(L) + "\n", (t100, t20)


DEVIATIONS: list[str] = [
    # --- ревизии 1-3 (всё ещё верно для модели)
    "rib_A: добавлена перемычка capsule (40,-5)->(67.1,8.8) w20. По плану лапа/рог (Y<=50) и диагональ "
    "(Y>=53) не соприкасались, ребро A было двумя островами. Ревизия 7: рога нет, лапа с перемычкой и диагональ остались одним куском.",
    "Нижняя зона нахлёста расширена с Y 185..220 до Y 185..225: скруглённый конец лапы A (до Y=222) "
    "иначе пересекал бегунок B (~100 мм³).",
    "Болты нахлёста: нижний (202,-5) -> (212,-5), чтобы не лежать в 2.5 мм от болта skid_front; "
    "верхний второй (276,219) -> (268,210), чтобы не лежать в 5 мм от болтов beam_top. "
    "Верхний первый (262,205) без изменений. Стенка между двумя верхними штифтами 2.2 мм.",
    "skid_front: 1 болт на конец вместо 2. Бегунок B покрывает болт Ø4.5 только при Y >= 194, "
    "скид кончается на Y=205, второй болт попадал бы в 2.5 мм от болта нахлёста или за край скида.",
    "Концы диагонали A оставлены по плану (u = 280): деталь уже 288.1 мм из 290, сдвиг дальше невозможен.",
    "beam_top: болты перенесены в ребро B (по плану). Колонна из двух болтов Ø5.6 с стенкой 2.1 мм помещается "
    "в сечении 20 мм только по центру (u 298.45, n -23.3 и -13.5 -> Y,Z (287.5,224.5) и (280.6,231.5)); "
    "носок B их не покрывает (верхний болт в 15.7 мм от оси носка при радиусе 14). Поэтому: (1) в B добавлен "
    "диск в центре сечения beam_top (Ø24 до ревизии 5, теперь Ø19, см. ниже); (2) в зонах нахлёста B теряет внутреннюю половину только там, "
    "где есть A (вырез = контур A), иначе между торцом балки (X=142) и B был бы зазор 8 мм.",
    "Носок B (скругление капсулы в (266,212)) входил в io_zone: пересечение 86 мм³, глубина ~0.9 мм. "
    "Носок срезан плоскостью n = -5.81 (зазор 2.0 мм до io_zone); болты нахлёста лежат при n <= -19 и не затронуты.",
    "psu_bulkhead: на концах бобышки X ±(122..142), Y 369..381 (пластина 6 мм не держит штифт); вставка M4 9.1 мм "
    "в бобышке 20 мм влезает, болты в хвостовую стойку на (Y 375, Z 5 и 80).",
    "beam_mid: вставки в торцах M4S (5.0 мм). Штифт M4 9.1 мм доходит до v = -10.9 и пересекается с проходным "
    "отверстием болта gpu_post (v = -10.5, радиус 2.25). Болты gpu_post: v = -10.5, u = 131 и 139 (стенка 2.8 мм до края "
    "beam_mid u = 125.97 и 4.2 мм до края поста u = 146; два штифта на расстоянии 8 мм, стенка 2.4 мм).",
    "gpu_post: v -20..-5.5 вместо -20..-6: при v = -6 стенка штифта у края была бы 1.7 мм (< 2.1); теперь 2.2 мм.",
    "Ревизия 2: dimms по плану v 183..221, u 158..295 пересекается с eps (u 290..305) на 7600 мм³ (5 мм по u, проверка 1). "
    "Сканом DIMM-слоты кончаются при u около 291, поэтому u1 = 290 вместо 295: зона касается eps с нулевым зазором. "
    "Ревизия 3: dimms начинается с u = 146, а не 158, как в плане: слоты занимают u 146..291 на скане "
    "(refs/board_scan_overlay.png, 840 px / 5.76 px/мм).",
    "Ревизия 2: gpu_post u 73.0..146 (нижняя грань карты 75.6 минус 2.6), gpu_rest палец с верхней гранью u = 75.6 "
    "(центр u = 67.6, ширина 16).",
    "Ревизия 2: beam_top в 3.19 мм от eps - это бобышка M (v 237.49) под платой: зона eps начинается на поверхности платы "
    "(n = 0), бобышка кончается на n = -2, в плане её край в 2.5 мм от зоны. Это не столкновение.",
    "Стенки штифтов и между ними измеряются кольцом толщины = стенке вставки вокруг каждого штифта (объём кольца "
    "минус материал детали < 0.5 мм³). Для M5 (шарнир) вставка в плане не задана, принята стенка M4 2.1 мм; обоснования в плане нет.",
    "Ревизия 3: пробный цилиндр для проверки «отверстие пусто» на 0.1 мм уже по радиусу (иначе его стенка совпадает с "
    "поверхностью отверстия и булево нестабильно). Сверление диаметром меньше номинала менее чем на 0.2 мм не будет "
    "обнаружено этой проверкой.",
    "Ревизия 3: отверстия - записи Hole у каждой детали (Part.holes), для левых деталей зеркальные; неотверстия-вырезы "
    "(окно БП, зоны нахлёста, выемка плеча) не записи. В frame_v0.py нет чисел, повторяющих hardware.py (проверяет test_checks.py).",
    "Ревизия 4: cpu_block - цилиндр R 45.5 (n 0..76) плюс ушко (v ±22, u от сокет-62.97 до сокет-40, n 0..74.7), как в плане.",
    # --- ревизия 5
    "Ревизия 5, hoses.py: маршруты перенесены из hose_routes.py без изменения чисел (таблица та же: CPU 482 из 500, GPU 435 из 450, "
    "радиус 35). hardware.py импортирует hoses.py внутри build_hardware (hoses.py импортирует hardware.py ради констант), "
    "поэтому зависимость в одну сторону только при вызове.",
    "Ревизия 5, keep-out шлангов: вместо цепочки цилиндров со сферами в стыках (fuse 50 тел, 5 с на шланг, 19 с на build_hardware) "
    "труба-sweep окружности по ломаной из каждой третьей точки маршрута, стыки скруглены (transition='round'), 0.1 с. "
    "Измерено на CPU-шланге R 8: объём sweep 96415 мм³ против 95965 мм³ у цепочки, то есть на 0.5 % толще (запас в безопасную сторону).",
    "Ревизия 5, концы keep-out шлангов: по плану плоские концы у воротников. Измерено: если довести маршрут до кончика порта "
    "(u 290 у 420, n 102 у 360), пара CPU входит в rad420_ports на 804 мм³, пара GPU в rad360_ports на 765 мм³ (проверка 1). "
    "Правка: цепочка кончается на грани ящика порта (u 288, n 100), то есть на 2 мм раньше кончика; "
    "начало цепочки заходит на 5 мм вглубь cpu_block / gpu и срезано по их поверхности (иначе плоский торец наклонён хордой первого "
    "изгиба и входит в карту на 28 мм³).",
    "Ревизия 5, gpu_tubes снят: оценочный бокс (bs v 278..338, u 80.6..121.6, n 5..75) заменён измеренным маршрутом gpu_hoses; "
    "измерено пересечение старого бокса с gpu_hoses 25292 мм³, то есть они описывают одно и то же место, проверка 1 падала бы.",
    "Ревизия 5, rad420_ports по плану (bs v -111..-86) выходит за |X| = 229 до 233: воронки Ø20 в 8.4 мм от торца стоят на 1.6 мм "
    "за торцом радиатора. Это железо, не деталь и не шланг, проверка 8 его не меряет; шланги и детали внутри 229 "
    "(шланг CPU до 228.6).",
    "Ревизия 5, rib_A: передний конец лапы Y 8 -> 10 (capsule (10,-5)->(40,-5)): радиус 10 давал Y = -2, то есть деталь перед "
    "плоскостью Y = 0 (проверка 8; плоскость задавали передние вентиляторы, теперь это константа ENVELOPE_Y0 = 0). Болт beam_front (10, 0) остаётся со стенкой 2.75 мм.",
    "Ревизия 5, rib_B, кредл: верх плоскость n = -18 над u 312..364, а не 312..376. Измерено: до u 376 ребро B имеет высоту Z -15..283.1, "
    "298.1 мм при пределе 290; конец кредла на u 364 даёт 289.7 мм. Опора под радиатором 52 мм из 68 (ядро u 310..348 опирается целиком). "
    "Контур: полигон (Y,Z) от (293.3, -5) вверх по плоскости n = -18 до (330.1, 274.7), горизонталь до Y 348 (POST_REAR_Y), вниз; "
    "горизонтальный участок оставлен, чтобы за язычком антлера было тело ребра (болты язычка на Y 328.7 и 340.0). "
    "Диск Ø24 под болты beam_top уменьшен до Ø19 (радиус 9.5 держит стенку 2.35 мм у болта в 4.9 мм от центра): "
    "с Ø24 он подходил к углу радиатора на 0.05 мм, теперь зазор 2.55 мм.",
    "Ревизия 5, антлеры: пластина 10 мм на u 378..388, планка X 68..212 по n -18.25..1.75 (нижний ряд винтов n -8.25 ± 10), палец "
    "X 193..212 до n 125 (верх радиатора n 123 плюс 2), три проходных отверстия Ø4.0 по u из таблицы hardware.py. "
    "Язычок X 158..168: плита u 338..388, n -56..-20 плюс перемычка u 378..388, n -56..-16 к планке; "
    "два болта M4 вдоль X на (u 350, n -30 и -46) в ребро B. Контуры язычка в плане не заданы, это мой выбор: самые простые.",
    "Ревизия 5, шея: стойка по n на u 284..307 (в плане u 287..307, 20 мм) и n -58..120 вместо -30..115. Кромка u 284 нужна болтам "
    "соединения с плечом (ревизия 6, u 289.2): при кромке 287 стенка вокруг проходного отверстия была бы 2.2 - 2.25 < 0, при 284 - 2.95 мм; "
    "(в ревизии 5 её же требовал шарнир). Нижний конец спущен до n -58: "
    "в плане болты накладки на n -30 попадали на 2.7 мм от сквозного отверстия болта beam_top (287.5, 224.5) в ребре B (нужно 7.15). "
    "Болты на (u 295.5, n -34 и -52), накладка X 158..180, u 284..307, n -58..-22. Верх стойки n 120 (2 мм под 360: стойка стоит в её "
    "ширине X 180..192 < 197).",
    "Ревизия 5, шарнир и замок визора (M5 на u 290, M4 на u 275, ушко шеи u 270..307) сняты в ревизии 6: шарнира на 360 нет, "
    "см. «Ревизия 6, соединение плеча с шеей».",
    "Ревизия 5, правое плечо визора: выемка X > 175 на u 219..270, n до 123. Измерено: плечо X 166.5..178.5 входит в rad360_ports "
    "(X >= 176) на 1715 мм³ (проход мимо бака с воротниками). Плечо там 8.5 мм вместо 12; отверстия винтов на u 192 и 297 вне "
    "выемки, стенки не тронуты. Левое плечо без выемки (зеркальное, без бака). Подъём плеча над шлангом CPU из ревизии 4 снят: "
    "шланги CPU теперь слева. Ревизия 6: внешняя грань плеча теперь X 180 (было 178.5), выемка считается от неё же.",
    "Ревизия 5, направляющие: размеры: длина вдоль шланга 12 мм; CPU: стопа X -202..-192 (u 272..300) на внешней грани левой шеи, полки на "
    "прямом участке u 274..286, 1 винт M4S в шею на (u 294, n 54); GPU: пластина X 158..168 на внешней грани правого ребра A "
    "(u 166..178), полки до оси шлангов, 1 винт M4 на (u 172, n -20). Канал по плану Ø шланг + 0.6 в ревизии 5 входил в keep-out "
    "(R 8.0 / 7.8) на 966 мм³ (CPU) и 998 мм³ (GPU), поэтому тогда канал был сделан по keep-out + 0.2 мм с люфтом 1.8 мм; в ревизии 6 это исправлено (ниже).",
    # --- ревизия 7
    "Ревизия 7, hardware.py: удалены FANS_FRONT_W, FAN_HOLES_X/Z, fans_front; ENVELOPE_Y0 стала константой 0.0 (раньше читалась из FANS_FRONT_W[2]), "
    "порог Y >= 0 не менялся. Добавлены fan_side_right / fan_side_left (X 201..226 и -205..-180, u 120..260, n -42..98 по таблице плана; v считается из X через x_to_v), "
    "четыре угла на шаге 124.5 вокруг центра (u 190, n 28): A (127.75, -34.25), B (252.25, -34.25), C (127.75, 90.25), D (252.25, 90.25), ось вдоль X. "
    "Измерено до всего остального: правый 2.00 мм до rad360_ports и 3.77 до gpu_hoses, левый 8.00 до io_zone и 7.60 до cpu_hoses - как в плане. "
    "shell_concepts.py (keep_clear) обращается к hw.FANS_FRONT_W: импорт проходит, вызов даст AttributeError; organic_frame.py импортирует shell_concepts. "
    "По заданию оба файла не тронуты.",
    "Ревизия 7a, третий винт правого вентилятора: к кронштейну добавлены планка и лапка, проверка 5 для fan_side_right зелёная (3 из 4 углов: A и C штифтами с внутренней грани, D "
    "через лапку с внешней). Причина по-прежнему та, что любой материал на ВНУТРЕННЕЙ грани у B и D ближе 5 мм к шлангу GPU (4.10 мм, измерено в ревизии 7; keep-out R 7.8 "
    "до X 197.2, грань вентилятора X 201 в 3.77 мм). Планка идёт снаружи верхней кромки вентилятора: X 202..226 (внутренняя грань на 1.0 мм дальше от шланга, чем грань вентилятора), "
    "n 98.5..104 (0.5 мм над кромкой вентилятора n 98, ширина 5.5), u от хребта (u 121) до 262; хребет поднят до n 104 (в плите X 191..201, u 116..122), корневой блок X 191..226 "
    "u 116..122 соединяет его с планкой над верхней кромкой вентилятора. Лапка: X 226..228.5 (2.5 мм), u 246..262, n 84..104, сквозное отверстие Ø4.5 на оси угла D (u 252.25, "
    "n 90.25); материал вокруг отверстия 6.25 мм к низким u и n (нужно 4), 9.75 мм к верхнему u, 13.75 мм к верхнему n; лапка прилегает к внешней грани вентилятора (контакт, как плита "
    "на внутренней). Измерено до шланга GPU: планка 5.60 мм (проверка 9, нужно 5; минимум по детали 5.60), хребет у планки 7.19 мм, лапка 29.6 мм; до rad360_ports планка 1.00 мм "
    "(это бокс воротников с запасом, зазор по клэшу у вентилятора 2.00 мм; требования на него нет, проверка 2 по объёму зелёная); до вентилятора планка 0.50 мм, лапка 0.00 (контакт). "
    "Предел |X| 229: максимум детали 228.5 (fan_bracket_right), запас 0.5 мм. Проверка 11: зазор до круга Ø134 у правого остался 1.00 мм, объём 0.00. Не учтено: головка винта "
    "вентилятора снаружи лапки (X > 228.5) выйдет за |X| = 229 примерно на 2-3 мм (M4 с цилиндрической головкой ~ 4 мм; потайная в лапку 2.5 мм не ляжет), проверка 8 деталей "
    "железо винтов не считает. Прочность планки 5.5 мм и лапки 2.5 мм не считалась.",

    "Ревизия 7, контур кронштейнов (в плане только намерение): плита 10 мм на внутренней грани вентилятора (правый X 191..201, левый X -180..-170), контур C: "
    "хребет вдоль n на u 116..122 (в 1 мм от круга Ø134, нижняя точка круга по u = 123; ширина 6 мм), ушки 9.8 x 9.8 мм вокруг каждого штифта (половина = Ø5.6/2 + 2.1 стенки = 4.9), "
    "у левого ещё планка вдоль нижней кромки n -47..-39.5 (в 0.5 мм под кругом, ширина 7.5 мм) к углу B. Нога от хребта к внешней грани ребра A: u 116..127, n -34..-6 "
    "(полная ширина диагонали ребра), справа X 158..192, слева X -171..-158. Минимальное сечение 6 мм (>= 5). Вставки M4S (5.0 мм) под винты вентилятора, "
    "винты идут с внешней стороны вентилятора; в плите 10 мм за штифтом остаётся 5 мм.",
    "Ревизия 7, крепление к ребру: два болта M4 вдоль X на u 121, n -26 и -14 (12 мм друг от друга, стенка между штифтами 6.4 мм), проходные Ø4.5 в rib_A "
    "(капсула диагонали n -34..-6), вставка M4 в грань ноги, головы на внутренней грани ребра (как у торцов поперечин, но с другой стороны). "
    "Снаружи головы не поставить: они упирались бы в вентилятор. u 121 выбрано так, чтобы голова (радиус 3.5) кончалась на u 124.5, а beam_mid начинается на u 125.97, "
    "и чтобы нога справа кончалась в 6.7 мм от keep-out шланга GPU, который при X 191 идёт вниз на u 101..103. Правая нога длиной 34 мм (X 158..192), левая 13 мм.",
    "Ревизия 7, проверка 11 добавлена (в плане её нет): кронштейн не входит в круг Ø134 (FAN_APERTURE_D) вокруг центра вентилятора, объём пересечения с цилиндром < 1 мм³. "
    "Цилиндр - щуп внутри run_checks, не железо: как keep-out он пересёк бы hose keep-out (X 193..201 против шланга при X 181..197), и проверка 1 падала бы. "
    "Измерено: зазор правого 1.00 мм, левого 0.50 мм до круга.",
    "Ревизия 7, проверка 5: для боковых вентиляторов считается число углов с отверстием на оси в кронштейне (точка на оси в 1.5 мм от грани; на 2.5 мм ближайшим материалом "
    "становилось дно штифта глубиной 5.0, а не стенка). Нужно не меньше 3 из 4, угол без винта сам по себе не ошибка. Левый 3 (A, B, C), правый 3: A и C штифтами с внутренней грани, D отверстием Ø4.5 в лапке на внешней грани (ревизия 7a; точка на оси посередине лапки, ближайший материал на расстоянии радиуса 2.25 ± 0.2). Угол считается один раз, если есть отверстие на любой из граней.",
    "Ревизия 7, рог и fan_rail_top удалены, beam_front остался простой коробкой Y 0..40, Z -10..10 с двумя штифтами на конце (болты (10, 0) и (30, 0)); проверка 7 зелёная.",
    "Ревизия 7, test_checks.py: случай «front fan row z shifted» заменён на сдвиг угла A боковых вентиляторов. Ревизия 7a: 61 случай (было 54); случаи «right fan has 2 screws» "
    "и «the only failure» заменены на «оба вентилятора по 3 винта», «третий винт - лапка» и «модель без повреждений не даёт ни одной ошибки»; добавлены: отверстие лапки заделано (CHECK7 и CHECK5 2 of 4), "
    "один штифт заделан (CHECK5 2 of 4), кронштейн сдвинут на 1 мм наружу (CHECK8 |X| > 229), планка расширена внутрь на 4 мм (CHECK9), блок планки в круге Ø134 (CHECK11).",
    # --- ревизия 6
    "Ревизия 6, beam_top: сечение сдвинуто на 3.5 мм вниз по склону, u 284.95..304.95 (row - 13.5 .. row + 6.5, ширина 20 как была). Измерено: "
    "beam_top x rad420 5.05 мм (было 1.55). Концевые болты остались там же (колонна из двух на u = 298.45, n -23.3 и -13.5): сдвинуть их на новую "
    "ось сечения (u 294.95) нельзя. Измерено на собранном ребре B (проверка 7, кольцо стенки вокруг проходного отверстия): на u 294.95 стенка 0.01 мм "
    "и 0.12 мм вместо 2.1, потому что отверстия оказываются у выреза B под капсулу диагонали A (центр u 280, n -20, R 14); на u 298.45 обе в норме. "
    "Стенка штифта до верхнего края сечения 3.7 мм (нужно 2.1), до нижнего 10.7 мм. Диск Ø19 в ребре B под эти болты не менялся (2.55 мм до 420, это не beam_top). "
    "Бобышки стоек остались на отверстиях платы (v, u = row).",
    "Ревизия 6, пальцы антлеров: конец n 121 (плана: 121; в коде RAD420_BS[5] - 2), стенка до верхнего винта (n 116.25) 4.75 мм при нужных 3.6. "
    "ВЕРХ КАРКАСА: план требует «ни одна деталь не выше верхней кромки 420». Буквально по высоте Z это невыполнимо при его же числах: пластина антлера "
    "10 мм за вентиляторной гранью, плоскость верха наклонена на 45° и растёт назад, поэтому внешний угол пальца (u 388, n 121) на Z 389.9, "
    "верхний угол радиатора (u 378, n 123) на Z 384.3 - выше на 5.6 мм (с n 125 было 392.7, на 8.4 мм). Чтобы он был не выше 384.3, пластина на пальце "
    "должна быть тоньше 1.9 мм, а винт 6-32 на n 116.25 выходит через неё на Z 386.6. Проверка 8 реализована в плоскости платы: ни одна деталь "
    "не выше верхней грани 420 (n <= 123, hardware.ENVELOPE_N), то есть над линией верхней грани радиатора на виде сбоку; максимум 122.00 (visor_arm_right, "
    "это грань 360), палец 121. Z верха каркаса (389.9, antler_right) и верха 420 (384.3) выводятся в отчёте. Если нужен именно Z <= 384.3, "
    "решение за владельцем: пластина тоньше или палец без верхнего винта.",
    "Ревизия 6, соединение плеча с шеей (без шарнира): два болта M4 вдоль X, вставки M4S в плече (с X 180, глубина 5.0), проходные Ø4.5 в шее, на u 289.2, "
    "n 114 и 93.5, расстояние 20.5 мм. Плана «два болта на 20 мм и более вдоль плеча» по u выполнить нельзя: по расчёту вдоль u остаётся окно u 288.35..290.1 "
    "(слева стенка 2.1 вокруг проходного отверстия в шее при кромке шеи u 284, справа стенка 2.1 вокруг штифта до отверстия винта радиатора M3 "
    "в плече на u 297, его ось идёт по n через всю планку). Измерено на собранных деталях (проверка 7): болт на u 289.2 в норме, на 288.0 стенки 1.80 мм (шея) "
    "и 1.29 мм (плечо), на 290.1 стенка штифта 1.69 мм, на 291.0 0.79 мм. Поэтому: (1) два болта разнесены по n: "
    "верхний в планке (n 114), нижний на «колене» плеча (n 93.5): блок X 166.5..180, u 284..294.5, n 88..108 под "
    "планкой, он кончается за 0.5 мм до отверстия M3 (u 295) и не перекрывает 420 (до неё 15.5 мм); (2) плечо толще на 1.5 мм (внешняя грань X 180 вместо 178.5): "
    "плечо и шея теперь касаются плоскостями X = 180 (зазор был 1.5 мм, болты тянули бы стойку 12 мм на 1.5 мм). Контакт деталь x деталь в списке "
    "контактов; расстояние от штифта до отверстия M3 3.6 мм (измерено). Ушко шеи u 270..307, диск и отверстия M5 удалены (служили только шарниру).",
    "Ревизия 6, направляющие: канал Ø = Ø шланга + 0.6 (радиус 6.5 CPU, 6.3 GPU от настоящих радиусов hardware.py), открыт в одну сторону "
    "(CPU к -X, GPU к +X) горловиной 0.75 x Ø шланга (9.3 мм CPU, 9.0 мм GPU), полка заходит за ось шланга на радиус канала, поэтому губа в месте входа "
    "в горловину толщиной около 2 мм (ось GPU-шланга A на направляющей отклонена на 11.8° от плоскости YZ и смещается по X на 2.5 мм на её длине, шланга B на 0.9°, поэтому конец полки берётся по самой дальней точке оси, а горловина строится в плоскости, перпендикулярной оси). "
    "Полки CPU кончаются на X -227.1 (предел 229). Проверка 2 для направляющей против keep-out своего шланга пропущена (в нём 1.8 мм запаса, а канал "
    "его занимает); против keep-out второй пары остаётся. Проверка 10: объём пересечения с трубой настоящего радиуса < 1 мм³ (0.00), стенка канала "
    "0.30 мм (нужно 0.2..0.5), горловина измеряется двумя плитами шире и уже на 0.4 мм (должна пройти уже, не пройти шире). Труба настоящего радиуса "
    "строится по маршрутам hoses.py, не попадает в keep-out. У CPU-шланга B при радиусе 6.2 sweep с transition='round' даёт невалидное тело "
    "(isValid false, объём тот же), для труб проверки 10 при этом берётся transition='right' (объём 58523 мм³ против π r² L = 58523, повороты менее 20°). "
    "Это не зажим на защёлке: упругость шланга при проходе горловины 12.4 -> 9.3 мм не проверялась (резиновый шланг должен сжиматься на 3.1 мм).",
    "Ревизия 6, test_checks.py: время прогона 595 с -> 44 с без потери случаев. Причина: bbox_of считал оптимальный габарит (25 мс на деталь с отверстиями) "
    "при каждом inter_vol, тысячи раз на одну деталь (из 35 с одного run_checks 25 с): теперь габариты кэшируются по телу. Второе: run_checks "
    "принимает необязательный memo, в который складываются результаты пар и отверстий по идентичности тел, поэтому повреждённая копия пересчитывает только "
    "пары и отверстия своей повреждённой детали; полная модель считается без memo в начале (пустой memo) и в конце (memo не передан). Случаи с подменой "
    "intersect идут без memo. Все 32 старых случая дают те же строки, плюс 10 новых (проверка 8 сверху, проверка 10).",
    "Ревизия 5, test_checks.py: случай «literal scanner finds the old antler / arm literals» ждал 7 попаданий, из них 252.75 и 377.25, которых в "
    "hardware.py больше нет (отверстия 420 теперь в n: -8.25 и 116.25). Образец переписан под новую таблицу, ожидается 5 попаданий "
    "(77.75, 202.25 дважды, 116.25, 172.5); -8.25 меньше порога 10 у сканера. Сам сканер не менялся.",
    "Ревизия 5, tube_study.py перенесён в history/ с одной строкой в начале; строка E в layout_b6_options.py переписана под 420 в "
    "пространстве платы (box из плана), порты шлангов заданы кончиками портов, длины трасс (482 из 500, 435 из 450) печатаются из hoses.py.",
    # --- ревизия 8
    "Ревизия 8, как устроено: контур плиты скругляется в 2D до выдавливания (cad_b6/rounding.py, BRepFilletAPI_MakeFillet2d по грани контура), "
    "коробчатые детали - вырезом клина по длинному ребру, галтели стыков (правило 4) - 3D-галтелью выбранных вогнутых рёбер. build_frame(rounded=False) даёт каркас "
    "до ревизии 8 (острые углы): с ним сравнивается каждое скругление, и его берёт check 12 как эталон. Для каждого угла радиус ищется делением пополам "
    "от желаемого (8 / 6 мм) вниз до 2 мм; принимается наибольший, при котором снятый (выпуклый угол) или добавленный (вогнутый) осколок проходит Guard. "
    "Левые детали строятся правосторонними и зеркалятся, поэтому для них соседи (железо и другие детали) зеркалятся тоже; левые и правые детали "
    "скругляются каждая своим расчётом (ребро B слева и справа, антлеры, шеи, плечи).",
    "Ревизия 8, главный конфликт плана: правило 1 велит скруглять внешние углы радиусом 6 мм, правило 3 запрещает уменьшать площадь любого контакта из отчёта. "
    "Каждый выпуклый угол грани, лежащей на железе или на другой детали, снимает с неё площадь (r = 6 мм: 7.7 мм², 3 мм: 1.9 мм²). Выбрано правило 3 (предел жёсткий): "
    "56 выпуклых углов оставлены острыми, из них 36 из-за площади контакта (антлеры на грани вентиляторов 420: 3 угла пластины и 2 угла язычка на ребре B на антлер; "
    "накладка шеи на пост B: 4 угла; ноги кронштейнов на ребре A: 4 угла на кронштейн; плечо визора на шее: 2 угла; шея на плече: 1; ребро B: угол на нахлёсте (9.2 мм²) и угол у антлера (7.7 мм²)), "
    "9 из-за стенки отверстия (плечи визора у винтов 6-32, кронштейны у вставок вентилятора, beam_top у штифта), 7 потому что между соседними рёбрами не помещается 2 мм, "
    "4 - концы поверхности кредла (по правилу 3). Нижние углы пластин антлера, которые висят за краем 420 (n -18.25 против грани n -15), скруглены радиусом 3.5 мм; нижние углы "
    "плеч визора вне шеи - 2.5 мм. Если владелец хочет скругления и на контактных гранях, цена - увеличить сами грани примерно на 0.1 мм по контуру (площадь потерь 31 мм² на пластину антлера "
    "при r = 6 мм при периметре около 300 мм): я этого не делал, это меняет сопрягаемые грани.",
    "Ревизия 8, внутренние углы: 34 угла скруглены радиусом 8 мм, 5 - меньше (4 / 5.5 / 6 мм: ребро A у стопы мидлега на Y 206 Z 5 даёт 5.5 мм, у gpu_rest правого ребра 6 мм - при 8 мм осколок вошёл бы в карту, язычок антлера 4 мм), "
    "6 остались острыми: пара углов B на носке (Y 292.4 Z 232.5 и Y 293.4 Z 232.8) в 0.9 мм друг от друга на каждом ребре B, четыре угла (двум кромкам нужно 1.55 r, то есть r не больше 0.6 мм), "
    "и по одному углу у каждого плеча визора рядом с отверстием винта 6-32 на u = 297 (колено плеча в 2.5 мм от оси; добавленный материал закрыл бы подход к головке винта; при 8 мм стенка вокруг отверстия была бы 0.08 мм, проверка 7 это поймала). "
    "Ограничение Guard для вогнутого осколка: он не пересекает соседей (объём < 0.01 мм³), не входит в стенку отверстия и не подходит к железу ближе, чем сама деталь уже к нему подходит (но не ближе 2 мм), "
    "к шлангам - не ближе 5 мм (проверка 9). Измерено на готовой модели: все 16 зазоров < 5 мм детали x железо те же, что до ревизии (до 0.001 мм), зазоры до шлангов те же.",
    "Ревизия 8, коробчатые детали: радиус 3 мм по длинным рёбрам вырезом клина, концы (4 мм) остаются острыми: торец детали упирается в ребро, площадь торца нельзя уменьшать (радиус 3 мм забирает 1.9 мм² с каждого угла торца, 7.7 мм² с торца). Поэтому у beam_front, beam_low, beam_mid, beam_top, skid_front, skid_rear, gpu_post (только нижний конец, верх свободен) "
    "на концах остаётся ступенька-плечо 4 мм. beam_mid: два ребра со стороны малых u остались острыми - у них стенка до проходного отверстия болта gpu_post (v -10.5, u 131) была бы "
    "ниже 2.1 мм при любом радиусе от 2 мм. beam_top: ребро у штифта скруглено 2.5 мм вместо 3 (стенка штифта). Верхние рёбра скидов (грань Z = 0 несёт БП) и нижние рёбра psu_bulkhead "
    "(грань на столе, контактная площадка) оставлены острыми. psu_bulkhead: пластина 6 мм, радиус 2.75 вместо 3 (при 3 на кромке не осталось бы плоского участка), "
    "скруглена только между концевыми бобышками (X ±122), бобышки остались острыми, как их торцы на хвостовой стойке.",
    "Ревизия 8, направляющие шлангов не скруглены: каждое наружное ребро стопы или пластины - ребро полки, а стенка канала у полки 2.5 мм (губа горловины около 2 мм). Радиус 3 мм на ребре полки "
    "сводит стенку к нулю на торцах полки (дуга касается на 3 мм от угла, радиус канала 6.3..6.5 из 8.8..9 мм полувысоты), радиус 2 мм оставляет 0.5 мм. План называет направляющие среди коробчатых деталей; "
    "выполнить правило 2 для них нельзя, не нарушив проверки 10 по смыслу (стенка канала).",
    "Ревизия 8, кронштейн правого вентилятора: рельс, корневой блок, шарнир и лапка (2.5..5.5 мм, соединены нахлёстами по 1 мм) остались острыми: скругление любой из этих четырёх коробок разрывало "
    "кронштейн на два тела (проверка 7 ловила 'two separate solids', измерено 18789 + 21208 мм³). Плита и нога скруглены.",
    "Ревизия 8, правило 4 (галтель 8 мм на стыке бобышки, ушка, язычка, ноги): шея, накладка к стойке - 8 мм (одно ребро по u на каждую шею); антлер, язычок к планке - 8 мм (одно ребро); "
    "бобышки beam_mid - 5 мм (высота бобышки 6.35 мм, остаётся 1.35 до платы); beam_low и beam_top - нет (подошва галтели 5 + r должна лежать на плоской вершине, которая от оси бобышки 7.0 и 3.5 мм); "
    "ноги кронштейнов - 5.5 мм справа и 3.0 мм слева (ядро не берёт больше: Standard_Failure на 6 мм и выше справа, 3.5 мм слева), по 3 ребра; ушки кронштейна и бобышки - углы контура, они в п. 1. "
    "Галтели добавляют материал, Guard проверил их так же, как вогнутые углы.",
    "Ревизия 8, проверка 12 (в плане описана так: излом контура > 30°, радиус < 2 мм, вне исключённых граней; падает, только если ни один угол плиты не скруглён). "
    "Реализация: на каждой плите (рёбра A, B, шеи, плечи, антлеры, скобы вентиляторов: 12 деталей) ищутся прямые рёбра вдоль направления выдавливания длиной от 2 мм, у которых соседние грани сходятся под углом > 30° "
    "(такое ребро острое по построению, радиус 0). Потерял ли каждый угол радиус, считается против эталона: тот же каркас без скругления (build_frame(rounded=False)). Падает, если у плиты острых рёбер не меньше, чем у эталона. "
    "Для отчёта каждое оставшееся ребро объясняется: шаг нахлёста (длина не больше половины ребра, на границе зоны), контакт (плоская площадка контакта с железом или деталью не дальше 8 мм от ребра, "
    "то есть скругление её съело бы), объявлено (кредл; группа рельса правого кронштейна), сбег галтели ноги или без объяснения. Без объяснения: 0. "
    "Не считаются рёбра антлера вдоль X вне язычка и вдоль u длиннее толщины плиты (это кромки, не углы контура), и ступень выемки плеча (5 мм).",
    "Ревизия 8, площади контактов (в плане 'тот же контакт с той же площадью или больше'): check_contact_areas сравнивает площадь плоского контакта у каждой из 43 пар из отчёта с эталоном без скругления. "
    "Измерено: ни одна не уменьшилась (минимальное изменение 0.0000 мм²); выросли 13 (антлеры к 420 +13.73 мм², кронштейн к вентилятору +54.94 слева и +38.15 справа, ребро B к шее +13.23, "
    "к beam_top +3.07, ребро A к направляющей GPU +1.38), потому что галтель внутреннего угла добавляет материал на самой плоскости контакта. Это отдельный счёт 'CONTACT' в report, не пронумерованная проверка; "
    "test_checks.py проверяет и его (случай с вырезанным углом контактной грани антлера).",
    "Ревизия 8, скорость: frame_v0.py 37 -> около 62 с, test_checks.py 44 -> около 81 с. Из прироста frame_v0 около 10 с - само скругление (около 230 кандидатов, "
    "каждый с осколком и булевыми операциями против примерно 70 соседей, плюс 7 галтелей стыков по 0.3 с), около 8 с - проверка 12 (поиск рёбер, эталон, объяснение), около 1.5 с - площади контактов, "
    "остальное - более тяжёлые тела в проверках 1-3 и 7 (больше граней: distance() на них вдвое дороже). Чтобы тесты не стали втрое длиннее, сделано: повторная сборка с тем же железом "
    "берёт решения о скруглении из кэша (1.2 с вместо 11), кэш solid_distance (inter_vol и run_checks спрашивали расстояние одной пары дважды: 31 -> 13 с в тестах), "
    "проверка 10 запоминает пробы горловины (9.4 -> 3.3 с вместе с кэшем расстояний), rounding.bbox_of считает быстрый габарит. Последние две правки вне ревизии 8 и не меняют результатов ни одной проверки.",
    "Ревизия 8, render_vtk.py (единственный файл вне плана, который тронут): cadquery теперь импортируется до vtk. Измерено: если vtk импортирован первым, булевы операции OCC идут "
    "примерно в 10 раз медленнее (build_frame со скруглением 11 с -> 150 с; render_vtk.py 178 с вместо 22 с). Раньше это скрывалось тем, что сборка была почти без булевых операций (1.5 с). "
    "shell_concepts.py (а через него organic_frame.py) тоже импортируют vtk первым: по заданию не тронуты, их вызов build_frame() будет медленным, пока там не поменять порядок импортов.",
    "Ревизия 8, test_checks.py: 61 -> 69 случаев, старые 61 без изменений (во всех вызовы build_frame получили hardware=hardware, чтобы повторная сборка брала кэш). Добавлены: "
    "антлер, шея и ребро A, построенные без скругления, дают CHECK12 'no corner of this plate was rounded' (3 случая); каждая плита имеет меньше острых углов, чем эталон, и нет ни одного CHECK12; "
    "оставшиеся острые углы все объяснены; искатель острых рёбер видит 4 ребра куба и 0 после скругления; все контакты сохранили площадь; антлер с вырезанным на 6 мм углом контактной грани даёт CONTACT.",
    # --- ревизия 8a
    "Ревизия 8a, правило контакта: по плану скругление может отнять площадь у контакта из отчёта, если контакт сохраняет не меньше 97 % площади без скругления и не меньше 4 мм "
    "плоского контакта вокруг каждого винта. Реализация в rounding.Guard (выпуклый угол): осколок, снимаемый скруглением, считается по площади граней, лежащих на контакте с соседом. "
    "Деталь может отдать каждому соседу не больше 3 % неснятой площади контакта (у детали, скруглённой с обеих сторон контакта, по 1.5 % каждой; у железа и нескруглённых деталей все 3 %), "
    "сумма по всем углам детали ведётся в RoundCtx.ledger. Углы одного контура делят допуск: перед первым выпуклым углом для каждого считается, сколько он снимет при радиусе 2 мм, и пока "
    "судится один угол, остальные держат это в запасе (иначе первый угол брал весь допуск радиусом 6 мм, а остальные оставались острыми: так было в первой версии, 70 острых вместо 56). "
    "Скругление по-прежнему не входит в стенки отверстий, не подходит к шлангам и железу ближе, чем раньше, и не рвёт деталь. Проверка на готовых телах: check_contact_areas "
    "(строки CONTACT в отчёте, не пронумерованная проверка): доля площади >= 97 %, и площадь контакта в круге радиуса (радиус пилота + 4 мм) вокруг каждого винта не меньше, чем в нескруглённом каркасе.",
    "Ревизия 8a, 4 мм вокруг винта - моя трактовка: считается от края самого большого отверстия винта (пилот вставки: M4 радиус 2.8, M3 2.0; проходное отверстие M4 получает ту же досягаемость, чтобы обе "
    "половины стыка судили один винт одинаково), то есть круг радиуса 6.8 мм (M4) или 6.0 мм (M3) вокруг оси; скругление не может снять контакт внутри него. Буквальное «остаётся 4 мм» "
    "невыполнимо даже без скругления: у ушка кронштейна вентилятора 4.9 мм от оси до края, то есть 2.1 мм плоскости вокруг отверстия, поэтому правило понято как «не уменьшать то, что есть в круге». "
    "Цена: 15 углов (ушки кронштейнов вентиляторов 9, шея и плечи визора 6, у болтов соединения) остались острыми только из-за этого правила. Измерено: без него (rounding.SCREW_FLAT = 0, один прогон) "
    "осталось бы 41 острое ребро вместо 56, и 97 % выполнялись бы так же. Решение владельца: принять 4 мм или разрешить скруглять ушки (они снимают меньше 1 % контакта с вентилятором).",
    "Ревизия 8a, итог по контурам (проверка 12, 150 рёбер на нескруглённых плитах): после ревизии 8 было 102 острых, стало 56. По плитам: rib_B 12 -> 8 (у каждого), кронштейн правый 19 -> 8, левый 11 -> 6, "
    "антлеры 7 -> 2, шеи 5 -> 1, плечи визора 6 -> 4, рёбра A 6 -> 6 (ступени нахлёста). Остались: ступени вырезов нахлёста 24 (рёбра по 8 мм внутри зон нахлёста, "
    "где контур одной половины срезан контуром другой: это срез, а не угол контура, правило 3 запрещает трогать грани нахлёста; в ревизии 8 они числились как «контакт»), "
    "предел 97 % или 4 мм у винта 19 (15 из них 4 мм у винта; 4 по самой доле: опоры кронштейнов на ребре A, 0.9 мм² при остатке 0.2, и по одному углу каждого плеча визора на 360, 27 мм² = радиус 2 мм на "
    "грани толщиной 13.5 мм), стенка отверстия или головка винта 2, радиус от 2 мм не помещается 6, группа рельса правого кронштейна 1, ступени у галтели антлера 4. Без объяснения 0. "
    "Из 36 углов, оставленных в ревизии 8 только ради площади контакта, скруглены антлеры (10 из 12 углов у каждого), накладки шей, ноги кронштейнов (по 3 из 4), углы рёбер B на нахлёсте и у антлера, концы кредла.",
    "Ревизия 8a, потеряли площадь 12 контактов из 45 (до -> после): rib_B x antler 963.95 -> 942.01 мм² (97.72 %, оба), visor_arm x rad360 1326.37 -> 1299.37 (97.96 %) справа и 1581.37 -> 1554.37 (98.29 %) слева, "
    "neck x visor_arm 412.74 -> 406.47 (98.48 %, оба), rib_A x fan_bracket 258.74 -> 255.09 (98.59 %, оба), rib_A x rib_B 1377.33 -> 1368.32 (99.35 %, оба), antler x rad420 4640.05 -> 4630.65 (99.80 %, оба). "
    "Наименьшая доля 97.72 %. 24 контакта не изменились, 9 выросли (галтели внутренних углов, до +54.68 мм² у кронштейна на вентиляторе). Плоский контакт в 4 мм вокруг винта не уменьшился ни у одного винта "
    "в контактах, потерявших площадь (число винтов в отчёте).",
    "Ревизия 8a, группа рельса правого кронштейна вентилятора (рельс, корневой блок, шарнир, лапка) теперь скруглена: корневой блок и лапка 6 мм, рельс 2 мм. Рельс шириной 5.5 мм со скруглением 6 мм "
    "съедал весь торец рельса и нахлёст 1 мм с корневым блоком, и получалось два тела (измерено: два тела по 18840 и 21429 мм³); радиус рельса ограничен 2 мм (RAIL_CONVEX), деталь остаётся одним телом. "
    "Страховка в коде: если после скругления тел не одно, группа возвращается нескруглённой и это пишется в отчёт. Острых рёбер у правого кронштейна было 19 из 20, стало 8: 4 у винтов вентилятора, "
    "1 нога, 2 радиус не помещается (угол пластины с корневым блоком и шарнир), 1 ребро группы рельса.",
    "Ревизия 8a, концы кредла: скруглены (KEEP_SHARP для ребра B пуст). Поверхность кредла - место под прокладку 3 мм, не контакт из отчёта, и скругление 6 мм на её концах контакта не отнимает. "
    "Группа 'declared' в проверке 12 теперь только остаток группы рельса.",
    "Ревизия 8a, проверка 12: прежний 'контакт' разбит по причинам из ROUND_LOG (предел 97 % / 4 мм, стенка отверстия, не помещается, ядро): к каждому оставшемуся ребру подбирается запись журнала по Y, Z. "
    "Ступени внутри зоны нахлёста (ребро по 8 мм, не записанное в журнале как угол) теперь 'lap', а не 'контакт'. Сама проверка (ни один угол плиты не скруглён -> провал) не менялась.",
    "Ревизия 8a, не тронуто: коробчатые детали (балки, полозья, пластина БП, gpu_post) остаются как в ревизии 8: концы 4 мм, верх полозьев и низ пластины БП. План 8a называет только плиты. "
    "Направляющие шлангов (PA6) не скруглены, как велит план 8a. Новое: у beam_front верхние длинные рёбра теперь остаются острыми: на его верхней грани стоят порог и модуль (контакты), "
    "и по 3 мм с обеих сторон сняли бы 14 % их площади, больше предела.",
    "Ревизия 8a, скорость: frame_v0.py вместе с порогом и тремя картинками около 75 с против 62 с, test_checks.py 96 с против 81 с. Из прибавки: пробный расчёт радиуса 2 мм для каждого выпуклого угла, "
    "расчёт допуска на каждый кандидат, новая деталь и 23 теста. Сборка со скруглением 15-18 с, run_checks 18-20 с.",
    # --- ревизия 9
    "Ревизия 9, io_block_base и полноширинный порог - одна деталь: front_sill. Порог X -140..140 (280 мм <= 290, делить пополам не понадобилось), стоит на beam_front, "
    "грань - плоскость n = 59.04 (параллельна плате, 45°). Сечение (Y, Z): (0, 10) -> (0, 53.5) -> (29.1, 82.6) -> (47.4, 64.2) -> (47.4, 10), высота до Z 80.1, глубина Y 0..47.4 (балка кончается на Y 40: свес 7.4 мм). "
    "Все числа порога мои; план задаёт X, грань 45° и три размера светлой линии.",
    "Ревизия 9, плоскость грани: бокс front_io (Y 0..42, Z 10..46, 165 x 42 x 36) по плану не может быть наклонённым на 45° блоком: у такого блока габарит по Y и по Z одинаков ((L + t) cos 45°), а здесь 42 и 36. "
    "Бокс охватывающий, положение грани в нём не определено. Выбрано: грань на 5 мм (по нормали) за верхней передней кромкой кармана (карман = бокс + 0.4 мм); толщина кожи 5 мм, "
    "в ней потом режутся порты. Из-за этого передняя стенка порога 43.5 мм высотой (Z 10..53.5), грань начинается на Z 53.5, а порог целиком 70 мм высотой.",
    "Ревизия 9, карман: бокс front_io плюс 0.4 мм с боков, сзади и сверху; открыт спереди (Y 0) и снизу. Модуль входит спереди и стоит на верхней грани beam_front (Z 10 у обоих по плану): "
    "пара beam_front x front_io контакт с нулевым зазором, внесён в INTENDED_CONTACTS (в плане его нет: «сиденье io_block_base» заменено верхом балки, потому что низ бокса лежит в плоскости верха балки). "
    "Зазоры до железа, measure.py: front_sill x front_io 0.40 мм, front_sill x light_strip 0.30 мм; это зазоры кармана и канала, не контакты.",
    "Ревизия 9, крепление модуля: 2 x M3 PLACEHOLDER вдоль X в торцевые стенки кармана (X -70.4 и 95.4, Y 21, Z 28), вставки M3 глубиной 6.7 мм; положения и резьба винтов модуля неизвестны до обмера. "
    "План: «io_block_base на beam_front, блок крепится к нему 2 x M4»; здесь модуль держит порог (2 x M3, проверка 5 выводит число из тел, держатель front_sill), а порог к beam_front 4 x M4 "
    "(по 2 в каждом концевом блоке: X -105 и 118, Y 10 и 30; проходные Ø4.5 в beam_front, вставки M4 в нижней грани порога; винты ставятся снизу, головки под балкой, зазор до стола 5 мм).",
    "Ревизия 9, светлая линия: light_strip - бокс bs v -13..257 (X -135..135), u -9..5, n 39.74..53.74 (14 x 14 в сечении), положение PLACEHOLDER; n1 равен верхней точке front_io вдоль нормали, "
    "u0 подобран так, чтобы до front_io было 5.74 мм (перемычка между карманом и каналом 5.04 мм). В пороге: канал = бокс + 0.3 мм насквозь через оба торца (X -141..141), от канала к лицу щель 4 мм "
    "(LIGHT_LINE_W; по плану диффузор 1.6 мм виден линией 4 мм) на X -135..135. План щель не просил, но канал без выхода к лицу закрытая полость; посадочного места под диффузор нет. "
    "Константы сборки (лента до 12 мм, не меньше 10 мм от светодиодов до диффузора, диффузор 1.6 мм, линия 4 мм) записаны в hardware.py, геометрией не проверяются.",
    "Ревизия 9, число плана, которое не сходится: «не меньше 10 мм от светодиодов до диффузора» в канале 14 x 14. Лента с подложкой около 2.5 мм (мой допуск), диффузор 1.6 мм: если диффузор стоит в канале, "
    "до него остаётся 14 - 2.5 - 1.6 = 9.9 мм; если он в щели стенки (5 мм), воздуха больше 10 мм. Принят второй вариант. Канал выходит торцами в зазор 2 мм до рёбер (X 140..142), "
    "то есть «открыт с обоих концов» упирается в рёбра; дышит он через щель на лице.",
    "Ревизия 9, front_io и light_strip в проверках: front_io обычное железо (проверки 1, 2, 5, 8), light_strip keep-out, как io_zone (проверки 1, 2, 8; не в габарите и не в держателях). "
    "Проверка 8 раньше смотрела только детали и шланги: добавлена группа hw.FRONT_HARDWARE (|X| <= 229, Y >= 0), в отчёте 'железо спереди'. Проверка 5: front_io 2 из 2 по телам, "
    "список крепежа сверяется с ним.",
    "Ревизия 9, порог в скруглении: контур сечения скругляется через rounded_like, как плиты (карман, канал и щель режутся после; кольцо 3 мм вокруг канала защищено). Углы: гребень, передний верх, задний верх "
    "и задний низ скруглены 6 мм; передний нижний остался острым (228 мм² против 134 мм² допуска на контакт с beam_front 4469 мм²). В проверку 12 порог не входит (не в PLATE_PREFIXES: "
    "рёбра вырезов кармана и канала считались бы острыми углами контура).",
    "Ревизия 9, материалы: поле Part.material, ABS у всех деталей, PA6 у hose_guide_cpu и hose_guide_gpu (решение владельца). Плотность PA6 1.14 г/см³ (не наполненный, 1.13..1.15), ABS 1.04. "
    "Масса считается по формуле v1 с плотностью материала. PLA (оболочка, диффузор) в этом файле нет; расстояния PLA до видеокарты и БП (10 мм) и до радиаторов и вентиляторов (4 мм) здесь не проверяются.",
    "Ревизия 9, render_vtk.py: в словарь HW_RGB добавлены front_io и light_strip (иначе KeyError на новом железе); других правок нет. "
    "organic_frame.py, shell_concepts.py, strength.py, hoses.py не тронуты. strength.py читает blank, solid, name: порог попадает в его модель как ненагруженная деталь на beam_front (прогон не делался).",
    "Ревизия 9, test_checks.py: 69 -> 92 случая. Новые: предел контакта 8a (антлер: 4 x 4 мм не провал, 7 x 7 мм у винта, 20 x 10 мм = 4.3 %), скругление на плите на основании (40 x 40 берёт четыре угла по 6; "
    "10 x 10: три по 2 мм, четвёртый острый; 4 x 4: ни одного; винт в 5.5 мм от угла держит его на 3 мм), порог (одно тело, зазоры 0.40 и 0.30, контакты, 4 x M4, 2 винта модуля из тел, "
    "сдвиг на 5 мм по X, front_io выше на 5 мм, light_strip на 4 мм в стенку, front_io перед Y = 0, 300 мм, заделанный штифт, порог без отверстий, сдвиг винта модуля в таблице), материалы. "
    "Случай «6 мм угол антлера даёт CONTACT» заменён: под предел 97 % он больше не провал (0.2 %).",
    "Ревизия 10, корень антлера: контрфорс (треугольник в u, n: основание на задней грани плиты, вершина на u + 14, n -20) входит в контур языка и скругляется вместе с ним; "
    "звено языка доходит до верха планки (TONGUE_LINK_N1 = n 1.75), и внутренний угол (u 378, n -20) скруглён радиусом 5 (больше нельзя: низ радиатора на n -15). "
    "Отклонение от плана: верхняя точка контрфорса на оси планки (n -8.25), а не на её верху (n 1.75). Пока он кончался на верхней кромке, скругление его острого угла оставляло на задней грани "
    "плиты острое вогнутое ребро 57° (проверка 12: без объяснения 1 на антлер); с точкой на оси стык переходит в плиту по касательной.",
    "Ревизия 11 (скелет, проход 1), окно для кабелей: одно окно X 40..90, Z 14..46 насквозь через заднюю стенку порога (SILL_REAR_WALL 5 мм), задано смещениями от hw.FRONT_IO_W "
    "(правый конец модуля минус 5, ширина 50, низ на 4 мм выше низа модуля, верх по верху модуля), так что двигается вместе с модулем; PLACEHOLDER, как и сам модуль. Углы R 8 (внутренний угол стенки). "
    "Верх окна на 0.4 мм ниже потолка кармана (SILL_POCKET_PLAY): ступенька 0.4 мм, не осколок. Винты модуля (X -70.4 и 95.4, Y 21) и их стенки окна не касаются. "
    "Второго окна для кабеля светлой линии нет: канал light_strip открыт через оба торца порога (X -141..141), кабель выходит через торец. Кабели USB 3 и USB-C в cables.py теперь стартуют на задней грани "
    "модуля и проходят через окно; с окном, заделанным обратно, оба упираются в порог (0.00 мм), так что окно несёт нагрузку в проверке.",
    "Ревизия 11, пилоты под площадки органической оболочки: hw.ORGANIC_PADS (12 строк) - единственный источник, organic_frame.py берёт площадки оттуда. На каждой площадке пилот M3 вдоль X в деталь "
    "(rib_A_L/R, rib_B_L/R x3, neck_L/R, front_sill x2), левые детали строятся правыми и зеркалятся, пилоты считаются в их координатах (organic_pilots, mirrored). Ни одна площадка не сдвинута: стенка вокруг "
    "пилота по проверке 7 не меньше 4.3 мм (нужно 1.6). Проверка 5 считает пилоты по телам (organic 12, список крепежа сверяется). Отверстий в проверке 7 стало 157 (было 145).",
    "Ревизия 11, test_checks.py: 92 -> 108 случаев. Новые: окно (есть, стенка под ним цела, следует за модулем, без него оба USB упираются в порог, с ним проверки кабелей проходят); пилоты "
    "(счёт из тел 12, заделанный пилот правой и левой детали, сдвиг площадки в таблице); organic_frame: ось винта на пилоте, пилот сдвинут на 0.5 мм, площадка сдвинута на 0.5 мм, площадка утоплена на 1 мм, "
    "pad_fits не считает свой пилот и считает любое другое отверстие.",
    # --- проход 2: кабельные точки крепления
    "Проход 2 скелета, кабельные точки (план: docs/plans/cables-and-organic.md, «Cable fixing»): 11 штифтов M3 и 11 мостиков tie_bridge (PA6, одна форма 28 x 13 x 9 мм, лапа 3 мм, щель 12.5 x 3.5 мм) вместо "
    "13 по плану (4 + 5 + 2 + 2). Ряды первого прохода (второй заход ниже убрал четыре точки и добавил четыре): mid 3 (beam_mid), rail 4 (рельс rib_A_right), low 2 (beam_low), top 2 (beam_top). Места найдены запросами расстояний на построенных телах: 3 мм до кабелей (cables.py), "
    "2 мм до остального (проверка 3b), стенка штифта по проверке 7, скругление ребра не тронуто (прибавка объёма от скруглений rib_A_right та же, +1.75 см³).",
    "Проход 2, почему не 13: мостик длиннее шага плана. Шаг плана 25 мм (X 60, 85, 110, 135), мостик 28 мм вдоль X, так что в ряду под beam_mid вмещается три мостика с зазором 4 мм, а не четыре; "
    "и X 110 и 135 заняты линией USB 3 (X 116..128, n -41, верх кабеля на n -37, низ мостика на n -37.5): мостик там ближе к кабелю 3 мм не держит, поэтому ряд сдвинут влево, X 20, 52, 84. "
    "Под beam_low X 60 (рука арки к -X) и 90 (к +X): USB 3 лежит на X 65..72, USB-C на X 77..89, оба на 4.5..5.5 мм от ближайшего мостика. Под beam_top X 77 и 109 (EPS 2 в 11 мм при X 109).",
    "Проход 2, рельс: под рельсом (низ диагонали rib_A_right, n -34) на u 141..172 стоит средняя нога ребра (Y 184..206), а внутренний угол в 45° с ней по скруглению R 8 занимает ещё около 19 мм перед ногой, "
    "поэтому свободны u < 121 и u > 179, и точка на u 128 уменьшала радиус скругления с 8 до 3 (проверено, убрано). Нижняя грань рельса за u 250 лежит под ребром B (нахлёст). Точки рельса: u 72 и 103 "
    "(арка к -u), u 185 и 216 (арка к +u), X 149 (мостик 13 мм вмещается в рельс 16 мм и держит 2.5 мм до пластины hose_guide_gpu на X 158). Над EPS 1 (u 255) и EPS 2 (u 275) нижняя грань рельса занята ребром B, "
    "точек там нет.",
    "Проход 2, ориентация: на балках мостик лежит длинной стороной вдоль X (полка плоской нижней грани beam_low и beam_top 14 мм, под 28 мм вдоль u места нет), липучка идёт вдоль u. Кабели под балками идут "
    "вдоль u, то есть параллельно щели: стяжку приходится закручивать на четверть оборота вокруг кабеля. На рельсе мостик лежит длинной стороной вдоль u, липучка идёт поперёк рельса (вдоль X).",
    "Проход 2, проверка 3b (новая): мостик касается только своей детали (контакт лапы с гранью, это единственный намеренный: его держит винт) и ни с каким железом, и держит 2 мм (TIE_CLEAR) от всех остальных деталей и железа. "
    "Проверка 5 считает два набора из тел: пилоты M3 в деталях и проходные отверстия в мостиках (по 11). test_checks.py: список деталей из PA6 теперь шланговые направляющие и мостики.",
    "Проход 2, новые числа в cables.py: от трассы до ближайшей точки крепления и самый длинный участок без точки в 60 мм, по всей трассе и под платой. Расстояние считается до середины щели мостика. "
    "Проходов и отказов по ним нет, показаны для того, чтобы видно было, где ряды не там: линии EPS 1 и EPS 2 лежат на n -106 и -147.5, то есть на 80 и 120 мм ниже балок, и мостик высотой 9 мм до них не достаёт.",
    "Проход 2, второй заход, кабельные точки (16.11.2026, docs/plans/cables-and-organic.md, «Tie points, second pass: spec»): два числа плана стали проверкой в cables.py (TIE_REACH 30 мм до середины щели, участок без точки не длиннее 150 мм, "
    "изгиб от 30° под платой; две вилки кабеля считаются закреплёнными точками). Убраны точки, у которых нет кабеля ближе 30 мм: mid X 20 (80.6 мм до ближайшего кабеля), mid X 52 (48.5), rail u 72 (32.6), top X 77 (45.4). "
    "low_2 перенесён с X 90 (арка к +X) на X 102 (арка к -X): излом USB-C под передним краем платы был в 30.8 мм, стал 19.3. Добавлены leg_1 (Y 196, Z 36) и leg_2 (Y 194, Z 72) на внутренней грани X 142 средней ноги rib_A_right (арка вверх; мостик стоит вдоль -X), "
    "post_1 (Y 336, Z 104) на внутренней грани поста rib_B_right (арка к -Y) и skid_1 (X 102, Y 195) на верхней грани skid_front (арка к -Y). Итого 11 точек. Пилоты левых рёбер не дублируются: tie_pilots ставит их только в rib_A_right "
    "(внутри if with_rest, как пилоты рельса) и rib_B_right (side > 0); левые рёбра строятся правыми и зеркалятся, зеркалить пилоты специально не нужно (test_checks проверяет, что в левых рёбрах на зеркальных местах отверстий нет).",
    "Проход 2, второй заход, skid_1: лапа мостика стоит на верхней грани skid_front и выступает за её передний край (Y 185) на 12.5 мм, опираясь примерно на 55 % площади (мостик 28 мм, ось отверстия на 10 мм за краем, стенка штифта >= 8 мм). Это единственное место в 30 мм "
    "от излома EPS 2 у переднего правого угла БП (излом на 76°, мир (78, 149, 3)): стоя вдоль ±X на той же грани мостик в 34.7 мм от дуги, передняя грань skid_front (10 мм) мостик 13 мм не принимает, а переднюю дугу кабель на 4 мм от БП не сдвинуть "
    "(путевые точки EPS 2 сдвигались: WAY на 10-14 мм вперёд даёт 22-26 мм до мостика, но тогда кабель в 2.7-2.9 мм от БП или пересекает ATX; сетка из 9 x 8 x 4 положений WAY дала два допустимых, оба с 31.5 мм). Консоль: от винта до середины щели 13.75 мм, нагрузка кабеля мала, но печатью это не проверено.",
    "Проход 2, второй заход, путевые точки: сдвинута одна, начало дорожки EPS 1 под платой с X 113 на X 122 (cables.V_IN_OF; остальные кабели остаются на X 113). Излом EPS 1 в 36° у начала дорожки был в 32.5 мм от лучшей точки на ноге rib_A_right, "
    "стал в 28.9 мм (угол 38°). Длина трассы 649 -> 652 мм при заводской 700 (запас 51 -> 48 мм), зазор до rib_A_right 4.5 -> 4.5 мм, остальные проверки кабелей зелёные, 12V-2x6 к допуску впереди не тронут.",
    "Материал мостиков (16.11.2026, вопрос владельца): tie_bridge теперь ABS, не PA6. Кабели держит стяжка-липучка, мостик не защёлкивается и не гнётся, нейлон ему не нужен. Форма не менялась. "
    "Ручная оценка для skid_1 (лапа 13 x 3 мм висит на 12.5 мм, рывок 20 Н за стяжку): 14 МПа вдоль слоёв при прочности ABS вдоль слоёв около 35 МПа, запас 2.4; испытанием не подтверждено. PA6 остаётся только у двух направляющих шлангов.",
    # --- отсеки под диски, проход 1
    "Отсеки под диски, проход 1 (16.11.2026, docs/plans/cables-and-organic.md, «Drive bays, pass 1»): добавлена одна деталь drive_sled_left (ABS, строится правосторонней и зеркалится), железо drive_left (составное тело: 3.5 дюйма на "
    "внешней грани, 2.5 дюйма на внутренней) и зона штекеров drive_plugs_left (запретная зона), два проходных отверстия M4 в psu_bulkhead (X -89.5, Z 30 и 76), проверка 13 в frame_v0.py и новый скрипт drive_access.py. Все таблицы "
    "отверстий, стандарты, разъём и место дисков - в hardware.py (DRIVE_FORMS, DRIVE_SATA, drive_layout). Приняты по плану: плита 5 мм, бобышка 1 мм, зазор до БП 4 мм, под головкой 3.0 мм материала, фланец у перегородки с двумя M4, ступня плоской гранью на skid_rear.",
    "Отсеки, отступление 1: 2.5 дюйма центрирован по Y на 3.5 дюйма (в плане положение по Y не задано). Если выровнять их по краю разъёма, колонна 2.5 дюйма (4.07 мм от края) оказывается в 0.9 мм по Y от колонны 3.5 дюйма (3.18 мм от края), "
    "а их отверстия по Z (85.73 и 90.60 мм от разъёма) в 4.9 мм друг от друга: зенковки с противоположных граней перекрылись бы (нужно не меньше 8.6 мм между осями при зенковке Ø7.5 и стенке 1.6). При центрировании ближайшие оси в 16.8 мм. "
    "Следствие: разъёмы 2.5 и 3.5 дюйма по Y не совпадают (3.5: Y 269.4..312.2, 2.5: Y 285.3..328.0), зона штекеров - два бокса, оба сверху Z 150..175.",
    "Отсеки, отступление 2: размеры, которых план не задавал. Диск 3.5 дюйма стоит нижним концом на Z 3.0 (DRIVE_Z0, как место в обмере: 3 мм над skid_rear), разъёмный край диска и разъёмы всех дисков на Z 150, его край по Y 256..357.6, "
    "пластина Y 252..375 и Z 0..145 (на 5 мм ниже разъёмного края, чтобы пластина не лезла в зону штекеров), фланец Y 362..375 (13 мм), Z 18..88, X 82.5..96.5 (14 мм: пилот M4 Ø5.6 со стенкой 2.1 даёт 9.8 мм). Вставки M4 (глубина 9.1), а не M4S: "
    "под них хватает 13 мм фланца, остаётся 3.9 мм дна. Бобышка Ø9 (R 4.5), зенковка Ø(головка + 0.8), головка 6.7 / 5.7 мм высотой 2.5 мм - ПРЕДПОЛОЖЕНИЕ (круглая головка), нижний предел входа винта 2.5 дюйма 1.0 мм - ПРЕДПОЛОЖЕНИЕ (стандарт даёт только максимум 2.5).",
    "Отсеки, отступление 3: скругление. Плита и фланец скруглены по контуру тем же правилом (rounded_like), но салазки не внесены в PLATE_PREFIXES: проверка 12 по-прежнему считает 12 плит. Два угла остались острыми по контакту "
    "с перегородкой: задний нижний угол плиты (ступня и задняя грань - контакты) и два задних угла фланца. Причина измерена: верхнее ребро самой перегородки (R 2.75) уже отнимает 13.75 мм² (1.3 %) от контакта 1040.74 мм² с салазками, "
    "а скругление этих углов отняло бы ещё 30 + 28 мм²; вместе с перегородкой это 4.2 % при пороге 3 % (первая сборка: CONTACT psu_bulkhead x drive_sled 95.8 %). Контакт сохранён на 98.68 %.",
    "Отсеки, отступление 4: проверка drive_access.py. (а) Тело - силуэт сбоку из прямоугольников построенных тел (салазки, диски, боксы зоны штекеров), а не один описанный прямоугольник: описанный 123 x 175 мм требует 45° наклона с зоной штекеров "
    "(боксы штекеров уже салазок и стоят на дисках, прямоугольник считает пустой воздух над ними телом). (б) Место - конечная поза, отодвинутая на 3 мм назад и 3 мм вверх, тело полного размера (задняя грань и ступня касаются перегородки и "
    "скида, а препятствия выросли на 1.5 мм); сверка со сценарием главной сессии (тело 120 x 150, Y 252..372): те же 26..30°. (в) Кабели берутся по жилам из cables.py с настоящим радиусом (замер по телам занял бы 3 минуты). "
    "(г) ВАЖНО: в черновой сетке главной сессии (rear_occ.npz) слой кабелей пуст: rt.solid у маршрута None, пока не вызван rt.build(), поэтому None было у всех 12 маршрутов, а не у пяти. Свободное место справа от БП измерено без кабелей.",
    "Отсеки, результат и решение (главная сессия, 16.11.2026): левый отсек проходит (наклон 26° без зоны штекеров и 28° с ней, при пределе 30°). Правого отсека нет: ATX 24-pin, EPS 1 и EPS 2 идут справа от БП вдоль и вокруг его задней части "
    "(EPS 2: от (84, 160, 7) к (113, 332, 93) и (122, 346, 108), потом вверх по X 132) и проходят сквозь объём правого отсека (X 79..119, Y 252..375, Z 3..150); при построенном правом отсеке cables.py не проходил (ATX 24-pin, EPS 1 и EPS 2 по 0.00 мм "
    "от drive_right при минимуме 3, EPS 2 1.59 мм от салазок). Кабели не перекладывались. В hardware.py DRIVE_SIDES = {\"left\": -1}; всё строится по этому словарю, возврат ключа right строит правый отсек (и снова роняет cables.py и drive_access.py). "
    "Свободное место справа от БП в плане было измерено без кабелей (слой кабелей в черновой сетке был пуст: rt.solid у маршрута None, пока не вызван rt.build()).",
    "Ревизия 11, антлеры (проход 2): кронштейн 420 стал пластиной 3 мм между сердцевиной и вентиляторами (u 348..351), двумя зеркальными половинами, с хордой под вентиляторами у конца радиатора и прежним языком на внешней грани rib_B (два болта M4). Таблица отверстий 420 по рисунку ARCTIC P14 Pro: шаг 125.00 (было 124.5), 12 винтов, по 6 на половину. rad420 в железе стал двумя телами (сердцевина u 310..348 шириной 138, вентиляторы u 351..378 шириной 140 и длиной 420). Отклонения от спецификации, каждое измерено:",
    "(1) Вентиляторы 140 мм в n (-16..124), сердцевина 138 (-15..123): ENVELOPE_N стал 124 (грань верха 420 - верх вентиляторов), перемычка над отверстием 2.0 мм (самая узкая 2.03 мм, X 124..156 над внешним вентилятором, измерено сечением на u 349.5; проверка 14c не пускает уже 1.9 мм). Низ вентиляторов n -16: зазор до кредла rib_B (n -18) стал 2.00 мм (был 2.55). Длину вентиляторов в железе я сделал 420 (X +-210, три рамки встык), а не 458 как у сердцевины: концевые бачки торчат на 19 мм за вентиляторами. Спецификация этого не требовала; без этого концевое ребро (п. 5) некуда поставить. Бокс органического слоя для keep-out теперь RAD420_ENV_BS (с шириной вентиляторов).",
    "(2) Пластина начинается на |X| = 40, не на X 0: над отверстием среднего вентилятора перемычка 2 мм только при |X| до 16.6, до |X| 40 меньше 12 мм, а торцевая кромка короче радиусов скругления. Нижняя кромка пластины n -17 (на 1 мм ниже вентиляторов, CHORD_FAN_GAP), зазор до кредла 1 мм.",
    "(3) Хорда: X 158..228 (от внешней грани rib_B до конца пластины), n -22..-17 (5 мм), u 338..388 как язык, верх на 1 мм ниже вентиляторов (проверка 14d). Во внутренней части |X| < 158 хорды нет: пластина висит на радиаторе. Над кредлом (|X| 142..158) хорде нет места: между вентиляторами (n -16) и кредлом (n -18) 2 мм, первый проход (хорда n -17..-15) там сидел на вентиляторах. Хорда не заходит в |X| < 158, поэтому drive_access.py даёт 28 / 28 градусов (хорда на всю длину давала 30 / 30). Короткий отрезок X 122..140 перед кредлом не делался: он не связан с остальной хордой.",
    "(4) Контур и скругление: вырезы вентиляторов в контур не входят (галтели в углах лыска-круг ограничены вырезом: r 2, не 8; 0.01 мм³ в вырезе); углы языка на u 338 и 388 у хорды не скругляются (одна грань с хордой); галтель язык-хорда r 4 (больше закрыла бы подход к головке винта M4). Буттресс ревизии 10 и звено языка убраны вместе со старой пластиной 10 мм.",
    "(5) КОНЦЕВОЕ РЕБРО, которого нет в спецификации: полоса X 222..228, u 351..378, n -17..124 на задней грани пластины у конца радиатора (за концом вентиляторов, X > 210; со стороны сердцевины концевой бачок). Измерено, зачем: без него (strength.py, радиатор как жёсткое тело, среднее по пятну 9.5 мм, шаг 7 и 1.5 мм) концевая полоса пластины 3 x 20 мм несёт вес верхних винтов как консоль: 7.9 МПа при допустимых 6.7 (запас 0.8), прогиб у верхнего внешнего винта 15.8 мм, у тела радиатора 6.5 мм. С ребром (сечение уголком, момент инерции в 220 раз больше) наибольшее напряжение в пластине, хорде и языке 2.3 МПа (мелкая сетка 2.4), прогиб 2.4 и 1.1 мм. Ребро доходит до u 378 (задняя грань вентиляторов) и не выше n 124: по Z оно вровень с верхом 420 (385.0), не выше. Масса антлера 71.5 г при 20 % (первый проход 84.9 г, без ребра 56.5 г).",
    "(6) strength.py, ревизия 11 проход 2: радиатор стал телом в модели (E 10000 МПа, паяная алюминиевая сборка; чувствительность к E в отчёте), связанным с пластинами в 12 винтах по пятну Ø9.5 мм (RAD420_SCREW_PATCH_D, ДОПУЩЕНИЕ: шайба #6), вес вдоль уклона - объёмная сила на теле (центр масс), кредл как раньше. Судится случай «stiff» (среднее перемещение по пятну с весами по площади): прямая жёсткая привязка узлов давала у края пятна напряжение, растущее с измельчением сетки (7.1 -> 12.4 МПа при 2.5 -> 1.5 мм до ребра), поэтому она осталась как проверка чувствительности («stiff-rigid»: 2.8 МПа, прогиб 2.1 мм). Случай «point» (старая модель, 12 точечных нагрузок, радиатор без жёсткости) на этой геометрии даёт 42 МПа на нижней кромке пластины и прогиб 90 мм: без хорды при |X| < 158 восемь из двенадцати винтов тянут консоль без опоры. Это и есть довод в пользу тела: настоящий радиатор передаёт вес на внешние винты. Первый проход (хорда на всю длину, точки): перемычка 15.7 МПа, прогиб 12.2 мм.",
]
OPEN_ITEMS: list[str] = [
    "Отсеки под диски: глубина штекера и изгиба кабеля за диском 25 мм (DRIVE_PLUG_ZONE) - ПРЕДПОЛОЖЕНИЕ, источника нет. Головки винтов, нижний предел входа 2.5 дюйма, резиновые втулки (нет размеров), кабели SATA (данные от платы, питание от БП), "
    "задняя органическая панель - не в этом проходе. Салазки весят около 100 г при 100 % и 75 г при 4 стенках и 20 %; устойчивость на ребре 5 x 20 мм скида (диск 3.5 дюйма около 0.7 кг на плече 16 мм от плоскости пластины) и крепление двумя M4 на сдвиг "
    "не считались. Запас прохода в левом отсеке 2° (28° из 30° с зоной штекеров).",
    "ПРАВЫЙ боковой вентилятор: три винта из четырёх (A, C с внутренней грани в штифты M4S, D с внешней через лапку Ø4.5; ревизия 7a), угол B без винта: на внутренней грани "
    "он в 4.10 мм от шланга GPU (нужно 5), с внешней планка до него не достаёт. Винт лапки идёт снаружи, головка выйдет за |X| = 229 на 2-3 мм: владелец принял это как допуск 15.11.2026 "
    "(потайная головка не нужна, лапка 2.5 мм для неё тонка). Планка в 1.00 мм от бокса rad360_ports (воротники с запасом): если запас нужен больше, RAIL_INSET (1.0) можно увеличить: планка станет тоньше по X и уйдёт дальше от rad360_ports.",
    "Боковые вентиляторы: винты идут с внешней грани через вентилятор 25 мм в вставки M4S кронштейна (глубина 5.0 мм, плита 10 мм), штатные винты вентиляторов коротки: "
    "нужны M4 около 35 мм. Прочность хребта 6 мм и ног кронштейна, вибрация и вес вентилятора не считались. Кабели вентиляторов не проложены.",
    "Фронт: передних вентиляторов нет, плоскость Y = 0 теперь задают лапы рёбер A и beam_front, а не вентиляторы; ближайшее железо (угол карты) на Y 7.4, "
    "то есть передние лапы можно было бы убрать назад примерно на 7 мм, если порог Y >= 0 не нужен. Не менялось.",
    "Обслуживание (RAM, блок CPU): откидывать 360 нельзя, шарнира нет (visor_swing.py: с осью за верхней кромкой 360 упирается в 420 через 15-20°, "
    "с осью на внешнем углу нижняя губа проходит через шланги CPU уже на 15°). Порядок: отвернуть 4 болта M4 (два на сторону, соединение плеча с шеей), "
    "поднять 360 вперёд; шланги дают около 100 мм (трасса GPU сжимается примерно до 331 и 352 мм из 450). Не проверено руками на настоящих шлангах.",
    "Опрокидывающая нагрузка: вес 420 разлагается на 0.71 вдоль n (прижим к кредлу) и 0.71 вдоль уклона (в сторону -u, вниз к плате); вдоль уклона и момент (центр масс n = 54, плоскость кредла n = -18, плечо 72 мм) держат только антлеры: 6 винтов 6-32 в пластине 3 мм между сердцевиной и вентиляторами, концевое ребро и язычок на двух болтах M4 каждый. strength.py 7 2, радиатор как жёсткое тело, 20 %: язык 2.05, хорда 2.31, корень пластины над хордой 2.21, перемычка между вентиляторами 0.16 МПа при допустимых 6.7; прогиб 420 2.4 мм у верхнего внешнего винта (случай точечных нагрузок: 42 МПа, 90 мм, он не судится). Не считалось: ползучесть пластины 3 мм под постоянной нагрузкой у тёплого радиатора, проскальзывание зажима плиты (трение зажатой между сердцевиной и рамкой), пятно Ø9.5 мм взято допущением.",
    "Длинные винты через вентиляторы (ревизия 11): винты идут с внешней грани через вентилятор 27 мм и пластину 3 мм в резьбу сердцевины, то есть на 3 мм длиннее штатных (6-32 x 34.9 мм, если штатные 32). Длину штатных винтов, резьбу (по отзывам 6-32 UNC) и полезную глубину резьбы в радиаторе ARCTIC не указывает: это замеры владельца. Вентиляторы нужно перенести на ту грань, где у радиатора воронки портов (чертёж ARCTIC), владелец подтвердил, что радиатор нарезан с обеих сторон.",
    "GPU_BRACKET_TAB_N = 108 остаётся PLACEHOLDER, верх gpu_post (n = 108) не подтверждён. Положение ATX-отверстий подтверждено по скану "
    "платы; схема БП и вставки взяты из исследования (ATX12V v2.0, ruthex RX), на деталях владельца не измерены. БП: вентилятор вверх, "
    "сетевой разъём у -X, одна схема из четырёх отверстий; на самом БП не проверено.",
    "Слот PCI_E1 = слот 6 ATX (u = 124.08) и центр сокета (134, 217) сняты со скана с точностью около 3 мм. dimms, atx24, eps сняты со "
    "скана с точностью около 5 мм. io_zone: 50 мм под штекеры и изгиб кабеля - оценка. Все эти боксы и keep-out'ы - только в проверках 1-2.",
    "cpu_block взят с чертежа ARCTIC (тело Ø91, ушко с воротниками на стороне видеокарты); высота дна над платой 7.5 мм - приближённая, "
    "воротники приняты неподвижными. Поворот блока на плате принят по решению владельца, на плате не проверен. Порты MSI-радиатора "
    "приняты как у ARCTIC (подтвердил владелец), радиус шланга GPU 6.0 мм (OD 11.2 на сестринской 5090).",
    "Шланги в keep-out - жёсткие тела R 8.0 / 7.8 (шланг + 1.8 мм), не мягкий шланг; длины и радиусы изгиба считает hose_routes.py "
    "(запас 18 и 15 мм), реальные шланги нужно подогнать по месту. Направляющие держат шланг с зазором 0.3 мм в канале Ø шланг + 0.6 и губой толщиной около 2 мм, "
    "в которую он должен вдавиться; настоящую упругость шланга не знаем.",
    "Трубки, кабели, кнопки, порты, органическая оболочка, STL, ориентация печати, усадка не входят в v0.",
    "Скругление (ревизии 8 и 8a): осталось 56 острых рёбер контуров из 150 (было 102). 24 из них ступени нахлёста (вырезы, правило 3), 15 держит правило 4 мм вокруг винта (ушки кронштейнов вентиляторов, "
    "болты соединения шея-плечо; без него 41 ребро): владелец принял это 15.11.2026, ушки остаются острыми; 4 по доле 97 %; остальные стенка отверстия, не помещается 2 мм, группа рельса, ступени галтели.",
    "Скругление: концы коробчатых деталей (4 мм) остаются острыми ступеньками у торца; верх beam_front, верх полозьев и низ пластины БП остаются острыми (контакты); галтель ноги кронштейна 5.5 / 3.0 мм (ядро не берёт 8); "
    "beam_mid не скруглён у двух рёбер; направляющие шлангов (PA6) не скруглены (стенка канала); передний нижний угол порога острый (контакт с beam_front). Острые углы объяснены в списке 'Оставлено острым'. "
    "Прочность на изгиб после скруглений не считалась.",
    "ПОРОГ И МОДУЛЬ ВВОДА (ревизия 9), всё PLACEHOLDER до обмера модуля Fractal North XL: бокс front_io, два винта M3 в торцевые стенки кармана, положение канала light_strip, шаги портов (таблица в hardware.py, +-1 мм). "
    "Нужно обмерить: плату модуля (контур, толщину), крепёжные отверстия и винты, высоту разъёмов и на сколько они выступают, переключатель и выходит ли колпачок кнопки вместе с модулем, длины четырёх кабелей. "
    "Вырезов под порты в пороге нет: они режутся в коже 5 мм по грани после обмера.",
    "Светлая линия: подключение ленты (заголовок LED платы или 5 В, чтобы горела при включённом ПК) и прокладка кабелей, как и остальные кабели, не сделаны. Посадочного места под диффузор (PLA прозрачный, 1.6 мм, щель 4 мм) нет; "
    "лента клеится на ABS-порог, не на диффузор. Мощность ленты в канале 14 x 14: полный белый может дать 50 °C на поверхности, нужна лента малой мощности или снижение яркости; канал через торцы упирается в рёбра (зазор 2 мм).",
    "Порог: масса 490 г при 100 % (210 г при 4 стенках/20 %), 280 x 47 x 70 мм, длинная ABS-деталь с большой плоской гранью склонна к короблению: если печать повело, делить пополам по X = 0 (каждая половина 140 мм). "
    "Винты порога к beam_front ставятся снизу, зазор до стола 5 мм (собирать до постановки на стол). Порог выступает на 7.4 мм за заднюю грань beam_front (Y 40 -> 47.4), до платы 12.6 мм. "
    "Порог не входит в проверку 12.",
    "PA6 (только две направляющие шлангов; мостики кабелей с 16.11.2026 из ABS, оболочка крепится винтами M3): сушить и печатать из сухой коробки, CFS при 65 % влажности для нейлона не годится; плотность 1.14 г/см³ принята по справочному значению, не по катушке. "
    "PLA оболочка: держать не ближе 10 мм к видеокарте и БП и 4 мм к радиаторам и вентиляторам, нести только свой вес, крепиться к каркасу несколькими точками с зазором (разная усадка ABS и PLA): в этом файле её нет.",
]


def main():
    print("Building hardware...")
    hardware = hw.build_hardware()
    print("Building frame...")
    parts, neck_prims = build_frame(hardware=hardware)
    check_bolts(neck_prims)
    print(f"  {len(parts)} parts")
    print("Checks...")
    memo: dict = {}          # run_checks and the report's corner table share the sharp-edge lists
    res = run_checks(hardware, parts, memo)
    check_contact_areas(parts, hardware, res)
    report, _ = format_report(hardware, parts, res, memo)
    with open(os.path.join(HERE, "report_frame_v0.txt"), "w", encoding="utf-8") as f:
        f.write(report)
    print(report)

    print("STEP...")
    assy = cq.Assembly(name="B6_frame_v0")
    for p in parts:
        assy.add(cq.Workplane("XY").newObject([p.solid]), name=p.name,
                 color=cq.Color(*FRAME_RGB, 1.0))
    for k, s in hardware.items():
        assy.add(cq.Workplane("XY").newObject([s]), name=k,
                 color=cq.Color(*to_rgb(hw.HW_COLORS[k]), 0.5))
    assy.save(os.path.join(HERE, "b6_frame_v0.step"))

    print("Previews...")
    render(hardware, parts, True, os.path.join(PREVIEWS, "b6_frame_v0.png"),
           "B6 «Шатёр»  ·  каркас v0 с железом")
    render(hardware, parts, False, os.path.join(PREVIEWS, "b6_frame_v0_bare.png"),
           "B6 «Шатёр»  ·  каркас v0 без железа")
    render(hardware, parts, True, os.path.join(PREVIEWS, "b6_frame_v0_exploded.png"),
           "B6 «Шатёр»  ·  каркас v0, взорванный вид", offsets=explode_offsets(parts))

    assert not res["failures"], "CHECKS FAILED:\n  " + "\n  ".join(res["failures"])
    print("Done, all asserts passed.")


if __name__ == "__main__":
    main()
