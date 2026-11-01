@echo off
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
echo ================================================================
echo   步骤 2 / 3 ： 标 注 后 校 验
echo ================================================================
echo.
echo  会检查：标签格式、类别范围、坐标是否 0~1、框大小是否离谱
echo  并统计各类实例数。不会修改任何文件。
echo.
pause
echo.
"C:\Users\29845\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" "..\_pi_tools\after_label.py" --check-only
echo.
echo ================================================================
echo  看完上面的结果：
echo    * 有问题  -^> 回 labelImg 修，或删掉对应图片
echo    * 没问题  -^> 双击 3_合并并重训.bat
echo ================================================================
pause
