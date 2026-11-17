# Feature map: what the case has to do, and what proves it

Written on 17 Nov 2026. One row per thing the owner will do with the case or expect of it. "Proved in the model" means a script fails when it is not so. "Proved on the hardware" means the owner tried a printed gauge or part. A row without proof is a gap, not a promise.

Use it two ways: as the definition of done for a revision (no row may get worse), and as the list of what still has to be proved before printing in ABS.

## Mounting the components

| Feature | Proved in the model | Proved on the hardware | Gap |
|---|---|---|---|
| The board screws to nine standoffs | check 5 (mounts from the solids), check 15 (screws) | gauges `G4a`, `G4b` printed, not tried (PC not apart) | hole pattern not confirmed on the real board |
| The 420 hangs on its twelve fan screws | checks 5, 14, 15; `strength.py` "stiff" | gauge `G1` printed, not tried | pattern and port offsets not confirmed; fan screw length (6-32, about 35 mm) not measured |
| The 360 hangs on its arms | checks 5, 16 | gauge `G2` printed, not tried | the model's least sure numbers (ports taken from ARCTIC's) |
| The PSU screws to the bulkhead and rests on the skids | checks 5, 16 | gauge `G3` printed, not tried | screw length is an assumption |
| The card stands in its slot, held at the bracket and resting at the far end | checks 5, 18, 19; check 16 (the rest's screw heads sit in counterbores deep enough for head and washer) | gauge `G7`: height and hose exits fit | the bracket tab's height is inferred from the PCIe drawing (108.3 mm against the model's 108.0), not measured |
| The CPU block's hoses leave where the model says | hose routes | gauge `G5` fits with a little play; the fittings turn | fitting spacing 23.8 mm not measured |
| The side fans screw to their brackets | checks 5, 11, 17 | gauge `G6` fits | none |
| A 3.5" or a 2.5" drive screws into the left bay | check 13 | none | no drive on hand; the bay is a provision |
| The front I/O module sits in its carrier | check 20; check 22 (the sill's rear wall behind it); `test_checks.py`: a module grown to its whole allowance leaves the sill unchanged and passes every check | none | every dimension of the module is a placeholder |

## Using the case

| Feature | Proved in the model | Proved on the hardware | Gap |
|---|---|---|---|
| A plug goes into each rear connector of the board and its cable leaves to the rear | `zone_access.py`: zone free, a 52 mm bundle gets out | none | the plug's 50 mm depth is an assumption |
| A plug goes into each video output of the card and its cable leaves to the rear | `zone_access.py`: zone free, a 72 mm bundle gets out | none | which part of the bracket carries the outputs is read off a photograph |
| A hand reaches the board's rear connectors | measured once: a 60 mm ball reaches them past the left fan | none | no check yet (revision 14b adds one); a hand is not a ball |
| A drive goes in and out with everything else assembled | `drive_access.py`: least tilt 28° of 30° allowed | none | 2° of margin |
| Every internal cable reaches its socket with its real length | `cables.py` | none | several real lengths are assumptions; the front I/O leads are not measured |
| Both pairs of hoses reach without a bend tighter than 35 mm | hose routes, checks 9 and 10; `test_checks.py`: the CPU clip still passes check 10 with either hose moved 1 mm | none | hoses are rigid lines in the model; no maker states a bend radius; the ARCTIC length is 450 or 500 mm depending on the source |
| Nothing sticks out to catch a passer-by | check 8 (|X| 229, the fans and their brackets 260, front plane) | none | none |
| The power button, the ports and the light line face the user | `front_sill`, check 20 (the cable window lies behind the module's rear face), `cables.py` (the front USB cables pass through the window) | none | placeholder module; the LED strip is not chosen |

## Carrying the load

| Feature | Proved in the model | Proved on the hardware | Gap |
|---|---|---|---|
| The skeleton carries every component with a safety of 3 across the layers | `strength.py`, "stiff" model, worst 2.87 MPa of 6.67 | none | ABS figures are typical values, not this spool's |
| A knock on a fan, a pull on a cable, the card's weight | checks 17, 18, 19 (margins 2.56, 3.29, 2.37) | none | hand calculations, no mesh |
| An insert holds its screw | none | coupon `C2` waits for the inserts | pull-out of the owner's inserts is unknown; two joints see about 225 N and 200 N in their worst case |
| The organic layer survives a 30 N push anywhere | `organic_strength.py` | none | twelve pushes over the allowable until revision 14b |

## Making it

| Feature | Proved in the model | Proved on the hardware | Gap |
|---|---|---|---|
| Every skeleton part fits the bed (290 mm) | report's bounding boxes | none | no check fails on it; read by eye |
| Every joint uses a screw and an insert the owner has | check 15, the bill of fasteners | none | the insert's diameter and length are assumptions |
| A screwdriver reaches every screw | the organic pads only (`driver_blocked`) | none | no check for the skeleton's screws |
| The parts can be put together in some order | none | none | no assembly order is written or checked |
| Printed holes come out the size the model asks | none | coupons `C1` (not printed), `C2` (waits for inserts) | shrinkage of ABS and PETG not measured |
| The organic layer prints | none | none | not split into pieces; the surface is lumpy; PETG settings are untested starting values |

## Not looked at

Cooling: the direction of each fan is decided, the air flow is not computed. Noise and vibration. Dust.
