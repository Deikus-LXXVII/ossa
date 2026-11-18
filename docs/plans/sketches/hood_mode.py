"""Where the layer moves when the hood over the front I/O module is pushed: one load case at a time, the displacement at named places.

Written to explain a 4.87 mm movement (limit 5) that organic_strength.py reported for a push on the hood's right cheek and that a shorter, thicker cheek did not change.
Result on the field of cable_gate_sketch.py --under before the pads front_post_R/L (3 mm voxels): the largest movement is 5.48 mm at the right post's foot (167, 7, -9), the
post moves 4.65 mm at Z 30, 3.17 at Z 110 and 2.43 at Z 160, the left post 0.27. The right post swings back about its top: its foot is held by nothing.

Run from the repository root:  .venv/bin/python docs/plans/sketches/hood_mode.py <field.npz> [voxel step, default 2]
"""
import sys
import numpy as np
from scipy import sparse
from scipy.spatial import cKDTree
sys.path.insert(0, "cad_b6")
import organic_strength as st

st.FIELD = sys.argv[1]
step = int(sys.argv[2]) if len(sys.argv) > 2 else 2
h, pads, names, conn, X, held, dropped = st.voxel_mesh(step, "main")
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
Kf = K[free][:, free].tocsr()
solve, solver, block = st.factorize(Kf)
tree = cKDTree(X)
count = np.bincount(conn.ravel(), minlength=nn)
surf = np.where((count < 8) & (held < 0))[0]
stree = cKDTree(X[surf])
probes = {"bar front_low X -160": (-160, 22, 60), "bar X -92": (-92, 22, 60), "bar X 0": (0, 22, 60), "bar X 60": (60, 22, 60), "bar X 117": (117, 22, 60), "bar X 160": (160, 22, 60),
          "roof front, middle": (0, 0, 59), "roof front, right": (117, 0, 59), "roof rear, right": (117, 44, 59), "right cheek tip": (117, 5, 14), "left cheek tip": (-92, 5, 14),
          "right post Z 30": (158.5, 14.5, 30), "right post Z 60": (159, 15, 60), "right post Z 110": (162, 17, 110), "right post Z 160": (165, 20, 160), "brow X 117": (117, 13, 152),
          "brow X 0": (0, 13, 152), "film X 117 Z 105": (117, 17, 105)}
for push_at in [(116, 0, 26), (0, -2, 59), (117, 22, 68)]:
    p = int(surf[stree.query(push_at)[1]])
    near = tree.query_ball_point(X[p], 12.0)
    outward = X[p] - X[near].mean(axis=0)
    outward /= max(np.linalg.norm(outward), 1e-9)
    patch = [q for q in tree.query_ball_point(X[p], st.FINGER_R) if held[q] < 0]
    for label, direction in (("inward", -outward), ("down", np.array([0.0, 0.0, -1.0]))):
        f = np.zeros(3 * nn)
        for q in patch:
            f[3 * q:3 * q + 3] += st.PUSH_N * direction / len(patch)
        u = np.zeros(3 * nn)
        u[free] = solve(f[free][:, None])[:, 0]
        U = u.reshape(-1, 3)
        mag = np.linalg.norm(U, axis=1)
        k = int(np.argmax(mag))
        print(f"\npush at ({X[p][0]:.0f}, {X[p][1]:.0f}, {X[p][2]:.0f}) {label} ({direction[0]:+.2f}, {direction[1]:+.2f}, {direction[2]:+.2f}): largest {mag[k]:.2f} mm at ({X[k][0]:.0f}, {X[k][1]:.0f}, {X[k][2]:.0f}), moving ({U[k][0]:+.2f}, {U[k][1]:+.2f}, {U[k][2]:+.2f})", flush=True)
        for name, q in probes.items():
            dist, j = tree.query(q)
            print(f"   {name:22} ({X[j][0]:5.0f},{X[j][1]:4.0f},{X[j][2]:4.0f}) off {dist:4.1f}: ({U[j][0]:+.2f}, {U[j][1]:+.2f}, {U[j][2]:+.2f})  {mag[j]:.2f}")
