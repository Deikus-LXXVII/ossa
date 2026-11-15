#!/usr/bin/env python3
"""B6 «Шатёр»: hardware block-out and mounting interfaces.

Single source of truth for every hardware dimension, its placement and the
coordinates of its mounting holes. frame_v0.py imports everything from here.

World, mm: X right (seen from the front), Y depth (front = 0, grows backwards),
Z up. Hardware zero Z = 0; the desk plane is Z = -15.

Board space (v, u, n): v from the rear-I/O edge along the 244 side, u from the
bottom edge along the 305 side (towards the CPU), n out of the component face.
The board is tilted 45 deg about X:
    bp(v, u, n) = (-122 + v, 60 + (u - n) C, 30 + (u + n) C),  C = cos 45
"""

from __future__ import annotations

import math

import cadquery as cq
from cadquery import Solid, Vector, Wire

C = math.cos(math.radians(45.0))
TILT_DEG = 45.0
ORIGIN = (-122.0, 60.0, 30.0)          # board-space origin in world coordinates
DESK_Z = -15.0

N_DIR = (0.0, -C, C)                   # board normal (n), world
U_DIR = (0.0, C, C)                    # along the 305 side, world


# ---------------------------------------------------------------------------
# Transforms and box helpers
# ---------------------------------------------------------------------------
def bp(v: float, u: float, n: float) -> tuple[float, float, float]:
    return (ORIGIN[0] + v, ORIGIN[1] + (u - n) * C, ORIGIN[2] + (u + n) * C)


def bp_yz(u: float, n: float) -> tuple[float, float]:
    """(Y, Z) of a board-space point; independent of v."""
    return (ORIGIN[1] + (u - n) * C, ORIGIN[2] + (u + n) * C)


def x_to_v(x: float) -> float:
    return x - ORIGIN[0]


def bs_of(x: float, y: float, z: float) -> tuple[float, float, float]:
    """(v, u, n) of a world point: the inverse of bp."""
    a, b = (y - ORIGIN[1]) / C, (z - ORIGIN[2]) / C        # u - n and u + n
    return (x - ORIGIN[0], (a + b) / 2, (b - a) / 2)


def to_board(shape) -> Solid:
    """A world shape expressed in board space (v, u, n), as (x, y, z): the inverse of bs_box's placement."""
    moved = shape.translate(Vector(-ORIGIN[0], -ORIGIN[1], -ORIGIN[2]))
    return moved.rotate(Vector(0, 0, 0), Vector(1, 0, 0), -TILT_DEG)


def bs_box(v0, v1, u0, u1, n0, n1) -> Solid:
    """Axis-aligned in (v, u, n), rotated +45 deg about X, moved by ORIGIN."""
    b = Solid.makeBox(v1 - v0, u1 - u0, n1 - n0, Vector(v0, u0, n0))
    b = b.rotate(Vector(0, 0, 0), Vector(1, 0, 0), TILT_DEG)
    return b.translate(Vector(*ORIGIN))


def wbox(x0, x1, y0, y1, z0, z1) -> Solid:
    return Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, Vector(x0, y0, z0))


def bs_cyl(radius, v, u, n0, n1) -> Solid:
    """Cylinder with its axis along n, centred at (v, u), from n0 to n1, placed like bs_box."""
    c = Solid.makeCylinder(radius, n1 - n0, Vector(v, u, n0), Vector(0, 0, 1))
    c = c.rotate(Vector(0, 0, 0), Vector(1, 0, 0), TILT_DEG)
    return c.translate(Vector(*ORIGIN))


def hose_chain(points, radius, transition: str = "round") -> Solid:
    """A circle of `radius` swept along the polyline `points` (world), round at the joints: the union of a
    cylinder per segment and a sphere per interior joint, built as one sweep because fusing fifty
    cylinders and spheres took 5 s per hose. Both ends are flat, square to the first and last segment, so
    the chain touches the collar it leaves and the box of the port it enters instead of burying a
    hemisphere in them."""
    pts = [Vector(*p) for p in points]
    path = Wire.makePolygon(pts)
    start = Wire.makeCircle(radius, pts[0], (pts[1] - pts[0]).normalized())
    out = cq.Workplane().add(start).toPending().sweep(cq.Workplane().add(path), transition=transition).val()
    assert out.isValid() and len(out.Solids()) == 1, "hose sweep failed"
    return out


# ---------------------------------------------------------------------------
# Hardware dimensions (boxes)
# ---------------------------------------------------------------------------
BOARD_BS = (0, 244, 0, 305, -2, 0)
# PCIe slot centrelines along u (slot 1..7, pitch 20.32). Measured on the scan of the real board
# (refs/board_scan_overlay.png): PCI_E1 is ATX slot 6. The card's PCB sits on the centreline and
# its cooler lies towards smaller u: 51 thick, 2.5 mm allowed on the back side.
SLOT_U = [22.48, 42.80, 63.12, 83.44, 103.76, 124.08, 144.40]
GPU_SLOT_U = SLOT_U[5]
GPU_BS = (-2, 278, 75.6, 126.6, 0, 150)

# CPU socket centre (v, u) measured on the same scan, +-3 mm.
CPU_SOCKET_VU = (134.0, 217.0)
# Reference keep-outs read off the scan, +-5 mm (see KEEP_OUT below): memory slots with modules,
# 24-pin connector with plug, EPS 8-pin with plug.
DIMMS_BS = (183, 221, 146, 290, 0, 45)           # read off the scan: slots span u 146..291; u1 290 because the EPS box starts there
ATX24_BS = (226, 244, 190, 246, 0, 40)
EPS_BS = (178, 230, 290, 305, 0, 40)
# CPU block (ARCTIC LF3 Pro 420 2D drawing, refs/arctic_block_side_measured.png): a round body and a
# lug with the two fittings on the side that faces the graphics card (towards smaller u). The hose
# leaves each collar square to the board. Collars are treated as fixed.
CPU_BODY_R, CPU_BODY_TOP_N = 45.5, 76.0
CPU_BASE_N = 7.5                                   # cold plate above the board (CPU package height, approx.)
CPU_COLLAR_RISE = 67.2                             # collar top above the cold plate
CPU_COLLAR_TOP_N = round(CPU_BASE_N + CPU_COLLAR_RISE, 3)         # 74.7, also the lug top
CPU_COLLAR_U = round(CPU_SOCKET_VU[1] - 54.6, 3)   # collar axis, 54.6 mm from the socket centre towards smaller u
CPU_LUG_HALF_V = 22.0
CPU_LUG_U = (round(CPU_SOCKET_VU[1] - 62.97, 3), CPU_SOCKET_VU[1] - 40.0)
CPU_COLLAR_HALF_SPACING = 11.9                     # the two collars are 23.8 apart about the socket centre in v

# Hoses: the routes are in hoses.py; the keep-outs are chains of cylinders along them with the hose
# radius plus an allowance. Hose radii: ARCTIC OD 12.4, the GPU's OD 11.2 measured on the 5090 sister card.
CPU_HOSE_R, GPU_HOSE_R = 6.2, 6.0
HOSE_ALLOW = 1.8
CPU_HOSE_KEEP_R = CPU_HOSE_R + HOSE_ALLOW           # 8.0
GPU_HOSE_KEEP_R = GPU_HOSE_R + HOSE_ALLOW           # 7.8

RAD360_INNER_N = 122.0                             # the 360's inner face, raised from 90 (owner accepted 122)
RAD360_BS = (-75, 319, 184, 305, RAD360_INNER_N, RAD360_INNER_N + 55)   # core n 122..152 (inner), fans n 152..177 (outer)
RAD360_CORE_N = (RAD360_INNER_N, RAD360_INNER_N + 30)
RAD360_FAN_N = (RAD360_INNER_N + 30, RAD360_INNER_N + 55)
# 420 at 90 deg to the board behind its top edge (board space), ported core face towards the board (u = 310),
# fans on the outer face (u = 378) blowing down-slope along the board. 68 mm stack (ARCTIC spec: 38 core + 27 fan
# + hardware), 138 mm wide in n, 458 long in v. Its underside is the plane n = -15, a 45 deg face rising to the back.
RAD420_BS = (-107, 351, 310, 378, -15, 123)
RAD420_CORE_U = (310, 348)
RAD420_FAN_U = (351, 378)
RAD420_MID_N = (RAD420_BS[4] + RAD420_BS[5]) / 2       # 54
# Ports (ARCTIC drawing page 2, refs/arctic_radiator_ports_*.png): two collars stand on the FACE of one end
# tank, square to it, 8.4 mm in from the radiator's end, 23.8 mm apart about the middle of the 138 mm width,
# collar diameter 20, top 20 mm above the core face. They are not axial. The MSI 360's ports are like ARCTIC's.
RAD420_PORT_INSET, RAD420_PORT_HALF_SPACING = 8.4, 11.9
RAD360_PORT_INSET = RAD420_PORT_INSET
RAD420_PORT_D, RAD420_PORT_RISE = 20.0, 20.0
PSU_W = (-75, 75, 165, 375, 0, 86)              # Seasonic PRIME TX-1600 Noctua Edition (120 mm fan), fan face up, IEC Y = 375, modular Y = 165

# Revision 7: the two 140 x 140 x 25 fans stand on the flanks, one under each end of the 360, blowing OUT. Positions
# come from a clash study against the model: the CPU hoses run down the left flank at X = -221 and the GPU hoses rise
# at X = +189, so the left fan sits 21 mm further in than the right one. Edges along the board's u and n, thickness
# along X. Hole axes along X, four corners on the 124.5 mm pattern about the box centre in (u, n).
FAN_SIDE_X = {"fan_side_right": (201.0, 226.0), "fan_side_left": (-205.0, -180.0)}
FAN_SIDE_INNER_X = {"fan_side_right": 201.0, "fan_side_left": -180.0}     # the face towards the board
FAN_SIDE_IN = {"fan_side_right": -1, "fan_side_left": 1}                  # direction of X towards the board
FAN_SIDE_U, FAN_SIDE_N = (120.0, 260.0), (-42.0, 98.0)
FAN_PITCH = 124.5
FAN_APERTURE_D = 134.0                                                     # open diameter that no bracket may enter
FAN_CENTRE_UN = ((FAN_SIDE_U[0] + FAN_SIDE_U[1]) / 2, (FAN_SIDE_N[0] + FAN_SIDE_N[1]) / 2)
# corner holes (u, n): A low u / low n, B high u / low n, C low u / high n, D high u / high n (n up = away from the board)
FAN_SIDE_HOLES_UN = {
    "A": (FAN_CENTRE_UN[0] - FAN_PITCH / 2, FAN_CENTRE_UN[1] - FAN_PITCH / 2),
    "B": (FAN_CENTRE_UN[0] + FAN_PITCH / 2, FAN_CENTRE_UN[1] - FAN_PITCH / 2),
    "C": (FAN_CENTRE_UN[0] - FAN_PITCH / 2, FAN_CENTRE_UN[1] + FAN_PITCH / 2),
    "D": (FAN_CENTRE_UN[0] + FAN_PITCH / 2, FAN_CENTRE_UN[1] + FAN_PITCH / 2),
}
FAN_SIDE_NAMES = tuple(FAN_SIDE_X)


def fan_side_bs(name):
    """Board-space box (v0, v1, u0, u1, n0, n1) of a side fan."""
    x0, x1 = FAN_SIDE_X[name]
    return (x_to_v(x0), x_to_v(x1), FAN_SIDE_U[0], FAN_SIDE_U[1], FAN_SIDE_N[0], FAN_SIDE_N[1])

# ---------------------------------------------------------------------------
# Revision 9: the front I/O module of the owner's Fractal North XL and the light line, both on the front sill.
# EVERYTHING IN THIS BLOCK IS A PLACEHOLDER until the owner has measured the module: the box, the screw positions, the strip's place.
# ---------------------------------------------------------------------------
# PLACEHOLDER until the module is measured: the module with its housing, world x0, x1, y0, y1, z0, z1 (165 x 42 x 36). The ports face forwards
# and upwards through the sill's 45 deg face, parallel to the board, so a plug goes in along the board's normal.
FRONT_IO_W = (-70.0, 95.0, 0.0, 42.0, 10.0, 46.0)
# Ports in a row along X, as read off refs/north_io_front_measured.png (7.3 px/mm on the USB-A shells; the panel measures 208 mm, which is the
# North's width). Centre to centre, +-1 mm. The module has no reset button.
FRONT_IO_ROW = ("power button", "headphone jack", "microphone jack", "USB-A", "USB-A", "USB-C")
FRONT_IO_PITCH = (22.1, 15.1, 18.2, 22.2, 20.4)         # between consecutive entries of FRONT_IO_ROW
FRONT_IO_OFFSETS = tuple(round(sum(FRONT_IO_PITCH[:k]), 2) for k in range(len(FRONT_IO_ROW)))     # from the power button's centre
FRONT_IO_BUTTON_D = 18.0                                # cap, about
FRONT_IO_ROW_EXTENT = 112.0                             # from the button's outer edge to the USB-C's outer edge, about
FRONT_IO_LED_SLIT_BEYOND = 43.0                         # the power-LED slit runs this far beyond the USB-C, about
# PLACEHOLDER: the module's mounting. Two screws along X into the end walls of the sill's pocket: (x, y, z) on the module's end face and
# the direction out of the module into the holder. Thread, positions, and whether the module has ears at all are not known.
FRONT_IO_SCREWS = (((-70.0, 21.0, 28.0), (-1.0, 0.0, 0.0)), ((95.0, 21.0, 28.0), (1.0, 0.0, 0.0)))
FRONT_IO_SCREW_KIND = "M3"                              # key of INSERTS
FRONT_IO_N_MAX = max(bs_of(x, y, z)[2] for x in FRONT_IO_W[:2] for y in FRONT_IO_W[2:4] for z in FRONT_IO_W[4:])   # the module's highest point along the board's normal

# PLACEHOLDER position: the light line, a reserved channel for an LED strip and its diffuser along the upper edge of the sill's face, over the
# whole width. 14 x 14 mm in section, aligned with the board (u along the face, n out of it), behind the module's top face and clear of the
# module in u. The sill is designed around the module, so this moves with it.
LIGHT_STRIP_X = (-135.0, 135.0)
LIGHT_STRIP_SECTION = (14.0, 14.0)                      # (along u, along n)
LIGHT_STRIP_U0 = -9.0
LIGHT_STRIP_BS = (x_to_v(LIGHT_STRIP_X[0]), x_to_v(LIGHT_STRIP_X[1]), LIGHT_STRIP_U0, LIGHT_STRIP_U0 + LIGHT_STRIP_SECTION[0],
                  FRONT_IO_N_MAX - LIGHT_STRIP_SECTION[1], FRONT_IO_N_MAX)
# The intended build-up (owner's translucent PLA; not geometry yet): the strip is up to 12 mm wide and sits on the sill (ABS), never on the
# diffuser (PLA); at least 10 mm from the LEDs to the diffuser, which is 1.6 mm thick and shows as a 4 mm line. The channel stays open at both
# ends so it breathes: a full-white strip in a closed 14 x 14 channel can pass 50 deg C, PLA softens at 55..60.
LIGHT_STRIP_W_MAX = 12.0
LIGHT_LED_TO_DIFFUSER_MIN = 10.0
LIGHT_DIFFUSER_T = 1.6
LIGHT_LINE_W = 4.0
FRONT_HARDWARE = ("front_io", "light_strip")           # in front of the front plane they must not reach either (check 8)

PSU_REAR_Y = 375.0

# Owner's rule (revision 5): nothing may stick out past the radiators' ends (|X| <= 229) or in front of the
# front fans (Y >= 0), because a passer-by could catch it. Frame parts and hose keep-outs are both held to it.
ENVELOPE_X = float(RAD420_BS[1] - RAD420_BS[0]) / 2          # 229
ENVELOPE_Y0 = 0.0                                            # the front plane (it was the front fans' face until revision 7)
# Revision 6: no frame part may rise above the 420's top edge. The 420 stands at 45 deg, so "above" is meant in board space:
# the top face of the radiator is the plane n = RAD420_BS[5] and a part reaching past it stands above the radiator seen from
# the side. (In world Z a 10 mm plate behind the fan face is always higher than the radiator's highest corner.)
ENVELOPE_N = float(RAD420_BS[5])                             # 123

# ---------------------------------------------------------------------------
# Mounting interfaces
# ---------------------------------------------------------------------------
# ATX 2.03/2.2 mounting holes (v, u), research report, not yet measured on the owner's board.
# Hole F sits at v = 33.02, not on the rear column (v = 10.16).
ATX_HOLE_D = 3.96
ATX_HOLES_NAMED = {
    "A": (10.16, 16.51), "C": (10.16, 140.97), "F": (33.02, 298.45),
    "G": (165.10, 16.51), "H": (165.10, 140.97), "J": (165.10, 298.45),
    "K": (237.49, 16.51), "L": (237.49, 140.97), "M": (237.49, 298.45),
}
ATX_HOLES = list(ATX_HOLES_NAMED.values())
ATX_ROWS_U = (16.51, 140.97, 298.45)
ATX_STANDOFF_H = 6.35
ATX_BOARD_N = -2.0                       # board underside
ATX_TRAY_N = ATX_BOARD_N - ATX_STANDOFF_H  # tray (beam) surface, -8.35

# rad420 threaded holes on the outer (fan) face u = RAD420_BS[3] (6-32): world X, and n = middle of the width +- 62.25
RAD420_HOLES_X = (-202.25, -77.75, -62.25, 62.25, 77.75, 202.25)
RAD420_HOLES_N = (RAD420_MID_N - 62.25, RAD420_MID_N + 62.25)

# rad360 inner-face threaded holes (n = RAD360_INNER_N): world X and u
RAD360_HOLES_X = (-172.5, -67.5, -52.5, 52.5, 67.5, 172.5)
RAD360_HOLES_U = (192.0, 297.0)

# PSU rear face 150 x 86, 6-32 holes from the lower-left corner seen from behind with the PSU upright.
# The Noctua Edition sits with its fan up and the AC inlet on the viewer's right, which is world -X, and
# the standard pattern applies in that view: world x = 75 - x_hole, z = y_hole.
PSU_FACE_W, PSU_FACE_H = 150.0, 86.0
PSU_PATTERN_FACE = [(6.0, 80.0), (144.0, 80.0), (6.0, 16.0), (120.0, 6.0)]
PSU_PATTERN = [(PSU_FACE_W / 2 - x, z) for (x, z) in PSU_PATTERN_FACE]          # 4 screws
PSU_HOLES = list(PSU_PATTERN)

# Airflow. 420: fans on its outer face (u 351..378) blow down-slope along the board through the core.
# 360: fans on its outer face (n 152..177) blow in from the front face, towards the board.
# Revision 7: the 360 and the 420 fans blow IN; the two 140 mm side fans (one under each end of the 360, on the flanks)
# blow OUT. Air comes in through both radiators, passes over the board and leaves sideways. There are no front fans.

# PLACEHOLDER: n of the surface the card bracket's tab screws onto
GPU_BRACKET_TAB_N = 108.0

# Heat-set insert pilots (ruthex RX): diameter, depth, minimum wall around the pilot
M3_PILOT_D, M3_PILOT_DEPTH, M3_MIN_WALL = 4.0, 6.7, 1.6
M4_PILOT_D, M4_PILOT_DEPTH, M4_MIN_WALL = 5.6, 9.1, 2.1
M4S_PILOT_D, M4S_PILOT_DEPTH, M4S_MIN_WALL = 5.6, 5.0, 2.1     # short RX-M4Sx4.0
INSERTS = {
    "M3": (M3_PILOT_D, M3_PILOT_DEPTH, M3_MIN_WALL),
    "M4": (M4_PILOT_D, M4_PILOT_DEPTH, M4_MIN_WALL),
    "M4S": (M4S_PILOT_D, M4S_PILOT_DEPTH, M4S_MIN_WALL),
}
M4_CLEAR_D = 4.5
M3_CLEAR_D = 4.0                            # also 6-32
M5_CLEAR_D = 5.5

# Rear I/O aperture plus 50 mm for plugs and cable bend. Keep-out volume, not a component.
IO_ZONE_BS = (-50, 0, 148.49, 307.24, -3.81, 40.64)
# The port collars on the core face of the 420 (left-hand end) and on the inner face of the 360 (right-hand end),
# with a small margin. The hose keep-outs stop at these boxes; they are not hoses.
RAD420_PORTS_BS = (-111, -86, 288, 310, 30, 78)
RAD360_PORTS_BS = (298, 323, 220, 269, 100, 122)
KEEP_OUT = ("io_zone", "dimms", "atx24", "eps", "rad420_ports", "rad360_ports", "cpu_hoses", "gpu_hoses", "light_strip")
HOSES = ("cpu_hoses", "gpu_hoses")

# ---------------------------------------------------------------------------
# Cables (research of 15 Nov 2026, docs/plans/cables-and-organic.md, "## Cables"). The routes are in cables.py.
# ---------------------------------------------------------------------------
# Board headers, (v, u) on the board. STANDING: positions scaled off the manual's drawing, about +-5 mm; ATX_PWR1 and the
# two EPS headers agree with the keep-outs measured on the board scan (ATX24_BS, EPS_BS). A header's top is HEADER_TOP_N above the board face.
HEADERS = {
    "ATX_PWR1": (239.0, 220.0), "CPU_PWR1": (190.0, 299.0), "CPU_PWR2": (205.0, 299.0), "JFP1": (235.0, 5.0),
    "JUSB3": (239.0, 160.0), "JUSBC1": (239.0, 110.0), "JAUD1": (20.0, 5.0), "CPU_FAN1": (225.0, 299.0),
    "PUMP_SYS1": (239.0, 290.0), "SYS_FAN1": (239.0, 270.0), "SYS_FAN2": (45.0, 299.0), "SYS_FAN3": (20.0, 135.0),
    "JARGB_V2_1": (55.0, 5.0),
}
HEADER_TOP_N = 12.0                       # ASSUMPTION: a header stands 12 mm proud of the board (plan)

# Sockets on the PSU's modular face (Y = PSU_W[2]), world (X, Y, Z). STANDING: INFERRED from a photo taken fan down, NOT CHECKED. Seen from
# the front with the fan up: the CPU/PCIe field on the left (-X), the two 12V-2x6 in the centre, the motherboard pair on the right (+X).
# The positions are the plan's, only the side is read off the photo.
PSU_SOCKETS = {
    "mb": (48.0, PSU_W[2], 43.0), "eps1": (-52.0, PSU_W[2], 30.0), "eps2": (-36.0, PSU_W[2], 30.0), "gpu": (0.0, PSU_W[2], 43.0),
}

# Cables: name -> (real length in mm or None, radius, minimum bend radius). STANDING: lengths of the PSU's own cables are Seasonic's spec
# sheet (ATX 24-pin 610, EPS 700, 12V-2x6 700); "None" = unknown (front I/O cables of the Fractal North XL, the ARCTIC PWM lead, the light line,
# which is still to be chosen); 400 for the two side fans is the research's TYPICAL length ("400 or more"), not measured.
# Radii and minimum bends are ASSUMPTIONS (the cable's outer size was not found; the build is individually sleeved wires with combs).
# gpu12v: the socket on the card is known now (GPU_PWR_SOCKET below, read off MSI's render); its 35 mm straight at the plug is the plan's.
CABLES = {
    "atx24": (610.0, 12.0, 30.0), "eps1": (700.0, 6.0, 20.0), "eps2": (700.0, 6.0, 20.0), "gpu12v": (700.0, 7.0, 35.0),
    "usb3": (None, 4.0, 15.0), "usbc": (None, 4.0, 15.0), "jfp1": (None, 2.0, 8.0), "jaud1": (None, 2.0, 8.0),
    "argb": (None, 2.0, 8.0), "cpu_fan": (None, 2.0, 8.0), "fan_right": (400.0, 2.0, 8.0), "fan_left": (400.0, 2.0, 8.0),
}
GPU12V_STRAIGHT = 35.0                    # straight length at the 12V-2x6 plug

# Second pass of the cables (docs/plans/cables-and-organic.md, "Second pass: spec for cad_b6/cables.py").
# The 12V-2x6 socket on the MSI RTX 5080 SUPRIM LIQUID, in board space. STANDING: read off MSI's render (refs/gpu_5080_suprim_liquid_power.png) with a
# projective fit, NOT MEASURED: +-12 mm along v, +-3 mm along u, +-8 mm in the recess. v is 132 mm from the bracket end of the lettering face,
# u is 7 mm below the backplate edge. The socket sits in a notch on the face that looks away from the board: the centre of its mouth is
# `recess` below that face (n = GPU_BS[5] - recess) and the plug enters along -n, so the cable leaves along +n.
GPU_PWR_SOCKET = dict(v=130.0, u=119.0, recess=13.0)
GPU12V_PLUG = 13.0                        # ASSUMPTION: how far the plug's back stands out of the socket's mouth; GPU12V_STRAIGHT counts from it
# Lying headers: the socket is on the board's edge and the plug enters along -v from outside it. STANDING: JUSBC1 is a lying socket at u 103..116,
# v 232..244 on the board scan (refs/board_scan_overlay.png, refs/usbc_under_card.png). The plug is centred thick / 2 above the board face.
HEADERS_LYING = ("JUSBC1",)
LYING_PLUG = dict(length=15.0, thick=8.0)  # ASSUMPTION (a USB-C plug body with its strain relief)
# ASSUMPTION: the card's lower edge beyond the slot is level with the slot's top, 11 mm above the board face (the model's card box reaches the
# board, n 0). Used by the USB-C route only, to pass under the card's body. The owner confirmed on 15 Nov 2026 that the front USB-C port works
# in the present PC with this board and this card, so a lying plug does fit under the card; the 11 mm itself is still not measured.
GPU_UNDERSIDE_N = 11.0
# OWNER DECISION, 15 Nov 2026: the 12V-2x6 cable may stand in front of the front plane (Y = ENVELOPE_Y0). The card's face looks forward and up
# and a straight plug with its 35 mm straight cannot arch lower. Accepted as measured, 10.4 mm; the limit leaves 0.6 mm for rebuilds.
GPU12V_FRONT_TOL = 11.0
# ASSUMPTION: where a bundle of sleeved wires passes the 20 mm gap at the board's edge it lies two wires thick, flat. Modelled as that many
# round strands side by side along u: strand radius, centre pitch, minimum bend. Strands: ATX 24-pin 6, 12V-2x6 4.
CABLE_SLAB = {"atx24": 6, "gpu12v": 4}
SLAB_STRAND_R = 4.0
SLAB_PITCH = 8.0
SLAB_BEND = 15.0


def cpu_block_solid() -> Solid:
    """Round body plus the lug that carries the two collars, fused. Board space, n out of the board."""
    sv, su = CPU_SOCKET_VU
    body = bs_cyl(CPU_BODY_R, sv, su, 0, CPU_BODY_TOP_N)
    lug = bs_box(sv - CPU_LUG_HALF_V, sv + CPU_LUG_HALF_V, CPU_LUG_U[0], CPU_LUG_U[1], 0, CPU_COLLAR_TOP_N)
    return body.fuse(lug).clean()


def hose_solid(name: str, start: Solid) -> Solid:
    """Keep-out of one pair: both hoses of hoses.routes() as swept chains, fused, with the component they
    leave (`start`, the CPU block or the card) cut away, so the chain begins on its surface."""
    import hoses                       # hoses.py imports this module for its constants
    r = CPU_HOSE_KEEP_R if name == "cpu_hoses" else GPU_HOSE_KEEP_R
    a, b = hoses.keepout_chains()[name]
    return hose_chain(a, r).fuse(hose_chain(b, r)).cut(start).clean()


# ---------------------------------------------------------------------------
def build_hardware() -> dict[str, Solid]:
    hw: dict[str, Solid] = {}
    hw["board"] = bs_box(*BOARD_BS)
    hw["gpu"] = bs_box(*GPU_BS)
    hw["cpu_block"] = cpu_block_solid()
    hw["rad360"] = bs_box(*RAD360_BS)
    hw["rad420"] = bs_box(*RAD420_BS)
    hw["psu"] = wbox(*PSU_W)
    for name in FAN_SIDE_NAMES:
        hw[name] = bs_box(*fan_side_bs(name))
    hw["front_io"] = wbox(*FRONT_IO_W)
    hw["io_zone"] = bs_box(*IO_ZONE_BS)
    hw["dimms"] = bs_box(*DIMMS_BS)
    hw["atx24"] = bs_box(*ATX24_BS)
    hw["eps"] = bs_box(*EPS_BS)
    hw["rad420_ports"] = bs_box(*RAD420_PORTS_BS)
    hw["rad360_ports"] = bs_box(*RAD360_PORTS_BS)
    hw["cpu_hoses"] = hose_solid("cpu_hoses", hw["cpu_block"])
    hw["gpu_hoses"] = hose_solid("gpu_hoses", hw["gpu"])
    hw["light_strip"] = bs_box(*LIGHT_STRIP_BS)
    return hw


HW_COLORS = {
    "board": "#4f7fbf", "gpu": "#5aa13c", "cpu_block": "#b84040",
    "rad420": "#e08a2e", "rad360": "#a6cc5c", "psu": "#a99bd0",
    "fan_side_right": "#6fb3b8", "fan_side_left": "#6fb3b8", "io_zone": "#c0507a",
    "dimms": "#d6c14a", "atx24": "#3fa7a0", "eps": "#8a5fc9",
    "rad420_ports": "#c25a00", "rad360_ports": "#7a8f00", "cpu_hoses": "#1a1a1c", "gpu_hoses": "#6b3d1f",
    "front_io": "#d4a017", "light_strip": "#f2e45a",
}
