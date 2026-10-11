#!/bin/sh
# 只读串口监听：静默 N 秒，把收到的字节全部落盘再打印。
# 用法： sh pi_listen_serial.sh [秒数] [设备] [波特率]
# 只做 cat 读，不向板上写任何字节。
SECS="${1:-120}"
DEV="${2:-/dev/serial0}"
BAUD="${3:-115200}"

stty -F "$DEV" "$BAUD" raw -echo 2>/dev/null
rm -f /tmp/rx_capture.bin
timeout "$SECS" cat "$DEV" > /tmp/rx_capture.bin 2>/dev/null

BYTES=$(wc -c < /tmp/rx_capture.bin)
echo "captured_bytes=$BYTES"
echo "window_seconds=$SECS"
echo "device=$DEV baud=$BAUD"

if [ "$BYTES" -gt 0 ]; then
    echo "--- od -c (前 40 行) ---"
    od -c /tmp/rx_capture.bin | head -40
    echo "--- 可打印文本 ---"
    tr -d '\000' < /tmp/rx_capture.bin | head -c 1200
    echo
else
    echo "--- 窗口内零字节 ---"
fi
