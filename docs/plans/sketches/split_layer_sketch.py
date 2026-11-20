"""The split of the organic layer's piece `main`, second sketch: the layer built with the joints' knots and with the films laid for the seams.

The owner, 20 Nov 2026: seams near the corners (the face and the hood whole), and the pieces screwed to each other. split_sketch.py showed where seams could go on the layer as it
is; this one builds the layer as it would be: a knot on every bone a seam crosses (a half-lap closed by one M3 into an insert), no film across a seam, and eight pieces:

  front            the lip, the bone over the card and front_low between the front seams, their films, the hood
  corner_R/_L      the ring, the side bone, the top of the front post, the outer ends of the lip and of the bone over the card, the films and ties on them
  foot_L           the left front post below its seam, the outer end of front_low, the front of the base rail and the ring's tie to the rail
  post_R, rail_R   the same on the right in two pieces: the post's foot and the base rail do not join there (front-and-outline.md, "The front posts' feet hang"), so the post with
                   the end of front_low is one piece on the pad front_post_R and the front of the rail another on the pad front_foot_R
  rear_R/_L        the rear sweep, the rest of the base rail, the film between them

Nothing in cad_b6/ is edited: organic_frame is loaded and its bone_members and film_list are replaced here.

Run from the repository root:
  .venv/bin/python docs/plans/sketches/split_layer_sketch.py sections [FIELD.npz]     the room round each bone where a joint is meant, read off a saved field
  .venv/bin/python docs/plans/sketches/split_layer_sketch.py layer OUT.npz            build the layer, its own checks, save the field
  .venv/bin/python docs/plans/sketches/split_layer_sketch.py pieces FIELD.npz [PREFIX]   cut that field at the joints: the table of pieces; with PREFIX also pictures in colours
  .venv/bin/python docs/plans/sketches/split_layer_sketch.py drivers                  the skeleton and the hardware in a driver's way to each joint's screw
  .venv/bin/python docs/plans/sketches/split_layer_sketch.py strength FIELD.npz       organic_strength.py's run of `main` on that field (the joints read as rigid)
  .venv/bin/python docs/plans/sketches/split_layer_sketch.py export OUT_DIR FIELD.npz    render_blender.py's export with that field
"""
import math
import os
import sys

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

ROOT = os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "cad_b6"))
sys.path.insert(0, os.path.join(ROOT, "docs", "plans", "sketches"))
import hardware as hw
import organic_frame as of

sc = of.sc
BED = 290.0
C45 = math.sqrt(0.5)
N_OUT = np.array([0.0, -C45, C45])           # the board's outward normal: forward and up
U_DIR = np.array([0.0, C45, C45])            # the board's u: back and up

# The joint (split_sketch.py's picture and joint_probe.py): a knot of radius KNOT_R round the bone over the lap, tapering to the bone over TAPER each side; the lap LAP long, parted
# by the plane through the knot's axis across the screw; the screw's head sunk in the half the driver reaches, the insert in the other.
KNOT_R, LAP, TAPER, KNOT_BLEND = 10.0, float(os.environ.get("SK_LAP", 20.0)), 8.0, 6.0
HEAD_R, DRIVER_REACH = of.HEAD_R, of.HEAD_REACH

FRONT_S = float(os.environ.get("SK_FRONT_S", 127.0))          # the front's seams on the lip and on the bone over the card, |X|
LOW_S = (-FRONT_S, float(os.environ.get("SK_LOW_R", 140.0)))  # and on front_low: on the right the hood's roof ends at X 143 and the post stands at 155, so the seam is between them
ROOF_END_R = float(os.environ.get("SK_ROOF_END", 104.0))     # the roof's centre line ends here on the right (117 today, its cap 26 beyond): the lap of the right seam starts where it ends
POST_Z = float(os.environ.get("SK_POST_Z", 150.0))           # a front post's seam, height
RAIL_Y = float(os.environ.get("SK_RAIL_Y", 165.0))           # a base rail's seam
REAR_ARC = float(os.environ.get("SK_REAR_ARC", 24.0))        # a rear sweep's seam, along it from the ring's centre line
TIE3_ARC = float(os.environ.get("SK_TIE3_ARC", 24.0))        # the left ring's tie to the rail: its seam, along it from the ring's centre line
FILM_IN = FRONT_S - LAP / 2 - TAPER - 6.0                    # the films of the front panel end here, |X|
FILM_OUT = FRONT_S + LAP / 2 + TAPER + 4.0                   # the films of the corner pieces start here


def fine(line, step=0.5):
    """A centre line resampled at `step` (the layer saves its bones' lines at 6 mm)."""
    line = np.asarray(line, dtype=float)
    cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(line, axis=0), axis=1))])
    s = np.arange(0.0, cum[-1] + 1e-9, step)
    return np.stack([np.interp(s, cum, line[:, k]) for k in range(3)], axis=1)


def unit(v):
    v = np.asarray(v, dtype=float)
    return v / np.linalg.norm(v)


# name: (bone, how its point is found: (axis, value) or ("arc", mm from the bone's start), the screw's direction (towards the driver; made square to the bone), the knot's centre off
# the bone's axis (mm along the screw's direction, mm along the third direction), the piece on the bone's start side, the piece on its end side, the piece with the head)
def joint_table():
    t = {}
    for s, tag in ((-1, "L"), (1, "R")):
        end, mid = ("corner_" + tag, "front") if s < 0 else ("front", "corner_" + tag)
        t["lip_" + tag] = ("lip", (0, s * FRONT_S), N_OUT, LIP_OFF, end, mid, "front")
        t["card_" + tag] = ("card", (0, s * FRONT_S), N_OUT, CARD_OFF, end, mid, "front")
        foot, rail = ("foot_L", "foot_L") if s < 0 else ("post_R", "rail_R")
        a, b = (foot, "front") if s < 0 else ("front", foot)
        t["low_" + tag] = ("front_low", (0, LOW_S[0] if s < 0 else LOW_S[1]), N_OUT, (0.0, 0.0), a, b, "front")
        t["post_" + tag] = ("front_" + tag, (2, POST_Z), (0.0, -1.0, 0.0), (0.0, 0.0), foot, "corner_" + tag, "corner_" + tag)
        t["rail_" + tag] = ("base_" + tag, (1, RAIL_Y), (float(s), 0.0, 0.0), (0.0, 0.0), rail, "rear_" + tag, rail)
        t["sweep_" + tag] = ("rear_" + tag, ("arc", REAR_ARC), (float(s), 0.0, 0.0), (0.0, 0.0), "corner_" + tag, "rear_" + tag, "corner_" + tag)
    t["tie3_L"] = ("ring_tie_L3", ("arc", TIE3_ARC), (-1.0, 0.0, 0.0), (0.0, 0.0), "corner_L", "foot_L", "corner_L")
    return t


LIP_OFF = tuple(float(a) for a in os.environ.get("SK_LIP_OFF", "0,0").split(","))
CARD_OFF = tuple(float(a) for a in os.environ.get("SK_CARD_OFF", "0,0").split(","))
WHOLE = {"ring": "corner", "side": "corner", "ring_tie_L": "corner", "ring_tie_L2": "corner"}       # bones no seam crosses
PAD_PIECE = {"front_foot_L": "foot_L", "front_post_L": "foot_L", "front_foot_R": "rail_R", "front_post_R": "post_R", "base_mid": "rear", "rear_foot": "rear", "rear_post": "rear",
             "neck_top": "corner"}
ORDER = ("rear_R", "rear_L", "rail_R", "post_R", "foot_L", "corner_R", "corner_L", "front")                   # the order they go on the skeleton
COLOURS = {"front": (0.20, 0.45, 0.80), "corner_L": (0.20, 0.65, 0.35), "corner_R": (0.20, 0.65, 0.35), "foot_L": (0.90, 0.55, 0.10), "post_R": (0.90, 0.55, 0.10), "rail_R": (0.80, 0.25, 0.60),
           "rear_L": (0.75, 0.20, 0.20), "rear_R": (0.75, 0.20, 0.20)}


def joints(lines):
    """{name: dict(bone, k: the point's number on the bone's fine line, line, P: the knot's centre, e: the bone's direction there, s: the screw's direction, t: the third, a_side,
    b_side, head)}."""
    out = {}
    for name, (bone, where, screw, off, a_side, b_side, head) in joint_table().items():
        line = fine(lines[bone])
        if where[0] == "arc":
            k = int(round(where[1] / 0.5))
        else:
            k = int(np.argmin(np.abs(line[:, where[0]] - where[1])))
        e = unit(line[min(k + 4, len(line) - 1)] - line[max(k - 4, 0)])
        s = unit(np.asarray(screw, dtype=float) - e * (np.asarray(screw, dtype=float) @ e))
        t = np.cross(e, s)
        out[name] = dict(bone=bone, k=k, line=line, P=line[k] + s * off[0] + t * off[1], axis=line[k], e=e, s=s, t=t, a_side=a_side, b_side=b_side, head=head)
    return out


def knot_member(j, r_bone=6.0):
    """The knot: a tube along the bone through the knot's centre, KNOT_R over the lap and down to the bone's radius over TAPER each side."""
    h = LAP / 2 + TAPER

    def prof(tt):
        a = abs(2 * tt - 1) * h
        return KNOT_R if a <= LAP / 2 else KNOT_R - (KNOT_R - r_bone) * (a - LAP / 2) / TAPER

    return ("tube", [tuple(j["P"] - j["e"] * h), tuple(j["P"]), tuple(j["P"] + j["e"] * h)], prof, KNOT_BLEND)


def sections(field):
    """The room round each bone at its joint, read off a saved field: how far the solid reaches from the bone's axis along the screw's direction and along the third, within 3 mm
    of the joint's point along the bone; and what stands in the driver's way."""
    f = np.load(field)
    xs, ys, zs, d = f["xs"], f["ys"], f["zs"], f["d_main"]
    _m, lines = of.bone_members()
    for name, j in joints(lines).items():
        P = j["axis"]
        sl = tuple(slice(int(np.searchsorted(g, c - 30.0)), int(np.searchsorted(g, c + 30.0))) for g, c in zip((xs, ys, zs), P))
        X, Y, Z = np.meshgrid(xs[sl[0]], ys[sl[1]], zs[sl[2]], indexing="ij")
        R = np.stack([X - P[0], Y - P[1], Z - P[2]], axis=-1)
        a, c, t = R @ j["e"], R @ j["s"], R @ j["t"]
        near = (np.abs(a) <= 3.0) & (d[sl] < 0) & (c ** 2 + t ** 2 < 16.0 ** 2)
        way = (np.sqrt(np.maximum((R ** 2).sum(axis=-1) - c ** 2, 0.0)) <= HEAD_R) & (c > KNOT_R + 1.5) & (c < KNOT_R + DRIVER_REACH) & (d[sl] < 0)
        print(f"{name:8s} on {j['bone']:11s} at X {P[0]:7.1f} Y {P[1]:6.1f} Z {P[2]:6.1f}  bone along ({j['e'][0]:5.2f} {j['e'][1]:5.2f} {j['e'][2]:5.2f}) screw from ({j['s'][0]:5.2f} "
              f"{j['s'][1]:5.2f} {j['s'][2]:5.2f}); solid along the screw {c[near].min():5.1f}..{c[near].max():4.1f}, across {t[near].min():5.1f}..{t[near].max():4.1f} "
              f"(third direction {j['t'][0]:5.2f} {j['t'][1]:5.2f} {j['t'][2]:5.2f}); layer in the driver's way {int(way.sum())} voxels")



def span(ctrl, x0, x1):
    """Three points of a bone's centre line: at X x0, half way, and at X x1 (a film's bar along that stretch of the bone)."""
    line = sc.spline(ctrl, step=0.5)
    return [tuple(float(c) for c in line[int(np.argmin(np.abs(line[:, 0] - x)))]) for x in (x0, (x0 + x1) / 2, x1)]


FILM_PIECE = []           # the piece of each film, in film_list's order


def film_list():
    """organic_frame.film_list laid for the seams: the two films between the bone over the card and the lip each in an inner part (the front panel's) and an outer part (the corner
    piece's), the front film between the front seams only, the right ring's film landing on the post above the post's seam."""
    bp, fm = of.bp, of.film_members
    out = []
    FILM_PIECE.clear()

    def add(piece, film):
        FILM_PIECE.append(piece)
        out.append(film)

    x0, x1 = of.PLUG_WINDOW_X
    away = (0.0, -0.707, 0.707)
    r = of.CARD_FILM_R
    add("front", fm(span(of.CARD, -FILM_IN, x0), span(of.LIP_BONE, -FILM_IN, x0), 4, seed=3, r_a=r, r_b=r, sag=away, sag_mm=4, links=3))
    add("front", fm(span(of.CARD, x1, FILM_IN), span(of.LIP_BONE, x1, FILM_IN), 3, seed=8, r_a=r, r_b=r, sag=away, sag_mm=4, links=2))
    fl = of.FRONT_FILM
    low = [(-FILM_IN, of.FRONT_LOW_Y, of.FRONT_LOW_Z), (0.0, of.FRONT_LOW_Y, of.FRONT_LOW_Z), (FILM_IN, of.FRONT_LOW_Y, of.FRONT_LOW_Z)]
    n_front = int(os.environ.get("SK_FRONT_N", 9))
    add("front", fm(low, span(of.CARD, -FILM_IN, FILM_IN), n_front, seed=fl["seed"], r_a=fl["r_a"], r_b=fl["r_b"], sag=fl["sag"], sag_mm=fl["sag_mm"], links=int(os.environ.get("SK_FRONT_LINKS", 8))))
    add("corner_L", fm(span(of.CARD, -of.SWEEP_X, -FILM_OUT), span(of.LIP_BONE, -190.0, -FILM_OUT), 2, seed=4, r_a=r, r_b=r, sag=away, sag_mm=3, links=1))
    add("corner_R", fm(span(of.CARD, FILM_OUT, of.SWEEP_X), span(of.LIP_BONE, FILM_OUT, 190.0), 2, seed=9, r_a=r, r_b=r, sag=away, sag_mm=3, links=1))
    for s, tag in ((-1, "L"), (1, "R")):
        (u0, u1), (n0, n1) = hw.FAN_SIDE_U, hw.FAN_SIDE_N
        x = of.RING_X[s]
        a, top = u0 - of.RING_OFF, n1 + of.RING_OFF
        if s > 0:
            near = [bp(a, of.NEAR_FILM_N0, x), bp(a, (of.NEAR_FILM_N0 + n1) / 2, x), bp(a, n1 - 4, x)]
            post = of.front_sweep(s)
            land = [of.at_z(post[0], post[3], POST_Z + LAP / 2 + TAPER + 4.0), post[3], of.toward(post[3], post[4], float(os.environ.get("SK_NEAR_UP", 28.0)))]
            add("corner_R", fm(near, land, 6, seed=50 + s, r_a=5.0, r_b=7.0, sag=(0.4 * s, 0.0, 0.0), sag_mm=8, links=2))
        ua = u0 + 12 if s > 0 else of.TOP_FILM_L_U0
        add("corner_" + tag, fm([bp(ua, top, x), bp((ua + u1 - 12) / 2, top + 1, x), bp(u1 - 12, top, x)], of.side_bone(s)[:3], 6, seed=70 + s, r_a=5.0, r_b=5.5,
                                sag=(0.5 * s, 0.0, 0.0), sag_mm=6, links=2))
        add("rear_" + tag, fm(of.BASE[s][2:], of.rear_sweep(s)[1:5], 9, seed=80 + s, r_a=6.5, r_b=6.5, sag=(0.4 * s, 0.0, 0.0), sag_mm=9))
    return out


_PATCHED = {}


def patch():
    """organic_frame builds the layer with the joints' knots, the roof's right end shortened, and the films above."""
    if _PATCHED:
        return
    old = of.bone_members
    _PATCHED["bones"] = old

    def bone_members():
        out, lines = old()
        new = []
        for m in out:
            if m[0] == "slab" and m[4][0] == "z":                    # the hood's roof: its right end stops at ROOF_END_R
                ctrl = list(m[1])
                assert ctrl[-1][0] == of.HOOD_X[1], "the roof is not where the sketch expects it"
                ctrl[-1] = (ROOF_END_R, *ctrl[-1][1:])
                m = (m[0], ctrl, *m[2:])
            new.append(m)
        for j in joints(lines).values():
            new.append(knot_member(j))
        return new, lines

    of.bone_members = bone_members
    of.film_list = film_list


def layer_main(out_npz):
    import frame_v0

    patch()
    hware = hw.build_hardware()
    parts, _ = frame_v0.build_frame(hardware=hware)
    U, anchors, fields, info = of.build(parts, hware)
    z = of.saved_arrays(U, anchors, fields, parts, info)
    np.savez(out_npz, **z)
    print("saved", out_npz)
    for piece, F in fields.items():
        lab, n = ndimage.label(F.d < 0)
        print(f"{piece}: {(F.d < 0).sum() * F.vox ** 3 / 1000.0:.1f} cm3 in {n} bodies")
    print("\n".join(of.film_record_lines(info)))
    _lines, fails = of.check(U, anchors, parts, hware, info["lines"], z)
    print(f"organic_frame's own checks: {'pass' if not fails else str(len(fails)) + ' FAIL'}")
    for t in fails[:12]:
        print("   ", str(t)[:300])


UP = {"standing": (0, 0, 1), "on its side": (1, 0, 0), "on its back": tuple(N_OUT), "on its rear": (0, 1, 0)}


def lie(xyz, vox):
    """How the piece fits the bed with each of UP's directions vertical, turned about it by whole degrees: {what: (the two sides on the bed, the height, the turn)} at the turn with
    the smallest larger side. A side is the span of the solid points' centres plus the cube's own width along it."""
    out = {}
    for what, up in UP.items():
        up = np.array(up, dtype=float)
        a = unit(np.cross(up, (1.0, 0.0, 0.0) if abs(up[0]) < 0.9 else (0.0, 1.0, 0.0)))
        b = np.cross(up, a)
        h = float(np.ptp(xyz @ up)) + vox * float(np.abs(up).sum())
        pa, pb = xyz @ a, xyz @ b
        best = None
        for deg in range(0, 180):
            c, s_ = math.cos(math.radians(deg)), math.sin(math.radians(deg))
            da, db = a * c + b * s_, -a * s_ + b * c
            sides = (float(np.ptp(pa * c + pb * s_)) + vox * float(np.abs(da).sum()), float(np.ptp(-pa * s_ + pb * c)) + vox * float(np.abs(db).sum()))
            if best is None or max(sides) < max(best[0]) - 1e-6:
                best = (sides, h, deg)
        out[what] = best
    return out


def piece_points(lines, films):
    """(points, the piece of each): every bone's centre line with the pieces its joints give it, every film member with its film's piece, the hood with the front panel's."""
    js = joints(lines)
    pts, own = [], []
    for name, line in lines.items():
        line = fine(line)
        on = sorted((j["k"], j) for j in js.values() if j["bone"] == name)
        if on:
            piece = np.empty(len(line), dtype=object)
            piece[:] = on[-1][1]["b_side"]
            for k, j in reversed(on):
                piece[:k] = j["a_side"]
            assert all(on[i][1]["b_side"] == on[i + 1][1]["a_side"] for i in range(len(on) - 1)), f"{name}: its joints disagree about the piece between them"
        else:
            kind = next((v for k_, v in WHOLE.items() if name == k_ or name.startswith(k_ + "_")), None)
            assert kind, f"no piece for the bone {name}"
            piece = np.full(len(line), kind + "_" + ("L" if "_L" in name else "R"), dtype=object)
        pts.append(line)
        own += list(piece)
    for fi, fm in enumerate(films):
        for m in fm:
            p = np.asarray(sc.spline(m[1], step=2.0), dtype=float)
            pts.append(p)
            own += [FILM_PIECE[fi]] * len(p)
    for x in np.arange(of.HOOD_X[0], ROOF_END_R + 0.1, 4.0):
        for dy in (-18.0, 0.0, 18.0):
            pts.append(np.array([[x, of.FRONT_LOW_Y + dy, of.ROOF_Z]]))
            own.append("front")
    for x in of.HOOD_X:
        for zc in np.arange(26.0, 58.0, 4.0):
            for dy in (-16.0, 0.0, 16.0):
                pts.append(np.array([[x, of.FRONT_LOW_Y + dy, zc]]))
                own.append("front")
    return np.vstack(pts), np.array(own, dtype=object), js


def cut(f):
    """The saved field of `main` cut at the joints: (names, the piece's number of every solid grid point, the joints, lines of findings). Every solid point goes to the piece of the
    nearest member; inside a joint's lap the half on the screw's side goes to the piece with the head and the other half to its neighbour."""
    patch()
    _m, lines = of.bone_members()
    films = of.film_list()
    pts, own, js = piece_points(lines, films)
    names = list(ORDER)
    num = np.array([names.index(p) for p in own])
    xs, ys, zs = f["xs"], f["ys"], f["zs"]
    vox = float(xs[1] - xs[0])
    solid = f["d_main"] < 0
    idx = np.argwhere(solid)
    xyz = np.stack([xs[idx[:, 0]], ys[idx[:, 1]], zs[idx[:, 2]]], axis=1).astype(float)
    _d, near = cKDTree(pts).query(xyz, workers=-1)
    lab_pts = num[near]
    in_lap = np.zeros(len(xyz), dtype=bool)
    notes = []
    for name, j in js.items():
        R = xyz - j["P"]
        a, c = R @ j["e"], R @ j["s"]
        rad = np.sqrt(np.maximum((R ** 2).sum(axis=1) - a ** 2, 0.0))
        other = j["b_side"] if j["head"] == j["a_side"] else j["a_side"]
        knot = rad <= KNOT_R + 3.0
        lap = knot & (np.abs(a) <= LAP / 2)
        lab_pts[lap & (c > 0)] = names.index(j["head"])
        lab_pts[lap & (c <= 0)] = names.index(other)
        lab_pts[knot & (a < -LAP / 2) & (a > -LAP / 2 - TAPER - 4.0)] = names.index(j["a_side"])
        lab_pts[knot & (a > LAP / 2) & (a < LAP / 2 + TAPER + 4.0)] = names.index(j["b_side"])
        in_lap |= (rad <= KNOT_R + 3.0 + vox) & (np.abs(a) <= LAP / 2 + vox)
        ideal = (np.abs(a) <= LAP / 2) & (rad <= KNOT_R - 1.5)
        # the ideal knot's volume against what the layer has of it, half by half
        full = math.pi * (KNOT_R - 1.5) ** 2 * LAP / 2
        up, dn = float((ideal & (c > 0)).sum()) * vox ** 3 / full, float((ideal & (c <= 0)).sum()) * vox ** 3 / full
        way = (np.sqrt(np.maximum((R ** 2).sum(axis=1) - c ** 2, 0.0)) <= HEAD_R + vox / 2) & (c > KNOT_R + 1.5) & (c < KNOT_R + DRIVER_REACH)
        notes.append(f"{name:8s} {j['a_side']:9s}|{j['b_side']:9s} head in {j['head']:9s} at X {j['P'][0]:7.1f} Y {j['P'][1]:6.1f} Z {j['P'][2]:6.1f}; of the knot's two halves the layer has "
                     f"{up:.2f} and {dn:.2f}; layer in the driver's way: {int(way.sum())} voxels")
    lab = np.full(solid.shape, -1, dtype=np.int16)
    lab[solid] = lab_pts
    lap3 = np.zeros(solid.shape, dtype=bool)
    lap3[solid] = in_lap
    # the nearest member is not always the member a voxel hangs on (a pad's knot beside another piece's bone): a bit of a piece that is loose from the piece's body and lies against
    # another piece outside a lap goes to that piece
    cross = ndimage.generate_binary_structure(3, 1)
    for k, name in enumerate(names):
        comp, n = ndimage.label(lab == k)
        if n < 2:
            continue
        sizes = ndimage.sum(lab == k, comp, index=np.arange(1, n + 1))
        for c_ in range(1, n + 1):
            if c_ == int(np.argmax(sizes)) + 1:
                continue
            bit = comp == c_
            rim = ndimage.binary_dilation(bit, structure=cross) & ~bit & (lab >= 0) & ~lap3
            if rim.any():
                to = int(np.bincount(lab[rim]).argmax())
                lab[bit] = to
                notes.append(f"   a loose bit of {name}, {sizes[c_ - 1] * vox ** 3 / 1000:.2f} cm3 round X {xs[np.where(bit)[0]].mean():.0f} Y {ys[np.where(bit)[1]].mean():.0f} Z {zs[np.where(bit)[2]].mean():.0f}, "
                             f"lies against {names[to]} and goes to it")
    stray = {}
    for ax in range(3):
        a_, b_ = [slice(None)] * 3, [slice(None)] * 3
        a_[ax], b_[ax] = slice(0, -1), slice(1, None)
        a_, b_ = tuple(a_), tuple(b_)
        differ = (lab[a_] >= 0) & (lab[b_] >= 0) & (lab[a_] != lab[b_]) & ~(lap3[a_] | lap3[b_])
        for i, k in zip(lab[a_][differ], lab[b_][differ]):
            key = tuple(sorted((names[i], names[k])))
            stray[key] = stray.get(key, 0) + 1
        if differ.any():
            w = np.argwhere(differ)
            for key in {tuple(sorted((names[i], names[k]))) for i, k in zip(lab[a_][differ], lab[b_][differ])}:
                sel = np.array([tuple(sorted((names[i], names[k]))) == key for i, k in zip(lab[a_][differ], lab[b_][differ])])
                q = w[sel]
                notes.append(f"   touch outside a lap, {key[0]}/{key[1]}, along {'XYZ'[ax]}: {len(q)} pairs round X {xs[q[:, 0]].mean():.0f} Y {ys[q[:, 1]].mean():.0f} Z {zs[q[:, 2]].mean():.0f}")
    notes.append("pieces touch outside the laps: " + (", ".join(f"{a}/{b} {n}" for (a, b), n in sorted(stray.items())) or "nowhere"))
    return names, lab, js, notes


def pieces_main(field, prefix=None):
    f = np.load(field)
    names, lab, js, notes = cut(f)
    xs, ys, zs = f["xs"], f["ys"], f["zs"]
    vox = float(xs[1] - xs[0])
    pad_rows = [(str(n), np.asarray(p[:3], dtype=float)) for n, p, pc in zip(f["names"], f["pads"], f["pad_piece"]) if str(pc) == "main"]
    print(f"`main` {(lab >= 0).sum() * vox ** 3 / 1000:.1f} cm3, cut at {len(js)} joints into {len(names)} pieces (lap {LAP:g}, knot radius {KNOT_R:g}):")
    for k, name in enumerate(names):
        idx = np.argwhere(lab == k)
        xyz = np.stack([xs[idx[:, 0]], ys[idx[:, 1]], zs[idx[:, 2]]], axis=1).astype(float)
        _l, n = ndimage.label(lab == k)
        sizes = sorted(ndimage.sum(lab == k, _l, index=np.arange(1, n + 1)) * vox ** 3 / 1000.0, reverse=True)
        tree = cKDTree(xyz)
        pads = sorted(p for p, q in pad_rows if tree.query(q)[0] < 6.0)
        want = sorted(p for p, _q in pad_rows if PAD_PIECE.get(p, PAD_PIECE.get(p[:-2], "") + "_" + p[-1]) == name)
        fits = lie(xyz[:: max(1, len(xyz) // 30000)], vox)
        ok = {w: v for w, v in fits.items() if max(v[0]) <= BED and v[1] <= BED}
        lo, hi = xyz.min(axis=0) - vox / 2, xyz.max(axis=0) + vox / 2
        print(f"{name:9s} {len(idx) * vox ** 3 / 1000:6.1f} cm3  X {lo[0]:5.0f}..{hi[0]:5.0f} Y {lo[1]:5.0f}..{hi[1]:5.0f} Z {lo[2]:5.0f}..{hi[2]:5.0f}; bodies {n}"
              + (f" (the rest {sum(sizes[1:]):.2f} cm3 in {n - 1})" if n > 1 else "") + f"; pads {len(pads)}" + ("" if pads == want else f" BUT MEANT {want}, HAS {pads}")
              + f"; joints {sum(1 for j in js.values() if name in (j['a_side'], j['b_side']))}")
        print("          " + "; ".join(f"{w}: {v[0][0]:.0f} x {v[0][1]:.0f} on the bed, {v[1]:.0f} tall, turned {v[2]}" + ("" if w in ok else " OVER") for w, v in fits.items()))
    print("\n".join(notes))
    if prefix:
        import split_sketch

        split_sketch.COLOURS.update(COLOURS)
        split_sketch.picture(f, names, lab, prefix)
    return names, lab, js


def drivers_main():
    """What of the skeleton and of the hardware stands in a driver's way to each joint's screw: a cylinder of the head's radius from the knot's surface out to the driver's reach,
    cut with every part and every piece of hardware (the exact solids)."""
    import cadquery as cq
    import frame_v0

    patch()
    hware = hw.build_hardware()
    parts, _ = frame_v0.build_frame(hardware=hware)
    solids = [("part " + p_.name, p_.solid) for p_ in parts] + [("hardware " + k, v) for k, v in hware.items() if k not in hw.KEEP_OUT]
    solids = [(n, v.val() if hasattr(v, "val") else v) for n, v in solids]
    boxes = [(n, v, v.BoundingBox()) for n, v in solids]
    _m, lines = of.bone_members()
    for name, j in joints(lines).items():
        a = j["P"] + j["s"] * KNOT_R
        cyl = cq.Solid.makeCylinder(HEAD_R, DRIVER_REACH, cq.Vector(*a), cq.Vector(*j["s"]))
        cb = cyl.BoundingBox()
        hits = []
        for n, v, b in boxes:
            if b.xmin > cb.xmax or b.xmax < cb.xmin or b.ymin > cb.ymax or b.ymax < cb.ymin or b.zmin > cb.zmax or b.zmax < cb.zmin:
                continue
            vol = v.intersect(cyl).Volume()
            if vol > 1e-3:
                hits.append(f"{n} {vol:.0f} mm3")
        print(f"{name:8s} the driver's way from X {a[0]:.0f} Y {a[1]:.0f} Z {a[2]:.0f} along ({j['s'][0]:5.2f} {j['s'][1]:5.2f} {j['s'][2]:5.2f}): " + ("; ".join(hits) or "free"), flush=True)


def strength_main(field):
    """organic_strength.py's run of `main` on the sketch's field: the surface pushes, the own weight, and a 30 N push on every strand and cross-thread. The joints are solid knots."""
    patch()
    import organic_strength as st

    st.FIELD = field
    out, fl, _arr, head = st.run_piece("main", 1)
    print(st.headline(head))
    print(f"main: {'pass' if not fl else str(len(fl)) + ' FAIL'}")
    for t in fl:
        print("   ", t[:300])


def export_main(out_dir, field):
    import cadquery  # noqa: F401  (before vtk, as render_blender.py does)
    import render_blender as rb

    sys.argv = [rb.__file__, "--src", os.path.join(ROOT, "cad_b6"), "--out", out_dir, "--field", field]
    rb.main()

if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "sections":
        sections(sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "out", "organic", "field.npz"))
    elif mode == "layer":
        layer_main(sys.argv[2])
    elif mode == "pieces":
        pieces_main(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif mode == "drivers":
        drivers_main()
    elif mode == "strength":
        strength_main(sys.argv[2])
    elif mode == "export":
        export_main(sys.argv[2], sys.argv[3])
