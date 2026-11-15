#!/usr/bin/env python3
"""B6 layout study: candidate arrangements where neither pump (CPU block,
GPU card) is the highest point of its loop. Block-out only, no frame.

Run:  .venv/bin/python layout_b6_options.py
Out:  previews/layout_b6_options.png  + a text table on stdout.

Axes (mm): X right (seen from the front), Y depth (front = 0), Z up,
hardware zero at Z = 0 (feet go below).

Board space (v, u, n): v from the rear-I/O edge along the 244 side,
u from the bottom (PCIe/audio) edge along the 305 side towards the CPU,
n out of the component face.
"""
from __future__ import annotations

import itertools
import math
import os
from dataclasses import dataclass, field

import cadquery as cq
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon

ROOT = os.path.dirname(os.path.abspath(__file__))

# --- hardware (manufacturer figures, see HANDOFF + hardware facts report) ---
BOARD_U, BOARD_V, BOARD_T = 305.0, 244.0, 2.0
GPU_LEN, GPU_H, GPU_T = 280.0, 150.0, 51.0     # 148 card + ~2 slot seating
GPU_SLOT_U = 126.6            # card's upper face (PCB on slot 6, u = 124.08, + 2.5); cooler hangs towards u = 0
GPU_V0 = -2.0                 # bracket just outside the I/O edge
GPU_PUMP = (140.0, GPU_SLOT_U - GPU_T / 2, 70.0)      # mid-card (assumed)
GPU_PUMP_TOP_N = 100.0        # worst-case top of the pump housing (assumed)
CPU_V, CPU_U = 134.0, 217.0   # socket centre, measured on the board scan (refs/board_scan_overlay.png), +-3
BLOCK_V, BLOCK_U, BLOCK_N = 108.5, 108.5, 75.0  # square envelope: which way the 108.5 side lies is unconfirmed
R420 = (458.0, 138.0, 68.0)   # length, width, stack (ARCTIC spec: 38 core + 27 fan + hardware)
R360 = (394.0, 121.0, 55.0)
FIT420 = 19.0                 # fixed fittings past the 420 end face
PSU = (210.0, 150.0, 86.0)
TUBE_CPU, TUBE_GPU = 500.0, 450.0
SLACK = 1.30                  # same rule as HANDOFF: path x 1.3 <= tube


@dataclass
class Option:
    key: str
    title: str
    theta: float                       # board tilt, deg
    x0: float                          # world X of the I/O edge
    y0: float                          # world Y,Z of the board's bottom edge
    z0: float
    r420: tuple                        # world AABB (x0,x1,y0,y1,z0,z1)
    r360: tuple
    psu: tuple
    tube_cpu: list = field(default_factory=list)   # waypoints after the block
    tube_gpu: list = field(default_factory=list)   # waypoints after the card
    r360_b: tuple | None = None        # 360 given in board space (v0,v1,u0,u1,n0,n1)
    r420_b: tuple | None = None        # 420 given in board space

    def bp(self, v, u, n):
        c, s = math.cos(math.radians(self.theta)), math.sin(math.radians(self.theta))
        return (self.x0 + v, self.y0 + u * c - n * s, self.z0 + u * s + n * c)

    def bbox(self, v0, v1, u0, u1, n0, n1) -> cq.Shape:
        b = cq.Solid.makeBox(v1 - v0, u1 - u0, n1 - n0, cq.Vector(v0, u0, n0))
        b = b.rotate(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), self.theta)
        return b.translate(cq.Vector(self.x0, self.y0, self.z0))

    def solids(self) -> dict:
        def aabb(t):
            return cq.Solid.makeBox(t[1] - t[0], t[3] - t[2], t[5] - t[4],
                                    cq.Vector(t[0], t[2], t[4]))
        return {
            "board": self.bbox(0, BOARD_V, 0, BOARD_U, -BOARD_T, 0),
            "gpu": self.bbox(GPU_V0, GPU_V0 + GPU_LEN, GPU_SLOT_U - GPU_T,
                             GPU_SLOT_U, 0, GPU_H),
            "cpu": self.bbox(CPU_V - BLOCK_V / 2, CPU_V + BLOCK_V / 2,
                             CPU_U - BLOCK_U / 2, CPU_U + BLOCK_U / 2, 0, BLOCK_N),
            "r420": self.bbox(*self.r420_b) if self.r420_b else aabb(self.r420),
            "r360": self.bbox(*self.r360_b) if self.r360_b else aabb(self.r360),
            "psu": aabb(self.psu),
        }


def plen(pts):
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------
B5 = Option(
    "B5", "B5 (сейчас): 360 лежит внизу,\n420 за платой", 45, -122, 150, 65,
    r420=(-229, 229, 353, 418, 106, 244), r360=(-197, 197, 29, 150, 10, 65),
    psu=(-75, 75, 243, 453, 0, 86),
    tube_cpu=[(270, 330, 200), (248, 385, 175)],
    tube_gpu=[(216, 90, 38)],
)
A = Option(
    "A", "A «Стена»: оба радиатора на ребре\nза платой, 420 над 360", 45, -122, 60, 30,
    r420=(-229, 229, 290, 355, 246, 384), r360=(-165, 229, 290, 345, 115, 236),
    psu=(-105, 105, 145, 295, 0, 86),
    tube_cpu=[(-270, 280, 300), (-248, 322, 315)],          # 420 fittings on the left
    tube_gpu=[(270, 300, 190), (248, 317, 176)],
)
B = Option(
    "B", "B «Козырёк»: 420 плашмя над платой,\n360 на ребре сзади", 45, -122, 60, 30,
    r420=(-229, 229, 150, 288, 305, 370), r360=(-165, 229, 290, 345, 115, 236),
    psu=(-105, 105, 145, 295, 0, 86),
    tube_cpu=[(-270, 215, 320), (-248, 219, 338)],
    tube_gpu=[(270, 300, 190), (248, 317, 176)],
)
C = Option(
    "C", "C «Паруса»: оба радиатора стоят\nвертикально справа от платы", 45, -122, 60, 30,
    r420=(185, 250, 181, 319, 20, 478), r360=(185, 240, 50, 171, 20, 414),
    psu=(-105, 105, 145, 295, 0, 86),
    tube_cpu=[(217, 250, 520), (217, 250, 497)],            # tubes up
    tube_gpu=[(212, 110, 455), (212, 110, 434)],
)
D = Option(
    "D", "D «Арена»: плата лежит, радиаторы\nстеной сзади и справа", 0, -150, 75, 100,
    r420=(-253, 205, 400, 465, 120, 258), r360=(150, 205, 0, 394, 132, 253),
    psu=(-130, 80, 150, 300, 0, 86),
    tube_cpu=[(-290, 405, 190), (-272, 432, 189)],
    tube_gpu=[(178, -55, 200), (178, -19, 192)],
)
E = Option(
    "E", "E «Шатёр»: 360 параллельно плате (n 122),\n420 под 90° к плате за её верхним краем", 45, -122, 60, 30,
    r420=(0, 0, 0, 0, 0, 0), r360=(0, 0, 0, 0, 0, 0),
    r420_b=(-107, 351, 310, 378, -15, 123),  # revision 5: stands at 90 deg to the board, ported core face (u 310) towards it, fans on u 378
    r360_b=(-75, 319, 184, 305, 122, 177),  # raised to n = 122 (owner accepted), fans on the outer side; 46 mm over the block body
    psu=(-105, 105, 145, 295, 0, 86),
    # port tips: CPU hoses into the 420's core face at its left-hand end, GPU hoses into the 360's inner face at its right-hand end
    # (the routed lengths, 482 of 500 and 435 of 450 mm, come from cad_b6/hoses.py and are printed below the table)
    tube_cpu=[(-220.6, 222.0, 252.0)],
    tube_gpu=[(188.6, 156.6, 262.0)],
)
OPTIONS = [B5, A, E, C, D]


def analyse(o: Option) -> dict:
    s = o.solids()
    clashes = []
    gaps = {}
    for (na, a), (nb, b) in itertools.combinations(s.items(), 2):
        if {na, nb} <= {"board", "gpu", "cpu"}:
            continue
        common = a.intersect(b)
        vol = common.Volume() if common and not common.isNull() else 0.0
        if vol > 1.0:
            clashes.append(f"{na}×{nb} {vol / 1000:.0f} см³")
        else:
            gaps[f"{na}-{nb}"] = a.distance(b)
    cpu_top = max(o.bp(CPU_V, CPU_U + du, BLOCK_N)[2] for du in (-BLOCK_U / 2, BLOCK_U / 2))
    gpu_pump_top = o.bp(GPU_PUMP[0], GPU_PUMP[1] + 20, GPU_PUMP_TOP_N)[2]
    bb = [x.BoundingBox() for x in s.values()]
    env = (min(b.xmin for b in bb), max(b.xmax for b in bb),
           min(b.ymin for b in bb), max(b.ymax for b in bb),
           min(b.zmin for b in bb), max(b.zmax for b in bb))
    block_port = o.bp(CPU_V, CPU_U, 50)
    card_end = o.bp(GPU_V0 + GPU_LEN - 10, GPU_SLOT_U - GPU_T / 2, GPU_H - 10)
    card_mid = o.bp(GPU_V0 + GPU_LEN / 2, GPU_SLOT_U - GPU_T / 2, GPU_H)
    t_cpu = plen([block_port] + o.tube_cpu) * SLACK
    t_gpu_end = plen([card_end] + o.tube_gpu) * SLACK
    t_gpu_mid = plen([card_mid] + o.tube_gpu) * SLACK
    return dict(
        clashes=clashes, gaps=gaps, env=env,
        cpu_margin=s['r420'].BoundingBox().zmax - cpu_top, gpu_margin=s['r360'].BoundingBox().zmax - gpu_pump_top,
        cpu_top=cpu_top, gpu_pump_top=gpu_pump_top,
        t_cpu=t_cpu, t_gpu_end=t_gpu_end, t_gpu_mid=t_gpu_mid,
        pts=dict(block=block_port, card_end=card_end),
    )


COL = dict(board="#4f7fbf", gpu="#5aa13c", cpu="#b84040", r420="#e08a2e",
           r360="#a6cc5c", psu="#a99bd0")


def draw(o: Option, r: dict, ax_side, ax_front):
    c, s = math.cos(math.radians(o.theta)), math.sin(math.radians(o.theta))

    def side_poly(u0, u1, n0, n1):
        return [(o.y0 + u * c - n * s, o.z0 + u * s + n * c)
                for u, n in ((u0, n0), (u1, n0), (u1, n1), (u0, n1))]

    def rect(a0, a1, b0, b1):
        return [(a0, b0), (a1, b0), (a1, b1), (a0, b1)]

    board_items = {
        "board": (0, BOARD_V, 0, BOARD_U, -BOARD_T, 0),
        "gpu": (GPU_V0, GPU_V0 + GPU_LEN, GPU_SLOT_U - GPU_T, GPU_SLOT_U, 0, GPU_H),
        "cpu": (CPU_V - BLOCK_V / 2, CPU_V + BLOCK_V / 2,
                CPU_U - BLOCK_U / 2, CPU_U + BLOCK_U / 2, 0, BLOCK_N),
    }
    if o.r360_b:
        board_items["r360"] = o.r360_b
    if o.r420_b:
        board_items["r420"] = o.r420_b
    for name, t in (("psu", o.psu), ("r360", o.r360), ("r420", o.r420)):
        if (name == "r360" and o.r360_b) or (name == "r420" and o.r420_b):
            continue
        ax_side.add_patch(Polygon(rect(t[2], t[3], t[4], t[5]), fc=COL[name], ec="k", alpha=.85))
        ax_front.add_patch(Polygon(rect(t[0], t[1], t[4], t[5]), fc=COL[name], ec="k", alpha=.55))
    for name, (v0, v1, u0, u1, n0, n1) in board_items.items():
        poly = side_poly(u0, u1, n0, n1)
        ax_side.add_patch(Polygon(poly, fc=COL[name], ec="k", alpha=.9))
        zs = [p[1] for p in poly]
        ax_front.add_patch(Polygon(rect(o.x0 + v0, o.x0 + v1, min(zs), max(zs)),
                                   fc=COL[name], ec="k", alpha=.75))
    # pumps and "must be above" lines
    for (v, u, n), top, rad, col in (
        ((CPU_V, CPU_U, 40), r["cpu_top"], o.r420, "#b84040"),
        (GPU_PUMP, r["gpu_pump_top"], o.r360, "#2d6b12"),
    ):
        x, y, z = o.bp(v, u, n)
        ok = (r['cpu_margin'] if rad is o.r420 else r['gpu_margin']) > 0
        for ax, h in ((ax_side, y), (ax_front, x)):
            ax.plot(h, z, "o", ms=9, mfc="white", mec=col, mew=2.5, zorder=5)
            ax.plot(h, z, "x" if not ok else ".", ms=7, color=col, zorder=6)
    ax_front.text(o.x0 - 6, o.bp(0, 225, 0)[2], "I/O ▸", ha="right", va="center",
                  fontsize=8, color="#333")
    e = r["env"]
    for ax, (h0, h1), lab in ((ax_side, (e[2], e[3]), "Y, глубина"), (ax_front, (e[0], e[1]), "X")):
        mid = (h0 + h1) / 2
        ax.set_xlim(mid - 270, mid + 270)
        ax.set_ylim(-25, 570)
        ax.set_aspect("equal")
        ax.axhline(0, color="#888", lw=.8)
        ax.grid(alpha=.25)
        ax.tick_params(labelsize=7)
        ax.set_xlabel(lab, fontsize=8)
    ok_c = "✓" if r["cpu_margin"] > 0 else "✗"
    ok_g = "✓" if r["gpu_margin"] > 0 else "✗"
    ax_side.set_title(o.title, fontsize=9.5, loc="left")
    ax_front.set_title(
        f"железо {e[1]-e[0]:.0f}×{e[3]-e[2]:.0f}×{e[5]-e[4]:.0f} (Ш×Г×В)\n"
        f"запас: CPU {ok_c} {r['cpu_margin']:+.0f}   GPU {ok_g} {r['gpu_margin']:+.0f}",
        fontsize=8.5, loc="left")


def main():
    fig, axes = plt.subplots(2, len(OPTIONS), figsize=(4.6 * len(OPTIONS), 11),
                             gridspec_kw=dict(hspace=.16, wspace=.16))
    print(f"{'':4}{'конверт ШxГxВ':>18}{'CPU зап.':>10}{'GPU зап.':>10}"
          f"{'тр.CPU/500':>12}{'тр.GPU/450 торец|центр':>26}  пересечения / мин. зазоры")
    for i, o in enumerate(OPTIONS):
        r = analyse(o)
        draw(o, r, axes[0][i], axes[1][i])
        e = r["env"]
        tight = sorted(r["gaps"].items(), key=lambda kv: kv[1])[:3]
        print(f"{o.key:4}{e[1]-e[0]:6.0f}x{e[3]-e[2]:.0f}x{e[5]-e[4]:.0f}".ljust(22)
              + f"{r['cpu_margin']:+10.0f}{r['gpu_margin']:+10.0f}"
              + f"{r['t_cpu']:12.0f}{r['t_gpu_end']:14.0f} |{r['t_gpu_mid']:5.0f}      "
              + (", ".join(r["clashes"]) or "нет") + " / "
              + ", ".join(f"{k} {v:.0f}" for k, v in tight))
    try:        # the routed hoses of row E (revision 5), measured in cad_b6/hoses.py
        import sys
        sys.path.insert(0, os.path.join(ROOT, "cad_b6"))
        import hoses
        rts = hoses.routes()
        print("E, трассы шлангов (cad_b6/hoses.py): "
              + ", ".join(f"{k.upper()} {h['length']:.0f} из {spec['length']:.0f} мм, радиус >= {h['rmin']:.0f}"
                          for k, (pair, spec) in rts.items() for h in pair[:1]))
    except ImportError as e:
        print("E: трассы шлангов не прочитаны:", e)
    fig.suptitle("B6: варианты расстановки. Сверху вид сбоку (перед слева), снизу вид спереди. "
                 "Кружки: помпы (CPU красный, GPU зелёный); запас = верх радиатора − верх помпы, мм",
                 fontsize=11, y=.96)
    out = os.path.join(ROOT, "previews", "layout_b6_options.png")
    fig.savefig(out, dpi=110, bbox_inches="tight")
    print("→", out)


if __name__ == "__main__":
    main()
