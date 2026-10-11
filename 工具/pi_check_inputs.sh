#!/bin/bash
pkill -f 'deploy/run_chain.py' 2>/dev/null
sleep 2
echo "=== INPUTS / STATUS ==="
python3 /home/pi/pi_ask_stm32.py 2>&1 | grep -E "PONG|INPUTS|APP_STATE|STATUS|SAFE" | head -6
