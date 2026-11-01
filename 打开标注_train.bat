@echo off
rem Open labelImg for the TRAIN split (image/label counts are printed by start_train.bat).
setlocal
set "KIT=%~dp0"
call "%KIT%_label_kit\start_train.bat"
endlocal
