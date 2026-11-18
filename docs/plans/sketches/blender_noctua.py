"""cad_b6/blender_scene.py run under the bpy module (no Blender application), with every case fan drawn as a Noctua in the classic colours.

Run from the repository root with the Python that has bpy (out/blender-venv, see the report of 18 Nov 2026):
    out/blender-venv/bin/python docs/plans/sketches/blender_noctua.py [--prefix P] [--pictures DIR] -- <blender_scene.py's own arguments>
        --prefix P       the pictures are saved as <DIR>/<P><view>.png (default render_)
        --pictures DIR   default docs/plans/sketches/pictures
        --noctua LIST    which fans are Noctuas, of 360, 420, side, psu (default: all four groups). The owner's choice of 18 Nov 2026 is 360,psu: the fans on the
                         card's radiator, and the PSU's own fan (a Noctua edition); the 420 keeps its ARCTIC fans and the side fans are the present case's
    e.g. ... blender_noctua.py --prefix render_proposed_ -- --data out/blender-sketch --out out/blender-renders/proposed --views hero

blender_scene.py is executed as it is committed (its source, less the last line that calls main()), and three of its functions are
wrapped, none rewritten:
  build_light_line  skipped when the export has no light line (the sketch's state has no sill and no slit);
  setup_render      after the original: Cycles on the Mac's GPU through Metal (the original tries OptiX and CUDA only),
                    then the fan colours below;
  main              unchanged; afterwards the pictures it wrote (b6_render_<view>.png in --out) are copied to <DIR>/<P><view>.png.
Fan colours: the frames and struts of the chosen fans get a beige copy of the material "fan_frame"; their hubs, blades and hub stickers
get a new brown material made from "fan_blade". A fan that is not chosen keeps the pipeline's dark materials. The graphics card's and
the CPU block's fans keep "fan_blade". Every other material stays as the pipeline has it.
"""
import os
import shutil
import sys

ROOT = os.getcwd()
SCENE_PY = os.path.join(ROOT, "cad_b6", "blender_scene.py")
BEIGE_SRGB, BROWN_SRGB = "E7CEB5", "653024"


def srgb_to_linear(hexrgb):
    out = []
    for i in (0, 2, 4):
        c = int(hexrgb[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


def own_args():
    mine = sys.argv[1:sys.argv.index("--")] if "--" in sys.argv else sys.argv[1:]
    prefix, pictures = "render_", os.path.join(ROOT, "docs", "plans", "sketches", "pictures")
    global NOCTUA
    if "--noctua" in mine:
        NOCTUA = tuple(mine[mine.index("--noctua") + 1].split(","))
        assert set(NOCTUA) <= {"360", "420", "side", "psu"}, NOCTUA
    if "--prefix" in mine:
        prefix = mine[mine.index("--prefix") + 1]
    if "--pictures" in mine:
        pictures = mine[mine.index("--pictures") + 1]
    return prefix, pictures


def load_scene_module():
    src = open(SCENE_PY).read().rstrip()
    assert src.endswith("\nmain()"), "blender_scene.py no longer ends with main(): look at it before running this"
    ns = {"__name__": "blender_scene", "__file__": SCENE_PY}
    exec(compile(src[: -len("main()")], SCENE_PY, "exec"), ns)
    return ns


NOCTUA = ("360", "420", "side", "psu")


def principled_of(mat):
    return next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def noctua(bpy, HW):
    beige, brown = srgb_to_linear(BEIGE_SRGB), srgb_to_linear(BROWN_SRGB)
    frame = bpy.data.materials["fan_frame"].copy()
    frame.name = "noctua_frame"
    principled_of(frame).inputs["Base Color"].default_value = (*beige, 1.0)
    impeller = bpy.data.materials["fan_blade"].copy()
    impeller.name = "noctua_impeller"
    principled_of(impeller).inputs["Base Color"].default_value = (*brown, 1.0)
    groups = {"360": [f"fan360_{k}" for k in range(3)], "420": [f"fan420_{k}" for k in range(len(HW["RAD420_FAN_X"]))], "side": list(HW["FAN_SIDE_X"]), "psu": ["psu_fan"]}
    fans = [f for g in NOCTUA for f in groups[g]]
    done = {}
    for ob in bpy.data.objects:
        base = next((f for f in fans if ob.name.startswith(f + "_")), None)
        if base is None or ob.type != "MESH":
            continue
        for i, m in enumerate(ob.data.materials):
            if m is not None and m.name in ("fan_blade", "fan_sticker"):
                ob.data.materials[i] = impeller
                done.setdefault(base, []).append(ob.name[len(base) + 1:])
            elif m is not None and m.name == "fan_frame":
                ob.data.materials[i] = frame
                done.setdefault(base, []).append(ob.name[len(base) + 1:] + "(beige)")
    missing = [f for f in fans if f not in done]
    assert not missing, f"no fan objects found for {missing}"
    print(f"noctua: frame #{BEIGE_SRGB} -> linear {tuple(round(c, 4) for c in beige)}, impeller #{BROWN_SRGB} -> linear {tuple(round(c, 4) for c in brown)}")
    for f, what in done.items():
        print(f"noctua: {f}: {', '.join(what)}")


def use_metal(bpy, ARGS, device):
    if ARGS.device != "GPU" or device != "CPU":
        return device
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.refresh_devices()
    gpus = [dv for dv in prefs.devices if dv.type == "METAL"]
    if not gpus:
        print("Metal: no GPU found, rendering on the CPU")
        return device
    for dv in prefs.devices:
        dv.use = dv.type == "METAL"
    bpy.context.scene.cycles.device = "GPU"
    device = "METAL " + gpus[0].name
    print("render device:", device)
    return device


def main():
    prefix, pictures = own_args()
    ns = load_scene_module()
    bpy, ARGS = ns["bpy"], ns["ARGS"]
    orig_light, orig_setup = ns.get("build_light_line"), ns["setup_render"]      # revision 18 took the light line out of blender_scene.py

    def build_light_line():
        if "light_slit" not in ns["MESH"]:
            print("light line: not in this export, left out")
            return
        orig_light()

    def setup_render():
        device = use_metal(bpy, ARGS, orig_setup())
        noctua(bpy, ns["HW"])
        return device

    ns["setup_render"] = setup_render
    if orig_light is not None:
        ns["build_light_line"] = build_light_line
    ns["main"]()
    if ARGS.check_only:
        return
    os.makedirs(pictures, exist_ok=True)
    for view in ARGS.views.split(","):
        src = os.path.join(os.path.abspath(ARGS.out), f"b6_render_{view}{ARGS.suffix}.png")
        dst = os.path.join(pictures, f"{prefix}{view}.png")
        shutil.copyfile(src, dst)
        print("saved", dst)


if __name__ == "__main__":
    main()
