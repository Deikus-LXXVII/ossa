#!/usr/bin/env python3
"""Tests of test_checks.py's runner, on a tiny fake suite (no frame is built): a run that loses a section or records fewer cases
than EXPECTED_CASES fails, a section that records none fails, a run with more cases passes and says to raise the figure,
--diff of two short runs fails although their lists are identical, and the record carries the digest of the code it ran.

    .venv/bin/python cad_b6/test_runner.py          # a few seconds (imports cadquery, builds nothing); exit status 1 on a failure
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
import test_checks as tc  # noqa: E402

OUT: list[bool] = []


def expect(name, got, want):
    OUT.append(got == want)
    print(f"{'PASS' if got == want else 'FAIL'}  {name}\n      expected: {want}\n      got:      {got}")


def fake_prelude():
    tc.check("fake prelude", True, ("", ""))
    return None, None, None


def section_of(n):
    def run(_hardware, _parts, _base):
        if n is None:
            raise RuntimeError("a section that raises")
        for k in range(n):
            tc.check(f"case {k}", True, ("", ""))
    return run


def run(sections, pinned, out, argv=("--serial",)):
    """test_checks.main on the fake sections [(title, number of cases)] with EXPECTED_CASES = pinned: (exit code, printed text, record)."""
    saved = (list(tc.SECTIONS), tc.prelude, tc.EXPECTED_CASES)
    tc.SECTIONS[:] = [(t, section_of(n)) for t, n in sections]
    tc.prelude, tc.EXPECTED_CASES = fake_prelude, pinned
    tc.RESULTS.clear()
    buf, code = io.StringIO(), 0
    try:
        with contextlib.redirect_stdout(buf):
            tc.main(list(argv) + ["--out", out])
    except SystemExit as e:
        code = e.code
    finally:
        tc.SECTIONS[:], tc.prelude, tc.EXPECTED_CASES = saved
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
               ({"cad_b6/test_checks.py", "cad_b6/frame_v0.py", "cad_b6/hardware.py"} <= set(rec["sources"]), rec["digest"] == tc.sr.digest(rec["sources"]),
                tc.sr.stale_sources(rec["sources"])), (True, True, []))

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

    bad = OUT.count(False)
    print(f"\n{len(OUT) - bad}/{len(OUT)} as expected: {'PASS' if not bad else 'FAIL'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
