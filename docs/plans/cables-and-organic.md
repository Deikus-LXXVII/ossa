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

Not started. Waiting for the facts: cable lengths of the Seasonic PRIME TX-1600 Noctua Edition, header positions on the MSI MAG Z890 Tomahawk WiFi, power and fan cabling of the RTX 5080 SUPRIM LIQUID and the ARCTIC Liquid Freezer III Pro 420, and the Fractal North XL front I/O cables. A research task is running. The plan after that: `cad_b6/cables.py` in the manner of `hoses.py` (routes as runs and bends, length check against the real cable, clearance checks), with the space behind the tilted board, above the PSU, as the cable chamber, and nylon clips on the skeleton.
