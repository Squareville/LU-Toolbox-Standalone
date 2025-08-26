# lu_batch.py
# Runs OUTSIDE Blender. Walks files or uses a single file, and spawns one Blender background
# process per input, invoking lu_batch_driver.py. Cross-platform.
#
# Example:
#   python lu_batch.py --input "D:\models" --output "D:\out" --device optix \
#       --blender "C:\Program Files\Blender Foundation\Blender 3.1\blender.exe" \
#       --driver "D:\tools\lu_batch_driver.py" --jobs 1 --recursive
#
import os, sys, argparse, subprocess, fnmatch, shlex, concurrent.futures, pathlib, time

def find_files(root, patterns, recursive=False):
    root = os.path.abspath(root)
    pats = [p.strip() for p in patterns.split(";") if p.strip()]
    matches = []
    if os.path.isfile(root):
        if any(fnmatch.fnmatch(root.lower(), p.lower()) for p in pats):
            return [root]
        # If a single file given without match restriction, accept
        if not pats:
            return [root]
        return []
    if recursive:
        walker = os.walk(root)
    else:
        # one level
        def one_level_walk(top):
            yield top, next(os.walk(top))[1], next(os.walk(top))[2]
        walker = os.walk(root)
    for dirpath, dirnames, filenames in walker:
        for f in filenames:
            full = os.path.join(dirpath, f)
            if any(fnmatch.fnmatch(f.lower(), p.lower()) for p in pats):
                matches.append(full)
        if not recursive:
            break
    return matches

def derive_output(in_path, out_root):
    stem = os.path.splitext(os.path.basename(in_path))[0]
    return os.path.abspath(os.path.join(out_root, stem + ".nif"))

def run_one(blender, driver, in_path, out_path, device, extra_driver_args):
    cmd = [
        blender, "-b", "--factory-startup",
        "--python", driver, "--",
        "--input", in_path,
        "--output", out_path,
        "--device", device,
    ] + extra_driver_args
    print("==> Running:", " ".join(shlex.quote(c) for c in cmd))
    t0 = time.time()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    dt = time.time() - t0
    success = (proc.returncode == 0)
    # Write per-file log next to output
    log_path = out_path + (".ok.log" if success else ".err.log")
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
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda", "optix"])
    parser.add_argument("--blender", required=True, help="Path to blender executable")
    parser.add_argument("--driver", required=True, help="Path to lu_batch_driver.py")
    parser.add_argument("--pattern", default="*.lxf;*.lxfml", help="Semicolon-separated glob(s)")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--jobs", type=int, default=1, help="Parallel conversions")
    parser.add_argument("--extra-driver-args", default="", help="Pass-through args, e.g. --extra-driver-args \"--process-prop scene.lu_toolbox.use_gpu_process=True\"")
    args = parser.parse_args()

    files = find_files(args.input, args.pattern, args.recursive)
    if not files:
        print("No matching files.")
        sys.exit(1)

    os.makedirs(os.path.abspath(args.output), exist_ok=True)
    extra = shlex.split(args.extra_driver_args) if args.extra_driver_args else []

    tasks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        futs = []
        for src in files:
            dst = derive_output(src, args.output)
            futs.append(ex.submit(run_one, args.blender, args.driver, src, dst, args.device, extra))
        ok = 0; fail = 0; total_dur = 0.0
        for fut in concurrent.futures.as_completed(futs):
            success, in_path, out_path, dt, code = fut.result()
            total_dur += dt
            if success:
                ok += 1
                print(f"[OK] {os.path.basename(in_path)} -> {os.path.basename(out_path)}  ({dt:.2f}s)")
            else:
                fail += 1
                print(f"[FAIL:{code}] {os.path.basename(in_path)}  ({dt:.2f}s)  See log: {out_path}.err.log")
    print(f"Done. OK={ok}  FAIL={fail}  TOTAL={ok+fail}")
    sys.exit(0 if fail == 0 else 2)

if __name__ == "__main__":
    main()
