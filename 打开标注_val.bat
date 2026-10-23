@echo off
rem open labelImg for val split (237 images)
setlocal
set "KIT=%~dp0"
call "%KIT%_label_kit\start_val.bat"
endlocal
