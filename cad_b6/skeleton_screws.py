#!/usr/bin/env python3
"""The skeleton's screws: for every screw, the seat under its washer, the axis pointing out of the head, the head's diameter and height, the washer's thickness, its length
and what it clamps (revision 18, docs/plans/front-and-outline.md, part J.1). One source for assembly_access.py, which judges the tools that reach the heads and the order of
assembly, and organic_frame.py, which keeps the organic layer off the washers and the heads. It loads the frame and the hardware only, not the assembly check's search.

  class A: every insert pilot with a stack, the organic layer's pads aside. The seat of the head is the stack from the pilot's mouth, the length and the washer are check 15's
           (frame_v0.check_screws), the joint is the pilot's part and the names check 15 measured on the axis inside the stack.
  class B: the clearance holes of kind M3c or 6-32c on no pilot's axis, the screws into the hardware's own threads, described by CLASS_B. Their seat is measured on the
           solids: from the face of the hardware that holds the thread outward, on a line beside the bore, to the end of the material the screw clamps.
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frame_v0  # noqa: E402
import hardware as hw  # noqa: E402

SEAT_PROBE = 60.0                       # mm: class B, the line the seat is measured on runs this far either side of the bore's middle

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

def unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


def across(e):
    """A unit vector at right angles to e."""
    a = np.cross(e, [1.0, 0.0, 0.0])
    if np.linalg.norm(a) < 0.1:
        a = np.cross(e, [0.0, 1.0, 0.0])
    return a / np.linalg.norm(a)



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


def thread_solids(parts, hardware):
    """({name: solid} that screws_of reads the threads of class B from: every printed part, every hardware solid, and each drive body of a bay by its own name
    (split_drives), the failures of split_drives). assembly_access passes its obstacles instead, which hold the same solids under the same names."""
    solids = {p.name: p.solid for p in parts}
    solids.update(hardware)
    drives, fails = split_drives(hardware)
    solids.update(drives)
    return solids, fails


def head_rows(screws):
    """(k, 8) array, one row a screw: the seat under its washer (X, Y, Z), the unit axis out of the head, the radius of what stands on the seat (the washer's where
    there is one, else the head's) and the height of the washer and the head together. What the organic layer keeps off (organic_frame.carve_heads, head_failures)."""
    rows = []
    for s in screws:
        r = hw.M3_WASHER_D / 2 if s["washer_t"] > 0 else s["head_d"] / 2
        rows.append((*np.asarray(s["seat"], dtype=float), *unit(s["e"]), max(r, s["head_d"] / 2), s["washer_t"] + s["head_h"]))
    return np.array(rows, dtype=float).reshape(-1, 8)
