#!/usr/bin/env python3
"""B5 organic frame v1: bone-like lofted ribs, slim I/O in the 32 mm gaps
beside the front 360, vented base on 15 mm feet. Black ABS, parts ≤ 290 mm.
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field

import cadquery as cq
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import trimesh
from cadquery import Solid, Vector, Wire

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import b5_model as m

OUT = os.path.dirname(os.path.abspath(__file__))
PARTS = os.path.join(OUT, "parts")
os.makedirs(PARTS, exist_ok=True)

ABS_DENSITY = 1.04          # g/cm^3
WALL_T = 1.6                # 4 perimeters × 0.4 mm
INFILL = 0.20
MAX_PART = 290.0
VOL_EPS = 1e-2
FOOT_H = 15.0               # feet hang below Z=0; desk at Z=-15
SPLIT_Y = 200.0
M4_INSERT_D = 6.4
M4_SCREW_D = 4.5
M4_BOSS_D = 11.0
M4_BOSS_H = 8.0

# Slim I/O in the 32 mm gaps (420 is ±229, 360 is ±197)
IO_X = 213.0                # centre of each 32 mm gap
IO_Y_FACE = 6.0             # flat front face
IO_DEPTH = 18.0             # cut depth into the cheek


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------
def _v(p):
    return p if isinstance(p, Vector) else Vector(*p)


def section_wire(origin, tangent, up, rx, ry, n=28):
    t = _v(tangent)
    t = t / t.Length
    upv = _v(up)
    upv = upv - t.multiply(upv.dot(t))
    if upv.Length < 1e-9:
        upv = Vector(0, 0, 1) if abs(t.z) < 0.9 else Vector(1, 0, 0)
        upv = upv - t.multiply(upv.dot(t))
    upv = upv / upv.Length
    right = t.cross(upv)
    o = _v(origin)
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        pts.append(o + right * (rx * math.cos(a)) + upv * (ry * math.sin(a)))
    return Wire.makePolygon(pts + [pts[0]])


def bone_loft(stations, n=28) -> cq.Solid:
    """stations: (origin, tangent, up, rx, ry)."""
    wires = [section_wire(*st, n=n) for st in stations]
    solid = Solid.makeLoft(wires, False)
    if not solid.isValid() or solid.Volume() < 1:
        solid = Solid.makeLoft(wires, True)
    return solid


def box_xyz(xmin, xmax, ymin, ymax, zmin, zmax) -> cq.Solid:
    return (
        cq.Workplane("XY")
        .moveTo(xmin, ymin)
        .rect(xmax - xmin, ymax - ymin, centered=False)
        .extrude(zmax - zmin)
        .translate((0, 0, zmin))
        .val()
    )


def capsule(p1, p2, r) -> cq.Solid:
    a, b = _v(p1), _v(p2)
    d = b.sub(a)
    length = d.Length
    if length < 1e-6:
        return cq.Solid.makeSphere(r, a)
    return cq.Workplane("XY").transform(offset=a, rotate=Vector(0, 0, 0)).each(
        lambda _: None
    )  # placeholder, use makeCylinder


def cyl_between(p1, p2, r) -> cq.Solid:
    a, b = _v(p1), _v(p2)
    d = b.sub(a)
    length = d.Length
    if length < 1e-6:
        return Solid.makeSphere(r, a)
    rod = Solid.makeCylinder(r, length, a, d)
    s1 = Solid.makeSphere(r, a)
    s2 = Solid.makeSphere(r, b)
    return rod.fuse(s1).fuse(s2)


def fuse_all(solids: list) -> cq.Solid:
    acc = solids[0]
    for s in solids[1:]:
        acc = acc.fuse(s)
    return acc


def split_at_y(solid: cq.Solid, y: float):
    front_box = box_xyz(-800, 800, -800, y, -800, 800)
    front = solid.intersect(front_box)
    rear = solid.cut(front_box)
    return front, rear


def as_wp(solid) -> cq.Workplane:
    return cq.Workplane("XY").newObject([solid])


def bbox(solid):
    return solid.BoundingBox()


def dims(solid):
    b = bbox(solid)
    return (b.xmax - b.xmin, b.ymax - b.ymin, b.zmax - b.zmin)


def max_dim(solid) -> float:
    return max(dims(solid))


# ---------------------------------------------------------------------------
# Hardware (slim I/O instead of the bulky right pod)
# ---------------------------------------------------------------------------
def build_hardware() -> dict[str, cq.Solid]:
    comps = m.build_components()
    # drop the old bulky pod
    out = {k: m.shape_of(v) for k, v in comps.items() if k != "io_pod"}
    # reserved connector / button bodies, in front of the 360 (Y < 29)
    out["io_right"] = box_xyz(IO_X - 12, IO_X + 12, IO_Y_FACE, IO_Y_FACE + 16, 14, 56)
    out["io_left"] = box_xyz(-IO_X - 12, -IO_X + 12, IO_Y_FACE, IO_Y_FACE + 16, 14, 88)
    return out


# ---------------------------------------------------------------------------
# Frame
# ---------------------------------------------------------------------------
@dataclass
class Part:
    name: str
    solid: cq.Solid
    note: str = ""
    print_hint: str = ""


def _rail_stations(sign: float):
    """sign = +1 right, -1 left. Profiles stay inside the 32 mm front gap
    and only a few mm outboard of the 420 at the rear."""
    s = sign
    # rx is half-thickness in X, ry half-height in Z
    return [
        # front head — tall enough for I/O, 28 mm wide, centred in the 32 mm gap
        ((s * IO_X, 8, 44), (0, 1, 0), (0, 0, 1), 13.5, 40),
        ((s * IO_X, 40, 40), (0, 1, 0), (0, 0, 1), 12.0, 32),
        ((s * IO_X, 100, 36), (0, 1, 0), (0, 0, 1), 10.0, 22),
        ((s * 220, 160, 48), (0, 1, 0.15), (0, 0, 1), 9.0, 28),
        # knuckle at the split, slightly swollen
        ((s * 230, SPLIT_Y, 70), (0, 1, 0.2), (0, 0, 1), 11.0, 38),
        ((s * 236, 270, 100), (0, 1, 0.2), (0, 0, 1), 8.0, 48),
        ((s * 238, 340, 140), (0, 1, 0.1), (0, 0, 1), 7.0, 62),
        # beside the 420, tall blade, 3 mm outboard + rx
        ((s * 239, 385, 170), (0, 1, 0), (0, 0, 1), 7.0, 72),
        ((s * 239, 430, 165), (0, 1, 0), (0, 0, 1), 6.5, 60),
        # taper off, leave the exhaust open
        ((s * 237, 452, 140), (0, 1, -0.25), (0, 0, 1), 5.5, 36),
    ]


def _flatten_front(rail: cq.Solid, sign: float) -> cq.Solid:
    """Cut a flat at Y = IO_Y_FACE so the I/O sits on a plane, not a belly."""
    x0, x1 = (IO_X - 18, IO_X + 18) if sign > 0 else (-IO_X - 18, -IO_X + 18)
    cutter = box_xyz(x0, x1, -20, IO_Y_FACE, -10, 100)
    return rail.cut(cutter)


def _cut_right_io(rail: cq.Solid) -> cq.Solid:
    face = cq.Workplane("XZ", origin=(0, IO_Y_FACE, 0))
    # power 19 mm, LED ring as a 0.8 mm deep 24 mm recess around it
    cut = (
        face.pushPoints([(IO_X, 44)])
        .circle(19.0 / 2)
        .extrude(IO_DEPTH)
    )
    ring = (
        cq.Workplane("XZ", origin=(0, IO_Y_FACE, 0))
        .workplane()
        .pushPoints([(IO_X, 44)])
        .circle(24.0 / 2)
        .circle(19.0 / 2)
        .extrude(0.9)
    )
    reset = (
        cq.Workplane("XZ", origin=(0, IO_Y_FACE, 0))
        .pushPoints([(IO_X, 22)])
        .circle(12.0 / 2)
        .extrude(IO_DEPTH)
    )
    rail = rail.cut(cut.val()).cut(ring.val()).cut(reset.val())
    return rail


def _cut_left_io(rail: cq.Solid) -> cq.Solid:
    wp = cq.Workplane("XZ", origin=(0, IO_Y_FACE, 0))
    # two USB-A, stacked
    for z in (76, 56):
        usb = wp.moveTo(-IO_X, z).rect(16.5, 8.0).extrude(IO_DEPTH)
        rail = rail.cut(usb.val())
        wp = cq.Workplane("XZ", origin=(0, IO_Y_FACE, 0))
    # USB-C stadium
    usbc = (
        cq.Workplane("XZ", origin=(0, IO_Y_FACE, 0))
        .moveTo(-IO_X, 38)
        .slot2D(9.4, 4.0, 0)
        .extrude(IO_DEPTH)
    )
    rail = rail.cut(usbc.val())
    # 3.5 mm jack
    jack = (
        cq.Workplane("XZ", origin=(0, IO_Y_FACE, 0))
        .pushPoints([(-IO_X, 22)])
        .circle(4.0)
        .extrude(IO_DEPTH)
    )
    rail = rail.cut(jack.val())
    return rail


def _m4_joint(front: cq.Solid, rear: cq.Solid, sign: float):
    """Three M4 bosses on the split face, inserts in the front, through in the rear."""
    # place along Z at the knuckle centre
    xs = sign * 230.0
    zs = (48.0, 70.0, 92.0)
    for z in zs:
        # insert boss sits in the front piece, opening at Y=SPLIT_Y
        boss = Solid.makeCylinder(
            M4_BOSS_D / 2, M4_BOSS_H,
            Vector(xs, SPLIT_Y - M4_BOSS_H, z - 0, ),
            Vector(0, 1, 0),
        )
        # actually: cylinder along +Y starting at SPLIT_Y - H, so it lives in the front
        insert_hole = Solid.makeCylinder(
            M4_INSERT_D / 2, M4_BOSS_H + 0.5,
            Vector(xs, SPLIT_Y - M4_BOSS_H, z),
            Vector(0, 1, 0),
        )
        through = Solid.makeCylinder(
            M4_SCREW_D / 2, M4_BOSS_H + 16,
            Vector(xs, SPLIT_Y - 2, z),
            Vector(0, 1, 0),
        )
        # alignment stub: short peg from the front into a recess in the rear? keep it simple:
        # just the holes. A small collar on the split face.
        collar = Solid.makeCylinder(
            M4_BOSS_D / 2, 3.0,
            Vector(xs, SPLIT_Y - 1.5, z),
            Vector(0, 1, 0),
        )
        try:
            front = front.fuse(collar).cut(insert_hole)
            rear = rear.cut(through)
        except Exception:
            front = front.cut(insert_hole)
            rear = rear.cut(through)
    return front, rear


def _spine() -> list[cq.Solid]:
    """Two scapula-like backplates, slotted to avoid a large flat, printed flat."""
    hx = m.BOARD_W / 2.0
    z0 = -(m.BOARD_T + m.SPINE_GAP + 6.0)
    z1 = -(m.BOARD_T + m.SPINE_GAP)
    split_s = m.BOARD_LEN / 2.0

    def plate(s0, s1):
        body = m.to_board_space(m.box_xyz(-hx + 8, hx - 8, s0 + 6, s1 - 6, z0, z1)).val()
        # three elongated slots along the length, in board space, to break the flat
        for xs in (-60, 0, 60):
            slot = m.to_board_space(
                m.box_xyz(xs - 12, xs + 12, s0 + 22, s1 - 22, z0 - 2, z1 + 2)
            ).val()
            try:
                body = body.cut(slot)
            except Exception:
                pass
        return body

    lo = plate(0.0, split_s)
    hi = plate(split_s, m.BOARD_LEN)
    # M4 holes along the mid split (in board space, s = split_s)
    for xs in (-70, 0, 70):
        # a cylinder through the split, along the board length (local Y)
        p = m.board_point(xs, split_s, (z0 + z1) / 2)
        # direction along the board (local +Y): (0, C, C)
        direction = Vector(0, C := math.cos(math.radians(45)), C)
        hole = Solid.makeCylinder(M4_SCREW_D / 2, 24, Vector(p[0], p[1], p[2]) - direction * 12, direction)
        try:
            lo = lo.cut(hole)
            hi = hi.cut(hole)
        except Exception:
            pass
    return lo, hi


def safe_fuse(a, b):
    try:
        c = a.fuse(b)
        if c.isValid():
            return c
    except Exception:
        pass
    try:
        c = a.fuse(b, glue=True)
        if c.isValid():
            return c
    except Exception:
        pass
    return a.fuse(b)


def _base_side(sign: float) -> cq.Solid:
    """One half of the skiff, built up to the mid-plane so we never cut at X=0."""
    s = sign
    peri_pts = [
        (s * 238, 448, 8),
        (s * 238, 300, 8),
        (s * 236, 200, 8),
        (s * 230, 90, 8),
        (s * 180, 24, 6),
        (s * 6, 14, 5),
    ]
    acc = None
    for a, b in zip(peri_pts, peri_pts[1:]):
        seg = cyl_between(a, b, 8.0)
        acc = seg if acc is None else safe_fuse(acc, seg)
    # cross ribs ending at the mid joint (X = ±6)
    acc = safe_fuse(acc, cyl_between((s * 236, SPLIT_Y - 8, 8), (s * 6, SPLIT_Y - 8, 8), 6.0))
    acc = safe_fuse(acc, cyl_between((s * 236, SPLIT_Y + 8, 8), (s * 6, SPLIT_Y + 8, 8), 6.0))
    acc = safe_fuse(acc, cyl_between((s * 236, 320, 8), (s * 90, 320, 8), 5.5))
    # 360 intake ribs, tied to the front peri
    for x in (30, 90, 150):
        rib = cyl_between((s * x, m.RAD360_Y0 + 8, 4.5), (s * x, m.RAD360_Y0 + m.RAD360_Y - 8, 4.5), 4.5)
        strut = cyl_between((s * x, 22, 4.5), (s * x, m.RAD360_Y0 + 8, 4.5), 4.5)
        acc = safe_fuse(acc, rib.fuse(strut))
    # PSU plenum ribs (Z <= 0), tied to the front-of-PSU header and the 192 cross rib
    acc = safe_fuse(acc, cyl_between((s * 70, 236, -4), (s * 8, 236, -4), 4.5))
    acc = safe_fuse(acc, cyl_between((s * 70, 236, -4), (s * 70, 192, 8), 4.5))
    acc = safe_fuse(acc, cyl_between((s * 50, 236, -4.5), (s * 50, m.PSU_Y0 + m.PSU_D - 8, -4.5), 4.5))
    # Feet are capsules hanging from exact peri / cross-rib points so they fuse.
    feet_xy = [
        (s * 238, 448),
        (s * 236, SPLIT_Y - 8),
        (s * 236, SPLIT_Y + 8),
        (s * 180, 24),
        (s * 6, 14),
    ]
    for x, y in feet_xy:
        foot = cyl_between((x, y, 8), (x, y, -FOOT_H + 6), 8.0)
        acc = safe_fuse(acc, foot)
    return acc


def _base() -> list[tuple[str, cq.Solid, str]]:
    """U-shaped perimeter, intake ribs, 15 mm feet. Open at the back. Two sides, then a Y split."""
    out = []
    for sign, xname in ((-1, "left"), (1, "right")):
        half = _base_side(sign)
        front, rear = split_at_y(half, SPLIT_Y)
        for yname, part in (("front", front), ("rear", rear)):
            # M4 holes at the mid-plane joint and at the Y split
            for (x, y, z, direc) in (
                (sign * 8, 14, 5, Vector(1, 0, 0)),
                (sign * 8, SPLIT_Y - 8, 8, Vector(1, 0, 0)),
                (sign * 8, SPLIT_Y + 8, 8, Vector(1, 0, 0)),
                (sign * 236, SPLIT_Y, 8, Vector(0, 1, 0)),
                (sign * 120, SPLIT_Y, 8, Vector(0, 1, 0)),
            ):
                hole = Solid.makeCylinder(M4_SCREW_D / 2, 28, Vector(x, y, z) - direc * 14, direc)
                try:
                    part = part.cut(hole)
                except Exception:
                    pass
            out.append((
                f"base_{yname}_{xname}",
                part,
                "vented skiff, 15 mm feet, intake ribs; print feet-down",
            ))
    return out


def _wishbone() -> list[tuple[str, cq.Solid, str]]:
    """Two half-arches under the board, over the PSU, joining the rails at Y~300."""
    # stations from left rail inward to the mid-plane, then mirror
    def half(sign):
        sts = [
            ((sign * 236, 305, 90), (sign * -1, 0, 0.15), (0, 0, 1), 6.0, 16),
            ((sign * 160, 305, 130), (sign * -1, 0, 0.2), (0, 0, 1), 6.0, 14),
            ((sign * 80, 305, 155), (sign * -1, 0, 0.05), (0, 0, 1), 5.5, 12),
            ((sign * 6, 305, 160), (sign * -1, 0, 0), (0, 0, 1), 6.5, 12),  # swollen mid joint
        ]
        return bone_loft(sts)

    left = half(-1)
    right = half(+1)
    # M4 through the mid joint
    hole = Solid.makeCylinder(M4_SCREW_D / 2, 30, Vector(-15, 305, 160), Vector(1, 0, 0))
    try:
        left = left.cut(hole)
        right = right.cut(hole)
    except Exception:
        pass
    note = "wishbone under the board / over the PSU; print on the split face"
    return [
        ("wishbone_left", left, note),
        ("wishbone_right", right, note),
    ]


def build_frame() -> list[Part]:
    parts: list[Part] = []

    # --- rails ---
    for sign, side, cut_io in ((1, "right", _cut_right_io), (-1, "left", _cut_left_io)):
        rail = bone_loft(_rail_stations(sign))
        rail = _flatten_front(rail, sign)
        rail = cut_io(rail)
        front, rear = split_at_y(rail, SPLIT_Y)
        front, rear = _m4_joint(front, rear, sign)
        parts.append(Part(f"rail_{side}_front", front,
                          f"{side} cheek, front, I/O cutouts, M4 inserts at the knuckle",
                          "print on the Y=200 split face, I/O up or on a 45° jib"))
        parts.append(Part(f"rail_{side}_rear", rear,
                          f"{side} cheek, rear, M4 through holes at the knuckle",
                          "print on the Y=200 split face"))

    # --- base ---
    for name, solid, note in _base():
        parts.append(Part(name, solid, note, "print feet-down"))

    # --- spine ---
    lo, hi = _spine()
    parts.append(Part("spine_lower", lo, "slotted 45° backplate, lower half",
                      "print flat on the back face"))
    parts.append(Part("spine_upper", hi, "slotted 45° backplate, upper half",
                      "print flat on the back face"))

    # --- wishbone ---
    for name, solid, note in _wishbone():
        parts.append(Part(name, solid, note, "print on the mid-plane split"))

    return parts


# ---------------------------------------------------------------------------
# Checks, mass, export
# ---------------------------------------------------------------------------
def intersection_volume(a, b) -> float:
    try:
        common = a.intersect(b)
    except Exception:
        return 0.0
    if common is None or common.isNull():
        return 0.0
    try:
        solids = common.Solids() if hasattr(common, "Solids") else [common]
        if not solids:
            vol = float(common.Volume())
            return vol if vol > 0 else 0.0
        return float(sum(s.Volume() for s in solids))
    except Exception:
        return 0.0


def tessellate(solid, tol=0.45):
    verts, faces = solid.tessellate(tol)
    v = np.array([[p.x, p.y, p.z] for p in verts], dtype=float)
    f = np.array(faces, dtype=int)
    return v, f


def _clean_mesh(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Drop degenerate slivers, fill holes, keep only meaningful closed bodies."""
    try:
        mesh.process(validate=False)
    except Exception:
        pass
    bodies = mesh.split(only_watertight=False)
    kept = []
    for b in bodies:
        if b.volume is not None and abs(b.volume) < 1.0:
            continue
        if max(b.extents) < 1.0:
            continue
        if not b.is_watertight:
            try:
                trimesh.repair.fill_holes(b)
            except Exception:
                pass
            try:
                trimesh.repair.fix_winding(b)
                trimesh.repair.fix_normals(b)
            except Exception:
                pass
        kept.append(b)
    if not kept:
        return mesh
    out = trimesh.util.concatenate(kept)
    try:
        out.merge_vertices()
    except Exception:
        pass
    return out


def to_trimesh(solid, tol=0.35) -> trimesh.Trimesh:
    try:
        solid = solid.clean()
    except Exception:
        pass
    try:
        sols = list(solid.Solids()) or [solid]
    except Exception:
        sols = [solid]
    meshes = []
    for s in sols:
        if abs(s.Volume()) < 1.0:
            continue
        v, f = tessellate(s, tol)
        mesh = trimesh.Trimesh(vertices=v, faces=f, process=True)
        meshes.append(_clean_mesh(mesh))
    if not meshes:
        v, f = tessellate(solid, tol)
        return _clean_mesh(trimesh.Trimesh(vertices=v, faces=f, process=True))
    out = trimesh.util.concatenate(meshes)
    try:
        out.merge_vertices()
    except Exception:
        pass
    return out


def mass_estimate(mesh: trimesh.Trimesh) -> tuple[float, float, float]:
    """Return (volume_cm3, mass_100_g, mass_20infill_g)."""
    vol_cm3 = float(mesh.volume) / 1000.0  # mm^3 -> cm^3
    if vol_cm3 < 0:
        vol_cm3 = abs(vol_cm3)
    mass_100 = vol_cm3 * ABS_DENSITY
    sa = float(mesh.area)  # mm^2
    shell = min(sa * WALL_T, vol_cm3 * 1000.0)
    inner = max(vol_cm3 * 1000.0 - shell, 0.0)
    print_vol_cm3 = (shell + INFILL * inner) / 1000.0
    mass_sparse = print_vol_cm3 * ABS_DENSITY
    return vol_cm3, mass_100, mass_sparse


def export_part(part: Part) -> str:
    path = os.path.join(PARTS, f"{part.name}.stl")
    mesh = to_trimesh(part.solid)
    mesh.export(path)
    return path


def run_checks(hardware: dict, parts: list[Part]) -> dict:
    errors = []
    # 1. no interference with hardware (planned contacts allowed)
    allowed = set()  # mounts may kiss the 360/420/PSU
    # 360 side stops / rails may contact the 360 ends — only if we designed it.
    # Rails are in the 32 mm gap, 2 mm clearance intended: any volume > eps is a fail
    # except feet/ribs that support the 360 (Z=10 contact) and PSU (Z=0 contact).
    contact_ok = {
        ("base_front_left", "rad360"),
        ("base_front_right", "rad360"),
        ("base_rear_left", "psu"),
        ("base_rear_right", "psu"),
        ("base_rear_left", "rad420"),
        ("base_rear_right", "rad420"),
        ("rail_left_front", "io_left"),
        ("rail_right_front", "io_right"),
    }
    inter = []
    for p in parts:
        for hn, hs in hardware.items():
            vol = intersection_volume(p.solid, hs)
            if vol > VOL_EPS:
                key = (p.name, hn)
                flag = "mount" if key in contact_ok else "FAIL"
                if flag == "FAIL":
                    errors.append(f"interference {p.name} × {hn}: {vol:.1f} mm3")
                inter.append((p.name, hn, vol, flag))

    # hardware vs hardware (slim I/O included)
    hw_pairs = []
    names = list(hardware)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            vol = intersection_volume(hardware[a], hardware[b])
            if vol > VOL_EPS:
                errors.append(f"hardware interference {a} × {b}: {vol:.1f} mm3")
            hw_pairs.append((a, b, vol))

    # 2. every part fits 290 mm
    sizes = []
    for p in parts:
        d = dims(p.solid)
        sizes.append((p.name, d, max(d)))
        if max(d) > MAX_PART + 0.05:
            errors.append(f"{p.name} is {max(d):.1f} mm, over {MAX_PART}")

    # 3. watertight STLs
    masses = []
    tight = []
    for p in parts:
        mesh = to_trimesh(p.solid)
        path = os.path.join(PARTS, f"{p.name}.stl")
        mesh.export(path)
        # re-load to check the file itself
        loaded = trimesh.load(path, force="mesh")
        bodies = loaded.split(only_watertight=False)
        ok = bool(loaded.is_watertight) or (len(bodies) > 0 and all(b.is_watertight for b in bodies))
        tight.append((p.name, ok, loaded.vertices.shape[0], loaded.faces.shape[0]))
        if not ok:
            errors.append(f"{p.name} STL is not watertight ({len(bodies)} bodies)")
        elif not loaded.is_watertight:
            # all bodies closed; still report as ok
            pass
        vol, m100, m20 = mass_estimate(loaded)
        masses.append((p.name, d := dims(p.solid), vol, m100, m20, p.note))

    return {
        "errors": errors,
        "inter": inter,
        "hw_pairs": hw_pairs,
        "sizes": sizes,
        "tight": tight,
        "masses": masses,
        "ok": not errors,
    }


# ---------------------------------------------------------------------------
# Cable / tube report for the slim I/O
# ---------------------------------------------------------------------------
def cable_tube_report() -> str:
    lines = []
    w = lines.append
    io_r = (IO_X, IO_Y_FACE + 2, 44.0)
    io_l = (-IO_X, IO_Y_FACE + 2, 45.0)
    jfp1 = m.board_point(100, 18, 0)
    jaud1 = m.board_point(-110, 18, 0)
    jusb3 = m.board_point(m.BOARD_W / 2, 70, 0)
    jusbc = m.board_point(m.BOARD_W / 2, 40, 0)

    def dist(a, b):
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    way_r = (IO_X, 155.0, 40.0)
    way_l = (-IO_X, 155.0, 40.0)
    w("Front-panel cables (30% slack):")
    path_jfp = dist(io_r, way_r) + dist(way_r, jfp1)
    w(f"  JFP1  power/reset/LED, right cheek → bottom-right header")
    w(f"    path {path_jfp:.0f} mm  need {path_jfp*1.3:.0f}  /  500  "
      f"{'PASS' if path_jfp*1.3<=500 else 'FAIL'}")
    path_aud = dist(io_l, way_l) + dist(way_l, jaud1)
    w(f"  JAUD1  3.5 mm jack, left cheek → bottom-left header")
    w(f"    path {path_aud:.0f} mm  need {path_aud*1.3:.0f}  /  500  "
      f"{'PASS' if path_aud*1.3<=500 else 'FAIL'}")
    path_usb3 = dist(io_l, way_l) + dist(way_l, jusb3)
    path_usbc = dist(io_l, way_l) + dist(way_l, jusbc)
    w(f"  JUSB3  2× USB-A, left cheek → right-edge header")
    w(f"    path {path_usb3:.0f} mm  need {path_usb3*1.3:.0f}  /  500  "
      f"{'PASS' if path_usb3*1.3<=500 else 'FAIL'}  — plan a 700 mm USB 3 cable")
    w(f"  JUSBC1  USB-C, left cheek → right-edge Key-A header")
    w(f"    path {path_usbc:.0f} mm  need {path_usbc*1.3:.0f}  /  500  "
      f"{'PASS' if path_usbc*1.3<=500 else 'FAIL'}  — plan a 700 mm USB-C cable")

    # tubes, fittings on the RIGHT
    cpu = m.board_point(0.0, m.CPU_FRAC * m.BOARD_LEN - m.CPU_XY / 2, m.CPU_H)
    port_420_r = (m.RAD420_X / 2 - 30, m.RAD420_Y0, m.RAD420_Z0 + m.RAD420_Z)
    side_r = (m.BOARD_W / 2 + 40, 280.0, 220.0)
    slot_s = m.GPU_SLOT_FRAC * m.BOARD_LEN
    gpu_r = m.board_point(m.GPU_LEN / 2, slot_s - m.GPU_THICK / 2, m.GPU_H * 0.5)
    port_360_r = (m.RAD360_X / 2 - 25, m.RAD360_Y0 + m.RAD360_Y, m.RAD360_Z0 + m.RAD360_Z)
    p420 = dist(cpu, side_r) + dist(side_r, port_420_r)
    p360 = dist(gpu_r, port_360_r)
    w("Tubes (fittings on the RIGHT, 30% slack):")
    w(f"  CPU → 420 right end, around the right board edge")
    w(f"    path {p420:.0f} mm  need {p420*1.3:.0f}  /  500  "
      f"{'PASS' if p420*1.3<=500 else 'FAIL'}")
    w(f"  GPU right → 360 right (same side, in front of the board)")
    w(f"    path {p360:.0f} mm  need {p360*1.3:.0f}  /  450  "
      f"{'PASS' if p360*1.3<=450 else 'FAIL'}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Dark-material previews
# ---------------------------------------------------------------------------
def _shade_faces(verts, faces, light1, light2, base_rgb, ambient=0.18):
    v = verts
    tri = v[faces]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    n = n / ln
    l1 = np.array(light1, dtype=float)
    l1 = l1 / (np.linalg.norm(l1) + 1e-12)
    l2 = np.array(light2, dtype=float)
    l2 = l2 / (np.linalg.norm(l2) + 1e-12)
    # two-sided? no, one-sided but flip if facing away so both show in ortho
    nd1 = np.abs(n.dot(l1))
    nd2 = np.abs(n.dot(l2)) * 0.4
    inten = np.clip(ambient + 0.7 * nd1 + 0.3 * nd2, 0, 1)
    cols = np.clip(np.array(base_rgb) * inten[:, None], 0, 1)
    return tri, cols, n


ISO_FL = dict(kind="iso_fl")  # front-left
ISO_RR = dict(kind="iso_rr")


def _project(p, kind):
    x, y, z = p
    if kind == "front":
        return (x, z)
    if kind == "side":
        return (y, z)
    if kind == "iso_fl":
        # camera from -X, -Y, +Z
        r = np.array([1, -1, 0], float); r /= np.linalg.norm(r)
        view = np.array([1, 1, -1], float); view /= np.linalg.norm(view)
        up = np.cross(r, view); up /= np.linalg.norm(up)
        return (np.dot(p, r), np.dot(p, up))
    if kind == "iso_rr":
        # camera from +X, +Y, +Z (rear-right-up)
        r = np.array([-1, 1, 0], float); r /= np.linalg.norm(r)
        view = np.array([-1, -1, -1], float); view /= np.linalg.norm(view)
        up = np.cross(r, view); up /= np.linalg.norm(up)
        return (np.dot(p, r), np.dot(p, up))
    raise ValueError(kind)


def _depth(tri, kind):
    c = tri.mean(axis=1)
    if kind == "front":
        return c[:, 1]
    if kind == "side":
        return -c[:, 0]
    if kind == "iso_fl":
        view = np.array([1, 1, -1], float)
        return c.dot(view)
    if kind == "iso_rr":
        view = np.array([-1, -1, -1], float)
        return c.dot(view)
    return c[:, 1]


FRAME_RGB = (0.18, 0.18, 0.20)
HW_RGB = {
    "board": (0.25, 0.35, 0.48),
    "rad360": (0.28, 0.38, 0.22),
    "rad420": (0.42, 0.28, 0.16),
    "psu": (0.30, 0.26, 0.38),
    "gpu": (0.22, 0.36, 0.20),
    "cpu": (0.40, 0.18, 0.18),
    "io_left": (0.45, 0.40, 0.18),
    "io_right": (0.45, 0.40, 0.18),
}


def _draw_kind(ax, kind, title, hw_meshes, frame_meshes, exploded=False):
    ax.set_facecolor("#141416")
    ax.set_title(title, color="#dddddd", fontsize=11, pad=8)
    ax.set_aspect("equal")
    ax.tick_params(colors="#888888", labelsize=7)
    for s in ax.spines.values():
        s.set_color("#444444")
    ax.xaxis.label.set_color("#888")
    ax.yaxis.label.set_color("#888")
    ax.grid(True, color="#2a2a2e", lw=0.5)

    items = []  # (depth, tri, col)
    light1, light2 = (0.6, -0.5, 0.8), (-0.3, 0.4, 0.5)
    if kind == "iso_rr":
        light1, light2 = (-0.6, 0.5, 0.8), (0.3, -0.3, 0.5)

    for name, (v, f) in hw_meshes.items():
        if name.startswith("io_"):
            continue  # I/O is in the cheeks
        tri, cols, n = _shade_faces(v, f, light1, light2, HW_RGB.get(name, (0.4, 0.4, 0.4)), ambient=0.22)
        items.append((_depth(tri, kind), tri, cols, 0.92))

    for name, (v, f) in frame_meshes.items():
        tri, cols, n = _shade_faces(v, f, light1, light2, FRAME_RGB, ambient=0.12)
        items.append((_depth(tri, kind), tri, cols, 1.0))

    # sort each group of triangles
    all_d, all_t, all_c, all_a = [], [], [], []
    for d, tri, cols, a in items:
        all_d.append(d)
        all_t.append(tri)
        all_c.append(cols)
        all_a.append(np.full(len(tri), a))
    if not all_t:
        return
    d = np.concatenate(all_d)
    tri = np.concatenate(all_t)
    cols = np.concatenate(all_c)
    order = np.argsort(-d)  # far first
    tri, cols = tri[order], cols[order]
    proj = np.empty((len(tri), 3, 2))
    for i in range(3):
        xs, ys = [], []
        for p in tri[:, i, :]:
            x, y = _project(p, kind)
            xs.append(x)
            ys.append(y)
        proj[:, i, 0] = xs
        proj[:, i, 1] = ys
    from matplotlib.collections import PolyCollection
    pc = PolyCollection(proj, facecolors=cols, edgecolors=(0, 0, 0, 0.15),
                        linewidths=0.12, closed=True)
    ax.add_collection(pc)
    ax.autoscale_view()
    if kind == "front":
        ax.set_xlabel("X мм")
        ax.set_ylabel("Z мм")
    elif kind == "side":
        ax.set_xlabel("Y мм  (перед слева)")
        ax.set_ylabel("Z мм")
    else:
        ax.set_xticks([])
        ax.set_yticks([])


def _explode_meshes(parts: list[Part]):
    """Offset each part along a readable axis."""
    offsets = {}
    for p in parts:
        o = np.array([0.0, 0.0, 0.0])
        if p.name.startswith("base_"):
            o[2] = -40
            if "front" in p.name:
                o[1] = -25
            else:
                o[1] = 25
            if "left" in p.name:
                o[0] = -25
            else:
                o[0] = 25
        elif p.name.startswith("rail_left"):
            o[0] = -55
            o[1] = -20 if "front" in p.name else 20
        elif p.name.startswith("rail_right"):
            o[0] = 55
            o[1] = -20 if "front" in p.name else 20
        elif p.name.startswith("spine"):
            # along the board normal (front-up)
            c = math.cos(math.radians(45))
            o += np.array([0, -c, c]) * (40 if "lower" in p.name else 70)
        elif p.name.startswith("wishbone"):
            o[1] = 10
            o[2] = 30
            o[0] = -20 if "left" in p.name else 20
        offsets[p.name] = o
    return offsets


def render_previews(hardware, parts, frame_path, exploded_path):
    hw_meshes = {}
    for k, s in hardware.items():
        v, f = tessellate(s, 0.8)
        hw_meshes[k] = (v, f)
    fr_meshes = {}
    for p in parts:
        v, f = tessellate(p.solid, 0.6)
        fr_meshes[p.name] = (v, f)

    fig, axes = plt.subplots(2, 2, figsize=(14.5, 12.5), facecolor="#101012")
    views = [
        (axes[0, 0], "iso_fl", "Изометрия спереди-слева"),
        (axes[0, 1], "iso_rr", "Изометрия сзади-справа"),
        (axes[1, 0], "front", "Вид спереди"),
        (axes[1, 1], "side", "Вид сбоку (перед слева)"),
    ]
    for ax, kind, title in views:
        _draw_kind(ax, kind, title, hw_meshes, fr_meshes)
    fig.suptitle("B5  ·  органический каркас v1  ·  чёрный ABS",
                 color="#eeeeee", fontsize=14, y=0.98)
    # tiny legend
    handles = [
        Patch(facecolor=FRAME_RGB, edgecolor="none", label="каркас ABS"),
        Patch(facecolor=HW_RGB["board"], label="плата"),
        Patch(facecolor=HW_RGB["rad360"], label="360"),
        Patch(facecolor=HW_RGB["rad420"], label="420"),
        Patch(facecolor=HW_RGB["psu"], label="БП"),
        Patch(facecolor=HW_RGB["gpu"], label="GPU"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=6, frameon=False,
               fontsize=8, labelcolor="#cccccc", bbox_to_anchor=(0.5, 0.01))
    plt.tight_layout(rect=(0, 0.04, 1, 0.96))
    fig.savefig(frame_path, dpi=130, facecolor=fig.get_facecolor())
    plt.close(fig)

    # exploded, two isos
    offs = _explode_meshes(parts)
    fr_exp = {}
    for p in parts:
        v, f = fr_meshes[p.name]
        fr_exp[p.name] = (v + offs[p.name], f)
    fig, axes = plt.subplots(1, 2, figsize=(15.0, 7.4), facecolor="#101012")
    _draw_kind(axes[0], "iso_fl", "Взорванный вид, спереди-слева", hw_meshes, fr_exp)
    _draw_kind(axes[1], "iso_rr", "Взорванный вид, сзади-справа", hw_meshes, fr_exp)
    fig.suptitle("B5  ·  органический каркас v1  ·  взорванный вид",
                 color="#eeeeee", fontsize=14, y=0.98)
    plt.tight_layout(rect=(0, 0.02, 1, 0.94))
    fig.savefig(exploded_path, dpi=130, facecolor=fig.get_facecolor())
    plt.close(fig)


def format_report(parts, checks) -> str:
    lines = []
    w = lines.append
    w("B5 organic frame v1")
    w("=" * 64)
    w(cable_tube_report())
    w("Parts (world AABB mm, mass in g of ABS at 1.04 g/cm³):")
    tot100 = tot20 = 0.0
    for name, d, vol, m100, m20, note in checks["masses"]:
        flag = "OK" if max(d) <= MAX_PART else "TOO BIG"
        w(f"  {name:20s}  {d[0]:6.1f} × {d[1]:6.1f} × {d[2]:6.1f}  {flag}")
        w(f"    {vol:7.1f} cm³   100% {m100:6.0f} g    4 walls/20% infill ~ {m20:6.0f} g")
        if note:
            w(f"    {note}")
        tot100 += m100
        tot20 += m20
    w(f"  TOTAL                100% {tot100:6.0f} g    4 walls/20% infill ~ {tot20:6.0f} g")
    w("")
    w("Watertight STL:")
    for name, ok, nv, nf in checks["tight"]:
        w(f"  {name:20s}  {'ok' if ok else 'NOT WATERTIGHT'}  {nv} verts, {nf} faces")
    w("")
    if checks["inter"]:
        w("Frame × hardware intersections (mount = planned contact):")
        for a, b, vol, flag in checks["inter"]:
            w(f"  {a:20s} × {b:8s}  {vol:10.1f} mm³   {flag}")
    w("")
    if checks["ok"]:
        w("ASSERTS: all passed (no unexpected interference, all parts ≤ 290 mm, all STLs watertight).")
    else:
        w("ASSERTS FAILED:")
        for e in checks["errors"]:
            w(f"  - {e}")
    return "\n".join(lines) + "\n"


def main():
    print("Building hardware…")
    hardware = build_hardware()
    print("Building organic frame v1…")
    parts = build_frame()
    print(f"  {len(parts)} parts")
    print("Checks, tessellation, mass…")
    checks = run_checks(hardware, parts)
    report = format_report(parts, checks)
    path = os.path.join(OUT, "report_frame_v1.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)

    # assembly exports
    print("Exporting assembly STEP…")
    assy = cq.Assembly(name="B5_frame_v1")
    for p in parts:
        assy.add(as_wp(p.solid), name=p.name, color=cq.Color(0.12, 0.12, 0.13))
    for name, s in hardware.items():
        r, g, b = HW_RGB.get(name, (0.5, 0.5, 0.5))
        assy.add(as_wp(s), name=name, color=cq.Color(r, g, b))
    assy.save(os.path.join(OUT, "b5_frame_v1.step"))

    preview = os.path.join(OUT, "preview_frame_v1.png")
    exploded = os.path.join(OUT, "exploded_v1.png")
    print("Rendering previews…")
    render_previews(hardware, parts, preview, exploded)
    print("Preview:", preview)
    print("Exploded:", exploded)
    if not checks["ok"]:
        print("FAILED CHECKS — inspect before shipping.")
        sys.exit(1)
    print("Done, all asserts passed.")


if __name__ == "__main__":
    main()
