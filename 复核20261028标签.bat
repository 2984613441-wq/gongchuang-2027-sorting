@echo off
chcp 65001 >nul
rem ============================================================
rem   20261028 批次标签复核 - 用 labelImg 打开
rem   images : _review_20261028\images   (179 张)
rem   labels : _review_20261028\labels   (v7 预标注 459 框)
rem   类别   : cube / cuboid / cylinder / pentagonal_prism / cone / tetrahedron
rem
rem   ⚠️ 这些框是 v7 自动预标的，不是你从零标
rem   ⇒ 只需改错的、补漏的、删误检的
rem ============================================================

set ENV=D:\Anaconda\envs\labelimg

rem labelImg 需要这些才能在 Windows 上正常启动
set PATH=%ENV%;%ENV%\Library\bin;%ENV%\Scripts;%PATH%
set QT_PLUGIN_PATH=%ENV%\Library\plugins

cd /d "C:\Users\29845\Desktop\工创赛"

rem 保存目录里必须有 classes.txt，否则 labelImg 会写错类别
copy /y _review_20261028\classes.txt _review_20261028\labels\classes.txt >nul

echo ============================================================
echo   20261028 batch review  (v7 pre-labeled)
echo   classes: cube cuboid cylinder pentagonal_prism cone tetrahedron
echo ============================================================
echo.
echo   Tips:
echo     1. double-click an image in the left File List to open
echo     2. wrong class  -> right-click the box, pick the right one
echo     3. wrong shape  -> drag / resize the box
echo     4. extra box    -> select it, press Delete
echo     5. missing box  -> press W, draw it, pick the class
echo     6. press Ctrl+S after each image
echo     7. empty label  = v7 found nothing (confirm it is a junk frame)
echo.
echo   Progress: 179 images
echo ============================================================
echo.

start "" "%ENV%\Scripts\labelImg.exe" _review_20261028\images _review_20261028\predefined_classes.txt _review_20261028\labels
