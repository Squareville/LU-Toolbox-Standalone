Use Blender 3.1 with niftools for LEGO Universe and LU Toolbox installed.

Current working cmd example:

"C:\Program Files\Blender Foundation\Blender 3.1\blender.exe" -b --factory-startup --python "V:\Squareville\Software\Tools\LU-Toolbox_Standalone\lu_batch_driver.py" -- --input "V:\Squareville\Assets\BrickModels\Official\Themes\Sculptures\3724_lego_dragon.lxf" --output "V:\Squareville\Assets\BrickModels\Official\Themes\Sculptures\3724_lego_dragon.nif" --brickdb "C:\LEGO Universe Clients\fullclient-maindev\res" --device cpu

CPU, CUDA, and OptiX are all available, depending on your hardware. OptiX is recommended for RTX GPUs and is the fastest option. CUDA and OptiX take time to initialize the first time around, but after that will give you significantly faster processing time compared to CPU. Currently, enabling CUDA or OptiX will force all available GPUs to be active, including integrated graphics. To circumvent this, you can opt for --device auto, and setup your device preferences directly inside Blender like you would normally. This is useful if you have multiple GPUs but only want to use one for processing models, or you have integrated graphics that you want to disable. If you pass --device auto, it's recommended that you do not pass --factory-startup, as this will launch headless Blender with your preferences reset. Device auto is recommended in general for robustness.

Arguments:
--device auto
--device cpu
--device cuda
--device optix
--factory-startup
