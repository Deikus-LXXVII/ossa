"""The test suite's record, shared by the writer (test_checks.py) and the reader (check_budgets.py) so that both compute it the same way.

  - The digest: the record names every file that decides the suite's result (each cad_b6/*.py the run imported, in the parent and in
    every worker, and the generated inputs it reads) with the SHA-256 it had when the run started. A reader recomputes those hashes on
    the working tree: a record whose files changed since is of other code and is not a figure of this one.
  - The environment: the Python version and the version of every third-party distribution that provides a module the run loaded, in the
    parent or in any worker (found from sys.modules, mapped to distributions by importlib.metadata): cadquery, cadquery-ocp (OCP), numpy,
    scipy, vtk, trimesh (loaded only in the workers), matplotlib, pillow and what they load in turn (casadi, nlopt, ezdxf, ...). None is
    left out by name: a package the suite loads can change a result, and a list kept by hand would miss the next one; a version change in
    a package that cannot change a result costs one rerun. The standard library is covered by the Python version, the project's own
    modules by the digest. A reader compares the versions installed now: a record of other packages is refused too.
  - When the hashes are taken: test_checks.py hashes the tree at its import, before it imports any of the model's modules, and again at
    the end of the run; a file whose hash moved fails the run (a worker, which imports later, may have run other bytes than the parent).
    What remains open: test_checks.py and this file are read by the interpreter a few milliseconds before that first hash, and a file
    changed and changed back during a run is not seen.
  - The pinned number of cases: test_checks.EXPECTED_CASES, read from the source without importing the suite (which builds nothing at
    import but loads cadquery and every module).
  - Writing a record atomically: a temporary file in the same folder, then a rename, so that a killed run leaves the previous record
    whole (or none), never half of one.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import platform
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TEST_CHECKS = os.path.join(HERE, "test_checks.py")
DATA_INPUTS = ("out/organic/field.npz",)          # generated inputs the suite reads (drive_access.py loads the organic layer's field)


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def tree_hashes(root=ROOT):
    """{relative path: sha256} of every cad_b6/*.py and every data input that exists, read now (the start of a run)."""
    here = os.path.join(root, "cad_b6")
    rels = [f"cad_b6/{n}" for n in sorted(os.listdir(here)) if n.endswith(".py")] + [r for r in DATA_INPUTS if os.path.exists(os.path.join(root, r))]
    return {r: file_sha(os.path.join(root, r)) for r in rels}


def loaded_sources(modules=None):
    """Relative paths of the cad_b6/*.py files loaded in this process (sys.modules), plus the data inputs: the files that decide what it computed."""
    out = set()
    for m in list((modules if modules is not None else sys.modules).values()):
        path = getattr(m, "__file__", None)
        if path and path.endswith(".py") and os.path.dirname(os.path.realpath(path)) == os.path.realpath(HERE):
            out.add("cad_b6/" + os.path.basename(path))
    return out | set(DATA_INPUTS)


def loaded_top_levels(modules=None):
    """The top-level names of the modules loaded in this process (sys.modules): environment() maps them to the distributions that provide them."""
    return {name.split(".")[0] for name in (modules if modules is not None else sys.modules)}


def environment(top_levels):
    """{'python': version, 'implementation': name, 'packages': {distribution: version}} for the third-party distributions that provide any of
    `top_levels` (the standard library and the project's own modules provide no distribution, so they drop out)."""
    from importlib import metadata

    owners = metadata.packages_distributions()
    packages = {}
    for d in sorted({d for t in top_levels for d in owners.get(t, ())}):
        try:
            packages[d] = metadata.version(d)
        except metadata.PackageNotFoundError:
            continue
    return dict(python=platform.python_version(), implementation=sys.implementation.name, packages=packages)


def stale_environment(env):
    """How the interpreter now differs from the recorded environment: [(what, recorded, now)]; empty when the same."""
    from importlib import metadata

    out = []
    for key, now in (("python", platform.python_version()), ("implementation", sys.implementation.name)):
        if env.get(key) != now:
            out.append((key, env.get(key), now))
    for d, v in sorted((env.get("packages") or {}).items()):
        try:
            now = metadata.version(d)
        except metadata.PackageNotFoundError:
            now = None
        if now != v:
            out.append((d, v, now))
    return out


def sources_of(rels, hashes):
    """{relative path: sha256 at the start} of the files in `rels` that existed then (a data input that did not is left out: nothing was read)."""
    return {r: hashes[r] for r in sorted(rels) if r in hashes}


def digest(sources, env=None):
    """One SHA-256 over the sorted (path, sha256) pairs and, when given, the environment's Python and package versions."""
    text = "".join(f"{r} {s}\n" for r, s in sorted(sources.items()))
    if env is not None:
        text += f"python {env.get('python')} {env.get('implementation')}\n" + "".join(f"package {d} {v}\n" for d, v in sorted((env.get("packages") or {}).items()))
    return hashlib.sha256(text.encode()).hexdigest()


def stale_sources(sources, root=ROOT):
    """The recorded files whose content differs now (or that are gone): [(path, why)]; empty when the record belongs to the working tree."""
    out = []
    for r, s in sorted(sources.items()):
        p = os.path.join(root, r)
        if not os.path.exists(p):
            out.append((r, "gone"))
        elif file_sha(p) != s:
            out.append((r, "changed"))
    return out


def pinned_cases(path=TEST_CHECKS):
    """EXPECTED_CASES as written in test_checks.py (a literal int), or None when it is not there."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "EXPECTED_CASES" for t in node.targets) \
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, int):
            return node.value.value
    return None


def short_of_pin(n_cases, sections, pinned):
    """Why a run's case list is not the whole suite: fewer cases than pinned, or a section (or the prelude) that recorded none. [] when whole.
    sections: [(title, number of cases)]."""
    out = [f"section '{t}' recorded no case" for t, n in sections if n == 0]
    if pinned is None:
        out.append("no EXPECTED_CASES in test_checks.py")
    elif n_cases < pinned:
        out.append(f"{n_cases} cases recorded, EXPECTED_CASES is {pinned}: {pinned - n_cases} missing (a section emptied or cut short)")
    return out


def write_json_atomic(path, obj):
    """json.dump to a temporary file next to `path`, then rename it over `path`: a reader sees the old file or the new one, whole."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix="." + os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
