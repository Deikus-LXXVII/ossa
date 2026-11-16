#!/usr/bin/env python3
"""Drive access: can a drive sled, with its drives on it, be carried in from behind the case and set down beside the PSU?

docs/plans/cables-and-organic.md, "Drive bays: which way the drive goes in" and "Drive bays, pass 1". The sled is put in from behind and above, over the bulkhead,
and down: a sweep in three degrees of freedom, Y, Z and the tilt about X, over a (Y, Z) map of everything that is in the way.

  Obstacles  the skeleton without this bay's sled, the hardware without this bay's drive and plug zone (keep-outs too), the cable solids and the organic layer
             (out/organic/field.npz, written by organic_frame.py), each voxelised on the layer's 1.5 mm grid and grown by one voxel (1.5 mm), then collapsed over the
             bay's X range (hw.DRIVE_ENVELOPE), because the sled moves in a plane and the slot beside the PSU is that wide. Free air is added behind and above the case.
             The desk is a floor. Every cable route of cables.py is in the grid, thin leads too, as the polyline of its strands thickened by the real radius.
  Body       the bay seen from the side: the union of the (Y, Z) bounding rectangles of the built sled, drives and (second run) plug boxes, which turns about its centre.
  Seat       the final pose backed off by SEAT_BACKOFF (3 mm back and 3 mm up): the sled's foot and flange touch the skid and the bulkhead, which the grown obstacles
             would block. The last 3 mm are a settling move and are not swept.
  Fails      when the seat cannot be reached from a pose behind the case with at most TILT_MAX (30) degrees of tilt.

Run:  .venv/bin/python cad_b6/drive_access.py          writes cad_b6/report_drive_access.txt, exit status 1 on a failure
"""
from __future__ import annotations

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cadquery as cq  # noqa: E402,F401  (before vtk, see render_vtk.py)
import vtk  # noqa: E402
from scipy import ndimage, signal  # noqa: E402
from vtk.util import numpy_support  # noqa: E402

import frame_v0  # noqa: E402
import hardware as hw  # noqa: E402

FIELD = os.path.join(ROOT, "out", "organic", "field.npz")
GROW = 1                                  # voxels of growth: 1.5 mm on the layer's grid
TILT_MAX = 30.0                           # deg: the most tilt the check allows
PITCHES = np.arange(-90.0, 90.1, 2.0)
TILT_STEPS = tuple(float(t) for t in range(0, 31, 2)) + (45.0, 60.0, 90.0)
SEAT_BACKOFF = (3.0, 3.0)                 # mm: (back along -Y, up along +Z) from the final pose to the pose that is swept to
PAD_Y_MM, PAD_Z_MM = 300.0, 90.0          # free air behind and above the grid
START_BEHIND = 160.0                      # mm: the start pose's centre this far behind the grid's rear end ...
START_Z = 200.0                           # ... at this height
DESK_Z = hw.DESK_Z


# ---------------------------------------------------------------------------
# voxels
# ---------------------------------------------------------------------------
def load_field(path=FIELD):
    if not os.path.exists(path):
        sys.exit(f"{path} is missing: run cad_b6/organic_frame.py first (it writes the layer's field)")
    f = np.load(path)
    return dict(d=f["d"], xs=f["xs"].astype(float), ys=f["ys"].astype(float), zs=f["zs"].astype(float))


def voxelise(solid, origin, shape, vox):
    """Boolean occupancy of the solid on a grid of `shape` voxels from `origin` (the centre of the first voxel)."""
    occ = np.zeros(shape, dtype=bool)
    for s in solid.Solids():
        verts, tris = s.tessellate(0.3)
        pd = vtk.vtkPolyData()
        vp = vtk.vtkPoints()
        vp.SetData(numpy_support.numpy_to_vtk(np.array([(v.x, v.y, v.z) for v in verts], dtype=np.float64), deep=True))
        pd.SetPoints(vp)
        cells = vtk.vtkCellArray()
        for t in tris:
            cells.InsertNextCell(3, t)
        pd.SetPolys(cells)
        st = vtk.vtkPolyDataToImageStencil()
        st.SetInputData(pd)
        st.SetOutputOrigin(*origin)
        st.SetOutputSpacing(vox, vox, vox)
        st.SetOutputWholeExtent(0, shape[0] - 1, 0, shape[1] - 1, 0, shape[2] - 1)
        st.Update()
        conv = vtk.vtkImageStencilToImage()
        conv.SetInputConnection(st.GetOutputPort())
        conv.SetInsideValue(1)
        conv.SetOutsideValue(0)
        conv.SetOutputScalarTypeToUnsignedChar()
        conv.Update()
        arr = numpy_support.vtk_to_numpy(conv.GetOutput().GetPointData().GetScalars())
        occ |= arr.reshape(shape, order="F").astype(bool)
    return occ


def cable_strands(routes=None):
    """({cable: [(points (N x 3), radius)]}, [cables without any strand]): the cable routes of cables.py as the polylines their solids are swept along (chain_solid: a cylinder per
    segment, a sphere per joint, that is the polyline thickened by the radius). Built from the strands, not from the solids, because tessellating the thousands of
    3 mm cylinders of the solids costs minutes; the voxels are the same."""
    if routes is None:
        import cables
        routes = cables.build_routes()
    out = {n: [(np.asarray(p, float), float(r)) for p, r in rt.strands] for n, rt in routes.items() if rt.strands}
    return out, sorted(n for n, rt in routes.items() if not rt.strands)


def cable_occupancy(strands, origin, shape, vox):
    """Boolean occupancy of the cables on a grid: every voxel whose centre is within the strand's radius of its polyline (a distance transform of the densified centreline)."""
    pad = int(np.ceil(max((r for sl in strands.values() for _p, r in sl), default=0.0) / vox)) + 2     # a centreline just outside the slab still reaches into it
    big = (shape[0] + 2 * pad, shape[1] + 2 * pad, shape[2] + 2 * pad)
    org = np.array(origin, float) - pad * vox
    by_r: dict = {}
    for sl in strands.values():
        for p, r in sl:
            by_r.setdefault(r, []).append(p)
    occ = np.zeros(big, dtype=bool)
    for r, plist in by_r.items():
        centre = np.zeros(big, dtype=bool)
        for p in plist:
            seg = np.diff(p, axis=0)
            n = np.maximum(np.ceil(np.linalg.norm(seg, axis=1) / (vox / 2)).astype(int), 1)
            pts = np.vstack([p[i] + seg[i] * (np.arange(n[i]) / n[i])[:, None] for i in range(len(seg))] + [p[-1:]])
            idx = np.rint((pts - org) / vox).astype(int)
            ok = np.all((idx >= 0) & (idx < np.array(big)), axis=1)
            centre[tuple(idx[ok].T)] = True
        if centre.any():
            occ |= ndimage.distance_transform_edt(~centre, sampling=vox) <= r
    return occ[pad:pad + shape[0], pad:pad + shape[1], pad:pad + shape[2]]


def bay_maps(parts, hardware, strands, field, side_name):
    """The (Y, Z) maps of one bay: for each layer a boolean map of the cells where something of that layer, grown by GROW voxels, lies anywhere over the bay's X range."""
    xs, ys, zs = field["xs"], field["ys"], field["zs"]
    vox = float(xs[1] - xs[0])
    ex = hw.DRIVE_ENVELOPE[0]
    x0, x1 = sorted((hw.DRIVE_SIDES[side_name] * ex[0], hw.DRIVE_SIDES[side_name] * ex[1]))
    i0, i1 = int(np.searchsorted(xs, x0)), int(np.searchsorted(xs, x1)) + 1           # voxels i0 .. i1 - 1 lie over the bay
    ia, ib = i0 - GROW, i1 + GROW                                                     # the slab carries the growth in X too
    origin = (float(xs[ia]), float(ys[0]), float(zs[0]))
    shape = (ib - ia, len(ys), len(zs))
    slab = (x0 - GROW * vox - 2.0, x1 + GROW * vox + 2.0)

    def near(solid):
        b = frame_v0.bbox_of(solid)
        return b[1] >= slab[0] and b[0] <= slab[1]

    own = {f"drive_sled_{side_name}", f"drive_{side_name}", f"drive_plugs_{side_name}"}
    layers = {
        "skeleton": [p.solid for p in parts if p.name not in own],
        "hardware": [s for n, s in hardware.items() if n not in own],
    }
    grids = {}
    for name, solids in layers.items():
        occ = np.zeros(shape, dtype=bool)
        for s in solids:
            if near(s):
                occ |= voxelise(s, origin, shape, vox)
        grids[name] = occ
    grids["cables"] = cable_occupancy(strands, origin, shape, vox)
    grids["organic"] = field["d"][ia:ib] < 0
    out = {}
    for name, occ in grids.items():
        grown = ndimage.binary_dilation(occ, iterations=GROW)
        out[name] = grown[GROW:GROW + (i1 - i0)].any(axis=0)
    return dict(layers=out, ys=ys, zs=zs, vox=vox, x_cells=(float(xs[i0]), float(xs[i1 - 1])), side=side_name)


# ---------------------------------------------------------------------------
# the body, the seat and the sweep
# ---------------------------------------------------------------------------
def bay_rects(parts, hardware, side_name):
    """(rects without the plug zone, rects with it): each a list of (y0, y1, z0, z1), the bounding rectangles seen from the side of the built solids: the sled, each drive, each plug box.
    Their union is the bay's silhouette (an L when the plug zone is in: the plug boxes are narrower than the sled and stand on the drives)."""
    byname = {p.name: p for p in parts}
    bodies = [byname[f"drive_sled_{side_name}"].solid] + list(hardware[f"drive_{side_name}"].Solids())
    plugs = list(hardware[f"drive_plugs_{side_name}"].Solids())

    def rects(solids):
        return [(b[2], b[3], b[4], b[5]) for b in (frame_v0.bbox_of(s) for s in solids)]
    return rects(bodies), rects(bodies + plugs)


def silhouette(rects):
    """(y0, y1, z0, z1) of the union of the rectangles."""
    return (min(r[0] for r in rects), max(r[1] for r in rects), min(r[2] for r in rects), max(r[3] for r in rects))


def access(maps, rects, extra_blocks=(), tilts=TILT_STEPS):
    """Sweep the body, the union of the rectangles `rects` (y0, y1, z0, z1 in its final pose), from behind the case to the seat. extra_blocks: [(y0, y1, z0, z1)] more obstacles (the tests
    use it). Returns dict(goal_free, start_free, least (the least tilt in degrees that connects the start and the seat, or None), seat, size, start)."""
    vox = maps["vox"]
    ys, zs = maps["ys"], maps["zs"]
    blocked = np.zeros((len(ys), len(zs)), dtype=bool)
    for m in maps["layers"].values():
        blocked |= m
    for (by0, by1, bz0, bz1) in extra_blocks:
        blocked[np.ix_((ys >= by0) & (ys <= by1), (zs >= bz0) & (zs <= bz1))] = True
    py, pz = int(round(PAD_Y_MM / vox)), int(round(PAD_Z_MM / vox))
    free = np.pad(~blocked, ((0, py), (0, pz)), constant_values=True)
    yy = ys[0] + vox * np.arange(free.shape[0])
    zz = zs[0] + vox * np.arange(free.shape[1])
    free[:, zz < DESK_Z] = False
    y0, y1, z0, z1 = silhouette(rects)
    LY, LZ = y1 - y0, z1 - z0
    c0 = ((y0 + y1) / 2, (z0 + z1) / 2)                                           # the pose is the silhouette's centre; the body turns about it
    cy, cz = c0[0] - SEAT_BACKOFF[0], c0[1] + SEAT_BACKOFF[1]
    r = int(np.ceil(np.hypot(LY, LZ) / 2 / vox)) + 2
    gy, gz = np.meshgrid(np.arange(-r, r + 1) * vox, np.arange(-r, r + 1) * vox, indexing="ij")
    obstacle = (~free).astype(np.float32)
    ok = np.zeros((len(PITCHES),) + free.shape, dtype=bool)
    for k, p in enumerate(PITCHES):
        c, s = np.cos(np.radians(p)), np.sin(np.radians(p))
        u, v = c * gy + s * gz, -s * gy + c * gz                                  # body-frame coordinates of each cell of the kernel
        mask = np.zeros(gy.shape, dtype=bool)
        for (ry0, ry1, rz0, rz1) in rects:
            mask |= (u >= ry0 - c0[0]) & (u <= ry1 - c0[0]) & (v >= rz0 - c0[1]) & (v <= rz1 - c0[1])
        ok[k] = signal.fftconvolve(obstacle, mask[::-1, ::-1].astype(np.float32), mode="same") < 0.5
    k0 = int(np.argmin(np.abs(PITCHES)))
    goal = (k0, int(np.argmin(np.abs(yy - cy))), int(np.argmin(np.abs(zz - cz))))
    start = (k0, int(np.argmin(np.abs(yy - (ys[-1] + START_BEHIND)))), int(np.argmin(np.abs(zz - START_Z))))
    res = dict(goal_free=bool(ok[goal]), start_free=bool(ok[start]), least=None, seat=(cy, cz), size=(LY, LZ), start=(float(yy[start[1]]), float(zz[start[2]])))
    if not (ok[goal] and ok[start]):
        return res
    for t in tilts:
        sel = np.abs(PITCHES) <= t + 1e-9
        lab, _ = ndimage.label(ok[sel])
        kk = int(np.argmin(np.abs(PITCHES[sel])))
        if lab[(kk,) + goal[1:]] != 0 and lab[(kk,) + goal[1:]] == lab[(kk,) + start[1:]]:
            res["least"] = t
            break
    return res


def verdict(res):
    if not res["goal_free"]:
        return "the seat is blocked"
    if not res["start_free"]:
        return "the start pose is blocked"
    if res["least"] is None:
        return "no path"
    return f"path, least tilt {res['least']:g} deg" + ("" if res["least"] <= TILT_MAX else f" (more than the {TILT_MAX:g} allowed)")


def passes(res):
    return res["least"] is not None and res["least"] <= TILT_MAX


# ---------------------------------------------------------------------------
# distances the sweep does not give: the organic layer and the cables to the bay's bodies
# ---------------------------------------------------------------------------
def organic_gap(field, hardware, parts, side_name, margin=45.0):
    """Smallest distance (mm) from the organic layer to the bay's drive, plug zone and sled: [(name, mm)], from a distance transform of the layer on a window round the bay."""
    xs, ys, zs = field["xs"], field["ys"], field["zs"]
    vox = float(xs[1] - xs[0])
    byname = {p.name: p for p in parts}
    items = {f"drive_{side_name}": hardware[f"drive_{side_name}"], f"drive_plugs_{side_name}": hardware[f"drive_plugs_{side_name}"],
             f"drive_sled_{side_name}": byname[f"drive_sled_{side_name}"].solid}
    bs = [frame_v0.bbox_of(s) for s in items.values()]
    lo = [min(b[k] for b in bs) - margin for k in (0, 2, 4)]
    hi = [max(b[k] for b in bs) + margin for k in (1, 3, 5)]
    sl = tuple(slice(int(np.searchsorted(g, a)), int(np.searchsorted(g, b)) + 1) for g, a, b in zip((xs, ys, zs), lo, hi))
    layer = field["d"][sl] < 0
    dist = ndimage.distance_transform_edt(~layer, sampling=vox) if layer.any() else np.full(layer.shape, np.inf)
    origin = (float(xs[sl[0].start]), float(ys[sl[1].start]), float(zs[sl[2].start]))
    out = []
    for name, s in items.items():
        occ = voxelise(s, origin, layer.shape, vox)
        out.append((name, float(dist[occ].min()) if occ.any() else float("nan")))
    return out


def gap_failures(organic, side_name):
    """DRIVE_ACCESS lines when the organic layer is closer than PLA_GAP to a drive (the plan: PLA keeps the distance it keeps from the card and the PSU; a 3.5 inch drive runs warm)."""
    gap = _pla_gap()
    return [f"DRIVE_ACCESS {side_name} bay: the organic layer is {d:.1f} mm from {n}, PLA keeps {gap:g}" for n, d in organic if n == f"drive_{side_name}" and not d >= gap]


def cable_gap(strands, hardware, parts, side_name, reach=40.0):
    """[(cable, body, mm)]: for each of the bay's bodies the nearest cable surface (the strand's points are 3 mm apart; the distance is to the centreline's points less the radius;
    negative: the cable passes through the body). Only points within `reach` mm of the body's box are measured."""
    byname = {p.name: p for p in parts}
    items = {f"drive_{side_name}": hardware[f"drive_{side_name}"], f"drive_plugs_{side_name}": hardware[f"drive_plugs_{side_name}"],
             f"drive_sled_{side_name}": byname[f"drive_sled_{side_name}"].solid}
    out = []
    for bn, bs in items.items():
        b = frame_v0.bbox_of(bs)
        best = (float("inf"), "-")
        for cn, sl in strands.items():
            for p, r in sl:
                gx = np.maximum(np.maximum(b[0] - p[:, 0], p[:, 0] - b[1]), 0)
                gy = np.maximum(np.maximum(b[2] - p[:, 1], p[:, 1] - b[3]), 0)
                gz = np.maximum(np.maximum(b[4] - p[:, 2], p[:, 2] - b[5]), 0)
                for q in p[np.sqrt(gx * gx + gy * gy + gz * gz) <= reach + r]:
                    d = frame_v0.solid_distance(cq.Vertex.makeVertex(*map(float, q)), bs) - r
                    if d < best[0]:
                        best = (d, cn)
        out.append((best[1], bn, best[0]))
    return out


# ---------------------------------------------------------------------------
def run(parts=None, hardware=None, field=None, strands=None, extra_blocks=()):
    """The whole check. Returns (lines for the report, failures, results {(bay, with_plugs): access result})."""
    if hardware is None:
        hardware = hw.build_hardware()
    if parts is None:
        parts, _ = frame_v0.build_frame(hardware=hardware)
    field = field or load_field()
    skipped = []
    if strands is None:
        strands, skipped = cable_strands()
    lines, fails, results = [], [], {}
    lines.append("Доступ к отсекам под диски (cad_b6/drive_access.py): салазки с дисками заносятся сзади и сверху над перегородкой и опускаются к месту у БП.")
    lines.append(f"  Препятствия: каркас без салазок этого отсека, железо без его дисков (зоны запрета тоже), тела кабелей и органический слой (сетка {field['xs'][1] - field['xs'][0]:g} мм), "
                 f"каждое увеличено на {GROW} воксель ({GROW * (field['xs'][1] - field['xs'][0]):g} мм), схлопнуто по X отсека |X| {hw.DRIVE_ENVELOPE[0][0]:g}..{hw.DRIVE_ENVELOPE[0][1]:g}; сзади и сверху воздух, пол - стол Z {DESK_Z:g}.")
    lines.append(f"  Кабели в сетке: все {len(strands)} маршрутов cables.py (по ломаным их жил, радиус настоящий); без жил и потому пропущены: {', '.join(skipped) if skipped else 'нет'}.")
    lines.append(f"  Тело - силуэт отсека сбоку: объединение прямоугольников (Y, Z) построенных салазок, дисков и (во втором прогоне) боксов зоны штекеров; место - конечная поза, отодвинутая на {SEAT_BACKOFF[0]:g} мм назад и {SEAT_BACKOFF[1]:g} мм вверх "
                 f"(последние {SEAT_BACKOFF[0]:g} мм - посадка на ступню и перегородку, не проверяются); наклон вокруг X до {TILT_MAX:g}°, шаг {PITCHES[1] - PITCHES[0]:g}°.")
    for side in hw.DRIVE_SIDES:
        maps = bay_maps(parts, hardware, strands, field, side)
        r_plain, r_plug = bay_rects(parts, hardware, side)
        for with_plugs, rects in ((False, r_plain), (True, r_plug)):
            rect = silhouette(rects)
            res = access(maps, rects, extra_blocks)
            results[(side, with_plugs)] = res
            lab = "с зоной штекеров" if with_plugs else "без зоны штекеров"
            lines.append(f"  {side:5s} {lab:18s} тело (силуэт сбоку) Y {rect[0]:.1f}..{rect[1]:.1f} x Z {rect[2]:.1f}..{rect[3]:.1f}, "
                         f"место (центр) Y {res['seat'][0]:.1f}, Z {res['seat'][1]:.1f}, старт Y {res['start'][0]:.0f}, Z {res['start'][1]:.0f}: {verdict(res)}   "
                         + ("PASS" if passes(res) else "FAIL"))
            if not passes(res):
                fails.append(f"DRIVE_ACCESS {side} bay {'with' if with_plugs else 'without'} the plug zone: {verdict(res)}")
        cells = maps["x_cells"]
        lines.append(f"        (слои, у которых есть препятствия в карте {side}: " + ", ".join(f"{n} {int(m.sum())} клеток" for n, m in maps["layers"].items()) + f"; X воксели {cells[0]:.1f}..{cells[1]:.1f})")
        og = organic_gap(field, hardware, parts, side)
        fails += gap_failures(og, side)
        lines.append(f"        органический слой до тел отсека, мм: " + ", ".join(f"{n} {d:.1f}" for n, d in og) + f" (слой держит {_pla_gap():g} мм от диска - ЦЕЛЬ плана; форму слоя этот проход не менял)")
        cg = cable_gap(strands, hardware, parts, side)
        lines.append(f"        ближайший кабель к телам отсека, мм: " + ", ".join(f"{b} {d:.1f} ({c})" for c, b, d in cg))
    return lines, fails, results


def _pla_gap():
    import organic_frame
    return organic_frame.PLA_GAP


def main():
    lines, fails, _ = run()
    text = "\n".join(lines + ["", "ПРОВЕРКИ НЕ ПРОЙДЕНЫ:" if fails else "Все проверки пройдены."] + (["  - " + f for f in fails] if fails else []))
    with open(os.path.join(HERE, "report_drive_access.txt"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
