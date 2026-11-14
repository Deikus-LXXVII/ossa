# PC case B5


Полная передача проекта (цель, история решений, текущая геометрия, как запускать, открытые вопросы) — в [HANDOFF.md](HANDOFF.md). Этот README — краткая справка по текущему варианту B5.

Open, asymmetric, fully printed black-ABS case for a desk showpiece. Volume and clearance study plus organic frame v1 — not a finished case.

Coordinates: X left–right, Y depth (front at 0, increasing backwards), Z up. Millimetres.

## Hardware

| Part | Size (mm) | Notes |
|------|-----------|--------|
| MSI MAG Z890 Tomahawk WiFi | ATX 305 × 244 × 2 | Board at 45°, leaning back. Bottom edge at Y=150, Z=65. Rear I/O at the top edge (~Y 366, Z 281), 45° up and back. |
| ARCTIC Liquid Freezer III Pro 420 | 458 × 138 × 65 (rad + fans) | Stands on its edge in the wedge behind and under the board, above the PSU. Y 353…418, Z 106…244. Tubes 500 mm. |
| MSI RTX 5080 SUPRIM LIQUID | GPU 280 × 148 × 51; 360 rad 394 × 121 × 55 | 360 lies flat in front of the board (Y 29…150, Z 10…65). GPU in the PCIe slot, 45% up the board, 280 mm along X. Tubes 450 mm. |
| Seasonic PRIME TX-1600 | 210 × 150 × 86 | 150 along X (centred), 210 along Y (243…453), 86 tall. Cables at the front, under the board. IEC at Y=453, behind the 420 exhaust. |
| CPU block | ~70 × 70 × 50 | On the board, 70% up from the bottom edge. |

The 360 and 420 were swapped versus B4 so the front is free for buttons and ports. Fan tops of the 360 are level with the board bottom (the 360 sits on a 10 mm plinth; the board stayed at Z=65 because lowering it would make the 420 hit the board).

The 420 does not fit in the old 360 pocket (17 mm taller, 10 mm thicker). It was moved back and up for 15 mm to the board and 20 mm to the PSU top. The case is therefore deeper (~460 mm vs ~405 mm in B4).

## Front I/O

The 360 is 394 mm wide, the 420 sets the width at 458 mm, so about 32 mm is free on each side. I/O lives in those gaps, as part of the cheek, not as a separate box. Overall width stays close to 458 mm plus the frame (rails reach about ±246 mm).

- **Right of the 360:** 19 mm anti-vandal power button with an LED-ring recess, and a 12 mm reset button below it.
- **Left of the 360:** a slim vertical strip — 2× USB-A, USB-C (Z890 Tomahawk JUSBC1, Key-A), and a 3.5 mm combo jack.

## Checks

All pairwise hardware intersection volumes are 0. Main gaps: board–360 contact (by design), board–420 15 mm, 420–PSU 20 mm, 360–GPU 86 mm, 420–CPU 27 mm.

Bounding box of the iron: X −229…229 (458), Y 8…453 (445), Z 0…280.7. Envelope with frame, 15 mm feet and exhaust: about X −246…246 (492), Y 0…460, Z −15…290.

### Tubes (straight-line × 1.3 slack)

Fittings are on the **right**. The right cheek only carries thin power / LED / reset wires, so the AIO tubes stay clear of the USB bundle on the left.

- **CPU → 420**, 500 mm: pass. Around the right board edge needs 328 mm.
- **GPU → 360**, 450 mm: pass. Same-side, right end, needs 179 mm. The path stays in front of the board.

### Front-panel cables

- **JFP1** (power / reset / LED), right cheek → bottom-right header: path 266 mm, need 346 / 500, **pass**.
- **JAUD1** (3.5 mm), left cheek → bottom-left header: path 257 mm, need 334 / 500, **pass**.
- **JUSB3** (2× USB-A), left cheek → right-edge header: path 493 mm, need 641 / 500, **fails** a typical 500 mm cable. Plan a **700 mm** USB 3 front-panel cable, routed along the left of the 360 then under the board.
- **JUSBC1** (USB-C), same path: 487 mm, need 633 / 500, **fails** a typical 500 mm cable. Plan a **700 mm** USB-C (Key-A) cable.

## Organic frame v1

Asymmetric, bone-like lofted rails, not flat plates. The right rail grows into the power-button head, the left into the port strip. Split at Y=200 as a slightly swollen knuckle with M4 heat-set insert bosses. U-shaped skiff on 15 mm feet, open at the back for the 420 exhaust, intake ribs under the 360 and in the plenum under the PSU. Slotted 45° spine (to avoid a large flat ABS panel) and a wishbone under the board / over the PSU.

12 parts, every one ≤ 290 mm, every STL watertight. Black ABS. Ribs at least 5 mm. Print the rails on the split face, the base feet-down, the spine flat.

| Part | Size (mm) | 100% ABS (g) | 4 walls / 20% infill (g) |
|------|-----------|--------------|---------------------------|
| rail_left/right_front | 42 × 195 × 110 | 192 each | 78 each |
| rail_left/right_rear | 28 × 262 × 214 | 360 each | 157 each |
| base_front_left/right | 246 × 194 × 25 | 133 each | 80 each |
| base_rear_left/right | 246 × 256 × 25 | 117 / 115 | 72 / 71 |
| spine_lower / upper | 228 × 104 × 104 (world AABB of a 5 mm tilted plate) | 151 each | 107 each |
| wishbone_left/right | 233 × 13 × 99 | 61 each | 33 each |
| **Total** | | **~2025** | **~1055** |

Density 1.04 g/cm³. Infill mass is an estimate from shell area + 20% of the remaining volume (4 perimeters at 0.4 mm).

## Open issues

- **700 mm USB 3 and USB-C cables** from the left strip to the right-side board headers, as above.
- **PSU intake:** 20 mm above the PSU is better than the old 4 mm, but a top-mounted fan is still tight. Prefer the bottom intake through the vented 15 mm plenum, or a rear/side intake. IEC is at Y=453, below the 420 exhaust.
- **Fittings on the right** for both AIOs.
- **360 airflow:** down through the intake ribs, or up into the board/GPU. The ribs kiss the 360 underside (~1 cm³ of overlap per side) — trim them 1 mm before a real print.
- Board rear I/O is at the top edge, 45° up and back, above the 420 (top Z=244).
- Frame v1 is still a first sculpture: I/O cutouts need a flat front-face finish, joints need real insert seats and alignment pins, rails can be slimmed, and the rear rails are heavy (~360 g solid each).
- Print on the K1 Max in 290 mm pieces. ABS: brim, glue, slow cooling; the printer is in the bedroom, so watch fumes. Watch creep under the GPU and radiator mass.

## Files

- `layout_b5.py` / `layout_b5.png` — 2D front and side scheme
- `cad_b5/b5_model.py` — parametric hardware and clearance model
- `cad_b5/frame_v1.py` — organic frame, asserts, mass, previews
- `cad_b5/preview_frame_v1.png` — iso front-left, iso rear-right, front, side
- `cad_b5/exploded_v1.png` — exploded iso views
- `cad_b5/parts/*.stl` — one watertight STL per part
- `cad_b5/b5_frame_v1.step` — assembly
- `cad_b5/report_frame_v1.txt` — numeric report
- `cad_b5/preview_b5.png`, `b5_assembly.*`, `report.txt` — earlier block-out
