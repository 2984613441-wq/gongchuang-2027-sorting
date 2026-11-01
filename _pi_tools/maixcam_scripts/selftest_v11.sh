#!/bin/sh
# 在 MaixCAM 上自测 yolo_v11_cn_view.py：后台跑 12 秒，然后杀掉并打印日志
# 用法：Get-Content ... | ssh root@172.20.10.9 "sh -s"

echo "=== 1) 释放相机 ==="
killall launcher_daemon 2>/dev/null
sleep 1
REMAIN=$(ps aux 2>/dev/null | grep launcher_daemon | grep -v grep | wc -l)
echo "  launcher_daemon 剩余: $REMAIN"

echo
echo "=== 2) 后台跑 12 秒 ==="
cd /root || exit 1
rm -f /tmp/v11_test.log
python3 yolo_v11_cn_view.py > /tmp/v11_test.log 2>&1 &
PID=$!
echo "  PID=$PID"
sleep 12
kill "$PID" 2>/dev/null
sleep 1
kill -9 "$PID" 2>/dev/null
echo "  已停止"

echo
echo "=== 3) 日志 ==="
if [ -f /tmp/v11_test.log ]; then
    grep -Ev 'Maix Comm|pinmap|listening|^$' /tmp/v11_test.log | head -45
else
    echo "  ❌ 没有日志"
fi

echo
echo "=== 4) 进程清理确认 ==="
ps aux 2>/dev/null | grep 'yolo_v11' | grep -v grep | wc -l
