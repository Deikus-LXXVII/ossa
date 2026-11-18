# Screwdriver reach and the order of assembly

Started on 17 Nov 2026. Two rows of `docs/feature-map.md` have no proof: "A screwdriver reaches every screw" and "The parts can be put together in some order". This plan closes them with one script. No printed part changes in the first step.

## The idea

The two questions are one. A screw that a later part covers is fine if it is driven before that part goes on. So the script finds, for every screw and every tool, the solids that stand in the tool's way in the assembled case, and then looks for an order of installing the parts in which every screw can be driven at the moment its joint is complete. That order is the assembly instruction. If there is none, the case cannot be assembled as drawn, and the script exits with an error.

## Step 1: `cad_b6/assembly_access.py` (a measurement and a derived order)

Standalone, like `zone_access.py`. Builds the frame once (`frame_v0.build_frame`, `hardware.build_hardware`). Changes no part and none of the 22 checks.

### Which screws (corrected after Grok's check of the first draft, 18 Nov 2026)

Holes on the returned parts are in world coordinates, left parts included (`add_mirror`), and the part list is in a fixed order.

- **Class A, insert joints, 90.** Every pilot `Hole` with a `stack`, except the organic layer's pads (`h.item == "organic pad"`). The mouth is `h.point(OVERSHOOT)`, the head's seat is `stack` mm from it along `-d`, the head points along `-d`. Length and washer come from check 15's rows (`check_screws`). The members of the joint are the pilot's part and every name `measured_stack` returns (parts and, for the board, the side fans and the CPU hose guide, hardware).
- **Class B, thread in the hardware, 30.** Clearance holes of kind `M3c` or `6-32c` that lie on the axis of no pilot. A `6-32cb` counterbore is not a screw: it shares its axis with its `6-32c`. These holes carry no item, no stack and a default `washer=True` that means nothing, so each group is described by a table in the script:

| Group | Part | Count | Thread in | Head | Length under the head | Washer |
|---|---|---|---|---|---|---|
| `psu` | `psu_bulkhead` | 4 | `psu` | 6-32 pan, `hw.UNC6_HEAD_D` x `hw.UNC6_HEAD_H` | `hw.PSU_SCREW_LEN` | none |
| `rad360` | `visor_arm_left`, `visor_arm_right` | 4 | `rad360` | the same | `hw.RAD360_SCREW_LEN` | none |
| `rad420` | `antler_left`, `antler_right` | 12 | `rad420` (the core) | the same | the fan's thickness + `ANTLER_T` + 5 mm into the core. No constant holds the stock screw's length: look in `hardware.py` first, and if there is none add `RAD_FAN_SCREW_LEN = 30.0` as an ASSUMPTION (the owner's "about 30 mm under the head", `docs/printer-and-materials.md`) and use it + `ANTLER_T` | none |
| `drive_left`, 3.5 inch | `drive_sled_left` | 6 | the 3.5 inch body | 6-32 pan, from `hw.DRIVE_FORMS` | from `hw.DRIVE_FORMS` (6.35) | none |
| `drive_left`, 2.5 inch | `drive_sled_left` | 4 | the 2.5 inch body | M3 pan 5.7 x 2.5, from `hw.DRIVE_FORMS` | from `hw.DRIVE_FORMS` (5.0) | none |

  The seat of a class B screw is measured on the solids, not assumed: from the face of the hardware that holds the thread, outward along the axis, on a line beside the bore (halfway between the clearance radius and the head's radius), the end of the material the screw clamps. For the PSU, the 360 and the drives that is the counterbore's floor in the printed part (the drives' counterbores are anonymous cuts, so only the solid shows them). For the 420 the run goes on through the fan, and the seat is the fan's outer face. The members are the part and the hardware that holds the thread.
- **Not judged here, but counted.** The two front I/O pilots (`stack is None`, the module is a placeholder): reported as "not judged, placeholder". The twelve organic pads: judged by `organic_frame.driver_blocked`.

**Cross-check against the bill.** The script holds a table with one entry for each of the 31 rows of `frame_v0.FASTENERS`, keyed by the row's `item`. An entry says how the row is judged: class A or class B with a rule that picks its screws (the hole's item, the part's name: the names differ, for example the holes' `"side fan"` against the rows `fan_side_left` and `fan_side_right`), "organic", "placeholder", or "the same screws as row X" (`tie_pilot` is `tie_bridge`'s inserts, `gpu` is `gpu_post`'s screws). The script fails when a row of `FASTENERS` has no entry, when an entry's row is gone, when a row's `count` differs from the number of screws its rule picks, or when a class A or class B screw is picked by no row or by two. A screw the script does not see is a screw nobody checked.

### The tools (new constants in `cad_b6/hardware.py`, every one an ASSUMPTION until the owner names his tools)

| Constant | Value | Meaning |
|---|---|---|
| `TOOL_PLAY` | 0.5 | the corridor of a screw's head, and of the bit that follows it, is the head's diameter plus this (it has to pass the counterbores: 7.8 for an M3 head with its washer, head + 0.8 for the others) |
| `DRIVER_SHAFT_LEN` | 75.0 | a straight driver's shaft, from the top of the head |
| `DRIVER_HANDLE_D`, `DRIVER_HANDLE_LEN` | 30.0, 100.0 | its handle, beyond the shaft |
| `LKEY_SHORT`, `LKEY_LONG`, `LKEY_T` | 20.0, 65.0, 4.0 | a 2.5 mm hex key: the short arm in the screw, the long arm (a bar `LKEY_LONG` x `LKEY_T` x `LKEY_T`) swinging across the axis at the short arm's end |
| `LKEY_SWING_DEG` | 60.0 | the free sector the long arm needs (a hex socket takes the key every 60°) |
| `STUBBY_LEN`, `STUBBY_D`, `STUBBY_BLADE` | 45.0, 30.0, 15.0 | a short cross-head driver, 45 mm in all: a blade as thin as the head's corridor for 15 mm, then a handle 30 mm across |

Tools by head: an M3 socket head takes the straight driver or the L-key. A pan head (6-32, and the 2.5 inch drive's M3) takes the straight driver or the stubby one.

### What is measured for each screw

Everything is measured with booleans on the exact solids, in the fully assembled case: a tool is a solid, and its **blockers** are the solids it intersects by `VOL_EPS` or more (the project's "no intersection" is a volume under 1 mm³). Printed parts are taken drilled (`part.solid`), so a head's corridor passes its own counterbore. Only solids whose box meets the tool's box are tried. Do not use `material_spans` for this: one probe costs seconds on some solids.

- **Insertion.** A cylinder of the head's corridor from just above the seat outward, as long as the screw (length under the head + the head + 2 mm). Its blockers are added to those of every tool: a screw that cannot be offered up cannot be driven.
- **Straight driver.** From the top of the head (seat + washer + head): the head's corridor for `DRIVER_SHAFT_LEN`, then a cylinder `DRIVER_HANDLE_D` across for `DRIVER_HANDLE_LEN`.
- **L-key.** The head's corridor for `LKEY_SHORT`, and the long arm tried every 5° round the axis. The key's blockers for a given state are found per direction; the key works when a run of directions `LKEY_SWING_DEG` wide is free at once. Compute it only for screws the straight driver cannot reach in the assembled case, and try the whole disc first (if nothing meets it, every direction is free).
- **Stubby driver.** From the top of the head: the head's corridor for `STUBBY_BLADE`, then a cylinder `STUBBY_D` across for the rest of `STUBBY_LEN`. (The first draft had one 30 mm cylinder from the top of the head; it can enter no counterbore, so it was blocked by its own part on all 18 counterbored pan heads. Corrected by the main session after the first run, 18 Nov 2026.)
- **Raw figures, whatever the tools:** the free length along the axis of the head's corridor and of a 30 mm corridor, from the top of the head, each with the name of the first thing it meets (the lowest point along the axis of the corridor's intersection with each solid). The owner can then judge with the tool he really has.

Solids are sorted in three kinds, by exact key of `build_hardware()`:

- **hard:** every printed part; `board`, `gpu`, `cpu_block`, `rad360`, `rad420`, `psu`, `fan_side_right`, `fan_side_left`, `front_io`, `dimms`, `rad420_ports`, `rad360_ports`, `light_strip`, `drive_left` (its two bodies separately), `drive_plugs_left`;
- **soft:** `cpu_hoses`, `gpu_hoses`, `atx24`, `eps` (a hose can be pushed aside, a plug goes in last). Soft blockers do not make a screw unreachable; a screw that only soft solids block is listed under "needs a look";
- **not obstacles:** `io_zone`, `gpu_out_zone`.

A key of `build_hardware()` that is in none of the three lists is a failure.

### The order

Nodes are the printed parts and the hardware units. A unit goes in as one piece:

- `cpu_aio`: `cpu_block`, `cpu_hoses`, `rad360`, `rad360_ports` (a closed loop);
- `gpu_aio`: `gpu`, `gpu_hoses`, `rad420`, `rad420_ports` (the card with its cooler);
- `board`: `board`, `dimms`, `atx24`, `eps`;
- `drive_left_25` and `drive_left_35`: the two bodies of `drive_left` are separate nodes (the 2.5 inch drive's screws end up under the 3.5 inch drive, `SLED_ORDER`); `drive_plugs_left` goes with the 3.5 inch one;
- every other hardware solid is its own node.

A screw is **drivable** when every member of its joint is installed, and it is driven at once: blockers only grow as parts go on, so waiting never helps. It is **reachable** in a state if some tool of its head has no hard blocker among the installed solids.

The script searches for an order, depth first:

1. A node may go on next only if every screw that becomes drivable with it is reachable in the new state, and every screw that is not yet drivable still has a tool without a hard blocker in the new state.
2. Among the nodes that may go on, those that share a screw with something installed are tried first (added after the first run, so that fewer parts stand loose). Within each group, this preference: the printed parts as `build_frame` returns them, then `psu`, `board`, `cpu_aio`, `gpu_aio`, `fan_side_right`, `fan_side_left`, `drive_left_25`, `drive_left_35`, `front_io`, `light_strip`.
3. If no node may go on and some remain, go back and try the next choice. Stop after 200 000 states and say so: "no order found within the cap" is a different failure from "every order was tried".
4. A screw all of whose tools are blocked by hard solids of its own joint or of a member's unit can never be driven. It is reported before the search and fails the run.
5. A node that shares no screw with anything installed before it is reported ("stands loose until ..."), not failed. The CPU block and the card have no screw in the model.

Exit 1 on: a cross-check difference, a solid in no list, a screw blocked by its own joint, no order. Printed limits are checks (`REVIEW.md` row 18).

### What the script prints

One line per screw (row of the bill, part, position, head and length, the tools that work in the assembled case, the two raw free lengths with the first obstacle), the counts by class, the order as numbered steps with the screws driven at each step and the tool for each, the screws that only an early step can reach (with what covers them later), the "needs a look" list, the nodes that stand loose, and the run time. It writes the same order to `out/assembly/order.md`.

### What it does not prove

Whether a part can be moved into its place past the others (no path is computed). Whether a hand can hold the part while the first screw goes in. The tools are assumptions. Hoses and plugs are solids that do not bend. The organic layer and the routed cables are not in the case here: they go on last, so a screw may be out of reach once they are on (re-tightening a screw later is not proved).

## Tests: `cad_b6/test_assembly.py`

Fast, on small synthetic solids and on hand-made tables of blockers where the logic allows it, in the style of `test_budgets.py`:

- a block at a known distance in front of a head gives that free length within 0.1 mm and names the block; it blocks the straight driver, and not the L-key when it stands beyond the key's reach;
- a 1 mm wire across a corridor is a blocker;
- a solid outside the corridor is ignored; a head in its own counterbore is not blocked by its part;
- an L-key with 55° of free sector fails, with 65° passes;
- the seat of a class B screw comes out at a counterbore's floor on a synthetic stepped bore;
- two joints that cover each other give "every order was tried" and exit 1;
- a hard blocker in the screw's own joint is a failure before the search; a soft one is a "needs a look";
- a unit's solids arrive together; the 2.5 inch drive goes before the 3.5 inch one;
- the search goes back: a first choice that leads to a dead end is replaced, and the found order is valid;
- an order changed by hand so that a cover precedes its screw is rejected by the same reachability function the search uses;
- on the real model: 90 class A and 30 class B screws, every row of the bill accounted for; a `FASTENERS` row with a changed count, a row removed from the table and a hardware key removed from the lists each make the script fail.

The count of cases is pinned, as in `test_checks.py`.

## After step 1

The main session reads the result. Screws that no order can reach become a geometry revision of their own (a moved bolt, a notch for the driver), specified separately. Then `docs/feature-map.md` gets its two rows, `REVIEW.md` a row if the work showed a new kind of mistake, and the script's run time a budget if it is long enough to matter.

## Result of step 1 (18 Nov 2026)

Run by the implementer and again by the main session, with the stubby driver's blade and the preference for a tied node in place: 160 s, exit 1.

- 90 class A and 30 class B screws; every row of the bill accounted for.
- In the assembled case the straight driver reaches 67 of 120, the L-key 29 of the 41 it was tried on, the stubby 20 of 30. No tool reaches 22; an early step reaches 20 of them (the board's screws under the coolers, beam_top's under the necks, beam_mid's under the fan brackets, the 2.5 inch drive's under the 3.5 inch one, four of the 3.5 inch drive's under the PSU, the carrier's four under beam_front).
- An order exists for everything but two screws (96 states): the ribs and beams first, then the brackets, skids, bulkhead, sled, antlers, necks, arms, card post, guides and tie bridges, the board, the two coolers, the side fans, the drives, the PSU, and the front sill with its carrier and beam_front last. Only `front_sill` stands loose (until its carrier), and `front_io` and `light_strip` have no screw.
- **Two screws can never be driven: #118 and #120, the 360's screws at u 297 on `visor_arm_right` and `visor_arm_left`.** The head comes up from under the bar along n. The arm's own knee (u 284 to 294.5, n 88 to 108, the tab for the second joint bolt) stands 2.5 mm from the screw's axis; the head's radius is 3.35 mm. The head cannot pass the knee to reach its counterbore. `KNEE_U`'s comment says the screw's hole "stays clear of it": the hole does, the head does not. None of checks 1 to 22 looks at what a head passes on its way in.

## Step 2: Revision 16, a channel for the 360's screw through the arm's knee

### What changes

`visor_arm_right` and `visor_arm_left` only (`build_arm_right`, before the mirror). The counterbore of the radiator screw at u = `hw.RAD360_HOLES_U[1]` is carried down through the knee: it starts at the knee's underside (n `KNEE_N0`, 88) and not at the bar's (n `RAD360_INNER_N - ARM_T`, 108). In code: `stepped_bore(hw.bp(v, u, KNEE_N0), hw.N_DIR, hw.RAD360_INNER_N - KNEE_N0)`, a thickness of 34, so that the floor stays `HW_SCREW_FLOOR` (2 mm) under the radiator at n 120. Passing the knee's height (20) as the thickness would put the floor at n 106 and cut through the bar. Its diameter stays the counterbore's (`CLEAR_KINDS["6-32cb"]`, 7.5 mm). In the knee the cut is an open groove 1.25 mm deep into the knee's face at its deepest (the face is 2.5 mm from the axis, the cut's radius is 3.75 mm), over X 169.7 to 175.3. The screw at u 192 keeps its counterbore.

The rule that decides it is geometric and not a list of holes: a radiator screw's counterbore starts at the knee's underside when the knee's face is closer to the screw's axis than the counterbore's radius (2.5 < 3.75 at u 297; u 192 is 102.5 mm away). It stays a recorded `Hole` of kind `6-32cb` (REVIEW.md row 17).

`KNEE_U`'s comment is corrected: the screw's clearance bore stays clear of the knee, its head does not, hence the groove.

### Numbers (measured by Grok on the unrounded right arm, 18 Nov 2026; the main session's first figures were 75 mm³ and 1.85 mm)

- The groove takes 94.4 mm³ more from the knee than today's counterbore does (segment 4.84 mm² over 19.5 mm; today's cutter already takes the top 0.5 mm).
- The joint bolt in the knee is a pilot in the arm, along -X from the face X 180, at u 289.2, n 93.5, 6.7 mm deep. To the groove: 2.700 mm from the insert's zone (rule 1.6) and 1.907 mm from the tip (rule 1.2). The upper joint bolt already stands at the same two distances from today's counterbore.
- The floor under the head stays 2.000 mm (check 16's probe does not enter the knee).
- Checks 5, 7 and 16 measured on the lengthened arm: no failure. Check 7 sees the groove only through the distances to the pilots: a hole's own wall is measured where its axis is inside the part, and the groove's axis is outside the knee.
- The knee's bottom outer corner (u 294.5, n 88) is rounded at 4.5 mm today; the longer hole's ring refuses that rounding and the corner stays sharp. Accepted: it is the groove's mouth. The arm's corner count in the report changes by this one.
- **Strength is not re-proved by the mesh.** `strength.py` meshes each part's blank, before its holes, so it cannot see the groove. By hand: the knee's section across n is 10.5 x 13.5 = 141.8 mm², the groove takes 4.84 mm² of it (3.4 %), on the side away from the joint bolt. `strength.py` is still rerun, for the corner that changed.

### What it must achieve

`assembly_access.py` exits 0. For #118 and #120 the straight driver's shaft passes the groove. Its handle still meets the neck in the assembled case (the axis is 7.5 mm from the neck's face, the handle's radius is 15), so the order will have the arms screwed to the radiator before they are bolted to the necks: the 360 goes on and comes off together with its two arms, by the four joint bolts on the necks' outer faces. That is a design call for the owner (recorded in `docs/plans/b6-frame-v0.md`). If the script finds no such order, that is a result to report, not something to tune.

### Check 23, "a screw can be offered up to its counterbore"

New in `frame_v0.py`, called from `run_checks` like checks 20 to 22, result key `head_way`, failures prefixed `CHECK23`, report line `  23. (доп., ревизия 16)` after check 22's.

For every recorded counterbore (`Hole` of kind `6-32cb` or `M3cb`): a cylinder from the counterbore's mouth (`h.point(OVERSHOOT)`) outward along `-d`, as long as the screw with its head, does not meet the counterbore's own part's solid by `VOL_EPS` or more. (As built after the review, below: a distance from the screw's axis and not a volume.)

- Diameter: for `6-32cb`, `hw.UNC6_HEAD_D + hw.TOOL_PLAY` (7.2, inside the 7.5 counterbore). For `M3cb`, the larger of the head and the washer plus `hw.TOOL_PLAY` (`hw.M3_WASHER_D` + 0.5 = 7.5, inside `M3_CB_D` 7.8).
- Length: the screw's length under the head plus the head's height. For `6-32cb` the length comes from the same table `check_counterbores` uses (by part name: `hw.PSU_SCREW_LEN`, `hw.RAD360_SCREW_LEN`); make it one table for both checks. For `M3cb` it is `screw_fit` of the joint's stack, found by the hole's `item` in a small table (`"gpu_rest"`: `REST_STACK`, `"front_io_carrier"`: `CARRIER_STACK`); an `M3cb` whose item is not in the table is a failure.
- On today's model (measured by Grok on the right arm, the bulkhead, the carrier and `rib_A_right`): 21.6 mm³ at the arm's u 297 counterbore, 0.000 everywhere else. After the change: 0.000 everywhere.

What check 23 does not do, and the report line should not claim: it looks at the screw's own part only and only as far as the screw is long. Whether a tool reaches the head past other parts is `assembly_access.py`. The drive sled's counterbores are anonymous cuts, not `Hole`s, so check 23 does not see them (check 13 measures their head room, and `assembly_access.py` measures their seats on the solid).

### Tests

- `test_checks.py`, two new cases, `EXPECTED_CASES` 322 to 324: an arm whose u 297 counterbore starts at the bar (the old shape) gives `CHECK23`; a block added to `rib_A_right` in front of one of its `M3cb` mouths (outward along -n from n -34) gives `CHECK23`. No existing case is removed or weakened.
- All 22 older checks pass on the new model.
- `parts_manifest.py --expect visor_arm_left visor_arm_right` passes: no other part differs.
- `assembly_access.py` and `test_assembly.py` are rerun; `cables.py`, `zone_access.py`, `strength.py` and the full `test_checks.py` are rerun by the main session.

### Grok's check of this section (18 Nov 2026)

`code-analysis` built the unrounded right arm and measured. Confirmed: the 2.5 mm, the head meeting the knee by 50.7 mm³, that rounding does not open the gap, that checks 5, 7 and 16 pass on the lengthened counterbore, that the notch, the neck's organic pad and the arm-to-neck contact are not touched. Corrected: the volume and the wall figure above, the thickness 34, that `strength.py` cannot see the groove, how check 23 finds a screw's length, and that the second test's block belongs on `rib_A_right`, which holds the rest's counterbores.

### Result of step 2 (18 Nov 2026)

Built by the implementer, rerun by the main session.

- `frame_v0.py`: 23 checks pass. Groove 94.38 mm³ on the unrounded arm; 2.700 and 1.907 mm to the joint bolts' pilots; floors 2.00 mm; check 23 reads 31.46 mm³ on the old arm (the plan's 21.6 was wrong) and 0.00 on all 14 counterbores now. Before the change the knee's corner was rounded at 2 mm on the right arm and already sharp on the left (the plan said 4.5). Check 12 counts 6 corners on each arm where it counted 8: the sliver edge the old counterbore left on the knee's face is gone, and the knee's bottom corner, cut in two by the groove, is no longer counted (it is in the rounding log as sharp).
- `parts_manifest.py --expect visor_arm_left,visor_arm_right`: only the two arms differ. `test_checks.py`: 324 of 324, 354 s. `cables.py`, `zone_access.py`, `check_budgets.py`: pass. `strength.py 7 2`: the judged case's largest wall stress 2.87 MPa of 6.7 (2.85 before; the arm's corner changed, the groove itself is not in the mesh).
- `assembly_access.py`: exit 0, 156 s. All 120 screws have a tool at their step. `test_assembly.py`: 51 of 51 after the reviews' fixes.

### Grok's review of revision 16 (18 Nov 2026) and what was changed

`change-review` built the right arm and measured. Confirmed: check 23's line starts at the mouth and points outward for both kinds of counterbore and for mirrored parts; the old arm in the test is the shape before the revision; no existing case was removed or moved; the floor stays 2.000 mm; the longer cutter meets neither the notch nor the neck's face; the report line claims no more than the check proves.

- **Important, fixed by the main session.** Check 23 as first built compared a volume with `VOL_EPS` (1 mm³): a ridge 0.1 mm into the head's way and under 1.6 mm long would have passed. That is the mistake revision 15a cured in check 7. Check 23 now measures a distance: the screw's axis, from the mouth outward for the screw's length with its head, keeps its own part at least half the head's way (head or washer, plus `hw.TOOL_PLAY`) away. On the old arm it reads 2.50 mm where 3.60 is needed.
- **Nit, fixed.** The two cases accepted any `CHECK23` line for the right hole; they now name the screw and the distance they expect (2.50 of 3.60 on the old arm, 0.00 of 3.75 behind the block).
- **Nit, recorded, not changed.** Check 12 counts a visor arm's edge only when it is longer than 5.5 mm (a filter written for the 5 mm notch step). The two edges at the groove's mouth are 3.2 and 4.7 mm long, so check 12 no longer counts that corner. It stays in the rounding log as sharp, with its reason.

### Bench groups (main session, 18 Nov 2026)

The first order found after the groove was valid and read badly: both rear ribs went on after the 360, because in the case a driver's handle on the arms' u 297 screws meets the neck and the rib. Nobody would build it so; the arms are screwed to the radiator on the bench. The script now knows a bench group (`BENCH`): nodes put together off the case and installed as one. A screw whose whole joint lies inside the group is judged with only the group's solids round it; the group gets its own order by the same search; in the case it stands where its last member stood in the preference. One group so far: `rad360_with_arms` (the two visor arms and `cpu_aio`). On the bench: an arm, the cooler (#117 and #118 with the straight driver), the other arm (#119, #120). In the case it is step 33, held by the four joint bolts on the necks' outer faces. What the model does not see there: the CPU block hangs on its hoses from that group and has to be seated on the board in the same step.

### Grok's two reviews of the script (18 Nov 2026) and what was changed

First review (the script as the implementer left it): the search, the tool solids and the bill found sound; `search` agreed with every permutation `check_order` accepts on 67 small instances. Fixed: the stubby's blade had no test; the L-key's 60° was only pinned between 55° and 65°; `joint_members` raised `KeyError` on a check 15 row that measured nothing.

Second review (the preference for a tied node and the bench groups): both sound as rules. Fixed:

- **Important.** A bench screw's "covered later by" list left out the group's own members that go on after it. The list now holds everything in the tool's way in the whole case that was not there when the screw was driven.
- A screw driven on the bench past a soft solid was missing from "needs a look"; a group member that no screw holds was not printed; the order file repeated its "In the case" heading per group.
- Four test cases did not pin what they claimed (the group's place when its members are apart in the preference, a handle no wider than its blade, two screws without tools, the guard in `joint_members` beside a real part). Rewritten; 51 cases now.
- **`SITS_ON`**, from the review's design remarks: the group could go into the case before the board, because no screw of the model holds the CPU block. A node that sits on another with no screw between them now goes on after it: both coolers after the board, the PSU after its skids, the I/O module after its carrier, the strip after the sill.

What the review says the model still cannot see, and is not changed: `cpu_aio` is one unit, so the block's seating on the socket and the arms' meeting the necks are one step; a screw that the block or the hoses would cover only in their final position fails or passes as if the loop could not be swung aside; no path into the case is computed.

## Grok's check of the first draft (18 Nov 2026)

`code-analysis` read the draft against `frame_v0.py` and `hardware.py`. What it changed: the rule for class B counted each PSU and 360 screw twice (bore and counterbore); the cross-check by name could not hold (31 rows sum to 147 against 120 screws to judge: 12 organic, 2 placeholder, 13 counted in two rows, and the holes' item strings differ from the rows'); the drives had to be two nodes; `material_spans` is too slow for rays (up to 1.9 s a probe on the hoses), so the method is booleans only; the 2.5 inch drive's pan-head M3 had no tool; the hardware lists now use exact keys. Confirmed as written: the seat of an insert joint, the organic pad's item string, world coordinates of the holes, the stable part order, the three units.
