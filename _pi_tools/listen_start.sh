#!/bin/bash
# 启动视觉数据监听（后台，30 秒）
set -u
pkill -f vision_listen.py 2>/dev/null
sleep 0.5
rm -f /tmp/listen.log
nohup python3 /tmp/vision_listen.py 8765 30 > /tmp/listen.log 2>&1 &
sleep 2
echo "--- 监听器已启动 ---"
cat /tmp/listen.log
