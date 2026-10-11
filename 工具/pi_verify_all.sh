#!/bin/bash
# 烧录后综合验证：串口链路 + 输入状态 + APP_STATE
pkill -f 'deploy/run_chain.py' 2>/dev/null
sleep 2
echo "############ 1) 串口链路（只听 + PING）############"
python3 /home/pi/pi_serial_diag.py
echo
echo "############ 2) 命令应答 + INPUTS + APP_STATE ############"
python3 /home/pi/pi_ask_stm32.py
