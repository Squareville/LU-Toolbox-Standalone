#!/usr/bin/env bash
# convert_lu.sh - POSIX helper for a single file
# Usage:
#   ./convert_lu.sh /path/to/blender /path/to/lu_batch_driver.py /in/foo.lxf /out/foo.nif optix
BLENDER_EXE="$1"
DRIVER_PY="$2"
IN_FILE="$3"
OUT_FILE="$4"
DEVICE="$5"
"$BLENDER_EXE" -b --factory-startup --python "$DRIVER_PY" -- --input "$IN_FILE" --output "$OUT_FILE" --device "$DEVICE"
