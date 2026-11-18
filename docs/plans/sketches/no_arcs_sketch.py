"""A first look at the organic layer without its corner arcs (the owner, 18 Nov 2026: "get rid of these arcs or make them smaller, to minimise the bread-bin look").

It takes the members of the piece `main` as organic_frame.py declares them and leaves some out. Nothing is redrawn and nothing is held anew: what falls apart is shown falling
apart, and the script says which bodies are left and which of them still hold a pad. A picture and a few numbers.

Run from the repository root:  .venv/bin/python docs/plans/sketches/no_arcs_sketch.py <variant> <out.png>
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

# what a variant leaves out: bones by name (as in bone_members' `lines`), films by what they span
VARIANTS = {
    "no_arcs": dict(bones=("front_L", "front_R", "rear_L", "rear_R", "base_L", "base_R", "ring_tie_L", "ring_tie_L3"), films=("rear window", "near")),
    "no_rear_arcs": dict(bones=("rear_L", "rear_R", "base_L", "base_R", "ring_tie_L3"), films=("rear window",)),
}
FILMS = ["card to lip, left", "card to lip, right", "veil", "top L", "rear window L", "near R", "top R", "rear window R"]      # film_list()'s order


def same(a, b):
    a, b = np.array(a, dtype=float), np.array(b, dtype=float)
    return a.shape == b.shape and np.allclose(a, b)


def main():
    var, out_png = VARIANTS[sys.argv[1]], sys.argv[2]
    hware = hw.build_hardware()
    parts, _ = frame_v0.build_frame(hardware=hware)
    bones_m, lines = of.bone_members()
    films = of.film_list()
    assert len(films) == len(FILMS), (len(films), FILMS)
    ctrl_of = {"lip": of.LIP_BONE, "card": of.CARD_BONE, "brow": of.BROW}
    for s, tag in ((1, "R"), (-1, "L")):
        ctrl_of.update({"ring_" + tag: of.ring(s), "front_" + tag: of.front_sweep(s), "rear_" + tag: of.rear_sweep(s), "side_" + tag: of.side_bone(s), "base_" + tag: of.BASE[s]})
    drop_ctrl = [ctrl_of[b] for b in var["bones"] if b in ctrl_of]
    drop_balls = [c[0] for b in var["bones"] if b.startswith("front_") for c in [ctrl_of[b]]] + [c[-1] for b in var["bones"] if b.startswith("rear_") for c in [ctrl_of[b]]]
    tie_end = {"ring_tie_L": of.front_sweep(-1)[-1]}
    members, dropped = [], []
    for m in bones_m:
        if m[0] == "tube":
            if any(same(m[1], c) for c in drop_ctrl):
                dropped.append("a bone")
                continue
            if "ring_tie_L" in var["bones"] and same(m[1][-1], tie_end["ring_tie_L"]) and len(m[1]) == 3:
                dropped.append("ring_tie_L")
                continue
            if "ring_tie_L3" in var["bones"] and len(m[1]) == 3 and m[1][-1][2] < 0 and abs(m[1][-1][1] - of.RING_TIE_L3_BASE_Y) < 3:
                dropped.append("ring_tie_L3")
                continue
        elif any(same(m[1], p) for p in drop_balls):
            dropped.append("a ball")
            continue
        members.append(m)
    kept_films = [f for f, name in zip(films, FILMS) if not any(name.startswith(k) for k in var["films"])]
    for fm in kept_films:
        members += fm
    lines = {k: v for k, v in lines.items() if k not in var["bones"]}
    print("left out:", ", ".join(var["bones"]), "| films:", ", ".join(n for n in FILMS if any(n.startswith(k) for k in var["films"])), "| members dropped", len(dropped))
    # the pads whose bone is still there (the others have nothing to hold)
    pads = {}
    for name, row in hw.ORGANIC_PADS.items():
        if row[3] != "main":
            continue
        want = of.BONE_OF[name[:-2]]
        if want is not None and f"{want}_{name[-1]}" in lines:       # front_foot ties to "the nearest bone": with its sweep gone that is a 200 mm stub to a ring, so it goes too
            pads[name] = row
    own = []
    for name, row in pads.items():
        try:
            own += of.place_anchors(parts, lines, hware, {name: row})
        except AssertionError as e:
            print("  pad left out:", str(e)[:140])
    for a in own:
        members.append(("ball", tuple(a["q"] + a["n"] * (of.KNOT_R - 4.0)), of.KNOT_R, 8.0))
        members.append(("tube", [a["q"] + a["n"] * (of.PAD_H * 0.6), (a["q"] + a["n"] * of.PAD_H + a["tie"]) / 2 + a["n"] * 3.0, a["tie"]], of.bone(*of.STUB), 8.0))
    F = of.Field()
    for m in members:
        F.add(m)
    of.carve_layer(F, parts, {})
    of.finish_piece(F, own)
    lab, n = ndimage.label(F.d < 0)
    sizes = ndimage.sum(F.d < 0, lab, index=np.arange(1, n + 1)) * F.vox ** 3 / 1000.0
    print(f"what is left: {float((F.d < 0).sum()) * F.vox ** 3 / 1000:.0f} cm3 in {n} bodies (the layer's piece main is 1742 cm3 in one)")
    for k in np.argsort(-sizes):
        idx = np.argwhere(lab == k + 1)
        c = [float(g[int(round(i))]) for g, i in zip((F.xs, F.ys, F.zs), idx.mean(axis=0))]
        held = [a["name"] for a in own if lab[tuple(int(round((a["q"][j] + a["n"][j] * of.PAD_H / 2 + of.across(a["n"])[j] * of.PAD_R * 0.6 - g[0]) / F.vox)) for j, g in enumerate((F.xs, F.ys, F.zs)))] == k + 1]
        print(f"  body {sizes[k]:7.1f} cm3 round X {c[0]:.0f}, Y {c[1]:.0f}, Z {c[2]:.0f}: pads {', '.join(held) if held else 'NONE (it hangs on nothing)'}")
    if "--strength" in sys.argv:
        import tempfile
        import organic_strength as st
        for k in np.argsort(-sizes):
            mine = [a for a in own if lab[tuple(int(round((a["q"][j] + a["n"][j] * of.PAD_H / 2 + of.across(a["n"])[j] * of.PAD_R * 0.6 - g[0]) / F.vox)) for j, g in enumerate((F.xs, F.ys, F.zs)))] == k + 1]
            if not mine:
                continue
            d = np.where(lab == k + 1, F.d, np.float32(F.vox))
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "field.npz")
                np.savez(path, d=d, d_body=d, xs=F.xs, ys=F.ys, zs=F.zs, pieces=np.array(["body"]), pads=np.array([list(a["q"]) + list(a["n"]) for a in mine], dtype=float),
                         names=np.array([a["name"] for a in mine]), pad_piece=np.array(["body"] * len(mine)))
                old, st.FIELD = st.FIELD, path
                try:
                    _l, _f, arr, head = st.run_piece("body", 1)
                finally:
                    st.FIELD = old
            print(f"  strength of the body with {', '.join(a['name'] for a in mine)}: worst {head['stress']:.1f} MPa at ({head['stress_at'][0]:.0f}, {head['stress_at'][1]:.0f}, {head['stress_at'][2]:.0f}), "
                  f"{int((arr['stress'] > st.ALLOW).sum())} of {len(arr['stress'])} over {st.ALLOW:g}; largest movement {head['move']:.1f} mm pushing ({head['move_push'][0]:.0f}, {head['move_push'][1]:.0f}, "
                  f"{head['move_push'][2]:.0f}), {int((arr['move'] > st.MOVE_MAX).sum())} over {st.MOVE_MAX:g}", flush=True)
    saved = np.load(os.path.join(ROOT, "out", "organic", "field.npz"))
    both = np.minimum(F.d, saved["d_rear_panel"])
    actors = rf.scene(layer=False, cable_colours=False)
    vox, sc.VOX = sc.VOX, float(F.vox)
    try:
        shell = sc.mesh(F.xs, F.ys, F.zs, both)
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
    rf.sheet(actors + [a], rf.CORNERS, 2, out_png, parallel=False)
    rf.sheet(actors + [a], {k: rf.SIDES[k] for k in ("front", "rear", "left", "right")}, 2, out_png.replace(".png", "_sides.png"), parallel=True)


if __name__ == "__main__":
    main()
