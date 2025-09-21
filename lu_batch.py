# lu_batch.py
import os, sys, argparse, subprocess, fnmatch, shlex, concurrent.futures, pathlib, time

def find_files(root, patterns, recursive=False):
    root = os.path.abspath(root)
    pats = [p.strip() for p in patterns.split(";") if p.strip()]
    if os.path.isfile(root):
        if any(fnmatch.fnmatch(root.lower(), p.lower()) for p in pats) or not pats:
            return [root]
        return []
    files = []
    walker = os.walk(root) if recursive else [next(os.walk(root))]
    for dirpath, dirnames, filenames in walker:
        for f in filenames:
            full = os.path.join(dirpath, f)
            if any(fnmatch.fnmatch(f.lower(), p.lower()) for p in pats):
                files.append(full)
        if not recursive:
            break
    return files

def derive_output(in_path, out_root):
    stem = os.path.splitext(os.path.basename(in_path))[0]
    return os.path.abspath(os.path.join(out_root, stem + ".nif"))

def run_one(blender, driver, in_path, out_path, device, extra_driver_args, pass_output: bool):
    cmd = [
        blender, "-b", "--factory-startup",
        "--python", driver, "--",
        "--input", in_path,
        "--device", device,
    ]
    if pass_output:
        cmd.extend(["--output", out_path])
    cmd += extra_driver_args
    print("==> Running:", " ".join(shlex.quote(c) for c in cmd))
    t0 = time.time()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    dt = time.time() - t0
    success = (proc.returncode == 0)
    # Per-file log next to the derived out_path even if we skipped export
    log_base = out_path if pass_output else os.path.splitext(out_path)[0] + ".noexport"
    log_path = log_base + (".ok.log" if success else ".err.log")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("CMD:\n")
        f.write(" ".join(shlex.quote(c) for c in cmd) + "\n\n")
        f.write(f"EXIT: {proc.returncode}  DURATION_S: {dt:.2f}\n\n")
        f.write("STDOUT:\n" + proc.stdout + "\n\n")
        f.write("STDERR:\n" + proc.stderr + "\n")
    return success, in_path, out_path, dt, proc.returncode

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input file or directory")
    parser.add_argument("--output", required=True, help="Output directory (also used for logs)")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda", "optix"])
    parser.add_argument("--blender", required=True, help="Path to blender executable")
    parser.add_argument("--driver", required=True, help="Path to lu_batch_driver.py")
    parser.add_argument("--pattern", default="*.lxf;*.lxfml", help="Semicolon-separated glob(s)")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--jobs", type=int, default=1, help="Parallel conversions")

    # Old pass-through still supported
    parser.add_argument("--extra-driver-args", default="", help="Raw pass-through to driver")

    # NEW convenience switches passed to the driver:
    parser.add_argument("--no-export", action="store_true",
                        help="Do not pass --output to driver (driver will skip NIF export)")
    parser.add_argument("--saveblend", nargs="?", const="", default=None,
                        help="Ask driver to save .blend (optional path)")
    parser.add_argument("--LOD_0", action="store_true")
    parser.add_argument("--LOD_1", action="store_true")
    parser.add_argument("--LOD_2", action="store_true")
    parser.add_argument("--LOD_3", action="store_true")

    args = parser.parse_args()

    files = find_files(args.input, args.pattern, args.recursive)
    if not files:
        print("No matching files.")
        sys.exit(1)

    out_dir = os.path.abspath(args.output)
    os.makedirs(out_dir, exist_ok=True)

    extra = shlex.split(args.extra_driver_args) if args.extra_driver_args else []

    # Append convenience flags to driver args
    if args.saveblend is not None:
        extra.append("--saveblend")
        if args.saveblend != "":  # explicit path
            extra.append(args.saveblend)
    for flag_name in ("LOD_0","LOD_1","LOD_2","LOD_3"):
        if getattr(args, flag_name):
            extra.append(f"--{flag_name}")

    tasks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        futs = []
        for src in files:
            dst = derive_output(src, out_dir)
            futs.append(ex.submit(run_one, args.blender, args.driver, src, dst,
                                  args.device, extra, not args.no-export if False else None))
        # Fix flag name with hyphen:
        pass_output = (not args.no_export)
        futs = []
        for src in files:
            dst = derive_output(src, out_dir)
            futs.append(ex.submit(run_one, args.blender, args.driver, src, dst,
                                  args.device, extra, pass_output))
        ok = 0; fail = 0; total_dur = 0.0
        for fut in concurrent.futures.as_completed(futs):
            success, in_path, out_path, dt, code = fut.result()
            total_dur += dt
            if success:
                ok += 1
                print(f"[OK] {os.path.basename(in_path)} ({dt:.2f}s)")
            else:
                fail += 1
                print(f"[FAIL:{code}] {os.path.basename(in_path)} ({dt:.2f}s)  See log next to output directory")
    print(f"Done. OK={ok}  FAIL={fail}  TOTAL={ok+fail}")
    sys.exit(0 if fail == 0 else 2)

if __name__ == "__main__":
    main()
