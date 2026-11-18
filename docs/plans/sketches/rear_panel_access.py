"""The access checks with the sketched rear panel added to the layer's field (zone_access: do the bundles still get out; drive_access: does the drive still come out)."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.getcwd(), "cad_b6"))
import hardware as hw
import frame_v0
import drive_access, zone_access

panel = np.load(sys.argv[1])
f = drive_access.load_field()
ld = np.full(panel["d"].shape, 1e9, dtype=np.float32)
ld[:, :f["d"].shape[1], :] = f["d"]
both = dict(d=np.minimum(ld, panel["d"]), xs=panel["xs"].astype(float), ys=panel["ys"].astype(float), zs=panel["zs"].astype(float))
hware = hw.build_hardware()
parts, _ = frame_v0.build_frame(hardware=hware)
lines, fails, res = zone_access.run(parts=parts, hardware=hware, field=both)
print("ZONE_ACCESS with the panel: fails", fails)
for l in lines:
    if "Ø" in l and ("пучок" in l or "bundle" in l or "выход" in l or "рук" in l):
        print("  ", l[:230])
lines, fails, res = drive_access.run(parts=parts, hardware=hware, field=both)
print("DRIVE_ACCESS with the panel: fails", [x[:200] for x in fails])
for l in lines[-8:]:
    print("  ", l[:200])
