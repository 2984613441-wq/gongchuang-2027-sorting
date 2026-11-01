@echo off
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
echo ================================================================
echo   步骤 3 / 3 ： 合 并 数 据 集 并 重 训
echo ================================================================
echo.
echo  1) 把标注好的新图合并进 _dataset_yolo_6c_v2（保留原 471 张）
echo  2) 直接开始训练 120 epoch
echo.
echo  ⚠️ 训练约 10 分钟，期间不要关窗口
echo.
pause
echo.
echo ---- 第 1 步：合并 ----
"C:\Users\29845\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" "..\_pi_tools\after_label.py" --overwrite
if errorlevel 1 goto :fail
echo.
echo ---- 第 2 步：训练 ----
"C:\Users\29845\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" "..\_pi_tools\train_6class.py" --dataset _dataset_yolo_6c_v2 --epochs 120 --name yolo11n_6c_v2 --batch 32 --imgsz 448
if errorlevel 1 goto :fail
echo.
echo ================================================================
echo   ✅ 全部完成
echo   权重: _runs\yolo11n_6c_v2\weights\best.pt
echo   混淆矩阵: _runs\yolo11n_6c_v2\confusion_matrix_normalized.png
echo ================================================================
pause
exit /b 0
:fail
echo.
echo ❌ 上一步失败了，看上面的报错
pause
exit /b 1
