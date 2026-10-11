#!/bin/bash
# 停掉占用 8765 的链路进程，然后跑相机视野实测（只碰树莓派 + 摄像头，不碰 STM32）
pkill -f 'deploy/run_chain.py' 2>/dev/null
sleep 2
if pgrep -f 'deploy/run_chain.py' >/dev/null 2>&1; then
    echo "run_chain 还在，强杀"; pkill -9 -f 'deploy/run_chain.py'; sleep 1
fi
echo "8765 占用情况:"
ss -tlnp 2>/dev/null | grep 8765 || echo "  空闲"
echo
python3 /home/pi/pi_camera_probe.py "${1:-40}"
