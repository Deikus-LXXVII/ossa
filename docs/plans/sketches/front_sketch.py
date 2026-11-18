"""The front of the organic layer redrawn (the owner, 18 Nov 2026): no light line, the module with the power button and the USB ports under an organic hood that is one
with the layer, and a denser film of straighter strands between the card and what stands under it. On top of the straight outline of straight_sketch.py.

What the sketch assumes about the skeleton, without building it: the ABS front sill is gone (198.5 g of ABS at 4 walls and 20 %); the carrier with the module stands on
beam_front as before and is screwed to it from below (where the sill's bolts were), so it slides out to the front from under the hood. The hood is a member of the piece
`main`: a flat lozenge over the carrier, two cheeks beside it, all carved 2 mm off the carrier like any skeleton part.

Run from the repository root:  .venv/bin/python docs/plans/sketches/front_sketch.py <out.png> [--strength] [--access]
"""
import os
import sys

import numpy as np

ROOT = os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "cad_b6"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hardware as hw
import shell_concepts as sc
import frame_v0
import organic_frame as of
import straight_sketch as ss

LOW_Y, LOW_Z = 22.0, 60.0                 # the film's lower bar and the hood's roof: over the carrier (its top Z 48.9), straight from post to post
LOW_X = 150.0                             # the film is hung between X -150 and 150
HOOD_X = (-92.0, 117.0)                   # the hood's cheeks: 10 mm outside the carrier's ends (X -82 and 107)
ROOF_R, ROOF_SQUASH = 26.0, 3.5           # the roof: a tube of this radius along X, flattened along Z by this factor (15 mm thick, 52 mm deep)
CHEEK_R, CHEEK_SQUASH = 22.0, 3.5         # a cheek: a tube down from the roof, flattened along X (12.6 mm thick)
FILM = dict(n=13, seed=23, sag=(0.0, 1.0, 0.0), sag_mm=2.0, links=6)     # 13 strands where the veil had 7, nearly straight (the veil sagged up to 12 mm)


def patch_front():
    ss.patch()
    low = [(-ss.BROW_Y - 147.0 + 0.0, LOW_Y, LOW_Z), (0.0, LOW_Y, LOW_Z), (160.0, LOW_Y, LOW_Z)]
    low[0] = (-160.0, LOW_Y, LOW_Z)
    # the sill is gone: its pads, its prism in the carve, the veil that stood on its ridge
    for name in [k for k, v in hw.ORGANIC_PADS.items() if v[0] == "front_sill"]:
        del hw.ORGANIC_PADS[name]
    of.sill_sdf = lambda G: np.full(G[0].shape, 1e9, dtype=np.float32)
    old_bones, old_films, old_add = of.bone_members, of.film_list, of.Field.add

    def bone_members():
        out, lines = old_bones()
        out.append(("tube", low, of.bone(7.0, 6.0, 7.0), of.K))
        lines["front_low"] = sc.spline(low, step=6.0)
        out.append(("slab", [(HOOD_X[0], LOW_Y, LOW_Z - 1.0), (0.0, LOW_Y, LOW_Z - 1.0), (HOOD_X[1], LOW_Y, LOW_Z - 1.0)], ROOF_R, 10.0, ("z", ROOF_SQUASH)))
        for x in HOOD_X:
            out.append(("slab", [(x, LOW_Y, LOW_Z - 4.0), (x, LOW_Y, 34.0), (x, LOW_Y, 14.0)], CHEEK_R, 10.0, ("x", CHEEK_SQUASH)))
        return out, lines

    def film_list():
        films = old_films()
        films[2] = of.film_members([(-LOW_X, LOW_Y, LOW_Z), (0.0, LOW_Y, LOW_Z), (LOW_X, LOW_Y, LOW_Z)], [(-LOW_X, ss.BROW_Y, ss.BROW_Z), (0.0, ss.BROW_Y, ss.BROW_Z), (LOW_X, ss.BROW_Y, ss.BROW_Z)],
                                   FILM["n"], seed=FILM["seed"], r_a=6.0, r_b=6.0, sag=FILM["sag"], sag_mm=FILM["sag_mm"], links=FILM["links"])
        return films

    def add(self, member):
        if member[0] != "slab":
            return old_add(self, member)
        _, ctrl, r, k, squash = member
        pts = np.array(ctrl, dtype=float)
        pad = r + k + 2 * self.vox
        sl, G = self.block(pts.min(axis=0) - pad, pts.max(axis=0) + pad)
        self.d[sl] = sc.smin(self.d[sl], sc.tube(G, ctrl, r, squash=squash), k)

    of.bone_members, of.film_list, of.Field.add = bone_members, film_list, add
    old_carve = of.carve_layer

    def carve_layer(F, parts, skel):
        old_carve(F, parts, skel)
        m = hw.FRONT_IO_W                                    # the module's face and the way the carrier slides out: open to the front and down to the beam
        car = next(p for p in parts if p.name == "front_io_carrier")
        b = frame_v0.exact_box(car.solid)
        F.carve_world_box((b[0], b[1], -20.0, b[3], 0.0, b[5]), of.GAP_SKEL)
        F.carve_world_box(m, of.GAP_HW)

    of.carve_layer = carve_layer


def main():
    out_png = sys.argv[1]
    patch_front()
    hware = {k: v for k, v in hw.build_hardware().items() if k != "light_strip"}
    parts, _ = frame_v0.build_frame(hardware=hw.build_hardware())
    parts = [p for p in parts if p.name != "front_sill"]
    U, anchors, fields, info = of.build(parts, hware)
    from scipy import ndimage
    for piece, F in fields.items():
        lab, n = ndimage.label(F.d < 0)
        sizes = sorted((ndimage.sum(F.d < 0, lab, index=np.arange(1, n + 1)) * F.vox ** 3 / 1000.0).tolist(), reverse=True)
        print(f"{piece}: {sum(sizes):.1f} cm3 in {n} bodies {[round(x, 1) for x in sizes[:4]]}")
    names = [a["name"] for a in anchors]
    tmp = os.path.join(os.path.dirname(out_png), "front_field.npz")
    np.savez(tmp, d=U.d, xs=U.xs, ys=U.ys, zs=U.zs, pads=np.array([list(a["q"]) + list(a["n"]) for a in anchors], dtype=float), names=np.array(names), pieces=np.array(list(fields)),
             pad_piece=np.array([hw.ORGANIC_PADS[a["name"]][3] for a in anchors]), **{"d_" + k: f.d for k, f in fields.items()})
    print("pads of main:", ", ".join(n for n in names if hw.ORGANIC_PADS[n][3] == "main"))
    if "--strength" in sys.argv:
        import organic_strength as st
        old, st.FIELD = st.FIELD, tmp
        try:
            _l, fails, arr, head = st.run_piece("main", 1)
        finally:
            st.FIELD = old
        order = np.argsort(-arr["stress"])[:3]
        print(f"strength of main: worst {head['stress']:.1f} MPa at ({head['stress_at'][0]:.0f}, {head['stress_at'][1]:.0f}, {head['stress_at'][2]:.0f}), {int((arr['stress'] > st.ALLOW).sum())} over; "
              f"largest movement {head['move']:.2f} mm pushing ({head['move_push'][0]:.0f}, {head['move_push'][1]:.0f}, {head['move_push'][2]:.0f}), {int((arr['move'] > st.MOVE_MAX).sum())} over", flush=True)
        for i in order:
            print(f"    {arr['stress'][i]:.1f} MPa, {arr['move'][i]:.2f} mm: push at ({arr['points'][i][0]:.0f}, {arr['points'][i][1]:.0f}, {arr['points'][i][2]:.0f})")
    if "--access" in sys.argv:
        import zone_access
        f = dict(d=U.d, xs=U.xs.astype(float), ys=U.ys.astype(float), zs=U.zs.astype(float), pieces=np.array(list(fields)), **{"d_" + k: v.d for k, v in fields.items()})
        lines, fails, _ = zone_access.run(parts=parts, hardware=hware, field=f)
        print("zone_access fails:", fails)
        for l in lines:
            if "со слоем" in l or "рука к грани" in l:
                print("  ", l.strip()[:200])
    import render_full as rf
    import render_vtk
    import cables
    import hoses
    import hose_routes
    actors = []
    for p in parts:
        actors += render_vtk._actors(p.solid, cables.TIE_RGB if p.name.startswith("tie_bridge") else rf.ABS_RGB, opacity=1.0, edge_opacity=0.45)
    for name, solid in hware.items():
        if name in hw.KEEP_OUT or name in hw.HOSES:
            continue
        actors += render_vtk._actors(solid, render_vtk.HW_RGB.get(name, (0.6, 0.6, 0.6)), opacity=1.0, edge_opacity=0.35)
    for name, (pair, spec) in hoses.routes().items():
        actors += [hose_routes.tube_actor(h["pts"], spec["r"], (0.10, 0.10, 0.11) if name == "cpu" else (0.42, 0.24, 0.12)) for h in pair]
    for name, rt in cables.build_routes().items():
        if name != "argb":
            actors += [hose_routes.tube_actor(p, r, rf.CABLE_RGB) for p, r in rt.strands]
    actors.append(ss.actor(U.xs, U.ys, U.zs, U.d))
    rf.sheet(actors, rf.CORNERS, 2, out_png, parallel=False)
    rf.sheet(actors, {k: rf.SIDES[k] for k in ("front", "rear", "left", "right")}, 2, out_png.replace(".png", "_sides.png"), parallel=True)
    close = {"front, close": ((0.0, -1.0, 0.25), (0, 0, 1)), "front left, low": ((-0.8, -1.2, 0.35), (0, 0, 1))}
    rf.sheet(actors, close, 2, out_png.replace(".png", "_close.png"), parallel=False)


if __name__ == "__main__":
    main()
