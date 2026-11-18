"""Export the whole design as meshes and centre lines for the Blender render (cad_b6/blender_scene.py).

Run:  .venv/bin/python cad_b6/render_blender.py [--src DIR] [--out DIR] [--field FILE]
        --src    the cad_b6 directory to import the model from (default: this file's directory). Point it at an extracted
                 commit (git archive <rev> cad_b6 | tar -x -C <dir>) to export a snapshot instead of the working tree.
        --out    where to write (default: out/blender/)
        --field  the organic layer's field (default: out/organic/field.npz, written by organic_frame.py)
Out:  <out>/scene.npz   every mesh (vertices, triangles) and every tube's centre line, world mm
      <out>/scene.json  what each array is (name, kind, material, radius) and every constant of hardware.py

What is exported, all of it straight from the model, nothing restyled:
  part      every skeleton part of frame_v0.build_frame(), tessellated (ABS, or PA6 for the two hose guides)
  organic   the organic layer: shell_concepts.mesh() of the field, as render_full.py draws it
  hw_box    hardware.build_hardware(): the block-out boxes. Blender does not draw them; it builds its stand-ins from the
            constants in scene.json and checks each stand-in against its box
  hose      hoses.routes(): centre line and radius of the four hoses
  cable     cables.build_routes(): centre line and radius of every strand

Nothing is checked here and no file of the model is written.
"""
import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOL, ANG = 0.05, 0.12          # tessellation: chord error in mm, angle in rad (a 3 mm rounding gets 13 facets per quarter turn)


def weld(v, f):
    """Merge coincident vertices (cadquery tessellates face by face) and drop the triangles that collapse."""
    v = np.asarray(v, dtype=np.float64).reshape(-1, 3)
    f = np.asarray(f, dtype=np.int64).reshape(-1, 3)
    key = np.round(v, 3)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    f = inv.reshape(-1)[f]
    keep = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])
    return uniq.astype(np.float32), f[keep].astype(np.int32)


def outward(v, f):
    """Triangles wound so that the normals point out of the solid (signed volume positive)."""
    a, b, c = (v[f[:, k]].astype(np.float64) for k in range(3))
    if np.einsum("ij,ij->i", a, np.cross(b, c)).sum() < 0:
        f = f[:, ::-1].copy()
    return v, f


def tess(shape):
    vs, fs, n = [], [], 0
    for s in shape.Solids():
        verts, tris = s.tessellate(TOL, ANG)
        vs.append(np.array([(p.x, p.y, p.z) for p in verts], dtype=np.float64).reshape(-1, 3))
        fs.append(np.array(tris, dtype=np.int64).reshape(-1, 3) + n)
        n += len(verts)
    return outward(*weld(np.vstack(vs), np.vstack(fs)))


def jsonable(x):
    try:
        json.dumps(x)
        return True
    except (TypeError, ValueError):
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=HERE)
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "blender"))
    ap.add_argument("--field", default=os.path.join(ROOT, "out", "organic", "field.npz"))
    a = ap.parse_args()
    src = os.path.abspath(a.src)
    sys.path.insert(0, src)
    import cadquery as cq  # noqa: F401  (before vtk, see render_vtk.py)
    import cables
    import frame_v0
    import hardware as hw
    import hoses
    import shell_concepts as sc
    from vtk.util import numpy_support

    t0 = time.time()
    arrays, meshes, tubes = {}, [], []

    def add_mesh(name, kind, material, v, f, note=""):
        k = f"m{len(meshes)}"
        arrays[k + "_v"], arrays[k + "_f"] = v, f
        meshes.append(dict(key=k, name=name, kind=kind, material=material, note=note, tris=int(len(f))))

    def add_tube(name, kind, pts, r):
        k = f"t{len(tubes)}"
        arrays[k + "_p"] = np.asarray(pts, dtype=np.float32).reshape(-1, 3)
        tubes.append(dict(key=k, name=name, kind=kind, r=float(r)))

    hardware = hw.build_hardware()
    parts, _ = frame_v0.build_frame(hardware=hardware)
    for p in parts:
        add_mesh(p.name, "part", p.material, *tess(p.solid), note=p.note)
    print(f"skeleton: {len(parts)} parts, {time.time() - t0:.0f} s")

    for name, solid in hardware.items():
        if name not in hw.HOSES:
            add_mesh(name, "hw_box", "", *tess(solid))

    f = np.load(a.field)
    vox, sc.VOX = sc.VOX, float(f["xs"][1] - f["xs"][0])
    try:
        shell = sc.mesh(f["xs"], f["ys"], f["zs"], f["d"])
    finally:
        sc.VOX = vox
    v = numpy_support.vtk_to_numpy(shell.GetPoints().GetData()).astype(np.float32)
    cells = numpy_support.vtk_to_numpy(shell.GetPolys().GetData()).reshape(-1, 4)
    assert (cells[:, 0] == 3).all(), "the organic layer's mesh is triangles"
    add_mesh("organic_layer", "organic", "PETG", *outward(v, cells[:, 1:].astype(np.int32)))

    for name, (pair, spec) in hoses.routes().items():
        for i, h in enumerate(pair):
            add_tube(f"hose_{name}_{i}", "hose_" + name, h["pts"], spec["r"])
    for name, rt in cables.build_routes().items():
        for i, (pts, r) in enumerate(rt.strands):
            add_tube(f"cable_{name}_{i}", "cable", pts, r)

    consts = {k: getattr(hw, k) for k in dir(hw) if k.isupper() and jsonable(getattr(hw, k))}
    consts["DRIVE_LAYOUT"] = hw.drive_layout()
    os.makedirs(a.out, exist_ok=True)
    np.savez_compressed(os.path.join(a.out, "scene.npz"), **arrays)
    with open(os.path.join(a.out, "scene.json"), "w") as fh:
        json.dump(dict(source=src, meshes=meshes, tubes=tubes, hw=consts), fh, indent=1)
    print(f"{len(meshes)} meshes ({sum(m['tris'] for m in meshes)} triangles), {len(tubes)} tubes -> {a.out}  ({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
