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

### Needed from the owner before the next pass

1. The real length of the ARCTIC hoses, pump collar to radiator fitting.
2. Where the power socket sits on the graphics card, and how its radiator fans and pump are wired.
3. Whether the front USB-C port is connected to the board today.
4. When the PC is apart: the lengths of the front I/O cables.

### Next pass

Routes redrawn with the fixes in the table, the 12V-2x6 route once its socket is known, then the parts the skeleton needs for cables: a cable slot in the sill's rear wall, nylon clips and their insert pilots.
