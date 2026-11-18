"""A sketch of the organic rear panel: its own piece, in its own field on the layer's grid, carved like the layer and kept clear of the layer. A picture and a few numbers, no pilots.

Run from the repository root:  .venv/bin/python <this file> [out.png] [out.npz]
"""
import os
import sys

import numpy as np
from scipy import ndimage

ROOT = os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "cad_b6"))
import hardware as hw
import hoses
import shell_concepts as sc
import frame_v0
import organic_frame as of
import render_full as rf
import vtk

OUT_PNG = sys.argv[1] if len(sys.argv) > 1 else "rear_panel_sketch.png"
OUT_NPZ = sys.argv[2] if len(sys.argv) > 2 else None

HALF_X = 131.0            # the frame's centre line: inside the posts' inner faces (142) by its radius and the gap to the skeleton
BAR_R = 6.5
Y_LOW, Z_LOW = 384.0, 104.0       # the lower bar: over the bulkhead's top (Z 92), its rear in line with the layer's flanks (Y 385); a drive's body ends at Y 357.6 and stands up to Z 150
Y_TOP, Z_TOP = 360.0, 250.0       # the upper bar: behind the posts' rear faces (Y 348), under the 420's fans (rear lower corner Y 338.6, Z 266.9)
GAP_PIECE = 3.0                   # to the rest of the layer: two pieces that are put on separately
PADS = [((s * 132.0, 381.0, z), (0.0, 1.0, 0.0)) for s in (1, -1) for z in (64.0, 25.0)]        # all four on the bulkhead's end blocks, rear face (the piece stays 285 mm wide)
Y_GRID = 394.0                    # the layer's own grid: the panel fits in it
Y_FLAT = 391.5                    # nothing of the panel behind this plane: the knots round the screws get a flat rear face
N_STRANDS, LINKS, SEED = 9, 5, 17


def members():
    low = [(-HALF_X, Y_LOW, Z_LOW), (0.0, Y_LOW + 2.0, Z_LOW + 2.0), (HALF_X, Y_LOW, Z_LOW)]
    top = [(-HALF_X, Y_TOP, Z_TOP), (0.0, Y_TOP + 2.0, Z_TOP + 3.0), (HALF_X, Y_TOP, Z_TOP)]
    out = []
    for s in (-1, 1):
        side = [(s * HALF_X, Y_LOW, Z_LOW), (s * (HALF_X + 2.0), (Y_LOW + Y_TOP) / 2 + 2.0, (Z_LOW + Z_TOP) / 2), (s * HALF_X, Y_TOP, Z_TOP)]
        out.append(("tube", side, BAR_R, of.K))
        out += [("ball", side[0], 9.0, of.K), ("ball", side[-1], 9.0, of.K)]
    out += of.film_members(low, top, N_STRANDS, seed=SEED, r_a=BAR_R, r_b=BAR_R, sag=(0.0, 1.0, 0.3), sag_mm=6.0, links=LINKS)
    return out, dict(low=low, top=top)


def main():
    hware = hw.build_hardware()
    parts, _ = frame_v0.build_frame(hardware=hware)
    layer = np.load(os.path.join(ROOT, "out", "organic", "field.npz"))
    y1, sc.Y1 = sc.Y1, Y_GRID
    try:
        F = of.Field()
    finally:
        sc.Y1 = y1
    ld = np.full(F.d.shape, 1e9, dtype=np.float32)
    ld[:, :layer["d"].shape[1], :] = layer["d"]
    assert np.allclose(F.ys[:layer["d"].shape[1]], layer["ys"])
    mem, lines = members()
    corners = {1: ((HALF_X, Y_LOW, Z_LOW), (HALF_X, Y_TOP, Z_TOP)), -1: ((-HALF_X, Y_LOW, Z_LOW), (-HALF_X, Y_TOP, Z_TOP))}
    for q, n in PADS:
        q, n = np.array(q), np.array(n)
        tie = np.array(corners[1 if q[0] > 0 else -1][0])
        mem.append(("ball", tuple(q + n * (of.KNOT_R - 4.0)), of.KNOT_R, 8.0))
        mem.append(("tube", [q + n * (of.PAD_H * 0.6), (q + n * of.PAD_H + tie) / 2 + n * 3.0, tie], of.bone(8.0, 7.0, 8.0), 8.0))
        if q[2] > 40:      # two more legs fan out from the upper pad inwards and up to the lower bar: over the bulkhead's top edge the panel is only as thick as the room behind the
            for bx in (115.0, 100.0):      # bulkhead (Y 383 to Y_FLAT), so it is made wide there
                brace = np.array([np.sign(q[0]) * bx, Y_LOW, Z_LOW + 1.0])
                mem.append(("tube", [q + n * (of.PAD_H * 0.6), (q + n * of.PAD_H + brace) / 2 + n * 2.0, brace], of.bone(7.5, 7.0, 7.5), 8.0))
    for m in mem:
        F.add(m)
    for b in (hw.RAD360_BS, hw.RAD420_ENV_BS, hw.BOARD_BS):
        F.carve_bs_box(b, of.GAP_HW)
    F.carve_world_box(hw.PSU_W, of.HOT_GAP)
    F.carve_bs_box(hw.GPU_BS, of.HOT_GAP)
    for name in hw.FAN_SIDE_NAMES:
        F.carve_bs_box(hw.fan_side_bs(name), of.GAP_HW)
    for b in (hw.DIMMS_BS, hw.IO_ZONE_BS, hw.GPU_OUT_ZONE_BS, hw.ATX24_BS, hw.EPS_BS):
        F.carve_bs_box(b, of.GAP_KEEP)
    F.carve_bs_box(of.OUT_PRISM_BS, of.OUT_PRISM_GAP)
    for name, (pair, spec) in hoses.routes().items():
        for h in pair:
            F.carve_polyline(h["pts"][::4], spec["r"] + of.GAP_HW + 1.0)
    skel, _ = of.skeleton_distance(F, parts)
    np.maximum(F.d, of.GAP_SKEL - skel, out=F.d)
    np.maximum(F.d, GAP_PIECE - ld, out=F.d)
    for body in hware["drive_left"].Solids():
        b = frame_v0.exact_box(body)
        F.carve_world_box(b, of.HOT_GAP)
        F.carve_world_box((-b[1], -b[0], *b[2:]), of.HOT_GAP)        # the same room on the right, so that the panel stays mirrored
    np.maximum(F.d, (F.ys - Y_FLAT)[None, :, None], out=F.d)
    solid = F.d < 0
    core = ndimage.distance_transform_edt(solid, sampling=F.vox) > of.MIN_THICK / 2
    opened = ndimage.distance_transform_edt(~core, sampling=F.vox) <= of.MIN_THICK / 2
    F.d[solid & ~opened] = 0.6 * F.vox
    for q, n in PADS:
        sl, cyl = F.cylinder(q, n, of.PAD_R, 0.0, of.PAD_H)
        F.d[sl] = sc.smin(F.d[sl], cyl, 3.0)
    for q, n in PADS:
        sl, cyl = F.cylinder(q, n, of.SCREW_R, -1.0, of.PAD_H + 0.5)
        F.d[sl] = np.maximum(F.d[sl], -cyl)
        sl, cyl = F.cylinder(q, n, of.HEAD_R, of.PAD_H, of.PAD_H + of.HEAD_REACH)
        F.d[sl] = np.maximum(F.d[sl], -cyl)
    lab, n = ndimage.label(F.d < 0)
    sizes = ndimage.sum(F.d < 0, lab, index=np.arange(1, n + 1)) * F.vox ** 3 / 1000.0
    print("pieces (cm3):", [round(float(s), 1) for s in sorted(sizes, reverse=True)])
    big = int(np.argmax(sizes)) + 1
    F.d[(lab != big) & (F.d < 0)] = F.vox
    idx = np.argwhere(F.d < 0)
    lo, hi = idx.min(axis=0), idx.max(axis=0)
    ext = [(float(c[a]), float(c[b])) for c, a, b in zip((F.xs, F.ys, F.zs), lo, hi)]
    ext = [(a - F.vox / 2, b + F.vox / 2) for a, b in ext]      # the surface stands up to half a voxel outside the last centre
    print("panel: %.1f cm3, %.0f g of PETG; X %.2f..%.2f (%.1f), Y %.2f..%.2f (%.1f), Z %.2f..%.2f (%.1f)" % (
        sizes[big - 1], sizes[big - 1] * of.LAYER_RHO, *ext[0], ext[0][1] - ext[0][0], *ext[1], ext[1][1] - ext[1][0], *ext[2], ext[2][1] - ext[2][0]))
    for q, n in PADS:
        i = [int(round((q[k] + n[k] * of.PAD_H / 2 + 0.0 - c[0]) / F.vox)) for k, c in enumerate((F.xs, F.ys, F.zs))]
        probe = (q[0] + 6.0, q[1] + of.PAD_H / 2, q[2])
        j = [int(round((probe[k] - c[0]) / F.vox)) for k, c in enumerate((F.xs, F.ys, F.zs))]
        print("  pad at", q, "in the piece:", bool(lab[tuple(j)] == big))
    if OUT_NPZ:
        np.savez_compressed(OUT_NPZ, xs=F.xs, ys=F.ys, zs=F.zs, d=F.d)
    # picture: the whole design, the panel in a lighter grey so that it reads against the layer
    actors = rf.scene(layer=True, cable_colours=False)
    vox, sc.VOX = sc.VOX, float(F.vox)
    try:
        shell = sc.mesh(F.xs, F.ys, F.zs, F.d)
    finally:
        sc.VOX = vox
    m = vtk.vtkPolyDataMapper()
    m.SetInputData(shell)
    m.ScalarVisibilityOff()
    a = vtk.vtkActor()
    a.SetMapper(m)
    a.GetProperty().SetColor(*(rf.LAYER_RGB if os.environ.get("PANEL_DARK") else (0.55, 0.20, 0.16)))
    a.GetProperty().SetAmbient(0.35)
    a.GetProperty().SetDiffuse(0.65)
    a.GetProperty().SetSpecular(0.25)
    views = {"rear": ((0.0, 1.0, 0.25), (0, 0, 1)), "rear left": ((-0.9, 1.2, 0.65), (0, 0, 1)), "rear right": ((0.95, 1.20, 0.65), (0, 0, 1)), "rear, from above": ((0.0, 1.0, 1.1), (0, 0, 1))}
    rf.sheet(actors + [a], views, 2, OUT_PNG, parallel=False)
    a.GetProperty().SetColor(*rf.LAYER_RGB)
    rf.sheet(actors + [a], views, 2, OUT_PNG.replace(".png", "_dark.png"), parallel=False)


if __name__ == "__main__":
    main()
