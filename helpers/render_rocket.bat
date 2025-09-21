@echo off
setlocal

REM Drag & drop an .lxf or .lxfml onto this .bat (or pass as %1)

REM --- Config: update these if your paths change ---
set "BLENDER=C:\Program Files\Blender Foundation\Blender 3.1\blender.exe"
set "DRIVER_LU=V:\Repositories\Squareville\LU-Toolbox-Standalone\lu_batch_driver.py"
set "DRIVER_UGC=V:\Repositories\Squareville\LU-Toolbox-Standalone\ugc_render_driver.py"
set "BRICKDB=Q:\LEGO Universe Master Folder\LEGO Universe Clients\fullclient-maindev\res"
REM -------------------------------------------------

if "%~1"=="" (
  echo Usage: drag an .lxf or .lxfml file onto this .bat
  exit /b 1
)

if not exist "%~1" (
  echo Source not found: %~1
  exit /b 2
)

REM Source parts
set "SRC=%~1"
set "SRC_DIR=%~dp1"
set "SRC_NAME=%~n1"
set "SRC_EXT=%~x1"

REM Outputs in same directory with same basename
set "OUT_NIF=%SRC_DIR%%SRC_NAME%.nif"
set "OUT_BLEND=%SRC_DIR%%SRC_NAME%.blend"
REM UGC output MUST be a real filename to avoid stem oddities
set "UGC_OUT_PNG=%SRC_DIR%%SRC_NAME%.png"

REM --- Nuke any pre-existing stray file literally named "NIF" in the source folder ---
if exist "%SRC_DIR%NIF" del /f /q "%SRC_DIR%NIF" >nul 2>&1

echo ==== [1/2] LXF->NIF (headless) ====
"%BLENDER%" -b --factory-startup --python "%DRIVER_LU%" -- ^
  --input "%SRC%" ^
  --brickdb "%BRICKDB%" ^
  --device optix ^
  --saveblend ^
  --LOD_0

if errorlevel 1 (
  echo [ERROR] LXF->NIF failed. See console above.
  exit /b 3
)

REM --- If step 1 created a stray "NIF", remove it now ---
if exist "%SRC_DIR%NIF" del /f /q "%SRC_DIR%NIF" >nul 2>&1

echo ==== [2/2] UGC Render (UI mode) ====
"%BLENDER%" --python "%DRIVER_UGC%" -- ^
  --input "%OUT_BLEND%" ^
  --output "%UGC_OUT_PNG%" ^
  --device optix ^
  --type-rocket ^
  --res 128 ^
  --framingscale 1.03 ^
  --dds ^
  --deleteblend

if errorlevel 1 (
  echo [ERROR] UGC Render failed. See console above.
  exit /b 4
)

REM --- Final sweep: remove any stray "NIF" one last time ---
if exist "%SRC_DIR%NIF" del /f /q "%SRC_DIR%NIF" >nul 2>&1

echo Done.
exit /b 0
