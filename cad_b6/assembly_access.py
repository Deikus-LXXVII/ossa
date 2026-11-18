#!/usr/bin/env python3
"""Screwdriver reach and the order of assembly (docs/plans/assembly-access.md, step 1).

A screw that a later part covers is fine if it is driven before that part goes on. So for every screw and every tool that fits its head this script finds the solids
that stand in the tool's way in the assembled case, and then looks for an order of installing the parts and the hardware in which every screw can be driven at the
moment its joint is complete. That order is the assembly instruction; if there is none, the case cannot be put together as drawn.

  Screws    class A: every insert pilot with a stack, the organic layer's pads aside. The seat of the head is the stack from the pilot's mouth, the length and the washer
            are check 15's (frame_v0.check_screws), the joint is the pilot's part and the names check 15 measured on the axis inside the stack.
            class B: the clearance holes of kind M3c or 6-32c on no pilot's axis, the screws into the hardware's own threads, described by CLASS_B. Their seat is measured on
            the solids: from the face of the hardware that holds the thread outward, on a line beside the bore, to the end of the material the screw clamps.
            Not judged here, but counted: the front I/O module's pilots (placeholder) and the organic layer's pads (organic_frame.driver_blocked judges them).
  Bill      every row of frame_v0.FASTENERS has an entry in BILL that says how it is judged, and its count must be the number of screws its rule picks; every class A
            and class B screw is picked by exactly one row.
  Tools     hardware.py's tool constants, all ASSUMPTIONS. An M3 socket head takes the straight driver or the L-key, a pan head the straight driver or the stubby one.
  Blockers  a tool is a solid; its blockers are the solids it meets by VOL_EPS or more (booleans on the exact solids, printed parts drilled, in the assembled case).
            The insertion of the screw (its head's corridor as long as the screw) is part of every tool. Hardware is hard, soft (hoses and plugs: a screw only they
            block needs a look) or no obstacle; a key of build_hardware() in none of the lists fails.
  Order     the nodes are the printed parts and the hardware units (UNITS). A screw is driven as soon as its whole joint is in; a node may go on only if every screw
            not yet driven still has a tool without a hard blocker, judged with the screw's own joint in as well (it will be in when the screw is driven). Depth first in
            the preference (the printed parts as build_frame returns them, then HARDWARE_PREFERENCE), with backtracking, at most SEARCH_CAP states.

The search and the reachability (swing_free .. loose_nodes) are pure functions of tables, so cad_b6/test_assembly.py drives them with hand-made ones.

Run:  .venv/bin/python cad_b6/assembly_access.py          writes out/assembly/order.md, exit status 1 on a failure
"""
from __future__ import annotations

import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cadquery as cq  # noqa: E402

import frame_v0  # noqa: E402
import hardware as hw  # noqa: E402

OUT_DIR = os.path.join(ROOT, "out", "assembly")
SEAT_LIFT = 0.1                         # mm: the insertion corridor starts this far above the seat, so it does not share the seat's face
LKEY_STEP_DEG = 5.0                     # the L-key's long arm is tried every this many degrees round the axis
RAW_LEN = hw.DRIVER_SHAFT_LEN + hw.DRIVER_HANDLE_LEN      # the raw free lengths are measured this far from the top of the head: the straight driver's whole length
RAW_WIDE_D = hw.DRIVER_HANDLE_D         # the second raw corridor: as wide as a handle
SEARCH_CAP = 200_000                    # states the search may visit before it gives up ("no order within the cap" is not "every order was tried")
SEAT_PROBE = 60.0                       # mm: class B, the line the seat is measured on runs this far either side of the bore's middle
TOOLS_BY_HEAD = {"socket": ("straight", "lkey"), "pan": ("straight", "stubby")}

# Every key of hw.build_hardware(), by exact name, in one of three lists.
HARD_HARDWARE = ("board", "gpu", "cpu_block", "rad360", "rad420", "psu", "fan_side_right", "fan_side_left", "front_io", "dimms", "rad420_ports", "rad360_ports",
                 "light_strip", "drive_left", "drive_plugs_left")
SOFT_HARDWARE = ("cpu_hoses", "gpu_hoses", "atx24", "eps")          # a hose can be pushed aside, a plug goes in last
NOT_OBSTACLES = ("io_zone", "gpu_out_zone")
LISTS = dict(hard=HARD_HARDWARE, soft=SOFT_HARDWARE, none=NOT_OBSTACLES)
# A unit goes in as one piece. The two bodies of a bay's drives are separate solids (split_drives) and separate nodes: the 2.5 inch drive's screws end up under the
# 3.5 inch drive (frame_v0.SLED_ORDER). A hardware solid in no unit is a node of its own.
UNITS = {"cpu_aio": ("cpu_block", "cpu_hoses", "rad360", "rad360_ports"),
         "gpu_aio": ("gpu", "gpu_hoses", "rad420", "rad420_ports"),
         "board": ("board", "dimms", "atx24", "eps"),
         "drive_left_25": ("drive_left_25",),
         "drive_left_35": ("drive_left_35", "drive_plugs_left")}
# Put together on the bench and installed as one node, where its last member stands in the preference. A screw whose whole joint lies inside a group is driven on the bench, with
# nothing but the group's own solids round it. The 360 goes on and comes off with its two arms (revision 16): in the case the neck stands 7.5 mm from the axis of the arms' u 297 screws.
BENCH = {"rad360_with_arms": ("visor_arm_right", "visor_arm_left", "cpu_aio")}
# A node that sits on another with no screw of the model between them goes on after it: the CPU block on the board's socket, the card in the board's slot, the PSU on its skids,
# the I/O module in its carrier, the strip on the sill. Without this the search may put a cooler in before the board it stands on.
SITS_ON = {"cpu_aio": ("board",), "gpu_aio": ("board",), "psu": ("skid_front", "skid_rear"), "front_io": ("front_io_carrier",), "light_strip": ("front_sill",)}
HARDWARE_PREFERENCE = ("psu", "board", "cpu_aio", "gpu_aio", "fan_side_right", "fan_side_left", "drive_left_25", "drive_left_35", "front_io", "light_strip")

_D35, _D25 = hw.DRIVE_FORMS[hw.DRIVE_ON["outer"]], hw.DRIVE_FORMS[hw.DRIVE_ON["inner"]]
# Class B: the screws into a thread of the hardware. The holes carry no item, stack or meaningful washer, so each group is described here. The head is a pan head,
# no washer. `thread` is the solid that holds the thread (the 420's core, not its fans: the run to the seat goes on through the fan).
CLASS_B = {
    "psu": dict(parts=("psu_bulkhead",), kind="6-32c", thread="psu", head_d=hw.UNC6_HEAD_D, head_h=hw.UNC6_HEAD_H, length=hw.PSU_SCREW_LEN),
    "rad360": dict(parts=("visor_arm_left", "visor_arm_right"), kind="6-32c", thread="rad360", head_d=hw.UNC6_HEAD_D, head_h=hw.UNC6_HEAD_H, length=hw.RAD360_SCREW_LEN),
    "rad420": dict(parts=("antler_left", "antler_right"), kind="6-32c", thread="rad420", head_d=hw.UNC6_HEAD_D, head_h=hw.UNC6_HEAD_H,
                   length=hw.RAD_FAN_SCREW_LEN + frame_v0.ANTLER_T),
    "drive_left_35": dict(parts=("drive_sled_left",), kind=frame_v0.THREAD_CLEAR[_D35["thread"]], thread="drive_left_35", head_d=_D35["head_d"], head_h=_D35["head_h"],
                          length=_D35["screw_len"]),
    "drive_left_25": dict(parts=("drive_sled_left",), kind=frame_v0.THREAD_CLEAR[_D25["thread"]], thread="drive_left_25", head_d=_D25["head_d"], head_h=_D25["head_h"],
                          length=_D25["screw_len"]),
}

# One entry per row of frame_v0.FASTENERS, by the row's item. The holes' items differ from the rows' ("side fan" against fan_side_left and fan_side_right).
BILL = {
    "board": dict(how="A", items=("board",)),
    "rad420": dict(how="B", groups=("rad420",)),
    "rad360": dict(how="B", groups=("rad360",)),
    "psu": dict(how="B", groups=("psu",)),
    "fan_side_left": dict(how="A", items=("side fan",), parts=("fan_bracket_left",)),
    "fan_side_right": dict(how="A", items=("side fan",), parts=("fan_bracket_right",)),
    "front_io": dict(how="placeholder"),
    "front_io_carrier": dict(how="A", items=("front_io_carrier",)),
    "gpu": dict(how="same", row="gpu_post"),
    "gpu_rest": dict(how="A", items=("gpu_rest",)),
    "lap A<->B": dict(how="A", items=("lap A<->B",)),
    "beam_front ends": dict(how="A", items=("beam_front end",)),
    "beam_low ends": dict(how="A", items=("beam_low end",)),
    "beam_mid ends": dict(how="A", items=("beam_mid end",)),
    "beam_top ends": dict(how="A", items=("beam_top end",)),
    "skid_front ends": dict(how="A", items=("skid_front end",)),
    "skid_rear ends": dict(how="A", items=("skid_rear end",)),
    "psu_bulkhead ends": dict(how="A", items=("psu_bulkhead end",)),
    "antler tongue": dict(how="A", items=("antler tongue",)),
    "neck pad": dict(how="A", items=("neck pad",)),
    "visor joint": dict(how="A", items=("visor joint",)),
    "fan brackets": dict(how="A", items=("fan bracket",)),
    "hose_guide_cpu": dict(how="A", items=("hose_guide_cpu",)),
    "hose_guide_gpu": dict(how="A", items=("hose_guide_gpu",)),
    "gpu_post": dict(how="A", items=("gpu_post",)),
    "front_sill": dict(how="A", items=("front_sill -> beam_front",)),
    "tie_pilot": dict(how="same", row="tie_bridge"),
    "tie_bridge": dict(how="A", items=("tie bridge",)),
    "drive_left": dict(how="B", groups=("drive_left_35", "drive_left_25")),
    "drive sled flanges": dict(how="A", items=("drive sled flange",)),
    "organic": dict(how="organic"),
}


# ---------------------------------------------------------------------------
# Pure functions of tables: no geometry below this line until "Geometry".
# A screw is dict(id, members: frozenset of solid names, tools: {tool: blockers}). A tool's blockers are a frozenset of solid names (the insertion's included), or
# for the L-key dict(base: frozenset, dirs: tuple of frozensets, one per direction, step: degrees). `units` maps a node to the frozenset of its solids.
# ---------------------------------------------------------------------------
def swing_free(free, step_deg, swing_deg):
    """True if the directions marked free (evenly spaced round the axis, `step_deg` apart) hold a run of consecutive free ones at least `swing_deg` wide."""
    n = len(free)
    if n and all(free):
        return True
    best = run = 0
    for f in list(free) + list(free):            # twice round: a run may cross direction 0
        run = run + 1 if f else 0
        best = max(best, min(run, n))
    return best > 0 and (best - 1) * step_deg >= swing_deg - 1e-9


def tool_status(blk, installed, hard):
    """'free' (nothing installed in the tool's way), 'soft' (only soft solids) or 'blocked' (a hard one)."""
    if isinstance(blk, dict):
        def passes(counted):
            if blk["base"] & counted:
                return False
            return swing_free([not (d & counted) for d in blk["dirs"]], blk["step"], hw.LKEY_SWING_DEG)
        if passes(installed):
            return "free"
        return "soft" if passes(installed & hard) else "blocked"
    got = blk & installed
    if not got:
        return "free"
    return "blocked" if got & hard else "soft"


def tool_blockers(blk, installed):
    """The installed solids in a tool's way (for an L-key: its base's, and those of every direction)."""
    if isinstance(blk, dict):
        return (blk["base"] | frozenset().union(*blk["dirs"])) & installed
    return blk & installed


def reachable(screw, installed, hard):
    """The tools of `screw` that no hard solid among `installed` blocks."""
    return [t for t, blk in screw["tools"].items() if tool_status(blk, installed, hard) != "blocked"]


def own_solids(screws, units):
    """{screw id: the solids of the units of its joint's members}: they are all in when the screw is driven."""
    where = node_of(units)
    return {s["id"]: frozenset().union(*(units[where[m]] for m in s["members"])) for s in screws}


def all_blockers(screw):
    """Every solid in the way of any of the screw's tools, in any direction."""
    return frozenset().union(*(b["base"].union(*b["dirs"]) if isinstance(b, dict) else b for b in screw["tools"].values()))


def step_problems(before, adding, screws, hard, own):
    """Why a node whose solids are `adding` may not go on when `before` is installed: every screw not driven yet (its joint not complete in `before`) must still have a
    tool without a hard blocker. A screw is judged with its own joint's solids (`own`) in as well: they will all be in when it is driven, and blockers only grow, so this
    refuses no order that is valid to the end and finds a dead end as soon as it is certain. [] when the node may go on."""
    after = before | adding
    out = []
    for s in screws:
        if s["members"] <= before:
            continue
        state = after | own[s["id"]]
        if not reachable(s, state, hard):
            when = "becomes drivable" if s["members"] <= after else "is not drivable yet"
            hit = sorted(set().union(*(tool_blockers(b, state) & hard for b in s["tools"].values())))
            out.append(f"{s['id']} {when} and every tool is blocked ({', '.join(hit)})")
    return out


def search(screws, units, preference, hard, cap=SEARCH_CAP, needs=None):
    """dict(status, order, states): status 'found' (order is the list of nodes), 'exhausted' (every order was tried) or 'cap' (gave up after `cap` states)."""
    needs = needs or {}
    own = own_solids(screws, units)
    # a node can only take a tool from a screw whose way it stands in; the others keep what they had (a screw its own joint blocks is caught when the blocking member goes on)
    touched = {n: [s for s in screws if all_blockers(s) & sol] for n, sol in units.items()}
    # a node that shares a screw with something installed is tried before one that would stand loose: the order then reads as an instruction (a preference, not a rule)
    where = node_of(units)
    linked = {n: set() for n in units}
    for s in screws:
        ns = {where[m] for m in s["members"]}
        for n in ns:
            linked[n] |= ns - {n}
    seen = set()
    order = []
    states = 0

    class Cap(Exception):
        pass

    def dfs(nodes, solids):
        nonlocal states
        if len(nodes) == len(preference):
            return True
        for n in sorted((n for n in preference if n not in nodes), key=lambda n: not (linked[n] & nodes)):      # stable: held nodes first, each group in the preference's order
            if any(m not in nodes for m in needs.get(n, ())):
                continue                         # what it sits on is not in yet
            key = nodes | {n}
            if key in seen:
                continue                         # a set already entered led nowhere: what may follow depends on the set, not on its order
            states += 1
            if states > cap:
                raise Cap
            if step_problems(solids, units[n], touched[n], hard, own):
                continue                         # not marked: the same set may be valid when another node comes last
            seen.add(key)
            order.append(n)
            if dfs(key, solids | units[n]):
                return True
            order.pop()
        return False

    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, 4 * len(preference) + 100))
    try:
        ok = dfs(frozenset(), frozenset())
        status = "found" if ok else "exhausted"
    except Cap:
        status, ok = "cap", False
    finally:
        sys.setrecursionlimit(limit)
    return dict(status=status, order=list(order) if ok else None, states=states)


def check_order(order, screws, units, hard, needs=None):
    """The problems of a given order, step by step, by the same rule the search uses. [] for a valid order."""
    own = own_solids(screws, units)
    out, solids = [], frozenset()
    for k, n in enumerate(order, 1):
        out += [f"step {k} ({n}): it sits on {m}, which is not in yet" for m in (needs or {}).get(n, ()) if m not in order[:k - 1]]
        out += [f"step {k} ({n}): {p}" for p in step_problems(solids, units[n], screws, hard, own)]
        solids |= units[n]
    return out


def choose_tool(screw, installed, hard):
    """(tool, status) a screw is driven with when `installed` is in: the first of its tools that is free, else the first that only soft solids block, else (None, 'blocked')."""
    st = {t: tool_status(b, installed, hard) for t, b in screw["tools"].items()}
    for want in ("free", "soft"):
        for t, s in st.items():
            if s == want:
                return t, s
    return None, "blocked"


def steps_of(order, screws, units, hard):
    """[(node, [(screw id, tool, status)])]: the screws driven at each step, as soon as their joint is complete."""
    out, solids = [], frozenset()
    for n in order:
        after = solids | units[n]
        driven = [(s["id"], *choose_tool(s, after, hard)) for s in screws if s["members"] <= after and not s["members"] <= solids]
        out.append((n, driven))
        solids = after
    return out


def node_of(units):
    return {s: n for n, sol in units.items() for s in sol}


def own_joint_blocked(screws, units, hard):
    """The screws every tool of which a hard solid of the screw's own joint, or of the unit of one of its members, blocks: no order can drive them."""
    where = node_of(units)
    out = []
    for s in screws:
        own = frozenset().union(*(units[where[m]] for m in s["members"]))
        if all(tool_status(b, own, hard) == "blocked" for b in s["tools"].values()):
            hit = sorted(set().union(*(tool_blockers(b, own) & hard for b in s["tools"].values())))
            out.append((s["id"], hit))
    return out


def loose_nodes(order, screws, units):
    """[(node, the node at whose step it is first held, or None)] for every node after the first that shares no screw with the nodes installed before it."""
    where = node_of(units)
    nodes_of = [frozenset(where[m] for m in s["members"]) for s in screws]
    pos = {n: k for k, n in enumerate(order)}
    out = []
    for k, n in enumerate(order[1:], 1):
        held = [max(pos[m] for m in ns) for ns in nodes_of if n in ns and len(ns) > 1]
        first = min(held, default=None)
        if first is None or first > k:
            out.append((n, None if first is None else order[first]))
    return out


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def across(e):
    """A unit vector at right angles to e."""
    a = np.cross(e, [1.0, 0.0, 0.0])
    if np.linalg.norm(a) < 0.1:
        a = np.cross(e, [0.0, 1.0, 0.0])
    return a / np.linalg.norm(a)


def frame_at(origin, e):
    """The location whose local Z is e and whose origin is `origin`."""
    return cq.Location(cq.Plane(origin=tuple(float(c) for c in origin), xDir=tuple(float(c) for c in across(e)), normal=tuple(float(c) for c in e)))


def cyl(p, e, dia, length):
    return frame_v0.cyl(tuple(float(c) for c in p), tuple(float(c) for c in e), dia, length)


def blockers(tool, obstacles):
    """The names of the solids in `obstacles` ({name: solid}) that the tool's solids (a list) meet by VOL_EPS or more. Only solids whose box meets a tool's box are tried."""
    out = set()
    for t in tool:
        tb = frame_v0.exact_box(t)
        for name, s in obstacles.items():
            if name in out or frame_v0.bbox_overlap(tb, frame_v0.bbox_of(s)) <= 0:
                continue
            if frame_v0.inter_vol(t, s) >= frame_v0.VOL_EPS:
                out.add(name)
    return frozenset(out)


def free_length(top, e, dia, obstacles, reach=RAW_LEN):
    """(length, name): how far along e from `top` a corridor `dia` across runs before it meets a solid by VOL_EPS or more, and that solid; (reach, None) if nothing within reach.
    The lowest point along the axis of the intersection, read from its exact box in the corridor's own frame."""
    c = cyl(top, e, dia, reach)
    cb = frame_v0.exact_box(c)
    back = frame_at(top, e).inverse
    best = (reach, None)
    for name, s in obstacles.items():
        if frame_v0.bbox_overlap(cb, frame_v0.bbox_of(s)) <= 0:
            continue
        x = c.intersect(s)
        got = [] if x is None or x.isNull() else x.Solids()
        if sum(g.Volume() for g in got) < frame_v0.VOL_EPS:
            continue
        z = min(frame_v0.exact_box(g.moved(back))[4] for g in got)
        if z < best[0]:
            best = (z, name)
    return best


def lkey(top, e, rc, obstacles, step=LKEY_STEP_DEG):
    """The L-key's blockers: dict(base: its short arm's, dirs: the long arm's in each direction, step). The arm is tried only against what meets the disc it sweeps."""
    base = blockers([cyl(top, e, 2 * rc, hw.LKEY_SHORT)], obstacles)
    loc = frame_at(top, e)
    z0 = hw.LKEY_SHORT - hw.LKEY_T
    disc = cq.Solid.makeCylinder(math.hypot(hw.LKEY_LONG, hw.LKEY_T / 2), hw.LKEY_T, cq.Vector(0, 0, z0)).moved(loc)      # holds the arm in every direction
    near = blockers([disc], obstacles)
    n = int(round(360.0 / step))
    dirs = []
    for k in range(n):
        if not near:
            dirs.append(frozenset())
            continue
        arm = cq.Solid.makeBox(hw.LKEY_LONG, hw.LKEY_T, hw.LKEY_T, cq.Vector(0, -hw.LKEY_T / 2, z0)).rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), k * step).moved(loc)
        dirs.append(blockers([arm], {m: obstacles[m] for m in near}))
    return dict(base=base, dirs=tuple(dirs), step=step)


def screw_tools(s, obstacles, with_lkey):
    """{tool: blockers} of a screw dict (seat, e, head, head_d, head_h, washer_t, length) and its raw free lengths. The L-key only if `with_lkey` says so for this screw."""
    e = unit(s["e"])
    seat = np.asarray(s["seat"], dtype=float)
    rc = (s["head_d"] + hw.TOOL_PLAY) / 2
    top = seat + (s["washer_t"] + s["head_h"]) * e
    insert = blockers([cyl(seat + SEAT_LIFT * e, e, 2 * rc, s["length"] + s["head_h"] + 2.0)], obstacles)
    tools = {}
    for t in TOOLS_BY_HEAD[s["head"]]:
        if t == "straight":
            tools[t] = insert | blockers([cyl(top, e, 2 * rc, hw.DRIVER_SHAFT_LEN),
                                          cyl(top + hw.DRIVER_SHAFT_LEN * e, e, hw.DRIVER_HANDLE_D, hw.DRIVER_HANDLE_LEN)], obstacles)
        elif t == "stubby":
            tools[t] = insert | blockers([cyl(top, e, 2 * rc, hw.STUBBY_BLADE),
                                          cyl(top + hw.STUBBY_BLADE * e, e, hw.STUBBY_D, hw.STUBBY_LEN - hw.STUBBY_BLADE)], obstacles)
        elif t == "lkey" and with_lkey(tools):
            k = lkey(top, e, rc, obstacles)
            tools[t] = dict(k, base=k["base"] | insert)
    raw = (free_length(top, e, 2 * rc, obstacles), free_length(top, e, RAW_WIDE_D, obstacles))
    return dict(insert=insert, tools=tools, raw=raw, top=top)


def class_b_seat(hole, thread, clamped, head_d):
    """(seat, e, stack) of a class B screw in the clearance hole `hole`: e points from the thread to the head; the seat is on the axis where the material the screw clamps
    ends, measured on a line beside the bore (halfway between the bore's radius and the head's) from the face of `thread` outward. None if nothing is clamped there."""
    d = unit(hole.d)
    mid = np.array(hole.point(hole.length / 2))
    c = frame_v0.exact_box(thread)
    centre = np.array([(c[0] + c[1]) / 2, (c[2] + c[3]) / 2, (c[4] + c[5]) / 2])
    e = d if np.dot(mid - centre, d) > 0 else -d
    rho = (hole.r + head_d / 2) / 2
    start = mid - SEAT_PROBE * e + rho * across(e)
    probe = frame_v0.Hole("probe", tuple(start), tuple(e), 0.1, 2 * SEAT_PROBE, 0.0, False)
    faces = [b for a, b in frame_v0.material_spans(thread, probe) if b <= SEAT_PROBE]
    if not faces:
        return None
    s_t = max(faces) + frame_v0.SPAN_MARGIN          # material_spans stops SPAN_MARGIN short of each face
    spans = []
    for solid in clamped:
        spans += [(a - s_t, b - s_t) for a, b in frame_v0.material_spans(solid, probe)]
    end = frame_v0.axis_run(None, [x for x in spans if x[1] > 0])
    if end <= 0:
        return None
    stack = end + frame_v0.SPAN_MARGIN
    return mid + (s_t + stack - SEAT_PROBE) * e, e, stack


# ---------------------------------------------------------------------------
# The model: the screws, the obstacles, the bill
# ---------------------------------------------------------------------------
def split_drives(hardware):
    """{name: solid} of each drive body of each bay, named drive_<side>_35 / _25 by its form (hw.DRIVE_ON), and the failures (a body not found in the compound)."""
    out, fails = {}, []
    lay = hw.drive_layout()
    for side, sgn in hw.DRIVE_SIDES.items():
        key = f"drive_{side}"
        bodies = hardware[key].Solids()
        for face, fc in lay["faces"].items():
            want = frame_v0.exact_box(hw._drive_box(sgn, fc["body"]))
            hit = [b for b in bodies if max(abs(x - y) for x, y in zip(frame_v0.exact_box(b), want)) < 1e-3]
            name = f"{key}_{fc['form'][-2:]}"
            if len(hit) != 1:
                fails.append(f"ASSEMBLY {key}: the {face} drive's body ({name}) is not one solid of the compound ({len(hit)} found)")
            else:
                out[name] = hit[0]
    return out, fails


def rad420_core(hardware):
    """(core, fans) of the 420: the solid of the compound that is the core (hw.RAD420_CORE_U, hw.RAD420_CORE_N), and the rest."""
    want = frame_v0.exact_box(hw.bs_box(*hw.RAD420_BS[:2], *hw.RAD420_CORE_U, *hw.RAD420_CORE_N))
    sol = hardware["rad420"].Solids()
    core = [b for b in sol if max(abs(x - y) for x, y in zip(frame_v0.exact_box(b), want)) < 1e-3]
    if len(core) != 1:
        return None, None
    return core[0], [b for b in sol if b is not core[0]]


def obstacles_of(parts, hardware, lists=LISTS):
    """({name: solid} of everything a tool can meet, {name: 'hard' | 'soft'}, failures). Printed parts are hard and drilled; hardware by the lists."""
    fails = []
    solids, kind = {}, {}
    for p in parts:
        solids[p.name], kind[p.name] = p.solid, "hard"
    listed = [k for ks in lists.values() for k in ks]
    for k in hardware:
        n = listed.count(k)
        if n != 1:
            fails.append(f"ASSEMBLY the hardware solid {k} is in {'no list' if n == 0 else f'{n} lists'} of hard, soft and not-an-obstacle")
    for k in listed:
        if k not in hardware:
            fails.append(f"ASSEMBLY the hardware list names {k}, which build_hardware() no longer has")
    drives, f2 = split_drives(hardware)
    fails += f2
    for k, s in hardware.items():
        which = next((w for w, ks in lists.items() if k in ks), None)
        if which in (None, "none"):
            continue
        if k in hw.DRIVES:
            for name, body in drives.items():
                if name.startswith(k + "_"):
                    solids[name], kind[name] = body, which
        else:
            solids[k], kind[k] = s, which
    return solids, kind, fails


def on_pilot_axis(g, pilots):
    for _p, h in pilots:
        if abs(abs(float(np.dot(g.d, h.d))) - 1.0) > 1e-6:
            continue
        off = np.subtract(g.start, h.start)
        t = float(np.dot(off, h.d))
        if math.sqrt(max(0.0, float(np.dot(off, off)) - t * t)) <= 0.01:
            return True
    return False


def joint_members(h, row, parts, hardware):
    """The names check 15 measured on the screw's axis that lie inside its stack (check 15 lists every part with a clearance hole on the axis, the far side's too)."""
    by = {p.name: p for p in parts}
    probe = frame_v0.Hole("probe", h.point(frame_v0.OVERSHOOT), tuple(-c for c in h.d), 0.1, row["stack"], 0.0, False)
    # a name that is neither a part nor a hardware solid is check 15's own note on a row it could not measure; that row has failed check 15, which fails this run too
    return {n for n in row["what"] if (n in by or n in hardware) and frame_v0.material_spans(by[n].blank if n in by else hardware[n], probe)}


def screws_of(parts, hardware, solids, groups=CLASS_B):
    """(screws, organic, placeholder, failures). A screw is dict(id, cls, part, item or group, seat, e, head, head_d, head_h, washer_t, length, stack, members)."""
    fails = []
    f15 = []
    rows = frame_v0.check_screws(parts, hardware, f15)["rows"]
    fails += [f"ASSEMBLY check 15, whose rows give the lengths, fails: {x}" for x in f15]
    by_pos = {(r["part"], tuple(round(c, 6) for c in r["pos"])): r for r in rows}
    pilots = [(p, h) for p in parts for h in p.holes if h.pilot]
    screws, organic, placeholder = [], [], []
    for p, h in pilots:
        mouth = h.point(frame_v0.OVERSHOOT)
        if h.item == "organic pad":
            organic.append((p.name, mouth))
            continue
        if h.stack is None:
            placeholder.append((p.name, h.item, mouth))
            continue
        r = by_pos.get((p.name, tuple(round(c, 6) for c in mouth)))
        if r is None:
            fails.append(f"ASSEMBLY {p.name}: {h.describe()} has no row in check 15")
            continue
        d = unit(h.d)
        screws.append(dict(cls="A", part=p.name, item=h.item, group=None, seat=np.array(mouth) - r["stack"] * d, e=-d, head="socket", head_d=hw.M3_HEAD_D,
                           head_h=hw.M3_HEAD_H, washer_t=hw.M3_WASHER_T if r["washer"] else 0.0, length=r["length"], stack=r["stack"],
                           members=frozenset({p.name} | joint_members(h, r, parts, hardware))))
    core, fans = rad420_core(hardware)
    by = {p.name: p for p in parts}
    for p in parts:
        for h in p.holes:
            if h.pilot or h.kind not in ("M3c", "6-32c") or on_pilot_axis(h, pilots):
                continue
            g = [k for k, G in groups.items() if p.name in G["parts"] and h.kind == G["kind"]]
            if len(g) != 1:
                fails.append(f"ASSEMBLY {p.name}: {h.describe()} is a screw into the hardware that {'no' if not g else 'more than one'} group of CLASS_B describes")
                continue
            G = groups[g[0]]
            if G["thread"] == "rad420":
                if core is None:
                    fails.append("ASSEMBLY the 420's core is not one solid of hardware['rad420']")
                    continue
                thread, clamped = core, [by[p.name].solid] + fans
            elif G["thread"] in solids:
                thread, clamped = solids[G["thread"]], [by[p.name].solid]
            else:
                fails.append(f"ASSEMBLY {p.name}: the thread of group {g[0]} is in {G['thread']}, which is no obstacle solid")
                continue
            got = class_b_seat(h, thread, clamped, G["head_d"])
            if got is None:
                fails.append(f"ASSEMBLY {p.name}: {h.describe()}: nothing clamped between {G['thread']} and the head")
                continue
            seat, e, stack = got
            members = {p.name, G["thread"]}
            screws.append(dict(cls="B", part=p.name, item=None, group=g[0], seat=seat, e=e, head="pan", head_d=G["head_d"], head_h=G["head_h"], washer_t=0.0,
                               length=G["length"], stack=stack, members=frozenset(members)))
    for k, s in enumerate(screws, 1):
        p = s["seat"]
        s["id"] = f"#{k} {s['part']} ({p[0]:.1f}, {p[1]:.1f}, {p[2]:.1f})"
    return screws, organic, placeholder, fails


def picks(rule, s):
    if rule["how"] == "A":
        return s["cls"] == "A" and s["item"] in rule["items"] and s["part"] in rule.get("parts", (s["part"],))
    if rule["how"] == "B":
        return s["cls"] == "B" and s["group"] in rule["groups"]
    return False


def bill_check(screws, organic, placeholder, fasteners, bill=BILL):
    """Failures of the cross-check against the bill of fasteners; sets each screw's `row`."""
    fails = []
    rows = {}
    for r in fasteners:
        if r["item"] in rows:
            fails.append(f"ASSEMBLY the bill has two rows {r['item']!r}")
        rows[r["item"]] = r
    for item in rows:
        if item not in bill:
            fails.append(f"ASSEMBLY the bill's row {item!r} has no entry in BILL: its screws are judged by nobody")
    for item in bill:
        if item not in rows:
            fails.append(f"ASSEMBLY BILL has an entry {item!r} for a row the bill no longer has")
    for s in screws:
        by = [item for item, rule in bill.items() if picks(rule, s)]
        s["row"] = by[0] if len(by) == 1 else None
        if len(by) != 1:
            fails.append(f"ASSEMBLY {s['id']} ({s['item'] or s['group']}) is picked by {len(by)} rows of the bill ({', '.join(by) or 'none'}), not one")

    def count(item):
        rule = bill[item]
        if rule["how"] == "same":
            return count(rule["row"]) if rule["row"] in bill else -1
        if rule["how"] == "organic":
            return len(organic)
        if rule["how"] == "placeholder":
            return len(placeholder)
        return sum(1 for s in screws if picks(rule, s))

    for item, r in rows.items():
        if item in bill and count(item) != r["count"]:
            fails.append(f"ASSEMBLY the bill's row {item!r} counts {r['count']}, its rule in BILL picks {count(item)}")
    return fails


def units_of(parts, solids, units=UNITS):
    """{node: frozenset of solid names}: every printed part, every unit, and every other obstacle solid on its own; and the failures (a unit's solid that is gone)."""
    fails = []
    out = {p.name: frozenset({p.name}) for p in parts}
    taken = set()
    for n, sol in units.items():
        miss = [s for s in sol if s not in solids]
        if miss:
            fails.append(f"ASSEMBLY the unit {n} names {', '.join(miss)}, which is no obstacle solid")
        out[n] = frozenset(s for s in sol if s in solids)
        taken |= set(sol)
    for s in solids:
        if s not in out and s not in taken:
            out[s] = frozenset({s})
    return out, fails


def preference_of(parts, units, hardware_preference=HARDWARE_PREFERENCE):
    pref = [p.name for p in parts] + [n for n in hardware_preference if n in units]
    fails = [f"ASSEMBLY the node {n} has no place in HARDWARE_PREFERENCE" for n in units if n not in pref]
    fails += [f"ASSEMBLY HARDWARE_PREFERENCE names {n}, which is no node" for n in hardware_preference if n not in units]
    return pref, fails


def model_of(parts, hardware, fasteners, bill=BILL, lists=LISTS, groups=CLASS_B, units=UNITS):
    """Everything but the tools: dict(solids, kind, screws, organic, placeholder, units, preference) and the failures. Fast: no tool is measured."""
    solids, kind, fails = obstacles_of(parts, hardware, lists)
    screws, organic, placeholder, f2 = screws_of(parts, hardware, solids, groups)
    fails += f2 + bill_check(screws, organic, placeholder, fasteners, bill)
    nodes, f3 = units_of(parts, solids, units)
    pref, f4 = preference_of(parts, nodes)
    return dict(solids=solids, kind=kind, screws=screws, organic=organic, placeholder=placeholder, units=nodes, preference=pref), fails + f3 + f4


# ---------------------------------------------------------------------------
# The judgment and the report
# ---------------------------------------------------------------------------
def judge(table, units, preference, hard, cap=SEARCH_CAP, needs=None):
    """From the tables: (failures, result). result: own (screws their own joint blocks), search, steps, loose, early (screws only an early step reaches, with what
    covers them later), look (screws driven with a tool only soft solids block)."""
    fails = []
    every = frozenset().union(*units.values())
    own = own_joint_blocked(table, units, hard)
    for sid, hit in own:
        fails.append(f"ASSEMBLY {sid}: every tool is blocked by its own joint ({', '.join(hit)}): no order can drive it")
    bad = {sid for sid, _ in own}
    rest = [s for s in table if s["id"] not in bad]
    res = search(rest, units, preference, hard, cap, needs)
    if res["status"] == "exhausted":
        fails.append(f"ASSEMBLY no order: every order was tried ({res['states']} states)")
    elif res["status"] == "cap":
        fails.append(f"ASSEMBLY no order found within the cap of {cap} states (not every order was tried)")
    out = dict(own=own, search=res, steps=[], loose=[], early=[], look=[])
    if res["order"] is None:
        return fails, out
    fails += [f"ASSEMBLY the order the search found fails the full check: {p}" for p in check_order(res["order"], rest, units, hard, needs)]
    out["steps"] = steps_of(res["order"], table, units, hard)
    out["loose"] = loose_nodes(res["order"], table, units)
    where = node_of(units)
    by_id = {s["id"]: s for s in table}
    solids = frozenset()
    for n, driven in out["steps"]:
        solids |= units[n]
        for sid, tool, status in driven:
            if tool is None:
                continue                         # blocked by its own joint: a failure already
            if status == "soft":
                out["look"].append((sid, tool, n))
            s = by_id[sid]
            if not reachable(s, every, hard):
                cover = sorted({where[x] for x in (tool_blockers(s["tools"][tool], every) - solids) & hard})
                out["early"].append((sid, tool, n, cover))
    return fails, out


def only(blk, sol):
    """A tool's blockers with nothing but the solids `sol` round the screw."""
    if isinstance(blk, dict):
        return dict(blk, base=blk["base"] & sol, dirs=tuple(d & sol for d in blk["dirs"]))
    return blk & sol


def judge_with_bench(table, units, preference, hard, bench, cap=SEARCH_CAP, needs=None):
    """judge() with the groups of `bench` ({name: nodes}) put together off the case first: each group is judged alone (its own order, its inner screws against its own solids only)
    and then stands in the case's order as one node, at the place of its last member in the preference, sitting on whatever its members sit on. result gains
    bench: [(name, steps, loose)]; its early and look lists hold the bench screws too (a bench screw's covers are everything that stands in its tool's way once the case is whole,
    the group's own later members included)."""
    fails, done, early, look = [], [], [], []
    needs = {n: tuple(m) for n, m in (needs or {}).items()}
    every = frozenset().union(*units.values())
    units, preference, table = dict(units), list(preference), list(table)
    for g, nodes in bench.items():
        miss = [n for n in nodes if n not in units]
        if miss or g in units:
            fails.append(f"ASSEMBLY the bench group {g} names {', '.join(miss)}, which is no node" if miss else f"ASSEMBLY the bench group {g} has a node's name")
            continue
        grp = {n: units[n] for n in nodes}
        sol = frozenset().union(*grp.values())
        inner = [s for s in table if s["members"] <= sol]
        alone = [dict(s, tools={t: only(b, sol) for t, b in s["tools"].items()}) for s in inner]
        f, res = judge(alone, grp, [n for n in preference if n in grp], hard, cap, {n: tuple(m for m in needs.get(n, ()) if m in grp) for n in grp})
        fails += [x.replace("ASSEMBLY ", f"ASSEMBLY on the bench ({g}): ", 1) for x in f]
        done.append((g, res["steps"], res["loose"]))
        look += [(sid, tool, f"{n}, on the bench") for sid, tool, n in res["look"]]
        by_id = {s["id"]: s for s in inner}
        there = frozenset()
        for n, driven in res["steps"]:
            there |= grp[n]
            for sid, tool, _ in driven:
                if tool is not None and not reachable(by_id[sid], every, hard):
                    early.append((sid, tool, f"{n}, on the bench", (tool_blockers(by_id[sid]["tools"][tool], every) - there) & hard))
        last = max(nodes, key=preference.index)
        preference = [g if n == last else n for n in preference if n not in grp or n == last]
        units = {n: v for n, v in units.items() if n not in grp}
        units[g] = sol
        table = [s for s in table if not s["members"] <= sol]
        sits = tuple(dict.fromkeys(m for n in nodes for m in needs.get(n, ()) if m not in grp))
        needs = {n: tuple(dict.fromkeys(g if m in grp else m for m in ms)) for n, ms in needs.items() if n not in grp}
        if sits:
            needs[g] = sits
    f, res = judge(table, units, preference, hard, cap, needs)
    where = node_of(units)
    res["bench"] = done
    res["early"] = [(sid, tool, n, sorted({where[x] for x in cover})) for sid, tool, n, cover in early] + res["early"]
    res["look"] = look + res["look"]
    return fails + f, res


def fmt_raw(r):
    length, name = r
    return f"free beyond {RAW_LEN:g}" if name is None else f"{round(length, 1) + 0.0:.1f} ({name})"


def run(parts=None, hardware=None, fasteners=None):
    t0 = time.time()
    hardware = hw.build_hardware() if hardware is None else hardware
    if parts is None:
        parts, _ = frame_v0.build_frame(hardware=hardware)
    fasteners = frame_v0.FASTENERS if fasteners is None else fasteners
    model, fails = model_of(parts, hardware, fasteners)
    solids, kind, units = model["solids"], model["kind"], model["units"]
    hard = frozenset(k for k, v in kind.items() if v == "hard")
    every = frozenset(solids)
    lines = ["Screwdriver reach and the order of assembly (cad_b6/assembly_access.py, docs/plans/assembly-access.md step 1).",
             f"  Tools (ASSUMPTIONS, hardware.py): corridor = head + {hw.TOOL_PLAY:g}; straight driver: shaft {hw.DRIVER_SHAFT_LEN:g}, handle Ø{hw.DRIVER_HANDLE_D:g} x {hw.DRIVER_HANDLE_LEN:g}; "
             f"L-key {hw.LKEY_SHORT:g} / {hw.LKEY_LONG:g} x {hw.LKEY_T:g}, needs {hw.LKEY_SWING_DEG:g} deg free (tried every {LKEY_STEP_DEG:g}); stubby {hw.STUBBY_LEN:g} long: a blade {hw.STUBBY_BLADE:g}, then a handle Ø{hw.STUBBY_D:g}.",
             f"  Raw free lengths from the top of the head, along the axis, up to {RAW_LEN:g}: the head's corridor and Ø{RAW_WIDE_D:g}, each with the first solid met.", ""]
    table = []
    for s in model["screws"]:
        m = screw_tools(s, solids, lambda tools: tool_status(tools["straight"], every, hard) == "blocked")
        s.update(m)
        table.append(dict(id=s["id"], members=s["members"], tools=m["tools"]))
        works = [f"{t}{' (soft: ' + ', '.join(sorted(tool_blockers(b, every) - hard)) + ')' if tool_status(b, every, hard) == 'soft' else ''}"
                 for t, b in m["tools"].items() if tool_status(b, every, hard) != "blocked"]
        hit = sorted(set().union(*(tool_blockers(b, every) & hard for b in m["tools"].values())))
        head = f"M3 socket" if s["head"] == "socket" else f"pan Ø{s['head_d']:g}"
        lines.append(f"  [{s['cls']}] {s['row']} | {s['id']} | {head} x {s['length']:g}{', washer' if s['washer_t'] else ''}, clamps {s['stack']:.2f} | "
                     f"assembled: {', '.join(works) if works else 'NO TOOL (' + ', '.join(hit) + ')'} | free: corridor {fmt_raw(m['raw'][0])}, Ø{RAW_WIDE_D:g} {fmt_raw(m['raw'][1])}")
    for n, ms in SITS_ON.items():
        fails += [f"ASSEMBLY SITS_ON names {x}, which is no node" for x in (n, *ms) if x not in units]
    f_judge, res = judge_with_bench(table, units, model["preference"], hard, BENCH, needs={n: ms for n, ms in SITS_ON.items() if n in units and all(m in units for m in ms)})
    fails += f_judge
    n_a = sum(1 for s in model["screws"] if s["cls"] == "A")
    n_b = sum(1 for s in model["screws"] if s["cls"] == "B")
    lines += ["", f"Screws: class A {n_a}, class B {n_b}; not judged here: {len(model['placeholder'])} placeholder (front I/O module), {len(model['organic'])} organic pads (organic_frame.driver_blocked)."]
    for t in ("straight", "lkey", "stubby"):
        have = [s for s in table if t in s["tools"]]
        ok = sum(1 for s in have if tool_status(s["tools"][t], every, hard) != "blocked")
        lines.append(f"  reachable in the assembled case by the {t}: {ok} of the {len(have)} screws it was measured for")
    none = [s for s in table if not reachable(s, every, hard)]
    lines.append(f"  reachable in the assembled case by no tool: {len(none)}; of these driven at an early step: {len(res['early'])}")
    if res["own"]:
        lines.append("Blocked by their own joint (no order can drive them):")
        lines += [f"  {sid}: {', '.join(hit)}" for sid, hit in res["own"]]
    sr = res["search"]
    lines += ["", f"Order: {sr['status']}, {sr['states']} states visited."]
    md = ["# Order of assembly", "", "Written by `cad_b6/assembly_access.py`. The tools are ASSUMPTIONS (`cad_b6/hardware.py`).", ""]
    def step_lines(steps, pad):
        for k, (n, driven) in enumerate(steps, 1):
            drv = "; ".join(f"{sid} NO TOOL (blocked by its own joint)" if tool is None else f"{sid} with the {tool}{' (soft blockers: needs a look)' if st == 'soft' else ''}"
                            for sid, tool, st in driven)
            lines.append(f"{pad}{k:2d}. {n}" + (f": {len(driven)} screw(s): {drv}" if driven else ""))
            md.append(f"{k}. **{n}**" + (f": drive {drv}" if driven else ""))

    for g, steps, loose in res["bench"]:
        lines.append(f"  On the bench, {g} (then it goes on as one piece):")
        md += [f"## On the bench: {g}", ""]
        step_lines(steps, "    ")
        lines += [f"      {n} lies loose on the bench until {until}" if until else f"      {n}: no screw of the group holds it" for n, until in loose]
        md.append("")
    if res["bench"]:
        md += ["## In the case", ""]
    step_lines(res["steps"], "  ")
    if res["early"]:
        lines.append("Only an early step reaches (covered later by):")
        lines += [f"  {sid} at {n} with the {tool}: later covered by {', '.join(cover)}" for sid, tool, n, cover in res["early"]]
    lines.append("Needs a look (only soft solids in the tool's way):" if res["look"] else "Needs a look: none.")
    lines += [f"  {sid} at {n}, the {tool}" for sid, tool, n in res["look"]]
    lines.append("Stand loose when they go on:" if res["loose"] else "Stand loose: none.")
    lines += [f"  {n} until {until}" if until else f"  {n}: no screw holds it" for n, until in res["loose"]]
    lines.append(f"Run time {time.time() - t0:.0f} s.")
    if res["steps"]:
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(os.path.join(OUT_DIR, "order.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(md) + "\n")
    return lines, fails, dict(model=model, table=table, result=res)


def main():
    lines, fails, _ = run()
    print("\n".join(lines + ["", "FAILED:" if fails else "All checks pass."] + ["  - " + f for f in fails]))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
