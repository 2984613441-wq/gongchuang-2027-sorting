@echo off
rem open labelImg for train split (949 images)
setlocal
set "KIT=%~dp0"
call "%KIT%_label_kit\start_train.bat"
endlocal
