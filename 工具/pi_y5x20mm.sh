#!/bin/bash
# Y 轴 5 次 2cm 测试，交替方向避免累计跑飞（无限位开关）
set -u
for i in 1 2 3 4 5; do
  if [ $((i % 2)) -eq 1 ]; then
    D=DIR1
  else
    D=DIR0
  fi
  echo "### MOVE $i/5  Y $D  1600 steps (20mm) ###"
  python3 /home/pi/pi_verify_timfix.py Y "$D" 1600 500
  sleep 1
done
echo "### ALL DONE ###"
