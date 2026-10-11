#!/bin/bash
# X 轴 3 次 2cm，交替方向避免累计顶到机械硬端（无限位开关）
set -u
for d in DIR0 DIR1 DIR0; do
  echo "### X $d  1600 steps (20mm) ###"
  python3 /home/pi/pi_verify_timfix.py X "$d" 1600 500
  sleep 3
done
echo "### X 3 RUNS DONE ###"
