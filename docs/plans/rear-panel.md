# The organic rear panel (revision 17)

Asked by the owner on 16 Nov 2026 ("an organic panel at the rear, where the PSU is"), started on 18 Nov 2026 on his word. The first concept is in `docs/plans/cables-and-organic.md` ("Rear panel and drive bays"). This file replaces it.

## What is there today (Grok `code-analysis`, 18 Nov 2026, measured on the built model)

- `psu_bulkhead` closes the rear from the desk to Z 92 across X -142..142. Its rear face is Y 381. The plate is 6 mm thick (Y 375..381); its end blocks, |X| 122..142, are 12 mm (Y 369..381).
- Above it the rear is open: on the plane Y 381, X -142..142 and Z 92 upward. Nothing of the skeleton closes it. The posts of `rib_B` have their rear faces at Y 348, the 420 ends at Y 339 and higher than Z 239.
- The organic layer has nothing between the posts. Its rear sweeps and rear window films run on the flanks, |X| 164..204, and reach Y 385.
- Screw heads on the bulkhead's rear face: the PSU's four at (69, 80), (-69, 80), (69, 16), (-45, 6) and the drive sled's two at (-89.5, 30) and (-89.5, 76) (X, Z). All are below Z 92.
- No routed cable crosses the opening. The modular sockets of the PSU are on its front face.
- The PSU is a box in the model (X -75..75, Y 165..375, Z 0..86), fan face up. No opening for its fan is modelled and no air gap is asserted.
- Every pad of the layer has its normal along X today (`hw.ORGANIC_PADS` holds a sign). The field code itself takes any normal.
- A second solid in the layer's field fails the layer's one-piece check.

## Sketch (main session, 18 Nov 2026)

`docs/plans/sketches/rear_panel_sketch.py` builds the panel in its own field on the layer's grid, carves it like the layer and draws it on the whole design: `previews/b6_rear_panel_sketch.png` (the panel in red so that it reads) and `previews/b6_rear_panel_sketch_dark.png` (as it will look). `docs/plans/sketches/rear_panel_access.py` runs `zone_access` and `drive_access` with the panel added.

The first sketch had two pads on the bulkhead and two on the posts' rear faces. It came out 320 mm wide: a pad on a post stands at X 150 and reaches X 158. That does not fit the bed, and its lower bar stood 8.1 mm from a drive in the bay.

The second sketch, which this plan builds:

- **A frame with a film of strands in it**, like the films of the layer: a lower bar over the bulkhead's top, an upper bar under the 420, two side bars, nine strands and five cross-threads between the bars.
- **Four pads, all on the bulkhead's end blocks**, rear face, at X ±132, Z 64 and Z 25, screwed from behind. Two legs on each side go down to them, and a brace from each upper pad runs inward and up to the lower bar.
- **290 mm wide** (X -145..144.5), 248 mm tall (Z 15..262.5), Y 347.5..400. 319 cm³, 405 g of PETG solid.
- **It stands back.** A drive in the bay ends at Y 375 and stands up to Z 150, 58 mm above the bulkhead. The layer keeps 10 mm from a drive, so the lower bar's centre line is at Y 392 and the panel's rear is flat at Y 401. The case gets 19 mm deeper at the rear: 382 to 401 mm.

Measured on the second sketch:

- `zone_access` with the panel: nothing changes. A bundle of 52 mm still leaves from the board's connectors and 56 mm from the card's outputs; the hand's 44 mm stays.
- `drive_access` with the panel: the drive in its seat is 18.8 mm from the layer (10 asked). The way out is closed: the sled with its drive is 150 mm tall and comes out backward and upward through this opening. **The panel comes off before a drive does.**

## Decisions taken by the main session, for the owner to confirm

| Decision | Why | The other way |
|---|---|---|
| One piece, four screws on the bulkhead, the top edge free | it stays 290 mm wide and prints flat; all four screws are driven from behind with a straight driver | two mirrored halves, each also screwed to a post: stiffer at the top, a seam down the middle, two prints, six or eight screws |
| The panel stands 19 mm behind the bulkhead's face | 10 mm from a drive in the bay | flush with the layer's flanks (Y 385) if the drive bay is given up |
| The panel is taken off to take a drive out | the sled's way out is this opening | a panel with the left third open |
| The panel covers the opening only; the bulkhead's face stays bare apart from the legs | the PSU's and the sled's screw heads and the IEC window are there | strands over the bulkhead's face round the window |
| The same room is kept on the right, where no bay is built | the panel stays mirrored | the right side closer to the bulkhead |

The stiffness of a panel held at the bottom only is not measured yet. By hand (a beam on two legs) a 30 N push at the top gives 5 to 8 MPa in the legs and 2 to 4 mm of movement; the limits are 10 MPa and 5 mm. `organic_strength.py` decides. If it fails, the two-halves design is next, and the owner is told.

## Revision 17: specification

### 1. The layer has named pieces

`organic_frame.py` builds pieces. A piece is a name, its members, its pads and its own field on the common grid. Today's layer is the piece `main`; the panel is `rear_panel`.

- **`main` does not change.** A differential check proves it: the new `main` field equals the field of the commit before, voxel for voxel, on the old grid's extent (keep the old `out/organic/field.npz` beside the new one to compare; say in the report how many voxels differ and where).
- **The grid** grows in Y from 394 to 406 (`shell_concepts.Y1`), for every piece. Nothing else of the grid changes.
- **One piece, one body:** each piece is one connected solid that holds all of its own pads. Loose crumbs under `CRUMB_CM3` are dropped per piece, as now.
- **Pieces keep `GAP_PIECE` = 3 mm from each other.** A later piece is carved back from the earlier ones. A check measures the least distance between any two pieces and fails under 3 mm less one voxel.
- **`out/organic/field.npz`** keeps `d` as the union of all pieces (what every reader takes as "the layer"), and gains `pieces` (the names) and one array per piece. `pads` and `names` gain the piece of each pad. Every reader that takes `d` keeps working unchanged.

### 2. A pad has a normal

`hw.ORGANIC_PADS`: each row carries the pad's outward normal as a unit vector and the piece it belongs to, in place of the sign along X. The twelve existing rows keep their places and normals (±X) and belong to `main`. `frame_v0.organic_pilots` cuts the pilot along minus the normal. The pad's disc, bore, driver channel, knot, stub, `pad_fits`, `pad_clear` and `driver_blocked` in `organic_frame.py` use the normal. Nothing may assume X.

Four new rows, piece `rear_panel`, part `psu_bulkhead`, normal (0, 1, 0), centres on the rear face Y 381 (derive Y from the bulkhead's own constants): (132, 381, 64), (132, 381, 25), (-132, 381, 64), (-132, 381, 25). `psu_bulkhead` gets the four pilots (`organic_pilots`), 6.7 mm deep into its 12 mm end blocks. The end bolts' pilots of the bulkhead stand at (±142, 375, 5) and (±142, 375, 80) along X: checks 7 and 15 judge the walls. If a pad's place fails a check, move it along Z inside the end block (stations Z 13 to 69 passed Grok's probe) and report; do not relax the check.

Consequences to carry through: the bill's `organic` row and its insert and M3 x 10 counts (16 pads; inserts 108), check 5's mount count for `organic`, `assembly_access.py`'s `BILL` (the organic row is counted there, not judged), `parts_manifest.py --expect psu_bulkhead`.

### 3. The panel

Members as in `docs/plans/sketches/rear_panel_sketch.py` (the second sketch; read it, it is the reference for shape and numbers), written in `organic_frame.py`'s own style: named bones `panel_low`, `panel_top`, `panel_side_L`, `panel_side_R`, the film between the lower and the upper bar, the legs and braces to the pads.

- The frame's centre line at |X| 131 (the sketch's 132 gave exactly 290 mm; the piece must be under 290 mm wide: check).
- Lower bar: centre Y 392, Z 104. Upper bar: centre Y 360, Z 250. Radius 6.5.
- Nine strands, five cross-threads, the layer's rules for strand radii (`STRAND_R_*`, `STRAND_SLENDER`).
- Rear limit: nothing of the panel behind Y 401. The knots round the screws get a flat rear face there.
- Carved like `main` (the same gaps to hardware, hoses, keep-outs and skeleton), and from: each body of `hw` `drive_left` and its mirror image on the right, by `HOT_GAP`; `main`, by `GAP_PIECE`.

### 4. Checks, each with a case in `test_organic.py` that damages the field and expects the failure

- Each piece one body with its pads; pieces 3 mm apart.
- **Bed:** each piece's extent along each world axis. For `rear_panel` X and Z must be at most `frame_v0.MAX_PART` (290). `main` is not split yet: report its extents, do not fail on them, and say so in the report.
- **Screw heads stay reachable:** no voxel of any piece in a cylinder 12 mm across and 100 mm long behind (along +Y from) each screw head on `psu_bulkhead`'s rear face. Take the positions from the part's holes (the `6-32cb` counterbores and the clearance holes of the sled's flange screws), not from typed numbers.
- **The layer keeps 10 mm from a drive, the panel included** (`drive_access.py` reports and fails on this already; the panel must pass it).
- **A drive comes out with the panel off.** `drive_access.py` computes the way out without the pieces named in a new constant (`REMOVED_FOR_DRIVE = ("rear_panel",)`), says so in its report, and still measures the seat's distance against every piece. A test proves both halves: with the panel counted there is no way out, without it the least tilt is what it was (28° of 30°).
- **`zone_access.py`** with the union: the bundles' 52 and 56 mm and the hand's 44 mm must not get worse.
- **`organic_strength.py`:** every piece is pushed, each fixed at its own pads. Limits unchanged (10 MPa, 5 mm). Report each piece's worst stress and largest movement. If the panel does not pass, stop there: do not thicken, move or tune anything, report the numbers and where.
- The existing checks of `main` (rings whole, nothing beyond |X| 260, the three empty boxes) keep working on the union.

### 5. What must not happen

- No existing case of `test_organic.py` or `test_checks.py` removed or weakened; counts reported before and after.
- No hardware number retyped: the bulkhead's face, the end blocks, the drive's box and the screw heads come from `hardware.py` and `frame_v0.py`.
- `cad_b6/budgets.json` is not edited. The organic volume will pass its ratchet (1741.7 cm³ + 2 %); `check_budgets.py` is expected to fail on that one line, and the main session re-records it in a commit of its own.

### 6. Reruns

By the implementer: `frame_v0.py`, `organic_frame.py`, `test_organic.py`, `drive_access.py`, `zone_access.py`, `organic_strength.py`, `parts_manifest.py --expect psu_bulkhead`, `assembly_access.py`, `test_assembly.py`, `test_checks.py` once at the end. By the main session again, plus `cables.py`, `strength.py`, `check_budgets.py`, `render_full.py`.
