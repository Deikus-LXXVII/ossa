# Fasteners: everything on M3 with captive nuts (Revision 12, planned)

Status: decided in the main session on 16 Nov 2026, not built. It starts after Revision 11 (the 420's bracket), because both change `cad_b6/frame_v0.py`.

## Why

The skeleton is drawn for ruthex heat-set inserts: about 58 M4 screws into 43 M4 and 20 short M4 inserts, and 34 M3 inserts for the board, the cable tie bridges and the organic layer. The owner has M3 socket head cap screws from 4 to 40 mm, about 700 M3 nuts, washers, at most 20 M3 inserts and no M4 screws (`docs/printer-and-materials.md`, "Fasteners on hand").

Three ways were weighed:

| Way | What it costs | Verdict |
|---|---|---|
| Buy M4 screws and all the inserts | a purchase, and about 110 inserts to melt in | the model stays as it is |
| M3 screws into M3 inserts | still a purchase of inserts; an M3 insert holds less than an M4 one | no gain |
| M3 screws into captive M3 nuts | a revision of every joint | chosen |

A steel nut in a pocket holds better in ABS than an insert, can be taken out and put back, and needs no soldering iron. The screws are not the weak part of any joint: the largest wall stress `strength.py` finds is in the plastic.

## Rules for the revision

- **One thread for the skeleton's own joints: M3.** Screw lengths only from the owner's table. The count of each length stays inside the kit with a fifth to spare, and the model checks that.
- **Captive nut:** a hex pocket for a 5.5 mm across-flats, 2.4 mm thick nut, with a slot that lets the nut slide in from a face that is reachable when the parts are assembled and that prints without support. The screw's hole runs on past the nut so that a screw never bottoms.
- **Heat-set inserts only under the board.** The owner has 20 M3 inserts at most. The nine board standoffs take them: a standoff is 6.35 mm tall and the screw comes from above into a blind boss, which is where a nut pocket is worst and an insert is best. That leaves eleven spare for ones that go in badly. Everything else (the cable tie bridges, the organic layer's pads, the drive sled, every joint of the skeleton) gets a nut.
- **Heads:** a washer under the head, or a counterbore where the head has to sit below the face. Sinking the head is also how a joint is brought to a length that is in the kit: the 26 joints through the 16 mm ribs go to M3 x 20 that way.
- **Screws that come with the hardware stay as they are:** 6-32 for the PSU, the radiators and a 3.5 inch drive, M3 for a 2.5 inch drive and the board. Where a printed wall is thicker than the stock screw allows (the 6 mm bulkhead under the PSU's screws), the wall gets a counterbore.
- **Side fans:** M3 x 35 through the 25 mm fan with a nut behind the bracket.
- Every existing check on holes, walls and fastener counts is kept and moved to the new hole kinds; none is dropped. `strength.py` is rerun, since nut slots take material out of the members' ends.

## Not covered by the owner's kits

- Twelve 6-32 screws about 35 mm long for the 420's fans, once the stock screw is measured (Revision 11).
- Anything the front I/O module needs, once it is measured.

## Update, 16 Nov 2026: the owner can order 100 more M3 inserts

With 20 on hand and 100 ordered there are 120 M3 inserts. The model needs about 97 (58 skeleton joints that are M4 or short M4 today, 9 under the board, 11 cable tie points, 12 pads of the organic layer, 2 for the drive sled, 2 for the front I/O, 3 to 5 for the side fans if they do not get a through screw and a nut).

Recommendation, main session: **order them, and keep inserts everywhere instead of nuts.** It is not strictly needed, nuts would work. The reasons to prefer inserts once there are enough of them:

- **The joints stay as they are drawn.** An insert pilot is a blind hole, as now; only its diameter and depth change from M4 to M3. A nut needs a pocket and a slot at every joint, which is a new shape at about 90 places, takes material out of the members' ends and has to be reachable and printable.
- **The owner's lengths fit without sinking any head.** With an M3 pilot 6.7 mm deep the stacks measured on the model give: 16 mm (26 joints) M3 x 20; 20 mm M3 x 25; 34 mm M3 x 40; 12 mm M3 x 16 or 18; 10 mm M3 x 14 or 16; 8 mm M3 x 12 or 14.
- **Assembly:** nothing to hold in place while a screw is started.

What it needs from the owner: the insert's outer diameter and length (of the ones on hand and of the ones ordered, best the same kind), because the pilot hole is sized to the insert. The model's M3 pilot today is 4.0 mm wide and 6.7 mm deep, which is ruthex's figure for its M3 x 5.7 insert.

If the owner does not order, the rules above (captive nuts, inserts only under the board) stand.

## Decided, 16 Nov 2026: M3 inserts everywhere

The owner orders 200 M3 inserts. Revision 12 is therefore the small one: every M4 and short M4 insert pilot becomes an M3 pilot, every M4 clearance hole an M3 one, the screw lengths come from the owner's table, and the model checks the count of each length and of the inserts against the stock. The captive-nut rules above are not used.

Open until the owner gives the insert's outer diameter and length: the pilot's diameter and depth.

**The 420's fan screws.** The owner's fan screws are about 30 mm under the head. With the 3 mm plate of Revision 11 the screws have to be about 33 mm; the nearest common length is 35 mm (6-32). Before ordering, the owner checks how deep a screw can go into the radiator's thread: a 35 mm screw goes 5 mm into it behind a 27 mm fan and the plate.

## Revision 12: spec for `cad-implementer` (M3 inserts everywhere)

**Goal.** Every screw that joins printed parts is an M3 socket head cap screw from the owner's kits into an M3 heat-set insert. No M4 anywhere. The screws that come with the hardware stay.

**Data, in `hardware.py` only.**

- The owner's stock, with its source (`docs/printer-and-materials.md`): the count of each M3 length from 4 to 40 mm, washers, and 220 M3 inserts.
- The M3 insert's pilot stays 4.0 mm wide and 6.7 mm deep with a 1.6 mm wall, marked as an assumption until the owner gives the insert's outer diameter and length. It is one constant; nothing else may repeat it.
- An M3 screw's clearance hole gets its own kind (3.4 mm). The 4.0 mm kind stays for 6-32 hardware screws. Today one kind serves both.
- Head 5.5 mm across and 3.0 mm high; washer 7 mm across and 0.5 mm thick.

**Joints.**

- Each pilot stays in the part it is in and each clearance hole in the part it is in. The M4 and short M4 pilots become M3 pilots; the M4 clearance holes become M3 clearance holes.
- A washer lies under every head that bears on printed plastic.
- **Length rule.** A screw goes at least 3.5 mm into its insert and stops at least 0.5 mm short of the bottom of the hole. Where no length in the kit does that, first deepen the blind hole under the insert with a relief bore of clearance diameter (the insert is open at the bottom), and only if that is not possible sink the head. Say which joints needed which.
- **Counts.** No more than four fifths of the stock of any length, and no more than four fifths of the inserts. The frame's report gets a bill of fasteners: length, where, how many, how many the owner has.
- The wall rules, the hole checks and the fastener counts move to the new kinds. No check is dropped.

**Particular places.**

- **Side fans:** M3 x 30 through the 25 mm fan into an insert in the bracket.
- **Cable tie bridges:** M3 x 8. The report says M3 x 10 today, which is 0.3 mm longer than foot plus hole.
- **Organic layer's pads:** M3 x 10. **Board:** M3 x 6. **Drive sled's flange:** through the 6 mm bulkhead.
- **PSU:** its own 6-32 screws are about 6 mm long and the bulkhead is 6 mm thick. Counterbore the bulkhead from behind so that 2.0 mm is left under each head.
- **360 radiator on the visor arms:** the same idea if the arm is thicker under the screw than a stock radiator screw allows. The stock screw's length is not known; mark the number as an assumption and put it in the report's open items.

**Fit gauges.** `C2_insert_ladder` becomes M3 only: a row of pilot diameters from 3.8 to 4.6 mm in steps of 0.1 at the pilot's depth, and a row of clearance holes from 3.2 to 3.8 mm. ABS.

**The organic layer's material, in the same pass.** `organic_frame.py`, `organic_strength.py`, `shell_concepts.py` and the frame report's material paragraph still say PLA. The layer is PETG with ABS as the fallback: density 1.27 g/cm3, and for strength the ABS figures `strength.py` uses (E 2000 MPa, 20 MPa across the layers), safety 2 as now, so the allowable is 10 MPa. Names that say PLA become names that say what the thing is (the gap to the card and the PSU, the layer's density). No member of the layer moves. `organic_strength.py` is not run here; the main session runs it on the gaming PC.

**Done means:** `frame_v0.py`, `test_checks.py`, `cables.py -norender`, `organic_frame.py`, `drive_access.py`, `fit_gauges.py` pass; `strength.py 7 2` is rerun (smaller holes, new counterbores) and reported; `render_full.py` rerun. Nothing committed.

## Pull-out strength of M3 heat-set inserts (Grok `web-research`, 17 Nov 2026; not re-opened by the main session)

Asked because Revision 13 leaves two joints that load one insert each in tension in the worst case: about 225 N (a bolt of `gpu_post` under a 20 N pull on a cable) and about 150 N (a rib bolt of a fan bracket under a 20 N knock). Both are rare, short loads.

- **PETG, M3 heat-set insert (Ruthex), axial pull-out:** 119 kg, about 1170 N, insert ripped out; 3 samples, 4 perimeters, 100 % infill (CNC Kitchen, hobbyist controlled test, 2020).
- **PLA, M3:** 1400 to 1775 N for knurled inserts in a tight hole; a cheap insert with straight vertical knurls only 382 N (CNC Kitchen, 2019 and 2026).
- **ABS:** no test of a short M3 heat-set insert in printed ABS was found.
- **Length matters:** in MJF PA12 a long M3 insert (5.7 mm deep) held 1258 N, a short one (3.6 mm) 813 N (Sculpteo). Working load recommended there: ultimate divided by 3 to 5 for structural use.
- **Hole matters:** strength falls steeply once the hole is above a true 4.0 to 4.1 mm; too few walls or too little infill round the hole makes the plastic fail first.
- **Heat and time:** no figure for sustained tension or for 50 to 60 °C on an insert was found. Printed coupons keep about 78 % (ABS) and 70 % (PETG) of their tensile strength at 60 °C.

**Reading (main session).** Against the PETG figure the two loads have margins of about 5 and 8; against the cheap straight-knurl insert only 1.7 and 2.5. The owner's inserts are not identified yet, so the margin is not known. What follows for the model: the pilot must not be oversize (the ladder `C2_insert_ladder` decides it), and the wall round an insert in tension should be solid (walls and infill in the slicer), not sparse. No geometry changes.
