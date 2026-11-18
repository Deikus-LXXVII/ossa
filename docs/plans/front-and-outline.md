# A straight outline, no light line, the I/O module under an organic hood (revision 18)

## What the owner asked (18 Nov 2026)

1. "Rework the module with the power button and the USB ports. We give up the light, and try to make this module one whole with the organic design. And between the graphics card and everything under it, make the organic design denser."
2. With `previews/b6_full_corners.png` marked up at the four corner arcs: "I meant to get rid of them or to make these arcs smaller, to minimise the bread-bin effect."
3. After seeing the layer with the arcs left out: "Try to make the outlines of the organic design straighter: not the webs themselves, the parts that form the silhouette."

The main session reads 3 as the answer to 2: the arcs stay as members, their lines become straight, the films between them stay as they are. **Approved by the owner on 18 Nov 2026** ("Yes, I approve this design"), after photo-style renders of the front sketch with the fans in Noctua's colours (`docs/plans/sketches/pictures/render_proposed_*.png`, made by `docs/plans/sketches/render_blender_sketch.py` and `blender_noctua.py`).

## Sketches (main session, 18 Nov 2026; scripts and pictures under `docs/plans/sketches/`)

Each sketch builds the layer with `organic_frame.build()` itself and replaces only control points or members, so the pads and the carves are the real ones. Strength is `organic_strength.py`'s own run on the sketch's field; access is `zone_access.py`'s.

| Sketch | What it does | Result |
|---|---|---|
| `no_arcs_sketch.py no_arcs` | leaves out the four corner sweeps, the base rails, the rear window films and the right ring's near film | 719 cm³ in two bodies; the upper one on its two remaining pads: 58.0 MPa, 87.8 mm. Not pursued |
| `straight_sketch.py` | the bones of the silhouette as straight legs with tight knees | one body, `main` 1708.7 cm³ (1741.7 today); 7.0 MPa, 3.03 mm (today 6.5, 2.16; limits 10, 5); bundles 52 and 56 mm, hand 44 mm, as today |
| `front_sketch.py` | on top of that: no sill, a hood over the carrier, 13 nearly straight strands for the veil's 7 | one body, `main` 1950.1 cm³; 5.5 MPa, 3.74 mm; access not rerun |

Pictures: `pictures/no_arcs_*.png`, `pictures/straight_*.png`, `pictures/front_*.png`.

## Facts the specification rests on (Grok `code-analysis`, 18 Nov 2026, measured on the built model)

- The module is the front I/O of the owner's Fractal North XL: power button, two audio jacks, two USB-A, one USB-C. Its box in the model is a placeholder (`hw.FRONT_IO_W`, X -70..95, Y 0..42, Z 10..46); its screws, its thickness and its cables' lengths are not known. It rests on `beam_front`.
- `front_sill` is 413.8 cm³, 198.5 g of ABS at 4 walls and 20 %. It is screwed to `beam_front` by four M3 x 25 from below, holds the carrier by four M3 x 10 along X, carries two pads of the layer (`sill_end_R/L`), and its ridge is where the veil's lower bar stands. Its height comes from the light strip's channel.
- `front_io_carrier` is an inverted U over the module, outside X -82..107, Y 0..44.2, Z 10.3..48.9, 47.9 g. Its outside does not follow the module's numbers. It hangs on the sill today and touches nothing.
- `beam_front` is a box X ±142, Y 0..40, Z -10..10.
- The light line is `hw.LIGHT_STRIP_*`, the hardware solid `light_strip` (a keep-out), a channel, a slit and a ring wall in the sill, the cable `argb`, a row in `SITS_ON`, and sentences in five documents. No diffuser is modelled.
- The USB 3 and USB-C leads leave the module's rear through the sill's window; the power-switch and audio leads start behind the sill's rear face (Y 55).
- The layer's generator has tubes, balls, flat discs for pads and carving boxes. It has no slab. `shell_concepts.tube` can flatten a tube along one axis (`squash`), which `Field.add` does not pass on today.
- A straight front post from the old foot (Y 22) crosses the driver's path to the pad `sill_end_R`; the sketch starts it at Y 14. With the sill gone that pad goes too.

## Decisions of the main session

The first, second and fifth are what the approved renders show. The third and fourth (how the module is held) were put to the owner in words with the sketch; he did not object and has not said yes to them by name.

| Decision | Why | The other way |
|---|---|---|
| The corner sweeps, the base rails and the brow become straight legs with tight knees; every film stays | the owner's third message; it keeps one body and the present strength | the arcs left out: every part would have to be held anew (58 MPa on what is left) |
| The ABS sill goes entirely | it existed for the light line and for a face round the module; 198.5 g of ABS come back (67 g are left under the limit today) | a lower sill without the channel |
| The module stays in its small ABS carrier; the layer only covers it | the module is not measured; the owner's rule of 16 Nov 2026 keeps an unproved hardware dimension out of a large part | the layer holds the module itself: a wrong dimension would mean reprinting a piece of 2 kg |
| The carrier is screwed to `beam_front` from below, where the sill's bolts were | the module then slides out to the front from under the hood without taking the layer off | screws from above, under the hood: the layer would have to come off first |
| The hood covers the carrier's top and ends; the module's face and the beam under it stay bare | the face has the button and the ports; the beam is the skeleton's front edge | a skin over the beam's face |

## Revision 18: specification

The reference for every shape and number of the layer is `docs/plans/sketches/straight_sketch.py` and `docs/plans/sketches/front_sketch.py` as committed with this plan. Where this text and a sketch differ, this text holds and the report says so.

### A. Skeleton

1. **The light line goes.** `hw.LIGHT_STRIP_*`, `LIGHT_LED_TO_DIFFUSER_MIN`, `LIGHT_DIFFUSER_T`, `LIGHT_LINE_W`, the solid `light_strip`, its place in `KEEP_OUT` and `FRONT_HARDWARE`, its colour in the renderers and the slit actors drawn from the sill's cutter. `hw.FRONT_IO_LED_SLIT_BEYOND` stays: it is the module's own LED.
2. **`front_sill` goes:** its builder, `sill_geometry()`, the pocket, the channel, the slit, the window, the `SILL_*` constants, its four bolts through `beam_front` and their row in `FASTENERS`, its two organic pads' pilots, its entry in the rounding log, and check 22 (the wall behind its pocket). Check 22's number is not reused: the report keeps a line that says it was retired with the sill.
3. **`front_io_carrier` stands on `beam_front`.** Its outside stays X -82..107, Y 0..44.2 and its top Z 48.9; its underside comes down to the beam's top (Z 10), an intended contact like the module's. Its four counterbored screws into the sill go. New: four M3 pilots in the underside of its end blocks, two a block, on each block's middle in X, at Y 10 and Y 30 (the sill bolts' Y), cut upward; four clearance holes through `beam_front` under them; four screws from below, their length by `screw_fit` of the beam's height (expected M3 x 25, with a washer, as the sill's were). Check 20 keeps what still exists (the end blocks' least thickness against `CARRIER_END_MIN`, now set by the vertical pilot; the top plate; the room behind the module) and loses its claim about the sill's window.
4. Everything that follows in the code: check 5's mounts (`front_io_carrier`: four screws into `beam_front`), the intended contacts, `strength.py`'s list of parts that touch nothing (the carrier now touches the beam), the report's revision note, `parts_manifest.py --expect front_sill,front_io_carrier,beam_front` (the sill as removed; and `hw:light_strip` removed).
5. Expected counts, to be confirmed by the build: inserts 108 to 102 (the sill's four bolt inserts, its four carrier inserts and its two pad inserts go; the carrier gets four), the layer's pads 16 to 14.

### B. Cables (`cables.py`)

1. `argb` goes (row, route, colour).
2. `usb3` and `usbc` start on the module's rear face as now and are free of the sill's window: the carrier is open at the rear. `jfp1` and `jaud1` start on the module's rear face too (they started at Y 55 only to stay off the sill). All four still pass under the board and keep their tie points.
3. `FAN_LEFT_START_V` and `FAN_RIGHT` are copied from `hardware.py` when the module is imported (a leftover of the review of revision 14a): read them when the route is built, as the USB starts are.

### C. The layer (`organic_frame.py`), piece `main`

1. **Straight outline.** `front_sweep`, `rear_sweep`, `BASE` and `BROW` as in `straight_sketch.py`: the front post one straight line from the front foot (158, 14, 4) to the end of the card's bone, and on the right one more straight leg to the lip's corner; the rear sweep two straight legs with a knee at (176, 366, 224), under the antler and behind the post, then down to (169, 372, 44) and the foot; the base rail one straight line from (160, 40, -4) to (166, 356, -4); the brow straight at Y 13, Z 152. A knee's two neighbours stand 25 mm from it. The number of control points of each bone stays, because the films slice them.
2. **A flattened tube as a member** (`"slab"`: control points, radius, blend, the axis and the factor it is flattened by), added to `Field.add`.
3. **The front** as in `front_sketch.py`: the bone `front_low` straight from (-160, 22, 60) to (160, 22, 60); the hood's roof, a slab along X from -92 to 117 at Y 22, Z 59, radius 26 flattened 3.5 times along Z; two cheeks, slabs from Z 56 down to Z 14 at X -92 and X 117, radius 22 flattened 3.5 times along X; the film between `front_low` and the brow over X ±150 with 13 strands, 6 links, seed 23, sag (0, 1, 0) by 2 mm, in place of the veil.
4. **Carves:** the sill's prism goes out of `carve_layer` (`SILL`, `sill_sdf`, `SILL_GAP`, `SILL_RIDGE`). New: the way the carrier slides out (its exact box, extended forward to Y -20 and down to Z 0) by `GAP_SKEL`, and the module's box by `GAP_HW`.
5. **Pads:** the rows `sill_end_R` and `sill_end_L` go from `hw.ORGANIC_PADS`.
6. **New check, "the carrier comes out":** no solid voxel of any piece in the carrier's box moved forward along -Y by its own depth (its box and every position on the way). A case in `test_organic.py`: a lump in front of the module's face fails it.
7. The existing checks of the layer keep working (the rings whole, nothing beyond |X| 260, the three empty boxes, each piece one body with its pads, the pieces 3 mm apart, the screw heads on the bulkhead reachable).

### D. `assembly_access.py`

`BILL`: the row `front_sill` goes; `front_io_carrier` is four class A screws from below through `beam_front`. `SITS_ON` and `HARD_HARDWARE` lose `light_strip`. The script must exit 0; report where the carrier and the module stand in the order and with which tool the carrier's screws are driven.

### E. Tests

The sill, the light strip, the window and check 22 no longer exist, so the cases that damage them go. That is the one place where this revision removes cases. For each removed case the report gives its name, its line at HEAD and the reason; a case goes only if the thing it damages is gone. Everything that still exists keeps its case or gets a successor of the same strictness: the carrier's pilots filled and moved (check 5, check 7), the module grown by its whole allowance leaves the carrier's outside unchanged and one step more fails check 20, the carrier's screws' length and washer (check 15), the cables' way out of the carrier's rear (a block behind the module makes the USB routes fail). The pinned counts move and are reported before and after.

### F. What must hold at the end

- `frame_v0.py`: every check passes. ABS mass: about 198 g less (report the figure).
- `organic_frame.py`: one body for `main`; `rear_panel` may change where `main`'s rear sweep moved (it is carved 3 mm off `main`): report by how much.
- `organic_strength.py`: both pieces within 10 MPa and 5 mm (the sketch: 5.5 MPa, 3.74 mm for `main`). If not, stop and report; do not tune.
- `zone_access.py`: bundles and hand not under today's 52, 56 and 44 mm (the floors in the script stay 40 and 44).
- `drive_access.py`, `assembly_access.py`, `cables.py`: pass.
- `organic_manifest.py --expect main,rear_panel`.
- `check_budgets.py` will fail on two lines, both foreseen: the organic ratchet (about 2250 cm³ against 2084.9) and the skeleton's floor (about 1535 g against a floor of 1646.3 g: lighter than the record by more than 5 %). The main session re-records both in a commit of its own, the second with `--accept-lower`. `cad_b6/budgets.json` is not edited by the implementer.

### G. Not in this revision

The module's own face plate with its cut-outs (it waits for the module to be measured). The split of `main` into printable pieces. The smoothing of the layer's surface.
