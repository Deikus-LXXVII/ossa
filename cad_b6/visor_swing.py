#!/usr/bin/env python3
"""How far can the 360 radiator ("visor") be lifted for access to the RAM and CPU block?

Run:  .venv/bin/python cad_b6/visor_swing.py

The visor turns about an axis along X. Its hoses stay connected, so the lift is limited by
 - the visor hitting the 420 radiator or the CPU hoses, and
 - the GPU hoses, whose spare length lies in the run behind the board.
Two hinge positions are compared. For the GPU hoses the table gives the shortest length the drawn
route can shrink to with the port moved; "—" means the drawn route shape no longer fits its bend
radii at that angle, which says nothing about tautness (the hose would take another shape).
"""
from __future__ import annotations

import math
import os
import sys

import cadquery as cq
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hardware as hw
import hoses

TAUT_MARGIN = 3.0          # mm of hose kept in hand when calling it taut
MIN_GAP = 2.0              # mm; closer than this counts as a hit

PIVOTS = {
    "за верхней кромкой, под радиатором (как в модели)": (290.0, 115.0),
    "на внешнем верхнем углу радиатора": (303.0, 185.0),
}


def rot_un(u, n, pu, pn, deg):
    """Rotate a board-space (u, n) point about the pivot; positive lifts the visor's lower lip."""
    a = math.radians(deg)
    du, dn = u - pu, n - pn
    return pu + du * math.cos(a) + dn * math.sin(a), pn - du * math.sin(a) + dn * math.cos(a)


def visor_solid(pu, pn, deg):
    v0, v1, u0, u1, n0, n1 = hw.RAD360_BS
    corners = [rot_un(u, n, pu, pn, deg) for u, n in ((u0, n0), (u1, n0), (u1, n1), (u0, n1))]
    yz = [hw.bp(0, u, n)[1:] for u, n in corners]
    x0, x1 = hw.bp(v0, 0, 0)[0], hw.bp(v1, 0, 0)[0]
    wp = cq.Workplane("YZ").polyline(yz).close().extrude(x1 - x0)
    return wp.val().translate(cq.Vector(x0, 0, 0))


def gpu_min_length(pu, pn, deg):
    """Shortest admissible length of each GPU hose with the port moved by the lift."""
    card_v = hw.GPU_BS[1]
    card_u = (hw.GPU_BS[2] + hw.GPU_BS[3]) / 2
    port_v = hw.RAD360_BS[1] - 8.4
    vis_u = (hw.RAD360_BS[2] + hw.RAD360_BS[3]) / 2
    tip_n = hw.RAD360_BS[4] - 20.0
    out = []
    for start_n, lane_v, port_u in ((60.0, card_v + 60, vis_u - hoses.GPU_PORT_PITCH),
                                    (35.0, card_v + 35, vis_u + hoses.GPU_PORT_PITCH)):
        best = None
        for depth in np.arange(start_n - 70.0 if start_n >= 70 else 70.0 - start_n, 121.0, 2.0):
            tu, tn = rot_un(port_u, tip_n, pu, pn, deg)
            # the point "below" the port along its own axis, at the depth of the hidden run
            bu, bn = rot_un(port_u, -depth, pu, pn, deg)
            pts, length, rmin, _ = hoses.fillet_path(
                hoses.B((card_v, card_u, start_n), (lane_v, card_u, start_n), (lane_v, card_u, -depth),
                        (port_v, bu, bn), (port_v, tu, tn)), [35, 35, 35])
            if rmin >= hoses.BEND_R - 0.5 and (best is None or length < best):
                best = length
        out.append(best)
    return out


def main():
    hware = hw.build_hardware()
    r420, cpu_hoses, block = hware["rad420"], hware["cpu_hoses"], hware["cpu_block"]
    for label, (pu, pn) in PIVOTS.items():
        print(f"\nОсь: {label} (u {pu:.0f}, n {pn:.0f})")
        print(f"{'угол':>5} {'подъём кромки':>14} {'до 420':>7} {'до шлангов CPU':>15} {'шланги GPU, мин. длина':>24}")
        limit = {}
        for deg in range(0, 61, 5):
            solid = visor_solid(pu, pn, deg)
            lip_u, lip_n = rot_un(hw.RAD360_BS[2], hw.RAD360_BS[4], pu, pn, deg)
            lift = lip_n - hw.RAD360_BS[4]
            d420 = solid.distance(r420)
            dhose = solid.distance(cpu_hoses)
            lens = gpu_min_length(pu, pn, deg)
            taut = any(l is not None and l > hoses.GPU_HOSE["length"] - TAUT_MARGIN for l in lens)
            if d420 < MIN_GAP:
                limit.setdefault("радиатор 420", deg)
            if dhose < MIN_GAP:
                limit.setdefault("шланги процессора", deg)
            if taut:
                limit.setdefault("натяжение шлангов видеокарты", deg)
            ltxt = " / ".join("—" if l is None else f"{l:.0f}" for l in lens)
            print(f"{deg:>5} {lift:>14.0f} {d420:>7.1f} {dhose:>15.1f} {ltxt:>24}")
        if limit:
            first = min(limit.values())
            print("  первое ограничение:", ", ".join(k for k, v in limit.items() if v == first), f"на {first}°;",
                  "остальные:", ", ".join(f"{k} на {v}°" for k, v in limit.items() if v != first) or "нет")
        else:
            print("  до 60° ограничений нет")


if __name__ == "__main__":
    main()
