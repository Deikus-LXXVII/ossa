# Modularity of the skeleton: what is reprinted when a number turns out wrong

Status: review by the main session on 16 Nov 2026, asked for by the owner. Two changes proposed for Revision 14; nothing built.

## The owner's aim

A wrong number should cost a small reprint, not a large piece of the load-bearing skeleton.

## Where the skeleton stands (parts table of `cad_b6/report_frame_v0.txt`, revision 12; masses at 4 walls and 20 % infill)

The skeleton is 35 parts. Most places where it meets hardware are already small parts screwed on: the 420's brackets (`antler_*`, 72 g each), the 360's arms (`visor_arm_*`, 15 g) and necks (35 g), the side fan brackets, `gpu_post`, the drive sled, both hose guides, the cable tie bridges. The fans' move in Revision 13 changes only the two brackets, which shows the split at work.

Four places remain where a hardware dimension lives inside a large part:

| Large part | Mass | Hardware feature inside it | How sure the number is | Proposal |
|---|---|---|---|---|
| `front_sill` | 205 g, the largest part | pocket and two screws for the front I/O module | placeholder: the module is not measured | make the module's seat a separate carrier plate |
| `rib_A_right` | 116 g | `gpu_rest`, the card's right-hand rest | confirmed by the owner's measurements, about 2 mm | separate part (decided, see `external-cables.md`) |
| `beam_low`, `beam_mid`, `beam_top` | 55 to 76 g each | nine standoffs of the board | ATX standard and the board's scan; gauges `G4a`, `G4b` exist | keep; print the beams after the gauges were tried on the board |
| `psu_bulkhead` | 107 g | four PSU screws, the socket's window | ATX standard; gauge `G3` exists | keep; print after the gauge was tried on the PSU |

## Why not split further

- **Each split is a joint:** two more screws and inserts, a tolerance added to the chain, and a little stiffness lost. The ribs carry the radiators; `strength.py` passes with the ribs as they are.
- **The ribs and beams hold no hardware number of their own** apart from the rows above. What can go wrong in them is the fit of part to part and ABS shrinkage, and that is caught before any large print by the coupons `C1` and `C2` and by the trial print of every part in white PLA (`docs/printer-and-materials.md`).

## Rule for later revisions

A feature whose dimension comes from hardware and has not been proved by a gauge or a measurement does not live in a part heavier than about 80 g. It goes into a small part screwed to the skeleton.

## Proposed for Revision 14

1. `gpu_rest` becomes a part of its own on `rib_A_right` (already decided).
2. The front I/O module's seat becomes a carrier plate screwed into `front_sill`; the sill keeps an opening with room to spare around the module.
3. Order of printing in ABS: small hardware-facing parts first, the ribs, beams, sill and bulkhead last, each only after its gauge or its PLA trial fitted.
