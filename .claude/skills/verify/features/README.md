# What the B6 model must do

One file per property a builder of this case depends on. Each says how to reach it, how to drive it, and what end state proves it.

| Feature | File | Proven by |
|---|---|---|
| Nothing collides | [clearances.md](clearances.md) | checks 1–3 in the report, `measure.py` |
| Every component is held | [mounts.md](mounts.md) | check 5, fastener list, renders |
| Every part fits the printer | [print-fit.md](print-fit.md) | check 4 |
| Pumps are below their radiators | [pump-height.md](pump-height.md) | `layout_b6_options.py` row E |
