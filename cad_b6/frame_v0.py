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
Revision 12 puts every screw between printed parts on M3: an M3 socket head cap screw of the owner's kits into an M3 heat-set insert, a washer under the head
(hardware.py has the stock, the pilot and the clearances; screw_fit picks the length; checks 15 and 16 measure it). The PSU's and the 360's own 6-32 screws stay,
their heads in counterbores.
Revision 14a makes three supports parts of their own, so that a misplaced one costs a small reprint: gpu_rest (the card's right-hand rest, screwed to rib_A_right), front_io_carrier (holds the front I/O module,
screwed into front_sill, whose pocket follows the carrier's outside) and hose_guide_cpu (a comb on the left side fan's corner D, screwed through the fan).

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
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

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
# The organic layer (organic_frame.py; PETG, ABS as the fallback) and the light diffuser (translucent PLA) are not in this file.
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
_A_LAYER: dict = {}                                         # right (True) / left (False) -> rib_A's outline prism, for rib_B's lap cut
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
           tuple(round(x, 2) for r in rings for x in bbox_of(r)), tuple(round(x, 2) for c in post_cuts for x in bbox_of(c)),
           tuple(tuple(round(float(x), 2) for x in pt) for pt, _why in keep))      # the corners kept sharp are part of the result (found by the review of the 14a fixes: without them a later
    # call with another `keep` got the first call's solid and log)
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
SLED_CB_PLAY = 0.8       # a counterbore's diameter = the screw's head + this (the drive sleds', the PSU bulkhead's and the visor arms')
# clearance hole kinds: (diameter, minimum wall around it). "M3c" is an M3 screw's, "6-32c" the clearance of the 6-32 hardware screws (PSU, radiators, 3.5 inch drive), "M3r" the relief bore
# under an insert's pilot (the insert is open at the bottom, so the screw may run on into it), "6-32cb" a counterbore for a 6-32 screw's head (a pan head plus SLED_CB_PLAY).
CLEAR_KINDS = {
    "M3c": (hw.M3_CLEAR_D, hw.M3_MIN_WALL),
    "6-32c": (hw.UNC6_CLEAR_D, hw.M3_MIN_WALL),
    "M3r": (hw.M3_CLEAR_D, hw.M3_MIN_WALL),
    "6-32cb": (hw.UNC6_HEAD_D + SLED_CB_PLAY, hw.M3_MIN_WALL),
}


def _unit(d):
    L = math.sqrt(sum(c * c for c in d))
    return tuple(c / L for c in d)


@dataclass
class Hole:
    """A cylindrical cutter: starts at `start`, runs along unit vector `d` for `length`."""
    kind: str                # "M3" (insert pilot) or "M3c", "6-32c", "M3r", "6-32cb" (clearance, relief, counterbore)
    start: tuple
    d: tuple
    r: float
    length: float
    wall: float              # minimum wall the insert / screw needs around the hole
    pilot: bool
    solid: object = None
    _spans: tuple = None     # (blank, the numbers they were measured with, spans) cache of material_spans
    stack: float = None      # a pilot only: the thickness the screw clamps, from its head's seat to the pilot's mouth; None where nothing is known (the I/O module's screws)
    washer: bool = True      # a washer lies under the head (it bears on plastic; the board's screws bear on the PCB)
    item: str = ""           # what the screw is, for the bill of fasteners

    def __post_init__(self):
        if self.solid is None:
            self.solid = cyl(self.start, self.d, 2 * self.r, self.length)

    def point(self, t):
        return tuple(s0 + t * c for s0, c in zip(self.start, self.d))

    def screw_r(self):
        """Radius the 4 mm of flat contact around a screw (revision 8a) is measured from: the insert's pilot, which is what the screw's
        other half has, so both parts of a joint judge the same screw with the same reach."""
        twin = {"M3c": hw.M3_PILOT_D / 2}
        return max(self.r, twin.get(self.kind, 0.0))

    def mirrored(self):
        return Hole(self.kind, (-self.start[0], self.start[1], self.start[2]),
                    (-self.d[0], self.d[1], self.d[2]), self.r, self.length, self.wall, self.pilot,
                    stack=self.stack, washer=self.washer, item=self.item)

    def moved(self, dx, dy, dz):
        return Hole(self.kind, (self.start[0] + dx, self.start[1] + dy, self.start[2] + dz),
                    self.d, self.r, self.length, self.wall, self.pilot,
                    stack=self.stack, washer=self.washer, item=self.item)

    def describe(self):
        p = self.point(OVERSHOOT)
        return (f"{self.kind} {'pilot' if self.pilot else 'clearance'} at ({p[0]:.1f}, {p[1]:.1f}, {p[2]:.1f}) "
                f"along ({self.d[0]:.2f}, {self.d[1]:.2f}, {self.d[2]:.2f})")


def pilot(org, d, kind="M3", stack=None, washer=True, item=""):
    """Insert pilot starting at the part face point `org`, going into the material along d. stack: what the screw clamps (see screw_fit); None for a screw nothing is known of."""
    dia, depth, wall = hw.INSERTS[kind]
    d = _unit(d)
    start = tuple(o - OVERSHOOT * c for o, c in zip(org, d))
    return Hole(kind, start, d, dia / 2.0, depth + OVERSHOOT, wall, True, stack=stack, washer=washer, item=item)


def clear_hole(kind, start, d, length):
    dia, wall = CLEAR_KINDS[kind]
    return Hole(kind, tuple(start), _unit(d), dia / 2.0, length, wall, False)


HW_SCREW_FLOOR = 2.0     # material left under the head of a hardware 6-32 screw (the PSU's, the 360's), between its counterbore's floor and the part it screws into


def stepped_bore(face_pt, d, thickness):
    """[counterbore, bore] for a hardware 6-32 screw that comes in at the point `face_pt` on a face and goes `thickness` deep along d (into the part): a counterbore for the head
    that leaves HW_SCREW_FLOOR under it, and the 6-32 clearance bore through that floor. The two do not overlap, so each keeps its own wall (check 7)."""
    d = _unit(d)
    depth = thickness - HW_SCREW_FLOOR
    cb_dia, cb_wall = CLEAR_KINDS["6-32cb"]
    bore_dia, bore_wall = CLEAR_KINDS["6-32c"]
    cb = Hole("6-32cb", tuple(c - OVERSHOOT * k for c, k in zip(face_pt, d)), d, cb_dia / 2.0, depth + OVERSHOOT, cb_wall, False)
    bore = Hole("6-32c", tuple(c + depth * k for c, k in zip(face_pt, d)), d, bore_dia / 2.0, HW_SCREW_FLOOR + OVERSHOOT, bore_wall, False)
    return [cb, bore]


# A counterbore for an M3 screw's head and its washer between printed parts (revision 14a review): one rule for every such counterbore, the carrier's and the card rest's. It is a Hole of kind
# "M3cb", recorded with the part's holes and cut with them (not an anonymous cut), so check 7 sees its wall and check 16 measures its depth and the material left under it on the solid.
M3_CB_SINK = 0.2                                              # the head stands at least this far under the face the counterbore is sunk in
M3_CB_DEPTH = hw.M3_HEAD_H + hw.M3_WASHER_T + M3_CB_SINK      # 3.7: the least depth of an M3 counterbore, from the face to the floor the washer lies on
M3_CB_D = hw.M3_WASHER_D + 0.8                                # its diameter: the washer on its floor, 0.4 of play round it
CLEAR_KINDS["M3cb"] = (M3_CB_D, hw.M3_MIN_WALL)


def m3_counterbore(face_pt, d, depth, item):
    """The counterbore for an M3 head and its washer that enters at `face_pt` on a face and goes `depth` along d: a Hole of kind "M3cb". The screw's clearance bore starts at its floor
    (clear_hole from the floor point, not overlapping it), as the 6-32 stepped bores do, so each keeps its own wall and check 15 measures the stack from the floor."""
    d = _unit(d)
    dia, wall = CLEAR_KINDS["M3cb"]
    return Hole("M3cb", tuple(c - OVERSHOOT * k for c, k in zip(face_pt, d)), d, dia / 2.0, depth + OVERSHOOT, wall, False, item=item)


FIT_EPS = 1e-6


def screw_fit(stack, washer=True):
    """(length, entry, relief) of the M3 screw for a joint that clamps `stack` mm (the head's seat to the pilot's mouth), from the owner's lengths. A screw goes at least
    hw.SCREW_ENGAGE_MIN into its insert and stops at least hw.SCREW_BOTTOM_GAP short of the bottom of the hole: entry = length - stack - washer, and
    SCREW_ENGAGE_MIN <= entry <= pilot depth - SCREW_BOTTOM_GAP. Among the lengths that do, the one furthest from both limits. When none does, the shortest length
    that reaches the minimum, with the relief bore (clearance diameter, under the pilot) that gives it its bottom gap; relief is 0 otherwise."""
    w = hw.M3_WASHER_T if washer else 0.0
    lo = hw.SCREW_ENGAGE_MIN
    hi = hw.M3_PILOT_DEPTH - hw.SCREW_BOTTOM_GAP
    fits = [(min(L - stack - w - lo, hi - (L - stack - w)), -L, L) for L in hw.M3_SCREW_STOCK if lo - FIT_EPS <= L - stack - w <= hi + FIT_EPS]
    if fits:
        L = max(fits)[2]
        return L, L - stack - w, 0.0
    L = min(L for L in hw.M3_SCREW_STOCK if L - stack - w >= lo - FIT_EPS)       # raises when the stack is longer than the longest screw
    entry = L - stack - w
    return L, entry, entry + hw.SCREW_BOTTOM_GAP - hw.M3_PILOT_DEPTH


def joint_pilots(org, d, stack, item, washer=True):
    """The insert pilot of a screw that clamps `stack` mm, plus the relief bore under it when no length in the kit fits (screw_fit): a list of holes."""
    h = pilot(org, d, "M3", stack, washer, item)
    relief = screw_fit(stack, washer)[2]
    if relief <= FIT_EPS:
        return [h]
    overlap = 0.2                                              # the relief starts this far inside the pilot, which is wider
    start = tuple(c + (h.length - overlap) * k for c, k in zip(h.start, h.d))
    return [h, Hole("M3r", start, h.d, hw.M3_CLEAR_D / 2, relief + overlap, hw.M3_MIN_WALL, False, item=item)]


# ---------------------------------------------------------------------------
# Rib outlines (Y, Z)
# ---------------------------------------------------------------------------
DIAG_N, DIAG_W = -20.0, 28.0            # the diagonal's axis along n and its width: n -34..-6, whose upper face is the flat seat of gpu_rest (revision 14a)
P_DIAG0 = hw.bp_yz(-10, DIAG_N)
P_DIAG1 = hw.bp_yz(280, DIAG_N)

FOOT_W = 20.0
SHAPE_A = [
    Cap((hw.ENVELOPE_Y0 + FOOT_W / 2, -5), (40, -5), FOOT_W),    # foot pad; the plan starts it at Y 8, which is 2 mm in front of the fans
    Cap((40, -5), P_DIAG0, 20),                      # web (deviation, see report)
    Cap(P_DIAG0, P_DIAG1, DIAG_W),                   # diagonal under the board
    Cap((195, 136), (195, -3), 22),                  # mid leg
    Cap((188, -5), (212, -5), 20),                   # mid leg foot
]
# Revision 14a: the card's right-hand rest is a part of its own, gpu_rest (ABS). It was a capsule 16 mm wide in rib_A_right's outline; it now stands on the diagonal's upper face (n DIAG_N + DIAG_W / 2,
# the rib keeps a flat seat) and is screwed to the rib by two M3 along n, from the diagonal's underside, through plain clearance holes in the rib into inserts in the part. Its contact face with the card is
# where it was: u = hw.GPU_BS[2], along n over the capsule's axis n REST_N_AXIS (literals, as before). The finger is REST_W wide (it was 16): the 20 N knock along X at its tip bent the 16 mm finger with a
# margin of 1.93 (revision 14a, check 19); the extra width goes to lower u, away from the card, so the contact face and the USB-C riser's distance do not change.
REST_W = 20.0           # the finger's width along u; its upper face is the card's lower face (u = GPU_BS[2])
REST_U = hw.GPU_BS[2] - REST_W / 2
REST_N_AXIS = (-10.0, 104.0)                         # the capsule's axis along n (where the finger was), the round tip stands REST_W / 2 beyond the upper end
REST_SEAT_N = DIAG_N + DIAG_W / 2                    # n of the diagonal's upper face: the foot of the part lies on it
REST_X = (X_IN, X_OUT)                               # the part is as thick as the rib, and flush with both its faces
REST_SCREW_DU = 5.0                                  # the two screws stand this far either side of the finger's middle, along u, on X = the rib's middle
REST_SCREW_DU_LIST = (-REST_SCREW_DU, REST_SCREW_DU)
REST_SCREW_V = hw.x_to_v((X_IN + X_OUT) / 2)
# The head and its washer sit in a counterbore in the diagonal's underside, REST_CB_DEPTH deep: through the whole 28 mm of the diagonal no length of the owner's kit fits the 6.7 mm pilot (M3 x 35 would
# enter 6.5, 0.3 over the limit, and the relief bore under it that screw_fit then asks for fails check 7's wall). The counterbore follows the rule of every M3 counterbore (M3_CB_DEPTH: head 3 + washer 0.5
# + 0.2, revision 14a review; it was 3.0 and left the head 0.5 mm proud), which leaves 24.3 mm of the diagonal under the washer: M3 x 30 enters the insert 5.2 mm. The heads stay under the underside, which
# has the rail's tie bridges and the cables on it.
REST_CB_DEPTH = M3_CB_DEPTH
REST_CB_D = M3_CB_D
REST_STACK = DIAG_W - REST_CB_DEPTH                  # what a rest screw clamps: from the counterbore's floor to the seat

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
LAP_STACK = X_OUT - X_MID                                        # what a lap screw clamps: rib B's outer half, into rib A's inner half

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
# Arm-to-neck joint (revision 6, no hinge): two M3 bolts along X, insert pilots in the arm, clearance holes in the neck.
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
HOLDING_RIB = {      # which rib outline(s) the bolt must lie inside
    "beam_front": ("A",), "beam_low": ("A",),
    "beam_mid": ("A",), "beam_top": ("B",), "skid_front": ("A", "B"),
    "skid_rear": ("B",), "psu_bulkhead": ("B",),
}

NECK_BOLTS = [hw.bp_yz(sum(NECK_U) / 2, n) for n in (-34.0, -52.0)]      # (Y, Z), along X through pad + neck into rib_B's post
NECK_PAD_STACK = NECK_X[1] - X_OUT                                       # the pad and the strut: 34 mm, the longest stack of the skeleton
TONGUE_BOLTS = [hw.bp_yz(350.0, n) for n in (-30.0, -46.0)]               # (Y, Z), along X through the antler tongue into rib_B's post
# Revision 13: the card's post is a frame (a plate 14.5 mm thick along v with a window), so that the card's video outputs are open (hw.GPU_OUT_ZONE_BS). Every size that depends on the
# card or on the tab's seat comes from hw.GPU_BS, hw.GPU_OUT_N and hw.GPU_BRACKET_TAB_N: the card's real size is about to be corrected from a fit gauge.
GPU_POST_CLEAR = 0.5                    # the frame keeps this far from the card's thickness in u and from gpu_out_zone in n
GPU_POST_V = (-20.0, -5.5)              # the base's thickness along v: the beam's end face to 5.5 mm short of the board's edge (as before the rebuild)
GPU_POST_V_UP = (-30.0, GPU_POST_V[1])  # the part above n GPU_POST_N_STEP: 10 mm thicker towards the flank, over rib_A's top (n -6, 1 mm clear). The 20 N pull of the plan bends the columns about u
                                        # over a 95 mm arm; at 14.5 mm thick the low column carried 6.8 MPa, at 24.5 mm 1.6 (see the report, "card post strength")
GPU_POST_N_STEP = -5.0                  # where the post gets thicker: 1 mm above the top of rib_A's diagonal (n -6)
GPU_POST_BOLT_V = -10.5                 # the two bolts' v
GPU_POST_COL_W = 12.0                   # the low-u column's width in u (the high one is as wide as the bolts need)
GPU_POST_U_WINDOW = (hw.GPU_BS[2] - GPU_POST_CLEAR, hw.GPU_BS[3] + GPU_POST_CLEAR)       # the opening: the card's whole thickness in u, and a little more
GPU_POST_BOLT_WALL = 1.9                # wall between the first bolt's pilot and the window's edge (rule 1.6)
GPU_POST_U_BOLT0 = GPU_POST_U_WINDOW[1] + hw.M3_PILOT_D / 2 + GPU_POST_BOLT_WALL      # the first bolt: its pilot keeps that wall to the window's edge
GPU_POST_U = (round(GPU_POST_U_BOLT0, 3), round(GPU_POST_U_BOLT0 + 8.0, 3))     # the two bolts into beam_mid (131 and 139 for the card as it is now)
GPU_POST_U_RANGE = (GPU_POST_U_WINDOW[0] - GPU_POST_COL_W, round(GPU_POST_U[1] + 7.0, 3))     # the frame's outside, along u
GPU_POST_N_WINDOW = (hw.GPU_OUT_N[0] - GPU_POST_CLEAR, hw.GPU_OUT_N[1] + GPU_POST_CLEAR)      # the opening, along n: the zone's n range, and a little more each end
GPU_POST_N_RANGE = (hw.ATX_TRAY_N, hw.GPU_BRACKET_TAB_N)      # the base stands on beam_mid, the lintel's top is the seat of the card bracket's tab
GPU_POST_R = 3.0                        # radius of the frame's outside corners (edges along v)
GPU_POST_R_WINDOW = 1.0                 # and of the window's: 1 mm, because a bigger one would fill the window's corner to within 0.5 mm of gpu_out_zone's (the zone's edge is 0.5 mm from the window's)
GPU_POST_BS = (GPU_POST_V_UP[0], GPU_POST_V[1], *GPU_POST_U_RANGE, *GPU_POST_N_RANGE)      # the box round the whole frame, board space
GPU_POST_STACK = hw.ATX_TRAY_N - BEAM_N0                       # what a card post's screw clamps: beam_mid's section along n

GUIDE_PARTS = ("hose_guide_cpu", "hose_guide_gpu")
GUIDE_HOSE = {"hose_guide_cpu": "cpu_hoses", "hose_guide_gpu": "gpu_hoses"}     # the keep-out a guide is exempt from in check 2
GUIDE_LEN = 12.0          # along the hose
GUIDE_PLAY = 0.3          # channel diameter = hose diameter + 0.6: radius = the true hose radius + this (revision 6)
GUIDE_MOUTH = 0.75        # the open side is this x the hose diameter wide, so the hose snaps in
GUIDE_RIM = 2.5           # material around a channel, in n
GUIDE_WALL_MIN, GUIDE_WALL_MAX = 0.2, 0.5     # check 10: channel wall to the true hose, mm
GUIDE_T = 10.0            # plate thickness on the neck / rib face
# Revision 14a: the CPU hose guide is a comb on the left side fan's free corner D, holding both hoses where they pass the fan (they cross its open circle there, 6.4 mm from the fan's face).
# One screw, M3 from the fan's outer face through the fan into an insert in the comb, like a bracket's ear. The comb is a bar from the screw's axis along the line to the point of the nearer hose's
# route nearest to that axis (hose 1) and on to where the line meets the farther hose's route (hose 0), GUIDE_CPU_W wide along the hoses and as thick as it takes to reach past the hoses' axes by a
# channel radius, from the fan's face (X -235) to the tip. Revision 14a review: the channels are the true tubes grown by GUIDE_PLAY, swept along the hoses' own chains over the whole comb (the same
# sweep as the true tube, see guide_cpu_channels), so no part of the comb comes nearer a hose than the play wherever the route bends; the place follows the route, not a number of u. The snap mouths
# open towards +X (towards the board, away from the fan) at the channels' places.
GUIDE_CPU_FAN = "fan_side_left"
GUIDE_CPU_CORNER = "D"                         # the fan's free corner: high u, high n (the brackets use A, B, C)
GUIDE_CPU_SPAN = 90.0                          # mm: the stretch of each hose's chain swept for the channels: its vertices within this distance of the screw's axis point, and one more each way (the comb reaches 52)
GUIDE_CPU_W = GUIDE_LEN                        # the comb's width along the hoses: the shelf length of every guide
GUIDE_CPU_REACH = 45.0                         # the farther channel's centre may be at most this far from the screw's axis (else the guide is not stretched: report)
GUIDE_SHADOW_MAX = 400.0                       # mm2: what the guide's projection along X may cover inside the fan's open circle outside the two hoses' own projection (3 % of the circle)
GUIDE_GPU_U = (166.0, 166.0 + GUIDE_LEN)       # on the up-slope run behind the board, where both hoses are straight
GUIDE_GPU_BOLT_N = -20.0                       # on rib_A's diagonal, whose axis is n = -20
GUIDE_GPU_PLATE_N1 = -6.0

# Side fans (revision 7, rebuilt in revision 13). Each 140 mm fan is screwed to a printed bracket by its corner holes (M3 inserts in the bracket, screws
# from the fan's outer face) and the bracket is bolted to that side's rib_A. The bracket lies on the fan's inner face (the side towards the board) as a plate,
# BRACKET_T thick. Its outline is a C: a spine along n just outside the fan's open circle on the low-u side, an ear under each of the three screws it uses (A, B, C;
# the CPU hoses pass at D on the left, and the card's hoses at D and B on the right at the old place), a bar along the low-n edge, and a root block that joins the bar to the
# leg. A leg carries it across the gap to the rib's outer face. One design for both sides: the right bracket is built where it stands and the left one is its mirror.
# No part of it enters the circle (check 11, which now reaches from the fan's outer face to the rib).
BRACKET_T = 28.0                                          # plate thickness along X. Revision 13: 28 (was 10). The knock of the plan (20 N along X at the fan's far corner) bends the spine
                                                          # and the bar about their thin axis; at 10 mm they carry about 20 MPa, at 28 mm 2.6 (see the report, "bracket strength")
BRACKET_EAR = 4.9                                         # half-side of the ear around a pilot (the M4S insert's radius and wall until revision 12; the outline stays)
_AP_R = hw.FAN_APERTURE_D / 2
BRACKET_SPINE_U = (116.0, hw.FAN_CENTRE_UN[0] - _AP_R - 1.0)       # 116..122: 1 mm outside the circle, whose low-u point is u 123
SPINE_N0 = -34.0                                          # the spine's lower end: the leg's lower face. Below it only the A ear and the bar, because on the right the card's hoses pass 3 mm
                                                          # from a spine that reaches n -40 (measured, revision 13)
BAR_N = (hw.FAN_CENTRE_UN[1] - _AP_R - 0.5 - 7.5, hw.FAN_CENTRE_UN[1] - _AP_R - 0.5)   # -47..-39.5: 0.5 mm under the circle, 7.5 wide
BAR_U0 = 128.0                                            # the bar starts here (the root block's low-u edge)
BRACKET_LEG_N = (-34.0, -6.0)                             # the leg's footprint on the rib: n -34..-6 = the diagonal's full width
BRACKET_LEG_U0 = 116.0
BRACKET_LEG_U1 = (130.0, 150.0)                           # the leg's high-u edge at its top (n -6) and at its foot (n -34): it leans away from the fan's open circle, which at n -6 starts
                                                          # at u 132.3 (1.9 mm kept) and is far at the foot. A rectangle 24 wide would enter the circle (check 11).
BRACKET_LEG_UN = ((BRACKET_LEG_U0, BRACKET_LEG_N[0]), (BRACKET_LEG_U1[1], BRACKET_LEG_N[0]), (BRACKET_LEG_U1[0], BRACKET_LEG_N[1]), (BRACKET_LEG_U0, BRACKET_LEG_N[1]))
ROOT_U = (BAR_U0, BRACKET_LEG_U1[1])                      # the root block joins the bar to the leg: u 128..150, n from the bar's underside to 1 mm into the leg
ROOT_N = (BAR_N[0], BRACKET_LEG_N[0] + 1.0)
BRACKET_BOLT_U = 121.0                                    # two M3 along X through rib_A into the leg, stacked in n
BRACKET_BOLT_N = (-26.0, -14.0)
BRACKET_BOLTS = [hw.bp_yz(BRACKET_BOLT_U, n) for n in BRACKET_BOLT_N]      # (Y, Z), the same on both ribs
BRACKET_CORNERS = {"fan_bracket_left": ("A", "B", "C"), "fan_bracket_right": ("A", "B", "C")}      # the corners each bracket screws to from the fan's inner face (one design)
BRACKET_FAN = {"fan_bracket_left": "fan_side_left", "fan_bracket_right": "fan_side_right"}
APERTURE_FROM_OUT = 20.0                                  # check 11's probe cylinder starts this far outside the fan's outer face
FAN_STACK = hw.FAN_SIDE_X["fan_side_right"][1] - hw.FAN_SIDE_X["fan_side_right"][0]       # what a side fan's screw clamps: the fan's thickness (the right one's; both are the same)
BOARD_STACK = hw.BOARD_BS[5] - hw.BOARD_BS[4]                   # what a board screw clamps: the board's thickness (no washer, the head bears on the PCB)
FAN_MIN_SCREWS = 3                                        # revision 7: at least three of the four corner holes
FASTENERS: list[dict] = []
BOLT_CHECKS: list[tuple] = []     # (label, ok, detail)


def fastener(item, part, kind, count, note=""):
    FASTENERS.append(dict(item=item, part=part, kind=kind, count=count, note=note))


def m3(stack, washer=True):
    """The kind column of the fastener list for an M3 screw that clamps `stack` mm: its length from the owner's kit (screw_fit) and the insert it goes into."""
    return f"M3 x {screw_fit(stack, washer)[0]} insert"


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


def lap_cut_boxes(half: str, right: bool = True):
    """Boxes removed from A (outer half) or B (inner half, only where A is) inside the lap zones. B follows the rib A it
    laps with (`right`: the right one), as rounded, so the two halves still fit."""
    out = []
    a_slab = _A_LAYER.get(right)
    if a_slab is None:
        a_slab = outline_solid(SHAPE_A, X_IN - 1, X_MID)
    for (y0, y1, z0, z1) in LAP_ZONES:
        if half == "A":
            out.append(hw.wbox(X_MID, X_OUT + 1, y0, y1, z0, z1))
        else:
            out.append(hw.wbox(X_IN - 1, X_MID, y0, y1, z0, z1).intersect(a_slab))
    return out


def x_clear(y, z, x0=X_IN - OVERSHOOT, x1=X_OUT + OVERSHOOT, kind="M3c"):
    return clear_hole(kind, (x0, y, z), (1, 0, 0), x1 - x0)


def end_pilot_holes(name):
    """Pilots in a cross member's end faces (X = +-142), along X."""
    holes = []
    for (y, z) in END_BOLTS[name]:
        holes += joint_pilots((X_IN, y, z), (-1, 0, 0), RIB_T, f"{name} end")
        holes += joint_pilots((-X_IN, y, z), (1, 0, 0), RIB_T, f"{name} end")
    return holes


def rest_screw_points():
    """The two gpu_rest screws' axis points, world (X, Y, Z): on the diagonal's upper face (the seat, where the insert's pilot opens) and on the floor of the counterbore in its underside (where the washer bears)."""
    out = []
    for du in REST_SCREW_DU_LIST:
        out.append((hw.bp(REST_SCREW_V, REST_U + du, REST_SEAT_N), hw.bp(REST_SCREW_V, REST_U + du, REST_SEAT_N - REST_STACK)))
    return out


def rest_counterbores():
    """The counterbores (M3cb holes) in rib_A_right's underside for gpu_rest's two screws: REST_CB_DEPTH deep along n from the underside (n REST_SEAT_N - DIAG_W)."""
    return [m3_counterbore(hw.bp(REST_SCREW_V, REST_U + du, REST_SEAT_N - DIAG_W), hw.N_DIR, REST_CB_DEPTH, "gpu_rest") for du in REST_SCREW_DU_LIST]


def rib_a_holes(right: bool):
    holes = []
    for name, pts in END_BOLTS.items():
        if "A" in HOLDING_RIB[name]:
            holes += [x_clear(y, z) for (y, z) in pts]
    for (y, z) in LAP_BOLTS:      # insert pilots in the inner half, from the X = 150 face
        holes += joint_pilots((X_MID, y, z), (-1, 0, 0), LAP_STACK, "lap A<->B")
    for (y, z) in BRACKET_BOLTS:  # fan bracket bolts: clearance through the rib, the insert is in the bracket's leg
        holes.append(x_clear(y, z))
    if right:                     # right rib only: the GPU hose guide's bolt, into the outer face
        holes += joint_pilots((X_OUT, *guide_gpu_bolt()), (-1, 0, 0), GUIDE_T, "hose_guide_gpu")
        holes += tie_pilots("rib_A_right")     # the cable tie points under the rail (the diagonal's underside)
        for (_seat, floor), cb in zip(rest_screw_points(), rest_counterbores()):     # gpu_rest's two screws: the counterbore for the head and the washer, then a plain clearance hole along n
            holes += [cb, clear_hole("M3c", floor, hw.N_DIR, REST_STACK + OVERSHOOT)]   # from the counterbore's floor through the diagonal to the seat (the insert is in the part)
    holes += organic_pilots("rib_A_right" if right else "rib_A_left", mirrored=not right)     # the organic layer's pads, on the outer face
    return holes


def build_rib_a(right: bool):
    """rib_A, right or left: the same outline (revision 14a: the right one lost the finger of the card's rest, which is gpu_rest now), the right one with the GPU hose guide's
    pilot, the rail's tie pilots and gpu_rest's two clearance holes."""
    name = "rib_A_right" if right else "rib_A_left"
    holes = rib_a_holes(right)
    cuts = lap_cut_boxes("A")
    cbores = [h for h in holes if h.kind == "M3cb"]          # the rounding sees gpu_rest's counterbores as cuts, as before they were holes (no wall ring of their own)
    s = outline_solid(SHAPE_A, X_IN, X_OUT)
    s = rounded_like(s, (1, 0, 0), name, sides=(1,) if right else (-1,), own=(name,),
                     rings=hole_rings([h for h in holes if h.kind != "M3cb"]), post_cuts=cuts + [h.solid for h in cbores])
    _A_LAYER[right] = s
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
        holes += joint_pilots((X_OUT, y, z), (-1, 0, 0), TONGUE_T, "antler tongue")
    for (y, z) in NECK_BOLTS:     # neck pad, along X into the post's outer face
        holes += joint_pilots((X_OUT, y, z), (-1, 0, 0), NECK_PAD_STACK, "neck pad")
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
SILL_STACK = BEAM_FRONT_Z[1] - BEAM_FRONT_Z[0]                  # what a sill screw clamps: beam_front's height

# Front sill (revision 9): a bar across X -SILL_HALF_X..SILL_HALF_X on beam_front, its face a plane parallel to the board (45 deg), with a pocket
# for hw front_io, a channel for hw light_strip and a slit from the channel to the face. Wall thicknesses are the part's own numbers; where the
# module and the strip are is hardware.py's (placeholders until the module is measured).
SILL_HALF_X = 140.0
SILL_FACE_WALL = 5.0          # material between the module (and the channel) and the face, normal to it: the skin the port cut-outs will go through
SILL_TOP_WALL = 10.0          # behind the channel along the face, so the ridge can take a 6 mm rounding and keep SILL_RING_WALL
# Revision 14a: the module sits in a carrier (front_io_carrier), the carrier sits in the sill's pocket. The pocket follows the carrier's OUTSIDE (CARRIER_X, CARRIER_Y1, CARRIER_Z below), which is a set of
# numbers of its own, not the module's: a later change of hw.FRONT_IO_W changes the carrier's inside and nothing in the sill, until the module grows past the carrier's walls (check 20).
SILL_POCKET_PLAY = 0.3        # the pocket is the carrier's outside plus this on the ends, the rear and the top (it is open at the front and at the bottom)
SILL_Y_REAR = 47.4            # the sill's rear plane: where it always was (the module's rear 42 + 0.4 + a wall of 5); the pocket's rear moved forward of it, so the rear wall is thinner now
SILL_CHANNEL_PLAY = 0.3       # the channel is the strip's box plus this on every side, and runs through both ends of the sill
SILL_RING_WALL = 3.0          # a rounding keeps this much material round the channel
SILL_BOLTS = [(-105.0, 10.0), (-105.0, 30.0), (118.0, 10.0), (118.0, 30.0)]      # (X, Y): M3 from below, clearance through beam_front, pilot in the sill
CARRIER_PROBE_DEPTH = 3.0     # check 5: the axis point of a module screw lies this far into the carrier's end wall
# The carrier (front_io_carrier, ABS): an inverted U round the module, two end blocks and a top plate, no back wall (the module's cables leave through the sill's window), open at the front and at the bottom.
# Its inside follows hw.FRONT_IO_W (plus CARRIER_PLAY on the ends and CARRIER_TOP_PLAY on top); its outside is fixed:
CARRIER_X = (-82.0, 107.0)     # ends: the module's X -70 / 95 plus 0.4 of play plus an end block of 11.6 each
CARRIER_Y1 = 44.2             # rear plane: 0.3 short of the pocket's rear, 2.5 behind the module's rear (the module may be that much deeper before the sill has to change)
CARRIER_Z = (BEAM_FRONT_Z[1] + SILL_POCKET_PLAY, 48.9)     # 0.3 above beam_front (the module rests on the beam, the carrier hangs from the sill); the top is 0.3 under the pocket's roof, which stops 2 mm short of the light channel (Z 49.2)
CARRIER_PLAY = 0.4            # module to the carrier's end blocks (the module's own screws cross it)
CARRIER_TOP_PLAY = 0.2        # module to the carrier's top plate
CARRIER_TOP_MIN = 2.5         # the top plate's least thickness (check 20): the plan asks for 3, the room under the light channel gives 2.7 (see the report)
CARRIER_SCREW_FLOOR = 4.0     # material under the washer of a carrier screw, from the counterbore's floor to the end block's outer face
CARRIER_CB_D = M3_CB_D                                     # the counterbore: the washer on its floor, 0.4 of play round it
CARRIER_CB_BELOW = M3_CB_DEPTH                             # the head and the washer stand this far under the end block's inner face at least (the rule of every M3 counterbore)
CARRIER_END_MIN = max(CARRIER_SCREW_FLOOR + CARRIER_CB_BELOW, hw.M3_PILOT_DEPTH + hw.M3_MIN_WALL)      # the end block's least thickness (check 20): the carrier's own screw head and the module's pilot
CARRIER_SCREWS_YZ = ((8.0, 28.0), (34.0, 28.0))           # the carrier's own screws, along X into the sill's end blocks, on each end: (Y, Z). Fixed (they are the sill's interface), 13 mm either side of the module's screw
CARRIER_STACK = CARRIER_SCREW_FLOOR + SILL_POCKET_PLAY    # what a carrier screw clamps: the floor under its washer and the pocket's play, to the pilot's mouth in the sill
# Cable window (skeleton pass 1): one opening through the rear wall for the module's front cables (USB 3, USB-C, power switch, audio). Revision 14a review: the window is the sill's own, world
# X SILL_WINDOW_X and Z SILL_WINDOW_Z, and no longer offsets from hw.FRONT_IO_W (a module grown inside its allowance moved it, and so changed the sill). It lies inside the rear face of the placeholder
# module (X -70..95, Z 10..46, where it was), so inside the rear face of every module the carrier admits, which can only be larger (3.3 mm more at each end, 0.2 up, 2.5 back): a cable that leaves the
# module's rear face in front of the window passes it. Check 20 fails a module whose rear face does not cover the window. The light line's lead needs no window of its own: the channel is open
# through both ends of the sill (see the notes).
SILL_WINDOW_X = (40.0, 90.0)  # world X: 50 wide, its right end 17 inside the carrier's right end (the end block, the carrier's play and 5 mm of the module's rear face)
SILL_WINDOW_Z = (14.0, 46.0)  # world Z: 3.7 above the carrier's underside (the rear wall keeps this strip under it) to the placeholder module's top, 3.2 under the pocket's roof
SILL_WINDOW_R = ROUND_CONCAVE  # its four corners are inside corners of the wall: the concave radius
SILL_WALL_MIN = 2.0           # check 22: the rear wall behind the pocket, from the pocket's floor to its roof and over its length (apart from the window)
SILL_WALL_STEP = (10.0, 2.0)  # check 22: the wall is measured every this many mm along X and along Z


def sill_geometry():
    """Everything about the sill that follows from the carrier's outside, the sill's own numbers and hardware.py's strip (not the module: revision 14a review): the section (Y, Z) polygon, the cutters,
    the ring."""
    z0 = BEAM_FRONT_Z[1]
    ls = hw.LIGHT_STRIP_BS
    y_rear = SILL_Y_REAR
    roof = CARRIER_Z[1] + SILL_POCKET_PLAY
    pocket_rear = CARRIER_Y1 + SILL_POCKET_PLAY
    n_pocket = hw.bs_of(0.0, hw.ENVELOPE_Y0, roof)[2]       # the pocket's top front edge, along the board's normal
    n_face = max(n_pocket, ls[5] + SILL_CHANNEL_PLAY) + SILL_FACE_WALL
    u_top = ls[3] + SILL_CHANNEL_PLAY + SILL_TOP_WALL
    u_front = n_face + (hw.ENVELOPE_Y0 - hw.ORIGIN[1]) / hw.C               # the face reaches the front plane Y = ENVELOPE_Y0 here
    n_rear = u_top - (y_rear - hw.ORIGIN[1]) / hw.C                          # the back slope (u = u_top) reaches the rear plane here
    pts = [(hw.ENVELOPE_Y0, z0), hw.bp_yz(u_front, n_face), hw.bp_yz(u_top, n_face), hw.bp_yz(u_top, n_rear), (y_rear, z0)]
    v0, v1 = hw.x_to_v(-SILL_HALF_X - 1.0), hw.x_to_v(SILL_HALF_X + 1.0)
    u_c = (ls[2] + ls[3]) / 2
    window_xz = SILL_WINDOW_X + SILL_WINDOW_Z
    window = hw.wbox(window_xz[0], window_xz[1], pocket_rear - 1.0, y_rear + 1.0, window_xz[2], window_xz[3])
    window = window.fillet(SILL_WINDOW_R, [e for e in window.Edges() if abs(e.startPoint().x - e.endPoint().x) < 1e-6 and abs(e.startPoint().z - e.endPoint().z) < 1e-6])
    cuts = dict(
        pocket=hw.wbox(CARRIER_X[0] - SILL_POCKET_PLAY, CARRIER_X[1] + SILL_POCKET_PLAY, hw.ENVELOPE_Y0 - 1.0, pocket_rear, z0 - 1.0, roof),
        channel=hw.bs_box(v0, v1, ls[2] - SILL_CHANNEL_PLAY, ls[3] + SILL_CHANNEL_PLAY, ls[4] - SILL_CHANNEL_PLAY, ls[5] + SILL_CHANNEL_PLAY),
        slit=hw.bs_box(ls[0], ls[1], u_c - hw.LIGHT_LINE_W / 2, u_c + hw.LIGHT_LINE_W / 2, ls[5] - 1.0, n_face + 1.0),
        window=window)
    ring = hw.bs_box(v0, v1, ls[2] - SILL_CHANNEL_PLAY - SILL_RING_WALL, ls[3] + SILL_CHANNEL_PLAY + SILL_RING_WALL,
                     ls[4] - SILL_CHANNEL_PLAY - SILL_RING_WALL, ls[5] + SILL_CHANNEL_PLAY + SILL_RING_WALL)
    return dict(z0=z0, pts=pts, cuts=cuts, ring=ring, n_face=n_face, u_top=u_top, y_rear=y_rear, window_xz=window_xz, roof=roof, pocket_rear=pocket_rear)


SILL_REAR_WALL = SILL_Y_REAR - (CARRIER_Y1 + SILL_POCKET_PLAY)      # the wall behind the pocket, 2.9 mm (it was 5 behind the module, and would be 2.1 behind a carrier with a back wall)
# Revision 14a review: the sill's rear bottom edge (Y SILL_Y_REAR, Z on beam_front) stays sharp over the sill's whole length. Its 6 mm rounding cut through the pocket's rear plane, 2.9 mm in front of it:
# no wall under Z 10.9, under 2 mm up to Z 12.8, the full 2.9 only above Z 16. A radius that keeps SILL_WALL_MIN would be at most 0.9 mm, under ROUND_MIN; check 22 measures the wall.
SILL_REAR_EDGE_SHARP = (f"the rear wall behind the pocket is {SILL_REAR_WALL:.1f} mm thick (the pocket keeps 2.5 mm of room behind the module): a {ROUND_CONVEX:g} mm rounding of this edge cuts through the "
                        f"pocket's rear plane and leaves no wall under Z 10.9, and a radius that keeps {SILL_WALL_MIN:g} mm (0.9 at most) is under {ROUND_MIN:g}")


def organic_pilots(name, mirrored=False):
    """M3 insert pilots for the organic layer's pads on part `name` (hw.ORGANIC_PADS), along X into the part from the pad's centre on its outer face; the screw clamps the pad (hw.ORGANIC_PAD_H).
    mirrored: the part is built right-handed and mirrored afterwards (the left ribs and neck), so the pilots go in its own coordinates."""
    k = -1.0 if mirrored else 1.0
    return [h for (part, (x, y, z), s) in hw.ORGANIC_PADS.values() if part == name
            for h in joint_pilots((k * x, y, z), (-k * s, 0.0, 0.0), hw.ORGANIC_PAD_H, "organic pad")]


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
    h = next(h for h in host.holes if h.pilot and math.dist(h.point(OVERSHOOT), pt) < 0.01 and max(abs(a + b) for a, b in zip(h.d, tp["normal"])) < 1e-6)
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
    return [h for tp in TIE_POINTS if tp["host"] == host for h in joint_pilots(tie_face_point(tp), tuple(-c for c in tp["normal"]), TIE_FOOT_T, "tie bridge")]


def carrier_screw_points():
    """The carrier's screws, one per (end, CARRIER_SCREWS_YZ): (sign of X of the end, pocket wall point where the sill's pilot opens, point on the carrier's outer face), world (X, Y, Z); the screw
    goes from the carrier's inside, outwards along (sign, 0, 0), through the end block and the pocket's play into the sill."""
    out = []
    for sgn, x_out in ((-1.0, CARRIER_X[0]), (1.0, CARRIER_X[1])):
        for (y, z) in CARRIER_SCREWS_YZ:
            out.append((sgn, (x_out + sgn * SILL_POCKET_PLAY, y, z), (x_out, y, z)))
    return out


def carrier_sill_pilots():
    """The sill's four pilots for the carrier's screws, in the pocket's end walls, along X into the end blocks."""
    return [h for sgn, wall, _face in carrier_screw_points() for h in joint_pilots(wall, (sgn, 0.0, 0.0), CARRIER_STACK, "front_io_carrier")]


def sill_holes():
    g = sill_geometry()
    holes = []
    for (x, y) in SILL_BOLTS:                                                             # from beam_front's top face up into the sill
        holes += joint_pilots((x, y, g["z0"]), (0, 0, 1), SILL_STACK, "front_sill -> beam_front")
    holes += carrier_sill_pilots()                                                        # the carrier's four screws, along X into the end blocks (revision 14a; the module's own pilots are in the carrier now)
    holes += organic_pilots("front_sill")                                                 # the organic layer's two pads, on the end faces
    return holes


def build_front_sill():
    g = sill_geometry()
    holes = sill_holes()
    cuts = list(g["cuts"].values())
    prism = Poly(g["pts"]).solid(-SILL_HALF_X, SILL_HALF_X)
    rings = hole_rings(holes)
    rings.append(g["ring"])
    s = rounded_like(prism, (1, 0, 0), "front_sill", sides=(1,), own=("front_sill",), rings=rings, post_cuts=cuts, keep=(((-SILL_HALF_X, g["y_rear"], g["z0"]), SILL_REAR_EDGE_SHARP),))
    return drill(s, holes, cuts)


def carrier_inside():
    """The carrier's inside, from the module: world (x0, x1, z1); the module's box plus CARRIER_PLAY on the ends and CARRIER_TOP_PLAY on top."""
    io = hw.FRONT_IO_W
    return io[0] - CARRIER_PLAY, io[1] + CARRIER_PLAY, io[5] + CARRIER_TOP_PLAY


def build_front_io_carrier():
    """The carrier of the front I/O module (revision 14a): an inverted U, X CARRIER_X, Y ENVELOPE_Y0..CARRIER_Y1, Z CARRIER_Z, with the module's box (plus its plays) cut out, open at the front, the rear and
    the bottom. Two insert pilots for the module's own screws (hw.FRONT_IO_SCREWS, in the end blocks from the inside) and four clearance holes for the carrier's own screws (CARRIER_SCREWS_YZ), each
    with a counterbore from the inside for the washer and the head that leaves CARRIER_SCREW_FLOOR under the washer, whatever the end block's thickness. Not rounded: it is not an outline of a plate."""
    x_in0, x_in1, z_in = carrier_inside()
    blank = hw.wbox(CARRIER_X[0], CARRIER_X[1], hw.ENVELOPE_Y0, CARRIER_Y1, CARRIER_Z[0], CARRIER_Z[1])
    blank = blank.cut(hw.wbox(x_in0, x_in1, hw.ENVELOPE_Y0 - 1.0, CARRIER_Y1 + 1.0, CARRIER_Z[0] - 1.0, z_in)).clean()
    holes = []
    for (pt, d) in hw.FRONT_IO_SCREWS:                                                    # the module's screws, along X into the end blocks (the module's own; no stack known)
        org = tuple(c + k * CARRIER_PLAY for c, k in zip(pt, d))
        holes.append(pilot(org, d, hw.FRONT_IO_SCREW_KIND, item="front_io"))
    for sgn, _wall, face in carrier_screw_points():
        x_floor = face[0] - sgn * CARRIER_SCREW_FLOOR                                     # the counterbore's floor: CARRIER_SCREW_FLOOR in from the outer face
        x_inner = x_in0 if sgn < 0 else x_in1
        holes.append(m3_counterbore((x_inner, face[1], face[2]), (sgn, 0.0, 0.0), abs(x_inner - x_floor), "front_io_carrier"))
        holes.append(clear_hole("M3c", (x_floor, face[1], face[2]), (sgn, 0.0, 0.0), CARRIER_SCREW_FLOOR + OVERSHOOT))
    return drill(blank, holes)


def build_beam_front():
    """The tie between the two front feet. Revision 9: the front sill and the module stand on its top face, so the top edges stay sharp (a
    contact face, as on the skids), and four M3 clearance holes from below carry the sill's bolts."""
    holes = end_pilot_holes("beam_front")
    z_lo, z_hi = BEAM_FRONT_Z
    holes += [clear_hole("M3c", (x, y, z_lo - OVERSHOOT), (0, 0, 1), z_hi - z_lo + 2 * OVERSHOOT) for (x, y) in SILL_BOLTS]
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
            holes += joint_pilots(hw.bp(v, u, hw.ATX_BOARD_N), [-c for c in hw.N_DIR], BOARD_STACK, "board", washer=False)
    holes += end_pilot_holes(name)
    holes += tie_pilots(name)      # the cable tie points, from the underside up into the beam
    if name == "beam_mid":     # clearance for the gpu_post bolts, along n through the beam
        for u in GPU_POST_U:
            holes.append(clear_hole("M3c", hw.bp(GPU_POST_BOLT_V, u, BEAM_N0 - OVERSHOOT), hw.N_DIR, 22.0))
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
# that two M3 screws from behind (through the bulkhead's flank) hold. The foot is the plate's bottom face, flat, on skid_rear's top face.
SLED_FLOOR = 3.0                  # material left under each screw head, between the counterbore's floor and the drive's board: the screw then enters screw_len - 3.0 (3.35 for 6-32 x 6.35, 2.0 for M3 x 5)
THREAD_CLEAR = {"6-32": "6-32c", "M3": "M3c"}      # a drive's screw thread -> the clearance kind of its bore
SLED_BOSS_R = 4.5                 # boss radius round a hole
# (SLED_CB_PLAY, the counterbore's play, is defined with the hole kinds above)
SLED_FRONT = 4.0                  # the plate starts this far in front of the outer drive's side edge
SLED_TOP_GAP = 5.0                # the plate stops this far under the drives' connector end (the plug zone is above that end)
SLED_FLANGE_Y = 13.0              # the flange's depth against the bulkhead's front face (the pilot is hw.M3_PILOT_DEPTH deep, the rest is floor)
SLED_FLANGE_Z = (18.0, 88.0)      # its height: the bulkhead's rounded top edge starts at Z 89.25
SLED_FLANGE_HALF_X = 7.0          # its half width about the plate's mid-plane (it was set by the M4 pilot's 5.6 plus 2 x 2.1 wall; the outline stays)
SLED_BOLT_Z = (30.0, 76.0)        # the two M3 screws along Y through the bulkhead's flank, stacked in Z
SLED_BOLT_X = sum(hw.drive_layout()["plate_x"]) / 2     # on the plate's mid-plane (right bay; the left is the mirror image)
SLED_ORDER = ("a sled that carries a 3.5 inch drive and an inner 2.5 inch drive takes the inner drive first: its screw heads end up under the 3.5 inch drive "
              "(the outer face's counterbores are covered by it, the heads stay below the face)")


def sled_holes():
    """(holes, counterbore cutters) of one right-hand sled. holes: the clearance bores of the drive screws (the drive's own thread: 6-32 or M3) and the two M3 pilots in the flange."""
    lay = hw.drive_layout()
    px0, px1 = lay["plate_x"]
    holes, cuts = [], []
    for face, fc in lay["faces"].items():
        F = fc["spec"]
        far = px0 if face == "outer" else px1               # the face the screw comes in from: opposite to the drive
        d = fc["dir"]                                        # towards the drive's side: from the far face through the plate and the boss
        depth_cb = hw.DRIVE_PLATE_T + hw.DRIVE_BOSS_H - SLED_FLOOR
        for (y, z) in fc["holes"]:
            holes.append(clear_hole(THREAD_CLEAR[F["thread"]], (far - d * OVERSHOOT, y, z), (d, 0, 0), hw.DRIVE_PLATE_T + hw.DRIVE_BOSS_H + 2 * OVERSHOOT))
            cuts.append(cyl((far - d * OVERSHOOT, y, z), (d, 0, 0), F["head_d"] + SLED_CB_PLAY, depth_cb + OVERSHOOT))
    for z in SLED_BOLT_Z:
        holes += joint_pilots((SLED_BOLT_X, hw.PSU_REAR_Y, z), (0, -1, 0), BULK_T, "drive sled flange")
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
    for (x, z) in hw.PSU_HOLES:          # the PSU's own 6-32 screws, from behind: its screw is hw.PSU_SCREW_LEN long and the wall BULK_T, so each head sits in a counterbore from the rear face
        holes += stepped_bore((x, BULK_Y1, z), (0, -1, 0), BULK_T)
    for sgn in hw.DRIVE_SIDES.values():          # the drive sleds' flange screws, through the flank, from behind
        for z in SLED_BOLT_Z:
            holes.append(clear_hole("M3c", (sgn * SLED_BOLT_X, hw.PSU_REAR_Y - OVERSHOOT, z), (0, 1, 0), BULK_T + 2 * OVERSHOOT))
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
# end and joins the foot on rib_B's outer face: the tongue with its two M3 bolts. The old 10 mm plate on the fans' outer face, its bar and its finger are gone.
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
        holes.append(clear_hole("6-32c", hw.bp(hw.x_to_v(x), u0 - OVERSHOOT, n), hw.U_DIR, ANTLER_T + 2 * OVERSHOOT))
    for (y, z) in TONGUE_BOLTS:             # M3 clearance through the tongue, along X
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
JOINT_STACK = NECK_X[1] - NECK_X[0]                        # what a joint screw clamps: the neck's strut


def build_neck_right(side=1):
    """Straight strut along n at |X| 180..192, u 284..307, and the spacer pad |X| 158..180 behind its lower end. The two
    joint bolts to the visor arm pass through it at n 114 and 93.5. Returns solid, holes, blank and the YZ outlines of
    strut and pad for the bolt checks."""
    name = "neck_right" if side > 0 else "neck_left"
    holes = [x_clear(y, z, NECK_X[0] - OVERSHOOT, NECK_X[1] + OVERSHOOT) for (y, z) in JOINT_BOLTS]
    for (y, z) in NECK_BOLTS:
        holes.append(x_clear(y, z, X_OUT - OVERSHOOT, X_OUT - OVERSHOOT + 35.0))
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
    holes = []
    for (y, z) in JOINT_BOLTS:     # joint bolts, from the neck's side
        holes += joint_pilots((x1, y, z), (-1, 0, 0), JOINT_STACK, "visor joint")
    v = hw.x_to_v(RAD360_X_ARM)
    for u in hw.RAD360_HOLES_U:    # the radiator's own 6-32 screws, along n through the bar at the outer column: the head sits in a counterbore from below, HW_SCREW_FLOOR under it
        holes += stepped_bore(hw.bp(v, u, hw.RAD360_INNER_N - ARM_T), hw.N_DIR, ARM_T)
    notch = bsx(ARM_NOTCH_X, x1 + 1, ARM_NOTCH_U[0], ARM_NOTCH_U[1], n0 - 1, hw.RAD360_INNER_N + 1)
    s = bsx(x0, x1, ARM_U0, hw.BOARD_BS[3], n0, hw.RAD360_INNER_N)
    s = s.fuse(bsx(x0, x1, KNEE_U[0], KNEE_U[1], KNEE_N0, n0)).clean()
    # the neck's own pad screw (the organic layer's) crosses the contact with this arm just beside the knee: the 4 mm of flat contact round it is the arm's rounding to keep too,
    # so its axis goes into the rings (the ring's cylinder itself stays in the neck's X range and touches nothing of the arm)
    neck_pads = organic_pilots("neck_right" if notched else "neck_left", mirrored=not notched)
    s = rounded_like(s, (1, 0, 0), name, sides=(1,) if notched else (-1,), own=(name,), rings=hole_rings(holes + neck_pads),
                     post_cuts=[notch] if notched else ())
    if notched:
        s = s.cut(notch)
    return drill(s, holes)


GUIDE_ON_CHAIN = ("cpu",)       # the pairs whose guides are drawn round the keep-out chain (the true tube's own axis: a polyline of every third route point) and not round the route
CHAIN_VERTEX_TOL = 0.1          # mm of u: a crossing this close to a vertex of the chain is put on it, and the axis there bisects the two chords (the tube is built round those chords)


def hose_at(pair, idx, u):
    """Hose `idx` of a pair where its route crosses board-space u: the world centre point, the unit direction there (world) and the point in board space (v, u, n). For a pair of GUIDE_ON_CHAIN
    the route is the keep-out chain, the polyline the true tube is swept along (check 10 measures a guide against that tube: where the hose bends, the chords of the chain are 0.1 mm or so off the
    route points, which is more than a snug channel can take); for the other pair it is hoses.routes()'s own points."""
    if pair in GUIDE_ON_CHAIN:
        pts = [np.array(p, float) for p in hoses.keepout_chains()[f"{pair}_hoses"][idx]]
        q = [hoses.world_to_bs(p) for p in pts]
        unit = lambda v: v / float(np.linalg.norm(v))      # noqa: E731
        for k in range(len(pts) - 1):
            u0, u1 = q[k][1], q[k + 1][1]
            if not (u1 > u0 and u0 - CHAIN_VERTEX_TOL <= u <= u1 + CHAIN_VERTEX_TOL):
                continue
            for kv in (k, k + 1):
                if 0 < kv < len(pts) - 1 and abs(u - q[kv][1]) <= CHAIN_VERTEX_TOL:
                    return pts[kv], unit(unit(pts[kv] - pts[kv - 1]) + unit(pts[kv + 1] - pts[kv])), hoses.world_to_bs(pts[kv])
            p = pts[k] + (u - u0) / (u1 - u0) * (pts[k + 1] - pts[k])
            return p, unit(pts[k + 1] - pts[k]), hoses.world_to_bs(p)
        raise ValueError(f"hose {pair}[{idx}] never reaches u = {u}")
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


def chain_nearest_yz(pts, q):
    """(point, distance) of the polyline `pts` (world points) nearest to the line along X through q = (Y, Z): the nearest point in the (Y, Z) projection."""
    best = None
    for a, b in zip(pts, pts[1:]):
        ab = b[1:] - a[1:]
        t = float(np.clip((q - a[1:]) @ ab / max(float(ab @ ab), 1e-12), 0.0, 1.0))
        p = a + t * (b - a)
        dist = float(np.linalg.norm(p[1:] - q))
        if best is None or dist < best[1]:
            best = (p, dist)
    return best


def chain_crossing_yz(pts, org, e, s_min):
    """(s, point) where the ray org + s e (in (Y, Z)) crosses the polyline `pts` (world) in the (Y, Z) projection, the first crossing with s > s_min; None when it never does."""
    best = None
    for a, b in zip(pts, pts[1:]):
        m = np.array([[e[0], -(b[1] - a[1])], [e[1], -(b[2] - a[2])]])
        if abs(np.linalg.det(m)) < 1e-12:
            continue
        sv, t = np.linalg.solve(m, a[1:] - org)
        if 0.0 <= t <= 1.0 and sv > s_min and (best is None or sv < best[0]):
            best = (float(sv), a + t * (b - a))
    return best


def guide_cpu_geometry():
    """The comb's layout, from the hoses' chains (the true tubes' axes): dict(axis=(Y, Z) of the fan's corner hole, e=unit vector in (Y, Z) from the axis along the comb, f=the unit vector across it (about
    along the hoses), s=[distance along e of hose 0's and hose 1's channel], u=[board u of those points], centres=[board-space (v, u, n) of the two channels' axes], s_end=the bar's far end), world (Y, Z).
    The comb's line runs from the screw's axis to the point of the nearer hose's chain nearest to that axis; the other channel is where the line meets the other hose's chain beyond it."""
    du, dn = hw.FAN_SIDE_HOLES_UN[GUIDE_CPU_CORNER]
    axis = np.array(hw.bp_yz(du, dn))
    chains = [[np.array(p, float) for p in line] for line in hoses.keepout_chains()["cpu_hoses"]]
    near = [chain_nearest_yz(c, axis) for c in chains]
    i_near = int(np.argmin([d for _p, d in near]))
    p_near, s_near = near[i_near]
    e = (p_near[1:] - axis) / s_near
    hit = chain_crossing_yz(chains[1 - i_near], axis, e, s_near)
    if hit is None:
        raise ValueError(f"the comb's line from corner {GUIDE_CPU_CORNER} through cpu hose {i_near} never meets cpu hose {1 - i_near}")
    s_far, p_far = hit
    pts, s = {i_near: p_near, 1 - i_near: p_far}, {i_near: float(s_near), 1 - i_near: s_far}
    u = [hw.bs_of(*map(float, pts[i]))[1] for i in (0, 1)]
    centres = [hose_at("cpu", i, u[i])[2] for i in (0, 1)]
    r_ch = hw.CPU_HOSE_R + GUIDE_PLAY
    return dict(axis=axis, e=e, f=np.array([-e[1], e[0]]), s=[s[0], s[1]], u=u, centres=centres, s_end=max(s.values()) + r_ch + GUIDE_RIM)


def guide_cpu_channels(axis_pt, grow):
    """The cutters of the CPU comb's channels: each CPU hose's chain near the comb (its vertices within GUIDE_CPU_SPAN of `axis_pt`, world, and one more each way) swept with the true hose's radius plus
    `grow`. The sweep is mitred ("right"), the true tube is round or mitred (hose_tube): a mitred sweep of radius r + g holds every point within g of either, so the comb keeps at least g from the true
    hose everywhere it is cut by this, bends included."""
    out = []
    for line in hoses.keepout_chains()["cpu_hoses"]:
        pts = [np.array(p, float) for p in line]
        near = [k for k, p in enumerate(pts) if float(np.linalg.norm(p - axis_pt)) <= GUIDE_CPU_SPAN]
        if not near:
            raise ValueError("a CPU hose's chain does not come within reach of the comb")
        k0, k1 = max(min(near) - 1, 0), min(max(near) + 1, len(pts) - 1)
        out.append(hw.hose_chain(pts[k0:k1 + 1], hw.CPU_HOSE_R + grow, transition="right"))
    return out


def guide_not_rounded(name):
    """The hose guides keep their edges: every outer edge of the foot or plate is also an edge of a shelf, and the shelf's wall around its
    channel is GUIDE_RIM thick (the mouth's lip about 2 mm). A 3 mm radius on those edges takes the wall to zero where the channel leaves the
    shelf's end faces (the arc is tangent 3 mm in, the channel radius is 6.3..6.5 of the 9 mm half-height), and at 2 mm it leaves 0.5 mm."""
    if ROUND is not None:
        ROUND_LOG.append(rd.Entry(name, (0.0, 0.0, 0.0), "layer", 0.0, 0.0,
                                  f"not rounded: the channel wall is {GUIDE_RIM:g} mm and the mouth's lip about 2 mm; a {BOX_R:g} mm radius on the shelf edges "
                                  f"takes the wall to 0 at the shelf's end faces, a 2 mm radius leaves 0.5 mm; the foot's corners are corners of the shelves"))


def build_hose_guide_cpu(shrink=0.0, width=None):
    """The CPU hose guide, a comb on the left side fan's corner D (see GUIDE_CPU_*): a bar GUIDE_CPU_W wide (`width`: the tests use another) from a round end round the screw's axis to the farther channel
    and a channel's rim beyond it, X from the fan's inner face to past the hoses' axes by a channel radius; both hoses' true tubes grown by GUIDE_PLAY (less `shrink`, which only the tests use) and swept
    along their chains are cut out over the whole comb (guide_cpu_channels), open towards +X through a mouth of 0.75 x the hose diameter at each channel; one insert pilot in the face on the fan, along +X,
    for the M3 x 30 from the fan's outer face. Returns (solid, holes, blank), (Y, Z) of the screw."""
    width = GUIDE_CPU_W if width is None else width
    g = guide_cpu_geometry()
    fan = GUIDE_CPU_FAN
    x_face, d_in = hw.FAN_SIDE_INNER_X[fan], hw.FAN_SIDE_IN[fan]
    tips = [guide_tip("cpu", (i,), g["u"][i], g["u"][i], d_in) for i in (0, 1)]
    x_tip = max(tips) if d_in > 0 else min(tips)                                                      # the tip, world X: past the farther hose's axis by a channel radius
    ax, e, f = g["axis"], g["e"], g["f"]
    h = width / 2
    corners = [ax + a * e + b * f for a, b in ((0.0, -h), (g["s_end"], -h), (g["s_end"], h), (0.0, h))]
    bar = fuse_all([Poly([tuple(map(float, c)) for c in corners]).solid(*sorted((x_face, x_tip))), Disc(tuple(map(float, ax)), width).solid(*sorted((x_face, x_tip)))])
    mouths = [guide_channel("cpu", i, g["u"][i], d_in, shrink)[1] for i in (0, 1)]                  # the snap mouths at the channels' places (guide_channel's slot; its straight channel is not used)
    s = bar.cut(*(guide_cpu_channels(np.array([x_face, ax[0], ax[1]]), GUIDE_PLAY - shrink) + mouths))
    holes = joint_pilots((x_face, float(ax[0]), float(ax[1])), (d_in, 0.0, 0.0), FAN_STACK, "hose_guide_cpu")
    guide_not_rounded("hose_guide_cpu")
    return drill(s, holes), (float(ax[0]), float(ax[1]))


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


def bracket_leg_outline():
    return Poly([hw.bp_yz(u, n) for u, n in BRACKET_LEG_UN])


def build_fan_bracket():
    """The side fan bracket, built where the RIGHT one stands (the left one is its mirror, add_mirror). A plate BRACKET_T thick on the fan's inner face: an ear under
    each of the three screws, the spine, the bar and the root block; a leg to the rib's outer face. Pilots: one under each used fan corner, and two in the leg's rib
    face for the rib bolts."""
    name = "fan_bracket_right"
    fan = BRACKET_FAN[name]
    plate, leg, rib_face, d = fan_bracket_geometry(name)
    corners = BRACKET_CORNERS[name]
    pos = {k: hw.FAN_SIDE_HOLES_UN[k] for k in corners}
    r = BRACKET_EAR
    plate_boxes = []                    # the C: ears, spine, bar, root block (one layer, one outline)
    for k, (u, n) in pos.items():
        low_n = n < hw.FAN_CENTRE_UN[1]
        n0, n1 = (BAR_N[1] - 0.5, n + r) if low_n else (n - r, n + r)
        u0 = BRACKET_SPINE_U[1] - 0.5 if u < hw.FAN_CENTRE_UN[0] else u - r
        plate_boxes.append(bsx(*plate, u0, u + r, n0, n1))
    n_top = max(pos[k][1] + r for k in pos)
    plate_boxes.append(bsx(*plate, *BRACKET_SPINE_U, SPINE_N0, n_top))
    plate_boxes.append(bsx(*plate, BAR_U0, max(pos[k][0] for k in pos) + r, *BAR_N))
    plate_boxes.append(bsx(*plate, *ROOT_U, *ROOT_N))
    leg_solid = outline_solid([bracket_leg_outline()], *leg)
    holes = []
    for k, (u, n) in pos.items():       # fan screws: from the fan's inner face into the plate, away from the fan
        y, z = hw.bp_yz(u, n)
        holes += joint_pilots((hw.FAN_SIDE_INNER_X[fan], y, z), (d, 0, 0), FAN_STACK, "side fan")
    for (y, z) in BRACKET_BOLTS:        # rib bolts: insert pilots in the leg's face on the rib
        holes += joint_pilots((rib_face, y, z), (math.copysign(1.0, rib_face), 0, 0), RIB_T, "fan bracket")   # away from the rib: +X on the right, -X on the left
    rings = hole_rings(holes)
    extra = [rd.Neighbor("aperture", aperture_cylinder(fan), "keepout")] if ROUND is not None else []   # the fan's open circle: a probe, not hardware
    kw = dict(sides=(1,), own=(name,), rings=rings, extra=extra)
    s = fuse_all([rounded_like(fuse_all(plate_boxes), (1, 0, 0), name + " plate", **kw),
                  rounded_like(leg_solid, (1, 0, 0), name + " leg", **kw)])
    x_join = plate[0] if d < 0 else plate[1]          # the plate's face towards the rib, where the leg joins it

    def pick(e):      # the leg's sides where they meet that face
        m, dd = edge_info(e)
        if abs(float(dd[0])) > 1e-6 or abs(m[0] - x_join) > 1e-3:
            return False
        u, n = un_of(m[1], m[2])
        return min(_seg_dist((u, n), a, b) for a, b in zip(BRACKET_LEG_UN, BRACKET_LEG_UN[1:] + BRACKET_LEG_UN[:1])) < 1e-2
    s = junction_fillet(s, name, "leg meets plate", pick, **kw)
    return drill(s, holes)


def build_gpu_rest():
    """The card's right-hand rest (revision 14a): the finger that was in rib_A_right's outline, as a part of its own. A capsule REST_W wide whose upper face is the card's lower face (u = hw.GPU_BS[2]), along n over
    REST_N_AXIS, X as thick as the rib, standing on the diagonal's upper face (n REST_SEAT_N: the capsule's lower end is cut off flat there, so the foot is flat on the rib). Two insert pilots in the foot, along n,
    for the screws that come from the diagonal's underside. Not rounded: the contact faces are flat, the capsule's tip is round already."""
    cap = Cap(hw.bp_yz(REST_U, REST_N_AXIS[0]), hw.bp_yz(REST_U, REST_N_AXIS[1]), REST_W)
    blank = cap.solid(*REST_X)
    below = hw.bs_box(hw.x_to_v(REST_X[0] - 1.0), hw.x_to_v(REST_X[1] + 1.0), REST_U - REST_W, REST_U + REST_W, REST_SEAT_N - REST_W - 10.0, REST_SEAT_N)
    blank = blank.cut(below).clean()
    holes = []
    for seat, _floor in rest_screw_points():
        holes += joint_pilots(seat, hw.N_DIR, REST_STACK, "gpu_rest")
    return drill(blank, holes)


def build_gpu_post():
    """The card's post as a frame: a foot on beam_mid (v GPU_POST_V thick) and, above n GPU_POST_N_STEP, a plate GPU_POST_V_UP thick along v with a window that leaves the card bracket open over the
    card's whole thickness in u and from n GPU_OUT_N[0] to the lintel's underside. Two columns outside the card's thickness, a base under the window, a lintel under the tab's seat.
    The two bolts are in the high-u column's foot, through beam_mid."""
    (u0, u1), (n0, n1) = GPU_POST_U_RANGE, GPU_POST_N_RANGE
    (wu0, wu1), (wn0, wn1) = GPU_POST_U_WINDOW, GPU_POST_N_WINDOW
    assert n1 - wn1 >= 5.0, f"the lintel between n {wn1:g} and the tab's seat {n1:g} is under 5 mm thick: the post cannot be a frame"
    s = hw.bs_box(*GPU_POST_V, u0, u1, n0, GPU_POST_N_STEP).fuse(hw.bs_box(*GPU_POST_V_UP, u0, u1, GPU_POST_N_STEP, n1))
    s = s.cut(hw.bs_box(GPU_POST_V_UP[0] - 1.0, GPU_POST_V_UP[1] + 1.0, wu0, wu1, wn0, wn1)).clean()
    holes = []
    for u in GPU_POST_U:
        holes += joint_pilots(hw.bp(GPU_POST_BOLT_V, u, hw.ATX_TRAY_N), hw.N_DIR, GPU_POST_STACK, "gpu_post")
    if ROUND is not None:
        def corner_edges(shape, us, ns):      # the edges along v (world X) that stand at a corner (u, n) of the lists
            out = []
            for e in shape.Edges():
                m, dd = edge_info(e)
                u, n = un_of(m[1], m[2])
                if abs(float(dd[0])) > 0.9999 and any(abs(u - a) < 1e-3 for a in us) and any(abs(n - b) < 1e-3 for b in ns):
                    out.append(e)
            return out
        win = corner_edges(s, (wu0, wu1), (wn0, wn1))
        assert len(win) == 4 and len(corner_edges(s, (u0, u1), (n0, n1))) == 4, "gpu_post: expected 4 window and 4 outside corner edges along v"
        s = s.fillet(GPU_POST_R_WINDOW, win)
        # the outside corners, except the foot's high-u one: the foot stands on beam_mid, and a rounding there would take contact area from it (check 12's 97 % floor)
        keep_sharp = corner_edges(s, (u1,), (n0,))
        rest = [e for e in corner_edges(s, (u0, u1), (n0, n1)) if not any(e.isSame(k) for k in keep_sharp)]
        s = s.fillet(GPU_POST_R, rest)
        assert s.isValid() and n_solids(s) == 1, "gpu_post: the corner fillet gave an invalid solid"
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

    add("rib_A_right", build_rib_a(True), "right rib, front + diagonal + mid leg; 2 x M3 clearance (in counterbores) for gpu_rest")
    add_mirror("rib_A_left", build_rib_a(False), "left rib, front + diagonal + mid leg")
    add("gpu_rest", build_gpu_rest(), f"the card's right-hand rest: a capsule {REST_W:g} mm wide on the right rib's diagonal, contact face u = {hw.GPU_BS[2]:g}, 2 x M3 along n from the diagonal's underside")
    add("rib_B_right", build_rib_b(1), "right rib, rear post: runner, post, nose, tail post")
    add_mirror("rib_B_left", build_rib_b(-1), "left rib, rear post")

    add("beam_front", build_beam_front(), "front beam, ties the front feet; carries the front sill (4 x M3 from below)")
    add("front_sill", build_front_sill(),
        "front sill X +-140: 45 deg face parallel to the board, pocket for the I/O module's carrier (the carrier's outside, not the module's PLACEHOLDER box), channel and slit for the light line, 4 x M3 into beam_front, 4 x M3 inserts for the carrier")
    add("front_io_carrier", build_front_io_carrier(),
        f"carrier of the front I/O module (PLACEHOLDER box): an inverted U, end blocks and a top plate {CARRIER_Z[1] - carrier_inside()[2]:.1f} mm, no back wall; 2 x M3 for the module (PLACEHOLDER), 4 x M3 into the sill's end blocks")
    bracket = build_fan_bracket()      # revision 13: one design, built where the right one stands, mirrored for the left
    add("fan_bracket_right", bracket,
        f"right side fan bracket: plate {BRACKET_T:g} mm on the fan's inner face (corners A, B, C, spine, bar, root block), leg to rib_A_right's outer face, 2 x M3")
    add_mirror("fan_bracket_left", bracket,
               f"left side fan bracket: the right one mirrored (corners A, B, C), leg to rib_A_left's outer face, 2 x M3")
    for name, row in BEAM_ROW.items():
        add(name, build_beam(name), f"ATX tray beam, row u = {row}, 3 standoff bosses")
    add("skid_front", build_skid("skid_front", 185, 205), "PSU skid, front")
    add("skid_rear", build_skid("skid_rear", 325, 345), "PSU skid, rear")
    add("psu_bulkhead", build_psu_bulkhead(), "PSU bulkhead with IEC window, 4 PSU screw holes (6-32, counterbored from behind), M3 clearance holes for the drive sleds' flanges (only on the side that has a bay)")
    for bay, sgn in hw.DRIVE_SIDES.items():          # hw.DRIVE_SIDES lists the bays that are built
        if sgn > 0:
            add(f"drive_sled_{bay}", build_drive_sled(sgn),
                "right drive sled: 5 mm plate beside the PSU, bosses and counterbored 6-32 / M3 holes for a 3.5 inch drive (outer face) and a 2.5 inch drive (inner face), flange with 2 x M3 inserts against the bulkhead, foot on skid_rear")
        else:
            add_mirror(f"drive_sled_{bay}", build_drive_sled(sgn),
                       "left drive sled: the right one mirrored in X; flange with 2 x M3 inserts against the bulkhead, foot on skid_rear")

    add("antler_right", build_antler_right(1), "420 bracket on the fan face + tongue on the rib's outer face, right")
    add_mirror("antler_left", build_antler_right(-1), "420 bracket on the fan face + tongue on the rib's outer face, left")

    *neck, neck_prims = build_neck_right(side=1)
    add("neck_right", tuple(neck), "neck: strut along n + spacer pad, right; 2 x M3 clearance to the visor arm")
    *neck_l, _ = build_neck_right(side=-1)
    add_mirror("neck_left", tuple(neck_l), "neck: strut along n + spacer pad, left; 2 x M3 clearance to the visor arm (revision 14a: the CPU hose guide is on the fan now)")
    add("visor_arm_right", build_arm_right(True), "360 visor arm, right (2 x M3 to the neck, knee below the bar, radiator screws counterbored), notched at the port tank")
    add_mirror("visor_arm_left", build_arm_right(False), "360 visor arm, left (2 x M3 to the neck, knee below the bar, radiator screws counterbored)")

    add("gpu_post", build_gpu_post(), "card bracket post, left side: a frame with a window for the card's video outputs, columns outside the card's thickness, a lintel under the tab's seat (tab height PLACEHOLDER)")

    g_cpu, _ = build_hose_guide_cpu()
    add("hose_guide_cpu", g_cpu, f"CPU hose guide: a comb on the left side fan's inner face at corner {GUIDE_CPU_CORNER}, two channels open to +X (towards the board), 1 x M3 through the fan", material="PA6")
    g_gpu, _ = build_hose_guide_gpu()
    add("hose_guide_gpu", g_gpu, "GPU hose guide: plate on rib_A_right's outer face, two channels open to +X, 1 x M3", material="PA6")

    for tp in TIE_POINTS:
        add(tie_name(tp), build_tie_bridge(tp),
            f"cable tie bridge {tp['row']} {tp['k']}: foot on {tp['host']}'s {tp['face']} at world ({tp['pt'][0]:.1f}, {tp['pt'][1]:.1f}, {tp['pt'][2]:.1f}), 1 x M3 into its insert, a 12.5 x 3.5 slot for a hook-and-loop strap", material="ABS")

    # --- fastener registry: what the plan lists per hardware item. The counts below are written down by
    # hand; run_checks derives the real ones from the solids (derive_mounts) and fails if they differ.
    n_atx = len(hw.ATX_HOLES)
    fastener("board", "beam_low/beam_mid/beam_top", m3(BOARD_STACK, washer=False), n_atx,
             "9 standoff bosses, 3 per beam; board underside n=-2 touches the bosses")
    fastener("rad420", "antler_left + antler_right", "6-32", 2 * len(antler_holes_xn(1)),
             f"{len(antler_holes_xn(1))} per antler along u: the fan screws, from the fans' outer face through the fan and the {ANTLER_T:g} mm plate into the core "
             f"(the four of the outer fan and the two nearer ones of the middle fan); {ANTLER_T:g} mm longer than the stock screw")
    fastener("rad360", "visor_arm_left + visor_arm_right", "6-32", 2 * len(hw.RAD360_HOLES_U),
             f"2 per arm along n at u = 192, 297: the radiator's own screws, heads in counterbores from below ({HW_SCREW_FLOOR:g} mm of arm under each; the screw's {hw.RAD360_SCREW_LEN:g} mm is an ASSUMPTION)")
    fastener("psu", "psu_bulkhead (+ skid_front, skid_rear support)", "6-32", len(hw.PSU_PATTERN),
             f"{len(hw.PSU_HOLES)} holes, standard pattern seen from behind (inlet at -X); PSU rests on the skids; heads in counterbores from behind ({HW_SCREW_FLOOR:g} mm of the {BULK_T:g} mm wall under each; the screw's {hw.PSU_SCREW_LEN:g} mm is an ASSUMPTION)")
    for fan, holder in (("fan_side_left", "fan_bracket_left"), ("fan_side_right", "fan_bracket_right")):
        fastener(fan, holder, m3(FAN_STACK), len(BRACKET_CORNERS[holder]),
                 f"corners {', '.join(BRACKET_CORNERS[holder])} of 4 (needs >= {FAN_MIN_SCREWS}): screws from the fan's outer face through the {FAN_STACK:g} mm fan into the plate")
    fastener("front_io", "front_io_carrier", hw.FRONT_IO_SCREW_KIND + " insert", len(hw.FRONT_IO_SCREWS),
             "PLACEHOLDER: 2 along X into the carrier's end blocks (revision 14a: they were in the sill's pocket); the module's screws are not known until it is measured")
    fastener("front_io_carrier", "front_io_carrier -> front_sill", m3(CARRIER_STACK), 2 * len(CARRIER_SCREWS_YZ),
             f"2 per end block along X: from the carrier's inside, head and washer in a Ø{CARRIER_CB_D:g} counterbore, {CARRIER_SCREW_FLOOR:g} mm of block under the washer and {SILL_POCKET_PLAY:g} mm of play, into an insert in the sill's end block; a screwdriver reaches them along X with the module out")
    fastener("gpu", "gpu_post (left)", m3(GPU_POST_STACK), 2,
             "2 M3 through beam_mid into the post")
    fastener("gpu_rest", "gpu_rest -> rib_A_right (right)", m3(REST_STACK), len(REST_SCREW_DU_LIST),
             f"2 along n from the diagonal's underside (heads and washers in Ø{REST_CB_D:g} counterbores {REST_CB_DEPTH:g} mm deep), through {REST_STACK:g} mm of the diagonal, into inserts in the rest's foot; plain holes, no slots (the card's weight acts along u)")
    # structural
    fastener("lap A<->B", "rib_A/rib_B x2", m3(LAP_STACK), 2 * len(LAP_BOLTS),
             "3 per side (2 top, 1 bottom); clearance in B, pilot in A")
    for name, pts in END_BOLTS.items():
        fastener(f"{name} ends", "ribs", m3(RIB_T), 2 * len(pts),
                 f"{len(pts)} per end, pilots in the member")
    fastener("antler tongue", "antler_L/R -> rib_B_L/R post", m3(TONGUE_T), 4, "2 per side along X into the post's outer face")
    fastener("neck pad", "neck_L/R -> rib_B_L/R post", m3(NECK_PAD_STACK), 4, "2 per side along X")
    fastener("visor joint", "visor_arm + neck", m3(JOINT_STACK), 4,
             "two per side, along X at u 289.2, n 114 and 93.5 (pilot in the arm, clearance in the neck); no hinge")
    fastener("fan brackets", "fan_bracket_L/R -> rib_A_L/R", m3(RIB_T), 2 * len(BRACKET_BOLTS),
             "2 per side along X at u 121, n -26 and -14: clearance through the rib, pilot in the bracket's leg; heads on the rib's inner face")
    fastener("hose_guide_cpu", "hose_guide_cpu -> fan_side_left (corner D)", m3(FAN_STACK), 1,
             f"1 along X from the left fan's outer face through the {FAN_STACK:g} mm fan into an insert in the comb (the M3 x 16 into the neck is gone)")
    fastener("hose_guide_gpu", "hose_guide_gpu -> rib_A_right", m3(GUIDE_T), 1, "1 along X into the right rib's outer face")
    fastener("gpu_post", "gpu_post -> beam_mid", m3(GPU_POST_STACK), 2, "along n")
    fastener("front_sill", "front_sill -> beam_front", m3(SILL_STACK), len(SILL_BOLTS),
             "2 per end block along Z: clearance through beam_front from below, pilot in the sill's bottom face; heads under the beam")
    fastener("tie_pilot", "/".join(dict.fromkeys(t["host"] for t in TIE_POINTS)), "M3 insert", len(TIE_POINTS),
             "the cable tie points (TIE_POINTS): one pilot each, into the part's face along the face's inward normal (along n into an underside, along X into a rib's inner face, along Z into the skid's top); rows: " + ", ".join(
                 f"{r} {sum(1 for t in TIE_POINTS if t['row'] == r)}" for r in dict.fromkeys(t["row"] for t in TIE_POINTS)))
    fastener("tie_bridge", "tie_bridge_* -> the tie points", m3(TIE_FOOT_T).replace(" insert", ""), len(TIE_POINTS),
             f"one screw through the bridge's foot ({TIE_FOOT_T:g} mm, {hw.M3_CLEAR_D:g} mm clearance hole) and a washer into the insert; the bridge is ABS, the same part at every point")
    for side_name in hw.DRIVE_SIDES:
        faces = hw.drive_layout()["faces"]
        fastener(f"drive_{side_name}", f"drive_sled_{side_name}", "6-32 x 6.35 + M3 x 5", DRIVE_SCREWS,
                 f"{len(faces['outer']['holes'])} 6-32 x 6.35 on the 3.5 inch drive (outer face), {len(faces['inner']['holes'])} M3 x 5 on the 2.5 inch drive (inner face): each from the face "
                 f"opposite the drive, head in a counterbore, {SLED_FLOOR:g} mm of material under it, so the screw enters 6.35 - {SLED_FLOOR:g} = {faces['outer']['spec']['screw_len'] - SLED_FLOOR:.2f} mm "
                 f"(standard {faces['outer']['spec']['enter'][0]:g}..{faces['outer']['spec']['enter'][1]:g}) and 5 - {SLED_FLOOR:g} = {faces['inner']['spec']['screw_len'] - SLED_FLOOR:.2f} mm (at most {faces['inner']['spec']['enter'][1]:g}); "
                 f"assembly order: {SLED_ORDER}")
    fastener("drive sled flanges", "drive_sled_* -> psu_bulkhead", m3(BULK_T), len(hw.DRIVE_SIDES) * len(SLED_BOLT_Z),
             f"{len(SLED_BOLT_Z)} per sled along Y at X {', '.join(f'{sg * SLED_BOLT_X:g}' for sg in hw.DRIVE_SIDES.values())}, Z {SLED_BOLT_Z[0]:g} and {SLED_BOLT_Z[1]:g}: clearance holes through the bulkhead's flank, pilots in the flange; screws from behind (heads on the bulkhead's rear face)")
    fastener("organic", "rib_A_L/R, rib_B_L/R, neck_L/R, front_sill", m3(hw.ORGANIC_PAD_H), len(hw.ORGANIC_PADS),
             f"the organic layer's pads (hw.ORGANIC_PADS): 6 a side, one pilot each along X into the outer face, through a {hw.ORGANIC_PAD_H:g} mm pad; the screw and the pad are in organic_frame.py")
    return parts, neck_prims


# ---------------------------------------------------------------------------
# Bolt geometry checks (positions inside outlines)
# ---------------------------------------------------------------------------
def check_bolts(neck_prims):
    BOLT_CHECKS.clear()
    shapes = {"A": SHAPE_A, "B": SHAPE_B}
    cr = hw.M3_CLEAR_D / 2
    for name, pts in END_BOLTS.items():
        for pt in pts:
            for r in HOLDING_RIB[name]:
                # beam_top's bolts must also keep the insert wall (2.1 mm) around the clearance hole
                m = cr + (hw.M3_MIN_WALL if name == "beam_top" else 0.0)
                ok = inside(shapes[r], pt, m)
                BOLT_CHECKS.append((f"{name} end bolt ({pt[0]:.1f},{pt[1]:.1f}) in rib {r}", ok, ""))
    for pt in LAP_BOLTS:
        for r in "AB":
            ok = inside(shapes[r], pt, hw.M3_PILOT_D / 2 + hw.M3_MIN_WALL if r == "A" else cr)
            BOLT_CHECKS.append((f"lap bolt ({pt[0]:.1f},{pt[1]:.1f}) in rib {r}", ok, ""))
    pr = hw.M3_PILOT_D / 2 + hw.M3_MIN_WALL
    for pt in NECK_BOLTS:
        ok = inside(neck_prims["strut"], pt, cr + hw.M3_MIN_WALL) and inside(neck_prims["pad"], pt, cr + hw.M3_MIN_WALL) \
            and inside(SHAPE_B, pt, pr)
        BOLT_CHECKS.append((f"neck bolt ({pt[0]:.1f},{pt[1]:.1f}) in neck + pad + rib_B", ok, ""))
    arm_prims = [_rect_poly(ARM_U0, hw.BOARD_BS[3], hw.RAD360_INNER_N - ARM_T, hw.RAD360_INNER_N),
                 _rect_poly(KNEE_U[0], KNEE_U[1], KNEE_N0, hw.RAD360_INNER_N - ARM_T)]
    for pt in JOINT_BOLTS:     # clearance wall in the strut, pilot wall in the arm (bar or knee), and 20 mm between the two bolts
        ok = inside(neck_prims["strut"], pt, cr + hw.M3_MIN_WALL) and inside(arm_prims, pt, hw.M3_PILOT_D / 2 + hw.M3_MIN_WALL)
        BOLT_CHECKS.append((f"joint bolt ({pt[0]:.1f},{pt[1]:.1f}) in neck strut + visor arm", ok, ""))
    gap = math.dist(JOINT_BOLTS[0], JOINT_BOLTS[1])
    BOLT_CHECKS.append((f"joint bolts {gap:.1f} mm apart (>= {JOINT_MIN_SPACING:g})", gap >= JOINT_MIN_SPACING, ""))
    leg = [bracket_leg_outline()]
    for pt in BRACKET_BOLTS:       # clearance wall in rib_A, pilot wall in the bracket's leg
        ok = inside(SHAPE_A, pt, cr + hw.M3_MIN_WALL) and inside(leg, pt, pr)
        BOLT_CHECKS.append((f"fan bracket bolt ({pt[0]:.1f},{pt[1]:.1f}) in rib_A + bracket leg", ok, ""))
    gap = math.dist(BRACKET_BOLTS[0], BRACKET_BOLTS[1])
    BOLT_CHECKS.append((f"fan bracket bolts {gap:.1f} mm apart (>= 2 x pilot + wall = {hw.M3_PILOT_D + hw.M3_MIN_WALL:.1f})",
                        gap >= hw.M3_PILOT_D + hw.M3_MIN_WALL, ""))
    for pt in TONGUE_BOLTS:
        ok = inside([TONGUE_OUTLINE], pt, cr + hw.M3_MIN_WALL) and inside(SHAPE_B, pt, pr)
        BOLT_CHECKS.append((f"tongue bolt ({pt[0]:.1f},{pt[1]:.1f}) in antler tongue + rib_B", ok, ""))
    # front sill (revision 9): the four bolts inside beam_front's top face and inside the sill's section, clear of the pocket; the module's two screws inside the wall
    g = sill_geometry()
    sill_section = [Poly(g["pts"])]
    pr3 = hw.M3_PILOT_D / 2 + hw.M3_MIN_WALL
    io = hw.FRONT_IO_W
    for (x, y) in SILL_BOLTS:
        in_beam = BEAM_FRONT_Y[0] + cr + hw.M3_MIN_WALL <= y <= BEAM_FRONT_Y[1] - cr - hw.M3_MIN_WALL and abs(x) <= X_IN - cr - hw.M3_MIN_WALL
        in_sill = inside(sill_section, (y, g["z0"] + pr3 + 0.1), pr3)        # the pilot opens in the bottom face, so only the sides count
        in_block = (-SILL_HALF_X + pr3 <= x <= CARRIER_X[0] - SILL_POCKET_PLAY - pr3) or (CARRIER_X[1] + SILL_POCKET_PLAY + pr3 <= x <= SILL_HALF_X - pr3)
        BOLT_CHECKS.append((f"sill bolt (X {x:.1f}, Y {y:.1f}) inside beam_front's top face, the sill's section and an end block", in_beam and in_sill and in_block, ""))
    # the carrier (revision 14a): the module's two screws and the carrier's own four inside the end blocks' faces (Y ENVELOPE_Y0..CARRIER_Y1, Z CARRIER_Z) with the wall their insert or counterbore needs, and the carrier's
    # own screws' pilots inside the sill's section; the module's screws and the carrier's counterbores are the carrier's inside business and clear each other by the insert's wall
    pr_io = hw.INSERTS[hw.FRONT_IO_SCREW_KIND][0] / 2 + hw.INSERTS[hw.FRONT_IO_SCREW_KIND][2]
    face = Rect(hw.ENVELOPE_Y0, CARRIER_Y1, CARRIER_Z[0], CARRIER_Z[1])
    for (pt, d) in hw.FRONT_IO_SCREWS:
        ok = inside([face], (pt[1], pt[2]), pr_io)
        BOLT_CHECKS.append((f"I/O module screw (Y {pt[1]:.1f}, Z {pt[2]:.1f}) inside the carrier's end block with the {hw.FRONT_IO_SCREW_KIND} wall (PLACEHOLDER)", ok, ""))
    for sgn, wall, _face in carrier_screw_points():
        y, z = wall[1], wall[2]
        in_carrier = inside([face], (y, z), CARRIER_CB_D / 2 + hw.M3_MIN_WALL)
        in_sill_ = inside(sill_section, (y, z), pr_io)
        clear_io = min(math.dist((y, z), (pt[1], pt[2])) for pt, _d in hw.FRONT_IO_SCREWS) >= CARRIER_CB_D / 2 + pr_io
        BOLT_CHECKS.append((f"carrier screw (X {wall[0]:.1f}, Y {y:.1f}, Z {z:.1f}) inside the carrier's end block (counterbore + wall), inside the sill's section, clear of the module's screws", in_carrier and in_sill_ and clear_io, ""))
    # beam end bolts also inside the member's own section (pilot + insert wall)
    for name, row in BEAM_ROW.items():
        lo, hi = BEAM_SPAN[name]
        for (y, z) in END_BOLTS[name]:
            # back to (u, n)
            a, b = (y - hw.ORIGIN[1]) / hw.C, (z - hw.ORIGIN[2]) / hw.C
            u, n = (a + b) / 2, (b - a) / 2
            m = hw.INSERTS["M3"]
            r = m[0] / 2 + m[2]
            ok = (row + lo + r <= u <= row + hi - r) and (BEAM_N0 + r <= n <= hw.ATX_TRAY_N - r)
            BOLT_CHECKS.append((f"{name} bolt (u={u:.1f}, n={n:.1f}) pilot inside section", ok, ""))
    # drive sleds: the flange screws' X, Z in the bulkhead's flank, clear of the PSU's screws, the window and the end blocks; the pilots inside the flange's section
    m3p = hw.INSERTS["M3"]
    flange = Rect(SLED_BOLT_X - SLED_FLANGE_HALF_X, SLED_BOLT_X + SLED_FLANGE_HALF_X, *SLED_FLANGE_Z)
    for z in SLED_BOLT_Z:
        x = SLED_BOLT_X
        wall = cr + hw.M3_MIN_WALL
        in_flank = BULK_WINDOW[1] + wall <= x <= BULK_BLOCK_X - wall and BULK_Z[0] + wall <= z <= BULK_Z[1] - wall - BULK_R
        gap_psu = min(math.dist((x, z), px) for px in hw.PSU_HOLES) - cr - CLEAR_KINDS["6-32cb"][0] / 2
        BOLT_CHECKS.append((f"drive sled bolt (X {x:.1f}, Z {z:.1f}) in the bulkhead's flank: outside the window (|X| {BULK_WINDOW[1]:g}) and the end blocks (|X| {BULK_BLOCK_X:g}) by the M3 wall, "
                            f"{gap_psu:.1f} mm of wall to the PSU's screw holes (needs {hw.M3_MIN_WALL:g})", in_flank and gap_psu >= hw.M3_MIN_WALL, ""))
        ok = flange.contains((x, z), m3p[0] / 2 + m3p[2])
        BOLT_CHECKS.append((f"drive sled bolt (X {x:.1f}, Z {z:.1f}) pilot inside the flange's section (X, Z) with the M3 wall", ok, ""))
    gap = abs(SLED_BOLT_Z[1] - SLED_BOLT_Z[0])
    BOLT_CHECKS.append((f"drive sled bolts {gap:.1f} mm apart (>= pilot + wall = {m3p[0] + m3p[2]:.1f})", gap >= m3p[0] + m3p[2], ""))
    sections = {"beam_front": Rect(0, 40, -10, 10),
                "skid_front": Rect(185, 205, -10, 0), "skid_rear": Rect(325, 345, -10, 0),
                "psu_bulkhead": Rect(BULK_Y0, BULK_Y1, BULK_Z[0], BULK_Z[1])}
    for name, sec in sections.items():
        m = hw.INSERTS["M3"]
        for pt in END_BOLTS[name]:
            ok = sec.contains(pt, m[0] / 2 + m[2])
            BOLT_CHECKS.append((f"{name} bolt ({pt[0]:.1f},{pt[1]:.1f}) pilot inside section", ok, ""))


# ---------------------------------------------------------------------------
# Geometry queries
# ---------------------------------------------------------------------------
class BooleanFailure(RuntimeError):
    """An OCC boolean or distance query raised, or returned something that contradicts the geometry.
    It is never turned into 0: callers either let it propagate or record a check failure."""


_BBOX = weakref.WeakKeyDictionary()      # Shape -> bbox; the optimal box is 25 ms on a drilled part, and the
                                        # hole checks ask for the same part's box thousands of times


def exact_box(shape):
    """(xmin, xmax, ymin, ymax, zmin, zmax) of a shape from its geometry alone, never from a mesh. cadquery's BoundingBox() takes a face's
    triangulation when the face has one and widens the box by its deflection. Any tessellation meshes a face (check 21's shadow, the voxel
    grids of zone_access and drive_access, a render), and the mesh stays on the face, which every moved or rebuilt copy of the part shares:
    the same solid then had another box depending on what ran before (a rebuilt sill read Y min -0.029 instead of 0.00 after a render)."""
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, b, False, False)
    xmin, ymin, zmin, xmax, ymax, zmax = b.Get()
    return (xmin, xmax, ymin, ymax, zmin, zmax)


def exact_bound_box(shape):
    """exact_box as a cadquery BoundBox (xmin .. zmax, xlen, ylen, zlen, center()), for code that reads those attributes."""
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, b, False, False)
    return cq.occ_impl.geom.BoundBox(b)


def bbox_of(shape):
    hit = _BBOX.get(shape)
    if hit is None:
        hit = exact_box(shape)
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
    the objects are kept in the entry, so their ids cannot be reused, and a hit must be the very same objects.
    A solid's identity stands for its geometry (a shape is not changed in place), nothing else: `extra` must hold every other
    number fn reads, the measurement's own steps, margins and tolerances (span_numbers(), iv_numbers()) and the fields of a
    mutable object such as a Hole (hole_numbers()). A number left out lets a changed measurement return the old answer."""
    if memo is None:
        return fn(*args)
    key = (tag,) + tuple(id(o) for o in objs) + tuple(extra)
    hit = memo.get(key)
    if hit is not None and len(hit[0]) == len(objs) and all(x is y for x, y in zip(hit[0], objs)):
        return hit[1]
    val = fn(*args)
    memo[key] = (tuple(objs), val)
    return val


def hole_numbers(h):
    """Every field of a Hole a measurement can read. A Hole is mutable, so its identity does not stand for its numbers."""
    return (h.kind, tuple(h.start), tuple(h.d), h.r, h.length, h.wall, h.pilot, h.stack, h.washer, h.item)


def iv_numbers():
    """The numbers inter_vol reads besides its two shapes."""
    return (BBOX_TOL, CROSS_VOL)


def span_numbers():
    """The numbers material_spans reads besides the solid and the probe's own numbers."""
    return (SPAN_STEP, SPAN_MARGIN)


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
    numbers = (tuple(hole.start), tuple(hole.d), hole.length) + span_numbers()
    if hole._spans is not None and hole._spans[0] is blank and hole._spans[1] == numbers:
        return hole._spans[2]

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
    hole._spans = (blank, numbers, spans)
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
            failures += memo_call(memo, (p.solid, p.blank, h), "hole", check_hole, p, h,
                                  extra=(p.name, hole_numbers(h), OVERSHOOT, BORE_SHRINK, BORE_EPS, WALL_EPS) + span_numbers() + iv_numbers())
    return n


# ---------------------------------------------------------------------------
# Check 5: mounts derived from the solids
# ---------------------------------------------------------------------------
DRIVE_SCREWS = sum(len(fc["holes"]) for fc in hw.drive_layout()["faces"].values())          # per bay: 6 on the 3.5 inch drive + 4 on the 2.5 inch drive
EXPECTED_MOUNTS = {"board": 9, "rad420": 2 * len(antler_holes_xn(1)), "rad360": 4, "psu": 4, "gpu_post": 2, "gpu_rest": 1, "gpu_rest_screw": len(REST_SCREW_DU_LIST), "front_io": len(hw.FRONT_IO_SCREWS),
                   "front_io_carrier": 2 * len(CARRIER_SCREWS_YZ), "hose_guide_cpu": 1, "organic": 12,
                   "tie_pilot": len(TIE_POINTS), "tie_bridge": len(TIE_POINTS), **{k: DRIVE_SCREWS for k in hw.DRIVES}}
ORGANIC_PROBE_DEPTH = 3.0      # check 5: the axis point of a pad's pilot lies this far in from the face
MIN_MOUNTS = {"fan_side_left": FAN_MIN_SCREWS, "fan_side_right": FAN_MIN_SCREWS}     # at least this many of the four corner holes
FAN_HOLDER = {"fan_side_left": "fan_bracket_left", "fan_side_right": "fan_bracket_right"}
DRIVE_PROBE_DEPTH = 1.5        # check 5: the axis point of a drive screw lies this far into the boss and plate from the drive's board (the boss is 1 mm high, the bore is empty to the head)
FAN_PROBE_DEPTH = 1.5          # axis point inside the pilot, from the fan face: at 1.5 the bore wall (r 2.0) is the nearest material


def mount_points():
    """(item, holder part, point on the hole axis inside the holder's thickness, hole radius, corner) for every
    mounting position, read from hardware.py's tables as they are at the moment of the call."""
    out = []
    for (v, u) in hw.ATX_HOLES:
        holder = next((nm for nm, row in BEAM_ROW.items() if abs(row - u) < 1e-6), None)
        out.append(("board", holder, hw.bp(v, u, hw.ATX_BOARD_N - 3.0), hw.M3_PILOT_D / 2, None))
    for side, holder in ((1, "antler_right"), (-1, "antler_left")):
        for (x, n) in antler_holes_xn(side):
            out.append(("rad420", holder, hw.bp(hw.x_to_v(x), ANTLER_U[0] + ANTLER_T / 2, n), hw.UNC6_CLEAR_D / 2, None))
    for holder, x in (("visor_arm_right", max(hw.RAD360_HOLES_X)), ("visor_arm_left", min(hw.RAD360_HOLES_X))):
        for u in hw.RAD360_HOLES_U:
            out.append(("rad360", holder, hw.bp(hw.x_to_v(x), u, hw.RAD360_INNER_N - HW_SCREW_FLOOR / 2), hw.UNC6_CLEAR_D / 2, None))      # in the floor under the counterbore
    for (x, z) in hw.PSU_HOLES:
        out.append(("psu", "psu_bulkhead", (x, hw.PSU_REAR_Y + HW_SCREW_FLOOR / 2, z), hw.UNC6_CLEAR_D / 2, None))      # in the floor under the counterbore
    for (pt, d) in hw.FRONT_IO_SCREWS:      # the module's screws: the axis point inside the carrier's end wall (revision 14a: it was the sill's), which must be an empty bore of the insert's radius
        probe = tuple(c + k * (CARRIER_PLAY + CARRIER_PROBE_DEPTH) for c, k in zip(pt, d))
        out.append(("front_io", "front_io_carrier", probe, hw.INSERTS[hw.FRONT_IO_SCREW_KIND][0] / 2, None))
    ax = guide_cpu_geometry()["axis"]      # the CPU hose guide's screw: the axis point inside the pilot, from the fan's face (the fan's own corner D has no hole in the bracket)
    out.append(("hose_guide_cpu", "hose_guide_cpu", (hw.FAN_SIDE_INNER_X[GUIDE_CPU_FAN] + hw.FAN_SIDE_IN[GUIDE_CPU_FAN] * FAN_PROBE_DEPTH, float(ax[0]), float(ax[1])), hw.M3_PILOT_D / 2, None))
    for (holder, (x, y, z), sgn) in hw.ORGANIC_PADS.values():      # the organic layer's pads: the axis point inside the pilot, which must be an empty bore of the insert's radius
        out.append(("organic", holder, (x - sgn * ORGANIC_PROBE_DEPTH, y, z), hw.M3_PILOT_D / 2, None))
    for tp in TIE_POINTS:      # the cable tie points: an empty M3 pilot bore in the host (axis point 3 mm in from the underside) and an empty clearance bore in the bridge's foot, on the same axis
        pt = tie_face_point(tp)
        out.append(("tie_pilot", tp["host"], tuple(c - ORGANIC_PROBE_DEPTH * k for c, k in zip(pt, tp["normal"])), hw.M3_PILOT_D / 2, None))
        out.append(("tie_bridge", tie_name(tp), tuple(c + TIE_FOOT_T / 2 * k for c, k in zip(pt, tp["normal"])), hw.M3_CLEAR_D / 2, None))
    for item, side in zip(hw.DRIVES, hw.DRIVE_SIDES.values()):      # the drives' screws: an empty clearance bore on the axis, 1.5 mm into the sled from the drive's board
        for fc in hw.drive_layout()["faces"].values():
            for (y, z) in fc["holes"]:
                out.append((item, "drive_sled_" + item.split("_")[1], (side * (fc["pb_x"] - fc["dir"] * DRIVE_PROBE_DEPTH), y, z), CLEAR_KINDS[THREAD_CLEAR[fc["spec"]["thread"]]][0] / 2, None))
    for fan, holder in FAN_HOLDER.items():
        x = hw.FAN_SIDE_INNER_X[fan] + hw.FAN_SIDE_IN[fan] * FAN_PROBE_DEPTH
        for corner, (u, n) in hw.FAN_SIDE_HOLES_UN.items():
            # an insert pilot in the plate at each corner, looked for at every corner of every fan; a corner counts once if it has one. The fan's flat inner face has no material at the probe.
            out.append((fan, holder, hw.bp(hw.x_to_v(x), u, n), hw.M3_PILOT_D / 2, corner))
    return out


def joint_mounts():
    """The screws between two printed parts that check 5 reads from BOTH solids, like gpu_post's: (item, [(part, axis point, radius of the empty bore expected there)]). gpu_rest's two (the insert's pilot
    in the part, 3 mm in from the seat; the clearance hole through the diagonal, half way) and the carrier's four (the insert's pilot in the sill's end block, 3 mm in from the pocket's wall; the clearance
    hole in the end block, in the middle of the floor under the counterbore)."""
    out = []
    for seat, floor in rest_screw_points():
        out.append(("gpu_rest_screw", [("gpu_rest", tuple(c + ORGANIC_PROBE_DEPTH * k for c, k in zip(seat, hw.N_DIR)), hw.M3_PILOT_D / 2),
                                       ("rib_A_right", tuple((a + b) / 2 for a, b in zip(seat, floor)), hw.M3_CLEAR_D / 2)]))
    for sgn, wall, face in carrier_screw_points():
        out.append(("front_io_carrier", [("front_sill", (wall[0] + sgn * ORGANIC_PROBE_DEPTH, wall[1], wall[2]), hw.M3_PILOT_D / 2),
                                         ("front_io_carrier", (face[0] - sgn * CARRIER_SCREW_FLOOR / 2, face[1], face[2]), hw.M3_CLEAR_D / 2)]))
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
            why = memo_call(memo, (part.solid,), "mount", hole_at, part, pt, r, extra=(tuple(pt), r, MOUNT_TOL))
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
                pt_post, pt_beam = hw.bp(GPU_POST_BOLT_V, u, hw.ATX_TRAY_N + 4.0), hw.bp(GPU_POST_BOLT_V, u, BEAM_N_MID)
                why_post = memo_call(memo, (byname["gpu_post"].solid,), "mount", hole_at, byname["gpu_post"], pt_post,
                                     hw.M3_PILOT_D / 2, extra=(tuple(pt_post), hw.M3_PILOT_D / 2, MOUNT_TOL))
                why_beam = memo_call(memo, (byname["beam_mid"].solid,), "mount", hole_at, byname["beam_mid"], pt_beam,
                                     hw.M3_CLEAR_D / 2, extra=(tuple(pt_beam), hw.M3_CLEAR_D / 2, MOUNT_TOL))
            except BooleanFailure as e:
                failures.append(f"CHECK5 gpu_post screw at u = {u}: BOOLEAN FAILED: {e}")
                continue
            if why_post or why_beam:
                failures.append(f"CHECK5 gpu_post screw at u = {u}: post {why_post or 'ok'}; beam_mid {why_beam or 'ok'}")
            else:
                got["gpu_post"] += 1
    for item, pairs in joint_mounts():      # revision 14a: the rest's and the carrier's screws, a pilot in one part and a clearance hole in the other
        whys = []
        for holder, pt, r in pairs:
            part = byname.get(holder)
            if part is None:
                whys.append(f"no holder part {holder}")
                continue
            try:
                why = memo_call(memo, (part.solid,), "mount", hole_at, part, pt, r, extra=(tuple(pt), r, MOUNT_TOL))
            except BooleanFailure as e:
                why = f"BOOLEAN FAILED: {e}"
            if why:
                whys.append(f"{holder} at ({pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f}): {why}")
        if whys:
            failures.append(f"CHECK5 {item} screw: " + "; ".join(whys))
        else:
            got[item] += 1
    if ("gpu_rest", "gpu") in contacts:
        got["gpu_rest"] = 1
    for item, n in EXPECTED_MOUNTS.items():
        if got[item] != n:
            failures.append(f"CHECK5 {item}: {got[item]} positions have a hole in the solids, the plan needs {n}")
    for item, n in MIN_MOUNTS.items():
        if got[item] < n:
            failures.append(f"CHECK5 {item}: {got[item]} of 4 corner holes have a screw hole in {FAN_HOLDER[item]}, the plan needs at least {n}")
    # the hand-written registry must agree with what the solids show
    registry = {"board": "board", "rad420": "rad420", "rad360": "rad360", "psu": "psu", "front_io": "front_io", "front_io_carrier": "front_io_carrier",
                "fan_side_left": "fan_side_left", "fan_side_right": "fan_side_right", "gpu": "gpu_post", "gpu_rest": "gpu_rest_screw", "hose_guide_cpu": "hose_guide_cpu",
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
    ("gpu_rest", "gpu"),                                                     # revision 14a: the rest's contact face under the card (it was rib_A_right's finger)
    ("gpu_rest", "rib_A_right"),                                             # part x part: the rest's foot on the diagonal's upper face (screwed there; listed with the planned contacts, though the report's part x part list has no tag)
    ("hose_guide_cpu", "fan_side_left"),                                     # revision 14a: the comb on the left fan's inner face, screwed through the fan at corner D
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


def _guard(failures, tag, label, fn, *args, **kw):
    """Run fn; a BooleanFailure becomes a named check failure and the result is None."""
    try:
        return fn(*args, **kw)
    except BooleanFailure as e:
        failures.append(f"{tag} {label}: BOOLEAN FAILED: {e}")
        return None


_NMAX: dict = {}


def part_n_max(p):
    """Highest board-space n of a part (the solid expressed in board space). Cached per solid object, which stays
    referenced by the cache so its id cannot be reused."""
    hit = _NMAX.get(id(p.solid))
    if hit is None or hit[0] is not p.solid:
        hit = (p.solid, float(exact_box(hw.to_board(p.solid))[5]))
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
            limit = hw.ENVELOPE_FAN_X if n in hw.FAN_SIDE_PARTS else hw.ENVELOPE_X      # revision 13: the side fans' brackets stand out to the fans' outer face, everything else to the radiators' ends
            if max(abs(b[0]), abs(b[1])) > limit + 1e-6:
                failures.append(f"CHECK8 {n} reaches |X| = {max(abs(b[0]), abs(b[1])):.2f}, limit {limit:g}")
            if b[2] < hw.ENVELOPE_Y0 - 1e-6:
                failures.append(f"CHECK8 {n} reaches Y = {b[2]:.2f}, in front of {hw.ENVELOPE_Y0:g}")
        if tag == "parts":
            rest = max(((max(abs(b[0]), abs(b[1])), n) for n, b in items if n not in hw.FAN_SIDE_PARTS))
            fans = max(((max(abs(b[0]), abs(b[1])), n) for n, b in items if n in hw.FAN_SIDE_PARTS), default=(0.0, ""))
            out["parts_rest"], out["parts_fan"] = rest, fans
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


def guide_spec():
    """guide -> (pair, hose keep-out name, side the mouths open to (world X sign), board u of each hose's channel, by hose index)."""
    return {"hose_guide_cpu": ("cpu", "cpu_hoses", hw.FAN_SIDE_IN[GUIDE_CPU_FAN], guide_cpu_geometry()["u"]),
            "hose_guide_gpu": ("gpu", "gpu_hoses", 1, [sum(GUIDE_GPU_U) / 2] * 2)}
MOUTH_TOL = 0.4         # mm: a slab this much narrower than the mouth must pass it, one this much wider must not


def check_guides(parts, failures, memo=None):
    """Check 10. For each hose guide and each hose it holds: the guide's solid does not intersect a tube of the true hose
    radius (volume < VOL_EPS), the channel wall is GUIDE_WALL_MIN..GUIDE_WALL_MAX from that tube, and the mouth is
    GUIDE_MOUTH x the hose diameter wide. Returns rows (guide, hose index, overlap mm3, wall mm, mouth ok)."""
    rows = []
    tubes = true_tubes()
    spec = guide_spec()
    for p in parts:
        if p.name not in spec:
            continue
        pair, hose_name, side, u_of = spec[p.name]
        mouth = GUIDE_MOUTH * 2 * guide_hose_r(pair)
        for i, tube in enumerate(tubes[hose_name]):
            label = f"{p.name} x {hose_name}[{i}]"
            v = _guard(failures, "CHECK10", label, memo_call, memo, (p.solid, tube), "iv", inter_vol, p.solid, tube, extra=iv_numbers())
            d = _guard(failures, "CHECK10", label, memo_call, memo, (p.solid, tube), "dist", solid_distance, p.solid, tube)
            def probe_vol(w):
                try:
                    hp, hd, _ = hose_at(pair, i, u_of[i])           # where the probe stands: the hose's route, which no solid's identity stands for
                    return memo_call(memo, (p.solid,), "mouth", lambda: inter_vol(p.solid, mouth_probe(pair, i, u_of[i], side, w)),
                                     extra=(pair, i, round(w, 4), u_of[i], side, guide_hose_r(pair), tuple(np.round(hp, 6)), tuple(np.round(hd, 9))) + iv_numbers())
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
    """The fan's open circle (hardware.FAN_APERTURE_D) as a cylinder along X, from APERTURE_FROM_OUT past the fan's outer face to the rib's outer face
    (revision 13: the leg is 49 mm long now, so the probe reaches the rib; it was 60 mm inside the inner face for a leg of 12 or 33). It is a probe, not hardware."""
    face, d = hw.FAN_SIDE_INNER_X[fan], hw.FAN_SIDE_IN[fan]
    x_out_face = hw.FAN_SIDE_X[fan][0 if d > 0 else 1]
    y, z = hw.bp_yz(*hw.FAN_CENTRE_UN)
    x0, x1 = sorted((x_out_face - d * APERTURE_FROM_OUT, -d * X_OUT))
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


def probe_line(start, d, length):
    return Hole("probe", tuple(start), _unit(d), 0.05, length, 0.0, False)


def check_carrier(parts, hardware, failures):
    """Check 20 (revision 14a). The module's box must sit in the carrier with the walls the carrier needs, measured on the carrier's undrilled solid: the end blocks at the module's own screws (along X, from the
    carrier's outer face to its inside) at least CARRIER_END_MIN thick (the module's pilot and the carrier's own counterbore), the top plate above the module (along Z, in the middle of the module) at least
    CARRIER_TOP_MIN thick. When the module grows past that the carrier is rebuilt with its inside bigger and its walls thinner; this is what stops it, short of the sill (the sill follows the carrier's outside,
    which does not move). Also the module's rear against the sill's pocket (the room behind it). Returns dict(end=[left, right], top, rear, grow=dict(left, right, top, rear)): the walls and how far the module may
    grow in each direction before this check, or the sill, has to change."""
    byname = {p.name: p for p in parts}
    car, io = byname.get("front_io_carrier"), hardware.get("front_io")
    if car is None or io is None:
        failures.append("CHECK20 the carrier or the module is missing")
        return {}
    b = bbox_of(io)                                 # the module's own box, as hardware (not the numbers the carrier was built from)
    (pl, dl), (pr, dr) = hw.FRONT_IO_SCREWS
    out = {"end": [], "top": None, "rear": None}
    try:
        for tag, (pt, d), x_out in (("left", (pl, dl), CARRIER_X[0]), ("right", (pr, dr), CARRIER_X[1])):
            sgn = -1.0 if x_out < 0 else 1.0
            spans = material_spans(car.blank, probe_line((x_out + sgn * 2.0, pt[1], pt[2]), (-sgn, 0.0, 0.0), 40.0))
            wall = spans[0][1] - spans[0][0] + 2 * SPAN_MARGIN if spans else 0.0       # from the outer face (the probe starts 2 mm outside it) to the cavity
            out["end"].append(wall)
            if wall < CARRIER_END_MIN - 1e-6:
                failures.append(f"CHECK20 the {tag} end block of front_io_carrier is {wall:.2f} mm thick at the module's screw, needs {CARRIER_END_MIN:g} (the module's box X {b[0]:g}..{b[1]:g} is too big for it)")
        xm, ym = (b[0] + b[1]) / 2, pl[1]
        spans = material_spans(car.blank, probe_line((xm, ym, CARRIER_Z[1] + 2.0), (0.0, 0.0, -1.0), 40.0))
        top = spans[0][1] - spans[0][0] + 2 * SPAN_MARGIN if spans else 0.0
        out["top"] = top
        if top < CARRIER_TOP_MIN - 1e-6:
            failures.append(f"CHECK20 the top plate of front_io_carrier is {top:.2f} mm thick over the module, needs {CARRIER_TOP_MIN:g} (the module's top Z {b[5]:g} is too high for it)")
    except BooleanFailure as e:
        failures.append(f"CHECK20 front_io_carrier: BOOLEAN FAILED: {e}")
        return out
    pocket_rear = CARRIER_Y1 + SILL_POCKET_PLAY
    out["rear"] = pocket_rear - b[3]
    if out["rear"] < -1e-6:
        failures.append(f"CHECK20 the module's rear Y {b[3]:g} is behind the sill's pocket (Y {pocket_rear:g})")
    wx0, wx1, wz0, wz1 = SILL_WINDOW_X + SILL_WINDOW_Z           # the module's cables leave its rear face: the sill's window must lie behind that face (revision 14a review)
    if not (b[0] <= wx0 + 1e-6 and wx1 <= b[1] + 1e-6 and b[4] <= wz0 + 1e-6 and wz1 <= b[5] + 1e-6):
        failures.append(f"CHECK20 the sill's cable window X {wx0:g}..{wx1:g}, Z {wz0:g}..{wz1:g} is not behind the module's rear face (X {b[0]:g}..{b[1]:g}, Z {b[4]:g}..{b[5]:g})")
    out["grow"] = dict(left=out["end"][0] - CARRIER_END_MIN if out["end"] else None, right=out["end"][1] - CARRIER_END_MIN if len(out["end"]) > 1 else None,
                       top=out["top"] - CARRIER_TOP_MIN, rear=out["rear"], front=b[2] - hw.ENVELOPE_Y0, bottom=b[4] - BEAM_FRONT_Z[1])
    return out


def check_sill_rear_wall(parts, failures, memo=None):
    """Check 22 (revision 14a review). The sill's rear wall behind the pocket, measured on the solid along +Y from the pocket's rear plane: every SILL_WALL_STEP along X over the pocket's length and along Z
    from the pocket's floor (beam_front's top) to its roof, apart from the cable window (a probe whose line runs through the window's cutter is skipped). The first run of material behind the pocket must
    be at least SILL_WALL_MIN. Returns dict(min=(wall, X, Z), n=probes). The probing (about 8 s) is remembered in `memo` under the sill's solid and every number of the pocket and the window it reads."""
    sill = next((p for p in parts if p.name == "front_sill"), None)
    if sill is None:
        failures.append("CHECK22 front_sill is missing")
        return {}
    g = sill_geometry()
    worst, n = memo_call(memo, (sill.solid,), "sill_wall", sill_wall_probes, sill.solid, g,
                         extra=(CARRIER_X, SILL_POCKET_PLAY, g["z0"], g["roof"], g["pocket_rear"], g["y_rear"], g["window_xz"], SILL_WINDOW_R, SILL_WALL_STEP) + span_numbers())
    if n == 0:
        failures.append("CHECK22 no probe of the sill's rear wall")
        return {}
    if worst[0] < SILL_WALL_MIN - 1e-3:
        failures.append(f"CHECK22 the sill's rear wall behind the pocket is {worst[0]:.2f} mm thick at X {worst[1]:.1f}, Z {worst[2]:.1f}, needs {SILL_WALL_MIN:g}")
    return dict(min=worst, n=n)


def sill_wall_probes(solid, g):
    """(thinnest wall (mm, X, Z) or None, number of probes) of check 22 on the sill's solid, for the pocket and window of sill_geometry() `g`."""
    x0, x1 = CARRIER_X[0] - SILL_POCKET_PLAY, CARRIER_X[1] + SILL_POCKET_PLAY
    z0, z1 = g["z0"], g["roof"]
    window, y_mid = g["cuts"]["window"], (g["pocket_rear"] + g["y_rear"]) / 2
    eps = 0.1                                                        # the probes stay this far inside the pocket's ends, floor and roof
    nx, nz = int(math.ceil((x1 - x0) / SILL_WALL_STEP[0])), int(math.ceil((z1 - z0) / SILL_WALL_STEP[1]))
    xs = [x0 + eps + (x1 - x0 - 2 * eps) * i / nx for i in range(nx + 1)]
    zs = [z0 + eps + (z1 - z0 - 2 * eps) * k / nz for k in range(nz + 1)]
    worst, n = None, 0
    for x in xs:
        for z in zs:
            if window.isInside(Vector(x, y_mid, z), 0.05):
                continue                                             # the window itself (its rounded corners included)
            spans = material_spans(solid, probe_line((x, g["pocket_rear"] - 1.0, z), (0.0, 1.0, 0.0), g["y_rear"] - g["pocket_rear"] + 3.0))
            wall = spans[0][1] - spans[0][0] + 2 * SPAN_MARGIN if spans else 0.0         # the first run of material behind the pocket
            n += 1
            if worst is None or wall < worst[0]:
                worst = (wall, x, z)
    return worst, n


SHADOW_RES = 0.1                  # mm per pixel of the guide's shadow in the fan's circle (check 21)
SHADOW_FAN = {"hose_guide_cpu": "fan_side_left"}      # the parts that may stand in a fan's open circle, but only so far (GUIDE_SHADOW_MAX), and their fan
_SHADOW_TUBES: dict = {}


def projection_mask(shape, window, res=SHADOW_RES):
    """Boolean image (rows = n, columns = u) of the pixels of `window` = (u0, u1, n0, n1) that `shape`'s projection along X covers, in board space: the shape is tessellated and every
    triangle filled. The boundary pixels count, so an area read from it is a little over the true one (by about half a pixel along the outline: under 0.1 % of the circle here)."""
    from PIL import Image, ImageDraw
    u0, u1, n0, n1 = window
    w, h = int(math.ceil((u1 - u0) / res)), int(math.ceil((n1 - n0) / res))
    img = Image.new("1", (w, h), 0)
    draw = ImageDraw.Draw(img)
    verts, tris = shape.tessellate(0.05, 0.2)
    pts = [hw.bs_of(v.x, v.y, v.z)[1:] for v in verts]
    for a, b, c in tris:
        draw.polygon([((pts[k][0] - u0) / res, (pts[k][1] - n0) / res) for k in (a, b, c)], fill=1)
    return np.array(img, dtype=bool)


def guide_shadow(solid, fan, tubes):
    """Area (mm2) that `solid`'s projection along X covers inside `fan`'s open circle (hw.FAN_APERTURE_D) outside the projection of `tubes` (the two hoses at their true radius): what the guide adds to
    what the hoses cover of the fan's opening anyway (revision 14a, check 21)."""
    cu, cn = hw.FAN_CENTRE_UN
    r = hw.FAN_APERTURE_D / 2
    window = (cu - r - 1.0, cu + r + 1.0, cn - r - 1.0, cn + r + 1.0)
    key = (round(cu, 3), round(cn, 3))
    if key not in _SHADOW_TUBES or _SHADOW_TUBES[key][0] is not tubes[0]:
        _SHADOW_TUBES[key] = (tubes[0], np.logical_or.reduce([projection_mask(t, window) for t in tubes]))
    hoses_mask = _SHADOW_TUBES[key][1]
    mask = projection_mask(solid, window)
    nn, uu = np.indices(mask.shape)
    uc, nc = window[0] + (uu + 0.5) * SHADOW_RES, window[2] + (nn + 0.5) * SHADOW_RES
    inside_circle = (uc - cu) ** 2 + (nc - cn) ** 2 <= r * r
    return float((mask & inside_circle & ~hoses_mask).sum() * SHADOW_RES ** 2)


def check_guide_shadow(parts, failures):
    """Check 21. A hose guide on a side fan's corner may not cast more than GUIDE_SHADOW_MAX mm2 of shadow into the fan's open circle beyond the hoses' own (the hoses cross the circle there
    whatever the guide does). Returns rows (part, mm2)."""
    rows = []
    tubes = true_tubes()["cpu_hoses"]
    for p in parts:
        if p.name not in SHADOW_FAN:
            continue
        a = guide_shadow(p.solid, SHADOW_FAN[p.name], tubes)
        rows.append((p.name, a))
        if a > GUIDE_SHADOW_MAX:
            failures.append(f"CHECK21 {p.name} shades {a:.0f} mm2 of the open circle of {SHADOW_FAN[p.name]} outside the hoses, the limit is {GUIDE_SHADOW_MAX:g}")
    return rows


# ---------------------------------------------------------------------------
# Checks 17 and 18 (revision 13): the side fan bracket and the card's post, hand calculations as functions of the model's own numbers (beam formulas, no mesh), so that a
# section that is made thinner fails here. The material numbers are strength.py's (it reads them from here): printed ABS, 20 MPa across the layers, safety 3.
# ---------------------------------------------------------------------------
ABS_STRENGTH_LAYER = 20.0        # MPa, typical across the layers
ABS_SAFETY = 3.0                 # on the weaker direction, for creep, heat and print defects
ABS_ALLOW = ABS_STRENGTH_LAYER / ABS_SAFETY          # 6.67 MPa
ABS_E = 2000.0                   # MPa, printed ABS along the layers
STRENGTH_MARGIN_MIN = 2.0        # revision 13: the bracket's and the post's worst section stays under ABS_ALLOW / this
FAN_KG = 0.2                     # a 140 mm fan's mass (strength.py's KG["fan140"])
CARD_KG = 1.6                    # the graphics card's mass (strength.py's KG["card"]; revision 14a: the number lives here, strength.py reads it)
GRAVITY = 9.81                   # m/s^2
KNOCK_N = 20.0                   # the plan's load on a side fan: 20 N along X at its far corner
PULL_N = 20.0                    # the plan's load on the card's post: 20 N along -X (v) on a cable at the lintel


def poly_props(pts):
    """(area, (cu, cn), Inn, Iuu, Iun) of a simple polygon of (u, n) vertices: the centroid, and the second moments about it, Inn = integral (u - cu)^2 dA, Iuu = integral (n - cn)^2 dA,
    Iun = integral (u - cu)(n - cn) dA (shoelace formulas)."""
    a = cx = cy = ixx = iyy = ixy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, list(pts[1:]) + [pts[0]]):
        k = x0 * y1 - x1 * y0
        a += k
        cx += (x0 + x1) * k
        cy += (y0 + y1) * k
        iyy += (x0 * x0 + x0 * x1 + x1 * x1) * k
        ixx += (y0 * y0 + y0 * y1 + y1 * y1) * k
        ixy += (x0 * y1 + 2 * x0 * y0 + 2 * x1 * y1 + x1 * y0) * k
    sgn = 1.0 if a > 0 else -1.0
    a, cx, cy = a / 2, cx / (6 * (a / 2)), cy / (6 * (a / 2))
    ixx, iyy, ixy = sgn * ixx / 12 - abs(a) * cy * cy, sgn * iyy / 12 - abs(a) * cx * cx, sgn * ixy / 24 - abs(a) * cx * cy
    return abs(a), (cx, cy), iyy, ixx, ixy


def bracket_strength(depth=None, leg=None, spine_w=None, bar_w=None):
    """Hand calculation of a side fan bracket under the plan's two loads (revision 13, item 5). Returns dict(rows, worst, margin, bolts, lines).
    Model: the fan is rigid and held by the three screws (corners A, B, C of the bracket), each of which takes a force along X only; the knock, KNOCK_N along X at the fan's far corner
    (u, n) = (FAN_SIDE_U[1], FAN_SIDE_N[1]), is shared by the three by statics: F_A + F_B + F_C = -F and the moments about the u and n axes. The leg carries the whole of F, eccentrically.
    The spine (a beam along n, depth `depth` along X) carries F_C over the lever from corner C down to the leg's top; the bar (a beam along u) carries F_B over the lever from the root
    block's end to corner B; the ear at C carries F_C over its stub. The weight, FAN_KG, acts at the fan's centre, down, across X over the lever from the fan's centre to the rib's face.
    rows: (what, load case, stress MPa, how)."""
    depth = BRACKET_T if depth is None else depth
    leg = BRACKET_LEG_UN if leg is None else leg
    spine_w = (BRACKET_SPINE_U[1] - BRACKET_SPINE_U[0]) if spine_w is None else spine_w
    bar_w = (BAR_N[1] - BAR_N[0]) if bar_w is None else bar_w
    corners = BRACKET_CORNERS["fan_bracket_right"]
    pos = {k: hw.FAN_SIDE_HOLES_UN[k] for k in corners}
    uK, nK = hw.FAN_SIDE_U[1], hw.FAN_SIDE_N[1]
    M = np.array([[1.0] * 3, [pos[k][0] for k in "ABC"], [pos[k][1] for k in "ABC"]])
    Fa, Fb, Fc = np.linalg.solve(M, -KNOCK_N * np.array([1.0, uK, nK]))
    force = dict(A=float(Fa), B=float(Fb), C=float(Fc))
    area, (cu, cn), Inn, Iuu, Iun = poly_props(list(leg))
    I = np.array([[Inn, Iun], [Iun, Iuu]])
    bc, cc = np.linalg.solve(I, KNOCK_N * np.array([uK - cu, nK - cn]))
    leg_sigma = max(abs(KNOCK_N / area + bc * (u - cu) + cc * (n - cn)) for u, n in leg)
    rows = [("leg", "knock", float(leg_sigma),
             f"A = {area:.0f} mm2, centroid (u {cu:.1f}, n {cn:.1f}), I_n = {Inn:.0f}, I_u = {Iuu:.0f}, I_un = {Iun:.0f} mm4; F = {KNOCK_N:g} N at (u {uK:g}, n {nK:g}): "
             f"M_n = F (u_K - u_c) = {KNOCK_N * (uK - cu):.0f}, M_u = F (n_K - n_c) = {KNOCK_N * (nK - cn):.0f} N mm; sigma = F/A + M_n (u - u_c)/I_n + M_u (n - n_c)/I_u at the worst vertex")]
    uC, nC = pos["C"]
    m_spine = abs(force["C"]) * (nC - BRACKET_LEG_N[1])
    rows.append(("spine", "knock", m_spine * 6 / (spine_w * depth ** 2),
                 f"F_C = {abs(force['C']):.1f} N at n {nC:.1f}, lever to the leg's top (n {BRACKET_LEG_N[1]:g}) {nC - BRACKET_LEG_N[1]:.1f} mm, M = {m_spine:.0f} N mm; section {spine_w:g} (u) x {depth:g} (X), "
                 f"W = b h^2 / 6 = {spine_w * depth ** 2 / 6:.0f} mm3"))
    uB = pos["B"][0]
    m_bar = abs(force["B"]) * (uB - ROOT_U[1])
    rows.append(("bar", "knock", m_bar * 6 / (bar_w * depth ** 2),
                 f"F_B = {abs(force['B']):.1f} N at u {uB:.1f}, lever from the root block's end (u {ROOT_U[1]:g}) {uB - ROOT_U[1]:.1f} mm, M = {m_bar:.0f} N mm; section {bar_w:g} (n) x {depth:g} (X), "
                 f"W = {bar_w * depth ** 2 / 6:.0f} mm3"))
    stub = uC - BRACKET_SPINE_U[1]
    rows.append(("ear C", "knock", abs(force["C"]) * stub * 6 / (2 * BRACKET_EAR * depth ** 2),
                 f"F_C = {abs(force['C']):.1f} N, stub {stub:.1f} mm from the spine's face, section {2 * BRACKET_EAR:.1f} x {depth:g}"))
    # the weight: F_u = F_n = -C W across X, lever L from the fan's centre to the rib's face
    W = FAN_KG * GRAVITY
    L = abs(sum(hw.FAN_SIDE_X["fan_side_right"]) / 2) - X_OUT
    fu = fn = hw.C * W
    bw = np.linalg.solve(I, np.array([fu * L, fn * L]))       # the two moments about the n and u axes through the leg's centroid
    grav_sigma = max(max(abs(sa * bw[0] * (u - cu) + sb * bw[1] * (n - cn)) for sa in (-1, 1) for sb in (-1, 1)) for u, n in leg)
    rows.append(("leg", "weight", float(grav_sigma),
                 f"W = {FAN_KG:g} kg x {GRAVITY:g} = {W:.2f} N, components along u and n {fu:.2f} N each, lever {L:.1f} mm (fan centre to the rib's face): M = {fu * L:.0f} N mm about each axis"))
    knock = max(r[2] for r in rows if r[1] == "knock")
    worst = max(r[2] for r in rows)
    # the two rib bolts' tension under the knock, by the pivot at the far edge of the leg's footprint (not a stress: the insert's pull-out is not in the data)
    (bu, bn_list) = BRACKET_BOLT_U, BRACKET_BOLT_N
    u_edge = max(u for u, n in leg)
    t_u = abs(KNOCK_N * (uK - cu)) / max(u_edge - bu, 1.0) / len(bn_list)
    arms = [BRACKET_LEG_N[1] - n for n in bn_list]
    t_n = [abs(KNOCK_N * (nK - cn)) * a / sum(x * x for x in arms) for a in arms]
    bolt = max(t_u + t for t in t_n)
    lines = [f"  Нагрузки (план, п. 5): удар {KNOCK_N:g} Н вдоль X в дальний угол вентилятора (u {uK:g}, n {nK:g}); вес вентилятора {FAN_KG:g} кг = {W:.2f} Н в его центре (u {hw.FAN_CENTRE_UN[0]:g}, n {hw.FAN_CENTRE_UN[1]:g}). "
             f"Допустимое {ABS_ALLOW:.2f} МПа (strength.py: {ABS_STRENGTH_LAYER:g} МПа поперёк слоёв / запас {ABS_SAFETY:g}); требуемый запас не меньше {STRENGTH_MARGIN_MIN:g}, то есть напряжение не выше {ABS_ALLOW / STRENGTH_MARGIN_MIN:.2f} МПа.",
             f"  Три винта (A, B, C) делят удар по статике: F_A {force['A']:+.1f}, F_B {force['B']:+.1f}, F_C {force['C']:+.1f} Н (сумма {sum(force.values()):+.1f} = -{KNOCK_N:g})."]
    for what, case_, sg, how in rows:
        lines.append(f"    {what:6s} {case_:7s} {sg:5.2f} МПа (запас {ABS_ALLOW / sg:4.1f}): {how}")
    lines.append(f"  Наихудшее сечение при ударе {knock:.2f} МПа ({[r[0] for r in rows if r[2] == knock][0]}), запас {ABS_ALLOW / knock:.2f}; от веса {grav_sigma:.2f} МПа.")
    lines.append(f"  Для сравнения, прежняя конструкция (плита {10:g} мм, ножка {11:g} x {28:g} мм): ножка при ударе {abs(KNOCK_N / (11 * 28) + KNOCK_N * (uK - 121.5) * 6 / (28 * 11 ** 2) + KNOCK_N * (nK + 20) * 6 / (11 * 28 ** 2)):.1f} МПа, "
                 f"хребет {abs(force['C']) * (nC - BRACKET_LEG_N[1]) * 6 / (spine_w * 10 ** 2):.1f} МПа, планка {abs(force['B']) * (uB - 128.0) * 6 / (bar_w * 10 ** 2):.1f} МПа (ножка была не худшим сечением).")
    lines.append(f"  Растяжение болтов M3 в ребре (2 штуки, давление на дальнем краю ножки): не больше {bolt:.0f} Н на болт; прочность вставки на вырыв в данных проекта нет, strength.py её не считает.")
    return dict(rows=rows, worst=float(worst), knock=float(knock), margin=float(ABS_ALLOW / worst), forces=force, bolt=float(bolt), lines=lines)


def post_strength(v_up=None, col_w=None):
    """Hand calculation of the card's post under PULL_N along -X (v) on a cable at the lintel (revision 13, item 6). Returns dict(rows, worst, margin, stiffness, lines).
    The post is a foot on beam_mid, two columns (the high-u one 18.9 wide, the low-u one GPU_POST_COL_W) joined by a lintel and standing on the slab under the window; the pull
    bends the columns about the u axis over the arm from the top of that slab to the lintel's middle. Worst case for the stress: the high column alone carries all of it (the
    low one, hanging from the lintel, taken as not there); the stiffness is given for both ways (both columns of equal curvature, and the high column alone)."""
    v_up = GPU_POST_V_UP if v_up is None else v_up
    col_w = GPU_POST_COL_W if col_w is None else col_w
    t = v_up[1] - v_up[0]
    w_high = GPU_POST_U_RANGE[1] - GPU_POST_U_WINDOW[1]
    n_load = (GPU_POST_N_WINDOW[1] + GPU_POST_N_RANGE[1]) / 2       # the lintel's mid-height
    arm = n_load - GPU_POST_N_WINDOW[0]                               # from the top of the slab under the window
    height = n_load - GPU_POST_N_RANGE[0]                             # from the foot
    m = PULL_N * arm
    sig_b = m * 6 / (w_high * t ** 2)
    sig_low = m * 6 / (col_w * t ** 2)                                # the case in which the pull's whole moment goes into the low column instead
    u_load = sum(GPU_POST_U_WINDOW) / 2
    torque = PULL_N * abs(u_load - (GPU_POST_U_WINDOW[1] + GPU_POST_U_RANGE[1]) / 2)

    def torsion_shear(width, tq):      # the largest shear of a rectangular section width x t under the torque tq (at the middle of its long side): tau = T / (alpha a b^2)
        a, b = max(width, t), min(width, t)
        al = float(np.interp(a / b, [1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 10.0], [0.208, 0.219, 0.231, 0.246, 0.258, 0.267, 0.282, 0.291, 0.312]))
        return tq / (al * a * b ** 2), a / b, al
    a_b = (max(w_high, t), min(w_high, t))
    tau, _ratio, alpha = torsion_shear(w_high, torque)
    vm = float(np.hypot(sig_b, np.sqrt(3.0) * tau))
    # the low column carrying the whole pull is loaded off its own centre too (found by the outside review of revision 13): the same combination, bending with the largest torsion shear
    torque_low = PULL_N * abs(u_load - (GPU_POST_U_WINDOW[0] - col_w / 2))
    tau_low = torsion_shear(col_w, torque_low)[0]
    vm_low = float(np.hypot(sig_low, np.sqrt(3.0) * tau_low))
    lintel_n = GPU_POST_N_RANGE[1] - GPU_POST_N_WINDOW[1]
    span = GPU_POST_U_WINDOW[1] - GPU_POST_U_WINDOW[0]
    sig_lintel = PULL_N * span * 6 / (lintel_n * t ** 2)               # a cantilever the width of the window, the pull at its free end
    I_h, I_l = w_high * t ** 3 / 12, col_w * t ** 3 / 12
    d_one = PULL_N * height ** 3 / (3 * ABS_E * I_h)
    d_both = PULL_N * height ** 3 / (3 * ABS_E * (I_h + I_l))
    rows = [("high column above the slab", "pull at the lintel's middle, the high column alone", sig_b),
            ("the same with torsion", "von Mises with the torque of the load's offset", vm),
            ("low column above the slab", "the whole moment in the low column", sig_low),
            ("the same with torsion", f"von Mises with the torque of the load's offset from the low column ({torque_low:.0f} N mm, shear {tau_low:.2f} MPa)", vm_low),
            ("lintel", "pull at the window's free end, a cantilever the width of the window", sig_lintel)]
    worst = max(r[2] for r in rows)
    lines = [f"  Нагрузка (план, п. 6): тяга кабеля {PULL_N:g} Н вдоль -X в середине перемычки (n {n_load:.2f}); допустимое {ABS_ALLOW:.2f} МПа, запас не меньше {STRENGTH_MARGIN_MIN:g}.",
             f"  Окно: u {GPU_POST_U_WINDOW[0]:.1f}..{GPU_POST_U_WINDOW[1]:.1f} ({span:.1f} мм, вся толщина карты {hw.GPU_BS[3] - hw.GPU_BS[2]:.1f} и по {GPU_POST_CLEAR:g} мм с каждой стороны) x n {GPU_POST_N_WINDOW[0]:g}..{GPU_POST_N_WINDOW[1]:g} "
             f"({GPU_POST_N_WINDOW[1] - GPU_POST_N_WINDOW[0]:g} мм, зона n {hw.GPU_OUT_N[0]:g}..{hw.GPU_OUT_N[1]:g} и по {GPU_POST_CLEAR:g} мм), насквозь по v {t:g} мм.",
             f"  Перемычка: n {GPU_POST_N_WINDOW[1]:g}..{GPU_POST_N_RANGE[1]:g} ({lintel_n:g} мм) x v {t:g} мм, на всю ширину рамки u {GPU_POST_U_RANGE[0]:.1f}..{GPU_POST_U_RANGE[1]:g}; верх n {GPU_POST_N_RANGE[1]:g} - место лапки планки карты (GPU_BRACKET_TAB_N, ЗАГЛУШКА).",
             f"  Колонны: высокая u {GPU_POST_U_WINDOW[1]:.1f}..{GPU_POST_U_RANGE[1]:g} ({w_high:.1f} мм, в ней два болта M3 u {GPU_POST_U[0]:g} и {GPU_POST_U[1]:g}, стенка вокруг пилота {GPU_POST_U[0] - hw.M3_PILOT_D / 2 - GPU_POST_U_WINDOW[1]:.1f} мм), низкая u {GPU_POST_U_RANGE[0]:.1f}..{GPU_POST_U_WINDOW[0]:.1f} ({col_w:g} мм); "
             f"плита под окном n {GPU_POST_N_RANGE[0]:g}..{GPU_POST_N_WINDOW[0]:g}. Наименьшая стенка сечения {min(lintel_n, col_w, w_high):g} мм (перемычка {lintel_n:g}, колонна {col_w:g}); вокруг пилота болта {GPU_POST_U[0] - hw.M3_PILOT_D / 2 - GPU_POST_U_WINDOW[1]:.1f} мм (правило {hw.M3_MIN_WALL:g}).",
             f"  Момент тяги у верха плиты под окном: M = {PULL_N:g} x {arm:.2f} = {m:.0f} Н мм (плечо до середины перемычки; от ступни {height:.2f}).",
             ]
    for what, how, sg in rows:
        lines.append(f"    {what:28s} {sg:5.2f} МПа (запас {ABS_ALLOW / sg:4.1f}): {how}")
    lines.append(f"    сечение колонны {w_high:.1f} x {t:g} мм, W = {w_high * t ** 2 / 6:.0f} мм3 (низкая {col_w * t ** 2 / 6:.0f}); крутящий момент {torque:.0f} Н мм, касательное {tau:.2f} МПа (a/b = {a_b[0] / a_b[1]:.2f}, коэффициент {alpha:.3f}).")
    lines.append(f"  Жёсткость: прогиб верха под {PULL_N:g} Н = F h^3 / (3 E I) при E = {ABS_E:g} МПа, h = {height:.2f} мм: обе колонны одной кривизны (I = {I_h + I_l:.0f} мм4) {d_both:.2f} мм ({PULL_N / d_both:.0f} Н/мм); "
                 f"одна высокая (I = {I_h:.0f} мм4) {d_one:.2f} мм ({PULL_N / d_one:.0f} Н/мм). Податливость болтов и вставок не учтена; значения для сплошной стенки.")
    return dict(rows=rows, worst=float(worst), margin=float(ABS_ALLOW / worst), stiffness=float(PULL_N / d_one), deflection=(float(d_both), float(d_one)), lines=lines)


def rest_strength(width=None, depth=None):
    """Hand calculation of the card's rest, gpu_rest, under two loads (revision 14a, item 1). Returns dict(rows, worst, margin, tension, lines).
    The finger is a cantilever standing on the diagonal's upper face (the seat, n REST_SEAT_N), `width` along u (REST_W) and `depth` along X (the rib's thickness).
    1. The card's whole weight, CARD_KG x g, pressing on the contact face at the middle of its flat part (n from the seat to REST_N_AXIS[1]) along -u: bending about the X axis,
       sigma = M 6 / (depth width^2) at the foot. The card's other end is held by the post, so the whole weight on the rest is the safe side.
    2. A knock of KNOCK_N along X at the finger's tip (n REST_N_AXIS[1] + width / 2): bending about the u axis, sigma = M 6 / (width depth^2) at the foot.
    The screws' tension, from the moment of each load about the foot's edge, which the foot turns about: the weight about the low-u edge (two screws at REST_SCREW_DU either side of
    the finger's middle, tension in proportion to the distance from the edge), the knock about the X edge, the two screws on the middle line of X sharing it equally. Not a stress:
    the insert's pull-out is not in the data."""
    width = REST_W if width is None else width
    depth = (REST_X[1] - REST_X[0]) if depth is None else depth
    W = CARD_KG * GRAVITY
    n_mid = (REST_SEAT_N + REST_N_AXIS[1]) / 2
    arm_w = n_mid - REST_SEAT_N
    m_w = W * arm_w
    sig_w = m_w * 6 / (depth * width ** 2)
    n_tip = REST_N_AXIS[1] + width / 2
    arm_k = n_tip - REST_SEAT_N
    m_k = KNOCK_N * arm_k
    sig_k = m_k * 6 / (width * depth ** 2)
    edge = hw.GPU_BS[2] - width
    arms = [(hw.GPU_BS[2] - width / 2 + du) - edge for du in (-REST_SCREW_DU, REST_SCREW_DU)]
    t_w = [m_w * a / sum(x * x for x in arms) for a in arms]
    t_k = m_k / (depth / 2) / 2
    tension = max(t_w) + t_k
    rows = [("finger at the foot", "weight", sig_w,
             f"the card's {CARD_KG:g} kg x {GRAVITY:g} = {W:.2f} N on the contact face at n {n_mid:g}, arm {arm_w:g} mm from the seat (n {REST_SEAT_N:g}), M = {m_w:.0f} N mm; section {width:g} (u) x {depth:g} (X), "
             f"W = d w^2 / 6 = {depth * width ** 2 / 6:.0f} mm3"),
            ("finger at the foot", "knock", sig_k,
             f"{KNOCK_N:g} N along X at the tip (n {n_tip:g}), arm {arm_k:g} mm, M = {m_k:.0f} N mm; W = w d^2 / 6 = {width * depth ** 2 / 6:.0f} mm3")]
    worst = max(r[2] for r in rows)
    lines = [f"  Нагрузки (план, п. 1): весь вес карты {CARD_KG:g} кг = {W:.2f} Н на контактную грань посередине её плоской части (n {n_mid:g}); удар {KNOCK_N:g} Н вдоль X в кончик пальца (n {n_tip:g}). "
             f"Допустимое {ABS_ALLOW:.2f} МПа, запас не меньше {STRENGTH_MARGIN_MIN:g}, то есть не выше {ABS_ALLOW / STRENGTH_MARGIN_MIN:.2f} МПа."]
    for what, case_, sg, how in rows:
        lines.append(f"    {what:20s} {case_:7s} {sg:5.2f} МПа (запас {ABS_ALLOW / sg:4.1f}): {how}")
    lines.append(f"  Наихудшее сечение {worst:.2f} МПа, запас {ABS_ALLOW / worst:.2f}. Для сравнения, палец прежних 16 мм (ребро): удар {KNOCK_N * (REST_N_AXIS[1] + 8.0 - REST_SEAT_N) * 6 / (16.0 * depth ** 2):.2f} МПа "
                 f"(запас {ABS_ALLOW / (KNOCK_N * (REST_N_AXIS[1] + 8.0 - REST_SEAT_N) * 6 / (16.0 * depth ** 2)):.2f}).")
    lines.append(f"  Растяжение двух винтов M3: от веса {max(t_w):.0f} Н на дальний (поворот вокруг нижней по u кромки, плечи {arms[0]:g} и {arms[1]:g} мм), от удара {t_k:.0f} Н на каждый "
                 f"(поворот вокруг кромки по X, плечо {depth / 2:g} мм); вместе до {tension:.0f} Н на винт. Прочность вставки на вырыв в данных проекта нет (docs/plans/fasteners-m3.md: около 1170 Н хорошая вставка в PETG, 380 Н плохая, для ABS не найдено).")
    return dict(rows=rows, worst=float(worst), margin=float(ABS_ALLOW / worst), tension=float(tension), tension_weight=float(max(t_w)), tension_knock=float(t_k), lines=lines)


def check_strength(failures):
    """Checks 17, 18 and 19: the margins of bracket_strength(), post_strength() and rest_strength()."""
    out = {}
    for tag, fn, what in (("CHECK17", bracket_strength, "fan bracket"), ("CHECK18", post_strength, "card post"), ("CHECK19", rest_strength, "gpu_rest")):
        r = fn()
        out[what] = r
        if r["margin"] < STRENGTH_MARGIN_MIN - 1e-9:
            failures.append(f"{tag} {what}: the worst section carries {r['worst']:.2f} MPa, margin {r['margin']:.2f} against {ABS_ALLOW:.2f} MPa, needs {STRENGTH_MARGIN_MIN:g}")
    return out


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
                               p.blank if p.blank is not None else p.solid, extra=(tuple(ANTLER_U), tuple(hw.U_DIR), WEB_RES)) or (float("nan"), None, None)
            out["webs"].append((p.name, w, xr, nr))
            if w < MIN_WEB - 0.1:
                failures.append(f"CHECK14 {p.name} has a web {w:.2f} mm wide at |X| {abs(xr[0]):.1f}..{abs(xr[1]):.1f}, n {nr[0]:.1f}..{nr[1]:.1f}: nothing of the plate may be narrower than {MIN_WEB:g} mm")
    # (d) the chord and the plate's lower edge keep CHORD_FAN_GAP clear of the fans' underside (n -16) wherever they stand under the fans
    air = hw.bs_box(*hw.RAD420_FAN_V, *hw.RAD420_FAN_U, hw.RAD420_FAN_N[0] - CHORD_FAN_GAP + 0.01, hw.RAD420_FAN_N[0] - 0.01)
    out["underside"] = []
    for p in parts:
        if p.name.startswith("antler"):
            v = _guard(failures, "CHECK14", f"{p.name} x the fans' underside", memo_call, memo, (p.solid, air), "iv", inter_vol, p.solid, air, extra=iv_numbers())
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


def sharp_numbers(name):
    """What sharp_axial_edges reads for plate `name` besides its solid: the plate's axes, the numbers its filter (plate_accept) reads, the angle that makes an edge sharp."""
    axes = plate_axes(name)
    return (name, None if axes is None else tuple(map(tuple, axes)), tuple(TONGUE_X), tuple(TONGUE_N), NECK_X[0], ARM_NOTCH_X, rd.SHARP_DEG)


def classify_corners(p, others, memo=None):
    """Sharp outline corners of plate `p` and why each is allowed to stay: 'lap' (a step of a lap joint), 'allowance' (the corner's rounding would
    take more contact area than the 97 % floor leaves, or flat contact within 4 mm of a screw; ROUND_LOG says so), 'hole' (it would cut a
    hole's wall or the access to a screw head), 'nofit' (no radius of 2 mm or more fits between the neighbouring edges), 'kernel' (the
    kernel could not make the fillet), 'declared' (KEEP_SHARP, the bracket's rail group), 'junction' (the run-out of a fillet), 'contact'
    (a face of the part lies against hardware or another part within the reach of the largest radius and the log has no entry: a step cut
    by a neighbour), or 'open' (nothing excuses it). others: rounding.Neighbors of the hardware and the other parts."""
    edges = memo_call(memo, (p.solid,), "sharp", lambda: rd.sharp_axial_edges(p.solid, plate_axes(p.name), accept=plate_accept(p.name)), extra=sharp_numbers(p.name))
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
                       lambda: rd.sharp_axial_edges(p.solid, plate_axes(p.name), accept=plate_accept(p.name), caps=False), extra=sharp_numbers(p.name))
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
        recorded = [h for h in sled.holes if h.kind in THREAD_CLEAR.values()]
        n_table = 0
        for face, fc in hw.drive_layout()["faces"].items():
            F = fc["spec"]
            into = (-side * fc["dir"], 0.0, 0.0)                    # from the drive's board into the sled
            far_into = (side * fc["dir"], 0.0, 0.0)                 # from the face the screw comes in from, towards the drive
            r_head = F["head_d"] / 2
            r_bore = CLEAR_KINDS[THREAD_CLEAR[F["thread"]]][0] / 2
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


# ---------------------------------------------------------------------------
# Check 15: the owner's screws. Every insert pilot that carries a stack is a screw: the thickness it clamps is measured on the solids (the clearance holes
# on its axis and the material round them, or the hardware it clamps), the length is the owner's that fits (screw_fit), and the counts stay inside the stock.
# ---------------------------------------------------------------------------
STACK_TOL = 0.1          # mm: the measured stack against the one the pilot was made for
STACK_GAP = 0.5          # mm: a gap this small between two clamped parts does not break the stack
CLAMPS_HARDWARE = {"board": ("board",), "side fan": hw.FAN_SIDE_NAMES, "hose_guide_cpu": (GUIDE_CPU_FAN,)}      # the screws that clamp a hardware solid, by their item: the board's, the side fans' and the CPU guide's, which goes through the left fan
HARDWARE_PROBE_LEN = 40.0            # mm: how far behind a pilot's mouth the hardware is looked for
WASHER_SEAT_DEPTH = 0.1              # mm: the washer's rim is probed this far inside the face it bears on
WASHER_RIM_POINTS = 24


def axis_run(h, solids_spans):
    """From the pilot `h`'s mouth towards its screw head: the end of the unbroken run of material given as (s0, s1) intervals along the axis (s = distance from the mouth)."""
    end = 0.0
    for a, b in sorted(solids_spans):
        if a <= end + STACK_GAP:
            end = max(end, b)
    return end


def measured_stack(h, parts, hardware):
    """(stack, what) of the screw whose pilot is `h`: the run of material on the axis behind the pilot's mouth, from the clearance holes of the other parts and from the hardware.
    None when nothing is there to measure (the organic layer's pad is not in this file)."""
    mouth = h.point(OVERSHOOT)
    back = tuple(-c for c in h.d)
    spans, names = [], []

    def along(p):
        return sum((a - b) * c for a, b, c in zip(p, mouth, back))

    for q in parts:
        for g in q.holes:
            if g.pilot or g.kind != "M3c" or abs(abs(sum(a * b for a, b in zip(g.d, h.d))) - 1.0) > 1e-6:
                continue
            off = [a - b for a, b in zip(g.start, mouth)]
            t = sum(a * b for a, b in zip(off, h.d))
            if math.sqrt(max(0.0, sum(a * a for a in off) - t * t)) > 0.01:
                continue
            for (a, b) in material_spans(q.blank, g):
                s0, s1 = sorted((along(g.point(a)), along(g.point(b))))
                spans.append((s0 - SPAN_MARGIN, s1 + SPAN_MARGIN))
                names.append(q.name)
    for k in CLAMPS_HARDWARE.get(h.item, ()):
        probe = Hole("probe", mouth, back, 0.1, HARDWARE_PROBE_LEN, 0.0, False)
        for (a, b) in material_spans(hardware[k], probe):
            spans.append((a - SPAN_MARGIN, b + SPAN_MARGIN))
            names.append(k)
    end = axis_run(h, spans)
    seat = next((n for (a, b), n in zip(spans, names) if abs(b - end) < 1e-9 and n in {q.name for q in parts}), None)       # the part the head's washer bears on
    return (end, sorted(set(names)), seat) if end > 0 else None


def washer_on_face(h, stack, seat, parts):
    """True if the washer (hw.M3_WASHER_D across) under the head of the screw whose pilot is `h` lies on the face of the part `seat` it bears on: points on the washer's rim, just
    inside the face, are material (the face has the flat for it: not an edge, a rounding or another hole)."""
    q = next(x for x in parts if x.name == seat)
    mouth = h.point(OVERSHOOT)
    d = np.array(h.d, float)
    a = np.cross(d, [1.0, 0.0, 0.0])
    if np.linalg.norm(a) < 0.1:
        a = np.cross(d, [0.0, 1.0, 0.0])
    a /= np.linalg.norm(a)
    b = np.cross(d, a)
    centre = np.array(mouth) - (stack - WASHER_SEAT_DEPTH) * d
    for k in range(WASHER_RIM_POINTS):
        t = 2 * math.pi * k / WASHER_RIM_POINTS
        if not q.solid.isInside(Vector(*(centre + hw.M3_WASHER_D / 2 * (math.cos(t) * a + math.sin(t) * b)))):
            return False
    return True


def check_screws(parts, hardware, failures):
    """Check 15. Returns dict(rows, bill, inserts, washers, tightest): one row per insert pilot that carries a stack (part, item, position, stack, length, entry, depth, margin,
    relief, what is clamped), the bill {length: (count, items)}, the number of inserts (every pilot) and of washers."""
    rows, inserts, washers = [], 0, 0
    for p in parts:
        for h in p.holes:
            if not h.pilot:
                continue
            inserts += 1
            if h.stack is None:
                continue
            got = measured_stack(h, parts, hardware)
            where = f"{p.name}: {h.describe()}"
            if got is None:
                stack, what = h.stack, ["not measured here (the pad is the organic layer's)"]
                if h.item != "organic pad":
                    failures.append(f"CHECK15 {where}: nothing clamped on the screw's axis, the pilot was made for {h.stack:g} mm")
            else:
                stack, what, seat = got
                if h.washer and seat is not None and not washer_on_face(h, h.stack, seat, parts):
                    failures.append(f"CHECK15 {where}: the {hw.M3_WASHER_D:g} mm washer under the head does not lie on the face of {seat}")
                if abs(stack - h.stack) > STACK_TOL:
                    failures.append(f"CHECK15 {where}: the screw clamps {stack:.2f} mm ({', '.join(what)}), the pilot was made for {h.stack:g} mm")
                else:
                    stack = h.stack          # agreed within STACK_TOL: the length is chosen for the design figure, not for the sampling noise
            try:
                length, entry, relief_needed = screw_fit(stack, h.washer)
            except ValueError:
                failures.append(f"CHECK15 {where}: no screw in the kit is long enough for {stack:.2f} mm")
                continue
            relief = sum(g.length - 0.2 for g in p.holes if g.kind == "M3r" and g.item == h.item and math.dist(g.start, h.start) < h.length + 1e-6
                         and abs(abs(sum(a * b for a, b in zip(g.d, h.d))) - 1.0) < 1e-6)
            depth = hw.M3_PILOT_DEPTH + relief
            if entry < hw.SCREW_ENGAGE_MIN - FIT_EPS:
                failures.append(f"CHECK15 {where}: M3 x {length} enters the insert {entry:.2f} mm, needs {hw.SCREW_ENGAGE_MIN:g}")
            if entry > depth - hw.SCREW_BOTTOM_GAP + FIT_EPS:
                failures.append(f"CHECK15 {where}: M3 x {length} stops {depth - entry:.2f} mm from the bottom of the hole ({hw.M3_PILOT_DEPTH:g} deep, relief {relief:.1f}), needs {hw.SCREW_BOTTOM_GAP:g}")
            washers += 1 if h.washer else 0
            margin = min(entry - hw.SCREW_ENGAGE_MIN, depth - hw.SCREW_BOTTOM_GAP - entry)
            rows.append(dict(part=p.name, item=h.item, pos=h.point(OVERSHOOT), stack=stack, length=length, entry=entry, depth=depth, margin=margin, relief=relief, what=what, washer=h.washer))
    bill = {}
    for r in rows:
        n, items = bill.get(r["length"], (0, {}))
        items[r["item"]] = items.get(r["item"], 0) + 1
        bill[r["length"]] = (n + 1, items)
    for length, (n, _) in sorted(bill.items()):
        if n > hw.STOCK_SHARE * hw.M3_SCREW_STOCK[length] + FIT_EPS:
            failures.append(f"CHECK15 M3 x {length}: {n} needed, the owner has {hw.M3_SCREW_STOCK[length]} and the model may use {hw.STOCK_SHARE:g} of them ({hw.STOCK_SHARE * hw.M3_SCREW_STOCK[length]:g})")
    if inserts > hw.STOCK_SHARE * hw.M3_INSERT_STOCK + FIT_EPS:
        failures.append(f"CHECK15 {inserts} M3 inserts needed, the owner has {hw.M3_INSERT_STOCK} and the model may use {hw.STOCK_SHARE:g} of them ({hw.STOCK_SHARE * hw.M3_INSERT_STOCK:g})")
    if washers > hw.STOCK_SHARE * hw.M3_WASHER_STOCK + FIT_EPS:
        failures.append(f"CHECK15 {washers} M3 washers needed, the owner has {hw.M3_WASHER_STOCK} and the model may use {hw.STOCK_SHARE:g} of them ({hw.STOCK_SHARE * hw.M3_WASHER_STOCK:g})")
    tightest = min(rows, key=lambda r: r["margin"]) if rows else None
    return dict(rows=rows, bill=bill, inserts=inserts, washers=washers, tightest=tightest)


COUNTERBORE_TOL = 0.1    # mm: the material measured under a hardware screw's head against the floor the counterbore was made to leave


def check_counterbores(parts, failures):
    """Check 16. Under the head of each hardware 6-32 screw that sits in a counterbore (the PSU's on psu_bulkhead, the 360's on the visor arms) HW_SCREW_FLOOR mm of material is left,
    measured on the solid beside the bore. Returns [(part, position, floor, screw length, entry)]."""
    screw_len = {"psu_bulkhead": hw.PSU_SCREW_LEN, "visor_arm_right": hw.RAD360_SCREW_LEN, "visor_arm_left": hw.RAD360_SCREW_LEN}
    rows = []
    for p in parts:
        for h in p.holes:
            if h.kind != "6-32cb":
                continue
            rho = (hw.UNC6_CLEAR_D / 2 + h.r) / 2
            side = (1.0, 0.0, 0.0)
            probe = Hole("probe", tuple(c + rho * k for c, k in zip(h.start, side)), h.d, 0.1, h.length + 12.0, 0.0, False)
            floor = sum(b - a + 2 * SPAN_MARGIN for a, b in material_spans(p.solid, probe))      # material_spans stops SPAN_MARGIN short of each face
            pos = h.point(OVERSHOOT)
            rows.append((p.name, pos, floor, screw_len[p.name], screw_len[p.name] - floor))
            if abs(floor - HW_SCREW_FLOOR) > COUNTERBORE_TOL:
                failures.append(f"CHECK16 {p.name}: {h.describe()} leaves {floor:.2f} mm under the head, the plan leaves {HW_SCREW_FLOOR:g}")
    return rows


CB_RIM_POINTS = 8          # check 16, M3 counterbores: the face round a counterbore is probed at this many points, 0.5 mm outside its edge
CB_FACE_FLAT = 0.05        # mm: the rim points agree this well, or the counterbore is not sunk in one flat face


def check_m3_counterbores(parts, failures, memo=None):
    """Check 16, second half (revision 14a review). Every M3 counterbore (Hole kind "M3cb": the carrier's and the card rest's, recorded with the part's holes) measured on the solid along its axis:
    the face round it (CB_RIM_POINTS probes 0.5 mm outside its edge, which must agree within CB_FACE_FLAT), its floor (a probe between the screw's clearance bore and the counterbore's wall) and the
    unbroken material under the floor. The depth from the face to the floor holds the head and the washer with M3_CB_SINK to spare (at least M3_CB_DEPTH). Returns [(part, item, position, depth, floor)].
    The probing (about 4 s for all of them) is remembered in `memo` under the part's solid and the hole."""
    rows = []
    for p in parts:
        for h in p.holes:
            if h.kind != "M3cb":
                continue
            where = f"{p.name}: {h.describe()}"
            rim, bottom = memo_call(memo, (p.solid, h), "m3cb", m3_counterbore_probes, p.solid, h, extra=(hole_numbers(h), CB_RIM_POINTS, hw.M3_CLEAR_D) + span_numbers())
            if None in rim or bottom is None:
                failures.append(f"CHECK16 {where}: no face round the counterbore or no floor under it")
                continue
            face = [s0 for s0, _ in rim]
            if max(face) - min(face) > CB_FACE_FLAT:
                failures.append(f"CHECK16 {where}: the face round the counterbore is not flat ({min(face) - OVERSHOOT:.2f}..{max(face) - OVERSHOOT:.2f} mm along its axis)")
            depth, floor = bottom[0] - min(face), bottom[1] - bottom[0]
            rows.append((p.name, h.item, h.point(OVERSHOOT), depth, floor))
            if depth < M3_CB_DEPTH - COUNTERBORE_TOL / 2:
                failures.append(f"CHECK16 {where}: the counterbore is {depth:.2f} mm deep, the head and the washer need {hw.M3_HEAD_H + hw.M3_WASHER_T:g} and {M3_CB_SINK:g} to spare ({M3_CB_DEPTH:g})")
    return rows


def m3_counterbore_probes(solid, h):
    """(the CB_RIM_POINTS spans of material 0.5 mm outside the counterbore's edge, the span under its floor) along the hole's axis, each (start, end) or None (check 16)."""
    d = np.array(h.d, float)
    a = np.cross(d, [1.0, 0.0, 0.0])
    if np.linalg.norm(a) < 0.1:
        a = np.cross(d, [0.0, 1.0, 0.0])
    a /= np.linalg.norm(a)
    b = np.cross(d, a)
    reach = h.length + 40.0

    def first_span(rho, t):
        off = rho * (math.cos(t) * a + math.sin(t) * b)
        spans = material_spans(solid, Hole("probe", tuple(np.array(h.start) + off), h.d, 0.05, reach, 0.0, False))
        return (spans[0][0] - SPAN_MARGIN, spans[0][1] + SPAN_MARGIN) if spans else None
    return [first_span(h.r + 0.5, 2 * math.pi * k / CB_RIM_POINTS) for k in range(CB_RIM_POINTS)], first_span((hw.M3_CLEAR_D / 2 + h.r) / 2, 0.0)


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
        rows = memo_call(memo, (p.solid,) + tuple(n.shape for n in near), "corners", classify_corners, p, rd.Neighbors(near), memo,
                         extra=sharp_numbers(p.name) + (tuple(n.name for n in near), tuple(map(tuple, LAP_ZONES)), RIB_T, ROUND_CONCAVE,
                                                         bracket_join_x(p.name) if p.name.startswith("fan_bracket") else None))
        # not in the key: ROUND_LOG and KEEP_SHARP, which the build that made p.solid wrote; a later build (a test's damaged copy) rewrites them for other solids
        by = {w: sum(1 for c in rows if c[0] == w) for w in CORNER_CLASSES}
        out.append((p.name, len(rows), ref_sharp(p.name), by, [c for c in rows if c[0] == "open"]))
    return out


def run_checks(hardware, parts, memo=None):
    failures: list[str] = []
    res: dict = {}

    # 1. hardware x hardware
    hh = []
    for (an, a), (bn, b) in itertools.combinations(hardware.items(), 2):
        v = _guard(failures, "CHECK1", f"hardware {an} x {bn}", memo_call, memo, (a, b), "iv", inter_vol, a, b, extra=iv_numbers())
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
                       inter_vol, p.solid, hs, extra=iv_numbers())
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
                   inter_vol, a.solid, b.solid, extra=iv_numbers())
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
    for need in ("gpu_post", "gpu_rest", "rib_A_right", "front_io_carrier"):
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

    # 21. the CPU hose guide, on the left fan's corner D, may shade only so much of the fan's circle beyond the hoses' own shadow
    res["guide_shadow"] = check_guide_shadow(parts, failures)

    # 20. the front I/O module sits in its carrier with the walls the carrier needs; the room behind it in the sill's pocket; the sill's cable window behind its rear face
    res["carrier"] = check_carrier(parts, hardware, failures)

    # 22. the sill's rear wall behind the pocket keeps SILL_WALL_MIN from the pocket's floor to its roof and over its length
    res["sill_wall"] = check_sill_rear_wall(parts, failures, memo)

    # 14. the 420's bracket plates stay out of the fans' openings and keep the wall round every fan screw
    res["plates420"] = check_420_plates(parts, failures, memo)

    # 17, 18. the side fan bracket and the card's post carry the plan's loads with a margin of 2 (hand calculation, revision 13)
    res["strength"] = check_strength(failures)

    # 12. sharp outline corners that remain on the plates; fails only for a plate where nothing was rounded
    res["corners"] = check_corners(parts, hardware, pb, hb, failures, memo)

    # 13. the drive bays: hole patterns, screw penetration, head room, envelope
    res["drives"] = check_drive_bays(parts, hardware, failures, contacts, pp_contact)

    # 15. the owner's screws: stack, length, entry, counts against the stock; 16. the counterbores for the hardware's own screws, and for the M3 heads and washers between printed parts
    res["screws"] = check_screws(parts, hardware, failures)
    res["counterbores"] = check_counterbores(parts, failures)
    res["m3_counterbores"] = check_m3_counterbores(parts, failures, memo)

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
                     f"2 x M3 x {screw_fit(BULK_T)[0]} вдоль Y в X {sg * SLED_BOLT_X:g}, Z {SLED_BOLT_Z[0]:g} и {SLED_BOLT_Z[1]:g} (проходные Ø{hw.M3_CLEAR_D:g} в стенке psu_bulkhead, вставки M3 во фланце, шайба под головкой); ступня - нижняя грань на skid_rear (Z 0)")
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
    w("Масса по материалам (слой оболочки из PETG и диффузор света - не в этом файле):")
    for m in MATERIALS:
        n, v, m100, m20 = per_material[m]
        w(f"  {m:4s} {n:2d} деталей: {v:7.1f} см³   100 % {m100:7.1f} г   4 стенки/20 % ~ {m20:7.1f} г")
    w("  ABS: каркас, всё несущее. PA6 (нейлон yxpolyer, не наполненный, чёрный): две направляющие шлангов (горловина защёлкивается на шланге). "
      "PETG: органическая оболочка (organic_frame.py, запасной вариант ABS); диффузор светлой линии из прозрачного PLA. Оболочка не несёт нагрузки и держится "
      "не ближе 10 мм к видеокарте и БП, 4 мм к радиаторам и вентиляторам (в этом файле таких деталей нет).")
    w("")
    w("Крепёж железа (держатель, количество)")
    for f in FASTENERS:
        w(f"  {f['item']:22s} {f['part']:48s} {f['kind']:22s} x{f['count']:<2d} {f['note']}")
    w("")
    sc, cbs = res["screws"], res["counterbores"]
    w("Ведомость винтов M3 (ревизия 12; цилиндрическая головка из набора владельца, шайба под головкой, кроме винтов платы: они на текстолите; вставки M3 в каждом стыке)")
    w(f"  Правило: винт входит во вставку не меньше {hw.SCREW_ENGAGE_MIN:g} мм и не доходит до дна отверстия (глубина {hw.M3_PILOT_DEPTH:g} мм) не меньше {hw.SCREW_BOTTOM_GAP:g} мм; шайба {hw.M3_WASHER_D:g} x {hw.M3_WASHER_T:g} мм, головка {hw.M3_HEAD_D:g} x {hw.M3_HEAD_H:g} мм; "
      f"длина = зажимаемая толщина + шайба + вход. Из подходящих длин берётся та, что дальше от обоих пределов. Количество каждой длины не больше {hw.STOCK_SHARE:g} запаса (запас - числа этикеток наборов, не остаток в коробках).")
    w(f"  {'длина':8s} {'нужно':>6s} {'у владельца':>12s} {'допустимо':>10s}  где")
    for length, (n, items) in sorted(sc["bill"].items()):
        w(f"  M3 x {length:<3d} {n:6d} {hw.M3_SCREW_STOCK[length]:12d} {hw.STOCK_SHARE * hw.M3_SCREW_STOCK[length]:10.0f}  " + ", ".join(f"{k} {c}" for k, c in sorted(items.items())))
    nscrew = sum(n for n, _ in sc["bill"].values())
    w(f"  Всего {nscrew} винтов M3, {sc['washers']} шайб M3 (у владельца {hw.M3_WASHER_STOCK}, допустимо {hw.STOCK_SHARE * hw.M3_WASHER_STOCK:.0f}), "
      f"{sc['inserts']} вставок M3 (у владельца {hw.M3_INSERT_STOCK}, допустимо {hw.STOCK_SHARE * hw.M3_INSERT_STOCK:.0f}): {nscrew} под винты с известной длиной и {sc['inserts'] - nscrew} под винты модуля front_io (PLACEHOLDER, свои).")
    reliefs = [r for r in sc["rows"] if r["relief"] > 0]
    w(f"  Рассверловки под вставкой (диаметр проходного, вставка открыта снизу): {len(reliefs)}" + (": " + ", ".join(f"{r['part']} {r['relief']:.1f} мм" for r in reliefs) if reliefs else " (ни одна длина набора не потребовала)")
      + "; утопленные головки в стыках скелета: 0 (ни один стык не потребовал).")
    t = sc["tightest"]
    if t:
        w(f"  Самый тугой стык: {t['part']}, {t['item']}, M3 x {t['length']} через {t['stack']:g} мм: вход {t['entry']:.2f} мм (нужно >= {hw.SCREW_ENGAGE_MIN:g}), до дна {t['depth'] - t['entry']:.2f} мм (нужно >= {hw.SCREW_BOTTOM_GAP:g}), "
          f"запас до ближайшего предела {t['margin']:.2f} мм; таких стыков с запасом {min(r['margin'] for r in sc['rows']):.2f} мм: {sum(1 for r in sc['rows'] if abs(r['margin'] - t['margin']) < 1e-6)} (все через ребро 16 мм, M3 x 20 - единственная длина набора, которая подходит).")
    w(f"  Штатные винты железа остаются: 6-32 у БП, радиаторов и диска 3.5 дюйма, M3 у платы и диска 2.5 дюйма. Стенка там, где она толще штатного винта, получает зенковку с тыла, под головкой {HW_SCREW_FLOOR:g} мм материала:")
    for nm in ("psu_bulkhead", "visor_arm_right", "visor_arm_left"):
        rr = [r for r in cbs if r[0] == nm]
        if rr:
            w(f"    {nm}: {len(rr)} зенковки Ø{CLEAR_KINDS['6-32cb'][0]:g} (головка 6-32 {hw.UNC6_HEAD_D:g} + {SLED_CB_PLAY:g}), под головкой {min(r[2] for r in rr):.2f} мм, штатный винт {rr[0][3]:g} мм входит {rr[0][4]:.1f} мм")
    w(f"    ПРЕДПОЛОЖЕНИЯ, не измерены: штатный винт БП {hw.PSU_SCREW_LEN:g} мм (\"около 6 мм\") и штатный винт радиатора 360 {hw.RAD360_SCREW_LEN:g} мм (владелец радиатор не измерял); головка 6-32 {hw.UNC6_HEAD_D:g} x {hw.UNC6_HEAD_H:g} мм (как в DRIVE_FORMS).")
    w("")
    w(f"Подпорки GPU: gpu_post (левый торец, рамка с окном для видеовыходов, ревизия 13; M3 x {screw_fit(GPU_POST_STACK)[0]} через beam_mid) + gpu_rest (ревизия 14a: отдельная деталь на верхней грани диагонали правого ребра A, "
      f"плоскость u = {hw.GPU_BS[2]:.1f}; 2 x M3 x {screw_fit(REST_STACK)[0]} вдоль n снизу, головки в зенковках Ø{REST_CB_D:g} глубиной {REST_CB_DEPTH:g} мм).")
    w("")
    w("Намеренные контакты с нулевым зазором, деталь x железо:")
    for a, b in sorted(res["contacts"]):
        tag = "по плану" if (a, b) in INTENDED_CONTACTS else "НЕ в плане"
        w(f"  {a:16s} x {b:11s} {tag}")
    w("")
    w("Контакты деталь x деталь (нулевой зазор, объём пересечения < 1 мм³):")
    for a, b in sorted(res["pp_contact"]):
        w(f"  {a:16s} x {b}" + ("   по плану" if (a, b) in INTENDED_CONTACTS or (b, a) in INTENDED_CONTACTS else ""))
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
    w(f"  Боковые 2 x 140 (ревизия 7, вынесены наружу в ревизии 13): по одному под каждым концом 360, на флангах, дуют НАРУЖУ. Правый X {fr[0]:g}..{fr[1]:g}, левый X {fl[0]:g}..{fl[1]:g}, "
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
      f"gpu post {m['gpu_post']} + rest (контакт {m['gpu_rest']}, винты {m['gpu_rest_screw']}, ревизия 14a), front_io {m['front_io']} (PLACEHOLDER-винты модуля в front_io_carrier), "
      f"винты каретки front_io_carrier в вставки порога {m['front_io_carrier']}, направляющая CPU на углу D левого вентилятора {m['hose_guide_cpu']}, "
      f"органическая оболочка {m['organic']} пилотов M3 под площадки (hw.ORGANIC_PADS), кабельные точки {m['tie_pilot']} пилотов M3 в деталях + {m['tie_bridge']} отверстий в мостиках (TIE_POINTS)   "
      + ("PASS" if not any(f.startswith('CHECK5') for f in res['failures']) else "FAIL"))
    lz = min(z for _, z in res["low"])
    w(f"  6. нижняя точка >= -15: минимум {lz:.2f}                      "
      + ("PASS" if not any(f.startswith('CHECK6') for f in res['failures']) else "FAIL"))
    w(f"  7. (доп.) связность, болты внутри контуров, {res['n_holes']} отверстий: полость пуста и стенка до поверхности "
      f"и до соседних отверстий >= {hw.M3_MIN_WALL:g} мм (вставка M3, проходные M3 и 6-32, зенковки и рассверловки)   "
      + ("PASS" if not any(f.startswith('CHECK7') for f in res['failures']) else "FAIL"))
    ev = res["envelope"]
    w(f"  8. огибающая |X| <= {hw.ENVELOPE_X:g} (ревизия 13: кронштейны боковых вентиляторов до внешней грани вентилятора, |X| <= {hw.ENVELOPE_FAN_X:g}), Y >= {hw.ENVELOPE_Y0:g}: детали без кронштейнов вентиляторов max |X| {ev['parts_rest'][0]:.1f} ({ev['parts_rest'][1]}), "
      f"кронштейны вентиляторов max |X| {ev['parts_fan'][0]:.1f} ({ev['parts_fan'][1]}), "
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
    sc, cbs = res["screws"], res["counterbores"]
    w(f"  15. (доп., ревизия 12) винты M3 владельца: у каждого из {len(sc['rows'])} пилотов со стеком зажатая толщина измерена по телам (проходные отверстия на оси и материал вокруг них, или железо: плата, вентилятор), "
      f"длина из набора (вход >= {hw.SCREW_ENGAGE_MIN:g} мм, до дна >= {hw.SCREW_BOTTOM_GAP:g} мм), шайба Ø{hw.M3_WASHER_D:g} лежит на грани детали целиком, каждая длина не больше {hw.STOCK_SHARE:g} запаса, вставок {sc['inserts']} из {hw.M3_INSERT_STOCK} (не больше {hw.STOCK_SHARE * hw.M3_INSERT_STOCK:.0f}), "
      f"шайб {sc['washers']} из {hw.M3_WASHER_STOCK}   "
      + ("PASS" if not any(f.startswith('CHECK15') for f in res['failures']) else "FAIL"))
    w(f"  16. (доп., ревизия 12) зенковки под штатные винты 6-32: {len(cbs)} (БП {sum(1 for r in cbs if r[0] == 'psu_bulkhead')}, 360 {sum(1 for r in cbs if r[0] != 'psu_bulkhead')}), под головкой измерено {min((r[2] for r in cbs), default=0):.2f}..{max((r[2] for r in cbs), default=0):.2f} мм (нужно {HW_SCREW_FLOOR:g}); "
      f"зенковки M3 под головку и шайбу между печатными деталями (ревизия 14a, после ревью): {len(res['m3_counterbores'])} ("
      + ", ".join(f"{nm} {sum(1 for r in res['m3_counterbores'] if r[0] == nm)}" for nm in sorted({r[0] for r in res['m3_counterbores']}))
      + f"), глубина от грани до дна измерена {min((r[3] for r in res['m3_counterbores']), default=0):.2f}..{max((r[3] for r in res['m3_counterbores']), default=0):.2f} мм "
      f"(нужно не меньше {M3_CB_DEPTH:g}: головка {hw.M3_HEAD_H:g} + шайба {hw.M3_WASHER_T:g} + {M3_CB_SINK:g}), под дном материала "
      + ", ".join(f"{nm} {min(r[4] for r in res['m3_counterbores'] if r[0] == nm):.2f}" for nm in sorted({r[0] for r in res['m3_counterbores']})) + " мм   "
      + ("PASS" if not any(f.startswith('CHECK16') for f in res['failures']) else "FAIL"))
    st = res["strength"]
    w(f"  17. (доп., ревизия 13) кронштейн бокового вентилятора держит удар {KNOCK_N:g} Н вдоль X в дальний угол вентилятора и его вес: наихудшее сечение {st['fan bracket']['knock']:.2f} МПа ("
      f"допустимое {ABS_ALLOW:.2f}), запас {st['fan bracket']['margin']:.2f} (нужно не меньше {STRENGTH_MARGIN_MIN:g})   "
      + ("PASS" if not any(f.startswith('CHECK17') for f in res['failures']) else "FAIL"))
    w(f"  18. (доп., ревизия 13) рамка стойки карты держит тягу кабеля {PULL_N:g} Н вдоль -X на перемычке: наихудшее сечение {st['card post']['worst']:.2f} МПа, запас {st['card post']['margin']:.2f} (нужно не меньше {STRENGTH_MARGIN_MIN:g}), "
      f"прогиб верха {st['card post']['deflection'][0]:.2f}..{st['card post']['deflection'][1]:.2f} мм   "
      + ("PASS" if not any(f.startswith('CHECK18') for f in res['failures']) else "FAIL"))
    gs, cw = res["guide_shadow"], res["carrier"]
    w(f"  19. (доп., ревизия 14a) упор карты gpu_rest держит весь вес карты {CARD_KG:g} кг на контактной грани и удар {KNOCK_N:g} Н вдоль X в кончик пальца: наихудшее сечение {st['gpu_rest']['worst']:.2f} МПа, запас {st['gpu_rest']['margin']:.2f} "
      f"(нужно не меньше {STRENGTH_MARGIN_MIN:g}); растяжение винта до {st['gpu_rest']['tension']:.0f} Н   "
      + ("PASS" if not any(f.startswith('CHECK19') for f in res['failures']) else "FAIL"))
    w(f"  20. (доп., ревизия 14a) модуль front_io в каретке: торцевые блоки {cw['end'][0]:.2f} и {cw['end'][1]:.2f} мм (нужно не меньше {CARRIER_END_MIN:g}), верхняя плита {cw['top']:.2f} мм (нужно не меньше {CARRIER_TOP_MIN:g}), "
      f"зазор за модулем до задней стенки кармана порога {cw['rear']:.2f} мм; модуль может вырасти до того, как придётся менять каретку или порог: влево {cw['grow']['left']:.2f}, вправо {cw['grow']['right']:.2f}, вверх {cw['grow']['top']:.2f}, "
      f"назад {cw['grow']['rear']:.2f}, вперёд {cw['grow']['front']:.2f}, вниз {cw['grow']['bottom']:.2f} мм   "
      + ("PASS" if not any(f.startswith('CHECK20') for f in res['failures']) else "FAIL"))
    w(f"  21. (доп., ревизия 14a) направляющая CPU на левом вентиляторе затеняет в круге Ø{hw.FAN_APERTURE_D:g} за вычетом тени самих шлангов: "
      + ", ".join(f"{a} {v:.0f} мм² (предел {GUIDE_SHADOW_MAX:g}, {100 * v / (math.pi * (hw.FAN_APERTURE_D / 2) ** 2):.1f} % круга)" for a, v in gs) + "   "
      + ("PASS" if not any(f.startswith('CHECK21') for f in res['failures']) else "FAIL"))
    sw = res["sill_wall"]
    w(f"  22. (доп., ревизия 14a, после ревью) задняя стенка порога за карманом: {sw.get('n', 0)} проб вдоль Y через каждые {SILL_WALL_STEP[0]:g} мм по X и {SILL_WALL_STEP[1]:g} мм по Z от пола кармана до потолка, мимо окна; "
      + (f"наименьшая {sw['min'][0]:.2f} мм (X {sw['min'][1]:.1f}, Z {sw['min'][2]:.1f}), нужно не меньше {SILL_WALL_MIN:g}   " if sw else "нет данных   ")
      + ("PASS" if not any(f.startswith('CHECK22') for f in res['failures']) else "FAIL"))
    w("")
    w("Прочность кронштейна бокового вентилятора (ручной расчёт, ревизия 13, п. 5; расчёт - функция bracket_strength(), числа из модели)")
    for ln in st["fan bracket"]["lines"]:
        w(ln)
    w("")
    w("Прочность рамки стойки карты (ручной расчёт, ревизия 13, п. 6; функция post_strength())")
    for ln in st["card post"]["lines"]:
        w(ln)
    w("")
    w("Прочность упора карты gpu_rest (ручной расчёт, ревизия 14a, п. 1; функция rest_strength())")
    for ln in st["gpu_rest"]["lines"]:
        w(ln)
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
        w(f"  Карман (ревизия 14a): снаружи каретки front_io_carrier (X {CARRIER_X[0]:g}..{CARRIER_X[1]:g}, Y {hw.ENVELOPE_Y0:g}..{CARRIER_Y1:g}, Z {CARRIER_Z[0]:g}..{CARRIER_Z[1]:g}) плюс {SILL_POCKET_PLAY:g} мм с боков, сзади и сверху: "
          f"X {exact_box(g['cuts']['pocket'])[0]:g}..{exact_box(g['cuts']['pocket'])[1]:g}, Y до {g['pocket_rear']:g}, потолок Z {g['roof']:g} (до канала светлой линии {solid_distance(g['cuts']['pocket'], g['cuts']['channel']):.2f} мм); открыт спереди и снизу. "
          f"Бокс модуля front_io X {io[0]:g}..{io[1]:g}, Y {io[2]:g}..{io[3]:g}, Z {io[4]:g}..{io[5]:g} (PLACEHOLDER) лежит в каретке, не в пороге: зазор до него за модулем {g['pocket_rear'] - io[3]:.2f} мм, "
          f"задняя стенка порога {SILL_REAR_WALL:.2f} мм (была 5; плоскость Y {g['y_rear']:g} не двигалась). Пилотов модуля в пороге больше нет; 4 пилота M3 под винты каретки в торцевых стенках кармана. Отверстий под порты нет.")
        ls = hw.LIGHT_STRIP_BS
        w(f"  Канал светлой линии: бокс light_strip (X {hw.LIGHT_STRIP_X[0]:g}..{hw.LIGHT_STRIP_X[1]:g}, {hw.LIGHT_STRIP_SECTION[0]:g} x {hw.LIGHT_STRIP_SECTION[1]:g} мм по u, n, "
          f"u {ls[2]:g}..{ls[3]:g}, n {ls[4]:.2f}..{ls[5]:.2f}) плюс {SILL_CHANNEL_PLAY:g} мм, насквозь через оба торца порога (дышит); щель {hw.LIGHT_LINE_W:g} мм от канала к лицу "
          f"(диффузор {hw.LIGHT_DIFFUSER_T:g} мм из прозрачного PLA сядет в неё; посадочного места под диффузор пока нет). Ленка до {hw.LIGHT_STRIP_W_MAX:g} мм стоит на ABS, "
          f"от светодиодов до диффузора не меньше {hw.LIGHT_LED_TO_DIFFUSER_MIN:g} мм (в канале глубиной {hw.LIGHT_STRIP_SECTION[1]:g} мм это держится только при диффузоре в щели стенки, не в канале).")
        w(f"  Крепление к beam_front: {len(SILL_BOLTS)} x M3 x {screw_fit(SILL_STACK)[0]} снизу (проходные Ø{hw.M3_CLEAR_D:g} в beam_front, вставки M3 в нижней грани порога, шайба под головкой), по 2 в каждом концевом блоке: "
          + ", ".join(f"(X {x:g}, Y {y:g})" for x, y in SILL_BOLTS) + ".")
        wx0, wx1, wz0, wz1 = g["window_xz"]
        w(f"  Окно для кабелей в задней стенке (PLACEHOLDER, как модуль): X {wx0:g}..{wx1:g}, Z {wz0:g}..{wz1:g} насквозь через стенку {SILL_REAR_WALL:g} мм (Y {g['y_rear'] - SILL_REAR_WALL:g}..{g['y_rear']:g}), углы R {SILL_WINDOW_R:g}. "
          f"С ревью ревизии 14a это числа самого порога (SILL_WINDOW_X, SILL_WINDOW_Z), не смещения от hw.FRONT_IO_W: окно лежит внутри задней грани модуля-заглушки, а значит и любого модуля, который принимает каретка "
          f"(он может только расти), и кабель, выходящий из задней грани перед окном, проходит в него; проверка 20 валит модуль, задняя грань которого окно не закрывает. Винты модуля и их стенки в окно не попадают. "
          f"Отдельного окна для кабеля светлой линии нет: канал открыт через оба торца порога.")
        w(f"  Задний нижний край порога (Y {g['y_rear']:g}, Z {g['z0']:g}) оставлен острым по всей длине (запись в журнале скруглений): скругление {ROUND_CONVEX:g} мм прорезало плоскость задней стенки кармана "
          f"(стенки не было ниже Z 10.9, меньше 2 мм до Z 12.8), а радиус, оставляющий {SILL_WALL_MIN:g} мм, не больше 0.9 мм, меньше {ROUND_MIN:g}. Стенку меряет проверка 22: наименьшая {res['sill_wall']['min'][0]:.2f} мм.")
        w(f"  Крепления органической оболочки: {len(organic_pilots('front_sill'))} пилота M3 в торцевых гранях (X +-{SILL_HALF_X:g}), см. hw.ORGANIC_PADS.")
        w(f"  Зазоры: до front_io {solid_distance(sl.solid, hardware['front_io']):.2f} мм (за модулем; с боков и сверху между ними каретка), до front_io_carrier {solid_distance(sl.solid, next(q for q in parts if q.name == 'front_io_carrier').solid):.2f} мм, "
          f"до light_strip {solid_distance(sl.solid, hardware['light_strip']):.2f} мм (зазоры кармана и канала по плану, не контакты); beam_front x front_io 0.00 мм: низ модуля стоит на верхней грани балки (контакт по плану: Z 10 у обоих).")
        w("")
    carr = next((q for q in parts if q.name == "front_io_carrier"), None)
    if carr is not None:
        cw = res["carrier"]
        xin0, xin1, zin = carrier_inside()
        w("Каретка front_io_carrier и упор gpu_rest (ревизия 14a)")
        w(f"  Каретка (ABS): перевёрнутая П вокруг модуля, два торцевых блока и верхняя плита, задней стенки нет (кабели модуля выходят через окно порога), открыта спереди, сзади и снизу. "
          f"Снаружи X {CARRIER_X[0]:g}..{CARRIER_X[1]:g}, Y {hw.ENVELOPE_Y0:g}..{CARRIER_Y1:g}, Z {CARRIER_Z[0]:g}..{CARRIER_Z[1]:g} (числа каретки, не модуля: порог следует им); внутри по модулю: X {xin0:g}..{xin1:g} (зазор {CARRIER_PLAY:g}), верх Z {zin:g} (зазор {CARRIER_TOP_PLAY:g}). "
          f"Торцевые блоки {cw['end'][0]:.1f} и {cw['end'][1]:.1f} мм, верхняя плита {cw['top']:.2f} мм (план просил не меньше 3: потолок кармана упирается в канал светлой линии, выше Z {g['roof']:g} нельзя без зазора 2 мм до него). "
          f"Масса: {mass_estimate(carr.solid, carr.material)[1]:.0f} г при 100 %, {mass_estimate(carr.solid, carr.material)[2]:.0f} г при 4 стенках/20 %; порог {mass_estimate(sl.solid, sl.material)[1]:.0f} / {mass_estimate(sl.solid, sl.material)[2]:.0f} г (до ревизии 482 / 205 г).")
        w(f"  Крепления: 2 x {hw.FRONT_IO_SCREW_KIND} модуля (PLACEHOLDER) в торцевые блоки с внутренней грани; 4 x M3 x {screw_fit(CARRIER_STACK)[0]} каретки (по 2 на конец: Y {CARRIER_SCREWS_YZ[0][0]:g} и {CARRIER_SCREWS_YZ[1][0]:g}, Z {CARRIER_SCREWS_YZ[0][1]:g}) "
          f"изнутри в вставки торцевых блоков порога: головка и шайба в зенковке Ø{CARRIER_CB_D:g}, под шайбой {CARRIER_SCREW_FLOOR:g} мм блока и {SILL_POCKET_PLAY:g} мм зазора кармана; отвёртка доходит вдоль X, когда модуля нет. "
          f"Каретка не касается порога и балки (зазоры {SILL_POCKET_PLAY:g} мм) и висит на винтах.")
        w(f"  Модуль может вырасти до того, как придётся менять каретку или порог (проверка 20): по X на {min(cw['grow']['left'], cw['grow']['right']):.2f} мм с каждого конца (торцевой блок не меньше {CARRIER_END_MIN:g}: пилот модуля {hw.M3_PILOT_DEPTH:g} + стенка {hw.M3_MIN_WALL:g}), "
          f"вверх на {cw['grow']['top']:.2f} мм (плита не меньше {CARRIER_TOP_MIN:g}), назад на {cw['grow']['rear']:.2f} мм (до задней стенки кармана); вперёд и вниз на {max(cw['grow']['front'], cw['grow']['bottom']):.1f} мм: плоскость Y = {hw.ENVELOPE_Y0:g} и верх beam_front. "
          f"За этими пределами каретка перестаёт держать стенки (проверка 20), а порог следует её наружному размеру; больше места слева и справа даёт порог (блоки {CARRIER_X[0] - SILL_POCKET_PLAY + SILL_HALF_X:.1f} и {SILL_HALF_X - CARRIER_X[1] - SILL_POCKET_PLAY:.1f} мм).")
        rest = next(q for q in parts if q.name == "gpu_rest")
        rb = bbox_of(rest.solid)
        w(f"  Упор gpu_rest (ABS): капсула шириной {REST_W:g} мм (u {hw.GPU_BS[2] - REST_W:g}..{hw.GPU_BS[2]:g}), контактная грань u = {hw.GPU_BS[2]:g} на n {REST_SEAT_N:g}..{REST_N_AXIS[1]:g} (ось n {REST_N_AXIS[0]:g}..{REST_N_AXIS[1]:g} как у пальца), "
          f"X {REST_X[0]:g}..{REST_X[1]:g} (толщина ребра), стоит на верхней грани диагонали (n {REST_SEAT_N:g}), габарит X {rb[0]:.0f}..{rb[1]:.0f}, Y {rb[2]:.1f}..{rb[3]:.1f}, Z {rb[4]:.1f}..{rb[5]:.1f}; масса {mass_estimate(rest.solid)[1]:.0f} / {mass_estimate(rest.solid)[2]:.0f} г. "
          f"Два винта M3 x {screw_fit(REST_STACK)[0]} вдоль n снизу (u {REST_U - REST_SCREW_DU:g} и {REST_U + REST_SCREW_DU:g}, X {(X_IN + X_OUT) / 2:g}), проходные Ø{hw.M3_CLEAR_D:g} в ребре без прорезей, вставки в упоре, зенковки Ø{REST_CB_D:g} x {REST_CB_DEPTH:g} мм в низу диагонали "
          f"(головка {hw.M3_HEAD_H:g} + шайба {hw.M3_WASHER_T:g} + {M3_CB_SINK:g}, как у каретки; до ревью было 3.0 и головка торчала на 0.5 мм), под шайбой {REST_STACK:g} мм диагонали, винт входит во вставку на {screw_fit(REST_STACK)[1]:.1f} мм.")
        gd = next(q for q in parts if q.name == "hose_guide_cpu")
        gg = guide_cpu_geometry()
        gb = bbox_of(gd.solid)
        tubes = true_tubes()["cpu_hoses"]
        w(f"  Направляющая CPU (PA6) на левом вентиляторе: гребёнка на внутренней грани вентилятора у угла {GUIDE_CPU_CORNER} (u {hw.FAN_SIDE_HOLES_UN[GUIDE_CPU_CORNER][0]:g}, n {hw.FAN_SIDE_HOLES_UN[GUIDE_CPU_CORNER][1]:g}), один M3 x {screw_fit(FAN_STACK)[0]} с внешней грани через вентилятор. "
          f"Каналы центрами в {gg['s'][1]:.1f} мм (шланг 1, u {gg['u'][1]:.1f}) и {gg['s'][0]:.1f} мм (шланг 0, u {gg['u'][0]:.1f}) от оси винта (предел {GUIDE_CPU_REACH:g}); стенка канала до шлангов "
          + " и ".join(f"{solid_distance(gd.solid, t):.2f}" for t in tubes[::-1]) + f" мм; расстояние до вентилятора 0.00 (контакт по плану), габарит X {gb[0]:.1f}..{gb[1]:.1f}, Y {gb[2]:.1f}..{gb[3]:.1f}, Z {gb[4]:.1f}..{gb[5]:.1f}; масса {mass_estimate(gd.solid, 'PA6')[1]:.0f} г / {mass_estimate(gd.solid, 'PA6')[2]:.0f} г. "
          f"Тень в круге вентилятора сверх шлангов {res['guide_shadow'][0][1]:.0f} мм² (предел {GUIDE_SHADOW_MAX:g}). Устья каналов смотрят к плате (+X), от вентилятора. "
          f"С ревью ревизии 14a место каналов берётся из трассы (линия гребёнки идёт от оси винта к ближайшей к ней точке цепочки шланга 1 и дальше до цепочки шланга 0), а каналы - это истинные трубки, "
          f"увеличенные на {GUIDE_PLAY:g} мм и протянутые вдоль цепочек обоих шлангов через всю гребёнку: ни одна точка гребёнки не ближе {GUIDE_PLAY:g} мм к шлангу, где бы трасса ни гнулась.")
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
    "Ревизия 12, всё на M3 (docs/plans/fasteners-m3.md, «Revision 12: spec»). Каждый винт между печатными деталями - M3 с цилиндрической головкой из набора владельца во вставку M3, шайба под головкой (на плате без шайбы: головка на текстолите); "
    "M4 и M4S нет нигде. Виды отверстий: M3 (пилот вставки), M3c (проходное Ø3.4), 6-32c (проходное Ø4.0 для штатных винтов БП, радиаторов, диска 3.5 дюйма; прежнее M3c было общим для M3 и 6-32), M3r (рассверловка под пилотом, диаметр проходного), "
    "6-32cb (зенковка под головку штатного винта 6-32). Hole получил поля stack, washer, item: у пилота записана зажатая толщина, длина винта выбирается screw_fit (из hardware.M3_SCREW_STOCK, из подходящих длин берётся дальше от обоих пределов: вход >= 3.5, до дна >= 0.5). "
    "Проверка 15 измеряет зажатую толщину по телам (проходные отверстия на оси и материал вокруг, или железо: плата, вентилятор) и считает остатки: каждая длина <= 4/5 запаса, вставки <= 176 из 220, шайбы <= 304 из 380. Проверка 16 измеряет дно под зенковками. "
    "Результат: 95 винтов M3 (M3 x 6 9, x 8 11, x 10 12, x 12 2, x 14 6, x 16 6, x 18 4, x 20 30, x 25 6, x 30 5, x 40 4), 86 шайб, 97 вставок M3 (95 под винты с известной длиной и 2 под винты модуля front_io). Рассверловка под вставкой и утопленная головка не понадобились ни в одном стыке "
    "(механизм есть: joint_pilots строит M3r, когда длины набора не хватает, test_checks.py его проверяет).",
    "Ревизия 12, отступления и последствия, каждое измерено. (1) Контуры не менялись. Числа, которые выводились из размеров M4, оставлены числами: BRACKET_EAR 4.9 (ушко кронштейна), полуширина лапки 6.25 (теперь FAN_SIDE_HOLE_D / 2 + TAB_WALL, "
    "FAN_SIDE_HOLE_D = 4.5 - собственное отверстие вентилятора, прежнее M4_CLEAR_D), SLED_FLANGE_HALF_X 7.0. (2) Стенка вокруг проходного отверстия была 2.1 мм (M4), стала 1.6 (M3). (3) СКРУГЛЕНИЕ ПОМЕНЯЛОСЬ САМО: кольца вокруг отверстий "
    "стали меньше (пилот M4 R 2.8 + стенка 2.1 -> M3 R 2.0 + 1.6; четыре мм плоскости вокруг винта считаются от радиуса пилота, 6.8 -> 6.0 мм), поэтому скруглению разрешено больше: детали стали тяжелее на 0.1..1.4 см³ (ребро B +1.4, ребро A +1.2, beam_front +1.1; "
    "общий объём 3089.8 -> 3100.8 см³), острых рёбер на плитах 64 из 156 (было 66). Плечи визора легче на 0.7 и 0.6 см³: зенковки. (4) Первая сборка не прошла CONTACT: у плеча визора (колено, u 294.5, n 88) в 4.0 мм от оси органического пилота шеи; "
    "прежде колено держало кольцо болта соединения M4S (досягаемость 6.8 мм), теперь 6.0, и скругление колена съело 1.34 мм² из 9.08 плоского контакта в пределах 4 мм от этого винта. Исправление: build_arm_right передаёт скруглению оси органических пилотов шеи (hole_rings(holes + neck_pads)); "
    "кольцо этого пилота лежит в X шеи и плеча не касается. Правило не ослаблено. (5) Зенковки под штатные винты: psu_bulkhead (4 шт., с тыла Y 381, Ø7.5, глубина 4.0, под головкой 2.0 мм; винт 6.0 мм входит в БП 4.0 мм) и плечи визора (по 2, снизу, глубина 12.0, под головкой 2.0 мм, в 14 мм плече). "
    "ПРЕДПОЛОЖЕНИЯ: штатные винты 6.0 мм (hardware.PSU_SCREW_LEN, RAD360_SCREW_LEN), головка 6-32 6.7 x 2.5 (UNC6_HEAD_D, UNC6_HEAD_H). Проходное и зенковка стали двумя отверстиями (одно начинается на дне другого), чтобы проверка 7 мерила стенку каждого: "
    "всего отверстий 207, было 199. (6) Пробные точки проверки 5 для БП и 360 стоят в дне под зенковкой (раньше на середине толщины). (7) Угол D правого бокового вентилятора (винт через лапку) по-прежнему без резьбы на дальнем конце, см. «Открыто». "
    "(8) Салазки: отверстия под винты дисков теперь по резьбе диска (3.5 дюйма 6-32c Ø4.0, 2.5 дюйма M3c Ø3.4); зенковки не менялись. (9) beam_mid: торцевые пилоты M4S (5.0 мм) стали M3 (6.7 мм), стенка до проходных отверстий болтов gpu_post держится (проходные Ø4.5 стали Ø3.4); "
    "нахлёст: пилот M4S в 8 мм половине A стал M3 6.7 мм, дна 1.3 мм (было 3.0); печать дна в 1.3 мм из 4 периметров по 0.4 держится, но запаса нет. (10) fit_gauges.py: G1, G2, G3 на UNC6_CLEAR_D, G6 на FAN_SIDE_HOLE_D, C2 только M3 (пилоты 3.8..4.6 и проходные 3.2..3.8 шагом 0.1, ABS).",
    "Ревизия 12, органическая оболочка: материал PETG, запасной вариант ABS. organic_frame.py: PLA_RHO -> LAYER_RHO = 1.27 г/см³, PLA_GAP -> HOT_GAP (зазор 10 мм до карты и БП), толщина площадки PAD_H = hardware.ORGANIC_PAD_H (5.0, то, что зажимает винт); organic_strength.py: E 2000 МПа и 20 МПа поперёк слоёв, цифры ABS из strength.py, "
    "запас 2 как прежде, допустимое 10 МПа (запускает главная сессия, здесь не запускался); drive_access.py: _pla_gap -> _hot_gap, сообщение «it must keep»; shell_concepts.py, render_full.py (LAYER_RGB): комментарии и имена. Ни один элемент оболочки не сдвинут (165 элементов), "
    "но её поле считается вырезанием из каркаса, а каркас чуть другой (скругление, п. 3): объём слоя 1843 -> 1842 см³, крошек 1 -> 0.",
    # --- ревизия 13
    "Ревизия 13 (боковые вентиляторы вынесены наружу, стойка карты рамкой; docs/plans/b6-frame-v0.md), отступления от плана, каждое измерено. (1) Вентиляторы X +-235..+-260 как в плане: левый в 6.40 мм от cpu_hoses (нужно 5, "
    "сдвигать дальше не пришлось), правый в 16.55 мм от gpu_hoses. Радиаторы, шланги, направляющие и 40 мм прямого у портов 420 не тронуты. hardware.py: ENVELOPE_FAN_X = 260 (из FAN_SIDE_X), FAN_SIDE_PARTS и FAN_SIDE_CABLES - "
    "кому позволено выходить за |X| 229; GPU_OUT_ZONE_BS и keep-out gpu_out_zone (v -82..-2, u во всю толщину карты, n 10..100; ДОПУЩЕНИЕ: какая часть планки несёт выходы, не известно, открыта вся грань).",
    "Ревизия 13, кронштейн вентилятора: плита 28 мм, а не 10 (ножка тогда 49 мм, а не 67). Удар плана, 20 Н вдоль X в дальний угол, делится тремя винтами (F_A +22.5, F_B -21.2, F_C -21.2 Н) и даёт на хребет 6 x 10 мм "
    "20.4 МПа, на планку 7.5 x 10 мм 21.1 МПа; ножка 11 x 28, как оценил план, даёт 6.6 МПа, но она не худшее сечение. Плита 28 мм: хребет 2.61, планка 2.22 МПа (допустимое 6.67, запас 2.56; функция bracket_strength(), проверка 17). "
    "Корневой блок u 128..150 (n -47..-33) соединяет планку с ножкой; хребет начинается на n -34, а не -40: на правой стороне при n -40 до gpu_hoses 3.02 мм (нужно 5). Ножка - трапеция (u 116..130 вверху, 116..150 внизу, n -34..-6), а не "
    "прямоугольник: прямоугольник u 116..140 заходит в круг Ø134 вентилятора (проверка 11, 2189 мм³ в тесте), трапеция в 1.9 мм от круга; сечение 672 мм², при ударе 2.23 МПа.",
    "Ревизия 13, кронштейн: строится правосторонним (на месте правого), левый - его зеркало (add_mirror), как все левые детали модуля. План говорит наоборот (правый - зеркало левого); форма та же, но скругление проверяется "
    "по соседям той стороны, где строится, а справа шланги GPU (5.55 мм), то есть там строже. Правый кронштейн в 5.55 мм от gpu_hoses (нужно 5), левый в 24.85 мм от cpu_hoses; левый в 3.00 мм от gpu_out_zone, в 16.3 мм от io_zone. "
    "Ушки A, B, C; угла D нет ни у одного, рельс, коленце и лапка ревизии 7a убраны. Проверка 11: пробный цилиндр круга идёт от внешней грани вентилятора до внешней грани ребра (был 60 мм внутрь от внутренней грани, "
    "что покрывало ножку 12 и 33 мм; сейчас ножка 49), иначе блок у ребра в круге не находился бы.",
    "Ревизия 13, стойка карты (gpu_post): рамка, а не блок. Окно u 75.1..127.1 (вся толщина карты 51 мм и по 0.5 мм) x n 9.5..100.5 (зона n 10..100 и по 0.5 мм; 0.5 мм запаса, а не точно n 10, чтобы не было контакта с keep-out), насквозь по v; "
    "перемычка n 100.5..108 (7.5 мм), верх n 108 = GPU_BRACKET_TAB_N (ЗАГЛУШКА), колонны: низкая u 63.1..75.1 (12 мм), высокая u 127.1..146 (18.9 мм, в ней два болта M3 u 131 и 139, как раньше), плита под окном n -8.35..9.5. "
    "Все размеры из hw.GPU_BS, hw.GPU_OUT_N и hw.GPU_BRACKET_TAB_N. Выше n -5 стойка толще: v -30..-5.5 (24.5 мм), а не -20..-5.5: тяга кабеля 20 Н по плану при 14.5 мм даёт на нижнюю колонну 6.8 МПа (запас 1.0), при 24.5 мм 1.6 (запас 4.2); "
    "утолщение стоит над верхом ребра A (n -6) с зазором 1 мм. Углы окна скруглены R 1 (R 3 заполнил бы угол окна и подошёл бы к зоне на 0.0 мм); внешний угол ступени у beam_mid остаётся острым (иначе контакт теряет больше 3 %). "
    "Жёсткость: прогиб верха под 20 Н 0.13 мм (обе колонны) .. 0.21 мм (одна высокая), 159 .. 97 Н/мм. Растяжение двух болтов M3 в beam_mid при опрокидывании 20 Н на плече 112.6 мм и рычаге 5 мм до ребра опоры около 225 Н на болт: "
    "прочность вставки на вырыв в данных проекта нет, не проверено.",
    "Ревизия 13, проверки и тесты. Проверка 8: предел |X| 260 для кронштейнов вентиляторов, 229 для всего остального (в том числе шлангов); cables.py: то же для проводов вентиляторов. Новые проверки 17 (кронштейн) и 18 (рамка стойки) - "
    "ручной расчёт как функции чисел модели, запас не меньше 2. Новый cad_b6/zone_access.py: io_zone и gpu_out_zone свободны от деталей и кабелей, жгут Ø20 мм выходит из каждой к задней грани (шар R 10 + воксель на сетке 2 мм; "
    "каждый слой сетки непуст). fit_gauges.py G6: ожидаемое число совпавших отверстий выводится из таблицы углов кронштейнов (3 из 4: угол D калибра остаётся без отверстия), прежде 4 (D совпадало с отверстием лапки). "
    "strength.py берёт допустимое напряжение и массу вентилятора из frame_v0.py (числа те же).",
    "Ревизия 13, organic_frame.py: только запущен, слой не перерисован. shell_concepts.X_LIM = ENVELOPE_FAN_X + 20 (сетка до |X| 280, была 252); organic_frame.REAR_BEND_X = 176.5: изгиб заднего свипа был привязан к X вентилятора "
    "(центр - 16 = 176.5) и с вентиляторами на 247.5 уходил на 231.5, где кость пересекала путь отвёртки площадки rear_post_R; X оставлен прежним. Предел слоя |X| 229 (ENVELOPE_X) не менялся: кольца вокруг вентиляторов "
    "(центр X +-247.5) срезаны им целиком, поэтому слой идёт без колец; фланги перерисуют в следующей ревизии. Проверки слоя пройдены: одно тело 1641 см³, 12 площадок, ось винта на оси пилота.",
    # ----- revision 14a -----
    "Ревизия 14a, упор карты gpu_rest. Палец-капсула ушёл из контура rib_A_right (ребро теперь с тем же контуром, что левое; направляющая GPU, рельсовые пилоты и площадки оболочки остались) и стал деталью ABS: капсула шириной "
    f"{REST_W:g} мм, контактная грань u = hw.GPU_BS[2] на n {REST_SEAT_N:g}..{REST_N_AXIS[1]:g}, стоит на верхней грани диагонали (n {REST_SEAT_N:g}), толщина X {X_IN:g}..{X_OUT:g}. Два винта M3 x {screw_fit(REST_STACK)[0]} вдоль n снизу. "
    f"ОТКЛОНЕНИЯ ОТ ПЛАНА: (1) ширина {REST_W:g} вместо 16: удар {KNOCK_N:g} Н вдоль X в кончик изгибает палец 16 мм с запасом 1.93 (меньше 2), при {REST_W:g} мм запас {rest_strength()['margin']:.2f}; лишняя ширина ушла к меньшему u, контактная грань и расстояние до райзера USB-C не изменились; "
    f"(2) головки в зенковках: через всю диагональ {DIAG_W:g} мм ни одна длина набора не подходит под пилот 6.7 мм (M3 x 35 вошёл бы на 6.5 мм при пределе 6.2, а рассверловка под вставкой, которой это требует screw_fit, не проходит проверку 7: стенка 0.29 мм), "
    f"поэтому в низе диагонали зенковки Ø{REST_CB_D:g} x {REST_CB_DEPTH:g} мм, стек {REST_STACK:g} мм, M3 x {screw_fit(REST_STACK)[0]} входит на {screw_fit(REST_STACK)[1]:g} мм; головки на {M3_CB_SINK:g} мм ниже низа ребра (там рельс с мостиками и кабели; до ревью зенковка была 3.0 и головка с шайбой торчала на 0.5); "
    "(3) растяжение винтов: 52 Н на дальний от веса карты и 150 Н от удара, вместе 202 Н на винт (расчёт в проверке 19); прочность вставки в ABS в данных нет. Проверка 5: gpu_rest считается по контакту с картой (1) и по двум винтам (оба тела: пилот в упоре и проходное в ребре); контакт rib_A_right x gpu заменён на gpu_rest x gpu и gpu_rest x rib_A_right.",
    "Ревизия 14a, каретка front_io_carrier. Перевёрнутая П из ABS вокруг бокса модуля: два торцевых блока и верхняя плита, задней стенки нет (кабели выходят в окно порога, задняя стенка порога осталась бы при 2.1 мм), открыта спереди, сзади и снизу. Модуль держат его два винта "
    f"{hw.FRONT_IO_SCREW_KIND} (PLACEHOLDER) в пилотах торцевых блоков; каретку держат 4 x M3 x {screw_fit(CARRIER_STACK)[0]} вдоль X (по 2 на конец) в вставках торцевых блоков порога, головки в зенковках с внутренней стороны. Порог: карман по наружному размеру каретки плюс {SILL_POCKET_PLAY:g} мм, "
    f"2.5 мм зазора за модулем, задняя стенка {SILL_REAR_WALL:.1f} мм (плоскость Y {SILL_Y_REAR:g} не двигалась), пилотов модуля в нём больше нет. ОТКЛОНЕНИЯ ОТ ПЛАНА: (1) верхняя плита {CARRIER_Z[1] - carrier_inside()[2]:.1f} мм, а не 3: потолок кармана "
    f"может подняться не выше Z {CARRIER_Z[1] + SILL_POCKET_PLAY:g} (до канала светлой линии не меньше 2 мм; план называл Z 51.2 до касания канала, зазор 2 мм оставляет 49.2), с зазором {SILL_POCKET_PLAY:g} мм до порога и {CARRIER_TOP_PLAY:g} мм до модуля остаётся 2.7 мм; "
    f"(2) потолок кармана поднялся с Z 46.4 до {CARRIER_Z[1] + SILL_POCKET_PLAY:g}, а кожа лица порога {SILL_FACE_WALL:g} мм над передним верхним краем кармана осталась правилом порога: лицо ушло на {sill_geometry()['n_face'] - 59.04:.2f} мм по n вперёд (n {sill_geometry()['n_face']:.2f} вместо 59.04), "
    "верх порога стал на 1.4 мм выше (Z 81.5 вместо 80.1); органический слой (organic_frame.py читает сечение порога) от этого не сломался, его проверки проходят; (3) каретка висит на винтах над beam_front на 0.3 мм: опирается на балку модуль, не она; "
    f"(4) торцевые блоки порога стали {CARRIER_X[0] - SILL_POCKET_PLAY + SILL_HALF_X:.1f} и {SILL_HALF_X - CARRIER_X[1] - SILL_POCKET_PLAY:.1f} мм (были 69.6 и 44.6), стенки окна, канала, 4 винтов к beam_front и площадок оболочки не затронуты. "
    "Проверка 20 (новая): торцевой блок не тоньше 8.3 мм (пилот модуля 6.7 + стенка 1.6), плита не тоньше 2.5 мм, модуль не глубже кармана: модуль, выросший за каретку, не проходит молча.",
    "Ревизия 14a, направляющая hose_guide_cpu. Гребёнка из PA6 на внутренней грани левого бокового вентилятора у угла D (u 252.25, n 90.25): один M3 x 30 с внешней грани через вентилятор в вставку гребёнки, два канала Ø13 (шланг + 0.6) с устьями к плате (+X), от вентилятора. "
    "С шеи neck_left снята вставка направляющей (шея теперь зеркало neck_right, кроме площадки оболочки neck_top_L, которая не двигалась). ОТКЛОНЕНИЯ ОТ ПЛАНА: (1) канал первого шланга поставлен на вершину его keep-out цепочки (u 235.4), а не в точку (u 239.3, n 75.0) по маршруту: "
    "труба шланга (проверка 10) строится по цепочке из каждой третьей точки маршрута, и от u 240.2, где шланг начинает изгиб, хорда цепочки уходит от маршрута на 0.1 мм и больше, а канал даёт всего 0.3 мм; в точке 239.3 стенка до трубы была бы 0.06 мм (нужно 0.2..0.5). "
    "Отсюда расстояния от оси винта до центров каналов 20.6 и 40.3 мм (в плане 20.0 и 38.8), оба не дальше 45; (2) ось гребёнки идёт через D и вершину цепочки, а не по перпендикуляру к шлангам: 3-4° от ряда D - шланг 1 - шланг 0, поэтому полка не квадратна к шлангу и канал выходит на грань эллипсом (калибр C3 режет полосу вокруг канала и читает радиус по цилиндрической грани); "
    f"(3) тень в круге вентилятора сверх шлангов считает проверка 21 по проекции вдоль X (предел {GUIDE_SHADOW_MAX:g} мм²; число - в строке проверки 21); (4) guide входит в hw.FAN_SIDE_PARTS (|X| до 260), все остальные детали остаются в |X| <= 229; (5) GUIDE_SPEC стал функцией guide_spec() (u каналов считаются по геометрии), "
    "build_neck_right потерял параметр guide_pilot. fit_gauges.py: калибр C3 режет полосу гребёнки вокруг канала шланга 1, проверка C3 читает радиус канала по цилиндрической грани (рёбра-окружности на эллиптических выходах нет); strength.py: каретка не входит в расчётное тело (висит с зазором, не нагружает каркас), масса карты берётся из frame_v0.CARD_KG.",
    "Ревизия 14a, правки после внешнего ревью (17 ноября 2026). (1) Задняя стенка порога: скругление R 6 заднего нижнего края прорезало плоскость задней стенки кармана (стенки не было ниже Z 10.86, меньше 2 мм до Z 12.84); "
    "край оставлен острым по всей длине (запись в журнале скруглений, радиус, сохраняющий 2 мм, не больше 0.9 мм), стенку меряет новая проверка 22 (2.9 мм везде, от пола кармана до потолка). "
    "(2) Окно для кабелей - числа порога (X 40..90, Z 14..46), не смещения от hw.FRONT_IO_W; light_strip больше не следует наивысшей точке модуля (hw.LIGHT_STRIP_N1, те же числа). Модуль, выросший на весь допуск, "
    "не меняет порог; проверка 20 валит модуль, задняя грань которого не закрывает окно. (3) Направляющая CPU: каналы - истинные трубки шлангов + 0.3 мм, протянутые по цепочкам через всю гребёнку; место - ближайшая к оси винта точка шланга 1, "
    "стенка 0.30 и 0.30 мм (было 0.30 и 0.24). (4) Зенковки gpu_rest 3.7 мм (головка + шайба + 0.2, как у каретки; было 3.0, головка торчала на 0.5 мм), M3 x 30 входит на 5.2 мм; все зенковки M3 записаны как отверстия M3cb и меряются проверкой 16.",
]
OPEN_ITEMS: list[str] = [
    "Отсеки под диски: глубина штекера и изгиба кабеля за диском 25 мм (DRIVE_PLUG_ZONE) - ПРЕДПОЛОЖЕНИЕ, источника нет. Головки винтов, нижний предел входа 2.5 дюйма, резиновые втулки (нет размеров), кабели SATA (данные от платы, питание от БП), "
    "задняя органическая панель - не в этом проходе. Салазки весят около 100 г при 100 % и 75 г при 4 стенках и 20 %; устойчивость на ребре 5 x 20 мм скида (диск 3.5 дюйма около 0.7 кг на плече 16 мм от плоскости пластины) и крепление двумя M4 на сдвиг "
    "не считались. Запас прохода в левом отсеке 2° (28° из 30° с зоной штекеров).",
    "Боковые вентиляторы (ревизия 13): оба кронштейна - один проект (правый построен на месте, левый его зеркало), три винта из четырёх (A, B, C с внутренней грани во вставки M3); угла D нет ни у одного, "
    "лапка и планка ревизии 7a убраны. Левый вентилятор в 6.4 мм от шлангов CPU, кронштейн правого в 5.55 мм от шлангов GPU (нужно 5).",
    "Боковые вентиляторы: винты M3 x 30 идут с внешней грани через вентилятор 25 мм (с шайбой) во вставки M3 кронштейна (глубина 6.7 мм, плита 28 мм), 6 штук (3 слева, 3 справа), штатные винты вентиляторов коротки и не нужны. "
    "Прочность кронштейна считана вручную (проверка 17, удар 20 Н и вес), вибрация не считалась. Растяжение болтов M3 крепления ножки к ребру под ударом около 150 Н на болт: прочность вставки на вырыв в данных проекта нет. Кабели вентиляторов проложены (cables.py).",
    "Фронт: передних вентиляторов нет, плоскость Y = 0 теперь задают лапы рёбер A и beam_front, а не вентиляторы; ближайшее железо (угол карты) на Y 7.4, "
    "то есть передние лапы можно было бы убрать назад примерно на 7 мм, если порог Y >= 0 не нужен. Не менялось.",
    "Обслуживание (RAM, блок CPU): откидывать 360 нельзя, шарнира нет (visor_swing.py: с осью за верхней кромкой 360 упирается в 420 через 15-20°, "
    "с осью на внешнем углу нижняя губа проходит через шланги CPU уже на 15°). Порядок: отвернуть 4 болта M3 x 18 (два на сторону, соединение плеча с шеей), "
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
    "Прочность на изгиб после скруглений не считалась. (Ревизия 12: острых рёбер 64 из 156, было 66.)",
    "ПОРОГ И МОДУЛЬ ВВОДА (ревизия 9), всё PLACEHOLDER до обмера модуля Fractal North XL: бокс front_io, два винта M3 в торцевые стенки кармана, положение канала light_strip, шаги портов (таблица в hardware.py, +-1 мм). "
    "Нужно обмерить: плату модуля (контур, толщину), крепёжные отверстия и винты, высоту разъёмов и на сколько они выступают, переключатель и выходит ли колпачок кнопки вместе с модулем, длины четырёх кабелей. "
    "Вырезов под порты в пороге нет: они режутся в коже 5 мм по грани после обмера.",
    "Светлая линия: подключение ленты (заголовок LED платы или 5 В, чтобы горела при включённом ПК) и прокладка кабелей, как и остальные кабели, не сделаны. Посадочного места под диффузор (PLA прозрачный, 1.6 мм, щель 4 мм) нет; "
    "лента клеится на ABS-порог, не на диффузор. Мощность ленты в канале 14 x 14: полный белый может дать 50 °C на поверхности, нужна лента малой мощности или снижение яркости; канал через торцы упирается в рёбра (зазор 2 мм).",
    "Порог: масса 490 г при 100 % (210 г при 4 стенках/20 %), 280 x 47 x 70 мм, длинная ABS-деталь с большой плоской гранью склонна к короблению: если печать повело, делить пополам по X = 0 (каждая половина 140 мм). "
    "Винты порога к beam_front ставятся снизу, зазор до стола 5 мм (собирать до постановки на стол). Порог выступает на 7.4 мм за заднюю грань beam_front (Y 40 -> 47.4), до платы 12.6 мм. "
    "Порог не входит в проверку 12.",
    "PA6 (только две направляющие шлангов; мостики кабелей с 16.11.2026 из ABS, оболочка крепится винтами M3): сушить и печатать из сухой коробки, CFS при 65 % влажности для нейлона не годится; плотность 1.14 г/см³ принята по справочному значению, не по катушке. "
    "Ревизия 12, открыто: (1) вставка M3: наружный диаметр и длина вставок владельца (20 штук и 200 заказанных) не известны, пилот 4.0 x 6.7 со стенкой 1.6 - ПРЕДПОЛОЖЕНИЕ (hardware.M3_PILOT_D, M3_PILOT_DEPTH, M3_MIN_WALL), одно место; "
    "длины винтов выбраны под глубину 6.7, при другой вставке их надо пересчитать (screw_fit), 30 стыков через ребро 16 мм сидят ровно на нижнем пределе входа 3.5 мм (M3 x 20 - единственная длина набора, которая подходит). "
    "(2) Штатные винты 6-32 БП (6.0 мм) и радиатора 360 (6.0 мм) - ПРЕДПОЛОЖЕНИЯ (hardware.PSU_SCREW_LEN, RAD360_SCREW_LEN): владелец винт БП назвал как около 6 мм, винт 360 не измерял; от них зависит только глубина зенковок (под головкой 2.0 мм), "
    "при другой длине зенковку надо пересчитать (HW_SCREW_FLOOR, ARM_T, BULK_T). Головка 6-32 6.7 x 2.5 - тоже предположение (как у винта диска 3.5 дюйма). "
    "(3) Угол D правого бокового вентилятора: винт идёт с внешней грани через лапку (2.5 мм) и вентилятор (25 мм) и заканчивается в воздухе: во вставку ему некуда, внутри кронштейна в этом углу нет (шланги GPU в 4.10 мм). Это было так и с M4; "
    "решение за владельцем: гайка M3 (их около 700) с внутренней стороны вентилятора или два винта вместо трёх (вентилятор держат A и C, проверка 5 требует три из четырёх). В ведомость этот винт не внесён. "
    "(4) Винты 6-32 для вентиляторов 420 (по 6 на половину, 12 штук) и штатные винты 6-32 и M3 дисков и платы в ведомость не входят: они штатные.",
    "Оболочка (PETG, запасной вариант ABS): держать не ближе 10 мм к видеокарте и БП и 4 мм к радиаторам и вентиляторам, нести только свой вес, крепиться к каркасу несколькими точками с зазором (разная усадка ABS и PETG): в этом файле её нет.",
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
