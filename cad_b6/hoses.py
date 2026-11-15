#!/usr/bin/env python3
"""Hose routes for both coolers: the geometry only (no rendering, no analysis).

Depends on hardware.py constants and numpy. hardware.build_hardware() turns these routes into the
cpu_hoses / gpu_hoses keep-outs, hose_routes.py measures and draws them. Every waypoint is typed
here and nowhere else.

A hose has a fixed length, so each path is drawn to use almost all of it: the spare is kept in
generous curves that can be tightened if the real hose turns out shorter.

Routes are in board space (v, u, n). Each pair is two arches on a flank of the board.
"""
from __future__ import annotations

import functools
import math

import numpy as np

import hardware as hw

CPU_HOSE = dict(length=500.0, r=hw.CPU_HOSE_R, min_bend=35.0)
GPU_HOSE = dict(length=450.0, r=hw.GPU_HOSE_R, min_bend=35.0)     # OD 11.2 measured on the 5090 sister card
CPU_SPARE, GPU_SPARE = 18.0, 15.0        # hose left over after the drawn path
SOCKET_V, SOCKET_U = hw.CPU_SOCKET_VU
BEND_R = 35.0
LANE_U = 152.0                           # CPU pair: u of the run just below the visor's lower lip
LANE_PITCH = 11.5                        # half the spacing of the two CPU hoses on that run
FLANK_RUN = 40.0                         # straight run square to the 420 face in front of a CPU port
GPU_PORT_PITCH = 12.0                    # half the spacing of the GPU hoses at the 360's ports
SAMPLE_STEP = 3.0                        # mm between sampled points of a route
CHAIN_EVERY = 3                          # the keep-out chain uses every third sample


def bs(v, u, n):
    return np.array(hw.bp(v, u, n))


def world_to_bs(p):
    """Inverse of hw.bp: (v, u, n) of a world point."""
    dy, dz = p[1] - hw.ORIGIN[1], p[2] - hw.ORIGIN[2]
    return (p[0] - hw.ORIGIN[0], (dy + dz) * hw.C, (dz - dy) * hw.C)


def fillet_path(points, radii, step=SAMPLE_STEP):
    """Straight runs joined by circular arcs: waypoints P0..Pm, one radius per interior waypoint.
    Where two neighbouring arcs do not both fit on the run between them, both are reduced in
    proportion. Returns sampled points, exact length, the smallest radius actually used and the unit
    tangents of the first and last run."""
    P = [np.array(p, dtype=float) for p in points]
    m = len(P)
    seg = [P[i + 1] - P[i] for i in range(m - 1)]
    seglen = [float(np.linalg.norm(d)) for d in seg]
    unit = [d / l for d, l in zip(seg, seglen)]
    theta = [0.0] * m
    tan = [0.0] * m
    for i in range(1, m - 1):
        theta[i] = math.acos(float(np.clip(unit[i - 1] @ unit[i], -1, 1)))
        tan[i] = radii[i - 1] * math.tan(theta[i] / 2)
    for _ in range(3):
        for i in range(m - 1):                      # run i lies between waypoints i and i + 1
            need = tan[i] + tan[i + 1]
            if need > seglen[i] > 0:
                k = seglen[i] / need
                tan[i] *= k
                tan[i + 1] *= k
    out, length, rmin = [P[0]], 0.0, float("inf")
    prev = P[0]
    for i in range(1, m - 1):
        if theta[i] < 1e-3:
            continue
        d1, d2 = unit[i - 1], unit[i]
        r = tan[i] / math.tan(theta[i] / 2)
        start, end = P[i] - d1 * tan[i], P[i] + d2 * tan[i]
        m1 = d2 - (d1 @ d2) * d1
        m1 /= np.linalg.norm(m1)
        centre = start + r * m1
        run = float(np.linalg.norm(start - prev))
        length += run + r * theta[i]
        nseg = max(int(run / step), 1)
        out += [prev + (start - prev) * k / nseg for k in range(1, nseg + 1)]
        narc = max(int(r * theta[i] / step), 2)
        out += [centre + r * (-m1 * math.cos(phi) + d1 * math.sin(phi))
                for phi in np.linspace(0, theta[i], narc + 1)[1:]]
        prev = end
        rmin = min(rmin, r)
    run = float(np.linalg.norm(P[-1] - prev))
    length += run
    nseg = max(int(run / step), 1)
    out += [prev + (P[-1] - prev) * k / nseg for k in range(1, nseg + 1)]
    return np.array(out), length, rmin, (unit[0], unit[-1])


def solve(build, target, lo, hi):
    """Find the parameter for which build(x) has the target length (length grows with x)."""
    for _ in range(40):
        mid = (lo + hi) / 2
        if build(mid)[1] < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def B(*pts):
    return [bs(*p) for p in pts]


@functools.lru_cache(maxsize=1)
def routes():
    """{'cpu': (pair, spec), 'gpu': (pair, spec)}; each hose is dict(pts, length, rmin, top)."""
    r420, r360 = hw.RAD420_BS, hw.RAD360_BS
    lug_u = hw.CPU_COLLAR_U
    face_u = r420[2]
    port_v = r420[0] + hw.RAD420_PORT_INSET             # left-hand end of the 420
    port_n = (r420[4] + r420[5]) / 2
    tip_u = face_u - hw.RAD420_PORT_RISE

    def cpu(side, port_dn):
        # Nothing may stick out past the radiators' ends, so the spare length is taken up in height:
        # the hoses rise from the block to the level of the visor's outer face, run along just below
        # its lower lip to the left-hand end, and drop down the flank into the 420's port.
        # The parameter is the height of that run above the board.
        my_lane = LANE_U + side * LANE_PITCH             # the two hoses run side by side below the lip
        jog_v = 78 if side < 0 else 36                   # the nearer hose moves to its lane first
        cv = SOCKET_V + side * hw.CPU_COLLAR_HALF_SPACING

        def build(run_n):
            return fillet_path(B((cv, lug_u, hw.CPU_COLLAR_TOP_N), (cv, lug_u, run_n),
                                 (jog_v, my_lane, run_n), (port_v, my_lane, run_n),
                                 (port_v, tip_u - FLANK_RUN, port_n + port_dn), (port_v, tip_u, port_n + port_dn)),
                               [BEND_R, 40, BEND_R, BEND_R])
        return build

    h = hw.RAD420_PORT_HALF_SPACING
    cpu_a, cpu_b = cpu(-1, -h), cpu(1, h)

    card_v = hw.GPU_BS[1]
    card_u = (hw.GPU_BS[2] + hw.GPU_BS[3]) / 2
    vis_u = (r360[2] + r360[3]) / 2

    # The owner confirmed the MSI radiator's ports are like ARCTIC's: on the face of an end tank,
    # square to it, and its fans can go on either face. The fans go on the outer face, so the ports
    # are on the inner face at the right-hand end, pointing at the board, and the hose comes up into
    # them. The straight way from the card is only about 225 mm of a 450 mm hose, so the spare runs
    # out of sight: the hose turns behind the board plane beside the card's end, runs up-slope
    # behind the board's right-hand edge, and rises into the port. The parameter is how deep it runs.
    port_v_gpu = r360[1] - hw.RAD360_PORT_INSET
    port_tip_n = r360[4] - hw.RAD420_PORT_RISE

    def gpu(start_n, lane_v, port_u):
        def build(depth):
            return fillet_path(B((card_v, card_u, start_n), (lane_v, card_u, start_n),
                                 (lane_v, card_u, -depth), (port_v_gpu, port_u, -depth),
                                 (port_v_gpu, port_u, port_tip_n)),
                               [BEND_R] * 3)
        return build

    gpu_a = gpu(60, card_v + 60, vis_u - GPU_PORT_PITCH)
    gpu_b = gpu(35, card_v + 35, vis_u + GPU_PORT_PITCH)

    out = {}
    for name, builders, spec, spare in (("cpu", (cpu_a, cpu_b), CPU_HOSE, CPU_SPARE),
                                        ("gpu", (gpu_a, gpu_b), GPU_HOSE, GPU_SPARE)):
        pair = []
        for build in builders:
            lo, hi = (112.0, 260.0) if name == "cpu" else (10.0, 160.0)
            top = solve(build, spec["length"] - spare, lo, hi)
            pts, length, rmin, tangents = build(top)
            pair.append(dict(pts=pts, length=length, rmin=rmin, top=top, tangents=tangents))
        out[name] = (pair, spec)
    return out


def trim_to_box(pts, box_bs):
    """The route up to the first point inside the board-space box (v0, v1, u0, u1, n0, n1); the last
    point is the entry point on the box face. The box of a port is where the collar lives, so a keep-out
    chain stops at its face instead of burying a cylinder in it."""
    v0, v1, u0, u1, n0, n1 = box_bs

    def inside(p):
        v, u, n = world_to_bs(p)
        return v0 < v < v1 and u0 < u < u1 and n0 < n < n1

    for i in range(1, len(pts)):
        if inside(pts[i]):
            lo, hi = np.array(pts[i - 1]), np.array(pts[i])
            for _ in range(40):
                mid = (lo + hi) / 2
                if inside(mid):
                    hi = mid
                else:
                    lo = mid
            return [np.array(p) for p in pts[:i]] + [lo]
    return [np.array(p) for p in pts]


START_EXTEND = 5.0                       # a keep-out chain starts this far inside the component the hose leaves


def chain_points(pts, t0):
    """Every CHAIN_EVERY-th sample plus the last one, with the start pushed START_EXTEND back along the
    tangent t0 so that it begins inside the component the hose leaves (the caller cuts that component away,
    which leaves a flat face exactly on its surface; a chord of the first bend would tilt the end)."""
    q = [np.array(p) for p in pts[::CHAIN_EVERY]]
    if not np.allclose(q[-1], pts[-1]):
        q.append(np.array(pts[-1]))
    q[0] = q[0] - START_EXTEND * np.array(t0)
    return q


def keepout_chains():
    """{'cpu_hoses': [points, points], 'gpu_hoses': [...]}: world polylines for the keep-out solids.
    Each hose ends at the face of the port box of the radiator it enters."""
    rts = routes()
    ends = {"cpu": hw.RAD420_PORTS_BS, "gpu": hw.RAD360_PORTS_BS}
    out = {}
    for name, (pair, _spec) in rts.items():
        out[f"{name}_hoses"] = [chain_points(trim_to_box(h["pts"], ends[name]), h["tangents"][0]) for h in pair]
    return out
