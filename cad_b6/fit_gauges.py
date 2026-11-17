#!/usr/bin/env python3
"""Fit gauges G1..G7 (PLA) and coupons C1..C3 (ABS, PA6): thin test plates built from the model.

Plan: docs/plans/fit-gauges.md. Every hardware number is read from hardware.py, hoses.py and the parts
that frame_v0.build_frame() returns; nothing here changes them. A gauge is a flat plate in its own
frame (x right, y up, z out of the component face, seen from outside, so engraved text reads
correctly), made of strips round the features it tests. Frame.place() puts it where it lies on the
component in the model; the checks use that to compare the gauge with the skeleton's holes and with
the hardware solids.

Run from the repo root:  .venv/bin/python cad_b6/fit_gauges.py [--closeups DIR]
Out: out/gauges/<id>.step and .stl, previews/gauges.png, cad_b6/report_gauges.txt
Exit status 1 when a coincidence check fails (the report says which pair and by how much).
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field

import numpy as np
import cadquery as cq                      # before vtk: with vtk imported first OCC booleans run about 10 times slower
from cadquery import Solid, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import frame_v0 as fv  # noqa: E402
import hardware as hw  # noqa: E402
import hoses  # noqa: E402

OUT_DIR = os.path.join(ROOT, "out", "gauges")
PREVIEW = os.path.join(ROOT, "previews", "gauges.png")
REPORT = os.path.join(HERE, "report_gauges.txt")

# ---------------------------------------------------------------------------
# Numbers of the plan itself (not hardware)
# ---------------------------------------------------------------------------
T = 2.0                      # plate thickness
STRIP = 12.0                 # strip width
ENGRAVE = 0.6                # engraving depth
BED = 290.0                  # largest part
FLOW = 12.0                  # mm3/s for the print-time estimate
PLA_DENSITY = 1.24           # g/cm3 (ABS and PA6 come from frame_v0.DENSITY)
DENSITY = {"PLA": PLA_DENSITY, **fv.DENSITY}
CLEARANCE = 1.0              # slot clearance round a collar or a hose
BRIDGE = 6.0                 # material kept behind a slot so the plate stays one piece
TOL = 0.01                   # coincidence tolerance
NEAR_MISS = 3.0              # a gauge hole this close to a skeleton hole, but not within TOL, is a mismatch
TEXT_SIZES = (4.5, 4.0, 3.5, 3.0)
NOTCH_W, NOTCH_D = 4.0, 6.0  # G4's notch at the PCIe slot line
# coupons (plan, "Coupons")
C1_LEG, C1_HOLE_D, C1_PITCH = 200.0, 4.0, 50.0
C2_BLOCK_T = 8.0             # the plan's block thickness; a pilot deeper than it makes the block thicker (see build_c2)
C2_PITCH, C2_ROW, C2_LABEL_W, C2_HEAD = 10.0, 10.0, 34.0, 9.0
C2_PILOT_STEPS = tuple(round(-0.2 + 0.1 * k, 1) for k in range(9))      # added to the M3 pilot's diameter: 3.8 to 4.6 mm while the pilot is 4.0
C2_CLEAR_STEPS = tuple(round(-0.2 + 0.1 * k, 1) for k in range(7))      # added to the M3 clearance diameter: 3.2 to 3.8 mm while it is 3.4
C2_HORIZ_H, C2_HORIZ_LABEL = 10.0, 8.0
C3_LEN = 20.0                # slice length along the hose


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------
_AXES = {"v": (1.0, 0.0, 0.0), "u": tuple(hw.U_DIR), "n": tuple(hw.N_DIR)}


def axis(name: str) -> Vector:
    sign = -1.0 if name.startswith("-") else 1.0
    return Vector(*[sign * c for c in _AXES[name.lstrip("-")]])


@dataclass
class Frame:
    """origin, x and y axes in world coordinates; z = x cross y points out of the component face."""
    origin: Vector
    ex: Vector
    ey: Vector

    @property
    def ez(self) -> Vector:
        return self.ex.cross(self.ey)

    def world(self, x: float, y: float, z: float = 0.0) -> Vector:
        return self.origin + self.ex * x + self.ey * y + self.ez * z

    def place(self, shape):
        plane = cq.Plane(origin=self.origin.toTuple(), xDir=self.ex.toTuple(), normal=self.ez.toTuple())
        return shape.moved(cq.Location(plane))


def bs_frame(origin_vun, ex: str, ey: str) -> Frame:
    return Frame(Vector(*hw.bp(*origin_vun)), axis(ex), axis(ey))


# ---------------------------------------------------------------------------
# 2D building blocks in the plate frame
# ---------------------------------------------------------------------------
def rect(x0, x1, y0, y1, z0=0.0, z1=T) -> Solid:
    return Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, Vector(x0, y0, z0))


def disc(x, y, r, z0=-1.0, z1=T + 1.0) -> Solid:
    return Solid.makeCylinder(r, z1 - z0, Vector(x, y, z0), Vector(0, 0, 1))


def slot_cut(x, y, r, direction, reach=80.0) -> list:
    """An open-sided slot: a circle of radius r at (x, y) and a bar 2r wide from its centre outwards."""
    dx, dy = direction
    if dx:
        a, b = sorted((x, x + dx * reach))
        bar = rect(a, b, y - r, y + r, -1.0, T + 1.0)
    else:
        a, b = sorted((y, y + dy * reach))
        bar = rect(x - r, x + r, a, b, -1.0, T + 1.0)
    return [disc(x, y, r), bar]


def fuse_rects(rects) -> Solid:
    solids = [rect(*r) for r in rects]
    return solids[0].fuse(*solids[1:]).clean() if len(solids) > 1 else solids[0]


def one_solid(shape, what) -> Solid:
    sols = shape.Solids()
    if len(sols) != 1:
        raise AssertionError(f"{what}: {len(sols)} separate solids, expected 1")
    return sols[0]


def on_strips(rects, x, y, r, wall=1.2) -> bool:
    """The hole (x, y, r) lies inside one strip with at least `wall` of material round it."""
    return any(x0 + r + wall <= x <= x1 - r - wall and y0 + r + wall <= y <= y1 - r - wall for x0, x1, y0, y1 in rects)


def text_cutter(txt, size, x, y, angle=0.0, z_top=T):
    s = (cq.Workplane("XY").workplane(offset=z_top)
         .text(txt, size, -ENGRAVE, combine=False, halign="left", valign="center").val())
    if angle:
        s = s.rotate(Vector(0, 0, 0), Vector(0, 0, 1), angle)
    return s.translate(Vector(x, y, 0))


def arrow_cutter(x, y, angle, length, shaft=2.0, head=6.0, head_len=5.0, z_top=T):
    """Arrow with its tail at (x, y) pointing along `angle` (degrees from +x), engraved ENGRAVE deep."""
    pts = [(0, -shaft / 2), (length - head_len, -shaft / 2), (length - head_len, -head / 2), (length, 0),
           (length - head_len, head / 2), (length - head_len, shaft / 2), (0, shaft / 2)]
    s = (cq.Workplane("XY").workplane(offset=z_top - ENGRAVE).polyline(pts).close().extrude(ENGRAVE).val())
    if angle:
        s = s.rotate(Vector(0, 0, 0), Vector(0, 0, 1), angle)
    return s.translate(Vector(x, y, 0))


def engrave(solid, texts=(), arrows=(), z_top=T):
    """Cut ids and arrows into `solid`. Each text is tried at the sizes of TEXT_SIZES until all of it lies on
    material (the volume removed equals the volume of the tool); failing that is an error, not a silent
    partial id. Returns the solid and a log of what was engraved."""
    log = []
    for txt, x, y, *rest in texts:
        angle = rest[0] if rest else 0.0
        for size in TEXT_SIZES:
            cutter = text_cutter(txt, size, x, y, angle, z_top)
            out = solid.cut(cutter)
            removed = solid.Volume() - out.Volume()
            if removed >= 0.985 * cutter.Volume():
                solid = out
                bb = cutter.BoundingBox()
                log.append(f"'{txt}' size {size:g} mm, {removed:.1f} mm3 engraved, {max(bb.xlen, bb.ylen):.1f} mm long")
                break
        else:
            raise AssertionError(f"text '{txt}' does not fit on the material at {TEXT_SIZES[-1]} mm")
    for x, y, angle, length in arrows:
        cutter = arrow_cutter(x, y, angle, length, z_top=z_top)
        out = solid.cut(cutter)
        removed = solid.Volume() - out.Volume()
        if removed < 0.985 * cutter.Volume():
            raise AssertionError(f"arrow at ({x:.1f}, {y:.1f}) does not lie on material ({removed:.1f} of {cutter.Volume():.1f} mm3)")
        solid = out
        log.append(f"arrow at ({x:.1f}, {y:.1f}) towards {angle:g} deg, {length:g} mm")
    return solid, log


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------
@dataclass
class Item:
    id: str                       # file name stem
    name: str                     # the id engraved on it, as in the plan
    material: str
    solid: object
    frame: Frame | None = None    # where it lies on its component, in world coordinates
    hole_r: tuple = ()            # radii of the mounting holes the coincidence check looks for
    engraving: list = field(default_factory=list)
    checks: list = field(default_factory=list)      # (ok, text)
    notes: list = field(default_factory=list)

    @property
    def ok(self):
        return all(ok for ok, _ in self.checks)


def hole_centres(solid, r):
    """Local (x, y) of every complete circle of radius r in the plate's z = 0 face, read from the built solid."""
    out = []
    for e in solid.Edges():
        if e.geomType() != "CIRCLE" or abs(e.radius() - r) > 1e-6:
            continue
        c = e.arcCenter()
        if abs(c.z) > 1e-6 or (e.startPoint() - e.endPoint()).Length > 1e-6:
            continue
        key = (round(c.x, 6), round(c.y, 6))
        if key not in out:
            out.append(key)
    return sorted(out)


def inside(shape, pt) -> bool:
    return any(sol.isInside(pt) for sol in shape.Solids())


def line_distance(p: Vector, start, d) -> float:
    return (p - Vector(*start)).cross(Vector(*d)).Length


def check_holes(item: Item, holders: list[str], parts_by_name: dict, expect: int, label: str):
    """Every hole of the gauge, read from its solid, against the holes the skeleton's holder parts carry: the
    axis of a skeleton hole parallel to the plate's normal must pass through the gauge hole's centre within
    TOL. A gauge hole with no skeleton hole nearby is listed as not used by the skeleton; one that is
    within NEAR_MISS of a skeleton hole without coinciding is a failure; `expect` holes must coincide."""
    ez = item.frame.ez
    centres = sorted({c for r in item.hole_r for c in hole_centres(item.solid, r)})
    matched, unused, bad = [], [], []
    for (x, y) in centres:
        p = item.frame.world(x, y)
        best = None
        for pn in holders:
            for h in parts_by_name[pn].holes:
                if abs(Vector(*h.d).dot(ez)) < 0.9999:
                    continue
                dist = line_distance(p, h.start, h.d)
                if best is None or dist < best[0]:
                    best = (dist, pn, h)
        pos = f"({x:.2f}, {y:.2f}) = world ({p.x:.3f}, {p.y:.3f}, {p.z:.3f})"
        if best is not None and best[0] <= TOL:
            matched.append((pos, best))
        elif best is not None and best[0] < NEAR_MISS:
            bad.append(f"{label}: gauge hole {pos} misses {best[1]} hole axis by {best[0]:.3f} mm")
        else:
            unused.append(f"{pos}" + ("" if best is None else f", nearest {best[1]} hole axis {best[0]:.1f} mm away"))
    worst = max((m[1][0] for m in matched), default=0.0)
    ok = not bad and len(matched) == expect
    by = {}
    for _, (_, pn, _) in matched:
        by[pn] = by.get(pn, 0) + 1
    text = (f"{len(matched)} of {len(centres)} gauge holes coincide with a hole of {', '.join(holders)} "
            f"(by part {by}; largest offset {worst:.1e} mm, expected {expect})")
    if unused:
        text += "; no skeleton hole at " + "; ".join(unused)
    if bad:
        text += "; " + "; ".join(bad)
    if len(matched) != expect and not bad:
        text += f"; EXPECTED {expect} coinciding holes"
    item.checks.append((ok, text))
    return matched


def check_placed(item: Item, hardware: dict, name: str, touch: bool = True):
    """Placed on its component face in the model, the plate must not enter the component (overlap volume) and, where it lies
    on a face, touch it (distance 0)."""
    placed = item.frame.place(item.solid)
    vol = fv.inter_vol(placed, hardware[name])
    dist = fv.solid_distance(placed, hardware[name])
    ok = vol < fv.VOL_EPS and (dist < TOL if touch else True)
    item.checks.append((ok, f"placed on hw:{name}: overlap {vol:.2f} mm3, distance {dist:.3f} mm"))
    return placed


# ---------------------------------------------------------------------------
# G1, G2: the end of a radiator with its fan screws and its two port collars
# ---------------------------------------------------------------------------
def end_plate(length, width, holes_xy, hole_d, ports_xy, name_text, arrow_xy):
    """x runs from the radiator's end edge inwards, y across it. Two long edge strips carry the screw holes; an end strip
    and a block round the ports carry the two collar slots, which open through the end edge."""
    r_slot = hw.RAD420_PORT_D / 2 + CLEARANCE
    reach = ports_xy[0][0] + r_slot + BRIDGE
    y_lo, y_hi = min(p[1] for p in ports_xy) - r_slot - BRIDGE, max(p[1] for p in ports_xy) + r_slot + BRIDGE
    strips = [(0, length, 0, STRIP), (0, length, width - STRIP, width), (0, STRIP, 0, width), (0, reach, y_lo, y_hi)]
    for (x, y) in holes_xy:
        assert on_strips(strips, x, y, hole_d / 2), f"hole at ({x}, {y}) is not on a strip"
    s = fuse_rects(strips)
    cuts = [disc(x, y, hole_d / 2) for (x, y) in holes_xy]
    for (x, y) in ports_xy:
        cuts += slot_cut(x, y, r_slot, (-1, 0))
    s = one_solid(s.cut(*cuts), name_text)
    text_y = STRIP / 2
    s, log = engrave(s, texts=[(name_text, arrow_xy[0] + 18.0, text_y)],
                     arrows=[(arrow_xy[0], width - STRIP / 2, 180.0, arrow_xy[1])])
    return s, log


def build_g1():
    v0, v1, u_face, _, n0, n1 = hw.RAD420_BS
    frame = bs_frame((v0, u_face, n0), "v", "n")                   # z = v x n = -u: out of the core face
    xs = sorted(hw.RAD420_HOLES_X)[:2]                              # the end fan bay at the port end (ports are at the low-v end)
    holes = [(hw.x_to_v(x) - v0, n - n0) for x in xs for n in hw.RAD420_HOLES_N]
    ports = [hoses.world_to_bs(h["pts"][-1]) for h in hoses.routes()["cpu"][0]]
    ports_xy = [(p[0] - v0, p[2] - n0) for p in ports]
    length = max(h[0] for h in holes) + STRIP / 2
    s, log = end_plate(length, n1 - n0, holes, hw.UNC6_CLEAR_D, ports_xy, "G1 rad420_ports_end", (62.0, 24.0))
    it = Item("G1_rad420_ports_end", "G1 rad420_ports_end", "PLA", s, frame, (hw.UNC6_CLEAR_D / 2,), log)
    it.notes.append(f"port slots from the last points of the CPU hoses: x = {ports_xy[0][0]:.2f} (RAD420_PORT_INSET {hw.RAD420_PORT_INSET}), "
                    f"y = {ports_xy[0][1]:.2f} and {ports_xy[1][1]:.2f}, {ports_xy[1][1] - ports_xy[0][1]:.2f} apart "
                    f"(2 x RAD420_PORT_HALF_SPACING = {2 * hw.RAD420_PORT_HALF_SPACING:.2f}); slot radius {hw.RAD420_PORT_D / 2 + CLEARANCE:g}")
    it.notes.append(f"holes: end edge to first hole column {holes[0][0]:.2f} mm, first column to second {holes[-1][0] - holes[0][0]:.2f} mm, rows {holes[0][1]:.2f} and {holes[1][1]:.2f} from the long edge")
    return it, dict(ports_xy=ports_xy, deltas=(ports_xy[0][0] - hw.RAD420_PORT_INSET, ports_xy[1][1] - ports_xy[0][1] - 2 * hw.RAD420_PORT_HALF_SPACING))


def build_g2():
    v0, v1, u0, u1, n_in, _ = hw.RAD360_BS
    frame = bs_frame((v1, u0, n_in), "-v", "u")                     # x from the end edge inwards (towards -v), z = -v x u = -n: towards the board
    xs = sorted(hw.RAD360_HOLES_X)[-2:]
    holes = sorted((v1 - hw.x_to_v(x), u - u0) for x in xs for u in hw.RAD360_HOLES_U)
    ports = [hoses.world_to_bs(h["pts"][-1]) for h in hoses.routes()["gpu"][0]]
    ports_xy = [(v1 - p[0], p[1] - u0) for p in ports]
    length = max(h[0] for h in holes) + STRIP / 2
    s, log = end_plate(length, u1 - u0, holes, hw.UNC6_CLEAR_D, ports_xy, "G2 rad360_ports_end", (50.0, 24.0))
    it = Item("G2_rad360_ports_end", "G2 rad360_ports_end", "PLA", s, frame, (hw.UNC6_CLEAR_D / 2,), log)
    it.notes.append(f"port slots from the last points of the GPU hoses: x = {ports_xy[0][0]:.2f} (RAD360_PORT_INSET {hw.RAD360_PORT_INSET}), "
                    f"y = {ports_xy[0][1]:.2f} and {ports_xy[1][1]:.2f}, {ports_xy[1][1] - ports_xy[0][1]:.2f} apart "
                    f"(hoses.GPU_PORT_PITCH x 2 = {2 * hoses.GPU_PORT_PITCH:.2f}; the 420's 2 x RAD420_PORT_HALF_SPACING = {2 * hw.RAD420_PORT_HALF_SPACING:.2f}); slot radius {hw.RAD420_PORT_D / 2 + CLEARANCE:g}")
    it.notes.append(f"holes: end edge to first hole column {holes[0][0]:.2f} mm, columns {holes[-1][0] - holes[0][0]:.2f} mm apart, rows {holes[0][1]:.2f} and {holes[1][1]:.2f} from the low-u edge")
    return it, dict(ports_xy=ports_xy, deltas=(ports_xy[0][0] - hw.RAD360_PORT_INSET, ports_xy[1][1] - ports_xy[0][1] - 2 * hw.RAD420_PORT_HALF_SPACING))


# ---------------------------------------------------------------------------
# G3: the PSU's rear face
# ---------------------------------------------------------------------------
def build_g3():
    w, h = hw.PSU_W[1] - hw.PSU_W[0], hw.PSU_W[5] - hw.PSU_W[4]
    frame = Frame(Vector(hw.PSU_W[1], hw.PSU_REAR_Y, hw.PSU_W[4]), Vector(-1, 0, 0), Vector(0, 0, 1))      # seen from behind: x to the right = world -X
    strips = [(0, STRIP, 0, h), (w - STRIP, w, 0, h), (0, w, 0, STRIP), (0, w, h - STRIP, h)]
    d = hw.UNC6_CLEAR_D                                   # 6-32, the clearance the skeleton's own PSU holes use
    for (x, y) in hw.PSU_PATTERN_FACE:
        assert on_strips(strips, x, y, d / 2), f"PSU hole ({x}, {y}) is not on a strip"
    s = fuse_rects(strips)
    s = one_solid(s.cut(*[disc(x, y, d / 2) for (x, y) in hw.PSU_PATTERN_FACE]), "G3")
    s, log = engrave(s, texts=[("G3 psu_rear", 16.0, STRIP / 2)], arrows=[(w - STRIP / 2, 40.0, -90.0, 14.0)])
    it = Item("G3_psu_rear", "G3 psu_rear", "PLA", s, frame, (d / 2,), log)
    it.notes.append(f"outline {w:g} x {h:g} from PSU_W; hole pattern PSU_PATTERN_FACE from the lower-left corner seen from behind; holes at UNC6_CLEAR_D ({d:g}), the 6-32 clearance of psu_bulkhead")
    return it


# ---------------------------------------------------------------------------
# G4: the nine ATX holes, in two plates (one bed cannot hold 305 mm)
# ---------------------------------------------------------------------------
def build_g4(tag, u_lo, u_hi, datum_lo, datum_hi, text_x, arrow_x):
    rows = sorted({u for (_, u) in hw.ATX_HOLES if u_lo < u < u_hi})
    vs = sorted({v for (v, u) in hw.ATX_HOLES if u in rows})
    v_max = max(v for (v, _) in hw.ATX_HOLES) + STRIP / 2
    strips = []
    for i, u in enumerate(rows):          # strips along v through each hole row (they run across the plate's y)
        lo = u_lo if (datum_lo and i == 0) else max(u_lo, u - STRIP / 2)
        hi = u_hi if (datum_hi and i == len(rows) - 1) else min(u_hi, u + STRIP / 2)
        strips.append((lo - u_lo, hi - u_lo, 0, v_max))
    for j, v in enumerate(vs):            # strips along u through each hole column
        strips.append((0, u_hi - u_lo, 0 if j == 0 else v - STRIP / 2, v + STRIP / 2))
    holes = [(u - u_lo, v) for (v, u) in hw.ATX_HOLES if u in rows]
    for (x, y) in holes:
        assert on_strips(strips, x, y, hw.ATX_HOLE_D / 2), f"ATX hole ({x}, {y}) is not on a strip"
    frame = bs_frame((0, u_lo, hw.ATX_BOARD_N), "u", "v")           # x = u, y = v, z = u x v = -n: out of the board's underside
    s = fuse_rects(strips)
    cuts = [disc(x, y, hw.ATX_HOLE_D / 2) for (x, y) in holes]
    notch = None
    if u_lo < hw.GPU_SLOT_U < u_hi:
        notch = hw.GPU_SLOT_U - u_lo
        cuts.append(rect(notch - NOTCH_W / 2, notch + NOTCH_W / 2, -1.0, NOTCH_D, -1.0, T + 1.0))
    s = one_solid(s.cut(*cuts), tag)
    vs_mid = vs[1] if len(vs) > 1 else vs[0]
    s, log = engrave(s, texts=[(tag.split("_", 1)[0] + " " + tag.split("_", 1)[1], text_x, 8.0)],
                     arrows=[(arrow_x, vs_mid + 5.5, -90.0, 11.0)])
    name = tag.replace("_", " ", 1)
    it = Item(tag, name, "PLA", s, frame, (hw.ATX_HOLE_D / 2,), log)
    it.notes.append(f"covers u {u_lo:g}..{u_hi:g}, v 0..{v_max:g}; rows u = {', '.join(f'{r:g}' for r in rows)}")
    if notch is not None:
        it.notes.append(f"notch {NOTCH_W:g} wide, {NOTCH_D:g} deep in the rear edge (v = 0) at u = GPU_SLOT_U = {hw.GPU_SLOT_U} (x = {notch:.2f})")
    return it


# ---------------------------------------------------------------------------
# G5: the CPU block
# ---------------------------------------------------------------------------
def build_g5():
    sv, su = hw.CPU_SOCKET_VU
    r_hole = (2 * hw.CPU_BODY_R + 1.0) / 2                      # the body's diameter plus 1 mm
    r_out = r_hole + STRIP
    frame = bs_frame((sv - r_out, su - r_out, 0.0), "v", "u")   # on the board's component face, seen from above (z = +n)
    c = r_out
    tab = (c + r_hole + 2.0, c + r_hole + 2.0 + 62.0, c - STRIP / 2, c + STRIP / 2)
    s = Solid.makeCylinder(r_out, T, Vector(c, c, 0), Vector(0, 0, 1)).fuse(rect(*tab)).clean()
    lug_half = hw.CPU_LUG_HALF_V + CLEARANCE
    y_lug0 = hw.CPU_LUG_U[0] - CLEARANCE - (su - r_out)
    cuts = [disc(c, c, r_hole), rect(c - lug_half, c + lug_half, y_lug0, c, -1.0, T + 1.0)]
    r_slot = hw.RAD420_PORT_D / 2 + CLEARANCE
    y_collar = hw.CPU_COLLAR_U - (su - r_out)
    slots = []
    for side in (-1, 1):
        slots += slot_cut(c + side * hw.CPU_COLLAR_HALF_SPACING, y_collar, r_slot, (0, -1))
    v_before = one_solid(s.cut(*cuts), "G5 ring").Volume()
    s = one_solid(s.cut(*cuts, *slots), "G5")
    removed_by_slots = v_before - s.Volume()
    s, log = engrave(s, texts=[("G5 cpu_block", tab[0] + 14.0, c)], arrows=[(tab[1] - 7.0, c + 5.0, -90.0, 10.0)])
    it = Item("G5_cpu_block", "G5 cpu_block", "PLA", s, frame, (), log)
    it.notes.append(f"ring hole diameter {2 * r_hole:g} (CPU_BODY_R x 2 + 1), outer {2 * r_out:g}; lug notch {2 * lug_half:g} wide from u {hw.CPU_LUG_U[0] - CLEARANCE:.2f}; "
                    f"collar slots at u {hw.CPU_COLLAR_U}, v {sv:g} +- {hw.CPU_COLLAR_HALF_SPACING}")
    it.notes.append(f"the two collar slots remove {removed_by_slots:.2f} mm3 beyond the lug notch: they lie inside it (collar slot radius {r_slot:g} reaches v +-{hw.CPU_COLLAR_HALF_SPACING + r_slot:g} from the middle, the notch +-{lug_half:g}), "
                    "so they add no geometry; the CPU block's collar diameter is not in hardware.py, the radiator's RAD420_PORT_D is used")
    return it


# ---------------------------------------------------------------------------
# G6: a 140 mm fan
# ---------------------------------------------------------------------------
def build_g6():
    size = hw.FAN_SIDE_U[1] - hw.FAN_SIDE_U[0]
    assert abs(size - (hw.FAN_SIDE_N[1] - hw.FAN_SIDE_N[0])) < 1e-9
    u0, n0 = hw.FAN_SIDE_U[0], hw.FAN_SIDE_N[0]
    name = "fan_side_left"
    frame = bs_frame((hw.x_to_v(hw.FAN_SIDE_INNER_X[name]), u0, n0), "u", "n")      # on the fan's inner face (towards the board): z = u x n = +v = +X
    holes = [(u - u0, n - n0) for (u, n) in hw.FAN_SIDE_HOLES_UN.values()]
    tab = (20.0, size - 20.0, -STRIP, 1.0)
    s = rect(0, size, 0, size).fuse(rect(*tab)).clean()
    d = hw.FAN_SIDE_HOLE_D
    for (x, y) in holes:
        assert on_strips([(0, size, 0, size)], x, y, d / 2), "fan hole is outside the plate"
    cuts = [disc(size / 2, size / 2, hw.FAN_APERTURE_D / 2)] + [disc(x, y, d / 2) for (x, y) in holes]
    s = one_solid(s.cut(*cuts), "G6")
    s, log = engrave(s, texts=[("G6 fan140", 26.0, -STRIP / 2 + 0.5)], arrows=[(size - 26.0, -STRIP / 2 + 0.5, 180.0, 28.0)])
    it = Item("G6_fan140", "G6 fan140", "PLA", s, frame, (d / 2,), log)
    it.notes.append(f"outer {size:g} x {size:g} (FAN_SIDE_U/N), holes at FAN_SIDE_HOLES_UN (pitch {hw.FAN_PITCH}) at FAN_SIDE_HOLE_D {d:g}, open circle {hw.FAN_APERTURE_D:g}; label tab below the plate; arrow towards low u")
    return it


# ---------------------------------------------------------------------------
# G7: the graphics card's end
# ---------------------------------------------------------------------------
def build_g7():
    v_end, u0, u1, n1 = hw.GPU_BS[1], hw.GPU_BS[2], hw.GPU_BS[3], hw.GPU_BS[5]
    w, h = u1 - u0, n1 - hw.GPU_BS[4]
    frame = bs_frame((v_end, u0, hw.GPU_BS[4]), "u", "n")           # on the card's end face, z = u x n = +v
    exits = [hoses.world_to_bs(hh["pts"][0]) for hh in hoses.routes()["gpu"][0]]
    exits_xy = [(e[1] - u0, e[2] - hw.GPU_BS[4]) for e in exits]
    r_slot = hw.GPU_HOSE_R + CLEARANCE
    y_a, y_b = sorted(p[1] for p in exits_xy)
    x_c = exits_xy[0][0]
    bar = (STRIP, w - STRIP, y_a + r_slot, y_b - r_slot)            # keeps the tooth between the two slots attached to the left strip
    strips = [(0, STRIP, 0, h), (w - STRIP, w, 0, h), (0, w, 0, STRIP), (0, w, h - STRIP, h), bar]
    cuts = []
    for (x, y) in exits_xy:
        cuts += slot_cut(x, y, r_slot, (1, 0))
    s = one_solid(fuse_rects(strips).cut(*cuts), "G7")
    s, log = engrave(s, texts=[("G7 gpu_end", STRIP / 2, 24.0, 90.0)], arrows=[(w - STRIP / 2, y_a - r_slot - 2.0, -90.0, 12.0)])
    it = Item("G7_gpu_end", "G7 gpu_end", "PLA", s, frame, (), log)
    it.notes.append(f"outline {w:g} x {h:g} from GPU_BS (u and n); hose exits from the first points of the GPU hoses: u {x_c + u0:.2f}, n {y_a:g} and {y_b:g}; slot radius {r_slot:g} open towards +u; a bar between the slots joins the tooth to the plate")
    return it, exits_xy


# ---------------------------------------------------------------------------
# Coupons
# ---------------------------------------------------------------------------
def build_c1():
    L, w = C1_LEG, STRIP
    s = fuse_rects([(0, L, 0, w), (0, w, 0, L)])
    pos = [w / 2 + C1_PITCH * k for k in range(4)]
    holes = [(x, w / 2) for x in pos] + [(w / 2, y) for y in pos[1:]]
    s = one_solid(s.cut(*[disc(x, y, C1_HOLE_D / 2) for (x, y) in holes]), "C1")
    s, log = engrave(s, texts=[("C1 scale_l", 12.0, w / 2 + 0.0), ("X", 128.0, w / 2), ("Y", w / 2 - 1.5, 128.0)],
                     arrows=[(165.0, w / 2, 0.0, 30.0), (w / 2, 165.0, 90.0, 30.0)])
    it = Item("C1_scale_l", "C1 scale_l", "ABS", s, None, (), log)
    it.notes.append(f"legs {L:g} long, {w:g} wide, {T:g} thick; {len(holes)} holes of {C1_HOLE_D:g} at {C1_PITCH:g} pitch from the corner hole (centres 6, 56, 106, 156 on each leg); print flat, X leg along the bed's X")
    it.holes = holes
    return it


def build_c2():
    """The M3 insert's ladders: a row of pilot diameters (blind, to the pilot's depth) and a row of clearance holes for the M3 screw, round the model's own figures, and a small
    block with the nominal pilot horizontal. The rows hold the steps C2_PILOT_STEPS and C2_CLEAR_STEPS added to hw.M3_PILOT_D and hw.M3_CLEAR_D."""
    dia, depth, _ = hw.INSERTS["M3"]
    rows = [("pilot", dia, C2_PILOT_STEPS, depth), ("clear", hw.M3_CLEAR_D, C2_CLEAR_STEPS, None)]
    floor = C2_BLOCK_T - depth                                 # what the plan leaves under the pilot
    thick = max(C2_BLOCK_T, depth + floor)
    ncols = max(len(steps) for _, _, steps, _ in rows)
    row_h = C2_ROW + C2_HEAD                                   # holes, then the row of diameters over them
    width = C2_LABEL_W + ncols * C2_PITCH
    height = len(rows) * row_h
    block = Solid.makeBox(width, height, thick, Vector(0, 0, 0))
    cuts, texts, marks, specs = [], [], [], []
    for r, (what, nominal, steps, hole_depth) in enumerate(rows):
        y0 = row_h * (len(rows) - 1 - r)
        y = y0 + C2_ROW / 2
        for k, dd in enumerate(steps):
            x = C2_LABEL_W + C2_PITCH * (k + 0.5)
            d_k = nominal + dd
            if hole_depth is not None:                         # pilots: blind, from the top face, to the table's depth
                cuts.append(Solid.makeCylinder(d_k / 2, hole_depth + 1.0, Vector(x, y, thick - hole_depth), Vector(0, 0, 1)))
            else:                                              # clearance holes go through
                cuts.append(Solid.makeCylinder(d_k / 2, thick + 2.0, Vector(x, y, -1.0), Vector(0, 0, 1)))
            specs.append((f"{what} M3", x, y, d_k, hole_depth))
            texts.append((f"{d_k:.1f}", x - 3.0, y0 + C2_ROW + C2_HEAD / 2))
            if abs(dd) < 1e-9:
                marks.append((x, y + 3.9))
        texts.append((f"M3 {what} {nominal:.1f}", 2.0, y))
    block = block.cut(*cuts)
    block, log = engrave(block, texts=texts, z_top=thick)
    tri = []
    for (x, y) in marks:                                       # engraved triangle above the nominal hole of each row
        t = (cq.Workplane("XY").workplane(offset=thick - ENGRAVE).polyline([(-1.4, 0.0), (1.4, 0.0), (0.0, 1.8)]).close().extrude(ENGRAVE + 1.0).val())
        tri.append(t.translate(Vector(x, y, 0)))
    block = block.cut(*tri)
    log.append(f"{len(tri)} nominal-hole triangles")
    # second block: the nominal pilot, axis along +Y, blind from the y = 0 face
    pitch = 12.0
    wx = pitch
    ylen = depth + floor + C2_HORIZ_LABEL
    small = Solid.makeBox(wx, ylen, C2_HORIZ_H, Vector(width + 8.0, 0, 0))
    small = small.cut(Solid.makeCylinder(dia / 2, depth + 1.0, Vector(width + 8.0 + pitch / 2, -1.0, C2_HORIZ_H / 2), Vector(0, 1, 0)))
    specs.append(("horizontal M3", width + 8.0 + pitch / 2, 0.0, dia, depth))
    small, log2 = engrave(small, texts=[("M3", width + 8.0 + pitch / 2 - 4.5, depth + floor + C2_HORIZ_LABEL / 2)], z_top=C2_HORIZ_H)
    solid = cq.Compound.makeCompound([one_solid(block, "C2 block"), one_solid(small, "C2 small block")])
    it = Item("C2_insert_ladder", "C2 insert_ladder", "ABS", solid, None, (), log + log2)
    it.specs = specs
    it.thick = thick
    pil = [dia + dd for dd in C2_PILOT_STEPS]
    clr = [hw.M3_CLEAR_D + dd for dd in C2_CLEAR_STEPS]
    it.notes.append(f"main block {width:g} x {height:g} x {thick:g}: the plan's 8 mm block with the M3 pilot {depth:g} deep (hardware.M3_PILOT_DEPTH, an assumption until the owner gives the insert's length), {floor:g} mm of floor under it")
    it.notes.append(f"rows top to bottom: M3 pilots {pil[0]:.1f} to {pil[-1]:.1f} mm in steps of 0.1 (blind, {depth:g} deep), then M3 clearance holes {clr[0]:.1f} to {clr[-1]:.1f} mm in steps of 0.1 (through); "
                    f"the diameter is engraved over each hole and a triangle marks the nominal one ({dia:g} and {hw.M3_CLEAR_D:g})")
    it.notes.append(f"small block {wx:g} x {ylen:g} x {C2_HORIZ_H:g} at x {width + 8:g}: the nominal pilot along +Y from its y = 0 face; print both blocks flat")
    return it


def build_c3(parts_by_name):
    """The hose clip coupon: the slice of hose_guide_cpu round the channel of the nearer hose (revision 14a: the guide is a comb on the left fan's corner D, its shelves are no longer square to u).
    The slice is the comb's strip across that channel: all of X, 2 x (channel radius + rim) across the hose, C3_LEN along it, cut in a frame at the channel's crossing (x' across the hose, y' along it,
    z' towards the mouth). Printed with the face that lies on the fan down and the channel horizontal, the mouth up."""
    part = parts_by_name["hose_guide_cpu"]
    g = fv.guide_cpu_geometry()
    p, d, _ = fv.hose_at("cpu", 1, g["u"][1])
    d_in = float(hw.FAN_SIDE_IN[fv.GUIDE_CPU_FAN])
    xh = np.array([d_in, 0.0, 0.0])
    w = np.cross(d, xh)
    w /= np.linalg.norm(w)
    loc = cq.Location(cq.Plane(origin=tuple(float(c) for c in p), xDir=tuple(float(c) for c in w), normal=tuple(float(c) for c in xh)))
    r_ch = hw.CPU_HOSE_R + fv.GUIDE_PLAY
    half = r_ch + fv.GUIDE_RIM
    box = Solid.makeBox(2 * half, C3_LEN, 80.0, Vector(-half, -C3_LEN / 2, -40.0)).moved(loc)
    sl = one_solid(part.solid.intersect(box), "C3 slice")
    out = sl.moved(loc.inverse)                                         # x' = across the hose, y' = along it, z' = towards the mouth (+X for the left fan)
    bb = fv.exact_bound_box(out)
    out = out.translate(Vector(-bb.xmin, -bb.ymin, -bb.zmin))
    it = Item("C3_hose_clip", "C3 hose_clip", "PA6", one_solid(out, "C3"), None, (), [])
    it.slice = sl
    it.notes.append(f"slice of hose_guide_cpu: the comb's strip {2 * half:g} across the nearer hose's channel (hose 1, u {g['u'][1]:.1f}) and {C3_LEN:g} along the hose, all of X; the comb itself is only {fv.GUIDE_CPU_W:g} mm wide along the hose; "
                    "turned so the face that lies on the fan is on the bed and the channel horizontal with its mouth up; no engraving (the part's own shape)")
    return it


# ---------------------------------------------------------------------------
# Checks that need the whole model
# ---------------------------------------------------------------------------
def solid_checks(items: dict, parts_by_name: dict, hardware: dict, extra: dict):
    # G1 .. G4, G6: holes against the skeleton, then placement on the component
    g = items
    check_holes(g["G1"], ["antler_left"], parts_by_name, 2 * len(hw.RAD420_HOLES_N), "G1")      # revision 11: the antler takes all four holes of the end fan (two columns, two rows)
    check_placed(g["G1"], hardware, "rad420")
    check_holes(g["G2"], ["visor_arm_right"], parts_by_name, 2, "G2")
    check_placed(g["G2"], hardware, "rad360")
    check_holes(g["G3"], ["psu_bulkhead"], parts_by_name, 4, "G3")
    check_placed(g["G3"], hardware, "psu")
    for k in ("G4a", "G4b"):
        check_holes(g[k], ["beam_low", "beam_mid", "beam_top"], parts_by_name, 6, k)
        check_placed(g[k], hardware, "board")
    # revision 13: both brackets screw to corners A, B and C and none reaches D (the tab of revision 7a is gone), so three of the gauge's four holes must coincide with a pilot of each bracket
    # and the fourth is listed as unused. Each bracket is held to its own table of corners (before, the two were pooled and the count was 4: D coincided with the right tab's hole), so a
    # pilot that is missing or off its fan hole in either of them fails
    for holder in ("fan_bracket_left", "fan_bracket_right"):
        check_holes(g["G6"], [holder], parts_by_name, len(fv.BRACKET_CORNERS[holder]), f"G6 {holder.split('_')[-1]}")
    check_placed(g["G6"], hardware, "fan_side_left")
    # G5: ring and lug against the CPU block solid
    sv, su = hw.CPU_SOCKET_VU
    block = hardware["cpu_block"]
    pts = [("socket axis", hw.bp(sv, su, 10.0))] + [
        (f"collar axis v {sv + s * hw.CPU_COLLAR_HALF_SPACING:g}", hw.bp(sv + s * hw.CPU_COLLAR_HALF_SPACING, hw.CPU_COLLAR_U, 30.0)) for s in (-1, 1)]
    contained = [(name, block.isInside(Vector(*p))) for name, p in pts]
    g["G5"].checks.append((all(i for _, i in contained), "block solid contains " + ", ".join(f"{n}: {i}" for n, i in contained)))
    placed = g["G5"].frame.place(g["G5"].solid)
    vol, dist = fv.inter_vol(placed, block), fv.solid_distance(placed, block)
    want = (hw.CPU_BODY_R * 2 + 1.0) / 2 - hw.CPU_BODY_R
    g["G5"].checks.append((vol < fv.VOL_EPS and abs(dist - want) < 0.05,
                           f"placed on the board round hw:cpu_block: overlap {vol:.2f} mm3, nearest approach {dist:.3f} mm (ring clearance {want:g})"))
    check_placed(g["G5"], hardware, "board")
    # G7: the hose exits lie on the card's end face and on the start face of the GPU hose keep-out
    gpu, hose = hardware["gpu"], hardware["gpu_hoses"]
    rows = []
    for (x, y) in extra["g7_exits"]:
        p = g["G7"].frame.world(x, y)
        vtx = cq.Vertex.makeVertex(p.x, p.y, p.z)
        rows.append((fv.solid_distance(vtx, gpu), fv.solid_distance(vtx, hose)))
    corner_d = max(fv.solid_distance(cq.Vertex.makeVertex(*g["G7"].frame.world(x, y).toTuple()), gpu) for x in (0, fv.exact_box(g["G7"].solid)[1]) for y in (0, fv.exact_box(g["G7"].solid)[3]))
    g["G7"].checks.append((all(a < TOL and b < TOL for a, b in rows) and corner_d < TOL,
                           "slot centres: distance to hw:gpu " + ", ".join(f"{a:.4f}" for a, _ in rows) + " mm, to hw:gpu_hoses " + ", ".join(f"{b:.4f}" for _, b in rows)
                           + f" mm; plate corners to hw:gpu {corner_d:.4f} mm"))
    check_placed(g["G7"], hardware, "gpu")
    # G1 / G2 port positions against the hardware constants (model-internal consistency, reported, not a gauge-skeleton pair)
    for k in ("G1", "G2"):
        d_inset, d_pitch = extra[k.lower()]["deltas"]
        g[k].checks.append((True, f"port slots against hardware.py: inset differs by {d_inset:+.3f} mm, spacing by {d_pitch:+.3f} mm from 2 x RAD420_PORT_HALF_SPACING"))


def coupon_checks(items: dict, parts_by_name: dict):
    c1 = items["C1"]
    cs = hole_centres(c1.solid, C1_HOLE_D / 2)
    bb = fv.exact_bound_box(c1.solid)
    ok = len(cs) == 7 and abs(bb.xlen - C1_LEG) < 1e-6 and abs(bb.ylen - C1_LEG) < 1e-6
    c1.checks.append((ok, f"{len(cs)} holes of {C1_HOLE_D:g}, legs {bb.xlen:.1f} x {bb.ylen:.1f}, X-leg centres {[c[0] for c in cs if abs(c[1] - STRIP / 2) < 1e-6]}"))
    c2 = items["C2"]
    bad = []
    for (what, x, y, dia, depth) in c2.specs:
        horizontal = what.startswith("horizontal")
        if horizontal:
            probe = lambda t: Vector(x, depth + t, C2_HORIZ_H / 2)                 # noqa: E731
            solid = c2.solid
            inside_at_floor, empty_above = inside(solid, probe(+0.05)), not inside(solid, probe(-0.05))
        elif depth is not None:
            probe = lambda t: Vector(x, y, c2.thick - depth + t)                   # noqa: E731
            inside_at_floor, empty_above = inside(c2.solid, probe(-0.05)), not inside(c2.solid, probe(+0.05))
        else:
            inside_at_floor, empty_above = True, not inside(c2.solid, Vector(x, y, c2.thick / 2))
        # radius: the point at the wall of the nominal radius is empty just inside and solid just outside
        r = dia / 2
        z = (C2_HORIZ_H / 2) if horizontal else (c2.thick / 2 if depth is None else c2.thick - depth / 2)
        if horizontal:
            c_in, c_out = Vector(x, depth / 2, z + r - 0.03), Vector(x, depth / 2, z + r + 0.03)
        else:
            c_in, c_out = Vector(x + r - 0.03, y, z), Vector(x + r + 0.03, y, z)
        if inside(c2.solid, c_in) or not inside(c2.solid, c_out) or not inside_at_floor or not empty_above:
            bad.append(f"{what} {dia:.2f}")
    c2.checks.append((not bad, f"{len(c2.specs)} holes probed (diameter and blind depth against hardware.INSERTS and M3_CLEAR_D)" + (f"; FAILED: {bad}" if bad else "")))
    c3 = items["C3"]
    part = parts_by_name["hose_guide_cpu"]
    r_ch = hw.CPU_HOSE_R + fv.GUIDE_PLAY
    # revision 14a: the comb's side faces are not square to the channel, so the channel ends in ellipses and the slice has no circular edge; the channel's radius is read off its cylindrical faces instead
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    cyl_r = sorted({round(BRepAdaptor_Surface(f_.wrapped).Cylinder().Radius(), 4) for f_ in c3.slice.Faces() if f_.geomType() == "CYLINDER"})
    same_vol = abs(c3.solid.Volume() - c3.slice.Volume()) < 1e-3
    c3.checks.append((same_vol and any(abs(r - r_ch) < 1e-3 for r in cyl_r),
                      f"slice volume {c3.slice.Volume():.1f} mm3 (of the part's {part.solid.Volume():.1f}), channel radius in the slice {r_ch:g} = CPU_HOSE_R + GUIDE_PLAY: cylinder radii {cyl_r}; turned copy has the same volume: {same_vol}"))


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def export(item: Item):
    os.makedirs(OUT_DIR, exist_ok=True)
    step = os.path.join(OUT_DIR, item.id + ".step")
    stl = os.path.join(OUT_DIR, item.id + ".stl")
    cq.exporters.export(item.solid, step)
    cq.exporters.export(item.solid, stl, tolerance=0.02, angularTolerance=0.1)
    import trimesh
    m = trimesh.load(stl)
    vol = float(item.solid.Volume())
    item.stl_ok = bool(m.is_watertight) and abs(float(m.volume) - vol) < 0.01 * vol
    item.stl_info = f"STL watertight {m.is_watertight}, mesh volume {m.volume:.1f} vs {vol:.1f} mm3"


def report_lines(items: list[Item]) -> list[str]:
    out = ["Fit gauges: G1..G7 in PLA, C1 and C2 in ABS, C3 in PA6. Plan: docs/plans/fit-gauges.md. Generated by cad_b6/fit_gauges.py.",
           f"Plastic: volume x density at 100 % fill (PLA {PLA_DENSITY}, ABS {fv.ABS_DENSITY}, PA6 {fv.PA6_DENSITY} g/cm3). Print time: volume / {FLOW:g} mm3/s, no travel, no first layers.", ""]
    head = f"{'item':22}{'mat':5}{'bbox x y z (mm)':28}{'vol cm3':>9}{'g':>7}{'min':>6}  checks"
    out += [head, "-" * len(head)]
    for it in items:
        bb = it.bbox
        vol = float(it.solid.Volume())
        g = vol / 1000.0 * DENSITY[it.material]
        out.append(f"{it.id:22}{it.material:5}{f'{bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f}':28}{vol / 1000:9.2f}{g:7.1f}{vol / FLOW / 60:6.0f}  "
                   f"{'PASS' if it.ok else 'FAIL'} ({len(it.checks)})")
    out.append("")
    for it in items:
        out.append(f"{it.id}  ({it.material})")
        for note in it.notes:
            out.append(f"  note: {note}")
        for line in it.engraving:
            out.append(f"  engraved: {line}")
        for ok, text in it.checks:
            out.append(f"  {'ok  ' if ok else 'FAIL'} {text}")
        out.append(f"  {it.stl_info}")
        out.append("")
    return out


def pack(items: list[Item], width=700.0, gap=34.0):
    """Shelf packing of the items' footprints, tallest first. Returns [(item, shape moved flat to its place, (x0, y0, x1, y1))]."""
    boxes = []
    for it in items:
        bb = it.bbox
        boxes.append((it, bb.xlen, bb.ylen, bb))
    boxes.sort(key=lambda t: -t[2])
    placed, x, y, row_h = [], 0.0, 0.0, 0.0
    for it, w, h, bb in boxes:
        if x + w > width and x > 0:
            x, y, row_h = 0.0, y + row_h + gap + 22.0, 0.0
        shape = it.solid.translate(Vector(x - bb.xmin, y - bb.ymin, -bb.zmin))
        placed.append((it, shape, (x, y, x + w, y + h)))
        x += w + gap
        row_h = max(row_h, h)
    return placed


COLORS = {"PLA": (0.45, 0.68, 0.88), "ABS": (0.72, 0.72, 0.70), "PA6": (0.95, 0.62, 0.22)}


def render(placed, path, size_px=2600):
    import render_vtk
    import vtk
    ren = vtk.vtkRenderer()
    ren.SetBackground(1, 1, 1)
    x0 = min(b[0] for _, _, b in placed) - 10
    x1 = max(b[2] for _, _, b in placed) + 60
    y0 = min(b[1] for _, _, b in placed) - 10
    y1 = max(b[3] for _, _, b in placed) + 34
    for it, shape, (a, b, c, d) in placed:
        for act in render_vtk._actors(shape, COLORS[it.material], edge_opacity=0.9):
            ren.AddActor(act)
        t = vtk.vtkBillboardTextActor3D()
        t.SetInput(f"{it.name}\n{it.material}  {c - a:.0f} x {d - b:.0f} x {it.bbox.zlen:.1f} mm")
        t.SetPosition(a, d + 5.0, 0.0)
        t.GetTextProperty().SetFontSize(26)
        t.GetTextProperty().SetColor(0, 0, 0)
        t.GetTextProperty().SetJustificationToLeft()
        t.GetTextProperty().SetVerticalJustificationToBottom()
        ren.AddActor(t)
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    w_px = size_px
    h_px = int(size_px * (y1 - y0) / (x1 - x0))
    win.SetSize(w_px, h_px)
    win.SetMultiSamples(0)
    win.AddRenderer(ren)
    ren.UseFXAAOn()
    cam = ren.GetActiveCamera()
    cam.ParallelProjectionOn()
    cam.SetFocalPoint((x0 + x1) / 2, (y0 + y1) / 2, 0)
    cam.SetPosition((x0 + x1) / 2, (y0 + y1) / 2, 2000)
    cam.SetViewUp(0, 1, 0)
    cam.SetParallelScale((y1 - y0) / 2)
    ren.ResetCameraClippingRange()
    win.Render()
    grab = vtk.vtkWindowToImageFilter()
    grab.SetInput(win)
    grab.Update()
    wr = vtk.vtkPNGWriter()
    wr.SetFileName(path)
    wr.SetInputConnection(grab.GetOutputPort())
    wr.Write()


def main(argv):
    closeups = argv[argv.index("--closeups") + 1] if "--closeups" in argv else None
    parts, _ = fv.build_frame()
    parts_by_name = {p.name: p for p in parts}
    hardware = hw.build_hardware()

    g1, x1 = build_g1()
    g2, x2 = build_g2()
    g7, exits = build_g7()
    named = {"G1": g1, "G2": g2, "G3": build_g3(),
             "G4a": build_g4("G4a_atx_holes_low", 0.0, hw.ATX_ROWS_U[1] + STRIP / 2, True, False, 28.0, 80.0),
             "G4b": build_g4("G4b_atx_holes_high", hw.ATX_ROWS_U[1] - STRIP / 2, hw.BOARD_BS[3], False, True, 20.0, 80.0),
             "G5": build_g5(), "G6": build_g6(), "G7": g7,
             "C1": build_c1(), "C2": build_c2(), "C3": build_c3(parts_by_name)}
    solid_checks(named, parts_by_name, hardware, dict(g1=x1, g2=x2, g7_exits=exits))
    coupon_checks(named, parts_by_name)
    items = list(named.values())
    for it in items:
        bb = it.bbox = fv.exact_bound_box(it.solid)     # from the geometry: after the STL export OCC's BoundingBox() follows the mesh and grows by its deflection
        it.checks.append((max(bb.xlen, bb.ylen) <= BED, f"fits the bed: {bb.xlen:.1f} x {bb.ylen:.1f} mm (limit {BED:g})"))
        export(it)
        it.checks.append((it.stl_ok, it.stl_info))
    lines = report_lines(items)
    with open(REPORT, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    placed = pack(items)
    render(placed, PREVIEW)
    print("->", PREVIEW)
    if closeups:
        os.makedirs(closeups, exist_ok=True)
        for p in placed:
            render([(p[0], p[1], p[2])], os.path.join(closeups, p[0].id + ".png"), size_px=1600)
    failed = [(it.id, text) for it in items for ok, text in it.checks if not ok]
    if failed:
        print("\nFAILED CHECKS")
        for i, t in failed:
            print(f"  {i}: {t}")
        sys.exit(1)
    print("\nAll gauge checks passed.")


if __name__ == "__main__":
    main(sys.argv[1:])
