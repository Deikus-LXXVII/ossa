"""A joint of the organic layer to print and try by hand before the layer's pieces are printed (docs/plans/layer-split.md).

One half-lap joint by itself, the size split_layer_sketch.py builds on the layer: a bone of radius BONE_R thickened to a knot of radius KNOT_R over a lap LAP long, the knot tapering to
the bone over TAPER; the two halves parted by the plane through the knot's axis; one M3 x 10 through a clearance bore in the half with the head, its head sunk so that CLAMP of
plastic is under it (the layer's pads clamp the same 5 mm), into a heat-set insert in the other half. Each half has a stub of bone STUB long to hold it by.

Three files, the same two halves lying three ways, because a piece of the layer has up to six joints that point different ways and cannot lie well for all of them:
  joint_up.stl      the lap's faces up (the top surface of the print), the screw upright: the best case
  joint_wall.stl    the lap's faces upright (printed as walls), the screw lying
  joint_down.stl    the lap's faces down, on supports: the worst case

Run from the repository root:  .venv/bin/python docs/plans/sketches/joint_trial.py [OUT_DIR]     (out/trial/joint by default)
"""
import os
import sys

import numpy as np

ROOT = os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "cad_b6"))
import cadquery  # noqa: F401  (before vtk)
import vtk
from vtk.util import numpy_support
import hardware as hw
import shell_concepts as sc

VOX = 0.4
BONE_R, KNOT_R, LAP, TAPER, STUB = 6.0, 10.0, 20.0, 8.0, 35.0
SHOULDER = 0.5                              # between a tongue's tip and the other half's shoulder; the faces the screw closes get none
CLAMP = hw.ORGANIC_PAD_H                    # plastic under the screw's head, as at the layer's pads
BORE, HEAD_D = 3.4, 6.5                     # the clearance bore and the recess for an M3 cap head (5.5)
PILOT, PILOT_DEPTH = hw.M3_PILOT_D, hw.M3_PILOT_DEPTH      # the insert's pilot, as the skeleton drills it
END = LAP / 2 + TAPER + STUB                # a half's far end, from the screw


def half(sign, X, Y, Z):
    """The signed distance of one half: +1 the half with the head (whole for X <= -LAP/2, its tongue above the parting plane), -1 the half with the insert (the mirror)."""
    x, z = sign * X, sign * Z
    ax = np.abs(x)
    r_of = np.where(ax <= LAP / 2, KNOT_R, np.maximum(KNOT_R - (KNOT_R - BONE_R) * (ax - LAP / 2) / TAPER, BONE_R))
    body = np.sqrt(Y ** 2 + Z ** 2) - r_of
    body = np.where(x < -END, np.sqrt((x + END) ** 2 + Y ** 2 + Z ** 2) - BONE_R, body)        # the stub's round end
    region = np.minimum(x + LAP / 2, np.maximum(x - (LAP / 2 - SHOULDER), -z))
    d = np.maximum(body, region)
    r = np.sqrt(X ** 2 + Y ** 2)
    if sign > 0:
        hole = np.maximum(BORE / 2 - r, np.minimum(HEAD_D / 2 - r, z - CLAMP))
    else:
        hole = np.minimum(PILOT / 2 - r, PILOT_DEPTH - z)                                       # blind: PILOT_DEPTH into the tongue from the parting plane
    return np.maximum(d, hole).astype(np.float32)


def meshes():
    # the grid stands off the joint's own planes (the parting plane, the shoulders): a face that passes exactly through grid points leaves the mesher open edges
    xs = np.arange(-END - BONE_R - 2, LAP / 2 + 2 + VOX, VOX) + 0.07
    ys = np.arange(-KNOT_R - 2, KNOT_R + 2 + VOX, VOX) + 0.13
    zs = np.arange(-KNOT_R - 2, KNOT_R + 2 + VOX, VOX) + 0.17
    sc.VOX = VOX
    out = {}
    for sign, name in ((1, "head"), (-1, "insert")):
        gx = xs if sign > 0 else -xs[::-1]
        X, Y, Z = np.meshgrid(gx, ys, zs, indexing="ij")
        clean = vtk.vtkCleanPolyData()                           # the mesher's normals split points along sharp edges; an STL has no shared points anyway
        clean.SetInputData(sc.mesh(gx, ys, zs, half(sign, X, Y, Z)))
        rev = vtk.vtkReverseSense()                              # shell_concepts.mesh winds its triangles facing inward (the field is negative inside); a slicer wants them outward
        rev.SetInputConnection(clean.GetOutputPort())
        rev.ReverseCellsOn()
        rev.ReverseNormalsOn()
        rev.Update()
        out[name] = rev.GetOutput()
    return out


def measure(name, poly):
    v = numpy_support.vtk_to_numpy(poly.GetPoints().GetData())
    sign = 1 if name == "head" else -1
    x, z = sign * v[:, 0], sign * v[:, 2]
    r = np.hypot(v[:, 0], v[:, 1])
    face = v[(np.abs(v[:, 0]) < LAP / 2 - 3) & (np.abs(v[:, 2]) < 0.5) & (r > 4.5) & (np.abs(v[:, 1]) < KNOT_R - 3)]
    if sign > 0:
        bore = r[(z > 1.0) & (z < CLAMP - 1.0) & (r < BORE / 2 + 0.6)]
        rec = r[(z > CLAMP + 1.0) & (z < KNOT_R - 1.5) & (r < HEAD_D / 2 + 0.6) & (r > BORE / 2 + 0.5)]
        holes = f"bore asked {BORE}: {2 * bore.mean():.2f} ({2 * bore.min():.2f}..{2 * bore.max():.2f}); head's recess asked {HEAD_D}: {2 * rec.mean():.2f} ({2 * rec.min():.2f}..{2 * rec.max():.2f})"
    else:
        pil = r[(z > 1.0) & (z < PILOT_DEPTH - 1.0) & (r < PILOT / 2 + 0.6)]
        floor = z[(r < PILOT / 2 - 0.8) & (z > PILOT_DEPTH - 1.5) & (z < PILOT_DEPTH + 1.5)]
        holes = (f"pilot asked {PILOT}: {2 * pil.mean():.2f} ({2 * pil.min():.2f}..{2 * pil.max():.2f}), its floor {floor.mean():.2f} below the face (asked {PILOT_DEPTH}), "
                 f"{KNOT_R - floor.mean():.2f} of plastic under it")
    tip = x[(np.abs(v[:, 1]) < 4.0) & (z > 3.0) & (z < 7.0) & (x > LAP / 2 - 2.0)]
    edges = vtk.vtkFeatureEdges()
    edges.SetInputData(poly)
    edges.BoundaryEdgesOn()
    edges.NonManifoldEdgesOn()
    edges.FeatureEdgesOff()
    edges.ManifoldEdgesOff()
    edges.Update()
    conn = vtk.vtkPolyDataConnectivityFilter()
    conn.SetInputData(poly)
    conn.SetExtractionModeToAllRegions()
    conn.Update()
    mass = vtk.vtkMassProperties()
    mass.SetInputData(poly)
    return (f"{name}: {mass.GetVolume() / 1000:.1f} cm3, {poly.GetNumberOfCells()} triangles, open or doubled edges {edges.GetOutput().GetNumberOfCells()}, bodies {conn.GetNumberOfExtractedRegions()}; "
            f"lap face at {face[:, 2].mean():+.3f} ({face[:, 2].min():+.3f}..{face[:, 2].max():+.3f}); tongue's tip at {tip.max():.2f} from the screw (asked {LAP / 2 - SHOULDER}); {holes}")


def placed(poly, turn_x, shift_y):
    """The half turned about the bar's axis by turn_x degrees, set down on the bed (lowest point at Z 0) and moved along Y."""
    t = vtk.vtkTransform()
    t.RotateX(turn_x)
    f = vtk.vtkTransformPolyDataFilter()
    f.SetInputData(poly)
    f.SetTransform(t)
    f.Update()
    b = f.GetOutput().GetBounds()
    t2 = vtk.vtkTransform()
    t2.Translate(-(b[0] + b[1]) / 2, shift_y - (b[2] + b[3]) / 2, -b[4])
    g = vtk.vtkTransformPolyDataFilter()
    g.SetInputData(f.GetOutput())
    g.SetTransform(t2)
    g.Update()
    return g.GetOutput()


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "out", "trial", "joint")
    os.makedirs(out_dir, exist_ok=True)
    m = meshes()
    for name, poly in m.items():
        print(measure(name, poly))
    # the head half as modelled has its lap face down (it lies on the insert half), the insert half has it up
    ways = {"up": dict(head=180.0, insert=0.0), "wall": dict(head=90.0, insert=90.0), "down": dict(head=0.0, insert=180.0)}
    for way, turns in ways.items():
        app = vtk.vtkAppendPolyData()
        for k, (name, poly) in enumerate(m.items()):
            app.AddInputData(placed(poly, turns[name], (k - 0.5) * 32.0))
        app.Update()
        b = app.GetOutput().GetBounds()
        path = os.path.join(out_dir, f"joint_{way}.stl")
        w = vtk.vtkSTLWriter()
        w.SetFileName(path)
        w.SetFileTypeToBinary()
        w.SetInputData(app.GetOutput())
        w.Write()
        both = app.GetOutput()
        v = numpy_support.vtk_to_numpy(both.GetPoints().GetData())
        tri = numpy_support.vtk_to_numpy(both.GetPolys().GetConnectivityArray()).reshape(-1, 3)
        p0, p1, p2 = v[tri[:, 0]], v[tri[:, 1]], v[tri[:, 2]]
        nrm = np.cross(p1 - p0, p2 - p0)
        area = np.linalg.norm(nrm, axis=1) / 2
        nz, ny = nrm[:, 2] / (2 * area + 1e-12), nrm[:, 1] / (2 * area + 1e-12)
        vol = float(np.einsum("ij,ij->i", p0, np.cross(p1, p2)).sum()) / 6000.0
        print(f"saved {path}: {b[1] - b[0]:.0f} x {b[3] - b[2]:.0f} x {b[5] - b[4]:.0f} mm, {os.path.getsize(path) / 1e6:.1f} MB; volume by its triangles {vol:.1f} cm3 (positive: they face outward); "
              f"flat faces: up {area[nz > 0.999].sum():.0f} mm2, down {area[nz < -0.999].sum():.0f}, upright {area[np.abs(ny) > 0.999].sum():.0f}")


if __name__ == "__main__":
    main()
