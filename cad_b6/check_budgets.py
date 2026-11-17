#!/usr/bin/env python3
"""Budgets: what the owner pays for, recorded and held.

    .venv/bin/python cad_b6/check_budgets.py            # one line per budget; exit 1 on a FAIL
    .venv/bin/python cad_b6/check_budgets.py --write    # record the present figures in cad_b6/budgets.json

The figures:
  - the skeleton's ABS at 4 walls and 20 % infill (frame_v0.mass_estimate over every ABS part; the frame is built, about 20 s),
  - the organic layer's solid volume, from out/organic/field.npz (organic_frame.py writes it),
  - the fast test suite's counts of expensive operations and its wall time, from out/test_checks/fast.json (test_checks.py writes it).

The rule (owner, 17 Nov 2026): a budget is the present figure, recorded in budgets.json. A figure may grow by the
stated margin; past it the budget fails. Wall time is noisy, so it only warns; the suite is gated on its counts.
The hard limits come from the owner's stock and fail whatever is recorded. A budget is lowered only on purpose,
with --write, in a commit of its own after the figure improved. Never meet a budget by removing a check.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

BUDGETS = os.path.join(HERE, "budgets.json")
FIELD = os.path.join(ROOT, "out", "organic", "field.npz")
SUITE = os.path.join(ROOT, "out", "test_checks", "fast.json")
STOCK_LIMIT = 0.9               # a hard limit: at most this share of the owner's stock of a filament


# ---------------------------------------------------------------------------
# the present figures (None: the input is missing, and the budget fails)
# ---------------------------------------------------------------------------
def skeleton_abs_g():
    """Grams of ABS in the skeleton at 4 walls and 20 % infill: frame_v0.mass_estimate over every ABS part, as the report's totals."""
    import warnings

    warnings.filterwarnings("ignore")
    import frame_v0 as f
    import hardware as hw

    parts, _ = f.build_frame(hardware=hw.build_hardware())
    return sum(f.mass_estimate(p.solid, p.material)[2] for p in parts if p.material == "ABS")


def organic_cm3(path=FIELD):
    """The organic layer's solid volume, cm3: the voxels inside the layer (d < 0) times the voxel's volume, as organic_frame.check reports it."""
    if not os.path.exists(path):
        return None
    import numpy as np

    z = np.load(path)
    xs = z["xs"].astype(float)
    vox = (xs[-1] - xs[0]) / (len(xs) - 1)
    return float((z["d"] < 0).sum()) * vox ** 3 / 1000.0


def suite_record(path=SUITE):
    """The fast suite's counts and wall time, or None when there is no record or it is not a whole, clean fast run."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        rec = json.load(fh)
    if rec.get("mode") != "fast" or rec.get("errors") or not rec.get("counts") or rec.get("passed") != rec.get("total"):
        return None
    return dict(counts=rec["counts"], wall_s=rec["wall_s"], finished=rec.get("finished"), workers=rec.get("workers"))


def gather(field=FIELD, suite=SUITE, skeleton=skeleton_abs_g):
    return dict(skeleton_abs_g=skeleton(), organic_cm3=organic_cm3(field), suite=suite_record(suite))


def petg_density():
    import organic_frame

    return organic_frame.LAYER_RHO


def abs_stock_g():
    import hardware as hw

    return hw.ABS_STOCK_G


# ---------------------------------------------------------------------------
# the judgement: pure, so that the tests can feed it any figures
# ---------------------------------------------------------------------------
PASS, FAIL, WARN = "PASS", "FAIL", "WARN"


def row(name, figure, limit, unit, kind, verdict_over=FAIL, note=""):
    """One budget line: (verdict, name, figure, limit, margin left, unit, kind, note). A missing figure fails."""
    if figure is None:
        return (FAIL, name, None, limit, None, unit, kind, "input missing: " + note)
    verdict = PASS if figure <= limit + 1e-9 else verdict_over
    return (verdict, name, figure, limit, limit - figure, unit, kind, note)


def judge(fig, budgets, abs_stock, petg_rho):
    rows = []
    sk = budgets["skeleton_abs_g"]
    g = fig["skeleton_abs_g"]
    rows.append(row("skeleton ABS, ratchet", g, sk["figure"] * (1 + sk["margin"]), "g", "gate", note=f"recorded {sk['figure']:.1f} g + {100 * sk['margin']:g} %"))
    rows.append(row("skeleton ABS, stock", g, STOCK_LIMIT * abs_stock, "g", "gate", note=f"{100 * STOCK_LIMIT:g} % of {abs_stock:.0f} g of black ABS on hand"))
    org = budgets["organic_cm3"]
    v = fig["organic_cm3"]
    rows.append(row("organic layer, ratchet", v, org["figure"] * (1 + org["margin"]), "cm3", "gate", note=f"recorded {org['figure']:.1f} cm3 + {100 * org['margin']:g} %"
                    if v is not None else "no out/organic/field.npz: run organic_frame.py"))
    rows.append(row("organic layer, PETG stock", None if v is None else v * petg_rho, STOCK_LIMIT * org["petg_stock_g"], "g", "gate",
                    note=f"solid PETG at {petg_rho:g} g/cm3, {100 * STOCK_LIMIT:g} % of {org['petg_stock_g']:.0f} g ordered" if v is not None else "no out/organic/field.npz: run organic_frame.py"))
    su = budgets["suite"]
    rec = fig["suite"]
    if not su["counts"]:
        rows.append((FAIL, "test suite, counts", None, 0, None, "", "gate", "no counts recorded in budgets.json: run check_budgets.py --write"))
    for key, n in su["counts"].items():
        got = None if rec is None else rec["counts"].get(key)
        rows.append(row(f"test suite, {key}", got, int(n * (1 + su["count_margin"]) + 1e-9), "", "gate",
                        note=f"recorded {n} + {100 * su['count_margin']:g} %" if rec is not None else "no clean out/test_checks/fast.json: run test_checks.py"))
    rows.append(row("test suite, wall time", None if rec is None else rec["wall_s"], su["wall_s"] * (1 + su["wall_margin"]), "s", "warning", verdict_over=WARN,
                    note=f"recorded {su['wall_s']:.0f} s + {100 * su['wall_margin']:g} %, noisy: a warning, never a failure" if rec is not None
                    else "no clean out/test_checks/fast.json: run test_checks.py"))
    return rows


def fmt(r):
    verdict, name, figure, limit, margin, unit, kind, note = r
    num = (lambda x: f"{x:.1f} {unit}".strip()) if unit else (lambda x: f"{x:.0f}")
    fig = "missing" if figure is None else num(figure)
    left = "" if margin is None else f"margin {num(margin)} ({100 * margin / limit:+.1f} %)" if limit else f"margin {num(margin)}"
    return f"{verdict}  {name:34s} {fig:>11s}  budget {num(limit):>11s}  {left:28s} [{kind}] {note}"


def write(fig, budgets, path=BUDGETS):
    """Record the present figures, the margins and limits kept. Refused when an input is missing."""
    missing = [k for k, v in fig.items() if v is None]
    if missing:
        raise SystemExit(f"--write refused: input missing for {', '.join(missing)}")
    new = json.loads(json.dumps(budgets))
    new["skeleton_abs_g"]["figure"] = round(fig["skeleton_abs_g"], 1)
    new["organic_cm3"]["figure"] = round(fig["organic_cm3"], 1)
    new["suite"]["counts"] = dict(fig["suite"]["counts"])
    new["suite"]["wall_s"] = round(fig["suite"]["wall_s"], 1)
    new["suite"]["recorded_from"] = f"fast run of {fig['suite']['finished']}, {fig['suite']['workers']} workers"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(new, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    return new


def main(argv=None, skeleton=skeleton_abs_g):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true", help="record the present figures in budgets.json")
    ap.add_argument("--budgets", default=BUDGETS)
    ap.add_argument("--field", default=FIELD)
    ap.add_argument("--suite", default=SUITE)
    args = ap.parse_args(argv)
    with open(args.budgets, encoding="utf-8") as fh:
        budgets = json.load(fh)
    fig = gather(args.field, args.suite, skeleton)
    if args.write:
        budgets = write(fig, budgets, args.budgets)
        print(f"recorded the present figures in {os.path.relpath(args.budgets, ROOT)}")
    rows = judge(fig, budgets, abs_stock_g(), petg_density())
    for r in rows:
        print(fmt(r))
    fails = [r for r in rows if r[0] == FAIL]
    warns = [r for r in rows if r[0] == WARN]
    print(f"\n{len(rows) - len(fails) - len(warns)} PASS, {len(warns)} WARN, {len(fails)} FAIL. Gates fail the run; the wall time only warns."
          + (f" Suite record: {fig['suite']['finished']}, {fig['suite']['workers']} workers." if fig["suite"] else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
