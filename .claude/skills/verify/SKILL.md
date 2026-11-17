---
name: verify
description: Prove a change to the B6 PC-case CAD model (CadQuery scripts in cad_b6/) by rebuilding it, running the geometry asserts, measuring, and looking at rendered views. Use after any edit to cad_b6/*.py, before reporting CAD work as done, and whenever a clearance, fit, or mount is in question.
---

# Verify the B6 CAD model

The app is a set of CadQuery scripts. "Running it" means rebuilding the solids. Text that parses is not evidence. Numbers and pictures are.

Run everything from the repo root with `.venv/bin/python`. There is no server and nothing to tear down.

## Doctor

```bash
.venv/bin/python -c "import cadquery, vtk, trimesh; print(cadquery.__version__, vtk.vtkVersion.GetVTKVersion())"
```

Expect `2.8.0` and a VTK version. If it fails, the venv is broken. Report that and stop. Do not install packages to work around it.

## Launch

```bash
.venv/bin/python cad_b6/frame_v0.py
```

About 20 s. It writes the report, STEP and legacy previews first, then asserts. Success ends with `Done, all asserts passed.` A failed assert prints the offending pairs and exits non-zero. The asserts are listed in `docs/plans/b6-frame-v0.md` under Checks.

## Differential and property checks

Run both after `frame_v0.py`. Neither needs a view, and they can run side by side.

```bash
.venv/bin/python cad_b6/test_properties.py      # ~20 s: property tests of the helper functions; ends PASS (a known failure is listed, not hidden)
.venv/bin/python cad_b6/parts_manifest.py --expect <parts the revision's spec says it changes>      # ~20 s: exit 1 names any part or hardware solid that changed outside the list
```

`parts_manifest.py` compares the working tree with `cad_b6/parts_manifest.json` in the last commit. Take the list from the spec (`tie_bridge_*` and `hw:<name>` work). Quote its table in the report. Rewrite the manifest with `--write` only in the commit that carries the revision, after the table has been read. A property that fails is a finding: do not weaken it.

## Drive

1. **Measure.** `cad_b6/measure.py` prints AABBs, minimum distance and overlap volume for named parts and hardware. Names come from running it with no arguments. Hardware names carry the `hw:` prefix.

   ```bash
   .venv/bin/python cad_b6/measure.py                      # list names and AABBs
   .venv/bin/python cad_b6/measure.py hw:rad360 hw:cpu_block
   .venv/bin/python cad_b6/measure.py hw:gpu --near 5      # everything within 5 mm
   ```

2. **Render.** `cad_b6/render_vtk.py` writes eight shaded images with edges to `previews/b6_v0_<view>_<hw|bare>.png`, views `front_left`, `front_right`, `rear_right`, `left`. About 40 s.

   ```bash
   .venv/bin/python cad_b6/render_vtk.py
   ```

3. **Look.** Open at least `front_right_hw`, `rear_right_hw` and `left_hw` with the Read tool. Check that each changed part is where you intended, touches what it should hold, and that nothing floats or pokes through hardware.

The `cadquery` MCP server (`.mcp.json`) offers `inspect` and `render` for a code snippet. Use `inspect` for a quick bbox, volume and centre of mass of a single part. Its fixed cameras suit single parts, not this assembly, so use `render_vtk.py` for the whole model.

## Evidence

A proof is the three things together: the assert summary lines from `cad_b6/report_frame_v0.txt`, the `measure.py` lines for every pair you changed or claimed a clearance for, and the views you opened with what you saw in them.

- Quote measured numbers. Do not restate a number from the plan as if it were measured.
- Mark every value that still comes from a `# PLACEHOLDER` in `cad_b6/hardware.py`.
- A contact is intended only if the plan lists it. Anything else under 2 mm is a finding.
- Never loosen an assert, raise a tolerance, or add a pair to an allow-list to get green. Report the failure.

## Cleanup

Nothing to stop. Outputs in `previews/` and `cad_b6/` are the evidence and stay. Scratch files go in the session scratchpad, not the repo.

## Features

See [features/README.md](features/README.md).
