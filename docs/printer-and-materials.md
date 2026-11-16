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
| Creality CR-ABS, Creality Hyper ABS | black | load-bearing skeleton (`cad_b6/frame_v0.py`) and, since 16 Nov 2026, the organic outer layer (`cad_b6/organic_frame.py`): the owner finds ABS cheaper than PLA now |
| Creality Hyper PLA | black | no planned use since the organic layer went to ABS |
| ELEGOO translucent PLA | translucent | diffuser of the light line |
| yxpolyer Nylon PA6, unfilled, 1 kg | black | parts that snap: the two hose guides only. The cable tie bridges are ABS since 16 Nov 2026 (hook-and-loop straps hold the cables), and the PLA layer is fixed with M3 screws |
| plain PLA | white | test prints of every part before it is printed in ABS (owner's decision, 16 Nov 2026) |

## Stock and order of printing (owner, 16 Nov 2026)

- **Black ABS:** two spools of 1 kg. The skeleton is about 1.65 kg at 4 walls and 20 % infill, before supports and rejects, so nothing is wasted on trials.
- **Trials in white PLA first.** A part is printed in white PLA and checked on the hardware; ABS follows only when the trial fits.
- **Black PLA:** about 1.8 kg. Not needed for the case since the organic layer went to ABS.
- **ABS needed in all:** about 1.65 kg for the skeleton and, by the main session's estimate, 1.5 to 2 kg for the organic layer with its supports (1843 cm3 is 1.9 kg solid). With rejects that is 4 to 5 kg against the 2 kg on hand.
- **Side fans:** the two 140 mm fans come from the owner's present case.
- **Hook-and-loop straps:** to be ordered.
- **Drives:** the owner has neither an HDD nor a SATA SSD. The drive bay is a provision for later; no SATA cable is routed.
- **Radiator fan screws:** the screws the owner used to put fans on a radiator are about 30 mm under the head.

Mind when reading a PLA trial: ABS shrinks more than PLA as it cools, so a hole or a fit that is right in PLA comes out a little tighter in ABS. Fits that matter (insert pilots, screw clearances, the fit gauges) are confirmed on a small ABS piece, not on the PLA trial.

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
- **M3 heat-set inserts:** 20 at most on hand, 200 more ordered (owner's word, 16 Nov 2026). Outer diameter and length not stated yet; the pilot hole is sized to them.
- An M2 kit (M2 x 4 to M2 x 20 with nuts and washers). The case has no use for it so far.
- The counts are the kits' labels, not a count of what is left in the boxes. The ordered kit's contents were read off its Amazon listing (the label in the product picture and the description agree).

What follows for the model is in `docs/plans/fasteners-m3.md`.

## LED strip for the light line (researched 16 Nov 2026)

Looked for on amazon.de by Grok (`web-research`); the product pages were then opened and read in the main session.

- **Header on the board:** JARGB_V2, 5 V, 3 A, 180 LEDs at most, pins +5 V, data, no pin, ground (MSI user guide, page 55).
- **No bare strip up to 10 mm wide comes with the motherboard plug.** The ready-made PC strips with that plug are 16 to 20 mm wide bars and do not fit the 14 x 14 mm channel.
- **Strip:** BTF-LIGHTING WS2812 ECO, 1 m, 60 LEDs per metre, black PCB, IP30, 10 mm wide, JST-SM 3-pin on both ends, ASIN B088BRY2SH, 9.49 EUR, in stock on the day. About 270 mm is used: 16 LEDs, at most 0.96 A at full white, so it is run dimmed in the closed channel. The same strip with 30 LEDs per metre is sold only as a 5 m roll (ASIN B088BB8WTZ, 17.99 EUR); its 33 mm pitch behind a 10 mm air gap would show as separate dots (main session's judgement, not tested).
- **Lead from the board to the strip:** a "5 V 3-pin ARGB to SM 3-pin" cable, for example ASIN B0CQJLQ7ZC (four 30 cm cables, 5.99 EUR) or B0F8C4SB31 (a 30 cm splitter, 6.69 EUR). Not verified: whether the lead's SM end is the gender that mates with the strip's input end, and the wire order. The strip is one-directional (data in at one end). If the plug does not mate, three wires are soldered.
