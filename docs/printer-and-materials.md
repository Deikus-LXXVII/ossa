# Printer and materials

Given by the owner on 15 Nov 2026. Facts about his equipment, not design decisions.

## Printer
- Creality K1 Max, 300 × 300 × 300 mm. Design rule in this project: every part ≤ 290 mm.
- Mainboard CR4CU220812S11, stock firmware 2.3.5.34. **Firmware V1.1.0.27 must not be installed: it is for S12 boards.** Do not change the firmware at all without the owner.
- Nozzle E3D Obxidian High Flow 0.4 mm (hardened); a full set of nozzles is available.
- The camera serves an MJPEG stream on port 8080.

## Feed
- CFS with 4 slots. On 29 Oct 2026: A empty, B Creality Hyper PLA black, C Creality CR-ABS black, D plain white PLA.
- Humidity inside the CFS was about 65 %.

## Filament, 1.75 mm
| Material | Colour | Use in this project |
|---|---|---|
| Creality CR-ABS, Creality Hyper ABS | black | load-bearing skeleton (`cad_b6/frame_v0.py`) |
| Creality Hyper PLA | black | organic outer layer (`cad_b6/organic_frame.py`) |
| ELEGOO translucent PLA | translucent | diffuser of the light line |
| yxpolyer Nylon PA6, unfilled, 1 kg | black | parts that snap: the two hose guides only. The cable tie bridges are ABS since 16 Nov 2026 (hook-and-loop straps hold the cables), and the PLA layer is fixed with M3 screws |
| plain PLA | white | not planned |

## What follows for printing
- PA6 takes up water fast and prints badly when damp. At 65 % humidity the CFS is not a place to keep it: dry it before printing and feed it from a dry box.
- ABS and PA6 need the chamber closed; the printer stands in a bedroom, so mind the fumes (see `HANDOFF.md`).
- Unfilled PA6 warps on large flat parts. Keep nylon parts small.

## Fasteners on hand (owner's photo of the kits and the kit ordered on 16 Nov 2026)

All screws are M3 hex socket head cap screws. There are no M4 screws.

| Screw | Black 12.9 steel, 620-piece kit | Stainless 304, 440-piece kit | Black alloy steel, 1110-piece kit (ordered) | Total |
|---|---|---|---|---|
| M3 x 4 | | | 55 | 55 |
| M3 x 5 | | | 55 | 55 |
| M3 x 6 | 30 | 20 | 55 | 105 |
| M3 x 8 | 30 | 20 | 55 | 105 |
| M3 x 10 | 30 | 20 | 55 | 105 |
| M3 x 12 | 30 | 20 | 55 | 105 |
| M3 x 14 | | | 30 | 30 |
| M3 x 16 | 30 | 20 | 30 | 80 |
| M3 x 18 | | 20 | 30 | 50 |
| M3 x 20 | 30 | 20 | 30 | 80 |
| M3 x 25 | | 20 | 30 | 50 |
| M3 x 30 | | 20 | 30 | 50 |
| M3 x 35 | | 20 | | 20 |
| M3 x 40 | | 20 | | 20 |

- **M3 nuts:** about 700 (180 + 220 + 300). **M3 flat washers:** 380 (80 + 300). **M3 lock washers:** 180.
- **M3 heat-set inserts:** 20 at most (owner's word, 16 Nov 2026). Size not stated.
- An M2 kit (M2 x 4 to M2 x 20 with nuts and washers). The case has no use for it so far.
- The counts are the kits' labels, not a count of what is left in the boxes. The ordered kit's contents were read off its Amazon listing (the label in the product picture and the description agree).

What follows for the model is in `docs/plans/fasteners-m3.md`.
