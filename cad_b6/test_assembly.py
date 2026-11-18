#!/usr/bin/env python3
"""Tests of assembly_access.py: the measurement on small synthetic solids (a free length and its obstacle, a thin wire, a solid beside the corridor, a head in its own
counterbore, the seat of a class B screw on a stepped bore), the reachability and the search on hand-made tables (the L-key's sector, two joints that cover each other,
a joint that blocks itself, a unit's solids arriving together, the drives' order, backtracking, an order changed by hand, the cap), and on the real model the screw
counts and the cross-checks that must fail (a changed count in the bill, a row without an entry, a hardware key in no list).

    .venv/bin/python cad_b6/test_assembly.py          # about a minute and a half (the real model is built once, its screws listed four times); exit status 1 on a failure
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cadquery as cq  # noqa: E402

import assembly_access as aa  # noqa: E402
import frame_v0  # noqa: E402
import hardware as hw  # noqa: E402

RESULTS = []
EXPECTED_CASES = 51


def expect(name, got, want):
    RESULTS.append(got == want)
    print(f"{'PASS' if got == want else 'FAIL'}  {name}\n      expected: {want}\n      got:      {got}")


def box(x0, x1, y0, y1, z0, z1):
    return cq.Solid.makeBox(x1 - x0, y1 - y0, z1 - z0, cq.Vector(x0, y0, z0))


def socket_screw(seat=(0.0, 0.0, 0.0), length=10.0):
    """An M3 socket head with its washer on a seat at `seat`, the head pointing along +Z."""
    return dict(seat=seat, e=(0.0, 0.0, 1.0), head="socket", head_d=hw.M3_HEAD_D, head_h=hw.M3_HEAD_H, washer_t=hw.M3_WASHER_T, length=length)


def screw(sid, members, **tools):
    return dict(id=sid, members=frozenset(members), tools={t: frozenset(b) if not isinstance(b, dict) else b for t, b in tools.items()})


def units(*nodes, **groups):
    out = {n: frozenset({n}) for n in nodes}
    out.update({n: frozenset(s) for n, s in groups.items()})
    return out


def lkey_with_free(degrees, start=0):
    """An L-key whose long arm is free in the directions from `start` over `degrees` (inclusive) and blocked by the wall 'w' everywhere else."""
    n = int(round(360 / aa.LKEY_STEP_DEG))
    free = {int(round((start + k * aa.LKEY_STEP_DEG) / aa.LKEY_STEP_DEG)) % n for k in range(int(round(degrees / aa.LKEY_STEP_DEG)) + 1)}
    return dict(base=frozenset(), dirs=tuple(frozenset() if k in free else frozenset({"w"}) for k in range(n)), step=aa.LKEY_STEP_DEG)


def geometry():
    s = socket_screw()
    top = hw.M3_WASHER_T + hw.M3_HEAD_H
    always = lambda tools: True      # noqa: E731
    # a block 40 mm in front of the head, beyond the L-key's reach (its long arm stands LKEY_SHORT from the top of the head)
    block = {"block": box(-5, 5, -5, 5, top + 40.0, top + 50.0)}
    got = aa.screw_tools(s, block, always)
    length, name = got["raw"][0]
    expect("a block 40 mm in front of the head: the free length of the head's corridor is 40 within 0.1 and names the block", (abs(length - 40.0) <= 0.1, name), (True, "block"))
    expect("the same block blocks the straight driver", "block" in got["tools"]["straight"], True)
    expect("the same block does not block the L-key (it stands beyond the key's reach)", aa.tool_status(got["tools"]["lkey"], frozenset(block), frozenset(block)), "free")
    near = {"near": box(-5, 5, -5, 5, top + 10.0, top + 15.0)}
    expect("a block 10 mm in front of the head blocks the L-key's short arm", aa.tool_status(aa.screw_tools(s, near, always)["tools"]["lkey"], frozenset(near), frozenset(near)), "blocked")
    wire = {"wire": cq.Solid.makeCylinder(0.5, 40.0, cq.Vector(-20.0, 0.0, top + 30.0), cq.Vector(1, 0, 0))}
    expect("a 1 mm wire across the corridor 30 mm in front of the head blocks the straight driver", "wire" in aa.screw_tools(s, wire, always)["tools"]["straight"], True)
    beside = {"beside": box(hw.LKEY_LONG + 5, hw.LKEY_LONG + 25, -10, 10, -10, 200)}
    got = aa.screw_tools(s, beside, always)
    expect("a solid beside the corridors and beyond the L-key's swing is in no tool's way", (got["tools"]["straight"], got["tools"]["lkey"]["base"], set().union(*got["tools"]["lkey"]["dirs"])),
           (frozenset(), frozenset(), set()))
    # a head and its washer in their own counterbore (frame_v0's M3 counterbore: Ø M3_CB_D, M3_CB_DEPTH deep), the clearance bore below
    part = box(-15, 15, -15, 15, -10, frame_v0.M3_CB_DEPTH)
    part = part.cut(frame_v0.cyl((0, 0, 0), (0, 0, 1), frame_v0.M3_CB_D, frame_v0.M3_CB_DEPTH + 1)).cut(frame_v0.cyl((0, 0, -11), (0, 0, 1), hw.M3_CLEAR_D, 12))
    got = aa.screw_tools(s, {"own": part}, always)
    expect("a head in its own counterbore: its part blocks neither the insertion, nor the straight driver, nor the L-key's short arm",
           (got["insert"], got["tools"]["straight"], got["tools"]["lkey"]["base"]), (frozenset(), frozenset(), frozenset()))
    # class B: a plate on a hardware box, a 6-32 stepped bore from the plate's free face (frame_v0.stepped_bore: a counterbore leaving HW_SCREW_FLOOR under the head)
    thread = box(-30, 30, -30, 30, -30, 0)
    cb, bore = frame_v0.stepped_bore((0.0, 0.0, 6.0), (0.0, 0.0, -1.0), 6.0)
    plate = box(-20, 20, -20, 20, 0, 6).cut(cb.solid).cut(bore.solid)
    seat, e, stack = aa.class_b_seat(bore, thread, [plate], hw.UNC6_HEAD_D)
    expect(f"class B on a stepped bore: the seat is the counterbore's floor, {frame_v0.HW_SCREW_FLOOR:g} above the thread's face within 0.05, and the head points away from the thread",
           (abs(seat[2] - frame_v0.HW_SCREW_FLOOR) <= 0.05, abs(stack - frame_v0.HW_SCREW_FLOOR) <= 0.05, tuple(round(float(c), 6) for c in e)), (True, True, (0.0, 0.0, 1.0)))
    # a pan head in that counterbore: the stubby's blade is as thin as the head's corridor, so the screw's own part is in no tool's way (one 30 mm cylinder from the head would be)
    pan = dict(seat=tuple(float(c) for c in seat), e=(0.0, 0.0, 1.0), head="pan", head_d=hw.UNC6_HEAD_D, head_h=hw.UNC6_HEAD_H, washer_t=0.0, length=hw.PSU_SCREW_LEN)
    got = aa.screw_tools(pan, {"own": plate}, always)
    expect("a pan head in its own counterbore: its part blocks neither the insertion, nor the straight driver, nor the stubby",
           (got["insert"], got["tools"]["straight"], got["tools"]["stubby"]), (frozenset(), frozenset(), frozenset()))
    # beside the axis: outside the head's corridor, inside the handle's radius, at the handle's height (a handle no wider than its blade would miss it)
    low = {"low": box(hw.UNC6_HEAD_D, hw.STUBBY_D / 2 - 1.0, -3, 3, 6.0 + hw.STUBBY_BLADE, 6.0 + hw.STUBBY_BLADE + 5.0)}
    got = aa.screw_tools(pan, low, always)
    expect("a block beside the axis at the stubby's handle blocks the stubby and not the straight driver's thin shaft", ("low" in got["tools"]["stubby"], "low" in got["tools"]["straight"]), (True, False))
    fan = box(-30, 30, -30, 30, 6, 31)
    seat, e, stack = aa.class_b_seat(frame_v0.clear_hole("6-32c", (0, 0, 6.5), (0, 0, -1), 7.0), thread, [box(-20, 20, -20, 20, 0, 6).cut(frame_v0.cyl((0, 0, -1), (0, 0, 1), hw.UNC6_CLEAR_D, 8)), fan],
                                     hw.UNC6_HEAD_D)
    expect("class B through a plate and a fan (the 420): the seat is the fan's outer face, 31 above the thread's face within 0.05", abs(seat[2] - 31.0) <= 0.05, True)


def tables():
    hard = frozenset({"A", "B", "C", "w", "dimms", "rad360", "d35", "plugs", "rib", "sled"})
    expect("an L-key with 55 degrees of free sector fails", aa.tool_status(lkey_with_free(55), frozenset({"w"}), hard), "blocked")
    expect(f"an L-key with exactly {hw.LKEY_SWING_DEG:g} degrees of free sector passes", aa.tool_status(lkey_with_free(hw.LKEY_SWING_DEG), frozenset({"w"}), hard), "free")
    expect("an L-key with 65 degrees of free sector passes", aa.tool_status(lkey_with_free(65), frozenset({"w"}), hard), "free")
    expect("an L-key with 65 degrees free across direction 0 (330 to 35) passes", aa.tool_status(lkey_with_free(65, start=330), frozenset({"w"}), hard), "free")
    expect("an L-key whose wall is not installed is free", aa.tool_status(lkey_with_free(0), frozenset(), hard), "free")

    # two joints that cover each other: no order
    sc = [screw("s1", {"A"}, straight={"B"}), screw("s2", {"B"}, straight={"A"})]
    fails, res = aa.judge(sc, units("A", "B"), ["A", "B"], hard)
    expect("two joints that cover each other: every order was tried, and the run fails", (res["search"]["status"], any("no order: every order was tried" in f for f in fails)), ("exhausted", True))
    fails, res = aa.judge(sc, units("A", "B"), ["A", "B"], hard, cap=1)
    expect("a search stopped by its cap says so, not that every order was tried", (res["search"]["status"], any("within the cap" in f for f in fails),
                                                                                     any("no order: every order was tried" in f for f in fails)), ("cap", True, False))

    # a joint that blocks itself: a hard solid of a member's unit fails before the search; a soft one is a "needs a look"
    u = units("P", board={"board", "dimms", "atx24"})
    fails, res = aa.judge([screw("s", {"P", "board"}, straight={"dimms"}, lkey={"dimms"})], u, ["P", "board"], hard)
    expect("a hard blocker in the screw's own joint (the DIMMs, in the board's unit) fails before the search", ([sid for sid, _ in res["own"]], any("its own joint" in f for f in fails)), (["s"], True))
    fails, res = aa.judge([screw("s", {"P", "board"}, straight={"atx24"})], u, ["P", "board"], hard)
    expect("a soft one (the 24-pin plug) is no failure and the screw needs a look", (fails, [x[0] for x in res["look"]]), ([], ["s"]))

    # a unit's solids arrive together: the 360 comes with the CPU block's unit, so the part it covers must go on first
    u = units("part", cpu_aio={"cpu_block", "rad360"})
    sc = [screw("x", {"part"}, straight={"rad360"})]
    res = aa.search(sc, u, ["cpu_aio", "part"], hard)
    expect("a unit's solids arrive together: a part the 360 covers goes on before the CPU unit, although the CPU block itself is in nobody's way", res["order"], ["part", "cpu_aio"])
    expect("and the order the preference asks for is refused, naming the 360", any("rad360" in p for p in aa.check_order(["cpu_aio", "part"], sc, u, hard)), True)
    # the drives: the 2.5 inch drive's screws stand under the 3.5 inch drive
    u = units("sled", d25={"d25"}, d35={"d35", "plugs"})
    sc = [screw(f"m3 {k}", {"sled", "d25"}, straight={"d35"}, stubby={"plugs", "d35"}) for k in range(4)] + [screw(f"6-32 {k}", {"sled", "d35"}, straight=set()) for k in range(6)]
    res = aa.search(sc, u, ["sled", "d35", "d25"], hard)
    expect("the 2.5 inch drive goes on before the 3.5 inch one, against the preference", res["order"], ["sled", "d25", "d35"])
    expect("its four screws are driven at its own step", [len(d) for _, d in aa.steps_of(res["order"], sc, u, hard)], [0, 4, 6])

    # a screw is judged with its own joint in: the stubby in the sled's own counterbore gives the rib no licence to go on before the screw's joint is complete
    u = units("rib", "sled", d25={"d25"})
    sc = [screw("m3", {"sled", "d25"}, straight={"rib"}, stubby={"sled"})]
    bad = aa.check_order(["rib", "sled", "d25"], sc, u, hard)
    expect("a cover is refused as soon as it is certain: the rib at step 1, not when the sled's counterbore arrives at step 2", bad[0].startswith("step 1 (rib)"), True)
    expect("and the search puts the rib last", aa.search(sc, u, ["rib", "sled", "d25"], hard)["order"], ["sled", "d25", "rib"])

    # backtracking: A first leaves no node that may follow, and is replaced
    sc = [screw("s1", {"B"}, straight={"A"}, stubby={"C"}), screw("s2", {"C"}, straight={"B"})]
    u = units("A", "B", "C")
    res = aa.search(sc, u, ["A", "B", "C"], hard)
    expect("the search goes back: A first is a dead end (B then buries s2, C then buries s1), and C, B, A is found", (res["status"], res["order"]), ("found", ["C", "B", "A"]))
    expect("it visited more states than the order's three steps", res["states"] > 3, True)
    expect("the found order is valid by check_order", aa.check_order(res["order"], sc, u, hard), [])
    bad = aa.check_order(["C", "A", "B"], sc, u, hard)
    expect("the order changed by hand (A before B: the 2nd step covers s1 before its joint is complete) is rejected by the same rule", (len(bad) > 0, "s1" in " ".join(bad)), (True, True))
    expect("reachable() lists the tools no installed hard solid blocks: with A in, s1 only by the stubby", aa.reachable(sc[0], frozenset({"A"}), hard), ["stubby"])

    # the search prefers a node that a screw ties to what is in
    sc = [screw("ab", {"A", "B"}, straight=set()), screw("bc", {"B", "C"}, straight=set())]
    res = aa.search(sc, units("A", "B", "C"), ["A", "C", "B"], hard)
    expect("a node tied to what is installed goes before one that would stand loose: A, B, C against the preference A, C, B, and the order is valid",
           (res["order"], aa.loose_nodes(res["order"], sc, units("A", "B", "C")), aa.check_order(res["order"], sc, units("A", "B", "C"), hard)), (["A", "B", "C"], [], []))
    # a node that sits on another goes on after it, whatever the preference says
    res = aa.search([], units("X", "Y"), ["X", "Y"], hard, needs={"X": ("Y",)})
    expect("a node that sits on another goes on after it, against the preference", res["order"], ["Y", "X"])
    expect("and the order that puts it first is refused, naming what it sits on", aa.check_order(["X", "Y"], [], units("X", "Y"), hard, needs={"X": ("Y",)}), ["step 1 (X): it sits on Y, which is not in yet"])

    # a check 15 row that measured nothing carries a sentence where the clamped names should be: it names no member, and does not crash
    note = frame_v0.Hole("M3", (0.0, 0.0, 0.0), (0.0, 0.0, -1.0), 2.2, 6.7, 1.6, True)
    arm = frame_v0.Part("arm", None, "", blank=box(-5, 5, -5, 5, 0, 4))
    expect("a check 15 row whose clamped names are its own note beside a real part gives that part and no more",
           (aa.joint_members(note, dict(stack=5.0, what=["not measured here"]), [], {}), aa.joint_members(note, dict(stack=5.0, what=["not measured here", "arm"]), [arm], {})), (set(), {"arm"}))

    # a bench group: the arm is screwed to the radiator off the case, where the frame is not in the driver's way; in the case the pair goes on as one node, after the frame
    sc = [screw("s", {"arm", "rad"}, straight={"frame"}), screw("j", {"arm", "neck"}, straight=set()), screw("f", {"frame", "neck"}, straight=set())]
    u = units("frame", "neck", "arm", "rad")
    fails, res = aa.judge(sc, u, ["frame", "arm", "neck", "rad"], frozenset(u))
    expect("without a bench group the arm and the radiator must go on before the frame", (fails, res["search"]["order"]), ([], ["arm", "neck", "rad", "frame"]))
    fails, res = aa.judge_with_bench(sc, u, ["frame", "arm", "neck", "rad"], frozenset(u), {"sub": ("arm", "rad")})
    expect("with the pair as a bench group: s is driven on the bench; in the case the group stands at its last member's place (frame, neck, sub), f is driven at the neck and j at the group; s is listed as covered later by the frame",
           (fails, [(g, [(n, [d[0] for d in drv]) for n, drv in steps]) for g, steps, _ in res["bench"]], [(n, [d[0] for d in drv]) for n, drv in res["steps"]], [(e[0], e[3]) for e in res["early"]]),
           ([], [("sub", [("arm", []), ("rad", ["s"])])], [("frame", []), ("neck", ["f"]), ("sub", ["j"])], [("s", ["frame"])]))
    # a member of the group that goes on after a bench screw and covers it is named among the screw's covers; a member no screw holds is reported; a soft blocker on the bench needs a look
    u3 = units("neck", "arm", "rad", "lid", "hose")
    sc3 = [screw("s", {"arm", "rad"}, straight={"lid", "neck"}), screw("t", {"arm", "rad"}, straight={"hose"})]
    fails, res = aa.judge_with_bench(sc3, u3, ["neck", "arm", "rad", "hose", "lid"], frozenset({"neck", "arm", "rad", "lid"}), {"sub": ("arm", "rad", "hose", "lid")})
    expect("a bench screw's covers name the group's own later member (the lid) and the neck; the lid, held by no screw, is reported loose; no failure",
           (fails, [(e[0], e[3]) for e in res["early"]], [x for _, _, loose in res["bench"] for x in loose if x[0] == "lid"]), ([], [("s", ["neck", "sub"])], [("lid", None)]))
    fails, res = aa.judge_with_bench(sc3, u3, ["neck", "hose", "arm", "rad", "lid"], frozenset({"neck", "arm", "rad", "lid"}), {"sub": ("hose", "arm", "rad", "lid")})
    expect("a screw driven on the bench past a soft solid of its group is listed under needs a look", [(x[0], x[1]) for x in res["look"]], [("t", "straight")])
    # the group sits on what its members sit on
    fails, res = aa.judge_with_bench(sc, units("frame", "neck", "arm", "rad", "board"), ["frame", "neck", "arm", "rad", "board"], frozenset(u), {"sub": ("arm", "rad")}, needs={"rad": ("board",)})
    expect("a bench group sits on what its members sit on: the board goes on before the group, against the preference", (fails, res["search"]["order"]), ([], ["frame", "neck", "board", "sub"]))
    bad = [screw("s", {"arm", "rad"}, straight={"rad"})]
    fails, _ = aa.judge_with_bench(bad, units("arm", "rad"), ["arm", "rad"], frozenset({"arm", "rad"}), {"sub": ("arm", "rad")})
    expect("a screw its own group blocks on the bench fails the run and says where", any("on the bench (sub)" in f and "its own joint" in f for f in fails), True)
    fails, _ = aa.judge_with_bench(sc, u, ["frame", "neck", "arm", "rad"], frozenset(u), {"sub": ("arm", "gone")})
    expect("a bench group that names a missing node fails the run", any("bench group sub names gone" in f for f in fails), True)

    # loose nodes: a node that no screw ties to what is already in
    sc = [screw("ab", {"A", "B"}), screw("bc", {"B", "C"})]
    expect("loose nodes: C after A with nothing between them stands loose until B", aa.loose_nodes(["A", "C", "B"], sc, units("A", "B", "C")), [("C", "B")])


def real_model():
    hardware = hw.build_hardware()
    parts, _ = frame_v0.build_frame(hardware=hardware)
    fast = [dict(r) for r in frame_v0.FASTENERS]
    model, fails = aa.model_of(parts, hardware, fast)
    n = {c: sum(1 for s in model["screws"] if s["cls"] == c) for c in "AB"}
    expect("the real model: 90 class A and 30 class B screws, 2 placeholders and 16 organic pads counted", (n["A"], n["B"], len(model["placeholder"]), len(model["organic"])), (90, 30, 2, 16))
    expect("every row of the bill is accounted for and nothing else fails", fails, [])
    expect("every class A and class B screw is picked by one row", sum(1 for s in model["screws"] if s.get("row") is None), 0)
    groups = {}
    for s in model["screws"]:
        if s["cls"] == "B":
            groups.setdefault(s["group"], []).append(round(s["stack"], 2))
    want = {"psu": frame_v0.HW_SCREW_FLOOR, "rad360": frame_v0.HW_SCREW_FLOOR, "drive_left_35": frame_v0.SLED_FLOOR, "drive_left_25": frame_v0.SLED_FLOOR}
    expect("class B seats measured on the solids: the floors of the PSU's and the 360's counterbores, and of the sled's anonymous ones",
           {g: all(abs(x - w) <= 0.05 for x in groups[g]) for g, w in want.items()}, {g: True for g in want})
    fan_t = hw.RAD420_FAN_U[1] - hw.RAD420_FAN_U[0]
    expect(f"the 420's screws clamp the plate and the fan to its outer face ({frame_v0.ANTLER_T:g} + {fan_t:g})",
           all(abs(x - (frame_v0.ANTLER_T + fan_t)) <= 0.05 for x in groups["rad420"]), True)
    changed = [dict(r, count=r["count"] - 1) if r["item"] == "board" else r for r in fast]
    _, f = aa.model_of(parts, hardware, changed)
    expect("a FASTENERS row with a changed count (board 8) makes the script fail", any("'board' counts 8" in x for x in f), True)
    bill = {k: v for k, v in aa.BILL.items() if k != "neck pad"}
    _, f = aa.model_of(parts, hardware, fast, bill=bill)
    expect("a row removed from the script's table (neck pad) makes the script fail, twice: the row is judged by nobody and its screws by no row",
           (any("'neck pad' has no entry" in x for x in f), any("picked by 0 rows" in x for x in f)), (True, True))
    lists = dict(aa.LISTS, hard=tuple(k for k in aa.HARD_HARDWARE if k != "dimms"))
    _, f = aa.model_of(parts, hardware, fast, lists=lists)
    expect("a hardware key removed from the lists (dimms) makes the script fail", any("dimms is in no list" in x for x in f), True)


def main():
    geometry()
    tables()
    real_model()
    if len(RESULTS) != EXPECTED_CASES:
        print(f"FAIL  {len(RESULTS)} cases ran, EXPECTED_CASES is {EXPECTED_CASES}")
        RESULTS.append(False)
    bad = RESULTS.count(False)
    print(f"\n{len(RESULTS) - bad}/{len(RESULTS)} as expected: {'PASS' if not bad else 'FAIL'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
