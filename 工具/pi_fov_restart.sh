#!/bin/bash
# 重开视野实测。pkill 的模式不能出现在调用方的 ssh 命令行里，所以放脚本里。
pkill -9 -f pi_fov_probe 2>/dev/null
sleep 1
rm -f /tmp/fov.log
nohup timeout -s INT 300 python3 -u /home/pi/pi_fov_probe.py 1 > /tmp/fov.log 2>&1 &
sleep 5
echo "=== 已启动（240 秒）—— 前几行 ==="
head -20 /tmp/fov.log
echo "=== 现在开始挪物块！ ==="
