#!/usr/bin/env python3
"""Cable routes of the B6 case, from docs/plans/cables-and-organic.md ("## Cables", "Build: cad_b6/cables.py").

In the manner of hoses.py: every route is a list of way-points joined with hoses.fillet_path. The facts (headers, PSU
sockets, cable radius / real length / minimum bend) are in hardware.py. Nothing here moves hardware or changes the skeleton.

Board space (v, u, n) as in hardware.py. Every way-point number the plan does not give, and every move of a plan number, is
in the tables below and is listed in report_cables.txt.

Run:  .venv/bin/python cad_b6/cables.py
Out:  cad_b6/report_cables.txt, previews/b6_cables_<view>.png; exits non-zero when a check fails (after writing both).
"""
from __future__ import annotations

import math
import os
import sys

import cadquery as cq                      # before vtk (see render_vtk.py)
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frame_v0                            # noqa: E402
import hardware as hw                      # noqa: E402
import hoses                               # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Numbers of the plan
# ---------------------------------------------------------------------------
LANE_V = hw.x_to_v(132.0)                  # right edge: 10 mm outside the board's edge (v 244), world X 132
LANE_LEFT_V = hw.x_to_v(-132.0)            # left edge
LANE_N = -45.0                             # under the board
UP_N = 35.0                                # over the board, after the edge
OUT_PSU = 45.0                             # straight run out of a PSU socket, along -Y
FRONT_START_W = (60.0, 50.0, 30.0)         # the plan's start of the front I/O cables, behind the sill (the sill has no cable exit yet); see USB_START_W / THIN_START_YZ for what is used
CLEAR_MM, HOSE_CLEAR_MM = 3.0, 5.0         # to every skeleton part / hardware solid, and to the hoses

# ---------------------------------------------------------------------------
# Numbers the plan does not give (chosen here, listed in the report)
# ---------------------------------------------------------------------------
LANE_GAP = 2.0                             # air between two cables stacked in the lane, on top of their radii
U_EDGE = -6.0                              # u at which a USB cable passes the board's bottom edge
FRONT_START_X = {"jaud1": 48.0, "jfp1": 82.0}     # along X on the plan's start line (Y 50, Z 30); usb3 is the plan's X 60
LIGHT_START_W = (-125.0, 50.0, 30.0)       # "sill end": the left end, behind the sill (only its X is used; Y and Z as THIN_START_YZ)
USB_START_W = {"usb3": (60.0, 54.0, 30.0), "usbc": (70.0, 54.0, 30.0)}   # the plan's (60, 50, 30) is 2.7 mm from the sill: Y moved +4 (r 4 would sit in it); X 70 for USB-C so the two do not start together
THIN_START_YZ = (55.0, 40.0)               # front start of JFP1, JAUD1 and the light line: the plan's (Y 50, Z 30) is 2.7 mm from the sill; Y +5 and Z +10 (11 mm) put an r 2 lead 3.5 mm off it and 4.5 mm off the board's edge
THIN_ENTRY_N = 14.0                        # n at which JFP1 and the light line meet their header (2 mm over the plug's top, one radius)
AUD_RUN = (30.0, 20.0)                     # (n, u) of JAUD1's run over the board's front strip: it descends into its header from there, over the light line
AUD_RUN_V0 = 110.0                         # v at which JAUD1 reaches the level of its run
LIGHT_PASS_UN = (14.0, 14.0)               # (u, n) at which the light line passes under JAUD1's descent, at JAUD1's header's v
SIDE_FAN_START_N = -30.0                   # n at which a side fan's lead leaves its frame
FAN_RIGHT_START_U, FAN_LEFT_START_U = 255.0, 130.0       # u at which it leaves the fan (the fans span u 120..260)
FAN_LEFT_START_V = hw.x_to_v(hw.FAN_SIDE_X["fan_side_left"][1])      # inner face of the left fan
FAN_RIGHT_START_V = hw.x_to_v(hw.FAN_SIDE_X["fan_side_right"][0])    # inner face of the right fan
PUMP_START_N = 60.0                        # where the pump lead leaves the block's wall
EPS_N_RUN = {"eps1": 44.0, "eps2": 30.0}   # EPS2 at the plan's n 30; EPS1 passes 14 mm over it (6 + 6 + 2)
U_IN = {"atx24": 45.0, "eps1": 45.0, "eps2": 90.0}    # u at which a PSU cable meets the lane (EPS2 later: its level is below the skid's top)
OUT_LEG = {"atx24": OUT_PSU, "eps1": OUT_PSU + 15.0, "eps2": OUT_PSU}   # EPS1's socket is the left one: it runs 15 mm further out so that it passes EPS2's first leg
U_LOW_B = {"usb3": 6.0, "usbc": 0.0}    # u at which a USB cable has gone under the board and turns towards the lane (the board edge and beam_low are what it steers between)
ALT_FAN_LEFT = dict(u=190.0, n=55.0)    # alternative, not the plan: over the board at n 55, see ALTERNATIVE in the report
ALT_FAN_RIGHT = dict(u=190.0, n=56.0)
LANE_CABLES = ("usbc", "usb3", "atx24", "eps1", "eps2")  # these run in the right-edge lane under the board; the lowest rise u lies on top

# The plan says "about" for the rise u; where the header is within 5 mm of the plan's number the cable rises at the header's u (so that it
# meets the header straight). Rise u = descent u. EPS2 at 265 would sit on EPS1, so it is 14 mm further (the plan gives one number for both).
PLAN_RISE = {"usbc": 110.0, "usb3": 160.0, "atx24": 220.0, "eps1": 265.0, "eps2": 279.0, "fan_right": 270.0, "fan_left": 135.0}
PLAN_EPS_RUN_U = 297.0                     # the plan: along u to 297
# Moves of a way-point, within 15 mm of the plan's number, for the clearances (each is in the report with the reason).
MOVED = {
    "rise": {"usb3": 163.0, "eps1": 261.0, "eps2": 275.5},
    "eps_run_u": 301.0,
    "lane_v": {"fan_right": 256.0},
}
OWN = {   # the two ends of a route, which it may touch
    "atx24": {"psu", "board", "atx24"}, "eps1": {"psu", "board", "eps"}, "eps2": {"psu", "board", "eps"},
    "usb3": {"front_io", "board"}, "usbc": {"front_io", "board"}, "jfp1": {"front_io", "board"}, "jaud1": {"front_io", "board"},
    "argb": {"light_strip", "board"}, "cpu_fan": {"cpu_block", "board", "eps"},      # CPU_FAN1 lies inside the EPS keep-out box
    "fan_right": {"fan_side_right", "board"}, "fan_left": {"fan_side_left", "board"},
}
HEADER_OF = {"atx24": "ATX_PWR1", "eps1": "CPU_PWR1", "eps2": "CPU_PWR2", "usb3": "JUSB3", "usbc": "JUSBC1", "jfp1": "JFP1",
             "jaud1": "JAUD1", "argb": "JARGB_V2_1", "cpu_fan": "CPU_FAN1", "fan_right": "SYS_FAN1", "fan_left": "SYS_FAN3"}
SOCKET_OF = {"atx24": "mb", "eps1": "eps1", "eps2": "eps2"}
TITLE = {"atx24": "ATX 24-pin", "eps1": "EPS 1", "eps2": "EPS 2", "gpu12v": "12V-2x6", "usb3": "USB 3 front", "usbc": "USB-C front",
         "jfp1": "Power switch", "jaud1": "Audio", "argb": "Light line", "cpu_fan": "Pump / 420 fans", "fan_right": "Right side fan",
         "fan_left": "Left side fan"}
RGB = {"atx24": (0.85, 0.10, 0.10), "eps1": (0.95, 0.55, 0.05), "eps2": (0.95, 0.80, 0.05), "usb3": (0.10, 0.35, 0.85),
       "usbc": (0.05, 0.65, 0.85), "jfp1": (0.80, 0.10, 0.75), "jaud1": (0.10, 0.70, 0.25), "argb": (0.55, 0.20, 0.85),
       "cpu_fan": (0.0, 0.0, 0.0), "fan_right": (0.60, 0.35, 0.10), "fan_left": (0.30, 0.55, 0.10)}


def B(v, u, n):
    return np.array(hw.bp(v, u, n))


def header(name):
    v, u = hw.HEADERS[HEADER_OF[name]]
    return v, u


def lane_levels(rise):
    """n of each lane cable's run under the board: the one that rises first lies on top at LANE_N, the next below it
    spaced by the two radii and LANE_GAP, so that a cable rising later passes under the ones that have gone up."""
    levels, prev = {}, None
    for name in sorted(LANE_CABLES, key=lambda k: rise[k]):
        r = hw.CABLES[name][1]
        levels[name] = LANE_N if prev is None else levels[prev] - (hw.CABLES[prev][1] + r + LANE_GAP)
        prev = name
    return levels


def waypoints(variant: str):
    """{cable: [world way-points]} for the variant "plan" (the plan's numbers), "moved" (way-points moved within 15 mm) or
    "alt" (moved, and the two side fans on a route that is not the plan's)."""
    moved = variant != "plan"
    rise = dict(PLAN_RISE)
    eps_run_u = PLAN_EPS_RUN_U
    lane_v = {}
    if moved:
        rise.update(MOVED["rise"])
        eps_run_u = MOVED["eps_run_u"]
        lane_v.update(MOVED["lane_v"])
    levels = lane_levels(rise)
    P = {}
    # ---- PSU cables: out of the socket 45 mm along -Y, to the lane under the board, up round the right edge, to the header
    for name in ("atx24", "eps1", "eps2"):
        sx, sy, sz = hw.PSU_SOCKETS[SOCKET_OF[name]]
        hv, _hu = header(name)
        u, n = rise[name], levels[name]
        pts = [np.array([sx, sy, sz]), np.array([sx, sy - OUT_LEG[name], sz]), B(LANE_V, U_IN[name], n), B(LANE_V, u, n)]
        if name == "atx24":
            pts += [B(LANE_V, u, UP_N), B(hv, u, UP_N), B(hv, u, hw.HEADER_TOP_N)]
        else:
            nr = EPS_N_RUN[name]
            pts += [B(LANE_V, u, nr), B(LANE_V, eps_run_u, nr), B(hv, eps_run_u, nr), B(hv, eps_run_u, hw.HEADER_TOP_N)]
        P[name] = pts
    # ---- front I/O cables into the lane (USB 3, USB-C)
    for name in ("usb3", "usbc"):
        x = USB_START_W[name][0]
        hv, _hu = header(name)
        u, n = rise[name], levels[name]
        v0 = hw.x_to_v(x)
        P[name] = [np.array(USB_START_W[name]), B(v0, U_EDGE, -3.0), B(v0, U_LOW_B[name], n), B(LANE_V, U_LOW_B[name], n), B(LANE_V, u, n),
                   B(LANE_V, u, UP_N), B(hv, u, UP_N), B(hv, u, hw.HEADER_TOP_N)]
    # ---- front cables that stay in front of the board: an arch over the header
    hv, hu = header("jfp1")
    P["jfp1"] = [np.array([FRONT_START_X["jfp1"], *THIN_START_YZ]), B(hv, hu, THIN_ENTRY_N)]
    hv, hu = header("argb")
    P["argb"] = [np.array([LIGHT_START_W[0], *THIN_START_YZ]), B(hw.HEADERS["JAUD1"][0], *LIGHT_PASS_UN), B(hv, hu, THIN_ENTRY_N)]
    hv, hu = header("jaud1")
    P["jaud1"] = [np.array([FRONT_START_X["jaud1"], *THIN_START_YZ]), B(AUD_RUN_V0, AUD_RUN[1], AUD_RUN[0]), B(hv, AUD_RUN[1], AUD_RUN[0]), B(hv, hu, hw.HEADER_TOP_N)]
    # ---- the pump lead: over the board from the block's wall to its header
    sv, su = hw.CPU_SOCKET_VU
    hv, hu = header("cpu_fan")
    d = np.array([hv - sv, hu - su])
    d /= np.linalg.norm(d)
    wall = (sv + hw.CPU_BODY_R * d[0], su + hw.CPU_BODY_R * d[1])
    P["cpu_fan"] = [B(wall[0], wall[1], PUMP_START_N), B(hv, wall[1], PUMP_START_N), B(hv, hu, PUMP_START_N), B(hv, hu, hw.HEADER_TOP_N)]
    # ---- the side fans: out of the fan's inner face, round the edge at the header's u, over the board to the header
    hv, _hu = header("fan_right")
    u, lv = rise["fan_right"], lane_v.get("fan_right", LANE_V)
    P["fan_right"] = [B(FAN_RIGHT_START_V, FAN_RIGHT_START_U, SIDE_FAN_START_N), B(lv, u, SIDE_FAN_START_N), B(lv, u, UP_N),
                      B(hv, u, UP_N), B(hv, u, hw.HEADER_TOP_N)]
    hv, _hu = header("fan_left")
    u = rise["fan_left"]
    P["fan_left"] = [B(FAN_LEFT_START_V, FAN_LEFT_START_U, SIDE_FAN_START_N), B(LANE_LEFT_V, u, SIDE_FAN_START_N), B(LANE_LEFT_V, u, UP_N),
                     B(hv, u, UP_N), B(hv, u, hw.HEADER_TOP_N)]
    if variant == "alt":
        hv, hu = header("fan_left")
        a = ALT_FAN_LEFT
        P["fan_left"] = [B(FAN_LEFT_START_V, a["u"], a["n"]), B(hv, a["u"], a["n"]), B(hv, hu, a["n"]), B(hv, hu, hw.HEADER_TOP_N)]
        hv, hu = header("fan_right")
        a = ALT_FAN_RIGHT
        P["fan_right"] = [B(FAN_RIGHT_START_V, a["u"], a["n"]), B(hv, hu, a["n"]), B(hv, hu, hw.HEADER_TOP_N)]
    return P, levels


def chain_solid(pts, r):
    """The route as cylinders along its sampled segments and a sphere at every joint, as a compound (not fused: a distance query
    needs no union, and the sweep of hardware.hose_chain failed on some of these paths). The segments are 3 mm long."""
    items = []
    for a, b in zip(pts[:-1], pts[1:]):
        d = cq.Vector(*(b - a))
        if d.Length < 1e-6:
            continue
        items.append(cq.Solid.makeCylinder(r, d.Length, cq.Vector(*a), d.normalized()))
    for p in pts[1:-1]:
        items.append(cq.Solid.makeSphere(r, cq.Vector(*p), angleDegrees1=-90, angleDegrees2=90))
    return cq.Compound.makeCompound(items)


class Route:
    def __init__(self, name, wps):
        self.name = name
        real, self.r, self.min_bend = hw.CABLES[name]
        self.real = real
        self.wps = wps
        pts, self.length, self.rmin, _t = hoses.fillet_path(wps, [self.min_bend] * (len(wps) - 2))
        self.pts = np.array(pts)
        self.solid = None
        self.body = None
        self.clear = []            # (target, distance, needed)
        self.fail = []

    def end_offset(self):
        """(v, u) distance of the route's end from its header."""
        if self.name not in HEADER_OF:
            return None
        v, u, _n = hoses.world_to_bs(self.pts[-1])
        hv, hu = header(self.name)
        return math.hypot(v - hv, u - hu)

    def build(self):
        self.solid = chain_solid(self.pts, self.r)
        if self.name in HEADER_OF:                     # the part of the route that is not the plug's descent: it is held off the board
            ns = np.array([hoses.world_to_bs(p)[2] for p in self.pts])
            low = hw.HEADER_TOP_N + self.r + 0.5
            k = len(ns) - 1
            while k > 0 and ns[k] <= low:
                k -= 1
            self.body = chain_solid(self.pts[:k + 1], self.r) if k > 2 else None


def evaluate(variant: str, parts, hardware):
    P, levels = waypoints(variant)
    routes = {n: Route(n, w) for n, w in P.items()}
    targets = {p.name: p.solid for p in parts}
    targets.update({f"hw:{k}": v for k, v in hardware.items()})
    for rt in routes.values():
        rt.build()
        own = {f"hw:{k}" for k in OWN[rt.name]}
        rb = frame_v0.bbox_of(rt.solid)
        for tn, ts in targets.items():
            if tn in own:
                continue
            if frame_v0.bbox_gap(rb, frame_v0.bbox_of(ts)) > 30.0:
                continue
            need = HOSE_CLEAR_MM if tn in ("hw:cpu_hoses", "hw:gpu_hoses") else CLEAR_MM
            d = frame_v0.solid_distance(rt.solid, ts)
            rt.clear.append((tn, d, need))
        if rt.body is not None and rt.name in HEADER_OF:
            d = frame_v0.solid_distance(rt.body, targets["hw:board"])
            rt.clear.append(("hw:board (route without the plug's descent)", d, CLEAR_MM))
        zmin = float(rt.pts[:, 2].min()) - rt.r
        rt.clear.append((f"desk plane Z {hw.DESK_Z:g}", zmin - hw.DESK_Z, 0.0))
        rt.clear.sort(key=lambda c: c[1] - c[2])
        # checks 1, 2, 3
        if rt.real is not None and rt.length > rt.real + 1e-6:
            rt.fail.append(f"length {rt.length:.0f} > real {rt.real:.0f}")
        if rt.rmin < rt.min_bend - 1e-6:
            rt.fail.append(f"bend {rt.rmin:.1f} < min {rt.min_bend:g}")
        for tn, d, need in rt.clear:
            if d < need - 1e-6:
                rt.fail.append(f"{d:.2f} mm from {tn}, needs {need:g}")
        off = rt.end_offset()
        if off is not None and off > 5.0:
            rt.fail.append(f"ends {off:.1f} mm from its header (scaled position +-5)")
    overlaps = []
    names = list(routes)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            d = frame_v0.solid_distance(routes[a].solid, routes[b].solid)
            overlaps.append((a, b, d))
    overlaps.sort(key=lambda t: t[2])
    return routes, levels, overlaps


def fmt_rows(routes, overlaps):
    out = [f"{'cable':16} {'route':>6} {'real':>6} {'spare':>6} {'bend':>9} {'r':>4}  {'smallest clearance':>20}  to"]
    for name in hw.CABLES:
        if name == "gpu12v":
            real, r, mb = hw.CABLES[name]
            out.append(f"{TITLE[name]:16} {'OPEN':>6} {real:6.0f} {'':>6} {'':>9} {r:4g}  socket on the card unknown, 35 mm straight at the plug, not routed")
            continue
        rt = routes[name]
        tn, d, _need = rt.clear[0]
        real = f"{rt.real:6.0f}" if rt.real is not None else f"{'n/a':>6}"
        spare = f"{rt.real - rt.length:6.0f}" if rt.real is not None else f"{'n/a':>6}"
        bend = f"{rt.rmin:5.1f}" if math.isfinite(rt.rmin) else "  -  "
        out.append(f"{TITLE[name]:16} {rt.length:6.0f} {real} {spare} {bend}/{rt.min_bend:<3g} {rt.r:4g}  {d:20.2f}  {tn}")
    out.append("")
    out.append("per route: every clearance under 10 mm, and every failed check")
    for name, rt in routes.items():
        near = [f"{tn} {d:.1f}" for tn, d, _n in rt.clear if d < 10.0]
        out.append(f"  {TITLE[name]:16} {'; '.join(near) or 'nothing under 10 mm'}")
        for f in rt.fail:
            out.append(f"  {'':16} FAIL {f}")
    touch = [(a, b, d) for a, b, d in overlaps if d < 3.0]
    out.append("route x route: smallest distances " + ", ".join(f"{TITLE[a]} x {TITLE[b]} {d:.2f}" for a, b, d in overlaps[:6]))
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render_views(parts, hardware, routes, tag="cables"):
    import vtk
    import hose_routes
    import render_vtk
    for view in render_vtk.VIEWS:
        ren = vtk.vtkRenderer()
        ren.SetBackground(1, 1, 1)
        for p in parts:
            for a in render_vtk._actors(p.solid, (0.86, 0.86, 0.86), opacity=0.55, edge_opacity=0.35):
                ren.AddActor(a)
        for name, solid in hardware.items():
            keep = name in hw.KEEP_OUT
            if name in hw.HOSES:
                op = 0.25
            else:
                op = 0.10 if keep else 0.25
            for a in render_vtk._actors(solid, render_vtk.HW_RGB[name], opacity=op, edges=not keep, edge_opacity=0.15):
                ren.AddActor(a)
        for name, rt in routes.items():
            ren.AddActor(hose_routes.tube_actor(rt.pts, rt.r, RGB[name]))
        win = vtk.vtkRenderWindow()
        win.SetOffScreenRendering(1)
        win.SetSize(1500, 1150)
        win.SetAlphaBitPlanes(1)
        win.SetMultiSamples(0)
        win.AddRenderer(ren)
        ren.SetUseDepthPeeling(1)
        ren.SetMaximumNumberOfPeels(8)
        ren.UseFXAAOn()
        cam = ren.GetActiveCamera()
        cam.SetFocalPoint(0, 0, 0)
        cam.SetPosition(*render_vtk.VIEWS[view])
        cam.SetViewUp(0, 0, 1)
        if view == "left":
            cam.ParallelProjectionOn()
        ren.ResetCamera()
        win.Render()
        grab = vtk.vtkWindowToImageFilter()
        grab.SetInput(win)
        grab.Update()
        wr = vtk.vtkPNGWriter()
        path = os.path.join(ROOT, "previews", f"b6_{tag}_{view}.png")
        wr.SetFileName(path)
        wr.SetInputConnection(grab.GetOutputPort())
        wr.Write()
        print("->", path)


VARIANTS = (("plan", "PLAN numbers (no way-point moved)"),
            ("moved", "AFTER moving way-points within 15 mm of the plan (this is the build; its failures are the findings)"),
            ("alt", "ALTERNATIVE for the two side fans, NOT the plan: over the board at n 50..55 (measured open), everything else as 'moved'"))


NOTES = """
Numbers the plan does not give, as chosen (all in cables.py):
  lane: stacked by rise u, the lowest rise on top at n -45, 2 mm of air between neighbours' radii; lane v = x_to_v(132) = 254
  rise u: the header's own u where the plan says "about" (ATX 220 for 210, USB 3 160 for 150, USB-C 110 for 100); the cable then descends
    at the rise u and ends at the header (EPS: ends at u 297 / 301, 2 / 0 mm from the header's 299)
  EPS: EPS2 at the plan's n 30, EPS1 at n 44 (14 mm over it); EPS2 rises 14 mm after EPS1 (the plan gives one u for both)
  PSU legs: 45 mm along -Y from every socket, EPS1 (the left socket) 60 mm so that it passes EPS2's first leg
  USB: start (X 60 / 70, Y 54, Z 30), down at u -6 to n -3, then to u 6 (USB 3) / 0 (USB-C) at the lane's level, across to v 254
  JFP1, JAUD1, light line: they do not go under the board: their start and their header are on the same side of it. Start (Y 55, Z 40) and
    X 82 / 48 / -125; JFP1 and the light line meet the header at n 14; JAUD1 runs at (n 30, u 20) and drops into its header, the light line passes
    under that drop at (u 14, n 14)
  pump lead: from the block's wall towards CPU_FAN1 at n 60, along v, along u, down
  side fans, plan route: leave the fan's inner face at n -30 (right fan u 255, left fan u 130), to the lane at the header's u, up to n 35, to the header
  side fans, alternative: right fan (v 323, u 190, n 56) straight to above SYS_FAN1 then down; left fan (v -58, u 190, n 55) to v 20, along -u to 135, down
Moves of way-points (plan number -> used, and why):
  USB 3 rise u 150 -> 163 (+13): beam_mid (u 126..156) has to be 3 mm from an r 4 cable
  EPS 1 rise u 265 -> 261 (-4) and EPS 2 265 -> 275.5 (+10.5), EPS run along u 297 -> 301 (+4): the two r 6 cables need 14 mm between them,
    beam_top (u 284.9) 3 mm and the DIMM box (u 290) 3 mm / the 420's core face (u 310) 3 mm
  right side fan lane v 254 -> 256 (+2): so the 15 mm to the header takes two bends of 8
  front starts: Y 50 -> 54 (USB), Y 50 -> 55 and Z 30 -> 40 (thin leads): the plan's point is 2.7 mm from the sill
Not built: the 12V-2x6 route (socket on the card unknown), clips, the sill's cable slot.
"""


def main(argv):
    only = [a for a in argv if not a.startswith("-")]
    parts, _ = frame_v0.build_frame()
    hardware = hw.build_hardware()
    lines = ["B6 cables: routes and checks (cad_b6/cables.py)", ""]
    results = {}
    for variant, label in VARIANTS:
        if only and variant not in only:
            continue
        routes, levels, overlaps = evaluate(variant, parts, hardware)
        results[variant] = (routes, levels, overlaps)
        lines.append(f"== {variant}: {label}")
        lines += fmt_rows(routes, overlaps)
        lines.append("lane levels n: " + ", ".join(f"{TITLE[k]} {v:.0f}" for k, v in sorted(levels.items(), key=lambda kv: -kv[1])))
        fails = [f"{TITLE[n]}: {f}" for n, rt in routes.items() for f in rt.fail]
        fails += [f"{TITLE[a]} x {TITLE[b]} overlap ({d:.2f} mm)" for a, b, d in overlaps if d <= 1e-6]
        lines.append(f"failed checks ({variant}): " + (str(len(fails)) if fails else "none"))
        lines += [f"  {f}" for f in fails]
        lines.append("")
        results[variant] += (fails,)
    lines.append(NOTES.strip("\n"))
    out = os.path.join(HERE_DIR, "report_cables.txt")
    with open(out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    if "-norender" not in argv:
        for variant, tag in (("moved", "cables"), ("alt", "cables_alt")):
            if variant in results:
                render_views(parts, hardware, results[variant][0], tag)
    final = results.get("moved")
    if final and final[3]:
        sys.exit(f"cables.py: {len(final[3])} check(s) failed in the build ('moved')")
    print("Done, all cable checks passed.")


HERE_DIR = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    main(sys.argv[1:])
