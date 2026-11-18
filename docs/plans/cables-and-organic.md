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

### After the hoses moved (450 mm, 15 Nov 2026)

The CPU hoses now run 30 mm lower, at n 131 and 140. The layer still passed its own checks, but the strength run did not: 5 of 320 pushes were over the allowable. Two causes, both found by building the layer with the old hoses and comparing the fields:

- The hoses now cross between the left fan ring's top and the side bone, at u 141 to 170. They cut two threads of that film (3.7 cm³ lost), and the ring's upper front corner went from 11 to 20 MPa.
- The threads between the card bone and the lip dipped 20 mm to pass under the old hose run. The hoses now lie below that surface and notched the dipped threads (24 MPa).

Changes in `organic_frame.py`: the left card-to-lip film passes over the hoses (sag 4 mm, as on the right); the left ring-to-side-bone film starts at u 186, past the hoses (`TOP_FILM_L_U0`); two ties hold the left ring (`ring_tie_L` from its upper front corner to the end of the front sweep, `ring_tie_L2` from its upper far corner to the lower end of the side bone).

Result: 1 push of 320 over the allowable, the same right rear window thread as before (17.6 MPa at X 178, Y 284, Z 146). The left ring's worst case is now 6.9 MPa. Volume 1843 cm³ (2.3 kg solid PLA), one piece, 12 pads, all checks pass. Lesson for later hose or hardware changes: rerun `organic_strength.py`, the layer's own checks do not see a notched thread.

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

**Margins that were inside the model's error.** EPS 1 had 8 mm to spare, the 12V-2x6 16 mm and EPS 2 17 mm. Settled later the same day: see "The PSU's modular face" below.

What the skeleton has to provide is listed with coordinates at the end of `cad_b6/report_cables.txt`: the sill slot (USB 3 at X 60, USB-C at X 70, power switch X 82, audio X 48, light line X -125), no rail notch, and the clip points.

### Owner decisions (15 Nov 2026, second round)

- **The 12V-2x6 cable in front of the front plane is accepted as a tolerance.** Measured 10.4 mm; `hardware.GPU12V_FRONT_TOL` is 11. Going past it is a route failure. Do not raise it again.
- **The front USB-C port works in the present PC** with this board and this card. So a lying plug fits under the card. The 11 mm in `GPU_UNDERSIDE_N` is still an assumption, not a measurement.
- The ruler measurement of the power socket and the front I/O cable lengths come when the PC is apart.

`cables.py` now fails 4 checks, all of class `skeleton`: the two front USB cables at the sill.

### Still needed from the owner, when the PC is apart

1. On the card: from the bracket end of the lettering face to the centre of the power socket, and how deep the socket sits below that face.
2. The lengths of the front I/O cables.

### Skeleton pass 1 for cables and the organic layer: spec

Two changes to the skeleton. Both are small and neither waits for the owner.

**A. Cable window in the sill's rear wall** (`front_sill`, `frame_v0.py`).
- One window through the rear wall (`SILL_REAR_WALL`, 5 mm) for the front cables: X 40 to 90, Z 14 to 46. It follows the pocket: give it as offsets from `hw.FRONT_IO_W` and the sill's own numbers, not as bare coordinates, so it moves with the module when the real one is measured. A second small window for the light line's lead at the left end, X -131 to -119, Z 34 to 46, if the channel's end does not already let the lead out; say which.
- Corners rounded as the rounding rules allow. The module's screw inserts keep their walls. The window is a placeholder like the module itself: mark it so in the code and in the report.
- Then move the first way-points of the USB 3 and USB-C routes in `cables.py` so that they pass through the window and keep 3 mm from the board's bottom edge and from the sill. Remove the `skeleton` allowance from `classify` once nothing needs it: after this pass every failure is a `route` failure and the script must exit 0.

**B. Insert pilots for the organic layer's twelve pads.**
- `hardware.py` gains `ORGANIC_PADS`: name -> (part name, pad centre world (X, Y, Z), the outward normal's sign along X). The twelve rows are the table in `cad_b6/report_organic.txt` as it stands now.
- `frame_v0.py` cuts an M3 insert pilot (`pilot(..., "M3")`) at each, along X into the part, and counts them in the fastener bookkeeping. Every existing check must hold, check 7 (walls) in particular. If a pilot cannot keep its wall, move the pad the least distance along the face that gives it, change the row, and say so.
- `organic_frame.py` takes its pads from `ORGANIC_PADS` and gains a check: each pad's screw axis coincides with an M3 pilot of that part within 0.01 mm. `pad_fits` must not count a pad's own pilot as "another hole too close"; every other hole still counts.
- Rerun `organic_strength.py` afterwards (main session, on the gaming PC).

Not in this pass: cable clips. They come after the PSU's sockets are read from a photo, because that may move the lanes.

### Skeleton pass 1, built (15 Nov 2026)

Checked in the main session: `frame_v0.py` passes, `test_checks.py` 108 of 108 (16 new cases), `cables.py` exits 0 with no failed check, `organic_frame.py` passes with its new check, `fit_gauges.py` passes.

- **Cable window:** X 40 to 90, Z 14 to 46, through the sill's rear wall, corners R 8. It is tied to `hw.FRONT_IO_W` and moves with the module (a test shifts the module 10 mm and the window follows). It is a placeholder like the module. The light line needs no window: its channel is open at both ends of the sill.
- **USB 3 and USB-C** now start on the module's rear face and go through the window: 6.6 mm from the sill, 5.6 mm from the board's bottom edge. With the window filled back in they hit the sill, so the window is what makes them pass. The `skeleton` and `owner` failure classes are gone from `cables.py`.
- **Twelve M3 insert pilots** for the organic layer's pads are cut in rib A, rib B, the necks and the sill's ends. No pad had to move. Smallest wall left 4.3 mm (front feet); 1.6 is the minimum. `hardware.ORGANIC_PADS` is the only place the pad positions live; `organic_frame.py` checks that each pad's screw axis lies on its pilot within 0.01 mm.
- **Organic strength not rerun:** the gaming PC could not be reached (its SSH host key changed, so it is probably booted into Windows). The layer changed by 0.1 cm³ (1842.7 to 1842.8), so the last result stands for now. Rerun when the PC is back.

Found on the way, not changed:
- The light line's route starts at X -125 behind the sill; the real lead leaves the channel's mouth at X -140 and goes round the sill's end.
- Each `sill_end` pad's rim overlaps the light channel's mouth by under 2 mm³.
- Nothing checks the window's rounding: the sill is outside check 12.

### The PSU's modular face, read from a photo (15 Nov 2026)

Source: a straight-on photo in the Vortez review (`refs/psu_tx1600_modular_face.jpg`, local only), taken label side up, so fan down. The PSU stands fan up in the case, so the photo is turned half a turn. Scale: 9.73 px/mm across the 150 mm face, 6.9 px/mm over its 86 mm height (the camera looks down a little). Accuracy about +-3 mm in X and +-5 mm in Z.

Seen from the front of the case, fan up, world X and Z on the face Y 165:

| Field | Sockets |
|---|---|
| MB | A 10-pin and an 18-pin socket side by side, X -5 to 56, centre X 26, Z 28. The 24-pin cable ends in both |
| CPU/PCIe | Nine 8-pin sockets, three columns X -19, -37, -55 by three rows Z 29, 49, 67. An EPS cable fits any of them |
| 12V-2x6 | Two, at X 1.5, Z 49 and Z 67 |
| Peripheral | Six, X about 10 to 55, Z 49 and 67. Not used |

Against the model's old numbers: `mb` was (48, 43), now (26, 28); `eps1` and `eps2` were (-52, 30) and (-36, 30), which are two real sockets of the bottom row; `gpu` was (0, 43), the real ones are at Z 49 and 67.

**Third cable pass, built (15 Nov 2026).** `hardware.PSU_SOCKET_FIELD` holds the field, `PSU_SOCKET_USE` names the sockets in use. Checked in the main session: `cables.py` exits 0 with no failed check; `test_checks.py` 108 of 108 (the subagent's run).

| Cable | Socket (X, Z) | Route before, after | Real | Spare before, after |
|---|---|---|---|---|
| ATX 24-pin | MB (26, 28) | 532, 517 | 610 | 78, 93 |
| 12V-2x6 | upper 12V-2x6 (1.5, 67) | 684, 670 | 700 | 16, 30 |
| EPS 1 | CPU/PCIe column 1, row 2 (-19, 49) | 692, 649 | 700 | 8, 51 |
| EPS 2 | CPU/PCIe column 1, row 1 (-19, 29) | 683, 669 | 700 | 17, 31 |

The smallest spare is 30 mm now. That is more than the photo's error, but the 12V-2x6 socket on the card is still good only to about 12 mm, so its 30 mm is not a wide margin until the ruler measurement. The lanes, the order in the gap and everything above the board are unchanged. The ATX cable really ends in two plugs side by side (X -5 to 56); it is modelled as one round bundle from their centre.

### Cable fixing: tie points, not per-cable clips (decision of 15 Nov 2026, main session)

The routes are drawn to the millimetre, but a real cable will lie centimetres from its drawn line: the front I/O lengths are unknown, the sockets are read off pictures, and sleeved wires take their own set. A clip printed for one cable at one drawn point would be false precision. So the skeleton gets **rows of general tie points**, and one small printed part fits all of them.

- **Tie point:** an M3 insert pilot in a skeleton face.
- **`tie_bridge`:** one printed part, PA6. A foot with an M3 clearance hole and, beside it, an arch that a 12 mm hook-and-loop strap or a cable tie passes under. About 30 x 14 x 9 mm. One at every tie point. It is its own printed part in the parts list, with its material, and takes part in every check like any other part.
- **Rows** (the builder finds the exact places; each must keep every check, check 7's walls in particular, and the cables must keep their 3 mm from every bridge):
  1. Under beam_mid, on its underside, four points across the right half (about X 60, 85, 110, 135): the lanes pass below it.
  2. Under the right rib's rail, on its underside, five points from u about 150 to 280: beside the place where the cables rise into the gap.
  3. Under beam_low, two points at about X 60 and 85: where the front USB cables dive under the board.
  4. Under beam_top, two points on the right half: for the EPS pair before it rises.
- If a point cannot be placed (walls, a hose, a cable in the way), move it along its row; if a row cannot be placed at all, say so and leave it out. Do not move a cable to make room unless there is no other way, and then say which.
- `cables.py` reports, for every PSU cable and the two front USB cables, the distance from the route to its nearest tie point and the longest stretch of route that has no tie point within 60 mm. No pass or fail on these two numbers in this pass: they show whether the rows are in the right places.

### Tie points, built (15 Nov 2026): eleven, and the EPS pair is not served yet

Checked in the main session: `frame_v0.py` passes, `test_checks.py` 124 of 124 (16 new cases), `cables.py` exits 0, `organic_frame.py` passes. `strength.py` has not been rerun with the bridges in the parts list.

- **`tie_bridge`:** 28 x 13 x 9 mm, PA6, about 2 g. A 3 mm foot with an M3 clearance hole and an arch over a 12.5 x 3.5 mm slot for the strap. Prints foot down; the slot's roof is a 12.5 mm bridge. Screw M3 x 10.
- **Eleven tie points:** three under beam_mid (X 20, 52, 84), four under the right rib's rail (u 72, 103, 185, 216), two under beam_low (X 60, 90), two under beam_top (X 77, 109). A new check, 3b, holds each bridge on its pilot, touching only its host and 2 mm from everything else. Every cable keeps at least 4.3 mm from every bridge.
- **Departures from the spec, each measured:** a 28 mm bridge does not fit a 25 mm pitch; USB 3 runs 8.5 mm under beam_mid, so no bridge can sit above its lane; the rail's underside is taken at u 141 to 172 by the rib's mid leg and past u 250 by rib B's lap, so the rail row is four points in two groups.

| Cable | Nearest tie point | Longest stretch below the board with no tie point within 60 mm |
|---|---|---|
| ATX 24-pin | 18 mm | 30 mm |
| 12V-2x6 | 25 mm | 54 mm |
| EPS 1 | 27 mm | **218 mm** |
| EPS 2 | 22 mm | **301 mm** |
| USB 3 front | 22 mm | 0 |
| USB-C front | 21 mm | 0 |

**The rows in the spec were in the wrong places for the EPS pair.** Their lanes lie 80 to 120 mm under the beams (n -106 and -147.5), where no bridge on a beam reaches. Measured nearby faces: rib B's inner face is 10 to 23 mm from EPS 2 and 13 mm from EPS 1; `skid_front`'s front face is 20 mm under EPS 2. Next: a row on the inner face (X 142) of rib B's post and runner and of rib A's mid leg, with the bridge standing out along -X.

Also found: under the beams the bridge has to lie across the cables' direction, so the strap takes a quarter turn round the cable; `render_vtk.py` has no view that shows the bridges.

### Owner's direction on cable fixing (16 Nov 2026)

The owner will use hook-and-loop straps. The tie points have to **give each cable its shape**; a strap lets a cable shift a little, so the cables need not lie exactly on the drawn lines. This keeps the strap bridge and changes where the tie points go: at the places that shape a cable, not in general rows.

### Tie points, second pass: spec

**Rule, now a check in `cables.py`** (pass or fail), for the four PSU cables and the two front USB cables, on the part of each route below the board (n < -2):
1. Every bend of 30 degrees or more has a tie point within `TIE_REACH` = 30 mm of some point of its arc (centre line to the middle of the bridge's slot).
2. No stretch longer than 150 mm is without a tie point within `TIE_REACH`.
A cable's two plugs count as fixed points. Above the board nothing is required: the hooks are short and the 12V-2x6 arch hangs between its plug and the gap.

**Where the new tie points go** (measured in the last pass; the builder finds the exact places):
- Down the inner face (X 142) of rib A's mid leg, bridges standing out along -X: the leg runs from the rail down to n about -110 and passes each of the four upper lanes (USB 3, 12V-2x6, ATX, EPS 1) at the lane's own level.
- On the inner face of rib B's post and runner, for the EPS pair before and at its rise (EPS 1 is 13 mm from it at u 241, EPS 2 10 to 23 mm at u 252 to 275).
- On `skid_front`'s front face or another face in reach, for the EPS pair where it passes the PSU's front right corner.
- Wherever a face allows it, turn the bridge so the strap goes round the cable without a twist.

**Tie points that shape nothing go.** Remove every existing tie point that has no cable within `TIE_REACH`, and say which.

If a bend or a stretch cannot be served from any face, first move the cable's way-points (the routes are allowed to shift: every other cable check must still pass), and only if that fails propose a small hanger part and stop on that item for a decision. Do not loosen the two numbers.

### Tie points, second pass, built (16 Nov 2026): every cable is shaped

Checked in the main session: `frame_v0.py` passes, `test_checks.py` 136 of 136, `cables.py` exits 0 with the two new tie checks, `organic_frame.py` passes; the view `previews/b6_cables_under_board.png` was looked at.

Eleven tie points again, but different ones. Removed, because no cable came within 30 mm: two under beam_mid (X 20, 52), one under the rail (u 72), one under beam_top (X 77). Moved: `low_2` to X 102. Added: `leg_1` and `leg_2` on the inner face of rib A's mid leg, `post_1` on the inner face of rib B's post, `skid_1` on top of `skid_front`.

| Cable | Bends of 30 degrees or more below the board: distance to the nearest tie point | Longest stretch without one |
|---|---|---|
| ATX 24-pin | 28.0, 24.5 | 105 mm |
| 12V-2x6 | 24.4, 25.0 | 116 mm |
| EPS 1 | 28.8, 28.9, 28.5 | 106 mm |
| EPS 2 | 27.7, 29.0 | 139 mm |
| USB 3 front | 22.3, 24.1 | 73 mm |
| USB-C front | 19.3, 22.9 | 37 mm |

The limits are 30 mm and 150 mm. Each cable's first bend sits at its PSU plug, which counts as a fixed point.

- One way-point moved: EPS 1's lane start, from X 113 to X 122. Its route went from 649 to 652 mm (spare 51 to 48).
- Five bends are within 1.5 mm of the 30 mm limit. That comes from where the faces are.
- **`skid_1` overhangs.** `skid_front`'s front face is too low for a bridge, so the bridge sits on the skid's top with 12.5 mm of its foot past the front edge. Hand check, main session: a 20 N pull on the strap gives 14 MPa in the 13 x 3 mm PA6 foot and about 50 N on the screw. That is acceptable for a strap; it is not tested.
- The ATX and 12V-2x6 routes begin their first bend right at the PSU socket (148 and 128 degrees). A real cable wants a short straight there first; not modelled.
- The strap takes a twist at most points: a face allows one direction for the bridge, and the cable passes at 28 to 90 degrees to it.

### Bridge material: ABS, not PA6 (16 Nov 2026)

The owner asked whether hook-and-loop straps remove the need for nylon. For the cables they do. PA6 was chosen for parts that snap or flex; a `tie_bridge` only gives the strap a slot to pass through. All eleven bridges are ABS now, the shape is unchanged. `frame_v0.py` passes, `test_checks.py` 136 of 136.

- **Hand check, `skid_1`:** the 13 x 3 mm foot overhangs by 12.5 mm. A 20 N pull on the strap gives 14 MPa along the layers. Printed ABS holds about 35 MPa along the layers, so the margin is 2.4. Not tested.
- **PA6 that is left:** the two hose guides. Their mouth is 0.75 of the hose diameter and the lip is about 2 mm, so the guide has to give when the hose goes in. Open point for the owner: an open channel closed by a strap would remove PA6 from the project (no drying, no dry box). Not changed without the owner's word, since PA6 for the guides was the owner's decision.

### Whole-design pictures (16 Nov 2026)

`cad_b6/render_full.py` draws everything in one scene: skeleton, hardware, hoses, cables, organic layer. It reads the layer from `out/organic/field.npz`. Output: `previews/b6_full_sides.png` (six parallel views at one scale), `previews/b6_full_corners.png` (four corners), `previews/b6_full_inside.png` (four corners without the layer, cables in their report colours).

### Rear panel and drive bays (owner proposal, 16 Nov 2026): measurement

The owner proposes an organic panel at the rear, where the PSU is, and places for HDD and SSD drives there.

**Measured** on a 1.5 mm voxel grid of skeleton, hardware with keep-outs, the six thick cables and the organic layer, every body grown by 3 mm, plus 30 mm of air above the PSU's fan (my assumption). The five thin leads (ARGB, audio, three fan leads) have no solid and are not in the grid.

- **Beside the PSU, both sides:** free X 79..138 (59 mm), Y 178..373, Z 3..169, and standing room up to Z 209 from Y 206 on. The right side is free from Y 194 on; in front of that the cables leave the PSU.
- **Above the PSU:** free X -138..139, Y 188..375, Z 117..about 190, rising to Z 274 at Y 330.
- **A 3.5 inch drive** (101.6 x 147 x 26.1, plus 20 mm for plugs) fits beside the PSU on its long edge on either side, and flat above the PSU. Two side by side on one side do not fit: 52.2 of 59 mm.
- **A 2.5 inch drive** (69.85 x 100 x 7, plus 20 mm) fits almost anywhere in those zones.
- **Rear face:** `psu_bulkhead` closes the rear from the desk to Z 92 across X -142..142 and holds the PSU. Above it the rear is open up to the board's underside.

**Concept, main session, not built:**

- **Two drive sleds, one on each side of the PSU.** ABS, because the PLA layer carries no component. A sled is a vertical plate along Y with both hole patterns: one 3.5 inch drive, or two 2.5 inch drives one above the other. Capacity: two HDDs, or four SSDs, or one HDD and two SSDs.
- **Plugs face forward**, towards the PSU's modular face and the board's right edge, where the SATA ports are (to be confirmed by the research).
- **Rear organic panel** as its own piece of the PLA layer, screwed with M3 to pilots in the rear faces of the B ribs and the bulkhead. It covers the open rear above the bulkhead and the flanks beside the PSU. It leaves the PSU's window open and keeps 10 mm from the PSU. The field's grid ends at Y 394, so the panel has Y 383..392.

**Open points:**

- **Getting a drive in and out.** The bulkhead blocks the way straight back below Z 92, and it is structural. The sled has to go in through the rear opening above the bulkhead and down, or from the side through rib B. This needs a swept check, not a guess.
- **PLA near a hard drive.** A 3.5 inch drive runs warm. Proposal: PLA keeps 10 mm from a drive, as from the card and the PSU.
- **Vibration.** Rubber grommets between drive and sled.
- **SATA cables.** Two more cable kinds (data from the board, power from the PSU) to route and tie.
- **How many drives the owner has** decides nothing in the concept above, only which holes get used.

### Correction: the right side is not free (16 Nov 2026)

The measurement above was wrong on the right side. My scratch grid held no cables at all: a route's solid is `None` until `build()` is called, so every route was skipped, not five thin leads. `cad-implementer` found it when `cables.py` failed against the right drive; the main session measured again with the cables in the grid (as polylines thickened by their radius, the way `drive_access.py` does it).

- **Right of the PSU:** ATX, EPS 1 and EPS 2 run through the pocket (X 62..153, Y 200..356, Z 21..288). No drive fits there without rerouting three cables.
- **Left of the PSU:** free as measured; the left bay is more than 40 mm from every cable.
- **Above the PSU**, with 30 mm kept over its fan and the left bay taken: a 3.5 inch drive still fits flat (within X -75..115, Y 188..377, Z 117..169) or standing across the very rear (within Y 342..377, from Z 117 up). 2.5 inch drives fit flat there too.

Decision, main session: **one bay, on the left.** It holds one 3.5 inch or one 2.5 inch drive on its outer face and one 2.5 inch drive on its inner face. The cables took several passes to settle and their smallest spare length is 30 mm, so they are not rerouted for a second bay. A second 3.5 inch place above the PSU's rear end is possible and is the owner's call.

Lesson for the next measurement: assert that every layer of an occupancy grid is non-empty before trusting it.

### Drive bays: research result (16 Nov 2026)

Grok, `web-research`, checked in the main session against the numbers of the standards.

- **3.5 inch, SFF-8301 Rev 1.9:** 101.60 wide, 147.00 long at most, 26.10 high at most. Bottom holes 6-32 UNC: two columns 3.18 from each side edge (95.25 apart), at 41.28, 85.73 and 117.48 from the connector end; the pair at 41.28 is always there, and one of the other two. Side holes at 28.50 and 130.10 from the connector end, 6.35 above the bottom face. A screw enters 2.39 to 3.56 mm.
- **2.5 inch, SFF-8201 Rev 3.4:** 69.85 wide, 100.45 long at most, 7.00, 9.50 or 15.00 high. Bottom holes M3: two columns 4.07 from the side edge (61.72 apart), at 14.00 and 90.60 from the connector end. Side holes at the same stations, 3.00 above the bottom face. A bottom screw enters 2.50 mm at most. The standard lets a 7 mm drive leave its bottom holes out; drives on sale have them.
- **SATA connector, SFF-8323 and SFF-8223:** on the connector end, starts 13.43 from one side edge, 42.73 long, about 3.5 above the bottom face.
- **Plug depth and cable bend behind a drive:** not found. 25 mm is this plan's assumption.
- **Board:** four SATA ports. Read off `refs/board_scan_overlay.png` in the main session: two stacked pairs on the right edge (v 229..244) at u 23..57, openings facing off the edge. Four M.2 slots.
- **PSU:** the Noctua Edition sheet lists 16 SATA connectors on 950 mm cables. Two reviews give 510 mm to the first connector and 155 mm between connectors, four per cable. The socket each cable uses is not documented.
- **Temperature:** 3.5 inch drives 60 to 65 C at most, 2.5 inch SSD 70 C. Seagate allows any mounting orientation and asks for four screws.
- **Rubber grommets:** nothing dimensioned found.

### Drive bays: which way the drive goes in (16 Nov 2026)

Checked with a sweep in three degrees of freedom (Y, Z, tilt about X) on the voxel grid, 1.5 mm margin. The bulkhead's top is at Z 92, the board's underside rises at 45 degrees from the front, and `beam_mid` closes the pocket's front top corner.

| Sled with drive, seen from the side | Result, both sides |
|---|---|
| Lying on its long edge, plugs forward, 181 x 108 | no path |
| Lying, 171 x 105 | left: path with 30 degrees of tilt; right: the seat is blocked by cables |
| Standing on its far end, plugs up, 120 x 150, in X 78.5..120 | path, tilt up to 30 degrees |
| The same with plugs attached, 120 x 175 | path, tilt up to 30 degrees |
| Standing, a plate 150 or 160 long for two 2.5 inch drives side by side | no path |

Decision, main session: **the drive stands on its far end with the connector end up.** The plugs are then at the top, next to the rear opening, and can be put in after the sled is seated.

### Drive bays, pass 1: spec for `cad-implementer` (skeleton and hardware)

**Changed after the correction above: one sled, on the left only.** The text below is the spec as it was given.

**Goal.** Two drive sleds, one on each side of the PSU, each holding one 3.5 inch drive or one 2.5 inch drive on its outer face and one 2.5 inch drive on its inner face. Capacity: two HDDs and two SSDs, or four SSDs.

**Hardware facts, into `hardware.py` only**, with the standard named beside each: the two form factors (body, bottom holes, side holes, screw penetration), the connector's place, the plug zone of 25 mm marked as an assumption.

**Envelope.** Everything of a bay (sled, drives, plug zones) stays inside |X| 78.5..120, Y 248..375, Z 0..178. This is the volume the sweep proved free and reachable. The left bay is the right one mirrored in X.

**Arrangement, right side** (outer face looks to +X):

- The drive's bottom face (its board) lies against the sled. Connector ends of all drives are at the same height, at the top.
- From the PSU's side (X 75) outwards: 4 mm of air, the inner 2.5 inch drive (7 mm), the sled, the outer drive (26.1 mm for a 3.5 inch).
- The outer face takes the 3.5 inch pattern (all six bottom holes) and a 2.5 inch pattern. The inner face takes a 2.5 inch pattern.

**Part `drive_sled_right`, `drive_sled_left`, ABS.**

- **Plate** 5 mm, in the YZ plane. A boss 1 mm high round every drive screw hole, on the face where that drive sits, so the drive's board does not lie on the plate.
- **Drive screw holes:** clearance for 6-32 and for M3, each counterbored from the opposite face so that 3.0 mm of material is left under the screw's head. A 6-32 x 6.35 mm drive screw then enters the drive 3.35 mm (allowed 2.39 to 3.56). An M3 x 5 enters 2.0 mm (allowed up to 2.5). The heads sit below the face, so a drive on that face can lie over them. Counterbores of different patterns keep a wall between them; place the patterns so that they do.
- **Rear flange:** a block at the plate's rear end against the bulkhead's front face (Y 375). Two M4 screws from behind, through two new clearance holes in `psu_bulkhead`, into inserts in the flange. The holes sit in the bulkhead's flank (|X| 80..118), clear of the PSU's screws, the window and the end blocks, by the skeleton's own wall rules.
- **Foot:** the plate's lower end stands on `skid_rear`'s top face (Z 0) with a face, not an edge.
- Rounded by the skeleton's rules; what stays sharp is listed in the report as usual.

**Assembly order, into the report's notes:** on a sled that carries both a 3.5 inch drive and an inner 2.5 inch drive, the inner drive is screwed on first, because its screw heads end up under the 3.5 inch drive.

**Hardware entries.** `drive_right`, `drive_left`: the largest occupants (a 3.5 inch body on the outer face and a 7 mm 2.5 inch body on the inner face). The plug zones above them are keep-outs. They are drawn in the previews and take part in every check: parts, cables (3 mm), and the organic layer keeps `PLA_GAP` (10 mm) from a drive, as from the card and the PSU.

**Checks.**

- The existing clearance, contact and fastener checks, with the new intended contacts (sled on `skid_rear`, flange on the bulkhead, drive on the sled's bosses) and the new fastener rows.
- New: every hole pattern on a sled agrees with the table in `hardware.py`, and the material under each head gives a screw penetration inside the standard's limits.
- New script `cad_b6/drive_access.py`: the sweep above as a check. Obstacles are the skeleton without the sled, the hardware without that bay's drive, the cable solids and the organic field, grown by 1.5 mm. The moving body is the bay's envelope seen from the side, once without and once with the plug zone. It fails if the seat cannot be reached from behind the case with at most 30 degrees of tilt. Working reference code is in the main session's scratch folder (named in the task).
- `test_checks.py` gains cases that prove the new checks bite (a hole pattern shifted, a seat too thin, an obstacle in the way of the sweep).
- `cables.py`, `organic_frame.py`, `fit_gauges.py` still pass. If the organic field changes, say by how much and why.

**Not in this pass:** SATA cable routes, the rear organic panel, rubber grommets.

### The organic layer is printed in ABS (owner's decision, 16 Nov 2026)

The owner prints the organic layer in black ABS as well, because ABS costs less than PLA now.

- **What gets simpler:** skeleton and layer shrink alike, and heat near the card and the PSU stops being a limit. The 10 mm gaps stay as drawn; nothing is moved closer.
- **Strength.** Under a given push the stress does not depend on the stiffness, so the PLA run still gives the stresses. The allowable falls from 12.5 MPa (PLA, 25 across the layers, safety 2) to 10 MPa (ABS, 20 across the layers, the figure `strength.py` uses). Read off `report_organic_strength.txt`: 2 of 320 pushes are over 10 MPa (17.6 and one more among the ten worst listed) where 1 was over 12.5. Deflections grow by about 1.4 (E 2000 against 2800). A rerun with ABS numbers waits for the gaming PC.
- **Printing.** ABS warps more on long thin members and prints overhangs worse than PLA. A white PLA trial does not show either, so one piece of the layer with long threads is an early ABS trial.
- **To do in the code after Revision 11:** `organic_frame.py` and `organic_strength.py` name PLA, use its density and modulus, and call the gap `PLA_GAP`; the skeleton report's material paragraph; the mass of the layer (1843 cm3 is 1.92 kg of solid ABS).
- The light line's diffuser stays translucent PLA, with its 10 mm air gap to the LED strip.

### PETG for the organic layer (16 Nov 2026)

The owner asked about PETG and ordered 4 kg of black SUNLU Rapid PETG. Main session's reading of that: the organic layer is printed in PETG, and ABS stays the fallback if a trial piece with long threads strings too much. The skeleton stays ABS for heat and creep next to the radiators and the PSU.

- Strength is judged with the ABS figures (E 2000 MPa, 20 MPa across the layers, safety 2, allowable 10 MPa). They are on the safe side for PETG, whose layers bond better.
- The gaming PC answers again (`ssh gamepc-linux`, 20 cores, 125 GB). The organic strength run follows Revision 11's second pass, which may move the field by the millimetre the 420's fans gain.

### Next

Drive sleds and the rear panel, once the research is back: spec, then `cad-implementer`. Split the organic layer into printable pieces (the rear panel is one of them). Rerun `strength.py` with the bridges. Rerun the organic strength check when the gaming PC is back in Linux.

## Revision 14b — the organic layer's flanks redrawn for the moved fans (17 Nov 2026)

**Why.** Revision 13 moved the side fans out to |X| 235..260 and added two plug zones on the left (`io_zone`, `gpu_out_zone`). The layer was drawn for the old fans and is cut at |X| 229, so both fan rings are gone from the solid, twelve of 320 pushes are over the allowable where the flank films now end in the air, and 2.7 cm³ of the layer stand in `gpu_out_zone`. The owner's aim on the left flank: plugs go into the board's rear connectors and the card's outputs, and their cables leave to the rear behind the left fan.

**Map of the present code** (Grok `code-analysis`, 17 Nov 2026, numbers not re-measured by the main session): `build` in `organic_frame.py:517` is the whole shape; the |X| clip is at `organic_frame.py:550`; `io_zone` is in the carve list at `:537` and `gpu_out_zone` is not; rings follow `hw.FAN_SIDE_X` already (X 250 and -247.5); `REAR_BEND_X`, the `rear_sweep` literals 204, 202, 196, and `side_bone`'s |X| 190..209 are still the old fan band; `RING_TOP` 18 on the right refers to a bracket rail that no longer exists; `RING_L_GAP` (26, 94) and `rear_L`'s start at n 24 were drawn round the CPU hose guide on the left neck, which Revision 14a moves to the fan's corner D.

### Revision 14b: spec for `cad-implementer`

Work only in `cad_b6/organic_frame.py`, `cad_b6/organic_strength.py` (constants only), `cad_b6/zone_access.py`, `cad_b6/test_checks.py` (new cases only) and the layer's reports and previews. Do not change `hardware.py` or `frame_v0.py`: Revision 14a is editing them at the same time in another checkout. The twelve pads stay where they are.

**1. Let the flanks reach the fans.** The |X| clip becomes `hw.ENVELOPE_FAN_X` (260). Nothing of the layer may pass it.

**2. The rings.** Both rings are closed loops round their fan and mirror each other: same offset, same top, no gap on the left, no arch on the right (the reasons for both are gone: the bracket rail, the hose guide on the neck, the card's hoses next to the old right fan). The ring's surface keeps `GAP_HW` from the fan box without being notched by the carve, so the offset grows from 10 to at least `BONE_R` + `GAP_HW` + 0.5. A ring that the carves bite (`bitten`) is a failure of the script from now on, for the rings only.

**3. The bones that still stand in the old fan band** (`side_bone`, `rear_sweep` with `REAR_BEND_X`, the ring ties, the films `flank_near`, `under_fan`, `top`, `rear_window`) are redrawn so that every one of them ends on a bone at both ends and none ends at a clip. Where a number was an old fan coordinate, derive it from `hw.FAN_SIDE_X` or name it as the layer's own. Left and right are mirror images except where a rule below needs a difference on the left; say in the report where they differ.

**4. The left flank stays open for plugs and cables.**
- `gpu_out_zone` joins the carve list with the same gap as `io_zone`. The layer's volume inside each of the two zones is 0.
- With the layer counted as an obstacle, a bundle 40 mm across leaves each zone to the rear plane inside the hull (`zone_access.py`; today it tests 20 mm). Report the widest that gets out.
- A hand reaches the board's connectors: with the layer, the skeleton, the hardware and the cables as obstacles, a ball 70 mm across gets from outside the left flank (beyond the fan's outer face) to within 50 mm of `io_zone`. Add this to `zone_access.py` as its own function and report the widest ball. If 70 mm cannot be met without removing the left ring or a pad, stop at the largest ball that can and report what is in the way.
- No member may run in front of the card's outputs: nothing of the layer within the prism that continues `gpu_out_zone` outwards to the fan's outer face (v from -138 to -82, the zone's u and n).

**5. Strength.** `organic_strength.py` at step 2 while you iterate (a few seconds), step 1 once at the end if the machine has the memory free (it needs about 15 GB; another agent is running checks; if it cannot run, say so and the main session runs it after the merge). Target: no push over the allowable. If some remain, list them with the member each belongs to.

**6. Checks and tests.** `organic_frame.py`'s own checks gain: nothing beyond |X| 260, both rings whole, zero volume in the two zones and in the prism of item 4. `test_checks.py` gains cases that damage each of those and expect the failure. `zone_access.py`'s existing checks and cases keep passing.

**7. Previews and reports.** Regenerate the layer's previews, `render_full.py`'s sheets, `report_organic.txt`, `report_organic_strength.txt` and `report_zone_access.txt`.

**Not in this revision:** the rear panel round the PSU, the smoothing of the surface, the split into printable pieces.

**Report back:** the numbers asked for above, the layer's volume and mass before and after, where left and right differ, every place the spec was wrong and what you did instead, anything left failing. Commit to your own branch in your checkout when the layer's checks pass; do not push.

### Revision 14b: corrections after Grok's check of the spec against the code (17 Nov 2026)

Where this list and the spec above disagree, this list holds. Revision 14a is finished in the same checkout and not committed yet: the CPU hose guide is already a comb on the left fan's corner D (X -235..-214), and nothing stands on the left neck.

1. **Files.** As above, with one change: new test cases go into a new file `cad_b6/test_organic.py`, not into `test_checks.py` (Revision 14a's changes to that file are not committed yet, and the layer's tests should not need the 20 minute run). Write the layer's checks as functions of a field array, so that a test can damage a copy of the saved field and expect the failure.
2. **The prism of item 4 is wrong as written:** the left fan (u from 120) and the bracket's spine (u 116..122) stand in it, and so would the low-u side of a closed ring. Replace it: the layer keeps out of v -138..-82, u 75.6..100, n 10..100. The ring's low-u side may pass above that (u about 108) at the fan's plane. The film between the ring's near side and the front sweep on the left must not hang in front of the outputs; attach it above n 100 or leave it out on the left.
3. **The hand of item 4:** a ball 70 mm across cannot get within 50 mm of `io_zone` even without the layer; the skeleton and the hardware stop it at 60 mm (measured by Grok on a 2 mm grid, perhaps 64 mm in truth). The requirement becomes: the layer does not make it worse. Report the widest ball without the layer and with it; they must be equal, and not under 60 mm.
4. **`zone_access.py`:** the 40 mm bundle and the hand are new functions with their own report lines. `BUNDLE_D` 20 and the existing cases stay. The hand starts outside the hull (beyond the left fan's outer face), so it cannot use `reach`, which keeps a bundle inside the hull.
5. **The rings.** Offset `BONE_R` + `GAP_HW` + one voxel (12 mm), because a 0.5 mm margin is smaller than the field's 1.5 mm step and the carve would notch the surface. At that offset a closed ring clears every neighbour by more than its radius (nearest: the bracket's bar 13.9 mm from the centre line, the 420's port collars 22 mm on the left, the CPU hoses 27 mm on the left, the card's hoses 32 mm on the right; desk 89 mm, front plane 65 mm). Both rings at the fan's mid-plane (today the right one is 2.5 mm off it). Only a bitten ring fails the script; other bones are bitten today and stay a report line.
6. **Left and right.** The differences the hoses force stay and are listed in the report: the top film on the left starts beyond the CPU hoses (they cross u 141..170), the front sweeps differ, the film under the fan exists on the left only unless the card's hoses now leave room for its mirror.
7. **Other checks that must still pass:** `drive_access.py` (the layer at least 10 mm from a drive), `zone_access.py`, and the pads' own checks. Report the layer's least distance to the two fan leads.
8. **Strength.** `organic_strength.py 2` takes about 9 s and is stiffer than the truth; step 1 takes about 2.5 minutes and about 15 GB. The script reports a push point and a stress point, not a member; name the member by reading the coordinates.
9. **Renders.** `render_full.py` is enough; the Blender scripts read the same field and are rerun by the main session.

### Revision 14b, result and second pass (17 Nov 2026)

**First pass, built and committed as `0c39467`, rerun by the main session:** closed mirrored rings 12 mm off the fans; nothing of the layer in `io_zone`, `gpu_out_zone` or the prism in front of the outputs; a bundle of 52 mm gets out from the board's connectors and 62 mm from the card's outputs with the layer in place (40 mm asked); 0 of 320 pushes over the allowable (12 before), worst 7.5 MPa; volume 1520 cm³ (1640 before). `test_organic.py` 12 of 12.

**What was wrong with it** (the main session's requirement, and Grok's `change-review`):
- The "hand" requirement was written from a figure (a 60 to 64 mm ball) whose route runs under the board and ends 50 mm below `io_zone`, on the wrong side for a hand that holds a plug. To keep that route the implementer opened the left base bone (Y 80..230), lowered and thinned both base bones, moved both rear window films back and left out the film under the left fan. Only the last of these serves a hand that reaches the plugs.
- The second reading, "on the plugs' side", accepts a ball centre anywhere with v <= -50 within 50 mm of the zone, including under the zone's outer corner; it does not ask that the ball stand in front of the plug face. An empty goal gives 0 with and without the layer and passes.
- The test's wall for the hand is larger than the region it is meant to close; the 60 mm floor and the bitten-ring failure have no test.
- The left ring's lower front corner moves 9.6 mm under a 30 N push.

**Second pass: spec.** Files as in the first pass (`organic_frame.py`, `zone_access.py`, `test_organic.py`, the layer's reports and previews).
1. **One hand measure, the right one.** The goal is a ball centre in front of the plug face of `io_zone`: within the zone's u and n ranges, outside its outer face (v below the zone's low-v face), and no further than 50 mm from that face. The start is outside the left flank, beyond the fan's outer face. Remove the "any side" reading and its 60 mm floor: they measure a route no hand can use. The rule stays: the layer does not make the widest ball smaller than the skeleton, the hardware and the cables alone allow; report both numbers. An empty start or an empty goal is a failure, not a pass.
2. **Put back what the wrong route cost,** as long as item 1 and the 40 mm bundles still hold: the left base bone is closed again; both base bones return to their height and radius of before the first pass; the rear window films return to where they started before, on both sides, unless the corrected hand measure shows the left one in the way (then say by how much and keep both flanks mirrored). No film under either fan: the left one is the hand's way up to the plugs, the right one would cross the card's hoses.
3. **Stiffness.** No push of 30 N may move the layer more than 5 mm (step 1 of `organic_strength.py`; today the left ring's lower front corner moves 9.6 mm). Hold that corner without entering the prism in front of the outputs or either zone. If 5 mm cannot be reached, report the best and what stands in the way. Add the largest movement to the strength report's headline.
4. **Tests.** The hand's blocking wall is no larger than the region it closes (a plate across the slot under the fan, inside the fan's footprint), and one case blocks only the plug-face goal. A case with an empty goal expects the failure. A case for the bitten ring. Cases removed with the "any side" reading are named in the report.
5. **Small things from the review:** the bundle's bisection reports the true widest value up to its limit; the ring's X is printed with a decimal.

### Revision 14b, second pass: result (17 Nov 2026)

Built by an Opus child (`688cf3b`), finished and rerun by the main session, re-checked by Grok, fixed (`cf3927a`), regenerated on the merged tree (`65734ac`).

- **Layer:** 1742 cm³, one piece, 12 pads. Both rings closed, mirrored, 12 mm off their fans. The left base bone is closed again, both base bones and the rear window films are back. No film under either fan. A new strut, `ring_tie_L3`, holds the left ring's lower front corner.
- **Zones:** nothing of the layer in `io_zone`, `gpu_out_zone` or the prism in front of the card's outputs. With the layer a bundle of 52 mm gets out from the board's connectors and 56 mm from the card's outputs (40 mm asked).
- **Hand:** a ball has to stand in front of the plug face of `io_zone`, coming in through the left flank (the grid's front, rear and top margins are closed). 50 mm without the layer, 44 mm with it. Recorded as a budget, `HAND_BUDGET_D` = 44: the layer costs the hand 6 mm. Both the closed left ring and the left rear sweep stand in the 50 mm route; which of them sets the 6 mm has not been separated, so opening the rings is not known to give the 6 mm back. The owner confirmed on 17 Nov 2026: the rings stay closed.
- **Strength:** 0 of 320 pushes over 10 MPa, worst 6.5 MPa. Largest movement under 30 N 2.16 mm (limit 5 mm; the left ring's corner moved 9.6 mm after the first pass). `organic_strength.py` now exits 1 when either limit is passed.
- **Tests:** `test_organic.py`, 26 cases.
- **Still open for the layer:** the lumpy surface, and the split of `main` into pieces that fit the 290 mm bed. The rear panel is built (`docs/plans/rear-panel.md`).
- **Trial piece for the print test (PETG; owner's decision of 17 Nov 2026: it is printed in PETG only, and ABS is tried only if the PETG piece prints badly):** `cad_b6/organic_trial.py` cuts the layer round the pad `base_mid_R` and writes `out/organic/trial_base_mid_R.stl` (not tracked) and `previews/b6_organic_trial_base_mid_R.png`. 27 x 110 x 61 mm, 76 cm³, 97 g solid, one closed piece with a flat underside: a stretch of the base bone, the pad with its M3 bore and driver channel, the feet of three film strands. It shows how thin round members, a branch and a screw pad print and how the supports come off. It carries the layer's present surface.
