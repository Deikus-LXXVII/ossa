# External cables: the board's rear connectors and the card's video outputs

Status: found on 16 Nov 2026 after the owner raised it. Decided the same day: 140 mm side fans moved outwards, case 520 mm wide, card post rebuilt as a frame. Being built as Revision 13 (`docs/plans/b6-frame-v0.md`).

## What the model shows

Both the board's rear connectors and the card's video outputs face the left flank (-X). Measured on the voxel grid of the model (skeleton, hardware, hoses, cables, organic layer), depth along -X to the first obstacle:

- **Board, rear connectors** (board edge X -122, u 148..307, n -4..41): 58 mm, then the left side fan (X -205..-180, u 120..260, n -42..98). The model's `io_zone` keep-out reserves 50 mm for plugs and stops 8 mm short of the fan.
- **Card, video outputs** (bracket at X -124, u 76..127, n 5..115): 3 mm, then `gpu_post`, a solid placeholder block (v -20..-5.5, u 73..146, n up to 108) that covers the whole bracket. Above it (n 110) 52 to 60 mm to the organic layer.
- **No way out.** The left flank is closed by the fan, the ring round it and the layer's threads.

## Can the left fan move? (search over the flank, 10 mm steps, 3 mm margin)

- **Up:** no. The 360's end, the visor arm that holds it and the CPU hoses are there.
- **Outwards:** no. From 6 mm on it meets the CPU hoses, which pass outside the fan.
- **Down by about 110 mm** (fan's lower corner at n -150 or lower, u 90..140): free and clear of both sets of connectors. The fan is then wholly below the board's plane.
- **Forward and down along the board by about 115 mm** (u0 near 0, n0 -20..-60): free and clear of the board's connectors, but 56 mm in front of the card's outputs.
- **The right fan has no mirrored place:** below the board on the right are the PSU's cables, in front are the card's hoses. It can only stand where it stands.

## Owner's direction so far (16 Nov 2026)

- **Card:** rebuild the post so the outputs are open; the gap to the wall should then let the cables bend and leave towards the rear.
- **Board:** see whether the fan can be raised to free the connectors, and raise the other one too for symmetry. The search above says it cannot.

## Ways open

1. **No side fans.** Both flanks become open windows in the organic layer; the left one gives access to the connectors. Symmetric. Main session's judgement, not computed: in an open case the radiators' air leaves through the flanks anyway.
2. **Both fans stay; the connectors go to a panel at the rear** on short extension leads.
3. **Asymmetric:** the right fan stays, the left one goes or drops below the board.

In every case `gpu_post` becomes a frame with an opening for the outputs, and the layer in front of the outputs moves out so that a DisplayPort plug with its bend (about 80 mm) fits and the cables can run to the rear.

## Study: both side fans raised, mirrored (16 Nov 2026)

The owner asked to look at raising the radiators so the fans could go up, then at 120 mm fans. `cad-implementer` ran a study (`cad_b6/study_side_fans.py`, `cad_b6/report_study_side_fans.txt`, pictures `previews/b6_study_fans_*`); the main session looked at the pictures and has not rerun the script.

- **The radiators do not have to move.** The right fan can go up as it is. On the left the only thing in the way is the CPU hoses' run down the flank. Raising the 360 itself is not possible: 68 mm would be needed and the card's hoses have 15 mm spare.
- **Result: a mirrored raised place exists for 140 mm and for 120 mm fans,** lower edge at n 41 (the whole connector aperture open to the side), fans at X -229..-204 and 204..229.
  - **140 mm:** u 96..236, n 41..181. Its front corner touches the front plane (Y -0.1). The right fan moves 3 mm out and the card's hoses are rerouted as well. It stands in front of 41 % of the card's bracket, 80 mm away.
  - **120 mm:** u 114..234, n 41..161. The card's hoses and the right fan's X stay. It stands in front of 17 % of the bracket.
- **What both cost:**
  - The straight in front of each port of the 420 goes from 40 mm to 10 mm. Whether the hose ends accept that is not known.
  - The CPU hoses run inside, under the 360, with 8 to 12 bends in free air at the 35 mm radius, and sit on the 5 mm clearance limit in several places (card, `gpu_post`, visor arm, 360, the fan).
  - Both fan brackets are new parts; both hose guides are redrawn or dropped; the fans' leads are rerouted; `gpu_post` becomes a frame; the organic layer is redrawn on both flanks.
- **Not verified:** hoses are rigid centre lines in the model (stiffness, twist and sag are not modelled); the search is not exhaustive; the 120 mm route was not rerun after the script's last edits.

## Measurement: 140 mm fans kept at their height and moved outwards (16 Nov 2026)

The owner asked to go back to 140 mm fans and stand them further from the case, so that the cables have room behind the fan. Measured by the main session on the model's 1.5 mm grid (skeleton without the fan brackets, hardware, hoses, cables without the fans' own leads; the organic layer left out because it is redrawn). The scripts were scratch files and are not in the repository. Picture: `previews/b6_study_fans_out_f140.png` (fans teal, the plugs' zone pink, no brackets, no layer).

- **The fan can stand outside the CPU hoses.** In the fan's footprint (u 120..260, n -42..98) the hoses lie at X -228..-213. Moving the fan out by 6 to 48 mm meets them; from an inner face at X -235.5 the fan is 6 mm clear of them (4.5 mm at X -234).
- **Proposed place:** left fan X -260..-235, right fan X 235..260, both at today's u and n. Nothing stands in the right fan's way at any shift.
- **Room behind the left fan:** 113 mm from the board's edge instead of 58 mm. The CPU hoses stay where they are and run through that room 91 to 106 mm from the board's edge, in its upper part (n 35..98); they cross the top 6 mm of the connectors' aperture (u 243..287).
- **Way out for the cables:** from the plugs' zone a ball 90 mm across reaches the rear face of the model without leaving the slot between the fan and the board (X -234..-122).
- **Nothing else moves:** the radiators, both pairs of hoses and their guides stay; the 40 mm straight at the 420's ports stays.
- **What it costs:** the case becomes 520 mm wide instead of 458 mm (each fan stands 31 mm beyond the 420's end); both fan brackets are new and reach further; the fans' leads are rerouted; the organic layer is redrawn on both flanks with an opening to the rear on the left.
- **Not checked:** the new brackets and their strength; the leads' length; the view of the connectors (the fan still stands in front of them, so plugs go in by hand from the rear or from below); air flow (the fan is twice as far from the board).

## Next revision (14), agreed with the owner on 16 Nov 2026

- **Move `hose_guide_cpu`.** The owner asked what the clip next to the 420's ports is for, since the fittings already hold the hoses there. It adds little at that place. Agreed: move it along the route to where the CPU hoses pass the left fan (6 mm apart after Revision 13), so that it holds the pair off the fan. It stays a separate part on one screw.
- **Redraw the organic layer's flanks** for the fans' new places, with an opening to the rear on the left for the cables, and keep `io_zone` and `gpu_out_zone` free.
- **The card's shape needs no correction of the supports.** The owner's measurements (`docs/plans/fit-gauges.md`): height as modelled; 51 mm thick near the board; the cooler face slopes towards the long edge away from the board, where the body is about 42.5 mm; a cut corner of 13 x 10 mm at the far end on that same edge. The model's 51 mm box is right where the `gpu_rest` finger and `gpu_post` meet the card and is larger than the card only near the far long edge, which costs nothing. An earlier entry here asked to move the finger by 8.5 mm; that rested on the main session's wrong reading of where the slope is and is withdrawn.
