"""A push on the middle of every film strand and every cross-thread of a sketch's layer, judged as organic_strength.py judges its own pushes.

organic_strength.py pushes at 160 places spread over the surface. Whether one of them lands on the middle of a thin member is chance: the front film's longest cross-thread
showed 29.7 MPa only after two new pads had shifted the sample. This run takes the chance out for the films.

Run from the repository root:  .venv/bin/python docs/plans/sketches/member_probes.py <field.npz of cable_gate_sketch.py --under>
"""
import os
import sys

import numpy as np
from scipy import sparse
from scipy.spatial import cKDTree

ROOT = os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "cad_b6"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import organic_frame as of
import organic_strength as st
import cable_gate_sketch as cg


def main():
    st.FIELD = sys.argv[1]
    cg.patch_gate(under=True)
    mids = []                                                    # (film, kind, mid-span point, length)
    for fi, film in enumerate(of.film_list()):
        three = [m for m in film if m[0] == "tube" and len(m[1]) == 3 and m[3] in (10.0, 7.0)]
        for m in three:
            a, mid, b = (np.array(p, dtype=float) for p in m[1])
            mids.append((fi, "strand" if m[3] == 10.0 else "link", 0.25 * a + 0.5 * mid + 0.25 * b, float(np.linalg.norm(b - a))))
    h, pads, names, conn, X, held, dropped = st.voxel_mesh(1, "main")
    ne, nn = len(conn), len(X)
    Ke, B0, D = st.cube_stiffness(h)
    dofs = (3 * conn[:, :, None] + np.arange(3)[None, None, :]).reshape(ne, 24)
    K = None
    for s in range(0, ne, 100_000):
        d = dofs[s:s + 100_000].astype(np.int32)
        part = sparse.coo_matrix((np.tile(Ke.ravel(), len(d)), (np.repeat(d, 24, axis=1).ravel(), np.tile(d, (1, 24)).ravel())), shape=(3 * nn, 3 * nn)).tocsr()
        K = part if K is None else K + part
    fixed = np.repeat(held >= 0, 3)
    free = np.where(~fixed)[0]
    solve, solver, block = st.factorize(K[free][:, free].tocsr())
    del K
    tree = cKDTree(X)
    count = np.bincount(conn.ravel(), minlength=nn)
    surf = np.where((count < 8) & (held < 0))[0]
    stree = cKDTree(X[surf])
    DB = D @ B0
    cen = X[conn].mean(axis=1)
    clamped = (held[conn] >= 0).any(axis=1)
    rows = []
    for fi, kind, q, length in mids:
        dist, j = stree.query(q)
        if dist > 8.0:                                           # the member was carved away there (a strand that ended in a clearance)
            rows.append((fi, kind, q, length, None, None, "no material within 8 mm"))
            continue
        p = int(surf[j])
        near = tree.query_ball_point(X[p], 12.0)
        outward = X[p] - X[near].mean(axis=0)
        outward /= max(np.linalg.norm(outward), 1e-9)
        patch = [n for n in tree.query_ball_point(X[p], st.FINGER_R) if held[n] < 0]
        worst = (0.0, 0.0, "")
        for label, direction in (("inward", -outward), ("down", np.array([0.0, 0.0, -1.0]))):
            f = np.zeros(3 * nn)
            for n in patch:
                f[3 * n:3 * n + 3] += st.PUSH_N * direction / len(patch)
            u = np.zeros(3 * nn)
            u[free] = solve(f[free][:, None])[:, 0]
            vm = st.von_mises(u[dofs] @ DB.T)
            vm = np.where(np.linalg.norm(cen - X[p], axis=1) < st.FINGER_R + 2 * h, 0.0, vm)
            vm = np.where(clamped, 0.0, vm)
            move = float(np.linalg.norm(u.reshape(-1, 3), axis=1).max())
            if float(vm.max()) > worst[0]:
                worst = (float(vm.max()), move, label)
        rows.append((fi, kind, X[p], length, worst[0], worst[1], worst[2]))
        print(f"film {fi} {kind:6} {length:5.0f} mm at ({X[p][0]:5.0f},{X[p][1]:4.0f},{X[p][2]:4.0f}): {worst[0]:5.1f} MPa, {worst[1]:.2f} mm ({worst[2]})" + ("   OVER" if worst[0] > st.ALLOW or worst[1] > st.MOVE_MAX else ""), flush=True)
    done = [r for r in rows if r[4] is not None]
    over = [r for r in done if r[4] > st.ALLOW or r[5] > st.MOVE_MAX]
    print(f"{len(done)} members pushed at mid-span ({len(rows) - len(done)} carved away there); worst {max(r[4] for r in done):.1f} MPa, {max(r[5] for r in done):.2f} mm; {len(over)} over {st.ALLOW:g} MPa or {st.MOVE_MAX:g} mm")


if __name__ == "__main__":
    main()
