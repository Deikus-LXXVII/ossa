"""Revision 19, a sketch: the bone over the card whole again and farther from the card, the card's power cable in a small arch under it.

The owner on revision 18's render (19 Nov 2026): "this does not suit me ... leave a little room round the card's power connector, and I have said already that the PSU's
power cables are very flexible, they do not need an arc of the size you made in the render", then: "stop, do not lower the beam, just move it a little away from the
card so that more room is left under it".

What revision 18 did: the plug (13 mm), a straight of 35 and a bend of R 35 stood the cable up to n 220, 51 mm past the bone `card`, so the bone was cut in two with a gate
67 mm wide and the cable arched through it.

Here: the straight is STRAIGHT and the bend BEND (the owner's cable; 35 and 35 were the plan's general figures for a 12V-2x6 lead), the arch turns over towards +u and comes
down beside the card's top edge, and the bone `card` is one bone again, its centre line BEAM_OUT farther from the card along n, so that the arch passes under it with the
layer's clearance from a cable. The films either side of the connector keep a window over it.

Run from the repository root:
  .venv/bin/python docs/plans/sketches/beam_out_sketch.py route [n_a v_d u_d n_run ...]     the cable alone, cables.py's own checks, one line per candidate
  .venv/bin/python docs/plans/sketches/beam_out_sketch.py layer OUT.npz [--strength]        the layer built with the cable and the bone as above, its own checks, the field saved
  .venv/bin/python docs/plans/sketches/beam_out_sketch.py strength FIELD.npz                 organic_strength.py's run of `main` on that field (20 minutes, 10 GB)
  .venv/bin/python docs/plans/sketches/beam_out_sketch.py export OUT_DIR FIELD.npz          cad_b6/render_blender.py's export with this cable and that field, for blender_noctua.py
"""
import math
import os
import sys

import numpy as np

ROOT = os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "cad_b6"))
sys.path.insert(0, os.path.join(ROOT, "docs", "plans", "sketches"))
import hardware as hw
import frame_v0
import cables
import hoses

# The cable: straight at the plug, least bend (centre line). First try 10 and 20 with the bone 25 mm out; the owner: "not that far", with a photo of the cable in his present case
# (single sleeved wires in two rows, turned through 90 degrees right behind the plug within about 15 mm): "look how well the power cable bends, it does not need that much room".
STRAIGHT, BEND = float(os.environ.get("SK_STRAIGHT", 2.0)), float(os.environ.get("SK_BEND", 12.0))
OLD_BEND = hw.CABLES["gpu12v"][2]
GS = hw.GPU_PWR_SOCKET
MOUTH_N = hw.GPU_BS[5] - GS["recess"]
TOP_N = MOUTH_N + hw.GPU12V_PLUG + STRAIGHT + BEND          # the arch's top: 180 (220 in revision 18)
UNDER = tuple(float(a) for a in os.environ["SK_UNDER"].split(",")) if "SK_UNDER" in os.environ else (83.0, 150.0, 139.5, 115.0)        # n_a, v_d, u_d, n_run of cable_under_route.under_wps: the far leg 2 x BEND from the socket, diagonally (+v, +u), beside the card's top edge;
                                           # straight along +u (v 130 or 145) the run under the film meets the CPU hoses (runs/10_beam_out_route.txt)
BEAM_OUT = float(os.environ.get("SK_BEAM_OUT", -1.5))                            # the bone `card`'s centre line, this much farther from the card along n (the second try's route asks for n >= 180.4 at the socket; it was 169; the first try, straight 10 and bend 20 with the far leg at v 158.3, u 147.3, asked for 194.1 and was sketched with 25)
# Third try. The owner on the second try's render (19 Nov 2026): "I would like the beam to be level with the plane of the card's fans; to free a little room, move the beam a little
# forward relative to the fans". The fans' face is the card's u 75.6 (hw.GPU_BS[2]; the backplate is u 126.6, the socket u 119), and it looks forward and down. So the bone leaves
# the place over the socket altogether: its centre line goes to BEAM_U, FAN_AHEAD in front of the fans' plane, at the n revision 18 built it with (BEAM_OUT 0).
# The defaults are the third try's first variant (the bone 2.6 mm in front of the fans' plane, the layer let 24 mm in front of Y 0). Its second variant, the bone as near the fans' plane
# as the front plane lets it be, is SK_BEAM_U=91 SK_FRONT_OUT=0. The second try is SK_BEAM_U=118 SK_BEAM_OUT=12 SK_FRONT_OUT=0.
FAN_AHEAD = float(os.environ.get("SK_FAN_AHEAD", 8.6))
BEAM_U = float(os.environ["SK_BEAM_U"]) if "SK_BEAM_U" in os.environ else hw.GPU_BS[2] - FAN_AHEAD
# The layer is cut at the case's front plane (organic_frame.py: `np.maximum(F.d, -F.ys[None, :, None], out=F.d)`, Y 0) and its grid starts at Y -8 (shell_concepts.Y0). The card's
# front corner (u 75.6, n 150) is at Y 7.4, so a bone in front of the fans' plane, 10 mm (HOT_GAP) clear of the card, stands in front of Y 0: the first run of the third try came out with
# no bone `card` at all and the front posts cut off (runs/14_beam_at_fans_layer.txt; the layer's own checks passed all the same). FRONT_OUT lets the sketch's layer stand this far in
# front of Y 0: organic_frame.py is loaded with that one line changed and the grid begun farther forward. Nothing in cad_b6/ is edited.
FRONT_OUT = float(os.environ.get("SK_FRONT_OUT", 24.0))
FRONT_CUT = "np.maximum(F.d, -F.ys[None, :, None], out=F.d)"
# Fourth try. The owner on the third try's renders: "we take the first variant [the bone in front of the fans' plane], and then the second beam can go, with connections made between the
# beam we moved and the other beams and places", and: "only do not leave such open connections, in practice they will be quite easy to break off". The second beam is the brow
# (organic_frame.BROW, Y 13, Z 152), 44 mm under the moved bone. NO_BROW takes it out and hangs the front film (front_low up to the brow) on the bone `card` instead. The strands get more
# cross-threads: FRONT_LINKS in the front film (6 in revision 18, its strands were 92 mm long and are 140 now), CARD_LINKS in each film between the bone `card` and the lip (3 in revision
# 18, 58 mm strands, 108 now). `--strength` pushes every strand and cross-thread with 30 N (organic_strength.py's probes: 10 MPa and 5 mm allowed).
NO_BROW = os.environ.get("SK_NO_BROW", "1") == "1"
FRONT_LINKS, CARD_LINKS = int(os.environ.get("SK_FRONT_LINKS", 12)), int(os.environ.get("SK_CARD_LINKS", 6))
BROW_ADD = '    add("brow", BROW, bone(*BONE_R["brow"]))\n'
BROW_FILM = "[(-FRONT_FILM_X, BROW_Y, BROW_Z), (0.0, BROW_Y, BROW_Z), (FRONT_FILM_X, BROW_Y, BROW_Z)]"
CARD_FILM_ENDS = ("sag=(0.0, 0.707, -0.707), sag_mm=4, links=3))", 2)                # the two films between the bone `card` and the lip end so
# The fifth try's first build (runs/18_no_torn_layer.txt) took 3 strands and 8 cross-threads out of those two films: they now lie over the whole of the card's top face, 17.5 mm above
# it at the bone, and they sagged 4 mm towards the card, into the 10 mm the layer keeps from it (their centre lines were cut at n 159..161, u 103..130). CARD_SAG_OUT: they sag away
# from the card instead.
CARD_SAG_OUT = os.environ.get("SK_CARD_SAG_OUT", "1") == "1"
END_MM = 4.0                               # a member's last millimetres stand inside a bone, which a clearance may have shaved: there the layer within a voxel of the centre line is enough
# Fifth try. The owner, with a cut of the fourth try's render (cross-threads by the connector's window that end in the air): "by open connections I meant the parts of the organic design
# that are torn-off cross-threads". Two things make them. A cross-thread's ends stand on its two strands' chords (film_members), and a strand's middle is thrown up to about 10 mm off its
# chord, so an end can miss its strand. And a clearance (the plug's room, a cable, a hose, the card) cuts a strand or a cross-thread through and leaves both halves standing. NO_TORN:
# a cross-thread's ends are put on its strands' centre lines; then the layer is built, every strand and cross-thread whose centre line is not solid from end to end is taken out, with
# the cross-threads that hung on a strand taken out, and the layer is built again, until none is left.
NO_TORN = os.environ.get("SK_NO_TORN", "1") == "1"
DROP = set()                               # (film's number in film_list, member's number in the film) taken out
WINDOW_X = (-25.5, 41.5)                   # the films stop here either side of the connector (revision 18's gate: the socket's X 8, its tolerance 12, half a plug 10, 5 spare, a thread's radius)
PLUG_ABOVE = 10.0                          # the plug's room reaches this far along n beyond the plug and its straight


def patch_cable(under=UNDER):
    """cables.py routes the last section of gpu12v as `under`, with the straight STRAIGHT and every bend of that section BEND; the rest of the route keeps its 35."""
    import cable_under_route as cur

    hw.GPU12V_STRAIGHT = STRAIGHT
    cables.GPU12V_TOP_N = TOP_N
    old = cables.waypoints_all.__wrapped__ if hasattr(cables.waypoints_all, "__wrapped__") else cables.waypoints_all

    def waypoints_all():
        real, r, _b = hw.CABLES["gpu12v"]
        hw.CABLES["gpu12v"] = (real, r, OLD_BEND)
        R = old()
        hw.CABLES["gpu12v"] = (real, r, BEND)                  # the last section, and the stretch build() holds off the card, read the new bend
        R["gpu12v"][2] = cables.Sec("round", cur.under_wps(*under), "gpu12v")
        return R

    waypoints_all.__wrapped__ = old
    cables.waypoints_all = waypoints_all


def route_main(cands):
    import cable_under_route as cur

    patch_cable()
    hware = hw.build_hardware()
    parts, _ = frame_v0.build_frame(hardware=hware)
    targets, gpu_under = cables.route_targets(parts, hware)
    slots = cables.tie_slots(parts)
    others = {k: v for k, v in cables.build_routes().items() if k != "gpu12v"}
    for rt in others.values():
        rt.build()
    for under in cands:
        patch_cable(under)
        secs = cables.waypoints_all()["gpu12v"]
        rt = cables.Route("gpu12v", secs, own_leg=cables.OUT_LEG.get("gpu12v"))
        fails, least, pair = cur.judge(rt, others, targets, gpu_under, slots)
        bs = np.array([hoses.world_to_bs(p) for p in secs[2].pts])
        du = bs[:, 1] - (GS["u"])
        near = np.abs(du) < 18.0                                # the bone's centre line stands at the socket's u; 18 = the cable's 7 + the bone's 5 + the layer's 3 from a cable + its carve's 1.65 + 1.35
        beam_n = float((bs[near, 2] + np.sqrt(18.0 ** 2 - du[near] ** 2)).max())
        print(f"under {under}: {'pass' if not fails else str(len(fails)) + ' FAIL'}; length {rt.length:.0f} of {hw.CABLES['gpu12v'][0]:g}; least bend of the last section {secs[2].rmin:.1f}; "
              f"arch top n {bs[:, 2].max():.1f}; in front of Y 0 by {hw.ENVELOPE_Y0 - rt.ymin:.1f}; tightest {least[0]} {least[1]:.1f} (needs {least[2]:g}); nearest cable {pair[0]} x {pair[1]} "
              f"{pair[2]:.1f}; a bone of radius 5 at u {GS['u']:g} clears it by 3 with its centre line at n >= {beam_n:.1f} (now {of_card_n():.1f})"
              + ("" if not fails else "\n      " + "; ".join(fails)[:400]), flush=True)


def load_of():
    """organic_frame, loaded from its source with the sketch's changes that no attribute reaches: the front plane's cut moved FRONT_OUT forward, the brow gone."""
    if "organic_frame" in sys.modules or (FRONT_OUT <= 0 and not NO_BROW):
        import organic_frame as of

        return of
    import types
    import shell_concepts as sc

    path = os.path.join(ROOT, "cad_b6", "organic_frame.py")
    src = open(path, encoding="utf-8").read()

    def swap(old, new, count=1):
        nonlocal src
        assert src.count(old) == count, f"organic_frame.py has changed: {old!r} stands {src.count(old)} times"
        src = src.replace(old, new)

    if FRONT_OUT > 0:
        sc.Y0 -= 1.5 * math.ceil(FRONT_OUT / 1.5)              # whole steps of the grid, so that its points stay where they were
        swap(FRONT_CUT, f"np.maximum(F.d, -(F.ys + {FRONT_OUT!r})[None, :, None], out=F.d)")
    if NO_BROW:
        swap(BROW_ADD, "")
        swap(BROW_FILM, "[bp(cu + 1, cn + 1, -FRONT_FILM_X), bp(cu + 1, cn + 1, 0.0), bp(cu + 1, cn + 1, FRONT_FILM_X)]")
        sag = "(0.0, -0.707, 0.707)" if CARD_SAG_OUT else "(0.0, 0.707, -0.707)"
        swap(CARD_FILM_ENDS[0], f"sag={sag}, sag_mm=4, links={CARD_LINKS}))", CARD_FILM_ENDS[1])
    of = types.ModuleType("organic_frame")
    of.__file__ = path
    sys.modules["organic_frame"] = of
    exec(compile(src, path, "exec"), of.__dict__)
    if NO_BROW:
        of.FRONT_FILM = dict(of.FRONT_FILM, links=FRONT_LINKS)
    return of


def of_card_n():
    of = load_of()

    return of.CARD_BONE_N + 1.0


def patch_layer():
    """organic_frame builds the bone `card` whole, BEAM_OUT farther out, the films with a window over the connector, and the plug's room under the bone."""
    of = load_of()
    patch_cable()
    of.CARD_BONE_U = BEAM_U
    of.CARD_BONE_N += BEAM_OUT
    cu, cn = of.CARD_BONE_U, of.CARD_BONE_N
    whole = [of.bp(cu, cn, -of.SWEEP_X), of.bp(cu + 1, cn + 1, -60), of.bp(cu + 1, cn + 1, 60), of.bp(cu, cn, of.SWEEP_X)]
    of.PLUG_ZONE = (*of.PLUG_ZONE[:5], MOUTH_N + hw.GPU12V_PLUG + STRAIGHT + PLUG_ABOVE)
    of.EMPTY_BOXES["plug_zone"] = of.PLUG_ZONE
    of.CARD_GATE_X = WINDOW_X
    of.FILM_UNDER_X0 = WINDOW_X[1]
    # the two halves meet at the socket's X with no ball: one bone. The films read CARD_L and the right half's points from CARD_BONE_N at call time.
    mid = of.GPU_SOCKET_X
    of.CARD_L = [of.bp(cu, cn, -of.SWEEP_X), of.bp(cu + 1, cn + 1, -100), of.bp(cu + 1, cn + 1, mid)]
    of.CARD_R = [of.bp(cu + 1, cn + 1, mid), of.bp(cu + 1, cn + 1, 100), of.bp(cu, cn, of.SWEEP_X)]
    of.CARD_END_BALL = of.BONE_R["card"][1]
    old_films = of.film_list

    def film_list():
        left_whole = of.CARD_L
        of.CARD_L = [of.bp(cu, cn, -of.SWEEP_X), of.bp(cu + 1, cn + 1, -100), of.bp(cu + 1, cn + 1, WINDOW_X[0])]      # the left film ends at the window, the bone does not
        try:
            return old_films()
        finally:
            of.CARD_L = left_whole

    raw_members = of.film_members

    def film_members(*args, **kw):
        """organic_frame.film_members, each cross-thread's ends moved from its strands' chords onto their centre lines. `joins`: the two strands' member numbers, per cross-thread."""
        fm = raw_members(*args, **kw)
        kinds = [k for k, _pt, _len in fm.probes]
        n = kinds.count("strand")
        lines = [of.sc.spline(fm[2 + i][1], step=0.5) for i in range(n)]
        chords = [(np.array(fm[2 + i][1][0], dtype=float), np.array(fm[2 + i][1][-1], dtype=float)) for i in range(n)]
        fm.joins = []
        for j in range(len(kinds) - n):
            m = 2 + n + j
            ctrl = [np.array(c, dtype=float) for c in fm[m][1]]
            ends, who = [], []
            for q in (ctrl[0], ctrl[-1]):
                d = [np.linalg.norm(np.cross(b_ - a_, q - a_)) / np.linalg.norm(b_ - a_) for a_, b_ in chords]
                i = int(np.argmin(d))
                assert d[i] < 0.5, f"a cross-thread's end is {d[i]:.1f} mm from every strand's chord"
                ends.append(lines[i][int(np.argmin(np.linalg.norm(lines[i] - q, axis=1)))])
                who.append(2 + i)
            new = [ends[0], (ends[0] + ends[1]) / 2 + (ctrl[1] - (ctrl[0] + ctrl[-1]) / 2), ends[1]]
            length = float(np.linalg.norm(ends[1] - ends[0]))
            r_end, r_mid = of.link_radii(length)
            fm[m] = ("tube", new, of.bone(r_end, r_mid, r_end), fm[m][3])
            fm.probes[n + j] = ("link", of.centre_mid(new), length)
            fm.links[j] = (length, of.LINK_R[1], r_mid)
            fm.joins.append(tuple(who))
        return fm

    if NO_TORN:
        of.film_members = film_members
    windowed = film_list

    def film_list(raw=False):
        """The films, without the members in DROP (raw: with them)."""
        films = windowed()
        if raw or not DROP:
            return films
        out = []
        for fi, fm in enumerate(films):
            if not hasattr(fm, "probes"):
                out.append(fm)
                continue
            keep = [m for m in range(len(fm)) if (fi, m) not in DROP]
            new = of.Film([fm[m] for m in keep], [fm.probes[m - 2] for m in keep if m >= 2], [])
            n = [k for k, _pt, _len in fm.probes].count("strand")
            new.links = [fm.links[m - 2 - n] for m in keep if m >= 2 + n]
            out.append(new)
        return out

    of.film_list = film_list
    return of, whole


def torn(of, F):
    """The strands and cross-threads of the films that are not whole in the field F: {(film, member): why}. A member is whole when every point of its centre line is solid (within
    END_MM of an end: when the layer is within a voxel of it); a cross-thread also needs both its strands."""
    from scipy import ndimage

    solid = F.d < 0
    near = ndimage.binary_dilation(solid, structure=np.ones((3, 3, 3), dtype=bool))
    grid = (F.xs, F.ys, F.zs)

    def whole(ctrl):
        pts = of.sc.spline(ctrl, step=1.0)
        idx = np.array([np.round((pts[:, k] - grid[k][0]) / F.vox).astype(int) for k in range(3)]).T
        if not np.all((idx >= 0) & (idx < np.array(solid.shape))):
            return False
        cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
        end = (cum < END_MM) | (cum > cum[-1] - END_MM)
        at = (idx[:, 0], idx[:, 1], idx[:, 2])
        return bool(np.where(end, near[at], solid[at]).all())

    out = {}
    for fi, fm in enumerate(of.film_list(raw=True)):
        if not hasattr(fm, "probes"):
            continue
        n = [k for k, _pt, _len in fm.probes].count("strand")
        for m in range(2, len(fm)):
            if (fi, m) in DROP:
                continue
            if not whole(fm[m][1]):
                out[(fi, m)] = "strand cut" if m < 2 + n else "cross-thread cut"
        for j, who in enumerate(getattr(fm, "joins", ())):
            m = 2 + n + j
            if (fi, m) not in DROP and (fi, m) not in out and any((fi, w) in DROP or (fi, w) in out for w in who):
                out[(fi, m)] = "cross-thread on a strand that is out"
    return out


def layer_main(out_npz, strength=False):
    of, _whole = patch_layer()
    hware = hw.build_hardware()
    parts, _ = frame_v0.build_frame(hardware=hware)
    routes = cables.build_routes()
    fails = cables.failures(routes, cables.evaluate(routes, parts, hware))
    print("cables.py's own checks: " + ("pass" if not fails else f"{len(fails)} FAIL"))
    for _c, t in fails[:8]:
        print("   ", str(t)[:260])
    U, anchors, fields, info = of.build(parts, hware)
    for rnd in range(4):
        out = torn(of, fields["main"])
        films = of.film_list(raw=True)
        count = sum(len(fm) - 2 for fm in films if hasattr(fm, "probes"))
        why = {}
        for w in out.values():
            why[w] = why.get(w, 0) + 1
        print(f"build {rnd + 1}: strands and cross-threads of main's films {count - len(DROP)}; not whole {len(out)} {why if out else ''}"
              + ("" if not out else "; by film " + str({fi: sum(1 for k in out if k[0] == fi) for fi in sorted({k[0] for k in out})})), flush=True)
        if not out or not NO_TORN:
            break
        DROP.update(out)
        U, anchors, fields, info = of.build(parts, hware)
    else:
        print("members are still torn after 4 builds")
    from scipy import ndimage

    for piece, F in fields.items():
        if piece == "main":
            solid = F.d < 0
            ahead = solid[:, F.ys < hw.ENVELOPE_Y0, :]
            print(f"main in front of the front plane: {ahead.sum() * F.vox ** 3 / 1000.0:.1f} cm3, as far as Y {float(F.ys[np.where(solid.any(axis=(0, 2)))[0][0]]):.1f}")
            sl, (X, Y, Z) = F.block(np.array(of.bp(of.CARD_BONE_U + 1, of.CARD_BONE_N + 1, 0.0)) - 1.6, np.array(of.bp(of.CARD_BONE_U + 1, of.CARD_BONE_N + 1, 0.0)) + 1.6)
            print(f"the bone `card`'s centre line at X 0 is {'solid' if (F.d[sl] < 0).any() else 'NOT THERE'}")
        lab, n = ndimage.label(F.d < 0)
        sizes = sorted((ndimage.sum(F.d < 0, lab, index=np.arange(1, n + 1)) * F.vox ** 3 / 1000.0).tolist(), reverse=True)
        print(f"{piece}: {sum(sizes):.1f} cm3 in {n} bodies {[round(x, 1) for x in sizes[:4]]}")
    z = of.saved_arrays(U, anchors, fields, parts, info)
    np.savez(out_npz, **z)
    print("saved", out_npz)
    _lines, layer_fails = of.check(U, anchors, parts, hware, info["lines"], z)
    print(f"organic_frame's own checks: {'pass' if not layer_fails else str(len(layer_fails)) + ' FAIL'}")
    for t in layer_fails[:12]:
        print("   ", str(t)[:300])
    # the bone's front against the front plane, and the room under it at the connector
    C = math.sqrt(0.5)
    cn = of.CARD_BONE_N + 1.0
    cu, r_mid, r_end = of.CARD_BONE_U + 1.0, of.BONE_R["card"][1], of.BONE_R["card"][0]
    print(f"the bone `card`: centre line u {cu:.1f}, n {cn:.1f} at the middle (the fans' plane u {hw.GPU_BS[2]:g}, the card's top n {hw.GPU_BS[5]:g}, the socket u {GS['u']:g}); "
          f"its back {hw.GPU_BS[2] - (cu + r_mid):.1f} mm in front of the fans' plane; world Y {60 + (cu - cn) * C:.1f}, Z {30 + (cu + cn) * C:.1f}; "
          f"its front at Y {60 + (cu - cn) * C - r_mid:.1f} at the middle and Y {60 + (cu - cn) * C - r_end:.1f} at the ends (the front plane Y {hw.ENVELOPE_Y0:g})")
    if strength:
        strength_main(out_npz)


def strength_main(field):
    """organic_strength.py's run of `main` on a sketch's saved field: the surface pushes, the own weight, and a 30 N push on every strand and cross-thread."""
    load_of()
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

    patch_cable()
    sys.argv = [rb.__file__, "--src", os.path.join(ROOT, "cad_b6"), "--out", out_dir, "--field", field]
    rb.main()


if __name__ == "__main__":
    if sys.argv[1] == "export":
        export_main(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "strength":
        strength_main(sys.argv[2])
    elif sys.argv[1] == "route":
        nums = [float(a) for a in sys.argv[2:]]
        route_main([tuple(nums[i:i + 4]) for i in range(0, len(nums), 4)] or [UNDER])
    else:
        layer_main(sys.argv[2], strength="--strength" in sys.argv)
