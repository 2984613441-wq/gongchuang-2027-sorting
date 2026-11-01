#!/bin/sh
# 只保留脚本自身的输出行（过滤掉 sensor/ISP 的启动噪声）

killall launcher_daemon 2>/dev/null
sleep 1
cd /root || exit 1
rm -f /tmp/v11_test2.log
python3 yolo_v11_cn_view.py > /tmp/v11_test2.log 2>&1 &
PID=$!
sleep 15
kill "$PID" 2>/dev/null
sleep 1
kill -9 "$PID" 2>/dev/null

echo "=== 脚本自身输出 ==="
grep -E '六类|MODEL|FRAME|字体|camera OK|display OK|YOLO11|预热|开始|帧 |FPS|个|正方体|长方体|圆柱|五棱柱|圆锥|正四面体|结束|Traceback|Error|❌|⚠️' /tmp/v11_test2.log | head -40

echo
echo "=== 是否出现异常 ==="
grep -cE 'Traceback|Error|❌' /tmp/v11_test2.log 2>/dev/null || echo 0
