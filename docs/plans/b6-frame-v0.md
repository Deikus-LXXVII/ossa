# B6 «Шатёр»: hardware model + structural skeleton v0

Status: in progress (14 Nov 2026). Owner approved the layout; buttons/ports and cables are deliberately out of scope until he has seen the first sketches.

## Goal

Replace the B5 block-out with the approved B6 arrangement and build a first **structural skeleton** in which every component is actually held by a named part with real fasteners. This is a sketch of load paths and mounts, not final styling. v1's failure was a silhouette that held nothing; v0 must be the opposite.

## Files to create

- `cad_b6/hardware.py` — single source of truth: dimensions, placement, mounting-interface coordinates, `build_hardware()`.
- `cad_b6/frame_v0.py` — parts, checks (asserts), report, previews, STEP export. Imports everything about hardware from `hardware.py`; no duplicated numbers.
- Outputs: `cad_b6/report_frame_v0.txt`, `cad_b6/b6_frame_v0.step`, `previews/b6_frame_v0.png` (4 views with hardware), `previews/b6_frame_v0_bare.png` (frame only, same 4 views), `previews/b6_frame_v0_exploded.png`.

Do not modify `cad_b5/`, `history/`, `HANDOFF.md`. Reuse ideas from `cad_b5/frame_v1.py` (capsule/box helpers, `intersection_volume`, tessellation, matplotlib renderer, mass estimate) by copying what is needed into `cad_b6/`; read the "Полезные уроки по геометрии" list in `HANDOFF.md` first. Run with `.venv/bin/python cad_b6/frame_v0.py` from the repo root.

## Coordinates

World, mm: X right (seen from the front), Y depth (front = 0, grows backwards), Z up. Hardware zero Z = 0; **desk plane Z = −15**.

Board space `(v, u, n)`: v from the rear-I/O edge along the 244 side, u from the bottom edge along the 305 side (towards the CPU), n out of the component face. Board tilted 45° about X:

```
C = cos 45°
bp(v, u, n) = (-122 + v,  60 + (u - n)·C,  30 + (u + n)·C)
```

A box given "in board space" is built axis-aligned in (v, u, n), rotated +45° about the X axis through the origin, then translated by (−122, 60, 30) — same as `Option.bbox` in `layout_b6_options.py`.

## Hardware (all boxes; `bs` = board space, otherwise world AABB x0,x1,y0,y1,z0,z1)

| Name | Box |
|---|---|
| board | bs v 0..244, u 0..305, n −2..0 |
| gpu | bs v −2..278, u 86..137, n 0..150 |
| cpu_block | bs v 49.5..140.5, u 190.75..299.25, n 0..75 |
| rad360 (GPU, "visor") | bs v −75..319, u 184..305, n 90..145. Core n 90..120, fans n 120..145 |
| rad420 (CPU) | world −229..229, 287..352, 246..384. Fans Y 287..314, core Y 314..352 |
| psu | world −75..75, 165..375, 0..86. Fan face up (Z = 86), IEC/screw face at Y = 375, modular face at Y = 165 |
| fans_front (2×140×25) | world −140..140, 0..25, 12..152 (two fans, centres X = ±70) |

Mounting interfaces (put in `hardware.py`, each marked `# PLACEHOLDER` where noted — exact values are being researched and will be swapped in, so nothing else may hard-code them):

- `ATX_HOLES` (v, u): PLACEHOLDER 3×3 grid, v ∈ {10.16, 165.1, 237.49}, u ∈ {16.5, 139.9, 294.84}. Standoff: board underside n = −2, tray surface n = −8.5, M3 heat-set insert.
- rad420 rear-face threaded holes (Y = 352, 6-32): X ∈ {±62.25, ±77.75, ±202.25}, Z ∈ {252.75, 377.25}.
- rad360 inner-face threaded holes (n = 90): world X ∈ {±52.5, ±67.5, ±172.5}, u ∈ {192, 297}.
- front fan holes (140 mm fans, 124.5 pitch): X ∈ {±7.75, ±132.25}, Z ∈ {19.75, 144.25}.
- `PSU_HOLES` on the Y = 375 face (x, z): PLACEHOLDER (−69, 6), (69, 6), (−69, 70), (45, 80).
- `GPU_BRACKET_TAB_N = 108` PLACEHOLDER (n of the surface the card bracket's tab screws onto).
- Heat-set insert pilot holes: M4 Ø5.6 × 9 deep, M3 Ø4.0 × 6 deep (PLACEHOLDER). Clearance holes: M4 Ø4.5, 6-32/M3 Ø4.0.

## Parts

Everything ≤ 290 mm in each world axis. Members ≥ 5 mm thick. Side ribs are **flat plates extruded along X** (print flat on the side face), built as unions of 2D shapes in the YZ plane. `capsule2d(p, q, w)` = stadium of width w around segment p→q. Ribs are 16 thick: right rib X 142..158, left rib X −158..−142 (mirror). Coordinates below are (Y, Z).

### rib_A_left / rib_A_right (front + diagonal)
Union of:
- foot pad: capsule (8, −5)→(40, −5), w 20
- horn (fan upright): capsule (33, 0)→(33, 146), w 14
- diagonal under the board: capsule bp(u=−10, n=−20)→bp(u=280, n=−20), w 28 — i.e. (67.1, 8.8)→(272.1, 213.8)
- mid leg: capsule (195, 136)→(195, −3), w 22; its foot pad: capsule (188, −5)→(212, −5), w 20
- **right rib only** — `gpu_rest` finger: capsule bp(u=78, n=−10)→bp(u=78, n=104), w 16, i.e. (122.2, 78.1)→(41.6, 158.7). Its upper face is the plane u = 86 and supports the free end of the card (X 142..156). This is the deliberate asymmetry of the right rib.

### rib_B_left / rib_B_right (rear post)
Union of:
- runner: capsule (200, −5)→(372, −5), w 20
- post: rectangle Y 300..352, Z −5..243 (flat top = saddle for the 420, 3 mm below the radiator for a rubber pad)
- nose: capsule (326, 226)→(266, 212), w 28
- tail post (PSU bulkhead upright): capsule (373, −5)→(373, 88), w 18

### Lap joints rib_A ↔ rib_B (per side)
Where A and B overlap in YZ they must not intersect: inside the zone boxes below A keeps only the **inner** half-thickness (|X| 142..150) and B only the **outer** half (|X| 150..158).
- top zone: Y 250..300, Z 190..245; 2×M4 along X at (262, 205) and (276, 219)
- bottom zone: Y 185..220, Z −16..10; 1×M4 along X at (202, −5)
Bolt: clearance Ø4.5 through the outer half, insert pilot Ø5.6 in the inner half. Verify that each bolt position lies inside both outlines; nudge if not and say so in the report.

### Cross members (between rib inner faces, X −142..142, single 284 mm pieces)
Each end: 2×M4 through the rib (clearance Ø4.5 in the rib) into insert pilots Ø5.6 × 9 in the member's end face. Choose bolt positions inside both the rib outline and the member's section; report them.

| Part | Geometry | Holds |
|---|---|---|
| beam_front | world box Y 0..40, Z −10..10 plus fence Y 25..31, Z 10..28 (X ±140) with 4 holes Ø4.5 along Y at the lower fan holes | fans (lower row), ties the front feet |
| fan_rail_top | world box Y 25..31, Z 135..152, 4 holes Ø4.5 along Y at the upper fan holes; ends bolt into the horns | fans (upper row) |
| beam_low / beam_mid / beam_top | bs box, u = row ± 10 for each of the three ATX rows, n −28.5..−8.5. On each: standoff bosses Ø10 from n −8.5 to −2 at that row's `ATX_HOLES`, M3 insert pilot Ø4.0 × 6 along n | board (9 standoffs) |
| skid_front | world Y 185..205, Z −10..0 | PSU rests on it |
| skid_rear | world Y 325..345, Z −10..0 | PSU rests on it |
| psu_bulkhead | world plate Y 375..381, Z −15..92, with window X −63..63, Z 12..74; holes Ø4.0 along Y at `PSU_HOLES`; ends bolt into the tail posts (2×M4 each side) | PSU (4 screws), ties the rear |

beam_top's ends land in the top lap zone; that is fine, its bolts go through both lap halves.

### antler_left / antler_right (420 bracket)
Plate 10 thick, Y 352..362 (touches the radiator's rear face and the post's rear face). In XZ, right side (mirror for left): bar X 68..212 × Z 243..263; finger X 193..212 × Z 263..386; tongue X 142..158 × Z 200..243. Holes Ø4.0 along Y at (77.75, 252.75), (202.25, 252.75), (202.25, 377.25). Tongue: 2×M4 along Y into insert pilots in the post's rear face at Z 210 and 232.

### neck_left / neck_right + visor_arm_left / visor_arm_right (360 hinge)
The 360 hangs from a hinge along its upper edge so it can swing up for access to RAM and the CPU block.
- Pivot axis along X through bp(u=335, n=83) = (238.2, 325.6). M5: Ø5.5 through both parts.
- visor_arm: plate X 166.5..178.5 (centred on the ±172.5 hole column). In board space: bar u 186..305, n 76..90 (top face n = 90 touches the radiator), continuing as capsule (u 305, n 83)→(u 335, n 83), w 14, with a Ø20 disc at the pivot. Holes Ø4.0 along n at u = 192 and u = 297.
- neck: plate X 180..192, in YZ: capsule (324, 216)→(266, 230), w 24; capsule (266, 230)→(238.2, 325.6), w 20; Ø24 disc at the pivot. Plus spacer pad: world box X 158..180, Y 300..346, Z 200..236, touching the post's outer face; 2×M4 along X into the post.
- Mirror both for the left side.
- No stop/latch yet — list it as an open item.

### gpu_post (bracket end of the card, left side only)
PLACEHOLDER geometry until the bracket standard is confirmed: bs box v −20..−6, u 84..150, n −8.5..`GPU_BRACKET_TAB_N`; it stands on beam_mid's top face (n = −8.5) and is bolted to it with 2×M4 along n. If it collides with beam_mid's standoff bosses, shift the post in v (more negative), not the bosses.

## Checks (asserts; the script must fail loudly)

1. hardware × hardware: intersection volume 0 for every pair.
2. part × hardware: intersection volume < 1 mm³ for every pair. Touching faces are fine. Report the minimum distance for every pair closer than 5 mm, and list the intended zero-gap contacts separately.
3. **part × part: intersection volume < 1 mm³ for every pair** (v1 had none of this).
4. every part ≤ 290 mm in X, Y, Z (world AABB).
5. every hardware item has its holder parts and fastener count listed in the report (board 9, rad420 6, rad360 4, psu 4, fans 8, gpu: post + rest).
6. lowest point of every part ≥ −15; only foot pads/runners/bulkhead may touch −15.

Report (Russian, plain text): parts table (AABB, volume, mass at 100 % and at 4 walls/20 % infill with the v1 formula), fastener list, contacts, minimum clearances, envelope with and without hardware, total mass.

## Previews

Reuse the v1 matplotlib renderer. Frame in mid-grey (so the form is readable, not near-black), hardware translucent in the colours of `layout_b6_options.py`. Views: iso front-left, iso rear-right, front, left side.

## Known open items (not for this pass)

- exact ATX / PSU / bracket coordinates (research running, placeholders above);
- visor stop and latch; tube and cable routing; buttons and ports; organic skin over the board;
- STL export and watertightness, print orientation, shrinkage compensation.

## Revision 1 — real interface coordinates (14 Nov 2026)

Source: ATX 2.03/2.2 figures, ATX12V Design Guide v2.0 Fig. 8, PCIe CEM, ruthex RX datasheet (research report, medium–high confidence; not yet measured on the owner's parts). Same (v, u) convention as above.

### hardware.py

- `ATX_HOLES` (v, u), no longer a placeholder: A (10.16, 16.51), C (10.16, 140.97), F (33.02, 298.45), G (165.10, 16.51), H (165.10, 140.97), J (165.10, 298.45), K (237.49, 16.51), L (237.49, 140.97), M (237.49, 298.45). Board hole Ø3.96. Rows are u = 16.51, 140.97, 298.45. Note F sits at v = 33.02, not on the rear column.
- Standoff height 6.35 (tray surface n = −8.35, board underside n = −2).
- `PSU_HOLES`: rear face 150 × 86, holes from the lower-left corner as seen from behind with the PSU upright: (6, 80), (144, 80), (6, 16), (120, 6), thread 6-32. Which way up the Seasonic sits with its fan facing up is unconfirmed, so the bulkhead gets the pattern and its vertical mirror (z → 86 − z): 8 holes. Seen from behind, the viewer's right is world −X, so world x = 75 − x_hole, z = y_hole. Mark the orientation `# TO CONFIRM ON THE PART`.
- `SLOT_U` = [22.48, 42.80, 63.12, 83.44, 103.76, 124.08, 144.40] (slot 1..7 centrelines, pitch 20.32). Which position PCI_E1 occupies on this board is unknown, so the gpu box stays as it is and stays `# PLACEHOLDER`, as does `GPU_BRACKET_TAB_N`.
- Inserts (ruthex RX): `M3` pilot Ø4.0, depth 6.7, min wall 1.6; `M4` pilot Ø5.6, depth 9.1, min wall 2.1; `M4S` (short, RX-M4Sx4.0) pilot Ø5.6, depth 5.0, min wall 2.1.
- New keep-out solid `io_zone`: bs v −50..0, u 148.49..307.24, n −3.81..40.64 (rear I/O aperture plus 50 mm for plugs and cable bend). It is part of `build_hardware()` so checks 1 and 2 cover it, but it is drawn at low opacity and excluded from the envelope and from "holders" check 5.

### frame_v0.py

- Board beams follow the three real rows. Boss for hole F at v = 33.02.
- beam_mid: widen to u = row ± 15 so the end pilots and the gpu_post bolts keep ≥ 2.1 mm wall.
- beam_top now spans u 288.45..308.45, which is past the end of rib_A's diagonal. Move its end bolts into rib_B's nose (reshape the nose locally if needed) so each has ≥ 2.1 mm wall; keep rib_A ≤ 290 mm. beam_top must stay clear of rad420 (expect about 4 mm).
- Lap joints: use `M4S` inserts (depth 5.0) in the 8 mm halves. Thin plates (fan_rail_top, psu_bulkhead): keep the end bosses, use `M4` or `M4S` whichever keeps the wall.
- gpu_post: u 84..146 so it stays out of `io_zone`.
- Check 7: raise the minimum wall between holes, and between a hole and the part's outer surface, to the insert's min wall (2.1 mm for M4/M4S pilots, 1.6 mm for M3). Report every hole that fails rather than loosening the limit.
- Remove `# PLACEHOLDER` only from values this revision replaces.

## Revision 2 — positions measured on the real board and parts list (14 Nov 2026)

Evidence: `refs/board_scan_overlay.png` is a straight-on scan of the MAG Z890 Tomahawk WiFi (ixbt review) with the ATX hole table, the seven slot centrelines and the socket centre drawn on it at the PCB-outline scale (5.76 px/mm). All nine ATX holes land on the board's holes, so the hole table and the scale are confirmed on this board. Read-off accuracy is about ±3 mm.

### hardware.py
- **Socket centre (v, u) = (134, 217)**, not (95, 245). `cpu_block` becomes bs v 79.75..188.25, u 162.75..271.25, n 0..75: a 108.5 × 108.5 envelope, because which way the ARCTIC block's 108.5 mm side lies is not confirmed. Drop the placeholder mark on the centre, keep a note on the orientation.
- **PCI_E1 is ATX slot 6, centreline u = 124.08.** The card's PCB sits on the centreline and its cooler lies towards smaller u. `gpu` becomes bs v −2..278, u 75.6..126.6, n 0..150 (51 thick, 2.5 mm allowed on the back side). `GPU_SLOT_U = 124.08`. Drop the placeholder mark on the slot; `GPU_BRACKET_TAB_N` stays a placeholder.
- **rad420 stack is 68 mm**, per the ARCTIC spec sheet (38 core + 27 fan + hardware): world Y 287..355, fans Y 287..314, core to Y 355. The rear-face hole plane moves to Y = 355.
- Add reference boxes, not checked as components but included in checks 1–2 as keep-outs like `io_zone`: `dimms` bs v 183..221, u 158..295, n 0..45; `atx24` bs v 226..244, u 190..246, n 0..40 (connector plus plug); `eps` bs v 178..230, u 290..305, n 0..40. These are read off the scan, ±5 mm.
- PSU is the Seasonic PRIME TX-1600 **Noctua Edition**: same 210 × 150 × 86, 120 mm fan. Update the comment only.

### frame_v0.py
- Everything that follows the card moves with it: `gpu_rest` finger (its support plane is the card's lower face, now u = 75.6), `gpu_post` (span it under the card's bracket end, u about 73..146 minus the io_zone limit, standing on beam_mid as before).
- Everything that follows the 420's rear face moves 3 mm back: antlers Y 355..365, post Y 300..355 so the saddle still spans the radiator and the antler tongue still meets the post's rear face.
- Re-check fan_rail_top, the horns and the finger against the card's new position, and the visor arms and necks against `dimms`, `eps` and `cpu_block`.
- Keep all checks as they are. New keep-outs follow the `io_zone` rule: in checks 1–2, out of the envelope and of the holders check.

### layout_b6_options.py
- Update the shared constants so row E's pump margins stay true: `CPU_V, CPU_U = 134, 217`; block 108.5 × 108.5; card u 75.6..126.6 (`GPU_SLOT_U = 126.6` in that script's convention, where the constant is the card's upper face). Regenerate `previews/layout_b6_options.png` and report row E.

## Revision 3 — make the checks look at the solids (14 Nov 2026)

Source: independent review by Grok (seven findings, each confirmed by running a probe) and my spot-check of the cited lines. The current geometry is clean; the problem is that several checks would still pass if it were not. No part moves in this revision.

### Fix the checks
1. **A pilot or clearance hole must actually be empty.** For every recorded hole (insert pilots and clearance holes), the bore volume must not intersect the part: `inter_vol(part, bore cylinder)` below 0.5 mm³. Keep the existing ring test for the wall. An undrilled boss must fail.
2. **A failed boolean or distance is a failure, not a pass.** `inter_vol` and `a_b_overlap` must not swallow exceptions. Let the error propagate, or record a check failure naming the pair. A null result from `intersect` on two shapes whose bounding boxes overlap by more than the tolerance is to be confirmed with `distance()` > 0 before it counts as "no intersection".
3. **Check 5 is derived from the solids.** For each hardware mounting position in `hardware.py` (9 ATX holes, 6 used radiator-420 holes, 4 used radiator-360 holes, 4 PSU holes of the active pattern plus the mirrored 4, 8 fan holes), find the holder part and prove a hole exists there: a point on the hole axis inside the holder's thickness is outside the solid and within the hole radius plus 0.2 mm of it. Count those. Delete the hand-appended count, or keep it only as a cross-check that must equal the derived number. `build_frame()` must reset `FASTENERS` and `PILOTS` on every call so a second call does not double them.
4. **Left-hand parts carry left-hand cutters.** When a solid is mirrored, mirror its `cut_cyls` too, so check 7 and the new bore test measure holes that lie in that part.
5. **Minimum wall for every hole.** Between any two holes in a part, and between any hole and the part's outer surface: 2.1 mm when either is an M4/M4S pilot or an M4 clearance hole, 1.6 mm for M3 and 6-32. Replace the 0.8 mm rule. If an existing hole fails, report it with the measured wall and the smallest fix; do not lower the limit.
6. **No literals for hardware holes.** `build_antler_right` and the visor arm read their hole positions from `RAD420_HOLES_X/Z` and `RAD360_HOLES_X/U` in `hardware.py`. Search `frame_v0.py` for any other number that duplicates `hardware.py` and remove it.

### Prove the checks bite
Add `cad_b6/test_checks.py`, run with `.venv/bin/python cad_b6/test_checks.py`. It builds the frame once, then for each case below damages a copy in memory and asserts that `run_checks` reports a failure for it, and finally asserts that the undamaged model reports none:
- a part with one pilot hole filled back in (fuse the bore cylinder into it);
- a part translated 5 mm into a neighbouring component;
- two parts overlapping each other;
- a left-hand part with one clearance hole filled;
- a hardware hole position shifted by 5 mm in `hardware.py`'s table without moving the hole in the part (check 5 must drop by one);
- an `inter_vol` call whose `intersect` raises.
Print one line per case: name, expected failure, what was reported.

### Record what is already in the model
- `dimms` starts at u = 146, not 158: the slots span u 146..291 on the scan (`refs/board_scan_overlay.png`, 840 px / 5.76 px/mm). Add this to "Отклонения от плана".
- `gpu_tubes` keep-out (bs v 278..338, u 80.6..121.6, n 5..75): tubes leave the card axially from the end opposite the bracket (`refs/gpu_5080_suprim_liquid_tubes.png`). The 60 mm depth is an estimate. Mention it in the report with the other keep-outs.

## Revision 4 — real hose geometry, fans outside blowing in, 360 raised (14 Nov 2026)

Owner decisions: both radiators stay centred on the structure; the 360 may be raised; every radiator fan sits on the outer side of the case and blows inwards, towards the board.

Evidence, all measured on ARCTIC's 2D drawing (`refs/arctic_lf3_pro_420_2d_drawing.pdf`; marked-up crops `refs/arctic_block_side_measured.png`, `refs/arctic_radiator_ports_front.png`, `refs/arctic_radiator_ports_side.png`) and on photos (`refs/gpu_5080_suprim_liquid_tubes.png`):
- CPU block: round body Ø91, a lug with the two fittings on the side that faces the graphics card (towards smaller u). The hose leaves each collar square to the board. Collar axis 54.6 mm from the socket centre, collar top 67.2 mm above the cold plate, cold plate taken 7.5 mm above the board. Collars are treated as fixed.
- 420 radiator: the two ports stand on the **face** of one end tank, square to the face, 8.4 mm in from the radiator's end, 23.8 mm apart about the middle of the 138 mm width, collar Ø20, top 20 mm above the core face. They are not axial. Fans can go on either face.
- PSU (Noctua Edition): with the fan up and seen from behind, the AC inlet is on the right, which is world −X. The hole pattern is the standard one in that view; the mirrored set is no longer needed.

`cad_b6/tube_study.py` (run it) gives the CPU hose 318 mm of its 500 mm to the right-hand port with the 360 at n = 122, no clash, nothing closer than 8 mm.

### hardware.py
- `cpu_block`: replace the box with the real envelope. Body: cylinder radius 45.5 on the socket centre, n 0..76. Lug: box v socket ± 22, u from socket − 62.97 to socket − 40, n 0..74.7. Fuse them. Keep the socket centre constant; drop the clipped-box workaround.
- `rad360` moves out: `RAD360_BS = (-75, 319, 184, 305, 122, 177)`. Core n 122..152 (inner side), fans n 152..177 (outer side, blowing towards the board). Everything derived from the inner face follows.
- `rad420` keeps its box (Y 287..355) but is turned round: core Y 287..325 at the front, facing the board; fans Y 328..355 at the rear, blowing forwards through the core. The rear face at Y = 355 is now the fans' face; the frame's screws pass through the fans into the radiator (same X/Z pattern).
- New keep-outs, treated like `io_zone` (in checks 1–2, out of the envelope and holders check):
  - `rad420_ports`: world box X 208..233, Y 265..287, Z 290..340 (the two collars on the front face at the right-hand end).
  - `cpu_hoses`: two hoses, each a chain of capsules of radius 8.0 (hose radius 6.2 plus 1.8 allowance). Hose A: bs(134 − 11.9, 162.4, 74.7) → bs(134 − 11.9, 162.4, 109.7) → world (220.6, 222, 315 − 11.9) → world (220.6, 267, 315 − 11.9). Hose B: the same with + 11.9 in both places. Build the chain from `hardware.py` constants, not literals in `frame_v0.py`.
- `PSU_HOLES`: the single standard pattern, world x = 75 − x_hole, z = y_hole. Delete the mirrored set and the "TO CONFIRM" note; record that the inlet is at −X.
- Add a short comment block stating the airflow: 360 fans on its outer face blow in towards the board, 420 fans on its rear face blow forwards, front 2×140 blow in.

### frame_v0.py
- visor arms, necks and the pivot follow the 360's new inner face (arm bar n 108..122, pivot 7 mm below the inner face as before). Reshape the necks as little as needed to clear `cpu_hoses` and `rad420_ports` by at least 5 mm; the right-hand neck and arm are the ones near the hose.
- psu_bulkhead: four PSU holes, not eight. Check 5 expects psu 4.
- The antlers stay behind the 420. Record in the report's open items that their screws now pass through the 27 mm fans, so the stock fan screws are too short for a 10 mm plate (longer 6-32 screws or a counterbore).
- Report: add an "Воздушный поток" paragraph with the fan sides and directions, and the hose result from `tube_study.py` (path, slack, nearest clearance).

### layout_b6_options.py
- Row E: `r360_b` n 122..177. Regenerate the figure and report row E's margins.

### test_checks.py
- Keep all 26 cases passing; add one: a frame part pushed into `cpu_hoses` must fail check 2.

## Revision 5 — 420 at 90° to the board, hoses routed inside the envelope (14 Nov 2026)

Owner decisions: the 420 stands at 90° to the board behind its top edge (it gains hose length and blows along the board); both radiators stay centred; **nothing may stick out past the radiators' ends (|X| ≤ 229) or in front of the front fans (Y ≥ 0)**, because a passer-by could catch it; the hoses should read as a design element. The MSI radiator's ports are like ARCTIC's (on the face of an end tank, square to it) and its fans can go on either face.

The routes are designed and measured in `cad_b6/hose_routes.py` (run it; it prints the table and renders `previews/b6_hoses_*.png`). Result: CPU hoses 482 of 500 mm, GPU hoses 435 of 450 mm, every bend ≥ 35 mm radius, nothing closer than 8 mm to hardware, |X| ≤ 227.
- CPU pair: up from the block to the level of the visor's outer face, along just below its lower lip to the left-hand end, down the left flank into the 420's port.
- GPU pair: out of the card's end, down behind the board plane, up-slope behind the board's right-hand edge, up into the 360's port from below. The spare length is out of sight there.

### Module layout
- Move the route geometry (`fillet_path`, `solve`, the route builders and their constants) out of `hose_routes.py` into a new `cad_b6/hoses.py` that depends only on `hardware.py` constants and numpy. `hose_routes.py` keeps the analysis and rendering and imports from it. `hardware.build_hardware()` builds the hose keep-outs from `hoses.py`. No waypoint may be typed twice.

### hardware.py
- `rad420`: board-space box v −107..351, u 310..378, n −15..123. Core u 310..348 on the side facing the board, fans u 351..378 on the outer side blowing down-slope along the board. Screw pattern on the outer (fan) face u = 378: world X ∈ {±62.25, ±77.75, ±202.25}, n ∈ {54 − 62.25, 54 + 62.25}.
- `rad420_ports` (keep-out): bs v −111..−86, u 288..310, n 30..78 — the two collars on the core face at the left-hand end.
- `rad360`: unchanged box (n 122..177), fans on the outer side, ports on the inner face at the right-hand end. `rad360_ports` (keep-out): bs v 298..323, u 220..269, n 100..122.
- `cpu_hoses`, `gpu_hoses` (keep-outs): for each hose a chain of cylinders along the sampled route from `hoses.py`, radius = hose radius + 1.8. Flat ends at the collars, as in Revision 4.
- Delete the Revision 4 `cpu_hoses` and `rad420_ports` definitions (the vertical-420 route).
- Update the airflow comment: 420 fans blow down-slope along the board, 360 fans blow in from the front face, front 2×140 blow in.

### frame_v0.py — parts that change
1. **rib_B: cradle for the tilted 420.** The radiator's underside is the plane n = −15 between u = 310 and u = 378, a 45° face rising towards the back. Replace the flat saddle with a cradle whose top is the plane n = −18 (3 mm for a pad) over u 312..376, carried by the post. Keep the runner, the nose, the tail post and the lap joints to rib_A. Keep the part ≤ 290 mm.
2. **Antlers on the fan face.** A plate 10 thick on the plane u = 378..388. In (X, n): bar X 68..212 at the lower screw row, finger X 193..212 up to the upper row, three clearance holes at the hole pattern (the screws pass through the 27 mm fans). A tongue laps onto the outer face of the rib (|X| 158..168) below the radiator and is bolted to the rib with 2×M4 along X; extend the rib's tail post or post upwards as needed so there is material behind the tongue. The radiator's centre of mass is forward of the cradle, so the antlers carry the tipping load: say so in the report.
3. **Necks and visor arms.** The pivot behind the visor's top edge is now inside the 420, so the neck becomes a straight strut along n at u = 297, |X| 180..192, from n = −30 to n = 115, standing 3 mm clear of the 420's core face, with a spacer pad to the rib's top node (|X| 158..180) and 2×M4 into the rib. The visor arm (|X| 166.5..178.5, under the 360's inner face, two screws into the radiator) joins the neck at its upper end with an M5 pivot at bs(u 298, n 115) and an M4 locking bolt 30 mm down-slope along the arm. Swing clearance is not checked in this pass.
4. **gpu_post** and everything else: unchanged unless a hose keep-out is in the way; then move the part, not the hose.
5. **Hose guides** (two printed parts, each a block with two open-sided channels of hose diameter + 0.6 mm at the route's local spacing, 12 mm long along the hose):
   - `hose_guide_cpu`: on the left neck, where the CPU pair turns from the lip run down the flank. Bolted to the neck with 1×M4.
   - `hose_guide_gpu`: on the right-hand rib's outer face, on the up-slope run behind the board. Bolted with 1×M4.
   The guides are the only parts allowed to touch the hose keep-outs; list those contacts as intended. If a guide cannot pass the checks with a small change, leave it out and report it.

### Checks
- All existing checks and all `test_checks.py` cases stay. Check 5 for `rad420` uses the new hole pattern.
- New check 8: no frame part and no hose reaches beyond |X| = 229 or in front of Y = 0. Report the extremes.
- New check 9: every frame part except the two guides is at least 5 mm from `cpu_hoses` and `gpu_hoses`.
- Add test cases: a hose waypoint pushed 20 mm outward must fail check 8; a part moved against a hose must fail check 9.

### Report and studies
- Rewrite "Отклонения от плана" and the open items for the model as it stands. Add the hose table from `hose_routes.py` and the airflow paragraph.
- `tube_study.py` and row E of `layout_b6_options.py` describe the vertical 420. Move `tube_study.py` to `history/` with a one-line note at the top; update row E to the tilted 420 (its box is now in board space) and regenerate the figure.
- Open items to list: visor swing against the hoses and the 420; how far the visor can open before the GPU hoses go taut; the GPU bracket tab height (still a placeholder); longer screws through the fans.

## Revision 6 — clearances, snug hose guides, no hinge on the 360 (15 Nov 2026)

Findings behind this revision:
- `beam_top` is 1.55 mm from the 420's core face (beam u 288.45..308.45, face at u 310).
- The hose guides hold with 1.8 mm of play because a snug channel overlaps the hose keep-out.
- `cad_b6/visor_swing.py` (run it): with the pivot where it is (u 290, n 115) the 360 meets the 420 after about 15–20° of lift (36 mm at the lower lip); with a pivot on the outer top corner the lower lip sweeps through the CPU hoses at 15°. A hinge is not worth its parts. The GPU hoses are not the limit: their drawn route can shrink to about 331 and 352 mm of 450, so roughly 100 mm of hose can be pulled out of the run behind the board.
- The antler fingers stand above the radiator and add 7 mm to the height.

### Changes
1. **beam_top**: move the section 3.5 mm down-slope, to u = row − 13.5 .. row + 6.5 (same 20 mm width), so it is at least 5 mm from the 420. The standoff bosses stay on the holes. Re-place the end bolts with the 2.1 mm wall.
2. **Antler fingers**: end at n = 121 (the upper screw is at n 116.25; keep the wall). No frame part may rise above the 420's top edge; add that to check 8 and report the frame's top Z.
3. **Arm to neck joint**: no pivot. Two M4 bolts 20 mm or more apart along the arm, both inside both parts with the 2.1 mm wall; remove the pivot disc and lug shapes that only served the hinge. Report: to reach the RAM or the CPU block, undo these four bolts and lift the 360 forward; the hoses allow about 100 mm.
4. **Hose guides, snug**: channel diameter = hose diameter + 0.6, open on one side with a mouth 0.75 × hose diameter so the hose snaps in. The guides are exempt from check 2 against `cpu_hoses` / `gpu_hoses` (the keep-outs carry a 1.8 mm allowance) and are checked against the true hose instead: new check 10 — each guide's solid must not intersect a tube of the real hose radius along the route (volume < 1 mm³) and its channel wall must be within 0.2..0.5 mm of that tube. Build the true-radius tubes from `hoses.py`; do not add them to the hardware keep-outs.
5. Add `test_checks.py` cases: a guide whose channel is 2 mm too small must fail check 10; a part raised above the 420's top must fail check 8.

Everything else stays. Update the report, the deviations list and the open items; drop the visor-swing open item and replace it with the service note.

## Revision 7 — side exhaust fans instead of front fans; skeleton stays the structure (15 Nov 2026)

Owner decisions:
- The two 140 mm fans move from the front to the flanks, one below each end of the 360 radiator, blowing **out**. Air comes in through both radiators, passes over the board, and leaves sideways.
- The plate skeleton in `frame_v0.py` remains the structure that holds every component, with all its checks. The organic design (`organic_frame.py`, a sketch) is a separate outer layer that will be fixed to the skeleton; it carries no component. Nothing in this revision touches the organic sketch.

A clash study against the current model gave these positions (140 × 140 × 25, edges along the board's u and n, thickness along X):

| Fan | World X | Board space | Nearest things |
|---|---|---|---|
| right | 201..226 | u 120..260, n −42..98 | rad360_ports 2.0 mm, gpu_hoses 3.8 mm |
| left | −205..−180 | u 120..260, n −42..98 | cpu_hoses 7.6 mm, io_zone 8.0 mm, visor_arm_left 10 mm |

They are not mirror images: the CPU hoses run down the left flank at X = −221 and the GPU hoses rise at X = +189, so the left fan sits 21 mm further in than the right one.

### hardware.py
- Remove `fans_front` and its hole table.
- Add `fan_side_right` and `fan_side_left` with the boxes above (convert world X to v with `ORIGIN`). Each has four corner holes on the 124.5 mm pattern about the box centre in (u, n), axis along X. State in the airflow comment: 360 and 420 fans blow in, the two side fans blow out.
- The fans are ordinary hardware: in checks 1–2, in the envelope, and in the holders check.

### frame_v0.py
- Remove `fan_rail_top` and the horns on `rib_A` (the `gpu_rest` finger on the right rib stays). `beam_front` stays as the tie between the front feet but loses its fence and fan holes.
- Add `fan_bracket_right` and `fan_bracket_left`. Intent: each fan is screwed to a printed bracket by at least three of its four corner holes, and the bracket is bolted to that side's `rib_A` with at least 2×M4 (inserts with the 2.1 mm wall). Keep the fan's aperture open: no bracket material inside a Ø134 circle about the fan centre. The bracket lies on the fan's inner face (the side towards the board). On the right the GPU hoses rise just inside the fan's up-slope top corner; leave that corner out rather than crowd the hoses. Choose the simplest outline that does this, members ≥ 5 mm, part ≤ 290 mm.
- Check 5: `fan_side_left` ≥ 3 and `fan_side_right` ≥ 3 screws, derived from the solids as for the other components.
- Checks 8 and 9 apply to the new parts as to all others (|X| ≤ 229, Y ≥ 0, n ≤ 123, ≥ 5 mm from the hoses).

### test_checks.py
- Replace the cases that used the front fans or `fan_rail_top` with equivalents on the side fans and brackets. Keep the case count at or above 42.

### Report
- Rewrite the airflow paragraph, the deviations and the open items for the model as it stands. Give the new envelope: the front limit is no longer set by fans.

## Revision 7a — third screw for the right fan (15 Nov 2026)

Finding: on the right the GPU hoses rise 3.77 mm inside the fan's up-slope end, so no bracket material can reach the two up-slope corners on the fan's inner face without coming closer than 5 mm to the hoses. The bracket holds the fan by the two down-slope corners only; check 5 fails, correctly.

Change to `fan_bracket_right` only:
- Keep the spine, the two inner-face ears at the down-slope corners, and the leg to `rib_A_right`.
- Add a top rail that runs along the outside of the fan's top edge: board space n 98.5..104, from the spine up-slope to u 262, lying in the fan's own thickness but no closer than X = 202 on the inboard side (world X 202..226), so it stays at least 5 mm from the hoses.
- At the up-slope end of the rail add a tab that folds over the fan's **outer** face at the up-slope top corner: world X 226..228.5, covering that corner hole with at least 4 mm of material around it, with a Ø4.5 hole on the fan-hole axis. The fan screw goes in from outside through the tab. Nothing may pass |X| = 229.
- Check 5 counts this tab as the third screw: the hole test is the same (a hole on the corner's axis in the holder), applied on the outer face.
- The fan's aperture rule (check 11) applies to the tab and the rail as to the rest of the bracket.

If the rail or the tab cannot keep 5 mm from the hoses, report the measured gap and leave the assert failing.

## Revision 8 — round the skeleton's sharp corners (15 Nov 2026)

Owner request: smooth the sharp corners of the main frame. Two reasons: rounded inside corners carry load better than notches, and a rounded skeleton shows less under the organic outer layer.

This changes shape only. No part moves, no hole moves, no mating face changes.

### Rules
1. **Plate parts built from 2D outlines** (ribs, necks, visor arms, antlers, fan brackets, and any other part extruded from an outline): round the outline before extruding.
   - Inside (concave) corners: radius 8 mm. These are the ones that matter for strength.
   - Outside (convex) corners: radius 6 mm.
   - Where the local geometry is too small for that radius, use the largest radius that fits, down to 2 mm; below that leave the corner and list it.
2. **Box members** (beams, skids, PSU bulkhead, gpu_post, hose guides): round the four long edges with radius 3 mm. If a fillet fails in the kernel, use a 3 mm chamfer on that part and say so.
3. **Do not round**: any face or edge that touches hardware or another part (standoff tops, cradle surface, saddle and contact pads, lap-joint faces, the bulkhead's face on the PSU, bracket faces on the fans, guide channels), and the rim of any hole. A rounded edge must not reduce a contact that the report lists.
4. Also add an 8 mm fillet where a boss, ear, tongue or leg meets its plate, where that corner is free.

### Checks
- All eleven checks and every `test_checks.py` case stay and pass. The wall rule around holes (check 7) now also has to hold against the rounded outline; if rounding brings an outline within the minimum wall of a hole, reduce that radius locally.
- Add check 12: count sharp outline corners that remain on the plate parts (interior angle change above 30° with radius below 2 mm, outside the excluded faces) and list them by part. It reports; it fails only if a part that was meant to be rounded has none of its corners rounded.
- Report the mass before and after, and every part where a corner was left sharp, with the reason.

## Revision 9 — front I/O block from the Fractal North XL module (15 Nov 2026), to do after Revision 8

Owner request: a small block at the front, where the front fans used to be, holding the front I/O taken from his Fractal North XL: 2× USB-A, 1× USB-C, power button.

What is known (research report plus my own reading of a straight-on photo, `refs/north_io_front_measured.png`, scaled on the USB-A shells at 7.3 px/mm; the panel then measures 208 mm, which matches the North's width):
- One module carries, in a row: power button, headphone jack, microphone jack, USB-A, USB-A, USB-C, and a power-LED light slit beyond the USB-C. No reset button.
- Centre-to-centre along the row, ±1 mm: button → headphone 22.1, headphone → microphone 15.1, microphone → USB-A 18.2, USB-A → USB-A 22.2, USB-A → USB-C 20.4. Button cap about Ø18. From the button's edge to the USB-C's edge about 112 mm; the LED slit runs about 43 mm further.
- Four cables to the motherboard: power switch + LED, HD Audio, USB 3.0 19-pin, USB Type-E.
- **Not known**: PCB outline and thickness, mounting holes and screws, connector heights, how far the ports stand proud, the switch and whether the metal button cap comes out with the module, and every cable length. No drawing or photo of the bare module was found. The owner will measure the module when he takes the PC apart for the prototype.

So this revision reserves the place and fixes the interface, and leaves the pocket for the module as parameters:
- `hardware.py`: `front_io`, a box for the module with its housing: world X −70..95, Y 0..42, Z 10..46 (165 × 42 × 36), marked `# PLACEHOLDER until the module is measured`, plus the port pitches above as a table.
- The ports face forwards and upwards: the block's face is a plane tilted 45°, parallel to the motherboard, so a plug goes in along the board's normal.
- `frame_v0.py`: `io_block_base`, a printed seat on `beam_front` that the block bolts to with 2×M4, and nothing else. No port cut-outs yet.
- Checks: `front_io` is hardware (checks 1, 2, 8) with one holder and 2 fasteners.

### Revision 9, additions (15 Nov 2026): light line and materials

**Light line.** The owner has translucent plastic and wants a diffuser line like the power-indicator line on the Fractal North XL. Reserve it in the front sill, not in the organic layer:
- The front I/O block becomes a full-width **front sill**: a bar on `beam_front` across X −140..140 with the 45° face. The I/O module sits in its middle; the light line runs along the upper edge of the face over the whole width.
- `hardware.py`: `light_strip`, a reserved channel for an LED strip and its diffuser: world X −135..135, 14 × 14 mm in section, just behind the upper edge of the sill's face (`# PLACEHOLDER` position until the sill is designed around the measured module). Record the intended build-up as constants: strip up to 12 mm wide, at least 10 mm from the LEDs to the diffuser, diffuser 1.6 mm thick showing as a 4 mm line.
- The strip is lit from a motherboard LED header or 5 V supply, so it is on when the PC is on. The I/O module's own single LED cannot light a line this long. Wiring is an open item, with the cables.
- Parts stay ≤ 290 mm: the diffuser and the sill are each split at the middle if needed.

**Materials.** Decided by the owner:
- **ABS** for everything that carries load: every part in `frame_v0.py`.
- **PLA** for the visual, organic outer layer (`organic_frame.py`).
- **Translucent PLA** for the light line's diffuser (the owner's translucent plastic is PLA too).
Consequences to build in:
- Give every part a `material` field and report mass per material.
- PLA softens at about 55–60 °C and creeps under load well below that. PLA parts carry only their own weight, and keep at least 10 mm from the graphics card's body and from the PSU; 4 mm from the radiators and fans is enough.
- ABS and PLA shrink differently, so the organic layer is fixed to the skeleton at a few points with slack, not along long seams.
- The diffuser is PLA, so the LED strip is mounted on the ABS sill, never on the diffuser, and the 10 mm air gap between the LEDs and the diffuser is also a thermal requirement. A strip run at full white in a closed 14 × 14 channel can pass 50 °C at its surface; plan for a low-power strip or reduced brightness, and leave the channel open at both ends so it breathes.

**Nylon.** The owner's spool is yxpolyer PA6, unfilled, 1 kg, black (`docs/printer-and-materials.md`). Decision: PA6 for the two hose guides (their mouths snap over the hose), cable clips, and the clips that fix the PLA layer to the skeleton. Update of 16 Nov 2026: the cables are held by hook-and-loop straps through `tie_bridge` parts and the PLA layer by M3 screws, so both of those are ABS or gone; PA6 is left for the two hose guides only (`docs/plans/cables-and-organic.md`, "Bridge material"). Everything else in the skeleton stays ABS: PA6 is too little for the plates, warps on large parts, and is less stiff than ABS once it has taken up moisture. `fan_bracket_right` stays one ABS part, tab included. PA6 must be dried and fed from a dry box; the CFS was at about 65 % humidity.

## Revision 8a — round the outside corners too (15 Nov 2026)

Result of Revision 8: 48 of 150 sharp outline corners were rounded; 102 remain, 36 of them only because Revision 8's rule 3 forbade any loss of contact area and a 6 mm corner on a contact face costs 7.7 mm². That rule was stricter than the purpose needs. The owner asked for the sharp corners to go; a corner of a pad that rests on a radiator does not need its last few square millimetres.

Change to the rules:
- A rounded corner **may** reduce a listed contact's area, as long as that contact keeps at least 97 % of its unrounded area and at least 4 mm of flat contact remains around every screw or bolt in it. Report every contact that lost area with before and after.
- Everything else in Revision 8 stands: hole walls, hose and hardware clearances, no overlaps, part stays one solid.
- With this rule, round the convex corners that were left for contact area (antler plates and tongues, neck pads, bracket legs, arm corners, rib B at the lap and the antler, the cradle ends), at 6 mm or the largest radius that fits, down to 2 mm.
- Hose guides stay unrounded (PA6 snap parts; their channel walls are thin).
- The right bracket's rail group: round what can be rounded without splitting the part; otherwise leave it and say so.
- Check 12 keeps reporting; the contact-area check now enforces the 97 % floor instead of "no loss".

## Status after Revisions 8a and 9 (15 Nov 2026)

- Checks: `frame_v0.py` passes, `test_checks.py` 92/92. Sharp outline corners 102 -> 56 of 150, every one explained in the report. No contact lost more than 2.3 % of its area.
- `front_sill` is built (one ABS part, 280 mm). `organic_frame.py` now reads the real sill from `frame_v0.sill_geometry()` instead of its own placeholder box; its veil starts at the sill's upper edge, behind the light line.
- Strength on the rounded skeleton (`strength.py 7 2`, 4 perimeters): sag at the 420 1.98 mm and at the 360 1.51 mm at 20 % infill, the same as before the rounding. Plastic with the sill: 1475 / 1864 / 2643 / 3032 g at 20 / 40 / 80 / 100 %.
- The rounding did **not** lower the peak. It sits at the antler root, at the concave corner (u 378, n -20) where the tongue meets the plate, which Revision 8 could not round (the link step is 4 mm long). With a 1.5 mm mesh in a 12 mm ball there (`strength.py 7 2 --focus`) the wall stress is 5.99 MPa left and 5.89 MPa right at 20 % infill, against 6.7 MPa allowable. The next places are at 2.8 MPa (the feet).
- Hand check of the same place: half of the 420's weight (9.3 N) acts about 75 mm from the root, about 730 N mm about X. The only material between the tongue (50 mm deep along u) and the radiator is the plate, 10 mm along u. That is about 4 MPa nominal, so the cause is the small section, not only the sharp corner.

## Revision 10 — strengthen the antler root (15 Nov 2026)

Scope: `cad_b6/frame_v0.py`, both antlers (mirrored). No hardware moves. No hole or bolt moves.

1. **Buttress behind the plate.** A prism over the tongue's X range (`TONGUE_X`), on the plate's rear face (u = `ANTLER_U[1]`). In (u, n) it is the triangle (`ANTLER_U[1]`, -44), (`ANTLER_U[1]` + 14, `TONGUE_N[1]`), (`ANTLER_U[1]`, top of the bar). The section at the root grows from 10 to 24 mm along u. Use named constants (`ANTLER_BUTTRESS_DEPTH = 14.0`, `ANTLER_BUTTRESS_N0 = -44.0`); the other two numbers come from existing constants. Fuse it into the antler before drilling, so `blank` carries it. Round its apex and its two ends with the existing rounding rules.
   Free space was measured in the main session with this exact triangle: 10.0 mm to `rad420`, 13.8 mm to `rib_B`, everything else beyond 80 mm; its largest Y is 365.5, inside the antler's present 371.5.
2. **Fillet the concave corner (u 378, n -20).** Let the link reach the bar's top (`TONGUE_LINK_N1`), so the corner's upward edge is long enough, and give the corner the largest radius the checks accept. The radiator's bottom face at n -15 limits it to 5 mm; do not move the tongue's top to get more.
3. Nothing else changes. The contact `rib_B x antler` keeps its area. The tongue bolts stay reachable from outside along X.
4. All checks pass as they are. No check, tolerance or exemption is changed to make this pass. `test_checks.py` stays at 92/92; change an expected number only if a case measures the antler's own outline or volume, and say which.
5. Report: the radius reached at the corner, the buttress's clearance to `rad420` and `rib_B` (`measure.py`), the antler's volume before and after, largest Y of the antler.

After it, the main session reruns `strength.py 7 2 --focus`. Aim: the peak in both focus zones at or below 3.5 MPa at 20 % infill (now 5.99 and 5.89).

### Revision 10, result (15 Nov 2026)

Built as planned, with one deviation: the buttress ends on the bar's centre line (n -8.25), not at the bar's top (n 1.75). Ending at the top edge left a sharp 57° concave edge on the plate's rear face that check 12 could not explain. The section at the root is the same 24 mm. The corner (u 378, n -20) has a 5 mm fillet. `frame_v0.py` passes, `test_checks.py` 92/92, sharp corners 54 of 156.

| At 20 % infill, 4 perimeters | Before | After |
|---|---|---|
| Wall stress at the antler root, 1.5 mm mesh, left / right | 5.99 / 5.89 MPa | 2.58 / 2.63 MPa |
| Sag at the 420 | 1.98 mm | 1.68 mm |
| Sag at the 360 | 1.51 mm | 1.51 mm |
| Wall stress, 99.9th percentile | 2.17 MPa | 1.99 MPa |
| Skeleton plastic | 1475 g | 1478 g |

The aim of 3.5 MPa is met. The most loaded places are now the feet (2.7 to 2.9 MPa), where the model fixes the skids to the desk; that is a boundary of the model more than a load in the part.

`strength.py` changes made along the way: the stiffness matrix is assembled once for a unit modulus and scaled per infill (assembly was 71 s of every case), and MKL Pardiso is used where `pypardiso` is installed. Same numbers, 519 s -> 144 s on a 20-core x86 machine. On the Mac the solver stays SuperLU and the single assembly still applies.

## Owner decisions (15 Nov 2026)

Two items the earlier revisions left open are accepted as they are. Do not raise them again.

- The 15 outline corners kept sharp by the rule "4 mm of flat contact around every screw" stay sharp (fan bracket ears, neck-to-arm bolts).
- The head of the outer screw on the right fan bracket's tab stands 2 to 3 mm past |X| = 229. That is accepted as a tolerance; no countersink.

The owner's reason: neither will get in the way during assembly or show in the look of the case.

- The graphics card's power cable may stand up to 11 mm in front of the front plane Y 0 (measured 10.4 mm). Details: `docs/plans/cables-and-organic.md`.

**ARCTIC hose length: 450 mm.** ARCTIC's spec sheet says 450 mm and its product page says 500 mm. The owner decided to use the spec sheet's number. `hoses.CPU_HOSE` is 450 now (it was 500 from Revision 5 on). Measured after the change: the CPU hoses use 432 of 450 mm, every bend is 35 mm, and the run below the visor's lip sits at n 131 and 140 (it was 161 and 169). Hose a now passes 7.7 mm from the graphics card; the keep-out check allows it. `frame_v0.py` passes every check, `test_checks.py` 92 of 92, the gauges and the organic layer rebuild clean. The numbers "482 of 500" in the Revision 5 text above are history.

## Revision 11 — the 420's bracket moves between the fans and the radiator (16 Nov 2026, to build after the drive bays)

Owner's observation: the 420's mount sits where its fans are. Either it has to cover every fan hole and lie between the fans and the radiator, or the mount has to be redone.

**What the model has now.** Each antler is a 10 mm plate on the outer face of the fans (u 378..388). Three 6-32 screws per antler pass through the plate and the 27 mm fans into the radiator. Two things are wrong with it:

- The bar (20 mm tall along the lower screw row, X 68..212) and the finger (X 193..212) lie across the blades of the outer fan, on its intake side.
- The screws have to be about 41 mm long (10 + 27 + thread), which is not a stock length.

**Why not the other face.** Measured on the voxel grid: in front of the core face (u 310) there are 5 mm to `beam_top`, the board's edge and the 360's upper edge at the inner holes, and the organic layer and the 360's ends at the outer holes. No bracket and no screwdriver fit there.

**Decision, main session: the owner's first option.** A plate between the fans and the radiator that takes all twelve fan holes, so the three fans stand on one plane.

- Two mirrored halves that meet at X 0, since 456 mm does not fit the 300 mm bed. Each half takes six holes: all four of its outer fan and the two nearer ones of the middle fan.
- The plate follows the fan frames: a round opening per fan, material only where the frames are. Nothing lies across the blades on either side.
- Thickness 3 mm, which is the 3 mm the model already keeps between core (u 310..348) and fans (u 351..378). ARCTIC's drawing gives 38 + 27 = 65 mm and 68 mm over the screw heads, so the fans end up at u 351..378 and the heads behind them.
- Below the radiator's underside (n -15) each half grows into the present foot: the tongue on rib B's outer face with its two M4 bolts and the buttress. The root is the place Revision 10 had to strengthen, so `strength.py` is rerun.
- The fan screws become 3 mm longer than stock. Length and thread of the stock screws are being researched and go on the owner's check sheet.

**Also found, from ARCTIC's drawing (`refs/arctic_lf3_pro_420_2d_drawing.pdf`, page 1, side view):** the fans come mounted on the face the hose collars stand on. The model has the collars on the core face towards the board and the fans on the opposite face, so the fans have to be moved to the other face when the case is built. Whether the radiator is threaded on that face and whether the fans' lead reaches is in the same research.

**Owner, 16 Nov 2026:** fans can be put on either face of a radiator, the CPU's or the card's, in any configuration. So the radiator is threaded on both faces and moving the fans is not an open point any more.

It does not change the decision. Fans on the board side would need 27 mm where there are 5, and moving the radiator back by 27 mm to make room would lengthen the CPU hoses, which use 432 of their 450 mm.

### Research result (Grok `web-research`, 16 Nov 2026; the pattern drawing was opened and read in the main session)

- **Fan hole pattern: 125.00 mm, not 124.5.** ARCTIC's "P14 Pro Fan Mounting Pattern" drawing (rev. 2025-05-14): holes 125.00 apart, diameter 4.30, frame 140.00 square. `hardware.py` has 124.5 for the 420. ARCTIC does not dimension the radiator's own holes; the fans that come on it are P14 Pro, so the radiator's pattern is taken from the fan.
- **Fan opening:** a circle of 140.00 cut to 136.00 across the flats. At the middle of a side the opening is 2 mm from the frame's edge.
- **Thread:** not stated by ARCTIC. Users report 6-32 UNC, and the 4.30 hole fits a #6 screw. Stock long screws: 32 to 34 mm by two user reports, not measured.
- **How deep a screw may go into the radiator:** not stated anywhere.
- **Fan corners:** rubber round the four mounting holes on a plastic frame (one review).
- **Fans on either face:** ARCTIC's manual shows both; the owner says the same.
- **Stack:** 38.0 + 27.00 with 68.0 overall on the drawing. The 3 mm are not labelled.
- **Weight:** 2370 g for the whole cooler.

### Revision 11: spec for `cad-implementer`

**Hardware, `hardware.py`.**

- The 420's hole table on the 125.00 pattern: X +-62.5, +-77.5, +-202.5; n = middle +-62.5. Name the source beside it. Add the fan's hole diameter and the opening (circle 140 cut to 136 across the flats, about the fan's centre).
- `rad420` becomes two solids under one name: the core u 310..348 and the fans u 351..378. The 3 mm between them is where the plate goes. Correct the comment that calls those 3 mm "hardware".

**Parts.** `antler_right` and `antler_left` keep their names and their foot; the plate changes. The left one is the right one mirrored, as now.

- **Plate:** 3 mm, on the plane u 348..351, between core and fans. The right half covers X 0..228 less a joint gap at X 0, and n -15..123.
- **Openings:** nothing of the plate lies inside a fan's opening. What is left of it between the fans' frames is the outer end bar (over the end tank, beyond the outer fan), the web between two fans, the 2 mm webs along the top, and the corners.
- **Holes:** six per half, 6-32 clearance, at the table's positions: all four of the outer fan and the two nearer ones of the middle fan.
- **Limits:** nothing above n 123 (the rule that no part rises above the 420), nothing beyond the radiator's end.
- **Lower chord and foot:** below the radiator's underside (n -15) the plate may grow thicker and run the half's whole length as a chord. It joins the present foot: the tongue on rib B's outer face with its two M4 bolts (`TONGUE_BOLTS` stay if they can) and the buttress. The old 10 mm plate behind the fans, its bar and its finger go.
- Rounded by the skeleton's rules.

**Checks.**

- Existing ones as they are: clearances, intended contacts (the plate touches the core and the fans), fastener rows (the 420 now has 12 screws, 6 per half), the height rule, rounding.
- New: the plate does not enter any fan opening, and every one of the twelve holes has plate material round it by the wall rule.
- `test_checks.py`: cases that prove the two new checks bite; the cases that measured the old antler are updated and named in the report.
- `strength.py`: rerun. Report the stress at the root and in the plate against the allowable.
- `organic_frame.py`, then `organic_strength` is not rerun here (the gaming PC is down); `cables.py`, `fit_gauges.py`, `drive_access.py`, `render_full.py` rerun. Say how much the organic field changed.

**Report's open items:** the fan screws must be 3 mm longer than stock (6-32 x 34.9 mm if the stock ones are 32); the stock length, the thread and the usable thread depth in the radiator are the owner's measurements.

### Revision 11, first pass: built, strength not passed (16 Nov 2026)

`cad-implementer` built the plate and every geometric check passes (177 of 177 test cases). Not committed. Its numbers, not yet rerun in the main session:

- **Strength fails under the present load case.** The 4 x 3 mm web between two fans reaches 15.7 MPa (18 to 19 with a fine mesh) against 6.7 allowed, and the 420 sags 12.2 mm (1.7 before). The roots are fine: 1.0 MPa where the tongue meets the chord, 1.6 to 2.6 where the plate meets the chord.
- **Why, main session's reading:** `strength.py` puts the radiator's weight on the twelve screws as point loads and gives the radiator no stiffness. The plate then has to carry the load of its upper screws down through the webs between the openings by itself. In the case the plate is clamped to the radiator's core, an aluminium body far stiffer than 3 mm of ABS, so the radiator and the plate move as one and the webs carry next to nothing. The old 10 mm plate hid this simplification; the thin plate does not.
- **The fans are wider than the radiator.** The frame is 140 mm, the radiator 138 mm, so a fan stands 1 mm proud on each long side (n -16 and n 124). The model has both at 138. This is why the web over an opening came out 1 mm, not 2, and it means the chord touches the fans' lower edge.
- **The drive bay lost its margin.** The chord under the radiator (u 338..388, the half's whole length) lies in the path a drive takes: the least tilt went from 26 and 28 degrees to 30 and 30, the limit. Without the chord in |X| 78..120 it is 26 and 28 again.

### Revision 11, second pass: spec for `cad-implementer`

1. **Hardware.** The 420's fans are 140 mm in n: n -16..124 about the same middle. The core stays 138. Everything derived from the fans' outline follows; report what moved, the height rule (`ENVELOPE_N`) included. The plate may use the fans' outline, so the web over an opening is 2 mm.
2. **No sliver.** No part of the plate is narrower than 2 mm. A web that cannot be 2 mm is left out; the plate does not have to close round an opening.
3. **The chord keeps clear of the drive bay's path.** No chord in |X| below about 122, or whatever restores the bay's least tilt to 28 degrees or less in `drive_access.py`. Inboard of that the plate hangs from the radiator. Under the fans the chord keeps clear of their lower edge at n -16.
4. **`strength.py`: the 420 as a stiff body.** The radiator's core becomes a body in the model, stiff against ABS (say what modulus and why; it is a brazed aluminium assembly, so a low figure for aluminium is on the safe side), tied to the two plates only at the twelve screws, each over a patch the size of a screw's washer, not over the whole face. Its weight acts at its centre of mass. The cradle on rib B carries what it carried. The other hardware keeps its present load model.
   - Report both results side by side for the plate: the old point-load case and the stiff-body case. The stiff-body case is the one the allowable is judged on; the report says so and says why.
   - If the root or the chord goes over the allowable with the shorter chord, make the chord thicker where there is room, or longer, and say which.
5. Everything else as in the first pass: no check weakened, nothing committed, the same "done means" list and the same report, plus the 420's sag in both load cases.

## Revision 13 — side fans moved outwards; the card's post becomes a frame (16 Nov 2026)

**Why.** The board's rear connectors and the card's video outputs face the left flank, and nothing could be plugged in (`docs/plans/external-cables.md`). The owner chose on 16 Nov 2026: 140 mm side fans stay at their height and stand further out, so that the cables have room behind the left fan; the case becomes 520 mm wide. The owner also agreed to rebuild the card's post so that the outputs are open and the cables can bend and leave to the rear.

**Measured before the spec** (main session, 1.5 mm grid, see `external-cables.md`): in the left fan's footprint the CPU hoses lie at X -228..-213; a fan whose inner face is at X -235.5 or further is 6 mm clear of them; nothing stands in the right fan's way; nothing but the CPU hoses stands between today's place and the new one on the left.

### Revision 13: spec for `cad-implementer`

The radiators, both pairs of hoses, both hose guides and the 40 mm straight at the 420's ports do not change. If a requirement below cannot be met without moving one of them, stop and report.

**hardware.py**
1. `FAN_SIDE_X`: left (-260, -235), right (235, 260). `FAN_SIDE_INNER_X` follows. `FAN_SIDE_U` and `FAN_SIDE_N` stay. If the exact model puts the left fan closer than 5 mm to `cpu_hoses`, move both fans out together in 1 mm steps and report the number.
2. The envelope. `ENVELOPE_X` (229, the 420's half length) stays the limit for everything except the side fans, their brackets and their leads. For those the limit is the fans' outer face (a new constant derived from `FAN_SIDE_X`). Check 8 and the cables' envelope check use the right limit for each part; no test of the limit is dropped.
3. A new keep-out `gpu_out_zone` for the video plugs and their bend, drawn like `io_zone`: 80 mm out from the card's bracket (v -82..-2), the card's whole thickness in u, n 10..100. Assumption to mark in the file: which part of the bracket carries the outputs is not known, so the whole face is kept open. No printed part and no cable may stand in it. If anything other than `gpu_post` stands in it today, report it and do not move it.

**frame_v0.py**
4. Fan brackets. Both brackets become one design, the right one a mirror of the left (`add_mirror`). The plate lies on the fan's inner face as now, with ears under the three corner holes other than the one at high u and high n (the CPU hoses pass there on the left), the spine along the low-u edge and the bar along the low-n edge. The rail, knuckle and tab of revision 7a go: the card's hoses are no longer near the right bracket. The leg now spans from the rib's outer face (|X| 158) to the plate (|X| 225), 67 mm instead of 12 and 33 mm.
5. The leg's strength. Show by a hand calculation in the report (beam formulas, the numbers written out) that the bracket's worst section stays under the ABS allowable of `strength.py` (6.7 MPa) for two loads: the fan's weight, and a 20 N knock along X at the fan's far corner. My estimate for today's 11 x 28 mm leg under the knock is about 6.5 MPa, which is too close. Make the leg stronger until the margin is at least 2: a deeper section, a second leg to rib_A, or a gusset. No part of the bracket enters the fan's open circle (check 11) or `gpu_out_zone`, and each stays 5 mm from the hoses (check 9). Report the section you chose and why.
6. `gpu_post` becomes a frame. It keeps its job (the seat for the card bracket's tab at n `GPU_BRACKET_TAB_N`, and its two bolts into `beam_mid`). The solid block in front of the bracket is replaced by two columns outside the card's thickness in u, joined by a lintel under the tab, so that the opening shows the bracket over the card's whole thickness and from n 10 to the lintel's underside. Every dimension derives from `hw.GPU_BS` and the tab's constant, because the card's real size is about to be corrected from a fit gauge. State in the report: the opening's size, the lintel's section, the least wall, and the frame's stiffness against a 20 N pull on a cable along -X at the lintel (hand calculation).
7. Bill of fasteners, mounts and the report's text follow the new parts.

**cables.py**
8. The two fan leads start at the fans' new inner faces and are rerouted. They keep clear of `io_zone` and `gpu_out_zone`. Report each lead's length against the lead's real length in the file.

**organic_frame.py and the layer**
9. Do not redesign the layer in this revision. Make `organic_frame.py` run with the new fan places (the grid has to cover |X| 260 plus the layer's thickness) and report what its checks say and where the layer now stands in `io_zone`, `gpu_out_zone` or in the slot between the left fan and the board (X -235..-122). The flanks are redrawn in the next revision.

**Checks and tests**
10. Add a check that `io_zone` and `gpu_out_zone` are free of printed parts and cables, and that a cable bundle 20 mm across can leave from each zone to the rear face of the skeleton without crossing a part (the grid method of `drive_access.py` is acceptable; assert every layer is non-empty).
11. `test_checks.py`: cases for the removed rail and tab are replaced by cases for the new design of the same strictness (a bracket moved past its limit in X, a bracket moved towards the hoses, a block in the open circle, a pilot filled in, a part moved into each keep-out). `fit_gauges.py` G6 must still prove that every corner hole a bracket uses coincides with the fan's.
12. Run the project `verify` skill in full. Regenerate the reports and the previews that show the fans (`render_full.py`; the Blender pictures are not needed).

**Report back:** the numbers asked for above, every place where this spec was wrong and what you did instead, every check or test that changed and why, anything left failing. Do not commit.

## Revision 14a — card rest and front I/O seat as parts of their own; CPU hose clip moved to the left fan (17 Nov 2026)

**Why.** Three decisions of 16 Nov 2026, recorded in `docs/plans/external-cables.md` and `docs/plans/modularity.md`: every card support is a part of its own, so that a misplaced support costs a small reprint; a hardware dimension that is not proved does not live in a part heavier than about 80 g, which today means the front I/O module's seat in `front_sill` (205 g, placeholder dimensions); the CPU hose clip does little next to the 420's ports and moves to where the hoses pass the left fan (6.4 mm apart since Revision 13).

Built on Revision 13. The radiators, the fans, both pairs of hoses, `hose_guide_gpu`, `gpu_post` and the fan brackets do not change. If a requirement cannot be met without changing one of them, stop and report.

### Revision 14a: spec for `cad-implementer`

**1. `gpu_rest` becomes a part.**
- Today it is the capsule `SHAPE_A_REST` in `rib_A_right`'s outline (`frame_v0.py`, near line 544): a finger 16 mm wide whose upper face is the card's cooler face (u = `hw.GPU_BS[2]`), from n -10 to n 104, as thick as the rib.
- New: `rib_A_right` loses the finger and becomes the mirror of `rib_A_left` apart from what else differs today (report what does). A new part `gpu_rest` (ABS) carries the same contact face in the same place and is screwed to `rib_A_right` with two M3 screws into inserts in the new part, through clearance holes in the rib. The rib keeps a flat seat; the new part's foot lies on a face of the rib, not in a pocket.
- Plain holes, no slots (the card's weight acts along a slot's direction).
- Every dimension that follows the card comes from `hw.GPU_BS`.
- Strength as a function in `frame_v0.py` like checks 17 and 18, margin at least 2 against the ABS allowable: the card's whole weight (`strength.py` has 1.6 kg) pressing on the finger's contact face at its middle, and separately a 20 N knock along X at the finger's tip. Report the two screws' tension.
- Check 5's mount count for `gpu_rest`, the intended contact `rib_A_right` x `gpu`, the bill of fasteners and the report text follow.

**2. The front I/O module's seat becomes a carrier.**
- Today `front_sill` has a pocket drawn round the placeholder box `hw.FRONT_IO_W` with `SILL_POCKET_PLAY`, open to the front and below, and two M3 pilots for the module's own screws in the pocket's end walls (`hw.FRONT_IO_SCREWS`).
- New: a part `front_io_carrier` (ABS) holds the module: it wraps the module's box on the two ends, the back and the top with walls of at least 3 mm and carries the two pilots for the module's screws. The sill's pocket grows to take the carrier with 0.3 mm of play and loses the module's pilots. The carrier is screwed to the sill with M3 screws into inserts (in the sill), at least two, placed where a screwdriver reaches them with the module out.
- The carrier's inside follows `hw.FRONT_IO_W` and `hw.FRONT_IO_SCREWS`; the sill's pocket follows the carrier's outside. A later change of the module's numbers must change the carrier only, unless the module grows beyond the carrier's outside; say in the report how much the module may grow in each direction before the sill has to change.
- The window in the sill's face, the light line's channel and slit, the sill's four screws into `beam_front` and the module's rest on `beam_front` stay as they are. If the larger pocket breaks one of them (wall under 2 mm, a screw's wall), stop and report the conflict with numbers.
- Report the carrier's mass and the sill's mass before and after.

**3. `hose_guide_cpu` moves.**
- Today: a PA6 block with two snap channels, foot on `neck_left`, at about u 285, n 54, X -227..-192, just above the left fan and next to the 420's ports.
- New place: on the left fan's free corner. Both fan brackets use corners A, B, C; corner D (high u, high n) is free on the left fan because the CPU hoses pass there. The guide is screwed to the fan's corner D hole: an M3 screw from the fan's outer face through the fan's 25 mm into an insert in the guide, like a bracket's ear. The guide sits on the fan's inner face and holds both hoses in snap channels drawn round the routes at that place (`hose_at`, `guide_channel`), mouths away from the fan.
- If the hoses do not pass within the guide's reach of corner D (channel centres further than 45 mm from the screw's axis), do not stretch the guide: report the distances and propose the nearest sound foot instead.
- `neck_left` loses the guide's pilot and its contact. Check 10 (guide against the true hose), check 9's exemption for the guides, the mirror relation of `neck_left` and `neck_right`, and the bill of fasteners follow.
- The guide may not enter the fan's open circle (check 11 covers the brackets today; extend it to the guide) and must clear `io_zone` and `gpu_out_zone`.

**4. Checks, tests, reports.**
- `test_checks.py`: a case for each new joint (pilot filled in, part moved off its seat), for the rest's strength function (a thinned finger must fail), for the carrier (the module's box grown past the carrier must fail a check, not pass silently), and for the guide in the fan's open circle. No existing case is dropped without a successor of the same strictness.
- `zone_access.py`, `cables.py`, `fit_gauges.py`, `drive_access.py` must still pass. Run the project `verify` skill in full. Regenerate the reports and the previews.
- `organic_frame.py`: only make it run; the layer is redrawn in Revision 14b.

**Report back:** the numbers asked for above, every place where this spec was wrong and what you did instead, every check or test that changed and why, anything left failing. Do not commit.
