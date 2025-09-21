# ugc_render_standalone.py
# Launches Blender (WITH UI) to run LU Toolbox UGC Render.
# Supports optional --dds flag to convert PNG -> DDS (BC7_UNORM) via texconv.
#
# Example:
#   python ugc_render_standalone.py ^
#     --blender "C:\Program Files\Blender Foundation\Blender 3.1\blender.exe" ^
#     --inputblend "V:\path\model.blend" ^
#     --output "V:\path\icon.png" ^
#     --type-brickbuild ^
#     --device optix ^
#     --res 512 --framingscale 1.05 ^
#     --dds ^
#     --deleteblend

import argparse, os, sys, subprocess, shlex, shutil

def _stemmed_dds_path(out_path: str) -> str:
    base, _ = os.path.splitext(out_path)
    return base + ".dds"

def _convert_png_to_dds(png_path: str, target_dds_path: str) -> bool:
    if not os.path.isfile(png_path):
        print(f"[DDS] PNG not found: {png_path}")
        return False

    texconv = shutil.which("texconv") or os.environ.get("TEXCONV")
    if not texconv or (not shutil.which(texconv) and not os.path.isfile(texconv)):
        print("[DDS] texconv not found. Put it in PATH or set TEXCONV env var.")
        return False

    out_dir = os.path.dirname(os.path.abspath(target_dds_path)) or os.getcwd()
    os.makedirs(out_dir, exist_ok=True)

    cmd = [
        texconv, "-nologo", "-y",
        "-f", "BC7_UNORM",
        "-o", out_dir,
        png_path
    ]
    print("[DDS] Running:", " ".join(shlex.quote(c) for c in cmd))
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if proc.returncode != 0:
        print("[DDS] texconv failed")
        print("STDOUT:\n", proc.stdout)
        print("STDERR:\n", proc.stderr)
        return False

    produced = os.path.join(out_dir, os.path.splitext(os.path.basename(png_path))[0] + ".dds")
    if not os.path.isfile(produced):
        print(f"[DDS] Expected DDS not produced: {produced}")
        return False

    if os.path.abspath(produced) != os.path.abspath(target_dds_path):
        try:
            if os.path.isfile(target_dds_path):
                os.remove(target_dds_path)
            os.replace(produced, target_dds_path)
        except Exception as ex:
            print(f"[DDS] Could not move DDS into place: {ex}")
            return False

    print(f"[DDS] Wrote: {target_dds_path}")
    return True

def main():
    p = argparse.ArgumentParser("LU Toolbox UGC Render Standalone")
    p.add_argument("--blender", required=True, help="Path to blender.exe")
    p.add_argument("--inputblend", required=True, help="Path to input .blend")
    p.add_argument("--device", default="auto", choices=["auto","cpu","cuda","optix"])
    p.add_argument("--output", required=True, help="Output image filepath (e.g., .png, .jpg, .exr)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--type-brickbuild", action="store_true")
    g.add_argument("--type-rocket", action="store_true")
    g.add_argument("--type-car", action="store_true")
    p.add_argument("--res", type=float, default=None, help="Square resolution (float -> rounded to int)")
    p.add_argument("--framingscale", type=float, default=None, help="Framing scale (1.0 = as-framed)")
    p.add_argument("--deleteblend", action="store_true", help="Delete the .blend after successful render")
    # NEW: convert to DDS
    p.add_argument("--dds", action="store_true", help="Convert PNG -> DDS (BC7_UNORM) and delete PNG")
    args = p.parse_args()

    if not os.path.isfile(args.inputblend):
        print(f"[Args] .blend not found: {args.inputblend}")
        sys.exit(2)

    # Map type flags to addon enum identifiers
    if args.type_brickbuild:
        ugc_type = "BRICKBUILD"
    elif args.type_rocket:
        ugc_type = "ROCKET"
    else:
        ugc_type = "CAR"

    driver_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ugc_render_driver.py")
    if not os.path.isfile(driver_path):
        print(f"[Args] Missing driver next to this script: {driver_path}")
        sys.exit(2)

    cmd = [
        args.blender,
        "--python", driver_path, "--",
        "--input", os.path.abspath(args.inputblend),
        "--output", os.path.abspath(args.output),
        "--device", args.device,
        f"--type-{ugc_type.lower()}",
    ]
    if args.res is not None:
        cmd += ["--res", str(args.res)]
    if args.framingscale is not None:
        cmd += ["--framingscale", str(args.framingscale)]

    print("==> Launching Blender UI:", " ".join(shlex.quote(c) for c in cmd))
    proc = subprocess.run(cmd, text=True)
    if proc.returncode != 0:
        print(f"[UGC Render] Blender exited with code {proc.returncode}")
        sys.exit(proc.returncode)

    if args.deleteblend:
        try:
            os.remove(args.inputblend)
            print(f"[UGC Render] Deleted blend: {args.inputblend}")
        except Exception as ex:
            print(f"[UGC Render] Could not delete blend: {ex}")

    if args.dds:
        out_path = os.path.abspath(args.output)
        if not os.path.isfile(out_path):
            print(f"[DDS] Rendered PNG not found at: {out_path}")
            sys.exit(3)
        dds_path = _stemmed_dds_path(out_path)
        if _convert_png_to_dds(out_path, dds_path):
            try:
                os.remove(out_path)
                print(f"[DDS] Deleted PNG: {out_path}")
            except Exception as ex:
                print(f"[DDS] Converted to DDS but could not delete PNG: {ex}")
        else:
            print("[DDS] Conversion failed; leaving PNG in place.")
            sys.exit(4)

    print("[UGC Render] Done.")
    sys.exit(0)

if __name__ == "__main__":
    main()
