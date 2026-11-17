#!/usr/bin/env python3
"""Tests of check_budgets.py: each budget exceeded fails, a figure inside its margin passes, the wall time only warns,
and a missing input (no field, no suite record, a record of a failed or serial run) fails instead of passing.

    .venv/bin/python cad_b6/test_budgets.py          # a few seconds; builds no frame; exit status 1 on a failure
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_budgets as cb  # noqa: E402

RESULTS = []
BUDGETS = dict(skeleton_abs_g=dict(figure=1600.0, margin=0.02),
               organic_cm3=dict(figure=1700.0, margin=0.02, petg_stock_g=4000.0),
               suite=dict(counts=dict(frame_builds=20, run_checks=200, cable_routings=10), count_margin=0.10, wall_s=500.0, wall_margin=0.25))
ABS_STOCK, RHO = 2000.0, 1.27


def figures(**over):
    fig = dict(skeleton_abs_g=1600.0, organic_cm3=1700.0, suite=dict(counts=dict(frame_builds=20, run_checks=200, cable_routings=10), wall_s=500.0, finished="t", workers=8))
    fig.update(over)
    return fig


def verdicts(fig, budgets=BUDGETS):
    return {r[1]: r[0] for r in cb.judge(fig, budgets, ABS_STOCK, RHO)}


def expect(name, got, want):
    RESULTS.append(got == want)
    print(f"{'PASS' if got == want else 'FAIL'}  {name}\n      expected: {want}\n      got:      {got}")


def only(v, name, verdict):
    """The named budget has `verdict`, every other one passes."""
    return {k: x for k, x in v.items() if x != cb.PASS} == ({name: verdict} if verdict != cb.PASS else {})


def suite_with(**counts):
    return dict(counts=dict(BUDGETS["suite"]["counts"], **counts), wall_s=500.0, finished="t", workers=8)


def main():
    v = verdicts(figures())
    expect("the recorded figures pass every budget", set(v.values()), {cb.PASS})
    # each budget exceeded fails, alone
    expect("skeleton 2.1 % over its record: the ratchet fails", only(verdicts(figures(skeleton_abs_g=1600.0 * 1.021)), "skeleton ABS, ratchet", cb.FAIL), True)
    expect("skeleton 1.9 % over its record: inside the margin, passes", only(verdicts(figures(skeleton_abs_g=1600.0 * 1.019)), "skeleton ABS, ratchet", cb.PASS), True)
    big = dict(BUDGETS, skeleton_abs_g=dict(figure=1790.0, margin=0.02))
    expect("skeleton over 90 % of 2 kg (1801 g) with a ratchet that would allow it: the stock limit fails",
           only(verdicts(figures(skeleton_abs_g=1801.0), big), "skeleton ABS, stock", cb.FAIL), True)
    expect("skeleton at 1799 g, same ratchet: under the stock limit, passes", only(verdicts(figures(skeleton_abs_g=1799.0), big), "skeleton ABS, stock", cb.PASS), True)
    expect("organic layer 2.1 % over its record: the ratchet fails", only(verdicts(figures(organic_cm3=1700.0 * 1.021)), "organic layer, ratchet", cb.FAIL), True)
    expect("organic layer 1.9 % over its record: passes", only(verdicts(figures(organic_cm3=1700.0 * 1.019)), "organic layer, ratchet", cb.PASS), True)
    huge = dict(BUDGETS, organic_cm3=dict(figure=2900.0, margin=0.02, petg_stock_g=4000.0))
    expect("organic layer of 2840 cm3 (3607 g of PETG, over 90 % of 4 kg) with a ratchet that would allow it: the stock limit fails",
           only(verdicts(figures(organic_cm3=2840.0), huge), "organic layer, PETG stock", cb.FAIL), True)
    for key, n in BUDGETS["suite"]["counts"].items():
        over, inside = int(n * 1.1) + 1, int(n * 1.1)
        expect(f"suite: {key} {over} against {n} recorded (over 10 %): fails", only(verdicts(figures(suite=suite_with(**{key: over}))), f"test suite, {key}", cb.FAIL), True)
        expect(f"suite: {key} {inside} against {n} recorded (10 %): passes", only(verdicts(figures(suite=suite_with(**{key: inside}))), f"test suite, {key}", cb.PASS), True)
    slow = dict(suite_with(), wall_s=500.0 * 1.26)
    expect("suite 26 % slower than recorded: a warning, not a failure", only(verdicts(figures(suite=slow)), "test suite, wall time", cb.WARN), True)
    expect("suite 24 % slower: passes", only(verdicts(figures(suite=dict(suite_with(), wall_s=500.0 * 1.24))), "test suite, wall time", cb.PASS), True)
    expect("a count missing from the record fails (an operation the record no longer counts)",
           verdicts(figures(suite=dict(suite_with(), counts=dict(frame_builds=20, run_checks=200))))["test suite, cable_routings"], cb.FAIL)

    expect("a budget file with no counts recorded fails (nothing would gate the suite)",
           verdicts(figures(), dict(BUDGETS, suite=dict(BUDGETS["suite"], counts={})))["test suite, counts"], cb.FAIL)

    # missing inputs fail, through the files, and main() exits 1
    with tempfile.TemporaryDirectory() as tmp:
        nofield, nosuite = os.path.join(tmp, "field.npz"), os.path.join(tmp, "fast.json")
        expect("no field.npz: organic_cm3 is None", cb.organic_cm3(nofield), None)
        expect("no suite record: suite_record is None", cb.suite_record(nosuite), None)
        for label, rec in (("a failed run", dict(mode="fast", errors=[], counts={"run_checks": 1}, passed=285, total=286, wall_s=1.0)),
                           ("a serial run", dict(mode="serial", errors=[], counts={"run_checks": 1}, passed=286, total=286, wall_s=1.0)),
                           ("a run with an error", dict(mode="fast", errors=["x: boom"], counts={"run_checks": 1}, passed=286, total=286, wall_s=1.0))):
            with open(nosuite, "w") as fh:
                json.dump(rec, fh)
            expect(f"the record of {label} is not a figure", cb.suite_record(nosuite), None)
        os.remove(nosuite)
        v = verdicts(figures(organic_cm3=None, suite=None))
        expect("no field: both organic budgets fail", (v["organic layer, ratchet"], v["organic layer, PETG stock"]), (cb.FAIL, cb.FAIL))
        expect("no suite record: every suite budget fails, the wall time too", {k: x for k, x in v.items() if k.startswith("test suite")},
               {f"test suite, {k}": cb.FAIL for k in list(BUDGETS["suite"]["counts"]) + ["wall time"]})
        expect("no skeleton figure: both skeleton budgets fail", {k: x for k, x in verdicts(figures(skeleton_abs_g=None)).items() if x != cb.PASS},
               {"skeleton ABS, ratchet": cb.FAIL, "skeleton ABS, stock": cb.FAIL})
        bpath = os.path.join(tmp, "budgets.json")
        with open(bpath, "w") as fh:
            json.dump(BUDGETS, fh)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = cb.main(["--budgets", bpath, "--field", nofield, "--suite", nosuite], skeleton=lambda: 1600.0)
        expect("main() with no field and no suite record exits 1", code, 1)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                cb.main(["--write", "--budgets", bpath, "--field", nofield, "--suite", nosuite], skeleton=lambda: 1600.0)
            refused = False
        except SystemExit as e:
            refused = "refused" in str(e)
        with open(bpath) as fh:
            expect("--write with inputs missing is refused and leaves budgets.json as it was", (refused, json.load(fh)), (True, BUDGETS))
        expect("the output says which lines are gates and which a warning", "[gate]" in out.getvalue() and "[warning]" in out.getvalue(), True)

    bad = RESULTS.count(False)
    print(f"\n{len(RESULTS) - bad}/{len(RESULTS)} as expected: {'PASS' if not bad else 'FAIL'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
