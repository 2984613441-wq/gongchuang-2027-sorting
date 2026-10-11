#!/bin/bash
# 对比主机与树莓派的 electrical_control 文件清单，找出缺失/不一致
echo "=== 树莓派 rpi/*.py ==="
ls -1 /home/pi/电控/src/electrical_control/rpi/*.py 2>/dev/null | xargs -n1 basename | sort
echo
echo "=== 树莓派 顶层子包 ==="
ls -1 /home/pi/电控/src/electrical_control/ 2>/dev/null
echo
echo "=== 树莓派 全部 .py 数量 ==="
find /home/pi/电控/src/electrical_control -name '*.py' | wc -l
echo
echo "=== 是否有 __pycache__ 残留 ==="
find /home/pi/电控/src/electrical_control -name '__pycache__' -type d | wc -l
