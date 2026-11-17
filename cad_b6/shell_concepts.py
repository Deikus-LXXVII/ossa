#!/usr/bin/env python3
"""Organic shell over the B6 skeleton: three quick concepts to choose a direction from.

Run:  .venv/bin/python cad_b6/shell_concepts.py [A|B|C ...]
Out:  previews/b6_shell_<concept>_<view>.png

The shell is modelled as a signed distance field (smooth unions of tapered tubes and perforated
panels) and meshed with marching cubes, because lofts and booleans on organic B-rep shapes have
not been reliable in this project. These are sketches: no fixings, no print split, no checks yet.
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frame_v0                                  # cadquery must be imported before vtk: with vtk first,
import hardware as hw                            # OpenCascade booleans run about ten times slower
import hoses
import render_vtk
import vtk
from vtkmodules.util import numpy_support

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C = math.sqrt(0.5)
VOX = 3.0
X_LIM = hw.ENVELOPE_FAN_X + 20.0     # revision 13: the side fans stand out to |X| 260 (it was 252 for fans at 226); 20 mm more for the layer's own thickness there
Y0, Y1, Z0, Z1 = -8.0, 394.0, -18.0, 400.0
FLANK = 238.0                # centre plane of the shell on each side; radiator ends are at 229
CLEAR = 4.0                  # shell stays this far from hardware
HOT_CLEAR = None             # if set: distance kept from the graphics card and the PSU (the organic layer)
SMOOTH = 12.0                # blend radius where members meet


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------
def grid():
    xs = np.arange(-X_LIM, X_LIM + VOX, VOX, dtype=np.float32)
    ys = np.arange(Y0, Y1 + VOX, VOX, dtype=np.float32)
    zs = np.arange(Z0, Z1 + VOX, VOX, dtype=np.float32)
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    return xs, ys, zs, X, Y, Z


def smin(a, b, k=SMOOTH):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b + (a - b) * h - k * h * (1.0 - h)


def spline(ctrl, step=10.0):
    """Catmull-Rom through the control points, resampled at about `step` mm."""
    P = np.array(ctrl, dtype=float)
    P = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        n = max(int(np.linalg.norm(p2 - p1) / step), 2)
        for t in np.linspace(0, 1, n, endpoint=False):
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(P[-2])
    return np.array(out)


def tube(G, ctrl, r0, r1=None, squash=None):
    """Distance to a tapered tube along a spline. squash=(axis, factor) flattens it into a ribbon."""
    X, Y, Z = G
    pts = spline(ctrl)
    if callable(r0):                                     # radius profile along the member, t in 0..1
        rad = np.array([r0(t) for t in np.linspace(0, 1, len(pts))])
    else:
        rad = np.linspace(r0, r0 if r1 is None else r1, len(pts))
    d = np.full(X.shape, 1e9, dtype=np.float32)
    sx = sy = sz = 1.0
    if squash:
        axis, f = squash
        sx, sy, sz = [(f if a == axis else 1.0) for a in "xyz"]
    for (a, b, ra, rb) in zip(pts[:-1], pts[1:], rad[:-1], rad[1:]):
        ab = b - a
        L2 = float(ab @ ab)
        t = np.clip(((X - a[0]) * ab[0] + (Y - a[1]) * ab[1] + (Z - a[2]) * ab[2]) / L2, 0.0, 1.0)
        dx = (X - (a[0] + ab[0] * t)) * sx
        dy = (Y - (a[1] + ab[1] * t)) * sy
        dz = (Z - (a[2] + ab[2] * t)) * sz
        d = np.minimum(d, np.sqrt(dx * dx + dy * dy + dz * dz) - (ra + (rb - ra) * t))
    return d


def mirror(ctrl):
    return [(-x, y, z) for x, y, z in ctrl]


def box_world(G, b):
    X, Y, Z = G
    q = [np.maximum(b[0] - X, X - b[1]), np.maximum(b[2] - Y, Y - b[3]), np.maximum(b[4] - Z, Z - b[5])]
    out = np.sqrt(sum(np.maximum(c, 0) ** 2 for c in q))
    return out + np.minimum(np.maximum(np.maximum(q[0], q[1]), q[2]), 0)


def to_bs(G):
    X, Y, Z = G
    v = X - hw.ORIGIN[0]
    y, z = Y - hw.ORIGIN[1], Z - hw.ORIGIN[2]
    return v, (y + z) * C, (z - y) * C


def keep_clear(G, d):
    """Carve the shell back from the hardware and the hoses."""
    Gb = to_bs(G)
    hot = CLEAR if HOT_CLEAR is None else HOT_CLEAR
    for b in (hw.RAD360_BS, hw.RAD420_ENV_BS, hw.BOARD_BS):
        d = np.maximum(d, CLEAR - box_world(Gb, b))
    d = np.maximum(d, hot - box_world(Gb, hw.GPU_BS))
    d = np.maximum(d, hot - box_world(G, hw.PSU_W))
    for name in hw.FAN_SIDE_NAMES:
        d = np.maximum(d, CLEAR - box_world(Gb, hw.fan_side_bs(name)))
    X, Y, Z = G
    for name, (pair, spec) in hoses.routes().items():
        for h in pair:
            p = h["pts"][::4]
            dh = np.full(X.shape, 1e9, dtype=np.float32)
            for a in p:
                dh = np.minimum(dh, (X - a[0]) ** 2 + (Y - a[1]) ** 2 + (Z - a[2]) ** 2)
            d = np.maximum(d, (spec["r"] + CLEAR + 1.0) - np.sqrt(dh))
    d = np.maximum(d, -(Z + 15.0))                       # desk
    d = np.maximum(d, -Y)                                # front plane
    return d


def bp(u, n, x):
    y, z = hw.bp(0, u, n)[1:]
    return (x, y, z)


# ---------------------------------------------------------------------------
# Shared members
# ---------------------------------------------------------------------------
RIDGE_U, RIDGE_N = 344.0, 137.0          # line along the 420's top face


def flank_curves(x=FLANK):
    """Three ribs down one flank from the ridge to the feet, plus the base rail."""
    top = bp(RIDGE_U, RIDGE_N, x)
    front = [top, (x + 2, 150, 330), (x + 2, 90, 250), (x, 45, 160), (x - 6, 22, 60), (x - 12, 18, -4)]
    mid = [top, (x + 3, 214, 300), (x + 3, 205, 200), (x, 196, 90), (x - 6, 192, -4)]
    rear = [top, (x + 1, 270, 348), (x + 2, 330, 285), (x, 372, 180), (x - 4, 378, 60), (x - 10, 378, -4)]
    rail = [(x - 12, 18, -4), (x - 7, 100, -6), (x - 6, 192, -4), (x - 7, 290, -6), (x - 10, 378, -4)]
    return front, mid, rear, rail


def collar(x=FLANK):
    """Arch across the front, above the fans and below the card."""
    return [(x, 45, 160), (150, 16, 167), (0, 9, 171), (-150, 16, 167), (-x, 45, 160)]


def ridge(x=FLANK):
    return [bp(RIDGE_U, RIDGE_N, -x), bp(RIDGE_U, RIDGE_N + 2, -100), bp(RIDGE_U, RIDGE_N + 3, 0),
            bp(RIDGE_U, RIDGE_N + 2, 100), bp(RIDGE_U, RIDGE_N, x)]


# ---------------------------------------------------------------------------
# Concepts
# ---------------------------------------------------------------------------
def concept_a(G):
    """«Рёбра»: a spine on the ridge and three ribs down each flank, like a ribcage."""
    d = tube(G, ridge(), 9.0)
    front, mid, rear, rail = flank_curves()
    for crv, r0, r1 in ((front, 9, 10), (mid, 8, 9), (rear, 9, 10), (rail, 8, 8)):
        d = smin(d, tube(G, crv, r0, r1))
        d = smin(d, tube(G, mirror(crv), r0, r1))
    d = smin(d, tube(G, collar(), 7.0))
    return d


def concept_b(G):
    """«Панцирь»: the same spine and collar, with perforated shields on the flanks."""
    X, Y, Z = G
    d = smin(tube(G, ridge(), 9.0), tube(G, collar(), 7.0))
    # side silhouette as a convex polygon in (Y, Z), clockwise
    poly = [(2, -13), (2, 150), (58, 286), (150, 372), (242, 394), (342, 292), (384, 180), (384, -13)]
    region = np.full(Y.shape, -1e9, dtype=np.float32)
    for (y0, z0), (y1, z1) in zip(poly, poly[1:] + poly[:1]):
        ey, ez = y1 - y0, z1 - z0
        L = math.hypot(ey, ez)
        region = np.maximum(region, -((Y - y0) * ez - (Z - z0) * ey) / L)   # negative inside (clockwise polygon)
    rng = np.random.default_rng(7)
    seeds = []
    for _ in range(6000):                                # random sequential packing; stops when full
        y, z = rng.uniform(15, 375), rng.uniform(0, 380)
        inside = all(((y - a[0]) * (b[1] - a[1]) - (z - a[1]) * (b[0] - a[0])) / math.hypot(b[0] - a[0], b[1] - a[1])
                     > 16 for a, b in zip(poly, poly[1:] + poly[:1]))
        if inside and all(math.hypot(y - s[0], z - s[1]) > 46 for s in seeds):
            seeds.append((y, z))
    holes = np.full(Y.shape, 1e9, dtype=np.float32)
    for y, z in seeds:
        near = min(math.hypot(y - s[0], z - s[1]) for s in seeds if s != (y, z))
        holes = smin(holes, np.sqrt((Y - y) ** 2 + (Z - z) ** 2) - 0.36 * near, 8.0)
    rim = np.abs(region + 9.0) - 9.0                      # a solid band along the edge
    sheet = np.maximum(region, -holes)
    sheet = np.minimum(sheet, np.maximum(rim, region))
    for side in (1, -1):
        slab = np.abs(X - side * (FLANK + 2)) - 3.5
        d = smin(d, np.maximum(slab, sheet), 6.0)
    return d


def concept_c(G):
    """«Ветви»: one trunk at the rear left that branches over the ridge and round the flanks."""
    x = FLANK
    top_l = bp(RIDGE_U, RIDGE_N, -x)
    top_r = bp(RIDGE_U, RIDGE_N, x)
    trunk = [(-x + 20, 378, -4), (-x + 2, 368, 110), (-x, 335, 255), top_l]
    over = [top_l, bp(RIDGE_U, RIDGE_N + 3, -110), bp(RIDGE_U, RIDGE_N + 3, 60), top_r,
            (x + 2, 150, 330), (x + 2, 90, 250), (x, 42, 155), (x - 12, 18, -4)]
    left = [(-x, 335, 255), (-x - 3, 255, 262), (-x - 3, 150, 232), (-x, 62, 178), (-x + 6, 22, 60), (-x + 12, 18, -4)]
    rear_r = [top_r, (x + 1, 270, 348), (x + 2, 330, 285), (x, 372, 180), (x - 10, 378, -4)]
    twig_l = [(-x - 3, 150, 232), (-x, 185, 120), (-x + 6, 192, -4)]
    twig_r = [(x + 2, 90, 250), (x + 3, 170, 150), (x - 6, 192, -4)]
    d = tube(G, trunk, 15.0, 11.0)
    for crv, r0, r1 in ((over, 11, 7), (left, 10, 7), (rear_r, 8, 7), (twig_l, 7, 6), (twig_r, 6, 6)):
        d = smin(d, tube(G, crv, r0, r1), 16.0)
    d = smin(d, tube(G, collar(), 6.0))
    return d


CONCEPTS = {"A": ("«Рёбра»", concept_a), "B": ("«Панцирь»", concept_b), "C": ("«Ветви»", concept_c)}


# ---------------------------------------------------------------------------
# Meshing and rendering
# ---------------------------------------------------------------------------
def mesh(xs, ys, zs, d):
    img = vtk.vtkImageData()
    img.SetDimensions(len(xs), len(ys), len(zs))
    img.SetOrigin(float(xs[0]), float(ys[0]), float(zs[0]))
    img.SetSpacing(VOX, VOX, VOX)
    arr = numpy_support.numpy_to_vtk(d.ravel(order="F"), deep=True, array_type=vtk.VTK_FLOAT)
    img.GetPointData().SetScalars(arr)
    fe = vtk.vtkFlyingEdges3D()
    fe.SetInputData(img)
    fe.SetValue(0, 0.0)
    sm = vtk.vtkWindowedSincPolyDataFilter()
    sm.SetInputConnection(fe.GetOutputPort())
    sm.SetNumberOfIterations(25)
    sm.SetPassBand(0.08)
    nrm = vtk.vtkPolyDataNormals()
    nrm.SetInputConnection(sm.GetOutputPort())
    nrm.SetFeatureAngle(70)
    nrm.Update()
    return nrm.GetOutput()


VIEWS = {"front_left": (-0.75, -1.25, 0.70), "front_right": (0.85, -1.15, 0.60), "left": (-1.0, 0.0, 0.0),
         "rear_left": (-0.9, 1.2, 0.65)}


def render(key, shell, hware, parts, rts, extras=()):
    for view, cam_dir in VIEWS.items():
        ren = vtk.vtkRenderer()
        ren.SetBackground(1, 1, 1)
        for name, solid in hware.items():
            if name in hw.KEEP_OUT:
                continue
            for a in render_vtk._actors(solid, render_vtk.HW_RGB.get(name, (0.6, 0.6, 0.6)), opacity=0.35,
                                        edge_opacity=0.25):
                ren.AddActor(a)
        for p in parts:
            for a in render_vtk._actors(p.solid, (0.86, 0.86, 0.84), opacity=1.0, edge_opacity=0.5):
                ren.AddActor(a)
        for solid, rgb, opacity in extras:
            for a in render_vtk._actors(solid, rgb, opacity=opacity, edge_opacity=0.4):
                ren.AddActor(a)
        import hose_routes
        for name, (pair, spec) in rts.items():
            rgb = (0.10, 0.10, 0.11) if name == "cpu" else (0.42, 0.24, 0.12)
            for h in pair:
                ren.AddActor(hose_routes.tube_actor(h["pts"], spec["r"], rgb))
        m = vtk.vtkPolyDataMapper()
        m.SetInputData(shell)
        m.ScalarVisibilityOff()
        a = vtk.vtkActor()
        a.SetMapper(m)
        a.GetProperty().SetColor(0.16, 0.16, 0.18)
        a.GetProperty().SetAmbient(0.35)
        a.GetProperty().SetDiffuse(0.65)
        a.GetProperty().SetSpecular(0.25)
        a.GetProperty().SetSpecularPower(18)
        ren.AddActor(a)
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
        cam.SetViewUp(0, 0, 1)
        if view == "left":
            cam.ParallelProjectionOn()
        ren.ResetCamera()
        cam.Zoom(1.05)
        win.Render()
        grab = vtk.vtkWindowToImageFilter()
        grab.SetInput(win)
        grab.Update()
        wr = vtk.vtkPNGWriter()
        path = os.path.join(ROOT, "previews", f"b6_shell_{key}_{view}.png")
        wr.SetFileName(path)
        wr.SetInputConnection(grab.GetOutputPort())
        wr.Write()
        print("→", path)


def main(keys):
    xs, ys, zs, X, Y, Z = grid()
    G = (X, Y, Z)
    hware = hw.build_hardware()
    parts, _ = frame_v0.build_frame()
    rts = hoses.routes()
    for key in keys:
        title, fn = CONCEPTS[key]
        d = keep_clear(G, fn(G))
        shell = mesh(xs, ys, zs, d)
        vol = float((d < 0).sum()) * VOX ** 3 / 1000.0
        b = shell.GetBounds()
        print(f"{key} {title}: объём ≈ {vol:.0f} см³ ({vol * 1.04:.0f} г сплошного ABS), "
              f"X {b[0]:.0f}..{b[1]:.0f}, Y {b[2]:.0f}..{b[3]:.0f}, Z {b[4]:.0f}..{b[5]:.0f}")
        render(key, shell, hware, parts, rts)


if __name__ == "__main__":
    main([k.upper() for k in sys.argv[1:]] or list(CONCEPTS))
