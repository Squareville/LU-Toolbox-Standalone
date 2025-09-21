#!/usr/bin/env bash
set -euo pipefail

# Usage: ./lu_pipeline.sh /path/to/model.lxfml

# --- Config: update these to match your system ---
BLENDER="${BLENDER:-blender}"   # or absolute path like /usr/bin/blender
DRIVER_LU="${DRIVER_LU:-/path/to/LU-Toolbox-Standalone/lu_batch_driver.py}"
DRIVER_UGC="${DRIVER_UGC:-/path/to/LU-Toolbox-Standalone/ugc_render_driver.py}"
BRICKDB="${BRICKDB:-/mnt/lu/fullclient-maindev/res}"  # <-- adjust for Linux path
# --------------------------------------------------

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 /path/to/file.lxfml"
  exit 1
fi

SRC="$1"
if [[ ! -f "$SRC" ]]; then
  echo "Source not found: $SRC"
  exit 2
fi

SRC_DIR="$(dirname "$SRC")"
SRC_BASE="$(basename "$SRC")"
SRC_NAME="${SRC_BASE%.*}"
SRC_EXT="${SRC_BASE##*.}"

OUT_NIF="$SRC_DIR/$SRC_NAME.nif"
OUT_BLEND="$SRC_DIR/$SRC_NAME.blend"
UGC_OUT_STEM="$SRC_DIR/$SRC_NAME"

echo "==== [1/2] LXF->NIF (headless) ===="
"$BLENDER" -b --factory-startup --python "$DRIVER_LU" -- \
  --input "$SRC" \
  --brickdb "$BRICKDB" \
  --device optix \
  --saveblend \
  --LOD_0

echo "==== [2/2] UGC Render (UI mode) ===="
# NOTE: No -b here; UGC needs UI context
"$BLENDER" --python "$DRIVER_UGC" -- \
  --input "$OUT_BLEND" \
  --output "$UGC_OUT_STEM" \
  --device optix \
  --type-rocket \
  --res 128 \
  --framingscale 1.03 \
  --dds \
  --deleteblend
