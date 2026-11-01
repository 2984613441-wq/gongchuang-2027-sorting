@echo off
chcp 65001 >nul
setlocal
set "ENV=D:\Anaconda\envs\labelimg"
set "EXE=%ENV%\Scripts\labelImg.exe"
set "PATH=%ENV%;%ENV%\Library\mingw-w64\bin;%ENV%\Library\usr\bin;%ENV%\Library\bin;%ENV%\Scripts;%PATH%"
set "QT_PLUGIN_PATH=%ENV%\Library\plugins"
set "PYTHONIOENCODING=utf-8"
set "WS=%~dp0_label_review_all"
set "CLS=%WS%\classes_6c.txt"
set "IMG=%WS%\images"
set "SAVE=%WS%\labels"
if not exist "%EXE%" goto noexe
if not exist "%IMG%" goto noimg
if not exist "%SAVE%" mkdir "%SAVE%"
copy /y "%CLS%" "%SAVE%\classes.txt" >nul
echo 正在启动 labelImg ...
echo 第一次打开请把左侧 PascalVOC 切换成 YOLO
start "" "%EXE%" "%IMG%" "%CLS%" "%SAVE%"
goto done
:noexe
echo ERROR labelImg.exe not found
pause
goto done
:noimg
echo ERROR images dir not found
pause
:done
endlocal
