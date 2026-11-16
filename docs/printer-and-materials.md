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
