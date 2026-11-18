"""A way for the card's power cable through the organic layer (the owner, 18 Nov 2026: "make sure it can be plugged in properly; in the renders it goes through an organic
beam"). Measured before: the 12V-2x6 cable's centre line runs 14.7 mm deep inside the layer for about 84 mm: the bone `card` stands at u 118, n 168, right over the card's
socket (u 119), and the cable's descent at u 173 stands 4.5 mm from the lip's centre line (u 177.5).

On top of front_sketch.py. Two layouts were tried:
- the bone `card` moved to u 140 and the cable's descent moved to u 158: the cable script then fails (the arch stands 12.1 mm in front of the case, 11 are accepted; by its
  own checks the descent can move to u 168 at most), and the front posts, which end on the bone `card`, lean away from the brow (23.1 MPa in the front film);
- this one: the cable's route stays as it is, and the two bones it crosses each get a gate. The bone `card` stops either side of the socket (CARD_GATE_X); the lip stops
  either side of the cable's descent (LIP_GATE_X), where it is squeezed between the 360 and the cable anyway. The films between the two bones end at the gates. Nothing of
  the layer stands in a box round the plug and the cable's straight (PLUG_ZONE), like the plug zones of the board's connectors. The layer is carved from every routed cable
  and every hose along the whole centre line (the layer's own carve takes every fourth point of a hose and no cable).

Run from the repository root:  .venv/bin/python docs/plans/sketches/cable_gate_sketch.py <out.png> [--strength]
"""
import os
import sys

import numpy as np

ROOT = os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "cad_b6"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hardware as hw
import frame_v0
import organic_frame as of
import cables
import hoses
import straight_sketch as ss
import front_sketch as fs
import cables_through_layer as ctl


def ctl_same(a, b):
    a, b = np.array(a, dtype=float), np.array(b, dtype=float)
    return a.shape == b.shape and np.allclose(a, b)

CARD_GATE_X = (-25.5, 41.5)      # the bone `card` stops at these X (its centre line's ends): the socket is at X 8, known to 12 mm; half a plug 10; 5 to spare; the bone's radius 6.5
LIP_GATE_X = (111.0, 152.0)      # the lip stops here: the cable comes down at X 131.5 (cables.V_GAP), radius 7, 3 of air, 4 to spare, the bone's radius
FILM_R_X1 = 108.0                # the film between `card` and the lip on the right ends before the lip's gate
GS = hw.GPU_PWR_SOCKET
MOUTH_N = hw.GPU_BS[5] - GS["recess"]
PLUG_ZONE = (GS["v"] - 30.0, GS["v"] + 30.0, GS["u"] - 14.0, GS["u"] + 14.0, MOUTH_N, MOUTH_N + hw.GPU12V_PLUG + hw.GPU12V_STRAIGHT + 10.0)      # board space: the socket's place +- its tolerance and half a plug
CABLE_GAP = 3.0                  # the layer keeps this far from a cable's surface (GAP_KEEP); from a hose GAP_HW, as before


def patch_gate():
    fs.patch_front()
    front_bones, front_films = of.bone_members, of.film_list      # front_sketch's
    cu, cn = of.CARD_BONE_U, of.CARD_BONE_N
    card_l = [of.bp(cu, cn, -of.SWEEP_X), of.bp(cu + 1, cn + 1, -100), of.bp(cu + 1, cn + 1, CARD_GATE_X[0])]
    card_r = [of.bp(cu + 1, cn + 1, CARD_GATE_X[1]), of.bp(cu + 1, cn + 1, 100), of.bp(cu, cn, of.SWEEP_X)]
    lip_l = [of.bp(of.LIP_U, of.FACE_N, -190), of.bp(of.LIP_U - 1, of.FACE_N + 1, -60), of.bp(of.LIP_U - 1, of.FACE_N + 1, 60), of.bp(of.LIP_U - 1, of.FACE_N + 1, LIP_GATE_X[0])]
    lip_r = [of.bp(of.LIP_U - 1, of.FACE_N + 1, LIP_GATE_X[1]), of.bp(of.LIP_U - 0.5, of.FACE_N + 0.5, 171), of.bp(of.LIP_U, of.FACE_N, 190)]

    def bone_members():
        out, lines = front_bones()
        keep = [m for m in out if not (m[0] == "tube" and (ctl_same(m[1], of.LIP_BONE) or ctl_same(m[1], of.CARD_BONE)))]
        assert len(keep) == len(out) - 2, "the bones card and lip were not found"
        for name, ctrl, r in (("card_L", card_l, of.BONE_R["card"]), ("card_R", card_r, of.BONE_R["card"]), ("lip_L", lip_l, of.BONE_R["lip"]), ("lip_R", lip_r, of.BONE_R["lip"])):
            keep.append(("tube", ctrl, of.bone(*r), of.K))
            lines[name] = of.sc.spline(ctrl, step=6.0)
        for p in (card_l[-1], card_r[0], lip_l[-1], lip_r[0]):          # a bone's free end is a ball, like the feet
            keep.append(("ball", p, 8.0, 8.0))
        for k in ("card", "lip"):
            lines.pop(k)
        return keep, lines

    def film_list():
        films = front_films()
        films[0] = of.film_members(card_l, [of.bp(of.LIP_U, of.FACE_N, -190), of.bp(of.LIP_U - 1, of.FACE_N + 1, -100), of.bp(of.LIP_U - 1, of.FACE_N + 1, CARD_GATE_X[0])],
                                   8, seed=3, r_a=6.0, r_b=6.0, sag=(0.0, 0.707, -0.707), sag_mm=4, links=3)
        films[1] = of.film_members([of.bp(cu + 1, cn + 1, 44.0), of.bp(cu + 1, cn + 1, 76.0), of.bp(cu + 1, cn + 1, FILM_R_X1)],
                                   [of.bp(of.LIP_U - 1, of.FACE_N + 1, 44.0), of.bp(of.LIP_U - 1, of.FACE_N + 1, 76.0), of.bp(of.LIP_U - 1, of.FACE_N + 1, FILM_R_X1)],
                                   5, seed=8, r_a=6.0, r_b=6.0, sag=(0.0, 0.707, -0.707), sag_mm=4, links=2)
        return films

    of.bone_members, of.film_list = bone_members, film_list
    front_carve = of.carve_layer
    strand_dist = {}                                 # {clearance: distance field}: one distance transform per clearance, for every piece

    def carve_layer(F, parts, skel):
        front_carve(F, parts, skel)
        F.carve_bs_box(PLUG_ZONE, of.GAP_KEEP)
        if not strand_dist:                          # every strand's centre line marked on the grid, then one distance transform for each clearance (a sphere at every
            from scipy import ndimage                # point of every strand, as carve_polyline does, takes half an hour)
            groups = {}
            for name, rt in cables.build_routes().items():
                if name != "argb":
                    for p, r in rt.strands:
                        groups.setdefault(round(float(r) + CABLE_GAP, 2), []).append(ctl.densify(p, 0.7))
            for name, (pair, spec) in hoses.routes().items():
                for h in pair:
                    groups.setdefault(round(spec["r"] + of.GAP_HW, 2), []).append(ctl.densify(h["pts"], 0.7))
            for clear, lines in groups.items():
                occ = np.zeros(F.d.shape, dtype=bool)
                for pts in lines:
                    idx = np.round((pts - np.array([F.xs[0], F.ys[0], F.zs[0]])) / F.vox).astype(int)
                    ok = np.all((idx >= 0) & (idx < np.array(F.d.shape)), axis=1)
                    occ[tuple(idx[ok].T)] = True
                strand_dist[clear] = ndimage.distance_transform_edt(~occ, sampling=F.vox).astype(np.float32)
        for clear, dist in strand_dist.items():
            np.maximum(F.d, (clear + F.vox) - dist, out=F.d)      # one voxel more: the centre line is marked on the nearest voxel

    of.carve_layer = carve_layer


def main():
    out_png = sys.argv[1]
    patch_gate()
    hware = {k: v for k, v in hw.build_hardware().items() if k != "light_strip"}
    parts_all, _ = frame_v0.build_frame(hardware=hw.build_hardware())
    parts = [p for p in parts_all if p.name != "front_sill"]
    routes = cables.build_routes()
    fails = cables.failures(routes, cables.evaluate(routes, parts_all, hw.build_hardware()))
    print("cables.py's own checks, the routes as they are: " + ("pass" if not fails else f"{len(fails)} FAIL"))
    for _c, t in fails[:8]:
        print("   ", str(t)[:220])
    U, anchors, fields, info = of.build(parts, hware)
    from scipy import ndimage
    for piece, F in fields.items():
        lab, n = ndimage.label(F.d < 0)
        sizes = sorted((ndimage.sum(F.d < 0, lab, index=np.arange(1, n + 1)) * F.vox ** 3 / 1000.0).tolist(), reverse=True)
        print(f"{piece}: {sum(sizes):.1f} cm3 in {n} bodies {[round(x, 1) for x in sizes[:4]]}")
    tmp = os.path.join(os.path.dirname(out_png), "gate_field.npz")
    names = [a["name"] for a in anchors]
    np.savez(tmp, d=U.d, xs=U.xs, ys=U.ys, zs=U.zs, pads=np.array([list(a["q"]) + list(a["n"]) for a in anchors], dtype=float), names=np.array(names), pieces=np.array(list(fields)),
             pad_piece=np.array([hw.ORGANIC_PADS[a["name"]][3] for a in anchors]), **{"d_" + k: f.d for k, f in fields.items()})
    # the zone and the strands against the layer
    Xb = of.sc.to_bs(np.meshgrid(U.xs, U.ys, U.zs, indexing="ij")) if False else None
    sys.argv = [sys.argv[0], tmp]
    lines = [(f"cable {name}[{k}]", ctl.densify(p), float(r)) for name, rt in routes.items() if name != "argb" for k, (p, r) in enumerate(rt.strands)]
    lines += [(f"hose {name}[{k}]", ctl.densify(h["pts"]), float(spec["r"])) for name, (pair, spec) in hoses.routes().items() for k, h in enumerate(pair)]
    vox = float(U.xs[1] - U.xs[0])
    worst = []
    for name, pts, r in lines:
        idx = np.array([(pts[:, 0] - U.xs[0]) / vox, (pts[:, 1] - U.ys[0]) / vox, (pts[:, 2] - U.zs[0]) / vox])
        val = ndimage.map_coordinates(U.d, idx, order=1, mode="nearest")
        ok = np.all((idx.T >= 0) & (idx.T <= np.array(U.d.shape) - 1), axis=1)
        gap = np.where(ok, val, 1e9) - r
        k = int(np.argmin(gap))
        worst.append((float(gap[k]), name, pts[k]))
    worst.sort(key=lambda w: w[0])
    print("least gap between a strand's surface and the layer (the five closest):")
    for g, name, p in worst[:5]:
        print(f"   {name:16} {g:6.1f} mm at X {p[0]:.0f}, Y {p[1]:.0f}, Z {p[2]:.0f}")
    try:
        for b in of.bitten(fields["main"], {k: v for k, v in info["lines"].items() if k in ("card_L", "card_R", "lip_L", "lip_R", "brow", "front_L", "front_R")}, parts, hware):
            print("  bitten:", str(b)[:160])
    except Exception as e:
        print("  (bitten() not run:", type(e).__name__, ")")
    if "--strength" in sys.argv or "--strength" in os.environ.get("SKETCH_ARGS", ""):
        import organic_strength as st
        old, st.FIELD = st.FIELD, tmp
        try:
            _l, f2, arr, head = st.run_piece("main", 1)
        finally:
            st.FIELD = old
        print(f"strength of main: worst {head['stress']:.1f} MPa at ({head['stress_at'][0]:.0f}, {head['stress_at'][1]:.0f}, {head['stress_at'][2]:.0f}), {int((arr['stress'] > st.ALLOW).sum())} over; "
              f"largest movement {head['move']:.2f} mm pushing ({head['move_push'][0]:.0f}, {head['move_push'][1]:.0f}, {head['move_push'][2]:.0f}), {int((arr['move'] > st.MOVE_MAX).sum())} over", flush=True)
    import render_full as rf
    import render_vtk
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
    for name, rt in routes.items():
        if name != "argb":
            actors += [hose_routes.tube_actor(p, r, (0.95, 0.20, 0.55) if name == "gpu12v" else rf.CABLE_RGB) for p, r in rt.strands]
    actors.append(ss.actor(U.xs, U.ys, U.zs, U.d))
    rf.sheet(actors, {"front, from above": ((0.0, -1.0, 1.0), (0, 0, 1)), "front left": ((-0.75, -1.25, 0.70), (0, 0, 1))}, 2, out_png, parallel=False)


if __name__ == "__main__":
    STRENGTH = "--strength" in sys.argv
    if STRENGTH:
        os.environ["SKETCH_ARGS"] = "--strength"
    main()
