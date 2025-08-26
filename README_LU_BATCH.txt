LU headless batch conversion (LXF/LXFML -> NIF for LEGO Universe)

Files:
- lu_batch_driver.py (run inside Blender via -b --python)
- lu_batch.py        (run in system Python; spawns Blender per file)
- convert_lu.bat     (Windows one-file helper)
- convert_lu.sh      (POSIX one-file helper)

Minimum example (single file):
  blender -b --factory-startup --python lu_batch_driver.py -- --input "in/foo.lxf" --output "out/foo.nif" --device optix

Batch example (folder):
  python lu_batch.py --input "in_dir" --output "out_dir" --device cuda --blender "/path/to/blender" --driver "/path/to/lu_batch_driver.py" --recursive --jobs 1

Notes:
- The driver enables LU Toolbox and NifTools add-ons by common module names. If your module ids differ, enable them in driver or via Blender UI once, then keep using --factory-startup (the driver enables best-effort at runtime).
- If no CUDA/OptiX GPUs are found, driver falls back to CPU and prints a warning.
- You can override operator ids with:
    --import-op  lu_toolbox.import_lxfml
    --process-op lu_toolbox.process_model
    --bake-op    lu_toolbox.bake_lighting
- You can force specific property sets:
    --process-prop scene.lu_toolbox.use_gpu_process=True
    --bake-prop    scene.lu_toolbox.use_gpu_bake=True
- Per-file logs are written next to the .nif as .ok.log or .err.log.

Current working cmd example:

"C:\Program Files\Blender Foundation\Blender 3.1\blender.exe" -b --factory-startup --python "V:\Dropbox\Squareville\Software\Tools\LU-Toolbox_Standalone\lu_batch_driver.py" -- --input "V:\Dropbox\Squareville\Assets\BrickModels\Official\Themes\Sculptures\3724_lego_dragon.lxf" --output "V:\Dropbox\Squareville\Assets\BrickModels\Official\Themes\Sculptures\3724_lego_dragon.nif" --brickdb "Q:\LEGO Universe Master Folder\LEGO Universe Clients\fullclient-maindev\res" --device cpu