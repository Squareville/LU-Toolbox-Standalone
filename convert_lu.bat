@echo off
REM convert_lu.bat - Windows helper for a single file
REM Usage:
REM   convert_lu.bat "V:\Dropbox\Squareville\Software\Tools\blender-3.1.0-windows-x64\blender.exe" "V:\Dropbox\Squareville\Software\Tools\LU-Toolbox_Standalone\lu_batch_driver.py" "V:\Dropbox\Squareville\Assets\BrickModels\Pets\Quadruped\pq_pony.lxfml" "V:\Dropbox\Squareville\Assets\BrickModels\Pets\Quadruped/pq_pony.nif" cpu

set BLENDER_EXE=%~1
set DRIVER_PY=%~2
set IN_FILE=%~3
set OUT_FILE=%~4
set DEVICE=%~5

"%BLENDER_EXE%" -b --factory-startup --python "%DRIVER_PY%" -- --input "%IN_FILE%" --output "%OUT_FILE%" --device %DEVICE%
