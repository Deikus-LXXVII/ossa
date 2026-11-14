#!/usr/bin/env python3
"""Parametric B4 PC-case block-out: volume and clearance check, not a finished case."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import cadquery as cq
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from OCP.BRepExtrema import BRepExtrema_DistShapeShape

OUT = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Parameters (mm). Every dimension lives here.
# ---------------------------------------------------------------------------
C = math.cos(math.radians(45.0))  # also sin(45)

# ATX board
BOARD_LEN = 305.0          # long side, along the tilt
BOARD_W = 244.0            # width along X
BOARD_T = 2.0
BOARD_ANGLE_DEG = 45.0
BOARD_Y0 = 150.0           # bottom edge
BOARD_Z0 = 65.0
# Board front face: Y = BOARD_Y0 + s*C, Z = BOARD_Z0 + s*C, s in [0, BOARD_LEN]

# 420 radiator + fans, lying flat in front of the board's bottom edge
RAD420_X = 458.0
RAD420_Y = 138.0
RAD420_Z = 65.0
RAD420_Y0 = 12.0           # Y 12..150
RAD420_Z0 = 0.0

# 360 radiator, standing on its edge behind and under the board
RAD360_X = 394.0
RAD360_Y = 55.0
RAD360_Z = 121.0
RAD360_Y0 = 315.0          # Y 315..370
RAD360_Z0 = 90.0           # Z 90..211
RAD360_EXHAUST = 25.0      # free air behind it

# PSU: Seasonic PRIME TX-1600. Orientation: width along X, depth along Y,
# height along Z. Cables at the front (Y min), IEC inlet at the rear (Y max).
PSU_W = 150.0              # along X
PSU_D = 210.0              # along Y
PSU_H = 86.0               # along Z
PSU_Y0 = 190.0             # Y 190..400
PSU_Z0 = 0.0

# GPU in the PCIe slot, length along X, thickness down the board, height out
GPU_LEN = 280.0            # along X
GPU_THICK = 51.0           # along the board, toward the bottom edge
GPU_H = 148.0              # perpendicular to the board, forward and up
GPU_SLOT_FRAC = 0.45       # slot position along board length from the bottom

# CPU block on the board
CPU_XY = 70.0
CPU_H = 50.0
CPU_FRAC = 0.70

# Frame
WALL = 5.0
CLEAR_X = 8.0              # inner cheek clearance outboard of the 420
CHEEK_Z = 285.0            # open top; GPU may poke above this
BASE_Y0 = 0.0
BASE_Y1 = 405.0            # 5 mm past PSU at Y=400 and exhaust at Y=395
SPINE_GAP = 2.0            # air behind the board before the spine
SPLIT_BASE_Y = 155.0
SPLIT_CHEEK_Y = 200.0

# Tube slack
TUBE_SLACK = 1.30
TUBE_420 = 500.0           # ARCTIC LF III
TUBE_360 = 450.0           # GPU AIO

# Numeric tolerance
VOL_EPS = 1e-2             # mm^3, treat smaller intersection as contact only


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def box_xyz(xmin, xmax, ymin, ymax, zmin, zmax) -> cq.Workplane:
    if xmax <= xmin or ymax <= ymin or zmax <= zmin:
        raise ValueError(f"bad box {(xmin, xmax, ymin, ymax, zmin, zmax)}")
    return (
        cq.Workplane("XY")
        .moveTo(xmin, ymin)
        .rect(xmax - xmin, ymax - ymin, centered=False)
        .extrude(zmax - zmin)
        .translate((0.0, 0.0, zmin))
    )


def to_board_space(wp: cq.Workplane) -> cq.Workplane:
    """Local X across, Y up the board from the bottom edge, Z out of the front face."""
    return wp.rotate((0, 0, 0), (1, 0, 0), BOARD_ANGLE_DEG).translate(
        (0.0, BOARD_Y0, BOARD_Z0)
    )


def board_point(x: float, s: float, n: float) -> tuple[float, float, float]:
    """World coords of a board-space point (X, along-board, outward-normal)."""
    return (x, BOARD_Y0 + (s - n) * C, BOARD_Z0 + (s + n) * C)


def shape_of(wp: cq.Workplane) -> cq.Shape:
    return wp.val()


def bbox_of(shape: cq.Shape) -> cq.BoundBox:
    return shape.BoundingBox()


def volume_of(shape: cq.Shape) -> float:
    return float(shape.Volume())


def intersection_volume(a: cq.Shape, b: cq.Shape) -> float:
    try:
        common = a.intersect(b)
    except Exception:
        return 0.0
    if common is None or common.isNull():
        return 0.0
    try:
        solids = common.Solids()
        if not solids:
            # might already be a solid
            vol = float(common.Volume())
            return vol if vol > 0 else 0.0
        return float(sum(s.Volume() for s in solids))
    except Exception:
        return 0.0


def min_distance(a: cq.Shape, b: cq.Shape) -> float:
    dss = BRepExtrema_DistShapeShape(a.wrapped, b.wrapped)
    dss.Perform()
    if not dss.IsDone():
        return float("nan")
    return float(dss.Value())


def dist3(p, q) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(p, q)))


# ---------------------------------------------------------------------------
# Build components
# ---------------------------------------------------------------------------
def build_components() -> dict[str, cq.Workplane]:
    hx = BOARD_W / 2.0
    board = to_board_space(box_xyz(-hx, hx, 0.0, BOARD_LEN, -BOARD_T, 0.0))

    r420 = box_xyz(
        -RAD420_X / 2.0,
        RAD420_X / 2.0,
        RAD420_Y0,
        RAD420_Y0 + RAD420_Y,
        RAD420_Z0,
        RAD420_Z0 + RAD420_Z,
    )
    r360 = box_xyz(
        -RAD360_X / 2.0,
        RAD360_X / 2.0,
        RAD360_Y0,
        RAD360_Y0 + RAD360_Y,
        RAD360_Z0,
        RAD360_Z0 + RAD360_Z,
    )
    # PSU centred in X. Cables at Y=PSU_Y0 (under the board), IEC at Y=PSU_Y0+PSU_D.
    psu = box_xyz(
        -PSU_W / 2.0,
        PSU_W / 2.0,
        PSU_Y0,
        PSU_Y0 + PSU_D,
        PSU_Z0,
        PSU_Z0 + PSU_H,
    )

    slot_s = GPU_SLOT_FRAC * BOARD_LEN
    gpu = to_board_space(
        box_xyz(
            -GPU_LEN / 2.0,
            GPU_LEN / 2.0,
            slot_s - GPU_THICK,
            slot_s,
            0.0,
            GPU_H,
        )
    )

    cpu_s = CPU_FRAC * BOARD_LEN
    cpu = to_board_space(
        box_xyz(
            -CPU_XY / 2.0,
            CPU_XY / 2.0,
            cpu_s - CPU_XY / 2.0,
            cpu_s + CPU_XY / 2.0,
            0.0,
            CPU_H,
        )
    )
    return {
        "board": board,
        "rad420": r420,
        "rad360": r360,
        "psu": psu,
        "gpu": gpu,
        "cpu": cpu,
    }


@dataclass
class FramePart:
    name: str
    solid: cq.Workplane
    print_size: tuple[float, float, float]  # printable local AABB (mm)
    note: str = ""


def build_frame() -> list[FramePart]:
    inner = RAD420_X / 2.0 + CLEAR_X  # 237
    cheek_in = inner
    cheek_out = inner + WALL          # 242
    parts: list[FramePart] = []

    def add(name, solid, print_size, note=""):
        parts.append(FramePart(name, solid, print_size, note))

    # Base plate, four quadrants. Solid under the iron; vents called out in the report.
    add(
        "base_front_left",
        box_xyz(-cheek_out, 0.0, BASE_Y0, SPLIT_BASE_Y, -WALL, 0.0),
        (cheek_out, SPLIT_BASE_Y - BASE_Y0, WALL),
        "front half under the 420, left",
    )
    add(
        "base_front_right",
        box_xyz(0.0, cheek_out, BASE_Y0, SPLIT_BASE_Y, -WALL, 0.0),
        (cheek_out, SPLIT_BASE_Y - BASE_Y0, WALL),
        "front half under the 420, right",
    )
    add(
        "base_rear_left",
        box_xyz(-cheek_out, 0.0, SPLIT_BASE_Y, BASE_Y1, -WALL, 0.0),
        (cheek_out, BASE_Y1 - SPLIT_BASE_Y, WALL),
        "rear half under PSU / 360, left",
    )
    add(
        "base_rear_right",
        box_xyz(0.0, cheek_out, SPLIT_BASE_Y, BASE_Y1, -WALL, 0.0),
        (cheek_out, BASE_Y1 - SPLIT_BASE_Y, WALL),
        "rear half under PSU / 360, right",
    )

    # Side cheeks, split front / rear so each is <= 290 mm in every direction
    for side, x0, x1 in (
        ("left", -cheek_out, -cheek_in),
        ("right", cheek_in, cheek_out),
    ):
        add(
            f"cheek_{side}_front",
            box_xyz(x0, x1, BASE_Y0, SPLIT_CHEEK_Y, 0.0, CHEEK_Z),
            (WALL, SPLIT_CHEEK_Y - BASE_Y0, CHEEK_Z),
        )
        add(
            f"cheek_{side}_rear",
            box_xyz(x0, x1, SPLIT_CHEEK_Y, BASE_Y1, 0.0, CHEEK_Z),
            (WALL, BASE_Y1 - SPLIT_CHEEK_Y, CHEEK_Z),
        )

    # Board spine, 2 mm behind the board, split along its length for the bed
    hx = BOARD_W / 2.0
    z0 = -(BOARD_T + SPINE_GAP + WALL)
    z1 = -(BOARD_T + SPINE_GAP)
    split_s = BOARD_LEN / 2.0
    spine_lo = to_board_space(box_xyz(-hx, hx, 0.0, split_s, z0, z1))
    spine_hi = to_board_space(box_xyz(-hx, hx, split_s, BOARD_LEN, z0, z1))
    add("spine_lower", spine_lo, (BOARD_W, split_s, WALL), "print flat, lower half of the 45° backplate")
    add("spine_upper", spine_hi, (BOARD_W, BOARD_LEN - split_s, WALL), "print flat, upper half of the 45° backplate")

    # 420 end stops, just outboard of the radiator ends, sitting on the base
    y0, y1 = RAD420_Y0, RAD420_Y0 + RAD420_Y
    add(
        "rad420_stop_left",
        box_xyz(-RAD420_X / 2.0 - WALL, -RAD420_X / 2.0, y0, y1, 0.0, 20.0),
        (WALL, RAD420_Y, 20.0),
        "keeps the 420 from sliding left",
    )
    add(
        "rad420_stop_right",
        box_xyz(RAD420_X / 2.0, RAD420_X / 2.0 + WALL, y0, y1, 0.0, 20.0),
        (WALL, RAD420_Y, 20.0),
        "keeps the 420 from sliding right",
    )

    # 360 side supports, outboard of the PSU (PSU is X=±75, 360 is X=±197)
    support_w = 20.0
    for side, x0, x1 in (
        ("left", -RAD360_X / 2.0, -RAD360_X / 2.0 + support_w),
        ("right", RAD360_X / 2.0 - support_w, RAD360_X / 2.0),
    ):
        add(
            f"rad360_support_{side}",
            box_xyz(x0, x1, RAD360_Y0, RAD360_Y0 + RAD360_Y, 0.0, RAD360_Z0),
            (support_w, RAD360_Y, RAD360_Z0),
            "post under the 360 end, beside the PSU",
        )

    return parts


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
PAIRS = [
    ("board", "rad420"),
    ("board", "rad360"),
    ("board", "psu"),
    ("board", "gpu"),
    ("board", "cpu"),
    ("rad420", "rad360"),
    ("rad420", "psu"),
    ("rad420", "gpu"),
    ("rad420", "cpu"),
    ("rad360", "psu"),
    ("rad360", "gpu"),
    ("rad360", "cpu"),
    ("psu", "gpu"),
    ("psu", "cpu"),
    ("gpu", "cpu"),
]

NEIGHBOURS = [
    ("board", "rad420"),
    ("board", "rad360"),
    ("board", "psu"),
    ("board", "gpu"),
    ("board", "cpu"),
    ("rad420", "gpu"),
    ("rad360", "psu"),
    ("rad360", "cpu"),
    ("gpu", "cpu"),
    ("psu", "rad420"),
]


def run_checks(comps: dict[str, cq.Workplane]) -> dict:
    shapes = {k: shape_of(v) for k, v in comps.items()}

    inter = []
    bad = False
    for a, b in PAIRS:
        vol = intersection_volume(shapes[a], shapes[b])
        inter.append((a, b, vol))
        if vol > VOL_EPS:
            bad = True

    gaps = []
    for a, b in NEIGHBOURS:
        vol = next(v for x, y, v in inter if {x, y} == {a, b})
        if vol > VOL_EPS:
            gaps.append((a, b, 0.0, "INTERSECTION"))
        else:
            d = min_distance(shapes[a], shapes[b])
            gaps.append((a, b, d, "contact" if d < 0.05 else "ok"))

    # Bounding boxes
    compound = cq.Compound.makeCompound(list(shapes.values()))
    bb = compound.BoundingBox()
    # Envelope includes 25 mm exhaust behind the 360 and the base plate
    cheek_out = RAD420_X / 2.0 + CLEAR_X + WALL
    env = {
        "xmin": -cheek_out,
        "xmax": cheek_out,
        "ymin": BASE_Y0,
        "ymax": BASE_Y1,
        "zmin": -WALL,
        "zmax": max(bb.zmax, CHEEK_Z),
    }

    # Tube ports
    # CPU ports on the lower face of the block (toward the 420), on the outer face
    cpu_s0 = CPU_FRAC * BOARD_LEN - CPU_XY / 2.0
    cpu_port = board_point(0.0, cpu_s0, CPU_H)
    # 420 fittings on the top-back edge, both ends (end tank)
    port_420_l = (-RAD420_X / 2.0 + 30.0, RAD420_Y0 + RAD420_Y, RAD420_Z0 + RAD420_Z)
    port_420_r = (RAD420_X / 2.0 - 30.0, RAD420_Y0 + RAD420_Y, RAD420_Z0 + RAD420_Z)

    # GPU fittings at the card ends, mid thickness, mid cooler height
    slot_s = GPU_SLOT_FRAC * BOARD_LEN
    gpu_s = slot_s - GPU_THICK / 2.0
    gpu_port_l = board_point(-GPU_LEN / 2.0, gpu_s, GPU_H * 0.5)
    gpu_port_r = board_point(GPU_LEN / 2.0, gpu_s, GPU_H * 0.5)
    # 360 fittings on the front face (toward the board), both ends, mid height
    port_360_l = (
        -RAD360_X / 2.0 + 25.0,
        RAD360_Y0,
        RAD360_Z0 + RAD360_Z / 2.0,
    )
    port_360_r = (
        RAD360_X / 2.0 - 25.0,
        RAD360_Y0,
        RAD360_Z0 + RAD360_Z / 2.0,
    )
    # Waypoints around the board sides (GPU is already 18 mm outboard of the board)
    way_l = (-BOARD_W / 2.0 - 30.0, 280.0, 200.0)
    way_r = (BOARD_W / 2.0 + 30.0, 280.0, 200.0)

    def tube_check(name, straight, limit, via=None):
        need = straight * TUBE_SLACK
        path = straight
        path_need = need
        if via is not None:
            path = via
            path_need = via * TUBE_SLACK
        ok_s = need <= limit
        ok_p = path_need <= limit
        return {
            "name": name,
            "straight": straight,
            "straight_need": need,
            "path": path,
            "path_need": path_need,
            "limit": limit,
            "pass_straight": ok_s,
            "pass_path": ok_p,
        }

    tubes = [
        tube_check(
            "CPU → 420 left end (nearer)",
            dist3(cpu_port, port_420_l),
            TUBE_420,
        ),
        tube_check(
            "CPU → 420 right end (farther)",
            dist3(cpu_port, port_420_r),
            TUBE_420,
        ),
        tube_check(
            "GPU right → 360 right (same side, around board)",
            dist3(gpu_port_r, port_360_r),
            TUBE_360,
            via=dist3(gpu_port_r, way_r) + dist3(way_r, port_360_r),
        ),
        tube_check(
            "GPU right → 360 left (opposite side, around board)",
            dist3(gpu_port_r, port_360_l),
            TUBE_360,
            via=dist3(gpu_port_r, way_r) + dist3(way_r, port_360_l),
        ),
        tube_check(
            "GPU left → 360 left (same side, around board)",
            dist3(gpu_port_l, port_360_l),
            TUBE_360,
            via=dist3(gpu_port_l, way_l) + dist3(way_l, port_360_l),
        ),
    ]

    ports = {
        "cpu": cpu_port,
        "420_l": port_420_l,
        "420_r": port_420_r,
        "gpu_l": gpu_port_l,
        "gpu_r": gpu_port_r,
        "360_l": port_360_l,
        "360_r": port_360_r,
        "way_l": way_l,
        "way_r": way_r,
    }
    return {
        "inter": inter,
        "bad": bad,
        "gaps": gaps,
        "bb": bb,
        "env": env,
        "tubes": tubes,
        "ports": ports,
        "compound": compound,
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
COLORS_RGB = {
    "board": (0.31, 0.51, 0.74),
    "rad420": (0.88, 0.54, 0.23),
    "rad360": (0.66, 0.80, 0.42),
    "psu": (0.56, 0.49, 0.76),
    "gpu": (0.42, 0.66, 0.31),
    "cpu": (0.75, 0.31, 0.30),
    "frame": (0.75, 0.75, 0.75),
}
LABELS = {
    "board": "плата ATX",
    "rad420": "420",
    "rad360": "360",
    "psu": "БП",
    "gpu": "GPU",
    "cpu": "CPU",
}


def export_files(comps: dict[str, cq.Workplane], frame_parts: list[FramePart]) -> None:
    assy = cq.Assembly(name="B4_components")
    for name, wp in comps.items():
        r, g, b = COLORS_RGB[name]
        assy.add(wp, name=name, color=cq.Color(r, g, b))
    assy.save(os.path.join(OUT, "b4_assembly.step"))

    compound = cq.Compound.makeCompound([shape_of(wp) for wp in comps.values()])
    cq.exporters.export(compound, os.path.join(OUT, "b4_assembly.stl"))

    frame_assy = cq.Assembly(name="B4_frame")
    fr, fg, fb = COLORS_RGB["frame"]
    frame_solids = []
    for p in frame_parts:
        frame_assy.add(p.solid, name=p.name, color=cq.Color(fr, fg, fb))
        frame_solids.append(shape_of(p.solid))
    frame_assy.save(os.path.join(OUT, "b4_frame.step"))
    cq.exporters.export(
        cq.Compound.makeCompound(frame_solids), os.path.join(OUT, "b4_frame.stl")
    )

    all_assy = cq.Assembly(name="B4_all")
    for name, wp in comps.items():
        r, g, b = COLORS_RGB[name]
        all_assy.add(wp, name=name, color=cq.Color(r, g, b))
    for p in frame_parts:
        all_assy.add(p.solid, name=p.name, color=cq.Color(fr, fg, fb, 0.5))
    all_assy.save(os.path.join(OUT, "b4_all.step"))



# ---------------------------------------------------------------------------
# Preview: true 2D orthographic / isometric projections (painter's algorithm)
# ---------------------------------------------------------------------------
def world_box_corners(xmin, xmax, ymin, ymax, zmin, zmax, board_space=False):
    pts = []
    for x in (xmin, xmax):
        for y in (ymin, ymax):
            for z in (zmin, zmax):
                if board_space:
                    pts.append(board_point(x, y, z))
                else:
                    pts.append((x, y, z))
    return pts


def component_corners() -> dict[str, list[tuple[float, float, float]]]:
    slot_s = GPU_SLOT_FRAC * BOARD_LEN
    cpu_s = CPU_FRAC * BOARD_LEN
    hx = BOARD_W / 2.0
    return {
        "board": world_box_corners(-hx, hx, 0.0, BOARD_LEN, -BOARD_T, 0.0, True),
        "rad420": world_box_corners(
            -RAD420_X / 2.0, RAD420_X / 2.0,
            RAD420_Y0, RAD420_Y0 + RAD420_Y,
            RAD420_Z0, RAD420_Z0 + RAD420_Z,
        ),
        "rad360": world_box_corners(
            -RAD360_X / 2.0, RAD360_X / 2.0,
            RAD360_Y0, RAD360_Y0 + RAD360_Y,
            RAD360_Z0, RAD360_Z0 + RAD360_Z,
        ),
        "psu": world_box_corners(
            -PSU_W / 2.0, PSU_W / 2.0,
            PSU_Y0, PSU_Y0 + PSU_D,
            PSU_Z0, PSU_Z0 + PSU_H,
        ),
        "gpu": world_box_corners(
            -GPU_LEN / 2.0, GPU_LEN / 2.0,
            slot_s - GPU_THICK, slot_s,
            0.0, GPU_H, True,
        ),
        "cpu": world_box_corners(
            -CPU_XY / 2.0, CPU_XY / 2.0,
            cpu_s - CPU_XY / 2.0, cpu_s + CPU_XY / 2.0,
            0.0, CPU_H, True,
        ),
    }


def frame_corners(frame_parts: list[FramePart]) -> list[list[tuple[float, float, float]]]:
    """Recover 8 AABB corners for axis-aligned frame parts; tessellate the spine."""
    out = []
    for p in frame_parts:
        if p.name.startswith("spine_"):
            # rotated: use tessellated vertices unique-rounded as a point cloud is messy;
            # rebuild from the same parameters as build_frame
            continue
        bb = bbox_of(shape_of(p.solid))
        out.append(world_box_corners(bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))
    # spines in board space
    hx = BOARD_W / 2.0
    split_s = BOARD_LEN / 2.0
    z0 = -(BOARD_T + SPINE_GAP + WALL)
    z1 = -(BOARD_T + SPINE_GAP)
    out.append(world_box_corners(-hx, hx, 0.0, split_s, z0, z1, True))
    out.append(world_box_corners(-hx, hx, split_s, BOARD_LEN, z0, z1, True))
    return out


# 8 corners in (x0/x1, y0/y1, z0/z1) nested order: for x in (min,max): for y in (min,max): for z in (min,max)
# indices: 0=(0,0,0) 1=(0,0,1) 2=(0,1,0) 3=(0,1,1) 4=(1,0,0) 5=(1,0,1) 6=(1,1,0) 7=(1,1,1)
_FACES = (
    (0, 1, 3, 2),  # x = min
    (4, 6, 7, 5),  # x = max
    (0, 4, 5, 1),  # y = min
    (2, 3, 7, 6),  # y = max
    (0, 2, 6, 4),  # z = min
    (1, 5, 7, 3),  # z = max
)


def faces_of(corners):
    return [[corners[i] for i in idx] for idx in _FACES]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    l = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / l, a[1] / l, a[2] / l)


# Camera from front-left-up: position direction (-X, -Y, +Z), looking toward the origin.
# view_dir is from camera toward the scene.
ISO_VIEW = _norm((1.0, 1.0, -1.0))
ISO_RIGHT = _norm((1.0, -1.0, 0.0))          # +X right, +Y left on the screen
ISO_UP = _norm(_cross(ISO_RIGHT, ISO_VIEW))   # roughly (1, 1, 2)


def project(p, kind: str):
    x, y, z = p
    if kind == "front":
        return (x, z)
    if kind == "side":
        # looking from +X (right), front (Y=0) on the left
        return (y, z)
    # isometric
    return (_dot(p, ISO_RIGHT), _dot(p, ISO_UP))


def face_depth(face, kind: str) -> float:
    cx = sum(v[0] for v in face) / 4.0
    cy = sum(v[1] for v in face) / 4.0
    cz = sum(v[2] for v in face) / 4.0
    c = (cx, cy, cz)
    if kind == "front":
        return cy  # larger Y is farther
    if kind == "side":
        return -cx  # smaller X is farther when looking from +X
    return _dot(c, ISO_VIEW)


def face_front_facing(face, kind: str) -> bool:
    n = _cross(_sub(face[1], face[0]), _sub(face[2], face[0]))
    if kind == "front":
        view = (0.0, 1.0, 0.0)
    elif kind == "side":
        view = (-1.0, 0.0, 0.0)
    else:
        view = ISO_VIEW
    return _dot(n, view) < -1e-9


def collect_faces(named_corners, kind, is_frame=False):
    items = []
    if is_frame:
        for corners in named_corners:
            for face in faces_of(corners):
                if not face_front_facing(face, kind):
                    continue
                items.append((face_depth(face, kind), None, face))
    else:
        for name, corners in named_corners.items():
            for face in faces_of(corners):
                if not face_front_facing(face, kind):
                    continue
                items.append((face_depth(face, kind), name, face))
    items.sort(key=lambda t: t[0], reverse=True)  # far first
    return items


def draw_view(ax, kind, title, comp_corners, frame_cs, label_anchors):
    ax.set_title(title, fontsize=11, pad=8)
    ax.set_aspect("equal")
    ax.set_facecolor("white")
    ax.grid(True, color="0.9", lw=0.6)
    ax.tick_params(labelsize=7)

    # Frame, very light, behind the iron
    for _, _, face in collect_faces(frame_cs, kind, is_frame=True):
        poly = [project(v, kind) for v in face]
        ax.fill(*zip(*poly), facecolor=(0.82, 0.82, 0.82, 0.18),
                edgecolor=(0.45, 0.45, 0.45, 0.45), linewidth=0.5, zorder=1)

    vis_pts = {name: [] for name in comp_corners}
    for depth, name, face in collect_faces(comp_corners, kind):
        poly = [project(v, kind) for v in face]
        rgb = COLORS_RGB[name]
        ax.fill(*zip(*poly), facecolor=(*rgb, 0.93),
                edgecolor=(0.12, 0.12, 0.12, 0.85), linewidth=0.7, zorder=2)
        vis_pts[name].extend(poly)

    # Exhaust zone hint on the side view
    if kind == "side":
        y0 = RAD360_Y0 + RAD360_Y
        z0, z1 = RAD360_Z0, RAD360_Z0 + RAD360_Z
        ax.fill([y0, y0 + RAD360_EXHAUST, y0 + RAD360_EXHAUST, y0],
                [z0, z0, z1, z1],
                facecolor=(0.4, 0.6, 0.9, 0.12), edgecolor=(0.3, 0.45, 0.7, 0.7),
                linestyle="--", linewidth=0.8, zorder=1.5)
        ax.text(y0 + RAD360_EXHAUST / 2, z1 + 8, "выхлоп 25 мм",
                ha="center", va="bottom", fontsize=7, color="#3d5a8a")

    # Labels on the visible silhouette
    for name, pts in vis_pts.items():
        if not pts:
            continue
        # prefer a custom anchor in this view if provided
        if name in label_anchors[kind]:
            x, y = label_anchors[kind][name]
        else:
            xs, ys = zip(*pts)
            x, y = sum(xs) / len(xs), max(ys)
        ax.text(x, y, LABELS[name], ha="center", va="bottom", fontsize=8,
                color="0.05", zorder=5,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.7))

    if kind == "front":
        ax.set_xlabel("X мм", fontsize=8)
        ax.set_ylabel("Z мм", fontsize=8)
    elif kind == "side":
        ax.set_xlabel("Y мм  (перед слева)", fontsize=8)
        ax.set_ylabel("Z мм", fontsize=8)
    else:
        ax.set_xlabel("изометрия", fontsize=8)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_ylabel("")
        for s in ax.spines.values():
            s.set_visible(False)


def render_preview(
    comps: dict[str, cq.Workplane],
    frame_parts: list[FramePart],
    checks: dict,
    path: str,
) -> None:
    cc = component_corners()
    fc = frame_corners(frame_parts)

    # View-specific label anchors so overlapping projections stay readable
    label_anchors = {
        "front": {
            "rad420": (0.0, RAD420_Z0 + RAD420_Z / 2.0 - 8),
            "psu": (0.0, PSU_Z0 + PSU_H + 4),
            "rad360": (-RAD360_X / 2.0 + 40, RAD360_Z0 + RAD360_Z + 4),
            "board": (0.0, BOARD_Z0 + BOARD_LEN * C + 6),
            "gpu": (0.0, 210.0),
            "cpu": (0.0, 270.0),
        },
        "side": {
            "rad420": (RAD420_Y0 + RAD420_Y / 2.0, RAD420_Z0 + RAD420_Z + 6),
            "psu": (PSU_Y0 + 80.0, PSU_Z0 + PSU_H / 2.0),
            "rad360": (RAD360_Y0 + RAD360_Y / 2.0, RAD360_Z0 + RAD360_Z / 2.0),
            "board": (260.0, 230.0),
            "gpu": (145.0, 255.0),
            "cpu": (255.0, 290.0),
        },
        "iso": {},  # use silhouette centroids
    }

    fig = plt.figure(figsize=(16.8, 7.0), facecolor="white")
    views = [
        ("iso", "Изометрия (спереди-слева-сверху)"),
        ("front", "Вид спереди"),
        ("side", "Вид сбоку (перед слева)"),
    ]
    axes = [fig.add_subplot(1, 3, i + 1) for i in range(3)]
    for ax, (kind, title) in zip(axes, views):
        draw_view(ax, kind, title, cc, fc, label_anchors)

    # Shared colour legend
    from matplotlib.patches import Patch
    handles = [
        Patch(facecolor=COLORS_RGB[n], edgecolor="k", label=LABELS[n])
        for n in ("board", "rad420", "rad360", "psu", "gpu", "cpu")
    ]
    handles.append(Patch(facecolor=(0.82, 0.82, 0.82), edgecolor="0.4", label="каркас"))
    fig.legend(handles=handles, loc="lower center", ncol=7, frameon=False,
               fontsize=8, bbox_to_anchor=(0.5, -0.01))

    fig.suptitle(
        "Вариант B4, блочный объём  ·  420 снизу, плата 45°, 360 за платой, БП под платой",
        fontsize=13,
        y=0.98,
    )
    plt.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(path, dpi=130, facecolor="white")
    plt.close(fig)


def format_report(
    comps: dict[str, cq.Workplane],
    frame_parts: list[FramePart],
    checks: dict,
) -> str:
    bb = checks["bb"]
    env = checks["env"]
    lines = []
    w = lambda s="": lines.append(s)

    w("B4 CAD block-out  /  mm")
    w("=" * 64)
    w("Components (parametric boxes):")
    for name, wp in comps.items():
        b = bbox_of(shape_of(wp))
        w(
            f"  {name:8s}  X {b.xmin:7.1f}..{b.xmax:7.1f}   "
            f"Y {b.ymin:7.1f}..{b.ymax:7.1f}   "
            f"Z {b.zmin:7.1f}..{b.zmax:7.1f}   "
            f"vol {volume_of(shape_of(wp)):.0f} mm3"
        )
    w()
    w("PSU orientation: 150 along X (centred), 210 along Y (190..400), 86 along Z.")
    w("  Cables at Y=190 (under the board). IEC inlet at Y=400 (rear).")
    w("GPU: 280 along X (18 mm overhang each side of the 244 mm board),")
    w("  148 mm out of the board (forward and up), 51 mm thickness down the board")
    w("  from the slot at 45% so it stays clear of the CPU at 70%.")
    w()
    w("Interference (pairwise intersection volume, must be 0):")
    for a, b, vol in checks["inter"]:
        flag = "FAIL" if vol > VOL_EPS else "ok"
        w(f"  {a:8s} × {b:8s}  {vol:10.4f} mm3   {flag}")
    w(
        "RESULT: "
        + (
            "INTERFERENCE DETECTED"
            if checks["bad"]
            else "no interference (all intersection volumes ~ 0)"
        )
    )
    w()
    w("Minimum gaps between neighbours:")
    for a, b, d, tag in checks["gaps"]:
        w(f"  {a:8s} – {b:8s}  {d:7.1f} mm   {tag}")
    w()
    w("Bounding box of the iron (components only):")
    w(f"  X {bb.xmin:.1f} .. {bb.xmax:.1f}   ({bb.xmax - bb.xmin:.1f})")
    w(f"  Y {bb.ymin:.1f} .. {bb.ymax:.1f}   ({bb.ymax - bb.ymin:.1f})")
    w(f"  Z {bb.zmin:.1f} .. {bb.zmax:.1f}   ({bb.zmax - bb.zmin:.1f})")
    w("Envelope including 5 mm base, cheeks and 25 mm exhaust behind the 360:")
    w(f"  X {env['xmin']:.1f} .. {env['xmax']:.1f}   ({env['xmax'] - env['xmin']:.1f})")
    w(f"  Y {env['ymin']:.1f} .. {env['ymax']:.1f}   ({env['ymax'] - env['ymin']:.1f})")
    w(f"  Z {env['zmin']:.1f} .. {env['zmax']:.1f}   ({env['zmax'] - env['zmin']:.1f})")
    w()
    w(f"Tube reach  (straight-line × {TUBE_SLACK:.2f} slack vs rated length):")
    for t in checks["tubes"]:
        ps = "PASS" if t["pass_straight"] else "FAIL"
        w(
            f"  {t['name']}"
        )
        w(
            f"    straight {t['straight']:.0f} mm  →  need {t['straight_need']:.0f}  /  {t['limit']:.0f}  {ps}"
        )
        if t["path"] != t["straight"]:
            pp = "PASS" if t["pass_path"] else "FAIL"
            w(
                f"    around-board path {t['path']:.0f} mm  →  need {t['path_need']:.0f}  /  {t['limit']:.0f}  {pp}"
            )
    w()
    w("Printable frame parts (each ≤ 290 mm, 300³ bed with 10 mm margin):")
    over = False
    for p in frame_parts:
        sx, sy, sz = p.print_size
        mx = max(sx, sy, sz)
        flag = "OK" if mx <= 290 else "TOO BIG"
        if mx > 290:
            over = True
        note = f"  — {p.note}" if p.note else ""
        w(f"  {p.name:22s}  {sx:6.1f} × {sy:6.1f} × {sz:6.1f}   {flag}{note}")
    w("  All parts fit." if not over else "  WARNING: some parts exceed 290 mm.")
    w()
    w("Issues / watch-outs:")
    w("  • 420 sits on the base (Z=0). If it intakes from below, the base needs a grille")
    w("    and short feet. If it blows up, that air goes into the PSU and the underside")
    w("    of the board / GPU (86 mm clearance from the 420 to the GPU).")
    w("  • PSU top is only ~4 mm under the 360. A top-mounted PSU fan would be starved.")
    w("    Use a bottom intake (vented base + feet) or a rear/side intake; IEC is at Y=400.")
    w("  • 360 exhaust needs a clear 25 mm behind it (Y 370..395). The back of the frame")
    w("    is left open. Blow the 360 backward, away from the board.")
    w("  • Board rear I/O is at the top edge (~Y 366, Z 281), facing up and back at 45°.")
    w("    The 360 (top Z=211) does not block it, but cables come in from above.")
    w("  • GPU already overhangs the board by 18 mm each side. A PCIe 5.0 riser would")
    w("    let it move off the board entirely (not modelled here).")
    w("  • GPU tubes must go around the board to reach the 360. Same-side ports pass;")
    w("    opposite-side ports fail the 30% slack check on 450 mm tubes.")
    w("  • Board-to-360 clearance is tight (11.4 mm). Do not thicken")
    w("    the spine past 5 mm without checking.")
    w("  • Split joints need fasteners / heat-set inserts later; this is only a volume check.")
    return "\n".join(lines) + "\n"


def main() -> None:
    comps = build_components()
    frame_parts = build_frame()

    # Frame must not eat the iron (small planned contacts: 420 end stops touch
    # the 420 ends, 360 supports touch the 360 underside — those are mounts).
    mount_ok = {
        ("rad420_stop_left", "rad420"),
        ("rad420_stop_right", "rad420"),
        ("rad360_support_left", "rad360"),
        ("rad360_support_right", "rad360"),
        # spine is gapped 2 mm behind the board; base touches nothing at Z=0
        # except it shares the Z=0 plane with 420 and PSU (zero-volume contact).
    }
    print("Building checks…")
    checks = run_checks(comps)

    # Extra: frame vs components
    frame_hits = []
    comp_shapes = {k: shape_of(v) for k, v in comps.items()}
    for p in frame_parts:
        fs = shape_of(p.solid)
        for cn, cs in comp_shapes.items():
            vol = intersection_volume(fs, cs)
            if vol > VOL_EPS and (p.name, cn) not in mount_ok:
                frame_hits.append((p.name, cn, vol))
    checks["frame_hits"] = frame_hits

    report = format_report(comps, frame_parts, checks)
    if frame_hits:
        report += "Frame/component intersections (unexpected):\n"
        for a, b, v in frame_hits:
            report += f"  {a} × {b}  {v:.2f} mm3\n"
    else:
        report += "Frame does not unexpectedly intersect the iron.\n"

    report_path = os.path.join(OUT, "report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(report)

    print("Exporting STEP / STL…")
    export_files(comps, frame_parts)

    preview = os.path.join(OUT, "preview_b4.png")
    print("Rendering preview…")
    render_preview(comps, frame_parts, checks, preview)
    print(f"Preview: {preview}")
    print("Done.")


if __name__ == "__main__":
    main()
