@echo off
rem ============================================================
rem  6 类版 labelImg 启动器（白托盘标注）
rem  机制抄自 _label_kit\start_train.bat（已实测跑通的那套），只改三处：
rem    1) classes 换成 6 类（含 cone，去掉 hexagonal/triangular/square_pyramid）
rem    2) IMG 指向 _label_ws_6c\images（40 张白托盘实拍）
rem    3) SAVE 指向 _label_ws_6c\labels（与图分开，避免 classes.txt 被当标签）
rem
rem  FIX 1: 必须把 conda env 目录前置进 PATH，否则 Qt 加载不到 jpeg 插件
rem         （症状：Open Dir 后 0 张图 / 画布空白）
rem  FIX 2: 必须在 SAVE 目录里放 classes.txt，否则 YoloReader 抛
rem         FileNotFoundError，PyQt5 qFatal 直接杀进程（症状：闪退）
rem ============================================================
setlocal
set "ENV=D:\Anaconda\envs\labelimg"
set "EXE=%ENV%\Scripts\labelImg.exe"
set "PATH=%ENV%;%ENV%\Library\mingw-w64\bin;%ENV%\Library\usr\bin;%ENV%\Library\bin;%ENV%\Scripts;%PATH%"
set "QT_PLUGIN_PATH=%ENV%\Library\plugins"
set "PYTHONIOENCODING=utf-8"

set "ROOT=%~dp0"
set "WS=%ROOT%_label_ws_6c"
set "CLS=%WS%\classes_6c.txt"
set "IMG=%WS%\images"
set "SAVE=%WS%\labels"

if not exist "%EXE%" goto :noexe
if not exist "%IMG%" goto :noimg
if not exist "%SAVE%" mkdir "%SAVE%"

rem FIX 2 本体：把 6 类 classes.txt 放进保存目录
copy /y "%CLS%" "%SAVE%\classes.txt" >nul

echo ============================================================
echo   6 类标注  (YOLO 格式)
echo ============================================================
echo.
echo   IMG  = %IMG%
echo   SAVE = %SAVE%
echo   CLS  = %CLS%
echo.
echo   类别顺序:
echo     0 cube              正方体
echo     1 cuboid            长方体
echo     2 cylinder          圆柱
echo     3 pentagonal_prism  五棱柱
echo     4 cone              圆锥    ^<-- 最缺，优先标
echo     5 tetrahedron       正四面体
echo.
echo   ⚠️ 第一次打开务必: 左侧 [PascalVOC] 点一下切成 [YOLO]
echo.
pause
echo.
start "" "%EXE%" "%IMG%" "%CLS%" "%SAVE%"
goto :eof

:noexe
echo [ERROR] labelImg.exe not found: %EXE%
pause
goto :eof

:noimg
echo [ERROR] image dir not found: %IMG%
pause
goto :eof
