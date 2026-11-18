"""The organic layer with a straight outline (the owner, 18 Nov 2026: "make the outlines of the organic design straighter: not the webs themselves, the parts that form the
silhouette"). The bones that draw the silhouette (the front posts, the rear sweeps, the base rails, the brow) are redrawn as straight legs with tight knees; the films between
them are left as they are. The layer is built by organic_frame.build() itself, with only those control points replaced, so every pad and every carve is the real one.

Run from the repository root:  .venv/bin/python docs/plans/sketches/straight_sketch.py <out.png> [--strength] [--access]
"""
import os
import sys

import numpy as np
from scipy import ndimage

ROOT = os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "cad_b6"))
import hardware as hw
import shell_concepts as sc
import frame_v0
import organic_frame as of
import render_full as rf
import vtk

KNEE = 25.0                       # a knee's two neighbours stand this far from it along its legs: the bend is that tight, the rest of each leg is straight
REAR_KNEE = (176.0, 366.0, 224.0)        # (|X|, Y, Z): where the rear sweep turns down the back, under the antler (Z 232) and behind the post (Y 348)
BROW_Y, BROW_Z = 13.0, 152.0             # the brow, straight across


def toward(a, b, mm):
    a, b = np.array(a, dtype=float), np.array(b, dtype=float)
    return tuple(a + (b - a) / np.linalg.norm(b - a) * mm)


def at_z(a, b, z):
    a, b = np.array(a, dtype=float), np.array(b, dtype=float)
    return tuple(a + (b - a) * (z - a[2]) / (b[2] - a[2]))


def front_sweep(s):
    """A straight post from the front foot to the end of the card's bone; on the right one more straight leg to the corner of the 360's lip. The same number of control
    points as before (the films slice them): two on the post, the upper one a knee's neighbour."""
    foot = (158 * s, 14, 4)        # 8 mm further forward than before (Y 22): a straight post from Y 22 crosses the driver's path to the sill's end pad (Y 28, Z 45)
    card = of.bp(of.CARD_BONE_U, of.CARD_BONE_N, of.SWEEP_X * s)
    pts = [foot, at_z(foot, card, BROW_Z), toward(card, foot, KNEE), card]
    return pts + [of.bp(of.LIP_U, of.FACE_N, 190 * s)] if s > 0 else pts


def rear_sweep(s):
    """Two straight legs: from the ring's far side to a knee under the antler, and from there down the back to the pad on the post; then the short way to the rear foot."""
    start = of.bp(hw.FAN_SIDE_U[1] + of.RING_OFF, of.REAR_FROM_N, of.RING_X[s])
    knee = (REAR_KNEE[0] * s, REAR_KNEE[1], REAR_KNEE[2])
    low = (169 * s, 372, 44)
    return [start, toward(knee, start, KNEE), knee, toward(knee, low, KNEE), low, (166 * s, 368, -6)]


def base(s):
    a, b = (160 * s, 40, -4), (166 * s, 356, -4)
    return [a] + [tuple(np.array(a) + (np.array(b) - np.array(a)) * t) for t in (0.22, 0.49, 0.79)] + [b]


def patch():
    of.front_sweep, of.rear_sweep = front_sweep, rear_sweep
    of.BASE = {s: base(s) for s in (1, -1)}
    of.BROW = [(-160, BROW_Y, BROW_Z), (0, BROW_Y, BROW_Z), (160, BROW_Y, BROW_Z)]


def actor(F_xs, F_ys, F_zs, d):
    vox, sc.VOX = sc.VOX, float(F_xs[1] - F_xs[0])
    try:
        shell = sc.mesh(F_xs, F_ys, F_zs, d)
    finally:
        sc.VOX = vox
    m = vtk.vtkPolyDataMapper()
    m.SetInputData(shell)
    m.ScalarVisibilityOff()
    a = vtk.vtkActor()
    a.SetMapper(m)
    a.GetProperty().SetColor(*rf.LAYER_RGB)
    a.GetProperty().SetAmbient(0.35)
    a.GetProperty().SetDiffuse(0.65)
    a.GetProperty().SetSpecular(0.25)
    return a


def main():
    out_png = sys.argv[1]
    patch()
    hware = hw.build_hardware()
    parts, _ = frame_v0.build_frame(hardware=hware)
    U, anchors, fields, info = of.build(parts, hware)
    for piece, F in fields.items():
        lab, n = ndimage.label(F.d < 0)
        sizes = sorted((ndimage.sum(F.d < 0, lab, index=np.arange(1, n + 1)) * F.vox ** 3 / 1000.0).tolist(), reverse=True)
        print(f"{piece}: {sum(sizes):.1f} cm3 in {n} bodies {[round(x, 1) for x in sizes[:4]]}")
    saved = np.load(os.path.join(ROOT, "out", "organic", "field.npz"))
    print(f"main before: {float((saved['d_main'] < 0).sum()) * 1.5 ** 3 / 1000:.1f} cm3")
    try:
        for b in of.bitten(fields["main"], info["lines"], parts, hware):
            print("  bitten:", str(b)[:200])
    except Exception as e:                       # the sketch does not depend on it
        print("  (bitten() not run:", type(e).__name__, str(e)[:100], ")")
    names = [a["name"] for a in anchors]
    pads = np.array([list(a["q"]) + list(a["n"]) for a in anchors], dtype=float)
    piece_of = [hw.ORGANIC_PADS[a["name"]][3] for a in anchors]
    tmp = os.path.join(os.path.dirname(out_png), "straight_field.npz")
    np.savez(tmp, d=U.d, xs=U.xs, ys=U.ys, zs=U.zs, pads=pads, names=np.array(names), pieces=np.array(list(fields)), pad_piece=np.array(piece_of),
             **{"d_" + k: f.d for k, f in fields.items()})
    print("field ->", tmp)
    if "--strength" in sys.argv:
        import organic_strength as st
        old, st.FIELD = st.FIELD, tmp
        try:
            _l, fails, arr, head = st.run_piece("main", 1)
        finally:
            st.FIELD = old
        print(f"strength of main: worst {head['stress']:.1f} MPa at ({head['stress_at'][0]:.0f}, {head['stress_at'][1]:.0f}, {head['stress_at'][2]:.0f}), {int((arr['stress'] > st.ALLOW).sum())} over; "
              f"largest movement {head['move']:.2f} mm pushing ({head['move_push'][0]:.0f}, {head['move_push'][1]:.0f}, {head['move_push'][2]:.0f}), {int((arr['move'] > st.MOVE_MAX).sum())} over "
              f"(before: 6.5 MPa, 2.16 mm)", flush=True)
    if "--access" in sys.argv:
        import drive_access
        import zone_access
        f = dict(d=U.d, xs=U.xs.astype(float), ys=U.ys.astype(float), zs=U.zs.astype(float), pieces=np.array(list(fields)), **{"d_" + k: v.d for k, v in fields.items()})
        lines, fails, _ = zone_access.run(parts=parts, hardware=hware, field=f)
        print("zone_access fails:", fails)
        for l in lines:
            if "со слоем" in l or "рука к грани" in l:
                print("  ", l.strip()[:220])
    actors = rf.scene(layer=False, cable_colours=False) + [actor(U.xs, U.ys, U.zs, U.d)]
    rf.sheet(actors, rf.CORNERS, 2, out_png, parallel=False)
    rf.sheet(actors, {k: rf.SIDES[k] for k in ("front", "rear", "left", "right")}, 2, out_png.replace(".png", "_sides.png"), parallel=True)


if __name__ == "__main__":
    main()
