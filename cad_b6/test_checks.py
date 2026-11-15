#!/usr/bin/env python3
"""Prove that the model's checks fail when the solid is wrong.

Builds the frame once, then for each case damages a copy in memory (or a hardware table, or a boolean),
runs frame_v0.run_checks and asserts that the failure the damage should cause is reported. The last case
is the undamaged model, which must report nothing.

    .venv/bin/python cad_b6/test_checks.py

One line per case: PASS/FAIL, name, the failure that was expected, what was reported.
Exit status 1 if any case fails.
"""
from __future__ import annotations

import ast
import dataclasses
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cadquery as cq  # noqa: E402

import frame_v0 as f  # noqa: E402
import hardware as hw  # noqa: E402
import measure  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS: list[tuple[bool, str]] = []
MEMO: dict = {}      # solid-identity memo for run_checks: a damaged copy recomputes only what touches the damage


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def part_named(parts, name):
    return next(p for p in parts if p.name == name)


def with_part(parts, name, **changes):
    """Copy of the parts list in which `name` is replaced by a modified copy."""
    return [dataclasses.replace(p, **changes) if p.name == name else p for p in parts]


def moved(p, dx, dy, dz):
    v = cq.Vector(dx, dy, dz)
    return dataclasses.replace(p, solid=p.solid.translate(v), blank=p.blank.translate(v),
                               holes=[h.moved(dx, dy, dz) for h in p.holes])


def refilled(p, hole):
    """The part with that hole filled back in: the bore, clipped to the undrilled shape, fused in."""
    return p.solid.fuse(hole.solid.intersect(p.blank)).clean()


def first_match(failures, *needles):
    for line in failures:
        if all(n in line for n in needles):
            return line
    return None


def case(name, expected, failures, *needles):
    """Record PASS when a failure containing every needle was reported."""
    got = first_match(failures, *needles)
    ok = got is not None
    RESULTS.append((ok, name))
    print(f"{'PASS' if ok else 'FAIL'}  {name}\n      expected: {expected}\n      reported: "
          f"{got if ok else 'NOTHING MATCHING (' + str(len(failures)) + ' other failures: ' + '; '.join(failures[:3]) + ')'}")


def check(name, ok, detail):
    RESULTS.append((bool(ok), name))
    print(f"{'PASS' if ok else 'FAIL'}  {name}\n      expected: {detail[0]}\n      reported: {detail[1]}")


class patched:
    """Temporarily replace an attribute."""

    def __init__(self, obj, attr, value):
        self.obj, self.attr, self.value = obj, attr, value

    def __enter__(self):
        self.old = getattr(self.obj, self.attr)
        setattr(self.obj, self.attr, self.value)

    def __exit__(self, *exc):
        setattr(self.obj, self.attr, self.old)


class patched_intersect:
    """Replace Shape.intersect and Compound.intersect (the latter overrides the former) by
    make(original) -> replacement, restoring both on exit."""

    CLASSES = (cq.occ_impl.shapes.Shape, cq.occ_impl.shapes.Compound)

    def __init__(self, make):
        self.make = make

    def __enter__(self):
        self.saved = {c: c.__dict__["intersect"] for c in self.CLASSES}
        for c, orig in self.saved.items():
            setattr(c, "intersect", self.make(orig))

    def __exit__(self, *exc):
        for c, orig in self.saved.items():
            setattr(c, "intersect", orig)


def hardware_literals(source: str):
    """(line, value) of numeric literals in `source` that repeat a hardware.py value which cannot be a
    coincidence: any non-integer of 10 or more (hole positions such as 77.75, 252.75, 172.5, 16.51)."""
    forbidden: set[float] = set()

    def walk(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            if abs(v) >= 10 and abs(v - round(v)) > 1e-9:
                forbidden.add(round(abs(float(v)), 4))
        elif isinstance(v, (tuple, list)):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)

    for name, value in vars(hw).items():
        if not name.startswith("_") and name not in ("TILT_DEG",):
            walk(value)
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            if round(abs(float(node.value)), 4) in forbidden:
                hits.append((node.lineno, node.value))
    return sorted(hits)


# ---------------------------------------------------------------------------
def main():
    t_start = time.time()
    print("Building hardware and frame (twice, to prove the registries reset)...")
    hardware = hw.build_hardware()
    f.build_frame(hardware=hardware)
    n_fasteners = len(f.FASTENERS)
    parts, neck_prims = f.build_frame(hardware=hardware)
    check("build_frame twice", len(f.FASTENERS) == n_fasteners,
          ("a second call does not double FASTENERS", f"{n_fasteners} -> {len(f.FASTENERS)} entries"))
    f.check_bolts(neck_prims)
    nb = len(f.BOLT_CHECKS)
    f.check_bolts(neck_prims)
    check("check_bolts twice", len(f.BOLT_CHECKS) == nb and nb > 0,
          ("a second call does not double the bolt checks", f"{nb} -> {len(f.BOLT_CHECKS)}"))

    t0 = time.time()
    base = f.run_checks(hardware, parts, MEMO)     # the memo is empty: every pair and every hole of the undamaged model is computed
    print(f"undamaged model: {len(base['failures'])} failures, {base['n_holes']} holes measured, "
          f"mounts derived from the solids {base['mounts']} ({time.time() - t0:.0f} s, nothing remembered)\n")

    # 1. a pilot hole filled back in
    p = part_named(parts, "beam_low")
    h = next(h for h in p.holes if h.kind == "M3")
    r = f.run_checks(hardware, with_part(parts, "beam_low", solid=refilled(p, h)), MEMO)
    case("M3 insert pilot of beam_low filled back in", "CHECK7 beam_low ... M3 pilot ... is not drilled",
         r["failures"], "CHECK7 beam_low", "M3 pilot", "is not drilled")
    case("  same damage, board count derived from the solids", "CHECK5 board: 8 positions have a hole",
         r["failures"], "CHECK5 board: 8 positions")

    # 1b. every hole of a part never drilled (blank used as the part)
    r = f.run_checks(hardware, with_part(parts, "beam_low", solid=p.blank), MEMO)
    case("beam_low undrilled (blank instead of the part)", "CHECK7 beam_low ... is not drilled and CHECK5 board: 6",
         r["failures"], "CHECK5 board: 6 positions")
    case("  same damage, hole check", "CHECK7 beam_low ... is not drilled", r["failures"], "CHECK7 beam_low", "is not drilled")

    # 2. a part pushed 5 mm into a neighbouring component
    ant = part_named(parts, "antler_right")
    mv = moved(ant, 0, -5, 0)
    r = f.run_checks(hardware, with_part(parts, "antler_right", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("antler_right moved 5 mm into rad420", "CHECK2 part x hardware antler_right x rad420",
         r["failures"], "CHECK2 part x hardware antler_right x rad420")

    # 2b. a part pushed into the CPU hoses (neck_left stands 20.6 mm from the left flank run; 25 mm outward is into it)
    neck = part_named(parts, "neck_left")
    mv = moved(neck, -25, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "neck_left", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("neck_left moved 25 mm outward, into cpu_hoses", "CHECK2 part x hardware neck_left x cpu_hoses",
         r["failures"], "CHECK2 part x hardware neck_left x cpu_hoses")

    # 2c. check 9: a part 3 mm from a hose (not touching it) fails the 5 mm rule; check 2 stays quiet
    mv = moved(neck, -17.6, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "neck_left", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("neck_left moved 17.6 mm outward, 3 mm from cpu_hoses", "CHECK9 neck_left is 3.00 mm from cpu_hoses, needs 5",
         r["failures"], "CHECK9 neck_left", "cpu_hoses", "needs 5")
    check("  same damage, check 2 does not fire", first_match(r["failures"], "CHECK2 part x hardware neck_left x cpu_hoses") is None,
          ("no CHECK2 cpu_hoses line: the part does not overlap that keep-out (it does reach rad420_ports)", f"{len(r['failures'])} failure(s): {'; '.join(r['failures'][:2])}"))
    near_guide = [x for x in r["hose_gaps"] if x[0] == "hose_guide_cpu"]
    check("check 9 leaves the guides out", not near_guide and "hose_guide_cpu" in f.GUIDE_PARTS,
          ("the guides are not measured against the hoses", f"{len(near_guide)} guide rows in the check 9 table"))

    # 2d. check 8: a hose pushed 20 mm outward, and a part in front of Y = 0
    import numpy as np
    import hoses
    real_chains = hoses.keepout_chains

    def pushed_chains():
        out = real_chains()
        out["cpu_hoses"] = [[p + np.array([-20.0, 0, 0]) if p[0] < -219.0 else p for p in line] for line in out["cpu_hoses"]]
        return out

    with patched(hoses, "keepout_chains", pushed_chains):
        pushed = hw.hose_solid("cpu_hoses", hardware["cpu_block"])
    hw_pushed = dict(hardware, cpu_hoses=pushed)
    r = f.run_checks(hw_pushed, parts, MEMO)
    case("a cpu hose waypoint run pushed 20 mm outward", "CHECK8 cpu_hoses reaches |X| = 248.6, limit 229",
         r["failures"], "CHECK8 cpu_hoses reaches |X|", "limit 229")
    bf = part_named(parts, "beam_front")
    mv = moved(bf, 0, -3, 0)
    r = f.run_checks(hardware, with_part(parts, "beam_front", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("beam_front moved 3 mm in front of Y = 0", "CHECK8 beam_front reaches Y = -3.00, in front of 0",
         r["failures"], "CHECK8 beam_front reaches Y", "in front of 0")

    # 2e. check 8, top: a part raised above the 420's top face (antler_right up by 10 mm in Z is 7.07 mm in n: 121 -> 128.07)
    ant = part_named(parts, "antler_right")
    mv = moved(ant, 0, 0, 10)
    r = f.run_checks(hardware, with_part(parts, "antler_right", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("antler_right raised 10 mm", "CHECK8 antler_right rises above the 420's top face: n = 128.07, limit 123",
         r["failures"], "CHECK8 antler_right rises above", "limit 123")
    check("  the undamaged frame stays below the 420's top face", base["envelope"]["top"][2] <= hw.ENVELOPE_N,
          (f"highest n of the frame <= {hw.ENVELOPE_N:g}", f"{base['envelope']['top'][2]:.2f} ({base['envelope']['top'][3]})"))
    wide = part_named(parts, "visor_arm_right")
    mv = moved(wide, 0, 0, 3)
    r = f.run_checks(hardware, with_part(parts, "visor_arm_right", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("visor_arm_right raised 3 mm (n 122 -> 124.12)", "CHECK8 visor_arm_right rises above the 420's top face",
         r["failures"], "CHECK8 visor_arm_right rises above")

    # 2f. check 10: a guide whose channel is 2 mm too small, one 2 mm too large, one whose mouth is too narrow
    for gname, build in (("hose_guide_cpu", f.build_hose_guide_cpu), ("hose_guide_gpu", f.build_hose_guide_gpu)):
        (solid, holes, blank), _ = build(shrink=2.0)
        r = f.run_checks(hardware, with_part(parts, gname, solid=solid, blank=blank, holes=holes), MEMO)
        case(f"{gname} with the channel 2 mm too small", f"CHECK10 {gname} x ...: the guide intersects the true hose",
             r["failures"], f"CHECK10 {gname}", "intersects the true hose")
        (solid, holes, blank), _ = build(shrink=-2.0)
        r = f.run_checks(hardware, with_part(parts, gname, solid=solid, blank=blank, holes=holes), MEMO)
        case(f"{gname} with the channel 2 mm too large", f"CHECK10 {gname} x ...: channel wall is 2.30 mm from the true hose, needs 0.2..0.5",
             r["failures"], f"CHECK10 {gname}", "channel wall is 2.30 mm", "needs 0.2..0.5")
        check(f"  the undamaged {gname} passes check 10",
              not [x for x in base["failures"] if x.startswith("CHECK10") and gname in x] and
              all(0.2 <= row[3] <= 0.5 and row[2] < 1.0 and row[4] for row in base["guides"] if row[0] == gname),
              ("overlap < 1 mm3, wall within 0.2..0.5, mouth right",
               "; ".join(f"hose {row[1]}: {row[2]:.2f} mm3, wall {row[3]:.2f} mm, mouth {'ok' if row[4] else 'WRONG'}" for row in base["guides"] if row[0] == gname)))
    saved_mouth = f.GUIDE_MOUTH
    f.GUIDE_MOUTH = 0.5
    try:
        (solid, holes, blank), _ = f.build_hose_guide_cpu()
    finally:
        f.GUIDE_MOUTH = saved_mouth
    r = f.run_checks(hardware, with_part(parts, "hose_guide_cpu", solid=solid, blank=blank, holes=holes), MEMO)
    case("hose_guide_cpu built with a 0.5 x diameter mouth", "CHECK10 hose_guide_cpu x ...: the mouth is not 9.3 mm wide",
         r["failures"], "CHECK10 hose_guide_cpu", "the mouth is not 9.3 mm wide")

    # 2g. side fans and their brackets (revision 7)
    br_l = part_named(parts, "fan_bracket_left")
    br_r = part_named(parts, "fan_bracket_right")
    h_l = next(h for h in br_l.holes if h.kind == "M4S")
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_left", solid=refilled(br_l, h_l)), MEMO)
    case("fan_bracket_left: one fan screw pilot filled back in", "CHECK7 fan_bracket_left ... M4S pilot ... is not drilled",
         r["failures"], "CHECK7 fan_bracket_left", "M4S pilot", "is not drilled")
    case("  same damage, left fan screw count derived from the solids", "CHECK5 fan_side_left: 2 of 4 corner holes",
         r["failures"], "CHECK5 fan_side_left: 2 of 4")
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_left", solid=br_l.blank), MEMO)
    case("fan_bracket_left undrilled (blank instead of the part)", "CHECK5 fan_side_left: 0 of 4 corner holes",
         r["failures"], "CHECK5 fan_side_left: 0 of 4")
    mv = moved(br_l, -5, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_left", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("fan_bracket_left moved 5 mm into fan_side_left", "CHECK2 part x hardware fan_bracket_left x fan_side_left",
         r["failures"], "CHECK2 part x hardware fan_bracket_left x fan_side_left")
    mv = moved(br_r, 5, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_right", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("fan_bracket_right moved 5 mm into fan_side_right", "CHECK2 part x hardware fan_bracket_right x fan_side_right",
         r["failures"], "CHECK2 part x hardware fan_bracket_right x fan_side_right")
    mv = moved(br_r, 0, -4 * hw.C, -4 * hw.C)        # 4 mm down-slope along u: 7.03 -> 3.03 mm from gpu_hoses
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_right", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("fan_bracket_right moved 4 mm along u, 3 mm from gpu_hoses", "CHECK9 fan_bracket_right is 3.03 mm from gpu_hoses, needs 5",
         r["failures"], "CHECK9 fan_bracket_right", "gpu_hoses", "needs 5")
    ap_blank = f.bsx(*f.fan_bracket_geometry("fan_bracket_left")[0], 180.0, 200.0, 20.0, 40.0)    # a block in the middle of the fan's circle
    fused = br_l.solid.fuse(ap_blank).clean()
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_left", solid=fused), MEMO)
    case("fan_bracket_left with a block across the fan's open circle", "CHECK11 fan_bracket_left has N mm3 inside the open circle",
         r["failures"], "CHECK11 fan_bracket_left", "inside the open circle")
    check("  the undamaged brackets keep out of the circle", all(v < f.VOL_EPS for _, v, _ in base["apertures"]) and len(base["apertures"]) == 2,
          ("2 brackets, 0 mm3 each", "; ".join(f"{a} {v:.2f} mm3, gap {d:.2f} mm" for a, v, d in base["apertures"])))
    wide = f.bsx(*f.fan_bracket_geometry("fan_bracket_left")[0], 120.0, 135.0, 20.0, 40.0)   # touches the circle's low-u edge (u 123)
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_left", solid=br_l.solid.fuse(wide).clean()), MEMO)
    case("fan_bracket_left with a block that bites 12 mm into the circle's edge", "CHECK11 fan_bracket_left ... inside the open circle",
         r["failures"], "CHECK11 fan_bracket_left", "inside the open circle")
    # fan corner holes are the revision-7 mount table: the left bracket uses A, B, C from the inner face; the right one A, C from the inner
    # face (B, D are 4.1 mm from gpu_hoses there) and D from the outside through the revision-7a tab
    check("both fans have 3 screws", base["mounts"]["fan_side_left"] == 3 and base["mounts"]["fan_side_right"] == 3,
          ("left 3, right 3", f"left {base['mounts']['fan_side_left']}, right {base['mounts']['fan_side_right']}"))
    tab_x = f.hw.FAN_SIDE_X["fan_side_right"][1]
    tab_holes = [h for h in br_r.holes if h.kind == "M4c"]
    check("the right bracket's third screw is the outer tab: two M4S pilots and one clearance hole, no inner pilot at corner D",
          len([h for h in br_r.holes if h.kind == "M4S"]) == 2 and len(tab_holes) == 1 and tab_holes[0].start[0] < tab_x < tab_holes[0].start[0] + tab_holes[0].length,
          ("2 M4S + 1 M4c through the tab (X 226..228.5)", f"{len([h for h in br_r.holes if h.kind == 'M4S'])} M4S, {len(tab_holes)} M4c"))
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_right", solid=refilled(br_r, tab_holes[0])), MEMO)
    case("fan_bracket_right: tab clearance hole filled back in", "CHECK7 fan_bracket_right ... M4c ... is not drilled",
         r["failures"], "CHECK7 fan_bracket_right", "is not drilled")
    case("  same damage, right fan screw count derived from the solids", "CHECK5 fan_side_right: 2 of 4 corner holes",
         r["failures"], "CHECK5 fan_side_right: 2 of 4")
    h_r = next(h for h in br_r.holes if h.kind == "M4S")
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_right", solid=refilled(br_r, h_r)), MEMO)
    case("fan_bracket_right: one inner pilot filled back in (the tab alone does not make three)", "CHECK5 fan_side_right: 2 of 4 corner holes",
         r["failures"], "CHECK5 fan_side_right: 2 of 4")
    mv = moved(br_r, 1.0, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_right", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("fan_bracket_right moved 1 mm outwards: the tab passes |X| = 229", "CHECK8 fan_bracket_right reaches |X| = 229.50, limit 229",
         r["failures"], "CHECK8 fan_bracket_right", "|X|")
    near = f.bsx(198.0, 202.0, 235.0, 262.0, 98.5, 104.0)        # the rail's inboard face brought 4 mm closer to the hoses
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_right", solid=br_r.solid.fuse(near).clean()), MEMO)
    case("fan_bracket_right rail widened 4 mm inboard", "CHECK9 fan_bracket_right is N mm from gpu_hoses, needs 5",
         r["failures"], "CHECK9 fan_bracket_right", "gpu_hoses", "needs 5")
    drop = f.bsx(202.0, 226.0, 150.0, 170.0, 90.0, 104.0)         # the rail with a block hanging into the fan's open circle (n 95 at the top)
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_right", solid=br_r.solid.fuse(drop).clean()), MEMO)
    case("fan_bracket_right rail with a block hanging into the fan's open circle", "CHECK11 fan_bracket_right has N mm3 inside the open circle",
         r["failures"], "CHECK11 fan_bracket_right", "inside the open circle")
    check("undamaged model: no failure at all, including the right fan and its rail and tab", not base["failures"],
          ("0 failures", f"{len(base['failures'])}: {'; '.join(base['failures'][:3])}"))

    # 3. two parts overlapping each other
    bf = part_named(parts, "beam_front")
    mv = moved(bf, 5, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "beam_front", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("beam_front moved 5 mm into rib_A_right", "CHECK3 part x part beam_front x rib_A_right",
         r["failures"], "CHECK3 part x part", "beam_front", "rib_A_right")

    # 4. a left-hand part: one clearance hole filled, and right-hand cutters on a left-hand part
    lp = part_named(parts, "rib_A_left")
    hl = next(h for h in lp.holes if h.kind == "M4c")
    r = f.run_checks(hardware, with_part(parts, "rib_A_left", solid=refilled(lp, hl)), MEMO)
    case("rib_A_left: one M4 clearance hole filled", "CHECK7 rib_A_left ... M4c clearance ... is not drilled",
         r["failures"], "CHECK7 rib_A_left", "M4c clearance", "is not drilled")
    rp = part_named(parts, "rib_A_right")
    r = f.run_checks(hardware, with_part(parts, "rib_A_left", holes=[h for h in rp.holes]), MEMO)
    case("rib_A_left carrying the right-hand cutters", "CHECK7 rib_A_left ... does not run through this part's material",
         r["failures"], "CHECK7 rib_A_left", "does not run through")
    check("left-hand cutters are mirrored",
          all(any(abs(a.start[0] + b.start[0]) < 1e-9 and a.start[1:] == b.start[1:] for b in rp.holes) for a in lp.holes),
          ("every rib_A_left hole is a rib_A_right hole mirrored in X", f"{len(lp.holes)} left holes checked"))

    # 5. hardware table shifted by 5 mm, the hole in the part left where it was
    atx0 = hw.ATX_HOLES[0]
    hw.ATX_HOLES[0] = (atx0[0] + 5.0, atx0[1])
    try:
        r = f.run_checks(hardware, parts, MEMO)
    finally:
        hw.ATX_HOLES[0] = atx0
    check("ATX hole A shifted 5 mm in hardware.py", r["mounts"]["board"] == base["mounts"]["board"] - 1,
          (f"board count {base['mounts']['board']} -> {base['mounts']['board'] - 1}",
           f"board count {r['mounts']['board']}; {first_match(r['failures'], 'CHECK5 board')}"))
    case("  same damage, the failure line", "CHECK5 board: 8 positions", r["failures"], "CHECK5 board: 8 positions")

    old_x = hw.RAD420_HOLES_X
    hw.RAD420_HOLES_X = tuple(x + 5.0 if abs(x - 77.75) < 1e-9 else x for x in old_x)
    try:
        r = f.run_checks(hardware, parts, MEMO)
    finally:
        hw.RAD420_HOLES_X = old_x
    check("rad420 hole x = 77.75 shifted 5 mm in hardware.py", r["mounts"]["rad420"] == base["mounts"]["rad420"] - 1,
          (f"rad420 count {base['mounts']['rad420']} -> {base['mounts']['rad420'] - 1}",
           f"rad420 count {r['mounts']['rad420']}; {first_match(r['failures'], 'CHECK5 rad420')}"))

    # the left fan's corner A shifted 5 mm along u in hardware.py: its screw count must drop from 3 to 2, which is below the minimum
    a0 = hw.FAN_SIDE_HOLES_UN["A"]
    hw.FAN_SIDE_HOLES_UN["A"] = (a0[0] + 5.0, a0[1])
    try:
        r = f.run_checks(hardware, parts, MEMO)
    finally:
        hw.FAN_SIDE_HOLES_UN["A"] = a0
    check("side fan corner A shifted 5 mm in hardware.py", r["mounts"]["fan_side_left"] == base["mounts"]["fan_side_left"] - 1,
          (f"left fan count {base['mounts']['fan_side_left']} -> {base['mounts']['fan_side_left'] - 1}",
           f"left fan count {r['mounts']['fan_side_left']}; right {r['mounts']['fan_side_right']}"))
    case("  same damage, the failure line", "CHECK5 fan_side_left: 2 of 4 corner holes have a screw hole in fan_bracket_left, the plan needs at least 3",
         r["failures"], "CHECK5 fan_side_left: 2 of 4")

    # 5b. a hand-written count that disagrees with the solids
    keep = [dict(x) for x in f.FASTENERS]
    for x in f.FASTENERS:
        if x["item"] == "rad360":
            x["count"] += 1
    try:
        r = f.run_checks(hardware, parts, MEMO)
    finally:
        f.FASTENERS[:] = keep
    case("hand-written rad360 count raised by one", "CHECK5 rad360: the fastener list says 5, the solids show 4",
         r["failures"], "CHECK5 rad360", "fastener list says 5")

    # 6. an intersect that raises
    victim = part_named(parts, "beam_mid").solid

    def make_boom(orig):
        def boom(self, *a, **k):
            if self is victim or any(x is victim for x in a):
                raise RuntimeError("injected failure")
            return orig(self, *a, **k)
        return boom

    with patched_intersect(make_boom):
        r = f.run_checks(hardware, parts)
        try:
            f.inter_vol(victim, hardware["board"])
            raised = False
        except f.BooleanFailure:
            raised = True
        shapes = {"beam_mid": victim, "hw:board": hardware["board"]}
        measure.FAILED.clear()
        line = measure.pair(shapes, "beam_mid", "hw:board")
        measured_loudly = "ERROR" in line and "0.0 mm" not in line and len(measure.FAILED) == 1
        measure.FAILED.clear()
    case("intersect() raises for beam_mid", "CHECK2/CHECK3 ... beam_mid ... BOOLEAN FAILED",
         r["failures"], "beam_mid", "BOOLEAN FAILED")
    check("inter_vol propagates the error", raised, ("inter_vol raises BooleanFailure", f"raised = {raised}"))
    check("measure.py prints ERROR and exits non-zero instead of 0", measured_loudly, ("an ERROR line, FAILED recorded", line))

    # 6b. intersect that finds nothing for two overlapping parts
    a = hw.wbox(0, 10, 0, 10, 0, 10)
    b = hw.wbox(5, 15, 0, 10, 0, 10)
    empty = cq.Compound.makeCompound([])
    with patched_intersect(lambda orig: (lambda self, *x, **k: empty)):
        try:
            v = f.inter_vol(a, b)
            res_txt = f"returned {v}"
            raised = False
        except f.BooleanFailure as e:
            res_txt, raised = f"BooleanFailure: {e}", True
        # touching boxes and boxes that are apart must still read 0 with the same empty answer
        touch = f.inter_vol(a, hw.wbox(10, 20, 0, 10, 0, 10))
        apart = f.inter_vol(a, hw.wbox(30, 40, 0, 10, 0, 10))
    check("empty intersect() on two overlapping boxes is not read as 0", raised and touch == 0.0 and apart == 0.0,
          ("BooleanFailure for the 5 mm overlap; 0 for touching and for apart", f"{res_txt}; touching {touch}; apart {apart}"))
    lshape = hw.wbox(0, 20, 0, 5, 0, 5).fuse(hw.wbox(0, 5, 0, 20, 0, 5)).clean()
    far = hw.wbox(12, 20, 12, 20, 0, 5)           # inside the L's bounding box, not touching it
    check("overlapping boxes, shapes apart: 0 confirmed by distance()", f.inter_vol(lshape, far) == 0.0,
          ("0 mm3", f"{f.inter_vol(lshape, far)} mm3, distance {f.solid_distance(lshape, far):.2f}"))

    # 7. minimum wall: two holes too close, a hole too close to the surface
    rpart = part_named(parts, "rib_A_right")
    base_hole = next(h for h in rpart.holes if h.kind == "M4c")
    near = base_hole.moved(0, 5.7, 0)      # centres 5.7 apart: wall 5.7 - 4.5 = 1.2 mm
    damaged = with_part(parts, "rib_A_right", solid=rpart.solid.cut(near.solid), holes=rpart.holes + [near])
    r = f.run_checks(hardware, damaged, MEMO)
    case("rib_A_right: second M4 clearance hole 1.2 mm from the first", "CHECK7 rib_A_right ... wall 1.2x mm < 2.1 mm",
         r["failures"], "CHECK7 rib_A_right", "wall 1.2", "< 2.1 mm")
    bh = part_named(parts, "psu_bulkhead")
    edge = f.clear_hole("M3c", (f.X_IN - hw.M3_CLEAR_D / 2 - 1.2, hw.PSU_REAR_Y - f.OVERSHOOT, 40.0), (0, 1, 0), 7.0)
    damaged = with_part(parts, "psu_bulkhead", solid=bh.solid.cut(edge.solid), holes=bh.holes + [edge])
    r = f.run_checks(hardware, damaged, MEMO)
    case("psu_bulkhead: M3 hole 1.2 mm from the plate end", "CHECK7 psu_bulkhead ... wall 1.2x mm < 1.6 mm",
         r["failures"], "CHECK7 psu_bulkhead", "wall 1.2", "< 1.6 mm")

    # 8. hardware literals in frame_v0.py
    with open(os.path.join(HERE, "frame_v0.py"), encoding="utf-8") as fh:
        src = fh.read()
    # the 420's holes moved from world Z (252.75, 377.25) to board-space n (-8.25, 116.25) in revision 5: the first two
    # are no longer hardware.py values, 116.25 is, and the scanner ignores values below 10
    old_antler = "holes = [(77.75, -8.25), (202.25, -8.25), (202.25, 116.25)]\nx = hw.x_to_v(172.5)\n"
    seeded = hardware_literals(old_antler)
    check("literal scanner finds retyped antler / arm literals", len(seeded) == 5,
          ("5 hits: 77.75, 202.25 twice, 116.25 and 172.5 (the -8.25 are below the scanner's threshold of 10)",
           ", ".join(str(v) for _, v in seeded)))
    real = hardware_literals(src)
    check("no hardware.py hole value is retyped in frame_v0.py", not real,
          ("no hits", "no hits" if not real else ", ".join(f"line {ln}: {v}" for ln, v in real)))

    # 9. check 12 (revision 8): a plate built without rounding is reported, a rounded plate passes
    ref = f.reference_parts()                 # the skeleton as built before revision 8: sharp corners
    for pname in ("antler_right", "neck_left", "rib_A_left"):
        r0 = ref[pname]
        r = f.run_checks(hardware, with_part(parts, pname, solid=r0.solid, blank=r0.blank, holes=r0.holes), MEMO)
        case(f"{pname} built without rounding", f"CHECK12 {pname}: no corner of this plate was rounded: N sharp outline corners, as many as the unrounded part has",
             r["failures"], f"CHECK12 {pname}: no corner of this plate was rounded")
    rows = {row[0]: row for row in f.explain_corners(parts, hardware, MEMO)}
    plates = [p.name for p in parts if f.plate_axes(p.name) is not None]
    check("every rounded plate has fewer sharp outline corners than its unrounded build, and no CHECK12 failure",
          not [x for x in base["failures"] if x.startswith("CHECK12")] and len(rows) == len(plates) == 12
          and {r[0]: (r[1], r[2]) for r in base["corners"]} == {n: (rows[n][1], rows[n][2]) for n in rows}
          and all(rows[n][1] < rows[n][2] for n in plates),
          ("12 plates, each with fewer sharp corners than unrounded, none reported",
           "; ".join(f"{n} {rows[n][1]}/{rows[n][2]}" for n in plates)))
    check("the sharp corners that remain on the rounded plates are all explained (lap step, contact, declared, run-out)",
          all(rows[n][3]["open"] == 0 for n in plates),
          ("0 unexplained", "; ".join(f"{n} {rows[n][3]['open']}" for n in plates if rows[n][3]["open"]) or "0"))
    cube = hw.wbox(0, 20, 0, 20, 0, 20)       # the corner finder itself: four sharp edges along X on a cube, none once they are rounded
    rounded_cube = cube
    for hi_i in (False, True):
        for hi_j in (False, True):
            rounded_cube = rounded_cube.cut(f.corner_wedge(((0, 0, 0), (20, 20, 20)), 0, hi_i, hi_j, 3.0, -1.0, 21.0))
    n_plain = len(f.rd.sharp_axial_edges(cube, [(1, 0, 0)], caps=False))
    n_round = len(f.rd.sharp_axial_edges(rounded_cube, [(1, 0, 0)], caps=False))
    check("the corner finder sees the four sharp edges of a cube and none once its long edges are rounded", n_plain == 4 and n_round == 0,
          ("4 sharp edges, then 0", f"{n_plain}, then {n_round}"))

    # 10. revision 8a's limit, measured on the solids: a contact keeps 97 % of its area and 4 mm of flat contact round every screw
    r = dict(base, failures=[])
    rows = f.check_contact_areas(parts, hardware, r)
    lost = [x for x in rows if x[3] < x[2] - 1e-3]
    check("every listed contact keeps at least 97 % of its unrounded area, and the flat contact round every screw", not r["failures"] and len(rows) == len(base["contacts"]) + len(base["pp_contact"]) > 30
          and all(x[3] >= f.rd.CONTACT_FLOOR * x[2] for x in rows) and len(lost) > 0,
          ("no CONTACT failure over all listed pairs, and 8a really took area from some",
           f"{len(rows)} pairs, {len(lost)} lost area, {len(r['failures'])} failures; lowest share {min(100 * x[3] / x[2] for x in rows):.2f} %"))
    ant = part_named(parts, "antler_right")
    face_u = (f.ANTLER_U[0] - 1.0, f.ANTLER_U[1] + 1.0)
    n_lo = hw.RAD420_HOLES_N[0] + f.ANTLER_BAR_HALF
    small = ant.solid.cut(f.bsx(67.0, 71.0, *face_u, n_lo - 4.0, n_lo + 1.0))          # a 4 x 4 mm corner, 7 mm from the nearest screw: 0.3 % of the contact, which 8a allows
    r = dict(base, failures=[])
    f.check_contact_areas(with_part(parts, "antler_right", solid=small), hardware, r)
    check("antler_right with a 4 x 4 mm corner off its contact face is no CONTACT failure (revision 8a allows 3 %)", not first_match(r["failures"], "CONTACT antler_right x rad420"),
          ("no failure: 0.3 % of 4640 mm2", "; ".join(r["failures"][:2]) or "none"))
    near = ant.solid.cut(f.bsx(67.0, 74.0, *face_u, n_lo - 6.0, n_lo + 1.0))          # a 7 x 7 mm corner: 1.1 % of the contact, but it reaches to within 4 mm of the screw's pilot
    r = dict(base, failures=[])
    f.check_contact_areas(with_part(parts, "antler_right", solid=near), hardware, r)
    case("antler_right with a 7 x 7 mm corner off its contact face, 1.1 % of it but within 4 mm of a screw", "CONTACT antler_right x rad420: the flat contact within 4 mm of the screw hole ... fell",
         r["failures"], "CONTACT antler_right x rad420", "flat contact within 4 mm of the screw hole")
    big = ant.solid.cut(f.bsx(67.0, 87.0, *face_u, n_lo - 10.0, n_lo + 1.0))            # 20 x 10 mm off the face: 4.3 % of the contact
    r = dict(base, failures=[])
    f.check_contact_areas(with_part(parts, "antler_right", solid=big), hardware, r)
    case("antler_right with 20 x 10 mm cut off its contact face (4.3 %)", "CONTACT antler_right x rad420: the contact area fell from 4640.050 to ..., 95.x % of the unrounded area (floor 97 %)",
         r["failures"], "CONTACT antler_right x rad420", "the contact area fell", "floor 97 %")
    ring = part_named(parts, "visor_arm_right")
    sc = next(h for h in ring.holes if h.kind == "M3c")                 # the arm's radiator screw along n, 4 mm of flat contact round it on the 360's face
    bite = hw.bs_cyl(sc.screw_r() + f.rd.SCREW_FLAT - 1.0, hw.x_to_v(hw.RAD360_HOLES_X[-1]), hw.RAD360_HOLES_U[1], hw.RAD360_INNER_N - 3.0, hw.RAD360_INNER_N + 1.0)
    r = dict(base, failures=[])
    f.check_contact_areas(with_part(parts, "visor_arm_right", solid=ring.solid.cut(bite)), hardware, r)
    case("visor_arm_right with the flat contact round a radiator screw eaten to within 3 mm of the hole (area loss under 3 %)", "CONTACT visor_arm_right x rad360: the flat contact within 4 mm of the screw hole fell",
         r["failures"], "CONTACT visor_arm_right x rad360", "flat contact within 4 mm of the screw hole")

    # 10b. the rounding itself refuses a corner that would take a contact below 97 %, and shares the allowance out (rounding.Guard, on a plate on a base)
    import cadquery as _cq

    def round_plate(w, l, screw=None):
        base_plane = hw.wbox(-60, 100, -60, 100, -10, 0)
        plate = hw.wbox(0, w, 0, l, 0, 10)
        face = next(fc for fc in plate.Faces() if fc.normalAt().z < -0.99)
        nbs = f.rd.Neighbors([f.rd.Neighbor("base", base_plane, "hw")])
        guard = f.rd.Guard(nbs, (0, 0, 10), selfshape=plate, own="plate", screws=[((screw[0], screw[1], 0.0), (0, 0, 1), 2.0)] if screw else [])
        log = []
        new = f.rd.round_face(face, part="plate", convex_r=6.0, concave_r=8.0, r_min=2.0, guard=guard, log=log)
        a1 = f.contact_area(f.rd.extrude_face(new, (0, 0, 10)), base_plane)
        return log, w * l, a1
    log, a0, a1 = round_plate(40, 40)
    check("a 40 x 40 contact takes four 6 mm corners (7.7 mm2 each, 1.9 % in all)", [e.radius for e in log] == [6.0] * 4 and a1 >= 0.97 * a0,
          ("four corners at r = 6, at least 97 % left", f"radii {[e.radius for e in log]}, {100 * a1 / a0:.2f} % left"))
    log, a0, a1 = round_plate(10, 10)
    check("a 10 x 10 contact: three corners at 2 mm, the fourth stays sharp, and the contact stays above 97 %", sorted(e.radius for e in log) == [0.0, 2.0, 2.0, 2.0] and a1 >= 0.97 * a0
          and any("allowance" in e.reason for e in log if e.radius == 0),
          ("radii 0, 2, 2, 2 (four 2 mm corners would take 3.4 %), the sharp one refused for the allowance", f"radii {[e.radius for e in log]}, {100 * a1 / a0:.2f} % left; {[e.reason[:60] for e in log if e.radius == 0]}"))
    log, a0, a1 = round_plate(4, 4)
    check("a 4 x 4 contact: a 2 mm corner would take 5.4 % of it, so no corner is rounded", [e.radius for e in log] == [0.0] * 4 and abs(a1 - a0) < 1e-6
          and all("allowance" in e.reason for e in log),
          ("four sharp corners, area unchanged, each refused for the allowance", f"radii {[e.radius for e in log]}, {a1:.3f} of {a0:.3f} mm2; {[e.reason[:50] for e in log][:1]}"))
    log, a0, a1 = round_plate(40, 40, screw=(5.5, 5.5))
    corner = next(e for e in log if e.pt[0] < 1 and e.pt[1] < 1)
    check("a screw 5.5 mm from a corner holds that corner to 3 mm (4 mm of flat contact round the screw: the tangent point must stay 6 mm from its axis), the others reach 6",
          corner.radius == 3.0 and sorted(e.radius for e in log if e is not corner) == [6.0] * 3 and "flat contact" in corner.reason,
          ("corner next to the screw r = 3 with the screw reason, the rest 6", f"{corner.radius}: {corner.reason[:90]}; others {[e.radius for e in log if e is not corner]}"))

    # 10c. revision 9: the front sill, the module and the light line
    sill = part_named(parts, "front_sill")
    check("front_sill is one valid solid across X -140..140, 290 mm or less, and every part has a material", len(sill.solid.Solids()) == 1 and sill.solid.isValid()
          and abs(f.bbox_of(sill.solid)[0] + 140) < 1e-6 and abs(f.bbox_of(sill.solid)[1] - 140) < 1e-6
          and all(p.material in f.MATERIALS for p in parts),
          ("1 solid, X -140..140, materials in ABS/PA6", f"{len(sill.solid.Solids())} solid, X {f.bbox_of(sill.solid)[0]:.1f}..{f.bbox_of(sill.solid)[1]:.1f}"))
    check("only the two hose guides are PA6, every other part is ABS", sorted(p.name for p in parts if p.material == "PA6") == ["hose_guide_cpu", "hose_guide_gpu"]
          and all(p.material == "ABS" for p in parts if p.name not in f.GUIDE_PARTS),
          ("PA6: hose_guide_cpu, hose_guide_gpu; the other parts ABS", ", ".join(f"{p.name}={p.material}" for p in parts if p.material != "ABS")))
    check("front_io and light_strip are hardware: front_io real, light_strip a keep-out; both in front of Y = 0 nowhere", "front_io" in hardware and "light_strip" in hardware
          and "light_strip" in hw.KEEP_OUT and "front_io" not in hw.KEEP_OUT and base["envelope"]["front"][2] >= hw.ENVELOPE_Y0,
          ("both in build_hardware, min Y >= 0", f"min Y {base['envelope']['front'][2]:.1f} ({base['envelope']['front'][3]})"))
    d_io, d_ls = f.solid_distance(sill.solid, hardware["front_io"]), f.solid_distance(sill.solid, hardware["light_strip"])
    check("the pocket clears front_io and the channel clears light_strip, by their clearances", abs(d_io - f.SILL_POCKET_PLAY) < 0.05 and abs(d_ls - f.SILL_CHANNEL_PLAY) < 0.05
          and f.inter_vol(sill.solid, hardware["front_io"]) < f.VOL_EPS and f.inter_vol(sill.solid, hardware["light_strip"]) < f.VOL_EPS,
          (f"{f.SILL_POCKET_PLAY:g} mm and {f.SILL_CHANNEL_PLAY:g} mm, no overlap", f"{d_io:.2f} mm and {d_ls:.2f} mm"))
    check("the module stands on beam_front (a listed zero-gap contact) and the sill stands on beam_front (part x part contact)",
          ("beam_front", "front_io") in base["contacts"] and ("beam_front", "front_io") in f.INTENDED_CONTACTS and
          any(set(x) == {"beam_front", "front_sill"} for x in base["pp_contact"]),
          ("beam_front x front_io and beam_front x front_sill touch", f"{[c for c in base['contacts'] if 'front_io' in c]}, {[c for c in base['pp_contact'] if 'front_sill' in c]}"))
    check("front_io has one holder with two screws, derived from the solids", base["mounts"]["front_io"] == 2 and f.EXPECTED_MOUNTS["front_io"] == 2
          and sum(x["count"] for x in f.FASTENERS if x["item"] == "front_io") == 2,
          ("front_io 2, fastener list 2", f"derived {base['mounts']['front_io']}, listed {sum(x['count'] for x in f.FASTENERS if x['item'] == 'front_io')}"))
    check("front_sill is bolted to beam_front with at least 2 x M4", sum(1 for h in sill.holes if h.kind == "M4") >= 2 and sum(1 for h in part_named(parts, "beam_front").holes if h.kind == "M4c") >= 2,
          ("pilots in the sill and clearance holes in the beam, 4 each", f"{sum(1 for h in sill.holes if h.kind == 'M4')} pilots, {sum(1 for h in part_named(parts, 'beam_front').holes if h.kind == 'M4c')} clearance holes"))
    mv = moved(sill, 5, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "front_sill", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("front_sill moved 5 mm along X, its end wall into the module", "CHECK2 part x hardware front_sill x front_io", r["failures"], "CHECK2 part x hardware front_sill x front_io")
    high = dict(hardware, front_io=hw.wbox(*(hw.FRONT_IO_W[:4] + (hw.FRONT_IO_W[4] + 5.0, hw.FRONT_IO_W[5] + 5.0))))
    r = f.run_checks(high, parts, MEMO)
    case("front_io raised 5 mm in hardware: it enters the sill's roof", "CHECK2 part x hardware front_sill x front_io", r["failures"], "CHECK2 part x hardware front_sill x front_io")
    near_strip = dict(hardware, light_strip=hw.bs_box(*(hw.LIGHT_STRIP_BS[:4] + (hw.LIGHT_STRIP_BS[4] - 4.0, hw.LIGHT_STRIP_BS[5] - 4.0))))
    r = f.run_checks(near_strip, parts, MEMO)
    case("light_strip moved 4 mm into the sill's wall (n -4)", "CHECK2 part x hardware front_sill x light_strip", r["failures"], "CHECK2 part x hardware front_sill x light_strip")
    front = dict(hardware, front_io=hw.wbox(hw.FRONT_IO_W[0], hw.FRONT_IO_W[1], -3.0, hw.FRONT_IO_W[3] - 3.0, hw.FRONT_IO_W[4], hw.FRONT_IO_W[5]))
    r = f.run_checks(front, parts, MEMO)
    case("front_io moved 3 mm in front of Y = 0 (hardware reaches the envelope check)", "CHECK8 front_io reaches Y = -3.00, in front of 0", r["failures"], "CHECK8 front_io reaches Y", "in front of 0")
    wide = hw.wbox(-150.0, 150.0, 0.0, 10.0, 10.0, 20.0)
    r = f.run_checks(hardware, with_part(parts, "front_sill", solid=sill.solid.fuse(wide).clean()), MEMO)
    case("front_sill grown to X -150..150 (300 mm)", "CHECK4 front_sill is 300.0 mm (> 290.0)", r["failures"], "CHECK4 front_sill", "> 290")
    hs = next(h for h in sill.holes if h.kind == "M4")
    r = f.run_checks(hardware, with_part(parts, "front_sill", solid=refilled(sill, hs)), MEMO)
    case("front_sill: one M4 bolt pilot filled back in", "CHECK7 front_sill ... M4 pilot ... is not drilled", r["failures"], "CHECK7 front_sill", "M4 pilot", "is not drilled")
    r = f.run_checks(hardware, with_part(parts, "front_sill", solid=sill.blank), MEMO)
    case("front_sill undrilled: the module has no screw hole", "CHECK5 front_io: 0 positions have a hole", r["failures"], "CHECK5 front_io: 0 positions")
    s0 = hw.FRONT_IO_SCREWS[0]
    hw.FRONT_IO_SCREWS = ((tuple(s0[0][:1]) + (s0[0][1] + 5.0, s0[0][2]), s0[1]),) + hw.FRONT_IO_SCREWS[1:]
    try:
        r = f.run_checks(hardware, parts, MEMO)
    finally:
        hw.FRONT_IO_SCREWS = (s0,) + hw.FRONT_IO_SCREWS[1:]
    check("front_io screw 1 shifted 5 mm in hardware.py", r["mounts"]["front_io"] == base["mounts"]["front_io"] - 1,
          (f"front_io count {base['mounts']['front_io']} -> {base['mounts']['front_io'] - 1}", f"front_io count {r['mounts']['front_io']}; {first_match(r['failures'], 'CHECK5 front_io')}"))
    check("mass_estimate takes the material's density", abs(f.mass_estimate(sill.solid, "PA6")[1] / f.mass_estimate(sill.solid, "ABS")[1] - f.PA6_DENSITY / f.ABS_DENSITY) < 1e-9,
          (f"PA6/ABS mass ratio {f.PA6_DENSITY / f.ABS_DENSITY:.4f}", f"{f.mass_estimate(sill.solid, 'PA6')[1] / f.mass_estimate(sill.solid, 'ABS')[1]:.4f}"))

    # 10d. skeleton pass 1: the sill's cable window, and the insert pilots of the organic layer's twelve pads
    import numpy as np
    import organic_frame as of
    import cables
    g = f.sill_geometry()
    wx0, wx1, wz0, wz1 = g["window_xz"]
    io = hw.FRONT_IO_W
    ym = g["y_rear"] - f.SILL_REAR_WALL / 2                                       # the middle of the rear wall
    centre, wall_under = (cq.Vector((wx0 + wx1) / 2, ym, (wz0 + wz1) / 2), cq.Vector((wx0 + wx1) / 2, ym, io[4] + f.SILL_WINDOW_Z_LOW / 2))
    check("the sill's rear wall has the cable window and keeps the strip under it", not sill.solid.isInside(centre) and sill.solid.isInside(wall_under)
          and (wx0, wx1, wz0, wz1) == (40.0, 90.0, 14.0, 46.0),
          ("window X 40..90, Z 14..46 (offsets from hw.FRONT_IO_W): empty in the middle, wall below it", f"X {wx0:g}..{wx1:g}, Z {wz0:g}..{wz1:g}; middle empty {not sill.solid.isInside(centre)}, strip under it solid {sill.solid.isInside(wall_under)}"))
    old_io = hw.FRONT_IO_W
    hw.FRONT_IO_W = (old_io[0] + 10.0, old_io[1] + 10.0) + old_io[2:]
    try:
        moved_xz = f.sill_geometry()["window_xz"]
    finally:
        hw.FRONT_IO_W = old_io
    check("the window follows the module: FRONT_IO_W moved 10 mm in X moves it 10 mm", all(abs(a - b - 10.0) < 1e-9 for a, b in zip(moved_xz[:2], (wx0, wx1))) and moved_xz[2:] == (wz0, wz1),
          (f"X {wx0 + 10:g}..{wx1 + 10:g}, Z unchanged", f"X {moved_xz[0]:g}..{moved_xz[1]:g}, Z {moved_xz[2]:g}..{moved_xz[3]:g}"))
    filled = sill.solid.fuse(g["cuts"]["window"].intersect(f.Poly(g["pts"]).solid(-f.SILL_HALF_X, f.SILL_HALF_X))).clean()     # the sill as it was without the window
    parts_nowin = with_part(parts, "front_sill", solid=filled)
    routes = cables.build_routes()
    cables.evaluate(routes, parts_nowin, hardware)
    bad = [t for n in ("usb3", "usbc") for _c, t in routes[n].fail if "front_sill" in t]
    check("the two front USB cables go through the window: with it filled back in both hit the sill", len(bad) == 2,
          ("USB 3 and USB-C each report 'N mm from front_sill, needs 3'", "; ".join(bad) or "no failure"))
    routes = cables.build_routes()
    ov = cables.evaluate(routes, parts, hardware)
    check("with the window every cable check passes", not cables.failures(routes, ov), ("0 failed cable checks", f"{len(cables.failures(routes, ov))}: {'; '.join(t for _c, t in cables.failures(routes, ov)[:2])}"))

    pads = list(hw.ORGANIC_PADS.items())
    check("twelve pads, six a side, each with an M3 pilot in its part: derived from the solids", len(pads) == 12 and base["mounts"]["organic"] == 12 and f.EXPECTED_MOUNTS["organic"] == 12
          and sum(x["count"] for x in f.FASTENERS if x["item"] == "organic") == 12,
          ("organic 12 derived, 12 listed", f"{len(pads)} rows; derived {base['mounts']['organic']}, listed {sum(x['count'] for x in f.FASTENERS if x['item'] == 'organic')}"))
    nm, (pn, q0, sgn) = pads[0]
    pp = part_named(parts, pn)
    hp = next(h for h in pp.holes if h.kind == "M3" and h.pilot and of.is_pilot_of(h, q0, sgn))
    r = f.run_checks(hardware, with_part(parts, pn, solid=refilled(pp, hp)), MEMO)
    case(f"{nm}: its M3 pilot filled back in", f"CHECK7 {pn} ... M3 pilot ... is not drilled", r["failures"], f"CHECK7 {pn}", "M3 pilot", "is not drilled")
    case("  same damage, organic count derived from the solids", "CHECK5 organic: 11 positions have a hole", r["failures"], "CHECK5 organic: 11 positions")
    nm_l, (pn_l, q_l, sgn_l) = next(row for row in pads if row[1][0] == "neck_left")
    pl = part_named(parts, pn_l)
    r = f.run_checks(hardware, with_part(parts, pn_l, solid=refilled(pl, next(h for h in pl.holes if h.kind == "M3" and h.pilot))), MEMO)
    case(f"{nm_l}: the left neck's pilot (built right-handed, mirrored) filled back in", f"CHECK5 organic: 11 positions", r["failures"], "CHECK5 organic: 11 positions")
    hw.ORGANIC_PADS[nm] = (pn, (q0[0], q0[1] + 5.0, q0[2]), sgn)
    try:
        r = f.run_checks(hardware, parts, MEMO)
    finally:
        hw.ORGANIC_PADS[nm] = (pn, q0, sgn)
    case(f"{nm} shifted 5 mm in hardware.py, the pilot left where it was", "CHECK5 organic: 11 positions have a hole", r["failures"], "CHECK5 organic: 11 positions")

    def anchors_of(table):
        return [dict(name=n, part=p_, q=np.array(q_, dtype=float), n=np.array([float(s_), 0.0, 0.0])) for n, (p_, q_, s_) in table.items()]
    check("organic_frame: every pad's screw axis coincides with an M3 pilot of its part, on the part's face", not of.pad_pilot_failures(anchors_of(hw.ORGANIC_PADS), parts),
          ("no failure", "; ".join(of.pad_pilot_failures(anchors_of(hw.ORGANIC_PADS), parts)[:2]) or "none"))
    moved_pilot = with_part(parts, pn, holes=[h.moved(0.0, 0.5, 0.0) if h is hp else h for h in pp.holes])
    got = of.pad_pilot_failures(anchors_of(hw.ORGANIC_PADS), moved_pilot)
    check(f"organic_frame: the pilot of {nm} moved 0.5 mm in the part, the pad does not follow it", len(got) == 1 and nm in got[0] and "lies on no M3 pilot" in got[0],
          (f"one failure naming {nm}: the screw axis lies on no M3 pilot within 0.01 mm", "; ".join(got) or "NOTHING"))
    moved_pad = dict(hw.ORGANIC_PADS, **{nm: (pn, (q0[0], q0[1], q0[2] + 0.5), sgn)})
    got = of.pad_pilot_failures(anchors_of(moved_pad), parts)
    check(f"organic_frame: the pad {nm} moved 0.5 mm in the table, the pilot does not follow it", len(got) == 1 and nm in got[0] and "lies on no M3 pilot" in got[0],
          (f"one failure naming {nm}", "; ".join(got) or "NOTHING"))
    deep = dict(hw.ORGANIC_PADS, **{nm: (pn, (q0[0] - sgn * 1.0, q0[1], q0[2]), sgn)})
    got = of.pad_pilot_failures(anchors_of(deep), parts)
    check(f"organic_frame: the pad {nm} sunk 1 mm into the part is not on its face", any("not on" in x and nm in x for x in got),
          (f"a failure 'not on {pn}'s face'", "; ".join(got) or "NOTHING"))
    # pad_fits: a pad's own pilot is not "another hole too close"; any other hole is
    check("pad_fits ignores a pad's own pilot and accepts the pad", of.pad_fits(pp, np.array(q0), sgn) is None,
          ("None (fits)", str(of.pad_fits(pp, np.array(q0), sgn))))
    other = f.pilot((q0[0], q0[1] + 4.0, q0[2]), (-sgn, 0.0, 0.0), "M3")        # another M3 pilot 4 mm from the pad's axis (centres 6.1 needed)
    with_other = dataclasses.replace(pp, holes=pp.holes + [other])
    why = of.pad_fits(with_other, np.array(q0), sgn)
    check("pad_fits still counts every other hole: a second M3 pilot 4 mm from the axis rejects the pad", why is not None and "too close" in why and "M3 hole" in why,
          ("'... mm too close to the part's M3 hole'", str(why)))
    moved_own = dataclasses.replace(pp, holes=[h.moved(0.0, 0.5, 0.0) if h is hp else h for h in pp.holes])
    why = of.pad_fits(moved_own, np.array(q0), sgn)
    check("pad_fits: a pilot 0.5 mm off the pad's axis is not its own, and is too close", why is not None and "too close" in why, ("'... mm too close to the part's M3 hole'", str(why)))

    # last: the undamaged model, once more with nothing remembered
    final = f.run_checks(hardware, parts)
    check("undamaged model reports no failure", not base["failures"] and not final["failures"],
          ("0 failures, first with an empty memo and again without a memo",
           f"{len(base['failures'])} and {len(final['failures'])}: {'; '.join((base['failures'] + final['failures'])[:3])}"))

    bad = [n for ok, n in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} cases as expected   ({time.time() - t_start:.0f} s)")
    if bad:
        print("FAILED: " + "; ".join(bad))
        sys.exit(1)


if __name__ == "__main__":
    main()
