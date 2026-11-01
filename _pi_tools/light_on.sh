#!/bin/bash
# 在树莓派上执行：检查 STM32 + 打开补光灯
set -u
echo "=== 1) STM32 PING ==="
OUT=$(timeout 8 python3 /home/pi/pi_light.py "PING" 2>&1)
echo "$OUT" | head -n 5

echo
echo "=== 2) 补光灯当前状态 ==="
timeout 8 python3 /home/pi/pi_light.py "LIGHT?" 2>&1 | head -n 5

echo
echo "=== 3) 打开补光灯（默认暖白）==="
timeout 8 python3 /home/pi/pi_light.py "LIGHT ON" 2>&1 | head -n 5

echo
echo "=== 4) 确认已开 ==="
timeout 8 python3 /home/pi/pi_light.py "LIGHT?" 2>&1 | head -n 5
