# The organic rear panel (revision 17)

Asked by the owner on 16 Nov 2026 ("an organic panel at the rear, where the PSU is"), started on 18 Nov 2026 on his word. The first concept is in `docs/plans/cables-and-organic.md` ("Rear panel and drive bays"). This file replaces it.

## What is there today (Grok `code-analysis`, 18 Nov 2026, measured on the built model)

- `psu_bulkhead` closes the rear from the desk to Z 92 across X -142..142. Its rear face is Y 381. The plate is 6 mm thick (Y 375..381); its end blocks, |X| 122..142, are 12 mm (Y 369..381).
- Above it the rear is open: on the plane Y 381, X -142..142 and Z 92 upward. Nothing of the skeleton closes it. The posts of `rib_B` have their rear faces at Y 348, the 420 ends at Y 339 and higher than Z 239.
- The organic layer has nothing between the posts. Its rear sweeps and rear window films run on the flanks, |X| 164..204, and reach Y 385.
- Screw heads on the bulkhead's rear face: the PSU's four at (69, 80), (-69, 80), (69, 16), (-45, 6) and the drive sled's two at (-89.5, 30) and (-89.5, 76) (X, Z). All are below Z 92.
- No routed cable crosses the opening. The modular sockets of the PSU are on its front face.
- The PSU is a box in the model (X -75..75, Y 165..375, Z 0..86), fan face up. No opening for its fan is modelled and no air gap is asserted.
- A drive in the left bay: the 3.5 inch body is X -119.1..-93, Y 256..357.6, Z 3..150; the 2.5 inch body X -86..-79, Y 271.9..341.7, Z 49.6..150. The sled is X -96.5..-82.5, Y 252..375, Z 0..145: it stands 53 mm above the bulkhead, against its front face.
- Every pad of the layer has its normal along X today (`hw.ORGANIC_PADS` holds a sign). The field code itself takes any normal.
- A second solid in the layer's field fails the layer's one-piece check.

## Sketches (main session, 18 Nov 2026)

`docs/plans/sketches/rear_panel_sketch.py` builds the panel in its own field on the layer's grid, carves it like the layer and draws it on the whole design: `previews/b6_rear_panel_sketch.png` (the panel in red so that it reads) and `previews/b6_rear_panel_sketch_dark.png` (as it will look). `docs/plans/sketches/rear_panel_access.py` runs `zone_access` and `drive_access` with the panel added.

1. Two pads on the bulkhead and two on the posts' rear faces: 320 mm wide (a pad on a post stands at X 150 and reaches X 158). It does not fit the bed. Its strands leaned over a drive's upper rear corner, 8.1 mm from it.
2. Four pads on the bulkhead, the lower bar at Y 392: fits, but the case got 19 mm deeper. That depth came from a wrong reading: the main session took the bay's envelope (Y 375) for the drive's end, which is at Y 357.6.
3. The lower bar at Y 379: the sled's top bit into the bar on the left only.
4. **The one this plan builds.** The lower bar at Y 384.

The fourth sketch:

- **A frame with a film of strands in it**, like the films of the layer: a lower bar over the bulkhead's top, an upper bar under the 420, two side bars, nine strands and five cross-threads between the bars.
- **Four pads, all on the bulkhead's end blocks**, rear face, at X ±132, Z 64 and Z 25, screwed from behind. A leg goes from each pad up to the frame's lower corner, and two more legs fan out from each upper pad inward to the lower bar: over the bulkhead's top edge the panel can only be as thick as the room behind the bulkhead (Y 383 to 391.5), so it is made wide there.
- **288 mm wide** (X -144.25..143.75), 249 mm tall (Z 14.25..263.25), Y 346.75..391.75. 299 cm³, 380 g of PETG solid.
- **Its rear is flat at Y 391.5**, 6.5 mm behind the layer's flanks (Y 385) and 10 mm behind the skeleton (Y 382). The layer's grid (to Y 394) holds it; the grid does not change.

Measured on the fourth sketch:

- `zone_access` with the panel: nothing changes. A bundle of 52 mm still leaves from the board's connectors and 56 mm from the card's outputs; the hand's 44 mm stays.
- `drive_access` with the panel: a drive in its seat is 13.4 mm from the layer (10 asked), the sled 2.1 mm (2 asked of the skeleton). The way out is closed: the sled with its drive is 150 mm tall and comes out backward and upward through this opening. **The panel comes off before a drive does.**

## Decisions taken by the main session, for the owner to confirm

| Decision | Why | The other way |
|---|---|---|
| One piece, four screws on the bulkhead, the top edge free | it stays under 290 mm wide and prints flat; all four screws are driven from behind with a straight driver | two mirrored halves, each also screwed to a post: stiffer at the top, a seam down the middle, two prints, six or eight screws |
| The panel's rear stands 10 mm behind the skeleton's | the lower bar has to clear the sled's top, and the legs need thickness behind the bulkhead | none found that keeps the bay |
| The panel is taken off to take a drive out | the sled's way out is this opening | a panel with the left third open |
| The panel covers the opening only; the bulkhead's face stays bare apart from the legs | the PSU's and the sled's screw heads and the IEC window are there | strands over the bulkhead's face round the window |
| The same room is kept on the right, where no bay is built | the panel stays mirrored | the right side closer in |

The stiffness of a panel held at the bottom only is not measured yet. By hand (a beam on its legs) a 30 N push at the top gives about 5 MPa in the legs and 2 to 4 mm of movement; the limits are 10 MPa and 5 mm. `organic_strength.py` decides. If it fails, the two-halves design is next, and the owner is told.

## Revision 17: specification

The reference for the panel's shape and numbers is `docs/plans/sketches/rear_panel_sketch.py` as committed with this plan (the fourth sketch). Where this text and the sketch differ, this text holds, and the implementer says so in the report.

### 1. The layer has named pieces

`organic_frame.py` builds pieces. A piece is a name, its members, its pads and its own field on the common grid. Today's layer is the piece `main`; the panel is `rear_panel`. The grid does not change.

- **`main` does not change.** A differential check proves it: the new `main` field equals the field of the commit before with `np.array_equal`, no tolerance (copy the old `out/organic/field.npz` aside before the first run and compare `d` of `main` with the old `d`; report the number of voxels that differ).
- **One piece, one body:** each piece is one connected solid that holds all of its own pads. Loose crumbs under `CRUMB_CM3` are dropped per piece, as `build()` does now, and what is left must be one body (`check()`'s test, run per piece, before the union is made). The join test of a pad samples a point of the pad's disc beside its screw: the offset is across the pad's normal, not along Y.
- **Pieces keep `GAP_PIECE` = 3.0 mm from each other** (a new constant in `organic_frame.py`). A later piece is carved back from the earlier ones. A check measures the least distance between the solids of any two pieces and fails under `GAP_PIECE` less one voxel.
- **`out/organic/field.npz`:** `d` is the union of all pieces, which is what every present reader takes as "the layer". `pads` stays an (n, 6) array (centre and normal) and `names` stays the pads' names. New arrays: `pieces` (the pieces' names), `pad_piece` (the piece of each pad, in the order of `names`), and one field per piece named `d_<piece>`. No column is added to `pads`: `organic_strength.py` reads `row[3:]` as the normal.

### 2. A pad has a normal

`hw.ORGANIC_PADS`: each row carries the pad's outward normal as a unit vector and its piece, in place of the sign along X. The twelve existing rows keep their places and normals (±X) and belong to `main`.

Everything that reads a row follows, and nothing may assume X. Grok's list: `frame_v0.organic_pilots` (cuts along minus the normal; for a mirrored part the normal's X flips) and its callers; `frame_v0.mount_points` (check 5 probes the pilot: along the normal, not along X); in `organic_frame.py` `face_hit`, `is_pilot_of`, `pad_fits`, `pad_clear`, `driver_blocked`, `pad_pilot_failures`, `place_anchors`, the pad's join test; `test_checks.py`'s `anchors_of`. The row in `FASTENERS` and its note ("6 a side ... along X") follow too.

Four new rows, piece `rear_panel`, part `psu_bulkhead`, normal (0, 1, 0), centres on the bulkhead's rear face:

| Pad | Centre |
|---|---|
| `panel_hip_R` | (132, 381, 64) |
| `panel_foot_R` | (132, 381, 25) |
| `panel_hip_L` | (-132, 381, 64) |
| `panel_foot_L` | (-132, 381, 25) |

X 132 is the middle of the end block (`(BULK_BLOCK_X + X_IN) / 2`), Y 381 is `BULK_Y1`; the rows are literals in `hardware.py` like the other twelve, and the existing check that a pad sits on its part's face on a pilot of that part is what holds them to the part. `build_psu_bulkhead` gets `organic_pilots("psu_bulkhead")` before `drill`, as `front_sill` does. The pilot is `joint_pilots(..., hw.ORGANIC_PAD_H)` like every organic pad: stack 5, M3 x 10, the bore 6.7 mm deep (`hw.M3_PILOT_DEPTH`).

Measured by Grok on the built bulkhead with the four cutters: 7.8 mm of wall to the block's outer face (1.6 asked), 5.3 mm of floor (1.2 asked), 12.0 and 15.9 mm to the nearest end bolt's cutter, 66.8 mm to the window. Check 7 (`check_hole`, `pilot_walls`) judges the walls; check 15 counts the screws and inserts. If a pad's place fails a check, move it along Z inside the end block and report; do not relax the check.

A pad may name its own legs. `BONE_OF` ties a pad to a bone by the automatic stub; the four panel pads use the legs declared with the panel (below) and get no automatic stub. `place_anchors` still tests each of them (`pad_fits`, `pad_clear`, `driver_blocked`).

**Counts that move with the model** (the damage each test does stays the same; list every changed expectation in the report with its old and new value): organic pads 12 to 16 (`EXPECTED_MOUNTS["organic"]`, which should be derived from `hw.ORGANIC_PADS` instead of typed; the cases at `test_checks.py` about 1405 to 1425 and 1917, "11 positions" becoming 15), inserts 104 to 108, washers 93 to 97, M3 x 10 screws 16 to 20, `assembly_access.py`'s `BILL` (the organic row is counted there, not judged). `parts_manifest.py --expect psu_bulkhead` must pass.

### 3. The panel

Written in `organic_frame.py`'s own style, as members of the piece `rear_panel`:

- Named bones `panel_low` (centre line (-131, 384, 104), (0, 386, 106), (131, 384, 104)), `panel_top` ((-131, 360, 250), (0, 362, 253), (131, 360, 250)), `panel_side_L` and `panel_side_R` (from the lower to the upper corner, bowed 2 mm outward and 2 mm back at mid-height), radius 6.5, blend `K`, a ball of radius 9 on each corner.
- The film between `panel_low` and `panel_top`: `film_members`, nine strands, five links, seed 17, bar radii 6.5, sag (0, 1, 0.3) by 6 mm.
- Legs: from each pad a tube `bone(8, 7, 8)` to the frame's lower corner on its side; from each `panel_hip` pad two more tubes `bone(7.5, 7, 7.5)` to the lower bar at |X| 115 and |X| 100 (Y 384, Z 105). A knot round each pad as for the other pads.
- Rear limit: nothing of the panel behind Y 391.5 (a named constant). The knots get a flat rear face there.
- Carved exactly as `build()` carves `main`, in the same order (that includes the card, the side fans, the out prism, the sill, the desk, the front plane and the |X| limit, which the sketch leaves out because they are far away), and also from: each body of `hw`'s `drive_left` and its mirror image on the right, by `HOT_GAP` (take each body's box with `frame_v0.exact_box`); `main`, by `GAP_PIECE`.

### 4. Checks

New checks in `organic_frame.py`, each a function of the saved arrays so that `test_organic.py` can damage a copy and expect the failure (one case per check at least):

- Each piece one body with its pads. Pieces `GAP_PIECE` apart.
- **Bed:** a piece's extent along a world axis is the span of its solid voxels' centres plus one voxel. `rear_panel`'s X and Z extents must not be over `frame_v0.MAX_PART` (290). `main` is not split yet: its extents are reported and not failed, and the report says why.
- **Screw heads stay reachable:** no solid voxel of any piece in a cylinder behind each screw head on `psu_bulkhead`'s rear face. The cylinder starts on the rear face and runs along +Y for `HEAD_REACH` (45, the layer's own driver channel length), radius `(hw.UNC6_HEAD_D + hw.TOOL_PLAY) / 2` (3.6, which is also `HEAD_R`). The heads are found from the part's holes: every hole of kind `6-32cb` (its mouth is on the rear face) and every hole of kind `M3c` on this part (the sled's flange screws; the head is at the hole's end with the larger Y). Six cylinders today; the count is reported.

Changes to other scripts:

- **`drive_access.py`:** `load_field` keeps the per-piece arrays. `bay_maps` builds the organic obstacle map without the pieces named in a new constant `REMOVED_FOR_DRIVE = ("rear_panel",)`; `organic_gap` (the 10 mm between the layer and a drive in its seat) keeps using the union. The report says which pieces were taken off. A test in `test_checks.py`'s drive section proves both halves: with the panel counted there is no way out; with it removed there is one within the tilt limit. The least tilt is reported, not pinned.
- **`zone_access.py`:** no change. Its floors stay 40 and 44 mm. The main session compares the report with today's 52, 56 and 44 mm.
- **`organic_strength.py`:** one run per piece: the piece's own field, fixed at its own pads, `N_POINTS` pushes on it. The limits stay 10 MPa and 5 mm. The report gives each piece's worst stress and largest movement and one headline. If the panel does not pass, stop there: do not thicken, move or tune anything; report the numbers and where the worst is.
- `check_budgets.py`, `organic_trial.py`, `render_full.py`, `test_organic.py`'s existing cases: they read `d` and keep working; say so after running them.

### 5. What must not happen

- No existing case of `test_organic.py` or `test_checks.py` removed or weakened; counts reported before and after (`test_organic.py` has 26 cases and no pin: add a pinned count, as `test_checks.py` has).
- No hardware number retyped.
- `cad_b6/budgets.json` is not edited. With the panel the layer is about 2040 cm³; `check_budgets.py` will fail on the line "organic layer, ratchet" (limit 1776.5 cm³) and pass the PETG stock line. The main session re-records the figure in a commit of its own.

### 6. Reruns

By the implementer, in this order: `frame_v0.py`; `parts_manifest.py --expect psu_bulkhead`; `organic_frame.py`; the differential check of `main`; `test_organic.py`; `drive_access.py`; `zone_access.py`; `organic_strength.py` (about 15 minutes); `assembly_access.py` and `test_assembly.py`; `test_checks.py` once at the end (it rewrites the suite's record; every `cad_b6/*.py` and the field are in its digest). By the main session again, plus `cables.py`, `strength.py`, `check_budgets.py`, `render_full.py`.

## Result of the first build (18 Nov 2026): the machinery holds, the panel held at the bottom only does not

Built by an Opus child from the specification above. Its report, not yet rerun by the main session:

- **`main` is unchanged:** 0 of 28,245,000 voxels differ from the field of the commit before; its pads, names and grid are equal; its strength figures are the same (6.5 MPa, 2.16 mm).
- The pieces, the pads with a normal, the four pilots in `psu_bulkhead` (7.8 mm of wall, 5.3 mm of floor, 12.0 and 15.9 mm to the end bolts), the checks and their tests are in: `test_organic.py` 26 to 35 cases, `test_checks.py` 324 to 328, `test_assembly.py` 51.
- The panel came out 303.6 cm³, 289.5 mm wide. The drive in its seat keeps 13.4 mm; with the panel off it comes out at 28°; the bundles (52, 56 mm) and the hand (44 mm) are as before.
- **`organic_strength.py` fails the panel: 13.9 MPa (10 allowed) and 8.97 mm (5 allowed).** The stress peaks at (±129, 383, 73), the root of the legs just above the hip pads; the movement is at the top corners. The hand estimate in this plan (about 5 MPa, 2 to 4 mm) was wrong: a push on a top corner loads one side's legs alone, and the estimate had shared it between both.

### Variants tried by the main session (`docs/plans/sketches/rear_panel_iter.py`: only the panel is built and pushed, 15 s a run; the limits are the script's own)

| Variant | Volume | Width | Worst stress | Largest movement |
|---|---|---|---|---|
| as built | 303.6 cm³ | 289.5 | 13.9 MPa | 8.97 mm |
| bars of radius 8.5 | 364.6 | 288.0 | 13.1 | 7.20 |
| and thicker legs, three braces a side | 374.4 | 289.5 | 11.9 | 6.26 |
| and the rear flat at Y 392.9 | 386.2 | 289.5 | 10.0 | 4.93 |
| lower top bar (Z 225) with the thick legs | 327.4 | 289.5 | 10.6 | 4.64 |
| **two more pads on the posts' rear faces** (the first build's bars and legs) | 314.8 | 321.0 | **5.5** | **0.98** |
| **the same without the two foot pads** | 301.8 | 321.0 | **6.4** | **0.97** |

A panel held at the bottom only reaches the limits exactly, with a quarter more plastic and no margin: the strap over the bulkhead's top edge can only be 8.5 to 10 mm thick, and it carries the whole moment. Held at the top as well it is as stiff as the rest of the layer (`main`: 6.5 MPa, 2.16 mm).

### Decision of the main session, for the owner to confirm: held at four corners, printed upright

The panel is one piece on four screws, all driven from behind: `panel_hip_R/L` on the bulkhead's end blocks and `panel_top_R/L` on the posts' rear faces. The foot pads go. It is 321 mm wide at its two upper pads, so **it does not lie flat on the 290 mm bed**. It is printed standing as it stands on the case, turned on the bed: 321 mm by 45 mm on the diagonal takes about 259 mm each way, and it is 211 mm tall. The strands run nearly upright, which prints without support; the two bars and the legs need support. Not tried on the printer.

The other ways, not taken: the heavy bottom-held panel at the limits (flat print, springy); two halves (each flat, but each half's bars then end free in the middle, and a 30 N push on a free end of a 131 mm bar of radius 6.5 is 18 MPa by hand, so the halves would need a screwed joint between them).

## Revision 17, second step: specification of the change

Against the first build, which stays as it is apart from this:

1. **Pads.** `hw.ORGANIC_PADS`: the rows `panel_foot_R` and `panel_foot_L` go. Two new rows, piece `rear_panel`, normal (0, 1, 0): `panel_top_R` on `rib_B_right` at (150, 348, 236) and `panel_top_L` on `rib_B_left` at (-150, 348, 236). X 150 is the middle of the rib's thickness (`(X_IN + X_OUT) / 2`), Y 348 is `POST_REAR_Y`; literals in `hardware.py` like the others, held to the part by the pad checks. The ribs already cut the pilots of their own rows (`organic_pilots`); make sure a pad whose normal is not along X is cut right on a mirrored part (the normal's X flips, Y and Z do not). The bulkhead keeps two pilots, each rib B gets one more. Checks 7 and 15 judge them; the antler's tongue bolts stand at (±168, 340, 245) and (±168, 328.7, 256.3) along X in the same post: report the measured walls. If a place fails a check, move the pad along Z on the post's rear face and report; do not relax the check.
2. **Legs.** A `panel_top` pad gets a knot and one leg `bone(*PANEL_LEG)` to the frame's upper corner on its side, bowed 2 mm along the pad's normal. The hip pads keep their leg to the lower corner and their two braces. `OWN_LEGS` names the three kinds.
3. **Bed.** A piece fits the bed when, standing as built (Z up) and turned about the vertical by some angle, its extents are at most `frame_v0.MAX_PART` along both horizontal directions and along Z. The check tries every whole degree from 0 to 179 on the solid voxels' centres (extent = span plus one voxel), reports the best angle with its two horizontal extents and the height, and fails when no angle fits. `main` is still reported and not judged. The report line says in words that the panel is printed upright and turned, and that this is not tried on the printer. Test cases: a panel lengthened in Y so that no angle fits fails; today's panel passes at about 45°; the old case (a lump on its end) is rewritten to the same strictness and the report says so.
4. **Counts that move:** organic pads stay 16 (12 `main`, 4 `rear_panel`: 2 on `psu_bulkhead`, 1 on each rib B); inserts, washers and M3 x 10 screws stay 108, 97 and 20. `parts_manifest.py --expect psu_bulkhead,rib_B_right,rib_B_left`.
5. **Reruns,** as in section 6 above, with `organic_strength.py` expected to pass both pieces (the sketch gave 6.4 MPa and 0.97 mm for the panel). If it does not, stop and report.

## Grok's check of the first specification (18 Nov 2026)

`code-analysis` read the first text against the code, built the bulkhead and measured the four pilots. What it changed: the union alone fails the layer's one-piece check, so that check runs per piece; a column on `pads` would break the strength script, so the piece of a pad is a parallel array; "nothing may assume X" needed seven more places than the text named; the new pads had no names and no way to a bone; the legs were ambiguous between automatic stubs and the sketch's tubes; the pinned counts in `test_checks.py` that move (12, 11, 104, 93, 16) were not named; the bed test and the "extent" of a voxel piece were undefined; the screw-head cylinder had typed numbers; "checks 7 and 15 judge the walls" was wrong for check 15; the drive's end was given as Y 375 where the body ends at Y 357.6 (which also took 9 mm off the panel's depth and made the longer grid unnecessary). Confirmed: bitwise equality of `main` is achievable; the four pilot places clear every wall rule; the readers of `d` do not hard-code the grid's shape.
