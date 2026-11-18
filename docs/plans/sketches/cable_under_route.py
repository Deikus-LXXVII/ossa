"""The card's power cable under the organic layer (the owner, 18 Nov 2026: "no need to run the card's power cable over the bio-design panel, it can go under it; the main
thing is that there is room for the connector").

What cannot change: the socket opens along +n at the card's top edge (v 130, u 119, mouth n 137), and the plug (13 mm), the straight (35 mm) and the first bend (R 35) stand
up from it to n 220. The layer's face there is at n 168 to 170.5. So the cable's first 70 mm always stand out of the layer, and the layer needs an opening at the connector.

What can change is where the cable goes after that. Today it runs outside the layer for 135 mm, over to X 131.5, and comes down through the lip. Here it comes straight back
down beside the connector, into the gap between the card (u up to 126.6) and the 360 (u from 184), and runs under the film to X 131.5, where it joins its old way down.

This script searches that route with cables.py's own checks. Run from the repository root:  .venv/bin/python docs/plans/sketches/cable_under_route.py [--all]
"""
import itertools
import os
import sys

import numpy as np

ROOT = os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "cad_b6"))
import hardware as hw
import frame_v0
import cables
from cables import B, Sec, Route, V_GAP

GS = hw.GPU_PWR_SOCKET
MOUTH_N = hw.GPU_BS[5] - GS["recess"]
SLAB_U = cables.GAP_U["gpu12v"]


def under_wps(n_a, v_d, u_d, n_run):
    """The slab's top, up the gap to n_a, over to the foot of the loop under the film, up the loop's far leg, over the arch, down into the socket."""
    return [B(V_GAP, SLAB_U, cables.GPU12V_SLAB_TOP_N), B(V_GAP, SLAB_U, n_a), B(v_d, u_d, n_run), B(v_d, u_d, cables.GPU12V_TOP_N),
            B(GS["v"], GS["u"], cables.GPU12V_TOP_N), B(GS["v"], GS["u"], MOUTH_N)]


def route_with(wps):
    secs = cables.waypoints_all()["gpu12v"]
    secs[2] = Sec("round", wps, "gpu12v")
    return Route("gpu12v", secs, own_leg=cables.OUT_LEG.get("gpu12v"))


def judge(rt, others, targets, gpu_under, slots):
    cables.evaluate_route(rt, targets, gpu_under, slots)
    pairs = cables.route_pair_distances({**others, "gpu12v": rt}, names=("gpu12v",))
    fails = [t for _c, t in rt.fail] + [f"overlaps {b if a == 'gpu12v' else a}" for a, b, d in pairs if d <= 1e-6]
    least = min(rt.clear, key=lambda c: c[1] - c[2])
    return fails, least, pairs[0]


def main():
    hware = hw.build_hardware()
    parts, _ = frame_v0.build_frame(hardware=hware)
    targets, gpu_under = cables.route_targets(parts, hware)
    slots = cables.tie_slots(parts)
    others = {k: v for k, v in cables.build_routes().items() if k != "gpu12v"}
    for rt in others.values():
        rt.build()
    grid = itertools.product((60.0, 70.0, 80.0), (185.0, 195.0, 205.0), (148.0, 156.0, 164.0), (105.0, 120.0, 135.0)) if "--all" in sys.argv else [tuple(float(a) for a in sys.argv[1:5])]
    rows = []
    for n_a, v_d, u_d, n_run in grid:
        rt = route_with(under_wps(n_a, v_d, u_d, n_run))
        fails, least, pair = judge(rt, others, targets, gpu_under, slots)
        rows.append((len(fails), -(least[1] - least[2]), n_a, v_d, u_d, n_run, rt, fails, least, pair))
        print(f"n_a {n_a:.0f} v_d {v_d:.0f} u_d {u_d:.0f} n_run {n_run:.0f}: {'pass' if not fails else str(len(fails)) + ' FAIL'}; length {rt.length:.0f}; least bend {min(r for _k, r, _b in rt.bend_checks):.1f}; "
              f"front {hw.ENVELOPE_Y0 - rt.ymin:.1f}; tightest {least[0]} {least[1]:.1f} (needs {least[2]:g}); nearest cable {pair[0]} x {pair[1]} {pair[2]:.1f}" + ("" if not fails else "\n      " + "; ".join(fails)[:300]), flush=True)
    rows.sort(key=lambda r: (r[0], r[1]))
    print("best:", [f"n_a {r[2]:.0f} v_d {r[3]:.0f} u_d {r[4]:.0f} n_run {r[5]:.0f} ({r[0]} fails, margin {-r[1]:.1f})" for r in rows[:5]])


if __name__ == "__main__":
    main()
