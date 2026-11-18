#!/usr/bin/env python3
"""Prove that the organic layer's checks of revision 14b fail when the layer is wrong.

Loads the layer's saved field (out/organic/field.npz, written by organic_frame.py), damages a copy for each case and runs the check that should
catch it: organic_frame.field_checks (nothing beyond |X| 260, both rings whole, no material in io_zone, gpu_out_zone or the prism in front of the
card's outputs), organic_frame.bitten with ring_cut_failures (a ring cut by a carve), and zone_access (with the layer: a 40 mm bundle leaves each
zone; the hand that reaches the plug face of io_zone is not made smaller; an empty start or goal of the hand fails). The undamaged field must pass.

    .venv/bin/python cad_b6/test_organic.py            about two minutes (zone_access builds the skeleton and voxelises it)
    .venv/bin/python cad_b6/test_organic.py --quick    the field checks only, a few seconds

Revision 17: the checks of the layer's pieces (organic_frame.piece_checks: the arrays' layout, each piece one body holding its pads, the pieces GAP_PIECE apart, a piece
other than `main` fits the bed standing and turned about the vertical, nothing of the layer in front of psu_bulkhead's screw heads), each on a damaged copy of the saved
arrays; organic_manifest.py (a moved voxel of `main` is named, a piece in --expect may differ, no manifest is exit 2, an empty piece is not fingerprinted); and in the
full run organic_strength.load_failures (the own weight judged with the pushes).

One line per case: PASS/FAIL, name, the failure that was expected, what was reported. Exit status 1 if any case fails, or if the number of cases is not EXPECTED_CASES.
"""
from __future__ import annotations

import math
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
# The number of cases a run records, pinned so that a reviewer sees it change in the diff that adds or removes cases (quick: the field and piece cases only).
EXPECTED_CASES = {"quick": 43, "full": 65}       # revision 18: 32 and 51 before; the plug's room, the four new checks of the saved arrays, the cross-threads' rule, and in the full run the probes' solver cases
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


def damaged_piece(f, piece, how):
    """A copy of the field dict with the field of `piece` (d_<piece>) changed by how(d)."""
    g = dict(f)
    g["d_" + piece] = f["d_" + piece].copy()
    how(g["d_" + piece])
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


def piece_cases(f):
    """Revision 17: the checks of the pieces on damaged copies of the saved arrays."""
    pieces = [str(p) for p in f["pieces"]]
    lines, fails, _joined = of.piece_checks(f)
    check("the undamaged pieces pass: main and rear_panel, each one body holding its pads, apart, the panel on the bed, six screw heads free",
          not fails and pieces == ["main", "rear_panel"] and len(f["heads"]) == 6, "no failure; pieces main, rear_panel; 6 heads", f"{fails or 'none'}; pieces {pieces}; {len(f['heads'])} heads")
    xs, ys, zs = f["xs"], f["ys"], f["zs"]

    def split(d):                                        # a slot 6 mm wide through the panel at X 0, over its whole height and depth
        d[np.abs(xs) <= 3.0] = np.maximum(d[np.abs(xs) <= 3.0], 1.0)
    case("the rear panel cut in two at X 0", "ORGANIC_PIECES rear_panel is not one body", of.body_checks(damaged_piece(f, "rear_panel", split))[1], "ORGANIC_PIECES rear_panel is not one body")
    names = [str(n) for n in f["names"]]
    i = names.index("panel_hip_R")
    q, n = f["pads"][i][:3], f["pads"][i][3:]

    def unpad(d):                                        # the pad's disc and knot taken away: nothing of the panel within 12 mm of the disc's middle
        sl, m = ball_mask(f, q + n * of.PAD_H / 2, 12.0)
        d[sl] = np.where(m, np.maximum(d[sl], 1.0), d[sl])
    case("the panel's pad panel_hip_R with its disc and knot gone", "ORGANIC_PIECES panel_hip_R: the pad is not joined to the body of the piece rear_panel",
         of.body_checks(damaged_piece(f, "rear_panel", unpad))[1], "ORGANIC_PIECES panel_hip_R: the pad is not joined")
    idx = np.argwhere(f["d_main"] < 0)
    a = idx[np.argmax(idx[:, 1])]                        # main's rearmost voxel; the one behind it is outside main

    def touch(d):                                        # one voxel of the panel right behind it: voxel centres 1.5 mm apart, the solids touch
        d[a[0], a[1] + 1, a[2]] = -1.0
    case(f"a voxel of the panel touching main (behind its rearmost voxel at X {xs[a[0]]:.1f}, Y {ys[a[1]]:.1f}, Z {zs[a[2]]:.1f})",
         "ORGANIC_PIECES main and rear_panel are 0.00 mm apart ..., they must keep 3 less one voxel", of.gap_checks(damaged_piece(f, "rear_panel", touch))[1],
         "ORGANIC_PIECES main and rear_panel are 0.00 mm apart", "less one voxel")
    # the bed (revision 17, second step): the panel stands as built and is turned about the vertical; it fits when some whole degree fits
    lim, vox = of.frame_v0.MAX_PART, float(xs[1] - xs[0])
    fit0 = of.bed_fit(f["d_rear_panel"], xs, ys, zs)
    check("today's rear panel fits the bed standing and turned, at about 45 degrees (it is wider than the bed along X)",
          fit0["any_fits"] and fit0["fits"] and min(abs(fit0["angle"] - 45), abs(fit0["angle"] - 135)) <= 10 and of.piece_extents(f["d_rear_panel"], xs, ys, zs)[0][1]
          - of.piece_extents(f["d_rear_panel"], xs, ys, zs)[0][0] > lim and not any("rear_panel" in x for x in of.bed_checks(f)[1]),
          f"fits at 45 +- 10 (or 135 +- 10) degrees, X over {lim:g}, no failure",
          f"{fit0['angle']} degrees: {fit0['u']:.1f} x {fit0['v']:.1f}, {fit0['height']:.1f} tall; failures {of.bed_checks(f)[1] or 'none'}")
    pidx = np.argwhere(f["d_rear_panel"] < 0)
    b = pidx[np.argmax(pidx[:, 0])]                      # the panel's rightmost voxel

    def lump(k):                                         # a lump of k voxels on the panel's right end, along +X from its rightmost voxel
        def how(d):
            d[b[0]:b[0] + k + 1, b[1], b[2]] = -1.0
        return damaged_piece(f, "rear_panel", how)

    def fits_with(k):
        return of.bed_fit(lump(k)["d_rear_panel"], xs, ys, zs)["any_fits"]
    lo_k, hi_k = 0, 1                                    # the shortest lump that no whole degree fits (the extents only grow with k): bisection
    while fits_with(hi_k) and hi_k < len(xs) - b[0] - 1:
        lo_k, hi_k = hi_k, 2 * hi_k
    while hi_k - lo_k > 1:
        mid = (lo_k + hi_k) // 2
        lo_k, hi_k = (mid, hi_k) if fits_with(mid) else (lo_k, mid)
    fit_k = of.bed_fit(lump(hi_k)["d_rear_panel"], xs, ys, zs)
    got = of.bed_checks(lump(hi_k))[1]
    # the old case (first build: a lump 6 mm beyond the right end took the X extent from 289.5 to 295.5, 5.5 over the bed) rewritten to the same strictness: the shortest
    # lump on the end that no angle fits fails the check, one voxel shorter passes it, and it fails by less than two voxels
    check(f"a lump on the rear panel's right end: {hi_k * vox:.1f} mm, the shortest that no whole degree fits, fails the bed; {lo_k * vox:.1f} mm passes",
          fits_with(lo_k) and not fit_k["any_fits"] and max(fit_k["u"], fit_k["v"]) <= lim + 2 * vox
          and first_match(got, "ORGANIC_PIECES rear_panel does not fit the bed at any whole degree") is not None,
          f"fails at {hi_k} voxels by under {2 * vox:g} mm, passes at {lo_k}",
          f"{fit_k['angle']} degrees: {fit_k['u']:.2f} x {fit_k['v']:.2f}; {first_match(got, 'ORGANIC_PIECES rear_panel') or 'NOTHING'}")
    # a turned voxel is wider than a voxel: a straight row whose centres span 408 mm measures 290.00 at 45 degrees by "span plus one voxel" and 290.62 by its cubes
    row = np.full(f["d_rear_panel"].shape, 1.0, dtype=np.float32)
    n_row = int(round(408.0 / vox)) + 1
    row[10:10 + n_row, 100, 100] = -1.0
    fit_row = of.bed_fit(row, xs, ys, zs)
    check(f"a straight row of {n_row} voxels (centres {(n_row - 1) * vox:g} mm apart end to end) is over the bed at every angle once the voxels' own width when turned is counted",
          not fit_row["any_fits"] and abs(max(fit_row["u"], fit_row["v"]) - ((n_row - 1) * vox + 2 * vox) * math.sqrt(0.5)) < 0.01,
          f"fits no angle; at 45 degrees {((n_row - 1) * vox + 2 * vox) * math.sqrt(0.5):.2f} mm", f"{fit_row['angle']} degrees: {fit_row['u']:.2f} x {fit_row['v']:.2f}, fits {fit_row['any_fits']}")
    fy = int(pidx[:, 1].min())
    iy = int(np.searchsorted(ys, ys[fy] - 260.0))
    bz = pidx[np.argmin(pidx[:, 1])]

    def longer(d):                                       # the panel lengthened 260 mm forward (along -Y) from its frontmost voxel: 321 wide and about 305 deep fits no angle
        d[bz[0], iy:fy + 1, bz[2]] = -1.0
    g = damaged_piece(f, "rear_panel", longer)
    fit_y = of.bed_fit(g["d_rear_panel"], xs, ys, zs)
    case(f"the rear panel lengthened 260 mm along -Y (at best {fit_y['angle']} degrees: {fit_y['u']:.0f} x {fit_y['v']:.0f})",
         "ORGANIC_PIECES rear_panel does not fit the bed at any whole degree about the vertical", of.bed_checks(g)[1],
         "ORGANIC_PIECES rear_panel does not fit the bed at any whole degree")
    tz = pidx[np.argmax(pidx[:, 2])]
    top = int(np.searchsorted(zs, zs[int(pidx[:, 2].min())] + lim + 3 * vox))

    def taller(d):                                       # a strand up from the panel's topmost voxel until it is 290 + 3 voxels tall, standing as built
        d[tz[0], tz[1], tz[2]:top + 1] = -1.0
    g = damaged_piece(f, "rear_panel", taller)
    case(f"the rear panel made {of.bed_fit(g['d_rear_panel'], xs, ys, zs)['height']:.1f} mm tall (it is printed standing)",
         "ORGANIC_PIECES rear_panel does not fit the bed ... tall", of.bed_checks(g)[1] if top < len(zs) else ["the grid is too low for this case"],
         "ORGANIC_PIECES rear_panel does not fit the bed at any whole degree", "mm tall")
    ext = of.piece_extents(f["d_main"], xs, ys, zs)
    check("main, which is not split yet, is wider than the bed and is reported, not failed", max(hi - lo for lo, hi in ext) > of.frame_v0.MAX_PART and not of.bed_checks(f)[1]
          and any("main" in l_ and "не проверяется" in l_ for l_ in of.bed_checks(f)[0]), f"main over {of.frame_v0.MAX_PART:g}, no failure, a report line",
          f"main {max(hi - lo for lo, hi in ext):.1f} mm; failures {of.bed_checks(f)[1] or 'none'}")
    h0 = f["heads"][0]

    def in_head(d):                                      # a lump of the panel 20 mm behind the first screw head, on its axis
        sl, m = ball_mask(f, h0[:3] + h0[3:] * 10.0, 2.0)
        d[sl] = np.where(m, -1.0, d[sl])
    case(f"a lump of the panel 10 mm behind the screw head at X {h0[0]:.1f}, Z {h0[2]:.1f}", "ORGANIC_PIECES rear_panel has ... voxels in the way of the screw head",
         of.head_checks(damaged_piece(f, "rear_panel", in_head))[1], "ORGANIC_PIECES rear_panel has", "in the way of the screw head")
    case("no screw head found on the bulkhead is a failure, not a pass", "ORGANIC_PIECES no screw head found", of.head_checks(dict(f, heads=np.zeros((0, 6))))[1],
         "ORGANIC_PIECES no screw head found")
    off = np.array([[0.0, float(ys[-1]) + 100.0, 50.0, 0.0, 1.0, 0.0]])
    case("a screw head whose cylinder lies off the grid is a failure, not a pass", "ORGANIC_PIECES the cylinder behind the head ... has no grid point",
         of.head_checks(dict(f, heads=off))[1], "ORGANIC_PIECES the cylinder behind the head", "has no grid point")
    # the arrays' layout (revision 17, second step): each check of the pieces passes when it has nothing to judge, so piece_checks fails first
    case("a field with no piece is a failure, not a pass", "ORGANIC_PIECES the field has no piece", of.piece_checks(dict(f, pieces=np.array([], dtype=str)))[1],
         "ORGANIC_PIECES the field has no piece")
    sm = np.argwhere(f["d_main"] < 0)[0]

    def unmin(g):                                        # one voxel of main taken out of d only: d is no longer the minimum of the pieces' fields
        g["d"][tuple(sm)] = 1.0
    case(f"d with one voxel of main taken out (X {xs[sm[0]]:.1f}, Y {ys[sm[1]]:.1f}, Z {zs[sm[2]]:.1f}), the pieces' fields as they are",
         "ORGANIC_PIECES d is not the minimum of the pieces' fields: 1 voxels differ", of.piece_checks(damaged(f, unmin))[1],
         "ORGANIC_PIECES d is not the minimum of the pieces' fields: 1 voxels differ")
    case(f"the last pad ({names[-1]}) without its piece in pad_piece", f"ORGANIC_PIECES the pad {names[-1]} names no piece",
         of.piece_checks(dict(f, pad_piece=f["pad_piece"][:-1]))[1], f"ORGANIC_PIECES the pad {names[-1]} names no piece")
    case("a field that names the piece main and holds no d_main", "ORGANIC_PIECES the field names the piece main but has no field d_main",
         of.piece_checks({k: f[k] for k in f if k != "d_main"})[1], "ORGANIC_PIECES the field names the piece main but has no field d_main")


def solid_at(g, centre, r, piece="main"):
    """Material (d = -1) in the field of `piece` and in the union d at the grid points within r of centre (the nearest grid point at least)."""
    g["d_" + piece] = g["d_" + piece].copy()
    g["d"] = g["d"].copy()
    sl, m = ball_mask(g, centre, r)
    if not m.any():
        idx = grid_index(g, centre)
        sl, m = tuple(slice(i, i + 1) for i in idx), np.ones((1, 1, 1), dtype=bool)
    for k in ("d_" + piece, "d"):
        blk = g[k][sl]
        blk[m] = -1.0
        g[k][sl] = blk
    return g


def revision18_cases(f):
    """Revision 18's checks of the saved arrays (organic_frame.layer_clearance_checks): the carrier comes out (C.6), no layer in a pad's pilot (C.8), no cable or hose in the layer (H.6),
    no layer in a screw's head (J.3); and the cross-threads' rule reads organic_strength's push and allowable (C.7)."""
    from scipy.spatial import cKDTree
    _l, fails = of.layer_clearance_checks(f)
    check("the undamaged layer passes revision 18's checks (the carrier's way, the pads' pilots, the cables and hoses, the screws' heads)", not fails, "no failure", fails or "none")
    b = f["carrier_box"]
    front = ((b[0] + b[1]) / 2, b[2] - 5.0, (b[4] + b[5]) / 2)          # a lump 5 mm in front of the module's face, in the carrier's way out
    case(f"a lump in front of the module's face (X {front[0]:.1f}, Y {front[1]:.1f}, Z {front[2]:.1f})", "ORGANIC_CARRIER main has ... voxels in the way the carrier slides out",
         of.carrier_checks(solid_at(dict(f), front, 2.0))[1], "ORGANIC_CARRIER main has", "in the way the carrier slides out")
    names = [str(n) for n in f["names"]]
    i = names.index(next(n for n, p in zip(names, f["pad_piece"]) if str(p) == "main"))
    q, n = f["pads"][i][:3], f["pads"][i][3:]
    mouth = q - 1.0 * n                                                   # 1 mm into the insert's pilot, on its axis
    case(f"a voxel in the mouth of {names[i]}'s pilot", f"ORGANIC_PILOT main has ... voxels in the insert pilot of the pad {names[i]}",
         of.pilot_checks(solid_at(dict(f), mouth, 0.1))[1], "ORGANIC_PILOT main has", f"pilot of the pad {names[i]}")
    no_pads = {**dict(f), "pads": np.zeros((0, 6)), "names": np.array([], dtype=str)}
    case("a field saved with no pad", "ORGANIC_PILOT no pad saved with the field: nothing is checked", of.pilot_checks(no_pads)[1], "ORGANIC_PILOT no pad saved", "nothing is checked")
    lines = of.strands_of(f)
    card = next(l for l in lines if l[0].startswith("cable gpu12v"))
    p = card[1][len(card[1]) // 2]
    case(f"a lump on the card's power cable's line (X {p[0]:.1f}, Y {p[1]:.1f}, Z {p[2]:.1f})", "ORGANIC_STRANDS cable gpu12v[...]: ... points of its centre line are nearer the layer",
         of.strand_checks(solid_at(dict(f), p, 3.0))[1], "ORGANIC_STRANDS cable gpu12v", "nearer the layer")
    hose = next(l for l in lines if l[0].startswith("hose"))
    k = 4 * (len(hose[1]) // 8) + 2                                       # half way between two of the points the layer was carved from until revision 18 (every fourth)
    t = hose[1][k + 1] - hose[1][k - 1]
    w = np.cross(t, (0.0, 0.0, 1.0)) if abs(t[2]) < 0.9 * np.linalg.norm(t) else np.cross(t, (1.0, 0.0, 0.0))
    w /= np.linalg.norm(w)
    at = hose[1][k] + w * (hose[2] + 1.0)                                 # 1 mm off the hose's surface, inside GAP_HW
    case(f"a voxel 1 mm off {hose[0]} between two of its every-fourth points (point {k})", f"ORGANIC_STRANDS {hose[0]}: ... nearer the layer than its radius and {of.GAP_HW:g} mm",
         of.strand_checks(solid_at(dict(f), at, 0.1))[1], f"ORGANIC_STRANDS {hose[0]}", "nearer the layer")
    # a wall whose nearest voxel centres stand at the clearance passes; the same wall one voxel closer fails. On a field holding the wall alone and one strand alone
    name, line, r, gap = next(l for l in lines if l[0] == "cable usb3[0]")
    samp = of.densify(line, 1.0)
    tree = cKDTree(samp)
    j = len(samp) // 2
    t = samp[j + 1] - samp[j - 1]
    ax = int(np.argmin(np.abs(t)))                                        # the grid axis most across the cable there
    sgn = 1
    c = list(grid_index(f, samp[j]))
    xs3 = (f["xs"], f["ys"], f["zs"])

    def wall(m):
        idx = []
        o = [a for a in range(3) if a != ax]
        for da in range(-3, 4):
            for db in range(-3, 4):
                ii = list(c)
                ii[ax] += sgn * m
                ii[o[0]] += da
                ii[o[1]] += db
                idx.append(tuple(ii))
        return np.array(idx)

    def centres(idx):
        return np.stack([np.asarray(xs3[a], dtype=float)[idx[:, a]] for a in range(3)], axis=1)

    m0 = next(m for m in range(1, 40) if tree.query(centres(wall(m)))[0].min() - r >= gap - 1e-9)
    near = tree.query(centres(wall(m0)))[0].min() - r

    def only_wall(m):
        g = dict(f)
        for piece in [str(x) for x in f["pieces"]]:
            g["d_" + piece] = np.ones_like(f["d_" + piece])
        idx = wall(m)
        g["d_main"][tuple(idx.T)] = -1.0
        g["d"] = np.minimum.reduce([g["d_" + str(x)] for x in f["pieces"]])
        g.update(of.strand_arrays([(name, line, r, gap)]))
        return g
    got = of.strand_checks(only_wall(m0))[1]
    check(f"a wall whose nearest voxel centres stand {near:.2f} mm off {name}'s surface (clearance {gap:g}) passes", not got, "no failure", got or "none")
    case(f"  the same wall one voxel closer ({tree.query(centres(wall(m0 - 1)))[0].min() - r:.2f} mm) fails", f"ORGANIC_STRANDS {name}: ... nearer the layer",
         of.strand_checks(only_wall(m0 - 1))[1], f"ORGANIC_STRANDS {name}", "nearer the layer")
    sc_ = f["screws"][0]
    head = sc_[:3] + sc_[3:6] * (sc_[7] / 2)                              # in the middle of the first screw's washer and head
    case(f"a lump on the head of the screw at X {sc_[0]:.1f}, Y {sc_[1]:.1f}, Z {sc_[2]:.1f}", "ORGANIC_HEADS main has ... voxels within 1 mm of the washer or head",
         of.head_distance_checks(solid_at(dict(f), head, 1.0))[1], "ORGANIC_HEADS main has", "of the washer or head of the screw")
    import organic_strength as ost
    check("the cross-threads' rule reads organic_strength's push and allowable (LINK_PUSH = PUSH_N, LINK_ALLOW = ALLOW)", of.LINK_PUSH == ost.PUSH_N and of.LINK_ALLOW == ost.ALLOW,
          f"{ost.PUSH_N:g} N and {ost.ALLOW:g} MPa", f"{of.LINK_PUSH:g} N and {of.LINK_ALLOW:g} MPa")


def manifest_cases(f):
    """Revision 17, second step: organic_manifest.py notices when a piece changes (REVIEW.md row 13 for the layer)."""
    import organic_manifest as om
    base = om.normalise(om.build_manifest(f))
    idx = np.argwhere(f["d_main"] < 0)
    s = None                                             # a voxel of main with an empty neighbour along +X, in the middle of the list: moved there, the count and the extents stay
    for k in range(len(idx) // 2, len(idx)):
        i, j, l_ = idx[k]
        if f["d_main"][i + 1, j, l_] >= 0:
            s = (int(i), int(j), int(l_))
            break

    def moved(d):
        d[s] = 1.0
        d[s[0] + 1, s[1], s[2]] = -1.0
    g = damaged_piece(f, "main", moved)
    new = om.normalise(om.build_manifest(g))
    code, lines = om.judge(base, new, ["rear_panel"])
    check(f"organic_manifest: one voxel of main moved by one cell (X {f['xs'][s[0]]:.1f}, Y {f['ys'][s[1]]:.1f}, Z {f['zs'][s[2]]:.1f}): same count and extents, the hash names it, exit 1",
          code == 1 and new["main"]["voxels"] == base["main"]["voxels"] and new["main"]["centres"] == base["main"]["centres"]
          and first_match(lines, "FAIL: outside the expected list: main") is not None and first_match(lines, "solid mask differs") is not None,
          "exit 1; 'solid mask differs'; 'FAIL: outside the expected list: main'", f"exit {code}; " + "; ".join(x.strip() for x in lines if x.strip()))
    # a pad moved and no voxel touched: the mask's hash cannot see it, the pads are compared on their own
    pads = np.array(f["pads"], dtype=float)
    pads[0, 2] += 0.1
    code, lines = om.judge(base, om.normalise(om.build_manifest(dict(f, pads=pads))), ["rear_panel"])
    pad0 = str(f["names"][0])
    check(f"organic_manifest: the pad {pad0} of main moved 0.1 mm along Z, every voxel as it was: the pad is named, exit 1",
          code == 1 and first_match(lines, f"pad {pad0}") is not None and first_match(lines, "FAIL: outside the expected list: main") is not None
          and first_match(lines, "solid mask differs") is None,
          f"exit 1; 'pad {pad0}'; 'FAIL: outside the expected list: main'; no 'solid mask differs'", f"exit {code}; " + "; ".join(x.strip() for x in lines if x.strip()))
    pidx = np.argwhere(f["d_rear_panel"] < 0)
    t = tuple(int(c) for c in pidx[np.argmax(pidx[:, 2])])

    def less(d):                                         # the panel's topmost voxel taken away
        d[t] = 1.0
    code, lines = om.judge(base, om.normalise(om.build_manifest(damaged_piece(f, "rear_panel", less))), ["rear_panel"])
    check("organic_manifest: the rear panel changed, and named in --expect: allowed, exit 0",
          code == 0 and first_match(lines, "rear_panel", "solid voxels") is not None and first_match(lines, "OK: every difference is in the expected list") is not None,
          "exit 0; rear_panel changed; OK", f"exit {code}; " + "; ".join(x.strip() for x in lines if x.strip()))
    with open(os.devnull, "w") as quiet:
        old_out, sys.stdout = sys.stdout, quiet
        try:
            code = om.main(["--against", os.path.join(HERE, "no_such_organic_manifest.json"), "--expect", "rear_panel"])
        finally:
            sys.stdout = old_out
    check("organic_manifest: no manifest to compare with is exit 2, as in parts_manifest.py", code == 2, "exit 2", f"exit {code}")
    try:
        om.build_manifest(damaged_piece(f, "rear_panel", lambda d: d.__setitem__(slice(None), 1.0)))
        why = None
    except om.Unusable as e:
        why = str(e)
    check("organic_manifest: a piece with no solid voxel cannot be fingerprinted (exit 2), it does not compare equal to another empty piece",
          why is not None and "rear_panel" in why and "no solid voxel" in why, "Unusable: the piece rear_panel: no solid voxel", why or "NOTHING")


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
    # a budget is a floor: a layer that leaves the hand more room than the budget passes (the budget is then raised on purpose, in its own commit); a budget above what
    # the skeleton alone allows could never be met and is a mistake
    check("the hand's budget is not above what the layer gives today nor above what the skeleton alone allows",
          za.HAND_BUDGET_D <= h0[True]["d"] <= h0[False]["d"], f"budget Ø{za.HAND_BUDGET_D} <= with the layer <= without", f"Ø{h0[True]['d']} with the layer, Ø{h0[False]['d']} without")
    # the whole left flank closed by a slab just inside the fans' plane, from the front plane to the rear of the skeleton and from the desk to its top: the hand must not get in
    # round it through the grid's own margin behind, in front of or above the case (it did before the re-check of the second pass: 44 mm by the rear margin)
    hg = za.hand_grid(parts)
    flank_slab = (-(hw.ENVELOPE_FAN_X - 20.0), -(hw.ENVELOPE_FAN_X - 30.0), hw.ENVELOPE_Y0, hg.y_rear, hw.DESK_Z, hg.z_hull)
    _l, fz, hs = za.hand_check(parts, hardware, strands, f, extra_blocks=[flank_slab], route=False)
    case("a slab that closes the whole left flank stops the hand (no way round through the grid's margin)",
         "ZONE_ACCESS hand: without the organic layer no ball", fz, "ZONE_ACCESS hand: without the organic layer no ball")
    check("... and the hand is 0 with the layer and without it", hs[True]["d"] == 0 and hs[False]["d"] == 0, "Ø0 and Ø0", f"Ø{hs[True]['d']} with, Ø{hs[False]['d']} without")
    import organic_strength as ost
    ok_push = ("внутрь", (0.0, 0.0, 0.0), ost.MOVE_MAX - 0.1, ost.ALLOW - 0.1, (0.0, 0.0, 0.0))
    check("organic_strength: pushes inside both limits give no failure", not ost.push_failures([ok_push]), "no failure", ost.push_failures([ok_push]) or "none")
    case("organic_strength: a push that moves the layer too far fails the script", "ORGANIC_STRENGTH 1 of 2 pushes move the layer more than 5 mm",
         ost.push_failures([ok_push, ("внутрь", (1.0, 2.0, 3.0), ost.MOVE_MAX + 4.6, 1.0, (0.0, 0.0, 0.0))]), "ORGANIC_STRENGTH 1 of 2 pushes move the layer more than")
    case("organic_strength: a push over the allowable stress fails the script", "ORGANIC_STRENGTH 1 of 2 pushes are over the allowable",
         ost.push_failures([ok_push, ("вниз", (1.0, 2.0, 3.0), 0.1, ost.ALLOW + 1.0, (0.0, 0.0, 0.0))]), "ORGANIC_STRENGTH 1 of 2 pushes are over the allowable")
    # revision 17, second step: the own weight is judged with the pushes (load_failures: res[0] the weight, res[1:] the pushes); it was left out before
    ok_weight = ("вес", None, ost.MOVE_MAX - 0.1, ost.ALLOW - 0.1, (0.0, 0.0, 0.0))
    check("organic_strength: the own weight and the pushes inside both limits give no failure", not ost.load_failures([ok_weight, ok_push]), "no failure",
          ost.load_failures([ok_weight, ok_push]) or "none")
    case("organic_strength: the own weight over the allowable stress fails the script, the pushes inside", "ORGANIC_STRENGTH the layer's own weight gives ... over the allowable",
         ost.load_failures([("вес", None, 0.1, ost.ALLOW + 0.5, (4.0, 5.0, 6.0)), ok_push]), "ORGANIC_STRENGTH the layer's own weight gives", "over the allowable")
    case("organic_strength: the own weight moving the layer too far fails the script, the pushes inside", "ORGANIC_STRENGTH the layer's own weight moves it ... more than 5 mm",
         ost.load_failures([("вес", None, ost.MOVE_MAX + 0.5, 0.1, (4.0, 5.0, 6.0)), ok_push]), "ORGANIC_STRENGTH the layer's own weight moves it", "more than")
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


GAP_UNDER_TEST = 140.0     # probe_solver_cases: the thread's length between the blocks. The blocks clamp its ends, which the rule's loose bar does not, and the voxel model is stiff in
                           # bending: at 60 mm the thin thread gave 4.9 MPa (100 mm 9.6, 140 mm 14.5, 180 mm 19.4; at the rule's radius 2.3, 3.0, 3.8, 3.8)


def probe_solver_cases():
    """Revision 18 (part I.3): organic_strength pushes at a film member's probe and judges it, with the solver. A small field: two 30 mm blocks, each held by a pad on its outer end, and a
    thread across GAP_UNDER_TEST between them with its probe at the middle. The thread at LINK_R's mid radius (2.6) fails; at the radius of part C.7's rule for its length it passes."""
    import tempfile
    import organic_strength as ost
    import shell_concepts as sc
    vox, gap = of.VOX, GAP_UNDER_TEST
    xs = np.arange(-3.0, 2 * 30.0 + gap + 3.0 + vox / 2, vox, dtype=np.float32)
    ys = zs = np.arange(-3.0, 33.0 + vox / 2, vox, dtype=np.float32)
    G = np.meshgrid(xs, ys, zs, indexing="ij")
    x1 = 30.0 + gap
    blocks = np.minimum(sc.box_world(G, (0.0, 30.0, 0.0, 30.0, 0.0, 30.0)), sc.box_world(G, (x1, x1 + 30.0, 0.0, 30.0, 0.0, 30.0)))
    mid = (30.0 + gap / 2, 15.0, 15.0)

    def run(r_mid, with_probe=True, every=False):
        r_end = max(of.LINK_R[0], r_mid + of.LINK_END_MORE)
        thread = sc.tube(G, [(30.0, 15.0, 15.0), mid, (x1, 15.0, 15.0)], of.bone(r_end, r_mid, r_end))
        d = sc.smin(blocks.astype(np.float32), thread, 7.0).astype(np.float32)
        z = dict(d=d, d_test=d, xs=xs, ys=ys, zs=zs, pieces=np.array(["test"]), pads=np.array([[0.0, 15.0, 15.0, 1.0, 0.0, 0.0], [x1 + 30.0, 15.0, 15.0, -1.0, 0.0, 0.0]]),
                 names=np.array(["a", "b"]), pad_piece=np.array(["test", "test"]), probes=np.array([mid]), probe_kind=np.array(["link"]), probe_len=np.array([gap]),
                 probe_piece=np.array(["test" if with_probe else "another piece"]))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "field.npz")
            np.savez(path, **z)
            with patched(ost, "FIELD", path):
                _lines, fails, _arr, head = ost.run_piece("test", 1, n_points=1)
        return (fails if every else [x for x in fails if "probe pushes" in x]), head

    thin, h_thin = run(of.LINK_R[1])
    case(f"organic_strength: a {gap:g} mm thread of radius {of.LINK_R[1]:g} pushed at its probe ({h_thin['probe_stress']:.1f} MPa, {h_thin['probe_move']:.2f} mm)",
         "test: ORGANIC_STRENGTH ... probe pushes are over the allowable", thin, "ORGANIC_STRENGTH", "probe pushes are over the allowable")
    r_rule = of.link_radii(gap)[1]
    ok, h_ok = run(r_rule)
    check(f"  the same thread at the rule's radius {r_rule:.2f} passes ({h_ok['probe_stress']:.1f} MPa, {h_ok['probe_move']:.2f} mm; pushed {h_ok['probes_pushed']} of {h_ok['probes']})",
          not ok and h_ok["probes_pushed"] == 1, "no probe failure, the probe pushed", ok or f"none; pushed {h_ok['probes_pushed']}")
    none, _h = run(r_rule, with_probe=False, every=True)
    case("  the same thread with no probe saved for its piece", "ORGANIC_STRENGTH no probe was pushed", none, "ORGANIC_STRENGTH no probe was pushed", "not checked")


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
    f = {k: z[k] for k in z.files}
    field_cases(f)
    piece_cases(f)
    revision18_cases(f)
    manifest_cases(f)
    mode = "quick" if "--quick" in sys.argv else "full"
    if mode == "full":
        zone_cases(f)
        probe_solver_cases()
    bad = [n for ok, n in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(bad)} of {len(RESULTS)} cases pass" + ("" if not bad else ": FAILING " + "; ".join(bad)))
    if len(RESULTS) != EXPECTED_CASES[mode]:
        print(f"TEST_ORGANIC the {mode} run recorded {len(RESULTS)} cases, EXPECTED_CASES pins {EXPECTED_CASES[mode]}")
    sys.exit(1 if bad or len(RESULTS) != EXPECTED_CASES[mode] else 0)


if __name__ == "__main__":
    main()
