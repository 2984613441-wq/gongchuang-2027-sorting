#!/bin/bash
# Y 轴 3 次 2cm，交替方向避免累计顶到机械硬端（无限位开关）
# Y 正方向 = DIR1
set -u
for d in DIR1 DIR0 DIR1; do
  echo "### Y $d  1600 steps (20mm) ###"
  python3 /home/pi/pi_verify_timfix.py Y "$d" 1600 500
  sleep 3
done
echo "### Y 3 RUNS DONE ###"
