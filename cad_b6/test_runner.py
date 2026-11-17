#!/usr/bin/env python3
"""Tests of test_checks.py's runner, on a tiny fake suite (no frame is built).

Serial mode (test_checks.main --serial, in this process): a run that loses a section or records fewer cases than EXPECTED_CASES
fails, a section that records none fails, a run with more cases passes and says to raise the figure, --diff of two short runs
fails although their lists are identical, the record carries the digest of the code it ran and the versions of the packages,
a file whose hash moved between the start of the run and its end fails the run, and a run that dies leaves the previous record.

Fast mode (test_checks.main, worker processes): the pool runs test_checks._worker_task itself, the real function, in spawned
workers; a stand-in for WORKER_TASK only swaps the fake prelude and sections in before calling it (a spawned worker imports
the modules afresh and would otherwise run the real suite). Proved here: a section that raises in a worker fails the run, a worker
that dies (os._exit: the pool breaks) fails the run and names the sections lost, the sections run longest first by the previous
record's times while the output keeps their order, and the record's sources and packages are the union over the processes
(a module only a worker imported is in it).
Not proved here: the real prelude in a worker, the memory each worker holds and the default worker count, what the real
sections leave in the memo; the fast run of the real suite (test_checks.py, then --diff against a serial run) covers those.

    .venv/bin/python cad_b6/test_runner.py          # about 20 s (imports cadquery here and in each spawned worker, builds nothing); exit status 1 on a failure
"""
from __future__ import annotations

import contextlib
import functools
import io
import itertools
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_checks as tc  # noqa: E402

OUT: list[bool] = []


def expect(name, got, want):
    OUT.append(got == want)
    print(f"{'PASS' if got == want else 'FAIL'}  {name}\n      expected: {want}\n      got:      {got}")


def fake_prelude():
    tc.check("fake prelude", True, ("", ""))
    return None, None, None


_SEQ = itertools.count(1)       # per process: the order in which this process ran its sections


def section_of(n, title=""):
    """A fake section: n cases; None raises; "exit" kills the process (a worker's death); "import" imports a module of the project and a
    third-party package that the parent process has not loaded, then records one case."""
    def run(_hardware, _parts, _base):
        print(f"ran {title} as this process's section {next(_SEQ)}")
        if n is None:
            raise RuntimeError("a section that raises")
        if n == "exit":
            os._exit(3)
        if n == "import":
            import check_budgets  # noqa: F401
            import trimesh  # noqa: F401
            tc.check("case imported", True, ("", ""))
            return
        for k in range(n):
            tc.check(f"case {k}", True, ("", ""))
    return run


def fake_worker_task(plan, i):
    """WORKER_TASK in a spawned worker: put the fake prelude and sections in this process's test_checks (which imported the real ones), then run
    the real test_checks._worker_task."""
    if tc.prelude is not fake_prelude:
        tc.SECTIONS[:] = [(t, section_of(n, t)) for t, n in plan]
        tc.prelude = fake_prelude
    return tc._worker_task(i)


def run(sections, pinned, out, argv=("--serial",), previous=None, start_hashes=None):
    """test_checks.main on the fake sections [(title, number of cases)] with EXPECTED_CASES = pinned: (exit code, printed text, record).
    previous: the sections' times of an earlier fast run [(title, seconds)]; start_hashes: in place of START_HASHES."""
    saved = (list(tc.SECTIONS), tc.prelude, tc.EXPECTED_CASES, tc.WORKER_TASK, tc.OUT_DIR, tc.START_HASHES)
    tc.SECTIONS[:] = [(t, section_of(n, t)) for t, n in sections]
    tc.prelude, tc.EXPECTED_CASES = fake_prelude, pinned
    tc.WORKER_TASK = functools.partial(fake_worker_task, list(sections))
    tc.OUT_DIR = tempfile.mkdtemp(dir=os.path.dirname(out))             # where main looks for the previous fast record
    if previous is not None:
        tc.sr.write_json_atomic(os.path.join(tc.OUT_DIR, "fast.json"), dict(sections=[dict(title=t, seconds=x) for t, x in previous]))
    if start_hashes is not None:
        tc.START_HASHES = start_hashes
    tc.RESULTS.clear()
    buf, code = io.StringIO(), 0
    try:
        with contextlib.redirect_stdout(buf):
            tc.main(list(argv) + ["--out", out])
    except SystemExit as e:
        code = e.code
    finally:
        tc.SECTIONS[:], tc.prelude, tc.EXPECTED_CASES, tc.WORKER_TASK, tc.OUT_DIR, tc.START_HASHES = saved
        tc.RESULTS.clear()
    with open(out, encoding="utf-8") as fh:
        rec = json.load(fh)
    return code, buf.getvalue(), rec


def diff(a, b, pinned):
    saved = tc.EXPECTED_CASES
    tc.EXPECTED_CASES = pinned
    try:
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code = tc.diff(a, b)
    finally:
        tc.EXPECTED_CASES = saved
    return code, buf.getvalue()


def main():
    whole = [("a", 2), ("b", 3)]                 # with the prelude's case: 6
    with tempfile.TemporaryDirectory() as tmp:
        p_whole, p_drop, p_empty, p_more = (os.path.join(tmp, n) for n in ("whole.json", "drop.json", "empty.json", "more.json"))
        code, text, rec = run(whole, 6, p_whole)
        expect("the whole fake suite (6 cases, EXPECTED_CASES 6): exit 0", (code, rec["total"], rec["short"]), (0, 6, []))
        expect("its record names the code it ran: the digest covers test_checks.py, frame_v0.py and hardware.py and matches the files now",
               ({"cad_b6/test_checks.py", "cad_b6/frame_v0.py", "cad_b6/hardware.py"} <= set(rec["sources"]), rec["digest"] == tc.sr.digest(rec["sources"], rec["environment"]),
                tc.sr.stale_sources(rec["sources"])), (True, True, []))
        expect("and the packages it ran: Python's version, cadquery, cadquery-ocp (OCP), numpy, scipy and vtk, as installed now",
               ({"cadquery", "cadquery-ocp", "numpy", "scipy", "vtk"} <= set(rec["environment"]["packages"]), rec["environment"]["python"] == tc.sr.platform.python_version(),
                tc.sr.stale_environment(rec["environment"])), (True, True, []))

        moved = dict(tc.START_HASHES, **{"cad_b6/hardware.py": "0" * 64})
        code, text, rec = run(whole, 6, os.path.join(tmp, "moved.json"), start_hashes=moved)
        expect("a file whose hash at the end differs from its hash before the imports (hardware.py edited during the run): exit 1, the record says so",
               (code, "cad_b6/hardware.py changed" in text, any("changed during the run" in e for e in rec["errors"])), (1, True, True))

        code, text, rec = run(whole[:1], 6, p_drop)
        expect("a section dropped (3 cases, EXPECTED_CASES 6): exit 1, the record says so", (code, "3 cases recorded, EXPECTED_CASES is 6" in text, len(rec["short"])), (1, True, 1))

        code, text, rec = run([("a", 2), ("b", 0), ("c", 3)], 6, p_empty)
        expect("a section emptied, the total still at the figure (6 of 6): exit 1, the section named", (code, "section 'b' recorded no case" in text, rec["total"]), (1, True, 6))

        code, text, rec = run([("a", 2), ("b", 4)], 6, p_more)
        expect("one case more than the figure: exit 0, and a line says to raise EXPECTED_CASES to 7", (code, "raise it to 7" in text), (0, True))

        p_drop2 = os.path.join(tmp, "drop2.json")
        run(whole[:1], 6, p_drop2)
        code, text = diff(p_drop, p_drop2, 6)
        expect("--diff of two runs that both lost a section: identical lists, still exit 1", (code, "IDENTICAL" in text and "FAILED" in text), (1, True))
        code, text = diff(p_whole, p_drop, 6)
        expect("--diff of a whole run and a short one: exit 1", code, 1)
        p_whole2 = os.path.join(tmp, "whole2.json")
        run(whole, 6, p_whole2)
        code, text = diff(p_whole, p_whole2, 6)
        expect("--diff of two whole runs: IDENTICAL, exit 0", (code, "IDENTICAL" in text), (0, True))

        with open(p_whole, encoding="utf-8") as fh:
            before = fh.read()
        try:
            run([("a", 2), ("boom", None)], 6, p_whole)
            died = False
        except RuntimeError:
            died = True
        with open(p_whole, encoding="utf-8") as fh:
            expect("a serial run that dies before its record leaves the previous record whole", (died, fh.read() == before), (True, True))
        expect("no temporary file is left next to the records", [n for n in os.listdir(tmp) if n.endswith(".tmp")], [])

        # the fast path: the real _worker_task in spawned workers
        p_fast = os.path.join(tmp, "fast_whole.json")
        code, text, rec = run([("a", 2), ("b", 1), ("c", 2), ("imp", "import")], 7, p_fast, argv=("--workers", "1"), previous=[("a", 1.0), ("b", 9.0), ("c", 5.0), ("imp", 0.5)])
        order = [line.split(" as ")[0][4:] for line in text.splitlines() if line.startswith("ran ")]
        seq = {line.split(" as ")[0][4:]: int(line.rsplit(" ", 1)[1]) for line in text.splitlines() if line.startswith("ran ")}
        expect("fast, 1 worker: exit 0, the output in the sections' order, the sections run longest first by the previous record (b 9 s, c 5 s, a 1 s, imp 0.5 s)",
               (code, rec["mode"], rec["total"], order, sorted(seq, key=seq.get)), (0, "fast", 7, ["a", "b", "c", "imp"], ["b", "c", "a", "imp"]))
        expect("fast: the record's sources and packages include what only a worker imported (check_budgets.py, trimesh), and its digest covers them",
               ("cad_b6/check_budgets.py" in rec["sources"], "trimesh" in rec["environment"]["packages"], "check_budgets" in sys.modules, "trimesh" in sys.modules,
                rec["digest"] == tc.sr.digest(rec["sources"], rec["environment"])), (True, True, False, False, True))
        code, text, rec = run([("a", 2), ("boom", None), ("c", 3)], 6, os.path.join(tmp, "fast_raise.json"), argv=("--workers", "2"))
        expect("fast, 2 workers: a section that raises in a worker: exit 1, the record names it",
               (code, any(e.startswith("boom: RuntimeError") for e in rec["errors"]), "ERROR in section 'boom'" in text), (1, True, True))
        code, text, rec = run([("a", 2), ("die", "exit"), ("c", 3)], 6, os.path.join(tmp, "fast_die.json"), argv=("--workers", "1"))
        expect("fast: a worker that dies (the pool breaks): exit 1, the dead worker's section and every section lost with the pool are errors",
               (code, sorted(e.split(":")[0] for e in rec["errors"]), "BrokenProcessPool" in text), (1, ["c", "die"], True))

    bad = OUT.count(False)
    print(f"\n{len(OUT) - bad}/{len(OUT)} as expected: {'PASS' if not bad else 'FAIL'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
