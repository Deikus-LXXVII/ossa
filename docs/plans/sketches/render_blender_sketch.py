"""The Blender export (cad_b6/render_blender.py) of revision 18's front as sketched in front_sketch.py, not of the model as committed.

Against the committed model the export differs in this, and in nothing else:
  - the organic layer is the sketch's saved field, out/organic/sketch_front_field.npz (array `d`, the union of its pieces);
  - the skeleton part `front_sill` is left out;
  - the hardware solid `light_strip` is left out, and so is the light line (the mesh `light_slit` and the constants `SILL`);
  - the cable `argb` is left out.
render_blender.py's own code does the work: this script filters what it is given (build_frame's parts, build_hardware's solids) and,
after it has written, what it wrote (the slit, the sill's constants, the argb strands).

Run from the repository root:  .venv/bin/python docs/plans/sketches/render_blender_sketch.py [--out out/blender-sketch] [--field FILE]
"""
import json
import os
import sys

import numpy as np

ROOT = os.getcwd()
CAD = os.path.join(ROOT, "cad_b6")
sys.path.insert(0, CAD)

import cadquery  # noqa: E402,F401  (before vtk, as render_blender.py does)
import frame_v0  # noqa: E402
import hardware as hw  # noqa: E402
import render_blender as rb  # noqa: E402

GONE_PARTS = {"front_sill"}
GONE_HW = {"light_strip"}
GONE_MESHES = {"light_slit"}
GONE_CABLES = ("cable_argb_",)


def main():
    out = os.path.join(ROOT, "out", "blender-sketch")
    field = os.path.join(ROOT, "out", "organic", "sketch_front_field.npz")
    args = sys.argv[1:]
    if "--out" in args:
        out = args[args.index("--out") + 1]
    if "--field" in args:
        field = args[args.index("--field") + 1]

    full_hardware = hw.build_hardware
    full_frame = frame_v0.build_frame

    def build_hardware():
        return {k: v for k, v in full_hardware().items() if k not in GONE_HW}

    def build_frame(hardware=None, **kw):
        parts, rest = full_frame(hardware=full_hardware(), **kw)     # the skeleton is built as committed (front_sketch.py does the same), then the sill is left out
        return [p for p in parts if p.name not in GONE_PARTS], rest

    hw.build_hardware, frame_v0.build_frame = build_hardware, build_frame
    sys.argv = [rb.__file__, "--src", CAD, "--out", out, "--field", field]
    rb.main()

    npz_path, json_path = os.path.join(out, "scene.npz"), os.path.join(out, "scene.json")
    with open(json_path) as fh:
        scene = json.load(fh)
    arrays = dict(np.load(npz_path))
    keep_m = [m for m in scene["meshes"] if m["name"] not in GONE_MESHES]
    keep_t = [t for t in scene["tubes"] if not t["name"].startswith(GONE_CABLES)]
    dropped = [m["name"] for m in scene["meshes"] if m not in keep_m] + [t["name"] for t in scene["tubes"] if t not in keep_t]
    for m in scene["meshes"]:
        if m not in keep_m:
            del arrays[m["key"] + "_v"], arrays[m["key"] + "_f"]
    for t in scene["tubes"]:
        if t not in keep_t:
            del arrays[t["key"] + "_p"]
    scene["meshes"], scene["tubes"] = keep_m, keep_t
    scene["hw"].pop("SILL", None)
    scene["state"] = dict(field=field, gone_parts=sorted(GONE_PARTS), gone_hardware=sorted(GONE_HW), dropped=dropped)
    np.savez_compressed(npz_path, **arrays)
    with open(json_path, "w") as fh:
        json.dump(scene, fh, indent=1)
    names = {m["name"] for m in keep_m}
    assert not (names & (GONE_PARTS | GONE_HW | GONE_MESHES)), names & (GONE_PARTS | GONE_HW | GONE_MESHES)
    print("left out after the export:", ", ".join(dropped))
    print(f"sketch state: {len(keep_m)} meshes, {len(keep_t)} tubes -> {out}")


if __name__ == "__main__":
    main()
