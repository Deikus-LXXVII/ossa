#!/usr/bin/env python3
"""Prove that the organic layer's checks of revision 14b fail when the layer is wrong.

Loads the layer's saved field (out/organic/field.npz, written by organic_frame.py), damages a copy for each case and runs the check that should
catch it: organic_frame.field_checks (nothing beyond |X| 260, both rings whole, no material in io_zone, gpu_out_zone or the prism in front of the
card's outputs) and zone_access.run (with the layer: a 40 mm bundle leaves each zone, the hand is not made smaller). The undamaged field must pass.

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


def zone_cases(f):
    import drive_access
    import frame_v0
    import zone_access as za
    hardware = hw.build_hardware()
    parts, _ = frame_v0.build_frame(hardware=hardware)
    strands, _ = drive_access.cable_strands()
    _l, fails, _r = za.run(parts=parts, hardware=hardware, strands=strands, field=f)
    check("zone_access with the undamaged layer passes", not fails, "no failure", fails or "none")

    def walls(g):
        X = g["xs"][:, None, None]
        Y = g["ys"][None, :, None]
        g["d"][...] = np.where((np.abs(X) <= za.Grid(parts).x_hull) & (Y >= 300.0) & (Y <= 310.0), -1.0, g["d"])     # across the hull behind both zones
        Z = g["zs"][None, None, :]
        g["d"][...] = np.where((X <= -165.0) & (Y >= 100.0) & (Y <= 300.0) & (Z <= 140.0), -1.0, g["d"])     # a block under the left fan, where the hand's ways in pass
    _l, fails, _r = za.run(parts=parts, hardware=hardware, strands=strands, field=damaged(f, walls))
    case("a layer wall behind the zones stops the 40 mm bundle (io_zone)", "ZONE_ACCESS io_zone: with the organic layer the widest bundle ... under Ø40", fails,
         "ZONE_ACCESS io_zone: with the organic layer the widest bundle")
    case("a layer wall behind the zones stops the 40 mm bundle (gpu_out_zone)", "ZONE_ACCESS gpu_out_zone: with the organic layer the widest bundle ... under Ø40", fails,
         "ZONE_ACCESS gpu_out_zone: with the organic layer the widest bundle")
    case("a layer wall outside the left flank makes the hand smaller", "ZONE_ACCESS hand: the organic layer makes the widest hand smaller", fails,
         "ZONE_ACCESS hand: the organic layer makes the widest hand smaller")
    case("... and the plugs' side hand too", "ZONE_ACCESS hand (plugs side): the organic layer makes the widest hand smaller", fails,
         "ZONE_ACCESS hand (plugs side): the organic layer makes the widest hand smaller")


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
