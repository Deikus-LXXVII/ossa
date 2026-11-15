#!/usr/bin/env python3
"""Hose routing as a design element: analysis and render of the routes in hoses.py (length, bend radius,
clearance to the hardware) for both coolers.

Run:  .venv/bin/python cad_b6/hose_routes.py
Out:  previews/b6_hoses_<view>.png and a table on stdout.

The route geometry itself lives in hoses.py; hardware.build_hardware() builds the keep-outs from it.
"""
from __future__ import annotations

import os
import sys

import cadquery as cq
import numpy as np
import vtk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hardware as hw
import hoses

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tube_actor(p, r, rgb):
    pts = vtk.vtkPoints()
    line = vtk.vtkPolyLine()
    line.GetPointIds().SetNumberOfIds(len(p))
    for i, q in enumerate(p):
        pts.InsertNextPoint(*q)
        line.GetPointIds().SetId(i, i)
    cells = vtk.vtkCellArray()
    cells.InsertNextCell(line)
    pd = vtk.vtkPolyData()
    pd.SetPoints(pts)
    pd.SetLines(cells)
    tf = vtk.vtkTubeFilter()
    tf.SetInputData(pd)
    tf.SetRadius(r)
    tf.SetNumberOfSides(24)
    tf.CappingOn()
    m = vtk.vtkPolyDataMapper()
    m.SetInputConnection(tf.GetOutputPort())
    a = vtk.vtkActor()
    a.SetMapper(m)
    a.GetProperty().SetColor(*rgb)
    return a


def chain(p, r, every=3):
    q = p[::every]
    caps = []
    for a, b in zip(q, q[1:]):
        d = cq.Vector(*(b - a))
        caps.append(cq.Solid.makeCylinder(r, d.Length, cq.Vector(*a), d.normalized()))
    return cq.Compound.makeCompound(caps)


def hardware():
    """The hardware the hoses are measured against: the real components, not the keep-outs."""
    h = dict(hw.build_hardware())
    for k in hw.KEEP_OUT:
        h.pop(k, None)
    return h


def analyse(rts, hware):
    rows = []
    for name, (pair, spec) in rts.items():
        skip = ("cpu_block",) if name == "cpu" else ("gpu",)
        for i, h in enumerate(pair):
            solid = chain(h["pts"], spec["r"])
            near = []
            for k, s in hware.items():
                if k in skip:
                    continue
                d = solid.distance(s)
                if d < 8.0:
                    near.append(f"{k} {d:.1f}")
            p = h["pts"]
            rows.append((f"{name} {'ab'[i]}", h["length"], spec["length"], h["rmin"], spec["min_bend"], near,
                         float(p[:, 0].min()) - spec["r"], float(p[:, 0].max()) + spec["r"], h["top"],
                         float(p[:, 1].min()) - spec["r"]))
        a, b = pair[0]["pts"], pair[1]["pts"]
        gap = min(float(np.linalg.norm(b - q, axis=1).min()) for q in a[10:-4]) - 2 * spec["r"]
        rows.append((f"{name} зазор между шлангами", gap))
    return rows


VIEWS = {"front": (0.0, -1.0, 0.55), "front_left": (-0.75, -1.25, 0.70), "front_right": (0.85, -1.15, 0.60),
         "top": (0.0, -0.35, 1.0)}


def render(rts, hware, tag="hoses"):
    import render_vtk
    for view, cam_dir in VIEWS.items():
        ren = vtk.vtkRenderer()
        ren.SetBackground(1, 1, 1)
        for name, solid in hware.items():
            if name in hw.KEEP_OUT:
                continue
            for a in render_vtk._actors(solid, render_vtk.HW_RGB.get(name, (0.6, 0.6, 0.6)), opacity=0.55):
                ren.AddActor(a)
        for name, (pair, spec) in rts.items():
            rgb = (0.10, 0.10, 0.11) if name == "cpu" else (0.42, 0.24, 0.12)
            for h in pair:
                ren.AddActor(tube_actor(h["pts"], spec["r"], rgb))
        win = vtk.vtkRenderWindow()
        win.SetOffScreenRendering(1)
        win.SetSize(1500, 1150)
        win.SetAlphaBitPlanes(1)
        win.SetMultiSamples(0)
        win.AddRenderer(ren)
        ren.SetUseDepthPeeling(1)
        ren.SetMaximumNumberOfPeels(8)
        ren.UseFXAAOn()
        cam = ren.GetActiveCamera()
        cam.SetFocalPoint(0, 0, 0)
        cam.SetPosition(*cam_dir)
        cam.SetViewUp(0, 0, 1) if view != "top" else cam.SetViewUp(0, 1, 0)
        ren.ResetCamera()
        cam.Zoom(1.05)
        win.Render()
        grab = vtk.vtkWindowToImageFilter()
        grab.SetInput(win)
        grab.Update()
        wr = vtk.vtkPNGWriter()
        path = os.path.join(ROOT, "previews", f"b6_{tag}_{view}.png")
        wr.SetFileName(path)
        wr.SetInputConnection(grab.GetOutputPort())
        wr.Write()
        print("→", path)


def table_lines(rts=None, hware=None):
    """The hose table as text lines: path, length, spare, smallest bend radius, X range, front-most Y and
    everything closer than 8 mm to the hardware."""
    rts = rts or hoses.routes()
    hware = hware or hardware()
    out = [f"{'шланг':8} {'путь':>6} {'длина':>6} {'остаток':>8} {'мин. радиус':>12} {'параметр':>10}  X от..до   ближе 8 мм"]
    for row in analyse(rts, hware):
        if len(row) == 2:
            out.append(f"{row[0]}: {row[1]:.1f} мм")
            continue
        name, length, total, rad, need, near, x0, x1, top, ymin = row
        out.append(f"{name:8} {length:6.0f} {total:6.0f} {total - length:8.0f} {rad:9.0f}/{need:.0f} {top:10.0f}  "
                   f"{x0:5.0f}..{x1:4.0f}  перед Y {ymin:4.0f}  {', '.join(near) or 'нет'}")
    return out


def main():
    hware = hardware()
    rts = hoses.routes()
    print("\n".join(table_lines(rts, hware)))
    render(rts, hware)


if __name__ == "__main__":
    main()
