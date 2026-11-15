# Cables, and fixing the organic layer

Asked by the owner on 15 Nov 2026 as the second of two work streams: plan the cables and the fixing of the organic layer, and make sure the organic part is not too weak, as a whole and at its fixings.

## Organic layer: decisions

1. **One solid.** `cad_b6/organic_frame.py` builds the whole layer as one signed-distance field on one 1.5 mm grid. Before, the bones and each film were separate overlapping meshes, which cannot be printed, fixed or checked as a body.
2. **Fixings.** The layer is screwed to the ABS skeleton, not clipped. Each fixing is a flat PLA pad, Ø16 x 5 mm, on a skeleton face, with one M3 screw into a heat-set insert in the ABS part. A knot of material (radius 10 mm) surrounds each pad, so the screwdriver channel leaves walls even where a bone lies on the pad. A stub ties the pad to its bone.
3. **Where.** Twelve pads, six a side: `front_foot` (rib A, foot of the diagonal), `sill_end` (end face of the front sill), `base_mid`, `rear_foot`, `rear_post` (rib B), `neck_top` (neck). The script finds each pad's place near a target: 4 mm of flat face round the screw, material round the insert, 2.1 mm from the part's own holes, clear of other parts, hardware and hoses, and a free line for the screwdriver.
4. **Rejected places.** The right rib's upper front arm (2 mm from the graphics card, PLA must keep 10). The visor arms (their outward face is a 10 mm edge). The lower half of the neck (a stub cannot leave it; hoses, the 420 and the rib close it in). The fan brackets (they carry fans; a push on the layer should not load them).
5. **Clearances.** 2 mm from every skeleton part except at the pads, 3 mm from the board's keep-out boxes, 4 mm from hardware and hoses, 10 mm from the graphics card and the PSU, inside |X| <= 229.
6. **Strength rules.** Film strand at mid-span Ø6 to 7.2 mm and at least its length / 18 in diameter (was Ø3.4 to 4.6); where it leaves a bone Ø9 to 12; cross-thread Ø5.2 to 6.8; stub Ø11 to 13. Whatever the carving leaves thinner than 4.5 mm is removed. Loose pieces under 6 cm³ are dropped.
7. **The hoses are part of the frame.** On the right the graphics card's hoses run along the fan's near side and under it, so the fan ring is an arch over the fan and the hoses close it. On the left the ring is open where the CPU hose guide sits, and the front sweep stops at the card's edge, because the CPU hoses turn down the flank between that edge and the lip's corner. The bones that used to run into the 360's end are gone or rerouted.

## Checks in `organic_frame.py`

- Every pad fits its part and keeps its distances (it fails with the reason otherwise).
- The layer is one connected piece and contains every pad.
- A list of every bone the clearances cut, with the length of the cut and what is nearest. Empty apart from the intended places: the screw channels at the pads and the ends of bones that finish in a skeleton part.

## Strength run: `cad_b6/organic_strength.py`

Voxel finite elements on the field's own grid, solid isotropic PLA (E 2800 MPa), fixed at the pads. Load cases: own weight, and a 30 N push at 160 places spread over the surface, once into the surface and once straight down, over a fingertip of 6 mm radius. Allowable stress 12.5 MPa: 25 MPa across layers, halved for a rare hand load. It runs on the gaming PC in about three minutes (1.9 million unknowns, 321 load cases).

What it does not cover: layer direction and infill of the real print, creep near warm parts, impact, and lifting the PC by the organic layer, which the layer is not made for.

| Step | Pushes over the allowable, of 320 | Largest movement | Worst stress |
|---|---|---|---|
| First unified layer, thicker strands, 12 pads | 27 | 45 mm | 67 MPa |
| Right films as dense as the left | 14 | 26 mm | 50 MPa |
| Rings and sweeps routed round hoses, radiators, neck and guide; knots at pads | 2 | 6.0 mm | 24.5 MPa |
| Strand thickness tied to length, rings Ø13 | 1 | 5.5 mm | 17.6 MPa |

State now: median stress under a push 1.3 MPa, median movement 0.17 mm. Own weight moves it 0.03 mm. The largest force on a fixing screw over all pushes is 83 N; own weight puts at most 5 N on one. One push still exceeds the allowable: inward at X 178, Y 288, Z 182 (a strand of the right rear window), 17.6 MPa, which is below the 25 MPa strength but above the allowable.

The price: the layer is 1795 cm³, 2.2 kg if printed solid. Printed with walls and sparse infill it will be well under that; the number to trust comes from slicing.

## Open, organic layer

- The insert pilots in the skeleton are not cut. That is a `frame_v0.py` change for the CAD subagent: twelve M3 pilots at the pad centres in `cad_b6/report_organic.txt`, along X into the named parts, with the skeleton's own hole checks.
- The split into printable pieces of 290 mm or less, with joints, and the print orientation.
- The one strand above the allowable.
- The pads' screw holes are 2 voxels wide in the field; the real holes belong in the printable pieces.
- The front centre (brow, card bone, lip bone) spans 380 mm with no skeleton behind it. It passes the push test through the films, but it is the place to watch when the layer is split.

## Cables

### Facts (research of 15 Nov 2026, each checked against its source unless marked)

| Fact | Value | Standing |
|---|---|---|
| Seasonic PRIME TX-1600 Noctua Edition cables | ATX 24-pin 610 mm; EPS 700 mm (3 in the box); 12V-2x6 700 mm (2); PCIe 8-pin 750 mm (6) | Read in Seasonic's spec sheet |
| Cable build | Individually sleeved wires with combs, not a round bundle | Reviews; not checked |
| PSU sockets, fan up, seen from the front | CPU/PCIe field on the left (-X), the two 12V-2x6 in the centre, motherboard pair on the right (+X) | Inferred from a photo taken fan down; not checked |
| Board headers | Positions scaled off the manual's drawing, about ±5 mm. In (v, u): ATX_PWR1 (239, 220); CPU_PWR1 (190, 299); CPU_PWR2 (205, 299); JFP1 (235, 5); JUSB3 (239, 160); JUSBC1 (239, 110); JAUD1 (20, 5); CPU_FAN1 (225, 299); PUMP_SYS1 (239, 290); SYS_FAN1 (239, 270); SYS_FAN2 (45, 299); SYS_FAN3 (20, 135); JARGB_V2_1 (55, 5) | Agree with the keep-outs measured on the board scan (`ATX24_BS`, `EPS_BS`) |
| ARGB header | 5 V, 3 A, 180 LEDs | Manual, via the research |
| ARCTIC hose length | 450 mm in ARCTIC's spec sheet, 500 mm on ARCTIC's product page. **The owner chose 450 on 15 Nov 2026**; `hoses.CPU_HOSE` uses it | Decided |
| ARCTIC wiring | Fan wires run inside the hose sleeve; one PWM lead leaves the pump head | Product page |

Not found: where the 12V-2x6 socket sits on the RTX 5080 SUPRIM LIQUID, how its radiator fans and pump are wired, the lengths of the Fractal North XL front I/O cables, the lead length of the ARCTIC PWM cable, the outer size of any cable.

**The hose conflict, settled.** With 450 mm the solver finds a route: the run below the visor's lip sits at n 131 / 140 (161 / 169 with 500), and `frame_v0.py` passes every check. Details: `docs/plans/b6-frame-v0.md`, "Owner decisions".

### Where cables go

The space behind the tilted board, above the PSU and between the ribs, is the cable chamber. Every cable leaves the PSU's front face, turns up-slope under the board, and reaches its header round the board's **right edge**, through the 20 mm gap between the board (X 122) and the rib (X 142). The top edge is closed: the 420's core face stands 5 mm from it.

| Cable | From | Round | To | Real length |
|---|---|---|---|---|
| ATX 24-pin | PSU, right sockets | right edge at u about 210 | ATX_PWR1 | 610 |
| EPS 1 and 2 | PSU, left sockets | right edge at u about 265, between the middle and top beams, then along the top strip | CPU_PWR1, CPU_PWR2 | 700 |
| 12V-2x6 | PSU, centre | open | the card | 700 |
| USB 3 front | front sill | right edge at u about 150 | JUSB3 | unknown |
| USB-C front | front sill | right edge at u about 100 | JUSBC1 | unknown |
| Power switch | front sill | bottom edge, right corner | JFP1 | unknown |
| Audio | front sill | bottom edge, left corner | JAUD1 | unknown |
| Light line | sill end | bottom edge | JARGB_V2_1 | to be chosen |
| Pump and 420 fans | pump head | on the board | CPU_FAN1 | unknown |
| Right side fan | fan | right edge at u about 270 | SYS_FAN1 | typical 400 or more |
| Left side fan | fan | left edge at u about 135 | SYS_FAN3 | typical 400 or more |

### Build: `cad_b6/cables.py`

In the manner of `hoses.py`. It does not move hardware and does not change the skeleton.

1. **`hardware.py` gains the facts**, each with its standing in a comment: `HEADERS` (name -> (v, u), the header's top at n 12), `PSU_SOCKETS` (name -> world (X, Y, Z) on the face Y = `PSU_W[2]`: `mb` (48, 43), `eps1` (-52, 30), `eps2` (-36, 30), `gpu` (0, 43) as (X, Z)), `CABLES` (name -> real length in mm or None, radius, minimum bend). Radii and bends are assumptions and say so: ATX 24-pin r 12, bend 30; EPS r 6, bend 20; 12V-2x6 r 7, bend 35 and 35 mm straight at the plug; USB 3 and USB-C r 4, bend 15; thin leads r 2, bend 8.
2. **Routes** as runs and bends through way-points (use `hoses.fillet_path`). The lanes, in board space unless marked world:
   - Out of each PSU socket 45 mm along -Y (world).
   - Under the board at n = -45, in a lane at v = `x_to_v(132)` for the right edge. Cables in the same lane are spaced by their radii.
   - Round the right edge: from n -45 up to n +35, 10 mm outside the board's edge, then down into the header from above.
   - EPS: after the edge, along u to 297, then along v to its header, at n 30.
   - Front I/O: from (X 60, Y 50, Z 30) world behind the sill, under the board's bottom edge, into the same lane. JFP1 and JAUD1 go round the bottom edge at their own v.
   - Left side fan: round the left edge (v = `x_to_v(-132)`).
   - The 12V-2x6 route is not built: its socket on the card is unknown. Leave a clearly named placeholder entry that the report lists as open.
3. **Checks** (asserts, with the numbers in the report):
   - every route's length is at most its real length where that is known; report the spare;
   - no bend tighter than the cable's minimum;
   - every route keeps 3 mm from every skeleton part and every hardware solid other than its own two ends, and 5 mm from the hoses;
   - no two routes overlap.
   If a route fails a clearance, a way-point may move up to 15 mm inside its lane to pass; report every such move. If it still fails, stop and report where and against what. Do not change a check to pass.
4. **Outputs:** `cad_b6/report_cables.txt` (the table: cable, route length, real length, spare, smallest bend, smallest clearance and to what), `previews/b6_cables_<view>.png` for the views `render_vtk.py` uses, with the skeleton light grey, hardware translucent and cables coloured.
5. **Not in this pass:** clips and their insert pilots in the skeleton, the cable slot in the sill's rear wall, the 12V-2x6 route.

### First pass, built (15 Nov 2026): the lane works, the details do not yet

`cad_b6/cables.py` builds eleven routes, checks them and writes `cad_b6/report_cables.txt` and `previews/b6_cables_*.png`. **It ends with an error on purpose: 20 checks fail.** Six of the eleven routes do not pass as drawn. The checks stay as they are; the routes have to change.

What holds:
- The chamber under the board carries every cable from the PSU to the right edge.
- The PSU's cables are long enough: ATX 24-pin 402 of 610 mm, EPS 592 and 686 of 700 mm. EPS 1 has only 14 mm to spare.
- Power switch, audio, light line and pump leads pass. They do not need to go under the board's bottom edge at all.
- The side fan leads fail on the planned route and pass on another one the build found: straight from the fan to its header above the board (right fan 12.4 mm from the hoses; left fan through a window at n 45 to 65).

What does not, and why:

| Finding | Cause | What to do |
|---|---|---|
| ATX 24-pin overlaps the board and the rib | The gap at the right edge is 20.0 mm; the plan modelled the cable as a round bundle of 24 mm | Model it as it is: a flat ribbon about 50 x 9 mm, lying flat against the rib |
| ATX, USB 3, USB-C bend too tightly at the header | 15 mm between the lane and the header cannot hold two bends | Rise about 40 mm before the header, run along u above the board, and turn down into the header with one bend |
| The two EPS cables and the pump lead overlap | They share the 15 mm strip along the board's top edge; CPU_FAN1 sits under the EPS run | Order them in that strip, EPS outermost, and take the pump lead in from the DIMM side |
| EPS 2 bends too tightly | Only 25 mm between its rise and the top strip; the top beam stops it rising later | Rise earlier, with EPS 1 |
| USB-C ends inside the graphics card | JUSBC1 at u 110 lies under the card's body (u 75.6 to 126.6) | Ask the owner whether the front USB-C is connected today, on the same board with the same card |
| USB cables pass 1 mm from the board's bottom edge | The gap between the sill and the board is 12.6 mm; an 8 mm cable with 3 mm each side wants 14 | Accept as a tolerance or open the gap when the sill is redrawn for the real module |

Passage windows along the right edge, measured in the build: the gap is free of beams and the card for u 26 to 73 and u 156 to 285. Everything that goes round the right edge has to use those.

### Owner answers and second research round (15 Nov 2026)

- **Hose length:** 450 mm, done (see above).
- **Front I/O cable lengths:** the owner measures them when the PC is apart. Until then they stay unknown and only their routes are checked.
- **12V-2x6 socket.** The owner supplied MSI's render (`refs/gpu_5080_suprim_liquid_power.png`): the socket sits in a notch on the card's lettering face, the face away from the board (board-space n = top of the card), and the plug enters along -n, so the cable leaves along +n, at right angles to the hoses. No drawing of the card exists: MSI publishes a data sheet only (card 280 x 148 x 51, radiator 394 x 121 x 55, tubes 450), and MSI's site and the TechPowerUp review refuse automated requests. Position read off the render with a projective fit: **centre 132 mm from the bracket end of the face (v 130), +-12 mm; 7 mm below the backplate edge (u 119), +-3 mm; mouth about 13 mm below the face, +-8 mm.** The owner can replace these with one ruler measurement.
- **The card's radiator fans and pump** need no lead to the board: the three fans are daisy-chained and wired to the card through the hose sleeve (a review of the 5090 sister card in the same body); the pump is inside the card.
- **Card height.** MSI's 148 mm includes the edge fingers, so the lettering face stands roughly 143 mm above the board. The model's box reaches n 150. Left as it is (conservative); gauge G7 and a ruler settle it.
- **Board connectors, read again on the scan** (`refs/board_scan_overlay.png`, 5.758 px/mm): ATX_PWR1 is upright, u 192 to 246, v 233 to 241. JUSB3 is upright, u 150 to 173, v 235 to 241. **JUSBC1 is a lying socket at the very edge, u 103 to 116, v 232 to 244: its plug enters from outside the board edge, in the board's plane.** CPU_PWR1 and CPU_PWR2 are upright at u 292 to 303, v 181 to 198 and 201 to 219. The DIMMs cover u 146 to 291, v 185 to 219.
- **JUSBC1 and the card.** The header lies under the card's body (`refs/usbc_under_card.png`). The model's card box reaches the board (n 0), the real card's lower edge beyond the slot is level with the slot's top, about 11 mm up, and a lying plug is about 8 mm thick. So it probably fits; asked of the owner: does the front USB-C port work in the present PC (same board, same card)?
- **Section of the right edge**, cut from the model at X 132 and X 150: the rib's rail (X 142 to 158) spans n about -30 to 0 along the whole board. Above the board's plane the rib has only a post at u 58 to 72. So a cable that has come up through the 20 mm gap may swing outward over the rail. Beams cross under the board at n -30 to -10: beam_low u 8 to 25, beam_mid u 125 to 155, beam_top u 285 to 305.

### Second pass: spec for `cad_b6/cables.py`

Rewrite the routes. One set of routes only: drop the `plan`, `moved` and `alt` variants and their constants. Keep the route machinery, the report and the previews. The first pass's findings stay in this file; the script describes the present design only.

**Facts into `hardware.py`** (each with its standing in a comment):
- `GPU_PWR_SOCKET = dict(v=130.0, u=119.0, recess=13.0)`: centre of the socket's mouth; its n is `GPU_BS[5] - recess`. Standing: read off a render, +-12 mm along v.
- `GPU12V_PLUG = 13.0`: how far the plug's back stands out of the mouth (assumption). `GPU12V_STRAIGHT` (35) counts from the plug's back.
- `HEADERS_LYING = ("JUSBC1",)`, `LYING_PLUG = dict(length=15.0, thick=8.0)` (assumption): a lying header's plug enters along -v from outside the board edge, centred `thick / 2` above the board face.
- `GPU_UNDERSIDE_N = 11.0` (assumption, see above).
- `CABLE_SLAB = {"atx24": 6, "gpu12v": 4}`, `SLAB_STRAND_R = 4.0`, `SLAB_PITCH = 8.0`, `SLAB_BEND = 15.0` (assumptions): where a bundle of sleeved wires passes the gap at the board's edge it lies two wires thick, modelled as that many round strands side by side along u.
- Correct the comment on `CABLES`: the 12V-2x6 socket is known now.

**Cross-sections.** A route is a list of sections; each section is round (the cable's radius and bend from `CABLES`) or a slab (strands side by side along u, bend `SLAB_BEND`). A slab section must stay in a plane of constant u. ATX and 12V-2x6 are slabs from just under the board's edge to their end above the board (ATX) or to the top of their descent (12V-2x6); round elsewhere. EPS, USB and the thin leads are round everywhere.

**Routes.** Way-point numbers are the builder's to find; the shape of each route is fixed here. Search the numbers against the checks, the way `hoses.py` does, and keep them as named constants.

| Cable | Shape |
|---|---|
| ATX 24-pin | PSU `mb` socket, out along -Y, under the board below the beams, turn to +v under the header, slab through the gap centred on the header (u 219), above the board's plane swing out over the rail as far as the bend needs, one U-turn, down into ATX_PWR1 from above |
| 12V-2x6 | From the socket's mouth along +n: plug, then 35 mm straight. Then one arch in the plane through the socket and the descent point: bend, straight, bend, to come down along -n in the gap between the card (u 126.6) and the 360 (u 184), in the lane at the right edge. Slab down through the gap to under the board, then round to the PSU `gpu` socket |
| EPS 1, EPS 2 | PSU sockets, under the board, up through the gap above the ATX slab and below beam_top, then over the board to CPU_PWR1 / CPU_PWR2 and down into them. The two must not cross; EPS lies outermost in the strip along the top edge |
| USB 3 front | Sill start, under the board's bottom edge, the lane, up through the gap between the 12V-2x6 and the ATX slab, U-turn, down into JUSB3 from above |
| USB-C front | Sill start, under the bottom edge, the lane, to u 110; the plug leaves JUSBC1 along +v (`LYING_PLUG`), then the cable bends down into the chamber. For this route only, the card counts from `GPU_UNDERSIDE_N` up. If the rail is in the way, do not move the rail: report the notch it would need (u range, n range, depth) |
| Pump and 420 fans | As now, but under or beside the EPS run: in from the DIMM side |
| Side fans | The routes the first pass called `alt`: straight from the fan to its header above the board |
| Power switch, audio, light line | As now |

Order in the gap, from low u: 12V-2x6, USB 3, ATX, EPS. Everything keeps 3 mm from the card (u 126.6) and from beam_top.

**Checks**, as before, unchanged: length within the real length where known; no bend under the section's minimum; 3 mm from every skeleton part and hardware solid except the route's own ends, 5 mm from hoses; no two routes overlap. **New check:** every route stays inside the envelope (`Y >= ENVELOPE_Y0`, `|X| <= ENVELOPE_X`), measured on the cable's surface.

The script still exits 1 if any check fails. Each failure is printed with one of three classes, and only these may be used:
- `owner`: the 12V-2x6 route's envelope check, if it fails (a straight plug on a card whose face looks forward; the owner decides between accepting it and an angled plug). Report by how many millimetres.
- `skeleton`: the two USB cables' clearance at the sill and the board's bottom edge (the sill gets a cable slot in the next pass), and the USB-C notch in the rail if it is needed.
- `route`: everything else. A `route` failure means the pass is not done: fix the route or stop and report where and against what.

**Report additions:** the socket numbers and assumptions used; the 12V-2x6 route's furthest point in front of Y 0; a section "What the skeleton has to provide" with the sill slot (where the front cables leave it and the gap they need), the rail notch if any, and a proposed list of clip points (where a cable changes direction under the board and where it enters the gap), as coordinates only. Nothing is cut in the skeleton in this pass.

**Previews:** `previews/b6_cables_<view>.png` as before, plus one close view of the right edge from the front right. Remove the `b6_cables_alt_*` images.

### Second pass, built (15 Nov 2026): no route errors left

`cad_b6/cables.py` builds twelve routes in one set. It ends with an error because 5 checks fail: **1 for the owner to decide, 4 that wait for the sill's cable slot, 0 route errors.** Checked in the main session: the script was rerun, the check code was read for exemptions, the previews were looked at, `frame_v0.py` passes.

| Cable | Route | Real | Spare | Smallest clearance, to what |
|---|---|---|---|---|
| ATX 24-pin | 532 | 610 | 78 | 5.5, board |
| 12V-2x6 | 684 | 700 | 16 | 3.5, rib_A_right |
| EPS 1 | 692 | 700 | 8 | 3.5, board |
| EPS 2 | 683 | 700 | 17 | 3.5, board |
| USB 3 front | 433 | unknown | | 1.93, board's bottom edge; 2.65, sill |
| USB-C front | 295 | unknown | | the same |
| Power switch, light line, audio | 31, 61, 175 | unknown | | 3.8 to 4.3, sill |
| Pump and 420 fans | 140 | unknown | | 3.5, DIMMs |
| Side fans, right and left | 157, 167 | 400 (typical) | 243, 233 | 5.6, GPU hoses; 6.4, card |

Every bend is at its minimum or above. No two routes overlap; the closest pairs lie 0.4 to 0.6 mm apart in the gap.

**The failures.**
- `owner`: the 12V-2x6 cable stands **10.4 mm in front of the front plane Y 0**. The arch cannot be lower: the socket's mouth at n 137, the plug 13, the 35 mm straight and a 35 mm bend put its top at n 220, and the card's face looks forward and up. The owner decides between accepting it (as with the fan screw head) and a 90-degree plug, which would keep the cable inside. The real card's face is probably about 7 mm lower than the model's, which would take most of the 10.4 mm away; the ruler measurement settles it.
- `skeleton`: USB 3 and USB-C pass 1.93 mm from the board's bottom edge and 2.65 mm from the sill. The gap there is 12.6 mm and an 8 mm cable wants 14. The sill's cable slot fixes this.

**Where the build departs from the spec**, each for a measured reason:
- Order in the gap from low u: USB 3 (u 163.5), 12V-2x6 (184), ATX (224.5), EPS 1 (255), EPS 2 (275). The spec put the 12V-2x6 first; JUSB3 at u 160 would then have to cross it. The window is u 158 to 282 and the cables use 112 of its 124 mm.
- The 12V-2x6 is a slab only below n 53. Beside the 360 it has to stay round and at u 173; an S-bend then takes it to u 184.
- USB-C needs no notch in the rail. The rail's top is at n -6, not 0, so the cable makes a U-turn in the board's plane over the rail and comes down in the gap at u 84. The cable is exactly 3.00 mm from the card's assumed underside (n 11): no margin on that assumption.
- The lanes under the board run at X 113, inside the ribs, stacked in n, because the rib has diagonal members at X 142 to 158.
- The right side fan's lead crosses the board's edge at u 287, beyond EPS 2. The first pass's route ran into the new ATX and EPS hooks.
- Two checks were added: a PSU cable keeps 3 mm from the PSU after its socket leg, and the 12V-2x6 keeps 3 mm from the card after its first bend.

**Margins that are inside the model's error.** EPS 1 has 8 mm to spare, the 12V-2x6 16 mm and EPS 2 17 mm. The PSU's socket positions are inferred from a photo and the 12V socket from a render, so these three are not proven. Next: read the PSU's modular face from a photo and choose the sockets nearest the right edge.

What the skeleton has to provide is listed with coordinates at the end of `cad_b6/report_cables.txt`: the sill slot (USB 3 at X 60, USB-C at X 70, power switch X 82, audio X 48, light line X -125), no rail notch, and the clip points.

### Still needed from the owner

1. Does the front USB-C port work in the present PC?
2. One ruler measurement on the card: from the bracket end of the lettering face to the centre of the power socket, and how deep the socket sits below that face.
3. When the PC is apart: the lengths of the front I/O cables.

### After the second pass

The parts the skeleton needs for cables: the cable slot in the sill's rear wall, the rail notch if the USB-C route needs it, nylon clips and their insert pilots.
