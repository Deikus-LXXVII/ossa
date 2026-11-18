"""Does the layer stand in a skeleton screw's head or washer? Every screw of assembly_access.py against the solid voxels of a saved field.

On the committed layer (out/organic/field.npz at 772787a) 22 of the 120 screws have voxels of `main` in their head, up to 24 each: the screws on the ribs' outer faces that hold
beam_front, the skids, the PSU bulkhead, the ribs' lap and the visor arms. The layer is carved 2 mm off the printed parts; a head with its washer stands 3.5 mm proud.

Run from the repository root:  .venv/bin/python docs/plans/sketches/heads_vs_layer.py <field.npz>
"""
import sys
import numpy as np
sys.path.insert(0, "cad_b6")
import hardware as hw, frame_v0, assembly_access as aa, organic_frame as of

f = np.load(sys.argv[1])
xs, ys, zs = f["xs"].astype(float), f["ys"].astype(float), f["zs"].astype(float)
solid = {str(p): f["d_" + str(p)] < 0 for p in f["pieces"]}
hware = hw.build_hardware()
parts, _ = frame_v0.build_frame(hardware=hware)
model, fails = aa.model_of(parts, hware, frame_v0.FASTENERS)
s0 = model["screws"][0]
print("fields:", sorted(s0.keys()))
rows = []
for s in model["screws"]:
    seat, e = np.array(s["seat"], dtype=float), np.array(s["e"], dtype=float)       # the seat under the washer and the axis pointing out of the head
    h1 = s["washer_t"] + s["head_h"]
    for piece, m in solid.items():
        for label, r, a, b in (("washer", hw.M3_WASHER_D / 2 if s["washer_t"] > 0 else s["head_d"] / 2, 0.0, max(s["washer_t"], 0.01)), ("head", s["head_d"] / 2, 0.0, h1)):
            sl, mask = of.cylinder_mask(xs, ys, zs, seat, e, r, a, b)
            n = int((m[sl] & mask).sum())
            if n:
                rows.append((n, piece, label, s["id"], s["part"], tuple(round(float(c), 1) for c in seat), tuple(round(float(c), 2) for c in e)))
rows.sort(reverse=True)
print(len(model["screws"]), "screws;", len({r[3] for r in rows}), "have layer voxels inside the head or washer")
for r in rows[:40]:
    print("  %4d voxels of %-10s in the %-6s of %s (%s) at %s along %s" % r)
