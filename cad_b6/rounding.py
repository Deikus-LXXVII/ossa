#!/usr/bin/env python3
"""Corner rounding for the B6 skeleton (revision 8).

Plates are unions of 2D primitives extruded along one axis. Their corners are rounded in 2D, on the outline face,
before the face is extruded: the kernel's planar fillet (BRepFilletAPI_MakeFillet2d) is exact and fast, while a
3D fillet on the finished solid, with its lap cuts and holes, is not.

The module knows nothing about the case: frame_v0.py gives it the neighbours (hardware and the other parts), the
hole rings that must keep their wall, and the corners that must stay sharp. For every corner it tries the wanted
radius first and goes down in steps to a minimum; a candidate is accepted only if

  convex  (material removed): the removed sliver does not enter a hole's wall ring, and the contact areas it takes
          away stay within the revision 8a floor: every contact keeps CONTACT_FLOOR (97 %) of its unrounded area
          (a part that shares the contact with another rounded part takes half of the allowance) and at least
          SCREW_FLAT (4 mm) of flat contact around every screw hole that crosses it;
  concave (material added):   the added sliver does not overlap any neighbour, stays 5 mm from the hoses and
          2 mm from the hardware.

A corner for which no radius is accepted stays sharp and is logged with the reason. Nothing here weakens a
check: the same constraints are measured again on the finished solids by run_checks in frame_v0.py.
"""
from __future__ import annotations

import math
import weakref
from dataclasses import dataclass

import numpy as np
import cadquery as cq
from cadquery import Compound, Face, Solid, Vector
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet2d
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Line, GeomAbs_Plane
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

TURN_MIN = 1.0           # deg: a smaller change of direction is a tangent junction, not a corner
SHARP_DEG = 30.0         # check 12: dihedral (outline turn) above this is a sharp corner
AREA_EPS = 1e-4          # mm^2: contact patches smaller than this are noise (the face booleans are good to ~1e-6)
CONTACT_FLOOR = 0.97     # revision 8a: a rounded contact keeps at least this share of its unrounded area ...
SCREW_FLAT = 4.0         # ... and at least this much flat contact (mm, from the hole's edge) around every screw that crosses it
VOL_EPS = 0.01           # mm^3 of overlap a rounding may add
PLANE_TOL = 1e-3         # mm
HOSE_GAP = 5.0           # mm, a frame part keeps this from the hose keep-outs (check 9)
HW_GAP = 2.0             # mm, an added sliver keeps this from the hardware (the verify skill calls less than 2 mm a finding)


# ---------------------------------------------------------------------------
# small geometry helpers
# ---------------------------------------------------------------------------
_BBOX = weakref.WeakKeyDictionary()      # Shape -> bbox; BoundingBox() is the optimal one and costs ~25 ms on a drilled part


def bbox_of(shape):
    hit = _BBOX.get(shape)
    if hit is None:
        box = Bnd_Box()
        BRepBndLib.Add_s(shape.wrapped, box, False)       # the quick box (control points), not the optimal one: only a prefilter here, so a little loose is safe
        xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
        hit = (xmin, xmax, ymin, ymax, zmin, zmax)
        try:
            _BBOX[shape] = hit
        except TypeError:
            pass
    return hit


def bbox_gap(a, b):
    gx = max(a[0] - b[1], b[0] - a[1], 0.0)
    gy = max(a[2] - b[3], b[2] - a[3], 0.0)
    gz = max(a[4] - b[5], b[4] - a[5], 0.0)
    return math.sqrt(gx * gx + gy * gy + gz * gz)


def _vec(v):
    return np.array(v.toTuple() if hasattr(v, "toTuple") else v, float)


def _plane_of(face):
    """(unit outward normal, plane offset d with n.x = d, centre) of a planar face."""
    n = _vec(face.normalAt())
    c = _vec(face.Center())
    return n, float(n @ c), c


# ---------------------------------------------------------------------------
# neighbours: shapes a rounded part must not collide with or lose contact with
# ---------------------------------------------------------------------------
@dataclass
class Neighbor:
    name: str
    shape: object
    role: str                       # "hw", "keepout", "hose", "part"
    bbox: tuple = None
    _planes: list = None

    def __post_init__(self):
        self.bbox = bbox_of(self.shape)

    def planes(self):
        if self._planes is None:
            out = []
            for f in self.shape.Faces():
                if f.geomType() == "PLANE":
                    n, d, _ = _plane_of(f)
                    out.append((n, d, f, bbox_of(f)))
            self._planes = out
        return self._planes


class Neighbors:
    def __init__(self, items: list[Neighbor]):
        self.items = list(items)

    def near(self, bb, gap):
        return [n for n in self.items if bbox_gap(bb, n.bbox) <= gap]

    def contact_faces(self, nb: Neighbor, faces) -> list:
        """The faces where a planar face of `faces` lies in the same plane as a face of `nb`, facing it, and overlaps it."""
        out = []
        planes = nb.planes()
        for fs in faces:
            if fs.geomType() != "PLANE":
                continue
            ns, ds, _ = _plane_of(fs)
            fb = None
            for (n, d, fn, nbb) in planes:
                if float(n @ ns) > -0.9999 or abs(ds + d) > PLANE_TOL:
                    continue
                fb = fb or bbox_of(fs)               # the face's box only once a neighbour has a face in the same plane (it costs ~2 ms)
                if bbox_gap(fb, nbb) > PLANE_TOL:
                    continue
                r = fs.intersect(fn)
                if r is None or r.isNull():
                    continue
                out += list(r.Faces())
        return out

    def contact_area(self, nb: Neighbor, faces) -> float:
        """Area where a planar face of `faces` lies in the same plane as a face of `nb`, facing it, and overlaps it."""
        return sum(x.Area() for x in self.contact_faces(nb, faces))

    def patches(self, shape_faces, bb, exclude=()):
        """The areas (faces) where `shape_faces` lie flat against a neighbour: [(neighbour name, overlap face)]."""
        out = []
        for nb in self.near(bb, PLANE_TOL):
            if nb.name in exclude or nb.role in ("keepout", "hose"):
                continue
            for fs in shape_faces:
                if fs.geomType() != "PLANE":
                    continue
                ns, ds, _ = _plane_of(fs)
                fb = None
                for (n, d, fn, nbb) in nb.planes():
                    if float(n @ ns) > -0.9999 or abs(ds + d) > PLANE_TOL:
                        continue
                    fb = fb or bbox_of(fs)
                    if bbox_gap(fb, nbb) > PLANE_TOL:
                        continue
                    r = fs.intersect(fn)
                    if r is None or r.isNull():
                        continue
                    out += [(nb.name, x) for x in r.Faces() if x.Area() > AREA_EPS]
        return out

    def touching(self, shape_faces, bb, exclude=()) -> list[tuple[str, float]]:
        """[(neighbour name, contact area mm2)] of the neighbours that `shape_faces` touches over an area."""
        out = []
        for nb in self.near(bb, PLANE_TOL):
            if nb.name in exclude or nb.role in ("keepout", "hose"):
                continue
            a = self.contact_area(nb, shape_faces)
            if a > AREA_EPS:
                out.append((nb.name, a))
        return out


# ---------------------------------------------------------------------------
# outline corners of a planar face
# ---------------------------------------------------------------------------
@dataclass
class Corner:
    pt: np.ndarray
    turn: float          # deg, unsigned change of direction
    convex: bool


def _oriented_edges(wire):
    edges = list(wire.Edges())
    ends = [(_vec(e.positionAt(0)), _vec(e.positionAt(1))) for e in edges]
    used = [False] * len(edges)
    order = [(0, False)]
    used[0] = True
    cur = ends[0][1]
    while len(order) < len(edges):
        for i in range(len(edges)):
            if used[i]:
                continue
            if np.linalg.norm(ends[i][0] - cur) < 1e-4:
                order.append((i, False))
                cur = ends[i][1]
            elif np.linalg.norm(ends[i][1] - cur) < 1e-4:
                order.append((i, True))
                cur = ends[i][0]
            else:
                continue
            used[i] = True
            break
        else:
            raise ValueError("outline wire is not a single closed chain")
    return edges, order


def corners(face) -> list[Corner]:
    """Every vertex of the outer wire with its turn and whether the material is on the inside of the turn."""
    edges, order = _oriented_edges(face.outerWire())
    n = _vec(face.normalAt())
    poly = []
    for i, rev in order:
        ts = np.linspace(0, 1, 9)
        pts = [_vec(edges[i].positionAt(t)) for t in (ts[::-1] if rev else ts)]
        poly += pts[:-1]
    poly = np.array(poly)
    newell = np.zeros(3)
    for k in range(len(poly)):
        newell += np.cross(poly[k], poly[(k + 1) % len(poly)])
    ccw = float(newell @ n) > 0.0

    def tan(i, rev, at_end):
        e = edges[i]
        if not rev:
            return _vec(e.tangentAt(1.0 if at_end else 0.0))
        return -_vec(e.tangentAt(0.0 if at_end else 1.0))

    out = []
    for k, (i, rev) in enumerate(order):
        j, rev2 = order[(k + 1) % len(order)]
        a = tan(i, rev, True)
        b = tan(j, rev2, False)
        a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
        cr = float(np.cross(a, b) @ n)
        ang = math.degrees(math.atan2(abs(cr), float(a @ b)))
        pt = _vec(edges[i].positionAt(0.0 if rev else 1.0))
        out.append(Corner(pt, ang, (cr > 0) == ccw))
    return out


def fillet_corner(face, pt, r):
    """The face with the vertex at `pt` rounded by radius r, or None when the kernel cannot fit it."""
    vs = face.Vertices()
    v = min(vs, key=lambda x: np.linalg.norm(_vec(x.toTuple()) - pt))
    if np.linalg.norm(_vec(v.toTuple()) - pt) > 1e-3:
        return None
    mk = BRepFilletAPI_MakeFillet2d(face.wrapped)
    mk.AddFillet(v.wrapped, r)
    mk.Build()
    if not mk.IsDone():
        return None
    try:
        new = Face(mk.Shape())
    except Exception:       # noqa: BLE001 - the kernel gave a non-face: treat as "does not fit"
        return None
    return new if new.isValid() else None


# ---------------------------------------------------------------------------
# the guard: what a candidate rounding is not allowed to do
# ---------------------------------------------------------------------------
class Guard:
    """Judges one candidate fillet by the sliver of material it removes (convex) or adds (concave), extruded through
    the layer's thickness `tvec` and trimmed by `post_cuts` (cuts applied to the layer afterwards, e.g. the lap
    zones, so only material that really exists counts).

    Revision 8a: a convex sliver may take contact area. For every neighbour it touches, the part may lose at most
    (1 - CONTACT_FLOOR) * share of the unrounded contact area `selfshape` has with that neighbour, summed over every
    corner of the part (`ledger`, shared by all the Guards of one build: {(part, neighbour): area lost so far}); `share`
    is 1 against hardware and 1/2 against another rounded plate, which spends its own half. A sliver that takes
    contact within SCREW_FLAT of the edge of a screw hole (`screws`: [(point on the axis, unit axis, hole radius)] whose
    axis is square to the contact plane) is refused."""

    def __init__(self, nb: Neighbors, tvec, rings=(), post_cuts=(), exclude=(), selfshape=None,
                 screws=(), ledger=None, own="", share=None, a0=None):
        self.nb = nb
        self.selfshape = selfshape          # the part as it is before rounding: added material may be as close to a neighbour as the part already is; its contacts are the 100 %
        self._dref: dict = {}
        self.tvec = Vector(*tvec) if not isinstance(tvec, Vector) else tvec
        self.rings = [(r, bbox_of(r)) for r in rings]
        self.post_cuts = list(post_cuts)
        self.exclude = set(exclude)
        self.screws = [(np.array(p, float), np.array(a, float) / np.linalg.norm(a), float(r)) for p, a, r in screws]
        self.ledger = ledger if ledger is not None else {}
        self.own = own
        self.share = share or (lambda name: 1.0)
        self._a0 = a0 if a0 is not None else {}     # (part, neighbour) -> unrounded contact area; the owner may share it between guards
        self._by_name = {n.name: n for n in nb.items}
        self._pending: dict = {}
        self.last_loss: dict = {}
        self.reserve: dict = {}        # neighbour -> mm2 kept back for the corners still to come in this outline (see round_face)

    def d_ref(self, nb):
        if self.selfshape is None:
            return float("inf")
        if nb.name not in self._dref:
            self._dref[nb.name] = float(self.selfshape.distance(nb.shape))
        return self._dref[nb.name]

    def contact0(self, name) -> float:
        """Area the unrounded part has in contact with neighbour `name`."""
        key = (self.own, name)
        if key not in self._a0:
            nb = self._by_name[name]
            self._a0[key] = self.nb.contact_area(nb, self.selfshape.Faces()) if self.selfshape is not None else 0.0
        return self._a0[key]

    def sliver(self, kind, before, after):
        a, b = (before, after) if kind == "convex" else (after, before)
        d = a.cut(b)
        solids = []
        for fc in d.Faces():
            if fc.Area() < 1e-6:
                continue
            solids.append(Solid.extrudeLinear(fc.outerWire(), fc.innerWires(), self.tvec))
        if solids and self.post_cuts:
            cut = []
            for s in solids:
                cut += s.cut(*self.post_cuts).Solids()
            solids = [s for s in cut if s.Volume() > 1e-6]
        return solids

    def __call__(self, kind, r, before, after, pt):
        sl = self.sliver(kind, before, after)
        if not sl:
            self._pending[id(after)] = {}
            return True, ""
        ok, why = self.judge(kind, Compound.makeCompound(sl))
        self._pending[id(after)] = dict(self.last_loss) if ok else {}
        return ok, why

    def commit(self, after):
        """The candidate `after` was chosen: its contact losses now count against the part's allowance."""
        for name, a in self._pending.pop(id(after), {}).items():
            key = (self.own, name)
            self.ledger[key] = self.ledger.get(key, 0.0) + a

    def screw_flat(self, face) -> str:
        """Why the removal of contact patch `face` is refused because of a screw, or ''."""
        if not self.screws:
            return ""
        n, d, _ = _plane_of(face)
        fb = bbox_of(face)
        for (p, ax, r) in self.screws:
            dn = float(n @ ax)
            if abs(dn) < 0.999:
                continue
            q = p + ((d - float(n @ p)) / dn) * ax
            reach = r + SCREW_FLAT
            if bbox_gap(fb, (q[0], q[0], q[1], q[1], q[2], q[2])) > reach:
                continue
            if face.distance(cq.Vertex.makeVertex(*q)) < reach - 1e-6:
                return f"it would leave less than {SCREW_FLAT:g} mm of flat contact around the screw at ({q[0]:.1f}, {q[1]:.1f}, {q[2]:.1f})"
        return ""

    def judge_contacts(self, comp, bb, budget=True):
        """Accept or refuse the contact area that the removed sliver `comp` takes (revision 8a). budget=False skips the allowance (the
        dry run of round_face, which asks what a corner would take at the smallest radius)."""
        patches = self.nb.patches(comp.Faces(), bb, self.exclude)
        self.last_loss = {}
        for name, face in patches:
            self.last_loss[name] = self.last_loss.get(name, 0.0) + face.Area()
        for name, a in self.last_loss.items() if budget else ():
            a0 = self.contact0(name)
            left = (1.0 - CONTACT_FLOOR) * self.share(name) * a0 - self.ledger.get((self.own, name), 0.0) - self.reserve.get(name, 0.0)
            if a > left + 1e-9:
                return False, (f"it would take {a:.1f} mm2 from the {a0:.0f} mm2 contact with {name}: "
                               f"{max(left, 0.0):.1f} mm2 of the {100 * (1 - CONTACT_FLOOR) * self.share(name):.1f} % allowance is left "
                               f"after what the corners still to come need at the smallest radius")
        for name, face in patches:
            why = self.screw_flat(face)
            if why:
                return False, why
        return True, ""

    def dry_loss(self, before, after) -> dict:
        """{neighbour: mm2 of contact} that a convex rounding before -> after takes, or {} when it is refused for a reason other than the
        allowance (a hole's wall, a screw): such a corner will stay sharp at every radius and keeps nothing in reserve."""
        sl = self.sliver("convex", before, after)
        if not sl:
            return {}
        comp = Compound.makeCompound(sl)
        ok, _ = self.judge("convex", comp, budget=False)
        return dict(self.last_loss) if ok else {}

    def judge(self, kind, comp, budget=True):
        """Accept or refuse `comp`, the material a rounding removes (kind 'convex') or adds (kind 'concave')."""
        bb = bbox_of(comp)
        if kind == "convex":
            for ring, rb in self.rings:
                if bbox_gap(bb, rb) <= 0.0 and comp.intersect(ring).Volume() > VOL_EPS:
                    return False, "it would cut into a hole's wall"
            return self.judge_contacts(comp, bb, budget)
        self.last_loss = {}
        for ring, rb in self.rings:           # added material must not close in on a hole either (a screw head sits there)
            if bbox_gap(bb, rb) <= 0.0 and comp.intersect(ring).Volume() > VOL_EPS:
                return False, "the added material would close in on a hole"
        for nb in self.nb.near(bb, HOSE_GAP):
            if nb.name in self.exclude:
                continue
            if bbox_gap(bb, nb.bbox) <= 0.0:
                v = comp.intersect(nb.shape).Volume()
                if v > VOL_EPS:
                    return False, f"the added material would overlap {nb.name} ({v:.1f} mm3)"
            need = HOSE_GAP if nb.role == "hose" else HW_GAP if nb.role == "hw" else 0.0
            if need:
                need = min(need, self.d_ref(nb))
            if need > 1e-6 and comp.distance(nb.shape) < need - 1e-6:
                return False, f"the added material would come within {need:g} mm of {nb.name}"
        return True, ""


# ---------------------------------------------------------------------------
# rounding a face
# ---------------------------------------------------------------------------
@dataclass
class Entry:
    part: str
    pt: tuple
    kind: str            # "convex" / "concave"
    turn: float
    radius: float        # 0 = left sharp
    reason: str          # why it stayed sharp (or smaller than wanted)


def largest_passing(n, trial):
    """Index of the first k in 0..n-1 for which trial(k)[0] is not None, where k = 0 is the largest radius and passing is
    monotone (a smaller radius removes or adds a subset of what a larger one does): bisection, so a failing corner costs two
    trials, not n. None when even the smallest fails."""
    if trial(0)[0] is not None:
        return 0
    lo, hi = n - 1, 0
    if lo == hi or trial(lo)[0] is None:
        return None
    while lo - hi > 1:
        mid = (lo + hi) // 2
        if trial(mid)[0] is not None:
            lo = mid
        else:
            hi = mid
    return lo


def _add(log, entry):
    if log is not None:
        log.append(entry)


def round_face(face, *, part, convex_r=6.0, concave_r=8.0, r_min=2.0, step=0.5, guard=None, keep=(), log=None):
    """Round every corner of the face's outline. `keep` is a list of (point, reason): a corner within 0.3 mm of the point stays sharp.
    Returns the new face; `log` (a list) gets one Entry per corner."""
    cur = face
    todo = [c for c in corners(cur) if c.turn > TURN_MIN]
    todo.sort(key=lambda c: (c.convex, tuple(np.round(c.pt, 3))))      # concave first: the corners that carry load
    # Revision 8a: the contact allowance is shared out. Before the first convex corner, ask what each convex corner would take at the
    # smallest radius; while a corner is judged, the corners after it keep that much back, so the first corner cannot use the whole
    # allowance at 6 mm and leave the others sharp: every corner that can be rounded at 2 mm is, and the radius grows where there is room.
    mins = {}
    if guard is not None and hasattr(guard, "dry_loss"):
        for c in todo:
            if c.convex:
                new = fillet_corner(face, c.pt, r_min)
                mins[tuple(np.round(c.pt, 3))] = guard.dry_loss(face, new) if new is not None else {}
    later = {}
    for c in todo:
        for name, a in mins.get(tuple(np.round(c.pt, 3)), {}).items():
            later[name] = later.get(name, 0.0) + a
    for c in todo:
        key = tuple(np.round(c.pt, 3))
        for name, a in mins.get(key, {}).items():       # this corner is no longer "to come"
            later[name] -= a
        if guard is not None and hasattr(guard, "reserve"):
            guard.reserve = {k: v for k, v in later.items() if v > 1e-9} if c.convex else {}
        now = next((k for k in corners(cur) if np.linalg.norm(k.pt - c.pt) < 1e-3 and k.turn > TURN_MIN), None)
        kind = "convex" if c.convex else "concave"
        pt3 = tuple(round(float(x), 2) for x in c.pt)
        if now is None:
            _add(log, Entry(part, pt3, kind, c.turn, 0.0, "the corner was consumed by a neighbouring fillet"))
            continue
        held = next((why for (p, why) in keep if np.linalg.norm(np.array(p, float) - c.pt) < 0.3), None)
        if held:
            _add(log, Entry(part, pt3, kind, c.turn, 0.0, held))
            continue
        want = convex_r if c.convex else concave_r
        radii = []
        r = want
        while r >= r_min - 1e-9:
            radii.append(round(r, 6))
            r -= step
        memo: dict = {}

        def trial(k):
            """(new face or None, reason) for radius radii[k]. A smaller radius removes or adds a subset of what a larger one
            does, so passing is monotone in k and the largest passing radius can be found by bisection."""
            if k not in memo:
                new = fillet_corner(cur, c.pt, radii[k])
                if new is None:
                    memo[k] = (None, f"no radius of {r_min:g}..{want:g} mm fits between the neighbouring edges")
                elif (new.Area() - cur.Area() < 0) != c.convex or abs(new.Area() - cur.Area()) < 1e-9:
                    memo[k] = (None, "the kernel returned an outline of the wrong sense")
                else:
                    ok, why = guard(kind, radii[k], cur, new, c.pt) if guard else (True, "")
                    memo[k] = (new if ok else None, why)
            return memo[k]

        best = largest_passing(len(radii), trial)
        if best is None:        # left sharp: the reason is the one at the smallest radius, the last chance
            _add(log, Entry(part, pt3, kind, c.turn, 0.0, trial(len(radii) - 1)[1]))
        else:
            cur = trial(best)[0]
            if guard is not None and hasattr(guard, "commit"):
                guard.commit(cur)               # the contact area this corner takes now counts against the part's allowance
            why = "" if best == 0 else (trial(best - 1)[1] or "largest radius that fits")
            _add(log, Entry(part, pt3, kind, c.turn, radii[best], why))
    return cur


def extrude_face(face, vec) -> Solid:
    return Solid.extrudeLinear(face.outerWire(), face.innerWires(), vec if isinstance(vec, Vector) else Vector(*vec))


# ---------------------------------------------------------------------------
# check 12: sharp outline corners that remain on a finished solid
# ---------------------------------------------------------------------------
def _fast_normal(face, pt):
    """Outward unit normal of a face at a point on it. For a planar face cq's normalAt() without a point is enough (and cheap); with a point it
    projects the point onto the surface first, ~10 ms."""
    if BRepAdaptor_Surface(face.wrapped).GetType() == GeomAbs_Plane:
        return _vec(face.normalAt())
    return _vec(face.normalAt(pt))


def sharp_axial_edges(solid, axes, min_deg=SHARP_DEG, min_len=2.0, accept=None, caps=True):
    """Straight edges parallel to one of `axes` (the plate's extrusion directions) whose two faces meet at more than min_deg:
    the corners of a plate's outline that are still sharp. Returns dicts (edge, mid, angle, faces, length, caps): `caps` are the
    planar faces square to the edge at its two ends (the plate's big faces there). accept(edge dict) -> bool may drop edges."""
    amap = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(solid.wrapped, TopAbs_EDGE, TopAbs_FACE, amap)
    vmap = None
    out = []
    axes = [np.array(a, float) / np.linalg.norm(a) for a in axes]
    for i in range(1, amap.Extent() + 1):
        key = amap.FindKey(i)
        ad = BRepAdaptor_Curve(TopoDS.Edge_s(key))             # the kernel's own adaptor: much cheaper than cq.Edge for the many edges that are not lines
        if ad.GetType() != GeomAbs_Line:
            continue
        p0, p1 = ad.Value(ad.FirstParameter()), ad.Value(ad.LastParameter())
        a, b = np.array([p0.X(), p0.Y(), p0.Z()]), np.array([p1.X(), p1.Y(), p1.Z()])
        L = float(np.linalg.norm(b - a))
        if L < min_len:
            continue
        d = (b - a) / L
        if not any(abs(float(d @ ax)) > 0.9999 for ax in axes):
            continue
        fshapes = list(amap.FindFromIndex(i))
        if len(fshapes) != 2:
            continue
        sa = [BRepAdaptor_Surface(TopoDS.Face_s(x)) for x in fshapes]
        if all(x.GetType() == GeomAbs_Plane for x in sa):         # two planes: the unoriented normals already say whether the fold is more than min_deg
            nn = [x.Plane().Axis().Direction() for x in sa]
            dot = abs(nn[0].X() * nn[1].X() + nn[0].Y() * nn[1].Y() + nn[0].Z() * nn[1].Z())
            if dot >= math.cos(math.radians(min_deg)):
                continue
        e = cq.Edge(key)
        faces = [Face(x) for x in fshapes]
        mid = e.positionAt(0.5)
        n1, n2 = _fast_normal(faces[0], mid), _fast_normal(faces[1], mid)
        ang = math.degrees(math.acos(max(-1.0, min(1.0, float(n1 @ n2)))))
        if ang <= min_deg:
            continue
        cps = []
        if caps:
            if vmap is None:
                vmap = TopTools_IndexedDataMapOfShapeListOfShape()
                TopExp.MapShapesAndAncestors_s(solid.wrapped, TopAbs_VERTEX, TopAbs_FACE, vmap)
            for v in e.Vertices():
                k = vmap.FindIndex(v.wrapped)
                if k:
                    for fs in vmap.FindFromIndex(k):
                        sa = BRepAdaptor_Surface(TopoDS.Face_s(fs))
                        if sa.GetType() == GeomAbs_Plane:
                            nd = sa.Plane().Axis().Direction()
                            if abs(nd.X() * d[0] + nd.Y() * d[1] + nd.Z() * d[2]) > 0.9999:
                                cps.append(Face(fs))
        info = dict(edge=e, mid=_vec(mid), angle=ang, faces=faces, length=L, caps=cps, a=a, b=b)
        if accept is None or accept(info):
            out.append(info)
    return out


# ---------------------------------------------------------------------------
# edges of a solid with their two faces (for the 3D fillets of revision 8, rule 4)
# ---------------------------------------------------------------------------
def edge_table(solid):
    """[(edge, [face, face])] for every edge of the solid that two faces share."""
    amap = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(solid.wrapped, TopAbs_EDGE, TopAbs_FACE, amap)
    out = []
    for i in range(1, amap.Extent() + 1):
        faces = [Face(x) for x in amap.FindFromIndex(i)]
        if len(faces) == 2:
            out.append((cq.Edge(amap.FindKey(i)), faces))
    return out


def is_concave(solid, edge, faces, eps=0.05) -> bool:
    """True when the material wraps more than 180 deg around the edge. Probe two points beside the edge, displaced along
    +-(n1 - n2) (the outward normals of the two faces): both lie in the material at a concave edge and both outside at a convex one."""
    mid = _vec(edge.positionAt(0.5))
    n1, n2 = _vec(faces[0].normalAt(edge.positionAt(0.5))), _vec(faces[1].normalAt(edge.positionAt(0.5)))
    dv = n1 - n2
    if np.linalg.norm(dv) < 1e-6:
        return False
    dv = dv / np.linalg.norm(dv)
    return all(solid.isInside(Vector(*(mid + sgn * eps * dv))) for sgn in (1.0, -1.0))
