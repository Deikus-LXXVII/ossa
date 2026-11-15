# Every component is held

## Sub-features
Required holders and fasteners: board 9 standoffs, 420 radiator 6 screws, 360 radiator 4 screws, PSU 4 screws, front fans 8 screws, GPU bracket post plus free-end rest.

## How to get to it (user POV)
The builder screws each component to a printed part. A component with no holder falls out.

## Driving it with frame_v0.py and renders
Check 5 in `cad_b6/report_frame_v0.txt` lists holder and count per component and fails if one is missing. Check 7 confirms each bolt lies inside the outlines it passes through. Then open `previews/b6_v0_rear_right_hw.png` and `previews/b6_v0_front_right_hw.png` and confirm each holder visibly reaches its component.

## Gotchas
- A fastener count proves a hole exists, not that the joint is strong. Wall around a hole below 2 mm is a finding even when the check passes.
- The 360 visor has no stop or latch yet.
- Check 7 enforces the insert maker's minimum wall around every pilot hole (2.1 mm for M4 and short M4S, 1.6 mm for M3). Thin sections use the short M4S insert.
- The PSU bulkhead carries the ATX hole pattern and its vertical mirror because the PSU's orientation is unconfirmed.
