"""The whole design in one picture set: skeleton, hardware, hoses, cables and the organic layer, from six sides and four corners.

Run:  .venv/bin/python cad_b6/render_full.py
In:   out/organic/field.npz (written by organic_frame.py; run that first if the layer changed)
Out:  previews/b6_full_sides.png    six parallel views at one scale, everything drawn
      previews/b6_full_corners.png  four corner views, everything drawn
      previews/b6_full_inside.png   the same four corners without the organic layer, cables in their report colours

Nothing is checked here. Hardware is drawn opaque, as it is seen; keep-out zones are left out.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cadquery as cq  # noqa: F401  (before vtk, see render_vtk.py)
import vtk

import cables
import frame_v0
import hardware as hw
import hose_routes
import hoses
import organic_frame
import render_vtk
import shell_concepts as sc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ABS_RGB = (0.80, 0.80, 0.78)          # the skeleton is black ABS; drawn light so that it reads against the black layer
PLA_RGB = (0.16, 0.16, 0.18)
CABLE_RGB = (0.22, 0.22, 0.24)
TILE = (1100, 850)

# name -> (direction from the model to the eye, the picture's up)
SIDES = {"front": ((0, -1, 0), (0, 0, 1)), "rear": ((0, 1, 0), (0, 0, 1)), "top": ((0, 0, 1), (0, 1, 0)),
         "left": ((-1, 0, 0), (0, 0, 1)), "right": ((1, 0, 0), (0, 0, 1)), "bottom": ((0, 0, -1), (0, -1, 0))}
CORNERS = {"front left": ((-0.75, -1.25, 0.70), (0, 0, 1)), "front right": ((0.85, -1.15, 0.60), (0, 0, 1)),
           "rear left": ((-0.9, 1.2, 0.65), (0, 0, 1)), "rear right": ((0.95, 1.20, 0.65), (0, 0, 1))}


def organic_actor():
    f = np.load(os.path.join(ROOT, "out", "organic", "field.npz"))
    vox, sc.VOX = sc.VOX, float(f["xs"][1] - f["xs"][0])
    try:
        shell = sc.mesh(f["xs"], f["ys"], f["zs"], f["d"])
    finally:
        sc.VOX = vox
    m = vtk.vtkPolyDataMapper()
    m.SetInputData(shell)
    m.ScalarVisibilityOff()
    a = vtk.vtkActor()
    a.SetMapper(m)
    p = a.GetProperty()
    p.SetColor(*PLA_RGB)
    p.SetAmbient(0.35)
    p.SetDiffuse(0.65)
    p.SetSpecular(0.25)
    p.SetSpecularPower(18)
    return a


def scene(layer, cable_colours):
    parts, _ = frame_v0.build_frame()
    out = []
    for p in parts:
        rgb = cables.TIE_RGB if p.name.startswith("tie_bridge") else ABS_RGB
        out += render_vtk._actors(p.solid, rgb, opacity=1.0, edge_opacity=0.45)
    for name, solid in hw.build_hardware().items():
        if name in hw.KEEP_OUT or name in hw.HOSES:
            continue
        out += render_vtk._actors(solid, render_vtk.HW_RGB.get(name, (0.6, 0.6, 0.6)), opacity=1.0, edge_opacity=0.35)
    out += render_vtk._actors(organic_frame.SILL["cuts"]["slit"], (1.0, 0.86, 0.35), opacity=1.0, edge_opacity=0.4)
    for name, (pair, spec) in hoses.routes().items():
        rgb = (0.10, 0.10, 0.11) if name == "cpu" else (0.42, 0.24, 0.12)
        out += [hose_routes.tube_actor(h["pts"], spec["r"], rgb) for h in pair]
    for name, rt in cables.build_routes().items():
        out += [hose_routes.tube_actor(p, r, cables.RGB[name] if cable_colours else CABLE_RGB) for p, r in rt.strands]
    if layer:
        out.append(organic_actor())
    return out


def sheet(actors, views, cols, path, parallel):
    rows = -(-len(views) // cols)
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.SetSize(TILE[0] * cols, TILE[1] * rows)
    win.SetMultiSamples(0)
    rens = []
    for i, (name, (direction, up)) in enumerate(views.items()):
        c, r = i % cols, i // cols
        ren = vtk.vtkRenderer()
        ren.SetBackground(1, 1, 1)
        ren.SetViewport(c / cols, 1 - (r + 1) / rows, (c + 1) / cols, 1 - r / rows)
        ren.UseFXAAOn()
        for a in actors:
            ren.AddActor(a)
        cam = ren.GetActiveCamera()
        cam.SetFocalPoint(0, 0, 0)
        cam.SetPosition(*direction)
        cam.SetViewUp(*up)
        if parallel:
            cam.ParallelProjectionOn()
        ren.ResetCamera()
        if not parallel:
            cam.Zoom(1.02)
        lab = vtk.vtkTextActor()
        lab.SetInput(name)
        lab.SetPosition(24, 20)
        lab.GetTextProperty().SetFontSize(34)
        lab.GetTextProperty().SetBold(True)
        lab.GetTextProperty().SetColor(0.1, 0.1, 0.1)
        ren.AddViewProp(lab)
        win.AddRenderer(ren)
        rens.append(ren)
    if parallel:                       # one scale for every side
        scale = max(r.GetActiveCamera().GetParallelScale() for r in rens) * 0.68
        for r in rens:
            r.GetActiveCamera().SetParallelScale(scale)
    win.Render()
    grab = vtk.vtkWindowToImageFilter()
    grab.SetInput(win)
    grab.Update()
    wr = vtk.vtkPNGWriter()
    wr.SetFileName(path)
    wr.SetInputConnection(grab.GetOutputPort())
    wr.Write()
    print("->", path)


def main():
    full = scene(layer=True, cable_colours=False)
    sheet(full, SIDES, 3, os.path.join(ROOT, "previews", "b6_full_sides.png"), parallel=True)
    sheet(full, CORNERS, 2, os.path.join(ROOT, "previews", "b6_full_corners.png"), parallel=False)
    inside = scene(layer=False, cable_colours=True)
    sheet(inside, CORNERS, 2, os.path.join(ROOT, "previews", "b6_full_inside.png"), parallel=False)


if __name__ == "__main__":
    main()
