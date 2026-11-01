@echo off
chcp 65001 >nul
rem ============================================================
rem   v6 标签复核 - 用 labelImg 打开
rem   images : _review_v6\images
rem   labels : _review_v6\labels
rem   类别   : cube / cuboid / cylinder / pentagonal_prism / cone / tetrahedron
rem ============================================================

set ENV=D:\Anaconda\envs\labelimg

rem labelImg 需要这些才能在 Windows 上正常启动
set PATH=%ENV%;%ENV%\Library\bin;%ENV%\Scripts;%PATH%
set QT_PLUGIN_PATH=%ENV%\Library\plugins

cd /d "C:\Users\29845\Desktop\工创赛"

rem 保存目录里必须有 classes.txt，否则 labelImg 会写错类别
copy /y _review_v6\classes.txt _review_v6\labels\classes.txt >nul

echo ============================================================
echo   v6 标签复核
echo   类别：cube cuboid cylinder pentagonal_prism cone tetrahedron
echo ============================================================
echo.
echo   操作提示：
echo     1. 左侧 File List 双击图片打开
echo     2. 发现类别标错 - 右键框选择正确类别
echo     3. 发现框位置不对 - 拖动/缩放
echo     4. 发现多余框 - 选中按 Delete
echo     5. 每次改完按 Ctrl+S 保存
echo     6. 改完关掉窗口，告我一声
echo.
echo   进度：216 张
echo ============================================================
echo.

start "" "%ENV%\Scripts\labelImg.exe" _review_v6\images _review_v6\predefined_classes.txt _review_v6\labels
