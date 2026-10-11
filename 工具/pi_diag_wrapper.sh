#!/bin/bash
# 停掉链路进程后再跑串口诊断
# （pkill 的匹配串不能出现在 ssh 的那条命令行里，否则会连自己所在的 shell 一起杀）
pkill -f 'deploy/run_chain.py' 2>/dev/null
sleep 2
pgrep -af 'deploy/run_chain.py' | grep python3 && { echo "还有残留，强杀"; pkill -9 -f 'deploy/run_chain.py'; sleep 1; }
echo "链路进程已停。"
python3 /home/pi/pi_serial_diag.py
