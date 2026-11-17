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

## The owner's inserts, measured (17 Nov 2026), and Revision 15

The owner measured the heat-set inserts he has: **4.0 mm long, 4.96 mm outer diameter**. Until now the model assumed a pilot of Ø4.0 x 6.7 mm, which is the hole of a 4.6 mm insert 5.7 mm long.

**What follows.**
- The pilot is too small by about 0.4 mm. For an M3 insert of 5.0 mm outer diameter and 4.0 mm length the maker's guideline (CNC Kitchen's dimension sheet, quoted by Grok's research above and not re-opened) is a hole of 4.4 mm and a wall of 1.6 mm. The ladder `C2_insert_ladder` decides the real figure on this printer.
- The pilot's depth stays 6.7 mm. The insert sits in the top 4 mm; the rest is room for the screw's tip, which keeps the screw-length window (enters 3.5 mm at least, stops 0.5 mm off the bottom) as wide as it is. A shallower pilot would leave a window of 1 mm and many joints would have no screw in the owner's kit.
- The thread a screw can use is now 4.0 mm at most, where the rule's minimum is 3.5 mm.
- A shorter insert holds less. In the one test found that compares lengths (MJF PA12, not printed ABS) a 3.6 mm insert held 813 N and a 5.7 mm one 1258 N. The two joints that see about 225 N and 200 N in their worst case keep a margin of about 3.5 against that figure. Not proved for ABS.

### Revision 15: spec for `cad-implementer`

1. `cad_b6/hardware.py`: record the owner's measurement as named constants (insert length 4.0, outer diameter 4.96, with the date and "owner's measurement"); `M3_PILOT_D` becomes 4.4 with its source (maker's guideline for a 5.0 x 4.0 insert, to be confirmed by `C2`); `M3_PILOT_DEPTH` stays 6.7 and its comment says why (above). Remove the word ASSUMPTION from the insert's size where it stood; keep it on the pilot's diameter until `C2` is tried.
2. Rebuild. Every pilot grows by 0.4 mm in diameter, so walls round pilots shrink by 0.2 mm. Where a check fails (the wall round a pilot, the spacing between holes, a pad of the organic layer, a tie bridge, a counterbore's wall), move the hole or thicken the part by the least amount, and list each such place with its numbers. Do not lower a wall rule.
3. The rule that a screw enters the insert by at least 3.5 mm: add that the thread engaged is at most the insert's length, and report for each row of the bill of fasteners the engaged thread. If any joint would engage less than 3.5 mm, stop and report.
4. `cad_b6/fit_gauges.py`: regenerate `C2_insert_ladder` round the new pilot: the pilot row from 4.1 to 4.9 in steps of 0.1 mm with 4.4 marked as the model's, the clearance row unchanged. The plate must be thick enough to take a 4 mm insert with a floor under it. Update `docs/fit-gauges-check-sheet.ru.md` (the C2 row: the new diameters, and that the insert is 4.0 x 4.96 mm).
5. The organic layer's pads carry M3 pilots in the skeleton and a bore in the layer: rerun `organic_frame.py` and its checks; change nothing in the layer unless a pad check fails, and then report before changing.
6. Verify in full (the verify skill): `frame_v0.py`, `test_properties.py`, `parts_manifest.py --expect` with the list of parts you expect to change (every part with a pilot; state the list and confirm nothing else changed), `cables.py`, `fit_gauges.py`, `zone_access.py`, `drive_access.py`, `organic_frame.py`, `test_organic.py`, `test_checks.py` (about 6 minutes now), `check_budgets.py`, `strength.py 7 2`. The skeleton's mass budget must still pass.
7. Report: the list of places that had to move, every check or test that changed and why, the engaged thread per fastener row, the script results with counts. Do not commit.

### Revision 15: corrections after Grok's check of the spec against the code (17 Nov 2026)

Where this list and the spec above disagree, this list holds. Grok built the frame with the pilot at 4.4 mm in a probe: **no wall and no gap falls under a rule.** The tightest places after the change: the fan brackets' ears 2.70 mm (rule 1.6), the lap pilots of the ribs 3.41 mm apart, the card post's window wall 1.90 mm (it does not shrink, the bolts move with the radius).

1. **The source of 4.4 mm.** It is not in the research section above, which leaves it out. It is the row for a 5.0 x 4.0 mm M3 insert in CNC Kitchen's dimension sheet (https://www.cnckitchen.com/s/CNCKitchen_Heat-Set-Insert-Dimensions-and-Design-Guidelines.pdf): hole 4.4 mm, minimum wall 1.6 mm. Read by Grok, not re-opened by the main session. Say so in the constant's comment.
2. **The window if the pilot were shallower.** A pilot only as deep as the insert plus the 0.5 mm gap would be 4.5 mm deep and leave a window of 0.5 mm (3.5 to 4.0), not 1 mm. The conclusion stands: the depth stays 6.7 mm.
3. **Do not teach `screw_fit` the insert's length.** A ceiling of 4.0 mm on the entry would shorten 17 screws and add relief bores to 46 joints. The rule stays as coded (the screw enters the pilot by 3.5 to 6.2 mm). Report the engaged thread as min(entry, 4.0) per row of the bill of fasteners; today it is 3.5 mm at the least (30 joints) and 4.0 mm at the most. The two screws of the front I/O module have no stack; give them a line that says so.
4. **New constants** for the insert's length (4.0) and outer diameter (4.96) in `hardware.py`; the wall 1.6 mm is a design rule and stays. The comment that calls diameter, depth and wall together an assumption is rewritten: the insert's size is measured, the pilot's diameter is the maker's figure until `C2` is tried, the depth is a choice explained in this plan.
5. **`C2_insert_ladder`:** change `C2_PILOT_STEPS` so that the row is 4.1 to 4.9 with 4.4 marked (with the diameter alone it would become 4.2 to 5.0). The plate's thickness does not need to change.
6. **Parts expected to change** (23, every part with a pilot): `beam_front`, `beam_low`, `beam_mid`, `beam_top`, `drive_sled_left`, `fan_bracket_left`, `fan_bracket_right`, `front_io_carrier`, `front_sill`, `gpu_post`, `gpu_rest`, `hose_guide_cpu`, `neck_left`, `neck_right`, `psu_bulkhead`, `rib_A_left`, `rib_A_right`, `rib_B_left`, `rib_B_right`, `skid_front`, `skid_rear`, `visor_arm_left`, `visor_arm_right`. Run `parts_manifest.py --expect` with this list. If one of the other fourteen (the antlers, `hose_guide_gpu`, the eleven tie bridges) differs, say which and why (a neighbour's larger protected ring can move a rounding) before you accept it.
7. **Stale text to bring in step:** the C2 row of `docs/fit-gauges-check-sheet.ru.md`; `docs/plans/fit-gauges.md` where it still describes the old ladder; the fastener table of `docs/printer-and-materials.md` where it names the insert; the deviations text in `frame_v0.py` and the C2 note in `fit_gauges.py` that call the depth an assumption.
8. **Contact flats.** The protected disc round each pilot grows by 0.2 mm in radius. Rerun the contact checks and report any face that loses its flat.

### Revision 15, result and what its review found (17 Nov 2026)

Built by an Opus child, rerun by the main session, reviewed by Grok, committed as `aecfe7a`. The pilot is 4.4 mm x 6.7 mm, 23 parts changed and nothing else, the ladder C2 runs from 4.1 to 4.9 mm, every joint engages 3.5 to 4.0 mm of thread, the suite is 287 of 287.

Two findings of the review are not fixed by that commit:
1. **A wall of 1.28 mm passes check 7.** In `beam_mid` the left end pilot and the clearance hole for `gpu_post`'s high bolt are 1.283 mm apart; the rule is 1.6 mm. Check 7 judges a wall by the volume missing from a 1.6 mm ring round the hole and tolerates 0.5 mm³ (`WALL_EPS`), and the pinch here is a small lens of 0.25 mm³. It was there before this revision (the gap was the same with the 4.0 mm pilot). The next tightest pair of bores is 1.907 mm.
2. **Nothing stops an insert from going too deep.** The hole is 2.7 mm deeper than the insert. An insert on the bottom leaves entry minus 2.7 mm of thread: 0.8 mm in the thirty rib-end joints. The documents now tell the owner to set inserts flush; the model does not help him.

## Revision 15a: a pilot that stops the insert, and walls measured as distances

### Spec for `cad-implementer`

1. **Stepped pilot.** The pilot becomes two coaxial bores: the insert's seat, `M3_PILOT_D` (4.4) wide and as deep as the insert plus a small allowance (`M3_INSERT_LEN` + 0.3 = 4.3 mm), and under it the tip bore, as wide as an M3 clearance hole (`M3_CLEAR_D`, 3.4) down to the present depth of 6.7 mm. The ledge between them, 0.5 mm wide all round, is where the insert stops. The screw-length rule is unchanged: the screw still enters 3.5 to 6.2 mm, its tip in the tip bore. All new numbers are named constants in `hardware.py` with a comment on why.
   - Record the tip bore so that every check that reads a pilot's radius or depth reads the right one at each depth (there is a precedent in the relief bore of kind `M3r`). The wall rule of 1.6 mm applies to the seat; say what applies to the tip bore and why (it holds no insert; it must not break out).
   - The melted plastic the insert displaces has to have room: report the volume of the tip bore against the volume of the interference (the insert's 4.96 mm in a 4.4 mm seat, 4 mm long) and say if it does not fit.
2. **The same in the ladder `C2`:** stepped holes like the model's, so that the owner tries the stop as well as the diameter. The check sheet's row says what to look for: the insert stops flush on the ledge.
3. **Walls as distances.** Add to check 7 the plain distance between a pilot's cutter (seat and tip bore) and every other hole's cutter in the same part, and between a pilot's cutter and the part's outside: the rule is 1.6 mm for the seat. Keep the present volume test; the new test is in addition. A test puts two bores 1.3 mm apart with a lens under 0.5 mm³ and expects the failure.
   - With the stepped pilot the pair in `beam_mid` may already clear 1.6 mm, because the end of the pilot is then the narrower tip bore. Measure it. If any pair is still under the rule, move the hole that is cheaper to move by the least amount (for `gpu_post`, the bolts' v, `GPU_POST_BOLT_V`) and report the numbers before and after.
4. **The engaged-thread test proves the `min()`:** a case in which the entry is smaller than the insert's length (the M3 x 20 joints, entry 3.5) reports the entry, and one in which it is larger reports the insert's length; a version without the `min()` must fail the case.
5. **Verify in full** as in revision 15 (the suite takes about 6 minutes), with `parts_manifest.py --expect` on the 23 parts that have a pilot. Regenerate the reports, the STEP file, the gauge files and the previews. Do not commit.
6. **Report:** the stepped pilot's numbers, the melt volume, the tightest five distances between bores before and after, anything that had to move, every check or test added or changed, the script results.
