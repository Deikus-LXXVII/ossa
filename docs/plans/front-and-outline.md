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
| `front_sketch.py` | on top of that: no sill, a hood over the carrier, 13 nearly straight strands for the veil's 7 | one body, `main` 1950.1 cm³; 5.5 MPa, 3.74 mm; access not rerun. That was the sketch's first version, the one rendered for the owner; the pads under the posts, the cross-threads' rule and the cable came after (see the strength runs and part H) |

Pictures: `pictures/no_arcs_*.png`, `pictures/straight_*.png`, `pictures/front_*.png`, `pictures/cable_gates.png`, `pictures/cable_under.png`.

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

## What the strength runs found (main session, 18 Nov 2026)

Every figure below was printed by a script on a sketch (`REVIEW.md` row 21); the script and the field are named.

| Run | Field | Result |
|---|---|---|
| `organic_strength.run_piece` in `cable_gate_sketch.py --under --strength` | the front of `front_sketch.py`, cable under the layer | 6.4 MPa; 4.87 mm for a push on the hood's right cheek at (116, 0, 26). Limits 10 and 5 |
| the same with the cheeks shorter and thicker | | 4.87 mm again: the cheek is not what gives |
| `hood_mode.py` (3 mm voxels, that push alone) | the same field | the right post swings back about its top: 5.48 mm at its foot (167, 7, -9), 4.65 at Z 30, 2.43 at Z 160; the left post 0.27. The foot is held by nothing: the sill's pads are gone, `front_foot_R` is 46 mm behind it, and the layer is cut through between them at Y 30, where it keeps off the head of the screw that holds `beam_front` |
| with a pad under each front post (`front_post_R/L`) | | 3.48 mm; but 29.7 MPa in the front film for a push at (-16, 22, 122). It is a cross-thread 55 mm long and 5.2 mm thick. It had been there in every earlier run; none of the 160 pushes had landed on its middle |
| with a cross-thread as thick as its length asks | | **5.4 MPa, 2.79 mm** |
| `member_probes.py`: a push on the middle of each of the 87 strands and cross-threads of `main` | the last field | worst **4.5 MPa, 1.79 mm**, none over |

Two things follow for the model, both in the specification: the front posts get pads of their own, and the strength check stops depending on where its sample of pushes happens to land.

## Revision 18: specification

Third text, 18 Nov 2026. The first got 25 findings from Grok's check against the code, the second 16; all are taken. The references for every shape and number of the layer are `docs/plans/sketches/straight_sketch.py`, `front_sketch.py` and `cable_gate_sketch.py` run with `--under`, as committed with this plan (the commit that carries this text). Where this text and a sketch differ, this text holds and the report says so. A sketch patches the layer's generator from outside; the model gets the same shapes in `organic_frame.py` itself.

The pilot hole of the M3 inserts went from 4.4 to 4.5 mm in a commit of its own (`772787a`). Figures below that depend on it are for 4.5.

### A. Skeleton

1. **The light line goes.** In `hardware.py`: `LIGHT_STRIP_*`, `LIGHT_LED_TO_DIFFUSER_MIN`, `LIGHT_DIFFUSER_T`, `LIGHT_LINE_W`, the solid `light_strip`, its entries in `KEEP_OUT` and `FRONT_HARDWARE`, its colour. Its readers go with it: `render_vtk.py` (the colour), `render_blender.py` (the slit and `consts["SILL"]`), `blender_scene.py` (`build_light_line`), `organic_frame.py` (the slit it draws), `assembly_access.py` (`HARD_HARDWARE`, `HARDWARE_PREFERENCE`, `SITS_ON`), and in `frame_v0.py` the channel, the slit and their block of the report. Find the rest by search. `hw.FRONT_IO_LED_SLIT_BEYOND` stays: it is the module's own LED.
2. **`front_sill` goes:** its builder, `sill_geometry()`, the pocket, the channel, the slit, the window, its four bolts through `beam_front` and their row in `FASTENERS`, its rows in `check_bolts`, its two organic pads' pilots, its entry in the rounding log, check 22 and every read of `res["sill_wall"]`. Check 22's number is not reused: the report keeps one line that says it was retired with the sill. Not every `SILL_*` name is dead: `SILL_STACK` is the height of `beam_front` that a bolt passes through (20 mm), and the carrier's new screws clamp the same height. It becomes the new `CARRIER_STACK`; the old `CARRIER_STACK` (4.3 mm, the carrier's floor and the pocket's play) goes with the screws it described.
3. **`front_io_carrier` stands on `beam_front`.** Outside as today: X -82..107, Y 0..44.2, top Z 48.9. Its underside comes down to the beam's top: `CARRIER_Z[0]` is `BEAM_FRONT_Z[1]` (10), and `("beam_front", "front_io_carrier")` joins `INTENDED_CONTACTS`. Its four counterbored screws into the sill go, with `M3CB_STACK["front_io_carrier"]` and their rows in `check_bolts`. New: four M3 pilots in the underside of its end blocks, two a block, on each block's middle in X (X -76.2 and 101.2), at Y 10 and Y 30, cut upward; four clearance holes through `beam_front` under them; four screws from below with a washer, their length by `screw_fit(CARRIER_STACK)` (M3 x 25). `joint_mounts` pairs a pilot in the sill with a clearance hole in the carrier today; the pair becomes a pilot in the carrier and a clearance hole in the beam. A new row in `check_bolts`: each new pilot lies inside its end block with the insert's wall, keeps its distance to the module's own pilot, and its clearance hole lies inside `beam_front` clear of the beam's end pilots. Grok measured, on solids: 12.1 mm and 11.0 mm from a new pilot to the module's pilot (at Y 10 and Y 30), 3.6 mm of wall to the block's side, and the beam's end pilots stop at X ±135.3. Report the figures the model gives.
4. **Check 20** keeps the end blocks' least thickness against `CARRIER_END_MIN` (8.3 mm: the module's pilot sets it, `M3_PILOT_DEPTH + M3_MIN_WALL`; the term for the carrier's counterbore goes) and the top plate. Three things in it belong to the sill and go: the sentence about the pocket, the sentence about the window, and the 2.5 mm the module may grow to the rear inside the pocket. Their successor: no part of the skeleton stands in the box behind the module's rear face, `CARRIER_REAR_ROOM = 15.0` deep, over the module's X and Z, so the leads can leave. The box moves with the module's rear face, so the module may grow to the rear until the box meets a part. Today the box is inside the sill; with the sill gone Grok measured the carrier's top plate 0.2 mm above it, `beam_front` 2.0 mm under it and `beam_low` 12.6 mm behind it. Report the model's figures; the rear growth in `out["grow"]` becomes the box's distance to the nearest part behind it.
5. **What follows in the code:** check 5's mounts (the carrier: four screws into `beam_front`), `strength.py`'s list of parts that touch nothing (the carrier now touches the beam and leaves the list), the report's revision note.
6. **`rib_A_right` and `rib_A_left` get a pilot each** for the layer's new pads `front_post_R/L` (part C.5), through `organic_pilots` as every pad's pilot is made. The pad's centre is on the rib's outer face at (±158, 20, -6), between the two clearance holes of `beam_front`'s screws (Y 10 and Y 30, Z 0). By hand, to be replaced by the model's figures: 11.66 mm between the pilot's axis and each hole's, so 7.7 mm of wall.
7. `parts_manifest.py --expect`: removed `front_sill` and `hw:light_strip`; changed `front_io_carrier`, `beam_front`, `rib_A_left`, `rib_A_right`. Any other part that changes is named in the report with the reason.
8. **Expected counts**, to be confirmed by the build or corrected with the reason. Grok's from the report, for the sill and the carrier alone: inserts 108 to 102, washers 97 to 91, screws with a stack 106 to 100, M3 x 10 down to 14, M3 x 25 still 6. The two new pads add two inserts, two washers and two screws of a pad's length to that. The layer's pads stay 16, 12 of them `main`'s: `sill_end_R/L` go, `front_post_R/L` come.

### B. Cables (`cables.py`)

1. `argb` goes: its row, its route, its colour, `LIGHT_START_W`, `LIGHT_PASS_UN`, `OWN["argb"]`.
2. `front_stretch` is called for `usb3` and `usbc` and returns the distance to the board and the distance to `front_sill`. The second goes; the first stays.
3. **Every other route but the card's power cable keeps every point it has today.** `usb3` and `usbc` start where they start today; those two points are read from the sill's window now, and become named constants with the same values, (60, 42, 30) and (70, 42, 30). `jfp1` and `jaud1` keep `THIN_START_YZ`. The main session holds the routes of HEAD and compares them point for point after the build.
4. `FAN_LEFT_START_V` and `FAN_RIGHT` are bound when the module is imported (a leftover of the review of revision 14a). Read them when the route is built, as the USB starts are.
5. The card's power cable: part H.

### C. The layer (`organic_frame.py`), piece `main`

1. **Straight outline.** `front_sweep`, `rear_sweep`, `BASE` and `BROW` as in `straight_sketch.py`: the front post one straight line from the front foot (158, 14, 4) to the end of the card's bone, and on the right one more straight leg to the lip's corner; the rear sweep two straight legs with a knee at (176, 366, 224), then down to (169, 372, 44) and the foot; the base rail one straight line from (160, 40, -4) to (166, 356, -4); the brow straight at Y 13, Z 152 between X -160 and 160. Where the sketch puts a control point each side of a knee, it stands 25 mm from the knee along its leg (`KNEE`); the sketch is the reference for which knees have them. The number of control points of each bone stays (front sweep 4 on the left and 5 on the right, rear sweep 6, base 5, brow 3), because the films slice them.
2. **A flattened tube as a member** (`"slab"`: control points, radius, blend, the axis and the factor it is flattened by), added to `Field.add`. The value it gives is not a true distance along the flattened axis: `shell_concepts.tube` scales the offset by the factor before it subtracts the radius, so the blend and every later reading of the field see it stretched. Say so where the member is defined. Nothing may read a clearance off the field beside a slab (see H.6).
3. **The front** as in `front_sketch.py`: the bone `front_low` straight from (-160, 22, 60) to (160, 22, 60); the hood's roof, a slab along X from -92 to 117 at Y 22, Z 59, radius 26 flattened 3.5 times along Z; two cheeks at X -92 and X 117, slabs of radius 22 flattened 3 times along X, their centre line from Z 56 down to Z 28 (`CHEEK_Z`); the three slabs blended at 10; the film between `front_low` and the brow over X -150..150 with 13 strands, 6 links, seed 23, sag (0, 1, 0) by 2 mm, in place of the veil. `SILL_RIDGE` is the veil's lower bar today and goes with the veil.
4. **Carves:** the sill's prism goes out of `carve_layer` (`SILL`, `sill_sdf`, `SILL_GAP`, `SILL_RIDGE`). New: the way the carrier slides out (its exact box, extended forward to Y -20 and down to Z 0) by `GAP_SKEL`, and the module's box by `GAP_HW`.
5. **Pads.** The rows `sill_end_R` and `sill_end_L` go from `hw.ORGANIC_PADS`, and `BONE_OF["sill_end"]` with them. New rows `front_post_R` and `front_post_L`: on `rib_A_right` and `rib_A_left`, centre (±158, 20, -6), normal (±1, 0, 0), piece `main`; `BONE_OF["front_post"]` is `"front"`. Why: the table above. If `pad_fits` or a pad check refuses the place (the washers of `beam_front`'s screws stand 0.16 mm from the pad's rim by hand), stop and report; do not move the pad.
6. **New check, "the carrier comes out":** no solid voxel of any piece in the carrier's box moved forward along -Y by its own depth (the box and every position on the way). The carrier's box is saved in `field.npz` under the key `carrier_box` (six numbers), so the check can be run on a saved field. A case in `test_organic.py`: a lump in front of the module's face fails it.
7. **A cross-thread is as thick as its length asks.** In `film_members` a link's radius at mid-span is at least `(LINK_PUSH * length / (pi * LINK_ALLOW)) ** (1/3)` and never under `LINK_R[1]`; its radius at the ends is at least 0.8 more and never under `LINK_R[0]` (a round bar held loosely at both ends, pushed in the middle). `LINK_PUSH` and `LINK_ALLOW` are 30 N and 10 MPa in `organic_frame.py`, and a case in `test_organic.py` fails if they differ from `organic_strength.PUSH_N` and `ALLOW`. This applies to every film of both pieces.
8. **The layer stays out of a pad's pilot.** Today a pad is blended on after the skeleton's carve and only the screw's hole (radius 1.75) is cut through it, so the pad can stand in the mouth of the insert's pilot (the pilot commit counted four voxels in each piece). The cut at a pad becomes the pilot's radius plus one voxel from the pad's face down to the pilot's depth, and the screw's hole above the face as today. New check: no solid voxel centre of a piece inside a pad's pilot. A case in `test_organic.py`: a lump in a pilot's mouth fails it.
9. The existing checks of the layer keep working (the rings whole, nothing beyond |X| 260, the empty boxes, each piece one body with its pads, the pieces 3 mm apart, the screw heads on the bulkhead reachable).

### D. `assembly_access.py`

`BILL`: the row `front_sill` goes; `front_io_carrier` stays class A and becomes four screws from below through `beam_front`. `SITS_ON`, `HARD_HARDWARE` and `HARDWARE_PREFERENCE` lose `light_strip`. The script must exit 0. Report where the carrier and the module stand in the order and with which tool the carrier's screws are driven (the beam's underside is 5 mm above the desk).

### E. Tests

The sill, the light strip, the window and check 22 no longer exist, so the records that damage them go. That is the one place where this revision removes cases. Grok's list at `4f34a0b` (`cad_b6/test_checks.py`, by line), to be confirmed or corrected:

- 15 `case()` calls damage something that goes: 963, 966, 969, 975, 978, 980, 1138, 1139, 1142, 1145, 1148, 1149, 1358, 1395, 1399. Eight of them need a successor of the same kind on what replaces their subject: 978, 980, 1138, 1139, 1145, 1148, 1149, 1358.
- 5 `check()` calls go: 929, 946, 1339, 1370, 1387. 2 `bites()` of check 22 go: 1981, 1982.
- `check()` calls to rewrite: 937, 951, 959, 991, 1003, 1009, 1014, the five allowance registrations from 1086, 1131, 1157 (the carrier's screws: M3 x 10 and a 4.3 mm stack today), 1222 (four carrier counterbores, six M3 counterbores), 1353, 1378, 1406, 1952, and the pinned counts at 1887 (inserts) and 1890 (washers). `grown_full` (1091) requires the sill's signature today. The cases at 1155 and 1156 move onto `beam_front`'s clearance holes, where the stack is a real 20 mm.
- The five "15 positions" cases (1417 to 1439) damage `front_foot_R` and stay; the count of pads stays 16.

For each removed record the report gives its name, its line and the reason; a record goes only if the thing it damages is gone. Everything that still exists keeps its case or gets a successor of the same strictness: the carrier's pilots filled and moved (check 5, check 7, the new row of `check_bolts`), the module grown by its whole allowance leaves the carrier's outside unchanged and one step more fails check 20 at the ends and at the top, a block in the room behind the module fails check 20, the carrier's screws' length and washer (check 15), a block behind the module makes the USB routes fail. New cases for the new checks are named in C.6, C.7, C.8, H.6 and I. The pinned counts are reported before and after.

### F. What must hold at the end

- `frame_v0.py`: every check passes. ABS mass: an estimate of 1535 g (1733.2 less the sill's 198.5); report the figure.
- `organic_frame.py`: one body for `main`; `rear_panel` changes with the cross-threads' rule and where `main`'s rear sweep moved (it is carved 3 mm off `main`): report by how much. The sketch has `main` 1920.3 cm³ and `rear_panel` 304.6.
- `organic_strength.py`: both pieces within 10 MPa and 5 mm, the 160 pushes and the new ones of part I. The sketch: 5.4 MPa and 2.79 mm for `main`'s 160, 4.5 MPa and 1.79 mm for its members. If not, stop and report; do not tune.
- `zone_access.py`: bundles and hand not under today's 52, 56 and 44 mm (the floors in the script stay 40 and 44).
- `drive_access.py`, `assembly_access.py`, `cables.py`: pass.
- `organic_manifest.py --expect main,rear_panel`.
- `check_budgets.py` will fail on two lines, both foreseen. The layer's ratchet has a ceiling of 2084.9 cm³ and a floor of 1941.8; the sketch's two pieces are 2224.9. The skeleton's has a floor of 1646.255 g; the estimate is 1535. The main session re-records both in a commit of its own with `--write --accept-lower`. `cad_b6/budgets.json` is not edited by the implementer.

### G. Not in this revision

The module's own face plate with its cut-outs (it waits for the module to be measured). The split of `main` into printable pieces. The smoothing of the layer's surface. A contact rule inside `round_box` (the pilot commit declared the one edge that needed it).

### H. The card's power cable and the layer

**What was wrong.** `cables_through_layer.py` on the committed layer's field (main session, 18 Nov 2026): the 12V-2x6 cable's centre line runs up to 14.7 mm inside the layer over about 84 mm, and a hose of the card's cooler is 1.0 mm inside it over 15 mm. The bone `card` passes over the card's socket: its centre line there is at u 119, n 169 with a radius of 5, and the socket is at u 119. The cable's way down, at u 173, is 4.0 mm from the lip's centre line (u 177, n 171 at X 131.5). The layer is carved from every fourth point of a hose (plus 1 mm) and from no cable, and no check compares cables or hoses with it. The owner saw the first in a render.

**What the owner said (18 Nov 2026).** "Make sure it can be plugged in properly." "The PSU's cables are quite flexible, the cable can go over the card or under it." On hearing of a gate in each of the two bones: "No need to run the card's power cable over the bio-design panel, it can go under it. The main thing is that there is room for the connector."

**What cannot change.** The socket opens along +n at the card's top edge (v 130, u 119, mouth n 137). The plug (13 mm), the straight (35 mm) and the first bend (R 35) stand up from it to n 220 (`cables.GPU12V_TOP_N`), 51 mm beyond the bone's centre line, and the cable already stands 10.4 mm in front of the case's front plane there (11 accepted by the owner). So the cable's first stretch always stands out of the layer, and the layer needs an opening at the connector.

**Layouts tried** (`cable_gate_sketch.py`, `cable_under_route.py`; the figures are the scripts' own, from the main session's runs):

| Layout | Result |
|---|---|
| the bone `card` moved to u 140, the cable's way down to u 158 | `cables.py` fails (12.1 mm in front of Y 0, 11 accepted); `organic_strength.py` 23.1 MPa in the front film. Not pursued |
| the route untouched, a gate in the bone `card` and one in the lip | passes; the cable lies outside the layer from the socket to X 131.5. Set aside by the owner's last message |
| **the cable comes back down beside the connector and runs under the film** (`--under`) | this part. Picture: `docs/plans/sketches/pictures/cable_under.png` |

1. **The route** (`cables.py`, the last section of `gpu12v` only). Today: up the gap at v 253.5, an S-bend to u 173, up to n 220, across to the socket. New, as `cable_under_route.under_wps(83, 192.5, 154, 115)`: from the slab's top (v 253.5, u 184, n 53) up the gap to n 83; over to (v 192.5, u 154, n 115), under the film, in the gap between the card (u up to 126.6) and the 360 (u from 184); up to n 220; across to (v 130, u 119, n 220); down into the socket. `GPU12V_ARCH_U` and `GPU12V_S_N` go, and the report's line that prints `GPU12V_ARCH_U` is rewritten; the four numbers become named constants with a comment that says they were searched and what bounds them (every bend 35; the loop's far leg clear of the lip; clear of the card and of the 360 by `cables.py`'s own check). `cable_under_route.py 83 192.5 154 115` prints: pass; length 639 (700 allowed); least bend 35.0; 9.1 mm in front of Y 0 (10.4 today); tightest `rib_A_right` 3.5 mm (needs 3); nearest cable `usb3` 0.5 mm, in the lanes under the board, where a pair of routes fails only when it overlaps. Everything below the board, the slab and the tie points stay as they are.
2. **The bone `card` gets a gate** at the connector: it becomes `card_L` and `card_R`, with the control points of `cable_gate_sketch.py`. The gate's ends are computed, not typed: the socket's X, its tolerance (12 mm), an allowance of 10 for the plug, 5 to spare and the bone's end radius (6.5) either side. Today that gives X -25.5 and X 41.5. A free end is a ball of radius 8. **The lip stays whole.**
3. **The films between the two bones.** Today the left one ends at X 28 (8 strands, 3 links) and the right one runs from X 44 to the corner (9 strands, 4 links). New: the left one keeps its 8 and 3 and ends at the gate's left end; the right one starts where the loop's far leg has passed (the leg's X, the cable's radius 7, 3 mm of air, the film's `r_a` 6, 3 to spare: X 89.5 today) and runs to the corner on the control points of the sketch, with 6 strands and 3 links. Between them the layer is open over the connector and the loop.
4. **The plug's room:** an empty box in board space, v 100..160, u 105..133, n 137..195 (`PLUG_ZONE` in the sketch, built from the socket's place, its tolerance, the plug and the straight), carved by `GAP_KEEP` and added to `EMPTY_BOXES`, which `field_checks` loops over and `test_organic.py` makes a case from for every key.
5. **The layer is carved from every cable and every hose along the whole centre line.** Every strand of every route of `cables.build_routes()` at its radius plus `GAP_CABLE` (new, 3.0, beside `GAP_SKEL`, `GAP_KEEP` and `GAP_HW`), every hose at its radius plus `GAP_HW`, in place of the present carve from every fourth hose point. One distance transform for each clearance, of the centre lines marked on the layer's grid at steps under one voxel, shared by the pieces; the carve takes one voxel of the layer's grid (`VOX`, 1.5) more than the clearance, because a centre line is marked on the nearest voxel. `organic_frame.py` reads `cables.py`; `cables.py` does not read the layer. `test_organic.py`, `organic_trial.py` and `check_budgets.py` then load `cables` too: report what that costs in time.
6. **New check, "no cable or hose in the layer":** for every strand and every hose, sampled every millimetre, the distance from the point to the nearest solid voxel of any piece, less the strand's radius, is at least the clearance (3.0 for a cable, `GAP_HW` for a hose). The distance is a Euclidean distance transform of the solid, not the field's value: beside a slab the field is stretched. The report prints the five closest. Cases in `test_organic.py`: a lump on the card cable's line fails it; a hose with material on it between two of the old every-fourth points fails it; a wall at the clearance passes and one millimetre closer fails. The main session runs the new check on the committed layer's field, where it has to fail on the card's cable and on the hose.
7. **Report:** the layer's least distance to a cable and to a hose (the sketch, off the field: `jaud1` 4.0 mm, a CPU hose 4.5 mm, the card's cable 8.4 mm); whether the loop's far leg passes the film's plane inside the opening; `cables.py`'s lines for `gpu12v` before and after.

### I. The strength check stops depending on its sample (`organic_strength.py`)

1. `organic_frame.py` saves, for every film strand and every cross-thread of both pieces, the point at the middle of its centre line, its kind and its length (`probes`, `probe_kind`, `probe_len` in `field.npz`).
2. `organic_strength.py` pushes at each of them as it pushes at its 160 places (inward and down, 30 N, the same limits, the same exclusions), for the piece whose surface is within 8 mm of the point. A point with no surface within 8 mm is listed as carved away and judged by nobody. The report gets a section for them: how many were pushed, the worst stress and movement, each one over a limit. They count for the piece's verdict.
3. A case in `test_organic.py`: a thin thread across a gap, with its probe, fails; the same thread at the thickness of C.7's rule passes.
4. Report the run's time before and after. `member_probes.py` is the sketch of this and gives the figures to compare with: 87 members of `main`, worst 4.5 MPa and 1.79 mm.

### Order of work

The parts are checked as they are built: first A, B and D with `frame_v0.py`, `cables.py`, `assembly_access.py` and the test suite; then C and H with `organic_frame.py` and its tests; then I. A stop in one part is reported with what the earlier parts gave.
