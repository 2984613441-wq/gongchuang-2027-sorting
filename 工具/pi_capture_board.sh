#!/bin/sh
# 被动监听串口 N 秒（不发任何字节），统计板子是否在复位。
# 判据：ec_app.c:598 每次启动都会打印一条 "BOOT SAFE HSI=16000000 ..."，
#       所以 BOOT SAFE 出现 >1 次 = 板子在反复复位。
# 另外统计 1Hz ASCII STATUS 的 APP_STATE 取值分布（ec_diag.c:684-690 每 1000ms 发一条）。
SECS="${1:-30}"
stty -F /dev/serial0 115200 raw -echo 2>/dev/null
rm -f /tmp/board_capture.txt
timeout "$SECS" cat /dev/serial0 > /tmp/board_capture.txt 2>/dev/null

BYTES=$(wc -c < /tmp/board_capture.txt)
echo "captured_bytes=$BYTES  window_seconds=$SECS"

echo "--- BOOT SAFE 出现次数（>=2 即板子在复位）---"
grep -c 'BOOT SAFE' /tmp/board_capture.txt 2>/dev/null || echo 0

echo "--- BOOT SAFE 原文 ---"
grep 'BOOT SAFE' /tmp/board_capture.txt 2>/dev/null | head -5

echo "--- APP_STATE 取值分布 ---"
grep -o 'APP_STATE=[A-Z_]*' /tmp/board_capture.txt 2>/dev/null | sort | uniq -c

echo "--- INPUTS 行（如有）---"
grep -o 'INPUTS RAW=[0-9A-F]* STABLE=[0-9A-F]* ACTIVE=[0-9A-F]*' /tmp/board_capture.txt 2>/dev/null | sort | uniq -c

echo "--- 前 400 字节 ---"
head -c 400 /tmp/board_capture.txt
echo ""
echo "--- 末 300 字节 ---"
tail -c 300 /tmp/board_capture.txt
echo ""
