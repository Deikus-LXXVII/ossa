"""Can the layer's 1.5 mm field and its mesher make a half-lap joint that fits? Two half-knots of radius R over a lap of length LAP, parted by a plane through the bar's axis
with GAP between the faces, a 3.4 mm clearance bore in the upper half and a 4.5 mm insert pilot in the lower; meshed as the layer is (shell_concepts.mesh). Measures what comes out."""
import sys
import numpy as np
sys.path.insert(0, "cad_b6")
import cadquery  # noqa: F401
from vtk.util import numpy_support
import shell_concepts as sc
R, LAP, GAP, BORE, PILOT, PILOT_DEPTH = 10.0, 24.0, 0.3, 3.4, 4.5, 6.7
for vox, off in ((1.5, 0.0), (1.5, 0.6), (0.75, 0.3)):
    xs = np.arange(-40, 40 + vox, vox) + off
    ys = np.arange(-16, 16 + vox, vox) + off * 0.7
    zs = np.arange(-16, 16 + vox, vox) + off * 0.4
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    bar = np.sqrt(Y ** 2 + Z ** 2) - R                                   # a knot's cylinder along X
    def half(s_):                                                        # +1: the upper half, whole for X <= -LAP/2 and above the parting plane to LAP/2 - GAP; -1: its mirror
        d_a = s_ * X + LAP / 2
        d_b = np.maximum(s_ * X - (LAP / 2 - GAP), GAP / 2 - s_ * Z)
        d = np.maximum(bar, np.minimum(d_a, d_b))
        hole = (BORE if s_ > 0 else PILOT) / 2 - np.sqrt(X ** 2 + Y ** 2)
        if s_ < 0:
            hole = np.minimum(hole, Z + PILOT_DEPTH)                     # the pilot is blind: no hole below its depth
        return np.maximum(d, hole).astype(np.float32)
    sc.VOX = vox
    out = []
    for sign, name in ((1, "upper"), (-1, "lower")):
        poly = sc.mesh(xs, ys, zs, half(sign))
        v = numpy_support.vtk_to_numpy(poly.GetPoints().GetData())
        face = v[(np.abs(v[:, 0]) < LAP / 2 - 4) & (np.abs(v[:, 2] - sign * GAP / 2) < 0.6) & (np.hypot(v[:, 0], v[:, 1]) > 4.5) & (np.abs(v[:, 1]) < R - 3)]
        r = np.hypot(v[:, 0], v[:, 1])
        zsel = (v[:, 2] * sign > (2.0 if sign > 0 else 1.5)) & (v[:, 2] * sign < (R - 2.5 if sign > 0 else PILOT_DEPTH - 1.5))
        bore = r[zsel & (r < (BORE if sign > 0 else PILOT) / 2 + 0.8)]
        want = (BORE if sign > 0 else PILOT)
        near = r[zsel & (r < 6.0)]
        st = lambda a: "none" if len(a) == 0 else f"mean {2 * a.mean():.2f}, least {2 * a.min():.2f}, largest {2 * a.max():.2f} ({len(a)} points)"
        out.append(f"{name}: lap face Z {face[:, 2].mean():+.3f} (asked {sign * GAP / 2:+.2f}), spread {face[:, 2].min():+.3f}..{face[:, 2].max():+.3f}, {len(face)} points; "
                   f"hole diameter asked {want}: {st(bore)}; any surface within 6 mm of the axis: {st(near)}")
    print(f"grid {vox} mm, shifted {off}:\n  " + "\n  ".join(out))
