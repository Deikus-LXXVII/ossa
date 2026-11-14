# PC case B5

Open, asymmetric, fully printed black-ABS case for a desk showpiece. This folder is a volume and clearance study plus a first organic frame, not a finished case.

Layout origin: X is left–right, Y is depth (front at 0, increasing backwards), Z is up. All sizes in mm.

## Hardware

| Part | Size (mm) | Notes |
|------|-----------|--------|
| MSI MAG Z890 Tomahawk WiFi | ATX 305 × 244 × 2 | Board at 45°, leaning back. Bottom edge at Y=150, Z=65. Face toward the front and up. Rear I/O at the top edge (~Y 366, Z 281), 45° up and back. |
| ARCTIC Liquid Freezer III Pro 420 | 458 × 138 × 65 (rad + fans) | Stands on its edge in the wedge behind and under the board, above the PSU. Tubes 500 mm. |
| MSI RTX 5080 SUPRIM LIQUID | GPU 280 × 148 × 51; 360 rad 394 × 121 × 55 | 360 lies flat in front of the board. GPU in the PCIe slot, 45% up the board, 280 mm along X (18 mm overhang each side), 148 mm out of the board, 51 mm thickness down the board so it clears the CPU. Tubes 450 mm. |
| Seasonic PRIME TX-1600 | 210 × 150 × 86 | 150 along X (centred), 210 along Y, 86 tall. Cables at the front, under the board. IEC at the rear. |
| CPU block | ~70 × 70 × 50 | On the board, 70% up from the bottom edge. |

The 360 and 420 were swapped versus layout B4 so the front is free for buttons and ports.

## Layout (B5)

- **360** lies flat in front of the board's bottom edge: Y 29…150, Z 10…65, X ±197. Fan tops are level with the board bottom. The board stayed at Z=65; the 360 is raised 10 mm on a plinth (an intake gap). Lowering the board to 55 would shrink the rear wedge and the 420 would hit it.
- **Board** at 45°, bottom edge Y=150, Z=65.
- **420** stands on its edge behind and under the board: Y 353…418, Z 106…244, X ±229. Open 25 mm exhaust behind it (Y 418…443). Blow it backward, away from the board.
- **PSU** at Y 243…453, Z 0…86, still under the 420. Shifted back so the IEC at Y=453 stays reachable behind the exhaust.
- **Front I/O pod** on the right (asymmetric), in the space freed by the narrower, shallower 360: X 212…302, Y 8…98, Z 8…72. Face toward the front: power and reset (16–19 mm anti-vandal), 2× USB-A 3.x, USB-C (Z890 Tomahawk JUSBC1, Key-A), 3.5 mm combo jack, optional power LED.

The 420 does not fit in the old 360 pocket from B4 (it is 17 mm taller and 10 mm thicker, and already intersects the board there). It was moved back and up to keep 15 mm to the board and 20 mm to the PSU top. The case is therefore deeper (~460 mm vs ~405 mm in B4) and a little wider on the right because of the pod.

## Checks

All pairwise component intersection volumes are 0. Main gaps:

- board–360: contact (fan tops = board bottom, by design)
- board–420: 15 mm
- 420–PSU: 20 mm
- 360–I/O pod: 15 mm
- 360–GPU: 86 mm
- 420–CPU: 27 mm
- GPU–CPU: 41 mm

Bounding box of the iron + I/O pod: X −229…302 (531), Y 8…453 (445), Z 0…280.7 (280.7). Envelope with frame and exhaust: X −242…315 (557), Y 0…460 (460), Z −6…290 (296).

### Tubes (straight-line × 1.3 slack)

- **CPU → 420**, 500 mm tubes: pass. Around either board edge needs 328 mm; over the top needs 451 mm. Put the 420 fittings on the **left** end and route around the left edge, so the right side stays clear for I/O cables.
- **GPU → 360**, 450 mm tubes: pass. Same-side needs 179 mm; opposite-side 441 mm (tight but legal). Prefer **same-side, left end**, away from the I/O pod. The path stays in front of the board.

### Front-panel cables

The pod sits on the right, near JUSB3, JUSBC1 and JFP1. Route USB 3 and USB-C around the 360's right end, not through it.

- JFP1, JUSB3, JUSBC1: pass on a typical 500 mm cable (need 345–367 mm).
- JAUD1 is on the opposite (left) edge: a stock 500 mm HD-audio cable is short (path ~525 mm). Use a **700 mm** front-audio extension along the front lip.

## Open issues

- **700 mm audio extension** for JAUD1, as above.
- **PSU intake:** 20 mm above the PSU is better than the old 4 mm, but a top-mounted fan is still tight. Prefer a bottom intake with a vented base and feet, or a rear/side intake. The IEC is at Y=453, below the 420 exhaust.
- **Fittings on the left** for both AIOs, as above.
- **360 airflow:** either down through a grille in the 10 mm plinth, or up into the board/GPU.
- Board rear I/O is at the top edge, 45° up and back, above the 420 (top Z=244).
- Printable parts must stay at most 290 mm in every direction (K1 Max 300³ bed, 10 mm margin). ABS: brim, glue, slow cooling; the printer is in the bedroom, so watch fumes. Walls 4–6 mm with ribs and M4 heat-set inserts. Watch creep under the GPU and radiator mass.

## Files

- `layout_b5.py` / `layout_b5.png` — 2D front and side scheme
- `cad_b5/b5_model.py` — parametric CadQuery model (components, checks, frame, previews)
- `cad_b5/preview_b5.png` — isometric, front and side of the block-out
- `cad_b5/b5_assembly.step/.stl`, `b5_frame.step/.stl`, `b5_all.step` — exports
- `cad_b5/report.txt` — numeric clearance and tube report

Coordinates and every component size are parameters in `cad_b5/b5_model.py`.
