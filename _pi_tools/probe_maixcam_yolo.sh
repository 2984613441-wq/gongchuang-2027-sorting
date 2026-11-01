#!/bin/bash
# 查 MaixCAM 上的模型与 MaixPy NPU/YOLO 能力
set -u
echo "=== 1) /root 下的模型文件 ==="
find /root -maxdepth 3 \( -name "*.cvimodel" -o -name "*.mud" -o -name "*.onnx" \) 2>/dev/null | head -n 20
echo
echo "=== 2) /maixapp 下的模型 ==="
find /maixapp -maxdepth 4 \( -name "*.cvimodel" -o -name "*.mud" \) 2>/dev/null | head -n 15
echo
echo "=== 3) maix.nn 能否 import ==="
python3 -c "from maix import nn; print('  maix.nn OK')" 2>&1 | tail -n 2
echo
echo "=== 4) YOLO11 适配器是否可用 ==="
python3 -c "from maix.nn import YOLOv11; print('  YOLOv11 OK')" 2>&1 | tail -n 2
echo
echo "=== 5) 已有 YOLO 相关脚本 ==="
find /root -maxdepth 2 -name "*yolo*" -o -maxdepth 2 -name "*detect*" 2>/dev/null | head -n 10
echo
echo "=== 6) 相机/显示模块 ==="
python3 -c "from maix import camera, display, image, app; print('  camera/display OK')" 2>&1 | tail -n 2
