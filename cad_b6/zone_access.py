#!/usr/bin/env python3
"""Zone access (revision 13): the two keep-outs where plugs go in, io_zone (the board's rear connectors) and gpu_out_zone (the card's video outputs), stay free,
and a cable bundle 20 mm across can leave each of them to the rear face of the skeleton without crossing a part.

docs/plans/b6-frame-v0.md, "Revision 13", item 10. The grid method of cad_b6/drive_access.py: every obstacle voxelised on one grid, grown, and searched.

  Free       no printed part stands in either zone (exact: boolean volume), no hardware solid but the two zones' own host (the overlap check 1 already says this for hardware),
             and no cable: the nearest strand's surface is at least CABLE_CLEAR from the zone's box (cables.py keeps its own 3 mm from every hardware solid, zones included).
  Way out    a ball of BUNDLE_D / 2 moves through the free air from the zone to the plane Y = the skeleton's rearmost point. Obstacles: the skeleton, every hardware solid and keep-out
             except the two zones, and the cables (the thin leads too), on a VOX grid; a ball's centre is free where it is BALL_R + one voxel from the nearest occupied voxel centre
             (the voxel's error is up to one voxel, so this is on the safe side). The desk is a floor.
  The layer  the organic layer (out/organic/field.npz, written by organic_frame.py) is NOT a hard obstacle here: revision 13 does not redraw it (the flanks are redrawn in the
             next revision). The report says what it does in the zones, in the slot, and whether the way out still exists with it.
  Layers     every layer of the grid (skeleton, hardware, cables, the organic layer) must be non-empty, as must the seeds, the target and the reached set: an empty one means the
             check looked at nothing.

Run:  .venv/bin/python cad_b6/zone_access.py          writes cad_b6/report_zone_access.txt, exit status 1 on a failure
"""
from __future__ import annotations

import os
import sys

from types import SimpleNamespace

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cadquery as cq  # noqa: E402,F401  (before vtk, see render_vtk.py)
from scipy import ndimage  # noqa: E402

import drive_access  # noqa: E402
import frame_v0  # noqa: E402
import hardware as hw  # noqa: E402

ZONES = ("io_zone", "gpu_out_zone")
ZONE_BS = {"io_zone": hw.IO_ZONE_BS, "gpu_out_zone": hw.GPU_OUT_ZONE_BS}
BUNDLE_D = 20.0                         # the bundle's diameter, mm (the plan: "a cable bundle 20 mm across")
BALL_R = BUNDLE_D / 2
VOX = 2.0                               # grid step, mm
CABLE_CLEAR = 0.0                       # a cable's surface may not enter the zone
CABLE_STEP = 0.25                       # a cable's polyline is resampled this finely before it is measured against a zone, mm
PAD_XY = 30.0                           # grid margin beyond the model, mm
SLOT_BS = (hw.x_to_v(hw.FAN_SIDE_INNER_X["fan_side_left"]), 0.0, hw.FAN_SIDE_U[0], hw.FAN_SIDE_U[1], hw.FAN_SIDE_N[0], hw.FAN_SIDE_N[1])      # the slot between the left fan's inner face and the board's edge, over the fan's footprint in (u, n)


class Grid:
    def __init__(self, parts, vox=VOX):
        self.vox = vox
        y_rear = max(frame_v0.bbox_of(p.solid)[3] for p in parts)
        self.y_rear = float(y_rear)
        lo = (-(hw.ENVELOPE_FAN_X + PAD_XY), -PAD_XY, hw.DESK_Z - 5.0)
        hi = (hw.ENVELOPE_FAN_X + PAD_XY, y_rear + 2 * PAD_XY, 420.0)
        self.xs = lo[0] + vox * np.arange(int(np.ceil((hi[0] - lo[0]) / vox)) + 1)
        self.ys = lo[1] + vox * np.arange(int(np.ceil((hi[1] - lo[1]) / vox)) + 1)
        self.zs = lo[2] + vox * np.arange(int(np.ceil((hi[2] - lo[2]) / vox)) + 1)
        self.shape = (len(self.xs), len(self.ys), len(self.zs))
        self.origin = (float(self.xs[0]), float(self.ys[0]), float(self.zs[0]))
        # the hull a bundle has to stay in on its way out: between the side fans' inner faces and below the top of the skeleton. The grid's own margin beyond it is not a way
        # out (the outside review of revision 13 showed a wall across the case being walked round through the margin beside the fans and over the top)
        self.x_hull = min(abs(x) for x in hw.FAN_SIDE_INNER_X.values())
        self.z_hull = float(max(frame_v0.bbox_of(p.solid)[5] for p in parts))

    def crop(self, bbox, pad):
        """(slices, origin, shape) of the part of the grid that holds bbox (xmin, xmax, ymin, ymax, zmin, zmax) with `pad` mm round it, or None."""
        sl = []
        for a, (lo, hi) in zip((self.xs, self.ys, self.zs), ((bbox[0], bbox[1]), (bbox[2], bbox[3]), (bbox[4], bbox[5]))):
            i0 = max(int(np.floor((lo - pad - a[0]) / self.vox)), 0)
            i1 = min(int(np.ceil((hi + pad - a[0]) / self.vox)) + 1, len(a))
            if i1 <= i0:
                return None
            sl.append(slice(i0, i1))
        sl = tuple(sl)
        return sl, (float(self.xs[sl[0].start]), float(self.ys[sl[1].start]), float(self.zs[sl[2].start])), tuple(s.stop - s.start for s in sl)

    def solid_occupancy(self, solids):
        occ = np.zeros(self.shape, dtype=bool)
        for s in solids:
            for one in (s.Solids() or [s]):
                c = self.crop(frame_v0.bbox_of(one), self.vox)
                if c is None:
                    continue
                sl, org, shp = c
                occ[sl] |= drive_access.voxelise(one, org, shp, self.vox)
        return occ

    def bs_coords(self):
        """(v, u, n) of every grid point, as three broadcastable arrays."""
        X, Y, Z = self.xs[:, None, None], self.ys[None, :, None], self.zs[None, None, :]
        a, b = (Y - hw.ORIGIN[1]) / hw.C, (Z - hw.ORIGIN[2]) / hw.C
        return X - hw.ORIGIN[0], (a + b) / 2, (b - a) / 2

    def zone_mask(self, box):
        v, u, n = self.bs_coords()
        return (v >= box[0]) & (v <= box[1]) & (u >= box[2]) & (u <= box[3]) & (n >= box[4]) & (n <= box[5])


def layers_of(grid, parts, hardware, strands, field=None, skip=ZONES):
    """{layer: boolean occupancy}: the skeleton, the hardware and keep-outs without the zones in `skip`, the cables, and (if given) the organic layer."""
    out = {"skeleton": grid.solid_occupancy([p.solid for p in parts]),
           "hardware": grid.solid_occupancy([s for k, s in hardware.items() if k not in skip]),
           "cables": drive_access.cable_occupancy(strands, grid.origin, grid.shape, grid.vox)}
    if field is not None:
        occ = np.zeros(grid.shape, dtype=bool)
        xs, ys, zs = field["xs"], field["ys"], field["zs"]
        # the field's grid (1.5 mm) sampled at this grid's points
        ix = np.clip(np.rint((grid.xs - xs[0]) / (xs[1] - xs[0])).astype(int), 0, len(xs) - 1)
        iy = np.clip(np.rint((grid.ys - ys[0]) / (ys[1] - ys[0])).astype(int), 0, len(ys) - 1)
        iz = np.clip(np.rint((grid.zs - zs[0]) / (zs[1] - zs[0])).astype(int), 0, len(zs) - 1)
        inside = (grid.xs >= xs[0]) & (grid.xs <= xs[-1])
        occ = (field["d"][np.ix_(ix, iy, iz)] < 0) & inside[:, None, None] \
            & ((grid.ys >= ys[0]) & (grid.ys <= ys[-1]))[None, :, None] & ((grid.zs >= zs[0]) & (grid.zs <= zs[-1]))[None, None, :]
        out["organic"] = occ
    return out


def reach(grid, occupied, seeds, extra_blocks=()):
    """The way out of each zone. occupied: boolean grid of everything in the way. Returns dict(free (ball centre free), reached {zone: mask of the free air connected to the zone's seeds},
    seeds {zone: count}, target (mask), out {zone: bool})."""
    occ = occupied.copy()
    occ[:, :, grid.zs < hw.DESK_Z] = True                                       # the desk is a floor
    occ[np.abs(grid.xs) > grid.x_hull, :, :] = True                             # outside the fans' inner faces: not a way out
    occ[:, :, grid.zs > grid.z_hull] = True                                     # above the skeleton's top: not a way out
    for (x0, x1, y0, y1, z0, z1) in extra_blocks:
        occ[np.ix_((grid.xs >= x0) & (grid.xs <= x1), (grid.ys >= y0) & (grid.ys <= y1), (grid.zs >= z0) & (grid.zs <= z1))] = True
    dist = ndimage.distance_transform_edt(~occ, sampling=grid.vox)
    free = dist >= BALL_R + grid.vox
    lab, _ = ndimage.label(free)
    target = free & (grid.ys[None, :, None] >= grid.y_rear)
    res = dict(free=free, target=target, reached={}, seeds={}, out={}, dist=dist)
    for z in ZONES:
        sd = free & grid.zone_mask(ZONE_BS[z])
        labels = np.unique(lab[sd])
        labels = labels[labels > 0]
        mask = np.isin(lab, labels) if len(labels) else np.zeros(grid.shape, dtype=bool)
        res["seeds"][z] = int(sd.sum())
        res["reached"][z] = mask
        res["out"][z] = bool((mask & target).any())
    return res


def widest(grid, dist, zone):
    """The largest ball radius (whole mm, from BALL_R up to 60) with which the zone still has a way out: the margin of the check, found by bisection on the clearance."""
    zm = grid.zone_mask(ZONE_BS[zone])
    rear = grid.ys[None, :, None] >= grid.y_rear

    def gets_out(radius):
        free = dist >= radius + grid.vox
        sd = free & zm
        if not sd.any():
            return False
        lab, _ = ndimage.label(free)
        labels = np.unique(lab[sd])
        return bool(np.isin(lab[free & rear], labels[labels > 0]).any())
    lo, hi = int(BALL_R), 60
    if not gets_out(lo):
        return 0
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if gets_out(mid) else (lo, mid)
    return lo


def densify(p, step=CABLE_STEP):
    """The polyline with points added so that no two neighbours are further apart than `step`: a chord between two of the route's points (3 mm apart) can cut a corner of a box that both
    points miss."""
    if len(p) < 2:
        return p
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    if s[-1] <= 0:
        return p
    t = np.unique(np.concatenate([s, np.arange(0.0, s[-1], step)]))
    return np.stack([np.interp(t, s, p[:, k]) for k in range(3)], axis=1)


def cable_clearance(strands, zone):
    """Smallest distance (mm) from any cable surface to the zone's box, negative inside it: the polyline resampled every CABLE_STEP mm (radius added) in board space against the box."""
    v0, v1, u0, u1, n0, n1 = ZONE_BS[zone]
    best = (float("inf"), "-")
    for cn, sl in strands.items():
        for p, r in sl:
            p = densify(np.asarray(p, dtype=float))
            a, b = (p[:, 1] - hw.ORIGIN[1]) / hw.C, (p[:, 2] - hw.ORIGIN[2]) / hw.C
            q = np.stack([p[:, 0] - hw.ORIGIN[0], (a + b) / 2, (b - a) / 2], axis=1)
            lo, hi = np.array([v0, u0, n0]), np.array([v1, u1, n1])
            d = np.linalg.norm(np.maximum(np.maximum(lo - q, q - hi), 0), axis=1)
            inside = np.all((q >= lo) & (q <= hi), axis=1)
            d = np.where(inside, -np.min(np.minimum(q - lo, hi - q), axis=1), d) - r
            k = float(d.min())
            if k < best[0]:
                best = (k, cn)
    return best


def part_clearance(parts, hardware, zone):
    """[(part, overlap mm3, distance mm)] for the parts within 30 mm of the zone."""
    box = hardware[zone]
    zb = frame_v0.bbox_of(box)
    rows = []
    for p in parts:
        if frame_v0.bbox_gap(frame_v0.bbox_of(p.solid), zb) > 30.0:
            continue
        rows.append((p.name, frame_v0.inter_vol(p.solid, box), frame_v0.solid_distance(p.solid, box)))
    return sorted(rows, key=lambda r: r[2])


def run(parts=None, hardware=None, strands=None, field=None, extra_blocks=(), extra_parts=()):
    """The whole check. Returns (lines for the report, failures, results). extra_blocks: [(x0, x1, y0, y1, z0, z1)] more obstacles for the way out; extra_parts: [shape] more printed
    parts (the tests put a block in a zone with it)."""
    if hardware is None:
        hardware = hw.build_hardware()
    if parts is None:
        parts, _ = frame_v0.build_frame(hardware=hardware)
    if strands is None:
        strands, _skipped = drive_access.cable_strands()
    lines, fails = [], []
    grid = Grid(parts)
    lines.append("Зоны штекеров (cad_b6/zone_access.py, ревизия 13): io_zone (разъёмы платы) и gpu_out_zone (видеовыходы карты) свободны, и жгут Ø20 мм выходит из каждой к задней грани каркаса.")
    lines.append(f"  Сетка {grid.vox:g} мм, {grid.shape[0]} x {grid.shape[1]} x {grid.shape[2]} вокселей, X {grid.xs[0]:.0f}..{grid.xs[-1]:.0f}, Y {grid.ys[0]:.0f}..{grid.ys[-1]:.0f}, Z {grid.zs[0]:.0f}..{grid.zs[-1]:.0f}. "
                 f"Шар жгута R {BALL_R:g}: центр свободен, если до ближайшего занятого вокселя не меньше {BALL_R + grid.vox:g} мм (R + воксель, с запасом на ошибку вокселя). Цель: плоскость Y = {grid.y_rear:.1f} "
                 f"(самая задняя точка каркаса). Стол - пол. Жгут обязан оставаться в габарите: |X| <= {grid.x_hull:g} (внутренние грани боковых вентиляторов) и Z <= {grid.z_hull:g} (верх каркаса); поле сетки за ним выходом не считается.")
    all_parts = list(parts) + [SimpleNamespace(solid=s, name="extra") for s in extra_parts]
    lay = layers_of(grid, all_parts, hardware, strands, field)
    occupied = lay["skeleton"] | lay["hardware"] | lay["cables"]
    for n, m in lay.items():
        lines.append(f"  слой {n}: {int(m.sum())} вокселей")
    for n in ("skeleton", "hardware", "cables"):
        if not lay[n].any():
            fails.append(f"ZONE_ACCESS layer {n} is empty: the check looked at nothing")
    if field is not None and not lay["organic"].any():
        fails.append("ZONE_ACCESS layer organic is empty: the field was given but holds no material")
    r = reach(grid, occupied, None, extra_blocks)
    if not r["target"].any():
        fails.append("ZONE_ACCESS the target (free air at the rear plane) is empty")
    results = dict(grid=grid, reach=r, layers=lay)
    for z in ZONES:
        rows = part_clearance(all_parts, hardware, z)
        near = rows[0] if rows else ("-", 0.0, float("inf"))
        bad = [x for x in rows if x[1] >= frame_v0.VOL_EPS]
        for name, vol, _d in bad:
            fails.append(f"ZONE_ACCESS {z}: the printed part {name} stands in it ({vol:.1f} mm3)")
        cd, cn = cable_clearance(strands, z)
        if cd < CABLE_CLEAR - 1e-6:
            fails.append(f"ZONE_ACCESS {z}: the cable {cn} stands in it (its surface is {cd:.1f} mm from the box, needs {CABLE_CLEAR:g})")
        lines.append(f"  {z}: ближайшая печатная деталь {near[0]} в {near[2]:.1f} мм (пересечение {near[1]:.1f} мм3), ближайший кабель {cn} в {cd:.1f} мм")
        n_seed, ok = r["seeds"][z], r["out"][z]
        if n_seed == 0:
            fails.append(f"ZONE_ACCESS {z}: no place for a ball of {BUNDLE_D:g} mm in the zone")
        if not r["reached"][z].any():
            fails.append(f"ZONE_ACCESS {z}: the free air reached from the zone is empty")
        elif not ok:
            fails.append(f"ZONE_ACCESS {z}: a bundle of {BUNDLE_D:g} mm cannot leave the zone for the rear face (Y {grid.y_rear:.0f}) without crossing a part, a keep-out or a cable")
        reached_pts = r["reached"][z]
        wide = widest(grid, r["dist"], z) if ok else 0
        lines.append(f"  {z}: центров шара в зоне {n_seed}, достижимого свободного воздуха {int(reached_pts.sum()) * grid.vox ** 3 / 1000:.0f} см3, до задней грани: {'ДА' if ok else 'НЕТ'}, "
                     f"самый толстый жгут, который ещё выходит: Ø{2 * wide} мм (запас по диаметру {2 * wide - BUNDLE_D:g} мм)   "
                     + ("PASS" if ok and n_seed and not bad and cd >= CABLE_CLEAR else "FAIL"))
    if field is not None:
        with_layer = reach(grid, occupied | lay["organic"], None, extra_blocks)
        for z in ZONES:
            lz = int((lay["organic"] & grid.zone_mask(ZONE_BS[z])).sum()) * grid.vox ** 3 / 1000
            lines.append(f"  слой (органическая оболочка, ревизия 13 её не перерисовывает) в {z}: {lz:.1f} см3; жгут выходит и с ней: {'ДА' if with_layer['out'][z] else 'НЕТ (слой перекрывает выход, его перерисуют во фланговой ревизии)'}")
        lz = int((lay["organic"] & grid.zone_mask(SLOT_BS)).sum()) * grid.vox ** 3 / 1000
        lines.append(f"  слой в щели между левым вентилятором и платой (v {SLOT_BS[0]:.0f}..{SLOT_BS[1]:.0f}, u {SLOT_BS[2]:g}..{SLOT_BS[3]:g}, n {SLOT_BS[4]:g}..{SLOT_BS[5]:g}): {lz:.1f} см3")
        results["with_layer"] = with_layer
    return lines, fails, results


def main():
    field = drive_access.load_field() if os.path.exists(drive_access.FIELD) else None
    lines, fails, _ = run(field=field)
    if field is None:
        fails.append(f"ZONE_ACCESS the organic layer's field {drive_access.FIELD} is missing: the layer was not looked at (run organic_frame.py first)")
    text = "\n".join(lines + ["", "ПРОВЕРКИ НЕ ПРОЙДЕНЫ:" if fails else "Все проверки пройдены."] + (["  - " + f for f in fails] if fails else []))
    with open(os.path.join(HERE, "report_zone_access.txt"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)
    if fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
