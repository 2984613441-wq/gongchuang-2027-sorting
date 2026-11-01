@echo off
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
echo ================================================================
echo   步骤 1 / 3 ： 打 开 标 注 工 具
echo ================================================================
echo.
echo  类别顺序（标错整个数据集就废了，务必记住）：
echo.
echo    0 = cube              正方体
echo    1 = cuboid            长方体
echo    2 = cylinder          圆柱
echo    3 = pentagonal_prism  五棱柱
echo    4 = cone              圆锥   ^<-- 最缺，优先标
echo    5 = tetrahedron       正四面体
echo.
echo  第一次打开的必做设置：
echo    左侧工具栏点 [PascalVOC] 按钮  --^>  切换成 [YOLO]
echo    （不切会存成 XML，后面用不了）
echo.
echo  快捷键：
echo    W        画框
echo    D / A    下一张 / 上一张
echo    0~5      把选中的框改成对应类别
echo    Del      删除选中的框
echo    Ctrl+Z   撤销
echo    Ctrl+S   保存（一般自动保存）
echo.
echo  图在： _label_workspace\images\  （40 张白托盘实拍）
echo.
pause
echo.
"C:\Users\29845\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\Scripts\labelImg.exe" "%CD%\..\_label_workspace\images" "%CD%\..\_label_workspace\predefined_classes.txt" "%CD%\..\_label_workspace\images"
echo.
echo ================================================================
echo   标注结束。下一步：双击  2_标注后校验.bat
echo ================================================================
pause
