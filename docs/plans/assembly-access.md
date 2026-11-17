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
| `STUBBY_LEN`, `STUBBY_D` | 45.0, 30.0 | a short cross-head driver, one cylinder above the head |

Tools by head: an M3 socket head takes the straight driver or the L-key. A pan head (6-32, and the 2.5 inch drive's M3) takes the straight driver or the stubby one.

### What is measured for each screw

Everything is measured with booleans on the exact solids, in the fully assembled case: a tool is a solid, and its **blockers** are the solids it intersects by `VOL_EPS` or more (the project's "no intersection" is a volume under 1 mm³). Printed parts are taken drilled (`part.solid`), so a head's corridor passes its own counterbore. Only solids whose box meets the tool's box are tried. Do not use `material_spans` for this: one probe costs seconds on some solids.

- **Insertion.** A cylinder of the head's corridor from just above the seat outward, as long as the screw (length under the head + the head + 2 mm). Its blockers are added to those of every tool: a screw that cannot be offered up cannot be driven.
- **Straight driver.** From the top of the head (seat + washer + head): the head's corridor for `DRIVER_SHAFT_LEN`, then a cylinder `DRIVER_HANDLE_D` across for `DRIVER_HANDLE_LEN`.
- **L-key.** The head's corridor for `LKEY_SHORT`, and the long arm tried every 5° round the axis. The key's blockers for a given state are found per direction; the key works when a run of directions `LKEY_SWING_DEG` wide is free at once. Compute it only for screws the straight driver cannot reach in the assembled case, and try the whole disc first (if nothing meets it, every direction is free).
- **Stubby driver.** One cylinder `STUBBY_D` x `STUBBY_LEN` above the head.
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
2. Among the nodes that may go on, try them in this preference: the printed parts as `build_frame` returns them, then `psu`, `board`, `cpu_aio`, `gpu_aio`, `fan_side_right`, `fan_side_left`, `drive_left_25`, `drive_left_35`, `front_io`, `light_strip`.
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

## Grok's check of the first draft (18 Nov 2026)

`code-analysis` read the draft against `frame_v0.py` and `hardware.py`. What it changed: the rule for class B counted each PSU and 360 screw twice (bore and counterbore); the cross-check by name could not hold (31 rows sum to 147 against 120 screws to judge: 12 organic, 2 placeholder, 13 counted in two rows, and the holes' item strings differ from the rows'); the drives had to be two nodes; `material_spans` is too slow for rays (up to 1.9 s a probe on the hoses), so the method is booleans only; the 2.5 inch drive's pan-head M3 had no tool; the hardware lists now use exact keys. Confirmed as written: the seat of an insert joint, the organic pad's item string, world coordinates of the holes, the stable part order, the three units.
