# Review guide for this repository

For any reviewer of a change to the model, human or agent. It says what to look at first and lists the mistakes this project has already made, each with the sign in a diff that should make you check for it again.

Read this file from the last commit, not from the change under review: `git show HEAD:REVIEW.md`. A change may not relax the guide that judges it.

## What matters most

1. **A check that passes for the wrong reason.** The model is trusted because its checks fail when the geometry is wrong. A check that cannot fail is worse than no check.
2. **A check or a test made weaker by the change it judges.** Every removed or rewritten case needs a successor of the same strictness.
3. **A number that is not what the comment says it is:** a hardware dimension retyped outside `cad_b6/hardware.py`, a placeholder treated as a measurement, a figure from a coarse grid treated as exact.

Tag each finding **Important** (wrong result possible), **Nit**, or **Pre-existing** (was there before this change).

## Checklist: check an item only when its trigger is in the diff

| # | Trigger in the diff | What to check | Where it went wrong before |
|---|---|---|---|
| 1 | A measurement or check on a voxel grid, new or changed | Every layer of the grid is asserted non-empty. Seeds and targets are asserted non-empty. | 16 Nov 2026: free space was measured with the cables missing from the grid, and a drive bay was promised where cables run. |
| 2 | A flood fill or reachability check | The grid's own margin cannot serve as a path. The test's blocking wall is no larger than the region the check claims to close. | Revision 13: a cable was "getting out" round the outside of the fans and over the case. |
| 3 | A hand calculation of strength, new or changed | Every loaded section has a row. A load off a section's centre brings torsion. The worst row is really the worst. A test thins each section and expects a failure. The allowable comes from one place. | Revision 13: the bracket's leg was assumed worst, the spine was (20 MPa). Check 18 left torsion out of the low column. |
| 4 | Cases removed from `test_checks.py` or `test_organic.py`, or expected strings changed | Each has a successor of the same strictness. The report states the count before and after. | Asked of every revision since 11. |
| 5 | A literal in `frame_v0.py`, `cables.py`, `organic_frame.py` or `zone_access.py` that equals a hardware dimension | It is derived from `hardware.py`. | Revision 13: a fan's edge and a pilot radius were retyped. |
| 6 | Hardware moved or resized in `hardware.py` | The organic layer was regenerated and its checks read. `zone_access.py`, `cables.py`, `drive_access.py`, `fit_gauges.py` and `strength.py` were rerun. Constants that held the old position are gone. | Revision 13: the layer's fan rings were cut off by a clip left at the old limit. |
| 7 | A new printed part or joint | A row in the bill of fasteners. Inserts within four fifths of the stock. The screw-length rule. The mount count and the intended contacts. The part's mass and its longest side against 290 mm. | Revisions 12 and 14a. |
| 8 | A spec's number that came from a grid or from reading code | It was confirmed on the exact model and the difference reported. | Every spec from revision 11 to 14a carried at least one wrong number. |
| 9 | A hardware-facing feature in a part heavier than about 80 g | The dimension is proved by a gauge or a measurement, or the feature is a small part of its own (`docs/plans/modularity.md`). | 16 Nov 2026, owner's rule. |
| 10 | A dimension marked PLACEHOLDER or ASSUMPTION is used | The report names it. Nothing claims a fit that rests on it. | The front I/O module, the insert's size, the screw lengths of the PSU and the 360. |
| 11 | The load model of `strength.py` or `organic_strength.py` changed | The allowable is untouched. The old model is still reported beside the new one. | Revision 11. |
| 12 | A solver, a mesh or a speed change in a strength script | The report is identical to the one before, apart from timing lines. A failure to converge or a bad residual stops the run. | 17 Nov 2026, the Accelerate solver. |
| 13 | A part the revision says it did not touch | `cad_b6/parts_manifest.py --expect <the parts the spec names>` passes: no other part or hardware solid differs from the last commit. | Revision 14a: the sill's face moved 2 mm as a side effect of a larger pocket. |
| 15 | A test probe, an expected string or a threshold moved in the same change as the geometry it tests | The move is not what makes the test pass. Put the probe back and see. | Revision 14a: the probe in the sill's rear wall was moved off the place where the wall had become open. |
| 14 | A channel, a clip or a wall drawn round a hose or a cable route | The clearance does not hang on one sample of the route. Say what happens if the route moves by a millimetre. | Revision 14a: a hose channel with a 0.24 mm wall placed on one vertex of the route. |

## What a review does not have to redo

The author's own run of the scripts (`frame_v0.py`, `cables.py`, `zone_access.py`, `fit_gauges.py`, `drive_access.py`, `test_checks.py`, `strength.py`) is repeated by the main session before every commit. A reviewer recomputes numbers and looks for the wrong reason behind a pass; it does not need to rerun the long scripts.

## Keeping this file honest

Add a row when a review or the owner finds a mistake that a diff could have shown. Remove a row when the code makes the mistake impossible (a check, a type, a derived constant) and say so in the commit.
