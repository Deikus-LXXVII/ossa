#!/usr/bin/env python3
"""Prove that the organic layer's checks of revision 14b fail when the layer is wrong.

Loads the layer's saved field (out/organic/field.npz, written by organic_frame.py), damages a copy for each case and runs the check that should
catch it: organic_frame.field_checks (nothing beyond |X| 260, both rings whole, no material in io_zone, gpu_out_zone or the prism in front of the
card's outputs), organic_frame.bitten with ring_cut_failures (a ring cut by a carve), and zone_access (with the layer: a 40 mm bundle leaves each
zone; the hand that reaches the plug face of io_zone is not made smaller; an empty start or goal of the hand fails). The undamaged field must pass.

    .venv/bin/python cad_b6/test_organic.py            about two minutes (zone_access builds the skeleton and voxelises it)
    .venv/bin/python cad_b6/test_organic.py --quick    the field checks only, a few seconds

One line per case: PASS/FAIL, name, the failure that was expected, what was reported. Exit status 1 if any case fails.
"""
from __future__ import annotations

import os
import sys
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

import hardware as hw  # noqa: E402
import organic_frame as of  # noqa: E402

FIELD = os.path.join(os.path.dirname(HERE), "out", "organic", "field.npz")
RESULTS: list[tuple[bool, str]] = []


def first_match(failures, *needles):
    for line in failures:
        if all(n in line for n in needles):
            return line
    return None


def case(name, expected, failures, *needles):
    """Record PASS when a failure containing every needle was reported."""
    got = first_match(failures, *needles)
    RESULTS.append((got is not None, name))
    print(f"{'PASS' if got else 'FAIL'}  {name}\n      expected: {expected}\n      reported: "
          f"{got if got else 'NOTHING MATCHING (' + str(len(failures)) + ' other failures: ' + '; '.join(failures[:3]) + ')'}")


def check(name, ok, expected, reported):
    RESULTS.append((bool(ok), name))
    print(f"{'PASS' if ok else 'FAIL'}  {name}\n      expected: {expected}\n      reported: {reported}")


def grid_index(f, p):
    return tuple(int(round((c - g[0]) / (g[1] - g[0]))) for c, g in zip(p, (f["xs"], f["ys"], f["zs"])))


def ball_mask(f, centre, r):
    """(slices, mask) of the grid points within r of centre."""
    lo, hi = grid_index(f, np.array(centre) - r), grid_index(f, np.array(centre) + r)
    sl = tuple(slice(max(a, 0), b + 1) for a, b in zip(lo, hi))
    X, Y, Z = np.meshgrid(f["xs"][sl[0]], f["ys"][sl[1]], f["zs"][sl[2]], indexing="ij")
    return sl, (X - centre[0]) ** 2 + (Y - centre[1]) ** 2 + (Z - centre[2]) ** 2 <= r * r


def damaged(f, how):
    """A copy of the field dict with its d changed by how(d)."""
    g = dict(f)
    g["d"] = f["d"].copy()
    how(g)
    return g


def field_fails(g):
    return of.field_checks(g["d"], g["xs"], g["ys"], g["zs"])[1]


def put_material(g, box_bs):
    """Material (d = -1) at the grid points of a 6 mm cube at the centre of a board-space box."""
    c = [(box_bs[0] + box_bs[1]) / 2, (box_bs[2] + box_bs[3]) / 2, (box_bs[4] + box_bs[5]) / 2]
    sl, m = ball_mask(g, hw.bp(*c), 3.0)
    g["d"][sl][m] = -1.0


def field_cases(f):
    _lines, fails = of.field_checks(f["d"], f["xs"], f["ys"], f["zs"])
    check("the undamaged layer passes its field checks", not fails, "no failure", fails or "none")
    rings = of.ring_lines()

    def beyond(g):                                       # a lump 5 mm beyond the right fan's outer face, beside the ring
        p = rings["ring_R"][len(rings["ring_R"]) // 4]
        sl, m = ball_mask(g, (hw.ENVELOPE_FAN_X + 5.0, p[1], p[2]), 3.0)
        g["d"][sl][m] = -1.0
    case("material beyond |X| 260", "слой выходит за |X| 260", field_fails(damaged(f, beyond)), "слой выходит за |X|")

    def cut(g):                                          # the left ring cut through: a gap 16 mm long
        p = rings["ring_L"][len(rings["ring_L"]) // 3]
        sl, m = ball_mask(g, p, 8.0 + of.RING_R)
        g["d"][sl][m] = 1.0
    case("the left ring cut through", "кольцо ring_L не цело", field_fails(damaged(f, cut)), "кольцо ring_L не цело")

    def notch(g):                                        # the right ring notched 3.5 mm deep from outside, as a carve of GAP_HW from a 2 mm rod 9.5 mm from its axis would
        line = rings["ring_R"]
        i = len(line) // 2
        p, t = line[i], line[i + 1] - line[i - 1]
        w = np.cross(t, [1.0, 0.0, 0.0])
        w /= np.linalg.norm(w)
        c = p + 9.5 * w
        sl, m = ball_mask(g, c, 12.0)
        X, Y, Z = np.meshgrid(g["xs"][sl[0]], g["ys"][sl[1]], g["zs"][sl[2]], indexing="ij")
        rod = np.sqrt((Y - c[1]) ** 2 + (Z - c[2]) ** 2) - 2.0          # a rod along X through c
        g["d"][sl] = np.maximum(g["d"][sl], of.GAP_HW - rod)
    case("the right ring notched 3.5 mm deep", "кольцо ring_R не цело", field_fails(damaged(f, notch)), "кольцо ring_R не цело")
    for name, box in of.EMPTY_BOXES.items():
        case(f"material in {name}", f"слой стоит в {name}", field_fails(damaged(f, lambda g, b=box: put_material(g, b))), f"слой стоит в {name}")

    # the left ring cut through by a carve: bitten finds the run of its centre line outside the layer and ring_cut_failures makes it a failure (the full build's path)
    from types import SimpleNamespace
    _members, lines = of.bone_members()
    hware = {k: v for k, v in hw.build_hardware().items() if k in hw.FAN_SIDE_NAMES}
    whole = SimpleNamespace(d=f["d"], xs=f["xs"], ys=f["ys"], zs=f["zs"], vox=float(f["xs"][1] - f["xs"][0]))
    rings = {k: lines[k] for k in ("ring_L", "ring_R")}
    got = of.ring_cut_failures(of.bitten(whole, rings, [], hware))
    check("the undamaged rings are not cut (bitten)", not got, "no failure", got or "none")
    g = damaged(f, cut)
    cut_F = SimpleNamespace(d=g["d"], xs=g["xs"], ys=g["ys"], zs=g["zs"], vox=whole.vox)
    case("the left ring cut by a carve (bitten)", "кольцо ring_L перерезано", of.ring_cut_failures(of.bitten(cut_F, rings, [], hware)), "кольцо ring_L перерезано")

    # the bisections of the bundle and of the hand report the true largest value up to their limit, the limit included
    import zone_access as za
    bad = [(t, za.largest(lambda r, t=t: r <= t, 10, 60)) for t in range(0, 80) if za.largest(lambda r, t=t: r <= t, 10, 60) != (0 if t < 10 else min(t, 60))]
    check("largest(): the true largest radius from 10 up to the limit of 60, 0 below 10", not bad, "no mismatch for thresholds 0..79", bad or "none")


def zone_cases(f):
    import drive_access
    import frame_v0
    import zone_access as za
    hardware = hw.build_hardware()
    parts, _ = frame_v0.build_frame(hardware=hardware)
    strands, _ = drive_access.cable_strands()
    _l, fails, _r = za.run(parts=parts, hardware=hardware, strands=strands, field=f)
    check("zone_access with the undamaged layer passes", not fails, "no failure", fails or "none")

    def wall(g):                                         # across the hull behind both zones, no larger than the hull: between the fans' inner faces, up to the skeleton's top
        X = g["xs"][:, None, None]
        Y = g["ys"][None, :, None]
        Z = g["zs"][None, None, :]
        g0 = za.Grid(parts)
        g["d"][...] = np.where((np.abs(X) <= g0.x_hull) & (Y >= 300.0) & (Y <= 310.0) & (Z <= g0.z_hull), -1.0, g["d"])
    _l, fails, _r = za.run(parts=parts, hardware=hardware, strands=strands, field=damaged(f, wall))
    case("a layer wall behind the zones stops the 40 mm bundle (io_zone)", "ZONE_ACCESS io_zone: with the organic layer the widest bundle ... under Ø40", fails,
         "ZONE_ACCESS io_zone: with the organic layer the widest bundle")
    case("a layer wall behind the zones stops the 40 mm bundle (gpu_out_zone)", "ZONE_ACCESS gpu_out_zone: with the organic layer the widest bundle ... under Ø40", fails,
         "ZONE_ACCESS gpu_out_zone: with the organic layer the widest bundle")

    # the hand, checked by itself (hand_check, without the route search)
    _l, h_fails, h0 = za.hand_check(parts, hardware, strands, f, route=False)
    check("the hand with the undamaged layer: start and goal non-empty, a ball gets in without the layer, and with the layer it is not under its budget",
          not h_fails and h0[False]["d"] > 0 and h0[True]["d"] >= za.HAND_BUDGET_D, "no failure",
          f"{h_fails or 'none'}; Ø{h0[False]['d']} without, Ø{h0[True]['d']} with, budget Ø{za.HAND_BUDGET_D}")
    check("the hand's budget is what the layer gives today and not above what the skeleton alone allows (a budget moved by hand shows here)",
          h0[True]["d"] == za.HAND_BUDGET_D <= h0[False]["d"], f"Ø{za.HAND_BUDGET_D}", f"Ø{h0[True]['d']} with the layer, Ø{h0[False]['d']} without")
    b = za.ZONE_BS[za.HAND_ZONE]
    (u0, u1), n0 = hw.FAN_SIDE_U, hw.FAN_SIDE_N[0]
    plate = (hw.x_to_v(hw.FAN_SIDE_INNER_X["fan_side_left"]), b[0], u0, u1, n0, n0 + 6.0)

    def slot_plate(g):                                   # a plate 6 mm thick across the slot between the left fan's inner face and the plug face, at the fan's lower edge, inside its footprint in u
        g["d"][of.bs_box_mask(g["xs"], g["ys"], g["zs"], plate)] = -1.0
    _l, fz, h1 = za.hand_check(parts, hardware, strands, damaged(f, slot_plate), route=False)
    case(f"a plate across the slot under the left fan (v {plate[0]:g}..{plate[1]:g}, u {u0:g}..{u1:g}, n {n0:g}..{n0 + 6:g}) makes the hand smaller",
         "ZONE_ACCESS hand: the organic layer makes the widest hand smaller", fz, "ZONE_ACCESS hand: the organic layer makes the widest hand smaller")
    check("... and the number drops below the undamaged layer's", h1[True]["d"] < h0[True]["d"], f"under Ø{h0[True]['d']}", f"Ø{h1[True]['d']}")
    goal = (b[0] - za.HAND_NEAR, b[0], b[2], b[3], b[4], b[5])

    def goal_block(g):                                   # material only where the hand's centre has to arrive: in front of the plug face, within the zone's u and n
        g["d"][of.bs_box_mask(g["xs"], g["ys"], g["zs"], goal)] = -1.0
    _l, fz, _h = za.hand_check(parts, hardware, strands, damaged(f, goal_block), route=False)
    case("material that fills only the plug-face goal", "ZONE_ACCESS hand with the layer: the goal in front of the plug face of io_zone is empty", fz,
         "ZONE_ACCESS hand with the layer: the goal in front of the plug face", "is empty")
    with patched(za, "HAND_NEAR", -2.0):                 # a goal with no grid point: v at or below the face and at least 2 mm inside it
        _l, fz, _h = za.hand_check(parts, hardware, strands, f, route=False)
    case("an empty goal is a failure, not a pass", "ZONE_ACCESS hand: the goal in front of the plug face of io_zone is empty", fz, "ZONE_ACCESS hand: the goal in front of the plug face", "is empty")
    with patched(za, "HAND_ROOM", 0.0):                  # the hand's grid ends at the left fan's outer face, so no ball lies wholly beyond it
        _l, fz, _h = za.hand_check(parts, hardware, strands, f, route=False)
    case("an empty start is a failure, not a pass", "ZONE_ACCESS hand: the start beyond the left fan's outer face is empty", fz, "ZONE_ACCESS hand: the start beyond the left fan's outer face is empty")
    case("... and so is a hand that cannot get in without the layer", "ZONE_ACCESS hand: without the organic layer no ball", fz, "ZONE_ACCESS hand: without the organic layer no ball")


class patched:
    """Set a module attribute for the length of a with-block."""
    def __init__(self, mod, name, value):
        self.mod, self.name, self.value = mod, name, value

    def __enter__(self):
        self.old = getattr(self.mod, self.name)
        setattr(self.mod, self.name, self.value)

    def __exit__(self, *exc):
        setattr(self.mod, self.name, self.old)


def main():
    path = next((a for a in sys.argv[1:] if not a.startswith("--")), FIELD)
    if not os.path.exists(path):
        sys.exit(f"{path} is missing: run cad_b6/organic_frame.py first")
    z = np.load(path)
    f = dict(d=z["d"], xs=z["xs"], ys=z["ys"], zs=z["zs"])
    field_cases(f)
    if "--quick" not in sys.argv:
        zone_cases(f)
    bad = [n for ok, n in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(bad)} of {len(RESULTS)} cases pass" + ("" if not bad else ": FAILING " + "; ".join(bad)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
