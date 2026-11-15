# Nothing collides

## Sub-features
- hardware × hardware, part × hardware, part × part: overlap volume below 1 mm³.
- Intended zero-gap contacts are the ones the plan lists (standoffs under the board, antlers on the 420, visor arms on the 360, skids and bulkhead on the PSU, fence on the fans, `gpu_rest` under the card).

## How to get to it (user POV)
The builder assembles the printed parts around the real components. A clash means a part cannot be fitted.

## Driving it with measure.py
`.venv/bin/python cad_b6/frame_v0.py` runs checks 1–3 over every pair. For a pair you touched, also run `.venv/bin/python cad_b6/measure.py <a> <b>` and quote the line. `--near 5` lists everything within 5 mm of one item.

## Gotchas
- Hardware is boxes. Tubes, fittings, cables and connectors are not modelled, so a clear box does not prove a tube can leave it.
- The 360 sits 122 mm above the board so the CPU hoses pass under it; nearest frame part to the hoses is about 5 mm. The 360's swing path is not checked.
- Board and PSU hole coordinates come from the ATX specifications, not from measuring the owner's parts. The graphics-card slot position and bracket tab height are still `# PLACEHOLDER` in `hardware.py`.
- `hw:io_zone` is a keep-out volume for rear-I/O plugs, not a component. Its 50 mm depth is an estimate.
