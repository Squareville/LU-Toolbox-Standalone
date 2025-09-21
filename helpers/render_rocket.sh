#!/usr/bin/env bash
set -euo pipefail

# Drag & drop (or pass as $1) an .lxf or .lxfml

# --- Config: update these if your paths change ---
BLENDER=${BLENDER:-/usr/bin/blender}
DRIVER_LU=${DRIVER_LU:-/path/to/LU-Toolbox-Standalone/lu_batch_driver.py}
DRIVER_UGC=${DRIVER_UGC:-/path/to/LU-Toolbox-Standalone/ugc_render_driver.py}
BRICKDB=${BRICKDB:-/path/to/fullclient-maindev/res}
# -------------------------------------------------

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 /path/to/file.lxfml"
  exit 1
fi

if [[ ! -f "$1" ]]; then
  echo "Source not found: $1"
  exit 2
fi

# Source parts
SRC="$(realpath "$1")"
SRC_DIR="$(dirname "$SRC")"
SRC_BASE="$(basename "$SRC")"
SRC_NAME="${SRC_BASE%.*}"

# Outputs in same directory with same basename
OUT_NIF="$SRC_DIR/$SRC_NAME.nif"
OUT_BLEND="$SRC_DIR/$SRC_NAME.blend"
# UGC output MUST be a real filename to avoid stem oddities
UGC_OUT_PNG="$SRC_DIR/$SRC_NAME.png"

# --- Nuke any pre-existing stray file literally named "NIF" in the source folder ---
rm -f "$SRC_DIR/NIF"

echo "==== [1/2] LXF->NIF (headless) ===="
if ! "$BLENDER" -b --factory-startup --python "$DRIVER_LU" -- \
  --input "$SRC" \
  --brickdb "$BRICKDB" \
  --device optix \
  --saveblend \
  --LOD_0
then
  echo "[ERROR] LXF->NIF failed."
  exit 3
fi

# --- If step 1 created a stray "NIF", remove it now ---
rm -f "$SRC_DIR/NIF"

echo "==== [2/2] UGC Render (UI mode) ===="
# NOTE: UGC needs UI context (no -b). Make sure you have a DISPLAY/X available.
if ! "$BLENDER" --python "$DRIVER_UGC" -- \
  --input "$OUT_BLEND" \
  --output "$UGC_OUT_PNG" \
  --device optix \
  --type-rocket \
  --res 128 \
  --framingscale 1.03 \
  --dds \
  --deleteblend
then
  echo "[ERROR] UGC Render failed."
  exit 4
fi

# --- Final sweep: remove any stray "NIF" one last time ---
rm -f "$SRC_DIR/NIF"

echo "Done."
