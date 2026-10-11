#!/bin/bash
# 先预检物块是否在标定工作区内；通过就直接起链路，不通过就只打印预检结果。
cd /home/pi/电控 || exit 1
pkill -f 'deploy/run_chain.py' 2>/dev/null
sleep 1

OUT=/tmp/obj_check.txt
PYTHONPATH=src python3 /home/pi/pi_check_object.py 5 > "$OUT" 2>&1
echo "===== 预检结果 ====="
cat "$OUT"
echo

# 判据：出现 "可用" 且没有出现 "超出工作区"
if grep -q '可用' "$OUT" && ! grep -q '超出工作区' "$OUT"; then
    echo ">>> 预检通过，起链路"
    echo
    sh /home/pi/pi_repro_and_read.sh
else
    echo ">>> 预检未通过（物块越界或视觉没在发），拒绝启动链路"
    exit 1
fi
