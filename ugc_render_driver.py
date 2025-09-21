# ugc_render_driver.py
# LU Toolbox UGC Render Standalone (UI-mode)
# Example:
# "C:\Program Files\Blender Foundation\Blender 3.1\blender.exe" --python "V:\...\ugc_render_driver.py" -- ^
#   --input "V:\...\pq_squirrel.blend" --output "V:\...\output\pq_squirrel.png" ^
#   --device optix --type-brickbuild --res 512 --framingscale 1.05 --deleteblend

import sys, os, argparse, bpy, traceback

def eprint(*a): print(*a, file=sys.stderr)

def split_script_argv():
    argv = sys.argv
    return argv[argv.index("--")+1:] if "--" in argv else []

# ---------- Device helpers (consistent w/ your batch driver) ----------
def enable_cycles():
    try: bpy.ops.preferences.addon_enable(module="cycles")
    except Exception: pass

def set_device_auto():
    enable_cycles()
    prefs = bpy.context.preferences.addons.get("cycles")
    if not prefs:
        bpy.context.scene.cycles.device = 'CPU'
        print("[Device] Cycles unavailable; CPU"); return 'cpu'
    cp = prefs.preferences
    try: cp.refresh_devices()
    except Exception: pass
    any_optix = any(getattr(d,'type','')=='OPTIX' and getattr(d,'use',False) for d in cp.devices)
    any_cuda  = any(getattr(d,'type','')=='CUDA'  and getattr(d,'use',False) for d in cp.devices)
    if any_optix or any_cuda:
        bpy.context.scene.cycles.device = 'GPU'
        used = 'optix' if any_optix else 'cuda'
        print(f"[Device] AUTO -> {used.upper()}"); return used
    bpy.context.scene.cycles.device = 'CPU'
    print("[Device] AUTO -> CPU"); return 'cpu'

def set_device_forced(kind: str):
    enable_cycles()
    prefs = bpy.context.preferences.addons.get("cycles")
    if not prefs:
        bpy.context.scene.cycles.device = 'CPU'
        print("[Device] Cycles unavailable; CPU"); return 'cpu'
    cp = prefs.preferences
    want = (kind or 'cpu').lower()
    backend = 'NONE' if want=='cpu' else ('CUDA' if want=='cuda' else 'OPTIX')
    try: cp.compute_device_type = backend
    except Exception: cp.compute_device_type = 'NONE'
    try: cp.refresh_devices()
    except Exception: pass
    has_gpu = False
    for d in cp.devices:
        if backend in {'CUDA','OPTIX'} and getattr(d,'type','') == backend:
            d.use = True; has_gpu = True
        elif getattr(d,'type','') == 'CPU':
            d.use = True
    if backend in {'CUDA','OPTIX'} and not has_gpu:
        bpy.context.scene.cycles.device = 'CPU'
        print(f"[Device] No {backend} -> CPU"); return 'cpu'
    if backend == 'NONE':
        bpy.context.scene.cycles.device = 'CPU'; return 'cpu'
    bpy.context.scene.cycles.device = 'GPU'
    print(f"[Device] {backend}"); return want

def pick_device(flag: str):
    return set_device_auto() if flag == 'auto' else set_device_forced(flag)

# ---------- UI context helpers ----------
def get_ui_context_for_ops():
    wm = bpy.context.window_manager
    if not wm or not wm.windows:
        return None
    win = wm.windows[0]
    screen = win.screen
    # Prefer a 3D View, else fall back to the first area
    area = next((a for a in screen.areas if a.type == 'VIEW_3D'), None) or screen.areas[0]
    # WINDOW region required for many ops
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if region is None and area.regions:
        region = area.regions[0]
    scene = win.scene
    return dict(window=win, screen=screen, area=area, region=region, scene=scene)

# ---------- Main ----------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input .blend file")
    parser.add_argument("--output", required=True, help="Output image filepath")
    parser.add_argument("--device", default="auto", choices=["auto","cpu","cuda","optix"])
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--type-brickbuild", action="store_true")
    g.add_argument("--type-rocket", action="store_true")
    g.add_argument("--type-car", action="store_true")
    parser.add_argument("--res", type=float, default=None, help="Resolution (float, rounded to int)")
    parser.add_argument("--framingscale", type=float, default=None, help="Framing scale")
    parser.add_argument("--deleteblend", action="store_true", help="Delete .blend after render")
    args = parser.parse_args(split_script_argv())

    blend = os.path.abspath(args.input)
    out   = os.path.abspath(args.output)
    if not os.path.isfile(blend):
        eprint(f"[Args] Blend not found: {blend}"); sys.exit(2)

    print(f"[UGC] Opening {blend}")
    bpy.ops.wm.open_mainfile(filepath=blend)

    # Choose device
    pick_device(args.device)

    # Map type flag to addon enum
    ugc_type = "BRICKBUILD" if args.type_brickbuild else ("ROCKET" if args.type_rocket else "CAR")
    res_int = int(round(args.res)) if args.res is not None else None
    margin  = float(args.framingscale) if args.framingscale is not None else None

    os.makedirs(os.path.dirname(out), exist_ok=True)

    # Build operator kwargs (matches luugc.render_icon signature)
    kwargs = dict(ugc_type=ugc_type, save_path=out)
    if res_int is not None: kwargs["resolution"] = res_int
    if margin  is not None: kwargs["margin"] = margin

    print(f"[UGC] Render {ugc_type} res={res_int} margin={margin} -> {out}")

    try:
        # Prepare a real UI override so context.window.scene exists
        wm = bpy.context.window_manager
        if not wm or not wm.windows:
            raise RuntimeError("No UI window available; do not use -b and ensure UI started.")

        win = wm.windows[0]
        screen = win.screen
        area = next((a for a in screen.areas if a.type == 'VIEW_3D'), None) or screen.areas[0]
        region = next((r for r in area.regions if r.type == 'WINDOW'), None) or area.regions[0]
        scene = win.scene

        override = dict(window=win, screen=screen, area=area, region=region, scene=scene)

        # Use temp_override if present (Blender 3.2+), else classic override call (3.1 and older)
        temp_override = getattr(bpy.context, "temp_override", None)
        if callable(temp_override):
            with temp_override(**override):
                result = bpy.ops.luugc.render_icon(**kwargs)
        else:
            result = bpy.ops.luugc.render_icon(override, **kwargs)

        print(f"[UGC] Operator result: {result}")
    except Exception as ex:
        eprint("[UGC] Render failed:", ex)
        traceback.print_exc()
        sys.exit(5)

    if args.deleteblend:
        try:
            os.remove(blend)
            print(f"[UGC] Deleted blend {blend}")
        except Exception as ex:
            eprint(f"[UGC] Could not delete blend: {ex}")

    print("[UGC] Done."); sys.exit(0)

if __name__ == "__main__":
    main()
