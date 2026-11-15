#!/usr/bin/env python3
"""Offscreen VTK renderer for the B6 model: shaded solids with feature edges.

Run:  .venv/bin/python cad_b6/render_vtk.py
Out:  previews/b6_v0_<view>.png  for each view in VIEWS, with and without hardware.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frame_v0      # noqa: E402  cadquery first: with vtk imported before it, OCC's booleans run about 10 times slower (measured 11 s -> 150 s for the rounded frame)
import hardware      # noqa: E402
import vtk           # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FRAME_RGB = (0.86, 0.86, 0.84)
HW_RGB = {
    "board": (0.31, 0.50, 0.75), "gpu": (0.35, 0.63, 0.24), "cpu_block": (0.72, 0.25, 0.25),
    "rad420": (0.88, 0.54, 0.18), "rad360": (0.65, 0.80, 0.36), "psu": (0.66, 0.61, 0.82),
    "fan_side_right": (0.35, 0.65, 0.70), "fan_side_left": (0.35, 0.65, 0.70), "io_zone": (0.75, 0.31, 0.48),
    "dimms": (0.84, 0.76, 0.29), "atx24": (0.25, 0.65, 0.63), "eps": (0.54, 0.37, 0.79),
    "rad420_ports": (0.76, 0.35, 0.0), "rad360_ports": (0.48, 0.56, 0.0),
    "cpu_hoses": (0.10, 0.10, 0.11), "gpu_hoses": (0.42, 0.24, 0.12),     # the hoses are drawn opaque, as hoses
    "front_io": (0.83, 0.63, 0.09), "light_strip": (0.95, 0.89, 0.35),
}
# camera direction (from the model towards the eye), world axes: X right, Y back, Z up
VIEWS = {
    "front_left": (-0.75, -1.25, 0.70),
    "front_right": (0.85, -1.15, 0.60),
    "rear_right": (0.95, 1.20, 0.65),
    "left": (-1.0, 0.0, 0.0),
}


_CACHE: dict[int, list] = {}


def _polydata(solid, tol=0.4):
    verts, tris = solid.tessellate(tol, 0.3)
    pts = vtk.vtkPoints()
    for v in verts:
        pts.InsertNextPoint(v.x, v.y, v.z)
    cells = vtk.vtkCellArray()
    for a, b, c in tris:
        cells.InsertNextCell(3, (a, b, c))
    pd = vtk.vtkPolyData()
    pd.SetPoints(pts)
    pd.SetPolys(cells)
    return pd


def _actors(solid, rgb, opacity=1.0, edges=True, edge_opacity=None):
    out = []
    if id(solid) not in _CACHE:
        _CACHE[id(solid)] = [_polydata(s) for s in solid.Solids()]
    for pd in _CACHE[id(solid)]:
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputData(pd)
        normals.SetFeatureAngle(40)
        normals.SplittingOn()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(normals.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(*rgb)
        prop.SetOpacity(opacity)
        prop.SetAmbient(0.25)
        prop.SetDiffuse(0.75)
        out.append(actor)
        if edges:
            fe = vtk.vtkFeatureEdges()
            fe.SetInputData(pd)
            fe.SetFeatureAngle(30)
            fe.BoundaryEdgesOn()
            fe.FeatureEdgesOn()
            fe.ColoringOff()
            em = vtk.vtkPolyDataMapper()
            em.SetInputConnection(fe.GetOutputPort())
            ea = vtk.vtkActor()
            ea.SetMapper(em)
            ea.GetProperty().SetColor(0.12, 0.12, 0.12)
            ea.GetProperty().SetLineWidth(1.4)
            ea.GetProperty().SetOpacity(edge_opacity if edge_opacity is not None else max(opacity, 0.5))
            out.append(ea)
    return out


def render(parts, hw, view, path, size=(1500, 1150)):
    ren = vtk.vtkRenderer()
    ren.SetBackground(1, 1, 1)
    for p in parts:
        for a in _actors(p.solid, FRAME_RGB):
            ren.AddActor(a)
    for name, solid in (hw or {}).items():
        hose = name in hardware.HOSES
        keep = name in hardware.KEEP_OUT
        opacity = 1.0 if hose else (0.12 if keep else 0.38)      # hoses opaque, the other keep-outs faint
        for a in _actors(solid, HW_RGB[name], opacity=opacity, edges=not hose,
                         edge_opacity=0.2 if keep and not hose else None):
            ren.AddActor(a)
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.SetSize(*size)
    win.SetAlphaBitPlanes(1)
    win.SetMultiSamples(0)
    win.AddRenderer(ren)
    ren.SetUseDepthPeeling(1)
    ren.SetMaximumNumberOfPeels(8)
    ren.UseFXAAOn()
    cam = ren.GetActiveCamera()
    cam.SetFocalPoint(0, 0, 0)
    cam.SetPosition(*VIEWS[view])
    cam.SetViewUp(0, 0, 1)
    if view == "left":
        cam.ParallelProjectionOn()
    ren.ResetCamera()
    cam.Zoom(1.0)
    win.Render()
    grab = vtk.vtkWindowToImageFilter()
    grab.SetInput(win)
    grab.Update()
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(path)
    writer.SetInputConnection(grab.GetOutputPort())
    writer.Write()


def main():
    parts, _ = frame_v0.build_frame()
    hw = hardware.build_hardware()
    for view in VIEWS:
        for tag, h in (("hw", hw), ("bare", None)):
            path = os.path.join(ROOT, "previews", f"b6_v0_{view}_{tag}.png")
            render(parts, h, view, path)
            print("→", path)


if __name__ == "__main__":
    main()
