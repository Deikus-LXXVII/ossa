# Fit gauges: test the model against the real hardware before printing parts

Asked by the owner on 15 Nov 2026: thin, fast-printing test plates that reproduce the mounting interfaces of the model, so the CAD numbers can be calibrated cheaply.

## Two questions, kept apart

1. **Is the model right about the hardware?** Hole patterns, outlines, port and hose positions. Answered by gauges G1 to G7, printed in **PLA**. PLA shrinks little, so a mismatch means the model's number is wrong, not the printer.
2. **Does the printer reproduce the model?** Shrinkage and hole sizes in the real materials. Answered by coupons C1 to C3, printed in **ABS** (C1, C2) and **PA6** (C3).

Mixing the two would hide the cause of an error: ABS shrinks about 0.7 %, which is 2 mm over the 282 mm between the outer ATX hole rows.

## What to build

One new script, `cad_b6/fit_gauges.py`. It reads `cad_b6/hardware.py` and the parts built by `cad_b6/frame_v0.py`. It does not change either. Run: `.venv/bin/python cad_b6/fit_gauges.py`.

Every gauge is a flat plate, 2.0 mm thick unless stated, made of 12 mm wide strips round the features it tests (a frame, not a full sheet), so it prints fast. Each fits a 290 x 290 mm bed. Each has its name engraved 0.6 mm deep and one arrow showing the datum edge. If engraved text fails or makes the build slow, use a row of notches as the id and say so in the report.

All numbers come from `hardware.py` by name. Do not retype a number.

### Gauges (PLA)

| Id | Lies on | Tests | Features, in the component's own frame |
|---|---|---|---|
| G1 `rad420_ports_end` | The 420's core face (the face with the ports), at the port end | Fan-screw pattern, distance from the radiator's end to the first holes, port positions | The 4 holes of the end fan bay from `RAD420_HOLES_X` / `RAD420_HOLES_N` at screw clearance (`M3_CLEAR_D`); the radiator's end edge and both long edges as datum edges; two open-sided slots for the port collars so the plate slides on with hoses attached (collar Ø20, positions as `hoses.py` and `RAD420_PORT_INSET` give them, 1 mm clearance) |
| G2 `rad360_ports_end` | The 360's inner face, at the port end | The same for the MSI radiator. Its port numbers are the least certain in the model | The same from `RAD360_HOLES_X` / `RAD360_HOLES_U`, `RAD360_PORT_INSET`, `RAD360_BS` |
| G3 `psu_rear` | The PSU's rear face | Screw pattern and outline | Outline 150 x 86 from `PSU_W`; the 4 holes of `PSU_PATTERN_FACE` at `M3_CLEAR_D` (6-32, as `psu_bulkhead` has them) |
| G4 `atx_holes` | The board's underside, or a case tray | The 9 ATX holes, the rear edge, the slot line | Lattice of strips through `ATX_HOLES` at `ATX_HOLE_D`; a datum edge on the rear I/O edge (v = 0) and one on the bottom edge (u = 0); a notch at `GPU_SLOT_U` on the rear edge |
| G5 `cpu_block` | Over the CPU block, on the board side panel open | Where the hoses leave the block | Ring that clears the block body (Ø91 plus 1 mm); two open slots for the collars from `CPU_COLLAR_U` and `CPU_COLLAR_HALF_SPACING`; a notch for the lug from `CPU_LUG_U` / `CPU_LUG_HALF_V`; an arrow towards the graphics card |
| G6 `fan140` | A 140 mm fan | Fan-screw pitch and the clear opening | 4 holes at `FAN_PITCH`; inner opening `FAN_APERTURE_D` |
| G7 `gpu_end` | The end of the graphics card where the hoses leave | Card section and hose exits | Outline of the card's end from `GPU_BS` (u and n extents); two open slots at the hose exit positions `hoses.py` uses for the GPU pair, hose radius plus 1 mm |

For every gauge, add a check in the script that its holes coincide (within 0.01 mm) with the holes the skeleton really has for that component: take them from the `Part.holes` of the parts that hold it (antlers for the 420, visor arms for the 360, `psu_bulkhead`, the ATX standoff positions, the fan brackets). This proves a gauge represents the skeleton and not only the tables. Where the skeleton uses only some of the holes (3 of 4 on an antler), check those. If a pair does not coincide, stop and report it; do not adjust anything.

### Coupons (real materials)

| Id | Material | Tests | Shape |
|---|---|---|---|
| C1 `scale_l` | ABS | Shrinkage along X and along Y | L-shaped ruler, 200 mm legs, 12 mm wide, 2 mm thick, Ø4 holes every 50 mm on each leg, legs marked X and Y |
| C2 `insert_ladder` | ABS | Which pilot diameter grips each heat-set insert; which clearance diameter passes each screw | *Superseded (first plan).* Block 8 mm thick. For each key of `hardware.INSERTS`: five pilot holes at the table's diameter -0.2, -0.1, 0, +0.1, +0.2 mm, to the table's depth. For `M3_CLEAR_D`, `M4_CLEAR_D`, `M5_CLEAR_D`: three through holes at -0.2, 0, +0.2. The nominal hole of each row is marked. Holes vertical. A second small block carries the same nominal pilot holes horizontal, because sideways holes print differently. The built ladder is stated under Built |
| C3 `hose_clip` | PA6 | The snap of a hose guide on the real 12.4 mm hose | One channel of `hose_guide_cpu`, cut from the real part built by `frame_v0.py` as a slice about 20 mm long. No new geometry: it must be the part's own shape |

### Outputs

- `out/gauges/<id>.step` and `out/gauges/<id>.stl` for each item. Add `/out/` to `.gitignore`: generated files are not tracked.
- `previews/gauges.png`: all items laid out flat, labelled, one image.
- `cad_b6/report_gauges.txt`: for each item its bounding box, volume, plastic in grams for its material, a rough print time at 12 mm³/s, and the result of its coincidence check.

### Rules

- Do not edit `hardware.py`, `frame_v0.py`, `hoses.py` or any other existing script. If something needed is not exposed, read it through the existing functions; if that is impossible, stop and report what is missing.
- Do not commit.
- Done means: the script runs clean, every coincidence check passes or is reported, `previews/gauges.png` has been looked at, and `frame_v0.py` still ends with "Done, all asserts passed." (it must, since it was not touched).

## After the build (main session)

Write the owner's check sheet: for each gauge, what to print, how to hold it against the component, what to look at, and which number in `hardware.py` it corrects. Record the owner's measurements in this file and update `hardware.py` from them.

## Built (15 Nov 2026)

`cad_b6/fit_gauges.py` builds 11 items into `out/gauges/` (not tracked). Table and check results: `cad_b6/report_gauges.txt`. Picture: `previews/gauges.png`. Every gauge's holes coincide with the skeleton's own holes for that component; G5 and G7 have no skeleton holes and are checked against the hardware solids.

Differences from the list above:
- **G4 is two plates**, `G4a` (u 0 to 147) and `G4b` (u 135 to 305). The ATX hole span does not fit one 290 mm plate. They share the middle hole row.
- **G1 and G2** have a wider end strip (25.4 mm) so the tooth between the two collar slots is held.
- **C2 is 10.4 mm thick**: the M4 pilot is 9.1 mm deep. *Superseded:* since Revision 12 the model has M3 inserts only, and since Revision 15 (17 Nov 2026, the owner's inserts measured at 4.0 mm long and 4.96 mm across) C2 is one block 124 x 38 x 8 mm: a row of nine blind M3 pilots 4.1 to 4.9 mm in steps of 0.1, 6.7 mm deep with 1.3 mm of floor, the model's 4.4 marked with a triangle; a row of seven M3 clearance holes 3.2 to 3.8 mm, 3.4 marked; and a small block 12 x 16 x 10 mm at x 132 with the 4.4 pilot along +Y. The two blocks together measure 144.0 x 38.0 x 10.0 mm. The table above (five pilots per key, M4 and M5 rows) describes the first plan, not the part.
- **G5 tests the block's body and lug only.** The collar slots fall inside the lug notch. Measure the collar spacing (model: 23.8 mm) with calipers on the hoses.
- **G3's holes** were first built at M4 clearance by a mistake in this plan; they are 6-32 clearance now.

Found on the way, left for the gauges to settle:
- `hoses.py` spaces the 360's ports 24.0 mm apart (`GPU_PORT_PITCH` = 12); `hardware.py` gives 23.8 for the ARCTIC ports and says the MSI ports are alike. G2 uses the hose route's 24.0. The real spacing is unknown until G2 is tried.
- G1 lies on the 420's core face and uses the fan-face hole pattern. Radiators normally carry the same threaded pattern on both faces; G1 will show whether this one does.

## Results from the owner (16 Nov 2026, first pass, printed in white PLA)

- **`G6_fan140`:** the four holes coincide. The side fans' pattern in `hardware.py` stands.
- **`G7_gpu_end`:** the hoses pass through the two cut-outs, but the plate is larger than the end of the card. The model's 51 x 150 mm end is therefore too big on at least one side. Which edge and by how much is asked of the owner; `hw.GPU_BS` is corrected when the numbers come.
- **`G5_cpu_block`:** fits with a little play. The size of the play was not given; nothing is changed.
- **New fact:** the 90 degree fittings on the CPU block turn. The hose routes may leave the block in another direction than the model draws.
- **`C1_scale_l`:** not printed. The main session had not put it on the list it gave the owner. It is needed before the first real part in ABS or PETG, in each of those materials, not before.
- **Owner's decision (17 Nov 2026):** `C2_insert_ladder` is printed in PETG, not ABS: there is PETG to spare. Its result sets `hw.M3_PILOT_D` as a first figure; it is confirmed on the first small ABS part with an insert (`docs/printer-and-materials.md`). The main session asked for `C1_scale_l` in PETG in the same print.
- **Owner's results of the three PETG prints (18 Nov 2026):**
  - `C2_insert_ladder`: "the holes for the inserts have to be printed at about 4.5 to 4.6 mm". The model had 4.4 (`hw.M3_PILOT_D`, the maker's figure). It took 4.5 on 18 Nov 2026, in a step of its own before revision 18: it is inside the owner's range, and ABS, which the skeleton is printed in, shrinks a little more than PETG, so the same hole comes out slightly tighter there (main session's estimate, about 0.02 mm, not measured). To be confirmed on the first small ABS part with an insert. The owner did not say which clearance hole of the lower row takes an M3 screw best; `hw.M3_CLEAR_D` stays 3.4.
  - `C1_scale_l`: "the plastic settles well, it comes out at about 150 mm; if there is an error it is small". No scale correction for PETG. ABS is not measured.
  - The organic layer's trial piece (`trial_base_mid_R`): "visually everything is as it should be; no problems with the steps, the support or the strength". A photograph is promised.
- **Not yet reported:** `C3_hose_clip` (meaningful only in nylon), the M3 clearance row of `C2_insert_ladder`, and the second pass with the PC apart (`G1`, `G2`, `G3`, `G4a`, `G4b`).
- **`G7_gpu_end`, follow-up (16 Nov 2026):** the owner measured the card's body at about 135 mm. MSI gives 280 x 148 x 51 mm; the model draws the card as a box from the board's surface, n 0..150. Main session's inference, not yet confirmed: the 13 to 15 mm difference is the strip between the board and the card's lower edge, where the slot is, so the card's top is where the model has it and the gauge overhangs on the board side only because it was drawn from the whole box. To confirm with the owner: the plate overhangs on the arrow side only, and the 51 mm thickness fits. If so, `hw.GPU_BS` stays and only the gauge's outline was wrong.
- **`G7_gpu_end`, confirmed by the owner (16 Nov 2026):** placed from the motherboard's surface, the plate matches the card along its height; MSI's 148 mm includes the edge connector. `hw.GPU_BS` stays (n 0..150). The owner did not mention the 51 mm thickness separately.
- **Card thickness (owner, 16 Nov 2026):** about 42.5 mm at the card's body; the model has 51 mm (MSI's figure, `hw.GPU_BS` u 75.6..126.6). The owner also sent a photo of the card in the present case (not in the repository). Read from it by the main session: the hoses leave the far end along the card's axis, as modelled; the power socket sits in a recess in the long face with the light strip, right after the strip, as modelled (its distance from the bracket is still to be measured); the body is a flat slab. Main session's inference, not confirmed: MSI's 51 mm includes the raised fan frame on the cooler face (seen in `refs/gpu_5080_suprim_liquid_tubes.png`), which faces away from the camera in the photo. If so, at the far end the card's cooler face is at about u 84 and not 75.6, and the `gpu_rest` finger of `rib_A_right` (upper face at u 75.6) would stand 8.5 mm short of the card. To ask: the thickness measured over the fan frame. Correction goes into Revision 14 (`docs/plans/external-cables.md`).
- **Cut corner on the card (owner, 16 Nov 2026):** one corner of the card is cut off, on the front (cooler) side at the end where the hoses leave. Seen by the main session in the owner's photo and in `refs/gpu_5080_suprim_liquid_tubes.png`: the cut is at the far end's corner with the long edge away from the board (the edge with the light strip, n 150); the shroud is cut there and the backplate runs on to the full corner. The model's box has no cut. It removes material, so no clearance gets worse. It matters only for what touches the card there: the `gpu_rest` finger runs along the cooler face at the far end from n -10 to n 104. Whether the cut reaches down to n 104 is not known; to ask: how far the cut runs along the card from its end and how far from the long edge towards the board.
- **Card shape, confirmed by the owner (16 Nov 2026):** the card is about 51 mm thick over the fan frame, and the cooler face slopes down towards the card's edge, so the body is about 42.5 mm at the far end. The cut corner runs 13 mm along the card from its end and 10 mm from the long edge towards the board (v 265..278, n 140..150 in the model's terms). Consequences: the cut does not reach the `gpu_rest` finger (it ends at n 104); the finger's upper face (u 75.6) is about 8.5 mm short of the card's real cooler face at the far end. Still an assumption: the 2.5 mm the model allows behind the card's PCB, so the real face is known to about 2 mm only.
- **Correction from the owner (16 Nov 2026):** the slope runs towards the long edge away from the motherboard (n 150), not towards the far end. Near the motherboard the card keeps 51 mm. The two entries above that put the cooler face 8.5 mm short of the `gpu_rest` finger are wrong: the finger lies along the cooler face from n -10 to n 104, on the board's side, where the card is 51 mm thick as modelled. Not known: at which n the slope begins. `hw.GPU_BS` stays; the box is larger than the card only near the edge at n 150 and at the cut corner, which is the safe side for every clearance. This also explains why `G7_gpu_end` overhung the card: the plate is the whole 51 x 150 box.
