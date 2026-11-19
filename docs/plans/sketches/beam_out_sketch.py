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
BEAM_OUT = float(os.environ.get("SK_BEAM_OUT", 12.0))                            # the bone `card`'s centre line, this much farther from the card along n (the second try's route asks for n >= 180.4 at the socket; it was 169; the first try, straight 10 and bend 20 with the far leg at v 158.3, u 147.3, asked for 194.1 and was sketched with 25)
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


def of_card_n():
    import organic_frame as of

    return of.CARD_BONE_N + 1.0


def patch_layer():
    """organic_frame builds the bone `card` whole, BEAM_OUT farther out, the films with a window over the connector, and the plug's room under the bone."""
    import organic_frame as of

    patch_cable()
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

    of.film_list = film_list
    return of, whole


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
    from scipy import ndimage

    for piece, F in fields.items():
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
    print(f"the bone `card` over the socket: centre line n {cn:.1f} (the card's top {hw.GPU_BS[5]:g}, the plug's back {MOUTH_N + hw.GPU12V_PLUG:g}); "
          f"room under its 5 mm radius {cn - 5.0 - (MOUTH_N + hw.GPU12V_PLUG):.1f} mm above the plug's back; its front at Y {60 + (of.CARD_BONE_U + 1 - cn) * C - 5.0:.1f} (the front plane Y {hw.ENVELOPE_Y0:g})")
    if strength:
        import organic_strength as st

        st.FIELD = out_npz
        for piece in ("main",):
            out, fl, _arr, head = st.run_piece(piece, 1)
            print("\n".join(out[:8]))
            print(st.headline(head))
            print(f"{piece}: {'pass' if not fl else str(len(fl)) + ' FAIL'}")
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
    elif sys.argv[1] == "route":
        nums = [float(a) for a in sys.argv[2:]]
        route_main([tuple(nums[i:i + 4]) for i in range(0, len(nums), 4)] or [UNDER])
    else:
        layer_main(sys.argv[2], strength="--strength" in sys.argv)
