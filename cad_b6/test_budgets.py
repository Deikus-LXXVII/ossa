#!/usr/bin/env python3
"""Tests of check_budgets.py: each budget exceeded fails, a figure inside its margin passes, the wall time only warns,
a missing input (no field, no suite record, a record of a failed or serial run) fails instead of passing, a figure under
half its record fails (a wrong input, not a saving), the suite's record is refused when it is of other code (its digest),
short of the pinned number of cases or half written, and --write records no figure that fails a hard limit.

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


def suite_file(path, n_cases=3, sections=(("prelude", 1), ("a", 2)), sources=None, digest=None, **over):
    """A clean fast record at `path` whose digest matches the working tree (hardware.py and this file as they are now), unless told otherwise."""
    if sources is None:
        sources = {r: cb.sr.file_sha(os.path.join(cb.ROOT, r)) for r in ("cad_b6/hardware.py", "cad_b6/test_budgets.py")}
    rec = dict(mode="fast", errors=[], short=[], counts=dict(BUDGETS["suite"]["counts"]), passed=n_cases, total=n_cases, wall_s=500.0, finished="t", workers=8,
               sources=sources, digest=cb.sr.digest(sources) if digest is None else digest,
               sections=[dict(title=t, n_cases=n) for t, n in sections], cases=[dict(name=f"c{k}", ok=True, expected="", reported="") for k in range(n_cases)])
    rec.update(over)
    with open(path, "w") as fh:
        json.dump(rec, fh)
    return path


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

    # a figure under half its record is a wrong input, not a saving: it fails, alone
    for key, n in BUDGETS["suite"]["counts"].items():
        expect(f"suite: {key} 0 against {n} recorded: fails (a wrong input)", only(verdicts(figures(suite=suite_with(**{key: 0}))), f"test suite, {key}", cb.FAIL), True)
    expect("suite: frame_builds 9 against 20 recorded (under half): fails", only(verdicts(figures(suite=suite_with(frame_builds=9))), "test suite, frame_builds", cb.FAIL), True)
    expect("suite: frame_builds 10 against 20 recorded (half): passes", only(verdicts(figures(suite=suite_with(frame_builds=10))), "test suite, frame_builds", cb.PASS), True)
    expect("organic layer of 0 cm3: the ratchet fails (a wrong input), the stock passes", only(verdicts(figures(organic_cm3=0.0)), "organic layer, ratchet", cb.FAIL), True)
    expect("organic layer under half its record (849 cm3 against 1700): fails", only(verdicts(figures(organic_cm3=849.0)), "organic layer, ratchet", cb.FAIL), True)
    expect("skeleton of 0 g: the ratchet fails (a wrong input)", only(verdicts(figures(skeleton_abs_g=0.0)), "skeleton ABS, ratchet", cb.FAIL), True)
    expect("the failure under half says it is a wrong input", "wrong input" in next(r[7] for r in cb.judge(figures(organic_cm3=0.0), BUDGETS, ABS_STOCK, RHO) if r[1] == "organic layer, ratchet"), True)
    # small counts: the limit is n x 1.1 rounded down, and the line says so
    expect("count limits: 9 allows 9, 2 allows 2, 20 allows 22, 122 allows 134", [cb.count_limit(n, 0.1) for n in (9, 2, 20, 122)], [9, 2, 22, 134])
    small = dict(BUDGETS, suite=dict(BUDGETS["suite"], counts=dict(BUDGETS["suite"]["counts"], frame_builds=9)))
    expect("9 frame builds recorded, 10 run: fails", only(verdicts(figures(suite=suite_with(frame_builds=10)), small), "test suite, frame_builds", cb.FAIL), True)
    expect("the line of a count states its rounded limit", "limit 9 (+ 10 % rounded down)" in next(r[7] for r in cb.judge(figures(suite=suite_with(frame_builds=9)), small, ABS_STOCK, RHO)
                                                                                                  if r[1] == "test suite, frame_builds"), True)

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

        # the suite's record must be of this code, whole, and written whole
        rec = os.path.join(tmp, "rec.json")
        got, why = cb.read_suite(suite_file(rec), pinned=3)
        expect("a clean, whole record whose digest matches the working tree is a figure", (got is not None, why), (True, None))
        stale = {"cad_b6/hardware.py": "0" * 64, "cad_b6/test_budgets.py": cb.sr.file_sha(os.path.join(cb.ROOT, "cad_b6/test_budgets.py"))}
        got, why = cb.read_suite(suite_file(rec, sources=stale), pinned=3)
        expect("a stale digest (hardware.py changed since the run): refused, and the reason says to rerun the suite",
               (got, "other code" in str(why) and "cad_b6/hardware.py changed" in str(why) and "rerun cad_b6/test_checks.py" in str(why)), (None, True))
        got, why = cb.read_suite(suite_file(rec, sources={"cad_b6/no_such_file.py": "0" * 64}), pinned=3)
        expect("a recorded file that is gone: refused", (got, "gone" in str(why)), (None, True))
        got, why = cb.read_suite(suite_file(rec, digest="f" * 64), pinned=3)
        expect("a digest that does not match the record's own list: refused", (got, "digest" in str(why)), (None, True))
        got, why = cb.read_suite(suite_file(rec, sources={}), pinned=3)
        expect("a record without a digest (written before digests): refused", (got, "digest" in str(why)), (None, True))
        got, why = cb.read_suite(suite_file(rec, n_cases=2, sections=(("prelude", 1), ("a", 1))), pinned=3)
        expect("too few cases (2, EXPECTED_CASES 3): refused", (got, "2 cases recorded, EXPECTED_CASES is 3" in str(why)), (None, True))
        got, why = cb.read_suite(suite_file(rec, sections=(("prelude", 1), ("a", 2), ("emptied", 0))), pinned=3)
        expect("a section that recorded no case: refused", (got, "section 'emptied' recorded no case" in str(why)), (None, True))
        got, why = cb.read_suite(suite_file(rec, short=["section 'x' recorded no case"]), pinned=3)
        expect("a record the suite itself marked short: refused", got, None)
        with open(suite_file(rec), encoding="utf-8") as fh:
            whole = fh.read()
        with open(rec, "w", encoding="utf-8") as fh:
            fh.write(whole[: len(whole) // 2])
        got, why = cb.read_suite(rec, pinned=3)
        expect("a half-written record: refused as unreadable", (got, "unreadable" in str(why)), (None, True))
        expect("EXPECTED_CASES is read from test_checks.py without importing it", isinstance(cb.sr.pinned_cases(), int) and cb.sr.pinned_cases() > 0, True)
        expect("by default the record is held to test_checks.py's EXPECTED_CASES", cb.read_suite(suite_file(rec))[0], None)
        # an atomic write: a write that fails half way leaves the previous file as it was, and no temporary file
        target = os.path.join(tmp, "atomic.json")
        cb.sr.write_json_atomic(target, dict(a=1))
        try:
            cb.sr.write_json_atomic(target, dict(a=2, b=object()))       # json.dump raises on the object, after writing part of the text
            raised = False
        except TypeError:
            raised = True
        with open(target) as fh:
            expect("a write that fails half way leaves the previous record whole and no temporary file", (raised, json.load(fh), sorted(os.listdir(tmp)).count("atomic.json"),
                   [n for n in os.listdir(tmp) if n.endswith(".tmp")]), (True, dict(a=1), 1, []))

        # --write never records a figure past a hard limit
        bw = os.path.join(tmp, "budgets_w.json")
        for label, fig, budgets in (("skeleton at 1801 g (over 90 % of 2 kg), its ratchet allowing it", figures(skeleton_abs_g=1801.0, suite_why=None), big),
                                    ("organic layer of 2840 cm3 (3607 g of PETG, over 90 % of 4 kg)", figures(organic_cm3=2840.0, suite_why=None), huge)):
            with open(bw, "w") as fh:
                json.dump(budgets, fh)
            try:
                cb.write(fig, budgets, bw, ABS_STOCK, RHO)
                why = None
            except SystemExit as e:
                why = str(e)
            with open(bw) as fh:
                expect(f"--write with the {label}: refused, budgets.json as it was", ("hard limit" in str(why), json.load(fh)), (True, budgets))
        cb.write(figures(suite_why=None), BUDGETS, bw, ABS_STOCK, RHO)
        with open(bw) as fh:
            expect("--write with every figure inside the hard limits records them", json.load(fh)["skeleton_abs_g"]["figure"], 1600.0)

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
