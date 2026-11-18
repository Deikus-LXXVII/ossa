# Ossa (PC case, layout B6)

A 3D-printed open PC case modelled as CadQuery scripts. Current model: `cad_b6/`. Design record and coordinates: `docs/plans/b6-frame-v0.md`. History and constraints: `HANDOFF.md` (its B5 layout is superseded by B6; the file and the reference images under `refs/` are kept on the owner's disk and are not in the public repository, see `refs/README.md`).

- Run scripts from the repo root with `.venv/bin/python`.
- `cad_b6/hardware.py` is the only place hardware dimensions and mounting coordinates live.
- After any change to `cad_b6/`, run the project `verify` skill before reporting.
- `REVIEW.md` row 20 asks for `cad_b6/assembly_access.py` after a new screw, a counterbore, or a part moved near a screw's axis.
- CAD geometry changes go to the `cad-implementer` agent.
- Research and chores (re-rendering previews, report and doc updates, file housekeeping) go to Grok, as the global rules say. Agreed with the owner on 16 Nov 2026 for every revision: Grok checks the spec's claims against the code before it goes to `cad-implementer`, reviews the finished change, and afterwards re-renders the previews and brings `README.md`, `AGENTS.md` and this file in step. Reference lookups (filament settings, hose and fitting data, hardware dimensions) go to Grok too. Layout and geometry decisions stay in the main session. This folder is trusted for Grok, so its children load `AGENTS.md` and this file at startup; keep the two in step.
- `cad_b5/` and `history/` are frozen.
- Commits: any model may commit to its own working branch when the work is verified; only Fable-class and Opus-class models commit to `main`. A delegated child commits only when its task says so. Pushing needs the owner's go-ahead.
- Materials: load-bearing parts (`cad_b6/frame_v0.py`) are ABS; the organic outer layer (`cad_b6/organic_frame.py`) is no longer PLA: the owner ordered black PETG for it on 16 Nov 2026, with black ABS as the fallback if a trial piece prints badly; it carries no component and keeps the 10 mm from the graphics card and the PSU it was drawn with; the light line's diffuser is translucent PLA, so the LED strip sits on the ABS sill with a 10 mm air gap to it.
- The organic layer is built as named pieces. `cad_b6/organic_manifest.py --expect <pieces>` is to the layer what `cad_b6/parts_manifest.py` is to the skeleton.
- Verification (adopted on 17 Nov 2026 from Anthropic's note on how the Claude Code team verifies): `REVIEW.md` is the reviewer's guide and the checklist of this project's past mistakes, each with its trigger in a diff; every review task points to it. `docs/feature-map.md` lists what the case has to do and what proves each item; a revision is done when no row got worse. A change does not relax the check that judges it. End each commit that changes `cad_b6/` with a line `Verified: <what was rerun and its result>` or `Verified: none (<why>)`. If a check still fails after three rounds of fixing, stop and bring it to the owner.
- Printer, firmware limits and the filament on hand: `docs/printer-and-materials.md`. Never change the printer's firmware.
