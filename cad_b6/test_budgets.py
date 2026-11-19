#!/usr/bin/env python3
"""Tests of check_budgets.py: each budget exceeded fails, a figure inside its margin passes, the wall time only warns,
a missing input (no field, no suite record, a record of a failed or serial run) fails instead of passing, a figure under
its floor fails (a count under its record, a mass or a volume more than 5 % under it: a saving is recorded on purpose),
the suite's record is refused when it is of other code (its digest) or of other packages or another Python, short of the
pinned number of cases or half written, and --write records no figure that fails a hard limit or is under its floor
(unless --accept-lower). The strength run's record: more load cases than its limit fail, fewer than its record fail, a slow
run only warns, and a record of a quick run, of a failed run, of another field, of other probes or of another organic_strength.py
is refused; the record organic_strength.write_record writes is read back as the pieces' sums.

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
               suite=dict(counts=dict(frame_builds=20, run_checks=200, cable_routings=10), count_margin=0.10, wall_s=500.0, wall_margin=0.25),
               strength=dict(load_cases=600, count_margin=0.10, wall_s=1000.0, wall_margin=0.25))
PRINTS = dict(field=dict(grid=dict(shape=[4, 4, 4], first=[0.0, 0.0, 0.0], vox=1.5), main=dict(sha256="a" * 64, voxels=10), rear_panel=dict(sha256="b" * 64, voxels=5)),
              probes=dict(n=101, sha256="d" * 64), script="e" * 64)
ABS_STOCK, RHO = 2000.0, 1.27
ENV = cb.sr.environment({"cadquery", "numpy"})       # the interpreter running this test: cadquery and numpy as installed now


def figures(**over):
    fig = dict(skeleton_abs_g=1600.0, organic_cm3=1700.0, suite=dict(counts=dict(frame_builds=20, run_checks=200, cable_routings=10), wall_s=500.0, finished="t", workers=8),
               strength=dict(load_cases=600, wall_s=1000.0, finished="t"))
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


def suite_file(path, n_cases=3, sections=(("prelude", 1), ("a", 2)), sources=None, digest=None, env=ENV, **over):
    """A clean fast record at `path` whose digest matches the working tree (hardware.py and this file as they are now) and the interpreter, unless told otherwise."""
    if sources is None:
        sources = {r: cb.sr.file_sha(os.path.join(cb.ROOT, r)) for r in ("cad_b6/hardware.py", "cad_b6/test_budgets.py")}
    rec = dict(mode="fast", errors=[], short=[], counts=dict(BUDGETS["suite"]["counts"]), passed=n_cases, total=n_cases, wall_s=500.0, finished="t", workers=8,
               sources=sources, environment=env, digest=cb.sr.digest(sources, env) if digest is None else digest,
               sections=[dict(title=t, n_cases=n) for t, n in sections], cases=[dict(name=f"c{k}", ok=True, expected="", reported="") for k in range(n_cases)])
    rec.update(over)
    with open(path, "w") as fh:
        json.dump(rec, fh)
    return path


def strength_file(path, **over):
    """A record of a full strength run that passed on the field PRINTS, at `path`, unless told otherwise."""
    rec = dict(step=1, earlier=False, passed=True, finished="t", of=PRINTS,
               pieces=dict(main=dict(elements=10, unknowns=30, load_cases=495, probes_pushed=87, seconds=900.0),
                           rear_panel=dict(elements=5, unknowns=15, load_cases=105, probes_pushed=14, seconds=100.0)))
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
        over, inside = cb.count_limit(n, 0.1) + 1, cb.count_limit(n, 0.1)
        expect(f"suite: {key} {over} against {n} recorded (over its limit): fails", only(verdicts(figures(suite=suite_with(**{key: over}))), f"test suite, {key}", cb.FAIL), True)
        expect(f"suite: {key} {inside} against {n} recorded (its limit): passes", only(verdicts(figures(suite=suite_with(**{key: inside}))), f"test suite, {key}", cb.PASS), True)
    slow = dict(suite_with(), wall_s=500.0 * 1.26)
    expect("suite 26 % slower than recorded: a warning, not a failure", only(verdicts(figures(suite=slow)), "test suite, wall time", cb.WARN), True)
    expect("suite 24 % slower: passes", only(verdicts(figures(suite=dict(suite_with(), wall_s=500.0 * 1.24))), "test suite, wall time", cb.PASS), True)
    expect("a count missing from the record fails (an operation the record no longer counts)",
           verdicts(figures(suite=dict(suite_with(), counts=dict(frame_builds=20, run_checks=200))))["test suite, cable_routings"], cb.FAIL)

    # a figure under its floor fails, alone: a count under its record (the suite did less work), a mass or a volume more than 5 % under it
    for key, n in BUDGETS["suite"]["counts"].items():
        expect(f"suite: {key} 0 against {n} recorded: fails", only(verdicts(figures(suite=suite_with(**{key: 0}))), f"test suite, {key}", cb.FAIL), True)
        expect(f"suite: {key} {n - 1}, one under its recorded {n}: fails", only(verdicts(figures(suite=suite_with(**{key: n - 1}))), f"test suite, {key}", cb.FAIL), True)
        expect(f"suite: {key} {n}, exactly its record: passes", only(verdicts(figures(suite=suite_with(**{key: n}))), f"test suite, {key}", cb.PASS), True)
    expect("the failure of a count under its record says the suite did less work and how to record a saving that is meant",
           next(r[7] for r in cb.judge(figures(suite=suite_with(run_checks=199)), BUDGETS, ABS_STOCK, RHO) if r[1] == "test suite, run_checks").startswith(
               "under its recorded 200: the suite did less work than its record") and "--write --accept-lower" in next(
               r[7] for r in cb.judge(figures(suite=suite_with(run_checks=199)), BUDGETS, ABS_STOCK, RHO) if r[1] == "test suite, run_checks"), True)
    for label, key, rec_ in (("skeleton", "skeleton_abs_g", 1600.0), ("organic layer", "organic_cm3", 1700.0)):
        line = "skeleton ABS, ratchet" if key == "skeleton_abs_g" else "organic layer, ratchet"
        expect(f"{label} at 96 % of its record: passes", only(verdicts(figures(**{key: 0.96 * rec_})), line, cb.PASS), True)
        expect(f"{label} at exactly 95 % of its record (the floor): passes", only(verdicts(figures(**{key: 0.95 * rec_})), line, cb.PASS), True)
        expect(f"{label} at 94 % of its record: fails", only(verdicts(figures(**{key: 0.94 * rec_})), line, cb.FAIL), True)
        expect(f"{label} of 0: fails", only(verdicts(figures(**{key: 0.0})), line, cb.FAIL), True)
    expect("the failure of a mass under its floor says it is a wrong input until a saving is recorded on purpose",
           "wrong input" in next(r[7] for r in cb.judge(figures(organic_cm3=0.0), BUDGETS, ABS_STOCK, RHO) if r[1] == "organic layer, ratchet"), True)
    # the count's limit: n x 1.1 rounded down, never under n + 1, and the line says so
    expect("count limits: 0 allows 1, 2 allows 3, 6 allows 7, 9 allows 10, 12 allows 13, 20 allows 22, 122 allows 134",
           [cb.count_limit(n, 0.1) for n in (0, 2, 6, 9, 12, 20, 122)], [1, 3, 7, 10, 13, 22, 134])
    small = dict(BUDGETS, suite=dict(BUDGETS["suite"], counts=dict(BUDGETS["suite"]["counts"], frame_builds=9)))
    expect("9 frame builds recorded, 10 run (one more): passes", only(verdicts(figures(suite=suite_with(frame_builds=10)), small), "test suite, frame_builds", cb.PASS), True)
    expect("9 frame builds recorded, 11 run: fails", only(verdicts(figures(suite=suite_with(frame_builds=11)), small), "test suite, frame_builds", cb.FAIL), True)
    expect("the line of a count states its limit and floor", "recorded 9, limit 10 (the larger of + 1 and + 10 % rounded down), floor 9" in next(
        r[7] for r in cb.judge(figures(suite=suite_with(frame_builds=9)), small, ABS_STOCK, RHO) if r[1] == "test suite, frame_builds"), True)

    # the strength run: its load cases gate both ways, its wall time warns
    st = lambda **kw: figures(strength=dict(dict(load_cases=600, wall_s=1000.0, finished="t"), **kw))      # noqa: E731
    expect("strength run: 661 load cases against 600 recorded (over its limit 660): fails", only(verdicts(st(load_cases=661)), cb.STRENGTH_CASES, cb.FAIL), True)
    expect("strength run: 660 load cases (its limit): passes", only(verdicts(st(load_cases=660)), cb.STRENGTH_CASES, cb.PASS), True)
    expect("strength run: 599 load cases, one under its recorded 600 (a probe lost): fails", only(verdicts(st(load_cases=599)), cb.STRENGTH_CASES, cb.FAIL), True)
    expect("the failure of load cases under their record says the run pushed less",
           "the run pushed less than its record" in next(r[7] for r in cb.judge(st(load_cases=599), BUDGETS, ABS_STOCK, RHO) if r[1] == cb.STRENGTH_CASES), True)
    expect("strength run 26 % slower than recorded: a warning, not a failure", only(verdicts(st(wall_s=1260.0)), "strength run, wall time", cb.WARN), True)
    expect("strength run 24 % slower: passes", only(verdicts(st(wall_s=1240.0)), "strength run, wall time", cb.PASS), True)
    expect("no strength record: both strength budgets fail, the wall time too", {k: x for k, x in verdicts(figures(strength=None)).items() if x != cb.PASS},
           {cb.STRENGTH_CASES: cb.FAIL, "strength run, wall time": cb.FAIL})

    expect("a budget file with no counts recorded fails (nothing would gate the suite)",
           verdicts(figures(), dict(BUDGETS, suite=dict(BUDGETS["suite"], counts={})))["test suite, counts"], cb.FAIL)

    # missing inputs fail, through the files, and main() exits 1
    with tempfile.TemporaryDirectory() as tmp:
        nofield, nosuite, nostrength = os.path.join(tmp, "field.npz"), os.path.join(tmp, "fast.json"), os.path.join(tmp, "no_strength.json")
        expect("no field.npz: organic_cm3 is None", cb.organic_cm3(nofield), None)
        expect("no suite record: suite_record is None", cb.suite_record(nosuite), None)
        for label, rec in (("a failed run", dict(mode="fast", errors=[], counts={"run_checks": 1}, passed=285, total=286, wall_s=1.0)),
                           ("a serial run", dict(mode="serial", errors=[], counts={"run_checks": 1}, passed=286, total=286, wall_s=1.0)),
                           ("a run with an error", dict(mode="fast", errors=["x: boom"], counts={"run_checks": 1}, passed=286, total=286, wall_s=1.0))):
            with open(nosuite, "w") as fh:
                json.dump(rec, fh)
            expect(f"the record of {label} is not a figure", cb.suite_record(nosuite), None)
        os.remove(nosuite)

        # the strength run's record must be of a full run that passed, on the field as it is now
        srec, sfield = os.path.join(tmp, "strength.json"), os.path.join(tmp, "sfield.npz")
        now = lambda _path: json.loads(json.dumps(PRINTS))      # noqa: E731
        got, why = cb.read_strength(srec, sfield, prints=now)
        expect("no strength record: not a figure, and the reason says to rerun", (got, "rerun cad_b6/organic_strength.py" in str(why)), (None, True))
        got, why = cb.read_strength(strength_file(srec), sfield, prints=now)
        expect("a record with no field to hold it against: refused", (got, "organic_frame.py" in str(why)), (None, True))
        open(sfield, "w").close()
        got, why = cb.read_strength(strength_file(srec), sfield, prints=now)
        expect("a full run that passed on the present field: its load cases are the pieces' sum, its time the pieces' own",
               (got, why), (dict(load_cases=600, wall_s=1000.0, finished="t"), None))
        got, why = cb.read_strength(strength_file(srec, earlier=True), sfield, prints=now)
        expect("a record that says the earlier model ran as well: the same figure", got, dict(load_cases=600, wall_s=1000.0, finished="t"))
        three = dict(main=dict(load_cases=495, seconds=900.0), rear_panel=dict(load_cases=105, seconds=100.0), **{"весь слой": dict(load_cases=321, seconds=980.0)})
        got, why = cb.read_strength(strength_file(srec, pieces=three), sfield, prints=now)
        expect("a record that holds the earlier model as a piece (not a piece of the field): refused", (got, "its pieces differ" in str(why)), (None, True))
        import organic_strength as ost
        heads = dict(main=dict(elements=10, unknowns=30, cases=495, probes_pushed=87, seconds=900.04), rear_panel=dict(elements=5, unknowns=15, cases=105, probes_pushed=14, seconds=99.96))
        ost.write_record(srec, 1, True, [], heads, PRINTS)
        got, why = cb.read_strength(srec, sfield, prints=now)
        expect("the record organic_strength.write_record writes for two pieces is read back as their sums", (got["load_cases"], got["wall_s"], why), (600, 1000.0, None))
        ost.write_record(srec, 1, False, ["main: ORGANIC_STRENGTH 1 of 320 pushes are over the allowable"], heads, PRINTS)
        got, why = cb.read_strength(srec, sfield, prints=now)
        expect("the record write_record writes for a run with a failure: refused", (got, "failed" in str(why)), (None, True))
        got, why = cb.read_strength(strength_file(srec, step=2), sfield, prints=now)
        expect("a record of a quick run (step 2): refused", (got, "step 2" in str(why)), (None, True))
        got, why = cb.read_strength(strength_file(srec, passed=False), sfield, prints=now)
        expect("a record of a run that failed its checks: refused", (got, "failed" in str(why)), (None, True))
        NOT_NOW = "not of the layer and the script as they are now"
        other = dict(PRINTS, field=dict(PRINTS["field"], main=dict(sha256="c" * 64, voxels=11)))
        got, why = cb.read_strength(strength_file(srec, of=other), sfield, prints=now)
        expect("a record of another field (main's mask differs): refused, the reason names the piece", (got, NOT_NOW + " (main differ" in str(why)), (None, True))
        got, why = cb.read_strength(strength_file(srec, of=dict(PRINTS, probes=dict(n=101, sha256="f" * 64))), sfield, prints=now)
        expect("a record of other probes (the same masks and pads): refused, the reason names the probes", (got, NOT_NOW + " (probes differ" in str(why)), (None, True))
        got, why = cb.read_strength(strength_file(srec, of=dict(PRINTS, script="0" * 64)), sfield, prints=now)
        expect("a record of another organic_strength.py (N_POINTS or PROBE_REACH may have changed): refused, the reason names the script",
               (got, NOT_NOW + " (script differ" in str(why)), (None, True))
        for label, of in (("does not say what it was a run of", None), ("names its field as a string", dict(PRINTS, field="main")), ("has no script digest", {k: v for k, v in PRINTS.items() if k != "script"})):
            got, why = cb.read_strength(strength_file(srec, of=of), sfield, prints=now)
            expect(f"a record that {label}: refused", (got, NOT_NOW in str(why)), (None, True))
        got, why = cb.read_strength(strength_file(srec, pieces=dict(main=dict(load_cases=495, seconds=900.0))), sfield, prints=now)
        expect("a record that lacks a piece of the field: refused", (got, "its pieces differ" in str(why)), (None, True))
        for label, over in (("step true", dict(step=True)), ("step 1.0", dict(step=1.0)), ("passed 1", dict(passed=1)),
                            ("a piece's load cases true", dict(pieces=dict(main=dict(load_cases=True, seconds=1.0), rear_panel=dict(load_cases=599, seconds=1.0)))),
                            ("a piece that is not an object", dict(pieces=dict(main=495, rear_panel=dict(load_cases=105, seconds=1.0)))),
                            ("pieces as a list", dict(pieces=[dict(load_cases=600, seconds=1.0)]))):
            got, why = cb.read_strength(strength_file(srec, **over), sfield, prints=now)
            expect(f"a record edited by hand to {label}: refused, not read as a figure", (got, why is not None), (None, True))
        with open(srec, "w") as fh:
            json.dump([1, 2], fh)
        got, why = cb.read_strength(srec, sfield, prints=now)
        expect("a record that is not an object: refused", (got, "unreadable" in str(why)), (None, True))
        got, why = cb.read_strength(strength_file(srec, pieces={}), sfield, prints=now)
        expect("a record with no piece: refused", (got, "no piece" in str(why)), (None, True))
        got, why = cb.read_strength(strength_file(srec, pieces=dict(main=dict(load_cases=0, seconds=1.0), rear_panel=dict(load_cases=105, seconds=1.0))), sfield, prints=now)
        expect("a record with a piece that solved no load case: refused", (got, "no load case" in str(why)), (None, True))

        def boom(_path):
            raise ValueError("no pieces")
        got, why = cb.read_strength(strength_file(srec), sfield, prints=boom)
        expect("a field that cannot be fingerprinted: refused", (got, "cannot be fingerprinted" in str(why)), (None, True))
        with open(srec, "w") as fh:
            fh.write('{"step": 1, "pas')
        got, why = cb.read_strength(srec, sfield, prints=now)
        expect("a half-written strength record: refused as unreadable", (got, "unreadable" in str(why)), (None, True))

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
        # the packages and the Python the record ran
        old_cq = dict(ENV, packages=dict(ENV["packages"], cadquery="0.0.1"))
        got, why = cb.read_suite(suite_file(rec, env=old_cq), pinned=3)
        expect("a record of another cadquery (0.0.1 then): refused, the reason names the package and both versions",
               (got, "other packages" in str(why) and f"cadquery 0.0.1 then, {ENV['packages']['cadquery']} now" in str(why)), (None, True))
        got, why = cb.read_suite(suite_file(rec, env=dict(ENV, packages=dict(ENV["packages"], no_such_distribution="1.0"))), pinned=3)
        expect("a record of a package not installed now: refused", (got, "no_such_distribution 1.0 then, not installed now" in str(why)), (None, True))
        got, why = cb.read_suite(suite_file(rec, env=dict(ENV, python="2.7.18")), pinned=3)
        expect("a record of another Python (2.7.18): refused", (got, "python 2.7.18 then" in str(why)), (None, True))
        got, why = cb.read_suite(suite_file(rec, env=None), pinned=3)
        expect("a record without the environment (written before this review): refused", (got, "packages" in str(why)), (None, True))
        rec_env = suite_file(rec)
        with open(rec_env, encoding="utf-8") as fh:
            tampered = json.load(fh)
        tampered["environment"]["packages"]["numpy"] = "0.0.1"
        with open(rec_env, "w", encoding="utf-8") as fh:
            json.dump(tampered, fh)
        got, why = cb.read_suite(rec_env, pinned=3)
        expect("a record whose environment was edited after its digest: refused by the digest", (got, "does not match" in str(why)), (None, True))
        expect("the environment found from a module name: OCP is cadquery-ocp's", "cadquery-ocp" in cb.sr.environment({"OCP"})["packages"], True)
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

        # --write never records a figure under its floor by accident
        def try_write(fig, accept_lower=False):
            with open(bw, "w") as fh:
                json.dump(BUDGETS, fh)
            try:
                new, low = cb.write(fig, BUDGETS, bw, ABS_STOCK, RHO, accept_lower=accept_lower)
                why = None
            except SystemExit as e:
                new, low, why = None, None, str(e)
            with open(bw) as fh:
                return why, json.load(fh), low
        why, now, _ = try_write(figures(organic_cm3=0.94 * 1700.0, suite_why=None))
        expect("--write with the organic layer at 94 % of its record: refused, says why and how, budgets.json as it was",
               ("under its floor" in str(why) and "organic layer, ratchet" in str(why) and "--accept-lower" in str(why), now), (True, BUDGETS))
        why, now, _ = try_write(figures(suite=suite_with(run_checks=199), suite_why=None))
        expect("--write with run_checks 199 against 200 recorded: refused, budgets.json as it was",
               ("test suite, run_checks 199 under its floor 200" in str(why), now), (True, BUDGETS))
        why, now, low = try_write(figures(organic_cm3=800.0, suite=suite_with(run_checks=199), suite_why=None), accept_lower=True)
        expect("--write --accept-lower with both: recorded, and the lower figures are named",
               (why, now["organic_cm3"]["figure"], now["suite"]["counts"]["run_checks"], sorted(x[0] for x in low)),
               (None, 800.0, 199, ["organic layer, ratchet", "test suite, run_checks"]))
        why, now, low = try_write(figures(organic_cm3=0.96 * 1700.0, suite_why=None))
        expect("--write with the organic layer at 96 % (inside its floor): recorded without the flag", (why, now["organic_cm3"]["figure"], low), (None, round(0.96 * 1700.0, 1), []))
        why, now, _ = try_write(figures(strength=dict(load_cases=599, wall_s=900.0, finished="t"), suite_why=None))
        expect("--write with 599 load cases against 600 recorded: refused, budgets.json as it was",
               ("strength run, load cases 599 under its floor 600" in str(why), now), (True, BUDGETS))
        why, now, low = try_write(figures(strength=dict(load_cases=330, wall_s=450.0, finished="t2"), suite_why=None), accept_lower=True)
        expect("--write --accept-lower with fewer load cases: the strength figures are recorded",
               (why, now["strength"]["load_cases"], now["strength"]["wall_s"], now["strength"]["recorded_from"], [x[0] for x in low]),
               (None, 330, 450.0, "full run of t2", [cb.STRENGTH_CASES]))
        why, now, _ = try_write(figures(strength=None, strength_why="no out/organic/strength.json", suite_why=None))
        expect("--write with no strength record: refused, says why, budgets.json as it was",
               ("input missing for strength" in str(why) and "no out/organic/strength.json" in str(why), now), (True, BUDGETS))
        why, now, _ = try_write(figures(suite=dict(suite_with(), counts=dict(frame_builds=20, run_checks=200)), suite_why=None))
        expect("--write with a record that lacks a count budgets.json holds: refused (the gate would be dropped)", ("no count 'cable_routings'" in str(why), now), (True, BUDGETS))

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
            code = cb.main(["--budgets", bpath, "--field", nofield, "--suite", nosuite, "--strength", nostrength], skeleton=lambda: 1600.0)
        expect("main() with no field, no suite record and no strength record exits 1", code, 1)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                cb.main(["--write", "--budgets", bpath, "--field", nofield, "--suite", nosuite, "--strength", nostrength], skeleton=lambda: 1600.0)
            refused = False
        except SystemExit as e:
            refused = "refused" in str(e)
        with open(bpath) as fh:
            expect("--write with inputs missing is refused and leaves budgets.json as it was", (refused, json.load(fh)), (True, BUDGETS))
        expect("the output says which lines are gates and which a warning", "[gate]" in out.getvalue() and "[warning]" in out.getvalue(), True)
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                cb.main(["--accept-lower", "--budgets", bpath, "--field", nofield, "--suite", nosuite, "--strength", nostrength], skeleton=lambda: 1600.0)
            code = 0
        except SystemExit as e:
            code = e.code
        expect("--accept-lower without --write is an error", code, 2)

    bad = RESULTS.count(False)
    print(f"\n{len(RESULTS) - bad}/{len(RESULTS)} as expected: {'PASS' if not bad else 'FAIL'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
