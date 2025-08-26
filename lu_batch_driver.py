# lu_batch_driver.py
# Headless LXF/LXFML -> NIF (LEGO Universe)
# Minimal pipeline with device auto-detect:
#   --device auto (default): honor saved Blender prefs (CUDA/OPTIX enabled state)
#   --device cuda/optix/cpu: force backend
# Keeps: headless UI patches, importer robustness, vertex-color ensure, export scale fix.
import sys, os, argparse, zipfile, tempfile, shutil, traceback
import bpy

def eprint(*a): print(*a, file=sys.stderr)
print("=== LU DRIVER START (auto-device) ===")

def split_script_argv():
    argv = sys.argv
    if "--" in argv:
        return argv[argv.index("--")+1:]
    return argv[1:]

# --------------------- Device handling ---------------------
def _refresh_cycles_devices(cp):
    for attr in ("refresh_devices", "get_devices"):
        fn = getattr(cp, attr, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass

def _log_devices(cp, prefix="[Device] Found"):
    try:
        for d in cp.devices:
            print(f"{prefix}: type={getattr(d,'type','?')} name={getattr(d,'name','?')} use={getattr(d,'use','?')}")
    except Exception as ex:
        eprint(f"[Device] Listing devices failed: {ex}")

def set_cycles_device_auto():
    """Honor existing prefs; enable LU GPU flags based on whether any CUDA/OPTIX device is enabled."""
    try:
        bpy.ops.preferences.addon_enable(module="cycles")
    except Exception:
        pass
    prefs = bpy.context.preferences
    cycles_prefs = prefs.addons.get("cycles")
    if not cycles_prefs:
        eprint("[Device] Cycles addon not available; auto -> CPU.")
        bpy.context.scene.cycles.device = 'CPU'
        return 'cpu'
    cp = cycles_prefs.preferences
    _refresh_cycles_devices(cp)
    _log_devices(cp)
    any_optix = any(getattr(d,'type','')=='OPTIX' and getattr(d,'use',False) for d in cp.devices)
    any_cuda  = any(getattr(d,'type','')=='CUDA'  and getattr(d,'use',False) for d in cp.devices)
    if any_optix or any_cuda:
        bpy.context.scene.cycles.device = 'GPU'
        used = 'optix' if any_optix else 'cuda'
        print(f"[Device] AUTO: Using {used.upper()} from saved prefs")
        return used
    bpy.context.scene.cycles.device = 'CPU'
    print("[Device] AUTO: No GPUs enabled in prefs -> Using CPU")
    return 'cpu'

def set_cycles_device_forced(device: str):
    want = (device or 'cpu').lower()
    try:
        bpy.ops.preferences.addon_enable(module="cycles")
    except Exception:
        pass
    prefs = bpy.context.preferences
    cycles_prefs = prefs.addons.get("cycles")
    if not cycles_prefs:
        eprint("[Device] Cycles addon not available; using CPU.")
        bpy.context.scene.cycles.device = 'CPU'
        return 'cpu'
    cp = cycles_prefs.preferences
    backend = 'NONE' if want=='cpu' else ('CUDA' if want=='cuda' else 'OPTIX')
    try:
        cp.compute_device_type = backend
    except Exception as ex:
        eprint(f"[Device] Cannot set backend {backend}: {ex}")
        backend = 'NONE'
        cp.compute_device_type = backend
    _refresh_cycles_devices(cp)
    _log_devices(cp)
    found_gpu = False
    try:
        for d in cp.devices:
            if backend in {'CUDA','OPTIX'} and getattr(d,'type','') == backend:
                d.use = True
                found_gpu = True
            elif getattr(d,'type','') == 'CPU':
                d.use = True
    except Exception as ex:
        eprint(f"[Device] Iterating devices failed: {ex}")
    if backend in {'CUDA','OPTIX'} and not found_gpu:
        eprint(f"[Device] No {backend} GPUs found; using CPU.")
        bpy.context.scene.cycles.device = 'CPU'
        return 'cpu'
    if backend == 'NONE':
        bpy.context.scene.cycles.device = 'CPU'
        print("[Device] Using CPU")
        return 'cpu'
    bpy.context.scene.cycles.device = 'GPU'
    print(f"[Device] Using {backend}")
    return want

def set_lu_gpu_flags(use_gpu: bool):
    try:
        bpy.context.scene.lutb_process_use_gpu = bool(use_gpu)
        bpy.context.scene.lutb_bake_use_gpu = bool(use_gpu)
        print(f"[Props] Set lutb_process_use_gpu / lutb_bake_use_gpu = {use_gpu}")
    except Exception as ex:
        eprint(f"[Props] Could not set LU GPU flags: {ex}")

# --------------------- Headless UI patching ---------------------
def _headless_patch_method(cls, method_name):
    if not hasattr(cls, method_name):
        return False
    def _stub(self, context, *args, **kwargs):
        print(f"[HeadlessPatch] {cls.__name__}.{method_name}() skipped (background mode).")
        return None
    try:
        setattr(cls, method_name, _stub)
        return True
    except Exception:
        return False

def _apply_headless_patches():
    if not bpy.app.background:
        return False
    patched = False
    pm = None; bl = None
    try:
        pm = __import__("lu_toolbox.process_model", fromlist=['*'])
    except Exception as ex:
        eprint(f"[HeadlessPatch] Could not import lu_toolbox.process_model: {ex}")
    try:
        bl = __import__("lu_toolbox.bake_lighting", fromlist=['*'])
    except Exception as ex:
        eprint(f"[HeadlessPatch] Could not import lu_toolbox.bake_lighting: {ex}")
    target_methods = ("apply_vertex_colors", "set_viewport_to_vertex_color", "ensure_viewport_settings")
    for mod in (pm, bl):
        if not mod:
            continue
        for name in dir(mod):
            obj = getattr(mod, name, None)
            if isinstance(obj, type) and issubclass(obj, bpy.types.Operator):
                for m in target_methods:
                    if _headless_patch_method(obj, m):
                        patched = True
    if patched:
        print("[HeadlessPatch] Applied proactive UI safety patches.")
    return patched

# --------------------- Import, export, ops ---------------------
def ensure_vertex_colors_exist(layer_name="Col"):
    created = 0
    for obj in list(bpy.data.objects):
        if obj.type != 'MESH' or obj.data is None:
            continue
        me = obj.data
        try:
            vcols = getattr(me, "vertex_colors", None)
            if vcols is not None:
                if len(vcols) == 0:
                    vcols.new(name=layer_name)
                    created += 1
                try:
                    vcols.active_index = 0
                except Exception:
                    pass
                continue
        except Exception:
            pass
        try:
            ca = getattr(me, "color_attributes", None)
            if ca is not None:
                if len(ca) == 0:
                    ca.new(name=layer_name, type='BYTE_COLOR', domain='CORNER')
                    created += 1
                try:
                    if hasattr(ca, "active_color_index"):
                        ca.active_color_index = 0
                except Exception:
                    pass
        except Exception:
            pass
    if created:
        print(f"[HeadlessPrep] Created {created} vertex color layer(s).")
    else:
        print("[HeadlessPrep] Vertex color layers already present.")

def try_import_lxf(path: str, op_override: str = None) -> None:
    ext = os.path.splitext(path)[1].lower()
    work_path = path
    temp_dir = None
    try:
        if ext == ".lxf":
            temp_dir = tempfile.mkdtemp(prefix="lxf_unpacked_")
            with zipfile.ZipFile(path, 'r') as zf:
                zf.extractall(temp_dir)
            lxfml = None
            for root, _, files in os.walk(temp_dir):
                for f in files:
                    if f.lower().endswith(".lxfml"):
                        lxfml = os.path.join(root, f)
                        break
                if lxfml: break
            if not lxfml:
                raise RuntimeError("No .lxfml found inside .lxf")
            work_path = lxfml

        op_ids = []
        if op_override:
            op_ids.append(op_override)
        op_ids += ["import_scene.importldd","import_scene.lxfml","import_scene.lxf"]

        attempts = [
            lambda op: op(filepath=work_path),
            lambda op: op(path=work_path),
            lambda op: op(directory=os.path.dirname(work_path), files=[{'name': os.path.basename(work_path)}]),
        ]

        last_err = None
        for op_id in op_ids:
            try:
                mod, func = op_id.split(".", 1)
                operator = getattr(getattr(bpy.ops, mod), func)
            except Exception as ex:
                last_err = ex
                continue
            for call in attempts:
                try:
                    call(operator)
                    print(f"[Import] Imported via {op_id}")
                    return
                except Exception as ex:
                    last_err = ex
                    continue
        raise RuntimeError(f"Could not import '{path}'. Last error: {last_err}")
    finally:
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

def call_op(op_id: str, label: str):
    if "." not in op_id:
        raise RuntimeError(f"Bad operator id: {op_id}")
    mod, func = op_id.split(".", 1)
    operator = getattr(getattr(bpy.ops, mod), func)
    print(f"[Op] {label} via {op_id}")
    return operator()

def set_niftools_game_to_lu():
    scene = bpy.context.scene
    nt = getattr(scene, "niftools_scene", None)
    if nt is None:
        eprint("[NifTools] scene.niftools_scene not found.")
        return False
    try:
        nt.game = 'LEGO_UNIVERSE'
        print("[NifTools] Set game to LEGO_UNIVERSE")
        return True
    except Exception:
        pass
    try:
        enum_items = nt.bl_rna.properties['game'].enum_items
        for it in enum_items:
            disp = (it.name or "").lower()
            if "lego" in disp and "universe" in disp:
                nt.game = it.identifier
                print(f"[NifTools] Set game to {it.identifier} ('{it.name}')")
                return True
    except Exception as ex:
        eprint(f"[NifTools] Could not enumerate game enum: {ex}")
    eprint("[NifTools] Could not set game to LEGO Universe; continuing.")
    return False

def export_nif(out_path: str):
    try:
        op = bpy.ops.export_scene.nif
    except Exception:
        op = None
    if op is None:
        raise RuntimeError("NifTools export operator not found: export_scene.nif")
    print(f"[Export] export_scene.nif -> {out_path}")
    try:
        bpy.ops.image.save_all_modified()
    except Exception:
        pass
    try:
        op(filepath=out_path, scale_correction=1.0)
    except TypeError:
        try:
            nt = getattr(bpy.context.scene, "niftools_scene", None)
            if nt and hasattr(nt, "scale_correction"):
                setattr(nt, "scale_correction", 1.0)
                print("[Export] Set scene.niftools_scene.scale_correction = 1.0")
        except Exception:
            pass
        op(filepath=out_path)

# --------------------- Main ---------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="auto", choices=["auto","cpu","cuda","optix"])
    parser.add_argument("--import-op", default=None)
    parser.add_argument("--brickdb", default=None)
    parser.add_argument("--process-op", default="lutb.process_model")
    parser.add_argument("--bake-op", default="lutb.bake_lighting")
    args = parser.parse_args(split_script_argv())

    src = os.path.abspath(args.input)
    dst = os.path.abspath(args.output)
    if not os.path.isfile(src):
        eprint(f"[Args] Input not found: {src}")
        sys.exit(2)
    os.makedirs(os.path.dirname(dst), exist_ok=True)

    # Enable required add-ons (best-effort)
    for mod in ["lu_toolbox", "io_scene_niftools"]:
        try:
            bpy.ops.preferences.addon_enable(module=mod)
        except Exception:
            pass

    # Set Brick DB if provided
    if args.brickdb:
        try:
            ap = bpy.context.preferences.addons["lu_toolbox"].preferences
            ap.brickdbpath = args.brickdb
            print(f"[LU] Brick DB set to: {ap.brickdbpath}")
        except Exception as ex:
            eprint(f"[LU] Could not set Brick DB path on 'lu_toolbox': {ex}")
    else:
        print("[LU] No --brickdb provided; if importer needs it, set in addon prefs or pass --brickdb")

    _apply_headless_patches()

    # Device policy
    if args.device == 'auto':
        actual = set_cycles_device_auto()
    else:
        actual = set_cycles_device_forced(args.device)
    set_lu_gpu_flags(use_gpu=(actual != 'cpu'))

    # Import
    try:
        try_import_lxf(src, op_override=args.import_op)
    except Exception as ex:
        eprint("[Import] FAILED:", ex)
        traceback.print_exc()
        sys.exit(2)

    # Process
    try:
        call_op(args.process_op, "Process Model")
    except Exception as ex:
        eprint("[Process] FAILED:", ex)
        traceback.print_exc()
        sys.exit(3)

    # Ensure VCols for Bake
    try:
        ensure_vertex_colors_exist()
    except Exception as ex:
        eprint(f"[HeadlessPrep] Could not ensure vertex colors: {ex}")

    # Bake
    try:
        call_op(args.bake_op, "Bake Lighting")
    except Exception as ex:
        eprint("[Bake] FAILED:", ex)
        traceback.print_exc()
        sys.exit(4)

    # NifTools scene setup (best-effort)
    try:
        set_niftools_game_to_lu()
    except Exception as ex:
        eprint("[NifTools] Warning:", ex)

    # Export
    try:
        export_nif(dst)
    except Exception as ex:
        eprint("[Export] FAILED:", ex)
        traceback.print_exc()
        sys.exit(5)

    print("[Done] Success.")
    sys.exit(0)

if __name__ == "__main__":
    main()
