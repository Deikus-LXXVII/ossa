# Pumps are below their radiators

## Sub-features
The top of each radiator must be above the top of its pump: the 420 above the CPU block, the 360 above the pump on the graphics card.

## How to get to it (user POV)
Air in a closed loop collects at its highest point. If that point is the pump, the pump runs dry and fails. The owner rejected layout B5 for this.

## Driving it with layout_b6_options.py
`.venv/bin/python layout_b6_options.py` prints one row per layout. Row `E` is the approved one. Columns `CPU зап.` and `GPU зап.` must be positive.

## Gotchas
- `layout_b6_options.py` keeps its own copy of the placement. If hardware moves in `cad_b6/hardware.py`, update row E there or the margin is stale.
- The pump position inside the card is assumed to be mid-card.
