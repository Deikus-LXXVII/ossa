#!/usr/bin/env python3
"""Cable routes of the B6 case, second pass (docs/plans/cables-and-organic.md, "Second pass: spec for cad_b6/cables.py").

In the manner of hoses.py: a route is a list of sections, a section is a list of way-points joined with hoses.fillet_path. A section is
round (the cable's radius and bend from hardware.CABLES) or a slab (hardware.CABLE_SLAB round strands side by side along u, bend
hardware.SLAB_BEND; a slab stays in a plane of constant u). The facts (headers, sockets, radii, lengths) are in hardware.py. Nothing here moves
hardware or changes the skeleton; the front cables leave the I/O module's rear face (revision 18: the sill and its cable window are gone), and what else the skeleton would have to give is listed in report_cables.txt.

Board space (v, u, n) as in hardware.py: B(v, u, n) is the world point. Every way-point number is a named constant below with its reason.

Run:  .venv/bin/python cad_b6/cables.py [-norender]
Out:  cad_b6/report_cables.txt, previews/b6_cables_<view>.png; exits 1 if a check fails (after writing both), 0 if nothing fails.
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
HERE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Checks (unchanged from the first pass)
# ---------------------------------------------------------------------------
CLEAR_MM, HOSE_CLEAR_MM = 3.0, 5.0         # to every skeleton part / hardware solid, and to the hoses
END_TOL = 5.0                              # a route's end may be this far from its header (the headers are scaled off a drawing, +-5)

# ---------------------------------------------------------------------------
# Lanes and the gap at the right edge (board space)
# ---------------------------------------------------------------------------
# Every number below that was found by search (a hill-climb / annealing run against the checks, with 0.5 mm of margin on every clearance) is marked
# "search"; the rest are from the spec or the geometry and say so.
V_GAP = hw.x_to_v(131.5)                   # the gap's v: the board's edge is X 122 and the rib's X 142; here 9.5 / 10.5 mm from them, so that r 6 and r 7 keep 3.5 mm from both
V_IN = hw.x_to_v(113.0)                    # the lane under the board, inboard of the ribs (the r 12 ATX cable must stay 15 mm from X 142)
V_IN_OF = {"eps1": hw.x_to_v(122.0)}       # tie-point pass 2: EPS 1's lane starts at X 122, not 113 (the other cables keep V_IN): its 36 deg corner then lies 26 mm from a bridge on rib A's mid leg (X 142), 32 mm before; the cable keeps 10 mm from that rib (r 6)
LANE_N = {"usb3": -41.0, "gpu12v": -57.5, "atx24": -85.0, "eps1": -106.0, "eps2": -147.5}   # search: levels of the lanes at v 235: the cable that rises first lies on top, the next one under it by the two radii and air; USB 3 under beam_low (n -30) with r 4, EPS 2 above the desk (Z -15)
SHIFT_DEG = {"gpu12v": 24.0, "atx24": 12.0, "eps1": 8.5, "eps2": 29.5}   # search: angle of the diagonal that moves a lane cable from v 235 to the gap (it sets where each cable crosses the others); third pass: the diagonal is also where a PSU cable leaves its straight run to the lane, so a small angle is a long gentle ramp

# The u of each cable where it passes the gap, in the order USB 3, 12V-2x6, ATX, EPS 1, EPS 2. The spec has 12V-2x6 first: that cannot be, JUSB3 is at u 160 and
# USB 3 would have to cross the 12V slab (u 167..199, n up to 53, and the round cable above it) to reach it. The window is u 158 (beam_mid, u 155, + 3 + r 4)
# to 282 (beam_top, u 285, - 3).
GAP_U = {"usb3": 163.5, "gpu12v": 184.0, "atx24": 224.5, "eps1": 255.0, "eps2": 275.0}   # search: the slabs and USB 3 within 0.5..1 mm of each other, the ATX slab 4.5 mm from its header (u 220), EPS 2 6 mm + r 6 from beam_top

OWN = {   # the hardware a route may touch: its two ends
    "atx24": {"psu", "board", "atx24"}, "eps1": {"psu", "board", "eps"}, "eps2": {"psu", "board", "eps"}, "gpu12v": {"psu", "gpu"},
    "usb3": {"front_io", "board"}, "usbc": {"front_io", "board"}, "jfp1": {"front_io", "board"}, "jaud1": {"front_io", "board"},
    "cpu_fan": {"cpu_block", "board", "eps"},      # CPU_FAN1 lies inside the EPS keep-out box
    "fan_right": {"fan_side_right", "board"}, "fan_left": {"fan_side_left", "board"},
}
HEADER_OF = {"atx24": "ATX_PWR1", "eps1": "CPU_PWR1", "eps2": "CPU_PWR2", "usb3": "JUSB3", "usbc": "JUSBC1", "jfp1": "JFP1",
             "jaud1": "JAUD1", "cpu_fan": "CPU_FAN1", "fan_right": "SYS_FAN1", "fan_left": "SYS_FAN3"}
SOCKET_OF = {"atx24": "mb", "eps1": "eps1", "eps2": "eps2", "gpu12v": "gpu"}
TITLE = {"atx24": "ATX 24-pin", "eps1": "EPS 1", "eps2": "EPS 2", "gpu12v": "12V-2x6", "usb3": "USB 3 front", "usbc": "USB-C front",
         "jfp1": "Power switch", "jaud1": "Audio", "cpu_fan": "Pump / 420 fans", "fan_right": "Right side fan",
         "fan_left": "Left side fan"}
RGB = {"atx24": (0.85, 0.10, 0.10), "eps1": (0.95, 0.55, 0.05), "eps2": (0.95, 0.80, 0.05), "gpu12v": (0.95, 0.20, 0.55),
       "usb3": (0.10, 0.35, 0.85), "usbc": (0.05, 0.65, 0.85), "jfp1": (0.80, 0.10, 0.75), "jaud1": (0.10, 0.70, 0.25),
       "cpu_fan": (0.0, 0.0, 0.0), "fan_right": (0.60, 0.35, 0.10), "fan_left": (0.30, 0.55, 0.10)}


def B(v, u, n):
    return np.array(hw.bp(v, u, n))


def header(name):
    return hw.HEADERS[HEADER_OF[name]]


# ---------------------------------------------------------------------------
# Sections and routes
# ---------------------------------------------------------------------------
class Sec:
    """A stretch of one cross-section: kind "round" (radius and bend of the cable) or "slab" (hw.CABLE_SLAB strands, hw.SLAB_BEND)."""

    def __init__(self, kind, wps, name):
        self.kind, self.wps = kind, [np.array(p, dtype=float) for p in wps]
        real, r, bend = hw.CABLES[name]
        if kind == "slab":
            self.r, self.bend, self.strands = hw.SLAB_STRAND_R, hw.SLAB_BEND, hw.CABLE_SLAB[name]
        else:
            self.r, self.bend, self.strands = r, bend, 1
        pts, self.length, self.rmin, _t = hoses.fillet_path(self.wps, [self.bend] * (len(self.wps) - 2))
        self.pts = np.array(pts)
        if kind == "slab":
            us = np.array([hoses.world_to_bs(p)[1] for p in self.pts])
            assert us.max() - us.min() < 1e-6, f"{name}: a slab section leaves its plane of constant u ({us.min():.3f}..{us.max():.3f})"
            self.u0 = float(us[0])

    def strand_pts(self):
        """[(points, radius)] of every strand of the section; a slab's strands are the centre line shifted along u."""
        if self.kind == "round":
            return [(self.pts, self.r)]
        k = self.strands
        return [(self.pts + np.array(hw.U_DIR) * ((i - (k - 1) / 2) * hw.SLAB_PITCH), self.r) for i in range(k)]


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


def surface_extent(pts, r):
    """(min Y, max |X|) of the surface of a chain of cylinders of radius r along the polyline pts (exact for cylinders and their end spheres)."""
    ymin, xmax = float("inf"), 0.0
    for a, b in zip(pts[:-1], pts[1:]):
        d = b - a
        L = float(np.linalg.norm(d))
        if L < 1e-9:
            continue
        d = d / L
        ry, rx = r * math.sqrt(max(1 - d[1] ** 2, 0.0)), r * math.sqrt(max(1 - d[0] ** 2, 0.0))
        ymin = min(ymin, a[1] - ry, b[1] - ry)
        xmax = max(xmax, abs(a[0]) + rx, abs(b[0]) + rx)
    return ymin, xmax


class Route:
    def __init__(self, name, secs, own_leg=None, lying=False):
        """own_leg: the length at the start that stays in its socket's neighbourhood (a PSU cable's first leg): not held off its PSU."""
        self.name, self.secs, self.own_leg, self.lying = name, secs, own_leg, lying
        self.real = hw.CABLES[name][0]
        self.r = hw.CABLES[name][1]
        self.length = sum(s.length for s in secs)
        self.rmin = min(s.rmin for s in secs)
        self.bend_checks = [(s.kind, s.rmin, s.bend) for s in secs]
        self.strands = [sp for s in secs for sp in s.strand_pts()]
        self.pts = np.vstack([secs[0].pts] + [s.pts[1:] for s in secs[1:]])
        self.solid = self.body = self.psu_body = self.card_body = None
        self.clear = []            # (target, distance, needed)
        self.stretch = None        # front USB routes: the distance to the board of the first stretch
        self.fail = []             # (class, text)
        self.tie = None            # tie_eval(...) of the six cables with tie points, set by evaluate
        self.tie_n = 0             # how many bridges that was worked out with
        self.ymin, self.xmax = min(surface_extent(p, r)[0] for p, r in self.strands), max(surface_extent(p, r)[1] for p, r in self.strands)

    def end_offset(self):
        """(v, u) distance of the route's end from its header."""
        if self.name not in HEADER_OF:
            return None
        v, u, _n = hoses.world_to_bs(self.pts[-1])
        hv, hu = header(self.name)
        if self.lying:                                   # a lying socket is on the board's edge: the plug stops at the edge, in u it is held to the header's u
            hv = hw.BOARD_BS[1]
        return math.hypot(v - hv, u - hu)

    def _cut_end(self, pts, r):
        """The part of a section's points before the plug's descent into its header (which touches the board): up to the level of the header's top + r + 0.5."""
        ns = np.array([hoses.world_to_bs(p)[2] for p in pts])
        low = hw.HEADER_TOP_N + r + 0.5
        k = len(ns) - 1
        while k > 0 and ns[k] <= low:
            k -= 1
        return pts[:k + 1]

    def build(self):
        self.solid = cq.Compound.makeCompound([s for p, r in self.strands for s in chain_solid(p, r)])
        if self.name == "gpu12v":              # the card is this route's end: held off it after the plug, the straight and the first bend
            cum = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(self.pts, axis=0), axis=1))])
            keep = self.pts[cum <= cum[-1] - (hw.GPU12V_PLUG + hw.GPU12V_STRAIGHT + hw.CABLES["gpu12v"][2])]
            self.card_body = chain_solid(keep, self.r)
        if self.name not in HEADER_OF:
            return
        body = []
        for i, sec in enumerate(self.secs):
            last = i == len(self.secs) - 1
            for p, r in sec.strand_pts():
                if last:
                    if self.lying:                       # the plug (LYING_PLUG length) is the part that touches the board's edge
                        cum = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])
                        p = p[cum <= cum[-1] - hw.LYING_PLUG["length"] - 1.0]
                    else:
                        p = self._cut_end(p, r)
                if len(p) > 2:
                    body.append((p, r))
        self.body = cq.Compound.makeCompound([s for p, r in body for s in chain_solid(p, r)]) if body else None
        if self.own_leg is not None:                     # a PSU cable after its socket leg
            cum = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(self.pts, axis=0), axis=1))])
            keep = self.pts[cum >= self.own_leg + 5.0]
            self.psu_body = chain_solid(keep, self.r) if len(keep) > 2 else None


# ---------------------------------------------------------------------------
# Way-points
# ---------------------------------------------------------------------------
def shift_wps(v_from, v_to, c, n, theta_deg):
    """From the lane at v_from along +u, a diagonal to v_to at u = c, both in the plane n: the two corners."""
    return [B(v_from, c - (v_to - v_from) / math.tan(math.radians(theta_deg)), n), B(v_to, c, n)]


def psu_lead(name, theta):
    """A PSU cable out of its socket OUT_LEG[name] mm along -Y, round the PSU's front corner through (WAY_X, WAY_Y, WAY_Z) (world) where the straight way would
    cut the PSU, to the lane's start (v V_IN, or V_IN_OF[name], U_IN, LANE_N), along u, and a diagonal to the gap at u = GAP_U, still at the lane level."""
    sx, sy, sz = hw.PSU_SOCKETS[SOCKET_OF[name]]
    pts = [np.array([sx, sy, sz]), np.array([sx, sy - OUT_LEG[name], sz])]
    if name in WAY_X:
        pts.append(np.array([WAY_X[name], WAY_Y[name], WAY_Z[name]]))
    v_in = V_IN_OF.get(name, V_IN)
    pts += [B(v_in, U_IN[name], LANE_N[name])] + shift_wps(v_in, V_GAP, GAP_U[name], LANE_N[name], theta)
    return pts


# ---- the numbers of each route (board space unless said) ----
# PSU cables: out of the socket OUT_LEG mm along -Y, round the PSU's right front corner through WAY_* (EPS only), to the lane's start at u U_IN, then the lane.
U_IN = {"atx24": 120.0, "gpu12v": 113.5, "eps1": 123.0, "eps2": 233.0}   # third-pass search: u at which a PSU cable reaches its lane (EPS 2's 233 lies on the diagonal's own ramp: the cable meets its lane only just before the gap)
OUT_LEG = {"atx24": 103.0, "gpu12v": 72.5, "eps1": 45.0, "eps2": 45.0}   # third-pass search; the plan's 45 mm along -Y is the lower bound for every cable (ATX 103: the shortest way to its lane starts out along -Y)
WAY_X = {"eps1": 68.0, "eps2": 81.5}       # third-pass search: world X, Y, Z of the point where an EPS cable passes the PSU's right front corner (X 75, Y 165): the straight way to the lane cuts the PSU
WAY_Y = {"eps1": 123.0, "eps2": 146.5}
WAY_Z = {"eps1": 11.0, "eps2": 0.0}

# 12V-2x6: from the socket's mouth along +n (plug 13 + straight 35), one arch over the socket, and back down beside it under the organic layer's film (revision 18, docs/plans/front-and-outline.md,
# part H: the owner, "it can go under it; the main thing is that there is room for the connector"). From the slab's top the round part goes up the gap at the slab's u to GPU12V_UNDER_N,
# over to the foot of the loop (GPU12V_LOOP_V, GPU12V_LOOP_U) at GPU12V_RUN_N, under the film in the gap between the card (u up to 126.6) and the 360 (u from 184), up the loop's far leg to
# the arch's top, across to above the socket and down into it. Until revision 18 it went up the gap to an S-bend (GPU12V_S_N) and a descent at u 173 (GPU12V_ARCH_U), which ran through
# the layer's lip and over the bone `card`. The four numbers were searched with this script's own checks (docs/plans/sketches/cable_under_route.py, a grid of 81): every bend 35 (the
# cable's least), the loop's far leg clear of the lip, the route clear of the card and the 360 by evaluate_route's clearances; they pass with the least bend 35.0 and the route 9.1 mm in
# front of Y 0 (10.4 before; GPU12V_FRONT_TOL 11).
GPU12V_TOP_N = 220.0                       # top of the arch: mouth n 137 + plug 13 + straight 35 + the first bend's radius 35 (the arch cannot be lower)
GPU12V_UNDER_N = 83.0                      # search: n up the gap at the slab's u before the cable turns over to the loop
GPU12V_LOOP_V, GPU12V_LOOP_U = 192.5, 154.0      # search: (v, u) of the loop's far leg (X 70.5), which rises from GPU12V_RUN_N to GPU12V_TOP_N; the organic layer's right film starts past it
GPU12V_RUN_N = 115.0                       # search: n of the run under the film to the foot of the loop
GPU12V_SLAB_TOP_N = 53.0                   # search: the slab (4 strands r 4, constant u) starts here ...
GPU12V_SLAB_BOTTOM_N = -22.0               # ... and ends here: the round part's bend ends at the lane level + 35 = -23; its r 7 stays 3.5 mm off the rib at X 142
# ATX 24-pin: round r 12 to the foot of the gap, slab up through it, hook out over the rail, one U-turn, down into ATX_PWR1.
ATX_SLAB_BOTTOM_N = -50.0                  # the r 12 part ends 3 mm under the rail's bottom (n -34) + 12
ATX_HOOK = dict(n1=12.0, n2=22.0, v_up=272.5, n_top=90.0)   # search: the slab goes up the gap to n1, out over the rail to v_up at n2, up, and one U-turn (R 15, corners at n_top) down at the header's v
USB3_HOOK = dict(n1=29.0, n2=46.0, v_up=283.5, n_top=70.0)  # search: the same for USB 3 (round r 4), clear of the 12V-2x6's S-bend, which stands 3 mm from the same u
# EPS: round r 6 to the gap, up to the run over the board, a diagonal to above the header, down into it.
EPS_RUN_N = {"eps1": 65.0, "eps2": 59.5}   # search: level of the run over the board: over the DIMMs (n 45) + 3 + r 6 = 54
EPS_END_U = 300.0                          # u of the last leg: 4 mm from the DIMM box (u 290) and from the 420's core face (u 310) with r 6
# Front I/O
# The two USB cables leave the module's rear face (Y FRONT_IO_W[3]) at hw.FRONT_IO_LEAD_XZ, both read when the routes are built. Until revision 18 they passed the sill through its
# cable window and their X and Z were read from it; the sill is gone and the points keep those values (60, 30) and (70, 30). Before the window the start lay behind the sill (Y 54) and
# the cable passed the board's bottom edge 1.93 mm and the sill's rear face 2.65 mm away.


def usb_start(name):
    """World start of a front USB cable: on the module's rear face as hardware.py has it now."""
    x, z = hw.FRONT_IO_LEAD_XZ[name]
    return (x, hw.FRONT_IO_W[3], z)
U_EDGE = -9.5                              # search: u at which a USB cable passes the board's bottom edge
USB_DIVE_U = -4.5                          # search: u at which a USB cable has dived under the board at the lane level
USBC_RISER = dict(v=249.5, u=84.0)         # search: USB-C goes up the gap here, 3 mm + r 4 from the board's edge, and its U-turn stays off gpu_rest (u 75.6) by 3 mm
USBC_N = {"lane": -46.0, "plane": hw.LYING_PLUG["thick"] / 2}   # search: lane level under beam_low (n -30) with r 4; the plug's centre line over the board's plane (spec)
USBC_U_TURN = dict(v=290.0, u_end=121.5, v_exit=259.0)   # search: apex of the in-plane U-turn over the rail; the u it comes back to; the v where it straightens for the plug
FRONT_START_X = {"jaud1": 48.0, "jfp1": 82.0}     # first pass: along X on the plan's start line (Y 50, Z 30)
THIN_START_YZ = (55.0, 40.0)               # first pass: front start of JFP1 and JAUD1: the plan's (Y 50, Z 30) was 2.7 mm from the sill (gone in revision 18); Y +5 and Z +10 put an r 2 lead 3.5 mm off it
THIN_ENTRY_N = 14.0                        # first pass: n at which JFP1 meets its header (2 mm over the plug's top, one radius)
AUD_RUN = (30.0, 20.0)                     # first pass: (n, u) of JAUD1's run over the board's front strip: it descends into its header from there (over the light line's lead, gone in revision 18)
AUD_RUN_V0 = 110.0                         # first pass: v at which JAUD1 reaches the level of its run
# Pump lead and side fans
PUMP_START_N = 50.5                        # search: where the pump lead leaves the block's wall: 3 mm + r 2 over the DIMMs (n 45), in from the DIMM side
def fan_left_start_v():
    """v of the left fan's inner face, read when the route is built (revision 18: it was bound when the module was imported)."""
    return hw.x_to_v(hw.FAN_SIDE_X["fan_side_left"][1])


FAN_RIGHT_RUN = dict(n=46.0, ua=287.0, va=270.0)


def fan_right():
    """The right fan's lead, read when the route is built (revision 18: it was the dict FAN_RIGHT, bound when the module was imported). v0 the fan's inner face, u0 its high-u edge; the
    rest is FAN_RIGHT_RUN."""
    return dict(v0=hw.x_to_v(hw.FAN_SIDE_X["fan_side_right"][0]), u0=hw.FAN_SIDE_U[1], **FAN_RIGHT_RUN)


# search: the right fan's lead leaves the fan's rear edge (its high-u edge) at v0 (the fan's inner face), crosses the board's edge beyond EPS 2's rise (u ua) at level n, and enters SYS_FAN1 from the +u side; 5.5 mm off the hoses
FAN_LEFT = dict(u=177.5, n=65.0)           # search: the left fan's lead runs straight from the fan to above the header (the first pass's `alt`), over the board at level n, u from the fan to the header's


def hook(v_from, v_up, u, n1, n2, n_top, v_down, n_end):
    """Over the board: up the gap to n1 at v_from, out over the rail to v_up at n2 (an S-bend), up to n_top, U-turn (corners at n_top), down at v_down."""
    return [B(v_from, u, n1), B(v_up, u, n2), B(v_up, u, n_top), B(v_down, u, n_top), B(v_down, u, n_end)]


def waypoints_all():
    R = {}
    top = hw.HEADER_TOP_N
    # --- ATX 24-pin
    c = GAP_U["atx24"]
    hv, hu = header("atx24")
    h = ATX_HOOK
    rd = psu_lead("atx24", SHIFT_DEG["atx24"]) + [B(V_GAP, c, ATX_SLAB_BOTTOM_N)]
    sl = [B(V_GAP, c, ATX_SLAB_BOTTOM_N)] + hook(V_GAP, h["v_up"], c, h["n1"], h["n2"], h["n_top"], hv, top)
    R["atx24"] = [Sec("round", rd, "atx24"), Sec("slab", sl, "atx24")]
    # --- 12V-2x6 (from the PSU to the card, so the card is the end)
    c = GAP_U["gpu12v"]
    gs = hw.GPU_PWR_SOCKET
    mouth_n = hw.GPU_BS[5] - gs["recess"]
    rd1 = psu_lead("gpu12v", SHIFT_DEG["gpu12v"]) + [B(V_GAP, c, GPU12V_SLAB_BOTTOM_N)]
    sl = [B(V_GAP, c, GPU12V_SLAB_BOTTOM_N), B(V_GAP, c, GPU12V_SLAB_TOP_N)]
    rd2 = [B(V_GAP, c, GPU12V_SLAB_TOP_N), B(V_GAP, c, GPU12V_UNDER_N), B(GPU12V_LOOP_V, GPU12V_LOOP_U, GPU12V_RUN_N),
           B(GPU12V_LOOP_V, GPU12V_LOOP_U, GPU12V_TOP_N), B(gs["v"], gs["u"], GPU12V_TOP_N), B(gs["v"], gs["u"], mouth_n)]
    R["gpu12v"] = [Sec("round", rd1, "gpu12v"), Sec("slab", sl, "gpu12v"), Sec("round", rd2, "gpu12v")]
    # --- EPS 1 and 2
    for name in ("eps1", "eps2"):
        c, nr = GAP_U[name], EPS_RUN_N[name]
        hv, _hu = header(name)
        pts = psu_lead(name, SHIFT_DEG[name]) + [B(V_GAP, c, nr), B(hv, EPS_END_U, nr), B(hv, EPS_END_U, top)]
        R[name] = [Sec("round", pts, name)]
    # --- USB 3: under the bottom edge, diagonal under the board to the gap, up, hook, down into JUSB3
    hv, hu = header("usb3")
    c, v0 = GAP_U["usb3"], hw.x_to_v(usb_start("usb3")[0])
    h = USB3_HOOK
    pts = [np.array(usb_start("usb3")), B(v0, U_EDGE, -3.0), B(v0, USB_DIVE_U, LANE_N["usb3"]), B(V_GAP, c, LANE_N["usb3"])] \
        + hook(V_GAP, h["v_up"], c, h["n1"], h["n2"], h["n_top"], hv, top)
    R["usb3"] = [Sec("round", pts, "usb3")]
    # --- USB-C: under the bottom edge, up the gap at u 83, in the board's plane (n 4) a U-turn over the rail, into the lying plug along -v
    hv, hu = header("usbc")
    v0, rs, ut, pn = hw.x_to_v(usb_start("usbc")[0]), USBC_RISER, USBC_U_TURN, USBC_N["plane"]
    edge = hw.BOARD_BS[1]
    pts = [np.array(usb_start("usbc")), B(v0, U_EDGE, -3.0), B(v0, USB_DIVE_U, USBC_N["lane"]), B(rs["v"], rs["u"], USBC_N["lane"]),
           B(rs["v"], rs["u"], pn), B(ut["v"], rs["u"], pn), B(ut["v"], ut["u_end"], pn), B(ut["v_exit"], hu, pn), B(edge, hu, pn)]
    R["usbc"] = [Sec("round", pts, "usbc")]
    # --- the front cables that stay in front of the board
    hv, hu = header("jfp1")
    R["jfp1"] = [Sec("round", [np.array([FRONT_START_X["jfp1"], *THIN_START_YZ]), B(hv, hu, THIN_ENTRY_N)], "jfp1")]
    hv, hu = header("jaud1")
    R["jaud1"] = [Sec("round", [np.array([FRONT_START_X["jaud1"], *THIN_START_YZ]), B(AUD_RUN_V0, AUD_RUN[1], AUD_RUN[0]), B(hv, AUD_RUN[1], AUD_RUN[0]),
                                B(hv, hu, top)], "jaud1")]
    # --- the pump lead: over the DIMMs from the block's wall, in from the DIMM side to its header
    sv, su = hw.CPU_SOCKET_VU
    hv, hu = header("cpu_fan")
    d = np.array([hv - sv, hu - su])
    d /= np.linalg.norm(d)
    wall = (sv + hw.CPU_BODY_R * d[0], su + hw.CPU_BODY_R * d[1])
    R["cpu_fan"] = [Sec("round", [B(wall[0], wall[1], PUMP_START_N), B(hv, wall[1], PUMP_START_N), B(hv, hu, PUMP_START_N), B(hv, hu, top)], "cpu_fan")]
    # --- the side fans: straight from the fan to above the header
    hv, hu = header("fan_right")
    a = fan_right()
    R["fan_right"] = [Sec("round", [B(a["v0"], a["u0"], a["n"]), B(a["va"], a["ua"], a["n"]), B(hv, a["ua"], a["n"]), B(hv, hu, a["n"]), B(hv, hu, top)], "fan_right")]
    hv, hu = header("fan_left")
    a = FAN_LEFT
    R["fan_left"] = [Sec("round", [B(fan_left_start_v(), a["u"], a["n"]), B(hv, a["u"], a["n"]), B(hv, hu, a["n"]), B(hv, hu, top)], "fan_left")]
    return R


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
BODY_BOARD = "hw:board (route without the plug's descent)"
BODY_PSU = "hw:psu (route after its socket leg)"
BODY_CARD = "hw:gpu (route after the plug, the straight and the first bend)"


def build_routes():
    return {name: Route(name, secs, own_leg=OUT_LEG.get(name), lying=(HEADER_OF.get(name) in hw.HEADERS_LYING))
            for name, secs in waypoints_all().items()}


FRONT_STRETCH_U = 16.0   # the stretch of a front USB route with u below this passes the board's bottom edge (report only)


def front_stretch(rt, targets):
    """The distance to the board of the first stretch of a front USB route, where it passes the board's bottom edge (revision 18: the distance to the sill went with it)."""
    us = np.array([hoses.world_to_bs(p)[1] for p in rt.pts])
    zone = chain_solid(rt.pts[:int(np.argmax(us > FRONT_STRETCH_U)) + 1], rt.r)
    return frame_v0.solid_distance(zone, targets["hw:board"])


def evaluate_route(rt, targets, gpu_under, slots):
    """Build one route and run every check on it that does not involve another route (clearances, length, bends, ends, envelope, the two tie rules)."""
    rt.build()
    own = {f"hw:{k}" for k in OWN[rt.name]}
    rb = frame_v0.bbox_of(rt.solid)
    for tn, ts in targets.items():
        if tn in own:
            continue
        if tn == "hw:gpu" and rt.name == "usbc":
            ts = gpu_under                                # for this route only the card counts from GPU_UNDERSIDE_N up
        if frame_v0.bbox_gap(rb, frame_v0.bbox_of(ts)) > 30.0:
            continue
        need = HOSE_CLEAR_MM if tn in ("hw:cpu_hoses", "hw:gpu_hoses") else CLEAR_MM
        rt.clear.append((tn if tn != "hw:gpu" or rt.name != "usbc" else f"hw:gpu (from n {hw.GPU_UNDERSIDE_N:g} up)",
                         frame_v0.solid_distance(rt.solid, ts), need, tn))
    if rt.body is not None:
        rt.clear.append((BODY_BOARD, frame_v0.solid_distance(rt.body, targets["hw:board"]), CLEAR_MM, BODY_BOARD))
    if rt.psu_body is not None:
        rt.clear.append((BODY_PSU, frame_v0.solid_distance(rt.psu_body, targets["hw:psu"]), CLEAR_MM, BODY_PSU))
    if rt.card_body is not None:
        rt.clear.append((BODY_CARD, frame_v0.solid_distance(rt.card_body, targets["hw:gpu"]), CLEAR_MM, BODY_CARD))
    zmin = float(min(p[:, 2].min() - r for p, r in rt.strands))
    rt.clear.append((f"desk plane Z {hw.DESK_Z:g}", zmin - hw.DESK_Z, 0.0, "desk"))
    rt.clear.sort(key=lambda c: c[1] - c[2])
    rt.stretch = front_stretch(rt, targets) if rt.name in ("usb3", "usbc") else None
    # the checks
    if rt.real is not None and rt.length > rt.real + 1e-6:
        rt.fail.append(("route", f"length {rt.length:.0f} > real {rt.real:.0f}"))
    for kind, rmin, bend in rt.bend_checks:
        if rmin < bend - 1e-6:
            rt.fail.append(("route", f"bend {rmin:.1f} < min {bend:g} ({kind} section)"))
    for label, d, need, tn in rt.clear:
        if d < need - 1e-6:
            rt.fail.append(("route", f"{d:.2f} mm from {label}, needs {need:g}"))
    if rt.name in TIE_ROUTES:
        rt.tie, rt.tie_n = tie_eval(rt, slots), len(slots)
        rt.fail += tie_failures(rt)
    off = rt.end_offset()
    if off is not None and off > END_TOL:
        rt.fail.append(("route", f"ends {off:.1f} mm from its header (scaled position +-5)"))
    front_tol = hw.GPU12V_FRONT_TOL if rt.name == "gpu12v" else 0.0       # the owner's tolerance, for this cable only
    if rt.ymin < hw.ENVELOPE_Y0 - front_tol - 1e-6:
        text = f"envelope: {hw.ENVELOPE_Y0 - rt.ymin:.1f} mm in front of Y {hw.ENVELOPE_Y0:g} (surface at Y {rt.ymin:.1f})" + (f", accepted up to {front_tol:g}" if front_tol else "")
        rt.fail.append(("route", text))
    x_limit = hw.ENVELOPE_FAN_X if rt.name in hw.FAN_SIDE_CABLES else hw.ENVELOPE_X       # revision 13: a side fan's own lead may reach the fan's outer face, every other cable stops at the radiators' ends
    if rt.xmax > x_limit + 1e-6:
        text = f"envelope: {rt.xmax - x_limit:.1f} mm outside |X| {x_limit:g} (surface at |X| {rt.xmax:.1f})"
        rt.fail.append(("route", text))


def route_targets(parts, hardware):
    targets = {p.name: p.solid for p in parts}
    targets.update({f"hw:{k}": v for k, v in hardware.items()})
    return targets, hw.bs_box(hw.GPU_BS[0], hw.GPU_BS[1], hw.GPU_BS[2], hw.GPU_BS[3], hw.GPU_UNDERSIDE_N, hw.GPU_BS[5])


def route_pair_distances(routes, names=None):
    """[(a, b, distance)] between routes, nearest first (a pair whose boxes are over 30 mm apart counts as 1e9); with `names`, only the pairs that include one of them."""
    out, order = [], list(routes)
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            if names is not None and a not in names and b not in names:
                continue
            ra, rb_ = frame_v0.bbox_of(routes[a].solid), frame_v0.bbox_of(routes[b].solid)
            d = 1e9 if frame_v0.bbox_gap(ra, rb_) > 30.0 else frame_v0.solid_distance(routes[a].solid, routes[b].solid)
            out.append((a, b, d))
    out.sort(key=lambda t: t[2])
    return out


def evaluate(routes, parts, hardware):
    targets, gpu_under = route_targets(parts, hardware)
    slots = tie_slots(parts)
    for rt in routes.values():
        evaluate_route(rt, targets, gpu_under, slots)
    return route_pair_distances(routes)


def failures(routes, overlaps):
    """[(class, 'Cable: text')] over every route and every pair of routes."""
    out = [(c, f"{TITLE[n]}: {t}") for n, rt in routes.items() for c, t in rt.fail]
    out += [("route", f"{TITLE[a]} x {TITLE[b]} overlap ({d:.2f} mm)") for a, b, d in overlaps if d <= 1e-6]
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def arcs_of(sec):
    """[(waypoint index, turn angle deg, radius used, arc midpoint, 17 points along the arc)] of a section's bends (the fillet of hoses.fillet_path, replicated)."""
    P, m = sec.wps, len(sec.wps)
    seg = [P[i + 1] - P[i] for i in range(m - 1)]
    sl = [float(np.linalg.norm(d)) for d in seg]
    un = [d / l for d, l in zip(seg, sl)]
    th, tan = [0.0] * m, [0.0] * m
    for i in range(1, m - 1):
        th[i] = math.acos(float(np.clip(un[i - 1] @ un[i], -1, 1)))
        tan[i] = sec.bend * math.tan(th[i] / 2)
    for _ in range(3):
        for i in range(m - 1):
            need = tan[i] + tan[i + 1]
            if need > sl[i] > 0:
                k = sl[i] / need
                tan[i] *= k
                tan[i + 1] *= k
    out = []
    for i in range(1, m - 1):
        if th[i] < 0.1:
            continue
        r = tan[i] / math.tan(th[i] / 2)
        b = un[i] - un[i - 1]
        b = b / np.linalg.norm(b)
        start, d1 = P[i] - un[i - 1] * tan[i], un[i - 1]
        m1 = un[i] - (d1 @ un[i]) * d1
        m1 /= np.linalg.norm(m1)
        centre = start + r * m1
        arc = np.array([centre + r * (-m1 * math.cos(phi) + d1 * math.sin(phi)) for phi in np.linspace(0, th[i], 17)])
        out.append((i, math.degrees(th[i]), r, P[i] + b * r * (1 / math.cos(th[i] / 2) - 1), arc))
    return out


def fmt(p):
    return f"world ({p[0]:.0f}, {p[1]:.0f}, {p[2]:.0f}) board ({hoses.world_to_bs(p)[0]:.0f}, {hoses.world_to_bs(p)[1]:.0f}, {hoses.world_to_bs(p)[2]:.0f})"


def fmt_rows(routes, overlaps):
    out = [f"{'cable':16} {'route':>6} {'real':>6} {'spare':>6} {'smallest bend':>14}  {'smallest clearance':>20}  {'to':44} {'furthest in front of Y 0':>25}"]
    for name, rt in routes.items():
        label, d, _need, _tn = rt.clear[0]
        real = f"{rt.real:6.0f}" if rt.real is not None else f"{'n/a':>6}"
        spare = f"{rt.real - rt.length:6.0f}" if rt.real is not None else f"{'n/a':>6}"
        k = min(range(len(rt.bend_checks)), key=lambda i: rt.bend_checks[i][1] - rt.bend_checks[i][2])
        kind, rmin, bend = rt.bend_checks[k]
        bend_s = f"{rmin:5.1f}/{bend:<3g}" if math.isfinite(rmin) else "  -  /" + f"{bend:<3g}"
        front = f"{-rt.ymin:6.1f} mm" if rt.ymin < hw.ENVELOPE_Y0 else f"none (Y {rt.ymin:.0f})"
        out.append(f"{TITLE[name]:16} {rt.length:6.0f} {real} {spare} {bend_s:>14}  {d:20.2f}  {label:44} {front:>25}")
    out.append("")
    out.append("per route: every clearance under 10 mm, and every failed check")
    for name, rt in routes.items():
        near = [f"{label} {d:.1f}" for label, d, _n, _t in rt.clear if d < 10.0]
        out.append(f"  {TITLE[name]:16} {'; '.join(near) or 'nothing under 10 mm'}")
        for c, f in rt.fail:
            out.append(f"  {'':16} FAIL [{c}] {f}")
    out.append("route x route: smallest distances " + ", ".join(f"{TITLE[a]} x {TITLE[b]} {d:.2f}" for a, b, d in overlaps[:6]))
    return out


def skeleton_section(routes):
    out = ["", "What the skeleton has to provide (coordinates only; item 1 is built, nothing else is cut)", ""]
    out.append(f"1. The room behind the I/O module (revision 18: the sill and its cable window are gone): no part of the skeleton stands within {frame_v0.CARRIER_REAR_ROOM:g} mm behind the module's rear face "
               f"over its X and Z (frame_v0.py, check 20). The USB cables start on the module's rear face (Y {hw.FRONT_IO_W[3]:g}, PLACEHOLDER like the module):")
    for n in ("usb3", "usbc"):
        rt = routes[n]
        p = rt.pts[0]
        d_board = rt.stretch
        out.append(f"   {TITLE[n]:16} starts at {fmt(p)}; its first stretch (u < {FRONT_STRETCH_U:g}, where it passes the board's bottom edge) is {d_board:.2f} mm from the board (3 wanted)")
    out.append("   Power switch (X 82) and audio (X 48) start behind the module's rear face (Y 55).")
    notch = []
    for n, rt in routes.items():
        for c, f in rt.fail:
            if "rib_A_right" in f or "rib_B_right" in f:
                notch.append((n, f))
    rail = {n: d for n in ("usbc",) for label, d, _need, _t in routes[n].clear if label == "rib_A_right"}
    out.append("2. Rail notch: " + ("needed, see the failed checks against rib_A_right / rib_B_right above" if notch else
               f"none. No route comes within 3 mm of the ribs; the USB-C cable, which passes over the rail in the board's plane (n {USBC_N['plane']:g}), is {rail.get('usbc', float('nan')):.1f} mm from rib_A_right at the closest."))
    out.append("3. Proposed clip points (where a cable changes direction under the board, and where it enters the gap), arc midpoints of each bend under the board (n < -2):")
    for n, rt in routes.items():
        pts = []
        for sec in rt.secs:
            for _i, ang, r, mid, _arc in arcs_of(sec):
                if hoses.world_to_bs(mid)[2] < -2.0 and ang > 15.0:
                    pts.append((ang, r, mid))
        if pts:
            out.append(f"   {TITLE[n]}:")
            for ang, r, mid in pts:
                out.append(f"      {ang:3.0f} deg, R {r:4.1f}: {fmt(mid)}")
    out.append("   where each cable enters the gap (its centre line crosses the board's underside n -2 at the gap):")
    for n, rt in routes.items():
        if n in ("atx24", "gpu12v", "eps1", "eps2", "usb3", "usbc"):
            ns = np.array([hoses.world_to_bs(p)[2] for p in rt.pts])
            vs = np.array([hoses.world_to_bs(p)[0] for p in rt.pts])
            idx = [i for i in range(len(ns) - 1) if (ns[i] + 2.0) * (ns[i + 1] + 2.0) <= 0 and vs[i] > 247.0]
            for i in idx[:1]:
                out.append(f"      {TITLE[n]:16} {fmt(rt.pts[i])}")
    return out


TIE_REACH = 30.0           # spec (docs/plans/cables-and-organic.md, "Tie points, second pass"): a tie point holds a cable within this distance of its strap slot's middle
TIE_STRETCH = 150.0        # spec: no stretch of a cable below the board longer than this is without a tie point within TIE_REACH
TIE_BEND_DEG = 30.0        # spec: a bend of at least this angle below the board needs a tie point within TIE_REACH of some point of its arc
UNDER_N = -2.0             # below the board: n under this
TIE_ROUTES = ("atx24", "gpu12v", "eps1", "eps2", "usb3", "usbc")      # every PSU cable and the two front USB cables


def tie_slots(parts):
    """{bridge name: middle of its strap slot (world)} for every tie point whose bridge is among `parts`."""
    have = {p.name for p in parts}
    return {frame_v0.tie_name(tp): np.array(frame_v0.tie_slot_centre(tp)) for tp in frame_v0.TIE_POINTS if frame_v0.tie_name(tp) in have}


def tie_eval(rt, slots):
    """The two numbers of the spec for one route, below the board (n < UNDER_N), with the cable's two plugs (the route's two ends) as fixed points like a slot.
    Returns dict(nearest, which: the smallest distance from the route to any slot and which one; bends: [(angle, R, arc midpoint, smallest distance from the arc to a fixed point, which)]
    for every bend of TIE_BEND_DEG or more whose midpoint is below the board; stretches: [(length, first point, last point)] of the runs below the board with no fixed point
    within TIE_REACH, longest first; below: the length of the route below the board)."""
    pts = rt.pts
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    names = list(slots)
    fixed = {**slots, "plug at the start": pts[0], "plug at the end": pts[-1]}
    fnames, fpos = list(fixed), np.array(list(fixed.values()))
    d_slot = np.array([[float(np.linalg.norm(p - c)) for c in slots.values()] for p in pts]) if slots else np.full((len(pts), 1), np.inf)
    i = int(np.argmin(d_slot.min(axis=1)))
    nearest, which = float(d_slot[i].min()), (names[int(np.argmin(d_slot[i]))] if names else "-")
    below = np.array([hoses.world_to_bs(p)[2] < UNDER_N for p in pts])
    covered = np.array([float(np.min(np.linalg.norm(fpos - p, axis=1))) <= TIE_REACH for p in pts])
    stretches, a = [], None
    for k in range(len(pts) + 1):
        bad = k < len(pts) and below[k] and not covered[k]
        if bad and a is None:
            a = k
        if not bad and a is not None:
            stretches.append((float(cum[k - 1] - cum[a]), pts[a], pts[k - 1]))
            a = None
    stretches.sort(key=lambda s: -s[0])
    bends = []
    for sec in rt.secs:
        for _i, ang, r, mid, arc in arcs_of(sec):
            if ang < TIE_BEND_DEG - 1e-9 or hoses.world_to_bs(mid)[2] >= UNDER_N:
                continue
            d = np.linalg.norm(arc[:, None, :] - fpos[None, :, :], axis=2)
            j = int(np.argmin(d.min(axis=0)))
            bends.append((ang, r, mid, float(d[:, j].min()), fnames[j]))
    return dict(nearest=nearest, which=which, bends=bends, stretches=stretches, below=float(cum[below][-1] - cum[below][0]) if below.any() else 0.0)


def tie_failures(rt):
    out = []
    for ang, r, mid, d, which in rt.tie["bends"]:
        if d > TIE_REACH + 1e-9:
            out.append(("tie", f"bend of {ang:.0f} deg (R {r:.0f}) at {fmt(mid)} has no tie point within {TIE_REACH:g} mm of its arc (nearest fixed point {which}, {d:.1f} mm)"))
    for length, p0, p1 in rt.tie["stretches"]:
        if length > TIE_STRETCH + 1e-9:
            out.append(("tie", f"{length:.0f} mm of its length below the board have no tie point within {TIE_REACH:g} mm (limit {TIE_STRETCH:g}), from {fmt(p0)} to {fmt(p1)}"))
    return out


def tie_section(routes):
    n_slots = routes[TIE_ROUTES[0]].tie_n
    out = ["", f"Cable tie points (frame_v0.TIE_POINTS, {n_slots} bridges; distances from the route's centre line to the middle of a bridge's strap slot; a PASS or FAIL for the two numbers of the spec)",
           f"  rule 1: every bend of {TIE_BEND_DEG:g} deg or more below the board (n < {UNDER_N:g}, arc midpoint) has a tie point within {TIE_REACH:g} mm of some point of its arc",
           f"  rule 2: no stretch of route below the board longer than {TIE_STRETCH:g} mm has no tie point within {TIE_REACH:g} mm",
           "  the cable's two plugs (the route's ends) count as fixed points, like a tie point",
           f"  {'cable':16} {'nearest':>10}  {'which':20} {'longest unserved stretch':>25} {'below the board':>16}  bends served / bends"]
    for n in TIE_ROUTES:
        t = routes[n].tie
        worst = t["stretches"][0][0] if t["stretches"] else 0.0
        ok = sum(1 for b in t["bends"] if b[3] <= TIE_REACH + 1e-9)
        out.append(f"  {TITLE[n]:16} {t['nearest']:7.1f} mm  {t['which']:20} {worst:22.0f} mm {t['below']:13.0f} mm  {ok} / {len(t['bends'])}"
                   + ("   PASS" if not tie_failures(routes[n]) else "   FAIL"))
    out.append("  every bend of 30 deg or more below the board: distance from its arc to the nearest fixed point (a bridge's slot, or a plug)")
    for n in TIE_ROUTES:
        for ang, r, mid, d, which in routes[n].tie["bends"]:
            out.append(f"    {TITLE[n]:16} {ang:4.0f} deg R {r:4.1f} at {fmt(mid)}: {d:5.1f} mm to {which}" + ("" if d <= TIE_REACH + 1e-9 else "   FAIL"))
    return out


def facts_section(routes):
    gs = hw.GPU_PWR_SOCKET
    mouth_n = hw.GPU_BS[5] - gs["recess"]
    out = ["", "Socket numbers and assumptions used",
           f"  12V-2x6 socket on the card (read off MSI's render, +-12 mm along v, +-3 mm along u, +-8 mm recess): v {gs['v']:g}, u {gs['u']:g}, mouth n {mouth_n:g} (card face n {hw.GPU_BS[5]:g} - recess {gs['recess']:g})",
           f"  plug {hw.GPU12V_PLUG:g} mm out of the mouth (assumption), straight {hw.GPU12V_STRAIGHT:g} mm from the plug's back; radius {hw.CABLES['gpu12v'][1]:g}, bend {hw.CABLES['gpu12v'][2]:g}",
           f"  slabs: strands r {hw.SLAB_STRAND_R:g}, pitch {hw.SLAB_PITCH:g}, bend {hw.SLAB_BEND:g}; ATX {hw.CABLE_SLAB['atx24']} strands, 12V-2x6 {hw.CABLE_SLAB['gpu12v']} strands (assumptions)",
           f"  USB-C: lying plug {hw.LYING_PLUG['length']:g} x {hw.LYING_PLUG['thick']:g} mm (assumption); the card counts from n {hw.GPU_UNDERSIDE_N:g} up for this route only (assumption; the owner confirmed the port works under this card today)",
           f"  PSU sockets (read off a photo of the modular face, +-3 mm in X, +-5 mm in Z, not measured; hardware.PSU_SOCKET_FIELD): " + ", ".join(f"{k} = {hw.PSU_SOCKET_USE[k]} X {v[0]:g} Z {v[2]:g}" for k, v in hw.PSU_SOCKETS.items()) + f" on the face Y {hw.PSU_W[2]:g}",
           "  the ATX 24-pin cable really ends in two plugs side by side at the PSU (the 10-pin and the 18-pin, X -5 to 56); it is modelled as one round bundle from the field's centre (X 26): a simplification",
           "  radii and bends of every other cable: hardware.CABLES (assumptions)",
           ""]
    rt = routes["gpu12v"]
    ymin = rt.ymin
    out.append(f"12V-2x6, furthest point in front of Y {hw.ENVELOPE_Y0:g}: " + (f"{hw.ENVELOPE_Y0 - ymin:.1f} mm (surface at Y {ymin:.1f}); the arch's top is n {GPU12V_TOP_N:g}. Accepted by the owner on 15 Nov 2026 as a tolerance, up to {hw.GPU12V_FRONT_TOL:g} mm" if ymin < hw.ENVELOPE_Y0 else "none"))
    return out


def notes():
    return f"""
Numbers chosen here (all in cables.py, each with its reason there):
  order in the gap, from low u: USB 3 {GAP_U['usb3']:g}, 12V-2x6 slab {GAP_U['gpu12v']:g} (then up the gap to n {GPU12V_UNDER_N:g}, under the organic layer's film at n {GPU12V_RUN_N:g} to the loop at v {GPU12V_LOOP_V:g}, u {GPU12V_LOOP_U:g}, up to the arch over the socket), ATX slab {GAP_U['atx24']:g}, EPS 1 {GAP_U['eps1']:g}, EPS 2 {GAP_U['eps2']:g}
  lanes under the board at v {V_IN:g} (EPS 1: v {V_IN_OF['eps1']:g}, X {V_IN_OF['eps1'] + hw.ORIGIN[0]:g}, so that its 36 deg corner is within the reach of a bridge on rib A's mid leg), levels n: """ + ", ".join(f"{TITLE[k]} {v:g}" for k, v in LANE_N.items()) + f"""; each cable's diagonal takes it to v {V_GAP:g} and it rises through the gap
  hooks (ATX, USB 3): up the gap, out over the rail (S-bend) to v {ATX_HOOK['v_up']:g} / {USB3_HOOK['v_up']:g}, up, one U-turn of R 15, down at the header's v
  EPS: up the gap to the run over the board (n {EPS_RUN_N['eps1']:g} / {EPS_RUN_N['eps2']:g}, over the DIMMs' 45 + 3 + r 6), a diagonal to above the header at u {EPS_END_U:g}, down into it
  USB-C: up the gap at v {USBC_RISER['v']:g} / u {USBC_RISER['u']:g}, then in the board's plane (n {USBC_N['plane']:g}) a U-turn over the rail and the plug along -v
Not built: nylon clips for single cables, any cut in the skeleton. The tie points (frame_v0.TIE_POINTS) are built; the two rules for them (TIE_REACH {TIE_REACH:g} mm, stretches of {TIE_STRETCH:g} mm, bends of {TIE_BEND_DEG:g} deg) are checks in this script, and their numbers are in the section above.
"""


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
CLOSE_VIEWS = {   # name -> (focal point (world), camera direction, distance, view angle): the right edge, where the cables pass the gap; the parts are drawn fainter
    "right_edge": ((130.0, 200.0, 170.0), (0.85, -1.15, 0.60), 430.0, 30.0),
    "right_edge_side": ((130.0, 190.0, 150.0), (1.0, 0.0, 0.0), 520.0, 30.0),
    "under_board": ((100.0, 215.0, 70.0), (-0.30, 0.68, -0.68), 600.0, 30.0),      # tie points: looking up at the board's underside (front of the case at the top of the picture, X to the right), tilted a little to the left so that the bridges on the ribs' inner faces show their sides; the bridges (solid, named) and the six cables they hold
    "tie_inner": ((120.0, 215.0, 70.0), (-1.0, 0.0, 0.0), 700.0, 30.0),     # tie points: from the left, level, at the right rib's inner face (the board and the left ribs are left out): the bridges on the leg, the post and the skid, and the cables in front of them
}
VIEW_UP = {"under_board": tuple(-c for c in hw.U_DIR)}      # the picture's up; default Z
TIE_RGB = (0.0, 0.40, 0.45)       # the bridges are drawn solid in this colour in every view
# views in which each bridge carries its name; they draw only the right-hand skeleton (what the bridges stand on), the board and the PSU, so that nothing hides a bridge
_RIGHT_SKELETON = ("rib_A_right", "rib_B_right", "beam_low", "beam_mid", "beam_top", "skid_front", "skid_rear", "beam_front", "psu_bulkhead")
LABELLED_VIEWS = {"under_board": dict(parts=_RIGHT_SKELETON, hardware=("board", "psu")), "tie_inner": dict(parts=_RIGHT_SKELETON, hardware=("psu",))}


def render_views(parts, hardware, routes, tag="cables"):
    import vtk
    import hose_routes
    import render_vtk
    views = {k: (None, v) for k, v in render_vtk.VIEWS.items()}
    views.update({k: (c, d) for k, (c, d, _dist, _ang) in CLOSE_VIEWS.items()})
    for view, (close, direction) in views.items():
        fade = close is not None
        ren = vtk.vtkRenderer()
        ren.SetBackground(1, 1, 1)
        only = LABELLED_VIEWS.get(view)
        for p in parts:
            if p.name.startswith("tie_bridge"):
                for a in render_vtk._actors(p.solid, TIE_RGB, opacity=1.0, edge_opacity=0.9):
                    ren.AddActor(a)
                continue
            if only and p.name not in only["parts"]:
                continue
            for a in render_vtk._actors(p.solid, (0.86, 0.86, 0.86), opacity=0.14 if fade else 0.55, edge_opacity=0.3 if fade else 0.35):
                ren.AddActor(a)
        for name, solid in hardware.items():
            if only and name not in only["hardware"]:
                continue
            keep = name in hw.KEEP_OUT
            op = 0.25 if name in hw.HOSES else (0.10 if keep else 0.25)
            for a in render_vtk._actors(solid, render_vtk.HW_RGB[name], opacity=op * (0.4 if fade else 1.0), edges=not keep, edge_opacity=0.15):
                ren.AddActor(a)
        for name, rt in routes.items():
            for p, r in rt.strands:
                ren.AddActor(hose_routes.tube_actor(p, r, RGB[name]))
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
        if close is None:
            cam.SetFocalPoint(0, 0, 0)
            cam.SetPosition(*direction)
            cam.SetViewUp(0, 0, 1)
            if view == "left":
                cam.ParallelProjectionOn()
            ren.ResetCamera()
        else:
            _c, _d, dist, ang = CLOSE_VIEWS[view]
            u = np.array(direction, dtype=float)
            u /= np.linalg.norm(u)
            cam.SetFocalPoint(*close)
            cam.SetPosition(*(np.array(close) + u * dist))
            cam.SetViewUp(*VIEW_UP.get(view, (0, 0, 1)))
            cam.SetViewAngle(ang)
            ren.ResetCameraClippingRange()
        if view in LABELLED_VIEWS:        # each bridge's name, drawn flat on top of the picture at the place where its slot is seen
            win.Render()
            for p in parts:
                if p.name.startswith("tie_bridge"):
                    tp = next(t for t in frame_v0.TIE_POINTS if frame_v0.tie_name(t) == p.name)
                    ren.SetWorldPoint(*frame_v0.tie_slot_centre(tp), 1.0)
                    ren.WorldToDisplay()
                    x, y, _z = ren.GetDisplayPoint()
                    lab = vtk.vtkTextActor()
                    lab.SetInput(p.name.replace("tie_bridge_", ""))
                    lab.SetPosition(x + 6, y + 6)
                    lab.GetTextProperty().SetFontSize(26)
                    lab.GetTextProperty().SetBold(True)
                    lab.GetTextProperty().SetColor(0.0, 0.0, 0.0)
                    lab.GetTextProperty().SetBackgroundColor(1.0, 1.0, 1.0)
                    lab.GetTextProperty().SetBackgroundOpacity(0.7)
                    ren.AddViewProp(lab)
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


def main(argv):
    parts, _ = frame_v0.build_frame()
    hardware = hw.build_hardware()
    routes = build_routes()
    overlaps = evaluate(routes, parts, hardware)
    fails = failures(routes, overlaps)
    lines = ["B6 cables, second pass: routes and checks (cad_b6/cables.py)", ""]
    lines += fmt_rows(routes, overlaps)
    lines.append("")
    lines.append("failed checks: " + (str(len(fails)) if fails else "none"))
    lines += [f"    {t}" for _c, t in fails]
    lines += facts_section(routes)
    lines += skeleton_section(routes)
    lines += tie_section(routes)
    lines.append(notes().rstrip("\n"))
    with open(os.path.join(HERE_DIR, "report_cables.txt"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    if "-norender" not in argv:
        render_views(parts, hardware, routes)
    if fails:
        sys.exit(f"cables.py: {len(fails)} check(s) failed")
    print("Done, all cable checks passed.")


if __name__ == "__main__":
    main(sys.argv[1:])
