#!/bin/bash
# 重启真实链路（含 --start-round）。run_chain.py 会在打开串口前要求输入 HOME；
# 因此本脚本故意前台运行，不能再用 nohup 把确认提示藏进 /tmp/chain.log。
set -o pipefail
cd /home/pi/电控 || exit 1
pkill -f 'deploy/run_chain.py' 2>/dev/null
sleep 2
rm -f /tmp/chain.log
PYTHONPATH=src python3 deploy/run_chain.py \
    --config /home/pi/sorting_config.ini \
    --port /dev/serial0 \
    --image-dir /home/pi/images \
    --names-file /home/pi/电控/deploy/names.json \
    --frame-output fb0 \
    --font /usr/share/fonts/truetype/wqy/wqy-zenhei.ttc \
    --round-id r1 --round-task-id 1 \
    --start-round 2>&1 | tee /tmp/chain.log
