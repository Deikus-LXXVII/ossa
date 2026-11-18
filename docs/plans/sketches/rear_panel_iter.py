"""Try variants of the rear panel's numbers against organic_strength.py's limits, quickly: only the piece `rear_panel` is built (the piece `main` is read from the saved field)
and only it is pushed. A design aid of the main session; the limits are organic_strength.py's own and are not touched.

Run from the repository root:  .venv/bin/python docs/plans/sketches/rear_panel_iter.py <variant> [<variant> ...]
A variant is a name from VARIANTS below.
"""
import os
import sys
import tempfile

import numpy as np

ROOT = os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "cad_b6"))
import hardware as hw
import frame_v0
import organic_frame as of
import organic_strength as st


def frame(half_x, y_low=384.0, z_low=104.0, y_top=360.0, z_top=250.0):
    return dict(PANEL_LOW=[(-half_x, y_low, z_low), (0.0, y_low + 2.0, z_low + 2.0), (half_x, y_low, z_low)],
                PANEL_TOP=[(-half_x, y_top, z_top), (0.0, y_top + 2.0, z_top + 3.0), (half_x, y_top, z_top)])


VARIANTS = {
    "base": {},
    "thick": dict(frame(128.5), PANEL_R=8.5),
    "thick_legs": dict(frame(128.5), PANEL_R=8.5, PANEL_LEG=(9.0, 8.5, 9.0), PANEL_BRACE=(8.5, 8.0, 8.5), PANEL_BRACE_X=(116.0, 102.0, 88.0)),
    "thick_legs_flat": dict(frame(128.5), PANEL_R=8.5, PANEL_LEG=(9.0, 8.5, 9.0), PANEL_BRACE=(8.5, 8.0, 8.5), PANEL_BRACE_X=(116.0, 102.0, 88.0), PANEL_Y_FLAT=392.9),
    # held at the top as well: two more pads on the posts' rear faces (X 150 reaches X 158: the piece is 316 mm wide and does not lie flat on the bed)
    "posts": dict(_top=((150.0, 348.0, 236.0),)),
    "posts_hip_only": dict(_top=((150.0, 348.0, 236.0),), _drop=("panel_foot",)),
    "low": dict(frame(128.5, z_top=225.0, y_top=364.0), PANEL_R=8.5, PANEL_LEG=(9.0, 8.5, 9.0), PANEL_BRACE=(8.5, 8.0, 8.5), PANEL_BRACE_X=(116.0, 102.0, 88.0)),
}


def main():
    hware = hw.build_hardware()
    parts, _ = frame_v0.build_frame(hardware=hware)
    saved = np.load(os.path.join(ROOT, "out", "organic", "field.npz"))
    d_main = saved["d_main"]
    skel = {}
    keep = {k: getattr(of, k) for k in ("PANEL_LOW", "PANEL_TOP", "PANEL_R", "PANEL_LEG", "PANEL_BRACE", "PANEL_BRACE_X", "PANEL_BRACE_YZ", "PANEL_Y_FLAT", "PANEL_FILM", "PANEL_CORNER_R")}
    for name in sys.argv[1:]:
        for k, v in keep.items():
            setattr(of, k, v)
        var = VARIANTS[name]
        for k, v in var.items():
            if not k.startswith("_"):
                setattr(of, k, v)
        if "PANEL_LOW" in VARIANTS[name]:
            of.PANEL_BRACE_YZ = (of.PANEL_LOW[0][1], of.PANEL_LOW[0][2] + 1.0)
        bones_m, lines, films = of.panel_frame()
        all_lines = dict(of.bone_members()[1], **lines)
        pads = {k: v for k, v in hw.ORGANIC_PADS.items() if v[3] == "rear_panel"}
        own = [a for a in of.place_anchors(parts, lines, hware, pads, driver_lines=all_lines) if a["name"][:-2] not in var.get("_drop", ())]
        extra = [dict(name=f"panel_top_{'R' if sx > 0 else 'L'}", q=np.array([sx * x, y, z]), n=np.array([0.0, 1.0, 0.0]), tie=None) for (x, y, z) in var.get("_top", ()) for sx in (1, -1)]
        members = list(bones_m)
        for a in extra:      # not in hardware.py: a sketch. A knot and one leg to the frame's upper corner on its side
            corner = np.array(of.PANEL_TOP[-1] if a["q"][0] > 0 else of.PANEL_TOP[0], dtype=float)
            members.append(("ball", tuple(a["q"] + a["n"] * (of.KNOT_R - 4.0)), of.KNOT_R, 8.0))
            members.append(("tube", [a["q"] + a["n"] * (of.PAD_H * 0.6), (a["q"] + a["n"] * of.PAD_H + corner) / 2 + a["n"] * 2.0, corner], of.bone(*of.PANEL_LEG), 8.0))
        for fm in films:
            members += fm
        for a in own:
            members.append(("ball", tuple(a["q"] + a["n"] * (of.KNOT_R - 4.0)), of.KNOT_R, 8.0))
            members += of.panel_legs(a)
        F = of.Field()
        for m in members:
            F.add(m)
        of.carve_layer(F, parts, skel)
        of.carve_panel(F, hware)
        np.maximum(F.d, of.GAP_PIECE - d_main, out=F.d)
        own = own + extra
        of.finish_piece(F, own)
        solid = F.d < 0
        idx = np.argwhere(solid)
        ext = [(float(c[lo]) - F.vox / 2, float(c[hi]) + F.vox / 2) for c, lo, hi in zip((F.xs, F.ys, F.zs), idx.min(axis=0), idx.max(axis=0))]
        cm3 = float(solid.sum()) * F.vox ** 3 / 1000.0
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "field.npz")
            np.savez(path, d=F.d, d_rear_panel=F.d, xs=F.xs, ys=F.ys, zs=F.zs, pieces=np.array(["rear_panel"]),
                     pads=np.array([list(a["q"]) + list(a["n"]) for a in own], dtype=float), names=np.array([a["name"] for a in own]), pad_piece=np.array(["rear_panel"] * len(own)))
            old, st.FIELD = st.FIELD, path
            try:
                _lines, fails, arr, head = st.run_piece("rear_panel", 1)
            finally:
                st.FIELD = old
        over_s = int((arr["stress"] > st.ALLOW).sum())
        over_m = int((arr["move"] > st.MOVE_MAX).sum())
        print(f"{name:16} {cm3:6.1f} cm3  X {ext[0][1] - ext[0][0]:5.1f}  Y ..{ext[1][1]:.2f}  Z {ext[2][0]:.1f}..{ext[2][1]:.1f} | stress {head['stress']:5.1f} MPa at "
              f"({head['stress_at'][0]:.0f}, {head['stress_at'][1]:.0f}, {head['stress_at'][2]:.0f}), {over_s} over | move {head['move']:5.2f} mm pushing "
              f"({head['move_push'][0]:.0f}, {head['move_push'][1]:.0f}, {head['move_push'][2]:.0f}), {over_m} over | reactions {arr['reactions'][:, 1:].max():.0f} N", flush=True)


if __name__ == "__main__":
    main()
