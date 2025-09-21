# ugc_render_standalone.py
# Launches Blender (WITH UI) to run LU Toolbox UGC Render.
# Usage example (Windows):
#   python ugc_render_standalone.py ^
#     --blender "C:\Program Files\Blender Foundation\Blender 3.1\blender.exe" ^
#     --inputblend "V:\path\model.blend" ^
#     --output "V:\path\icon.png" ^
#     --type-brickbuild ^
#     --device optix ^
#     --res 512 --framingscale 1.05 --deleteblend
import argparse, os, sys, subprocess, shlex, tempfile

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

    # Build the Blender UI command; DO NOT use -b (headless). We also avoid --factory-startup
    # so the LU UGC Render addon (with operator id luugc.render_icon) is available. :contentReference[oaicite:5]{index=5}
    driver_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ugc_render_driver.py")
    if not os.path.isfile(driver_path):
        print(f"[Args] Missing driver next to this script: {driver_path}")
        sys.exit(2)

    # Pass args to the in-Blender driver after the "--"
    cmd = [
        args.blender,
        "--python", driver_path, "--",
        "--inputblend", os.path.abspath(args.inputblend),
        "--output", os.path.abspath(args.output),
        "--ugc_type", ugc_type,
        "--device", args.device,
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

    print("[UGC Render] Done.")
    sys.exit(0)

if __name__ == "__main__":
    main()
