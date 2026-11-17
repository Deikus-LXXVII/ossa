"""Property tests (Hypothesis) of the model's pure helper functions.

test_checks.py proves the model on the cases someone thought of; these tests state what each helper promises for every input in the
model's range and let Hypothesis look for the one that breaks it. They build no solid beyond a box or a cylinder and take about half a minute.

Run:  .venv/bin/python cad_b6/test_properties.py          prints one line per property, a count, PASS or FAIL; exit status 1 on a failure

Settings: derandomize=True (the same examples every run, so a failure is reproducible and a pass is not luck), no deadline, no example database.
A property that fails on the real code is a finding: it is marked xfail=<reason> with the falsifying example and reported. The property is not
weakened and the function is not changed. An xfail that passes is itself a failure (the mark has to go).

Every tolerance is written beside its property. A tolerance is a bound on float rounding at the model's scale (coordinates up to a few
hundred mm), not room for a wrong answer.
"""
from __future__ import annotations

import functools
import math
import os
import sys
import time
import traceback

import numpy as np
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cadquery as cq  # noqa: E402  (before anything that may import vtk)
import frame_v0 as fr  # noqa: E402
import hardware as hw  # noqa: E402
import hoses  # noqa: E402
import zone_access as za  # noqa: E402

TESTS: list[dict] = []


def prop(*strategies, examples=200, xfail=None):
    """Register a property: the function runs on `examples` generated inputs. xfail=<reason> marks a known failure on the real code."""
    def deco(fn):
        calls = [0]

        @functools.wraps(fn)
        def counted(*a, **kw):
            r = fn(*a, **kw)
            calls[0] += 1                     # counted after the body returns: an example that assume() rejected is not one
            return r

        test = settings(max_examples=examples, deadline=None, derandomize=True, database=None,
                        suppress_health_check=list(HealthCheck))(given(*strategies)(counted))
        TESTS.append(dict(name=fn.__name__, test=test, calls=calls, xfail=xfail, doc=(fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else ""))
        return fn
    return deco


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------
def fl(lo, hi):
    return st.floats(lo, hi, allow_nan=False, allow_infinity=False)


COORD = fl(-1000.0, 1000.0)                     # a board-space or world coordinate, mm (the model spans about 500 mm)
POINT3 = st.tuples(fl(-300, 300), fl(-300, 300), fl(-300, 300))


def close(a, b, tol):
    return abs(a - b) <= tol


def close_all(a, b, tol):
    return all(close(x, y, tol) for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# hardware.py: board space <-> world
# ---------------------------------------------------------------------------
@prop(COORD, COORD, COORD, examples=1000)
def bp_then_bs_of_is_identity(v, u, n):
    """bs_of(bp(v, u, n)) == (v, u, n). Tolerance 1e-9 mm: the arithmetic is a 45 degree rotation and a shift of at most 1e3 mm."""
    assert close_all(hw.bs_of(*hw.bp(v, u, n)), (v, u, n), 1e-9)


@prop(COORD, COORD, COORD, examples=1000)
def bs_of_then_bp_is_identity(x, y, z):
    """bp(bs_of(x, y, z)) == (x, y, z)."""
    assert close_all(hw.bp(*hw.bs_of(x, y, z)), (x, y, z), 1e-9)


@prop(COORD, COORD, COORD, COORD, examples=1000)
def bp_yz_agrees_with_bp_and_ignores_v(v, v2, u, n):
    """bp_yz(u, n) is the (Y, Z) of bp(v, u, n) for any v, and bp's X is ORIGIN X + v."""
    assert close_all(hw.bp_yz(u, n), hw.bp(v, u, n)[1:], 1e-9)
    assert close_all(hw.bp(v, u, n)[1:], hw.bp(v2, u, n)[1:], 1e-9)
    assert close(hw.bp(v, u, n)[0], hw.ORIGIN[0] + v, 1e-9)


@prop(COORD, COORD, COORD, examples=1000)
def x_to_v_inverts_the_x_of_bp_and_matches_bs_of(x, y, z):
    """x_to_v(x) is bs_of's v, and bp(x_to_v(x), ...) lands on X = x."""
    assert close(hw.x_to_v(x), hw.bs_of(x, y, z)[0], 1e-9)
    assert close(hw.bp(hw.x_to_v(x), 0.0, 0.0)[0], x, 1e-9)


@prop(COORD, COORD, COORD, examples=1000)
def un_of_and_hoses_world_to_bs_agree_with_bs_of(x, y, z):
    """frame_v0.un_of(y, z) is bs_of's (u, n), hoses.world_to_bs is bs_of, and bp_yz(un_of(y, z)) gives (y, z) back."""
    v, u, n = hw.bs_of(x, y, z)
    assert close_all(fr.un_of(y, z), (u, n), 1e-9)
    assert close_all(hoses.world_to_bs((x, y, z)), (v, u, n), 1e-9)
    assert close_all(hw.bp_yz(*fr.un_of(y, z)), (y, z), 1e-9)


@prop(POINT3, POINT3, examples=1000)
def bp_is_a_rigid_motion(p, q):
    """bp keeps distances (the u and n axes are orthonormal): |bp(p) - bp(q)| == |p - q|."""
    d0 = math.dist(p, q)
    d1 = math.dist(hw.bp(*p), hw.bp(*q))
    assert close(d0, d1, 1e-9)


# ---------------------------------------------------------------------------
# frame_v0.py: mirror_x
# ---------------------------------------------------------------------------
BOX = st.tuples(fl(-200, 200), fl(-200, 200), fl(-200, 200), fl(0.5, 100), fl(0.5, 100), fl(0.5, 100))
CYL = st.tuples(fl(-200, 200), fl(-200, 200), fl(-200, 200), fl(0.5, 30), fl(1, 100), POINT3.filter(lambda d: math.dist(d, (0, 0, 0)) > 1.0))


def _box(t):
    x, y, z, a, b, c = t
    return cq.Solid.makeBox(a, b, c, cq.Vector(x, y, z))


def _cyl(t):
    x, y, z, r, h, d = t
    return cq.Solid.makeCylinder(r, h, cq.Vector(x, y, z), cq.Vector(*d))


def _bb(s):
    b = s.BoundingBox()
    return (b.xmin, b.xmax, b.ymin, b.ymax, b.zmin, b.zmax)


@prop(BOX, examples=300)
def mirror_x_twice_is_identity_on_a_box(t):
    """mirror_x(mirror_x(box)): same bounding box, volume and centre; once: X negated, Y, Z and the volume kept. Tolerance 1e-6 mm (OCC's box tolerance)."""
    s = _box(t)
    m, mm = fr.mirror_x(s), fr.mirror_x(fr.mirror_x(s))
    assert close_all(_bb(mm), _bb(s), 1e-6)
    assert close(mm.Volume(), s.Volume(), 1e-6 * s.Volume())
    assert close_all(mm.Center().toTuple(), s.Center().toTuple(), 1e-6)
    x0, x1, y0, y1, z0, z1 = _bb(s)
    assert close_all(_bb(m), (-x1, -x0, y0, y1, z0, z1), 1e-6)
    assert close(m.Volume(), s.Volume(), 1e-6 * s.Volume())
    c, cm = s.Center().toTuple(), m.Center().toTuple()
    assert close_all(cm, (-c[0], c[1], c[2]), 1e-6)


@prop(CYL, examples=300)
def mirror_x_twice_is_identity_on_a_slanted_cylinder(t):
    """The same for a cylinder in any direction (curved faces): volume and centre of mass; once, X of the centre negated. Tolerance 1e-6 relative."""
    s = _cyl(t)
    m, mm = fr.mirror_x(s), fr.mirror_x(fr.mirror_x(s))
    assert close(mm.Volume(), s.Volume(), 1e-6 * s.Volume())
    assert close_all(mm.Center().toTuple(), s.Center().toTuple(), 1e-6)
    c, cm = s.Center().toTuple(), m.Center().toTuple()
    assert close_all(cm, (-c[0], c[1], c[2]), 1e-6)
    assert close(m.Volume(), s.Volume(), 1e-6 * s.Volume())


@prop(POINT3, examples=500)
def mirror_x_twice_is_identity_on_a_point(p):
    """A vertex goes to (-x, y, z) and back."""
    v = cq.Vertex.makeVertex(*p)
    once, twice = fr.mirror_x(v).toTuple(), fr.mirror_x(fr.mirror_x(v)).toTuple()
    assert close_all(once, (-p[0], p[1], p[2]), 1e-9)
    assert close_all(twice, p, 1e-9)


HOLE = st.tuples(st.sampled_from(["M3", "M3c", "6-32c", "M3r"]), POINT3, POINT3, fl(0.5, 5), fl(1, 50), st.booleans())


@prop(HOLE, examples=300)
def hole_mirrored_twice_is_identity(t):
    """Hole.mirrored() twice gives the same start, direction and size (the left parts' hole records are the right ones' mirrored)."""
    kind, start, d, r, length, pilot = t
    assume(math.dist(d, (0, 0, 0)) > 0.1)
    h = fr.Hole(kind, start, d, r, length, 1.6, pilot, stack=3.0, item="x")
    hh = h.mirrored().mirrored()
    assert hh.kind == h.kind and hh.stack == h.stack and hh.item == h.item and hh.pilot == h.pilot
    assert close_all(hh.start, h.start, 1e-12) and close_all(hh.d, h.d, 1e-12)
    assert (hh.r, hh.length) == (h.r, h.length)
    m = h.mirrored()
    assert close(m.start[0], -h.start[0], 1e-12) and close(m.d[0], -h.d[0], 1e-12)


# ---------------------------------------------------------------------------
# frame_v0.py: screw_fit (the screw-length rule, docs/plans/fasteners-m3.md, "Length rule")
# ---------------------------------------------------------------------------
STACK = fl(0.0, 45.0)               # longest stock screw is 40 mm: 45 includes stacks no screw can serve
LO = hw.SCREW_ENGAGE_MIN
HI = hw.M3_PILOT_DEPTH - hw.SCREW_BOTTOM_GAP
EPS = fr.FIT_EPS


@prop(STACK, st.booleans(), examples=3000)
def screw_fit_follows_the_length_rule(stack, washer):
    """The screw is one the owner has, enters the insert by >= SCREW_ENGAGE_MIN, stops >= SCREW_BOTTOM_GAP short of the pilot's bottom (or the relief bore gives that gap); it raises only when no screw reaches the minimum."""
    w = hw.M3_WASHER_T if washer else 0.0
    reach = any(L - stack - w >= LO - EPS for L in hw.M3_SCREW_STOCK)
    if not reach:
        try:
            fr.screw_fit(stack, washer)
        except ValueError:
            return
        raise AssertionError("screw_fit returned although no stock screw reaches the minimum entry")
    L, entry, relief = fr.screw_fit(stack, washer)
    assert L in hw.M3_SCREW_STOCK
    assert close(entry, L - stack - w, 1e-9)
    assert entry >= LO - 2 * EPS
    if relief <= EPS:                     # a length in the kit fits: it stops short of the bottom
        assert relief == 0.0
        assert entry <= HI + 2 * EPS
        assert hw.M3_PILOT_DEPTH - entry >= hw.SCREW_BOTTOM_GAP - 2 * EPS
    else:                                 # none fits: the shortest that reaches the minimum, the relief bore makes the bottom gap
        assert entry > HI
        assert close(hw.M3_PILOT_DEPTH + relief - entry, hw.SCREW_BOTTOM_GAP, 1e-9)
        shorter = [x for x in hw.M3_SCREW_STOCK if x < L]
        assert all(x - stack - w < LO - EPS for x in shorter)


@prop(STACK, st.booleans(), examples=3000)
def screw_fit_picks_the_length_furthest_from_both_limits(stack, washer):
    """When several lengths fit, the chosen one has the largest margin min(entry - minimum, deepest - entry) (docstring: "the one furthest from both limits"); when one fits, it is that one."""
    w = hw.M3_WASHER_T if washer else 0.0
    fits = {L: min(L - stack - w - LO, HI - (L - stack - w)) for L in hw.M3_SCREW_STOCK if LO - EPS <= L - stack - w <= HI + EPS}
    assume(fits)
    L, _, relief = fr.screw_fit(stack, washer)
    assert relief == 0.0 and L in fits
    assert fits[L] >= max(fits.values()) - 1e-9, (L, fits)


@prop(STACK, STACK, st.booleans(), examples=3000)
def screw_fit_length_never_decreases_when_the_stack_grows(s1, s2, washer):
    """For two stacks that both have a screw, the longer stack gets a screw at least as long."""
    lo, hi = sorted((s1, s2))
    w = hw.M3_WASHER_T if washer else 0.0
    assume(any(L - hi - w >= LO - EPS for L in hw.M3_SCREW_STOCK))
    assert fr.screw_fit(lo, washer)[0] <= fr.screw_fit(hi, washer)[0]


# ---------------------------------------------------------------------------
# frame_v0.py: poly_props (area, centroid and second moments of a polygon, used by the strength checks)
# ---------------------------------------------------------------------------
@st.composite
def star_polygons(draw):
    """A simple polygon, counter-clockwise: 3..8 vertices at increasing angles round the origin (no gap of 180 degrees, so the origin is inside and the polygon is star-shaped)."""
    n = draw(st.integers(3, 8))
    ang = sorted(draw(st.lists(fl(0, 2 * math.pi), min_size=n, max_size=n, unique=True)))
    gaps = [b - a for a, b in zip(ang, ang[1:])] + [ang[0] + 2 * math.pi - ang[-1]]
    assume(max(gaps) < math.pi - 0.1 and min(gaps) > 0.05)
    rad = draw(st.lists(fl(5, 100), min_size=n, max_size=n))
    return [(r * math.cos(a), r * math.sin(a)) for r, a in zip(rad, ang)]


def moments_by_triangles(pts):
    """Independent calculation: the fan of triangles from the origin (valid for a star-shaped polygon), second moments by the edge-midpoint rule (exact for degree 2)."""
    A = sx = sy = ixx = iyy = ixy = 0.0
    for p, q in zip(pts, pts[1:] + pts[:1]):
        a = 0.5 * (p[0] * q[1] - q[0] * p[1])
        mids = [((p[0] + q[0]) / 2, (p[1] + q[1]) / 2), (p[0] / 2, p[1] / 2), (q[0] / 2, q[1] / 2)]
        A += a
        sx += a * (p[0] + q[0]) / 3
        sy += a * (p[1] + q[1]) / 3
        iyy += a / 3 * sum(m[0] ** 2 for m in mids)
        ixx += a / 3 * sum(m[1] ** 2 for m in mids)
        ixy += a / 3 * sum(m[0] * m[1] for m in mids)
    cx, cy = sx / A, sy / A
    return A, (cx, cy), iyy - A * cx * cx, ixx - A * cy * cy, ixy - A * cx * cy


def props_close(a, b, scale):
    """(area, (cu, cn), Inn, Iuu, Iun) agree to 1e-9 of the polygon's scale (A for the area, L for the centroid, A L^2 for the moments)."""
    A, L = scale
    assert close(a[0], b[0], 1e-9 * A), (a[0], b[0])
    assert close_all(a[1], b[1], 1e-9 * L), (a[1], b[1])
    assert all(close(x, y, 1e-9 * A * L * L) for x, y in zip(a[2:], b[2:])), (a[2:], b[2:])


def poly_scale(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    L = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    return L * L, L


@prop(star_polygons(), examples=1000)
def poly_props_matches_an_independent_calculation_and_is_positive(pts):
    """Area > 0, and area, centroid and the three second moments equal the fan-of-triangles calculation."""
    got = fr.poly_props(pts)
    assert got[0] > 0
    props_close(got, moments_by_triangles(pts), poly_scale(pts))
    assert got[2] >= 0 and got[3] >= 0
    assert got[2] * got[3] - got[4] ** 2 >= -1e-9 * got[2] * got[3]        # the inertia tensor is positive semi-definite


@prop(star_polygons(), examples=1000)
def poly_props_does_not_depend_on_the_winding(pts):
    """Reversing the vertex order gives the same area, centroid and moments, and so does starting the list at another vertex."""
    sc = poly_scale(pts)
    base = fr.poly_props(pts)
    props_close(fr.poly_props(pts[::-1]), base, sc)
    props_close(fr.poly_props(pts[1:] + pts[:1]), base, sc)


@prop(star_polygons(), fl(-400, 400), fl(-400, 400), examples=1000)
def poly_props_translation_moves_the_centroid_only(pts, dx, dy):
    """Translating by (dx, dy): same area, centroid + (dx, dy), same moments about the centroid. The model's polygons are 10..300 mm across at up to 400 mm from the origin."""
    base = fr.poly_props(pts)
    moved = fr.poly_props([(x + dx, y + dy) for x, y in pts])
    A, L = poly_scale(pts)
    far = max(abs(dx), abs(dy), L)
    assert close(moved[0], base[0], 1e-9 * A)
    assert close_all(moved[1], (base[1][0] + dx, base[1][1] + dy), 1e-9 * far)
    # the moments are computed about the origin and shifted back, so their rounding grows with the distance: 1e-9 of A (L + far)^2
    assert all(close(x, y, 1e-9 * A * (L + far) ** 2) for x, y in zip(moved[2:], base[2:]))


@prop(fl(1, 300), fl(1, 300), fl(-400, 400), fl(-400, 400), st.booleans(), examples=1000)
def poly_props_rectangle_matches_the_textbook(w, h, x0, y0, clockwise):
    """A w x h rectangle (u along w): area w h, centroid at its middle, Inn = h w^3 / 12, Iuu = w h^3 / 12, Iun = 0, either winding."""
    pts = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]
    if clockwise:
        pts = pts[::-1]
    area, (cu, cn), inn, iuu, iun = fr.poly_props(pts)
    far = max(abs(x0), abs(y0), w, h)
    assert close(area, w * h, 1e-9 * w * h)
    assert close_all((cu, cn), (x0 + w / 2, y0 + h / 2), 1e-9 * far)
    tol = 1e-9 * w * h * (w + h + far) ** 2
    assert close(inn, h * w ** 3 / 12, tol)
    assert close(iuu, w * h ** 3 / 12, tol)
    assert close(iun, 0.0, tol)


# ---------------------------------------------------------------------------
# frame_v0.py: _seg_dist (distance from a point to a segment)
# ---------------------------------------------------------------------------
P2 = st.tuples(fl(-300, 300), fl(-300, 300))


@prop(P2, P2, fl(0, 1), examples=2000)
def seg_dist_is_zero_on_the_segment(a, b, t):
    """A point a + t (b - a) with t in [0, 1] is at distance 0 (tolerance 1e-9 mm: the point itself is rounded)."""
    p = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    assert close(fr._seg_dist(p, a, b), 0.0, 1e-9)


@prop(P2, P2, P2, examples=2000)
def seg_dist_is_symmetric_never_negative_and_no_more_than_an_end(p, a, b):
    """_seg_dist(p, a, b) == _seg_dist(p, b, a) (1e-9 mm), >= 0, and <= the distance to either end."""
    d = fr._seg_dist(p, a, b)
    assert d >= 0
    assert close(d, fr._seg_dist(p, b, a), 1e-9)
    assert d <= min(math.dist(p, a), math.dist(p, b)) + 1e-9


@prop(P2, fl(0, 2 * math.pi), fl(0.5, 300), fl(-2, 3), fl(-100, 100), examples=2000)
def seg_dist_matches_the_textbook_beside_and_beyond_the_ends(a, ang, length, t, h):
    """Construct p from the segment's own frame: t along it (in lengths from a), h across it. Beside the segment (0 <= t <= 1) the distance is |h|; beyond an end it is the distance to that end, not to the line. Tolerance 1e-9 relative to the scale."""
    ux, uy = math.cos(ang), math.sin(ang)
    b = (a[0] + length * ux, a[1] + length * uy)
    p = (a[0] + t * length * ux - h * uy, a[1] + t * length * uy + h * ux)
    want = abs(h) if 0 <= t <= 1 else math.hypot(h, (t if t < 0 else t - 1) * length)
    assert close(fr._seg_dist(p, a, b), want, 1e-9 * (length + abs(h) + 300))


@prop(P2, P2, examples=500)
def seg_dist_of_a_point_segment_is_the_distance_to_the_point(p, a):
    """A segment whose ends coincide: the distance to that point."""
    assert close(fr._seg_dist(p, a, a), math.dist(p, a), 1e-9)


# ---------------------------------------------------------------------------
# zone_access.py: densify (a polyline with no gap above `step`)
# ---------------------------------------------------------------------------
POLYLINE = st.lists(POINT3, min_size=1, max_size=6).map(lambda l: np.array(l, dtype=float))


def poly_len(p):
    return float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())


@prop(POLYLINE, fl(0.25, 10.0), examples=500)
def densify_keeps_the_points_the_length_and_leaves_no_gap(p, step):
    """Every input point is still in the output (1e-9 mm), the first and last are the same, neighbours are <= step apart (+1e-9), and the polyline's length is unchanged (1e-9 relative): the added points lie on it."""
    out = za.densify(p, step)
    assert out.shape[1] == 3
    for q in p:
        assert np.min(np.linalg.norm(out - q, axis=1)) <= 1e-9
    assert np.allclose(out[0], p[0], atol=1e-9) and np.allclose(out[-1], p[-1], atol=1e-9)
    if len(out) > 1:
        assert np.linalg.norm(np.diff(out, axis=0), axis=1).max() <= step + 1e-9
    assert close(poly_len(out), poly_len(p), 1e-9 * max(poly_len(p), 1.0))


# ---------------------------------------------------------------------------
# hoses.py: fillet_path (straight runs joined by arcs)
# ---------------------------------------------------------------------------
@st.composite
def hose_polylines(draw):
    """3..6 waypoints and one radius per interior waypoint. Legs >= 5 mm, the model's hoses have radii 20..60 on legs of 30..300 mm."""
    m = draw(st.integers(3, 6))
    pts = [np.array(draw(POINT3), dtype=float) for _ in range(m)]
    for a, b in zip(pts, pts[1:]):
        assume(np.linalg.norm(b - a) >= 5.0)
    radii = draw(st.lists(fl(1.0, 40.0), min_size=m - 2, max_size=m - 2))
    return pts, radii


def corners(pts, radii):
    """(legs, theta, tangent lengths) with the radii as asked: what the function would need if no run had to give way."""
    seg = [b - a for a, b in zip(pts, pts[1:])]
    ln = [float(np.linalg.norm(d)) for d in seg]
    unit = [d / l for d, l in zip(seg, ln)]
    theta = [math.acos(float(np.clip(unit[i - 1] @ unit[i], -1, 1))) for i in range(1, len(pts) - 1)]
    tan = [r * math.tan(t / 2) for r, t in zip(radii, theta)]
    return ln, theta, tan


@prop(hose_polylines(), examples=1500)
def fillet_path_is_no_longer_than_its_legs_and_joins_its_ends(case):
    """Whatever the radii: length <= the sum of the straight legs (+1e-9 relative), length > 0, the samples start at the first waypoint and end at the last, tangents are the first and last legs' unit vectors."""
    pts, radii = case
    out, length, rmin, (t0, t1) = hoses.fillet_path(pts, radii)
    legs = sum(float(np.linalg.norm(b - a)) for a, b in zip(pts, pts[1:]))
    assert 0 < length <= legs * (1 + 1e-9), (length, legs)
    assert np.allclose(out[0], pts[0], atol=1e-9) and np.allclose(out[-1], pts[-1], atol=1e-6)
    assert np.allclose(t0, (pts[1] - pts[0]) / np.linalg.norm(pts[1] - pts[0]), atol=1e-12)
    assert np.allclose(t1, (pts[-1] - pts[-2]) / np.linalg.norm(pts[-1] - pts[-2]), atol=1e-12)


@prop(hose_polylines(), examples=1500)
def fillet_path_reports_the_asked_radius_when_every_run_has_room(case):
    """When every run is long enough for the two arcs on it (tangent lengths summed <= the leg), no radius is reduced: the smallest radius reported is the smallest asked (corners that bend by < 1e-3 rad are skipped), and so at least the one asked for."""
    pts, radii = case
    ln, theta, tan = corners(pts, radii)
    bends = [t for t in theta if t >= 1e-3]
    tans = [0.0] + tan + [0.0]
    assume(all(tans[i] + tans[i + 1] <= ln[i] * (1 - 1e-9) for i in range(len(ln))))
    rmin = hoses.fillet_path(pts, radii)[2]
    asked = [r for r, t in zip(radii, theta) if t >= 1e-3]
    if not bends:
        assert rmin == float("inf")
    else:
        assert close(rmin, min(asked), 1e-9 * max(asked)), (rmin, min(asked))


@prop(hose_polylines(), examples=1500)
def fillet_path_never_reports_more_than_was_asked_and_stays_positive(case):
    """On any input the radius reported is > 0 and <= the smallest radius asked at a bending corner (a run too short for two arcs reduces both: the docstring), or inf with no bend."""
    pts, radii = case
    _, theta, _ = corners(pts, radii)
    asked = [r for r, t in zip(radii, theta) if t >= 1e-3]
    rmin = hoses.fillet_path(pts, radii)[2]
    if not asked:
        assert rmin == float("inf")
    else:
        assert 0 < rmin <= min(asked) * (1 + 1e-9)


@prop(hose_polylines(), examples=1500,
      xfail="a waypoint list that doubles back on itself (a turn of exactly 180 degrees, e.g. (0,0,0), (5,0,0), (0,0,0)) gives NaN samples and a length of ~1e-15: hoses.py:76 divides the zero vector m1 by its norm; the arc's radius collapses to ~3e-16")
def fillet_path_samples_are_finite(case):
    """Every sampled point, the length and the radius are finite numbers, whatever the polyline (the hose keep-outs are built from these samples)."""
    pts, radii = case
    out, length, rmin, _ = hoses.fillet_path(pts, radii)
    assert np.isfinite(out).all(), "NaN or inf in the sampled path"
    assert math.isfinite(length)


@prop(hose_polylines(), examples=1500)
def fillet_path_is_no_shorter_than_the_chord(case):
    """A path from the first to the last waypoint is at least as long as the straight line between them (+1e-9 relative)."""
    pts, radii = case
    with np.errstate(all="ignore"):
        _, length, _, _ = hoses.fillet_path(pts, radii)
    chord = float(np.linalg.norm(pts[-1] - pts[0]))
    assert length >= chord * (1 - 1e-9) - 1e-9, (length, chord)


# ---------------------------------------------------------------------------
def run():
    np.seterr(all="ignore")       # a property that finds a NaN says so itself; numpy's warnings would only bury it
    n_fail = n_xfail = n_ex = 0
    t0 = time.time()
    width = max(len(t["name"]) for t in TESTS)
    for t in TESTS:
        t1 = time.time()
        err = None
        try:
            t["test"]()
        except BaseException as e:                       # noqa: BLE001 (a failing property raises whatever it found)
            if isinstance(e, KeyboardInterrupt):
                raise
            err = e
        n = t["calls"][0]
        dt = time.time() - t1
        if err is None and t["xfail"] is None:
            status = "ok"
        elif err is None:
            status = "XPASS"
            n_fail += 1
        elif t["xfail"] is not None:
            status = "xfail"
            n_xfail += 1
        else:
            status = "FAIL"
            n_fail += 1
        if status != "FAIL" and status != "XPASS":
            n_ex += n
        print(f"  {status:<5} {t['name']:<{width}} {n:>5} examples {dt:5.1f} s")
        if status == "xfail":
            print(f"        known failure: {t['xfail']}")
            print("        " + "\n        ".join(f"{type(err).__name__}: {err}".splitlines()[:1] + [x for x in getattr(err, '__notes__', [])][:3]))
        elif status == "FAIL":
            print("        " + "\n        ".join(traceback.format_exception_only(type(err), err)[0].rstrip().splitlines()))
            for note in getattr(err, "__notes__", []):
                print("        " + note.replace("\n", "\n        "))
            tb = traceback.extract_tb(err.__traceback__)
            for fs in tb[-3:]:
                print(f"        at {os.path.basename(fs.filename)}:{fs.lineno} {fs.line}")
        elif status == "XPASS":
            print(f"        marked xfail ({t['xfail']}) but it passes: remove the mark")
    total = time.time() - t0
    ok = n_fail == 0
    print(f"\n{len(TESTS)} properties, {n_ex} examples, {n_xfail} known failure(s), {n_fail} failure(s), {total:.1f} s: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
