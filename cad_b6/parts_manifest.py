"""Fingerprint of every printed part and every hardware solid, and a comparison against the last commit.

A revision can change a part it did not mean to touch (REVIEW.md row 13). This script makes that visible: it builds the model, writes down
for every printed part and every hardware solid its volume, bounding box, centre of mass, number of solids and faces, material and (parts)
holes, and compares that with `cad_b6/parts_manifest.json` as committed at HEAD.

  .venv/bin/python cad_b6/parts_manifest.py                     table of parts added, removed and changed against HEAD, exit 0
  .venv/bin/python cad_b6/parts_manifest.py --expect a,b,c_*    the same, exit 1 if anything outside the list differs (fnmatch patterns,
                                                                a trailing * is the usual use; hardware solids are named hw:<name>)
  .venv/bin/python cad_b6/parts_manifest.py --write             rewrite cad_b6/parts_manifest.json from the working tree
  .venv/bin/python cad_b6/parts_manifest.py --against FILE      compare with FILE instead of HEAD's manifest

Exit 2: there is nothing to compare with (HEAD has no manifest, or FILE is unreadable).

Numbers: two builds of the same model on the same machine, in one process or two, give bit-identical values (measured 17 Nov 2026), so the
file's rounding (4 decimals for lengths in mm, 3 for volumes in mm^3) is only there to keep it short. The comparison tolerates a relative
1e-6 on a volume and 1e-3 mm on a coordinate, which is far above that noise and far below any change a revision makes on purpose.
"""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
MANIFEST = os.path.join(HERE, "parts_manifest.json")
MANIFEST_REL = "cad_b6/parts_manifest.json"

FORMAT = 1
LEN_DECIMALS = 4        # mm
VOL_DECIMALS = 3        # mm^3
TOL_VOL_REL = 1e-6      # relative, on a volume
TOL_MM = 1e-3           # on a bounding box, a centre of mass, a hole's start, direction, radius and length


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------
def _r(x, n=LEN_DECIMALS):
    x = round(float(x), n)
    return 0.0 if x == 0 else x          # no "-0.0"


def shape_print(shape, material=None):
    bb, c = shape.BoundingBox(), shape.Center()
    d = {"volume": _r(shape.Volume(), VOL_DECIMALS),
         "bbox": [_r(v) for v in (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)],
         "com": [_r(c.x), _r(c.y), _r(c.z)],
         "solids": len(shape.Solids()),
         "faces": len(shape.Faces())}
    if material is not None:
        d["material"] = material
    return d


def hole_print(h):
    """[kind, start x, y, z, direction x, y, z, length, radius]"""
    return [h.kind, *(_r(v) for v in h.start), *(_r(v) for v in h.d), _r(h.length), _r(h.r)]


def build_manifest():
    import frame_v0
    import hardware
    parts, _ = frame_v0.build_frame()
    items = {}
    for p in parts:
        d = shape_print(p.solid, p.material)
        d["holes"] = [hole_print(h) for h in p.holes]
        items[p.name] = d
    for name, solid in hardware.build_hardware().items():
        items["hw:" + name] = shape_print(solid)
    return {"format": FORMAT, "items": dict(sorted(items.items()))}


def dumps(m):
    """One line per item's numbers and one per hole, so a git diff of the file reads like the table."""
    out = ['{', f' "format": {m["format"]},', ' "items": {']
    keys = list(m["items"])
    for i, k in enumerate(keys):
        it = dict(m["items"][k])
        holes = it.pop("holes", None)
        head = json.dumps(it, sort_keys=True)
        tail = "," if i < len(keys) - 1 else ""
        if holes is None:
            out.append(f'  {json.dumps(k)}: {head}{tail}')
            continue
        out.append(f'  {json.dumps(k)}: {{"shape": {head}, "holes": [')
        out += [f'    {json.dumps(h)}{"," if j < len(holes) - 1 else ""}' for j, h in enumerate(holes)]
        out.append(f'  ]}}{tail}')
    out += [' }', '}']
    return "\n".join(out) + "\n"


def normalise(m):
    """Bring both shapes of an item (a part: {"shape":..., "holes":...} in the file, flat in memory) to the flat one."""
    items = {}
    for k, it in m["items"].items():
        if "shape" in it:
            it = {**it["shape"], "holes": it["holes"]}
        items[k] = it
    return items


def loads(text):
    return normalise(json.loads(text))


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def _same_len(a, b):
    return abs(a - b) <= TOL_MM


def _same_hole(a, b):
    return a[0] == b[0] and all(_same_len(x, y) for x, y in zip(a[1:], b[1:]))


def match_holes(old, new):
    """(removed, added): holes of `old` with no partner in `new` and the other way round; the order of the list does not matter."""
    left = list(new)
    removed = []
    for h in old:
        for i, g in enumerate(left):
            if _same_hole(h, g):
                del left[i]
                break
        else:
            removed.append(h)
    return removed, left


def _fmt(v):
    return f"{v:.4f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def _hole_text(h):
    return f"{h[0]} at ({_fmt(h[1])}, {_fmt(h[2])}, {_fmt(h[3])}) along ({_fmt(h[4])}, {_fmt(h[5])}, {_fmt(h[6])}) length {_fmt(h[7])}"


def diff_item(old, new):
    """The list of what differs between two fingerprints, each a short sentence with the size of the change; empty when they agree."""
    out = []
    ov, nv = old["volume"], new["volume"]
    if abs(ov - nv) > TOL_VOL_REL * max(abs(ov), abs(nv)) + 1e-9:
        pct = f", {100 * (nv - ov) / ov:+.2f} %" if ov else ""
        out.append(f"volume {ov:.1f} -> {nv:.1f} mm3 ({nv - ov:+.2f}{pct})")
    for label, a, b in zip(("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"), old["bbox"], new["bbox"]):
        if not _same_len(a, b):
            out.append(f"bbox {label} {_fmt(a)} -> {_fmt(b)} ({b - a:+.3f})")
    if not all(_same_len(a, b) for a, b in zip(old["com"], new["com"])):
        d = [b - a for a, b in zip(old["com"], new["com"])]
        out.append(f"centre of mass moved ({d[0]:+.3f}, {d[1]:+.3f}, {d[2]:+.3f})")
    for key in ("solids", "faces", "material"):
        if old.get(key) != new.get(key):
            out.append(f"{key} {old.get(key)} -> {new.get(key)}")
    if "holes" in old or "holes" in new:
        removed, added = match_holes(old.get("holes", []), new.get("holes", []))
        if removed or added:
            out.append(f"holes: {len(added)} added, {len(removed)} removed (of {len(old.get('holes', []))} before)")
            out += [f"  + {_hole_text(h)}" for h in added] + [f"  - {_hole_text(h)}" for h in removed]
    return out


def compare(old, new):
    """(added, removed, changed): names present only in `new`, only in `old`, and {name: [what changed]} for those in both."""
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = {}
    for k in sorted(set(old) & set(new)):
        d = diff_item(old[k], new[k])
        if d:
            changed[k] = d
    return added, removed, changed


def outside(names, patterns):
    return sorted(n for n in names if not any(fnmatch.fnmatchcase(n, p) for p in patterns))


def report(added, removed, changed, n_old, n_new):
    lines = [f"{n_old} items before, {n_new} now: {len(added)} added, {len(removed)} removed, {len(changed)} changed"]
    if added:
        lines += ["", "ADDED"] + [f"  {k}" for k in added]
    if removed:
        lines += ["", "REMOVED"] + [f"  {k}" for k in removed]
    if changed:
        w = max(len(k) for k in changed)
        lines += ["", "CHANGED"]
        for k, d in changed.items():
            first = [x for x in d if not x.startswith("  ")]
            lines.append(f"  {k:<{w}}  {first[0] if first else ''}")
            lines += [f"  {'':<{w}}  {x}" for x in first[1:]]
            lines += [f"  {'':<{w}}  {x}" for x in d if x.startswith("  ")]
    if not (added or removed or changed):
        lines.append("no differences")
    return "\n".join(lines)


def head_manifest():
    r = subprocess.run(["git", "show", f"HEAD:{MANIFEST_REL}"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return loads(r.stdout)


def main(argv):
    expect = None
    against = None
    write = False
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--write":
            write = True
        elif a == "--expect" and args:
            expect = [p.strip() for p in args.pop(0).split(",") if p.strip()]
        elif a == "--against" and args:
            against = args.pop(0)
        else:
            print(__doc__)
            return 2
    old, base = None, None
    if not write:                 # find the baseline before the 20 s build, so a missing one fails at once
        if against:
            try:
                with open(against) as f:
                    old = loads(f.read())
            except (OSError, ValueError, KeyError) as e:
                print(f"cannot read {against}: {e}")
                return 2
            base = against
        else:
            old = head_manifest()
            base = f"HEAD:{MANIFEST_REL}"
            if old is None:
                print(f"HEAD has no {MANIFEST_REL}: nothing to compare with. Write one with --write (the commit that adds the file is the baseline).")
                return 2
    t0 = time.time()
    new_m = build_manifest()
    t_build = time.time() - t0
    if write:
        with open(MANIFEST, "w") as f:
            f.write(dumps(new_m))
        print(f"wrote {MANIFEST} ({len(new_m['items'])} items, build {t_build:.1f} s)")
        return 0
    new = normalise(new_m)
    added, removed, changed = compare(old, new)
    print(f"compared with {base}   (tolerance: volume {TOL_VOL_REL:g} relative, coordinates {TOL_MM:g} mm; build {t_build:.1f} s)")
    print(report(added, removed, changed, len(old), len(new)))
    if expect is None:
        return 0
    bad = outside(set(added) | set(removed) | set(changed), expect)
    unused = [p for p in expect if not any(fnmatch.fnmatchcase(n, p) for n in set(added) | set(removed) | set(changed))]
    print()
    if unused:
        print("expected but not different: " + ", ".join(unused))
    if bad:
        print("FAIL: outside the expected list: " + ", ".join(bad))
        return 1
    print(f"OK: every difference is in the expected list ({', '.join(expect)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
