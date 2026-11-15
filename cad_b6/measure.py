#!/usr/bin/env python3
"""Measure the B6 model instead of reading coordinates off the source.

  .venv/bin/python cad_b6/measure.py                 list every part and hardware name with its AABB
  .venv/bin/python cad_b6/measure.py A B [C ...]     min distance and overlap volume for each pair
  .venv/bin/python cad_b6/measure.py A --near 5      everything within 5 mm of A
"""
from __future__ import annotations

import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frame_v0
import hardware


def load() -> dict:
    parts, _ = frame_v0.build_frame()
    shapes = {p.name: p.solid for p in parts}
    shapes.update({f"hw:{k}": v for k, v in hardware.build_hardware().items()})
    return shapes


def aabb(s) -> str:
    b = s.BoundingBox()
    return (f"X {b.xmin:7.1f}..{b.xmax:7.1f}  Y {b.ymin:7.1f}..{b.ymax:7.1f}  "
            f"Z {b.zmin:7.1f}..{b.zmax:7.1f}")


FAILED: list[str] = []


def pair(shapes, a, b) -> str:
    """One output line. A boolean or distance that fails is printed as ERROR, never as 0, and makes
    the script exit non-zero."""
    try:
        vol = frame_v0.inter_vol(shapes[a], shapes[b])
        dist = frame_v0.solid_distance(shapes[a], shapes[b])
    except frame_v0.BooleanFailure as e:
        FAILED.append(f"{a} x {b}")
        return f"{a:18} {b:18} ERROR boolean failed, overlap unknown: {e}"
    return f"{a:18} {b:18} min distance {dist:7.2f} mm   overlap {vol:10.1f} mm³"


def main(argv):
    shapes = load()
    if not argv:
        for name, s in shapes.items():
            print(f"{name:18} {aabb(s)}")
        return
    near = None
    if "--near" in argv:
        i = argv.index("--near")
        near = float(argv[i + 1])
        argv = argv[:i]
    unknown = [n for n in argv if n not in shapes]
    if unknown:
        sys.exit(f"unknown name(s) {unknown}; run with no arguments to list names")
    if near is not None:
        for other in shapes:
            if other == argv[0]:
                continue
            try:
                close = frame_v0.solid_distance(shapes[argv[0]], shapes[other]) <= near
            except frame_v0.BooleanFailure as e:
                FAILED.append(f"{argv[0]} x {other}")
                print(f"{argv[0]:18} {other:18} ERROR distance failed: {e}")
                continue
            if close:
                print(pair(shapes, argv[0], other))
        return
    for a, b in itertools.combinations(argv, 2):
        print(pair(shapes, a, b))


if __name__ == "__main__":
    main(sys.argv[1:])
    if FAILED:
        sys.exit(f"measure.py: {len(FAILED)} pair(s) could not be measured: {', '.join(FAILED)}")
