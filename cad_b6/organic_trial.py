"""A trial piece of the organic layer for the print test (PETG against ABS): the part of the layer inside a box, cut flat at the box's faces, as an STL.

Run:  .venv/bin/python cad_b6/organic_trial.py
In:   out/organic/field.npz (written by organic_frame.py)
Out:  out/organic/trial_<name>.stl, previews/b6_organic_trial_<name>.png, a few lines on the piece

The piece is not a part of the case. It is there to learn how the layer's shapes print: thin round members, a branch, a screw pad with its M3 bore and driver
channel, overhangs that need support. It carries the layer's present surface, steps of the 1.5 mm field included; the smoothing of that surface is still open
(docs/plans/cables-and-organic.md). Print it without scaling. Out of out/ nothing is tracked.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cadquery as cq  # noqa: F401  (before vtk, see render_vtk.py)
import vtk

import organic_frame
import shell_concepts as sc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# name -> (pad the piece is drawn round, box (x0, x1, y0, y1, z0, z1) in world mm). The box is chosen by hand so that the piece holds a stretch of a bone, a pad and the
# start of a film, and stays one piece
TRIALS = {"base_mid_R": ("base_mid_R", (148.0, 200.0, 195.0, 305.0, -15.0, 45.0))}
PETG_RHO = organic_frame.LAYER_RHO if hasattr(organic_frame, "LAYER_RHO") else 1.27       # g/cm3


def cut(field, box):
    """The field with everything outside `box` removed: the same signed distance, raised to the distance outside the box."""
    xs, ys, zs = field["xs"].astype(float), field["ys"].astype(float), field["zs"].astype(float)
    x0, x1, y0, y1, z0, z1 = box
    out = np.maximum.reduce([np.broadcast_to((x0 - xs)[:, None, None], field["d"].shape), np.broadcast_to((xs - x1)[:, None, None], field["d"].shape),
                             np.broadcast_to((y0 - ys)[None, :, None], field["d"].shape), np.broadcast_to((ys - y1)[None, :, None], field["d"].shape),
                             np.broadcast_to((z0 - zs)[None, None, :], field["d"].shape), np.broadcast_to((zs - z1)[None, None, :], field["d"].shape)])
    return xs, ys, zs, np.maximum(field["d"], out)


def surface(xs, ys, zs, d):
    vox, sc.VOX = sc.VOX, float(xs[1] - xs[0])
    try:
        return sc.mesh(xs, ys, zs, d)
    finally:
        sc.VOX = vox


def largest_piece(poly):
    """(the largest connected piece as closed triangles, number of pieces)."""
    conn = vtk.vtkPolyDataConnectivityFilter()
    conn.SetInputData(poly)
    conn.SetExtractionModeToLargestRegion()
    conn.Update()
    n = conn.GetNumberOfExtractedRegions()
    tri = vtk.vtkTriangleFilter()
    tri.SetInputConnection(conn.GetOutputPort())
    clean = vtk.vtkCleanPolyData()
    clean.SetInputConnection(tri.GetOutputPort())
    clean.Update()
    return clean.GetOutput(), n


def open_edges(poly):
    fe = vtk.vtkFeatureEdges()
    fe.SetInputData(poly)
    fe.BoundaryEdgesOn()
    fe.NonManifoldEdgesOn()
    fe.FeatureEdgesOff()
    fe.ManifoldEdgesOff()
    fe.Update()
    return fe.GetOutput().GetNumberOfCells()


def picture(poly, path):
    m = vtk.vtkPolyDataMapper()
    m.SetInputData(poly)
    m.ScalarVisibilityOff()
    a = vtk.vtkActor()
    a.SetMapper(m)
    a.GetProperty().SetColor(0.20, 0.20, 0.22)
    a.GetProperty().SetSpecular(0.25)
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.SetSize(1600, 700)
    win.SetMultiSamples(0)
    for i, direction in enumerate(((1.0, -0.8, 0.6), (-1.0, 0.6, 0.5))):
        ren = vtk.vtkRenderer()
        ren.SetBackground(1, 1, 1)
        ren.SetViewport(i / 2, 0, (i + 1) / 2, 1)
        ren.UseFXAAOn()
        ren.AddActor(a)
        cam = ren.GetActiveCamera()
        cam.SetFocalPoint(0, 0, 0)
        cam.SetPosition(*direction)
        cam.SetViewUp(0, 0, 1)
        ren.ResetCamera()
        win.AddRenderer(ren)
    win.Render()
    grab = vtk.vtkWindowToImageFilter()
    grab.SetInput(win)
    grab.Update()
    wr = vtk.vtkPNGWriter()
    wr.SetFileName(path)
    wr.SetInputConnection(grab.GetOutputPort())
    wr.Write()


def main():
    field = np.load(os.path.join(ROOT, "out", "organic", "field.npz"))
    names = [str(n) for n in field["names"]]
    fails = []
    for name, (pad, box) in TRIALS.items():
        poly, pieces = largest_piece(surface(*cut(field, box)))
        if poly.GetNumberOfCells() == 0:
            fails.append(f"ORGANIC_TRIAL {name}: nothing of the layer is inside the box {box}")
            continue
        mp = vtk.vtkMassProperties()
        mp.SetInputData(poly)
        b = poly.GetBounds()
        gaps = open_edges(poly)
        p = field["pads"][names.index(pad)][:3]
        inside = all(box[2 * k] <= p[k] <= box[2 * k + 1] for k in range(3))
        stl = os.path.join(ROOT, "out", "organic", f"trial_{name}.stl")
        wr = vtk.vtkSTLWriter()
        wr.SetFileName(stl)
        wr.SetInputData(poly)
        wr.SetFileTypeToBinary()
        wr.Write()
        png = os.path.join(ROOT, "previews", f"b6_organic_trial_{name}.png")
        picture(poly, png)
        print(f"{name}: box X {box[0]:g}..{box[1]:g}, Y {box[2]:g}..{box[3]:g}, Z {box[4]:g}..{box[5]:g}")
        print(f"  piece {b[1] - b[0]:.0f} x {b[3] - b[2]:.0f} x {b[5] - b[4]:.0f} mm, {mp.GetVolume() / 1000:.1f} cm3, {mp.GetVolume() / 1000 * PETG_RHO:.0f} g of solid PETG, "
              f"{poly.GetNumberOfCells()} triangles, pieces in the box {pieces} (the largest is kept), open edges {gaps}")
        print(f"  pad {pad} at ({p[0]:.0f}, {p[1]:.0f}, {p[2]:.0f}) is {'inside' if inside else 'OUTSIDE'} the box")
        print(f"  -> {stl}\n  -> {png}")
        if pieces != 1:
            fails.append(f"ORGANIC_TRIAL {name}: the box holds {pieces} separate pieces of the layer; move the box so that the trial is one piece")
        if gaps:
            fails.append(f"ORGANIC_TRIAL {name}: the surface has {gaps} open edges, a slicer may not take it")
        if not inside:
            fails.append(f"ORGANIC_TRIAL {name}: the pad {pad} is not inside the box")
    if fails:
        print("\n".join(fails))
        sys.exit(1)


if __name__ == "__main__":
    main()
