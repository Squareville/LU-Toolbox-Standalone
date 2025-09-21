# ugc_render_driver.py
# LU Toolbox UGC Render Standalone (UI-mode)
#
# Example:
# "C:\Program Files\Blender Foundation\Blender 3.1\blender.exe" --python "V:\...\ugc_render_driver.py" -- ^
#   --input "V:\...\pq_squirrel.blend" --output "V:\...\output\pq_squirrel.png" ^
#   --device optix --type-brickbuild --res 512 --framingscale 1.05 --dds --deleteblend
#
# NOTE: Do NOT use -b (headless). UGC Render needs a real UI context.

import sys, os, argparse, bpy, traceback, subprocess, shutil, shlex, glob, platform

def eprint(*a): print(*a, file=sys.stderr)

def split_script_argv():
    argv = sys.argv
    return argv[argv.index("--")+1:] if "--" in argv else []

# --------------------- Device helpers (consistent w/ your batch driver) ---------------------
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

# --------------------- UI context helpers ---------------------
def _find_ui_context():
    wm = bpy.context.window_manager
    if not wm or not wm.windows:
        return None
    win = wm.windows[0]
    screen = win.screen
    if not screen or not screen.areas:
        return None
    area = next((a for a in screen.areas if a.type == 'VIEW_3D'), None) or screen.areas[0]
    region = next((r for r in area.regions if r.type == 'WINDOW'), None) or (area.regions[0] if area.regions else None)
    scene = win.scene
    if not region or not scene:
        return None
    return dict(window=win, screen=screen, area=area, region=region, scene=scene)

def _call_with_override(op_callable, override, **kwargs):
    temp_override = getattr(bpy.context, "temp_override", None)
    if callable(temp_override):
        with temp_override(**override):
            return op_callable(**kwargs)
    else:
        return op_callable(override, **kwargs)

def _resolve_render_operator():
    # Prefer luugc.render_icon; fallback to lu_ugc_render.render_icon depending on registration
    op = getattr(getattr(bpy.ops, "luugc", None), "render_icon", None)
    if callable(op): return op
    op = getattr(getattr(bpy.ops, "lu_ugc_render", None), "render_icon", None)
    if callable(op): return op
    raise RuntimeError("UGC Render operator not found (expected luugc.render_icon or lu_ugc_render.render_icon).")

# --------------------- Rendered image resolution ---------------------
def _resolve_rendered_path(out_argument: str) -> str | None:
    """
    The addon may write exactly to --output, or append an extension if none was given.
    Try:
      1) exact path
      2) if no extension, try common ones with same stem: .png, .jpg, .jpeg, .exr, .tga
      3) glob stem.*
    """
    out_argument = os.path.abspath(out_argument)
    if os.path.isfile(out_argument):
        return out_argument
    stem, ext = os.path.splitext(out_argument)
    if not ext:
        for cand_ext in (".png", ".jpg", ".jpeg", ".exr", ".tga"):
            cand = stem + cand_ext
            if os.path.isfile(cand):
                return cand
        for path in glob.glob(stem + ".*"):
            if os.path.isfile(path):
                return path
    return None

def _stemmed_dds_path(image_path: str) -> str:
    base, _ = os.path.splitext(image_path)
    return base + ".dds"

# --------------------- External encoder discovery ---------------------
def _which_or_env(default_name: str, env_var: str):
    # Prefer explicit env var path; otherwise search PATH
    cand = os.environ.get(env_var)
    if cand:
        return cand
    return shutil.which(default_name)

def _is_linux():
    return platform.system().lower() == "linux"

# --------------------- DDS conversion (DXT5 + full mipmaps) ---------------------
def _to_dds_dxt5_mips(src_image_path: str, target_dds_path: str) -> bool:
    """
    Try in order:
      1) texconv (native)
      2) nvcompress (NVIDIA Texture Tools)         -> -bc3 (DXT5), auto-mips
      3) compressonatorcli (AMD Compressonator)    -> -fd DXT5 -miplevels 0
      4) wine + texconv.exe (Linux fallback)
    """
    src_image_path = os.path.abspath(src_image_path)
    target_dds_path = os.path.abspath(target_dds_path)
    out_dir = os.path.dirname(target_dds_path) or os.getcwd()
    os.makedirs(out_dir, exist_ok=True)

    # --- 1) texconv (native)
    texconv = _which_or_env("texconv", "TEXCONV")
    if texconv and (shutil.which(texconv) or os.path.isfile(texconv)):
        cmd = [texconv, "-nologo", "-y", "-f", "DXT5", "-m", "0", "-o", out_dir, src_image_path]
        print("[DDS] texconv:", " ".join(shlex.quote(c) for c in cmd))
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode == 0:
            produced = os.path.join(out_dir, os.path.splitext(os.path.basename(src_image_path))[0] + ".dds")
            if os.path.isfile(produced):
                if os.path.abspath(produced) != target_dds_path:
                    try:
                        if os.path.isfile(target_dds_path): os.remove(target_dds_path)
                        os.replace(produced, target_dds_path)
                    except Exception as ex:
                        print(f"[DDS] Move failed: {ex}"); return False
                print(f"[DDS] Wrote: {target_dds_path}")
                return True
        else:
            print("[DDS] texconv failed")
            print("STDOUT:\n", proc.stdout); print("STDERR:\n", proc.stderr)

    # --- 2) nvcompress (cross-OS)
    nvcompress = _which_or_env("nvcompress", "NVCOMPRESS")
    if nvcompress and (shutil.which(nvcompress) or os.path.isfile(nvcompress)):
        # BC3 == DXT5; nvcompress generates mips by default
        cmd = [nvcompress, "-bc3", src_image_path, target_dds_path]
        print("[DDS] nvcompress:", " ".join(shlex.quote(c) for c in cmd))
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode == 0 and os.path.isfile(target_dds_path):
            print(f"[DDS] Wrote: {target_dds_path}")
            return True
        else:
            print("[DDS] nvcompress failed")
            print("STDOUT:\n", proc.stdout); print("STDERR:\n", proc.stderr)

    # --- 3) compressonatorcli (cross-OS)
    compcli = _which_or_env("compressonatorcli", "COMPRESSONATORCLI")
    if compcli and (shutil.which(compcli) or os.path.isfile(compcli)):
        # Full mip chain: -miplevels 0    DXT5: -fd DXT5
        cmd = [compcli, "-fd", "DXT5", "-miplevels", "0", src_image_path, target_dds_path]
        print("[DDS] compressonatorcli:", " ".join(shlex.quote(c) for c in cmd))
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode == 0 and os.path.isfile(target_dds_path):
            print(f"[DDS] Wrote: {target_dds_path}")
            return True
        else:
            print("[DDS] compressonatorcli failed")
            print("STDOUT:\n", proc.stdout); print("STDERR:\n", proc.stderr)

    # --- 4) wine + texconv.exe (Linux fallback)
    if _is_linux():
        wine = _which_or_env("wine", "WINE")
        texconv_exe = os.environ.get("TEXCONV")  # here TEXCONV should point to the .exe
        if wine and texconv_exe and os.path.isfile(texconv_exe):
            cmd = [wine, texconv_exe, "-nologo", "-y", "-f", "DXT5", "-m", "0", "-o", out_dir, src_image_path]
            print("[DDS] wine+texconv:", " ".join(shlex.quote(c) for c in cmd))
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if proc.returncode == 0:
                produced = os.path.join(out_dir, os.path.splitext(os.path.basename(src_image_path))[0] + ".dds")
                if os.path.isfile(produced):
                    if os.path.abspath(produced) != target_dds_path:
                        try:
                            if os.path.isfile(target_dds_path): os.remove(target_dds_path)
                            os.replace(produced, target_dds_path)
                        except Exception as ex:
                            print(f"[DDS] Move failed: {ex}"); return False
                    print(f"[DDS] Wrote: {target_dds_path}")
                    return True
            else:
                print("[DDS] wine+texconv failed")
                print("STDOUT:\n", proc.stdout); print("STDERR:\n", proc.stderr)

    print("[DDS] No suitable encoder found.")
    return False

def _delete_blend_backups(blend_path: str):
    # Delete .blend and typical Blender backups (.blend1, .blend2, …)
    removed = 0
    base = os.path.abspath(blend_path)
    dirn = os.path.dirname(base)
    name = os.path.basename(base)
    # exact .blend
    for p in [base]:
        try:
            if os.path.isfile(p):
                os.remove(p); removed += 1
        except Exception:
            pass
    # patterns like file.blend1, file.blend2, …
    stem, ext = os.path.splitext(base)
    for p in glob.glob(stem + ext + "[0-9]") + glob.glob(stem + ext + "[0-9][0-9]"):
        try:
            if os.path.isfile(p):
                os.remove(p); removed += 1
        except Exception:
            pass
    print(f"[UGC] Deleted blend backups count: {removed}")

# --------------------- Main ---------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input .blend file")
    parser.add_argument("--output", required=True, help="Output image filepath (can be with or without extension)")
    parser.add_argument("--device", default="auto", choices=["auto","cpu","cuda","optix"])
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--type-brickbuild", action="store_true")
    g.add_argument("--type-rocket", action="store_true")
    g.add_argument("--type-car", action="store_true")
    parser.add_argument("--res", type=float, default=None, help="Resolution (float, rounded to int)")
    parser.add_argument("--framingscale", type=float, default=None, help="Framing scale")
    parser.add_argument("--deleteblend", action="store_true", help="Delete .blend (and .blend1, .blend2, …) after render")
    # DDS conversion: DXT5 + mipmaps
    parser.add_argument("--dds", action="store_true", help="Convert rendered image to DDS (DXT5) with full mipmaps; delete source image on success")
    args = parser.parse_args(split_script_argv())

    blend = os.path.abspath(args.input)
    out_arg = os.path.abspath(args.output)
    if not os.path.isfile(blend):
        eprint(f"[Args] Blend not found: {blend}")
        sys.exit(2)

    print(f"[UGC] Opening {blend}")
    bpy.ops.wm.open_mainfile(filepath=blend)

    # Choose device
    pick_device(args.device)

    # Map type flag to addon enum
    ugc_type = "BRICKBUILD" if args.type_brickbuild else ("ROCKET" if args.type_rocket else "CAR")
    res_int = int(round(args.res)) if args.res is not None else None
    margin  = float(args.framingscale) if args.framingscale is not None else None

    out_dir = os.path.dirname(out_arg)
    if out_dir: os.makedirs(out_dir, exist_ok=True)

    # Build operator kwargs (matches your addon signature)
    kwargs = dict(ugc_type=ugc_type, save_path=out_arg)
    if res_int is not None: kwargs["resolution"] = res_int
    if margin  is not None: kwargs["margin"] = margin

    print(f"[UGC] Render {ugc_type} res={res_int} margin={margin} -> {out_arg}")

    try:
        ctx = _find_ui_context()
        if not ctx:
            raise RuntimeError("No UI context available; run without -b and ensure a UI screen is active.")
        op = _resolve_render_operator()
        result = _call_with_override(op, ctx, **kwargs)
        print(f"[UGC] Operator result: {result}")
    except Exception as ex:
        eprint("[UGC] Render failed:", ex)
        traceback.print_exc()
        sys.exit(5)

    # Resolve actual image produced (handles when --output lacks extension)
    rendered_path = _resolve_rendered_path(out_arg)
    if not rendered_path:
        eprint(f"[UGC] Could not find rendered image at or near: {out_arg}")
        sys.exit(6)

    # Optional DDS conversion (DXT5 + full mipmaps)
    if args.dds:
        dds_target = _stemmed_dds_path(rendered_path)
        if _to_dds_dxt5_mips(rendered_path, dds_target):
            # Delete source image only if DDS succeeded
            try:
                if os.path.isfile(rendered_path):
                    os.remove(rendered_path)
                    print(f"[DDS] Deleted source image: {rendered_path}")
            except Exception as ex:
                print(f"[DDS] Converted to DDS but could not delete source: {ex}")
        else:
            print("[DDS] Conversion failed; leaving original image in place.")

    # Optional delete of blend and its backups
    if args.deleteblend:
        _delete_blend_backups(blend)

    print("[UGC] Done."); sys.exit(0)

if __name__ == "__main__":
    main()
