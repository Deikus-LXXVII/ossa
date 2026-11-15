# PC case B6

A 3D-printed open PC case modelled as CadQuery scripts. Current model: `cad_b6/`. Design record and coordinates: `docs/plans/b6-frame-v0.md`. History and constraints: `HANDOFF.md` (its B5 layout is superseded by B6).

- Run scripts from the repo root with `.venv/bin/python`.
- `cad_b6/hardware.py` is the only place hardware dimensions and mounting coordinates live.
- After any change to `cad_b6/`, run the project `verify` skill before reporting.
- CAD geometry changes go to the `cad-implementer` agent.
- Research and chores (re-rendering previews, report and doc updates, file housekeeping) go to Grok, as the global rules say. Layout and geometry decisions stay in the main session. This folder is trusted for Grok, so its children load `AGENTS.md` and this file at startup; keep the two in step.
- `cad_b5/` and `history/` are frozen.
- Commits: any model may commit to its own working branch when the work is verified; only Fable-class and Opus-class models commit to `main`. A delegated child commits only when its task says so. Pushing needs the owner's go-ahead.
- Materials: load-bearing parts (`cad_b6/frame_v0.py`) are ABS; the organic outer layer (`cad_b6/organic_frame.py`) is PLA and carries no component, keeps 10 mm from the graphics card and the PSU; the light line's diffuser is translucent PLA, so the LED strip sits on the ABS sill with a 10 mm air gap to it.
- Printer, firmware limits and the filament on hand: `docs/printer-and-materials.md`. Never change the printer's firmware.
