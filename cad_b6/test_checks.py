#!/usr/bin/env python3
"""Prove that the model's checks fail when the solid is wrong.

Builds the frame, then for each case damages a copy in memory (or a hardware table, or a boolean),
runs frame_v0.run_checks and asserts that the failure the damage should cause is reported. The last case
is the undamaged model, which must report nothing.

    .venv/bin/python cad_b6/test_checks.py                  # the sections in worker processes (about 5 min)
    .venv/bin/python cad_b6/test_checks.py --serial         # everything in this process, as before (about 32 min)
    .venv/bin/python cad_b6/test_checks.py --diff A.json B.json      # the two runs' case lists must be identical

The cases are grouped in sections (@section below). Each section depends only on the prelude (the hardware, the
frame and the undamaged model's checks), so a worker process runs the prelude once and then any section; the
output is printed in the sections' order whatever order they finished in. Neither mode drops, merges or reorders
a case.

One line per case: PASS/FAIL, name, the failure that was expected, what was reported.
Exit status 1 if any case fails, a section raises, a section records no case, or the run records fewer than
EXPECTED_CASES cases. The run's case list, its time and the counts of the expensive operations go
to out/test_checks/<fast|serial>.json, written atomically, with the SHA-256 of every file that decided the result, taken
before the model is imported and compared again at the end (a file that moved fails the run), and the versions of Python and
of every third-party package the run loaded (check_budgets.py reads the fast one and refuses it once one of those has changed).
"""
from __future__ import annotations

import argparse
import ast
import collections
import contextlib
import dataclasses
import functools
import io
import json
import math
import os
import resource
import sys
import time
import traceback
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import suite_record as sr  # noqa: E402

START_HASHES = sr.tree_hashes()     # the files as they are before any of the model's modules is imported: the record names the code the run read

import cadquery as cq  # noqa: E402
import numpy as np  # noqa: E402

import frame_v0 as f  # noqa: E402
import hardware as hw  # noqa: E402
import measure  # noqa: E402
import cables  # noqa: E402
import drive_access  # noqa: E402
import zone_access  # noqa: E402
import organic_frame as of  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, "out", "test_checks")
RESULTS: list[tuple[bool, str, str, str]] = []      # (passed, name, expected, reported), in the order printed
MEMO: dict = {}      # solid-identity memo for run_checks: a damaged copy recomputes only what touches the damage
SECTIONS: list[tuple[str, object]] = []             # (title, function(hardware, parts, base)), in the order printed

# The number of cases the suite records, pinned here so that a reviewer sees it change in the diff that adds or removes cases.
# A run that records fewer fails (a section emptied, cut short or skipped would otherwise pass as "N/N cases as expected"), and
# so does a section, or the prelude, that records none. A run that records more passes and says to raise this in the same commit.
# Not in budgets.json: check_budgets.py --write rewrites that file from a run's record, and the pin must not follow a run down.
EXPECTED_CASES = 302

# the expensive operations, counted per process: the budget of the time to verify gates on these (check_budgets.py)
COUNTS: collections.Counter = collections.Counter()
EXPENSIVE = ((f, "build_frame", "frame_builds"), (f, "run_checks", "run_checks"), (cables, "build_routes", "cable_routings"),
             (cables, "evaluate", "cable_evaluations"), (zone_access, "run", "zone_access_runs"), (drive_access, "bay_maps", "drive_access_maps"))


def _counted(fn, key):
    @functools.wraps(fn)
    def counted(*a, **k):
        COUNTS[key] += 1
        return fn(*a, **k)
    return counted


for _mod, _name, _key in EXPENSIVE:
    setattr(_mod, _name, _counted(getattr(_mod, _name), _key))


def section(title):
    def register(fn):
        SECTIONS.append((title, fn))
        return fn
    return register


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


def board_box(shape):
    """The shape's box in board space (v, u, n as x, y, z), exact: from the geometry, never from a mesh (see f.exact_box)."""
    return Box(*f.exact_box(hw.to_board(shape)))


Box = collections.namedtuple("Box", "xmin xmax ymin ymax zmin zmax")


def first_match(failures, *needles):
    for line in failures:
        if all(n in line for n in needles):
            return line
    return None


def case(name, expected, failures, *needles):
    """Record PASS when a failure containing every needle was reported."""
    got = first_match(failures, *needles)
    ok = got is not None
    record(ok, name, expected, got if ok else 'NOTHING MATCHING (' + str(len(failures)) + ' other failures: ' + '; '.join(failures[:3]) + ')')


def check(name, ok, detail):
    record(bool(ok), name, detail[0], detail[1])


def record(ok, name, expected, reported):
    RESULTS.append((ok, name, str(expected), str(reported)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}\n      expected: {expected}\n      reported: {reported}")


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
# ---------------------------------------------------------------------------
# the prelude every process runs once, then the sections
# ---------------------------------------------------------------------------
def prelude():
    """Build the hardware and the frame (twice), run every check on the undamaged model with an empty memo. Returns (hardware, parts, base)."""
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
    return hardware, parts, base



@section("1. a pilot hole filled back in, a part undrilled")
def s_pilot_holes(hardware, parts, base):
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


@section("2..2c. a part pushed into a component, into the hoses, near the hoses")
def s_into_hardware(hardware, parts, base):
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


@section("2d..2e. check 8: a hose pushed out, parts in front and above")
def s_envelope(hardware, parts, base):
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

    # 2e. check 8, top: a part raised above the 420's top face (antler_right up by 10 mm in Z is 7.07 mm in n: 124 -> 131.07; revision 11, second pass: the fans are 140 wide, the top face
    # is n 124, the plate reaches it; first pass 123, before it 121)
    ant = part_named(parts, "antler_right")
    mv = moved(ant, 0, 0, 10)
    r = f.run_checks(hardware, with_part(parts, "antler_right", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("antler_right raised 10 mm", "CHECK8 antler_right rises above the 420's top face: n = 131.07, limit 124",
         r["failures"], "CHECK8 antler_right rises above", "limit 124")
    check("  the undamaged frame stays below the 420's top face", base["envelope"]["top"][2] <= hw.ENVELOPE_N + 1e-6,      # check 8's own tolerance: the plate's top edge is the limit itself since revision 11, the arithmetic leaves 1e-9
          (f"highest n of the frame <= {hw.ENVELOPE_N:g}", f"{base['envelope']['top'][2]:.2f} ({base['envelope']['top'][3]})"))
    wide = part_named(parts, "visor_arm_right")
    mv = moved(wide, 0, 0, 3)
    r = f.run_checks(hardware, with_part(parts, "visor_arm_right", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("visor_arm_right raised 3 mm (n 122 -> 124.12)", "CHECK8 visor_arm_right rises above the 420's top face",
         r["failures"], "CHECK8 visor_arm_right rises above")


@section("2f. check 10: the hose guides' channels and mouths")
def s_guides(hardware, parts, base):
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


@section("2g. the side fans and their brackets")
def s_side_fans(hardware, parts, base):
    # 2g. side fans and their brackets (revision 7, rebuilt in revision 13: one design, the right one built where it stands, the left one its mirror)
    br_l = part_named(parts, "fan_bracket_left")
    br_r = part_named(parts, "fan_bracket_right")
    h_l = next(h for h in br_l.holes if h.pilot and h.item == "side fan")
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_left", solid=refilled(br_l, h_l)), MEMO)
    case("fan_bracket_left: one fan screw pilot filled back in", "CHECK7 fan_bracket_left ... M3 pilot ... is not drilled",
         r["failures"], "CHECK7 fan_bracket_left", "M3 pilot", "is not drilled")
    case("  same damage, left fan screw count derived from the solids", "CHECK5 fan_side_left: 2 of 4 corner holes",
         r["failures"], "CHECK5 fan_side_left: 2 of 4")
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_left", solid=br_l.blank), MEMO)
    case("fan_bracket_left undrilled (blank instead of the part)", "CHECK5 fan_side_left: 0 of 4 corner holes",
         r["failures"], "CHECK5 fan_side_left: 0 of 4")
    h_rib = next(h for h in br_l.holes if h.pilot and h.item == "fan bracket")
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_left", solid=refilled(br_l, h_rib)), MEMO)
    case("fan_bracket_left: one rib-bolt pilot in the leg filled back in", "CHECK7 fan_bracket_left ... M3 pilot ... is not drilled",
         r["failures"], "CHECK7 fan_bracket_left", "M3 pilot", "is not drilled")
    mv = moved(br_l, -5, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_left", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("fan_bracket_left moved 5 mm into fan_side_left", "CHECK2 part x hardware fan_bracket_left x fan_side_left",
         r["failures"], "CHECK2 part x hardware fan_bracket_left x fan_side_left")
    mv = moved(br_r, 5, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_right", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("fan_bracket_right moved 5 mm into fan_side_right", "CHECK2 part x hardware fan_bracket_right x fan_side_right",
         r["failures"], "CHECK2 part x hardware fan_bracket_right x fan_side_right")


@section("2g. the side fans' brackets near the hoses and in the fans' open circle")
def s_side_fans_circle(hardware, parts, base):
    br_l, br_r = part_named(parts, "fan_bracket_left"), part_named(parts, "fan_bracket_right")
    # the bracket towards the hoses: the right one is the near one (gpu_hoses 5.55 mm from its spine's foot and the root block); 3 mm towards -u leaves about 2.5 mm
    d_gpu = f.solid_distance(br_r.solid, hardware["gpu_hoses"])
    mv = moved(br_r, 0, -3 * hw.C, -3 * hw.C)
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_right", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("fan_bracket_right moved 3 mm along -u, towards gpu_hoses", f"CHECK9 fan_bracket_right is N mm from gpu_hoses, needs 5 (it is {d_gpu:.2f} mm in place)",
         r["failures"], "CHECK9 fan_bracket_right", "gpu_hoses", "needs 5")
    check("  the undamaged right bracket is 5 mm or more from gpu_hoses, and the left one far from cpu_hoses", d_gpu >= f.HOSE_CLEAR - 1e-6 and f.solid_distance(br_l.solid, hardware["cpu_hoses"]) >= f.HOSE_CLEAR,
          (f">= {f.HOSE_CLEAR:g} mm", f"right {d_gpu:.2f} mm from gpu_hoses, left {f.solid_distance(br_l.solid, hardware['cpu_hoses']):.2f} mm from cpu_hoses"))
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
    # revision 13: the probe reaches the rib, not 60 mm in from the fan's inner face (that covered a leg of 12 or 33 mm; the leg is 49 now): a block in the circle next to the rib is found
    near_rib = f.bsx(-170.0, -160.0, 150.0, 170.0, 20.0, 40.0)
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_left", solid=br_l.solid.fuse(near_rib).clean()), MEMO)
    case("fan_bracket_left with a block in the circle, 10 mm from the rib (X -170..-160)", "CHECK11 fan_bracket_left has N mm3 inside the open circle",
         r["failures"], "CHECK11 fan_bracket_left", "inside the open circle")
    rect_leg = f.bsx(*f.fan_bracket_geometry("fan_bracket_left")[1], 116.0, 140.0, *f.BRACKET_LEG_N)      # the old rectangular leg widened to u 140: it enters the circle (u 132.3 at n -6)
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_left", solid=br_l.solid.fuse(rect_leg).clean()), MEMO)
    case("fan_bracket_left with a rectangular leg 24 mm wide (the trapezoid leans away from the circle)", "CHECK11 fan_bracket_left has N mm3 inside the open circle",
         r["failures"], "CHECK11 fan_bracket_left", "inside the open circle")


@section("2g. the side fans' screws and the limits of check 8")
def s_side_fans_limits(hardware, parts, base):
    br_l, br_r = part_named(parts, "fan_bracket_left"), part_named(parts, "fan_bracket_right")
    # fan corner holes are the revision-13 mount table: both brackets use A, B, C from the inner face and none reaches D (the CPU hoses pass there on the left)
    check("both fans have 3 screws", base["mounts"]["fan_side_left"] == 3 and base["mounts"]["fan_side_right"] == 3,
          ("left 3, right 3", f"left {base['mounts']['fan_side_left']}, right {base['mounts']['fan_side_right']}"))
    fan_pilots = [h for h in br_r.holes if h.pilot and h.item == "side fan"]
    check("each bracket has three fan pilots (corners A, B, C), no clearance hole at the fan's outer face, and the right one is the left one mirrored",
          len(fan_pilots) == 3 and not [h for h in br_r.holes if h.kind == "M3c"] and not [h for h in br_l.holes if h.kind == "M3c"]
          and abs(br_l.solid.Volume() - br_r.solid.Volume()) < 1e-3 and all(any(abs(a.start[0] + b.start[0]) < 1e-9 and a.start[1:] == b.start[1:] for b in br_r.holes) for a in br_l.holes),
          ("3 fan pilots, 0 M3c, equal volumes, every left hole a right hole mirrored", f"{len(fan_pilots)} fan pilots, {len([h for h in br_r.holes if h.kind == 'M3c'])} M3c, volumes {br_l.solid.Volume():.0f} / {br_r.solid.Volume():.0f}"))
    h_r = fan_pilots[0]
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_right", solid=refilled(br_r, h_r)), MEMO)
    case("fan_bracket_right: one fan pilot filled back in", "CHECK5 fan_side_right: 2 of 4 corner holes",
         r["failures"], "CHECK5 fan_side_right: 2 of 4")
    # check 8: the brackets stand out to the fans' outer face, everything else stops at the radiators' ends
    check("the limits: the fans' brackets 260 (the fans' outer face), the skeleton 229", hw.ENVELOPE_FAN_X == 260.0 and hw.ENVELOPE_X == 229.0 and hw.ENVELOPE_FAN_X == max(abs(x) for xs in hw.FAN_SIDE_X.values() for x in xs)
          and base["envelope"]["parts_fan"][0] <= hw.ENVELOPE_FAN_X and base["envelope"]["parts_rest"][0] <= hw.ENVELOPE_X,
          ("fan brackets max |X| <= 260, other parts max |X| <= 229",
           f"brackets {base['envelope']['parts_fan'][0]:.1f}, others {base['envelope']['parts_rest'][0]:.1f} ({base['envelope']['parts_rest'][1]})"))
    mv = moved(br_r, 26.0, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_right", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("fan_bracket_right moved 26 mm outwards: past the fans' outer face (|X| 261)", "CHECK8 fan_bracket_right reaches |X| = 261.00, limit 260",
         r["failures"], "CHECK8 fan_bracket_right", "|X| = 261", "limit 260")
    mv = moved(br_l, -26.0, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_left", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("fan_bracket_left moved 26 mm outwards: past the fans' outer face (|X| 261)", "CHECK8 fan_bracket_left reaches |X| = 261.00, limit 260",
         r["failures"], "CHECK8 fan_bracket_left", "|X| = 261", "limit 260")
    ant_r = part_named(parts, "antler_right")
    mv = moved(ant_r, 2.0, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "antler_right", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("antler_right moved 2 mm outwards: the skeleton keeps the radiators' limit (|X| 229)", "CHECK8 antler_right reaches |X| = 230, limit 229",
         r["failures"], "CHECK8 antler_right reaches |X| = 230", "limit 229")


@section("2g. a part moved into each keep-out, gpu_post's frame")
def s_keepouts(hardware, parts, base):
    br_l = part_named(parts, "fan_bracket_left")
    # a part moved into each keep-out (the check is 2: part x hardware, every keep-out is hardware)
    mv = moved(br_l, 20.0, 0, 0)                       # the left bracket's spine (u 116..122, n up to 95) then stands in gpu_out_zone (X -204..-124, u 75.6..126.6, n 10..100)
    r = f.run_checks(hardware, with_part(parts, "fan_bracket_left", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("fan_bracket_left moved 20 mm inwards: its spine stands in gpu_out_zone", "CHECK2 part x hardware fan_bracket_left x gpu_out_zone",
         r["failures"], "CHECK2 part x hardware fan_bracket_left x gpu_out_zone")
    post = part_named(parts, "gpu_post")
    r = f.run_checks(hardware, with_part(parts, "gpu_post", solid=post.solid.fuse(hw.bs_box(-20.0, -5.5, 90.0, 110.0, 20.0, 60.0)).clean()), MEMO)
    case("gpu_post with a block in its window (the card's video outputs)", "CHECK2 part x hardware gpu_post x gpu_out_zone",
         r["failures"], "CHECK2 part x hardware gpu_post x gpu_out_zone")
    old_post = hw.bs_box(-20.0, -5.5, hw.GPU_BS[2] - 2.6, 146.0, hw.ATX_TRAY_N, hw.GPU_BRACKET_TAB_N)      # the solid block before revision 13
    r = f.run_checks(hardware, with_part(parts, "gpu_post", solid=old_post), MEMO)
    case("gpu_post as the solid block of revisions 2..12", "CHECK2 part x hardware gpu_post x gpu_out_zone", r["failures"], "CHECK2 part x hardware gpu_post x gpu_out_zone")
    rb = part_named(parts, "rib_B_left")
    r = f.run_checks(hardware, with_part(parts, "rib_B_left", solid=rb.solid.fuse(hw.bs_box(-40.0, -20.0, 180.0, 200.0, 0.0, 20.0)).clean()), MEMO)
    case("rib_B_left with a block in io_zone", "CHECK2 part x hardware rib_B_left x io_zone", r["failures"], "CHECK2 part x hardware rib_B_left x io_zone")
    # the frame that leaves the outputs open (revision 13, item 6): the window, the lintel under the tab's seat, the two columns outside the card's thickness
    window = hw.bs_box(*f.GPU_POST_V, hw.GPU_BS[2], hw.GPU_BS[3], hw.GPU_OUT_N[0], hw.GPU_OUT_N[1])
    in_window = f.inter_vol(post.solid, window)
    probes = {"lintel": (-12.0, (hw.GPU_BS[2] + hw.GPU_BS[3]) / 2, hw.GPU_BRACKET_TAB_N - 1.0), "low column": (-12.0, hw.GPU_BS[2] - f.GPU_POST_CLEAR - 3.0, 50.0),
              "high column": (-12.0, hw.GPU_BS[3] + f.GPU_POST_CLEAR + 5.0, 50.0), "base": (-12.0, (hw.GPU_BS[2] + hw.GPU_BS[3]) / 2, hw.ATX_TRAY_N + 3.0)}
    solid_at = {k: post.solid.isInside(cq.Vector(*hw.bp(*pt))) for k, pt in probes.items()}
    top = max(board_box(post.solid).zmax, 0.0)
    check("gpu_post is a frame: nothing in the opening (the card's whole thickness in u, n GPU_OUT_N), material in both columns, the lintel and the base, top at the tab's seat",
          in_window < f.VOL_EPS and all(solid_at.values()) and abs(top - hw.GPU_BRACKET_TAB_N) < 1e-3,
          (f"0 mm3 in the opening, solid at {sorted(probes)}, top n {hw.GPU_BRACKET_TAB_N:g}", f"{in_window:.2f} mm3 in the opening, {solid_at}, top n {top:.2f}"))
    check("gpu_post's every size follows hardware.py: window from the card's u range, lintel under the tab's seat, columns outside the card",
          abs(f.GPU_POST_U_WINDOW[0] - (hw.GPU_BS[2] - f.GPU_POST_CLEAR)) < 1e-9 and abs(f.GPU_POST_U_WINDOW[1] - (hw.GPU_BS[3] + f.GPU_POST_CLEAR)) < 1e-9
          and abs(f.GPU_POST_N_RANGE[1] - hw.GPU_BRACKET_TAB_N) < 1e-9 and f.GPU_POST_N_WINDOW[1] == hw.GPU_OUT_N[1] + f.GPU_POST_CLEAR and f.GPU_POST_N_WINDOW[0] == hw.GPU_OUT_N[0] - f.GPU_POST_CLEAR,
          ("window u (GPU_BS u range +- 0.5), window n (GPU_OUT_N -+ 0.5), top n GPU_BRACKET_TAB_N", f"window u {f.GPU_POST_U_WINDOW}, n {f.GPU_POST_N_WINDOW}, top {f.GPU_POST_N_RANGE[1]:g}"))
    check("hardware: gpu_out_zone is 80 mm out from the card's bracket (v -82..-2), the card's whole thickness in u, n 10..100, and a keep-out",
          "gpu_out_zone" in hw.KEEP_OUT and "gpu_out_zone" in hardware and hw.GPU_OUT_ZONE_BS == (hw.GPU_BS[0] - 80.0, hw.GPU_BS[0], hw.GPU_BS[2], hw.GPU_BS[3], 10.0, 100.0)
          and (hw.GPU_OUT_ZONE_BS[0], hw.GPU_OUT_ZONE_BS[1]) == (-82.0, -2.0),
          ("v -82..-2, u = the card's, n 10..100", f"{hw.GPU_OUT_ZONE_BS}"))
    check("undamaged model: no failure at all, including both fan brackets, gpu_post and the two keep-outs", not base["failures"],
          ("0 failures", f"{len(base['failures'])}: {'; '.join(base['failures'][:3])}"))


@section("2h. zone_access.py")
def s_zone_access(hardware, parts, base):
    # 2h. revision 13, item 10: zone_access.py. The zones are free of printed parts and cables and a 20 mm bundle leaves each of them to the rear face; every layer of its grid is non-empty
    import drive_access
    import zone_access
    strands, _skipped = drive_access.cable_strands()
    za_lines, za_fails, za = zone_access.run(parts=parts, hardware=hardware, strands=strands, field=drive_access.load_field())      # with the organic layer's field, so that "every layer" includes it
    check("zone_access: the undamaged model passes (both zones free, a 20 mm bundle leaves each, every layer non-empty)",
          not za_fails and all(za["reach"]["out"][z] and za["reach"]["seeds"][z] > 0 for z in zone_access.ZONES) and all(m.any() for m in za["layers"].values()) and "organic" in za["layers"],
          ("0 failures, both zones reach the rear face, skeleton / hardware / cables / organic layers non-empty", f"{len(za_fails)} failures: {'; '.join(za_fails[:2])}; layers {{{', '.join(f'{k} {int(m.sum())}' for k, m in za['layers'].items())}}}"))


@section("2h. zone_access.py: printed blocks in the zones")
def s_zone_access_blocks(hardware, parts, base):
    strands, _skipped = drive_access.cable_strands()
    _l, fz, _ = zone_access.run(parts=parts, hardware=hardware, strands=strands, extra_parts=[hw.bs_box(-60.0, -40.0, 160.0, 180.0, 0.0, 20.0)])
    case("zone_access: a printed block in io_zone", "ZONE_ACCESS io_zone: the printed part extra stands in it", fz, "ZONE_ACCESS io_zone", "printed part extra stands in it")
    _l, fz, _ = zone_access.run(parts=parts, hardware=hardware, strands=strands, extra_parts=[hw.bs_box(-50.0, -30.0, 90.0, 100.0, 30.0, 50.0)])
    case("zone_access: a printed block in gpu_out_zone", "ZONE_ACCESS gpu_out_zone: the printed part extra stands in it", fz, "ZONE_ACCESS gpu_out_zone", "printed part extra stands in it")


@section("2h. zone_access.py: a cable through each zone")
def s_zone_access_cables(hardware, parts, base):
    strands, _skipped = drive_access.cable_strands()
    for zone, pt0, pt1 in (("io_zone", (-60.0, 200.0, 20.0), (-10.0, 200.0, 20.0)), ("gpu_out_zone", (-70.0, 100.0, 50.0), (-10.0, 100.0, 50.0))):
        bad = dict(strands, fake=[(np.array([hw.bp(*pt0), hw.bp(*pt1)]), 2.0)])
        _l, fz, _ = zone_access.run(parts=parts, hardware=hardware, strands=bad)
        case(f"zone_access: a cable through {zone}", f"ZONE_ACCESS {zone}: the cable fake stands in it", fz, f"ZONE_ACCESS {zone}", "the cable fake stands in it")


@section("2h. zone_access.py: a wall behind the zones, a cable's chord, no cables")
def s_zone_access_wall(hardware, parts, base):
    strands, _skipped = drive_access.cable_strands()
    g0 = zone_access.Grid(parts)          # the grid run() builds for these parts: its hull is the parts' exact top and the fans' inner faces
    # a wall across the case behind both zones, only as wide and as high as the hull (between the fans' inner faces, up to the skeleton's top): the grid's margin beside the fans and above the
    # case must not count as a way round it (it did before the outside review of revision 13; the wall then had to cover the whole grid to block)
    _l, fz, _ = zone_access.run(parts=parts, hardware=hardware, strands=strands, extra_blocks=[(-g0.x_hull, g0.x_hull, 300.0, 310.0, hw.DESK_Z, g0.z_hull)])
    case("zone_access: a wall behind io_zone", "ZONE_ACCESS io_zone: a bundle of 20 mm cannot leave the zone", fz, "ZONE_ACCESS io_zone", "cannot leave the zone")
    case("zone_access: the same wall behind gpu_out_zone", "ZONE_ACCESS gpu_out_zone: a bundle of 20 mm cannot leave the zone", fz, "ZONE_ACCESS gpu_out_zone", "cannot leave the zone")
    u_edge = zone_access.ZONE_BS["io_zone"][2]
    # two route points 3.4 mm apart, each 0.6 mm outside io_zone (one below its low-u face, one beyond its v 0 face); the chord between them cuts the zone's edge 0.6 mm deep
    clip = dict(strands, fake=[(np.array([hw.bp(-1.8, u_edge - 0.6, 20.0), hw.bp(0.6, u_edge + 1.8, 20.0)]), 0.0)])
    _l, fz, _ = zone_access.run(parts=parts, hardware=hardware, strands=clip)
    case("zone_access: a cable whose chord cuts io_zone between two route points", "ZONE_ACCESS io_zone: the cable fake stands in it", fz, "ZONE_ACCESS io_zone", "the cable fake stands in it")
    _l, fz, _ = zone_access.run(parts=parts, hardware=hardware, strands={})
    case("zone_access: no cables at all is reported, not passed", "ZONE_ACCESS layer cables is empty", fz, "ZONE_ACCESS layer cables is empty")


@section("2i. checks 17 and 18")
def s_strength(hardware, parts, base):
    # 2i. checks 17 and 18 (revision 13): the hand calculations bite when a section is made thinner
    st = base["strength"]
    check("checks 17 and 18: the fan bracket and the card's post carry the plan's loads with a margin of 2 or more", st["fan bracket"]["margin"] >= f.STRENGTH_MARGIN_MIN and st["card post"]["margin"] >= f.STRENGTH_MARGIN_MIN
          and not [x for x in base["failures"] if x.startswith(("CHECK17", "CHECK18"))],
          (f"margins >= {f.STRENGTH_MARGIN_MIN:g}", f"bracket {st['fan bracket']['margin']:.2f} ({st['fan bracket']['knock']:.2f} MPa at the knock), post {st['card post']['margin']:.2f} ({st['card post']['worst']:.2f} MPa)"))
    check("check 17 numbers: the three screws share the knock by statics (sum -20 N), the old 11 x 28 leg carries about 6.5 MPa, as the plan estimated",
          abs(sum(st["fan bracket"]["forces"].values()) + f.KNOCK_N) < 1e-9
          and abs(f.bracket_strength(leg=((116.0, -34.0), (127.0, -34.0), (127.0, -6.0), (116.0, -6.0)))["rows"][0][2] - 6.5) < 0.5,
          ("forces sum to -20 N; the old leg 6.5 +- 0.5 MPa", f"sum {sum(st['fan bracket']['forces'].values()):+.3f} N; old leg {f.bracket_strength(leg=((116.0, -34.0), (127.0, -34.0), (127.0, -6.0), (116.0, -6.0)))['rows'][0][2]:.2f} MPa"))
    with patched(f, "BRACKET_T", 10.0):                 # the plate before revision 13: the spine and the bar take 20 MPa
        fl = []
        f.check_strength(fl)
    case("bracket plate 10 mm thick (as before revision 13)", "CHECK17 fan bracket: the worst section carries 20.4 MPa, margin 0.33", fl, "CHECK17 fan bracket", "worst section carries 20", "margin 0.33")
    with patched(f, "BRACKET_LEG_UN", ((116.0, -34.0), (122.0, -34.0), (122.0, -6.0), (116.0, -6.0))):      # a leg 6 mm wide in u
        fl = []
        f.check_strength(fl)
    case("bracket leg 6 mm wide in u", "CHECK17 fan bracket: the worst section carries N MPa, margin under 2", fl, "CHECK17 fan bracket", "needs 2")
    with patched(f, "GPU_POST_V_UP", (-20.0, -5.5)), patched(f, "GPU_POST_COL_W", 8.0):      # the frame as first drawn: 14.5 mm thick above the slab, a low column 8 wide
        fl = []
        f.check_strength(fl)
    thin = f.post_strength(col_w=6.0)
    check("check 18 counts torsion in the low column: a 6 mm low column fails (bending alone would pass it with margin 2.1)", thin["margin"] < f.STRENGTH_MARGIN_MIN,
          ("margin < 2", f"margin {thin['margin']:.2f}, worst {thin['worst']:.2f} MPa"))
    case("card post 14.5 mm thick with an 8 mm low column", "CHECK18 card post: the worst section carries 6.77 MPa, margin 0.99", fl, "CHECK18 card post", "needs 2")


@section("3..4. two parts overlapping, a left-hand part")
def s_overlaps(hardware, parts, base):
    # 3. two parts overlapping each other
    bf = part_named(parts, "beam_front")
    mv = moved(bf, 5, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "beam_front", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("beam_front moved 5 mm into rib_A_right", "CHECK3 part x part beam_front x rib_A_right",
         r["failures"], "CHECK3 part x part", "beam_front", "rib_A_right")

    # 4. a left-hand part: one clearance hole filled, and right-hand cutters on a left-hand part
    lp = part_named(parts, "rib_A_left")
    hl = next(h for h in lp.holes if h.kind == "M3c")
    r = f.run_checks(hardware, with_part(parts, "rib_A_left", solid=refilled(lp, hl)), MEMO)
    case("rib_A_left: one M3 clearance hole filled", "CHECK7 rib_A_left ... M3c clearance ... is not drilled",
         r["failures"], "CHECK7 rib_A_left", "M3c clearance", "is not drilled")
    rp = part_named(parts, "rib_A_right")
    r = f.run_checks(hardware, with_part(parts, "rib_A_left", holes=[h for h in rp.holes]), MEMO)
    case("rib_A_left carrying the right-hand cutters", "CHECK7 rib_A_left ... does not run through this part's material",
         r["failures"], "CHECK7 rib_A_left", "does not run through")
    check("left-hand cutters are mirrored",
          all(any(abs(a.start[0] + b.start[0]) < 1e-9 and a.start[1:] == b.start[1:] for b in rp.holes) for a in lp.holes),
          ("every rib_A_left hole is a rib_A_right hole mirrored in X", f"{len(lp.holes)} left holes checked"))


@section("5..5b. hardware tables shifted, a hand-written count")
def s_hardware_tables(hardware, parts, base):
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

    # revision 11: a column of the 420's table holds two screws (both rows), so a column shifted loses two positions (it lost one when the antler had three screws)
    old_x = hw.RAD420_HOLES_X
    hw.RAD420_HOLES_X = tuple(x + 5.0 if abs(x - 77.5) < 1e-9 else x for x in old_x)
    try:
        r = f.run_checks(hardware, parts, MEMO)
    finally:
        hw.RAD420_HOLES_X = old_x
    check("rad420 hole column x = 77.5 shifted 5 mm in hardware.py", r["mounts"]["rad420"] == base["mounts"]["rad420"] - 2,
          (f"rad420 count {base['mounts']['rad420']} -> {base['mounts']['rad420'] - 2}",
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


@section("6..6b. an intersect that raises or finds nothing")
def s_booleans(hardware, parts, base):
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


@section("7. minimum wall")
def s_walls(hardware, parts, base):
    # 7. minimum wall: two holes too close, a hole too close to the surface
    rpart = part_named(parts, "rib_A_right")
    base_hole = next(h for h in rpart.holes if h.kind == "M3c")
    near = base_hole.moved(0, hw.M3_CLEAR_D + 1.2, 0)      # centres one clearance diameter and 1.2 mm apart: wall 1.2 mm
    damaged = with_part(parts, "rib_A_right", solid=rpart.solid.cut(near.solid), holes=rpart.holes + [near])
    r = f.run_checks(hardware, damaged, MEMO)
    case("rib_A_right: second M3 clearance hole 1.2 mm from the first", "CHECK7 rib_A_right ... wall 1.2x mm < 1.6 mm",
         r["failures"], "CHECK7 rib_A_right", "wall 1.2", "< 1.6 mm")
    bh = part_named(parts, "psu_bulkhead")
    edge = f.clear_hole("M3c", (f.X_IN - hw.M3_CLEAR_D / 2 - 1.2, hw.PSU_REAR_Y - f.OVERSHOOT, 40.0), (0, 1, 0), 7.0)
    damaged = with_part(parts, "psu_bulkhead", solid=bh.solid.cut(edge.solid), holes=bh.holes + [edge])
    r = f.run_checks(hardware, damaged, MEMO)
    case("psu_bulkhead: M3 hole 1.2 mm from the plate end", "CHECK7 psu_bulkhead ... wall 1.2x mm < 1.6 mm",
         r["failures"], "CHECK7 psu_bulkhead", "wall 1.2", "< 1.6 mm")


@section("8. hardware literals in frame_v0.py")
def s_literals(hardware, parts, base):
    # 8. hardware literals in frame_v0.py
    with open(os.path.join(HERE, "frame_v0.py"), encoding="utf-8") as fh:
        src = fh.read()
    # the 420's holes moved from world Z (252.75, 377.25) to board-space n (-8.25, 116.25) in revision 5: the first two
    # are no longer hardware.py values, 116.25 is, and the scanner ignores values below 10
    old_antler = "holes = [(77.5, -8.5), (202.5, -8.5), (202.5, 116.5)]\nx = hw.x_to_v(172.5)\n"      # revision 11: the table is the 125 mm pattern (was 77.75, 202.25, 116.25)
    seeded = hardware_literals(old_antler)
    check("literal scanner finds retyped antler / arm literals", len(seeded) == 5,
          ("5 hits: 77.5, 202.5 twice, 116.5 and 172.5 (the -8.5 are below the scanner's threshold of 10)",
           ", ".join(str(v) for _, v in seeded)))
    real = hardware_literals(src)
    check("no hardware.py hole value is retyped in frame_v0.py", not real,
          ("no hits", "no hits" if not real else ", ".join(f"line {ln}: {v}" for ln, v in real)))


@section("9. check 12: plates built without rounding")
def s_rounding(hardware, parts, base):
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


@section("10. contact areas")
def s_contacts(hardware, parts, base):
    # 10. revision 8a's limit, measured on the solids: a contact keeps 97 % of its area and 4 mm of flat contact round every screw
    r = dict(base, failures=[])
    rows = f.check_contact_areas(parts, hardware, r)
    lost = [x for x in rows if x[3] < x[2] - 1e-3]
    check("every listed contact keeps at least 97 % of its unrounded area, and the flat contact round every screw", not r["failures"] and len(rows) == len(base["contacts"]) + len(base["pp_contact"]) > 30
          and all(x[3] >= f.rd.CONTACT_FLOOR * x[2] for x in rows) and len(lost) > 0,
          ("no CONTACT failure over all listed pairs, and 8a really took area from some",
           f"{len(rows)} pairs, {len(lost)} lost area, {len(r['failures'])} failures; lowest share {min(100 * x[3] / x[2] for x in rows):.2f} %"))
    # revision 11: these three cases measured the old antler's 10 mm plate on the fans' face (contact 4640 mm2; bites near the bar's inner screw, 77.75). They now
    # bite the 3 mm plate between core and fans (contact with the core and the fans, about 25000 mm2 in all) near its inner screw at X 77.5, n -8.5
    ant = part_named(parts, "antler_right")
    face_u = (f.ANTLER_U[0] - 1.0, f.ANTLER_U[1] + 1.0)
    cols = sorted(x for x in hw.RAD420_HOLES_X if x > 0)
    n_lo, n_top = hw.RAD420_HOLES_N[0], f.ANTLER_N[1]
    a0 = next(x[2] for x in rows if x[0] == "antler_right" and x[1] == "rad420")
    small = ant.solid.cut(f.bsx(f.ANTLER_PLATE_X0, f.ANTLER_PLATE_X0 + 4.0, *face_u, n_top - 4.0, n_top + 1.0))          # a 4 x 4 mm corner at the plate's far end, far from every screw: well under 3 %
    r = dict(base, failures=[])
    f.check_contact_areas(with_part(parts, "antler_right", solid=small), hardware, r)
    check("antler_right with a 4 x 4 mm corner off its contact faces is no CONTACT failure (revision 8a allows 3 %)", not first_match(r["failures"], "CONTACT antler_right x rad420"),
          (f"no failure: under 0.2 % of {a0:.0f} mm2", "; ".join(r["failures"][:2]) or "none"))
    near = ant.solid.cut(f.bsx(cols[1] - 10.5, cols[1] - 3.5, *face_u, f.ANTLER_N[0], n_lo + 1.5))          # a 7 x 6.5 mm bite at the plate's lower edge, under 0.5 % of the contact, but it reaches to within 4 mm of the screw's pilot
    r = dict(base, failures=[])
    f.check_contact_areas(with_part(parts, "antler_right", solid=near), hardware, r)
    case("antler_right with a 7 x 6.5 mm bite off its contact faces, under 0.5 % of them but within 4 mm of a screw", "CONTACT antler_right x rad420: the flat contact within 4 mm of the screw hole ... fell",
         r["failures"], "CONTACT antler_right x rad420", "flat contact within 4 mm of the screw hole")
    big = ant.solid.cut(f.bsx(cols[0] - 20.0, cols[1] + 20.0, *face_u, f.ANTLER_N[0], n_lo + 20.0))            # 60 x 26 mm off the faces, well over 3 % of the contact
    r = dict(base, failures=[])
    f.check_contact_areas(with_part(parts, "antler_right", solid=big), hardware, r)
    case("antler_right with 60 x 26 mm cut off its contact faces (over 3 %)", f"CONTACT antler_right x rad420: the contact area fell from {a0:.3f} to ..., under 97 % of the unrounded area (floor 97 %)",
         r["failures"], "CONTACT antler_right x rad420", "the contact area fell", "floor 97 %")
    ring = part_named(parts, "visor_arm_right")
    sc = next(h for h in ring.holes if h.kind == "6-32c")               # the arm's radiator screw along n, 4 mm of flat contact round it on the 360's face
    bite = hw.bs_cyl(sc.screw_r() + f.rd.SCREW_FLAT - 1.0, hw.x_to_v(hw.RAD360_HOLES_X[-1]), hw.RAD360_HOLES_U[1], hw.RAD360_INNER_N - 3.0, hw.RAD360_INNER_N + 1.0)
    r = dict(base, failures=[])
    f.check_contact_areas(with_part(parts, "visor_arm_right", solid=ring.solid.cut(bite)), hardware, r)
    case("visor_arm_right with the flat contact round a radiator screw eaten to within 3 mm of the hole (area loss under 3 %)", "CONTACT visor_arm_right x rad360: the flat contact within 4 mm of the screw hole fell",
         r["failures"], "CONTACT visor_arm_right x rad360", "flat contact within 4 mm of the screw hole")


@section("10b. the rounding's allowance")
def s_round_plate(hardware, parts, base):
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


@section("10c. the front sill, the module and the light line")
def s_sill(hardware, parts, base):
    # 10c. revision 9: the front sill, the module and the light line
    sill = part_named(parts, "front_sill")
    check("front_sill is one valid solid across X -140..140, 290 mm or less, and every part has a material", len(sill.solid.Solids()) == 1 and sill.solid.isValid()
          and abs(f.bbox_of(sill.solid)[0] + 140) < 1e-6 and abs(f.bbox_of(sill.solid)[1] - 140) < 1e-6
          and all(p.material in f.MATERIALS for p in parts),
          ("1 solid, X -140..140, materials in ABS/PA6", f"{len(sill.solid.Solids())} solid, X {f.bbox_of(sill.solid)[0]:.1f}..{f.bbox_of(sill.solid)[1]:.1f}"))
    tie_names = [f.tie_name(tp) for tp in f.TIE_POINTS]
    check("only the two hose guides are PA6, every other part (the cable tie bridges too) is ABS", sorted(p.name for p in parts if p.material == "PA6") == sorted(["hose_guide_cpu", "hose_guide_gpu"])
          and all(p.material == "ABS" for p in parts if p.name not in f.GUIDE_PARTS) and all(n in [p.name for p in parts] for n in tie_names),
          ("PA6: hose_guide_cpu and hose_guide_gpu; the other parts ABS", ", ".join(f"{p.name}={p.material}" for p in parts if p.material != "ABS")))
    check("front_io and light_strip are hardware: front_io real, light_strip a keep-out; both in front of Y = 0 nowhere", "front_io" in hardware and "light_strip" in hardware
          and "light_strip" in hw.KEEP_OUT and "front_io" not in hw.KEEP_OUT and base["envelope"]["front"][2] >= hw.ENVELOPE_Y0,
          ("both in build_hardware, min Y >= 0", f"min Y {base['envelope']['front'][2]:.1f} ({base['envelope']['front'][3]})"))
    # revision 14a: the module sits in the carrier, the carrier in the sill's pocket: carrier to module CARRIER_PLAY on the ends and CARRIER_TOP_PLAY on top, sill to carrier SILL_POCKET_PLAY all round, the
    # sill's rear wall 2.5 mm behind the module (no back wall on the carrier); the channel clears light_strip by SILL_CHANNEL_PLAY as before
    carrier = part_named(parts, "front_io_carrier")
    d_io, d_ls = f.solid_distance(sill.solid, hardware["front_io"]), f.solid_distance(sill.solid, hardware["light_strip"])
    d_sc, d_cm = f.solid_distance(sill.solid, carrier.solid), f.solid_distance(carrier.solid, hardware["front_io"])
    rear_room = f.CARRIER_Y1 + f.SILL_POCKET_PLAY - hw.FRONT_IO_W[3]
    check("the pocket clears the carrier, the carrier clears the module and the channel clears light_strip, by their clearances; the sill's rear wall stands 2.5 mm behind the module",
          abs(d_sc - f.SILL_POCKET_PLAY) < 0.05 and abs(d_cm - min(f.CARRIER_PLAY, f.CARRIER_TOP_PLAY)) < 0.05 and abs(d_io - rear_room) < 0.05 and abs(rear_room - 2.5) < 1e-9 and abs(d_ls - f.SILL_CHANNEL_PLAY) < 0.05
          and f.inter_vol(sill.solid, hardware["front_io"]) < f.VOL_EPS and f.inter_vol(sill.solid, hardware["light_strip"]) < f.VOL_EPS and f.inter_vol(carrier.solid, hardware["front_io"]) < f.VOL_EPS,
          (f"sill-carrier {f.SILL_POCKET_PLAY:g}, carrier-module {min(f.CARRIER_PLAY, f.CARRIER_TOP_PLAY):g}, sill-module 2.5, channel-strip {f.SILL_CHANNEL_PLAY:g}, no overlap",
           f"{d_sc:.2f}, {d_cm:.2f}, {d_io:.2f}, {d_ls:.2f} mm"))
    check("the module stands on beam_front (a listed zero-gap contact) and the sill stands on beam_front (part x part contact)",
          ("beam_front", "front_io") in base["contacts"] and ("beam_front", "front_io") in f.INTENDED_CONTACTS and
          any(set(x) == {"beam_front", "front_sill"} for x in base["pp_contact"]),
          ("beam_front x front_io and beam_front x front_sill touch", f"{[c for c in base['contacts'] if 'front_io' in c]}, {[c for c in base['pp_contact'] if 'front_sill' in c]}"))
    check("front_io has one holder with two screws, derived from the solids", base["mounts"]["front_io"] == 2 and f.EXPECTED_MOUNTS["front_io"] == 2
          and sum(x["count"] for x in f.FASTENERS if x["item"] == "front_io") == 2,
          ("front_io 2, fastener list 2", f"derived {base['mounts']['front_io']}, listed {sum(x['count'] for x in f.FASTENERS if x['item'] == 'front_io')}"))
    sill_pilots = [h for h in sill.holes if h.pilot and h.item == "front_sill -> beam_front"]
    check("front_sill is bolted to beam_front with at least 2 x M3", len(sill_pilots) >= 2 and sum(1 for h in part_named(parts, "beam_front").holes if h.kind == "M3c") >= 2,
          ("pilots in the sill and clearance holes in the beam, 4 each", f"{len(sill_pilots)} pilots, {sum(1 for h in part_named(parts, 'beam_front').holes if h.kind == 'M3c')} clearance holes"))
    mv = moved(sill, 5, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "front_sill", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("front_sill moved 5 mm along X, its end wall into the carrier", "CHECK3 part x part front_sill x front_io_carrier", r["failures"], "CHECK3 part x part front_sill x front_io_carrier")
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
    hs = sill_pilots[0]
    r = f.run_checks(hardware, with_part(parts, "front_sill", solid=refilled(sill, hs)), MEMO)
    case("front_sill: one M3 bolt pilot filled back in", "CHECK7 front_sill ... M3 pilot ... is not drilled", r["failures"], "CHECK7 front_sill", "M3 pilot", "is not drilled")
    r = f.run_checks(hardware, with_part(parts, "front_sill", solid=sill.blank), MEMO)
    case("front_sill undrilled: the carrier's screws have no insert", "CHECK5 front_io_carrier: 0 positions have a hole", r["failures"], "CHECK5 front_io_carrier: 0 positions")
    r = f.run_checks(hardware, with_part(parts, "front_io_carrier", solid=carrier.blank), MEMO)
    case("front_io_carrier undrilled: the module has no screw hole", "CHECK5 front_io: 0 positions have a hole", r["failures"], "CHECK5 front_io: 0 positions")
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


@section("10c2. the front I/O module's carrier")
def s_carrier(hardware, parts, base):
    sill, carrier = part_named(parts, "front_sill"), part_named(parts, "front_io_carrier")
    # 10c2. revision 14a, item 2: the front I/O module's carrier. It holds the module (two pilots for the module's own screws, an inverted U with no back wall), hangs from the sill's end blocks on four
    # M3 into inserts in the sill, and its outside, not the module, sets the sill's pocket: a module that grows changes the carrier until its walls are used up, never the sill
    car_pilots = [h for h in carrier.holes if h.pilot and h.item == "front_io"]
    car_clear = [h for h in carrier.holes if h.kind == "M3c"]
    sill_car = [h for h in sill.holes if h.pilot and h.item == "front_io_carrier"]
    check("front_io_carrier: 2 pilots for the module's screws, 4 clearance holes and 4 pilots in the sill for its own, all derived from the solids, listed in the bill",
          len(car_pilots) == 2 and len(car_clear) == 4 and len(sill_car) == 4 and base["mounts"]["front_io_carrier"] == 4 == f.EXPECTED_MOUNTS["front_io_carrier"]
          and sum(x["count"] for x in f.FASTENERS if x["item"] == "front_io_carrier") == 4 and base["mounts"]["front_io"] == 2,
          ("2 module pilots, 4 clearance holes, 4 sill pilots, 4 derived, 4 listed",
           f"{len(car_pilots)}, {len(car_clear)}, {len(sill_car)}; derived {base['mounts']['front_io_carrier']}, listed {sum(x['count'] for x in f.FASTENERS if x['item'] == 'front_io_carrier')}"))
    cb_ = f.bbox_of(carrier.solid)
    check("front_io_carrier: ABS, one valid solid inside its outside numbers, no back wall (the module's rear face is open), touches neither the sill nor the beam nor the module (hangs on its screws)",
          carrier.material == "ABS" and len(carrier.solid.Solids()) == 1 and carrier.solid.isValid() and abs(cb_[0] - f.CARRIER_X[0]) < 1e-6 and abs(cb_[1] - f.CARRIER_X[1]) < 1e-6 and abs(cb_[3] - f.CARRIER_Y1) < 1e-6
          and not carrier.solid.isInside(cq.Vector(0.0, f.CARRIER_Y1 - 1.0, 30.0)) and not [c for c in base["pp_contact"] if "front_io_carrier" in c] and not [c for c in base["contacts"] if "front_io_carrier" in c],
          ("X -82..107, Y 0..44.2, empty at the rear middle, no contact", f"X {cb_[0]:g}..{cb_[1]:g}, Y {cb_[2]:g}..{cb_[3]:g}; contacts {[c for c in base['pp_contact'] + base['contacts'] if 'front_io_carrier' in c]}"))
    cw = base["carrier"]
    check("check 20 on the undamaged model: end blocks 11.6 mm, top plate 2.7 mm; the module may grow 3.3 mm per end, 0.2 up, 2.5 back before the carrier or the sill has to change",
          abs(cw["end"][0] - 11.6) < 0.02 and abs(cw["end"][1] - 11.6) < 0.02 and abs(cw["top"] - 2.7) < 0.02 and abs(cw["rear"] - 2.5) < 1e-6
          and abs(cw["grow"]["left"] - 3.3) < 0.02 and abs(cw["grow"]["right"] - 3.3) < 0.02 and abs(cw["grow"]["top"] - 0.2) < 0.02 and not [x for x in base["failures"] if x.startswith("CHECK20")],
          ("11.6, 11.6, 2.7, 2.5; growth 3.3 / 3.3 / 0.2 / 2.5", f"{[round(x, 2) for x in cw['end']]}, {cw['top']:.2f}, {cw['rear']:.2f}; growth {{{', '.join(f'{k}: {v:.2f}' for k, v in cw['grow'].items())}}}"))
    fl, _ = grown(hardware, parts, dx1=5.0)
    case("the module 5 mm longer on the right (carrier rebuilt, its end block 6.6 mm): the walls are used up", "CHECK20 the right end block of front_io_carrier is 6.60 mm thick at the module's screw, needs 8.3",
         fl, "CHECK20 the right end block of front_io_carrier", "needs 8.3")


def grown(hardware, parts, dx0=0.0, dx1=0.0, dz1=0.0):
    """run_checks with the module's box grown in the given directions (the module's two screws move with its end faces), the carrier rebuilt for it (it follows hw.FRONT_IO_W) and the sill left as it is
    (its pocket follows the carrier's outside): returns (failures, the pocket's box as the sill_geometry gives it for that module, the carrier's walls)"""
    old_w, old_s = hw.FRONT_IO_W, hw.FRONT_IO_SCREWS
    new_w = (old_w[0] - dx0, old_w[1] + dx1, old_w[2], old_w[3], old_w[4], old_w[5] + dz1)
    hw.FRONT_IO_W = new_w
    hw.FRONT_IO_SCREWS = (((old_s[0][0][0] - dx0,) + old_s[0][0][1:], old_s[0][1]), ((old_s[1][0][0] + dx1,) + old_s[1][0][1:], old_s[1][1]))
    try:
        solid_, holes_, blank_ = f.build_front_io_carrier()
        pocket_ = f.bbox_of(f.sill_geometry()["cuts"]["pocket"])
        r_ = f.run_checks(dict(hardware, front_io=hw.wbox(*new_w)), with_part(parts, "front_io_carrier", solid=solid_, blank=blank_, holes=holes_), MEMO)
    finally:
        hw.FRONT_IO_W, hw.FRONT_IO_SCREWS = old_w, old_s
    return r_["failures"], pocket_


# revision 14a review: the module grown to the whole of its allowance, in each direction and all at once, with the whole frame rebuilt for it (not only the carrier): the sill comes out the same
# (volume, box, every hole), every check passes, the cables pass the sill; and one step of 0.1 mm beyond each allowance fails check 20. hardware.py itself, run again with only FRONT_IO_W changed,
# changes nothing else (the light strip, which the sill's channel is drawn round, used to follow the module's highest point). One section per allowance: each rebuilds the whole frame.
def sill_signature(p):
    """Volume, exact box (f.exact_box: never a triangulation's) and every hole of a part."""
    return (round(p.solid.Volume(), 6), tuple(round(x, 9) for x in f.exact_box(p.solid)),
            sorted((h.kind, tuple(round(c, 9) for c in h.start), tuple(round(c, 9) for c in h.d), round(h.r, 9), round(h.length, 9)) for h in p.holes))


def grown_full(hardware, parts, dx0=0.0, dx1=0.0, dz1=0.0, dy1=0.0, route=False):
    """The module's box grown (its two screws move with its end faces), hardware.py's FRONT_IO_W and FRONT_IO_SCREWS and the hardware solid changed, the whole frame rebuilt with build_frame (the same
    hardware set, so the same rounding context), every check run on the undamaged parts with the rebuilt sill and carrier in place (every other rebuilt part is compared with the undamaged one, and
    must be the same), and with `route` the cables routed: (the rebuilt sill's signature, failures, cable failures or None, names of the other parts that changed). The module state the build resets
    (fasteners, bolt checks, rounding log) is put back afterwards. The cables see the module only through its rear face (their start, cables.usb_start) and the parts: the X and Z growths leave the
    start where it is and the carrier's outside as it was, so only the cases that move the rear face are routed (routing takes about 90 s)."""
    from OCP.BRepTools import BRepTools

    old_w, old_s, old_io = hw.FRONT_IO_W, hw.FRONT_IO_SCREWS, hardware["front_io"]
    new_w = (old_w[0] - dx0, old_w[1] + dx1, old_w[2], old_w[3] + dy1, old_w[4], old_w[5] + dz1)
    saved = (list(f.FASTENERS), list(f.BOLT_CHECKS), list(f.ROUND_LOG), {k_: list(v_) for k_, v_ in f.KEEP_SHARP.items()}, dict(f._A_LAYER))
    hw.FRONT_IO_W = new_w
    hw.FRONT_IO_SCREWS = (((old_s[0][0][0] - dx0,) + old_s[0][0][1:], old_s[0][1]), ((old_s[1][0][0] + dx1,) + old_s[1][0][1:], old_s[1][1]))
    hardware["front_io"] = hw.wbox(*new_w)
    try:
        parts_g, _ = f.build_frame(hardware=hardware)
        by_g = {p_.name: p_ for p_ in parts_g}
        others = [p_.name for p_ in parts if p_.name not in ("front_sill", "front_io_carrier")
                  and (abs(by_g[p_.name].solid.Volume() - p_.solid.Volume()) > 1e-6 or any(abs(a_ - b_) > 1e-9 for a_, b_ in zip(f.exact_box(by_g[p_.name].solid), f.exact_box(p_.solid))))]
        for n_ in ("front_sill", "front_io_carrier"):      # the rebuilt parts share faces with the undamaged ones, and their meshes (see f.exact_box): checked as freshly built
            BRepTools.Clean_s(by_g[n_].solid.wrapped)
        mixed = [by_g[p_.name] if p_.name in ("front_sill", "front_io_carrier") else p_ for p_ in parts]
        r_ = f.run_checks(hardware, mixed, MEMO)
        cf_ = None
        if route:
            routes_g = cables.build_routes()
            cf_ = cables.failures(routes_g, cables.evaluate(routes_g, mixed, hardware))
    finally:
        hw.FRONT_IO_W, hw.FRONT_IO_SCREWS = old_w, old_s
        hardware["front_io"] = old_io
        f.FASTENERS[:], f.BOLT_CHECKS[:], f.ROUND_LOG[:] = saved[0], saved[1], saved[2]
        f.KEEP_SHARP.clear()
        f.KEEP_SHARP.update(saved[3])
        f._A_LAYER.clear()
        f._A_LAYER.update(saved[4])
    return sill_signature(by_g["front_sill"]), r_["failures"], cf_, others


ALLOWANCE = (("3.3 mm longer on the left", dict(dx0=3.3)), ("3.3 mm longer on the right", dict(dx1=3.3)), ("0.2 mm taller", dict(dz1=0.2)), ("2.5 mm deeper", dict(dy1=2.5, route=True)),
             ("all of these at once", dict(dx0=3.3, dx1=3.3, dz1=0.2, dy1=2.5, route=True)))


def s_allowance(hardware, parts, base, label_, kw_):
    base_sill_sig = sill_signature(part_named(parts, "front_sill"))
    sig_, fl, cf_, others_ = grown_full(hardware, parts, **kw_)
    check(f"the module {label_} (its whole allowance), the frame rebuilt: the sill is the same (volume, box, holes) and so is every part but the carrier, every check passes"
          + (", every cable passes" if kw_.get("route") else ""),
          sig_ == base_sill_sig and not others_ and not fl and not cf_,
          ("same sill, no other part changed, 0 failures, 0 cable failures", f"sill same {sig_ == base_sill_sig} (volume {sig_[0]:.3f} against {base_sill_sig[0]:.3f}); changed {others_}; "
                                                                            f"{len(fl)} failures {fl[:2]}; cable failures {None if cf_ is None else [t_ for _c, t_ in cf_[:2]]}"))


for _label, _kw in ALLOWANCE:
    section(f"10c2. the module {_label}, the frame rebuilt")(functools.partial(s_allowance, label_=_label, kw_=_kw))


@section("10c2. the module past its allowance, the carrier's holes")
def s_past_allowance(hardware, parts, base):
    sill, carrier = part_named(parts, "front_sill"), part_named(parts, "front_io_carrier")
    car_pilots = [h for h in carrier.holes if h.pilot and h.item == "front_io"]
    car_clear = [h for h in carrier.holes if h.kind == "M3c"]
    sill_car = [h for h in sill.holes if h.pilot and h.item == "front_io_carrier"]
    for label_, kw_, needle_ in (("3.4 mm longer on the left", dict(dx0=3.4), "CHECK20 the left end block of front_io_carrier"),
                                 ("3.4 mm longer on the right", dict(dx1=3.4), "CHECK20 the right end block of front_io_carrier"),
                                 ("0.3 mm taller", dict(dz1=0.3), "CHECK20 the top plate of front_io_carrier"),
                                 ("2.6 mm deeper", dict(dy1=2.6), "CHECK20 the module's rear")):
        if "dy1" in kw_:
            deeper_ = dict(hardware, front_io=hw.wbox(*(hw.FRONT_IO_W[:3] + (hw.FRONT_IO_W[3] + kw_["dy1"],) + hw.FRONT_IO_W[4:])))
            fl = []
            f.check_carrier(parts, deeper_, fl)
        else:
            fl, _ = grown(hardware, parts, **kw_)
        case(f"the module {label_}: 0.1 mm past its allowance", f"{needle_} ...", fl, needle_)
    import importlib.util
    import re as re_
    src_ = open(hw.__file__, encoding="utf-8").read()
    w_all = (hw.FRONT_IO_W[0] - 3.3, hw.FRONT_IO_W[1] + 3.3, hw.FRONT_IO_W[2], hw.FRONT_IO_W[3] + 2.5, hw.FRONT_IO_W[4], hw.FRONT_IO_W[5] + 0.2)
    src_g, n_sub = re_.subn(r"^FRONT_IO_W = .*$", f"FRONT_IO_W = {w_all!r}", src_, count=1, flags=re_.M)
    spec_ = importlib.util.spec_from_loader("hardware_grown", loader=None)
    hw_g = importlib.util.module_from_spec(spec_)
    exec(compile(src_g, hw.__file__, "exec"), hw_g.__dict__)
    data_ = lambda v_: " at 0x" not in repr(v_)        # noqa: E731
    changed = sorted(k_ for k_, v_ in vars(hw).items() if not k_.startswith("_") and data_(v_) and k_ in vars(hw_g) and repr(vars(hw_g)[k_]) != repr(v_))
    check("hardware.py run again with only FRONT_IO_W grown by the whole allowance: nothing else in it changes (LIGHT_STRIP_BS, which the sill's light channel follows, included)",
          n_sub == 1 and changed == ["FRONT_IO_W"] and hw_g.LIGHT_STRIP_BS == hw.LIGHT_STRIP_BS,
          ("only FRONT_IO_W differs", f"{n_sub} substitution(s); differing names {changed}"))
    fl, _ = grown(hardware, parts, dz1=1.0)
    case("the module 1 mm taller (carrier rebuilt: its top plate 1.7 mm)", "CHECK20 the top plate of front_io_carrier is 1.70 mm thick over the module, needs 2.5", fl, "CHECK20 the top plate of front_io_carrier", "needs 2.5")
    deep = dict(hardware, front_io=hw.wbox(hw.FRONT_IO_W[0], hw.FRONT_IO_W[1], hw.FRONT_IO_W[2], hw.FRONT_IO_W[3] + 3.0, hw.FRONT_IO_W[4], hw.FRONT_IO_W[5]))
    r = f.run_checks(deep, parts, MEMO)
    case("the module 3 mm deeper than its 2.5 mm of room: it reaches the sill's rear wall", "CHECK2 part x hardware front_sill x front_io", r["failures"], "CHECK2 part x hardware front_sill x front_io")
    case("  same damage, check 20 reports the room", "CHECK20 the module's rear Y 45 is behind the sill's pocket (Y 44.5)", r["failures"], "CHECK20 the module's rear", "behind the sill's pocket")
    mv = moved(carrier, 0, 0, 0.5)
    r = f.run_checks(hardware, with_part(parts, "front_io_carrier", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("front_io_carrier raised 0.5 mm: its top plate enters the sill's roof", "CHECK3 part x part front_sill x front_io_carrier", r["failures"], "CHECK3 part x part front_sill x front_io_carrier")
    mv = moved(carrier, 0, 3.0, 0)
    r = f.run_checks(hardware, with_part(parts, "front_io_carrier", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("front_io_carrier moved 3 mm back off its seat: its screws no longer meet the sill's inserts", "CHECK5 front_io_carrier", r["failures"], "CHECK5 front_io_carrier")
    hs_c = sill_car[0]
    r = f.run_checks(hardware, with_part(parts, "front_sill", solid=refilled(sill, hs_c)), MEMO)
    case("front_sill: one of the carrier's pilots filled back in", "CHECK7 front_sill ... M3 pilot ... is not drilled", r["failures"], "CHECK7 front_sill", "M3 pilot", "is not drilled")
    case("  same damage, the carrier's screw count derived from the solids", "CHECK5 front_io_carrier: 3 positions have a hole", r["failures"], "CHECK5 front_io_carrier: 3 positions")
    hc_ = car_pilots[0]
    r = f.run_checks(hardware, with_part(parts, "front_io_carrier", solid=refilled(carrier, hc_)), MEMO)
    case("front_io_carrier: one of the module's pilots filled back in", "CHECK7 front_io_carrier ... M3 pilot ... is not drilled", r["failures"], "CHECK7 front_io_carrier", "M3 pilot", "is not drilled")
    case("  same damage, the module's screw count derived from the solids", "CHECK5 front_io: 1 positions have a hole", r["failures"], "CHECK5 front_io: 1 positions")
    r = f.run_checks(hardware, with_part(parts, "front_io_carrier", solid=refilled(carrier, car_clear[0])), MEMO)
    case("front_io_carrier: one of its own clearance holes filled back in", "CHECK7 front_io_carrier ... M3c ... is not drilled", r["failures"], "CHECK7 front_io_carrier", "M3c", "is not drilled")
    case("  same damage, the carrier's screw count and the stack that nothing clamps", "CHECK5 front_io_carrier: 3 positions have a hole", r["failures"], "CHECK5 front_io_carrier: 3 positions")
    check("the bill: the carrier's four screws are M3 x 10 (4.3 mm under the washer: 4 mm of floor and 0.3 of play), measured on the solids by check 15",
          f.screw_fit(f.CARRIER_STACK)[0] == 10 and abs(f.CARRIER_STACK - 4.3) < 1e-9 and sum(1 for r_ in base["screws"]["rows"] if r_["item"] == "front_io_carrier" and r_["length"] == 10 and abs(r_["stack"] - 4.3) < 1e-9) == 4,
          ("4 rows, M3 x 10, stack 4.3", f"{[(r_['part'], r_['length'], round(r_['stack'], 2)) for r_ in base['screws']['rows'] if r_['item'] == 'front_io_carrier']}"))


@section("10c3. gpu_rest")
def s_gpu_rest(hardware, parts, base):
    # 10c3. revision 14a, item 1: gpu_rest. The card's right-hand rest is a part of its own: a capsule on the diagonal's upper face (the rib keeps a flat seat), 2 x M3 along n from the diagonal's underside
    # through plain holes (no slots) into inserts in the part; the contact face with the card where the finger's was, u = hw.GPU_BS[2]
    rest = part_named(parts, "gpu_rest")
    rib_r = part_named(parts, "rib_A_right")
    rest_pilots = [h for h in rest.holes if h.pilot and h.item == "gpu_rest"]
    rest_clear = [h for h in rib_r.holes if h.kind == "M3c" and abs(abs(sum(a * b for a, b in zip(h.d, hw.N_DIR))) - 1.0) < 1e-6]
    rb_ = f.bbox_of(rest.solid)
    on_face = [fc for fc in rest.solid.Faces() if fc.geomType() == "PLANE" and abs(abs(float(np.dot(fc.normalAt().toTuple(), hw.U_DIR))) - 1.0) < 1e-6 and abs(hw.bs_of(*fc.Center().toTuple())[1] - hw.GPU_BS[2]) < 1e-6]
    check("gpu_rest: ABS, one valid solid, 2 pilots in the part, 2 plain clearance holes in rib_A_right (every hole round, no slot), contact face u = GPU_BS[2], listed in the bill",
          rest.material == "ABS" and len(rest.solid.Solids()) == 1 and rest.solid.isValid() and len(rest_pilots) == 2 and len(rest_clear) == 2 and all(h.kind in ("M3", "M3r") for h in rest.holes)
          and on_face and base["mounts"]["gpu_rest_screw"] == 2 == f.EXPECTED_MOUNTS["gpu_rest_screw"] and base["mounts"]["gpu_rest"] == 1
          and sum(x["count"] for x in f.FASTENERS if x["item"] == "gpu_rest") == 2 and sum(x["count"] for x in f.FASTENERS if x["item"] == "gpu") == 2,
          ("2 + 2 holes, a contact face at u 75.6, 2 screws derived and listed, the 'gpu' row is gpu_post's alone",
           f"{len(rest_pilots)} pilots, {len(rest_clear)} clearance holes, {len(on_face)} faces at u = GPU_BS[2]; derived {base['mounts']['gpu_rest_screw']}"))
    check("gpu_rest's contact face and place follow hardware.py and the old finger: u = GPU_BS[2] (card 75.6), along n the capsule's axis -10..104 kept, standing on the diagonal's upper face n -6, as thick as the rib",
          abs(f.REST_U + f.REST_W / 2 - hw.GPU_BS[2]) < 1e-9 and f.REST_N_AXIS == (-10.0, 104.0) and abs(f.REST_SEAT_N - -6.0) < 1e-9 and f.REST_X == (f.X_IN, f.X_OUT)
          and abs(board_box(rest.solid).zmin - f.REST_SEAT_N) < 1e-6 and ("gpu_rest", "gpu") in base["contacts"] and ("gpu_rest", "gpu") in f.INTENDED_CONTACTS
          and any(set(x) == {"gpu_rest", "rib_A_right"} for x in base["pp_contact"]) and ("rib_A_right", "gpu") not in base["contacts"],
          ("contact with the card and the rib, not the rib's own finger", f"hardware contacts {[c for c in base['contacts'] if 'gpu' in c[0] or c[1] == 'gpu']}"))
    check("rib_A_right lost the finger and kept what else it carries: same outline as rib_A_left; the hose guide's pilot, the rail's tie pilots, its organic pads and 2 clearance holes for the rest",
          abs(f.bbox_of(rib_r.solid)[2] - f.bbox_of(part_named(parts, "rib_A_left").solid)[2]) < 1e-6 and abs(f.bbox_of(rib_r.solid)[3] - f.bbox_of(part_named(parts, "rib_A_left").solid)[3]) < 1e-6
          and abs(f.bbox_of(rib_r.solid)[5] - f.bbox_of(part_named(parts, "rib_A_left").solid)[5]) < 1e-6
          and any(h.item == "hose_guide_gpu" for h in rib_r.holes) and any(h.item == "tie bridge" for h in rib_r.holes) and any(h.item == "organic pad" for h in rib_r.holes),
          ("Y and Z extent as the left rib's, guide / tie / pad pilots present", f"Y {f.bbox_of(rib_r.solid)[2]:.1f}..{f.bbox_of(rib_r.solid)[3]:.1f}, Z top {f.bbox_of(rib_r.solid)[5]:.1f}"))
    r = f.run_checks(hardware, with_part(parts, "gpu_rest", solid=refilled(rest, rest_pilots[0])), MEMO)
    case("gpu_rest: one insert pilot filled back in", "CHECK7 gpu_rest ... M3 pilot ... is not drilled", r["failures"], "CHECK7 gpu_rest", "M3 pilot", "is not drilled")
    case("  same damage, the rest's screw count derived from the solids", "CHECK5 gpu_rest_screw: 1 positions have a hole", r["failures"], "CHECK5 gpu_rest_screw: 1 positions")
    r = f.run_checks(hardware, with_part(parts, "rib_A_right", solid=refilled(rib_r, rest_clear[0])), MEMO)
    case("rib_A_right: one of gpu_rest's clearance holes filled back in", "CHECK7 rib_A_right ... M3c ... is not drilled", r["failures"], "CHECK7 rib_A_right", "M3c", "is not drilled")
    case("  same damage, the rest's screw count derived from the solids", "CHECK5 gpu_rest_screw: 1 positions have a hole", r["failures"], "CHECK5 gpu_rest_screw: 1 positions")
    mv = moved(rest, 3.0, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "gpu_rest", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("gpu_rest moved 3 mm along X off its seat: its screws no longer meet the rib's holes", "CHECK5 gpu_rest_screw", r["failures"], "CHECK5 gpu_rest_screw")
    up2 = cq.Vector(*(2.0 * np.array(hw.U_DIR)))
    r = f.run_checks(hardware, with_part(parts, "gpu_rest", solid=rest.solid.translate(up2), blank=rest.blank.translate(up2)), MEMO)
    case("gpu_rest moved 2 mm along +u into the card", "CHECK2 part x hardware gpu_rest x gpu", r["failures"], "CHECK2 part x hardware gpu_rest x gpu")
    down3 = cq.Vector(*(-3.0 * np.array(hw.U_DIR)))
    r = f.run_checks(hardware, with_part(parts, "gpu_rest", solid=rest.solid.translate(down3), blank=rest.blank.translate(down3)), MEMO)
    case("gpu_rest moved 3 mm along -u: its contact face leaves the card", "CHECK5 gpu_rest: 0 positions have a hole in the solids, the plan needs 1", r["failures"], "CHECK5 gpu_rest: 0 positions")
    bs_ = f.rest_strength()
    check("check 19 on the undamaged model: the card's whole weight and the 20 N knock at the tip, margin 2 or more; the old 16 mm finger carried the knock with a margin of 1.93",
          bs_["margin"] >= f.STRENGTH_MARGIN_MIN and not [x for x in base["failures"] if x.startswith("CHECK19")] and base["strength"]["gpu_rest"]["margin"] == bs_["margin"]
          and abs(f.rest_strength(width=16.0)["margin"] - 1.93) < 0.02 and bs_["tension"] > 0,
          (f"margin >= {f.STRENGTH_MARGIN_MIN:g}; 16 mm finger 1.93 +- 0.02", f"margin {bs_['margin']:.2f} ({bs_['worst']:.2f} MPa), 16 mm {f.rest_strength(width=16.0)['margin']:.2f}, screw tension up to {bs_['tension']:.0f} N"))
    with patched(f, "REST_W", 10.0):                       # a finger half as wide (the contact face stays at u = GPU_BS[2])
        fl = []
        f.check_strength(fl)
    case("gpu_rest 10 mm wide (a thinned finger)", "CHECK19 gpu_rest: the worst section carries N MPa, margin under 2", fl, "CHECK19 gpu_rest", "needs 2")
    thin_rest = f.rest_strength(depth=10.0)
    check("  the same for a finger only 10 mm thick in X: the knock bends it about u and the margin falls under 2", thin_rest["margin"] < f.STRENGTH_MARGIN_MIN,
          ("margin < 2", f"margin {thin_rest['margin']:.2f}, worst {thin_rest['worst']:.2f} MPa"))

    # revision 14a review: the rest's counterbores follow the rule of every M3 counterbore (head 3 + washer 0.5 + 0.2 = 3.7 deep; they were 3.0 and the head stood 0.5 mm proud) and are recorded as holes (M3cb), so
    # check 16 measures each on the solid: its depth from the face round it and the material under its floor
    m3cb = base["m3_counterbores"]
    rest_cb = [r_ for r_ in m3cb if r_[0] == "rib_A_right"]
    car_cb = [r_ for r_ in m3cb if r_[0] == "front_io_carrier"]
    rest_rows = [r_ for r_ in base["screws"]["rows"] if r_["item"] == "gpu_rest"]
    check("check 16 on the M3 counterbores: 2 under gpu_rest's screws 3.7 mm deep with 24.3 mm of the diagonal under them, 4 in the carrier 7.6 mm deep with 4.0 mm under them; the rest's screws M3 x 30 entering 5.2 mm",
          len(m3cb) == 6 and len(rest_cb) == 2 and len(car_cb) == 4 and all(abs(r_[3] - 3.7) < 0.02 and abs(r_[4] - 24.3) < 0.02 for r_ in rest_cb)
          and all(abs(r_[3] - 7.6) < 0.02 and abs(r_[4] - 4.0) < 0.02 for r_ in car_cb) and abs(f.M3_CB_DEPTH - 3.7) < 1e-9 and f.REST_CB_DEPTH == f.M3_CB_DEPTH == f.CARRIER_CB_BELOW
          and len(rest_rows) == 2 and all(r_["length"] == 30 and abs(r_["stack"] - 24.3) < 1e-9 and abs(r_["entry"] - 5.2) < 1e-9 for r_ in rest_rows),
          ("rest 2 x (3.70, 24.30), carrier 4 x (7.60, 4.00), M3 x 30 entry 5.2",
           f"rest {[(round(r_[3], 2), round(r_[4], 2)) for r_ in rest_cb]}, carrier {[(round(r_[3], 2), round(r_[4], 2)) for r_ in car_cb]}, screws {[(r_['length'], round(r_['stack'], 2), round(r_['entry'], 2)) for r_ in rest_rows]}"))
    cbr = next(h for h in rib_r.holes if h.kind == "M3cb")
    floor_ = np.array(cbr.point(cbr.length))
    ring_ = f.cyl(tuple(floor_ - 1.0 * np.array(cbr.d)), cbr.d, 2 * cbr.r, 1.0).cut(f.cyl(tuple(floor_ - 2.0 * np.array(cbr.d)), cbr.d, hw.M3_CLEAR_D, 3.0))
    fl = []
    f.check_m3_counterbores(with_part(parts, "rib_A_right", solid=rib_r.solid.fuse(ring_).clean()), fl)
    case("rib_A_right: one of gpu_rest's counterbores 1 mm too shallow (its floor filled 1 mm, the clearance bore left open)", "CHECK16 rib_A_right: M3cb ... the counterbore is 2.70 mm deep, the head and the washer need 3.5 and 0.2 to spare (3.7)",
         fl, "CHECK16 rib_A_right", "is 2.70 mm deep")
    with patched(f, "REST_CB_DEPTH", f.REST_CB_DEPTH - 1.0), patched(f, "REST_STACK", f.REST_STACK + 1.0):
        sh_solid, sh_holes, sh_blank = f.build_rib_a(True)
    fl = []
    f.check_m3_counterbores(with_part(parts, "rib_A_right", solid=sh_solid, blank=sh_blank, holes=sh_holes), fl)
    case("rib_A_right built with REST_CB_DEPTH 1 mm short (2.7: the head and washer 0.8 mm proud)", "CHECK16 rib_A_right: ... is 2.70 mm deep", fl, "CHECK16 rib_A_right", "is 2.70 mm deep")


@section("10c4. the CPU hose guide")
def s_guide_cpu(hardware, parts, base):
    # 10c4. revision 14a, item 3: the CPU hose guide is a comb on the left side fan's corner D. One M3 x 30 from the fan's outer face through the fan into an insert in the comb; both hoses in snap channels with
    # their mouths towards +X; the neck no longer carries it. The hoses cross the fan's open circle there, so the guide is held to a shadow, not to check 11's zero
    gd = part_named(parts, "hose_guide_cpu")
    gg = f.guide_cpu_geometry()
    gb_ = f.bbox_of(gd.solid)
    check("hose_guide_cpu: PA6, one valid solid on the left fan's inner face (X -235), one pilot at corner D's axis, the neck carries no guide pilot, nothing in the bill goes into the neck",
          gd.material == "PA6" and len(gd.solid.Solids()) == 1 and gd.solid.isValid() and abs(gb_[0] + 235.0) < 1e-6 and len([h for h in gd.holes if h.pilot]) == 1
          and not [h for h in part_named(parts, "neck_left").holes if h.item == "hose_guide_cpu"] and not [x for x in f.FASTENERS if x["item"] == "hose_guide_cpu" and "neck" in x["part"]]
          and abs(gg["axis"][0] - hw.bp_yz(*hw.FAN_SIDE_HOLES_UN["D"])[0]) < 1e-9 and abs(gg["axis"][1] - hw.bp_yz(*hw.FAN_SIDE_HOLES_UN["D"])[1]) < 1e-9,
          ("PA6, X from -235, 1 pilot on D's axis, none in the neck", f"X {gb_[0]:.1f}..{gb_[1]:.1f}, {len([h for h in gd.holes if h.pilot])} pilot(s)"))
    check("the guide's screw is an M3 x 30 through the fan's 25 mm (the M3 x 16 into the neck is gone), measured by check 15 on the hardware: stack 25, one row, derived and listed",
          f.screw_fit(f.FAN_STACK)[0] == 30 and sum(1 for r_ in base["screws"]["rows"] if r_["item"] == "hose_guide_cpu" and r_["length"] == 30 and abs(r_["stack"] - 25.0) < 1e-9) == 1
          and base["mounts"]["hose_guide_cpu"] == 1 == sum(x["count"] for x in f.FASTENERS if x["item"] == "hose_guide_cpu") and ("hose_guide_cpu", "fan_side_left") in base["contacts"] and ("hose_guide_cpu", "fan_side_left") in f.INTENDED_CONTACTS,
          ("M3 x 30, stack 25, 1 derived, 1 listed, the contact with the fan listed",
           f"{[(r_['part'], r_['length'], r_['stack']) for r_ in base['screws']['rows'] if r_['item'] == 'hose_guide_cpu']}"))
    check("the channels are within the guide's reach of corner D's screw (45 mm), both mouths open towards +X, away from the fan, and the guide is one of the parts that may reach the fans' limit",
          max(gg["s"]) <= f.GUIDE_CPU_REACH and f.guide_spec()["hose_guide_cpu"][2] == 1 and "hose_guide_cpu" in hw.FAN_SIDE_PARTS and base["envelope"]["parts_rest"][0] <= hw.ENVELOPE_X,
          (f"distances <= {f.GUIDE_CPU_REACH:g}, side +1, in FAN_SIDE_PARTS, the rest of the frame within 229", f"channel centres {gg['s'][1]:.1f} and {gg['s'][0]:.1f} mm from the screw's axis"))
    check("check 21 on the undamaged model: the guide shades under 400 mm2 of the fan's circle beyond the hoses",
          base["guide_shadow"][0][1] < f.GUIDE_SHADOW_MAX and not [x for x in base["failures"] if x.startswith("CHECK21")], (f"< {f.GUIDE_SHADOW_MAX:g} mm2", f"{base['guide_shadow'][0][1]:.0f} mm2"))
    (wide_solid, wide_holes, wide_blank), _ = f.build_hose_guide_cpu(width=60.0)
    r = f.run_checks(hardware, with_part(parts, "hose_guide_cpu", solid=wide_solid, blank=wide_blank, holes=wide_holes), MEMO)
    case("hose_guide_cpu built 60 mm wide along the hoses: it shades far more of the fan's circle", "CHECK21 hose_guide_cpu shades N mm2 of the open circle of fan_side_left outside the hoses, the limit is 400", r["failures"], "CHECK21 hose_guide_cpu", "the limit is 400")
    hg_ = next(h for h in gd.holes if h.pilot)
    r = f.run_checks(hardware, with_part(parts, "hose_guide_cpu", solid=refilled(gd, hg_)), MEMO)
    case("hose_guide_cpu: its insert pilot filled back in", "CHECK7 hose_guide_cpu ... M3 pilot ... is not drilled", r["failures"], "CHECK7 hose_guide_cpu", "M3 pilot", "is not drilled")
    case("  same damage, the guide's screw derived from the solids", "CHECK5 hose_guide_cpu: 0 positions have a hole", r["failures"], "CHECK5 hose_guide_cpu: 0 positions")
    mv = moved(gd, 5.0, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "hose_guide_cpu", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("hose_guide_cpu moved 5 mm along +X off the fan's face: the screw no longer meets its insert", "CHECK5 hose_guide_cpu: 0 positions have a hole", r["failures"], "CHECK5 hose_guide_cpu: 0 positions")
    mv = moved(gd, -5.0, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "hose_guide_cpu", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("hose_guide_cpu moved 5 mm into the left fan", "CHECK2 part x hardware hose_guide_cpu x fan_side_left", r["failures"], "CHECK2 part x hardware hose_guide_cpu x fan_side_left")
    mv = moved(gd, -26.0, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "hose_guide_cpu", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("hose_guide_cpu moved 26 mm outwards: past the fans' outer face (|X| 261)", "CHECK8 hose_guide_cpu reaches |X| = 261.00, limit 260", r["failures"], "CHECK8 hose_guide_cpu", "|X| = 261", "limit 260")
    gd_far = dataclasses.replace(gd, solid=gd.solid.translate(cq.Vector(0, 25.0, 0)), blank=gd.blank.translate(cq.Vector(0, 25.0, 0)), holes=[h.moved(0, 25.0, 0) for h in gd.holes])
    r = f.run_checks(hardware, with_part(parts, "hose_guide_cpu", solid=gd_far.solid, blank=gd_far.blank, holes=gd_far.holes), MEMO)
    case("hose_guide_cpu slid 25 mm along Y: it leaves the hoses (the channels no longer hold them)", "CHECK10 hose_guide_cpu x cpu_hoses[0]", r["failures"], "CHECK10 hose_guide_cpu x cpu_hoses[0]")
    neck_l, neck_r = part_named(parts, "neck_left"), part_named(parts, "neck_right")
    nl_mirror = [(round(h.start[0], 6) * -1, tuple(round(c, 6) for c in h.start[1:]), h.kind) for h in neck_l.holes if h.item != "organic pad"]
    nr_ = [(round(h.start[0], 6), tuple(round(c, 6) for c in h.start[1:]), h.kind) for h in neck_r.holes if h.item != "organic pad"]
    check("neck_left is neck_right mirrored: the same holes apart from the organic layer's pad (the left pad stands where neck_top_L is), now that the guide's pilot is gone",
          sorted(nl_mirror) == sorted(nr_) and abs(neck_l.solid.Volume() - neck_r.solid.Volume()) < 0.005 * neck_r.solid.Volume(), ("same holes mirrored, volumes within 0.5 %", f"{len(nl_mirror)} / {len(nr_)} holes; volumes {neck_l.solid.Volume():.0f} / {neck_r.solid.Volume():.0f}"))


@section("10c4. the CPU hoses shifted 1 mm, the guide rebuilt eight times")
def s_guide_shifted(hardware, parts, base):
    gd, gg = part_named(parts, "hose_guide_cpu"), f.guide_cpu_geometry()
    # revision 14a review: the comb's clearance holds by construction. Each CPU hose's route shifted 1 mm either way in two directions across the hose (towards the board, and square to that and to the
    # hose), the guide rebuilt for it: check 10 passes every time with the wall inside its window (it was 0.24 mm, 0.04 over the limit, and a 0.05 mm shift of hose 1 failed it)
    chains0 = f.hoses.keepout_chains()
    shifted_rows = []
    for i_ in (0, 1):
        _p, d_, _ = f.hose_at("cpu", i_, gg["u"][i_])
        ex_ = np.array([1.0, 0.0, 0.0]) - d_[0] * d_
        ex_ /= np.linalg.norm(ex_)
        wy_ = np.cross(d_, ex_)
        for tag_, v_ in (("+X", ex_), ("-X", -ex_), ("+w", wy_), ("-w", -wy_)):
            moved_chains = dict(chains0, cpu_hoses=[[np.array(q_) + (v_ if k_ == i_ else 0.0) for q_ in line] for k_, line in enumerate(chains0["cpu_hoses"])])
            saved_tubes = dict(f._TUBES)
            f._TUBES.clear()
            try:
                with patched(f.hoses, "keepout_chains", lambda m=moved_chains: m):
                    (s_g, h_g, b_g), _ = f.build_hose_guide_cpu()
                    fl = []
                    rows_g = f.check_guides([dataclasses.replace(gd, solid=s_g, blank=b_g, holes=h_g)], fl)
            finally:
                f._TUBES.clear()
                f._TUBES.update(saved_tubes)
            shifted_rows.append((i_, tag_, [round(r_[3], 3) for r_ in rows_g], fl, len(s_g.Solids())))
    check("each CPU hose's route shifted 1 mm in four directions across the hose (8 rebuilds): check 10 passes, the wall stays 0.2..0.5 mm from both true hoses, the guide stays one solid",
          len(shifted_rows) == 8 and all(not fl_ and len(w_) == 2 and all(f.GUIDE_WALL_MIN <= x_ <= f.GUIDE_WALL_MAX for x_ in w_) and n_ == 1 for _i, _t, w_, fl_, n_ in shifted_rows),
          ("8 x no failure, walls 0.2..0.5, one solid", "; ".join(f"hose {i_} {t_}: walls {w_}, {len(fl_)} failures {fl_[:1]}, {n_} solid(s)" for i_, t_, w_, fl_, n_ in shifted_rows)))
    check("the comb's channels are placed from the route: the line from corner D's screw axis runs to the point of the nearer hose's chain nearest to it (no literal u), and both walls are the play, 0.30 mm",
          not hasattr(f, "GUIDE_CPU_U1") and abs(gg["s"][1] - f.chain_nearest_yz([np.array(q_) for q_ in chains0["cpu_hoses"][1]], gg["axis"])[1]) < 1e-9
          and all(abs(r_[3] - f.GUIDE_PLAY) < 0.005 for r_ in base["guides"] if r_[0] == "hose_guide_cpu"),
          ("hose 1's channel at the nearest point, walls 0.30", f"s {gg['s'][1]:.2f} mm, u {gg['u'][1]:.1f}; walls {[round(r_[3], 3) for r_ in base['guides'] if r_[0] == 'hose_guide_cpu']}"))


@section("10d. the sill's cable window")
def s_sill_window(hardware, parts, base):
    sill = part_named(parts, "front_sill")
    # 10d. skeleton pass 1: the sill's cable window, and the insert pilots of the organic layer's twelve pads
    import numpy as np
    import organic_frame as of
    import cables
    g = f.sill_geometry()
    wx0, wx1, wz0, wz1 = g["window_xz"]
    ym = g["y_rear"] - f.SILL_REAR_WALL / 2                                       # the middle of the rear wall
    # revision 14a review: the rear bottom edge stays sharp, so the strip under the window is probed in the middle of the rear wall again, and at low Z: from just over the pocket's floor to just under
    # the window, at both ends of the window and in its middle (revision 14a had moved the probe 1 mm behind the pocket's plane, onto material the R 6 rounding had left)
    centre = cq.Vector((wx0 + wx1) / 2, ym, (wz0 + wz1) / 2)
    strip = [cq.Vector(x_, ym, z_) for x_ in (wx0 + 1.0, (wx0 + wx1) / 2, wx1 - 1.0) for z_ in (g["z0"] + 0.2, g["z0"] + 1.0, (g["z0"] + wz0) / 2, wz0 - 0.5)]
    solid_strip = [q_ for q_ in strip if sill.solid.isInside(q_)]
    check("the sill's rear wall has the cable window and keeps the strip under it down to the pocket's floor, probed in the middle of the wall", not sill.solid.isInside(centre) and len(solid_strip) == len(strip)
          and (wx0, wx1, wz0, wz1) == f.SILL_WINDOW_X + f.SILL_WINDOW_Z == (40.0, 90.0, 14.0, 46.0),
          ("window X 40..90, Z 14..46 (the sill's own numbers): empty in the middle, 12 points of the strip under it solid (Y = the wall's middle, Z 10.2..13.5)",
           f"X {wx0:g}..{wx1:g}, Z {wz0:g}..{wz1:g}; middle empty {not sill.solid.isInside(centre)}, strip {len(solid_strip)} of {len(strip)} solid"))
    # the window must let the module's cables through: each front USB route crosses the rear wall's middle plane inside the window, its radius and the cables' 3 mm clear of the window's edges
    routes = cables.build_routes()
    through = {}
    for n_ in ("usb3", "usbc"):
        rt_ = routes[n_]
        k_ = next(k for k in range(len(rt_.pts) - 1) if (rt_.pts[k][1] - ym) * (rt_.pts[k + 1][1] - ym) <= 0)
        a_, b_ = rt_.pts[k_], rt_.pts[k_ + 1]
        q_ = a_ + (ym - a_[1]) / (b_[1] - a_[1]) * (b_ - a_)
        m_ = rt_.r + cables.CLEAR_MM
        through[n_] = (round(float(q_[0]), 1), round(float(q_[2]), 1), wx0 + m_ <= q_[0] <= wx1 - m_ and wz0 + m_ <= q_[2] <= wz1 - m_)
    check("the front USB cables pass through the window: each crosses the rear wall's middle plane inside it, radius + 3 mm from its edges", all(v_[2] for v_ in through.values()),
          ("both inside X 40..90, Z 14..46 less r + 3", f"{through}"))
    short_ = hw.FRONT_IO_W[:1] + (f.SILL_WINDOW_X[1] - 5.0,) + hw.FRONT_IO_W[2:]          # a module 10 mm shorter on the right: its rear face ends 5 mm short of the window's right edge
    fl = []
    f.check_carrier(parts, dict(hardware, front_io=hw.wbox(*short_)), fl)
    case("a module whose rear face does not cover the window (10 mm shorter on the right, X -70..85): its cables could not reach all of it", "CHECK20 the sill's cable window ... is not behind the module's rear face",
         fl, "CHECK20 the sill's cable window", "is not behind the module's rear face")


@section("10d. the sill's cable window filled back in: the USB cables hit the sill")
def s_sill_window_filled(hardware, parts, base):
    sill, g = part_named(parts, "front_sill"), f.sill_geometry()
    filled = sill.solid.fuse(g["cuts"]["window"].intersect(f.Poly(g["pts"]).solid(-f.SILL_HALF_X, f.SILL_HALF_X))).clean()     # the sill as it was without the window
    parts_nowin = with_part(parts, "front_sill", solid=filled)
    routes = cables.build_routes()
    cables.evaluate(routes, parts_nowin, hardware)
    bad = [t for n in ("usb3", "usbc") for _c, t in routes[n].fail if "front_sill" in t]
    check("the two front USB cables go through the window: with it filled back in both hit the sill", len(bad) == 2,
          ("USB 3 and USB-C each report 'N mm from front_sill, needs 3'", "; ".join(bad) or "no failure"))


@section("10d. with the window every cable check passes")
def s_sill_window_cables(hardware, parts, base):
    routes = cables.build_routes()
    ov = cables.evaluate(routes, parts, hardware)
    check("with the window every cable check passes", not cables.failures(routes, ov), ("0 failed cable checks", f"{len(cables.failures(routes, ov))}: {'; '.join(t for _c, t in cables.failures(routes, ov)[:2])}"))


@section("10d2. check 22, the sill's rear wall")
def s_sill_wall(hardware, parts, base):
    sill, g = part_named(parts, "front_sill"), f.sill_geometry()
    # 10d2. revision 14a review, check 22: the sill's rear wall behind the pocket keeps 2 mm from the pocket's floor to its roof and over its length; the rear bottom edge stays sharp (a logged exception)
    sw_ = base["sill_wall"]
    logged_ = [e for e in f.ROUND_LOG if e.part == "front_sill" and e.radius == 0 and e.reason == f.SILL_REAR_EDGE_SHARP and abs(e.pt[1] - g["y_rear"]) < 0.01 and abs(e.pt[2] - g["z0"]) < 0.01]
    check("check 22 on the undamaged model: the rear wall is 2.9 mm everywhere it is probed (more than 300 probes, the pocket's floor included), the sharp rear bottom edge is in the rounding log with its reason",
          sw_ and abs(sw_["min"][0] - f.SILL_REAR_WALL) < 0.01 and sw_["n"] > 300 and abs(sw_["min"][2] - g["z0"]) < 0.5 and len(logged_) == 1 and not [x for x in base["failures"] if x.startswith("CHECK22")],
          ("min 2.90 mm over > 300 probes, one log entry", f"min {sw_['min'] if sw_ else None}, {sw_.get('n') if sw_ else 0} probes, {len(logged_)} log entries"))
    yb_, zb_ = g["y_rear"], g["z0"]
    wedge_ = hw.wbox(-f.SILL_HALF_X - 1.0, f.SILL_HALF_X + 1.0, yb_ - f.ROUND_CONVEX, yb_ + 1.0, zb_ - 1.0, zb_ + f.ROUND_CONVEX).cut(
        f.cyl((-f.SILL_HALF_X - 2.0, yb_ - f.ROUND_CONVEX, zb_ + f.ROUND_CONVEX), (1.0, 0.0, 0.0), 2 * f.ROUND_CONVEX, 2 * f.SILL_HALF_X + 4.0))
    fl = []
    f.check_sill_rear_wall(with_part(parts, "front_sill", solid=sill.solid.cut(wedge_)), fl)
    case("front_sill with its rear bottom edge rounded R 6 again (as revision 14a had it)", "CHECK22 the sill's rear wall behind the pocket is 0.00 mm thick at ..., needs 2", fl, "CHECK22 the sill's rear wall", "needs 2")
    deeper_pocket = hw.wbox(f.CARRIER_X[0] - f.SILL_POCKET_PLAY, f.CARRIER_X[1] + f.SILL_POCKET_PLAY, g["pocket_rear"] - 1.0, g["pocket_rear"] + 1.0, zb_ - 1.0, g["roof"])
    fl = []
    f.check_sill_rear_wall(with_part(parts, "front_sill", solid=sill.solid.cut(deeper_pocket)), fl)
    case("front_sill with its pocket 1 mm deeper (the rear wall thinned to 1.9 mm)", "CHECK22 the sill's rear wall behind the pocket is 1.90 mm thick ..., needs 2", fl, "CHECK22 the sill's rear wall", "is 1.90 mm", "needs 2")


@section("10d3. the organic layer's pads")
def s_pads(hardware, parts, base):
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
    r = f.run_checks(hardware, with_part(parts, pn_l, solid=refilled(pl, next(h for h in pl.holes if h.pilot and h.item == "organic pad"))), MEMO)
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


@section("10e. the cable tie points and bridges")
def s_tie_points(hardware, parts, base):
    # 10e. skeleton pass 2: the cable tie points and the one bridge shape
    tps = f.TIE_POINTS
    n_tie = len(tps)
    bridges = [part_named(parts, f.tie_name(tp)) for tp in tps]
    listed = {k: sum(x["count"] for x in f.FASTENERS if x["item"] == k) for k in ("tie_pilot", "tie_bridge")}
    check("every tie point has an M3 pilot in its part and a clearance hole in its bridge: derived from the solids, and the fastener list agrees",
          n_tie >= 8 and base["mounts"]["tie_pilot"] == n_tie and base["mounts"]["tie_bridge"] == n_tie and f.EXPECTED_MOUNTS["tie_pilot"] == n_tie and f.EXPECTED_MOUNTS["tie_bridge"] == n_tie
          and listed == {"tie_pilot": n_tie, "tie_bridge": n_tie},
          (f"{n_tie} pilots and {n_tie} holes derived, {n_tie} listed each", f"derived {base['mounts']['tie_pilot']} / {base['mounts']['tie_bridge']}, listed {listed}"))
    rows = {tp["row"]: tp["host"] for tp in tps}
    check("the rows: the first pass's four on undersides (mid, rail, low, top) and the second pass's three on faces that look sideways or up (leg and post: the right ribs' inner faces, skid: the top of skid_front)",
          rows == {"mid": "beam_mid", "rail": "rib_A_right", "low": "beam_low", "top": "beam_top", "leg": "rib_A_right", "post": "rib_B_right", "skid": "skid_front"}
          and all(tp["normal"] == f.TIE_UNDER for tp in tps if tp["row"] in ("mid", "rail", "low", "top")) and all(tp["normal"] == (-1.0, 0.0, 0.0) for tp in tps if tp["row"] in ("leg", "post"))
          and all(tp["normal"] == (0.0, 0.0, 1.0) for tp in tps if tp["row"] == "skid"),
          ("seven rows on seven hosts, normals -n / -X / +Z as listed", str(rows)))
    right_only = [tp for tp in tps if tp["host"] in ("rib_A_right", "rib_B_right")]
    leaked, blind = [], []
    for tp in right_only:       # a pilot of a right rib must not appear in the left twin (built right-handed and mirrored): its mirrored bore axis point is material there
        twin = part_named(parts, tp["host"].replace("right", "left"))
        probe = tuple(c - f.ORGANIC_PROBE_DEPTH * k for c, k in zip(tp["pt"], tp["normal"]))
        if part_named(parts, tp["host"]).solid.isInside(cq.Vector(*probe)):      # control: the same probe in the right rib is inside its bore, which is empty
            blind.append(f.tie_name(tp))
        if not twin.solid.isInside(cq.Vector(-probe[0], probe[1], probe[2])) or any(h.pilot and math.dist(h.point(f.OVERSHOOT), (-tp["pt"][0], tp["pt"][1], tp["pt"][2])) < 0.5 for h in twin.holes):
            leaked.append(f.tie_name(tp))
    check("tie points are on the right-hand ribs only: no pilot at the mirrored place of any of them in rib_A_left or rib_B_left, which are built right-handed and mirrored", len(right_only) >= 6 and not leaked and not blind,
          ("no left twin has a bore where a right rib has a tie pilot (and the probe does find the bore in the right rib)", f"{len(right_only)} right-rib tie points; bored in the left twin: {leaked or 'none'}; probe missed the right rib's bore: {blind or 'none'}"))
    vols = [b.blank.Volume() for b in bridges]
    check("one bridge shape: every bridge has the same volume before and after its hole, and 28 x 13 x 9 mm", max(vols) - min(vols) < 1e-6
          and max(b.solid.Volume() for b in bridges) - min(b.solid.Volume() for b in bridges) < 1e-6
          and abs(f.TIE_ARCH_END + f.TIE_HOLE_END - 28.0) < 1e-9 and f.TIE_W == 13.0 and abs(f.TIE_H - 9.0) < 1e-9 and f.TIE_SLOT_W >= 12.0 + 0.4 and all(b.material == "ABS" for b in bridges),
          ("equal volumes, 28 x 13 x 9, a slot wider than the 12 mm strap, ABS", f"{min(vols):.1f}..{max(vols):.1f} mm3, slot {f.TIE_SLOT_W:g}"))
    tp0 = tps[0]
    hp = part_named(parts, tp0["host"])
    hole0 = next(h for h in hp.holes if h.pilot and h.kind == "M3" and math.dist(h.point(f.OVERSHOOT), f.tie_face_point(tp0)) < 0.01)
    r = f.run_checks(hardware, with_part(parts, tp0["host"], solid=refilled(hp, hole0)), MEMO)
    case(f"{f.tie_name(tp0)}: its pilot in {tp0['host']} filled back in", f"CHECK7 {tp0['host']} ... M3 pilot ... is not drilled", r["failures"], f"CHECK7 {tp0['host']}", "M3 pilot", "is not drilled")
    case("  same damage, the tie pilot count derived from the solids", f"CHECK5 tie_pilot: {n_tie - 1} positions have a hole", r["failures"], f"CHECK5 tie_pilot: {n_tie - 1} positions")
    tp_r = next(tp for tp in tps if tp["host"] == "rib_A_right")
    hr = part_named(parts, "rib_A_right")
    hole_r = next(h for h in hr.holes if h.pilot and h.kind == "M3" and math.dist(h.point(f.OVERSHOOT), f.tie_face_point(tp_r)) < 0.01)
    r = f.run_checks(hardware, with_part(parts, "rib_A_right", solid=refilled(hr, hole_r)), MEMO)
    case(f"{f.tie_name(tp_r)}: the rail's pilot filled back in", f"CHECK5 tie_pilot: {n_tie - 1} positions have a hole", r["failures"], f"CHECK5 tie_pilot: {n_tie - 1} positions")
    case("  same damage, check 7 on the rail", "CHECK7 rib_A_right ... M3 pilot ... is not drilled", r["failures"], "CHECK7 rib_A_right", "M3 pilot", "is not drilled")


@section("10e. the tie bridges moved: off the pilot, lifted, pressed in, next to each other, in a cable's lane")
def s_tie_bridges_moved(hardware, parts, base):
    tps = f.TIE_POINTS
    n_tie = len(tps)
    tp0 = tps[0]
    bridges = [part_named(parts, f.tie_name(tp)) for tp in tps]
    b0 = bridges[0]
    ax = hw.U_DIR if tp0["dir"][0] == 0.0 else tp0["dir"]
    mv = moved(b0, *(0.5 * c for c in ax))
    r = f.run_checks(hardware, with_part(parts, b0.name, solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case(f"{b0.name} slid 0.5 mm along its face: still on its host, but off its pilot", f"CHECK5 tie_bridge: {n_tie - 1} positions have a hole", r["failures"], f"CHECK5 tie_bridge: {n_tie - 1} positions")
    axis_gap = max(math.dist(b.holes[0].point(f.TIE_FOOT_T + f.OVERSHOOT), f.tie_face_point(tp)) for b, tp in zip(bridges, tps))
    check("every bridge sits on its pilot: the bridge's hole axis passes through the tie point on the host's face", axis_gap < 1e-6 and all(
          abs(sum((a - c) * k for a, c, k in zip(b.holes[0].start, f.tie_face_point(tp), tp["normal"])) - (f.TIE_FOOT_T + f.OVERSHOOT)) < 1e-6 for b, tp in zip(bridges, tps)),
          ("each hole starts 3.5 mm above its tie point along the normal, on the axis", f"largest offset of an axis point from its tie point {axis_gap:.1e} mm"))
    lift = moved(b0, *(1.0 * c for c in tp0["normal"]))
    r = f.run_checks(hardware, with_part(parts, b0.name, solid=lift.solid, blank=lift.blank, holes=lift.holes), MEMO)
    case(f"{b0.name} lifted 1 mm off its host", f"CHECK3 tie bridge {b0.name} touches nothing, the plan lists only its host", r["failures"], f"CHECK3 tie bridge {b0.name} touches nothing")
    sunk = moved(b0, *(-1.0 * c for c in tp0["normal"]))
    r = f.run_checks(hardware, with_part(parts, b0.name, solid=sunk.solid, blank=sunk.blank, holes=sunk.holes), MEMO)
    case(f"{b0.name} pressed 1 mm into its host", f"CHECK3 part x part {tp0['host']} x {b0.name}: ... mm3", r["failures"], "CHECK3 part x part", b0.name, "mm3")
    rail = {tp["k"]: b for b, tp in zip(bridges, tps) if tp["row"] == "rail"}      # rail_3 and rail_4 stand 3 mm apart on the rail's underside, along u
    gap_rail = f.solid_distance(rail[3].solid, rail[4].solid)
    along = tuple(hw.U_DIR)
    mv = moved(rail[3], *(gap_rail * c for c in along))
    r = f.run_checks(hardware, with_part(parts, rail[3].name, solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case(f"{rail[3].name} slid along the rail until it touches {rail[4].name}", f"CHECK3 tie bridge {rail[3].name} touches ['{rail[4].name}', ...], the plan lists only its host", r["failures"],
         f"CHECK3 tie bridge {rail[3].name} touches", rail[4].name)
    mv = moved(rail[3], *((gap_rail - 1.0) * c for c in along))
    r = f.run_checks(hardware, with_part(parts, rail[3].name, solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case(f"{rail[3].name} 1 mm from {rail[4].name}", f"CHECK3 tie bridge {rail[3].name} is 1.00 mm from {rail[4].name}, needs {f.TIE_CLEAR:g}", r["failures"], f"CHECK3 tie bridge {rail[3].name} is 1.00 mm from {rail[4].name}")
    import cables
    far = bridges[0]
    routes = cables.build_routes()
    mv = moved(far, 28.0, 0.0, 0.0)     # slid in X into the lane the USB 3 cable runs in under beam_mid (X 116..128, n -41)
    ov = cables.evaluate(routes, with_part(parts, far.name, solid=mv.solid, blank=mv.blank, holes=mv.holes), hardware)
    bad = [t for _c, t in cables.failures(routes, ov) if far.name in t]
    check("a bridge slid into USB 3's lane is a cable failure: cables.py keeps 3 mm from every bridge", len(bad) >= 1 and "needs 3" in bad[0], (f"'... mm from {far.name}, needs 3'", "; ".join(bad) or "no failure"))


@section("10f. the tie rules of cables.py")
def s_tie_rules(hardware, parts, base):
    tps = f.TIE_POINTS
    n_tie = len(tps)
    routes = cables.build_routes()
    ov = cables.evaluate(routes, parts, hardware)

    # 10f. skeleton pass 2, the two rules of "Tie points, second pass: spec", in cables.py. tie_eval / tie_failures take the slots of the bridges that are present, so a bridge taken out
    # of the parts list is a tie point removed.
    def tie_failures_with(slots_):
        out = []
        for n in cables.TIE_ROUTES:
            rt = routes[n]
            saved, rt.tie = rt.tie, cables.tie_eval(rt, slots_)
            out += [f"{cables.TITLE[n]}: {t}" for _c, t in cables.tie_failures(rt)]
            rt.tie = saved
        return out
    slots = cables.tie_slots(parts)
    check("the spec's two numbers are cables.py's: TIE_REACH 30 mm, stretches of at most 150 mm, bends of 30 deg or more", cables.TIE_REACH == 30.0 and cables.TIE_STRETCH == 150.0 and cables.TIE_BEND_DEG == 30.0,
          ("30 / 150 / 30", f"{cables.TIE_REACH:g} / {cables.TIE_STRETCH:g} / {cables.TIE_BEND_DEG:g}"))
    stats = {n: routes[n].tie for n in cables.TIE_ROUTES}
    n_bends = sum(len(v["bends"]) for v in stats.values())
    worst_d = max(b[3] for v in stats.values() for b in v["bends"])
    worst_s = max(v["stretches"][0][0] if v["stretches"] else 0.0 for v in stats.values())
    check("as built every bend of 30 deg or more below the board has a tie point (or a plug) within 30 mm, and no stretch below the board is over 150 mm: no tie failure, no cable failure",
          set(stats) == {"atx24", "gpu12v", "eps1", "eps2", "usb3", "usbc"} and n_bends >= 15 and worst_d <= cables.TIE_REACH and worst_s <= cables.TIE_STRETCH and not tie_failures_with(slots) and not cables.failures(routes, ov),
          (f"{n_bends} bends all within 30 mm, stretches within 150 mm, 0 failures", f"worst bend {worst_d:.1f} mm, longest stretch {worst_s:.0f} mm, tie failures {len(tie_failures_with(slots))}, cable failures {len(cables.failures(routes, ov))}"))
    check("every bridge shapes a cable: the middle of its slot is within 30 mm of at least one of the six routes",
          all(min(float(np.linalg.norm(routes[n].pts - c, axis=1).min()) for n in cables.TIE_ROUTES) <= cables.TIE_REACH for c in slots.values()) and len(slots) == n_tie,
          (f"all {n_tie} slots within 30 mm of a route", "; ".join(f"{k} {min(float(np.linalg.norm(routes[n].pts - c, axis=1).min()) for n in cables.TIE_ROUTES):.1f}" for k, c in slots.items())))
    none = tie_failures_with({})
    check("the two plugs count as fixed points: with no bridge at all the bends within 30 mm of a plug are not failures and the others are",
          not any("bend of 148 deg" in t or "bend of 128 deg" in t or "bend of 104 deg" in t or "bend of 92 deg" in t for t in none) and any("bend of 45 deg" in t for t in none),
          ("ATX 148 deg, 12V-2x6 128 deg, EPS 1 92 deg, EPS 2 104 deg unreported; ATX 45 deg reported", f"{len(none)} failures without bridges, e.g. {none[0] if none else 'none'}"))
    def without(*names):
        return tie_failures_with({k: v for k, v in slots.items() if k not in names})
    got = without("tie_bridge_leg_1")
    case("tie_bridge_leg_1 taken out (it holds ATX's 45 deg corner and EPS 1's 38 deg corner)", "ATX 24-pin: bend of 45 deg ... has no tie point within 30 mm", got, "ATX 24-pin", "bend of 45 deg", "no tie point within 30 mm")
    case("  same removal: EPS 1's corner", "EPS 1: bend of 38 deg ... has no tie point within 30 mm", got, "EPS 1", "bend of 38 deg", "no tie point within 30 mm")
    case("  same removal: ATX has a stretch of over 150 mm with no tie point", "ATX 24-pin: ... mm of its length below the board have no tie point within 30 mm (limit 150)", got, "ATX 24-pin", "below the board have no tie point within 30 mm (limit 150)")
    case("tie_bridge_skid_1 taken out (EPS 2 round the PSU's front corner)", "EPS 2: bend of 76 deg ... has no tie point within 30 mm", without("tie_bridge_skid_1"), "EPS 2", "bend of 76 deg", "no tie point within 30 mm")
    got = without("tie_bridge_post_1")
    case("tie_bridge_post_1 taken out (the 90 deg corners of EPS 1 and EPS 2 at the foot of the gap)", "EPS 2: bend of 90 deg ... has no tie point within 30 mm", got, "EPS 2", "bend of 90 deg", "no tie point within 30 mm")
    case("  same removal: EPS 1's corner", "EPS 1: bend of 90 deg ... has no tie point within 30 mm", got, "EPS 1", "bend of 90 deg", "no tie point within 30 mm")
    case("tie_bridge_low_2 taken out (USB-C's dive under the board)", "USB-C front: bend of 84 deg ... has no tie point within 30 mm", without("tie_bridge_low_2"), "USB-C front", "bend of 84 deg", "no tie point within 30 mm")
    case("tie_bridge_leg_2 taken out (USB 3's 90 deg corner)", "USB 3 front: bend of 90 deg ... has no tie point within 30 mm", without("tie_bridge_leg_2"), "USB 3 front", "bend of 90 deg", "no tie point within 30 mm")
    rt_x = routes["atx24"]
    saved_tie, saved_fail = rt_x.tie, rt_x.fail
    rt_x.tie = cables.tie_eval(rt_x, {k: v for k, v in slots.items() if k != "tie_bridge_leg_1"})
    rt_x.fail = list(cables.tie_failures(rt_x))
    got = [t for _c, t in cables.failures(routes, [])]
    rt_x.tie, rt_x.fail = saved_tie, saved_fail
    check("a tie failure is a cable failure, so cables.py ends with exit status 1: failures() carries it with the cable's name", any(t.startswith("ATX 24-pin: bend of 45 deg") for t in got),
          ("'ATX 24-pin: bend of 45 deg ...' among the failures", got[0] if got else "no failure"))


@section("14. the drive bay")
def s_drive_bay(hardware, parts, base):
    # 14. the drive bay (docs/plans/cables-and-organic.md, "Drive bays, pass 1"; one bay, the left: the PSU's cables run through the right side): hole patterns, seats, envelope, contacts.
    # The sled is built right-handed and mirrored, so the cutters of the damage below are built right-handed and mirrored too.
    lay = hw.drive_layout()
    n_screws = sum(len(fc["holes"]) for fc in lay["faces"].values())
    sled_l = part_named(parts, "drive_sled_left")
    check("one bay, the left: one sled, one drive, one plug zone, and no right-hand part or hardware",
          list(hw.DRIVE_SIDES) == ["left"] and hw.DRIVES == ("drive_left",) and sum(1 for p_ in parts if p_.name.startswith("drive_sled")) == 1
          and not [k_ for k_ in hardware if k_.startswith("drive") and k_.endswith("right")],
          ("DRIVE_SIDES = {'left': -1}, 1 sled, drive_left only", f"{hw.DRIVE_SIDES}, {[p_.name for p_ in parts if p_.name.startswith('drive_sled')]}, {[k_ for k_ in hardware if k_.startswith('drive')]}"))
    check("the sled has its ten drive screw holes derived from the solids (six 6-32 and four M3), the fastener list agrees, and check 13 is quiet",
          base["mounts"]["drive_left"] == n_screws == 10 and sum(f_["count"] for f_ in f.FASTENERS if f_["item"] == "drive_left") == 10 and "drive_right" not in base["mounts"]
          and not [x for x in base["failures"] if x.startswith("CHECK13")],
          ("10, no CHECK13", f"{base['mounts'].get('drive_left')}, {len([x for x in base['failures'] if x.startswith('CHECK13')])} CHECK13"))
    check("the screws enter the drives as the standards allow: 3.35 mm into the 3.5 inch (2.39..3.56), 2.00 mm into the 2.5 inch (up to 2.50), with the head's room under the face",
          len(base["drives"]) == 1 and all(abs(r_["pen"]["outer"][0] - 3.35) < 0.02 and abs(r_["pen"]["inner"][0] - 2.0) < 0.02 and min(r_["head"].values()) >= 2.5 - 1e-6 for r_ in base["drives"]),
          ("3.35 and 2.00 mm, head room 2.5 mm", "; ".join(f"{r_['bay']}: {r_['pen']['outer'][0]:.2f}, {r_['pen']['inner'][0]:.2f}, room {min(r_['head'].values()):.2f}" for r_ in base["drives"])))
    contacts_all = set(base["contacts"]) | set(base["pp_contact"]) | {(b_, a_) for a_, b_ in base["pp_contact"]}
    check("the bosses carry the drive (listed zero-gap contact), the foot stands on skid_rear and the flange against psu_bulkhead (part contacts), no other contact with hardware",
          ("drive_sled_left", "drive_left") in base["contacts"] and ("drive_sled_left", "drive_left") in f.INTENDED_CONTACTS and ("drive_sled_left", "skid_rear") in contacts_all
          and ("drive_sled_left", "psu_bulkhead") in contacts_all and not [c_ for c_ in base["contacts"] if c_[0].startswith("drive_sled") and c_ not in f.INTENDED_CONTACTS],
          ("drive, skid_rear, psu_bulkhead; nothing else", f"{sorted(c_ for c_ in base['contacts'] if c_[0].startswith('drive_sled'))}"))
    check("the plug zone is a keep-out, the drive is not, and each is a compound of two bodies (3.5 inch outer, 2.5 inch inner)",
          all(k_ in hw.KEEP_OUT for k_ in hw.DRIVE_PLUGS) and not any(k_ in hw.KEEP_OUT for k_ in hw.DRIVES) and all(len(hardware[k_].Solids()) == 2 for k_ in hw.DRIVES + hw.DRIVE_PLUGS),
          ("plug zone in KEEP_OUT, drive out, two solids each", f"{[k_ in hw.KEEP_OUT for k_ in hw.DRIVE_PLUGS + hw.DRIVES]}"))
    check("every name that colours or draws a bay is a bay that exists: HW_COLORS and render_vtk.HW_RGB name no drive that is not in hardware",
          {k_ for k_ in hw.HW_COLORS if k_.startswith("drive")} == set(hw.DRIVES + hw.DRIVE_PLUGS) == {k_ for k_ in __import__("render_vtk").HW_RGB if k_.startswith("drive")},
          ("drive_left, drive_plugs_left only", f"{sorted(k_ for k_ in hw.HW_COLORS if k_.startswith('drive'))}"))


@section("14a. a drive's hole pattern shifted")
def s_drive_patterns(hardware, parts, base):
    # 14a. a hole pattern shifted 5 mm in hardware.py, the sled left as it was: the screws of that drive have no holes (the 4 M3 holes of the other face still do)
    forms0 = hw.DRIVE_FORMS
    shifted = {k_: dict(v_) for k_, v_ in forms0.items()}
    shifted["hdd35"]["rows"] = tuple(r_ + 5.0 for r_ in forms0["hdd35"]["rows"])
    with patched(hw, "DRIVE_FORMS", shifted):
        r = f.run_checks(hardware, parts, MEMO)
    case("the 3.5 inch pattern shifted 5 mm in hardware.py: the six 6-32 positions have no hole", "CHECK5 drive_left: 4 positions have a hole", r["failures"], "CHECK5 drive_left: 4 positions")
    case("  same damage, the sled's recorded holes disagree with the table", "CHECK13 drive_sled_left: no recorded 6-32 hole at the table's (Y ..., Z ...)", r["failures"], "CHECK13 drive_sled_left: no recorded 6-32 hole")
    shifted = {k_: dict(v_) for k_, v_ in forms0.items()}
    shifted["ssd25"]["col_inset"] = forms0["ssd25"]["col_inset"] + 5.0
    with patched(hw, "DRIVE_FORMS", shifted):
        r = f.run_checks(hardware, parts, MEMO)
    case("the 2.5 inch columns shifted 5 mm in hardware.py: the four M3 positions have no hole", "CHECK5 drive_left: 6 positions have a hole", r["failures"], "CHECK5 drive_left: 6 positions")


@section("14b. the sled's seats and bores")
def s_drive_seats(hardware, parts, base):
    lay, sled_l = hw.drive_layout(), part_named(parts, "drive_sled_left")
    # 14b. a seat too thin or too thick: the counterbore cut 1 mm deeper under one head leaves 2 mm, and the screw enters 4.35 mm (3.5 inch, limit 3.56) or 3.00 mm (2.5 inch, limit 2.50)
    px0, px1 = lay["plate_x"]
    y_o, z_o = lay["faces"]["outer"]["holes"][0]
    y_i, z_i = lay["faces"]["inner"]["holes"][0]
    cb_o = f.mirror_x(f.cyl((px0 - f.OVERSHOOT, y_o, z_o), (1, 0, 0), lay["faces"]["outer"]["spec"]["head_d"] + f.SLED_CB_PLAY, f.OVERSHOOT + 4.0))
    cb_i = f.mirror_x(f.cyl((px1 + f.OVERSHOOT, y_i, z_i), (-1, 0, 0), lay["faces"]["inner"]["spec"]["head_d"] + f.SLED_CB_PLAY, f.OVERSHOOT + 4.0))
    r = f.run_checks(hardware, with_part(parts, "drive_sled_left", solid=sled_l.solid.cut(cb_o)), MEMO)
    case("drive_sled_left: one 6-32 counterbore cut 1 mm too deep (2 mm of seat)", "CHECK13 drive_sled_left: the 6-32 screw ... enters the outer drive 4.35 mm", r["failures"], "CHECK13 drive_sled_left", "6-32 screw", "enters the outer drive 4.35")
    r = f.run_checks(hardware, with_part(parts, "drive_sled_left", solid=sled_l.solid.cut(cb_i)), MEMO)
    case("drive_sled_left: one M3 counterbore cut 1 mm too deep (2 mm of seat)", "CHECK13 drive_sled_left: the M3 screw ... enters the inner drive 3.00 mm", r["failures"], "CHECK13 drive_sled_left", "M3 screw", "enters the inner drive 3.00")
    ring = f.mirror_x(f.cyl((px0 + 0.5, y_o, z_o), (1, 0, 0), 7.4, 1.0).cut(f.cyl((px0 + 0.4, y_o, z_o), (1, 0, 0), 6.0, 1.2)))      # a lip in the counterbore: the head has no room under it
    r = f.run_checks(hardware, with_part(parts, "drive_sled_left", solid=sled_l.solid.fuse(ring).clean()), MEMO)
    case("drive_sled_left: a lip inside one counterbore, the head has no room", "CHECK13 drive_sled_left: the head of the 6-32 screw ... has room only 0.50 mm", r["failures"], "CHECK13 drive_sled_left", "head of the 6-32 screw", "has room only")
    hole_o = next(h for h in sled_l.holes if h.kind == "6-32c")
    r = f.run_checks(hardware, with_part(parts, "drive_sled_left", solid=refilled(sled_l, hole_o)), MEMO)
    case("drive_sled_left: one 6-32 drive screw bore (3.5 inch drive) filled back in", "CHECK7 drive_sled_left ... 6-32c clearance ... is not drilled", r["failures"], "CHECK7 drive_sled_left", "6-32c clearance", "is not drilled")
    case("  same damage, the drive's screw count derived from the solids", "CHECK5 drive_left: 9 positions have a hole", r["failures"], "CHECK5 drive_left: 9 positions")
    hole_i = next(h for h in sled_l.holes if h.kind == "M3c")
    r = f.run_checks(hardware, with_part(parts, "drive_sled_left", solid=refilled(sled_l, hole_i)), MEMO)
    case("drive_sled_left: one M3 drive screw bore (2.5 inch drive) filled back in", "CHECK7 drive_sled_left ... M3c clearance ... is not drilled", r["failures"], "CHECK7 drive_sled_left", "M3c clearance", "is not drilled")
    pilot_f = next(h for h in sled_l.holes if h.pilot)
    r = f.run_checks(hardware, with_part(parts, "drive_sled_left", solid=refilled(sled_l, pilot_f)), MEMO)
    case("drive_sled_left (built right-handed, mirrored): one flange pilot filled back in", "CHECK7 drive_sled_left ... M3 pilot ... is not drilled", r["failures"], "CHECK7 drive_sled_left", "M3 pilot", "is not drilled")
    bulk = part_named(parts, "psu_bulkhead")
    hole_b = next(h for h in bulk.holes if h.kind == "M3c" and h.start[2] == f.SLED_BOLT_Z[0] and h.start[0] < 0)
    r = f.run_checks(hardware, with_part(parts, "psu_bulkhead", solid=refilled(bulk, hole_b)), MEMO)
    case("psu_bulkhead: the sled's lower flange clearance hole filled back in", "CHECK7 psu_bulkhead ... M3c clearance ... is not drilled", r["failures"], "CHECK7 psu_bulkhead", "M3c clearance", "is not drilled")
    flank = [h_b for h_b in bulk.holes if h_b.kind == "M3c" and abs(h_b.start[0]) > 80]
    check("the flange screws line up: each sled pilot axis meets a clearance hole of the bulkhead (X -89.5 at Z 30 and 76), and the bulkhead has holes on the left only",
          all(any(abs(h_b.start[0] - pl.start[0]) < 1e-6 and abs(h_b.start[2] - pl.start[2]) < 1e-6 for h_b in flank) for pl in sled_l.holes if pl.pilot)
          and sum(1 for h_ in sled_l.holes if h_.pilot) == 2 == len(flank) and all(h_b.start[0] < 0 for h_b in flank),
          ("2 pilots, 2 clearance holes, same X and Z, none at X > 0", f"{[(h_.kind, round(h_.start[0], 1), round(h_.start[2], 1)) for h_ in flank]}"))


@section("14c. the sled moved")
def s_drive_moves(hardware, parts, base):
    sled_l = part_named(parts, "drive_sled_left")
    # 14c. a sled moved into its drive, out of its envelope, off the bulkhead and the skid
    mv = moved(sled_l, -2, 0, 0)
    r = f.run_checks(hardware, with_part(parts, "drive_sled_left", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("drive_sled_left moved 2 mm into its drive (the bosses enter the 3.5 inch body)", "CHECK2 part x hardware drive_sled_left x drive_left", r["failures"], "CHECK2 part x hardware drive_sled_left x drive_left")
    mv = moved(sled_l, 0, -5, 0)
    r = f.run_checks(hardware, with_part(parts, "drive_sled_left", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("drive_sled_left moved 5 mm to the front: the bay leaves its envelope (Y 248..375)", "CHECK13 left bay ... outside the envelope", r["failures"], "CHECK13 left bay", "outside the envelope")
    mv = moved(sled_l, 0, 0, 3)
    r = f.run_checks(hardware, with_part(parts, "drive_sled_left", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("drive_sled_left lifted 3 mm off skid_rear: the foot no longer stands on it", "CHECK13 drive_sled_left does not stand on skid_rear: no zero-gap contact", r["failures"], "CHECK13 drive_sled_left", "skid_rear", "no zero-gap contact")
    mv = moved(sled_l, 0, -3, 0)
    r = f.run_checks(hardware, with_part(parts, "drive_sled_left", solid=mv.solid, blank=mv.blank, holes=mv.holes), MEMO)
    case("drive_sled_left moved 3 mm to the front: the flange leaves the bulkhead", "CHECK13 drive_sled_left does not stand against psu_bulkhead: no zero-gap contact", r["failures"], "CHECK13 drive_sled_left", "psu_bulkhead", "no zero-gap contact")


@section("14d. drive_access.py")
def s_drive_access(hardware, parts, base):
    lay = hw.drive_layout()
    # 14d. cad_b6/drive_access.py: the sweep. The bay (the left; there is no right bay, the PSU cables run through it), without and with the plug zone
    import drive_access as da
    field = da.load_field()
    strands, no_strand = da.cable_strands()
    maps_l = da.bay_maps(parts, hardware, strands, field, "left")
    rects_l = da.bay_rects(parts, hardware, "left")
    res_l = [da.access(maps_l, rc) for rc in rects_l]
    check("drive_access: the left bay's sled can be carried in from behind with at most 30 degrees of tilt, without and with the plug zone", all(da.passes(x_) for x_ in res_l),
          ("a path, least tilt <= 30 both times", "; ".join(da.verdict(x_) for x_ in res_l)))
    check("drive_access: every cable route is in the grid (no route without strands), and the body is the sled, the drives and the plug boxes as built",
          not no_strand and len(strands) == 12 and len(rects_l[0]) == 3 and len(rects_l[1]) == 5 and abs(da.silhouette(rects_l[1])[3] - (lay["z_top"] + hw.DRIVE_PLUG_ZONE)) < 1e-6,
          ("12 routes, 3 and 5 rectangles, top at the plug zone's top", f"{len(strands)} routes (without strands: {no_strand}), {len(rects_l[0])} and {len(rects_l[1])} rectangles, top {da.silhouette(rects_l[1])[3]!r} against {lay['z_top'] + hw.DRIVE_PLUG_ZONE!r}"))
    seat_l = da.access(maps_l, rects_l[1], extra_blocks=[(250.0, 300.0, 100.0, 130.0)])
    check("drive_access: a block of 50 x 30 mm in the seat (Y 250..300, Z 100..130) leaves the seat blocked, and the check fails", not da.passes(seat_l) and not seat_l["goal_free"],
          ("the seat is blocked", da.verdict(seat_l)))
    lid = da.access(maps_l, rects_l[0], extra_blocks=[(378.0, 394.0, 92.0, 400.0)])
    check("drive_access: a wall across the rear opening (Y 378..394, from the bulkhead's top up) leaves no path, and the check fails", not da.passes(lid),
          ("no path (the seat is free, the way is not)", da.verdict(lid)))
    tight = da.access(maps_l, rects_l[1], tilts=(0.0, 10.0))
    check("drive_access: the plug-zone body does not get in with at most 10 degrees (the least tilt is 28, which is what the limit of 30 is measured against)", not da.passes(tight) and res_l[1]["least"] is not None and res_l[1]["least"] > 10.0,
          ("no path at 0 or 10 degrees, a path at the least tilt above 10", f"{da.verdict(tight)}; least tilt {res_l[1]['least']}"))
    cab_l = da.access(da.bay_maps(parts, hardware, {"test_cable": [(np.array([[-100.0, 240.0, 20.0], [-100.0, 330.0, 140.0]]), 6.0)]}, field, "left"), rects_l[0])
    check("drive_access: a cable of radius 6 across the left slot (from (-100, 240, 20) to (-100, 330, 140)) is in the grid: the seat is blocked", not cab_l["goal_free"] and not da.passes(cab_l),
          ("the seat is blocked", da.verdict(cab_l)))
    og = da.organic_gap(field, hardware, parts, "left")
    check("drive_access: the organic layer is at least HOT_GAP (10 mm) from the left drive, and nothing is reported", all(d_ >= da._hot_gap() for n_, d_ in og if n_ == "drive_left") and not da.gap_failures(og, "left"),
          ("every distance >= 10", ", ".join(f"{n_} {d_:.1f}" for n_, d_ in og)))
    near_field = dict(field, d=field["d"].copy())
    ix, iy, iz = (int(np.searchsorted(near_field[k_], v_)) for k_, v_ in (("xs", -125.0), ("ys", 300.0), ("zs", 80.0)))
    near_field["d"][ix:ix + 3, iy:iy + 3, iz:iz + 3] = -1.0                  # a lump of layer 6 mm outside the 3.5 inch drive's outer face (X -119.1)
    og2 = da.organic_gap(near_field, hardware, parts, "left")
    got = da.gap_failures(og2, "left")
    case("drive_access: a lump of the organic layer 5..8 mm from the left drive is reported (it must keep 10 mm)", "DRIVE_ACCESS left bay: the organic layer is ... mm from drive_left, it must keep 10", got, "DRIVE_ACCESS left bay", "drive_left", "it must keep 10")


@section("15. the 420: core and fans, check 14")
def s_rad420(hardware, parts, base):
    # 15. revision 11: the 420 is core + fans with a 3 mm gap, the hole table is the 125 mm pattern, and check 14 (the plates stay out of the fans' openings and keep the wall round every fan screw)
    solids = hardware["rad420"].Solids()
    gap = solids[0].distance(solids[1]) if len(solids) == 2 else float("nan")
    check("hardware: rad420 is two solids, the core and the fans, 3 mm apart (the plate's place)", len(solids) == 2 and abs(gap - (hw.RAD420_PLATE_U[1] - hw.RAD420_PLATE_U[0])) < 1e-6,
          ("2 solids, distance 3.000 mm", f"{len(solids)} solids, distance {gap:.3f} mm"))
    pitch = hw.FAN_P14["pitch"]
    want = sorted(c + k * pitch / 2 for c in hw.RAD420_FAN_X for k in (-1, 1))
    check("hardware: the 420's hole table is the fans' pattern (125.00 about each centre, rows 125.00 apart about the middle of the width)",
          len(hw.RAD420_HOLES_X) == 6 and all(abs(a - b) < 1e-9 for a, b in zip(sorted(hw.RAD420_HOLES_X), want)) and abs(hw.RAD420_HOLES_N[1] - hw.RAD420_HOLES_N[0] - pitch) < 1e-9
          and abs(sum(hw.RAD420_HOLES_N) / 2 - hw.RAD420_MID_N) < 1e-9 and pitch == 125.0,
          ("columns -202.5 -77.5 -62.5 62.5 77.5 202.5, rows -8.5 and 116.5", f"{list(hw.RAD420_HOLES_X)}, {list(hw.RAD420_HOLES_N)}"))
    op = hw.rad420_fan_opening(1, *hw.RAD420_PLATE_U)
    bb_op = board_box(op)
    check("hardware: a fan opening is a circle of 140 cut to 136 across the flats on both axes, about the fan's centre",
          abs((bb_op.xmax - bb_op.xmin) - 136.0) < 1e-6 and abs((bb_op.zmax - bb_op.zmin) - 136.0) < 1e-6 and abs(op.Volume() / (hw.RAD420_PLATE_U[1] - hw.RAD420_PLATE_U[0]) - 15216.0) < 1.0,
          ("136 x 136 box, area about 15216 mm2 (a 140 circle less four 2 mm segments)", f"{bb_op.xmax - bb_op.xmin:.3f} x {bb_op.zmax - bb_op.zmin:.3f}, area {op.Volume() / 3.0:.0f} mm2"))
    p4 = base["plates420"]
    check("  the undamaged antlers have no material in the fans' openings and 12 of 12 fan screws keep their wall", not [x for x in base["failures"] if x.startswith("CHECK14")]
          and all(v < f.VOL_EPS for _, _, v, _ in p4["openings"]) and len(p4["openings"]) == 6 and sum(1 for _, _, ok in p4["screws"] if ok) == len(p4["screws"]) == 12,
          ("6 antler x opening pairs with overlap < 1 mm3, 12 screws with their wall", f"{len(p4['openings'])} pairs, largest overlap {max(v for _, _, v, _ in p4['openings']):.3f} mm3; {sum(1 for _, _, ok in p4['screws'] if ok)} of {len(p4['screws'])} screws"))
    ant = part_named(parts, "antler_right")
    u0, u1 = f.ANTLER_U
    web = f.bsx(60.0, 80.0, u0, u1, hw.RAD420_MID_N - 5.0, hw.RAD420_MID_N + 5.0)         # a bar across the vertical web between the middle fan and the next one: 8 mm into each opening
    r = f.run_checks(hardware, with_part(parts, "antler_right", solid=ant.solid.fuse(web).clean(), blank=ant.blank.fuse(web).clean()), MEMO)
    case("antler_right with a bar across the web between two fans, into both openings", "CHECK14 antler_right has ... mm3 inside the opening of the 420's fan 1 (and fan 2)",
         r["failures"], "CHECK14 antler_right has", "inside the opening of the 420's fan 1")
    case("  same damage, the second opening", "CHECK14 antler_right has ... mm3 inside the opening of the 420's fan 2", r["failures"], "CHECK14 antler_right has", "opening of the 420's fan 2")
    h0 = next(h for h in ant.holes if abs(abs(float(np.dot(h.d, hw.U_DIR))) - 1.0) < 1e-6)       # a fan screw's hole, along u
    h2 = h0.moved(5.0, 0.0, 0.0)                                                               # a second hole 5 mm from it: 1.0 mm of wall between them (the wall rule is 1.6)
    damaged = with_part(parts, "antler_right", solid=ant.solid.cut(h2.solid), holes=ant.holes + [h2])
    r = f.run_checks(hardware, damaged, MEMO)
    case("antler_right: a second fan-screw hole 5 mm from the first, 1.0 mm of wall", "CHECK14 antler_right: the fan screw at (...) has no wall of 1.6 mm of plate round it",
         r["failures"], "CHECK14 antler_right: the fan screw", "no wall of 1.6 mm")
    case("  same damage, the hole check of check 7 says it too", "CHECK7 antler_right ... has wall 0.9x mm < 1.6 mm", r["failures"], "CHECK7 antler_right", "has wall", "< 1.6 mm")
    left = part_named(parts, "antler_left")
    refill = refilled(left, left.holes[0])           # one fan screw's hole of the left antler filled back in: check 5 and check 7 see it (check 14 measures the wall, not the bore)
    r = f.run_checks(hardware, with_part(parts, "antler_left", solid=refill), MEMO)
    case("antler_left with one fan-screw hole filled back in, check 5 counts 11 of 12", "CHECK5 rad420: 11 positions have a hole in the solids, the plan needs 12", r["failures"], "CHECK5 rad420: 11 positions")
    case("  same damage, check 7", "CHECK7 antler_left ... is not drilled", r["failures"], "CHECK7 antler_left", "is not drilled")
    web_l = f.mirror_x(web)                          # the same bar across the left web, between the middle fan and the left one
    r = f.run_checks(hardware, with_part(parts, "antler_left", solid=left.solid.fuse(web_l).clean(), blank=left.blank.fuse(web_l).clean()), MEMO)
    case("antler_left with a bar across the web between two fans, into both openings", "CHECK14 antler_left has ... mm3 inside the opening of the 420's fan 1 (and fan 0)",
         r["failures"], "CHECK14 antler_left has", "inside the opening of the 420's fan 1")
    case("  same damage, the outer fan's opening", "CHECK14 antler_left has ... mm3 inside the opening of the 420's fan 0", r["failures"], "CHECK14 antler_left has", "opening of the 420's fan 0")


@section("16. the antlers' webs and the fans' underside")
def s_antler_webs(hardware, parts, base):
    u0, u1 = f.ANTLER_U
    # 16. revision 11, second pass: the fans are 140 mm wide (the core 138), nothing of an antler is narrower than 2 mm, the chord keeps clear of the fans' underside
    core_s, fans_s = sorted(hardware["rad420"].Solids(), key=lambda s_: board_box(s_).ymin)      # the core (u 310..348), then the fans (u 351..378)
    fb, cb = board_box(fans_s), board_box(core_s)
    check("hardware: the 420's fans are 140 mm wide in n (-16..124), 1 mm more than the core (-15..123) on each long side, and ENVELOPE_N is the fans' top",
          abs(fb.zmin + 16.0) < 1e-6 and abs(fb.zmax - 124.0) < 1e-6 and abs(cb.zmin + 15.0) < 1e-6 and abs(cb.zmax - 123.0) < 1e-6 and hw.ENVELOPE_N == 124.0,
          ("fans n -16..124, core n -15..123, ENVELOPE_N 124", f"fans n {fb.zmin:.2f}..{fb.zmax:.2f}, core n {cb.zmin:.2f}..{cb.zmax:.2f}, ENVELOPE_N {hw.ENVELOPE_N:g}"))
    check("  the undamaged antlers have no web narrower than 2 mm, nothing within 1 mm below the fans' underside",
          all(w >= f.MIN_WEB - 0.1 for _, w, _, _ in base["plates420"]["webs"]) and len(base["plates420"]["webs"]) == 2
          and all(v < f.VOL_EPS for _, v in base["plates420"]["underside"]) and len(base["plates420"]["underside"]) == 2,
          ("2 antlers, narrowest web >= 1.9 mm, 2 antlers clear below the fans",
           f"webs {[round(w, 2) for _, w, _, _ in base['plates420']['webs']]}, underside {[round(v, 2) for _, v in base['plates420']['underside']]}"))
    ant = part_named(parts, "antler_right")
    cut1, cut2 = f.bsx(212.0, 217.0, u0 - 1.0, u1 + 1.0, 40.0, 80.0), f.bsx(218.0, 224.0, u0 - 1.0, u1 + 1.0, 40.0, 80.0)      # two slots in the end bar that leave a 1 mm web between them
    r = f.run_checks(hardware, with_part(parts, "antler_right", solid=ant.solid.cut(cut1).cut(cut2), blank=ant.blank.cut(cut1).cut(cut2)), MEMO)
    case("antler_right with two slots in its end bar that leave a 1 mm web", "CHECK14 antler_right has a web 1.0x mm wide at |X| 217..218, n 40..80: nothing of the plate may be narrower than 2 mm",
         r["failures"], "CHECK14 antler_right has a web", "nothing of the plate may be narrower than 2 mm")
    ml = part_named(parts, "antler_left")
    cut1l, cut2l = f.mirror_x(cut1), f.mirror_x(cut2)
    r = f.run_checks(hardware, with_part(parts, "antler_left", solid=ml.solid.cut(cut1l).cut(cut2l), blank=ml.blank.cut(cut1l).cut(cut2l)), MEMO)
    case("antler_left with the same two slots", "CHECK14 antler_left has a web 1.0x mm wide", r["failures"], "CHECK14 antler_left has a web", "nothing of the plate may be narrower than 2 mm")
    ridge = f.bsx(180.0, 200.0, 352.0, 376.0, f.ANTLER_N[0], hw.RAD420_FAN_N[0] - 0.5)          # a block on the chord that reaches to 0.5 mm below the fans' underside: 0.5 mm of clearance left, the gap is 1
    r = f.run_checks(hardware, with_part(parts, "antler_right", solid=ant.solid.fuse(ridge).clean(), blank=ant.blank.fuse(ridge).clean()), MEMO)
    case("antler_right with a block on the chord standing right up to the fans' underside", "CHECK14 antler_right has ... mm3 within 1 mm below the underside of the 420's fans (n -16)",
         r["failures"], "CHECK14 antler_right has", "below the underside of the 420's fans")


@section("17. screws, inserts, washers, counterbores")
def s_screws(hardware, parts, base):
    # 17. revision 12: every screw between printed parts is an M3 cap screw of the owner's, into an M3 insert; check 15 measures the stack and counts against the stock, check 16 the counterbores
    want = {16.0: 20, 8.0: 14, 10.0: 16, 12.0: 18, 34.0: 40, 20.0: 25, 6.0: 12, 25.0: 30, 3.0: 8, 5.0: 10, 4.3: 10}      # revision 14a: 4.3 is the carrier's stack (4 mm of floor and the pocket's 0.3)
    got_len = {k_: f.screw_fit(k_)[0] for k_ in want}
    check("screw_fit picks the owner's length for each stack the skeleton has (washer under the head)", got_len == want,
          (f"{want}", f"{got_len}"))
    check("  the board's screw (2 mm of PCB, no washer) is M3 x 6, entering 4 mm", f.screw_fit(2.0, washer=False)[:2] == (6, 4.0), ("(6, 4.0)", f"{f.screw_fit(2.0, washer=False)[:2]}"))
    check("  the lengths fit the rule: at least 3.5 mm into the insert, at least 0.5 mm short of the bottom, no relief bore needed anywhere",
          all(r_["entry"] >= hw.SCREW_ENGAGE_MIN - 1e-6 and r_["entry"] <= r_["depth"] - hw.SCREW_BOTTOM_GAP + 1e-6 and r_["relief"] == 0 for r_ in base["screws"]["rows"]) and len(base["screws"]["rows"]) == 102,      # revision 14a: 102 (was 96): the rest's 2, the carrier's 4, and the CPU guide's screw moved from the neck (stack 10) to the fan (stack 25)
          ("102 screws with a stack, all inside the rule, relief 0", f"{len(base['screws']['rows'])} screws, tightest margin {base['screws']['tightest']['margin']:.2f} mm"))
    check("  the counts stay inside four fifths of the stock: no length over, inserts under 176, washers under 304",
          all(n_ <= hw.STOCK_SHARE * hw.M3_SCREW_STOCK[L_] for L_, (n_, _) in base["screws"]["bill"].items()) and base["screws"]["inserts"] <= hw.STOCK_SHARE * hw.M3_INSERT_STOCK
          and base["screws"]["washers"] <= hw.STOCK_SHARE * hw.M3_WASHER_STOCK,
          ("every length, the inserts and the washers inside four fifths of the stock",
           f"bill {sorted((L_, n_) for L_, (n_, _) in base['screws']['bill'].items())}, inserts {base['screws']['inserts']}, washers {base['screws']['washers']}"))
    rb = part_named(parts, "rib_B_right")
    hp = next(h for h in rb.holes if h.pilot and h.item == "neck pad")
    wrong = [dataclasses.replace(h, stack=h.stack - 6.0) if h is hp else h for h in rb.holes]
    r = f.run_checks(hardware, with_part(parts, "rib_B_right", holes=wrong), MEMO)
    case("rib_B_right: a neck pad pilot made for a stack 6 mm shorter than the one the neck and pad make", "CHECK15 rib_B_right: ... the screw clamps 34.00 mm (neck_..), the pilot was made for 28 mm",
         r["failures"], "CHECK15 rib_B_right", "the screw clamps 34", "was made for 28")
    ra = part_named(parts, "rib_A_right")
    notch = hw.wbox(f.X_OUT - 2.0, f.X_OUT + 2.0, 5.0, 15.0, -30.0, -3.0)          # the rib's outer face cut away from 3 mm below the axis of the beam_front end screw at (Y 10, Z 0): the 7 mm washer hangs over it
    r = f.run_checks(hardware, with_part(parts, "rib_A_right", solid=ra.solid.cut(notch), blank=ra.blank.cut(notch)), MEMO)
    case("rib_A_right: the face under one beam_front screw's washer cut away on one side", "CHECK15 beam_front: ... the 7 mm washer under the head does not lie on the face of rib_A_right",
         r["failures"], "CHECK15 beam_front", "washer under the head does not lie on the face of rib_A_right")
    no_clear = part_named(parts, "neck_right")
    r = f.run_checks(hardware, with_part(parts, "neck_right", holes=[h for h in no_clear.holes if h.pilot or abs(h.start[1] - f.NECK_BOLTS[0][0]) > 1.0]), MEMO)
    case("neck_right without the clearance hole of one neck pad screw: nothing is clamped on the pilot's axis", "CHECK15 rib_B_right: ... nothing clamped on the screw's axis",
         r["failures"], "CHECK15 rib_B_right", "nothing clamped")
    with patched(hw, "M3_SCREW_STOCK", {**hw.M3_SCREW_STOCK, 20: 30}):
        r = f.run_checks(hardware, parts, MEMO)
    case("the owner has only 30 M3 x 20 (the 30 joints through the ribs need more than four fifths of that)", "CHECK15 M3 x 20: 30 needed, the owner has 30 and the model may use 0.8 of them (24)",
         r["failures"], "CHECK15 M3 x 20: 30 needed", "owner has 30")
    with patched(hw, "M3_INSERT_STOCK", 100):
        r = f.run_checks(hardware, parts, MEMO)
    case("the owner has 100 inserts (the model needs 104)", "CHECK15 104 M3 inserts needed, the owner has 100 and the model may use 0.8 of them (80)", r["failures"], "CHECK15 104 M3 inserts needed")
    with patched(hw, "M3_WASHER_STOCK", 100):
        r = f.run_checks(hardware, parts, MEMO)
    case("the owner has 100 washers (the model needs 93)", "CHECK15 93 M3 washers needed, the owner has 100", r["failures"], "CHECK15 93 M3 washers needed")
    with patched(hw, "M3_INSERT_LEN", 3.0):          # revision 15: the thread engaged is min(entry, the insert's length); an insert shorter than SCREW_ENGAGE_MIN fails every joint
        r = f.run_checks(hardware, parts, MEMO)
    case("the owner's inserts 3.0 mm long: no screw can engage 3.5 mm of thread", "CHECK15 beam_front: ... engages 3.00 mm of thread (the insert is 3 mm long), needs 3.5",
         r["failures"], "CHECK15 beam_front", "engages 3.00 mm of thread", "insert is 3 mm long")
    with patched(hw, "M3_SCREW_STOCK", {k_: v_ for k_, v_ in hw.M3_SCREW_STOCK.items() if k_ != 20}):
        r = f.run_checks(hardware, parts, MEMO)
        relief_set = f.joint_pilots((142.0, 10.0, 0.0), (-1, 0, 0), 16.0, "rib end")
    case("no M3 x 20 in the kit: the pilots built for it stop short of the bottom they now need (M3 x 25 enters 8.5 mm of a 6.7 mm hole)", "CHECK15 beam_front: ... M3 x 25 stops -1.80 mm from the bottom of the hole",
         r["failures"], "CHECK15 beam_front", "M3 x 25 stops -1.80 mm from the bottom")
    check("  the relief bore that case needs: a clearance-diameter bore under the pilot, 2.3 mm deep, so M3 x 25 stops 0.5 mm short of the bottom",
          len(relief_set) == 2 and relief_set[1].kind == "M3r" and abs((relief_set[1].length - 0.2) - 2.3) < 1e-6 and abs(relief_set[1].r * 2 - hw.M3_CLEAR_D) < 1e-9
          and abs(relief_set[1].point(0.2)[0] - (relief_set[0].point(relief_set[0].length)[0])) < 1e-9,
          ("pilot + M3r 2.3 mm (+ 0.2 overlap), diameter 3.4, starting at the pilot's bottom", f"{[(h_.kind, round(h_.length, 2)) for h_ in relief_set]}"))
    bulk = part_named(parts, "psu_bulkhead")
    cb = next(h for h in bulk.holes if h.kind == "6-32cb")
    deeper = f.cyl(cb.start, cb.d, 2 * cb.r, cb.length + 1.0)
    r = f.run_checks(hardware, with_part(parts, "psu_bulkhead", solid=bulk.solid.cut(deeper)), MEMO)
    case("psu_bulkhead: one counterbore cut 1 mm too deep (1 mm left under the head)", "CHECK16 psu_bulkhead: 6-32cb ... leaves 1.00 mm under the head, the plan leaves 2", r["failures"], "CHECK16 psu_bulkhead", "leaves 1.0", "plan leaves 2")
    arm = part_named(parts, "visor_arm_right")
    cba = next(h for h in arm.holes if h.kind == "6-32cb")
    deeper_a = f.cyl(cba.start, cba.d, 2 * cba.r, cba.length + 1.0)
    r = f.run_checks(hardware, with_part(parts, "visor_arm_right", solid=arm.solid.cut(deeper_a)), MEMO)
    case("visor_arm_right: one counterbore cut 1 mm too deep (1 mm left under the head)", "CHECK16 visor_arm_right: 6-32cb ... leaves 1.00 mm under the head, the plan leaves 2", r["failures"], "CHECK16 visor_arm_right", "leaves 1.0", "plan leaves 2")
    check("  the undamaged counterbores: 4 under the PSU's screws and 4 under the 360's (2 per arm), 2.0 mm of floor each, the screws (6.0 mm, both ASSUMPTIONS) entering 4.0 mm",
          len(base["counterbores"]) == 8 and all(abs(fl_ - 2.0) < 0.05 and abs(en_ - 4.0) < 0.05 for _, _, fl_, _, en_ in base["counterbores"]),
          ("8 rows, floor 2.0, entry 4.0", f"{len(base['counterbores'])} rows, floors {sorted({round(r_[2], 2) for r_ in base['counterbores']})}"))
    pads = [h_ for p_ in parts for h_ in p_.holes if h_.pilot and h_.item == "organic pad"]
    check("the organic layer's 12 pads each have an M3 pilot and a stack of the pad's height, so M3 x 10", len(pads) == 12 and all(h_.stack == hw.ORGANIC_PAD_H for h_ in pads) and f.screw_fit(hw.ORGANIC_PAD_H)[0] == 10,
          ("12 pilots, stack 5, M3 x 10", f"{len(pads)} pilots, stack {sorted({h_.stack for h_ in pads})}, M3 x {f.screw_fit(hw.ORGANIC_PAD_H)[0]}"))
    check("no M4 or M5 anywhere: the hole kinds are M3, M3c, 6-32c, M3r, 6-32cb, M3cb and the hardware has no M4 constant",
          {h_.kind for p_ in parts for h_ in p_.holes} <= {"M3", "M3c", "6-32c", "M3r", "6-32cb", "M3cb"} and not any("M4" in k_ or "M5" in k_ for k_ in vars(hw)) and set(hw.INSERTS) == {"M3"},
          ("only M3 kinds", f"{sorted({h_.kind for p_ in parts for h_ in p_.holes})}, inserts {sorted(hw.INSERTS)}"))


@section("18. the memo's keys: a number a measurement reads, changed after the memo holds the answer")
def s_memo_keys(hardware, parts, base):
    # The memo is keyed on the solids' identity and the numbers in `extra`. A number the measurement reads that is not in the key
    # lets a changed measurement return the stored answer (the review of the fast suite: a hole's r set to 20, or SPAN_MARGIN set to 5,
    # still passed check 16 from the memo while a call without a memo failed). Each case: the check passes warm (from the memo the
    # prelude filled), then with one number changed the call with the memo must report exactly what a call without a memo reports, a failure.
    def bites(name, tag, run, change, what):
        warm, remembered, fresh = [], [], []
        run(warm, MEMO)
        with change:
            run(remembered, MEMO)
            run(fresh, None)
        own = [x for x in fresh if x.startswith(tag)]
        check(name, not [x for x in warm if x.startswith(tag)] and own and remembered == fresh,
              (f"{tag} passes warm; with {what} the memo's answer equals a fresh call's, which fails",
               f"warm {len(warm)} failures; fresh {len(fresh)} ({'; '.join(own[:1])}); the memo's {'the same' if remembered == fresh else 'DIFFERENT: ' + '; '.join(remembered[:2])}"))

    cb_part, cb_hole = next((p_, h_) for p_ in parts for h_ in p_.holes if h_.kind == "M3cb")
    m3cb = lambda fl, m: f.check_m3_counterbores(parts, fl, m)      # noqa: E731
    bites(f"check 16 from the memo: {cb_part.name}'s counterbore with its r set to 20 in place", "CHECK16", m3cb, patched(cb_hole, "r", 20.0), "the hole's r 20")
    bites("check 16 from the memo: SPAN_MARGIN 5", "CHECK16", m3cb, patched(f, "SPAN_MARGIN", 5.0), "SPAN_MARGIN 5")
    sill_wall = lambda fl, m: f.check_sill_rear_wall(parts, fl, m)      # noqa: E731
    bites("check 22 from the memo: SPAN_MARGIN 5", "CHECK22", sill_wall, patched(f, "SPAN_MARGIN", 5.0), "SPAN_MARGIN 5")
    bites("check 22 from the memo: SPAN_STEP 100 (one sample at each end of the probe)", "CHECK22", sill_wall, patched(f, "SPAN_STEP", 100.0), "SPAN_STEP 100")
    post = part_named(parts, "gpu_post")
    holes7 = lambda fl, m: f.check_holes([post], fl, m)      # noqa: E731
    bites("check 7 from the memo: gpu_post's first hole 1 mm wider in place", "CHECK7", holes7, patched(post.holes[0], "r", post.holes[0].r + 1.0), "the hole's r + 1")
    bites("check 7 from the memo: BORE_SHRINK -1 (the bore's probe 1 mm wider than the bore)", "CHECK7", holes7, patched(f, "BORE_SHRINK", -1.0), "BORE_SHRINK -1")
    mounts = lambda fl, m: f.derive_mounts(parts, base["contacts"], fl, m)      # noqa: E731
    bites("check 5 from the memo: MOUNT_TOL -1 (no hole can match)", "CHECK5", mounts, patched(f, "MOUNT_TOL", -1.0), "MOUNT_TOL -1")

    # The board frame (third review of the fast suite): web_section places its plane with hw.bp and folds with un_of, plate_accept places an edge
    # with un_of, part_n_max reads hw.to_board, the guide's shadow hw.bs_of; all read hw.ORIGIN and hw.C when called. hw.U_DIR is computed at import,
    # so a key that carried only it returned the old plane and the old edge list. Each case: the answer warm, then with the frame changed the
    # remembered answer must equal a fresh one (no memo, or an emptied cache), and the fresh one must differ from the warm one (the change matters).
    def follows(name, run, change, what):
        warm = run(MEMO)
        with change:
            remembered, fresh = run(MEMO), run(None)
        check(name, remembered == fresh and fresh != warm,
              (f"with {what} the remembered answer equals a fresh call's, which differs from the answer before",
               f"before {str(warm)[:90]}; fresh {str(fresh)[:90]}; remembered {'the same' if remembered == fresh else 'DIFFERENT: ' + str(remembered)[:90]}"))

    o = hw.ORIGIN
    down = lambda: patched(hw, "ORIGIN", (o[0], o[1], o[2] - 100.0))      # noqa: E731 - every board-space n of a fixed solid grows by 100 / (2 C), u falls as much
    tilt = lambda: patched(hw, "C", math.cos(math.radians(40.0)))         # noqa: E731
    ants = [p_ for p_ in parts if p_.name.startswith("antler")]
    webs = lambda m: f.check_420_plates(ants, [], m)["webs"]      # noqa: E731
    follows("check 14's narrowest web from the memo: the board origin moved 100 mm down (the section's plane with it)", webs, down(), "hw.ORIGIN Z - 100")
    follows("check 14's narrowest web from the memo: hw.C of 40 deg (the section's plane and the fold to n)", webs, tilt(), "hw.C = cos 40 deg")
    sharp = lambda m: f.classify_corners(ants[0], f.rd.Neighbors([]), m)      # noqa: E731
    follows(f"the sharp edges from the memo ({ants[0].name}): the board origin moved 100 mm down (the tongue's rim edges count as corners)", sharp, down(), "hw.ORIGIN Z - 100")
    corners = lambda m: f.explain_corners(ants, hardware, m)      # noqa: E731
    follows("check 12's explained corners from the memo (the antlers): the board origin moved 100 mm down", corners, down(), "hw.ORIGIN Z - 100")
    sharp0 = lambda m: f.check_corners(ants, hardware, None, None, [], m)      # noqa: E731
    follows("check 12's counts from the memo, and the unrounded plates' counts: the board origin moved 100 mm down", sharp0, down(), "hw.ORIGIN Z - 100")
    follows("check 12's unrounded plates' counts (cached by name until this review): hw.C of 40 deg", sharp0, tilt(), "hw.C = cos 40 deg")
    n_max = lambda m: [f.part_n_max(p_) if m is not None else float(f.exact_box(hw.to_board(p_.solid))[5]) for p_ in ants]      # noqa: E731
    follows("check 8's highest n of a part (cached per solid): the board origin moved 100 mm down", n_max, down(), "hw.ORIGIN Z - 100")
    shadow = lambda m: f.check_guide_shadow(parts, []) if m is not None else _fresh_shadow(parts)      # noqa: E731
    follows("check 21's shadow of the hoses (cached per fan): hw.C of 40 deg", shadow, tilt(), "hw.C = cos 40 deg")


def _fresh_shadow(parts):
    """check 21 with the hoses' shadow cache emptied for the call (and put back after)."""
    with patched(f, "_SHADOW_TUBES", {}):
        return f.check_guide_shadow(parts, [])


@section("last: the undamaged model with nothing remembered")
def s_final(hardware, parts, base):
    # last: the undamaged model, once more with nothing remembered
    final = f.run_checks(hardware, parts)
    check("undamaged model reports no failure", not base["failures"] and not final["failures"],
          ("0 failures, first with an empty memo and again without a memo",
           f"{len(base['failures'])} and {len(final['failures'])}: {'; '.join((base['failures'] + final['failures'])[:3])}"))


# ---------------------------------------------------------------------------
# running: the sections in worker processes (default), or all in this process (--serial, as before)
# ---------------------------------------------------------------------------
WORKER_MB = 2000                # a worker's mean peak resident memory (17 Nov 2026, 6 workers: 0.85 GB for those that run no zone_access section, 2.8 to 4.1 GB for those that do; 10.6 to 12.5 GB together)
MEMORY_SHARE = 0.66             # the workers may hold this share of the machine's memory together (6 workers on the owner's 18 GB)


def _rss_mb():
    """Peak resident memory of this process, MB (ru_maxrss is bytes on macOS, kB on Linux)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0)


def _captured(fn, *args):
    """fn(*args) with its printed output captured: (value, record of text, cases, seconds, counts, error)."""
    buf, n0, c0, t0 = io.StringIO(), len(RESULTS), COUNTS.copy(), time.time()
    value, error = None, None
    with contextlib.redirect_stdout(buf):
        try:
            value = fn(*args)
        except Exception:
            error = traceback.format_exc()
    return value, dict(text=buf.getvalue(), results=RESULTS[n0:], seconds=time.time() - t0, counts=dict(COUNTS - c0), error=error)


_WORKER: dict = {}


def _worker_task(i):
    """In a worker process: the prelude on the first call, then section i (i = -1: the prelude's own output)."""
    first = "prelude" not in _WORKER
    if first:
        ctx, rec = _captured(prelude)
        _WORKER.update(ctx=ctx, prelude=rec, memo_keys=set(MEMO))
    pre = _WORKER["prelude"]
    if pre["error"]:
        rec = dict(text="", results=[], seconds=0.0, counts={}, error="the prelude failed in this worker:\n" + pre["error"])
    elif i < 0:
        rec = dict(pre)
    else:
        _, rec = _captured(SECTIONS[i][1], *_WORKER["ctx"])
        for k in [k for k in MEMO if k not in _WORKER["memo_keys"]]:       # what the section's damaged copies left: no other section has those objects, so it only holds memory
            del MEMO[k]
    rec.update(i=i, pid=os.getpid(), rss_mb=_rss_mb(), prelude_here=dict(seconds=pre["seconds"], counts=pre["counts"]) if first else None,
               sources=sorted(sr.loaded_sources()), modules=sorted(sr.loaded_top_levels()))
    return rec


WORKER_TASK = _worker_task      # what run_fast submits for each task; test_runner.py puts a fake in its place to drive the pool without the model


def default_workers(n_tasks):
    """As many workers as there are cores less one, as the memory allows (WORKER_MB each), and tasks need. Not from the last run's peaks: fewer workers each hold more, which would lower the count again."""
    total_mb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024.0 * 1024.0)
    return max(1, min((os.cpu_count() or 2) - 1, int(MEMORY_SHARE * total_mb // WORKER_MB), n_tasks))


def run_serial():
    """Everything in this process, printed as it runs: the suite as it ran before the sections."""
    records = []
    n0, c0, t0 = len(RESULTS), COUNTS.copy(), time.time()
    ctx = prelude()
    records.append(dict(title="prelude", seconds=time.time() - t0, counts=dict(COUNTS - c0), n_cases=len(RESULTS) - n0))
    for title, fn in SECTIONS:
        n0, c0, t0 = len(RESULTS), COUNTS.copy(), time.time()
        fn(*ctx)
        records.append(dict(title=title, seconds=time.time() - t0, counts=dict(COUNTS - c0), n_cases=len(RESULTS) - n0))
    return records, dict(rss_mb_per_worker={str(os.getpid()): _rss_mb()}, counts_all_processes=dict(COUNTS)), [], sr.loaded_sources(), sr.loaded_top_levels()


def run_fast(workers, previous):
    """The prelude once in each worker, the sections shared out longest first (the previous run's times), printed in their own order."""
    import concurrent.futures as cf
    import multiprocessing

    cost = {s["title"]: s["seconds"] for s in (previous or {}).get("sections", [])}
    order = [-1] + sorted(range(len(SECTIONS)), key=lambda i: -cost.get(SECTIONS[i][0], 0.0))
    records, errors, rss, all_counts, sources, modules = [], [], {}, collections.Counter(), sr.loaded_sources(), sr.loaded_top_levels()
    with cf.ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn")) as ex:
        futs = {i: ex.submit(WORKER_TASK, i) for i in order}
        for i in [-1] + list(range(len(SECTIONS))):
            title = "prelude" if i < 0 else SECTIONS[i][0]
            try:
                rec = futs[i].result()
            except Exception:                       # a worker died (BrokenProcessPool): every section it held is lost, and the run fails
                rec = dict(text="", results=[], seconds=0.0, counts={}, error=traceback.format_exc(), pid=None, rss_mb=0.0, prelude_here=None, sources=[], modules=[])
            sys.stdout.write(rec["text"])
            if rec["error"]:
                errors.append(f"{title}: {rec['error'].strip().splitlines()[-1]}")
                print(f"ERROR in section '{title}':\n{rec['error']}")
            sys.stdout.flush()
            RESULTS.extend(tuple(x) for x in rec["results"])
            records.append(dict(title=title, seconds=rec["seconds"], counts=rec["counts"], n_cases=len(rec["results"]), pid=rec["pid"]))
            if rec["pid"] is not None:
                rss[str(rec["pid"])] = max(rss.get(str(rec["pid"]), 0.0), rec["rss_mb"])
            sources.update(rec["sources"])
            modules.update(rec["modules"])
            all_counts.update(rec["counts"] if i >= 0 else {})
            if rec["prelude_here"]:
                all_counts.update(rec["prelude_here"]["counts"])
    return records, dict(rss_mb_per_worker=rss, counts_all_processes=dict(all_counts)), errors, sources, modules


def suite_counts(records):
    """The expensive operations the suite does, prelude once plus every section: the same in either mode and for any number of workers."""
    total = collections.Counter()
    for r in records:
        total.update(r["counts"])
    return {key: total.get(key, 0) for _m, _n, key in EXPENSIVE}


def load_record(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run_shortfall(rec):
    """Why a run's record is not the whole suite (sr.short_of_pin against EXPECTED_CASES as it is now): [] when whole."""
    return sr.short_of_pin(len(rec.get("cases", [])), [(s["title"], s["n_cases"]) for s in rec.get("sections", [])], EXPECTED_CASES)


def diff(path_a, path_b):
    """The two runs' case lists must be identical: same count, same order, each case's name, verdict, expected and reported text.
    Each must also be the whole suite: two runs that lost the same section are identical and still wrong."""
    ra, rb = load_record(path_a), load_record(path_b)
    a, b = ra["cases"], rb["cases"]
    keys = ("name", "ok", "expected", "reported")
    rows = [(k, x, y) for k, (x, y) in enumerate(zip(a, b)) if tuple(x[q] for q in keys) != tuple(y[q] for q in keys)]
    for k, x, y in rows[:10]:
        print(f"case {k + 1} differs:\n  {path_a}: {[x[q] for q in keys]}\n  {path_b}: {[y[q] for q in keys]}")
    short = [f"{path}: {why}" for path, rec in ((path_a, ra), (path_b, rb)) for why in run_shortfall(rec)]
    for line in short:
        print("SHORT  " + line)
    same = not rows and len(a) == len(b)
    print(f"{'IDENTICAL' if same else 'DIFFERENT'}: {len(a)} and {len(b)} cases, {len(rows)} differ in name, verdict, expected or reported text"
          + (f"; {len(short)} shortfall(s) against EXPECTED_CASES {EXPECTED_CASES}: FAILED" if short else ""))
    return 0 if same and not short else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--serial", action="store_true", help="run everything in this process, in order (as before the sections)")
    ap.add_argument("--workers", type=int, help="worker processes (default: cores less one, as memory allows)")
    ap.add_argument("--out", help="where to write the run's record (default out/test_checks/<fast|serial>.json)")
    ap.add_argument("--diff", nargs=2, metavar=("A", "B"), help="compare the case lists of two records and exit")
    args = ap.parse_args(argv)
    if args.diff:
        sys.exit(diff(*args.diff))
    mode = "serial" if args.serial else "fast"
    out = args.out or os.path.join(OUT_DIR, f"{mode}.json")
    prev_path = os.path.join(OUT_DIR, "fast.json")
    previous = load_record(prev_path) if os.path.exists(prev_path) else None
    workers = 1 if args.serial else (args.workers or default_workers(len(SECTIONS)))
    load_before = os.getloadavg()
    t_start = time.time()
    if args.serial:
        records, mem, errors, loaded, modules = run_serial()
    else:
        print(f"{len(SECTIONS)} sections in {workers} worker processes (each runs the prelude once); the output follows the sections' order\n")
        records, mem, errors, loaded, modules = run_fast(workers, previous)
    wall = time.time() - t_start
    sources = sr.sources_of(loaded, START_HASHES)       # each file as it was before the model was imported (START_HASHES)
    moved = sr.stale_sources(sources)                   # and now: a file that moved during the run may have been read as other bytes by a worker
    if moved:
        errors.append("a file the run read changed during the run, so the processes may have run different code: " + ", ".join(f"{r} {why}" for r, why in moved) + "; rerun")
        print("ERROR: " + errors[-1])
    env = sr.environment(modules)
    bad = [n for ok, n, _e, _r in RESULTS if not ok]
    short = sr.short_of_pin(len(RESULTS), [(r["title"], r["n_cases"]) for r in records], EXPECTED_CASES)
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} cases as expected   ({wall:.0f} s)"
          + (f"; EXPECTED_CASES is {EXPECTED_CASES}" if len(RESULTS) != EXPECTED_CASES else ""))
    if len(RESULTS) > EXPECTED_CASES and not short:
        print(f"{len(RESULTS) - EXPECTED_CASES} case(s) more than EXPECTED_CASES: raise it to {len(RESULTS)} in test_checks.py in the commit that adds them")
    rss = mem["rss_mb_per_worker"]
    print(f"{mode}: {workers} process(es), peak memory per process {max(rss.values()):.0f} MB, {sum(rss.values()):.0f} MB together; "
          f"expensive operations {suite_counts(records)}")
    sr.write_json_atomic(out, dict(mode=mode, workers=workers, wall_s=round(wall, 1), finished=time.strftime("%Y-%m-%d %H:%M:%S"), load_before=load_before, load_after=os.getloadavg(),
                                   total=len(RESULTS), passed=len(RESULTS) - len(bad), expected_cases=EXPECTED_CASES, short=short, errors=errors,
                                   counts=suite_counts(records), **mem, sources=sources, environment=env, digest=sr.digest(sources, env),
                                   sections=[dict(r, seconds=round(r["seconds"], 1)) for r in records],
                                   cases=[dict(name=n, ok=ok, expected=e, reported=r) for ok, n, e, r in RESULTS]))
    print(f"record: {os.path.relpath(out, ROOT)} ({len(sources)} files and {len(env['packages'])} packages in its digest, Python {env['python']})")
    if bad or errors or short:
        print("FAILED: " + "; ".join(bad + errors + short))
        sys.exit(1)


if __name__ == "__main__":
    main()
