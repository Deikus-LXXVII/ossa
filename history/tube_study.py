#!/usr/bin/env python3
# ARCHIVED (revision 5): studies the CPU hose of the vertical 420 of revisions 1-4; superseded by cad_b6/hoses.py and cad_b6/hose_routes.py. Not maintained, imports from cad_b6/ may no longer work.
"""CPU hose routing study for layout B6: length and clearance of candidate routes.

Run:  .venv/bin/python cad_b6/tube_study.py
Out:  a table on stdout and previews/b6_tube_study.png

The hose is one centreline swept with the hose radius. The real cooler has two hoses side by side,
12 mm either side of this line in v, so a clearance below about 15 mm sideways needs a closer look.
Lengths are polyline lengths; real bends are arcs and come out slightly shorter.
"""
from __future__ import annotations

import math
import os
import sys

import cadquery as cq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frame_v0
import hardware as hw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HOSE_R = 6.2                    # ARCTIC: OD 12.4
HOSE_LEN = 500.0
RULE = 1.30                     # HANDOFF rule: path x 1.3 <= hose
FIT = 19.0                      # fixed fittings past the 420's end face (ARCTIC drawing)
BEND = 45.0                     # straight run kept clear in front of an axial fitting

SOCKET_V, SOCKET_U = hw.CPU_SOCKET_VU
# Measured on ARCTIC's 2D drawing (LF3 Pro 420 2D Drawing.pdf, side view, 8.78 px/mm from the 108.47
# and 68.5 dimensions): the fitting leaves the pump body sideways, turns 90 deg, and the hose leaves
# the collar square to the board. Collar axis 54.6 mm from the block centre, collar top 67.2 mm above
# the cold plate. Owner: the lug faces the graphics card and the collars are taken as fixed.
BLOCK_R, BLOCK_TOP_N = 45.5, 76.0
BASE_N = 7.5                                    # cold plate above the board (CPU package height, approx.)
COLLAR_U = SOCKET_U - 54.6
COLLAR_TOP_N = BASE_N + 67.2
LUG_U = SOCKET_U - (108.47 - BLOCK_R)
BEND_R = 35.0                                   # assumed minimum bend radius of the 12.4 mm hose


def bs(v, u, n):
    return hw.bp(v, u, n)


def v_of(x):
    return hw.x_to_v(x)


def capsule(p, q, r):
    a, b = cq.Vector(*p), cq.Vector(*q)
    d = b - a
    seg = cq.Solid.makeCylinder(r, d.Length, a, d.normalized())
    return seg.fuse(cq.Solid.makeSphere(r).translate(a)).fuse(cq.Solid.makeSphere(r).translate(b))


def hose(points):
    out = None
    for p, q in zip(points, points[1:]):
        c = capsule(p, q, HOSE_R)
        out = c if out is None else out.fuse(c)
    return out


def length(points, r=BEND_R):
    """Polyline length with every interior corner rounded to radius r."""
    total = sum(math.dist(p, q) for p, q in zip(points, points[1:]))
    for a, b, c in zip(points, points[1:], points[2:]):
        u1 = [b[i] - a[i] for i in range(3)]
        u2 = [c[i] - b[i] for i in range(3)]
        n1, n2 = math.hypot(*u1), math.hypot(*u2)
        cosang = max(-1.0, min(1.0, sum(x * y for x, y in zip(u1, u2)) / (n1 * n2)))
        theta = math.acos(cosang)
        total -= 2 * r * math.tan(theta / 2) - r * theta
    return total


def block_solids():
    body = cq.Solid.makeCylinder(BLOCK_R, BLOCK_TOP_N, cq.Vector(SOCKET_V, SOCKET_U, 0), cq.Vector(0, 0, 1))
    lug = cq.Solid.makeBox(44, SOCKET_U - BLOCK_R + 8 - LUG_U, COLLAR_TOP_N - 2, cq.Vector(SOCKET_V - 22, LUG_U, 0))
    shape = body.fuse(lug).rotate(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), 45.0)
    return shape.translate(cq.Vector(*hw.bp(0, 0, 0)))


# Radiator ports, measured on page 2 of the same drawing (refs/arctic_radiator_ports_*.png): the two
# fittings stand on the FACE of the end tank, square to it, 8.4 mm in from the radiator's end, 23.8 mm
# apart about the centre of the 138 mm width, collar top 20 mm above the core face. They are not axial.
PORT_INSET, PORT_RISE = 8.4, 20.0


def routes(box, visor_n0):
    """420 box (x0,x1,y0,y1,z0,z1) with the ported core face towards the board (y0)."""
    x0, x1, y0, y1, z0, z1 = box
    zc = (z0 + z1) / 2
    start = [bs(SOCKET_V, COLLAR_U, COLLAR_TOP_N), bs(SOCKET_V, COLLAR_U, COLLAR_TOP_N + BEND_R)]
    out = {}
    for label, px in (("к правому концу 420", x1 - PORT_INSET), ("к левому концу 420", x0 + PORT_INSET)):
        tip = (px, y0 - PORT_RISE, zc)
        out[label] = start + [(px, y0 - PORT_RISE - BEND, zc), tip]
    return out


def analyse(name, pts, hardware, parts):
    solid = hose(pts)
    hits, near = [], []
    for label, other in list(hardware.items()) + [(p.name, p.solid) for p in parts]:
        d = solid.distance(other)
        if d <= 0.01:
            vol = solid.intersect(other).Volume()
            if vol > 1.0:
                hits.append(f"{label} {vol / 1000:.1f} см³")
                continue
        if d < 8.0:
            near.append(f"{label} {d:.1f}")
    raw = length(pts)
    return dict(name=name, raw=raw, need=raw * RULE, slack=(HOSE_LEN - raw) / HOSE_LEN, hits=hits, near=near,
                pts=pts)


CASES = [
    # name, 420 box (x0,x1,y0,y1,z0,z1), distance of the 360 from the board
    ("420 по центру, 360 в 90 мм от платы", (-229, 229, 287, 355, 246, 384), 90.0),
    ("420 по центру, 360 в 122 мм от платы", (-229, 229, 287, 355, 246, 384), 122.0),
    ("420 по центру, 360 в 115 мм от платы", (-229, 229, 287, 355, 246, 384), 115.0),
]


def main():
    parts, _ = frame_v0.build_frame()
    moved = ("neck", "visor_arm")                          # move with the 360
    frame = [p for p in parts if not p.name.startswith(moved)]
    rows = []
    for name, box, visor_n0 in CASES:
        hardware = dict(hw.build_hardware())
        for keep in ("cpu_hoses", "rad420_ports"):         # keep-outs derived from this kind of route, not obstacles for it
            hardware.pop(keep, None)
        hardware["cpu_block"] = block_solids()
        hardware["rad420"] = hw.wbox(*box)
        v0, v1, u0, u1, n0, n1 = hw.RAD360_BS
        hardware["rad360"] = hw.bs_box(v0, v1, u0, u1, visor_n0, visor_n0 + (n1 - n0))
        for rname, pts in routes(box, visor_n0).items():
            r = analyse(f"{name}, {rname}", pts, hardware, frame)
            rows.append(r)
    print(f"{'вариант':60} {'путь':>5} {'запас':>6}  пересечения | ближе 8 мм")
    for r in rows:
        print(f"{r['name']:60} {r['raw']:5.0f} {r['slack'] * 100:5.0f}%  "
              f"{', '.join(r['hits']) or 'нет'} | {', '.join(r['near']) or 'нет'}")
    return rows


if __name__ == "__main__":
    main()
