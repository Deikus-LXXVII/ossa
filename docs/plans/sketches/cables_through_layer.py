"""Do the routed cables and the hoses pass through the organic layer? For every strand of cables.build_routes() and every hose of hoses.routes(): the least of the layer's
signed distance along the strand's centre line, less the strand's radius (negative: the strand's surface is inside the layer), and where.

Run from the repository root:  .venv/bin/python docs/plans/sketches/cables_through_layer.py [field.npz ...]
"""
import os
import sys

import numpy as np
from scipy import ndimage

ROOT = os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "cad_b6"))
import cables
import hoses


def densify(pts, step=1.0):
    pts = np.asarray(pts, dtype=float)
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:]):
        n = max(int(np.ceil(np.linalg.norm(b - a) / step)), 1)
        out += [a + (b - a) * k / n for k in range(1, n + 1)]
    return np.array(out)


def main():
    lines = [(f"cable {name}[{k}]", densify(p), float(r)) for name, rt in cables.build_routes().items() for k, (p, r) in enumerate(rt.strands)]
    lines += [(f"hose {name}[{k}]", densify(h["pts"]), float(spec["r"])) for name, (pair, spec) in hoses.routes().items() for k, h in enumerate(pair)]
    for path in sys.argv[1:] or [os.path.join(ROOT, "out", "organic", "field.npz")]:
        f = np.load(path)
        d, xs, ys, zs = f["d"], f["xs"].astype(float), f["ys"].astype(float), f["zs"].astype(float)
        vox = xs[1] - xs[0]
        print(f"{path}: layer {float((d < 0).sum()) * vox ** 3 / 1000:.0f} cm3")
        for name, pts, r in lines:
            idx = np.array([(pts[:, 0] - xs[0]) / vox, (pts[:, 1] - ys[0]) / vox, (pts[:, 2] - zs[0]) / vox])
            val = ndimage.map_coordinates(d, idx, order=1, mode="nearest")
            inside = np.all((idx.T >= 0) & (idx.T <= np.array(d.shape) - 1), axis=1)
            val = np.where(inside, val, 1e9)
            gap = val - r
            k = int(np.argmin(gap))
            bad = gap < 0
            length = float(bad.sum())            # the points are about 1 mm apart
            print(f"  {name:18} r {r:4.1f}: least gap to the layer {gap[k]:7.1f} mm at X {pts[k][0]:6.1f}, Y {pts[k][1]:6.1f}, Z {pts[k][2]:6.1f}"
                  + (f"   INSIDE the layer over about {length:.0f} mm of its length" if bad.any() else ""))


if __name__ == "__main__":
    main()
