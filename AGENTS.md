# Ossa (PC case, layout B6)

A 3D-printed open PC case modelled as CadQuery 2.8 scripts. Current model: `cad_b6/`. Design record and coordinates: `docs/plans/b6-frame-v0.md`. History and constraints: `HANDOFF.md` (its B5 layout is superseded by B6; the file and the reference images under `refs/` are kept on the owner's disk and are not in the public repository, see `refs/README.md`).

- Run scripts from the repo root with `.venv/bin/python`.
- `cad_b6/hardware.py` is the only place hardware dimensions and mounting coordinates live. Never retype a number from it elsewhere.
- To prove a change to `cad_b6/`, follow `.claude/skills/verify/SKILL.md`: run `cad_b6/frame_v0.py` (asserts), `cad_b6/measure.py` for the pairs you touched, `cad_b6/render_vtk.py`, and look at the renders. `REVIEW.md` row 20 asks for `cad_b6/assembly_access.py` after a new screw, a counterbore, or a part moved near a screw's axis.
- Never weaken a check, raise a tolerance, or exempt a pair to make an assert pass. Report the failure instead.
- `cad_b5/` and `history/` are frozen.
- Commits: any model may commit to its own working branch when the work is verified; only Fable-class and Opus-class models commit to `main`. A delegated child commits only when its task says so. Pushing needs the owner's go-ahead.
- Layout and geometry decisions belong to the main session. Do not move hardware or redesign parts on your own.
- When you review a change, read `REVIEW.md` from the last commit (`git show HEAD:REVIEW.md`) and check the rows whose trigger is in the diff. When you build one, do not relax a check or a test that judges your own change; if a check still fails after three rounds of fixing, stop and report. `docs/feature-map.md` lists what the case has to do and what proves it.
- Materials: load-bearing parts (`cad_b6/frame_v0.py`) are ABS; the organic outer layer (`cad_b6/organic_frame.py`) is no longer PLA: the owner ordered black PETG for it on 16 Nov 2026, with black ABS as the fallback if a trial piece prints badly; it carries no component and keeps the 10 mm from the graphics card and the PSU it was drawn with; the light line's diffuser is translucent PLA, so the LED strip sits on the ABS sill with a 10 mm air gap to it.
- Printer, firmware limits and the filament on hand: `docs/printer-and-materials.md`. Never change the printer's firmware.
