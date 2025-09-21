# lu_batch_driver.py
# Headless LXF/LXFML -> NIF (LEGO Universe)
import sys, os, argparse, zipfile, tempfile, shutil, traceback
import bpy

def eprint(*a): print(*a, file=sys.stderr)
print("=== LU DRIVER START (headless parity for apply_vertex_colors) ===")

def split_script_argv():
    argv = sys.argv
    if "--" in argv:
        return argv[argv.index("--")+1:]
    return argv[1:]

# --------------------- Device handling (unchanged) ---------------------
def _refresh_cycles_devices(cp):
    for attr in ("refresh_devices", "get_devices"):
        fn = getattr(cp, attr, None)
        if callable(fn):
            try: fn()
            except Exception: pass

def _log_devices(cp, prefix="[Device] Found"):
    try:
        for d in cp.devices:
            print(f"{prefix}: type={getattr(d,'type','?')} name={getattr(d,'name','?')} use={getattr(d,'use','?')}")
    except Exception as ex:
        eprint(f"[Device] Listing devices failed: {ex}")

def set_cycles_device_auto():
    try: bpy.ops.preferences.addon_enable(module="cycles")
    except Exception: pass
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
    try: bpy.ops.preferences.addon_enable(module="cycles")
    except Exception: pass
    prefs = bpy.context.preferences
    cycles_prefs = prefs.addons.get("cycles")
    if not cycles_prefs:
        eprint("[Device] Cycles addon not available; using CPU.")
        bpy.context.scene.cycles.device = 'CPU'
        return 'cpu'
    cp = cycles_prefs.preferences
    backend = 'NONE' if want=='cpu' else ('CUDA' if want=='cuda' else 'OPTIX')
    try: cp.compute_device_type = backend
    except Exception as ex:
        eprint(f"[Device] Cannot set backend {backend}: {ex}")
        backend = 'NONE'; cp.compute_device_type = backend
    _refresh_cycles_devices(cp)
    _log_devices(cp)
    found_gpu = False
    try:
        for d in cp.devices:
            if backend in {'CUDA','OPTIX'} and getattr(d,'type','') == backend:
                d.use = True; found_gpu = True
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

# --------------------- Headless viewport-safe wrappers (unchanged) ---------------------
class _ShadingProxy:
    def __init__(self):
        self.color_type = getattr(self, "color_type", "MATERIAL")
        self.use_scene_lights = getattr(self, "use_scene_lights", False)
        self.use_scene_world = getattr(self, "use_scene_world", False)

class _SpaceProxy:
    def __init__(self): self.shading = _ShadingProxy()

class _AreaProxy:
    def __init__(self): self.spaces = [_SpaceProxy()]

class _CtxProxy:
    def __init__(self, base_ctx): self._base_ctx = base_ctx; self.area = _AreaProxy()
    def __getattr__(self, name): return getattr(self._base_ctx, name)

def _wrap_ctx_method(cls, method_name):
    if not hasattr(cls, method_name): return False
    orig = getattr(cls, method_name)
    if not callable(orig): return False
    def _wrapped(self, context, *a, **kw):
        try:
            ctx = _CtxProxy(context) if getattr(context, "area", None) is None else context
            return orig(self, ctx, *a, **kw)
        except Exception as ex:
            eprint(f"[HeadlessWrap] {cls.__name__}.{method_name}() warning: {ex}")
            return orig(self, context, *a, **kw)
    setattr(cls, method_name, _wrapped)
    print(f"[HeadlessWrap] Wrapped {cls.__name__}.{method_name}")
    return True

def _apply_headless_patches():
    patched = False
    try:
        pm = __import__("lu_toolbox.process_model", fromlist=['*'])
    except Exception as ex:
        eprint(f"[HeadlessWrap] Could not import lu_toolbox.process_model: {ex}")
        return patched
    target_methods = {"apply_vertex_colors", "set_viewport_to_vertex_color", "ensure_viewport_settings"}
    for name in dir(pm):
        obj = getattr(pm, name, None)
        try:
            is_op = isinstance(obj, type) and issubclass(obj, bpy.types.Operator)
        except Exception:
            is_op = False
        if not is_op: continue
        for m in target_methods:
            try:
                if _wrap_ctx_method(obj, m): patched = True
            except Exception as ex:
                eprint(f"[HeadlessWrap] Failed to wrap {obj.__name__}.{m}: {ex}")
    if patched:
        print("[HeadlessWrap] Viewport methods wrapped for headless parity.")
    return patched

# --------------------- Import / Export helpers ---------------------
def ensure_vertex_colors_exist(layer_name="Col"):
    created = 0
    for obj in list(bpy.data.objects):
        if obj.type != 'MESH' or obj.data is None: continue
        me = obj.data
        try:
            vcols = getattr(me, "vertex_colors", None)
            if vcols is not None:
                if len(vcols) == 0:
                    vcols.new(name=layer_name); created += 1
                try: vcols.active_index = 0
                except Exception: pass
                continue
        except Exception: pass
        try:
            ca = getattr(me, "color_attributes", None)
            if ca is not None:
                if len(ca) == 0:
                    ca.new(name=layer_name, type='BYTE_COLOR', domain='CORNER'); created += 1
                try:
                    if hasattr(ca, "active_color_index"):
                        ca.active_color_index = 0
                except Exception: pass
        except Exception: pass
    print(f"[HeadlessPrep] Created {created} vertex color layer(s)." if created else "[HeadlessPrep] Vertex color layers already present.")

def _call_import_with_kwargs(op, path, lod_kwargs):
    # Only import_scene.importldd supports LOD kwargs (see importldd.py). 
    try:
        idname = op.idname()
    except Exception:
        idname = ""
    if idname == "IMPORT_SCENE_OT_importldd" and lod_kwargs:
        return op(filepath=path, **lod_kwargs)
    return op(filepath=path)

def try_import_lxf(path: str, op_override: str = None, lod_kwargs: dict | None = None) -> None:
    """Import .lxf or .lxfml. Prefer LU Toolbox importer; unzip to .lxfml only as fallback."""
    ext = os.path.splitext(path)[1].lower()
    temp_dir = None

    op_ids = []
    if op_override: op_ids.append(op_override)
    # Prefer lu_toolbox importer; fall back to the generic ones. 
    if ext == ".lxf":
        op_ids += ["import_scene.importldd", "import_scene.lxf"]
    else:
        op_ids += ["import_scene.importldd", "import_scene.lxfml"]

    attempts = [
        lambda op, p: _call_import_with_kwargs(op, p, lod_kwargs),
        lambda op, p: op(path=p),  # some importers use 'path'
        lambda op, p: op(directory=os.path.dirname(p), files=[{'name': os.path.basename(p)}]),
    ]

    last_err = None
    for op_id in op_ids:
        try:
            mod, func = op_id.split(".", 1)
            operator = getattr(getattr(bpy.ops, mod), func)
        except Exception as ex:
            last_err = ex; continue
        for call in attempts:
            try:
                call(operator, path)
                print(f"[Import] Imported via {op_id}")
                return
            except Exception as ex:
                last_err = ex; continue

    if ext == ".lxf":
        try:
            temp_dir = tempfile.mkdtemp(prefix="lxf_unpacked_")
            with zipfile.ZipFile(path, 'r') as zf:
                zf.extractall(temp_dir)
            lxfml = None
            for root, _, files in os.walk(temp_dir):
                for f in files:
                    if f.lower().endswith(".lxfml"):
                        lxfml = os.path.join(root, f); break
                if lxfml: break
            if not lxfml:
                raise RuntimeError("No .lxfml found inside .lxf")
            for op_id in ["import_scene.importldd", "import_scene.lxfml"]:
                try:
                    mod, func = op_id.split(".", 1)
                    operator = getattr(getattr(bpy.ops, mod), func)
                except Exception as ex:
                    last_err = ex; continue
                for call in attempts:
                    try:
                        call(operator, lxfml)
                        print(f"[Import] Imported via {op_id} (unzipped .lxfml fallback)")
                        return
                    except Exception as ex:
                        last_err = ex; continue
        finally:
            if temp_dir and os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    raise RuntimeError(f"Could not import '{path}'. Last error: {last_err}")

def call_op(op_id: str, label: str):
    if "." not in op_id: raise RuntimeError(f"Bad operator id: {op_id}")
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
    try: op = bpy.ops.export_scene.nif
    except Exception: op = None
    if op is None:
        raise RuntimeError("NifTools export operator not found: export_scene.nif")
    print(f"[Export] export_scene.nif -> {out_path}")
    try: bpy.ops.image.save_all_modified()
    except Exception: pass
    try:
        op(filepath=out_path, scale_correction=1.0)
    except TypeError:
        try:
            nt = getattr(bpy.context.scene, "niftools_scene", None)
            if nt and hasattr(nt, "scale_correction"):
                setattr(nt, "scale_correction", 1.0)
                print("[Export] Set scene.niftools_scene.scale_correction = 1.0")
        except Exception: pass
        op(filepath=out_path)

# --------------------- NEW: Save .blend helper ---------------------
def save_blend_after(input_path: str, out_nif_path: str | None, saveblend_arg):
    """
    saveblend_arg:
      - None  : disabled
      - ""    : flag present with no path -> default target
      - "X.blend": explicit path
    Default target:
      - if NIF path exists -> next to NIF (same stem)
      - else -> next to INPUT (same stem)
    """
    if saveblend_arg is None:
        return
    if isinstance(saveblend_arg, str) and saveblend_arg != "":
        blend_path = os.path.abspath(saveblend_arg)
    else:
        stem_source = out_nif_path if out_nif_path else input_path
        stem = os.path.splitext(os.path.basename(stem_source))[0]
        base_dir = os.path.dirname(os.path.abspath(stem_source))
        blend_path = os.path.join(base_dir, stem + ".blend")
    os.makedirs(os.path.dirname(blend_path), exist_ok=True)
    print(f"[Blend] Saving .blend -> {blend_path}")
    # NOTE: Blender 3.1 does not accept 'copy=' kwarg here; omit it.
    bpy.ops.wm.save_mainfile(filepath=blend_path, compress=False)

# --------------------- Main ---------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    # OUTPUT NOW OPTIONAL: if omitted, we skip NIF export.
    parser.add_argument("--output", required=False)
    parser.add_argument("--device", default="auto", choices=["auto","cpu","cuda","optix"])
    parser.add_argument("--import-op", default=None)
    parser.add_argument("--brickdb", default=None)
    parser.add_argument("--process-op", default="lutb.process_model")
    parser.add_argument("--bake-op", default="lutb.bake_lighting")

    # NEW: optional blend save flag (with optional path)
    parser.add_argument("--saveblend", nargs="?", const="", default=None,
                        help="Save .blend after pipeline. No value: default path; with value: explicit filepath.")

    # NEW: optional LOD selectors (only applied for LU Toolbox importer)
    parser.add_argument("--LOD_0", action="store_true", help="Import LOD0")
    parser.add_argument("--LOD_1", action="store_true", help="Import LOD1")
    parser.add_argument("--LOD_2", action="store_true", help="Import LOD2")
    parser.add_argument("--LOD_3", action="store_true", help="Import LOD3")

    args = parser.parse_args(split_script_argv())

    src = os.path.abspath(args.input)
    dst = os.path.abspath(args.output) if args.output else None
    if not os.path.isfile(src):
        eprint(f"[Args] Input not found: {src}")
        sys.exit(2)
    if dst:
        os.makedirs(os.path.dirname(dst), exist_ok=True)

    # Enable required add-ons (best-effort) – LU Toolbox & NifTools. 
    for mod in ["lu_toolbox", "io_scene_niftools"]:
        try: bpy.ops.preferences.addon_enable(module=mod)
        except Exception: pass

    # Brick DB passthrough
    if args.brickdb:
        try:
            ap = bpy.context.preferences.addons["lu_toolbox"].preferences
            ap.brickdbpath = args.brickdb
            print(f"[LU] Brick DB set to: {ap.brickdbpath}")
        except Exception as ex:
            eprint(f"[LU] Could not set Brick DB path on 'lu_toolbox': {ex}")
    else:
        print("[LU] No --brickdb provided; set in addon prefs or pass --brickdb")

    _apply_headless_patches()

    # Device policy
    actual = set_cycles_device_auto() if args.device == 'auto' else set_cycles_device_forced(args.device)
    set_lu_gpu_flags(use_gpu=(actual != 'cpu'))

    # LOD override logic: if no LOD flags are set, we pass nothing and let addon defaults apply. 
    any_lod = args.LOD_0 or args.LOD_1 or args.LOD_2 or args.LOD_3
    lod_kwargs = None
    if any_lod:
        lod_kwargs = {
            "importLOD0": bool(args.LOD_0),
            "importLOD1": bool(args.LOD_1),
            "importLOD2": bool(args.LOD_2),
            "importLOD3": bool(args.LOD_3),
        }
        print(f"[Import] LOD override -> {lod_kwargs}")

    # Import
    try:
        try_import_lxf(src, op_override=args.import_op, lod_kwargs=lod_kwargs)
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

    # Ensure VCols (parity)
    try: ensure_vertex_colors_exist()
    except Exception as ex: eprint(f"[HeadlessPrep] Could not ensure vertex colors: {ex}")

    # Bake
    try:
        call_op(args.bake_op, "Bake Lighting")
    except Exception as ex:
        eprint("[Bake] FAILED:", ex)
        traceback.print_exc()
        sys.exit(4)

    # Export NIF (only if --output provided)
    if dst:
        try:
            set_niftools_game_to_lu()
        except Exception as ex:
            eprint("[NifTools] Warning:", ex)
        try:
            export_nif(dst)
        except Exception as ex:
            eprint("[Export] FAILED:", ex)
            traceback.print_exc()
            sys.exit(5)
    else:
        print("[Export] Skipped (no --output provided)")

    # Save .blend if requested (default path next to NIF if exporting; else next to input)
    try:
        save_blend_after(src, dst, args.saveblend)
    except Exception as ex:
        eprint("[Blend] Save failed:", ex)

    print("[Done] Success.")
    sys.exit(0)

if __name__ == "__main__":
    main()
