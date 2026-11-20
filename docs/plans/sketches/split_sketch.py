"""The split of the organic layer's piece `main` into printable pieces, a sketch: where the seams could go.

`main` is one body about 515 x 408 x 381 mm; the printer's bed is 300 mm and the project's rule for a part is 290. This script does not build the layer. It reads the saved
field (out/organic/field.npz), gives every solid voxel of `main` to the piece that owns the nearest bone or film member (PLAN below says which piece owns what), opens a gap
between the pieces, and reports each piece: its size, the smallest box it fits in when it is turned about one axis, the pads it has, whether it is one body, and what the seam cut.

Run from the repository root:
  .venv/bin/python docs/plans/sketches/split_sketch.py report [PLAN]              the table, one line per piece
  .venv/bin/python docs/plans/sketches/split_sketch.py field OUT.npz [PLAN]       the field with d_<piece> for every piece (organic_strength.py reads it), and the table
  .venv/bin/python docs/plans/sketches/split_sketch.py joint PREFIX               one half-lap joint drawn on the lip, put together and apart: PREFIX_together.png, PREFIX_apart.png
  .venv/bin/python docs/plans/sketches/split_sketch.py picture PREFIX [PLAN]      the pieces in colours over the skeleton, three views PREFIX_<view>.png, and the table
"""
import os
import sys

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

ROOT = os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "cad_b6"))
import hardware as hw
import organic_frame as of

FIELD = os.path.join(ROOT, "out", "organic", "field.npz")
SEAM_X = float(of.GPU_SOCKET_X)            # the front's seam: the socket's X, in the middle of the window the films keep over the connector
BASE_CUT_Y = 190.0                         # the base rails are cut here: behind the left ring's tie to the rail (Y up to 175), in front of the first strand of the film to the rear sweep (Y 203)
BED = 290.0


def side(x):
    return "L" if x < SEAM_X else "R"


def plan_v1(kind, name, pts):
    """Eight pieces: the front in two halves at the connector's window, each with its post and the front part of its base rail; a ring piece and a rear piece each side.
    kind "bone" (name: the bone's) or "film" (name: the film's number); pts: the member's centre line. Returns the piece of every point."""
    x, y = pts[:, 0], pts[:, 1]
    if kind == "bone":
        if name in ("lip", "card", "front_low"):
            return np.where(x < SEAM_X, "front_L", "front_R")
        tag = name[-1] if name[-1] in "LR" else name.split("_")[-1][0]
        if name.startswith("front_"):
            return np.full(len(pts), "front_" + tag)
        if name.startswith("base_"):
            return np.where(y < BASE_CUT_Y, "front_" + tag, "rear_" + tag)
        if name.startswith("rear_"):
            return np.full(len(pts), "rear_" + tag)
        return np.full(len(pts), "ring_" + tag)             # the rings, the side bones, the left ring's ties
    owner = {0: "front_L", 1: "front_R", 3: "ring_L", 4: "rear_L", 5: "ring_R", 6: "ring_R", 7: "rear_R"}
    if name in owner:
        return np.full(len(pts), owner[name])
    if np.ptp(x) > 60:                                       # the front film's bars along front_low and the bone over the card: each point by its side
        return np.where(x < SEAM_X, "front_L", "front_R")
    return np.full(len(pts), "front_" + side(float(pts[:, 0].mean())))      # the front film: a strand or a cross-thread goes whole to the side its middle is on


FRONT_X = float(os.environ.get("SK_FRONT_X", 130.0))       # v2: the front panel is everything of the lip, the bone over the card, front_low and their films within |X| of this
POST_CUT_Z = float(os.environ.get("SK_POST_CUT_Z", -1e9))  # v2: a post below this height goes with the rear piece's... no: with the piece "foot" (the foot and the front of the base rail)


def plan_v2(kind, name, pts):
    """Five pieces (seven with SK_POST_CUT_Z): the front panel whole, between X -FRONT_X and FRONT_X, with no seam in the middle; a side piece each side (the post, the ring, the
    side bone, the ends of the lip, of the bone over the card and of front_low, and the front of the base rail); a rear piece each side."""
    x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
    tags = np.where(x < 0, "L", "R")
    inner = np.abs(x) < FRONT_X
    if kind == "bone":
        if name in ("lip", "card", "front_low"):
            return np.where(inner, "front", np.char.add("side_", tags))
        tag = name[-1] if name[-1] in "LR" else name.split("_")[-1][0]
        if name.startswith("base_"):
            return np.where(y < BASE_CUT_Y, ("foot_" if POST_CUT_Z > -1e8 else "side_") + tag, "rear_" + tag)
        if name.startswith("rear_"):
            return np.full(len(pts), "rear_" + tag)
        if name.startswith("front_"):
            return np.where(z < POST_CUT_Z, "foot_" + tag, "side_" + tag)
        return np.full(len(pts), "side_" + tag)
    owner = {2: "front", 3: "side_L", 4: "rear_L", 5: "side_R", 6: "side_R", 7: "rear_R"}
    if name in owner:
        return np.full(len(pts), owner[name])
    if len(pts) > 40 and np.ptp(x) > 60:                    # a film's bar along a bone: each point by its place
        return np.where(inner, "front", np.char.add("side_", tags))
    return np.full(len(pts), "front" if abs(float(x.mean())) < FRONT_X else "side_" + ("L" if x.mean() < 0 else "R"))


def plan_v3(kind, name, pts):
    """Nine pieces. The front panel whole between X -FRONT_X and FRONT_X (the lip, the bone over the card, front_low, the hood and their films: the face of the case has no seam);
    a post each side with the ends of those three bones; a ring piece each side (the ring, the side bone, the films and ties that hang on them); the front of each base rail; a rear
    piece each side (the rear sweep, the rest of the base rail and the film between them)."""
    x, y = pts[:, 0], pts[:, 1]
    tags = np.where(x < 0, "L", "R")
    inner = np.abs(x) < FRONT_X
    if kind == "bone":
        if name in ("lip", "card", "front_low"):
            return np.where(inner, "front", np.char.add("post_", tags))
        tag = name[-1] if name[-1] in "LR" else name.split("_")[-1][0]
        if name.startswith("base_"):
            return np.where(y < BASE_CUT_Y, "rail_" + tag, "rear_" + tag)
        if name.startswith("rear_"):
            return np.full(len(pts), "rear_" + tag)
        if name.startswith("front_"):
            return np.full(len(pts), "post_" + tag)
        return np.full(len(pts), "ring_" + tag)
    owner = {2: "front", 3: "ring_L", 4: "rear_L", 5: "ring_R", 6: "ring_R", 7: "rear_R"}
    if name in owner:
        return np.full(len(pts), owner[name])
    if len(pts) > 40 and np.ptp(x) > 60:                    # a film's bar along a bone: each point by its place
        return np.where(inner, "front", np.char.add("post_", tags))
    return np.full(len(pts), "front" if abs(float(x.mean())) < FRONT_X else "post_" + ("L" if x.mean() < 0 else "R"))


POST_CUT = float(os.environ.get("SK_POST_CUT", 140.0))      # v4: a front post is cut at this height
TIE3_CUT = float(os.environ.get("SK_TIE3_CUT", 0.45))       # v4: the left ring's tie to the base rail is cut this far along it from the ring (a share of its length)


def plan_v4(kind, name, pts):
    """Seven pieces (the owner, 20 Nov 2026: seams near the corners, pieces screwed to each other). The front panel whole between X -FRONT_X and FRONT_X; a corner piece each side
    (the ring, the side bone, the top of the front post above POST_CUT, the ends of the lip and of the bone over the card, the films and ties that hang on them: so the right ring's
    film to the post stays in one piece); a foot piece each side (the post below POST_CUT, the end of front_low, the front of the base rail); a rear piece each side."""
    x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
    tags = np.where(x < 0, "L", "R")
    inner = np.abs(x) < FRONT_X
    if kind == "bone":
        if name in ("lip", "card"):
            return np.where(inner, "front", np.char.add("corner_", tags))
        if name == "front_low":
            return np.where(inner, "front", np.char.add("foot_", tags))
        tag = name[-1] if name[-1] in "LR" else name.split("_")[-1][0]
        if name.startswith("base_"):
            return np.where(y < BASE_CUT_Y, "foot_" + tag, "rear_" + tag)
        if name.startswith("rear_"):
            return np.full(len(pts), "rear_" + tag)
        if name.startswith("front_"):
            return np.where(z < POST_CUT, "foot_" + tag, "corner_" + tag)
        if name == "ring_tie_L3":
            return np.where(np.arange(len(pts)) < TIE3_CUT * len(pts), "corner_L", "foot_L")
        return np.full(len(pts), "corner_" + tag)
    owner = {2: "front", 3: "corner_L", 4: "rear_L", 5: "corner_R", 6: "corner_R", 7: "rear_R"}
    if name in owner:
        if name == 2 and not (len(pts) > 40 and np.ptp(x) > 60) and abs(float(x.mean())) >= FRONT_X:
            return np.full(len(pts), "foot_" + ("L" if x.mean() < 0 else "R"))
        return np.full(len(pts), owner[name])
    if len(pts) > 40 and np.ptp(x) > 60:                    # a film's bar along a bone: each point by its place
        return np.where(inner, "front", np.char.add("corner_", tags))
    return np.full(len(pts), "front" if abs(float(x.mean())) < FRONT_X else "corner_" + ("L" if x.mean() < 0 else "R"))


PLANS = {"v1": plan_v1, "v2": plan_v2, "v3": plan_v3, "v4": plan_v4}
COLOURS = {"front": (0.20, 0.45, 0.80), "post_L": (0.90, 0.55, 0.10), "post_R": (0.90, 0.55, 0.10), "ring_L": (0.20, 0.65, 0.35), "ring_R": (0.20, 0.65, 0.35),
           "rail_L": (0.80, 0.25, 0.60), "rail_R": (0.80, 0.25, 0.60), "rear_L": (0.75, 0.20, 0.20), "rear_R": (0.75, 0.20, 0.20), "front_L": (0.20, 0.45, 0.80),
           "front_R": (0.35, 0.70, 0.90), "corner_L": (0.20, 0.65, 0.35), "corner_R": (0.20, 0.65, 0.35), "side_L": (0.20, 0.65, 0.35), "side_R": (0.20, 0.65, 0.35), "foot_L": (0.80, 0.25, 0.60), "foot_R": (0.80, 0.25, 0.60)}


def picture(f, names, lab, prefix):
    """The pieces in colours over the skeleton in grey, three views."""
    import vtk
    import frame_v0
    import render_vtk
    import shell_concepts as sc

    hware = hw.build_hardware()
    parts, _ = frame_v0.build_frame(hardware=hware)
    sc.VOX = float(f["xs"][1] - f["xs"][0])               # shell_concepts meshes with its own step (3 mm); the layer's field is 1.5
    shells = [(name, sc.mesh(f["xs"], f["ys"], f["zs"], np.where(lab == k, f["d_main"], np.float32(1.0)).astype(np.float32))) for k, name in enumerate(names)]
    views = {"front_left": (-0.75, -1.25, 0.70), "front_right": (0.85, -1.15, 0.60), "left": (-1.0, -0.15, 0.25)}
    for view, cam in views.items():
        ren = vtk.vtkRenderer()
        ren.SetBackground(1, 1, 1)
        for name, solid in hware.items():
            if name in hw.KEEP_OUT:
                continue
            for a in render_vtk._actors(solid, (0.55, 0.57, 0.60), opacity=0.30, edge_opacity=0.25):
                ren.AddActor(a)
        for p_ in parts:
            for a in render_vtk._actors(p_.solid, (0.90, 0.90, 0.88), opacity=1.0, edge_opacity=0.35):
                ren.AddActor(a)
        for name, shell in shells:
            m = vtk.vtkPolyDataMapper()
            m.SetInputData(shell)
            m.ScalarVisibilityOff()
            a = vtk.vtkActor()
            a.SetMapper(m)
            a.GetProperty().SetColor(*COLOURS.get(name, (0.3, 0.3, 0.3)))
            a.GetProperty().SetAmbient(0.35)
            a.GetProperty().SetDiffuse(0.65)
            ren.AddActor(a)
        win = vtk.vtkRenderWindow()
        win.SetOffScreenRendering(1)
        win.SetSize(1500, 1150)
        win.SetMultiSamples(0)
        win.AddRenderer(ren)
        c = ren.GetActiveCamera()
        focal = np.array([0.0, 180.0, 170.0])
        c.SetFocalPoint(*focal)
        c.SetPosition(*(focal + 1400.0 * np.array(cam) / np.linalg.norm(cam)))
        c.SetViewUp(0, 0, 1)
        c.ParallelProjectionOn()
        ren.ResetCamera()
        c.Zoom(1.15)
        win.Render()
        w2i = vtk.vtkWindowToImageFilter()
        w2i.SetInput(win)
        w2i.Update()
        wr = vtk.vtkPNGWriter()
        path = f"{prefix}_{view}.png"
        wr.SetFileName(path)
        wr.SetInputConnection(w2i.GetOutputPort())
        wr.Write()
        print("saved", path)


def members(plan):
    """[(kind, name, what, centre line, the piece of each of its points)] of every bone and every film member."""
    _m, lines = of.bone_members()
    rows = [("bone", name, name, np.asarray(pts, dtype=float)) for name, pts in lines.items()]
    for fi, fm in enumerate(of.film_list()):
        kinds = ["bar"] * fm.bars + [k for k, _p, _l in fm.probes]
        for m, kind in enumerate(kinds):
            rows.append(("film", fi, f"film {fi} {kind} {m}", np.asarray(of.sc.spline(fm[m][1], step=2.0), dtype=float)))
    return [(kind, name, what, pts, plan(kind, name, pts)) for kind, name, what, pts in rows]


def label(f, rows):
    """(names of the pieces, the piece's number of every grid point of `main`'s solid, -1 elsewhere): each solid voxel goes to the piece of the nearest member point; a voxel that
    touches another piece's voxel is taken out of both, which leaves a gap of two voxels (3 mm, organic_frame.GAP_PIECE)."""
    names = sorted({p for r in rows for p in r[4]})
    pts = np.vstack([r[3] for r in rows])
    own = np.concatenate([[names.index(p) for p in r[4]] for r in rows])
    solid = f["d_main"] < 0
    idx = np.argwhere(solid)
    xyz = np.stack([f["xs"][idx[:, 0]], f["ys"][idx[:, 1]], f["zs"][idx[:, 2]]], axis=1)
    _d, near = cKDTree(pts).query(xyz, workers=-1)
    lab = np.full(solid.shape, -1, dtype=np.int16)
    lab[solid] = own[near]
    edge = np.zeros(solid.shape, dtype=bool)
    for ax in range(3):
        a = [slice(None)] * 3
        b = [slice(None)] * 3
        a[ax], b[ax] = slice(0, -1), slice(1, None)
        differ = (lab[tuple(a)] >= 0) & (lab[tuple(b)] >= 0) & (lab[tuple(a)] != lab[tuple(b)])
        edge[tuple(a)] |= differ
        edge[tuple(b)] |= differ
    lab[edge] = -1
    return names, lab


def best_turn(xyz):
    """The smallest largest side of the box round the points when the piece is turned about one world axis: (largest side, axis, angle in degrees, the three sides)."""
    best = None
    for ax in range(3):
        u, v = [k for k in range(3) if k != ax]
        for deg in range(0, 90, 3):
            c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
            a, b = xyz[:, u] * c + xyz[:, v] * s, -xyz[:, u] * s + xyz[:, v] * c
            sides = sorted([float(np.ptp(a)), float(np.ptp(b)), float(np.ptp(xyz[:, ax]))], reverse=True)
            if best is None or sides[0] < best[0] - 1e-6:
                best = (sides[0], "XYZ"[ax], deg, sides)
    return best


C45 = float(np.sqrt(0.5))
UP = {"Z (standing)": (0, 0, 1), "X (on its side)": (1, 0, 0), "Y (on its back wall)": (0, 1, 0), "the board's normal (on its back)": (0, -C45, C45), "the board's u": (0, C45, C45)}


def best_lie(xyz):
    """The piece put on the bed with one of UP's directions vertical and turned about it by whole degrees: (largest horizontal side, which direction is up, degrees, the two
    horizontal sides, the height), the choice with the smallest largest side among those no taller than BED."""
    best = None
    for what, up in UP.items():
        up = np.array(up, dtype=float)
        a = np.cross(up, (1.0, 0.0, 0.0) if abs(up[0]) < 0.9 else (0.0, 1.0, 0.0))
        a /= np.linalg.norm(a)
        b = np.cross(up, a)
        h = float(np.ptp(xyz @ up))
        pa, pb = xyz @ a, xyz @ b
        for deg in range(0, 180):
            c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
            sides = (float(np.ptp(pa * c + pb * s)), float(np.ptp(-pa * s + pb * c)))
            if h <= BED and (best is None or max(sides) < best[0] - 1e-6):
                best = (max(sides), what, deg, sides, h)
    return best


def report(f, rows, names, lab):
    vox = float(f["xs"][1] - f["xs"][0])
    pad_pos = {str(n): np.asarray(p[:3], dtype=float) for n, p, pc in zip(f["names"], f["pads"], f["pad_piece"]) if str(pc) == "main"}
    out = []
    for k, name in enumerate(names):
        idx = np.argwhere(lab == k)
        xyz = np.stack([f["xs"][idx[:, 0]], f["ys"][idx[:, 1]], f["zs"][idx[:, 2]]], axis=1)
        lo, hi = xyz.min(axis=0) - vox / 2, xyz.max(axis=0) + vox / 2
        _l, n = ndimage.label(lab == k, structure=np.ones((3, 3, 3)))
        big, ax, deg, sides = best_turn(xyz[:: max(1, len(xyz) // 20000)])
        lie = best_lie(xyz[:: max(1, len(xyz) // 20000)])
        tree = cKDTree(xyz)
        pads = sorted(p for p, q in pad_pos.items() if tree.query(q)[0] < 12.0)
        out.append(f"{name:8s} {len(idx) * vox ** 3 / 1000:7.1f} cm3  X {lo[0]:5.0f}..{hi[0]:5.0f} Y {lo[1]:5.0f}..{hi[1]:5.0f} Z {lo[2]:5.0f}..{hi[2]:5.0f}  "
                   f"box {hi[0] - lo[0]:3.0f} x {hi[1] - lo[1]:3.0f} x {hi[2] - lo[2]:3.0f}; turned {deg:2d} deg about {ax}: {sides[0] + vox:3.0f} x {sides[1] + vox:3.0f} x {sides[2] + vox:3.0f} "
                   f"({'fits' if sides[0] + vox <= BED else 'OVER'} {BED:g}); bodies {n}; pads {len(pads)}: {', '.join(pads) or 'none'}")
        out.append(f"         lying, up {lie[1]}, turned {lie[2]} deg: {lie[3][0] + 2 * vox:.0f} x {lie[3][1] + 2 * vox:.0f} on the bed, {lie[4] + vox:.0f} tall "
                   f"({'fits' if lie[0] + 2 * vox <= BED else 'OVER'} {BED:g})")
    cut = [(what, sorted(set(p))) for _k, _n, what, _pts, p in rows if len(set(p)) > 1]
    out.append("members the seams cut: " + ("; ".join(f"{what} ({'/'.join(ps)})" for what, ps in cut) or "none"))
    lost = int((f["d_main"] < 0).sum() - (lab >= 0).sum())
    out.append(f"taken out by the gaps: {lost * vox ** 3 / 1000:.1f} cm3")
    return out


KNOT_R, LAP, LAP_GAP, KNOT_MORE = 10.0, 24.0, 0.3, 6.0     # the joint: a knot of this radius, a lap this long, this far between its faces, the knot this much longer than the lap each end
BORE, HEAD_D, HEAD_H, PILOT, PILOT_DEPTH = 3.4, 6.5, 3.5, 4.5, 6.7


def joint_picture(f, prefix, bone="lip", at_x=None):
    """One half-lap joint drawn where a seam crosses a bone (the lip at X FRONT_X by default), on a grid of 0.75 mm, as a printable piece would be meshed: the two halves in two
    colours, put together and drawn apart, with the screw. A picture of what a joint looks like; nothing of it is in the model."""
    import vtk
    import hose_routes
    import shell_concepts as sc

    _m, lines = of.bone_members()
    line = np.asarray(lines[bone], dtype=float)
    k = int(np.argmin(np.abs(line[:, 0] - (FRONT_X if at_x is None else at_x))))
    P = line[k]
    e1 = line[k + 1] - line[k - 1]
    e1 /= np.linalg.norm(e1)
    out = np.array([0.0, -np.sqrt(0.5), np.sqrt(0.5)])               # the board's outward normal: the screw is driven from the front and above
    e3 = out - e1 * (out @ e1)
    e3 /= np.linalg.norm(e3)
    half = 36.0                                                      # the knot and a stub of the bone each side: the films round it are not laid for a seam yet and would only confuse the picture
    sl = tuple(slice(int(np.searchsorted(g, c - half)), int(np.searchsorted(g, c + half))) for g, c in zip((f["xs"], f["ys"], f["zs"]), P))
    d0 = ndimage.zoom(f["d_main"][sl].astype(np.float32), 2, order=1)
    vox = float(f["xs"][1] - f["xs"][0]) / 2
    grid = [g[s_][0] + vox * (np.arange(n) - 0.25) for g, s_, n in zip((f["xs"], f["ys"], f["zs"]), sl, d0.shape)]
    X, Y, Z = np.meshgrid(*grid, indexing="ij")
    R_ = np.stack([X - P[0], Y - P[1], Z - P[2]], axis=-1)
    a_, c_ = R_ @ e1, R_ @ e3
    rad = np.sqrt(np.maximum((R_ ** 2).sum(axis=-1) - a_ ** 2, 0.0))
    knot = np.maximum(rad - KNOT_R, np.abs(a_) - (LAP / 2 + KNOT_MORE))
    body = np.minimum(d0, knot)
    axis_r = np.sqrt(np.maximum(rad ** 2 - c_ ** 2, 0.0) + a_ ** 2)       # distance from the screw's axis (through P along e3)
    halves = {}
    for name, s_ in (("upper", 1.0), ("lower", -1.0)):
        region = np.minimum(s_ * a_ + LAP / 2, np.maximum(s_ * a_ - (LAP / 2 - LAP_GAP), LAP_GAP / 2 - s_ * c_))
        d = np.maximum(body, region)
        if s_ > 0:
            hole = np.minimum(BORE / 2 - axis_r, c_)                                              # the clearance bore, above the parting plane
            hole = np.maximum(hole, np.minimum(HEAD_D / 2 - axis_r, c_ - (KNOT_R - HEAD_H)))      # and the head's recess
        else:
            hole = np.minimum(PILOT / 2 - axis_r, c_ + PILOT_DEPTH)                               # the insert's pilot, blind
        halves[name] = np.maximum(d, hole).astype(np.float32)
    sc.VOX = vox
    shells = {name: sc.mesh(grid[0], grid[1], grid[2], d) for name, d in halves.items()}
    colours = {"upper": (0.20, 0.45, 0.80), "lower": (0.90, 0.55, 0.10)}
    for tag, lift in (("together", 0.0), ("apart", 22.0)):
        ren = vtk.vtkRenderer()
        ren.SetBackground(1, 1, 1)
        for name, shell in shells.items():
            m = vtk.vtkPolyDataMapper()
            m.SetInputData(shell)
            m.ScalarVisibilityOff()
            a = vtk.vtkActor()
            a.SetMapper(m)
            a.GetProperty().SetColor(*colours[name])
            a.GetProperty().SetAmbient(0.3)
            a.GetProperty().SetDiffuse(0.7)
            if name == "upper":
                a.SetPosition(*(e3 * lift))
            ren.AddActor(a)
        top = P + e3 * (KNOT_R + lift + (0.0 if lift == 0 else 14.0))
        ren.AddActor(hose_routes.tube_actor(np.array([top - e3 * HEAD_H, top]), 2.75, (0.75, 0.75, 0.78)))                      # the screw's head
        if lift:
            ren.AddActor(hose_routes.tube_actor(np.array([top - e3 * (HEAD_H + 12.0), top - e3 * HEAD_H]), 1.5, (0.75, 0.75, 0.78)))   # and its shank
            ren.AddActor(hose_routes.tube_actor(np.array([P - e3 * 4.2, P - e3 * 0.2]), 2.48, (0.85, 0.70, 0.25)))                # the brass insert, flush with the lower face
        win = vtk.vtkRenderWindow()
        win.SetOffScreenRendering(1)
        win.SetSize(1400, 1000)
        win.SetMultiSamples(0)
        win.AddRenderer(ren)
        c = ren.GetActiveCamera()
        c.SetFocalPoint(*P)
        c.SetPosition(*(P + 400.0 * np.array([0.35, -0.80, 0.55])))
        c.SetViewUp(0, 0, 1)
        c.ParallelProjectionOn()
        ren.ResetCamera()
        c.Zoom(1.1)
        win.Render()
        w2i = vtk.vtkWindowToImageFilter()
        w2i.SetInput(win)
        w2i.Update()
        wr = vtk.vtkPNGWriter()
        wr.SetFileName(f"{prefix}_{tag}.png")
        wr.SetInputConnection(w2i.GetOutputPort())
        wr.Write()
        print("saved", f"{prefix}_{tag}.png")
    print(f"joint on `{bone}` at X {P[0]:.0f}, Y {P[1]:.0f}, Z {P[2]:.0f}: knot radius {KNOT_R:g} over {LAP + 2 * KNOT_MORE:g} mm (the bone there is about 5.5), lap {LAP:g}, "
          f"{LAP_GAP:g} between the faces; M3 from the front and above into an insert in the lower half")


def main():
    mode = sys.argv[1]
    if mode == "joint":
        joint_picture(np.load(FIELD), sys.argv[2])
        return
    plan = PLANS[sys.argv[-1]] if sys.argv[-1] in PLANS else plan_v1
    f = np.load(FIELD)
    rows = members(plan)
    names, lab = label(f, rows)
    print("\n".join(report(f, rows, names, lab)))
    if mode == "picture":
        picture(f, names, lab, sys.argv[2])
    if mode == "field":
        z = {k: f[k] for k in f.files if not k.startswith("d_main")}
        for k, name in enumerate(names):
            z["d_" + name] = np.where(lab == k, f["d_main"], np.float32(1.0)).astype(np.float32)
        np.savez(sys.argv[2], **z)
        print("saved", sys.argv[2])


if __name__ == "__main__":
    main()
