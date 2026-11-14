#!/usr/bin/env python3
"""Parametric B5 PC-case block-out: radiators swapped vs B4, plus a reserved
front I/O pod and a first organic open frame. Volume / clearance check, not a
finished case.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import cadquery as cq
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Patch, Polygon, Rectangle
from OCP.BRepExtrema import BRepExtrema_DistShapeShape

OUT = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(OUT)

C = math.cos(math.radians(45.0))

# ---------------------------------------------------------------------------
# Parameters (mm)
# ---------------------------------------------------------------------------
# ATX board — kept at Z0=65 so the rear wedge stays tall enough for the 420.
# The front 360 is raised 10 mm (Z 10..65) so its fan tops line up with the
# board's bottom edge. Lowering the board to 55 would drop the wedge and the
# 420 would hit the board even sooner.
BOARD_LEN = 305.0
BOARD_W = 244.0
BOARD_T = 2.0
BOARD_ANGLE_DEG = 45.0
BOARD_Y0 = 150.0
BOARD_Z0 = 65.0

# 360 + fans, now lying flat in front of the board's bottom edge
RAD360_X = 394.0
RAD360_Y = 121.0
RAD360_Z = 55.0
RAD360_Y0 = BOARD_Y0 - RAD360_Y          # 29..150
RAD360_Z0 = BOARD_Z0 - RAD360_Z          # 10..65  (raised, not sitting on Z=0)

# 420 + fans, now standing on its edge in the wedge, above the PSU
RAD420_X = 458.0
RAD420_Y = 65.0                          # thickness (rad + fans)
RAD420_Z = 138.0                         # tall
RAD420_EXHAUST = 25.0
# PSU / board clearance targets after the old 4 mm / 11.4 mm gaps broke
PSU_RAD_GAP = 20.0
BOARD_RAD_GAP = 15.0
# Derived placement (see comments in place_rear()):
#   420 Z = 86+20 .. 86+20+138 = 106..244
#   front Y chosen so the board's back face is 15 mm above the 420
RAD420_Z0 = 86.0 + PSU_RAD_GAP           # 106
RAD420_Y0 = 353.0                        # 353..418  (15 mm true gap to board)
# exhaust Y 412..437

# PSU: Seasonic PRIME TX-1600, still 150 along X, 210 along Y, 86 tall.
# Shifted back so the IEC inlet sits at the rear, under the exhaust, reachable
# from behind (Y=447). Cables at the front, under the board.
PSU_W = 150.0
PSU_D = 210.0
PSU_H = 86.0
PSU_Y0 = 243.0                           # 243..453
PSU_Z0 = 0.0

# GPU / CPU — same board-space placement as B4
GPU_LEN = 280.0
GPU_THICK = 51.0
GPU_H = 148.0
GPU_SLOT_FRAC = 0.45
CPU_XY = 70.0
CPU_H = 50.0
CPU_FRAC = 0.70

# Front I/O pod, reserved volume, front-right (asymmetric), beside the 360.
# Faces forward (-Y). 19 mm anti-vandal buttons, 2× USB-A, USB-C, 3.5 mm jack.
IOD_X0, IOD_X1 = 212.0, 302.0            # 90 mm wide, 15 mm outboard of the 360
IOD_Y0, IOD_Y1 = 8.0, 98.0               # 90 mm deep
IOD_Z0, IOD_Z1 = 8.0, 72.0               # 64 mm tall
USB3_CABLE = 500.0
TUBE_SLACK = 1.30
TUBE_420 = 500.0
TUBE_360 = 450.0

# Frame
WALL = 5.0
BASE_T = 6.0
CLEAR_X = 8.0
CHEEK_Z = 290.0
BASE_Y0 = 0.0
BASE_Y1 = 460.0                          # 7 mm past PSU at 453
SPINE_GAP = 2.0
SPLIT_Y = 200.0
VOL_EPS = 1e-2


def box_xyz(xmin, xmax, ymin, ymax, zmin, zmax) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .moveTo(xmin, ymin)
        .rect(xmax - xmin, ymax - ymin, centered=False)
        .extrude(zmax - zmin)
        .translate((0.0, 0.0, zmin))
    )


def to_board_space(wp: cq.Workplane) -> cq.Workplane:
    return wp.rotate((0, 0, 0), (1, 0, 0), BOARD_ANGLE_DEG).translate(
        (0.0, BOARD_Y0, BOARD_Z0)
    )


def board_point(x: float, s: float, n: float) -> tuple[float, float, float]:
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
# Iron
# ---------------------------------------------------------------------------
def build_components() -> dict[str, cq.Workplane]:
    hx = BOARD_W / 2.0
    board = to_board_space(box_xyz(-hx, hx, 0.0, BOARD_LEN, -BOARD_T, 0.0))
    r360 = box_xyz(
        -RAD360_X / 2.0, RAD360_X / 2.0,
        RAD360_Y0, RAD360_Y0 + RAD360_Y,
        RAD360_Z0, RAD360_Z0 + RAD360_Z,
    )
    r420 = box_xyz(
        -RAD420_X / 2.0, RAD420_X / 2.0,
        RAD420_Y0, RAD420_Y0 + RAD420_Y,
        RAD420_Z0, RAD420_Z0 + RAD420_Z,
    )
    psu = box_xyz(
        -PSU_W / 2.0, PSU_W / 2.0,
        PSU_Y0, PSU_Y0 + PSU_D,
        PSU_Z0, PSU_Z0 + PSU_H,
    )
    slot_s = GPU_SLOT_FRAC * BOARD_LEN
    gpu = to_board_space(
        box_xyz(-GPU_LEN / 2.0, GPU_LEN / 2.0, slot_s - GPU_THICK, slot_s, 0.0, GPU_H)
    )
    cpu_s = CPU_FRAC * BOARD_LEN
    cpu = to_board_space(
        box_xyz(
            -CPU_XY / 2.0, CPU_XY / 2.0,
            cpu_s - CPU_XY / 2.0, cpu_s + CPU_XY / 2.0,
            0.0, CPU_H,
        )
    )
    io_pod = box_xyz(IOD_X0, IOD_X1, IOD_Y0, IOD_Y1, IOD_Z0, IOD_Z1)
    return {
        "board": board,
        "rad360": r360,
        "rad420": r420,
        "psu": psu,
        "gpu": gpu,
        "cpu": cpu,
        "io_pod": io_pod,
    }


@dataclass
class FramePart:
    name: str
    solid: cq.Workplane
    print_size: tuple[float, float, float]
    note: str = ""


def _fillet_safe(wp: cq.Workplane, r: float) -> cq.Workplane:
    try:
        edged = wp.edges("|Z")
        return edged.fillet(r)
    except Exception:
        return wp


def build_frame() -> list[FramePart]:
    """Open organic frame v1: skiff base, asymmetric rails, I/O pod, spine, cradles."""
    parts: list[FramePart] = []

    def add(name, solid, print_size, note=""):
        parts.append(FramePart(name, solid, print_size, note))

    # --- skiff base, split into printable plates (organic outline is in the 2D
    # preview; here each plate is a rectangle covering its quadrant, with the
    # front-right plate carrying the pod footprint).
    add("base_front_left",
        box_xyz(-245, 0, BASE_Y0, SPLIT_Y, -BASE_T, 0),
        (245, SPLIT_Y, BASE_T), "skiff front left")
    add("base_front_center",
        box_xyz(0, 200, BASE_Y0, SPLIT_Y, -BASE_T, 0),
        (200, SPLIT_Y, BASE_T), "skiff front centre")
    add("base_front_pod",
        box_xyz(200, 310, BASE_Y0, SPLIT_Y, -BASE_T, 0),
        (110, SPLIT_Y, BASE_T), "skiff under the I/O pod")
    add("base_rear_left",
        box_xyz(-245, 0, SPLIT_Y, BASE_Y1, -BASE_T, 0),
        (245, BASE_Y1 - SPLIT_Y, BASE_T), "skiff rear left")
    add("base_rear_right",
        box_xyz(0, 245, SPLIT_Y, BASE_Y1, -BASE_T, 0),
        (245, BASE_Y1 - SPLIT_Y, BASE_T), "skiff rear right")

    # 10 mm intake plinth under the 360, with the radiator sitting on it
    add("plinth_360_left",
        box_xyz(-RAD360_X / 2, 0, RAD360_Y0, RAD360_Y0 + RAD360_Y, 0, RAD360_Z0),
        (RAD360_X / 2, RAD360_Y, RAD360_Z0),
        "intake plinth under the 360, left; cut a grille later")
    add("plinth_360_right",
        box_xyz(0, RAD360_X / 2, RAD360_Y0, RAD360_Y0 + RAD360_Y, 0, RAD360_Z0),
        (RAD360_X / 2, RAD360_Y, RAD360_Z0),
        "intake plinth under the 360, right")

    # Organic-ish side rails: thick rounded bars, right rail blooms into the pod.
    # Front / rear split at SPLIT_Y so each piece is <= 290 mm.
    def rail(x0, x1, y0, y1, z0, z1, r=12.0):
        return _fillet_safe(box_xyz(x0, x1, y0, y1, z0, z1), r)

    # Left rail, slimmer
    add("rail_left_front",
        rail(-245, -229, BASE_Y0, SPLIT_Y, 0, 120),
        (16, SPLIT_Y, 120), "left rail, front")
    add("rail_left_rear",
        rail(-245, -229, SPLIT_Y, BASE_Y1, 0, 250),
        (16, BASE_Y1 - SPLIT_Y, 250), "left rail, rear, taller around the 420")

    # Right rail, front section sits outboard of the pod
    add("rail_right_front",
        rail(302, 318, BASE_Y0, SPLIT_Y, 0, 90),
        (16, SPLIT_Y, 90), "right rail, front, outboard of the I/O pod")
    add("rail_right_rear",
        rail(229, 245, SPLIT_Y, BASE_Y1, 0, 250),
        (16, BASE_Y1 - SPLIT_Y, 250), "right rail, rear, against the 420")

    # I/O pod as a filleted block — printable as one part (90×90×64 + walls)
    pod = _fillet_safe(
        box_xyz(IOD_X0 - 4, IOD_X1 + 4, IOD_Y0 - 4, IOD_Y1 + 4, 0, IOD_Z1 + 4),
        10.0,
    )
    add("io_pod_shell", pod, (98, 98, IOD_Z1 + 4),
        "sculpted front I/O pod, right side; hollow later")

    # Board spine, print flat, two halves
    hx = BOARD_W / 2.0
    z0 = -(BOARD_T + SPINE_GAP + WALL)
    z1 = -(BOARD_T + SPINE_GAP)
    split_s = BOARD_LEN / 2.0
    add("spine_lower",
        to_board_space(box_xyz(-hx, hx, 0.0, split_s, z0, z1)),
        (BOARD_W, split_s, WALL), "print flat, lower 45° backplate")
    add("spine_upper",
        to_board_space(box_xyz(-hx, hx, split_s, BOARD_LEN, z0, z1)),
        (BOARD_W, BOARD_LEN - split_s, WALL), "print flat, upper 45° backplate")

    # 420 side cradles (posts under each end, outboard of the PSU at X=±75)
    # The 420 sits at Z=106, so a 20 mm wide post from Z=0 to 106, under each end.
    for side, x0, x1 in (
        ("left", -RAD420_X / 2, -RAD420_X / 2 + 22),
        ("right", RAD420_X / 2 - 22, RAD420_X / 2),
    ):
        add(f"rad420_cradle_{side}",
            box_xyz(x0, x1, RAD420_Y0, RAD420_Y0 + RAD420_Y, 0, RAD420_Z0),
            (22, RAD420_Y, RAD420_Z0),
            "post under the 420 end, beside the PSU")

    # 360 end stops
    add("rad360_stop_left",
        box_xyz(-RAD360_X / 2 - WALL, -RAD360_X / 2, RAD360_Y0, RAD360_Y0 + RAD360_Y, RAD360_Z0, RAD360_Z0 + 16),
        (WALL, RAD360_Y, 16), "keeps the 360 from sliding left")
    add("rad360_stop_right",
        box_xyz(RAD360_X / 2, RAD360_X / 2 + WALL, RAD360_Y0, RAD360_Y0 + RAD360_Y, RAD360_Z0, RAD360_Z0 + 16),
        (WALL, RAD360_Y, 16), "keeps the 360 from sliding right")

    return parts


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
PAIRS = [
    ("board", "rad360"), ("board", "rad420"), ("board", "psu"),
    ("board", "gpu"), ("board", "cpu"), ("board", "io_pod"),
    ("rad360", "rad420"), ("rad360", "psu"), ("rad360", "gpu"),
    ("rad360", "cpu"), ("rad360", "io_pod"),
    ("rad420", "psu"), ("rad420", "gpu"), ("rad420", "cpu"), ("rad420", "io_pod"),
    ("psu", "gpu"), ("psu", "cpu"), ("psu", "io_pod"),
    ("gpu", "cpu"), ("gpu", "io_pod"), ("cpu", "io_pod"),
]
NEIGHBOURS = [
    ("board", "rad360"), ("board", "rad420"), ("board", "psu"),
    ("board", "gpu"), ("board", "cpu"),
    ("rad360", "gpu"), ("rad360", "io_pod"),
    ("rad420", "psu"), ("rad420", "cpu"),
    ("gpu", "cpu"), ("psu", "rad360"), ("io_pod", "psu"),
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

    compound = cq.Compound.makeCompound(list(shapes.values()))
    bb = compound.BoundingBox()
    env = {
        "xmin": min(bb.xmin, -RAD420_X / 2, IOD_X0) - CLEAR_X - WALL,
        "xmax": max(bb.xmax, RAD420_X / 2, IOD_X1) + CLEAR_X + WALL,
        "ymin": BASE_Y0,
        "ymax": BASE_Y1,
        "zmin": -BASE_T,
        "zmax": max(bb.zmax, CHEEK_Z),
    }

    # ---- tubes ----
    cpu_s0 = CPU_FRAC * BOARD_LEN - CPU_XY / 2.0
    cpu_port = board_point(0.0, cpu_s0, CPU_H)
    # 420 fittings on the front-top of each end tank (toward the board)
    port_420_l = (-RAD420_X / 2 + 30, RAD420_Y0, RAD420_Z0 + RAD420_Z)
    port_420_r = (RAD420_X / 2 - 30, RAD420_Y0, RAD420_Z0 + RAD420_Z)
    # over-the-top waypoint (above the board I/O edge)
    top_way = board_point(0.0, BOARD_LEN + 10, 20)
    side_l = (-BOARD_W / 2 - 40, 280.0, 220.0)
    side_r = (BOARD_W / 2 + 40, 280.0, 220.0)

    slot_s = GPU_SLOT_FRAC * BOARD_LEN
    gpu_s = slot_s - GPU_THICK / 2.0
    gpu_port_l = board_point(-GPU_LEN / 2, gpu_s, GPU_H * 0.5)
    gpu_port_r = board_point(GPU_LEN / 2, gpu_s, GPU_H * 0.5)
    # 360 fittings on the top-back edge (toward the board / GPU)
    port_360_l = (-RAD360_X / 2 + 25, RAD360_Y0 + RAD360_Y, RAD360_Z0 + RAD360_Z)
    port_360_r = (RAD360_X / 2 - 25, RAD360_Y0 + RAD360_Y, RAD360_Z0 + RAD360_Z)

    def tube(name, straight, limit, via=None):
        need = straight * TUBE_SLACK
        path = via if via is not None else straight
        path_need = path * TUBE_SLACK
        return {
            "name": name,
            "straight": straight,
            "straight_need": need,
            "path": path,
            "path_need": path_need,
            "limit": limit,
            "pass_straight": need <= limit,
            "pass_path": path_need <= limit,
        }

    tubes = [
        tube("CPU → 420 left, over the board top",
             dist3(cpu_port, port_420_l), TUBE_420,
             via=dist3(cpu_port, top_way) + dist3(top_way, port_420_l)),
        tube("CPU → 420 right, over the board top",
             dist3(cpu_port, port_420_r), TUBE_420,
             via=dist3(cpu_port, top_way) + dist3(top_way, port_420_r)),
        tube("CPU → 420 left, around the left edge",
             dist3(cpu_port, port_420_l), TUBE_420,
             via=dist3(cpu_port, side_l) + dist3(side_l, port_420_l)),
        tube("CPU → 420 right, around the right edge",
             dist3(cpu_port, port_420_r), TUBE_420,
             via=dist3(cpu_port, side_r) + dist3(side_r, port_420_r)),
        tube("GPU left → 360 left (same side)",
             dist3(gpu_port_l, port_360_l), TUBE_360),
        tube("GPU right → 360 right (same side)",
             dist3(gpu_port_r, port_360_r), TUBE_360),
        tube("GPU right → 360 left (opposite side)",
             dist3(gpu_port_r, port_360_l), TUBE_360),
    ]

    # ---- front-panel cables ----
    # Header estimates on the Z890 Tomahawk, I/O at the top of our board:
    # JUSB3 and JUSBC1 are on the right edge; JFP1 near the bottom-right;
    # JAUD1 near the bottom-left. I/O pod is front-right, closer to the USB headers.
    io_face = ((IOD_X0 + IOD_X1) / 2, IOD_Y0, (IOD_Z0 + IOD_Z1) / 2)
    headers = {
        "JFP1 (power/reset/LED, bottom-right)": board_point(100, 18, 0),
        "JAUD1 (front audio, bottom-left)": board_point(-110, 18, 0),
        "JUSB3 (USB 5Gbps, right edge)": board_point(BOARD_W / 2, 70, 0),
        "JUSBC1 (USB-C 20Gbps Key-A, right edge below JUSB3)": board_point(BOARD_W / 2, 40, 0),
    }
    # USB / JFP cables go around the 360's right end. JAUD1 is on the left,
    # so it takes the shorter path along the front lip, not around the back.
    way_io = (220.0, 155.0, 40.0)
    way_front = (-110.0, 12.0, 30.0)
    cables = []
    for name, hdr in headers.items():
        straight = dist3(io_face, hdr)
        if "JAUD1" in name:
            path = dist3(io_face, way_front) + dist3(way_front, hdr)
            limit = 700.0  # stock 500 mm often short; 700 mm HD-audio extensions are common
        else:
            path = dist3(io_face, way_io) + dist3(way_io, hdr)
            limit = USB3_CABLE
        cables.append({
            "name": name,
            "straight": straight,
            "path": path,
            "path_need": path * TUBE_SLACK,
            "limit": limit,
            "pass": path * TUBE_SLACK <= limit,
        })

    return {
        "inter": inter, "bad": bad, "gaps": gaps, "bb": bb, "env": env,
        "tubes": tubes, "cables": cables, "compound": compound,
        "ports": {
            "cpu": cpu_port, "420_l": port_420_l, "420_r": port_420_r,
            "gpu_l": gpu_port_l, "gpu_r": gpu_port_r,
            "360_l": port_360_l, "360_r": port_360_r,
            "io": io_face, **{k: v for k, v in headers.items()},
        },
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
COLORS_RGB = {
    "board": (0.31, 0.51, 0.74),
    "rad360": (0.66, 0.80, 0.42),
    "rad420": (0.88, 0.54, 0.23),
    "psu": (0.56, 0.49, 0.76),
    "gpu": (0.42, 0.66, 0.31),
    "cpu": (0.75, 0.31, 0.30),
    "io_pod": (0.90, 0.75, 0.30),
    "frame": (0.75, 0.75, 0.75),
}
LABELS = {
    "board": "плата ATX",
    "rad360": "360",
    "rad420": "420",
    "psu": "БП",
    "gpu": "GPU",
    "cpu": "CPU",
    "io_pod": "I/O",
}


def export_files(comps, frame_parts) -> None:
    assy = cq.Assembly(name="B5_components")
    for name, wp in comps.items():
        r, g, b = COLORS_RGB[name]
        assy.add(wp, name=name, color=cq.Color(r, g, b))
    assy.save(os.path.join(OUT, "b5_assembly.step"))
    cq.exporters.export(
        cq.Compound.makeCompound([shape_of(wp) for wp in comps.values()]),
        os.path.join(OUT, "b5_assembly.stl"),
    )
    frame_assy = cq.Assembly(name="B5_frame")
    fr, fg, fb = COLORS_RGB["frame"]
    solids = []
    for p in frame_parts:
        frame_assy.add(p.solid, name=p.name, color=cq.Color(fr, fg, fb))
        solids.append(shape_of(p.solid))
    frame_assy.save(os.path.join(OUT, "b5_frame.step"))
    cq.exporters.export(
        cq.Compound.makeCompound(solids), os.path.join(OUT, "b5_frame.stl")
    )
    all_assy = cq.Assembly(name="B5_all")
    for name, wp in comps.items():
        r, g, b = COLORS_RGB[name]
        all_assy.add(wp, name=name, color=cq.Color(r, g, b))
    for p in frame_parts:
        all_assy.add(p.solid, name=p.name, color=cq.Color(fr, fg, fb, 0.5))
    all_assy.save(os.path.join(OUT, "b5_all.step"))


# ---------------------------------------------------------------------------
# 2D / 3D previews
# ---------------------------------------------------------------------------
def world_box_corners(xmin, xmax, ymin, ymax, zmin, zmax, board_space=False):
    pts = []
    for x in (xmin, xmax):
        for y in (ymin, ymax):
            for z in (zmin, zmax):
                pts.append(board_point(x, y, z) if board_space else (x, y, z))
    return pts


def component_corners():
    slot_s = GPU_SLOT_FRAC * BOARD_LEN
    cpu_s = CPU_FRAC * BOARD_LEN
    hx = BOARD_W / 2.0
    return {
        "board": world_box_corners(-hx, hx, 0, BOARD_LEN, -BOARD_T, 0, True),
        "rad360": world_box_corners(
            -RAD360_X / 2, RAD360_X / 2, RAD360_Y0, RAD360_Y0 + RAD360_Y,
            RAD360_Z0, RAD360_Z0 + RAD360_Z),
        "rad420": world_box_corners(
            -RAD420_X / 2, RAD420_X / 2, RAD420_Y0, RAD420_Y0 + RAD420_Y,
            RAD420_Z0, RAD420_Z0 + RAD420_Z),
        "psu": world_box_corners(
            -PSU_W / 2, PSU_W / 2, PSU_Y0, PSU_Y0 + PSU_D, PSU_Z0, PSU_Z0 + PSU_H),
        "gpu": world_box_corners(
            -GPU_LEN / 2, GPU_LEN / 2, slot_s - GPU_THICK, slot_s, 0, GPU_H, True),
        "cpu": world_box_corners(
            -CPU_XY / 2, CPU_XY / 2, cpu_s - CPU_XY / 2, cpu_s + CPU_XY / 2, 0, CPU_H, True),
        "io_pod": world_box_corners(IOD_X0, IOD_X1, IOD_Y0, IOD_Y1, IOD_Z0, IOD_Z1),
    }


def frame_aabb_corners(frame_parts):
    out = []
    for p in frame_parts:
        if p.name.startswith("spine_"):
            continue
        b = bbox_of(shape_of(p.solid))
        out.append(world_box_corners(b.xmin, b.xmax, b.ymin, b.ymax, b.zmin, b.zmax))
    hx = BOARD_W / 2.0
    split_s = BOARD_LEN / 2.0
    z0 = -(BOARD_T + SPINE_GAP + WALL)
    z1 = -(BOARD_T + SPINE_GAP)
    out.append(world_box_corners(-hx, hx, 0, split_s, z0, z1, True))
    out.append(world_box_corners(-hx, hx, split_s, BOARD_LEN, z0, z1, True))
    return out


_FACES = (
    (0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
    (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3),
)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    l = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / l, a[1] / l, a[2] / l)


ISO_VIEW = _norm((1.0, 1.0, -1.0))
ISO_RIGHT = _norm((1.0, -1.0, 0.0))
ISO_UP = _norm(_cross(ISO_RIGHT, ISO_VIEW))


def project(p, kind):
    x, y, z = p
    if kind == "front":
        return (x, z)
    if kind == "side":
        return (y, z)
    return (_dot(p, ISO_RIGHT), _dot(p, ISO_UP))


def face_depth(face, kind):
    c = (sum(v[0] for v in face) / 4, sum(v[1] for v in face) / 4, sum(v[2] for v in face) / 4)
    if kind == "front":
        return c[1]
    if kind == "side":
        return -c[0]
    return _dot(c, ISO_VIEW)


def face_front_facing(face, kind):
    n = _cross(_sub(face[1], face[0]), _sub(face[2], face[0]))
    view = {"front": (0, 1, 0), "side": (-1, 0, 0)}.get(kind, ISO_VIEW)
    return _dot(n, view) < -1e-9


def collect_faces(src, kind, is_frame=False):
    items = []
    seq = src if is_frame else src.items()
    if is_frame:
        for corners in src:
            for idx in _FACES:
                face = [corners[i] for i in idx]
                if face_front_facing(face, kind):
                    items.append((face_depth(face, kind), None, face))
    else:
        for name, corners in src.items():
            for idx in _FACES:
                face = [corners[i] for i in idx]
                if face_front_facing(face, kind):
                    items.append((face_depth(face, kind), name, face))
    items.sort(key=lambda t: t[0], reverse=True)
    return items


def draw_view(ax, kind, title, cc, frame_cs, anchors):
    ax.set_title(title, fontsize=11, pad=8)
    ax.set_aspect("equal")
    ax.set_facecolor("white")
    ax.grid(True, color="0.9", lw=0.6)
    ax.tick_params(labelsize=7)
    for _, _, face in collect_faces(frame_cs, kind, is_frame=True):
        poly = [project(v, kind) for v in face]
        ax.fill(*zip(*poly), facecolor=(0.82, 0.82, 0.82, 0.16),
                edgecolor=(0.45, 0.45, 0.45, 0.4), linewidth=0.4, zorder=1)
    vis = {n: [] for n in cc}
    for _, name, face in collect_faces(cc, kind):
        poly = [project(v, kind) for v in face]
        rgb = COLORS_RGB[name]
        ax.fill(*zip(*poly), facecolor=(*rgb, 0.93),
                edgecolor=(0.12, 0.12, 0.12, 0.85), linewidth=0.7, zorder=2)
        vis[name].extend(poly)
    if kind == "side":
        y0 = RAD420_Y0 + RAD420_Y
        z0, z1 = RAD420_Z0, RAD420_Z0 + RAD420_Z
        ax.fill([y0, y0 + RAD420_EXHAUST, y0 + RAD420_EXHAUST, y0],
                [z0, z0, z1, z1],
                facecolor=(0.4, 0.6, 0.9, 0.12), edgecolor=(0.3, 0.45, 0.7, 0.7),
                linestyle="--", linewidth=0.8, zorder=1.5)
        ax.text(y0 + RAD420_EXHAUST / 2, z1 + 8, "выхлоп 25 мм",
                ha="center", va="bottom", fontsize=7, color="#3d5a8a")
    for name, pts in vis.items():
        if not pts:
            continue
        if name in anchors.get(kind, {}):
            x, y = anchors[kind][name]
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


def render_preview(comps, frame_parts, checks, path):
    cc = component_corners()
    fc = frame_aabb_corners(frame_parts)
    anchors = {
        "front": {
            "rad360": (0, RAD360_Z0 + RAD360_Z / 2 - 6),
            "psu": (0, PSU_Z0 + PSU_H + 4),
            "rad420": (-RAD420_X / 2 + 40, RAD420_Z0 + RAD420_Z + 4),
            "board": (0, BOARD_Z0 + BOARD_LEN * C + 6),
            "gpu": (0, 210),
            "cpu": (0, 270),
            "io_pod": ((IOD_X0 + IOD_X1) / 2, IOD_Z1 + 6),
        },
        "side": {
            "rad360": (RAD360_Y0 + RAD360_Y / 2, RAD360_Z0 + RAD360_Z + 6),
            "psu": (PSU_Y0 + 70, PSU_Z0 + PSU_H / 2),
            "rad420": (RAD420_Y0 + RAD420_Y / 2, RAD420_Z0 + RAD420_Z / 2),
            "board": (260, 230),
            "gpu": (145, 255),
            "cpu": (255, 290),
            "io_pod": ((IOD_Y0 + IOD_Y1) / 2, IOD_Z1 + 6),
        },
        "iso": {},
    }
    fig = plt.figure(figsize=(16.8, 7.0), facecolor="white")
    views = [
        ("iso", "Изометрия (спереди-слева-сверху)"),
        ("front", "Вид спереди"),
        ("side", "Вид сбоку (перед слева)"),
    ]
    axes = [fig.add_subplot(1, 3, i + 1) for i in range(3)]
    for ax, (kind, title) in zip(axes, views):
        draw_view(ax, kind, title, cc, fc, anchors)
    handles = [
        Patch(facecolor=COLORS_RGB[n], edgecolor="k", label=LABELS[n])
        for n in ("board", "rad360", "rad420", "psu", "gpu", "cpu", "io_pod")
    ]
    handles.append(Patch(facecolor=(0.82, 0.82, 0.82), edgecolor="0.4", label="каркас"))
    fig.legend(handles=handles, loc="lower center", ncol=8, frameon=False,
               fontsize=8, bbox_to_anchor=(0.5, -0.01))
    fig.suptitle(
        "Вариант B5, блочный объём  ·  360 спереди, плата 45°, 420 за платой, I/O справа",
        fontsize=13, y=0.98,
    )
    plt.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(path, dpi=130, facecolor="white")
    plt.close(fig)


def render_layout_2d(path):
    """Standalone front + side 2D layout, same style as layout_b4.png."""
    fig, (a, b) = plt.subplots(1, 2, figsize=(15.5, 8.2))

    def r(ax, x, y, w, h, col, t, **k):
        ax.add_patch(Rectangle((x, y), w, h, fc=col, ec="k", lw=1.5, **k))
        ax.text(x + w / 2, y + h / 2, t, ha="center", va="center", fontsize=8)

    # FRONT
    r(a, -RAD360_X / 2, RAD360_Z0, RAD360_X, RAD360_Z, "#a9cc6b",
      "радиатор 360 (394), лежит слева направо\nверх вентиляторов = низ платы")
    H = BOARD_LEN * C
    r(a, -BOARD_W / 2, BOARD_Z0, BOARD_W, H, "#4f81bd", "", alpha=0.9)
    a.text(0, BOARD_Z0 + H - 22,
           "плата ATX 244 шир., наклон 45° от нас\n(видна высота ~216 из 305)",
           ha="center", fontsize=8, color="w")
    r(a, -35, BOARD_Z0 + H - 95, 70, 50, "#c0504d", "CPU")
    r(a, -GPU_LEN / 2, BOARD_Z0 + 40, GPU_LEN, 52, "#6aa84f", "GPU 280 (на плате)")
    a.add_patch(Rectangle((-RAD420_X / 2, RAD420_Z0), RAD420_X, RAD420_Z,
                          fc="none", ec="#e08a3a", lw=2, ls="--"))
    a.text(-RAD420_X / 2 + 8, RAD420_Z0 + 8, "420 (458) за платой, пунктир",
           fontsize=8, color="#b86a1c")
    r(a, -229, 10, 32, 80, "#e8c03a", "USB\nC\njack")
    r(a, 197, 10, 32, 56, "#e8c03a", "PWR")
    a.set_title("Вид спереди (смотрим на плату)")
    a.set_xlim(-280, 280)
    a.set_ylim(-30, 470)

    # SIDE
    x0 = BOARD_Y0
    bx = [x0, x0 + H, x0 + H + 8, x0 + 8]
    by = [BOARD_Z0, BOARD_Z0 + H, BOARD_Z0 + H - 8, BOARD_Z0 - 8]
    b.add_patch(Polygon(list(zip(bx, by)), fc="#4f81bd", ec="k"))
    b.text(x0 + H / 2 + 25, BOARD_Z0 + H / 2 - 15, "плата 45°",
           rotation=45, color="w", fontsize=9)
    r(b, RAD360_Y0, RAD360_Z0, RAD360_Y, RAD360_Z, "#a9cc6b", "360\n121×55")
    r(b, RAD420_Y0, RAD420_Z0, RAD420_Y, RAD420_Z, "#e08a3a", "420\n65×138\nна ребре")
    r(b, PSU_Y0, PSU_Z0, PSU_D, PSU_H, "#8e7cc3", "БП 210×86", alpha=0.7)
    r(b, 4, 10, 22, 80, "#e8c03a", "I/O", alpha=0.85)
    # GPU
    gx, gy = x0 + H * 0.45, BOARD_Z0 + H * 0.45
    n = (-C, C)
    t = (C, C)
    # thickness goes down the board, so from slot along -t
    p0 = (gx, gy)
    p1 = (gx - t[0] * GPU_THICK, gy - t[1] * GPU_THICK)
    p2 = (p1[0] + n[0] * GPU_H, p1[1] + n[1] * GPU_H)
    p3 = (p0[0] + n[0] * GPU_H, p0[1] + n[1] * GPU_H)
    b.add_patch(Polygon([p0, p1, p2, p3], fc="#6aa84f", ec="k"))
    b.text(gx - 55, gy + 60, "GPU", fontsize=9)
    # exhaust
    y0 = RAD420_Y0 + RAD420_Y
    b.add_patch(Rectangle((y0, RAD420_Z0), RAD420_EXHAUST, RAD420_Z,
                          fc="none", ec="#3d5a8a", lw=1.2, ls="--"))
    b.text(y0 + 2, RAD420_Z0 + RAD420_Z + 6, "выхлоп 25", fontsize=7, color="#3d5a8a")
    b.annotate("", xy=(x0, BOARD_Z0), xytext=(x0, 0),
               arrowprops=dict(arrowstyle="-", ls="--"))
    b.set_title("Вид сбоку (перед слева)")
    b.set_xlim(-20, 480)
    b.set_ylim(-30, 470)
    for ax in (a, b):
        ax.set_aspect("equal")
        ax.grid(alpha=0.3)
        ax.set_xlabel("мм")
        ax.set_ylabel("мм")
    fig.suptitle(
        "Вариант B5: 360 спереди, 420 за платой, I/O в щелях по бокам 360 (USB слева, питание справа)  ·  мм",
        fontsize=12,
    )
    plt.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def format_report(comps, frame_parts, checks) -> str:
    bb, env = checks["bb"], checks["env"]
    lines: list[str] = []
    w = lines.append
    w("B5 CAD block-out  /  mm  (radiators swapped vs B4)")
    w("=" * 64)
    w("Placement decisions:")
    w("  • Board stays at Y=150, Z=65. Lowering it to 55 would drop the wedge")
    w("    and the taller 420 would hit the board.")
    w("  • Front 360 is raised 10 mm (Z 10..65) so fan tops line up with the")
    w("    board bottom. The 10 mm plinth is an intake gap.")
    w("  • In the old 360 slot the 420 already intersects the board (~0.8 mm).")
    w("    It is 17 mm taller and 10 mm thicker. Moved back and up:")
    w(f"      420 at Y {RAD420_Y0:.0f}..{RAD420_Y0+RAD420_Y:.0f}, Z {RAD420_Z0:.0f}..{RAD420_Z0+RAD420_Z:.0f}")
    w("    giving 15 mm shortest distance to the board back and 20 mm to the PSU top.")
    w("  • PSU stays 150 along X, 210 along Y, 86 tall, but is shifted back")
    w(f"    to Y {PSU_Y0:.0f}..{PSU_Y0+PSU_D:.0f} so the IEC inlet at Y={PSU_Y0+PSU_D:.0f}")
    w("    sits behind the 25 mm exhaust and stays reachable from the rear.")
    w("    Cables come out at the front of the PSU, under the board.")
    w("  • Front I/O pod is reserved on the right (X 212..302, Y 8..98, Z 8..72),")
    w("    in the width freed by the narrower 360 (394 vs 458) and the shallower")
    w("    front (starts at Y=29 vs 12).")
    w("")
    w("Components:")
    for name, wp in comps.items():
        b = bbox_of(shape_of(wp))
        w(f"  {name:8s}  X {b.xmin:7.1f}..{b.xmax:7.1f}   "
          f"Y {b.ymin:7.1f}..{b.ymax:7.1f}   "
          f"Z {b.zmin:7.1f}..{b.zmax:7.1f}")
    w("")
    w("Interference (pairwise intersection volume, must be 0):")
    for a, b, vol in checks["inter"]:
        flag = "FAIL" if vol > VOL_EPS else "ok"
        w(f"  {a:8s} × {b:8s}  {vol:10.4f} mm3   {flag}")
    w("RESULT: " + (
        "INTERFERENCE DETECTED" if checks["bad"]
        else "no interference (all intersection volumes ~ 0)"
    ))
    w("")
    w("Minimum gaps between neighbours:")
    for a, b, d, tag in checks["gaps"]:
        w(f"  {a:8s} – {b:8s}  {d:7.1f} mm   {tag}")
    w("")
    w("Bounding box of the iron (components + I/O pod):")
    w(f"  X {bb.xmin:.1f} .. {bb.xmax:.1f}   ({bb.xmax-bb.xmin:.1f})")
    w(f"  Y {bb.ymin:.1f} .. {bb.ymax:.1f}   ({bb.ymax-bb.ymin:.1f})")
    w(f"  Z {bb.zmin:.1f} .. {bb.zmax:.1f}   ({bb.zmax-bb.zmin:.1f})")
    w("Envelope including frame, 20 mm PSU gap stack, 25 mm exhaust:")
    w(f"  X {env['xmin']:.1f} .. {env['xmax']:.1f}   ({env['xmax']-env['xmin']:.1f})")
    w(f"  Y {env['ymin']:.1f} .. {env['ymax']:.1f}   ({env['ymax']-env['ymin']:.1f})")
    w(f"  Z {env['zmin']:.1f} .. {env['zmax']:.1f}   ({env['zmax']-env['zmin']:.1f})")
    w("")
    w(f"Tube reach (straight × {TUBE_SLACK:.2f} slack vs rated length):")
    for t in checks["tubes"]:
        ps = "PASS" if t["pass_straight"] else "FAIL"
        w(f"  {t['name']}")
        w(f"    straight {t['straight']:.0f} mm  →  need {t['straight_need']:.0f}  /  {t['limit']:.0f}  {ps}")
        if abs(t["path"] - t["straight"]) > 0.5:
            pp = "PASS" if t["pass_path"] else "FAIL"
            w(f"    routed path {t['path']:.0f} mm  →  need {t['path_need']:.0f}  /  {t['limit']:.0f}  {pp}")
    w("")
    w("Front-panel cables (I/O pod → headers, path around the 360, ×1.30 slack):")
    for c in checks["cables"]:
        flag = "PASS" if c["pass"] else "FAIL"
        w(f"  {c['name']}")
        w(f"    straight {c['straight']:.0f}  path {c['path']:.0f}  →  need {c['path_need']:.0f}  /  {c['limit']:.0f}  {flag}")
    w("")
    w("Printable frame parts (each ≤ 290 mm):")
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
    w("")
    w("Issues / watch-outs:")
    w("  • The swap is possible, but the rear 420 no longer fits in the old 360")
    w("    pocket. The case is deeper (~460 vs ~405) because the 420 had to")
    w("    move back and the PSU had to follow so the IEC stays reachable.")
    w("  • 20 mm between PSU top and 420 is better than 4 mm, but a top-mounted")
    w("    PSU fan is still tight. Prefer a bottom intake (vented base) or a")
    w("    rear/side intake. The IEC is at Y=447, below the 420's exhaust.")
    w("  • 360 sits on a 10 mm plinth; cut a grille in it if the 360 intakes down,")
    w("    or blow it up into the board/GPU (similar chimney to B4, slightly more")
    w("    front space).")
    w("  • Blow the 420 backward, away from the board (Y 418..443 is free).")
    w("  • CPU tubes must go around or over the board to the rear 420. Same-side")
    w("    or over-the-top routes should be used; fittings on one end of the 420,")
    w("    not opposite corners.")
    w("  • GPU tubes to the front 360 are short and stay in front of the board.")
    w("    Same-side fittings are easiest; opposite-side also likely fine.")
    w("  • I/O pod is on the right, next to JUSB3 / JUSBC1 / JFP1. Route the")
    w("    USB 3 and USB-C cables around the 360's right end, not through it.")
    w("    Typical 500 mm USB 3 and USB-C cables reach with plenty of slack.\n    JAUD1 sits on the opposite (left) edge: a stock 500 mm HD-audio cable is\n    short, so plan a 700 mm front-audio extension along the front lip.")
    w("  • Rear I/O of the board is still at the top edge (~Y 366, Z 281),")
    w("    45° up-back, above the 420 (top Z=244).")
    w("  • The organic frame v1 is a volume sketch: skiff base, left/right rails,")
    w("    filleted I/O pod, spine, 360 plinth and 420 cradles. Split joints and")
    w("    real hollowing / grilles come later.")
    return "\n".join(lines) + "\n"


def main() -> None:
    comps = build_components()
    print("Building frame…")
    frame_parts = build_frame()
    print("Running checks…")
    checks = run_checks(comps)

    mount_ok = {
        ("rad360_stop_left", "rad360"),
        ("rad360_stop_right", "rad360"),
        ("rad420_cradle_left", "rad420"),
        ("rad420_cradle_right", "rad420"),
        ("io_pod_shell", "io_pod"),
        ("plinth_360_left", "rad360"),
        ("plinth_360_right", "rad360"),
    }
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

    preview = os.path.join(OUT, "preview_b5.png")
    layout = os.path.join(ROOT, "layout_b5.png")
    print("Rendering previews…")
    render_preview(comps, frame_parts, checks, preview)
    render_layout_2d(layout)
    print(f"Preview: {preview}")
    print(f"Layout:  {layout}")
    print("Done.")


if __name__ == "__main__":
    main()
