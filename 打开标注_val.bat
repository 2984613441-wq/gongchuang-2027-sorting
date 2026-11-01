@echo off
rem Open labelImg for the VAL split (image/label counts are printed by start_val.bat).
setlocal
set "KIT=%~dp0"
call "%KIT%_label_kit\start_val.bat"
endlocal
