#!/usr/bin/env python3
"""Budgets: what the owner pays for, recorded and held.

    .venv/bin/python cad_b6/check_budgets.py            # one line per budget; exit 1 on a FAIL
    .venv/bin/python cad_b6/check_budgets.py --write    # record the present figures in cad_b6/budgets.json
    .venv/bin/python cad_b6/check_budgets.py --write --accept-lower    # the same when a figure fell under its floor on purpose (a real saving)

The figures:
  - the skeleton's ABS at 4 walls and 20 % infill (frame_v0.mass_estimate over every ABS part; the frame is built, about 20 s),
  - the organic layer's solid volume, from out/organic/field.npz (organic_frame.py writes it),
  - the fast test suite's counts of expensive operations and its wall time, from out/test_checks/fast.json (test_checks.py writes it),
  - the strength run of the organic layer: its load cases and its wall time, from out/organic/strength.json (organic_strength.py writes it).

The rule (owner, 17 Nov 2026): a budget is the present figure, recorded in budgets.json. A figure may grow by the
stated margin; past it the budget fails. Wall time is noisy, so it only warns; the suite is gated on its counts.
The hard limits come from the owner's stock and fail whatever is recorded. A budget is lowered only on purpose,
with --write, in a commit of its own after the figure improved. Never meet a budget by removing a check.

A figure under its floor fails too, because a saving is recorded on purpose, never found by chance: a count under its
recorded figure (the suite did less work than its record: a section that did not run, a loop cut short), a mass or a
volume more than 5 % under its record (an empty field, a part left out). --write refuses such a figure unless
--accept-lower says the saving is meant. A count may grow by 10 % rounded down, and always by one (count_limit).
The suite's record must be of the code in the working tree (its digest, suite_record.py), of the Python and the packages
installed now, hold the whole suite (test_checks.EXPECTED_CASES) and be of a clean fast run.
The strength run's record must be of a full run (step 1) that passed, on the layer as it is now (organic_manifest.py's fingerprint
of the grid and of every piece, and the saved probes) and by organic_strength.py as it is now (its SHA-256). Its load cases gate: more of them is a longer run, fewer is a push or a probe that was lost. Its
wall time only warns, and is the pieces' own (the unjudged earlier model of --earlier is not counted). The size of what it solves
follows the layer's volume, which has its own budget above.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import suite_record as sr  # noqa: E402

BUDGETS = os.path.join(HERE, "budgets.json")
FIELD = os.path.join(ROOT, "out", "organic", "field.npz")
SUITE = os.path.join(ROOT, "out", "test_checks", "fast.json")
STRENGTH = os.path.join(ROOT, "out", "organic", "strength.json")
STOCK_LIMIT = 0.9               # a hard limit: at most this share of the owner's stock of a filament
MASS_FLOOR = 0.95               # a mass or a volume under this share of its record fails: a saving is recorded on purpose (--write --accept-lower)
                                # a count fails under its recorded figure itself: the suite did less work than its record


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


RERUN = "rerun cad_b6/test_checks.py"


def read_suite(path=SUITE, root=ROOT, pinned=None):
    """(the fast suite's counts and wall time, None) or (None, why it is not a figure of this code): no record, an unreadable one,
    not a clean fast run, short of the pinned number of cases or a section that recorded none, or a digest that does not match the
    working tree (a file the run read has changed since: the record is of other code)."""
    if not os.path.exists(path):
        return None, f"no {os.path.relpath(path, root)}: {RERUN}"
    try:
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError) as e:
        return None, f"unreadable record {os.path.relpath(path, root)} ({type(e).__name__}): {RERUN}"
    if rec.get("mode") != "fast":
        return None, f"the record is of a {rec.get('mode')} run, the budget is of the fast one: {RERUN}"
    if rec.get("errors") or rec.get("passed") != rec.get("total") or rec.get("short"):
        return None, f"the record is of a failed run ({rec.get('passed')}/{rec.get('total')} cases, {len(rec.get('errors') or [])} errors, {len(rec.get('short') or [])} shortfalls): fix it and {RERUN}"
    if not rec.get("counts"):
        return None, f"the record has no counts: {RERUN}"
    pinned = sr.pinned_cases() if pinned is None else pinned
    short = sr.short_of_pin(len(rec.get("cases", [])), [(s_["title"], s_.get("n_cases", 0)) for s_ in rec.get("sections", [])], pinned)
    if short:
        return None, "the record is not the whole suite: " + "; ".join(short) + f": {RERUN}"
    sources, env = rec.get("sources"), rec.get("environment")
    if not sources or not env or rec.get("digest") != sr.digest(sources, env):
        return None, f"the record carries no digest of the code and the packages it ran, or one that does not match its own lists: {RERUN}"
    stale = sr.stale_sources(sources, root)
    if stale:
        return None, "the record is of other code: " + ", ".join(f"{r} {why}" for r, why in stale[:4]) + (f" and {len(stale) - 4} more" if len(stale) > 4 else "") + f" since the run: {RERUN}"
    moved = sr.stale_environment(env)
    if moved:
        return None, "the record is of other packages: " + ", ".join(f"{d} {v} then, {now or 'not installed'} now" for d, v, now in moved[:4]) \
            + (f" and {len(moved) - 4} more" if len(moved) > 4 else "") + f": {RERUN} with this interpreter"
    return dict(counts=rec["counts"], wall_s=rec["wall_s"], finished=rec.get("finished"), workers=rec.get("workers")), None


def suite_record(path=SUITE, root=ROOT, pinned=None):
    """The fast suite's counts and wall time, or None when read_suite() refuses the record."""
    return read_suite(path, root, pinned)[0]


RERUN_STRENGTH = "rerun cad_b6/organic_strength.py"


def run_prints(path=FIELD):
    """organic_strength.run_prints of the field and the script as they are now: what a strength record must be a run of."""
    import organic_strength

    return organic_strength.run_prints(path)


def whole(x):
    """A whole number that is not a bool (True == 1 in Python, and a record is read from JSON)."""
    return type(x) is int


def read_strength(path=STRENGTH, field=FIELD, root=ROOT, prints=run_prints):
    """(the strength run's load cases and wall time, None) or (None, why it is not a figure of this layer): no record, an unreadable one, not a full run,
    a run that failed, a record with no piece, or one that is not of the layer and the script as they are now (a piece, the grid, the probes or
    organic_strength.py differs)."""
    if not os.path.exists(path):
        return None, f"no {os.path.relpath(path, root)}: {RERUN_STRENGTH}"
    try:
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError) as e:
        return None, f"unreadable record {os.path.relpath(path, root)} ({type(e).__name__}): {RERUN_STRENGTH}"
    if not isinstance(rec, dict):
        return None, f"unreadable record {os.path.relpath(path, root)} (not an object): {RERUN_STRENGTH}"
    if not (whole(rec.get("step")) and rec["step"] == 1):
        return None, f"the record is of a run at step {rec.get('step')!r}, the budget is of the full one (step 1): {RERUN_STRENGTH}"
    if rec.get("passed") is not True:
        return None, f"the record is of a run that failed its checks: fix the layer and {RERUN_STRENGTH}"
    pieces = rec.get("pieces")
    if not isinstance(pieces, dict) or not pieces or not all(
            isinstance(p, dict) and whole(p.get("load_cases")) and p["load_cases"] > 0 and type(p.get("seconds")) in (int, float) and p["seconds"] >= 0 for p in pieces.values()):
        return None, f"the record has no piece, or a piece with no load case or no time: {RERUN_STRENGTH}"
    if not os.path.exists(field):
        return None, f"no {os.path.relpath(field, root)} to hold the record against: run cad_b6/organic_frame.py, then {RERUN_STRENGTH}"
    try:
        now = prints(field)
    except Exception as e:      # noqa: BLE001  a field that cannot be fingerprinted is not the field the record was run on
        return None, f"the field cannot be fingerprinted ({type(e).__name__}: {e}): run cad_b6/organic_frame.py, then {RERUN_STRENGTH}"
    then = rec.get("of") if isinstance(rec.get("of"), dict) else {}
    was, is_ = (x.get("field") if isinstance(x.get("field"), dict) else {} for x in (then, now))
    moved = sorted(k for k in set(was) | set(is_) if was.get(k) != is_.get(k)) + [k for k in ("probes", "script") if then.get(k) != now.get(k) or now.get(k) is None]
    if not is_ or set(pieces) != set(is_) - {"grid"}:
        moved.append("its pieces")
    if moved:
        return None, (f"the record is not of the layer and the script as they are now ({', '.join(moved)} differ; `script` is cad_b6/organic_strength.py, "
                      f"the rest is out/organic/field.npz): {RERUN_STRENGTH}")
    return dict(load_cases=sum(p["load_cases"] for p in pieces.values()), wall_s=float(sum(p["seconds"] for p in pieces.values())), finished=rec.get("finished")), None


def gather(field=FIELD, suite=SUITE, skeleton=skeleton_abs_g, strength=STRENGTH):
    rec, why = read_suite(suite)
    st, st_why = read_strength(strength, field)
    return dict(skeleton_abs_g=skeleton(), organic_cm3=organic_cm3(field), suite=rec, suite_why=why, strength=st, strength_why=st_why)


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


LOWER = "if the saving is meant, record it with --write --accept-lower"


def under_floor(figure, floor):
    return figure is not None and floor is not None and figure < floor - 1e-9


def row(name, figure, limit, unit, kind, verdict_over=FAIL, note="", floor=None, floor_why=""):
    """One budget line: (verdict, name, figure, limit, margin left, unit, kind, note). A missing figure fails; so does one under `floor`
    (floor_why says what the floor is and why a figure under it is not taken as a saving)."""
    if figure is None:
        return (FAIL, name, None, limit, None, unit, kind, "input missing: " + note)
    if under_floor(figure, floor):
        return (FAIL, name, figure, limit, limit - figure, unit, kind, f"{floor_why}; {LOWER}; " + note)
    verdict = PASS if figure <= limit + 1e-9 else verdict_over
    return (verdict, name, figure, limit, limit - figure, unit, kind, note)


def count_limit(n, margin):
    """The largest count a recorded count n allows: n x (1 + margin) rounded down, and never less than n + 1. A count is whole, so on a
    small count the margin alone would allow nothing (9 frame builds: 9.9, so 9) and the next honest test that adds one operation would fail."""
    return max(n + 1, int(n * (1 + margin) + 1e-9))


STRENGTH_CASES = "strength run, load cases"


def floors(budgets):
    """{budget line: (floor, why a figure under it fails)} for the lines that have a floor."""
    sk, org, su, st = budgets["skeleton_abs_g"], budgets["organic_cm3"], budgets["suite"], budgets["strength"]
    mass = lambda fig, unit: (MASS_FLOOR * fig, f"more than {100 * (1 - MASS_FLOOR):g} % under its record (floor {MASS_FLOOR * fig:.3f} {unit}): "      # noqa: E731
                              "a wrong input (an empty field, a part left out) until a saving is recorded on purpose")
    out = {"skeleton ABS, ratchet": mass(sk["figure"], "g"), "organic layer, ratchet": mass(org["figure"], "cm3")}
    for key, n in su["counts"].items():
        out[f"test suite, {key}"] = (n, f"under its recorded {n}: the suite did less work than its record (a section that did not run, a loop cut short)")
    out[STRENGTH_CASES] = (st["load_cases"], f"under its recorded {st['load_cases']}: the run pushed less than its record (a push point or a film member's probe lost)")
    return out


def judge(fig, budgets, abs_stock, petg_rho):
    rows = []
    fl = floors(budgets)
    sk = budgets["skeleton_abs_g"]
    g = fig["skeleton_abs_g"]
    rows.append(row("skeleton ABS, ratchet", g, sk["figure"] * (1 + sk["margin"]), "g", "gate", note=f"recorded {sk['figure']:.1f} g + {100 * sk['margin']:g} %",
                    floor=fl["skeleton ABS, ratchet"][0], floor_why=fl["skeleton ABS, ratchet"][1]))
    rows.append(row("skeleton ABS, stock", g, STOCK_LIMIT * abs_stock, "g", "gate", note=f"{100 * STOCK_LIMIT:g} % of {abs_stock:.0f} g of black ABS on hand"))
    org = budgets["organic_cm3"]
    v = fig["organic_cm3"]
    rows.append(row("organic layer, ratchet", v, org["figure"] * (1 + org["margin"]), "cm3", "gate", note=f"recorded {org['figure']:.1f} cm3 + {100 * org['margin']:g} %"
                    if v is not None else "no out/organic/field.npz: run organic_frame.py", floor=fl["organic layer, ratchet"][0], floor_why=fl["organic layer, ratchet"][1]))
    rows.append(row("organic layer, PETG stock", None if v is None else v * petg_rho, STOCK_LIMIT * org["petg_stock_g"], "g", "gate",
                    note=f"solid PETG at {petg_rho:g} g/cm3, {100 * STOCK_LIMIT:g} % of {org['petg_stock_g']:.0f} g ordered" if v is not None else "no out/organic/field.npz: run organic_frame.py"))
    su = budgets["suite"]
    rec = fig["suite"]
    why = fig.get("suite_why") or "no clean out/test_checks/fast.json: run test_checks.py"
    if not su["counts"]:
        rows.append((FAIL, "test suite, counts", None, 0, None, "", "gate", "no counts recorded in budgets.json: run check_budgets.py --write"))
    for key, n in su["counts"].items():
        got = None if rec is None else rec["counts"].get(key)
        lim = count_limit(n, su["count_margin"])
        rows.append(row(f"test suite, {key}", got, lim, "", "gate", floor=fl[f"test suite, {key}"][0], floor_why=fl[f"test suite, {key}"][1],
                        note=f"recorded {n}, limit {lim} (the larger of + 1 and + {100 * su['count_margin']:g} % rounded down), floor {n}" if rec is not None else why))
    rows.append(row("test suite, wall time", None if rec is None else rec["wall_s"], su["wall_s"] * (1 + su["wall_margin"]), "s", "warning", verdict_over=WARN,
                    note=f"recorded {su['wall_s']:.0f} s + {100 * su['wall_margin']:g} %, noisy: a warning, never a failure" if rec is not None else why))
    st = budgets["strength"]
    rec = fig.get("strength")
    why = fig.get("strength_why") or "no clean out/organic/strength.json: run organic_strength.py"
    lim = count_limit(st["load_cases"], st["count_margin"])
    rows.append(row(STRENGTH_CASES, None if rec is None else rec["load_cases"], lim, "", "gate", floor=fl[STRENGTH_CASES][0], floor_why=fl[STRENGTH_CASES][1],
                    note=f"recorded {st['load_cases']}, limit {lim} (+ {100 * st['count_margin']:g} % rounded down), floor {st['load_cases']}" if rec is not None else why))
    rows.append(row("strength run, wall time", None if rec is None else rec["wall_s"], st["wall_s"] * (1 + st["wall_margin"]), "s", "warning", verdict_over=WARN,
                    note=f"recorded {st['wall_s']:.0f} s + {100 * st['wall_margin']:g} %, noisy: a warning, never a failure" if rec is not None else why))
    return rows


def fmt(r):
    verdict, name, figure, limit, margin, unit, kind, note = r
    num = (lambda x: f"{x:.1f} {unit}".strip()) if unit else (lambda x: f"{x:.0f}")
    fig = "missing" if figure is None else num(figure)
    left = "" if margin is None else f"margin {num(margin)} ({100 * margin / limit:+.1f} %)" if limit else f"margin {num(margin)}"
    return f"{verdict}  {name:34s} {fig:>11s}  budget {num(limit):>11s}  {left:28s} [{kind}] {note}"


HARD = ("skeleton ABS, stock", "organic layer, PETG stock")       # the rows of the owner's stock: a figure past them is never recorded


def lows(fig, budgets):
    """[(budget line, figure, floor, why)] of the figures under their floor."""
    got = {"skeleton ABS, ratchet": fig.get("skeleton_abs_g"), "organic layer, ratchet": fig.get("organic_cm3")}
    for key in budgets["suite"]["counts"]:
        got[f"test suite, {key}"] = None if fig.get("suite") is None else fig["suite"]["counts"].get(key)
    got[STRENGTH_CASES] = None if fig.get("strength") is None else fig["strength"]["load_cases"]
    return [(name, got[name], floor, why) for name, (floor, why) in floors(budgets).items() if under_floor(got[name], floor)]


def write(fig, budgets, path=BUDGETS, abs_stock=None, petg_rho=None, accept_lower=False):
    """Record the present figures, the margins and limits kept. Refused when an input is missing, when a figure fails a hard limit
    (recording it would move the ratchet up past the stock, and a later figure a little smaller would pass it), and when a figure is
    under its floor (a count under its record, a mass or volume more than 5 % under it) unless accept_lower says the saving is meant:
    recorded by accident, a wrong input would lower the ratchet and the floor with it. Returns (the new budgets, the lower figures accepted)."""
    missing = [k for k in ("skeleton_abs_g", "organic_cm3", "suite", "strength") if fig.get(k) is None]
    if missing:
        raise SystemExit(f"--write refused: input missing for {', '.join(missing)}" + "".join(f" ({fig[k]})" for k in ("suite_why", "strength_why") if fig.get(k)))
    for k in budgets["suite"]["counts"]:
        if k not in fig["suite"]["counts"]:
            raise SystemExit(f"--write refused: the suite's record has no count '{k}', which budgets.json holds: the record would drop a gate")
    hard = [r for r in judge(fig, budgets, abs_stock_g() if abs_stock is None else abs_stock, petg_density() if petg_rho is None else petg_rho)
            if r[1] in HARD and r[0] != PASS]
    if hard:
        raise SystemExit("--write refused: a figure fails a hard limit, it is not recorded: " + "; ".join(fmt(r) for r in hard))
    low = lows(fig, budgets)
    if low and not accept_lower:
        raise SystemExit("--write refused: a figure is under its floor, it is not recorded: "
                         + "; ".join(f"{name} {figure:.8g} under its floor {floor:.8g}: {why}" for name, figure, floor, why in low)
                         + ". If the saving is meant, rerun with --write --accept-lower and say why in the commit.")
    new = json.loads(json.dumps(budgets))
    new["skeleton_abs_g"]["figure"] = round(fig["skeleton_abs_g"], 1)
    new["organic_cm3"]["figure"] = round(fig["organic_cm3"], 1)
    new["suite"]["counts"] = dict(fig["suite"]["counts"])
    new["suite"]["wall_s"] = round(fig["suite"]["wall_s"], 1)
    new["suite"]["recorded_from"] = f"fast run of {fig['suite']['finished']}, {fig['suite']['workers']} workers"
    new["strength"]["load_cases"] = int(fig["strength"]["load_cases"])
    new["strength"]["wall_s"] = round(fig["strength"]["wall_s"], 1)
    new["strength"]["recorded_from"] = f"full run of {fig['strength']['finished']}"
    sr.write_json_atomic(path, new)
    return new, low


def main(argv=None, skeleton=skeleton_abs_g):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true", help="record the present figures in budgets.json")
    ap.add_argument("--accept-lower", action="store_true", help="with --write: record a figure under its floor (a count under its record, a mass or volume more than 5 %% under it) as a saving that is meant")
    ap.add_argument("--budgets", default=BUDGETS)
    ap.add_argument("--field", default=FIELD)
    ap.add_argument("--suite", default=SUITE)
    ap.add_argument("--strength", default=STRENGTH)
    args = ap.parse_args(argv)
    if args.accept_lower and not args.write:
        ap.error("--accept-lower goes with --write")
    with open(args.budgets, encoding="utf-8") as fh:
        budgets = json.load(fh)
    fig = gather(args.field, args.suite, skeleton, args.strength)
    if args.write:
        budgets, low = write(fig, budgets, args.budgets, accept_lower=args.accept_lower)
        print(f"recorded the present figures in {os.path.relpath(args.budgets, ROOT)}")
        for name, figure, floor, _why in low:
            print(f"accepted lower (--accept-lower): {name} {figure:.8g}, under its floor {floor:.8g}: the floor follows it down")
    rows = judge(fig, budgets, abs_stock_g(), petg_density())
    for r in rows:
        print(fmt(r))
    fails = [r for r in rows if r[0] == FAIL]
    warns = [r for r in rows if r[0] == WARN]
    print(f"\n{len(rows) - len(fails) - len(warns)} PASS, {len(warns)} WARN, {len(fails)} FAIL. Gates fail the run; the wall time only warns."
          + (f" Suite record: {fig['suite']['finished']}, {fig['suite']['workers']} workers." if fig["suite"] else "")
          + (f" Strength record: {fig['strength']['finished']}." if fig["strength"] else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
