"""Fingerprint of every piece of the organic layer, and a comparison against the last commit.

A revision can change a piece of the layer it did not mean to touch (revision 17 promised that the piece `main` stays bit for bit as it was, and proved it once by
hand). This script makes that visible every time, in the manner of parts_manifest.py: it reads the layer's saved field (out/organic/field.npz, written by
organic_frame.py), writes down for every piece the number of its solid voxels, its volume, the extents of its solid voxels' centres, a SHA-256 of its packed
solid mask (np.packbits(d_piece < 0), the whole grid in C order) and its pads (name, centre, normal), and compares that with `cad_b6/organic_manifest.json` as
committed at HEAD. The grid itself (shape, first point, voxel) is the item `grid`.

  .venv/bin/python cad_b6/organic_manifest.py                     table of pieces added, removed and changed against HEAD, exit 0
  .venv/bin/python cad_b6/organic_manifest.py --expect a,b        the same, exit 1 if anything outside the list differs (fnmatch patterns; the grid is `grid`)
  .venv/bin/python cad_b6/organic_manifest.py --write             rewrite cad_b6/organic_manifest.json from the field
  .venv/bin/python cad_b6/organic_manifest.py --against FILE      compare with FILE instead of HEAD's manifest
  .venv/bin/python cad_b6/organic_manifest.py --field FILE        fingerprint FILE instead of out/organic/field.npz; a field of before revision 17 (no
                                                                  `pieces`) is read as the one piece `main`: its `d` with every pad

Exit 2: there is nothing to compare with (HEAD has no manifest, or FILE is unreadable), or the field is missing, has no piece, or has a piece with no solid
voxel (row 1 of REVIEW.md: a fingerprint of nothing would compare equal to another fingerprint of nothing).

Numbers: the field is deterministic, so the voxel count and the hash compare exactly; the volume (cm3, 3 decimals), the extents (mm, 4 decimals) and the pads
(4 decimals) are there to say how large a change is, and compare within TOL_MM.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(HERE, "organic_manifest.json")
MANIFEST_REL = "cad_b6/organic_manifest.json"
FIELD = os.path.join(ROOT, "out", "organic", "field.npz")

FORMAT = 1
LEN_DECIMALS = 4        # mm
VOL_DECIMALS = 3        # cm3
TOL_MM = 1e-3           # on an extent, a pad's centre or normal, the grid's first point and voxel
GRID = "grid"


class Unusable(Exception):
    """The field cannot be fingerprinted (exit 2)."""


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------
def _r(x, n=LEN_DECIMALS):
    x = round(float(x), n)
    return 0.0 if x == 0 else x          # no "-0.0"


def pieces_of(z):
    """{piece: (its field, [(pad name, centre, normal)])} of a saved field (a dict or an NpzFile). A field without `pieces` (before revision 17) is the one piece `main`."""
    files = set(z.files) if hasattr(z, "files") else set(z)
    names = [str(n) for n in z["names"]] if "names" in files else []
    pads = np.asarray(z["pads"], dtype=float).reshape(-1, 6) if "pads" in files else np.zeros((0, 6))
    if len(names) != len(pads):
        raise Unusable(f"{len(pads)} pad rows and {len(names)} pad names")
    if "pieces" not in files:
        return {"main": (z["d"], [(n, p[:3], p[3:]) for n, p in zip(names, pads)])}
    pieces = [str(p) for p in np.atleast_1d(z["pieces"])]
    of_piece = [str(p) for p in z["pad_piece"]]
    if len(of_piece) != len(names):
        raise Unusable(f"{len(of_piece)} pieces named for {len(names)} pads")
    out = {}
    for piece in pieces:
        if "d_" + piece not in files:
            raise Unusable(f"the field names the piece {piece} but has no field d_{piece}")
        out[piece] = (z["d_" + piece], [(n, p[:3], p[3:]) for n, p, k in zip(names, pads, of_piece) if k == piece])
    return out


def mask_hash(d):
    """SHA-256 of the packed solid mask of a field: np.packbits(d < 0) over the whole grid in C order."""
    return hashlib.sha256(np.packbits(np.ascontiguousarray(d < 0)).tobytes()).hexdigest()


def piece_print(d, xs, ys, zs, pads):
    solid = d < 0
    n = int(np.count_nonzero(solid))
    if not n:
        raise Unusable("no solid voxel")
    vox = float(xs[1] - xs[0])
    ext = []
    for axis, g in enumerate((xs, ys, zs)):
        cols = np.flatnonzero(np.any(solid, axis=tuple(k for k in range(3) if k != axis)))
        ext += [_r(g[cols[0]]), _r(g[cols[-1]])]
    return {"voxels": n, "volume_cm3": _r(n * vox ** 3 / 1000.0, VOL_DECIMALS), "centres": ext, "sha256": mask_hash(d),
            "pads": [[name, *(_r(c) for c in q), *(_r(c) for c in nrm)] for name, q, nrm in pads]}


def build_manifest(z):
    """The manifest of a saved field: {"format", "items": {grid, every piece}}. Raises Unusable when there is nothing to fingerprint."""
    pieces = pieces_of(z)
    if not pieces:
        raise Unusable("the field has no piece")
    xs, ys, zs = (np.asarray(z[k], dtype=float) for k in ("xs", "ys", "zs"))
    items = {GRID: {"shape": [len(xs), len(ys), len(zs)], "first": [_r(xs[0]), _r(ys[0]), _r(zs[0])], "vox": _r(xs[1] - xs[0])}}
    for piece, (d, pads) in pieces.items():
        if d.shape != (len(xs), len(ys), len(zs)):
            raise Unusable(f"the piece {piece}'s field has the shape {d.shape}, the grid {(len(xs), len(ys), len(zs))}")
        try:
            items[piece] = piece_print(d, xs, ys, zs, pads)
        except Unusable as e:
            raise Unusable(f"the piece {piece}: {e}") from None
    return {"format": FORMAT, "items": items}


def dumps(m):
    """One line per item's numbers and one per pad, so a git diff of the file reads like the table."""
    out = ['{', f' "format": {m["format"]},', ' "items": {']
    keys = list(m["items"])
    for i, k in enumerate(keys):
        it = dict(m["items"][k])
        pads = it.pop("pads", None)
        tail = "," if i < len(keys) - 1 else ""
        head = json.dumps(it, sort_keys=True)
        if pads is None:
            out.append(f'  {json.dumps(k)}: {head}{tail}')
            continue
        out.append(f'  {json.dumps(k)}: {{"piece": {head}, "pads": [')
        out += [f'    {json.dumps(p)}{"," if j < len(pads) - 1 else ""}' for j, p in enumerate(pads)]
        out.append(f'  ]}}{tail}')
    out += [' }', '}']
    return "\n".join(out) + "\n"


def normalise(m):
    """Bring both shapes of an item (a piece: {"piece":..., "pads":...} in the file, flat in memory) to the flat one."""
    items = {}
    for k, it in m["items"].items():
        if "piece" in it:
            it = {**it["piece"], "pads": it["pads"]}
        items[k] = it
    return items


def loads(text):
    return normalise(json.loads(text))


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def _same(a, b):
    return all(abs(float(x) - float(y)) <= TOL_MM for x, y in zip(a, b)) and len(a) == len(b)


def _fmt(v):
    return f"{v:.4f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def diff_item(old, new):
    """The list of what differs between two fingerprints of a piece (or of the grid), each a short sentence; empty when they agree."""
    out = []
    if "shape" in old or "shape" in new:
        for key in ("shape", "first", "vox"):
            a, b = old.get(key), new.get(key)
            if a is None or b is None or not _same(a if isinstance(a, list) else [a], b if isinstance(b, list) else [b]):
                out.append(f"{key} {a} -> {b}")
        return out
    if old["voxels"] != new["voxels"]:
        out.append(f"solid voxels {old['voxels']} -> {new['voxels']} ({new['voxels'] - old['voxels']:+d}); volume {old['volume_cm3']:.3f} -> {new['volume_cm3']:.3f} cm3")
    if old["sha256"] != new["sha256"]:
        out.append(f"solid mask differs: sha256 {old['sha256'][:12]}... -> {new['sha256'][:12]}...")
    for label, a, b in zip(("X min", "X max", "Y min", "Y max", "Z min", "Z max"), old["centres"], new["centres"]):
        if abs(a - b) > TOL_MM:
            out.append(f"centres' {label} {_fmt(a)} -> {_fmt(b)} ({b - a:+.3f})")
    po, pn = {p[0]: p[1:] for p in old["pads"]}, {p[0]: p[1:] for p in new["pads"]}
    for name in sorted(set(po) | set(pn)):
        if name not in pn:
            out.append(f"  - pad {name} at ({', '.join(_fmt(c) for c in po[name][:3])})")
        elif name not in po:
            out.append(f"  + pad {name} at ({', '.join(_fmt(c) for c in pn[name][:3])}) normal ({', '.join(_fmt(c) for c in pn[name][3:])})")
        elif not _same(po[name], pn[name]):
            out.append(f"  ~ pad {name} ({', '.join(_fmt(c) for c in po[name])}) -> ({', '.join(_fmt(c) for c in pn[name])})")
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
    return lines


def judge(old, new, expect):
    """(exit code, lines) of a comparison of two normalised manifests: 0, or 1 when `expect` is a list and something outside it differs."""
    added, removed, changed = compare(old, new)
    lines = report(added, removed, changed, len(old), len(new))
    if expect is None:
        return 0, lines
    differ = set(added) | set(removed) | set(changed)
    bad = outside(differ, expect)
    unused = [p for p in expect if not any(fnmatch.fnmatchcase(n, p) for n in differ)]
    lines.append("")
    if unused:
        lines.append("expected but not different: " + ", ".join(unused))
    if bad:
        lines.append("FAIL: outside the expected list: " + ", ".join(bad))
        return 1, lines
    lines.append(f"OK: every difference is in the expected list ({', '.join(expect)})")
    return 0, lines


def head_manifest():
    r = subprocess.run(["git", "show", f"HEAD:{MANIFEST_REL}"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return loads(r.stdout)


def main(argv):
    expect, against, field, write = None, None, FIELD, False
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--write":
            write = True
        elif a == "--expect" and args:
            expect = [p.strip() for p in args.pop(0).split(",") if p.strip()]
        elif a == "--against" and args:
            against = args.pop(0)
        elif a == "--field" and args:
            field = args.pop(0)
        else:
            print(__doc__)
            return 2
    old, base = None, None
    if not write:                 # find the baseline before reading the field, so a missing one fails at once
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
    if not os.path.exists(field):
        print(f"{field} is missing: run cad_b6/organic_frame.py first (it writes the layer's field)")
        return 2
    try:
        new_m = build_manifest(np.load(field))
    except Unusable as e:
        print(f"{field}: {e}")
        return 2
    for k, it in new_m["items"].items():
        if k != GRID:
            print(f"{k:12} {it['voxels']:9d} voxels  {it['volume_cm3']:9.3f} cm3  sha256 {it['sha256']}  pads {', '.join(p[0] for p in it['pads'])}")
    if write:
        with open(MANIFEST, "w") as f:
            f.write(dumps(new_m))
        print(f"wrote {MANIFEST} from {field} ({len(new_m['items']) - 1} pieces and the grid)")
        return 0
    code, lines = judge(old, normalise(new_m), expect)
    print(f"{field} compared with {base}   (voxel counts and mask hashes exactly; extents, pads and the grid within {TOL_MM:g} mm)")
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
