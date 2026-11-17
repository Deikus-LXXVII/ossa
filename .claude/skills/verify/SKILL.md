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

## The checks bite: test_checks.py

```bash
.venv/bin/python cad_b6/test_checks.py                    # ~5 min (309 and 316 s idle, 330 to 340 s under load, 406 s under load in a fresh checkout with no earlier record to order the sections; 6 workers): the sections in worker processes; ends "293/293 cases as expected"
.venv/bin/python cad_b6/test_checks.py --serial           # ~32 min (1943 s, partly under load; the suite before the sections took 3396 s under load): everything in one process, as before the sections
.venv/bin/python cad_b6/test_checks.py --diff out/test_checks/serial.json out/test_checks/fast.json      # the two case lists must be IDENTICAL
.venv/bin/python cad_b6/test_runner.py                    # ~5 s: the runner on a fake suite: a dropped or emptied section fails, --diff of two short runs fails
```

The cases sit in sections (`@section`). Each section needs only the prelude (the hardware, the frame built twice, the undamaged model's checks with an empty memo), so a worker runs the prelude once and then takes sections, longest first by the last run's times. The output comes in the sections' order whatever order they finished in; a section that raises, or a worker that dies, fails the run, and so does a section that records no case or a run that records fewer cases than `EXPECTED_CASES` in `test_checks.py` (a run with more passes and says to raise it: raise it in the commit that adds the cases). `--diff` fails too when either run is short of it. The default worker count is the cores less one, as many as 0.66 of the machine's memory holds at a fixed 2000 MB a worker (`MEMORY_SHARE`, `WORKER_MB` in `test_checks.py`; 6 on the owner's 18 GB), and no more than the sections; `--workers N` sets it. Measured with 6 workers: about 0.85 GB for a worker that runs no zone_access section, 2.8 to 4.1 GB for one that does, 10.5 to 12.5 GB together; each worker drops its section's memo entries when the section ends. The serial run peaks at 4.0 GB.

Each run writes `out/test_checks/<fast|serial>.json` atomically (a temporary file, then a rename): every case (name, verdict, expected, reported), the wall time, each section's time and case count, the counts of the expensive operations (frame builds, `run_checks` calls, cable routings and evaluations, zone_access runs, drive_access maps), and the SHA-256 of every file that decided the result (each `cad_b6/*.py` imported in any process, and `out/organic/field.npz`) as it was when the run started (`suite_record.py`). After a change to the runner or to how sections are cut, run both modes and `--diff` them: same count, same order, same texts. A new case goes into an existing section or a new `@section` function that takes `(hardware, parts, base)` and looks up what it needs itself; it must not read anything another section left behind.

Bounding boxes: read them with `frame_v0.exact_box` or `bbox_of` (the same, cached), or `exact_bound_box` where code wants a cadquery `BoundBox`, never `BoundingBox()`. cadquery's box takes a face's mesh when the face has one, and any tessellation (check 21's shadow, the voxel grids, a render) leaves a mesh on faces that every moved or rebuilt copy shares, so the answer depended on what ran before.

## Budgets: check_budgets.py

```bash
.venv/bin/python cad_b6/check_budgets.py          # ~20 s (builds the frame once): one line per budget, PASS / FAIL / WARN, exit 1 on a FAIL
.venv/bin/python cad_b6/test_budgets.py           # ~5 s: each budget exceeded fails, inside its margin passes, a missing input, a figure under half its record and a stale or short suite record fail
```

It reads `out/test_checks/fast.json` (run the fast suite first) and `out/organic/field.npz`. Gates: the skeleton's ABS at 4 walls / 20 % (recorded figure + 2 %, and 90 % of `hw.ABS_STOCK_G`), the organic layer's volume (+ 2 %, and its solid PETG at 90 % of the 4 kg ordered), the suite's counts of expensive operations (+ 10 % rounded down: a count is whole, so a count under 10 allows no growth, and the line prints the limit). Warning only: the suite's wall time (+ 25 %), because it is noisy. A figure under half its record fails as a wrong input, not a saving. The suite's record is refused when it is not a clean fast run, when it is short of `EXPECTED_CASES` or has a section with no case, and when a file in its digest has changed since the run (the record is of other code): rerun the suite. Lower a budget with `--write` in a commit of its own after a figure improved; `--write` refuses a figure that fails a hard limit (the stock); never meet a budget by removing a check. A budget that has to rise is the owner's call.

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
