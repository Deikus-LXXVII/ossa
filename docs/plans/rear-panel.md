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

## Grok's check of the first specification (18 Nov 2026)

`code-analysis` read the first text against the code, built the bulkhead and measured the four pilots. What it changed: the union alone fails the layer's one-piece check, so that check runs per piece; a column on `pads` would break the strength script, so the piece of a pad is a parallel array; "nothing may assume X" needed seven more places than the text named; the new pads had no names and no way to a bone; the legs were ambiguous between automatic stubs and the sketch's tubes; the pinned counts in `test_checks.py` that move (12, 11, 104, 93, 16) were not named; the bed test and the "extent" of a voxel piece were undefined; the screw-head cylinder had typed numbers; "checks 7 and 15 judge the walls" was wrong for check 15; the drive's end was given as Y 375 where the body ends at Y 357.6 (which also took 9 mm off the panel's depth and made the longer grid unnecessary). Confirmed: bitwise equality of `main` is achievable; the four pilot places clear every wall rule; the readers of `d` do not hard-code the grid's shape.
