# Feature map: what the case has to do, and what proves it

Written on 17 Nov 2026. One row per thing the owner will do with the case or expect of it. "Proved in the model" means a script fails when it is not so. "Proved on the hardware" means the owner tried a printed gauge or part. A row without proof is a gap, not a promise.

Use it two ways: as the definition of done for a revision (no row may get worse), and as the list of what still has to be proved before printing in ABS.

## Mounting the components

| Feature | Proved in the model | Proved on the hardware | Gap |
|---|---|---|---|
| The board screws to nine standoffs | check 5 (mounts from the solids), check 15 (screws) | gauges `G4a`, `G4b` printed, not tried (PC not apart) | hole pattern not confirmed on the real board |
| The 420 hangs on its twelve fan screws | checks 5, 14, 15; `strength.py` "stiff" | gauge `G1` printed, not tried | pattern and port offsets not confirmed; fan screw length (6-32, about 35 mm) not measured |
| The 360 hangs on its arms | checks 5, 16, 23 (each screw with its head can be offered up to its counterbore past its own part: the screw's axis keeps the part half the head's way off, least margin 0.15 mm) | gauge `G2` printed, not tried | the model's least sure numbers (ports taken from ARCTIC's) |
| The PSU screws to the bulkhead and rests on the skids | checks 5, 16 | gauge `G3` printed, not tried | screw length is an assumption |
| The card stands in its slot, held at the bracket and resting at the far end | checks 5, 18 (2.03 MPa, margin 3.29), 19 (2.81 MPa, margin 2.37); check 16 (the rest's screw heads sit in counterbores deep enough for head and washer) | gauge `G7`: height and hose exits fit | the bracket tab's height is inferred from the PCIe drawing (108.3 mm against the model's 108.0), not measured |
| The CPU block's hoses leave where the model says | hose routes | gauge `G5` fits with a little play; the fittings turn | fitting spacing 23.8 mm not measured |
| The side fans screw to their brackets | checks 5, 11, 17 | gauge `G6` fits | none |
| A 3.5" or a 2.5" drive screws into the left bay | check 13 | none | no drive on hand; the bay is a provision |
| The front I/O module sits in its carrier | check 20 (end blocks 11.60 mm, top plate 2.70 mm, 2.50 mm behind the module); check 22 (rear wall 2.90 mm, at least 2); `test_checks.py`: a module grown to its whole allowance leaves the sill unchanged and passes every check | none | every dimension of the module is a placeholder |

## Using the case

| Feature | Proved in the model | Proved on the hardware | Gap |
|---|---|---|---|
| A plug goes into each rear connector of the board and its cable leaves to the rear | `zone_access.py`: zone free, a 52 mm bundle gets out, and 52 mm with the organic layer in place (40 mm asked) | none | the plug's 50 mm depth is an assumption |
| A plug goes into each video output of the card and its cable leaves to the rear | `zone_access.py`: zone free, a 72 mm bundle gets out, and 56 mm with the organic layer in place (40 mm asked) | none | which part of the bracket carries the outputs is read off a photograph |
| A hand reaches the board's rear connectors | `zone_access.py`, the hand line: a 50 mm ball without the layer, 44 mm with it (budget 44; the layer costs the hand 6 mm) | none | the owner confirmed the budget of 44 mm on 17 Nov 2026; a hand is not a ball |
| A drive goes in and out with the rest assembled, once the rear panel is off | `drive_access.py`: least tilt 28° of 30° allowed, computed with the layer's piece `rear_panel` taken off (`REMOVED_FOR_DRIVE`); the layer, the panel included, keeps 13.4 mm from a drive in its seat (10 asked); `test_checks.py`: with the panel counted there is no way out | none | 2° of margin; since revision 17 the panel's four screws come out first (the owner has not confirmed this) |
| Every internal cable reaches its socket with its real length | `cables.py` | none | several real lengths are assumptions; the front I/O leads are not measured |
| Both pairs of hoses reach without a bend tighter than 35 mm | hose routes, checks 9 and 10; check 21 (the CPU clip shadows 112 mm² of the fan's circle, limit 400); `test_checks.py`: the CPU clip still passes check 10 with either hose moved 1 mm | none | hoses are rigid lines in the model; no maker states a bend radius; the ARCTIC length is 450 or 500 mm depending on the source |
| Nothing sticks out to catch a passer-by | check 8 (|X| 229, the fans and their brackets 260, front plane) | none | none |
| The power button, the ports and the light line face the user | `front_sill`, check 20 (the cable window lies behind the module's rear face), `cables.py` (the front USB cables pass through the window) | none | placeholder module; the LED strip is not chosen |

## Carrying the load

| Feature | Proved in the model | Proved on the hardware | Gap |
|---|---|---|---|
| The skeleton carries every component with a safety of 3 across the layers | `strength.py`, "stiff" model, worst 2.87 MPa of 6.7 | none | ABS figures are typical values, not this spool's |
| A knock on a fan, a pull on a cable, the card's weight | checks 17, 18, 19 (margins 2.56, 3.29, 2.37) | none | hand calculations, no mesh |
| An insert holds its screw | check 15: every joint engages 3.5 to 4.0 mm of thread, the minimum of the entry and the insert's 4.0 mm (the bill: 4.00 mm on every length except M3 x 20, which is 3.50 mm on 30 joints); check 7: walls as plain distances as well as the volume of the ring, at least 1.6 mm over the insert's zone (from the mouth, 4.3 mm) and 1.2 mm deeper and under the floor. The report's tightest five in the zone are 2.300, 2.300, 2.700, 2.700 and 2.700 mm; the tightest five below it and under the floor are 1.300 mm | coupon `C2` waits for the inserts | pull-out strength is not measured (two joints see about 225 N and 200 N in their worst case); the pilot's 4.4 mm is the maker's figure until `C2` is tried; the insert's depth is set by hand (flush, `docs/printer-and-materials.md`), and nothing in the model stops one pushed deeper |
| The organic layer survives a 30 N push anywhere | `organic_strength.py`, each piece held at its own pads: `main` worst 6.5 MPa, largest movement 2.16 mm; `rear_panel` 6.4 MPa, 0.97 mm (limits 10 MPa and 5 mm); the pieces' own weight is judged too (0.15 and 0.03 MPa). The script exits with an error when a push or the weight is over a limit | none | the allowable is an ABS stand-in (20 MPa across the layers, safety 2, where the skeleton uses 3) on a layer that will be PETG; PETG's strength across the layers is not measured, so the pass is not proved for PETG |

## Making it

| Feature | Proved in the model | Proved on the hardware | Gap |
|---|---|---|---|
| Every skeleton part fits the bed (290 mm) | check 4: every part's box along the world axes is at most 290 mm on each side (`MAX_PART`); `test_checks.py`: a sill grown to 300 mm fails | none | the box is taken along the world axes, so a part that lies at 45° is judged larger than it is (the safe side); no print orientation is recorded, and supports are not looked at |
| Every joint uses a screw and an insert the owner has | check 15, the bill of fasteners | none | the insert's size is the owner's measurement (4.0 mm long, 4.96 mm outside, 17 Nov 2026); the pilot's diameter is an assumption until `C2` is tried; `C2` is printed in PETG (owner, 17 Nov 2026), so its figure still has to be confirmed in ABS on the first small part |
| A screwdriver reaches every screw | `assembly_access.py` (exit 1 otherwise; `test_assembly.py`, 51 cases): each of the 120 screws (90 in inserts, 30 into the hardware) has a tool, of those assumed, that no part or hardware solid blocks at the step its joint is complete; check 23 for the screw's own part; the organic pads by `driver_blocked` | none | the tools are assumptions (a straight driver 75 mm with a 30 mm handle, a 2.5 mm L-key, a 45 mm stubby driver) until the owner names his; 22 screws are reached only while the case is being put together, so re-tightening them means taking off what covers them; the organic layer and the cables are not in the case here; the two front I/O screws are not judged (placeholder); a hand is not modelled |
| The parts can be put together in some order | `assembly_access.py` finds one (45 steps in the case, and the 360 with its two arms put together on the bench first) and writes it to `out/assembly/order.md`; the order is re-checked step by step by the rule the search uses | none | no path is computed for moving a part into its place past the others; nobody holds the part while its first screw goes in; the CPU block and the card have no screw in the model; the order is not tried on printed parts |
| Printed holes come out the size the model asks | none | coupons `C1` (not printed), `C2` (waits for inserts; to be printed in PETG) | shrinkage of ABS and PETG not measured |
| The organic layer prints | `organic_frame.py`, bed check: the piece `rear_panel`, standing as built and turned 45° about the vertical, takes 245.0 x 244.0 mm and is 211.5 mm tall (290 allowed each way); `cad_b6/organic_manifest.py` names any piece that changes outside an expected list | none | `main` is not split into pieces and is not judged against the bed; the panel is 321 mm wide and does not lie flat: printed upright and turned, with support under its bars and legs, not tried on the printer; the surface is lumpy; PETG settings are untested starting values |
| The open rear above the PSU is closed by a panel that leaves the cables, the screws and the PSU alone | `organic_frame.py`: the piece `rear_panel` is one body on four pads (two on `psu_bulkhead`, one on each `rib_B` post), 3 mm and more from `main` (15.7 mm), no voxel in the driver's way to the six screw heads on the bulkhead's rear face, 10 mm from the PSU; `zone_access.py`: the bundles (52 and 56 mm) and the hand (44 mm) are as without it; checks 5, 7 and 15 for its four pilots | none | the case is 10 mm deeper (Y 391.75 against the skeleton's 382); the PSU's fan has no modelled opening and no air gap is asserted; no check judges a driver's way to an organic pad past the skeleton and the hardware (`driver_blocked` looks at the layer's own bones, `assembly_access.py` skips organic pads); for the two top pads it was measured by hand twice: 9.85 mm clear of the antler |

## Budgets

What the owner pays for, recorded in `cad_b6/budgets.json` and held by `cad_b6/check_budgets.py` (exit 1 on a FAIL; `cad_b6/test_budgets.py` proves each budget fails when exceeded, when its input is missing, when a figure falls under its floor (a count under its record, a mass or a volume more than 5 % under it), and when the suite's record is of other code, of other packages or another Python, short or half written). A figure may grow by its margin; a budget is lowered with `--write` in a commit of its own, and `--write` refuses a figure past a hard limit, and one under its floor unless `--accept-lower` says the saving is meant.

| Feature | Proved in the model | Proved on the hardware | Gap |
|---|---|---|---|
| The skeleton prints from the black ABS on hand | `check_budgets.py`: ABS at 4 walls / 20 % 1732.9 g, ratchet 1767.6 g (+ 2 %), floor 1646.3 g (- 5 %), hard limit 1800 g (90 % of the 2 kg in `hw.ABS_STOCK_G`) | none | 67.1 g (3.7 %) left under the hard limit; supports and rejects are not counted; the 4 walls / 20 % formula is an estimate, not a slicer's figure |
| The organic layer prints from the PETG ordered | `check_budgets.py`: 2044.0 cm3 (2595.9 g solid) with the rear panel, ratchet + 2 %, floor - 5 %, hard limit 3600 g solid (90 % of 4 kg) | none | solid volume, not the slicer's; supports not counted |
| The checks run often enough to be used | `check_budgets.py`: the fast `test_checks.py` gated on six counts, each limited to the larger of + 1 and + 10 % rounded down: frame builds 9 (limit 10), `run_checks` calls 127 (limit 139), cable routings 12 (13), cable evaluations 6 (7), zone_access runs 8 (9), drive_access maps 3 (4); a count under its record fails (the suite did less work). Its wall time (355.4 s recorded, 6 workers) warns at its margin of 0.25. The record must be of the working tree's code (its digest) and of the Python and package versions installed now, and hold the 329 cases of `EXPECTED_CASES` | none | wall time depends on the machine's load; counts do not see a slower single operation; on a small count + 1 is more than 10 % (3 drive_access maps may become 4) |

## Not looked at

Cooling: the direction of each fan is decided, the air flow is not computed. Noise and vibration. Dust.
