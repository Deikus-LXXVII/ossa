# Every part fits the printer

## Sub-features
- Each part at most 290 mm in X, Y and Z (Creality K1 Max, 300 mm bed, 10 mm margin).
- Members at least 5 mm thick. No part below the desk plane Z = −15.

## How to get to it (user POV)
The builder prints every part in black ABS on one K1 Max.

## Driving it with frame_v0.py
Checks 4 and 6 in the report. The parts table gives each AABB and mass.

## Gotchas
- The AABB is measured in world orientation, not in print orientation. Print orientation, supports, overhangs and ABS shrinkage are not checked yet.
- OrcaSlicer 2.5.1 is installed at `/Applications/OrcaSlicer.app` and its CLI runs without a window, but no K1 Max slicing recipe exists yet. Do not claim a print time or support volume.
