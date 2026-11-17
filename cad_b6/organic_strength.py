#!/usr/bin/env python3
"""How weak is the organic layer? Push on it everywhere and see what gives.

Run:  .venv/bin/python cad_b6/organic_strength.py [step]      (after organic_frame.py, which writes out/organic/field.npz)
Out:  cad_b6/report_organic_strength.txt, out/organic/strength.npz

step = 1 uses the field's own grid (1.5 mm), 2 uses every second point (3 mm, quick, too stiff for thin strands).

Method (linear static finite elements on the voxels of the field):
- every voxel inside the layer is one 8-node cube of solid PETG, taken with the ABS figures of strength.py (the fallback material); all cubes are identical, so one element matrix serves all;
- fixed at the fixing pads (the first 2 mm above each skeleton face, inside the pad's radius);
- load cases: the layer's own weight, and a push of PUSH_N newtons at each of N_POINTS places spread over the surface, once
  straight into the surface and once straight down, spread over a fingertip (FINGER_R).
For every push it records the largest movement and the largest stress away from the fingertip itself, and the force each
fixing screw has to hold. What it does not cover: layer direction and infill of the print (the model is solid, isotropic, with ABS figures),
creep near warm parts, impact, and anyone lifting the PC by the organic layer, which it is not made for.
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
from scipy import ndimage, sparse
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

E, NU, RHO = 2000.0, 0.35, 1.27e-9          # ABS figures of strength.py (E, nu), PETG's density: MPa, -, tonne/mm3
STRENGTH_LAYER = 20.0                       # MPa across layers, the weak direction of a print (strength.py's ABS figure)
SAFETY = 2.0                                # for a rare hand load
ALLOW = STRENGTH_LAYER / SAFETY
PUSH_N = 30.0                               # a firm push with a hand
MOVE_MAX = 5.0                              # mm: no push of PUSH_N may move the layer more than this (revision 14b, second pass)
FINGER_R = 6.0
N_POINTS = 160
PAD_FIX_H = 2.0                             # nodes this far above a skeleton face, inside the pad, are held
PAD_R = 8.0
G = 9810.0                                  # mm/s2
CHUNK = 32                                  # load cases solved together where memory is short (Accelerate, SuperLU)


def cube_stiffness(h):
    """Stiffness matrix (24 x 24) of an h-sided cube, and the strain matrix B (6 x 24) at its centre."""
    lam = E * NU / ((1 + NU) * (1 - 2 * NU))
    mu = E / (2 * (1 + NU))
    D = np.zeros((6, 6))
    D[:3, :3] = lam
    D[np.arange(3), np.arange(3)] += 2 * mu
    D[np.arange(3, 6), np.arange(3, 6)] = mu
    corners = np.array([[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1], [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]], dtype=float)

    def bmat(xi):
        dN = corners * (1 + corners[:, [1, 2, 0]] * xi[[1, 2, 0]]) * (1 + corners[:, [2, 0, 1]] * xi[[2, 0, 1]]) / 8.0   # d/dxi, d/deta, d/dzeta
        dN = dN * (2.0 / h)
        B = np.zeros((6, 24))
        for a in range(8):
            dx, dy, dz = dN[a]
            B[0, 3 * a], B[1, 3 * a + 1], B[2, 3 * a + 2] = dx, dy, dz
            B[3, 3 * a], B[3, 3 * a + 1] = dy, dx
            B[4, 3 * a + 1], B[4, 3 * a + 2] = dz, dy
            B[5, 3 * a], B[5, 3 * a + 2] = dz, dx
        return B

    g = 1 / np.sqrt(3)
    Ke = np.zeros((24, 24))
    for sx in (-g, g):
        for sy in (-g, g):
            for sz in (-g, g):
                B = bmat(np.array([sx, sy, sz]))
                Ke += B.T @ D @ B * (h / 2) ** 3
    return Ke, bmat(np.zeros(3)), D


def factorize(Kff):
    """Factor the stiffness once; returns (solve for a block of right-hand sides, solver name, load cases per block or None for all at once). MKL Pardiso where
    pypardiso is installed (x86), else Accelerate's sparse LDLT where macldlt is installed (Apple silicon), else SuperLU."""
    try:
        import pypardiso
        return (lambda B: pypardiso.spsolve(Kff, B, squeeze=False)), "MKL Pardiso", None    # one call, as before: each call hashes the 2 GB matrix
    except ImportError:
        pass
    try:
        import macldlt
    except ImportError:
        from scipy.sparse.linalg import splu
        lu = splu(Kff.tocsc())
        return lu.solve, "SuperLU", CHUNK
    upper = sparse.triu(Kff, format="csc")
    upper.sort_indices()
    # nested dissection: at step 1 its factor is about 9 GB, the default ordering's does not fit in 18 GB
    ldlt = macldlt.LDLTSolver(upper, triangle="upper", ordering="metis")
    neg, zero, _ = ldlt.inertia()
    if neg or zero:
        raise RuntimeError(f"stiffness not positive definite: {neg} negative and {zero} zero pivots")
    b = Kff @ np.ones(Kff.shape[0])                            # one probe solve; a residual on every block costs a minute of matrix products at step 1
    rel = np.linalg.norm(Kff @ ldlt.solve(b) - b) / np.linalg.norm(b)
    if not rel < 1e-6:
        raise RuntimeError(f"Accelerate LDLT residual {rel:.1e}")
    # macldlt 0.0.1 traps on a one-column block
    return (lambda B: ldlt.solve(B[:, 0]).reshape(B.shape) if B.shape[1] == 1 else ldlt.solve(np.asfortranarray(B))), "Accelerate LDLT", CHUNK


def von_mises(sig):
    s = sig
    return np.sqrt(0.5 * ((s[:, 0] - s[:, 1]) ** 2 + (s[:, 1] - s[:, 2]) ** 2 + (s[:, 2] - s[:, 0]) ** 2) + 3 * (s[:, 3] ** 2 + s[:, 4] ** 2 + s[:, 5] ** 2))


def voxel_mesh(step):
    """The voxels of the field inside the layer that are connected to a pad. Returns (h, pads, names, conn, X, held, dropped cm3); the full-grid arrays it
    works on (several GB at step 1) are freed when it returns, before the factorisation needs the memory."""
    f = np.load(os.path.join(ROOT, "out", "organic", "field.npz"))
    d, xs, ys, zs = f["d"][::step, ::step, ::step], f["xs"][::step], f["ys"][::step], f["zs"][::step]
    pads, names = f["pads"], [str(n) for n in f["names"]]
    h = float(xs[1] - xs[0])
    # a cell is solid if the mean of its 8 corners is inside
    c = sum(d[i:d.shape[0] - 1 + i, j:d.shape[1] - 1 + j, k:d.shape[2] - 1 + k] for i in (0, 1) for j in (0, 1) for k in (0, 1)) / 8.0
    solid = c < 0
    nxn, nyn, nzn = d.shape

    def nid(i, j, k):
        return (i * nyn + j) * nzn + k

    # nodes held by the pads
    ii, jj, kk = np.meshgrid(np.arange(nxn), np.arange(nyn), np.arange(nzn), indexing="ij")
    P = np.stack([xs[ii], ys[jj], zs[kk]], axis=-1).reshape(-1, 3)
    held = np.zeros(len(P), dtype=np.int32) - 1
    for a, row in enumerate(pads):
        q, n = row[:3], row[3:]
        v = P - q
        hh = v @ n
        rad = np.sqrt(np.maximum((v * v).sum(axis=1) - hh * hh, 0.0))
        held[(hh > -0.5 * h) & (hh < PAD_FIX_H + 0.5 * h) & (rad < PAD_R)] = a
    # keep the pieces that touch a pad (face-connected cells)
    lab, n = ndimage.label(solid)
    cell_nodes = np.stack([nid(ii[:-1, :-1, :-1] + di, jj[:-1, :-1, :-1] + dj, kk[:-1, :-1, :-1] + dk)
                           for (di, dj, dk) in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))], axis=-1)
    keep = np.zeros(n + 1, dtype=bool)
    held_cells = (held[cell_nodes] >= 0).any(axis=-1) & solid
    keep[np.unique(lab[held_cells])] = True
    keep[0] = False
    dropped = float((solid & ~keep[lab]).sum()) * h ** 3 / 1000.0
    solid &= keep[lab]
    conn = cell_nodes[solid]                                   # (ne, 8) global node ids
    used = np.unique(conn)
    remap = np.zeros(len(P), dtype=np.int64) - 1
    remap[used] = np.arange(len(used))
    conn = remap[conn]
    return h, pads, names, conn, P[used], held[used], dropped


def main():
    step = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    t0 = time.time()
    h, pads, names, conn, X, held, dropped = voxel_mesh(step)
    ne, nn = len(conn), len(X)
    out = [f"ПРОЧНОСТЬ ОРГАНИЧЕСКОГО СЛОЯ: воксели {h:g} мм, {ne} элементов, {nn} узлов; сплошной PETG (цифры ABS из strength.py), E {E:g} МПа",
           f"Объём в расчёте {ne * h ** 3 / 1000:.0f} см³ ({ne * h ** 3 * RHO * 1e6:.0f} г); не связано с креплениями и отброшено {dropped:.1f} см³",
           f"Закреплено у {len(pads)} площадок: {int((held >= 0).sum())} узлов"]
    assert all((held == a).any() for a in range(len(pads))), "a pad holds no node: " + ", ".join(names[a] for a in range(len(pads)) if not (held == a).any())

    Ke, B0, D = cube_stiffness(h)
    dofs = (3 * conn[:, :, None] + np.arange(3)[None, None, :]).reshape(ne, 24)
    K = None
    for s in range(0, ne, 100_000):                            # in slices: all elements' triplets at once peak near 10 GB at step 1
        d = dofs[s:s + 100_000].astype(np.int32)
        part = sparse.coo_matrix((np.tile(Ke.ravel(), len(d)), (np.repeat(d, 24, axis=1).ravel(), np.tile(d, (1, 24)).ravel())), shape=(3 * nn, 3 * nn)).tocsr()
        K = part if K is None else K + part
    del part
    fixed = np.repeat(held >= 0, 3)
    free = np.where(~fixed)[0]
    held_dofs = np.where(fixed)[0]
    K_held = K[held_dofs]                                      # the rows the reactions need; the full K is not kept
    pad_of = held[held >= 0]                                   # pad of each held node, in the order of K_held's rows
    K_free = K[free][:, free].tocsr()
    del K

    # surface points to push on: farthest-point sampling over surface nodes away from the pads
    count = np.bincount(conn.ravel(), minlength=nn)
    surf = np.where((count < 8) & (held < 0))[0]
    tree = cKDTree(X)
    far = np.ones(len(surf), dtype=bool)
    for row in pads:
        far &= np.linalg.norm(X[surf] - row[:3], axis=1) > 30.0
    surf = surf[far]
    picks = [int(surf[np.argmax(X[surf, 2])])]
    dist = np.linalg.norm(X[surf] - X[picks[0]], axis=1)
    for _ in range(N_POINTS - 1):
        j = int(np.argmax(dist))
        picks.append(int(surf[j]))
        dist = np.minimum(dist, np.linalg.norm(X[surf] - X[surf[j]], axis=1))
    # outward direction at a pick: away from the mass of nearby nodes
    cases, meta = [], []                                       # each load case as a sparse column: 321 dense ones are 5 GB
    w = np.zeros(3 * nn)
    np.add.at(w, 3 * conn.ravel() + 2, -RHO * G * h ** 3 / 8.0)
    cases.append(sparse.csc_matrix(w[:, None]))
    meta.append(("вес", None, None))
    for p in picks:
        near = tree.query_ball_point(X[p], 12.0)
        outward = X[p] - X[near].mean(axis=0)
        outward = outward / max(np.linalg.norm(outward), 1e-9)
        patch = [q for q in tree.query_ball_point(X[p], FINGER_R) if held[q] < 0]
        for label, direction in (("внутрь", -outward), ("вниз", np.array([0.0, 0.0, -1.0]))):
            rows = (3 * np.array(patch)[:, None] + np.arange(3)).ravel()
            vals = np.tile(PUSH_N * direction / len(patch), len(patch))
            cases.append(sparse.csc_matrix((vals, (rows, np.zeros(len(rows), dtype=np.int64))), shape=(3 * nn, 1)))
            meta.append((label, p, direction))
    Bm = sparse.hstack(cases, format="csc")
    Bf = Bm[free]
    out.append(f"Сборка {time.time() - t0:.0f} с; случаев нагрузки {Bm.shape[1]}: вес и {len(picks)} точек x 2 направления по {PUSH_N:g} Н на пятно радиусом {FINGER_R:g} мм")
    t1 = time.time()
    solve, solver, block = factorize(K_free)
    block = block or Bm.shape[1]
    del K_free
    t_solve = time.time() - t1

    DB = D @ B0
    res = []
    reactions = np.zeros((len(pads), Bm.shape[1]))
    cen = X[conn].mean(axis=1)
    clamped = (held[conn] >= 0).any(axis=1)
    for j in range(Bm.shape[1]):
        if j % block == 0:                                     # a block of right-hand sides at a time, so the answers need not all sit in memory
            t1 = time.time()
            U = solve(Bf[:, j:j + block].toarray())
            t_solve += time.time() - t1
        u = np.zeros(3 * nn)
        u[free] = U[:, j % block]
        vm = von_mises((u[dofs] @ DB.T))
        label, p, direction = meta[j]
        if p is not None:
            vm = np.where(np.linalg.norm(cen - X[p], axis=1) < FINGER_R + 2 * h, 0.0, vm)      # not the contact itself
        vm = np.where(clamped, 0.0, vm)                                                        # nor the clamped nodes (a rigid clamp is harsher than a screw)
        e = int(np.argmax(vm))
        mag = np.linalg.norm(u.reshape(-1, 3), axis=1)
        r = (K_held @ u - Bm[held_dofs, j].toarray().ravel()).reshape(-1, 3)
        for a in range(len(pads)):
            reactions[a, j] = np.linalg.norm(r[pad_of == a].sum(axis=0))
        res.append((label, None if p is None else X[p], float(mag.max()), float(vm.max()), cen[e]))
    out.append(f"Решение {t_solve:.0f} с ({solver}), неизвестных {len(free)}")
    out.append("")
    lab_, _, sag, s, where = res[0]
    out.append(f"Собственный вес: наибольшее смещение {sag:.3f} мм, напряжение {s:.2f} МПа у X {where[0]:.0f}, Y {where[1]:.0f}, Z {where[2]:.0f}")
    out.append(f"Допустимое напряжение {ALLOW:g} МПа (прочность поперёк слоёв, цифра ABS {STRENGTH_LAYER:g} МПа, запас {SAFETY:g} для редкой нагрузки рукой)")
    pushes = res[1:]
    over = [r_ for r_ in pushes if r_[3] > ALLOW]
    out.append(f"Толчки {PUSH_N:g} Н: напряжение выше допустимого в {len(over)} случаях из {len(pushes)}; "
               f"медиана напряжения {np.median([r_[3] for r_ in pushes]):.1f} МПа, медиана смещения {np.median([r_[2] for r_ in pushes]):.2f} мм")
    worst = max(pushes, key=lambda r_: r_[2])
    out.append(f"Толчки {PUSH_N:g} Н: наибольшее смещение {worst[2]:.2f} мм (давим {worst[0]} в X {worst[1][0]:.0f}, Y {worst[1][1]:.0f}, Z {worst[1][2]:.0f}), предел {MOVE_MAX:g} мм; "
               f"выше предела в {sum(r_[2] > MOVE_MAX for r_ in pushes)} случаях из {len(pushes)}")
    out.append("")
    out.append("Десять самых слабых мест по напряжению (куда давят -> где наибольшее напряжение):")
    for label, p, m, s, where in sorted(pushes, key=lambda r_: -r_[3])[:10]:
        out.append(f"  {s:6.1f} МПа (запас {ALLOW / s:4.1f}), смещение {m:5.2f} мм: давим {label:6} в X {p[0]:5.0f}, Y {p[1]:4.0f}, Z {p[2]:4.0f} -> X {where[0]:5.0f}, Y {where[1]:4.0f}, Z {where[2]:4.0f}")
    out.append("Десять самых податливых мест (смещение под рукой):")
    for label, p, m, s, where in sorted(pushes, key=lambda r_: -r_[2])[:10]:
        out.append(f"  {m:5.2f} мм, {s:6.1f} МПа: давим {label:6} в X {p[0]:5.0f}, Y {p[1]:4.0f}, Z {p[2]:4.0f}")
    out.append("")
    out.append("Наибольшая сила на каждом креплении по всем случаям, Н (и от собственного веса):")
    for a, name in enumerate(names):
        out.append(f"  {name:14} {reactions[a, 1:].max():6.1f}   ({reactions[a, 0]:.2f})")
    out.append("")
    out.append(f"Время {time.time() - t0:.0f} с.")
    text = "\n".join(out)
    with open(os.path.join(HERE, "report_organic_strength.txt"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)
    np.savez_compressed(os.path.join(ROOT, "out", "organic", "strength.npz"),
                        points=np.array([r_[1] for r_ in pushes]), labels=np.array([r_[0] for r_ in pushes]),
                        move=np.array([r_[2] for r_ in pushes]), stress=np.array([r_[3] for r_ in pushes]), where=np.array([r_[4] for r_ in pushes]),
                        reactions=reactions)


if __name__ == "__main__":
    main()
